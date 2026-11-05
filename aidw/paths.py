"""Path and repository-root helpers.

AIDW must run from any working directory (design §12 / decision F6) and resolves every
path internally as an absolute path. Two independent roots exist:

* the **toolkit root** — where this package, its default prompts, agent configs and
  bundled scripts live. It is resolved from the installed package location, never from
  git, so it does not depend on the working directory or on which repository AIDW runs
  against.
* the **target repository root** — the working tree the workflows operate on, discovered
  from git.

E1.2 formalises the toolkit root into the :class:`ToolkitPaths` type, E1.1 did the same
for the target repository (:class:`TargetRepo`) and E1.3 adds the workspace and state
roots (:class:`WorkspacePaths`). Run artifacts are written under the per-repo state
root, never into the toolkit root or the target working tree.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
import shlex
from urllib.parse import urlparse


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
            # EXTRACTION.md §3.2: a bare repo has no working tree, so AIDW refuses with
            # a copy-pasteable §3.2 bootstrap. The branch word is the literal `main`
            # (the §3.2 example, matching TargetRepo.base_branch's current default) —
            # no config-resolved base branch exists at this raise site, and a bare dir
            # has no working tree to read `aidw/config.yaml` from (E3 owns that).
            raise BareRepositoryError(
                f"'{origin}' is a bare repository: it has no working tree, so AIDW has "
                "nothing to operate on. Bootstrap a control worktree and run from it:\n"
                f"  git -C {shlex.quote(str(origin))} worktree add ../main main"
            )
        for candidate in (origin, *origin.parents):
            if (candidate / ".git").exists():
                return candidate.resolve()
        raise RepoNotFoundError(
            f"Not inside a git repository (started at {origin}); cannot determine repo root."
        )
    return Path(top).resolve()


def _rev_parse_roots(origin: Path) -> tuple[Path, Path, Path] | None:
    """Resolve the worktree root, git dir and common dir in a single ``git`` call.

    ``git rev-parse`` prints one line per requested field, in argument order, so the three
    values :class:`TargetRepo` needs cost one process spawn instead of three — the hot path
    of every ``aidw`` invocation and of roughly 400 resolutions in the test suite.

    Returns ``None`` when the command fails or prints an unexpected shape, so the caller can
    fall back to the step-by-step path. That fallback keeps the specific diagnostics
    (:class:`BareRepositoryError` vs :class:`RepoNotFoundError`) exactly as they were.
    """
    try:
        out = _git_output(
            origin,
            "rev-parse",
            "--path-format=absolute",
            "--show-toplevel",
            "--absolute-git-dir",
            "--git-common-dir",
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    lines = out.splitlines()
    if len(lines) != 3 or not all(lines):
        return None
    root, git_dir, common_dir = (Path(line).resolve() for line in lines)
    return root, git_dir, common_dir


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
    #: Branch and worktree name derived from task ids (EXTRACTION.md §3.4). Until E3
    #: loads ``aidw/config.yaml`` this mirrors ``base_branch``: a hardcoded default on
    #: the frozen dataclass, overridable by constructing/replacing a ``TargetRepo``.
    branch_pattern: str = "{phase}-{task}"

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

        roots = _rev_parse_roots(origin)
        if roots is not None:
            root, git_dir, common_dir = roots
            return cls(root=root, git_dir=git_dir, common_dir=common_dir)

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


#: Environment variable the stage runner sets to the toolkit's absolute
#: ``prompts/scripts`` directory (EXTRACTION.md §3.6). Prompt-invoked helpers such as
#: ``review_followup.py`` resolve through it, because a path relative to the stage's
#: working directory would point inside the *target* repository, not the toolkit.
SCRIPTS_DIR_ENV_VAR = "AIDW_SCRIPTS_DIR"

#: Environment variable carrying the target repo's **resolved** ``github.markers`` and
#: ``github.labels`` to the bundled review-followup scripts (EXTRACTION.md §3.4/§3.9, D5;
#: task E6.1). One JSON object, so the standalone scripts stay stdlib-only and never read
#: ``aidw/config.yaml``: ``{"markers": {parent, child, summary}, "labels": {name: {color,
#: description}}}`` with defaults merged and provenance dropped. Set at both invocation
#: seams — the agent's stage environment (:func:`aidw.runner.run_stage`) and aidw's own
#: script runs (:func:`aidw.github._run`) — because a mismatch between the marker the
#: publisher writes and the one ``select`` searches for silently finds no parent issue.
#: ``prompts/scripts/review-followup/gh.py`` owns the parsing; that copy of the literal is
#: deliberate, because the scripts are copied into other repositories without ``aidw``.
REVIEW_FOLLOWUP_CONFIG_ENV_VAR = "AIDW_REVIEW_FOLLOWUP_CONFIG"

#: Environment variables the stage runner sets so a gate the *agent* runs lands in the
#: right run state (EXTRACTION.md E4.8). ``aidw gate run`` reads them to record an
#: outcome against the run and stage that produced it, which is what lets a later stage
#: cite it. Unset (a human at a terminal, or a repo under plain ``aidw gate run``) simply
#: means nothing is recorded; the gate still runs.
RUN_ID_ENV_VAR = "AIDW_RUN_ID"
STAGE_ENV_VAR = "AIDW_STAGE"


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


# ---------------------------------------------------------------------------
# Workspace and per-repo state roots (E1.3 / D18 / R1)
# ---------------------------------------------------------------------------

#: Environment variable overriding the state-root base (EXTRACTION.md §3.10).
STATE_DIR_ENV_VAR = "AIDW_STATE_DIR"

#: Fallback slug when even the workspace-root basename is empty (filesystem root).
_FALLBACK_SLUG = "repo"


def _origin_remote(repo_root: Path) -> str | None:
    """Return ``origin``'s URL for ``repo_root``, or ``None`` when git cannot tell us.

    Any failure (no ``origin`` remote, not a repository, git missing) is treated the
    same way: the caller falls back to the workspace-root basename. This deliberately
    never raises — a missing remote is a normal, supported configuration.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout.strip() or None


