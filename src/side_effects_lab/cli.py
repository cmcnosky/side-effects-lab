"""Implementation-status command-line interface."""

import typer

IMPLEMENTATION_STATUS = (
    "Side Effects Lab kernel foundation is installed. "
    "Executable lab runtime, services, scenarios, and demo are not implemented."
)

app = typer.Typer(
    add_completion=False,
    help="Inspect the current Side Effects Lab implementation status.",
    no_args_is_help=False,
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Report the honest implementation status until runtime commands exist."""
    if ctx.invoked_subcommand is None:
        typer.echo(IMPLEMENTATION_STATUS)
