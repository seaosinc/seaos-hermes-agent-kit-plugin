#!/usr/bin/env python3
"""テストをまとめて走らせる。

    ~/.hermes/hermes-agent/venv/bin/python tests/run_all.py            # 速いものだけ
    ~/.hermes/hermes-agent/venv/bin/python tests/run_all.py --all      # hermes を実際に呼ぶものも

**本番の ~/.hermes には触らない**（各テストが一時ディレクトリを HOME に見立てる）。
`fresh_install_test` は hermes で実際にプロファイルを入れるので遅い。既定では飛ばす。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLOW = {"fresh_install_test.py"}


def main() -> int:
    run_slow = "--all" in sys.argv[1:]
    failed: list[str] = []
    for test in sorted(HERE.glob("*_test.py")):
        if test.name in SLOW and not run_slow:
            print(f"- {test.name}（遅いので飛ばす。--all で走る）")
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
