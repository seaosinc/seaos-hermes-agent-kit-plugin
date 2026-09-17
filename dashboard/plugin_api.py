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
from paths import env_file, git_bin, kit_root, os_kind, profile_dir  # noqa: E402

router = APIRouter()


# ── 読み取り ──────────────────────────────────────────────────────────────

def _source() -> Dict[str, str]:
    """いま入っている値。**値そのものは画面へ返さない**——有無だけを見る。"""
    return env_mod.read_env(env_file())


@router.get("/roles")
def list_roles() -> List[Dict]:
    """役の一覧。導入済みかどうかと、人が読む一行説明を返す。

    **無効にした役も返す。** 画面で入れ直せないと、一度外した役が戻せない。
    """
    out: List[Dict] = []
    enabled = set(roles.names())
    source = _source()  # 鍵ごとに .env を読み直さない
    for name in roles.all_names():
        out.append(
            {
                "name": name,
                "installed": profile_dir(name).is_dir(),
                # 反映の対象か。`essential` は外せない（板の仕組みが前提にしている）
                "enabled": name in enabled,
                "essential": roles.essential(name),
                "summary": roles.summary(name),
                # **その役だけの鍵。** 共通の一覧に混ぜると、窓口の数だけ行が増えて
                # 読めなくなる（実際にそうなった）。役の行から開く。
                "ownSecrets": [
                    {
                        "name": roles.env_key(name, var),
                        "label": var,
                        "description": desc,
                        "configured": bool(source.get(roles.env_key(name, var))),
                        **_plain_fields(var, source.get(roles.env_key(name, var), "")),
                    }
                    for var, _req, desc in roles.env_requirements(name)
                    if var in set(roles.own_env_vars(name))
                ],
                # **共通の値を、この役だけ差し替える鍵。** 空なら共通を使う。
                "overrideSecrets": [
                    {
                        "name": roles.env_key(name, var),
                        "label": var,
                        "description": "この役だけ別の値を使うときに入れます。未設定なら共通の値を使います。",
                        "configured": bool(source.get(roles.env_key(name, var))),
                        "override": True,
                    }
                    for var in roles.override_env_vars(name)
                ],
                # 配られてきた役か、この環境で作った役か。後者は git に入らない
                "origin": roles.origin(name),
            }
        )
    return out


def _plain_fields(var: str, value: str) -> Dict:
    """**秘密ではない値だけ**、画面に値を返す（roles.PLAIN_ENV）。鍵は有無だけ。"""
    return {"plain": True, "value": value} if roles.is_plain(var) else {}


