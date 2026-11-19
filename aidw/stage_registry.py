"""The default stage registry: AIDT's workflow chains as data (EXTRACTION.md §3.5, E4.1).

This module is the single declarative home of *which stage runs where*: the nine-stage
``implement`` chain (design §8.2), the post-phase-02 ``prompt`` review loop (§8.1), the
``review`` pair (§8.3), the ``fix`` iteration loop (§8.4) and the single ``approve`` stage
(§8.5). It is **data plus pure helpers** (the expander and the ``parallel_groups``
validator): nothing here spawns a process, touches the filesystem, or imports a workflow
module.

Two stage definitions are **shared between workflows** so their behaviour cannot drift:
``A1`` (``approve`` and ``fix``'s approval rounds, the pre-H3.3 precedent) and, since H3.3,
``I7 update-roadmap`` — the roadmap tick that ``implement`` runs in its static chain and
``fix`` runs from its :attr:`WorkflowDefinition.post_loop` half once its loop converges
(§8.4). Both are module-level constants referenced from the workflow definitions, never
copied.

Since 05-P1.1 (design §17 Z9) ``fix``'s post-loop half carries a **second** stage, ``F5
commit-and-push``: the one stage of ``fix`` that publishes work. It is core, it carries no
``when=`` token (its trigger is loop convergence, not green evidence — D2), and it is
modelled on ``implement``'s ``I6 pr``, which is the only stage that commits there.

Dependency direction (EXTRACTION.md §3.5, task E4.1's trap list):

* :mod:`aidw.workflows.implement` → this module is the direction E4.3 installed:
  ``build_plan`` is now a thin wrapper over :func:`expand` and ``PlanStage`` is gone, so
  nothing is imported back out of a workflow (that would be a cycle). The registry owns
  its own stage types, :class:`StageDefinition` and :class:`PlannedStage`, carrying the
  same §3.5 fields.
* :mod:`aidw.target_config` must never import a workflow module (its docstring states
  why), so the registry imports nothing from the config or workflow layers; it may be
  imported *by* both. ``workflows.<name>.stages`` config entries stay the separate
  ``StageConfig`` shape: since E4.3 :func:`aidw.runner.plan_stages` treats a repo-declared
  list as a ``prompt:`` overlay over these defaults (the defaults themselves stay the only
  source of stage order and size).
* The only imports are two leaf modules: :mod:`aidw.findings`, which renders the
  review-finding blocks and the publisher's manifest brief (reusing it rather than copying
  the prose keeps one source of truth for text the fix and publisher stages receive), and
  :mod:`aidw.config`, for the ``Issue``/``ERROR`` pair :func:`validate_parallel_groups`
  returns (E4.4) — so the workflow's preflight prints a bad ``parallel_groups`` through the
  same ``format_issues`` as every other config refusal. Both are safe: neither imports a
  workflow or a target-config module. Anything that would need the resolved config, a
  workflow module or the filesystem stays out — the validator takes the **effective**
  groups as an argument, exactly as :func:`aidw.runner.plan_stages` takes the resolved
  config.

Stage-id vocabulary (R6 — ids are *retained*, never renamed to the semantic
``author``/``review``/``implement`` of §3.4's illustrative YAML): ``I1``–``I9``, ``P1``,
``P2``, ``R1``, ``R2``, ``F1``–``F5``, ``A1`` (:data:`STAGE_IDS`). Two different fields are
kept apart on purpose — ``id`` is the retained key (``"I1"``) and ``name`` is the runtime
stage name (``"impliment-task"``), which is what ``state.json`` and the run artifacts key
on. §3.4's ``author``/``review``/... ids illustrate the *schema shape* only.

Loops are not flat lists (design §8's ``⟳``/``if`` notation):

* :class:`LoopDefinition` is the minimal bounded-loop shape: ``head`` stages run every
  iteration, ``body``/``tail`` only for an iteration that still has budget, and
  ``terminal_last`` makes the final iteration head-only. That single boolean is H6/G2/L4.1
  ("the ``max_revisions``-th review is review-only; a review is always the last stage").
  ``unprimed_first`` is L2.3 ("round 1 is deliberately unprimed" — no delta brief).
* :class:`StageDefinition.when` is the ``if`` of §8.3/§8.4 (``if findings: → R2``), and
  also the two conditions the expander cannot resolve — :data:`WHEN_EVIDENCE_GREEN`
  (H3.2) and :data:`WHEN_PATHS_CHANGED` (S1.1) — so they are carried onto the planned
  stage and evaluated by the workflow.
* :class:`FixBatch` carries one round's finding partition, so the ``prompt`` loop's
  per-finding / combined-could-fix / whole-review-fallback staging is *input*, not
  branching code inside the expander.

Deliberate, prompt-fixed choices (the task prompt left these to the implementer):

* **Data shape**: a ``WorkflowDefinition`` of static ``stages`` plus one optional
  :class:`LoopDefinition`, not the §3.4 YAML ``stages:`` list literally. The config list
  cannot express a bounded loop, and the config's ``StageConfig`` cannot carry
  ``name``/``prompt_file``/``variables`` at all.
* **Entry point**: :func:`expand` — pure, deterministic, takes the concrete inputs
  (``max_revisions``, the per-round finding partitions, the fix iteration) and returns the
  ordered stages as :class:`PlannedStage` values. ``variables`` are tuples (frozen data)
  so a caller cannot mutate the defaults through a result; ``list()`` them to build a
  :class:`aidw.runner.StageSpec` argument list.
* **``extra`` text location**: the static briefs (I2's test context, F2's re-test context,
  R2/F4's manifest pointer) are *templates in this module*, and the data-dependent briefs
  (the delta brief, the reconcile brief, the whole-review fallback) are rendered by the
  pure helpers :func:`render_delta_brief`, :func:`render_reconcile` and
  :func:`render_whole_review_extra`. E4.3 deleted the workflow modules' copies, so this is
  the single home for that wording; ``tests/test_stage_registry.py`` pins the rendering and
  ``tests/test_prompt_workflow.py``'s real-run ``extra`` assertions pin it end to end.
* **What stays in the workflow**: the L2.4 evidence pointer, the ``git diff`` that feeds a
  delta/reconcile brief, the L3.3 prompt snapshots and the gates (``◇``) are not stage
  data. ``extra`` here is the stage's *body* text; the workflow composes the pointer in
  front of it, exactly as :func:`aidw.workflows.prompt._with_evidence` does today.

Since H2.1 :func:`render_delta_brief` also carries a **size contract**: its two halves are
budgeted separately — the previous review by picking the smaller of the raw prose and the
structured finding blocks (:func:`render_previous_review`), the diff by a hard cap
(:data:`DELTA_BRIEF_DIFF_BUDGET_CHARS`, :func:`render_diff_section`). The contract and the
values live here, not in ``workflows/prompt.py``, because ``_brief_diff`` also feeds
:func:`render_reconcile`, which stays verbatim (H2.1 req 3).

Since E4.4 ``implement.py`` schedules the target config's effective ``parallel_groups``
(this default when the config does not declare the list) and runs
:func:`validate_parallel_groups` over them in its preflight; a config's explicit ``[]``
means "no parallel groups" (serial), never a fallback to the default. Since E4.5a every
workflow's preflight runs :func:`validate_stage_list` over a **declared**
``workflows.<name>.stages`` list, so a reordered, removed or disabled core stage is
refused with stderr + exit 2 before any run record — while a repo-optional
``enabled: false`` and a repo-added stage are accepted. Since E4.5b
:func:`aidw.runner.plan_stages` plans exactly those shapes — it refuses a declared list the
validator rejects (:class:`StageListError`), builds the static half from the declared list
in declared order and honours a repo-optional ``enabled: false`` by omission — while a
repo-added stage's ``agent`` is still only *existence*-checked (moving a default stage's
agent, and the model/thinking overrides, are E4.6). Still not wired by design:
agent/model/thinking overrides (E4.6) and the fixture integration test (E4.7).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from aidw.config import ERROR, Issue
from aidw.findings import (
    MANIFEST_EXTRA,
    ParsedFinding,
    # H2.1: the delta brief re-emits the previous review as the reviewer's own blocks,
    # and ``_finding_text_block`` is that block. ``render_finding_block`` is *not* used:
    # it wraps each block in the fixer's "Fix exactly this finding" instruction, the
    # wrong voice for a reviewer that must resolve, not fix (H2.1 trap).
    _finding_text_block,
    parse_review_findings,
    render_could_fix_block,
    render_finding_block,
)

# --------------------------------------------------------------------------- #
# Stage-id vocabulary (EXTRACTION.md §3.5, §10 R6)
# --------------------------------------------------------------------------- #

#: The retained §3.5 stage ids. Semantic ids (``author``, ``review``, ``implement``) appear
#: only in §3.4's illustrative YAML example and are deliberately **not** adopted (R6).
STAGE_IDS = frozenset(
    {
        "I1",
        "I2",
        "I3",
        "I4",
        "I5",
        "I6",
        "I7",
        "I8",
        "I9",
        "P1",
        "P2",
        "R1",
        "R2",
        "F1",
        "F2",
        "F3",
        "F4",
        "F5",
        "A1",
    }
)

#: The **repo-optional** stage ids (D13, EXTRACTION.md §3.5): traceability (``I3`` →
#: ``update-traceability``) and architecture (``I4`` → ``update-architecture``) are the
#: only stages a repo may disable, remove or move. Everything else a workflow's static
#: ``stages`` declares is **core**: D13 names implement/test/code-review/record/pr plus
#: author, and the task prompt fixes R2 (review publisher) and A1 (approve) as core too —
#: a repo-optional publisher/approver would make ``review``/``approve``/``fix`` no-ops.
REPO_OPTIONAL_IDS = frozenset({"I3", "I4"})

#: Loop-internal labels. These are *not* §3.5 stage ids: the prompt loop's fix and
#: reconcile stages live inside the loop descriptor (§8.1's ``P2a``/reconcile), so they
#: carry a descriptive key rather than a new flat id in :data:`STAGE_IDS`.
PROMPT_FIX_BLOCKING = "P2-fix-blocking"
PROMPT_FIX_COULD_FIX = "P2-fix-could-fix"
PROMPT_FIX_FALLBACK = "P2-fix-fallback"
PROMPT_RECONCILE = "P2-reconcile"

# ``if`` conditions (design §8's notation; §8.3 "if findings", §8.1 "if Request changes").
#: The stage runs only when the preceding review reported findings (R2, F4).
WHEN_FINDINGS = "findings"
#: One fix stage per blocking (must-fix/should-fix) finding.
WHEN_BLOCKING = "blocking"
#: One combined stage for the non-blocking could-fix findings.
WHEN_COULD_FIX = "could-fix"
#: The single stage carrying the whole review when it does not parse into findings.
WHEN_UNPARSEABLE = "unparseable"
#: The stage runs only when the **workflow's own evidence is green** (H3.2, design §8.2).
#: Unlike ``findings``/``blocking``/``could-fix``/``unparseable`` — which the expander
#: resolves from data it already has — this condition is decided by the running workflow
#: from state no expansion can see (the run's recorded gate outcomes), so the expander
#: **carries it, never expands it away**: :func:`_expand_static` only omits on
#: ``when=findings`` with ``findings is False``, and
#: :func:`~aidw.runner._spec_from_planned` copies the value onto
#: :attr:`aidw.runner.StageSpec.when`. The workflow evaluates the token (I7 in
#: ``implement``; H3.3 reuses it for ``fix``) and records a ``skipped`` stage with its
#: reason when the condition does not hold.
WHEN_EVIDENCE_GREEN = "evidence-green"
#: The stage runs only when the run's **change set touches one of the stage's declared
#: paths** (S1.1, design §§8.2, 12.2). The paths are a repo's declaration — the additive
#: per-stage ``when_paths`` field of ``workflows.<name>.stages[]`` — never a toolkit
#: default: a hardcoded path set would be a product literal (design §7.1/§17 S1), so the
#: toolkit set is empty and an empty set means the stage runs unconditionally. Like
#: :data:`WHEN_EVIDENCE_GREEN` the token is **carried, never expanded away** — the
#: expander cannot see a change set — so ``plan_stages``/``build_plan``/``--dry-run`` plan
#: the stage in position and the workflow decides before ``run_stage``.
WHEN_PATHS_CHANGED = "paths-changed"

# Runtime-assembled ``extra`` kinds. The workflow owns the payload (prior review text, the
# real ``git diff``); these helpers own the wording, so the text cannot drift.
BRIEF_DELTA = "delta-brief"
BRIEF_RECONCILE = "reconcile"

#: Loop kinds. ``review-rounds`` is bounded by ``max_revisions``; ``fix-iterations`` is
#: bounded by GitHub state (``--max-iterations``), so it expands one iteration at a time.
LOOP_REVIEW_ROUNDS = "review-rounds"
LOOP_FIX_ITERATIONS = "fix-iterations"


# --------------------------------------------------------------------------- #
# Errors — every one of them is fail-closed
# --------------------------------------------------------------------------- #


class StageRegistryError(ValueError):
    """A contract violation in a registry lookup or an expansion request."""


class UnknownWorkflowError(StageRegistryError):
    """No default chain is registered under that workflow name."""


class UnknownStageError(StageRegistryError):
    """No stage with that id exists in that workflow."""


class StageFieldError(StageRegistryError):
    """An expansion field is missing or unusable for a stage template."""


class RevisionBudgetError(StageRegistryError):
    """The requested expansion would exceed the loop's revision budget."""


