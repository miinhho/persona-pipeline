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
