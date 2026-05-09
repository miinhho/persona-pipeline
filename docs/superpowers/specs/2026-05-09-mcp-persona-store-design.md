# MCP Persona Store — replacing archetype-card pipeline

**Status**: design
**Date**: 2026-05-09
**Author**: 작업 brainstorm 결과
**Predecessor pipeline**: download → enrich → partition → archetype → match → simulate

## Problem

현재 pipeline은 raw Nemotron-Personas (per country ~1M rows, 13 풍부한 컬럼) 위에 *압축 layer*를 쌓아 archetype 카드를 산출한다.
정성 평가 결과 (8개 segment × 2 task simulation, blind subagent eval):

- **Region 신호가 fake**: 카드의 `top_hobbies`에 박힌 지명을 LLM이 복사. 카드 자체에 *동네 단위* 정보 없음
- **Sex 신호 거의 부재**: 동일 segment 남녀 swap 시 응답 사실상 동일
- **Occupation 디테일 평탄화**: raw의 "CNC 떨림", "굴착기" 같은 풍부함이 응답에선 generic으로 압축
- **Sample cherry-pick**: 5명 중 1번만 사용, 나머지 4명 raw 무시
- **Top_hobbies 체크리스트**: 한 단락에 hobby 4–5개 다 박는 슈퍼휴먼 응답
- **LLM default 메타-담론으로 수렴**: 광고 task에서 페르소나가 아니라 모델 기본값으로 회귀

원인 분해:
- 도메인 활용 부재 (압축 손실): **80%**
- Nemotron 1차 LLM 합성 한계: **15%**
- 2차 LLM 가공 부재: **5%**

→ 80%의 진짜 문제는 *압축이 raw의 80%를 폐기*해서 발생한다. 2차 LLM 가공은 우리 LLM의 stereotype을 NVIDIA LLM의 한계 위에 덮어쓰기 — noise 증폭.

또한 Output consumer가 LLM이라는 사실 (analyst가 직접 카드를 보는 use case 없음)이 다음을 함의:
- human-readable summary는 dead weight
- structured schema가 인터페이스의 본체
- LLM은 raw 5000자도 그대로 처리 가능 — 요약 layer 불필요
- LLM client는 *필요할 때 query*해서 데이터를 가져옴 (push 아닌 pull)
- 따라서 자연스러운 인터페이스 = MCP

## Goal

LLM consumer (Claude Desktop, Claude Code, 외부 client)가 MCP tool을 통해 raw Nemotron persona를 query/filter/sample 해서 자기 client에서 simulation·analysis에 사용한다.
우리는 *데이터 server*만 제공하고 simulation은 호스팅하지 않는다.

## Non-goals

- 카드/segment_id 보존 (decision: 폐기)
- human-facing dashboard / prose summary
- 2차 LLM 가공 (텍스트 추출, segment 요약 등) — 1차 합성 위에 stereotype 누적 위험
- axes 정의 변경 — 현재 region / age_gen / sex / occupation_group 유지. 별도 spec에서 validate 결과로 정당화될 때만.
- Vector embedding search (v2)
- HTTP/SSE transport (v2)
- Multi-tenant auth

## Architecture

```
data/raw/{country}/personas.parquet              ← Nemotron HF (immutable, gitignore)
        │
        ▼ enrich (axes 추출 + occupation 분류 lookup join)
data/store/{country}.parquet                     ← single source of truth (gitignore, 재생성)
        │
        ▼ store.py query helpers (polars LazyFrame)
data/occupation_lookup/{country}.parquet         ← versioned data asset (git)
        ▲
        │ classify_occupation (Anthropic Batches API, 1회 가공)
        │
mcp_server.py                                     ← stdio MCP server
  • sample_personas(country, filter, n, seed?)
  • search_personas(country, query, top_k, filter?)
  • persona_distribution(country, group_by, filter?)
  • get_persona(uuid)
        ▲
        │ MCP stdio
LLM client (Claude Desktop / Code / external)     ← simulation·analysis는 여기
```

## Components

### 1. Enriched store