class StageListError(StageRegistryError):
    """A declared ``workflows.<name>.stages`` list violates D12/D13 (E4.5b).

    Raised by :func:`aidw.runner.plan_stages` when
    :func:`validate_stage_list` reports one or more ``ERROR`` issues: the run path never
    builds a silently shortened or reordered plan just because the preflight is expected
    to have refused it first. The message is the validator's own ``format_issues`` text,
    so a direct caller (``aidw exec``, a test) sees exactly what the preflight prints.
    """


# --------------------------------------------------------------------------- #
# The declarative shapes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StageDefinition:
    """One §3.5 stage: retained ``id``, runtime ``name``, agent, prompt and variables.

    ``name``, ``variables`` and ``extra`` are ``str.format`` templates rendered from the
    expansion fields (``{branch}``, ``{prompt_rel}``, ``{iteration}``, ``{index}``, …), so
    the same definition serves every iteration of a loop. ``when`` marks a conditional
    stage (``if findings``). ``brief`` names a runtime-assembled ``extra``
    (:data:`BRIEF_DELTA` / :data:`BRIEF_RECONCILE`) that the workflow renders with
    :func:`render_delta_brief` / :func:`render_reconcile` once it has the review text and
    the diff.
    """

    id: str
    name: str
    agent: str
    prompt_file: str
    variables: tuple[str, ...] = ()
    extra: str = ""
    when: str = ""
    brief: str = ""


@dataclass(frozen=True)
class LoopDefinition:
    """A bounded loop with a conditional body (design §8's ``⟳``/``if``).

    ``head`` runs every iteration; ``body`` and ``tail`` run only while the iteration has
    budget. ``terminal_last`` makes the final iteration head-only — H6/G2/L4.1's
    review-only terminal review, the reason a review is always the last stage for a
    non-approving prompt. ``unprimed_first`` suppresses the delta brief on round 1 (L2.3:
    the independent first sample must not anchor on a previous review).
    """

    id: str
    kind: str
    head: tuple[StageDefinition, ...]
    body: tuple[StageDefinition, ...] = ()
    tail: tuple[StageDefinition, ...] = ()
    terminal_last: bool = False
    unprimed_first: bool = False


