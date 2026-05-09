# MCP UX Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add catalog discovery (MCP resources), observability (Context logging), and error UX (ToolError + Pydantic Field) to the existing persona-store MCP server.

**Architecture:** `cli/build` writes a per-country `*.catalog.json` sidecar at the same time as the parquet store. Two new MCP resources expose the catalog (`personas://catalog`, `personas://catalog/{country}`). All four tools gain a `Context` parameter, a `_observe` context manager wraps every call for start/finish/elapsed/error logging, and a `_validate_axis_names` helper raises `ToolError` (with catalog URI in the message) for invalid filter / group_by columns. Pydantic `Annotated[..., Field(description=...)]` adds self-correcting parameter docs and integer bounds.

**Tech Stack:** Python 3.11, polars 1.x, mcp SDK 1.27 (FastMCP + Context + ToolError + resource template), pydantic 2.x (Field metadata), pytest, json (stdlib).

---

## File Structure

**Modify:**
- `persona_pipeline/store.py` — append `catalog_path`, `write_catalog`, `load_catalog` helpers
- `persona_pipeline/cli/build.py` — call `store.write_catalog(country)` after `sink_parquet`
- `persona_pipeline/mcp_server.py` — `_observe` context manager, `_validate_axis_names` helper, `ctx: Context | None = None` and `Annotated[..., Field(...)]` on all four tools, two new `@mcp.resource` handlers
- `tests/unit/test_store.py` — append catalog tests
- `tests/unit/test_mcp_server.py` — append observability / error UX / resource tests

**Create:** none.
**Delete:** none.

`.gitignore` already covers `data/store/`, so `*.catalog.json` sidecars are automatically ignored.

---

## Tasks

### Task 1: store.py — catalog helpers (TDD)

**Files:**
- Test: `tests/unit/test_store.py`
- Modify: `persona_pipeline/store.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_store.py`:

```python
import json


def test_catalog_path_returns_sidecar_alongside_store():
    p = store.catalog_path("Korea")
    assert p.name == "Korea.catalog.json"
    assert p.parent == store.store_path("Korea").parent


def test_write_catalog_produces_expected_schema(korea_store):
    out = store.write_catalog("Korea")
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["country"] == "Korea"
    assert data["n_personas"] == 110  # fixture has 110 rows
    assert set(data["axes"].keys()) == {"region", "age_gen", "sex", "occupation_group"}
    assert data["axes"]["region"]["수도권"] == 80
    assert data["axes"]["region"]["영남권"] == 20
    assert data["axes"]["region"]["호남권"] == 10
    assert "country" in data["schema"]
    assert "uuid" in data["schema"]
    assert "persona" in data["schema"]
    assert "built_at" in data and data["built_at"].endswith("Z")


def test_load_catalog_round_trips(korea_store):
    store.write_catalog("Korea")
    loaded = store.load_catalog("Korea")
    assert loaded is not None
    assert loaded["country"] == "Korea"
    assert loaded["n_personas"] == 110


def test_load_catalog_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "store_path", lambda c: tmp_path / f"{c}.parquet")
    assert store.load_catalog("Atlantis") is None
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/test_store.py -v -k catalog`
Expected: AttributeError (no `catalog_path` / `write_catalog` / `load_catalog` in store).

- [ ] **Step 3: Implement helpers**

Append to `persona_pipeline/store.py`:

```python
import json
from datetime import datetime, timezone

from persona_pipeline.mappings import get_mappings


def catalog_path(country: str) -> Path:
    """Sidecar JSON next to the country store parquet."""
    return store_path(country).with_suffix("").with_suffix(".catalog.json")


def write_catalog(country: str) -> Path:
    """Compute axes value-counts + schema from the country store and write the sidecar.

    Reads the just-written `{country}.parquet`, groups by each axis declared in the
    country's mapping, and emits a JSON document with the structure documented in
    `docs/superpowers/specs/2026-05-09-mcp-ux-upgrade-design.md`.
    """
    mapping = get_mappings(country)
    lf = load(country)
    schema = lf.collect_schema()
    n_personas = lf.select(pl.len()).collect().item()
    axes: dict[str, dict[str, int]] = {}
    for axis in mapping.axes:
        df = (
            lf.group_by(axis)
              .agg(pl.len().alias("count"))
              .sort("count", descending=True)
              .collect()
        )
        axes[axis] = {row[axis]: row["count"] for row in df.iter_rows(named=True)}
    data = {
        "country": country,
        "n_personas": n_personas,
        "axes": axes,
        "schema": list(schema.names()),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    out = catalog_path(country)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return out


def load_catalog(country: str) -> dict | None:
    """Read the catalog sidecar; return None if absent."""
    path = catalog_path(country)
    if not path.exists():
        return None
    return json.loads(path.read_text())
```

