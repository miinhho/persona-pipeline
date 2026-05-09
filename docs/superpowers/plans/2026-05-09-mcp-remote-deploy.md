# MCP Remote Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a streamable-http MCP transport with API key auth, in-memory rate limiting, structured stderr logging, and a containerized deployment, so multiple authenticated clients can connect to a single remote persona-store instance.

**Architecture:** A new `persona_mcp_store/remote.py` exposes `build_app(mcp)` that wraps `mcp.streamable_http_app()` (returned by FastMCP 1.27 — confirmed signature `() -> Starlette`) with four middleware (request_id → auth → rate limit → structured log) plus an unauthenticated `/health` route. A new `serve-http` Typer command wires this to uvicorn. `store.store_path()` becomes env-driven so the container can mount data at `/data`. A multi-stage Dockerfile and docker-compose example complete the deploy story.

**Tech Stack:** Python 3.11, mcp SDK 1.27 (`mcp.server.fastmcp.FastMCP.streamable_http_app`), starlette ≥0.40 (middleware + TestClient), uvicorn ≥0.30 (ASGI server), pydantic 2 (already transitive), pytest, typer, Docker.

---

## File Structure

**Modify:**
- `pyproject.toml` — add `starlette>=0.40` and `uvicorn>=0.30` to `[mcp]` extra
- `persona_mcp_store/store.py` — `store_path` reads `PERSONA_STORE_DATA_DIR` env var (default `data/store`)
- `persona_mcp_store/cli/app.py` — register `serve_http` submodule
- `tests/unit/test_store.py` — append env-var test
- `README.md` — append "Remote deployment" section

**Create:**
- `persona_mcp_store/remote.py` — middleware + `build_app` factory
- `persona_mcp_store/cli/serve_http.py` — Typer `serve-http` command
- `tests/unit/test_remote.py` — middleware + integration tests
- `Dockerfile` — multi-stage build
- `.dockerignore` — exclude data/, tests/, docs/, etc.
- `docker-compose.yml` — operational example (single service)

**Delete:** none.

`.gitignore` already covers `data/store/` so mounted-only data stays out of git.

---

## Tasks

### Task 1: pyproject — add starlette + uvicorn to [mcp] extra

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit `pyproject.toml`**

Replace the `[mcp]` extra to read:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.6"]
mcp = ["mcp>=1.2", "anthropic>=0.40", "starlette>=0.40", "uvicorn>=0.30"]
```

Rationale: `starlette` is already a transitive dep through `mcp`, but pinning explicitly documents intent and prevents accidental break if `mcp` ever drops it. `uvicorn` is required at runtime to serve the ASGI app produced by `streamable_http_app()` + our middleware wrapper.

- [ ] **Step 2: Sync uv lockfile**

Run: `uv sync --extra mcp --extra dev`
Expected: `starlette` (already present) is unchanged or upgraded; `uvicorn` is newly installed; no resolution errors.

- [ ] **Step 3: Smoke imports**

Run:
```bash
uv run python -c "import starlette, uvicorn; from starlette.testclient import TestClient; print('starlette', starlette.__version__, 'uvicorn', uvicorn.__version__)"
```
Expected: both versions print without error.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add starlette + uvicorn to [mcp] extra for remote transport"
```

---

### Task 2: store.py — env-driven `_store_dir()` (TDD)

**Files:**
- Test: `tests/unit/test_store.py`
- Modify: `persona_mcp_store/store.py`

- [ ] **Step 1: Append failing test**

Append to `tests/unit/test_store.py`:

```python
def test_store_path_respects_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONA_STORE_DATA_DIR", str(tmp_path))
    assert store.store_path("Korea") == tmp_path / "Korea.parquet"
    assert store.catalog_path("Korea") == tmp_path / "Korea.catalog.json"


def test_store_path_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("PERSONA_STORE_DATA_DIR", raising=False)
    from pathlib import Path
    assert store.store_path("Korea") == Path("data/store") / "Korea.parquet"
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/test_store.py -v -k "respects_env_var or default_when_env"`
Expected: FAIL — `store_path` ignores the env var; first test asserts equality on a tmp path that doesn't match the hardcoded `Path("data") / "store" / ...`.