@dataclass(frozen=True)
class WorkflowDefinition:
    """A workflow's static chain, optional loop, optional post-loop half, and groups.

    ``post_loop`` (H3.3) is the stages that run **once per run, after the loop ends**: the
    roadmap tick ``I7`` for ``fix``, shared with ``implement``'s static half, and — since
    05-P1.1 (Z9) — ``F5 commit-and-push``, the stage that publishes the run's work. They
    are a separate field from ``stages`` because ``expand("fix", …)`` *is* the
    per-iteration expansion (``fix.py:_planned_iteration`` expands one iteration at a
    time), and a stage riding it would be planned — and dry-run printed — once per
    iteration. The expander therefore emits the half **only on request**
    (``include_post_loop``), and every id in it is classified as core for declared-list
    validation like any static stage (req 2).
    """

    name: str
    stages: tuple[StageDefinition, ...] = ()
    loop: LoopDefinition | None = None
    post_loop: tuple[StageDefinition, ...] = ()
    #: R11/§3.4 ``parallel_groups``: stage *names*, not ids, because that is what
    #: ``implement.py``'s ``by_name`` lookup keys on. This default is what ``implement.py``
    #: schedules when a target repo does not declare the list (E4.4);
    #: :func:`validate_parallel_groups` checks whatever list the caller resolves.
    parallel_groups: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class FixBatch:
    """One review round's fix work: the parsed partition, or the whole review."""

    review_text: str = ""
    blocking: tuple[ParsedFinding, ...] = ()
    could_fix: tuple[ParsedFinding, ...] = ()
    #: ``True`` when the review did not parse into findings (or any block was malformed):
    #: one fallback stage carries the whole review instead of a per-finding partition.
    unparseable: bool = False


@dataclass(frozen=True)
class PlannedStage:
    """An expanded stage: exactly the §3.5 ``PlanStage`` fields, frozen.

    ``variables`` is a tuple so a caller cannot mutate a default through a result;
    ``list(planned.variables)`` when building a ``StageSpec``.
    """

    id: str
    name: str
    agent: str
    prompt_file: str
    variables: tuple[str, ...] = ()
    extra: str = ""
    when: str = ""
    brief: str = ""


# --------------------------------------------------------------------------- #
# Stage `extra` text (the single home since E4.3 deleted the workflows' copies)
# --------------------------------------------------------------------------- #

#: I2's test context. E4.3 uses this rendering on the implement run path and deleted
#: ``implement.py``'s copy.
TEST_CONTEXT_EXTRA = """\

## Stage context (provided by aidw)

- Task: {task_id}
- Branch: {branch}
- Task prompt: {prompt_rel}

Read the task prompt above, follow its acceptance criteria, and prove them. Leave your
changes uncommitted in the working tree.
"""

#: F2's re-test context. E4.3 uses this rendering on the fix run path and deleted
#: ``fix.py``'s copy.
FIX_TEST_CONTEXT_EXTRA = """\

## Stage context (provided by aidw)

This re-verifies a single approved review follow-up fix for PR #{pr} (iteration {iteration}).
Prove the fix and its acceptance criteria. This stage does not fix implementation code:
report `Fail` and hand a real defect back to `/fix-next-review-followup`. Leave changes
uncommitted in the working tree.
"""

#: Instruction prepended to every review round after the first (L2.3). E4.3 deleted
#: ``prompt.py``'s copy; the review loop renders this through :func:`render_delta_brief`.
DELTA_BRIEF_INSTRUCTION = """\
## Delta brief — resolve the previous review before raising new findings

This is a later review round, not the first. For **each** finding in the previous review
below, state a per-finding resolution verdict of exactly `resolved`, `not resolved`, or
`newly contradicted` before you raise any new finding. Judge `resolved` only from the
current prompt and the diff that follows. New findings must be genuinely new: never
re-litigate a finding you judged `resolved`."""

#: Note used when the prompt diff cannot be produced. E4.3 deleted ``prompt.py``'s copy.
DIFF_UNAVAILABLE = (
    "The prompt diff for this round is unavailable (`git diff` could not be produced); "
    "review the prompt file itself for its current state."
)

#: Hard cap on the **diff** half of a delta brief, in characters (H2.1 req 3).
#:
#: Measured with ``len(s)`` — the same metric as the previous-review half's
#: smaller-representation rule — never UTF-8 bytes or lines: the roadmap counts the
#: failure as 12,317 → 55,636 chars, and a byte count would differ for no gain.
#: 4000 is anchored to round 1's ~12k prompt, so a budgeted brief keeps the diff a small
#: fraction of what the reviewer already reads. The roadmap's second lever (a narrower
#: ``--unified`` context) is deliberately **not** taken: the context width lives in the
#: shared diff producer (``workflows/prompt.py:_brief_diff`` → ``_prompt_diff``), which also
#: feeds the out-of-scope reconcile brief, so this registry-side cap is the diff's only
#: lever in this task.
DELTA_BRIEF_DIFF_BUDGET_CHARS = 4000

#: Heading for the structured previous review (H2.1 req 2). ``_finding_text_block`` emits
#: no heading of its own, so the delta brief supplies one; its exact text is unpinned, but
#: it must not carry the fixer's voice (``render_finding_block``'s "Review finding N of M
#: to address") — the reviewer must *resolve* findings, not fix them.
DELTA_BRIEF_FINDINGS_LEAD = "#### Previous review findings, one block per finding"

#: Note replacing an **over-budget** diff (H2.1 req 3), in :data:`DIFF_UNAVAILABLE`'s style.
#:
#: It is deliberately distinguishable from the could-not-produce case: it names the size
#: as the reason, states the numeric budget and says the diff was elided, so a reviewer can
#: tell "we could not produce it" from "we dropped it to fit" and cannot mistake it for an
#: empty section. ``{size}`` is the diff's own ``len(s)``.
DELTA_BRIEF_DIFF_ELIDED = (
    "The prompt diff for this round was elided for size: the diff is {size} characters, "
    f"over the {DELTA_BRIEF_DIFF_BUDGET_CHARS}-character delta-brief budget, so it is not "
    "shown — neither whole nor shortened. Review the prompt file itself for its current "
    "state and judge each finding's verdict from the file, not from an imagined diff."
)

#: Instruction prepended to the single reconcile stage after a fix batch (L3.4). E4.3
#: deleted ``prompt.py``'s copy.
RECONCILE_INSTRUCTION = """\
## Reconcile the fix batch

One or more fix stages have just edited this prompt in isolation. Compare the fixed
prompt against the full review text and the combined diff below. Repair every
cross-section contradiction the edits introduced and address any finding the batch left
unaddressed. Do not review or re-litigate the findings; make the prompt internally
consistent with the review."""


#: The ``prompt`` review loop's head stage name prefix (``task-review-<n>``, H2.1 req 5).
DELTA_BRIEF_REVIEW_STAGE_PREFIX = "task-review-"


def is_review_stage(name: str) -> bool:
    """True for the ``prompt`` loop's review-loop **head** stages, ``task-review-<n>`` (H2.1).

    Called by :func:`aidw.runner.run_stage` to scope the ``rendered_chars`` record. It is a
    deterministic name rule, so it lives here rather than inline at the call site: the head
    is the only stage that carries a delta brief, and the fix/reconcile stages of the same
    loop (``task-review-fixes-*``, ``task-review-reconcile-*``) must not match it. Derived
    from the loop's own naming, not from a second stage list — the registry already owns
    those names.
    """
    if not name.startswith(DELTA_BRIEF_REVIEW_STAGE_PREFIX):
        return False
    iteration = name[len(DELTA_BRIEF_REVIEW_STAGE_PREFIX) :]
    # ``isascii`` keeps an exotic decimal (e.g. a superscript) from counting as an index.
    return iteration.isascii() and iteration.isdigit()