Note: `with_suffix("").with_suffix(".catalog.json")` strips the `.parquet` suffix and replaces it. This yields `Korea.catalog.json` next to `Korea.parquet`.

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/unit/test_store.py -v`
Expected: 4 new + 17 existing = 21/21 pass.

- [ ] **Step 5: Commit**

```bash
git add persona_pipeline/store.py tests/unit/test_store.py
git commit -m "feat(store): add catalog sidecar helpers (path / write / load)"
```

---

### Task 2: cli/build.py — wire write_catalog

**Files:**
- Modify: `persona_pipeline/cli/build.py`

This task has no unit test (the catalog logic is fully tested in Task 1; here we only wire the call). End-to-end smoke runs in Task 7.

- [ ] **Step 1: Modify `cli/build.py` to call `store.write_catalog`**

Open `persona_pipeline/cli/build.py`. Add `from persona_pipeline import store` at the top of the imports (alongside the existing `from persona_pipeline import io as io_mod`). Then inside the `build` function, after the `n_rows = ...` computation and the existing `typer.echo` line, append two lines that write the catalog sidecar and report it.

Final body (replace the entire function):

```python
from __future__ import annotations

import polars as pl
import typer

from persona_pipeline import io as io_mod, store
from persona_pipeline.cli._paths import (
    occupation_lookup_path, raw_path,
)
from persona_pipeline.cli.app import app
from persona_pipeline.mappings import get_mappings
from persona_pipeline.stages.enrich import enrich
from persona_pipeline.store import store_path


