"""``aidw implement`` — implement a task prompt and open the PR (design §8.2).

Stage order follows the registry (``aidw/stage_registry.py``; the focused stages run serially,
leaving the working tree uncommitted; ``/pr`` is the single owner of the delivery step):

```
I1 impliment-task                 agent implementer (session shared)
I2 test                           agent tester      (fresh)
I3 update-traceability            agent implementer (session shared)
I4 update-architecture            agent implementer (session shared)
I5 record-implementation-results  agent recorder    (fresh)  SYNC POINT
I8 summarize-implementation-results agent recorder  (fresh)  read-only summary
I9 write-integration-test-guide   agent recorder    (fresh)  human-run guide, runs nothing
I7 update-roadmap                 agent recorder    (fresh)  one checkbox, verified
◇  approve-implementation-pr
I6 pr                             agent pr-publisher (fresh)
…  any repo-added stages the repo declared before / after I6 (E4.5b)
```

``--parallel`` runs the target config's ``workflows.implement.parallel_groups``
(EXTRACTION.md §3.4/§3.5, R11): each group's members run concurrently at the position of
the group's earliest member, every non-member keeps registry order, and the registry
default is the one pair known to be safe — ``I2 test`` and ``I4 update-architecture``,
which touch disjoint trees. Without ``--parallel``, or with a declared
``parallel_groups: []``, every stage runs serially. The effective groups are validated in
the preflight (§3.5: every member exists and is not ordered against another member); an
invalid list is a config refusal (stderr + exit 2) before any run record or worktree.

I7 (H3.1) is the roadmap tick: a **core** stage that resolves its one entry itself, from the
configured ``paths.roadmap_dir``/``paths.roadmap_glob`` **after** the worktree locate (D15/D17;
the control root is the wrong tree for a chain invocation, design K1), and renders the entry's
own absolute file and its task id into the stage. A count other than exactly one refuses with
exit 2 before the stage runs, and the workflow re-reads the file afterwards: exactly the target
line may flip `- [ ]` -> `- [x]`, every other byte must be unchanged, and an already-`[x]` entry
is a successful no-op recorded as `tick: already`. The edit stays uncommitted — I6 commits it,
so the tick lands in the task's own PR.

Since H3.2 the tick is also **conditional on the run's own evidence**: I7's registry entry
carries `when=WHEN_EVIDENCE_GREEN`, and the workflow evaluates it itself, before
`run_stage` is ever invoked and on both dispatch paths (serial and a `--parallel` group
member). The condition is green iff the tree the tick edits has a content identity, at least
one recorded `gate_outcomes` row is for exactly that tree, and every such row passed —
computed with `aidw.verification.tree_identity`'s default base and with the four resolved
document write-targets as its `--ignore` scope, exactly as `aidw gate run` computed the
evidence it cites. Anything else (a red gate, no matching outcome, an identity that cannot
be computed) withholds the stage: it is recorded `skipped` with a reason naming the failing
gates or the absence, the roadmap file is never touched, the run's exit status is unchanged,
and no agent ever got the chance to make the claim. An already-`[x]` entry under green
evidence is still H3.1's successful no-op.

Since S1.1 `I3 update-traceability` is the first **path-scoped** stage: its registry entry
carries `when=WHEN_PATHS_CHANGED`, and a repo declares the paths it owns as the per-stage
`when_paths` list (repo-relative prefixes). The workflow evaluates the token in the same
two dispatch points as H3.2's evidence check and with the same change set I7 measures
(`git.changed_paths` against `BASE_DEFAULT` plus untracked paths, state root excluded);
when the change set touches none of the declared prefixes the stage is recorded `skipped`
with the prefixes in its reason and no agent is invoked. An **undeclared/empty**
`when_paths` is the toolkit default and means "unconditional" — today's behaviour — and an
unresolvable change set runs the stage rather than skipping it. The decision is
`paths_changed_reason` (pure); the I/O is `change_set_paths`.

X1.1 adds `I8` (design §8.2, §17 Z3): a read-only narration of what `I5` recorded. It runs
no verification gate and re-runs no command — `I5` remains the single owner of the whole-repo
gate, so a second run here would double the run's most expensive step for no new evidence —
and it edits nothing but `<implementation_results_dir>/<branch>/summary.md`, uncommitted for
`I6`. Its five-section narrative structure lives in the prompt, not in config.

X1.2 adds `I9` (design §8.2, §17 Z6): the integration-test **guide**, immediately after the
summary and before the tick. It reads the build results, the task prompt and the branch's
changed files through read-only `git`, and writes
`<implementation_results_dir>/<branch>/integration-test-guide.md` — the step-by-step procedure
a human follows to integration-test the change by hand. It **executes nothing**: no
integration test, no gate, no cloud, browser or deployed-stack command, so §1.3's
deployed-integration-tests non-goal still holds (AIDT writes the recipe, a human runs it).
Core and unconditional like `I8` (no `when=` token), serial between `I8` and `I7`, never in a
`parallel_group`, and its four-section structure and five per-scenario fields live in the
prompt, not in config.

Q1.1 adds the **I2 verdict gate** (design §8.2, §17 Z10): a `test` stage that reports an
in-scope `Fail` exits 0 and stays `SUCCEEDED`, so its failure lives in the final *message*, not
in the stage status. The workflow parses a bare `Test verdict: Pass|Fail` declaration (plus, on
`Fail`, a following `Failing in-scope criteria:` line) from the recorded I2 `out.txt` with
:func:`_parse_test_verdict` — fenced blocks blanked and code-span/heading lines rejected, the
same prose-only discipline `aidw.verdict` records (M1/M3, design §18) — after the pre-PR stages
and **before** the `approve-implementation-pr` gate, so `I6 pr` never opens a PR for a failing
in-scope criterion. `Fail` and an unparseable verdict (including a missing or empty recorded
message) each stop the run `BLOCKED` with exit 3, mirroring `review.py`'s ambiguous verdict; a
`Pass` proceeds unchanged. `Unverified`, out-of-scope and pre-existing failures stay in the
tester's per-criterion report and never make the verdict `Fail`.

The nine stages are not hardcoded here since E4.3: ``run()`` builds them with
:func:`aidw.runner.plan_stages` over the ``aidw.stage_registry`` defaults, so the target
repo's per-stage ``prompt:`` overlay applies and the prompts resolve against the located
worktree (EXTRACTION.md §3.5, D2/D14). The target config's two fail-closed preflight
refusals run first, sharing :func:`aidw.target_config.resolve_workflow_config` with the
other four workflows. The same preflight validates a **declared**
``workflows.implement.stages`` list (E4.5a, D12/D13): disabling, removing or reordering a
core stage is one ``ERROR`` per violation (stderr + exit 2, before any run record or
worktree), while a repo-optional ``enabled: false`` and a repo-added stage are accepted.

Branch setup is a Python stage: ``run()`` derives the branch/worktree name from
``repo.branch_pattern`` and **locates** the existing worktree (``git.worktree_for_branch``,
EXTRACTION.md §3.2) — ``aidw prompt`` (E2.5) is what creates it and commits the task
prompt inside it. When the worktree is missing, ``run()`` prints the exact ``worktree
add`` command and refuses (exit 4, design §14) without creating anything. The located
worktree is re-resolved into the target and agents so every stage runs in it. It no
longer refuses to run on ``main`` or on a branch that does not match the task id, but
still refuses when another implement run for the branch is marked ``running`` unless
``--resume``.

The run lock (``aidw.lock``, EXTRACTION.md §3.2/§3.10) is keyed on the **located
worktree path**, acquired immediately before ``create_run`` and released on every exit
path (success, stage/gate failure, and the post-acquire refusals). A live peer in the
same worktree is refused with exit 4 and writes no run state. ``--dry-run`` reaches
``create_run`` too, so it holds and releases the same lock.
"""

from __future__ import annotations

import json
import os
import re
import string
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path

from aidw import __version__, git, lock, roadmap, verification
from aidw import stage_registry
from aidw.config import ERROR, WARNING, format_issues, load_all
from aidw.gates import decide
from aidw.log import NullLogger, RunLogger
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.report import print_stage
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
    GateOutcome,
    GateRecord,
    RunState,
    StageRecord,
    PLANNED_RUN_DIR_TEXT,
    create_run,
    list_runs,
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

GATE = "approve-implementation-pr"

#: The resolved §3.4 path of the config-driven parallel groups (R11/E4.4).
PARALLEL_GROUPS_PATH = "workflows.implement.parallel_groups"

#: The resolved §3.4 path of the declared stage list (D12/D13, E4.5a).
STAGES_PATH = "workflows.implement.stages"

#: The roadmap-tick stage's registry **name** (H3.1). Located by name, not id: a declared
#: stage list may carry repo-added stages, and the tick's postcondition attaches to this
#: stage wherever it was declared.
TICK_STAGE_NAME = "update-roadmap"

#: ``StageRecord.artifacts`` key carrying the tick outcome (H3.1 req 7; additive).
TICK_ARTIFACT_KEY = "tick"

