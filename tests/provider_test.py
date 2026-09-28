#!/usr/bin/env python3
"""モデルの取り寄せ先（OpenRouter / Bedrock）の切り替えの回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/provider_test.py

一時ディレクトリを `HERMES_HOME` に見立てる。**本番の ~/.hermes には触らない。**
mem0 の消去は Docker を触るので、呼ばれたかどうかだけを見る。
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

import yaml

HOME = Path(tempfile.mkdtemp(prefix="provider-test-"))
os.environ["HERMES_HOME"] = str(HOME)
os.environ.pop("MODEL_PROVIDER", None)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import env as env_mod  # noqa: E402
import kit  # noqa: E402
import mem0  # noqa: E402
import provider as provider_mod  # noqa: E402
import roles  # noqa: E402

from _harness import finish, run_tests  # noqa: E402

WIPED: list = []
mem0.wipe = lambda log=None: WIPED.append(True) or True


def set_provider(name: str) -> None:
    env_mod.set_value("MODEL_PROVIDER", name)
    # 更新時刻の粒度で読み直しを取りこぼさないよう、読み直しを強いる
    roles._cache.clear()


def built_config(role: str) -> dict:
    out = Path(tempfile.mkdtemp(prefix="provider-dist-"))
    with contextlib.redirect_stdout(io.StringIO()):
        roles.generator().build(ROOT, out, {role})
    return yaml.safe_load((out / role / "config.yaml").read_text(encoding="utf-8"))


def required_keys(role: str) -> set:
    return {var for var, req, _ in roles.env_requirements(role) if req}


def test_default_is_openrouter():
    """何も選んでいなければ OpenRouter のまま（今までと同じ config）"""
    env_mod.env_file().unlink(missing_ok=True)
    roles._cache.clear()
    assert provider_mod.current() == "openrouter"
    cfg = built_config("fixer")
    assert "provider" not in cfg["model"], cfg["model"]
    assert cfg["model"]["default"] == "openai/gpt-6-astra", cfg["model"]
    assert required_keys("fixer") == {"OPENROUTER_API_KEY"}


def test_bedrock_config():
    """Bedrock では us-east-1 の Converse へ繋ぎ、段は global. のモデル（smart は gpt-6-sol）"""
    set_provider("bedrock")
    cfg = built_config("fixer")
    assert cfg["model"] == {"default": "global.openai.gpt-6-sol", "provider": "bedrock"}, cfg["model"]
    assert cfg["bedrock"]["region"] == "us-east-1", cfg["bedrock"]
    assert "providers" not in cfg, cfg.get("providers")
    assert cfg["auxiliary"]["kanban_decomposer"]["provider"] == "main"
    assert built_config("operator")["model"]["default"] == "global.openai.gpt-5.6-luna"
    assert built_config("senior-developer")["model"]["default"] == "global.anthropic.claude-opus-5-5"


def test_bedrock_key_is_required():
    """Bedrock では Bedrock の鍵が必須になり、OpenRouter の鍵は要らない"""
    set_provider("bedrock")
    assert required_keys("fixer") == {"AWS_BEARER_TOKEN_BEDROCK"}
    # 選んでいない側の鍵も管理下（各役から掃除できる）
    assert "OPENROUTER_API_KEY" in roles.managed_env_vars()


def test_workspace_gets_bedrock_key():
    """作業部屋へは Bedrock の鍵を渡し、opencode も Bedrock を向く"""
    set_provider("bedrock")
    out = Path(tempfile.mkdtemp(prefix="provider-dist-"))
    with contextlib.redirect_stdout(io.StringIO()):
        roles.generator().build(ROOT, out, {"developer"})
    text = (out / "developer" / "config.yaml").read_text(encoding="utf-8")
    assert "AWS_BEARER_TOKEN_BEDROCK" in text
    assert "OPENROUTER_API_KEY" not in text
    assert "amazon-bedrock/global.openai.gpt-5.6-luna" in text


def test_switch_needs_confirm():
    """確認が無ければ切り替えず、記憶も消さない"""
    set_provider("openrouter")
    WIPED.clear()
    try:
        provider_mod.switch("bedrock")
    except provider_mod.ProviderError:
        pass
    else:
        raise AssertionError("確認なしで切り替わった")
    assert provider_mod.current() == "openrouter"
    assert not WIPED


def test_switch_wipes_memory():
    """確認つきで切り替えると、.env が変わり、記憶を消す"""
    set_provider("openrouter")
    WIPED.clear()
    res = provider_mod.switch("bedrock", confirm=True)
    roles._cache.clear()
    assert provider_mod.current() == "bedrock"
    assert WIPED == [True]
    assert any("AWS_BEARER_TOKEN_BEDROCK" in line for line in res.lines), res.lines


def test_same_provider_is_noop():
    """同じ取り寄せ先を選んでも何もしない（記憶は消さない）"""
    set_provider("bedrock")
    WIPED.clear()
    provider_mod.switch("bedrock", confirm=True)
    assert not WIPED


def test_mem0_settings_follow_provider():
    """mem0 の取り寄せ先も切り替わる（OpenRouter では既定のまま）"""
    set_provider("openrouter")
    env_mod.set_value("OPENROUTER_API_KEY", "sk-or")
    s = mem0.settings()
    assert s["MEM0_LLM_API_KEY"] == "sk-or" and s["MEM0_EMBEDDER_PROVIDER"] == "", s
    set_provider("bedrock")
    env_mod.set_value("AWS_BEARER_TOKEN_BEDROCK", "bedrock-key")
    s = mem0.settings()
    assert s["MEM0_LLM_API_KEY"] == "bedrock-key", s
    assert s["MEM0_LLM_BASE_URL"] == "https://bedrock-mantle.us-east-1.api.aws/openai/v1", s
    assert s["MEM0_LLM_MODEL"] == "openai.gpt-5.6-luna", s
    assert s["MEM0_EMBEDDER_PROVIDER"] == "aws_bedrock" and s["MEM0_EMBEDDING_DIMS"] == "1024", s


def test_mem0_env_keeps_secrets():
    """取り寄せ先を書き換えても、mem0 の秘密（DB のパスワード）は残る"""
    path = HOME / "mem0" / ".env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("MEM0_PG_PASSWORD=keep\nMEM0_LLM_API_KEY=old\n", encoding="utf-8")
    set_provider("bedrock")
    assert mem0._write_settings(path, mem0.settings())
    values = mem0._read_env(path)
    assert values["MEM0_PG_PASSWORD"] == "keep", values
    assert values["MEM0_LLM_API_KEY"] == "bedrock-key", values
    assert not mem0._write_settings(path, mem0.settings()), "同じなら書き直さない"


def test_model_change_forces_config():
    """配るモデルが入っているものと違えば、config.yaml ごと入れ替える"""
    dist = HOME / "dist" / "fixer"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "config.yaml").write_text("model: {default: global.openai.gpt-6-sol, provider: bedrock}\n")
    pdir = HOME / "profiles" / "fixer"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "config.yaml").write_text("model: {default: openai/gpt-6-astra}\nagent: {environment_hint: x}\n")
    assert kit._model_differs(dist, "fixer")
    (pdir / "config.yaml").write_text(
        "model: {default: global.openai.gpt-6-sol, provider: bedrock}\nagent: {environment_hint: x}\n")
    assert not kit._model_differs(dist, "fixer"), "モデル以外の差では入れ替えない"


run_tests(globals())
finish()
