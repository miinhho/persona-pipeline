# MCP UX upgrade — Catalog resources + Observability + Error UX

**Status**: design
**Date**: 2026-05-09
**Author**: brainstorm 결과
**Predecessor**: `2026-05-09-mcp-persona-store-design.md` (initial MCP server)

## Problem

초기 MCP server는 4 tool (sample / search / distribution / get) 만 노출한다. 실제 사용 시 발견된 갭:

- **Discovery 부재**: LLM 클라이언트가 연결 직후 "어떤 country가 빌드돼 있는지, 각 country의 axis 값이 무엇인지" 알 방법이 없다. 추측성 `persona_distribution` 호출이 유일한 길.
- **Observability 갭**: 1M-row 쿼리가 몇 ms 걸렸는지, 어떤 호출이 어떤 매개변수로 들어왔는지 server stderr에도 client에도 안 남는다. tool description 외엔 사용 흐름 보기 어려움.
- **Error UX**: country-not-found 외 대부분의 잘못된 입력 (filter axis 이름 오타, group_by 컬럼 오타, n=0 등)이 raw polars/python 에러 그대로 client에 노출. self-correcting 힌트 없음.

근본 원인: MCP의 tool primitive만 활용하고, **resource** primitive와 **Context** logging 인터페이스를 안 썼음.

## Goal

LLM 클라이언트(Claude Desktop / Code / 외부)가 server 연결 직후 catalog를 자동 발견하고, tool 호출 결과/소요시간을 정상 채널로 받고, 잘못된 입력에 대해 자기 교정 가능한 메시지를 받게 한다.

## Non-goals

- v1 catalog 갱신 메커니즘 (build 재실행 = catalog 재생성으로 충분)
- HTTP/SSE transport (별도 spec)
- Progress reporting (`ctx.report_progress`) — polars 작업이 atomic, 모든 tool이 1–2초 내 완료라 ROI 낮음
- 구조화 메트릭 export (Prometheus 등) — stdio MCP에 안 맞음
- Pydantic value validator로 axis 값 사전 검증 — silent-zero가 더 간결, catalog로 발견 가능
- 새 tool 추가 (catalog는 resource로 노출)

## Architecture

```
data/store/{country}.parquet                 ← 기존: store
data/store/{country}.catalog.json            ← 신규: build sidecar (gitignore, 결정적)
        │
        ▼
mcp_server.py
  • tools (기존 4개 + ctx + Field):
      sample_personas / search_personas / persona_distribution / get_persona
  • resources (신규):
      personas://catalog            (list of built countries)
      personas://catalog/{country}  (per-country axes + counts + schema)
        │
        ▼
LLM client (Claude Desktop / Code / 외부)
  - list_resources() / list_resource_templates() 자동 발견
  - read_resource(uri) catalog 조회
  - call_tool(...) — Field description 보고 호출, 에러 메시지에 catalog URI 자동 포함
  - notifications/message 채널로 server 로그 수신
```

## Components

### 1. Catalog sidecar 생성 (build 단계 변경)

**Location**: `data/store/{country}.catalog.json` (per-country single file, ~수 KB)

**Schema**:
```json
{
  "country": "Korea",
  "n_personas": 1000000,
  "axes": {
    "region": {"수도권": 506000, "영남권": 246000, ...},
    "age_gen": {"중장년": 541000, "노년": 234000, "청년": 224000},
    "sex": {"여자": 504000, "남자": 496000},
    "occupation_group": {"무직": 381000, ...}
  },
  "schema": ["country","uuid","region","age_gen","sex","occupation_group", ...],
  "built_at": "2026-05-09T19:32:00Z"
}
```

**Where**: `persona_pipeline/cli/build.py` 끝에 추가. enrich → store.parquet 작성 직후, store를 한 번 scan해서 axes별 value-counts + schema + n_personas 계산해 sidecar 작성.

**Why sidecar JSON, not parquet**: KB 단위 메타데이터, 빈번 read, JSON이 sufficient. parquet 오버헤드 불필요.

**Why per-country file (not single global manifest)**: country 추가 시 race condition 회피. 빌드 단위와 일치.

**Reproducibility**: raw + lookup + code → store + catalog 모두 결정적. catalog도 store와 같이 gitignore.

### 2. Catalog resources (mcp_server.py 신규)

```python
@mcp.resource(
    "personas://catalog",
    name="catalog",
    description="List all built persona stores (one entry per country).",
    mime_type="application/json",
)
def catalog() -> str:
    """Return list of built countries with row counts and axis names."""
    countries = []
    for path in sorted(DATA_STORE.glob("*.catalog.json")):
        meta = json.loads(path.read_text())
        countries.append({
            "country": meta["country"],
            "n_personas": meta["n_personas"],
            "axes": list(meta["axes"].keys()),
        })
    return json.dumps(countries, ensure_ascii=False)


@mcp.resource(
    "personas://catalog/{country}",
    name="country_catalog",
    description="Per-country catalog: axes with value counts, schema, n_personas.",
    mime_type="application/json",
)
def country_catalog(country: str) -> str:
    path = catalog_path(country)
    if not path.exists():
        raise ValueError(f"unknown country '{country}'. See personas://catalog.")
    return path.read_text()
```

