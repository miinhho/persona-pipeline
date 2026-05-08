"""Download a single country — intended for parallel runs.

Splits are pinned per country (verified up-front):
- USA / Japan / Singapore / Brazil / France / Korea: train
- India: en_IN (English of the multilingual splits)
"""

import sys
from pathlib import Path
from typing import cast

import polars as pl
from datasets import load_dataset

SPLITS = {
    "USA": "train",
    "Japan": "train",
    "India": "en_IN",
    "Singapore": "train",
    "Brazil": "train",
    "France": "train",
    "Korea": "train",
}


def main():
    country = sys.argv[1]
    split = SPLITS[country]
    out = Path(f"data/raw/{country}/personas.parquet")
    if out.exists():
        print(f"[{country}] cached: {out}", flush=True)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"[{country}] downloading split={split}...", flush=True)
    ds = load_dataset(f"nvidia/Nemotron-Personas-{country}", split=split)
    df = cast(pl.DataFrame, pl.from_arrow(ds.data.table))
    df.write_parquet(out, compression="zstd")
    print(f"[{country}] {len(df):,} rows → {out}", flush=True)


if __name__ == "__main__":
    main()
