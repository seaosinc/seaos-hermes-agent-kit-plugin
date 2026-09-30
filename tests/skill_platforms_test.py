#!/usr/bin/env python3
"""キットのスキルが、どの OS でも読めることの回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/skill_platforms_test.py

Hermes はスキルの `platforms:` にいまの OS が無いと、そのスキルを読まない
（「Skill '…' is not supported on this platform.」）。キットのスキルは全部 `[macos, linux]` だったので、
Windows ではどの役もスキルを1本も読めず、operator は受付の手順（request-intake）を読めないまま
通知の紐付けを落とし、カードが終わっても起こされなかった（2026-09-30、Windows の PC で実際に起きた）。

**キットは macOS / Windows / Linux で動かす。** `platforms:` は書かない（書かなければ全 OS で読める）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import finish, run_tests  # noqa: E402


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    return yaml.safe_load(text.split("---", 2)[1]) or {}


def test_no_skill_is_limited_to_some_os():
    """どのスキルも OS を絞らない（Windows で読めなくなる）。"""
    limited = [str(p.relative_to(ROOT)) for p in ROOT.glob("templates/**/SKILL.md")
               if _frontmatter(p).get("platforms")]
    assert not limited, f"platforms を書いたスキルがある（Windows で読めない）: {limited}"


run_tests(dict(globals()))
finish()
