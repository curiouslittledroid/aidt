"""``aidw fix`` — fix approved review follow-ups (design §8.4).

```
preflight (PR exists, targets main, the PR head's worktree is located)
  → list open children; show GitHub state
  ◇  approve-followups              runs /approve-review-followups (agent review-approver)
  ⟳  up to --fix-batch approved children (default 3) per iteration:
       → F1 fix-next-review-followup  (agent fixer, fresh, over the batch)
       → F2 test                      (agent tester, fresh, over the batch)
       → F3 code-review               (agent code-reviewer, fresh, over the batch)
       if F3 has findings:
         → F4 review-findings-to-github (ungated)  then ◇ approve-followups
       else:
         ◇ approve-fix-pr
     repeat until no approved child remains
  → I7 update-roadmap               (agent recorder, fresh)     once per run, if green
  → F5 commit-and-push              (agent pr-publisher, fresh)  once per run, and publishes
  → review_followup.py close        (Python, not an agent)       per recorded issue, after F5
```

Selection is always re-derived from ``review_followup.py select`` (never by counting), so
the loop is driven by real GitHub state: each iteration asks it for a **bounded batch**
(``--limit <fix_batch>``, default 3) and runs one F1, one F2 and one F3 over exactly the
children it returned — never ``len(closed_issues)`` or ``childrenInspected`` arithmetic.
``--max-iterations`` bounds the number of **iterations** (batches), never the total number
of fixes: a batch of 3 with ``--max-iterations 2`` can fix up to six children.

The approval round is deliberately **not** batched: it calls ``select`` without ``--limit``
and its summary reads the single ``selected`` object. The loop and the dry-run preview both
always pass the flag, so both read the payload through the same :func:`_selected_batch`
guard and accept only the array shape — the object-to-batch normalisation lives entirely in
``cmd_select``'s flag branch (req 2), never on this side.

Since H3.3 the run then ticks the task's roadmap checkbox **once**, after the loop converges
(design §8.4; H3.1's stage, H3.2's condition): the tick is the shared ``I7 update-roadmap``
stage from ``aidw.stage_registry`` — one id, one prompt, one agent and one name with
``implement`` — so the two ticks cannot drift. Three things are deliberate about *where* it
lives:

* the stage is a :attr:`~aidw.stage_registry.WorkflowDefinition.post_loop` entry, emitted
  only when a caller asks for the post-loop half. ``_planned_iteration`` calls
  ``plan_stages`` once per iteration and must never carry the tick (or ``F5``, which shares
  that half through :func:`_post_loop_specs`), or it would run — and dry-run print — once
  per iteration instead of once per run;
* the task id comes from the newest ``implement`` run's recorded ``state.task`` for the
  PR-head branch (``run.py:find_pr_number``'s re-read-the-run-state trade-off: no new ``gh``
  query, never the PR title), falling back to reversing ``repo.branch_pattern``. When neither
  yields exactly one roadmap entry the stage is **skipped with a reason** and the run still
  succeeds, because ``fix`` must keep working on PRs that are not AIDT tasks;
* the condition is this run's own evidence — ``select`` returned ``EXIT_NONE_AVAILABLE``,
  every ``iter{N}-test`` record succeeded, and the last re-review is ``Approve`` — evaluated
  by the workflow before ``run_stage``, never by the agent, and deliberately **not** a copy
  of ``implement``'s gate-outcome rule. A stopped loop (``--max-iterations``, a denied gate,
  an ambiguous verdict, a failed stage) records the same skip with the stop as its reason and
  leaves the roadmap byte-identical.

Since 05-P1.1 (design §17 Z9) a second post-loop stage follows the tick: ``F5
commit-and-push``. Before it, no stage of ``fix`` committed, so a run's fixes and its
roadmap tick stayed uncommitted in the PR-head worktree while its stages closed the
follow-up issues as ``Status: fixed`` — the work never reached the PR. ``F5`` is the
single owner of that write: the ``pr-publisher`` agent commits the accumulated change set
and pushes the PR-head branch, and this module only decides *whether* it may (D3's
four-case table) and verifies what landed (D6's head comparison). Python never commits and
never pushes.

Since 05-P1.2 (design §8.4, §17 Z9's close-after-push half) the **close is not the fixer's
job**. ``F1`` leaves every issue it fixed ``OPEN`` with the exact ``Status: in progress``
comment that ``start`` posted, and writes one closing comment body per issue to
``<run_dir>/artifacts/iter{N}/closing-body-{issue}.md`` — the absolute directory rendered
into the prompt as ``{closing_bodies}`` (05-B1.1: a per-iteration file could not say which
body belongs to which of the batch's issues, and a variable batch cannot carry N paths).
After the loop, and only once :func:`run_commit` has proved the push (`HEAD` moved,
`HEAD == origin/<branch>`, clean tree, ``state.pr["head_sha"]`` written), Python runs
``review_followup.py close --issue <n> --body-file <path>`` for each ``closed_issues`` entry
this run recorded. A non-zero ``close`` fails the run (exit 1) naming the PR, the branch and
the issue; an issue is therefore never reported fixed before its work reached the PR. The
close stays one issue per entry — never a batch: batching fixes is not a licence to batch
closes, where a half-failed call would strand an issue half-closed.

All GitHub writes are performed by AIDT's bundled prompts/scripts (the fixer and approver
agents, and — for the deferred close — this module, through the same script). AIDT only
reads: ``gh pr view`` and ``review_followup.py select``.

The run lock (``aidw.lock``, EXTRACTION.md §3.2/§3.10) is keyed on the **re-resolved
PR-head worktree**, acquired immediately before ``create_run`` and released on every exit
path; a live peer in that worktree is refused (exit 4) before any run state is written.
``_latest_fix_run`` stays branch-keyed and is *not* the lock: it is the `--resume` path
for a crashed run, which ``flock`` has already released.
"""

from __future__ import annotations

import json
import string
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from aidw import __version__, findings as findings_mod
from aidw import git, github, lock, roadmap, stage_registry
from aidw.config import ERROR, WARNING, Issue, format_issues, load_all
from aidw.gates import decide
from aidw.log import NullLogger, RunLogger
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.report import empty_final_message_error, print_stage
from aidw.runner import (
    StageSpec,
    declared_stage_issues,
    plan_stages,
    record_skipped,
    run_stage,
)
from aidw.state import (
    BLOCKED,
    FAILED,
    RUNNING,
    SUCCEEDED,
    GateRecord,
    RunState,
    StageRecord,
    create_run,
    list_runs,
    PLANNED_RUN_DIR_TEXT,
    planned_run,
    run_dir,
    save,
    utcnow_iso,
)
from aidw.target_config import (
    SOURCE_CONFIG,
    ResolvedConfig,
    agent_configs_override,
    config_identity,
    resolve_workflow_config,
)
from aidw.verdict import APPROVE, BLOCKED as VERDICT_BLOCKED, parse_verdict
from aidw.workflows.implement import (
    TICK_STAGE_NAME,
    settle_roadmap_tick,
    worktree_add_command,
)

GATE_FOLLOWUPS = "approve-followups"
GATE_FIX_PR = "approve-fix-pr"
DEFAULT_MAX_ITERATIONS = 10

#: The default batch width of one fix iteration (05-B1.1, design §8.4): how many approved
#: child issues one ``F1`` fixes, and how many one ``F2``/``F3`` pair then judges. Bounded on
#: purpose — an unbounded batch would turn one bad fix into a whole unreviewable change set,
#: and the roadmap's default is three.
DEFAULT_FIX_BATCH = 3

#: Why a ``select`` read under ``--limit`` is refused (05-B1.1 reqs 2/3, design §8.4):
#: ``--limit`` is always passed — by the loop **and** by the dry-run preview — so ``selected``
#: must be the array shape. One wording for both readers because it is one rule: an object
#: here means the batch contract was not honoured, and acting on a one-child batch would
#: silently restore the one-fix-per-iteration behaviour this task reverses.
SELECT_NOT_A_BATCH = (
    "select did not return a batch of children with issue numbers (`--limit` is always "
    "passed, by the loop and the dry-run preview); failing closed instead of acting on a "
    "subset."
)

#: The runtime name of ``F5`` (``stage_registry``'s ``_COMMIT_PUSH_STAGE``). The workflow
#: keys on the *name* — the same rule ``implement.TICK_STAGE_NAME`` follows — because
#: ``state.json`` and the stage block are name-keyed (R6).
COMMIT_STAGE_NAME = "commit-and-push"

#: The two ``state.pr`` fields the post-loop tick records (H3.3 req 6). ``roadmap_ticked``
#: is the roadmap's own name; the skip reason's key is prompt-fixed here because the roadmap
#: fixes only ``roadmap_ticked``. A ``True`` means the tick was **run** and verified
#: (``flipped`` or the already-``[x]`` no-op); ``False`` pairs with the reason, whether the
#: stage was withheld (req 4's non-green skip) or its postcondition failed.
PR_ROADMAP_TICKED = "roadmap_ticked"
PR_ROADMAP_TICK_SKIP_REASON = "roadmap_tick_skip_reason"

#: Why a stopped loop's tick was withheld (H3.3 req 4(a)): ``{stop}`` names the exit, so a
#: ``--max-iterations`` run, a denied gate and a failed stage each say why they ticked
#: nothing. ``select`` never returned ``EXIT_NONE_AVAILABLE``, so the loop did not converge.
STOP_REASON = (
    "fix stopped before the loop converged ({stop}), so the roadmap tick was withheld"
)

#: The ``state.pr`` fields ``F5`` records (05-P1.1, decisions D6/D7). ``head_sha`` is the
#: **verified remote** SHA — ``origin/<branch>`` at verification time, written only when the
#: head comparison holds — so its presence *is* the "committed and pushed" boolean; there is
#: deliberately no second ``committed``/``pushed`` flag. A skip writes the reason instead,
#: mirroring H3.3's ``roadmap_tick_skip_reason``.
PR_HEAD_SHA = "head_sha"
PR_COMMIT_SKIP_REASON = "commit_skip_reason"

