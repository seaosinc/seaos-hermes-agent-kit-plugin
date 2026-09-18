---
name: slack-reactions
description: "Slack の絵文字リアクションで来た合図への応じ方。👀 は状況を聞かれている、✅ 🙆 👌 🎉 💯 はもう終わりでよいという合図で、その依頼を片付ける。人がメッセージに絵文字を付けたときに読む。"
version: 1.0.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [slack, reactions, operator]
---

# 絵文字で来た合図に応じる

絵文字は**短い指示**である。文章で返しすぎない。

## 👀 — いまの状況を一言で返す

答えるのは、**頼んだ人の言葉で見た状況だけ**である。

    ✓ 「会社概要はまとまりました。いま参入の経緯を調べています。あと数分です」
    ✗ 「カード t_xxx が running、t_yyy は ready です」
    ✗ 「3枚中2枚が done です」

進み具合は**枚数ではなく中身で言う**（「二つのうち一つは終わりました」）。
状態の名前、カードの id、役の名前は出さない。

## ✅ 🙆 👌 🎉 💯 — その依頼を片付ける

`white_check_mark` `ok_woman` `ok_hand` `tada` `100` のどれかが付いたら、
「この件はもう見た、終わりでよい」という合図である。
**そのスレッドに紐付いたカードを archive する。**

    hermes kanban archive <id>

`done` ではなく `archive` にする。done は「仕事が終わった」という判定で、これは
「もう要らない」というユーザーの意思——別のものである。
未完了のものが残っていてもそのまま畳んでよい。**要らないと言われたものを
走らせ続けない。**

**返事は要らない。** 同じ絵文字を返すだけでよく、「片付けました」とは言わない。

## 効かないときに見るところ

配る設定では `reactions` と `reaction_triggers` が有効になっている。それでも届かない
なら、Slack App 側である。

- `reactions:read` / `reactions:write` の scope
- `reaction_added` / `reaction_removed` のイベント購読
- Bot が対象チャンネルに参加しているか（DM は不要）

`seaos-kit doctor` が権限の欠けを名指しする。確かめたことと未確認のことを分けて、
事実としてカードに残す。
