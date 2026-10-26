"""Git safety helpers (design §13).

AIDW enforces a small set of safety rules before it mutates anything: work happens on
the right branch and unrelated user changes are never overwritten. This module only
reads git state; the agents perform any commits the prompts specify.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(repo: Path, args: list[str]) -> tuple[int, str]:
    code, out, err = _git_out(repo, args)
    return code, (out + err).strip()


def _git_out(repo: Path, args: list[str]) -> tuple[int, str, str]:
    """Run git and return ``(code, stdout, stderr)`` with stdout untouched.

    ``-z``-delimited output is parsed by splitting on NUL, so it must not be stripped:
    a path may legitimately begin or end with whitespace.
    """
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return 127, "", "git: not found"
    return result.returncode, result.stdout, result.stderr


def rev_parse(repo: Path, rev: str) -> str | None:
    """Resolve ``rev`` to a commit sha, or ``None`` when it does not exist."""
    code, out, _ = _git_out(repo, ["rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"])
    value = out.strip()
    return value if code == 0 and value else None


def changed_paths(repo: Path, base: str = "main") -> list[str] | None:
    """Paths whose content differs between ``base`` and the working tree.

    Compares ``base`` against the working tree (so committed and uncommitted work both
    count) with rename detection off, so a rename reports both the removed and the added
    path. Returns ``None`` — never an empty list — when ``base`` cannot be resolved, so a
    caller hashing the change set fails closed instead of reading "no changes".
    """
    if rev_parse(repo, base) is None:
        return None
    code, out, _ = _git_out(repo, ["diff", "--no-renames", "--name-only", "-z", base])
    if code != 0:
        return None
    return _split_nul(out)


def untracked_paths(repo: Path) -> list[str]:
    """Untracked, non-ignored paths (gitignored build and run output is excluded)."""
    code, out, _ = _git_out(repo, ["ls-files", "--others", "--exclude-standard", "-z"])
    return _split_nul(out) if code == 0 else []


def _split_nul(text: str) -> list[str]:
    return [item for item in text.split("\0") if item]


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
