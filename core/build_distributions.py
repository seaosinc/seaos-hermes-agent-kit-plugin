#!/usr/bin/env python3
"""templates/ から**公式のプロファイル配布**を生成する。

    build_distributions.py <KIT_ROOT> <OUT_DIR>

Hermes には「プロファイルを git で配って更新する」公式の仕組みがある
（`hermes profile install <source>` / `profile update`）。1配布＝1プロファイルなので、
役ごとにディレクトリを1つ作る。

    dist/operator/
    ├── distribution.yaml   マニフェスト（名前・版・必要な環境変数）
    ├── SOUL.md             役の規約 ＋ 共通ブロック（差し込み済み）
    ├── config.yaml         キットが決める設定だけ（既定は Hermes が補う）
    ├── skills/             その役が読むスキル
    ├── plugins/            その役に載せるプラグイン（operator のゲート）
    ├── hooks/              gateway:startup フック（operator の mem0 起動）
    └── cron/jobs.json      定期実行

**共通ブロックの差し込みはここでやる。** 配布物は独立しているので、
プロファイル間で共有する仕組みは公式には無い。DRY を保つのは生成側の仕事になる。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import yaml

# **廃止・改名した役の台帳。** 生成物は正しいのに、エージェントが読む文書だけが
# 古い名前のまま残る——という形で2回踏んだ（researcher の廃止、messenger の改名）。
# build も test も気づかないので、doctor が名指しで照合する（core/refcheck.py）。
# **役を消す・改名したら、ここに足すこと。**
RETIRED = (
    "researcher",   # → handler（読むだけでなく書き込みも行う役に作り替えた）
    "messenger",    # → broker
    "driver",       # → avatar
    "e2e-worker",   # 廃止
    "clerk",        # 候補で終わった名前。採用していない
)

FAST = os.environ.get("MODEL_FAST", "openai/gpt-5.6-luna")
SMART = os.environ.get("MODEL_SMART", "openai/gpt-6-astra")
# 難度の高い実装だけに充てる上位モデル。**単価が高いので既定では使わない**——
# ROLES で明示的に指定した役だけが引く（いまは senior-developer のみ）。
SENIOR = os.environ.get("MODEL_SENIOR", "anthropic/claude-opus-5")
INTERVAL = int(os.environ.get("DISPATCH_INTERVAL", "15"))
VERSION = os.environ.get("KIT_VERSION", "0.1.0")

# 作業部屋（DESIGN.md の「作業部屋」）。**イメージ名は差し替えられるようにしておく。**
# 薄いイメージを自前で持つのが既定だが、全部入り（ghcr.io/openai/codex-universal 等）へ
# 寄せたくなったときに、生成器の外から変えられる余地を残す。
# **箱は1種類にする。** 実装役が自分の変更を画面で確かめられる必要があり、E2E を
# 別の役へ渡すと往復が増える。イメージが太っても起動は変わらないと実測で分かったので
# （212ms → 209ms）、分ける理由が無くなった。
WORKSPACE_IMAGE = os.environ.get("WORKSPACE_IMAGE", "hermes-workspace:latest")
WORKSPACE_CACHE = os.environ.get("WORKSPACE_CACHE_VOLUME", "hermes-workspace-cache")
# opencode に渡すモデル。**既定のままだと落ちる**——opencode が自分で選ぶ既定は
# ツール実行に対応していないことがあり（実測: google/gemini-3-pro-image-preview で
# "No endpoints found that support tool use"）、その場合エラーだけ返して何もしない。
# provider/model の形が要るので、キットのモデル名にプロバイダを冠する。
OPENCODE_PROVIDER = os.environ.get("OPENCODE_PROVIDER", "openrouter")
# 成果物の受け渡し口。カードのワークスペース（ホスト側）を**左右同じ絶対パス**で渡す。
# こうすると HERMES_KANBAN_WORKSPACE が箱の中でも外でも同じ意味になり、
# kanban_complete の artifacts がホスト側で解決できる（kanban_db.py:5647 は
# Path().resolve() でホストを見るため、箱の中のパスでは通らない）。
ARTIFACTS_ROOT = os.environ.get(
    "WORKSPACE_ARTIFACTS_ROOT", str(Path.home() / ".hermes/kanban/workspaces"))
# 作業部屋1つに割り当てる資源。**上限であって、確保量ではない。**
#
# 実測で要るのは、clone と読み書きなら 200MB 以下、`npm ci` で 0.5〜1GB、
# Nuxt / webpack のビルドで 1.5〜3GB、Chromium の E2E で ＋1GB。
# **4GB はビルドが通る余裕を見た値**である。足りないリポジトリに当たったら
# WORKSPACE_MEMORY で上げる——**黙って刈られるより、はっきり OOM で落ちるほうが扱いやすい。**
#
# 以前は 8GB × 並列無制限だった。カード2枚で 16GB になり、
# ホストが落ちかけた（実際に踏んだ）。
WORKSPACE_CPU = int(os.environ.get("WORKSPACE_CPU", "2"))
WORKSPACE_MEMORY = int(os.environ.get("WORKSPACE_MEMORY", "4096"))
# 同時に走らせるカードの数。**並列は必要なので止めないが、上限は置く。**
#
# **役ごとに別々の数を与える口は無い**（Hermes は数値1つを全役へ一律に効かせる）。
# 「箱を使う役だけ絞る」は表現できないので、全体の上限で受ける。
#
# **箱を立てるのは workspace を持つ役だけである。** いまは developer だけで、
# fixer / broker / handler / recruiter / avatar は箱を立てない。
# だから 6 枚走っても、実際に 4GB を取るのは箱を持つ役のぶんに限られる。
#
# **ただし recruiter が作る新しい役は、既定で箱を持つ**（workspace: true）。
# 箱を持つ役が増えるほど最悪値は上がる——6 枚全部が箱なら 24GB で、
# 一度落ちかけた線を超える。役を増やしたら、ここを見直すこと。
MAX_IN_PROGRESS = int(os.environ.get("MAX_IN_PROGRESS", "6"))
MAX_IN_PROGRESS_PER_PROFILE = int(os.environ.get("MAX_IN_PROGRESS_PER_PROFILE", "2"))

# 役ごとの構成。**ここが唯一の配置表**
ROLES: dict[str, dict] = {
    "operator": {
        "model": FAST,
        # 窓口。Slack の振る舞いはこの役の config で決まる。
        "gateway": True,
        "skills": ["kanban-collaboration", "guest-access"],
        "plugins": ["booking-gate"],
        "hooks": ["mem0-up"],
        "cron": ["booking-sync", "runtime-guard", "spin-guard", "container-guard",
                 "kit-sync", "kit-maintain"],
        "env": [
            ("SLACK_BOT_TOKEN", "Slack の Bot トークン（gateway が使う）", True),
            ("SLACK_APP_TOKEN", "Slack の App トークン（Socket Mode）", True),
            ("SLACK_ALLOWED_USERS", "常に話せる Slack ユーザー ID（カンマ区切り）", True),
            ("SLACK_OWNER_ID", "判断を仰ぐ相手の Slack ユーザー ID", False),
            ("SLACK_HOME_CHANNEL", "既定の投稿先チャンネル", False),
            ("OPENROUTER_API_KEY", "モデルプロバイダの API キー", True),
        ],
        "desc": "ユーザーと話す唯一の窓口。依頼をカードにして triage に置き、結果をユーザーが判断できる形で報告する。長い複数テーマの報告は意味のまとまりを保った連続投稿に分け、短文や単一テーマは分割しない。",
        "describe": ("ユーザーとの対話専用の窓口。Slack で依頼を受けてカードを作り、"
                     "結果をユーザーが判断できる形で報告する。長い複数テーマの報告は意味のまとまりを保った"
                     "連続投稿に分け、短文や単一テーマは分割しない。【重要】実作業のカードをこのプロファイルに"
                     "割り当ててはならない。"),
    },
    "fixer": {
        "model": SMART,
        "skills": ["kanban-collaboration", "precedent-lookup"],
        # 「道具が足りない」という判断を下す役なので、道具の綴りを確かめる口を持つ
        "mcp_shared": ["context7"],
        # **記憶を引くのは判断する役だけ。** 前例を今回に当てはめてよいかを
        # 決める責任が、引く役と同じところにある必要がある。
        "memory": True,
        "env": [("OPENROUTER_API_KEY", "モデルプロバイダの API キー", True)],
        "desc": "止まったカードを動かして去る。依存の整理、詰まりの解決、完了判定。",
        "describe": ("止まったカードを動かす役。依存を整理し、詰まりを解き、"
                     "終わったものの完了を判定する。道具が足りずに止まっているなら、"
                     "役そのものを作り直させて仕事を引き継がせる。"
                     "【重要】実作業のカードをこのプロファイルに割り当ててはならない。"
                     "呼ばれるのは、止まったときと、子カードが全部終わったときだけである。"),
    },
    "broker": {
        "model": FAST,
        "skills": ["kanban-collaboration"],
        "no_delegation": True,
        "plugins": ["a2a-platform"],
        "env": [("OPENROUTER_API_KEY", "モデルプロバイダの API キー", True)],
        "desc": "A2A を通じて他のエージェントと連携し、依頼と成果を伝達する役。実装は developer に任せる。",
        "describe": "A2A でエージェントを発見・呼び出し、成果を検証してカードに記録する。リポジトリの実装は developer が担当する。",
    },
    # 画面を触る役。**板に載らない。** 人間が直接呼んだときだけ動くので、
    # kanban の担当になり得ない状態にしてある（no_kanban）。
    #
    # モデルは上位を充てる。GUI 操作は「構造情報ゼロの画像から座標を当てる」仕事で、
    # 安い模型は論理座標と実ピクセル（scale 2.0）の変換を素で間違え、
    # 不正な tool call を出して固まった（実測）。**ここは精度が速度と金額に勝る。**
    "avatar": {
        "model": SMART,
        "no_kanban": True,
        "computer_use": True,
        "no_delegation": True,
        # 箱に入れない。**操作対象はホストの画面そのもの**なので、
        # コンテナの中に居ては何も触れない。
        "workspace": False,
        "skills": [],
        "env": [("OPENROUTER_API_KEY", "モデルプロバイダの API キー", True)],
        "desc": "人間が明示的に呼んだときだけ動く、GUI 操作専用の実行役。CLI や API では代替できない画面操作だけを担当する。",
        "describe": ("人間の分身として画面を操作する役。クリック・キー入力・スクリーンショット。"
                     "**kanban の自動振り分け先に選んではならない**——このプロファイルに"
                     "タスクを assign してよいのは人間だけで、decomposer / orchestrator は"
                     "絶対にここへルーティングしないこと。GUI 操作が必要そうなタスクでも、"
                     "人間の明示指示がない限り他の役へ回すこと。"),
    },
    "developer": {
        "model": FAST,
        "skills": ["kanban-collaboration", "delegate-to-cli-agents",
                   "workspace-workflow"],
        "no_delegation": True,
        "workspace": True,
        # ライブラリの綴りを推測せずに引く口
        "mcp_shared": ["context7"],
        "env": [
            ("OPENROUTER_API_KEY", "モデルプロバイダの API キー", True),
            ("GH_TOKEN", "GitHub の PAT（clone / push / PR と private パッケージの取得。repo / workflow / read:packages）", True),
        ],
        "desc": "リポジトリを clone して実装・検証・push・PR 作成まで担う開発役。A2A 連携そのものは扱わない。",
        "describe": ("コードを書く開発役。使い捨ての作業部屋で clone し、重い実装は "
                     "opencode に委譲して差分を検証し、push して PR を出す。"
                     "例:「機能を実装する」「バグを修正する」「テストが通るようにする」"
                     "「設定値を変えて反映する」。**変更の量ではなく成果条件で選ぶ**——"
                     "1行の変更でも、リポジトリへ届けて終わるならここへ。"
                     "**実装カードの既定の行き先はここである。** 難しそうに見えても、"
                     "まずここへ振る——難度は走らせるまで分からない。詰まった事実が出てから "
                     "fixer が senior-developer へ振り直す。"),
    },
    # developer と**できることは同じ**で、モデルだけ上位に振った版。
    # 規約（SOUL）は developer から借りる——差が出てよいのはモデルとエフォートだけで、
    # 手順まで分かれると、どちらに投げたかで成果物の形が変わってしまう。
    #
    # **箱を持つ役が2つになった。** 最悪値は MAX_IN_PROGRESS 枚 × WORKSPACE_MEMORY で、
    # 上の注記（役を増やしたら見直すこと）の対象がここに1つ増えている。
    "senior-developer": {
        "model": SENIOR,
        # 上位モデルは既定 low。**難度で単価を上げる役であって、
        # 毎回めいっぱい考えさせる役ではない。**
        "reasoning": "low",
        "soul_from": "developer",
        # 借りた SOUL の後ろに、この役だけの節を足す（受け持つ範囲と受け取り方の差）。
        "soul_extra": "SOUL.extra.md",
        "skills": ["kanban-collaboration", "delegate-to-cli-agents",
                   "workspace-workflow"],
        "no_delegation": True,
        "workspace": True,
        "mcp_shared": ["context7"],
        "env": [
            ("OPENROUTER_API_KEY", "モデルプロバイダの API キー", True),
            ("GH_TOKEN", "GitHub の PAT（clone / push / PR と private パッケージの取得。repo / workflow / read:packages）", True),
        ],
        "desc": "developer の上位版。実装に加えてセキュリティとコード品質まで見る。設計判断を伴うもの、developer が詰まったものを引き取る。A2A 連携そのものは扱わない。",
        "describe": ("developer と同じ開発役で、実装に加えて**セキュリティとコード品質まで見る**版。"
                     "**難度ではなく根拠で選ぶ**——「難しそう」では選ばない（単価が高い）。"
                     "次のどれかがカードに**事実として**書かれているときだけここへ: "
                     "(1) developer が試して詰まり、何を試したかが記録されている "
                     "(2) 設計判断が要る（選択肢が複数あり、採る案で後の形が変わる） "
                     "(3) セキュリティか品質に影響が及ぶ（認証・権限・秘密の扱い・外部入力の経路）。"
                     "**新規のカードは既定で developer へ振る。** 難度は走らせるまで分からないので、"
                     "詰まった事実が出てから fixer が振り直す。"),
    },
}


def worker_roles(kit: Path) -> dict[str, dict]:
    """業務別ワーカーは templates/workers/ から拾う。"""
    out = {}
    # **`_` で始まるものは雛形。** 役として配らない。
    # 「何でもやる役」は役割の不在で、不在だとモデルも道具も作業環境も選べない
    # ——本番に置くと構成が全部曖昧になる。雛形としてだけ残す。
    for d in sorted(p for p in (kit / "templates/workers").glob("*")
                    if p.is_dir() and not p.name.startswith("_")):
        prof = yaml.safe_load((d / "profile.yaml").read_text(encoding="utf-8")) or {}
        out[d.name] = {
            "model": prof.get("model") or FAST,
            # コードを書く役だけに委譲のスキルと実装の規約を載せる。
            # 調べるだけの役に clone / push / 委譲を教えても、使い道が無いうえに
            # 「自分の仕事だ」と誤解させる。
            "implements": prof.get("implements", True),
            "skills": (["kanban-collaboration", "delegate-to-cli-agents",
                        "workspace-workflow"]
                       if prof.get("implements", True) else ["kanban-collaboration"]),
            "own_skills": d / "skills",
            "worker": True,
            "no_delegation": True,
            # 自分の SOUL を書き換える役なので、命令ファイルの保護と承認を外す
            "hotl": d.name == "recruiter",
            "mcp": d / "mcp.yaml",
            # **業務別ワーカーは既定で context7 を持つ。** どのワーカーも、
            # 道具の名前・設定キー・API の綴りを書く場面がある。外れても静かに
            # 落ちる場所が多いので、推測の代わりに引ける口を最初から置く。
            "mcp_shared": prof.get("mcp_shared", ["context7"]),
            # 作業部屋に入れるか。プロファイルを書き換える役（recruiter）は
            # ホストのファイルに届く必要があるので、箱に入れない。
            "workspace": prof.get("workspace", d.name != "recruiter"),
            # **コマンドを実行させるか。** false にすると terminal ごと外れる。
            # 他人が書いた文章を読む役（handler）は、読んだ内容に影響された状態で
            # コマンドを打つ経路そのものを持たないほうが堅い。
            "shell": prof.get("shell", True),
            "extra": prof.get("extra", ""),
            "desc": " ".join((prof.get("description") or "").split()),
            "describe": " ".join((prof.get("description") or "").split()),
            "env": [("OPENROUTER_API_KEY", "モデルプロバイダの API キー", True)]
                   + ([("GH_TOKEN", "GitHub の PAT（clone / push / PR と private パッケージの取得。repo / workflow / read:packages）", True)]
                      if (prof.get("workspace", d.name != "recruiter")
                          and prof.get("shell", True)) else [])
                   # **MCP を足した役は、たいてい鍵も要る。** profile.yaml で宣言させ、
                   # env apply が配る。宣言しないと、サーバは起動しても認証されない
                   # まま「有効」に見える。
                   + [(r["name"], r.get("description", ""), bool(r.get("required", True)))
                      for r in (prof.get("env_requires") or [])],
        }
    return out


def build_soul(kit: Path, name: str, spec: dict) -> str:
    """役の SOUL に共通ブロックを差し込む。"""
    if spec.get("worker"):
        src = kit / "templates/workers" / name / "SOUL.md"
        def _block(fname: str) -> str:
            text = (kit / "templates/workers" / fname).read_text(encoding="utf-8")
            # コメント行（雛形の説明）は配布物には要らない
            return text.split("-->", 1)[-1].strip()

        base = _block("_worker-base.md")
        if not spec.get("shell", True):
            # ファイルを書けない役に「成果物を置いて宣言する」を教えても実行できない。
            # 報告はカードのコメントで完結する。
            base = base.split("## 見せたいものは成果物として渡す")[0].rstrip() + "\n\n" + \
                   "## " + base.split("## 見せたいものは成果物として渡す")[1].split("## ", 1)[1]
        if spec.get("implements", True):
            base = _block("_worker-impl.md") + "\n\n" + base
        body = src.read_text(encoding="utf-8")
        body = body.replace("{{NAME}}", name)
        body = body.replace("{{WORKER_BASE}}",
                            f"<!-- WORKER-BASE:BEGIN -->\n{base}\n<!-- WORKER-BASE:END -->")
        body = body.replace("{{EXTRA}}", spec.get("extra", "") or "")
    else:
        # **同じ規約の役は SOUL を借りる。** できることが同じでモデルだけ違う役
        # （senior-developer）のために 14KB を書き写すと、直すたびに片方が取り残される。
        src_name = spec.get("soul_from", name)
        body = (kit / "templates/profiles" / src_name / "SOUL.md").read_text(encoding="utf-8")
        if src_name != name:
            # **借りた SOUL は借り元の名前で始まっている。** そのままだと
            # 「あなたの名前は developer である」と読み、自分を借り元だと思い込む
            # （doctor の「SOUL 冒頭で自分の名前を名乗っていない」で気づいた）。
            # 冒頭の名乗りだけ、実際の役名へ書き換える。
            head, _, rest = body.partition("\n")
            body = head.replace(f"**{src_name}**", f"**{name}**") + "\n" + rest
        # 借りた SOUL に、その役だけの節を足す。**借りる＝同一ではない。**
        # 手順（clone → 実装 → 検証 → push）は同じでも、受け持つ範囲や
        # カードの受け取り方が違う役がある（senior-developer）。
        # 差分だけをここで継ぎ足し、共通部分は借り元の1箇所に保つ。
        if spec.get("soul_extra"):
            extra = (kit / "templates/profiles" / name / spec["soul_extra"]).read_text(encoding="utf-8")
            body = body.rstrip() + "\n\n" + extra.strip() + "\n"

    shared = "\n\n".join(
        f.read_text(encoding="utf-8").strip()
        for f in sorted((kit / "templates/shared").glob("*.md"))
    )
    return (body.rstrip() + "\n\n<!-- SHARED:BEGIN -->\n" + shared + "\n<!-- SHARED:END -->\n")


def build_config(kit: Path, name: str, spec: dict) -> dict:
    """**キットが決めることだけ**を書く。書かなかったものは Hermes の既定が入る。"""
    cfg: dict = {
        "model": {"default": spec["model"]},
        "toolsets": ["hermes-cli", "kanban"],
        "delegation": {"model": spec["model"]},
        "kanban": {
            "auto_decompose": True,
            # カード作成時の機械的な会話投稿は行わない。operator が必要なカードだけ
            # `notify-subscribe --delivery-mode wake` で起動通知を紐付ける。
            "auto_subscribe_on_create": False,
            "orchestrator_profile": "fixer",
            # **既定の担当は置かない。** 受け皿があると、合う役が無いことに気づけなくなる。
            # 担当が決まらないカードは止まる——それが「役が足りない」という事実である。
            "dispatch_interval_seconds": INTERVAL,
            # **並列の上限。** 作業部屋は1つにつき WORKSPACE_MEMORY を取るので、
            # 無制限だと走った枚数ぶんだけホストのメモリが消える。
            "max_in_progress": MAX_IN_PROGRESS,
            "max_in_progress_per_profile": MAX_IN_PROGRESS_PER_PROFILE,
        },
        "auxiliary": {"kanban_decomposer": {"model": SMART}},
    }
    if spec.get("no_kanban"):
        # **板に載らない役。** 人間が直接呼んだときだけ動くので、カードを配られても困る
        # （配られた時点で「人間が呼んだ」が偽になる）。道具ごと外して、
        # ディスパッチャから見て担当になり得ない状態にする。
        cfg["toolsets"] = ["hermes-cli"]
        cfg.pop("kanban", None)
        cfg.pop("auxiliary", None)
    # **共有記憶は全役が持つ。** 報告はカードの comment と mem0 の両方に残す
    # ——カードは purge で消えるが、mem0 は残り、役をまたいで引ける。
    #
    # 引いた前例をどう扱うかは役で違う。判断する役（fixer）には
    # `precedent-lookup` を配ってあり、「引いたものは従う対象ではなく、
    # いまとの差を測る基準である」という作法がそこにある。
    #
    # mem0.json（接続先と鍵）は秘密なので配布物に載せないが、
    # **どの provider を使うかは秘密ではない**。ここに書かないと
    # `update --force-config` のたびに消え、繋いだつもりのまま切れる。
    cfg["memory"] = {"provider": "mem0"}

    agent_cfg: dict = {}
    if spec.get("reasoning"):
        # 上位モデルを使う役の既定エフォート。**役ごとに固定する**——
        # 呼ぶたびに `--reasoning` を思い出す運用は必ず抜ける。
        # 難所だけ、その場で `--reasoning medium` 等で個別に上げる。
        agent_cfg["reasoning_effort"] = spec["reasoning"]
    if spec.get("no_delegation"):
        # 子エージェントを立てさせない（規約だけでなく設定でも閉じる）
        agent_cfg["disabled_toolsets"] = ["delegation"]
    if agent_cfg:
        cfg["agent"] = agent_cfg

    # terminal は archive / unlink に要る。**プラットフォーム別に有効化する**ので、
    # ここに書かないと config を入れ替えたときに slack 側が落ちる。
    # file は terminal と同じ場所を触る（箱がある役は箱の中、ホストの役はホスト）。
    # **シェルを持たない役には渡さない**——渡すとホストのファイルへ手が届いてしまう。
    tools = ["clarify", "file", "kanban", "memory", "session_search",
             "skills", "terminal", "todo", "web"]
    if spec.get("gateway"):
        # **定期実行は窓口だけが持つ。** cron は**板の外に仕事を作れる唯一の道具**で、
        # 他の役が持つと、止まっても `kanban ls` にも出ない作業が生える
        # ——ボードが唯一の共有状態である、という前提がそこだけ崩れる。
        #
        # 繰り返しの依頼は、窓口が cron に「カードを立てる一手」だけを持たせる
        # （operator の SOUL）。仕事そのものは毎回カードとして板に現れる。
        tools.append("cronjob")
    if not spec.get("shell", True):
        # **コマンドを実行する手を持たせない。** MCP と web だけで調べる役に使う。
        # workspace を false にするだけでは、シェルがホストへ移るだけで手は残る。
        tools = [t for t in tools if t not in ("terminal", "file")]
    if spec.get("no_kanban"):
        tools = [t for t in tools if t != "kanban"]
    if spec.get("computer_use"):
        # 画面を触る役。**vision と対で渡す**——スクリーンショットを撮っても、
        # 読む手が無ければ何も分からない。
        tools += ["computer_use", "vision"]
    cfg["platform_toolsets"] = {plat: tools for plat in ("cli", "slack")}

    if spec.get("gateway"):
        # **窓口の振る舞い。** スレッドに複数人がいる前提で組む。
        #
        # チャンネルでもスレッドでも、**呼ばれたときだけ**答える。スレッドは
        # 既定だと「一度参加したら以降はメンション不要」なので、人が増えると
        # 他人あての発言にも反応する。DM は逆で、メンションは要らない
        # （require_mention はチャンネルとスレッドにしか効かない）。
        #
        # **チャンネルではスレッドに返す。** 人がいる場所で平場に流すと、
        # 他の会話に割り込む。`reply_in_thread` は DM とチャンネルを区別しない
        # 1つのスイッチなので（Hermes の `_resolve_thread_ts` は文脈を見ない）、
        # 人がいる側に合わせる。
        cfg["platforms"] = {
            "slack": {
                "reply_to_mode": "first",
                "extra": {
                    "require_mention": True,
                    "thread_require_mention": True,
                    # 先頭が他人あてのメンションなら、自分も呼ばれていない限り無視する
                    "ignore_other_user_mentions": True,
                    "reply_in_thread": True,
                    # Slack の送受信リアクションは本体の機能を使う。実際に有効化するには
                    # App 側の reactions:read / reactions:write scope と reaction_added /
                    # reaction_removed event subscription も必要（オーナーが再認可する）。
                    "reactions": True,
                    "reaction_triggers": True,
                },
            }
        }

    if spec.get("hotl"):
        # 承認プロンプトを出さない（HOTL: Human Out The Loop）。
        #
        # この環境には承認に応えるユーザーがいない。無人実行では承認待ちがタイムアウトして
        # 拒否になり、ツールは再試行と迂回を禁止するので、カードはそこで永久に止まる。
        # SOUL.md は Hermes の保護命令ファイル（AGENTS.md / CLAUDE.md と同じ扱い）で、
        # 置き場所を問わず書き込みに承認を要求する——**それが recruiter の仕事の中核**。
        #
        # 緩めるのはこの役だけにする。全体を緩めると、どのエージェントも任意の命令ファイルを
        # 書き換えられるようになる。1体に絞れば、書き換えの経路もその1体に限られる。
        # 引き換えに、止めるものは承認ではなく SOUL の規約になる
        # （「自分の足元を書き換えるときは止まって報告する」）。
        cfg["approvals"] = {
            "mode": "off",
            "cron_mode": "approve",
            "single_query_mode": "approve",
            "mcp_reload_confirm": False,
            "destructive_slash_confirm": False,
        }
        cfg["security"] = {"protected_instruction_files": False}
        cfg["hooks_auto_accept"] = True

    if spec.get("workspace") and spec.get("shell", True):
        # 作業部屋（DESIGN.md の「作業部屋」）。カードごとにコンテナを立てて捨てる。
        cfg["terminal"] = {
            # **`backend` で書く。`env_type` では効かない。**
            # 既定に terminal.backend: local が入っており（config_defaults.py:376）、
            # cli.py:631 が backend を env_type より優先して上書きする。
            # env_type だけ書くと、他の TERMINAL_* は正しく渡るのに
            # バックエンドだけ local のまま——**気づきにくい形で箱に入らない。**
            "backend": "docker",
            "docker_image": WORKSPACE_IMAGE,
            # **cwd を省けない。** ディスパッチャがカードのホスト側ワークスペース
            # （コンテナ内に存在しないパス）を TERMINAL_CWD へ焼き込むため
            # （kanban_db.py:10786）。担当は gateway ではなく `hermes -p <役> --cli` で
            # 起動するので、config の値が必ず勝つ（cli.py:694 "CLI: always export"）。
            "cwd": "/workspace",
            # **true にする。** false だと /workspace が tmpfs になり、コマンドの合間に
            # 部屋ごと消える。clone した成果が次の操作へ渡らず、以後の terminal が全部
            # `No such container` で落ちる（実装カードが同じ原因で5回続けて失敗した）。
            # 調べるだけのカードは1コマンドで完結するので落ちず、**clone を伴う実装だけ**
            # が落ちるため、原因が作業部屋にあると気づきにくい。
            "container_persistent": True,
            "docker_network": True,
            "container_cpu": WORKSPACE_CPU,
            "container_memory": WORKSPACE_MEMORY,
            # 部屋を捨てても残る唯一の場所。**公開パッケージと言語ランタイムだけ**が入る。
            "docker_volumes": [
                f"{WORKSPACE_CACHE}:/cache",
                # 成果物を外へ出すための口。**左右同じパスにするのが要点**で、
                # ずらすと artifacts の宣言がホスト側で解決できない。
                f"{ARTIFACTS_ROOT}:{ARTIFACTS_ROOT}",
            ],
            # ホストの値を名前で転送する。**イメージには焼かない。**
            "docker_forward_env": [
                "GH_TOKEN", "OPENROUTER_API_KEY",
                # **カードの識別と成果物の置き場。** 秘密ではないが、渡さないと
                # 規約が指す $HERMES_KANBAN_WORKSPACE が箱の中で空になり、
                # 成果物の宣言が / 直下を指してしまう（実際に踏んだ）。
                "HERMES_KANBAN_TASK", "HERMES_KANBAN_WORKSPACE",
            ],
            # 固定値。委譲先のモデルを担当に覚えさせず、ここ1箇所で決める。
            "docker_env": {"OPENCODE_MODEL": f"{OPENCODE_PROVIDER}/{spec['model']}"},
        }

    if spec.get("plugins"):
        # 置くだけでは有効にならない（既定は無効）。配布物の側で有効にしておく。
        cfg["plugins"] = {"enabled": list(spec["plugins"]), "disabled": []}
    servers: dict = {}
    # **全役で同じものは1箇所に置く**（templates/shared/mcp/<名前>.yaml）。
    # 役ごとに書き写すと、直すたびに全部を直すことになり、必ず取り残される。
    for name in spec.get("mcp_shared") or []:
        f = kit / "templates/shared/mcp" / f"{name}.yaml"
        if f.exists():
            servers.update(yaml.safe_load(f.read_text(encoding="utf-8")) or {})
    if spec.get("mcp") and Path(spec["mcp"]).exists():
        mcp = yaml.safe_load(Path(spec["mcp"]).read_text(encoding="utf-8")) or {}
        # 雛形は `servers:` を頂点に持つ。**そのまま入れると1段深くなる**
        # （mcp_servers.servers.<名前> になり、Hermes からは空に見える）。
        # 中身が入るまで空 dict だったので、長らく露呈しなかった。
        # 役が自分で書いたものを後にして、共通より優先させる。
        servers.update(mcp.get("servers", mcp) if isinstance(mcp, dict) else {})
    if servers:
        cfg["mcp_servers"] = servers
    return cfg


# cron のジョブ表。実体のスキーマ（schedule はオブジェクト、id や state が要る）に
# 合わせる。手で書くとずれるので、**Hermes が読める最小限**をここで組み立てる。
# 定期実行の定義。**登録は hermes cron create（公式）でやる**ので、ここは表だけ。
# hermes-kit install が --jobs で引いて、無いものを作る。
CRON_JOBS = {
    "booking-sync":  ("* * * * *",    "booking_sync.py"),
    # **毎分。** 短すぎる上限のカードは実行中に殺され、2回で gave_up になる。
    # 規約で止まらなかったので、入ってしまったものをここで直す。
    "runtime-guard": ("* * * * *",    "runtime_guard.py"),
    # **5分ごと。** ディスパッチャが再spawnを見送ったことは `ready` のままの
    # カードに現れないので、空転はボードから見えない。実際に4時間空転した。
    # 見つけたら入力待ちへ移して、人の目に入る場所へ出す。
    "spin-guard":    ("*/5 * * * *",  "spin_guard.py"),
    # **毎分。** 親が SIGKILL されると作業部屋は running のまま残り、
    # Hermes の回収係（status=exited しか見ない）は一生届かない。1つ 4GB。
    "container-guard": ("* * * * *",  "container_guard.py"),
    "kit-sync":      ("*/10 * * * *", "kit_sync.sh"),
    "kit-maintain":  ("30 4 * * *",   "kit_maintain.sh"),
}


IGNORE = shutil.ignore_patterns("__pycache__")


def copy_skills(kit: Path, d: Path, spec: dict) -> None:
    """共通のスキルと、その役だけのスキル（ワーカーの専用スキル）を入れる。"""
    (d / "skills").mkdir(parents=True, exist_ok=True)
    for name in spec.get("skills", []):
        shutil.copytree(kit / "templates/skills" / name, d / "skills" / name, ignore=IGNORE)
    own = spec.get("own_skills")
    if own and Path(own).exists():
        for src in sorted(p for p in Path(own).glob("*") if p.is_dir()):
            shutil.copytree(src, d / "skills" / src.name, ignore=IGNORE)


def copy_runtime(kit: Path, d: Path, spec: dict) -> list[str]:
    """プラグイン・フック・スクリプト。載せたものを distribution_owned として返す。"""
    owned: list[str] = []
    for name in spec.get("plugins", []):
        # A2A は Hermes の組み込みプラグインで、キット固有のファイルは持たない。
        if name == "a2a-platform":
            continue
        shutil.copytree(kit / "templates/booking-gate/plugin", d / "plugins" / name, ignore=IGNORE)
        owned.append("plugins/")

    for name in spec.get("hooks", []):
        shutil.copytree(kit / "templates/hooks" / name, d / "hooks" / name, ignore=IGNORE)
        owned.append("hooks/")
    if spec.get("cron"):
        # **cron/jobs.json は配布物に載せない。**
        # 載せると profile update のたびに、スケジューラが持っている状態
        # （id / next_run_at / last_run_at）を骨だけの版で上書きしてしまう。
        # kit-sync が10分ごとに update を回すので、10分ごとにジョブが死ぬ（実際に死んだ）。
        # 登録は公式の `hermes cron create` に任せる（hermes-kit install が冪等にやる）。
        #
        # スクリプトだけは配る。cron は**プロファイル配下の scripts/ しか実行しない**
        # （cron/scheduler.py:3966）。
        (d / "scripts").mkdir(exist_ok=True)
        for src in [*(kit / "templates/booking-gate/sync").glob("*.py"),
                    *(kit / "templates/cron").glob("*.sh"),
                    *(kit / "templates/cron").glob("*.py")]:
            shutil.copy2(src, d / "scripts" / src.name)
        owned.append("scripts/")
    if spec.get("workspace") and spec.get("shell", True):
        # 作業部屋の作り方を配布物に同梱する。**プロファイルだけ受け取った人でも
        # 自分で建てられる**ようにするため（イメージ自体はマシンごとの生成物なので配れない）。
        shutil.copytree(kit / "templates/workspace", d / "workspace", ignore=IGNORE)
        owned.append("workspace/")
    return owned


def build_manifest(name: str, spec: dict, owned: list[str]) -> dict:
    return {
        "name": name,
        "version": VERSION,
        "description": spec.get("desc", ""),
        "author": "seaos-hermes-agent-collab-kit",
        # 秘密は配布物に入れず、**必要な環境変数として宣言する**。
        # インストール時に「設定済みか」が表示され、.env.EXAMPLE も作られる。
        "env_requires": [
            {"name": n, "description": desc, "required": req}
            for n, desc, req in spec.get("env", [])
        ],
        "distribution_owned": sorted(set(owned)),
    }


def build_one(kit: Path, out: Path, name: str, spec: dict) -> None:
    d = out / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SOUL.md").write_text(build_soul(kit, name, spec), encoding="utf-8")
    (d / "config.yaml").write_text(
        yaml.safe_dump(build_config(kit, name, spec), allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    copy_skills(kit, d, spec)
    # **スキルは1つずつ名指しする。** `skills/` とまとめて宣言すると、更新のたびに
    # そのフォルダが rmtree されて作り直される（profile_distribution.py の
    # `_copy_dist_payload`）。**実機で Hermes やエージェントが生やしたスキルが
    # 毎回消える。** 配るものだけを持ち物にすれば、増えたぶんは触られない。
    owned = ["SOUL.md", "config.yaml", "distribution.yaml"]
    owned += [f"skills/{p.name}" for p in sorted((d / "skills").iterdir()) if p.is_dir()]
    owned += copy_runtime(kit, d, spec)
    (d / "distribution.yaml").write_text(
        yaml.safe_dump(build_manifest(name, spec, owned), allow_unicode=True, sort_keys=False),
        encoding="utf-8")

    extras = " ".join(k for k in ("plugins", "hooks", "cron") if spec.get(k))
    print(f"  + {name}  （skills {len(list((d / 'skills').glob('*')))}"
          f"{' / ' + extras if extras else ''}）")


def build(kit: Path, out: Path) -> None:
    roles = {**ROLES, **worker_roles(kit)}
    # 役を消したら配布物も消す。残すと install できてしまい、
    # 「templates には無いのにプロファイルが生える」ことになる
    for stale in sorted(p for p in out.glob("*") if p.is_dir() and p.name not in roles):
        shutil.rmtree(stale, ignore_errors=True)
        print(f"  - {stale.name}（役が無くなったので削除）")
    for name, spec in roles.items():
        shutil.rmtree(out / name, ignore_errors=True)
        build_one(kit, out, name, spec)


def skills_of(kit: Path, role: str) -> list[str]:
    """その役に載るスキル。**doctor はここを正とする。**

    インストーラは distribution.yaml を正規化して独自キーを落とすので、
    配布物側に一覧を持たせても読み返せない。生成側が答える。
    """
    roles = {**ROLES, **worker_roles(kit)}
    spec = roles.get(role)
    if not spec:
        return []
    names = list(spec.get("skills", []))
    own = spec.get("own_skills")
    if own and Path(own).exists():
        names += [p.name for p in Path(own).glob("*") if p.is_dir()]
    return sorted(set(names))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--jobs":
        # "<名前> <式> <スクリプト>" を1行ずつ。install が読む
        kit = Path(sys.argv[2])
        roles = {**ROLES, **worker_roles(kit)}
        for role, spec in roles.items():
            for name in spec.get("cron", []):
                expr, script = CRON_JOBS[name]
                print(f"{role}\t{name}\t{expr}\t{script}")
    elif len(sys.argv) > 2 and sys.argv[1] == "--describe":
        kit = Path(sys.argv[3] if len(sys.argv) > 3 else ".")
        roles = {**ROLES, **worker_roles(kit)}
        print((roles.get(sys.argv[2]) or {}).get("describe", ""))
    elif len(sys.argv) > 2 and sys.argv[1] == "--env":
        # その役が要る環境変数。**.env に何を書けばいいか**を zsh 側へ渡す口。
        # 配布物の .env.EXAMPLE は profile install のときしか作られず、
        # update では更新されない——鍵を増やしても受け手に伝わらないので、
        # 生成器が持っている宣言を正とする。
        kit = Path(sys.argv[3] if len(sys.argv) > 3 else ".")
        roles = {**ROLES, **worker_roles(kit)}
        for name, desc, required in (roles.get(sys.argv[2]) or {}).get("env", []):
            print(f"{name}\t{'required' if required else 'optional'}\t{desc}")
    elif sys.argv[1:2] == ["--env-all"]:
        # 全役の宣言をまとめる。**キット直下の .env の正**になる。
        # 同じ名前が複数の役に出るので、説明は最初のものを採り、使う役を並べる。
        kit = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".")
        roles = {**ROLES, **worker_roles(kit)}
        seen: dict[str, tuple[str, bool, list[str]]] = {}
        for role, spec in roles.items():
            for name, desc, required in spec.get("env", []):
                if name in seen:
                    seen[name][2].append(role)
                else:
                    seen[name] = (desc, required, [role])
        for name, (desc, required, users) in seen.items():
            print(f"{name}\t{'required' if required else 'optional'}\t{desc}\t{' '.join(users)}")
    elif sys.argv[1:2] == ["--workspace"]:
        # 作業部屋の設定を zsh 側へ渡す。**名前を2箇所で持たない**ための口。
        kit = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".")
        roles = {**ROLES, **worker_roles(kit)}
        print(f"image\t{WORKSPACE_IMAGE}")
        print(f"cache\t{WORKSPACE_CACHE}")
        print("roles\t" + " ".join(r for r, sp in roles.items()
                                   if sp.get("workspace") and sp.get("shell", True)))
        # **意図的に terminal を持たない役。** doctor が「壊れている」と誤判定しないように。
        print("shellless\t" + " ".join(r for r, sp in roles.items() if not sp.get("shell", True)))
        # 役ごとの期待イメージ。**派生を使う役があるので、1つに決め打ちできない。**
        for r, sp in roles.items():
            if sp.get("workspace") and sp.get("shell", True):
                print(f"role\t{r}\t{WORKSPACE_IMAGE}")
    elif len(sys.argv) > 2 and sys.argv[1] == "--roles":
        kit = Path(sys.argv[2])
        print(" ".join({**ROLES, **worker_roles(kit)}.keys()))
    elif len(sys.argv) > 1 and sys.argv[1] == "--no-kanban":
        # 板に載らない役。**doctor が「kanban が無い」を咎めないため**の口
        # （zsh 側で役名を別に持つと、役を足したときに片方だけ古くなる）。
        kit = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
        roles = {**ROLES, **worker_roles(kit)}
        print(" ".join(n for n, sp in roles.items() if sp.get("no_kanban")))
    elif len(sys.argv) > 2 and sys.argv[1] == "--memory-roles":
        # 共有記憶を引く役。**zsh 側で別に持たない**ための口
        # （持つと、判断役を増やしたときに片方だけ古くなる）。
        kit = Path(sys.argv[2])
        print(" ".join({**ROLES, **worker_roles(kit)}.keys()))
    elif len(sys.argv) > 2 and sys.argv[1] == "--skills":
        print(" ".join(skills_of(Path(sys.argv[3] if len(sys.argv) > 3 else "."), sys.argv[2])))
    else:
        build(Path(sys.argv[1]), Path(sys.argv[2]))
