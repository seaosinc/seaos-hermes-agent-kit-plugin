# コマンド

ふだんの操作は SEAOS 画面で足ります。ここにあるのは、画面に無い操作と、困ったときに使うものです。

[← README に戻る](../README.md)

## 打つ場所

| OS | 打つ場所 | コマンドの場所 |
|---|---|---|
| macOS | ターミナル | `~/.local/bin/seaos-kit` |
| Windows | PowerShell | `%LOCALAPPDATA%\Programs\seaos-kit\seaos-kit.cmd` |

このページでは `seaos-kit` とだけ書きます。PATH に足していなければ、上の場所を付けて実行してください。

```
# macOS の例
~/.local/bin/seaos-kit doctor

# Windows の例
& "$env:LOCALAPPDATA\Programs\seaos-kit\seaos-kit.cmd" doctor
```

コマンドは、SEAOS 画面で一度 **「エージェントを反映」** を押すと置かれます。

---

## よく使うもの

| コマンド | すること |
|---|---|
| `seaos-kit doctor` | 設定漏れや壊れているところを探します。最後に「✓ 問題なし」と出れば正常です |
| `seaos-kit install` | 初回の仕上げ。定期的な見回り・作業部屋・共有の記憶を用意します。何度実行しても壊れません |
| `seaos-kit update` | 画面の「エージェントを反映」と同じです |
| `seaos-kit update --force-config` | エージェントの設定ファイルまで入れ直します。困ったときに案内されたら使います |
| `seaos-kit gateway restart operator` | Slack の窓口（operator）を起こし直します |
| `seaos-kit gateway status` | 窓口が動いているか（pid が出ていれば動いています） |

## エージェント

| コマンド | すること |
|---|---|
| `seaos-kit roles` | エージェントの一覧（無効にしたものには「（無効）」と出ます） |
| `seaos-kit disable <名前>` | 外します（画面のチェックを外すのと同じ）。記憶も消すなら `--remove-profile` |
| `seaos-kit enable <名前>` | 戻します。そのあと `seaos-kit update` で導入されます |
| `seaos-kit worker list` | エージェントの一覧（この PC で作ったものかどうかも出ます） |

## この PC の道具

| コマンド | すること |
|---|---|
| `seaos-kit machine check` | Docker・Node.js が揃っているか |
| `seaos-kit machine install docker` | Docker を入れます（`node` なら Node.js） |
| `seaos-kit machine start docker` | 入っているが止まっている Docker を起こします |

## 片付け

| コマンド | すること |
|---|---|
| `seaos-kit purge` | 終わって片付けたカードが何件あるか数えます。`--yes` を付けると本当に消します（戻せません） |
| `seaos-kit uninstall` | このキットがコマンドや共有の記憶として置いたものを外します。エージェントは残ります |
| `seaos-kit uninstall --profiles` | エージェントも（記憶ごと）消します。**戻せません** |

プラグインそのものを消すには、そのあとで `hermes plugins remove seaos-hermes-agent-kit-plugin` を実行します。

---

ほかにもコマンドはありますが、主にエージェント自身が使うものです。一覧は `seaos-kit --help` で見られます。
