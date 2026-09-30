#!/usr/bin/env python3
"""default ホームへの配布（core/default_home.py）の回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/default_home_test.py

一時ディレクトリを `HERMES_HOME` に見立てる。**本番の ~/.hermes には触らない。**
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="default-home-test-"))
os.environ["HERMES_HOME"] = str(HOME)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import yaml  # noqa: E402

import default_home  # noqa: E402
import env as env_mod  # noqa: E402
import roles  # noqa: E402

from _harness import finish, run_tests  # noqa: E402


def reset() -> None:
    env_mod.env_file().unlink(missing_ok=True)
    (HOME / ".env").unlink(missing_ok=True)
    (HOME / "config.yaml").unlink(missing_ok=True)


def default_env() -> dict:
    return env_mod.read_env(HOME / ".env")


def default_cfg() -> dict:
    path = HOME / "config.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}


def test_model_key_is_distributed():
    """正にあるモデルの鍵は、default ホームの .env にも配られる。"""
    reset()
    gen = roles.generator()
    env_mod.set_value(gen.MODEL_KEY, "sk-test")
    default_home.sync()
    assert default_env()[gen.MODEL_KEY] == "sk-test"


def test_existing_default_env_is_not_clobbered():
    """正に無い値は、default 側に既にある値を潰さない。"""
    reset()
    (HOME / ".env").write_text("OPENROUTER_API_KEY=sk-desktop\n", encoding="utf-8")
    default_home.sync()
    assert default_env()["OPENROUTER_API_KEY"] == "sk-desktop"


def test_master_value_wins_over_default():
    """正に値があれば、default 側の古い値は正で更新される。"""
    reset()
    gen = roles.generator()
    (HOME / ".env").write_text(f"{gen.MODEL_KEY}=sk-old\n", encoding="utf-8")
    env_mod.set_value(gen.MODEL_KEY, "sk-new")
    default_home.sync()
    assert default_env()[gen.MODEL_KEY] == "sk-new"


def test_config_gets_decomposer_settings():
    """default の config.yaml に、分解の設定と親の持ち主が書かれる。"""
    reset()
    gen = roles.generator()
    default_home.sync()
    cfg = default_cfg()
    dec = cfg["auxiliary"]["kanban_decomposer"]
    assert dec["model"] == gen.SMART
    assert dec["provider"] == gen.PROVIDER
    assert cfg["kanban"]["orchestrator_profile"] == "fixer"


def test_other_sections_are_preserved():
    """model 節など、キットの管理外の節はそのまま残る。"""
    reset()
    (HOME / "config.yaml").write_text(
        "model:\n  default: some-model\nauxiliary:\n  vision:\n    provider: auto\n",
        encoding="utf-8",
    )
    default_home.sync()
    cfg = default_cfg()
    assert cfg["model"]["default"] == "some-model"
    assert cfg["auxiliary"]["vision"]["provider"] == "auto"
    assert cfg["auxiliary"]["kanban_decomposer"]["model"]


def test_idempotent():
    """2回目は何も変わらない（毎回の反映でファイルを書き換えない）。"""
    reset()
    default_home.sync()
    first = (HOME / "config.yaml").read_text(encoding="utf-8")
    report = default_home.sync()
    assert (HOME / "config.yaml").read_text(encoding="utf-8") == first
    assert report == ["default ホームの自動分解の設定は最新です"]


def test_bedrock_writes_region_and_disables_discovery():
    """Bedrock のときは、入口のリージョンと discovery 停止も揃える。"""
    reset()
    os.environ["MODEL_PROVIDER"] = "bedrock"
    try:
        default_home.sync()
        cfg = default_cfg()
        assert cfg["bedrock"]["region"]
        assert cfg["bedrock"]["discovery"]["enabled"] is False
        assert cfg["auxiliary"]["kanban_decomposer"]["provider"] == "bedrock"
    finally:
        os.environ.pop("MODEL_PROVIDER")


if __name__ == "__main__":
    run_tests(globals())
    finish()
