"""Contract tests for ``aidw doctor``.

Two halves: the environment checks (``pi``/``gh``/``git`` versions, dependencies) with
faked binaries, and the E2.8 target-layout checks (``git version``, ``repo root``/
``target repo``, ``workspace root``, ``state root``, ``control worktree``) against *real*
temporary repositories — a bare repo, the supported bare + sibling-worktree layout, a
single-checkout plain clone and the §3.2 clone-of-a-worktree trap.

The repo fixtures are deliberately local: E2.9's ``worktree_repo`` fixture covers only
the bare + ``main`` + ``task`` layout, while these tests add the bare-only, trap and
single-checkout layouts, so each is exercised against actual ``git worktree list``
output rather than a stubbed guard.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aidw import doctor, git
from aidw.cli import app
from aidw.doctor import (
    FAIL,
    OK,
    WARN,
    _check_dependencies,
    _check_gh_version,
    _check_git_version,
    _check_pi,
    _check_python,
    _missing_gh_capabilities,
    _parse_gh_version,
    _parse_git_version,
    _parse_pi_version,
    collect_checks,
    run_doctor,
)
from aidw.paths import TargetRepo, WorkspacePaths

runner = CliRunner()

FAKE_ORIGIN = "https://github.com/acme/widget.git"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}

#: The E2.8 checks, in report order.
NEW_CHECKS = ("git version", "repo root", "workspace root", "state root", "control worktree")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's real target/state overrides out of these tests."""
    monkeypatch.delenv("AIDW_REPO", raising=False)
    monkeypatch.delenv("AIDW_STATE_DIR", raising=False)


def _named(checks: list[doctor.Check], name: str) -> doctor.Check:
    """The single check called ``name`` (doctor check names are unique)."""
    matches = [check for check in checks if check.name == name]
    assert len(matches) == 1, [check.name for check in checks]
    return matches[0]


# ---------------------------------------------------------------------------
# git fixtures: four real layouts (mirrors tests/test_layout.py)
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


def _make_supported(
    tmp_path: Path, *, task_worktree: bool = False, remote: str | None = FAKE_ORIGIN
) -> tuple[Path, Path]:
    """The §3.2 supported layout: bare repo plus sibling control/task worktrees."""
    bare = _make_bare(tmp_path, remote=remote)
    control = tmp_path / "main"
    _git_run(bare, "worktree", "add", "-q", str(control), "main")
    if task_worktree:
        _git_run(bare, "worktree", "add", "-q", "-b", "task", str(tmp_path / "task"), "main")
    return bare, control


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

#: ``gh --help`` excerpts for a build that has sub-issue support, and one that predates it.
_CURRENT_GH_HELP = {
    "issue view --help": (
        "JSON FIELDS\n  assignees, body, number, parent, state, subIssues,\n"
        "  subIssuesSummary, title, url\n"
    ),
    "issue create --help": (
        "FLAGS\n  -t, --title string\n      --parent number   Add the new issue as a sub-issue\n"
    ),
}
_OLD_GH_HELP = {
    "issue view --help": "JSON FIELDS\n  assignees, author, body, number, state, title\n",
    "issue create --help": "FLAGS\n  -t, --title string\n",
}


def _install_gh(
    monkeypatch: pytest.MonkeyPatch,
    *,
    version: str | None = "gh version 2.97.0 (2026-07-31)",
    help_output: dict[str, str] | None = None,
    path: str | None = "/usr/local/bin/gh",
    version_exit: int = 0,
) -> list[list[str]]:
    """Stand in for ``gh``; returns the list of argv arrays the checks invoked."""
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: path)
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: object = None) -> tuple[int, str]:
        assert cmd[0] == "gh", f"unexpected command: {cmd}"
        calls.append(cmd)
        if cmd[1] == "--version":
            return version_exit, version or ""
        if help_output is None:
            return 1, "gh: help unavailable"
        return 0, help_output.get(" ".join(cmd[1:]), "")

    monkeypatch.setattr(doctor, "_run", fake_run)
    return calls


def _install_pi(
    monkeypatch: pytest.MonkeyPatch,
    *,
    version: str | None = "1.2.0",
    path: str | None = "/usr/local/bin/pi",
    version_exit: int = 0,
) -> list[list[str]]:
    """Stand in for ``pi``; returns the list of argv arrays the checks invoked."""
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: path)
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: object = None) -> tuple[int, str]:
        assert cmd[0] == "pi", f"unexpected command: {cmd}"
        calls.append(cmd)
        return version_exit, version or ""

    monkeypatch.setattr(doctor, "_run", fake_run)
    return calls