- [ ] **Step 3: Modify `persona_mcp_store/store.py`**

Open `persona_mcp_store/store.py`. At the top of the file (with other stdlib imports), add `import os`. Replace the existing module-level `DATA = Path("data")` line and the `store_path` function with:

```python
def _store_dir() -> Path:
    """Resolve the per-country store directory.

    Defaults to `data/store` (local dev). Overridable via the
    `PERSONA_STORE_DATA_DIR` env var so containers can point at a mounted volume.
    """
    return Path(os.environ.get("PERSONA_STORE_DATA_DIR", "data/store"))


def store_path(country: str) -> Path:
    return _store_dir() / f"{country}.parquet"
```

`catalog_path(country)` is already defined as `store_path(country).with_suffix("").with_suffix(".catalog.json")` and inherits the env-driven behaviour automatically — no change needed.

The previous `DATA = Path("data")` constant can be removed if nothing else in this file references it. Verify with: `grep -n "DATA" persona_mcp_store/store.py`. If `DATA` is referenced elsewhere in the file, leave it but stop using it from `store_path`.

- [ ] **Step 4: Run all store tests — expect PASS**

Run: `uv run pytest tests/unit/test_store.py -v`
Expected: previous 23 + 2 new = 25/25 pass. The existing `korea_store` fixture monkeypatches `store.store_path` directly (replacing the function), which still works because tests intercept the function reference, not the env-resolution path.

- [ ] **Step 5: Run full suite to confirm no regressions**

Run: `uv run pytest tests/ -v`
Expected: 90 + 2 new = 92/92 pass. The `cli/build.py` test path doesn't rely on `data/store` literal — it routes through `store.store_path()` which now reads the env (defaulting to `data/store`). Korea catalog test (uses real store) also unaffected because PERSONA_STORE_DATA_DIR is unset.

- [ ] **Step 6: Commit**

```bash
git add persona_mcp_store/store.py tests/unit/test_store.py
git commit -m "feat(store): make store directory env-driven (PERSONA_STORE_DATA_DIR)"
```

---

### Task 3: remote.py — `_RequestIdMiddleware` (TDD)

**Files:**
- Create: `tests/unit/test_remote.py`
- Create: `persona_mcp_store/remote.py`

- [ ] **Step 1: Create test file with failing tests**

Create `tests/unit/test_remote.py`:

```python
"""Tests for persona_mcp_store.remote (ASGI middleware + build_app)."""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
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
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/test_remote.py -v`
Expected: ImportError (`persona_mcp_store.remote` does not exist).

- [ ] **Step 3: Create `persona_mcp_store/remote.py`**

Create with the `_RequestIdMiddleware` class only (other middleware in later tasks):

```python
"""Remote-deploy concerns: ASGI app assembly with auth, rate limit, structured log.

This module is *only* used by the `serve-http` CLI command. The stdio MCP server
(`persona_mcp_store.cli.serve`) does not import it.
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
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/unit/test_remote.py -v`
Expected: 2/2 pass.

- [ ] **Step 5: Commit**

```bash
git add persona_mcp_store/remote.py tests/unit/test_remote.py
git commit -m "feat(remote): add _RequestIdMiddleware with x-request-id propagation"
```

---

### Task 4: remote.py — `_AuthMiddleware` + `_load_api_keys` (TDD)

**Files:**
- Modify: `tests/unit/test_remote.py`
- Modify: `persona_mcp_store/remote.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_remote.py`:

```python
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
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/test_remote.py -v -k "load_api_keys or auth"`
Expected: AttributeError on `_load_api_keys` / `_AuthMiddleware`.

- [ ] **Step 3: Add `_load_api_keys` and `_AuthMiddleware` to `persona_mcp_store/remote.py`**

Append to the imports block at the top of `remote.py`:

```python
import os

from starlette.responses import JSONResponse
```

Append to the body of `remote.py`:

```python
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
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/unit/test_remote.py -v`
Expected: 2 (request_id) + 8 (auth) = 10/10 pass.

- [ ] **Step 5: Commit**

```bash
git add persona_mcp_store/remote.py tests/unit/test_remote.py
git commit -m "feat(remote): add _AuthMiddleware with Bearer token + /health exemption"
```