#: The three things D3's table can decide. ``commit`` is the only one that runs the stage.
COMMIT_ACTION_COMMIT = "commit"
COMMIT_ACTION_SKIP = "skip"
COMMIT_ACTION_FAIL = "fail"

#: D3 case 2: a dirty tree with nothing closed this run. The dirt is real but **unowned** —
#: nothing records which paths a fixer touched, so publishing it would publish somebody
#: else's work (design §13 preserves unrelated user changes).
COMMIT_SKIP_DIRTY_UNOWNED = (
    "this run closed no issue; the working-tree changes are not this run's"
)

#: D3 case 3: the roadmap's successful no-op — nothing closed, nothing to publish. No empty
#: commit, no push.
COMMIT_SKIP_CLEAN_NOOP = (
    "this run closed no issue and the working tree is clean, so there is nothing to commit"
)

#: D3 case 4: issues were closed but there is nothing to push — exactly the untruthful
#: state this epic removes, so it fails closed (P1.2's close-after-push ordering makes it
#: unrepresentable later).
COMMIT_FAIL_NOTHING_TO_PUSH = (
    "this run closed {closed} issue(s) but the working tree is clean, so there is nothing "
    "to push"
)

#: The loop's re-test stage names (``iter1-test``, ``iter2-test``) — H3.3 req 4(b)'s
#: "every ``iter{N}-test`` stage record is ``SUCCEEDED``". Derived from the registry's
#: template rather than a second spelling of it.
_TEST_STAGE_PREFIX = "iter"
_TEST_STAGE_SUFFIX = "-test"

#: Why a recorded close never ran: this run recorded at least one fixed issue, but no
#: verified push followed (05-P1.2 req 5). It is defence in depth — D3's table already
#: fails clean-with-closed and skips only when nothing was closed — and it is the guard that
#: makes "reported fixed without a push" unrepresentable rather than merely unlikely.
CLOSE_FAIL_NO_VERIFIED_PUSH = (
    "the run recorded this issue as fixed, but no commit-and-push verified a push, so it "
    "stays open"
)


def is_test_stage(name: str) -> bool:
    """Whether ``name`` is the fix loop's re-test stage (``iter{N}-test``).

    Pure. The shape is the registry's (``_FIX``'s ``F2`` name template), so this reads the
    same vocabulary the plan uses instead of matching a hand-written regex. It is
    deliberately anchored on **both** ends: ``iter1-test`` matches, ``iter1-test-extra`` and
    ``round1-approve-review-followups`` do not.
    """
    if not name.startswith(_TEST_STAGE_PREFIX) or not name.endswith(_TEST_STAGE_SUFFIX):
        return False
    digits = name[len(_TEST_STAGE_PREFIX) : -len(_TEST_STAGE_SUFFIX)]
    return digits.isdigit() and digits.isascii()


@dataclass(frozen=True)
class FixTickEvidence:
    """The verdict on ``fix``'s ``WHEN_EVIDENCE_GREEN`` condition (H3.3 req 4).

    ``reason`` is the human-readable explanation carried by a skipped stage; it is empty
    exactly when ``green`` is true, so a green verdict can never be paired with a reason
    somebody might print as one.
    """

    green: bool
    reason: str


def tick_evidence(
    *,
    loop_closed: bool,
    test_records: Sequence[StageRecord],
    latest_verdict: str | None,
) -> FixTickEvidence:
    """**The rule**: is the loop's outcome green enough to claim the task is done?

    ``fix``'s own three conditions (H3.3 req 4) — deliberately not ``implement``'s
    gate-outcome rule (H3.2), which asks whether the tree's recorded gates passed. Here the
    evidence is the loop's convergence itself, read from this run:

    (a) ``loop_closed`` — the loop ended because ``review_followup.py select`` returned
        ``EXIT_NONE_AVAILABLE``. ``--max-iterations``, a denied gate and an ambiguous or
        ``Blocked`` verdict all stop the run before that and have already returned 3/1, so
        the tick is never planned for them;
    (b) every ``iter{N}-test`` record is ``SUCCEEDED`` — a red re-test is a fix that did not
        land, and nothing in the chain can untick;
    (c) ``latest_verdict == Approve`` — the last re-review approved the work. An **empty**
        run (the first ``select`` already returned ``EXIT_NONE_AVAILABLE``) has
        ``latest_verdict is None`` and is therefore **not** green: a run that closed
        nothing must not claim the task done.

    Pure: no I/O, no mutation of ``test_records``, and the result is a frozen value.
    """
    if not loop_closed:
        return FixTickEvidence(
            False,
            STOP_REASON.format(
                stop="the loop did not end on `select` exit EXIT_NONE_AVAILABLE"
            ),
        )
    failing = [record for record in test_records if record.status != SUCCEEDED]
    if failing:
        names = ", ".join(record.name for record in failing)
        return FixTickEvidence(
            False, f"this run's re-test did not succeed ({names}), so the fix has no green evidence"
        )
    if latest_verdict is None:
        return FixTickEvidence(
            False,
            "no re-review verdict is recorded (the first `select` already found no available "
            "follow-up), so this run closed nothing to tick",
        )
    if latest_verdict != APPROVE:
        return FixTickEvidence(
            False, f"the last re-review verdict is `{latest_verdict}`, not `Approve`"
        )
    return FixTickEvidence(True, "")


@dataclass(frozen=True)
class CommitDecision:
    """What ``F5`` may do with this run's tree and its closed-issue list (decision D3).

    ``action`` is one of :data:`COMMIT_ACTION_COMMIT` / :data:`COMMIT_ACTION_SKIP` /
    :data:`COMMIT_ACTION_FAIL`; ``reason`` is the human-readable explanation a skip records
    (``state.pr[PR_COMMIT_SKIP_REASON]`` and the skipped stage's ``artifacts``) or a failure
    prints. It is empty exactly on ``commit``, so a decision that runs the stage can never
    carry a reason somebody might print as one.
    """

    action: str
    reason: str = ""


def commit_decision(
    *, tree_dirty: bool, closed_issues: Sequence[Mapping[str, Any]]
) -> CommitDecision:
    """**The rule** (decision D3): may ``F5`` publish this run's tree?

    ``closed_issues`` is this run's **own** accumulated list (the loop's ``closed_issues``),
    never a ``gh`` query and never a count of ``Status: fixed`` comments — so "this run
    closed nothing" and "somebody else closed something" cannot be confused. ``tree_dirty``
    is the worktree state *before* the stage runs, i.e. after the tick has flipped (the tick
    is part of the change set ``F5`` commits).

    | tree | ``closed_issues`` | decision |
    |---|---|---|
    | dirty | >= 1 | commit (the fix edits plus the tick if it flipped) |
    | dirty | 0 | skip — unowned dirt is not this run's to publish (design §13) |
    | clean | 0 | skip — the roadmap's successful no-op, no empty commit |
    | clean | >= 1 | **fail closed** — issues were closed and there is nothing to push |

    Pure: no I/O, no mutation of ``closed_issues``, and the result is a frozen value.
    """
    closed = len(closed_issues)
    if not closed:
        return CommitDecision(
            COMMIT_ACTION_SKIP,
            COMMIT_SKIP_DIRTY_UNOWNED if tree_dirty else COMMIT_SKIP_CLEAN_NOOP,
        )
    if not tree_dirty:
        return CommitDecision(
            COMMIT_ACTION_FAIL, COMMIT_FAIL_NOTHING_TO_PUSH.format(closed=closed)
        )
    return CommitDecision(COMMIT_ACTION_COMMIT)


def closing_bodies_dir(directory: Path, iteration: int) -> Path:
    """The **absolute** directory ``F1`` writes this iteration's closing bodies into.

    This is the value rendered into the prompt as ``{closing_bodies}`` (05-B1.1 req 5): one
    directory per iteration, inside the run directory — never a ``mktemp`` directory and
    never relative. Absolute for the same reason ``_planned_iteration`` passes an absolute
    ``manifest_path``: ``F1`` runs with the target repo as its cwd, so a relative path would
    write the bodies into the repo tree and pollute the very diff ``F5`` pushes. It is run
    state (design §9.1), so it lives with the run, not in the worktree.
    """
    return Path(directory) / "artifacts" / f"iter{iteration}"


def closing_body_path(directory: Path, iteration: int, issue_number: int) -> Path:
    """The **absolute** per-issue body path ``F1`` writes for one child (05-B1.1 req 5).

    ``<run_dir>/artifacts/iter{N}/closing-body-{issue}.md``: the directory is
    :func:`closing_bodies_dir`, and the filename names the issue so each ``closed_issues``
    entry can record its own body and the deferred close can pass it back as
    ``--body-file``. A per-iteration body could not say which of a batch's fixes it
    describes. Pure: the path is derived, never created.
    """
    return closing_bodies_dir(directory, iteration) / f"closing-body-{issue_number}.md"


def close_failure_message(
    pr: int, branch: str | None, issue: Any, detail: str
) -> str:
    """The one shape of a deferred-close failure: PR, branch **and** issue (P1.2 req 3).

    An operator reading stderr must know which issue is in an untruthful state — recorded as
    fixed, still open — so the issue number is part of the message rather than left to the
    surrounding output. Pure.
    """
    return (
        "close failed for PR #{pr} on branch `{branch}`: issue #{issue} — {detail}"
    ).format(pr=pr, branch=branch or "(unresolved)", issue=issue, detail=detail)


def run_close(
    entry: Mapping[str, Any],
    *,
    aidt: Path,
    repo: Path,
    pr: int,
    config: ResolvedConfig,
) -> github.ScriptResult:
    """Run the bundled ``review_followup.py close`` for one recorded issue (req 2/req 3).

    ``entry`` is one of this run's own ``closed_issues`` records: it carries the issue
    ``number`` and the absolute ``closing_body`` path ``F1`` wrote for **that** issue. The
    script posts the exact ``Status: fixed`` comment if it is absent and closes the issue
    with that body; its guards (labels, refuse-to-reopen, a body that repeats the status
    marker) run again here, so a bad body fails the close before any close action.
    """
    script = github.script_path(aidt, github.FOLLOWUP_SCRIPT)
    argv = github.build_followup_argv(
        script,
        "close",
        pr,
        issue=entry.get("number"),
        body_file=entry.get("closing_body"),
    )
    return github.run_script(argv, repo, config=config)


