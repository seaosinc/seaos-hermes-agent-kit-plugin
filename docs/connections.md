# 接続情報

エージェントが外部のサービスを使うための鍵です。SEAOS 画面の **「接続情報」** から入れます。

- **入れた値は画面に二度と表示されません。** 変えるときは「変更」から入れ直してください
- 値はこの PC の中（`~/.hermes/seaos-kit/.env`）にだけ保存され、Slack や AI には送られません
- 入れたあとは **「エージェントを反映」** を押すと、各エージェントに配られます

[← README に戻る](../README.md)

---

## 一覧

| 名前 | 必須か | 使うエージェント | 無いとどうなるか |
|---|---|---|---|
| `OPENROUTER_API_KEY` | **必須** | 全員 | 何も動きません |
| `GH_TOKEN` | 任意 | developer / senior-developer / handler | GitHub の読み書き（clone・PR・Issue）ができません |
| `NOTION_TOKEN` | 任意 | handler | Notion を読めません |
| `BACKLOG_DOMAIN` | 任意 | handler | Backlog を読めません（`BACKLOG_API_KEY` とセット） |
| `BACKLOG_API_KEY` | 任意 | handler | 同上 |
| `AWS_ACCESS_KEY_ID` | 任意 | developer / senior-developer | AWS を触れません（3つセット） |
| `AWS_SECRET_ACCESS_KEY` | 任意 | 同上 | 同上 |
| `AWS_REGION` | 任意 | 同上 | 同上 |

Slack の鍵は、共通の一覧ではなく **operator の行の「設定」** から入れます。→ [Slack とつなぐ](slack.md)

画面に出てくるのは、**有効にしているエージェントが使う鍵だけ**です。
たとえば handler を外していると、Notion や Backlog の行は出ません。

任意の鍵が空のあいだは、その鍵を使う機能が自動で無効になります（エラーにはなりません）。
入れて反映すれば、自動で有効に戻ります。

---

## 入手方法

### OPENROUTER_API_KEY

1. [openrouter.ai](https://openrouter.ai/) にログインする
2. [Keys](https://openrouter.ai/keys) で「Create Key」を押す
3. 表示された `sk-or-…` をコピーして貼り付ける

クレジット（残高）が無いと動きません。OpenRouter の Credits 画面で確認してください。

### GH_TOKEN

1. GitHub の **Settings → Developer settings → Personal access tokens → Tokens (classic)** を開く
2. 「Generate new token (classic)」を押す
3. スコープに **`repo`**・**`workflow`**・**`read:packages`** を付ける
4. 作られた `ghp_…` を貼り付ける

エージェントがこの鍵でリポジトリを clone し、ブランチを push し、PR を作ります。
**触らせたいリポジトリにアクセスできるアカウント**で作ってください。

### NOTION_TOKEN

1. [notion.so/my-integrations](https://www.notion.so/my-integrations) で「新しいインテグレーション」を作る（種類は「内部」）
2. 表示された `ntn_…` を貼り付ける
3. **読ませたいページで「…」→「接続」から、そのインテグレーションを追加する**（これを忘れると何も読めません）

### BACKLOG_DOMAIN / BACKLOG_API_KEY

- `BACKLOG_DOMAIN`：Backlog のアドレスの `https://` を除いた部分（例：`example.backlog.com`）
- `BACKLOG_API_KEY`：Backlog の **個人設定 → API** で発行します

### AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION

AWS の操作をエージェントに任せるときだけ入れます。IAM でアクセスキーを発行し、
リージョンは `ap-northeast-1` のように入れます。**3つとも入れるか、3つとも空**にしてください。

---

## エージェントごとに別の OpenRouter キーを使う

請求や利用上限をエージェントごとに分けたいときに使います。

1. エージェントの行の **「設定」** を押す
2. 「共通の接続情報を、この役だけ別の値にできます。」の下の **OPENROUTER_API_KEY** に入れる
3. **「エージェントを反映」** を押す

- 入れていないエージェントは、共通の値を使います
- 元に戻すには **「共通に戻す」** を押して反映します
- 有効なエージェント全員が個別の値を持っていれば、共通の値は空でも構いません
