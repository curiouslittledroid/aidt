"""``aidw fix`` — fix approved review follow-ups (design §8.4).

```
preflight (PR exists, targets main, the PR head's worktree is located)
  → list open children; show GitHub state
  ◇  approve-followups              runs /approve-review-followups (agent review-approver)
  ⟳  one approved child at a time:
       → F1 fix-next-review-followup  (agent fixer, fresh)
       → F2 test                      (agent tester, fresh)
       → F3 code-review               (agent code-reviewer, fresh)
       if F3 has findings:
         → F4 review-findings-to-github (ungated)  then ◇ approve-followups
       else:
         ◇ approve-fix-pr
     repeat until no approved child remains
```

Selection is always re-derived from ``review_followup.py select`` (never by counting), so
the loop is driven by real GitHub state. ``--max-iterations`` bounds the number of fixes.

Since H3.3 the run then ticks the task's roadmap checkbox **once**, after the loop converges
(design §8.4; H3.1's stage, H3.2's condition): the tick is the shared ``I7 update-roadmap``
stage from ``aidw.stage_registry`` — one id, one prompt, one agent and one name with
``implement`` — so the two ticks cannot drift. Three things are deliberate about *where* it
lives:

* the stage is a :attr:`~aidw.stage_registry.WorkflowDefinition.post_loop` entry, emitted
  only when a caller asks for the post-loop half. ``_planned_iteration`` calls
  ``plan_stages`` once per iteration and must never carry the tick, or it would run — and
  dry-run print — once per iteration instead of once per run;
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

All GitHub writes are performed by AIDT's bundled prompts/scripts (the fixer and approver
agents). AIDT only reads: ``gh pr view`` and ``review_followup.py select``.

The tick's edit stays **uncommitted**, like every other ``fix`` stage: no stage of ``fix``
commits (design §13).

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
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from aidw import __version__, findings as findings_mod
from aidw import git, github, lock, roadmap, stage_registry
from aidw.config import ERROR, WARNING, Issue, format_issues, load_all
from aidw.gates import decide
from aidw.log import RunLogger
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

#: The loop's re-test stage names (``iter1-test``, ``iter2-test``) — H3.3 req 4(b)'s
#: "every ``iter{N}-test`` stage record is ``SUCCEEDED``". Derived from the registry's
#: template rather than a second spelling of it.
_TEST_STAGE_PREFIX = "iter"
_TEST_STAGE_SUFFIX = "-test"


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


def _tick_spec(
    *,
    target: RoadmapTarget,
    pr: int,
    round_index: int,
    iteration: int,
    config: ResolvedConfig,
    aidt: Path,
    repo: Path,
    directory: Path,
) -> StageSpec:
    """The shared post-loop stage as a runnable spec — planned once per run (req 1/req 7).

    ``include_post_loop`` is what keeps the tick out of ``_planned_iteration``'s
    per-iteration plan: the same ``plan_stages`` call produces it only here. An unresolved
    target renders empty roadmap values, which is honest for a stage that is only ever
    **recorded as skipped** in that case — the record needs the stage's name and agent, not
    its variables.

    ``round_index``/``iteration`` are the loop's current position for a converged run; the
    skip paths pass ``1``/``1``, because the stage being recorded has neither variable.
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
        include_post_loop=True,
        roadmap_file=str(target.roadmap_file) if target.roadmap_file else "",
        checkbox_id=target.task,
    )
    for spec in planned:
        if spec.name == TICK_STAGE_NAME:
            return spec
    raise AssertionError(  # pragma: no cover - the preflight refuses a list without I7
        "the `fix` plan carries no post-loop `update-roadmap` stage; a declared "
        "`workflows.fix.stages` list must include `I7`"
    )


