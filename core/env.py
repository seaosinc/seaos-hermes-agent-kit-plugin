"""秘密の配布。**正はキット直下の .env ただ1つ。**

各役へは、**その役が宣言した変数だけ**を配る。宣言していないのに残っている
キット管理下の変数は引き上げる（以前の「全役へ丸ごと複製」の名残を掃除するため）。
**キットが知らない変数には触らない。**
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Dict, List, Tuple

import roles
from paths import env_file, profile_dir


def read_env(path: Path) -> Dict[str, str]:
    """`KEY=VALUE` を読む。コメントと空行は捨てる。値はそのまま（引用は外さない）。"""
    out: Dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out[key.strip()] = value
    return out


def _secure(path: Path) -> None:
    """秘密のファイルは 600。**作った直後に必ず絞る。**"""
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        # Windows は POSIX パーミッションを持たない。ACL は OS 既定に委ねる。
        pass


def _upsert(lines: List[str], name: str, value: str, desc: str) -> List[str]:
    """既にあれば値だけ差し替え、無ければ説明付きで足す。"""
    for i, line in enumerate(lines):
        if line.startswith(f"{name}="):
            lines[i] = f"{name}={value}"
            return lines
    if lines and lines[-1].strip():
        lines.append("")
    lines.append(f"# {desc}")
    lines.append(f"{name}={value}")
    return lines


def _drop(lines: List[str], name: str) -> List[str]:
    """変数と、その直前の説明行を一緒に落とす（説明だけ残ると読み手が混乱する）。"""
    out: List[str] = []
    for line in lines:
        if line.startswith(f"{name}="):
            while out and (out[-1].startswith("#") or not out[-1].strip()):
                out.pop()
            continue
        out.append(line)
    return out


def apply() -> Tuple[List[str], List[str]]:
    """正の .env から各役へ配る。戻り値は (報告行, 値が空のままの項目)。"""
    # **鍵がまだ無いのは、壊れているのではなく「これから入れる」状態である。**
    # 入れたてのプラグインには .env が無い（gitignore なので clone に含まれない）。
    # ここで例外を投げると、利用者が最初に踏む場所で画面が落ちる。
    # 何が足りないかを報告して、既にある値は残す。
    src = env_file()
    source = read_env(src) if src.is_file() else {}
    managed = roles.managed_env_vars()
    report: List[str] = []
    missing: List[str] = []

    for name in roles.names():
        pdir = profile_dir(name)
        if not pdir.is_dir():
            continue
        dst = pdir / ".env"
        lines = dst.read_text(encoding="utf-8").splitlines() if dst.is_file() else []

        existing = {}
        for line in lines:
            if not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                existing[k.strip()] = v

        declared: List[str] = []
        wrote = 0
        for var, required, desc in roles.env_requirements(name):
            declared.append(var)
            value = source.get(var, "")
            if not value and existing.get(var):
                # **既にある値を空で潰さない。** 正に無いのは「まだ入れていない」
                # だけかもしれず、消すと動いている役の鍵が飛ぶ。
                # 配布物として入れ直した直後の .env は空なので、ここを踏むと
                # 8役ぶんの鍵が同時に消える（実際に踏みかけた）。
                if required:
                    missing.append(f"{name}:{var}（正に無いので既存値を残した）")
                continue
            if required and not value:
                missing.append(f"{name}:{var}")
            lines = _upsert(lines, var, value, desc)
            wrote += 1

        pruned = 0
        for var in managed:
            if var in declared:
                continue
            if any(line.startswith(f"{var}=") for line in lines):
                lines = _drop(lines, var)
                pruned += 1

        dst.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        _secure(dst)
        report.append(
            f"{name} に鍵を {wrote} 件" + (f"（不要な {pruned} 件を引き上げた）" if pruned else "")
        )

    return report, missing


def set_value(name: str, value: str, desc: str = "") -> None:
    """正の .env に1件書く。**GUI と CLI の共通の入口。**

    呼び手が変数名を検証すること（キットが知らない名前を書かせない）。
    ここは書き込みだけを担い、どこへ配るかは apply() が決める。
    """
    path = env_file()
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    lines = _upsert(lines, name, value, desc or f"{name}")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    _secure(path)
