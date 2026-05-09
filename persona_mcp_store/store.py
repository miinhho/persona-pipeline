"""Query helpers over the per-country persona store.

The store is a single parquet at `<store_dir>/{country}.parquet` produced by the
`build` CLI, where `<store_dir>` defaults to `data/store` and is overridable via
the `PERSONA_STORE_DATA_DIR` env var. All helpers operate on polars LazyFrames
so axis filters get predicate-pushed down to row-group level.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from persona_mcp_store.mappings import get_mappings

ENV_DATA_DIR = "PERSONA_STORE_DATA_DIR"
DEFAULT_STORE_DIR = "data/store"


def store_dir() -> Path:
    """Per-country store directory. Reads `PERSONA_STORE_DATA_DIR` on each call."""
    return Path(os.environ.get(ENV_DATA_DIR, DEFAULT_STORE_DIR))


def store_path(country: str) -> Path:
    return store_dir() / f"{country}.parquet"


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


def list_built_countries() -> list[str]:
    """Return sorted list of countries with a catalog sidecar on disk."""
    return sorted(
        p.name.removesuffix(".catalog.json")
        for p in store_dir().glob("*.catalog.json")
    )


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