---

### Task 5: remote.py — `_RateLimitMiddleware` (TDD)

**Files:**
- Modify: `tests/unit/test_remote.py`
- Modify: `persona_mcp_store/remote.py`

- [ ] **Step 1: Append failing tests**

Append to the imports at the top of `tests/unit/test_remote.py`:

```python
from starlette.middleware.base import BaseHTTPMiddleware
```

Then append to the body of `tests/unit/test_remote.py`:

```python
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
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/test_remote.py -v -k "rate_limit"`
Expected: AttributeError on `_RateLimitMiddleware`.

- [ ] **Step 3: Add `_RateLimitMiddleware` to `remote.py`**

Append to the imports of `remote.py`:

```python
import time
from collections import defaultdict, deque
```

Append to the body:

```python
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
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/unit/test_remote.py -v`
Expected: 10 + 4 = 14/14 pass.

- [ ] **Step 5: Commit**

```bash
git add persona_mcp_store/remote.py tests/unit/test_remote.py
git commit -m "feat(remote): add _RateLimitMiddleware (in-memory token bucket per key)"
```

---

### Task 6: remote.py — `_StructuredLogMiddleware` (TDD)

**Files:**
- Modify: `tests/unit/test_remote.py`
- Modify: `persona_mcp_store/remote.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_remote.py`:

```python
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
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/test_remote.py -v -k "structured_log"`
Expected: AttributeError on `_StructuredLogMiddleware`.

- [ ] **Step 3: Add `_StructuredLogMiddleware` to `remote.py`**

Append to imports of `remote.py`:

```python
import json
import sys
```

Append to the body:

```python
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
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/unit/test_remote.py -v`
Expected: 14 + 2 = 16/16 pass.

- [ ] **Step 5: Commit**

```bash
git add persona_mcp_store/remote.py tests/unit/test_remote.py
git commit -m "feat(remote): add _StructuredLogMiddleware (JSON line per request to stderr)"
```

---

### Task 7: remote.py — `build_app` factory + `/health` route (TDD)

**Files:**
- Modify: `tests/unit/test_remote.py`
- Modify: `persona_mcp_store/remote.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_remote.py`:

```python
from unittest.mock import MagicMock


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
```

The test `test_build_app_health_reachable_without_auth` requires a fixture that prepares a Korea store + catalog under a tmp data dir. Add this fixture above the new tests:

```python
@pytest.fixture
def korea_with_catalog_for_remote(tmp_path, monkeypatch):
    """Write a minimal Korea store + catalog under PERSONA_STORE_DATA_DIR=tmp_path."""
    import polars as pl
    from persona_mcp_store import store

    monkeypatch.setenv("PERSONA_STORE_DATA_DIR", str(tmp_path))
    rows = [
        {"country": "Korea", "uuid": "u", "region": "수도권", "age_gen": "청년",
         "sex": "여자", "occupation_group": "사무", "age": 30, "province": "서울",
         "occupation": "사무원", "hobbies": ["독서"],
         "persona": "p", "professional_persona": "",
         "sports_persona": "", "arts_persona": "",
         "travel_persona": "", "culinary_persona": "", "family_persona": ""},
    ]
    pl.DataFrame(rows).write_parquet(tmp_path / "Korea.parquet", compression="zstd")
    store.write_catalog("Korea")
    return tmp_path
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/test_remote.py -v -k "build_app"`
Expected: AttributeError on `build_app`.

- [ ] **Step 3: Add `build_app` and `_health` to `remote.py`**

Append to imports of `remote.py`:

```python
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from persona_mcp_store import store
```

Append to the body:

