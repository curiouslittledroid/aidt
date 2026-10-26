"""Shared test fixtures and session-wide guards.

Tests must never leave run state in the toolkit's ``runs/`` directory: workflows write
under the per-repo state root (E1.4) and the prompt tests label their runs ``pytest``.
The session fixture below deletes any ``runs/*-pytest-*`` directory left under the
toolkit root, so a stale artifact from a crashed session is cleaned up automatically.
"""

from __future__ import annotations

import os
import shutil

import pytest

from aidw import doctor
from aidw.paths import toolkit_root

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
