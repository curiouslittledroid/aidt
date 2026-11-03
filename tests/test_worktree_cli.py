"""Contract tests for ``aidw worktree add|list|remove`` (E2.3, EXTRACTION.md §3.3).

The command is a thin, safe wrapper over the E2.1 primitives, so these tests build the
real §3.2 layout — the shared ``worktree_repo`` fixture's bare repo plus its ``main`` and
``task`` sibling worktrees (E2.9) — and assert against actual git output (no faked
porcelain). The two refusals ``remove`` owns are the point of the wrapper: git's own
``worktree remove`` accepts a *clean but unmerged* branch, and ``is_ancestor`` returning
``None`` must fail closed.

The fixture pre-creates the ``task`` worktree, so these tests use ``repo.task`` rather
than re-adding that branch (git refuses an already-checked-out branch); ``repo.add_task``
is only for *additional* branches.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from aidw import git
from aidw.cli import EXIT_OK, EXIT_REFUSED, EXIT_USAGE, app

if TYPE_CHECKING:  # pragma: no cover - type-only
    # Two conftest files are collected (``tests/`` and the review-followup script tests)
    # and share the top-level module name ``conftest``; a runtime import would break the
    # full-suite run. Annotations are strings, so the name is never resolved here.
    from conftest import WorktreeRepo

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's real target/state overrides out of these tests."""
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)


def _git_run(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git; the session fixture in ``tests/conftest.py`` supplies the identity."""
    return subprocess.run(
        ["git", *args],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _invoke(control: Path, *args: str):
    """Invoke ``aidw worktree ...`` against the control worktree."""
    return runner.invoke(app, ["--repo", str(control), "worktree", *args])


def _commit_in(worktree: Path, name: str) -> None:
    """Commit a new file on the worktree's branch, leaving the worktree clean."""
    (worktree / name).write_text(name, encoding="utf-8")
    _git_run(worktree, "add", name)
    _git_run(worktree, "commit", "-qm", f"add {name}")


def _snapshot(root: Path) -> list[str]:
    """Sorted relative file paths under ``root`` — a write detector for purity tests."""
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


def test_add_creates_sibling_worktree_and_list_json_reports_it(
    worktree_repo: WorktreeRepo,
) -> None:
    repo = worktree_repo

    result = _invoke(repo.control, "add", "feat")

    assert result.exit_code == EXIT_OK, result.output
    feat = (repo.workspace / "feat").resolve()
    assert (repo.workspace / "feat").is_dir()
    assert result.stdout.strip() == str(feat)
    # No --base: the default is target.base_branch ("main").
    assert git.is_ancestor(repo.control, "main", "feat") is True

    listed = _invoke(repo.control, "list", "--json")
    assert listed.exit_code == EXIT_OK, listed.output
    payload = json.loads(listed.stdout)
    by_branch = {entry["branch"]: entry for entry in payload}
    assert by_branch["feat"]["path"] == str(feat)
    assert by_branch["feat"]["detached"] is False


def test_add_defaults_to_target_base_branch_and_honours_base(
    worktree_repo: WorktreeRepo,
) -> None:
    repo = worktree_repo
    # ``dev`` is cut from main, then main advances: a child of dev cannot contain main's
    # tip, so ``--base dev`` is distinguishable from the default.
    _git_run(repo.control, "branch", "dev")
    _commit_in(repo.control, "main-only.txt")

    result = _invoke(repo.control, "add", "child", "--base", "dev")

    assert result.exit_code == EXIT_OK, result.output
    assert git.is_ancestor(repo.control, "dev", "child") is True
    assert git.is_ancestor(repo.control, "main", "child") is False
    assert (repo.bare / "worktrees" / "child").is_dir()


def test_add_refuses_an_already_checked_out_branch(worktree_repo: WorktreeRepo) -> None:
    repo = worktree_repo

    result = _invoke(repo.control, "add", "main")

    assert result.exit_code == EXIT_REFUSED
    assert "main" in result.stderr
    assert "already checked out" in result.stderr
    assert str(repo.control) in result.stderr
    assert "Traceback" not in result.output


def test_add_refuses_when_git_declines(worktree_repo: WorktreeRepo) -> None:
    """``add_worktree`` discards stderr, so a git refusal must be a named refusal."""
    repo = worktree_repo
    _git_run(repo.control, "branch", "taken")

    result = _invoke(repo.control, "add", "taken")

    assert result.exit_code == EXIT_REFUSED
    assert "taken" in result.stderr
    assert "git declined" in result.stderr
    assert not (repo.workspace / "taken").exists()


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_json_round_trips_a_detached_worktree(worktree_repo: WorktreeRepo) -> None:
    repo = worktree_repo
    detached = repo.workspace / "detached"
    _git_run(repo.control, "worktree", "add", "-q", "--detach", str(detached), "main")

    result = _invoke(repo.control, "list", "--json")

    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.stdout)
    # Parsing the JSON reproduces git.worktrees(): same order, same resolved paths,
    # same short branch names, and no `bare` entry.
    parsed = [
        git.Worktree(path=Path(entry["path"]), branch=entry["branch"], detached=entry["detached"])
        for entry in payload
    ]
    assert parsed == git.worktrees(repo.control)
    by_branch = {entry.branch: entry for entry in parsed}
    assert set(by_branch) == {"main", "task", None}
    assert by_branch["main"].detached is False
    assert by_branch["task"].path == repo.task
    assert by_branch[None].detached is True
    assert by_branch[None].path == detached.resolve()
    assert all(entry.path != repo.bare for entry in parsed)


