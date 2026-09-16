#!/usr/bin/env python3
"""この PC に足りない道具があれば、provisioner へのカードを立てる。

**人が意識しなくても道具が揃う**ための入口。足りないまま放っておくと、その道具を
使う最初のカードで初めて落ちる（Docker が無ければ実装の依頼が、Node.js が無ければ
Notion を読む依頼が）。落ちてから人が原因を探すより、先に揃えておく。

- 同じ道具のカードが**まだ開いていれば立てない**（人の承認待ちで止まっているものも含む）
- 閉じたあとも足りなければ、**週が変わってから**立て直す。毎時立てると、
  人が「今は入れない」と決めたものまで毎時騒ぐ
- provisioner を無効にしていれば何もしない（設定画面の「この PC」に出るだけ）

cron の --no-agent で走るので、標準出力がそのまま通知になる。**立てたときだけ喋る。**
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kit_common import HERMES, hermes_home, kit, out  # noqa: E402

ROLE = "provisioner"


def provisioner_available(home: Path) -> bool:
    if not (home / "profiles" / ROLE).is_dir():
        return False
    try:
        data = json.loads((home / "seaos-kit" / "roles.json").read_text(encoding="utf-8"))
        return ROLE not in (data.get("disabled") or [])
    except (OSError, ValueError, AttributeError):
        return True


def open_card(db: Path, tool: str) -> bool:
    if not db.exists():
        return False
    with sqlite3.connect(db, timeout=5) as conn:
        row = conn.execute(
            "SELECT 1 FROM tasks WHERE idempotency_key LIKE ? "
            "AND status NOT IN ('done', 'archived') LIMIT 1",
            (f"machine:{tool}:%",),
        ).fetchone()
    return row is not None


def main() -> int:
    home = hermes_home()
    if not provisioner_available(home):
        return 0
    proc = kit("machine", "check", "--json")
    try:
        rows = json.loads(proc.stdout or "[]")
    except ValueError:
        print("道具の状態を読めなかった:")
        print("\n".join(out(proc).splitlines()[-10:]))
        return 0

    week = time.strftime("%G-W%V")
    created = []
    for r in rows:
        if not r.get("missing"):
            continue
        tool = r["name"]
        try:
            if open_card(home / "kanban.db", tool):
                continue
        except sqlite3.Error as e:
            print(f"板を読めなかった: {e}")
            return 0
        state = "止まっている" if r.get("installed") else "入っていない"
        body = (
            f"{r['label']} が{state}。{r['why']}。\n"
            f"使う役: {', '.join(r.get('neededBy') or [])}\n\n"
            "完了条件: `seaos-kit machine check` で足りないものとして出なくなっていること。"
        )
        c = subprocess.run(
            [HERMES, "kanban", "create", f"{r['label']} を使える状態にする",
             "--assignee", ROLE, "--body", body, "--max-runtime", "1800",
             "--idempotency-key", f"machine:{tool}:{week}", "--created-by", "machine-guard"],
            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
        )
        if c.returncode == 0:
            created.append(r["label"])
        else:
            print(f"{r['label']} のカードを立てられなかった: {c.stderr.strip()[:200]}")

    if created:
        print(f"この PC に足りない道具を provisioner に揃えさせる: {', '.join(created)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
