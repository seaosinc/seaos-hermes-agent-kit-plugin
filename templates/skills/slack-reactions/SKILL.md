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

絵文字は**短い指示**である。返すほうも短くする。

## 👀 — いまの状況を一言で返す

答えるのは、**頼んだ人の言葉で見た状況だけ**である。

    「会社概要はまとまりました。いま参入の経緯を調べています。あと数分です」

進み具合は**中身で言う**（「二つのうち一つは終わりました」）。状態の名前や枚数で
答えたくなったら、それを依頼の言葉へ置き換える合図である。

## ✅ 🙆 👌 🎉 💯 — その依頼を片付ける

`white_check_mark` `ok_woman` `ok_hand` `tada` `100` のどれかが付いたら、
「この件はもう見た、終わりでよい」という合図である。
**そのスレッドに紐付いたカードを archive する。**

    hermes kanban archive <id>

`done` ではなく `archive` にする。done は「仕事が終わった」という判定で、これは
「もう要らない」というユーザーの意思——別のものである。
未完了のものが残っていてもそのまま畳む。**要らないと言われたものは、そこで止める。**

**返事は同じ絵文字ひとつでよい。**

## 効かないときに見るところ

配る設定では `reactions` と `reaction_triggers` が有効になっている。それでも届かない
なら、Slack App 側である。

- `reactions:read` / `reactions:write` の scope
- `reaction_added` / `reaction_removed` のイベント購読
- Bot が対象チャンネルに参加しているか（DM は不要）

`seaos-kit doctor` が権限の欠けを名指しする。確かめたことと未確認のことを分けて、
事実としてカードに残す。
