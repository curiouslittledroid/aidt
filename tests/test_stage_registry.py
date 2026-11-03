"""Contract and property tests for the default stage registry (EXTRACTION.md §3.5, E4.1).

The registry is *data plus one pure expander*, so these tests are its executable
specification: each workflow default is compared against the hardcoded chain the workflow
module runs today (``implement.build_plan``, the ``prompt`` run loop's stage names,
``review``'s R1/R2, ``fix``'s dry-run plan, ``approve``'s ``STAGE``/``AGENT``/``PROMPT``),
including the ``extra`` text, which is part of "byte for byte". Nothing here edits or
rewires a workflow: E4.3 owns that, and this file is what would catch it changing behaviour.

Structural tests are per-behaviour hand-calculated vectors (one per path of the prompt
loop's ``if``/``⟳`` notation). The invariant sweep at the end is this module's property
test: ``hypothesis`` is not a dependency (AGENTS.md §15, no new deps), so it enumerates the
small input space deterministically instead, and the seed is the enumeration itself.
"""

from __future__ import annotations

import ast
import builtins
import inspect
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from aidw import stage_registry as registry
from aidw.findings import MANIFEST_EXTRA, ParsedFinding
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
from aidw.workflows import prompt as prompt_workflow
from aidw.workflows import review as review_workflow

PROMPT_REL = "docs/task-prompts/03-E4.1-prompt.md"
BRANCH = "03-E4.1"
TASK_ID = "03-E4.1"
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
    )
    stages = expand(
        "implement",
        prompt_rel=PROMPT_REL,
        branch=BRANCH,
        task_id=TASK_ID,
        base_branch=base_branch,
    )

    assert len(stages) == len(plan) == 6
    for planned, expected in zip(stages, plan):
        assert planned.id == expected.id
        assert planned.name == expected.name
        assert planned.agent == expected.agent
        assert planned.prompt_file == expected.prompt_file
        assert list(planned.variables) == expected.variables
        # The `extra` is part of "byte for byte": I2's test context is exactly
        # `implement.py`'s `_TEST_CONTEXT.format(...)`, and every other stage carries none.
        assert planned.extra == expected.extra


def test_implement_defaults_base_branch_to_main() -> None:
    plan = implement_workflow.build_plan(
        aidt=Path("/aidt"), prompt_rel=PROMPT_REL, branch=BRANCH, task_id=TASK_ID
    )
    stages = expand(
        "implement", prompt_rel=PROMPT_REL, branch=BRANCH, task_id=TASK_ID
    )
    assert [list(s.variables) for s in stages] == [p.variables for p in plan]
    assert stages[3].variables == (BRANCH, "main")


def test_implement_records_the_parallel_group_as_stage_names() -> None:
    """R11/§3.4: the safe pair is data, keyed on the stage *names* `implement.py` uses."""
    definition = registry.get_workflow("implement")
    assert definition.parallel_groups == (("test", "update-architecture"),)
    names = [stage.name for stage in definition.stages]
    for group in definition.parallel_groups:
        for member in group:
            assert member in names, f"{member} is not a stage name of `implement`"


def test_retained_stage_ids_are_the_vocabulary() -> None:
    """R6: ids are retained. §3.4's `author`/`review`/`implement` example ids are not."""
    assert registry.STAGE_IDS == frozenset(
        {"I1", "I2", "I3", "I4", "I5", "I6", "P1", "P2", "R1", "R2",
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
# The data-dependent briefs must reproduce prompt.py's rendering exactly
# --------------------------------------------------------------------------- #


def test_delta_brief_matches_the_workflow_rendering(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        prompt_workflow, "_prompt_diff", lambda baseline, current, *, name: DIFF
    )
    expected = prompt_workflow._render_delta_brief(
        index=2,
        previous_review="previous review",
        baseline="before",
        current="after",
        rel=REL,
    )
    assert registry.render_delta_brief(previous_review="previous review", diff=DIFF) == expected


def test_delta_brief_unavailable_note_matches_the_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        prompt_workflow, "_prompt_diff", lambda baseline, current, *, name: None
    )
    expected = prompt_workflow._render_delta_brief(
        index=2,
        previous_review="previous review",
        baseline="before",
        current="after",
        rel=REL,
    )
    rendered = registry.render_delta_brief(previous_review="previous review", diff=None)
    assert rendered == expected
    assert registry.DIFF_UNAVAILABLE in rendered


def test_reconcile_brief_matches_the_workflow_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        prompt_workflow, "_prompt_diff", lambda baseline, current, *, name: DIFF
    )
    expected = prompt_workflow._render_reconcile(
        index=1,
        review_text="whole review",
        baseline="before",
        current="after",
        rel=REL,
    )
    assert registry.render_reconcile(review="whole review", diff=DIFF) == expected


# --------------------------------------------------------------------------- #
# review / approve / fix (design §8.3, §8.4, §8.5)
# --------------------------------------------------------------------------- #


def test_review_chain_reproduces_r1_and_r2() -> None:
    stages = expand(
        "review", pr=PR, manifest_rel="artifacts/review-manifest.json", findings=True
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
        manifest_rel="artifacts/review-manifest.json"
    )


def test_review_without_findings_omits_r2() -> None:
    stages = expand(
        "review", pr=PR, manifest_rel="artifacts/review-manifest.json", findings=False
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
        manifest_rel="artifacts/iter1-review-manifest.json",
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
         MANIFEST_EXTRA.format(manifest_rel="artifacts/iter1-review-manifest.json")),
    ]
    # F4 is conditional on F3's verdict (§8.4); the condition travels with the stage.
    assert [stage.id for stage in stages] == ["A1", "F1", "F2", "F3", "F4"]
    assert stages[-1].when == registry.WHEN_FINDINGS
    for stage in stages[:-1]:
        assert stage.when == ""


def test_fix_iteration_is_part_of_the_stage_names() -> None:
    stages = expand(
        "fix",
        pr=PR,
        round_index=2,
        iteration=3,
        manifest_rel="artifacts/iter3-review-manifest.json",
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
        registry.stage("implement", "I7")


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
    assert len(expand("implement", prompt_rel=PROMPT_REL, branch=BRANCH, task_id=TASK_ID)) == 6
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
    assert imported == {"__future__", "collections.abc", "dataclasses", "types", "typing", "aidw.findings"}
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
