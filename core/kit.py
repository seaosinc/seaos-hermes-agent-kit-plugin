"""キットの中核。**CLI も GUI もここを呼ぶ。**

zsh 版（bin/hermes-kit + bin/_*.zsh）のうち、OS に触らない部分をここへ移した。
常駐の作法とコマンドの置き場だけが OS で違い、それは paths.py と後続の
platform 実装に閉じる。ここには platform 分岐を書かないこと。
"""

from __future__ import annotations

import io
import shutil
import tempfile
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import yaml

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


def build(out: Optional[Path] = None, log: Optional[Log] = None) -> Path:
    """templates/ → 配布物。**dist/ は生成物なので毎回作り直す。**"""
    root = kit_root()
    target = out or (root / "dist")
    # **関数を直接呼ぶ。** 生成器の CLI 分岐（__main__）は zsh 版が使っていた口で、
    # Python から使うときに argv を差し替えるのは事故のもと。
    #
    # **進捗出力は飲む。** 生成器は「+ operator …」を stdout へ書く。CLI では
    # それが表示になるが、GUI から呼ぶと API のレスポンス経路とサーバログへ
    # そのまま漏れる。出したい呼び手には log 経由で渡す。
    captured = io.StringIO()
    with redirect_stdout(captured):
        roles.generator().build(root, target, set(roles.names()))
    if log:
        for line in captured.getvalue().splitlines():
            if line.strip():
                log(line.strip())
    return target


# 外した役に残す説明文。**プロファイルが残っている限り、分解器は担当の候補に並べる**
# （Hermes は profiles/ にあるものを全部名簿に載せる）。説明文が唯一の入力なので、
# ここで「選ぶな」と書く。
DISABLED_DESCRIPTION = ("【無効】このプロファイルは使われていない。"
                        "kanban の担当に選んではならず、どのカードも割り当ててはならない。")


def sync_descriptions(log: Optional[Log] = None) -> Result:
    """説明文を生成器の文面に合わせる。**振り分けの唯一の入力なので毎回やる。**

    外した役でプロファイルが残っているものは、選ばれないように書き換える。
    """
    result = Result()
    enabled = set(roles.names())
    for name in roles.all_names():
        if not hermes.profile_exists(name):
            continue
        text = roles.describe(name) if name in enabled else DISABLED_DESCRIPTION
        if _current_description(name) == text:
            # **同じなら叩かない。** 1回 0.3 秒の hermes 呼び出しが、反映のたびに全役ぶん走っていた
            continue
        if not text:
            continue
        code, _out = hermes.set_description(name, text)
        if code == 0:
            result.lines.append(f"{name} の説明文をそろえました")
        else:
            result.failures += 1
            result.lines.append(f"✗ {name} の説明文を設定できませんでした")
    return result


def apply_env(log: Optional[Log] = None) -> Result:
    """正の .env から各役へ配る。"""
    result = Result()
    report, missing = env_mod.apply()
    result.lines.extend(report)
    for item in missing:
        result.lines.append(f"{item} が空のままです")
    if log:
        for line in result.lines:
            log(line)
    return result


def prune_skills(log: Optional[Log] = None) -> Result:
    """**その役に載らなくなったキット由来のスキルを、実機から外す。**

    配布物の持ち物は `skills/<名前>` と1つずつ宣言してある（まとめて `skills/` と
    書くと、更新のたびにフォルダごと作り直されて、実機で生えたスキルが消える）。
    その代わり、**配置表から外したスキルは持ち物でなくなり、実機に残り続ける。**
    存在しない規約を担当が読むことになるので、ここで外す。

    見分けはキットの中にあるかどうかで付く。キットが配りうるスキル
    （`templates/skills/` と `templates/workers/<役>/skills/`）に名前があるのに、
    その役には載っていない——これがキット由来の残骸である。
    **キットが知らないスキルには触らない**（Hermes やエージェントが生やしたもの）。
    """
    root = kit_root()
    ours = {p.name for p in (root / "templates" / "skills").glob("*") if p.is_dir()}
    ours |= {p.name for p in (root / "templates" / "workers").glob("*/skills/*") if p.is_dir()}

    result = Result()
    for name in roles.names():
        pdir = profile_dir(name)
        if not pdir.is_dir():
            continue
        declared = set(roles.skills(name))
        for skill in sorted((pdir / "skills").glob("*")):
            if not skill.is_dir() or skill.name in declared or skill.name not in ours:
                continue
            shutil.rmtree(skill, ignore_errors=True)
            result.lines.append(f"{name} から {skill.name} を外しました（配られなくなったため）")
    if log:
        for line in result.lines:
            log(line)
    return result


