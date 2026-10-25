"""Contract tests for ``TargetRepo`` resolution (E1.1, EXTRACTION.md §3.1/§3.2).

The resolver is the sole construction entry point for the target-repository root.
These tests build real repositories with git (a bare clone plus a linked worktree, and a
plain clone) so the worktree ``git_dir``/``common_dir`` distinction is actually
exercised, and they pin every fail-closed path: an invalid ``explicit`` override must
raise rather than fall back to cwd.
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

import pytest

from aidw.paths import BareRepositoryError, RepoNotFoundError, TargetRepo, repo_root


def _git(directory: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _init_repo(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _git(directory, "init", "-q", "-b", "main")
    _git(directory, "config", "user.email", "t@example.com")
    _git(directory, "config", "user.name", "Test")
    (directory / "f.txt").write_text("x", encoding="utf-8")
    _git(directory, "add", ".")
    _git(directory, "commit", "-qm", "init")


def _make_bare_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Bootstrap the §3.2 layout: a bare clone plus one linked worktree."""
    seed = tmp_path / "seed"
    _init_repo(seed)

    bare = tmp_path / "bare.git"
    _git(tmp_path, "clone", "--bare", "-q", str(seed), str(bare))

    worktree = tmp_path / "worktree"
    _git(bare, "worktree", "add", "-q", "-b", "task", str(worktree), "main")
    return bare, worktree


# ---------------------------------------------------------------------------
# Default resolution: cwd walk-up (Requirement 2)
# ---------------------------------------------------------------------------


def test_linked_worktree_exposes_distinct_git_and_common_dirs(tmp_path: Path) -> None:
    bare, worktree = _make_bare_with_worktree(tmp_path)

    target = TargetRepo.resolve(start=worktree)

    assert target.root == worktree.resolve()
    # In a linked worktree git_dir points into the bare repo's worktrees/ dir.
    assert target.git_dir == (bare / "worktrees" / "worktree").resolve()
    # common_dir is the bare repo itself, not the worktree.
    assert target.common_dir == bare.resolve()
    assert target.git_dir != target.common_dir
    assert target.base_branch == "main"


def test_subdirectory_walks_up_to_the_worktree_root(tmp_path: Path) -> None:
    _bare, worktree = _make_bare_with_worktree(tmp_path)
    deep = worktree / "sub" / "deeper"
    deep.mkdir(parents=True)

    assert TargetRepo.resolve(start=deep).root == worktree.resolve()


def test_default_start_is_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _bare, worktree = _make_bare_with_worktree(tmp_path)
    monkeypatch.chdir(worktree)

    assert TargetRepo.resolve().root == worktree.resolve()


@pytest.mark.parametrize("depth", [1, 2, 3, 5])
def test_resolution_is_invariant_to_subdirectory_depth(
    tmp_path: Path, depth: int
) -> None:
    """Metamorphic: nesting deeper under a tree must not change the resolved root."""
    _bare, worktree = _make_bare_with_worktree(tmp_path)
    nested = worktree.joinpath(*["d"] * depth)
    nested.mkdir(parents=True)

    assert TargetRepo.resolve(start=nested).root == worktree.resolve()


# ---------------------------------------------------------------------------
# Explicit override (Requirement 3)
# ---------------------------------------------------------------------------


def test_explicit_override_wins_over_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cwd_repo = tmp_path / "cwd-repo"
    other_repo = tmp_path / "other-repo"
    _init_repo(cwd_repo)
    _init_repo(other_repo)
    monkeypatch.chdir(cwd_repo)

    target = TargetRepo.resolve(start=cwd_repo, explicit=other_repo)

    assert target.root == other_repo.resolve()
    assert target.root != cwd_repo.resolve()


def test_explicit_override_subdirectory_resolves_to_tree_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd_repo = tmp_path / "cwd-repo"
    _init_repo(cwd_repo)
    monkeypatch.chdir(cwd_repo)
    _bare, worktree = _make_bare_with_worktree(tmp_path)
    sub = worktree / "pkg"
    sub.mkdir()

    assert TargetRepo.resolve(explicit=sub).root == worktree.resolve()


def test_explicit_override_on_worktree_uses_worktree_git_dirs(tmp_path: Path) -> None:
    bare, worktree = _make_bare_with_worktree(tmp_path)

    target = TargetRepo.resolve(explicit=worktree)

    assert target.root == worktree.resolve()
    assert target.git_dir == (bare / "worktrees" / "worktree").resolve()
    assert target.common_dir == bare.resolve()


