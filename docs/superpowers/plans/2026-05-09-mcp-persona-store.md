# MCP Persona Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the archetype-card pipeline (`partition → archetype → match → simulate`) with a raw-individual store + MCP server. LLM consumers query the server via MCP tools to fetch raw Nemotron personas; we no longer host simulation or build compressed archetype cards.

**Architecture:** Single source of truth = `data/store/{country}.parquet` (raw columns + 3 derived axes + country, sorted by axes for predicate pushdown). Four MCP tools (`sample_personas`, `search_personas`, `persona_distribution`, `get_persona`) wrap pure polars helpers in `store.py`. CLI exposes `build` (one-time enrich) and `serve` (stdio MCP server).

**Tech Stack:** Python 3.11, polars 1.x (LazyFrame + uuid hash sampling), pyarrow, MCP Python SDK (`mcp.server.fastmcp.FastMCP`), Anthropic SDK (occupation classifier only — judgmental LLM use), pytest, typer.

---

## File Structure

**Create:**
- `persona_pipeline/store.py` — query helpers (`load`, `sample`, `distribution`, `get`, `search`)
- `persona_pipeline/mcp_server.py` — FastMCP server, four `@mcp.tool()` definitions wrapping store
- `persona_pipeline/cli/build.py` — `build {country}` command (download + classify + enrich → store)
- `persona_pipeline/cli/serve.py` — `serve` command (run MCP server over stdio)
- `tests/unit/test_store.py` — store helper tests
- `tests/unit/test_mcp_server.py` — tool dispatch tests via mock store

**Modify:**
- `persona_pipeline/stages/enrich.py` — output = raw + axes + country, sorted; remove SEGMENT_KEY column
- `persona_pipeline/mappings/_base.py` — remove `SEGMENT_ID`, `SEGMENT_KEY`, `SEGMENT_SEP`, `backoff_axes`, `parse_segment`
- `persona_pipeline/mappings/__init__.py` — drop removed exports
- `persona_pipeline/cli/_paths.py` — add `store_path`; remove `enriched_path`, `partitioned_path`, `archetypes_path`, `simulations_path`, `cache_dir`
- `persona_pipeline/cli/app.py` — register only `download`, `classify-occupation`, `build`, `serve`
- `persona_pipeline/_config.py` — drop archetype/sample/backoff constants; keep `ROW_GROUP_SIZE`
- `persona_pipeline/validate.py` — drop `validate_partitioned`; keep raw-schema sanity checks
- `tests/unit/test_enrich.py` — adapt to new store schema
- `tests/unit/test_mappings.py` — drop any `parse_segment` test if present
- `pyproject.toml` — replace `[sim]` extra with `[mcp]`
- `README.md` — pipeline diagram + quick-start rewrite
- `Makefile` — `build`, `serve` targets only
- `.gitignore` — add `data/store/`

**Delete:**
- `persona_pipeline/stages/{partition,archetype,match,simulate}.py`
- `persona_pipeline/cli/{archetype,match,simulate,stages}.py`
- `tests/unit/{test_partition,test_match,test_workflow,test_simulate,test_validate}.py`
- `data/{archetypes,cache,simulations}/`
- `scripts/simulate_poc.py`, `scripts/diagnose_occupation.py`

---

## Tasks

### Task 1: Update pyproject extras

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Replace `[sim]` extra with `[mcp]`**

Edit `pyproject.toml` so `[project.optional-dependencies]` reads:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.6"]
mcp = ["mcp>=1.2", "anthropic>=0.40"]
```

Rationale: `anthropic` is required for the occupation classifier (Batches API). `mcp` is the official Python SDK exposing `mcp.server.fastmcp.FastMCP`.

- [ ] **Step 2: Sync uv lockfile**

Run: `uv sync --extra mcp --extra dev`
Expected: `mcp` installs, no resolution errors.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: switch [sim] extra to [mcp] (mcp + anthropic SDKs)"
```

---

### Task 2: Strip segment-id machinery from mappings module

**Files:**
- Modify: `persona_pipeline/mappings/_base.py`
- Modify: `persona_pipeline/mappings/__init__.py`

- [ ] **Step 1: Remove segment-id symbols from `_base.py`**

In `persona_pipeline/mappings/_base.py`, delete these definitions:
- `SEGMENT_ID = "segment_id"`
- `SEGMENT_KEY = "segment_key"`
- `SEGMENT_SEP = "|"`
- the `backoff_axes` function
- the `parse_segment` function

Preserve `REGION`, `AGE_GEN`, `SEX`, `OCCUPATION_GROUP`, `UUID`, `AGE`, `HOBBIES_COL`, `AGE_GEN_BOUNDS`, and the `CountryMappings` dataclass (with all its existing fields including `axes`).

- [ ] **Step 2: Remove dropped names from `mappings/__init__.py`**

Edit `persona_pipeline/mappings/__init__.py`:
- Drop `SEGMENT_ID`, `SEGMENT_KEY`, `SEGMENT_SEP`, `backoff_axes`, `parse_segment` from the `from persona_pipeline.mappings._base import (...)` import block.
- Drop the same names from `__all__`.

- [ ] **Step 3: Verify only soon-to-delete files reference them**

Run:
```bash
grep -rn "SEGMENT_ID\|SEGMENT_KEY\|SEGMENT_SEP\|backoff_axes\|parse_segment" persona_pipeline tests scripts 2>/dev/null
```
Expected: matches only inside `stages/{partition,archetype,match,simulate}.py`, `cli/{stages,match,simulate,archetype}.py`, `tests/unit/{test_partition,test_match,test_workflow,test_simulate,test_validate}.py`, `validate.py`, `scripts/*` — all of which Task 10 deletes or Task 9 modifies. Importantly, `enrich.py` should no longer match after Task 3.

- [ ] **Step 4: Commit**

```bash
git add persona_pipeline/mappings/_base.py persona_pipeline/mappings/__init__.py
git commit -m "refactor(mappings): drop segment-id constants and helpers"
```

---

### Task 3: Rewrite `enrich` to produce store-shaped output

