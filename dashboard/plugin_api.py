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
from paths import env_file, kit_root, os_kind, profile_dir  # noqa: E402

router = APIRouter()


# ── 読み取り ──────────────────────────────────────────────────────────────

# 役の一行説明。**describe は decomposer 向けの長文**なので画面には出さない
# （「〜してはならない」のような機械向けの指示が混ざる）。人が読む用に短く持つ。
_SUMMARY = {
    "operator": "ユーザーとの窓口。依頼を受けて結果を報告する",
    "fixer": "詰まりを解決し、完了を判定する",
    "broker": "外部エージェントとの連携",
    "avatar": "画面を操作する（人が呼んだときだけ動く）",
    "developer": "実装・検証・PR 作成",
    "senior-developer": "難度の高い実装。セキュリティと品質も見る",
    "handler": "外部サービスの読み書き（GitHub / Backlog / Notion / Slack）",
    "recruiter": "エージェントそのものを新設・改修する",
}


@router.get("/roles")
def list_roles() -> List[Dict]:
    """役の一覧。導入済みかどうかと、人が読む一行説明を返す。"""
    out: List[Dict] = []
    for name in roles.names():
        out.append(
            {
                "name": name,
                "installed": profile_dir(name).is_dir(),
                "summary": _SUMMARY.get(name, roles.describe(name)[:40]),
            }
        )
    return out


def _version() -> Dict:
    """いま動いている版。**「すでに最新です」だけだと、本当に最新なのか
    更新の仕組みが壊れているのか区別が付かない。** 版を添えて答える。
    """
    import subprocess

    root = _REPO
    if not (root / ".git").is_dir():
        return {"revision": "", "date": ""}
    proc = subprocess.run(
        ["git", "-C", str(root), "log", "-1", "--format=%h\t%cd", "--date=format:%m/%d %H:%M"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        return {"revision": "", "date": ""}
    parts = (proc.stdout.strip().split("\t") + ["", ""])[:2]
    return {"revision": parts[0], "date": parts[1]}


@router.post("/self-update")
def self_update() -> Dict:
    """**このプラグイン自身**を最新にする（git pull）。

    更新するのはファイルだけで、動いているプロセスは差し替わらない。
    画面へ反映するにはアプリの再起動が要る——それを呼び手へ伝える。
    """
    import subprocess

    root = _REPO
    if not (root / ".git").is_dir():
        raise HTTPException(status_code=400, detail="git から入れていないので更新できません")
    proc = subprocess.run(
        ["git", "-C", str(root), "pull", "--ff-only"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=out.strip()[:400])
    changed = "Already up to date" not in out
    return {
        "ok": True,
        "changed": changed,
        "version": _version(),
    }


# 鍵どうしの依存。**片方だけ入れても働かない組**を、画面で言えるようにする。
# 「無いと何も動かない」ではないので必須にはしないが、黙って半端に動くのは避ける。
_PAIRS = [
    (("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"),
     "Slack はこの2つが揃って初めて繋がります"),
    (("SLACK_BOT_TOKEN", "SLACK_ALLOWED_USERS"),
     "話せる人を挙げないと、Slack から誰も話しかけられません"),
    (("BACKLOG_DOMAIN", "BACKLOG_API_KEY"),
     "Backlog はこの2つが揃って初めて繋がります"),
]


def _disables() -> Dict[str, List[str]]:
    """鍵ごとに、空だと無効になる MCP（変数名 -> 「役の道具」の一覧）。"""
    import build_distributions as gen

    out: Dict[str, List[str]] = {}
    for name in roles.names():
        for server, needed in gen.mcp_env_vars(kit_root(), name).items():
            for var in needed:
                out.setdefault(var, []).append(f"{name} の {server}")
    return out


@router.get("/version")
def version() -> Dict:
    """いま動いている版。画面の隅に出す。"""
    return _version()


@router.get("/secrets")
def list_secrets() -> List[Dict]:
    """鍵の**名前と充足状況だけ**。値は返さない。

    `required` は「**無いとキット自体が成り立たない**」ものだけに付ける
    （いまは OPENROUTER_API_KEY ひとつ）。それ以外は空でも動くので任意にし、
    代わりに `disables` で「入れないと何が使えなくなるか」を返す。
    """
    source = env_mod.read_env(env_file())
    disables = _disables()
    seen: Dict[str, Dict] = {}
    for name in roles.names():
        for var, required, desc in roles.env_requirements(name):
            entry = seen.setdefault(
                var, {"name": var, "description": desc, "required": False,
                      "usedBy": [], "disables": disables.get(var, [])}
            )
            entry["required"] = entry["required"] or required
            entry["usedBy"].append(name)
    for var, entry in seen.items():
        entry["configured"] = bool(source.get(var))
    return sorted(seen.values(), key=lambda e: (not e["required"], e["name"]))


@router.get("/validate")
def validate() -> Dict:
    """反映してよい状態か。**必須が欠けていれば止める。**

    `blocking` は必須の未設定。`warnings` は片方だけ入っている組など、
    動くけれど期待どおりにならないもの。
    """
    source = env_mod.read_env(env_file())
    blocking = [s["name"] for s in list_secrets()
                if s["required"] and not source.get(s["name"])]
    warnings: List[str] = []
    for group, message in _PAIRS:
        filled = [v for v in group if source.get(v)]
        if filled and len(filled) != len(group):
            missing = [v for v in group if not source.get(v)]
            warnings.append(f"{', '.join(missing)} が空です。{message}")
    return {"ok": not blocking, "blocking": blocking, "warnings": warnings}


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


@router.post("/update")
def run_update(body: Optional[UpdateIn] = None) -> Dict:
    """生成 → 全役へ反映 → 説明文 → 鍵。画面の「更新」が呼ぶ唯一の実行口。

    **役は選ばせない。** 8役はチームとして設計されていて、欠けると成立しない
    （fixer が居ないと詰まりが解けない、operator が居ないと窓口が無い）。
    """
    result = kit.update(force_config=bool(body and body.forceConfig))
    return {"ok": result.ok(), "lines": result.lines}


@router.post("/env/apply")
def run_env_apply() -> Dict:
    result = kit.apply_env()
    return {"ok": result.ok(), "lines": result.lines}
