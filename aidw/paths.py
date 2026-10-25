"""Path and repository-root helpers.

AIDW must run from any working directory (design §12 / decision F6) and resolve every
path internally as an absolute path rooted at the Mythical Forge repository.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class RepoNotFoundError(RuntimeError):
    """Raised when the containing git repository cannot be determined."""


def repo_root(start: Path | None = None) -> Path:
    """Return the absolute git repository root, walking up from ``start`` (or cwd)."""
    start = (start or Path.cwd()).resolve()

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        for candidate in (start, *start.parents):
            if (candidate / ".git").exists():
                return candidate
        raise RepoNotFoundError(
            f"Not inside a git repository (started at {start}); cannot determine repo root."
        )

    return Path(result.stdout.strip()).resolve()


def aidt_root(start: Path | None = None) -> Path:
    """Return the absolute ``<repo>/aidt`` directory."""
    return repo_root(start) / "aidt"


def runs_dir(start: Path | None = None) -> Path:
    """Return the absolute per-run artifact directory (``aidt/runs``)."""
    return aidt_root(start) / "runs"
