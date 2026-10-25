"""Phase 0 tests for the AIDW CLI surface."""

from __future__ import annotations

from typer.testing import CliRunner

from aidw import __version__
from aidw.cli import app

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"aidt {__version__}"


def test_help_lists_workflow_groups() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "prompt",
        "implement",
        "review",
        "fix",
        "approve-followups",
        "tasks",
        "agents",
    ):
        assert command in result.stdout


def test_run_chain_requires_arguments() -> None:
    result = runner.invoke(app, ["run", "task-to-pr"])
    assert result.exit_code == 2
    assert "requires" in result.stderr


def test_doctor_runs() -> None:
    result = runner.invoke(app, ["doctor"])
    # Unknown environment issues are warnings; doctor fails only on FAIL checks.
    assert result.exit_code in (0, 1)
    assert "AIDT doctor" in result.stdout
