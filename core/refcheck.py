"""**規約に書いてある名前が、実在するかを機械的に照合する。**

規約（SOUL とスキル）に書いた名前が存在しなくても、何も起きない。エージェントは
呼べないまま「この環境ではできない」と正しく観測して止まる。**止まった理由は次の
カードの前提になる**ので、綴り1つの違いが世代を越えて残る。

同じ形で何度も踏んだ:

  * `mem0_search` / `process` ——実在しない道具の綴り
  * `researcher` / `messenger` ——廃止・改名した役が文書に残る
  * `hermes-kit worker new` ——**入口ごと消えているのに全文書がそれを指していた**

照合するのは4種類:

  1. **コマンド** `seaos-kit X` / `hermes X` が実在する下位コマンドか
  2. **道具** `名前(` の形で呼ばれたものを、その役が実際に持っているか
  3. **スキル** 配置表が載せると言ったスキルが、実機の役に届いているか
  4. **名前** `` ` `` で括られた語が、いま実在するものか。**台帳は持たない**
     ——手で足し忘れたら黙って効かなくなるので、役・スキル・下位コマンド・
     選択肢・道具・MCP を実物から集めて、そこに無いものを挙げる
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

import roles as roles_mod
from paths import hermes_bin, hermes_home, kit_root, profile_dir, profiles_dir

# `名前(` の形。道具名は snake_case。
CALL = re.compile(r"\b([a-z][a-z0-9]{2,}(?:_[a-z0-9]+)*)\(")

# 道具ではないが同じ形で出てくる語。**規約に出た実績があるものだけ**を並べる。
NOT_A_TOOL = {
    "def", "if", "for", "print", "json", "yaml", "http", "https", "utf",
    "self", "len", "str", "int", "dict", "list", "set", "get", "post",
    "python3", "npm", "npx", "git", "curl", "grep", "sed", "awk", "docker",
    "hermes", "opencode", "sqlite3", "bash", "zsh", "sh", "cat", "ls",
}

# 下位コマンドを探す。`hermes -p <役> tools list` のような大域オプションは読み飛ばす。
# 値を取る大域オプション。**`hermes -p avatar tools list` の `avatar` を
# 下位コマンドと読み違えないために要る**（読み飛ばす対象を名指しする）。
_OPTS_WITH_VALUE = {
    "-p", "-m", "-t", "-z", "--profile", "--provider", "--reasoning",
    "--resume", "--in", "--skills", "--usage-file", "--model", "--platform",
}

_ENTRY = re.compile(r"\b(seaos-kit|hermes)\b")


def _invocations(body: str):
    r"""行の中の `seaos-kit` / `hermes` の呼び出しから、下位コマンドを取り出す。

    **行をまたがない。** 正規表現の `\s` は改行を含むので、コード塊の隣り合う
    2行が1つの呼び出しに見えて誤検知した。
    """
    for line in body.splitlines():
        for m in _ENTRY.finditer(line):
            rest = line[m.end():].replace("`", " ").split()
            index = 0
            while index < len(rest) and rest[index].startswith("-"):
                skip = 2 if rest[index] in _OPTS_WITH_VALUE else 1
                index += skip
            if index < len(rest) and re.fullmatch(r"[a-z][a-z0-9-]*", rest[index]):
                yield m.group(1), rest[index]


def _subcommands(argv: List[str]) -> Set[str]:
    """`--help` が出す `{a,b,c}` を読む。**入口に直接聞く**ので、実装とズレない。"""
    try:
        proc = subprocess.run(argv + ["--help"], capture_output=True, text=True,
                              timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return set()
    match = re.search(r"\{([a-z0-9_,-]+)\}", proc.stdout)
    return set(match.group(1).split(",")) if match else set()


def _known_commands() -> Dict[str, Set[str]]:
    out: Dict[str, Set[str]] = {}
    kit_cli = kit_root() / "core" / "cli.py"
    out["seaos-kit"] = _subcommands([sys.executable, str(kit_cli)])
    hermes = hermes_bin()
    out["hermes"] = _subcommands([hermes]) if hermes else set()
    return out


def _rule_files(role: str) -> List[Path]:
    """その役に**配られた**規約。定義ではなく、実際に読まれる側を見る。"""
    root = profile_dir(role)
    files = [root / "SOUL.md"]
    files += sorted((root / "skills").glob("*/SKILL.md"))
    return [f for f in files if f.is_file()]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ── 1. コマンド ──────────────────────────────────────────────────────────

def missing_commands(role: str, known: Dict[str, Set[str]]) -> Dict[str, List[str]]:
    """実在しない下位コマンドを名指ししている箇所。"""
    bad: Dict[str, List[str]] = {}
    for path in _rule_files(role):
        for tool, sub in _invocations(_read(path)):
            subs = known.get(tool) or set()
            if not subs or sub in subs:
                continue
            bad.setdefault(f"{tool} {sub}", []).append(path.name)
    return bad


# ── 2. 道具 ──────────────────────────────────────────────────────────────

def _toolset_members() -> Dict[str, Set[str]]:
    """道具セット -> 実際に呼べる道具名。

    **`tools list` が出すのはセットの名前である。** `terminal` セットの中身は
    `terminal` と `process_manage` の2つで、後者は一覧に現れない。セットの名前
    だけで照合すると、`process_manage` を実在しないと言ってしまう。

    定義は `"名前": _ts("説明", ["道具", ...], includes=["別のセット", ...])` の形。
    **説明が複数行に折り返される**ので、1本の正規表現では取れない。
    宣言の位置から最初の `[...]` を拾う。
    """
    f = hermes_home() / "hermes-agent" / "toolsets.py"
    out: Dict[str, Set[str]] = {}
    if not f.is_file():
        return out
    body = _read(f)
    includes: Dict[str, Set[str]] = {}
    for m in re.finditer(r'"([a-z][a-z0-9_-]*)":\s*_ts\(', body):
        name = m.group(1)
        # 宣言の終わりまで（次の宣言か、テーブルの閉じまで）を見る
        tail = body[m.end():m.end() + 2000]
        tools = re.search(r"\[([^\]]*)\]", tail)
        if not tools:
            continue
        out[name] = set(re.findall(r'"([a-z][a-z0-9_]+)"', tools.group(1)))
        inc = re.search(r"includes\s*=\s*\[([^\]]*)\]", tail)
        includes[name] = set(re.findall(r'"([a-z][a-z0-9_-]+)"', inc.group(1))) if inc else set()

    # includes は他のセットを取り込む。**畳まないと中身が漏れる。**
    for name in out:
        seen: Set[str] = set()
        stack = list(includes.get(name, ()))
        while stack:
            other = stack.pop()
            if other in seen:
                continue
            seen.add(other)
            out[name] |= out.get(other, set())
            stack.extend(includes.get(other, ()))
    return out


def _provider_tools(role: str) -> Set[str]:
    """記憶プロバイダが**実行時に注入する**道具。静的な `tools list` には出ない。"""
    cfg = profile_dir(role) / "config.yaml"
    if not cfg.is_file():
        return set()
    m = re.search(r"^memory:\s*\n(?:\s+.*\n)*?\s+provider:\s*(\S+)", _read(cfg), re.M)
    if not m:
        return set()
    f = hermes_home() / "hermes-agent" / "plugins" / "memory" / m.group(1) / "__init__.py"
    return set(re.findall(r'"name":\s*"([a-z][a-z0-9_]+)"', _read(f))) if f.is_file() else set()


def tools_of(role: str, members: Dict[str, Set[str]]) -> Set[str]:
    """その役が実際に呼べる道具。**定義ではなく実体を見る。**"""
    hermes = hermes_bin()
    out: Set[str] = _provider_tools(role)
    if not hermes:
        return out
    for platform in ("cli", "slack"):
        try:
            proc = subprocess.run([hermes, "-p", role, "tools", "list", "--platform", platform],
                                  capture_output=True, text=True, timeout=180,
                                  stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            continue
        for line in proc.stdout.splitlines():
            m = re.search(r"enabled\s+([a-z][a-z0-9_]+)", line)
            if m:
                out.add(m.group(1))
                out |= members.get(m.group(1), set())
    return out


def missing_tools(role: str, members: Dict[str, Set[str]]) -> Tuple[Dict[str, List[str]], bool]:
    have = tools_of(role, members)
    if not have:
        return {}, False
    bad: Dict[str, List[str]] = {}
    for path in _rule_files(role):
        for name in set(CALL.findall(_read(path))):
            if name in NOT_A_TOOL or name in have:
                continue
            bad.setdefault(name, []).append(path.name)
    return bad, True


# ── 3. スキル ────────────────────────────────────────────────────────────

def missing_skills(role: str) -> List[str]:
    """配置表が載せると言ったスキルが、実機の役に届いているか。"""
    import build_distributions as gen

    declared = gen.skills_of(kit_root(), role)
    landed = {p.name for p in (profile_dir(role) / "skills").glob("*") if p.is_dir()}
    return sorted(set(declared) - landed)


# ── 4. 括られた名前が現役か ──────────────────────────────────────────────

_BACKTICK = re.compile(r"`([^`\n]{1,60})`")
# 名前の形。パス・コード片・フラグ・環境変数（大文字）は最初から見ない。
_NAME = re.compile(r"[a-z][a-z0-9-]{2,}")

# 機械的な出どころが無い語。**ここは短いままに保つこと**——長くなってきたら、
# それは導出元を見つけていないという意味である。
_PROSE = {
    "auto-decomposer", "decomposer", "swarm",  # Hermes の仕組みの呼び名
    "capability", "dependency",                # カードの関係の呼び名
    "artifacts", "compliance", "security",     # 分類の語
    "off-topic", "other",                      # 判定の語
}


def _choice_groups(text: str) -> Set[str]:
    """`--help` が出す `{a,b,c}` を全部拾う。状態・種別・並び順がここに出る。"""
    out: Set[str] = set()
    for group in re.findall(r"\{([a-z0-9_,-]+)\}", text):
        out |= set(group.split(","))
    return out


def _help_text(argv: List[str]) -> str:
    try:
        proc = subprocess.run(argv + ["--help"], capture_output=True, text=True,
                              timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout


def vocabulary(used: Set[str]) -> Set[str]:
    """**現役の名前の全体。** 出どころのあるものは、すべて実物から引く。

    `used` は文書に出てきた語。**下位コマンドの `--help` は、実際に使われて
    いるものだけ叩く**（72 個すべてを起動すると doctor が数分になる）。
    """
    known: Set[str] = set(_PROSE)

    import build_distributions as gen

    known |= set(roles_mod.names())
    known |= {p.name for p in (kit_root() / "templates" / "skills").glob("*") if p.is_dir()}
    # 役ごとの専用スキル（`templates/workers/<役>/skills/`）も名前である
    known |= {p.name for p in (kit_root() / "templates" / "workers").glob("*/skills/*") if p.is_dir()}
    known |= set(getattr(gen, "CRON_JOBS", {}))

    kit_cli = [sys.executable, str(kit_root() / "core" / "cli.py")]
    hermes = hermes_bin()
    for entry, argv in (("seaos-kit", kit_cli), ("hermes", [hermes] if hermes else None)):
        if argv is None:
            continue
        text = _help_text(argv)
        subs = _choice_groups(text)
        known |= subs | {entry}
        # **3階層まで降りる。** `hermes kanban list --help` にカードの状態が出る
        # ように、語彙は下の階層に置かれている。使われている枝だけ叩く。
        for sub in sorted(subs & used):
            deeper = _choice_groups(_help_text(argv + [sub]))
            known |= deeper
            for leaf in sorted(deeper & used):
                known |= _choice_groups(_help_text(argv + [sub, leaf]))

    # 設定ファイルのキー。`description` や `platforms` は「名前」ではなく項目名で、
    # 出どころは雛形そのものにある。
    for spec in (kit_root() / "templates" / "workers" / "_template" / "profile.yaml",
                 kit_root() / "plugin.yaml"):
        if spec.is_file():
            known |= set(re.findall(r"^\s*([a-z][a-z0-9_-]*):", _read(spec), re.M))
    for d in profiles_dir().glob("*"):
        meta = d / "distribution.yaml"
        if meta.is_file():
            known |= set(re.findall(r"^\s*([a-z][a-z0-9_-]*):", _read(meta), re.M))

    # 設定ファイルのキー。`description` や `platforms` は「名前」ではなく項目名で、
    # 出どころは雛形そのものにある。
    for spec in (kit_root() / "templates" / "workers" / "_template" / "profile.yaml",
                 kit_root() / "plugin.yaml"):
        if spec.is_file():
            known |= set(re.findall(r"^\s*([a-z][a-z0-9_-]*):", _read(spec), re.M))
    for d in profiles_dir().glob("*"):
        meta = d / "distribution.yaml"
        if meta.is_file():
            known |= set(re.findall(r"^\s*([a-z][a-z0-9_-]*):", _read(meta), re.M))

    members = _toolset_members()
    known |= set(members)
    for tools in members.values():
        known |= tools

    for d in profiles_dir().glob("*"):
        if not d.is_dir() or d.name.startswith("."):
            continue
        known |= {p.name for p in (d / "skills").glob("*") if p.is_dir()}
        known |= _provider_tools(d.name)
        cfg = d / "config.yaml"
        if not cfg.is_file():
            continue
        # MCP サーバの名前と、その役に見えている道具
        for m in re.finditer(r"^  ([a-z][a-z0-9_-]*):$", _read(cfg), re.M):
            known.add(m.group(1))
        known |= set(re.findall(r"^\s+-\s+([a-z][a-z0-9_-]+)$", _read(cfg), re.M))
    return known


def _quoted_names(role: str) -> Dict[str, List[str]]:
    """規約が `` ` `` で括った、名前の形をした語 -> どのファイルで。

    **コード片は ``` で囲う約束**なので、そこは見ない（囲われていないコード片が
    混ざると、シェルのコマンド名まで名前として数えてしまう）。
    """
    out: Dict[str, List[str]] = {}
    for path in _rule_files(role):
        body = re.sub(r"```.*?```", "", _read(path), flags=re.S)
        for token in _BACKTICK.findall(body):
            token = token.strip()
            if _NAME.fullmatch(token):
                out.setdefault(token, []).append(path.name)
    return out


def unknown_names(role: str, known: Set[str]) -> Dict[str, List[str]]:
    return {n: w for n, w in _quoted_names(role).items() if n not in known}


# ── まとめ ───────────────────────────────────────────────────────────────

def used_words(role: str) -> Set[str]:
    """その役の規約に出てきた語。**語彙をどこまで掘るかを決める。**"""
    out = set(_quoted_names(role))
    for path in _rule_files(role):
        for _tool, sub in _invocations(_read(path)):
            out.add(sub)
    return out


def run(rep, *, deep: bool = True) -> None:
    """doctor から呼ばれる。`deep=False` なら道具の照合（役ごとに hermes を起動）を省く。"""
    root = profiles_dir()
    if not root.is_dir():
        return
    commands = _known_commands()
    live = [q for q in sorted(root.iterdir()) if q.is_dir() and not q.name.startswith(".")]
    used: Set[str] = set()
    for d in live:
        used |= used_words(d.name)
    known = vocabulary(used)
    members = _toolset_members() if deep else {}
    # `.deleted` のような、役ではないディレクトリは見ない
    for d in live:
        role = d.name
        problems = 0

        for spelling, where in sorted(missing_commands(role, commands).items()):
            rep.ng(f"{role}: 実在しないコマンド `{spelling}` ← {', '.join(sorted(set(where)))}")
            problems += 1

        unknown = sorted(unknown_names(role, known).items())
        for name, where in unknown:
            # **落とすのではなく挙げる。** 現役に無い＝間違いとは限らず、
            # 括り方の約束から外れているだけのこともある（コード片、架空の例）。
            rep.note(f"{role}: 照合できない名前 `{name}` ← {', '.join(sorted(set(where)))}")

        for name in missing_skills(role):
            rep.ng(f"{role}: 載るはずのスキルが届いていない `{name}`")
            problems += 1

        if deep:
            ghosts, asked = missing_tools(role, members)
            if not asked:
                rep.note(f"{role}: 道具の一覧を取れなかった")
            for name, where in sorted(ghosts.items()):
                rep.ng(f"{role}: 実在しない道具 `{name}` ← {', '.join(sorted(set(where)))}")
                problems += 1

        if problems == 0 and not unknown:
            rep.ok(f"{role}: 名指しした名前はすべて実在する")
