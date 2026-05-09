"""MCP server exposing the persona store to LLM clients.

Run with: `python -m persona_pipeline.mcp_server` (stdio transport).
"""
from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from time import perf_counter

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError

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
        raise ToolError(f"unknown country '{country}'. {exc.args[0]}") from exc
    path = store.store_path(country)
    if not path.exists():
        raise ToolError(
            f"country store not built: '{country}'. Run `build {country}` first"
            f" (looked at: {path})."
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
    _validate_country(country)
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
    _validate_country(country)
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
    _validate_country(country)
    return store.distribution(
        country, group_by,
        _axes_filter(region, age_gen, sex, occupation_group),
    ).to_dicts()


@mcp.tool()
def get_persona(country: str, uuid: str) -> dict | None:
    """Look up one persona by uuid. Returns None if not found."""
    _validate_country(country)
    return store.get(country, uuid)


if __name__ == "__main__":
    mcp.run()
