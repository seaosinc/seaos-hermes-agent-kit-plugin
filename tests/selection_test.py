#!/usr/bin/env python3
"""役を選んで入れる仕組みの回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/selection_test.py

一時ディレクトリを `HERMES_HOME` に見立てる。**本番の ~/.hermes には触らない。**

守りたいのは3つ:
  * 外した役は、反映・鍵の配布の対象に入らない
  * 外せない役（operator / fixer）は外せない
  * 外している間も、その役の鍵は「知らない鍵」として掃除されない
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="selection-test-"))
os.environ["HERMES_HOME"] = str(HOME)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import env as env_mod  # noqa: E402
import kit  # noqa: E402
import roles  # noqa: E402
import selection  # noqa: E402

from _harness import finish, run_tests  # noqa: E402


def reset() -> None:
    selection.selection_file().unlink(missing_ok=True)


def test_default_enables_everything():
    """何も選んでいなければ全役が入る（既存の環境の振る舞いを変えない）。"""
    reset()
    assert roles.names() == roles.all_names(), roles.names()


def test_disabled_role_is_left_out():
    reset()
    selection.set_enabled("avatar", False)
    assert "avatar" not in roles.names()
    assert "avatar" in roles.all_names()
    # 反映の差分にも出ない（出ると「新規」と言われ続ける）
    assert not any("avatar" in line for line in kit.diff().lines), kit.diff().lines


def test_essential_cannot_be_disabled():
    reset()
    for name in ("operator", "fixer"):
        assert roles.essential(name), name
        try:
            selection.set_enabled(name, False, essential=roles.essential(name))
        except selection.SelectionError:
            pass
        else:
            raise AssertionError(f"{name} を外せてしまった")
    # ファイルを手で書き換えられても、外せない役は残る
    selection.selection_file().write_text('{"disabled": ["fixer"]}', encoding="utf-8")
    assert "fixer" in roles.names()


def test_broken_file_enables_everything():
    """壊れた記録で全役が消えるより、全役が入るほうが戻しやすい。"""
    reset()
    selection.selection_file().parent.mkdir(parents=True, exist_ok=True)
    selection.selection_file().write_text("{", encoding="utf-8")
    assert roles.names() == roles.all_names()


def test_keys_of_disabled_role_stay_managed():
    """外した役の鍵を「知らない鍵」として掃除しない（入れ直したときに消えている）。"""
    reset()
    # AWS の鍵を宣言しているのは developer と senior-developer だけ
    selection.set_enabled("developer", False)
    selection.set_enabled("senior-developer", False)
    assert "AWS_REGION" in roles.managed_env_vars(), roles.managed_env_vars()


def test_env_apply_skips_disabled_profile():
    """外した役のプロファイルが残っていても、鍵を配らない（もう管理していない）。"""
    reset()
    for name in roles.all_names():
        (HOME / "profiles" / name).mkdir(parents=True, exist_ok=True)
    env_mod.set_value("OPENROUTER_API_KEY", "sk-test")
    selection.set_enabled("broker", False)
    env_mod.apply()
    assert not (HOME / "profiles" / "broker" / ".env").exists(), "外した役に鍵が配られた"
    assert "sk-test" in (HOME / "profiles" / "developer" / ".env").read_text(encoding="utf-8")


def test_profile_scoped_home_sees_the_same_selection():
    """定期実行は HERMES_HOME=<HOME>/profiles/<役> で走る。そこからも同じ記録を読む。"""
    reset()
    selection.set_enabled("broker", False)
    os.environ["HERMES_HOME"] = str(HOME / "profiles" / "operator")
    try:
        assert "broker" not in roles.names(), "プロファイルの中から走ると、外した役が戻る"
    finally:
        os.environ["HERMES_HOME"] = str(HOME)


def test_forget_on_removal():
    reset()
    selection.set_enabled("handler", False)
    selection.forget("handler")
    assert "handler" in roles.names()


def test_every_enabled_role_is_wired_to_mem0():
    """有効な全役が mem0 に繋がり、無効にした役からは鍵が外れる。

    規約は全役に `mem0_add` を書かせる。繋ぐのが fixer だけだと、他の役は書いたつもりで
    一度も届かない（実際にそうなっていた）。
    """
    import mem0
    from paths import profile_dir

    reset()
    mem0.mem0_dir().mkdir(parents=True, exist_ok=True)
    mem0.mem0_env().write_text("MEM0_PORT=8888\nMEM0_API_KEY=k-test\n", encoding="utf-8")
    for name in roles.all_names():
        profile_dir(name).mkdir(parents=True, exist_ok=True)
    selection.set_enabled("avatar", False)
    (profile_dir("avatar") / "mem0.json").write_text("{}", encoding="utf-8")

    mem0.rewire()
    for name in roles.names():
        assert (profile_dir(name) / "mem0.json").is_file(), f"{name} が mem0 に繋がっていない"
    assert not (profile_dir("avatar") / "mem0.json").exists(), "無効にした役に鍵が残っている"


def test_update_retargets_a_vanished_source():
    """キットのフォルダが移ったら、役が覚えている取得元を付け替える。実在する取得元は触らない。"""
    from paths import profile_dir

    reset()
    d = profile_dir("fixer")
    d.mkdir(parents=True, exist_ok=True)
    dist = HOME / "plugins" / "seaos-hermes-agent-kit-plugin" / "dist" / "fixer"
    dist.mkdir(parents=True, exist_ok=True)
    gone = HOME / "plugins" / "seaos-hermes-agent-kit" / "dist" / "fixer"
    (d / "distribution.yaml").write_text(f"name: fixer\nsource: {gone}\nversion: 1\n", encoding="utf-8")
    assert kit.retarget_source(dist, "fixer")
    assert f"source: {dist.resolve()}\n" in (d / "distribution.yaml").read_text(encoding="utf-8")
    assert "name: fixer" in (d / "distribution.yaml").read_text(encoding="utf-8"), "他の行を壊した"

    elsewhere = HOME / "my-own-dist"
    elsewhere.mkdir(exist_ok=True)
    (d / "distribution.yaml").write_text(f"name: fixer\nsource: {elsewhere}\n", encoding="utf-8")
    assert not kit.retarget_source(dist, "fixer"), "利用者が意図して入れた取得元を付け替えた"


if __name__ == "__main__":
    run_tests(globals())
    finish()