def commit_failure_message(pr: int, branch: str | None, detail: str) -> str:
    """The one shape of an ``F5`` failure: it names the PR and the branch (req 5/req 6).

    Requirement 5 is explicit that a failure must never surface as a raw exception or a bare
    ``git`` message: an operator reading stderr has to know which PR and which branch are in
    an untruthful state. Pure.
    """
    return "commit-and-push failed for PR #{pr} on branch `{branch}`: {detail}".format(
        pr=pr, branch=branch or "(unresolved)", detail=detail
    )


def reverse_branch_pattern(branch: str, pattern: str) -> list[tuple[str, str]]:
    """Every ``(phase, task)`` split that reproduces ``branch`` under ``pattern``.

    ``repo.branch_pattern`` is a ``str.format`` template, so there is no split to take: the
    pattern's own literal/field structure is what has to be matched. This walks
    ``string.Formatter().parse``'s parts — each literal ``startswith``-matched, each field a
    **non-empty** capture over every possible length — and **enumerates** every viable split
    instead of returning a single regex match (H3.3 req 3's prompt-fixed rule). That matters
    because under ``{phase}-{task}`` the branch ``03-H3-3`` splits two ways (``03``/``H3-3``
    and ``03-H3``/``3``), and a single greedy or lazy match would silently pick one; the
    caller requires **exactly one** viable split before it resolves a roadmap entry, so an
    ambiguous branch falls through to the skip instead of ticking a guess.

    Returns ``[]`` when the pattern is malformed (unbalanced braces, a field other than
    ``phase``/``task``, a field repeated, or a format spec/conversion) or when nothing
    matches; the branch is matched anchored on both ends. Pure: no I/O, no mutation.
    """
    try:
        parts = list(string.Formatter().parse(pattern))
    except ValueError:
        return []
    fields = [field for _literal, field, _spec, _conv in parts if field is not None]
    # Exactly `{phase}` and `{task}`, once each, with no format spec/conversion: the same
    # shape `implement.derive_branch_name` requires to apply the pattern.
    if sorted(fields) != ["phase", "task"]:
        return []
    if any(spec or conv for _l, field, spec, conv in parts if field is not None):
        return []

    splits: list[tuple[str, str]] = []

    def walk(index: int, position: int, captured: dict[str, str]) -> None:
        if index == len(parts):
            if position == len(branch) and len(captured) == 2:
                splits.append((captured["phase"], captured["task"]))
            return
        literal, field, _spec, _conversion = parts[index]
        if literal:
            if not branch.startswith(literal, position):
                return
            position += len(literal)
        if field is None:
            walk(index + 1, position, captured)
            return
        for end in range(position + 1, len(branch) + 1):
            walk(index + 1, end, {**captured, field: branch[position:end]})

    walk(0, 0, {})
    return splits


@dataclass(frozen=True)
class RoadmapTarget:
    """The roadmap entry a ``fix`` run would tick, or why it has none (H3.3 req 3).

    ``roadmap_file`` is the entry's **absolute** path (``roadmap.entry_path``), the file the
    stage is told to edit and the file the postcondition re-reads. It is ``None`` exactly
    when ``reason`` is non-empty: a run whose branch maps to no single roadmap entry skips
    the tick with that reason and still succeeds.
    """

    phase: str = ""
    task: str = ""
    roadmap_file: Path | None = None
    source: str = ""
    reason: str = ""


def _recorded_task_identity(
    runs_root: Path, branch: str | None
) -> tuple[str, str] | None:
    """The ``(phase, task)`` the newest ``implement`` run recorded for ``branch``.

    ``implement`` records ``state.task = {phase, task, prompt_path}`` at ``create_run``;
    this re-reads that instead of asking ``gh`` or parsing the PR title — the same trade-off
    ``run.py:find_pr_number`` makes for the PR number (H3.3 req 3). Newest wins, so a re-run
    on the same branch supersedes an older record; a run with no ``branch`` recorded (a
    ``--dry-run``) or no usable ``state.task`` is skipped over.
    """
    if not branch:
        return None
    matches = [
        state
        for state in list_runs(runs_root)
        if state.workflow == "implement" and state.git.get("branch") == branch
    ]
    # Only the newest implement run is authoritative.  If it has no usable task (for
    # example a dry-run or an older run recorded before task metadata was added), fall
    # through to the branch-pattern resolver rather than resurrecting an older task.
    state = matches[-1] if matches else None
    if state is not None:
        recorded = state.task if isinstance(state.task, dict) else {}
        phase = recorded.get("phase")
        task = recorded.get("task")
        if isinstance(phase, str) and phase and isinstance(task, str) and task:
            return phase, task
    return None


def resolve_roadmap_target(
    *,
    runs_root: Path,
    branch: str | None,
    branch_pattern: str,
    repo_root: Path,
    config: ResolvedConfig,
) -> RoadmapTarget:
    """Resolve the one roadmap entry this run would tick, from the PR-head worktree.

    Two sources, in order (H3.3 req 3): the newest ``implement`` run's recorded
    ``state.task`` for ``branch``, then the **unique** viable ``(phase, task)`` split of
    ``branch`` under ``repo.branch_pattern`` (:func:`reverse_branch_pattern`). Zero or
    several viable splits is a skip, never a guess.

    The roadmap is read from ``repo_root`` (the located PR-head worktree, design K1) with the
    resolved ``paths.roadmap_dir``/``paths.roadmap_glob`` — the same two values and the same
    ``roadmap.load_tasks`` + ``roadmap.tick_entry`` call ``implement.run`` makes, so a
    duplicate ``(phase, task)`` refuses here exactly as it does there. Every failure is a
    ``RoadmapTarget`` with a ``reason``, never an exception: ``fix`` must keep working on
    PRs that are not AIDT tasks.
    """
    recorded = _recorded_task_identity(runs_root, branch)
    if recorded is not None:
        phase, task = recorded
        source = "the newest `implement` run's state.task"
    else:
        candidates = reverse_branch_pattern(branch or "", branch_pattern)
        if len(candidates) != 1:
            named = f"`{branch}`" if branch else "no branch"
            return RoadmapTarget(
                reason=(
                    f"no task id: no `implement` run records one for {named}, and "
                    f"`{branch_pattern}` admits {len(candidates)} viable `(phase, task)` "
                    f"split(s) of the branch name; exactly one is required"
                )
            )
        phase, task = candidates[0]
        source = f"the branch name reversed through `{branch_pattern}`"

    roadmap_root = (Path(repo_root) / str(config["paths.roadmap_dir"].value)).resolve()
    try:
        entry = roadmap.tick_entry(
            roadmap.load_tasks(
                roadmap_root, str(config["paths.roadmap_glob"].value)
            ),
            phase=phase,
            task=task,
        )
    except roadmap.RoadmapTickError as exc:
        return RoadmapTarget(
            phase=phase,
            task=task,
            source=source,
            reason=f"no single roadmap entry to tick: {exc}",
        )
    return RoadmapTarget(
        phase=phase,
        task=task,
        roadmap_file=roadmap.entry_path(roadmap_root, entry),
        source=source,
    )


def _post_loop_specs(
    *,
    target: RoadmapTarget,
    pr: int,
    round_index: int,
    iteration: int,
    config: ResolvedConfig,
    aidt: Path,
    repo: Path,
    directory: Path,
    fix_batch: int = DEFAULT_FIX_BATCH,
) -> dict[str, StageSpec]:
    """The post-loop half as runnable specs, keyed by stage name — **one** planning call.

    ``include_post_loop`` is what keeps ``I7`` and ``F5`` out of ``_planned_iteration``'s
    per-iteration plan: the same ``plan_stages`` call produces them only here, so a run
    plans (and a dry run prints) each of them exactly once, after the loop. One call for
    both stages rather than one per stage keeps their variables, order and any declared
    override in a single place (05-P1.1 req 2).

    An unresolved target renders empty roadmap values, which is honest for the tick: in
    that case it is only ever **recorded as skipped** — the record needs the stage's name
    and agent, not its variables. ``F5`` renders nothing but ``{pr}``.

    ``round_index``/``iteration`` are the loop's current position for a converged run; the
    skip paths pass ``1``/``1``, because neither stage carries those variables.
    """
    planned = plan_stages(
        "fix",
        config=config,
        toolkit_root=aidt,
        target_root=repo,
        pr=pr,
        round_index=round_index,
        iteration=iteration,
        manifest_path=str(directory / f"artifacts/iter{iteration}-review-manifest.json"),
        closing_bodies=str(closing_bodies_dir(directory, iteration)),
        # 05-B1.1: the run's own `--fix-batch` width. It rides the plan even though this
        # call's F1 stage is discarded (`I7`/`F5` are all the caller runs), because the
        # registry renders F1's variables here too — an omitted field would raise rather
        # than quietly plan a wrong width.
        fix_batch=str(fix_batch),
        include_post_loop=True,
        roadmap_file=str(target.roadmap_file) if target.roadmap_file else "",
        checkbox_id=target.task,
    )
    specs = {spec.name: spec for spec in planned}
    missing = [
        name for name in (TICK_STAGE_NAME, COMMIT_STAGE_NAME) if name not in specs
    ]
    if missing:  # pragma: no cover - the preflight refuses a list without a core id
        raise AssertionError(
            "the `fix` plan carries no post-loop stage(s) "
            f"{', '.join('`' + name + '`' for name in missing)}; a declared "
            "`workflows.fix.stages` list must include `I7` and `F5`"
        )
    return specs


