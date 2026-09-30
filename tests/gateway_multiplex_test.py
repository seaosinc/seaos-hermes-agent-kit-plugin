#!/usr/bin/env python3
"""ゲートウェイが1台に1つ（multiplex）になったあとの常駐操作の回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/gateway_multiplex_test.py

守りたいのは:
  * 役の再起動・停止は `hermes -p <役> gateway restart / stop` でホストに頼む
    （`hermes --profile <役> gateway run` を起こして pgrep で探すと、ホストがその役を
    拾い直してすぐ終わるので「再起動に失敗」と誤表示していた）
  * 動いているかはホストの記録（host-gateway.json）の pid と受け持ちで見る
  * ホストを起こすときは default から、HERMES_PROFILE を持たせずに起こす
    （持たせると、全役の子プロセスがその名前を名乗る）
  * その役がホストを起こした役なら、役だけ外さずホストごと起こし直す

**実機の Hermes には触らない。** hermes.run と subprocess.Popen を差し替え、
記録は一時ディレクトリに置く。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import hermes  # noqa: E402
import platform_ops  # noqa: E402

from _harness import finish, run_tests  # noqa: E402

# 生きていることが確かな pid（このテスト自身）。死んでいる pid は、まず使われない大きな値。
ALIVE = os.getpid()
DEAD = 2 ** 22 - 7


class Fake:
    """ホストの記録と、Hermes の呼び出しを手元で演じる。"""

    def __init__(self):
        base = Path(tempfile.mkdtemp(prefix="gw-mux-"))
        self.home = base / "hermes"
        self.locks = base / "locks"
        (self.home / "profiles" / "operator").mkdir(parents=True)
        (self.home / "profiles" / "shadow").mkdir(parents=True)
        self.locks.mkdir()
        self.calls: list = []
        self.spawned: list = []
        self.killed: list = []
        self.on_run = None       # (args) -> (code, out)
        self.on_spawn = None     # () -> None
        self._saved = {}

    # ── 記録 ──
    def record(self, pid, profiles, home=None):
        (self.locks / "host-gateway.json").write_text(json.dumps({
            "role": "gateway", "home": str(home or self.home), "pid": pid,
            "profiles": list(profiles),
        }), encoding="utf-8")

    def drop_record(self):
        (self.locks / "host-gateway.json").unlink(missing_ok=True)

    def served(self):
        data = json.loads((self.locks / "host-gateway.json").read_text(encoding="utf-8"))
        return data["profiles"]

    # ── 差し替え ──
    def __enter__(self):
        env = {"HERMES_HOME": str(self.home), "HERMES_GATEWAY_LOCK_DIR": str(self.locks),
               "HOME": str(self.home.parent), "HERMES_PROFILE": "recruiter",
               "HERMES_KANBAN_TASK": "t_self"}
        self._saved["env"] = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        self._saved["run"] = hermes.run
        self._saved["popen"] = platform_ops.subprocess.Popen
        self._saved["sleep"] = platform_ops.time.sleep
        self._saved["which"] = platform_ops.shutil.which
        self._saved["terminate"] = platform_ops._terminate
        self._saved["kill"] = platform_ops._kill
        self._saved["os_kind"] = platform_ops.os_kind

        def fake_run(args, **kw):
            self.calls.append(list(args))
            if self.on_run:
                return self.on_run(list(args))
            return 0, ""

        def fake_popen(argv, **kw):
            self.spawned.append((list(argv), dict(kw.get("env") or {})))
            if self.on_spawn:
                self.on_spawn()

        hermes.run = fake_run
        platform_ops.subprocess.Popen = fake_popen
        platform_ops.time.sleep = lambda s: None
        platform_ops.shutil.which = lambda name: "/usr/local/bin/hermes"
        platform_ops._terminate = lambda pid: self.killed.append(pid)
        platform_ops._kill = lambda pid: self.killed.append(pid)
        # CI は Linux。systemd の unit は無い（HOME を一時ディレクトリにしてある）ので、
        # どの OS でも素のプロセスの経路を通る。pid の生存確認だけは本物の OS で行う。
        return self

    def __exit__(self, *exc):
        for k, v in self._saved["env"].items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        hermes.run = self._saved["run"]
        platform_ops.subprocess.Popen = self._saved["popen"]
        platform_ops.time.sleep = self._saved["sleep"]
        platform_ops.shutil.which = self._saved["which"]
        platform_ops._terminate = self._saved["terminate"]
        platform_ops._kill = self._saved["kill"]
        platform_ops.os_kind = self._saved["os_kind"]


def gateway_calls(fake):
    return [c for c in fake.calls if "gateway" in c]


def test_pid_is_the_host_when_served():
    """受け持たれている役の pid はホストの pid。受け持たれていない役・死んだホストは None。"""
    with Fake() as f:
        f.record(ALIVE, ["default", "operator"])
        assert platform_ops.gateway_pid("operator") == ALIVE
        assert platform_ops.gateway_pid("shadow") is None, "受け持っていない役に pid を返した"
        f.record(DEAD, ["default", "operator"])
        assert platform_ops.gateway_pid("operator") is None, "死んだホストの記録を信じた"
        f.drop_record()
        assert platform_ops.gateway_pid("operator") is None


def test_restart_one_role_asks_the_host():
    """ホストが動いていれば、その役だけを `hermes -p <役> gateway restart` で起こし直す。"""
    with Fake() as f:
        f.record(ALIVE, ["default", "operator", "shadow"])
        f.on_run = lambda a: (0, "Profile 'shadow' restarted by the host gateway.\n")
        lines: list = []
        assert platform_ops.restart_gateway("shadow", log=lines.append), lines
        assert gateway_calls(f) == [["-p", "shadow", "gateway", "restart"]], f.calls
        assert not f.spawned, "役の再起動でプロセスを起こした（ホストが拾い直してすぐ終わる）"
        assert not f.killed, "役の再起動でホストを止めた"


def test_restart_unconfirmed_is_failure():
    """Hermes が「外せなかった」と言ったら、受け持ちに残っていても失敗と数える。"""
    with Fake() as f:
        f.record(ALIVE, ["default", "shadow"])
        f.on_run = lambda a: (0, "Profile 'shadow' restart was not confirmed: host control socket did not answer.\n")
        assert not platform_ops.restart_gateway("shadow"), "古いアダプタのまま成功にした"


def test_start_host_without_profile_name():
    """ホストが無ければ default から起こす。HERMES_PROFILE やカードの札を持たせない。"""
    with Fake() as f:
        f.drop_record()
        f.on_spawn = lambda: f.record(ALIVE, ["default", "operator"])
        assert platform_ops.restart_gateway("operator")
        assert len(f.spawned) == 1, f.spawned
        argv, env = f.spawned[0]
        assert argv[1:] == ["gateway", "run", "--replace"], argv
        assert "--profile" not in argv and "-p" not in argv, argv
        assert "HERMES_PROFILE" not in env, "ホストに役の名前を持たせた"
        assert not any(k.startswith("HERMES_KANBAN_") for k in env), "ホストにカードの札を持たせた"
        assert env.get("HERMES_HOME") == str(f.home), env.get("HERMES_HOME")


def test_launch_role_restarts_whole_host():
    """その役がホストを起こした役なら、役だけ外さず、ホストごと default から起こし直す。"""
    with Fake() as f:
        # 生きている別の pid が要る。親プロセス（このテストを起こした側）を使う。
        old = os.getppid()
        f.record(old, ["operator", "default"], home=f.home / "profiles" / "operator")
        alive = {"old": True}
        real_alive = platform_ops.pid_alive

        def fake_alive(pid):
            if pid == old:
                return alive["old"]
            return real_alive(pid)

        def on_kill(pid):
            f.killed.append(pid)
            alive["old"] = False

        platform_ops.pid_alive = fake_alive
        platform_ops._terminate = on_kill
        try:
            f.on_spawn = lambda: f.record(ALIVE, ["default", "operator"])
            assert platform_ops.restart_gateway("operator")
        finally:
            platform_ops.pid_alive = real_alive
        assert f.killed == [old], f.killed
        assert len(f.spawned) == 1 and "--profile" not in f.spawned[0][0]
        assert ["-p", "operator", "gateway", "restart"] not in f.calls, \
            "ホストの持ち主を外そうとした（外すと全役が落ちる）"


def test_stop_parks_one_role():
    """役を止めるのは `hermes -p <役> gateway stop`。受け持ちから消えたことで確かめる。"""
    with Fake() as f:
        f.record(ALIVE, ["default", "operator", "shadow"])

        def on_run(args):
            if args == ["-p", "shadow", "gateway", "stop"]:
                f.record(ALIVE, ["default", "operator"])
            return 0, ""

        f.on_run = on_run
        assert platform_ops.stop_gateway("shadow")
        assert not f.killed, "役を止めるのにホストを止めた"
        assert f.served() == ["default", "operator"]


def test_stop_reports_when_still_served():
    """止めたはずの役が受け持ちに残っていれば、失敗と数える。"""
    with Fake() as f:
        f.record(ALIVE, ["default", "shadow"])
        assert not platform_ops.stop_gateway("shadow")


def test_stop_refuses_launch_role():
    """ホストを起こした役は単独で止めない（止めると全役が落ちる）。"""
    with Fake() as f:
        f.record(ALIVE, ["operator", "default"], home=f.home / "profiles" / "operator")
        lines: list = []
        assert not platform_ops.stop_gateway("operator", log=lines.append)
        assert not gateway_calls(f) and not f.killed
        assert any("--host" in l for l in lines), lines


def test_parked_role_is_visible():
    """止めた印があれば、状態にそう出る。"""
    with Fake() as f:
        f.record(ALIVE, ["default", "operator"])
        (f.home / "profiles" / "shadow" / "gateway.parked").write_text("", encoding="utf-8")
        assert platform_ops.is_parked("shadow")
        text = "\n".join(platform_ops.status_lines("shadow"))
        assert "止めてある" in text, text


def test_adapter_state_per_role():
    """役のアダプタの状態は、ホストの状態ファイルの `<役>:<platform>` から読む。"""
    with Fake() as f:
        f.record(ALIVE, ["default", "operator"])
        (f.home / "gateway_state.json").write_text(json.dumps({"platforms": {
            "slack": {"state": "connected"},
            "operator:slack": {"state": "fatal"},
        }}), encoding="utf-8")
        assert platform_ops.adapter_states("operator") == {"slack": "fatal"}
        assert platform_ops.adapter_states("shadow") == {}


def test_running_cards_skip_own_card():
    """カードの中から叩いたとき、自分のカードは走行中に数えない（待ちが終わらなくなる）。"""
    with Fake() as f:
        def on_run(args):
            if args[:2] == ["kanban", "list"] and "running" in args:
                return 0, json.dumps([{"id": "t_self"}, {"id": "t_other"}])
            return 0, "[]"

        f.on_run = on_run
        assert platform_ops.running_cards() == 1


if __name__ == "__main__":
    run_tests(globals())
    finish()
