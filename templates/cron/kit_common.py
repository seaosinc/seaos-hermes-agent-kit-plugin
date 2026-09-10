"""定期実行のスクリプトが共通で使うもの。

**cron はプロファイル配下の `scripts/` しか実行しない**（cron/scheduler.py:3966）ので、
ここも一緒に配られる。core/ は import できない位置にあるため、コマンド経由で叩く。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PLUGIN_ID = "seaos-hermes-agent-kit"


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def kit_root() -> Path | None:
    """キットの本体。**プラグインとして入るので置き場は決まっている。**

    `HERMES_HOME` はゲートウェイではプロファイル配下を指すことがあるので、
    そこと既定の `~/.hermes` の両方を見る。
    """
    for base in (hermes_home(), Path.home() / ".hermes"):
        root = base / "plugins" / PLUGIN_ID
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
