"""Tests for narrow git commit helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from aidw import git


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)


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
