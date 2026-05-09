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


def test_load_api_keys_raises_when_env_unset(monkeypatch):
    monkeypatch.delenv("PERSONA_STORE_API_KEYS", raising=False)
    with pytest.raises(RuntimeError, match="PERSONA_STORE_API_KEYS"):
        remote._load_api_keys()


def test_load_api_keys_raises_when_env_empty(monkeypatch):
    monkeypatch.setenv("PERSONA_STORE_API_KEYS", "   ")
    with pytest.raises(RuntimeError, match="PERSONA_STORE_API_KEYS"):
        remote._load_api_keys()


def test_load_api_keys_parses_comma_separated(monkeypatch):
    monkeypatch.setenv("PERSONA_STORE_API_KEYS", "alpha, beta ,gamma")
    assert remote._load_api_keys() == {"alpha", "beta", "gamma"}


def _auth_client(api_keys: set[str], exempt=("/health",)) -> TestClient:
    return _client(Middleware(remote._AuthMiddleware, api_keys=api_keys, exempt_paths=exempt))


def test_auth_blocks_missing_authorization_header():
    c = _auth_client({"k1"})
    r = c.get("/x")
    assert r.status_code == 401
    assert "missing" in r.json()["error"].lower() or "authoriz" in r.json()["error"].lower()


def test_auth_blocks_malformed_authorization_header():
    c = _auth_client({"k1"})
    r = c.get("/x", headers={"authorization": "Basic abc"})
    assert r.status_code == 401


def test_auth_blocks_unknown_token():
    c = _auth_client({"k1"})
    r = c.get("/x", headers={"authorization": "Bearer not-the-key"})
    assert r.status_code == 401


def test_auth_passes_valid_token():
    c = _auth_client({"k1"})
    r = c.get("/x", headers={"authorization": "Bearer k1"})
    assert r.status_code == 200
    assert r.text == "ok"


def test_auth_exempts_health_path():
    # Build app with /health route and middleware exempting it
    app = Starlette(
        routes=[Route("/health", _ok), Route("/x", _ok)],
        middleware=[Middleware(remote._AuthMiddleware, api_keys={"k1"}, exempt_paths=("/health",))],
    )
    c = TestClient(app)
    assert c.get("/health").status_code == 200  # no auth needed
    assert c.get("/x").status_code == 401       # /x still requires auth
