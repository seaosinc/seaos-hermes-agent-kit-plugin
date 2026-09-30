"""生成物の**形**を検査する。

**壊れていてもインストールは通ってしまう**ので、ここで形を見る。
秒で終わるので普段の検査に使う（振る舞いの検査は evals/ が別に持つ）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from paths import kit_root

Log = Callable[[str], None]


def _ci_only(tests: Path) -> set:
    """Hermes 本体を動かすので GitHub でだけ走らせるテスト（tests/_harness.py の CI_ONLY）。"""
    sys.path.insert(0, str(tests))
    try:
        from _harness import CI_ONLY
    finally:
        sys.path.remove(str(tests))
    return set(CI_ONLY)


def suites() -> List[Path]:
    """手元で流すテスト。**Hermes 本体を動かすものは含めない**——一時 HOME で動かしても、
    この PC の Hermes のインストール先を書き換える（実際に Hermes Desktop が壊れた）。"""
    tests = kit_root() / "tests"
    skip = _ci_only(tests)
    return sorted(p for p in tests.glob("*_test.py") if p.name not in skip)


def run(log: Optional[Log] = None) -> Tuple[bool, List[str]]:
    say: Log = log or (lambda _l: None)
    lines: List[str] = []
    ok = True
    for path in suites():
        say(f"=== {path.stem} ===")
        proc = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        lines.extend(out.splitlines())
        for line in out.splitlines():
            say(line)
        if proc.returncode != 0:
            ok = False
    say("")
    say("すべて通った" if ok else "★ 失敗あり")
    return ok, lines
