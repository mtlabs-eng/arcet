"""Tests for the command line surface.

These never touch Azure. Milestone 0 has no resolver to touch it with, and
later milestones keep the property by feeding recorded fixtures instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from arcet import __version__
from arcet import cli as cli_module
from arcet.cli import OutputFormat, app

runner = CliRunner()


def test_version_exits_clean() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("arcet ")


def test_version_reports_the_package_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert __version__ in result.stdout


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_exits_clean(flag: str) -> None:
    result = runner.invoke(app, [flag])
    assert result.exit_code == 0
    assert "whocan" in result.stdout


def test_help_states_the_read_only_invariant() -> None:
    """The promise not to write is part of the interface, not just the README.

    It is the reason someone runs this against production with real
    credentials, so it belongs where they see it.
    """
    result = runner.invoke(app, ["--help"])
    assert "never writes" in result.stdout.lower()


def test_whocan_declares_the_v01_flag_surface() -> None:
    result = runner.invoke(app, ["whocan", "--help"])
    assert result.exit_code == 0
    for flag in ("--subscription", "--format", "--expand", "--no-expand"):
        assert flag in result.stdout


def test_whocan_requires_a_subscription() -> None:
    result = runner.invoke(app, ["whocan", "user@example.com"])
    assert result.exit_code != 0


def test_whocan_requires_an_identity() -> None:
    result = runner.invoke(app, ["whocan", "--subscription", "sub-id"])
    assert result.exit_code != 0


def test_whocan_rejects_an_unknown_format() -> None:
    result = runner.invoke(
        app,
        ["whocan", "user@example.com", "--subscription", "sub-id", "--format", "yaml"],
    )
    assert result.exit_code != 0


@pytest.mark.parametrize("output_format", list(OutputFormat))
def test_every_format_is_accepted(output_format: OutputFormat) -> None:
    """Argument validation only. A valid invocation would reach Azure.

    Nothing in this suite is allowed to do that, so the resolver is covered in
    test_resolve.py against a fixture-backed source instead.
    """
    result = runner.invoke(
        app,
        [
            "whocan",
            "user@example.com",
            "--subscription",
            "sub-id",
            "--format",
            output_format.value,
            "--help",
        ],
    )
    assert result.exit_code == 0


def test_the_azure_sdk_is_not_imported_for_help() -> None:
    """--help and --version stay instant.

    Importing the SDK costs the best part of a second, and a CLI that pauses
    before printing its own help feels broken.
    """
    source = Path(cli_module.__file__).read_text(encoding="utf-8")
    header = source[: source.index("def whocan")]
    assert "azure" not in header
