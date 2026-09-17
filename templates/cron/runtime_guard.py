#!/usr/bin/env python3
"""実行時間の上限が既定（30分）より短いカードを、既定まで引き上げる。

**`0` は「無制限」ではなく「0秒」である。** Hermes は値の有無で判定するので、
0 が入ったカードは起動から15秒で強制終了され、2回失敗すると `gave_up` になって
二度と動かない。

**短すぎる値も同じところへ落ちる。** 0 だけを直していたが、`300` を入れられた
完了判定のカードが `elapsed 2571s > limit 300s` で2回 timeout し、`gave_up` に
なった。しかもそのカードは、**0秒で死んだ別のカードを引き取るために立てられた
もの**である——同じ穴に、別の数字で落ちた。

**上げる方向しか要らない。** 規約（kanban-collaboration）が渡すのは 1800 の一択で、
足りないと分かっている作業だけその場で上げる、と決めてある。**下回る値は
どれも書き間違いである**ため、既定まで引き上げてよい。

規約（kanban-collaboration）にも書いてあるが、**それだけでは止まらなかった**
——「上限なしのつもりで 0」を繰り返し作る。カードを作るときにモデルが読んでいるのは
ツールのスキーマ（`"type": "integer"`）で、規約はそこより遠い。
**規約で守れないものは、入ってしまったあとで直す。**

**ツールで作るカードは、作る前にプラグイン `runtime-floor` が直す**（pre_tool_call）。
ここは、それを通らない CLI（`--max-runtime`）で作られたカードの受け皿である。

**上限なし（NULL）ではなく 30分を入れる。** 上限が無いと、暴走したカードが
いつまでも走り続け、作業部屋を掴んだままになる。**止まる線があるほうが安全である。**

cron の --no-agent で走るので、標準出力がそのまま通知になる。
**直したときだけ喋る。**
"""

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kit_common import board  # noqa: E402

# 終わったカードは直しても意味がない
LIVE = ("triage", "todo", "ready", "running", "blocked", "review", "scheduled")
# 既定の上限。今日の実測では調査が3分、実装が6分だったので、30分あれば足りる。
DEFAULT_SECONDS = int(os.environ.get("KANBAN_DEFAULT_MAX_RUNTIME", "1800"))


def main() -> int:
    # プロファイル配下から起動されるので、ボードは共有の HOME にある（kit_common）
    db = board()
    if db is None:
        return 0

    marks = ",".join("?" * len(LIVE))
    try:
        with sqlite3.connect(db, timeout=5) as conn:
            rows = conn.execute(
                f"SELECT id, COALESCE(assignee,'-'), substr(title,1,50), "
                f"       max_runtime_seconds FROM tasks "
                f"WHERE max_runtime_seconds IS NOT NULL "
                f"  AND max_runtime_seconds < ? AND status IN ({marks})",
                (DEFAULT_SECONDS, *LIVE),
            ).fetchall()
            if not rows:
                return 0
            conn.execute(
                f"UPDATE tasks SET max_runtime_seconds = ? "
                f"WHERE max_runtime_seconds IS NOT NULL "
                f"  AND max_runtime_seconds < ? AND status IN ({marks})",
                (DEFAULT_SECONDS, DEFAULT_SECONDS, *LIVE),
            )
    except sqlite3.Error as e:
        print(f"実行時間の上限を直せなかった: {e}")
        return 0

    print(f"実行時間の上限が短すぎるカードを {DEFAULT_SECONDS}秒 に引き上げた"
          "（短いままでは実行中に強制終了され、2回で二度と動かなくなる）:")
    for tid, who, title, was in rows:
        print(f"  {tid} ({who}) {title} — {was}秒 → {DEFAULT_SECONDS}秒")
    print(f"作った役へ: max_runtime_seconds は {DEFAULT_SECONDS}（30分）を渡す。0 は 0秒である。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
