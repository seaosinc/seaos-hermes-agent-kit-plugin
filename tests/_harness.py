"""テストの走らせ方。**各テストファイルで同じものを書き写さない**ための共通部分。

pytest を入れていない（Hermes の venv にそのまま載せて動かすため）ので、
1つずつ実行して結果を並べるだけの薄いものを持つ。
"""

from __future__ import annotations

import sys

failures: list[str] = []


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
