"""導入と撤去。

**エージェントの中身は配布物が運ぶ**（SOUL / skills / plugins / hooks / cron）。
ここが面倒を見るのは、配布物に載らないものだけ——コマンドの置き場、共有記憶、
ゲートウェイの常駐。

OS で違うところは platform_ops に閉じてある。
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import booking
import hermes
import kit
import mem0
import platform_ops
import roles
from paths import hermes_home, kit_root, profile_dir

Log = Callable[[str], None]


@dataclass
class Result:
    lines: List[str] = field(default_factory=list)
    failures: int = 0

    def ok(self) -> bool:
        return self.failures == 0


def register_cron(*, log: Optional[Log] = None) -> Result:
    """定期実行を登録する。**冪等**——無いものだけ作る。

    **配布物には載せない。** 載せると `profile update` のたびにスケジューラが
    持っている状態（次の実行時刻など）が骨だけの版で上書きされ、ジョブが死ぬ
    （実際に死んだ）。登録は公式の `hermes cron create` に任せ、ここは
    「無ければ作る」だけにする。スクリプトの実体は配布物が運ぶ。
    """
    import build_distributions as gen

    res = Result()
    say: Log = log or (lambda _l: None)
    profile = booking.gate_profile()

    code, listing = hermes.run(["-p", profile, "cron", "list"])
    if code != 0:
        res.failures += 1
        say(f"✗ 登録済みの定期実行を読めなかった（{profile}）")
        return res

    roles_spec = {**gen.ROLES, **gen.worker_roles(kit_root())}
    for role, spec in roles_spec.items():
        if role != profile:
            continue
        for name in spec.get("cron", []):
            expr, script = gen.CRON_JOBS[name]
            if re.search(rf"Name:\s*{re.escape(name)}\b", listing):
                say(f"= {name}（登録済み）")
                continue
            if not (profile_dir(role) / "scripts" / script).is_file():
                res.failures += 1
                say(f"✗ {name}: {script} が配布されていない（先に update）")
                continue
            code, _out = hermes.run(
                ["-p", profile, "cron", "create", expr,
                 "--name", name, "--script", script, "--no-agent"])
            if code == 0:
                say(f"+ {name}（{expr}）")
            else:
                res.failures += 1
                say(f"✗ {name} の登録に失敗")
    return res


def install(*, log: Optional[Log] = None) -> Result:
    """全役を導入し、配布物に載らないものを揃える。**冪等。**

    既にあるものは壊さず、足りないものだけ足す。
    """
    res = Result()
    say: Log = log or (lambda _l: None)

    say("=== 1. 配布物を生成して全役を導入 ===")
    result = kit.update()
    res.lines.extend(result.lines)
    res.failures += result.failures
    for line in result.lines:
        say(line)

    say("=== 2. コマンドの置き場 ===")
    try:
        platform_ops.link_command(log=say)
    except OSError as exc:
        res.failures += 1
        say(f"✗ コマンドを置けなかった: {exc}")

    say("=== 3. 定期実行（Hermes の cron） ===")
    res.failures += register_cron(log=say).failures

    say("=== 4. 共有記憶（mem0） ===")
    if not mem0.up(log=say):
        res.failures += 1

    say("=== 5. 常駐 ===")
    say(platform_ops.autostart_hint())

    return res


def uninstall(*, remove_profiles: bool = False, log: Optional[Log] = None) -> Result:
    """撤去する。

    **既定ではキット自身の痕跡だけ**を消す（コマンドの置き場と mem0）。
    役のプロファイルは記憶とセッションを抱えているので、明示されたときだけ消す。
    """
    res = Result()
    say: Log = log or (lambda _l: None)

    say("=== 1. コマンドの置き場 ===")
    if platform_ops.unlink_command(log=say):
        pass
    else:
        say("= 置いていなかった")

    say("=== 2. 共有記憶（mem0） ===")
    mem0.down(log=say)

    say("=== 3. アクセスゲートの承認 ===")
    removed = booking.revoke_all(log=say)
    say(f"= このゲート由来の承認を {removed} 箇所から削除" if removed else "= 消すものは無かった")

    if not remove_profiles:
        say("")
        say("役のプロファイルは残した（記憶とセッションを抱えているため）。")
        say("消すなら remove_profiles を渡すこと。")
        return res

    say("=== 4. 役のプロファイル ===")
    for name in roles.names():
        if not profile_dir(name).is_dir():
            continue
        code, _out = hermes.run(["profile", "delete", name])
        if profile_dir(name).is_dir():
            res.failures += 1
            say(f"✗ {name} を消せなかった（手で消すこと）")
        else:
            say(f"- {name}")
    return res
