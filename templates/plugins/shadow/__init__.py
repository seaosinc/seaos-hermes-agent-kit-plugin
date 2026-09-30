"""shadow — 本人の Slack アカウントのまま、不在のあいだ代わりに受ける（影武者）。

shadow の役の Slack は、Bot トークンの代わりに**本人のユーザートークン（xoxp）**で
繋がっている。Hermes から見れば「ボットを個人アカウントで動かしている」だけなので、
影武者に固有のことは全部ここで足す。

  1. **本人の Slack ステータスが正。** 🤖（:robot_face:）が付いているあいだだけ受ける。
     変化は ``user_status_changed`` で知り、取りこぼしに備えて定期的に読み直す
  2. **本人の発言は受けない。** 本人は shadow の許可ユーザーから外してあり（キットが配る）、
     ここでも落とす。二重にしてあるのは、フックを通らない経路（応答中の割り込み）があるため
  3. **本人名義で出るものには、必ず代理の印を付ける。** 最終の返信だけでなく、Hermes が
     出す定型の通知も同じ口（adapter.send / edit_message）を通るので、そこで付ける

**別の役に効かせない。** multiplex では全役が1つのプロセスに同居する。フックも
Slack の口も、自分の役（ctx.profile_name）のときだけ働かせる。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

MARK = "🤖 代理応答"
STATUS_EMOJI = ":robot_face:"
STATUS_TEXT = "Bot 対応中"
# イベントを取りこぼしても、この間隔で読み直して追いつく。
REFRESH_SEC = 300


def _hermes_root() -> Path:
    """Hermes の根っこ。プロファイル配下の HERMES_HOME を吸収する（booking-gate と同じ）。"""
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    return home.parent.parent if home.parent.name == "profiles" else home


# 外から状態を確かめる痕跡（`seaos-kit shadow status` と doctor が読む）。
STATE_PATH = _hermes_root() / "shadow" / "state.json"

_state: dict = {"profile": None, "self_id": None, "on": False, "checked_at": 0.0, "task": None}


# ------------------------------------------------------------------ 状態


def status_is_on(profile: dict, now: float | None = None) -> bool:
    """本人のプロフィールから、いま代わりに受けるかを決める。

    **期限付きのステータスは、期限を過ぎたら OFF。** Slack は期限切れのステータスを
    すぐには消さないことがあるので、こちらでも時刻を見る。
    """
    if (profile or {}).get("status_emoji") != STATUS_EMOJI:
        return False
    expiration = int((profile or {}).get("status_expiration") or 0)
    return expiration == 0 or expiration > (now if now is not None else time.time())


def _apply(profile: dict, *, source: str) -> None:
    on = status_is_on(profile)
    if on != _state["on"]:
        logger.info("[shadow] %s（%s）", "受け付けを始めた" if on else "受け付けをやめた", source)
    _state["on"] = on
    _state["checked_at"] = time.time()
    _write_state()


def _write_state() -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({
            "profile": _state["profile"],
            "self_id": _state["self_id"],
            "on": _state["on"],
            "checked_at": datetime.fromtimestamp(_state["checked_at"], timezone.utc).astimezone().isoformat(),
            "pid": os.getpid(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logger.debug("[shadow] 状態を書けなかった: %s", e)


def _is_mine(profile: str | None = None) -> bool:
    mine = _state["profile"]
    if not mine:
        return False
    if profile:
        return profile == mine
    try:
        from hermes_cli.profiles import get_active_profile_name

        return get_active_profile_name() == mine
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ 受信の関門


def gate(event, gateway=None, session_store=None, **kwargs):
    source = getattr(event, "source", None)
    if source is None:
        return None
    if getattr(source.platform, "value", str(source.platform)) != "slack":
        return None
    if not _is_mine(getattr(source, "profile", None)):
        return None
    user_id = (getattr(source, "user_id", None) or "").strip()
    if user_id and user_id == _state["self_id"]:
        return {"action": "skip", "reason": "shadow-self"}
    if not _state["on"]:
        # **読めていないうちは受けない。** 本人がいるかもしれないときに代わりに話すより、
        # 黙っているほうが害が小さい。
        return {"action": "skip", "reason": "shadow-off"}
    return None


# ------------------------------------------------------------------ Slack の口


def marked(text):
    """代理の印を付ける。付いていれば付け直さない（編集で二重にしない）。"""
    if not isinstance(text, str) or not text.strip() or text.startswith(MARK):
        return text
    return f"{MARK}\n{text}"


def _wrap_outbound(adapter) -> None:
    """本人名義で出る文字に、印を付ける口を挟む。**一度だけ**（再接続のたびに重ねない）。"""
    if getattr(adapter, "_shadow_marked", False):
        return
    send, edit = adapter.send, adapter.edit_message

    async def send_marked(chat_id, content, *args, **kwargs):
        return await send(chat_id, marked(content), *args, **kwargs)

    async def edit_marked(chat_id, message_id, content, *args, **kwargs):
        return await edit(chat_id, message_id, marked(content), *args, **kwargs)

    adapter.send, adapter.edit_message = send_marked, edit_marked
    adapter._shadow_marked = True


async def _refresh(client) -> None:
    try:
        if not _state["self_id"]:
            auth = await client.auth_test()
            _state["self_id"] = auth.get("user_id")
        resp = await client.users_profile_get()
        _apply(resp.get("profile") or {}, source="読み直し")
    except Exception as e:  # noqa: BLE001
        # 読めないときは前の状態を保つ。**OFF へ倒すのは期限（REFRESH_SEC の3倍）を過ぎてから。**
        logger.warning("[shadow] ステータスを読めなかった: %s", e)
        if time.time() - _state["checked_at"] > REFRESH_SEC * 3 and _state["on"]:
            _state["on"] = False
            _write_state()
            logger.warning("[shadow] 長く読めないので受け付けをやめた")


async def _refresh_loop(client) -> None:
    while True:
        await _refresh(client)
        await asyncio.sleep(REFRESH_SEC)


def wire(native, adapter) -> None:
    """Slack の口に、ステータスの見張りと印付けを足す（接続のたびに呼ばれる）。"""
    if not _is_mine():
        return
    _state["self_id"] = getattr(adapter, "_bot_user_id", None) or _state["self_id"]
    _wrap_outbound(adapter)

    # **イベントはミドルウェアで拾う。** アダプタは「何にでも当たる受け皿」をプラグインより
    # 先に登録するので、`@app.event("user_status_changed")` を足しても呼ばれない。
    # ミドルウェアは振り分けの前に必ず通る。
    async def watch_status(body, next):  # noqa: A002 — bolt が名前で渡す
        event = (body or {}).get("event") or {}
        if event.get("type") == "user_status_changed":
            user = event.get("user") or {}
            if user.get("id") and user.get("id") == _state["self_id"]:
                _apply(user.get("profile") or {}, source="ステータスの変化")
        await next()

    native.use(watch_status)

    task = _state.get("task")
    if task is not None and not task.done():
        task.cancel()
    try:
        _state["task"] = asyncio.get_running_loop().create_task(_refresh_loop(native.client))
    except RuntimeError:
        logger.warning("[shadow] ステータスの見張りを始められなかった（イベントループが無い）")


def register(ctx) -> None:
    _state["profile"] = ctx.profile_name
    ctx.register_hook("pre_gateway_dispatch", gate)
    ctx.register_platform_handler("slack", wire)
