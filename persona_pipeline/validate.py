"""Per-stage invariant checks."""
import polars as pl

from persona_pipeline._config import (
    DEFAULT_MAX_SEGMENTS, DEFAULT_MIN_SIZE, MAX_SEGMENT_KEYS,
)
from persona_pipeline.mappings import SEGMENT_ID, SEGMENT_KEY, UUID


class ValidationError(Exception):
    pass


def _require_non_null(lf: pl.LazyFrame, *cols: str) -> None:
    schema_cols = set(lf.collect_schema().names())
    for col in cols:
        if col not in schema_cols:
            raise ValidationError(f"missing column: {col}")
    null_counts = lf.select(
        [pl.col(c).null_count().alias(c) for c in cols]
    ).collect().row(0, named=True)
    bad = [c for c, n in null_counts.items() if n > 0]
    if bad:
        raise ValidationError(f"null values found in: {bad}")


def validate_enriched(lf: pl.LazyFrame, axes: list[str]) -> None:
    _require_non_null(lf, UUID, *axes, SEGMENT_KEY)
    n_unique = lf.select(pl.col(SEGMENT_KEY).n_unique()).collect().item()
    if n_unique > MAX_SEGMENT_KEYS:
        raise ValidationError(
            f"segment_key cardinality {n_unique} > {MAX_SEGMENT_KEYS} (segment explosion)"
        )


def validate_partitioned(
    lf: pl.LazyFrame,
    min_size: int = DEFAULT_MIN_SIZE,
    max_segments: int = DEFAULT_MAX_SEGMENTS,
) -> None:
    _require_non_null(lf, UUID, SEGMENT_ID)
    sizes = lf.group_by(SEGMENT_ID).len().collect()
    too_small = sizes.filter(pl.col("len") < min_size)
    if len(too_small) > 0:
        ids = too_small[SEGMENT_ID].to_list()[:10]
        raise ValidationError(f"segment size < {min_size}: {ids} ...")
    if len(sizes) > max_segments:
        raise ValidationError(
            f"segment_id cardinality {len(sizes)} > {max_segments} (insufficient backoff merge)"
        )