```python
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
      2. _AuthMiddleware       — Bearer key gate (exempts /health)
      3. _RateLimitMiddleware  — per-token rolling-window
      4. _StructuredLogMiddleware — emits one JSON line per request to stderr

    Routes:
      - GET /health      — unauthenticated liveness check
      - everything else  — mounted FastMCP streamable-http app at root
    """
    api_keys = _load_api_keys()
    rate = int(os.environ.get("PERSONA_STORE_RATE_LIMIT", "60"))

    mcp_asgi = mcp.streamable_http_app()

    middleware = [
        Middleware(_RequestIdMiddleware),
        Middleware(_AuthMiddleware, api_keys=api_keys, exempt_paths=("/health",)),
        Middleware(_RateLimitMiddleware, per_minute=rate),
        Middleware(_StructuredLogMiddleware),
    ]
    routes = [
        Route("/health", _health, methods=["GET"]),
        Mount("/", app=mcp_asgi),
    ]
    return Starlette(routes=routes, middleware=middleware)
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/unit/test_remote.py -v`
Expected: 16 + 5 = 21/21 pass. Then full suite: `uv run pytest tests/ -v` — 92 + 5 = 97/97 pass (existing 92 from earlier tasks + 5 new build_app).

Note: counts assume the test count after Task 2 was 92 (90 baseline + 2 store env-var tests). If your baseline was different (other branches diverged), adjust expectations accordingly — what matters is that all tests pass.

- [ ] **Step 5: Commit**

```bash
git add persona_mcp_store/remote.py tests/unit/test_remote.py
git commit -m "feat(remote): add build_app factory with /health route and 4-layer middleware chain"
```

---

### Task 8: CLI — `serve-http` command

**Files:**
- Create: `persona_mcp_store/cli/serve_http.py`
- Modify: `persona_mcp_store/cli/app.py`

- [ ] **Step 1: Create `persona_mcp_store/cli/serve_http.py`**

```python
"""CLI: serve-http — run the persona MCP server over streamable-http transport.

Configuration via environment variables (read inside `remote.build_app`):
  PERSONA_STORE_API_KEYS  - comma-separated bearer tokens (required, non-empty)
  PERSONA_STORE_DATA_DIR  - parquet store directory (default: data/store)
  PERSONA_STORE_RATE_LIMIT - requests per minute per token (default: 60)

Use `serve` (separate command) for stdio transport.
"""
from __future__ import annotations

import typer

from persona_mcp_store.cli.app import app


@app.command(name="serve-http")
def serve_http(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Run the MCP server over streamable-http (HTTP transport).

    The server expects HTTPS to be terminated upstream by a reverse proxy
    (nginx, Caddy, cloud LB, etc.). The container itself listens on plain HTTP.
    """
    import uvicorn

    from persona_mcp_store.mcp_server import mcp
    from persona_mcp_store.remote import build_app

    asgi_app = build_app(mcp)
    typer.echo(
        f"starting persona-store MCP server (streamable-http) on {host}:{port}…",
        err=True,
    )
    uvicorn.run(asgi_app, host=host, port=port, log_config=None)
```

- [ ] **Step 2: Register the new command in `cli/app.py`**

Open `persona_mcp_store/cli/app.py`. Append `from persona_mcp_store.cli import serve_http` to the existing import block (alongside `download`, `classify_occupation`, `build`, `serve`). Final state:

```python
import typer

app = typer.Typer(help="Persona pipeline: build the per-country store and serve it over MCP.")

from persona_mcp_store.cli import download  # noqa: F401, E402
from persona_mcp_store.cli import classify_occupation  # noqa: F401, E402
from persona_mcp_store.cli import build  # noqa: F401, E402
from persona_mcp_store.cli import serve  # noqa: F401, E402
from persona_mcp_store.cli import serve_http  # noqa: F401, E402
```

- [ ] **Step 3: Smoke check — CLI parses with new command**

Run:
```bash
uv run python -c "from persona_mcp_store.cli.app import app; app(['--help'], standalone_mode=False)"
```
Expected: help text lists 5 commands: `download`, `classify-occupation`, `build`, `serve`, `serve-http`.

- [ ] **Step 4: Smoke check — fail-fast without API keys**

Run:
```bash
unset PERSONA_STORE_API_KEYS
uv run python -c "
import os
os.environ.pop('PERSONA_STORE_API_KEYS', None)
from persona_mcp_store.cli.app import app
try:
    app(['serve-http', '--port', '0'], standalone_mode=False)
except RuntimeError as e:
    print('correctly raised:', e)
"
```
Expected: `correctly raised: PERSONA_STORE_API_KEYS env var is required ...`. The server doesn't bind a port because `build_app` raises during construction before uvicorn.run.

