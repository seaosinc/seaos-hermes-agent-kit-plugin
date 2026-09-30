#!/usr/bin/env python3
"""テストをまとめて走らせる。

    ~/.hermes/hermes-agent/venv/bin/python tests/run_all.py

**本番の ~/.hermes には触らない**（各テストが一時ディレクトリを HOME に見立てる）。
Hermes 本体を動かすテスト（`_harness.CI_ONLY`）は、ここからは流さない。
一時 HOME でも、この PC の Hermes のインストール先を書き換えるからである。
それらは GitHub Actions の「Hermes 契約検査」が流す。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _harness import CI_ONLY  # noqa: E402


def main() -> int:
    failed: list[str] = []
    for test in sorted(HERE.glob("*_test.py")):
        if test.name in CI_ONLY:
            print(f"- {test.name}（Hermes 本体を動かすので、GitHub の Hermes 契約検査で走る）")
            continue
        started = time.time()
        proc = subprocess.run([sys.executable, str(test)], capture_output=True, text=True)
        took = time.time() - started
        if proc.returncode == 0:
            print(f"✓ {test.name}（{took:.0f}秒）")
        else:
            failed.append(test.name)
            print(f"✗ {test.name}（{took:.0f}秒）")
            print("\n".join(l for l in proc.stdout.splitlines() if "✗" in l or l.startswith("      ")))
            if proc.stderr.strip():
                print(proc.stderr.strip()[-1500:])
    print()
    if failed:
        print(f"★ {len(failed)} 本が失敗: {' '.join(failed)}")
        return 1
    print("すべて通った")
    return 0


if __name__ == "__main__":
    sys.exit(main())
