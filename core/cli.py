#!/usr/bin/env python3
"""CLI の薄い皮。**ロジックはここに書かない。**

GUI（dashboard/plugin_api.py）も同じ core を呼ぶ。皮が2枚あっても中身は1つで、
片方を直したらもう片方が古くなる、という事故を構造的に起こさないための境界。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import booking  # noqa: E402
import doctor as doctor_mod  # noqa: E402
import install as install_mod  # noqa: E402
import kit  # noqa: E402
import maintain as maintain_mod  # noqa: E402
import platform_ops  # noqa: E402
import mem0  # noqa: E402
import roles  # noqa: E402
import selftest  # noqa: E402
import selfupdate  # noqa: E402
import worker as worker_mod  # noqa: E402
import workspace as ws  # noqa: E402


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
    sub.add_parser("doctor", help="設定漏れを検証する（問題があれば終了コード 1）")
    sub.add_parser("test", help="生成物の形を検査する（本番に触らない）")
    ug = sub.add_parser("upgrade", help="pull → 反映 → 検証")
    ug.add_argument("--dry-run", action="store_true", help="反映せず、何が起きるかだけ見る")
    ug.add_argument("--force-config", action="store_true", help="config.yaml も入れ替える")

    wk = sub.add_parser("worker", help="業務別ワーカーの CRUD")
    wsub = wk.add_subparsers(dest="wcmd", required=True)
    wsub.add_parser("list", help="一覧")

    # **新設と改修。** recruiter の本業なので、ここが無いとエージェントは
    # 増やせない（実装は core/worker.py にあったが CLI に繋がっていなかった）。
    def _shared(sp, *, required_desc: bool) -> None:
        sp.add_argument("name")
        sp.add_argument("--desc", required=required_desc,
                        help="decomposer が読む説明。**担当の割り振りはこれで決まる**")
        sp.add_argument("--summary", help="人が読む一行。**設定画面の一覧に出る**")
        sp.add_argument("--model", help="使うモデル")
        sp.add_argument("--extra", help="profile.yaml に足す YAML 片")
        sp.add_argument("--soul", type=Path, help="SOUL.md のもと")
        sp.add_argument("--skill", action="append", type=Path, default=[], metavar="PATH",
                        help="載せるスキルのフォルダ（繰り返し可）")
        sp.add_argument("--mcp", action="append", default=[], metavar="KEY=JSON",
                        help="足す MCP サーバ（繰り返し可）")
        sp.add_argument("--env", action="append", default=[], metavar="NAME=説明",
                        help="必要な環境変数（繰り返し可）")

    wnew = wsub.add_parser("new", help="新しい役を作る")
    _shared(wnew, required_desc=True)
    wnew.add_argument("--from", dest="source", default="_template", help="下敷きにする役")

    wset = wsub.add_parser("set", help="既存の役を直す")
    _shared(wset, required_desc=False)
    wset.add_argument("--rm-skill", action="append", default=[], metavar="NAME",
                      help="外すスキル（繰り返し可）")
    wshow = wsub.add_parser("show", help="1体の詳細")
    wshow.add_argument("name")
    wrm = wsub.add_parser("rm", help="削除")
    wrm.add_argument("name")
    wrm.add_argument("--keep-profile", action="store_true", help="プロファイルは残す")

    wp = sub.add_parser("workspace", help="作業部屋（使い捨てコンテナ）")
    wpsub = wp.add_subparsers(dest="wpcmd", required=True)
    wpsub.add_parser("verify", help="建ててあるイメージの中身を確かめる")
    wpb = wpsub.add_parser("build", help="イメージを建てる")
    wpb.add_argument("--no-warm", action="store_true", help="キャッシュを温めない")
    wpsub.add_parser("ca", help="組織の TLS 傍受プロキシの CA を取り出す")
    wpsub.add_parser("gc", help="匿名ボリュームと dangling イメージだけ落とす")

    m0 = sub.add_parser("mem0", help="共有記憶")
    m0sub = m0.add_subparsers(dest="mcmd", required=True)
    m0sub.add_parser("up", help="起動して各役へ繋ぐ")
    m0sub.add_parser("down", help="停止する")
    m0sub.add_parser("check", help="状態を見る")

    gw = sub.add_parser("gateway", help="ゲートウェイの常駐（OS ごとの作法を吸収する）")
    gwsub = gw.add_subparsers(dest="gcmd", required=True)
    gr = gwsub.add_parser("restart", help="再起動する")
    gr.add_argument("profile", nargs="?", help="省略時はゲートが載っている役")
    gr.add_argument("--when-idle", action="store_true",
                    help="走行中のカードが無くなってから（誰も落とさない）")
    gwsub.add_parser("status", help="いまの状態")

    ins = sub.add_parser("install", help="全役を導入し、配布物に載らないものを揃える")
    unins = sub.add_parser("uninstall", help="撤去する（既定はキット自身の痕跡だけ）")
    unins.add_argument("--profiles", action="store_true", help="役のプロファイルも消す")

    gu = sub.add_parser("guest", help="ゲストのアクセス許可")
    gu.add_argument("rest", nargs=argparse.REMAINDER)

    pg = sub.add_parser("purge", help="archived のカードを物理削除する（戻せない）")
    pg.add_argument("--yes", action="store_true", help="実際に消す（既定は数えるだけ）")
    pg.add_argument("--older-than", type=int, default=0, metavar="日数",
                    help="この日数より古いものだけ。0 なら archived すべて")

    sub.add_parser("maintain", help="日次の保守一式（反映 → 掃除 → 検証）")

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

    if args.cmd == "doctor":
        rep = doctor_mod.run(log=lambda l: print(l if l.startswith("=== ") or not l else f"  {l}"))
        print()
        print("✓ 問題なし" if rep.passed() else f"★ {rep.failures} 件の問題")
        return 0 if rep.passed() else 1

    if args.cmd == "test":
        ok, _lines = selftest.run(log=print)
        return 0 if ok else 1

    if args.cmd == "upgrade":
        ok = selfupdate.run(dry_run=args.dry_run, force_config=args.force_config, log=print)
        return 0 if ok else 1

    if args.cmd == "worker":
        if args.wcmd == "list":
            print(f"{'NAME':<20} {'MODEL':<24} {'DEPLOYED':<10} DESCRIPTION")
            for r in worker_mod.listing():
                mark = "yes" if r["deployed"] else "-"
                print(f"{r['name']:<20} {r['model']:<24} {mark:<10} {r['description'][:44]}")
            return 0
        if args.wcmd in ("new", "set"):
            def _pairs(items):
                out = {}
                for item in items:
                    key, _, value = item.partition("=")
                    if not key or not value:
                        raise worker_mod.WorkerError(f"KEY=VALUE の形で書くこと: {item}")
                    out[key] = value
                return out

            if args.wcmd == "new":
                res = worker_mod.new(
                    args.name, desc=args.desc, summary=args.summary or "",
                    model=args.model or "", extra=args.extra or "",
                    soul=args.soul, source=args.source, skills=args.skill,
                    mcps=_pairs(args.mcp), envs=_pairs(args.env))
                _print(f"{args.name} を作った: {res.path}")
                _print("反映するには update を実行する")
                return 0

            changed = worker_mod.update_worker(
                args.name, desc=args.desc, summary=args.summary, model=args.model,
                extra=args.extra,
                soul=args.soul, add_skills=args.skill, rm_skills=args.rm_skill,
                mcps=_pairs(args.mcp), envs=_pairs(args.env))
            _print(f"{args.name}: {', '.join(changed) if changed else '変更なし'}")
            if changed:
                _print("反映するには update を実行する")
            return 0

        if args.wcmd == "show":
            for key, value in worker_mod.show(args.name).items():
                shown = ", ".join(value) if isinstance(value, list) else value
                print(f"  {key:<12} {shown}")
            return 0
        if args.wcmd == "rm":
            out = worker_mod.remove(args.name, keep_profile=args.keep_profile)
            print(f"  ✓ {out['name']} を削除（プロファイル: {'削除' if out['profile_removed'] else '残置'}）")
            return 0

    if args.cmd == "workspace":
        if args.wpcmd == "verify":
            return 0 if ws.verify(log=_print) else 1
        if args.wpcmd == "build":
            return 0 if ws.build(warm=not args.no_warm, log=_print) else 1
        if args.wpcmd == "ca":
            ws.extract_ca(log=_print)
            return 0
        if args.wpcmd == "gc":
            ws.gc(log=_print)
            return 0

    if args.cmd == "mem0":
        if args.mcmd == "up":
            return 0 if mem0.up(log=_print) else 1
        if args.mcmd == "down":
            return 0 if mem0.down(log=_print) else 1
        if args.mcmd == "check":
            _print(f"起動中: {mem0.running()}")
            _print(f"記憶を引く役: {' '.join(mem0.memory_roles())}")
            return 0

    if args.cmd == "gateway":
        prof = getattr(args, "profile", None) or booking.gate_profile()
        if args.gcmd == "restart":
            fn = platform_ops.restart_when_idle if args.when_idle else platform_ops.restart_gateway
            return 0 if fn(prof, log=_print) else 1
        if args.gcmd == "status":
            _print(f"役: {prof}")
            _print(f"pid: {platform_ops.gateway_pid(prof) or '（動いていない）'}")
            _print(f"走行中カード: {platform_ops.running_cards()}")
            _print(platform_ops.autostart_hint())
            return 0

    if args.cmd == "install":
        res = install_mod.install(log=print)
        return 0 if res.ok() else 1

    if args.cmd == "uninstall":
        res = install_mod.uninstall(remove_profiles=args.profiles, log=print)
        return 0 if res.ok() else 1

    if args.cmd == "purge":
        res = maintain_mod.purge(confirm=args.yes, older_than=args.older_than, log=_print)
        return 0 if res.ok() else 1

    if args.cmd == "maintain":
        res = maintain_mod.maintain(log=_print)
        for line in res.lines:
            _print(line)
        return 0 if res.ok() else 1

    if args.cmd == "guest":
        code, out = booking.guest([a for a in args.rest if a != "--"])
        print(out.rstrip())
        return code

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
