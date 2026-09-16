---
name: kanban-collaboration
description: "kanban ボードの操作規約。ツールと CLI の使い分け、役割の名前、カードの扱い。全役割が読む。"
version: 1.0.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [kanban, collaboration, delegation, multi-agent]
---

# Kanban 協調規約

ボードが唯一の共有状態である。報告・相談・回答はすべて `hermes kanban` を通して
カードに書く。**後から誰でも経緯を追えることが最優先。**

（着手時の comment、止まり方、再開時の読み直しといった全役共通の作法は
SOUL に差し込まれている共通ブロックにある。ここはボードの操作に絞る。）

## 役割の名前は固定3役＋業務別ワーカーだけ

| 名前 | 担当 |
|---|---|
| `operator` | ユーザーと話す唯一の窓口 |
| `fixer` | **判断のすべて**。完了判定と、詰まったときの解決 |
<!-- if-role: broker -->
| `broker` | 外部エージェントとの連絡係。ローカル CLI もリモート A2A も |
<!-- end-if-role -->
<!-- if-role: provisioner -->
| `provisioner` | **この PC に道具を入れる**（Docker、Node.js など。台帳にあるものだけ） |
<!-- end-if-role -->
| 業務別ワーカー | 実務。役ごとに責任が違う。`hermes profile list` の説明文で分かる |
<!-- if-role: recruiter -->
| `recruiter` | **エージェントそのものを作る**業務別ワーカー |

`recruiter` は構成を書き換えるため、反映にゲートウェイの再起動を伴う。
**再起動は `seaos-kit gateway restart <役> --when-idle` で自分で叩き、
カードはそのまま完了させる。**（→「反映の再起動」）
<!-- end-if-role -->

**業務別ワーカーは増える。** db-migration のように業務ごとに足せる
（`seaos-kit worker new`）。実在する名前は `hermes profile list` で確認する。

役割に言及するときは、**実在する名前をそのまま使う。**
`--assignee` に書く名前も、本文で言及する名前も同じ語で統一する。
即席の呼び名（「判定担当」「実行役」「審判」）は、読んだ側が誰のことか推測するしかなくなる。

なお `kanban.orchestrator_profile` は「全子カード完了後にルートカードが戻る先」を指す
Hermes の設定キーであり、役割名ではない。現在の値は `fixer`。

## ツールと CLI の使い分け

**ツールに無い操作は CLI で実行する。** `terminal` は全役割が持っている。

| 操作 | 経路 |
|---|---|
| create / comment / complete / block / unblock / link | **ツール**（`kanban_*`） |
| show / list / heartbeat / attach / request_review | **ツール** |
| **archive**（カードを畳む） | **CLI** `hermes kanban archive <id>` |
| **unlink**（依存を外す） | **CLI** `hermes kanban unlink <親> <子>` |
| assign / promote / tail / log | **CLI** |

`kanban_archive` や `kanban_unlink` というツールは無いが、CLI にはある。
ツール一覧だけを見て「この環境ではできない」と答える前に、`--help` を読む。

**ゲートウェイの動きを確かめるのも `terminal` である。** 専用のツールは無い。

| 見たいもの | 場所 |
|---|---|
| ゲートウェイの動作ログ | `~/.hermes/profiles/<役>/logs/gateway.log` |
| 起動時の標準出力 | `~/.hermes/profiles/<役>/logs/gateway-stdout.log` |
| `--when-idle` の待ちと再起動 | `~/.hermes/profiles/<役>/logs/gateway-restart.log` |
| カード1枚のワーカーログ | `hermes kanban log <id>` |
| 何が起きたかの時系列 | `hermes kanban show <id>` の Events |

カードの作成はツールを使う。`--body` が長いと、CLI ではシェルのクォートで壊れる。

### カードを作るときに渡すもの

| | |
|---|---|
| `title` | 何を達成するか |
| `body` | 前提・完了条件・参照先 |
| `assignee` | 担当（`--triage` に置くなら省く） |
| `triage` | 分解に載せるとき |
| `max_runtime_seconds` | **`1800`（30分）** |

**`max_runtime_seconds` には `1800` を入れる。**

理由は2つある。**上限が無いと、暴走したカードが走り続けて作業部屋を掴んだままになる。**
そして **`0` は「無制限」ではない**——Hermes は「値が入っているか」で判定するので、
`0` は**0秒の上限**として効き、そのカードは起動から15秒で強制終了される。
2回失敗すると `gave_up` になり、**二度と動かない。**
`kanban show` の `Runs` に `timed_out ! elapsed 15s > limit 0s` と出ていたら、これである。

**30分で足りないと分かっている作業**（大きなビルド、長い調査）だけ、
その場で必要な秒数に上げる。**「念のため大きく」は取らない**——止まる線が無くなる。

**上限は上げる方向にしか動かさない。** `300` のような短い値も同じところへ落ちる
（`elapsed 2571s > limit 300s` で timeout し、2回で `gave_up`）。