**Files:**
- Test: `tests/unit/test_enrich.py`
- Modify: `persona_pipeline/stages/enrich.py`

- [ ] **Step 1: Replace `tests/unit/test_enrich.py` with the new schema test**

Overwrite the file with:

```python
import polars as pl

from persona_pipeline.mappings import get_mappings
from persona_pipeline.stages.enrich import enrich

KOREA = get_mappings("Korea")
PERSONA_TEXT_COLS = list(KOREA.persona_columns.keys())  # 7 fields for Korea


def _korea_synthetic_raw() -> pl.LazyFrame:
    rows = [
        {"uuid": "a", "age": 30, "sex": "남자", "province": "서울",
         "occupation": "초등학교 교사", "hobbies_and_interests_list": "['독서']",
         **{c: f"{c} 텍스트" for c in PERSONA_TEXT_COLS}},
        {"uuid": "b", "age": 70, "sex": "여자", "province": "제주",
         "occupation": "농업 종사원", "hobbies_and_interests_list": "['산책', '명상']",
         **{c: f"{c} 텍스트" for c in PERSONA_TEXT_COLS}},
    ]
    return pl.LazyFrame(rows)


def _lookup() -> pl.LazyFrame:
    return pl.LazyFrame({
        "occupation": ["초등학교 교사", "농업 종사원"],
        "occupation_group": ["전문가", "농림어업"],
    })


def test_enrich_output_contains_country_axes_and_raw_text():
    df = enrich(_korea_synthetic_raw(), KOREA, occupation_lookup=_lookup()).collect()
    expected = {
        "country", "uuid", "age", "sex", "province", "occupation", "hobbies",
        "region", "age_gen", "occupation_group",
        *PERSONA_TEXT_COLS,
    }
    assert expected.issubset(set(df.columns))
    assert df["country"].unique().to_list() == ["Korea"]


def test_enrich_does_not_emit_segment_key_or_id():
    df = enrich(_korea_synthetic_raw(), KOREA, occupation_lookup=_lookup()).collect()
    assert "segment_key" not in df.columns
    assert "segment_id" not in df.columns


def test_enrich_axes_resolved_correctly():
    df = enrich(_korea_synthetic_raw(), KOREA, occupation_lookup=_lookup()).collect()
    by_uuid = {r["uuid"]: r for r in df.iter_rows(named=True)}
    assert by_uuid["a"]["region"] == "수도권"
    assert by_uuid["a"]["age_gen"] == "청년"
    assert by_uuid["a"]["occupation_group"] == "전문가"
    assert by_uuid["b"]["region"] == "제주권"
    assert by_uuid["b"]["age_gen"] == "노년"
    assert by_uuid["b"]["occupation_group"] == "농림어업"


def test_enrich_hobbies_parsed_to_list():
    df = enrich(_korea_synthetic_raw(), KOREA, occupation_lookup=_lookup()).collect()
    assert df.schema["hobbies"] == pl.List(pl.Utf8)
    assert df.filter(pl.col("uuid") == "a")["hobbies"].to_list()[0] == ["독서"]
    assert df.filter(pl.col("uuid") == "b")["hobbies"].to_list()[0] == ["산책", "명상"]


def test_enrich_sorted_by_axes():
    df = enrich(_korea_synthetic_raw(), KOREA, occupation_lookup=_lookup()).collect()
    sorted_df = df.sort(KOREA.axes)
    assert df["uuid"].to_list() == sorted_df["uuid"].to_list()
```

- [ ] **Step 2: Run the failing tests**

Run: `uv run pytest tests/unit/test_enrich.py -v`
Expected: FAIL — current `enrich.py` selects only `[UUID, AGE, *axes, SEGMENT_KEY]`, dropping raw text.

- [ ] **Step 3: Rewrite `persona_pipeline/stages/enrich.py`**

Overwrite the file with:

```python
"""Enrich raw Nemotron rows with derived axes and emit the store-shaped LazyFrame.

Output schema (column order): country, uuid, region (if axis), age_gen, sex,
occupation_group, age, province (if exists), occupation (if exists), hobbies,
plus all persona text columns declared in `mapping.persona_columns`.

Hobbies are parsed from the raw `hobbies_and_interests_list` string column
(Python-list literal) into a `list[str]` column.
"""
from __future__ import annotations

import polars as pl

from persona_pipeline.mappings import (
    AGE, AGE_GEN, AGE_GEN_BOUNDS, CountryMappings, HOBBIES_COL,
    OCCUPATION_GROUP, REGION, SEX, UUID,
)


def _age_gen_expr(mapping: CountryMappings) -> pl.Expr:
    labels = list(mapping.age_gen_keywords.keys())
    if len(labels) != len(AGE_GEN_BOUNDS):
        raise ValueError(
            f"{mapping.country}: age_gen_keywords needs {len(AGE_GEN_BOUNDS)} labels, got {labels}"
        )
    young, middle, old = labels
    (_, hi_y), (_, hi_m), _ = AGE_GEN_BOUNDS
    return (
        pl.when(pl.col(AGE) <= hi_y).then(pl.lit(young))
        .when(pl.col(AGE) <= hi_m).then(pl.lit(middle))
        .otherwise(pl.lit(old))
        .alias(AGE_GEN)
    )


def _sex_expr(mapping: CountryMappings) -> pl.Expr | None:
    if mapping.sex_map is None:
        return None
    return pl.col(SEX).replace_strict(mapping.sex_map, default=pl.col(SEX))


def _region_expr(mapping: CountryMappings) -> pl.Expr:
    src = mapping.region_source_col
    if src is None:
        raise ValueError(f"{mapping.country}: region axis declared but region_source_col is None")
    if mapping.region_map is None:
        return pl.col(src).alias(REGION)
    return pl.col(src).replace_strict(mapping.region_map, default="Other").alias(REGION)


def _hobbies_expr() -> pl.Expr:
    return (
        pl.col(HOBBIES_COL)
        .str.strip_chars()
        .str.strip_prefix("[").str.strip_suffix("]")
        .str.replace_all("'", "")
        .str.split(", ")
        .alias("hobbies")
    )


def enrich(
    lf: pl.LazyFrame,
    mapping: CountryMappings,
    occupation_lookup: pl.LazyFrame | None = None,
) -> pl.LazyFrame:
    """Build the enriched LazyFrame to be written as the country store.

    `occupation_lookup` is required when `mapping.occupation_group_definitions` is set
    (Korea/Japan/USA/India). Native-category countries (Singapore/Brazil/France) pass None.
    """
    src = mapping.occupation_source_col
    schema_in = lf.collect_schema().names()

    derived: list[pl.Expr] = [_age_gen_expr(mapping)]
    sex_expr = _sex_expr(mapping)
    if sex_expr is not None:
        derived.append(sex_expr)
    if REGION in mapping.axes:
        derived.append(_region_expr(mapping))
    if HOBBIES_COL in schema_in:
        derived.append(_hobbies_expr())

    base = lf.with_columns(derived)

    if mapping.occupation_group_definitions is None:
        base = base.with_columns(pl.col(src).alias(OCCUPATION_GROUP))
    else:
        if occupation_lookup is None:
            raise ValueError(
                f"{mapping.country}: occupation_lookup required when occupation_group_definitions is set."
            )
        lookup = occupation_lookup.select([
            pl.col("occupation").alias(src),
            pl.col("occupation_group").alias(OCCUPATION_GROUP),
        ])
        base = (
            base.join(lookup, on=src, how="left")
            .with_columns(pl.col(OCCUPATION_GROUP).fill_null("Other"))
        )

    base = base.with_columns(pl.lit(mapping.country).alias("country"))

    schema_now = base.collect_schema().names()
    persona_text_cols = [c for c in mapping.persona_columns if c in schema_now]
    candidate = (
        ["country", UUID, *mapping.axes, AGE]
        + ([mapping.region_source_col]
           if mapping.region_source_col and mapping.region_source_col != REGION
           else [])
        + ([src] if src != OCCUPATION_GROUP else [])
        + (["hobbies"] if "hobbies" in schema_now else [])
        + persona_text_cols
    )
    seen, ordered = set(), []
    for c in candidate:
        if c in schema_now and c not in seen:
            seen.add(c)
            ordered.append(c)
    return base.select(ordered).sort(mapping.axes)
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/unit/test_enrich.py -v`
Expected: 5/5 PASS.

