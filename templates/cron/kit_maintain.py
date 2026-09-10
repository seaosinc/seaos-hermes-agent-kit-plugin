#!/usr/bin/env python3
"""保守一式（反映 → 掃除 → 検証）。doctor が重いので日次で回す。

問題があったときだけ喋る。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kit_common import kit, out  # noqa: E402


def main() -> int:
    proc = kit("maintain")
    body = out(proc)

    if proc.returncode != 0:
        print("保守が問題を検出した:")
        for line in [l for l in body.splitlines() if "✗" in l or "★" in l][:20]:
            print(line.strip())

    # 物理削除が起きたときは残しておきたい
    for line in body.splitlines():
        if "件を物理削除" in line:
            print(line.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
