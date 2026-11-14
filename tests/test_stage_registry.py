"""Contract and property tests for the default stage registry (EXTRACTION.md §3.5, E4.1).

The registry is *data plus one pure expander*, so these tests are its executable
specification: each workflow default is compared against the chain the workflow module runs
(``implement.build_plan``, the ``prompt`` run loop's stage names, ``review``'s R1/R2,
``fix``'s dry-run plan, ``approve``'s ``STAGE``/``AGENT``/``PROMPT``), including the
``extra`` text, which is part of "byte for byte". E4.3 then wired every run path to the
registry, so ``build_plan`` is now the expansion itself; the byte-level pins on what the
workflows actually render are the real-run tests in ``tests/test_prompt_workflow.py`` and
the stage-list pins in ``tests/test_plan_stages.py``. The delta/reconcile brief assertions
here are structural: the wording has a single home in this module, so there is no second
renderer left to compare against (E4.3 deleted ``prompt.py``'s copies).

Structural tests are per-behaviour hand-calculated vectors (one per path of the prompt
loop's ``if``/``⟳`` notation). The invariant sweep at the end is this module's property
test: ``hypothesis`` is not a dependency (AGENTS.md §15, no new deps), so it enumerates the
small input space deterministically instead, and the seed is the enumeration itself.
"""

from __future__ import annotations

import ast
import builtins
import inspect
import itertools
import random
from collections.abc import Collection, Sequence
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from aidw import stage_registry as registry
from aidw.config import ERROR
# H2.1: the delta brief re-emits the reviewer's own block (``_finding_text_block``), never
# ``render_finding_block`` whose "Fix exactly this finding" instruction is the fixer's voice.
from aidw.findings import (
    MANIFEST_EXTRA,
    ParsedFinding,
    _finding_text_block,
    parse_review_findings,
)
from aidw.stage_registry import (
    BRIEF_DELTA,
    BRIEF_RECONCILE,
    DEFAULTS,
    RevisionBudgetError,
    StageFieldError,
    UnknownStageError,
    UnknownWorkflowError,
    expand,
)
from aidw.workflows import approve as approve_workflow
from aidw.workflows import implement as implement_workflow
from aidw.workflows import review as review_workflow

PROMPT_REL = "docs/task-prompts/03-E4.1-prompt.md"
BRANCH = "03-E4.1"
TASK_ID = "03-E4.1"
#: I7's two expansion fields (H3.1): the entry's own roadmap file and its task id without
#: the phase prefix — ``{task_id}`` stays I6's branch form ``03-E4.1``.
ROADMAP_FILE = "/repo/docs/tasks/03 - Extraction.md"
CHECKBOX_ID = "E4.1"
REL = "docs/task-prompts/03-E4.1-prompt.md"
PR = 17


def _finding(priority: str, n: int) -> ParsedFinding:
    return ParsedFinding(
        priority=priority,
        confidence=4,
        what_found=f"what {n}",
        why_it_matters=f"why {n}",
        trigger_and_effect=f"trigger {n}",
        where=f"file{n}.py",
        suggested_fix=f"fix {n}",
    )


BLOCKING = _finding("must-fix", 1)
COULD_FIX = _finding("could-fix", 2)


def _batch(
    review_text: str = "review",
    *,
    blocking: tuple[ParsedFinding, ...] = (BLOCKING,),
    could_fix: tuple[ParsedFinding, ...] = (COULD_FIX,),
    unparseable: bool = False,
) -> registry.FixBatch:
    return registry.FixBatch(
        review_text=review_text,
        blocking=blocking,
        could_fix=could_fix,
        unparseable=unparseable,
    )


def _prompt_stages(*rounds: registry.FixBatch, max_revisions: int = 3):
    return expand(
        "prompt",
        phase="00",
        epic="E4",
        task="E4.1",
        rel=REL,
        max_revisions=max_revisions,
        rounds=list(rounds),
    )


# --------------------------------------------------------------------------- #
# implement — byte for byte against build_plan (design §8.2, E4.1's "Done when")
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("base_branch", ["main", "develop"])
def test_implement_default_reproduces_build_plan(base_branch: str) -> None:
    plan = implement_workflow.build_plan(
        aidt=Path("/aidt"),
        prompt_rel=PROMPT_REL,
        branch=BRANCH,
        task_id=TASK_ID,
        base_branch=base_branch,
        roadmap_file=ROADMAP_FILE,
        checkbox_id=CHECKBOX_ID,
    )
    stages = expand(
        "implement",
        prompt_rel=PROMPT_REL,
        branch=BRANCH,
        task_id=TASK_ID,
        base_branch=base_branch,
        roadmap_file=ROADMAP_FILE,
        checkbox_id=CHECKBOX_ID,
    )

    assert len(stages) == len(plan) == 8
    for planned, expected in zip(stages, plan):
        assert planned.id == expected.id
        assert planned.name == expected.name
        assert planned.agent == expected.agent
        assert planned.prompt_file == expected.prompt_file
        # Both sides are `PlannedStage`s since E4.3 (``build_plan`` is the wrapper), so
        # this compares the registry's frozen tuples directly (E4.3 req 4).
        assert planned.variables == expected.variables
        # The `extra` is part of "byte for byte": I2's test context, and none elsewhere.
        assert planned.extra == expected.extra


def test_implement_defaults_base_branch_to_main() -> None:
    plan = implement_workflow.build_plan(
        aidt=Path("/aidt"),
        prompt_rel=PROMPT_REL,
        branch=BRANCH,
        task_id=TASK_ID,
        roadmap_file=ROADMAP_FILE,
        checkbox_id=CHECKBOX_ID,
    )
    stages = expand(
        "implement",
        prompt_rel=PROMPT_REL,
        branch=BRANCH,
        task_id=TASK_ID,
        roadmap_file=ROADMAP_FILE,
        checkbox_id=CHECKBOX_ID,
    )
    assert [s.variables for s in stages] == [p.variables for p in plan]
    assert stages[3].variables == (BRANCH, "main")


def test_implement_records_the_parallel_group_as_stage_names() -> None:
    """R11/§3.4: the safe pair is data, keyed on the stage *names* `implement.py` uses."""
    definition = registry.get_workflow("implement")
    assert definition.parallel_groups == (("test", "update-architecture"),)
    names = [stage.name for stage in definition.stages]
    for group in definition.parallel_groups:
        for member in group:
            assert member in names, f"{member} is not a stage name of `implement`"


def test_i7_carries_the_evidence_green_condition() -> None:
    """H3.2 req 1: the tick's condition is declared on the *definition*, not the workflow."""
    i7 = registry.stage("implement", "I7")
    assert i7.name == "update-roadmap"
    assert i7.when == registry.WHEN_EVIDENCE_GREEN
    # No other stage carries it: the condition is I7's, and H3.3 is what shares the token.
    for workflow in ("implement", "prompt", "review", "approve", "fix"):
        definition = registry.get_workflow(workflow)
        carried = [
            stage.name
            for stage in definition.stages
            if stage.when == registry.WHEN_EVIDENCE_GREEN
        ]
        expected = ["update-roadmap"] if workflow == "implement" else []
        assert carried == expected


def test_the_evidence_green_condition_is_carried_never_expanded_away() -> None:
    """H3.2 req 1: ``expand`` still emits I7, with ``when`` carried onto the stage.

    ``_expand_static`` omits only on ``when=findings`` with ``findings is False``; a
    condition the expander cannot resolve (the run's gate outcomes do not exist yet) must
    survive expansion, so ``plan_stages``, ``build_plan`` and ``--dry-run`` plan I7 in its
    run position and the workflow decides at run time.
    """
    stages = expand(
        "implement",
        prompt_rel=PROMPT_REL,
        branch=BRANCH,
        task_id=TASK_ID,
        base_branch="main",
        roadmap_file=ROADMAP_FILE,
        checkbox_id=CHECKBOX_ID,
    )

    assert [stage.id for stage in stages] == [
        "I1", "I2", "I3", "I4", "I5", "I8", "I7", "I6",
    ]
    carried = {stage.id: stage.when for stage in stages}
    assert carried["I7"] == registry.WHEN_EVIDENCE_GREEN
    assert {key: value for key, value in carried.items() if key != "I7"} == {
        "I1": "", "I2": "", "I3": "", "I4": "", "I5": "", "I8": "", "I6": "",
    }
    # A lowered ``findings`` field cannot drop it either — that switch is R2/F4's alone.
    with_findings_flag = expand(
        "implement",
        prompt_rel=PROMPT_REL,
        branch=BRANCH,
        task_id=TASK_ID,
        base_branch="main",
        roadmap_file=ROADMAP_FILE,
        checkbox_id=CHECKBOX_ID,
        findings=False,
    )
    assert [stage.name for stage in with_findings_flag] == [
        stage.name for stage in stages
    ]


