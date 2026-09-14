---
name: workspace-workflow
description: "使い捨ての作業部屋の性質と、そこで使う道具の綴り。コードを書く役が使う。"
version: 2.0.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [worker, workspace, git, container]
---

# 作業部屋

あなたのターミナルとファイル操作は、**カードごとに立つコンテナの中**で動く。
**進め方はあなたが決める。** ここにあるのは、決めるために要る事実である。

## この部屋の性質

| | |
|---|---|
| **作業場所** | `/workspace`。**カードが終わると部屋ごと消える** |
| **外へ出る口** | `$HERMES_KANBAN_WORKSPACE` に置いたものだけ。ホストと共有されている |
| **残る場所** | `/cache`。言語と落としたパッケージが載る。**次のカードでも使える** |
| **足せないもの** | システムパッケージ（`apt-get` は権限が無く通らない） |
| **対象** | カード本文の「リポジトリ:」に書かれている。複数あることがある |
| **作法** | リポジトリ側の `AGENTS.md` / `CLAUDE.md` / `.hermes.md` にある |

**毎回まっさらな部屋で始まる。** 前のカードで調べたことも、入れた設定も残っていない。

## 道具の綴り

| やること | 綴り |
|---|---|
| 取ってくる | `gh repo clone <owner>/<repo> -- --branch <ベース>` |
| 言語を揃える | `mise install`（リポジトリの宣言を読む） |
| 道具を足す | `mise use -g <tool>@<版>`（入り先は `/cache`） |
| 枝を作る | `git switch -c task/$HERMES_KANBAN_TASK` |
| 送る | `git push -u origin task/$HERMES_KANBAN_TASK` |
| PR にする | `gh pr create --fill --base <ベース>` |
| **CI を見届ける** | `gh pr checks <番号> --watch`（緑になるまで。落ちたら直して push し直す） |
| **指摘を確かめる** | `gh pr view <番号> --comments` / `gh pr diff <番号>` |
| AWS を見る | `aws …`（**認証情報が無い間は失敗する**。カードが AWS を求めていないなら使わない） |
| 見せたいものを出す | `cp <ファイル> "$HERMES_KANBAN_WORKSPACE/"` → 完了時に `artifacts` で絶対パスを宣言 |

`$HERMES_KANBAN_WORKSPACE` は**部屋の中でもそのまま使える**——同じ場所が同じ絶対パスで
見えているので、読み替えは要らない。

## 触った数だけ要るもの

複数のリポジトリを変更したなら、**その数だけ push と PR がいる。**
またいだ変更は、PR の本文で互いを参照させる。