**Note**: resource handlers cannot raise `ToolError` (resource semantics). `ValueError` propagates as MCP `resources/read` error response.

**Storage helpers**: `store.catalog_path(country)`, `store.load_catalog(country) -> dict`.

### 3. Observability — `_observe` context manager

```python
from contextlib import contextmanager
from time import perf_counter

@contextmanager
def _observe(ctx: Context | None, op: str, **params):
    t0 = perf_counter()
    if ctx:
        ctx.info(f"{op}: " + " ".join(f"{k}={v!r}" for k, v in params.items()))
    try:
        yield
    except ToolError:
        raise  # already user-facing
    except Exception as e:
        if ctx:
            ctx.error(f"{op} failed: {type(e).__name__}: {e}")
        raise
    finally:
        ms = int((perf_counter() - t0) * 1000)
        if ctx:
            ctx.info(f"{op}: done in {ms}ms")
```

**Usage**:
```python
@mcp.tool()
def sample_personas(country, ..., ctx: Context | None = None) -> list[dict]:
    _validate_country(country)
    filt = _axes_filter(...)
    with _observe(ctx, "sample_personas", country=country, n=n, filter=filt):
        result = store.sample(country, filt, n, seed).to_dicts()
        if ctx and not result:
            ctx.warning(f"sample_personas: empty result for filter={filt}")
        return result
```

**Why optional `ctx`**: 기존 unit tests는 함수를 직접 호출. `Context` 인자가 None일 때 noop 동작.

### 4. Error UX 확장

**Helpers in `mcp_server.py`**:

```python
def _validate_axis_names(country: str, names: Iterable[str], purpose: str) -> None:
    """Raise ToolError if any name is not in mapping.axes for country."""
    valid = list(get_mappings(country).axes)
    bad = [n for n in names if n not in valid]
    if bad:
        raise ToolError(
            f"unknown {purpose}: {bad}. valid for {country}: {valid}. "
            f"See personas://catalog/{country}."
        )
```

**Apply to**:
- `sample_personas` / `search_personas` / `persona_distribution`: filter dict의 key들을 검증
- `persona_distribution`: `group_by` 리스트도 검증

**Boundary checks via `Field`**:
- `n: int = Field(default=10, ge=1, le=1000, description=...)`
- `top_k: int = Field(default=10, ge=1, le=1000, description=...)`
- `seed: int = Field(default=0, ge=0, description=...)`

Pydantic이 `ge`/`le` 위반을 자동으로 ValidationError → MCP error로 변환. 별도 ToolError 추가 불필요.

**Field descriptions for self-correction**:

| Parameter | Description |
|---|---|
| `country` | "Country name. List built countries: read 'personas://catalog'." |
| `region` / `age_gen` / `sex` / `occupation_group` | "Filter by axis. Values per country in 'personas://catalog/{country}'." |
| `n` / `top_k` | "Number to return (1–1000)." |
| `seed` | "Same (filter, n, seed) returns identical rows. Use for reproducibility." |
| `query` | "Literal substring (not regex). Matched against persona/professional_persona/sports_persona/arts_persona/travel_persona/culinary_persona/family_persona text fields." |
| `group_by` | "Axis names to group by. Same set as filter axes; see 'personas://catalog/{country}'." |
| `uuid` | "Persona UUID returned in `uuid` field of sample/search results." |

### 5. CLI / Tests

**No new CLI commands.** `build` 명령이 사이드카를 함께 생성한다.

**New tests**:
- `tests/unit/test_catalog.py`:
  - sidecar 생성 함수 (`store.write_catalog(country)` or build helper)
  - schema 정확성 (n_personas, axes counts, schema list)
  - per-country JSON read/parse
- `tests/unit/test_mcp_server.py` 추가:
  - `personas://catalog` resource read 시 빌드된 country list 반환
  - `personas://catalog/{country}` resource read 시 axes counts 반환
  - 미존재 country resource read 시 적절한 에러
  - filter axis name unknown → ToolError + valid axes 메시지
  - group_by column unknown → ToolError
  - n=0 → Pydantic ValidationError (FastMCP가 잡음)
  - Context 인자 None 호출은 기존처럼 동작 (regression 가드)

**Existing 4 store helper tests**: 변경 없음.

## Migration plan

