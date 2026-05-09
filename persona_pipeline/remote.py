"""Remote-deploy concerns: ASGI app assembly with auth, rate limit, structured log.

This module is *only* used by the `serve-http` CLI command. The stdio MCP server
(`persona_pipeline.cli.serve`) does not import it.
"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware


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
