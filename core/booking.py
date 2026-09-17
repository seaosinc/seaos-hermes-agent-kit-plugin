"""アクセスゲート（booking-gate）の検証とゲスト操作。

**配るのは配布物の仕事**（`templates/booking-gate/` → `dist/operator/`）。
ここに残るのは公式に無い2つだけ——doctor から呼ぶ検証と、ゲストのアクセス許可。
"""

from __future__ import annotations

import json
import os
import platform_ops
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import yaml

import hermes
from paths import hermes_home, profile_dir

Log = Callable[[str], None]


def booking_home() -> Path:
    return hermes_home() / "booking-gate"


def config() -> Dict:
    path = booking_home() / "config.yaml"
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def gate_profile() -> str:
    """ゲートウェイが動くプロファイル。

    gateway の HERMES_HOME はプロファイル配下なので、**プラグインもその
    プロファイルの plugins/ に置かないと発見されない。**
    """
    return str(config().get("profile") or "operator")


def plugin_dir() -> Path:
    return profile_dir(gate_profile()) / "plugins" / "booking-gate"


def guest(args: List[str]) -> Tuple[int, str]:
    """ゲストのアクセス許可。実体は配布済みの Python（引数だけで完結する）。"""
    impl = profile_dir(gate_profile()) / "scripts" / "booking_guest.py"
    if not impl.is_file():
        return 1, f"guest コマンドが未配布: {impl}（update を先に実行）"
    env = dict(os.environ, HERMES_HOME=str(hermes_home()))
    proc = subprocess.run(
        ["python3", str(impl), *args], capture_output=True, text=True,
        stdin=subprocess.DEVNULL, env=env,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def revoke_all(log: Optional[Log] = None) -> int:
    """pairing に残る「このゲートが出した承認」を消す（ゲートを外すとき）。"""
    hh = hermes_home()
    removed = 0
    patterns = (
        "profiles/*/platforms/pairing/slack-approved.json",
        "profiles/*/pairing/slack-approved.json",
    )
    for pattern in patterns:
        for path in hh.glob(pattern):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            left = {
                k: v for k, v in data.items()
                if not (isinstance(v, dict) and v.get("source") == "booking-gate")
            }
            if len(left) != len(data):
                path.write_text(json.dumps(left, indent=2, ensure_ascii=False), encoding="utf-8")
                removed += 1
                if log:
                    log(f"✓ {path.parent.parent.name}: このゲート由来の承認を削除")
    return removed


def _card_status(task_id: str) -> Optional[str]:
    db = hermes_home() / "kanban.db"
    if not db.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return row[0] if row else None
        finally:
            con.close()
    except sqlite3.Error:
        return None


def check(log: Optional[Log] = None) -> bool:
    """doctor から呼ばれる検証。**配置・有効化・稼働・鮮度・整合**を順に見る。"""
    say: Log = log or (lambda _l: None)
    home = booking_home()
    if not (home / "config.yaml").is_file():
        say("= 未導入（update で配布される）")
        return True

    ok = True
    prof = gate_profile()
    cfg = config()

    # --- ゲートそのもの
    if (plugin_dir() / "plugin.yaml").is_file():
        say(f"✓ プラグインが配置済み ({prof})")
    else:
        say("✗ プラグインが無い → update")
        ok = False

    # **「認識されている」だけでは足りない。** プラグインは既定で無効のまま入る。
    _code, listed = hermes.run(["-p", prof, "plugins", "list"])
    row = next((l for l in listed.splitlines() if "booking-gate" in l), "")
    if not row:
        say("✗ Hermes がプラグインを認識していない")
        ok = False
    elif "not enabled" in row:
        say(f"✗ プラグインが無効 → hermes -p {prof} plugins enable booking-gate")
        ok = False
    else:
        say("✓ プラグインが有効")

    # 配置と有効化が済んでいても、**ゲートウェイを再読み込みするまでフックは動かない。**
    # プラグインのログは gateway のログに出ないので、痕跡ファイルで確かめる。
    ev = home / "gate-loaded.json"
    if ev.is_file():
        try:
            pid = int(json.loads(ev.read_text(encoding="utf-8"))["pid"])
            if not platform_ops.pid_alive(pid):
                raise ProcessLookupError(pid)
            say(f"✓ ゲートが動いている（pid {pid}）")
        except Exception:  # noqa: BLE001
            say("✗ ゲートが動いていない → gateway restart")
            ok = False
    else:
        say("✗ ゲートが一度も読み込まれていない → gateway restart")
        ok = False

    _c, crons = hermes.run(["-p", prof, "cron", "list"])
    if "booking-sync" in crons:
        say("✓ ポーラーが cron に登録済み")
    else:
        say("✗ ポーラーが未登録 → install")
        ok = False

    _c, status = hermes.run(["-p", prof, "cron", "status"])
    if "Gateway is running" in status:
        say("✓ cron スケジューラが動いている")
    else:
        say("✗ cron が動いていない（ゲートウェイが止まっている）")
        ok = False

    # allow-all が開いているとゲートを迂回して全員通る
    envf = profile_dir("operator") / ".env"
    allow_all = False
    if envf.is_file():
        for line in envf.read_text(encoding="utf-8").splitlines():
            if line.upper().startswith("SLACK_ALLOW_ALL_USERS="):
                allow_all = line.split("=", 1)[1].strip().strip("\"'").lower() in ("true", "1", "yes")
    if allow_all:
        say("✗ SLACK_ALLOW_ALL_USERS が有効 → ゲートを迂回して全員通る")
        ok = False
    else:
        say("✓ allow-all は閉じている")

    # --- アクセス許可表の鮮度・整合
    try:
        table = json.loads((home / "reservations.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        say(f"✗ アクセス許可表が読めない: {exc} → オーナー以外は全員通らない")
        return False

    now = datetime.now(timezone.utc).astimezone()
    limit = int(cfg.get("stale_after_minutes", 5))
    age = now - datetime.fromisoformat(table["generated_at"])
    if age > timedelta(minutes=limit):
        say(f"✗ アクセス許可表が {int(age.total_seconds() // 60)} 分前のまま → ポーラーを確認")
        ok = False
    else:
        say(f"✓ アクセス許可表は新鮮（{int(age.total_seconds())}秒前 / 枠 {len(table.get('slots', []))}）")

    # 無期限のアクセス許可は、消し忘れるとオーナーと同じ強さになる
    try:
        grants = json.loads((home / "guests.json").read_text(encoding="utf-8")).get("grants", [])
    except Exception:  # noqa: BLE001
        grants = []
    for g in grants:
        # 人の許可なら U…、チャンネルの許可なら C…（そのメンバー全員に展開される）
        key = g.get("slack_user_id") or g.get("slack_channel_id") or "?"
        if g.get("slack_channel_id"):
            key = f"#{g.get('channel_name') or key} のメンバー"
        tid = (g.get("task_id") or "").strip()
        if tid:
            # **archive されるまで切れない。** 切るのは人の判断なので止めはしないが、見せる。
            if _card_status(tid) == "done":
                say(
                    f"! done のまま畳まれていないカードの許可: {key} "
                    f"{g.get('label', '')}（{tid}） → 話が終わっているなら archive"
                )
            continue
        if g.get("end"):
            continue
        who = g.get("requested_by") or "不明"
        if g.get("unlimited"):
            say(f"! 無期限のアクセス許可: {key} {g.get('label', '')}（指示: {who}）")
        else:
            # 終わり方が無い＝いつまでも残る。**意図された無期限とは別に扱う。**
            say(f"✗ 終わり方の無いアクセス許可: {key} {g.get('label', '')}")
            ok = False

    # 承認の残骸: このゲート由来なのに、いまの枠に居ない人
    grace = cfg.get("grace") or {}

    def active(slot: Dict, extra: int = 0) -> bool:
        start = datetime.fromisoformat(slot["start"]) - timedelta(
            minutes=int(grace.get("before_minutes", 5)))
        if now < start:
            return False
        if not slot.get("end"):
            return True
        after = int(grace.get("after_minutes", 5)) + extra
        return now <= datetime.fromisoformat(slot["end"]) + timedelta(minutes=after)

    slots = table.get("slots", [])
    live = {s["slack_user_id"] for s in slots if active(s)}
    # 承認は案内猶予のぶん長く残る。**これは残骸ではない。**
    window = int(cfg.get("notice_window_minutes", 10))
    tolerated = {s["slack_user_id"] for s in slots if active(s, window)}

    phome = hermes_home() if prof == "default" else hermes_home() / "profiles" / prof
    legacy = phome / "pairing"
    pdir = legacy if legacy.is_dir() and any(legacy.iterdir()) else phome / "platforms" / "pairing"
    try:
        approved = json.loads((pdir / "slack-approved.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        approved = {}
    stale = [
        k for k, v in approved.items()
        if isinstance(v, dict) and v.get("source") == "booking-gate" and k not in tolerated
    ]
    if stale:
        say(f"✗ 許可が終わったのに承認が残っている: {', '.join(stale)}")
        ok = False
    else:
        say(f"✓ 承認は許可と一致（いま話せるゲスト {len(live)} 人）")

    return ok
