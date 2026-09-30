# 影武者（本人の代わりに受ける）

あなたが席を外しているあいだ、**あなたの Slack アカウントのまま**エージェントが代わりに受け付けます。
operator は「ボット」として窓口に立ちますが、影武者は「あなた本人」として立ちます。

[← README に戻る](../README.md)

> **まだ試験段階です。** 実機での確認が済んでいない点があります（→ [まだ確かめていないこと](#まだ確かめていないこと)）。
> まず自分だけで試し、様子を見てから広げてください。

---

## どう動くか

- Slack のステータスの**絵文字を 🤖（`:robot_face:`）** にしているあいだだけ、影武者が動きます。
  見るのは絵文字だけで、文言は何でも構いません（「会議中」「今日は休み」など）。
  ステータスを外すか、絵文字を 🤖 以外にすれば、すぐに止まります
- あなた宛の **DM** と、チャンネル・グループ DM・スレッドでの **`@あなた` のメンション**に、あなたのアカウントで返事をします。
  あなた宛かどうか分からない発言には反応しません
- 返事の先頭には、必ず **「🤖 代理応答」** が付きます。相手は、あなた本人の返事と取り違えません
- 頼まれた作業は、operator と同じようにカードになり、各エージェントが進めて、終わったらあなたの名前で報告します
- 予定の約束・承諾や断り・評価・お金や契約など、**あなたにしか決められないことは預かります**。
  相手には「本人に確認して返します」と答え、カードを止めておきます。戻ったらボードで確かめてください

### 誰の話に応じるか

**operator と同じ人たちです。** operator に話しかけてよい人（`SLACK_ALLOWED_USERS` とオーナー）と、
アクセス許可（`seaos-kit guest`）を出したゲストに応じます。

- 許可の無い人には、**何も返しません。** 案内も返しません（あなたの名前で「いまは話せません」と届いてしまうため）
- **あなた自身の発言には反応しません。** 影武者に指示したいことは、これまでどおり operator に頼んでください
- 絵文字（👀 ✅ など）には反応しません。あなた宛に付けられたものとして、そのままにします

---

## 使い始める

所要時間は 15 分ほどです。operator を Slack につないでいること（→ [Slack とつなぐ](slack.md)）が前提です。

### 1. 影武者を有効にする

SEAOS 画面の「エージェント」で **shadow** にチェックを入れ、**「エージェントを反映」** を押します。
影武者は、チェックを入れた人にだけ入ります（ほかのエージェントと違い、既定では入りません）。

### 2. 影武者用の Slack App を作る

**operator の App とは別に作ります。** 同じ App を使うと、Slack が話をどちらか片方にしか届けず、
返事が来たり来なかったりします。

1. [api.slack.com/apps](https://api.slack.com/apps) で **Create New App** → **From an app manifest** を選ぶ
2. ワークスペースを選び、下のマニフェストを貼り付けて作成する
3. **Install App** でインストールする。**「あなたとして」操作する許可**を求められるので、許可する
4. 表示された **User OAuth Token**（`xoxp-…`）をコピーしておく。**Bot User OAuth Token ではありません**
5. **Settings → Basic Information → App-Level Tokens** で **Generate Token and Scopes** を押し、
   `connections:write` を付けて作る。表示された `xapp-…` をコピーしておく

```yaml
display_information:
  name: 影武者
  description: 本人の不在中、本人の Slack アカウントで代わりに受ける
features:
  bot_user:
    display_name: shadow
    always_online: false
oauth_config:
  scopes:
    user:
      - chat:write
      - im:history
      - mpim:history
      - channels:history
      - groups:history
      - files:read
      - files:write
      - users:read
      - users.profile:read
      - users.profile:write
    bot:
      - chat:write
settings:
  event_subscriptions:
    user_events:
      - message.im
      - message.mpim
      - message.channels
      - message.groups
      - user_status_changed
  interactivity:
    is_enabled: true
  org_deploy_enabled: false
  socket_mode_enabled: true
  token_rotation_enabled: false
```

> ワークスペースで App の承認制が有効なら、インストールに管理者の承認が要ります。
> `token_rotation_enabled` は **false のまま**にしてください。true にすると 12 時間でトークンが切れ、一度入れると戻せません。

### 3. 影武者に鍵を入れる

SEAOS 画面の **shadow の行の「設定」** を押し、次の値を入れて **「エージェントを反映」** を押します。

| 項目 | 入れるもの |
|---|---|
| `SLACK_BOT_TOKEN` | 手順 2-4 の `xoxp-…`（名前は Bot ですが、入れるのはあなたのユーザートークンです） |
| `SLACK_APP_TOKEN` | 手順 2-5 の `xapp-…` |
| `SLACK_SELF_ID` | あなたの **メンバー ID**（`U` で始まる。Slack のプロフィールの「︙」→ メンバー ID をコピー） |

話しかけてよい人は operator の設定がそのまま使われるので、ここでは入れません。

### 4. 起こして、確かめる

```
seaos-kit gateway restart shadow
seaos-kit doctor
```

doctor の「影武者」の節に「✓ shadow: 本人（U…）のトークンで、本人は許可から外れている」と出れば準備完了です。

---

## ふだんの使い方

**席を外すときに、Slack のステータスを 🤖 にするだけです。** 絵文字は `:robot_face:`（🤖）、文言は何でも構いません。
スマホから付けても外しても効きます。

コマンドでも切り替えられます。

| コマンド | すること |
|---|---|
| `seaos-kit shadow on` | ステータスを 🤖「Bot 対応中」にして、代わりに受け始めます（文言はこの既定が入るだけで、動くかどうかには関係しません） |
| `seaos-kit shadow on --minutes 60` | 60 分たったら自動で止まります |
| `seaos-kit shadow off` | 影武者のステータスを外して、止めます（あなたが手で付けた別のステータスには触りません） |
| `seaos-kit shadow status` | いま代わりに受けているかを出します |

止めたいのに止まらない、と感じたら、まずステータスが 🤖 のままになっていないかを見てください。

### やめるとき

SEAOS 画面の「エージェント」で shadow のチェックを外します。Slack App も要らなければ、
[api.slack.com/apps](https://api.slack.com/apps) から削除してください（あなたのトークンも無効になります）。

---

## 気をつけること

- **影武者は、あなたの権限すべてで動きます。** あなたが見えるチャンネルの発言は、影武者にも見えます。
  誤った返事も、あなたの名前で残ります（先頭の「🤖 代理応答」で見分けは付きます）
- 受けた会話は、operator と同じように Hermes のセッションと共有の記憶（mem0）に残ります。
  Slack の規約は、API で得た会話を AI の**学習**に使うことを禁止しています。返事を作るために使うのは禁止されていません
- あなたのアカウントが無効になると、影武者も止まります
- Hermes Desktop にも「Bot Mode」という別の機能があります（Desktop が管理するエージェントどうしのやり取り）。
  影武者とは関係ありません

---

## 仕組み（作る人向け）

### 決めたこと

| | 決めたこと |
|---|---|
| 作り | operator を元にした**別の役**（`shadow`）。Hermes 標準の `slack` の受け口に、本人のユーザートークン（`xoxp`）を入れる |
| 受ける範囲 | 本人宛と明示された話だけ（1 対 1 の DM と `@本人` のメンション）。`require_mention` / `thread_require_mention` は operator と同じ |
| 誰の話に応じるか | operator と共有。`SLACK_ALLOWED_USERS` は operator のもの（オーナーを含む）から本人を除いて配る（`roles.derived_env`）。ゲストの承認は、booking-gate を載せた窓口すべてに置く（`booking_sync.gate_profiles`） |
| 許可の無い人 | 黙る。`unauthorized_dm_behavior: ignore` と、booking-gate の `notice_profiles`（既定は operator だけ） |
| 本人の発言 | 常に捨てる。**許可から外して認可の段で落とす**うえに、shadow プラグインでも落とす |
| ON / OFF | 本人の Slack ステータスの**絵文字**（`:robot_face:`）が正。文言は見ない。`user_status_changed` と 5 分ごとの読み直しで追う。読めないうちは OFF |
| 代理の印 | shadow の口の `send` / `edit_message` に挟んで付ける。最終の返事だけでなく、Hermes の定型の知らせにも付く |
| 定型の知らせ | 途中経過・警告・記憶の通知などは切る（`config_extra`）。本人が言ったように見えるため |
| 入れ方 | `opt_in`。何もしなければ入らない（`selection.json` の `enabled`） |

### operator の中に受け口を足さなかった理由

- Hermes 本体に `Platform.SLACK` で分岐している箇所がおよそ 25 ある（スレッドのセッション化、返信先、
  セッション復旧、通知の除外など）。別名の受け口にすると、これらが全部効かなくなる
- Slack アダプタは設定を `SLACK_*` の鍵から、プロファイル単位で読む。1 つのプロファイルに受け口を 2 つ置くと、同じ値を読み合う
- 避けるには `connect()` などの大きなメソッドを丸ごと上書きすることになり、Hermes を更新するたびに壊れやすい

別の役にすれば、Hermes から見ると「ボットを個人アカウントで動かしている」だけで、標準の Slack 処理がそのまま効く。
その代わり、**会話のセッションと記憶は operator とは別**になる（カードのボードは共有）。

### 混線しないか

Hermes v2026.9.24 のコードを読んで確かめた（2026-09-30）。

**gateway は 1 つのプロセスしかない。** Hermes は 1 台に gateway を 1 つだけ立て、全役をその中で受け持つ（multiplex）。
shadow も、operator と同じプロセスの中に 2 つ目の Slack アダプタとして入る。
鍵・設定・カードの通知と起床・セッション・プラグインは役ごとに分かれていて、Hermes の中で operator と shadow が混ざることは基本的に無い。
漏れうるのは次のところで、それぞれ塞いである。

| # | どこ | 起きうること | 塞ぎ方 |
|---|---|---|---|
| 1 | App トークン | 同じ `xapp` を 2 つの窓口に入れても、同じプロセスの中なのでロックがぶつからず、イベントが片方にしか届かない | doctor が App トークンの重複を検査する |
| 2 | カード完了の通知 | gateway が `HERMES_PROFILE=operator` を持って起動していると、shadow の通知が operator 名義になる | request-intake で `--notifier-profile` を明示する。キットはゲートウェイに `HERMES_PROFILE` を持たせない |
| 3 | 本人の発言 | `pre_gateway_dispatch` は応答中の割り込みでは呼ばれないので、フックだけでは漏れる | 本人を shadow の許可から外し、認可の段で落とす |
| 4 | Slack 上で反応し合う | shadow の投稿に `app_id` が付かないと、operator が本人（オーナー）の発言として受ける | operator は `allow_bots: none` のまま、`api_human_users` を入れない。実機で確かめる（下の 2） |
| 5 | 鍵の配布 | shadow の鍵が共有の名前に落ちると、operator の鍵へ移される | `env_own` で `SHADOW__SLACK_*` だけを見る |
| 6 | 別の役への作用 | multiplex では全役が同じプロセスにいる | shadow プラグインは自分の役（`ctx.profile_name`）の発言と口にだけ作用する |

同じ発言で operator のボットと本人の両方がメンションされたときは、両方が返事をする。これは仕様どおり。

### まだ確かめていないこと

使い捨ての Slack App と小さなスクリプトで確かめる（Hermes は使わない）。
本人のアカウントで投稿とステータスの変更が実際に起きるので、本人の了解を取ってから行う。

1. **Socket Mode で、ユーザーに代わって購読したイベント（`message.im` など）が届くか。** 公式には明記されていない。
   届かなければ、この作りは成り立たない
2. 本人名義の投稿に「APP」の表示が付くか。メッセージの JSON に `app_id` や `bot_id` が入るか（混線の 4）
3. ステータスを変えてから `user_status_changed` が届くまでの遅れ。ユーザーイベントとして購読できるか
4. ユーザートークンで投稿したボタン（承認・選択肢）を押したとき、その操作が App に届くか