**Location**: `data/store/{country}.parquet` (per-country single file, ~100MB compressed)

**Schema** (열 순서: filter 효율을 위해 axes 우선):
```
country: str                  # always present
uuid: str                     # primary key, deterministic sampling 시드
region: str                   # derived axis (or null for native countries)
age_gen: str                  # derived axis ("청년" / "중장년" / "노년")
sex: str                      # raw axis
occupation_group: str         # derived axis (LLM-classified or native)
age: i32                      # raw int
province: str                 # raw native administrative
occupation: str               # raw free-text
hobbies: list[str]            # parsed from hobbies_and_interests_list
persona: str                  # raw text
professional_persona: str
sports_persona: str
arts_persona: str
travel_persona: str
culinary_persona: str
family_persona: str
```

**Write pattern**: `axes` 컬럼으로 sort 후 zstd compression. row group default. predicate pushdown으로 axes filter 시 row group level skip 효율.

**Reproducibility**: `raw + occupation_lookup + enrich code` → store는 deterministic. store 자체는 gitignore (`data/store/`).

### 2. Enrich pipeline (재정리)

기존 `persona_pipeline/stages/enrich.py` + `classify_occupation.py`를 새 store output으로 정리.

**Flow**:
```python
def build_store(country: str) -> None:
    raw = pl.scan_parquet(raw_path(country))
    lookup = pl.scan_parquet(occupation_lookup_path(country)) if needs_lookup else None
    enriched = enrich(raw, mapping, occupation_lookup=lookup)
    enriched_with_country = enriched.with_columns(pl.lit(country).alias("country"))
    sorted_lf = enriched_with_country.sort(mapping.axes)
    write_parquet(sorted_lf, store_path(country))
```

**변경**: `partition` stage 폐기. `segment_id` 컬럼 만들지 않음. `partitioned_path()` 함수 제거.

**유지**: occupation classify CLI (`stage-classify-occupation`) — 분류는 LLM 가공이지만 *판단형*이라 OK. lookup parquet은 git-tracked asset.

### 3. `store.py` — query helpers

```python
import polars as pl

def load(country: str) -> pl.LazyFrame:
    return pl.scan_parquet(store_path(country))


def _apply_filter(lf: pl.LazyFrame, filter: dict | None) -> pl.LazyFrame:
    """filter dict: {axis_name: value | list[value]}. None = no filter."""
    if not filter:
        return lf
    for col, val in filter.items():
        if isinstance(val, list):
            lf = lf.filter(pl.col(col).is_in(val))
        else:
            lf = lf.filter(pl.col(col) == val)
    return lf


def sample(country: str, filter: dict | None, n: int, seed: int = 0) -> pl.DataFrame:
    """Deterministic uniform random sample of n rows matching filter."""
    lf = _apply_filter(load(country), filter)
    return (
        lf.with_columns(pl.col("uuid").hash(seed=seed).alias("_rand"))
          .sort_by("_rand").head(n).drop("_rand").collect()
    )


def distribution(
    country: str, group_by: list[str], filter: dict | None = None
) -> pl.DataFrame:
    lf = _apply_filter(load(country), filter)
    return lf.group_by(group_by).agg(pl.len().alias("count")).sort("count", descending=True).collect()


def get(country: str, uuid: str) -> dict | None:
    df = load(country).filter(pl.col("uuid") == uuid).limit(1).collect()
    return df.row(0, named=True) if len(df) else None


def search(
    country: str, query: str, top_k: int = 10, filter: dict | None = None
) -> pl.DataFrame:
    """v1: substring match across all persona text columns. v2: embedding."""
    lf = _apply_filter(load(country), filter)
    text_cols = ["persona", "professional_persona", "sports_persona", "arts_persona",
                 "travel_persona", "culinary_persona", "family_persona"]
    cond = pl.lit(False)
    for c in text_cols:
        cond = cond | pl.col(c).str.contains(query, literal=True)
    return lf.filter(cond).head(top_k).collect()
```

deterministic uniform sampling은 기존 `archetype.py`의 검증된 패턴 (`uuid.hash(seed)`).