@app.command()
def build(country: str) -> None:
    """Enrich raw personas with axes and write the country store + catalog sidecar.

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

    catalog_out = store.write_catalog(country)
    typer.echo(f"catalog[{country}] → {catalog_out}")
```

Note: `from persona_pipeline.store import store_path` replaces `from persona_pipeline.cli._paths import store_path` (already removed in P1 cleanup; verify the existing build.py imports `store_path` from the right place — it should be `persona_pipeline.store`, not `cli._paths`).

- [ ] **Step 2: Smoke check — module imports cleanly**

Run: `uv run python -c "from persona_pipeline.cli import build as b; print('build import ok')"`
Expected: `build import ok`.

- [ ] **Step 3: Smoke check — full test suite still green**

Run: `uv run pytest tests/ -v`
Expected: same count as after Task 1 (21 store tests + others), all pass.

- [ ] **Step 4: Commit**

```bash
git add persona_pipeline/cli/build.py
git commit -m "feat(cli): write catalog sidecar at end of build"
```

---

### Task 3: mcp_server.py — `_observe` context manager (TDD)

**Files:**
- Test: `tests/unit/test_mcp_server.py`
- Modify: `persona_pipeline/mcp_server.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_mcp_server.py`:

```python
from unittest.mock import MagicMock
from mcp.server.fastmcp.exceptions import ToolError as _ToolError

from persona_pipeline.mcp_server import _observe as _observe_for_test  # noqa: E402


def test_observe_logs_start_and_finish_when_ctx_provided():
    ctx = MagicMock()
    with _observe_for_test(ctx, "myop", x=1, y="a"):
        pass
    # Two info calls: start with params, finish with elapsed_ms
    assert ctx.info.call_count == 2
    start_msg = ctx.info.call_args_list[0].args[0]
    finish_msg = ctx.info.call_args_list[1].args[0]
    assert "myop" in start_msg and "x=1" in start_msg and "y='a'" in start_msg
    assert "myop" in finish_msg and "ms" in finish_msg


def test_observe_silent_when_ctx_is_none():
    # Must not raise; must not require ctx methods
    with _observe_for_test(None, "myop", x=1):
        pass


def test_observe_logs_error_on_unexpected_exception():
    ctx = MagicMock()
    with pytest.raises(ValueError):
        with _observe_for_test(ctx, "myop"):
            raise ValueError("boom")
    ctx.error.assert_called_once()
    err_msg = ctx.error.call_args.args[0]
    assert "ValueError" in err_msg and "boom" in err_msg


def test_observe_does_not_log_error_on_tool_error():
    ctx = MagicMock()
    with pytest.raises(_ToolError):
        with _observe_for_test(ctx, "myop"):
            raise _ToolError("user-facing")
    ctx.error.assert_not_called()
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/test_mcp_server.py -v -k observe`
Expected: ImportError on `_observe` (not yet defined).

- [ ] **Step 3: Implement `_observe`**

Add to `persona_pipeline/mcp_server.py` near the top (after imports, before the existing `_axes_filter` helper):

```python
from contextlib import contextmanager
from time import perf_counter

from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError


@contextmanager
def _observe(ctx: Context | None, op: str, **params):
    """Bracket a tool call with start/finish/elapsed/error logs through MCP Context.

    `ToolError` is treated as user-facing and re-raised silently (the message is the
    response). Any other exception is logged as an error before re-raising — these
    indicate server-side bugs that we want surfaced to the client log channel.
    """
    t0 = perf_counter()
    if ctx is not None:
        ctx.info(f"{op}: " + " ".join(f"{k}={v!r}" for k, v in params.items()))
    try:
        yield
    except ToolError:
        raise
    except Exception as e:
        if ctx is not None:
            ctx.error(f"{op} failed: {type(e).__name__}: {e}")
        raise
    finally:
        ms = int((perf_counter() - t0) * 1000)
        if ctx is not None:
            ctx.info(f"{op}: done in {ms}ms")
```

`Context` and `ToolError` may already be imported earlier (P1 added `ToolError`); avoid duplicating imports — adjust to single import lines if needed.

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/unit/test_mcp_server.py -v -k observe`
Expected: 4/4 pass.

- [ ] **Step 5: Commit**

```bash
git add persona_pipeline/mcp_server.py tests/unit/test_mcp_server.py
git commit -m "feat(mcp): add _observe context manager for tool call logging"
```

---

### Task 4: mcp_server.py — `_validate_axis_names` helper (TDD)

**Files:**
- Test: `tests/unit/test_mcp_server.py`
- Modify: `persona_pipeline/mcp_server.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_mcp_server.py`:

```python
from persona_pipeline.mcp_server import _validate_axis_names as _validate_for_test  # noqa: E402


def test_validate_axis_names_passes_when_all_valid():
    # Korea has 4 axes; no exception expected
    _validate_for_test("Korea", ["region", "sex"], purpose="filter axis")


def test_validate_axis_names_raises_tool_error_when_unknown():
    with pytest.raises(_ToolError) as exc_info:
        _validate_for_test("Korea", ["region", "foo"], purpose="filter axis")
    msg = str(exc_info.value)
    assert "filter axis" in msg
    assert "foo" in msg
    assert "personas://catalog/Korea" in msg
    # Lists the valid axes for the country
    for axis in ["region", "age_gen", "sex", "occupation_group"]:
        assert axis in msg


def test_validate_axis_names_singapore_rejects_region():
    # Singapore has no region axis (city-state); region must be rejected
    with pytest.raises(_ToolError) as exc_info:
        _validate_for_test("Singapore", ["region"], purpose="filter axis")
    assert "region" in str(exc_info.value)
    assert "Singapore" in str(exc_info.value)
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/test_mcp_server.py -v -k validate_axis_names`
Expected: ImportError on `_validate_axis_names`.

- [ ] **Step 3: Implement `_validate_axis_names`**

Add to `persona_pipeline/mcp_server.py` next to `_validate_country`:

```python
from collections.abc import Iterable


def _validate_axis_names(country: str, names: Iterable[str], *, purpose: str) -> None:
    """Raise `ToolError` if any name is not in `mapping.axes` for `country`.

    `purpose` is a short noun phrase used in the error message ("filter axis",
    "group_by axis"). The message lists the valid axis set and the catalog URI
    so the LLM client can self-correct on the next call.
    """
    valid = list(get_mappings(country).axes)
    bad = [n for n in names if n not in valid]
    if bad:
        raise ToolError(
            f"unknown {purpose}: {bad}. valid for {country}: {valid}. "
            f"See personas://catalog/{country}."
        )
```

`get_mappings` is already imported in `mcp_server.py` (used by `_validate_country`); no new import needed.

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/unit/test_mcp_server.py -v -k validate_axis_names`
Expected: 3/3 pass.

- [ ] **Step 5: Commit**

```bash
git add persona_pipeline/mcp_server.py tests/unit/test_mcp_server.py
git commit -m "feat(mcp): add _validate_axis_names helper with catalog URI hint"
```

---

### Task 5: Apply `Context` + `Field` + `_observe` + `_validate_axis_names` to four tools

**Files:**
- Test: `tests/unit/test_mcp_server.py`
- Modify: `persona_pipeline/mcp_server.py`

This task rewrites the four `@mcp.tool()` functions in one shot. We add tests for the new behavior first (RED), then rewrite the tools (GREEN).

- [ ] **Step 1: Append regression + new-behavior tests**

Append to `tests/unit/test_mcp_server.py`:

```python
def test_sample_personas_with_ctx_logs_two_info_calls(korea_store):
    ctx = MagicMock()
    out = mcp_server.sample_personas(country="Korea", n=2, ctx=ctx)
    assert len(out) == 2
    # Two info calls (start + finish)
    assert ctx.info.call_count >= 2
    start_msg = ctx.info.call_args_list[0].args[0]
    assert "sample_personas" in start_msg


def test_sample_personas_empty_filter_result_warns(korea_store):
    # Filter to a region that doesn't exist in the fixture; expect zero rows + warning
    ctx = MagicMock()
    out = mcp_server.sample_personas(
        country="Korea", n=5, region=["존재하지않는지역"], ctx=ctx
    )
    assert out == []
    ctx.warning.assert_called_once()
    warn_msg = ctx.warning.call_args.args[0]
    assert "empty" in warn_msg.lower()


def test_persona_distribution_unknown_group_by_raises_tool_error(korea_store):
    with pytest.raises(_ToolError) as exc_info:
        mcp_server.persona_distribution(country="Korea", group_by=["foo"])
    msg = str(exc_info.value)
    assert "group_by axis" in msg
    assert "foo" in msg
    assert "personas://catalog/Korea" in msg


def test_sample_personas_default_ctx_none_still_works(korea_store):
    # Regression: existing tests pass ctx implicitly as None
    out = mcp_server.sample_personas(country="Korea", n=1)
    assert len(out) == 1
```

- [ ] **Step 2: Run new tests — expect FAIL**

Run: `uv run pytest tests/unit/test_mcp_server.py -v -k "with_ctx_logs or empty_filter_result or unknown_group_by or default_ctx_none"`
Expected: failures — `ctx` is not yet a tool parameter, no warning is logged on empty result, group_by is not validated.

- [ ] **Step 3: Rewrite the four tools**

Replace the four tool functions in `persona_pipeline/mcp_server.py` with the versions below. Keep the existing module-level imports / helpers (`mcp`, `_axes_filter`, `_validate_country`, `_validate_axis_names`, `_observe`) intact and add the `Annotated` / `Field` imports if not present.

Imports at top of file (consolidate; final form):

```python
"""MCP server exposing the persona store to LLM clients.