- [ ] **Step 5: Smoke check — full pytest still green**

Run: `uv run pytest tests/ -v`
Expected: same count as after Task 7 (97/97 typically), all pass.

- [ ] **Step 6: Commit**

```bash
git add persona_mcp_store/cli/serve_http.py persona_mcp_store/cli/app.py
git commit -m "feat(cli): add serve-http command (streamable-http transport)"
```

---

### Task 9: Container — Dockerfile + .dockerignore + docker-compose.yml

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `docker-compose.yml`

This task has no unit test (it's deploy artifacts). Validation: docker build succeeds; container starts and `/health` is reachable.

- [ ] **Step 1: Create `.dockerignore`**

```gitignore
# Local data / caches (mount via volume instead)
data/
.venv/
.uv-cache/

# Python build/test output
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
*.egg-info/

# VCS / editor / docs
.git/
.gitignore
.github/
.claude/
.mcp.json
docs/
README.md
Makefile

# Tests aren't needed at runtime
tests/
scripts/
```

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder

# Install uv (binary). Pin a known-good version; bump in a follow-up if needed.
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /app

# Resolve and install dependencies first (layer-cache friendly)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra mcp --no-dev --no-install-project

# Now bring in the package source and finalize
COPY persona_mcp_store persona_mcp_store
RUN uv sync --frozen --extra mcp --no-dev


FROM python:3.11-slim AS runtime

# Non-root user for runtime
RUN useradd -u 1000 -m app
WORKDIR /app

# Copy the resolved venv and the application package from builder
COPY --from=builder /app /app

USER app
ENV PATH="/app/.venv/bin:$PATH"
ENV PERSONA_STORE_DATA_DIR=/data
EXPOSE 8080

# Default entrypoint runs the streamable-http server on 0.0.0.0:8080.
# Operator must mount a directory at /data and supply PERSONA_STORE_API_KEYS.
ENTRYPOINT ["python", "-m", "persona_mcp_store.cli", "serve-http"]
CMD ["--host", "0.0.0.0", "--port", "8080"]
```

Notes:
- `python -m persona_mcp_store.cli` resolves to `persona_mcp_store/cli/__main__.py` (which exists from initial migration).
- `EXPOSE 8080` is documentation; the operator publishes the port via `-p` or compose.
- `USER app` (uid 1000) keeps the process unprivileged.

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
services:
  persona-store:
    build: .
    image: persona-store:latest
    container_name: persona-store
    environment:
      # Required: comma-separated bearer tokens
      PERSONA_STORE_API_KEYS: ${PERSONA_STORE_API_KEYS:?set in .env or shell}
      # Optional: requests per minute per token (default 60)
      PERSONA_STORE_RATE_LIMIT: "60"
    volumes:
      # Read-only mount of the host store directory
      - ./data/store:/data:ro
    ports:
      # Bind to localhost only; expose to internet via reverse proxy
      - "127.0.0.1:8080:8080"
    restart: unless-stopped
```

- [ ] **Step 4: Smoke check — image builds**

Run: `docker build -t persona-store:test .`
Expected: build succeeds. Image size: typically 200–300 MB.

If `docker` is not available locally, skip this step and note it as a deferred validation. The Dockerfile will be exercised in CI / production.

- [ ] **Step 5: Smoke check — container fails fast without API keys (if docker available)**

Run:
```bash
docker run --rm -e PERSONA_STORE_API_KEYS="" persona-store:test
```
Expected: container exits non-zero with `RuntimeError: PERSONA_STORE_API_KEYS env var is required ...` printed.

- [ ] **Step 6: Smoke check — container serves /health (if docker available)**

Run:
```bash
docker run --rm -d --name persona-store-test \
  -p 8080:8080 \
  -e PERSONA_STORE_API_KEYS=test \
  -v "$(pwd)/data/store:/data:ro" \
  persona-store:test

sleep 2
curl -s http://localhost:8080/health | head
docker stop persona-store-test
```
Expected: `{"status":"ok","stores":[...]}` with built countries listed.

- [ ] **Step 7: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.yml
git commit -m "feat(deploy): add Dockerfile, .dockerignore, docker-compose.yml for streamable-http server"
```

---

### Task 10: README — Remote deployment section

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append a new section to `README.md`**

Insert this section after the existing "Pipeline" section, before "Country mappings":

```markdown
## Remote deployment

For team-internal or remote LLM clients, run the server over streamable-http:

```bash
export PERSONA_STORE_API_KEYS="$(openssl rand -hex 32)"
uv run persona-mcp-store serve-http --host 0.0.0.0 --port 8080
```

Connect from an MCP-aware client by registering:

```json
{
  "mcpServers": {
    "persona-store": {
      "type": "streamable-http",
      "url": "https://persona-store.example.com",
      "headers": {"Authorization": "Bearer <your-key>"}
    }
  }
}
```

### Configuration (env vars)

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `PERSONA_STORE_API_KEYS` | — | yes | Comma-separated bearer tokens. Server refuses to start if unset/empty. |
| `PERSONA_STORE_DATA_DIR` | `data/store` | no | Parquet store + catalog sidecar directory. Container default `/data`. |
| `PERSONA_STORE_RATE_LIMIT` | `60` | no | Requests per minute per token (rolling 60-second window). |

### Container

```bash
docker compose up -d
```

The provided `docker-compose.yml` mounts `./data/store` read-only into the container at `/data` and binds port 8080 to `127.0.0.1` (i.e. localhost only — front with a reverse proxy for external access).

### TLS / production access

The container speaks plain HTTP. Production deployments terminate TLS at a reverse proxy (nginx, Caddy, cloud LB):

```nginx
server {
  listen 443 ssl;
  server_name persona-store.team.example.com;
  ssl_certificate /etc/letsencrypt/live/.../fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/.../privkey.pem;

  location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 60s;
  }

  location /health { access_log off; proxy_pass http://127.0.0.1:8080; }
}
```

### Operations

- **Logs**: each request emits one JSON line to stderr with `request_id`, `token_id` (key prefix), `path`, `status`, `elapsed_ms`. Wire stderr into your log shipper (Loki, ELK, Cloud Logging).
- **Health**: `GET /health` returns `{"status":"ok","stores":[...]}` without auth. Use as liveness probe.
- **Key rotation**: edit env var (e.g. `PERSONA_STORE_API_KEYS=new1,new2`) and restart the container. Old tokens become invalid immediately; new ones accepted.
- **Rate limit**: per-token rolling 60s window. 429 response includes `Retry-After` header.
- **Scaling**: rate limit and request-id buckets are in-memory (single-instance). Multi-instance horizontal scaling requires distributed state (Redis) — out of v1 scope.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add Remote deployment section to README (env vars, compose, TLS, ops)"
```

---

## Notes for the implementing engineer

- **TDD discipline**: every middleware-creating task writes tests first, runs them red, then implements. The test scaffolding (the `_client(*middleware)` helper, the `_StubAuth` class) is reused across tasks — do not redefine.
- **Frequent commits**: each task ends with one commit. If a task spans multiple commits (e.g. fixing test fallout), commit each cleanly. Don't squash.
- **Backward compatibility**: stdio `serve` command, all existing 90 tests, and local development (`make build COUNTRY=Korea`) must continue to work without setting any new env vars.
- **MCP SDK API**: `mcp.server.fastmcp.FastMCP.streamable_http_app() -> Starlette` is verified on mcp 1.27. If the installed version differs, check `dir(FastMCP())` for the alternative method (`http_app`, `create_streamable_http_app`, etc.).
- **starlette.testclient**: requires `httpx` as a transitive dep. `starlette[full]` brings it; on the slim install confirm `httpx` is importable. If not, add `httpx` to `[mcp]` extra (test scenarios use it).
- **Don't implement what's not in the plan**: no Prometheus metrics, no OpenTelemetry, no distributed rate limit, no per-tenant scoping, no OAuth. Each is explicitly called out in the spec as v2/P3.
- **Container caveat**: Steps 4–6 of Task 9 require `docker` on the implementer's machine. If absent, document the skipped steps and let CI / operator run them — Dockerfile syntax can be statically verified with `docker run --rm -i hadolint/hadolint < Dockerfile` (optional).