def _git_revision() -> str:
    """ディスクにある版（短縮 sha）。"""
    import subprocess

    root = _REPO
    if not (root / ".git").is_dir():
        return ""
    # **読み込み時に呼ばれる。ここで例外を出すと API がまるごと載らない**
    # （Windows で git が PATH に無く、画面が開けなくなった）。版は無くても動く。
    try:
        proc = subprocess.run([git_bin(), "-C", str(root), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


# **このプロセスが読み込まれた時点の版。**
# バックエンドはゲートウェイの起動時に一度だけ読み込まれる。`plugins update` で
# ファイルが新しくなっても、動いているコードは古いまま——そして版の表示は
# ディスクを読むので、**新しい版を表示しながら中身は古い**という嘘をつく。
# 実際にそれで「鍵が未設定」と表示された（古いコードが、移動前の場所を見ていた）。
_LOADED_REVISION = _git_revision()


def _version() -> Dict:
    """いま動いている版。**「すでに最新です」だけだと、本当に最新なのか
    更新の仕組みが壊れているのか区別が付かない。** 版を添えて答える。
    """
    import subprocess

    root = _REPO
    if not (root / ".git").is_dir():
        return {"revision": "", "date": ""}
    try:
        proc = subprocess.run(
            [git_bin(), "-C", str(root), "log", "-1", "--format=%h\t%cd", "--date=format:%m/%d %H:%M"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return {"revision": "", "date": ""}
    if proc.returncode != 0:
        return {"revision": "", "date": ""}
    parts = (proc.stdout.strip().split("\t") + ["", ""])[:2]
    return {
        "revision": parts[0],
        "date": parts[1],
        # 動いているコードの版。ディスクと食い違えば、再起動するまで
        # 画面の内容は当てにならない。
        "loaded": _LOADED_REVISION,
        "stale": bool(_LOADED_REVISION and parts[0] and _LOADED_REVISION != parts[0]),
    }


@router.post("/self-update")
def self_update() -> Dict:
    """**このプラグイン自身**を最新にする（git pull）。

    更新するのはファイルだけで、動いているプロセスは差し替わらない。
    画面へ反映するにはアプリの再起動が要る——それを呼び手へ伝える。
    """
    import subprocess

    root = _REPO
    if not (root / ".git").is_dir():
        raise HTTPException(status_code=400, detail="git から導入していないため、更新できません")
    try:
        proc = subprocess.run(
            [git_bin(), "-C", str(root), "pull", "--ff-only"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=500, detail=f"git を実行できません: {exc}")
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
# **役つきの名前にも効かせる。** 窓口ごとに鍵が分かれるので、組の判定も
# 役ごとに行う（`OPERATOR__SLACK_BOT_TOKEN` と `OPERATOR__SLACK_APP_TOKEN`）。
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


@router.get("/ui.js")
def ui_source() -> Dict:
    """画面の中身（desktop/ui.js）を、**その場でディスクから読んで**返す。

    Hermes はプラグインの JS を起動時に一度だけ読み込み、⌘K の Reload desktop
    plugins は既知のファイルを素通りする。**編集を反映する手がホストに無い。**
    そこで薄い皮だけを常駐させ、中身はここから取り直す。

    毎回読み直すのが肝で、キャッシュしない——`hermes plugins update` で
    ファイルが入れ替わった直後に、そのまま新しいものが出る。
    """
    path = _REPO / "desktop" / "ui.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="desktop/ui.js が見当たりません")
    return {"source": path.read_text(encoding="utf-8")}


@router.get("/version")
def version() -> Dict:
    """いま動いている版。画面の隅に出す。"""
    return _version()


@router.get("/secrets")
def list_secrets() -> List[Dict]:
    """鍵の**名前と充足状況だけ**。値は返さない。

    例外は秘密ではない値（Slack の ID やドメイン。roles.PLAIN_ENV）で、
    これだけは値も返す。伏せると、入っている値を確かめながら直せない。

    `required` は「**無いとキット自体が成り立たない**」ものだけに付ける
    （いまは OPENROUTER_API_KEY ひとつ）。それ以外は空でも動くので任意にし、
    代わりに `disables` で「入れないと何が使えなくなるか」を返す。
    """
    source = env_mod.read_env(env_file())
    disables = _disables()
    seen: Dict[str, Dict] = {}
    for name in roles.names():
        own = set(roles.own_env_vars(name))
        for var, required, desc in roles.env_requirements(name):
            # **役ごとに持つ鍵は、行を分ける。** 窓口が複数あるとき、同じ値を
            # 共有すると両方が同じ発言に返事をするので、共有させない。
            if var in own:
                # 役ごとの鍵は、その役の行から設定する（/roles が返す）
                continue
            entry = seen.setdefault(
                var, {"name": var, "label": var,
                      "description": desc, "required": False,
                      "usedBy": [], "disables": disables.get(var, [])}
            )
            entry["required"] = entry["required"] or required
            entry["usedBy"].append(name)
    for var, entry in seen.items():
        entry["configured"] = bool(source.get(var))
        entry.update(_plain_fields(var, source.get(var, "")))
        # **全員が自分の値を持っていれば、共通は無くても動く。** 必須のまま
        # 赤く出すと、埋める必要の無い欄を埋めさせることになる。
        if entry["required"] and not entry["configured"] and _all_overridden(var, entry["usedBy"], source):
            entry["required"] = False
    return sorted(seen.values(), key=lambda e: (not e["required"], e["name"]))


def _all_overridden(var: str, users: List[str], source: Dict[str, str]) -> bool:
    """その鍵を使う役が、**全員**役ごとの値を持っているか。"""
    return bool(users) and all(
        var in roles.override_env_vars(role) and source.get(roles.env_key(role, var))
        for role in users
    )


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
        # 共有の名前と、役つきの名前の両方で見る
        candidates = [group]
        for role in roles.names():
            own = set(roles.own_env_vars(role))
            if all(v in own for v in group):
                candidates.append(tuple(roles.env_key(role, v) for v in group))
        for names_ in candidates:
            filled = [v for v in names_ if source.get(v)]
            if filled and len(filled) != len(names_):
                missing = [v for v in names_ if not source.get(v)]
                warnings.append(f"{', '.join(missing)} が空です。{message}")
    return {"ok": not blocking, "blocking": blocking, "warnings": warnings}


@router.get("/machine")
def machine_status() -> Dict:
    """この PC の道具。**足りないものは provisioner が揃える**ので、画面は見せるだけ。"""
    import machine

    return {
        "tools": machine.status(),
        # provisioner を外していると誰も揃えない。そのときだけ入れ方を見せる
        "provisioner": "provisioner" in roles.names(),
    }


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
        raise HTTPException(status_code=400, detail=f"{body.name} は管理対象外の項目です")

    if not body.value:
        # **空で送られたら、役ごとの上書きを外す**（共通の値へ戻す）。
        # それ以外を空にする口は作らない——必須の鍵が画面から消せてしまう。
        overrides = {roles.env_key(r, v) for r in roles.all_names() for v in roles.override_env_vars(r)}
        if body.name not in overrides:
            raise HTTPException(status_code=400, detail="値が空です")
        env_mod.drop_value(body.name)
        return {"name": body.name, "configured": False}

    env_mod.set_value(body.name, body.value, f"{body.name}（GUI から設定）")
    return {"name": body.name, "configured": bool(body.value)}


class UpdateIn(BaseModel):
    forceConfig: bool = False


class ShareIn(BaseModel):
    name: str


@router.post("/share")
def share_role(body: ShareIn) -> Dict:
    """この環境で作った役を、キットへ取り込む PR にする。

    **プラグインのフォルダではコミットしない**（`plugins update` は `--ff-only` なので、
    ローカルのコミットが1つでもあると更新そのものが止まる）。一時的に clone する。
    """
    import worker as worker_mod

    if roles.origin(body.name) != "local":
        raise HTTPException(status_code=400, detail="このエージェントは配布済みです")
    try:
        out = worker_mod.share(body.name)
    except Exception as exc:  # noqa: BLE001  （原因をそのまま画面へ出す）
        raise HTTPException(status_code=500, detail=str(exc))
    return out


@router.get("/roles/{name}/removal")
def removal_impact(name: str) -> Dict:
    """消す前に、何が起きるかを返す。**押す前に見せるため。**

    プロファイルごと消すと**記憶とセッションが失われ、戻せない**。
    進行中のカードがあれば、そもそも消せない。
    """
    import worker as worker_mod

    # **読むだけなので、配られた役にも答える。** 無効にするときも同じ確認を出す。
    if name not in roles.all_names():
        raise HTTPException(status_code=404, detail=f"そのエージェントはありません: {name}")
    pdir = profile_dir(name)
    memories = len(list((pdir / "memories").glob("*"))) if (pdir / "memories").is_dir() else 0
    sessions = len(list((pdir / "sessions").glob("*"))) if (pdir / "sessions").is_dir() else 0
    return {
        "name": name,
        "busy": worker_mod.busy_cards(name),
        "installed": pdir.is_dir(),
        "memories": memories,
        "sessions": sessions,
    }


class EnableIn(BaseModel):
    name: str
    enabled: bool
    # 無効にするときだけ見る。**既定は残す**（記憶とセッションは戻せない）。
    removeProfile: bool = False


@router.post("/roles/enabled")
def set_role_enabled(body: EnableIn) -> Dict:
    """役を入れる／外す。

    **有効にするのは記録だけ**で、導入は「エージェントを反映」で行う。
    無効にすると、以後の反映・鍵の配布・検証から外れる。
    """
    import selection

    try:
        if body.enabled:
            result = kit.enable_role(body.name)
        else:
            result = kit.disable_role(body.name, remove_profile=body.removeProfile)
    except selection.SelectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": result.ok(), "lines": result.lines}


class RemoveIn(BaseModel):
    name: str
    # **既定は残す。** 記憶とセッションは戻せないので、消すほうを明示させる。
    keepProfile: bool = True


@router.post("/roles/remove")
def remove_role(body: RemoveIn) -> Dict:
    """この環境で作った役を消す。

    **配布物は消せない。** 消してもキットから配り直されるだけで、
    実態は「古い版に戻す」でしかない。
    """
    import worker as worker_mod

    if roles.origin(body.name) != "local":
        raise HTTPException(status_code=400, detail="配布されたエージェントはここから削除できません")
    try:
        return worker_mod.remove(body.name, keep_profile=body.keepProfile)
    except Exception as exc:  # noqa: BLE001  （進行中のカードなど、理由をそのまま画面へ）
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/update")
def run_update(body: Optional[UpdateIn] = None) -> Dict:
    """生成 → 全役へ反映 → 説明文 → 鍵。画面の「更新」が呼ぶ唯一の実行口。

    **反映の対象は、有効にしてある役だけ。** 選ぶのはこの呼び出しではなく、
    役の行のスイッチ（/roles/enabled）で先に済ませておく。
    """
    result = kit.update(force_config=bool(body and body.forceConfig))
    return {"ok": result.ok(), "lines": result.lines}


@router.post("/env/apply")
def run_env_apply() -> Dict:
    result = kit.apply_env()
    return {"ok": result.ok(), "lines": result.lines}