def test_the_when_vocabulary_is_exported_and_distinct() -> None:
    """H3.2 req 1: the token joins the ``when=`` vocabulary beside the other four."""
    tokens = (
        registry.WHEN_FINDINGS,
        registry.WHEN_BLOCKING,
        registry.WHEN_COULD_FIX,
        registry.WHEN_UNPARSEABLE,
        registry.WHEN_EVIDENCE_GREEN,
    )

    assert tokens == (
        "findings", "blocking", "could-fix", "unparseable", "evidence-green"
    )
    assert len(set(tokens)) == len(tokens)
    # Exported as module-level constants, beside the others (importable by name).
    for name in (
        "WHEN_FINDINGS",
        "WHEN_BLOCKING",
        "WHEN_COULD_FIX",
        "WHEN_UNPARSEABLE",
        "WHEN_EVIDENCE_GREEN",
    ):
        assert isinstance(getattr(registry, name), str)


def test_retained_stage_ids_are_the_vocabulary() -> None:
    """R6: ids are retained. §3.4's `author`/`review`/`implement` example ids are not."""
    assert registry.STAGE_IDS == frozenset(
        {"I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "P1", "P2", "R1", "R2",
         "F1", "F2", "F3", "F4", "A1"}
    )
    for workflow in ("implement", "review", "approve"):
        for stage in registry.get_workflow(workflow).stages:
            assert stage.id in registry.STAGE_IDS
    for stage in registry.get_workflow("prompt").stages:
        assert stage.id in registry.STAGE_IDS
    loop_ids = {stage.id for stage in registry.get_workflow("prompt").loop.head}
    assert loop_ids == {"P2"}
    fix_loop = registry.get_workflow("fix").loop
    assert {stage.id for stage in (*fix_loop.head, *fix_loop.body)} == {
        "F1", "F2", "F3", "F4"
    }
    # Id and name are different fields: I1's id is retained, its name is the runtime name.
    assert registry.stage("implement", "I1").name == "impliment-task"
    assert registry.stages_by_id("implement")["I6"].name == "pr"


# --------------------------------------------------------------------------- #
# prompt — the post-phase-02 loop (design §8.1, H6/G2/L4.1, L2.3, L3.4)
# --------------------------------------------------------------------------- #


def test_prompt_loop_reproduces_todays_run_loop_order() -> None:
    stages = _prompt_stages(_batch("round 1"), _batch("round 2"))

    assert [stage.name for stage in stages] == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1-1",
        "task-review-fixes-1-2",
        "task-review-reconcile-1",
        "task-review-2",
        "task-review-fixes-2-1",
        "task-review-fixes-2-2",
        "task-review-reconcile-2",
        "task-review-3",
    ]
    # Terminal review: nothing runs after it (H6/G2/L4.1).
    assert stages[-1].name == "task-review-3"
    assert sum(1 for stage in stages if stage.name.startswith("task-review-")
               and not stage.name.startswith(("task-review-fixes", "task-review-reconcile"))) == 3
    assert not any("task-review-fixes-3" in stage.name for stage in stages)
    assert not any("task-review-reconcile-3" in stage.name for stage in stages)


def test_prompt_loop_agents_prompts_and_variables_per_stage() -> None:
    """A reconcile stage on the wrong agent must fail this, not just a name assertion."""
    stages = _prompt_stages(_batch("round 1"), _batch("round 2"))
    author, *rest = stages
    assert (author.id, author.name, author.agent, author.prompt_file) == (
        "P1", "task-prompt", "task-author", "task-prompt.md"
    )
    assert author.variables == ("00", "E4", "E4.1")

    for stage in rest:
        assert stage.variables == (REL,)
        if stage.name.startswith("task-review-reconcile"):
            assert stage.id == registry.PROMPT_RECONCILE
            assert stage.agent == "task-fixer"
            assert stage.prompt_file == "task-review-fixes.md"
            assert stage.brief == BRIEF_RECONCILE
        elif stage.name.startswith("task-review-fixes"):
            assert stage.agent == "task-fixer"
            assert stage.prompt_file == "task-review-fixes.md"
            assert stage.brief == ""
        else:
            assert stage.id == "P2"
            assert stage.agent == "task-reviewer"
            assert stage.prompt_file == "task-review.md"


def test_prompt_fix_batch_carries_the_rendered_finding_blocks() -> None:
    """The `extra` for each fix stage is the reviewer's own block, as `prompt.py` renders it."""
    from aidw.findings import render_could_fix_block, render_finding_block

    stages = _prompt_stages(_batch("round 1"), _batch("round 2"))
    fixes = [stage for stage in stages if stage.name.startswith("task-review-fixes")]
    assert [stage.extra for stage in fixes] == [
        render_finding_block(BLOCKING, index=1, total=2),
        render_could_fix_block([COULD_FIX]),
        render_finding_block(BLOCKING, index=1, total=2),
        render_could_fix_block([COULD_FIX]),
    ]
    # The reconcile stage's extra is runtime-assembled (whole review + real diff), so the
    # expansion carries the brief kind rather than a placeholder body.
    for stage in stages:
        if stage.name.startswith("task-review-reconcile"):
            assert stage.extra == ""


def test_prompt_round_one_is_unprimed_and_later_rounds_carry_the_delta_brief() -> None:
    stages = _prompt_stages(_batch("round 1"), _batch("round 2"))
    reviews = [stage for stage in stages if stage.name.startswith("task-review-")
               and not stage.name.startswith(("task-review-fixes", "task-review-reconcile"))]
    assert [stage.brief for stage in reviews] == ["", BRIEF_DELTA, BRIEF_DELTA]


def test_prompt_approving_first_round_plans_author_and_one_review() -> None:
    stages = _prompt_stages()
    assert [stage.name for stage in stages] == ["task-prompt", "task-review-1"]
    assert stages[1].brief == ""


def test_prompt_unparseable_review_expands_to_one_fallback_stage() -> None:
    stages = _prompt_stages(
        _batch("the whole review text", blocking=(), could_fix=(), unparseable=True)
    )
    assert [stage.name for stage in stages] == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1",
        "task-review-reconcile-1",
        "task-review-2",
    ]
    assert not any("task-review-fixes-1-" in stage.name for stage in stages)
    fallback = stages[2]
    assert fallback.id == registry.PROMPT_FIX_FALLBACK
    assert fallback.agent == "task-fixer"
    assert fallback.prompt_file == "task-review-fixes.md"
    assert fallback.variables == (REL,)
    assert fallback.extra == registry.render_whole_review_extra("the whole review text")
    assert fallback.extra == "## Review findings to address\n\nthe whole review text"


def test_prompt_parsed_batch_with_only_blocking_findings_has_no_combined_stage() -> None:
    stages = _prompt_stages(_batch(could_fix=()))
    fixes = [stage.name for stage in stages if stage.name.startswith("task-review-fixes")]
    assert fixes == ["task-review-fixes-1-1"]
    # `total` counts the stages of the batch, so a single finding is "1 of 1".
    assert stages[2].extra.startswith("## Review finding 1 of 1 to address")


def test_prompt_loop_fails_closed_beyond_the_revision_budget() -> None:
    with pytest.raises(RevisionBudgetError):
        _prompt_stages(_batch(), _batch(), _batch(), max_revisions=3)
    with pytest.raises(StageFieldError):
        _prompt_stages(max_revisions=0)


# --------------------------------------------------------------------------- #
# The data-dependent briefs (the only renderers left after E4.3)
# --------------------------------------------------------------------------- #


def test_delta_brief_is_instruction_previous_review_and_diff_in_order() -> None:
    """L2.3: instruction, then the previous review verbatim, then the real diff."""
    previous = "previous review with trailing spaces  \n"
    rendered = registry.render_delta_brief(previous_review=previous, diff=DIFF)

    assert rendered.startswith(registry.DELTA_BRIEF_INSTRUCTION)
    for token in ("`resolved`", "`not resolved`", "`newly contradicted`"):
        assert token in rendered
    assert "### Previous review\n\n" + previous in rendered
    assert "### Prompt diff since that review\n\n" + DIFF in rendered
    assert rendered.index("### Previous review") < rendered.index(
        "### Prompt diff"
    )
    # Purity: the caller's strings are untouched.
    assert previous == "previous review with trailing spaces  \n"


def test_delta_brief_degrades_to_the_unavailable_note() -> None:
    """An unavailable diff is named, never rendered as a silently empty section."""
    rendered = registry.render_delta_brief(previous_review="previous review", diff=None)

    assert registry.DIFF_UNAVAILABLE in rendered
    assert "The prompt diff for this round is unavailable" in rendered
    assert "diff --git" not in rendered


# --------------------------------------------------------------------------- #
# The delta brief's size contract (H2.1, roadmap H2.1)
# --------------------------------------------------------------------------- #
#
# The previous-review half has **no hard cap**: the smaller of two representations wins,
# measured with ``len(s)`` on the exact strings compared (strictly smaller, so equality
# keeps the prose). The diff half has a hard cap (``DELTA_BRIEF_DIFF_BUDGET_CHARS``) and an
# over-budget diff becomes an explicit elision note. The sizes the roadmap counts are
# **chars**, never bytes or lines, so every expectation below is a ``len`` of a string.

