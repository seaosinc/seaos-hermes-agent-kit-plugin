"""multiplex ゲートウェイの常駐処理のために、**default ホーム**を設える。

multiplex では、ゲートウェイの常駐処理（kanban の自動分解など）は
**起動ホーム（default ルート）の config と .env を読む**
（Hermes の gateway/kanban_watchers_dispatcher.py）。キットは役の
プロファイルにだけ配ってきたので、デスクトップ本体の設定が無い環境では
分解が「no aux client」で静かに死に、triage にカードが積まれる
（実際に踏んだ）。

役への配布と同じく、**反映のたびに書き直す**。本体やデスクトップが
config を書き換えて節が消えても、次の反映で戻る。
"""

from __future__ import annotations

from typing import Dict, List

import yaml

import env as env_mod
import roles
from paths import hermes_home


def _sync_env(source: Dict[str, str], report: List[str]) -> None:
    """モデルの鍵を default ホームの .env にも配る。

    **正に無い値は潰さない。** default ホームはデスクトップ本体の家でもあり、
    本体が入れた鍵がそこにあることがある。役への配布と同じ規則で、
    正に値があるときだけ書く。
    """
    path = hermes_home() / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    wrote = False
    for var in roles.MODEL_KEYS:
        value = source.get(var, "")
        if not value:
            continue
        before = list(lines)
        lines = env_mod._upsert(lines, var, value, f"{var}（キットが default ホームにも配る）")
        wrote = wrote or lines != before
    if wrote:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        env_mod._secure(path)
        report.append("default ホームにもモデルの鍵を配りました")


def _sync_config(report: List[str]) -> None:
    """default ホームの config.yaml に、自動分解に必要な節だけを外科的に書く。

    **他の節には触らない。** model 節はデスクトップ本体のものなので、
    分解のモデルは auxiliary で明示して本体の設定に依存しない形にする。
    """
    gen = roles.generator()
    path = hermes_home() / "config.yaml"
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except yaml.YAMLError:
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    before = yaml.safe_dump(cfg, sort_keys=False)

    dec = cfg.setdefault("auxiliary", {}).setdefault("kanban_decomposer", {})
    # **provider を明示する。** 書かないと default ホームのメインモデルに
    # フォールバックし、本体の設定次第で動いたり死んだりする
    dec["provider"] = gen.PROVIDER
    dec["model"] = gen.SMART
    # **分解の親カードの持ち主。** 無いと default プロファイルに落ちる
    # （Hermes の kanban_decompose._resolve_profile_from_cfg）
    cfg.setdefault("kanban", {})["orchestrator_profile"] = "fixer"
    if gen.PROVIDER == "bedrock":
        bedrock = cfg.setdefault("bedrock", {})
        bedrock["region"] = gen.BEDROCK_REGION
        bedrock.setdefault("discovery", {})["enabled"] = False

    after = yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True)
    if after != before:
        path.write_text(after, encoding="utf-8")
        report.append("default ホームに自動分解の設定を配りました")


def sync() -> List[str]:
    """default ホームへ配る。報告行を返す（変化が無ければ「最新です」の1行）。"""
    source = env_mod.read_env(env_mod.env_file())
    report: List[str] = []
    _sync_env(source, report)
    _sync_config(report)
    if not report:
        report.append("default ホームの自動分解の設定は最新です")
    return report