def render_previous_review(previous_review: str) -> str:
    """The **previous-review** half of a delta brief: the smaller representation (H2.1 req 2).

    The spec fixes the strategy, not a number: when the review parses cleanly into
    findings, one :func:`aidw.findings._finding_text_block` per finding under
    :data:`DELTA_BRIEF_FINDINGS_LEAD` is offered as a substitute for the raw prose, and it
    is used **only when strictly smaller** — ``len(structured) < len(previous_review)``, the
    same ``len(s)`` char metric as the diff cap (:data:`DELTA_BRIEF_DIFF_BUDGET_CHARS`),
    never UTF-8 bytes or lines. On equality, as on any non-win, and on anything that does
    not parse cleanly (any problem, or no findings at all), the prose is kept **verbatim** —
    trailing whitespace included — because a review that did not parse into findings cannot
    be re-emitted as blocks without losing text.

    No finding is ever dropped: the structured rendering is built from every parsed finding,
    and the substitution is all-or-nothing for exactly that reason. The review's non-finding
    prose (its verdict, headings, commentary) is what the size win gives up; the verdict was
    already consumed by the loop that routed on it, and the per-finding verdict instruction
    (:data:`DELTA_BRIEF_INSTRUCTION`) survives in every rendering,
    whichever representation the review itself is given in.

    Pure: the caller's string is neither mutated nor written anywhere.
    """
    findings, problems = parse_review_findings(previous_review)
    if problems or not findings:
        return previous_review
    structured = DELTA_BRIEF_FINDINGS_LEAD + "\n\n" + "\n\n".join(
        _finding_text_block(finding) for finding in findings
    )
    return structured if len(structured) < len(previous_review) else previous_review


def render_diff_section(diff: str | None) -> str:
    """The **diff** half of a delta brief: unchanged, unavailable, or explicitly elided.

    ``None`` means the workflow could not produce a diff → :data:`DIFF_UNAVAILABLE`. A diff
    over :data:`DELTA_BRIEF_DIFF_BUDGET_CHARS` is replaced by
    :data:`DELTA_BRIEF_DIFF_ELIDED`, never truncated to fit: a silently shortened diff reads
    like a complete one, and a reviewer that cannot see a fix cannot verify it (H2.1 req 3).
    An in-budget diff is returned byte-identically.
    """
    if diff is None:
        return DIFF_UNAVAILABLE
    if len(diff) > DELTA_BRIEF_DIFF_BUDGET_CHARS:
        return DELTA_BRIEF_DIFF_ELIDED.format(size=len(diff))
    return diff


def render_delta_brief(*, previous_review: str, diff: str | None) -> str:
    """Assemble a later review round's ``extra`` (instruction, prior review, diff) (L2.3).

    **Size contract (H2.1).** Both halves are budgeted *separately*, because they fail
    differently and are fixed differently:

    * **Previous review** — no hard cap. The smaller of two representations wins
      (:func:`render_previous_review`): the reviewer's structured finding blocks when the
      review parses cleanly into findings *and* those blocks are strictly fewer ``len(s)``
      characters than the prose, else the prose verbatim. Every parsed finding survives
      either way, and so does :data:`DELTA_BRIEF_INSTRUCTION`'s per-finding
      `resolved`/`not resolved`/`newly contradicted` verdict instruction.
    * **Diff** — a hard cap at :data:`DELTA_BRIEF_DIFF_BUDGET_CHARS` (4000) characters
      (:func:`render_diff_section`). An over-budget diff is replaced by
      :data:`DELTA_BRIEF_DIFF_ELIDED`, which names the size and the budget; an unavailable
      one by :data:`DIFF_UNAVAILABLE`. Neither is ever an empty or shortened section.

    Pure: no I/O, and neither input is mutated (design §15). ``diff`` is the
    already-produced unified diff (or ``None``/unavailable); producing it is the workflow's
    job, because only it has the two prompt snapshots. Round 1 never reaches this function —
    the registry zeroes the ``unprimed_first`` round's brief (L2.3, H2.1 req 4) — so nothing
    here can prime a first review. :func:`render_reconcile` is deliberately **not** budgeted:
    it shares the workflow's diff producer and is the out-of-scope L3.4 brief.
    """
    return "\n\n".join(
        [
            DELTA_BRIEF_INSTRUCTION,
            "### Previous review\n\n" + render_previous_review(previous_review),
            "### Prompt diff since that review\n\n" + render_diff_section(diff),
        ]
    )


def render_reconcile(*, review: str, diff: str | None) -> str:
    """Assemble a reconcile stage's ``extra`` (instruction, whole review, diff) (L3.4).

    Pure, like :func:`render_delta_brief`; ``diff`` is the fix batch's net effect.
    """
    return "\n\n".join(
        [
            RECONCILE_INSTRUCTION,
            "### Full review\n\n" + review,
            "### Combined diff for this fix batch\n\n"
            + (diff if diff is not None else DIFF_UNAVAILABLE),
        ]
    )


def render_whole_review_extra(review: str) -> str:
    """The fallback fix stage's ``extra``: the whole review, verbatim (design §8.1)."""
    return f"## Review findings to address\n\n{review}"


# --------------------------------------------------------------------------- #
# The defaults
# --------------------------------------------------------------------------- #

#: The roadmap tick is one logical stage (§3.5 ``I7``) that two workflows run: ``implement``
#: in its static chain (H3.1/H3.2) and ``fix`` from its post-loop half once the loop
#: converges (H3.3, design §8.4). One id, one prompt, one agent and one name in both — the
#: ``A1`` precedent — so the two ticks cannot drift.
#:
#: ``checkbox_id`` is the entry's own task id (``H3.3``); ``{task_id}`` stays I6's branch
#: form (``03-H3.3``). ``{roadmap_file}`` is the entry's own absolute roadmap path, so the
#: prompt names no directory (D15).
_ROADMAP_TICK_STAGE = StageDefinition(
    "I7",
    "update-roadmap",
    "recorder",
    "update-roadmap.md",
    ("{roadmap_file}", "{checkbox_id}"),
    # H3.2: the tick waits behind the run's own evidence. The condition is *carried* (the
    # expander cannot see gate outcomes or iteration records), so ``plan_stages``,
    # ``build_plan`` and ``--dry-run`` still plan I7 unconditionally and the workflow
    # decides at run time — before ``run_stage``, so an agent never gets the chance to
    # tick a box the run has no green evidence for. ``fix`` evaluates its own three-part
    # rule (H3.3 req 4), never a copy of ``implement``'s gate-outcome rule.
    when=WHEN_EVIDENCE_GREEN,
)

#: ``F5`` — the one stage of ``fix`` that **publishes** work (design §8.4, §13; 05-P1.1,
#: decision Z9). Modelled on ``implement``'s ``I6 pr``: the ``pr-publisher`` agent runs
#: ``git add -A`` and ``git commit`` and ``git push origin <branch>``; Python only verifies
#: the result (a stage record alone is not evidence the push landed — the O1 precedent).
#:
#: Deliberately **no** ``when=`` token: its trigger is the loop's convergence, not green
#: evidence. A converged run whose tick was withheld (Z7's unmet conclusion, an empty run,
#: an unresolvable roadmap target) still has real fix edits that must land, so gating F5 on
#: ``WHEN_EVIDENCE_GREEN`` would reintroduce the defect the stage exists to fix (decision
#: D2). ``{pr}`` is its only variable; the branch and the task id are read inside the
#: PR-head worktree by the prompt itself (D8), exactly as ``pr.md`` does.
_COMMIT_PUSH_STAGE = StageDefinition(
    "F5",
    "commit-and-push",
    "pr-publisher",
    "fix-commit.md",
    ("{pr}",),
)

