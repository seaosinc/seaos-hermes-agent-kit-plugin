#!/usr/bin/env python3
"""規約が名指しした道具を、その役が実際に持っているか照合する。

**規約に書いた道具名が実在しなくても、何も起きない。** エージェントは呼べないまま
「この環境ではできない」と正しく観測し、そこで止まる。**止まった理由は次のカードの
前提になる**ので、綴り1つの違いが世代を越えて残る。

同じ形で2回踏んだ:

  * MCP の allowlist に実在しない8個（→ bin/check_mcp_tools.py が照合する）
  * `mem0_search` / `mem0_add`（実在するのは `memory` 1個。自前サーバの mem0 は
    道具ではなくプロバイダとして裏に入るため、この綴りはどの役にも無い）

ここが見るのは**配られた SOUL とスキル**である。`名前(` の形で書かれたものを
道具の呼び出しとみなし、その役の `tools list` と突き合わせる。

終了コード: 実在しない名前があれば 1。
"""

import os
import re
import subprocess
import sys
from pathlib import Path

HERMES = os.environ.get("HERMES_BIN") or str(Path.home() / ".local/bin/hermes")
HHOME = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")

# `名前(` の形。道具名は snake_case で4文字以上。
CALL = re.compile(r"\b([a-z][a-z0-9]{2,}(?:_[a-z0-9]+)*)\(")

# 道具ではないが同じ形で出てくる語。**規約に出た実績があるものだけ**を並べる。
NOT_A_TOOL = {
    "def", "if", "for", "print", "json", "yaml", "http", "https", "utf",
    "self", "len", "str", "int", "dict", "list", "set", "get", "post",
    "python3", "npm", "npx", "git", "curl", "grep", "sed", "awk", "docker",
    "hermes", "opencode", "sqlite3", "bash", "zsh", "sh", "cat", "ls",
}


def _toolset_members() -> dict[str, set[str]]:
    """道具セット -> 実際に呼べる道具名。

    **`tools list` が出すのはセットの名前である。** `terminal` セットの中身は
    `terminal` と `process_manage` の2つで、後者は一覧には現れない。
    セットの名前だけで照合すると、`process_manage` を実在しないと言ってしまう。
    """
    f = HHOME / "hermes-agent" / "toolsets.py"
    out: dict[str, set[str]] = {}
    if not f.exists():
        return out
    body = f.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(
            r'"([a-z][a-z0-9_-]*)":\s*\{[^{}]*?"tools":\s*\[([^\]]*)\]', body, re.S):
        out[m.group(1)] = set(re.findall(r'"([a-z][a-z0-9_]+)"', m.group(2)))
    return out


def _provider_tools(profile: str) -> set[str]:
    """記憶プロバイダが**実行時に注入する**道具。

    `memory.provider: mem0` を入れると、セッション開始時に `mem0_*` が足される。
    **静的な `tools list` には出ない**ので、そこだけを見ると実在するものを
    「無い」と言ってしまう。プロバイダの定義から名前を拾う。
    """
    cfg = HHOME / "profiles" / profile / "config.yaml"
    if not cfg.exists():
        return set()
    m = re.search(r"^memory:\s*\n(?:\s+.*\n)*?\s+provider:\s*(\S+)",
                  cfg.read_text(encoding="utf-8", errors="replace"), re.M)
    if not m:
        return set()
    f = HHOME / "hermes-agent" / "plugins" / "memory" / m.group(1) / "__init__.py"
    if not f.exists():
        return set()
    return set(re.findall(r'"name":\s*"([a-z][a-z0-9_]+)"',
                          f.read_text(encoding="utf-8", errors="replace")))


def tools_of(profile: str, members: dict[str, set[str]]) -> set[str]:
    """その役が実際に呼べる道具。**定義ではなく実体を見る。**"""
    out: set[str] = _provider_tools(profile)
    for platform in ("cli", "slack"):
        r = subprocess.run(
            [HERMES, "-p", profile, "tools", "list", "--platform", platform],
            capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL,
        )
        for line in r.stdout.splitlines():
            m = re.search(r"enabled\s+([a-z][a-z0-9_]+)", line)
            if m:
                out.add(m.group(1))
                out |= members.get(m.group(1), set())
    return out


def referenced(profile: str) -> dict[str, list[str]]:
    """配られた規約が名指ししている道具 -> どのファイルで。"""
    root = HHOME / "profiles" / profile
    found: dict[str, list[str]] = {}
    files = [root / "SOUL.md"] + sorted((root / "skills").glob("*/SKILL.md"))
    for f in files:
        if not f.exists():
            continue
        for name in set(CALL.findall(f.read_text(encoding="utf-8", errors="replace"))):
            if name in NOT_A_TOOL:
                continue
            found.setdefault(name, []).append(
                str(f.relative_to(root)))
    return found


def main() -> int:
    root = HHOME / "profiles"
    if not root.is_dir():
        return 0
    fail = 0
    members = _toolset_members()
    # `.deleted` のような、役ではないディレクトリは見ない
    for d in sorted(p for p in root.iterdir()
                    if p.is_dir() and not p.name.startswith(".")):
        have = tools_of(d.name, members)
        if not have:
            print(f"? {d.name}: 道具の一覧を取れなかった")
            continue
        ghost = {n: w for n, w in referenced(d.name).items() if n not in have}
        if not ghost:
            print(f"✓ {d.name}: 規約が名指しした道具はすべて実在する")
            continue
        print(f"✗ {d.name}: 実在しない道具を名指ししている"
              "（呼べないまま「できない」と報告して止まる）")
        for n, where in sorted(ghost.items()):
            print(f"    {n}  ← {', '.join(sorted(set(where)))}")
        fail = 1
    return fail


if __name__ == "__main__":
    sys.exit(main())
