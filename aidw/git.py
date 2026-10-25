"""Git safety helpers (design §13).

AIDW enforces a small set of safety rules before it mutates anything: work happens on
the right branch and unrelated user changes are never overwritten. This module only
reads git state; the agents perform any commits the prompts specify.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(repo: Path, args: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return 127, "git: not found"
    return result.returncode, (result.stdout + result.stderr).strip()


def current_branch(repo: Path) -> str | None:
    code, out = _git(repo, ["branch", "--show-current"])
    if code != 0:
        return None
    return out or None


def status_short(repo: Path, paths: list[str] | None = None) -> str:
    args = ["status", "--porcelain"]
    if paths:
        args += ["--", *paths]
    code, out = _git(repo, args)
    return out if code == 0 else ""


def is_clean(repo: Path) -> bool:
    """True when the working tree has no staged, unstaged, or untracked changes.

    ``git status --porcelain`` omits gitignored files, so AIDT run artifacts do not
    count as dirty.
    """
    return status_short(repo) == ""


def commit_paths(repo: Path, paths: list[str], message: str) -> bool:
    """Commit only ``paths`` (narrow, owned paths); never broadens ``git add``."""
    code, _ = _git(repo, ["add", "--", *paths])
    if code != 0:
        return False
    code, _ = _git(repo, ["commit", "-m", message, "--", *paths])
    return code == 0


def is_on_main(repo: Path) -> bool:
    return current_branch(repo) == "main"


def diff_stat(repo: Path, ref: str = "main") -> str:
    code, out = _git(repo, ["diff", f"{ref}...HEAD", "--stat"])
    return out if code == 0 else ""


def changed_files(repo: Path, ref: str = "main") -> list[str]:
    """Names of files changed on the branch relative to ``ref``."""
    code, out = _git(repo, ["diff", f"{ref}...HEAD", "--name-only"])
    if code != 0:
        return []
    return [line for line in out.splitlines() if line.strip()]
