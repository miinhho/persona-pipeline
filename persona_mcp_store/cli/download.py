"""CLI: download — fetch raw Nemotron parquet from HuggingFace."""
import typer

from persona_mcp_store import io as io_mod
from persona_mcp_store.cli._paths import raw_path
from persona_mcp_store.cli.app import app


@app.command()
def download(country: str) -> None:
    out = raw_path(country)
    io_mod.download_raw(country, out)
    typer.echo(f"saved → {out}")
