#!/usr/bin/env python3
"""役ごとにモデルの鍵を差し替える仕組みの回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/env_override_test.py

一時ディレクトリを `HERMES_HOME` に見立てる。**本番の ~/.hermes には触らない。**
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="env-override-test-"))
os.environ["HERMES_HOME"] = str(HOME)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "dashboard"))

import env as env_mod  # noqa: E402
import roles  # noqa: E402

from _harness import finish, run_tests  # noqa: E402


KEY = "OPENROUTER_API_KEY"


def reset() -> None:
    env_mod.env_file().unlink(missing_ok=True)
    for name in roles.all_names():
        d = HOME / "profiles" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / ".env").unlink(missing_ok=True)


def profile_env(name: str) -> dict:
    return env_mod.read_env(HOME / "profiles" / name / ".env")


def test_every_role_can_override_model_key():
    for name in roles.all_names():
        assert KEY in roles.override_env_vars(name), name
        assert roles.env_key(name, KEY) in roles.managed_env_vars(), name


def test_falls_back_to_shared():
    """役つきが無ければ共通の値を使う。"""
    reset()
    env_mod.set_value(KEY, "sk-shared")
    env_mod.apply()
    assert profile_env("developer")[KEY] == "sk-shared"


def test_override_wins_only_for_that_role():
    reset()
    env_mod.set_value(KEY, "sk-shared")
    env_mod.set_value(roles.env_key("developer", KEY), "sk-dev")
    env_mod.apply()
    assert profile_env("developer")[KEY] == "sk-dev"
    assert profile_env("fixer")[KEY] == "sk-shared"


def test_clearing_override_returns_to_shared():
    reset()
    env_mod.set_value(KEY, "sk-shared")
    env_mod.set_value(roles.env_key("developer", KEY), "sk-dev")
    env_mod.apply()
    env_mod.drop_value(roles.env_key("developer", KEY))
    env_mod.apply()
    assert profile_env("developer")[KEY] == "sk-shared"


def test_override_does_not_leak_into_own_slack_keys():
    """専用の鍵（Slack）は、これまでどおり共通へ落ちない。"""
    reset()
    env_mod.set_value("SLACK_BOT_TOKEN", "xoxb-shared")
    env_mod.apply()
    assert "SLACK_BOT_TOKEN" not in profile_env("fixer")
    # 共通の名前は operator の専用へ一度だけ移される（既存の移行）
    assert profile_env("operator").get("SLACK_BOT_TOKEN") == "xoxb-shared"


def test_api_clears_only_overrides():
    import plugin_api as api
    from fastapi import HTTPException

    reset()
    env_mod.set_value(KEY, "sk-shared")
    env_mod.set_value(roles.env_key("developer", KEY), "sk-dev")
    api.set_secret(api.SecretIn(name=roles.env_key("developer", KEY), value=""))
    assert not env_mod.read_env(env_mod.env_file()).get(roles.env_key("developer", KEY))
    try:
        api.set_secret(api.SecretIn(name=KEY, value=""))
    except HTTPException:
        pass
    else:
        raise AssertionError("共通のモデルの鍵を空にできてしまった")


def test_api_shows_only_plain_values():
    """設定画面へ値を返すのは、秘密ではない項目（ID やドメイン）だけ。鍵は有無だけ。"""
    import plugin_api as api

    reset()
    env_mod.set_value(roles.env_key("operator", "SLACK_ALLOWED_USERS"), "U0AAA,U0BBB")
    env_mod.set_value(roles.env_key("operator", "SLACK_BOT_TOKEN"), "xoxb-hidden")
    env_mod.set_value(KEY, "sk-hidden")

    operator = next(r for r in api.list_roles() if r["name"] == "operator")
    own = {s["label"]: s for s in operator["ownSecrets"]}
    assert own["SLACK_ALLOWED_USERS"].get("plain") is True
    assert own["SLACK_ALLOWED_USERS"].get("value") == "U0AAA,U0BBB"
    assert "value" not in own["SLACK_BOT_TOKEN"] and not own["SLACK_BOT_TOKEN"].get("plain")

    shared = {s["name"]: s for s in api.list_secrets()}
    assert "value" not in shared[KEY]
    everything = repr(api.list_roles()) + repr(api.list_secrets())
    assert "xoxb-hidden" not in everything and "sk-hidden" not in everything, "鍵の値を画面へ返している"


def test_deleted_profile_is_not_shown_as_residual():
    """削除済みの印が残っている役は、画面でも「残置」と出さない。"""
    import plugin_api as api

    reset()
    d = HOME / "profiles" / "recruiter"
    d.mkdir(parents=True, exist_ok=True)
    assert next(r for r in api.list_roles() if r["name"] == "recruiter")["installed"]

    marker = HOME / "profiles" / ".deleted" / "recruiter"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("", encoding="utf-8")
    try:
        row = next(r for r in api.list_roles() if r["name"] == "recruiter")
        assert not row["installed"], "本体からは見えない役を、画面が残置と出している"
    finally:
        marker.unlink()


def test_owner_can_always_talk():
    """オーナーは、話しかけてよい人に入れ忘れても、operator に配る一覧へ足される。"""
    reset()
    allowed = roles.env_key("operator", "SLACK_ALLOWED_USERS")
    owner = roles.env_key("operator", "SLACK_OWNER_ID")

    env_mod.set_value(allowed, "U0AAA,U0BBB")
    env_mod.set_value(owner, "U0OWNER")
    env_mod.apply()
    assert profile_env("operator").get("SLACK_ALLOWED_USERS") == "U0AAA,U0BBB,U0OWNER"

    # すでに入っていれば二重にしない
    env_mod.set_value(allowed, "U0OWNER,U0AAA")
    env_mod.apply()
    assert profile_env("operator").get("SLACK_ALLOWED_USERS") == "U0OWNER,U0AAA"

    # 一覧が空でも、オーナーだけは話せる
    env_mod.drop_value(allowed)
    env_mod.apply()
    assert profile_env("operator").get("SLACK_ALLOWED_USERS") == "U0OWNER"


def test_shared_not_required_when_all_overridden():
    import plugin_api as api

    reset()
    assert KEY in api.validate()["blocking"]
    for name in roles.names():
        env_mod.set_value(roles.env_key(name, KEY), f"sk-{name}")
    assert KEY not in api.validate()["blocking"], api.validate()


def test_doctor_finds_stolen_slack_bot():
    """キットの外（default の .env）が窓口と同じ Slack トークンを持っていたら、doctor が言う。"""
    import doctor

    reset()
    (HOME / "profiles" / "operator" / ".env").write_text("SLACK_BOT_TOKEN=xoxb-same\n", encoding="utf-8")
    (HOME / ".env").write_text("SLACK_BOT_TOKEN=xoxb-same\n", encoding="utf-8")
    rep = doctor.Report()
    doctor._slack_token_holders(rep)
    assert rep.failures == 1, rep.lines
    assert "xoxb-same" not in "\n".join(rep.lines), "値を出してしまった"
    (HOME / ".env").unlink()
    rep = doctor.Report()
    doctor._slack_token_holders(rep)
    assert rep.failures == 0, rep.lines


def test_doctor_finds_missing_slack_scope():
    """窓口の Slack App に files:write が無ければ、doctor が欠けた権限と起きることを言う。"""
    import doctor

    reset()
    (HOME / "profiles" / "operator" / ".env").write_text("SLACK_BOT_TOKEN=xoxb-scope\n", encoding="utf-8")
    real = doctor._slack_granted_scopes
    try:
        doctor._slack_granted_scopes = lambda _t: set(doctor.SLACK_SCOPES) - {"files:write"}
        rep = doctor.Report()
        doctor._slack_scopes(rep)
        assert rep.failures == 1, rep.lines
        assert any("files:write" in line and "返せない" in line for line in rep.lines), rep.lines
        assert "xoxb-scope" not in "\n".join(rep.lines), "値を出してしまった"

        doctor._slack_granted_scopes = lambda _t: set(doctor.SLACK_SCOPES)
        rep = doctor.Report()
        doctor._slack_scopes(rep)
        assert rep.failures == 0, rep.lines

        # 確かめられないときは失敗にしない（オフラインで doctor が赤くならない）
        doctor._slack_granted_scopes = lambda _t: None
        rep = doctor.Report()
        doctor._slack_scopes(rep)
        assert rep.failures == 0, rep.lines
    finally:
        doctor._slack_granted_scopes = real


if __name__ == "__main__":
    run_tests(globals())
    finish()
