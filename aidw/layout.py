"""Target and workspace layout guards (EXTRACTION.md §3.1/§3.2/§3.10, D20/E2.2).

The supported layout is a bare repository plus sibling worktrees (§3.2). Two layouts
break that model and must be rejected before any workflow runs, and one must be
reported as a warning:

* **bare directory as the target** — refused inside
  :meth:`aidw.paths.TargetRepo.resolve` with :class:`aidw.paths.BareRepositoryError`
  (§3.2 "the bare dir as a target"); this module upgrades that message's corrective
  command but does not re-check the bare dir (a duplicate check would be dead code).
* **a plain clone with worktrees hanging off it** — the §3.2 "clone-of-a-worktree"
  trap. ``dirname(<absolute git-common-dir>)`` becomes the clone folder, so run state
  lands inside a prunable worktree. :func:`check_layout` raises :class:`LayoutError`.
* **the §3.10 single-checkout case**, where the state root falls inside the target
  working tree — :func:`check_layout` returns an advisory warning string.

:func:`check_layout` is read-only. It consults the :func:`aidw.git.worktrees`
primitive (one ``git worktree list`` spawn) and never writes and never runs a mutating
git command. ``cli._roots`` is the only caller, so every command pays exactly that one
extra spawn alongside the spawns ``TargetRepo.resolve``/``WorkspacePaths.resolve``
already make there (AGENTS.md Tests: acknowledge the spawn rather than hide it).
"""

from __future__ import annotations

import shlex

from aidw import git, paths
from aidw.paths import TargetRepo, WorkspacePaths


class LayoutError(RuntimeError):
    """Raised when the target's layout cannot be run on (EXTRACTION.md §3.2/§3.10)."""


def check_layout(target: TargetRepo, workspace: WorkspacePaths) -> list[str]:
    """Verify the resolved target/workspace layout (EXTRACTION.md §3.2/§3.10).

    Returns advisory warning strings (the caller echoes them) and raises
    :class:`LayoutError` for hard failures. Both operands are expected to be already
    resolved (``TargetRepo.resolve``/``WorkspacePaths.resolve`` do that), so every path
    compared here is resolved and no path is re-derived from raw strings.

    Ordering is fixed: the clone-of-a-worktree failure is decided before the
    state-inside-working-tree warning, because the trap layout *also* places the state
    root inside a tree and must fail rather than warn (§3.2 beats §3.10).

    The fail closes on an unverifiable worktree list: ``git.worktrees`` returns ``[]``
    both when git fails and when there are genuinely no entries, and a resolved working
    tree always lists at least itself — so ``[]`` after a successful resolve means the
    list could not be read, never that the layout is clean.
    """
    worktrees = git.worktrees(target.root)
    if not worktrees:
        raise LayoutError(_unverifiable_worktree_list_message(target))

    worktree_paths = [entry.path for entry in worktrees]

    # §3.2's literal rule ("the resolved workspace root is itself a registered worktree
    # of the same repository") also matches the legitimate single-checkout plain clone
    # that §3.10 blesses with a warning — its sole entry is itself. Gate on list
    # membership *and* more than one entry so the trap fires from both rejected-layout
    # positions (from the clone: workspace_root == target.root; from a linked child:
    # workspace_root == the clone, target.root == the child) while exempting that
    # single-checkout self-entry. Never gate on workspace_root == target.root: a linked
    # child hanging off a plain clone is exactly the position that must fail.
    if workspace.workspace_root in worktree_paths and len(worktree_paths) > 1:
        raise LayoutError(_clone_of_worktree_message(target, workspace))

    warnings: list[str] = []
    # Compare against the working tree (``target.root``), never ``workspace.workspace_root``:
    # in the supported layout state sits inside the workspace root by design
    # (``<workspace>/.aidw/state/<slug>``) and outside every worktree, so the workspace
    # root would warn on the healthy layout.
    if workspace.state_root.is_relative_to(target.root):
        warnings.append(_state_inside_working_tree_message(target, workspace))
    return warnings


def _unverifiable_worktree_list_message(target: TargetRepo) -> str:
    """Fail-closed message for ``git worktree list`` returning nothing (§3.2)."""
    return (
        f"Refusing to run: the worktree list for '{target.root}' is unverifiable — "
        "`git worktree list` reported no worktrees, so AIDW cannot tell whether this "
        "layout is the supported bare + sibling-worktree model. A resolved working "
        "tree always lists at least itself, so this means the git command failed "
        f"(run `git -C {target.root} worktree list` to diagnose)."
    )


def _clone_of_worktree_message(target: TargetRepo, workspace: WorkspacePaths) -> str:
    """Cause plus copy-pasteable §3.2 re-bootstrap for the clone-of-a-worktree trap.

    Every value is real: ``<bare>``/``<parent>`` derive from the rejected clone's parent
    and ``<origin>`` from :func:`aidw.paths.origin_remote`. When there is no ``origin``
    remote — a normal, supported configuration — the clone source falls back to the
    detected rejected clone itself (``workspace.workspace_root``) so both bootstrap
    steps stay present with real paths rather than a placeholder.

    The clone step runs *before* the ``mv`` so a local clone source still exists when
    the source is the rejected clone; the ``mv`` frees ``<parent>/main`` for the new
    control worktree when the old clone occupies that canonical name.
    """
    clone = workspace.workspace_root
    parent = clone.parent
    origin = paths.origin_remote(target.root) or str(clone)
    bare = parent / "bare.git"
    control = parent / "main"
    quote = shlex.quote
    return (
        f"Refusing to run: the workspace root '{clone}' is itself a registered "
        "worktree of this repository (EXTRACTION.md §3.2 rejected layout — a plain "
        "clone with worktrees hanging off it). Run state would land inside a prunable "
        "worktree.\n"
        "Re-bootstrap the workspace once, from outside the rejected clone:\n"
        f"  git clone --bare {quote(origin)} {quote(str(bare))}\n"
        f"  mv {quote(str(clone))} {quote(str(clone) + '.rejected')}\n"
        f"  git -C {quote(str(bare))} worktree add ../main main\n"
        f"(The 'mv' is only needed while the old clone still occupies {control}.) "
        f"Then run AIDW from the new control worktree '{control}' and delete the old "
        "clone."
    )


def _state_inside_working_tree_message(
    target: TargetRepo, workspace: WorkspacePaths
) -> str:
    """Advisory warning for the §3.10 single-checkout case."""
    return (
        f"Warning: the run state root '{workspace.state_root}' falls inside the target "
        f"working tree '{target.root}' (EXTRACTION.md §3.10 single-checkout case), so "
        "`git worktree remove` or a clean can delete run state. Prefer the bare + "
        "sibling-worktree layout (§3.2)."
    )
