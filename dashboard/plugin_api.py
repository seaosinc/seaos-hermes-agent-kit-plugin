"""Agent Kit — バックエンド。

`/api/plugins/seaos-hermes-agent-kit/` にマウントされる。

**この層は薄い。** すべてのハンドラは `core/` の関数を呼ぶだけで、判断も分岐も
持たない。CLI（`core/cli.py`）と GUI がまったく同じ関数を通るので、片方を直したら
もう片方が古くなる、という食い違いが起きない。

秘密の扱い
----------
**鍵の値をレスポンスへ返さない。** 画面へ返すのは「設定済み / 未設定」だけで、
値そのものは一度も画面に乗らない。保存先はキット直下の `.env`（唯一の正）で、
CLI から入れても GUI から入れても同じ場所に置かれる。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# core/ を import 可能にする（このファイルはリポジトリ内の dashboard/ にある）
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "core"))

import env as env_mod  # noqa: E402
import kit  # noqa: E402
import roles  # noqa: E402
from paths import env_file, os_kind, profile_dir  # noqa: E402

router = APIRouter()


# ── 読み取り ──────────────────────────────────────────────────────────────

@router.get("/roles")
def list_roles() -> List[Dict]:
    """役の一覧。導入済みかどうかも返す（画面の初期表示に要る）。"""
    out: List[Dict] = []
    board_less = set(roles.without_board())
    for name in roles.names():
        out.append(
            {
                "name": name,
                "installed": profile_dir(name).is_dir(),
                "onBoard": name not in board_less,
                "describe": roles.describe(name),
            }
        )
    return out


@router.get("/secrets")
def list_secrets() -> List[Dict]:
    """鍵の**名前と充足状況だけ**。値は返さない。"""
    source = env_mod.read_env(env_file())
    seen: Dict[str, Dict] = {}
    for name in roles.names():
        for var, required, desc in roles.env_requirements(name):
            entry = seen.setdefault(
                var, {"name": var, "description": desc, "required": False, "usedBy": []}
            )
            entry["required"] = entry["required"] or required
            entry["usedBy"].append(name)
    for var, entry in seen.items():
        entry["configured"] = bool(source.get(var))
    return sorted(seen.values(), key=lambda e: (not e["required"], e["name"]))


@router.get("/status")
def status() -> Dict:
    """いまの状態。差分の有無まで見るので、押す前に何が起きるか分かる。"""
    result = kit.diff()
    return {
        "os": os_kind(),
        "envFile": str(env_file()),
        "envExists": env_file().is_file(),
        "changes": result.lines,
    }


# ── 書き込み ──────────────────────────────────────────────────────────────

class SecretIn(BaseModel):
    name: str
    value: str


@router.post("/secrets")
def set_secret(body: SecretIn) -> Dict:
    """鍵を `.env` へ書く。**値は返さない。**

    キットが知っている変数だけを受け付ける。知らない名前を弾くのは、画面から
    任意のキーを書き込める口にしないため。
    """
    if body.name not in roles.managed_env_vars():
        raise HTTPException(status_code=400, detail=f"知らない変数: {body.name}")

    env_mod.set_value(body.name, body.value, f"{body.name}（GUI から設定）")
    return {"name": body.name, "configured": bool(body.value)}


class UpdateIn(BaseModel):
    forceConfig: bool = False
    # ON にした役。**None なら現状維持**（いま入っている役だけを更新する）。
    enabled: Optional[List[str]] = None


@router.post("/update")
def run_update(body: Optional[UpdateIn] = None) -> Dict:
    """生成 → 各役へ反映 → 説明文 → 鍵。ウィザードの最後の一押し。

    `enabled` が来たら、**あるべき状態に合わせる**——ON は入れ、OFF は消す。
    OFF はプロファイル削除なので、走行中のカードを抱えた役は消さずに残す。
    """
    force = bool(body and body.forceConfig)
    if body is not None and body.enabled is not None:
        unknown = set(body.enabled) - set(roles.names())
        if unknown:
            raise HTTPException(status_code=400, detail=f"知らない役: {', '.join(sorted(unknown))}")
        result = kit.apply_roles(set(body.enabled), force_config=force)
    else:
        result = kit.update(force_config=force)
    return {"ok": result.ok(), "lines": result.lines}


@router.post("/env/apply")
def run_env_apply() -> Dict:
    result = kit.apply_env()
    return {"ok": result.ok(), "lines": result.lines}
