"""定期保守——**板の物理削除と、日次でまとめて回す一式。**

zsh 版から移し忘れていた2つ（`purge` / `maintain`）がここに入る。cron が
`kit_maintain.sh` から毎日叩くので、無いと日次の掃除と検証が丸ごと止まる。

**sqlite3 コマンドには頼らない。** Windows に無く、Python の標準ライブラリで
足りる（zsh 版はヒアドキュメントで外部コマンドへ流していた）。
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from paths import hermes_home

Log = Callable[[str], None]

# 板は外部キーの CASCADE を張っていないので、消すテーブルを明示する。
# **ここに書き漏らすと孤児行が残る。**
_CHILD_TABLES = (
    ("task_comments", "task_id"),
    ("task_events", "task_id"),
    ("task_runs", "task_id"),
    ("task_attachments", "task_id"),
    ("kanban_notify_subs", "task_id"),
)


@dataclass
class Result:
    lines: List[str] = field(default_factory=list)
    failures: int = 0

    def ok(self) -> bool:
        return self.failures == 0


def db_path() -> Path:
    return hermes_home() / "kanban.db"


def purge(*, confirm: bool = False, older_than: int = 0, log: Optional[Log] = None) -> Result:
    """archived のカードを物理削除する。

    `archive` は論理削除で、カードもコメントも DB に残る。**溜まると板の DB が
    重くなる**ので、古いものだけを本当に消す。

    **既定では数えるだけ。** 消すには confirm を明示する（戻せないため）。
    """
    res = Result()
    say: Log = log or (lambda _l: None)
    db = db_path()
    if not db.is_file():
        res.failures += 1
        res.lines.append(f"板の DB が無い: {db}")
        say(res.lines[-1])
        return res

    where = "status = 'archived'"
    if older_than > 0:
        cutoff = int(time.time()) - older_than * 86400
        where += f" AND COALESCE(completed_at, created_at) < {cutoff}"
        res.lines.append(f"対象: archived かつ {older_than} 日より古いもの")
    else:
        res.lines.append("対象: archived すべて")

    conn = sqlite3.connect(db)
    try:
        total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        n = conn.execute(f"SELECT COUNT(*) FROM tasks WHERE {where}").fetchone()[0]
        res.lines.append(f"削除対象 {n} 件 / 全 {total} 件")
        if n == 0:
            res.lines.append("対象なし")
            for line in res.lines:
                say(line)
            return res
        if not confirm:
            res.lines.append("数えただけ。消すには確認を明示すること。")
            for line in res.lines:
                say(line)
            return res

        backup = db.with_name(f"{db.name}.bak.purge.{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(db, backup)
        res.lines.append(f"バックアップ: {backup}")
        before = db.stat().st_size

        conn.execute("BEGIN")
        conn.execute(f"CREATE TEMP TABLE _p AS SELECT id FROM tasks WHERE {where}")
        for table, column in _CHILD_TABLES:
            conn.execute(f"DELETE FROM {table} WHERE {column} IN (SELECT id FROM _p)")
        conn.execute(
            "DELETE FROM task_links WHERE parent_id IN (SELECT id FROM _p) "
            "OR child_id IN (SELECT id FROM _p)"
        )
        conn.execute("DELETE FROM tasks WHERE id IN (SELECT id FROM _p)")
        conn.commit()
        conn.execute("VACUUM")
    except sqlite3.Error as exc:
        conn.rollback()
        res.failures += 1
        res.lines.append(f"物理削除に失敗: {exc}")
        for line in res.lines:
            say(line)
        return res
    finally:
        conn.close()

    after = db.stat().st_size
    res.lines.append(f"{n} 件を物理削除")
    res.lines.append(f"DB: {before} → {after} bytes（{(before - after) * 100.0 / before:.1f}% 減）")
    for line in res.lines:
        say(line)
    return res


def maintain(*, log: Optional[Log] = None) -> Result:
    """日次の保守一式。**問題が無ければ静かに終わる**（cron が喋るのは出力があるときだけ）。

    反映 → 作業部屋のキャッシュを温める → 古いカードを物理削除 → Docker の掃除
    → 期限切れのアクセス許可を畳む → 検証。
    """
    import booking
    import doctor as doctor_mod
    import kit
    import workspace as ws

    res = Result()
    say: Log = log or (lambda _l: None)

    # 1. 規約が編集されていれば反映する（静かに。失敗しても後段は回す）
    updated = kit.update()
    res.failures += updated.failures

    # 2. 作業部屋のキャッシュ。**冷えていると最初のカードが 34 秒背負う。**
    #    温まっていれば数百 ms で終わるので、毎日回して害は無い。
    try:
        ws.warm_cache()
    except OSError:
        pass

    # 3. 古いカードを本当に消す
    days = int(os.environ.get("PURGE_DAYS") or 90)
    purged = purge(confirm=True, older_than=days)
    res.lines.extend(purged.lines)
    res.failures += purged.failures

    # 受け取ったファイルも同じ日数で畳む。カードが消えたあとは誰も読まない
    import files as files_mod

    files_mod.prune(days, log=res.lines.append)

    # 4. 箱を捨ててもボリュームとイメージ層は残る
    try:
        ws.gc()
    except OSError:
        pass

    # 5. 終わったアクセス許可を畳む。残っていても効かないが、一覧が読めなくなる
    try:
        booking.guest(["prune"])
    except OSError:
        pass

    # 6. 検証
    checked = doctor_mod.run()
    res.lines.extend(checked.lines)
    res.failures += checked.failures
    return res