#: The resolved §3.4 **document write-targets** whose edits are never evidence about the
#: tree the tick is judged against (H3.2 req 3). Every other stage of this workflow writes
#: into one of them, and the tick's own edit lands in ``roadmap_dir`` — so a tree identity
#: that included them would (a) differ from the ones ``aidw gate run`` recorded, because the
#: prompts pass the same scope as ``--ignore``, and (b) make the tick's own edit part of the
#: evidence checked against it. Prompt-fixed to the canonical scope ``prompts/pr.md`` and
#: ``prompts/record-implementation-results.md`` declare.
TICK_EVIDENCE_IGNORE_PATHS = (
    "paths.implementation_results_dir",
    "paths.architecture_dir",
    "paths.roadmap_dir",
    "paths.task_prompts_dir",
)

#: Why a tick is withheld when the change set has no tree identity. ``tree_identity``
#: returns ``None`` for an unresolvable base branch or an over-budget change set, and
#: "cannot prove" is never "green" (E4.8 is cite-or-run, never assume).
TICK_NO_TREE_REASON = (
    "no evidence: the change set has no tree identity (the base branch could not be "
    "resolved, or the change set is over budget), so no recorded gate outcome can "
    "cite it"
)

#: ``03-E4.1-prompt.md`` → phase ``03``, task ``E4.1``, branch ``03-E4.1``.
_PROMPT_NAME = re.compile(
    r"^(?P<phase>[0-9]+(?:\.[0-9]+)?)-(?P<task>.+?)(?:-prompt)?\.md$"
)

_PR_URL = re.compile(r"https?://\S*/pull/(\d+)")


def worktree_add_command(
    workspace: WorkspacePaths, branch: str, base_branch: str
) -> str:
    """The copy-pasteable §3.2 per-task worktree command (E2.6 req 4).

    Prompt-fixed to §3.2's per-task command with ``base_branch`` substituted for the
    literal ``main``: ``-C`` points at the base-branch worktree, so the new worktree is
    linked off the configured base. ``workspace.workspace_root`` is absolute, so every
    path in the returned string is absolute and the line can be pasted as-is.
    """
    root = workspace.workspace_root
    return (
        f"git -C {root / base_branch} worktree add -b {branch} "
        f"{root / branch} {base_branch}"
    )


def _resolve_prompt_argument(
    task_prompt_path: Path, control_root: Path, worktree_root: Path
) -> tuple[Path, str] | None:
    """Resolve the task-prompt argument inside the task worktree (E2.6 req 2).

    Returns ``(prompt_path, prompt_rel)`` where ``prompt_rel`` is the repo-relative
    subpath used by I1 and I5, or ``None`` when an absolute argument lives inside
    neither the control root nor the worktree (a usage error). Three argument shapes:

    * relative — a repo-relative subpath, resolved against ``worktree_root`` (never the
      control root or the cwd);
    * absolute under the control root — re-based by its repo-relative subpath;
    * absolute under the worktree root — resolved as-is (what the chain hands over).

    Pure apart from ``Path.resolve`` on the arguments; no file existence check here
    (the caller owns the real-run-only ``is_file`` refusal).
    """
    raw = Path(task_prompt_path)
    if not raw.is_absolute():
        rel = Path(os.path.normpath(raw))
        candidate = (worktree_root / rel).resolve()
        try:
            candidate.relative_to(worktree_root.resolve())
        except ValueError:
            return None
        return candidate, rel.as_posix()
    resolved = raw.resolve()
    control = control_root.resolve()
    worktree = worktree_root.resolve()
    try:
        rel = resolved.relative_to(control)
    except ValueError:
        pass
    else:
        return (worktree / rel).resolve(), rel.as_posix()
    try:
        rel = resolved.relative_to(worktree)
    except ValueError:
        return None
    return resolved, rel.as_posix()


def parse_task_id(prompt_path: Path) -> tuple[str, str, str] | None:
    """Derive ``(phase, task, task_id)`` from a task-prompt filename.

    Pure: one argument, no I/O. The third element is the task id ``f"{phase}-{task}"``;
    the *branch* name is ``repo.branch_pattern`` applied to it by :func:`run`. Accepts the
    canonical ``<phase>-<task>-prompt.md`` and the bare ``<phase>-<task>.md`` an author
    model may produce. Returns ``None`` when the filename carries no task id.
    """
    match = _PROMPT_NAME.match(prompt_path.name)
    if not match:
        return None
    phase = match.group("phase")
    task = match.group("task")
    return phase, task, f"{phase}-{task}"


def _branch_pattern_fields(pattern: str) -> set[str]:
    """Top-level replacement field names referenced by ``pattern``.

    ``string.Formatter().parse`` lets :func:`derive_branch_name` check "mentions both
    ``phase`` and ``task``" without formatting, and never raises on an arbitrary
    placeholder (unlike ``str.format``, which would). ````phase.foo```` / ``task[0]``
    still reference ``phase`` / ``task``.
    """
    fields: set[str] = set()
    for _literal, field_name, _spec, _conversion in string.Formatter().parse(pattern):
        if field_name:
            fields.add(re.split(r"[.\[]", field_name, maxsplit=1)[0])
    return fields


def derive_branch_name(pattern: str, *, phase: str, task: str) -> str | None:
    """Apply ``repo.branch_pattern`` to a task id (EXTRACTION.md §3.4), or ``None``.

    ``None`` means the pattern is malformed — ``str.format`` cannot apply it (unknown
    placeholder, unbalanced braces) or it does not reference both ``phase`` and
    ``task`` (a constant/partial name would collide across tasks; §3.2 one branch, one
    worktree). The caller turns ``None`` into a usage error (exit 2) before any worktree
    or stage. Under the §3.4 default this reproduces the old names byte-for-byte.
    """
    try:
        fields = _branch_pattern_fields(pattern)
    except ValueError:
        # Unbalanced braces; ``str.format`` would raise the same.
        return None
    if not {"phase", "task"} <= fields:
        return None
    try:
        return pattern.format(phase=phase, task=task)
    except (KeyError, IndexError, ValueError):
        return None


@dataclass(frozen=True)
class TickEvidence:
    """The verdict on I7's ``WHEN_EVIDENCE_GREEN`` condition (H3.2 req 3).

    ``tree`` is the content-tree identity the condition was evaluated for, or ``None``
    when it could not be computed. ``reason`` is the human-readable explanation carried by
    a skipped stage; it is empty exactly when ``green`` is true, so a green verdict can
    never be paired with a reason somebody might print as one.
    """

    green: bool
    tree: str | None
    reason: str


def tick_evidence(
    outcomes: Sequence[GateOutcome], tree: str | None
) -> TickEvidence:
    """**The rule**: is the tick's tree covered by green evidence? (H3.2, design §8.2).

    Green iff (a) the tree has an identity, (b) at least one recorded gate outcome is for
    exactly that tree, and (c) **every** such outcome passed. Anything else withholds the
    tick, and the reason says which:

    * ``tree is None`` — no identity, so no outcome can cite it (a ``None`` identity is
      also what an unresolvable base branch and an over-budget change set produce);
    * no matching outcome — "no evidence" is not "green" (E4.8 is cite-or-run, never
      assume), and a run whose gates recorded nothing has nothing to cite;
    * any non-``passed`` outcome — the red gate the roadmap's E6.1 incident exists for,
      named per failing ``GateOutcome.key`` so one line says *which* gate said no.

    Outcomes recorded for a **different** tree are ignored in both directions: another
    tree's pass is not evidence for this one, and another tree's failure is not this run's
    verdict (design §9.2 — the identity is the whole point of recording it).

    Pure: no I/O, no mutation of ``outcomes``, and the returned value is a frozen value.
    """
    if tree is None:
        return TickEvidence(False, None, TICK_NO_TREE_REASON)
    matching = [outcome for outcome in outcomes if outcome.tree == tree]
    if not matching:
        return TickEvidence(
            False,
            tree,
            f"no evidence for tree {tree}: no gate outcome is recorded for it "
            "(cite-or-run, never assume)",
        )
    failing = [outcome for outcome in matching if not outcome.passed]
    if failing:
        # Every failing key, once, in recorded order: the operator must not have to guess
        # which gate said no, and two failures of one key are still one key to fix.
        keys = list(dict.fromkeys(outcome.key for outcome in failing))
        label = "gate" if len(keys) == 1 else "gates"
        return TickEvidence(
            False, tree, f"red {label} for tree {tree}: {', '.join(keys)}"
        )
    return TickEvidence(True, tree, "")


