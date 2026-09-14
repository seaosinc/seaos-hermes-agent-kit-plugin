---
name: slack-window
description: 新しい窓口（Slack から話しかけられる役）を用意する手順。App のマニフェストを書いて人に渡し、鍵が入るまで止まる。
metadata:
  tags: [slack, gateway, worker, provisioning]
---

# 窓口を用意する

**窓口とは、Slack から直接話しかけられる役である。** operator がその一例で、
プロジェクト専用のボットのように増やすことができる。

普通の役（板から仕事を受けるだけ）には要らない。**人が直接話しかける相手として
頼まれたときだけ**この手順を踏む。

## 1. 役そのものを先に作る

`worker-provisioning` の手順で役を作る。**窓口かどうかは後から足せる**ので、
まず何をする役かを固める。

`profile.yaml` に足すのは3つ。

```yaml
gateway: true

# **鍵は必ず自分専用にする。** 共有すると、2つのゲートウェイが同じ発言を拾って
# 両方が返事をする。
env_own:
  - SLACK_BOT_TOKEN
  - SLACK_APP_TOKEN
  - SLACK_ALLOWED_USERS

env_requires:
- name: SLACK_BOT_TOKEN
  description: "この窓口の Bot トークン（Bot トークン）"
  required: false
- name: SLACK_APP_TOKEN
  description: "この窓口の App トークン（App トークン。Socket Mode 用）"
  required: false
- name: SLACK_ALLOWED_USERS
  description: "この窓口と話せる Slack ユーザー ID（カンマ区切り）"
  required: false
```

**すべて任意にする。** 必須にすると、その役を足しただけで設定画面の
「反映」が全体で止まる。

## 2. マニフェストを出す

**自分で書かない。** Hermes に生成器がある。

    hermes slack manifest --name "<人が見る名前>" --description "<一行で。何に答える窓口か>"

スラッシュコマンドは `COMMAND_REGISTRY` から、スコープと Socket Mode は Hermes の
既定から作られる。**本体が要求するものと必ず一致する**ので、手で並べたスコープより
確実である。増減させたくなったら、まず**なぜ既定で足りないのか**を書くこと。

名前と説明は**あなたが決める**。何をする窓口かはあなたがいちばん分かっている。

**`socket_mode_enabled` が入っていることを確かめる。** これが無いと App トークンを
発行できず、窓口は繋がらない。

**リアクションを使うなら**、生成された JSON に `reactions:read` /
`reactions:write` と、`reaction_added` / `reaction_removed` を足す。
足さないまま設定だけ有効にすると、呼んだときに `missing_scope` で落ちる。

## 3. 人に渡して止まる

カードに次を書いて `block --kind needs_input` で止まる。**この3つが揃っていないと
人は動けない。**

1. **https://api.slack.com/apps** — ここで「Create New App」→「From an app manifest」
2. **生成したマニフェスト**（`hermes slack manifest` の出力をそのまま）
3. **やってもらうこと**を順に:
   - ワークスペースにインストールして Bot トークンを控える
   - Basic Information → App-Level Tokens で `connections:write` を付けて
     トークンを作り、App トークンを控える（**API では作れないので手で発行する**）
   - Hermes の設定画面 → SEAOS → その役の行の「設定」から2つを入れる
   - このカードを `unblock` する

**待っているあいだ、他のことを進めない。** 鍵が入るまでこの役は動かない。

## 4. 再開したら

```
seaos-kit update                      # 設定を配る
seaos-kit gateway restart <役>        # この窓口を起こす
seaos-kit doctor                      # 取りこぼしを見る
```

**同じトークンを2つの役に入れない。** 両方のゲートウェイが同じ発言を拾い、
ユーザーには二重に返事が届く。設定画面は役ごとに行が分かれているので、
そこで取り違えなければ起きない。

## 確かめること

- Slack でその窓口にメンションして、**その役だけが**返すこと
- operator が同じ発言に反応していないこと
- `seaos-kit doctor` が緑であること
