"""OS で違うことだけを、ここに閉じる。

**platform 分岐はこのファイルにだけ書く。** 役の定義・生成・配布は全 OS 共通で、
違うのは3つだけ:

  1. 常駐のさせ方（ゲートウェイを上げ続ける作法）
  2. コマンドの置き場（PATH に載せる作法）
  3. 自動起動の登録

**ゲートウェイは1台に1つ（multiplex）。** Hermes は1つの gateway プロセス（ホスト）が
全プロファイルを受け持つ形に一本化した（hermes_cli/gateway_multiplex_mode.py 冒頭）。
役ごとのプロセスはもう無い。役ごとの操作は、ホストに頼んでその役だけを外す・載せ直す
（`hermes -p <役> gateway restart / stop`）。ホストそのものの上げ下げだけが OS で違う:

  macOS   ホストを**素のプロセス**として走らせる（`hermes gateway run`）。launchd は使わない
          （Hermes Desktop も素のプロセスで起こす。二重に監督させない）。
          **落ちても誰も上げない。** 上げ直すのは人（か、このコマンド）。
  Windows 素のプロセス＋Scheduled Task（ログオン時の自動起動）。
  Linux   AWS の箱（Ubuntu）で自分自身を動かすためだけに残す。systemd の user unit
          （`hermes gateway install` が作る `hermes-gateway.service`）があればそれに任せ、
          無ければ素のプロセス。

**ホストは誰の名前も持たずに起こす。** 以前は役ごとのプロセスに HERMES_PROFILE を
入れて起こしていた（カードの発言者を役名にするため）。いまは Hermes が役ごとに
名前を付ける——会話のターンは役の HERMES_HOME を当てて走り（gateway/run.py の
_profile_runtime_scope）、カードのワーカーにはディスパッチャが HERMES_PROFILE を
入れる（hermes_cli/kanban_db_dispatch.py）。逆にホストが HERMES_PROFILE を持つと、
**全役の子プロセスにその名前が漏れる**（HERMES_PROFILE は役ごとに剥がされない
グローバルな変数で、`current_profile_name()` は環境変数を最優先する）。別の窓口の
ターンで打った `hermes kanban notify-subscribe` が operator 名義になる。
"""

from __future__ import annotations

import json
import os
import sys
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import hermes
from paths import hermes_home, kit_root, os_kind, profile_dir

Log = Callable[[str], None]

# 手が空くのを待つ上限（秒）。**待ちには終わりを付ける。**
IDLE_WAIT = int(os.environ.get("GATEWAY_IDLE_WAIT", "1800"))

# ホストが起きて、全役を載せ終えるまで待つ上限（秒）。Slack への接続や MCP の発見を
# 含むので、プロセスが立つより長くかかる。
HOST_BOOT_WAIT = 90

# 役が載る・外れるのを待つ上限（秒）。ホストが即答できなくても、**30秒ごとの見直し**
# （gateway/run_profile_reconcile.py の _PROFILE_RESCAN_INTERVAL_SECS）で追いつくので、
# それより少し長く待つ。
SERVE_WAIT = 45

# `hermes -p <役> gateway restart / stop` の打ち切り（秒）。ホストへの依頼は8秒で
# 返るが、**条件次第で `gateway run` を前面で始めて戻らない**ので、終わりを付ける。
LIFECYCLE_TIMEOUT = 120

# ホストに渡さない環境変数。**ホストは誰の名前も持たずに起こす**（→ 冒頭）。
# カードの中からこのコマンドが叩かれると、ワーカーに付いた名前・板・作業場所が
# 環境に載っている。そのまま起こすと、ホストが全役ぶんその札を下げて走る。
_HOST_ENV_DROP = ("HERMES_PROFILE", "HERMES_PROFILE_NAME", "HERMES_TENANT",
                  "HERMES_SESSION_SOURCE", "TERMINAL_CWD", "_HERMES_GATEWAY")
_HOST_ENV_DROP_PREFIX = ("HERMES_KANBAN_", "HERMES_SESSION_")


# ── ゲートウェイ ─────────────────────────────────────────────────────────