def tick_evidence_ignore(
    resolved_config: ResolvedConfig, repo_root: Path
) -> tuple[str, ...]:
    """The four resolved document write-targets as ``--ignore`` prefixes (H3.2 req 3).

    ``paths.*`` values are target-relative by default and may be absolute, while
    ``tree_identity``'s ``ignore`` (and ``aidw gate run``'s ``--ignore``) take
    **repo-relative** prefixes — so an absolute value inside the tree is re-based, and one
    outside the tree is dropped (it cannot be a prefix of any path in the tree).
    Canonicalisation is :func:`aidw.verification.normalise_ignore`, the same rule the gate
    CLI applies, so the identity computed here matches the one the gate recorded instead
    of a lookalike.
    """
    root = Path(repo_root).resolve()
    prefixes: list[str] = []
    for path in TICK_EVIDENCE_IGNORE_PATHS:
        value = resolved_config[path].value
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = Path(value)
        if candidate.is_absolute():
            try:
                relative = candidate.resolve().relative_to(root)
            except ValueError:
                continue
            prefixes.append(relative.as_posix())
            continue
        text = os.path.normpath(value).replace(os.sep, "/")
        # ``.``/``..`` would ignore the whole repository; ``normalise_ignore`` refuses them
        # (that would make every tree identical), so a pathological config scope empties
        # rather than crashing the run — and an emptied scope only ever *withholds* a tick.
        if text in ("", ".", "..") or text.startswith("../"):
            continue
        prefixes.append(text)
    return verification.normalise_ignore(prefixes)


def roadmap_tick_evidence(
    state: RunState,
    *,
    repo_root: Path,
    exclude: Sequence[Path],
    ignore: Sequence[str],
) -> TickEvidence:
    """I7's condition: this run's recorded outcomes against the **current** tree (H3.2).

    The tree is recomputed the way ``aidw gate run`` computed the ones it recorded:
    :func:`aidw.verification.tree_identity` with its **default** ``base``
    (``verification.BASE_DEFAULT``). Never ``repo.base_branch``: the prompts pass no
    ``--base`` to ``aidw gate run``, so every recorded outcome is measured against the
    default, and a different base would match nothing and silently never tick.

    ``exclude`` is the run's state root (the gate CLI's own exclusion — the run's logs are
    not part of the change set) and ``ignore`` is :func:`tick_evidence_ignore`'s scope, so
    the recomputed identity equals the one the gate recorded rather than a lookalike that
    matches nothing.

    Reads the **in-memory** run state, which is where H0.1's merge-on-write has already
    folded in every outcome a stage's ``aidw gate run`` subprocess appended; a fresh
    ``state.load`` or a ``run.log`` parse would re-introduce exactly the boundary loss H0.1
    closed. I/O: one ``git`` change-set read plus the content hashes.
    """
    tree = verification.tree_identity(repo_root, exclude=exclude, ignore=ignore)
    return tick_evidence(state.gate_outcomes, tree)


def _declared_prefixes(declared: Sequence[str]) -> tuple[str, ...]:
    """A stage's declared ``when_paths`` as canonical prefixes, or ``()`` when unusable.

    :func:`aidw.verification.normalise_ignore` is the one rule for "a repo-relative
    prefix", so the matcher reuses it rather than restating it (S1.1 req 7). The loader
    has already refused a bad entry on the config path (req 3); a plain dict handed to
    :func:`aidw.runner.plan_stages` directly can still carry one, and an unusable
    declaration fails closed the only way a **cost-control** skip may: by running the
    stage.
    """
    values = [value for value in declared if isinstance(value, str) and value.strip()]
    if not values:
        return ()
    try:
        return verification.normalise_ignore(values)
    except ValueError:
        return ()


def paths_changed_reason(
    changed: Sequence[str] | None, declared: Sequence[str]
) -> str | None:
    """**The rule**: withhold a ``WHEN_PATHS_CHANGED`` stage? (S1.1, design §8.2).

    Returns the skip reason when the stage has nothing to do, and ``None`` when it runs.
    It runs — never skips — in all three of these cases, each for its own reason:

    * the declaration is empty (or unusable): an undeclared path set is the toolkit
      default and means "unconditional", which is exactly what I3 did before this token;
    * ``changed is None``: the change set could not be computed (an unresolvable base), so
      "cannot prove the stage is irrelevant" is never "skip" — the fail-closed direction
      is running a stage that may be unnecessary, not dropping one that may be needed;
    * some changed path **touches** a declared prefix: ``path == prefix or
      path.startswith(prefix + "/")``, the same rule ``verification._excluded`` applies
      to a gate's declared scope, so ``docs/x`` matches the file and everything under the
      directory but never the sibling ``docs/xy``.

    Pure: no I/O, no mutation of ``changed``/``declared``, and the returned reason is a
    freshly built string.
    """
    prefixes = _declared_prefixes(declared)
    if not prefixes:
        return None
    if changed is None:
        return None
    if any(verification._excluded(path, prefixes) for path in changed):
        return None
    return (
        "no changed path matches the declared when_paths "
        f"({', '.join(prefixes)}): the change set does not touch any of them"
    )


def change_set_paths(
    repo_root: Path, *, exclude: Sequence[Path] = ()
) -> list[str] | None:
    """The change set I7's evidence already measures against (S1.1 req 6, design §8.2).

    ``git.changed_paths`` against :data:`aidw.verification.BASE_DEFAULT` — never
    ``repo.base_branch``: the prompts pass no ``--base`` to ``aidw gate run``, so a
    different base would silently always- or never-skip — plus every untracked path, with
    ``exclude`` removed exactly as :func:`aidw.verification.tree_identity` removes its own
    ``exclude`` (the run's state root: the run's logs are not a change a stage could have to
    trace). ``verification._relative_prefixes``/``_excluded`` are reused rather than
    restated, so this exclusion is the gate's own rule.

    ``None`` **only** when ``changed_paths`` could not resolve the base; an empty list is a
    real answer ("no changes") and does skip. I/O: three read-only ``git`` invocations.
    """
    changed = git.changed_paths(repo_root, verification.BASE_DEFAULT)
    if changed is None:
        return None
    prefixes = verification._relative_prefixes(repo_root, exclude)
    return sorted(
        path
        for path in (*changed, *git.untracked_paths(repo_root))
        if not verification._excluded(path, prefixes)
    )


def build_plan(
    *,
    aidt: Path,
    prompt_rel: str,
    branch: str,
    task_id: str,
    base_branch: str = "main",
    roadmap_file: str,
    checkbox_id: str,
) -> list[stage_registry.PlannedStage]:
    """The eight stages, in order, exactly as the registry expands them (compat wrapper).

    ``base_branch`` is I4's ``$2`` (``base_ref``): the architecture stage measures
    against the configured PR base, not a hardcoded ``main`` (EXTRACTION.md §3.4/R4).

    Since E4.3 this is a thin wrapper over :func:`aidw.stage_registry.expand`, kept for the
    one caller that needs only the stage **names** before the target config is resolved and
    the prompt located (``run``'s ``--from`` validation). It is deliberately *not* on the
    ``implement`` run path: ``run`` builds its stages with
    :func:`aidw.runner.plan_stages`, so a repo's ``prompt:`` override (D14) applies and the
    prompts resolve against the target repo rather than the toolkit unconditionally.
    ``aidt`` is accepted and unused now that the plan carries prompt *names*: keeping it
    keeps every existing call site (and its ``aidt=`` argument) working.

    ``roadmap_file``/``checkbox_id`` are I7's ``$1``/``$2`` (H3.1). ``expand`` renders every
    stage from one field mapping, so a field the mapping lacks raises ``StageFieldError`` on
    the first render; the pre-locate caller passes safe placeholders (see ``run``'s ``--from``
    validation), because it reads only the stage names (H3.1 req 6).
    """
    return list(
        stage_registry.expand(
            "implement",
            prompt_rel=prompt_rel,
            branch=branch,
            task_id=task_id,
            base_branch=base_branch,
            roadmap_file=roadmap_file,
            checkbox_id=checkbox_id,
        )
    )


def settle_roadmap_tick(
    record: StageRecord,
    *,
    checkbox_id: str,
    roadmap_file: Path,
    before: str,
    logger: RunLogger,
    state: RunState,
    directory: Path,
) -> None:
    """Verify I7's byte-exact postcondition and record which outcome happened (H3.1 req 7).

    The agent's exit 0 is not evidence the write happened (design §10, the O1 precedent), so
    the workflow re-reads the file the stage actually edited and applies
    :func:`aidw.roadmap.verify_checkbox_flip` — exactly the target line ``- [ ]`` ->
    ``- [x]``, every other byte unchanged; an already-``[x]`` file is a successful no-op.
    Everything else (a neighbour edit, a reflow, a vanished or duplicated entry, an
    unreadable file) marks the stage ``failed`` with the reason, which the caller's normal
    failure path then reports and stops on.

    The outcome is pinned observably without a transcript: ``artifacts["tick"]`` is
    ``flipped``/``already`` on the record and one ``run.log`` line names the checkbox and the
    outcome. ``already`` stays ``succeeded`` — ``skipped`` is H3.2's word for a tick
    withheld behind red gates — and ``error`` stays unset on both successful paths. The
    state is saved here because ``run_stage`` already published its own record before this
    workflow-owned check runs. Mutates only ``record`` (and the run state it persists).

    Shared with ``fix`` since H3.3: ``fix``'s post-loop tick runs the same ``I7`` stage and
    applies the same byte-exact rule, so the two workflows cannot disagree about what a
    legal flip is. ``implement`` calls it ``settle_tick``; ``fix`` calls the same function.
    """
    if record.exit_code not in (None, 0):
        record.status = FAILED
        record.error = (
            "roadmap tick stage exited non-zero "
            f"({record.exit_code}); postcondition cannot claim success"
        )
        logger.warn(f"stage {record.name}: {record.error}")
        save(directory, state)
        return

    try:
        after = roadmap_file.read_text(encoding="utf-8")
        outcome = roadmap.verify_checkbox_flip(before, after, checkbox_id=checkbox_id)
    except (OSError, roadmap.RoadmapTickError) as exc:
        record.status = FAILED
        record.error = f"roadmap tick postcondition not met: {exc}"
        logger.warn(f"stage {record.name}: {record.error}")
    else:
        record.artifacts[TICK_ARTIFACT_KEY] = outcome
        if outcome == roadmap.TICK_ALREADY:
            logger.info(f"roadmap {checkbox_id}: already `[x]`, file unchanged")
        else:
            logger.info(f"roadmap {checkbox_id}: flipped `[ ]` -> `[x]`")
    save(directory, state)