_IMPLEMENT = WorkflowDefinition(
    name="implement",
    stages=(
        StageDefinition(
            "I1",
            "impliment-task",
            "implementer",
            "impliment-task.md",
            ("{prompt_rel}",),
        ),
        StageDefinition(
            "I2",
            "test",
            "tester",
            "test.md",
            extra=TEST_CONTEXT_EXTRA,
        ),
        # S1.1 (design §17 Z11): traceability is the first **path-scoped** stage. The
        # condition is carried (the expander has no change set) and the *paths* are always
        # the repo's, never a registry default — a toolkit-hardcoded set would be a product
        # literal (design §7.1) and would skip the stage in every repo that lacks those
        # directories. With no declared ``when_paths`` the stage is unconditional, exactly
        # as it was before this token existed.
        StageDefinition(
            "I3",
            "update-traceability",
            "implementer",
            "update-traceability.md",
            ("{branch}",),
            when=WHEN_PATHS_CHANGED,
        ),
        StageDefinition(
            "I4",
            "update-architecture",
            "implementer",
            "update-architecture.md",
            ("{branch}", "{base_branch}"),
        ),
        StageDefinition(
            "I5",
            "record-implementation-results",
            "recorder",
            "record-implementation-results.md",
            ("{branch}",),
        ),
        # X1.1 (design §17 Z3): the narrative summary reads the build results I5 just wrote
        # and owns `<branch>/summary.md` beside them. A separate **core** stage (a generic
        # artifact like I5, unlike the repo-specific I3/I4) immediately after the record
        # sync point, because it has nothing to summarise until I5 has finished, and before
        # the tick and I6 so the summary lands uncommitted in the task's own PR. It runs no
        # gate of its own (I5 is the only stage that buys the whole-repo gate) and sits
        # serially between I5 and I7 — never in a `parallel_group`. Position is
        # load-bearing for `validate_stage_list`'s reorder rule, like I7's.
        StageDefinition(
            "I8",
            "summarize-implementation-results",
            "recorder",
            "summarize-implementation-results.md",
            ("{branch}",),
        ),
        # X1.2 (design §17 Z6): the integration-test guide is the **recipe** for a test AIDT
        # never runs (§1.3's deployed-integration-tests non-goal holds — a human runs it).
        # A separate **core** stage, like I8: generic, unconditional (no `when=`), and it
        # reads the build results I5 just wrote, so it follows the summary and stays before
        # the tick and I6 (uncommitted, in the task's own PR). Serially between I8 and I7 —
        # never in a `parallel_group`. Position is load-bearing for
        # `validate_stage_list`'s reorder rule, as I7's and I8's are. The prompt file is
        # deliberately not `integration-tests.md`: that is a product prompt a target repo
        # would shadow by filename (D14), silently swapping this stage's prompt.
        StageDefinition(
            "I9",
            "write-integration-test-guide",
            "recorder",
            "write-integration-test-guide.md",
            ("{branch}",),
        ),
        # H3.1: the roadmap tick is its own **core** stage, after the record sync point
        # and before the approval gate and I6, so the tick lands in the task's own PR
        # (I6 is the single owner of the commit, design §8.2). Registry order is
        # load-bearing: ``validate_stage_list``'s reorder rule compares the declared
        # core subsequence to this order.
        _ROADMAP_TICK_STAGE,
        StageDefinition("I6", "pr", "pr-publisher", "pr.md", ("{task_id}",)),
    ),
    # §3.4 ``parallel_groups`` / R11: the safe pair ``implement.py`` used to hardcode. I2
    # and I4 touch disjoint trees; E4.4 schedules it when the config declares no groups.
    parallel_groups=(("test", "update-architecture"),),
)

_PROMPT = WorkflowDefinition(
    name="prompt",
    stages=(
        StageDefinition(
            "P1",
            "task-prompt",
            "task-author",
            "task-prompt.md",
            ("{phase}", "{epic}", "{task}"),
        ),
    ),
    loop=LoopDefinition(
        id="P2",
        kind=LOOP_REVIEW_ROUNDS,
        head=(
            StageDefinition(
                "P2",
                "task-review-{iteration}",
                "task-reviewer",
                "task-review.md",
                ("{rel}",),
                brief=BRIEF_DELTA,
            ),
        ),
        body=(
            StageDefinition(
                PROMPT_FIX_BLOCKING,
                "task-review-fixes-{iteration}-{index}",
                "task-fixer",
                "task-review-fixes.md",
                ("{rel}",),
                when=WHEN_BLOCKING,
            ),
            StageDefinition(
                PROMPT_FIX_COULD_FIX,
                "task-review-fixes-{iteration}-{index}",
                "task-fixer",
                "task-review-fixes.md",
                ("{rel}",),
                when=WHEN_COULD_FIX,
            ),
            StageDefinition(
                PROMPT_FIX_FALLBACK,
                "task-review-fixes-{iteration}",
                "task-fixer",
                "task-review-fixes.md",
                ("{rel}",),
                when=WHEN_UNPARSEABLE,
            ),
        ),
        tail=(
            StageDefinition(
                PROMPT_RECONCILE,
                "task-review-reconcile-{iteration}",
                "task-fixer",
                "task-review-fixes.md",
                ("{rel}",),
                brief=BRIEF_RECONCILE,
            ),
        ),
        terminal_last=True,
        unprimed_first=True,
    ),
)

_REVIEW = WorkflowDefinition(
    name="review",
    stages=(
        StageDefinition("R1", "code-review", "code-reviewer", "code-review.md"),
        StageDefinition(
            "R2",
            "review-findings-to-github",
            "review-publisher",
            "review-findings-to-github.md",
            ("{pr}",),
            extra=MANIFEST_EXTRA,
            when=WHEN_FINDINGS,
        ),
    ),
)

#: The approval stage is one logical stage (§3.5 ``A1``) that two workflows run: ``approve``
#: once, ``fix`` at the head of every approval round (``round{N}-…``, §8.4's ``◇``). Same
#: agent, prompt and variables in both, so the id is shared.
_APPROVE_STAGE = StageDefinition(
    "A1",
    "approve-review-followups",
    "review-approver",
    "approve-review-followups.md",
    ("{pr}",),
)

_APPROVE = WorkflowDefinition(name="approve", stages=(_APPROVE_STAGE,))

_FIX = WorkflowDefinition(
    name="fix",
    stages=(
        StageDefinition(
            "A1",
            "round{round_index}-approve-review-followups",
            "review-approver",
            "approve-review-followups.md",
            ("{pr}",),
        ),
    ),
    loop=LoopDefinition(
        id="F",
        kind=LOOP_FIX_ITERATIONS,
        head=(
            # 05-P1.2 (Z9's close-after-push half): ``{closing_body}`` is the absolute path
            # the fixer writes its closing comment body to and the workflow reads back as
            # ``close --body-file`` once ``F5`` has proved the push. F1 therefore records the
            # fix and writes the body; it never posts ``Status: fixed`` and never closes.
            StageDefinition(
                "F1",
                "iter{iteration}-fix-next-review-followup",
                "fixer",
                "fix-next-review-followup.md",
                ("{pr}", "{closing_body}"),
            ),
            StageDefinition(
                "F2",
                "iter{iteration}-test",
                "tester",
                "test.md",
                extra=FIX_TEST_CONTEXT_EXTRA,
            ),
            StageDefinition(
                "F3",
                "iter{iteration}-code-review",
                "code-reviewer",
                "code-review.md",
            ),
        ),
        body=(
            StageDefinition(
                "F4",
                "iter{iteration}-review-findings-to-github",
                "review-publisher",
                "review-findings-to-github.md",
                ("{pr}",),
                extra=MANIFEST_EXTRA,
                when=WHEN_FINDINGS,
            ),
        ),
        # §8.4's ``--max-iterations`` bound. The loop is re-derived from GitHub state each
        # iteration (`review_followup.py select`), so it expands one iteration at a time.
        terminal_last=False,
    ),
    # H3.3: the shared roadmap tick, emitted **once per run** after the loop breaks on
    # ``select`` exit ``EXIT_NONE_AVAILABLE`` — never on the per-iteration expansion
    # (``include_post_loop``). Same definition object as ``implement``'s I7.
    # 05-P1.1 (Z9): ``F5`` follows it, so a converged run publishes the accumulated change
    # set (the fix edits plus the tick if it flipped) instead of leaving it uncommitted.
    post_loop=(_ROADMAP_TICK_STAGE, _COMMIT_PUSH_STAGE),
)

