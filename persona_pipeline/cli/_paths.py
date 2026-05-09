"""Per-country data paths."""
from pathlib import Path

DATA = Path("data")


def raw_path(country: str) -> Path:
    return DATA / "raw" / country / "personas.parquet"


def occupation_lookup_path(country: str) -> Path:
    """Versioned data asset: per-country (occupation, group) parquet committed to git."""
    return DATA / "occupation_lookup" / f"{country}.parquet"


def store_path(country: str) -> Path:
    return DATA / "store" / f"{country}.parquet"
