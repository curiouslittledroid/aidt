"""Contract tests for the target/layout guards (E2.2, EXTRACTION.md §3.1/§3.2/§3.10).

``check_layout`` must refuse the §3.2 clone-of-a-worktree trap (fail closed), warn on
the §3.10 single-checkout case, and pass the supported bare + sibling-worktree layout.
These tests build *real* repositories for all four layouts — a bare repo, the supported
bare + control worktree, a single-checkout plain clone, and a plain clone with a linked
worktree hanging off it — so the membership/more-than-one rule and the fail-closed
unverifiable-list path are exercised against actual git output.

The supported layout comes from the shared ``worktree_repo`` fixture (E2.9). The
*rejected* and single-checkout layouts stay local on purpose: ``_make_trap`` and
``_make_plain_clone`` build layouts the fixture must never produce, and ``_make_bare``
is the bare-with-no-control-worktree case the bare-target refusal needs.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from aidw import git, paths
from aidw.cli import EXIT_REFUSED, app
from aidw.layout import LayoutError, check_layout
from aidw.paths import BareRepositoryError, TargetRepo, WorkspacePaths

if TYPE_CHECKING:  # pragma: no cover - type-only
    # Two conftest files are collected (``tests/`` and the review-followup script tests)
    # and share the top-level module name ``conftest``; a runtime import would break the
    # full-suite run. Annotations are strings, so the name is never resolved here.
    from conftest import WorktreeRepo

runner = CliRunner()

FAKE_ORIGIN = "https://github.com/acme/widget.git"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's real target/state overrides out of these tests."""
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)


# ---------------------------------------------------------------------------
# git fixtures (four real layouts)
# ---------------------------------------------------------------------------


def _git_run(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **GIT_IDENTITY},
    )


