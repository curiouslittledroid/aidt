"""Phase 0 tests for the AIDW CLI surface, plus E1.4 run-location tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from aidw import __version__
from aidw import state as state_mod
from aidw.cli import app
from aidw.paths import TargetRepo, WorkspacePaths, toolkit_root

runner = CliRunner()


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def _runs_root(repo: Path) -> Path:
    """The per-repo state-root runs directory E1.4 writes to (never the toolkit)."""
    return WorkspacePaths.resolve(TargetRepo.resolve(repo)).state_root / "runs"


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


def test_runs_list_and_show_resolve_the_state_root(tmp_path: Path) -> None:
    """E1.4: ``runs`` reads the state root, not ``<toolkit>/runs``."""
    _init_repo(tmp_path)
    runs_root = _runs_root(tmp_path)
    created = state_mod.create_run(
        runs_root, tmp_path, "implement", label="03-E4.1", branch="03-E4.1"
    )

    listed = runner.invoke(app, ["--repo", str(tmp_path), "runs", "list"])
    assert listed.exit_code == 0
    assert created.run_id in listed.stdout
    assert not (toolkit_root() / "runs" / created.run_id).exists()

    shown = runner.invoke(app, ["--repo", str(tmp_path), "runs", "show", created.run_id])
    assert shown.exit_code == 0
    assert f"run:      {created.run_id}" in shown.stdout
    assert "workflow: implement" in shown.stdout


def test_exec_dry_run_writes_one_run_under_the_state_root(tmp_path: Path) -> None:
    """E1.4 ``_run_dir`` move: state.json, run.log and rendered prompt are siblings.

    The literal ``rg`` gate cannot catch a split here (a stray ``toolkit_root() /
    "runs"`` matches neither banned name), so this test proves the run is whole.
    """
    _init_repo(tmp_path)
    result = runner.invoke(
        app,
        [
            "--repo",
            str(tmp_path),
            "exec",
            "--agent",
            "code-reviewer",
            "--prompt",
            "code-review",
            "--workflow",
            "stage",
            "--label",
            "cli-test",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "aidt/runs" not in result.stdout
    assert "rendered: runs/" in result.stdout

    run_dirs = list(_runs_root(tmp_path).iterdir())
    assert len(run_dirs) == 1
    directory = run_dirs[0]
    assert (directory / "state.json").is_file()
    assert (directory / "run.log").is_file()
    assert (directory / "prompts" / "code-review.rendered.md").is_file()
    assert not (toolkit_root() / "runs" / directory.name).exists()
