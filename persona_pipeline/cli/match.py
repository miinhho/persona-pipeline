"""CLI: natural-language query → archetype matching."""
import polars as pl
import typer

from persona_pipeline._config import DEFAULT_TOP_K
from persona_pipeline.cli._paths import archetypes_path
from persona_pipeline.cli.app import app
from persona_pipeline.mappings import get_mappings
from persona_pipeline.stages.archetype import render_archetype_card
from persona_pipeline.stages.match import match_archetypes


@app.command()
def match(country: str, query: str = typer.Argument(...), top_k: int = DEFAULT_TOP_K):
    mapping = get_mappings(country)
    df = pl.read_parquet(archetypes_path(country))
    results = match_archetypes(query, df, mapping, top_k=top_k)
    if not results:
        typer.echo(f"No match: '{query}'")
        return
    for r in results:
        score = r.get("_score", "?")
        typer.echo(f"\n=== score={score} {r['segment_id']} "
                   f"size={r['size']:,} share={r['share_pct']:.2f}% ===")
        typer.echo(render_archetype_card(r))