def running_cards() -> int:
    """走行中のカード。**再起動は走っている作業を落とす**ので、叩く前に見せる。

    **自分のカードは数えない。** カードの中から `--when-idle` を叩くと、自分が
    走っている限り 0 にならず、上限まで待ち続けていた。
    """
    own = (os.environ.get("HERMES_KANBAN_TASK") or "").strip()
    total = 0
    for status in ("running", "review"):
        code, out = hermes.run(["kanban", "list", "--status", status, "--json"])
        if code != 0:
            continue
        try:
            rows = json.loads(out)
        except Exception:  # noqa: BLE001
            continue
        total += sum(1 for r in rows if not (own and isinstance(r, dict) and r.get("id") == own))
    return total


def pid_alive(pid: int) -> bool:
    """その PID が生きているか。

    **`os.kill(pid, 0)` を使わない。** POSIX では生存確認だが、**Windows では
    TerminateProcess になる**——CPython の os.kill は CTRL_C_EVENT 以外を
    受け取ると、その値を終了コードにしてプロセスを終わらせる。
    生存を確かめたつもりでゲートウェイを殺す。
    """
    if os_kind() == "win32":
        proc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        return str(pid) in proc.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@dataclass(frozen=True)
class Host:
    """いま動いているホスト（1台に1つの gateway プロセス）。"""

    pid: int
    home: Path                # 起こしたプロファイルの HERMES_HOME
    profiles: tuple           # 受け持っている役（served_profiles）

    def serves(self, profile: str) -> bool:
        return profile in self.profiles

    def launched_by(self, profile: str) -> bool:
        """その役がホストを起こしたか。**起こした役はホストから外せない**（外すと全役が落ちる）。"""
        try:
            return self.home.resolve() == profile_dir(profile).resolve()
        except OSError:
            return False


def _host_lock_dir() -> Path:
    """ホストの記録（host-gateway.json）の置き場。**Hermes と同じ規則で引く**
    （gateway/status.py の _get_lock_dir）。HERMES_HOME ではなく OS ユーザーごとに1つ。"""
    override = os.environ.get("HERMES_GATEWAY_LOCK_DIR")
    if override:
        return Path(override)
    state = os.environ.get("XDG_STATE_HOME") or ""
    base = Path(state) if os.path.isabs(state) else Path.home() / ".local" / "state"
    return base / "hermes" / "gateway-locks"


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  （無い・書きかけ・壊れている、はどれも「記録なし」）
        return {}
    return data if isinstance(data, dict) else {}


def host() -> Optional[Host]:
    """いま動いているホスト。無ければ None。

    **pid と受け持ちはホストの記録から読む**（gateway/host_rendezvous.py の
    host-gateway.json）。ホストは受け持ちが変わるたびにここを書き直す
    （gateway/run_adapters.py の _record_served_profiles）。プロセスの argv を
    探すやり方は使えない——ホストの argv に役の名前は出ない。
    記録が残っていても pid が死んでいれば「動いていない」。
    """
    record = _read_json(_host_lock_dir() / "host-gateway.json")
    pid = record.get("pid")
    if not isinstance(pid, int) or pid <= 0 or not pid_alive(pid):
        return None
    home = Path(record.get("home") or hermes_home())
    profiles = record.get("profiles")
    if not isinstance(profiles, list):
        # 古い記録には受け持ちが無い。ホスト自身の状態ファイルから補う。
        profiles = _read_json(home / "gateway_state.json").get("served_profiles") or []
    return Host(pid=pid, home=home, profiles=tuple(str(p) for p in profiles))


def gateway_pid(profile: str) -> Optional[int]:
    """その役を受け持っているホストの PID。受け持たれていなければ None。

    **役ごとのプロセスは無い。** 返るのは全役共通のホストの PID で、役を止めても
    この値のプロセスは止まらない（受け持ちから外れて None になる）。
    """
    h = host()
    return h.pid if h and h.serves(profile) else None


def is_parked(profile: str) -> bool:
    """その役が止めてあるか。**止めた印は残り続ける**（ホストを起こし直しても載らない）。
    外すのは `hermes -p <役> gateway start / restart`（hermes_cli/gateway_profile_lifecycle.py）。"""
    return (profile_dir(profile) / "gateway.parked").exists()


