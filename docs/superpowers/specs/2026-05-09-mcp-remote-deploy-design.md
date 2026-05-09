# MCP remote deploy — streamable-http transport, API key auth, container, rate limit, structured logging

**Status**: design
**Date**: 2026-05-09
**Author**: brainstorm 결과
**Predecessor**: `2026-05-09-mcp-ux-upgrade-design.md` (catalog resources + observability + error UX 완료된 stdio MCP server)

## Problem

현재 MCP server는 stdio transport 전용이다. Claude Desktop/Claude Code 같은 로컬 클라이언트가 같은 머신에서 process를 spawn해 사용하는 시나리오만 지원한다.

팀 안에서 "한 곳에 띄워둔 server를 여러 클라이언트가 원격으로 붙어 쓴다"는 시나리오는 다음이 빠져 있어 불가능:

- transport: stdio는 stdin/stdout 점유 — network 호출 불가
- authentication: 누가 호출하는지 식별·인증 없음
- 데이터 mount: store parquet (1GB×N국가)이 코드와 같은 디렉토리 가정. 컨테이너화 시 이미지 비대화
- 운영 가시성: stdio MCP의 `notifications/message`는 client side로만 가고 server stderr에는 호출 흔적 없음 — 다중 client 환경에서 디버깅·운영 불가
- abuse 방지: 한 client가 1초에 100번 1M-row scan 폭주시키면 server 죽음

## Goal

같은 LAN/VPN/internet 어디든 한 번 띄운 persona-store MCP server에 다수의 인증된 클라이언트가 streamable-http로 붙어 동일한 4 tool + 2 resource를 사용하게 한다. 운영자는 컨테이너로 배포하고, 호출 로그를 stderr에서 JSON line으로 수집하며, 폭주를 token-bucket으로 막는다.

## Non-goals

- **TLS 종료**: server 코드 안에서 처리하지 않음. reverse proxy/cloud LB(nginx, Caddy, ALB 등)에 위임. 컨테이너에 인증서 박지 않음.
- **OAuth 2.1**: MCP Authorization draft 기반 OAuth는 클라이언트 구현체 성숙도 균일하지 않은 시점이라 v1에서는 단순 API key bearer.
- **Per-tenant 권한 분리**: 모든 키 = 모든 country + 모든 tool 접근. 키별 country 제한·scope는 P3 이후.
- **Distributed rate limiting** (Redis 등): 단일 인스턴스 가정. 다중 인스턴스 scale-out은 P3.
- **OpenTelemetry tracing / Prometheus metrics**: P3 이후. v1은 stderr JSON log만.
- **Key lifecycle 관리** (발급/회수 API, hash 저장): env var 평문 + restart로 갱신. 외부 secret manager 통합은 운영자 자유.
- **Multi-instance load balancing**: 단일 docker container를 한 곳에 띄우는 게 v1. HA·autoscaling은 별도 spec.

## Architecture

```
                       ┌──────────────────────────────┐
                       │  reverse proxy / cloud LB    │
                       │  (nginx / Caddy / ALB)       │
HTTPS clients ──────►  │  - TLS termination           │
                       │  - optional ingress rules    │
                       └──────────────┬───────────────┘
                                      │ HTTP (LAN/cluster)
                                      ▼
                       ┌──────────────────────────────┐
                       │  persona-store container     │
                       │                              │
                       │  ┌────────────────────────┐  │
                       │  │ Starlette ASGI app     │  │
                       │  │  ↓ middleware chain    │  │
                       │  │  - request_id          │  │
                       │  │  - api_key auth        │  │
                       │  │  - rate limit          │  │
                       │  │  - structured log      │  │
                       │  │  ↓                     │  │
                       │  │ FastMCP                │  │
                       │  │  - 4 tools             │  │
                       │  │  - 2 resources         │  │
                       │  │  - GET /health         │  │
                       │  └────────────────────────┘  │
                       │           │                  │
                       │           ▼                  │
                       │   /data (read-only mount)    │
                       └──────────────┬───────────────┘
                                      │ bind mount
                                      ▼
                       host: ./data/store/{country}.parquet
                                       {country}.catalog.json
```

### Layered concerns

| Layer | Owns |
|---|---|
| reverse proxy | TLS, optional path-based routing, optional IP allowlist |
| container | streamable-http transport, auth, rate limit, structured log, MCP server |
| host filesystem / volume | parquet store + catalog sidecars (read-only mount into container) |

