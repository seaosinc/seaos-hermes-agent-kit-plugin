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

failures: list[str] = []


def check(name: str, fn) -> None:
    try:
        fn()
    except AssertionError as e:
        failures.append(name)
        print(f"  ✗ {name}\n      {e}")
    except Exception as e:  # noqa: BLE001
        failures.append(name)
        print(f"  ✗ {name}\n      {type(e).__name__}: {e}")
    else:
        print(f"  ✓ {name}")


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


def test_forget_on_removal():
    reset()
    selection.set_enabled("handler", False)
    selection.forget("handler")
    assert "handler" in roles.names()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(fn.__doc__.splitlines()[0] if fn.__doc__ else name, fn)
    print()
    if failures:
        print(f"★ {len(failures)} 件失敗")
        sys.exit(1)
    print("すべて通った")
