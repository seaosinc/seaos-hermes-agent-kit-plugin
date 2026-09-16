# 困ったとき

まず **`seaos-kit doctor`** を実行してください。✗ の行に、何が起きていてどう直すかが出ます。
（`seaos-kit` の場所は → [コマンド](commands.md#打つ場所)）

[← README に戻る](../README.md)

---

## セットアップ中

### サイドバーに SEAOS が出ない

- Hermes Desktop のプラグイン一覧で、SEAOS の **スイッチが2つとも** オンになっているか確認してください
- オンにしたあと、Hermes Desktop を再起動してください

### 「バックエンドに接続できません」と出る

プラグインの **Python 側のスイッチ** がオフです。オンにして Hermes Desktop を再起動してください。

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

## 使っているとき

### Slack で返事が来ない

1. `SLACK_ALLOWED_USERS` に、話しかけた人のメンバー ID が入っているか
2. App をそのチャンネルに招待したか、`@App名` でメンションしたか
3. `seaos-kit gateway status` で pid が出ているか。出ていなければ `seaos-kit gateway restart operator`

→ [Slack とつなぐ](slack.md)

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
2. 「足りない」「止まっている」なら、provisioner が自動で直しに行きます。管理者の承認を求められたら応じてください
3. provisioner を外している場合は、`seaos-kit machine install docker` → `seaos-kit machine start docker` → `seaos-kit install` の順に実行してください
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

---

## それでも直らないとき

`seaos-kit doctor` の出力をそのままコピーして、管理者か AI アシスタントに見せてください。
