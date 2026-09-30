#!/usr/bin/env python3
"""オーナーの不在中に、オーナー宛の話を operator が代わりに受ける（owner-away）の回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/owner_away_test.py

一時ディレクトリを `HERMES_HOME` に見立てる。**Slack には繋がない**（口は偽物に差し替える）。

守りたいのは:
  * オーナーがいるあいだは、オーナーの会話を operator に見せない（ボットのいない会話は捨てる）
  * 不在（ステータスの絵文字が 🤖）のあいだだけ、オーナー宛の DM とメンションを代わりに受ける
  * 見るのは絵文字だけ。文言は問わない
  * ボットがいない会話は、相手とボットの DM へ移してから受ける（案内は続けて出さない）
  * 許可の無い人と、オーナー自身の発言は、代わりに受けない
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import tempfile
from pathlib import Path

os.environ["HERMES_HOME"] = tempfile.mkdtemp(prefix="owner-away-test-")

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("owner_away", ROOT / "templates/plugins/owner-away/__init__.py")
oa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oa)

from _harness import finish, run_tests  # noqa: E402

OWNER, BOT, GUEST, STRANGER = "U0OWNER", "U0BOT", "U0GUEST", "U0STRANGER"
BOT_CH, OWNER_DM, BOT_DM = "C0BOTIN", "D0OWNERDM", "D0BOTDM"


class FakeClient:
    """ボットのトークンで見える範囲だけを返す偽物。"""

    def __init__(self):
        self.posted: list[tuple[str, str]] = []

    async def conversations_info(self, channel):
        if channel in (BOT_CH, BOT_DM):
            return {"channel": {"is_member": channel == BOT_CH, "is_im": channel == BOT_DM}}
        raise RuntimeError("channel_not_found")

    async def conversations_open(self, users):
        return {"channel": {"id": BOT_DM}}

    async def chat_postMessage(self, channel, text):
        self.posted.append((channel, text))
        return {"ts": f"9.{len(self.posted)}"}

    async def users_profile_get(self, user):
        return {"profile": {"status_emoji": ":robot_face:", "status_text": "会議中"}}


class FakeAdapter:
    def _early_reject_unauthorized(self, user, channel, is_dm):
        return user == STRANGER


def reset(away: bool) -> FakeClient:
    oa._state.update({"profile": "operator", "owner": OWNER, "away": away, "checked_at": 0.0})
    oa._members.clear()
    oa._noticed.clear()
    return FakeClient()


def msg(channel, user, text, channel_type="channel", **extra):
    return {"type": "message", "channel": channel, "user": user, "text": text,
            "channel_type": channel_type, "ts": "1.0", **extra}


def route(ev, client):
    asyncio.run(oa.route(ev, client, BOT, FakeAdapter()))
    return ev


def test_owner_conversations_stay_hidden_while_present():
    """在席中は、ボットのいない会話（オーナーの DM・チャンネル）を operator に見せない。"""
    client = reset(away=False)
    assert route(msg(OWNER_DM, GUEST, "明日の件", "im"), client)["type"] == oa.IGNORED
    assert route(msg("C0ELSE", GUEST, f"<@{OWNER}> 見て"), client)["type"] == oa.IGNORED
    assert not client.posted


def test_bot_conversations_pass_untouched():
    """ボットがいる会話は、在席中でも不在中でも、ふだんどおり Hermes に渡す。"""
    for away in (False, True):
        client = reset(away)
        ev = route(msg(BOT_CH, GUEST, f"<@{BOT}> 頼みたい"), client)
        assert ev["type"] == "message" and ev["text"] == f"<@{BOT}> 頼みたい"


def test_away_mention_in_bot_channel_is_read_as_bot_mention():
    """不在中、ボットのいるチャンネルで @オーナー と呼ばれたら、ボットが呼ばれたものとして受ける。"""
    client = reset(away=True)
    ev = route(msg(BOT_CH, GUEST, f"<@{OWNER}> 資料どこ？"), client)
    assert ev["type"] == "message"
    assert f"<@{BOT}>" in ev["text"] and f"<@{OWNER}>" not in ev["text"], ev["text"]
    assert ev["text"].startswith("［オーナー宛のメンション"), ev["text"]
    assert ev["channel"] == BOT_CH, "スレッドで返すはずが、場所が変わった"


def test_away_dm_moves_to_bot_dm_with_one_notice():
    """不在中のオーナー宛 DM は、相手とボットの DM へ移す。案内は続けて出さない。"""
    client = reset(away=True)
    first = route(msg(OWNER_DM, GUEST, "明日の件", "im", thread_ts="0.5"), client)
    assert first["type"] == "message" and first["channel"] == BOT_DM and first["channel_type"] == "im"
    assert first["ts"] == "9.1" and "thread_ts" not in first, first
    assert first["text"].startswith("［オーナー宛の DM"), first["text"]
    second = route(msg(OWNER_DM, GUEST, "追加です", "im"), client)
    assert second["channel"] == BOT_DM
    assert "代わりに受けます" in client.posted[0][1]
    assert "代わりに受けます" not in client.posted[1][1], "案内を繰り返した"


def test_away_mention_where_bot_is_absent_moves_to_dm():
    """ボットのいないチャンネルでの @オーナー も、相手とボットの DM へ移す。"""
    client = reset(away=True)
    ev = route(msg("C0ELSE", GUEST, f"<@{OWNER}> 見て"), client)
    assert ev["channel"] == BOT_DM, ev
    assert "<#C0ELSE>" in client.posted[0][1]


def test_not_for_owner_or_not_allowed():
    """不在中でも、オーナー宛でない会話・オーナー自身・許可の無い人・編集は代わりに受けない。"""
    client = reset(away=True)
    assert route(msg("C0ELSE", GUEST, "雑談"), client)["type"] == oa.IGNORED
    assert route(msg(OWNER_DM, OWNER, "送ったよ", "im"), client)["type"] == oa.IGNORED
    assert route(msg(OWNER_DM, STRANGER, "こんにちは", "im"), client)["type"] == oa.IGNORED
    assert route(msg(OWNER_DM, GUEST, "直した", "im", subtype="message_changed"), client)["type"] == oa.IGNORED
    assert not client.posted, "許可の無い人にも案内を出した"


def test_away_is_read_from_the_emoji_only():
    """見るのは絵文字だけ。文言は問わない。期限切れは不在ではない。"""
    now = 1_000_000.0
    assert oa.is_away({"status_emoji": ":robot_face:", "status_text": "会議中"}, now)
    assert oa.is_away({"status_emoji": ":robot_face:", "status_text": ""}, now)
    assert not oa.is_away({"status_emoji": ":palm_tree:", "status_text": "Bot 対応中"}, now)
    assert not oa.is_away({"status_emoji": ":robot_face:", "status_expiration": now - 1}, now)


def test_status_event_switches_mode():
    """オーナーのステータスの変化で切り替わる。他人の変化では切り替わらない。"""
    reset(away=False)

    class App:
        client = FakeClient()
        middleware: list = []

        def use(self, fn):
            self.middleware.append(fn)

    app = App()
    oa._is_mine = lambda: True
    oa._owner_id = lambda: OWNER

    class Adapter(FakeAdapter):
        _bot_user_id = BOT

    async def go():
        oa.wire(app, Adapter())
        await asyncio.sleep(0)
        assert oa._state["away"] is True, "接続時の読み直しで不在にならない"

        async def nxt():
            return None
        mw = app.middleware[0]
        await mw({"event": {"type": "user_status_changed", "user": {"id": GUEST, "profile": {}}}}, nxt)
        assert oa._state["away"] is True, "他人のステータスで切り替わった"
        await mw({"event": {"type": "user_status_changed", "user": {"id": OWNER, "profile": {}}}}, nxt)
        assert oa._state["away"] is False
        oa._state["task"].cancel()
    asyncio.run(go())


def test_note_matches_the_skill():
    """operator に添える一行が、owner-away スキルに書いた文言と一字一句そろっている。"""
    skill = (ROOT / "templates/skills/owner-away/SKILL.md").read_text(encoding="utf-8")
    for kind in ("DM", "メンション"):
        head = oa._note(kind, "").splitlines()[0]
        assert head in skill, head


run_tests(dict(globals()))
finish()