#: Pre-H3.3 spelling of :func:`settle_roadmap_tick`, kept as an alias because
#: ``tests/test_roadmap_tick.py`` pins the helper under this (private) name. The function
#: itself is public since H3.3 so ``fix`` imports the one flip rule instead of duplicating
#: it — the tick's postcondition must not exist twice.
_settle_roadmap_tick = settle_roadmap_tick


#: The registry **name** of I2, whose final message carries the tester's verdict block
#: (Q1.1, design §8.2). Matched by name — never by position — so a repo-declared stage list
#: (`workflows.implement.stages`) cannot move the stage the gate reads.
TEST_STAGE_NAME = "test"

#: The two verdict tokens the tester declares (Q1.1; prompt-fixed by `prompts/test.md`,
#: because §8.2 names none). Case is load-bearing: only the capitalised token parses, so a
#: lowercase `pass`/`fail` mention in prose can never be read as a declaration.
PASS = "Pass"
FAIL = "Fail"

#: `state.pr` keys recording I2's parsed verdict (Q1.1; additive at the same
#: `schema_version`, design §9.2). `test_verdict` is always written by the gate — `None` for
#: an unreadable verdict, so "no verdict parsed" is distinguishable from "never reached".
TEST_VERDICT_KEY = "test_verdict"
TEST_FAILING_CRITERIA_KEY = "test_failing_criteria"

#: The forward path every Q1.1 stop message must name (design §8.2's resume rule, §9.4). A
#: plain `--resume` skips the already-`SUCCEEDED` I2 (`should_run`) and re-reads the *same*
#: recorded verdict, so it repeats the stop identically — correct while the verdict is
#: unchanged, not "stuck". Re-testing therefore needs `--from test`, which overrides §9.4's
#: completed-stages-never-rerun rule; `--resume` keeps the same run.
TEST_VERDICT_RESUME_HINT = (
    "A plain `--resume` skips the already-SUCCEEDED I2 and re-reads this same recorded "
    "verdict, so it stops here again while the verdict is unchanged (a repeat-stop, not a "
    "stuck run). To re-test, run `aidw implement <task-prompt> --resume --from test`."
)

#: The bare declaration line (Q1.1 req 2/4): the label, a colon, exactly one capitalised
#: token and nothing else on the line. Anchored, so a heading (`## Test verdict: Fail`), a
#: code span (`` `Test verdict: Fail` ``) or a sentence that *mentions* the declaration is
#: never a declaration — `verdict.py`'s M1/M3 lesson, specialised to a token that needs no
#: prose fallback because there is exactly one place this verdict is stated.
_TEST_VERDICT_RE = re.compile(
    rf"^[ \t]*Test verdict:[ \t]*(?P<verdict>{PASS}|{FAIL})[ \t]*\r?$", re.MULTILINE
)

#: The criteria line a `Fail` declaration is followed by. Read **best-effort**: a `Fail`
#: without it is still `Fail` (the list only names what to re-test), so a missing line never
#: turns a definite failure into an "ambiguous" stop.
_TEST_CRITERIA_RE = re.compile(
    r"^[ \t]*Failing in-scope criteria:[ \t]*(?P<criteria>[^\n]*)$", re.MULTILINE
)

#: Fenced code blocks quote the required shape (`prompts/test.md`'s own per-criterion
#: template) or an example; they are never the tester's own conclusion (M1, design §18).
_TEST_FENCE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)

#: Markdown decoration (and a CRLF's carriage return) stripped from each criterion, so the
#: recorded list holds the tester's wording rather than its emphasis markers.
_CRITERION_DECORATION = " \t\r`*_\u201c\u201d\"'"


def _read_out(record) -> str | None:
    out = record.artifacts.get("out")
    if out and Path(out).is_file():
        return Path(out).read_text(encoding="utf-8")
    return None


def _blank_test_fences(text: str) -> str:
    """``text`` with fenced code blocks blanked, offsets and line starts preserved (M1)."""
    return _TEST_FENCE_RE.sub(
        lambda match: re.sub(r"[^\n]", " ", match.group(0)), text
    )


def _failing_criteria(prose: str, start: int) -> list[str]:
    """The criteria named on the first ``Failing in-scope criteria:`` line after ``start``.

    Returns ``[]`` when the tester named none: the verdict is still `Fail`, and the criteria
    are only the wording a human needs to re-test (Q1.1 req 5).
    """
    for match in _TEST_CRITERIA_RE.finditer(prose, start):
        items = (
            item.strip(_CRITERION_DECORATION)
            for item in match.group("criteria").split(",")
        )
        return [item for item in items if item]
    return []


def _parse_test_verdict(text: str) -> tuple[str, list[str]] | None:
    """Parse I2's verdict block (Q1.1; design §8.2, §17 Z10). Pure.

    Returns ``(PASS, [])``, ``(FAIL, [criteria...])``, or ``None`` when no declaration line
    parses. Fenced code blocks are blanked first, because `prompts/test.md` shows the block
    as a template inside a fence and a naive read would take the *example* for the verdict
    (design §18's M1 lesson, E4.5b). A code-span declaration (`` `Test verdict: Fail` ``) is
    rejected by the same anchoring: only a bare line is a declaration, while
    `verdict.py`'s `DECLARATION_RE` deliberately *accepts* backticked tokens for a label that
    carries its own meaning — this label does not, so prose must not supply it.

    No I/O, no mutation, no state: every workflow decision about I2 is derived from the text
    it is handed. When several declarations parse, the **last** wins, mirroring
    `verdict.parse_verdict`'s declaration pass: a report's conclusion is its final word.
    """
    prose = _blank_test_fences(text)
    declarations = list(_TEST_VERDICT_RE.finditer(prose))
    if not declarations:
        return None
    declaration = declarations[-1]
    verdict = declaration.group("verdict")
    if verdict == PASS:
        return (PASS, [])
    return (FAIL, _failing_criteria(prose, declaration.end()))


def _test_verdict_ambiguity(record: StageRecord | None, text: str | None) -> str:
    """Why I2's verdict could not be read, named for the operator (Q1.1 req 5).

    A missing record and an empty message are distinct failures — a resumed run can carry a
    `SUCCEEDED` `test` record whose `out.txt` is gone, and a fresh run whose I2 exhausted the
    U1 retry records a successful stage with an empty final message (H1.1: `runner.py` leaves
    the empty-final-message case to the workflow) — and both fail closed here.
    """
    if record is None:
        return "no recorded `test` stage to read"
    if text is None:
        return "the recorded `test` stage has no readable out.txt"
    if not text.strip():
        return "the recorded `test` final message is empty"
    return (
        "no bare `Test verdict: Pass|Fail` declaration line parses from the recorded "
        "final message"
    )


