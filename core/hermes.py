"""`hermes` CLI を呼ぶ薄いラッパ。

**配るのも入れるのも更新するのも Hermes の公式機能**（`profile install` /
`profile update` / `profile describe`）。キットはその呼び出しを組み立てるだけで、
本体には手を入れない。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from paths import hermes_bin, hermes_home, profiles_dir


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
    # **HERMES_HOME を明示する。** Hermes は cwd からも HOME を推測し、
    # `profiles/<役>/` の下から呼ぶとその役自身を HOME だと解釈する
    # （hermes_constants.py の named_profile_home）。定期実行のスクリプトは
    # まさにその位置（プロファイル配下の scripts/）で走るので、放っておくと
    # 「説明文を設定できず」が全役ぶん出る（実際に出た）。
    proc = subprocess.run(
        [_bin(), *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL if stdin_empty else None,
        cwd=str(Path.home()),
        env={**os.environ, "HERMES_HOME": str(hermes_home())},
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def profile_exists(name: str) -> bool:
    from paths import profile_dir
    return profile_dir(name).is_dir()


def clear_tombstone(name: str) -> bool:
    """その役の「削除済み」の印を外す。

    `hermes profile delete` は `profiles/.deleted/<役>` に印を置き、**以後その名前は
    フォルダが実在しても「存在しない」と扱われる**（hermes_constants の
    `named_profile_is_deleted`）。印は入れ直しても消えないので、同じ名前で作り直すと
    `hermes -p <役>` も `profile list` も見つけられない。

    **実際に8役ぶん踏んだ。** ディレクトリは正しくあるのに全滅し、原因に辿り着くまで
    長くかかった。入れる前に外す。
    """
    marker = profiles_dir() / ".deleted" / name
    if not marker.exists():
        return False
    marker.unlink()
    return True


def install(dist: Path, *, force: bool = False) -> Tuple[int, str]:
    # **入れる前に「削除済み」の印を外す。** 残っていると、入れても Hermes からは
    # 存在しないものとして扱われる（同名で作り直したときに必ず踏む）。
    clear_tombstone(dist.name)
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
