"""Remote-deploy concerns: ASGI app assembly with auth, rate limit, structured log.

This module is *only* used by the `serve-http` CLI command. The stdio MCP server
(`persona_pipeline.cli.serve`) does not import it.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from collections import defaultdict, deque

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from persona_pipeline import store


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


class _RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory token-bucket rate limit per Bearer key.

    Single-instance: the bucket dict lives in this process. Scaling horizontally
    requires moving to Redis (out of v1 scope). When `request.state.token_key` is
    absent (e.g. on auth-exempt paths like /health), the request is passed through.
    """

    def __init__(self, app, per_minute: int):
        super().__init__(app)
        self.per_minute = per_minute
        self.window_s = 60.0
        # token_key -> deque of monotonic timestamps within the rolling window
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request, call_next):
        key = getattr(request.state, "token_key", None)
        if key is None:
            return await call_next(request)
        now = time.monotonic()
        bucket = self._buckets[key]
        cutoff = now - self.window_s
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.per_minute:
            retry = int(self.window_s - (now - bucket[0])) + 1
            return JSONResponse(
                {"error": f"rate limit exceeded: {self.per_minute}/min"},
                status_code=429,
                headers={"retry-after": str(retry)},
            )
        bucket.append(now)
        return await call_next(request)


class _StructuredLogMiddleware(BaseHTTPMiddleware):
    """Emit one JSON line per request to stderr after the response is produced.

    Fields: ts (UTC ISO Z), level, request_id, token_id (or null), method, path,
    status, elapsed_ms. Operators wire stderr into log shippers (Loki/ELK).
    """

    async def dispatch(self, request, call_next):
        t0 = time.monotonic()
        response = await call_next(request)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": "info",
            "request_id": getattr(request.state, "request_id", None),
            "token_id": getattr(request.state, "token_id", None),
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "elapsed_ms": elapsed_ms,
        }
        print(json.dumps(record, ensure_ascii=False), file=sys.stderr, flush=True)
        return response


async def _health(request: Request) -> Response:
    """Liveness/readiness check. Lists built country stores discovered via sidecars."""
    countries: list[str] = []
    store_dir = store.store_path("_").parent
    if store_dir.exists():
        countries = sorted(
            p.name.replace(".catalog.json", "")
            for p in store_dir.glob("*.catalog.json")
        )
    return JSONResponse({"status": "ok", "stores": countries})


def build_app(mcp) -> Starlette:
    """Assemble the deployable ASGI app.

    Layers (outer-to-inner):
      1. _RequestIdMiddleware — ensures every request carries an id
      2. _StructuredLogMiddleware — emits one JSON line per request to stderr
         (placed here so it sees 401/429 short-circuit responses from auth/rate)
      3. _AuthMiddleware       — Bearer key gate (exempts /health)
      4. _RateLimitMiddleware  — per-token rolling-window

    Routes:
      - GET /health      — unauthenticated liveness check
      - everything else  — mounted FastMCP streamable-http app at root
    """
    api_keys = _load_api_keys()
    rate = int(os.environ.get("PERSONA_STORE_RATE_LIMIT", "60"))

    mcp_asgi = mcp.streamable_http_app()

    middleware = [
        Middleware(_RequestIdMiddleware),
        Middleware(_StructuredLogMiddleware),
        Middleware(_AuthMiddleware, api_keys=api_keys, exempt_paths=("/health",)),
        Middleware(_RateLimitMiddleware, per_minute=rate),
    ]
    routes = [
        Route("/health", _health, methods=["GET"]),
        Mount("/", app=mcp_asgi),
    ]
    return Starlette(routes=routes, middleware=middleware)
