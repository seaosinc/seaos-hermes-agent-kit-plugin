"""この PC に、キットが動くための道具が揃っているか。**揃っていなければ入れる。**

エージェントが使う道具の一部は、Hermes もキットも持ってこない:

  Docker     作業部屋（developer / senior-developer の箱）と共有記憶
  Node.js    `npx` で起動する MCP サーバ（handler の Notion、ファイル読み取り）

無くても導入は通り、**最初にその道具を使うカードで初めて落ちる。** 設定画面にも
出ないので、利用者からは「なぜか実装を頼むと失敗する」としか見えない。

ここは**入れてよいものの台帳**でもある。provisioner はこの台帳にある道具しか
入れない（`install` は台帳に無い名前を断る）。provisioner は Slack 経由の依頼で
動くことがあり、**他人の文章に書かれた任意のパッケージを入れる口にしない**ため。

入れ方は OS ごとの定番に寄せる（macOS は Homebrew、Windows は winget）。
**管理者の承認が要るものは、人に押してもらうしかない**（macOS のパスワード、
Windows の UAC）。そこは失敗として返し、provisioner がカードで人へ渡す。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import roles
from paths import os_kind

# cron やゲートウェイから呼ばれると PATH が痩せている。**入っているのに「無い」と
# 判定する**と、入れ直しのカードが立ち続けるので、定番の置き場も見る。
_EXTRA_DIRS = {
    "darwin": ["/opt/homebrew/bin", "/usr/local/bin",
               "/Applications/Docker.app/Contents/Resources/bin",
               str(Path.home() / ".local/bin")],
    "win32": [r"C:\Program Files\Docker\Docker\resources\bin", r"C:\Program Files\nodejs",
              str(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps")],
    "linux": ["/usr/local/bin", "/usr/bin"],
}


@dataclass
class Tool:
    name: str
    label: str
    why: str
    commands: List[str]                     # どれか1つが見つかれば「入っている」
    install: Dict[str, List[str]]           # OS -> コマンド
    after: List[str] = field(default_factory=list)   # 入れたあとにやること（seaos-kit の下位コマンド）


CATALOG: Dict[str, Tool] = {
    "docker": Tool(
        name="docker",
        label="Docker",
        why="作業部屋（コードを書く役の使い捨ての箱）と共有記憶に要る",
        commands=["docker"],
        install={
            "darwin": ["brew", "install", "--cask", "docker-desktop"],
            "win32": ["winget", "install", "-e", "--id", "Docker.DockerDesktop",
                      "--accept-source-agreements", "--accept-package-agreements"],
        },
        after=["machine start docker", "workspace build", "mem0 up"],
    ),
    "node": Tool(
        name="node",
        label="Node.js",
        why="npx で起動する MCP サーバ（Notion、受け取ったファイルの読み取りなど）に要る",
        commands=["npx"],
        install={
            "darwin": ["brew", "install", "node"],
            "win32": ["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS",
                      "--accept-source-agreements", "--accept-package-agreements"],
        },
    ),
}


class MachineError(RuntimeError):
    """呼び手に見せる、原因の分かる失敗。"""


def find(command: str) -> Optional[str]:
    found = shutil.which(command)
    if found:
        return found
    exts = ["", ".exe", ".cmd"] if os_kind() == "win32" else [""]
    for d in _EXTRA_DIRS.get(os_kind(), []):
        for ext in exts:
            p = Path(d) / f"{command}{ext}"
            if p.is_file():
                return str(p)
    return None


def _run(argv: List[str], timeout: int) -> subprocess.CompletedProcess:
    env = {**os.environ,
           # 対話を出さない。**出たら人に渡す**（stdin を閉じてあるので待たずに落ちる）
           "NONINTERACTIVE": "1", "HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_ENV_HINTS": "1"}
    exe = find(argv[0]) or argv[0]
    return subprocess.run([exe, *argv[1:]], capture_output=True, text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL, env=env)


def _docker_running() -> bool:
    exe = find("docker")
    if not exe:
        return False
    try:
        return subprocess.run([exe, "info"], capture_output=True, timeout=30,
                              stdin=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# 役ではなく、全役が使う仕組み。画面と provisioner のカードに、役名と並べて出す。
SHARED_MEMORY = "共有の記憶（mem0）"


def needed_by(tool: str) -> List[str]:
    """**有効な役のうち**、その道具が無いと働かないもの。空なら今は要らない。

    Docker は、作業部屋を持つ役と、共有の記憶（mem0 はコンテナで動く）が使う。
    mem0 を起こすフックは operator が持っているが、**使うのは全役**なので、
    operator の名前ではなく `SHARED_MEMORY` として出す（「operator が使う」は誤解を招いた）。
    """
    specs = roles.all_specs()
    out: List[str] = []
    for name in roles.names():
        spec = specs.get(name) or {}
        if tool == "docker":
            if spec.get("workspace") and spec.get("shell", True):
                out.append(name)
            elif spec.get("hooks") and SHARED_MEMORY not in out:
                out.append(SHARED_MEMORY)
        elif tool == "node":
            servers = roles.mcp_servers(name)
            if any(str((s or {}).get("command", "")) in ("npx", "node") for s in servers.values()):
                out.append(name)
    return out


def status() -> List[Dict]:
    """台帳の道具ごとの状態。"""
    rows: List[Dict] = []
    for tool in CATALOG.values():
        path = next((p for p in (find(c) for c in tool.commands) if p), None)
        row = {
            **{k: v for k, v in asdict(tool).items() if k in ("name", "label", "why", "after")},
            "installed": bool(path),
            "path": path or "",
            "neededBy": needed_by(tool.name),
            "installable": os_kind() in tool.install,
            "installCommand": " ".join(tool.install.get(os_kind(), [])),
        }
        if tool.name == "docker":
            row["running"] = _docker_running() if path else False
        # **足りない＝要る役があるのに無い（Docker なら動いていない）。**
        row["missing"] = bool(row["neededBy"]) and (
            not row["installed"] or (tool.name == "docker" and not row["running"]))
        rows.append(row)
    return rows


def install(name: str, *, timeout: int = 1800) -> Dict:
    """台帳の道具を入れる。**台帳に無い名前は断る。**

    返すのは `{"ok", "needsHuman", "command", "output"}`。`needsHuman` は、管理者の
    承認や前提（Homebrew 自体）が無くて、人にしか進められない状態。
    """
    tool = CATALOG.get(name)
    if tool is None:
        raise MachineError(f"{name} は入れてよい道具の台帳にありません（{', '.join(CATALOG)}）")
    argv = tool.install.get(os_kind())
    if not argv:
        raise MachineError(f"{tool.label} をこの OS（{os_kind()}）へ入れる手順を持っていません")
    command = " ".join(argv)

    if any(find(c) for c in tool.commands):
        return {"ok": True, "needsHuman": False, "command": command, "output": "既に入っています"}
    manager = argv[0]
    if not find(manager):
        how = ('/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
               if manager == "brew" else "Microsoft Store の「アプリ インストーラー」")
        return {"ok": False, "needsHuman": True, "command": command,
                "output": f"{manager} がありません。先に人が入れる必要があります: {how}"}
    try:
        proc = _run(argv, timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "needsHuman": True, "command": command,
                "output": f"{timeout // 60} 分で終わりませんでした。承認の画面が開いたまま待っている可能性があります"}
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    ok = proc.returncode == 0 and any(find(c) for c in tool.commands)
    # **パスワードや承認で止まった。** 無人では進められない。
    # 手がかりは、パスワードを求める文言、管理者（権限の昇格）を求める文言、
    # Windows の承認画面（UAC）と、winget が承認を得られなかったときの終了コード。
    # macOS の Homebrew が権限を求めるときも「Administrator」を含むので、ここで拾える。
    human = not ok and any(w in text.lower() for w in
                           ("password", "administrator", "elevat", "uac", "0x8a150056"))
    return {"ok": ok, "needsHuman": human, "command": command, "output": text[-1500:]}


def start(name: str, *, wait: int = 180) -> bool:
    """入っているが動いていないものを起こす。いまは Docker だけ。"""
    if name != "docker":
        raise MachineError(f"{name} は起動するものではありません")
    if _docker_running():
        return True
    if os_kind() == "darwin":
        subprocess.run(["open", "-a", "Docker"], capture_output=True, stdin=subprocess.DEVNULL)
    elif os_kind() == "win32":
        exe = Path(r"C:\Program Files\Docker\Docker\Docker Desktop.exe")
        if exe.is_file():
            subprocess.Popen([str(exe)], stdin=subprocess.DEVNULL)
    import time

    deadline = time.time() + wait
    while time.time() < deadline:
        if _docker_running():
            return True
        time.sleep(5)
    return False
