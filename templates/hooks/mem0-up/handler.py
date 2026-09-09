"""ゲートウェイの起動時に mem0 のコンテナを立ち上げる。

記憶を使うのはワーカーで、ワーカーはディスパッチャの子プロセス、ディスパッチャは
ゲートウェイに埋め込まれている。**記憶の寿命をゲートウェイに合わせるのが依存と一致する。**
launchd の install 時に1回上げるだけだと、Docker を再起動したあと誰も上げ直さない。

`docker compose up -d` は冪等なので、既に動いていれば何もしない。
**起動をブロックしない**（compose は数十秒かかることがあり、そのぶん Slack への
接続が遅れる）。結果はログに残し、失敗しても gateway は動き続ける。
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
ROOT = HERMES_HOME.parent.parent if HERMES_HOME.parent.name == "profiles" else HERMES_HOME
MEM0_ENV = ROOT / "mem0" / ".env"
LOG_PATH = ROOT / "logs" / "mem0-up.log"
MANIFEST = ROOT / ".hermes-kit-manifest.json"


def _compose_file() -> Path | None:
    """compose.yml はキットのリポジトリ側にある（版管理したいので）。

    場所は hermes-kit update がマニフェストに書いている。
    """
    try:
        kit = json.loads(MANIFEST.read_text(encoding="utf-8")).get("kit_root")
    except Exception:
        return None
    if not kit:
        return None
    path = Path(kit) / "templates" / "mem0" / "compose.yml"
    return path if path.exists() else None


def _log(msg: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().astimezone():%Y-%m-%d %H:%M:%S} {msg}\n")
    except Exception:
        pass


async def _up() -> None:
    compose = _compose_file()
    if compose is None:
        _log("compose.yml が見つからないので何もしない（キットが未導入）")
        return
    if not MEM0_ENV.exists():
        _log(f"{MEM0_ENV} が無いので何もしない（hermes-kit install が作る）")
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "--env-file", str(MEM0_ENV), "-f", str(compose), "up", "-d",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
    except FileNotFoundError:
        _log("docker が見つからない（記憶なしで続行する）")
        return
    except asyncio.TimeoutError:
        _log("docker compose up が5分で終わらなかった（記憶なしで続行する）")
        return
    except Exception as e:  # 起動を止めない
        _log(f"起動に失敗: {type(e).__name__}: {e}")
        return
    tail = (out or b"").decode("utf-8", "replace").strip().splitlines()[-3:]
    _log(f"docker compose up -d → rc={proc.returncode} " + " / ".join(tail))


async def handle(event_type: str, context: dict):
    """gateway:startup で呼ばれる。**待たずに投げる。**"""
    asyncio.create_task(_up())
