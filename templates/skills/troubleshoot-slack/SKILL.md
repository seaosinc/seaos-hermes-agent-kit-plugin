---
name: troubleshoot-slack
description: "Slack で話しかけても返事が来ない・👀 は付くのに返事が無い・「いま許可を確認できません」と出る・特定の人だけ無視されるときの手順。"
version: 1.0.0
metadata:
  hermes:
    tags: [troubleshooting, slack, gateway, booking-gate]
---

# Slack に返事が来ない

上から順に、どこで止まっているかを切り分ける。

## 1. ゲートウェイがその窓口を受け持っているか

    seaos-kit gateway status operator

「ホスト: pid …」と「operator: 受け持たれている」が出ればよい。`slack: fatal` などが出ていれば、
`gateway.log` / `gateway.error.log` でその理由を読む。止まっていれば `seaos-kit gateway restart operator`。

## 2. 👀 すら付かない → Slack の入口で落ちている

- `gateway.error.log` に「Early reject of unauthorized user U…」→ 話しかけた人に許可が無い。
  `SLACK_ALLOWED_USERS`、オーナー、ゲストの許可（`seaos-kit guest list`）を見る
- App をチャンネルに招待していない、メンションしていない
- Slack App の権限が足りない → `seaos-kit doctor` の「Slack App の権限」

## 3. 👀 は付くのに返事が無い → アクセスゲート（booking-gate）で止まっている

ログで止めた理由を見る。

    grep "pre_gateway_dispatch skip" <HOME>/logs/agent.log <HOME>/logs/gateway.log

| reason | 意味 | 直し方 |
|---|---|---|
| `booking-table-unavailable` | 許可表が無いか、5 分以上古い。**オーナー以外が全員止まる** | 下の「許可表が古い」 |
| `outside-booking` | その人の許可の時間外、またはチャンネルの許可を別の場所で使った | `seaos-kit guest list` で許可を確かめる |
| `rate-limited` | 1 人 1 時間の上限を超えた | 時間をおく |

止められた本人には、案内（「いまは会話できる時間ではありません」など）が本人にだけ見える形で届いている。

### 許可表が古い（`booking-table-unavailable`）

許可表 `<HOME>/booking-gate/reservations.json` は、定期実行の booking-sync が毎分作り直す。

1. `hermes -p operator cron list` に booking-sync があるか。無ければ → `troubleshoot-scheduled`
2. あれば `<HOME>/logs/booking-sync.log` の最後を読む。毎分増えていないか、エラーが出ていないか
3. Slack の読み取りの失敗（途中で切れた、時間切れ）が続くなら、ネットワークか Slack 側を疑う

## 4. operator が受けたのに返事を書いていない

`agent.log` で、その時刻の operator のターンを読む。
「Skill '…' is not supported on this platform」が出ていれば、スキルが読めていない → `troubleshoot-windows`。
