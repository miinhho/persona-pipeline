"""CLI: classify-occupation — run Anthropic Batches API classifier and write lookup parquet."""
import polars as pl
import typer

from persona_mcp_store import io as io_mod
from persona_mcp_store.cli._paths import occupation_lookup_path, raw_path
from persona_mcp_store.cli.app import app
from persona_mcp_store.mappings import get_mappings
from persona_mcp_store.stages.classify_occupation import (
    DEFAULT_MODEL as CLS_MODEL,
    classify_occupations,
)


@app.command(name="classify-occupation")
def classify_occupation(country: str, model: str = CLS_MODEL) -> None:
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
