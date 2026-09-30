"""owner-away — オーナーが不在（Slack ステータスの絵文字が 🤖）のあいだ、
オーナー宛の話を operator が代わりに受ける。

オーナーが operator の Slack App に「本人の DM とメンションを読む」権限（ユーザースコープ）を
与えると、オーナーに見える会話のイベントも operator の接続に届くようになる。
ここでそれを選り分ける。**返事はボット（operator）の名前で出す**——本人になりすまさない。

  * ボットがいる会話 → ふだんどおり。オーナーが不在で `@オーナー` と呼ばれたら、
    ボットが呼ばれたものとして読み替える（そのスレッドで operator が返す）
  * ボットがいない会話（オーナーと誰かの DM、ボットのいないチャンネル）
      - オーナーが不在で、オーナー宛（DM、または `@オーナー`）なら、相手とボットの DM へ移す。
        人と人の DM にボットは入れないので、場所を移してから operator が返す
      - それ以外は**捨てる。** operator に見せない（オーナーの会話を読ませない）
  * オーナー自身の発言は、代わりに受ける対象にしない

**捨てるときも ack は返す。** イベントの種類を誰も持たない名前に書き換え、アダプタの
「何にでも当たる受け皿」に ack させる。ack が返らない失敗が続くと、Slack は App の
イベント配信そのものを止める（Hermes の slack アダプタの説明のとおり）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

AWAY_EMOJI = ":robot_face:"
# イベントを取りこぼしても、この間隔で読み直して追いつく。
REFRESH_SEC = 300
# ボットがその会話に入っているかの覚え（秒）。入退室はまれなので長めでよい。
MEMBER_TTL = 600
IGNORED = "owner_away_ignored"

# 「代わりに受けます」の案内は、同じ相手に対してこの間隔に1回まで（続けて送られても繰り返さない）。
NOTICE_INTERVAL = 1800

_state: dict = {"profile": None, "owner": None, "away": False, "checked_at": 0.0, "task": None}
_members: dict[str, tuple[bool, float]] = {}
_noticed: dict[str, float] = {}


def _hermes_root() -> Path:
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    return home.parent.parent if home.parent.name == "profiles" else home


# 外から状態を確かめる痕跡（doctor が読む）。
STATE_PATH = _hermes_root() / "owner-away" / "state.json"


# ------------------------------------------------------------------ オーナーの状態


def is_away(profile: dict, now: float | None = None) -> bool:
    """ステータスの**絵文字だけ**で決める。文言は何でもよい。期限切れは不在ではない。"""
    if (profile or {}).get("status_emoji") != AWAY_EMOJI:
        return False
    expiration = int((profile or {}).get("status_expiration") or 0)
    return expiration == 0 or expiration > (now if now is not None else time.time())


def _apply(profile: dict, *, source: str) -> None:
    away = is_away(profile)
    if away != _state["away"]:
        logger.info("[owner-away] %s（%s）", "オーナー不在：代わりに受ける" if away else "オーナー在席：受けない", source)
    _state["away"] = away
    _state["checked_at"] = time.time()
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({
            "profile": _state["profile"], "owner": _state["owner"], "away": away,
            "checked_at": datetime.now(timezone.utc).astimezone().isoformat(), "pid": os.getpid(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logger.debug("[owner-away] 状態を書けなかった: %s", e)


def _owner_id() -> str:
    """オーナー（SLACK_OWNER_ID）。multiplex では役の secret scope から読む。"""
    try:
        from agent.secret_scope import get_secret

        value = get_secret("SLACK_OWNER_ID")
        if value:
            return str(value).strip()
    except Exception:  # noqa: BLE001
        pass
    return (os.environ.get("SLACK_OWNER_ID") or "").strip()


async def _refresh(client) -> None:
    owner = _state["owner"]
    if not owner:
        return
    try:
        resp = await client.users_profile_get(user=owner)
        _apply(resp.get("profile") or {}, source="読み直し")
    except Exception as e:  # noqa: BLE001
        # 読めないときは前の状態を保つ。**不在へは倒さない。** 長く読めなければ在席に戻す。
        logger.warning("[owner-away] オーナーのステータスを読めなかった: %s", e)
        if _state["away"] and time.time() - _state["checked_at"] > REFRESH_SEC * 3:
            _state["away"] = False
            logger.warning("[owner-away] 長く読めないので、代わりに受けるのをやめた")


async def _refresh_loop(client) -> None:
    while True:
        await _refresh(client)
        await asyncio.sleep(REFRESH_SEC)


# ------------------------------------------------------------------ 選り分け


async def _bot_is_member(client, channel: str) -> bool:
    """ボットがその会話に入っているか。入っていない会話はボットのトークンでは見えない。"""
    hit = _members.get(channel)
    if hit and time.time() - hit[1] < MEMBER_TTL:
        return hit[0]
    try:
        info = (await client.conversations_info(channel=channel)).get("channel") or {}
        member = bool(info.get("is_member") or info.get("is_im"))
    except Exception:  # noqa: BLE001  （channel_not_found = ボットは入っていない）
        member = False
    _members[channel] = (member, time.time())
    return member


def _mentions(text: str, user: str | None) -> bool:
    return bool(user) and f"<@{user}>" in (text or "")


def _drop(event: dict) -> None:
    event["type"] = IGNORED


def _note(kind: str, text: str) -> str:
    """operator が「オーナー宛を代わりに受けた」と分かるように、頭に一言添える。

    **文言は owner-away スキルの見出しと一字一句そろえる。** operator はこの一行でスキルを引く。
    """
    label = f" {kind} " if kind.isascii() else kind
    return f"［オーナー宛の{label}を、オーナーの不在中に代わりに受けた］\n{text}"


def _authorized(adapter, user: str, channel: str) -> bool:
    """operator と話してよい相手か。**Hermes 自身の判定**（許可ユーザー・ゲストの承認）を使う。

    許可の無い人に「代わりに受けます」と言ってから断ることになるので、移す前に確かめる。
    判定できないときは通す（その先で Hermes が同じ判定をするので、すり抜けはしない）。
    """
    check = getattr(adapter, "_early_reject_unauthorized", None)
    if not callable(check):
        return True
    try:
        return not check(user, channel, True)
    except Exception:  # noqa: BLE001
        return True


async def route(event: dict, client, bot_id: str | None, adapter=None) -> None:
    """届いたメッセージを、そのまま通す・読み替える・移す・捨てる、のどれかにする（その場で書き換える）。"""
    if event.get("type") != "message":
        return
    owner = _state["owner"]
    channel = event.get("channel") or ""
    sender = event.get("user") or ""
    text = event.get("text") or ""
    away = _state["away"]
    from_other = bool(sender) and sender != owner and not event.get("bot_id") and not event.get("subtype")

    if await _bot_is_member(client, channel):
        # ボットがいる会話。ふだんどおり Hermes に渡す。
        if (away and from_other and _mentions(text, owner) and not _mentions(text, bot_id) and bot_id):
            event["text"] = _note("メンション", text.replace(f"<@{owner}>", f"<@{bot_id}>"))
        return

    # ここから先は、オーナーの権限でだけ見えている会話。
    is_dm = event.get("channel_type") == "im"
    if not (away and from_other and (is_dm or _mentions(text, owner))):
        _drop(event)
        return
    if adapter is not None and not _authorized(adapter, sender, channel):
        # 許可の無い人には黙る。オーナーが戻れば、元の DM で自分で読める。
        _drop(event)
        return
    try:
        dm = ((await client.conversations_open(users=sender)).get("channel") or {}).get("id")
        kind = "DM" if is_dm else f"メンション（<#{channel}>）"
        first = time.time() - _noticed.get(sender, 0.0) > NOTICE_INTERVAL
        lead = f"オーナーは不在なので、代わりに受けます。届いた{kind}はこちらです。\n" if first else ""
        posted = await client.chat_postMessage(channel=dm, text=f"{lead}>>> {text}")
        _noticed[sender] = time.time()
    except Exception as e:  # noqa: BLE001
        logger.warning("[owner-away] 相手との DM を開けなかった: %s", e)
        _drop(event)
        return
    # 相手とボットの DM で、いま出した案内に続けて話したことにする。
    event.update({"channel": dm, "channel_type": "im", "ts": posted.get("ts"),
                  "text": _note("DM" if is_dm else "メンション", text)})
    event.pop("thread_ts", None)


# ------------------------------------------------------------------ 取り付け


def _is_mine() -> bool:
    mine = _state["profile"]
    if not mine:
        return False
    try:
        from hermes_cli.profiles import get_active_profile_name

        return get_active_profile_name() == mine
    except Exception:  # noqa: BLE001
        return False


def wire(native, adapter) -> None:
    """Slack の口に、オーナーの見張りと選り分けを足す（接続のたびに呼ばれる）。"""
    if not _is_mine():
        return
    _state["owner"] = _owner_id() or None
    if not _state["owner"]:
        logger.info("[owner-away] SLACK_OWNER_ID が無いので、代わりに受けない")
    bot_id = getattr(adapter, "_bot_user_id", None)
    client = native.client

    # **ミドルウェアで拾う。** アダプタは「何にでも当たる受け皿」をプラグインより先に
    # 登録するので、`@app.event(...)` を足しても呼ばれない。ミドルウェアは振り分けの前に必ず通る。
    async def owner_away(body, next):  # noqa: A002 — bolt が名前で渡す
        event = (body or {}).get("event") or {}
        try:
            if event.get("type") == "user_status_changed":
                user = event.get("user") or {}
                if user.get("id") and user.get("id") == _state["owner"]:
                    _apply(user.get("profile") or {}, source="ステータスの変化")
            elif _state["owner"]:
                await route(event, client, bot_id, adapter)
        except Exception as e:  # noqa: BLE001  （選り分けで落ちても、ふだんの受け取りは止めない）
            logger.warning("[owner-away] 選り分けに失敗した: %s", e)
        await next()

    native.use(owner_away)

    task = _state.get("task")
    if task is not None and not task.done():
        task.cancel()
    try:
        _state["task"] = asyncio.get_running_loop().create_task(_refresh_loop(client))
    except RuntimeError:
        logger.warning("[owner-away] ステータスの見張りを始められなかった（イベントループが無い）")


def register(ctx) -> None:
    _state["profile"] = ctx.profile_name
    ctx.register_platform_handler("slack", wire)
