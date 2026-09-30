---
name: troubleshoot-scheduled
description: "定期実行（booking-sync・kit-sync・各 guard など）が登録されていない・失敗し続ける・キットが自動で最新にならないときの手順。"
version: 1.0.0
metadata:
  hermes:
    tags: [troubleshooting, cron, schedule]
---

# 定期実行が回っていない

キットの定期実行は、operator の役に載っている。

    hermes -p operator cron list

次の 8 つが並んでいればよい。

| 名前 | 間隔 | 止まると |
|---|---|---|
| booking-sync | 毎分 | 許可表が古くなり、**オーナー以外が全員止まる** |
| kit-sync | 10 分ごと | キットが自動で最新にならない |
| kit-maintain | 毎日 4:30 | 日次の保守が走らない |
| runtime-guard / assignee-guard / container-guard | 毎分 | 見張りが止まる |
| spin-guard | 5 分ごと | 見張りが止まる |
| progress-report | 毎分 | 進捗の知らせが止まる |

## 無い

`seaos-kit update`（または SEAOS 画面の「エージェントを反映」）で、無いものが登録し直される。
`seaos-kit install` でもよい（こちらは作業部屋と共有の記憶も揃える）。

## あるのに失敗する

「前回の結果」がエラーなら、そのスクリプトのログを読む。booking-sync は `<HOME>/logs/booking-sync.log`。
スクリプトの実体は `<HOME>/profiles/operator/scripts/` にある。

## 登録されているのに走らない

定期実行はゲートウェイ（ホスト）が回す。ゲートウェイが止まっていれば全部止まる → `seaos-kit gateway status`。