def adapter_states(profile: str) -> dict:
    """その役のアダプタ（Slack など）の状態。**記録があるものだけ**を返す。

    ホストの状態ファイルは、役のアダプタを `<役>:<platform>` の名前で持つ
    （gateway/run_adapters.py の _configure_profile_adapter）。書かれるのは主に
    切れた・落ちたとき（gateway/platforms/base.py）なので、**記録が無いのは異常なし**と読む。
    """
    h = host()
    if not h:
        return {}
    platforms = _read_json(h.home / "gateway_state.json").get("platforms") or {}
    prefix = f"{profile}:"
    return {k[len(prefix):]: (v or {}).get("state") for k, v in platforms.items()
            if isinstance(k, str) and k.startswith(prefix) and isinstance(v, dict)}


def status_lines(profile: str) -> list:
    """`seaos-kit gateway status` に出す行。"""
    h = host()
    lines = []
    if not h:
        lines.append("ホスト: 動いていない（seaos-kit gateway restart で起こす）")
    else:
        lines.append(f"ホスト: pid {h.pid}（{_home_label(h.home)} が起こした。全役で1つ）")
        lines.append(f"受け持ち: {', '.join(h.profiles) or '（なし）'}")
    if is_parked(profile):
        lines.append(f"{profile}: 止めてある（seaos-kit gateway restart {profile} で戻す）")
    elif h and h.serves(profile):
        lines.append(f"{profile}: 受け持たれている")
    else:
        lines.append(f"{profile}: 受け持たれていない")
    for platform, state in sorted(adapter_states(profile).items()):
        lines.append(f"  {platform}: {state}")
    return lines


def _home_label(home: Path) -> str:
    return home.name if home.parent.name == "profiles" else "default"


def _host_env() -> dict:
    """ホストを起こす環境。**誰の名前も持たせない**（→ 冒頭と _HOST_ENV_DROP）。"""
    env = {k: v for k, v in os.environ.items()
           if k not in _HOST_ENV_DROP and not k.startswith(_HOST_ENV_DROP_PREFIX)}
    # **ホストは default から起こす。** 役の HERMES_HOME で起こすと、その役がホストの
    # 持ち主になり、その役だけは外せなくなる（外すと全役が落ちる）。
    env["HERMES_HOME"] = str(hermes_home())
    return env


def _host_unit() -> Path:
    """Linux でホストを受け持つ systemd の user unit（`hermes gateway install` が作る）。"""
    return Path.home() / ".config/systemd/user" / "hermes-gateway.service"


def _spawn_host(log: Optional[Log] = None) -> bool:
    """ホストを素のプロセスとして起こす（macOS / Windows、unit の無い Linux）。"""
    exe = shutil.which("hermes")
    if not exe:
        if log:
            log("✗ hermes が PATH に無い")
        return False
    logs = hermes_home() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    out = (logs / "gateway-stdout.log").open("ab")

    # **消えない場所で起こす。** ゲートウェイは自分の cwd を握り続けるので、
    # そこが後から削除されると os.getcwd() が落ち、以後どの発言でも
    # システムプロンプトの組み立てで例外になる（実際にカードの作業部屋を
    # 掴んだまま、そのカードが片付いて消えた）。$HOME なら消えない。
    kwargs: dict = {
        "cwd": str(Path.home()),
        "env": _host_env(),
        "stdout": out,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
    }
    if os_kind() == "win32":
        # 親が死んでも生き残らせる（コンソールを切り離す）
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    # **`--replace` を付ける。** 止めた直前のホストがまだ後始末中でも、それを引き継いで
    # 立つ。付けないと、残っている記録に「繋がって」何もせずに終わる（Hermes 自身の
    # 再起動も同じ理由で付けている。hermes_cli/gateway.py の _restart_all_as_host）。
    subprocess.Popen([exe, "gateway", "run", "--replace"], **kwargs)
    return True


def _wait_host(want_alive: bool, wait: float) -> Optional[Host]:
    waited = 0.0
    while True:
        h = host()
        if bool(h) == want_alive:
            return h
        if waited >= wait:
            return h
        time.sleep(2)
        waited += 2


