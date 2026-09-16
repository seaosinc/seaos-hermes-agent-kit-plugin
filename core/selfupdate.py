"""キット自身を最新にする。

`git pull` → `update`（配布物を作り直して各役へ反映）→ `doctor` まで通す。

**配布の形が2つある。**
  - プラグインとして入っている（`hermes plugins update` が pull を担う）
  - リポジトリを直接使っている（ここが pull する）
どちらでも「pull したあとエージェント側を追随させる」ところは同じ。
"""

from __future__ import annotations

import subprocess
from typing import Callable, Optional, Tuple

import doctor as doctor_mod
import kit
from paths import kit_root

Log = Callable[[str], None]


def _git(*args: str) -> Tuple[int, str]:
    proc = subprocess.run(
        ["git", "-C", str(kit_root()), *args],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def pull(*, dry_run: bool = False, log: Optional[Log] = None) -> bool:
    say: Log = log or (lambda _l: None)
    if not (kit_root() / ".git").exists():
        say(f"= git リポジトリではないので pull しない: {kit_root()}")
        return True
    if _git("remote", "get-url", "origin")[0] != 0:
        say("= リモートが未設定なので pull しない（git remote add origin <url>）")
        return True

    # **未コミットがあると pull は壊れる。** 先に止めるのが一番安い。
    _code, dirty = _git("status", "--porcelain")
    if dirty.strip():
        say("✗ 作業ツリーに未コミットの変更がある。commit か stash してから実行すること")
        for line in dirty.splitlines()[:5]:
            say(f"    {line}")
        return False

    before = _git("rev-parse", "--short", "HEAD")[1].strip()
    if dry_run:
        _git("fetch", "--quiet")
        code, out = _git("rev-list", "--count", "HEAD..@{u}")
        behind = int(out.strip() or 0) if code == 0 else 0
        say(f"~ {behind} コミット遅れている（pull される）" if behind else "= 最新")
        return True

    code, out = _git("pull", "--ff-only", "--quiet")
    if code != 0:
        say(f"✗ pull に失敗: {out.strip().splitlines()[-1] if out.strip() else ''}")
        return False
    after = _git("rev-parse", "--short", "HEAD")[1].strip()
    say(f"= {after}（変化なし）" if before == after else f"+ {before} → {after}")
    return True


def run(*, dry_run: bool = False, force_config: bool = False, log: Optional[Log] = None) -> bool:
    say: Log = log or (lambda _l: None)

    say("=== 1. キット本体 ===")
    if not pull(dry_run=dry_run, log=say):
        return False
    if dry_run:
        say("=== 2. 反映（--dry-run なので実行しない） ===")
        for line in kit.diff().lines:
            say(line)
        return True

    say("=== 2. 各役へ反映 ===")
    result = kit.update(force_config=force_config)
    for line in result.lines:
        say(line)

    say("=== 3. 検証 ===")
    rep = doctor_mod.run()
    for line in rep.lines:
        say(line)
    return result.ok() and rep.passed()
