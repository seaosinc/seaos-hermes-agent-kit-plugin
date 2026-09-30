"""どの役を入れるか。**外した役だけを記録する。**

選んだ役を記録する形（opt-in）にしなかったのは、**後から増える役が黙って
入らなくなる**から。recruiter が作った役は、作った直後の反映で入ってこないと
仕事にならない。配られてくる新しい役も同じで、入らないまま担当の候補にも
出ないと、足したことに誰も気づかない。

外す（opt-out）なら、何もしなければ全役が入る——これまでと同じ振る舞いで、
既に動いている環境は何も変わらない。

**外せない役がある。** 窓口（operator）と詰まりを解く役（fixer）は、
板の仕組みそのものが前提にしている（fixer は kanban の orchestrator で、
operator には定期実行と共有記憶の起動が載る）。配置表の `essential` で示す。

**入れると決めたときだけ入る役もある**（配置表の `opt_in`）。影武者（shadow）は
本人のユーザートークンを預かるので、黙って全員に入れない。こちらは入れた役を
`enabled` に記録する。
"""

from __future__ import annotations

import json
from typing import List

from paths import selection_file


class SelectionError(RuntimeError):
    """呼び手に見せる、原因の分かる失敗。"""


def _read(key: str) -> List[str]:
    """記録の一覧。**読めなければ空の扱い**にする。

    壊れたファイルで全役が消えるより、全役が入るほうが戻しやすい
    （入れると決めた役は、入らないほうが安全側）。
    """
    path = selection_file()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return []
    names = data.get(key) if isinstance(data, dict) else None
    return sorted({str(n) for n in names}) if isinstance(names, list) else []


def disabled() -> List[str]:
    """外した役の名前。"""
    return _read("disabled")


def opted_in() -> List[str]:
    """入れると決めた役（`opt_in` の役）の名前。"""
    return _read("enabled")


def is_enabled(name: str, *, opt_in: bool = False) -> bool:
    return name in opted_in() if opt_in else name not in disabled()


def set_enabled(name: str, enabled: bool, *, essential: bool = False, opt_in: bool = False) -> bool:
    """入れる／外すを記録する。変わったら True。

    **記録するだけで、実機には触らない。** プロファイルを消すか残すかは
    呼び手が決める（記憶とセッションは戻せないので、ここで勝手に消さない）。
    """
    if not enabled and essential:
        raise SelectionError(f"{name} は外せません（チームの仕組みが前提にしている役です）")
    off, on = set(disabled()), set(opted_in())
    before = (set(off), set(on))
    if opt_in:
        (on.add if enabled else on.discard)(name)
    elif enabled:
        off.discard(name)
    else:
        off.add(name)
    if (off, on) == before:
        return False
    data: dict = {"disabled": sorted(off)}
    if on:
        data["enabled"] = sorted(on)
    path = selection_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def forget(name: str) -> None:
    """役そのものを消したときに、記録からも外す（同名で作り直したら入るように）。"""
    if name in disabled():
        set_enabled(name, True)