def _start_host(log: Optional[Log] = None) -> bool:
    """ホストを起こす。起きたことは**ホストの記録に pid が載ったこと**で確かめる。"""
    if os_kind() == "linux" and _host_unit().is_file():
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        hermes.run(["gateway", "start"], timeout=LIFECYCLE_TIMEOUT)
    elif not _spawn_host(log=log):
        return False
    return _wait_host(True, HOST_BOOT_WAIT) is not None


def _stop_host(h: Host) -> bool:
    """ホストを止める。**全役が止まり、走っているカードも落ちる。**
    止まったかは記録の pid の消滅で確かめる（戻り値だけでは嘘をつく）。"""
    if os_kind() == "linux" and _host_unit().is_file():
        # 監督下のプロセスを素で殺すと、systemd が「落ちた」とみなして上げ直す。
        subprocess.run(["systemctl", "--user", "stop", _host_unit().name], capture_output=True)
    else:
        _terminate(h.pid)
    # 止まる前に、走っている会話を片付ける猶予がある。待ちきれなければ強く止める。
    # **二重に走らせないほうが大事**（ディスパッチャが二重になると、同じカードを2回取る）。
    for _ in range(30):
        if not pid_alive(h.pid):
            return True
        time.sleep(1)
    _kill(h.pid)
    time.sleep(1)
    return not pid_alive(h.pid)


def restart_host(log: Optional[Log] = None) -> bool:
    """ホストごと起こし直す。**全役が一度落ち、走っているカードも落ちる。**

    役1つの反映なら restart_gateway で足りる。ホストごとが要るのは、Hermes 本体や
    プラグインの入れ替えのように、プロセス全体に効くものを読み直させたいときだけ。
    """
    n = running_cards()
    if n > 0 and log:
        log(f"! running / review が {n} 件ある。ホストの再起動で落ちる")
    h = host()
    if h and not _stop_host(h):
        if log:
            log(f"✗ ホスト（pid {h.pid}）を止められなかった")
        return False
    ok = _start_host(log=log)
    if log:
        now = host()
        if ok and now:
            log(f"+ ホストを起こし直した（pid {now.pid}）")
        else:
            log("✗ ホストが起きてこない（~/.hermes/logs/gateway-stdout.log を見る）")
    return ok


def _wait_served(profile: str, want: bool, wait: float = SERVE_WAIT) -> bool:
    waited = 0.0
    while True:
        h = host()
        if h is not None and h.serves(profile) == want:
            return True
        if waited >= wait:
            return False
        time.sleep(3)
        waited += 3


def _lifecycle(profile: str, verb: str) -> tuple:
    """`hermes -p <役> gateway <verb>`。ホストにその役だけを外させる・載せ直させる。

    Hermes の中で、名前付きの役の restart は「外して（unserve-profile）載せ直す
    （serve-profile）」、stop は「止めた印を置いて外す」になる。どちらもホストへの
    依頼で、ホスト自身は止まらない（hermes_cli/gateway_profile_lifecycle.py の
    profile_lifecycle）。**載せ直すと、その役のアダプタは作り直される**——鍵を
    入れ替えたときに効くのはこちら。見直しだけでは、繋がっているアダプタは
    作り直されない（gateway/run_adapters.py の _start_one_profile_adapters）。
    """
    return hermes.run(["-p", profile, "gateway", verb], timeout=LIFECYCLE_TIMEOUT)


def stop_gateway(profile: str, log: Optional[Log] = None) -> bool:
    """その役だけを止める。**ホストと他の役は止めない。**

    エージェントを外したのに窓口が残ると、外したはずの役が Slack で返事をし続ける。
    **止めた印が残る**ので、ホストを起こし直してもその役は載らない。戻すのは
    restart_gateway（Hermes が印を外して載せる）。
    止まったかは、ホストの受け持ちから消えたことで確かめる（戻り値だけでは嘘をつく）。
    """
    h = host()
    if h is None or not h.serves(profile):
        return True
    if h.launched_by(profile):
        # 起こした役を外すとホストごと止まり、全役が落ちる。黙ってそれをしない。
        if log:
            log(f"✗ {profile} はホストを起こした役なので、単独では止められない。"
                "seaos-kit gateway restart --host で default から起こし直してから止める")
        return False
    code, out = _lifecycle(profile, "stop")
    ok = code == 0 and _wait_served(profile, False)
    if log and not ok:
        log(f"✗ {profile} を止められなかった: {out.strip()[-300:]}")
    return ok


