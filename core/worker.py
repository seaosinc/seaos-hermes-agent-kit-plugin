"""業務別ワーカーの CRUD。

**生成先は templates/workers/ だけ。** ~/.hermes への反映は update が担う。
対話プロンプトは出さない（AI が引数だけで操作できるようにするため）。

zsh 版は各操作でヒアドキュメントの Python を起こしていた。ここではそれが
そのまま関数になっている——**本文を YAML で往復させない**という要点は同じで、
profile.yaml / mcp.yaml のコメントには「なぜ shell を持たせないか」のような
役の設計そのものが書いてあり、往復すると全部消える。
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import subprocess
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

import yaml

import hermes
import roles
from paths import hermes_home, kit_root, local_workers_dir, profile_dir

NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class WorkerError(RuntimeError):
    """呼び手に見せる、原因の分かる失敗。"""


def workers_root() -> Path:
    """**新しい役を作る場所。** キットの外に置く。

    キットの中（`templates/workers/`）に作ると、配布のたびに危うい——更新は
    untracked も stash して戻すので衝突すれば取り残され、`install --force` なら
    フォルダごと消える。**配られてくる役と、ここで作った役を分ける。**
    """
    return local_workers_dir()


def shipped_root() -> Path:
    """配布物として配られてくる役。**ここは触らない**（更新で上書きされる）。"""
    return kit_root() / "templates" / "workers"


def worker_dir(name: str) -> Path:
    """その役のフォルダ。**ローカルを先に見る**（同名なら生成器もローカルを採る）。"""
    local = workers_root() / name
    if local.is_dir():
        return local
    shipped = shipped_root() / name
    return shipped if shipped.is_dir() else local


# ── SOUL の検査 ───────────────────────────────────────────────────────────

def check_soul(path: Path) -> None:
    """差し込み口が揃っているか確かめる。

    全文を差し替えられるぶん、**共通規約が落ちる事故**が起きうる。
    """
    if not path.is_file():
        raise WorkerError(f"SOUL が見つからない: {path}")
    text = path.read_text(encoding="utf-8")
    errs: List[str] = []
    if not text.lstrip().startswith("あなたの名前は **{{NAME}}**"):
        errs.append(
            "1行目が「あなたの名前は **{{NAME}}** である。…」で始まっていない"
            "（自分の名前は SOUL の1行目にある、と共通ブロックが言っている）"
        )
    if text.count("{{WORKER_BASE}}") != 1:
        errs.append("{{WORKER_BASE}} がちょうど1つ必要（全ワーカー共通の規約の差し込み口）")
    if "{{EXTRA}}" not in text:
        errs.append("{{EXTRA}} が要る（profile.yaml の extra の差し込み口。末尾に置く）")
    if errs:
        raise WorkerError(f"SOUL の書式が不正: {path}\n" + "\n".join(errs))


# ── profile.yaml / mcp.yaml への書き込み ─────────────────────────────────

def add_env(dst: Path, name: str, desc: str, *, required: bool = False) -> None:
    """`env_requires` へ1件足す。

    **MCP を足すと、たいてい鍵も要る。** 宣言しないと env apply が配らず、
    サーバは起動しても認証されないまま「有効」に見える（実際に踏んだ）。

    **既定は任意である。** `required` は「**無いとキット自体が成り立たない**」
    という意味で、いまそれに当たるのはモデルの鍵だけ。ワーカーの鍵を必須に
    すると、役を1つ足しただけで設定画面の「反映」が全体で押せなくなる
    （実際にそうなっていた）。欠けても困るのはその役の道具であって、
    チーム全体ではない——空なら該当の MCP を無効にして先へ進む。
    """
    path = dst / "profile.yaml"
    text = path.read_text(encoding="utf-8")
    doc = yaml.safe_load(text) or {}
    reqs = [r for r in (doc.get("env_requires") or []) if r.get("name") != name]
    reqs.append({"name": name, "description": desc, "required": required})
    # **説明は JSON で書く。** yaml.safe_dump は長い文字列を折り返して `...`
    # （ドキュメント終端）を足すことがあり、埋めると YAML が壊れる。
    block = "env_requires:\n" + "".join(
        f"- name: {r['name']}\n"
        f"  description: {json.dumps(r.get('description', ''), ensure_ascii=False)}\n"
        f"  required: {str(bool(r.get('required', False))).lower()}\n"
        for r in reqs
    )
    pat = re.compile(r"^env_requires:\n(?:[ -].*\n?)*", re.M)
    if pat.search(text):
        text = pat.sub(block, text, count=1)
    else:
        text = (
            text.rstrip("\n")
            + "\n\n# この役が使う秘密。**値はここに書かない**（正はキット直下の .env）。\n"
            + block
        )
    path.write_text(text, encoding="utf-8")


def add_mcp(dst: Path, key: str, spec_json: str) -> None:
    """`mcp.yaml` の `servers:` へ1つ足す（そのブロックだけ差し替える）。"""
    path = dst / "mcp.yaml"
    try:
        cfg = json.loads(spec_json)
    except Exception as exc:  # noqa: BLE001
        raise WorkerError(f"--mcp の値が JSON として読めない（{key}）: {exc}") from exc
    cfg.setdefault("enabled", True)
    body = yaml.safe_dump({key: cfg}, allow_unicode=True, sort_keys=False)
    block = "".join("  " + line + "\n" for line in body.rstrip("\n").splitlines())

    text = path.read_text(encoding="utf-8") if path.exists() else ""
    # **空のフロー表記を先にほどく。** 雛形は `servers: {}` で始まる。そのまま
    # 下へインデント付きのブロックを足すと YAML として壊れる（フロー表記の後に
    # ブロックマッピングが続く形になる）。zsh 版も同じ判定なので同じ壊れ方をする。
    text = re.sub(r"^servers:\s*\{\s*\}\s*$", "servers:", text, count=1, flags=re.M)
    if "servers:" not in text:
        head = (
            text.rstrip("\n") + "\n"
            if text.strip()
            else (
                "# このワーカー専用の MCP サーバ。生成器が config.yaml へ入れる。\n"
                "# **外部サービスの鍵はここに閉じる。** MCP はホスト側で動くので、\n"
                "# 使い捨てコンテナへトークンが入らない。\n"
            )
        )
        text = head + "servers:\n"

    pat = re.compile(r"^  " + re.escape(key) + r":\n(?:(?:  [ -].*)?\n)*?(?=^  \S|\Z)", re.M)
    text = pat.sub(block, text, count=1) if pat.search(text) else text.rstrip("\n") + "\n" + block
    path.write_text(text, encoding="utf-8")


def _set_scalar(path: Path, field: str, value: str) -> None:
    text = path.read_text(encoding="utf-8")
    text = re.sub(rf"^{field}:.*$", f"{field}: {value}", text, count=1, flags=re.M)
    path.write_text(text, encoding="utf-8")


def _set_description(path: Path, desc: str) -> None:
    text = path.read_text(encoding="utf-8")
    body = "".join(f"  {line}\n" for line in (desc.splitlines() or [desc]))
    text = re.sub(r"^description: >-\n(?:  .*\n)+", "description: >-\n" + body, text, count=1, flags=re.M)
    path.write_text(text, encoding="utf-8")


def _set_extra(path: Path, extra: str) -> None:
    text = path.read_text(encoding="utf-8")
    new = ("extra: |\n" + "".join(f"  {line}\n" for line in extra.splitlines())) if extra else 'extra: ""\n'
    text = re.sub(r"^extra:.*(?:\n  .*)*\n", new, text, count=1, flags=re.M)
    path.write_text(text, encoding="utf-8")


# ── コマンド ─────────────────────────────────────────────────────────────

@dataclass
class NewResult:
    name: str
    path: Path
    source: str
    skills: List[str]
    mcp: List[str]


def new(
    name: str,
    *,
    desc: str,
    summary: str = "",
    model: str = "",
    extra: str = "",
    soul: Optional[Path] = None,
    source: str = "_template",
    skills: Optional[List[Path]] = None,
    mcps: Optional[Dict[str, str]] = None,
    envs: Optional[Dict[str, str]] = None,
) -> NewResult:
    if not NAME_RE.match(name):
        raise WorkerError(f"名前は英小文字で始まり、英小文字・数字・ハイフンのみ: {name}")
    if not desc:
        raise WorkerError("--desc が要る。decomposer はこれを読んで担当を決めるので、空だと仕事が来ない")

    # **雛形は配布側から取り、作る先はローカル。** 下敷きに既存の役を指したときも
    # worker_dir が両方を見るので、配られた役からも複製できる。
    src, dst = worker_dir(source), workers_root() / name
    if not src.is_dir() and source == "_template":
        src = shipped_root() / "_template"
    if not src.is_dir():
        raise WorkerError(f"雛形が無い: {src}")
    if dst.exists():
        raise WorkerError(f"既に存在する: {name}（変更は worker set、削除は worker rm）")

    # **検証はディレクトリを作る前に済ませる。** 途中で失敗すると中途半端な
    # ワーカーが残り、update がそれを配ってしまう。
    if soul is not None:
        check_soul(soul)
    for sk in skills or []:
        if not Path(sk).is_dir():
            raise WorkerError(f"スキルが見つからない: {sk}")
    for key, raw in (mcps or {}).items():
        try:
            json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            raise WorkerError(f"--mcp の値が不正: {key}（{exc}）") from exc

    shutil.copytree(src, dst)
    (dst / "skills" / ".gitkeep").unlink(missing_ok=True)
    if soul is not None:
        shutil.copy(soul, dst / "SOUL.md")

    profile = dst / "profile.yaml"
    _set_scalar(profile, "name", name)
    _set_description(profile, desc)
    if summary:
        _set_scalar(profile, "summary", summary)
    if model:
        _set_scalar(profile, "model", model)
    if extra:
        _set_extra(profile, extra)

    added_skills: List[str] = []
    for sk in skills or []:
        shutil.copytree(Path(sk), dst / "skills" / Path(sk).name, dirs_exist_ok=True)
        added_skills.append(Path(sk).name)
    for var, description in (envs or {}).items():
        add_env(dst, var, description)
    added_mcp: List[str] = []
    for key, raw in (mcps or {}).items():
        add_mcp(dst, key, raw)
        added_mcp.append(key)

    return NewResult(name=name, path=dst, source=source, skills=added_skills, mcp=added_mcp)


def listing() -> List[Dict]:
    """業務別ワーカーの一覧。**配られてきたものと、ここで作ったものの両方。**"""
    rows: List[Dict] = []
    seen: Dict[str, Path] = {}
    for root in (shipped_root(), workers_root()):
        if not root.is_dir():
            continue
        for d in sorted(p for p in root.glob("*") if p.is_dir() and not p.name.startswith("_")):
            seen[d.name] = d
    for d in [seen[k] for k in sorted(seen)]:
        prof: Dict = {}
        pf = d / "profile.yaml"
        if pf.is_file():
            prof = yaml.safe_load(pf.read_text(encoding="utf-8")) or {}
        rows.append(
            {
                # **どちらの出自か。** 配られてくるものは更新で上書きされ、
                # ここで作ったものは残る。触る前に区別が要る。
                "origin": "local" if d.parent == workers_root() else "shipped",
                "name": d.name,
                "model": prof.get("model") or "",
                "deployed": profile_dir(d.name).is_dir(),
                "description": (prof.get("description") or "").strip().replace("\n", " "),
            }
        )
    return rows


def show(name: str) -> Dict:
    d = worker_dir(name)
    if not d.is_dir():
        raise WorkerError(f"存在しない: {name}")
    prof = yaml.safe_load((d / "profile.yaml").read_text(encoding="utf-8")) or {}
    mcp: Dict = {}
    if (d / "mcp.yaml").is_file():
        mcp = (yaml.safe_load((d / "mcp.yaml").read_text(encoding="utf-8")) or {}).get("servers", {}) or {}
    skills = sorted(p.name for p in (d / "skills").glob("*") if p.is_dir())
    return {
        "name": name,
        "path": str(d),
        "deployed": profile_dir(name).is_dir(),
        "model": prof.get("model"),
        "description": (prof.get("description") or "").strip(),
        "extra": (prof.get("extra") or "").strip(),
        "skills": skills,
        "mcp": list(mcp),
    }


def update_worker(
    name: str,
    *,
    desc: Optional[str] = None,
    summary: Optional[str] = None,
    model: Optional[str] = None,
    extra: Optional[str] = None,
    soul: Optional[Path] = None,
    add_skills: Optional[List[Path]] = None,
    rm_skills: Optional[List[str]] = None,
    mcps: Optional[Dict[str, str]] = None,
    envs: Optional[Dict[str, str]] = None,
) -> List[str]:
    d = worker_dir(name)
    if not d.is_dir():
        raise WorkerError(f"存在しない: {name}")
    profile = d / "profile.yaml"
    changed: List[str] = []

    if desc is not None:
        _set_description(profile, desc)
        changed.append("description")
    if summary is not None:
        _set_scalar(profile, "summary", summary)
        changed.append("summary")
    if model is not None:
        _set_scalar(profile, "model", model)
        changed.append("model")
    if extra is not None:
        _set_extra(profile, extra)
        changed.append("extra")
    if soul is not None:
        check_soul(soul)
        shutil.copy(soul, d / "SOUL.md")
        changed.append("soul")
    for sk in add_skills or []:
        if not Path(sk).is_dir():
            raise WorkerError(f"スキルが見つからない: {sk}")
        # 同名は中身ごと差し替える（部分的に古いファイルが残らないように）
        target = d / "skills" / Path(sk).name
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(Path(sk), target)
        changed.append(f"skill:{Path(sk).name}")
    for sk in rm_skills or []:
        target = d / "skills" / sk
        if not target.is_dir():
            raise WorkerError(f"そのスキルは無い: {sk}")
        shutil.rmtree(target)
        changed.append(f"skill-rm:{sk}")
    for key, raw in (mcps or {}).items():
        add_mcp(d, key, raw)
        changed.append(f"mcp:{key}")
    for var, description in (envs or {}).items():
        add_env(d, var, description)
        changed.append(f"env:{var}")

    if not changed:
        raise WorkerError("変更するものが無い（desc / model / extra / soul / skill / mcp / env）")
    return changed


def share(name: str, *, log: Optional[Callable[[str], None]] = None) -> Dict:
    """この環境で作った役を、キットへ取り込む PR にする。

    **プラグインのフォルダではコミットしない。** `hermes plugins update` は
    `git pull --ff-only` なので、ローカルのコミットが1つでもあると**更新そのものが
    止まる**。一時的に clone して、そこで枝を切る。

    **worktree を使う。** 取ってくる必要がなく、オフラインでも通る。

    HEAD は動かないので `--ff-only` の更新は止まらない。**必ず後片付けする**
    ——残すと `.git` にワークツリーの登録が居座る。

    （浅いクローンからは push できないと考えて clone にしていたが、実測すると
    通った。新しいコミットの**親をリモートが既に持っている**ので、浅さは
    関係ない。）

    PR が通ったら、この環境のコピーは消すこと（`worker rm --keep-profile`）。
    残しておくと配布物より優先され続け、以後の更新が効かなくなる。
    """
    say = log or (lambda _l: None)
    d = workers_root() / name
    if not d.is_dir():
        shipped = shipped_root() / name
        if shipped.is_dir():
            raise WorkerError(f"{name} は配布物として入っている（共有済み）")
        raise WorkerError(f"この環境に無い: {name}")

    for tool in ("git", "gh"):
        if not shutil.which(tool):
            raise WorkerError(f"{tool} が見つからない（PR を出すのに要る）")

    code, origin = hermes.run(["--version"])  # noqa: F841  （hermes の有無は無関係）
    proc = subprocess.run(["git", "-C", str(kit_root()), "remote", "get-url", "origin"],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise WorkerError("キットのリモートが分からない（git から入れていない）")
    url = proc.stdout.strip()

    branch = f"worker/{name}"
    root = kit_root()

    def kit_git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "kit"
        say(f"作業用の枝を切る: {branch}")
        made = kit_git("worktree", "add", "-b", branch, str(work), "HEAD")
        if made.returncode != 0:
            raise WorkerError(
                f"作業用の枝を作れなかった（{branch} が既にあるかもしれない）: "
                f"{(made.stdout + made.stderr).strip()[:160]}")

        dest = work / "templates" / "workers" / name
        if dest.exists():
            raise WorkerError(f"{name} は既にキットにある（`worker set` で直すこと）")
        shutil.copytree(d, dest, ignore=shutil.ignore_patterns("__pycache__"))

        def git(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run(["git", "-C", str(work), *args],
                                  capture_output=True, text=True, stdin=subprocess.DEVNULL)

        git("switch", "-c", branch)
        git("add", "-A")
        summary = ""
        prof = dest / "profile.yaml"
        if prof.is_file():
            summary = str((yaml.safe_load(prof.read_text(encoding="utf-8")) or {}).get("summary") or "")
        title = f"役を足す: {name}"
        body = (f"`{name}` をこの環境で作って動かしている。キットへ取り込みたい。\n\n"
                f"{summary}\n\n"
                "---\n"
                "`seaos-kit worker share` が出した PR。**取り込んだら、作った環境側の\n"
                "コピーを消すこと**（`seaos-kit worker rm <役> --keep-profile`）——\n"
                "残すと配布物より優先され続け、以後の更新が効かない。\n")
        if git("commit", "-m", f"{title}\n\n{summary}").returncode != 0:
            raise WorkerError("コミットできなかった")
        if git("push", "-u", "origin", branch).returncode != 0:
            raise WorkerError(f"push できなかった（枝 {branch} が既にあるかもしれない）")

        try:
            pr = subprocess.run(["gh", "pr", "create", "--title", title, "--body", body,
                                 "--head", branch, "--repo", _repo_slug(url)],
                                cwd=str(work), capture_output=True, text=True,
                                stdin=subprocess.DEVNULL)
            if pr.returncode != 0:
                raise WorkerError(f"PR を作れなかった: {(pr.stdout + pr.stderr).strip()[:200]}")
            link = pr.stdout.strip().splitlines()[-1] if pr.stdout.strip() else ""
        finally:
            # **必ず畳む。** 残すと `.git` にワークツリーの登録が居座り、
            # 次の共有で「枝が既にある」と言われる。
            kit_git("worktree", "remove", "--force", str(work))
            kit_git("worktree", "prune")
            kit_git("branch", "-D", branch)

    say(f"PR を出した: {link}")
    say("取り込まれたら、この環境のコピーを消すこと（worker rm --keep-profile）")
    return {"name": name, "branch": branch, "url": link}


def _repo_slug(url: str) -> str:
    """`git@github.com:owner/repo.git` / `https://github.com/owner/repo` -> `owner/repo`"""
    text = url.strip().removesuffix(".git")
    if text.startswith("git@"):
        return text.split(":", 1)[-1]
    return "/".join(text.split("/")[-2:])


def busy_cards(name: str) -> int:
    """進行中のカードを抱えていないか。**消す前に必ず見る。**"""
    db = hermes_home() / "kanban.db"
    if not db.is_file():
        return 0
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            cur = con.execute(
                "SELECT COUNT(*) FROM tasks WHERE assignee=? "
                "AND status IN ('todo','ready','running','blocked','review');",
                (name,),
            )
            return int(cur.fetchone()[0])
        finally:
            con.close()
    except sqlite3.Error:
        return 0


def remove(name: str, *, keep_profile: bool = False) -> Dict:
    if name == "_template":
        raise WorkerError("_template は雛形なので消せない")
    d = worker_dir(name)
    if not d.is_dir():
        raise WorkerError(f"存在しない: {name}")

    busy = busy_cards(name)
    if busy > 0:
        raise WorkerError(f"{name} は進行中のカードを {busy} 件抱えている。先に片付けること")

    # **その役だけの鍵も落とす。** 役が消えれば管理対象から外れるので、
    # 正の `.env` に値が入ったまま取り残される（実際に残った）。
    # 定義を消す前に、何を持っていたかを読む。
    own_keys = [roles.env_key(name, var)
                for var in [*roles.own_env_vars(name), *roles.override_env_vars(name)]]

    shutil.rmtree(d)

    # **外した記録も消す。** 残すと、同じ名前で作り直した役が最初から外れている。
    import selection

    selection.forget(name)

    import env as env_mod

    dropped = []
    for key in own_keys:
        if env_mod.read_env(env_mod.env_file()).get(key) is not None:
            env_mod.drop_value(key)
            dropped.append(key)

    removed_profile = False
    if not keep_profile and profile_dir(name).is_dir():
        # **`-y` が要る。** 無いと対話の確認待ちになり、stdin を閉じているので
        # 黙って終わる——「削除した」と報告しながらプロファイルが残っていた。
        hermes.run(["profile", "delete", name, "-y"], stdin_empty=True)
        # **成否は戻り値ではなくディレクトリの有無で見る。**
        # profile delete は対話確認を求めるため、失敗しても静かに終わることがある。
        removed_profile = not profile_dir(name).is_dir()
    return {"name": name, "template_removed": True,
            "profile_removed": removed_profile, "secrets_removed": dropped}