#: The E4.5 failure run's round-1 prompt size and its inflated round-2 size (roadmap H2.1).
ROUND_ONE_PROMPT_CHARS = 12_317
FAILURE_RUN_ROUND_TWO_CHARS = 55_636

#: The prompt-fixed round-2 acceptance bound (H2.1: the spec fixes no total number; 24,000
#: clears the budgeted ceiling and sits under half the failure run's 55,636).
ROUND_TWO_ACCEPTANCE_CHARS = 24_000

#: Pinned property-test parameters: ``hypothesis`` is not a dependency (AGENTS.md, design
#: §15), so the property run is a seeded sample and ``numRuns`` is an explicit constant.
DELTA_BRIEF_PROPERTY_SEED = 41_210
DELTA_BRIEF_PROPERTY_NUM_RUNS = 120


#: A review shaped like a real one: headings, fenced finding blocks, a verdict section.
MULTI_FINDING_REVIEW = """\
## What I verified

The prompt's assumptions hold.

## Findings

```text
Priority: Should fix
Confidence: 4
What I found: The deliverable leaves a stale path reference.
Why it matters: A reviewer lands on a missing file.
Trigger and effect: After the rename the pointer is dead.
Where: docs/task-prompts/00-E4.1-prompt.md, Deliverables.
Suggested fix: Add the path update to the deliverables.
```

```text
Priority: Should fix
Confidence: 3
What I found: The prompt is silent on matrix coverage.
Why it matters: A convention-mandated check is skipped silently.
Trigger and effect: The implementer omits the matrix review.
Where: docs/task-prompts/00-E4.1-prompt.md, requirement 7.
Suggested fix: Add one line recording the out-of-scope decision.
```

```text
Priority: Could fix
Confidence: 2
What I found: The annotations contradict the import strategy.
Why it matters: Minor compile churn or diff noise.
Trigger and effect: The implementer picks either strategy.
Where: docs/task-prompts/00-E4.1-prompt.md, Deliverables vs requirement 4.
Suggested fix: Pick one consumer-import strategy and align them.
```

## Verdict

Request changes — two should-fix items remain.
"""


#: A review that is *only* a fenced finding block: the structured rendering adds the lead
#: line, so blocks are not strictly smaller and the prose must win.
BARE_BLOCK_REVIEW = _finding_text_block(
    ParsedFinding(
        priority="should-fix",
        confidence=4,
        what_found="A stale path.",
        why_it_matters="The reviewer lands nowhere.",
        trigger_and_effect="After the rename.",
        where="docs/x.md",
        suggested_fix="Update the path.",
    )
)


def _expected_blocks(review: str) -> str:
    """The structured rendering the contract describes, built from the parsed findings."""
    findings, problems = parse_review_findings(review)
    assert problems == []
    assert findings
    return registry.DELTA_BRIEF_FINDINGS_LEAD + "\n\n" + "\n\n".join(
        _finding_text_block(finding) for finding in findings
    )


def test_delta_brief_renders_structured_findings_when_strictly_smaller() -> None:
    """H2.1 req 2: a parseable review whose blocks are smaller renders the blocks.

    Every finding survives, the reviewer's voice is kept (no fixer instruction anywhere),
    and the per-finding resolution instruction is still there to be answered.
    """
    expected = _expected_blocks(MULTI_FINDING_REVIEW)
    # The premise of this fixture: the structured rendering is the smaller representation.
    assert len(expected) < len(MULTI_FINDING_REVIEW)

    rendered = registry.render_delta_brief(
        previous_review=MULTI_FINDING_REVIEW, diff="diff --git a/x b/x\n"
    )

    assert expected in rendered
    assert MULTI_FINDING_REVIEW not in rendered
    # No finding is dropped by the substitution, and no fixer voice leaks in.
    assert "Fix exactly this finding" not in rendered
    assert "Review finding " not in rendered
    for excerpt in (
        "The deliverable leaves a stale path reference.",
        "The prompt is silent on matrix coverage.",
        "The annotations contradict the import strategy.",
    ):
        assert excerpt in rendered
    for token in ("`resolved`", "`not resolved`", "`newly contradicted`"):
        assert token in rendered
    # The section heading is still the delta brief's, not the fixer's.
    assert "### Previous review\n\n" + registry.DELTA_BRIEF_FINDINGS_LEAD in rendered


def test_delta_brief_keeps_prose_verbatim_when_blocks_are_not_smaller() -> None:
    """H2.1 req 2: a bare block review renders prose; the blocks would add characters."""
    expected = _expected_blocks(BARE_BLOCK_REVIEW)
    assert len(expected) >= len(BARE_BLOCK_REVIEW)

    rendered = registry.render_delta_brief(previous_review=BARE_BLOCK_REVIEW, diff=None)

    assert "### Previous review\n\n" + BARE_BLOCK_REVIEW in rendered
    assert registry.DELTA_BRIEF_FINDINGS_LEAD not in rendered


def test_delta_brief_keeps_prose_on_a_len_equal_tie() -> None:
    """H2.1 req 2: the win is **strict**, so an exact ``len`` tie keeps the prose.

    The fixture is the bare-block review (whose blocks are the *larger* representation),
    padded with unparseable prose until the two lengths are exactly equal — the padding
    cannot change the structured rendering, because it parses into no finding.
    """
    expected = _expected_blocks(BARE_BLOCK_REVIEW)
    padding = len(expected) - len(BARE_BLOCK_REVIEW)
    assert padding > 0
    padded = BARE_BLOCK_REVIEW + "\n" + "x" * (padding - 1)
    assert len(padded) == len(expected)
    assert _expected_blocks(padded) == expected

    rendered = registry.render_delta_brief(previous_review=padded, diff=None)

    assert "### Previous review\n\n" + padded in rendered
    assert registry.DELTA_BRIEF_FINDINGS_LEAD not in rendered


def test_delta_brief_keeps_an_unparseable_review_verbatim_with_whitespace() -> None:
    """H2.1 req 2: a review that does not parse into findings is never re-emitted.

    Trailing whitespace is meaningful evidence of "this is the bytes we were given", so
    the fallback is byte-for-byte, not stripped.
    """
    unparseable = "Priority: Urgent\nConfidence: 9\nWhat I found: broken  \n\n\n"
    assert parse_review_findings(unparseable)[1]

    rendered = registry.render_delta_brief(previous_review=unparseable, diff=None)

    assert unparseable in rendered
    assert registry.DELTA_BRIEF_FINDINGS_LEAD not in rendered


def test_an_over_budget_diff_is_replaced_by_the_elision_note() -> None:
    """H2.1 req 3: an over-budget diff is elided behind a named note, never truncated."""
    over = "diff --git a/x b/x\n" + "+" * 8000
    assert len(over) > registry.DELTA_BRIEF_DIFF_BUDGET_CHARS

    rendered = registry.render_delta_brief(
        previous_review=MULTI_FINDING_REVIEW, diff=over
    )

    # The pinned tokens: the word, the reason, and the numeric budget value.
    assert "elided" in rendered
    assert "for size" in rendered
    assert str(registry.DELTA_BRIEF_DIFF_BUDGET_CHARS) in rendered
    assert str(len(over)) in rendered
    # Not the could-not-produce note, and no silently shortened diff.
    assert registry.DIFF_UNAVAILABLE not in rendered
    assert "diff --git" not in rendered
    assert registry.DELTA_BRIEF_DIFF_ELIDED.format(size=len(over)) in rendered


def test_an_in_budget_diff_renders_unchanged() -> None:
    """H2.1 req 3: the cap is a ceiling, not a tightening — an in-budget diff is intact."""
    at_cap = "diff --git a/x b/x\n" + "+" * (
        registry.DELTA_BRIEF_DIFF_BUDGET_CHARS - len("diff --git a/x b/x\n")
    )
    assert len(at_cap) == registry.DELTA_BRIEF_DIFF_BUDGET_CHARS

    rendered = registry.render_delta_brief(previous_review="r", diff=at_cap)

    assert "### Prompt diff since that review\n\n" + at_cap in rendered
    assert "elided" not in rendered


def test_diff_budget_counts_characters_not_utf8_bytes() -> None:
    """H2.1 req 3: the roadmap's cap is ``len(s)`` characters, not encoded bytes."""
    at_cap = "é" * registry.DELTA_BRIEF_DIFF_BUDGET_CHARS
    over_cap = at_cap + "é"

    assert len(at_cap.encode("utf-8")) > registry.DELTA_BRIEF_DIFF_BUDGET_CHARS
    assert registry.render_diff_section(at_cap) == at_cap
    assert "elided" in registry.render_diff_section(over_cap)