def _test_verdict_stop(
    state: RunState, directory: Path, logger: RunLogger
) -> int | None:
    """Withhold I6 unless the tester's in-scope verdict is `Pass` (Q1.1, design §8.2).

    The verdict is in I2's **message**, not its stage status: the tester exits 0 and reports
    an in-scope `Fail` in prose, so a `record.status == SUCCEEDED` check would let the failure
    through. The message is read from the *recorded* stage through :func:`_read_out`, so a
    resumed run (whose I2 is skipped as already-`SUCCEEDED`) reaches the same decision as a
    fresh one — the flip side is that a plain `--resume` re-reads the same verdict and stops
    again, which :data:`TEST_VERDICT_RESUME_HINT` states rather than leaving as a dead end.

    Returns the exit code to stop with (3, `state.status = BLOCKED`) or ``None`` to continue
    to the approve gate and I6. Both stop paths write `state.pr` before returning, so the
    decision is recorded even though the run ends here.
    """
    record = state.stage(TEST_STAGE_NAME)
    text = _read_out(record) if record is not None else None
    parsed = _parse_test_verdict(text) if text is not None else None

    if parsed is None:
        reason = _test_verdict_ambiguity(record, text)
        state.pr[TEST_VERDICT_KEY] = None
        state.status = BLOCKED
        save(directory, state)
        logger.warn(f"test verdict: unreadable ({reason}); withholding I6 pr")
        print(
            f"test verdict gate: cannot read I2's verdict — {reason}; failing closed "
            "with state.status = BLOCKED and no PR opened.",
            file=sys.stderr,
        )
        print(TEST_VERDICT_RESUME_HINT, file=sys.stderr)
        return 3

    verdict, criteria = parsed
    state.pr[TEST_VERDICT_KEY] = verdict
    if verdict == PASS:
        save(directory, state)
        logger.info("test verdict: Pass; I6 pr may run")
        print(f"test verdict: {PASS}")
        return None

    state.pr[TEST_FAILING_CRITERIA_KEY] = criteria
    state.status = BLOCKED
    save(directory, state)
    named = ", ".join(criteria)
    logger.warn(
        f"test verdict: Fail ({named or 'criteria not named'}); withholding I6 pr"
    )
    print(
        "test verdict gate: I2 test reported `Fail` for in-scope criteria: "
        f"{named or '(the message names no `Failing in-scope criteria:` line)'}",
        file=sys.stderr,
    )
    print(
        "no PR opened: `I6 pr` is withheld, so this run opens no pull request.",
        file=sys.stderr,
    )
    print(TEST_VERDICT_RESUME_HINT, file=sys.stderr)
    return 3


def _latest_implement_run(runs_root: Path, branch: str) -> RunState | None:
    matches = [
        state
        for state in list_runs(runs_root)
        if state.workflow == "implement" and state.git.get("branch") == branch
    ]
    return matches[-1] if matches else None


def effective_parallel_groups(
    config: ResolvedConfig | None,
) -> tuple[tuple[str, ...], ...]:
    """The groups ``--parallel`` schedules: the repo's declared list, else the default (E4.4).

    Declared-ness decides, never value equality (matching :func:`resolve_config`'s
    whole-list semantics): a config that declares ``parallel_groups: []`` resolves with
    ``source == "config"`` and means "no parallel groups" — serial, never a fallback to
    the default. When the config did not declare the list the entry is **absent** from the
    resolved config (not an ``unset`` entry), and the registry default (E4.1's
    ``(('test', 'update-architecture'),)``) applies. Members are stage *names* (R6/R11),
    which is what the ``by_name``/``index_of`` lookups below key on.

    Pure; ``config`` is ``None`` only for a caller that has not resolved one — the
    preflight refuses before that can happen — and then the registry default is used.
    """
    entry = None if config is None else config.get(PARALLEL_GROUPS_PATH)
    if entry is None or entry.source != SOURCE_CONFIG:
        return stage_registry.get_workflow("implement").parallel_groups
    return tuple(tuple(group) for group in (entry.value or []))


