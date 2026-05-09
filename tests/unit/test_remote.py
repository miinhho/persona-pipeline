"""Tests for persona_mcp_store.remote (ASGI middleware + build_app)."""
from __future__ import annotations

import json as _json
from unittest.mock import MagicMock

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from persona_mcp_store import remote


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


def test_load_api_keys_raises_when_only_separators(monkeypatch):
    """Defensive: ',  ,  ' is non-empty after .strip() but yields empty key set."""
    monkeypatch.setenv("PERSONA_STORE_API_KEYS", "  ,  ,  ")
    with pytest.raises(RuntimeError, match="PERSONA_STORE_API_KEYS"):
        remote._load_api_keys()


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
    """Two tokens against the SAME middleware instance must use separate buckets."""

    class _SwitchingAuth(BaseHTTPMiddleware):
        """Pick token_key from `?token=` query param so we can hit one middleware
        with two distinct keys and verify per-key bucketing."""
        async def dispatch(self, request, call_next):
            request.state.token_key = request.query_params.get("token", "default")
            return await call_next(request)

    app = Starlette(
        routes=[Route("/x", _ok)],
        middleware=[
            Middleware(_SwitchingAuth),
            Middleware(remote._RateLimitMiddleware, per_minute=1),
        ],
    )
    c = TestClient(app)
    # Token A: 1 allowed, 2nd blocked
    assert c.get("/x?token=kA").status_code == 200
    assert c.get("/x?token=kA").status_code == 429
    # Token B against the same middleware instance: still allowed (own bucket)
    assert c.get("/x?token=kB").status_code == 200
    assert c.get("/x?token=kB").status_code == 429


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


def test_structured_log_emits_json_line_to_stderr(capsys):
    app = Starlette(
        routes=[Route("/x", _ok)],
        middleware=[
            Middleware(remote._RequestIdMiddleware),
            Middleware(_StubAuth, key="alpha-key"),
            Middleware(remote._StructuredLogMiddleware),
        ],
    )
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
            request.state.token_id = remote._token_id("kfull")
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
    assert record["token_id"] == remote._token_id("kfull")


@pytest.fixture
def korea_with_catalog_for_remote(tmp_path, monkeypatch):
    """Write a minimal Korea store + catalog under PERSONA_STORE_DATA_DIR=tmp_path."""
    import polars as pl
    from persona_mcp_store import store

    monkeypatch.setenv("PERSONA_STORE_DATA_DIR", str(tmp_path))
    rows = [
        {"country": "Korea", "uuid": "u", "region": "수도권", "age_gen": "청년",
         "sex": "여자", "age": 30, "province": "서울",
         "occupation": "사무원", "hobbies": ["독서"],
         "persona": "p", "professional_persona": "",
         "sports_persona": "", "arts_persona": "",
         "travel_persona": "", "culinary_persona": "", "family_persona": ""},
    ]
    pl.DataFrame(rows).write_parquet(tmp_path / "Korea.parquet", compression="zstd")
    store.write_catalog("Korea")
    return tmp_path


def _stub_mcp() -> MagicMock:
    """Stub FastMCP whose `streamable_http_app()` returns a tiny Starlette app
    with one POST /mcp endpoint, so we can exercise the middleware chain without
    booting the real server."""
    sub = Starlette(routes=[Route("/mcp", _ok, methods=["POST"])])
    mcp = MagicMock()
    mcp.streamable_http_app = MagicMock(return_value=sub)
    return mcp


def test_build_app_health_reachable_without_auth(monkeypatch, korea_with_catalog_for_remote):
    monkeypatch.setenv("PERSONA_STORE_API_KEYS", "k1")
    app = remote.build_app(_stub_mcp())
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "stores" in body and "Korea" in body["stores"]


def test_build_app_mcp_path_requires_auth(monkeypatch):
    monkeypatch.setenv("PERSONA_STORE_API_KEYS", "k1")
    app = remote.build_app(_stub_mcp())
    c = TestClient(app)
    r = c.post("/mcp", json={})
    assert r.status_code == 401


def test_build_app_mcp_path_succeeds_with_valid_token(monkeypatch):
    monkeypatch.setenv("PERSONA_STORE_API_KEYS", "k1")
    app = remote.build_app(_stub_mcp())
    c = TestClient(app)
    r = c.post("/mcp", json={}, headers={"authorization": "Bearer k1"})
    assert r.status_code == 200


def test_build_app_raises_when_api_keys_unset(monkeypatch):
    monkeypatch.delenv("PERSONA_STORE_API_KEYS", raising=False)
    with pytest.raises(RuntimeError, match="PERSONA_STORE_API_KEYS"):
        remote.build_app(_stub_mcp())


def test_build_app_health_returns_empty_stores_when_no_data_dir(tmp_path, monkeypatch):
    # PERSONA_STORE_DATA_DIR points to an empty directory
    monkeypatch.setenv("PERSONA_STORE_API_KEYS", "k1")
    monkeypatch.setenv("PERSONA_STORE_DATA_DIR", str(tmp_path))
    app = remote.build_app(_stub_mcp())
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json()["stores"] == []


def test_structured_log_captures_auth_rejection(capsys, monkeypatch):
    """401 from auth must still produce a JSON log line (abuse detection)."""
    monkeypatch.setenv("PERSONA_STORE_API_KEYS", "k1")
    app = remote.build_app(_stub_mcp())
    c = TestClient(app)
    # No Authorization header → 401
    r = c.post("/mcp", json={})
    assert r.status_code == 401
    err = capsys.readouterr().err
    json_lines = [ln for ln in err.splitlines() if ln.strip().startswith("{")]
    assert json_lines, f"no log line for 401; got: {err!r}"
    record = _json.loads(json_lines[-1])
    assert record["status"] == 401
    assert record["path"] == "/mcp"
    assert record["request_id"]


def test_structured_log_captures_rate_limit_rejection(capsys, monkeypatch):
    """429 from rate limit must still produce a JSON log line."""
    monkeypatch.setenv("PERSONA_STORE_API_KEYS", "k1")
    monkeypatch.setenv("PERSONA_STORE_RATE_LIMIT", "1")
    app = remote.build_app(_stub_mcp())
    c = TestClient(app)
    # First request: ok
    c.post("/mcp", json={}, headers={"authorization": "Bearer k1"})
    # Second: rate limited
    r2 = c.post("/mcp", json={}, headers={"authorization": "Bearer k1"})
    assert r2.status_code == 429
    err = capsys.readouterr().err
    json_lines = [ln for ln in err.splitlines() if ln.strip().startswith("{")]
    # Last line should be the 429 (the rejection)
    assert any(_json.loads(ln)["status"] == 429 for ln in json_lines), \
        f"no 429 log line; got: {err!r}"
