#!/usr/bin/env python3
"""allowlist に書いた道具の名前が、サーバに実在するか照合する。

**include に無い名前を書いても、何も起きない。** 綴りが違えば黙って落ちるだけで、
警告もエラーも出ない。残った道具だけで役は動き続けるので、**足りないことに
気づけるのは、その道具を使う仕事が来たときだけ**である。

実際に researcher〈現 handler〉の GitHub で起きた。`get_pull_request_reviews` のような
**実在しない名前が8個**並び、サーバが出しているのは `pull_request_read` ひとつ
だった。役に残ったのは `list_pull_requests` だけで、当人は「この環境では
レビューを取得できない」と正しく観測し、**取れない前提のカードを4時間ぶん
立て続けた。** 誰も嘘をついていないのに、誰も直せない。

**綴りは事実なので、事実と突き合わせる。** サーバに `tools/list` を投げて、
include の各名前が返答にあるかを見るだけでよい。

対象は url を持つ MCP（HTTP）だけ。stdio のサーバは起動しないと一覧が取れず、
doctor が npx を走らせることになるので見送る。

終了コード: 実在しない名前があれば 1。
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

VAR = re.compile(r"\$\{([A-Z0-9_]+)\}")
TIMEOUT = 20


def env_of(profile_dir: Path) -> dict[str, str]:
    """その役の .env。**値はここにしか無い**（配布物には入らない）。"""
    out: dict[str, str] = {}
    f = profile_dir / ".env"
    if not f.exists():
        return out
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def expand(text: str, env: dict[str, str]) -> str | None:
    """`${VAR}` を埋める。**埋まらなければ照合しない**（値が無いだけで、
    名前が違うわけではない。doctor の別の節が鍵の不足を見ている）。"""
    missing = False

    def sub(m):
        nonlocal missing
        v = env.get(m.group(1)) or os.environ.get(m.group(1))
        if not v:
            missing = True
            return ""
        return v

    got = VAR.sub(sub, text)
    return None if missing else got


def tools_of(url: str, headers: dict[str, str]) -> set[str] | None:
    """サーバが出している道具の名前。応答は SSE のこともある。"""
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    ).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        return None
    i = raw.find('{"jsonrpc"')
    if i < 0:
        i = raw.find("{")
    if i < 0:
        return None
    try:
        d = json.loads(raw[i:])
        return {t["name"] for t in d["result"]["tools"]}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def main() -> int:
    root = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes") / "profiles"
    if not root.is_dir():
        return 0
    fail = 0
    for prof in sorted(p for p in root.iterdir() if p.is_dir()):
        cfg = prof / "config.yaml"
        if not cfg.exists():
            continue
        try:
            servers = (yaml.safe_load(cfg.read_text()) or {}).get("mcp_servers") or {}
        except yaml.YAMLError:
            continue
        env = env_of(prof)
        for name, spec in servers.items():
            if not isinstance(spec, dict) or not spec.get("url"):
                continue
            include = ((spec.get("tools") or {}).get("include")) or []
            if not include:
                continue
            url = expand(spec["url"], env)
            headers = {}
            ok = url is not None
            for hk, hv in (spec.get("headers") or {}).items():
                got = expand(str(hv), env)
                if got is None:
                    ok = False
                else:
                    headers[hk] = got
            if not ok:
                print(f"= {prof.name}/{name}: 鍵が未設定なので照合しない")
                continue
            actual = tools_of(url, headers)
            if actual is None:
                print(f"? {prof.name}/{name}: 道具の一覧を取れなかった（疎通か認証）")
                continue
            ghost = [t for t in include if t not in actual]
            if not ghost:
                print(f"✓ {prof.name}/{name}: {len(include)} 個すべて実在する")
                continue
            print(f"✗ {prof.name}/{name}: 実在しない名前が {len(ghost)} 個ある"
                  "（黙って落ちるので、その役はその手を持っていない）")
            for t in ghost:
                print(f"    {t}")
            print(f"  サーバが出している {len(actual)} 個: "
                  f"{', '.join(sorted(actual))}")
            fail = 1
    return fail


if __name__ == "__main__":
    sys.exit(main())