### 4. `mcp_server.py` — MCP tool 노출

Anthropic 공식 `mcp` Python SDK 사용. FastMCP 스타일 (decorator 기반).

```python
from mcp.server.fastmcp import FastMCP
from persona_pipeline import store

mcp = FastMCP("persona-store")


@mcp.tool()
def sample_personas(
    country: str,
    n: int = 10,
    region: list[str] | None = None,
    age_gen: list[str] | None = None,
    sex: list[str] | None = None,
    occupation_group: list[str] | None = None,
    seed: int = 0,
) -> list[dict]:
    """Return n raw personas from the country, filtered by axes.
    Use the returned `persona`, `professional_persona`, ... fields directly as
    system-prompt material for roleplay simulation.
    """
    filt = {k: v for k, v in [
        ("region", region), ("age_gen", age_gen),
        ("sex", sex), ("occupation_group", occupation_group),
    ] if v}
    return store.sample(country, filt, n, seed).to_dicts()


@mcp.tool()
def search_personas(
    country: str,
    query: str,
    top_k: int = 10,
    region: list[str] | None = None,
    age_gen: list[str] | None = None,
    sex: list[str] | None = None,
    occupation_group: list[str] | None = None,
) -> list[dict]:
    """Substring search across persona text fields, optionally constrained by axes."""
    filt = {k: v for k, v in [
        ("region", region), ("age_gen", age_gen),
        ("sex", sex), ("occupation_group", occupation_group),
    ] if v}
    return store.search(country, query, top_k, filt).to_dicts()


@mcp.tool()
def persona_distribution(
    country: str,
    group_by: list[str],
    region: list[str] | None = None,
    age_gen: list[str] | None = None,
    sex: list[str] | None = None,
    occupation_group: list[str] | None = None,
) -> list[dict]:
    """Group filtered rows by `group_by` columns and return counts (descending)."""
    filt = {k: v for k, v in [
        ("region", region), ("age_gen", age_gen),
        ("sex", sex), ("occupation_group", occupation_group),
    ] if v}
    return store.distribution(country, group_by, filt).to_dicts()


@mcp.tool()
def get_persona(country: str, uuid: str) -> dict | None:
    """Look up one persona by uuid. Returns None if not found."""
    return store.get(country, uuid)


if __name__ == "__main__":
    mcp.run()  # stdio transport
```

**Schema**: typed Python signatures → MCP가 자동 JSON schema 생성.
**Output**: list of raw row dicts. JSON-serializable (list[str]은 그대로 직렬화).
**Failure modes**: country not found → `ToolError`. Empty filter result → 빈 list (에러 아님).

### 5. CLI (재정리)

```
persona_pipeline/cli/
├── app.py                          (Typer app)
├── _paths.py                       (raw_path, store_path, occupation_lookup_path)
├── build.py                        ← 새: download + classify-occupation + write store
└── serve.py                        ← 새: stdio MCP server start
```

**Commands**:
- `download <country>` — HF Nemotron 다운로드 (기존 그대로)
- `classify-occupation <country>` — Anthropic Batches API 분류 (기존 그대로)
- `build <country>` — enrich → store 작성
- `serve` — MCP server 시작 (stdio)

**폐기 commands**: `stage-enrich`, `stage-partition`, `match`, `simulate`.

### 6. Tests

```
tests/unit/
├── test_enrich.py                  (axes 추출 — 기존 보존, store output 형태로 적응)
├── test_store.py                   ← 새: load/sample/distribution/get/search
├── test_mcp_server.py              ← 새: tool dispatch (mock MCP client)
└── test_mappings.py                (per-country 정의 — 기존 보존)
```

**폐기 tests**: `test_partition.py`, `test_match.py`, `test_workflow.py` (archetype 의존), `test_simulate.py`.

**테스트 패턴**: 합성 raw → in-memory store → 함수 호출 결과 단언. 현재 코드베이스의 기존 패턴 유지.

## Migration plan

