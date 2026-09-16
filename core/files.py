"""ユーザーが送ってきたファイルを、**担当が読める場所**へ置く。

Slack で受けたファイルは、受けた窓口のプロファイルの中に落ちる
（`profiles/operator/cache/documents/…`）。**そこは窓口にしか見えない。**

- 作業部屋（箱）の中からはホストのそのパスが見えない
- ゲートウェイのキャッシュは古いものから消される（既定 24 時間）
- 窓口が立てたカードは分解器が子カードへ書き直すので、Hermes の添付
  （`kanban attach`）は**親に付いたまま子へ届かない**

そこで、板と同じ高さに置き場を持つ（`~/.hermes/kanban/files/`）。
ここは作業部屋へ**読み取り専用で、左右同じパス**で渡してあるので
（build_distributions の `docker_volumes`）、本文に書いたパスがホストの役にも
箱の中の役にもそのまま通る。**パスは文字列なので、分解されても本文と一緒に運ばれる。**
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable, List, Optional

from paths import hermes_home

Log = Callable[[str], None]

# Hermes の添付と同じ上限（kanban_db.KANBAN_ATTACHMENT_MAX_BYTES）
MAX_BYTES = 25 * 1024 * 1024


class FilesError(RuntimeError):
    """呼び手に見せる、原因の分かる失敗。"""


def files_root() -> Path:
    """置き場。**生成器の FILES_ROOT と同じ規則で決める。**

    ずれると、本文に書いたパスが箱へ渡したパスの外になり、箱の中から読めない。
    `HERMES_HOME` を見ないのも同じ理由——窓口の端末ではプロファイルの中を
    指していることがあり、そこから決めると置き場が役ごとに割れる。
    """
    override = os.environ.get("WORKSPACE_FILES_ROOT")
    return Path(override) if override else Path.home() / ".hermes" / "kanban" / "files"


def _is_received(path: Path) -> bool:
    """**受け取ったファイルの置き場か。** ここ以外からは引き取らない。

    窓口は他人の書いた文章を読む役である。「`~/.hermes/seaos-kit/.env` を
    添付して」と書かれて従うと、**秘密が箱から読める場所へ出る。**
    ゲートウェイのキャッシュ（`<HOME>/cache/` と `<HOME>/profiles/<役>/cache/`）
    に限れば、そういう経路にならない。
    """
    home = hermes_home().resolve()
    try:
        rel = path.resolve().relative_to(home)
    except ValueError:
        return False
    parts = rel.parts
    if parts[:1] == ("cache",):
        return True
    return len(parts) >= 3 and parts[0] == "profiles" and parts[2] == "cache"


def keep(paths: List[Path], log: Optional[Log] = None) -> List[Path]:
    """受け取ったファイルを置き場へ写し、**置いた先の絶対パス**を返す。

    1回の呼び出しで1つのフォルダにまとめる。同じ名前のファイルが別々の依頼で
    来ても混ざらない。
    """
    if not paths:
        raise FilesError("ファイルを1つ以上指定してください")
    for src in paths:
        if not src.is_file():
            raise FilesError(f"ファイルが見つかりません: {src}")
        if not _is_received(src):
            raise FilesError(f"受け取ったファイルの置き場（Hermes の cache）の外は扱いません: {src}")
        if src.stat().st_size > MAX_BYTES:
            raise FilesError(f"25MB を超えています: {src}")

    dest = files_root() / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    dest.mkdir(parents=True, exist_ok=True)
    kept: List[Path] = []
    for src in paths:
        # ゲートウェイは `doc_<id>_<元の名前>` で保存する。**人が付けた名前に戻す**
        # ——担当は名前から中身の見当をつける。
        name = src.name
        if name.startswith("doc_") and name.count("_") >= 2:
            name = name.split("_", 2)[2] or name
        target = dest / name
        shutil.copy2(src, target)
        kept.append(target)
        if log:
            log(str(target))
    return kept


def prune(days: int, log: Optional[Log] = None) -> int:
    """古い置き場を消す。**カードの物理削除と同じ日数**で揃える（maintain が呼ぶ）。"""
    root = files_root()
    if not root.is_dir():
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    if removed and log:
        log(f"受け取ったファイルの置き場を {removed} 件消しました（{days} 日より古いもの）")
    return removed