def test_the_delta_brief_helpers_are_pure_and_do_no_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H2.1 req 1/2/3: pure helpers — no I/O, no mutation of the caller's strings."""
    monkeypatch.setattr(builtins, "open", _explode)
    monkeypatch.setattr(Path, "read_text", _explode)
    monkeypatch.setattr(Path, "write_text", _explode)

    review = MULTI_FINDING_REVIEW
    over = "diff --git a/x b/x\n" + "+" * 8000
    before_review, before_diff = review, over

    assert registry.render_previous_review(review) == _expected_blocks(review)
    assert registry.render_diff_section(over) == registry.DELTA_BRIEF_DIFF_ELIDED.format(
        size=len(over)
    )
    assert registry.render_diff_section(None) == registry.DIFF_UNAVAILABLE
    assert registry.render_diff_section("diff --git a/x b/x\n") == "diff --git a/x b/x\n"
    assert registry.render_delta_brief(previous_review=review, diff=over)

    assert review == before_review
    assert over == before_diff


def test_is_review_stage_names_only_the_prompt_loops_review_heads() -> None:
    """H2.1 req 5: the rendered-size record is scoped to ``task-review-<n>`` heads."""
    for name in ("task-review-1", "task-review-2", "task-review-12"):
        assert registry.is_review_stage(name)
    for name in (
        "task-prompt",
        "task-review-fixes-1-1",
        "task-review-fixes-2",
        "task-review-reconcile-1",
        "task-review-",
        "task-review-1x",
        "task-review-1-1",
        "code-review",
        "impliment-task",
        "",
    ):
        assert not registry.is_review_stage(name), name


def _e45_shape_review(count: int = 6) -> str:
    """The E4.5 shape: ``count`` findings inside a realistically verbose review.

    The narrative around the blocks is what makes the structured rendering the *smaller*
    representation — the roadmap's premise that findings are cheaper than the prose the
    reviewer wrapped them in (~2k of blocks against a much longer review).
    """
    blocks = []
    for index in range(1, count + 1):
        blocks.append(
            "```text\n"
            "Priority: Should fix\n"
            "Confidence: 4\n"
            f"What I found: Requirement {index} names a file the prompt never lists.\n"
            "Why it matters: The stage stops or invents a path.\n"
            f"Trigger and effect: A round reads requirement {index} alone.\n"
            f"Where: docs/task-prompts/00-E4.5-prompt.md, req {index}.\n"
            "Suggested fix: Name the file in the deliverables.\n"
            "```"
        )
    return (
        "## What I verified\n\n"
        "I read the roadmap entry, the cited spec sections and the whole prompt, then re-read\n"
        "every requirement against the phase's non-goals and the repository's gates. The\n"
        "prompt's assumptions about the toolkit hold and every deliverable is reachable.\n\n"
        f"I then walked the {count} findings below one at a time, in review order.\n\n"
        "## Findings\n\n"
        + "\n\n".join(blocks)
        + "\n\n## Verdict\n\nRequest changes — six should-fix items remain.\n"
    )


def test_six_findings_plus_a_capped_diff_stay_under_the_round_two_bound() -> None:
    """H2.1's hand-calculated size check on the E4.5 shape (six findings).

    Round 1's 12,317-char prompt plus the budgeted brief must land under the prompt-fixed
    24,000-char bound — the failure run's 55,636 is the "before" — and the six structured
    blocks are ~2k, not the 40k+ the raw review prose carried.
    """
    review = _e45_shape_review()
    assert len(parse_review_findings(review)[0]) == 6
    blocks = _expected_blocks(review)
    assert 1_500 < len(blocks) < 2_500, len(blocks)
    # The structured rendering is the smaller representation for this shape, so the
    # budgeted brief carries the blocks, not the verbose prose.
    assert len(blocks) < len(review)

    diff = "diff --git a/p b/p\n" + "+" * (
        registry.DELTA_BRIEF_DIFF_BUDGET_CHARS - len("diff --git a/p b/p\n")
    )
    brief = registry.render_delta_brief(previous_review=review, diff=diff)
    assert blocks in brief
    assert review not in brief
    round_two = "x" * ROUND_ONE_PROMPT_CHARS + brief

    assert len(round_two) < ROUND_TWO_ACCEPTANCE_CHARS
    assert len(round_two) < FAILURE_RUN_ROUND_TWO_CHARS
    # And the elision is why a fix-batch-sized diff cannot blow the bound: the same
    # fixture with the diff left uncapped is measurably larger.
    uncapped = registry.DELTA_BRIEF_INSTRUCTION + "\n\n" + blocks + "\n\n" + (
        "+" * 40_000
    )
    elided = registry.render_delta_brief(
        previous_review=review, diff="+" * 40_000
    )
    assert len(elided) < len(uncapped)
    assert len(elided) < len(brief) + registry.DELTA_BRIEF_DIFF_BUDGET_CHARS


def test_delta_brief_size_property_holds_for_generated_reviews() -> None:
    """Property (seeded, ``numRuns`` pinned above): the contract holds on every sample.

    For each generated ``(review, diff)`` the rendering obeys exactly one of the two
    previous-review promises — the structured blocks when they parse cleanly and are
    strictly smaller, the prose verbatim otherwise — never drops a finding, always carries
    the resolution instruction, and never emits an over-budget diff section. The sample is
    the seed: same seed + same count => same cases on every machine.
    """
    rng = random.Random(DELTA_BRIEF_PROPERTY_SEED)
    structured_used = verbatim_used = 0
    for index in range(DELTA_BRIEF_PROPERTY_NUM_RUNS):
        count = rng.randint(1, 8)
        review = _e45_shape_review(count)
        if rng.random() < 0.5:
            # Strip the narrative, which flips the win to the *prose*: a review that is
            # little more than its blocks is not re-emitted as (larger) blocks.
            review = review[review.index("## Findings") :]
        if rng.random() < 0.25:
            review = review + "\n" + "noise " * rng.randint(0, 200)
        if rng.random() < 0.25:
            # A malformed finding makes the parse fail closed, so the prose must survive.
            review = review.replace("Confidence: 4", "Confidence: 9", 1)
        diff = (
            None
            if rng.random() < 0.15
            else "d" * rng.choice([0, 1, registry.DELTA_BRIEF_DIFF_BUDGET_CHARS,
                                   registry.DELTA_BRIEF_DIFF_BUDGET_CHARS + 1, 9_000])
        )

        findings, problems = parse_review_findings(review)
        blocks = (
            registry.DELTA_BRIEF_FINDINGS_LEAD
            + "\n\n"
            + "\n\n".join(_finding_text_block(f) for f in findings)
            if findings and not problems
            else None
        )
        rendered = registry.render_delta_brief(previous_review=review, diff=diff)

        if blocks is not None and len(blocks) < len(review):
            assert blocks in rendered, index
            structured_used += 1
        else:
            assert "### Previous review\n\n" + review in rendered, index
            verbatim_used += 1
        for token in ("`resolved`", "`not resolved`", "`newly contradicted`"):
            assert token in rendered, index
        if diff is None:
            assert registry.DIFF_UNAVAILABLE in rendered, index
            assert "was elided for size" not in rendered, index
        elif len(diff) > registry.DELTA_BRIEF_DIFF_BUDGET_CHARS:
            assert registry.DELTA_BRIEF_DIFF_ELIDED.format(size=len(diff)) in rendered
            assert diff not in rendered
        else:
            assert "### Prompt diff since that review\n\n" + diff in rendered, index
        assert rendered == registry.render_delta_brief(
            previous_review=review, diff=diff
        ), index

    # The sweep is only meaningful if both promises are actually exercised.
    assert structured_used and verbatim_used, (structured_used, verbatim_used)


def test_reconcile_brief_is_instruction_review_and_combined_diff() -> None:
    """L3.4: the reconcile wording, never the reviewer's delta brief (the trap)."""
    review = "whole review with trailing spaces  \n"
    rendered = registry.render_reconcile(review=review, diff=DIFF)

    assert rendered.startswith(registry.RECONCILE_INSTRUCTION)
    assert "## Reconcile the fix batch" in rendered
    assert "## Delta brief" not in rendered
    assert "### Full review\n\n" + review in rendered
    assert "### Combined diff for this fix batch\n\n" + DIFF in rendered
    assert rendered.index("### Full review") < rendered.index("### Combined diff")

    degraded = registry.render_reconcile(review=review, diff=None)
    assert registry.DIFF_UNAVAILABLE in degraded
    assert "diff --git" not in degraded
    # Purity: the caller's string is untouched.
    assert review == "whole review with trailing spaces  \n"


# --------------------------------------------------------------------------- #
# review / approve / fix (design §8.3, §8.4, §8.5)
# --------------------------------------------------------------------------- #


def test_review_chain_reproduces_r1_and_r2() -> None:
    stages = expand(
        "review", pr=PR, manifest_path="artifacts/review-manifest.json", findings=True
    )
    assert [(stage.id, stage.name, stage.agent, stage.prompt_file) for stage in stages] == [
        ("R1", review_workflow.R1, "code-reviewer", "code-review.md"),
        (
            "R2",
            review_workflow.R2,
            "review-publisher",
            "review-findings-to-github.md",
        ),
    ]
    assert stages[0].variables == () and stages[0].extra == ""
    assert stages[1].variables == (str(PR),)
    assert stages[1].when == registry.WHEN_FINDINGS
    assert stages[1].extra == MANIFEST_EXTRA.format(
        manifest_path="artifacts/review-manifest.json"
    )


