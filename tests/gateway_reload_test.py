#!/usr/bin/env python3
"""反映で窓口の読み込むものが変わったら、その役だけを起こし直すことの回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/gateway_reload_test.py

プラグインや鍵は、ゲートウェイが役を載せるときにしか読まれない。反映しても起こし直さなければ
古いまま動き、「反映したのに何も変わらない」になる。

一時ディレクトリを `HERMES_HOME` に見立てる。**ゲートウェイには触らない**（起こし直す口は偽物）。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="gateway-reload-test-"))
os.environ["HERMES_HOME"] = str(HOME)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import kit  # noqa: E402
import platform_ops  # noqa: E402
import roles  # noqa: E402

from _harness import finish, run_tests  # noqa: E402

OP = HOME / "profiles" / "operator"


def setup() -> list:
    (OP / "plugins" / "owner-away").mkdir(parents=True, exist_ok=True)
    (OP / "config.yaml").write_text("model:\n  default: x\nagent:\n  environment_hint: A\n", encoding="utf-8")
    (OP / ".env").write_text("SLACK_BOT_TOKEN=one\n", encoding="utf-8")
    (OP / "plugins" / "owner-away" / "__init__.py").write_text("v1\n", encoding="utf-8")
    calls: list = []
    platform_ops.serves_here = lambda name: True
    platform_ops.restart_later = lambda name: calls.append(name) or True
    return calls


def test_unchanged_does_not_restart():
    """何も変わらなければ起こし直さない（定期実行の反映は10分ごとに走る）。"""
    calls = setup()
    before = kit._gateway_fingerprints()
    kit._restart_changed_gateways(before, kit.Result())
    assert calls == [], calls


def test_hint_only_change_does_not_restart():
    """会話のたびに読まれる実測値（environment_hint）だけの変化では起こし直さない。"""
    calls = setup()
    before = kit._gateway_fingerprints()
    (OP / "config.yaml").write_text("model:\n  default: x\nagent:\n  environment_hint: B\n", encoding="utf-8")
    kit._restart_changed_gateways(before, kit.Result())
    assert calls == [], calls


def test_plugin_key_or_config_change_restarts_only_that_role():
    """プラグイン・鍵・設定が変われば、その窓口だけを起こし直す。"""
    for change in (lambda: (OP / "plugins" / "owner-away" / "__init__.py").write_text("v2\n", encoding="utf-8"),
                   lambda: (OP / ".env").write_text("SLACK_BOT_TOKEN=two\n", encoding="utf-8"),
                   lambda: (OP / "config.yaml").write_text("model:\n  default: y\n", encoding="utf-8")):
        calls = setup()
        before = kit._gateway_fingerprints()
        change()
        result = kit.Result()
        kit._restart_changed_gateways(before, result)
        assert calls == ["operator"], calls
        assert any("起こし直します" in line for line in result.lines), result.lines
    gateways = [n for n in roles.names() if (roles.all_specs().get(n) or {}).get("gateway")]
    assert set(kit._gateway_fingerprints()) == set(gateways), "窓口でない役まで見ている"


def test_stopped_gateway_is_left_alone():
    """止まっている窓口は起こさない（止めたのは人の判断かもしれない）。"""
    calls = setup()
    before = kit._gateway_fingerprints()
    (OP / ".env").write_text("SLACK_BOT_TOKEN=three\n", encoding="utf-8")
    platform_ops.serves_here = lambda name: False
    kit._restart_changed_gateways(before, kit.Result())
    assert calls == [], calls


def test_restart_later_does_not_pile_up():
    """待っている起こし直しがあれば、足さない（定期実行と手の反映が重なっても1回）。"""
    import importlib
    ops = importlib.reload(platform_ops)
    spawned: list = []

    class Proc:
        pid = os.getpid()  # 生きている pid として扱わせる

    real_popen = ops.subprocess.Popen
    ops.subprocess.Popen = lambda args, **kw: spawned.append(args) or Proc()
    try:
        (OP / "logs" / "gateway-restart.pending").unlink(missing_ok=True)
        assert ops.restart_later("operator")
        assert ops.restart_later("operator")
    finally:
        ops.subprocess.Popen = real_popen
    assert len(spawned) == 1, spawned
    assert spawned[0][-3:] == ["restart", "operator", "--when-idle"], spawned[0]


def test_other_hermes_host_is_not_restarted():
    """一時 HOME での反映は、この PC で本当に動いているホストを起こし直さない。"""
    import importlib
    ops = importlib.reload(platform_ops)
    elsewhere = ops.Host(pid=os.getpid(), home=Path(tempfile.mkdtemp(prefix="other-hermes-")),
                         profiles=("default", "operator"))
    ops.host = lambda: elsewhere
    assert not ops.serves_here("operator"), "別の Hermes のホストを自分のものとみなした"
    ops.host = lambda: ops.Host(pid=os.getpid(), home=HOME, profiles=("default", "operator"))
    assert ops.serves_here("operator")
    assert not ops.serves_here("fixer")


run_tests(dict(globals()))
finish()