def restart_gateway(profile: str, log: Optional[Log] = None) -> bool:
    """その役を起こし直す。呼ぶ側はこの1つだけ知っていればよい。

    - ホストが動いていれば、**その役だけ**を外して載せ直す。ホストも他の役も、
      走っているカードも止まらない。止めてあった役はこれで戻る。
    - ホストが動いていなければ、ホストを起こす（全役が載る）。
    - その役がホストを起こした役なら、ホストごと起こし直す（外すと全役が落ちるため）。
      起こし直したホストは default のものになり、以後は役だけを扱える。
    """
    h = host()
    if h is None:
        ok = _start_host(log=log)
        h = host() if ok else None
        if ok and h and not h.serves(profile) and is_parked(profile):
            ok = _lifecycle(profile, "restart")[0] == 0
        ok = ok and _wait_served(profile, True)
        return _report(profile, ok, "ホストを起こした", log)

    if h.launched_by(profile):
        return _report(profile, restart_host(log=log) and _wait_served(profile, True),
                       "ホストごと起こし直した", log)

    code, out = _lifecycle(profile, "restart")
    # **外すのに失敗すると、Hermes は「確かめられなかった」と言って 0 で終わる。**
    # 受け持ちには古いアダプタのまま残るので、受け持ちを見るだけでは成功と区別できない。
    failed = code != 0 or "restart was not confirmed" in out
    ok = not failed and _wait_served(profile, True)
    if not ok and log:
        log(out.strip()[-300:])
    return _report(profile, ok, "その役だけを起こし直した", log)


def _report(profile: str, ok: bool, how: str, log: Optional[Log]) -> bool:
    if log:
        if ok:
            h = host()
            log(f"+ {profile} を再起動した（{how}" + (f"。ホストは pid {h.pid}" if h else "") + "）")
        else:
            log(f"✗ {profile} の再起動に失敗（seaos-kit gateway status で状態を見る）")
    return ok


