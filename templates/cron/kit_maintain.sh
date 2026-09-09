#!/bin/bash
# 保守一式（反映 → 配布 → 掃除 → 検証）。doctor が重いので日次で回す。
# 問題があったときだけ喋る。
set -u
out=$("$HOME/.local/bin/hermes-kit" maintain 2>&1)
rc=$?
if [ $rc -ne 0 ]; then
  printf '%s\n' "hermes-kit maintain が問題を検出した:"
  printf '%s\n' "$out" | grep -E '✗|★' | head -20
fi
# 物理削除が起きたときは残しておきたい
printf '%s\n' "$out" | grep -E '件を物理削除' || true
exit 0
