#!/usr/bin/env python3
"""Hermes 本体を動かすテストが、手元では走らないことの回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/ci_only_test.py

2026-09-30、手元で `run_all.py --all` を叩いたら、fresh_install_test が一時 HOME で
Hermes を動かし、この PC の Hermes の起動スクリプトを一時 HOME の Python で書き直した。
一時 HOME が消えて、Hermes Desktop が「未インストール」の初期画面に戻った。

**Hermes は呼ばない。** 呼ばれたら印を書くだけの偽物を HERMES_BIN に置いて確かめる。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "core"))

import selftest  # noqa: E402

from _harness import CI_ONLY, finish, run_tests  # noqa: E402


def _fake_hermes() -> tuple[Path, Path]:
    d = Path(tempfile.mkdtemp(prefix="ci-only-test-"))
    called = d / "called"
    fake = d / "hermes"
    fake.write_text(f"#!/bin/sh\ntouch '{called}'\n", encoding="utf-8")
    fake.chmod(0o755)
    return fake, called


def test_refuses_outside_ci():
    """手元で叩いても、Hermes を呼ばず、一時 HOME も作らずに止まる。"""
    fake, called = _fake_hermes()
    tmp = Path(tempfile.mkdtemp(prefix="ci-only-tmp-"))
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
    env.update({"HERMES_BIN": str(fake), "TMPDIR": str(tmp)})
    for name in CI_ONLY:
        proc = subprocess.run([sys.executable, str(HERE / name)], env=env,
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 2, f"{name}: 止まらなかった（rc={proc.returncode}）\n{proc.stdout}"
        assert "GitHub Actions" in proc.stdout, proc.stdout
    assert not called.exists(), "手元で Hermes を呼んだ"
    assert not list(tmp.glob("hermes-fresh-*")), "手元で一時 HOME を作った"


def test_local_runners_skip_it():
    """手元の入口（seaos-kit test と run_all.py）は、Hermes を動かすテストを流さない。"""
    names = {p.name for p in selftest.suites()}
    assert not (names & CI_ONLY), names & CI_ONLY
    src = (HERE / "run_all.py").read_text(encoding="utf-8")
    assert "--all" not in src, "run_all.py に手元で Hermes を動かす入口が残っている"


def test_ci_still_runs_it():
    """GitHub の Hermes 契約検査は、これまでどおり流す（手元から外しただけで、検査は減らさない）。"""
    wf = (ROOT / ".github/workflows/hermes.yml").read_text(encoding="utf-8")
    for name in CI_ONLY:
        assert f"tests/{name}" in wf, f"{name} がどこでも流れなくなる"


run_tests(dict(globals()))
finish()
