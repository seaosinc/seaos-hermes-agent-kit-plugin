# Slack とつなぐ

operator を Slack の窓口にします。所要時間は 15 分ほどです。
Slack の管理画面で App を作れる権限が必要です（無ければワークスペースの管理者に頼んでください）。

[← README に戻る](../README.md)

---

## 1. App の設定（マニフェスト）を作る

ターミナル（Windows は PowerShell）で実行します。名前と説明は自由に変えてください。

```
hermes slack manifest --name "SEAOS" --description "チームのエージェントへの窓口"
```

`{` から始まる長い文字列（マニフェスト）が表示されるので、全部コピーしておきます。

## 2. Slack App を作る

1. [api.slack.com/apps](https://api.slack.com/apps) を開き、**Create New App** → **From an app manifest** を選ぶ
2. ワークスペースを選び、手順 1 でコピーしたマニフェストを貼り付けて作成する
3. **Install App**（または **OAuth & Permissions**）でワークスペースにインストールする
4. 表示された **Bot User OAuth Token**（`xoxb-…`）をコピーしておく
5. **Basic Information → App-Level Tokens** で **Generate Token and Scopes** を押し、
   スコープに **`connections:write`** を付けて作成する。表示された `xapp-…` をコピーしておく

`xapp-…` は画面からしか作れません。忘れずに作ってください。

## 3. operator に鍵を入れる

SEAOS 画面の **operator の行の「設定」** を押し、次の値を入れます。

| 項目 | 入れるもの | 必須か |
|---|---|---|
| `SLACK_BOT_TOKEN` | 手順 2-4 の `xoxb-…` | 必須 |
| `SLACK_APP_TOKEN` | 手順 2-5 の `xapp-…` | 必須 |
| `SLACK_ALLOWED_USERS` | 話しかけてよい人の **メンバー ID**（複数ならカンマ区切り） | 必須。**空だと誰も話しかけられません** |
| `SLACK_OWNER_ID` | 判断を仰ぐ相手（ふつうは自分）のメンバー ID | 任意 |
| `SLACK_HOME_CHANNEL` | 既定の投稿先のチャンネル ID | 任意 |

**メンバー ID の調べ方：** Slack でその人のプロフィールを開き、「︙」→ **メンバー ID をコピー**（`U` で始まる文字列）。
**チャンネル ID の調べ方：** チャンネル名を押して開く詳細の一番下（`C` で始まる文字列）。

入れたら **「エージェントを反映」** を押します。

## 4. operator を起こす

```
seaos-kit gateway restart operator
```

`seaos-kit` の場所は OS によって違います（→ [README の Windows の節](../README.md#windows-で使う場合)）。

Windows でログオン時に自動で起こしたい場合も、README の Windows の節を見てください。
macOS では自動では起きないので、PC を再起動したらこのコマンドをもう一度実行します。

## 5. 話しかける

1. 使いたいチャンネルに App を招待する（チャンネルで `/invite @SEAOS`）
2. **`@SEAOS` とメンションして**話しかける。チャンネルでは、メンションしないと返事をしません
3. 返事はスレッドに返ってきます

DM ならメンションは要りません。

---

## ファイルを渡す

頼みごとと一緒にファイルを添付すると、担当のエージェントが読めます。

- テキスト、画像、PDF、Excel、Word、PowerPoint を読めます
- Excel・Word・PowerPoint・PDF は、エージェントが読みやすい形に自動で変換されます
- 1ファイル 20MB までです
- **Excel の数式のセル**は、Excel で保存したファイルなら計算結果が読めます。システムが出力した Excel などで
  値が読めない場合は、一度 Excel で開いて保存し直してから渡してください
- 受け取ったファイルは、しばらく（既定 90 日）経つと自動で片付けられます

---

## うまくいかないとき

| 症状 | 確認すること |
|---|---|
| 返事が来ない | `SLACK_ALLOWED_USERS` に自分のメンバー ID が入っているか。App をチャンネルに招待したか。メンションしたか |
| まったく反応しない | `seaos-kit gateway status` で pid が出ているか。出ていなければ `seaos-kit gateway restart operator` |
| operator 以外が返事をしているようだ | `seaos-kit doctor` を実行。「Slack の窓口が奪われていないか」に ✗ が出ていたら、案内どおりに直す（→ [困ったとき](troubleshooting.md)） |
| 添付したファイルを読めないと言われる | Slack App に `files:read` の権限があるか（手順 1 のマニフェストで作れば入っています） |
| 画像やファイルが返ってこない（「送れなかった」と言われる） | Slack App に `files:write` の権限があるか。`seaos-kit doctor` の「Slack App の権限」に ✗ が出ます。**OAuth & Permissions → Bot Token Scopes** に足して App を再インストールする（トークンは変わりません） |
