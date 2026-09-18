#!/usr/bin/env python3
"""Windows で踏んだ「場所の決め打ち」の回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/windows_paths_test.py

守りたいのは:
  * PATH に git が無くても、設定画面のバックエンド（plugin_api）が読み込める
    （Windows 版 Hermes は Git を PATH に入れない。読み込み時に git で落ち、API ごと載らなかった）
  * git は、PATH に無ければ Hermes が持っている Git（<ホーム>/git/cmd/git.exe）を使う
  * HERMES_HOME が見えなくても、動いている Python の場所から Hermes のホームを当てる
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import paths  # noqa: E402

from _harness import finish, run_tests  # noqa: E402


def test_plugin_api_loads_without_git_on_path():
    """PATH に git が無く、Hermes の Git も無くても、バックエンドの読み込みは落ちない。"""
    home = tempfile.mkdtemp(prefix="no-git-home-")
    env = {**os.environ, "PATH": tempfile.mkdtemp(prefix="empty-path-"), "HERMES_HOME": home}
    code = (
        "import sys; sys.path.insert(0, %r); import plugin_api; "
        "print(len(plugin_api.router.routes))" % str(ROOT / "dashboard")
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, f"読み込みで落ちた:\n{proc.stderr[-1500:]}"
    assert int(proc.stdout.strip() or 0) > 0, proc.stdout


def test_git_falls_back_to_hermes_git():
    """PATH に git が無ければ、Hermes のホームにある Git を使う。"""
    home = Path(tempfile.mkdtemp(prefix="hermes-home-"))
    git = home / "git" / "cmd" / "git.exe"
    git.parent.mkdir(parents=True)
    git.write_text("", encoding="utf-8")
    saved = {k: os.environ.get(k) for k in ("PATH", "HERMES_HOME")}
    try:
        os.environ["PATH"] = tempfile.mkdtemp(prefix="empty-path-")
        os.environ["HERMES_HOME"] = str(home)
        assert paths.git_bin() == str(git), paths.git_bin()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_home_is_inferred_from_the_running_hermes_python():
    """HERMES_HOME が見えなくても、<ホーム>/hermes-agent/venv/... の Python からホームを当てる。"""
    saved_exe, saved_home = sys.executable, os.environ.pop("HERMES_HOME", None)
    try:
        for exe, home in (
            (r"C:\hermes\hermes-agent\venv\Scripts\python.exe", r"C:\hermes"),
            ("/opt/h/hermes-agent/.venv/bin/python", "/opt/h"),
        ):
            sys.executable = str(Path(exe.replace("\\", "/")))
            assert str(paths.hermes_home()) == str(Path(home.replace("\\", "/"))), (exe, paths.hermes_home())
        sys.executable = "/usr/bin/python3"
        assert paths.hermes_home() == paths.default_hermes_home()
    finally:
        sys.executable = saved_exe
        if saved_home is not None:
            os.environ["HERMES_HOME"] = saved_home


def test_windows_command_is_put_on_path():
    """Windows では、コマンドを置くだけでなくユーザーの PATH にも足す。

    置くだけだと、エージェントの端末から `seaos-kit` が見つからない。実際に、
    窓口がアクセス許可を出せず「seaos-kit も利用できない」と答えた。
    """
    import types

    import platform_ops

    target = Path(r"C:\Users\t\AppData\Local\Programs\seaos-kit")
    stored = {"Path": r"C:\Windows;C:\Windows\System32"}

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    fake = types.SimpleNamespace(
        HKEY_CURRENT_USER=0, KEY_READ=1, KEY_WRITE=2, REG_EXPAND_SZ=2,
        OpenKey=lambda *a, **k: _Key(),
        QueryValueEx=lambda _k, name: (stored[name], 2),
        SetValueEx=lambda _k, name, _r, _t, value: stored.__setitem__(name, value),
    )
    saved = sys.modules.get("winreg")
    sys.modules["winreg"] = fake
    saved_path = os.environ.get("PATH", "")
    try:
        assert platform_ops._win_add_to_path(target) is True, "PATH に足していない"
        assert str(target) in stored["Path"], stored["Path"]
        # 二度目は足さない（同じ場所が並ばない）
        assert platform_ops._win_add_to_path(target) is False, "同じ場所を二重に足した"
        assert stored["Path"].count(str(target)) == 1, stored["Path"]
    finally:
        os.environ["PATH"] = saved_path
        if saved is None:
            sys.modules.pop("winreg", None)
        else:
            sys.modules["winreg"] = saved


if __name__ == "__main__":
    run_tests(globals())
    finish()