def test_python_check_ok() -> None:
    check = _check_python()
    assert check.status == OK


def test_dependencies_importable() -> None:
    check = _check_dependencies()
    assert check.status == OK


def test_collect_checks_returns_results(fake_external_clis: None) -> None:  # noqa: ARG001
    checks = collect_checks()
    assert checks
    # Findings must be within the known status vocabulary.
    for check in checks:
        assert check.status in (OK, "WARN", FAIL)


def test_parse_pi_version() -> None:
    assert _parse_pi_version("0.74.2") == (0, 74, 2)
    assert _parse_pi_version("1.2.0 (node v24.18.0)") == (1, 2, 0)
    assert _parse_pi_version("pi 0.85.0") == (0, 85, 0)
    assert _parse_pi_version("pi: command not found") is None


def test_pi_check_ok_for_supported_pi(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_pi(monkeypatch, version="1.2.0")
    check = _check_pi()
    assert check.status == OK
    assert "1.2.0" in check.detail
    assert "/usr/local/bin/pi" in check.detail


def test_pi_check_ok_at_the_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_pi(monkeypatch, version="pi 0.85.0")
    assert _check_pi().status == OK


def test_pi_check_fails_below_the_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """The incident this check exists for: a stale ``pi`` shadowing a current one on PATH.

    It answered ``--version`` happily and then died loading extensions, which surfaced as a
    bare ``exit code 1`` with zero tokens in the run record.
    """
    _install_pi(monkeypatch, version="0.74.2", path="/Users/phil/.nvm/versions/node/v22.9.0/bin/pi")
    check = _check_pi()
    assert check.status == FAIL
    assert "0.74.2" in check.detail
    assert "/Users/phil/.nvm/versions/node/v22.9.0/bin/pi" in check.detail
    assert "0.85.0" in check.detail
    assert "which -a pi" in check.detail


def test_pi_check_warns_when_version_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unparseable or failing ``--version`` is not proof of an old Pi."""
    _install_pi(monkeypatch, version="", version_exit=1)
    assert _check_pi().status == WARN


def test_pi_check_fails_when_pi_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_pi(monkeypatch, path=None)
    assert _check_pi().status == FAIL


def test_parse_gh_version() -> None:
    assert _parse_gh_version("gh version 2.97.0 (2026-07-31)\nhttps://example") == (2, 97, 0)
    assert _parse_gh_version("gh: command not found") is None


def test_gh_version_check_ok_for_current_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_gh(monkeypatch, help_output=_CURRENT_GH_HELP)
    check = _check_gh_version()
    assert check.status == OK
    assert "2.97.0" in check.detail
    assert "/usr/local/bin/gh" in check.detail


def test_gh_version_check_fails_for_stale_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    """The incident this check exists for: an old ``gh`` shadowing a current one on PATH."""
    _install_gh(
        monkeypatch,
        version="gh version 2.65.0 (2025-01-06)",
        help_output=_OLD_GH_HELP,
        path="/Users/phil/.local/bin/gh",
    )
    check = _check_gh_version()
    assert check.status == FAIL
    assert "2.65.0" in check.detail
    assert "/Users/phil/.local/bin/gh" in check.detail
    assert "2.94.0" in check.detail
    assert "subIssues" in check.detail
    assert "--parent" in check.detail


def test_gh_version_check_fails_when_capability_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A new version number alone is not enough; the capability probe is authoritative."""
    _install_gh(monkeypatch, help_output=_OLD_GH_HELP)
    check = _check_gh_version()
    assert check.status == FAIL
    assert "lacks" in check.detail


def test_gh_version_check_warns_when_gh_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_gh(monkeypatch, path=None)
    check = _check_gh_version()
    assert check.status == WARN


def test_gh_version_check_warns_when_version_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_gh(monkeypatch, version_exit=1, help_output=_CURRENT_GH_HELP)
    check = _check_gh_version()
    assert check.status == WARN


def test_unreadable_probe_is_not_a_missing_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_gh(monkeypatch, help_output=None)
    assert _missing_gh_capabilities() == []


# ---------------------------------------------------------------------------
# git version floor (EXTRACTION.md §3.2 "Minimum git": 2.31)
# ---------------------------------------------------------------------------


def _install_git(
    monkeypatch: pytest.MonkeyPatch,
    *,
    version: str | None = "git version 2.39.5 (Apple Git-154)",
    path: str | None = "/usr/bin/git",
    version_exit: int = 0,
) -> list[list[str]]:
    """Stand in for ``git``; returns the list of argv arrays the check invoked."""
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: path)
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: object = None) -> tuple[int, str]:
        assert cmd[0] == "git", f"unexpected command: {cmd}"
        calls.append(cmd)
        return version_exit, version or ""

    monkeypatch.setattr(doctor, "_run", fake_run)
    return calls


