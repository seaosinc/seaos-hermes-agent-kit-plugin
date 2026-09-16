#!/usr/bin/env python3
"""配布物の生成器の回帰テスト。

    ~/.hermes/hermes-agent/venv/bin/python tests/build_distributions_test.py

生成物は `hermes profile install` にそのまま食わせるものなので、**壊れていても
インストールは通ってしまい、動かして初めて分かる**。ここで形を固定する。

入っているのは実際に踏んだ間違いばかりである——config を置き換えたら
platform_toolsets が消えて slack の terminal が落ちた、プラグインを置いたのに
enabled になっていなかった、役を消しても配布物が残った。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import build_distributions as bd  # noqa: E402

from _harness import check, finish  # noqa: E402


def build_once() -> Path:
    out = Path(tempfile.mkdtemp(prefix="dist-test-"))
    bd.build(ROOT, out)
    return out


OUT = build_once()


def cfg(role: str) -> dict:
    return yaml.safe_load((OUT / role / "config.yaml").read_text(encoding="utf-8"))


def manifest(role: str) -> dict:
    return yaml.safe_load((OUT / role / "distribution.yaml").read_text(encoding="utf-8"))


def test_roles_exist():
    """固定3役と業務別ワーカーが揃っているか。"""
    got = sorted(p.name for p in OUT.glob("*") if p.is_dir())
    for role in ("operator", "fixer", "developer", "handler"):
        assert role in got, f"{role} が無い: {got}"


def test_soul_has_shared_block():
    """共通ブロックが差し込まれているか。**配布物は独立しているのでここが唯一の経路。**"""
    for role in ("operator", "fixer", "developer", "handler"):
        soul = (OUT / role / "SOUL.md").read_text(encoding="utf-8")
        assert "<!-- SHARED:BEGIN -->" in soul, f"{role}: 共通ブロックが無い"
        assert "## すべての役割に共通の作法" in soul, f"{role}: AGENT-BASICS が無い"
        assert "## 言葉づかい" in soul, f"{role}: UBIQUITOUS が無い"
        assert soul.startswith(f"あなたの名前は **{role}**"), f"{role}: 1行目が名乗りでない"


def test_worker_placeholders_expanded():
    """ワーカーの雛形（{{NAME}} / {{WORKER_BASE}} / {{EXTRA}}）が展開されているか。"""
    soul = (OUT / "handler" / "SOUL.md").read_text(encoding="utf-8")
    for ph in ("{{NAME}}", "{{WORKER_BASE}}", "{{EXTRA}}"):
        assert ph not in soul, f"{ph} が残っている"
    assert "WORKER-BASE:BEGIN" in soul, "ワーカー共通規約が差し込まれていない"


def test_platform_toolsets_carry_terminal():
    """config を置き換えると消える設定。**terminal が無いと archive / unlink ができない。**"""
    for role in ("operator", "fixer"):
        pt = cfg(role).get("platform_toolsets") or {}
        for plat in ("cli", "slack"):
            assert "terminal" in (pt.get(plat) or []), f"{role}/{plat}: terminal が無い"
            assert "kanban" in (pt.get(plat) or []), f"{role}/{plat}: kanban が無い"


def test_plugin_is_enabled():
    """プラグインは置くだけでは動かない。**enabled に入っていること。**"""
    c = cfg("operator")
    assert (OUT / "operator/plugins/booking-gate/plugin.yaml").exists(), "プラグインが無い"
    assert "booking-gate" in ((c.get("plugins") or {}).get("enabled") or []), "有効になっていない"


def test_gate_ships_complete():
    """ゲートはプラグイン・ポーラー・スクリプトが揃って初めて動く。"""
    o = OUT / "operator"
    assert (o / "hooks/mem0-up/HOOK.yaml").exists(), "フックが無い"
    assert (o / "scripts/booking_sync.py").exists(), "ポーラーが無い"
    assert (o / "scripts/booking_guest.py").exists(), "guest の実体が無い"


def test_cron_jobs_are_not_shipped():
    """**cron/jobs.json を配布物に入れない。**

    入れると `profile update` のたびに、スケジューラが持っている状態
    （id / next_run_at / last_run_at）が骨だけの版で上書きされる。
    kit-sync が10分ごとに update を回すので、10分ごとにジョブが死ぬ——実際に死んだ。
    登録は公式の `hermes cron create`（hermes-kit install が冪等にやる）。
    """
    for role in ("operator", "fixer", "developer", "handler", "recruiter"):
        assert not (OUT / role / "cron").exists(), f"{role}: cron/ を配ってはいけない"
        owned = manifest(role)["distribution_owned"]
        assert "cron/" not in owned, f"{role}: cron/ を所有物に入れてはいけない"


def test_cron_scripts_are_shipped():
    """スクリプトは配る。cron はプロファイル配下の scripts/ しか実行しない。"""
    o = OUT / "operator"
    for name, (_expr, script) in bd.CRON_JOBS.items():
        assert (o / "scripts" / script).exists(), f"{name}: {script} が同梱されていない"
    assert "scripts/" in manifest("operator")["distribution_owned"]


def test_hotl_only_for_agent_creator():
    """承認を切るのは recruiter だけ。**他が緩むと任意の命令ファイルを書き換えられる。**"""
    assert cfg("recruiter")["approvals"]["mode"] == "off"
    assert cfg("recruiter")["security"]["protected_instruction_files"] is False
    for role in ("operator", "fixer", "developer", "handler"):
        assert "approvals" not in cfg(role), f"{role} が HOTL になっている"


def test_delegation_closed_for_workers():
    """ワーカーと developer は子エージェントを立てない（設定でも閉じる）。"""
    for role in ("developer", "handler", "recruiter"):
        dis = (cfg(role).get("agent") or {}).get("disabled_toolsets") or []
        assert "delegation" in dis, f"{role}: delegation が開いている"
    assert "delegation" not in ((cfg("operator").get("agent") or {}).get("disabled_toolsets") or [])


def test_manifest_declares_env_and_ownership():
    """秘密は配布物に入れず、環境変数として宣言する。"""
    m = manifest("operator")
    names = {e["name"] for e in m["env_requires"]}
    assert "SLACK_BOT_TOKEN" in names and "OPENROUTER_API_KEY" in names, names
    owned = set(m["distribution_owned"])
    assert {"SOUL.md", "config.yaml", "plugins/", "scripts/"} <= owned, owned
    # **`skills/` とまとめて持たない。** 持ち物のフォルダは更新のたびに rmtree
    # されるので、まとめて宣言すると実機で生えたスキルが毎回消える。
    assert "skills/" not in owned and "skills" not in owned, owned
    for name in bd.skills_of(ROOT, "operator"):
        assert f"skills/{name}" in owned, (name, owned)
    # .env は配布物に含めない（公式が除外するが、こちらでも作らない）
    assert not (OUT / "operator/.env").exists()


def test_gateway_keys_are_per_role():
    """**窓口ごとに鍵を分ける。共有の値へは落ちない。**

    同じ Slack トークンで2つのゲートウェイを繋ぐと、**両方が同じ発言を拾って
    二重に返事をする。** 共有へ落ちる実装だと、窓口を足した瞬間にそうなる
    （実際に踏んだ）。役つきの名前（`OPERATOR__SLACK_BOT_TOKEN`）だけを見る。
    """
    import sys as _sys

    _sys.path.insert(0, str(ROOT / "core"))
    import roles as roles_mod

    own = roles_mod.own_env_vars("operator")
    assert "SLACK_BOT_TOKEN" in own, own
    assert roles_mod.env_key("project-operator", "SLACK_BOT_TOKEN") == \
        "PROJECT_OPERATOR__SLACK_BOT_TOKEN"
    # 管理対象は役つきの名前だけ（共有の名前は残さない）
    managed = roles_mod.managed_env_vars()
    assert "SLACK_BOT_TOKEN" not in managed, managed
    assert "OPERATOR__SLACK_BOT_TOKEN" in managed, managed


def test_local_roles_live_outside_the_kit():
    """**この環境で作った役は、キットの外に置く。**

    キットの中（`templates/workers/`）に作ると配布のたびに危うい——
    `hermes plugins update` は untracked も stash して戻すので、同じパスに
    配布物が来れば衝突して stash に取り残される。`plugins install --force` なら
    フォルダごと置き換わって消える。

    生成器は両方を見て、同じ名前ならローカルを採る（配布物で黙って上書きすると、
    この環境で育てた役が理由も分からず別物に入れ替わる）。
    """
    import sys as _sys
    import tempfile

    _sys.path.insert(0, str(ROOT / "core"))

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        old = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(home)
        try:
            local = home / "seaos-kit" / "workers" / "probe-x"
            local.mkdir(parents=True)
            (local / "profile.yaml").write_text(
                "name: probe-x\ndescription: 確認用\nsummary: 確認用の役\n", encoding="utf-8")
            (local / "SOUL.md").write_text(
                "あなたの名前は **{{NAME}}** である。\n\n{{WORKER_BASE}}\n\n{{EXTRA}}\n",
                encoding="utf-8")

            dirs = [d.name for d in bd.worker_dirs(ROOT)]
            assert "probe-x" in dirs, dirs
            roles = bd.worker_roles(ROOT)
            assert roles["probe-x"]["dir"] == local, roles["probe-x"].get("dir")
            # キットの中には作られていないこと
            assert not (ROOT / "templates" / "workers" / "probe-x").exists()
        finally:
            if old is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = old


def test_worker_keys_are_optional_by_default():
    """**役を1つ足しただけで設定画面が止まらないこと。**

    `required` は「無いとキット自体が成り立たない」という意味で、いまそれに
    当たるのはモデルの鍵だけ。ワーカーの鍵を必須にすると `/validate` が塞がり、
    **全役の「反映」が押せなくなる**（実際にそうなっていた）。
    欠けても困るのはその役の道具であって、チーム全体ではない。
    """
    import sys as _sys
    import tempfile

    _sys.path.insert(0, str(ROOT / "core"))
    import worker as worker_mod

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "profile.yaml").write_text("name: probe\n", encoding="utf-8")
        worker_mod.add_env(d, "PROBE_TOKEN", "確認用")
        body = (d / "profile.yaml").read_text(encoding="utf-8")
        assert "required: false" in body, body


def test_every_role_has_a_human_summary():
    """**設定画面に出る一行は、役が自分で名乗る。**

    以前は API 側にベタ書きの表があり、**新しい役はそこに載っていない**ので
    describe（decomposer 向けの長文）を40字で切って出していた——文の途中で
    切れて読めなかった。表を配置表へ移し、ワーカーは profile.yaml に書く。
    """
    specs = {**bd.ROLES, **bd.worker_roles(ROOT)}
    for role in specs:
        text = (specs[role].get("summary") or "").strip()
        assert text, f"{role} に summary が無い"
        assert len(text) <= 40, f"{role} の summary が長い（{len(text)}字）: {text}"
        # 途中で切れていないこと
        assert not text.endswith("…"), role


def test_version_is_derived_from_git():
    """**版は固定値にしない。** 固定だと「更新が届いたのか」を判定できない。

    旧キットは全役が `0.1.0` のまま動かず、実機を見ても新旧が分からなかった。
    コミット数は単調に増えるので大小を比べられ、sha はどの木から出たかを指す。
    Hermes 側は `+` 以降を剥がすので（profile_distribution の `_parse_semver`）、
    この形で壊れない。
    """
    import re

    version = manifest("operator")["version"]
    assert re.fullmatch(r"0\.1\.\d+\+[0-9a-f]{7,}", version), version
    # 全役で揃っていること（役ごとにずれると比較の意味が無くなる）
    for role in ("fixer", "handler", "recruiter"):
        assert manifest(role)["version"] == version, role


def test_only_truly_required_keys_are_required():
    """**必須は「無いとキット自体が成り立たない」ものだけ。**

    欠けても道具が1つ使えなくなるだけの鍵まで必須にすると、設定画面が
    止まって誰も先へ進めない。Hermes のゲートウェイは認証情報が無くても
    落ちず、板と cron は動き続ける（gateway/run_startup.py の
    "degrade gracefully and allow cron jobs to run"）。

    いま必須なのは OPENROUTER_API_KEY だけ——全役の全モデル呼び出しが通る。
    """
    specs = {**bd.ROLES, **bd.worker_roles(ROOT)}
    required = {entry[0] for spec in specs.values()
                for entry in (spec.get("env") or []) if entry[2]}
    assert required == {"OPENROUTER_API_KEY"}, required


def test_mcp_without_keys_ships_disabled():
    """**鍵が来ないサーバは、既定で無効で配ること。**

    空トークンでもサーバは繋がって道具の一覧まで出し、**呼んだときだけ 400**
    を返す。役から見ると「手はあるのに毎回失敗する」状態になる。

    宣言（env_requires）に無い変数を参照しているなら、その鍵は配られない。
    そのときは `enabled: false` で出すこと——handler の Slack が該当する
    （Slack の鍵は operator だけ、という決めがあるため配られない）。
    鍵が配られれば `env apply` が自動で有効に戻す。
    """
    specs = {**bd.ROLES, **bd.worker_roles(ROOT)}
    for role, spec in specs.items():
        declared = {entry[0] for entry in (spec.get("env") or [])}
        servers = ((yaml.safe_load((OUT / role / "config.yaml").read_text(encoding="utf-8"))
                    or {}).get("mcp_servers") or {})
        for server, needed in bd.mcp_env_vars(ROOT, role).items():
            missing = [v for v in needed if v not in declared]
            if not missing:
                continue
            state = (servers.get(server) or {}).get("enabled", True)
            assert state is False, (
                f"{role}/{server} は {', '.join(missing)} が配られないのに有効で出ている")


def test_secrets_are_not_shipped():
    """生成物に秘密が紛れていないか。"""
    for path in OUT.rglob("*"):
        if not path.is_file() or path.suffix in (".db",):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for needle in ("xoxb-", "xapp-", "sk-", "OPENROUTER_API_KEY="):
            assert needle not in text, f"{path.name} に {needle} が入っている"


def test_stale_role_is_removed():
    """役を消したら配布物も消える。**残すと templates に無い役が install できてしまう。**"""
    ghost = OUT / "ghost-worker"
    ghost.mkdir()
    (ghost / "distribution.yaml").write_text("name: ghost-worker\n", encoding="utf-8")
    bd.build(ROOT, OUT)
    assert not ghost.exists(), "消えた役の配布物が残っている"


# ---------------------------------------------------------------- 作業部屋
# DESIGN.md。**イメージ名がずれると担当は起動した瞬間に落ちる**ので、
# 「生成器が唯一の正」であることを形の側で固定する。

def test_workspace_roles_get_terminal_block():
    for role in ("developer",):
        t = cfg(role).get("terminal") or {}
        # env_type ではなく backend。既定の backend: local が env_type を上書きするため
        assert t.get("backend") == "docker", f"{role}: backend が docker ではない ({t.get('backend')})"
        assert "env_type" not in t, f"{role}: env_type は効かない（backend で書く）"
        # ディスパッチャがホスト側のパスを TERMINAL_CWD に焼くので、config で上書きが要る
        assert t.get("cwd") == "/workspace", f"{role}: cwd が /workspace ではない ({t.get('cwd')})"
        # **true で固定する。** false は「セッションごとに部屋を立て、終わったら壊す」
        # という意味であって（terminal_tool.py:1387 _session_isolation_enabled）、
        # clone した成果がコマンドの合間に消え、以後の terminal が全部
        # `No such container` で落ちる。調べるだけのカードは1コマンドで完結するので
        # 落ちず、**clone を伴う実装カードだけ**が落ちるため気づきにくい。
        # true は「プロファイルに1つの長命な部屋を、全セッションで共有する」である
        # （terminal_tool.py:1423）。
        assert t.get("container_persistent") is True, f"{role}: 部屋が使い捨てで、clone が次の操作へ渡らない"
        vols = t.get("docker_volumes") or []
        assert any(v.endswith(":/cache") for v in vols), f"{role}: /cache が無い ({vols})"
        # 成果物の受け渡し口。**左右が同じパス**でないと artifacts がホストで解決できない
        same = [v for v in vols if v.count(":") == 1 and v.split(":")[0] == v.split(":")[1]]
        assert same, f"{role}: 成果物の受け渡し口が無い、または左右がずれている ({vols})"
        # 鍵はイメージに焼かず、ホストの値を名前で転送する
        fwd = t.get("docker_forward_env") or []
        assert "GH_TOKEN" in fwd, f"{role}: GH_TOKEN が渡らない"
        # 渡さないと規約が指す $HERMES_KANBAN_WORKSPACE が箱の中で空になり、
        # 成果物の宣言が / 直下を指す（実際に踏んだ）
        assert "HERMES_KANBAN_WORKSPACE" in fwd, f"{role}: 成果物の置き場が箱に届かない"
        # 委譲先のモデルを固定する。既定のままだとツールを実行できないモデルに当たり、
        # 「エラーだけ返して何もしない」という気づきにくい失敗になる
        model = (t.get("docker_env") or {}).get("OPENCODE_MODEL", "")
        assert model.count("/") >= 2, f"{role}: OPENCODE_MODEL が provider/model 形式でない ({model})"


def test_agent_creator_stays_on_the_host():
    # プロファイルを書き換える役。箱に入れるとホストのファイルに届かず、仕事ができない
    assert "terminal" not in cfg("recruiter"), "recruiter が箱に入っている"


def test_workspace_recipe_is_shipped():
    for role in ("developer",):
        d = OUT / role / "workspace"
        assert (d / "Dockerfile").exists(), f"{role}: Dockerfile が無い"
        assert (d / "profile.sh").exists(), f"{role}: profile.sh が無い"
        assert "workspace/" in manifest(role)["distribution_owned"], f"{role}: 所有に無い"
    # 箱を使わない役には要らない
    assert not (OUT / "operator" / "workspace").exists(), "operator に作業部屋が付いている"


def test_image_name_has_one_source():
    # config が指す名前と、zsh 側が引く名前（--workspace）が一致すること
    for role in ("developer",):
        assert cfg(role)["terminal"]["docker_image"] == bd.WORKSPACE_IMAGE, f"{role}: 名前がずれている"


def test_workspace_roles_declare_gh_token():
    for role in ("developer",):
        names = [e["name"] for e in manifest(role)["env_requires"]]
        assert "GH_TOKEN" in names, f"{role}: GH_TOKEN を宣言していない"
    # 箱に入らない役に GitHub の鍵を要求しない
    assert "GH_TOKEN" not in [e["name"] for e in manifest("recruiter")["env_requires"]]


def test_template_is_not_deployed():
    # 「何でもやる役」は役割の不在で、不在だとモデルも道具も作業環境も選べない。
    # 雛形としてだけ残し、本番のプロファイルにはしない。
    assert not (OUT / "_template").exists(), "雛形が配布物になっている"
    assert not (OUT / "common-worker").exists(), "汎用ワーカーが残っている"
    assert (ROOT / "templates/workers/_template/profile.yaml").exists(), "雛形が消えている"
    # 受け皿を置かない——担当が決まらないカードは止まることで、役の不足に気づける
    for role in ("operator", "fixer", "developer"):
        assert "default_assignee" not in cfg(role).get("kanban", {}), \
            f"{role} に既定の担当が残っている"


def test_recruiter_can_edit_the_kit():
    # 役を直すのが仕事なので、文書を読み書きする手が要る。terminal と file は
    # 同じ場所を触るので、ホストで動くこの役には両方ホストへ届く。
    t = cfg("recruiter")["platform_toolsets"]["cli"]
    for need in ("terminal", "file"):
        assert need in t, f"recruiter に {need} が無い（役を直せない）"
    assert "terminal" not in cfg("recruiter"), "recruiter が箱に入っている（templates/ に届かない）"


def test_shellless_roles_have_no_way_to_run_commands():
    # **なんでもできる役を作らない。** 他人が書いた文章を読む役は、読んだ内容に
    # 影響された状態でコマンドを打つ経路そのものを持たない。workspace を落とすだけでは
    # シェルがホストへ移るだけなので、terminal ごと外れていることを見る。
    c = cfg("handler")
    assert "terminal" not in c, "handler に terminal ブロックがある（箱が付いている）"
    for plat, tools in c["platform_toolsets"].items():
        assert "terminal" not in tools, f"handler の {plat} に terminal が残っている"
        # file も terminal と同じ場所を触る。シェルが無い役に渡すとホストへ届く
        assert "file" not in tools, f"handler の {plat} に file が残っている"
    assert not (OUT / "handler" / "workspace").exists(), "handler に作業部屋が付いている"
    # ファイルを書けないので、成果物の受け渡しは教えない（報告はコメントで完結する）
    soul = (OUT / "handler" / "SOUL.md").read_text(encoding="utf-8")
    assert "見せたいものは成果物として渡す" not in soul, "書けない役に成果物の渡し方を教えている"


def test_impl_rules_go_only_to_roles_that_write_code():
    # 調べるだけの役に clone / push / 委譲を教えると、使い道が無いうえに
    # 「自分の仕事だ」と誤解させる。handler に実装の規約が入っていないこと。
    r = (OUT / "handler" / "SOUL.md").read_text(encoding="utf-8")
    for bad in ("push まで届かせる", "CLI エージェントへ委譲", "作業は使い捨ての部屋の中で行う"):
        assert bad not in r, f"handler に実装の規約が入っている: {bad}"
    assert not (OUT / "handler" / "skills" / "delegate-to-cli-agents").exists(), \
        "handler に委譲のスキルが載っている"
    # 書く役には入っていること
    c = (OUT / "developer" / "SOUL.md").read_text(encoding="utf-8")
    assert "作業は使い捨ての部屋の中で行う" in c, "developer に作業部屋の説明が無い"
    # 全員に共通のものは、シェルの有無に関わらず入っている
    # 全員に共通のものは、シェルの有無に関わらず入っている
    t = (OUT / "handler" / "SOUL.md").read_text(encoding="utf-8")
    assert "自分のカードの中で完結させる" in t, "handler に共通の作法が無い"


def test_mcp_servers_are_not_nested_twice():
    # mcp.yaml は `servers:` を頂点に持つ。そのまま入れると
    # mcp_servers.servers.<名前> になり、Hermes からは空に見える。
    # 中身が空のうちは露呈しないので、名前が1段目に来ることを固定する。
    c = cfg("handler").get("mcp_servers") or {}
    assert c, "handler に mcp_servers が無い"
    assert "servers" not in c, f"mcp_servers が1段深い: {list(c)}"
    assert all(isinstance(v, dict) and ("url" in v or "command" in v) for v in c.values()), \
        f"サーバの定義になっていない: {c}"


def test_secrets_are_scoped_to_the_roles_that_need_them():
    # 鍵は「使う役」にだけ配る。全役へ丸ごと配ると、ワーカーが Slack のトークンを持ち、
    # gateway 以外からも喋れる状態になる（以前そうなっていた）。
    def names(role):
        return [e["name"] for e in manifest(role)["env_requires"]]

    for role in ("fixer", "developer", "handler", "recruiter"):
        leaked = [n for n in names(role) if n.startswith("SLACK_")]
        assert not leaked, f"{role} に Slack の鍵が漏れている: {leaked}"
    assert any(n.startswith("SLACK_") for n in names("operator")), "operator に Slack の鍵が無い"
    # GitHub の鍵は、**宣言した役にだけ**配る。宣言は profile.yaml の env_requires
    # （worker set --env）か、作業部屋を持つことによる。使わない役には渡らない。
    for role in ("operator", "fixer", "recruiter"):
        assert "GH_TOKEN" not in names(role), f"{role} に GH_TOKEN が漏れている"

    # **鍵を共有する役には、手のほうを絞らせる。** handler は他人が書いた文章を
    # 読む役で、インジェクションの露出が全役でいちばん高い。developer と同じ
    # 書き込み権限つきの鍵を共有する以上、書き換える MCP ツールを登録させない。
    import yaml as _yaml
    mcp_path = ROOT / "templates/workers/handler/mcp.yaml"
    if "GH_TOKEN" in names("handler") and mcp_path.exists():
        gh = ((_yaml.safe_load(mcp_path.read_text(encoding="utf-8")) or {})
              .get("servers", {}).get("github") or {})
        include = ((gh.get("tools") or {}).get("include")) or []
        assert include, "handler の GitHub MCP が全ツールを登録している（書き換える手が入る）"
        forbidden = [t for t in include
                     if any(t.startswith(p) or p in t
                            for p in ("create_", "update_", "push_", "merge_", "fork_", "delete_"))]
        assert not forbidden, f"handler に書き換える手が渡っている: {forbidden}"


def test_every_role_reaches_the_shared_memory():
    """**全役が共有記憶へ書き、そこから引ける。**

    報告はカードの comment と mem0 の両方に残す。カードは purge で消えるが、
    mem0 は残り、役をまたいで引ける——**役をまたいで過去を引ける手段はここだけ**
    （session_search も MEMORY.md も、その役に閉じている）。

    引いた前例をどう扱うかは役で違う。判断する役には `precedent-lookup` を配って
    「引いたものは従う対象ではなく、いまとの差を測る基準である」を持たせる。

    provider の宣言は配布物が持つ（`update --force-config` で消えないため）。
    接続先と鍵（mem0.json）は秘密なので、配布物には載せない。
    """
    specs = dict(bd.ROLES)
    specs.update(bd.worker_roles(ROOT))
    for name, spec in specs.items():
        cfg = bd.build_config(ROOT, name, spec)
        assert (cfg.get("memory") or {}).get("provider") == "mem0", \
            f"{name} が共有記憶に届かない"
    judges = {n for n, sp in specs.items() if sp.get("memory")}
    assert judges, "前例を引いて判断する役が1つも無い"
    for name in judges:
        assert "precedent-lookup" in (specs[name].get("skills") or []), \
            f"{name} は判断する役なのに、前例の扱い方（precedent-lookup）を持っていない"
    for d in (OUT).glob("*/"):
        for f in d.glob("**/*"):
            if f.is_file() and f.name == "mem0.json":
                raise AssertionError(f"接続情報が配布物に載っている: {f}")


def test_kanban_auto_subscription_is_disabled():
    """カード作成時の機械的な会話投稿を止め、明示的な wake 購読へ寄せる。"""
    for name, spec in bd.ROLES.items():
        cfg = bd.build_config(ROOT, name, spec)
        if spec.get("no_kanban"):
            # 板に載らない役（avatar）は kanban 設定ごと持たない。
            assert "kanban" not in cfg, f"{name} は板に載らないのに kanban 設定がある"
            continue
        assert cfg["kanban"]["auto_subscribe_on_create"] is False


def test_slack_reactions_are_explicitly_enabled_for_gateway():
    """Slack のリアクション機能は本体を変えず、gateway 設定から有効化する。"""
    gw = [n for n, sp in bd.ROLES.items() if sp.get("gateway")]
    assert len(gw) == 1
    extra = bd.build_config(ROOT, gw[0], bd.ROLES[gw[0]])["platforms"]["slack"]["extra"]
    assert extra["reactions"] is True
    assert extra["reaction_triggers"] is True


def test_gateway_answers_only_when_addressed():
    """**スレッドに複数人がいる前提で組む。**

    Slack の既定は「一度スレッドに参加したら以降はメンション不要」なので、
    人が増えると他人あての発言にも反応する。チャンネルでもスレッドでも
    呼ばれたときだけ答える形に倒す。DM は逆で、メンションは要らない
    （require_mention はチャンネルとスレッドにしか効かない）。

    設定を持つのは窓口の役だけ——他の役は Slack を受けない。
    """
    gw = [n for n, sp in bd.ROLES.items() if sp.get("gateway")]
    assert len(gw) == 1, f"窓口は1つに保つ: {gw}"
    slack = (bd.build_config(ROOT, gw[0], bd.ROLES[gw[0]])["platforms"]["slack"])
    assert slack["extra"]["require_mention"] is True
    assert slack["extra"]["thread_require_mention"] is True, \
        "スレッドで呼ばれていなくても反応する（他人あての会話に割り込む）"
    assert slack["extra"]["ignore_other_user_mentions"] is True
    assert slack["extra"]["reply_in_thread"] is True, \
        "チャンネルで平場に流している（他の会話に割り込む）"
    for name, spec in bd.ROLES.items():
        if spec.get("gateway"):
            continue
        assert "platforms" not in bd.build_config(ROOT, name, spec), \
            f"{name} が Slack の振る舞いを持っている（窓口は1つ）"


def test_roles_that_write_spellings_can_look_them_up():
    """**綴りを書く役は、綴りを引ける口を持つ。**

    道具の名前・設定キー・API の引数は、外れても静かに落ちる場所が多い
    （MCP の allowlist は、実在しない名前を警告なしに捨てる）。当たったか
    外れたかが見えないので、推測の代わりに引ける経路を最初から載せておく。

    窓口（operator）と連絡係（broker）は綴りを書かないので対象外。
    画面を触る役（avatar）も、書くのは座標とキー入力なので対象外。
    道具を揃える役（provisioner）も、叩くのは台帳の決まったコマンドだけなので対象外。
    """
    specs = dict(bd.ROLES)
    specs.update(bd.worker_roles(ROOT))
    for name, spec in specs.items():
        cfg = bd.build_config(ROOT, name, spec)
        servers = cfg.get("mcp_servers") or {}
        if name in ("operator", "broker", "provisioner") or spec.get("computer_use"):
            continue
        assert "context7" in servers, f"{name} が綴りを引けない"
        assert servers["context7"].get("url"), f"{name}/context7 に url が無い"


def test_shared_mcp_is_defined_once():
    """**共通の MCP は1箇所にしか書かない。**

    役ごとに書き写すと、直すたびに全部を直すことになり、必ず取り残される。
    定義は templates/shared/mcp/ にあり、役の表は名前で引くだけにする。
    """
    shared = ROOT / "templates/shared/mcp"
    names = {f.stem for f in shared.glob("*.yaml")}
    assert "context7" in names, "共通 MCP の定義が無い"
    for f in (ROOT / "templates/workers").glob("*/mcp.yaml"):
        body = f.read_text()
        for n in names:
            assert f"{n}:" not in body, \
                f"{f} が共通 MCP {n} を書き写している（shared/mcp/ から引く）"


def test_board_has_guards_for_silent_failures():
    """**黙って止まる形には、見張りを1つずつ当てる。**

    ボードは「動いていない」を状態として持たない。上限が短くて殺される、
    再spawnを見送られ続ける、同じ問題を掘り直し続ける——どれもカードの見た目は
    健康なままなので、`list` にも `stats` にも出ない。定期実行で見つけて、
    人が見る場所（blocked）へ移す。
    """
    need = {"runtime-guard", "spin-guard"}
    assert need <= set(bd.CRON_JOBS), \
        f"見張りが表に無い: {need - set(bd.CRON_JOBS)}"
    gw = [n for n, sp in bd.ROLES.items() if sp.get("gateway")]
    assert gw, "ゲートウェイの役が無い"
    on = set(bd.ROLES[gw[0]].get("cron") or [])
    assert need <= on, f"ゲートウェイの役に載っていない: {need - on}"
    for name in need:
        script = bd.CRON_JOBS[name][1]
        assert (ROOT / "templates/cron" / script).exists(), \
            f"{name} の実体が無い: {script}"


def test_only_the_gateway_can_schedule():
    """**定期実行は窓口だけが持つ。**

    cron は板の外に仕事を作れる唯一の道具である。他の役が持つと、止まっても
    `kanban ls` に出ない作業が生え、ボードが唯一の共有状態であるという前提が
    そこだけ崩れる。

    繰り返しの依頼は、窓口が cron に「カードを立てる一手」だけを持たせる。
    仕事そのものは毎回カードとして板に現れる。
    """
    specs = dict(bd.ROLES)
    specs.update(bd.worker_roles(ROOT))
    for name, spec in specs.items():
        tools = bd.build_config(ROOT, name, spec)["platform_toolsets"]["cli"]
        has = "cronjob" in tools
        assert has == bool(spec.get("gateway")), \
            f"{name}: 定期実行を持つのは窓口だけ（いま cronjob={has}）"


def test_completion_report_format_is_shared():
    """**完了時の報告の形は全役で同じにする。**

    読むのは書いた本人ではない——operator はこれを材料にユーザーへ報告し、
    fixer は完了を判定する。役ごとに形が違うと、読む側が毎回組み直すことになる。
    """
    shared = (ROOT / "templates/shared/AGENT-BASICS.md").read_text()
    for head in ("やったこと", "成果", "前提と制約", "残っていること", "次に生かせること"):
        assert head in shared, f"完了報告の見出しが共通ブロックに無い: {head}"


def test_memory_writing_is_shared_and_reading_is_not():
    """**書くのは全役、引いて判断に使うのは fixer。**

    書き込みは設定では起きない。`memory` 道具が書くのは役ごとのローカル
    （`profiles/<役>/memories/MEMORY.md`）で、他の役からは読めない。共有の記憶へ
    届くのは `mem0_add` を呼んだときだけなので、**全役に書き方を配る。**

    引き方（前例といまとの差を測る）は fixer の仕事なので、そこにだけ配る。
    全役へ配ると、担当が前例をなぞる読み方を覚える。
    """
    shared = "".join(f.read_text() for f in (ROOT / "templates/shared").glob("*.md"))
    assert "mem0_add" in shared, "共通ブロックが共有記憶への書き方を教えていない"
    assert "mem0_search" not in shared, \
        "共通ブロックが引き方を教えている（引くのは fixer だけ）"
    specs = dict(bd.ROLES)
    specs.update(bd.worker_roles(ROOT))
    for name, spec in specs.items():
        has = "precedent-lookup" in (spec.get("skills") or [])
        assert has == bool(spec.get("memory")), \
            f"{name}: 前例の扱い方は、明示的に役割を与えた役にだけ配る"


def test_env_declarations_are_queryable():
    # .env.EXAMPLE は profile install のときにしか作られず update では更新されない。
    # 後から増えた鍵を受け手へ伝える経路は、生成器の --env だけになる。
    import subprocess
    for role, want in (("developer", "GH_TOKEN"), ("operator", "SLACK_BOT_TOKEN")):
        out = subprocess.run(
            [sys.executable, str(ROOT / "core/build_distributions.py"), "--env", role, str(ROOT)],
            capture_output=True, text=True).stdout
        names = [l.split("\t")[0] for l in out.splitlines() if l.strip()]
        assert want in names, f"{role}: --env が {want} を返さない ({names})"
        # 形が崩れると zsh 側の追記が壊れる
        for line in out.splitlines():
            assert line.count("\t") == 2, f"{role}: 列が3つでない ({line!r})"


def test_workspace_does_not_depend_on_home():
    # Hermes は使い捨ての部屋で /root と /home を tmpfs で潰す（docker.py の非 persistent
    # 分岐）。$HOME に置いたものは実行時に消えるので、**効かないと困るものは ENV に焼く**。
    # 素の docker run では通るのに実運用で落ちる、という壊れ方を実際に踏んだ。
    df = (OUT / "developer" / "workspace" / "Dockerfile").read_text(encoding="utf-8")
    assert "ENV MISE_DATA_DIR=/cache/mise" in df, "キャッシュの向き先が ENV に無い"
    assert "GIT_CONFIG_COUNT" in df, "git の名乗りが ENV に無い（~/.gitconfig は毎回消える）"
    assert "/root/.profile" not in df, "$HOME の初期化ファイルに頼っている"
    assert "ln -sf" not in df, "$HOME への symlink は tmpfs で切れる（実体を移すこと）"
    # 無人で動くための宣言。対話に落ちた道具はタイムアウトまで固まる
    for name in ("GIT_TERMINAL_PROMPT=0", "CI=true", "PAGER=cat"):
        assert name in df, f"無人実行の宣言が無い: {name}"


def test_workspace_can_reach_private_npm_registry():
    """**private パッケージが引けないと、検証が1つも走らない。**

    `@scope:registry=https://npm.pkg.github.com` を宣言しているリポジトリで
    `npm ci` が 401 になると、lint も typecheck も build も動かず、
    「テストが通る」を完了条件にできなくなる（実際に踏んだ）。

    焼くのは「GH_TOKEN を読め」という指示だけで、値は実行時に転送される。
    """
    df = (OUT / "developer" / "workspace" / "Dockerfile").read_text(encoding="utf-8")
    assert "npm.pkg.github.com" in df, "private レジストリの認証が用意されていない"
    assert "${GH_TOKEN}" in df, "鍵を実行時に読む形になっていない"
    assert "NPM_CONFIG_GLOBALCONFIG" in df, \
        "$HOME に置くと tmpfs で消える。ENV で場所を焼くこと"


def test_workspace_recipe_bakes_no_secret():
    # イメージに鍵を焼くと、配布物にも痕跡が乗る
    text = "\n".join((OUT / "developer" / "workspace" / f).read_text(encoding="utf-8")
                      for f in ("Dockerfile", "profile.sh"))
    for bad in ("ghp_", "github_pat_", "xoxb-", "sk-", "OPENROUTER_API_KEY="):
        assert bad not in text, f"作業部屋の作り方に秘密が混ざっている: {bad}"
    # 言語ランタイムを焼くと、言語ごとにイメージを持つ羽目になる。
    # 見るのは **入れている行だけ**（ENV のキャッシュの向き先に maven/gradle の名前が
    # 出るのは正しいので、そこを拾わない）。
    df = (OUT / "developer" / "workspace" / "Dockerfile").read_text(encoding="utf-8")
    # 継続行（\ で折り返した先）にパッケージが並ぶので、先に1行へ畳んでから見る
    joined = df.replace("\\\n", " ")
    installs = " ".join(l for l in joined.splitlines()
                        if "apt-get install" in l or "npm install" in l).lower()
    for heavy in ("openjdk", "default-jdk", "maven", "gradle", "python3", "nodejs", "golang"):
        assert heavy not in installs, f"イメージが太っている: {heavy} を入れている"
    # ブラウザは標準装備。実装役が自分の変更を画面で確かめられないと、
    # 「テストが通る」を完了条件にできない
    assert "libnss3" in installs, "Chromium の依存が入っていない"
    assert "PLAYWRIGHT_BROWSERS_PATH=/cache" in df, "ブラウザ本体の置き場が /cache でない"


if __name__ == "__main__":
    print("配布物の生成")
    check("役が揃っている", test_roles_exist)
    check("共通ブロックが差し込まれている", test_soul_has_shared_block)
    check("ワーカーの雛形が展開されている", test_worker_placeholders_expanded)
    check("platform_toolsets に terminal", test_platform_toolsets_carry_terminal)
    check("プラグインが有効になっている", test_plugin_is_enabled)
    check("ゲートの部品がそろっている", test_gate_ships_complete)
    check("cron のジョブは配らない", test_cron_jobs_are_not_shipped)
    check("cron のスクリプトは配る", test_cron_scripts_are_shipped)
    check("HOTL は recruiter だけ", test_hotl_only_for_agent_creator)
    check("ワーカーは子を作れない", test_delegation_closed_for_workers)
    check("マニフェストが環境変数と所有を宣言", test_manifest_declares_env_and_ownership)
    check("窓口の鍵は役ごとに分かれる", test_gateway_keys_are_per_role)
    check("この環境の役はキットの外に置かれる", test_local_roles_live_outside_the_kit)
    check("ワーカーの鍵は既定で任意", test_worker_keys_are_optional_by_default)
    check("全役に人が読む一行がある", test_every_role_has_a_human_summary)
    check("版が git から採られている", test_version_is_derived_from_git)
    check("必須は本当に必須なものだけ", test_only_truly_required_keys_are_required)
    check("鍵が来ない MCP は無効で配る", test_mcp_without_keys_ships_disabled)
    check("秘密が混ざっていない", test_secrets_are_not_shipped)
    check("消した役の配布物が消える", test_stale_role_is_removed)
    check("作業部屋の役に terminal が載る", test_workspace_roles_get_terminal_block)
    check("recruiter はホストに残る", test_agent_creator_stays_on_the_host)
    check("作業部屋の作り方を同梱する", test_workspace_recipe_is_shipped)
    check("イメージ名の正が1つ", test_image_name_has_one_source)
    check("GH_TOKEN を宣言している", test_workspace_roles_declare_gh_token)
    check("雛形は配らない", test_template_is_not_deployed)
    check("recruiter がキットを直せる", test_recruiter_can_edit_the_kit)
    check("シェルの無い役に手が残っていない", test_shellless_roles_have_no_way_to_run_commands)
    check("実装の規約は書く役だけに載る", test_impl_rules_go_only_to_roles_that_write_code)
    check("MCP が二重に入れ子になっていない", test_mcp_servers_are_not_nested_twice)
    check("鍵が使う役だけに配られる", test_secrets_are_scoped_to_the_roles_that_need_them)
    check("必要な環境変数を引ける", test_env_declarations_are_queryable)
    check("全役が共有記憶に届く", test_every_role_reaches_the_shared_memory)
    check("カード作成時の自動購読を止める", test_kanban_auto_subscription_is_disabled)
    check("Slack リアクションを gateway 設定で有効化", test_slack_reactions_are_explicitly_enabled_for_gateway)
    check("窓口は呼ばれたときだけ答える", test_gateway_answers_only_when_addressed)
    check("綴りを書く役が綴りを引ける", test_roles_that_write_spellings_can_look_them_up)
    check("共通 MCP が1箇所だけ", test_shared_mcp_is_defined_once)
    check("黙って止まる形に見張りがある", test_board_has_guards_for_silent_failures)
    check("定期実行は窓口だけが持つ", test_only_the_gateway_can_schedule)
    check("完了報告の形が全役で同じ", test_completion_report_format_is_shared)
    check("記憶は全役が書き、fixer が引く", test_memory_writing_is_shared_and_reading_is_not)
    check("$HOME に依存していない", test_workspace_does_not_depend_on_home)
    check("private な npm レジストリへ届く", test_workspace_can_reach_private_npm_registry)
    check("作業部屋の作り方が薄く、秘密が無い", test_workspace_recipe_bakes_no_secret)
    shutil.rmtree(OUT, ignore_errors=True)
    finish()
