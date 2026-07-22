"""CodeAtlas CLI entrypoint.

Phase 0 provides only the skeleton. Commands are implemented in later phases
(see CLAUDE.md §9). The command surface is documented in docs/cli_contract.md.
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="codeatlas",
    help="Local-first verified context and change-impact layer.",
    no_args_is_help=True,
)


@app.callback()
def _main() -> None:
    """CodeAtlas — verified context and change-impact for AI-assisted development."""


@app.command()
def version() -> None:
    """Print the CodeAtlas version."""
    from codeatlas import __version__

    typer.echo(f"codeatlas {__version__}")


if __name__ == "__main__":
    app()
