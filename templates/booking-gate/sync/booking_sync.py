#!/usr/bin/env python3
"""booking-sync — 許可をアクセス許可表と pairing 承認へ反映する。

launchd から1分ごとに起動される。やることは3つだけ。

  1. 手で出したアクセス許可 grants.json を読む（seaos-kit guest が書く）
  2. アクセス許可表 reservations.json を原子的に置き換える（プラグインが読む）
  3. いま有効な人だけを pairing の承認済みに置く

**ゲートが見るのは reservations.json だけ**で、それを誰が書いたかは知らない。
材料を増やしたくなったら、この表に行を足す書き手を作ればよく、ゲートは変わらない。

LLM は一切通らない。許可の判断を LLM に任せると、カードの本文やメッセージで
判断を動かせてしまう。手を抜いているのではない。詳細は DESIGN.md を参照。

読めない・壊れている場合は「誰も許可されていない」状態を書く。
黙って前回の表を残すと、時間外の人が通り続ける。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
GUESTS_PATH = GATE_HOME / "guests.json"
_LEGACY_GUESTS_PATH = GATE_HOME / "grants.json"  # 改名前の名前。読むだけ
AUDIT_PATH = GATE_HOME / "audit.log"  # 追記専用。誰がいつ入ったかを後から追える唯一の記録
IDENTITY_CACHE_PATH = GATE_HOME / "identity-cache.json"

IDENTITY_TTL_SEC = 24 * 3600
SOURCE_TAG = "booking-gate"  # pairing の承認レコードに付ける印。これが無いものは触らない

# カードが「まだ生きている」状態。これ以外（done / archived）になったら許可も終わる
# カードに紐づけたアクセス許可が生きている状態。
#
# **`done` を含める。** `done` は「そのカードが終わった」であって
# 「依頼が完了した」ではない——エージェントが終わったと言っているだけで、
# 人が「まだこれが残っている」と言えば、当然その続きをやる必要がある。
# そのとき相手が締め出されていては話にならない。
#
# 切れるのは `archived` になったとき。**畳むのは明示的な操作**なので、
# 「もうこの件は終わり」という合図として意図がはっきりしている。
OPEN_STATUSES = {"triage", "todo", "ready", "running", "blocked", "review",
                 "scheduled", "done"}


LOG_PATH = HERMES_HOME / "logs" / "booking-sync.log"


def log(msg: str) -> None:
    """記録はファイルへ。**標準出力には出さない。**

    cron（`--no-agent`）で回すと標準出力がそのまま配信されるので、毎分の
    「変化なし」を出すと1分ごとに通知が飛ぶ。空の出力は黙って終わる契約なので、
    伝えるべきことがあるときだけ ``notify()`` を使う。
    """
    line = f"{datetime.now().astimezone():%Y-%m-%d %H:%M:%S} [booking-sync] {msg}"
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 1_000_000:
            LOG_PATH.replace(LOG_PATH.with_suffix(".log.1"))
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if sys.stdout.isatty():  # 手で叩いたときはそのまま見せる
        print(line, flush=True)


def notify(msg: str) -> None:
    """伝えるべきこと（許可の増減、異常）だけを標準出力へ。"""
    print(f"[booking-sync] {msg}", flush=True)


def audit(event: str, **fields) -> None:
    """追記専用の監査ログ。**消える情報を残すためにある。**

    grants.json は「いまの状態」しか持たないので、prune すると
    「あの日あの人をなぜ入れたのか」が消える。アクセス許可の出し入れと、実際に会話が
    開いた／閉じた瞬間だけをここに積む。読むのはオーナーと ``seaos-kit guest log``。
    """
    record = {
        "at": datetime.now(timezone.utc).astimezone().isoformat(),
        "event": event,
        "actor": os.environ.get("HERMES_PROFILE") or "cli",
        **fields,
    }
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        # 追記専用なので放っておくと際限なく増える。1MB で1世代だけ畳む。
        # 消すのではなく .1 へ寄せる（監査記録を黙って捨てない）
        if AUDIT_PATH.exists() and AUDIT_PATH.stat().st_size > 1_000_000:
            AUDIT_PATH.replace(AUDIT_PATH.with_suffix(".log.1"))
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:  # 監査に失敗しても本体は止めない
        notify(f"監査ログに書けない: {e}")


# ------------------------------------------------------------------ 設定

DEFAULTS = {
    "profile": "operator",
    "grace": {"before_minutes": 5, "after_minutes": 5},
    # 期限が切れたあと、pairing の承認だけを残す時間。この間はゲート1を通るが
    # ゲート2が必ず落とすので、会話はできず「終わりました」の案内だけが届く。
    "notice_window_minutes": 10,
    "always_allow": [],
}


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    if not CONFIG_PATH.exists():
        return cfg
    try:
        import yaml

        loaded = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception as e:  # 壊れた設定で「前回のまま通す」のが最悪なので握らない
        notify(f"設定が読めない: {e}")
        return cfg
    if isinstance(loaded, dict):
        for k, v in loaded.items():
            if k == "grace" and isinstance(v, dict):
                cfg["grace"].update(v)
            else:
                cfg[k] = v
    return cfg


def profile_home(profile: str) -> Path:
    return HERMES_HOME if profile == "default" else HERMES_HOME / "profiles" / profile


def read_env_file(path: Path) -> dict:
    """.env を読む。gateway とは別プロセスなので環境変数では届かない。"""
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


# ------------------------------------------------------------------ 手で出したアクセス許可


def task_status(task_id: str) -> str | None:
    """カードの状態。ボードが読めなければ None（＝許可を出さない）。"""
    db = HERMES_HOME / "kanban.db"
    if not db.exists():
        return None
    try:
        import sqlite3

        # 読み取り専用で開く。ディスパッチャが書いている最中でも邪魔しない
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute(
                "SELECT status FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        finally:
            conn.close()
    except Exception as e:
        notify(f"ボードを読めない: {e}")
        return None
    return row[0] if row else None


def load_guests() -> list[dict]:
    """seaos-kit guest が書いたアクセス許可。壊れていれば「許可なし」として扱う。"""
    path = GUESTS_PATH if GUESTS_PATH.exists() else _LEGACY_GUESTS_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception as e:
        notify(f"アクセス許可が読めない: {e}。手で出したアクセス許可は無効として扱う")
        return []
    grants = data.get("grants") if isinstance(data, dict) else None
    return grants if isinstance(grants, list) else []


def guest_slots(cfg: dict, now: datetime) -> list[dict]:
    """アクセス許可をスロットに直す。ファイルは掃除しない（それは prune の仕事）。

    **終わった直後のアクセス許可も、猶予のあいだは枠として残す。** ここで捨てると
    「切れました」と本人に返す余地まで消えて、完全な無言になる。
    実際に話せるかどうかは ``slot_is_active`` が決める。
    """
    margin = timedelta(
        minutes=int(cfg["grace"]["after_minutes"])
        + int(cfg.get("notice_window_minutes", 10))
    )
    out = []
    for g in load_guests():
        uid = str(g.get("slack_user_id") or "").strip()
        if not uid:
            continue
        end = g.get("end")  # None = 期限なし（カード紐付けか無期限）
        if end:
            try:
                if datetime.fromisoformat(end) + margin < now:
                    continue
            except ValueError:
                continue
        # カードに紐づけたアクセス許可は、そのカードが終わった時点で切れる
        task_id = (g.get("task_id") or "").strip()
        if task_id:
            st = task_status(task_id)
            if st is None:
                log(f"{task_id} が見つからない → {uid} の許可は出さない")
                continue
            if st not in OPEN_STATUSES:
                continue
        out.append(
            {
                "slack_user_id": uid,
                "email": g.get("email", ""),
                "start": g.get("start") or now.isoformat(),
                "end": end,
                "event_id": "",
                "summary": g.get("label") or g.get("note") or "手で出したアクセス許可",
                "task_id": task_id,
                "source": "guest",
            }
        )
    return out


# ------------------------------------------------------------------ Slack ID の解決


def load_identity_cache() -> dict:
    try:
        return json.loads(IDENTITY_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def slack_lookup(token: str, email: str) -> str | None:
    url = "https://slack.com/api/users.lookupByEmail?" + urllib.parse.urlencode(
        {"email": email}
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        log(f"Slack 参照に失敗 {email}: {e}")
        return None
    if not data.get("ok"):
        err = data.get("error", "unknown")
        if err == "missing_scope":
            log("Slack トークンに users:read.email が無い → アプリを再インストールすること")
        return None
    return ((data.get("user") or {}).get("id")) or None


def slack_directory(token: str, cache: dict) -> dict:
    """表示名 → Slack ID の対応表。``users.list`` を1時間キャッシュする。

    Slack のメンションは、エージェントに届く時点で ``@表示名`` に変換されていて
    ID が落ちている（アダプタが `<@U…>` を人間可読に直すため）。名前から引けないと
    「@田中さんを2時間」を実行できない。
    """
    hit = cache.get("_directory")
    if isinstance(hit, dict) and time.time() - hit.get("at", 0) < 3600:
        return hit.get("names") or {}

    names: dict[str, str] = {}
    cursor = ""
    for _ in range(20):  # 200 × 20 = 4000 人まで
        url = "https://slack.com/api/users.list?" + urllib.parse.urlencode(
            {"limit": 200, **({"cursor": cursor} if cursor else {})}
        )
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            log(f"ユーザー一覧を取れない: {e}")
            break
        if not data.get("ok"):
            log(f"ユーザー一覧を取れない: {data.get('error')}")
            break
        for u in data.get("members", []):
            if u.get("deleted") or u.get("is_bot"):
                continue
            prof = u.get("profile") or {}
            for key in (u.get("name"), prof.get("display_name"), prof.get("real_name")):
                if key:
                    names.setdefault(str(key).strip().lower(), u["id"])
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            break

    if names:
        cache["_directory"] = {"names": names, "at": time.time()}
    return names


# ------------------------------------------------------------------ 書き出し


def write_atomic(path: Path, payload: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(payload, encoding="utf-8")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def pairing_dir(profile: str) -> Path:
    """Hermes の解決規則を踏襲する（hermes_constants.get_hermes_dir と同じ挙動）。

    レガシーの ``pairing/`` は**中身がある場合のみ**優先される。空のディレクトリは
    無視して ``platforms/pairing/`` を使う。ここを取り違えると、書いた承認を
    gateway が読まない。
    """
    home = profile_home(profile)
    legacy = home / "pairing"
    if legacy.is_dir() and any(legacy.iterdir()):
        return legacy
    return home / "platforms" / "pairing"


def approved_by_us(profile: str) -> set[str]:
    """いま自分の印で承認されている人。差分を取って監査ログに書くために使う。"""
    try:
        data = json.loads((pairing_dir(profile) / "slack-approved.json").read_text())
    except Exception:
        return set()
    return {
        k for k, v in data.items()
        if isinstance(v, dict) and v.get("source") == SOURCE_TAG
    }


def sync_pairing(profile: str, user_ids: set[str]) -> tuple[int, int]:
    """進行中スロットの参加者だけを承認済みに置く。

    自分が付けた印 (source=booking-gate) のあるレコードしか消さない。
    手で pair した人や他経路の承認を巻き添えにしない。
    公式 API (_approve_user) は allowlist へミラー書き込みするので使わない。
    """
    path = pairing_dir(profile) / "slack-approved.json"
    try:
        approved = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(approved, dict):
            approved = {}
    except FileNotFoundError:
        approved = {}
    except Exception as e:
        log(f"承認ファイルが読めない: {e}")
        return (0, 0)

    added = removed = 0
    for uid, rec in list(approved.items()):
        if isinstance(rec, dict) and rec.get("source") == SOURCE_TAG and uid not in user_ids:
            del approved[uid]
            removed += 1
    for uid in user_ids:
        if uid not in approved:
            approved[uid] = {
                "user_name": "",
                "approved_at": time.time(),
                "source": SOURCE_TAG,
            }
            added += 1

    if added or removed:
        write_atomic(path, json.dumps(approved, indent=2, ensure_ascii=False))
    return (added, removed)


def audit_transitions(before: set[str], after: set[str], table: dict) -> None:
    """会話が開いた／閉じた瞬間を記録する。"""
    detail = {}
    for slot in table.get("slots", []):
        detail.setdefault(slot["slack_user_id"], slot)
    for uid in sorted(after - before):
        slot = detail.get(uid, {})
        audit("access_open", slack_user_id=uid, source=slot.get("source"),
              task_id=slot.get("task_id") or None, until=slot.get("end"))
    for uid in sorted(before - after):
        audit("access_close", slack_user_id=uid)


# ------------------------------------------------------------------ 本体


def build_table(cfg: dict, now: datetime) -> dict:
    """アクセス許可表を組み立てる。いまの材料は手で出したアクセス許可だけ。"""
    return {
        "generated_at": now.isoformat(),
        "slots": guest_slots(cfg, now),
    }


def slot_is_active(slot: dict, cfg: dict, now: datetime) -> bool:
    """いま有効か。``end`` が None のスロットは無期限。"""
    grace = cfg["grace"]
    try:
        start = datetime.fromisoformat(slot["start"]) - timedelta(
            minutes=int(grace["before_minutes"])
        )
    except (KeyError, TypeError, ValueError):
        return False
    if now < start:
        return False
    if not slot.get("end"):
        return True
    try:
        end = datetime.fromisoformat(slot["end"]) + timedelta(
            minutes=int(grace["after_minutes"])
        )
    except (TypeError, ValueError):
        return False
    return now <= end


def active_user_ids(table: dict, cfg: dict, now: datetime, extra_minutes: int = 0) -> set[str]:
    """いま有効な人。``extra_minutes`` は期限のうしろに足す猶予。

    ゲート1（pairing）にだけ猶予を足すと、切れた直後の発言が**プラグインまで届く**。
    プラグインは必ず落とすので会話はできないが、「終わりました」と返せる。
    猶予が無いと、承認も同時に消えるのでアダプタが先に弾き、完全な無言になる。
    """
    if not extra_minutes:
        return {s["slack_user_id"] for s in table["slots"] if slot_is_active(s, cfg, now)}
    stretched = json.loads(json.dumps(cfg))
    stretched["grace"]["after_minutes"] = (
        int(cfg["grace"]["after_minutes"]) + int(extra_minutes)
    )
    return {s["slack_user_id"] for s in table["slots"] if slot_is_active(s, stretched, now)}


def main() -> int:
    now = datetime.now(timezone.utc).astimezone()
    cfg = load_config()

    # 前回の「話せた人」を先に読む。監査ログの開閉はこの差分で決める
    try:
        before = set(json.loads(RESERVATIONS_PATH.read_text(encoding="utf-8")).get("active", []))
    except Exception:
        before = set()

    table = build_table(cfg, now)
    active = active_user_ids(table, cfg, now)          # 実際に話せる人
    table["active"] = sorted(active)
    write_atomic(RESERVATIONS_PATH, json.dumps(table, indent=2, ensure_ascii=False), 0o644)

    # 承認は少し長めに残す。切れた直後の発言に一言返すため（会話は通らない）
    approved = active_user_ids(table, cfg, now, int(cfg.get("notice_window_minutes", 10)))
    added, removed = sync_pairing(cfg["profile"], approved)
    audit_transitions(before, active, table)

    summary = f"枠 {len(table['slots'])} / 有効 {len(active)} 人（承認 +{added} -{removed}）"
    log(summary)
    if added or removed:
        notify(summary)   # 変化があったときだけ伝える
    return 0


if __name__ == "__main__":
    sys.exit(main())
