---
name: github-readonly-review
description: "Use when researching GitHub PR review state. Separate review bodies, inline comments, and thread resolution, and report unavailable fields without guessing."
version: 1.0.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [github, pull-request, review, read-only, provenance]
---

# GitHub PR read-only review

PR の調査は MCP の GitHub 読み取りツールだけで行う。結果にはツール名・`method`・
対象（owner/repository/PR 番号）を添える。

## PR を読む道具は `pull_request_read` ひとつ

**PR 系のツールは1個に畳まれている。** `method` で読む面を切り替える。

| `method` | 返るもの |
|---|---|
| `get` | PR 本体（タイトル、状態、本文、base/head、作成者） |
| `get_reviews` | 通常レビュー（本文、state、作成者） |
| `get_review_comments` | **review thread。** `is_resolved` / `is_outdated` と、同じ箇所へ付いたコメントの束 |
| `get_comments` | PR 会話欄のコメント（レビューではない） |
| `get_diff` / `get_files` / `get_commits` | 差分・変更ファイル・コミット |
| `get_status` / `get_check_runs` | CI の状態と、個々のジョブ |

issue も同じ形で、`issue_read` の `method` に `get` / `get_comments` /
`get_labels` / `get_sub_issues` などを渡す。

`get_pull_request_reviews` や `get_pull_request_review_threads` という名前の
道具は**存在しない**。呼べないのは権限でも設定でもなく、その名前が無いからである。

## 取れなかったものは、取れなかったと書く

カテゴリごとに「取得できた」「空だった」「取得できない」を分けて報告する。
レビュー本文が取れたことから、inline comment や thread の状態を推測しない。

**「取得経路が無い」と結論する根拠は、道具の一覧そのものである。**
`method` の選択肢は道具の説明文に書いてあるので、そこを読んでから判断する。

取得できないときに残すのは、ツール名・`method`・エラーまたは欠落フィールド・対象。

## 書けるのは issue の状態とコメントだけ

**`GH_TOKEN` 自体は書き込み可**であり、しかも broker / developer と同じ1本を
共有している。**鍵では絞れていない**——絞っているのは MCP に登録した手だけである
（mcp.yaml の include）。だから「トークンが read-only だから安全」とは考えないこと。

持っている手: `issue_write`（issue の状態変更）、`add_issue_comment`（追記）。

持っていない手: push、ファイル変更、ブランチ作成、PR の作成・更新・マージ、
レビュー送信（承認・変更要求）、pending review への追記、thread 解決。
**これらは能力の不足ではなく分担である。** 求められたら、できないと書いて止まる。

トークンはテンプレートやコメントへ書かず、オーナーがプロファイルの `.env` に置く。
