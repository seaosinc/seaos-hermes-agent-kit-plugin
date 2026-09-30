"""テストの走らせ方。**各テストファイルで同じものを書き写さない**ための共通部分。

pytest を入れていない（Hermes の venv にそのまま載せて動かすため）ので、
1つずつ実行して結果を並べるだけの薄いものを持つ。
"""

from __future__ import annotations

import os
import sys

failures: list[str] = []

# **テスト中は、この PC の Hermes を起動させない**（core/hermes.py の forbidden）。
# 一時 HOME で本物の Hermes を起動すると、共有の起動スクリプトが一時 HOME の Python で書き直され、
# 一時 HOME が消えたとき Hermes Desktop が壊れる（2026-09-30 に2度起きた）。
os.environ["SEAOS_KIT_TESTING"] = "1"

# **Hermes 本体を動かすテストは、捨てられる環境（GitHub Actions）でだけ走らせる。**
#
# 一時ディレクトリを HERMES_HOME に見立てても、この PC の Hermes 本体を呼べば
# インストール先（~/.hermes/hermes-agent）は共有になる。Hermes は道具の置き場を
# HERMES_HOME から決めるので、一時 HOME に Python を入れたうえで、共有の起動スクリプトを
# その Python で書き直す。テストが終わって一時 HOME が消えると、起動スクリプトは
# 無い Python を指し、Hermes Desktop が「未インストール」の初期画面に戻った
# （2026-09-30 に実際に起きた）。**一時 HOME では守れない。**
#
# ここに挙げたものは run_all.py と `seaos-kit test` が飛ばし、
# .github/workflows/hermes.yml（Hermes 契約検査）が流す。
CI_ONLY = {"fresh_install_test.py"}


def require_disposable_env() -> None:
    """GitHub Actions の中でなければ、何もせずに止める（CI_ONLY のテストの先頭で呼ぶ）。"""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return
    print("このテストは Hermes 本体を動かすので、GitHub Actions（Hermes 契約検査）でだけ走ります。\n"
          "手元で流すと、この PC の Hermes のインストール先が書き換わります。\n"
          "確かめたいときは PR を出すか、GitHub の Actions から「Hermes 契約検査」を手で起動してください。")
    sys.exit(2)


def check(name: str, fn) -> None:
    """1件を走らせて結果を出す。失敗しても止めずに次へ進む。"""
    try:
        fn()
    except AssertionError as e:
        failures.append(name)
        print(f"  ✗ {name}\n      {e}")
    except Exception as e:  # noqa: BLE001  （想定外の例外も失敗として並べる）
        failures.append(name)
        print(f"  ✗ {name}\n      {type(e).__name__}: {e}")
    else:
        print(f"  ✓ {name}")


def run_tests(namespace: dict) -> None:
    """`test_` で始まる関数を定義順に走らせる。docstring の1行目を名前にする。"""
    for name, fn in list(namespace.items()):
        if name.startswith("test_") and callable(fn):
            check(fn.__doc__.splitlines()[0] if fn.__doc__ else name, fn)


def finish() -> None:
    print()
    if failures:
        print(f"★ {len(failures)} 件失敗")
        sys.exit(1)
    print("すべて通った")