#: The default registry, keyed by workflow name. Immutable: a caller cannot replace or
#: reorder a default in place.
DEFAULTS: Mapping[str, WorkflowDefinition] = MappingProxyType(
    {
        "prompt": _PROMPT,
        "implement": _IMPLEMENT,
        "review": _REVIEW,
        "fix": _FIX,
        "approve": _APPROVE,
    }
)


def get_workflow(name: str) -> WorkflowDefinition:
    """The default definition for ``name``, or :class:`UnknownWorkflowError`."""
    try:
        return DEFAULTS[name]
    except KeyError:
        raise UnknownWorkflowError(
            f"no default stage chain for workflow `{name}`; "
            f"known: {', '.join(sorted(DEFAULTS))}"
        ) from None


def stage(workflow: str, stage_id: str) -> StageDefinition:
    """The (unrendered) definition of ``stage_id`` in ``workflow``.

    Loop stages are searchable by their id too (``P2``, ``F1``–``F4``, and the loop-internal
    ``P2-fix-*``/``P2-reconcile`` labels), and since H3.3 so is the post-loop half
    (``fix``'s shared ``I7``, and since 05-P1.1 its ``F5``).
    """
    definition = get_workflow(workflow)
    candidates = list(definition.stages)
    if definition.loop is not None:
        candidates.extend(definition.loop.head)
        candidates.extend(definition.loop.body)
        candidates.extend(definition.loop.tail)
    candidates.extend(definition.post_loop)
    for candidate in candidates:
        if candidate.id == stage_id:
            return candidate
    raise UnknownStageError(
        f"workflow `{workflow}` has no stage id `{stage_id}`"
    )


def stages_by_id(workflow: str) -> Mapping[str, StageDefinition]:
    """Every stage definition of ``workflow`` keyed by id (read-only)."""
    definition = get_workflow(workflow)
    found: dict[str, StageDefinition] = {}
    for candidate in definition.stages:
        found[candidate.id] = candidate
    if definition.loop is not None:
        for candidate in (*definition.loop.head, *definition.loop.body, *definition.loop.tail):
            found[candidate.id] = candidate
    for candidate in definition.post_loop:
        found[candidate.id] = candidate
    return MappingProxyType(found)


def validate_parallel_groups(
    workflow: str, groups: Sequence[Sequence[str]]
) -> list[Issue]:
    """Fail-closed checks on a workflow's ``parallel_groups`` (R11, EXTRACTION.md §3.5).

    §3.5's rule is "validate that every member exists and is not ordered against another
    member". Pure: no I/O, no mutation of ``groups``, no workflow import — the caller
    passes the **effective** groups in (a target repo's declared list, or the registry
    default above), exactly as :func:`aidw.runner.plan_stages` takes the resolved config.

    *Every member exists*: each member must be a stage **name**
    (:attr:`StageDefinition.name`, R6) of ``workflow``'s default ``stages`` — never a
    stage id, never §3.4's illustrative semantic ids. An unknown member is one ``ERROR``
    naming the workflow, the group index and the member.

    *Not ordered against another member*: the spec fixes the rule, not the mechanism
    (R11 forbids inferring more safety than is declared), so the rejections are exactly the
    two a single-trigger scheduler cannot honour — a member listed more than once in one
    group, and a member appearing in more than one group. Both order one stage against a
    conflicting concurrency set (or against itself).

    An empty *inner* group has no schedulable position, so it is one ``ERROR`` naming the
    workflow and the group index; an empty *list* of groups (``[]``) is valid and means
    "no parallel groups" (serial). Deliberately **not** validated: file-ownership safety,
    adjacency and semantic dependencies such as ``test`` before ``update-traceability`` —
    none is inferable, and R11 leaves them to the repo's declaration.

    Raises :class:`UnknownWorkflowError` for a workflow with no default chain: that is a
    programming error, not a config one.
    """
    definition = get_workflow(workflow)
    names = [stage.name for stage in definition.stages]
    known = set(names)
    #: ``error: workflows.<name>.parallel_groups: group [i]: …`` — the same shape as the
    #: target-config loader's dotted-path issues, so ``format_issues`` output is uniform.
    source = f"workflows.{workflow}.parallel_groups"
    issues: list[Issue] = []
    #: First group each member appeared in, for the cross-group rejection.
    seen_in: dict[str, int] = {}
    for index, group in enumerate(groups):
        members = list(group)
        if not members:
            issues.append(
                Issue(
                    ERROR,
                    source,
                    f"group [{index}] names no stage; a parallel group must have at "
                    "least one member",
                )
            )
            continue
        in_group: set[str] = set()
        for member in members:
            if not isinstance(member, str) or member not in known:
                issues.append(
                    Issue(
                        ERROR,
                        source,
                        f"group [{index}]: unknown stage name `{member}`; "
                        f"`{workflow}` stages are: {', '.join(names)}",
                    )
                )
                continue
            if member in in_group:
                issues.append(
                    Issue(
                        ERROR,
                        source,
                        f"group [{index}]: stage `{member}` is listed more than once",
                    )
                )
                continue
            in_group.add(member)
            if member in seen_in:
                issues.append(
                    Issue(
                        ERROR,
                        source,
                        f"group [{index}]: stage `{member}` already appears in "
                        f"group [{seen_in[member]}]",
                    )
                )
                continue
            seen_in[member] = index
    return issues


def _format_stage_order(ids: Sequence[str]) -> str:
    """A stage-id order for a message (``I1, I2, I5``); ``(none)`` when empty."""
    return ", ".join(ids) if ids else "(none)"


