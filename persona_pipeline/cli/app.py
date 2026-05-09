import typer

app = typer.Typer(no_args_is_help=True)

# Import side-effect: each module registers its @app.command()s.
from persona_pipeline.cli import stages, archetype, match, simulate  # noqa: F401, E402

if __name__ == "__main__":
    app()
