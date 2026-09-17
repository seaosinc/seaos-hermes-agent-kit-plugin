# 困ったとき

まず **`seaos-kit doctor`** を実行してください。✗ の行に、何が起きていてどう直すかが出ます。
（`seaos-kit` の場所は → [コマンド](commands.md#打つ場所)）

[← README に戻る](../README.md)

---

## セットアップ中

ここのコマンドは、macOS はターミナル、Windows は PowerShell で実行します。
**Windows は「管理者として実行」ではない、普通の PowerShell** を使ってください
（管理者の PowerShell には、ユーザーの環境変数 `HERMES_HOME` が渡らないことがあります）。

### 「画面のバックエンドに接続できません（…）」と出る

SEAOS の画面（見た目）は読み込めたが、中身を返す Hermes 側に繋がらない、という表示です。
括弧の中に理由が出ます。**「エラーをコピー」** ボタンで全文をコピーできます。

上から順に確かめてください。

1. **Hermes Desktop を完全に終了して起動し直し、画面左下のゲートウェイも「再起動」したか。**
   プラグインは起動時に読み込まれます。入れた直後や、有効にした直後は、再起動するまでこの表示になります（いちばん多い原因です）
2. **プラグイン本体が入っているか**
   ```
   hermes plugins list
   ```
   `seaos-hermes-agent-kit-plugin` が無ければ、本体が入っていません。
   画面の見た目だけが残っている状態なので、コマンドで入れ直します。
   ```
   hermes plugins install https://github.com/seaosinc/seaos-hermes-agent-kit-plugin --enable
   ```
   セキュリティ検査の確認を聞かれたら許可し、Hermes Desktop を再起動してください
3. **有効になっているか**
   ```
   hermes config get plugins.enabled
   ```
   一覧に `seaos-hermes-agent-kit-plugin` が無ければ、有効にして再起動します。
   ```
   hermes plugins enable seaos-hermes-agent-kit-plugin
   ```
4. **いま使うプロファイルが `default` か**
   ```
   hermes profile use default
   ```
   `default` 以外を選んだ状態でプラグインを入れると、本体がそのプロファイルに入り、画面だけが出てこの表示になります。
   `default` に戻してから 2. をやり直してください

括弧の中が次のときの意味：

| 括弧の中 | 意味 | 対処 |
|---|---|---|
| `Plugin not found` | Hermes が、SEAOS を有効になっていないとみなしている | 上の 2〜4 |
| `Headless backend … web UI disabled` | 有効だが、起動時に読み込まれていない | Hermes Desktop を再起動（上の 1） |

### サイドバーに SEAOS が出ない

- Hermes Desktop を完全に終了して、起動し直してください
- それでも出なければ、`hermes plugins list` で `seaos-hermes-agent-kit-plugin` が入っているか確かめ、
  無ければ上の「プラグイン本体が入っているか」の手順で入れてください

### Hermes Desktop の画面から入れたのに、プラグイン本体が入らない

画面から入れたときに、エージェント側の導入が失敗すると、デスクトップ側（見た目）だけが入ります。
導入の結果に出たエラーを確かめ、コマンドで入れ直してください（上の「プラグイン本体が入っているか」）。

古い版のキットは、導入時のセキュリティ検査で「確認が必要（CAUTION）」になり、
画面からは確認を答えられないため、必ずこの状態になっていました。今の版は検査を通るので起きません。

### SEAOS が2つ出る／古い名前のプラグインが残っている

以前の名前 `seaos-hermes-agent-kit`（`-plugin` が付かない）で入っていたものが残っています。
古いほうだけを外してください。

```
hermes plugins remove seaos-hermes-agent-kit
```

`-plugin` の付いたほうは消さないでください。外したあと、Hermes Desktop を再起動します。

### 「接続情報」に OPENROUTER_API_KEY しか出ない

「接続情報」には、**有効にしているエージェントが使う鍵だけ**が出ます。
GitHub（`GH_TOKEN`）は developer / senior-developer / handler、Notion・Backlog は handler、AWS は developer / senior-developer が使います。
これらのエージェントを「エージェント」の一覧で有効にすると、対応する鍵が出てきます。

何も選んでいない初期状態では、全エージェントが有効です。入れ直したのに外れた状態になっている場合は、
前回の選択（`<Hermes のホーム>/seaos-kit/roles.json`）が残っています。

Slack の鍵は「接続情報」ではなく、**エージェント一覧の operator の行の「設定」** にあります。

### 「エージェントを反映」が押せない

`OPENROUTER_API_KEY` が入っていません。「接続情報」の赤い `*` の行を設定してください。

### 「この画面は古い状態で動作しています」と出る

プラグインが更新されたのに、画面が古いまま動いています。横の **「再起動」** を押してください。

### `seaos-kit` が見つからないと言われる

- 先に SEAOS 画面で **「エージェントを反映」** を一度押してください。そのときにコマンドが置かれます
- PATH に入っていないだけなら、フルパスで実行してください（→ [コマンド](commands.md#打つ場所)）

### プラグインのインストールで GitHub の認証に失敗する

このリポジトリは非公開です。閲覧権限のある GitHub アカウントでログインしてください（`gh auth login`）。

---

## 入れ直す（まっさらからやり直す）

途中で壊れて入れ直すときは、**残骸を残さない**ことが大事です。残っていると、入れ直しても古い状態が使われます。

1. Hermes Desktop を終了する
2. プラグインを外す
   ```
   hermes plugins remove seaos-hermes-agent-kit-plugin
   ```
3. `<Hermes のホーム>/desktop-plugins/` の中の、`seaos` で始まるフォルダを**全部**消す
   （画面の見た目のコピーです。プラグインを外しても自動では消えず、本体が無いのに画面だけ出る原因になります）
4. 役の選択や鍵も初期化したい場合だけ、`<Hermes のホーム>/seaos-kit/` を消す（入れた鍵も消えます）
5. README の手順 2 から入れ直す

`<Hermes のホーム>` は、macOS は `~/.hermes`、Windows は環境変数 `HERMES_HOME` の場所（未設定なら `%LOCALAPPDATA%\hermes`）です。
`hermes config path` で表示される `config.yaml` のあるフォルダです。

エージェントまで消す手順は → [エージェント](agents.md)

---

## 使っているとき

### Slack で返事が来ない

1. `SLACK_ALLOWED_USERS` に、話しかけた人のメンバー ID（`U` で始まる）が入っているか。
   `SLACK_OWNER_ID` の人は、入れなくても自動で話せます
2. App をそのチャンネルに招待したか、`@App名` でメンションしたか
3. `seaos-kit gateway status` で pid が出ているか。出ていなければ `seaos-kit gateway restart operator`
4. 鍵や許可を変えたあと、`seaos-kit gateway restart operator` で窓口を再起動したか（窓口は起動時に読み込みます）

Hermes のログ（`<Hermes のホーム>/logs/agent.log`）に `Early reject of unauthorized user U…` と出ていれば、
その人が 1. の一覧に入っていないため、入口で弾かれています。期限付きで話させたいだけなら、
一覧に足さずにゲストの許可（`seaos-kit guest add`）を使えます。

→ [Slack とつなぐ](slack.md)

### Slack App を作ったのに、ボットのトークンが見つからない

**OAuth & Permissions** の **「Bot User OAuth Token」**（`xoxb-` で始まる）がボットのトークンです。
名前に「User」と入っていますが、ユーザーのトークンではありません。`SLACK_BOT_TOKEN` にはこれを入れます。
ユーザーのトークン（`xoxp-`）は使いません。

App トークン（`xapp-`）は、マニフェストでは作れません。**Settings → Basic Information → App-Level Tokens** で、
スコープ `connections:write` を付けて作ってください（→ [Slack とつなぐ](slack.md)）。

### 画像やファイル、頼んだ作業の結果（スクショなど）が Slack に返ってこない

Slack App の権限が足りません。`seaos-kit doctor` の「Slack App の権限」に ✗ が出ます。

- 返事に付けたファイルが返らない → `files:write`
- 作業が終わったあと、成果物が DM に返らない → `im:write`

**OAuth & Permissions → Bot Token Scopes** に足して、App を再インストールしてください（トークンは変わりません）。

### 「入力中…」の表示が出ない

Hermes 本体の不具合です（新しい Slack の API に、受け付けない値を送っています）。返事そのものは届きます。
Hermes の更新で直るのを待ってください。

### エージェントが返事をしない／カードが進まない（OpenRouter）

Hermes のログに `marking openrouter unhealthy … (payment / credit error)` と出ていれば、
OpenRouter のクレジットが足りないか、支払いに失敗しています。OpenRouter の管理画面で残高を確認してください。

### doctor に「Slack の窓口が奪われていないか」の ✗ が出る

operator と同じ Slack の鍵が、Hermes 本体の設定（`~/.hermes/.env`）にも入っています。
Hermes Desktop を起動したときに Hermes 本体が Slack に繋がり、operator が止まってしまいます。
（このキットを入れる前に、Hermes 自体を Slack に繋いでいた場合に起きます）

1. `~/.hermes/.env` をテキストエディタで開き、`SLACK_` で始まる行を削除する（念のため、先にファイルをコピーしておく）
2. ターミナルで `hermes gateway stop` を実行する
3. `seaos-kit gateway restart operator` を実行する
4. `seaos-kit doctor` で ✗ が消えたことを確かめる

### 実装を頼むと失敗する

コードを書くエージェントは Docker を使います。

1. `seaos-kit machine check` で Docker が「✓」か確認する
2. 「未導入」「停止中」なら、SEAOS 画面の「ツール」に出ているコマンドで入れる（起動する）。管理者の承認を求められたら応じてください
3. 入れ終わったら `seaos-kit install` を実行して、作業部屋を用意してください
4. 実装で GitHub を触るので、`GH_TOKEN` も入っているか確認してください

### Notion や Backlog を読めないと言われる

- 該当の鍵（`NOTION_TOKEN` / `BACKLOG_DOMAIN` + `BACKLOG_API_KEY`）が入っているか
- Notion は、読ませたいページにインテグレーションを **接続** したか（→ [接続情報](connections.md)）
- `seaos-kit machine check` で Node.js が「✓」か

### Excel の数式のセルが空（NaN）と言われる

そのファイルに計算結果が保存されていません。Excel で開いて保存し直してから渡してください。

### 設定を変えたのに、エージェントの動きが変わらない

`seaos-kit update --force-config` を実行してください。エージェントの設定ファイルまで入れ直します。

### 外したはずのエージェントに仕事が振られていた

外す前に作られたカードが残っていた場合に起きます。そのカードは自動で「入力待ち」に移され、
operator が振り直しを知らせます。そのまま任せて大丈夫です。

---

## Windows

- **コードを書くエージェント（developer / senior-developer）の作業部屋は、Windows では動かない可能性があります。**
  うまくいかない場合は、この2つを外して使ってください
- ログオン時に Slack の窓口を自動で起こすには、README の [Windows で使う場合](../README.md#windows-で使う場合) の `schtasks` を実行してください
- 道具のインストール中に「このアプリがデバイスに変更を加えることを許可しますか？」が出たら「はい」を押してください。
  出ないまま止まっている場合は、タスクバーに隠れていないか確認してください
- コマンドは、**「管理者として実行」ではない普通の PowerShell** で実行してください。
  管理者の PowerShell では、ユーザーの環境変数 `HERMES_HOME` が見えず、別の場所の設定を読み書きしてしまうことがあります。
  `hermes config path` で、使っている `config.yaml` の場所を確かめられます

### プロファイルやフォルダが「使用中」で消せない

Hermes Desktop を閉じても、裏で Hermes の Python が動き続けていることがあります（Slack の窓口など）。
Windows は、開かれたままのファイル（`gateway.lock` などの `.lock`）を消せません。
Hermes のプロセスを止めてから消してください。

```
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "hermes" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

それでも消せなければ、PC を再起動してから消してください（ログオン時に窓口を起こす `schtasks` を登録している場合は、先に外してください）。

### プロファイルのフォルダを手で消したら、Hermes が起動しない

消したプロファイルが「いま使うプロファイル」として登録されたままです。`default` に戻してください。

```
hermes profile use default
```

このコマンドも動かなければ、`<Hermes のホーム>\active_profile` というファイルを削除してください。
プロファイルは、フォルダを手で消すのではなく `hermes profile delete <名前>` で消すと、この登録も自動で戻ります。

---

## それでも直らないとき

`seaos-kit doctor` の出力をそのままコピーして、管理者か AI アシスタントに見せてください。