def validate_stage_list(
    workflow: str, stages: Sequence[Mapping[str, Any]]
) -> list[Issue]:
    """Fail-closed checks on a repo-declared ``workflows.<name>.stages`` list (D12/D13).

    EXTRACTION.md §3.5's rules, executable: a repo may replace a prompt, add a stage and
    disable a **repo-optional** stage (:data:`REPO_OPTIONAL_IDS`); it may **not** reorder,
    remove or disable a **core** stage (D12), and it cannot declare a loop stage at all —
    those are generated by :func:`expand` and are not flat list entries.

    Pure: no I/O, no mutation of ``stages``, no workflow import — the caller passes the
    resolved ``workflows.<name>.stages`` value in (the ``_workflow_value`` shape: plain
    ``id``/``enabled``/``prompt``/``agent`` mappings), exactly as
    :func:`validate_parallel_groups` takes the effective groups. The declared-ness test
    stays with the caller: when the config did not declare the list the entry is absent
    and there is nothing to validate, because the registry's own list is all that runs.

    Classification comes from the registry alone, with no other category:

    * **loop ids** — every id :func:`stages_by_id` knows that neither the static
      :attr:`WorkflowDefinition.stages` nor the :attr:`WorkflowDefinition.post_loop` half
      does (``P2``, the ``P2-fix-*`` / ``P2-reconcile`` loop labels, ``F1``–``F4``).
      Deliberately not ``STAGE_IDS`` membership: ``STAGE_IDS`` holds ``P2`` but not its
      fix/reconcile labels, which would make ``P2-fix-blocking`` look repo-added and be
      silently double-planned. H3.3 req 2: the post-loop half is subtracted too, or
      ``fix``'s ``I7`` would be misclassified as a loop id and refused as undeclarable
      exactly where a repo wants to declare the canonical ``[A1, I7, F5]``.
    * **core ids** — the static stage ids **followed by the post-loop ids**, minus
      :data:`REPO_OPTIONAL_IDS` (``I1``, ``I2``, ``I5``, ``I8``, ``I9``, ``I7``, ``I6`` for
      ``implement``; ``A1``, ``I7``, ``F5`` for ``fix``; ``P1``; ``R1``/``R2``). One
      declared list covers both halves (H3.3 req 2): the post-loop ids are declared
      **after** every static core id, so there is one core order — static-then-post-loop —
      for the reorder rule, and a missing ``I7`` in ``fix`` is the same removal ``ERROR``
      as a missing ``A1`` (and, since 05-P1.1, a missing ``F5``).
    * **repo-optional ids** — :data:`REPO_OPTIONAL_IDS` (``I3``/``I4``).
    * anything else is a **repo-added** stage and is accepted here (its fields are
      E4.5b's contract, not this validator's).

    Per-entry rejections (one ``ERROR`` each, naming the workflow path, the stage id and
    the rule): a loop id is refused whether or not it is enabled — with
    ``enabled: false`` it would otherwise read as a legitimate optional disable, and any
    other shape would be double-planned — and a core id carrying ``enabled: false`` is
    refused. Entries the target-config loader already errored on (not a mapping, no/empty
    ``id``) are skipped: re-reporting them here would duplicate that refusal.

    Whole-list checks, because a declared list **replaces** the toolkit's list wholesale
    (§3.4) and is never merged element-wise:

    * **removal** — every missing core id is one ``ERROR``, so ``stages: []`` reports one
      per core stage instead of silently planning defaults the repo asked away;
    * **duplicate** — each core id declared more than once is one ``ERROR``;
    * **reorder** — the declared core-id subsequence (duplicates excluded) must equal the
      registry's static-then-post-loop core order. Repo-added and repo-optional stages
      may sit anywhere;
      a mismatch is **one** ``ERROR`` for the list, naming the workflow and both orders.
      A removed core stage makes the subsequence shorter than the registry order too, so
      it reports removal *and* reorder — never one blended message.

    Raises :class:`UnknownWorkflowError` for a workflow with no default chain: that is a
    programming error, not a config one (mirroring :func:`validate_parallel_groups`).
    """
    definition = get_workflow(workflow)
    static_ids = [item.id for item in definition.stages]
    post_loop_ids = [item.id for item in definition.post_loop]
    # Loop stages are the ids the expansion can emit that are neither flat stage entries
    # nor the post-loop half (H3.3 req 2: a two-way split would call `fix`'s I7 a loop id).
    loop_ids = (
        set(stages_by_id(workflow)) - set(static_ids) - set(post_loop_ids)
    )
    core_ids = [
        stage_id
        for stage_id in (*static_ids, *post_loop_ids)
        if stage_id not in REPO_OPTIONAL_IDS
    ]
    core_set = set(core_ids)
    #: ``error: workflows.<name>.stages: …`` — the target-config loader's dotted-path
    #: shape, so ``format_issues`` output is uniform across every refusal.
    source = f"workflows.{workflow}.stages"
    issues: list[Issue] = []

    declared_counts: dict[str, int] = {}
    declared_core_order: list[str] = []
    for entry in list(stages):
        if not isinstance(entry, Mapping):
            # The loader already refused this entry (``must be a mapping``).
            continue
        stage_id = entry.get("id")
        if not isinstance(stage_id, str) or not stage_id:
            # Same: a missing/empty ``id`` is a loader ERROR, skipped rather than twice.
            continue
        declared_counts[stage_id] = declared_counts.get(stage_id, 0) + 1
        enabled = entry.get("enabled", True)
        if stage_id in loop_ids:
            # ``enabled: false`` on a loop id must never read as a legitimate optional
            # disable: the loop is core, so it is refused for the disable rule too.
            rule = (
                "core stage cannot be disabled"
                if enabled is False
                else "loop stages are generated by `expand`, not declarable"
            )
            issues.append(Issue(ERROR, source, f"stage `{stage_id}`: {rule}"))
            continue
        if stage_id not in core_set:
            # Repo-optional (any ``enabled``) or repo-added: accepted here.
            continue
        if stage_id not in declared_core_order:
            declared_core_order.append(stage_id)
        if enabled is False:
            issues.append(
                Issue(
                    ERROR,
                    source,
                    f"stage `{stage_id}`: core stage cannot be disabled",
                )
            )

    for stage_id in core_ids:
        if stage_id not in declared_counts:
            issues.append(
                Issue(
                    ERROR,
                    source,
                    f"stage `{stage_id}`: core stage cannot be removed",
                )
            )
    for stage_id in core_ids:
        if declared_counts.get(stage_id, 0) > 1:
            issues.append(
                Issue(
                    ERROR,
                    source,
                    f"stage `{stage_id}`: core stage declared more than once",
                )
            )
    if declared_core_order != core_ids:
        issues.append(
            Issue(
                ERROR,
                source,
                f"`{workflow}`: core stage cannot be reordered: declared "
                f"[{_format_stage_order(declared_core_order)}] but the registry order is "
                f"[{_format_stage_order(core_ids)}]",
            )
        )
    return issues


# --------------------------------------------------------------------------- #
# Expansion — pure and deterministic
# --------------------------------------------------------------------------- #


def _render(template: str, fields: Mapping[str, Any], *, where: str) -> str:
    """Render one ``str.format`` template, naming the stage and field on failure.

    ``str.format`` raises three unrelated errors for a bad template/field set
    (``KeyError``, ``IndexError``, ``ValueError``); they all mean the same thing to a
    caller — the expansion was asked for a stage it cannot render — so they collapse into
    :class:`StageFieldError` instead of leaking an opaque format error.
    """
    try:
        return template.format(**fields)
    except KeyError as exc:
        raise StageFieldError(
            f"{where} needs expansion field `{exc.args[0]}`"
        ) from None
    except (IndexError, ValueError) as exc:
        raise StageFieldError(f"{where} could not be rendered: {exc}") from None


def _require(fields: Mapping[str, Any], name: str, *, where: str) -> Any:
    if name not in fields:
        raise StageFieldError(f"{where} needs expansion field `{name}`")
    return fields[name]


