"""Atomic parquet write + HF dataset download."""

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import polars as pl
from datasets import load_dataset

from persona_pipeline._config import ROW_GROUP_SIZE
from persona_pipeline.mappings import get_mappings


@contextmanager
def _atomic_parquet_path(path: Path | str) -> Iterator[Path]:
    """Write to a tempfile, atomic-move on success, cleanup on failure."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_str = tempfile.mkstemp(suffix=".tmp.parquet", dir=out.parent)
    os.close(tmp_fd)
    tmp = Path(tmp_str)
    try:
        yield tmp
        shutil.move(tmp, out)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def write_parquet(df: pl.DataFrame, path: Path | str) -> None:
    with _atomic_parquet_path(path) as tmp:
        df.write_parquet(tmp, compression="zstd", row_group_size=ROW_GROUP_SIZE)


def sink_parquet(lf: pl.LazyFrame, path: Path | str) -> None:
    with _atomic_parquet_path(path) as tmp:
        lf.sink_parquet(tmp, compression="zstd", row_group_size=ROW_GROUP_SIZE)


def download_raw(country: str, out_path: Path | str) -> Path:
    mapping = get_mappings(country)
    ds = load_dataset(f"nvidia/Nemotron-Personas-{country}", split=mapping.hf_split)
    df = pl.from_arrow(ds.data.table)
    out = Path(out_path)
    write_parquet(cast(pl.DataFrame, df), out)
    return out
