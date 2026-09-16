#!/usr/bin/env python3
"""受け取ったファイルを担当へ渡す仕組みの回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/files_test.py

一時ディレクトリを `HERMES_HOME` と置き場に見立てる。**本番の ~/.hermes には触らない。**
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="files-test-"))
os.environ["HERMES_HOME"] = str(HOME)
os.environ["WORKSPACE_FILES_ROOT"] = str(HOME / "kanban" / "files")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import build_distributions as bd  # noqa: E402
import files  # noqa: E402

from _harness import finish, run_tests  # noqa: E402


def received(name: str, body: bytes = b"hello") -> Path:
    """ゲートウェイがキャッシュへ落としたのと同じ形のファイル。"""
    d = HOME / "profiles" / "operator" / "cache" / "documents"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(body)
    return p


def test_keep_copies_and_restores_name():
    """ゲートウェイが付けた接頭辞（doc_<id>_）を外して、人が付けた名前で置く。"""
    kept = files.keep([received("doc_0123456789ab_仕様書 v2.pdf")])
    assert kept[0].name == "仕様書 v2.pdf", kept
    assert kept[0].read_bytes() == b"hello"
    assert kept[0].is_relative_to(files.files_root())


def test_refuses_outside_cache():
    """受け取ったファイルの置き場の外（秘密など）は引き取らない。"""
    secret = HOME / "seaos-kit" / ".env"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("OPENROUTER_API_KEY=sk-x", encoding="utf-8")
    for bad in (secret, Path("/etc/hosts")):
        try:
            files.keep([bad])
        except files.FilesError:
            continue
        raise AssertionError(f"{bad} を引き取ってしまった")


def test_refuses_traversal():
    sneaky = HOME / "profiles" / "operator" / "cache" / ".." / ".." / ".." / "seaos-kit" / ".env"
    try:
        files.keep([sneaky])
    except files.FilesError:
        return
    raise AssertionError("cache/.. で外へ出られた")


def test_refuses_oversize():
    big = received("doc_0123456789ab_big.bin", b"\0" * (files.MAX_BYTES + 1))
    try:
        files.keep([big])
    except files.FilesError:
        return
    raise AssertionError("25MB を超えるものを引き取った")


def test_boxes_can_read_but_not_write():
    """作業部屋へ、置き場と添付が読み取り専用・左右同じパスで渡る。"""
    spec = {**bd.ROLES["developer"]}
    volumes = bd.build_config(ROOT, "developer", spec)["terminal"]["docker_volumes"]
    assert f"{bd.FILES_ROOT}:{bd.FILES_ROOT}:ro" in volumes, volumes
    assert f"{bd.ATTACHMENTS_ROOT}:{bd.ATTACHMENTS_ROOT}:ro" in volumes, volumes


def test_same_root_as_generator():
    """本文に書くパスと、箱へ渡すパスが一致する（ずれると箱から読めない）。"""
    import importlib

    os.environ.pop("WORKSPACE_FILES_ROOT")
    try:
        fresh = importlib.reload(bd)
        assert str(files.files_root()) == fresh.FILES_ROOT, (files.files_root(), fresh.FILES_ROOT)
    finally:
        os.environ["WORKSPACE_FILES_ROOT"] = str(HOME / "kanban" / "files")


def test_office_gets_markdown_beside_it():
    """Excel などは隣に .md を置き、そのパスも返す（担当の多くはそちらしか読めない）。"""
    original = files.to_markdown
    files.to_markdown = lambda _p: "| 品目 | 数量 |"
    try:
        kept = files.keep([received("doc_0123456789ab_見積.xlsx"), received("doc_0123456789ab_memo.txt")])
    finally:
        files.to_markdown = original
    names = [p.name for p in kept]
    assert names == ["見積.xlsx", "見積.xlsx.md", "memo.txt"], names
    assert kept[1].read_text(encoding="utf-8") == "| 品目 | 数量 |"


def test_failed_conversion_still_passes_original():
    original = files.to_markdown
    files.to_markdown = lambda _p: None
    try:
        kept = files.keep([received("doc_0123456789ab_壊れた.pdf")])
    finally:
        files.to_markdown = original
    assert [p.name for p in kept] == ["壊れた.pdf"], kept


def test_handler_reads_files_only():
    """シェルの無い handler に、置き場と添付だけを読む MCP が載る。書く道具は載らない。"""
    spec = bd.worker_roles(ROOT)["handler"]
    server = bd.build_config(ROOT, "handler", spec)["mcp_servers"]["files"]
    assert server["args"][-2:] == [bd.FILES_ROOT, bd.ATTACHMENTS_ROOT], server["args"]
    tools = set(server["tools"]["include"])
    assert "read_text_file" in tools
    assert not tools & {"write_file", "edit_file", "move_file", "create_directory"}, tools
    assert "{{" not in str(server)


def test_windows_paths_are_moved_under_seaos():
    """Windows のパスは箱の中に作れないので /seaos/… に振り替え、対応表を箱へ渡す。"""
    import importlib

    saved = {k: os.environ.get(k) for k in
             ("WORKSPACE_ARTIFACTS_ROOT", "WORKSPACE_FILES_ROOT", "WORKSPACE_ATTACHMENTS_ROOT")}
    os.environ.update({
        "WORKSPACE_ARTIFACTS_ROOT": r"C:\Users\u\.hermes\kanban\workspaces",
        "WORKSPACE_FILES_ROOT": r"C:\Users\u\.hermes\kanban\files",
        "WORKSPACE_ATTACHMENTS_ROOT": r"C:\Users\u\.hermes\kanban\attachments",
    })
    try:
        win = importlib.reload(bd)
        term = win.build_config(ROOT, "developer", dict(win.ROLES["developer"]))["terminal"]
        vols = term["docker_volumes"]
        assert r"C:\Users\u\.hermes\kanban\workspaces:/seaos/workspaces" in vols, vols
        assert r"C:\Users\u\.hermes\kanban\files:/seaos/files:ro" in vols, vols
        assert "/seaos/files" in term["docker_env"]["SEAOS_PATH_MAP"]
        # macOS の形は左右同じのまま
        assert bd.box_path("/Users/u/.hermes/kanban/files") == "/Users/u/.hermes/kanban/files"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        importlib.reload(bd)


def test_seaos_path_script_round_trips():
    """箱の中の seaos-path が、本文のパスを読み替え、宣言用にホストへ戻す。"""
    import subprocess

    script = ROOT / "templates/workspace/seaos-path"

    def run(*args, mapping):
        return subprocess.run(["sh", str(script), *args], capture_output=True, text=True,
                              env={**os.environ, "SEAOS_PATH_MAP": mapping}).stdout.strip()

    win = r"C:\U\.hermes\kanban\files=/seaos/files;C:\U\.hermes\kanban\workspaces=/seaos/workspaces"
    assert run(r"C:\U\.hermes\kanban\files\d\見積 v2.xlsx.md", mapping=win) == "/seaos/files/d/見積 v2.xlsx.md"
    assert run("--host", "/seaos/workspaces/t1/a.png", mapping=win) == r"C:\U\.hermes\kanban\workspaces\t1\a.png"
    mac = "/Users/u/.hermes/kanban/files=/Users/u/.hermes/kanban/files"
    assert run("/Users/u/.hermes/kanban/files/a.md", mapping=mac) == "/Users/u/.hermes/kanban/files/a.md"
    assert run("/elsewhere/x", mapping=win) == "/elsewhere/x"


def test_prune_removes_old_only():
    old = files.keep([received("doc_0123456789ab_old.txt")])[0].parent
    new = files.keep([received("doc_0123456789ab_new.txt")])[0].parent
    past = 100 * 86400
    os.utime(old, (old.stat().st_atime - past, old.stat().st_mtime - past))
    files.prune(90)
    assert not old.exists()
    assert new.exists()


if __name__ == "__main__":
    run_tests(globals())
    finish()
