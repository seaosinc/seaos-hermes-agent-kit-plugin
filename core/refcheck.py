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
  4. **役** 廃止・改名した名前が文書に残っていないか（RETIRED と突き合わせる）
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

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


# ── 4. 役 ────────────────────────────────────────────────────────────────

def retired_mentions(role: str) -> Dict[str, List[str]]:
    """**廃止・改名した役の名前が規約に残っていないか。**

    生成物は正しいのに、エージェントが読む文書だけが古いという形で残る。
    build も test も気づかないので、名指しで照合する。
    """
    import build_distributions as gen

    retired = getattr(gen, "RETIRED", ())
    if not retired:
        return {}
    bad: Dict[str, List[str]] = {}
    for path in _rule_files(role):
        body = _read(path)
        for name in retired:
            if re.search(rf"\b{re.escape(name)}\b", body):
                bad.setdefault(name, []).append(path.name)
    return bad


# ── まとめ ───────────────────────────────────────────────────────────────

def run(rep, *, deep: bool = True) -> None:
    """doctor から呼ばれる。`deep=False` なら道具の照合（役ごとに hermes を起動）を省く。"""
    root = profiles_dir()
    if not root.is_dir():
        return
    known = _known_commands()
    members = _toolset_members() if deep else {}
    # `.deleted` のような、役ではないディレクトリは見ない
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        role = d.name
        problems = 0

        for spelling, where in sorted(missing_commands(role, known).items()):
            rep.ng(f"{role}: 実在しないコマンド `{spelling}` ← {', '.join(sorted(set(where)))}")
            problems += 1

        for name, where in sorted(retired_mentions(role).items()):
            rep.ng(f"{role}: 廃止した役 `{name}` を参照 ← {', '.join(sorted(set(where)))}")
            problems += 1

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

        if problems == 0:
            rep.ok(f"{role}: 名指しした名前はすべて実在する")
