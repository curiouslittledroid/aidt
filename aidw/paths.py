"""Path and repository-root helpers.

AIDW must run from any working directory (design §12 / decision F6) and resolves every
path internally as an absolute path. Two independent roots exist:

* the **toolkit root** — where this package, its default prompts, agent configs and
  bundled scripts live. It is resolved from the installed package location, never from
  git, so it does not depend on the working directory or on which repository AIDW runs
  against.
* the **target repository root** — the working tree the workflows operate on, discovered
  from git.

E1.2 formalises the toolkit root into the :class:`ToolkitPaths` type and E1.1 did the
same for the target repository (:class:`TargetRepo`). E1.3 adds the workspace and state
roots; :func:`aidt_root` and :func:`runs_dir` remain transitional aliases until E1.4.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class RepoNotFoundError(RuntimeError):
    """Raised when the containing git repository cannot be determined."""


class BareRepositoryError(RepoNotFoundError):
    """Raised when the target is a bare repository, which has no working tree.

    Deliberately a subclass of :class:`RepoNotFoundError` so existing
    ``except RepoNotFoundError`` handlers (``aidw/doctor.py``) keep reporting a
    failure instead of crashing.
    """


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


def _git_output(directory: Path, *args: str) -> str:
    """Run ``git`` in ``directory`` and return stripped stdout, or raise."""
    result = subprocess.run(
        ["git", *args],
        cwd=directory,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _is_bare_repository(directory: Path) -> bool:
    """Return ``True`` when ``directory`` is the root of a bare repository."""
    try:
        return _git_output(directory, "rev-parse", "--is-bare-repository") == "true"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _resolve_worktree_root(origin: Path) -> Path:
    """Resolve the working-tree root containing ``origin`` (an existing directory).

    Mirrors :func:`repo_root`'s ``--show-toplevel`` call plus the ``.git`` walk-up
    fallback, but detects a bare repository first so it refuses with
    :class:`BareRepositoryError` instead of the generic "Not inside a git
    repository" message. The returned path is absolute and resolved.
    """
    try:
        top = _git_output(origin, "rev-parse", "--show-toplevel")
    except (subprocess.CalledProcessError, FileNotFoundError):
        if _is_bare_repository(origin):
            raise BareRepositoryError(
                f"'{origin}' is a bare repository; run from a worktree instead "
                "(for example the control worktree checked out from it)."
            )
        for candidate in (origin, *origin.parents):
            if (candidate / ".git").exists():
                return candidate.resolve()
        raise RepoNotFoundError(
            f"Not inside a git repository (started at {origin}); cannot determine repo root."
        )
    return Path(top).resolve()


@dataclass(frozen=True)
class TargetRepo:
    """The target repository a workflow operates on (EXTRACTION.md §3.1).

    Deliberately distinct from the toolkit root: ``root`` is the working tree git
    operations and generated artifacts target, while the toolkit root is where the
    installed package and its default prompts live. The four fields are the only
    data the rest of the toolkit may consume.
    """

    root: Path
    git_dir: Path
    common_dir: Path
    base_branch: str = "main"

    @classmethod
    def resolve(
        cls, start: Path | None = None, explicit: Path | None = None
    ) -> "TargetRepo":
        """Resolve the target repository.

        ``start`` is the walk-up origin in default mode (cwd when omitted).
        ``explicit`` is the override supplied by ``--repo``/``AIDW_REPO`` (wired in
        E1.5); when given it wins over ``start``/cwd entirely, and an invalid
        override raises rather than falling back to cwd.
        """
        if explicit is not None:
            origin = Path(explicit).resolve()
            if not origin.is_dir():
                raise RepoNotFoundError(
                    f"Target repo override is not a directory: {origin}; "
                    "pass the path to a working tree, not a file or a missing path."
                )
        else:
            origin = (start or Path.cwd()).resolve()

        root = _resolve_worktree_root(origin)
        try:
            git_dir = Path(_git_output(root, "rev-parse", "--absolute-git-dir")).resolve()
            common_dir = Path(
                _git_output(
                    root,
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-common-dir",
                )
            ).resolve()
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise RepoNotFoundError(
                f"Not inside a git repository (started at {origin}); "
                "cannot determine repo root."
            ) from exc

        return cls(root=root, git_dir=git_dir, common_dir=common_dir)


def toolkit_root() -> Path:
    """Return the absolute root of the installed toolkit.

    Derived from this package's location (``aidw/`` sits directly under the toolkit
    root), so it is stable under ``uv tool install`` and when the working directory is
    unrelated to any repository. The root holds ``prompts/``, ``agent-configs/``,
    ``agents/`` and ``tests/``.

    This is the single source of truth for the toolkit location; :meth:`ToolkitPaths.resolve`
    delegates to it rather than re-deriving the value.
    """
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ToolkitPaths:
    """The installed toolkit's own root and the asset directories under it (§3.1/§3.12).

    Deliberately a distinct type from :class:`TargetRepo`: every path here is resolved
    from the installed package location, never from git or the working directory, so
    toolkit-relative and target-relative paths can never be interchanged. ``resolve()``
    is the sole intended construction entry point (a call-site convention, not an
    enforced invariant: like :class:`TargetRepo`, the frozen dataclass carries no init
    guard).
    """

    root: Path
    prompts_dir: Path
    agent_configs_dir: Path
    agents_dir: Path
    scripts_dir: Path

    @classmethod
    def resolve(cls) -> "ToolkitPaths":
        """Resolve the toolkit root and its asset directories.

        ``root`` is delegated to :func:`toolkit_root` (``Path(__file__)`` based) so there
        is one source of truth for the package location; this method never consults git
        or the current working directory. ``scripts_dir`` lives under ``prompts/`` — it is
        the ``prompts/scripts/`` directory the bundled helper scripts sit in
        (``inventory.REQUIRED_SCRIPTS``), not a ``root/scripts/`` directory.
        """
        root = toolkit_root().resolve()
        prompts_dir = (root / "prompts").resolve()
        return cls(
            root=root,
            prompts_dir=prompts_dir,
            agent_configs_dir=(root / "agent-configs").resolve(),
            agents_dir=(root / "agents").resolve(),
            scripts_dir=(prompts_dir / "scripts").resolve(),
        )


def aidt_root() -> Path:
    """Transitional alias for :func:`toolkit_root` (call sites are ported in E1.4)."""
    return toolkit_root()


def runs_dir() -> Path:
    """Return the run artifact directory (``<toolkit root>/runs``).

    Still rooted at the toolkit; E1.3 moves run state to the per-repo state root, which
    lives outside every worktree.
    """
    return toolkit_root() / "runs"