## Components

### 1. CLI: new `serve-http` command

`persona_mcp_store/cli/serve_http.py` (new):

```python
import os
import typer

from persona_mcp_store.cli.app import app


@app.command(name="serve-http")
def serve_http(
    host: str = "0.0.0.0",
    port: int = 8080,
) -> None:
    """Run the MCP server over streamable-http transport.

    Reads configuration from environment variables:
      PERSONA_STORE_API_KEYS  - comma-separated bearer tokens (required, non-empty)
      PERSONA_STORE_DATA_DIR  - parquet store directory (default: data/store)
      PERSONA_STORE_RATE_LIMIT - requests per minute per token (default: 60)
      LOG_LEVEL               - info | debug | warning (default: info)
    """
    from persona_mcp_store.mcp_server import mcp
    from persona_mcp_store.remote import build_app
    import uvicorn

    asgi_app = build_app(mcp)
    uvicorn.run(asgi_app, host=host, port=port, log_config=None)
```

The existing `serve` (stdio) stays untouched.

### 2. New module: `persona_mcp_store/remote.py`

Wraps FastMCP's streamable-http app with auth + rate limit + logging middleware. Exposes a single factory `build_app(mcp) -> ASGI app`.

```python
"""Remote-deploy concerns: ASGI app assembly with auth, rate limit, structured log."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Iterable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware

from persona_mcp_store import store


def _load_api_keys() -> set[str]:
    raw = os.environ.get("PERSONA_STORE_API_KEYS", "").strip()
    if not raw:
        raise RuntimeError(
            "PERSONA_STORE_API_KEYS env var is required (comma-separated tokens)."
        )
    return {k.strip() for k in raw.split(",") if k.strip()}


def _token_id(key: str) -> str:
    """Short identifier for logging — never the full key."""
    return key[:6] + "…"


class _RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response


class _AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_keys: set[str], exempt_paths: tuple[str, ...] = ("/health",)):
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
    """In-memory token bucket per Bearer key. Single-instance only."""

    def __init__(self, app, per_minute: int):
        super().__init__(app)
        self.per_minute = per_minute
        self.window_s = 60.0
        # token_key -> deque of timestamps within the current window
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request, call_next):
        key = getattr(request.state, "token_key", None)
        if key is None:
            return await call_next(request)  # unauthenticated path (health)
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
    countries = []
    store_dir = store.store_path("_").parent
    if store_dir.exists():
        countries = sorted(p.stem.replace(".catalog", "") for p in store_dir.glob("*.catalog.json"))
    return JSONResponse({"status": "ok", "stores": countries})


def build_app(mcp) -> Starlette:
    """Assemble the ASGI app: health route + FastMCP streamable-http app + middlewares."""
    api_keys = _load_api_keys()
    rate = int(os.environ.get("PERSONA_STORE_RATE_LIMIT", "60"))

    mcp_asgi = mcp.streamable_http_app()

    middleware = [
        Middleware(_RequestIdMiddleware),
        Middleware(_AuthMiddleware, api_keys=api_keys),
        Middleware(_RateLimitMiddleware, per_minute=rate),
        Middleware(_StructuredLogMiddleware),
    ]
    routes = [
        Route("/health", _health, methods=["GET"]),
        Mount("/", app=mcp_asgi),
    ]
    return Starlette(routes=routes, middleware=middleware)
```

Notes:
- `mcp.streamable_http_app()` is FastMCP's standard ASGI app builder. Verify the exact method name on the installed mcp version during implementation; if it differs (e.g. `mcp.create_streamable_http_app()`), adapt — the wrapper does not change.
- `_AuthMiddleware` exempts `/health` so liveness probes don't need credentials.
- Rate limit bucket is in-memory; restart loses state. Acceptable for single-instance v1.

### 3. `store.store_path` env-driven directory

Current `store.py`:

```python
DATA = Path("data")

def store_path(country: str) -> Path:
    return DATA / "store" / f"{country}.parquet"
```

Change to read `PERSONA_STORE_DATA_DIR`:

```python
def _store_dir() -> Path:
    return Path(os.environ.get("PERSONA_STORE_DATA_DIR", "data/store"))


def store_path(country: str) -> Path:
    return _store_dir() / f"{country}.parquet"
```

`catalog_path(country)` stays as `store_path(country).with_suffix("").with_suffix(".catalog.json")` — unchanged.

