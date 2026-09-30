#!/usr/bin/env python3
"""許可表の同期（booking-sync）が、Slack の読み取りが途中で切れても落ちないことの回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/booking_sync_fetch_test.py

Windows の PC で、Slack のユーザー一覧を読む途中で接続が切れ（http.client.IncompleteRead）、
同期そのものが落ちて許可表が書かれず、オーナー以外の全員が止まった。**Slack には繋がない。**
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["HERMES_HOME"] = tempfile.mkdtemp(prefix="booking-sync-fetch-test-")
os.environ.pop("BOOKING_GATE_HOME", None)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "templates/booking-gate/sync"))

import booking_sync as bs  # noqa: E402

from _harness import finish, run_tests  # noqa: E402

bs.time.sleep = lambda _s: None  # 読み直しの待ちを飛ばす


class _Cut:
    """途中で切れる応答。"""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        raise http.client.IncompleteRead(b"x" * 66000, 270000)


class _Ok:
    def __init__(self, body: dict):
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def _with(responses):
    calls = []

    def fake(req, timeout=None):
        calls.append(req.full_url)
        return responses.pop(0) if responses else _Cut()
    saved = bs.urllib.request.urlopen
    bs.urllib.request.urlopen = fake
    return calls, lambda: setattr(bs.urllib.request, "urlopen", saved)


def test_cut_read_does_not_crash():
    """読み取りが途中で切れ続けても、落ちずに「取れなかった」で終わる。"""
    calls, restore = _with([])
    try:
        names, people = bs._fetch_directory("xoxb-test", {})
        members = bs.slack_channel_members("xoxb-test", "C0TEST")
    finally:
        restore()
    assert names == {} and people == [] and members is None
    assert len(calls) == 2 * bs.FETCH_TRIES, f"読み直していない: {len(calls)}"


def test_cut_then_ok_is_retried():
    """1回切れても、読み直して取れれば使う。"""
    ok = _Ok({"ok": True, "members": [{"id": "U0A", "name": "a", "profile": {}}],
              "response_metadata": {"next_cursor": ""}})
    calls, restore = _with([_Cut(), ok])
    try:
        names, people = bs._fetch_directory("xoxb-test", {})
    finally:
        restore()
    assert people == ["U0A"] and names.get("a") == "U0A", (names, people)
    assert len(calls) == 2


run_tests(dict(globals()))
finish()
