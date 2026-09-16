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
2. **AWS を developer / senior-developer に触らせる。** Terraform を扱い始めると要る。
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

3. **Slack App の作成を recruiter に持たせる。** 調べた結果、**人の操作は2回で済む。**

   - `apps.manifest.create` でアプリを作成。スコープ・イベント購読・Socket Mode の
     有効化までマニフェストに書ける。応答に `app_id`、資格情報、そして
     **`oauth_authorize_url`** が入る
   - **人が押すのは2箇所だけ**: その URL を開いてワークスペースへ入れる（`xoxb-` が出る）、
     管理画面で App レベルトークンを発行する（`xapp-`。**API では作れない**）
   - 設定トークンは **12時間で失効**する。`tooling.tokens.rotate` で回せるので、
     recruiter に持たせるなら更新の仕組みが要る。最初の1つは管理画面から取る

   ComputerUse で押しに行くより、この2回を人に任せるほうが確実である。

4. **秘密は当面「設定画面に入れる」ままにする。**（1Password 版は保留）

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

## 役の置き場は2つある

| | 場所 | 誰のもの | 更新で |
|---|---|---|---|
| **配られてくる役** | `templates/workers/`（キットの中） | リポジトリ | 上書きされる |
| **この環境で作った役** | `~/.hermes/seaos-kit/workers/` | この機械 | 触られない |

`worker new` は**必ず後者に作る。** キットの中に作ると配布のたびに危うい——
`hermes plugins update` は untracked も stash して戻すので、同じパスに配布物が
来れば衝突して stash に取り残される。`plugins install --force` ならフォルダごと
置き換わって消える。

生成器は両方を見る。**同じ名前ならローカルを採る**——配布物で黙って上書きすると、
この環境で育てた役が理由も分からず別物に入れ替わる。`worker list` の ORIGIN 欄で
どちらか分かる。

**この環境の役は git に入らない。** 機械が飛べば消える。共有したい役は、
リポジトリの `templates/workers/` へ手で移してコミットすること
（**recruiter にコミットさせない**——`plugins update` は `--ff-only` なので、
ローカルのコミットがあると更新そのものが止まる）。

## 入れる役は選べる

設定画面の役の行のチェック（CLI は `seaos-kit disable <役>` / `enable <役>`）。
記録は `~/.hermes/seaos-kit/roles.json` に**外した役だけ**を持つ。

- **何もしなければ全役が入る。** 選んだ役を記録する形にすると、recruiter が作った役や
  後から配られた役が黙って入らなくなる
- **operator と fixer は外せない**（配置表の `essential`）。定期実行と共有記憶は
  operator に、分解したカードの完了判定は fixer に載っている
- 外した役は**反映・鍵の配布・検証から外れる**。プロファイルが既にあれば、消すか残すかを
  その場で選ぶ。**残すと Hermes の分解器は担当の候補に並べ続ける**ので、説明文を
  「選ぶな」に書き換え、窓口なら常駐も止める
- 外した役の鍵は `.env` に残す（入れ直したときに入れ直さなくて済む）
- **外した役の名前を、規約から落とす。** Hermes は担当の実在を確かめないので、
  「詰まったら senior-developer へ」と書いたまま外すと、振られたカードは ready のまま
  誰にも起動されず、親は永久に待つ。規約とスキルの `<!-- if-role: 役 -->…<!-- else -->…
  <!-- end-if-role -->` を、反映のたびに有効な役に合わせて開く（`strip_role_blocks`）
- **それでも残った名前は `assignee-guard` が拾う**（毎分）。存在しない・無効にした役に
  振られた ready のカードを入力待ちへ移し、理由を書く。既存の環境では
  `seaos-kit install` で登録する（冪等）

## モデルの鍵は役ごとに差し替えられる

役の行の「設定」→「共通の接続情報を、この役だけ別の値にできます」。
`.env` には `DEVELOPER__OPENROUTER_API_KEY` のような役つきの名前で入る。

