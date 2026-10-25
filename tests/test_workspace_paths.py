"""Contract tests for ``WorkspacePaths`` (E1.3, EXTRACTION.md §3.1/§3.2/§3.10, D18/R1).

``workspace_root`` is ``dirname(<absolute git-common-dir>)`` and ``state_root`` is
``<state base>/<repo_slug>``. These tests build real repositories with git — a bare repo
with two linked worktrees, two bare repos sharing a parent, and a plain clone — so the
worktree vs single-checkout layouts are actually exercised, and they pin every tier of
the state-root formula plus its fail-closed fallback.

The resolver must derive ``workspace_root`` from the passed-in :class:`TargetRepo`
(never re-running git), never from ``git_dir.parent`` (a linked worktree's ``git_dir``
is ``<bare>/worktrees/<name>``) and never from ``root.parent`` (only coincidentally right
in the §3.2 sibling layout).
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

import pytest

from aidw import paths
from aidw.paths import (
    STATE_DIR_ENV_VAR,
    TargetRepo,
    ToolkitPaths,
    WorkspacePaths,
)

# Distinct, deterministic origin remotes so the expected slug is hand-calculable and does
# not depend on the tmp directory's (unpredictable) name.
HTTPS_REMOTE = "https://github.com/acme/widget.git"
SSH_REMOTE = "git@github.com:acme/widget.git"
EXPECTED_SLUG = "acme-widget"


@pytest.fixture(autouse=True)
def _clear_state_dir_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's real ``AIDW_STATE_DIR`` from leaking into these tests."""
    monkeypatch.delenv(STATE_DIR_ENV_VAR, raising=False)


# ---------------------------------------------------------------------------
# git fixtures
# ---------------------------------------------------------------------------


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


def _make_bare(
    parent: Path,
    name: str,
    *,
    remote: str | None = None,
    worktree_name: str | None = None,
) -> tuple[Path, Path]:
    """Create ``parent/<name>.git`` (a bare clone) plus one linked worktree of it."""
    parent.mkdir(parents=True, exist_ok=True)
    seed = parent / f"{name}-seed"
    _init_repo(seed)
    bare = parent / f"{name}.git"
    _git(parent, "clone", "--bare", "-q", str(seed), str(bare))
    if remote is not None:
        _git(bare, "remote", "set-url", "origin", remote)
    worktree = parent / (worktree_name or f"{name}-wt")
    _git(bare, "worktree", "add", "-q", "-b", f"{name}-branch", str(worktree), "main")
    return bare, worktree


def _add_worktree(bare: Path, path: Path, branch: str) -> Path:
    _git(bare, "worktree", "add", "-q", "-b", branch, str(path), "main")
    return path


# ---------------------------------------------------------------------------
# Bare repo + linked worktrees (Requirement 2 / done-when "identical")
# ---------------------------------------------------------------------------


def test_two_worktrees_of_one_bare_share_workspace_and_state_root(tmp_path: Path) -> None:
    bare, first = _make_bare(tmp_path, "bare", remote=HTTPS_REMOTE)
    second = _add_worktree(bare, tmp_path / "second-wt", "second-branch")

    a = WorkspacePaths.resolve(TargetRepo.resolve(start=first))
    b = WorkspacePaths.resolve(TargetRepo.resolve(start=second))

    expected_workspace = tmp_path.resolve()
    expected_state = expected_workspace / ".aidw" / "state" / EXPECTED_SLUG

    assert a.workspace_root == b.workspace_root == expected_workspace
    assert a.state_root == b.state_root == expected_state
    assert a.repo_slug == b.repo_slug == EXPECTED_SLUG


def test_workspace_root_is_common_dir_parent_not_git_dir_or_root_parent(
    tmp_path: Path,
) -> None:
    """A linked worktree nested below the bare repo must still yield the bare's parent."""
    bare, worktree = _make_bare(
        tmp_path,
        "bare",
        remote=HTTPS_REMOTE,
        worktree_name="nested/deeper/wt",
    )
    repo = TargetRepo.resolve(start=worktree)

    assert repo.git_dir.parent != repo.common_dir.parent
    assert repo.root.parent != repo.common_dir.parent

    resolved = WorkspacePaths.resolve(repo)

    assert resolved.workspace_root == repo.common_dir.parent == tmp_path.resolve()
    assert resolved.workspace_root != repo.git_dir.parent
    assert resolved.workspace_root != repo.root.parent