def test_review_without_findings_omits_r2() -> None:
    stages = expand(
        "review", pr=PR, manifest_path="artifacts/review-manifest.json", findings=False
    )
    assert [stage.name for stage in stages] == [review_workflow.R1]


def test_approve_chain_reproduces_the_single_stage() -> None:
    stages = expand("approve", pr=PR)
    assert [(stage.id, stage.name, stage.agent, stage.prompt_file, stage.variables)
            for stage in stages] == [
        (
            "A1",
            approve_workflow.STAGE,
            approve_workflow.AGENT,
            approve_workflow.PROMPT,
            (str(PR),),
        )
    ]
    assert stages[0].extra == ""


def test_fix_expansion_reproduces_the_dry_run_plan() -> None:
    stages = expand(
        "fix",
        pr=PR,
        round_index=1,
        iteration=1,
        manifest_path="artifacts/iter1-review-manifest.json",
    )
    assert [
        (stage.name, stage.agent, stage.prompt_file, list(stage.variables), stage.extra)
        for stage in stages
    ] == [
        ("round1-approve-review-followups", "review-approver",
         "approve-review-followups.md", [str(PR)], ""),
        ("iter1-fix-next-review-followup", "fixer",
         "fix-next-review-followup.md", [str(PR)], ""),
        ("iter1-test", "tester", "test.md", [],
         registry.FIX_TEST_CONTEXT_EXTRA.format(pr=PR, iteration=1)),
        ("iter1-code-review", "code-reviewer", "code-review.md", [], ""),
        ("iter1-review-findings-to-github", "review-publisher",
         "review-findings-to-github.md", [str(PR)],
         MANIFEST_EXTRA.format(manifest_path="artifacts/iter1-review-manifest.json")),
    ]
    # F4 is conditional on F3's verdict (§8.4); the condition travels with the stage.
    assert [stage.id for stage in stages] == ["A1", "F1", "F2", "F3", "F4"]
    assert stages[-1].when == registry.WHEN_FINDINGS
    for stage in stages[:-1]:
        assert stage.when == ""


# --------------------------------------------------------------------------- #
# The post-loop half: one shared tick, once per run (H3.3 req 1/req 2)
# --------------------------------------------------------------------------- #


def test_the_post_loop_field_exists_and_defaults_empty() -> None:
    """``WorkflowDefinition.post_loop`` is additive: only ``fix`` carries one today."""
    definition = registry.get_workflow("fix")
    assert definition.post_loop == (registry.stage("fix", "I7"),)
    for workflow in ("implement", "prompt", "review", "approve"):
        assert registry.get_workflow(workflow).post_loop == (), workflow


def test_the_shared_tick_is_one_definition_object() -> None:
    """The ``A1`` precedent: one id, one prompt, one agent, one name — same object.

    ``implement``'s static I7 and ``fix``'s post-loop I7 must be the *same*
    ``StageDefinition``, or the two ticks could drift (H3.3's whole point).
    """
    implemented = registry.stage("implement", "I7")
    fixed = registry.stage("fix", "I7")
    assert implemented is fixed
    assert fixed.id == "I7"
    assert fixed.name == "update-roadmap"
    assert fixed.agent == "recorder"
    assert fixed.prompt_file == "update-roadmap.md"
    assert fixed.variables == ("{roadmap_file}", "{checkbox_id}")
    assert fixed.when == registry.WHEN_EVIDENCE_GREEN
    assert fixed is registry.stages_by_id("fix")["I7"]
    assert fixed is registry.stages_by_id("implement")["I7"]


def test_expand_emits_the_post_loop_stage_only_on_request() -> None:
    """Req 1: ``expand("fix", …)`` is the per-iteration expansion — never the tick.

    The tick is emitted once, last, and only under ``include_post_loop`` (which is why the
    flag exists: an unconditional emission would plan and dry-run print it per iteration).
    """
    iteration = expand("fix", pr=PR, round_index=1, iteration=1, manifest_path="m.json")
    post = expand(
        "fix",
        pr=PR,
        round_index=1,
        iteration=1,
        manifest_path="m.json",
        include_post_loop=True,
        roadmap_file=ROADMAP_FILE,
        checkbox_id=CHECKBOX_ID,
    )

    assert [stage.id for stage in iteration] == ["A1", "F1", "F2", "F3", "F4"]
    assert [stage.id for stage in post] == ["A1", "F1", "F2", "F3", "F4", "I7"]
    assert post[: len(iteration)] == iteration
    tick = post[-1]
    assert (tick.name, tick.agent) == ("update-roadmap", "recorder")
    assert tick.variables == (ROADMAP_FILE, CHECKBOX_ID)
    # Carried, never expanded away (H3.2's rule for the shared condition).
    assert tick.when == registry.WHEN_EVIDENCE_GREEN


def test_the_post_loop_expansion_needs_its_two_fields() -> None:
    """Fail closed: asking for the tick without its fields is a ``StageFieldError``."""
    with pytest.raises(StageFieldError) as missing:
        expand(
            "fix",
            pr=PR,
            round_index=1,
            iteration=1,
            manifest_path="m.json",
            include_post_loop=True,
        )
    assert "roadmap_file" in str(missing.value)


def test_expand_never_emits_a_post_loop_stage_for_a_workflow_without_one() -> None:
    """``include_post_loop`` on ``implement`` is a no-op: I7 is already in its static half."""
    fields = dict(
        prompt_rel=PROMPT_REL,
        branch=BRANCH,
        task_id=TASK_ID,
        roadmap_file=ROADMAP_FILE,
        checkbox_id=CHECKBOX_ID,
    )
    assert expand("implement", **fields) == expand(
        "implement", include_post_loop=True, **fields
    )


def test_validate_stage_list_treats_the_fix_post_loop_i7_as_core() -> None:
    """Req 2: removal, disable and reorder each report an ``ERROR`` for ``I7``."""
    removal = registry.validate_stage_list("fix", [{"id": "A1"}])
    assert any(
        "I7" in issue.message and "core stage cannot be removed" in issue.message
        for issue in removal
    )

    disabled = registry.validate_stage_list(
        "fix", [{"id": "A1"}, {"id": "I7", "enabled": False}]
    )
    assert any(
        "I7" in issue.message and "core stage cannot be disabled" in issue.message
        for issue in disabled
    )

    reordered = registry.validate_stage_list("fix", [{"id": "I7"}, {"id": "A1"}])
    assert any(
        "core stage cannot be reordered" in issue.message
        and "declared [I7, A1]" in issue.message
        and "registry order is [A1, I7]" in issue.message
        for issue in reordered
    )

    # And the canonical declaration is clean — I7 is not misclassified as a loop stage.
    assert registry.validate_stage_list("fix", [{"id": "A1"}, {"id": "I7"}]) == []