def test_list_human_mode_shows_branch_and_path(worktree_repo: WorktreeRepo) -> None:
    repo = worktree_repo
    detached = repo.workspace / "detached"
    _git_run(repo.control, "worktree", "add", "-q", "--detach", str(detached), "main")

    result = _invoke(repo.control, "list")

    assert result.exit_code == EXIT_OK, result.output
    lines = result.stdout.splitlines()
    assert f"main  {repo.control}" in lines
    assert f"<detached>  {detached.resolve()}" in lines


def test_list_writes_nothing(worktree_repo: WorktreeRepo) -> None:
    repo = worktree_repo
    before = _snapshot(repo.workspace)

    result = _invoke(repo.control, "list", "--json")

    assert result.exit_code == EXIT_OK, result.output
    assert _snapshot(repo.workspace) == before


# ---------------------------------------------------------------------------
# remove — the two refusals the wrapper owns
# ---------------------------------------------------------------------------


def test_remove_refuses_a_dirty_tree_and_force_removes_it(
    worktree_repo: WorktreeRepo,
) -> None:
    repo = worktree_repo
    (repo.task / "wip.txt").write_text("uncommitted", encoding="utf-8")

    refused = _invoke(repo.control, "remove", "task")

    assert refused.exit_code == EXIT_REFUSED
    assert "uncommitted" in refused.stderr
    assert "task" in refused.stderr
    assert "Traceback" not in refused.output
    # The worktree and the uncommitted file survive the refusal.
    assert repo.task.is_dir()
    assert (repo.task / "wip.txt").read_text(encoding="utf-8") == "uncommitted"
    assert git.worktree_for_branch(repo.control, "task") == repo.task

    forced = _invoke(repo.control, "remove", "task", "--force")

    assert forced.exit_code == EXIT_OK, forced.output
    assert not repo.task.exists()
    assert git.worktree_for_branch(repo.control, "task") is None


def test_remove_refuses_a_clean_but_unmerged_branch(worktree_repo: WorktreeRepo) -> None:
    """git's own `worktree remove` accepts this case; the wrapper must not."""
    repo = worktree_repo
    _commit_in(repo.task, "task-only.txt")
    assert git.is_clean(repo.task)

    refused = _invoke(repo.control, "remove", "task")

    assert refused.exit_code == EXIT_REFUSED
    assert "not merged" in refused.stderr
    assert "main" in refused.stderr
    assert repo.task.is_dir()
    assert (repo.task / "task-only.txt").is_file()

    forced = _invoke(repo.control, "remove", "task", "--force")

    assert forced.exit_code == EXIT_OK, forced.output
    assert not repo.task.exists()


def test_remove_reports_the_dirty_cause_first_when_both_hold(
    worktree_repo: WorktreeRepo,
) -> None:
    repo = worktree_repo
    _commit_in(repo.task, "task-only.txt")
    (repo.task / "wip.txt").write_text("uncommitted", encoding="utf-8")

    refused = _invoke(repo.control, "remove", "task")

    assert refused.exit_code == EXIT_REFUSED
    assert "uncommitted" in refused.stderr
    assert "not merged" not in refused.stderr