def _planned_iteration(
    *,
    pr: int,
    round_index: int,
    iteration: int,
    config: ResolvedConfig,
    aidt: Path,
    repo: Path,
    directory: Path,
) -> dict[str, StageSpec]:
    """One fix iteration's stage specs from the registry, keyed by stage name (E4.3).

    The iteration count and the round index are external GitHub state, so the loop expands
    the iteration it is about to run rather than a pre-built list (EXTRACTION.md §3.5,
    design §8.4). ``manifest_path`` is that iteration's real-run manifest path in the run
    directory ``directory`` — the value the registry renders into F4's pointer — so the dry
    run and a real run plan the same ``extra``. It is absolute for the same reason
    ``review.py`` passes an absolute path: F4 runs with the target repo as its cwd.

    Deliberately **no** ``include_post_loop``: this is the per-iteration expansion, and the
    roadmap tick runs once per run, after the loop (H3.3 req 1/req 7). ``_tick_spec`` is the
    one caller that asks for the post-loop half.
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
    # A dry run reaches ``create_run`` too, so it holds and releases the same lock.
    try:
        run_lock = lock.acquire(workspace.state_root, repo.root)
    except lock.LockHeldError as exc:
        print(str(exc), file=sys.stderr)
        return 4

    try:
        # EXTRACTION.md §3.11 (E8.2): what produced this run. One helper so the
        # five workflows cannot record different values for one config.
        config_schema_version, config_hash = config_identity(resolved_config)
        state = create_run(
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
        directory = run_dir(runs_root, state.run_id)
        logger = RunLogger(directory, stream=stream)
        print(f"run:    {state.run_id}")
        print(f"pr:     #{pr}" + (f" {pr_info['url']}" if pr_info.get("url") else ""))

        # --- the post-loop roadmap tick (H3.3, design §8.4) ---------------------- #
        # Planned and run exactly once per run, after the loop — never inside it. The split
        # mirrors ``implement``'s ``withhold_tick``/``settle_tick`` (H3.2): the condition is
        # evaluated **before** ``run_stage``, and the skip is routed around the
        # postcondition, because ``settle_roadmap_tick`` would otherwise stamp
        # ``tick: already`` onto a stage that never ran.
        def withhold_tick(reason: str, target: RoadmapTarget | None = None) -> StageRecord:
            """Record the post-loop tick as skipped, with ``reason`` (H3.3 req 4/req 6).

            ``record_skipped`` publishes a full ``StageRecord`` (status ``skipped``, the
            reason in ``artifacts[SKIP_REASON_KEY]``, ``error`` unset) exactly as
            ``run_stage`` publishes its own, so a skip is a decision with a reason rather
            than a silent omission. The same reason is copied to
            ``state.pr[PR_ROADMAP_TICK_SKIP_REASON]`` and ``state.pr[PR_ROADMAP_TICKED]``
            becomes ``False`` (H3.3 req 6). A skip never changes ``state.status`` and never
            fails the run: the stop that caused it already decided the outcome.
            """
            spec = _tick_spec(
                target=target or RoadmapTarget(),
                pr=pr,
                round_index=1,
                iteration=1,
                config=resolved_config,
                aidt=aidt.root,
                repo=repo.root,
                directory=directory,
            )
            record = record_skipped(
                spec,
                state=state,
                directory=directory,
                agents=agents,
                reason=reason,
            )
            state.pr[PR_ROADMAP_TICKED] = False
            state.pr[PR_ROADMAP_TICK_SKIP_REASON] = reason
            logger.info(f"stage {spec.name}: skipped — {reason}")
            print_stage(record, repo_root=repo.root)
            return record

        def stop(reason: str) -> None:
            """Record why a stopped loop ticked nothing, before its own return (req 1)."""
            withhold_tick(STOP_REASON.format(stop=reason))

        def run_post_loop(*, iteration: int, latest_verdict: str | None) -> int:
            """Plan and — on green evidence — run the single post-loop tick (req 1/4/5).

            Called exactly once, after the loop breaks on ``EXIT_NONE_AVAILABLE``. The
            target is resolved first (req 3): with no single roadmap entry the stage is
            skipped with that reason and the run still succeeds, because ``fix`` must keep
            working on PRs that are not AIDT tasks. Then this run's own evidence decides
            (req 4). Only a green verdict reads the file, runs the shared stage and applies
            ``implement``'s byte-exact postcondition (req 5).
            """
            target = resolve_roadmap_target(
                runs_root=runs_root,
                branch=branch,
                branch_pattern=repo.branch_pattern,
                repo_root=repo.root,
                config=resolved_config,
            )
            if target.roadmap_file is None:
                withhold_tick(target.reason, target)
                return 0
            evidence = tick_evidence(
                loop_closed=True,
                test_records=[
                    record for record in state.stages if is_test_stage(record.name)
                ],
                latest_verdict=latest_verdict,
            )
            if not evidence.green:
                withhold_tick(evidence.reason, target)
                return 0
            # The loop converged, so this run's own evidence is green — but the tick is a
            # completion claim and must also agree with what the run recorded about the
            # task's Done-when (design §8.2; the rule is shared with `implement` so the two
            # ticks cannot drift, H3.3). Withheld, never failed: the recorded verdict is the
            # thing to fix, and `fix` cannot repair a build-results document it did not write.
            conclusion = roadmap.recorded_unmet_conclusion(
                repo.root,
                implementation_results_dir=(
                    resolved_config["paths.implementation_results_dir"].value
                ),
                phase=target.phase,
                task=target.task,
            )
            if conclusion is not None:
                withhold_tick(roadmap.unmet_conclusion_reason(conclusion), target)
                return 0
            spec = _tick_spec(
                target=target,
                pr=pr,
                round_index=round_index,
                # An empty converged run records `iterations == 0`; the value only names
                # the discarded loop stages of this planning call, so keep it legible.
                iteration=max(iteration, 1),
                config=resolved_config,
                aidt=aidt.root,
                repo=repo.root,
                directory=directory,
            )
            # Narrowed above: a ``None`` roadmap file returned early with its reason.
            roadmap_file = target.roadmap_file
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
                checkbox_id=target.task,
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
                selection = github.select_followups(
                    aidt.root, repo.root, pr, config=resolved_config
                )
                payload = github.parse_json_output(selection.stdout) or {}
                if selection.exit_code == github.EXIT_NONE_AVAILABLE:
                    print("child:  none available")
                elif selection.exit_code == github.EXIT_OK:
                    selected = payload.get("selected") or {}
                    print(
                        f"child:  #{selected.get('number')} {selected.get('title')} "
                        f"({selected.get('priority')})"
                    )
                    print(
                        f"children: {payload.get('childrenInspected')} inspected "
                        f"of {payload.get('totalChildren')}"
                    )
                else:
                    print(
                        f"select failed (exit {selection.exit_code}): "
                        f"{selection.stderr.strip()[:200]}",
                        file=sys.stderr,
                    )
            else:
                print("child:  unknown (`gh` not found)")
            print("select argv: " + " ".join(github.build_followup_argv(script, "select", pr)))

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
            # H3.3 req 7: the post-loop tick is planned here, in the final position, and
            # evaluates **no** evidence — a dry run never withholds and never ticks. An
            # unresolvable target (a PR that is not an AIDT task, or the chain's
            # placeholder PR 0) still shows the stage once, as the skip a real run records.
            dry_target = resolve_roadmap_target(
                runs_root=runs_root,
                branch=branch,
                branch_pattern=repo.branch_pattern,
                repo_root=repo.root,
                config=resolved_config,
            )
            if dry_target.roadmap_file is None:
                withhold_tick(dry_target.reason, dry_target)
            else:
                record = run_stage(
                    _tick_spec(
                        target=dry_target,
                        pr=pr,
                        round_index=1,
                        iteration=1,
                        config=resolved_config,
                        aidt=aidt.root,
                        repo=repo.root,
                        directory=directory,
                    ),
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
            print("gates (planned): approve-followups, approve-fix-pr")
            print(f"loop: bounded by --max-iterations={max_iterations}")
            state.status = SUCCEEDED
            save(directory, state)
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
        )
        if code is not None:
            state.status = BLOCKED if code == 3 else FAILED
            # H3.3 req 1: a stopped run records why it ticked nothing, once, with the stop
            # as the reason — then keeps its own exit code.
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

            selection = github.select_followups(
                aidt.root, repo.root, pr, config=resolved_config
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

            selected = payload.get("selected") or {}
            iterations += 1
            prefix = f"iter{iterations}"
            print(
                f"fix:    #{selected.get('number')} {selected.get('title')} "
                f"({selected.get('priority')})"
            )

            # This iteration's F1–F4, expanded from the registry once per iteration
            # (E4.3): the stage names carry the iteration count and F2/F4 carry the
            # registry-rendered context and manifest pointer. The loop is re-derived from
            # GitHub state each iteration, so nothing here is pre-planned.
            planned = _planned_iteration(
                pr=pr,
                round_index=round_index,
                iteration=iterations,
                config=resolved_config,
                aidt=aidt.root,
                repo=repo.root,
                directory=directory,
            )

            # F1 — fix exactly one approved child.
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
                    f"Fixed issue: #{selected.get('number')} {selected.get('title')}",
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
            closed_issues.append(selected)

        # --- the post-loop tick, once per run (H3.3 req 1/req 7) ------------------ #
        # The loop only reaches here through its `break` on `select` exit
        # `EXIT_NONE_AVAILABLE`, so this is the converged path: the tick is planned and —
        # on this run's green evidence — run exactly here, after the last iteration and
        # never inside it. `run_post_loop` records the skip with its own reason when the
        # target or the evidence is not good enough, which is still exit 0.
        tick_code = run_post_loop(iteration=iterations, latest_verdict=latest_verdict)
        if tick_code != 0:
            state.status = FAILED
            save(directory, state)
            return tick_code

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
