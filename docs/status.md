# いまどこまで出来ているか

`seaos-hermes-agent-collab-kit`（zsh 版）の後継。**キットそのものを Hermes の
プラグインとして配る**形にした。完成したら旧キットは撤去する。

## 動くもの

| | |
|---|---|
| `core/` | 生成・差分・説明文の同期・鍵配布・反映。**Python のみ** |
| `core/cli.py` | 薄い皮（`roles` / `build` / `diff` / `describe` / `env` / `update`） |
| `dashboard/plugin_api.py` | GUI から core を呼ぶ口。全ルート応答を実機で確認済み |
| `desktop/plugin.js` | 鍵 → 役 → 反映 の3段ウィザード。素の ESM（ビルド不要） |
| `templates/` | 役の定義。旧キットから持ち込み、**現行の8役と一致**（diff が全て `=`） |

インストールはローカルの bare リポジトリから実証済み。

```
hermes plugins install file:///Users/t-adachi/Hermes/kit.git
hermes plugins enable seaos-hermes-agent-kit
```

`~/.hermes/plugins/seaos-hermes-agent-kit/` に **1フォルダで全部**入る。

## 分かったこと（踏んだもの）

- **マニフェストは v1 で書く。** ローダ（`plugins.py`）は v2 を読めるが、**入口の
  インストーラ（`plugins_cmd.py`）は v1 まで**。v2 を宣言すると install で弾かれる。
- **`diff` に `config.yaml` を入れてはいけない。** `profile update` が既定で保持するので、
  生成物と一致しないのが正常な状態。比べると全役が永久に「更新される」と出る。
- **生成器の stdout を飲む。** CLI では表示だが、GUI から呼ぶと API の経路へ漏れる。
- **`.env` はインストール先ごとに別。** git に入らないので、配った先では
  ウィザードで入れ直す。これは仕様（1フォルダで自己完結する）。

## 残っている作業

1. **OS 依存の 578 行**（常駐・コマンド配置）。`_gateway` / `_init` / `_install` / `_uninstall`
   に相当する部分。Windows は Scheduled Task、macOS は launchd、Linux は systemd + linger。
   **paths.py 以外に platform 分岐を書かないこと。**
2. **OS 非依存の残り**（`_worker` / `_workspace` / `_booking` / `_mem0` / `_terraform` / `_hotl`）。
   呼び先が `hermes` / `git` / `docker` / `npx` だけなので、素直な引っ越しで済む。
3. **doctor と test の移植**（zsh 版の `hermes-kit doctor` / `test` 相当）。
4. **採番。** いま `0.0.0` 固定。旧キットは全役 `0.1.0` のまま動かず、更新が届いたか
   判定できなくなっていた。ビルド時に git から採番する。
5. **GUI の実機確認。** デスクトップアプリで Python 側・desktop 側のトグルを
   2つとも入れて、画面が出るところまで。

## 変えていない前提

- **Hermes 本体は改造しない**（`~/.hermes/hermes-agent/` は読むだけ）
- **配置表は `core/build_distributions.py` の `ROLES` が唯一の正**
- **秘密の正はキット直下の `.env`**。GUI は書き込み専用で、値を画面へ返さない
- **ビルド工程を持たない**（UI を TS 化したくなったときだけ GitHub Releases を足す）
