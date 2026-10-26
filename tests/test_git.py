"""Tests for the git helpers: narrow commit paths and worktree primitives.

EXTRACTION.md §3.2 fixes the bare-plus-sibling-worktree layout and the porcelain
format; these tests build real repositories (a bare clone with a branch worktree, a
detached-HEAD worktree, and a plain clone) so the parser and the fail-closed paths are
exercised against actual git output, not a hand-written fixture.
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

import pytest

from aidw import git


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)


def _git_run(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
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


def _make_bare_branch_and_detached(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Bare repo plus exactly one ``task`` branch worktree and one detached worktree."""
    bare = _make_bare(tmp_path)
    task = tmp_path / "task"
    _git_run(bare, "worktree", "add", "-q", "-b", "task", str(task), "main")
    detached = tmp_path / "detached"
    _git_run(bare, "worktree", "add", "-q", "--detach", str(detached), "main")
    return bare, task, detached


def _make_bare_with_control(tmp_path: Path) -> tuple[Path, Path]:
    """Bare repo plus the ``main`` control worktree (the §3.2 bootstrap layout)."""
    bare = _make_bare(tmp_path)
    control = tmp_path / "main"
    _git_run(bare, "worktree", "add", "-q", str(control), "main")
    return bare, control


def test_commit_paths_commits_only_given_path(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    (tmp_path / "a.txt").write_text("a2", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b2", encoding="utf-8")

    assert git.commit_paths(tmp_path, ["a.txt"], "update a")
    assert git.status_short(tmp_path, paths=["a.txt"]) == ""
    assert git.status_short(tmp_path, paths=["b.txt"]) != ""


def test_commit_paths_returns_false_when_clean(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    assert git.commit_paths(tmp_path, ["a.txt"], "noop") is False


def test_status_short_scoped(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    assert git.status_short(tmp_path, paths=["a.txt"]) != ""
    assert git.status_short(tmp_path, paths=["missing.txt"]) == ""


# ---------------------------------------------------------------------------
# Worktree shape (EXTRACTION.md §3.2)
# ---------------------------------------------------------------------------


def test_worktree_fields_are_the_three_contract_fields() -> None:
    names = [field.name for field in dataclasses.fields(git.Worktree)]
    assert names == ["path", "branch", "detached"]


def test_worktree_is_frozen() -> None:
    entry = git.Worktree(path=Path("/tmp/wt"), branch=None, detached=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.branch = "task"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Porcelain parsing (bare excluded, branch short name, detached HEAD)
# ---------------------------------------------------------------------------


def test_worktrees_parses_branch_and_detached_and_excludes_bare(tmp_path: Path) -> None:
    bare, task, detached = _make_bare_branch_and_detached(tmp_path)

    entries = git.worktrees(task)

    assert len(entries) == 2
    by_path = {entry.path: entry for entry in entries}
    assert set(by_path) == {task.resolve(), detached.resolve()}
    assert bare.resolve() not in by_path

    task_entry = by_path[task.resolve()]
    assert task_entry.branch == "task"  # refs/heads/ stripped
    assert task_entry.detached is False

    detached_entry = by_path[detached.resolve()]
    assert detached_entry.branch is None
    assert detached_entry.detached is True


def test_worktrees_ignores_optional_porcelain_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Variable-length locked/prunable blocks keep their branch and detached facts."""
    bare = tmp_path / "bare.git"
    task = tmp_path / "task"
    detached = tmp_path / "detached"
    porcelain = "\n".join(
        [
            f"worktree {bare}",
            "bare",
            "",
            f"worktree {task}",
            "HEAD abc123",
            "branch refs/heads/task",
            "locked",
            "prunable stale reason",
            "",
            f"worktree {detached}",
            "HEAD def456",
            "detached",
            "locked",
            "",
        ]
    )

    monkeypatch.setattr(
        git, "_git_out", lambda _repo, _args: (0, porcelain, "")
    )

    entries = git.worktrees(tmp_path)

    assert entries == [
        git.Worktree(path=task.resolve(), branch="task", detached=False),
        git.Worktree(path=detached.resolve(), branch=None, detached=True),
    ]


# ---------------------------------------------------------------------------
# common_dir / workspace_root (Requirement 2, §3.1/§3.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("depth", [0, 1, 2, 5])
def test_common_dir_and_workspace_root_are_invariant_to_cwd_depth(
    tmp_path: Path, depth: int
) -> None:
    """Metamorphic: nesting deeper under the worktree must not change either root."""
    bare, control = _make_bare_with_control(tmp_path)
    origin = control.joinpath(*["d"] * depth)
    origin.mkdir(parents=True, exist_ok=True)

    assert git.common_dir(origin) == bare.resolve()
    assert git.workspace_root(origin) == tmp_path.resolve()


def test_workspace_root_is_common_dir_parent_not_git_dir(tmp_path: Path) -> None:
    """A linked worktree's git_dir is ``<bare>/worktrees/<name>``; the root is not its parent."""
    bare, control = _make_bare_with_control(tmp_path)
    git_dir = (control / ".git").read_text(encoding="utf-8").strip().removeprefix("gitdir: ")

    workspace = git.workspace_root(control)

    assert workspace == tmp_path.resolve()
    assert workspace != Path(git_dir).parent.resolve()
    assert git.common_dir(control) == bare.resolve()


# ---------------------------------------------------------------------------
# add_worktree / worktree_for_branch (Requirements 4 and 5)
# ---------------------------------------------------------------------------


def test_add_worktree_creates_a_sibling_and_round_trips(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)

    created = git.add_worktree(control, "feat")

    assert created == (tmp_path / "feat").resolve()
    assert created.parent == tmp_path.resolve()
    # Sibling of the control worktree, never nested inside it.
    assert control.resolve() not in created.parents
    assert created.is_dir()
    assert created in {entry.path for entry in git.worktrees(control)}

    assert git.worktree_for_branch(control, "feat") == created
    assert git.worktree_for_branch(control, "nope") is None


def test_add_worktree_honours_base_branch(tmp_path: Path) -> None:
    bare, control = _make_bare_with_control(tmp_path)
    _git_run(bare, "branch", "develop", "main")

    created = git.add_worktree(control, "feat", base_branch="develop")

    assert created is not None
    assert git.rev_parse(created, "HEAD") == git.rev_parse(control, "develop")


def test_add_worktree_fails_closed_when_branch_already_checked_out(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)

    assert git.add_worktree(control, "main") is None


# ---------------------------------------------------------------------------
# remove_worktree (Requirement 6)
# ---------------------------------------------------------------------------


def test_remove_worktree_clean_removes_and_disappears(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    feat = git.add_worktree(control, "feat")
    assert feat is not None

    assert git.remove_worktree(control, feat) is True

    assert not feat.exists()
    assert git.worktree_for_branch(control, "feat") is None
    assert feat not in {entry.path for entry in git.worktrees(control)}


def test_remove_worktree_refuses_dirty_and_force_removes(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    feat = git.add_worktree(control, "feat")
    assert feat is not None
    (feat / "f.txt").write_text("dirty", encoding="utf-8")

    # Git's own refusal: no force, no deletion.
    assert git.remove_worktree(control, feat) is False
    assert feat.is_dir()

    assert git.remove_worktree(control, feat, force=True) is True
    assert not feat.exists()


# ---------------------------------------------------------------------------
# is_linked_worktree (Requirement 7)
# ---------------------------------------------------------------------------


def test_is_linked_worktree_true_in_a_linked_worktree(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    feat = git.add_worktree(control, "feat")

    assert git.is_linked_worktree(control) is True
    assert feat is not None
    assert git.is_linked_worktree(feat) is True


def test_is_linked_worktree_false_in_a_plain_clone(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    _init_committed_repo(plain)

    assert git.is_linked_worktree(plain) is False
    assert git.common_dir(plain) == (plain / ".git").resolve()
    assert git.workspace_root(plain) == plain.resolve()


def test_is_linked_worktree_false_in_a_non_repo_dir(tmp_path: Path) -> None:
    stray = tmp_path / "stray"
    stray.mkdir()

    assert git.is_linked_worktree(stray) is False


# ---------------------------------------------------------------------------
# Fail-closed and purity (module style; Requirement 1 and done-when)
# ---------------------------------------------------------------------------


def test_worktree_primitives_fail_closed_outside_a_repo(tmp_path: Path) -> None:
    stray = tmp_path / "not-a-repo"
    stray.mkdir()

    assert git.common_dir(stray) is None
    assert git.workspace_root(stray) is None
    assert git.worktrees(stray) == []
    assert git.worktree_for_branch(stray, "task") is None
    assert git.add_worktree(stray, "feat") is None
    assert git.remove_worktree(stray, stray / "nope") is False
    assert git.is_linked_worktree(stray) is False


def test_common_dir_fails_closed_for_a_missing_path(tmp_path: Path) -> None:
    assert git.common_dir(tmp_path / "does-not-exist") is None


def test_read_only_primitives_do_not_mutate_the_repo(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    before_worktrees = git.worktrees(control)
    before_status = git.status_short(control)
    before_branch = git.current_branch(control)

    git.common_dir(control)
    git.workspace_root(control)
    git.worktrees(control)
    git.worktree_for_branch(control, "main")
    git.is_linked_worktree(control)

    assert git.worktrees(control) == before_worktrees
    assert git.status_short(control) == before_status
    assert git.current_branch(control) == before_branch


def test_read_only_primitives_do_not_mutate_their_path_input(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    repo = Path(str(control))
    before = Path(str(repo))

    git.common_dir(repo)
    git.workspace_root(repo)
    git.worktrees(repo)
    git.worktree_for_branch(repo, "main")
    git.is_linked_worktree(repo)

    assert repo == before


def test_worktrees_metamorphic_add_then_remove(tmp_path: Path) -> None:
    """Adding then removing a worktree changes the listing by exactly that entry."""
    _bare, control = _make_bare_with_control(tmp_path)
    baseline = {entry.path for entry in git.worktrees(control)}

    created = git.add_worktree(control, "feat")
    assert created is not None
    assert {entry.path for entry in git.worktrees(control)} - baseline == {created}

    assert git.remove_worktree(control, created) is True
    assert {entry.path for entry in git.worktrees(control)} == baseline