def test_parse_git_version() -> None:
    assert _parse_git_version("git version 2.39.5 (Apple Git-154)") == (2, 39, 5)
    assert _parse_git_version("git version 2.31.0") == (2, 31, 0)
    assert _parse_git_version("git: command not found") is None


def test_git_version_check_ok_above_the_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_git(monkeypatch, version="git version 2.39.5 (Apple Git-154)")
    check = _check_git_version()
    assert check.status == OK
    assert "2.39.5" in check.detail
    assert "/usr/bin/git" in check.detail


def test_git_version_check_ok_at_the_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_git(monkeypatch, version="git version 2.31.0")
    assert _check_git_version().status == OK


def test_git_version_check_fails_below_the_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--path-format=absolute`` needs git 2.31; older git fails inside every command."""
    _install_git(monkeypatch, version="git version 2.30.9", path="/usr/local/bin/git")
    check = _check_git_version()
    assert check.status == FAIL
    assert "2.30.9" in check.detail
    assert "/usr/local/bin/git" in check.detail
    assert "2.31.0" in check.detail
    assert "--path-format=absolute" in check.detail


def test_git_version_check_fails_when_git_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Git is required by every command, so absence is a FAIL — unlike workflow-optional ``gh``."""
    _install_git(monkeypatch, path=None)
    check = _check_git_version()
    assert check.status == FAIL
    assert "required by every command" in check.detail


def test_git_version_check_warns_when_version_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing ``--version`` is not proof of an old git, so it stays advisory."""
    _install_git(monkeypatch, version_exit=1)
    check = _check_git_version()
    assert check.status == WARN
    assert "/usr/bin/git" in check.detail


def test_git_version_check_warns_when_version_output_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful command with no parseable version is still unreadable."""
    _install_git(monkeypatch, version="git release unknown")
    check = _check_git_version()
    assert check.status == WARN
    assert "unknown version" in check.detail
    assert "/usr/bin/git" in check.detail


def test_git_version_is_checked_outside_a_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_external_clis: None  # noqa: ARG001
) -> None:
    """The floor is an environment check: it reports before the target early-return."""
    monkeypatch.chdir(tmp_path)

    checks = collect_checks()

    assert _named(checks, "git version").status == OK
    names = [check.name for check in checks]
    assert names.index("git version") < names.index("repo root")
    assert _named(checks, "repo root").status == FAIL


def test_recorded_git_version_gate_row_matches_doctor_behaviour() -> None:
    """Review follow-up #64: the task's recorded audit must not contradict the code.

    Both unreadable-version cases are ``WARN`` at HEAD (the two tests above), so the
    ``build-results.md`` gate table may not record that case as a ❌ failure. A stale ❌
    in the permanent record misleads the next reader into thinking a gate failed when
    the suite is green — this row pins the record to the behaviour it claims.
    """
    doc = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "implementation-results"
        / "00-E2.8"
        / "build-results.md"
    )
    row = next(
        line
        for line in doc.read_text(encoding="utf-8").splitlines()
        if line.startswith("| git ≥ 2.31 floor")
    )

    assert "✅" in row
    assert "❌" not in row
    assert "version_exit=1" in row
    assert "_check_git_version" in row


# ---------------------------------------------------------------------------
# target-is-not-bare: a named FAIL with the §3.2 bootstrap (requirement 3)
# ---------------------------------------------------------------------------


