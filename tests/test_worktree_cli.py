"""Contract tests for ``aidw worktree add|list|remove`` (E2.3, EXTRACTION.md §3.3).

The command is a thin, safe wrapper over the E2.1 primitives, so these tests build the
real §3.2 layout — a bare repo plus the ``main`` control worktree, then task and
detached worktrees — and assert against actual git output (no faked porcelain). The
two refusals ``remove`` owns are the point of the wrapper: git's own ``worktree
remove`` accepts a *clean but unmerged* branch, and ``is_ancestor`` returning ``None``
must fail closed.

Fixtures are deliberately local (E2.9 owns the shared worktree fixture); they mirror
``tests/test_git.py``'s bare+control helper and ``tests/test_layout.py``'s
``CliRunner`` setup.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aidw import git
from aidw.cli import EXIT_OK, EXIT_REFUSED, EXIT_USAGE, app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's real target/state overrides out of these tests."""
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)


# ---------------------------------------------------------------------------
# Real git fixtures (§3.2 supported layout)
# ---------------------------------------------------------------------------


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


def _init_committed_repo(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _git_run(directory, "init", "-q", "-b", "main")
    (directory / "f.txt").write_text("x", encoding="utf-8")
    _git_run(directory, "add", ".")
    _git_run(directory, "commit", "-qm", "init")


def _make_bare(tmp_path: Path) -> Path:
    """Create ``tmp_path/bare.git`` from a committed seed and return it."""
    seed = tmp_path / "seed"
    _init_committed_repo(seed)
    bare = tmp_path / "bare.git"
    _git_run(tmp_path, "clone", "--bare", "-q", str(seed), str(bare))
    return bare


def _make_bare_with_control(tmp_path: Path) -> tuple[Path, Path]:
    """Bare repo plus the ``main`` control worktree (the §3.2 bootstrap layout)."""
    bare = _make_bare(tmp_path)
    control = tmp_path / "main"
    _git_run(bare, "worktree", "add", "-q", str(control), "main")
    return bare, control


def _invoke(control: Path, *args: str):
    """Invoke ``aidw worktree ...`` against the control worktree."""
    return runner.invoke(app, ["--repo", str(control), "worktree", *args])


def _add_task(control: Path, branch: str = "task", *, base: str = "main") -> Path:
    """Create a task worktree through git itself, for tests not about ``add``."""
    path = control.parent / branch
    _git_run(control, "worktree", "add", "-q", "-b", branch, str(path), base)
    return path


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


def test_add_creates_sibling_worktree_and_list_json_reports_it(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)

    result = _invoke(control, "add", "feat")

    assert result.exit_code == EXIT_OK, result.output
    feat = (tmp_path / "feat").resolve()
    assert (tmp_path / "feat").is_dir()
    assert result.stdout.strip() == str(feat)
    # No --base: the default is target.base_branch ("main").
    assert git.is_ancestor(control, "main", "feat") is True

    listed = _invoke(control, "list", "--json")
    assert listed.exit_code == EXIT_OK, listed.output
    payload = json.loads(listed.stdout)
    by_branch = {entry["branch"]: entry for entry in payload}
    assert by_branch["feat"]["path"] == str(feat)
    assert by_branch["feat"]["detached"] is False


def test_add_defaults_to_target_base_branch_and_honours_base(tmp_path: Path) -> None:
    bare, control = _make_bare_with_control(tmp_path)
    # ``dev`` is cut from main, then main advances: a child of dev cannot contain main's
    # tip, so ``--base dev`` is distinguishable from the default.
    _git_run(control, "branch", "dev")
    _commit_in(control, "main-only.txt")

    result = _invoke(control, "add", "child", "--base", "dev")

    assert result.exit_code == EXIT_OK, result.output
    assert git.is_ancestor(control, "dev", "child") is True
    assert git.is_ancestor(control, "main", "child") is False
    assert (bare / "worktrees" / "child").is_dir()


def test_add_refuses_an_already_checked_out_branch(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)

    result = _invoke(control, "add", "main")

    assert result.exit_code == EXIT_REFUSED
    assert "main" in result.stderr
    assert "already checked out" in result.stderr
    assert str((tmp_path / "main").resolve()) in result.stderr
    assert "Traceback" not in result.output


def test_add_refuses_when_git_declines(tmp_path: Path) -> None:
    """``add_worktree`` discards stderr, so a git refusal must be a named refusal."""
    _bare, control = _make_bare_with_control(tmp_path)
    _git_run(control, "branch", "taken")

    result = _invoke(control, "add", "taken")

    assert result.exit_code == EXIT_REFUSED
    assert "taken" in result.stderr
    assert "git declined" in result.stderr
    assert not (tmp_path / "taken").exists()


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_json_round_trips_a_detached_worktree(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    _add_task(control, "task")
    detached = tmp_path / "detached"
    _git_run(control, "worktree", "add", "-q", "--detach", str(detached), "main")

    result = _invoke(control, "list", "--json")

    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.stdout)
    # Parsing the JSON reproduces git.worktrees(): same order, same resolved paths,
    # same short branch names, and no `bare` entry.
    parsed = [
        git.Worktree(path=Path(entry["path"]), branch=entry["branch"], detached=entry["detached"])
        for entry in payload
    ]
    assert parsed == git.worktrees(control)
    by_branch = {entry.branch: entry for entry in parsed}
    assert set(by_branch) == {"main", "task", None}
    assert by_branch["main"].detached is False
    assert by_branch["task"].path == (tmp_path / "task").resolve()
    assert by_branch[None].detached is True
    assert by_branch[None].path == detached.resolve()
    assert all(entry.path != (tmp_path / "bare.git").resolve() for entry in parsed)


def test_list_human_mode_shows_branch_and_path(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    detached = tmp_path / "detached"
    _git_run(control, "worktree", "add", "-q", "--detach", str(detached), "main")

    result = _invoke(control, "list")

    assert result.exit_code == EXIT_OK, result.output
    lines = result.stdout.splitlines()
    assert f"main  {(tmp_path / 'main').resolve()}" in lines
    assert f"<detached>  {detached.resolve()}" in lines


def test_list_writes_nothing(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    _add_task(control, "task")
    before = _snapshot(tmp_path)

    result = _invoke(control, "list", "--json")

    assert result.exit_code == EXIT_OK, result.output
    assert _snapshot(tmp_path) == before


# ---------------------------------------------------------------------------
# remove — the two refusals the wrapper owns
# ---------------------------------------------------------------------------


def test_remove_refuses_a_dirty_tree_and_force_removes_it(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    task = _add_task(control, "task")
    (task / "wip.txt").write_text("uncommitted", encoding="utf-8")

    refused = _invoke(control, "remove", "task")

    assert refused.exit_code == EXIT_REFUSED
    assert "uncommitted" in refused.stderr
    assert "task" in refused.stderr
    assert "Traceback" not in refused.output
    # The worktree and the uncommitted file survive the refusal.
    assert task.is_dir()
    assert (task / "wip.txt").read_text(encoding="utf-8") == "uncommitted"
    assert git.worktree_for_branch(control, "task") == task.resolve()

    forced = _invoke(control, "remove", "task", "--force")

    assert forced.exit_code == EXIT_OK, forced.output
    assert not task.exists()
    assert git.worktree_for_branch(control, "task") is None


def test_remove_refuses_a_clean_but_unmerged_branch(tmp_path: Path) -> None:
    """git's own `worktree remove` accepts this case; the wrapper must not."""
    _bare, control = _make_bare_with_control(tmp_path)
    task = _add_task(control, "task")
    _commit_in(task, "task-only.txt")
    assert git.is_clean(task)

    refused = _invoke(control, "remove", "task")

    assert refused.exit_code == EXIT_REFUSED
    assert "not merged" in refused.stderr
    assert "main" in refused.stderr
    assert task.is_dir()
    assert (task / "task-only.txt").is_file()

    forced = _invoke(control, "remove", "task", "--force")

    assert forced.exit_code == EXIT_OK, forced.output
    assert not task.exists()


def test_remove_reports_the_dirty_cause_first_when_both_hold(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    task = _add_task(control, "task")
    _commit_in(task, "task-only.txt")
    (task / "wip.txt").write_text("uncommitted", encoding="utf-8")

    refused = _invoke(control, "remove", "task")

    assert refused.exit_code == EXIT_REFUSED
    assert "uncommitted" in refused.stderr
    assert "not merged" not in refused.stderr


def test_remove_fails_closed_when_the_merge_state_is_unverifiable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``is_ancestor`` returning ``None`` means "git cannot answer" — never "merged"."""
    _bare, control = _make_bare_with_control(tmp_path)
    task = _add_task(control, "task")
    monkeypatch.setattr("aidw.cli.git.is_ancestor", lambda *_args, **_kwargs: None)

    refused = _invoke(control, "remove", "task")

    assert refused.exit_code == EXIT_REFUSED
    assert "could not answer" in refused.stderr
    assert task.is_dir()
    assert git.worktree_for_branch(control, "task") == task.resolve()


def test_remove_succeeds_for_a_clean_merged_worktree(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    task = _add_task(control, "task")
    assert git.is_clean(task)

    result = _invoke(control, "remove", "task")

    assert result.exit_code == EXIT_OK, result.output
    assert not task.exists()
    assert git.worktree_for_branch(control, "task") is None
    # The control worktree is untouched and still the only entry.
    assert git.worktrees(control) == [
        git.Worktree(path=control.resolve(), branch="main", detached=False)
    ]
    assert (control / "f.txt").read_text(encoding="utf-8") == "x"


def test_remove_refuses_the_generic_git_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    _add_task(control, "task")
    monkeypatch.setattr("aidw.cli.git.remove_worktree", lambda *_args, **_kwargs: False)

    refused = _invoke(control, "remove", "task")

    assert refused.exit_code == EXIT_REFUSED
    assert "git declined" in refused.stderr
    assert "--force" in refused.stderr
    assert (tmp_path / "task").is_dir()


def test_remove_reports_the_generic_failure_without_resuggesting_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``--force`` already given, the refusal must not tell the user to re-run it."""
    _bare, control = _make_bare_with_control(tmp_path)
    _add_task(control, "task")
    monkeypatch.setattr("aidw.cli.git.remove_worktree", lambda *_args, **_kwargs: False)

    forced = _invoke(control, "remove", "task", "--force")

    assert forced.exit_code == EXIT_REFUSED
    assert "git declined" in forced.stderr
    assert "re-run with --force" not in forced.stderr
    assert "even with --force" in forced.stderr
    # The refusal leaves the worktree in place for manual inspection.
    assert (tmp_path / "task").is_dir()
    assert git.worktree_for_branch(control, "task") == (tmp_path / "task").resolve()


def test_remove_unknown_branch_is_a_usage_error(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)

    result = _invoke(control, "remove", "nope")

    assert result.exit_code == EXIT_USAGE
    assert "nope" in result.stderr


# ---------------------------------------------------------------------------
# Arity / dispatch
# ---------------------------------------------------------------------------


def test_unknown_action_is_a_usage_error(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)

    result = _invoke(control, "frobnicate")

    assert result.exit_code == EXIT_USAGE
    assert "unknown action" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("action", ["add", "remove"])
def test_missing_branch_is_a_usage_error(tmp_path: Path, action: str) -> None:
    _bare, control = _make_bare_with_control(tmp_path)

    result = _invoke(control, action)

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
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    """§3.3's per-action surface must not silently ignore extra args or flags."""
    _bare, control = _make_bare_with_control(tmp_path)

    result = _invoke(control, *args)

    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""


# ---------------------------------------------------------------------------
# Purity / blast radius
# ---------------------------------------------------------------------------


def test_add_and_remove_only_touch_their_own_worktree(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    _add_task(control, "other")
    other_file = (tmp_path / "other" / "f.txt").read_text(encoding="utf-8")
    control_before = _snapshot(control)

    assert _invoke(control, "add", "feat").exit_code == EXIT_OK
    assert _invoke(control, "remove", "feat").exit_code == EXIT_OK

    # The other worktrees are untouched: same files, clean, still registered.
    assert _snapshot(control) == control_before
    assert git.is_clean(control)
    assert (tmp_path / "other" / "f.txt").read_text(encoding="utf-8") == other_file
    assert git.is_clean(tmp_path / "other")
    assert git.worktree_for_branch(control, "other") == (tmp_path / "other").resolve()