def test_the_post_loop_expansion_does_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Purity: asking for the tick reads and writes nothing, and mutates no default."""

    def _explode(*args: object, **kwargs: object):
        raise AssertionError("the registry must not touch the filesystem")

    before = repr(DEFAULTS)
    monkeypatch.setattr(builtins, "open", _explode)
    monkeypatch.setattr(Path, "read_text", _explode)
    monkeypatch.setattr(Path, "write_text", _explode)
    monkeypatch.setattr(Path, "is_file", _explode)
    monkeypatch.setattr(Path, "exists", _explode)

    fields = dict(pr=PR, round_index=1, iteration=1, manifest_path="m.json")
    first = expand(
        "fix",
        include_post_loop=True,
        roadmap_file=ROADMAP_FILE,
        checkbox_id=CHECKBOX_ID,
        **fields,
    )
    second = expand(
        "fix",
        include_post_loop=True,
        roadmap_file=ROADMAP_FILE,
        checkbox_id=CHECKBOX_ID,
        **fields,
    )

    assert first == second
    assert first is not second
    assert repr(DEFAULTS) == before
    assert fields == dict(pr=PR, round_index=1, iteration=1, manifest_path="m.json")


def test_fix_iteration_is_part_of_the_stage_names() -> None:
    stages = expand(
        "fix",
        pr=PR,
        round_index=2,
        iteration=3,
        manifest_path="artifacts/iter3-review-manifest.json",
    )
    assert [stage.name for stage in stages] == [
        "round2-approve-review-followups",
        "iter3-fix-next-review-followup",
        "iter3-test",
        "iter3-code-review",
        "iter3-review-findings-to-github",
    ]
    assert stages[2].extra == registry.FIX_TEST_CONTEXT_EXTRA.format(pr=PR, iteration=3)


# --------------------------------------------------------------------------- #
# Fail-closed lookups and expansions
# --------------------------------------------------------------------------- #


def test_unknown_workflow_and_stage_fail_closed() -> None:
    with pytest.raises(UnknownWorkflowError):
        expand("nope", pr=PR)
    with pytest.raises(UnknownStageError):
        # I9 is the next free implement id after X1.1's I8; I1..I8 are all real stages.
        registry.stage("implement", "I9")


def test_missing_or_wrong_expansion_fields_fail_closed() -> None:
    with pytest.raises(StageFieldError) as missing:
        expand("implement", prompt_rel=PROMPT_REL, branch=BRANCH)  # no task_id
    assert "task_id" in str(missing.value)
    with pytest.raises(StageFieldError):
        expand("prompt", phase="00", epic="E4", task="E4.1")  # no max_revisions
    with pytest.raises(StageFieldError):
        expand("prompt", phase="00", epic="E4", task="E4.1", rel=REL,
               max_revisions=3, rounds=("not a batch",))
    with pytest.raises(StageFieldError):
        expand("fix", pr=PR, round_index=1)  # no iteration


# --------------------------------------------------------------------------- #
# Purity: no I/O, no mutation, immutable defaults, independently-owned results
# --------------------------------------------------------------------------- #


def _explode(*args: object, **kwargs: object):
    raise AssertionError("the registry must not perform I/O")


def test_expansion_does_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builtins, "open", _explode)
    monkeypatch.setattr(Path, "read_text", _explode)
    monkeypatch.setattr(Path, "write_text", _explode)
    stages = _prompt_stages(_batch(), _batch())
    assert [stage.name for stage in stages][:2] == ["task-prompt", "task-review-1"]
    assert (
        len(
            expand(
                "implement",
                prompt_rel=PROMPT_REL,
                branch=BRANCH,
                task_id=TASK_ID,
                roadmap_file=ROADMAP_FILE,
                checkbox_id=CHECKBOX_ID,
            )
        )
        == 8
    )
    assert registry.render_delta_brief(previous_review="r", diff=None)
    assert registry.render_reconcile(review="r", diff=None)
    assert registry.render_whole_review_extra("r")


def test_the_registry_module_imports_no_io_or_workflow_module() -> None:
    """The E4.1 dependency direction: no upward import, so E4.3 can invert `build_plan`."""
    tree = ast.parse(inspect.getsource(registry))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    # E4.4 added ``aidw.config`` (``Issue``/``ERROR`` for ``validate_parallel_groups``);
    # it is a leaf too — it imports no workflow and no target-config module.
    assert imported == {
        "__future__",
        "collections.abc",
        "dataclasses",
        "types",
        "typing",
        "aidw.config",
        "aidw.findings",
    }
    for module in imported:
        assert not module.startswith(("aidw.workflows", "aidw.git", "aidw.github")), module
        assert module not in {"subprocess", "pathlib", "shutil", "os", "aidw.target_config"}


def test_expansion_does_not_mutate_the_defaults_or_the_input_fields() -> None:
    rounds = [_batch(), _batch()]
    fields = {
        "phase": "00",
        "epic": "E4",
        "task": "E4.1",
        "rel": REL,
        "max_revisions": 3,
        "rounds": rounds,
    }
    before = repr(DEFAULTS)
    before_fields = dict(fields)

    expand("prompt", **fields)

    assert repr(DEFAULTS) == before
    assert fields == before_fields
    assert len(rounds) == 2
    with pytest.raises(FrozenInstanceError):
        registry.stage("implement", "I1").name = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        DEFAULTS["nope"] = registry.get_workflow("implement")  # type: ignore[index]
    for definition in DEFAULTS.values():
        assert isinstance(definition.stages, tuple)
        assert isinstance(definition.parallel_groups, tuple)


def test_a_second_expansion_is_equal_but_independently_owned() -> None:
    first = _prompt_stages(_batch(), _batch())
    second = _prompt_stages(_batch(), _batch())
    assert first == second
    assert first is not second
    for left, right in zip(first, second):
        assert left is not right
        assert left.variables == right.variables
        assert left.variables is not right.variables
        assert left.variables is not registry.stage("prompt", "P1").variables


# --------------------------------------------------------------------------- #
# parallel_groups validation (E4.4, EXTRACTION.md §3.5, R11)
# --------------------------------------------------------------------------- #

def test_validate_parallel_groups_accepts_the_default_and_no_groups() -> None:
    """The registry's default pair and the empty *list* of groups are both valid."""
    assert (
        registry.validate_parallel_groups(
            "implement", registry.get_workflow("implement").parallel_groups
        )
        == []
    )
    assert registry.validate_parallel_groups("implement", []) == []
    # Multi-member groups and a group naming the post-gate ``pr`` stage are valid too:
    # member existence is the only per-member rule (§3.5).
    assert registry.validate_parallel_groups(
        "implement", [("test",), ("record-implementation-results", "pr")]
    ) == []


def test_validate_parallel_groups_rejects_an_unknown_member() -> None:
    issues = registry.validate_parallel_groups("implement", [["test", "nonesuch"]])
    assert len(issues) == 1
    assert issues[0].level == ERROR
    # One message naming the workflow (its §3.4 path), the group index and the member.
    assert issues[0].source == "workflows.implement.parallel_groups"
    assert "group [0]" in issues[0].message
    assert "nonesuch" in issues[0].message
    assert "implement" in str(issues[0])


def test_validate_parallel_groups_rejects_the_illustrative_semantic_ids() -> None:
    """R6/R11: §3.4's ``[test, architecture]`` example is an id, not the stage name."""
    issues = registry.validate_parallel_groups("implement", [["test", "architecture"]])
    assert len(issues) == 1
    assert issues[0].level == ERROR
    assert "architecture" in issues[0].message
    assert "update-architecture" in issues[0].message


def test_validate_parallel_groups_rejects_an_empty_inner_group() -> None:
    issues = registry.validate_parallel_groups("implement", [[]])
    assert len(issues) == 1
    assert issues[0].level == ERROR
    assert "group [0]" in issues[0].message
    assert "workflows.implement.parallel_groups" == issues[0].source
    # The index is the empty group's own, not the first group's.
    issues = registry.validate_parallel_groups("implement", [["test"], []])
    assert len(issues) == 1
    assert "group [1]" in issues[0].message


def test_validate_parallel_groups_rejects_a_member_ordered_against_itself() -> None:
    issues = registry.validate_parallel_groups("implement", [["test", "test"]])
    assert len(issues) == 1
    assert issues[0].level == ERROR
    assert "`test`" in issues[0].message
    assert "more than once" in issues[0].message


def test_validate_parallel_groups_rejects_a_member_in_two_groups() -> None:
    issues = registry.validate_parallel_groups(
        "implement",
        [["test", "update-architecture"], ["test", "record-implementation-results"]],
    )
    assert len(issues) == 1
    assert issues[0].level == ERROR
    assert "`test`" in issues[0].message
    assert "already appears in group [0]" in issues[0].message


def test_validate_parallel_groups_requires_a_known_workflow() -> None:
    with pytest.raises(UnknownWorkflowError):
        registry.validate_parallel_groups("nonesuch", [])


def test_validate_parallel_groups_is_pure(monkeypatch: pytest.MonkeyPatch) -> None:
    """No I/O and no mutation of the input, even when every case is a failure."""
    monkeypatch.setattr(builtins, "open", _explode)
    monkeypatch.setattr(Path, "read_text", _explode)
    monkeypatch.setattr(Path, "write_text", _explode)
    groups = (("test", "update-architecture"), ("nonesuch",), ())
    before = tuple(tuple(group) for group in groups)

    issues = registry.validate_parallel_groups("implement", groups)

    assert groups == before
    assert len(issues) == 2  # the unknown member + the empty group
    assert all(issue.level == ERROR for issue in issues)


#: The sweep's member alphabet: two real stage names (one of them in the default pair)
#: and one unknown name.
_SWEEP_MEMBERS = ("test", "update-architecture", "aggregate-nonesuch")


def _all_group_lists() -> list[list[list[str]]]:
    """Every ``[[...], [...]]`` shape the sweep enumerates (pinned, not sampled).

    Each group is either empty or one to three members drawn from
    :data:`_SWEEP_MEMBERS`, and there are zero to two groups: ``(1 + 3 + 9 + 27) ** 2``
    = 1600 cases. That is the property test's whole seed and run count — hypothesis is
    not a dependency (AGENTS.md §15), so the enumeration is the generator.
    """
    per_group: list[list[str]] = [[]]
    for size in (1, 2, 3):
        for members in itertools.product(_SWEEP_MEMBERS, repeat=size):
            per_group.append(list(members))
    return [[list(left), list(right)] for left in per_group for right in per_group]


