#!/usr/bin/env python3
"""役ごとの前提（設定画面で書くもの）が、宣言した役の environment_hint にだけ載るかの回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/role_context_test.py

一時ディレクトリを `HERMES_HOME` に見立てる。**本番の ~/.hermes には触らない。**
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import yaml

HOME = Path(tempfile.mkdtemp(prefix="role-context-test-"))
os.environ["HERMES_HOME"] = str(HOME)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import envhint  # noqa: E402
import roles  # noqa: E402
import worker as worker_mod  # noqa: E402

from _harness import finish, run_tests  # noqa: E402


def reset() -> None:
    for name in roles.all_names():
        d = HOME / "profiles" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.yaml").write_text("agent: {}\n", encoding="utf-8")
        envhint.role_context_file(name).unlink(missing_ok=True)


def hint_of(name: str) -> str:
    body = yaml.safe_load((HOME / "profiles" / name / "config.yaml").read_text(encoding="utf-8"))
    return body["agent"].get("environment_hint") or ""


def two_roles() -> tuple:
    """1つ目だけが前提を受け付ける（profile.yaml に context を宣言した）ことにする。"""
    names = roles.names()
    assert len(names) >= 2, names
    a, b = names[0], names[1]
    roles.context_prompt = lambda n: "探索してよいディレクトリ" if n == a else ""
    return a, b


def test_context_reaches_only_its_role():
    """書いた役にだけ載り、他の役には載らない"""
    reset()
    a, b = two_roles()
    envhint.set_role_context(a, "探索は ~/Projects/foo の下だけ")
    assert "~/Projects/foo" in hint_of(a), hint_of(a)
    assert "~/Projects/foo" not in hint_of(b), hint_of(b)
    # 実測の部分は両方に残る
    assert "この作業環境について" in hint_of(a)
    assert "この作業環境について" in hint_of(b)


def test_clearing_removes_it():
    """空で保存すると、前提が config.yaml から消える"""
    reset()
    a, _ = two_roles()
    envhint.set_role_context(a, "探索は ~/Projects/foo の下だけ")
    envhint.set_role_context(a, "   ")
    assert "~/Projects/foo" not in hint_of(a), hint_of(a)
    assert not envhint.role_context_file(a).exists()


def test_survives_reapply():
    """反映（apply）をやり直しても前提は残る"""
    reset()
    a, _ = two_roles()
    envhint.set_role_context(a, "探索は ~/Projects/foo の下だけ")
    (HOME / "profiles" / a / "config.yaml").write_text("agent: {}\n", encoding="utf-8")
    envhint.apply()
    assert "~/Projects/foo" in hint_of(a), hint_of(a)


def test_undeclared_role_is_rejected():
    """context を宣言していない役は、保存を断り、置いてあるファイルも渡さない"""
    reset()
    _, b = two_roles()
    try:
        envhint.set_role_context(b, "探索は ~/Projects/foo の下だけ")
    except ValueError:
        pass
    else:
        raise AssertionError("宣言していない役に前提が保存できた")
    path = envhint.role_context_file(b)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("探索は ~/Projects/foo の下だけ\n", encoding="utf-8")
    envhint.apply()
    assert "~/Projects/foo" not in hint_of(b), hint_of(b)


def test_worker_set_context_writes_profile():
    """worker set --context が profile.yaml に書き、空で外せる（: を含んでも壊れない）"""
    prof = HOME / "profile.yaml"
    prof.write_text("name: x\nsummary: \"\"\n", encoding="utf-8")
    worker_mod._set_context(prof, "対象: 探索してよいディレクトリ")
    assert yaml.safe_load(prof.read_text(encoding="utf-8"))["context"] == "対象: 探索してよいディレクトリ"
    worker_mod._set_context(prof, "別の説明")
    assert yaml.safe_load(prof.read_text(encoding="utf-8"))["context"] == "別の説明"
    worker_mod._set_context(prof, "")
    assert "context" not in yaml.safe_load(prof.read_text(encoding="utf-8"))


def test_template_declares_nothing():
    """雛形の context は空（作っただけの役に欄は出ない）"""
    tmpl = yaml.safe_load((ROOT / "templates/workers/_template/profile.yaml").read_text(encoding="utf-8"))
    assert tmpl.get("context") == "", tmpl.get("context")


def test_too_long_is_rejected():
    """長すぎる前提は保存しない"""
    reset()
    a, _ = two_roles()
    try:
        envhint.set_role_context(a, "あ" * (envhint.CONTEXT_MAX_CHARS + 1))
    except ValueError:
        pass
    else:
        raise AssertionError("長すぎる前提が通った")
    assert not envhint.role_context_file(a).exists()


run_tests(globals())
finish()