순서:
1. spec 작성 (이 문서) + commit
2. plan 작성 (writing-plans skill)
3. 구현:
   1. `store.py` 신규 작성 (의존 없음)
   2. `mcp_server.py` 신규 작성
   3. `cli/build.py`, `cli/serve.py` 신규 작성
   4. `enrich.py` 출력을 store 형태로 조정
   5. tests 신규 작성, 기존 enrich/mappings test 적응
   6. 폐기 파일/디렉토리 삭제 (`stages/{partition,archetype,match,simulate}.py`, 관련 cli, 관련 test, `data/{archetypes,cache,simulations}/`)
   7. README rewrite, Makefile 정리, pyproject.toml `[sim]` extra → `[mcp]` extra
4. validation: `build Korea` 실행, MCP server 켜고 Claude Code에서 connect, sample/search/distribution/get 4 tool 모두 정상 응답 확인

## Decisions made (rationale)

| Decision | Reason |
|---|---|
| Per-country 단일 parquet (hive partition 안 함) | 1M rows × ~100MB는 단일 file이 deployment·git diff·테스트에 단순. country 인자로 dispatch. |
| `segment_id` 컬럼 폐기 | axes column 직접 filter가 predicate pushdown 효율. segment_id는 압축 잔재. |
| Search v1 = `str.contains` substring | 1M rows에 polars naive substring scan은 sub-second. embedding은 인프라 / 모델 / 인덱스 / 평가 4중 투자라 v1 과투자. |
| MCP stdio transport v1 | local-first. Claude Code·Desktop에서 직접 연결 가능. HTTP/SSE는 remote 배포 시점에 추가. |
| Top-level `mcp` extra in pyproject | `[sim]` extra (anthropic SDK 의존)는 폐기. 새 `[mcp]` extra (`mcp` SDK 의존). |
| Enriched store는 gitignore | raw + occupation_lookup + code = deterministic 재생성. occupation_lookup은 git-tracked (LLM 분류 결과 = 진짜 자산). |
| Validate harness는 *out of scope* | sex/region 신호 강도 정량 측정은 의미 있지만 별도 spec. 본 spec은 architecture 전환에 집중. |

## Open questions

(spec writing self-review에서 문제 없으면 implementation phase에서 해결)

1. `country` 컬럼을 store에 column으로 둘지, 디렉토리 partition으로 분리할지 — column으로 결정 (단일 파일 정책과 일치).
2. MCP server의 working directory를 environment variable로 받을지, CLI 인자로 받을지 — `--data-dir` CLI 옵션 + env fallback.
3. `Persona` dataclass / Pydantic 모델로 schema 강제할지, raw dict 통과할지 — raw dict 통과. MCP가 typed signature에서 자동 schema 생성하므로 충분.

## Risk

- **Search v1 (substring)이 LLM consumer에게 부족할 위험**: 자연어 query "30대 여성 IT" 같은 건 substring으로 부분 동작 (subset). 사용해보고 부족하면 v2에서 embedding 추가. v1은 exact-axes filter (sample/distribution) 위주가 진짜 use case일 가능성 높음.
- **MCP SDK API 변경 가능성**: Anthropic 공식이라 안정적이지만 버전 lock 필요 (`mcp>=X,<Y`).
- **Nemotron 1차 합성의 한계**: sex/region 신호 약함. 우리가 못 고침. 별도 spec에서 정량 측정 후 axes 정의 변경 또는 사용 문서에 limitation 명시.

## Success criteria

1. `build Korea` 명령으로 `data/store/Korea.parquet` 생성
2. `serve` 명령으로 stdio MCP server 시작
3. Claude Code에서 connect 후 4 tool 모두 정상 응답
4. `sample_personas(country="Korea", region=["수도권"], age_gen=["중장년"], sex=["여자"], occupation_group=["사무"], n=5)` 호출 시 5개 raw persona dict 반환
5. 폐기 대상 코드 / 데이터 / test 모두 삭제. 코드베이스 ~12 → ~6 핵심 파일
6. 기존 enrich / mappings / occupation classifier 테스트 그대로 통과
