#!/usr/bin/env python3
"""アクセスゲート（booking-gate）の回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/booking_gate_test.py

一時ディレクトリを `HERMES_HOME` に見立てる。**本番の ~/.hermes には触らない。**
Slack への問い合わせは差し替える（ネットワークにも鍵にも触らない）。

守りたいのは、チャンネルの許可について:
  * そのチャンネルの正式なメンバーだけが、1人ずつの枠に展開される
    （ボット・Slack のゲストアカウント・社外の人は入らない）
  * 展開された枠は、**そのチャンネルでの発言にだけ**効く（DM や他のチャンネルでは通さない）
  * メンバーを取れないときは、少しのあいだ前回の一覧を使い、古ければ許可を出さない
  * 人の名前をチャンネル ID と取り違えない
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

HOME = Path(tempfile.mkdtemp(prefix="booking-gate-test-"))
os.environ["HERMES_HOME"] = str(HOME)
os.environ.pop("BOOKING_GATE_HOME", None)

ROOT = Path(__file__).resolve().parent.parent
SYNC_DIR = ROOT / "templates/booking-gate/sync"
sys.path.insert(0, str(SYNC_DIR))

import booking_sync as bs  # noqa: E402
import booking_guest as guest  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "booking_gate_plugin", ROOT / "templates/booking-gate/plugin/__init__.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

from _harness import finish, run_tests  # noqa: E402

CHANNEL = "C0C1L6ESPR8"
OTHER = "C0OTHER1234"
MEMBER = "U0MEMBER01"
SLACK_GUEST = "U0GUEST001"    # Slack のゲストアカウント
BOT = "U0BOT00001"
OUTSIDER = "U0OUTSIDE1"      # 共有チャンネル越しの社外の人（users.list に出ない）

DIRECTORY = [
    {"id": MEMBER, "name": "member"},
    {"id": SLACK_GUEST, "name": "guest", "is_restricted": True},
    {"id": BOT, "name": "bot", "is_bot": True},
]


def now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def reset(members=(MEMBER, SLACK_GUEST, BOT, OUTSIDER)) -> None:
    for path in (bs.GUESTS_PATH, bs.IDENTITY_CACHE_PATH, bs.RESERVATIONS_PATH):
        path.unlink(missing_ok=True)
    op = HOME / "profiles/operator"
    op.mkdir(parents=True, exist_ok=True)
    (op / ".env").write_text("SLACK_BOT_TOKEN=xoxb-test\n", encoding="utf-8")

    def fetch_directory(token, cache):
        people = [u["id"] for u in DIRECTORY
                  if not (u.get("is_bot") or u.get("is_restricted") or u.get("is_ultra_restricted"))]
        cache["_directory"] = {"names": {u["name"]: u["id"] for u in DIRECTORY},
                               "people": people, "at": time.time()}
        return cache["_directory"]["names"], people

    bs._fetch_directory = fetch_directory
    bs.slack_channel_members = lambda token, channel_id: list(members) if members is not None else None


def grant_channel(**extra) -> None:
    grant = {"slack_channel_id": CHANNEL, "channel_name": "faq", "email": "", "label": "",
             "start": now().isoformat(), "end": None, "task_id": "",
             "unlimited": True, "requested_by": "owner", **extra}
    bs.write_atomic(bs.GUESTS_PATH, json.dumps({"grants": [grant]}))


def table() -> dict:
    cfg = bs.load_config()
    t = bs.build_table(cfg, now())
    t["active"] = sorted(bs.active_user_ids(t, cfg, now()))
    return t


def test_channel_grant_expands_to_full_members_only():
    """ボット・Slack のゲスト・社外の人は枠に入らない。"""
    reset()
    grant_channel()
    t = table()
    users = {s["slack_user_id"] for s in t["slots"]}
    assert users == {MEMBER}, users
    assert all(s["channel_id"] == CHANNEL for s in t["slots"])
    assert MEMBER in t["active"]


def test_channel_slot_only_counts_in_that_channel():
    """チャンネルの許可から来た枠は、そのチャンネル（とそのスレッド）での発言だけを通す。"""
    reset()
    grant_channel()
    t = table()
    cfg = bs.load_config()
    assert gate._find_slot(t, cfg, MEMBER, now(), {CHANNEL})
    assert gate._find_slot(t, cfg, MEMBER, now(), {"1789.000", CHANNEL})  # スレッドは親チャンネルで判定
    assert not gate._find_slot(t, cfg, MEMBER, now(), {"D0DMCHANNEL"}), "DM で通してしまった"
    assert not gate._find_slot(t, cfg, MEMBER, now(), {OTHER}), "他のチャンネルで通してしまった"
    assert not gate._find_slot(t, cfg, MEMBER, now(), None)


def test_notice_points_to_the_channel():
    """チャンネルの外で話しかけた人には、どこでなら話せるかを返す。"""
    reset()
    grant_channel()
    text = gate._notice_text(table(), MEMBER, now(), bs.load_config())
    assert f"<#{CHANNEL}>" in text, text


def test_gate_skips_outside_the_channel():
    """ゲート本体で、チャンネルの中は通し、DM は落とす。"""
    reset()
    grant_channel()
    bs.write_atomic(bs.RESERVATIONS_PATH, json.dumps(table()))
    gate._cache.update({"table": None, "table_mtime": 0.0})
    gate._always_allowed = lambda uid: False

    def event(chat_id, chat_type):
        src = SimpleNamespace(platform="slack", user_id=MEMBER, chat_id=chat_id,
                              chat_type=chat_type, parent_chat_id=None)
        return SimpleNamespace(source=src, message_id="1")

    assert gate.gate(event(CHANNEL, "group")) is None
    result = gate.gate(event("D0DMCHANNEL", "dm"))
    assert result and result.get("action") == "skip", result


def test_member_list_failure_uses_recent_then_closes():
    """取れないときは前回の一覧を少しだけ使い、古ければ許可を出さない。"""
    reset()
    grant_channel()
    assert {s["slack_user_id"] for s in table()["slots"]} == {MEMBER}

    bs.slack_channel_members = lambda token, channel_id: None
    assert {s["slack_user_id"] for s in table()["slots"]} == {MEMBER}, "一瞬の失敗で全員を締め出した"

    cache = bs.load_identity_cache()
    cache["_channels"][CHANNEL]["at"] = time.time() - bs.CHANNEL_MEMBERS_TTL_SEC - 1
    bs.write_atomic(bs.IDENTITY_CACHE_PATH, json.dumps(cache))
    assert table()["slots"] == [], "古い一覧のまま許可を出し続けた"


def test_channel_grant_respects_end_and_task():
    """期限の切れたチャンネルの許可は展開しない。"""
    reset()
    grant_channel(end=(now() - timedelta(days=1)).isoformat(), unlimited=False)
    assert table()["slots"] == []


def test_person_grant_still_works_everywhere():
    """人の許可はこれまでどおり場所を問わない。"""
    reset()
    bs.write_atomic(bs.GUESTS_PATH, json.dumps({"grants": [{
        "slack_user_id": MEMBER, "start": now().isoformat(), "end": None,
        "unlimited": True, "requested_by": "owner"}]}))
    t = table()
    cfg = bs.load_config()
    assert gate._find_slot(t, cfg, MEMBER, now(), {"D0DMCHANNEL"})
    assert gate._find_slot(t, cfg, MEMBER, now(), None)


def test_channel_targets_are_not_confused_with_names():
    assert guest.is_channel_target("#faq")
    assert guest.is_channel_target("<#C0C1L6ESPR8|faq>")
    assert guest.is_channel_target("C0C1L6ESPR8")
    for name in ("christina", "Christina", "CHRISTINA", "@田中", "U0C09TA5CSD"):
        assert not guest.is_channel_target(name), name
    assert guest.resolve_channel("<#C0C1L6ESPR8|faq>", {}) == ("C0C1L6ESPR8", "faq")


if __name__ == "__main__":
    run_tests(globals())
    finish()
