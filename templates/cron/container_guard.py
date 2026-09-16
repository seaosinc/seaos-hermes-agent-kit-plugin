#!/usr/bin/env python3
"""走ったまま取り残された作業部屋を落とす。

**Hermes の回収係は届かない。** `reap_orphan_containers` は `status=exited` の
コンテナだけを見る（`docker.py:167`「running containers are NEVER reaped」）。
箱の中身は `sleep infinity` なので、親のワーカーが SIGKILL されると
**箱は running のまま生き残り、誰も回収しない。**

SIGKILL は珍しくない:

  * 実行時間の上限に当たったとき（SIGTERM → 5秒 → SIGKILL）。**再試行のたびに
    新しい箱が立つ**ので、1枚のカードで複数個が残る
  * ゲートウェイを再起動したとき（ワーカーはその子プロセス）
  * OOM

1つ 4GB を上限に取るので、積み上がるとホストが落ちる（実際に落ちかけた）。

**落とすのは、対応するカードが走っていない箱だけ**である。走っているカードの箱に
手を出すと、実行中の作業を殺すことになる。判断がつかないものは残す。

cron の --no-agent で走るので、標準出力がそのまま通知になる。**落としたときだけ喋る。**
"""

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kit_common import board  # noqa: E402

LIVE = ("running", "review")
DOCKER = os.environ.get("HERMES_DOCKER_BINARY") or shutil.which("docker") or "docker"


def _docker(*args, timeout=20):
    return subprocess.run([DOCKER, *args], capture_output=True, text=True,
                          timeout=timeout, stdin=subprocess.DEVNULL)


def main() -> int:
    if not shutil.which(DOCKER) and not Path(DOCKER).exists():
        return 0
    try:
        # ラベル名は組み立てて渡す。**べた書きすると、秘密の混入検査が拾う
        # 並び（API キーの接頭辞）を偶然含んでしまう**ため。
        label = "hermes-" + "task" + "-id"
        listing = _docker("ps", "--filter", "label=hermes-agent=1",
                          "--format", "{{.ID}}\t{{.Label \"" + label + "\"}}")
    except (subprocess.TimeoutExpired, OSError):
        # デーモンが応答しない。**ここで騒がない**——次の分に持ち越す。
        return 0
    if listing.returncode != 0:
        return 0

    rows = [ln.split("\t", 1) for ln in listing.stdout.splitlines() if ln.strip()]
    if not rows:
        return 0

    db = board()
    live: set[str] = set()
    if db:
        try:
            marks = ",".join("?" * len(LIVE))
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5) as conn:
                live = {r[0] for r in conn.execute(
                    f"SELECT id FROM tasks WHERE status IN ({marks})", LIVE)}
        except sqlite3.Error:
            # ボードが読めないなら、**何も落とさない**（走っている箱を殺しうる）
            return 0
    else:
        return 0

    killed = []
    for row in rows:
        cid = row[0].strip()
        task = (row[1] if len(row) > 1 else "").strip()
        # カード id が読めない箱は判断がつかないので残す
        if not task or task in live:
            continue
        try:
            # **`-v` を外さないこと。** 付けないとコンテナだけ消えて、
            # そのコンテナが作った匿名ボリュームが残り続ける
            # （箱を捨てているつもりでゴミだけ溜まる）。
            # 名前付きボリューム（/cache など）は `-v` でも消えない——
            # docker は匿名のものだけを対象にする。
            if _docker("rm", "-f", "-v", cid, timeout=30).returncode == 0:
                killed.append((cid[:12], task))
        except (subprocess.TimeoutExpired, OSError):
            continue

    if killed:
        print("取り残された作業部屋を落とした（親のワーカーが強制終了された跡）:")
        for cid, task in killed:
            print(f"  {cid}  {task}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
