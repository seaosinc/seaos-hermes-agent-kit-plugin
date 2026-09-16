#!/usr/bin/env python3
"""ready のまま再spawnを見送られ続けているカードを、止めて人に見せる。

**ディスパッチャは「今回は起こさない」と決めたことを、カードの状態に書かない。**
`respawn_guarded` というイベントを1行足して `ready` のまま置く。ボードの見た目は
「順番待ち」と区別がつかず、`stats` も `list` も健康に見える。実際に、PR を指す
URL がコメントに入っていた2枚が **15秒おきに4時間、誰にも気づかれずに空転した。**

ガードの理由（`kanban_db.check_respawn_guard`）は4種類ある:

  rate_limit_cooldown  プロバイダの上限に当たった。時間が経てば解ける
  blocker_auth         直前の失敗が認証・課金。人が動かないと解けない
  recent_success       直近に成功した実行がある。再実行の指示を待つ
  active_pr            **直近24時間のコメントに PR の URL がある。**
                       「worker が PR を立てた直後」とみなして再spawnしない

**このうち解ける保証があるのは最初の1つだけ**である。残り3つは、待っても
状況は変わらない。とくに `active_pr` は、**レビュー対象として PR を指した**
だけのカードにも当たり、review レーン以外に解除経路が無い（URL が24時間
古くなるまで解けない）。

**待っても解けないものを待たせない。** 一定時間ほどけない空転は、ボードの
言葉で言えば「人の入力待ち」である。`block --kind needs_input` へ移して、
理由と解き方をカードに書く。operator がそれをユーザーに出せる。

止めるまでの猶予は長めに取る。`rate_limit_cooldown` は実際に時間で解けるので、
**解ける可能性が尽きたと言い切れる線**まで待つ。

cron の --no-agent で走るので、標準出力がそのまま通知になる。**止めたときだけ喋る。**
"""

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

# 空転が続いたら止める線。ディスパッチャは15秒ごとに回るので、これは
# 120回ぶん見送られたということ。rate_limit の窓はこれより短い。
SPIN_LIMIT_SECONDS = int(os.environ.get("KANBAN_SPIN_LIMIT", "1800"))

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kit_common import HERMES, board  # noqa: E402

# 理由ごとの、カードに書く解き方。**綴りは事実なので書く。**
HOWTO = {
    "active_pr": (
        "このカードのコメントに PR の URL があるため、ディスパッチャが "
        "「worker が PR を立てた直後」とみなして再spawnを見送り続けている。"
        "レビュー対象として PR を指しているだけなら、URL ではなく "
        "owner/repo#番号 の形で書き直す。"
    ),
    "blocker_auth": (
        "直前の失敗が認証・課金の壁だった。鍵か枠を人が直すまで、"
        "何度起こしても同じところで止まる。"
    ),
    "recent_success": (
        "直近に成功した実行がある。もう一度走らせたいなら、"
        "hermes kanban unblock で明示的に指示する。"
    ),
    "rate_limit_cooldown": (
        "プロバイダの利用上限に当たったまま、待ち時間が明けても解けていない。"
        "枠か、使うモデルを見直す。"
    ),
}


def spinning(conn: sqlite3.Connection, now: int) -> list[tuple[str, str, str, str, int]]:
    """途切れずに空転しているカードを返す。

    **数えるのは「連続」である。** 一度でも spawn / status / unblock などの
    別のイベントが挟まれば、そこで数え直す——直前まで空転していても、
    人が触ったカードはもう空転ではない。
    """
    out = []
    rows = conn.execute(
        "SELECT id, COALESCE(assignee,'-') AS who, substr(title,1,50) AS title "
        "FROM tasks WHERE status = 'ready'"
    ).fetchall()
    for tid, who, title in rows:
        # 直近の「空転ではない」イベント。これより新しい respawn_guarded が、
        # 今つながっている連続ぶんである。
        last_other = conn.execute(
            "SELECT COALESCE(MAX(created_at), 0) FROM task_events "
            "WHERE task_id = ? AND kind <> 'respawn_guarded'",
            (tid,),
        ).fetchone()[0]
        streak = conn.execute(
            "SELECT MIN(created_at), COUNT(*) FROM task_events "
            "WHERE task_id = ? AND kind = 'respawn_guarded' AND created_at > ?",
            (tid, last_other),
        ).fetchone()
        started = streak[0]
        if not started or now - started < SPIN_LIMIT_SECONDS:
            continue
        payload = conn.execute(
            "SELECT payload FROM task_events "
            "WHERE task_id = ? AND kind = 'respawn_guarded' "
            "ORDER BY created_at DESC LIMIT 1",
            (tid,),
        ).fetchone()[0] or ""
        reason = "unknown"
        for key in HOWTO:
            if key in payload:
                reason = key
                break
        out.append((tid, who, title, reason, now - started))
    return out


def main() -> int:
    db = board()
    if db is None:
        return 0
    now = int(time.time())
    try:
        with sqlite3.connect(db, timeout=5) as conn:
            found = spinning(conn, now)
    except sqlite3.Error as e:
        print(f"空転を数えられなかった: {e}")
        return 0
    if not found:
        return 0

    stopped = []
    for tid, who, title, reason, age in found:
        text = (
            f"再spawnが {age // 60} 分にわたって見送られ続けている"
            f"（ガードの理由: {reason}）。ready のままでは誰にも見えないので、"
            f"入力待ちとして止めた。{HOWTO.get(reason, '理由を kanban show の Events で確認する。')}"
        )
        r = subprocess.run(
            [HERMES, "kanban", "block", tid, "--kind", "needs_input", text],
            capture_output=True, text=True, timeout=60,
            stdin=subprocess.DEVNULL,
        )
        if r.returncode == 0:
            stopped.append((tid, who, title, reason, age))
        else:
            print(f"空転している {tid} を止められなかった: {r.stderr.strip()[:200]}")

    if not stopped:
        return 0
    print("空転していたカードを入力待ちへ移した（ready のままでは気づけないため）:")
    for tid, who, title, reason, age in stopped:
        print(f"  {tid} ({who}) {title} — {reason} / {age // 60}分")
    return 0


if __name__ == "__main__":
    sys.exit(main())
