"""Per-country data paths."""
from pathlib import Path

DATA = Path("data")


def raw_path(country: str) -> Path:
    return DATA / "raw" / country / "personas.parquet"


def cache_dir(country: str) -> Path:
    return DATA / "cache" / country


def enriched_path(country: str) -> Path:
    return cache_dir(country) / "01_enriched.parquet"


def partitioned_path(country: str) -> Path:
    return cache_dir(country) / "02_partitioned.parquet"


def archetypes_path(country: str) -> Path:
    return DATA / "archetypes" / f"cards_{country}.parquet"


def simulations_path(country: str, run_id: str) -> Path:
    return DATA / "simulations" / f"{country}_{run_id}.parquet"