- [ ] **Step 5: Commit**

```bash
git add persona_pipeline/stages/enrich.py tests/unit/test_enrich.py
git commit -m "refactor(enrich): emit store-shaped frame (raw + axes + country, sorted)"
```

---

### Task 4: `store.py` — load + sample (TDD)

**Files:**
- Test: `tests/unit/test_store.py`
- Create: `persona_pipeline/store.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_store.py`:

```python
import polars as pl
import pytest

from persona_pipeline import store


@pytest.fixture
def korea_store(tmp_path, monkeypatch):
    rows = []
    specs = [
        ("수도권", "청년", "여자", "사무", 28, 50),
        ("수도권", "중장년", "남자", "관리자", 50, 30),
        ("영남권", "노년", "여자", "무직", 75, 20),
        ("호남권", "중장년", "여자", "서비스", 50, 10),
    ]
    for region, age_gen, sex, occ_grp, age, n in specs:
        for i in range(n):
            rows.append({
                "country": "Korea",
                "uuid": f"{region}-{sex}-{occ_grp}-{i}",
                "region": region, "age_gen": age_gen, "sex": sex,
                "occupation_group": occ_grp, "age": age + i,
                "province": "서울", "occupation": "...",
                "hobbies": ["독서"],
                "persona": f"persona-text-{i}",
                "professional_persona": f"job-text-{i}",
                "sports_persona": "", "arts_persona": "",
                "travel_persona": "", "culinary_persona": "", "family_persona": "",
            })
    df = pl.DataFrame(rows)
    path = tmp_path / "Korea.parquet"
    df.write_parquet(path, compression="zstd")
    monkeypatch.setattr(store, "store_path", lambda c: tmp_path / f"{c}.parquet")
    return path


def test_load_returns_lazyframe(korea_store):
    lf = store.load("Korea")
    assert isinstance(lf, pl.LazyFrame)
    assert lf.collect().height == 110


def test_sample_returns_n_rows_matching_filter(korea_store):
    df = store.sample("Korea", {"region": "수도권"}, n=5)
    assert len(df) == 5
    assert set(df["region"].unique().to_list()) == {"수도권"}


def test_sample_supports_list_filter(korea_store):
    df = store.sample("Korea", {"region": ["수도권", "영남권"]}, n=20)
    assert len(df) == 20
    assert set(df["region"].unique().to_list()) <= {"수도권", "영남권"}


def test_sample_is_deterministic_for_same_seed(korea_store):
    a = store.sample("Korea", {"region": "수도권"}, n=5, seed=42)
    b = store.sample("Korea", {"region": "수도권"}, n=5, seed=42)
    assert a["uuid"].to_list() == b["uuid"].to_list()


def test_sample_differs_across_seeds(korea_store):
    a = store.sample("Korea", {"region": "수도권"}, n=5, seed=1)
    b = store.sample("Korea", {"region": "수도권"}, n=5, seed=2)
    assert a["uuid"].to_list() != b["uuid"].to_list()


def test_sample_with_no_filter_returns_n_rows(korea_store):
    df = store.sample("Korea", filter=None, n=10)
    assert len(df) == 10


def test_sample_caps_at_population_when_n_exceeds(korea_store):
    df = store.sample("Korea", {"region": "호남권"}, n=999)
    assert len(df) == 10  # only 10 호남권 rows in fixture
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `uv run pytest tests/unit/test_store.py -v`
Expected: ImportError (no module `persona_pipeline.store` yet).

- [ ] **Step 3: Implement `store.py` (load + sample only)**

Create `persona_pipeline/store.py`:

```python
"""Query helpers over the per-country persona store.

The store is a single parquet at `data/store/{country}.parquet` produced by the
`build` CLI. All helpers operate on polars LazyFrames so axis filters get
predicate-pushed down to row-group level.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

DATA = Path("data")


def store_path(country: str) -> Path:
    return DATA / "store" / f"{country}.parquet"


def load(country: str) -> pl.LazyFrame:
    return pl.scan_parquet(store_path(country))


def _apply_filter(lf: pl.LazyFrame, filter: dict | None) -> pl.LazyFrame:
    """`filter` is `{column: value | list[value]}`. Unknown columns raise."""
    if not filter:
        return lf
    schema_cols = set(lf.collect_schema().names())
    for col, val in filter.items():
        if col not in schema_cols:
            raise KeyError(f"filter column '{col}' not in store schema")
        if isinstance(val, (list, tuple)):
            lf = lf.filter(pl.col(col).is_in(list(val)))
        else:
            lf = lf.filter(pl.col(col) == val)
    return lf


def sample(
    country: str, filter: dict | None, n: int, seed: int = 0
) -> pl.DataFrame:
    """Deterministic uniform random sample of up to `n` rows matching `filter`.

    Sampling uses `hash(uuid, seed)` ordering — the same (filter, n, seed) returns
    the same rows. Returns fewer than `n` rows when the filtered population is smaller.
    """
    lf = _apply_filter(load(country), filter)
    return (
        lf.with_columns(pl.col("uuid").hash(seed=seed).alias("_rand"))
          .sort("_rand")
          .head(n)
          .drop("_rand")
          .collect()
    )
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/unit/test_store.py -v`
Expected: 7/7 PASS.

- [ ] **Step 5: Commit**

```bash
git add persona_pipeline/store.py tests/unit/test_store.py
git commit -m "feat(store): add load + deterministic sample helpers"
```

---

### Task 5: `store.py` — distribution + get (TDD)

**Files:**
- Modify: `tests/unit/test_store.py`
- Modify: `persona_pipeline/store.py`

- [ ] **Step 1: Append tests for distribution + get**

Append to `tests/unit/test_store.py`:

```python
def test_distribution_groups_and_counts(korea_store):
    df = store.distribution("Korea", group_by=["region"])
    rows = {r["region"]: r["count"] for r in df.iter_rows(named=True)}
    assert rows == {"수도권": 80, "영남권": 20, "호남권": 10}


def test_distribution_sorted_descending(korea_store):
    df = store.distribution("Korea", group_by=["region"])
    counts = df["count"].to_list()
    assert counts == sorted(counts, reverse=True)


def test_distribution_with_filter(korea_store):
    df = store.distribution("Korea", group_by=["sex"], filter={"region": "수도권"})
    rows = {r["sex"]: r["count"] for r in df.iter_rows(named=True)}
    assert rows == {"여자": 50, "남자": 30}


def test_distribution_multiple_group_by(korea_store):
    df = store.distribution("Korea", group_by=["region", "age_gen"])
    assert df.height == 4  # 4 distinct (region, age_gen) pairs in fixture
    assert "count" in df.columns


def test_get_returns_row_dict(korea_store):
    target_uuid = "수도권-여자-사무-3"
    row = store.get("Korea", target_uuid)
    assert row is not None
    assert row["uuid"] == target_uuid
    assert row["region"] == "수도권"
    assert row["sex"] == "여자"
    assert row["occupation_group"] == "사무"


def test_get_returns_none_when_uuid_missing(korea_store):
    assert store.get("Korea", "does-not-exist") is None
```

- [ ] **Step 2: Run new tests — expect FAIL**

Run: `uv run pytest tests/unit/test_store.py::test_distribution_groups_and_counts -v`
Expected: AttributeError (no `distribution` in store).

- [ ] **Step 3: Implement `distribution` and `get` in `store.py`**

Append to `persona_pipeline/store.py`:

```python
def distribution(
    country: str, group_by: list[str], filter: dict | None = None
) -> pl.DataFrame:
    """Group filtered rows by `group_by` columns and return counts (descending)."""
    lf = _apply_filter(load(country), filter)
    return (
        lf.group_by(group_by)
          .agg(pl.len().alias("count"))
          .sort("count", descending=True)
          .collect()
    )


def get(country: str, uuid: str) -> dict | None:
    """Look up one persona by uuid; return its row as a dict, or None if missing."""
    df = load(country).filter(pl.col("uuid") == uuid).limit(1).collect()
    return df.row(0, named=True) if df.height else None
```

- [ ] **Step 4: Run all store tests — expect PASS**

Run: `uv run pytest tests/unit/test_store.py -v`
Expected: 13/13 PASS.

- [ ] **Step 5: Commit**

```bash
git add persona_pipeline/store.py tests/unit/test_store.py
git commit -m "feat(store): add distribution and get helpers"
```

---

### Task 6: `store.py` — search (TDD)

**Files:**
- Modify: `tests/unit/test_store.py`
- Modify: `persona_pipeline/store.py`

- [ ] **Step 1: Append search tests**

Append to `tests/unit/test_store.py`:

```python
@pytest.fixture
def korea_search_store(tmp_path, monkeypatch):
    rows = [
        {"country": "Korea", "uuid": "u1", "region": "수도권", "age_gen": "청년",
         "sex": "남자", "occupation_group": "전문가", "age": 28, "province": "서울",
         "occupation": "개발자", "hobbies": [],
         "persona": "강남에서 일하는 개발자입니다",
         "professional_persona": "백엔드 시니어",
         "sports_persona": "", "arts_persona": "", "travel_persona": "",
         "culinary_persona": "", "family_persona": ""},
        {"country": "Korea", "uuid": "u2", "region": "영남권", "age_gen": "노년",
         "sex": "여자", "occupation_group": "농림어업", "age": 70, "province": "부산",
         "occupation": "농민", "hobbies": [],
         "persona": "어업 종사자입니다",
         "professional_persona": "갈치잡이",
         "sports_persona": "", "arts_persona": "", "travel_persona": "",
         "culinary_persona": "", "family_persona": "강남에 사는 자녀를 둠"},
    ]
    df = pl.DataFrame(rows)
    path = tmp_path / "Korea.parquet"
    df.write_parquet(path, compression="zstd")
    monkeypatch.setattr(store, "store_path", lambda c: tmp_path / f"{c}.parquet")
    return path


def test_search_substring_across_text_columns(korea_search_store):
    df = store.search("Korea", "강남", top_k=10)
    # u1 has '강남' in persona, u2 has '강남' in family_persona
    assert set(df["uuid"].to_list()) == {"u1", "u2"}


def test_search_respects_top_k(korea_search_store):
    df = store.search("Korea", "강남", top_k=1)
    assert df.height == 1


def test_search_with_filter(korea_search_store):
    df = store.search("Korea", "강남", top_k=10, filter={"region": "수도권"})
    assert df["uuid"].to_list() == ["u1"]


def test_search_no_match_returns_empty(korea_search_store):
    df = store.search("Korea", "지구상에없는단어", top_k=10)
    assert df.height == 0
```

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/unit/test_store.py::test_search_substring_across_text_columns -v`
Expected: AttributeError (no `search`).

- [ ] **Step 3: Implement `search` in `store.py`**

Append to `persona_pipeline/store.py`:

```python
_TEXT_COLS: tuple[str, ...] = (
    "persona", "professional_persona", "sports_persona", "arts_persona",
    "travel_persona", "culinary_persona", "family_persona",
)


def search(
    country: str, query: str, top_k: int = 10, filter: dict | None = None
) -> pl.DataFrame:
    """Substring search across persona text fields.

    v1: literal `str.contains` over each text column. Fast for ~1M rows because
    polars vectorizes the scan and the axes filter (if any) is predicate-pushed
    down before the substring evaluation.
    """
    lf = _apply_filter(load(country), filter)
    schema = lf.collect_schema().names()
    available = [c for c in _TEXT_COLS if c in schema]
    if not available:
        return lf.head(0).collect()
    cond = pl.col(available[0]).str.contains(query, literal=True)
    for c in available[1:]:
        cond = cond | pl.col(c).str.contains(query, literal=True)
    return lf.filter(cond).head(top_k).collect()
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/unit/test_store.py -v`
Expected: 17/17 PASS.

- [ ] **Step 5: Commit**

```bash
git add persona_pipeline/store.py tests/unit/test_store.py
git commit -m "feat(store): add substring search across persona text columns"
```

---

### Task 7: `mcp_server.py` — four tools (TDD)

**Files:**
- Test: `tests/unit/test_mcp_server.py`
- Create: `persona_pipeline/mcp_server.py`

The four `@mcp.tool()` functions are thin wrappers over `store`. Tests call them as plain Python functions (FastMCP's `tool()` decorator returns the wrapped function unchanged), which exercises argument validation + filter assembly + return shape without booting an MCP transport.

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_mcp_server.py`:

```python
import polars as pl
import pytest

from persona_pipeline import mcp_server, store


@pytest.fixture
def korea_store(tmp_path, monkeypatch):
    rows = []
    for i in range(20):
        rows.append({
            "country": "Korea", "uuid": f"k-{i}",
            "region": "수도권" if i < 10 else "영남권",
            "age_gen": "청년" if i % 2 == 0 else "중장년",
            "sex": "여자" if i % 3 == 0 else "남자",
            "occupation_group": "사무",
            "age": 30 + i, "province": "서울", "occupation": "사무원",
            "hobbies": ["독서"],
            "persona": f"persona {i}", "professional_persona": "",
            "sports_persona": "", "arts_persona": "",
            "travel_persona": "", "culinary_persona": "", "family_persona": "",
        })
    pl.DataFrame(rows).write_parquet(tmp_path / "Korea.parquet", compression="zstd")
    monkeypatch.setattr(store, "store_path", lambda c: tmp_path / f"{c}.parquet")


def test_sample_personas_returns_dicts_with_filters(korea_store):
    out = mcp_server.sample_personas(country="Korea", n=3, region=["수도권"])
    assert len(out) == 3
    for p in out:
        assert p["region"] == "수도권"
        assert "persona" in p  # raw text passed through


def test_sample_personas_no_axis_filter(korea_store):
    out = mcp_server.sample_personas(country="Korea", n=5)
    assert len(out) == 5


def test_sample_personas_combines_axis_filters(korea_store):
    out = mcp_server.sample_personas(
        country="Korea", n=10,
        region=["수도권"], age_gen=["청년"], sex=["여자"],
    )
    for p in out:
        assert p["region"] == "수도권"
        assert p["age_gen"] == "청년"
        assert p["sex"] == "여자"


def test_search_personas_returns_matching_substring(korea_store):
    out = mcp_server.search_personas(country="Korea", query="persona 5", top_k=10)
    assert len(out) == 1
    assert out[0]["uuid"] == "k-5"


def test_persona_distribution_by_region(korea_store):
    out = mcp_server.persona_distribution(country="Korea", group_by=["region"])
    rows = {r["region"]: r["count"] for r in out}
    assert rows == {"수도권": 10, "영남권": 10}


def test_get_persona_returns_dict(korea_store):
    out = mcp_server.get_persona(country="Korea", uuid="k-7")
    assert out is not None
    assert out["uuid"] == "k-7"


def test_get_persona_returns_none_when_missing(korea_store):
    assert mcp_server.get_persona(country="Korea", uuid="nope") is None
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/test_mcp_server.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Create `persona_pipeline/mcp_server.py`**

```python
"""MCP server exposing the persona store to LLM clients.

