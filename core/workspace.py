"""作業部屋（カードごとに立てて捨てる使い捨てコンテナ）。

**イメージはマシンごとの生成物なので配らない。** 配るのは作り方
（`templates/workspace/`）で、各マシンで一度 build する。プロファイルの
config.yaml がイメージ名を指しているので、名前がずれると担当が起動時に落ちる
——**名前の正は生成器**（`--workspace`）である。

docker はどの OS でも同じ口なので、ここに platform 分岐は無い。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import roles
from paths import kit_root

Log = Callable[[str], None]

# 傍受を確かめに行く先。**1ホストだけ見ると誤判定する**——この環境では
# github.com は素通しなのに mise.run と opencode.ai には別の CA が挟まる。
CA_PROBES = os.environ.get("WORKSPACE_CA_PROBES", "").split() or [
    "mise.run", "opencode.ai", "github.com", "cli.github.com",
    "registry.npmjs.org", "pypi.org", "repo.maven.apache.org", "proxy.golang.org",
]


class WorkspaceError(RuntimeError):
    pass


def _docker_bin() -> str:
    exe = os.environ.get("HERMES_DOCKER_BINARY", "docker")
    if not shutil.which(exe):
        raise WorkspaceError(f"{exe} が見つからない（HERMES_DOCKER_BINARY で差し替えられる）")
    return exe


def docker(*args: str, capture: bool = True, check: bool = False) -> Tuple[int, str]:
    proc = subprocess.run(
        [_docker_bin(), *args],
        capture_output=capture,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    out = ((proc.stdout or "") + (proc.stderr or "")) if capture else ""
    if check and proc.returncode != 0:
        raise WorkspaceError(out.strip() or f"docker {' '.join(args)} に失敗")
    return proc.returncode, out


def settings() -> Dict[str, str]:
    """image / cache を生成器から引く。**2箇所で名前を持たない。**"""
    import importlib.util
    import sys

    path = Path(__file__).resolve().parent / "build_distributions.py"
    spec = importlib.util.spec_from_file_location("kit_generator", path)
    gen = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules.setdefault("kit_generator", gen)
    spec.loader.exec_module(gen)  # type: ignore[union-attr]
    return {"image": gen.WORKSPACE_IMAGE, "cache": gen.WORKSPACE_CACHE}


def boxed_roles() -> List[str]:
    """箱を持つ役。**増えるほど最悪値（枚数 × メモリ）が上がる。**"""
    return [
        n for n, sp in roles.all_specs().items()
        if sp.get("workspace") and sp.get("shell", True)
    ]


# ── CA ────────────────────────────────────────────────────────────────────

def extract_ca(out: Optional[Path] = None, log: Optional[Log] = None) -> Path:
    """組織の TLS 傍受プロキシの CA を取り出す。

    **ホストが信頼していてもコンテナは知らない。** 入れないと clone も mise も
    npm も certificate エラーで落ちる。取り出し元は握手そのもの（公開情報）。
    傍受が無い環境では空になり、何も起きない。
    """
    target = out or (kit_root() / ".workspace-ca.pem")
    pem: List[str] = []
    for host in CA_PROBES:
        proc = subprocess.run(
            ["openssl", "s_client", "-showcerts", "-connect", f"{host}:443", "-servername", host],
            input="", capture_output=True, text=True,
        )
        pem.extend(re.findall(
            r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", proc.stdout, re.S))

    seen: set[str] = set()
    kept: List[str] = []
    for block in pem:
        info = subprocess.run(
            ["openssl", "x509", "-noout", "-subject", "-issuer"],
            input=block, capture_output=True, text=True,
        ).stdout
        subject = issuer = ""
        for line in info.splitlines():
            if line.startswith("subject="):
                subject = line[8:].strip()
            elif line.startswith("issuer="):
                issuer = line[7:].strip()
        # 自己署名＝ルート。公開のルートを配る側が送ることは稀なので、
        # ここに出るのは実質「傍受プロキシのルート」だけになる。
        if subject and subject == issuer and subject not in seen:
            seen.add(subject)
            if log:
                log(f"取り出した: {subject}")
            kept.append(block)

    target.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    if log:
        log(f"CA を {target} に置いた" if kept else "傍受は検出されなかった（CA の注入は不要）")
    return target


# ── build / warm / verify ────────────────────────────────────────────────

def build(*, warm: bool = True, log: Optional[Log] = None) -> bool:
    cfg = settings()
    image, cache = cfg["image"], cfg["cache"]
    if log:
        log(f"イメージ: {image}")
        log(f"元:       {kit_root() / 'templates/workspace'}")

    ca_file = os.environ.get("WORKSPACE_CA_FILE")
    ca_path = Path(ca_file) if ca_file else extract_ca(log=log)

    # **templates/ を汚さない**ため、build の文脈は一時ディレクトリに作る。
    with tempfile.TemporaryDirectory(prefix="kit-ws-") as ctx:
        ctx_path = Path(ctx)
        src = kit_root() / "templates" / "workspace"
        for name in ("Dockerfile", "profile.sh", "opencode-instructions.md", "seaos-path"):
            shutil.copy(src / name, ctx_path / name)
        extra = ctx_path / "extra-ca.crt"
        if ca_path.is_file():
            shutil.copy(ca_path, extra)
        else:
            extra.write_text("", encoding="utf-8")
        code, out = docker("build", "--pull", "-t", image, str(ctx_path))
        if code != 0:
            raise WorkspaceError(f"build に失敗した\n{out}")

    # 名前付きボリューム。**部屋を捨てても残る唯一の場所**なので明示して作る。
    if docker("volume", "inspect", cache)[0] != 0:
        docker("volume", "create", cache)
        if log:
            log(f"キャッシュを作成: {cache}")

    ok = verify(log=log)
    if ok and warm:
        warm_cache(log=log)
    return ok


def warm_cache(log: Optional[Log] = None) -> bool:
    """冷えた初回のコストを先に払う。**温めるのは公開のパッケージだけ。**"""
    cfg = settings()
    node = os.environ.get("WORKSPACE_WARM_NODE", "22.11.0")
    script = (
        "set -e\n"
        f"mise use -g node@{node} >/dev/null 2>&1\n"
        "cd /tmp && npm init -y >/dev/null 2>&1\n"
        "npm i -s playwright@${PLAYWRIGHT_VERSION:-1.49.0} >/dev/null 2>&1\n"
        "npx playwright install chromium >/dev/null 2>&1\n"
        "du -sh /cache 2>/dev/null | sed 's/^/  いま: /'\n"
    )
    code, out = docker("run", "--rm", "-v", f"{cfg['cache']}:/cache", cfg["image"], "bash", "-lc", script)
    if log:
        log("✓ 温めた" if code == 0 else "✗ 温められなかった（ネットワークを確認すること）")
    return code == 0


def _as_if(cfg: Dict[str, str]) -> List[str]:
    """**Hermes と同じ条件で叩く。**

    使い捨ての部屋では /root と /home が tmpfs で潰される。素の `docker run` では
    通るのに実運用では落ちる、という壊れ方を再現するために同じ条件を作る。
    """
    return [
        "run", "--rm",
        "--tmpfs", "/root:rw,exec",
        "--tmpfs", "/home:rw,exec",
        "-v", f"{cfg['cache']}:/cache",
        cfg["image"],
    ]


def verify(log: Optional[Log] = None) -> bool:
    cfg = settings()
    base = _as_if(cfg)
    ok = True

    for probe in ("git --version", "gh --version", "mise --version", "opencode --version"):
        code, out = docker(*base, "bash", "-lc", probe)
        head = (out.splitlines() or [""])[0]
        if code == 0:
            if log:
                log(f"✓ {probe.split()[0]}  {head}")
        else:
            ok = False
            if log:
                log(f"✗ {probe.split()[0]} が動かない: {head}")

    checks = [
        (
            'echo "$MISE_DATA_DIR|$MAVEN_OPTS"',
            lambda v: v.startswith("/cache/mise|"),
            "キャッシュの向き先",
            "キャッシュの向き先が入っていない",
        ),
        (
            'head -c 200 "$XDG_CONFIG_HOME/box.md" 2>/dev/null | head -1',
            lambda v: "作業部屋" in v,
            "委譲先への説明  /etc/hermes-config/box.md",
            "opencode に部屋の説明が届かない",
        ),
        (
            "cd /tmp && git init -q r && cd r && echo x > f && git add -A "
            "&& git commit -qm t && git log -1 --format=%an",
            lambda v: v == "hermes-worker",
            "git の名乗り",
            "commit できない（名乗りが無い）",
        ),
        (
            # Windows では本文のパスをこれで読み替える。無いと添付も成果物も通らない
            "SEAOS_PATH_MAP='C:\\h=/seaos/h' seaos-path 'C:\\h\\a'",
            lambda v: v == "/seaos/h/a",
            "パスの読み替え  seaos-path",
            "seaos-path が無い（Windows で本文のパスが読めない）",
        ),
        (
            'echo "$GIT_TERMINAL_PROMPT|$CI|$PAGER"',
            lambda v: v == "0|true|cat",
            "無人で止まらない設定",
            "対話に落ちる恐れ",
        ),
    ]
    for script, good, ok_msg, ng_msg in checks:
        _code, out = docker(*base, "bash", "-c", script)
        value = (out.strip().splitlines() or [""])[-1]
        if good(value):
            if log:
                log(f"✓ {ok_msg}  {value}" if "  " not in ok_msg else f"✓ {ok_msg}")
        else:
            ok = False
            if log:
                log(f"✗ {ng_msg}: {value}")
    return ok


def clean(*, confirm: bool = False, log: Optional[Log] = None) -> bool:
    """キャッシュを捨てる。**次回の初回だけ遅くなるが、壊れたときはこれで直る。**"""
    cache = settings()["cache"]
    if not confirm:
        if log:
            log(f"キャッシュ {cache} を削除する。実行するには confirm を渡すこと。")
        return False
    code, _ = docker("volume", "rm", cache)
    if log:
        log(f"削除した: {cache}" if code == 0 else "削除できなかった（使用中のコンテナがあるかもしれない）")
    return code == 0


def shell() -> int:
    """作業部屋のイメージに入る。**手で確かめるため。**

    エージェントが「その道具が無い」と言ったとき、本当に無いのかを見る唯一の手段。
    キャッシュも同じように繋ぐので、担当が見ているのと同じ状態になる。

    **端末をそのまま渡す**（capture しない）。対話で使うものなので、
    出力を捕まえると入力が効かない。
    """
    cfg = settings()
    return subprocess.run(
        [_docker_bin(), "run", "--rm", "-it",
         "-v", f"{cfg['cache']}:/cache", "-w", "/workspace", cfg["image"], "bash", "-l"]
    ).returncode


def gc(log: Optional[Log] = None) -> Dict[str, str]:
    """溜まったゴミを落とす。**守るものを明示して、それ以外だけ落とす。**

    `docker volume prune` は使わない——「使われていない名前付きボリューム」も
    巻き込み、温めた /cache（言語ランタイムと playwright）が飛ぶ。落とすのは
    **匿名ボリュームだけ**（64桁の16進名）。イメージも dangling だけ。
    """
    if docker("ps", "-q")[0] != 0:
        if log:
            log("= Docker が応答しない（掃除は次回）")
        return {}

    _code, listed = docker("volume", "ls", "-q", "-f", "dangling=true")
    anon = [v for v in listed.split() if re.fullmatch(r"[0-9a-f]{64}", v)]
    removed = 0
    if anon:
        if docker("volume", "rm", *anon)[0] == 0:
            removed = len(anon)

    _c, img_out = docker("image", "prune", "-f")
    _c, bc_out = docker("builder", "prune", "-f", "--filter", "until=168h")
    sizes = re.findall(r"[0-9.]+[KMG]B", img_out)
    imgs = sizes[-1] if sizes else ""
    sizes = re.findall(r"[0-9.]+[KMG]B", bc_out)
    bc = sizes[-1] if sizes else ""

    if log:
        if removed:
            log(f"- 匿名ボリューム {removed} 個を削除")
        if imgs and imgs != "0B":
            log(f"- タグの無いイメージ {imgs} を回収")
        if bc and bc != "0B":
            log(f"- ビルドキャッシュ {bc} を回収")
        if not removed and imgs in ("", "0B") and bc in ("", "0B"):
            log("= 落とすものは無かった")
    return {"volumes": str(removed), "images": imgs, "buildCache": bc}