**作成後に上限を変える CLI は無い**（`kanban edit` は結果テキストしか触れない）。
毎分走る `runtime-guard` が 1800 を下回る値を見つけ次第 1800 へ引き上げるが、
**間に合わずに死ぬことがある。**

### ユーザーから受け取ったファイルは、本文の「添付ファイル」にある

窓口がユーザーから受け取ったファイルは、本文に次の形で書かれている。

    添付ファイル（担当はこのパスから読める。読み取り専用）:
    - /…/.hermes/kanban/files/<日時>/<名前>  … 何のファイルか

**そのパスをそのまま読む。** ホストでも作業部屋の中でも同じパスで見える
（部屋の中では読み取り専用。加工するなら `/workspace` へ写してから）。
Hermes の添付（`kanban_attachments` と、カード文脈の「Attachments」）も同じく読める。

**カードを作る・分け直すときは、その行を要るカードへ写す。** 担当は兄弟カードも
親の本文も読めないので、書き写さないと届かない。

**Excel・Word・PowerPoint・PDF は、隣の `.md`（変換したもの）を先に読む。**
表の値や書式そのものが要るときだけ元のファイルを開く。

シェルを持たない役は、読み取り専用の `files` MCP で読む（置き場と板の添付だけが見える）。
読めなかったら、推測で進めずに止まる（パスと、何が起きたかを書く）。

## 反映の再起動は `--when-idle` で自分で叩く

構成を書き換えたら、ゲートウェイを起こし直すまで反映されない。
**ワーカーはゲートウェイの子**なので、カードの中から素で叩くと自分の実行ごと落ちる。

```
seaos-kit gateway restart <役> --when-idle
```

**走行中のカードが無くなってから起こし直す**ので、自分も他のカードも落ちない。
叩いたらすぐ戻るので、**そのままカードを完了してよい**——落ちない経路がある以上、
再起動の可否は人に仰ぐ判断ではなく、この役の手順である。

いま即座に反映が要る（自分が落ちてもよい）ときだけ `--detach` を使う。

## PR を指すときは `owner/repo#番号` で書く

```
seaosinc/seaos-quent-cloud-pc-client-nuxt#46
```

**コメントに PR の URL を貼ると、そのカードは24時間 spawn されなくなる。**
ディスパッチャの `active_pr` ガードが、直近24時間のコメントにある PR URL を
「worker が PR を立てた直後だから、もう一度起こすと PR が二重になる」と読む。
レビュー**対象**として指しただけでも同じで、review レーン以外に解除経路は無い。
**止まってもカードは `ready` のままなので、`list` にも `stats` にも異常として出ない。**

自分が立てた PR を報告するときは URL でよい。そのときガードは意図どおり働く。

## よく使うコマンド

| したいこと | コマンド |
|---|---|
| 進捗・気づき・判断の記録 | `hermes kanban comment $TASK_ID "本文"` |
| 判断を仰いで停止 | `hermes kanban block $TASK_ID --kind needs_input "質問"` |
| 前提が足りず着手不能 | `hermes kanban block $TASK_ID --kind capability "何が足りないか"` |
| 他カード待ち | `hermes kanban block $TASK_ID --kind dependency "待つ対象"` |
| 完了 | `hermes kanban complete $TASK_ID` |
| 状況確認 | `hermes kanban show $TASK_ID` |

## 「足りない」と書くときは、一覧そのものを根拠にする

`--kind capability` は**次の世代のカードの前提になる。** ここに書いた観測は
検算されないまま引き継がれ、それを埋めるためのカードが立ち、そのカードもまた
同じ壁に当たる。**一世代ずつ見るとどれも正しいので、誤りは世代を跨ぐまで現れない。**

だから、`capability` で止めるときは**列挙した実物**を添える。

| 足りないと言うもの | 添える事実 |
|---|---|
| MCP の道具 | `tools/list` の応答にある名前の一覧 |
| CLI のサブコマンド | `--help` の出力 |
| 設定キー | 実際の設定ファイルの該当箇所 |
| 権限・鍵 | 実行して返ってきたエラーの原文 |

**道具の説明文まで読んでから言う。** ひとつの道具が `method` や `mode` で複数の面を
持つことがあり、名前だけを見て「その面は無い」と結論すると、実際にはある経路を
無いことにしてしまう。

綴りを推測したくなったら `context7` で引く（`resolve-library-id` → `query-docs`）。

## カードを畳むときは archive まで行う

「止めて」と言われたら、対象カードと関連する子カードを `hermes kanban archive` で畳む。
todo のまま残ったカードは、依存が解けた瞬間に動き出す。

## 実装は CLI エージェントへ委譲する

コードを書く作業は `opencode run` に渡す。手順は
`delegate-to-cli-agents` スキルにある。Hermes の子エージェントは実装に使わない
（理由と代わりの経路は共通ブロックとそのスキルにある）。
