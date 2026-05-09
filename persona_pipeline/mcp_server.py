"""MCP server exposing the persona store to LLM clients.

Run with: `python -m persona_pipeline.mcp_server` (stdio transport).
"""
from __future__ import annotations

import json
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


def _validate_country(country: str) -> None:
    """Raise ToolError with a clean message when country is unknown or store not built."""
    try:
        get_mappings(country)
    except KeyError as exc:
        raise ToolError(str(exc.args[0])) from exc
    path = store.store_path(country)
    if not path.exists():
        built = store.list_built_countries()
        built_hint = f" Currently built: {built}." if built else " No countries built yet."
        raise ToolError(
            f"country store not built: '{country}'. Run `build {country}` first"
            f" (looked at: {path}).{built_hint}"
        )


def _validate_axis_values(
    country: str, filter_dict: dict[str, list[str]], *, sample_limit: int = 8
) -> None:
    """Raise `ToolError` if any filter value is absent from the country's catalog.

    Closes the silent-zero failure mode where e.g. `region=["서울"]` (instead of
    "수도권") returns []. Message lists up to `sample_limit` valid values per axis
    and points to the catalog resource for the full list.
    """
    catalog = store.load_catalog(country)
    if catalog is None:
        return  # store exists but no catalog (build sidecar missing); skip silently
    axes_meta: dict[str, dict[str, int]] = catalog.get("axes", {})
    for axis, values in filter_dict.items():
        valid = axes_meta.get(axis)
        if valid is None:
            continue  # axis-name validation handled by _validate_axis_names
        bad = [v for v in values if v not in valid]
        if bad:
            sample = list(valid.keys())[:sample_limit]
            more = len(valid) - sample_limit
            extra = f" (+{more} more)" if more > 0 else ""
            raise ToolError(
                f"unknown {axis} value(s): {bad}. valid {axis} for {country}: "
                f"{sample}{extra}. See personas://catalog/{country}."
            )


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
        _validate_axis_values(country, filt)
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
        _validate_axis_values(country, filt)
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
        _validate_axis_values(country, filt)
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


@mcp.resource(
    "personas://catalog",
    name="catalog",
    description="List of built persona stores (one entry per country with n_personas and axes names).",
    mime_type="application/json",
)
def catalog() -> str:
    """Return JSON list of built countries discovered via *.catalog.json sidecars."""
    countries = []
    for c in store.list_built_countries():
        data = store.load_catalog(c)
        if data is None:
            continue
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


if __name__ == "__main__":
    mcp.run()
