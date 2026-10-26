"""Git safety helpers (design §13, EXTRACTION.md §3.2).

AIDW enforces a small set of safety rules before it mutates anything: work happens on
the right branch and unrelated user changes are never overwritten. The read helpers
never change git state; the sole mutating exception is the worktree pair
:func:`add_worktree`/:func:`remove_worktree`, which create and remove linked worktrees
(never commits, never discards a branch). The agents perform any commits the prompts
specify.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
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


# ---------------------------------------------------------------------------
# Worktree primitives (EXTRACTION.md §3.2, D20/E2.1)
#
# The supported layout is a bare repo plus sibling worktrees. One branch maps to
# one worktree (git refuses a second checkout), so these primitives are how AIDT
# learns the workspace root, finds the worktree for a branch, and creates/removes
# the task worktree. They are fail-closed like the rest of the module: a git
# failure is ``None``/``False``/``[]``, never an exception.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Worktree:
    """One entry of ``git worktree list --porcelain`` (EXTRACTION.md §3.2).

    ``branch`` is the short name (``refs/heads/`` stripped) or ``None`` for a
    detached HEAD; the ``bare`` marker is not a worktree and is never emitted.
    """

    path: Path
    branch: str | None
    detached: bool


def common_dir(repo: Path) -> Path | None:
    """Absolute git common dir — the bare repo path from every worktree.

    ``--path-format=absolute`` is required (git ≥ 2.31): without it an older git
    prints a *relative* path that ``dirname`` would resolve against the wrong cwd.
    In a linked worktree this is the bare repo (``<bare>``), **not** ``git_dir``
    (``<bare>/worktrees/<name>``).
    """
    code, out, _ = _git_out(repo, ["rev-parse", "--path-format=absolute", "--git-common-dir"])
    value = out.strip()
    if code != 0 or not value:
        return None
    return Path(value).resolve()


def workspace_root(repo: Path) -> Path | None:
    """The folder containing the bare repo and its sibling worktrees (§3.1).

    Always ``common_dir(repo).parent`` — never derived from ``git_dir`` (wrong in a
    linked worktree) or a ``.git`` file's target. ``None`` when ``repo`` is not a
    git repository.
    """
    common = common_dir(repo)
    return common.parent if common is not None else None


def worktrees(repo: Path) -> list[Worktree]:
    """Parse ``git worktree list --porcelain`` (§3.2 branch ↔ worktree fact).

    Blocks are blank-line separated and variable-length, so parsing is line-driven
    on prefixes — never by positional index. The ``bare`` block is the common dir,
    not a worktree, and is excluded.
    """
    code, out, _ = _git_out(repo, ["worktree", "list", "--porcelain"])
    if code != 0:
        return []
    return _parse_worktrees(out)


def _parse_worktrees(porcelain: str) -> list[Worktree]:
    """Turn the porcelain text into :class:`Worktree` entries, dropping ``bare``."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in porcelain.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)

    entries: list[Worktree] = []
    for block in blocks:
        first = block[0]
        if not first.startswith("worktree "):
            continue
        # ``bare`` is the common dir itself; emitting it would make a branchless
        # entry that ``worktree_for_branch`` could never match anyway.
        if any(line == "bare" for line in block):
            continue

        path = Path(first[len("worktree ") :].strip()).resolve()
        branch: str | None = None
        detached = False
        for line in block[1:]:
            if line == "detached":
                detached = True
            elif line.startswith("branch "):
                branch = line[len("branch ") :].strip().removeprefix("refs/heads/")
        entries.append(Worktree(path=path, branch=branch, detached=detached))
    return entries


def worktree_for_branch(repo: Path, branch: str) -> Path | None:
    """Path of the worktree with exactly this short branch name, else ``None``."""
    for worktree in worktrees(repo):
        if worktree.branch == branch:
            return worktree.path
    return None


def add_worktree(repo: Path, branch: str, *, base_branch: str = "main") -> Path | None:
    """Create the task worktree at ``<workspace_root>/<branch>`` (§3.2).

    Runs the per-task command ``git -C <repo> worktree add -b <branch>
    <workspace_root>/<branch> <base_branch>``. The target is a *sibling* of the
    control worktree; nesting it under ``<repo>/<branch>`` would put it inside an
    existing worktree and git would refuse. Returns the created resolved path, or
    ``None`` when ``repo`` is not a repository or git refuses (e.g. the branch is
    already checked out).
    """
    root = workspace_root(repo)
    if root is None:
        return None
    target = (root / branch).resolve()
    code, _ = _git(repo, ["worktree", "add", "-b", branch, str(target), base_branch])
    return target if code == 0 else None


def remove_worktree(repo: Path, path: Path, *, force: bool = False) -> bool:
    """Remove a worktree, returning git's success.

    The dirty/unmerged refusal is git's own; ``--force`` is passed through only when
    the caller explicitly asks. This never ``rm -rf``s and never ``reset --hard``s.
    """
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(path))
    code, _ = _git(repo, args)
    return code == 0


def is_linked_worktree(repo: Path) -> bool:
    """True when ``repo`` is a linked worktree, not a plain clone (§3.2).

    A linked worktree's ``.git`` is a *file* pointing into
    ``<bare>/worktrees/<name>``; a plain clone's is a directory. Filesystem-only,
    so there is no git spawn, and a missing ``.git`` (non-repo) reports ``False``.
    """
    return (repo / ".git").is_file()
