"""segment_key → segment_id with backoff merge (PyArrow Dataset 2-pass)."""
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from persona_pipeline._config import BATCH_SIZE
from persona_pipeline.io import atomic_parquet_path
from persona_pipeline.mappings import (
    SEGMENT_ID, SEGMENT_KEY, SEGMENT_SEP, CountryMappings, backoff_axes,
)


def _join_axes_array(batch: pa.RecordBatch, axes: list[str]) -> pa.Array:
    if len(axes) == 1:
        return batch.column(axes[0]).cast(pa.string())
    cols = [batch.column(a).cast(pa.string()) for a in axes]
    return pc.binary_join_element_wise(*cols, SEGMENT_SEP)  # type: ignore[attr-defined]


def _decide_segment_id(
    sk: str,
    seg_to_b1: dict[str, str],
    seg_to_b2: dict[str, str],
    b1_min_l0: dict[str, int],
    l1_count: Counter,
    min_size: int,
) -> str:
    b1 = seg_to_b1[sk]
    if b1_min_l0[b1] >= min_size:
        return sk
    if l1_count[b1] >= min_size:
        return b1
    return seg_to_b2[sk]


def partition(
    input_path: Path | str,
    output_path: Path | str,
    mapping: CountryMappings,
    min_size: int = 100,
) -> None:
    axes = mapping.axes
    if len(axes) < 2:
        raise ValueError(f"axes must contain at least 2 entries, got {axes}")

    b1_axes = backoff_axes(axes, 1)
    b2_axes = backoff_axes(axes, 2)

    dataset = ds.dataset(str(input_path), format="parquet")

    l0_count: Counter = Counter()
    l1_count: Counter = Counter()
    l2_count: Counter = Counter()
    seg_to_b1: dict[str, str] = {}
    seg_to_b2: dict[str, str] = {}

    for batch in dataset.scanner(columns=[*axes, SEGMENT_KEY], batch_size=BATCH_SIZE).to_batches():
        sks = batch.column(SEGMENT_KEY).to_pylist()
        b1s = _join_axes_array(batch, b1_axes).to_pylist()
        b2s = _join_axes_array(batch, b2_axes).to_pylist()
        l0_count.update(sks)
        l1_count.update(b1s)
        l2_count.update(b2s)
        for sk, b1, b2 in zip(sks, b1s, b2s):
            if sk not in seg_to_b1:
                seg_to_b1[sk] = b1
                seg_to_b2[sk] = b2

    # backoff is triggered for a b1 bucket if any of its L0 segments is below min_size.
    b1_min_l0: dict[str, int] = {}
    for sk, count in l0_count.items():
        b1 = seg_to_b1[sk]
        if b1 not in b1_min_l0 or count < b1_min_l0[b1]:
            b1_min_l0[b1] = count

    seg_to_id: dict[str, str] = {
        sk: _decide_segment_id(sk, seg_to_b1, seg_to_b2, b1_min_l0, l1_count, min_size)
        for sk in l0_count
    }

    with atomic_parquet_path(output_path) as tmp:
        writer: pq.ParquetWriter | None = None
        try:
            for batch in dataset.scanner(batch_size=BATCH_SIZE).to_batches():
                sks = batch.column(SEGMENT_KEY).to_pylist()
                seg_id_array = pa.array([seg_to_id[sk] for sk in sks], type=pa.string())
                new_batch = batch.append_column(SEGMENT_ID, seg_id_array)
                if writer is None:
                    writer = pq.ParquetWriter(tmp, new_batch.schema, compression="zstd")
                writer.write_batch(new_batch)
        finally:
            if writer is not None:
                writer.close()