def _init_committed_repo(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _git_run(directory, "init", "-q", "-b", "main")
    (directory / "f.txt").write_text("x", encoding="utf-8")
    _git_run(directory, "add", ".")
    _git_run(directory, "commit", "-qm", "init")


def _make_bare(tmp_path: Path, *, remote: str | None = FAKE_ORIGIN) -> Path:
    """A bare clone of a committed seed at ``tmp_path/bare.git``."""
    seed = tmp_path / "seed"
    _init_committed_repo(seed)
    bare = tmp_path / "bare.git"
    _git_run(tmp_path, "clone", "--bare", "-q", str(seed), str(bare))
    if remote is not None:
        _git_run(bare, "remote", "set-url", "origin", remote)
    return bare


def _make_plain_clone(tmp_path: Path, name: str = "plain") -> Path:
    """A single-checkout plain clone (``common_dir == <root>/.git``)."""
    repo = tmp_path / name
    _init_committed_repo(repo)
    _git_run(repo, "remote", "add", "origin", FAKE_ORIGIN)
    return repo


def _make_trap(tmp_path: Path, *, remote: str | None = FAKE_ORIGIN) -> tuple[Path, Path]:
    """The §3.2 rejected layout: a plain clone with a linked worktree hanging off it."""
    seed = tmp_path / "seed"
    _init_committed_repo(seed)
    clone = tmp_path / "main"
    _git_run(tmp_path, "clone", "-q", str(seed), str(clone))
    if remote is None:
        _git_run(clone, "remote", "remove", "origin")
    else:
        _git_run(clone, "remote", "set-url", "origin", remote)
    child = tmp_path / "child"
    _git_run(clone, "worktree", "add", "-q", "-b", "child", str(child), "main")
    return clone, child


def _resolved(start: Path) -> tuple[TargetRepo, WorkspacePaths]:
    target = TargetRepo.resolve(start=start)
    return target, WorkspacePaths.resolve(target)


def _recovery_commands(message: str) -> list[str]:
    """Extract the indented copy-pasteable commands from a failure message."""
    commands: list[str] = []
    for line in message.splitlines():
        stripped = line.strip()
        if line.startswith("  ") and stripped and stripped.split()[0] in {"git", "mv"}:
            commands.append(stripped)
    return commands


# ---------------------------------------------------------------------------
# Trap: plain clone + linked worktree → FAIL from both positions (§3.2)
# ---------------------------------------------------------------------------


def test_trap_fails_from_the_plain_clone(tmp_path: Path) -> None:
    clone, _child = _make_trap(tmp_path)
    target, workspace = _resolved(clone)

    assert workspace.workspace_root == target.root  # the from-clone position

    with pytest.raises(LayoutError) as excinfo:
        check_layout(target, workspace)

    message = str(excinfo.value)
    assert "registered worktree" in message
    assert "git clone --bare" in message
    assert "worktree add ../main main" in message
    assert f"git -C {workspace.workspace_root.parent / 'bare.git'}" in message


def test_trap_fails_from_the_linked_child(tmp_path: Path) -> None:
    """The primary way users inhabit the trap: ``workspace_root`` = the clone ≠ target."""
    clone, child = _make_trap(tmp_path)
    target, workspace = _resolved(child)

    assert target.root == child.resolve()
    assert workspace.workspace_root == clone.resolve()
    assert workspace.workspace_root != target.root

    with pytest.raises(LayoutError) as excinfo:
        check_layout(target, workspace)

    message = str(excinfo.value)
    assert "registered worktree" in message
    assert str(clone.resolve()) in message
    assert "worktree add ../main main" in message


def test_trap_message_targets_the_parent_outside_the_rejected_clone(
    tmp_path: Path,
) -> None:
    clone, child = _make_trap(tmp_path)
    target, workspace = _resolved(child)

    with pytest.raises(LayoutError) as excinfo:
        check_layout(target, workspace)

    parent = clone.resolve().parent
    message = str(excinfo.value)
    assert str(parent / "bare.git") in message
    assert str(parent / "main") in message
    # Never nests the new layout inside the rejected clone.
    assert str(clone.resolve() / "bare.git") not in message


def test_trap_message_uses_the_configured_origin_remote(tmp_path: Path) -> None:
    clone, _child = _make_trap(tmp_path, remote=FAKE_ORIGIN)
    target, workspace = _resolved(clone)

    with pytest.raises(LayoutError) as excinfo:
        check_layout(target, workspace)

    message = str(excinfo.value)
    expected = f"git clone --bare {FAKE_ORIGIN} {workspace.workspace_root.parent / 'bare.git'}"
    assert expected in message


def test_trap_message_without_origin_uses_the_local_clone_source(
    tmp_path: Path,
) -> None:
    """No origin is a supported configuration: the clone source falls back locally."""
    clone, _child = _make_trap(tmp_path, remote=None)
    target, workspace = _resolved(clone)

    assert paths.origin_remote(target.root) is None

    with pytest.raises(LayoutError) as excinfo:
        check_layout(target, workspace)

    message = str(excinfo.value)
    expected = f"git clone --bare {clone.resolve()} {workspace.workspace_root.parent / 'bare.git'}"
    assert expected in message
    for placeholder in ("<origin>", "<remote>", "<bare>", "<parent>"):
        assert placeholder not in message


def test_trap_raises_rather_than_warning_about_state_inside_the_tree(
    tmp_path: Path,
) -> None:
    """Ordering: the trap also puts state inside a tree, but it must fail, not warn."""
    clone, _child = _make_trap(tmp_path)
    target, workspace = _resolved(clone)
    assert workspace.state_root.is_relative_to(target.root)

    with pytest.raises(LayoutError):
        check_layout(target, workspace)


# ---------------------------------------------------------------------------
# The corrective commands execute and re-resolve cleanly (§3.2)
# ---------------------------------------------------------------------------


def test_corrective_commands_rebuild_the_supported_layout(tmp_path: Path) -> None:
    clone, _child = _make_trap(tmp_path, remote=None)
    target, workspace = _resolved(clone)

    with pytest.raises(LayoutError) as excinfo:
        check_layout(target, workspace)

    commands = _recovery_commands(str(excinfo.value))
    assert len(commands) == 3, commands
    parent = clone.resolve().parent
    for command in commands:
        subprocess.run(
            command, shell=True, check=True, cwd=parent, capture_output=True, text=True
        )

    control = parent / "main"
    assert control.is_dir(), "the re-bootstrap must produce the new control worktree"

    new_target, new_workspace = _resolved(control)
    assert check_layout(new_target, new_workspace) == []


def test_corrective_commands_are_copy_pasteable_for_paths_with_spaces(
    tmp_path: Path,
) -> None:
    """The advertised shell commands must work for a valid workspace path."""
    workspace_parent = tmp_path / "workspace with spaces"
    workspace_parent.mkdir()
    clone, _child = _make_trap(workspace_parent, remote=None)
    target, workspace = _resolved(clone)

    with pytest.raises(LayoutError) as excinfo:
        check_layout(target, workspace)

    for command in _recovery_commands(str(excinfo.value)):
        subprocess.run(
            command,
            shell=True,
            check=True,
            cwd=workspace_parent.parent,
            capture_output=True,
            text=True,
        )

    assert (workspace_parent / "main").is_dir()


def test_cli_resolves_cleanly_from_the_new_control_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone, _child = _make_trap(tmp_path, remote=None)
    target, workspace = _resolved(clone)
    with pytest.raises(LayoutError) as excinfo:
        check_layout(target, workspace)

    for command in _recovery_commands(str(excinfo.value)):
        subprocess.run(
            command,
            shell=True,
            check=True,
            cwd=clone.resolve().parent,
            capture_output=True,
            text=True,
        )

    control = clone.resolve().parent / "main"
    monkeypatch.chdir(control)
    result = runner.invoke(app, ["runs", "list"])

    assert result.exit_code == 0, result.output
    assert "Warning" not in result.stderr
    assert "Refusing to run" not in result.stderr


# ---------------------------------------------------------------------------
# Fail closed on an unverifiable worktree list (§3.2, fail-closed)
# ---------------------------------------------------------------------------


def test_unverifiable_worktree_list_fails_closed_from_the_plain_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_plain_clone(tmp_path)
    target, workspace = _resolved(repo)
    monkeypatch.setattr("aidw.layout.git.worktrees", lambda _repo: [])

    with pytest.raises(LayoutError) as excinfo:
        check_layout(target, workspace)

    message = str(excinfo.value)
    assert "unverifiable" in message
    assert "git worktree list" in message
    # No bootstrap applies: there is nothing layout-side to correct.
    assert "git clone --bare" not in message


def test_unverifiable_worktree_list_fails_closed_from_a_linked_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Membership detection consults the list from every position — no path exemption."""
    clone, child = _make_trap(tmp_path)
    target, workspace = _resolved(child)
    assert workspace.workspace_root != target.root
    monkeypatch.setattr("aidw.layout.git.worktrees", lambda _repo: [])

    with pytest.raises(LayoutError) as excinfo:
        check_layout(target, workspace)

    assert "unverifiable" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Warn: single-checkout state-inside-tree; pass: supported layouts (§3.10)
# ---------------------------------------------------------------------------


def test_single_checkout_warns_without_raising(tmp_path: Path) -> None:
    repo = _make_plain_clone(tmp_path)
    target, workspace = _resolved(repo)

    warnings = check_layout(target, workspace)

    assert len(warnings) == 1
    assert "Warning" in warnings[0]
    assert str(workspace.state_root) in warnings[0]
    assert str(target.root) in warnings[0]


def test_supported_bare_and_control_worktree_passes(
    worktree_repo: WorktreeRepo,
) -> None:
    target, workspace = _resolved(worktree_repo.control)

    assert check_layout(target, workspace) == []


def test_supported_layout_with_a_task_worktree_passes_from_each_worktree(
    worktree_repo: WorktreeRepo,
) -> None:
    for start in (worktree_repo.control, worktree_repo.task):
        target, workspace = _resolved(start)
        assert check_layout(target, workspace) == [], start


# ---------------------------------------------------------------------------
# Bare target: the upgraded refusal message (§3.2)
# ---------------------------------------------------------------------------


def test_bare_refusal_message_carries_the_corrective_worktree_add(
    tmp_path: Path,
) -> None:
    bare = _make_bare(tmp_path)

    with pytest.raises(BareRepositoryError) as excinfo:
        TargetRepo.resolve(explicit=bare)

    message = str(excinfo.value)
    assert str(bare.resolve()) in message
    assert "worktree add ../main main" in message
    assert f"git -C {bare.resolve()}" in message


def test_bare_corrective_command_is_copy_pasteable_for_paths_with_spaces(
    tmp_path: Path,
) -> None:
    """The bare-target refusal must also provide a usable shell command."""
    workspace_parent = tmp_path / "bare workspace"
    workspace_parent.mkdir()
    bare = _make_bare(workspace_parent)

    with pytest.raises(BareRepositoryError) as excinfo:
        TargetRepo.resolve(explicit=bare)

    command = next(
        line.strip()
        for line in str(excinfo.value).splitlines()
        if line.strip().startswith("git -C ")
    )
    subprocess.run(
        command,
        shell=True,
        check=True,
        cwd=workspace_parent,
        capture_output=True,
        text=True,
    )
    assert (workspace_parent / "main").is_dir()


# ---------------------------------------------------------------------------
# CLI wiring: refuse the trap, warn the single checkout (E2.2 requirement 2)
# ---------------------------------------------------------------------------


def test_cli_refuses_from_the_plain_clone(tmp_path: Path) -> None:
    clone, _child = _make_trap(tmp_path)

    result = runner.invoke(app, ["--repo", str(clone), "runs", "list"])

    assert result.exit_code == EXIT_REFUSED
    assert "registered worktree" in result.stderr
    assert "git clone --bare" in result.stderr
    assert "Traceback" not in result.output


def test_cli_refuses_from_the_linked_child(tmp_path: Path) -> None:
    _clone, child = _make_trap(tmp_path)

    result = runner.invoke(app, ["--repo", str(child), "runs", "list"])

    assert result.exit_code == EXIT_REFUSED
    assert "registered worktree" in result.stderr
    assert "Traceback" not in result.output


def test_cli_refuses_on_an_unverifiable_worktree_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_plain_clone(tmp_path)
    monkeypatch.setattr("aidw.layout.git.worktrees", lambda _repo: [])

    result = runner.invoke(app, ["--repo", str(repo), "runs", "list"])

    assert result.exit_code == EXIT_REFUSED
    assert "unverifiable" in result.stderr
    assert "Traceback" not in result.output


def test_cli_warns_on_the_single_checkout_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_plain_clone(tmp_path)
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["runs", "list"])

    assert result.exit_code == 0, result.output
    assert "Warning" in result.stderr
    state_root = WorkspacePaths.resolve(TargetRepo.resolve(repo)).state_root
    assert str(state_root) in result.stderr


def test_cli_passes_the_supported_layout_without_warning(
    worktree_repo: WorktreeRepo,
) -> None:
    result = runner.invoke(app, ["--repo", str(worktree_repo.control), "runs", "list"])

    assert result.exit_code == 0, result.output
    assert "Warning" not in result.stderr
    assert "Refusing to run" not in result.stderr


# ---------------------------------------------------------------------------
# Public origin accessor (aidw/paths.py) used by the corrective message
# ---------------------------------------------------------------------------


def test_origin_remote_is_public_and_fails_closed_on_a_missing_origin(
    tmp_path: Path,
) -> None:
    repo = _make_plain_clone(tmp_path)
    assert paths.origin_remote(repo) == FAKE_ORIGIN

    _git_run(repo, "remote", "remove", "origin")

    assert paths.origin_remote(repo) is None


def test_origin_remote_returns_none_outside_a_repository(tmp_path: Path) -> None:
    stray = tmp_path / "stray"
    stray.mkdir()

    assert paths.origin_remote(stray) is None


# ---------------------------------------------------------------------------
# Purity / metamorphic
# ---------------------------------------------------------------------------


def test_check_layout_leaves_the_repository_unchanged(
    worktree_repo: WorktreeRepo,
) -> None:
    target, workspace = _resolved(worktree_repo.control)

    before_worktrees = [(wt.path, wt.branch, wt.detached) for wt in git.worktrees(target.root)]
    before_status = git.status_short(target.root)

    assert check_layout(target, workspace) == []

    after_worktrees = [(wt.path, wt.branch, wt.detached) for wt in git.worktrees(target.root)]
    after_status = git.status_short(target.root)
    assert after_worktrees == before_worktrees
    assert after_status == before_status
    # The single-checkout side of the same check leaves no state directory behind.
    plain = _make_plain_clone(worktree_repo.workspace)
    plain_target, plain_workspace = _resolved(plain)
    assert not plain_workspace.state_root.exists()
    check_layout(plain_target, plain_workspace)
    assert not plain_workspace.state_root.exists()


def test_check_layout_runs_only_read_only_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_plain_clone(tmp_path)
    target, workspace = _resolved(repo)

    recorded: list[list[str]] = []
    real_git_out = git._git_out

    def spy(repo_path: Path, args: list[str]) -> tuple[int, str, str]:
        recorded.append(list(args))
        return real_git_out(repo_path, args)

    monkeypatch.setattr("aidw.git._git_out", spy)

    check_layout(target, workspace)

    # Exactly one read-only consult of the worktree list; never a mutating command.
    assert recorded == [["worktree", "list", "--porcelain"]], recorded


def test_check_layout_verdict_is_invariant_to_cwd(
    worktree_repo: WorktreeRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Metamorphic: the verdict depends on the resolved paths, not the working directory."""
    target, workspace = _resolved(worktree_repo.control)
    expected = check_layout(target, workspace)

    elsewhere = worktree_repo.workspace / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert check_layout(target, workspace) == expected