def restart_when_idle(profile: str, log: Optional[Log] = None, *, whole_host: bool = False) -> bool:
    """走行中が無くなってから再起動する。**誰も落とさない。**

    構成を書き換える役は、書き換えたあとゲートウェイを起こし直さないと反映
    されない。役だけの再起動はカードを落とさないが、その役が Slack で返事を
    書いている途中なら、その会話は切れる。ホストごとの再起動は、**ワーカーが
    ホストの子**なので、カードの中から叩くと自分の実行ごと落ちる。手が空くまで
    待てば誰も落ちない。

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
    what = "ホストごと再起動する" if whole_host else "再起動する"
    with trail.open("a", encoding="utf-8") as fh:
        if left > 0:
            fh.write(f"{stamp} 手が空かないまま {IDLE_WAIT}秒 経ったので{what}"
                     f"（running / review が {left} 件残る）\n")
        else:
            fh.write(f"{stamp} 手が空いたので{what}（{waited}秒 待った）\n")
    try:
        if whole_host:
            return restart_host(log=log)
        return restart_gateway(profile, log=log)
    finally:
        # 裏で待っていたのが自分なら、待ちの印を外す（restart_later が次を足せるように）
        pending = logs / "gateway-restart.pending"
        try:
            if pending.read_text(encoding="utf-8").strip() == str(os.getpid()):
                pending.unlink()
        except (OSError, ValueError):
            pass


def serves_here(profile: str) -> bool:
    """**いま見ている Hermes（HERMES_HOME）の**ホストが、その役を受け持っているか。

    ホストの記録は HERMES_HOME ではなく OS ユーザーごとに1つの場所にある。一時 HOME で
    走らせた反映（テストなど）が、この PC で本当に動いているゲートウェイを起こし直さないよう、
    ホストの持ち主が同じ Hermes の根っこかを確かめる。
    """
    h = host()
    if not h or not h.serves(profile):
        return False
    try:
        root = hermes_home().resolve()
        home = h.home.resolve()
    except OSError:
        return False
    return home == root or root in home.parents


def restart_later(profile: str) -> bool:
    """手が空いてからその役だけを起こし直す処理（restart_when_idle）を、**裏で**始める。

    反映は画面や定期実行から呼ばれるので、そこで最大30分待つわけにいかない。
    切り離したプロセスに待たせ、反映そのものはすぐ返す。
    **既に待っているものがあれば足さない**——定期実行（10分ごと）と手の反映が重なっても、
    起こし直しは1回で済む。待っている側は、起こし直す時点の最新の設定を読む。
    """
    logs = profile_dir(profile) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    pending = logs / "gateway-restart.pending"
    try:
        pid = int(pending.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        pid = 0
    if pid and pid_alive(pid):
        return True
    out = (logs / "gateway-restart.log").open("ab")
    kwargs: dict = {"cwd": str(Path.home()), "stdout": out, "stderr": subprocess.STDOUT,
                    "stdin": subprocess.DEVNULL}
    if os_kind() == "win32":
        # 親（画面のバックエンドや定期実行）が終わっても生き残らせる
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen([sys.executable, str(kit_root() / "core" / "cli.py"),
                                 "gateway", "restart", profile, "--when-idle"], **kwargs)
    except OSError:
        return False
    pending.write_text(str(proc.pid), encoding="utf-8")
    return True


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


# ── コマンドの置き場 ─────────────────────────────────────────────────────

# PATH に置く名前。**`kit` のような一般名は使わない**——他のツールと衝突するし、
# エージェントの規約に書いたときに何のコマンドか分からない。
COMMAND = "seaos-kit"


def command_target() -> Path:
    """`seaos-kit` コマンドを置く場所。"""
    if os_kind() == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / COMMAND
    return Path.home() / ".local" / "bin"


def _interpreter() -> str:
    """このキットを走らせる Python。

    **解釈系を固定する。** `#!/usr/bin/env python3` に任せると、呼ぶ側の PATH で
    中身が変わる——実際、板から起動したエージェントの環境では `yaml` の無い
    python3 が引かれ、`seaos-kit roles` が落ちた。Hermes の venv には
    `pip_dependencies` が入っているので、そこを指す。
    """
    venv = hermes_home() / "hermes-agent" / "venv" / "bin" / "python"
    if os_kind() == "win32":
        venv = hermes_home() / "hermes-agent" / "venv" / "Scripts" / "python.exe"
    if venv.is_file():
        return str(venv)
    # **見つからなければ、いま動いている Python を使う。** キットは Hermes の Python で
    # 起動されるので、ホームの場所が想定と違っても（Windows で C:\hermes など）これが正しい。
    # PATH の python に落とすと、yaml も無い別の Python を掴む。
    return sys.executable or ("python" if os_kind() == "win32" else "python3")


def _win_add_to_path(target: Path, log: "Optional[Log]" = None) -> bool:
    """Windows のユーザー環境変数 PATH に、コマンドの置き場を足す。足したら True。

    **置くだけでは呼べない。** 以前は「PATH に足すこと」とログへ書くだけだったので、
    エージェントの端末から `seaos-kit` が見つからず、アクセス許可を出す手が無い状態に
    なっていた（実際に踏んだ）。macOS / Linux は `~/.local/bin` が最初から通っている。

    **書くのは利用者のユーザー環境変数だけ**（HKCU\Environment）。管理者権限も要らず、
    機械全体の設定には触らない。`setx` は 1024 文字で切り捨てるので使わない。

    反映は新しく起動したプロセスから。**いま動いているゲートウェイには届かない**ので、
    呼び手には再起動を案内させる。
    """
    try:
        import winreg  # noqa: PLC0415  （Windows でだけ import する）
    except ImportError:
        return False
    want = str(target)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as key:
            try:
                current, kind = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current, kind = "", winreg.REG_EXPAND_SZ
            # **区切りは `;` で固定する。** レジストリの PATH は Windows の形式なので、
            # 走っている OS の `os.pathsep` に任せない（検査が別の OS でも通るように）。
            parts = [p for p in str(current).split(";") if p.strip()]
            if any(os.path.normcase(p.rstrip("\\")) == os.path.normcase(want.rstrip("\\"))
                   for p in parts):
                return False
            parts.append(want)
            winreg.SetValueEx(key, "Path", 0, kind or winreg.REG_EXPAND_SZ, ";".join(parts))
    except OSError as exc:
        if log:
            log(f"  PATH に {target} を足せませんでした（手で足してください）: {exc}")
        return False
    # 走っているプロセスにも入れておく。**この回の処理で続けて呼べるように。**
    os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + want
    _win_broadcast_env()
    if log:
        log(f"  PATH に {target} を足しました（反映は再起動後）")
    return True


def _win_broadcast_env() -> None:
    """環境変数が変わったことを OS へ知らせる（WM_SETTINGCHANGE）。

    **レジストリに書くだけでは、すでに動いているアプリに伝わらない。** 新しく起こす
    プロセスは親の環境を引き継ぐので、通知が無いと Explorer から起動したアプリは
    古い PATH のままになる——「反映したのに見つからない」がこれで起きる。
    届かなくても害は無いので、失敗は黙って諦める。
    """
    try:
        import ctypes  # noqa: PLC0415

        HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(  # type: ignore[attr-defined]
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, ctypes.c_wchar_p("Environment"),
            SMTO_ABORTIFHUNG, 5000, None)
    except Exception:  # noqa: BLE001  （通知は補助。失敗しても PATH は書けている）
        pass


def link_command(log: Optional[Log] = None) -> Path:
    """PATH から叩けるようにする。

    **シンボリックリンクではなくラッパを書く**（Hermes 自身の `hermes` と同じ形）。
    解釈系を書き込む必要があるため。中身は本体を呼ぶだけなので、pull で追随する。
    """
    target = command_target()
    target.mkdir(parents=True, exist_ok=True)
    entry = kit_root() / "core" / "cli.py"
    python = _interpreter()

    if os_kind() == "win32":
        path = target / f"{COMMAND}.cmd"
        path.write_text(f'@echo off\r\n"{python}" "{entry}" %*\r\n', encoding="utf-8")
        if log:
            log(f"+ {path}")
        # **置くだけでは呼べない。** PATH に無いと、エージェントの端末から叩けない。
        _win_add_to_path(target, log)
        return path

    path = target / COMMAND
    if path.is_symlink() or path.exists():
        path.unlink()
    path.write_text(
        "#!/bin/sh\n"
        "# SEAOS のコマンド。**解釈系を固定してある**（PATH 次第で中身が変わると、\n"
        "# 板から起動したエージェントの環境で依存が足りずに落ちる）。\n"
        f'exec "{python}" "{entry}" "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    if log:
        log(f"+ {path} → {entry}")
    return path


def unlink_command(log: Optional[Log] = None) -> bool:
    target = command_target()
    removed = False
    # **旧名も消す。** `kit` から改名したので、前に入れた人の PATH には
    # 古い綴りが残っている。両方畳まないと、消したはずのコマンドが動き続ける。
    for name in (COMMAND, f"{COMMAND}.cmd", "kit", "kit.cmd"):
        path = target / name
        if path.is_symlink() or path.is_file():
            path.unlink()
            removed = True
            if log:
                log(f"- {path}")
    return removed


# ── 自動起動 ─────────────────────────────────────────────────────────────

def autostart_hint() -> str:
    """ログオン時にゲートウェイ（ホスト）を上げる作法（OS ごと）。

    **登録するのはホスト1つ。** 役ごとに登録しない（`--profile` を付けて起こすと、
    その役がホストの持ち主になり、その役だけを起こし直せなくなる）。
    """
    kind = os_kind()
    if kind == "win32":
        return (
            "Scheduled Task に登録する（全役を受け持つホストが1つ起きる）:\n"
            '  schtasks /Create /SC ONLOGON /TN "hermes-gateway" '
            '/TR "hermes gateway run"'
        )
    if kind == "linux":
        return (
            "systemd の user unit を使う（hermes gateway install。全役を受け持つホストが1つ）。\n"
            "**loginctl enable-linger が要る**——無いとログアウトで user systemd ごと落ちる。"
        )
    return (
        "macOS はホストを素のプロセスで走らせる（全役で1つ。launchd は使わない）。\n"
        "落ちたら seaos-kit gateway restart で上げ直す。"
    )
