"""Phase 0 tests for repository path resolution."""

from __future__ import annotations

from pathlib import Path

from aidw.paths import aidt_root, repo_root, runs_dir


def test_repo_root_contains_aidt() -> None:
    root = repo_root()
    assert root.is_dir()
    assert (root / "aidt").is_dir()


def test_aidt_root_is_repo_aidt() -> None:
    assert aidt_root() == repo_root() / "aidt"


def test_runs_dir_is_under_aidt() -> None:
    assert runs_dir() == aidt_root() / "runs"


def test_repo_root_from_explicit_start() -> None:
    assert repo_root(Path(__file__).parent) == repo_root()
