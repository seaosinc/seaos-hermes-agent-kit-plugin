"""ワーカー間で共有する記憶（mem0 セルフホスト）。

compose.yml はキットに入れて版管理し、**秘密（API キー・DB パスワード）は
`~/.hermes/mem0/.env`** に置く。.env はキットに入れない。

**秘密は作り直さない。** 消す・作り直すと過去の記憶が読めなくなる。
既存の .env には、後から必須になった項目だけを足す。
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import roles
from paths import hermes_home, kit_root, profile_dir, profiles_dir

Log = Callable[[str], None]

# 全ワーカーが同じ記憶を読む（operator / fixer は built-in のまま）。
USER_ID = os.environ.get("MEM0_USER_ID", "hermes-workers")


def mem0_dir() -> Path:
    return hermes_home() / "mem0"


def mem0_env() -> Path:
    return mem0_dir() / ".env"


def compose_file() -> Path:
    return kit_root() / "templates" / "mem0" / "compose.yml"


def have_docker() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(
        ["docker", "info"], capture_output=True, stdin=subprocess.DEVNULL
    ).returncode == 0


def _compose(*args: str) -> Tuple[int, str]:
    proc = subprocess.run(
        ["docker", "compose", "--env-file", str(mem0_env()), "-f", str(compose_file()), *args],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _secret(length: int = 32) -> str:
    raw = base64.b64encode(secrets.token_bytes(48)).decode()
    return "".join(c for c in raw if c not in "/+=")[:length]


def _read_env(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v
    return out


def ensure_env(log: Optional[Log] = None) -> Path:
    """秘密を用意する。**既にある値は触らない。**"""
    mem0_dir().mkdir(parents=True, exist_ok=True)
    path = mem0_env()

    if path.is_file():
        current = _read_env(path)
        if "MEM0_NEO4J_PASSWORD" not in current:
            # compose.yml が必須にしている。無いと起動前に compose が落ちる。
            with path.open("a", encoding="utf-8") as fh:
                fh.write(f"MEM0_NEO4J_PASSWORD={_secret(32)}\n")
            if log:
                log("+ MEM0_NEO4J_PASSWORD を追記（compose.yml が必須にしている）")
        return path

    # 事実抽出は OpenRouter に寄せる（既存のプロファイルから鍵を拾う）
    llm_key = ""
    for candidate in (profile_dir("operator") / ".env", hermes_home() / ".env", kit_root() / ".env"):
        llm_key = _read_env(candidate).get("OPENROUTER_API_KEY", "")
        if llm_key:
            break

    path.write_text(
        "# hermes-kit が生成。ここは秘密なのでキットには入れない。\n"
        "# 消すと過去の記憶が読めなくなるので、消さないこと。\n"
        f"MEM0_API_KEY={_secret(40)}\n"
        f"MEM0_PG_PASSWORD={_secret(32)}\n"
        "MEM0_PG_USER=mem0\n"
        "MEM0_PG_DB=mem0\n"
        f"MEM0_NEO4J_PASSWORD={_secret(32)}\n"
        "MEM0_PORT=8888\n"
        f"MEM0_LLM_API_KEY={llm_key}\n"
        "MEM0_LLM_BASE_URL=https://openrouter.ai/api/v1\n",
        encoding="utf-8",
    )
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    if log:
        log(f"+ {path}（API キーと DB パスワードを生成）")
    return path


def memory_roles() -> List[str]:
    """共有記憶を引く役。**ここで名簿を持たない**（持つと役を増やしたときにずれる）。"""
    return [n for n, sp in roles.all_specs().items() if sp.get("memory")]


def wire_one(name: str, port: str, key: str, log: Optional[Log] = None) -> bool:
    """1体を mem0 に繋ぐ。

    **どの provider を使うかは配布物が持つ**（生成器が config へ書く）。ここが
    持つのは接続先と鍵だけ——秘密なので配布物に載せられない。2箇所で決めない。
    """
    pdir = profile_dir(name)
    if not pdir.is_dir():
        return True
    target = pdir / "mem0.json"
    before = target.read_text(encoding="utf-8") if target.is_file() else ""
    payload = {
        "base_url": f"http://localhost:{port}",
        "api_key": key,
        "user_id": USER_ID,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    if log and target.read_text(encoding="utf-8") != before:
        log(f"+ {name} を mem0 に接続（user_id={USER_ID}）")
    return True


def wire(log: Optional[Log] = None) -> bool:
    """引く役へ繋ぎ、**引かない役からは接続情報を外す。**

    mem0.json には API キーが入っている。provider が選ばれていなければ動作は
    しないが、鍵は使う役だけに置く。
    """
    values = _read_env(mem0_env())
    port, key = values.get("MEM0_PORT", ""), values.get("MEM0_API_KEY", "")
    if not port or not key:
        if log:
            log(f"✗ {mem0_env()} が読めない")
        return False

    pull = memory_roles()
    for name in pull:
        wire_one(name, port, key, log=log)

    for name in roles.names():
        if name in pull:
            continue
        stale = profile_dir(name) / "mem0.json"
        if stale.is_file():
            stale.unlink()
            if log:
                log(f"- {name} から接続情報を外した（記憶を引かない役）")
    return True


def wire_new_worker(name: str, log: Optional[Log] = None) -> None:
    """update が新しいプロファイルを作った直後に呼ぶ。

    ここを通らないと doctor が「mem0 を参照していない」で落ち、ワーカーを
    増やすたびに install が要るはめになる。mem0 が無い環境では黙って何もしない。
    """
    values = _read_env(mem0_env())
    port, key = values.get("MEM0_PORT", ""), values.get("MEM0_API_KEY", "")
    if port and key:
        wire_one(name, port, key, log=log)


def up(log: Optional[Log] = None) -> bool:
    if not have_docker():
        if log:
            log("= Docker が使えないので mem0 は起動しない")
        return True
    ensure_env(log=log)
    code, out = _compose("ps", "--status", "running")
    if "hermes-mem0-api" in out:
        if log:
            log("= mem0 は起動済み")
    else:
        code, _out = _compose("up", "-d")
        if code != 0:
            if log:
                log("✗ mem0 の起動に失敗")
            return False
        if log:
            log("+ mem0 を起動（docker compose up -d）")
    return wire(log=log)


def down(log: Optional[Log] = None) -> bool:
    if not have_docker():
        return True
    code, _ = _compose("down")
    if log:
        log("mem0 を停止した" if code == 0 else "✗ mem0 の停止に失敗")
    return code == 0


def running() -> bool:
    if not have_docker() or not mem0_env().is_file():
        return False
    _code, out = _compose("ps", "--status", "running")
    return "hermes-mem0-api" in out
