"""CLI の薄い皮。**ロジックはここに書かない。**

GUI（dashboard/plugin_api.py）も同じ core を呼ぶ。皮が2枚あっても中身は1つで、
片方を直したらもう片方が古くなる、という事故を構造的に起こさないための境界。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kit  # noqa: E402
import roles  # noqa: E402


def _print(line: str) -> None:
    print(f"  {line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kit",
        description="SEAOS のエージェント役一式を生成・導入・検査する",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("roles", help="役の一覧を出す")
    sub.add_parser("build", help="templates/ から配布物を生成する")
    sub.add_parser("diff", help="反映せず、何が変わるかだけ見る")
    sub.add_parser("describe", help="説明文を生成器の文面に合わせる")
    sub.add_parser("env", help=".env から各役へ鍵を配る")
    up = sub.add_parser("update", help="生成 → 各役へ反映 → 説明文 → 鍵")
    up.add_argument(
        "--force-config",
        action="store_true",
        help="config.yaml も入れ替える（モデル・mcp_servers を変えたときに要る）",
    )

    args = parser.parse_args(argv)

    if args.cmd == "roles":
        for name in roles.names():
            board = "" if name not in roles.without_board() else "  （板に載らない）"
            print(f"{name}{board}")
        return 0

    if args.cmd == "build":
        kit.build(log=_print)
        return 0

    if args.cmd == "diff":
        result = kit.diff(log=_print)
        return 0 if result.ok() else 1

    if args.cmd == "describe":
        result = kit.sync_descriptions(log=_print)
        return 0 if result.ok() else 1

    if args.cmd == "env":
        result = kit.apply_env(log=_print)
        return 0 if result.ok() else 1

    if args.cmd == "update":
        result = kit.update(force_config=args.force_config, log=_print)
        return 0 if result.ok() else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
