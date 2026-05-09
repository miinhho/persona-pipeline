"""Tests for persona_pipeline.remote (ASGI middleware + build_app)."""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from persona_pipeline import remote


async def _ok(request):
    return PlainTextResponse("ok")


def _client(*middleware: Middleware) -> TestClient:
    """Build a TestClient over a single-route app wrapped in given middleware."""
    return TestClient(Starlette(routes=[Route("/x", _ok)], middleware=list(middleware)))


def test_request_id_generated_when_missing():
    c = _client(Middleware(remote._RequestIdMiddleware))
    r = c.get("/x")
    assert r.status_code == 200
    rid = r.headers.get("x-request-id")
    assert rid and len(rid) >= 8


def test_request_id_preserved_when_provided():
    c = _client(Middleware(remote._RequestIdMiddleware))
    r = c.get("/x", headers={"x-request-id": "client-supplied-abc123"})
    assert r.headers["x-request-id"] == "client-supplied-abc123"
