---
name: troubleshoot-desktop
description: "Hermes Desktop が起動しない・「Set up Hermes Desktop」の初期画面に戻る・起動がとても遅い・勝手に落ちたときの手順。"
version: 1.0.0
metadata:
  hermes:
    tags: [troubleshooting, desktop, launcher, update]
---

# Hermes Desktop が起動しない・初期画面に戻る

## まず、更新の仕上げ中でないか

`<HOME>/installs/*/source-completion-pending` があれば、Hermes が更新の仕上げをしている。
`desktop.log` に「An update is finishing」が並ぶ。**Desktop を終了させずに待つ**
（Desktop アプリの組み直しを含むと数分かかる）。印が消えれば自動で起動する。

## 「Set up Hermes Desktop」の初期画面に戻った

インストール済みなのに初期画面が出るのは、Desktop が Hermes の起動スクリプトで `--version` を試して
失敗したとき。いちばん多い原因は、**起動スクリプトが消えた一時ディレクトリの Python を指している**こと。

1. 起動スクリプトの2行目を読む

       <HOME>/hermes-agent/.hermes/bin/hermes      （Windows は hermes.cmd / hermes.exe）
       <HOME>/hermes-agent/.hermes/bin/hermes-acp

   `exec /var/folders/.../T/<何か>/tools/python-…/bin/python3` のように一時ディレクトリを指していたら、これ
2. 本来の Python（`<HOME>/tools/python-…/bin/python3`）があることを確かめる。
   動いているゲートウェイの Python と同じものである（`ps` で見える）
3. 人の承認を取ってから、2 つの起動スクリプトの Python のパスだけを本来のものに書き戻す（ほかの行は触らない）
4. Desktop を終了して起動し直す

**起きる理由：** 一時ディレクトリを HERMES_HOME にして Hermes を起動すると、Hermes は道具の置き場を
そこに移し、共有の起動スクリプトをその Python で書き直す。テストが本物の Hermes を呼ぶと起きる。

## 勝手に落ちた・起動が遅い

`desktop.log` の最後を読む。

- 「hand-off」「update is still running」「Code updated」→ Hermes の更新の途中。上の「仕上げ中」と同じく待つ
- 「Timed out connecting to Hermes backend」のあとに「HERMES_BACKEND_READY」→ 画面が先に諦めただけ。再読み込みで繋がる
- Windows で「Skipped rebuilding the desktop app」→ 動いているアプリは組み直せない。落ち着いたら 設定 → About → Update now

## 「更新サーバーに接続できませんでした」

更新の確認が、更新サーバー（`hermes-assets.nousresearch.com`）に届かなかっただけ。Hermes は動いている。
繋がるかは `curl -sS -o /dev/null -w "%{http_code}" https://hermes-assets.nousresearch.com/` で確かめる
（404 でも、サーバーは動いている）。時間をおいて「今すぐ確認」を押す。
