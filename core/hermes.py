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


def forbidden() -> bool:
    """**テスト中は、この PC の Hermes を起動しない。** 起動するなら理由を返す口で断る。

    テストは一時ディレクトリを HERMES_HOME にして走る。その HOME で本物の Hermes を起動すると、
    Hermes は道具の置き場を一時 HOME に移し、共有の起動スクリプトをその Python で書き直す。
    一時 HOME が消えると Hermes Desktop が「未インストール」になる（2026-09-30 に2度起きた）。
    テストの仕組み（tests/_harness.py）が SEAOS_KIT_TESTING を立てる。GitHub Actions は捨てられる
    環境なので、そこでは起動してよい。
    """
    return bool(os.environ.get("SEAOS_KIT_TESTING")) and os.environ.get("GITHUB_ACTIONS") != "true"


def _bin() -> str:
    exe = hermes_bin()
    if not exe:
        raise HermesMissing("hermes が PATH に無い（Hermes を先に入れること）")
    return exe


def run(args: List[str], *, stdin_empty: bool = True,
        timeout: Optional[float] = None) -> Tuple[int, str]:
    """`hermes <args>` を実行し (終了コード, 出力) を返す。

    **stdin は既定で閉じる。** 対話プロンプトが出る操作を無人で回すと、
    応答待ちのまま固まる（zsh 版が `</dev/null` を付けていたのと同じ理由）。

    ``timeout`` を渡すと、それを過ぎたら打ち切って (124, 理由) を返す。
    **前面で走り続けうる操作には必ず付ける**（ゲートウェイの操作は、条件次第で
    `gateway run` を前面で始めて戻らない）。
    """
    # **HERMES_HOME を明示する。** Hermes は cwd からも HOME を推測し、
    # `profiles/<役>/` の下から呼ぶとその役自身を HOME だと解釈する
    # （hermes_constants.py の named_profile_home）。定期実行のスクリプトは
    # まさにその位置（プロファイル配下の scripts/）で走るので、放っておくと
    # 「説明文を設定できず」が全役ぶん出る（実際に出た）。
    if forbidden():
        return 126, "テスト中は、この PC の Hermes を起動しない（hermes.forbidden）"
    try:
        proc = subprocess.run(
            [_bin(), *args],
            capture_output=True,
            text=True,
            # **UTF-8 で読む。** 日本語版 Windows の既定（cp932）で読むと、Hermes の出力の
            # 日本語や記号で落ちる。読めない文字は置き換えて、判定だけは続ける。
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL if stdin_empty else None,
            cwd=str(Path.home()),
            env={**os.environ, "HERMES_HOME": str(hermes_home())},
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, f"hermes {' '.join(args)} が {timeout:.0f}秒 で終わらなかった"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def profile_exists(name: str) -> bool:
    """本体から見て、その役が「ある」か。

    **フォルダの有無だけでは足りない。** `hermes profile delete` が置く
    `profiles/.deleted/<役>` の印が残っていると、フォルダが実在しても本体は
    存在しないものとして扱う（`clear_tombstone` の説明を見よ）。印を見ずに
    説明文を書きにいって、「プロファイルがありません」で失敗した。
    """
    from paths import profile_dir
    if (profiles_dir() / ".deleted" / name).exists():
        return False
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
