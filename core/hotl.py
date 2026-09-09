"""HOTL（Human Out The Loop）の検証。

**設定を当てるのは配布物の仕事**（生成器が config.yaml に書く）。
ここに残るのは doctor から呼ばれる検査だけである。
"""

from __future__ import annotations

from typing import Callable, List, Optional

import yaml

import roles
from paths import profile_dir

Log = Callable[[str], None]

# 対象プロファイルと、そこに入っているべきキー。**生成器と揃える。**
HOTL_PROFILES = ("recruiter",)
HOTL_KEYS = {
    "approvals.mode": "off",
    "approvals.cron_mode": "approve",
    "approvals.single_query_mode": "approve",
    "approvals.mcp_reload_confirm": "false",
    "approvals.destructive_slash_confirm": "false",
    "security.protected_instruction_files": "false",
    "hooks_auto_accept": "true",
}


def _get(cfg: dict, path: str):
    cur = cfg
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _as_text(value) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return "" if value is None else str(value)


def check(log: Optional[Log] = None) -> bool:
    say: Log = log or (lambda _l: None)
    ok = True
    for name in roles.names():
        path = profile_dir(name) / "config.yaml"
        if not path.is_file():
            continue
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        if name not in HOTL_PROFILES:
            # **対象外が緩んでいたら知らせる。** 命令ファイルの保護は既定で有効であるべき。
            loose: List[str] = []
            if _get(cfg, "approvals.mode") == "off":
                loose.append("approvals.mode=off")
            if _get(cfg, "security.protected_instruction_files") is False:
                loose.append("security.protected_instruction_files=false")
            if loose:
                say(f"✗ {name}: HOTL 対象外なのに緩んでいる（{' '.join(loose)}）")
                ok = False
            else:
                say(f"✓ {name}（保護は既定のまま）")
            continue

        bad = [key for key, want in HOTL_KEYS.items() if _as_text(_get(cfg, key)) != want]
        if bad:
            say(f"✗ {name}: {' '.join(bad)} が HOTL の設定になっていない → update --force-config")
            ok = False
        else:
            say(f"✓ {name}")
    return ok
