#!/usr/bin/env python3
"""**規約に書いた名前の実在照合が、本当に検知するか。**

「書いてあるのに無い」は一番静かに壊れる——エージェントは呼べないまま
「この環境ではできない」と正しく報告して止まるだけなので、綴りの誤りが
世代を越えて残る。**検知できていることを、偽物を置いて確かめる。**

本番の ~/.hermes には触らない（HERMES_HOME を一時ディレクトリに向ける）。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

failures: list[str] = []


def check(name: str, fn) -> None:
    try:
        fn()
    except AssertionError as e:
        failures.append(name)
        print(f"  ✗ {name}\n      {e}")
    else:
        print(f"  ✓ {name}")


class Rep:
    """doctor の Report の代役。"""

    def __init__(self) -> None:
        self.bad: list[str] = []
        self.good: list[str] = []
        self.notes: list[str] = []

    def ok(self, msg: str) -> None:
        self.good.append(msg)

    def ng(self, msg: str) -> None:
        self.bad.append(msg)

    def note(self, msg: str) -> None:
        self.notes.append(msg)


def _profile(home: Path, name: str, soul: str) -> None:
    d = home / "profiles" / name
    (d / "skills").mkdir(parents=True, exist_ok=True)
    (d / "SOUL.md").write_text(soul, encoding="utf-8")


def _scan(soul: str) -> Rep:
    """偽の役を1つ置いて照合させ、結果を返す。"""
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        os.environ["HERMES_HOME"] = str(home)
        _profile(home, "probe", soul)
        import importlib

        import paths
        import refcheck
        importlib.reload(paths)
        importlib.reload(refcheck)
        rep = Rep()
        # 道具の照合は役ごとに hermes を起動するので、ここでは見ない
        refcheck.run(rep, deep=False)
        return rep


def test_missing_command_is_caught():
    rep = _scan("実装したら `seaos-kit nosuchcommand` を叩く。\n")
    assert any("実在しないコマンド" in b for b in rep.bad), rep.bad


def test_existing_command_is_not_flagged():
    rep = _scan("反映するには `seaos-kit update` を叩く。\n")
    assert not rep.bad, rep.bad


def test_profile_option_is_not_mistaken_for_a_subcommand():
    """`hermes -p avatar tools list` の `avatar` は下位コマンドではない。"""
    rep = _scan("`hermes -p avatar tools list` で確かめる。\n")
    assert not rep.bad, rep.bad


def test_adjacent_lines_are_not_joined():
    """コード塊の隣り合う2行を1つの呼び出しとして読まない。"""
    rep = _scan("    seaos-kit --help    キット側の一覧\n    hermes kanban --help\n")
    assert not rep.bad, rep.bad


def test_unknown_name_is_reported():
    """**現役に無い名前は挙げる。** 落とさないのは、括り方の約束から外れて
    いるだけのこともあるため（コード片、架空の例）。"""
    rep = _scan("調べものは `researcher` に投げる。\n")
    assert any("照合できない名前" in n and "researcher" in n for n in rep.notes), rep.notes


def test_live_role_is_not_reported():
    rep = _scan("実装は `developer` に渡す。\n")
    assert not any("developer" in n for n in rep.notes), rep.notes


if __name__ == "__main__":
    check("実在しないコマンドを検知する", test_missing_command_is_caught)
    check("実在するコマンドは咎めない", test_existing_command_is_not_flagged)
    check("-p の値を下位コマンドと読み違えない", test_profile_option_is_not_mistaken_for_a_subcommand)
    check("隣の行とつなげて読まない", test_adjacent_lines_are_not_joined)
    check("現役に無い名前を挙げる", test_unknown_name_is_reported)
    check("現役の役は挙げない", test_live_role_is_not_reported)
    print()
    if failures:
        print(f"★ {len(failures)} 件失敗")
        sys.exit(1)
    print("すべて通った")
