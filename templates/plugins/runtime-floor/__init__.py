"""runtime-floor — カードの実行時間の上限を、作る前に既定（30分）まで引き上げる。

**`0` は「無制限」ではなく「0秒」である。** Hermes は値の有無で判定するので、
0 が入ったカードは起動から15秒で強制終了され、2回失敗すると `gave_up` になって
二度と動かない。短い値（300 など）も、作業の途中で同じように死ぬ。

規約（kanban-collaboration）に「1800 を渡す」と書き、毎分の `runtime-guard` が
あとから直しているが、**どちらも AI の手前で止められない。**
- 規約はコンテキストの遠くにあり、モデルが見ているのはツールのスキーマ
  （`"type": "integer"`）なので、「上限なしのつもりで 0」を繰り返し作る
- 見回りは1分おきなので、15秒で死ぬカードには間に合わない

そこで **`kanban_create` が実行される直前**（`pre_tool_call`）に、渡された値を直す。
AI が何を渡しても、短すぎる上限はカードに書き込まれない。

- 値が無い（None）ときは触らない。上限なしは Hermes の既定どおりで、見回りの扱いとも揃える
- 引き上げるだけで、下げない（長い作業のために上げた値はそのまま）
- CLI（`hermes kanban create --max-runtime`）はこのフックを通らないので、見回りが引き続き直す
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

TOOLS = ("kanban_create",)
FIELD = "max_runtime_seconds"
# runtime_guard.py と同じ既定。変えるときは両方を揃える。
DEFAULT_SECONDS = int(os.environ.get("KANBAN_DEFAULT_MAX_RUNTIME", "1800"))


def _as_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _on_pre_tool_call(tool_name: str = "", args: Any = None, **_: Any) -> Optional[Dict[str, Any]]:
    if tool_name not in TOOLS or not isinstance(args, dict) or args.get(FIELD) is None:
        return None
    given = _as_int(args.get(FIELD))
    if given is not None and given >= DEFAULT_SECONDS:
        return None
    logger.warning("[runtime-floor] %s の %s=%r は短すぎる → %s に引き上げた",
                   tool_name, FIELD, args.get(FIELD), DEFAULT_SECONDS)
    return {"action": "modify", "args": {FIELD: DEFAULT_SECONDS}}


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
