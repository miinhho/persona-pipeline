"""CLI: serve-http — run the persona MCP server over streamable-http transport.

Configuration via environment variables (read inside `remote.build_app`):
  PERSONA_STORE_API_KEYS  - comma-separated bearer tokens (required, non-empty)
  PERSONA_STORE_DATA_DIR  - parquet store directory (default: data/store)
  PERSONA_STORE_RATE_LIMIT - requests per minute per token (default: 60)

Use `serve` (separate command) for stdio transport.
"""
from __future__ import annotations

import typer

from persona_pipeline.cli.app import app


@app.command(name="serve-http")
def serve_http(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Run the MCP server over streamable-http (HTTP transport).

    The server expects HTTPS to be terminated upstream by a reverse proxy
    (nginx, Caddy, cloud LB, etc.). The container itself listens on plain HTTP.
    """
    import uvicorn

    from persona_pipeline.mcp_server import mcp
    from persona_pipeline.remote import build_app

    asgi_app = build_app(mcp)
    typer.echo(
        f"starting persona-store MCP server (streamable-http) on {host}:{port}…",
        err=True,
    )
    uvicorn.run(asgi_app, host=host, port=port, log_config=None)
