"""The default stage registry: AIDT's workflow chains as data (EXTRACTION.md §3.5, E4.1).

This module is the single declarative home of *which stage runs where*: the six-stage
``implement`` chain (design §8.2), the post-phase-02 ``prompt`` review loop (§8.1), the
``review`` pair (§8.3), the ``fix`` iteration loop (§8.4) and the single ``approve`` stage
(§8.5). It is **data plus one pure expander**: nothing here spawns a process, touches the
filesystem, or imports a workflow module.

Dependency direction (EXTRACTION.md §3.5, task E4.1's trap list):

* :mod:`aidw.workflows.implement` → this module is the direction E4.3 installs
  (``build_plan`` reads the registry), so importing :class:`PlanStage` back out of the
  workflow would be a cycle. The registry therefore owns its own stage type,
  :class:`StageDefinition`, carrying the same §3.5 fields.
* :mod:`aidw.target_config` must never import a workflow module (its docstring states
  why), so the registry imports nothing from the config or workflow layers; it may be
  imported *by* both. ``workflows.<name>.stages`` config entries stay the separate
  ``StageConfig`` shape — E4.3 merges them, this task only seeds the defaults.
* The only import is :mod:`aidw.findings`, a leaf module that renders the review-finding
  blocks and the publisher's manifest brief. Reusing it (rather than copying the prose)
  keeps one source of truth for text the fix and publisher stages receive.

Stage-id vocabulary (R6 — ids are *retained*, never renamed to the semantic
``author``/``review``/``implement`` of §3.4's illustrative YAML): ``I1``–``I6``, ``P1``,
``P2``, ``R1``, ``R2``, ``F1``–``F4``, ``A1`` (:data:`STAGE_IDS`). Two different fields are
kept apart on purpose — ``id`` is the retained key (``"I1"``) and ``name`` is the runtime
stage name (``"impliment-task"``), which is what ``state.json`` and the run artifacts key
on. §3.4's ``author``/``review``/... ids illustrate the *schema shape* only.

Loops are not flat lists (design §8's ``⟳``/``if`` notation):

* :class:`LoopDefinition` is the minimal bounded-loop shape: ``head`` stages run every
  iteration, ``body``/``tail`` only for an iteration that still has budget, and
  ``terminal_last`` makes the final iteration head-only. That single boolean is H6/G2/L4.1
  ("the ``max_revisions``-th review is review-only; a review is always the last stage").
  ``unprimed_first`` is L2.3 ("round 1 is deliberately unprimed" — no delta brief).
* :class:`StageDefinition.when` is the ``if`` of §8.3/§8.4 (``if findings: → R2``).
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
  :func:`render_whole_review_extra`. The workflow modules keep their own copies until E4.3
  deletes them; ``tests/test_stage_registry.py`` pins the two against each other, so the
  duplication can never drift silently.
* **What stays in the workflow**: the L2.4 evidence pointer, the ``git diff`` that feeds a
  delta/reconcile brief, the L3.3 prompt snapshots and the gates (``◇``) are not stage
  data. ``extra`` here is the stage's *body* text; the workflow composes the pointer in
  front of it, exactly as :func:`aidw.workflows.prompt._with_evidence` does today.

Not wired yet by design: ``ConfigDefaults.workflows``/``resolve_config`` (E4.3),
``parallel_groups`` validation and replacement (E4.4), core-vs-repo-optional enforcement
(E4.5), agent/model/thinking overrides (E4.6) and the fixture integration test (E4.7).
The ``implement`` default's :attr:`WorkflowDefinition.parallel_groups` is recorded here as
data only; ``implement.py`` keeps its hardcoded pair until E4.4.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from aidw.findings import (
    MANIFEST_EXTRA,
    ParsedFinding,
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
        "P1",
        "P2",
        "R1",
        "R2",
        "F1",
        "F2",
        "F3",
        "F4",
        "A1",
    }
)

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
    """A workflow's static chain, optional loop, and parallel-safe stage-name pairs."""

    name: str
    stages: tuple[StageDefinition, ...] = ()
    loop: LoopDefinition | None = None
    #: R11/§3.4 ``parallel_groups``: stage *names*, not ids, because that is what
    #: ``implement.py``'s ``by_name`` lookup keys on. Recorded as data; E4.4 owns wiring
    #: and validation.
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
# `extra` text reproduced from the workflow modules (pinned by the tests)
# --------------------------------------------------------------------------- #

#: I2's test context — byte-identical to ``aidw/workflows/implement.py:_TEST_CONTEXT``.
TEST_CONTEXT_EXTRA = """\

## Stage context (provided by aidw)

- Task: {task_id}
- Branch: {branch}
- Task prompt: {prompt_rel}

Read the task prompt above, follow its acceptance criteria, and prove them. Leave your
changes uncommitted in the working tree.
"""

