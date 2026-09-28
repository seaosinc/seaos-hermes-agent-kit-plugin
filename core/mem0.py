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
from paths import hermes_home, kit_root, profile_dir

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

    path.write_text(
        "# hermes-kit が生成。ここは秘密なのでキットには入れない。\n"
        "# 消すと過去の記憶が読めなくなるので、消さないこと。\n"
        f"MEM0_API_KEY={_secret(40)}\n"
        f"MEM0_PG_PASSWORD={_secret(32)}\n"
        "MEM0_PG_USER=mem0\n"
        "MEM0_PG_DB=mem0\n"
        f"MEM0_NEO4J_PASSWORD={_secret(32)}\n"
        "MEM0_PORT=8888\n",
        encoding="utf-8",
    )
    # 事実抽出と埋め込みの取り寄せ先は、キットのプロバイダに合わせて書く
    _write_settings(path, settings())
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    if log:
        log(f"+ {path}（API キーと DB パスワードを生成）")
    return path


# ── 取り寄せ先（OpenRouter / Bedrock）──────────────────────────────────────

# Bedrock の事実抽出と埋め込み。**次元は表の列と揃える**（compat.py が pgvector にも渡す）。
# 事実抽出は OpenAI 互換の口で呼ぶので、`global.` の付かない ID を使う。
BEDROCK_LLM = "openai.gpt-5.6-luna"
BEDROCK_EMBEDDER = "amazon.titan-embed-text-v2:0"
BEDROCK_EMBEDDING_DIMS = "1024"


def settings() -> Dict[str, str]:
    """mem0 の .env に置く、取り寄せ先の値。**キットの MODEL_PROVIDER に従う。**

    鍵はキットの .env（唯一の正）から取る。OpenRouter のときは MEM0_* のモデル指定を
    空にして、mem0 の既定（gpt-4o / text-embedding-3-small）をそのまま使う。
    """
    from env import read_env
    from paths import env_file

    gen = roles.generator()
    # 窓口（operator）と同じ鍵。役つきの上書きがあればそれ、無ければ共通
    key = roles.env_value("operator", gen.MODEL_KEY, read_env(env_file()))
    if gen.PROVIDER == "bedrock":
        return {
            "MEM0_LLM_API_KEY": key,
            "MEM0_LLM_BASE_URL": gen.BEDROCK_OPENAI_BASE_URL,
            "MEM0_LLM_MODEL": BEDROCK_LLM,
            "MEM0_EMBEDDER_PROVIDER": "aws_bedrock",
            "MEM0_EMBEDDER_MODEL": BEDROCK_EMBEDDER,
            "MEM0_EMBEDDING_DIMS": BEDROCK_EMBEDDING_DIMS,
            "MEM0_AWS_BEARER_TOKEN_BEDROCK": key,
            "MEM0_AWS_REGION": gen.BEDROCK_REGION,
        }
    return {
        "MEM0_LLM_API_KEY": key,
        "MEM0_LLM_BASE_URL": "https://openrouter.ai/api/v1",
        "MEM0_LLM_MODEL": "",
        "MEM0_EMBEDDER_PROVIDER": "",
        "MEM0_EMBEDDER_MODEL": "",
        "MEM0_EMBEDDING_DIMS": "",
        "MEM0_AWS_BEARER_TOKEN_BEDROCK": "",
        "MEM0_AWS_REGION": "",
    }


def _write_settings(path: Path, values: Dict[str, str]) -> bool:
    """mem0 の .env の取り寄せ先の行を書き換える。**秘密（DB のパスワードなど）には触らない。**

    変わったら True。
    """
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    current = _read_env(path)
    if all(current.get(k, "") == v for k, v in values.items()):
        return False
    kept = [line for line in lines if line.partition("=")[0].strip() not in values]
    kept += [f"{k}={v}" for k, v in values.items()]
    path.write_text("\n".join(kept).strip() + "\n", encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return True


def sync(log: Optional[Log] = None) -> bool:
    """取り寄せ先を mem0 に合わせる。**変わったときだけ、動いているコンテナを作り直す。**

    鍵を後から入れた・プロバイダを切り替えた、のどちらもここで届く。
    mem0 を立てていない環境では何もしない。
    """
    if not mem0_env().is_file():
        return True
    if not _write_settings(mem0_env(), settings()):
        return True
    if not running():
        return True
    # イメージにも差がありうる（Bedrock の埋め込みに boto3 が要る）ので、建て直して起こす
    code, _out = _compose("up", "-d", "--build")
    if log:
        log("mem0 を新しい取り寄せ先で起動し直しました" if code == 0
            else "✗ mem0 を起動し直せませんでした")
    return code == 0


def wipe(log: Optional[Log] = None) -> bool:
    """**共有記憶を消す。** 取り寄せ先を切り替えると埋め込みが変わり、これまでの記憶は
    引けなくなる（互換性が無い）ので、作り直す。

    消すのはデータ（ボリューム）だけで、秘密（mem0 の .env）は残す。新しい DB は同じ
    パスワードで初期化される。動いていれば、新しい設定で起こし直す。
    """
    if not have_docker() or not mem0_env().is_file():
        return True
    was_running = running()
    _write_settings(mem0_env(), settings())
    code, _out = _compose("down", "-v")
    if code != 0:
        if log:
            log("✗ 共有記憶を消せませんでした（docker compose down -v）")
        return False
    if log:
        log("共有記憶（mem0）を消しました")
    if was_running:
        code, _out = _compose("up", "-d", "--build")
        if log:
            log("mem0 を新しい取り寄せ先で起動しました" if code == 0 else "✗ mem0 を起動できませんでした")
        return code == 0
    return True


def memory_roles() -> List[str]:
    """mem0 に繋ぐ役。**有効な全役である。**

    共通の規約は全役に `mem0_add` で書かせ、生成器も全役の provider を mem0 にする。
    以前は前例を引く役（fixer）にだけ接続情報を置いていたので、**他の役は書いた
    つもりで一度も届いていなかった**（「mem0 が unavailable」とだけ出て動き続ける）。
    前例の引き方を誰に配るかは、接続とは別に `precedent-lookup` で決める。
    """
    return roles.names()


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
    """有効な全役へ繋ぐ。

    無効にした役のプロファイルが残っていても、そこへは鍵を置かない
    （mem0.json には API キーが入っている）。
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

    for name in roles.all_names():
        if name in pull:
            continue
        stale = profile_dir(name) / "mem0.json"
        if stale.is_file():
            stale.unlink()
            if log:
                log(f"- {name} から接続情報を外した（無効にした役）")
    return True


def rewire(log: Optional[Log] = None) -> None:
    """update のたびに繋ぎ直す。**mem0 を立てていない環境では黙って何もしない。**

    ここを通らないと、後から有効にした役（avatar など）は `mem0 up` を
    やり直すまで繋がらない。
    """
    values = _read_env(mem0_env())
    if values.get("MEM0_PORT") and values.get("MEM0_API_KEY"):
        wire(log=log)


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
