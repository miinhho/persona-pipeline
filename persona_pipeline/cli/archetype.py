"""Archetype CLI."""
import typer

from persona_pipeline import io as io_mod
from persona_pipeline.cli._paths import archetypes_path, partitioned_path, raw_path
from persona_pipeline.cli.app import app
from persona_pipeline.mappings import get_mappings
from persona_pipeline.stages.archetype import synthesize_archetypes


@app.command()
def stage_archetype(country: str):
    mapping = get_mappings(country)
    archetypes = synthesize_archetypes(
        partition_path=partitioned_path(country),
        raw_path=raw_path(country),
        mapping=mapping,
    )
    out = archetypes_path(country)
    io_mod.write_parquet(archetypes, out)
    typer.echo(f"archetype[{country}] → {out} ({len(archetypes)} archetypes)")
