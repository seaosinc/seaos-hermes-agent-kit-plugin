#!/usr/bin/env python3
"""テンプレートから消えたものを ~/.hermes からも消す。

`hermes-kit update` はテンプレートを ~/.hermes へ**コピーする**だけなので、
テンプレート側でファイルを消しても、配布先には残り続ける。共通ブロックなら
消したはずの規約が配られ続け、スキルなら存在しない規約を担当が読む。

**前回配ったものの記録（マニフェスト）にあるものだけを消す。** Hermes 組み込みの
スキルや、人が置いたファイルには触らない。

    prune_orphans.py <KIT_ROOT> <HERMES_HOME> [dry]
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

MANIFEST_NAME = ".hermes-kit-manifest.json"


def current(kit: Path) -> dict:
    """マニフェスト。``kit_root`` は ~/.hermes 側から動くもの（フック）が
    キットの場所を知る唯一の手段なので残す。"""
    return {"kit_root": str(kit)}


# 配布モデルへ移る前にキットが自分で配っていた場所。**もう誰も更新しない。**
# 残っていると「古い規約が生きている」ように見えるので畳む。
LEGACY = (
    "shared",                    # 共通ブロックは SOUL に差し込まれるようになった
    "skills/kanban-collaboration",
    "skills/delegate-to-cli-agents",
    "skills/guest-access",
    "booking-gate/bin",          # ゲートの実体はプロファイルの scripts/ へ
    "hooks",                     # フックはプロファイル配下へ
    "plugins/booking-gate",      # プラグインもプロファイル配下へ
)


def main() -> int:
    kit, home = Path(sys.argv[1]), Path(sys.argv[2])
    dry = len(sys.argv) > 3 and sys.argv[3] not in ("0", "")
    manifest_path = home / MANIFEST_NAME
    try:
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        old = {}

    now = current(kit)
    removed = []

    for rel in LEGACY:
        path = home / rel
        if not path.exists():
            continue
        removed.append(str(path))
        if not dry:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink()

    if not dry:
        manifest_path.write_text(json.dumps(now, indent=2, ensure_ascii=False), encoding="utf-8")

    if removed:
        for r in removed:
            print(f"  {'~' if dry else '-'} {r.replace(str(home), '~/.hermes')}")
    else:
        print("  = 取り残しなし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
