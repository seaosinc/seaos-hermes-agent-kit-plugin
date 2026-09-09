"""キットの中核。**CLI も GUI もここを呼ぶ。**

zsh 版（bin/hermes-kit + bin/_*.zsh）のうち、OS に触らない部分をここへ移した。
常駐の作法とコマンドの置き場だけが OS で違い、それは paths.py と後続の
platform 実装に閉じる。ここには platform 分岐を書かないこと。
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import env as env_mod
import hermes
import roles
from paths import kit_root, profile_dir

Log = Callable[[str], None]


@dataclass
class Result:
    """実行結果。**失敗を握り潰さない**ため、行と失敗数を分けて持つ。"""
    lines: List[str] = field(default_factory=list)
    failures: int = 0

    def ok(self) -> bool:
        return self.failures == 0


def _generator():
    path = Path(__file__).resolve().parent / "build_distributions.py"
    spec = importlib.util.spec_from_file_location("kit_generator", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules.setdefault("kit_generator", module)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def build(out: Optional[Path] = None, log: Optional[Log] = None) -> Path:
    """templates/ → 配布物。**dist/ は生成物なので毎回作り直す。**"""
    root = kit_root()
    target = out or (root / "dist")
    # **関数を直接呼ぶ。** 生成器の CLI 分岐（__main__）は zsh 版が使っていた口で、
    # Python から使うときに argv を差し替えるのは事故のもと。
    _generator().build(root, target)
    if log:
        log(f"配布物を {target} に生成した")
    return target


def sync_descriptions(log: Optional[Log] = None) -> Result:
    """説明文を生成器の文面に合わせる。**振り分けの唯一の入力なので毎回やる。**"""
    result = Result()
    for name in roles.names():
        if not hermes.profile_exists(name):
            continue
        text = roles.describe(name)
        if not text:
            continue
        code, _out = hermes.set_description(name, text)
        if code == 0:
            result.lines.append(f"= {name}")
        else:
            result.failures += 1
            result.lines.append(f"✗ {name}（説明文を設定できず）")
    if log:
        log(f"説明文を {len(result.lines) - result.failures} 役ぶん合わせた（decomposer が読む）")
    return result


def apply_env(log: Optional[Log] = None) -> Result:
    """正の .env から各役へ配る。"""
    result = Result()
    report, missing = env_mod.apply()
    result.lines.extend(report)
    for item in missing:
        result.lines.append(f"! 値が空のまま: {item}")
    if log:
        for line in result.lines:
            log(line)
    return result


def update(*, force_config: bool = False, log: Optional[Log] = None) -> Result:
    """templates/ → 配布物 → 各プロファイル → 説明文。

    **config.yaml は既定で保持される**（Hermes の仕様）。モデルやトポロジ、
    mcp_servers を変えたのに反映されないときは、たいてい force_config を忘れている。
    """
    result = Result()
    out = build(log=log)

    for name in roles.names():
        dist = out / name
        if not dist.is_dir():
            continue
        if not hermes.profile_exists(name):
            code, _ = hermes.install(dist)
            result.lines.append(f"+ {name}（新規に導入）" if code == 0 else f"✗ {name} の導入に失敗")
            result.failures += 0 if code == 0 else 1
            continue
        if not hermes.is_distribution(name):
            # 旧方式で作られたプロファイル。一度だけ配布物として入れ直す
            code, _ = hermes.install(dist, force=True)
            result.lines.append(f"+ {name}（配布物へ移行）" if code == 0 else f"✗ {name} の移行に失敗")
            result.failures += 0 if code == 0 else 1
            continue
        code, _ = hermes.update(name, force_config=force_config)
        result.lines.append(f"~ {name}" if code == 0 else f"✗ {name} の更新に失敗")
        result.failures += 0 if code == 0 else 1

    described = sync_descriptions(log=log)
    result.lines.extend(described.lines)
    result.failures += described.failures

    applied = apply_env()
    result.lines.extend(applied.lines)

    if log:
        for line in result.lines:
            log(line)
    return result


def _same_file(a: Path, b: Path) -> bool:
    if a.is_file() != b.is_file():
        return False
    return (not a.is_file()) or a.read_bytes() == b.read_bytes()


def _same_tree(a: Path, b: Path) -> bool:
    """スキルの木を比べる（__pycache__ は生成物なので無視する）。"""
    if a.is_dir() != b.is_dir():
        return False
    if not a.is_dir():
        return True

    def files(root: Path) -> dict:
        return {
            p.relative_to(root).as_posix(): p
            for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts
        }

    fa, fb = files(a), files(b)
    if set(fa) != set(fb):
        return False
    return all(fa[k].read_bytes() == fb[k].read_bytes() for k in fa)


def diff(log: Optional[Log] = None) -> Result:
    """反映せずに、何が変わるかだけ見る（zsh 版の --dry-run）。"""
    result = Result()
    with tempfile.TemporaryDirectory(prefix="kit-diff-") as tmp:
        out = build(Path(tmp), log=None)
        for name in roles.names():
            a, b = out / name, profile_dir(name)
            if not a.is_dir() or not b.is_dir():
                result.lines.append(f"+ {name}（新規）")
                continue
            # **config.yaml は比べない。** `profile update` が既定で保持するので、
            # 生成物と一致しないのが正常な状態である。比較に入れると全役が
            # 永久に「更新される」と出て、本当の差分が埋もれる。
            same = _same_file(a / "SOUL.md", b / "SOUL.md") and _same_tree(a / "skills", b / "skills")
            result.lines.append(f"= {name}" if same else f"~ {name}（更新される）")
    if log:
        for line in result.lines:
            log(line)
    return result
