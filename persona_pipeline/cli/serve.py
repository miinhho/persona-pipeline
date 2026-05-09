"""CLI: serve — run the persona MCP server over stdio."""
from __future__ import annotations

import typer

from persona_pipeline.cli.app import app


@app.command()
def serve() -> None:
    """Run the MCP server (stdio transport).

    Connect from an MCP-aware client (Claude Desktop, Claude Code) by registering
    a server pointing to `python -m persona_pipeline.mcp_server`.
    """
    from persona_pipeline.mcp_server import mcp
    typer.echo("starting persona-store MCP server (stdio)...", err=True)
    mcp.run()