def _planned_iteration(
    *,
    pr: int,
    round_index: int,
    iteration: int,
    config: ResolvedConfig,
    aidt: Path,
    repo: Path,
    directory: Path,
    fix_batch: int = DEFAULT_FIX_BATCH,
) -> dict[str, StageSpec]:
    """One fix iteration's stage specs from the registry, keyed by stage name (E4.3).

    The iteration count and the round index are external GitHub state, so the loop expands
    the iteration it is about to run rather than a pre-built list (EXTRACTION.md §3.5,
    design §8.4). ``manifest_path`` is that iteration's real-run manifest path in the run
    directory ``directory`` — the value the registry renders into F4's pointer — so the dry
    run and a real run plan the same ``extra``. It is absolute for the same reason
    ``review.py`` passes an absolute path: F4 runs with the target repo as its cwd.
    ``closing_bodies`` is F1's counterpart (05-P1.2 req 4, widened per issue by 05-B1.1):
    the absolute directory the fixer writes one closing comment body per issue into, and the
    close step reads one file per entry back after the push (:func:`closing_body_path`).
    ``fix_batch`` is the run's resolved width: F1 renders it as its third positional
    variable so the agent's own `select --limit` asks for exactly the bound Python selected
    with (05-B1.1; nothing exports that value to the stage environment).

    Deliberately **no** ``include_post_loop``: this is the per-iteration expansion, and the
    roadmap tick and ``F5`` run once per run, after the loop (H3.3 req 1/req 7; 05-P1.1
    req 2). :func:`_post_loop_specs` is the one caller that asks for the post-loop half.
    """
    planned = plan_stages(
        "fix",
        config=config,
        toolkit_root=aidt,
        target_root=repo,
        pr=pr,
        round_index=round_index,
        iteration=iteration,
        manifest_path=str(directory / f"artifacts/iter{iteration}-review-manifest.json"),
        closing_bodies=str(closing_bodies_dir(directory, iteration)),
        fix_batch=str(fix_batch),
    )
    return {spec.name: spec for spec in planned}


def _read_out(record) -> str | None:
    out = record.artifacts.get("out")
    if out and Path(out).is_file():
        return Path(out).read_text(encoding="utf-8")
    return None


def _latest_fix_run(runs_root: Path, branch: str) -> RunState | None:
    matches = [
        state
        for state in list_runs(runs_root)
        if state.workflow == "fix" and state.git.get("branch") == branch
    ]
    return matches[-1] if matches else None


def _filter_force_model(warnings: list[Issue]) -> list[Issue]:
    """The warnings ``--force-model`` overrides (design §5 independence check).

    ``reviewer != author`` is emitted by ``check_independence`` from inside
    ``load_all`` and ``differs from the fixer`` by the reviewer-rotation preflight;
    ``--force-model`` accepts the model coincidence, so neither may fail a strict
    run. Both the control-root preflight and the reloaded PR-head worktree check
    must apply this: they load the same toolkit agent configs, so the warning is
    identical in both (issue #58).
    """
    return [
        w
        for w in warnings
        if "reviewer != author" not in w.message and "differs from the fixer" not in w.message
    ]


def _selected_batch(payload: Mapping[str, Any]) -> list[dict] | None:
    """``select``'s array-shaped ``selected``, or ``None`` when it is not a batch.

    The **one** fail-closed read of a ``select --limit`` payload (05-B1.1 reqs 2/3, design
    §8.4), shared by the loop and the dry-run preview so the two cannot disagree about the
    same malformed result. ``--limit`` is always passed by both, so ``selected`` must be a
    non-empty array whose entries each carry an integer ``number`` and a ``title``. Anything
    else — the old single object, an empty array on exit 0, a child without a usable issue
    number — is ``None``, never ``[payload]`` or ``[batch[0]]``: coercing it would silently
    fix (or preview) a one-child batch, and deriving a width from ``childrenInspected`` is
    the count arithmetic §8.4 forbids. Pure.
    """
    batch = payload.get("selected")
    if (
        not isinstance(batch, list)
        or not batch
        or not all(
            isinstance(child, dict)
            and isinstance(child.get("number"), int)
            and child.get("title")
            for child in batch
        )
    ):
        return None
    return batch


def _followup_summary(selection: github.ScriptResult, round_index: int) -> str:
    payload = github.parse_json_output(selection.stdout) or {}
    selected = payload.get("selected") or {}
    lines = [f"Review follow-ups for this PR (round {round_index})"]
    if selected:
        lines.append(
            f"  next approved child: #{selected.get('number')} "
            f"{selected.get('title')} ({selected.get('priority')})"
        )
    else:
        lines.append("  no available approved child yet")
    lines.append(
        f"  children inspected: {payload.get('childrenInspected', '?')} "
        f"of {payload.get('totalChildren', '?')}"
    )
    for skipped in list(payload.get("skipped", []))[:10]:
        lines.append(
            f"  skip #{skipped.get('number')} [{skipped.get('reason')}] "
            f"{skipped.get('title')}"
        )
    lines.append("")
    lines.append(
        "Approving runs /approve-review-followups, which applies the GitHub decisions "
        "to every open child (`approve-fix`, removes `decision-pending`)."
    )
    return "\n".join(lines)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _approval_round(
    round_index: int,
    *,
    pr: int,
    repo: Path,
    aidt: Path,
    agents: dict,
    state: RunState,
    logger: RunLogger,
    directory: Path,
    runs_root: Path,
    config: ResolvedConfig,
    approve_all: bool,
    skip: set[str],
    deny: set[str] | None = None,
    gate_default: str | None = None,
    fix_batch: int = DEFAULT_FIX_BATCH,
) -> int | None:
    """Gate ``approve-followups`` and, on approval, run the approver agent.

    The A1 stage itself comes from the registry through :func:`plan_stages` (E4.3): its
    name carries the round index, which is the only part that varies per approval round, so
    the plan is asked for ``iteration=1`` and only its A1 entry is used.
    """
    planned = _planned_iteration(
        pr=pr,
        round_index=round_index,
        iteration=1,
        config=config,
        aidt=aidt,
        repo=repo,
        directory=directory,
        fix_batch=fix_batch,
    )
    spec = planned[f"round{round_index}-approve-review-followups"]
    name = spec.name
    selection = github.select_followups(aidt, repo, pr, config=config)
    outcome = decide(
        GATE_FOLLOWUPS,
        _followup_summary(selection, round_index),
        approve_all=approve_all,
        skip=skip,
        deny=deny,
        gate_default=gate_default,
    )
    state.record_gate(
        GateRecord(
            name=GATE_FOLLOWUPS,
            decision=outcome.decision,
            mechanism=outcome.mechanism,
            at=utcnow_iso(),
            detail=f"round={round_index}",
        )
    )
    save(directory, state)
    print(f"gate:   {GATE_FOLLOWUPS} [{outcome.mechanism}]")
    if not outcome.approved:
        print(
            f"gate {GATE_FOLLOWUPS} denied ({outcome.mechanism}); stopping.",
            file=sys.stderr,
        )
        return 3

    record = run_stage(
        # The approval postcondition is workflow-side, not stage data (E4.3 req 5): the
        # registry knows the stage, only this workflow knows how to verify the approvals.
        replace(
            spec,
            verify=lambda: github.verify_approvals(aidt, repo, pr, config=config),
        ),
        repo_root=repo,
        toolkit_root=aidt,
        runs_root=runs_root,
        state=state,
        logger=logger,
        agents=agents,
        config=config,
    )
    print_stage(record, repo_root=repo)
    if record.status != SUCCEEDED:
        print(f"stage {name} failed: {record.error}", file=sys.stderr)
        return 1
    return None


