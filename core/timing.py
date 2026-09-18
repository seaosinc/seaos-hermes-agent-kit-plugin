#!/usr/bin/env python3
"""カード1枚が「どこで待たされたか」を、板の記録から出す。

    seaos-kit timing            直近 10 枚
    seaos-kit timing -n 30      直近 30 枚

**遅さの原因を推測しない。** 「作業開始まで5分かかる」という報告に対して、
分解が遅いのか、巡回を待っていたのか、箱の起動に食われたのかは、外から見ても
区別がつかない。板の task_events には全部の時刻が残っているので、そこから読む。

実際、初回の測定で分かったのは「分解が遅いのではなく、15 秒の巡回を待っていた
だけ」だった（+0s 作成 → +15s 分解・掴む → +16s 起動）。**測る前の見当は外れた。**

出す区間は4つ。どれが大きいかで、直す場所がそのまま決まる。

    待ち   作成 → 掴まれる       巡回の刻み（kanban.dispatch_interval_seconds）
    分解   作成 → 子カードが出る  分解器の1ターン（auxiliary.kanban_decomposer）
    起動   掴まれる → spawn      プロセスと箱の立ち上げ
    作業   spawn → 完了/停止     実際の仕事
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from paths import hermes_home


def db_path() -> Path:
    return hermes_home() / "kanban.db"


@dataclass
class Row:
    id: str
    title: str
    assignee: str
    status: str
    created: int
    wait: int | None        # 作成 → 掴まれる
    decompose: int | None   # 作成 → 最初の子カード
    start: int | None       # 掴まれる → spawn
    work: int | None        # spawn → completed/blocked


def _first(con: sqlite3.Connection, task: str, kinds: tuple[str, ...]) -> int | None:
    marks = ",".join("?" * len(kinds))
    cur = con.execute(
        f"SELECT MIN(created_at) FROM task_events WHERE task_id=? AND kind IN ({marks})",
        (task, *kinds),
    )
    got = cur.fetchone()[0]
    return int(got) if got is not None else None


def recent(limit: int = 10) -> list[Row]:
    db = db_path()
    if not db.is_file():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cards = con.execute(
            "SELECT id, title, assignee, status, created_at FROM tasks "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for cid, title, assignee, status, created in cards:
            claimed = _first(con, cid, ("claimed",))
            spawned = _first(con, cid, ("spawned",))
            done = _first(con, cid, ("completed", "blocked", "failed"))
            kid = con.execute(
                "SELECT MIN(c.created_at) FROM task_links l JOIN tasks c ON c.id=l.child_id "
                "WHERE l.parent_id=?",
                (cid,),
            ).fetchone()[0]
            out.append(Row(
                id=str(cid), title=str(title or ""), assignee=str(assignee or ""),
                status=str(status or ""), created=int(created),
                wait=None if claimed is None else claimed - int(created),
                decompose=None if kid is None else int(kid) - int(created),
                start=None if (claimed is None or spawned is None) else spawned - claimed,
                work=None if (spawned is None or done is None) else done - spawned,
            ))
        return out
    finally:
        con.close()


def _sec(value: int | None) -> str:
    if value is None:
        return "    -"
    if value < 0:  # 親子の張り直しで前後することがある。嘘の数字を出さない
        return "    -"
    return f"{value:5d}"


def report(limit: int = 10, log=print) -> int:
    rows = recent(limit)
    if not rows:
        log(f"板の記録がありません（{db_path()}）")
        return 1
    log("秒。待ち=作成から掴まれるまで 分解=作成から子カードまで 起動=掴んでから実行まで 作業=実行から終了まで")
    log(f"{'いつ':16} {'待ち':>5} {'分解':>5} {'起動':>5} {'作業':>5}  役 / 題名")
    for r in rows:
        when = time.strftime("%m-%d %H:%M:%S", time.localtime(r.created))
        log(f"{when:16} {_sec(r.wait)} {_sec(r.decompose)} {_sec(r.start)} {_sec(r.work)}"
            f"  {r.assignee or '-'} / {r.title[:40]}")

    waits = [r.wait for r in rows if r.wait is not None and r.wait >= 0]
    starts = [r.start for r in rows if r.start is not None and r.start >= 0]
    if waits:
        log("")
        log(f"掴まれるまでの待ち: 中央 {sorted(waits)[len(waits) // 2]} 秒 / 最大 {max(waits)} 秒"
            "（巡回の刻みで決まる。kanban.dispatch_interval_seconds）")
    if starts:
        log(f"掴んでから走り出すまで: 中央 {sorted(starts)[len(starts) // 2]} 秒 / 最大 {max(starts)} 秒"
            "（大きいなら、プロセスか作業部屋の立ち上げ）")
    return 0
