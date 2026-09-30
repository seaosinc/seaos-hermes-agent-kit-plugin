---
name: troubleshoot-memory
description: "共有の記憶（mem0）が使えない・「Mem0 backend failed to initialize」「Invalid API key」がログに出る・記憶が0件のままのときの手順。"
version: 1.0.0
metadata:
  hermes:
    tags: [troubleshooting, mem0, memory, docker]
---

# 共有の記憶（mem0）が使えない

mem0 は、この PC の Docker の中で動くサーバー（`http://localhost:8888`）である。

## 1. サーバーが動いているか

    seaos-kit mem0 check

止まっていれば `seaos-kit mem0 up`。Docker そのものが動いていなければ、先に Docker Desktop を起動する
（Windows は WSL2 も要る → `troubleshoot-windows`）。

## 2. 各役が手元のサーバーを向いているか

`<HOME>/profiles/<役>/mem0.json` に **`host`** が入っているか。

- `host` が無いと、Hermes は手元ではなく mem0 のクラウド版へ繋ぎに行き、手元の鍵が合わずに
  `agent.log` に「Mem0 backend failed to initialize (platform mode): Invalid API key」が出る
- `seaos-kit update` で書き直される。`seaos-kit doctor` の「全役の共有記憶」でも ✗ が出る

## 3. 本当に届くか

`mem0.json` の `host` と `api_key` で、`GET <host>/memories?user_id=<user_id>` をヘッダ `X-API-Key: <api_key>` 付きで
叩き、200 が返れば届いている（読むだけで、何も書き換えない）。
