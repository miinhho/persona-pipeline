"""CLI: build {country} → write data/store/{country}.parquet end-to-end."""
from __future__ import annotations

import polars as pl
import typer

from persona_pipeline import io as io_mod, store
from persona_pipeline.cli._paths import occupation_lookup_path, raw_path
from persona_pipeline.store import store_path
from persona_pipeline.cli.app import app
from persona_pipeline.mappings import get_mappings
from persona_pipeline.stages.enrich import enrich


@app.command()
def build(country: str) -> None:
    """Enrich raw personas with axes and write the country store + catalog sidecar.

    Prerequisites:
      - `download {country}` has run (raw parquet exists)
      - `classify-occupation {country}` has run if the country uses LLM-classified
        occupation groups (Korea/Japan/USA/India)
    """
    mapping = get_mappings(country)
    raw = pl.scan_parquet(raw_path(country))

    lookup = None
    if mapping.occupation_group_definitions is not None:
        lp = occupation_lookup_path(country)
        if not lp.exists():
            raise typer.BadParameter(
                f"occupation lookup missing: {lp}. "
                f"Run `classify-occupation {country}` first."
            )
        lookup = pl.scan_parquet(lp)

    out = store_path(country)
    io_mod.sink_parquet(enrich(raw, mapping, occupation_lookup=lookup), out)
    n_rows = pl.scan_parquet(out).select(pl.len()).collect().item()
    typer.echo(f"build[{country}] → {out} ({n_rows:,} rows)")

    catalog_out = store.write_catalog(country)
    typer.echo(f"catalog[{country}] → {catalog_out}")