Run with: `python -m persona_pipeline.mcp_server` (stdio transport).
"""
from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from time import perf_counter
from typing import Annotated

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

from persona_pipeline import store
from persona_pipeline.mappings import get_mappings

mcp = FastMCP("persona-store")
```

Tool definitions (replace existing four):

```python
@mcp.tool()
def sample_personas(
    country: Annotated[str, Field(description=
        "Country name. List built countries: read 'personas://catalog'."
    )],
    n: Annotated[int, Field(ge=1, le=1000, description=
        "Number of personas to return (1-1000)."
    )] = 10,
    region: Annotated[list[str] | None, Field(description=
        "Filter by region. Values per country in 'personas://catalog/{country}'."
    )] = None,
    age_gen: Annotated[list[str] | None, Field(description=
        "Filter by age generation. Values per country in 'personas://catalog/{country}'."
    )] = None,
    sex: Annotated[list[str] | None, Field(description=
        "Filter by sex. Values per country in 'personas://catalog/{country}'."
    )] = None,
    occupation_group: Annotated[list[str] | None, Field(description=
        "Filter by occupation group. Values per country in 'personas://catalog/{country}'."
    )] = None,
    seed: Annotated[int, Field(ge=0, description=
        "Same (filter, n, seed) returns identical rows. Use for reproducibility."
    )] = 0,
    ctx: Context | None = None,
) -> list[dict]:
    """Return up to `n` raw personas from `country`, filtered by axes.

    Use the returned `persona`, `professional_persona`, ... fields directly as
    system-prompt material when role-playing a member of the segment.
    Sampling is deterministic for fixed (filter, n, seed).
    """
    _validate_country(country)
    filt = _axes_filter(region, age_gen, sex, occupation_group)
    if filt:
        _validate_axis_names(country, filt.keys(), purpose="filter axis")
    with _observe(ctx, "sample_personas",
                  country=country, n=n, filter=filt, seed=seed):
        result = store.sample(country, filt, n, seed).to_dicts()
        if ctx is not None and not result:
            ctx.warning(f"sample_personas: empty result for filter={filt}")
        return result


@mcp.tool()
def search_personas(
    country: Annotated[str, Field(description=
        "Country name. List built countries: read 'personas://catalog'."
    )],
    query: Annotated[str, Field(description=
        "Literal substring (not regex). Matched against persona, professional_persona, "
        "sports_persona, arts_persona, travel_persona, culinary_persona, family_persona text fields."
    )],
    top_k: Annotated[int, Field(ge=1, le=1000, description=
        "Maximum number of matches to return (1-1000)."
    )] = 10,
    region: Annotated[list[str] | None, Field(description=
        "Optional region filter. Values per country in 'personas://catalog/{country}'."
    )] = None,
    age_gen: Annotated[list[str] | None, Field(description=
        "Optional age generation filter."
    )] = None,
    sex: Annotated[list[str] | None, Field(description=
        "Optional sex filter."
    )] = None,
    occupation_group: Annotated[list[str] | None, Field(description=
        "Optional occupation group filter."
    )] = None,
    ctx: Context | None = None,
) -> list[dict]:
    """Substring search across persona text fields, optionally constrained by axes."""
    _validate_country(country)
    filt = _axes_filter(region, age_gen, sex, occupation_group)
    if filt:
        _validate_axis_names(country, filt.keys(), purpose="filter axis")
    with _observe(ctx, "search_personas",
                  country=country, query=query, top_k=top_k, filter=filt):
        result = store.search(country, query, top_k, filt).to_dicts()
        if ctx is not None and not result:
            ctx.warning(f"search_personas: no matches for query={query!r}")
        return result


@mcp.tool()
def persona_distribution(
    country: Annotated[str, Field(description=
        "Country name. List built countries: read 'personas://catalog'."
    )],
    group_by: Annotated[list[str], Field(description=
        "Axis names to group by. Same set as filter axes; see 'personas://catalog/{country}'."
    )],
    region: Annotated[list[str] | None, Field(description=
        "Optional region filter applied before grouping."
    )] = None,
    age_gen: Annotated[list[str] | None, Field(description=
        "Optional age generation filter applied before grouping."
    )] = None,
    sex: Annotated[list[str] | None, Field(description=
        "Optional sex filter applied before grouping."
    )] = None,
    occupation_group: Annotated[list[str] | None, Field(description=
        "Optional occupation group filter applied before grouping."
    )] = None,
    ctx: Context | None = None,
) -> list[dict]:
    """Group filtered rows by `group_by` columns and return counts (descending)."""
    _validate_country(country)
    _validate_axis_names(country, group_by, purpose="group_by axis")
    filt = _axes_filter(region, age_gen, sex, occupation_group)
    if filt:
        _validate_axis_names(country, filt.keys(), purpose="filter axis")
    with _observe(ctx, "persona_distribution",
                  country=country, group_by=group_by, filter=filt):
        return store.distribution(country, group_by, filt).to_dicts()


@mcp.tool()
def get_persona(
    country: Annotated[str, Field(description=
        "Country name. List built countries: read 'personas://catalog'."
    )],
    uuid: Annotated[str, Field(description=
        "Persona UUID returned in `uuid` field of sample/search results."
    )],
    ctx: Context | None = None,
) -> dict | None:
    """Look up one persona by uuid. Returns None if not found."""
    _validate_country(country)
    with _observe(ctx, "get_persona", country=country, uuid=uuid):
        return store.get(country, uuid)
```

Notes:
- `_axes_filter` and `_validate_country` exist already; do not redefine.
- The `from typing import Annotated` and `from pydantic import Field` imports are required (Python 3.11+ has Annotated in typing; pydantic 2 is already a transitive dep through mcp).
- The `ctx: Context | None = None` parameter must come *after* defaulted typed parameters (Python's rule). All Annotated parameters with defaults are placed first; `ctx` last.

- [ ] **Step 4: Run all tests — expect PASS**

Run: `uv run pytest tests/ -v`
Expected: previous total + 4 new = all green. Existing tests like `test_sample_personas_returns_dicts_with_filters` still pass because they pass kwargs and ctx defaults to None.

- [ ] **Step 5: Commit**

```bash
git add persona_pipeline/mcp_server.py tests/unit/test_mcp_server.py
git commit -m "feat(mcp): add Context logging, Field guidance, and axis-name validation to tools"
```

---

### Task 6: Catalog resources (TDD)

**Files:**
- Test: `tests/unit/test_mcp_server.py`
- Modify: `persona_pipeline/mcp_server.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_mcp_server.py`:

```python
import json as _json


@pytest.fixture
def korea_with_catalog(korea_store):
    """Re-uses the korea_store fixture (which monkeypatches store_path) and writes a catalog."""
    store.write_catalog("Korea")
    return korea_store


def test_catalog_resource_lists_built_countries(korea_with_catalog):
    payload = _json.loads(mcp_server.catalog())
    assert isinstance(payload, list)
    countries = [c["country"] for c in payload]
    assert "Korea" in countries
    korea = next(c for c in payload if c["country"] == "Korea")
    assert korea["n_personas"] == 110
    assert set(korea["axes"]) == {"region", "age_gen", "sex", "occupation_group"}


def test_catalog_resource_returns_empty_list_when_no_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "store_path", lambda c: tmp_path / f"{c}.parquet")
    payload = _json.loads(mcp_server.catalog())
    assert payload == []


def test_country_catalog_resource_returns_axes_and_counts(korea_with_catalog):
    payload = _json.loads(mcp_server.country_catalog("Korea"))
    assert payload["country"] == "Korea"
    assert payload["n_personas"] == 110
    assert payload["axes"]["region"]["수도권"] == 80
    assert "schema" in payload and "uuid" in payload["schema"]


def test_country_catalog_resource_unknown_country_raises_value_error():
    with pytest.raises(ValueError, match="unknown country"):
        mcp_server.country_catalog("Atlantis")
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/test_mcp_server.py -v -k "catalog_resource or country_catalog_resource"`
Expected: AttributeError (`mcp_server.catalog` / `mcp_server.country_catalog` not defined).

- [ ] **Step 3: Implement resources**

Append to `persona_pipeline/mcp_server.py`:

```python
import json
from pathlib import Path


@mcp.resource(
    "personas://catalog",
    name="catalog",
    description="List of built persona stores (one entry per country with n_personas and axes names).",
    mime_type="application/json",
)
def catalog() -> str:
    """Return JSON list of built countries discovered via *.catalog.json sidecars."""
    countries: list[dict] = []
    # Discover by globbing the directory of any country's would-be store path.
    # `store.store_path("_")` resolves the parent directory regardless of the country.
    store_dir = store.store_path("_").parent
    if store_dir.exists():
        for path in sorted(store_dir.glob("*.catalog.json")):
            data = json.loads(path.read_text())
            countries.append({
                "country": data["country"],
                "n_personas": data["n_personas"],
                "axes": list(data["axes"].keys()),
            })
    return json.dumps(countries, ensure_ascii=False)


@mcp.resource(
    "personas://catalog/{country}",
    name="country_catalog",
    description="Per-country catalog: axes with value counts, schema, n_personas, built_at.",
    mime_type="application/json",
)
def country_catalog(country: str) -> str:
    """Return JSON catalog for one country. Raises ValueError if not built."""
    data = store.load_catalog(country)
    if data is None:
        raise ValueError(
            f"unknown country '{country}'. See personas://catalog for built countries."
        )
    return json.dumps(data, ensure_ascii=False)
```

The `store_dir = store.store_path("_").parent` trick yields the configured `data/store` directory (or the test tmp path under monkeypatch) without hardcoding the path — important for the test that monkeypatches `store.store_path`.

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/unit/test_mcp_server.py -v -k "catalog_resource or country_catalog_resource"`
Expected: 4/4 pass. Then full suite: `uv run pytest tests/ -v` — all green.

- [ ] **Step 5: Commit**

```bash
git add persona_pipeline/mcp_server.py tests/unit/test_mcp_server.py
git commit -m "feat(mcp): expose catalog and country_catalog as MCP resources"
```

---

### Task 7: Rebuild Korea catalog + end-to-end smoke

**Files:** none (verification + data regeneration only).

- [ ] **Step 1: Rebuild Korea store with catalog sidecar**

Run: `make build COUNTRY=Korea`
Expected output (last two lines):
```
build[Korea] → data/store/Korea.parquet (1,000,000 rows)
catalog[Korea] → data/store/Korea.catalog.json
```

- [ ] **Step 2: Inspect catalog content**

Run:
```bash
uv run python -c "
import json
data = json.loads(open('data/store/Korea.catalog.json').read())
print('country:', data['country'])
print('n_personas:', data['n_personas'])
print('axes:', list(data['axes']))
print('schema columns:', len(data['schema']))
print('built_at:', data['built_at'])
print('region counts:', data['axes']['region'])
"
```

Expected: country=Korea, n_personas=1000000, four axes (region, age_gen, sex, occupation_group), schema list with country/uuid/persona/etc., built_at ISO-Z timestamp, region counts approximately matching the earlier smoke (수도권 ≈ 506k, 영남권 ≈ 246k, ...).

- [ ] **Step 3: Spot-check resource handlers via direct call**

Run:
```bash
uv run python -c "
from persona_pipeline import mcp_server
import json
print('--- catalog() ---')
print(mcp_server.catalog())
print('--- country_catalog(Korea) ---')
data = json.loads(mcp_server.country_catalog('Korea'))
print('axes keys:', list(data['axes']))
print('region top 3:', list(data['axes']['region'].items())[:3])
"
```

Expected: catalog() returns JSON list with `{"country":"Korea","n_personas":1000000,"axes":["region","age_gen","sex","occupation_group"]}`; country_catalog returns full per-country structure.

- [ ] **Step 4: Spot-check tool with Context (using a stub)**

Run:
```bash
uv run python -c "
from unittest.mock import MagicMock
from persona_pipeline import mcp_server
ctx = MagicMock()
out = mcp_server.sample_personas(country='Korea', n=2, region=['수도권'], age_gen=['청년'], sex=['여자'], occupation_group=['사무'], ctx=ctx)
print('rows:', len(out))
print('logs:')
for c in ctx.info.call_args_list:
    print('  info:', c.args[0])
"
```

Expected: 2 rows, two `info` log lines (start with params, finish with `done in Nms`).

- [ ] **Step 5: MCP server starts cleanly**

Run: `timeout 2 uv run python -m persona_pipeline.mcp_server || true`
Expected: process starts, blocks on stdin, killed by 2s timeout. No stack traces.

- [ ] **Step 6: Full test suite final check**

Run: `uv run pytest tests/ -v`
Expected: every test passes. Approximate count: 64 (post-P1) + ~20 new (Task 1: 4 catalog + Tasks 3/4: 7 helper + Task 5: 4 tool + Task 6: 4 resource = 19) ≈ 83 total.

- [ ] **Step 7: No commit**

Verification only. If any step fails, diagnose and add a fix commit; otherwise no commit needed.

---

## Notes for the implementing engineer

- **TDD discipline:** every helper-creating task writes the test first, runs it red, then implements. Don't skip the red step — it confirms the test actually exercises the new code.
- **Frequent commits:** each task ends with one commit. If a task spans multiple commits (e.g. fixing test fallout), commit each cleanly. Don't squash.
- **Single-source `store_path`:** `cli/build.py` must import `store_path` from `persona_pipeline.store`, not `cli/_paths` (already cleaned up in P1). Don't reintroduce a duplicate.
- **`Annotated[..., Field(...)]` pattern:** required for FastMCP 1.27 + Pydantic 2 to attach descriptions and integer bounds to the JSON schema. Without `Annotated`, `Field()` as a default value also works but the `Annotated` form survives static analysis better and keeps the actual default in the `=` position.
- **Resource handler exception:** unlike tools, MCP resource handlers cannot raise `ToolError` (that's a tool-only protocol error). Use plain `ValueError` — FastMCP forwards it as a resources/read error.
- **Backward compatibility:** all existing tests (P1 + initial migration) must continue to pass without modification. The new `ctx` parameter is optional; existing calls don't pass it. If a test breaks, the change is wrong — don't update the test, fix the code.
- **No new files, no new CLI commands:** this upgrade is additive on existing modules. If you find yourself creating a new module, stop and re-read the plan.