순서:
1. spec (이 문서) commit
2. plan (writing-plans skill로 작성)
3. 구현 (subagent-driven-development):
   1. `store.py`에 `catalog_path`, `write_catalog`, `load_catalog` 추가 (TDD)
   2. `cli/build.py` 끝에 `write_catalog` 호출
   3. `mcp_server.py`에 `_observe` + `_validate_axis_names` helpers 추가 (TDD)
   4. 4 tools에 `ctx: Context`, `Field(description=)`, `_observe`, `_validate_axis_names` 적용
   5. `personas://catalog` / `personas://catalog/{country}` resources 추가 (TDD)
   6. 기존 Korea store에 catalog 재생성 (`build Korea`로 사이드카 생성)
4. validation: Claude Code에서 connect → resources/list 자동으로 표시되는지, tool 잘못된 axis 호출 시 self-correcting 메시지 보이는지

## Decisions made

| Decision | Reason |
|---|---|
| Catalog = JSON sidecar per country | KB 메타데이터에 parquet 오버 |
| Catalog gitignore | 결정적 재생성 (raw + lookup + code → store + catalog) |
| Resource for catalog, tool for actions | MCP semantics 정확 사용. resource는 자동 발견됨 |
| `ctx: Context | None = None` (optional) | 기존 unit tests 호환. 함수 직접 호출 가능 유지 |
| `_observe` context manager | 4 tool 공통 패턴 boilerplate 제거. ToolError는 그대로 raise |
| filter value 미스매치는 silent zero | hard fail보다 catalog 발견이 더 자연스러운 흐름 |
| Pydantic `Field(ge=1)`로 boundary 강제 | FastMCP가 ValidationError → MCP error 자동 변환. ToolError 중복 불필요 |
| Catalog URI를 ToolError 메시지에 명시 | self-correcting 핵심. LLM이 에러 받으면 즉시 다음 호출 결정 가능 |

## Open questions

(implementation phase에서 해결)

1. `personas://catalog/{country}` resource의 mime_type은 `application/json` — FastMCP 1.27이 resource template + JSON 직렬화 자동 처리하는지 확인 필요. 안 되면 `text/plain`으로 fallback.
2. resource handler에서 ValueError vs custom exception — FastMCP가 정확히 어떻게 client에 forwarding하는지 SDK 동작 확인.
3. catalog의 `built_at`이 binary-reproducibility를 깨는지 — 결정적 재생성이 우선이면 timestamp 빼는 것도 옵션. (built_at 유지 추천: 운영 가시성 가치)

## Risk

- **resource auto-discovery 지원 차이**: MCP-aware 클라이언트(Claude Desktop/Code)는 `list_resources` 자동 호출. 단순 스크립트 클라이언트는 안 함. v1은 "MCP-aware 클라이언트 우선" 전제.
- **Pydantic `Field` description의 client-side 노출 여부**: FastMCP가 schema의 `description` field를 채우는 건 표준. 다만 클라이언트마다 description을 LLM에 노출하는 정도가 다를 수 있음. spec은 "최선의 가이드를 server에서 제공한다"까지가 책임.
- **catalog 재계산 비용**: 1M-row scan으로 axes value-counts. polars로 sub-second 예상. build의 sink_parquet 직후라 캐시도 따뜻함.

## Success criteria

1. `make build COUNTRY=Korea` 후 `data/store/Korea.catalog.json` 생성. JSON schema 위 명시대로.
2. `python -m persona_pipeline.mcp_server` 실행 후 MCP 클라이언트가 `list_resources` 호출 시 `personas://catalog` 항목 노출.
3. `read_resource("personas://catalog")` → 빌드된 country list 반환. `read_resource("personas://catalog/Korea")` → axes + counts 반환.
4. 4 tool 호출 시 server 로그에 `op: params... done in Nms` 두 줄이 client `notifications/message`로 전달된다.
5. `sample_personas(country="Korea", region=["없는축"])` 호출 — 사실 region 값이 없는 게 아니라 *axis 이름 자체*가 다른 경우, 즉 `filter={"foo":"bar"}` 시도 시 ToolError 메시지에 valid axes + catalog URI 포함.
6. `sample_personas(n=0)` → Pydantic validation error(>=1 필수)가 client에 전달.
7. 기존 store helper 테스트 + MCP server 테스트 모두 통과.

## Sequence: client first-connect (intended UX)

1. Client connects to stdio MCP server
2. Client calls `list_resources` and `list_resource_templates`
3. Client sees `personas://catalog` and `personas://catalog/{country}` template
4. Client reads `personas://catalog` → discovers `[{"country":"Korea","n_personas":1000000,"axes":[...]}]`
5. Client reads `personas://catalog/Korea` → discovers axis values + counts
6. Client now has enough info to call `sample_personas(country="Korea", region=["수도권"], ...)` correctly on first try
7. Tool call returns; `notifications/message` shows `sample_personas: country='Korea' n=5 ... → 5 rows in 87ms`
8. If client makes a typo (e.g. `region` value not in catalog), tool returns 0 rows + warning log; if filter axis name itself is invalid, ToolError with catalog URI

This sequence is the success bar.