def test_workspace_root_uses_the_passed_common_dir_without_rerunning_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``workspace_root`` comes from ``repo.common_dir``; only the origin lookup runs git."""
    _bare, worktree = _make_bare(tmp_path, "seed-repo", remote=HTTPS_REMOTE)
    real_run = subprocess.run
    calls: list[list[str]] = []

    def spy(cmd: list[str], *args: object, **kwargs: object) -> object:
        calls.append(list(cmd))
        return real_run(cmd, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(paths.subprocess, "run", spy)

    # A fabricated common_dir that no git command could ever return for this worktree.
    fabricated = tmp_path / "workspace" / "bare.git"
    repo = TargetRepo(
        root=worktree.resolve(),
        git_dir=(fabricated / "worktrees" / "wt").resolve(),
        common_dir=fabricated.resolve(),
    )

    resolved = WorkspacePaths.resolve(repo)

    assert resolved.workspace_root == (tmp_path / "workspace").resolve()
    flat = [arg for call in calls for arg in call]
    assert "--git-common-dir" not in flat
    assert "--show-toplevel" not in flat
    assert "--absolute-git-dir" not in flat
    # The only git work this resolver does is reading the origin remote.
    assert flat.count("get-url") == 1


# ---------------------------------------------------------------------------
# Two repos sharing a parent (done-when "differs")
# ---------------------------------------------------------------------------


def test_two_repos_sharing_a_parent_get_different_state_roots(tmp_path: Path) -> None:
    parent = tmp_path / "shared"
    _bare_a, worktree_a = _make_bare(
        parent, "alpha", remote="https://github.com/org-a/alpha.git"
    )
    _bare_b, worktree_b = _make_bare(
        parent, "beta", remote="https://github.com/org-b/beta.git"
    )

    a = WorkspacePaths.resolve(TargetRepo.resolve(start=worktree_a))
    b = WorkspacePaths.resolve(TargetRepo.resolve(start=worktree_b))

    assert a.workspace_root == b.workspace_root == parent.resolve()
    assert a.repo_slug == "org-a-alpha"
    assert b.repo_slug == "org-b-beta"
    assert a.state_root != b.state_root
    assert a.state_root == parent.resolve() / ".aidw" / "state" / "org-a-alpha"
    assert b.state_root == parent.resolve() / ".aidw" / "state" / "org-b-beta"


# ---------------------------------------------------------------------------
# Plain clone / single checkout (trap: state lands inside the working tree)
# ---------------------------------------------------------------------------


def test_single_checkout_places_state_inside_the_working_tree(tmp_path: Path) -> None:
    repo_dir = tmp_path / "plain"
    _init_repo(repo_dir)
    _git(repo_dir, "remote", "add", "origin", HTTPS_REMOTE)

    resolved = WorkspacePaths.resolve(TargetRepo.resolve(start=repo_dir))

    assert resolved.workspace_root == repo_dir.resolve()
    assert resolved.state_root == repo_dir.resolve() / ".aidw" / "state" / EXPECTED_SLUG
    # The §3.10 single-checkout case: the state root is inside the working tree.
    assert repo_dir.resolve() in resolved.state_root.parents


# ---------------------------------------------------------------------------
# Slug derivation (Requirement 3)
# ---------------------------------------------------------------------------


def test_missing_origin_falls_back_to_workspace_root_basename(tmp_path: Path) -> None:
    parent = tmp_path / "workspace-dir"
    bare, worktree = _make_bare(parent, "bare")
    _git(bare, "remote", "remove", "origin")

    resolved = WorkspacePaths.resolve(TargetRepo.resolve(start=worktree))

    assert resolved.workspace_root == parent.resolve()
    assert resolved.repo_slug == parent.resolve().name == "workspace-dir"
    assert resolved.state_root == parent.resolve() / ".aidw" / "state" / "workspace-dir"


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("https://github.com/acme/widget.git", "acme-widget"),
        ("https://github.com/acme/widget", "acme-widget"),
        # SSH scp-like form: the ':' before the path must be handled, not just '/'.
        ("git@github.com:acme/widget.git", "acme-widget"),
        ("ssh://git@github.com/acme/widget.git", "acme-widget"),
        # A host with subgroups keeps the last two segments (prompt-fixed).
        ("https://gitlab.example.com/group/subgroup/widget.git", "subgroup-widget"),
        # Fewer than two path segments -> the workspace-root basename (here "ws").
        ("https://github.com/onlyone.git", "ws"),
        ("widget", "ws"),
    ],
)
def test_slug_parsing_vectors(
    tmp_path: Path, remote: str, expected: str
) -> None:
    workspace = tmp_path / "ws"
    bare, worktree = _make_bare(workspace, "bare")
    _git(bare, "remote", "set-url", "origin", remote)

    resolved = WorkspacePaths.resolve(TargetRepo.resolve(start=worktree))

    assert resolved.workspace_root == workspace.resolve()
    assert resolved.repo_slug == expected


@pytest.mark.parametrize(
    "remote",
    [
        "",
        "widget",
        "https://github.com/onlyone.git",
        "git@github.com:acme/widget.git",
        "https://gitlab.example.com/a/b/c/d.git",
        "C:/dev/repo.git",
    ],
)
def test_slug_is_always_a_non_empty_single_segment(tmp_path: Path, remote: str) -> None:
    """Property: whatever the remote, the slug is a non-empty, separator-free string."""
    bare, worktree = _make_bare(tmp_path / "prop", "bare")
    if remote:
        _git(bare, "remote", "set-url", "origin", remote)
    else:
        _git(bare, "remote", "remove", "origin")

    resolved = WorkspacePaths.resolve(TargetRepo.resolve(start=worktree))

    assert isinstance(resolved.repo_slug, str)
    assert resolved.repo_slug
    assert "/" not in resolved.repo_slug
    assert resolved.repo_slug not in {".", ".."}


# ---------------------------------------------------------------------------
# State-root tiers (Requirements 4-6)
# ---------------------------------------------------------------------------


def test_injected_state_dir_override_wins_and_still_appends_the_slug(
    tmp_path: Path,
) -> None:
    _bare, worktree = _make_bare(tmp_path / "ws", "bare", remote=SSH_REMOTE)
    override = tmp_path / "custom-state"

    resolved = WorkspacePaths.resolve(
        TargetRepo.resolve(start=worktree), state_dir_override=override
    )

    assert resolved.repo_slug == EXPECTED_SLUG
    assert resolved.state_root == override.resolve() / EXPECTED_SLUG


def test_environment_state_dir_wins_over_the_workspace_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bare, worktree = _make_bare(tmp_path / "ws", "bare", remote=HTTPS_REMOTE)
    env_dir = tmp_path / "env-state"
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(env_dir))

    resolved = WorkspacePaths.resolve(TargetRepo.resolve(start=worktree))

    assert resolved.state_root == env_dir.resolve() / EXPECTED_SLUG


def test_explicit_state_dir_override_wins_over_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bare, worktree = _make_bare(tmp_path / "ws", "bare", remote=HTTPS_REMOTE)
    env_dir = tmp_path / "env-state"
    explicit = tmp_path / "explicit-state"
    monkeypatch.setenv(STATE_DIR_ENV_VAR, str(env_dir))

    resolved = WorkspacePaths.resolve(
        TargetRepo.resolve(start=worktree), state_dir_override=explicit
    )

    assert resolved.state_root == explicit.resolve() / EXPECTED_SLUG


def test_failed_origin_lookup_falls_back_to_workspace_basename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace-dir"
    _bare, worktree = _make_bare(workspace, "bare", remote=HTTPS_REMOTE)
    repo = TargetRepo.resolve(start=worktree)
    real_run = paths.subprocess.run

    def fail_origin(cmd: list[str], *args: object, **kwargs: object) -> object:
        if cmd == ["git", "remote", "get-url", "origin"]:
            raise subprocess.CalledProcessError(2, cmd)
        return real_run(cmd, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(paths.subprocess, "run", fail_origin)

    resolved = WorkspacePaths.resolve(repo)

    assert resolved.repo_slug == workspace.name
    assert resolved.state_root == workspace.resolve() / ".aidw" / "state" / workspace.name


def test_unusable_state_parent_falls_closed_to_injected_home(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    _bare, worktree = _make_bare(workspace, "bare", remote=HTTPS_REMOTE)
    # A file at .aidw makes creation of .aidw/state impossible.
    (workspace / ".aidw").write_text("not a directory", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()

    resolved = WorkspacePaths.resolve(TargetRepo.resolve(start=worktree), home=home)

    assert resolved.state_root == home.resolve() / ".aidw" / "state" / EXPECTED_SLUG


def test_unwritable_workspace_root_falls_closed_to_injected_home(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    _bare, worktree = _make_bare(workspace, "bare", remote=HTTPS_REMOTE)
    home = tmp_path / "home"
    home.mkdir()
    repo = TargetRepo.resolve(start=worktree)

    original_mode = workspace.stat().st_mode
    try:
        workspace.chmod(0o500)
        resolved = WorkspacePaths.resolve(repo, home=home)
    finally:
        workspace.chmod(original_mode)

    assert resolved.repo_slug == EXPECTED_SLUG
    assert resolved.state_root == home.resolve() / ".aidw" / "state" / EXPECTED_SLUG
    assert resolved.workspace_root == workspace.resolve()


def test_home_tier_appends_the_slug_too(tmp_path: Path) -> None:
    """The third tier is also ``<base>/<slug>``, not the bare base (R1)."""
    workspace = tmp_path / "ws"
    _bare, worktree = _make_bare(workspace, "bare", remote=SSH_REMOTE)
    home = tmp_path / "home"
    home.mkdir()
    repo = TargetRepo.resolve(start=worktree)

    original_mode = workspace.stat().st_mode
    try:
        workspace.chmod(0o500)
        resolved = WorkspacePaths.resolve(repo, home=home)
    finally:
        workspace.chmod(original_mode)

    assert resolved.state_root == home.resolve() / ".aidw" / "state" / EXPECTED_SLUG


def test_home_defaults_to_path_home_when_not_injected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    _bare, worktree = _make_bare(workspace, "bare", remote=HTTPS_REMOTE)
    (workspace / ".aidw").write_text("not a directory", encoding="utf-8")
    configured_home = tmp_path / "configured-home"
    configured_home.mkdir()
    monkeypatch.setattr(paths.Path, "home", staticmethod(lambda: configured_home))

    resolved = WorkspacePaths.resolve(TargetRepo.resolve(start=worktree))

    assert resolved.state_root == configured_home.resolve() / ".aidw" / "state" / EXPECTED_SLUG


def test_writable_workspace_root_uses_the_workspace_tier(tmp_path: Path) -> None:
    _bare, worktree = _make_bare(tmp_path / "ws", "bare", remote=HTTPS_REMOTE)
    home = tmp_path / "home"
    home.mkdir()

    resolved = WorkspacePaths.resolve(
        TargetRepo.resolve(start=worktree), home=home
    )

    expected = (tmp_path / "ws").resolve() / ".aidw" / "state" / EXPECTED_SLUG
    assert resolved.state_root == expected
    assert home.resolve() not in resolved.state_root.parents


# ---------------------------------------------------------------------------
# Purity / shape (Requirement 1)
# ---------------------------------------------------------------------------


def test_resolve_does_not_mutate_the_passed_target_repo(tmp_path: Path) -> None:
    _bare, worktree = _make_bare(tmp_path / "ws", "bare", remote=HTTPS_REMOTE)
    repo = TargetRepo.resolve(start=worktree)
    before = dataclasses.astuple(repo)

    WorkspacePaths.resolve(repo)

    assert dataclasses.astuple(repo) == before


def test_fields_are_exactly_the_three_contract_fields() -> None:
    names = [field.name for field in dataclasses.fields(WorkspacePaths)]
    assert names == ["workspace_root", "state_root", "repo_slug"]


def test_resolve_is_frozen_and_immutable(tmp_path: Path) -> None:
    _bare, worktree = _make_bare(tmp_path / "ws", "bare", remote=HTTPS_REMOTE)

    resolved = WorkspacePaths.resolve(TargetRepo.resolve(start=worktree))

    with pytest.raises(dataclasses.FrozenInstanceError):
        resolved.repo_slug = "other"  # type: ignore[misc]


def test_every_resolved_path_is_absolute_and_resolved(tmp_path: Path) -> None:
    _bare, worktree = _make_bare(tmp_path / "ws", "bare", remote=HTTPS_REMOTE)

    resolved = WorkspacePaths.resolve(
        TargetRepo.resolve(start=Path(worktree))
    )

    for path in (resolved.workspace_root, resolved.state_root):
        assert path.is_absolute()
        assert path == path.resolve()


def test_workspacepaths_is_a_distinct_type_from_the_other_roots() -> None:
    assert WorkspacePaths is not TargetRepo
    assert WorkspacePaths is not ToolkitPaths
    assert not issubclass(WorkspacePaths, TargetRepo)
    assert not issubclass(WorkspacePaths, ToolkitPaths)

    assert {field.name for field in dataclasses.fields(WorkspacePaths)} == {
        "workspace_root",
        "state_root",
        "repo_slug",
    }
    # Neither existing type's shape is changed by this task.
    assert [field.name for field in dataclasses.fields(TargetRepo)] == [
        "root",
        "git_dir",
        "common_dir",
        "base_branch",
    ]


# ---------------------------------------------------------------------------
# Metamorphic: cwd and depth must not change the resolved roots
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("depth", [0, 1, 3, 5])
def test_resolution_is_invariant_to_cwd_depth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, depth: int
) -> None:
    _bare, worktree = _make_bare(tmp_path / "ws", "bare", remote=HTTPS_REMOTE)
    repo = TargetRepo.resolve(start=worktree)
    expected = WorkspacePaths.resolve(repo)
    nested = tmp_path.joinpath(*["d"] * depth)
    nested.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(nested)

    assert WorkspacePaths.resolve(repo) == expected


def test_unrelated_env_and_home_do_not_leak_into_other_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Metamorphic: only the origin remote and state base affect the result."""
    _bare, worktree = _make_bare(tmp_path / "ws", "bare", remote=HTTPS_REMOTE)
    repo = TargetRepo.resolve(start=worktree)
    expected = WorkspacePaths.resolve(repo)

    monkeypatch.setenv("HOME", str(tmp_path / "unrelated-home"))
    monkeypatch.chdir(tmp_path)

    assert WorkspacePaths.resolve(repo) == expected