This keeps local development behaviour identical (`data/store` default) while allowing container deployment to mount `/data` and set `PERSONA_STORE_DATA_DIR=/data`.

Existing tests that monkeypatch `store_path` keep working because monkeypatching replaces the function entirely.

### 4. Dockerfile

Multi-stage at repo root:

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra mcp --no-dev --no-install-project
COPY persona_mcp_store persona_mcp_store
COPY README.md ./
RUN uv sync --frozen --extra mcp --no-dev

FROM python:3.11-slim AS runtime
RUN useradd -u 1000 -m app
WORKDIR /app
COPY --from=builder /app /app
USER app
ENV PATH="/app/.venv/bin:$PATH"
ENV PERSONA_STORE_DATA_DIR=/data
EXPOSE 8080
ENTRYPOINT ["python", "-m", "persona_mcp_store.cli", "serve-http"]
```

Final image expected ~200–300 MB (slim base + polars wheels). Data is NOT copied — operator mounts host directory to `/data:ro`.

### 5. docker-compose.yml (operational example)

```yaml
services:
  persona-store:
    build: .
    image: persona-store:latest
    container_name: persona-store
    environment:
      PERSONA_STORE_API_KEYS: ${PERSONA_STORE_API_KEYS}
      PERSONA_STORE_RATE_LIMIT: "60"
      LOG_LEVEL: info
    volumes:
      - ./data/store:/data:ro
    ports:
      - "127.0.0.1:8080:8080"  # bind localhost; reverse proxy in front
    restart: unless-stopped
```

Provided as a reference; operators free to swap (Kubernetes, Nomad, bare uvicorn behind systemd, etc.).

### 6. Tests

```
tests/unit/test_remote.py         (new)
  - _load_api_keys raises if env empty
  - _AuthMiddleware allows /health unauthenticated
  - _AuthMiddleware blocks missing Authorization, malformed, unknown token
  - _AuthMiddleware passes valid Bearer
  - _RateLimitMiddleware allows up to N requests, blocks N+1, sets retry-after
  - _StructuredLogMiddleware emits JSON line with required fields to stderr
  - _RequestIdMiddleware preserves provided x-request-id, generates if missing
  - build_app integration: health endpoint reachable, MCP path requires auth

tests/unit/test_store.py          (modify)
  - test_store_path_respects_env_var: PERSONA_STORE_DATA_DIR env honored
```

`httpx.AsyncClient(transport=ASGITransport(app=...))` for endpoint-level tests without booting uvicorn.

No new `tests/integration/` directory in v1 — Starlette's TestClient gives sufficient coverage.

## Migration plan

1. spec (this document) commit
2. plan via writing-plans
3. implementation (subagent-driven-development):
   1. `store.py`: `_store_dir()` env-driven (TDD — one new test) + 1 commit
   2. `remote.py`: skeleton + 4 middleware classes (TDD per middleware) + 1 commit each
   3. `remote.build_app` factory + health route (TDD) + 1 commit
   4. `cli/serve_http.py` + register in `cli/app.py` (TDD: smoke import) + 1 commit
   5. `Dockerfile` + `docker-compose.yml` + `.dockerignore` + 1 commit
   6. `pyproject.toml`: add `starlette`, `uvicorn` to `[mcp]` extra (FastMCP transitively pulls these but pin explicitly) + 1 commit
   7. `README.md` deployment section + 1 commit
4. validation:
   - local: `make build COUNTRY=Korea` then `PERSONA_STORE_API_KEYS=test1,test2 uv run persona-mcp-store serve-http`. `curl http://localhost:8080/health` returns 200, MCP path returns 401 without auth, succeeds with `Authorization: Bearer test1`.
   - container: `docker compose up`, same checks against the published port.
   - rate limit: 61 calls in 60s — 61st returns 429 with retry-after.
   - load test: 10 parallel clients, 1M-row sample queries — verify no crash, log line per request.

## Decisions made