def _current_description(name: str) -> str:
    """いま入っている説明文（空白は畳む）。読めなければ空。"""
    try:
        doc = yaml.safe_load((profile_dir(name) / "profile.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ""
    return " ".join(str(doc.get("description") or "").split())


def retarget_source(dist: Path, name: str) -> bool:
    """役が覚えている取得元を、**いまの配布物の場所へ付け替える。** 付け替えたら True。

    `profile update` は、導入したときの取得元（`distribution.yaml` の `source`）から取り直す。
    キットのフォルダが移ると（プラグインの名前をリポジトリ名に揃えたとき
    `plugins/seaos-hermes-agent-kit` → `plugins/seaos-hermes-agent-kit-plugin`）、
    **消えた場所を見て全役が更新できなくなった。**
    `install --force` でも付け替わるが、config.yaml を配布物で上書きしてしまうので、
    取得元の1行だけを直して、設定を残す update に任せる。
    """
    path = profile_dir(name) / "distribution.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    want = str(dist.resolve())
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if not line.startswith("source:"):
            continue
        current = line.split(":", 1)[1].strip().strip("'\"")
        if current == want or Path(current).exists():
            # 取得元がまだ実在するなら、利用者が意図して別の場所から入れたもの。触らない
            return False
        lines[i] = f"source: {want}\n"
        path.write_text("".join(lines), encoding="utf-8")
        return True
    return False


def _installed_matches(dist: Path, name: str) -> bool:
    """**配るものが、入っているものと同じか。** 同じなら profile update を飛ばす。

    比べるのは配布物の持ち物（distribution_owned）のうち、中身で比べられるもの。
    - `config.yaml` は比べない。update が既定で保持するので、違っていて正常
    - `distribution.yaml` はインストーラが書き直すので、版だけ比べる
    """
    pdir = profile_dir(name)
    try:
        built = yaml.safe_load((dist / "distribution.yaml").read_text(encoding="utf-8")) or {}
        installed = yaml.safe_load((pdir / "distribution.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return False
    if str(built.get("version")) != str(installed.get("version")):
        return False
    for owned in built.get("distribution_owned") or []:
        rel = owned.rstrip("/")
        if rel in ("config.yaml", "distribution.yaml"):
            continue
        a, b = dist / rel, pdir / rel
        if not (_same_tree(a, b) if a.is_dir() else _same_file(a, b)):
            return False
    return True


def enable_role(name: str, log: Optional[Log] = None) -> Result:
    """役を入れる側に戻す。**記録するだけ**で、導入は次の反映で行う。"""
    import selection

    if name not in roles.all_names():
        raise selection.SelectionError(f"そのエージェントはありません: {name}")
    result = Result()
    changed = selection.set_enabled(name, True)
    result.lines.append(f"{name} を有効にしました（反映すると導入されます）" if changed
                        else f"{name} は有効です")
    if log:
        for line in result.lines:
            log(line)
    return result


def disable_role(name: str, *, remove_profile: bool = False, log: Optional[Log] = None) -> Result:
    """役を外す。以後の反映・鍵の配布・検証の対象から外れる。

    **プロファイルは既定で残す**（記憶とセッションは戻せない）。残す場合は、
    分解器に選ばれないよう説明文を書き換え、窓口なら常駐を止める——
    残しただけでは、Hermes から見て**普通に動く役のまま**だからである。
    """
    import platform_ops
    import selection
    import worker as worker_mod

    if name not in roles.all_names():
        raise selection.SelectionError(f"そのエージェントはありません: {name}")
    reason = worker_mod.busy_reason(name)
    if reason:
        raise selection.SelectionError(reason + "。終わるのを待つか、そのカードを止めてください")

    result = Result()
    selection.set_enabled(name, False, essential=roles.essential(name))
    result.lines.append(f"{name} を無効にしました")

    if (roles.all_specs().get(name) or {}).get("gateway") and platform_ops.gateway_pid(name):
        if platform_ops.stop_gateway(name):
            result.lines.append(f"{name} の窓口を止めました")
        else:
            result.failures += 1
            result.lines.append(f"✗ {name} の窓口を止められませんでした")

    if hermes.profile_exists(name):
        if remove_profile:
            # **`-y` が要る。** 無いと対話の確認待ちのまま黙って終わる（worker.remove と同じ）。
            hermes.run(["profile", "delete", name, "-y"])
            if hermes.profile_exists(name):
                result.failures += 1
                result.lines.append(f"✗ {name} のプロファイルを削除できませんでした")
            else:
                result.lines.append(f"{name} のプロファイルを削除しました")
        else:
            code, _ = hermes.set_description(name, DISABLED_DESCRIPTION)
            if code != 0:
                result.failures += 1
                result.lines.append(f"✗ {name} の説明文を書き換えられませんでした（担当に選ばれるおそれがあります）")
    if log:
        for line in result.lines:
            log(line)
    return result


def _add_enabled(path: Path, cfg: dict, plugin: str) -> bool:
    """役の config.yaml の `plugins.enabled` へ1つ足す。**ほかの設定は触らない。**"""
    plugins = cfg.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {"enabled": [], "disabled": []}
        cfg["plugins"] = plugins
    enabled = plugins.get("enabled")
    if not isinstance(enabled, list):
        enabled = []
    if plugin in enabled:
        return True
    plugins["enabled"] = [*enabled, plugin]
    try:
        path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    except OSError:
        return False
    return True


def retire(log: Optional[Log] = None) -> Result:
    """**廃止した役と定期実行を、入っている環境から外す。**

    配置表から消しただけでは、プロファイルは担当として選べるまま残り、定期実行は
    消えたスクリプトを毎回呼び続ける。キットが配った役（distribution.yaml の author が
    このキット）だけを消し、利用者が同じ名前で自分で作ったプロファイルには触らない。
    """
    import re

    result = Result()
    gen = roles.generator()
    for name in getattr(gen, "RETIRED_ROLES", ()):
        pdir = profile_dir(name)
        try:
            dist = yaml.safe_load((pdir / "distribution.yaml").read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if "seaos" not in str(dist.get("author", "")):
            continue
        code, _out = hermes.run(["profile", "delete", name, "-y"])
        result.lines.append(f"廃止した {name} を外しました" if code == 0 and not pdir.exists()
                            else f"廃止した {name} を外せませんでした（hermes profile delete {name}）")
        result.failures += 0 if code == 0 and not pdir.exists() else 1

    retired_crons = set(getattr(gen, "RETIRED_CRONS", ()))
    if retired_crons:
        import booking

        profile = booking.gate_profile()
        code, listing = hermes.run(["-p", profile, "cron", "list"])
        if code == 0:
            job = None
            for line in listing.splitlines():
                m = re.match(r"^\s*([0-9a-f]{8,})\s*(\[|$)", line)
                if m:
                    job = m.group(1)
                    continue
                n = re.match(r"^\s*Name:\s*(\S+)", line)
                if n and job and n.group(1) in retired_crons:
                    rc, _o = hermes.run(["-p", profile, "cron", "remove", job])
                    result.lines.append(f"廃止した定期実行 {n.group(1)} を外しました" if rc == 0
                                        else f"廃止した定期実行 {n.group(1)} を外せませんでした")
                    result.failures += 0 if rc == 0 else 1
                    job = None
    return result


def enable_plugins() -> Result:
    """配布物で有効にしたプラグインを、**実際の設定でも有効にする。**

    `profile update` は config.yaml を上書きしない（利用者の設定を守る Hermes の仕様）。
    そのため、配布物の config に plugins.enabled を書いても、**すでに入っている役では
    有効にならない**——全役に runtime-floor を足したとき、置かれただけで全役
    「not enabled」だった。公式の `plugins enable` で足す（既に有効なら触らない）。
    """
    result = Result()
    gen = roles.generator()
    specs = roles.all_specs()
    for name in roles.names():
        cfg_path = profile_dir(name) / "config.yaml"
        if not cfg_path.is_file():
            continue
        try:
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        have = set(((cfg.get("plugins") or {}).get("enabled")) or [])
        for plugin in gen.plugins_of(specs.get(name) or {}, with_self=True):
            if plugin in have:
                continue
            # 道具の上書きは求めない。聞かれると対話待ちで止まる
            code, _out = hermes.run(["-p", name, "plugins", "enable", plugin, "--no-allow-tool-override"])
            if code == 0:
                result.lines.append(f"{name} で {plugin} を有効にしました")
                continue
            # **役のプロファイルからは、本体側に入っているプラグインを有効にできない**
            # （`plugins enable` はその役のフォルダしか見ずに「そんな名前は無い」と断る）。
            # 一方、設定画面のバックエンドは本体側のフォルダも見るので、設定に名前さえあれば通る。
            # 配布物の config には入れてあるが、update は既存の config を上書きしないので、
            # 入っている環境にはここで書き足す。
            if _add_enabled(cfg_path, cfg, plugin):
                result.lines.append(f"{name} の設定に {plugin} を足しました")
            else:
                result.lines.append(f"{name} で {plugin} を有効にできませんでした")
                result.failures += 1
    return result


def update(*, force_config: bool = False, log: Optional[Log] = None) -> Result:
    """templates/ → 配布物 → 各プロファイル → 説明文。

    **config.yaml は既定で保持される**（Hermes の仕様）。モデルやトポロジ、
    mcp_servers を変えたのに反映されないときは、たいてい force_config を忘れている。

    **報告は畳む。** 毎回8行の「○○ を更新した」が並んでも読まれない。
    件数で言い、**いつもと違うこと（新設・移行・失敗）だけ名前を出す。**
    """
    result = Result()
    # **配布物の置き場。** ループの中で使い回すので、役割の分かる名前にしておく。
    dist_root = build(log=log)

    updated = unchanged = 0
    notable: List[str] = []
    for name in roles.names():
        dist = dist_root / name
        if not dist.is_dir():
            continue
        if not hermes.profile_exists(name):
            code, _ = hermes.install(dist)
            notable.append(f"{name} を新しく導入しました" if code == 0
                           else f"{name} を導入できませんでした")
            result.failures += 0 if code == 0 else 1
            continue
        if not hermes.is_distribution(name):
            # 旧方式で作られたプロファイル。一度だけ配布物として入れ直す
            code, _ = hermes.install(dist, force=True)
            notable.append(f"{name} を配布物として入れ直しました" if code == 0
                           else f"{name} を入れ直せませんでした")
            result.failures += 0 if code == 0 else 1
            continue
        if retarget_source(dist, name):
            notable.append(f"{name} の取得元を、いまのキットの場所へ付け替えました")
        if not force_config and _installed_matches(dist, name):
            unchanged += 1
            continue
        code, _ = hermes.update(name, force_config=force_config)
        if code == 0:
            updated += 1
        else:
            notable.append(f"{name} を更新できませんでした")
            result.failures += 1

    if updated:
        result.lines.append(f"エージェント {updated} 件を更新しました")
    elif unchanged and not notable:
        result.lines.append("エージェントは最新です")
    result.lines.extend(notable)

    # **コマンドの置き場も反映のうち。** 規約は seaos-kit を叩けと書いてあるので、
    # 入口が無いとエージェントはその手順を実行できない（実際そうなっていた）。
    import platform_ops
    try:
        platform_ops.link_command()
    except OSError as exc:
        result.failures += 1
        result.lines.append(f"コマンドを配置できませんでした: {exc}")

    # **箱へ渡す置き場を先に作る。** 無いまま箱を立てると、Docker が root の
    # 持ち物として作り、ホストの役（窓口）が書けなくなる。
    import files as files_mod

    for folder in (files_mod.files_root(), Path(roles.generator().ATTACHMENTS_ROOT)):
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            result.lines.append(f"✗ {folder} を作れませんでした: {exc}")
            result.failures += 1

    pruned = prune_skills()
    result.lines.extend(pruned.lines)

    # **共有記憶へ繋ぐ。** 後から有効にした役も、ここで繋がる。
    import mem0

    mem0.rewire(log=result.lines.append)

    retired = retire()
    result.lines.extend(retired.lines)
    result.failures += retired.failures

    enabled = enable_plugins()
    result.lines.extend(enabled.lines)
    result.failures += enabled.failures

    # **この PC の事実を書き直す。** config.yaml ごと入れ替わると消えるので、
    # 反映のたびに置く（実際に全役から消えていた）。
    import envhint

    measured = envhint.apply()
    result.lines.extend(measured.lines)
    result.failures += measured.failures

    described = sync_descriptions(log=log)
    ok = len(described.lines) - described.failures
    if ok:
        result.lines.append(f"説明文を {ok} 件そろえました")
    result.lines.extend(l for l in described.lines if l.startswith("✗"))
    result.failures += described.failures

    applied = apply_env()
    result.lines.extend(applied.lines)

    # **鍵の有無で MCP の有効・無効を決める。** 空トークンでもサーバは繋がり、
    # 道具の一覧まで出す（呼んだときだけ 400）。役から見て「その手が無い」と
    # 分かる形にする。鍵が入ったら戻す——片道にしない。
    flipped, _disabled = env_mod.sync_mcp_enabled()
    result.lines.extend(flipped)

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