def _confirm_resume(assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return True
    try:
        answer = input("Resume this implement run? [y/N] ").strip().lower()
    except EOFError:
        return True
    return answer in ("y", "yes")


def _print_completed(state: RunState) -> None:
    for record in state.stages:
        print(f"  {record.name}: {record.status}")


def _gate_summary(state: RunState, repo: TargetRepo, branch: str, prompt_rel: str) -> str:
    lines = [f"Implementation for {branch}", f"Task prompt: {prompt_rel}", ""]
    for record in state.stages:
        lines.append(f"  {record.name}: {record.status} ({record.agent}, {record.model})")
    files = git.changed_files(repo.root, repo.base_branch)
    if files:
        lines.append("")
        lines.append(f"Changed files ({len(files)}):")
        lines.extend(f"  {name}" for name in files[:50])
    return "\n".join(lines)


def _record_pr(state: RunState, repo: TargetRepo, record) -> None:
    text = _read_out(record) or ""
    match = _PR_URL.search(text)
    if match:
        state.pr = {**state.pr, "number": int(match.group(1)), "url": match.group(0)}
    state.pr["changed_files"] = git.changed_files(repo.root, repo.base_branch)


def _write_artifacts(directory: Path, state: RunState, branch: str) -> Path:
    artifacts_dir = directory / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "branch": branch,
        "pr_number": state.pr.get("number"),
        "pr_url": state.pr.get("url"),
        "build_results_path": f"docs/implementation-results/{branch}/build-results.md",
        "changed_files": state.pr.get("changed_files", []),
    }
    path = artifacts_dir / "implementation.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def run(
    *,
    task_prompt_path: Path,
    repo: TargetRepo,
    aidt: ToolkitPaths,
    workspace: WorkspacePaths,
    pr: int | None = None,
    resume: bool = False,
    from_stage: str | None = None,
    parallel: bool = False,
    approve_all: bool = False,
    skip_gates: list[str] | None = None,
    deny_gates: list[str] | None = None,
    gate_default: str | None = None,
    strict: bool = False,
    dry_run: bool = False,
    stream: bool = False,
) -> int:
    skip = set(skip_gates or [])
    deny = set(deny_gates or [])
    runs_root = workspace.state_root / "runs"

    # --- task id + branch (before any side effect) -------------------------- #
    # The task id comes from the filename alone (E2.5 commits the prompt in the task
    # worktree, so the file is not readable from the control root at this point), and
    # the branch is derived from it with the same helper ``aidw prompt`` uses.
    raw_path = Path(task_prompt_path)
    parsed = parse_task_id(raw_path)
    if parsed is None:
        print(
            f"cannot derive a task id from prompt filename: {raw_path.name}",
            file=sys.stderr,
        )
        return 2
    phase, task, task_id = parsed
    branch_name = derive_branch_name(repo.branch_pattern, phase=phase, task=task)
    if branch_name is None:
        print(
            f"malformed repo.branch_pattern {repo.branch_pattern!r}: it must be a "
            "format string referencing both `{phase}` and `{task}` "
            '(e.g. "{phase}-{task}").',
            file=sys.stderr,
        )
        return 2

    # --- target config (E4.3, EXTRACTION.md §3.4/§3.11, D10) --------------------- #
    # The first two of `aidw prompt`'s config refusals, at the same site and with the same
    # contract: stderr + exit 2, before the locate and before any run record or worktree,
    # `--dry-run` included. The resolved config is what `plan_stages` needs for the
    # per-stage `prompt:` overlay (D14); a repo with no `aidw/config.yaml` resolves the
    # toolkit defaults and plans exactly as before. `validate_paths` stays prompt-only:
    # its read-paths (`roadmap_dir`, the build-results template) need not exist in an
    # implement tree, and a missing one surfaces fail-closed at the stage that reads it.
    resolved_config, config_issues = resolve_workflow_config(
        repo.root, toolkit_version=__version__
    )
    if config_issues:
        print(format_issues(config_issues), file=sys.stderr)
        return 2

    # --- parallel groups (E4.4, EXTRACTION.md §3.5, R11) ------------------------ #
    # Validate the *effective* groups (the repo's declared list or the registry default)
    # immediately after the config resolution, before any run record, worktree or stage —
    # and in `--dry-run` too: a broken group list is a config error either way, with the
    # same stderr + exit 2 contract as the two refusals above. `parallel_groups: []` (the
    # empty list of groups) is valid and means serial; an empty *inner* group is not.
    parallel_groups = effective_parallel_groups(resolved_config)
    group_issues = stage_registry.validate_parallel_groups("implement", parallel_groups)
    if group_issues:
        print(format_issues(group_issues), file=sys.stderr)
        return 2

    # --- core vs repo-optional stages (E4.5a, D12/D13, EXTRACTION.md §3.5) ------ #
    # A declared list **replaces** the registry's list wholesale (§3.4), so a repo that
    # omits a core stage has removed it; validate that list right after the config
    # resolution and the E4.4 groups, before `load_all`, any run record or worktree, and
    # in `--dry-run`: a D12/D13 violation is a config error either way, with the same
    # stderr + exit 2 contract as the refusals above. Declared-ness, never value
    # equality, decides (matching `effective_parallel_groups`): an undeclared list is
    # absent from the resolved config and the registry defaults plan unchanged, while an
    # explicit `stages: []` carries `source == "config"` and reports every core stage
    # removed.
    stages_entry = resolved_config.get(STAGES_PATH)
    if stages_entry is not None and stages_entry.source == SOURCE_CONFIG:
        stage_issues = stage_registry.validate_stage_list(
            "implement", stages_entry.value or []
        )
        if stage_issues:
            print(format_issues(stage_issues), file=sys.stderr)
            return 2

    # --- agents/config ---------------------------------------------------------- #
    # Config validation stays in the preflight, before the locate: a combined
    # bad-config-plus-missing-worktree run is a usage/config error (exit 2, design §14),
    # not a preflight refusal (exit 4).
    # E4.6: a declared `paths.agent_configs_dir` is target-repo configuration, resolved
    # against the control root here and re-resolved against the worktree below — the same
    # tree the stages run in. Unset (the toolkit default) passes `None`, so the toolkit's
    # own `agent-configs/` is used and nothing about a repo without overrides changes.
    agents, issues = load_all(
        aidt.root,
        repo.root,
        override_dir=agent_configs_override(resolved_config, repo.root),
    )
    errors = [i for i in issues if i.level == ERROR]
    warnings = [i for i in issues if i.level == WARNING]
    if errors or (strict and warnings):
        print(format_issues(errors + (warnings if strict else [])), file=sys.stderr)
        return 2

    # --- declared stage settings (E4.5b, EXTRACTION.md §3.5/§3.6) --------------- #
    # After `load_all`, because the agents dict is what a repo-added stage's `agent` is
    # checked against — the validator above runs before it. `validate_stage_list` stays
    # the first stage-list refusal; this one covers the two settings the plan needs and
    # turns them into config ERRORs (stderr + exit 2) before the locate, any run record or
    # worktree, and in `--dry-run`, so a missing declared prompt or an unknown repo-added
    # agent never escapes `run()` as a traceback. Control-root only: the worktree reload
    # below keeps its own `load_all` refusal and, like `validate_stage_list`, is not re-run.
    if stages_entry is not None and stages_entry.source == SOURCE_CONFIG:
        declaration_issues = declared_stage_issues(
            "implement",
            stages_entry.value or [],
            toolkit_root=aidt.root,
            target_root=repo.root,
            agents=agents,
        )
        if declaration_issues:
            print(format_issues(declaration_issues), file=sys.stderr)
            return 2

    # --- retained preflight: one live run per branch ------------------------ #
    # The old main/branch-mismatch guards are gone: the task worktree is located, so
    # `aidw implement` no longer requires being on the task branch. The still-running
    # guard stays, checked before the locate, so a refusal creates no run state.
    existing = _latest_implement_run(runs_root, branch_name)
    if existing is not None and existing.status == RUNNING and not resume:
        print(
            f"another implement run for `{branch_name}` is still marked running: "
            f"{existing.run_id}. Use --resume or finish it.",
            file=sys.stderr,
        )
        return 4
    if resume and not dry_run and existing is None:
        print(f"no implement run to resume for `{branch_name}`.", file=sys.stderr)
        return 2

    # --- --from validation (names only; before any lookup) ------------------ #
    # F1 (PR #49 review follow-up): validate `--from` against the planned stage
    # names before the locate and run-state creation, so a typo'd stage name refuses
    # with exit 2 and leaves behind no run directory. ``build_plan`` is the registry
    # expansion (pure); the real ``prompt_rel`` is resolved after the locate and the
    # run-path plan is built with it by ``plan_stages``.
    names = [
        entry.name
        for entry in build_plan(
            aidt=aidt.root,
            prompt_rel="",
            branch=branch_name,
            task_id=task_id,
            base_branch=repo.base_branch,
            # I7's fields cannot be resolved before the locate (the entry comes from the
            # located tree), and this call reads only the stage *names* (H3.1 req 6): the
            # same placeholder precedent as ``prompt_rel=""``.
            roadmap_file="",
            checkbox_id="",
        )
    ]
    from_index: int | None = None
    if from_stage is not None:
        if from_stage not in names:
            print(
                f"unknown stage `{from_stage}` (expected one of {', '.join(names)})",
                file=sys.stderr,
            )
            return 2
        from_index = names.index(from_stage)

    # --- resume confirmation (before any side effects) ---------------------- #
    # F2 (PR #49 review follow-up): ask before the locate, so a declined resume
    # leaves behind no run state — the same fail-closed contract as the
    # still-running refusal above.
    if resume and not dry_run:
        print(f"resume: {existing.run_id}")
        print("completed stages:")
        _print_completed(existing)
        if not _confirm_resume(approve_all):
            print("resume declined.", file=sys.stderr)
            return 4

    # --- locate the task worktree (EXTRACTION.md §3.2, E2.6 req 1) ---------- #
    # Inline Python, not a plan stage: the stage ids stay the registry's own (§3.5), and a
    # refusal must leave no run state behind. ``aidw prompt`` (E2.5) created the worktree
    # and committed the task prompt inside it; implement only locates it. A missing
    # worktree is a preflight refusal (exit 4, design §14) in a real run; a dry run
    # prints the corrective command as planned output and keeps planning (req 6).
    planned_worktree = (workspace.workspace_root / branch_name).resolve()
    worktree = git.worktree_for_branch(repo.root, branch_name)
    if worktree is None:
        command = worktree_add_command(workspace, branch_name, repo.base_branch)
        if dry_run:
            print(f"worktree (planned): {planned_worktree}")
            print(f"branch-setup (planned): {command}")
            target = repo
            worktree_root = planned_worktree
        else:
            print(
                f"branch-setup refused: no worktree for `{branch_name}`. "
                f"Create it first:\n  {command}",
                file=sys.stderr,
            )
            return 4
    else:
        # Re-resolve the target and agents against the worktree: agent.cwd was resolved
        # against the control root and would silently keep the stages in the wrong worktree.
        resolved = TargetRepo.resolve(worktree)
        target = replace(
            resolved,
            base_branch=repo.base_branch,
            branch_pattern=repo.branch_pattern,
        )
        agents, issues = load_all(
            aidt.root,
            target.root,
            override_dir=agent_configs_override(resolved_config, target.root),
        )
        reloaded_errors = [i for i in issues if i.level == ERROR]
        reloaded_warnings = [i for i in issues if i.level == WARNING]
        if reloaded_errors or (strict and reloaded_warnings):
            print(
                format_issues(reloaded_errors + (reloaded_warnings if strict else [])),
                file=sys.stderr,
            )
            return 2
        worktree_root = target.root
        if dry_run:
            print(f"worktree (planned): {worktree}")

    # --- resolve the prompt inside the worktree (E2.6 req 2) ---------------- #
    resolved_prompt = _resolve_prompt_argument(raw_path, repo.root, worktree_root)
    if resolved_prompt is None:
        print(
            f"task prompt must live inside the repository: {raw_path}",
            file=sys.stderr,
        )
        return 2
    prompt_path, prompt_rel = resolved_prompt
    # The existence refusal needs the located worktree: a dry run with no worktree plans
    # the re-based path unchecked, but a located worktree still refuses (even in dry-run).
    if not dry_run or worktree is not None:
        if not prompt_path.is_file():
            print(f"task prompt not found: {prompt_path}", file=sys.stderr)
            return 2

    # The tree every downstream read and stage uses: the located worktree, or — only for a
    # dry run with no worktree — the control root. A dry run with no such tree yet plans
    # against the control root (the same fallback review/fix document): resolving against the
    # planned-but-absent path would make every repo-declared `prompt:` fail closed in every
    # dry run, a state the real run never sees.
    plan_root = worktree_root if (worktree is not None or not dry_run) else repo.root

    # --- roadmap tick target (H3.1 req 5/req 6; D15/D17) ------------------- #
    # Resolved **after** the locate and from `plan_root`, so the entry comes from the tree
    # the stage edits: the control root a chain invokes `implement` from is on the base
    # branch and is the wrong tree (design K1). The two config values are the same ones
    # `prompt.py` reads; they are joined here rather than hardcoded, so a repo that keeps
    # its roadmap elsewhere still ticks (D15's "two readers, one source"). A count other
    # than exactly one refuses before the stage runs: `find_task` returns the first match,
    # so a duplicate would silently tick the wrong entry.
    roadmap_root = (plan_root / str(resolved_config["paths.roadmap_dir"].value)).resolve()
    try:
        tick = roadmap.tick_entry(
            roadmap.load_tasks(
                roadmap_root, str(resolved_config["paths.roadmap_glob"].value)
            ),
            phase=phase,
            task=task,
        )
    except roadmap.RoadmapTickError as exc:
        print(f"roadmap tick refused: {exc}", file=sys.stderr)
        return 2
    roadmap_file = roadmap.entry_path(roadmap_root, tick)
    # The bytes the post-stage check compares against; read before the stage runs, from the
    # same file the stage is told to edit.
    tick_before = roadmap_file.read_text(encoding="utf-8")

    # The run-path plan: the registry's eight stages mapped to specs through `resolve_prompt`,
    # with the repo's `prompt:` overlay applied (E4.3).
    plan = plan_stages(
        "implement",
        config=resolved_config,
        toolkit_root=aidt.root,
        target_root=plan_root,
        prompt_rel=prompt_rel,
        branch=branch_name,
        task_id=task_id,
        base_branch=repo.base_branch,
        roadmap_file=str(roadmap_file),
        checkbox_id=tick.task,
    )
    # I6 is the PR stage, located **by id** (E4.5b): a declared list may carry repo-added
    # stages before or after it, so a positional ``plan[:-1]``/``plan[-1]`` split would
    # mistake a trailing stage for the PR stage (or drop it). Everything before I6 is the
    # pre-PR block the gate sits behind; everything after it runs once I6 succeeded.
    pr_index = next(
        index for index, spec in enumerate(plan) if spec.id == "I6"
    )
    pre_pr = plan[:pr_index]
    pr_plan = plan[pr_index]
    post_pr = plan[pr_index + 1 :]

    # --- one run per worktree (EXTRACTION.md §3.2/§3.10, E2.7) ---------------- #
    # The key is the *resolved* worktree path -- ``target.root``, the same value
    # ``create_run`` records as ``repo_root`` -- never the branch: a detached-HEAD
    # worktree has no branch, and §3.2 says "keyed by worktree path". Acquired
    # immediately before ``create_run`` (the point where the key is final) and released
    # on every exit path below, refusals and failures included, so the worktree cannot
    # stay locked until process exit. It lives in the state root, never in a target
    # repo or worktree (§3.1), and it is neither ``_STATE_LOCK`` (in-process, per
    # ``state.json`` write) nor ``--parallel`` (concurrent stages inside one run).
    # A dry run acquires the same lock, so a peer run in this worktree is refused
    # (exit 4, §19 item 8) whether the invocation would write or merely plan; it holds
    # and releases it on every exit path below.
    try:
        run_lock = lock.acquire(workspace.state_root, target.root)
    except lock.LockHeldError as exc:
        print(str(exc), file=sys.stderr)
        return 4

    try:
        # --- run state (new or resumed) ----------------------------------------- #
        # A resumed run was confirmed above, before the worktree locate and this write.
        if resume and not dry_run:
            state = existing
            directory = run_dir(runs_root, state.run_id)
            logger = RunLogger(directory, stream=stream)
        else:
            # EXTRACTION.md §3.11 (E8.2): what produced this run. One helper so the
            # five workflows cannot record different values for one config.
            config_schema_version, config_hash = config_identity(resolved_config)
            # W1.2: a plan creates no run — `planned_run` is `create_run` under the
            # never-saved PLANNED_RUN_ID (identical signature, no write), and the plan's
            # directory is the `<run dir>` placeholder a real run replaces with run_dir().
            state = (planned_run if dry_run else create_run)(
                runs_root,
                target.root,
                "implement",
                label=branch_name,
                task={"phase": phase, "task": task, "prompt_path": prompt_rel},
                strict=strict,
                branch=branch_name,
                toolkit_version=__version__,
                config_schema_version=config_schema_version,
                config_hash=config_hash,
            )
            if pr is not None:
                state.pr = {**state.pr, "number": pr}
            if dry_run:
                directory = Path(PLANNED_RUN_DIR_TEXT)
                logger = NullLogger(stream=stream)
            else:
                directory = run_dir(runs_root, state.run_id)
                logger = RunLogger(directory, stream=stream)
                save(directory, state)

        logger.info(f"implement workflow {task_id}: {prompt_rel}")
        if not dry_run:
            print(f"run:    {state.run_id}")
        print(f"branch: {branch_name}")
        print(f"prompt: {prompt_rel}")

        # --- dry run: plan every stage, no Pi, no git/GitHub writes -------------- #
        if dry_run:
            for entry in plan:
                record = run_stage(
                    entry,
                    repo_root=target.root,
                    toolkit_root=aidt.root,
                    runs_root=runs_root,
                    state=state,
                    logger=logger,
                    agents=agents,
                    dry_run=True,
                    config=resolved_config,
                )
                print(f"{entry.id} {record.name} [{record.status}] (planned) "
                      f"agent={record.agent} model={record.model}")
            print(f"gate (planned): {GATE}")
            print("dry-run complete; Pi not invoked")
            return 0

        # --- stage selection (resume / --from) ---------------------------------- #
        # ``from_stage`` was validated against the registry names before branch setup;
        # the log line waits for the run's logger to exist. Its index is re-derived from
        # the run-path plan (E4.5b): ``should_run`` compares full-plan positions, and a
        # repo-added stage declared before the named one shifts them, so the registry-name
        # index would re-run the wrong stages. ``from_stage`` is always a registry name,
        # so it is present in the plan.
        if from_stage is not None:
            plan_names = [spec.name for spec in plan]
            if from_stage in plan_names:
                from_index = plan_names.index(from_stage)
                logger.info(f"--from {from_stage}: re-running from {from_stage}")
            else:
                # The named stage is not in this run's plan — a repo-optional stage the
                # repo disabled, or one `build_plan` knows but the declared list dropped.
                # Nothing to re-run from, so every stage keeps its own succeeded-skip
                # decision instead of crashing on a missing position.
                from_index = None
                logger.info(f"--from {from_stage}: stage is not in this run's plan")

        def should_run(index: int, name: str) -> bool:
            if from_index is not None and index >= from_index:
                return True
            record = state.stage(name)
            return not (record is not None and record.status == SUCCEEDED)

        def record_skip(entry: StageSpec, reason: str) -> bool:
            """Record a withheld stage and report it; always ``True`` (a skip is success).

            The one publishing path both conditions use, so a path-scoped skip and an
            evidence-withheld tick are indistinguishable in shape: ``record_skipped`` (a
            ``skipped`` StageRecord carrying the agent and model the stage *would* have
            run, the reason in ``SKIP_REASON_KEY``, ``error`` unset), one ``run.log`` line
            and the stage block. No ``state.status``/``state.resume`` write — a skip is not
            a failure.
            """
            record = record_skipped(
                entry,
                state=state,
                directory=directory,
                agents=agents,
                reason=reason,
            )
            logger.info(f"stage {entry.name}: skipped — {reason}")
            print_stage(record, repo_root=target.root, prefix=entry.id)
            return True

        def withhold_paths_stage(entry: StageSpec) -> bool:
            """S1.1: withhold a ``WHEN_PATHS_CHANGED`` stage the change set proves unused.

            The change set is computed here, at the stage's own position (after I1/I2 have
            done their work), with the run's state root excluded — the same scope
            :func:`roadmap_tick_evidence` uses, so both conditions read one change set. An
            undeclared/empty ``when_paths`` and a change set that cannot be computed both
            make :func:`paths_changed_reason` return ``None``, i.e. the stage runs: dropping
            a stage that may be needed is never the fail-closed direction.

            The **pure** decision comes first (#165): the declared prefixes are evaluated
            with no I/O, and an empty (or unusable) set returns before the change set is ever
            computed. The toolkit default — no declared paths — is statically unconditional,
            so the three read-only ``git`` spawns :func:`change_set_paths` would perform are
            pure waste on the most common path (AGENTS.md: git spawns dominate runtime).
            """
            if not _declared_prefixes(entry.when_paths):
                return False
            reason = paths_changed_reason(
                change_set_paths(target.root, exclude=(workspace.state_root,)),
                entry.when_paths,
            )
            return False if reason is None else record_skip(entry, reason)

        def withhold_stage(entry: StageSpec) -> bool:
            """Evaluate a carried ``when=`` token before ``run_stage`` (S1.1 req 5).

            Both carried tokens dispatch here — ``paths-changed`` (I3, S1.1) and
            ``evidence-green`` (I7, H3.2) — and both dispatch paths call *this*, never one
            token's evaluator directly: the serial ``execute()`` and the ``--parallel``
            member filter, which submits to the pool itself.
            """
            if entry.when == stage_registry.WHEN_PATHS_CHANGED:
                return withhold_paths_stage(entry)
            return withhold_tick(entry)

        def withhold_tick(entry: StageSpec) -> bool:
            """H3.2: evaluate I7's ``WHEN_EVIDENCE_GREEN`` **before** ``run_stage`` does.

            Called on **both** dispatch paths — the serial ``execute`` and the
            ``--parallel`` member loop, which submits to the pool directly rather than
            going through ``execute`` — because ``validate_parallel_groups`` only refuses
            unknown or double-listed members, so a repo-declared group may legally contain
            ``update-roadmap``. Evaluating here, before any Pi invocation, is what makes
            the condition real: an agent that ran could tick a box the run has no green
            evidence for, and routing the skip around ``settle_tick`` as well (it is only
            called after a stage returns) keeps a ``tick: already`` stamp off a stage that
            never ran.

            Returns ``True`` when the stage was withheld and fully recorded — a skip is a
            **success** on both paths: it never fails the run and never writes
            ``state.status``/``state.resume``, because the red gate that caused it already
            decided the run (design §8.2). Returns ``False`` for every other stage and for
            a green verdict, which then runs exactly as H3.1 left it.
            """
            if (
                entry.name != TICK_STAGE_NAME
                or entry.when != stage_registry.WHEN_EVIDENCE_GREEN
            ):
                return False
            evidence = roadmap_tick_evidence(
                state,
                repo_root=target.root,
                exclude=(workspace.state_root,),
                ignore=tick_evidence_ignore(resolved_config, target.root),
            )
            reason = evidence.reason
            if evidence.green:
                # H3.2 asks whether this run's gates passed. The tick is a *completion*
                # claim, so it also has to agree with what the run recorded about the
                # task's Done-when: PR #282 had every gate green and a build-results
                # document concluding the contract suite failed, and the tick was still
                # attempted (design §8.2, the same rule the target repo's own completion
                # check applies). A tick the recorded verdict contradicts is withheld, not
                # failed — like a red gate, the run has already decided.
                conclusion = roadmap.recorded_unmet_conclusion(
                    target.root,
                    implementation_results_dir=(
                        resolved_config["paths.implementation_results_dir"].value
                    ),
                    phase=tick.phase,
                    task=tick.task,
                )
                if conclusion is None:
                    return False
                reason = roadmap.unmet_conclusion_reason(conclusion)
            return record_skip(entry, reason)

        def settle_tick(entry: StageSpec, record: StageRecord) -> None:
            """Apply I7's postcondition on both the serial and the parallel schedule (H3.1).

            Only the tick stage has one, and only when the stage itself reported success: a
            failed stage keeps its own error, and a ``--dry-run`` returned before either call
            site, so no planned stage is ever verified as if it had run.
            """
            if entry.name != TICK_STAGE_NAME or record.status != SUCCEEDED:
                return
            settle_roadmap_tick(
                record,
                checkbox_id=tick.task,
                roadmap_file=roadmap_file,
                before=tick_before,
                logger=logger,
                state=state,
                directory=directory,
            )

        # --- I1..I5, I7 ----------------------------------------------------------- #
        def execute(entry: StageSpec, index: int) -> bool:
            """Run one stage unless it already succeeded; return its success."""
            if not should_run(index, entry.name):
                print(f"stage:  {entry.id} {entry.name} [skipped]")
                return True
            if withhold_stage(entry):
                return True
            record = run_stage(
                entry,
                repo_root=target.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
                config=resolved_config,
            )
            settle_tick(entry, record)
            print_stage(record, repo_root=target.root, prefix=entry.id)
            if record.status != SUCCEEDED:
                print(f"stage {entry.name} failed: {record.error}", file=sys.stderr)
                state.status = FAILED
                state.resume = {"next_stage": entry.name}
                save(directory, state)
                return False
            return True

        index_of = {entry.name: index for index, entry in enumerate(pre_pr)}
        by_name = {entry.name: entry for entry in pre_pr}

        if parallel:
            # The config-driven groups (E4.4, R11). Every member of a group runs
            # concurrently at the position of the group's *earliest* member (registry
            # order), and every non-member stage keeps its registry order — so the default
            # pair still schedules I1 → {I2, I4} → I3 → I5 → I6. The preflight proved each
            # member exists and is not ordered against another member; file-ownership
            # safety is the repo's declaration, not something the toolkit infers (R11),
            # and the groups must still touch disjoint trees because every member runs in
            # the same working tree. ``pr`` (I6) is the post-gate sync point and always
            # runs alone below, so a group naming it only schedules its other members.
            # Run-state writes are serialized inside ``run_stage`` (``_STATE_LOCK``).
            logger.info(
                "--parallel: groups: "
                + (
                    "; ".join(", ".join(group) for group in parallel_groups)
                    or "none (every stage serially)"
                )
            )
            group_of: dict[str, int] = {}
            for group_index, group in enumerate(parallel_groups):
                for member in group:
                    group_of.setdefault(member, group_index)
            handled: set[str] = set()
            for index, entry in enumerate(pre_pr):
                if entry.name in handled:
                    continue
                group_index = group_of.get(entry.name)
                if group_index is None:
                    if not execute(entry, index):
                        return 1
                    continue
                # This stage is its group's earliest pre-PR member: run the whole group
                # here. Members that already succeeded are reported and left out of the
                # pool, exactly as the serial path skips them (resume/--from).
                members = [
                    by_name[name]
                    for name in parallel_groups[group_index]
                    if name in by_name
                ]
                handled.update(member.name for member in members)
                active = [
                    member
                    for member in members
                    if should_run(index_of[member.name], member.name)
                ]
                for member in members:
                    if member not in active:
                        print(f"stage:  {member.id} {member.name} [skipped]")
                if not active:
                    continue
                # H3.2/S1.1: a group is a dispatch path in its own right, so the carried
                # `when=` check runs per member here too — before anything is submitted to
                # the pool. A repo-declared group may legally name `update-traceability`
                # (path-scoped, S1.1) as well as `update-roadmap`.
                runnable = [
                    member for member in active if not withhold_stage(member)
                ]
                if not runnable:
                    continue
                failed: list[StageSpec] = []
                with ThreadPoolExecutor(max_workers=len(runnable)) as pool:
                    futures = {
                        pool.submit(
                            run_stage,
                            member,
                            repo_root=target.root,
                            toolkit_root=aidt.root,
                            runs_root=runs_root,
                            state=state,
                            logger=logger,
                            agents=agents,
                        ): member
                        for member in runnable
                    }
                    for future in as_completed(futures):
                        member = futures[future]
                        record = future.result()
                        settle_tick(member, record)
                        print_stage(record, repo_root=target.root, prefix=member.id)
                        if record.status != SUCCEEDED:
                            print(
                                f"stage {member.name} failed: {record.error}",
                                file=sys.stderr,
                            )
                            failed.append(member)
                if failed:
                    # The earliest failed member in registry order (not whichever the pool
                    # happened to finish first), so the resume hint is deterministic. No
                    # later stage runs: the same failure contract as the serial path.
                    first = min(failed, key=lambda item: index_of[item.name])
                    state.status = FAILED
                    state.resume = {"next_stage": first.name}
                    save(directory, state)
                    return 1
        else:
            for index, entry in enumerate(pre_pr):
                if not execute(entry, index):
                    return 1

        # --- I2's verdict withholds I6 (Q1.1, design §8.2, §17 Z10) ---------------- #
        # After the whole pre-PR block (I1..I9 plus I7 on both dispatch paths) and before
        # the approve gate: an in-scope `Fail` withholds the PR, and the roadmap explicitly
        # does **not** withhold the tick — I6 is the only committer, and it never runs. Read
        # from the recorded stage, so a resumed run decides the same way (`_read_out`).
        withheld = _test_verdict_stop(state, directory, logger)
        if withheld is not None:
            return withheld

        # --- gate ---------------------------------------------------------------- #
        approved = any(g.name == GATE and g.decision == "approved" for g in state.gates)
        if approved:
            print(f"gate:   {GATE} [already approved]")
        else:
            summary = _gate_summary(state, target, branch_name, prompt_rel)
            outcome = decide(
                GATE,
                summary,
                approve_all=approve_all,
                skip=skip,
                deny=deny,
                gate_default=gate_default,
            )
            state.record_gate(
                GateRecord(
                    name=GATE,
                    decision=outcome.decision,
                    mechanism=outcome.mechanism,
                    at=utcnow_iso(),
                )
            )
            save(directory, state)
            if not outcome.approved:
                state.status = BLOCKED
                save(directory, state)
                print(
                    f"gate {GATE} denied ({outcome.mechanism}); stopping.",
                    file=sys.stderr,
                )
                return 3
            print(f"gate:   {GATE} [{outcome.mechanism}]")

        # --- I6 ------------------------------------------------------------------ #
        # I6's own plan index (E4.5b): ``len(plan) - 1`` is only I6 when nothing is
        # declared after it, so a trailing repo-added stage would make the skip/resume test
        # ask about the wrong stage.
        if should_run(pr_index, pr_plan.name):
            record = run_stage(
                pr_plan,
                repo_root=target.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
                config=resolved_config,
            )
            print_stage(record, repo_root=target.root, prefix=pr_plan.id)
            if record.status != SUCCEEDED:
                print(f"stage {pr_plan.name} failed: {record.error}", file=sys.stderr)
                return 1
            _record_pr(state, target, record)
        else:
            print(f"stage:  {pr_plan.id} {pr_plan.name} [skipped]")

        # --- stages declared after I6 (E4.5b) ------------------------------------- #
        # After a successful (or skipped-because-resumed) I6 only: a denied gate returns 3
        # and a failed I6 returns 1 above, so nothing declared after I6 runs on either —
        # exactly as a trailing stage did not exist before E4.5b. They run in declared
        # order under the same ``should_run`` skip, at their full-plan positions.
        for offset, spec in enumerate(post_pr, start=1):
            if not should_run(pr_index + offset, spec.name):
                print(f"stage:  {spec.id} {spec.name} [skipped]")
                continue
            record = run_stage(
                spec,
                repo_root=target.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
                config=resolved_config,
            )
            print_stage(record, repo_root=target.root, prefix=spec.id)
            if record.status != SUCCEEDED:
                print(f"stage {spec.name} failed: {record.error}", file=sys.stderr)
                state.status = FAILED
                state.resume = {"next_stage": spec.name}
                save(directory, state)
                return 1

        _write_artifacts(directory, state, branch_name)
        state.status = SUCCEEDED
        state.resume = {"next_stage": None}
        save(directory, state)

        print("implement workflow complete")
        print(f"branch: {branch_name}")
        if state.pr.get("url"):
            print(f"pr:     {state.pr['url']}")
        return 0
    finally:
        run_lock.release()
