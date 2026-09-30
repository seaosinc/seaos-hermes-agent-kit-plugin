#!/usr/bin/env python3
"""Windows で実際に壊れたところの回帰テスト（2026-09-30、ユーザー名が日本語の Windows の PC）。

    ~/.hermes/hermes-agent/venv/bin/python tests/windows_robustness_test.py

  * `seaos-kit.cmd` の改行が `\\r\\r\\n` になって壊れていた（Windows の Python が改行をもう一度変える）
  * パスの日本語を UTF-8 で書いた .cmd を、cmd.exe が cp932 で読み違えうる
  * upgrade の検証（refcheck が Hermes を何十回も起動する）で時間切れになった
  * 定期実行が1つも登録されておらず、許可表が古いまま全員止まっていた（反映で戻らなかった）

一時ディレクトリを `HERMES_HOME` に見立てる。**Hermes は呼ばない。**
"""

from __future__ import annotations

import inspect
import os
import sys
import tempfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="windows-robustness-test-"))
os.environ["HERMES_HOME"] = str(HOME)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import doctor  # noqa: E402
import kit  # noqa: E402
import maintain  # noqa: E402
import platform_ops  # noqa: E402
import selfupdate  # noqa: E402

from _harness import finish, run_tests  # noqa: E402

LOCAL = r"C:\Users\OM事業部ナレッジマネジメント\AppData\Local"
PY = LOCAL + r"\hermes\hermes-agent\venv\Scripts\python.exe"
CLI = LOCAL + r"\hermes\plugins\seaos-hermes-agent-kit-plugin\core\cli.py"


def test_wrapper_has_no_japanese_path():
    """ユーザー名が日本語でも、ラッパーの中身は環境変数で書き、日本語を残さない。"""
    os.environ["LOCALAPPDATA"] = LOCAL
    try:
        text = platform_ops.win_wrapper(PY, CLI)
    finally:
        os.environ.pop("LOCALAPPDATA", None)
    assert text.isascii(), text
    assert r'"%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe"' in text, text
    assert 'set "PYTHONUTF8=1"' in text, "Python を UTF-8 で動かしていない"
    assert "chcp" not in text, "日本語が無いのに文字コードを切り替えている"


def test_wrapper_switches_codepage_only_when_needed():
    """環境変数に置き換えられない日本語のパスが残るときだけ、先に UTF-8 へ切り替える。"""
    text = platform_ops.win_wrapper(r"D:\ツール\python.exe", r"D:\キット\core\cli.py")
    lines = text.split("\r\n")
    assert lines[0] == "@echo off" and lines[1] == "chcp 65001 >nul", lines


def test_wrapper_file_has_single_crlf():
    """書いた .cmd の改行は `\\r\\n` だけ（`\\r\\r\\n` にしない）。"""
    target = HOME / "bin"
    saved = (platform_ops.os_kind, platform_ops.command_target, platform_ops._win_add_to_path,
             platform_ops._interpreter)
    platform_ops.os_kind = lambda: "win32"
    platform_ops.command_target = lambda: target
    platform_ops._win_add_to_path = lambda *a, **k: None
    platform_ops._interpreter = lambda: PY
    try:
        path = platform_ops.link_command()
    finally:
        (platform_ops.os_kind, platform_ops.command_target, platform_ops._win_add_to_path,
         platform_ops._interpreter) = saved
    data = path.read_bytes()
    assert b"\r\r\n" not in data, data
    assert data.count(b"\r\n") == data.count(b"\n"), data


def test_upgrade_and_maintain_skip_refcheck():
    """upgrade と日次の保守は refcheck を省く。単独の doctor では省かない。

    **doctor を実際には走らせない**（走らせると Hermes を呼ぶ）。コードの形で確かめる。
    """
    src = inspect.getsource(doctor.run)
    assert "if refs:" in src and "refcheck.run(rep" in src, "refs で refcheck を省けない"
    assert "refs: bool = True" in src, "単独の doctor で refcheck を省いてしまう"
    assert "doctor_mod.run(refs=False)" in inspect.getsource(selfupdate.run)
    assert "doctor_mod.run(refs=False)" in inspect.getsource(maintain)


def test_tests_cannot_start_hermes():
    """テスト中は、キットの口から Hermes を起動できない（一時 HOME で起動すると Desktop が壊れる）。"""
    import hermes
    assert os.environ.get("SEAOS_KIT_TESTING") == "1"
    code, out = hermes.run(["--version"])
    assert code == 126 and "テスト中" in out, (code, out)


def test_apply_reregisters_missing_cron():
    """反映のたびに、定期実行が無ければ登録し直す（登録済みなら何もしない）。"""
    assert "register_cron" in inspect.getsource(kit.update)


def test_hermes_output_is_read_as_utf8():
    """Hermes の出力は UTF-8 で読む（cp932 で読むと、日本語や記号で落ちる）。"""
    import hermes
    src = inspect.getsource(hermes.run)
    assert 'encoding="utf-8"' in src and 'errors="replace"' in src


run_tests(dict(globals()))
finish()
