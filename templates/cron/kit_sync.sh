#!/bin/bash
# 規約の反映と配布だけを回す（軽い）。cron の --no-agent で走るので、
# **標準出力に出したものがそのまま通知される。** 変化があったときだけ喋る。
set -u
KIT="$HOME/.local/bin/hermes-kit"

# **手元で直す環境と、git で受け取る環境がある。**
# 手元（開発機）は templates/ を直接編集するので、pull するものが無い。
# 配られた箱（サーバ）は git だけが変更の入口なので、ここで取り込まないと
# 規約が永遠に古いままになる。**リモートがあって、手元に変更が無いときだけ**引く。
root=$(cd "$(dirname "$(readlink -f "$KIT")")/.." && pwd)
if git -C "$root" remote | grep -q . && [ -z "$(git -C "$root" status --porcelain)" ]; then
  before=$(git -C "$root" rev-parse HEAD)
  pull=$(git -C "$root" pull --ff-only 2>&1) || {
    printf '%s\n' "git pull が失敗した（手で見ること）:"
    printf '%s\n' "$pull" | tail -5
  }
  after=$(git -C "$root" rev-parse HEAD)
  [ "$before" != "$after" ] && \
    printf '%s\n' "キットを更新した: $(git -C "$root" log --oneline "$before..$after" | head -5)"
fi

out=$("$KIT" update 2>&1) || {
  printf '%s\n' "hermes-kit update が失敗した:"
  printf '%s\n' "$out" | tail -20
  exit 0
}
# 「+ 名前」「- 名前」の行があれば何かが変わっている
changed=$(printf '%s\n' "$out" | grep -E '^  [+-] ' || true)
[ -n "$changed" ] && { printf '%s\n' "規約を配布した:"; printf '%s\n' "$changed"; }
exit 0
