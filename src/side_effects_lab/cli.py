"""Planning-status command-line interface."""

import typer

BOOTSTRAP_STATUS = (
    "Side Effects Lab bootstrap is installed. "
    "Runtime, scenarios, and demo are not implemented."
)

app = typer.Typer(
    add_completion=False,
    help="Inspect the current Side Effects Lab implementation status.",
    no_args_is_help=False,
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Report the honest bootstrap status until runtime commands exist."""
    if ctx.invoked_subcommand is None:
        typer.echo(BOOTSTRAP_STATUS)
