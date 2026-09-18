#!/usr/bin/env python3
"""時間のかかっているカードを、人へ実況する。

**黙って待たされるのがいちばん悪い。** 依頼してから作業が始まるまでに分解と起動が
挟まり、実作業が数分かかることもある。その間カードの中では進んでいても、頼んだ人の
画面には何も出ない——「固まったのか、動いているのか」が分からない状態が続く。

cron の `--no-agent` で走るので、**標準出力がそのまま通知になる。**
だから「言うことがあるときだけ印字する」ことが、そのまま「用があるときだけ喋る」になる。

うるさくしないための線引き:

  ・始まってから `QUIET_SECONDS` 以内は黙る。ふつうに終わる仕事まで実況しない
  ・一度喋ったら `REPEAT_SECONDS` は同じカードの話をしない
  ・終わったカードの話はしない（完了は担当が自分で報告する）

言ったことは `<HERMES_HOME>/kanban/.progress-report.json` に置く。消えても、
次の周期でまた喋るだけで壊れない。
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kit_common import board, hermes_home  # noqa: E402

# これより短く終わる仕事は実況しない。**待たされたと感じ始める線**に置く。
QUIET_SECONDS = int(os.environ.get("PROGRESS_QUIET_SECONDS", "120"))
# 同じカードについて、次に喋るまでの間隔。
REPEAT_SECONDS = int(os.environ.get("PROGRESS_REPEAT_SECONDS", "180"))
# 一度に出す件数の上限。板が詰まったときに長文を投げない。
MAX_LINES = 5

# 状態ごとの、人に伝わる言い方。**板の用語をそのまま出さない。**
SAYING = {
    "running": "作業中",
    "ready": "順番待ち",
    "triage": "内容を仕分け中",
    "review": "確認中",
}


def state_file() -> Path:
    return hermes_home() / "kanban" / ".progress-report.json"


def load() -> dict:
    try:
        return json.loads(state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    path = state_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass  # 覚えられなくても、次の周期でまた喋るだけ


def minutes(seconds: int) -> str:
    return f"{seconds // 60}分" if seconds >= 60 else f"{seconds}秒"


def main() -> int:
    db = board()
    if db is None:
        return 0
    now = int(time.time())
    said = load()

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT id, title, assignee, status, created_at, started_at FROM tasks "
            "WHERE status IN ('running','ready','triage','review') ORDER BY created_at",
        ).fetchall()
    except sqlite3.Error:
        return 0
    finally:
        con.close()

    lines = []
    live = set()
    for cid, title, assignee, status, created, started in rows:
        cid = str(cid)
        live.add(cid)
        elapsed = now - int(started or created or now)
        if elapsed < QUIET_SECONDS:
            continue
        if now - int(said.get(cid) or 0) < REPEAT_SECONDS:
            continue
        who = f"{assignee} が" if assignee else ""
        lines.append(f"・{str(title or cid)[:60]}（{who}{SAYING.get(str(status), status)}・{minutes(elapsed)}経過）")
        said[cid] = now
        if len(lines) >= MAX_LINES:
            break

    # 板から消えたカードの記録は落とす（際限なく太らせない）
    save({k: v for k, v in said.items() if k in live})

    if lines:
        print("まだ動いています。終わったら報告します。")
        for line in lines:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
