"""Per-country data paths."""
from pathlib import Path

DATA = Path("data")


def raw_path(country: str) -> Path:
    return DATA / "raw" / country / "personas.parquet"
