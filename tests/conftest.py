"""Shared test fixtures and session-wide guards.

Tests must never leave run state in the toolkit's ``runs/`` directory: workflows take an
explicit ``runs_dir`` and the prompt tests label their runs ``pytest``. The session
fixture below deletes any ``runs/*-pytest-*`` directory, so a run that slips past the
override — or one left behind by a crashed session — is cleaned up automatically.
"""

from __future__ import annotations

import shutil

import pytest

from aidw.paths import toolkit_root

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
