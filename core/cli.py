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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kit",
        description="SEAOS のエージェント役一式を生成・導入・検査する",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("roles", help="役の一覧を出す（無効にした役も含む）")
    en = sub.add_parser("enable", help="役を有効にする（導入は次の update で行う）")
    en.add_argument("name")
    dis = sub.add_parser("disable", help="役を無効にする（反映・鍵の配布・検証から外す）")
    dis.add_argument("name")
    dis.add_argument("--remove-profile", action="store_true",
                     help="プロファイルも削除する（記憶とセッションは戻せない）")
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
    wsh = wsub.add_parser("share", help="この環境で作った役を、キットへ取り込む PR にする")
    wsh.add_argument("name")

    wrm = wsub.add_parser("rm", help="削除")
    wrm.add_argument("name")
    wrm.add_argument("--keep-profile", action="store_true", help="プロファイルは残す")

    mc = sub.add_parser("machine", help="この PC に、キットが要る道具が揃っているか（揃っていなければ入れる）")
    mcsub = mc.add_subparsers(dest="mcmd2", required=True)
    mck = mcsub.add_parser("check", help="道具ごとの状態（足りなければ終了コード 1）")
    mck.add_argument("--json", action="store_true", help="機械が読む形で出す")
    mci = mcsub.add_parser("install", help="台帳にある道具を入れる（台帳に無いものは断る）")
    mci.add_argument("tool")
    mcs = mcsub.add_parser("start", help="入っているが止まっている道具を起こす（docker）")
    mcs.add_argument("tool")

    fl = sub.add_parser("files", help="受け取ったファイルを、担当が読める場所へ置く")
    flsub = fl.add_subparsers(dest="fcmd", required=True)
    flk = flsub.add_parser("keep", help="置き場へ写し、置いた先のパスを出す（本文に書く）")
    flk.add_argument("paths", nargs="+", type=Path)

    wp = sub.add_parser("workspace", help="作業部屋（使い捨てコンテナ）")
    wpsub = wp.add_subparsers(dest="wpcmd", required=True)
    wpsub.add_parser("verify", help="建ててあるイメージの中身を確かめる")
    wpb = wpsub.add_parser("build", help="イメージを建てる")
    wpb.add_argument("--no-warm", action="store_true", help="キャッシュを温めない")
    wpsub.add_parser("ca", help="組織の TLS 傍受プロキシの CA を取り出す")
    wpsub.add_parser("gc", help="匿名ボリュームと dangling イメージだけ落とす")
    wpsub.add_parser("shell", help="作業部屋に入る（手で確かめるため）")

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

    sub.add_parser("install", help="全役を導入し、配布物に載らないものを揃える")
    unins = sub.add_parser("uninstall", help="撤去する（既定はキット自身の痕跡だけ）")
    unins.add_argument("--profiles", action="store_true", help="役のプロファイルも消す")

    gu = sub.add_parser("guest", help="ゲストのアクセス許可")
    gu.add_argument("rest", nargs=argparse.REMAINDER)

    pg = sub.add_parser("purge", help="archived のカードを物理削除する（戻せない）")
    pg.add_argument("--yes", action="store_true", help="実際に消す（既定は数えるだけ）")
    pg.add_argument("--older-than", type=int, default=0, metavar="日数",
                    help="この日数より古いものだけ。0 なら archived すべて")

    tm = sub.add_parser("timing", help="カードがどこで待たされたかを板の記録から出す")
    tm.add_argument("-n", "--limit", type=int, default=10, help="見る枚数（既定 10）")

    sub.add_parser("maintain", help="日次の保守一式（反映 → 掃除 → 検証）")

    return parser


def _cmd_roles(args: argparse.Namespace) -> int:
    enabled = set(roles.names())
    for name in roles.all_names():
        state = "" if name in enabled else "  （無効）"
        print(f"{name}{state}")
    return 0


def _cmd_enable_disable(args: argparse.Namespace) -> int:
    import selection

    try:
        if args.cmd == "enable":
            result = kit.enable_role(args.name, log=_print)
        else:
            result = kit.disable_role(args.name, remove_profile=args.remove_profile, log=_print)
    except selection.SelectionError as exc:
        _print(f"✗ {exc}")
        return 1
    return 0 if result.ok() else 1


def _cmd_build(args: argparse.Namespace) -> int:
    kit.build(log=_print)
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    result = kit.diff(log=_print)
    return 0 if result.ok() else 1


def _cmd_describe(args: argparse.Namespace) -> int:
    result = kit.sync_descriptions(log=_print)
    return 0 if result.ok() else 1


def _cmd_env(args: argparse.Namespace) -> int:
    result = kit.apply_env(log=_print)
    return 0 if result.ok() else 1


def _cmd_update(args: argparse.Namespace) -> int:
    result = kit.update(force_config=args.force_config, log=_print)
    return 0 if result.ok() else 1


def _cmd_doctor(args: argparse.Namespace) -> int:
    rep = doctor_mod.run(log=lambda l: print(l if l.startswith("=== ") or not l else f"  {l}"))
    print()
    print("✓ 問題なし" if rep.passed() else f"★ {rep.failures} 件の問題")
    return 0 if rep.passed() else 1


def _cmd_test(args: argparse.Namespace) -> int:
    ok, _lines = selftest.run(log=print)
    return 0 if ok else 1


def _cmd_upgrade(args: argparse.Namespace) -> int:
    ok = selfupdate.run(dry_run=args.dry_run, force_config=args.force_config, log=print)
    return 0 if ok else 1


