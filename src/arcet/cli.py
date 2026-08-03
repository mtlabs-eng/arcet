"""Command line surface for arcet.

Milestone 0 defines the interface and nothing else: `whocan` parses its
arguments and then refuses to pretend it resolved anything. The flags are
declared now so that later milestones fill them in rather than reshape them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

import typer

from arcet import __version__

HELP = """Effective Azure permissions, with the derivation chain that explains them.

arcet reads. It never writes to Azure, and it keeps no state between runs.
"""


class OutputFormat(StrEnum):
    """How to render a resolution result."""

    TABLE = "table"
    JSON = "json"


app = typer.Typer(
    help=HELP,
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"arcet {__version__}")
        raise typer.Exit


@app.callback()
def cli(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Print the version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Top-level options shared by every command."""


@app.command()
def whocan(
    identity: Annotated[
        str,
        typer.Argument(
            metavar="IDENTITY",
            help="User principal name, or object id of a user or service principal.",
        ),
    ],
    subscription: Annotated[
        str,
        typer.Option(
            "--subscription",
            "-s",
            metavar="SUBSCRIPTION_ID",
            help="Subscription id to resolve permissions within.",
        ),
    ],
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Output format."),
    ] = OutputFormat.TABLE,
    expand: Annotated[
        bool,
        typer.Option(
            "--expand/--no-expand",
            help=(
                "Expand wildcard actions into concrete ones using the provider "
                "operations catalogue. --no-expand keeps the literal pattern."
            ),
        ),
    ] = True,
) -> None:
    """Show what an identity can effectively do, and why."""
    # Milestone 3 replaces this with the real resolver.
    #
    # It exits non-zero on purpose. A stub that exited 0 would report "no
    # permissions found" to anything reading only the exit status, and being
    # wrong quietly about access is the one failure this tool exists to avoid.
    typer.secho(
        "arcet: resolution is not implemented yet (milestone 3); "
        "this build only knows its own version",
        err=True,
        fg=typer.colors.RED,
    )
    raise typer.Exit(code=2)


def main() -> None:
    """Console script entry point."""
    app()
