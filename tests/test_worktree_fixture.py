"""Contract tests for the shared ``worktree_repo`` fixture (E2.9, EXTRACTION.md §3.2).

The fixture is the product contract every later worktree test builds on, so it is
specified the way ``aidw``'s own primitives are: against *real* git output (no faked
porcelain), with one hand-calculated expectation per behaviour path, plus the fail-closed
collision contract and a purity check.

Hand-calculated wiring (§3.2's "Verified git facts"):

- ``git rev-parse --is-bare-repository`` is ``true`` in ``bare.git`` and ``false`` in both
  worktrees; ``--show-toplevel`` fails in the bare dir ("this operation must be run in a
  work tree"), which is why the bare dir is never a target.
- A worktree's ``.git`` is a **file** holding ``gitdir: <bare.git>/worktrees/<name>``.
- ``common_dir`` is ``bare.git`` from every position, so ``workspace_root`` is the folder
  the three siblings sit in.
- The workspace listing is ``bare.git``, ``main``, ``task`` (plus the clone's ``seed``,
  which is not a worktree) and nothing else — no ``.aidw/state``.

No property/hypothesis test appears here: this repository's AGENTS.md "Tests" section
requires pytest only and ``hypothesis`` is not a dependency (adding one inside this task
would be scope creep). The metamorphic test below covers the same intent — a fixture
operation changes the observable state by exactly its own effect.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aidw import git
from aidw.layout import check_layout
from aidw.paths import TargetRepo, WorkspacePaths

if TYPE_CHECKING:  # pragma: no cover - type-only
    # Not a runtime import: ``testpaths`` also collects ``prompts/scripts/review-followup/
    # tests/conftest.py``, and both conftest files share the top-level module name
    # ``conftest``, so importing it here breaks the full-suite run. Annotations are
    # strings (``from __future__ import annotations``), so the name is never resolved.
    from conftest import WorktreeRepo


def _git(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git with the session identity (``_git_identity``) already exported."""
    return subprocess.run(
        ["git", *args],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _rev_parse(directory: Path, *args: str) -> str:
    """Stripped stdout of a read-only ``git rev-parse`` in ``directory``."""
    return _git(directory, "rev-parse", *args).stdout.strip()


def _listing(repo: Path) -> list[tuple[Path, str | None, bool]]:
    """``git worktrees`` as ``(path, branch, detached)`` sorted by path.

    Sorted by path because that is git's own ``worktree list`` order for linked
    worktrees, so the expectation is hand-calculable (``feat`` < ``main`` < ``task``)
    instead of dependent on checkout order.
    """
    return sorted(
        ((wt.path, wt.branch, wt.detached) for wt in git.worktrees(repo)),
        key=lambda entry: str(entry[0]),
    )


def _commit_in(worktree: Path, name: str) -> None:
    """Commit a new file on the worktree's branch, leaving the worktree clean."""
    (worktree / name).write_text(name, encoding="utf-8")
    _git(worktree, "add", name)
    _git(worktree, "commit", "-qm", f"add {name}")


# ---------------------------------------------------------------------------
# Fixture contract: bare repo, two linked worktrees, all siblings (§3.2)
# ---------------------------------------------------------------------------


def test_bare_is_a_bare_repository_and_never_a_target(worktree_repo: WorktreeRepo) -> None:
    repo = worktree_repo

    assert _rev_parse(repo.bare, "--is-bare-repository") == "true"
    assert _rev_parse(repo.control, "--is-bare-repository") == "false"
    assert _rev_parse(repo.task, "--is-bare-repository") == "false"

    # §3.2: show-toplevel (and therefore paths.repo_root) fails in the bare dir.
    in_bare = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=repo.bare,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert in_bare.returncode != 0
    assert "work tree" in in_bare.stderr


def test_control_and_task_are_linked_worktrees_pointing_into_the_bare_repo(
    worktree_repo: WorktreeRepo,
) -> None:
    repo = worktree_repo

    for tree, name in ((repo.control, "main"), (repo.task, "task")):
        dot_git = tree / ".git"
        assert dot_git.is_file(), f"{tree} must be a linked worktree, not a clone"
        content = dot_git.read_text(encoding="utf-8").strip()
        assert content.startswith("gitdir: ")
        # git writes the absolute path of <bare>/worktrees/<name>.
        assert Path(content.removeprefix("gitdir: ")) == repo.bare / "worktrees" / name

    # Siblings of the bare repo, never nested inside it or inside one another (§3.2).
    assert repo.bare.parent == repo.workspace
    assert repo.control.parent == repo.workspace
    assert repo.task.parent == repo.workspace
    assert repo.bare not in repo.control.parents
    assert repo.control not in repo.task.parents
    assert repo.task not in repo.control.parents


def test_common_dir_and_workspace_root_are_the_bare_repo_from_every_position(
    worktree_repo: WorktreeRepo,
) -> None:
    repo = worktree_repo

    assert git.common_dir(repo.control) == repo.bare
    assert git.common_dir(repo.task) == repo.bare
    assert git.common_dir(repo.bare) == repo.bare
    assert git.workspace_root(repo.task) == repo.workspace
    assert git.is_linked_worktree(repo.control) is True
    assert git.is_linked_worktree(repo.task) is True


def test_task_worktree_holds_the_task_branch_off_main(worktree_repo: WorktreeRepo) -> None:
    repo = worktree_repo

    assert git.current_branch(repo.control) == "main"
    assert git.current_branch(repo.task) == "task"
    # Both branches start at the seed commit, so "off main" is exact, not coincidental.
    assert git.rev_parse(repo.task, "HEAD") == git.rev_parse(repo.control, "main")
    assert git.is_ancestor(repo.control, "main", "task") is True
    assert git.worktree_for_branch(repo.control, "task") == repo.task


def test_fixture_listing_is_exactly_the_control_and_task_worktrees(
    worktree_repo: WorktreeRepo,
) -> None:
    repo = worktree_repo

    assert _listing(repo.bare) == [
        (repo.control, "main", False),
        (repo.task, "task", False),
    ]
    # The bare dir is the common dir, never a worktree entry.
    assert all(entry[0] != repo.bare for entry in _listing(repo.bare))


def test_fixture_workspace_is_clean_and_carries_no_run_state(
    worktree_repo: WorktreeRepo,
) -> None:
    repo = worktree_repo

    assert git.status_short(repo.control) == ""
    assert git.status_short(repo.task) == ""
    assert sorted(path.name for path in repo.workspace.iterdir()) == [
        "bare.git",
        "main",
        "seed",
        "task",
    ]
    # Nothing is written outside tmp_path: no `.aidw/state` under the workspace.
    assert not (repo.workspace / ".aidw").exists()


# ---------------------------------------------------------------------------
# add_task: the §3.2 per-task command, run from the control worktree
# ---------------------------------------------------------------------------


def test_add_task_creates_a_sibling_worktree_on_the_new_branch(
    worktree_repo: WorktreeRepo,
) -> None:
    repo = worktree_repo

    feat = repo.add_task("feat")

    assert feat == (repo.workspace / "feat").resolve()
    assert feat.parent == repo.workspace
    assert git.current_branch(feat) == "feat"
    assert git.worktree_for_branch(repo.control, "feat") == feat
    assert git.is_ancestor(repo.control, "main", "feat") is True
    # §3.2: the branch is born in its own worktree, registered in the bare repo's
    # `worktrees/` admin dir.
    assert (repo.bare / "worktrees" / "feat").is_dir()
    assert _listing(repo.bare) == [
        (feat, "feat", False),
        (repo.control, "main", False),
        (repo.task, "task", False),
    ]


def test_add_task_base_is_discriminated_not_merely_accepted(
    worktree_repo: WorktreeRepo,
) -> None:
    """A child of ``dev`` cannot contain ``main``'s tip, so ``--base`` is observable."""
    repo = worktree_repo
    _git(repo.control, "branch", "dev")
    _commit_in(repo.control, "main-only.txt")

    child = repo.add_task("child", base="dev")

    assert git.is_ancestor(repo.control, "dev", "child") is True
    assert git.is_ancestor(repo.control, "main", "child") is False
    assert git.rev_parse(child, "child") == git.rev_parse(repo.control, "dev")
    assert (repo.workspace / "child").is_dir()


def test_add_task_raises_when_the_pre_created_branch_is_requested(
    worktree_repo: WorktreeRepo,
) -> None:
    """``add_task("task")`` collides with the fixture's own worktree: git refuses."""
    repo = worktree_repo
    before = _listing(repo.bare)

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        repo.add_task("task")

    # git's refusal is surfaced, not swallowed into a `None` return.
    assert "already exists" in excinfo.value.stderr
    assert excinfo.value.returncode != 0
    assert _listing(repo.bare) == before
    assert git.current_branch(repo.task) == "task"
    assert (repo.task / "f.txt").read_text(encoding="utf-8") == "x"


def test_add_task_raises_for_an_existing_branch_that_is_not_checked_out(
    worktree_repo: WorktreeRepo,
) -> None:
    repo = worktree_repo
    _git(repo.control, "branch", "taken")

    with pytest.raises(subprocess.CalledProcessError):
        repo.add_task("taken")

    assert git.worktree_for_branch(repo.control, "taken") is None
    assert not (repo.workspace / "taken").exists()


def test_add_task_raises_when_the_target_path_is_occupied(
    worktree_repo: WorktreeRepo,
) -> None:
    repo = worktree_repo
    occupied = repo.workspace / "occupied"
    occupied.mkdir()
    (occupied / "junk.txt").write_text("x", encoding="utf-8")

    with pytest.raises(subprocess.CalledProcessError):
        repo.add_task("occupied")

    assert not (occupied / ".git").exists()
    assert git.worktree_for_branch(repo.control, "occupied") is None


# ---------------------------------------------------------------------------
# The fixture is the layout the E2.2 guard accepts (§3.2)
# ---------------------------------------------------------------------------


def test_fixture_layout_passes_the_guard_from_each_worktree(
    worktree_repo: WorktreeRepo,
) -> None:
    repo = worktree_repo

    for start in (repo.control, repo.task):
        target = TargetRepo.resolve(start=start)
        workspace = WorkspacePaths.resolve(target)
        assert workspace.workspace_root == repo.workspace
        assert check_layout(target, workspace) == [], start


# ---------------------------------------------------------------------------
# Purity / metamorphic
# ---------------------------------------------------------------------------


def test_using_the_fixture_leaves_it_clean_and_unchanged(
    worktree_repo: WorktreeRepo,
) -> None:
    """Mirrors test_layout.py::test_check_layout_leaves_the_repository_unchanged."""
    repo = worktree_repo
    before_worktrees = _listing(repo.control)
    before_status = (git.status_short(repo.control), git.status_short(repo.task))

    target = TargetRepo.resolve(start=repo.task)
    workspace = WorkspacePaths.resolve(target)
    assert check_layout(target, workspace) == []
    assert git.worktrees(repo.task) == git.worktrees(repo.control)

    assert _listing(repo.control) == before_worktrees
    assert (git.status_short(repo.control), git.status_short(repo.task)) == before_status
    # No `.aidw/state` — not under the workspace, and not under any worktree.
    assert not (repo.workspace / ".aidw").exists()
    assert not (repo.control / ".aidw").exists()
    assert not (repo.task / ".aidw").exists()


def test_add_task_changes_the_listing_by_exactly_one_entry(
    worktree_repo: WorktreeRepo,
) -> None:
    """Metamorphic: the operation's effect is exactly the worktree it returns."""
    repo = worktree_repo
    baseline = {entry[0] for entry in _listing(repo.bare)}

    feat = repo.add_task("feat")

    assert {entry[0] for entry in _listing(repo.bare)} - baseline == {feat}
    assert baseline - {entry[0] for entry in _listing(repo.bare)} == set()

    other = repo.add_task("other")
    assert {entry[0] for entry in _listing(repo.bare)} - baseline == {feat, other}
    assert git.status_short(repo.control) == ""
    assert not (repo.workspace / ".aidw").exists()
