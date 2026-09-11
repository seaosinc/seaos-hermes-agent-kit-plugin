# いまどこまで出来ているか

`seaos-hermes-agent-collab-kit`（zsh 版）の後継。**キットそのものを Hermes の
プラグインとして配る**形にした。完成したら旧キットは撤去する。

## 動くもの

| | |
|---|---|
| `core/` | 生成・差分・説明文の同期・鍵配布・反映。**Python のみ** |
| `core/cli.py` | 薄い皮（16コマンド） |
| `core/worker.py` | 業務別ワーカーの CRUD |
| `core/workspace.py` | 作業部屋（CA / build / warm / verify / clean / gc） |
| `core/mem0.py` | 共有記憶（起動・接続・切り離し） |
| `core/booking.py` | アクセスゲートの検証とゲスト操作 |
| `core/hotl.py` | HOTL 設定の検証 |
| `core/terraform.py` | AWS の箱に渡す値の書き出し |
| `core/doctor.py` | 設定漏れの検証（全モジュールの check を束ねる） |
| `core/selftest.py` | 生成物の形の検査 |
| `core/selfupdate.py` | pull → 反映 → 検証 |
| `core/platform_ops.py` | **OS で違うことだけ**（常駐 / コマンドの置き場 / 自動起動） |
| `core/install.py` | 導入と撤去（配布物に載らないもの） |
| `dashboard/plugin_api.py` | GUI から core を呼ぶ口。全ルート応答を実機で確認済み |
| `desktop/plugin.js` | 鍵 → 役 → 反映 の3段ウィザード。素の ESM（ビルド不要） |
| `templates/` | 役の定義。旧キットから持ち込み、**現行の8役と一致**（diff が全て `=`） |

インストールはローカルの bare リポジトリから実証済み。

```
hermes plugins install file:///Users/t-adachi/Hermes/kit.git
hermes plugins enable seaos-hermes-agent-kit
```

`~/.hermes/plugins/seaos-hermes-agent-kit/` に **1フォルダで全部**入る。

## 分かったこと（踏んだもの）

- **マニフェストは v1 で書く。** ローダ（`plugins.py`）は v2 を読めるが、**入口の
  インストーラ（`plugins_cmd.py`）は v1 まで**。v2 を宣言すると install で弾かれる。
- **`diff` に `config.yaml` を入れてはいけない。** `profile update` が既定で保持するので、
  生成物と一致しないのが正常な状態。比べると全役が永久に「更新される」と出る。
- **生成器の stdout を飲む。** CLI では表示だが、GUI から呼ぶと API の経路へ漏れる。
- **`.env` はインストール先ごとに別。** git に入らないので、配った先では
  ウィザードで入れ直す。これは仕様（1フォルダで自己完結する）。

## 対応 OS

**利用者向けは Windows と macOS の2つ。** Linux は落とさない——terraform が立てる
AWS の箱が Ubuntu 24.04 で、cloud-init がそこでキットを動かすため（`terraform/main.tf`）。
つまり Linux は「自分自身を動かす先」としてだけ残る。

| | 常駐 | コマンドの置き場 |
|---|---|---|
| macOS | 素のプロセス（launchd は使わない。plist が再生成され HERMES_PROFILE が消えるため） | `~/.local/bin/seaos-kit`（ラッパ） |
| Windows | 素のプロセス ＋ Scheduled Task | `%LOCALAPPDATA%\Programs\seaos-kit\seaos-kit.cmd` |
| Linux（AWS のみ） | systemd user unit ＋ linger | `~/.local/bin/seaos-kit`（ラッパ） |

## 残っている作業

1. **Windows の実機確認。** 実装は入れたが、動かしていない
   （`gateway_pid` の PowerShell 経由の検出、`kit.cmd` のラッパ、Scheduled Task）。
2. **採番。** いま `0.0.0` 固定。旧キットは全役 `0.1.0` のまま動かず、更新が届いたか
   判定できなくなっていた。ビルド時に git から採番する。
3. **GUI の実機確認。** デスクトップアプリで Python 側・desktop 側のトグルを
   2つとも入れて、画面が出るところまで。
4. **AWS を developer / senior-developer に触らせる。** Terraform を扱い始めると要る。
   いまこの2役が持つのは箱（terminal / workspace）と GH_TOKEN だけで、AWS の状態を
   読む手が無い。作業部屋にも `aws` は入っていない（git / gh / mise / opencode /
   jq / rg / curl のみ）。

   **道具は CLI でも MCP でもよい。条件は「人の認証が要らないこと」。**

   | 認証 | 可否 | 備考 |
   |---|---|---|
   | EC2 のインスタンスロール | ◎ | **鍵が存在しない。** サーバではこれ |
   | 静的なアクセスキー | ○ | 手元でも無人で通る。長期の秘密なので参照（7）へ乗せる |
   | AWS SSO | ✗ | 定期的に人がログインする。条件から外れる |

   **CLI を作業部屋に入れるのが素直。** Terraform はどのみち箱の中で走るので、
   認証もそこに要る。ホスト側の MCP だと読めても `apply` ができない。

   **ただしこれは原則の例外になる。** キットは「MCP はホストで動かすので、
   使い捨てコンテナにトークンが入らない」を前提にしている。読むだけなら
   ホスト側 MCP で原則を守れるが、Terraform を回すなら箱に入れるしかない。
   **渡すなら読む手から**始め、`apply` まで持たせるかは別に決める。

