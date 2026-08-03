"""Tests for the command line surface.

These never touch Azure. Milestone 0 has no resolver to touch it with, and
later milestones keep the property by feeding recorded fixtures instead.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from arcet import __version__
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


def test_whocan_is_not_implemented_yet() -> None:
    """Guards the milestone 0 stub.

    This fails once the resolver lands, which is the reminder to delete the
    stub and every assumption built on it.
    """
    result = runner.invoke(
        app, ["whocan", "user@example.com", "--subscription", "sub-id"]
    )
    assert result.exit_code == 2
    assert "not implemented" in result.output


@pytest.mark.parametrize("output_format", list(OutputFormat))
@pytest.mark.parametrize("expand_flag", ["--expand", "--no-expand"])
def test_whocan_never_exits_clean_while_stubbed(
    output_format: OutputFormat, expand_flag: str
) -> None:
    """No valid invocation may reach exit 0 before the resolver exists.

    A caller reading only the exit status would take that as "resolved, and
    this identity has nothing".
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
            expand_flag,
        ],
    )
    assert result.exit_code != 0