| | 役つきに値がある | 役つきが空 |
|---|---|---|
| **上書きできる鍵**（`OPENROUTER_API_KEY`） | 役つきを使う | **共通を使う** |
| **専用の鍵**（窓口の Slack） | 役つきを使う | **何も配らない** |

落ち方が逆なのは意図どおり。Slack は共通へ落ちると二重返事の事故になり、
モデルの鍵は落ちないと何も動かない。どれを上書きできるかは `roles.OVERRIDABLE_ENV`。
全ての有効な役が自分の値を持っていれば、共通のモデルの鍵は必須でなくなる。

## Slack で受け取ったファイルを、担当が読める

**Hermes 本体だけでは、受けた窓口にしか見えない。** ゲートウェイはファイルを
`profiles/<窓口>/cache/` に落とし（テキストは 100KB まで本文へ展開、画像は vision で説明）、
窓口にはパスを注記で渡す。ここから先が届いていなかった:

- 作業部屋（箱）からはそのパスが見えない。キャッシュは一日ほどで消える
- Hermes の添付（`kanban attach`）は、分解器が作る子カードへ引き継がれない

そこで、窓口が `seaos-kit files keep <パス>` で `~/.hermes/kanban/files/` へ写し、
出たパスを本文の「添付ファイル:」に書く。**パスは文字列なので、分解されても本文と
一緒に子カードへ運ばれる。** 置き場と板の添付は、箱へ**読み取り専用・左右同じパス**で
渡してある。

- `files keep` は Hermes の cache の外を断る（窓口は他人の文章を読む。秘密を箱の見える
  場所へ出させないため）
- 置き場は日次の保守でカードと同じ日数（`PURGE_DAYS`、既定 90）で畳む
- **Excel / Word / PowerPoint / PDF は隣に `.md` を置く**（markitdown を Hermes が持っている uv で借りる。
  Hermes の venv には入れない）。uv が無ければ元のファイルだけ渡る
- **シェルを持たない役（handler）は、読み取り専用の `files` MCP で読む**
  （`templates/shared/mcp/files.yaml`）。見えるのは置き場と板の添付だけで、書く道具は載せない
- 箱のマウントは config.yaml にあるので、**既存の環境では `update --force-config` が要る**

## この PC の道具は provisioner が揃える

Hermes もキットも持ってこない道具がある。無くても導入は通り、**使う最初のカードで落ちる。**

| 道具 | 要る役 | 自動で揃えるか |
|---|---|---|
| Docker | 箱を持つ役（developer / senior-developer）、共有記憶（operator） | する（入れる → 起こす → 作業部屋を建てる） |
| Node.js | `npx` で起動する MCP を持つ役（handler） | する |
| uv | 変換（files） | 要らない。Hermes が `~/.hermes/bin/uv` を持っている |

- **台帳は `core/machine.py` の `CATALOG`。** `seaos-kit machine install` は台帳に無い名前を断る。
  provisioner は Slack 由来のカードで動くので、任意のパッケージを入れる口にしない
- **人が意識しなくても動く。** `seaos-kit install` の最後と、operator の定期実行
  `machine-guard`（毎時）が、足りない道具ごとに provisioner へカードを立てる。
  開いているカードがあれば立てず、閉じたあとも足りなければ週が変わってから立て直す
- **管理者の承認だけは人が押す**（macOS のパスワード、Windows の UAC、Docker の利用規約）。
  `install` が終了コード 3 を返したら、provisioner は needs_input で止まり、何をどこで押すかを書く
- 設定画面の「この PC」に状態が出る。provisioner を外しているときだけ、入れるコマンドを見せる
- 既存の環境では `seaos-kit install`（冪等）で machine-guard が登録され、その場で確認が走る

## 変えていない前提

- **Hermes 本体は改造しない**（`~/.hermes/hermes-agent/` は読むだけ）
- **配置表は `core/build_distributions.py` の `ROLES` が唯一の正**
- **秘密の正はキット直下の `.env`**。GUI は書き込み専用で、値を画面へ返さない
- **ビルド工程を持たない**（UI を TS 化したくなったときだけ GitHub Releases を足す）
