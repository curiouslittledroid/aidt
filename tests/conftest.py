"""Shared test fixtures and session-wide guards.

Tests must never leave run state in the toolkit's ``runs/`` directory: workflows write
under the per-repo state root (E1.4) and the prompt tests label their runs ``pytest``.
The session fixture below deletes any ``runs/*-pytest-*`` directory left under the
toolkit root, so a stale artifact from a crashed session is cleaned up automatically.

It also owns the shared real-git fixtures: the session-wide commit identity and
:func:`worktree_repo`, which builds the EXTRACTION.md §3.2 supported layout (a bare repo
with ``main`` and ``task`` sibling worktrees) once per test (E2.9).

Finally it owns the **single** extraction of the roadmap format doc's worked example
(E5.4, EXTRACTION.md §3.7): :class:`RoadmapExample`, handed to tests as the
``roadmap_example`` fixture. Both ``test_roadmap.py`` and ``test_roadmap_format.py`` parse
the doc's current bytes through it, so the doc and ``aidw/roadmap.py`` cannot drift.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from aidw import doctor
from aidw.paths import toolkit_root
from aidw.roadmap import TASK_RE

#: Commit identity exported once for the whole session. Roughly 300 repositories are
#: created across the suite, and a per-repo ``git config user.email``/``user.name`` pair
#: cost two process spawns each (``GIT_AUTHOR_*``/``GIT_COMMITTER_*`` make them redundant).
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}

#: Must match ``RUN_LABEL`` in ``tests/test_prompt_workflow.py``. ``run_id`` is
#: ``<stamp>-<label>-<workflow>``, so the label is its own ``-``-separated segment.
TEST_RUN_LABEL = "pytest"


def _remove_test_runs() -> None:
    """Delete run directories the test suite created under the toolkit ``runs/``."""
    runs = toolkit_root() / "runs"
    if not runs.is_dir():
        return
    for path in runs.iterdir():
        if path.is_dir() and TEST_RUN_LABEL in path.name.split("-"):
            shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _clean_test_runs() -> None:
    """Remove test-created runs before and after the session.

    Cleaning *before* the session also clears leftovers from a previously interrupted
    run, whose teardown never executed.
    """
    _remove_test_runs()
    yield
    _remove_test_runs()


@pytest.fixture(scope="session", autouse=True)
def _git_identity() -> None:
    """Give every repository a commit identity without a ``git config`` spawn each.

    ``git commit`` needs ``user.name``/``user.email``; the environment variables satisfy it
    for every repo the suite builds, so the repo fixtures only run ``git init``. The previous
    values are restored so the session does not leak into an outer process.
    """
    previous = {name: os.environ.get(name) for name in GIT_IDENTITY}
    os.environ.update(GIT_IDENTITY)
    yield
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


# ---------------------------------------------------------------------------
# The §3.2 supported worktree layout (E2.9)
# ---------------------------------------------------------------------------


def _git_run(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git in ``directory``, raising on failure.

    The commit identity comes from :func:`_git_identity`'s session environment, so no
    test — and no fixture — configures identity inside each temporary repo (AGENTS.md):
    two spawns per temporary repo across ~300 repos.
    """
    return subprocess.run(
        ["git", *args],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@dataclass(frozen=True)
class WorktreeRepo:
    """One repository wired as EXTRACTION.md §3.2 specifies (E2.9).

    ``bare`` is the bare clone — the common dir every worktree is linked off — and
    ``control``/``task`` are *sibling* linked worktrees, never worktrees of each other
    and never nested inside one another (§3.2's rejected layouts). ``workspace`` is the
    directory all of them sit directly under, i.e. the ``tmp_path`` root.

    Container name and fixture name are prompt-fixed for E2.9: the spec fixes the
    *layout*, not the helper's naming.
    """

    bare: Path
    control: Path
    task: Path
    workspace: Path

    def add_task(self, branch: str, *, base: str = "main") -> Path:
        """Create a *further* sibling worktree on ``branch`` off ``base``.

        Runs §3.2's per-task command from the **control** worktree — the position
        ``aidw.git.add_worktree`` runs from — so a consumer asserting the real wiring
        sees the same shape. The branch is born in its own worktree; creating it on
        ``main`` and moving it is impossible (one branch, one worktree, §3.2).

        Raises ``subprocess.CalledProcessError`` when git refuses, which is the honest
        contract for a helper that returns a ``Path``: the branch is already checked
        out (``add_task("task")`` — use ``repo.task`` for the pre-created worktree), the
        branch name already exists, or the target path is already occupied. It cannot
        return ``None`` quietly the way ``aidw.git.add_worktree`` does, because a silent
        ``None`` would let a test pass while asserting nothing.
        """
        path = self.workspace / branch
        _git_run(self.control, "worktree", "add", "-q", "-b", branch, str(path), base)
        return path.resolve()


@pytest.fixture
def worktree_repo(tmp_path: Path, _git_identity: None) -> WorktreeRepo:
    """Build the §3.2 supported layout under ``tmp_path`` and hand back its paths.

    ``git init -b main`` of a committed seed → ``git clone --bare`` to
    ``<workspace>/bare.git`` → ``git -C bare.git worktree add ../main main`` (the
    control worktree) → ``git -C <control> worktree add -b task <workspace>/task main``
    (the per-task command, from the control worktree, mirroring
    ``aidw.git.add_worktree``).

    The seed must be *committed* before the bare clone: an empty ``git init`` has no
    ``main`` ref, so ``worktree add ../main main`` would fail with "invalid reference".

    Function-scoped on ``tmp_path`` deliberately — a session-scoped bare repo with
    registered worktrees would leak checkouts between tests. There is no teardown
    because pytest removes ``tmp_path``: no explicit teardown spawns, and nothing is
    written outside ``tmp_path`` (no ``.aidw/state``, no toolkit ``runs/``), so
    ``_clean_test_runs`` stays green. The ``seed`` directory stays behind as the clone
    source; it is not a worktree and ``git.worktrees`` never reports it.
    """
    workspace = tmp_path.resolve()

    seed = workspace / "seed"
    seed.mkdir()
    _git_run(seed, "init", "-q", "-b", "main")
    (seed / "f.txt").write_text("x", encoding="utf-8")
    _git_run(seed, "add", ".")
    _git_run(seed, "commit", "-qm", "init")

    bare = workspace / "bare.git"
    _git_run(workspace, "clone", "--bare", "-q", str(seed), str(bare))

    # §3.2's one-time bootstrap: the control worktree is linked off the bare repo and
    # named relative to it, so ``bare.git`` and ``main`` are siblings.
    control = workspace / "main"
    _git_run(bare, "worktree", "add", "-q", "../main", "main")

    # §3.2's per-task command, run from the control worktree (not the bare repo).
    task = workspace / "task"
    _git_run(control, "worktree", "add", "-q", "-b", "task", str(task), "main")

    return WorktreeRepo(
        bare=bare.resolve(),
        control=control.resolve(),
        task=task.resolve(),
        workspace=workspace,
    )


@pytest.fixture
def fake_external_clis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for the ``pi`` and ``gh`` binaries ``aidw doctor`` shells out to.

    ``pi --version`` and the ``gh`` probes are real node/network startups (~0.5 s and ~0.08 s
    each, ~25 s across the suite) and their outcome is irrelevant to what the doctor tests
    assert. The fake reports a current, capable ``gh`` so the ``gh version`` check stays OK
    rather than failing on an unreadable capability probe.

    Opt in explicitly — ``test_doctor``'s own tests install their own ``gh`` stubs and must
    keep observing the argv those stubs record.
    """
    real_run = doctor._run
    real_which = shutil.which

    def fake_run(cmd: list[str], *args: object, **kwargs: object) -> tuple[int, str]:
        if cmd and cmd[0] == "pi":
            return 0, "pi 0.85.0"
        if cmd and cmd[0] == "gh":
            rest = list(cmd[1:])
            if rest[:2] == ["auth", "status"]:
                return 0, "github.com\n  Logged in to github.com account tester (keyring)"
            if rest[:1] == ["--version"]:
                return 0, "gh version 2.97.0 (2026-07-31)"
            if rest[:2] == ["issue", "view"]:
                return 0, "JSON Fields: assignees, body, subIssues, subIssuesSummary"
            if rest[:2] == ["issue", "create"]:
                return 0, "      --parent string   Attach the issue to a parent issue"
            return 0, ""
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(doctor, "_run", fake_run)
    monkeypatch.setattr(
        doctor.shutil,
        "which",
        lambda name: f"/usr/local/bin/{name}" if name in ("pi", "gh") else real_which(name),
    )


# ---------------------------------------------------------------------------
# The canonical roadmap example (E5.4, roadmap-format.md §9)
# ---------------------------------------------------------------------------

#: The document that owns the roadmap format contract (E5.1). Since E5.4 its §9 fenced
#: block is the **single** canonical example: every test parses *these bytes* on every run
#: instead of a private copy, so a doc edit and the parser cannot silently diverge
#: (EXTRACTION.md §3.7).
ROADMAP_FORMAT_DOC = toolkit_root() / "docs" / "roadmap-format.md"

#: The filename §9 names for the example. The ``07`` prefix is the phase authority
#: (``_FILENAME_RE``, roadmap-format.md §3) and pairs with the doc's ``# Phase 07:``
#: heading; writing the example under any other name would change ``phase`` and
#: ``phase_title``.
ROADMAP_EXAMPLE_NAME = "07 - Example Roadmap.md"
ROADMAP_EXAMPLE_PHASE = "07"


def _fenced_blocks(text: str) -> list[str]:
    """Every fenced code block body in a markdown document (fence lines dropped)."""
    blocks: list[str] = []
    body: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("```"):
            if body is None:
                body = []
            else:
                blocks.append("\n".join(body))
                body = None
            continue
        if body is not None:
            body.append(line)
    return blocks


def _example_text(doc: Path) -> str:
    """The one worked-example block in ``doc``, as a roadmap file's contents.

    Selected by content — a complete roadmap file starts with a phase heading *and* carries
    at least one task entry — rather than by position, so the doc may grow other fenced
    blocks without silently handing this suite the wrong one. Exactly one match is
    required: two competing examples would let the doc and the parser drift in one of them,
    which is the whole reason this guard exists (E5.4). Re-reads ``doc`` on every call: no
    cached copy of the example survives anywhere else.
    """
    candidates = [
        block
        for block in _fenced_blocks(doc.read_text(encoding="utf-8"))
        if block.startswith("# Phase") and any(TASK_RE.match(line) for line in block.splitlines())
    ]
    assert len(candidates) == 1, (
        f"expected exactly one complete worked example in {doc}, "
        f"found {len(candidates)}"
    )
    return candidates[0] + "\n"


@dataclass(frozen=True)
class RoadmapExample:
    """Handle on the roadmap format doc's canonical worked example (E5.4, §9).

    Handed to tests as the ``roadmap_example`` fixture rather than imported from this
    module: two ``conftest`` files are collected (``tests/`` and
    ``prompts/scripts/review-followup/tests``) under the same top-level module name, so a
    runtime ``from conftest import …`` binds whichever was imported last and breaks the
    full-suite run — the same reason ``test_layout.py``/``test_worktree_cli.py`` keep their
    ``WorktreeRepo`` import type-only.

    ``doc`` is overridable per call so a test can prove the parsed fields come from the
    doc's *bytes* (a doctored copy inside its own ``tmp_path``) and not from a cached
    string. Nothing here writes outside the caller-supplied directory.
    """

    doc: Path = ROADMAP_FORMAT_DOC
    name: str = ROADMAP_EXAMPLE_NAME
    phase: str = ROADMAP_EXAMPLE_PHASE

    def text(self, *, doc: Path | None = None) -> str:
        """The example's roadmap-file contents, extracted from ``doc`` (read fresh)."""
        return _example_text(self.doc if doc is None else doc)

    def write(self, directory: Path, *, doc: Path | None = None) -> Path:
        """Write the example into ``directory`` under §9's filename and return the path."""
        path = directory / self.name
        path.write_text(self.text(doc=doc), encoding="utf-8")
        return path


@pytest.fixture(scope="session")
def roadmap_example() -> RoadmapExample:
    """The doc's canonical roadmap example (E5.4) — one definition, one guard, no copy."""
    return RoadmapExample()
