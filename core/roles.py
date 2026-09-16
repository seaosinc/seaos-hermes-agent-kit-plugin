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


def all_names() -> List[str]:
    """**外した役も含めた**全役。設定画面の一覧と、鍵の管理範囲に使う。"""
    return list(all_specs().keys())


def names() -> List[str]:
    """**入れる役だけ。** 反映・鍵の配布・検証はここを回す。

    外した役を回すと、外したはずの役が反映のたびに作り直される。
    全役が要る場面（一覧・鍵の管理範囲）は all_names() を使う。
    """
    import selection

    off = set(selection.disabled())
    # 配置表は1回だけ読む（all_specs は呼ぶたびに生成器を読み直す）
    return [n for n, sp in all_specs().items() if n not in off or sp.get("essential")]


def is_enabled(name: str) -> bool:
    return name in names()


def essential(name: str) -> bool:
    """**外せない役。** 板の仕組みそのものが前提にしている（配置表の `essential`）。"""
    return bool((all_specs().get(name) or {}).get("essential"))


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


def origin(name: str) -> str:
    """その役の出自。`"shipped"`（配られてきた）か `"local"`（この環境で作った）。

    固定役は配布物の一部なので常に shipped。
    """
    return str((all_specs().get(name) or {}).get("origin") or "shipped")


def env_requirements(name: str) -> List[Tuple[str, bool, str]]:
    """その役が宣言した (変数名, 必須か, 説明)。"""
    spec = all_specs().get(name) or {}
    out: List[Tuple[str, bool, str]] = []
    for entry in spec.get("env") or []:
        var, desc, required = entry
        out.append((var, bool(required), str(desc)))
    return out


def env_key(role: str, var: str) -> str:
    """その役だけの値を入れる名前。`<役>__<変数>`（役名は大文字・`-` は `_`）。

    例: `PROJECT_OPERATOR__SLACK_BOT_TOKEN`
    """
    return f"{role.upper().replace('-', '_')}__{var}"


def own_env_vars(name: str) -> List[str]:
    """**その役が自分専用の値を要る変数。**

    窓口が複数あるとき、Slack のトークンを共有してはいけない——**同じトークンで
    2つのゲートウェイを繋ぐと、両方が同じ発言を拾って二重に返事をする。**
    共有の値に落ちないよう、ここに挙げた変数は `<役>__<変数>` だけを見る。
    """
    spec = all_specs().get(name) or {}
    declared = {var for var, _req, _desc in env_requirements(name)}
    return [v for v in (spec.get("env_own") or []) if v in declared]


# **役ごとに上書きできる鍵。** 共通の値があれば全役がそれを使い、役つきの名前
# （`DEVELOPER__OPENROUTER_API_KEY`）に値があればその役だけがそちらを使う。
# 役ごとに請求を分けたい・上限を分けたい、という用途。
#
# own（`env_own`）との違いは**共通へ落ちるかどうか**。Slack のトークンは落ちると
# 二重返事の事故になるので落とさないが、モデルの鍵は落ちてよい——
# 無いと何も動かない唯一の鍵なので、むしろ落ちないと困る。
OVERRIDABLE_ENV = ("OPENROUTER_API_KEY",)


def override_env_vars(name: str) -> List[str]:
    """**その役が、共通の値を役つきの値で上書きできる変数。**"""
    declared = [var for var, _req, _desc in env_requirements(name)]
    own = set(own_env_vars(name))
    return [v for v in OVERRIDABLE_ENV if v in declared and v not in own]


def env_value(name: str, var: str, source: Dict[str, str]) -> str:
    """その役に配る値。**3つの規則をここ1箇所で決める。**

    - 専用（own）: 役つきの名前だけを見る。共通へは落ちない
    - 上書きできる（override）: 役つきの名前に値があればそれ、無ければ共通
    - それ以外: 共通だけ
    """
    if var in own_env_vars(name):
        return source.get(env_key(name, var), "")
    if var in override_env_vars(name):
        return source.get(env_key(name, var), "") or source.get(var, "")
    return source.get(var, "")


def managed_env_vars() -> List[str]:
    """キットが管理している変数の全体。**知らない変数には触らないため**に使う。"""
    # **外した役の鍵も管理下に置く。** 外している間に「知らない鍵」として
    # 掃除されると、入れ直したときに鍵が消えている。
    seen: List[str] = []
    for name in all_names():
        own = set(own_env_vars(name))
        for var, _req, _desc in env_requirements(name):
            # 自分専用の値を要る変数は、役つきの名前だけを管理する
            key = env_key(name, var) if var in own else var
            if key not in seen:
                seen.append(key)
        # 上書きは共通の名前と**両方**を管理する（共通は他の役も使う）
        for var in override_env_vars(name):
            key = env_key(name, var)
            if key not in seen:
                seen.append(key)
    return seen


def without_board() -> List[str]:
    """板に載らない役（人間が直接呼ぶ）。doctor が kanban の欠落を咎めないため。"""
    return [n for n, sp in all_specs().items() if sp.get("no_kanban")]
