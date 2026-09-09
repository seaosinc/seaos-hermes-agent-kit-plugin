#!/usr/bin/env python3
"""まっさらな環境へ配布物を入れられるかを確かめる（別マシンの代役）。

    ~/.hermes/hermes-agent/venv/bin/python tests/fresh_install_test.py

一時ディレクトリを `HERMES_HOME` に見立てて、`hermes profile install` で各役を入れる。
**本番の ~/.hermes には触らない。**

配布の再現性はここでしか担保できない。手元では既に入っているので「動いている」ように
見えるが、初めての環境では config の既定・スキルの場所・cron のスクリプトなど、
どれか1つでも欠けると入らない。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERMES = Path(os.environ.get("HERMES_BIN") or (Path.home() / ".local/bin/hermes"))

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


def run(args: list[str], home: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "HERMES_HOME": str(home)}
    return subprocess.run(args, capture_output=True, text=True, env=env,
                          stdin=subprocess.DEVNULL, timeout=180)


HOME = Path(tempfile.mkdtemp(prefix="hermes-fresh-"))
DIST = HOME / "dist"
ROLES = ("operator", "fixer", "developer", "handler", "recruiter")

sys.path.insert(0, str(ROOT / "core"))
import build_distributions as bd  # noqa: E402

bd.build(ROOT, DIST)


def test_install_all_roles():
    """どの役も入るか。**1つでも欠けると協調が成立しない。**"""
    for role in ROLES:
        r = run([str(HERMES), "profile", "install", str(DIST / role), "-y"], HOME)
        assert r.returncode == 0, f"{role}: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
        assert (HOME / "profiles" / role / "SOUL.md").exists(), f"{role}: SOUL が無い"


def test_env_example_is_written():
    """秘密は運ばず、代わりに何が要るかを示すこと。"""
    ex = HOME / "profiles/operator/.env.EXAMPLE"
    assert ex.exists(), ".env.EXAMPLE が作られていない"
    body = ex.read_text(encoding="utf-8")
    for key in ("SLACK_BOT_TOKEN", "OPENROUTER_API_KEY"):
        assert key in body, f"{key} が示されていない"
    assert not (HOME / "profiles/operator/.env").exists(), ".env が配布されている"


def test_gate_lands_complete():
    """ゲートの部品（プラグイン・フック・スクリプト）が入るか。"""
    d = HOME / "profiles/operator"
    assert (d / "plugins/booking-gate/__init__.py").exists(), "プラグインが無い"
    assert (d / "hooks/mem0-up/handler.py").exists(), "フックが無い"
    assert (d / "scripts/booking_sync.py").exists(), "ポーラーが無い"
    assert (d / "scripts/kit_sync.sh").exists(), "定期実行のスクリプトが無い"
    # cron のジョブは配らない（update のたびにスケジューラの状態を壊すため）。
    # 登録は hermes-kit install が公式コマンドでやる
    assert not (d / "cron/jobs.json").exists(), "cron のジョブを配ってはいけない"


def test_profiles_are_listed():
    """Hermes がプロファイルとして認識し、版が出るか。"""
    r = run([str(HERMES), "profile", "list"], HOME)
    assert r.returncode == 0, r.stderr
    for role in ROLES:
        assert role in r.stdout, f"{role} が一覧に出ない\n{r.stdout}"
    assert "@0.1.0" in r.stdout, "版が出ていない（配布物として認識されていない）"


def test_update_is_idempotent():
    """同じ配布物で update しても壊れないか。"""
    r = run([str(HERMES), "profile", "update", "fixer", "-y"], HOME)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert (HOME / "profiles/fixer/SOUL.md").exists()


def test_user_data_survives_update():
    """更新でユーザーのデータが消えないか。**ここが公式に預けた一番の理由。**"""
    memories = HOME / "profiles/fixer/memories"
    memories.mkdir(parents=True, exist_ok=True)
    (memories / "keep.md").write_text("消えては困る", encoding="utf-8")
    cfg = HOME / "profiles/fixer/config.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8") + "\n# ユーザーが足した行\n", encoding="utf-8")

    r = run([str(HERMES), "profile", "update", "fixer", "-y"], HOME)
    assert r.returncode == 0, r.stderr
    assert (memories / "keep.md").exists(), "記憶が消えた"
    assert "ユーザーが足した行" in cfg.read_text(encoding="utf-8"), "config が上書きされた"


if __name__ == "__main__":
    print(f"まっさらな環境（{HOME}）")
    check("全役が入る", test_install_all_roles)
    check(".env.EXAMPLE が示される", test_env_example_is_written)
    check("ゲートが3点そろう", test_gate_lands_complete)
    check("プロファイルとして認識され、版が出る", test_profiles_are_listed)
    check("同じ配布物で update できる", test_update_is_idempotent)
    check("更新でユーザーのデータが残る", test_user_data_survives_update)
    shutil.rmtree(HOME, ignore_errors=True)
    print()
    if failures:
        print(f"★ {len(failures)} 件失敗")
        sys.exit(1)
    print("すべて通った")
