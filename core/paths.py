"""キットとプロファイルの置き場を解決する。

**OS 依存をここに閉じる。** 常駐の作法とコマンドの置き場だけが OS で違い、
役の定義・生成・配布は共通である。ここ以外に platform 分岐を書かないこと。
"""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path


def kit_root() -> Path:
    """このリポジトリのルート（templates/ がある場所）。"""
    return Path(__file__).resolve().parent.parent


def hermes_home() -> Path:
    """Hermes の HOME。既定は ~/.hermes（環境変数で差し替え可）。"""
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def local_workers_dir() -> Path:
    """**この環境で作った役の置き場。** キットの外に出してある。

    recruiter が作る役をキットの中（`templates/workers/`）に置くと、配布の
    たびに危うい。`hermes plugins update` は untracked も stash して戻すので
    （`stash push --include-untracked`）、同じパスに配布物が来れば衝突して
    stash に取り残される。`hermes plugins install --force` ならフォルダごと
    置き換わって消える。

    **配られてくる役と、ここで作った役を、物理的に分ける。**
    """
    return hermes_home() / "seaos-kit" / "workers"


def profiles_dir() -> Path:
    return hermes_home() / "profiles"


def profile_dir(name: str) -> Path:
    return profiles_dir() / name


def env_file() -> Path:
    """秘密の正。**ここ1箇所だけ。** git には入らない。"""
    return kit_root() / ".env"


def hermes_bin() -> str | None:
    """`hermes` 実行ファイル。見つからなければ None。"""
    return shutil.which("hermes")


def os_kind() -> str:
    """'darwin' / 'linux' / 'win32'。常駐と配置の分岐にだけ使う。"""
    system = platform.system().lower()
    if system == "darwin":
        return "darwin"
    if system == "windows":
        return "win32"
    return "linux"
