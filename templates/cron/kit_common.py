"""定期実行のスクリプトが共通で使うもの。

**cron はプロファイル配下の `scripts/` しか実行しない**（cron/scheduler.py:3966）ので、
ここも一緒に配られる。core/ は import できない位置にあるため、コマンド経由で叩く。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ID = "seaos-hermes-agent-kit-plugin"
# 名前をリポジトリ名に揃える前に入れた環境は、フォルダがこの名前のまま残っている
LEGACY_PLUGIN_IDS = ("seaos-hermes-agent-kit",)

# `hermes` の実体。cron の PATH は痩せているので、見つからなければ定番の置き場。
HERMES = os.environ.get("HERMES_BIN") or shutil.which("hermes") \
    or str(Path.home() / ".local/bin/hermes")


def hermes_home() -> Path:
    """共有の HOME。**cron はプロファイルの中（`profiles/<役>`）で走る**ので、そのときは2つ上。"""
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    return home.parent.parent if home.parent.name == "profiles" else home


def board() -> Path | None:
    """共有の板（kanban.db）。無ければ None（まだ一度も使っていない環境）。"""
    db = hermes_home() / "kanban.db"
    return db if db.exists() else None


def kit_root() -> Path | None:
    """キットの本体。**プラグインとして入るので置き場は決まっている。**

    `HERMES_HOME` はゲートウェイではプロファイル配下を指すことがあるので、
    そこと既定の `~/.hermes` の両方を見る。
    """
    for base in (hermes_home(), Path.home() / ".hermes"):
        for name in (PLUGIN_ID, *LEGACY_PLUGIN_IDS):
            root = base / "plugins" / name
            if (root / "core" / "cli.py").is_file():
                return root
    return None


def kit(*args: str) -> subprocess.CompletedProcess:
    """`seaos-kit` を叩く。

    **PATH のコマンドではなく本体を直に呼ぶ。** cron の環境は PATH が痩せていて、
    ラッパが見つからないことがある。解釈系はいま自分を走らせているものを使う
    （Hermes の venv なので依存が揃っている）。
    """
    root = kit_root()
    if root is None:
        raise FileNotFoundError(f"キットが見つからない（{PLUGIN_ID}）")
    return subprocess.run(
        [sys.executable, str(root / "core" / "cli.py"), *args],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def out(proc: subprocess.CompletedProcess) -> str:
    return (proc.stdout or "") + (proc.stderr or "")
