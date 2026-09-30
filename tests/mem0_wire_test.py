#!/usr/bin/env python3
"""共有記憶（mem0）の接続情報が、Hermes の読む形で書かれることの回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/mem0_wire_test.py

2026-09-30、キットは接続先を `base_url` だけで書いていたが、Hermes の mem0 プラグインは
`host` を読む。`host` が無いとクラウド（app.mem0.ai）へ繋ぎに行き、手元の鍵が合わずに
「Invalid API key」で初期化に失敗して、全役の記憶が1件も書けていなかった。

一時ディレクトリを `HERMES_HOME` に見立てる。**Hermes も mem0 サーバーも使わない。**
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="mem0-wire-test-"))
os.environ["HERMES_HOME"] = str(HOME)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import mem0  # noqa: E402
from paths import profile_dir  # noqa: E402

from _harness import finish, run_tests  # noqa: E402

HERMES_MEM0 = Path.home() / ".hermes/hermes-agent/plugins/memory/mem0/__init__.py"


def test_wire_writes_host():
    """接続先を `host` で書く（Hermes はこれがあれば手元のサーバーへ繋ぐ）。"""
    profile_dir("operator").mkdir(parents=True, exist_ok=True)
    assert mem0.wire_one("operator", "8888", "k")
    cfg = json.loads((profile_dir("operator") / "mem0.json").read_text(encoding="utf-8"))
    assert cfg["host"] == "http://localhost:8888", cfg
    assert cfg["api_key"] == "k" and cfg["user_id"] == mem0.USER_ID, cfg


def test_hermes_still_reads_host():
    """Hermes の mem0 プラグインが、いまも `host` で手元のサーバーを選ぶこと（読み方が変われば気づく）。"""
    if not HERMES_MEM0.is_file():
        print("      （この PC に Hermes が無いので飛ばす）")
        return
    src = HERMES_MEM0.read_text(encoding="utf-8")
    assert "SelfHostedBackend(self._api_key, self._host) if self._host" in src, \
        "Hermes の mem0 プラグインの、手元のサーバーの選び方が変わった。core/mem0.py の wire_one を見直すこと"


run_tests(dict(globals()))
finish()
