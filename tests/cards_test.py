#!/usr/bin/env python3
"""カードの保留（seaos-kit card）の回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/cards_test.py

保留のカードは、作るが誰にも回さない。分解（triage）にも担当にも回ったら、オーナーが
決める前に作業が始まってしまう。**Hermes は呼ばない**（hermes.run を偽物に差し替える）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="cards-test-"))
os.environ["HERMES_HOME"] = str(HOME)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import cards  # noqa: E402
import hermes  # noqa: E402

from _harness import finish, run_tests  # noqa: E402

CALLS: list = []
BOARD: dict = {}


def fake_run(args, **kw):
    CALLS.append(list(args))
    if args[:2] == ["kanban", "create"]:
        task_id = f"t_{len(BOARD) + 1:04d}"
        opts = dict(zip(args[3::2], args[4::2]))
        BOARD[task_id] = {"id": task_id, "title": args[2], "body": opts.get("--body"),
                          "created_by": opts.get("--created-by"),
                          "status": "triage" if "--triage" in args else opts.get("--initial-status", "ready")}
        return 0, "warning: something\n" + json.dumps(BOARD[task_id])
    if args[:2] == ["kanban", "show"]:
        return 0, json.dumps({"task": BOARD[args[2]]})
    if args[:2] == ["kanban", "archive"]:
        BOARD[args[2]]["status"] = "archived"
        return 0, ""
    return 1, "unexpected"


hermes.run = fake_run


def reset():
    CALLS.clear()
    BOARD.clear()
    cards.held_file().unlink(missing_ok=True)


def test_hold_parks_without_anyone():
    """保留は、担当なし・止めた状態で作る。分解にも回さない。依頼者を残す。"""
    reset()
    task = cards.hold("見積もり", "来週までに見積もりがほしい", "U0COLLEAGUE")
    create = CALLS[0]
    assert "--triage" not in create and "--assignee" not in create, create
    assert create[create.index("--initial-status") + 1] == "blocked", create
    assert create[create.index("--created-by") + 1] == "U0COLLEAGUE", create
    assert BOARD[task["id"]]["status"] == "blocked"
    assert "<@U0COLLEAGUE>" in BOARD[task["id"]]["body"]
    assert [c["id"] for c in cards.held()] == [task["id"]]


def test_hold_needs_requester():
    """依頼者が分からない保留は作らない（戻ったとき、誰の用件か分からなくなる）。"""
    reset()
    try:
        cards.hold("見積もり", "本文", "")
    except cards.CardError:
        pass
    else:
        raise AssertionError("依頼者なしで保留を作った")
    assert not CALLS


def test_resume_sends_to_triage_and_closes_the_hold():
    """保留を解くと、同じ中身で分解に回し、保留のカードは畳む。依頼者はそのまま。"""
    reset()
    held = cards.hold("見積もり", "来週までに", "U0COLLEAGUE")["id"]
    new_id = cards.resume(held)
    assert BOARD[new_id]["status"] == "triage", BOARD[new_id]
    assert BOARD[new_id]["created_by"] == "U0COLLEAGUE"
    assert "来週までに" in BOARD[new_id]["body"] and "保留）" not in BOARD[new_id]["body"].split("\n")[0]
    assert BOARD[held]["status"] == "archived"
    assert cards.held() == []


def test_drop_closes_without_work():
    """要らない保留は、分解に回さずに畳む。"""
    reset()
    held = cards.hold("見積もり", "来週までに", "U0COLLEAGUE")["id"]
    cards.drop(held)
    assert BOARD[held]["status"] == "archived"
    assert not any("--triage" in c for c in CALLS)
    assert cards.held() == []


def test_only_held_cards_can_be_resumed():
    """保留にしていないカードを、保留の口から動かさない。"""
    reset()
    for fn in (cards.resume, cards.drop):
        try:
            fn("t_9999")
        except cards.CardError:
            continue
        raise AssertionError(f"{fn.__name__} が保留でないカードを動かした")


def test_plugin_reads_the_same_record():
    """不在対応のプラグインは、保留の記録を同じ場所から読む（戻ったときの一覧に使う）。"""
    src = (ROOT / "templates/plugins/owner-away/__init__.py").read_text(encoding="utf-8")
    assert '"seaos-kit" / "held.json"' in src
    assert cards.held_file() == HOME / "seaos-kit" / "held.json"


run_tests(dict(globals()))
finish()
