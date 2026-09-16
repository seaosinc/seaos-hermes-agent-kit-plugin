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


def test_prune_removes_old_only():
    old = files.keep([received("doc_0123456789ab_old.txt")])[0].parent
    new = files.keep([received("doc_0123456789ab_new.txt")])[0].parent
    past = 100 * 86400
    os.utime(old, (old.stat().st_atime - past, old.stat().st_mtime - past))
    files.prune(90)
    assert not old.exists()
    assert new.exists()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(fn.__doc__.splitlines()[0] if fn.__doc__ else name, fn)
    print()
    if failures:
        print(f"★ {len(failures)} 件失敗")
        sys.exit(1)
    print("すべて通った")
