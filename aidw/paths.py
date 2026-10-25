"""Path and repository-root helpers.

AIDW must run from any working directory (design §12 / decision F6) and resolves every
path internally as an absolute path. Two independent roots exist:

* the **toolkit root** — where this package, its default prompts, agent configs and
  bundled scripts live. It is resolved from the installed package location, never from
  git, so it does not depend on the working directory or on which repository AIDW runs
  against.
* the **target repository root** — the working tree the workflows operate on, discovered
  from git.

E1.2/E1.3 formalise these into ``ToolkitPaths`` / ``TargetRepo`` types and add the
workspace and state roots; this module holds the transitional helpers until then.
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


def toolkit_root() -> Path:
    """Return the absolute root of the installed toolkit.

    Derived from this package's location (``aidw/`` sits directly under the toolkit
    root), so it is stable under ``uv tool install`` and when the working directory is
    unrelated to any repository. The root holds ``prompts/``, ``agent-configs/``,
    ``agents/`` and ``tests/``.
    """
    return Path(__file__).resolve().parent.parent


def aidt_root() -> Path:
    """Transitional alias for :func:`toolkit_root` (call sites are ported in E1.4)."""
    return toolkit_root()


def runs_dir() -> Path:
    """Return the run artifact directory (``<toolkit root>/runs``).

    Still rooted at the toolkit; E1.3 moves run state to the per-repo state root, which
    lives outside every worktree.
    """
    return toolkit_root() / "runs"
