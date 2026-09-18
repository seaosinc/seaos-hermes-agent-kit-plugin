"""設定漏れの検証。**壊れていることに気づく唯一の手段。**

zsh 版の `hermes-kit doctor` を移したもの。各検査は「何が起きるか」を添えて
返す——「✗ 〜が無い」だけでは、直すべきかどうかが分からないため。

booking / hotl / workspace / mem0 の検査は、それぞれのモジュールが持つ。
ここは束ねる側で、**判定の中身を二重に持たない。**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

import yaml

import booking
import check_mcp_tools
import hermes
import hotl
import mem0
import refcheck
import roles
import workspace
from paths import hermes_home, profile_dir, profiles_dir

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
    known = set(roles.all_names())
    enabled = set(roles.names())
    found = False
    root = profiles_dir()
    if root.is_dir():
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            # `.deleted` のような作業ディレクトリは役ではない。
            # ドット始まりを役として数えると、doctor が毎回赤くなる。
            if d.name.startswith(".") or d.name == "default":
                continue
            if d.name in known and d.name not in enabled:
                # **外した役のプロファイルは、残すと決めたもの。** 壊れてはいないが、
                # 説明文で「選ぶな」と書いてあるだけで、担当には書けてしまう。
                rep.note(f"{d.name} は無効にしてあるが、プロファイルは残っている（説明文で担当から外している）")
                continue
            if d.name in known:
                continue
            rep.ng(f"{d.name} は配置表に無いのに実機に残っている")
            rep.lines.append("    振られたカードは静かに止まる（SOUL も規約も配られていない）")
            rep.lines.append(f"    hermes profile delete {d.name}")
            found = True
    if not found:
        rep.ok("実機の役は配置表と一致している")


def _orphan_secrets(rep: Report) -> None:
    """**役が消えたのに残っている鍵を掃除する。**

    役つきの名前（`PROJECT_BOT__SLACK_BOT_TOKEN`）は、その役が居なくなると
    管理対象から外れ、**値が入ったまま正の `.env` に取り残される**（実際に残った）。
    使われないだけでなく、同じ名前の役を作り直したときに古い値が蘇る。
    """
    import env as env_mod

    source = env_mod.read_env(env_mod.env_file())
    managed = set(roles.managed_env_vars())
    orphans = [k for k in source if "__" in k and k not in managed]
    if not orphans:
        return
    for key in orphans:
        env_mod.drop_value(key)
    rep.note(f"役が消えたのに残っていた鍵を外した: {' '.join(orphans)}")


def _stale_tombstones(rep: Report) -> None:
    """**実在しない役の「削除済み」の印を掃除する。**

    `hermes profile delete` が置く印は、入れ直しても消えない。同じ名前で作り直すと
    フォルダが実在しても「存在しない」と扱われ、`hermes -p <役>` も `profile list` も
    見つけられなくなる。**実際に8役ぶん踏んだ。**

    フォルダが無いなら印は用済みなので、ここで外す。
    """
    marker_dir = profiles_dir() / ".deleted"
    if not marker_dir.is_dir():
        return
    cleared = []
    for marker in sorted(marker_dir.glob("*")):
        if marker.is_file() and not (profiles_dir() / marker.name).is_dir():
            marker.unlink()
            cleared.append(marker.name)
    if cleared:
        rep.note(f"使われていない削除済みの印を外した: {' '.join(cleared)}")


def _slack_token_holders(rep: Report) -> None:
    """**キットの窓口と同じ Slack トークンを、キットの外が持っていないか。**

    ボットは1つのゲートウェイにしか繋がらない。キットより前に default へ Slack を
    設定していると（`~/.hermes/.env`）、Hermes Desktop が default のゲートウェイを
    起こしたときに**窓口を奪われ、operator が黙って止まる。** Slack からは返事が
    来るので気づけず、operator の規約（カードの作り方、受け取ったファイルの渡し方）
    だけが効かなくなる。キットは default を管理しないので、ここで言う。

    値は出さない。どの窓口のトークンと、どのファイルが重なっているかだけを言う。
    """
    import env as env_mod

    rep.section("Slack の窓口が奪われていないか")
    ours: dict = {}
    for name in roles.names():
        token = env_mod.read_env(profile_dir(name) / ".env").get("SLACK_BOT_TOKEN")
        if token:
            ours.setdefault(token, name)
    if not ours:
        rep.note("Slack に繋ぐ窓口が無い")
        return
    candidates = [hermes_home() / ".env"]
    root = profiles_dir()
    if root.is_dir():
        known = set(roles.names())
        candidates += [d / ".env" for d in sorted(root.iterdir())
                       if d.is_dir() and not d.name.startswith(".") and d.name not in known]
    clashes = []
    for path in candidates:
        token = env_mod.read_env(path).get("SLACK_BOT_TOKEN")
        if token and token in ours:
            clashes.append((path, ours[token]))
    if not clashes:
        rep.ok("キットの窓口のトークンは、キットの外に無い")
        return
    for path, role in clashes:
        rep.ng(f"{path} が {role} と同じ Slack トークンを持っている（ゲートウェイが起きると {role} が止まる）")
        rep.lines.append(f"    {path} から SLACK_* を外し、seaos-kit gateway restart {role}")


def _profiles(rep: Report) -> None:
    rep.section("各役")
    specs = roles.all_specs()

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
        else:
            rep.ng("toolsets に kanban が無い → カードを扱えない")

        # **置いただけでは動かない。** 既存の役は update で config が上書きされないので、
        # 配布物で有効にしたつもりでも無効のまま残りうる（kit.enable_plugins が直す）
        enabled = set(((cfg.get("plugins") or {}).get("enabled")) or [])
        for plugin in roles.generator().plugins_of(specs.get(name) or {}, with_self=True):
            if plugin in enabled:
                rep.ok(f"プラグイン {plugin} が有効")
            else:
                rep.ng(f"プラグイン {plugin} が無効 → seaos-kit update")

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


# **窓口が使う権限と、欠けたときに起きること。** Slack は欠けていても接続を拒まない。
# 返事は届くのに、その操作のときだけ `missing_scope` で黙って失敗する
# （files:write が無く、画像を返せなかった）。
SLACK_SCOPES = {
    "chat:write": "返事を書けない",
    "app_mentions:read": "チャンネルでメンションしても反応しない",
    "im:history": "DM が届かない",
    "files:read": "添付されたファイルを読めない",
    "files:write": "画像やファイルを返せない",
    # 通知の宛先はユーザー ID で届く。文章はそのまま送れるが、ファイルは
    # DM を開いて（conversations.open）チャンネル ID に直さないと送れない。
    "im:write": "カードの成果物（スクショなど）を DM へ返せない",
}


def _slack_granted_scopes(token: str) -> Optional[set]:
    """トークンに付いている権限。**`auth.test` の応答ヘッダ（x-oauth-scopes）が持っている。**"""
    import json
    import urllib.request

    req = urllib.request.Request("https://slack.com/api/auth.test", data=b"", method="POST",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            header = r.headers.get("x-oauth-scopes")
            body = json.loads(r.read() or b"{}")
    except Exception:  # noqa: BLE001
        return None
    if not body.get("ok") or header is None:
        return None
    return {s.strip() for s in header.split(",") if s.strip()}


def _slack_scopes(rep: Report) -> None:
    """**窓口の Slack App に、要る権限が付いているか。**

    App を古い手順で作ったり、後から権限を足さなかったりすると欠ける。
    足したら App を再インストールする（トークンは変わらない）。
    """
    import env as env_mod

    rep.section("Slack App の権限")
    holders = [(name, env_mod.read_env(profile_dir(name) / ".env").get("SLACK_BOT_TOKEN"))
               for name in roles.names()]
    holders = [(name, token) for name, token in holders if token]
    if not holders:
        rep.note("Slack に繋ぐ窓口が無い")
        return
    for name, token in holders:
        granted = _slack_granted_scopes(token)
        if granted is None:
            rep.note(f"{name}: 権限を確かめられなかった（トークンが無効か、Slack に届かない）")
            continue
        missing = [s for s in SLACK_SCOPES if s not in granted]
        if not missing:
            rep.ok(f"{name}: 要る権限が揃っている")
            continue
        for scope in missing:
            rep.ng(f"{name}: {scope} が無い（{SLACK_SCOPES[scope]}）")
        rep.lines.append("    Slack App の OAuth & Permissions → Bot Token Scopes に足し、App を再インストールする")


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
    known = set(roles.all_names())
    stale = [r["name"] for r in rows if not r.get("on_disk") and (r.get("counts") or {})]
    unknown = [r["name"] for r in rows if r.get("on_disk") and r["name"] not in known and r["name"] != "default"]
    if unknown:
        rep.ng(f"配置表に無い担当が実在する: {' '.join(unknown)}")
    else:
        rep.ok("担当はすべて配置表にある")
    if stale:
        rep.note(f"過去の担当（実体なし・履歴のみ）: {' '.join(stale)}")


def run(log: Optional[Log] = None, *, deep: bool = True) -> Report:
    rep = Report()

    _orphan_profiles(rep)
    _stale_tombstones(rep)
    _orphan_secrets(rep)
    _profiles(rep)
    _slack_token_holders(rep)
    if deep:
        _slack_scopes(rep)
    _env_hint(rep)
    _assignees(rep)

    # **規約が名指しした名前の実在確認。** 書いてあるのに無い、が一番静かに壊れる
    # ——エージェントは呼べないまま「できない」と正しく報告して止まるだけなので、
    # 綴りの誤りが世代を越えて残る。
    rep.section("規約が名指しした名前（コマンド・道具・スキル・役）")
    refcheck.run(rep, deep=deep)

    # **MCP の allowlist は綴りを間違えても黙って落ちる。** 実在しない名前を
    # 8個並べたまま、担当が「取れない前提」のカードを4時間ぶん立てた事故がある。
    if deep:
        rep.section("MCP の allowlist（サーバに実在するか）")
        check_mcp_tools.run(rep)

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
