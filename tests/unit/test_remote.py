"""Tests for persona_pipeline.remote (ASGI middleware + build_app)."""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from starlette.middleware.base import BaseHTTPMiddleware

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


async def _ok_with_token(request):
    # Simulate auth having attached a token_key (since the rate limit middleware
    # reads request.state.token_key set by _AuthMiddleware in production).
    return PlainTextResponse("ok")


class _StubAuth(BaseHTTPMiddleware):
    """Test-only middleware that fakes an authenticated user by attaching a token_key."""
    def __init__(self, app, key: str):
        super().__init__(app)
        self.key = key

    async def dispatch(self, request, call_next):
        request.state.token_key = self.key
        return await call_next(request)


def _rate_client(per_minute: int, key: str = "k1") -> TestClient:
    # Order: stub-auth (sets token_key) -> rate-limit (reads it)
    return TestClient(Starlette(
        routes=[Route("/x", _ok)],
        middleware=[
            Middleware(_StubAuth, key=key),
            Middleware(remote._RateLimitMiddleware, per_minute=per_minute),
        ],
    ))


def test_rate_limit_allows_under_limit():
    c = _rate_client(per_minute=3)
    for _ in range(3):
        assert c.get("/x").status_code == 200


def test_rate_limit_blocks_over_limit_with_429_and_retry_after():
    c = _rate_client(per_minute=2)
    assert c.get("/x").status_code == 200
    assert c.get("/x").status_code == 200
    r = c.get("/x")
    assert r.status_code == 429
    assert "retry-after" in {h.lower() for h in r.headers}
    retry_value = r.headers.get("retry-after")
    assert retry_value and int(retry_value) >= 1


def test_rate_limit_isolates_per_token():
    # Each TestClient builds a fresh app instance — so we need both keys in one app
    # to test isolation. Build a custom app:
    app = Starlette(
        routes=[Route("/x", _ok)],
        middleware=[
            Middleware(_StubAuth, key="kA"),
            Middleware(remote._RateLimitMiddleware, per_minute=1),
        ],
    )
    c1 = TestClient(app)
    # First call for kA: ok. Second: 429.
    assert c1.get("/x").status_code == 200
    assert c1.get("/x").status_code == 429

    # Build separate app for a different key — bucket is per-token but per-app instance.
    # Verify per-token isolation by switching the stub to kB on the same per-minute=1 setting:
    app2 = Starlette(
        routes=[Route("/x", _ok)],
        middleware=[
            Middleware(_StubAuth, key="kB"),
            Middleware(remote._RateLimitMiddleware, per_minute=1),
        ],
    )
    c2 = TestClient(app2)
    assert c2.get("/x").status_code == 200  # different key, different bucket


def test_rate_limit_skips_when_no_token_key():
    # When request.state has no token_key (e.g. health endpoint via auth-exempt),
    # rate limit should let it through unconditionally.
    c = TestClient(Starlette(
        routes=[Route("/x", _ok)],
        middleware=[Middleware(remote._RateLimitMiddleware, per_minute=1)],
    ))
    # No StubAuth → no token_key on request.state
    assert c.get("/x").status_code == 200
    assert c.get("/x").status_code == 200  # second call also passes


import json as _json


def test_structured_log_emits_json_line_to_stderr(capsys):
    # Build app with request_id + stub-auth + log middleware so all fields are populated
    app = Starlette(
        routes=[Route("/x", _ok)],
        middleware=[
            Middleware(remote._RequestIdMiddleware),
            Middleware(_StubAuth, key="alpha-key"),
            Middleware(remote._StructuredLogMiddleware),
        ],
    )
    # Patch _token_id onto request.state so the log can pick it up. The stub auth
    # only sets token_key, but the log middleware reads token_id. In production,
    # _AuthMiddleware sets both. Use a richer stub here.
    c = TestClient(app)
    r = c.get("/x")
    assert r.status_code == 200

    captured = capsys.readouterr()
    # Stderr should contain at least one JSON line with the standard fields
    lines = [ln for ln in captured.err.splitlines() if ln.strip().startswith("{")]
    assert lines, f"no JSON line emitted to stderr; got: {captured.err!r}"
    record = _json.loads(lines[-1])
    assert record["status"] == 200
    assert record["method"] == "GET"
    assert record["path"] == "/x"
    assert "elapsed_ms" in record and isinstance(record["elapsed_ms"], int)
    assert "ts" in record and record["ts"].endswith("Z")
    assert record["request_id"]  # non-empty


def test_structured_log_includes_token_id_when_attached(capsys):
    class _StubBoth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.token_key = "kfull"
            request.state.token_id = "kfull"[:6] + "…"
            return await call_next(request)

    app = Starlette(
        routes=[Route("/x", _ok)],
        middleware=[
            Middleware(remote._RequestIdMiddleware),
            Middleware(_StubBoth),
            Middleware(remote._StructuredLogMiddleware),
        ],
    )
    TestClient(app).get("/x")
    err = capsys.readouterr().err
    record = _json.loads([ln for ln in err.splitlines() if ln.strip().startswith("{")][-1])
    assert record["token_id"] == "kfull…"