5. **`gateway: true` の役ごとに、窓口の設定を分けられるようにする。**
   いまは窓口が operator ひとつなので露呈していないが、プロジェクト専用のボット
   （別の Slack App を持ち、そいつ宛の話はそいつが返す役）を足すと詰まる。
   **塞がっているのは2箇所ある。**

   **(a) 鍵が名前ごとに1つしかない。** `env.apply()` は `source.get(var)` で
   引くので、2つの役が `SLACK_BOT_TOKEN` を宣言すると同じ値が配られる。
   プロファイル側の `.env` は役ごとに分かれていて**受け皿はある**ので、
   正（キット直下の `.env`）の側を分けられるようにすればよい。

       SLACK_BOT_TOKEN=xoxb-…                     既定（いままでどおり）
       PROJECT_OPERATOR__SLACK_BOT_TOKEN=xoxb-…   その役だけ別の値

   配るときに `<役>__<変数>` を先に見て、無ければ既定へ落とす。既存の挙動は
   変わらない。配置表に「**この役は自分専用の値が要る**」と宣言できるようにすると、
   設定画面も役ごとに行を出せる。

   **(b) Slack の振る舞いが固定。** 生成器は `gateway: true` の役すべてに同じ
   ブロックを書く（`require_mention` / `reply_in_thread` / リアクション設定）。
   役ごとの上書きを持てるようにする。

   **同じトークンで2つのゲートウェイを繋がないこと**——両方が同じ発言を拾って
   二重に返事をする。ボットを増やすなら Slack App ごと分ける。
   板の配車係は `~/.hermes/kanban/.dispatcher.lock` で全体に1つなので、
   ゲートウェイを増やしても二重に配られることはない。

6. **Slack App の作成を recruiter に持たせる。** 調べた結果、**人の操作は2回で済む。**

   - `apps.manifest.create` でアプリを作成。スコープ・イベント購読・Socket Mode の
     有効化までマニフェストに書ける。応答に `app_id`、資格情報、そして
     **`oauth_authorize_url`** が入る
   - **人が押すのは2箇所だけ**: その URL を開いてワークスペースへ入れる（`xoxb-` が出る）、
     管理画面で App レベルトークンを発行する（`xapp-`。**API では作れない**）
   - 設定トークンは **12時間で失効**する。`tooling.tokens.rotate` で回せるので、
     recruiter に持たせるなら更新の仕組みが要る。最初の1つは管理画面から取る

   ComputerUse で押しに行くより、この2回を人に任せるほうが確実である。

7. **秘密は当面「設定画面に入れる」ままにする。**（1Password 版は保留）

   **いまの形で要件は満たせている。** 値は手元の `.env` にしか書かれず、
   API は値を返さない（書き込み専用。テストで保証）。**Slack にも AI にも
   流れない**——出発点だった「値を会話に乗せない」はこれで足りている。

   ### なぜ 1Password を今やらないか

   **拙速だから。** 参照方式にすると設定画面の意味が変わる:
   参照（`op://…`）は秘密ではないのでキット側の設定として持てる。すると画面に
   残るのは `OP_SERVICE_ACCOUNT_TOKEN` と `OPENROUTER_API_KEY` の**2つだけ**になり、
   鍵を10個貼る画面ではなくなる。recruiter の仕事も変わる（参照を書き込む側になる）。
   **他の懸案と同時に動かすと両方が中途半端になる。**

   やるなら**ブランチを切って OP 版を作る**。他が片付いた後。

   ### 調べて分かっていること（着手時に使う）

   - Hermes に既に口がある（`hermes secrets onepassword`）。環境変数を `op://…` に
     対応づけ、プロセス起動時に解決する。`op` はこのマシンに入っている（2.31.1）
   - 認証は**サービスアカウントトークン**（`OP_SERVICE_ACCOUNT_TOKEN`）。
     **Touch ID は要らない**——handler の `mcp.yaml` にある「`op run` は使わない」は
     個人アカウント前提の話で、サービスアカウントなら無人で成立する
   - **モデルの鍵だけは直値で手元に置くこと。** 無いと本当に何も動かない唯一の鍵で、
     それ以外は欠けても該当の MCP が無効になるだけ（`sync_mcp_enabled`）。
     ここを分けておけば「保管庫が落ちたら全滅」は起きない
   - `env apply` は既存値を空で潰さないので、保管庫に届かなくても前回の値で動く
   - AWS Secrets Manager も同じ口に乗せられる（boto3 は Hermes の venv にある）。
     サーバではインスタンスロールで**配る鍵がゼロ**になるが、手間が大きい

   ### 決めたこと: 金庫番の役は作らない

   (1) 秘密を全部持つエージェントは、他人の文章を読む役がいる環境で
   インジェクションの標的として最悪である
   (2) **待ち時間が消えない**——`xoxb-` は人が承認ボタンを押した後にしか存在しない
   (3) recruiter は既にシェルを持つ。**能力を足すのに役は足さない**

## 変えていない前提

- **Hermes 本体は改造しない**（`~/.hermes/hermes-agent/` は読むだけ）
- **配置表は `core/build_distributions.py` の `ROLES` が唯一の正**
- **秘密の正はキット直下の `.env`**。GUI は書き込み専用で、値を画面へ返さない
- **ビルド工程を持たない**（UI を TS 化したくなったときだけ GitHub Releases を足す）