def origin_remote(repo_root: Path) -> str | None:
    """Public accessor for ``repo_root``'s ``origin`` remote URL (EXTRACTION.md §3.10).

    Exposes :func:`_origin_remote` across module boundaries — ``aidw/layout.py`` builds
    a copy-pasteable re-bootstrap command from it and must not import the underscore
    private name. Same contract: any git failure or a missing ``origin`` returns
    ``None``; a missing remote is a normal, supported configuration.
    """
    return _origin_remote(repo_root)


def _slug_from_remote(remote: str) -> str | None:
    """Derive ``owner-name`` from a git remote URL, or ``None`` when impossible.

    Handles both URL forms (``https://host/<owner>/<name>.git``,
    ``ssh://git@host/<owner>/<name>.git``) and the scp-like SSH form
    (``git@host:<owner>/<name>.git``), where a ``:`` precedes the path. A trailing
    ``.git`` is stripped, and the last two path segments are joined with ``-`` — so
    hosts with subgroups (more than two segments) still yield a distinct slug. Fewer
    than two path segments yields ``None`` so the caller can fall back.
    """
    text = remote.strip()
    if text.endswith(".git"):
        text = text[: -len(".git")]

    # scp-like syntax: `git@host:owner/name` — the ':' is a path separator, not a port.
    scp_like = re.match(r"^[^/]+@[^/:]+:(.+)$", text)
    if scp_like:
        text = scp_like.group(1)
    else:
        # For a URL the path component is after the host; for a plain/local path it is
        # the whole string, so this is a no-op there.
        text = urlparse(text).path or text

    segments = [segment for segment in text.split("/") if segment]
    if len(segments) < 2:
        return None
    return "-".join(segments[-2:])


def _repo_slug(repo_root: Path, workspace_root: Path) -> str:
    """``owner-name`` from ``origin``, else the workspace-root basename (§3.10/R1).

    Always a non-empty string: the slug guarantees a fallback state root shared by
    several repos cannot collide.
    """
    remote = _origin_remote(repo_root)
    if remote:
        slug = _slug_from_remote(remote)
        if slug:
            return slug
    return workspace_root.name or _FALLBACK_SLUG