def test_bare_target_fails_by_name_with_the_bootstrap(
    tmp_path: Path, fake_external_clis: None  # noqa: ARG001
) -> None:
    bare = _make_bare(tmp_path)

    checks = collect_checks(explicit=bare)

    check = _named(checks, "target repo")
    assert check.status == FAIL
    assert "bare repository" in check.detail
    assert f"git -C {bare.resolve()}" in check.detail
    assert "worktree add ../main main" in check.detail
    # A bare dir is not reported as the generic "repo root" refusal.
    assert "repo root" not in [c.name for c in checks]
    # Requirement 7: the toolkit root still reports past the early return.
    assert _named(checks, "toolkit root").status == OK
    assert run_doctor(explicit=bare) == 1


def test_bare_target_is_reachable_through_the_app_level_repo_option(
    tmp_path: Path, fake_external_clis: None  # noqa: ARG001
) -> None:
    """``aidw --repo <bare> doctor`` — the app option precedes the subcommand."""
    bare = _make_bare(tmp_path)

    result = runner.invoke(app, ["--repo", str(bare), "doctor"])

    assert result.exit_code == 1, result.output
    assert "target repo" in result.stdout
    assert "bare repository" in result.stdout
    assert "worktree add ../main main" in result.stdout
    # The trap the task prompt warns about: a per-command --repo would be rejected.
    assert "No such option" not in result.output
    assert "Traceback" not in result.output


def test_bare_target_is_reachable_through_aidw_repo_environment(
    tmp_path: Path, fake_external_clis: None  # noqa: ARG001
) -> None:
    """``AIDW_REPO`` participates in doctor target selection when no flag is given."""
    bare = _make_bare(tmp_path)

    result = runner.invoke(app, ["doctor"], env={"AIDW_REPO": str(bare)})

    assert result.exit_code == 1, result.output
    assert "target repo" in result.stdout
    assert "bare repository" in result.stdout
    assert "worktree add ../main main" in result.stdout


# ---------------------------------------------------------------------------
# control-worktree: the §3.2 clone-of-a-worktree trap, from both positions
# ---------------------------------------------------------------------------


def test_trap_clone_fails_the_control_worktree_check(
    tmp_path: Path, fake_external_clis: None  # noqa: ARG001
) -> None:
    clone, _child = _make_trap(tmp_path)

    checks = collect_checks(explicit=clone)

    control = _named(checks, "control worktree")
    assert control.status == FAIL
    assert "registered worktree" in control.detail
    assert "git clone --bare" in control.detail
    assert "worktree add ../main main" in control.detail
    # Fail before warn: the trap layout also puts state inside a tree, but a rejected
    # layout must never also report the advisory state-root WARN.
    assert _named(checks, "state root").status == OK
    assert run_doctor(explicit=clone) == 1


def test_trap_linked_child_fails_the_control_worktree_check(
    tmp_path: Path, fake_external_clis: None  # noqa: ARG001
) -> None:
    clone, child = _make_trap(tmp_path)

    checks = collect_checks(explicit=child)

    control = _named(checks, "control worktree")
    assert control.status == FAIL
    assert "registered worktree" in control.detail
    assert str(clone.resolve()) in control.detail
    assert _named(checks, "state root").status == OK
    assert run_doctor(explicit=child) == 1


def test_cli_doctor_from_the_trap_clone_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_external_clis: None  # noqa: ARG001
) -> None:
    clone, _child = _make_trap(tmp_path)
    monkeypatch.chdir(clone)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1, result.output
    assert "registered worktree" in result.stdout
    assert "Traceback" not in result.output


def test_cli_doctor_from_the_trap_linked_child_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_external_clis: None  # noqa: ARG001
) -> None:
    _clone, child = _make_trap(tmp_path)
    monkeypatch.chdir(child)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1, result.output
    assert "registered worktree" in result.stdout


# ---------------------------------------------------------------------------
# state-inside-tree: the §3.10 single-checkout WARN (requirement 6)
# ---------------------------------------------------------------------------


def test_single_checkout_warns_on_the_state_root_and_exits_zero(
    tmp_path: Path, fake_external_clis: None  # noqa: ARG001
) -> None:
    repo = _make_plain_clone(tmp_path)
    workspace = WorkspacePaths.resolve(TargetRepo.resolve(explicit=repo))

    checks = collect_checks(explicit=repo)

    state = _named(checks, "state root")
    assert state.status == WARN
    assert str(workspace.state_root) in state.detail
    assert str(repo.resolve()) in state.detail
    assert _named(checks, "control worktree").status == OK
    assert run_doctor(explicit=repo) == 0


