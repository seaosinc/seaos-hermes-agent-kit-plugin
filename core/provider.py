"""モデルの取り寄せ先（OpenRouter / Amazon Bedrock）を切り替える。

**全役で1つ。** 値はキットの `.env` の `MODEL_PROVIDER` にあり、生成器が読んで
段（fast / mid / smart / senior）のモデルと、要る鍵を決める。

**切り替えると共有記憶（mem0）を消す。** 埋め込みのモデルが変わるので、これまでの
記憶とは互換性が無い（引いても的外れのものが返る）。残して混ぜるより、消して作り直す。
呼び手は、消えることを人に確かめてから `confirm=True` で呼ぶこと。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import env as env_mod
import mem0
import roles

Log = Callable[[str], None]

LABELS: Dict[str, str] = {"openrouter": "OpenRouter", "bedrock": "Amazon Bedrock"}
WARNING = ("取り寄せ先を変えると、埋め込みのモデルも変わります。"
           "これまでの共有記憶（mem0）とは互換性が無いため、記憶を消して作り直します。元に戻せません。")


class ProviderError(Exception):
    pass


@dataclass
class Result:
    lines: List[str] = field(default_factory=list)
    failures: int = 0

    def ok(self) -> bool:
        return self.failures == 0


def current() -> str:
    return roles.generator().PROVIDER


def options() -> List[Dict[str, str]]:
    return [{"id": p, "label": LABELS[p]} for p in roles.generator().PROVIDERS]


def switch(name: str, *, confirm: bool = False, log: Optional[Log] = None) -> Result:
    """取り寄せ先を変える。**記憶を消すので、confirm が無ければ断る。**

    ここでは `.env` を書き換えて記憶を消すところまで。各役への反映は、新しい鍵を
    入れてから「エージェントを反映」（update）で行う——鍵が無いまま配ると、
    全役が動かなくなるだけである。
    """
    res = Result()
    if name not in roles.generator().PROVIDERS:
        raise ProviderError(f"知らない取り寄せ先です: {name}")
    if name == current():
        res.lines.append(f"すでに {LABELS[name]} を使っています")
        return res
    if not confirm:
        raise ProviderError(WARNING + " よければ確認のうえで実行してください。")

    env_mod.set_value("MODEL_PROVIDER", name, "モデルの取り寄せ先（openrouter / bedrock）")
    res.lines.append(f"取り寄せ先を {LABELS[name]} にしました")
    if not mem0.wipe(log=res.lines.append):
        res.failures += 1

    gen = roles.generator()
    if not env_mod.read_env(env_mod.env_file()).get(gen.MODEL_KEY):
        res.lines.append(f"{gen.MODEL_KEY} を設定してから、「エージェントを反映」を押してください")
    else:
        res.lines.append("「エージェントを反映」を押すと、各エージェントに届きます")
    if log:
        for line in res.lines:
            log(line)
    return res