#: F2's re-test context — byte-identical to ``aidw/workflows/fix.py:_TEST_EXTRA``.
FIX_TEST_CONTEXT_EXTRA = """\

## Stage context (provided by aidw)

This re-verifies a single approved review follow-up fix for PR #{pr} (iteration {iteration}).
Prove the fix and its acceptance criteria. This stage does not fix implementation code:
report `Fail` and hand a real defect back to `/fix-next-review-followup`. Leave changes
uncommitted in the working tree.
"""

#: Instruction prepended to every review round after the first (L2.3) — byte-identical to
#: ``aidw/workflows/prompt.py:_DELTA_BRIEF_INSTRUCTION``.
DELTA_BRIEF_INSTRUCTION = """\
## Delta brief — resolve the previous review before raising new findings

This is a later review round, not the first. For **each** finding in the previous review
below, state a per-finding resolution verdict of exactly `resolved`, `not resolved`, or
`newly contradicted` before you raise any new finding. Judge `resolved` only from the
current prompt and the diff that follows. New findings must be genuinely new: never
re-litigate a finding you judged `resolved`."""

#: Note used when the prompt diff cannot be produced — byte-identical to
#: ``aidw/workflows/prompt.py:_DIFF_UNAVAILABLE``.
DIFF_UNAVAILABLE = (
    "The prompt diff for this round is unavailable (`git diff` could not be produced); "
    "review the prompt file itself for its current state."
)

#: Instruction prepended to the single reconcile stage after a fix batch (L3.4) —
#: byte-identical to ``aidw/workflows/prompt.py:_RECONCILE_INSTRUCTION``.
RECONCILE_INSTRUCTION = """\
## Reconcile the fix batch

One or more fix stages have just edited this prompt in isolation. Compare the fixed
prompt against the full review text and the combined diff below. Repair every
cross-section contradiction the edits introduced and address any finding the batch left
unaddressed. Do not review or re-litigate the findings; make the prompt internally
consistent with the review."""


def render_delta_brief(*, previous_review: str, diff: str | None) -> str:
    """Assemble a later review round's ``extra`` (instruction, prior review, diff) (L2.3).

    Pure: ``diff`` is the already-produced unified diff (or ``None``/unavailable, which
    becomes :data:`DIFF_UNAVAILABLE`); producing it is the workflow's job, because only it
    has the two prompt snapshots. Mirrors
    :func:`aidw.workflows.prompt._render_delta_brief` after that function has resolved its
    inputs, so the wording is identical.
    """
    return "\n\n".join(
        [
            DELTA_BRIEF_INSTRUCTION,
            "### Previous review\n\n" + previous_review,
            "### Prompt diff since that review\n\n"
            + (diff if diff is not None else DIFF_UNAVAILABLE),
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
        StageDefinition(
            "I3",
            "update-traceability",
            "implementer",
            "update-traceability.md",
            ("{branch}",),
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
        StageDefinition("I6", "pr", "pr-publisher", "pr.md", ("{task_id}",)),
    ),
    # §3.4 ``parallel_groups`` / R11. Today's pair in ``implement.py``'s ``by_name``
    # lookup: I2 and I4 touch disjoint trees. Data only until E4.4.
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
            StageDefinition(
                "F1",
                "iter{iteration}-fix-next-review-followup",
                "fixer",
                "fix-next-review-followup.md",
                ("{pr}",),
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
    ``P2-fix-*``/``P2-reconcile`` labels).
    """
    definition = get_workflow(workflow)
    candidates = list(definition.stages)
    if definition.loop is not None:
        candidates.extend(definition.loop.head)
        candidates.extend(definition.loop.body)
        candidates.extend(definition.loop.tail)
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
    return MappingProxyType(found)


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


def expand(workflow: str, /, **fields: Any) -> tuple[PlannedStage, ...]:
    """The ordered stages ``workflow`` runs for these concrete inputs.

    Pure and deterministic: no process, no filesystem, no mutation of ``DEFAULTS`` or of
    ``fields``. Concrete inputs per workflow:

    * ``implement`` — ``prompt_rel``, ``branch``, ``task_id``, ``base_branch``
      (default ``"main"``, matching ``build_plan``).
    * ``prompt`` — ``phase``, ``epic``, ``task``, ``rel``, ``max_revisions``, and ``rounds``
      (one :class:`FixBatch` per fixing round, in order).
    * ``review`` — ``pr``, ``manifest_rel``, ``findings`` (``True``/``False``; ``False``
      omits R2).
    * ``fix`` — ``pr``, ``round_index``, ``iteration``, ``manifest_rel``.
    * ``approve`` — ``pr``.

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
    return tuple(planned)