def _cmd_worker(args: argparse.Namespace) -> int:
    if args.wcmd == "list":
        print(f"{'NAME':<20} {'ORIGIN':<9} {'MODEL':<24} {'DEPLOYED':<10} DESCRIPTION")
        for r in worker_mod.listing():
            mark = "yes" if r["deployed"] else "-"
            origin = "この環境" if r["origin"] == "local" else "配布"
            print(f"{r['name']:<20} {origin:<9} {r['model']:<24} {mark:<10} {r['description'][:36]}")
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

    if args.wcmd == "share":
        out = worker_mod.share(args.name, log=_print)
        return 0 if out.get("url") else 1

    if args.wcmd == "show":
        for key, value in worker_mod.show(args.name).items():
            shown = ", ".join(value) if isinstance(value, list) else value
            print(f"  {key:<12} {shown}")
        return 0
    if args.wcmd == "rm":
        out = worker_mod.remove(args.name, keep_profile=args.keep_profile)
        print(f"  ✓ {out['name']} を削除（プロファイル: {'削除' if out['profile_removed'] else '残置'}）")
        return 0
    return 2


def _cmd_machine(args: argparse.Namespace) -> int:
    import json

    import machine

    try:
        if args.mcmd2 == "check":
            rows = machine.status()
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            else:
                for r in rows:
                    state = ("✗ 足りない" if r["missing"] else
                             "✓" if r["installed"] else "- 入っていない（今は要らない）")
                    if r["installed"] and r.get("running") is False and r["name"] == "docker":
                        state = "✗ 止まっている" if r["missing"] else "- 止まっている"
                    used = f"（{', '.join(r['neededBy'])} が使う）" if r["neededBy"] else ""
                    _print(f"{r['label']:<12} {state} {used}")
            return 1 if any(r["missing"] for r in rows) else 0
        if args.mcmd2 == "install":
            res = machine.install(args.tool)
            _print(("✓ " if res["ok"] else "✗ ") + res["command"])
            if res["output"]:
                print(res["output"])
            if res["needsHuman"]:
                _print("人の操作が要ります（管理者の承認か、前提の道具）。上の出力を人に渡してください")
            return 0 if res["ok"] else (3 if res["needsHuman"] else 1)
        if args.mcmd2 == "start":
            ok = machine.start(args.tool)
            _print("✓ 動いています" if ok else "✗ 起動を確かめられませんでした（初回は利用規約の同意が要ることがあります）")
            return 0 if ok else 1
    except machine.MachineError as exc:
        _print(f"✗ {exc}")
        return 2
    return 2


def _cmd_files(args: argparse.Namespace) -> int:
    import files as files_mod

    try:
        # **パスだけを1行ずつ出す。** 窓口はこれをそのまま本文へ写す。
        files_mod.keep(args.paths, log=print)
    except files_mod.FilesError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_workspace(args: argparse.Namespace) -> int:
    if args.wpcmd == "verify":
        return 0 if ws.verify(log=_print) else 1
    if args.wpcmd == "build":
        return 0 if ws.build(warm=not args.no_warm, log=_print) else 1
    if args.wpcmd == "ca":
        ws.extract_ca(log=_print)
        return 0
    if args.wpcmd == "shell":
        return ws.shell()

    if args.wpcmd == "gc":
        ws.gc(log=_print)
        return 0
    return 2


def _cmd_mem0(args: argparse.Namespace) -> int:
    if args.mcmd == "up":
        return 0 if mem0.up(log=_print) else 1
    if args.mcmd == "down":
        return 0 if mem0.down(log=_print) else 1
    if args.mcmd == "check":
        _print(f"起動中: {mem0.running()}")
        _print(f"繋ぐ役: {' '.join(mem0.memory_roles())}")
        return 0
    return 2


def _cmd_gateway(args: argparse.Namespace) -> int:
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
    return 2


def _cmd_install(args: argparse.Namespace) -> int:
    res = install_mod.install(log=print)
    return 0 if res.ok() else 1


def _cmd_uninstall(args: argparse.Namespace) -> int:
    res = install_mod.uninstall(remove_profiles=args.profiles, log=print)
    return 0 if res.ok() else 1


def _cmd_purge(args: argparse.Namespace) -> int:
    res = maintain_mod.purge(confirm=args.yes, older_than=args.older_than, log=_print)
    return 0 if res.ok() else 1


def _cmd_timing(args: argparse.Namespace) -> int:
    import timing

    return timing.report(limit=args.limit, log=_print)


def _cmd_maintain(args: argparse.Namespace) -> int:
    res = maintain_mod.maintain(log=_print)
    for line in res.lines:
        _print(line)
    return 0 if res.ok() else 1


def _cmd_guest(args: argparse.Namespace) -> int:
    code, out = booking.guest([a for a in args.rest if a != "--"])
    print(out.rstrip())
    return code


# 下位コマンド -> 処理。**処理は core の関数を呼ぶだけ**にする（判断を皮に書かない）。
HANDLERS = {
    "roles": _cmd_roles,
    "enable": _cmd_enable_disable,
    "disable": _cmd_enable_disable,
    "build": _cmd_build,
    "diff": _cmd_diff,
    "describe": _cmd_describe,
    "env": _cmd_env,
    "update": _cmd_update,
    "doctor": _cmd_doctor,
    "test": _cmd_test,
    "upgrade": _cmd_upgrade,
    "worker": _cmd_worker,
    "machine": _cmd_machine,
    "files": _cmd_files,
    "workspace": _cmd_workspace,
    "mem0": _cmd_mem0,
    "gateway": _cmd_gateway,
    "install": _cmd_install,
    "uninstall": _cmd_uninstall,
    "purge": _cmd_purge,
    "timing": _cmd_timing,
    "maintain": _cmd_maintain,
    "guest": _cmd_guest,
}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return HANDLERS[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
