#!/usr/bin/env python3
"""無効にした役へ仕事が流れて止まらないかの回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/disabled_roles_test.py

Hermes は担当の実在を確かめない。存在しない役に振られたカードは ready のまま
永久に残り、親は待ち続ける。**規約から名前を落とす**ことと、**取りこぼしを止める網**の
両方を確かめる。本番の ~/.hermes には触らない。
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import build_distributions as bd  # noqa: E402

failures: list[str] = []


def check(name: str, fn) -> None:
    try:
        fn()
    except AssertionError as e:
        failures.append(name)
        print(f"  ✗ {name}\n      {e}")
    except Exception as e:  # noqa: BLE001
        failures.append(name)
        print(f"  ✗ {name}\n      {type(e).__name__}: {e}")
    else:
        print(f"  ✓ {name}")


ALL = set({**bd.ROLES, **bd.worker_roles(ROOT)})


def build(enabled):
    out = Path(tempfile.mkdtemp(prefix="dist-roles-"))
    bd.build(ROOT, out, enabled)
    return out


def rules(out: Path, role: str) -> str:
    parts = [(out / role / "SOUL.md").read_text(encoding="utf-8")]
    parts += [p.read_text(encoding="utf-8") for p in (out / role / "skills").glob("*/SKILL.md")]
    return "\n".join(parts)


def test_no_markers_leak():
    """囲みの印そのものは、全役有効でも一部無効でも配布物に残らない。"""
    for enabled in (None, ALL - {"senior-developer", "recruiter", "broker"}):
        out = build(enabled)
        for f in out.rglob("*.md"):
            text = f.read_text(encoding="utf-8")
            assert "if-role" not in text and "<!-- else -->" not in text, f


def test_disabled_names_disappear_from_routing_rules():
    """外した役の名前が、振る側（fixer / operator）の規約に残らない。"""
    off = {"senior-developer", "recruiter", "broker", "handler"}
    out = build(ALL - off)
    for role in ("fixer", "operator"):
        text = rules(out, role)
        for name in off:
            # 「無効になっている」「有効にすれば」と説明する文だけは許す
            leftover = [l for l in text.splitlines()
                        if f"`{name}`" in l or f" {name} " in l or f"{name} へ" in l]
            leftover = [l for l in leftover if "無効" not in l and "有効に" not in l]
            assert not leftover, (role, name, leftover[:3])


def test_full_build_keeps_everything():
    out = build(None)
    assert "senior-developer は、難度ではなく根拠で振る" in rules(out, "fixer")
    assert "recruiter" in rules(out, "operator")


def test_description_follows_selection():
    spec = bd.ROLES["developer"]["describe"]
    assert "senior-developer" in bd.strip_role_blocks(spec, None)
    assert "senior-developer" not in bd.strip_role_blocks(spec, ALL - {"senior-developer"})


def _board(home: Path, rows):
    db = sqlite3.connect(home / "kanban.db")
    db.execute("CREATE TABLE tasks (id TEXT, assignee TEXT, title TEXT, status TEXT)")
    db.executemany("INSERT INTO tasks VALUES (?,?,?,?)", rows)
    db.commit()
    db.close()


def test_guard_blocks_unrunnable_assignees():
    """存在しない役・無効にした役に振られた ready だけを止める。"""
    home = Path(tempfile.mkdtemp(prefix="guard-"))
    for name in ("developer", "avatar"):
        (home / "profiles" / name).mkdir(parents=True)
    (home / "seaos-kit").mkdir()
    (home / "seaos-kit" / "roles.json").write_text(json.dumps({"disabled": ["avatar"]}))
    _board(home, [
        ("t_ok", "developer", "動ける", "ready"),
        ("t_gone", "senior-developer", "存在しない", "ready"),
        ("t_off", "avatar", "無効", "ready"),
        ("t_todo", "senior-developer", "まだ todo", "todo"),
    ])
    log = home / "calls.txt"
    fake = home / "hermes"
    fake.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\n")
    fake.chmod(0o755)
    env = {**os.environ, "HERMES_HOME": str(home), "HERMES_BIN": str(fake)}
    r = subprocess.run([sys.executable, str(ROOT / "templates/cron/assignee_guard.py")],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    calls = log.read_text(encoding="utf-8") if log.exists() else ""
    assert "block t_gone" in calls and "block t_off" in calls, calls
    assert "t_ok" not in calls and "t_todo" not in calls, calls
    assert "t_gone" in r.stdout, r.stdout


def test_guard_is_registered():
    assert "assignee-guard" in bd.ROLES["operator"]["cron"]
    assert bd.CRON_JOBS["assignee-guard"][1] == "assignee_guard.py"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(fn.__doc__.splitlines()[0] if fn.__doc__ else name, fn)
    print()
    if failures:
        print(f"★ {len(failures)} 件失敗")
        sys.exit(1)
    print("すべて通った")