Run with: `python -m persona_pipeline.mcp_server` (stdio transport).
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from persona_pipeline import store

mcp = FastMCP("persona-store")


def _axes_filter(
    region: list[str] | None,
    age_gen: list[str] | None,
    sex: list[str] | None,
    occupation_group: list[str] | None,
) -> dict | None:
    filt = {
        "region": region, "age_gen": age_gen,
        "sex": sex, "occupation_group": occupation_group,
    }
    filt = {k: v for k, v in filt.items() if v}
    return filt or None


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
    """Return up to `n` raw personas from `country`, filtered by axes.

    Use the returned `persona`, `professional_persona`, ... fields directly as
    system-prompt material when role-playing a member of the segment.
    Sampling is deterministic for fixed (filter, n, seed).
    """
    return store.sample(
        country, _axes_filter(region, age_gen, sex, occupation_group), n, seed,
    ).to_dicts()


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
    return store.search(
        country, query, top_k,
        _axes_filter(region, age_gen, sex, occupation_group),
    ).to_dicts()


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
    return store.distribution(
        country, group_by,
        _axes_filter(region, age_gen, sex, occupation_group),
    ).to_dicts()


@mcp.tool()
def get_persona(country: str, uuid: str) -> dict | None:
    """Look up one persona by uuid. Returns None if not found."""
    return store.get(country, uuid)


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/unit/test_mcp_server.py -v`
Expected: 7/7 PASS.

- [ ] **Step 5: Commit**

```bash
git add persona_pipeline/mcp_server.py tests/unit/test_mcp_server.py
git commit -m "feat(mcp): expose four tools (sample/search/distribution/get)"
```

---

### Task 8: CLI — replace stage commands with `build` + `serve`

**Files:**
- Modify: `persona_pipeline/cli/_paths.py`
- Modify: `persona_pipeline/_config.py`
- Create: `persona_pipeline/cli/build.py`
- Create: `persona_pipeline/cli/serve.py`
- Modify: `persona_pipeline/cli/app.py`

- [ ] **Step 1: Replace `cli/_paths.py`**

Overwrite `persona_pipeline/cli/_paths.py`:

```python
"""Per-country data paths."""
from pathlib import Path

