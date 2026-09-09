"""booking-gate — アクセス許可のある時間だけ Slack の会話を通すゲート。

受信1通ごとに ``pre_gateway_dispatch`` で判定する。判定材料はポーラーが書いた
``~/.hermes/booking-gate/reservations.json`` だけで、LLM は一切通らない。

判定の順序（最初に当たったところで決まる）:

  1. オーナー           → 通す（カレンダーを見ない。ここが最後の砦）
  2. アクセス許可表に有効なスロット     → 通す
  3. それ以外                   → 落とす（skip）＋ 案内を1回返す

Hermes 標準の認可（pairing）と2枚重ねで運用する。どちらが落ちても
「時間外の人が通る」にはならない。詳細は DESIGN.md を参照。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

def _hermes_root() -> Path:
    """Hermes の根っこ。**プロファイル配下の HERMES_HOME を吸収する。**

    gateway の plist は ``HERMES_HOME=~/.hermes/profiles/operator`` で動く一方、
    ポーラーは ``~/.hermes`` で動く。素直に HERMES_HOME を信じると、書く側と読む側で
    別のファイルを見て、許可が永久に届かない。根っこを1つに揃える。
    """
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    return home.parent.parent if home.parent.name == "profiles" else home


HERMES_HOME = _hermes_root()
GATE_HOME = Path(os.environ.get("BOOKING_GATE_HOME") or (HERMES_HOME / "booking-gate"))
CONFIG_PATH = GATE_HOME / "config.yaml"
RESERVATIONS_PATH = GATE_HOME / "reservations.json"
LOADED_PATH = GATE_HOME / "gate-loaded.json"  # ゲートが生きている証拠（doctor が見る）

NOTICE_INTERVAL_SEC = 600  # 同じ人への案内は10分に1回まで
DEFAULT_STALE_MINUTES = 5
DEFAULT_MAX_PER_HOUR = 40  # 1人あたり1時間の発言上限。ただ乗り（コスト）への歯止め

_cache: dict = {"config": None, "config_mtime": 0.0, "table": None, "table_mtime": 0.0}
_notified: dict[str, float] = {}
_recent: dict[str, list[float]] = {}  # user_id -> 直近の発言時刻（1時間ぶん）
_active: dict[str, dict] = {}  # user_id -> {"session_key": str, "end": datetime}


# ------------------------------------------------------------------ 読み込み


def _load_config() -> dict:
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        return _cache["config"] or {}
    if _cache["config"] is not None and mtime == _cache["config_mtime"]:
        return _cache["config"]
    try:
        import yaml

        cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning("[booking-gate] 設定が読めない: %s", e)
        cfg = {}
    _cache["config"], _cache["config_mtime"] = cfg, mtime
    return cfg


def _load_table() -> dict | None:
    """アクセス許可表。読めない・壊れているときは None（＝全部落とす）。"""
    try:
        mtime = RESERVATIONS_PATH.stat().st_mtime
    except OSError:
        return None
    if _cache["table"] is not None and mtime == _cache["table_mtime"]:
        return _cache["table"]
    try:
        table = json.loads(RESERVATIONS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("[booking-gate] アクセス許可表が読めない: %s", e)
        return None
    _cache["table"], _cache["table_mtime"] = table, mtime
    return table


def _env_allowlist() -> set[str]:
    """gateway と同じ経路で allowlist を読む。

    multiplex 下では profile の secret scope に入っていて素の os.getenv では
    見えないことがある（gateway/authz_mixin.py の _platform_gate_env と同じ理由）。
    """
    out: set[str] = set()
    for name in ("SLACK_ALLOWED_USERS", "GATEWAY_ALLOWED_USERS"):
        raw = ""
        try:
            from agent.secret_scope import get_secret

            val = get_secret(name)
            if val is not None:
                raw = str(val)
        except Exception:
            pass
        if not raw:
            raw = os.getenv(name) or ""
        out.update(x.strip() for x in raw.split(",") if x.strip())
    return out


def _always_allowed(user_id: str) -> bool:
    """オーナーか。env と設定の**どちらか**に載っていれば通す。

    env だけに頼ると、secret scope から読めなかった瞬間に自分が締め出される。
    """
    if not user_id:
        return False
    if user_id in _env_allowlist():
        return True
    cfg = _load_config()
    return user_id in {str(x).strip() for x in (cfg.get("always_allow") or [])}


# ------------------------------------------------------------------ 判定


def _over_rate_limit(user_id: str, cfg: dict) -> int | None:
    """発言が多すぎないか。超えていたら「1時間あたりの上限」を返す。

    **時間で区切っただけでは、その時間内に何百通でも投げられる。** 会話1通ごとに
    LLM を呼ぶので、これがそのまま費用になる。オーナーには適用しない。
    """
    limit = int(cfg.get("max_messages_per_hour", DEFAULT_MAX_PER_HOUR))
    if limit <= 0:
        return None
    now = time.time()
    hits = [t for t in _recent.get(user_id, []) if now - t < 3600]
    hits.append(now)
    _recent[user_id] = hits
    return limit if len(hits) > limit else None


def _is_stale(table: dict, cfg: dict, now: datetime) -> bool:
    """ポーラーが死んでいないか。古いアクセス許可表は無効とみなす。"""
    limit = int(cfg.get("stale_after_minutes", DEFAULT_STALE_MINUTES))
    try:
        generated = datetime.fromisoformat(table["generated_at"])
    except Exception:
        return True
    return now - generated > timedelta(minutes=limit)


def _my_profile(cfg: dict) -> str:
    """この gateway が動いているプロファイル。plist の HERMES_PROFILE が正。"""
    return (os.environ.get("HERMES_PROFILE") or cfg.get("profile") or "operator").strip()


def _find_slot(table: dict, cfg: dict, user_id: str, now: datetime) -> dict | None:
    """いま有効な枠。人と話す窓口は operator ひとつなので、何も絞り込まない。"""
    grace = cfg.get("grace") or {}
    before = timedelta(minutes=int(grace.get("before_minutes", 5)))
    after = timedelta(minutes=int(grace.get("after_minutes", 5)))
    for s in table.get("slots") or []:
        if s.get("slack_user_id") != user_id:
            continue
        try:
            start = datetime.fromisoformat(s["start"]) - before
        except Exception:
            continue
        if now < start:
            continue
        if not s.get("end"):
            return s  # 無期限のアクセス許可
        try:
            end = datetime.fromisoformat(s["end"]) + after
        except Exception:
            continue
        if now <= end:
            return s
    return None


def _next_slot(table: dict, user_id: str, now: datetime) -> dict | None:
    upcoming = []
    for s in table.get("slots") or []:
        if s.get("slack_user_id") != user_id:
            continue
        try:
            start = datetime.fromisoformat(s["start"])
        except Exception:
            continue
        if start > now:
            upcoming.append((start, s))
    return min(upcoming)[1] if upcoming else None


# ------------------------------------------------------------------ 後始末と案内


def _remember_active(user_id: str, source, slot: dict, session_store) -> None:
    """許可が切れた後にセッションを畳めるよう、鍵を控えておく。

    畳むきっかけは時計ではなく「拒否したとき」なので、期限の有無に関係なく控える。
    カードに紐づけたアクセス許可（期限なし）も、カードが閉じれば拒否されて畳まれる。
    """
    key = None
    gen = getattr(session_store, "_generate_session_key", None)
    if callable(gen):
        try:
            key = gen(source)
        except Exception:
            key = None
    _active[user_id] = {
        "session_key": key,
        "slot": slot,
        "chat_type": getattr(source, "chat_type", None),
    }


def _finish_if_expired(user_id: str, session_store) -> None:
    """許可が終わった人のセッションを畳む。次の人に文脈を持ち越さない。

    **畳んでよいのは1対1の DM だけ。** 複数人がいるスレッドはセッションが1つなので、
    1人の期限切れで畳むと、まだ話している他の人の文脈まで消える。
    """
    entry = _active.pop(user_id, None)
    if not entry or not entry.get("session_key"):
        return
    if entry.get("chat_type") != "dm":
        return
    reset = getattr(session_store, "reset_session", None)
    if not callable(reset):
        return
    try:
        reset(entry["session_key"])
        logger.info("[booking-gate] %s のセッションをアクセス許可の終了で畳んだ", user_id)
    except Exception as e:
        logger.warning("[booking-gate] セッションを畳めなかった: %s", e)


def _notice_text(table: dict | None, user_id: str, now: datetime) -> str:
    base = "いまは会話できる時間ではありません。"
    if table:
        nxt = _next_slot(table, user_id, now)
        if nxt:
            try:
                start = datetime.fromisoformat(nxt["start"])
                return base + f"次のアクセス許可は {start.strftime('%m/%d %H:%M')} からです。"
            except Exception:
                pass
    return base + "オーナーに許可を依頼してください。"


def _send_notice(gateway, source, text: str, reply_to=None) -> None:
    """案内を1通返す。送れなくても判定には影響させない。

    **1対1の DM 以外では ephemeral（本人にしか見えない）で出す。**
    複数人がいるスレッドに「あなたは時間外です」を全員へ見せる必要はないし、
    会話の流れも汚さない。人なら小声で言うところ。
    """
    user_id = source.user_id or ""
    last = _notified.get(user_id, 0.0)
    if time.time() - last < NOTICE_INTERVAL_SEC:
        return
    _notified[user_id] = time.time()

    adapters = getattr(gateway, "adapters", None) or {}
    adapter = None
    for key, value in adapters.items():
        if getattr(key, "value", str(key)) == "slack":
            adapter = value
            break
    if adapter is None or not source.chat_id:
        return
    try:
        import asyncio

        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    try:
        if getattr(source, "chat_type", None) == "dm":
            loop.create_task(adapter.send(source.chat_id, text, reply_to=reply_to))
        else:
            loop.create_task(
                adapter.send_private_notice(source.chat_id, user_id, text, reply_to=reply_to)
            )
    except Exception as e:
        logger.debug("[booking-gate] 案内を送れなかった: %s", e)


# ------------------------------------------------------------------ フック本体


def gate(event, gateway=None, session_store=None, **kwargs):
    source = getattr(event, "source", None)
    if source is None:
        return None
    if getattr(source.platform, "value", str(source.platform)) != "slack":
        return None  # 他プラットフォームには関与しない

    user_id = (source.user_id or "").strip()
    now = datetime.now(timezone.utc).astimezone()

    if _always_allowed(user_id):
        return None  # ← バイパス。アクセス許可表を読む前に抜ける

    cfg = _load_config()
    table = _load_table()

    reply_to = getattr(event, "message_id", None)

    if table is None or _is_stale(table, cfg, now):
        _finish_if_expired(user_id, session_store)
        _send_notice(gateway, source, "いま許可を確認できません。時間をおいて試してください。",
                     reply_to)
        logger.warning("[booking-gate] アクセス許可表が無い/古い → %s を拒否", user_id)
        return {"action": "skip", "reason": "booking-table-unavailable"}

    slot = _find_slot(table, cfg, user_id, now)
    if slot:
        over = _over_rate_limit(user_id, cfg)
        if over is not None:
            _send_notice(
                gateway, source,
                f"少し急ぎすぎです（1時間に{over}通まで）。時間をおいて続けてください。",
                reply_to,
            )
            logger.warning("[booking-gate] %s が発言上限を超えた（%s/時）", user_id, over)
            return {"action": "skip", "reason": "rate-limited"}
        _remember_active(user_id, source, slot, session_store)
        return None

    _finish_if_expired(user_id, session_store)
    _send_notice(gateway, source, _notice_text(table, user_id, now), reply_to)
    return {"action": "skip", "reason": "outside-booking"}


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", gate)
    # プラグインのログはゲートウェイのログに出ない。**外から確認できる痕跡を残す。**
    # これが無いと「配置も有効化もしたのにフックが動いていない」を検出できない。
    #
    # ただし書くのは gateway の中だけ。`hermes plugins list` / `doctor` のような
    # 短命プロセスもプラグインを読み込むので、そこで書くと痕跡がその pid で
    # 上書きされ、doctor が「死んでいる」と誤判定する（実際に踏んだ）。
    if "gateway" not in sys.argv:
        return
    try:
        GATE_HOME.mkdir(parents=True, exist_ok=True)
        LOADED_PATH.write_text(
            json.dumps(
                {
                    "loaded_at": datetime.now(timezone.utc).astimezone().isoformat(),
                    "pid": os.getpid(),
                    "profile": _my_profile(_load_config()),
                    "reservations": str(RESERVATIONS_PATH),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("[booking-gate] 読み込みの痕跡を残せなかった: %s", e)
