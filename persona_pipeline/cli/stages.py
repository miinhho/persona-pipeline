"""Stage CLI."""
import polars as pl
import typer

from persona_pipeline import io as io_mod
from persona_pipeline._config import DEFAULT_MAX_SEGMENTS, DEFAULT_MIN_SIZE
from persona_pipeline.cli._paths import (
    enriched_path, occupation_lookup_path, partitioned_path, raw_path,
)
from persona_pipeline.cli.app import app
from persona_pipeline.mappings import SEGMENT_ID, get_mappings
from persona_pipeline.stages.classify_occupation import (
    DEFAULT_MODEL as CLS_MODEL,
    classify_occupations,
)
from persona_pipeline.stages.enrich import enrich
from persona_pipeline.stages.partition import partition
from persona_pipeline.validate import validate_enriched, validate_partitioned


@app.command()
def download(country: str):
    out = raw_path(country)
    io_mod.download_raw(country, out)
    typer.echo(f"saved → {out}")


@app.command()
def stage_classify_occupation(country: str, model: str = CLS_MODEL):
    """Classify the raw `occupation` free-text column into the country's group labels
    via Claude (Batches API). Output is a versioned data asset committed alongside the code."""
    mapping = get_mappings(country)
    if mapping.occupation_group_definitions is None:
        typer.echo(f"{country} uses native occupation category — no classification needed.")
        return
    raw = pl.scan_parquet(raw_path(country))
    df = classify_occupations(raw, mapping, model=model, progress=typer.echo)
    out = occupation_lookup_path(country)
    io_mod.write_parquet(df, out)
    n_err = int(df.filter(pl.col("error").is_not_null()).height)
    typer.echo(f"classify[{country}] → {out} ({len(df):,} unique values, {n_err} errors)")


@app.command()
def stage_enrich(country: str):
    mapping = get_mappings(country)
    out = enriched_path(country)

    lookup = None
    if mapping.occupation_group_definitions is not None:
        lp = occupation_lookup_path(country)
        if not lp.exists():
            raise typer.BadParameter(
                f"occupation lookup missing: {lp}. "
                f"Run `stage-classify-occupation {country}` first."
            )
        lookup = pl.scan_parquet(lp)

    io_mod.sink_parquet(enrich(pl.scan_parquet(raw_path(country)), mapping, occupation_lookup=lookup), out)
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
    validate_partitioned(final, min_size=min_size, max_segments=max_segments, n_axes=len(mapping.axes))
    n_segs = final.select(pl.col(SEGMENT_ID).n_unique()).collect().item()
    typer.echo(f"partition[{country}] → {out} ({n_segs} segments)")
