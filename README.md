# seaos-hermes-agent-kit-plugin

SEAOS のエージェント役一式を、**Hermes のプラグインとして配る**。
`seaos-hermes-agent-collab-kit`（zsh 版）の後継。完成したら旧キットは撤去する。

## 何が入っているか

| | |
|---|---|
| `templates/` | **役の規約・スキル・作業部屋の作り方。** 唯一の編集点 |
| `core/` | 生成・導入・検査・鍵配布。**Python のみ**（Win / Mac / Linux 共通） |
| `desktop/plugin.js` | GUI。素の ESM で読まれる（ビルド不要） |
| `dashboard/plugin_api.py` | GUI から `core/` を呼ぶための口 |

## 入れ方

```
hermes plugins install <URL>
```

デスクトップアプリなら 設定 → プラグイン → URL。
**入れたあとトグルを2つ入れる**（Python 側と desktop 側。どちらも既定オフ）。

## 方針

- **Hermes 本体は改造しない。** 公式の拡張口にだけ載る
- **配置表は `core/` の1箇所が正。** zsh 側も GUI も同じ口を叩く
- **ビルド工程を持たない。** pull した内容がそのまま動く