def test_validate_parallel_groups_accepts_exactly_the_schedulable_lists() -> None:
    """Property: no issues ⇔ groups non-empty, members known, no member repeated.

    A repeated member is exactly "ordered against another member" (or itself): the two
    rejections §3.5 needs and the scheduler can honour. Everything else is accepted.
    """
    known = {stage.name for stage in registry.get_workflow("implement").stages}
    cases = _all_group_lists()
    assert len(cases) == 1600  # 2 groups × (1 empty + 3 + 9 + 27 members)

    for groups in cases:
        flattened = [member for group in groups for member in group]
        schedulable = (
            all(group for group in groups)
            and all(member in known for member in flattened)
            and len(flattened) == len(set(flattened))
        )
        issues = registry.validate_parallel_groups("implement", groups)
        assert (issues == []) is schedulable, groups
        assert all(issue.level == ERROR for issue in issues), groups


# --------------------------------------------------------------------------- #
# Property / invariant sweep (deterministic: hypothesis is not a dependency)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("max_revisions", [1, 2, 3, 4])
@pytest.mark.parametrize("fix_rounds", [0, 1, 2, 3])
def test_loop_invariants_hold_for_every_budget_and_batch_count(
    max_revisions: int, fix_rounds: int
) -> None:
    """Metamorphic invariants of the loop shape, over the whole small input space.

    ``max_revisions`` covers the terminal-only case (1) and the CLI default (3);
    ``fix_rounds`` covers approve-immediately (0) through a full budget. A batch count
    above the budget is the fail-closed case, not an invariant case.
    """
    rounds = [_batch(f"round {n}") for n in range(1, fix_rounds + 1)]
    if fix_rounds > max_revisions - 1:
        with pytest.raises(RevisionBudgetError):
            _prompt_stages(*rounds, max_revisions=max_revisions)
        return

    stages = _prompt_stages(*rounds, max_revisions=max_revisions)
    names = [stage.name for stage in stages]
    reviews = [name for name in names if name.startswith("task-review-")
               and not name.startswith(("task-review-fixes", "task-review-reconcile"))]
    reconciles = [name for name in names if name.startswith("task-review-reconcile-")]

    # The loop always opens with the author and closes with a review; a review is always
    # the last stage, and the number of rounds is bounded by max_revisions.
    assert names[0] == "task-prompt"
    assert names[-1] == f"task-review-{fix_rounds + 1}"
    assert len(reviews) == fix_rounds + 1 <= max_revisions
    assert [review for review in reviews] == [
        f"task-review-{n}" for n in range(1, len(reviews) + 1)
    ]

    # Exactly one reconcile stage per fixing round, and it always follows that round's
    # last fix stage and precedes the next review: reconcile-per-batch, not per finding.
    assert reconciles == [f"task-review-reconcile-{n}" for n in range(1, fix_rounds + 1)]
    for n in range(1, fix_rounds + 1):
        last_fix = max(
            index
            for index, name in enumerate(names)
            if name.startswith(f"task-review-fixes-{n}-")
        )
        assert last_fix < names.index(f"task-review-reconcile-{n}")
        assert names.index(f"task-review-reconcile-{n}") < names.index(
            f"task-review-{n + 1}"
        )

    # Every expanded stage is renderable and complete: no template placeholder survives.
    for stage in stages:
        assert "{" not in stage.name and "}" not in stage.name
        assert all("{" not in variable for variable in stage.variables)
        assert "{" not in stage.extra
        assert stage.agent and stage.prompt_file.endswith(".md")


DIFF = "--- a/baseline/prompt.md\n+++ b/current/prompt.md\n@@ -1 +1 @@\n-a\n+b"


# --------------------------------------------------------------------------- #
# core vs repo-optional validation (E4.5a, D12/D13, EXTRACTION.md §3.5)
# --------------------------------------------------------------------------- #

#: The registry's static ``implement`` order, hand-copied from §3.5's inventory table so a
#: registry reorder cannot silently redefine what "in order" means for these tests. I8
#: (``summarize-implementation-results``, X1.1) sits between I5 and I7, and I7
#: (``update-roadmap``, H3.1) between I8 and I6; both are core.
IMPLEMENT_IDS = ("I1", "I2", "I3", "I4", "I5", "I8", "I7", "I6")
#: The same list minus the two repo-optional stages (D13) — the core subsequence the
#: validator compares against.
IMPLEMENT_CORE = ("I1", "I2", "I5", "I8", "I7", "I6")


def _declared(
    ids: Sequence[str], *, disabled: Collection[str] = ()
) -> list[dict[str, object]]:
    """The ``_workflow_value`` "stages" shape: plain dicts with only ``id``/``enabled``."""
    return [
        {"id": stage_id, "enabled": False} if stage_id in disabled else {"id": stage_id}
        for stage_id in ids
    ]


def test_repo_optional_ids_are_traceability_and_architecture() -> None:
    """D13: only ``update-traceability`` (I3) and ``update-architecture`` (I4) are optional."""
    assert registry.REPO_OPTIONAL_IDS == frozenset({"I3", "I4"})
    assert registry.REPO_OPTIONAL_IDS < {
        definition.id for definition in registry.get_workflow("implement").stages
    }


def test_validate_stage_list_accepts_every_workflow_s_own_static_list() -> None:
    """The registry's list, written out as a declared list, is valid for all five.

    Since H3.3 a declared list covers the post-loop half too, so ``fix``'s own list is
    ``[A1, I7]`` — its static stage followed by the shared tick (req 2).
    """
    for workflow in ("implement", "prompt", "review", "fix", "approve"):
        definition = registry.get_workflow(workflow)
        declared = [
            {"id": entry.id} for entry in (*definition.stages, *definition.post_loop)
        ]
        assert registry.validate_stage_list(workflow, declared) == [], workflow


def test_validate_stage_list_accepts_a_disabled_removed_or_moved_repo_optional_stage() -> None:
    """D12 locks only *core* stages: a repo-optional one may be disabled, dropped, moved."""
    both = _declared(IMPLEMENT_IDS, disabled={"I3", "I4"})
    assert registry.validate_stage_list("implement", both) == []
    # Removing a repo-optional stage is not a removal of a core stage.
    assert registry.validate_stage_list(
        "implement", _declared(("I1", "I2", "I5", "I8", "I7", "I6"))
    ) == []
    # I3/I4 are free to interleave anywhere in the list.
    assert registry.validate_stage_list(
        "implement", _declared(("I4", "I1", "I2", "I3", "I5", "I8", "I7", "I6"))
    ) == []


def test_validate_stage_list_accepts_a_repo_added_stage_at_any_position() -> None:
    """D12/§3.5: repos may add stages, including between core stages."""
    for index in range(len(IMPLEMENT_IDS) + 1):
        declared = _declared(IMPLEMENT_IDS)
        declared.insert(index, {"id": "repo-checks", "agent": "implementer"})
        assert registry.validate_stage_list("implement", declared) == [], index
        # ``enabled`` is accepted on a repo-added stage too; its planning is E4.5b's.
        declared[index]["enabled"] = False
        assert registry.validate_stage_list("implement", declared) == [], index


def test_validate_stage_list_rejects_disabling_a_core_stage() -> None:
    issues = registry.validate_stage_list(
        "implement", _declared(IMPLEMENT_IDS, disabled={"I5"})
    )
    assert len(issues) == 1
    assert issues[0].level == ERROR
    assert issues[0].source == "workflows.implement.stages"
    assert "I5" in issues[0].message
    assert "core stage cannot be disabled" in issues[0].message
    assert "implement" in str(issues[0])


def test_validate_stage_list_names_i7_when_the_core_tick_is_omitted() -> None:
    """H3.1: a replacement list cannot silently remove the roadmap tick."""
    issues = registry.validate_stage_list(
        "implement", _declared(("I1", "I2", "I3", "I4", "I5", "I8", "I6"))
    )

    removal = [issue for issue in issues if "core stage cannot be removed" in issue.message]
    assert [issue.message.split("`")[1] for issue in removal] == ["I7"]
    assert any("I7" in issue.message for issue in removal)


def test_validate_stage_list_names_i8_when_the_summary_stage_is_omitted() -> None:
    """X1.1: a replacement list cannot silently remove the narrative summary.

    The summary is **core** (`I3`/`I4` remain the only repo-optional ids), so a declared
    list without `I8` reports the removal `ERROR` and the list-level reorder — exactly the
    rule `I7` already carries, never a silent drop of the artifact the stage exists for.
    """
    issues = registry.validate_stage_list(
        "implement", _declared(("I1", "I2", "I3", "I4", "I5", "I7", "I6"))
    )

    removal = [issue for issue in issues if "core stage cannot be removed" in issue.message]
    assert [issue.message.split("`")[1] for issue in removal] == ["I8"]
    reorder = [issue for issue in issues if "core stage cannot be reordered" in issue.message]
    assert len(reorder) == 1
    assert len(issues) == 2


def test_validate_stage_list_refuses_disabling_i8() -> None:
    """X1.1: the generic summary artifact cannot be disabled by a target repo."""
    issues = registry.validate_stage_list(
        "implement",
        _declared(
            ("I1", "I2", "I3", "I4", "I5", "I8", "I7", "I6"),
            disabled={"I8"},
        ),
    )

    assert any(
        issue.level == ERROR
        and "stage `I8`: core stage cannot be disabled" in issue.message
        for issue in issues
    )


