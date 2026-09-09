"""設定漏れの検証。**壊れていることに気づく唯一の手段。**

zsh 版の `hermes-kit doctor` を移したもの。各検査は「何が起きるか」を添えて
返す——「✗ 〜が無い」だけでは、直すべきかどうかが分からないため。

booking / hotl / workspace / mem0 の検査は、それぞれのモジュールが持つ。
ここは束ねる側で、**判定の中身を二重に持たない。**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import yaml

import booking
import hermes
import hotl
import mem0
import roles
import workspace
from paths import profile_dir, profiles_dir

Log = Callable[[str], None]


@dataclass
class Report:
    lines: List[str] = field(default_factory=list)
    failures: int = 0

    def ok(self, msg: str) -> None:
        self.lines.append(f"✓ {msg}")

    def ng(self, msg: str) -> None:
        self.lines.append(f"✗ {msg}")
        self.failures += 1

    def note(self, msg: str) -> None:
        self.lines.append(f"= {msg}")

    def section(self, title: str) -> None:
        self.lines.append("")
        self.lines.append(f"=== {title} ===")

    def passed(self) -> bool:
        return self.failures == 0


def _orphan_profiles(rep: Report) -> None:
    """配置表に無い役が実機に残っていないか。

    **doctor は配置表を順に見る**ので、表から消した役はどの検査にも入らない。
    一方 Hermes は `profiles/` にあるものを実在として扱い、担当にも書ける
    ——**SOUL も規約も配られていないので、振られたカードは静かに止まる。**
    """
    rep.section("配置表に無い役が残っていないか")
    known = set(roles.names())
    found = False
    root = profiles_dir()
    if root.is_dir():
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            # `.deleted` のような作業ディレクトリは役ではない。
            # ドット始まりを役として数えると、doctor が毎回赤くなる。
            if d.name.startswith(".") or d.name in known or d.name == "default":
                continue
            rep.ng(f"{d.name} は配置表に無いのに実機に残っている")
            rep.lines.append("    振られたカードは静かに止まる（SOUL も規約も配られていない）")
            rep.lines.append(f"    hermes profile delete {d.name}")
            found = True
    if not found:
        rep.ok("実機の役は配置表と一致している")


def _profiles(rep: Report) -> None:
    rep.section("各役")
    specs = roles.all_specs()
    board_less = set(roles.without_board())

    for name in roles.names():
        rep.lines.append(f"--- {name}")
        d = profile_dir(name)
        cfg_path = d / "config.yaml"
        if not d.is_dir():
            rep.ng(f"プロファイルが無い → hermes profile install dist/{name}")
            continue

        dist = d / "distribution.yaml"
        if dist.is_file():
            version = ""
            for line in dist.read_text(encoding="utf-8").splitlines():
                if line.startswith("version:"):
                    version = line.split(":", 1)[1].strip()
                    break
            rep.ok(f"配布物として導入済み（v{version}）")
        else:
            rep.ng(f"配布物になっていない → hermes profile install dist/{name} --force")

        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
        cfg = cfg or {}

        toolsets = cfg.get("toolsets") or []
        if "kanban" in toolsets:
            rep.ok("toolsets に kanban")
        elif name in board_less:
            # **板に載らない役は例外である。** 咎めると doctor が毎回赤くなり、
            # 本物の異常が埋もれる。
            rep.ok("toolsets に kanban 無し（板に載らない役として意図的）")
        else:
            rep.ng("toolsets に kanban が無い → カードを扱えない")

        soul = d / "SOUL.md"
        if soul.is_file() and soul.stat().st_size and "SHARED:BEGIN" in soul.read_text(encoding="utf-8"):
            rep.ok("SOUL.md（共通ブロック込み）")
        else:
            rep.ng("SOUL.md か共通ブロックが無い → build して入れ直す")

        for skill in specs.get(name, {}).get("skills") or []:
            if (d / "skills" / skill / "SKILL.md").is_file():
                rep.ok(skill)
            else:
                rep.ng(f"{skill} が入っていない")

        model = ((cfg.get("model") or {}).get("default")) or ""
        deleg = ((cfg.get("delegation") or {}).get("model")) or ""
        rep.ok(f"model={model}") if model else rep.ng("model が空")
        if deleg:
            rep.ok(f"delegation={deleg}")
        else:
            rep.ng("delegation.model が空 → 子が HTTP 400 で即死する")

        # **terminal を持たない役がある。** 他人が書いた文章を読む役は、
        # コマンドを実行する経路そのものを持たせない設計（生成器の shell: false）。
        # 一律に要求すると、意図した構成を「壊れている」と言ってしまう。
        tools = (cfg.get("platform_toolsets") or {}).get("cli") or []
        shellless = not specs.get(name, {}).get("shell", True)
        if shellless:
            if "terminal" in tools:
                rep.ng("terminal が有効 → この役はコマンドを実行しない設計")
            else:
                rep.ok("terminal 無し")
        else:
            if "terminal" in tools:
                rep.ok("terminal")
            else:
                rep.ng("terminal が無効 → archive/unlink できない")


def _env_hint(rep: Report) -> None:
    """実測した環境が各役に載っているか。

    **配布物に無いものは、config を入れ替えると黙って消える。** 消えても
    エージェントは動くので、気づく手段がここにしか無い（実際に全役から消えていた）。
    """
    rep.section("環境の実測（agent.environment_hint）")
    missing: List[str] = []
    for name in roles.names():
        path = profile_dir(name) / "config.yaml"
        if not path.is_file():
            continue
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        hint = ((cfg.get("agent") or {}).get("environment_hint") or "").strip()
        if not hint:
            missing.append(name)
    if missing:
        rep.ng(f"environment_hint が無い: {' '.join(missing)}")
    else:
        rep.ok("全役に載っている")


def _assignees(rep: Report) -> None:
    """担当が実在するか（kanban の assignee と配置表の突き合わせ）。"""
    rep.section("担当が実在するか")
    code, out = hermes.run(["kanban", "assignees", "--json"])
    if code != 0:
        rep.note("kanban が応答しない（板が未初期化かもしれない）")
        return
    try:
        import json

        rows = json.loads(out)
    except Exception:  # noqa: BLE001
        rep.note("assignees を読めなかった")
        return
    known = set(roles.names())
    stale = [r["name"] for r in rows if not r.get("on_disk") and (r.get("counts") or {})]
    unknown = [r["name"] for r in rows if r.get("on_disk") and r["name"] not in known and r["name"] != "default"]
    if unknown:
        rep.ng(f"配置表に無い担当が実在する: {' '.join(unknown)}")
    else:
        rep.ok("担当はすべて配置表にある")
    if stale:
        rep.note(f"過去の担当（実体なし・履歴のみ）: {' '.join(stale)}")


def run(log: Optional[Log] = None) -> Report:
    rep = Report()

    _orphan_profiles(rep)
    _profiles(rep)
    _env_hint(rep)
    _assignees(rep)

    rep.section("HOTL（承認を待たない設定）")
    if not hotl.check(log=rep.lines.append):
        rep.failures += 1

    rep.section("全役の共有記憶（mem0）")
    if mem0.running():
        rep.ok("mem0 が動いている")
        for name in mem0.memory_roles():
            target = profile_dir(name) / "mem0.json"
            rep.ok(f"{name} が mem0 を参照") if target.is_file() else rep.ng(f"{name} が mem0 を参照していない")
    else:
        rep.note("mem0 は動いていない（Docker が無い環境では正常）")

    rep.section("アクセスゲート（booking-gate）")
    if not booking.check(log=rep.lines.append):
        rep.failures += 1

    rep.section("作業部屋")
    boxed = workspace.boxed_roles()
    rep.note(f"箱を持つ役: {' '.join(boxed) or '（なし）'}")
    try:
        cfg = workspace.settings()
        code, _out = workspace.docker("image", "inspect", cfg["image"])
        rep.ok(f"イメージがある（{cfg['image']}）") if code == 0 else rep.ng(
            f"イメージが無い（{cfg['image']}）→ workspace build")
    except workspace.WorkspaceError as exc:
        rep.note(str(exc))

    if log:
        for line in rep.lines:
            log(line)
    return rep