DATA = Path("data")


def raw_path(country: str) -> Path:
    return DATA / "raw" / country / "personas.parquet"


def occupation_lookup_path(country: str) -> Path:
    """Versioned data asset: per-country (occupation, group) parquet committed to git."""
    return DATA / "occupation_lookup" / f"{country}.parquet"


def store_path(country: str) -> Path:
    return DATA / "store" / f"{country}.parquet"
```

- [ ] **Step 2: Trim `_config.py`**

Open `persona_pipeline/_config.py` and remove every constant except `ROW_GROUP_SIZE` (used by `io.py`). Constants to delete: anything related to `DEFAULT_MIN_SIZE`, `DEFAULT_MAX_SEGMENTS`, `SAMPLES_PER_SEGMENT`, `HOBBIES_PARSE_CAP_PER_SEGMENT`, `BATCH_SIZE`, etc. Keep only:

```python
ROW_GROUP_SIZE = 100_000  # value already in the file; preserve it
```

(Inspect the existing `_config.py` first; preserve only what `io.py` imports.)

- [ ] **Step 3: Create `cli/build.py`**

```python
"""CLI: build {country} → write data/store/{country}.parquet end-to-end."""
from __future__ import annotations

import polars as pl
import typer

from persona_pipeline import io as io_mod
from persona_pipeline.cli._paths import (
    occupation_lookup_path, raw_path, store_path,
)
from persona_pipeline.cli.app import app
from persona_pipeline.mappings import get_mappings
from persona_pipeline.stages.enrich import enrich


