"""役の一覧と宣言を、生成器（配置表）から引く。

**2箇所で持たない。** zsh 版は `--roles` / `--env` / `--describe` を叩いていた。
Python になった以上、サブプロセスを挟まず直接 import する。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from paths import kit_root


def _generator():
    """build_distributions.py を module として読む（ファイル名が識別子にならないため）。"""
    path = Path(__file__).resolve().parent / "build_distributions.py"
    spec = importlib.util.spec_from_file_location("kit_generator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"生成器を読み込めない: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("kit_generator", module)
    spec.loader.exec_module(module)
    return module


def all_specs() -> Dict[str, dict]:
    """固定役（ROLES）＋業務別ワーカー（templates/workers/）。"""
    gen = _generator()
    return {**gen.ROLES, **gen.worker_roles(kit_root())}


def names() -> List[str]:
    return list(all_specs().keys())


def describe(name: str) -> str:
    """decomposer が読む説明文。**担当の割り振りを決める唯一の入力。**"""
    spec = all_specs().get(name) or {}
    return " ".join(str(spec.get("describe") or spec.get("desc") or "").split())


def summary(name: str) -> str:
    """人が読む一行。**設定画面の一覧に出る。**

    `describe` は decomposer 向けの長文なので、そのまま出すと切れて読めない。
    役が自分で名乗るのが筋なので、配置表と profile.yaml の `summary` を正とする。
    無ければ `describe` の最初の一文で代用する——**新しい役が無名のまま
    並ぶよりはましだが、書いてあるに越したことはない。**
    """
    spec = all_specs().get(name) or {}
    text = str(spec.get("summary") or "").strip()
    if text:
        return text
    described = describe(name)
    head = described.split("。")[0]
    return (head + "。") if head and len(head) < len(described) else described[:40]


def env_requirements(name: str) -> List[Tuple[str, bool, str]]:
    """その役が宣言した (変数名, 必須か, 説明)。"""
    spec = all_specs().get(name) or {}
    out: List[Tuple[str, bool, str]] = []
    for entry in spec.get("env") or []:
        var, desc, required = entry
        out.append((var, bool(required), str(desc)))
    return out


def managed_env_vars() -> List[str]:
    """キットが管理している変数の全体。**知らない変数には触らないため**に使う。"""
    seen: List[str] = []
    for name in names():
        for var, _req, _desc in env_requirements(name):
            if var not in seen:
                seen.append(var)
    return seen


def without_board() -> List[str]:
    """板に載らない役（人間が直接呼ぶ）。doctor が kanban の欠落を咎めないため。"""
    return [n for n, sp in all_specs().items() if sp.get("no_kanban")]
