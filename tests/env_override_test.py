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


if __name__ == "__main__":
    run_tests(globals())
    finish()
