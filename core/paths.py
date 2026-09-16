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
    """Hermes の HOME。既定は ~/.hermes（環境変数で差し替え可）。

    **プロファイルの中を指していたら、2つ上を採る。** 定期実行とゲートウェイは
    `HERMES_HOME=~/.hermes/profiles/<役>` で走る。そのまま使うと、役の選択も
    プロファイルの置き場も見当違いの場所を見て、「記録が無い＝全役有効」
    「どのプロファイルも無い」と判断する。kit-sync が10分ごとに全役の導入を試みて
    失敗し続け、外した役を入れ直していた（実際に踏んだ）。
    """
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    if home.parent.name == "profiles":
        return home.parent.parent
    return home


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
    """秘密の正。**ここ1箇所だけ。** git には入らない。

    **キットの外に置く。** 中（`<キット>/.env`）に置くと
    `hermes plugins install --force` で消える——あれはフォルダごと置き換えるので、
    git に入らないものは引き継がれない。**実際に全部の鍵が飛んだ。**

    キットの中に旧い `.env` が残っていれば、**一度だけ引き取る**。
    移行で鍵が消えないように。
    """
    new_path = hermes_home() / "seaos-kit" / ".env"
    if new_path.is_file():
        return new_path

    legacy = kit_root() / ".env"
    if legacy.is_file():
        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, new_path)
        os.chmod(new_path, 0o600)
        # **旧いほうは消す。** 残すと、どちらが正か分からなくなる
        # （消える側を編集し続ける事故が起きる）。
        legacy.unlink()
    return new_path


def selection_file() -> Path:
    """**どの役を入れるか**の記録。秘密と同じく、キットの外に置く。

    中に置くと `hermes plugins install --force` で消え、外したはずの役が
    次の反映で黙って戻ってくる。
    """
    return hermes_home() / "seaos-kit" / "roles.json"


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
