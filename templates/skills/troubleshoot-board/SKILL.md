---
name: troubleshoot-board
description: "カードが止まったまま動かない・完了しても報告が来ない・分解されない・壊れたカードを直接直したいときの手順。"
version: 1.0.0
metadata:
  hermes:
    tags: [troubleshooting, kanban, board]
---

# ボードが回らない

ボードは `<HOME>/kanban.db` に全役で共有されている。**直接読んで、直接直せる。**
コマンドは `hermes kanban --help` で引く。直す前に、そのカードの今の状態を `hermes kanban show <id>` で控える。

## 完了しても報告が来ない

窓口（operator）は、カードに紐付けた通知で起こされて報告する。紐付けが無いと、完了しても誰も起きない。

1. `hermes kanban show <根のカード>` で子カードが全部 done かを見る
2. 紐付けがあるかを `hermes kanban notify-list <id>` で見る
3. 無ければ、operator に「<id> はどうなった？」と聞けば、読んで報告する。
   原因が「スキルを読めなかった」なら → `troubleshoot-windows`

## カードが止まったまま

    hermes kanban list --status <状態>

| 状態 | よくある原因 | 手当て |
|---|---|---|
| `triage` のまま | 分解器が動いていない（ゲートウェイが止まっている、モデルの鍵が無い） | `seaos-kit gateway status`、`seaos-kit doctor` |
| `ready` のまま | 担当が存在しない・無効な役 | `hermes kanban assign <id> <役>` で付け替える |
| `blocked` | 誰かの判断待ち | 理由を読む。保留のカード（`seaos-kit card held` に出るもの）は、オーナーが決めるまで動かさない |
| `running` のまま動かない | ワーカーが死んでいる | `hermes kanban reclaim <id>` で掴みを外す |

## 壊れたカード・要らないカード

`hermes kanban archive <id>` で畳む（論理削除。戻せる）。物理削除（`seaos-kit purge`）は人の承認を取ってから。