def test_remove_fails_closed_when_the_merge_state_is_unverifiable(
    worktree_repo: WorktreeRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``is_ancestor`` returning ``None`` means "git cannot answer" — never "merged"."""
    repo = worktree_repo
    monkeypatch.setattr("aidw.cli.git.is_ancestor", lambda *_args, **_kwargs: None)

    refused = _invoke(repo.control, "remove", "task")

    assert refused.exit_code == EXIT_REFUSED
    assert "could not answer" in refused.stderr
    assert repo.task.is_dir()
    assert git.worktree_for_branch(repo.control, "task") == repo.task


def test_remove_succeeds_for_a_clean_merged_worktree(worktree_repo: WorktreeRepo) -> None:
    repo = worktree_repo
    assert git.is_clean(repo.task)

    result = _invoke(repo.control, "remove", "task")

    assert result.exit_code == EXIT_OK, result.output
    assert not repo.task.exists()
    assert git.worktree_for_branch(repo.control, "task") is None
    # The control worktree is untouched and still the only entry.
    assert git.worktrees(repo.control) == [
        git.Worktree(path=repo.control, branch="main", detached=False)
    ]
    assert (repo.control / "f.txt").read_text(encoding="utf-8") == "x"


def test_remove_refuses_the_generic_git_failure(
    worktree_repo: WorktreeRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = worktree_repo
    monkeypatch.setattr("aidw.cli.git.remove_worktree", lambda *_args, **_kwargs: False)

    refused = _invoke(repo.control, "remove", "task")

    assert refused.exit_code == EXIT_REFUSED
    assert "git declined" in refused.stderr
    assert "--force" in refused.stderr
    assert repo.task.is_dir()


def test_remove_reports_the_generic_failure_without_resuggesting_force(
    worktree_repo: WorktreeRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``--force`` already given, the refusal must not tell the user to re-run it."""
    repo = worktree_repo
    monkeypatch.setattr("aidw.cli.git.remove_worktree", lambda *_args, **_kwargs: False)

    forced = _invoke(repo.control, "remove", "task", "--force")

    assert forced.exit_code == EXIT_REFUSED
    assert "git declined" in forced.stderr
    assert "re-run with --force" not in forced.stderr
    assert "even with --force" in forced.stderr
    # The refusal leaves the worktree in place for manual inspection.
    assert repo.task.is_dir()
    assert git.worktree_for_branch(repo.control, "task") == repo.task


def test_remove_unknown_branch_is_a_usage_error(worktree_repo: WorktreeRepo) -> None:
    result = _invoke(worktree_repo.control, "remove", "nope")

    assert result.exit_code == EXIT_USAGE
    assert "nope" in result.stderr


# ---------------------------------------------------------------------------
# Arity / dispatch
# ---------------------------------------------------------------------------


def test_unknown_action_is_a_usage_error(worktree_repo: WorktreeRepo) -> None:
    result = _invoke(worktree_repo.control, "frobnicate")

    assert result.exit_code == EXIT_USAGE
    assert "unknown action" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("action", ["add", "remove"])
def test_missing_branch_is_a_usage_error(
    worktree_repo: WorktreeRepo, action: str
) -> None:
    result = _invoke(worktree_repo.control, action)

    assert result.exit_code == EXIT_USAGE
    assert f"aidw worktree {action} <branch>" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ("list", "extra"),
        ("list", "--force"),
        ("list", "--base", "dev"),
        ("add", "feat", "--json"),
        ("remove", "main", "--base", "dev"),
        ("remove", "main", "--json"),
    ],
)
def test_action_arity_rejects_arguments_belonging_to_another_action(
    worktree_repo: WorktreeRepo, args: tuple[str, ...]
) -> None:
    """§3.3's per-action surface must not silently ignore extra args or flags."""
    result = _invoke(worktree_repo.control, *args)

    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""


# ---------------------------------------------------------------------------
# Purity / blast radius
# ---------------------------------------------------------------------------


def test_add_and_remove_only_touch_their_own_worktree(worktree_repo: WorktreeRepo) -> None:
    repo = worktree_repo
    other = repo.add_task("other")
    other_file = (other / "f.txt").read_text(encoding="utf-8")
    control_before = _snapshot(repo.control)

    assert _invoke(repo.control, "add", "feat").exit_code == EXIT_OK
    assert _invoke(repo.control, "remove", "feat").exit_code == EXIT_OK

    # The other worktrees are untouched: same files, clean, still registered.
    assert _snapshot(repo.control) == control_before
    assert git.is_clean(repo.control)
    assert (other / "f.txt").read_text(encoding="utf-8") == other_file
    assert git.is_clean(other)
    assert git.worktree_for_branch(repo.control, "other") == other
