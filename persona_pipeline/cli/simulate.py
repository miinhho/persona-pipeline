"""CLI: persona simulation — fan a task across many archetypes for one country."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import polars as pl
import typer

from persona_pipeline import io as io_mod
from persona_pipeline.cli._paths import archetypes_path, simulations_path
from persona_pipeline.cli.app import app
from persona_pipeline.stages.simulate import (
    DEFAULT_CONCURRENCY, DEFAULT_MAX_TOKENS, DEFAULT_MODEL, run_simulation,
)


@app.command()
def simulate(
    country: str,
    task: str = typer.Option(..., "--task", help="Task / question to ask each persona"),
    top_n: int = typer.Option(10, "--top-n", help="Top-N largest segments (ignored if --segment-id given)"),
    segment_id: list[str] = typer.Option(
        None, "--segment-id", help="Specific segment_id (repeatable). Overrides --top-n."
    ),
    model: str = typer.Option(DEFAULT_MODEL, "--model"),
    max_tokens: int = typer.Option(DEFAULT_MAX_TOKENS, "--max-tokens"),
    concurrency: int = typer.Option(DEFAULT_CONCURRENCY, "--concurrency"),
    out: Path = typer.Option(None, "--out", help="Output parquet path. Default: data/simulations/{country}_{ts}.parquet"),
):
    cards_all = pl.read_parquet(archetypes_path(country))
    if segment_id:
        cards = cards_all.filter(pl.col("segment_id").is_in(segment_id))
        missing = set(segment_id) - set(cards["segment_id"].to_list())
        if missing:
            raise typer.BadParameter(f"segment_id not found in {country}: {sorted(missing)}")
    else:
        cards = cards_all.sort("size", descending=True).head(top_n)

    if len(cards) == 0:
        raise typer.BadParameter(f"No archetypes selected from {country}")

    typer.echo(
        f"simulate[{country}]: {len(cards)} segments × 1 task with {model} "
        f"(concurrency={concurrency}, max_tokens={max_tokens})"
    )

    results = run_simulation(
        cards, country, task,
        model=model, max_tokens=max_tokens, concurrency=concurrency,
    )

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(out) if out else simulations_path(country, run_id)
    io_mod.write_parquet(results, out_path)

    n_err = int(results.filter(pl.col("error").is_not_null()).height)
    total_in = int(results["input_tokens"].sum())
    total_out = int(results["output_tokens"].sum())
    total_cache_read = int(results["cache_read_tokens"].sum())
    typer.echo(
        f"-> {out_path} ({len(results)} responses, {n_err} errors) | "
        f"tokens: in={total_in:,}, out={total_out:,}, cache_read={total_cache_read:,}"
    )