def test_single_checkout_control_worktree_ok_detail_does_not_claim_non_membership(
    tmp_path: Path, fake_external_clis: None  # noqa: ARG001
) -> None:
    """Review follow-up #63: in a plain clone the workspace root IS the sole
    registered worktree (the self-entry check_layout's len == 1 gate exempts),
    so the OK detail must echo the guard's outcome instead of asserting
    non-membership.
    """
    repo = _make_plain_clone(tmp_path)
    workspace = WorkspacePaths.resolve(TargetRepo.resolve(explicit=repo))
    # The trigger's ground truth: the workspace root is the one listed worktree.
    listed = [entry.path for entry in git.worktrees(workspace.workspace_root)]
    assert listed == [workspace.workspace_root]

    control = _named(collect_checks(explicit=repo), "control worktree")

    assert control.status == OK
    assert "guard passed" in control.detail
    assert "is not a second registered worktree" in control.detail
    assert "is not a registered worktree" not in control.detail


def test_single_checkout_cli_output_uses_the_accurate_control_worktree_detail(
    tmp_path: Path, fake_external_clis: None  # noqa: ARG001
) -> None:
    """The corrected detail is visible in the user-facing doctor report."""
    repo = _make_plain_clone(tmp_path)

    result = runner.invoke(app, ["--repo", str(repo), "doctor"])

    assert result.exit_code == 0, result.output
    assert "control worktree" in result.stdout
    assert "clone-of-a-worktree guard passed" in result.stdout
    assert "is not a second registered worktree" in result.stdout
    assert "is not a registered worktree" not in result.stdout


# ---------------------------------------------------------------------------
# supported bare + sibling worktree: all five new checks OK (requirement 4/5/6)
# ---------------------------------------------------------------------------


def test_supported_layout_reports_the_new_checks_ok_from_each_worktree(
    tmp_path: Path, fake_external_clis: None  # noqa: ARG001
) -> None:
    _bare, control = _make_supported(tmp_path, task_worktree=True)

    for start in (control, tmp_path / "task"):
        checks = collect_checks(explicit=start)

        # All five new checks OK — no WARN among them. Unrelated checks (mcp config,
        # archify, …) legitimately may warn in a temporary repository.
        for name in NEW_CHECKS:
            assert _named(checks, name).status == OK, (start, name)
        assert _named(checks, "workspace root").detail == str(tmp_path.resolve())
        assert run_doctor(explicit=start) == 0


# ---------------------------------------------------------------------------
# Read-only and metamorphic (requirement 7)
# ---------------------------------------------------------------------------


def test_repo_checks_leave_git_state_and_the_state_root_untouched(
    tmp_path: Path, fake_external_clis: None  # noqa: ARG001
) -> None:
    _bare, control = _make_supported(tmp_path, task_worktree=True)
    target = TargetRepo.resolve(start=control)
    workspace = WorkspacePaths.resolve(target)
    before_status = git.status_short(target.root)
    before_worktrees = [
        (wt.path, wt.branch, wt.detached) for wt in git.worktrees(target.root)
    ]
    assert not workspace.state_root.exists()

    collect_checks(explicit=control)

    after_worktrees = [
        (wt.path, wt.branch, wt.detached) for wt in git.worktrees(target.root)
    ]
    assert git.status_short(target.root) == before_status
    assert after_worktrees == before_worktrees
    # §3.1: the checks must not create the state root under the workspace/target.
    assert not workspace.state_root.exists()
    assert not (tmp_path / ".aidw").exists()

    # The single-checkout side of the same check leaves no state directory behind either.
    plain = _make_plain_clone(tmp_path)
    plain_workspace = WorkspacePaths.resolve(TargetRepo.resolve(explicit=plain))
    assert not plain_workspace.state_root.exists()

    collect_checks(explicit=plain)

    assert not plain_workspace.state_root.exists()


def test_verdict_is_invariant_to_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_external_clis: None  # noqa: ARG001
) -> None:
    """Metamorphic: the report depends on the resolved target, not on the cwd."""
    _bare, control = _make_supported(tmp_path, task_worktree=True)

    from_control = [(c.name, c.status, c.detail) for c in collect_checks(explicit=control)]

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    from_elsewhere = [
        (c.name, c.status, c.detail) for c in collect_checks(explicit=control)
    ]
    assert from_elsewhere == from_control