def _require_int(fields: Mapping[str, Any], name: str, *, where: str) -> int:
    value = _require(fields, name, where=where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise StageFieldError(f"{where} field `{name}` must be an int, got {value!r}")
    if value < 1:
        raise StageFieldError(f"{where} field `{name}` must be >= 1, got {value}")
    return value


def _plan(definition: StageDefinition, fields: Mapping[str, Any]) -> PlannedStage:
    """Render one stage definition into a planned stage (new objects, defaults untouched)."""
    where = f"stage {definition.id} of `{definition.name}`"
    return PlannedStage(
        id=definition.id,
        name=_render(definition.name, fields, where=f"{where} name"),
        agent=definition.agent,
        prompt_file=definition.prompt_file,
        variables=tuple(
            _render(variable, fields, where=f"{where} variable") for variable in definition.variables
        ),
        extra=_render(definition.extra, fields, where=f"{where} extra")
        if definition.extra
        else "",
        when=definition.when,
        brief=definition.brief,
    )


def _expand_static(
    definition: WorkflowDefinition, fields: Mapping[str, Any], planned: list[PlannedStage]
) -> None:
    findings = fields.get("findings")
    for item in definition.stages:
        # ``if findings:`` (§8.3) is only resolvable when the caller said whether these
        # findings exist; when it did not, the stage is planned with the condition carried
        # so the workflow can decide at run time (``fix``'s dry run does exactly that).
        if item.when == WHEN_FINDINGS and findings is False:
            continue
        planned.append(_plan(item, fields))


def _expand_prompt_loop(
    loop: LoopDefinition, fields: Mapping[str, Any], planned: list[PlannedStage]
) -> None:
    """Expand the post-phase-02 review loop (design §8.1, H6/G2/L4.1, L2.3, L3.4).

    One review round per iteration, then — while the iteration still has revision budget —
    that round's fix batch and its single reconcile stage. ``terminal_last`` stops the body
    on the final iteration, so the last thing a non-approving prompt sees is a review.
    """
    max_revisions = _require_int(fields, "max_revisions", where="prompt loop")
    rounds_value = fields.get("rounds", ())
    if isinstance(rounds_value, (str, bytes)) or not isinstance(rounds_value, Sequence):
        raise StageFieldError(
            "prompt loop field `rounds` must be a sequence of FixBatch"
        )
    rounds = tuple(rounds_value)
    if len(rounds) > max_revisions - 1:
        raise RevisionBudgetError(
            f"prompt loop received {len(rounds)} fix batch(es) for max_revisions="
            f"{max_revisions}; at most {max_revisions - 1} may run and the last review is "
            "review-only"
        )

    iteration = 1
    while True:
        local = dict(fields)
        local["iteration"] = iteration
        # Round 1 is deliberately unprimed (L2.3): no delta brief, because the independent
        # first sample must not anchor on a previous review. Rounds 2+ carry the brief.
        unprimed = loop.unprimed_first and iteration == 1
        for item in loop.head:
            planned.append(
                _replace_brief(_plan(item, local), "" if unprimed else item.brief)
            )

        if loop.terminal_last and iteration >= max_revisions:
            break
        if iteration > len(rounds):
            break

        batch = rounds[iteration - 1]
        if not isinstance(batch, FixBatch):
            raise StageFieldError(
                f"prompt loop field `rounds[{iteration - 1}]` must be a FixBatch, "
                f"got {type(batch).__name__}"
            )
        planned.extend(_expand_fix_batch(loop, batch, local))
        planned.extend(_plan(item, local) for item in loop.tail)
        iteration += 1


def _expand_fix_batch(
    loop: LoopDefinition, batch: FixBatch, fields: Mapping[str, Any]
) -> list[PlannedStage]:
    """The fix stages of one batch: per blocking finding, combined could-fix, or fallback."""
    blocking = tuple(batch.blocking)
    could_fix = tuple(batch.could_fix)
    if batch.unparseable:
        # One stage carries the whole review verbatim (design §8.1's fallback), because a
        # review that did not parse into findings cannot be split per finding.
        whole = render_whole_review_extra(batch.review_text)
        return [
            _replace_extra(_plan(item, fields), whole)
            for item in loop.body
            if item.when == WHEN_UNPARSEABLE
        ]

    total = len(blocking) + (1 if could_fix else 0)
    planned: list[PlannedStage] = []
    for index, finding in enumerate(blocking, start=1):
        local = dict(fields)
        local["index"] = index
        for item in loop.body:
            if item.when != WHEN_BLOCKING:
                continue
            stage = _plan(item, local)
            planned.append(
                _replace_extra(
                    stage,
                    render_finding_block(finding, index=index, total=total),
                )
            )
    if could_fix:
        index = len(blocking) + 1
        local = dict(fields)
        local["index"] = index
        combined = render_could_fix_block(list(could_fix))
        for item in loop.body:
            if item.when != WHEN_COULD_FIX:
                continue
            planned.append(_replace_extra(_plan(item, local), combined))
    return planned


def _replace_extra(stage: PlannedStage, extra: str) -> PlannedStage:
    """A copy of ``stage`` carrying a runtime-rendered ``extra`` (never mutates it)."""
    return replace(stage, extra=extra)


def _replace_brief(stage: PlannedStage, brief: str) -> PlannedStage:
    """A copy of ``stage`` carrying ``brief`` (never mutates the definition)."""
    return replace(stage, brief=brief)


def _expand_fix_loop(
    loop: LoopDefinition, fields: Mapping[str, Any], planned: list[PlannedStage]
) -> None:
    """Expand one ``fix`` iteration (§8.4).

    The iteration count is external GitHub state (``review_followup.py select``), not a
    registry input, so the caller expands the iteration it is planning; F4 is emitted with
    ``when=findings`` because F3's verdict is only known after F3 runs (§8.4's dry run
    plans it too).
    """
    iteration = _require_int(fields, "iteration", where="fix loop")
    local = dict(fields)
    local["iteration"] = iteration
    for item in loop.head:
        planned.append(_plan(item, local))
    for item in loop.body:
        planned.append(_plan(item, local))
    for item in loop.tail:
        planned.append(_plan(item, local))


def expand(
    workflow: str, /, *, include_post_loop: bool = False, **fields: Any
) -> tuple[PlannedStage, ...]:
    """The ordered stages ``workflow`` runs for these concrete inputs.

    Pure and deterministic: no process, no filesystem, no mutation of ``DEFAULTS`` or of
    ``fields``. Concrete inputs per workflow:

    * ``implement`` — ``prompt_rel``, ``branch``, ``task_id``, ``base_branch``
      (default ``"main"``, matching ``build_plan``), ``roadmap_file`` and
      ``checkbox_id`` (I7's ``$1``/``$2``: the entry's own absolute roadmap path and its
      task id without the phase prefix, H3.1).
    * ``prompt`` — ``phase``, ``epic``, ``task``, ``rel``, ``max_revisions``, and ``rounds``
      (one :class:`FixBatch` per fixing round, in order).
    * ``review`` — ``pr``, ``manifest_path``, ``findings`` (``True``/``False``; ``False``
      omits R2).
    * ``fix`` — ``pr``, ``round_index``, ``iteration``, ``manifest_path``,
      ``closing_body`` (05-P1.2: F1's absolute closing-body path), plus ``roadmap_file`` and
      ``checkbox_id`` **for the post-loop half only** (H3.3 req 1: the shared ``I7`` renders
      them, and it is emitted only when ``include_post_loop`` is true; 05-P1.1's ``F5``
      renders ``{pr}`` and 05-P1.2's close step renders no prompt at all).
    * ``approve`` — ``pr``.

    ``include_post_loop`` (H3.3 req 1) appends :attr:`WorkflowDefinition.post_loop` after
    the static and loop halves. It defaults to ``False`` because ``expand("fix", …)`` *is*
    the per-iteration expansion (``fix.py:_planned_iteration`` calls it once per
    iteration): emitting the half unconditionally would plan — and dry-run print — the
    roadmap tick and ``F5`` once per iteration instead of once per run. ``fix`` asks for
    it in one named post-loop planning call after the loop breaks. ``include_post_loop``
    is keyword-only so it can never collide with an expansion field.

    ``manifest_path`` is the findings manifest's **absolute** path in the run directory.
    It is rendered into the publisher stage's ``extra``, whose agent runs with the target
    repo as its cwd — a relative value made the publisher look for the manifest in the
    target tree and refuse to publish (E7.3's PR 110).

    Raises :class:`UnknownWorkflowError`, :class:`StageFieldError` or
    :class:`RevisionBudgetError` — never returns a silently shortened plan.
    """
    definition = get_workflow(workflow)
    local = dict(fields)
    if definition.name == "implement":
        local.setdefault("base_branch", "main")
    planned: list[PlannedStage] = []
    _expand_static(definition, local, planned)
    if definition.loop is not None:
        if definition.loop.kind == LOOP_REVIEW_ROUNDS:
            _expand_prompt_loop(definition.loop, local, planned)
        elif definition.loop.kind == LOOP_FIX_ITERATIONS:
            _expand_fix_loop(definition.loop, local, planned)
        else:  # pragma: no cover - unreachable while the defaults are typed this way
            raise StageRegistryError(
                f"workflow `{workflow}` declares unknown loop kind "
                f"`{definition.loop.kind}`"
            )
    # H3.3: the post-loop half, on request only (see the docstring). Ordered last so the
    # plan is always static -> loop -> post-loop; 05-P1.1's ``F5`` therefore follows ``I7``.
    if include_post_loop:
        planned.extend(_plan(item, local) for item in definition.post_loop)
    return tuple(planned)