@app.command()
def build(country: str) -> None:
    """Enrich raw personas with axes and write the country store.

    Prerequisites:
      - `download {country}` has run (raw parquet exists)
      - `classify-occupation {country}` has run if the country uses LLM-classified
        occupation groups (Korea/Japan/USA/India)
    """
    mapping = get_mappings(country)
    raw = pl.scan_parquet(raw_path(country))

    lookup = None
    if mapping.occupation_group_definitions is not None:
        lp = occupation_lookup_path(country)
        if not lp.exists():
            raise typer.BadParameter(
                f"occupation lookup missing: {lp}. "
                f"Run `classify-occupation {country}` first."
            )
        lookup = pl.scan_parquet(lp)

    out = store_path(country)
    io_mod.sink_parquet(enrich(raw, mapping, occupation_lookup=lookup), out)
    n_rows = pl.scan_parquet(out).select(pl.len()).collect().item()
    typer.echo(f"build[{country}] → {out} ({n_rows:,} rows)")
```

- [ ] **Step 4: Create `cli/serve.py`**

```python
"""CLI: serve — run the persona MCP server over stdio."""
from __future__ import annotations

import typer

from persona_pipeline.cli.app import app


@app.command()
def serve() -> None:
    """Run the MCP server (stdio transport).

    Connect from an MCP-aware client (Claude Desktop, Claude Code) by registering
    a server pointing to `python -m persona_pipeline.mcp_server`.
    """
    from persona_pipeline.mcp_server import mcp
    typer.echo("starting persona-store MCP server (stdio)...", err=True)
    mcp.run()
```

- [ ] **Step 5: Update `cli/app.py` to register only the surviving commands**

Open `persona_pipeline/cli/app.py` and ensure only these submodules are imported / registered: `download` (`stages.py` currently hosts it — see Task 10), `classify-occupation`, `build`, `serve`. Replace any existing wiring with:

```python
import typer

app = typer.Typer(help="Persona pipeline: build the per-country store and serve it over MCP.")

# Register commands (each module attaches via @app.command())
from persona_pipeline.cli import download  # noqa: F401, E402
from persona_pipeline.cli import classify_occupation  # noqa: F401, E402
from persona_pipeline.cli import build  # noqa: F401, E402
from persona_pipeline.cli import serve  # noqa: F401, E402
```

This requires extracting `download` and `classify-occupation` from the current `stages.py` into their own modules. Do that now:

Create `persona_pipeline/cli/download.py`:

```python
"""CLI: download — fetch raw Nemotron parquet from HuggingFace."""
import typer

from persona_pipeline import io as io_mod
from persona_pipeline.cli._paths import raw_path
from persona_pipeline.cli.app import app


@app.command()
def download(country: str) -> None:
    out = raw_path(country)
    io_mod.download_raw(country, out)
    typer.echo(f"saved → {out}")
```

Create `persona_pipeline/cli/classify_occupation.py`:

```python
"""CLI: classify-occupation — run Anthropic Batches API classifier and write lookup parquet."""
import polars as pl
import typer

from persona_pipeline import io as io_mod
from persona_pipeline.cli._paths import occupation_lookup_path, raw_path
from persona_pipeline.cli.app import app
from persona_pipeline.mappings import get_mappings
from persona_pipeline.stages.classify_occupation import (
    DEFAULT_MODEL as CLS_MODEL,
    classify_occupations,
)


