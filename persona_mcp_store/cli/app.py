import typer

app = typer.Typer(help="Persona pipeline: build the per-country store and serve it over MCP.")

# Register commands (each module attaches via @app.command())
from persona_mcp_store.cli import download  # noqa: F401, E402
from persona_mcp_store.cli import build  # noqa: F401, E402
from persona_mcp_store.cli import serve  # noqa: F401, E402
from persona_mcp_store.cli import serve_http  # noqa: F401, E402
