"""AWS の箱に渡す値を書き出す。**箱までが担当**で、役や規約は書かない。

`terraform.tfvars` は**生成物**。手で編集しない（次の生成で消える）。
既定値の正は `terraform/variables.tf` にある。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Dict, Optional

from paths import kit_root

Log = Callable[[str], None]

ORDER = ("region", "instance_type", "data_volume_size", "name")


class TerraformError(RuntimeError):
    pass


def terraform_dir() -> Path:
    return kit_root() / "terraform"


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(kit_root()), *args],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def repo_url() -> str:
    return _git("remote", "get-url", "origin")


def ref() -> str:
    return _git("rev-parse", "--abbrev-ref", "HEAD")


def write_vars(
    overrides: Optional[Dict[str, str]] = None,
    *,
    out: Optional[Path] = None,
    force: bool = False,
    log: Optional[Log] = None,
) -> Path:
    over = dict(overrides or {})
    target = out or (terraform_dir() / "terraform.tfvars")

    url = over.pop("kit_repo_url", "") or repo_url()
    rev = over.pop("kit_ref", "") or ref()

    # **リモートが無いと箱は空のまま立ち上がる。** ここで止めるのが一番安い。
    if not url:
        raise TerraformError(
            "git のリモートが無い。先に足すこと（git remote add origin <url>）\n"
            "  一時的に別の場所から配るなら overrides に kit_repo_url を渡す"
        )

    lines = [
        "# hermes-kit terraform vars が生成した。**手で編集しない**（次の生成で消える）。",
        "# 既定値の正は terraform/variables.tf にある。ここに載るのは",
        "# 実測した値と、明示的に上書きしたものだけである。",
        "#",
        "# 秘密はここに入らない。.env は SSM Parameter Store へ入れる:",
        "#   aws ssm put-parameter --name /<name>/dotenv --type SecureString \\",
        "#     --overwrite --value file://.env",
        "",
        f"{'kit_repo_url':<16} = \"{url}\"",
        f"{'kit_ref':<16} = \"{rev}\"",
    ]
    for key in ORDER:
        value = over.get(key)
        if value is None:
            continue
        # 数値はそのまま、文字列は引用する（terraform fmt と同じ見え方）
        rendered = value if str(value).isdigit() else f'"{value}"'
        lines.append(f"{key:<16} = {rendered}")

    body = "\n".join(lines) + "\n"
    if target.is_file() and not force and target.read_text(encoding="utf-8") == body:
        if log:
            log(f"= {target}（変化なし）")
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    if log:
        log(f"+ {target}")
        log(f"  clone 元: {url}（{rev}）")
        if over:
            log(f"  上書き: {' '.join(sorted(over))}")
    return target