@app.command(name="classify-occupation")
def classify_occupation(country: str, model: str = CLS_MODEL) -> None:
    mapping = get_mappings(country)
    if mapping.occupation_group_definitions is None:
        typer.echo(f"{country} uses native occupation category — no classification needed.")
        return
    raw = pl.scan_parquet(raw_path(country))
    df = classify_occupations(raw, mapping, model=model, progress=typer.echo)
    out = occupation_lookup_path(country)
    io_mod.write_parquet(df, out)
    n_err = int(df.filter(pl.col("error").is_not_null()).height)
    typer.echo(f"classify[{country}] → {out} ({len(df):,} unique values, {n_err} errors)")
```

- [ ] **Step 6: Smoke check — CLI parses**

Run: `uv run python -c "from persona_pipeline.cli.app import app; app(['--help'], standalone_mode=False)"`
Expected: prints help with `download`, `classify-occupation`, `build`, `serve` commands and no others.

- [ ] **Step 7: Commit**

```bash
git add persona_pipeline/cli/ persona_pipeline/_config.py
git commit -m "feat(cli): add build + serve; split download / classify-occupation"
```

---

### Task 9: Trim `validate.py`

**Files:**
- Modify: `persona_pipeline/validate.py`

- [ ] **Step 1: Inspect current `validate.py`**

Run: `cat persona_pipeline/validate.py`
Identify which functions exist (likely `validate_enriched`, `validate_partitioned`, plus helpers).

- [ ] **Step 2: Remove `validate_partitioned`**

Edit `persona_pipeline/validate.py` and delete the `validate_partitioned` function and any segment_id-aware helpers it relies on.

If `validate_enriched` exists and is reusable (e.g. checks raw-axis presence), keep it but adapt the column expectation list to match the new store schema (`country`, `uuid`, all axes, raw text columns). If it only checked partition outputs, delete it instead and leave `validate.py` empty or remove the file (Task 10 will purge tests anyway).

- [ ] **Step 3: Verify imports across the codebase**

Run: `grep -rn "from persona_pipeline.validate\|import validate" persona_pipeline tests scripts 2>/dev/null`
Expected: only references in soon-to-delete files (Task 10) — partition.py, stages.py, test_validate.py.

- [ ] **Step 4: Commit**

```bash
git add persona_pipeline/validate.py
git commit -m "refactor(validate): drop partition-era validators"
```

---

### Task 10: Delete archetype-card pipeline

**Files (delete):**
- `persona_pipeline/stages/partition.py`
- `persona_pipeline/stages/archetype.py`
- `persona_pipeline/stages/match.py`
- `persona_pipeline/stages/simulate.py`
- `persona_pipeline/cli/archetype.py`
- `persona_pipeline/cli/match.py`
- `persona_pipeline/cli/simulate.py`
- `persona_pipeline/cli/stages.py`
- `tests/unit/test_partition.py`
- `tests/unit/test_match.py`
- `tests/unit/test_workflow.py`
- `tests/unit/test_simulate.py`
- `tests/unit/test_validate.py`
- `scripts/simulate_poc.py`
- `scripts/diagnose_occupation.py`
- `data/archetypes/`, `data/cache/`, `data/simulations/` (directories)

- [ ] **Step 1: Delete obsolete source / test files**

Run:
```bash
git rm persona_pipeline/stages/partition.py \
       persona_pipeline/stages/archetype.py \
       persona_pipeline/stages/match.py \
       persona_pipeline/stages/simulate.py \
       persona_pipeline/cli/archetype.py \
       persona_pipeline/cli/match.py \
       persona_pipeline/cli/simulate.py \
       persona_pipeline/cli/stages.py \
       tests/unit/test_partition.py \
       tests/unit/test_match.py \
       tests/unit/test_workflow.py \
       tests/unit/test_simulate.py \
       tests/unit/test_validate.py
git rm -f scripts/simulate_poc.py scripts/diagnose_occupation.py 2>/dev/null || true
```

- [ ] **Step 2: Delete generated data directories**

Run:
```bash
rm -rf data/archetypes data/cache data/simulations
```
(These are gitignored, so no `git rm`.)

- [ ] **Step 3: Add `data/store/` to .gitignore**

Edit `.gitignore`. The "Data outputs" block currently reads:
```
data/raw/
data/cache/
data/archetypes/
data/analysis/
data/simulations/
```
Replace with:
```
data/raw/
data/store/
data/analysis/
```
(`cache`, `archetypes`, `simulations` directories no longer exist; `store` replaces them.)

- [ ] **Step 4: Run remaining tests — expect PASS**

Run: `uv run pytest tests/unit/ -v`
Expected: only `test_enrich.py`, `test_mappings.py`, `test_store.py`, `test_mcp_server.py` collected; all pass.

If `test_mappings.py` references `parse_segment` or other deleted symbols, edit it now to remove those tests.

- [ ] **Step 5: Verify the codebase has no dangling references**

Run:
```bash
uv run python -c "from persona_pipeline.cli.app import app"
uv run python -c "from persona_pipeline import store, mcp_server"
uv run python -c "from persona_pipeline.stages.enrich import enrich"
uv run python -c "from persona_pipeline.stages.classify_occupation import classify_occupations"
```
Expected: all import without error.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: remove partition/archetype/match/simulate pipeline"
```

---

### Task 11: README + Makefile rewrite

**Files:**
- Modify: `README.md`
- Modify: `Makefile`

- [ ] **Step 1: Rewrite `README.md`**

Overwrite with:

```markdown
# persona-pipeline

Multi-country raw-persona MCP server over Nemotron-Personas (USA / Japan / India / Singapore / Brazil / France / Korea, ~1M personas each). LLM clients query the server to fetch raw personas filtered by demographic axes.

## Quick start

```bash
make download COUNTRY=Korea           # HF Nemotron-Personas-Korea
make classify COUNTRY=Korea           # Anthropic Batches: occupation → group lookup
make build COUNTRY=Korea              # write data/store/Korea.parquet
make serve                            # run MCP server (stdio)
```

`make build COUNTRY=Korea` requires `data/occupation_lookup/Korea.parquet`, which `classify` produces (committed to git as a versioned asset). Native-category countries (Singapore/Brazil/France) skip `classify`.

## Pipeline

```
raw (HF dataset, gitignore)
  ↓ classify-occupation   Anthropic Batches → (occupation, occupation_group) lookup parquet (git-tracked)
  ↓ build                 enrich raw with axes (region, age_gen, occupation_group) + sort
