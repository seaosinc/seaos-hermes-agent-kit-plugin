"""この PC の事実を実測して、各役の `agent.environment_hint` に置く。

**マシン固有なので配布物には入れない。** そのぶん `update --force-config` は
config.yaml ごと入れ替えるので、ここが消える——**実際に全役から消えていた。**
反映のたびに書き直す。

埋めるのは `templates/shared/ENVIRONMENT.md.tmpl` の穴。**推測しない**
——`python` が無い環境で `python` と書けば担当はそこで落ちるし、
Homebrew の綴りを Linux で試しても落ちる。実測した事実だけを渡す。
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import yaml

import roles
from paths import kit_root, profile_dir

Log = Callable[[str], None]


@dataclass
class Result:
    lines: List[str] = field(default_factory=list)
    failures: int = 0

    def ok(self) -> bool:
        return self.failures == 0


def repo_root() -> Path:
    """開発リポジトリの置き場。環境変数で差し替えられる。"""
    return Path(os.environ.get("HERMES_KIT_REPO_ROOT") or (Path.home() / "Projects"))


def _run(*args: str) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (proc.stdout or "").strip()


def _tool_line(name: str, note: str = "", absent: str = "") -> str:
    path = shutil.which(name)
    if not path:
        return absent or f"- `{name}` は未導入"
    version = _run(name, "--version").splitlines()
    head = version[0] if version else ""
    return f"- `{name}` → `{path}`（{head}）{note}"


def _package_manager() -> str:
    """**道具を足すときの叩き方は OS で違う。** 実測して書く。"""
    brew = shutil.which("brew")
    if brew:
        return f"- Homebrew は `{Path(brew).parent.parent}`"
    for name in ("apt-get", "dnf", "yum", "apk", "pacman"):
        if shutil.which(name):
            return f"- パッケージは `{name}`（導入には `sudo` が要る）"
    return "- パッケージマネージャは見つからなかった"


def _python_line() -> str:
    """**`python` が無い環境がある。** そこを知らないと担当は最初の一手で落ちる。"""
    version = _run("python3", "--version").replace("Python ", "")
    if shutil.which("python"):
        return f"- `python` / `python3` とも使える（Python {version}）"
    return (
        "- **`python` は存在しない。必ず `python3` を使う。** "
        "`python` を叩くと `command not found` になる\n"
        f"- `python3` → `{shutil.which('python3')}`（{version}）"
    )


def _os_name() -> str:
    if platform.system() == "Darwin":
        return _run("sw_vers", "-productName") or "macOS"
    release = Path("/etc/os-release")
    if release.is_file():
        for line in release.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("NAME="):
                return line.partition("=")[2].strip('"')
    return platform.system()


def _os_version() -> str:
    if platform.system() == "Darwin":
        return _run("sw_vers", "-productVersion") or platform.release()
    release = Path("/etc/os-release")
    if release.is_file():
        for line in release.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("VERSION_ID="):
                return line.partition("=")[2].strip('"')
    return platform.release()


def measure() -> Dict[str, str]:
    """テンプレートの穴を埋める値。すべて実測。"""
    root = repo_root()
    dirs = [p for p in root.glob("*") if p.is_dir()] if root.is_dir() else []
    gits = [p for p in dirs if (p / ".git").exists()]
    return {
        "OS_NAME": _os_name(),
        "OS_VERSION": _os_version(),
        "ARCH": platform.machine(),
        "SHELL": Path(os.environ.get("SHELL", "")).name or "不明",
        "USER": os.environ.get("USER") or os.environ.get("USERNAME") or "不明",
        "HOME": str(Path.home()),
        "REPO_ROOT": str(root),
        "REPO_DIRS": str(len(dirs)),
        "REPO_GITS": str(len(gits)),
        "PKGMGR_LINE": _package_manager(),
        "PYTHON_LINE": _python_line(),
        "NODE_LINE": _tool_line("node"),
        "CLAUDE_LINE": _tool_line(
            "claude", note="— サブスク枠。`ANTHROPIC_API_KEY` は設定しない",
            absent="- `claude` は未導入（委譲先が減る）"),
        "OPENCODE_LINE": _tool_line("opencode", absent="- `opencode` は未導入"),
    }


def render() -> str:
    tmpl = kit_root() / "templates" / "shared" / "ENVIRONMENT.md.tmpl"
    if not tmpl.is_file():
        return ""
    text = tmpl.read_text(encoding="utf-8")
    for key, value in measure().items():
        text = text.replace("{{" + key + "}}", value)
    return text


def apply(log: Optional[Log] = None) -> Result:
    """全役の config.yaml へ書く。**既に同じなら触らない。**"""
    res = Result()
    hint = render()
    if not hint:
        return res

    changed = 0
    for name in roles.names():
        cfg = profile_dir(name) / "config.yaml"
        if not cfg.is_file():
            continue
        try:
            body = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            res.failures += 1
            res.lines.append(f"✗ {name} の設定を読み取れませんでした")
            continue
        agent = body.setdefault("agent", {})
        if agent.get("environment_hint") == hint:
            continue
        agent["environment_hint"] = hint
        cfg.write_text(yaml.safe_dump(body, allow_unicode=True, sort_keys=False),
                       encoding="utf-8")
        changed += 1

    if changed:
        res.lines.append(f"環境の実測を {changed} 件のエージェントに書きました")
    if log:
        for line in res.lines:
            log(line)
    return res
