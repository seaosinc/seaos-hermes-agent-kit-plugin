"""役の一覧と宣言を、生成器（配置表）から引く。

**2箇所で持たない。** zsh 版は `--roles` / `--env` / `--describe` を叩いていた。
Python になった以上、サブプロセスを挟まず直接 import する。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from paths import kit_root, local_workers_dir

_GENERATOR_PATH = Path(__file__).resolve().parent / "build_distributions.py"
# 生成器の環境変数（モデル名・置き場）。変われば読み直す。
_GENERATOR_ENV = ("MODEL_FAST", "MODEL_SMART", "MODEL_SENIOR", "WORKSPACE_IMAGE",
                  "WORKSPACE_ARTIFACTS_ROOT", "WORKSPACE_FILES_ROOT", "WORKSPACE_ATTACHMENTS_ROOT",
                  "KIT_VERSION", "HERMES_HOME")
_cache: Dict[str, Tuple[Any, Any]] = {}


def _stamp(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def generator():
    """生成器（build_distributions.py）を module として読む。**ファイルが変わったときだけ読み直す。**

    `import` で済ませないのは、設定画面のバックエンドが長く生きるから。
    `plugins update` でファイルが新しくなっても、import したものは古いまま残る。
    かといって呼ぶたびに読み直すと、1回 60ms が1リクエストで100回を超え、
    設定画面の一覧に 7 秒かかった（実測）。更新時刻と環境変数で見分ける。
    """
    key = (_stamp(_GENERATOR_PATH), tuple(os.environ.get(k) for k in _GENERATOR_ENV))
    hit = _cache.get("generator")
    if hit and hit[0] == key:
        return hit[1]
    spec = importlib.util.spec_from_file_location("kit_generator", _GENERATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"生成器を読み込めない: {_GENERATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["kit_generator"] = module
    spec.loader.exec_module(module)
    _cache["generator"] = (key, module)
    return module


def _workers_stamp() -> tuple:
    """役の定義が置かれた場所の状態。**足した・消した・書き換えた**を見分ける。"""
    out = []
    for root in (kit_root() / "templates" / "workers", local_workers_dir()):
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            if d.is_dir():
                out.append((str(d), _stamp(d), _stamp(d / "profile.yaml"), _stamp(d / "mcp.yaml"),
                            _stamp(d / "SOUL.md")))
    return tuple(out)


def all_specs() -> Dict[str, dict]:
    """固定役（ROLES）＋業務別ワーカー（templates/workers/）。

    **読み直すのは、生成器か役の定義が変わったときだけ。** 設定画面の1回の表示で
    役ごとに何度も引かれる。
    """
    gen = generator()
    key = (id(gen), _workers_stamp())
    hit = _cache.get("specs")
    if hit and hit[0] == key:
        return dict(hit[1])
    specs = {**gen.ROLES, **gen.worker_roles(kit_root())}
    _cache["specs"] = (key, specs)
    return dict(specs)


def mcp_servers(name: str) -> Dict[str, dict]:
    """その役に載る MCP サーバ。"""
    return generator().mcp_servers_of(kit_root(), name, all_specs().get(name) or {})


def mcp_env_vars(name: str) -> Dict[str, List[str]]:
    """その役の MCP が参照する環境変数（サーバ名 -> 変数名）。"""
    return generator().mcp_env_vars(kit_root(), name, all_specs().get(name) or {})


def skills(name: str) -> List[str]:
    """その役に載るスキル。"""
    return generator().skills_of(kit_root(), name, all_specs().get(name))


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
    text = str(spec.get("describe") or spec.get("desc") or "")
    # 外した役を名指しする文は落とす（規約と同じ規則。生成器の strip_role_blocks）
    return " ".join(generator().strip_role_blocks(text, set(names())).split())


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


# **秘密ではない値。** 設定画面で伏せ字にせず、入っている値も見せる。
# ID の一覧やドメインを伏せると、カンマ区切りの入力を見ながら直せず、
# 何が入っているかも確かめられない。**迷ったら入れない**——伏せるほうが安全側。
PLAIN_ENV = ("SLACK_ALLOWED_USERS", "SLACK_OWNER_ID", "SLACK_HOME_CHANNEL",
             "AWS_REGION", "BACKLOG_DOMAIN")


def is_plain(var: str) -> bool:
    """画面で値を見せてよい変数か。"""
    return var in PLAIN_ENV


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
    if var == "SLACK_ALLOWED_USERS":
        return _allowed_with_owner(name, source)
    return _raw_env_value(name, var, source)


def _raw_env_value(name: str, var: str, source: Dict[str, str]) -> str:
    if var in own_env_vars(name):
        return source.get(env_key(name, var), "")
    if var in override_env_vars(name):
        return source.get(env_key(name, var), "") or source.get(var, "")
    return source.get(var, "")


def _allowed_with_owner(name: str, source: Dict[str, str]) -> str:
    """話しかけてよい人に、**オーナーを必ず含める。**

    オーナー（SLACK_OWNER_ID）は判断を仰ぐ相手なのに、SLACK_ALLOWED_USERS に入れ忘れると
    Slack の入口で弾かれて、オーナー本人が話しかけられなかった。配るときに足す
    （Hermes 本体の Slack もゲートも、同じ一覧を見る）。
    """
    allowed = [u.strip() for u in _raw_env_value(name, "SLACK_ALLOWED_USERS", source).split(",") if u.strip()]
    declared = {var for var, _req, _desc in env_requirements(name)}
    owner = _raw_env_value(name, "SLACK_OWNER_ID", source).strip() if "SLACK_OWNER_ID" in declared else ""
    if owner and owner not in allowed:
        allowed.append(owner)
    return ",".join(allowed)


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
