# SEAOS エージェントキット

Hermes に、**役割を分担して一緒に働くエージェントのチーム**を入れるプラグインです。

Slack（または Hermes Desktop）で窓口のエージェントに頼むと、仕事がカードに分けられ、
実装・調査・外部サービスの更新などをそれぞれの担当が進めて、結果を報告します。

このページを上から順に進めると、セットアップが終わります。
分からないところは、AI アシスタントにこのページを見せながら進めて構いません。

---

## 用意するもの

| | 必須か | 補足 |
|---|---|---|
| macOS か Windows の PC | 必須 | Windows は実機での確認がまだ済んでいません（→ [Windows で使う場合](#windows-で使う場合)） |
| GitHub アカウント | 必須 | このリポジトリは非公開です。**閲覧できる権限をもらっておいてください** |
| OpenRouter の API キー | 必須 | エージェントが使う AI モデルの鍵です。[openrouter.ai/keys](https://openrouter.ai/keys) で作れます |
| Slack のワークスペース | 任意 | Slack から話しかけたいときだけ。Hermes Desktop だけでも使えます |

Docker や Node.js などの道具は、**足りなければエージェントが自分で入れます**（途中で管理者の承認を求められることがあります）。

---

## 1. Hermes を入れる

**[Hermes のダウンロードページ](https://hermes-agent.nousresearch.com/)** から **Hermes Desktop** を入れてください。

コマンドで入れる場合は、次の1行を実行します。

| OS | 実行する場所 | コマンド |
|---|---|---|
| macOS | ターミナル | `curl -fsSL https://hermes-agent.nousresearch.com/install.sh \| bash` |
| Windows | PowerShell | `iex (irm https://hermes-agent.nousresearch.com/install.ps1)` |

入れたら一度 Hermes Desktop を起動し、Hermes 自体が動くことを確かめておいてください。

## 2. このプラグインを入れる

ターミナル（Windows は PowerShell）で次を実行します。

```
hermes plugins install https://github.com/seaosinc/seaos-hermes-agent-kit-plugin --enable
```

GitHub の認証を求められたら、ブラウザでログインして許可してください
（`gh auth login` を済ませておくと聞かれません）。

入れたら **Hermes Desktop を再起動**し、プラグインの一覧で **SEAOS のスイッチを入れます**。
スイッチは**2つ**（Python 側とデスクトップ側）あり、どちらも最初はオフです。両方オンにしてください。

サイドバーに **SEAOS** が出ていれば成功です。

## 3. 接続情報を入れる

サイドバーの **SEAOS** を開きます。

「接続情報」の **OPENROUTER_API_KEY**（赤い `*` の付いた行）の「設定」を押し、
OpenRouter の API キーを貼り付けて保存します。

これが無いと先へ進めません。それ以外の行（GitHub、Notion、Backlog など）は、
使う機能に合わせて後から入れれば大丈夫です。→ [接続情報の一覧と入手方法](docs/connections.md)

## 4. 使うエージェントを選ぶ

「エージェント」の一覧で、**使わないエージェントのチェックを外します**。

| エージェント | 仕事 | 外せるか |
|---|---|---|
| operator | ユーザーとの窓口。依頼を受けて結果を報告する | 外せない |
| fixer | 詰まりを解決し、完了を判定する | 外せない |
| developer | 実装・検証・PR 作成。CI とレビュー指摘の解消まで | ○ |
| senior-developer | 難度の高い実装。セキュリティと品質も見る | ○ |
| handler | 外部サービスの読み書き（GitHub / Backlog ほか） | ○ |
| provisioner | この PC に、チームが使う道具（Docker など）を揃える | ○ |
| recruiter | エージェントそのものを新設・改修する | ○ |
| broker | 外部エージェントとの連携 | ○ |
| avatar | この PC の画面を操作する・スクショを撮る | ○ |

迷ったら、全部チェックしたままで構いません。後からいつでも変えられます。
→ [エージェントの選び方](docs/agents.md)

## 5. 反映する

右上の **「エージェントを反映」** を押します。数十秒かかることがあります。

「反映しました」と出て、選んだエージェントが **「導入済み」** になれば完了です。

## 6. 仕上げのコマンドを実行する

反映すると `seaos-kit` というコマンドが使えるようになります。
ターミナル（Windows は PowerShell）で一度だけ実行してください。

| OS | コマンド |
|---|---|
| macOS | `~/.local/bin/seaos-kit install` |
| Windows | `& "$env:LOCALAPPDATA\Programs\seaos-kit\seaos-kit.cmd" install` |

定期的な見回り、作業部屋、共有の記憶などを用意します。数分かかることがあります。
最後に「✗」が出ていなければ完了です。

> 毎回フルパスで打つのが面倒なら、上の置き場を PATH に足しておくと `seaos-kit` だけで動きます。

## 7. Slack から使う（任意）

Slack から話しかけるには、Slack App を作り、operator の行の「設定」から鍵を入れます。
手順が長いので別のページにまとめました。→ [Slack とつなぐ](docs/slack.md)

App は次のマニフェストから作ります（[api.slack.com/apps](https://api.slack.com/apps) の
**Create New App → From an app manifest** に貼り付け）。名前と説明は自由に変えてください。

<details>
<summary>Slack App のマニフェスト</summary>

```json
{
  "_metadata": {
    "major_version": 1,
    "minor_version": 1
  },
  "display_information": {
    "name": "SEAOS",
    "description": "チームのエージェントへの窓口"
  },
  "features": {
    "app_home": {
      "home_tab_enabled": false,
      "messages_tab_enabled": true,
      "messages_tab_read_only_enabled": false
    },
    "bot_user": {
      "display_name": "SEAOS",
      "always_online": true
    },
    "assistant_view": {
      "assistant_description": "チームのエージェントに頼みごとができます"
    }
  },
  "oauth_config": {
    "scopes": {
      "bot": [
        "app_mentions:read",
        "assistant:write",
        "channels:history",
        "channels:read",
        "groups:history",
        "groups:read",
        "im:history",
        "im:read",
        "im:write",
        "mpim:history",
        "mpim:read",
        "chat:write",
        "files:read",
        "files:write",
        "reactions:read",
        "reactions:write",
        "users:read",
        "users:read.email"
      ]
    }
  },
  "settings": {
    "event_subscriptions": {
      "bot_events": [
        "app_mention",
        "message.channels",
        "message.groups",
        "message.im",
        "message.mpim",
        "assistant_thread_started",
        "assistant_thread_context_changed",
        "reaction_added",
        "reaction_removed"
      ]
    },
    "interactivity": {
      "is_enabled": true
    },
    "org_deploy_enabled": false,
    "socket_mode_enabled": true,
    "token_rotation_enabled": false
  }
}
```

</details>

**要る設定はこの3つです。** 既にある App を使う場合は、足りないものを足して再インストールしてください
（トークンは変わりません）。

| 設定 | 値 | 無いと |
|---|---|---|
| Socket Mode | 有効 | Slack とつながらない |
| Bot Token Scopes | `app_mentions:read` `channels:history` `channels:read` `groups:history` `groups:read` `im:history` `im:read` `mpim:history` `mpim:read` | 話しかけても届かない |
| | `chat:write` | 返事を書けない |
| | `files:read` | 添付したファイルを読めない |
| | `files:write` `im:write` | 画像やファイル、頼んだ作業の結果（スクショなど）が返ってこない |
| | `assistant:write` | 「入力中…」の表示が出ない |
| | `reactions:read` `reactions:write` | リアクションで操作できない |
| | `users:read` `users:read.email` | 相手の名前やメールアドレスからゲストを引けない |
| Event Subscriptions（bot events） | `app_mention` `message.channels` `message.groups` `message.im` `message.mpim` `assistant_thread_started` `assistant_thread_context_changed` `reaction_added` `reaction_removed` | メッセージやリアクションに反応しない |

`seaos-kit doctor` の「Slack App の権限」で、足りない権限を確かめられます。

Slack を使わない場合は、Hermes Desktop で **operator** を選んで話しかけてください。

## 8. 確かめる

```
seaos-kit doctor
```

最後に **「✓ 問題なし」** と出れば、セットアップは完了です。
問題が出たら → [困ったとき](docs/troubleshooting.md)

---

## 使い方

- **頼む：** operator に、やってほしいことをそのまま伝えます。「◯◯ リポジトリの △△ を直して PR を出して」のように、**何が終われば完了か**が伝わると確実です
- **ファイルを渡す：** Slack でファイルを添えて頼めば、担当のエージェントが読めます。Excel・Word・PowerPoint・PDF も読めます
- **エージェントを増やす：** 「◯◯ をする専門のエージェントがほしい」と operator に頼むと、recruiter が作ります（recruiter を有効にしている場合）

## 更新

- **自動：** プラグインの更新は、10分ごとに自動で取り込まれ、エージェントに反映されます
- **すぐ更新したい：** SEAOS 画面の **「プラグインを最新化」** を押してから **「エージェントを反映」** を押します
- 画面に **「この画面は古い状態で動作しています」** と出たら、その横の **「再起動」** を押してください

---

## Windows で使う場合

手順は同じですが、いくつか違いがあります。

| | macOS | Windows |
|---|---|---|
| コマンドを打つ場所 | ターミナル | PowerShell |
| `seaos-kit` の場所 | `~/.local/bin/seaos-kit` | `%LOCALAPPDATA%\Programs\seaos-kit\seaos-kit.cmd` |
| PC の起動時に Slack 窓口を自動で起こす | 自動では起きません。落ちたら `seaos-kit gateway restart operator` | タスク スケジューラに登録します（下記） |
| 道具を入れるときの承認 | Mac のログインパスワード | 「このアプリがデバイスに変更を加えることを許可しますか？」で「はい」 |

Windows でログオン時に Slack の窓口を自動で起こすには、PowerShell で一度だけ実行します。

```
schtasks /Create /SC ONLOGON /TN "hermes-gateway" /TR "hermes --profile operator gateway run"
```

**Windows は実機での確認がまだ済んでいません。** とくに、コードを書くエージェント（developer / senior-developer）の
作業部屋は、Windows では動かない可能性があります。うまくいかない場合は、そのエージェントを外して使ってください。

---

## もっと詳しく

| | |
|---|---|
| [接続情報](docs/connections.md) | 各キーの意味と入手方法、エージェントごとに別のキーを使う方法 |
| [エージェント](docs/agents.md) | 各エージェントの仕事、選び方、外し方・消し方 |
| [Slack とつなぐ](docs/slack.md) | Slack App の作り方、ファイルの渡し方 |
| [コマンド](docs/commands.md) | `seaos-kit` でできること |
| [困ったとき](docs/troubleshooting.md) | よくある症状と直し方、アンインストール |