def test_validate_stage_list_refuses_i8_moved_past_the_tick() -> None:
    """X1.1: the registry's `I5 → I8 → I7` subsequence is load-bearing, like `I7`'s."""
    issues = registry.validate_stage_list(
        "implement",
        _declared(("I1", "I2", "I3", "I4", "I5", "I7", "I8", "I6")),
    )

    assert len(issues) == 1
    assert issues[0].level == ERROR
    assert "core stage cannot be reordered" in issues[0].message
    assert "I5, I7, I8" in issues[0].message
    assert "I5, I8, I7, I6" in issues[0].message


def test_validate_stage_list_rejects_a_declared_loop_stage() -> None:
    """Loop stages are generated by ``expand``; ``enabled: false`` reads as core-disabled."""
    definition = registry.stages_by_id("prompt")
    # ``STAGE_IDS`` holds ``P2`` but not the loop-internal labels — which is exactly why
    # the validator classifies by ``stages_by_id`` minus the static stages, not by
    # ``STAGE_IDS`` membership.
    assert "P2" in registry.STAGE_IDS
    assert registry.PROMPT_FIX_BLOCKING not in registry.STAGE_IDS
    assert registry.PROMPT_FIX_BLOCKING in definition

    for stage_id in (
        "P2",
        registry.PROMPT_FIX_BLOCKING,
        registry.PROMPT_FIX_COULD_FIX,
        registry.PROMPT_FIX_FALLBACK,
        registry.PROMPT_RECONCILE,
    ):
        issues = registry.validate_stage_list(
            "prompt", [{"id": "P1"}, {"id": stage_id}]
        )
        assert len(issues) == 1, stage_id
        assert issues[0].level == ERROR
        assert stage_id in issues[0].message
        assert "loop stages are generated by `expand`, not declarable" in issues[0].message

    # ``enabled: false`` on a loop stage is the disable rule, never an optional disable.
    issues = registry.validate_stage_list(
        "prompt", [{"id": "P1"}, {"id": "P2", "enabled": False}]
    )
    assert len(issues) == 1
    assert "P2" in issues[0].message
    assert "core stage cannot be disabled" in issues[0].message

    # The ``fix`` loop's F1–F4 are loop stages too (A1 and the post-loop I7 are that
    # workflow's core stages — H3.3 req 2 keeps I7 out of the loop classification).
    issues = registry.validate_stage_list(
        "fix", [{"id": "A1"}, {"id": "I7"}, {"id": "F1"}]
    )
    assert len(issues) == 1
    assert "F1" in issues[0].message
    assert "loop stages are generated by `expand`, not declarable" in issues[0].message


def test_validate_stage_list_rejects_a_reordered_core_list_once_for_the_list() -> None:
    """One ``ERROR`` per reordered list (the spec fixes the rule, the prompt the count)."""
    issues = registry.validate_stage_list(
        "implement", _declared(("I2", "I1", "I3", "I4", "I5", "I8", "I7", "I6"))
    )
    assert len(issues) == 1
    assert issues[0].level == ERROR
    assert issues[0].source == "workflows.implement.stages"
    assert "implement" in issues[0].message
    # Both orders are named, so the message is actionable without re-reading the registry.
    assert "I2, I1" in issues[0].message
    assert "I1, I2, I5, I8, I7, I6" in issues[0].message
    assert "core stage cannot be reordered" in issues[0].message


def test_validate_stage_list_does_not_blend_removal_into_reorder() -> None:
    """``[I2, I1]`` is removal for I5/I8/I7/I6 *and* one reorder for I1/I2 — never one message."""
    issues = registry.validate_stage_list("implement", _declared(("I2", "I1")))
    removal = [issue for issue in issues if "cannot be removed" in issue.message]
    reorder = [issue for issue in issues if "cannot be reordered" in issue.message]
    assert {issue.message.split("`")[1] for issue in removal} == {"I5", "I8", "I7", "I6"}
    assert len(reorder) == 1
    assert len(issues) == len(removal) + len(reorder) == 5


def test_validate_stage_list_reports_one_removal_per_core_stage_for_an_empty_list() -> None:
    """§3.4: a declared list replaces the toolkit's list wholesale, so ``[]`` removes all."""
    issues = registry.validate_stage_list("implement", [])
    removal = [issue for issue in issues if "core stage cannot be removed" in issue.message]
    assert len(removal) == len(IMPLEMENT_CORE)
    assert [issue.message.split("`")[1] for issue in removal] == list(IMPLEMENT_CORE)
    # The one list-level reorder refusal is separate: removal is never folded into it.
    reorder = [issue for issue in issues if "core stage cannot be reordered" in issue.message]
    assert len(reorder) == 1
    assert len(issues) == len(IMPLEMENT_CORE) + 1


def test_validate_stage_list_reports_one_duplicate_per_core_id() -> None:
    """A duplicated core id is one ``ERROR`` per id, not one per extra occurrence."""
    declared = _declared(
        ("I1", "I1", "I2", "I3", "I4", "I5", "I5", "I5", "I8", "I7", "I6")
    )
    issues = registry.validate_stage_list("implement", declared)
    duplicates = [
        issue for issue in issues if "core stage declared more than once" in issue.message
    ]
    assert len(duplicates) == 2
    assert {issue.message.split("`")[1] for issue in duplicates} == {"I1", "I5"}
    assert len(issues) == 2  # the core order itself is untouched, so no reorder error


def test_validate_stage_list_requires_a_known_workflow() -> None:
    with pytest.raises(UnknownWorkflowError):
        registry.validate_stage_list("nonesuch", [])


def test_validate_stage_list_skips_entries_the_loader_already_refused() -> None:
    """A non-mapping or id-less entry is the loader's ``ERROR``; it is not reported twice."""
    declared = [
        None,
        "I1",
        {},
        {"id": ""},
        {"id": 3},
        *[{"id": stage_id} for stage_id in IMPLEMENT_IDS],
    ]
    assert registry.validate_stage_list("implement", declared) == []


def test_validate_stage_list_is_pure(monkeypatch: pytest.MonkeyPatch) -> None:
    """No I/O and no mutation of the input, even when every case is a failure."""
    monkeypatch.setattr(builtins, "open", _explode)
    monkeypatch.setattr(Path, "read_text", _explode)
    monkeypatch.setattr(Path, "write_text", _explode)
    stages = [
        {"id": "I2"},
        {"id": "I1", "enabled": False},
        {"id": "I3", "enabled": False},
        {"id": "repo-added", "enabled": False},
        "not-a-mapping",
    ]
    before = repr(stages)

    issues = registry.validate_stage_list("implement", stages)

    assert repr(stages) == before
    assert all(issue.level == ERROR for issue in issues)
    # I5/I8/I7/I6 removed, I1/I2 reordered, I1 disabled: six failures. The disabled
    # repo-optional I3, the repo-added entry and the non-mapping are accepted/skipped.
    assert len(issues) == 6


def test_validate_stage_list_accepts_exactly_core_stages_in_registry_order() -> None:
    """Property sweep: no issues ⇔ the core subsequence equals the registry core order.

    The pinned generator is ``itertools.permutations(IMPLEMENT_IDS)`` — all 40320 orderings
    of the eight implement ids, ``seed = "I1..I8"`` — and ``numRuns = 40320``: the whole
    input space for the reorder/removal rules with every id present exactly once and
    nothing disabled. Hypothesis is not a dependency (AGENTS.md §15), so the enumeration
    *is* the seed and the run count (the same convention as the ``parallel_groups`` sweep
    above).

    Hand-checked expected count: the six core ids keep their registry order and the two
    repo-optional ids fill two of the remaining slots, so exactly
    ``1 × C(8, 6) × 2! = 56`` of the 40320 permutations are accepted.
    """
    cases = list(itertools.permutations(IMPLEMENT_IDS))
    assert len(cases) == 40320
    accepted = 0
    for order in cases:
        issues = registry.validate_stage_list("implement", _declared(order))
        core_subsequence = [stage_id for stage_id in order if stage_id in IMPLEMENT_CORE]
        assert (issues == []) is (core_subsequence == list(IMPLEMENT_CORE)), order
        assert all(issue.level == ERROR for issue in issues), order
        assert all(issue.source == "workflows.implement.stages" for issue in issues), order
        # A rejected all-present list carries exactly the one list-level reorder error.
        assert len(issues) == (0 if issues == [] else 1), order
        accepted += 1 if issues == [] else 0
    assert accepted == 56

    # Metamorphic half: a repo-added stage anywhere never changes any verdict.
    for order in cases:
        if [stage_id for stage_id in order if stage_id in IMPLEMENT_CORE] != list(
            IMPLEMENT_CORE
        ):
            continue
        for index in range(len(order) + 1):
            declared = _declared(order)
            declared.insert(index, {"id": "repo-added", "enabled": False})
            assert registry.validate_stage_list("implement", declared) == [], (order, index)
