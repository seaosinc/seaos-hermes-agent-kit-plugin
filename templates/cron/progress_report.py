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
  ・終わったカードの話はしない（完了は担当が自分で報告する）。done でも archived でも、
    板から動いた時点で実況は止まる
  ・同じカードを `MAX_TIMES` 回より多く実況しない。**それ以上は進捗ではなく詰まり**で、
    延々と「まだ動いています」と言い続けるのは黙っているより悪い（spin-guard の担当）

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
# 同じカードについて実況する回数の上限。**繰り返すほど価値が下がる。**
MAX_TIMES = int(os.environ.get("PROGRESS_MAX_TIMES", "3"))

# 状態ごとの、人に伝わる言い方。**板の用語も役の名前も出さない。**
# ユーザーから見ると相手は一人なので、「誰が担当か」は存在しない情報である
# （役名を出すと、仕事を他人に渡したように聞こえる）。
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
    # {カード id: [最後に言った時刻, 言った回数]}
    said = {k: (v if isinstance(v, list) else [v, 1]) for k, v in load().items()}

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
    for cid, title, _assignee, status, created, started in rows:
        cid = str(cid)
        live.add(cid)
        elapsed = now - int(started or created or now)
        if elapsed < QUIET_SECONDS:
            continue
        last, times = said.get(cid) or [0, 0]
        if now - int(last) < REPEAT_SECONDS:
            continue
        if int(times) >= MAX_TIMES:
            continue
        lines.append(f"・{str(title or cid)[:60]}（{SAYING.get(str(status), status)}・{minutes(elapsed)}経過）")
        said[cid] = [now, int(times) + 1]
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
