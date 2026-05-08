"""Stage CLI."""
import polars as pl
import typer

from persona_pipeline import io as io_mod
from persona_pipeline._config import DEFAULT_MAX_SEGMENTS, DEFAULT_MIN_SIZE
from persona_pipeline.cli._paths import (
    enriched_path, partitioned_path, raw_path,
)
from persona_pipeline.cli.app import app
from persona_pipeline.mappings import SEGMENT_ID, get_mappings
from persona_pipeline.stages.enrich import enrich
from persona_pipeline.stages.partition import partition
from persona_pipeline.validate import validate_enriched, validate_partitioned


@app.command()
def download(country: str):
    out = raw_path(country)
    io_mod.download_raw(country, out)
    typer.echo(f"saved → {out}")


@app.command()
def stage_enrich(country: str):
    mapping = get_mappings(country)
    out = enriched_path(country)
    io_mod.sink_parquet(enrich(pl.scan_parquet(raw_path(country)), mapping), out)
    validate_enriched(pl.scan_parquet(out), mapping.axes)
    typer.echo(f"enrich[{country}] → {out}")


@app.command()
def stage_partition(
    country: str,
    min_size: int = DEFAULT_MIN_SIZE,
    max_segments: int = DEFAULT_MAX_SEGMENTS,
):
    mapping = get_mappings(country)
    out = partitioned_path(country)
    partition(enriched_path(country), out, mapping, min_size=min_size)
    final = pl.scan_parquet(out)
    validate_partitioned(final, min_size=min_size, max_segments=max_segments)
    n_segs = final.select(pl.col(SEGMENT_ID).n_unique()).collect().item()
    typer.echo(f"partition[{country}] → {out} ({n_segs} segments)")
