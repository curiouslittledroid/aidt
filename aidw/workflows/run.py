"""``aidw run`` — convenience chains (design §8.6).

- ``task-to-pr <phase> <epic> <task>`` runs ``prompt`` then ``implement`` on the branch
  the prompt workflow creates.
- ``review-and-fix --pr <n>`` runs ``review`` then ``fix``.
- ``prompt-to-fix <phase> <epic> <task> [--pr <n>]`` runs the whole cycle:
  ``prompt`` → ``implement`` → ``review`` → ``approve-followups`` (auto-approved, unless
  refused with ``--deny-gates``) → ``fix``. The PR number comes from the ``implement``
  run's state (``--pr`` overrides it; a dry run uses a ``0`` placeholder).

Each workflow is a full orchestrator. A chain stops at the first non-zero exit and
returns that code, leaving the state of the completed workflows on disk (resumable with
``aidw implement --resume``).

``prompt-to-fix`` is the only chain that auto-approves a gate it would otherwise ask
about (decision I1): that is what makes the cycle unattended, and it is scoped to
``approve-followups`` so ``approve-implementation-pr`` and ``approve-fix-pr`` keep their
normal --yes/interactive semantics. A ``--deny-gates approve-followups`` still refuses it
(``deny`` wins over ``skip`` in ``aidw.gates.decide``).

A chain whose review published nothing ends **gracefully** (exit 0) after that review
rather than running the fix loop into its entry postcondition (decision I2). ``review``
records ``pr.followups_published``; with no review-follow-up parent issue there is nothing
for ``approve-followups`` to approve and nothing for the fixer to fix, so the chain prints
``chain complete.`` and returns 0. That guard is evidence-based, never an assumption: an
earlier round's follow-ups keep the loop, and an unreadable record keeps the old path.

This module takes no run lock itself (EXTRACTION.md §3.2, E2.7): each workflow it calls
acquires and releases its **own** worktree key in turn (``prompt`` the control worktree,
then ``implement`` the task worktree it created, …), so the two are never held at once and
a chain cannot deadlock against itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

from aidw import git
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.state import list_runs
from aidw.workflows import fix as fix_workflow
from aidw.workflows import implement as implement_workflow
from aidw.workflows import prompt as prompt_workflow
from aidw.workflows import review as review_workflow

#: The ``fix`` gate this chain approves unattended (design §6, §8.6).
GATE_FOLLOWUPS = fix_workflow.GATE_FOLLOWUPS

#: ``state.pr`` key ``review`` records on both successful exits (decision I2).
PR_FOLLOWUPS = review_workflow.PR_FOLLOWUPS


def find_task_prompt(repo: Path, phase: str, task: str) -> Path | None:
    """Newest ``docs/task-prompts/<phase>-<task>*.md`` (the author may not use ``-prompt``)."""
    root = repo / "docs" / "task-prompts"
    if not root.is_dir():
        return None
    candidates = sorted(
        root.glob(f"{phase}-{task}*.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _resolved_task_prompt(
    repo: Path, phase: str, task: str, *, dry_run: bool
) -> Path | None:
    """The prompt path ``implement`` should consume, or ``None`` when none was produced.

    A dry run never writes the prompt, so it keeps the conventional path (the same
    contract ``prompt --dry-run`` prints) rather than scanning for a file that cannot
    exist yet.
    """
    if dry_run:
        return repo / "docs" / "task-prompts" / f"{phase}-{task}-prompt.md"
    return find_task_prompt(repo, phase, task)


def _locate_task_worktree(
    repo: TargetRepo,
    workspace: WorkspacePaths,
    phase: str,
    task: str,
    *,
    dry_run: bool,
) -> tuple[str | None, Path | None, int | None]:
    """Derive the task branch and locate its worktree for the chain (E2.6 req 5).

    Returns ``(branch, worktree, refusal_code)``. The chain has the ids but not the
    prompt filename, so it derives the branch exactly as ``prompt``/``implement`` do
    (``derive_branch_name``). ``branch`` is ``None`` only when ``branch_pattern`` is
    malformed — exit 2 before any lookup. A non-dry run whose worktree is absent prints
    the §3.2 command and returns 4 (the same refusal ``implement`` gives); a dry run has
    no worktree to locate and no refusal, keeping its conventional-path fallback.
    """
    branch = implement_workflow.derive_branch_name(
        repo.branch_pattern, phase=phase, task=task
    )
    if branch is None:
        print(
            f"malformed repo.branch_pattern {repo.branch_pattern!r}: it must be a "
            "format string referencing both `{phase}` and `{task}` "
            '(e.g. "{phase}-{task}").',
            file=sys.stderr,
        )
        return branch, None, 2
    if dry_run:
        return branch, None, None
    worktree = git.worktree_for_branch(repo.root, branch)
    if worktree is None:
        command = implement_workflow.worktree_add_command(
            workspace, branch, repo.base_branch
        )
        print(
            f"chain stopped: no worktree for `{branch}`. Create it first:\n  {command}",
            file=sys.stderr,
        )
        return branch, None, 4
    return branch, worktree, None


def find_pr_number(runs_root: Path, branch: str | None) -> int | None:
    """The PR number the newest ``implement`` run recorded for ``branch``.

    ``implement``'s ``/pr`` stage writes ``pr.number`` into its ``state.json`` when it
    parses the PR URL (``implement._record_pr``); this re-reads that instead of asking
    ``gh`` for the branch's PR, so the chain adds no new GitHub call and works even when
    the PR was opened moments ago (``gh pr view <n>`` is what ``review``/``fix`` use
    next, which does need the network).
    """
    if not branch:
        return None
    matches = [
        state
        for state in list_runs(runs_root)
        if state.workflow == "implement" and state.git.get("branch") == branch
    ]
    for state in reversed(matches):
        number = state.pr.get("number")
        if isinstance(number, int) and not isinstance(number, bool) and number > 0:
            return number
    return None


def review_published_followups(runs_root: Path, pr: int) -> bool | None:
    """Whether any ``review`` run of ``pr`` published review follow-ups (decision I2).

    ``review`` records ``pr.followups_published`` in its run state on both successful
    exits, so the chain re-reads the state it just wrote instead of asking ``gh`` a
    second time — the same trade-off ``find_pr_number`` makes for the PR number.

    ``True`` as soon as one review of this PR published a parent issue: an earlier
    round's follow-ups outlive a later "approving, nothing to publish" review, and the
    fix loop must still run for them. ``False`` when the only recorded outcome is
    "nothing to publish" — the PR has no review-follow-up parent issue, so the fix loop
    has nothing to approve or fix. ``None`` when no review run of this PR is on disk
    (a ``--dry-run``, or a state root this chain did not write), which keeps the
    pre-I2 behaviour of running ``fix`` rather than guessing.
    """
    recorded = [
        state.pr.get(PR_FOLLOWUPS)
        for state in list_runs(runs_root)
        if state.workflow == "review" and state.pr.get("number") == pr
    ]
    flags = [value for value in recorded if isinstance(value, bool)]
    if not flags:
        return None
    return any(flags)


def _ended_because_nothing_was_published(pr: int) -> int:
    """Report the graceful end of a chain whose review published no follow-ups."""
    print(
        f"chain:  review published no follow-ups for PR #{pr}; nothing for the fix "
        "loop to approve or fix."
    )
    print("chain complete.")
    return 0


def task_to_pr(
    *,
    phase: str,
    epic: str,
    task: str,
    repo: TargetRepo,
    aidt: ToolkitPaths,
    workspace: WorkspacePaths,
    approve_all: bool = False,
    skip_gates: list[str] | None = None,
    deny_gates: list[str] | None = None,
    gate_default: str | None = None,
    strict: bool = False,
    dry_run: bool = False,
    parallel: bool = False,
    stream: bool = False,
) -> int:
    code = prompt_workflow.run(
        phase=phase,
        epic=epic,
        task=task,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
        approve_all=approve_all,
        skip_gates=list(skip_gates or []),
        deny_gates=deny_gates,
        gate_default=gate_default,
        strict=strict,
        dry_run=dry_run,
        stream=stream,
    )
    if code != 0:
        print(f"chain stopped: `prompt` exited {code}.", file=sys.stderr)
        return code

    branch, worktree, refusal = _locate_task_worktree(
        repo, workspace, phase, task, dry_run=dry_run
    )
    if refusal is not None:
        return refusal
    # The prompt is committed in the task worktree, so the non-dry scan runs there;
    # the dry run keeps the conventional path because it creates no worktree.
    prompt_root = repo.root if dry_run else worktree
    prompt_path = _resolved_task_prompt(prompt_root, phase, task, dry_run=dry_run)
    if prompt_path is None:
        print(
            f"chain stopped: no task prompt found for {phase}-{task} after `prompt`.",
            file=sys.stderr,
        )
        return 2

    return implement_workflow.run(
        task_prompt_path=prompt_path,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
        approve_all=approve_all,
        skip_gates=list(skip_gates or []),
        deny_gates=deny_gates,
        gate_default=gate_default,
        strict=strict,
        dry_run=dry_run,
        parallel=parallel,
        stream=stream,
    )


def review_and_fix(
    *,
    pr: int,
    repo: TargetRepo,
    aidt: ToolkitPaths,
    workspace: WorkspacePaths,
    approve_all: bool = False,
    skip_gates: list[str] | None = None,
    deny_gates: list[str] | None = None,
    gate_default: str | None = None,
    strict: bool = False,
    dry_run: bool = False,
    force_model: bool = False,
    max_iterations: int = fix_workflow.DEFAULT_MAX_ITERATIONS,
    stream: bool = False,
) -> int:
    code = review_workflow.run(
        pr=pr,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
        approve_all=approve_all,
        strict=strict,
        dry_run=dry_run,
        force_model=force_model,
        stream=stream,
    )
    if code != 0:
        print(f"chain stopped: `review` exited {code}.", file=sys.stderr)
        return code

    if review_published_followups(workspace.state_root / "runs", pr) is False:
        return _ended_because_nothing_was_published(pr)

    if GATE_FOLLOWUPS in set(skip_gates or []):
        print(
            f"chain:  `{GATE_FOLLOWUPS}` is in --skip-gates; the fix loop runs without "
            "the GitHub decision gate."
        )
    else:
        print(
            "human action: decide the published follow-up issues on GitHub before the fix "
            "loop; `fix`'s approve-followups gate fails closed unless it is approved."
        )
    return fix_workflow.run(
        pr=pr,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
        max_iterations=max_iterations,
        approve_all=approve_all,
        skip_gates=list(skip_gates or []),
        deny_gates=deny_gates,
        gate_default=gate_default,
        strict=strict,
        dry_run=dry_run,
        force_model=force_model,
        stream=stream,
    )


def prompt_to_fix(
    *,
    phase: str,
    epic: str,
    task: str,
    repo: TargetRepo,
    aidt: ToolkitPaths,
    workspace: WorkspacePaths,
    pr: int | None = None,
    approve_all: bool = False,
    skip_gates: list[str] | None = None,
    deny_gates: list[str] | None = None,
    gate_default: str | None = None,
    strict: bool = False,
    dry_run: bool = False,
    parallel: bool = False,
    force_model: bool = False,
    max_iterations: int = fix_workflow.DEFAULT_MAX_ITERATIONS,
    stream: bool = False,
) -> int:
    """Run the whole cycle: prompt → implement → review → approve-followups → fix.

    The stages are the four orchestrators in order, so each still owns its own
    preflight, gates, state and resumability. ``approve-followups`` is added to the
    ``fix`` stage's skip set (decision I1) so the GitHub decision gate does not stop an
    unattended chain; ``approve-implementation-pr`` and ``approve-fix-pr`` keep the
    caller's ``approve_all``/``gate_default`` behaviour, and ``--deny-gates
    approve-followups`` still refuses the auto-approval.
    """
    skip = list(skip_gates or [])

    code = prompt_workflow.run(
        phase=phase,
        epic=epic,
        task=task,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
        approve_all=approve_all,
        skip_gates=skip,
        deny_gates=deny_gates,
        gate_default=gate_default,
        strict=strict,
        dry_run=dry_run,
        stream=stream,
    )
    if code != 0:
        print(f"chain stopped: `prompt` exited {code}.", file=sys.stderr)
        return code

    branch, worktree, refusal = _locate_task_worktree(
        repo, workspace, phase, task, dry_run=dry_run
    )
    if refusal is not None:
        return refusal
    # The prompt is committed in the task worktree, so the non-dry scan runs there;
    # the dry run keeps the conventional path because it creates no worktree.
    prompt_root = repo.root if dry_run else worktree
    prompt_path = _resolved_task_prompt(prompt_root, phase, task, dry_run=dry_run)
    if prompt_path is None:
        print(
            f"chain stopped: no task prompt found for {phase}-{task} after `prompt`.",
            file=sys.stderr,
        )
        return 2

    code = implement_workflow.run(
        task_prompt_path=prompt_path,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
        approve_all=approve_all,
        skip_gates=skip,
        deny_gates=deny_gates,
        gate_default=gate_default,
        strict=strict,
        dry_run=dry_run,
        parallel=parallel,
        stream=stream,
    )
    if code != 0:
        print(f"chain stopped: `implement` exited {code}.", file=sys.stderr)
        return code

    if pr is not None:
        pr_number = pr
    elif dry_run:
        # A dry run opens no PR, so there is nothing to discover; the review/fix plans
        # are still printed and their run labels carry the placeholder.
        pr_number = 0
        print("pr:     (planned; --dry-run opens no PR)")
    else:
        pr_number = find_pr_number(workspace.state_root / "runs", branch)
        if pr_number is None:
            print(
                "chain stopped: no PR number recorded by `implement` on "
                f"`{branch}`; pass --pr <n>.",
                file=sys.stderr,
            )
            return 2
        print(f"pr:     #{pr_number}")

    code = review_workflow.run(
        pr=pr_number,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
        approve_all=approve_all,
        strict=strict,
        dry_run=dry_run,
        force_model=force_model,
        stream=stream,
    )
    if code != 0:
        print(f"chain stopped: `review` exited {code}.", file=sys.stderr)
        return code

    if review_published_followups(workspace.state_root / "runs", pr_number) is False:
        return _ended_because_nothing_was_published(pr_number)

    if GATE_FOLLOWUPS in set(deny_gates or []):
        print(
            f"note:   `{GATE_FOLLOWUPS}` is in --deny-gates; the fix loop will refuse "
            "the auto-approval and stop (exit 3)."
        )
    else:
        print(
            f"chain:  auto-approving `{GATE_FOLLOWUPS}` for the fix loop "
            f"(recorded as `--skip-gates {GATE_FOLLOWUPS}`); "
            "use --deny-gates to refuse it."
        )
        if GATE_FOLLOWUPS not in skip:
            skip.append(GATE_FOLLOWUPS)

    return fix_workflow.run(
        pr=pr_number,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
        max_iterations=max_iterations,
        approve_all=approve_all,
        skip_gates=skip,
        deny_gates=deny_gates,
        gate_default=gate_default,
        strict=strict,
        dry_run=dry_run,
        force_model=force_model,
        stream=stream,
    )
