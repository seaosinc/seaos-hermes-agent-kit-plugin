"""自前 mem0 サーバーと Hermes の mem0 プラグインの仕様差を吸収する。

プラグインは user_id を filters の中に入れて送る（Mem0 Platform の新仕様）。
一方 mem0-api-server の main.py はトップレベルの user_id しか見ないため、
検索が 500 "At least one of 'user_id', 'agent_id', or 'run_id' must be provided." で落ちる。

FastAPI のミドルウェアとして、filters にあるものをトップレベルへ引き上げる。
Hermes 本体には触らない（更新で消えるため）。
"""
import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_KEYS = ("user_id", "agent_id", "run_id")


class LiftFiltersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method != "POST":
            return await call_next(request)

        body = await request.body()
        if not body:
            return await call_next(request)

        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            return await call_next(request)

        filters = payload.get("filters") if isinstance(payload, dict) else None
        if isinstance(filters, dict):
            changed = False
            for key in _KEYS:
                if not payload.get(key) and filters.get(key):
                    payload[key] = filters[key]
                    changed = True
            if changed:
                new_body = json.dumps(payload).encode()
                # 読み直せるようにストリームを差し替える
                async def receive():
                    return {"type": "http.request", "body": new_body, "more_body": False}
                request._receive = receive
                request._body = new_body
                request.scope["headers"] = [
                    (k, str(len(new_body)).encode() if k == b"content-length" else v)
                    for k, v in request.scope["headers"]
                ]

        return await call_next(request)


def install(app):
    app.add_middleware(LiftFiltersMiddleware)


def patch_config():
    """main.py の DEFAULT_CONFIG を、環境変数で差し替える。

    main.py は LLM と埋め込みを OpenAI 固定で書いている。取り寄せ先が Bedrock のときは、
    LLM のモデル名と、埋め込み（プロバイダ・モデル・次元）を入れ替える必要がある。
    **変数が空なら何もしない**——OpenRouter のときの動きは変わらない。
    """
    import os

    import mem0

    original = mem0.Memory.from_config.__func__

    def from_config(cls, config_dict):
        config_dict = dict(config_dict)
        model = os.environ.get("MEM0_LLM_MODEL", "").strip()
        if model:
            llm = dict(config_dict.get("llm") or {})
            llm["config"] = {**(llm.get("config") or {}), "model": model}
            config_dict["llm"] = llm
        provider = os.environ.get("MEM0_EMBEDDER_PROVIDER", "").strip()
        if provider:
            dims = int(os.environ.get("MEM0_EMBEDDING_DIMS", "0") or 0) or None
            embedder = {"model": os.environ.get("MEM0_EMBEDDER_MODEL", "").strip() or None}
            if dims:
                embedder["embedding_dims"] = dims
            if os.environ.get("AWS_REGION"):
                embedder["aws_region"] = os.environ["AWS_REGION"]
            config_dict["embedder"] = {"provider": provider, "config": embedder}
            if dims:
                # **表の列の次元も揃える。** pgvector は既定で 1536 次元の列を作る
                store = dict(config_dict.get("vector_store") or {})
                store["config"] = {**(store.get("config") or {}), "embedding_model_dims": dims}
                config_dict["vector_store"] = store
        return original(cls, config_dict)

    mem0.Memory.from_config = classmethod(from_config)
