#!/usr/bin/env python3
"""規約の取り込みと配布だけを回す（軽い）。

`--no-agent` で走るので、**標準出力に出したものがそのまま通知される。**
変化があったときだけ喋る。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kit_common import kit, kit_root, out  # noqa: E402


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)


def main() -> int:
    root = kit_root()
    if root is None:
        print("キットが見つからない（定期実行を止めるか、入れ直すこと）")
        return 0

    # **手元で直す環境と、git で受け取る環境がある。**
    # 手元（開発機）は templates/ を直接編集するので、引くものが無い。
    # 配られた箱は git だけが変更の入口なので、ここで取り込まないと規約が
    # 永遠に古いままになる。**リモートがあって、手元に変更が無いときだけ**引く。
    if (root / ".git").is_dir():
        has_remote = bool(git(root, "remote").stdout.strip())
        is_clean = not git(root, "status", "--porcelain").stdout.strip()
        if has_remote and is_clean:
            before = git(root, "rev-parse", "HEAD").stdout.strip()
            pull = git(root, "pull", "--ff-only")
            if pull.returncode != 0:
                print("git pull が失敗した（手で見ること）:")
                print("\n".join((pull.stdout + pull.stderr).splitlines()[-5:]))
            after = git(root, "rev-parse", "HEAD").stdout.strip()
            if before != after:
                log = git(root, "log", "--oneline", f"{before}..{after}").stdout
                print("キットを更新した: " + " / ".join(log.splitlines()[:5]))

    proc = kit("update")
    if proc.returncode != 0:
        print("反映が失敗した:")
        print("\n".join(out(proc).splitlines()[-20:]))
        return 0

    # 新しく入った・消えた役があれば喋る（更新しただけなら黙る）
    changed = [l.strip() for l in out(proc).splitlines()
               if "新しく導入した" in l or "入れ直した" in l or "外した" in l]
    if changed:
        print("規約を配布した:")
        for line in changed:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
