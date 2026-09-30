"""影武者（shadow）の ON/OFF。**正は本人の Slack ステータスただ1つ。**

`seaos-kit shadow on` はステータスを 🤖 にするだけ、`off` は外すだけで、
影武者の側はステータスの変化を見て動く（templates/plugins/shadow）。スマホから
手でステータスを変えても同じように効くのは、正が1つしかないからである。

トークンは影武者の役に配った本人のユーザートークン（SLACK_BOT_TOKEN）を使う。
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Callable, Optional

import roles
from paths import profile_dir

Log = Callable[[str], None]

ROLE = "shadow"
# templates/plugins/shadow と同じ値。**片方だけ変えると、付けたステータスを影武者が読めない。**
STATUS_EMOJI = ":robot_face:"
STATUS_TEXT = "Bot 対応中"


class ShadowError(RuntimeError):
    """呼び手に見せる、原因の分かる失敗。"""


def _token() -> str:
    import env as env_mod

    if not roles.is_enabled(ROLE):
        raise ShadowError("影武者が有効になっていません（seaos-kit enable shadow → update）")
    token = env_mod.read_env(profile_dir(ROLE) / ".env").get("SLACK_BOT_TOKEN", "")
    if not token.startswith("xoxp-"):
        raise ShadowError("影武者に本人のユーザートークン（xoxp-）が入っていません")
    return token


def _call(method: str, token: str, payload: Optional[dict] = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else b""
    headers = {"Authorization": f"Bearer {token}"}
    if payload is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(f"https://slack.com/api/{method}", data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.loads(r.read() or b"{}")
    except Exception as exc:  # noqa: BLE001
        raise ShadowError(f"Slack に届きませんでした（{method}）: {exc}") from exc
    if not body.get("ok"):
        raise ShadowError(f"Slack が断りました（{method}）: {body.get('error')}")
    return body


def is_on(profile: dict, now: Optional[float] = None) -> bool:
    """影武者の側（templates/plugins/shadow の status_is_on）と同じ判定。"""
    if (profile or {}).get("status_emoji") != STATUS_EMOJI:
        return False
    expiration = int((profile or {}).get("status_expiration") or 0)
    return expiration == 0 or expiration > (now if now is not None else time.time())


def status(log: Optional[Log] = None) -> bool:
    """いま代わりに受けているか。"""
    profile = _call("users.profile.get", _token()).get("profile") or {}
    on = is_on(profile)
    if log:
        text = f"{profile.get('status_emoji', '')} {profile.get('status_text', '')}".strip() or "（なし）"
        log(f"{'ON' if on else 'OFF'}：本人のステータスは {text}")
    return on


def set_mode(on: bool, *, minutes: int = 0, log: Optional[Log] = None) -> None:
    """ステータスを付ける／外す。`minutes` を渡すと、その時間で自動的に外れる。"""
    token = _token()
    if on:
        expiration = int(time.time()) + minutes * 60 if minutes > 0 else 0
        profile = {"status_text": STATUS_TEXT, "status_emoji": STATUS_EMOJI,
                   "status_expiration": expiration}
    else:
        current = _call("users.profile.get", token).get("profile") or {}
        if current.get("status_emoji") != STATUS_EMOJI:
            # **影武者のもの以外は消さない。** 本人が手で付けたステータスを巻き添えにしない。
            if log:
                log("OFF です（影武者のステータスは付いていません）")
            return
        profile = {"status_text": "", "status_emoji": "", "status_expiration": 0}
    _call("users.profile.set", token, {"profile": profile})
    if log:
        if on and minutes > 0:
            log(f"ON にしました（{minutes} 分で自動的に OFF）")
        else:
            log("ON にしました" if on else "OFF にしました")
