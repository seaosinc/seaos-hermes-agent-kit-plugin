#!/usr/bin/env python3
"""影武者（shadow）の回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/shadow_test.py

一時ディレクトリを `HERMES_HOME` に見立てる。**本番の ~/.hermes には触らない。**
Slack には繋がない（プラグインの口は差し替えて確かめる）。

守りたいのは:
  * 本人の発言と、ステータスが 🤖 でないあいだの発言は受けない
  * 本人名義で出るものには、必ず代理の印が付く（二重には付かない）
  * 話しかけてよい人は operator と共有し、本人だけを除く。本人が分からないうちは誰も通さない
  * 許可の無い人に、本人の名前で案内やペアリングコードを返さない
  * 別の役（operator）の発言や口には触らない
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

HOME = Path(tempfile.mkdtemp(prefix="shadow-test-"))
os.environ["HERMES_HOME"] = str(HOME)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "templates/booking-gate/sync"))

import build_distributions as bd  # noqa: E402
import env as env_mod  # noqa: E402
import roles  # noqa: E402
import selection  # noqa: E402
import shadow as shadow_cli  # noqa: E402


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


plugin = _load("shadow_plugin", ROOT / "templates/plugins/shadow/__init__.py")
gate_plugin = _load("booking_gate_plugin", ROOT / "templates/booking-gate/plugin/__init__.py")
import booking_sync as bs  # noqa: E402

from _harness import finish, run_tests  # noqa: E402

SELF = "U0SELF0001"
GUEST = "U0GUEST001"
OWNER = "U0OWNER001"


def event(user: str, *, profile: str = "shadow", platform: str = "slack"):
    return SimpleNamespace(source=SimpleNamespace(
        platform=SimpleNamespace(value=platform), profile=profile, user_id=user,
        chat_id="D0CHAT", chat_type="dm"))


def reset_plugin(on: bool) -> None:
    plugin._state.update({"profile": "shadow", "self_id": SELF, "on": on, "checked_at": time.time()})


# ------------------------------------------------------------------ 受信の関門


def test_self_is_always_dropped():
    """本人の発言は、ON でも受けない（手で打った発言が依頼にならない）。"""
    reset_plugin(True)
    assert plugin.gate(event(SELF)) == {"action": "skip", "reason": "shadow-self"}


def test_off_drops_everyone():
    """ステータスが 🤖 でないあいだは、誰の発言も受けない。"""
    reset_plugin(False)
    assert plugin.gate(event(GUEST)) == {"action": "skip", "reason": "shadow-off"}


def test_on_passes_others():
    """ON のあいだは、本人以外の発言を通す（許可の判定は Hermes と booking-gate に任せる）。"""
    reset_plugin(True)
    assert plugin.gate(event(GUEST)) is None


def test_other_profile_is_untouched():
    """operator の発言には触らない（multiplex では全役が同じプロセスにいる）。"""
    reset_plugin(False)
    assert plugin.gate(event(GUEST, profile="operator")) is None
    assert plugin.gate(event(SELF, profile="operator")) is None
    assert plugin.gate(event(GUEST, platform="telegram")) is None


def test_status_reading():
    """🤖 が付いていて、期限が切れていなければ ON。影武者とコマンドで判定がずれない。"""
    now = 1_000_000.0
    cases = [
        ({"status_emoji": ":robot_face:", "status_expiration": 0}, True),
        ({"status_emoji": ":robot_face:", "status_expiration": now + 60}, True),
        ({"status_emoji": ":robot_face:", "status_expiration": now - 60}, False),
        ({"status_emoji": ":palm_tree:", "status_expiration": 0}, False),
        ({}, False),
    ]
    for profile, want in cases:
        assert plugin.status_is_on(profile, now) is want, profile
        assert shadow_cli.is_on(profile, now) is want, profile
    assert plugin.STATUS_EMOJI == shadow_cli.STATUS_EMOJI


# ------------------------------------------------------------------ Slack の口


class FakeAdapter:
    def __init__(self):
        self.sent, self.edited = [], []
        self._bot_user_id = SELF

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.sent.append(content)

    async def edit_message(self, chat_id, message_id, content, *, finalize=False, metadata=None):
        self.edited.append(content)


class FakeClient:
    def __init__(self, profile):
        self.profile = profile

    async def auth_test(self):
        return {"user_id": SELF}

    async def users_profile_get(self):
        return {"profile": self.profile}


class FakeApp:
    def __init__(self, profile):
        self.middleware = []
        self.client = FakeClient(profile)

    def use(self, fn):
        self.middleware.append(fn)


def test_outbound_is_marked_once():
    """本人名義で出るものには印が付き、編集や再接続で二重にならない。"""
    adapter = FakeAdapter()
    plugin._wrap_outbound(adapter)
    plugin._wrap_outbound(adapter)  # 再接続で2回呼ばれても重ねない

    async def go():
        await adapter.send("C1", "調べて返します")
        await adapter.send("C1", plugin.marked("既に印がある"))
        await adapter.edit_message("C1", "1.0", "直しました", finalize=True)
    asyncio.run(go())
    assert adapter.sent == [f"{plugin.MARK}\n調べて返します", f"{plugin.MARK}\n既に印がある"], adapter.sent
    assert adapter.edited == [f"{plugin.MARK}\n直しました"], adapter.edited


def test_wire_watches_status_and_reads_it():
    """接続したらステータスを読み、変化のイベントで ON/OFF を切り替える。本人以外の変化は無視。"""
    plugin._state.update({"profile": "shadow", "self_id": None, "on": False, "checked_at": 0.0, "task": None})
    plugin._is_mine = lambda profile=None: True if profile is None else profile == "shadow"
    app, adapter = FakeApp({"status_emoji": ":robot_face:"}), FakeAdapter()

    async def go():
        plugin.wire(app, adapter)
        await asyncio.sleep(0)  # 最初の読み直し
        await asyncio.sleep(0)
        assert plugin._state["on"] is True, "接続時の読み直しで ON にならない"

        async def nxt():
            return None
        mw = app.middleware[0]
        await mw({"event": {"type": "user_status_changed",
                            "user": {"id": "U0SOMEONE", "profile": {"status_emoji": ""}}}}, nxt)
        assert plugin._state["on"] is True, "他人のステータスで切り替わった"
        await mw({"event": {"type": "user_status_changed",
                            "user": {"id": SELF, "profile": {"status_emoji": ":palm_tree:"}}}}, nxt)
        assert plugin._state["on"] is False, "本人のステータスの変化を見ていない"
        plugin._state["task"].cancel()
    asyncio.run(go())
    assert (HOME / "shadow" / "state.json").is_file(), "外から確かめる痕跡が無い"


# ------------------------------------------------------------------ アクセス許可


def reset_env() -> None:
    env_mod.env_file().unlink(missing_ok=True)
    for name in roles.all_names():
        d = HOME / "profiles" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / ".env").unlink(missing_ok=True)


def test_access_is_shared_without_self():
    """話しかけてよい人は operator と共有し、本人だけを除く。"""
    source = {"OPERATOR__SLACK_ALLOWED_USERS": f"{GUEST},{SELF}", "OPERATOR__SLACK_OWNER_ID": OWNER,
              "SHADOW__SLACK_SELF_ID": SELF}
    [(var, value, _desc)] = roles.derived_env("shadow", source)
    assert var == "SLACK_ALLOWED_USERS"
    assert value.split(",") == [GUEST, OWNER], value


def test_unknown_self_lets_nobody_in():
    """本人の ID が分からないうちは、誰も通さない（本人が混ざるより安全側）。"""
    source = {"OPERATOR__SLACK_ALLOWED_USERS": GUEST, "OPERATOR__SLACK_OWNER_ID": SELF}
    [(_var, value, _desc)] = roles.derived_env("shadow", source)
    assert value == "", value
    assert roles.derived_env("operator", source) == []


def test_env_apply_hands_shadow_the_shared_list():
    """鍵を配ると、影武者に共有の一覧が入り、operator の Slack の鍵は入らない。"""
    reset_env()
    selection.selection_file().unlink(missing_ok=True)
    selection.set_enabled("shadow", True, opt_in=True)
    for key, value in {"OPERATOR__SLACK_BOT_TOKEN": "bot-operator", "OPERATOR__SLACK_ALLOWED_USERS": GUEST,
                       "OPERATOR__SLACK_OWNER_ID": SELF, "SHADOW__SLACK_BOT_TOKEN": "user-shadow",
                       "SHADOW__SLACK_SELF_ID": SELF}.items():
        env_mod.set_value(key, value)
    env_mod.apply()
    got = env_mod.read_env(HOME / "profiles" / "shadow" / ".env")
    assert got.get("SLACK_ALLOWED_USERS") == GUEST, got
    assert got.get("SLACK_BOT_TOKEN") == "user-shadow", got
    assert env_mod.read_env(HOME / "profiles" / "operator" / ".env").get("SLACK_BOT_TOKEN") == "bot-operator"
    selection.selection_file().unlink(missing_ok=True)


def test_gate_is_quiet_on_shadow():
    """booking-gate は、影武者の口では案内を返さない（本人の名前で同僚に届く）。"""
    cfg = {"profile": "operator"}
    gate_plugin._profile["name"] = "shadow"
    assert gate_plugin._gives_notice(cfg) is False
    gate_plugin._profile["name"] = "operator"
    assert gate_plugin._gives_notice(cfg) is True
    assert gate_plugin._gives_notice({"profile": "operator", "notice_profiles": ["operator", "shadow"]})


def test_gate_notice_uses_the_profile_adapter():
    """案内は、発言の来た役の口から出す（default の口には Slack が無い）。"""
    mine = {"slack": object()}
    gw = SimpleNamespace(adapters={}, _adapters_for_profile=lambda p: mine if p == "operator" else {})
    assert gate_plugin._adapters_of(gw, SimpleNamespace(profile="operator")) is mine


def test_guest_approval_reaches_every_gate():
    """ゲストの承認は、ゲートを載せた窓口すべてに置く（アクセス許可は共有）。"""
    for name in ("operator", "shadow", "developer"):
        (HOME / "profiles" / name).mkdir(parents=True, exist_ok=True)
    (HOME / "profiles" / "shadow" / "plugins" / "booking-gate").mkdir(parents=True, exist_ok=True)
    assert bs.gate_profiles({"profile": "operator"}) == ["operator", "shadow"]


# ------------------------------------------------------------------ 配布物


def test_distribution():
    """配布物: 名乗り・プラグイン・黙る設定・絵文字の作法が影武者のものになっている。"""
    spec = bd.ROLES["shadow"]
    soul = bd.build_soul(ROOT, "shadow", spec)
    assert soul.startswith("あなたの名前は **shadow** である"), soul[:40]
    assert "影武者" in soul
    cfg = bd.build_config(ROOT, "shadow", spec)
    assert cfg["platforms"]["slack"]["unauthorized_dm_behavior"] == "ignore", \
        "許可の無い人に、本人の名前でペアリングコードを返してしまう"
    assert {"shadow", "booking-gate"} <= set(cfg["plugins"]["enabled"])
    assert cfg["display"]["platforms"]["slack"]["interim_assistant_messages"] is False
    assert "slack-reactions" not in bd.skills_of(ROOT, "shadow", spec)
    assert "SLACK_BOT_TOKEN" in spec["env_own"] and "SLACK_APP_TOKEN" in spec["env_own"], \
        "operator と鍵が混ざる"
    # operator の設定は影武者の分で変わらない
    assert "display" not in bd.build_config(ROOT, "operator", bd.ROLES["operator"])


run_tests(dict(globals()))
finish()
