"""カードの保留。**作るが、誰にも回さない**カードを1つの操作にまとめる。

オーナーが不在のあいだ、許可の無い人から預かった用件は、オーナーが戻って判断するまで
進めない。カードにはしておく（何を頼まれたかを板に残す）が、分解にも担当にも回さない。

  hold    担当を付けずに、止めた状態（blocked / needs_input）で作る。保留の記録に載せる
  held    保留中のカードの一覧
  resume  保留を解く。同じ中身で triage にカードを作り直し、保留のカードは畳む
  drop    保留のまま畳む（要らなかった）

**止めた状態で作るのは、Hermes の `--initial-status blocked` を使う。** 担当が無いので
ディスパッチャは拾わず、キットの見張り（ready だけを見る）も手を出さない。
保留から出すときに「作り直し」にするのは、止まったカードを triage へ戻す口が Hermes に無いため。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Tuple

import hermes
from paths import hermes_home

REASON = "オーナーの判断待ち（保留）"


class CardError(RuntimeError):
    """呼び手に見せる、原因の分かる失敗。"""


def held_file() -> Path:
    return hermes_home() / "seaos-kit" / "held.json"


def _load() -> dict:
    try:
        data = json.loads(held_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    path = held_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _json(out: str):
    """`hermes ... --json` の出力から JSON を取り出す（警告が前に混ざることがある）。"""
    start = min((i for i in (out.find("{"), out.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise CardError(f"Hermes の応答を読めませんでした: {out.strip()[-300:]}")
    try:
        value, _ = json.JSONDecoder().raw_decode(out[start:])
    except ValueError as exc:
        raise CardError(f"Hermes の応答を読めませんでした: {exc}") from exc
    return value


def hold(title: str, body: str, requester: str, *, note: str = "") -> dict:
    """保留のカードを作る。返すのは作ったカード（id / title / created_by …）。"""
    if not requester:
        raise CardError("依頼者（--requester）が要ります。オーナーが戻ったとき、誰の用件か分からなくなります")
    text = body.rstrip() + f"\n\n依頼者: <@{requester}>\n［{REASON}。オーナーが進めると決めるまで着手しない］"
    code, out = hermes.run(["kanban", "create", title, "--body", text, "--created-by", requester,
                            "--initial-status", "blocked", "--json"])
    if code != 0:
        raise CardError(f"カードを作れませんでした: {out.strip()[-300:]}")
    task = _json(out)
    task_id = task.get("id")
    if not task_id:
        raise CardError("作ったカードの id が分かりませんでした")
    data = _load()
    data[task_id] = {"title": title, "requester": requester, "held_at": time.time(), "note": note}
    _save(data)
    return task


def held() -> List[dict]:
    """保留中のカード。古い順。"""
    return [{"id": k, **v} for k, v in sorted(_load().items(), key=lambda kv: kv[1].get("held_at", 0))]


def _show(task_id: str) -> dict:
    code, out = hermes.run(["kanban", "show", task_id, "--json"])
    if code != 0:
        raise CardError(f"カード {task_id} を読めませんでした: {out.strip()[-300:]}")
    return (_json(out) or {}).get("task") or {}


def resume(task_id: str) -> str:
    """保留を解いて、分解（triage）に回す。返すのは新しいカードの id。"""
    data = _load()
    if task_id not in data:
        raise CardError(f"{task_id} は保留のカードではありません（seaos-kit card held で一覧）")
    task = _show(task_id)
    body = (task.get("body") or "").replace(f"［{REASON}。オーナーが進めると決めるまで着手しない］", "").rstrip()
    code, out = hermes.run(["kanban", "create", task.get("title") or data[task_id]["title"],
                            "--body", body + f"\n\n（保留していた {task_id} を、オーナーの判断で進める）",
                            "--created-by", data[task_id]["requester"], "--triage", "--json"])
    if code != 0:
        raise CardError(f"カードを作り直せませんでした: {out.strip()[-300:]}")
    new_id = _json(out).get("id") or ""
    hermes.run(["kanban", "archive", task_id])
    data.pop(task_id, None)
    _save(data)
    return new_id


def drop(task_id: str) -> None:
    """保留のまま畳む。"""
    data = _load()
    if task_id not in data:
        raise CardError(f"{task_id} は保留のカードではありません（seaos-kit card held で一覧）")
    code, out = hermes.run(["kanban", "archive", task_id])
    if code != 0:
        raise CardError(f"カード {task_id} を畳めませんでした: {out.strip()[-300:]}")
    data.pop(task_id, None)
    _save(data)


def describe(cards: List[dict]) -> Tuple[str, ...]:
    return tuple(f"{c['id']}  {c.get('title')}（依頼者 {c.get('requester')}）" for c in cards)