@pytest.mark.parametrize("bad_kind", ["non_repo_dir", "file", "nonexistent"])
def test_invalid_override_raises_and_never_falls_back_to_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_kind: str
) -> None:
    """A typo'd/non-repo ``--repo`` must not silently operate on the cwd repo."""
    cwd_repo = tmp_path / "cwd-repo"
    _init_repo(cwd_repo)
    monkeypatch.chdir(cwd_repo)

    if bad_kind == "non_repo_dir":
        bad = tmp_path / "stray-dir"
        bad.mkdir()
    elif bad_kind == "file":
        bad = cwd_repo / "not-a-dir.txt"
        bad.write_text("x", encoding="utf-8")
    else:
        bad = cwd_repo / "does-not-exist"

    with pytest.raises(RepoNotFoundError) as excinfo:
        TargetRepo.resolve(explicit=bad)

    assert str(bad.resolve()) in str(excinfo.value)


def test_explicit_bare_override_raises_bare_refusal(tmp_path: Path) -> None:
    bare, _worktree = _make_bare_with_worktree(tmp_path)

    with pytest.raises(BareRepositoryError) as excinfo:
        TargetRepo.resolve(explicit=bare)

    assert str(bare.resolve()) in str(excinfo.value)


# ---------------------------------------------------------------------------
# Fail-closed errors (Requirements 2 and 5)
# ---------------------------------------------------------------------------


def test_non_repo_path_raises_with_start_in_message(tmp_path: Path) -> None:
    stray = tmp_path / "not-a-repo"
    stray.mkdir()

    with pytest.raises(RepoNotFoundError) as excinfo:
        TargetRepo.resolve(start=stray)

    assert str(stray.resolve()) in str(excinfo.value)


def test_bare_dir_raises_a_distinct_subclass(tmp_path: Path) -> None:
    bare, _worktree = _make_bare_with_worktree(tmp_path)

    assert issubclass(BareRepositoryError, RepoNotFoundError)
    assert BareRepositoryError is not RepoNotFoundError

    with pytest.raises(RepoNotFoundError) as excinfo:
        TargetRepo.resolve(start=bare)

    assert isinstance(excinfo.value, BareRepositoryError)
    message = str(excinfo.value)
    assert "bare repository" in message
    assert "worktree" in message
    # The bare refusal must not be swallowed into the generic message.
    assert "Not inside a git repository" not in message


# ---------------------------------------------------------------------------
# Plain clone (Requirement 4 / done-when)
# ---------------------------------------------------------------------------


def test_plain_clone_matches_repo_root_and_uses_dot_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "plain"
    _init_repo(repo)
    monkeypatch.chdir(repo)

    target = TargetRepo.resolve()

    assert target.root == repo_root()
    assert target.git_dir == target.common_dir == (repo / ".git").resolve()
    assert target.base_branch == "main"


# ---------------------------------------------------------------------------
# Shape / purity
# ---------------------------------------------------------------------------


def test_fields_are_exactly_the_four_contract_fields() -> None:
    names = [field.name for field in dataclasses.fields(TargetRepo)]
    assert names == ["root", "git_dir", "common_dir", "base_branch"]


def test_every_resolved_path_is_absolute_and_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bare, worktree = _make_bare_with_worktree(tmp_path)
    monkeypatch.chdir(worktree)

    target = TargetRepo.resolve(start=Path("."), explicit=Path("."))

    for path in (target.root, target.git_dir, target.common_dir):
        assert path.is_absolute()
        assert path == path.resolve()


def test_resolve_does_not_mutate_its_inputs(tmp_path: Path) -> None:
    _bare, worktree = _make_bare_with_worktree(tmp_path)
    start = Path(str(worktree))
    explicit = Path(str(worktree))
    before_start, before_explicit = Path(str(start)), Path(str(explicit))

    TargetRepo.resolve(start=start)
    TargetRepo.resolve(explicit=explicit)

    assert start == before_start
    assert explicit == before_explicit


def test_resolve_is_frozen_and_immutable(tmp_path: Path) -> None:
    _bare, worktree = _make_bare_with_worktree(tmp_path)

    target = TargetRepo.resolve(start=worktree)

    with pytest.raises(dataclasses.FrozenInstanceError):
        target.base_branch = "develop"  # type: ignore[misc]
