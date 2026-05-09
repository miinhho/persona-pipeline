"""Per-stage invariant checks."""
import sys

import polars as pl

from persona_pipeline._config import (
    DEFAULT_MAX_SEGMENTS, DEFAULT_MIN_SIZE, MAX_SEGMENT_KEYS,
)
from persona_pipeline.mappings import SEGMENT_ID, SEGMENT_KEY, SEGMENT_SEP, UUID


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
    n_axes: int | None = None,
) -> None:
    """Min-size violations on L0 / L1 segments fail; on terminal b2-cascade segments
    they warn — b2 is the last backoff step and a small residual there is unavoidable
    once the data forces it."""
    _require_non_null(lf, UUID, SEGMENT_ID)
    sizes = lf.group_by(SEGMENT_ID).len().collect()
    too_small = sizes.filter(pl.col("len") < min_size)
    if len(too_small) > 0:
        b2_axes_len = max(n_axes - 2, 1) if n_axes else 0
        violations: list[tuple[str, int]] = []
        residuals: list[tuple[str, int]] = []
        for sid, n in too_small.iter_rows():
            depth = len(sid.split(SEGMENT_SEP))
            if n_axes and depth <= b2_axes_len:
                residuals.append((sid, n))
            else:
                violations.append((sid, n))
        if violations:
            head = [f"{sid}({n})" for sid, n in violations[:10]]
            raise ValidationError(f"segment size < {min_size}: {head} ...")
        if residuals:
            head = [f"{sid}({n})" for sid, n in residuals[:5]]
            print(
                f"warn: {len(residuals)} terminal b2-cascade segment(s) below min_size={min_size}: "
                f"{head}{' ...' if len(residuals) > 5 else ''}",
                file=sys.stderr,
            )
    if len(sizes) > max_segments:
        raise ValidationError(
            f"segment_id cardinality {len(sizes)} > {max_segments} (insufficient backoff merge)"
        )
