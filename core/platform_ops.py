"""OS で違うことだけを、ここに閉じる。

**他所に platform 分岐を書かないこと。** 役の定義・生成・配布は全 OS 共通で、
違うのは3つだけ:

  1. 常駐のさせ方（ゲートウェイを上げ続ける作法）
  2. コマンドの置き場（PATH に載せる作法）
  3. 自動起動の登録

対応:
  macOS   **素のプロセス**として走らせる。launchd（plist）は使わない——
          plist は `hermes gateway start / restart` が再生成するので、そこへ
          書いた HERMES_PROFILE が消える。消えるとカードの発言者が全部
          `worker` になって誰が言ったか追えなくなる。
          **落ちても誰も上げない。** 上げ直すのは人（か、このコマンド）。
  Windows 素のプロセス＋Scheduled Task（ログオン時の自動起動）。
  Linux   AWS の箱（Ubuntu）で自分自身を動かすためだけに残す。systemd の
          user unit。HERMES_PROFILE は drop-in に置く（unit の再生成で消えない）。
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable, List, Optional

import hermes
from paths import hermes_home, kit_root, os_kind, profile_dir

Log = Callable[[str], None]

# 手が空くのを待つ上限（秒）。**待ちには終わりを付ける。**
IDLE_WAIT = int(os.environ.get("GATEWAY_IDLE_WAIT", "1800"))


# ── ゲートウェイ ─────────────────────────────────────────────────────────

def running_cards() -> int:
    """走行中のカード。**再起動は走っている作業を落とす**ので、叩く前に見せる。"""
    total = 0
    for status in ("running", "review"):
        code, out = hermes.run(["kanban", "list", "--status", status, "--json"])
        if code != 0:
            continue
        try:
            total += len(json.loads(out))
        except Exception:  # noqa: BLE001
            pass
    return total


def gateway_pid(profile: str) -> Optional[int]:
    """素のプロセスとして走っているゲートウェイの PID。"""
    pattern = f"hermes --profile {profile} gateway run"
    if os_kind() == "win32":
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | "
             f"Where-Object {{ $_.CommandLine -like '*{pattern}*' }} | "
             "Select-Object -First 1 -ExpandProperty ProcessId"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        value = proc.stdout.strip()
        return int(value) if value.isdigit() else None
    proc = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)
    first = proc.stdout.split()
    return int(first[0]) if first else None


def _start_plain(profile: str, log: Optional[Log] = None) -> bool:
    """素のプロセスとして起こす（macOS / Windows 共通）。"""
    logs = profile_dir(profile) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    out = (logs / "gateway-stdout.log").open("ab")

    env = dict(os.environ)
    # **HERMES_PROFILE をプロセスの環境に入れて起こす。** kanban_comment の
    # author がこれを読む。無いと発言者が全部 worker になる。
    env["HERMES_PROFILE"] = profile

    exe = shutil.which("hermes")
    if not exe:
        if log:
            log("✗ hermes が PATH に無い")
        return False

    # **消えない場所で起こす。** ゲートウェイは自分の cwd を握り続けるので、
    # そこが後から削除されると os.getcwd() が落ち、以後どの発言でも
    # システムプロンプトの組み立てで例外になる（実際にカードの作業部屋を
    # 掴んだまま、そのカードが片付いて消えた）。$HOME なら消えない。
    kwargs: dict = {
        "cwd": str(Path.home()),
        "env": env,
        "stdout": out,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
    }
    if os_kind() == "win32":
        # 親が死んでも生き残らせる（コンソールを切り離す）
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    subprocess.Popen([exe, "--profile", profile, "gateway", "run"], **kwargs)

    for _ in range(10):
        time.sleep(2)
        if gateway_pid(profile):
            return True
    return False


def _restart_plain(profile: str, log: Optional[Log] = None) -> bool:
    pid = gateway_pid(profile)
    if pid:
        _terminate(pid)
        for _ in range(10):
            time.sleep(1)
            if not gateway_pid(profile):
                break
        # 落ちきらなければ強く止める。**二重に走らせないほうが大事**
        # （ディスパッチャが二重になると、同じカードを2回取る）。
        stubborn = gateway_pid(profile)
        if stubborn:
            _kill(stubborn)
            time.sleep(1)
    return _start_plain(profile, log=log)


def _terminate(pid: int) -> None:
    if os_kind() == "win32":
        subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def _kill(pid: int) -> None:
    if os_kind() == "win32":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def _restart_systemd(profile: str, log: Optional[Log] = None) -> bool:
    unit = Path.home() / ".config/systemd/user" / f"hermes-gateway-{profile}.service"
    if not unit.is_file():
        if log:
            log(f"✗ {profile} の unit が無い（hermes gateway install -p {profile}）")
        return False
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    for _ in range(3):
        if hermes.run(["gateway", "restart", "-p", profile])[0] == 0:
            return True
        time.sleep(5)
    return False


def restart_gateway(profile: str, log: Optional[Log] = None) -> bool:
    """OS に合った作法で再起動する。呼ぶ側はこの1つだけ知っていればよい。"""
    n = running_cards()
    if n > 0 and log:
        log(f"! running / review が {n} 件ある。再起動すると落ちる")

    kind = os_kind()
    if kind == "linux":
        ok = _restart_systemd(profile, log=log)
    else:
        ok = _restart_plain(profile, log=log)

    if log:
        if ok:
            pid = gateway_pid(profile)
            log(f"+ {profile} を再起動した" + (f"（pid {pid}）" if pid else ""))
        else:
            log(f"✗ {profile} の再起動に失敗")
    return ok


def restart_when_idle(profile: str, log: Optional[Log] = None) -> bool:
    """走行中が無くなってから再起動する。**誰も落とさない。**

    構成を書き換える役は、書き換えたあとゲートウェイを起こし直さないと反映
    されない。ところが**ワーカーはゲートウェイの子**なので、カードの中から
    叩くと自分の実行ごと落ちる。手が空くまで待てば誰も落ちない。

    **待ちには終わりを付ける。** 混んだ板では手が空く瞬間が来ないことがあり、
    黙って待ち続けると反映されないまま誰も気づかない——それが一番悪い。
    """
    logs = profile_dir(profile) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    trail = logs / "gateway-restart.log"

    waited = 0
    while waited < IDLE_WAIT:
        if running_cards() == 0:
            break
        time.sleep(15)
        waited += 15

    left = running_cards()
    stamp = time.strftime("%F %T")
    with trail.open("a", encoding="utf-8") as fh:
        if left > 0:
            fh.write(f"{stamp} 手が空かないまま {IDLE_WAIT}秒 経ったので再起動する"
                     f"（running / review が {left} 件残る）\n")
        else:
            fh.write(f"{stamp} 手が空いたので再起動する（{waited}秒 待った）\n")
    return restart_gateway(profile, log=log)


# ── コマンドの置き場 ─────────────────────────────────────────────────────

def command_target() -> Path:
    """`kit` コマンドを置く場所。"""
    if os_kind() == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / "hermes-kit"
    return Path.home() / ".local" / "bin"


def link_command(log: Optional[Log] = None) -> Path:
    """PATH から叩けるようにする。

    macOS / Linux は**シンボリックリンク**（pull すれば本体も入れ替わる）。
    Windows はシンボリックリンクに管理者権限が要ることがあるので、
    **バッチのラッパを書く**（中身は python を呼ぶだけなので、pull で追随する）。
    """
    target = command_target()
    target.mkdir(parents=True, exist_ok=True)
    entry = kit_root() / "core" / "cli.py"

    if os_kind() == "win32":
        path = target / "kit.cmd"
        path.write_text(
            "@echo off\r\n"
            f'python "{entry}" %*\r\n',
            encoding="utf-8",
        )
        if log:
            log(f"+ {path}")
            log(f"  PATH に {target} を足すこと")
        return path

    path = target / "kit"
    if path.is_symlink() or path.exists():
        path.unlink()
    path.symlink_to(entry)
    path.chmod(0o755)
    if log:
        log(f"+ {path} → {entry}")
    return path


def unlink_command(log: Optional[Log] = None) -> bool:
    target = command_target()
    removed = False
    for name in ("kit", "kit.cmd"):
        path = target / name
        if path.is_symlink() or path.is_file():
            path.unlink()
            removed = True
            if log:
                log(f"- {path}")
    return removed


# ── 自動起動 ─────────────────────────────────────────────────────────────

def autostart_hint() -> str:
    """ログオン時にゲートウェイを上げる作法（OS ごと）。"""
    kind = os_kind()
    if kind == "win32":
        return (
            "Scheduled Task に登録する:\n"
            '  schtasks /Create /SC ONLOGON /TN "hermes-gateway" '
            '/TR "hermes --profile operator gateway run"'
        )
    if kind == "linux":
        return (
            "systemd の user unit を使う（hermes gateway install -p operator）。\n"
            "**loginctl enable-linger が要る**——無いとログアウトで user systemd ごと落ちる。"
        )
    return (
        "macOS は素のプロセスで走らせる（launchd は使わない。plist を "
        "hermes 側が再生成して HERMES_PROFILE が消えるため）。\n"
        "落ちたら kit gateway restart で上げ直す。"
    )
