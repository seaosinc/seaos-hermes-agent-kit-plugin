"""コンテナ起動時に compat のミドルウェアを差し込む。

main.py を書き換えずに済ませるため、FastAPI のインスタンス生成をフックする。
"""
import fastapi

_orig_init = fastapi.FastAPI.__init__


def _patched_init(self, *args, **kwargs):
    _orig_init(self, *args, **kwargs)
    try:
        import compat
        compat.install(self)
    except Exception:  # 差し込めなくても本体は動かす
        pass


fastapi.FastAPI.__init__ = _patched_init

# main.py は読み込み時に設定を組んで Memory を作る。その前に差し替えの口を仕込む
try:
    import compat

    compat.patch_config()
except Exception:  # 差し込めなくても本体は動かす（既定の設定で起動する）
    pass