def _is_usable_directory(path: Path) -> bool:
    """Whether ``path`` can be created/used as a directory, without creating it.

    Walks up to the nearest existing ancestor and checks it is a directory the current
    user can write to. Deliberately an access check rather than a guarded ``mkdir``:
    resolving paths must not write into a working tree (R8), and the single-checkout
    case (§3.10) resolves state *inside* the tree. Existence of ``path`` is not
    required — an ancestor that could host it is enough.
    """
    probe = path
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            return False
        probe = parent
    if not probe.is_dir():
        return False
    return os.access(probe, os.W_OK)


def _state_base(
    workspace_root: Path,
    *,
    state_dir_override: Path | None,
    home: Path | None,
) -> Path:
    """Resolve the pre-slug state base: override, else workspace, else home (§3.10/R1).

    The ``<workspace_root>/.aidw/state`` tier is only taken when it is usable; an
    unwritable workspace root therefore falls closed to ``~/.aidw/state`` rather than
    raising. Every tier is an absolute, resolved path — the ``<repo_slug>`` component is
    appended by the caller in *all* three tiers.
    """
    if state_dir_override is not None:
        return Path(state_dir_override).resolve()

    env = os.environ.get(STATE_DIR_ENV_VAR)
    if env:
        return Path(env).resolve()

    in_workspace = workspace_root / ".aidw" / "state"
    if _is_usable_directory(in_workspace):
        return in_workspace.resolve()

    home_dir = Path(home).resolve() if home is not None else Path.home().resolve()
    return (home_dir / ".aidw" / "state").resolve()


@dataclass(frozen=True)
class WorkspacePaths:
    """The workspace root and the per-repo state root (EXTRACTION.md §3.1/§3.2/§3.10).

    Deliberately a distinct type from :class:`TargetRepo` and :class:`ToolkitPaths`
    (§3.1's "two distinct types" rule): ``workspace_root`` is the folder containing the
    bare repository and all its sibling worktrees — not itself a git repository — and
    ``state_root`` is the per-repo run-state directory (``<state base>/<repo_slug>``),
    outside every worktree in the bare+worktrees layout (§3.2). In the §3.10
    single-checkout case a plain clone has ``common_dir == <root>/.git``, so
    ``workspace_root`` is the working tree itself and ``state_root`` lands *inside* it
    (``<root>/.aidw/state/<repo_slug>``) — E2.2's layout guard later warns on exactly
    that. ``repo_slug`` is the ``owner-name`` identifier that keeps a shared fallback
    state root from colliding between repos.

    ``resolve()`` is the sole intended construction entry point (a call-site convention,
    not an enforced invariant: like :class:`TargetRepo`, the frozen dataclass carries no
    init guard).
    """

    workspace_root: Path
    state_root: Path
    repo_slug: str

    @classmethod
    def resolve(
        cls,
        repo: TargetRepo,
        state_dir_override: Path | None = None,
        home: Path | None = None,
    ) -> "WorkspacePaths":
        """Resolve the workspace and state roots for ``repo``.

        ``workspace_root`` is ``repo.common_dir.parent`` — the ``dirname`` of the
        absolute git-common-dir (§3.2). It is derived from the already-resolved
        :class:`TargetRepo` and never re-runs git, so it is identical from every
        worktree of one repository and correct for the plain-clone case too (where
        ``common_dir == <root>/.git`` and ``workspace_root`` is the working tree).

        ``state_root`` is ``<base>/<repo_slug>`` with ``base`` = ``state_dir_override``
        (``AIDW_STATE_DIR`` when ``None``), else ``<workspace_root>/.aidw/state``, else
        ``<home>/.aidw/state``. Both injection points default to the real environment so
        tests can exercise every tier without touching it.
        """
        workspace_root = repo.common_dir.parent.resolve()
        repo_slug = _repo_slug(repo.root, workspace_root)
        base = _state_base(
            workspace_root, state_dir_override=state_dir_override, home=home
        )
        state_root = (base / repo_slug).resolve()
        return cls(
            workspace_root=workspace_root,
            state_root=state_root,
            repo_slug=repo_slug,
        )