def run(
    *,
    pr: int,
    repo: TargetRepo,
    aidt: ToolkitPaths,
    workspace: WorkspacePaths,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    fix_batch: int = DEFAULT_FIX_BATCH,
    approve_all: bool = False,
    skip_gates: list[str] | None = None,
    deny_gates: list[str] | None = None,
    gate_default: str | None = None,
    strict: bool = False,
    dry_run: bool = False,
    force_model: bool = False,
    stream: bool = False,
) -> int:
    skip = set(skip_gates or [])
    deny = set(deny_gates or [])
    runs_root = workspace.state_root / "runs"

    # Target config (E4.3, EXTRACTION.md §3.4/§3.11): `aidw prompt`'s two fail-closed
    # refusals — validation ERRORs and `check_compatibility` — stderr + exit 2 before any
    # run record or worktree, `--dry-run` included. `validate_paths` stays prompt-only.
    resolved_config, config_issues = resolve_workflow_config(
        repo.root, toolkit_version=__version__
    )
    if config_issues:
        print(format_issues(config_issues), file=sys.stderr)
        return 2

    # --- core vs repo-optional stages (E4.5a, D12/D13, EXTRACTION.md §3.5) ------ #
    # Only a *declared* `workflows.fix.stages` list is validated: it replaces the
    # toolkit's list wholesale (§3.4), so a missing core id is a removal. Declared-ness
    # (`source == "config"`) is the test — an undeclared list is absent from the resolved
    # config and the registry defaults plan unchanged, while an explicit `stages: []`
    # must report every core stage removed. Runs immediately after the config refusal,
    # before `load_all`, any run record/worktree, and in `--dry-run`: stderr + exit 2, the
    # same contract as every other config refusal.
    stages_entry = resolved_config.get("workflows.fix.stages")
    if stages_entry is not None and stages_entry.source == SOURCE_CONFIG:
        stage_issues = stage_registry.validate_stage_list(
            "fix", stages_entry.value or []
        )
        if stage_issues:
            print(format_issues(stage_issues), file=sys.stderr)
            return 2

    # E4.6: a declared `paths.agent_configs_dir` shadows the toolkit's agent configs by
    # id; unset passes `None` (toolkit defaults). Re-resolved against the PR-head
    # worktree below, the tree the fix stages actually run in.
    agents, issues = load_all(
        aidt.root,
        repo.root,
        override_dir=agent_configs_override(resolved_config, repo.root),
    )
    errors = [i for i in issues if i.level == ERROR]
    warnings = [i for i in issues if i.level == WARNING]
    if force_model:
        # The rotation warning below is appended *after* this filter: it reports the
        # workflow's own re-review pairing, not a configured reviewer/author pair,
        # so ``--force-model`` deliberately does not override it.
        warnings = _filter_force_model(warnings)

    # Reviewer rotation: the re-review must not run on the fixer's model.
    if all(aid in agents for aid in ("fixer", "tester", "code-reviewer")):
        fixer_model = agents["fixer"].qualified_model
        reviewers = {
            agents["tester"].qualified_model,
            agents["code-reviewer"].qualified_model,
        }
        if not (reviewers - {fixer_model}):
            warnings.append(
                Issue(
                    WARNING,
                    "fix",
                    f"no reviewer model differs from the fixer model "
                    f"({fixer_model}); the re-review would judge its own author",
                )
            )

    if errors or (strict and warnings):
        print(format_issues(errors + (warnings if strict else [])), file=sys.stderr)
        return 2

    # --- declared stage settings (E4.5b, EXTRACTION.md §3.5/§3.6) --------------- #
    # After `load_all` (and its refusal), because the agents dict is what a repo-added
    # stage's `agent` is checked against — the validator above runs before it.
    # `validate_stage_list` stays the first stage-list refusal; this one covers the two
    # settings a plan needs and turns them into config ERRORs (stderr + exit 2) before any
    # run record or worktree, so a missing declared prompt or an unknown repo-added agent
    # never escapes `run()` as a traceback. Control-root only: the reloaded-agents refusal
    # in the worktree branch keeps its own `load_all` check and, like `validate_stage_list`,
    # is not re-run — this workflow runs no repo-added stage (its consumer is name-keyed,
    # E4.5b's non-goal), but the declaration is still checked and warned about, never a
    # silent drop.
    if stages_entry is not None and stages_entry.source == SOURCE_CONFIG:
        declaration_issues = declared_stage_issues(
            "fix",
            stages_entry.value or [],
            toolkit_root=aidt.root,
            target_root=repo.root,
            agents=agents,
        )
        if declaration_issues:
            print(format_issues(declaration_issues), file=sys.stderr)
            return 2

    # --- preflight: gh, PR exists, targets main (design §8.4) ---------------- #
    # ``gh`` missing and a missing PR are read failures: the refusals stay real-run
    # only, but the ``pr_view`` read itself runs in dry-run too (E2.6 req 6), so the PR
    # head resolves in both modes and ``git.current_branch`` is gone entirely.
    pr_info: dict = {}
    branch: str | None = None
    worktree: Path | None = None

    if not dry_run and not github.gh_available():
        print("`gh` was not found on PATH.", file=sys.stderr)
        return 4

    view = github.pr_view(repo.root, pr) if github.gh_available() else None

    if not dry_run:
        if view is None:
            print(f"PR #{pr} was not found (or `gh` failed).", file=sys.stderr)
            return 2
        if view.get("baseRefName") != "main":
            print(f"PR #{pr} targets `{view.get('baseRefName')}`, not `main`.", file=sys.stderr)
            return 4

    pr_info = view or {}
    branch = pr_info.get("headRefName")

    if not dry_run:
        existing = _latest_fix_run(runs_root, branch) if branch else None
        if existing is not None and existing.status == RUNNING:
            print(
                f"another fix run for `{branch}` is still marked running: "
                f"{existing.run_id}.",
                file=sys.stderr,
            )
            return 4

    if max_iterations <= 0:
        print("--max-iterations must be positive.", file=sys.stderr)
        return 2

    # 05-B1.1: the batch width is refused exactly as `--max-iterations` is — same message
    # shape, same place (before any run record, worktree or stage, `--dry-run` included).
    # `--max-iterations` still bounds *iterations* (batches), never the total fixes.
    if fix_batch <= 0:
        print("--fix-batch must be positive.", file=sys.stderr)
        return 2

    # --- locate the PR-head worktree (E2.6 req 3) ---------------------------- #
    # The PR head is authoritative, not the control worktree's current branch. A
    # missing worktree is a preflight refusal (exit 4, design §14) in a real run; a
    # dry run prints the corrective command as planned output and plans the F-rounds
    # against ``repo.root`` (the branch is known, there is just no worktree to plan in).
    if branch:
        worktree = git.worktree_for_branch(repo.root, branch)
    if branch and worktree is None:
        command = worktree_add_command(workspace, branch, repo.base_branch)
        if dry_run:
            print(f"worktree (planned): {(workspace.workspace_root / branch).resolve()}")
            print(f"branch-setup (planned): {command}")
        else:
            print(
                f"branch-setup refused: no worktree for `{branch}`. "
                f"Create it first:\n  {command}",
                file=sys.stderr,
            )
            return 4
    elif worktree is not None:
        # Re-resolve the target and agents against the worktree, and use it for every
        # stage, every ``github.*`` read of the tree, and ``create_run`` below, so
        # ``state.json``'s ``repo_root`` records the worktree (mirroring implement).
        resolved = TargetRepo.resolve(worktree)
        repo = replace(
            resolved,
            base_branch=repo.base_branch,
            branch_pattern=repo.branch_pattern,
        )
        agents, issues = load_all(
            aidt.root,
            repo.root,
            override_dir=agent_configs_override(resolved_config, repo.root),
        )
        reloaded_errors = [i for i in issues if i.level == ERROR]
        reloaded_warnings = [i for i in issues if i.level == WARNING]
        if force_model:
            # Same override as the control-root preflight: the reloaded configs are
            # the toolkit's agent configs, so the same warning reappears here (issue #58).
            reloaded_warnings = _filter_force_model(reloaded_warnings)
        if reloaded_errors or (strict and reloaded_warnings):
            print(
                format_issues(reloaded_errors + (reloaded_warnings if strict else [])),
                file=sys.stderr,
            )
            return 2
        if dry_run:
            print(f"worktree (planned): {worktree}")
    else:
        # An unanswerable PR read (``gh`` missing, or the chain's placeholder PR 0):
        # plan against the control root and keep going (E2.6 req 6), mirroring the
        # existing ``child: unknown`` line rather than refusing.
        reason = "`gh` not found" if not github.gh_available() else "PR head unknown"
        print(f"branch: unknown ({reason})")

    if branch:
        print(f"branch: {branch}")

    # --- one run per worktree (EXTRACTION.md §3.2/§3.10, E2.7) ---------------- #
    # The key is the *resolved* worktree path -- ``repo.root``, the same value
    # ``create_run`` records as ``repo_root`` -- never the branch: a detached-HEAD
    # worktree has no branch, and §3.2 says "keyed by worktree path". Acquired
    # immediately before ``create_run`` (the point where the key is final) and released
    # on every exit path below, refusals and failures included, so the worktree cannot
    # stay locked until process exit. It lives in the state root, never in a target
    # repo or worktree (§3.1), and it is neither ``_STATE_LOCK`` (in-process, per
    # ``state.json`` write) nor ``--parallel`` (concurrent stages inside one run).
    # A dry run acquires the same lock, so a peer run in this worktree is refused
    # (exit 4, §19 item 8) before any plan output; it is released on every exit path.
    try:
        run_lock = lock.acquire(workspace.state_root, repo.root)
    except lock.LockHeldError as exc:
        print(str(exc), file=sys.stderr)
        return 4

    try:
        # EXTRACTION.md §3.11 (E8.2): what produced this run. One helper so the
        # five workflows cannot record different values for one config.
        config_schema_version, config_hash = config_identity(resolved_config)
        # W1.2: a plan creates no run — `planned_run` is `create_run` under the
        # never-saved PLANNED_RUN_ID (identical signature, no write).
        state = (planned_run if dry_run else create_run)(
            runs_root,
            repo.root,
            "fix",
            label=f"pr-{pr}",
            pr={
                "number": pr,
                **({"url": pr_info["url"]} if pr_info.get("url") else {}),
                **({"force_model": True} if force_model else {}),
            },
            strict=strict,
            toolkit_version=__version__,
            config_schema_version=config_schema_version,
            config_hash=config_hash,
            branch=branch,
        )
        # A dry run has no run directory, so the paths it renders (F1's
        # ``{closing_bodies}``, F4's manifest) are *planned* ones: the `<run dir>`
        # placeholder names where a real run would write, and never a fabricated id.
        if dry_run:
            directory = Path(PLANNED_RUN_DIR_TEXT)
            logger = NullLogger(stream=stream)
        else:
            directory = run_dir(runs_root, state.run_id)
            # F1 writes its closing comment body here (P1.2 req 4), inside the run directory
            # and never in the PR-head worktree. Created once so no stage has to guess a
            # directory; a plan creates nothing (§19 item 10).
            (directory / "artifacts").mkdir(parents=True, exist_ok=True)
            logger = RunLogger(directory, stream=stream)
            print(f"run:    {state.run_id}")
        print(f"pr:     #{pr}" + (f" {pr_info['url']}" if pr_info.get("url") else ""))

        # --- the post-loop half: the tick, then the commit (design §8.4) --------- #
        # Two stages, planned **together** and run exactly once per run, after the loop —
        # never inside it: `I7 update-roadmap` (H3.3) and `F5 commit-and-push` (05-P1.1).
        # The tick's split mirrors ``implement``'s ``withhold_tick``/``settle_tick``
        # (H3.2): its condition is evaluated **before** ``run_stage``, and the skip is routed
        # around the postcondition, because ``settle_roadmap_tick`` would otherwise stamp
        # ``tick: already`` onto a stage that never ran.
        def withhold_tick(reason: str, specs: Mapping[str, StageSpec]) -> StageRecord:
            """Record the post-loop tick as skipped, with ``reason`` (H3.3 req 4/req 6).

            ``record_skipped`` publishes a full ``StageRecord`` (status ``skipped``, the
            reason in ``artifacts[SKIP_REASON_KEY]``, ``error`` unset) exactly as
            ``run_stage`` publishes its own, so a skip is a decision with a reason rather
            than a silent omission. The same reason is copied to
            ``state.pr[PR_ROADMAP_TICK_SKIP_REASON]`` and ``state.pr[PR_ROADMAP_TICKED]``
            becomes ``False`` (H3.3 req 6). A skip never changes ``state.status`` and never
            fails the run: the stop that caused it already decided the outcome.

            ``specs`` is the one post-loop plan this decision belongs to
            (:func:`_post_loop_specs`), never a fresh per-stage planning call.
            """
            spec = specs[TICK_STAGE_NAME]
            record = record_skipped(
                spec,
                state=state,
                directory=directory,
                agents=agents,
                reason=reason,
                # W1.2: the dry run plans the same withheld tick a real run would record,
                # with the same reason, but a plan persists nothing.
                dry_run=dry_run,
            )
            state.pr[PR_ROADMAP_TICKED] = False
            state.pr[PR_ROADMAP_TICK_SKIP_REASON] = reason
            logger.info(f"stage {spec.name}: skipped — {reason}")
            print_stage(record, repo_root=repo.root)
            return record

        def withhold_commit(reason: str, specs: Mapping[str, StageSpec]) -> StageRecord:
            """Record ``F5`` as skipped with ``reason``, and why in ``state.pr`` (D3/D7).

            Same shape as :func:`withhold_tick`: a full ``StageRecord`` with status
            ``skipped``, the reason in ``artifacts[SKIP_REASON_KEY]`` and ``error`` unset,
            plus ``state.pr[PR_COMMIT_SKIP_REASON]``. ``state.pr[PR_HEAD_SHA]`` stays
            absent — its presence is the "committed and pushed" boolean (D7) — and a skip
            never changes ``state.status`` or the exit code.
            """
            spec = specs[COMMIT_STAGE_NAME]
            record = record_skipped(
                spec,
                state=state,
                directory=directory,
                agents=agents,
                reason=reason,
                dry_run=dry_run,
            )
            state.pr[PR_COMMIT_SKIP_REASON] = reason
            logger.info(f"stage {spec.name}: skipped — {reason}")
            print_stage(record, repo_root=repo.root)
            return record

        def stop(reason: str) -> None:
            """Record why a stopped loop ticked nothing **and** published nothing (req 4).

            The one call site every stop path shares (``--max-iterations``, a denied gate,
            an ambiguous or ``Blocked`` verdict, an unparseable manifest, a failed stage):
            it records ``I7``'s skip and ``F5``'s skip with the same stop reason, instead of
            a ``record_skipped`` at each ``return``. A stopped loop never commits and never
            pushes (decision D4).
            """
            stop_reason = STOP_REASON.format(stop=reason)
            specs = _post_loop_specs(
                target=RoadmapTarget(),
                pr=pr,
                round_index=1,
                iteration=1,
                config=resolved_config,
                aidt=aidt.root,
                repo=repo.root,
                directory=directory,
                fix_batch=fix_batch,
            )
            withhold_tick(stop_reason, specs)
            withhold_commit(stop_reason, specs)

        def run_commit(
            specs: Mapping[str, StageSpec], *, closed_issues: Sequence[Mapping[str, Any]]
        ) -> int:
            """Apply D3's table, then run and verify ``F5`` (req 3/req 4/req 5/req 6).

            The trigger is the loop's convergence, not the tick's outcome (decision D2):
            a converged run whose tick was withheld still has real fix edits, so this runs
            after ``I7`` succeeded **or** was recorded as skipped, for any skip reason.

            Nothing here is trusted from the agent's exit code alone — a **new commit**
            (``HEAD`` moved), the pushed proof (D6) and a clean tree are all re-read from
            git, the O1 precedent. The HEAD-movement check closes the PR #158 review
            finding: a stage that stashes or cleans the change set instead of committing
            leaves ``HEAD == origin/<branch>`` and a clean tree on the *pre-existing* SHAs,
            so the other checks alone would pass and the fixes would be lost. Every failure
            names the PR and the branch and leaves ``state.pr[PR_HEAD_SHA]`` absent.
            """
            decision = commit_decision(
                tree_dirty=not git.is_clean(repo.root), closed_issues=closed_issues
            )
            if decision.action == COMMIT_ACTION_SKIP:
                withhold_commit(decision.reason, specs)
                return 0
            if decision.action == COMMIT_ACTION_FAIL:
                print(commit_failure_message(pr, branch, decision.reason), file=sys.stderr)
                return 1
            # D5: the branch is the PR head the preflight already resolved (decision K1),
            # never the control root's `main`. A misresolved ref must never push the base
            # branch, so the refusal sits **before** the stage — the agent commits and
            # pushes in one invocation, and a `git push` is not reversible.
            if branch == repo.base_branch:
                print(
                    commit_failure_message(
                        pr,
                        branch,
                        f"the resolved PR head is the base branch "
                        f"`{repo.base_branch}`; refusing to commit or push it",
                    ),
                    file=sys.stderr,
                )
                return 1
            # The new-commit proof's baseline (PR #158 review finding): `HEAD` as it stands
            # before the agent runs. Captured here, after the base-branch refusal, so this
            # is the only worktree read the proof adds, and only on the commit path.
            before = git.rev_parse(repo.root, "HEAD")
            record = run_stage(
                specs[COMMIT_STAGE_NAME],
                repo_root=repo.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
                config=resolved_config,
            )
            print_stage(record, repo_root=repo.root)
            if record.status != SUCCEEDED:
                print(
                    commit_failure_message(
                        pr,
                        branch,
                        f"the stage ended `{record.status}`"
                        + (f": {record.error}" if record.error else ""),
                    ),
                    file=sys.stderr,
                )
                return 1
            # A new commit must exist before "the push landed" means anything (PR #158
            # review finding). The tree is dirty by construction on this path, so a real
            # `git commit` always moves `HEAD`; a stashed or cleaned tree leaves it where
            # `before` found it while the D6 equality and the clean-tree check below both
            # still hold on the pre-existing SHAs.
            head = git.rev_parse(repo.root, "HEAD")
            if before is None or head is None or head == before:
                print(
                    commit_failure_message(
                        pr,
                        branch,
                        "the stage reported success but HEAD did not move ("
                        f"`{before or 'unresolvable'}` -> `{head or 'unresolvable'}`); "
                        "the change set was not committed",
                    ),
                    file=sys.stderr,
                )
                return 1
            # D6: the pushed proof is pinned. A successful `git push` updates the
            # remote-tracking ref, so `rev_parse` on both sides is the evidence — no fetch,
            # no `ls-remote`, no `status`/`log` heuristic.
            pushed = git.rev_parse(repo.root, f"origin/{branch}") if branch else None
            if head is None or pushed is None or head != pushed:
                print(
                    commit_failure_message(
                        pr,
                        branch,
                        "the push did not land: HEAD is "
                        f"`{head or 'unresolvable'}` and `origin/{branch}` is "
                        f"`{pushed or 'unresolvable'}`",
                    ),
                    file=sys.stderr,
                )
                return 1
            # Nothing records which paths the fixers touched, so the add is broad by design
            # (`git add -A`, §13's documented primitive executed by the agent); a tree that
            # is still dirty means part of the change set did not make it into the commit.
            if not git.is_clean(repo.root):
                print(
                    commit_failure_message(
                        pr, branch, "the working tree is still dirty after the stage"
                    ),
                    file=sys.stderr,
                )
                return 1
            state.pr[PR_HEAD_SHA] = pushed
            state.pr.pop(PR_COMMIT_SKIP_REASON, None)
            logger.info(f"stage {record.name}: pushed `{pushed}` to `origin/{branch}`")
            return 0

        def run_closes(issues: Sequence[Mapping[str, Any]]) -> int:
            """Close exactly the issues this run recorded, one script call each (req 3/req 6).

            Called only after :func:`run_commit` returned 0 **and** ``state.pr[PR_HEAD_SHA]``
            is present, i.e. after D6's equality proved the push landed, so no issue is
            reported fixed before its fix reached the PR. One entry, one ``close`` call, one
            issue: never a batch and never a re-derived count (req 6), because a batch that
            failed halfway could strand an issue half-closed.
            """
            for entry in issues:
                result = run_close(
                    entry, aidt=aidt.root, repo=repo.root, pr=pr, config=resolved_config
                )
                if result.exit_code != 0:
                    detail = (result.stderr or result.stdout).strip()[:300]
                    print(
                        close_failure_message(
                            pr,
                            branch,
                            entry.get("number"),
                            f"`close` exited {result.exit_code}"
                            + (f": {detail}" if detail else ""),
                        ),
                        file=sys.stderr,
                    )
                    return 1
                logger.info(
                    f"close: #{entry.get('number')} marked fixed and closed "
                    f"({entry.get('closing_body')})"
                )
                print(
                    f"close:  #{entry.get('number')} marked `Status: fixed` and closed "
                    f"after the push"
                )
            return 0

        def run_post_loop(*, iteration: int, latest_verdict: str | None) -> int:
            """Plan the post-loop half once, tick the roadmap, then publish (req 1-5).

            Called exactly once, after the loop breaks on ``EXIT_NONE_AVAILABLE``. The
            target is resolved first (req 3): with no single roadmap entry the tick is
            skipped with that reason and the run still succeeds, because ``fix`` must keep
            working on PRs that are not AIDT tasks. Then this run's own evidence decides
            the tick (req 4); only a green verdict reads the file, runs the shared stage and
            applies ``implement``'s byte-exact postcondition (req 5). ``F5`` then applies
            D3's table whatever the tick decided (D2) — a failed tick stage is the one
            exception, because committing a half-applied tick is worse than leaving the
            tree for a human (D4).
            """
            target = resolve_roadmap_target(
                runs_root=runs_root,
                branch=branch,
                branch_pattern=repo.branch_pattern,
                repo_root=repo.root,
                config=resolved_config,
            )
            # One planning call for both post-loop stages (req 2); an empty converged run
            # records `iterations == 0`, and the value only names the discarded loop stages
            # of this planning call, so keep it legible.
            specs = _post_loop_specs(
                target=target,
                pr=pr,
                round_index=round_index,
                iteration=max(iteration, 1),
                config=resolved_config,
                aidt=aidt.root,
                repo=repo.root,
                directory=directory,
                fix_batch=fix_batch,
            )
            if target.roadmap_file is None:
                withhold_tick(target.reason, specs)
            else:
                evidence = tick_evidence(
                    loop_closed=True,
                    test_records=[
                        record for record in state.stages if is_test_stage(record.name)
                    ],
                    latest_verdict=latest_verdict,
                )
                if not evidence.green:
                    withhold_tick(evidence.reason, specs)
                else:
                    # The loop converged, so this run's own evidence is green — but the tick
                    # is a completion claim and must also agree with what the run recorded
                    # about the task's Done-when (design §8.2; the rule is shared with
                    # `implement` so the two ticks cannot drift, H3.3). Withheld, never
                    # failed: the recorded verdict is the thing to fix, and `fix` cannot
                    # repair a build-results document it did not write.
                    conclusion = roadmap.recorded_unmet_conclusion(
                        repo.root,
                        implementation_results_dir=(
                            resolved_config["paths.implementation_results_dir"].value
                        ),
                        phase=target.phase,
                        task=target.task,
                    )
                    if conclusion is not None:
                        withhold_tick(
                            roadmap.unmet_conclusion_reason(conclusion), specs
                        )
                    else:
                        code = _tick(
                            specs[TICK_STAGE_NAME], target.roadmap_file, target.task
                        )
                        if code != 0:
                            return code
            return run_commit(specs, closed_issues=closed_issues)

        def _tick(spec: StageSpec, roadmap_file: Path, checkbox_id: str) -> int:
            """Run the shared tick stage and apply ``implement``'s byte-exact postcondition."""
            before = roadmap_file.read_text(encoding="utf-8")
            record = run_stage(
                spec,
                repo_root=repo.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
                config=resolved_config,
            )
            print_stage(record, repo_root=repo.root)
            settle_roadmap_tick(
                record,
                checkbox_id=checkbox_id,
                roadmap_file=roadmap_file,
                before=before,
                logger=logger,
                state=state,
                directory=directory,
            )
            if record.status == SUCCEEDED:
                # `settle_roadmap_tick` already wrote the `tick: flipped|already` outcome
                # and its one `run.log` line (H3.1 req 7), so this only records the `pr`
                # field — one line, one meaning.
                state.pr[PR_ROADMAP_TICKED] = True
                state.pr.pop(PR_ROADMAP_TICK_SKIP_REASON, None)
                return 0
            state.pr[PR_ROADMAP_TICKED] = False
            state.pr[PR_ROADMAP_TICK_SKIP_REASON] = record.error
            print(f"stage {record.name} failed: {record.error}", file=sys.stderr)
            return 1

        if dry_run:
            script = github.script_path(aidt.root, github.FOLLOWUP_SCRIPT)
            if github.gh_available():
                # The preview passes `--limit` like the loop does, so the plan shows the
                # whole batch and the `select` argv it prints is the argv a real run uses.
                selection = github.select_followups(
                    aidt.root,
                    repo.root,
                    pr,
                    config=resolved_config,
                    limit=fix_batch,
                )
                payload = github.parse_json_output(selection.stdout) or {}
                if selection.exit_code == github.EXIT_NONE_AVAILABLE:
                    print("child:  none available")
                elif selection.exit_code == github.EXIT_OK:
                    # The preview reads the payload through the same guard as the loop, so a
                    # non-array `selected` fails the plan instead of being normalised into a
                    # one-child batch the real run would never fix (05-B1.1 reqs 2/3).
                    batch = _selected_batch(payload)
                    if batch is None:
                        print(SELECT_NOT_A_BATCH, file=sys.stderr)
                        return 1
                    for child in batch:
                        print(
                            f"child:  #{child.get('number')} {child.get('title')} "
                            f"({child.get('priority')})"
                        )
                    print(
                        f"children: {payload.get('childrenInspected')} inspected "
                        f"of {payload.get('totalChildren')} "
                        f"(up to {fix_batch} per iteration)"
                    )
                else:
                    print(
                        f"select failed (exit {selection.exit_code}): "
                        f"{selection.stderr.strip()[:200]}",
                        file=sys.stderr,
                    )
            else:
                print("child:  unknown (`gh` not found)")
            print(
                "select argv: "
                + " ".join(
                    github.build_followup_argv(script, "select", pr, limit=fix_batch)
                )
            )

            # The planned iteration's real-run field values (E4.3 req 5): round 1's
            # approval plus iteration 1's F1–F4, with that iteration's manifest path so the
            # dry-run F4 prompt already carries the pointer a real run would render.
            planned = _planned_iteration(
                pr=pr,
                round_index=1,
                iteration=1,
                config=resolved_config,
                aidt=aidt.root,
                repo=repo.root,
                directory=directory,
                fix_batch=fix_batch,
            )
            for spec in planned.values():
                record = run_stage(
                    spec,
                    repo_root=repo.root,
                    toolkit_root=aidt.root,
                    runs_root=runs_root,
                    state=state,
                    logger=logger,
                    agents=agents,
                    dry_run=True,
                    config=resolved_config,
                )
                note = (
                    " (only when F3 reports findings)"
                    if spec.name.endswith("review-findings-to-github")
                    else ""
                )
                print(f"{record.name} [{record.status}] (planned) agent={record.agent}{note}")
            # H3.3 req 7 + 05-P1.1 req 2/D10: the post-loop half is planned here, once
            # each and in order, and evaluates **no** evidence — a dry run never withholds
            # and never ticks. An unresolvable target (a PR that is not an AIDT task, or the
            # chain's placeholder PR 0) still shows the tick once, as the skip a real run
            # would record; ``F5`` is planned regardless, because a dry run inspects no
            # tree and never withholds.
            dry_target = resolve_roadmap_target(
                runs_root=runs_root,
                branch=branch,
                branch_pattern=repo.branch_pattern,
                repo_root=repo.root,
                config=resolved_config,
            )
            dry_specs = _post_loop_specs(
                target=dry_target,
                pr=pr,
                round_index=1,
                iteration=1,
                config=resolved_config,
                aidt=aidt.root,
                repo=repo.root,
                directory=directory,
                fix_batch=fix_batch,
            )
            if dry_target.roadmap_file is None:
                withhold_tick(dry_target.reason, dry_specs)
            else:
                record = run_stage(
                    dry_specs[TICK_STAGE_NAME],
                    repo_root=repo.root,
                    toolkit_root=aidt.root,
                    runs_root=runs_root,
                    state=state,
                    logger=logger,
                    agents=agents,
                    dry_run=True,
                    config=resolved_config,
                )
                print(
                    f"{record.name} [{record.status}] (planned) agent={record.agent} "
                    f"(after the loop, only when this run's evidence is green)"
                )
            record = run_stage(
                dry_specs[COMMIT_STAGE_NAME],
                repo_root=repo.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
                dry_run=True,
                config=resolved_config,
            )
            print(
                f"{record.name} [{record.status}] (planned) agent={record.agent} "
                f"(after the loop, only when this run closed an issue)"
            )
            print("gates (planned): approve-followups, approve-fix-pr")
            print(
                f"loop: bounded by --max-iterations={max_iterations} "
                f"(iterations; up to --fix-batch={fix_batch} fixes each)"
            )
            print("dry-run complete; Pi not invoked, no GitHub state written")
            return 0

        # --- initial approval round --------------------------------------------- #
        code = _approval_round(
            1,
            pr=pr,
            repo=repo.root,
            aidt=aidt.root,
            agents=agents,
            state=state,
            logger=logger,
            directory=directory,
            runs_root=runs_root,
            config=resolved_config,
            approve_all=approve_all,
            skip=skip,
            deny=deny,
            gate_default=gate_default,
            fix_batch=fix_batch,
        )
        if code is not None:
            state.status = BLOCKED if code == 3 else FAILED
            # H3.3 req 1 + 05-P1.1 req 4: a stopped run records why it ticked nothing and
            # published nothing, once, with the stop as the reason — then keeps its own exit
            # code.
            stop("the entry `approve-followups` round")
            save(directory, state)
            return code

        iterations = 0
        round_index = 1
        closed_issues: list[dict] = []
        latest_verdict: str | None = None

        while True:
            if iterations >= max_iterations:
                print(
                    f"reached --max-iterations ({max_iterations}); stopping.",
                    file=sys.stderr,
                )
                state.status = BLOCKED
                stop("--max-iterations")
                save(directory, state)
                return 3

            # 05-B1.1: the iteration's work is exactly the children `select --limit N`
            # returned, in native order — never a count re-derived from `closed_issues` or
            # `childrenInspected`. The flag is always passed here, so `selected` must be the
            # array shape; a single object would be the old single-select contract and
            # would silently fix only the first child.
            selection = github.select_followups(
                aidt.root, repo.root, pr, config=resolved_config, limit=fix_batch
            )
            payload = github.parse_json_output(selection.stdout) or {}
            if selection.exit_code == github.EXIT_NONE_AVAILABLE:
                break
            if selection.exit_code != github.EXIT_OK:
                print(
                    f"select failed (exit {selection.exit_code}): "
                    f"{selection.stderr.strip()[:300]}",
                    file=sys.stderr,
                )
                state.status = FAILED
                stop("a failed `select` read")
                save(directory, state)
                return 1

            batch = _selected_batch(payload)
            if batch is None:
                # Fail closed: a non-array, an empty array on exit 0, or an entry without a
                # usable issue number is not a batch this loop may fix. Never fall back to
                # the first element — that is the one-fix-per-iteration contract this task
                # reverses — and never derive a width from a count (§8.4).
                print(SELECT_NOT_A_BATCH, file=sys.stderr)
                state.status = FAILED
                stop("a `select` read that did not return a batch")
                save(directory, state)
                return 1

            iterations += 1
            prefix = f"iter{iterations}"
            for child in batch:
                print(
                    f"fix:    #{child.get('number')} {child.get('title')} "
                    f"({child.get('priority')})"
                )

            # Each issue gets its own closing body in this iteration's directory
            # (05-B1.1 req 5). The workflow creates it — never the agent, which cannot know
            # the run directory — before F1 and only on a real run: this loop is
            # real-run-only, so a plan still creates nothing (W1.2/Z14).
            closing_bodies_dir(directory, iterations).mkdir(parents=True, exist_ok=True)
            # This iteration's F1–F4, expanded from the registry once per iteration
            # (E4.3): the stage names carry the iteration count and F2/F4 carry the
            # registry-rendered context and manifest pointer. The loop is re-derived from
            # GitHub state each iteration, so nothing here is pre-planned. F1 also carries
            # the close-deferral's directory (P1.2 req 4, per issue since 05-B1.1), and
            # each `closed_issues` entry below records its own file inside it.
            planned = _planned_iteration(
                pr=pr,
                round_index=round_index,
                iteration=iterations,
                config=resolved_config,
                aidt=aidt.root,
                repo=repo.root,
                directory=directory,
                fix_batch=fix_batch,
            )

            # F1 — fix the approved batch of children, in the order `select` returned.
            record = run_stage(
                planned[f"{prefix}-fix-next-review-followup"],
                repo_root=repo.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
                config=resolved_config,
            )
            print_stage(record, repo_root=repo.root)
            if record.status != SUCCEEDED:
                print(f"stage {record.name} failed: {record.error}", file=sys.stderr)
                state.status = FAILED
                stop(f"a failed `{record.name}` stage")
                save(directory, state)
                return 1

            # F2 — independent re-test.
            record = run_stage(
                planned[f"{prefix}-test"],
                repo_root=repo.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
                config=resolved_config,
            )
            print_stage(record, repo_root=repo.root)
            if record.status != SUCCEEDED:
                print(f"stage {record.name} failed: {record.error}", file=sys.stderr)
                state.status = FAILED
                stop(f"a failed `{record.name}` stage")
                save(directory, state)
                return 1

            # F3 — independent re-review.
            record = run_stage(
                planned[f"{prefix}-code-review"],
                repo_root=repo.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
                config=resolved_config,
            )
            print_stage(record, repo_root=repo.root)
            if record.status != SUCCEEDED:
                print(f"stage {record.name} failed: {record.error}", file=sys.stderr)
                state.status = FAILED
                stop(f"a failed `{record.name}` stage")
                save(directory, state)
                return 1

            review_text = _read_out(record) or ""
            if not review_text.strip():
                print(f"{empty_final_message_error(record)}; stopping.", file=sys.stderr)
                state.status = FAILED
                stop("an empty re-review")
                save(directory, state)
                return 1
            verdict = parse_verdict(review_text)
            latest_verdict = verdict
            parsed, problems = findings_mod.parse_review_findings(review_text)
            _write_json(
                directory / "artifacts" / f"{prefix}-findings.json",
                {
                    "pr": pr,
                    "iteration": iterations,
                    "verdict": verdict,
                    "findings": [
                        f.to_manifest_entry(i) for i, f in enumerate(parsed, start=1)
                    ],
                    "problems": problems,
                },
            )
            print(f"verdict: {verdict or 'ambiguous'}")

            if verdict is None:
                state.status = BLOCKED
                stop("an ambiguous re-review verdict")
                save(directory, state)
                print("re-review verdict is ambiguous; failing closed.", file=sys.stderr)
                return 3
            if verdict == VERDICT_BLOCKED:
                state.status = BLOCKED
                stop("a `Blocked` re-review")
                save(directory, state)
                print("re-review is Blocked; stopping.", file=sys.stderr)
                return 3
            if problems:
                state.status = BLOCKED
                stop("an unparseable re-review findings manifest")
                save(directory, state)
                print(
                    "could not build a findings manifest for the re-review; failing closed.",
                    file=sys.stderr,
                )
                return 3

            if parsed:
                # F4 — publish the new findings (ungated), then a human decides on GitHub.
                _write_json(
                    directory / f"artifacts/{prefix}-review-manifest.json",
                    findings_mod.to_manifest(parsed),
                )
                record = run_stage(
                    planned[f"{prefix}-review-findings-to-github"],
                    repo_root=repo.root,
                    toolkit_root=aidt.root,
                    runs_root=runs_root,
                    state=state,
                    logger=logger,
                    agents=agents,
                    config=resolved_config,
                )
                print_stage(record, repo_root=repo.root)
                if record.status != SUCCEEDED:
                    print(f"stage {record.name} failed: {record.error}", file=sys.stderr)
                    state.status = FAILED
                    stop(f"a failed `{record.name}` stage")
                    save(directory, state)
                    return 1

                round_index += 1
                code = _approval_round(
                    round_index,
                    pr=pr,
                    repo=repo.root,
                    aidt=aidt.root,
                    agents=agents,
                    state=state,
                    logger=logger,
                    directory=directory,
                    runs_root=runs_root,
                    config=resolved_config,
                    approve_all=approve_all,
                    skip=skip,
                    deny=deny,
                    gate_default=gate_default,
                    fix_batch=fix_batch,
                )
                if code is not None:
                    state.status = BLOCKED if code == 3 else FAILED
                    stop(f"the `approve-followups` gate of round {round_index}")
                    save(directory, state)
                    return code
                continue

            if verdict != APPROVE:
                state.status = BLOCKED
                stop("a `Request changes` re-review with no extractable findings")
                save(directory, state)
                print(
                    "re-review requires changes but no findings could be extracted; "
                    "failing closed.",
                    file=sys.stderr,
                )
                return 3

            # Clean re-review: approve the fix PR.
            summary = "\n".join(
                [
                    f"Re-review approved for PR #{pr} (iteration {iterations})",
                    *(
                        f"Fixed issue: #{child.get('number')} {child.get('title')}"
                        for child in batch
                    ),
                    f"Verdict: {verdict}",
                ]
            )
            outcome = decide(
                GATE_FIX_PR,
                summary,
                approve_all=approve_all,
                skip=skip,
                deny=deny,
                gate_default=gate_default,
            )
            state.record_gate(
                GateRecord(
                    name=GATE_FIX_PR,
                    decision=outcome.decision,
                    mechanism=outcome.mechanism,
                    at=utcnow_iso(),
                    detail=f"iteration={iterations}",
                )
            )
            save(directory, state)
            print(f"gate:   {GATE_FIX_PR} [{outcome.mechanism}]")
            if not outcome.approved:
                state.status = BLOCKED
                stop(f"the `{GATE_FIX_PR}` gate")
                save(directory, state)
                print(
                    f"gate {GATE_FIX_PR} denied ({outcome.mechanism}); stopping.",
                    file=sys.stderr,
                )
                return 3
            # One entry per batch **issue**, each carrying its own absolute body path, so
            # the close step passes one `--body-file` per issue after the push (05-B1.1
            # req 4). `closed_issues` still means "fixed, close-pending" —
            # `commit_decision` reads it as "≥1 fix to publish" (Z9 D3) and is deliberately
            # unchanged. A failed F2/F3 above returns before any append, so a failed batch
            # records no entry and no issue in it is closed — never a subset.
            for child in batch:
                closed_issues.append(
                    {
                        **child,
                        "closing_body": str(
                            closing_body_path(
                                directory, iterations, child.get("number")
                            )
                        ),
                    }
                )

        # --- the post-loop half, once per run (H3.3 req 1/req 7; 05-P1.1 req 1-5) -- #
        # The loop only reaches here through its `break` on `select` exit
        # `EXIT_NONE_AVAILABLE`, so this is the converged path: the roadmap tick and the
        # commit-and-push stage are planned once, run exactly here — after the last
        # iteration and never inside it. `run_post_loop` records each with its own reason
        # when the target, the evidence or the tree is not good enough, which is still exit
        # 0 for a skip; the commit case fails the run when it cannot publish.
        post_loop_code = run_post_loop(
            iteration=iterations, latest_verdict=latest_verdict
        )
        if post_loop_code != 0:
            state.status = FAILED
            save(directory, state)
            return post_loop_code

        _write_json(
            directory / "artifacts" / "fix.json",
            {
                "pr": pr,
                "iterations": iterations,
                "closed_issues": closed_issues,
                "latest_verdict": latest_verdict,
            },
        )
        state.pr.update(
            {
                "iterations": iterations,
                "closed_issues": closed_issues,
                "latest_verdict": latest_verdict,
            }
        )

        # --- the deferred close, after the push (05-P1.2 req 1/req 3/req 5/req 6) ------- #
        # The loop only records an issue as fixed; the close waits for `run_commit`'s proof
        # that the fix reached the PR (D6). A run that recorded no entry keeps D3's skip
        # contract: nothing to close, exit 0. A run that recorded one but has no verified
        # push (a skip, a failure, an absent commit stage) fails closed here and closes
        # nothing — "reported fixed" without a push is exactly the untruthful state this
        # task removes.
        if closed_issues and PR_HEAD_SHA not in state.pr:
            for entry in closed_issues:
                print(
                    close_failure_message(
                        pr, branch, entry.get("number"), CLOSE_FAIL_NO_VERIFIED_PUSH
                    ),
                    file=sys.stderr,
                )
            state.status = FAILED
            save(directory, state)
            return 1
        close_code = run_closes(closed_issues)
        if close_code != 0:
            state.status = FAILED
            save(directory, state)
            return close_code

        state.status = SUCCEEDED
        save(directory, state)
        print("fix workflow complete")
        if closed_issues:
            print(f"closed: {', '.join('#' + str(i.get('number')) for i in closed_issues)}")
        else:
            print("no approved children required a fix")
        return 0
    finally:
        run_lock.release()