| Decision | Reason |
|---|---|
| streamable-http transport (not SSE) | MCP 2025-06 권장. SSE는 deprecated. |
| Plain Bearer API keys (env var) v1 | OAuth 클라이언트 생태계 미성숙. 키 rotation은 env 갱신 + restart. |
| Single permission model | per-tenant scoping은 운영 복잡도 큼. 사용 패턴 본 후 P3에 결정. |
| Reverse proxy가 TLS 종료 | 표준 패턴. 컨테이너에 인증서 burn-in은 인증서 갱신/관리 부담 큼. |
| In-memory token bucket | 단일 인스턴스 가정. 외부 store 의존성 도입 시점은 scale-out 시. |
| Bind volume for data | 1GB×N 이미지 burn-in 비대화. 갱신 시 mount 갱신만으로 충분. |
| stderr JSON line | 외부 시스템(ELK/Loki)이 자유롭게 수집. 별도 sink 결정 강제 안 함. |
| `serve` + `serve-http` 분리 | 두 transport가 기동 방식이 다름. flag 합치기보다 명령 분리가 직관적. |
| Health path 인증 면제 | liveness probe가 키 없이 동작해야 함. /health는 stores 목록만 노출. |
| 30초 default request timeout | Starlette/uvicorn 기본. polars 작업이 그 안에 끝나는 게 정상. |

## Open questions (resolve in implementation)

1. `mcp.streamable_http_app()` exact API name in installed mcp 1.27. Verify by `dir(FastMCP)` — alternative names: `streamable_http_app`, `create_streamable_http_app`, `http_app`. If missing entirely on this version, document SDK upgrade requirement.
2. Should `_RateLimitMiddleware` apply to `/health`? Currently no (key=None bypass). Confirm liveness probes won't need different limit.
3. `LOG_LEVEL` env var — is it consumed by any middleware now, or only reserved for v2 (e.g. when we add `level: "debug"` records)? v1 mention in serve-http docstring but unused.

## Risk

- **Single instance assumption**: rate limiter and request id are in-memory. Scaling horizontally will need Redis (rate) and reverting to header-only request id. P3 problem.
- **API key rotation downtime**: changing env requires restart. Brief unavailability during deploy. Mitigation: rolling deploy or temporary dual-key env.
- **MCP SDK transport stability**: streamable-http is newer than stdio. If `mcp` 1.27 has bugs, may need to pin version or wait for fix. Plan includes verification step (Step 4 in migration).
- **Memory growth from rate buckets**: deque per token, max 60 entries × 60s window = small. Stale tokens never reaped (dict grows). Mitigation: simple periodic cleanup if instance lives weeks; not v1 concern.
- **Reverse proxy misconfiguration**: operator mistake (e.g. forgetting TLS) is outside our control. Document in README that the app expects HTTPS termination upstream.

## Success criteria

1. `uv run persona-mcp-store serve-http` (with `PERSONA_STORE_API_KEYS=test`) starts uvicorn on `:8080` without error.
2. `GET /health` returns `200 {"status":"ok","stores":[...]}` without auth.
3. `POST /mcp` (or whatever streamable-http path FastMCP uses) without `Authorization` returns `401`.
4. Same path with `Authorization: Bearer test` succeeds.
5. 61 requests within 60s for one key — 61st returns `429` with `retry-after` header.
6. Each authenticated request emits one JSON line to stderr with `request_id`, `token_id`, `op` (or `path`), `elapsed_ms`, `status`.
7. `docker compose up` starts container; `/health` reachable on host port 8080.
8. Container does NOT contain parquet data (verify via `docker inspect` size or empty `/data` when no mount).
9. All existing 90 unit tests still pass; new ~10 tests for remote module pass.
10. README updated with deployment section showing env var matrix + docker-compose snippet + reverse proxy note.

## Sequence: client first call (intended UX)

1. Operator deploys container with `PERSONA_STORE_API_KEYS=k1,k2` and mounted store.
2. Reverse proxy terminates TLS at `https://persona-store.team.example.com`, forwards to container `:8080`.
3. Client configures `.mcp.json`:
   ```json
   {
     "mcpServers": {
       "persona-store": {
         "type": "streamable-http",
         "url": "https://persona-store.team.example.com",
         "headers": {"Authorization": "Bearer k1"}
       }
     }
   }
   ```
4. Client connects, calls `list_resources` → gets `personas://catalog` → reads catalog → calls `sample_personas` with valid axes.
5. Server logs each request as JSON line to stderr; operator's log shipper (Loki/ELK) ingests.
6. If client polls aggressively, 60th-per-minute call onwards gets 429; client backs off.
7. Operator rotates keys: `docker compose down && PERSONA_STORE_API_KEYS=k1,k3 docker compose up -d`. Old `k2` instantly invalid; `k3` accepted.

This sequence is the v1 success bar.
