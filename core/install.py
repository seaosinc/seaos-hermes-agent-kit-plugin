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
from paths import profile_dir

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
    gen = roles.generator()
    res = Result()
    say: Log = log or (lambda _l: None)
    profile = booking.gate_profile()

    code, listing = hermes.run(["-p", profile, "cron", "list"])
    if code != 0:
        res.failures += 1
        say(f"✗ {profile} の定期実行を読み取れませんでした")
        return res

    spec = roles.all_specs().get(profile) or {}
    for role in [profile]:
        for name in spec.get("cron", []):
            expr, script = gen.CRON_JOBS[name]
            if re.search(rf"Name:\s*{re.escape(name)}\b", listing):
                say(f"{name} は登録済みです")
                continue
            if not (profile_dir(role) / "scripts" / script).is_file():
                res.failures += 1
                say(f"✗ {name}: {script} が未配布です（先に反映してください）")
                continue
            code, _out = hermes.run(
                ["-p", profile, "cron", "create", expr,
                 "--name", name, "--script", script, "--no-agent"])
            if code == 0:
                say(f"{name} を登録しました（{expr}）")
            else:
                res.failures += 1
                say(f"✗ {name} を登録できませんでした")
    return res


def install(*, log: Optional[Log] = None) -> Result:
    """全役を導入し、配布物に載らないものを揃える。**冪等。**

    既にあるものは壊さず、足りないものだけ足す。
    """
    res = Result()
    say: Log = log or (lambda _l: None)

    say("エージェントを配ります")
    result = kit.update()
    res.lines.extend(result.lines)
    res.failures += result.failures
    for line in result.lines:
        say(line)

    say("コマンドを配置します")
    try:
        platform_ops.link_command(log=say)
    except OSError as exc:
        res.failures += 1
        say(f"✗ コマンドを配置できませんでした: {exc}")

    say("定期実行を登録します")
    res.failures += register_cron(log=say).failures

    # **足りない道具は provisioner に揃えさせる。** 入れたその場で立てると、
    # 人が意識する前に動き出す（定期実行を待たない）。provisioner を外していれば、
    # 何が足りないかだけ言う。
    say("この PC の道具を確かめます")
    import machine

    missing = [r for r in machine.status() if r["missing"]]
    if not missing:
        say("足りない道具はありません")
    else:
        say("足りない道具: " + "、".join(r["label"] for r in missing))
        script = profile_dir(booking.gate_profile()) / "scripts" / "machine_guard.py"
        if script.is_file() and "provisioner" in roles.names():
            import subprocess
            import sys

            subprocess.run([sys.executable, str(script)], stdin=subprocess.DEVNULL)
            say("provisioner にカードを立てました（管理者の承認が要るところは Slack で聞きます）")
        else:
            say("provisioner が無効なので、seaos-kit machine install <道具> で入れてください")

    # **作業部屋のイメージ。** これが無いと、箱を持つ役（developer /
    # senior-developer）は最初のカードで失敗する。入れたばかりの環境には
    # 当然無いので、ここで作る。
    #
    # **失敗しても止めない。** Docker が無い環境（サーバの一部、審査中の端末）でも
    # 他の役は動くし、後から `seaos-kit workspace build` で作れる。
    say("作業部屋を用意します")
    try:
        import workspace as ws

        if not shutil.which(ws._docker_bin()):
            say("Docker が無いので飛ばします（後で seaos-kit workspace build）")
        elif ws.build(log=say):
            say("作業部屋のイメージを作りました")
        else:
            say("✗ 作業部屋のイメージを作れませんでした（seaos-kit workspace build で再試行）")
    except OSError as exc:
        say(f"✗ 作業部屋を用意できませんでした: {exc}")

    # **受け取った Office / PDF を Markdown にする道具。** 初回は依存を落とすので、
    # ファイルを受けたその場ではなく、ここで待つ。無くても元のファイルは渡る。
    say("ファイルの変換を用意します")
    import files as files_mod

    if files_mod.converter_ready():
        say("Excel / Word / PowerPoint / PDF を Markdown にできます")
    else:
        say("uv が見つからないので飛ばします（元のファイルだけを渡します。シェルの無い役は Office を読めません）")

    say("共有記憶を用意します")
    if not mem0.up(log=say):
        res.failures += 1

    say("常駐の設定")
    say(platform_ops.autostart_hint())

    return res


def uninstall(*, remove_profiles: bool = False, log: Optional[Log] = None) -> Result:
    """撤去する。

    **既定ではキット自身の痕跡だけ**を消す（コマンドの置き場と mem0）。
    役のプロファイルは記憶とセッションを抱えているので、明示されたときだけ消す。
    """
    res = Result()
    say: Log = log or (lambda _l: None)

    say("コマンドを外します")
    if platform_ops.unlink_command(log=say):
        pass
    else:
        say("置かれていませんでした")

    say("共有記憶を止めます")
    mem0.down(log=say)

    say("アクセス許可を外します")
    removed = booking.revoke_all(log=say)
    say(f"このゲート由来の承認を {removed} 箇所から削除しました" if removed else "削除するものはありませんでした")

    if not remove_profiles:
        say("")
        say("エージェントのプロファイルは残しました（記憶とセッションがあるため）。")
        say("削除する場合は remove_profiles を指定してください。")
        return res

    say("エージェントのプロファイルを削除します")
    # 外した役でも、残したプロファイルは撤去の対象に入れる
    for name in roles.all_names():
        if not profile_dir(name).is_dir():
            continue
        code, _out = hermes.run(["profile", "delete", name])
        if profile_dir(name).is_dir():
            res.failures += 1
            say(f"✗ {name} を削除できませんでした（手で削除してください）")
        else:
            say(f"- {name}")
    return res
