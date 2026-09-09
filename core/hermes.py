"""`hermes` CLI を呼ぶ薄いラッパ。

**配るのも入れるのも更新するのも Hermes の公式機能**（`profile install` /
`profile update` / `profile describe`）。キットはその呼び出しを組み立てるだけで、
本体には手を入れない。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from paths import hermes_bin


class HermesMissing(RuntimeError):
    """`hermes` が PATH に無い。"""


def _bin() -> str:
    exe = hermes_bin()
    if not exe:
        raise HermesMissing("hermes が PATH に無い（Hermes を先に入れること）")
    return exe


def run(args: List[str], *, stdin_empty: bool = True) -> Tuple[int, str]:
    """`hermes <args>` を実行し (終了コード, 出力) を返す。

    **stdin は既定で閉じる。** 対話プロンプトが出る操作を無人で回すと、
    応答待ちのまま固まる（zsh 版が `</dev/null` を付けていたのと同じ理由）。
    """
    proc = subprocess.run(
        [_bin(), *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL if stdin_empty else None,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def profile_exists(name: str) -> bool:
    from paths import profile_dir
    return profile_dir(name).is_dir()


def install(dist: Path, *, force: bool = False) -> Tuple[int, str]:
    args = ["profile", "install", str(dist), "-y"]
    if force:
        args.append("--force")
    return run(args)


def update(name: str, *, force_config: bool = False) -> Tuple[int, str]:
    args = ["profile", "update", name, "-y"]
    if force_config:
        args.append("--force-config")
    return run(args)


def set_description(name: str, text: str) -> Tuple[int, str]:
    """decomposer が読む説明文を、生成器の文面に合わせる。

    **init だけでなく update でも毎回合わせる。** ここが古いと、能力を変えても
    振り分けの判断は古い文面のまま動く（新しく足した役が「存在しないのと同じ」になる）。
    """
    return run(["profile", "describe", name, "--text", text, "--overwrite"])


def is_distribution(name: str) -> bool:
    from paths import profile_dir
    return (profile_dir(name) / "distribution.yaml").is_file()
