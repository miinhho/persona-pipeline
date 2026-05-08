import polars as pl
import pytest

from persona_pipeline.validate import (
    ValidationError, validate_enriched, validate_partitioned,
)


def test_enriched_fails_when_axis_column_missing():
    lf = pl.LazyFrame({"uuid": ["u1"], "region": ["수도권"], "segment_key": ["x"]})
    with pytest.raises(ValidationError):
        validate_enriched(lf, axes=["region", "age_gen", "sex", "occupation_group"])


def test_partitioned_fails_when_segment_below_min_size():
    lf = pl.LazyFrame({
        "uuid": [f"u{i}" for i in range(50)],
        "segment_id": ["s1"] * 50,
    })
    with pytest.raises(ValidationError, match="100"):
        validate_partitioned(lf, min_size=100)


def test_partitioned_fails_when_too_many_segments():
    n_seg = 600
    lf = pl.LazyFrame({
        "uuid": [f"u{i}" for i in range(n_seg * 100)],
        "segment_id": [f"s{i}" for i in range(n_seg) for _ in range(100)],
    })
    with pytest.raises(ValidationError, match="500"):
        validate_partitioned(lf, min_size=100, max_segments=500)
