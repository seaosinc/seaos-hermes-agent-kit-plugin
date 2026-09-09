"""ワーカーのプロファイルを自前の mem0 サーバーへ向ける。

hermes memory setup は対話式でオプションを受け付けないため、設定ファイルを直接書く。
user_id を揃えることで、全ワーカーが同じ記憶を読む。
"""
import json
import pathlib
import sys

path, host, key, uid = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
cfg = json.loads(path.read_text()) if path.exists() else {}
cfg.update({"host": host, "api_key": key, "user_id": uid})
path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
