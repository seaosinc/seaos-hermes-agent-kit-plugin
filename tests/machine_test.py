#!/usr/bin/env python3
"""この PC の道具を揃える仕組み（provisioner）の回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/machine_test.py

**実際には何も入れない。** 探索と実行を差し替えて、判断だけを確かめる。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="machine-test-"))
os.environ["HERMES_HOME"] = str(HOME)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import build_distributions as bd  # noqa: E402
import machine  # noqa: E402
import selection  # noqa: E402

from _harness import finish, run_tests  # noqa: E402


def test_refuses_unlisted_tool():
    """台帳に無い道具は入れない（Slack 由来の依頼で任意のパッケージを入れさせない）。"""
    for bad in ("curl", "docker; rm -rf /", "openssh"):
        try:
            machine.install(bad)
        except machine.MachineError:
            continue
        raise AssertionError(f"{bad} を受け付けた")


def test_needed_by_follows_selection():
    """Docker を要る役は、箱を持つ有効な役。外せば要らなくなる。"""
    selection.selection_file().unlink(missing_ok=True)
    assert "developer" in machine.needed_by("docker")
    # mem0 を起こすのは operator のフックだが、使うのは全役。役名では出さない
    assert "operator" not in machine.needed_by("docker"), machine.needed_by("docker")
    assert machine.SHARED_MEMORY in machine.needed_by("docker")
    assert "handler" in machine.needed_by("node"), machine.needed_by("node")
    selection.set_enabled("handler", False)
    assert "handler" not in machine.needed_by("node")
    selection.selection_file().unlink(missing_ok=True)


def test_missing_means_needed_and_absent():
    original = machine.find, machine._docker_running
    try:
        machine.find = lambda _c: None
        rows = {r["name"]: r for r in machine.status()}
        assert rows["docker"]["missing"] and rows["node"]["missing"]
        selection.set_enabled("handler", False)
        rows = {r["name"]: r for r in machine.status()}
        assert not rows["node"]["missing"], "誰も使わないものを足りないと言った"
        selection.selection_file().unlink(missing_ok=True)
        machine.find = lambda c: f"/bin/{c}"
        machine._docker_running = lambda: False
        rows = {r["name"]: r for r in machine.status()}
        assert rows["docker"]["missing"], "止まっている Docker を足りていると言った"
        assert not rows["node"]["missing"]
    finally:
        machine.find, machine._docker_running = original


def test_needs_human_when_manager_absent():
    """Homebrew / winget が無ければ、人に渡す（勝手に入れない）。"""
    original = machine.find
    try:
        machine.find = lambda _c: None
        res = machine.install("node")
    except machine.MachineError:
        return  # この OS に手順が無い（Linux）
    finally:
        machine.find = original
    assert not res["ok"] and res["needsHuman"], res


def test_role_is_distributed():
    out = Path(tempfile.mkdtemp(prefix="dist-prov-"))
    bd.build(ROOT, out)
    soul = (out / "provisioner" / "SOUL.md").read_text(encoding="utf-8")
    assert soul.startswith("あなたの名前は **provisioner**")
    cfg = bd.build_config(ROOT, "provisioner", bd.ROLES["provisioner"])
    assert "terminal" in cfg["platform_toolsets"]["cli"], "道具を入れる手が無い"
    assert "terminal" not in cfg or cfg.get("terminal", {}).get("backend") != "docker", \
        "箱の中からホストへは入れられない"
    assert "machine-guard" in bd.ROLES["operator"]["cron"]


def _guard():
    spec = importlib.util.spec_from_file_location("machine_guard", ROOT / "templates/cron/machine_guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_guard_does_not_duplicate_open_cards():
    g = _guard()
    db = HOME / "kanban.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE tasks (id TEXT, idempotency_key TEXT, status TEXT)")
        conn.execute("INSERT INTO tasks VALUES ('t1', 'machine:docker:2026-W30', 'blocked')")
        conn.execute("INSERT INTO tasks VALUES ('t2', 'machine:node:2026-W30', 'done')")
    assert g.open_card(db, "docker"), "承認待ちのカードがあるのに立て直す"
    assert not g.open_card(db, "node"), "閉じたカードを開いていると見た"


def test_guard_respects_disabled_provisioner():
    g = _guard()
    (HOME / "profiles" / "provisioner").mkdir(parents=True, exist_ok=True)
    (HOME / "seaos-kit").mkdir(exist_ok=True)
    (HOME / "seaos-kit" / "roles.json").write_text(json.dumps({"disabled": []}))
    assert g.provisioner_available(HOME)
    (HOME / "seaos-kit" / "roles.json").write_text(json.dumps({"disabled": ["provisioner"]}))
    assert not g.provisioner_available(HOME)


if __name__ == "__main__":
    run_tests(globals())
    finish()
