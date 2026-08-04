"""Command line surface for arcet.

Milestone 0 defines the interface and nothing else: `whocan` parses its
arguments and then refuses to pretend it resolved anything. The flags are
declared now so that later milestones fill them in rather than reshape them.
"""

from __future__ import annotations

import logging
from typing import Annotated

import typer

from arcet import __version__
from arcet.render import OutputFormat

HELP = """Effective Azure permissions, with the derivation chain that explains them.

arcet reads. It never writes to Azure, and it keeps no state between runs.
"""

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
        typer.Option(
            "--format",
            "-f",
            help=(
                "table shows the chain behind each permission; list is one "
                "line per action for scanning; json is the machine contract."
            ),
        ),
    ] = OutputFormat.TABLE,
    action: Annotated[
        str | None,
        typer.Option(
            "--action",
            "-a",
            metavar="PATTERN",
            help=(
                "Only show permissions matching this action, wildcards "
                "allowed. The way to ask a narrow question of an identity "
                "that holds a lot, e.g. 'Microsoft.Authorization/*/write'."
            ),
        ),
    ] = None,
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
    # Imported here rather than at module level so that --help and --version
    # stay instant: pulling in the Azure SDK costs the best part of a second,
    # and nothing above this line needs it.
    from azure.core.exceptions import AzureError, ClientAuthenticationError

    from arcet.auth import build_credential
    from arcet.diagnostics import Diagnostics
    from arcet.reader import AzureSource
    from arcet.render import render
    from arcet.resolve import IdentityNotFound, filter_by_action, resolve

    diagnostics = Diagnostics()
    try:
        source = AzureSource(build_credential(), subscription, diagnostics)
        result = resolve(
            identity, subscription, source, expand=expand, diagnostics=diagnostics
        )
    except ClientAuthenticationError as error:
        # Checked before IdentityNotFound. Not being signed in makes every
        # lookup fail, and reporting that as "no such user" would be a
        # confident wrong answer about who exists.
        typer.secho(
            "arcet: could not authenticate to Azure. Sign in with `az login`, "
            "or set the usual AZURE_* environment variables.",
            err=True,
            fg=typer.colors.RED,
        )
        typer.secho(f"       {error.__class__.__name__}", err=True, dim=True)
        raise typer.Exit(code=2) from error
    except IdentityNotFound as error:
        # The identity being absent is a problem with what was asked for, not
        # with arcet, so it reads as a usage error rather than a failure.
        typer.secho(f"arcet: {error}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=3) from error
    except AzureError as error:
        typer.secho(
            f"arcet: could not reach Azure: {error}", err=True, fg=typer.colors.RED
        )
        raise typer.Exit(code=2) from error

    if action is not None:
        result = filter_by_action(result, action)

    # Warnings are printed, not signalled through the exit code. Deny
    # assignments exist in most real subscriptions, so exiting non-zero
    # whenever the result is partial would fire almost every run and teach
    # people to append `|| true` — which silences the real warnings too.
    render(result, output_format, action_filter=action)


def main() -> None:
    """Console script entry point."""
    # The Azure SDKs log their credential-chain failures at warning level, and
    # Python's fallback handler puts that on stderr. It arrives before our own
    # message and reads like a stack trace, which makes a clear, actionable
    # error look like a crash. We say what went wrong ourselves.
    logging.getLogger("azure").setLevel(logging.CRITICAL)
    app()