data/store/{country}.parquet  (gitignore, deterministic from raw + lookup + code)
  ↓ serve
MCP server (stdio) exposes:
  • sample_personas(country, n, region?, age_gen?, sex?, occupation_group?, seed?)
  • search_personas(country, query, top_k, axes filters?)
  • persona_distribution(country, group_by, axes filters?)
  • get_persona(country, uuid)
```

LLM clients (Claude Desktop / Claude Code / external) connect to the MCP server, sample raw personas, and use them as system-prompt material in their own simulation/analysis flows. We do not host simulation.

## Country mappings

`persona_pipeline/mappings/{korea,japan,...}.py` — per-country rules in a `CountryMappings` dataclass:
- `axes`: which demographic axes the store carries (Singapore has no region → 3 axes)
- `region_source_col` + `region_map`: native administrative division → regional grouping
- `occupation_group_definitions`: label → description fed to the classifier (Korea/Japan/USA/India). Singapore/Brazil/France use the dataset's native category column.

## Layout

```
persona_pipeline/
├── _config.py              constants (ROW_GROUP_SIZE)
├── mappings/               per-country rules + axis name constants
├── stages/
│   ├── enrich.py           raw → store-shaped LazyFrame
│   └── classify_occupation.py  Anthropic Batches occupation classifier
├── store.py                load / sample / distribution / get / search helpers
├── mcp_server.py           FastMCP server with four tools
├── validate.py             schema sanity checks
├── io.py                   atomic parquet write + HF download
└── cli/                    Typer commands

tests/                      pytest
docs/superpowers/           specs / plans
```
```

- [ ] **Step 2: Rewrite `Makefile`**

Overwrite with:

```make
COUNTRY ?= Korea

.PHONY: download classify build serve test

download:
	uv run python -m persona_pipeline.cli download $(COUNTRY)

classify:
	uv run python -m persona_pipeline.cli classify-occupation $(COUNTRY)

build:
	uv run python -m persona_pipeline.cli build $(COUNTRY)

serve:
	uv run python -m persona_pipeline.cli serve

test:
	uv run pytest tests/ -v
```

- [ ] **Step 3: Commit**

```bash
git add README.md Makefile
git commit -m "docs: rewrite README and Makefile for MCP server architecture"
```

---

### Task 12: End-to-end smoke

**Files:** none modified — runtime check only.

- [ ] **Step 1: Build Korea store**

(Skip if raw + occupation_lookup are not present locally; this step requires real data.)

Run: `make build COUNTRY=Korea`
Expected: `data/store/Korea.parquet` created. Output reports row count (~1M).

- [ ] **Step 2: Verify store schema**

Run:
```bash
uv run python -c "
import polars as pl
df = pl.scan_parquet('data/store/Korea.parquet')
print(df.collect_schema())
print('rows:', df.select(pl.len()).collect().item())
print('regions:', df.select('region').unique().collect()['region'].to_list())
print('age_gens:', df.select('age_gen').unique().collect()['age_gen'].to_list())
print('occupations:', df.select('occupation_group').unique().collect()['occupation_group'].to_list())
"
```
Expected: schema has `country`, `uuid`, axes, raw text columns; row count ~1,000,000; axes contain expected labels.

- [ ] **Step 3: Spot-check store helpers**

Run:
```bash
uv run python -c "
from persona_pipeline import store
out = store.sample('Korea', {'region': '수도권', 'age_gen': '청년', 'sex': '여자', 'occupation_group': '사무'}, n=3, seed=0)
for r in out.iter_rows(named=True):
    print(r['uuid'], r['region'], r['age_gen'], r['sex'], r['occupation_group'])
    print('  persona:', r['persona'][:80])
"
```
Expected: 3 rows, all matching the axis filter, with non-empty persona text.

- [ ] **Step 4: Verify MCP server starts (no client connect)**

Run: `timeout 2 uv run python -m persona_pipeline.mcp_server || true`
Expected: process starts and waits on stdin (no stack trace). 2s timeout terminates it.

- [ ] **Step 5: Final test run**

Run: `uv run pytest tests/ -v`
Expected: all tests pass; counts approximately match `test_enrich.py` (5) + `test_store.py` (17) + `test_mcp_server.py` (7) + `test_mappings.py` (existing).

- [ ] **Step 6: No commit**

This task is verification only. If any step fails, fix the underlying issue and add a commit there; otherwise no commit needed.

---

## Notes for the implementing engineer

- **TDD discipline:** every helper-creating task writes the test first, runs it red, then implements. Don't skip the red step — it confirms the test actually exercises the new code.
- **Frequent commits:** each task ends with a single commit. If a task spans multiple commits (e.g. fixing test fallout in unrelated files), commit each cleanly. Don't squash.
- **YAGNI:** the spec explicitly excludes embedding search, HTTP transport, validate harness, axes redefinition. Resist the urge to add them while you're nearby — they belong in separate plans.
- **Determinism:** `store.sample` MUST stay deterministic for fixed `(filter, n, seed)`. The hash-based ordering pattern (from the deleted `archetype.py`) is the simplest way; tests assert this.
- **MCP SDK API surface:** `mcp.server.fastmcp.FastMCP` is stable as of `mcp>=1.2`. If you hit an import error, check the installed version with `uv pip show mcp` and adjust to the SDK's current entry point — but the FastMCP decorator pattern (typed signatures → JSON schema) is unlikely to change.
- **Native-category countries:** Singapore/Brazil/France have `occupation_group_definitions=None`. The `build` CLI must handle them without requiring `classify-occupation`. The current Task 8 code does this via the `if mapping.occupation_group_definitions is not None` check.
