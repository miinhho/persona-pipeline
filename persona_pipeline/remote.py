"""Remote-deploy concerns: ASGI app assembly with auth, rate limit, structured log.

This module is *only* used by the `serve-http` CLI command. The stdio MCP server
(`persona_pipeline.cli.serve`) does not import it.
"""
from __future__ import annotations

import os
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class _RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach an x-request-id to each request and echo it back in the response.

    If the client sends `x-request-id`, preserve it; otherwise generate one.
    Stored on `request.state.request_id` for downstream middleware/handlers.
    """

    async def dispatch(self, request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response


def _load_api_keys() -> set[str]:
    """Read comma-separated bearer tokens from `PERSONA_STORE_API_KEYS`.

    Raises RuntimeError if unset or empty after trimming — fail fast, never run
    a remote server with no auth.
    """
    raw = os.environ.get("PERSONA_STORE_API_KEYS", "").strip()
    if not raw:
        raise RuntimeError(
            "PERSONA_STORE_API_KEYS env var is required (comma-separated tokens)."
        )
    keys = {k.strip() for k in raw.split(",") if k.strip()}
    if not keys:
        raise RuntimeError(
            "PERSONA_STORE_API_KEYS env var is required (comma-separated tokens)."
        )
    return keys


def _token_id(key: str) -> str:
    """Short, non-sensitive identifier for logging. Never the full key."""
    return (key[:6] + "…") if len(key) > 6 else key


class _AuthMiddleware(BaseHTTPMiddleware):
    """Bearer token auth via `Authorization: Bearer <key>`.

    Paths in `exempt_paths` bypass auth (used for `/health`). On success, attaches
    `request.state.token_key` (full key, in-memory only) and `request.state.token_id`
    (short prefix for logging).
    """

    def __init__(self, app, api_keys: set[str], exempt_paths: tuple[str, ...] = ()):
        super().__init__(app)
        self.api_keys = api_keys
        self.exempt_paths = exempt_paths

    async def dispatch(self, request, call_next):
        if request.url.path in self.exempt_paths:
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                {"error": "missing or malformed Authorization header"}, status_code=401
            )
        key = auth[len("Bearer "):].strip()
        if key not in self.api_keys:
            return JSONResponse({"error": "invalid token"}, status_code=401)
        request.state.token_key = key
        request.state.token_id = _token_id(key)
        return await call_next(request)
