#!/usr/bin/env python3
"""**動けない担当**に振られたカードを、止めて人に見せる。

Hermes は担当の実在を確かめない。存在しない役に振られたカードは、ディスパッチャが
黙って飛ばし、**`ready` のまま永久に残る**。親カードは子の完了を待ち続けるので、
依頼ごと止まる——それでいて板の見た目は「順番待ち」と区別がつかない。

起きる経路は2つある:

  存在しない   役を外してプロファイルも消した、名前を綴り間違えた
  無効にした   役を外したがプロファイルは残した。**起動はできてしまい**、
               更新の止まった古い規約と鍵のまま動く

規約からは外した役の名前を落としてある（build_distributions の if-role）。
**それでも書かれた名前は残りうる**——外す前に作られたカード、人の手での振り直し。
ここはその取りこぼしを拾う網である。

`ready` のものだけを見る（Hermes が `block` できるのは ready と running だけ）。
`todo` のものは親が終わって ready になった時点で拾う。

cron の --no-agent で走るので、標準出力がそのまま通知になる。**止めたときだけ喋る。**
"""

import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kit_common import HERMES, hermes_home  # noqa: E402


def disabled(home: Path) -> set:
    """設定画面で外した役（core/selection.py と同じ記録を読む）。"""
    try:
        data = json.loads((home / "seaos-kit" / "roles.json").read_text(encoding="utf-8"))
        return {str(n) for n in data.get("disabled") or []}
    except (OSError, ValueError, AttributeError):
        return set()


def why_not(home: Path, who: str, off: set) -> str:
    """動けない理由。動けるなら空文字。"""
    if who == "default":
        return ""
    profile = home / "profiles" / who
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", who) or not profile.is_dir() \
            or (home / "profiles" / ".deleted" / who).exists():
        return "存在しない"
    if who in off:
        return "この環境で無効にしてある"
    return ""


def main() -> int:
    home = hermes_home()
    db = home / "kanban.db"
    if not db.exists():
        return 0
    off = disabled(home)
    try:
        with sqlite3.connect(db, timeout=5) as conn:
            rows = conn.execute(
                "SELECT id, assignee, substr(title,1,50) FROM tasks "
                "WHERE status = 'ready' AND assignee IS NOT NULL AND assignee <> ''"
            ).fetchall()
    except sqlite3.Error as e:
        print(f"担当を確かめられなかった: {e}")
        return 0

    stopped = []
    for tid, who, title in rows:
        reason = why_not(home, who, off)
        if not reason:
            continue
        text = (
            f"担当の {who} は{reason}ため、このカードは誰にも起動されない。"
            "`hermes profile list` にある役へ振り直して unblock する。"
            "合う役が無ければ、その旨をユーザーへ上げる。"
        )
        r = subprocess.run(
            [HERMES, "kanban", "block", tid, "--kind", "needs_input", text],
            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
        )
        if r.returncode == 0:
            stopped.append((tid, who, title, reason))
        else:
            print(f"{tid} を止められなかった: {r.stderr.strip()[:200]}")

    if stopped:
        print("動けない担当に振られていたカードを入力待ちへ移した:")
        for tid, who, title, reason in stopped:
            print(f"  {tid} ({who}: {reason}) {title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
