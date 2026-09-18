"""runtime-floor — カードを作る直前に、そのままでは死ぬ値を直す。

**AI の手前で止める。** 規約（kanban-collaboration）に書いてあっても、モデルが見て
いるのはツールのスキーマなので、同じ間違いが繰り返し作られる。見回りの cron は
1分おきで、15秒で死ぬカードには間に合わない。そこで `kanban_create` が実行される
直前（`pre_tool_call`）に、渡された値そのものを直す。

いま直しているのは2つ。

1. **実行時間の上限（`max_runtime_seconds`）**

   `0` は「無制限」ではなく「0秒」である。Hermes は値の有無で判定するので、0 が
   入ったカードは起動から15秒で強制終了され、2回失敗すると `gave_up` になって
   二度と動かない。短い値（300 など）も、作業の途中で同じように死ぬ。

   ・値が無い（None）ときは触らない。上限なしは Hermes の既定どおり
   ・引き上げるだけで、下げない（長い作業のために上げた値はそのまま）

2. **スキルの指定（`skills`）**

   **スキルはプロファイルごとに配られる。** 自分の手元にあるスキル名をカードに
   書いても、担当のプロファイルに同じものが無ければ、担当は起動時にクラッシュして
   止まる。実際に起きた——窓口が自分用に作ったスキルの名前をカードへ必須指定し、
   受け取った役が一度も動けなかった。

   担当が決まっているカードは、その役のスキル置き場を見る。担当が決まっていない
   （triage に置く）カードは、**全部の役が持っているスキルだけ**を残す——
   分解器がどの役へ振るか、この時点では分からないからである。

   落とした名前はログに出す。**カードは作られる。** 指定が消えるだけで、担当は
   自分に配られたスキルで仕事を進められる。

CLI（`hermes kanban create`）はこのフックを通らないので、そちらは見回りが直す。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def _home() -> Path:
    """共有の HOME。**プラグインは役のプロファイルの中で走る**ので、そのときは2つ上。"""
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    return home.parent.parent if home.parent.name == "profiles" else home


def _skills_of(profile: str) -> set:
    d = _home() / "profiles" / profile / "skills"
    try:
        return {p.name for p in d.iterdir() if p.is_dir()}
    except OSError:
        return set()


def _profiles() -> List[str]:
    try:
        return [p.name for p in (_home() / "profiles").iterdir()
                if p.is_dir() and not p.name.startswith(".")]
    except OSError:
        return []


def _available(assignee: Optional[str]) -> Optional[set]:
    """そのカードで指定してよいスキル。分からなければ None（触らない）。"""
    if assignee:
        got = _skills_of(assignee)
        return got or None
    names = [n for n in _profiles()]
    sets = [s for s in (_skills_of(n) for n in names) if s]
    if not sets:
        return None
    # 担当が決まっていないなら、どの役へ振られても読めるものだけを残す
    return set.intersection(*sets)


def _keep_known_skills(args: Dict[str, Any]) -> Optional[List[str]]:
    given = args.get("skills")
    if not isinstance(given, list) or not given:
        return None
    allowed = _available(args.get("assignee") or args.get("profile"))
    if allowed is None:
        return None
    kept = [s for s in given if s in allowed]
    return kept if len(kept) != len(given) else None


def _on_pre_tool_call(tool_name: str = "", args: Any = None, **_: Any) -> Optional[Dict[str, Any]]:
    if tool_name not in TOOLS or not isinstance(args, dict):
        return None

    fixed: Dict[str, Any] = {}

    if args.get(FIELD) is not None:
        given = _as_int(args.get(FIELD))
        if given is None or given < DEFAULT_SECONDS:
            logger.warning("[runtime-floor] %s の %s=%r は短すぎる → %s に引き上げた",
                           tool_name, FIELD, args.get(FIELD), DEFAULT_SECONDS)
            fixed[FIELD] = DEFAULT_SECONDS

    kept = _keep_known_skills(args)
    if kept is not None:
        dropped = [s for s in args.get("skills") or [] if s not in kept]
        logger.warning("[runtime-floor] 担当が持っていないスキルを外した: %s（担当=%s）",
                       ", ".join(dropped), args.get("assignee") or "未定")
        fixed["skills"] = kept

    return {"action": "modify", "args": fixed} if fixed else None


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
