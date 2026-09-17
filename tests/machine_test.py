#!/usr/bin/env python3
"""この PC の道具（台帳・入れ方の案内）の回帰テスト。

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
    # 台帳の名前に余計なものを継ぎ足した指定も、台帳に無い名前として断る
    for bad in ("curl", "docker && echo injected", "openssh"):
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


def test_provisioner_is_retired():
    """provisioner と machine-guard は廃止した。配らず、入っている環境からは update が外す。"""
    assert "provisioner" not in bd.ROLES
    assert "provisioner" in bd.RETIRED_ROLES
    assert "machine-guard" not in bd.ROLES["operator"]["cron"]
    assert "machine-guard" not in bd.CRON_JOBS
    assert "machine-guard" in bd.RETIRED_CRONS


def test_status_shows_how_to_install_or_start():
    """足りない道具には、この OS での入れ方（Docker は起こし方も）を持たせる。"""
    rows = {r["name"]: r for r in machine.status()}
    for name in ("docker", "node"):
        assert "installCommand" in rows[name] and "startHint" in rows[name], rows[name]
    assert machine.CATALOG["docker"].start, "Docker の起こし方が無い"
    for hint in machine.CATALOG["docker"].start.values():
        assert "Docker Desktop" in hint and ":\\" not in hint, "起こし方をパスで出している"


if __name__ == "__main__":
    run_tests(globals())
    finish()
