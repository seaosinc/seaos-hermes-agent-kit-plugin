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
