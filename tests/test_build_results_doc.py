"""Consistency checks pinning the E9.1 build-results record to the tree it records.

Implements the regression cover for review follow-up PR #128 finding F2 (issue
#131): the record is the branch's gate evidence for the task's "repo gates stay
green" done-when (``docs/task-prompts/00-E9.1-prompt.md``), and AGENTS.md requires
exact commands and real outcomes — so while the recorded suite gate is green, the
record's verification tables must not claim a red tree.
"""

from __future__ import annotations

from aidw.paths import toolkit_root


def _record() -> str:
    return _record_for("00-E9.1")


def _record_for(branch: str) -> str:
    path = (
        toolkit_root()
        / "docs"
        / "implementation-results"
        / branch
        / "build-results.md"
    )
    return path.read_text(encoding="utf-8")


def _verification_section(record: str) -> str:
    """The ``## Verification Results`` section, up to the deviations heading."""
    start = record.index("## Verification Results")
    end = record.index("## Deviations observed during recording")
    return record[start:end]


def test_record_claims_no_failing_suite_gate() -> None:
    """The top-level Test row must record the suite gate's real, green outcome.

    The trigger (issue #131): the record's Test row read "❌ Fail (``5 failed,
    1860 passed``)" for tree ``1d6b0fc0454d``, while that tree's committed
    ``design.md`` plus ``tests/test_design_doc.py`` pass — so a reviewer re-running
    the cited command concluded the branch's gate was red.
    """
    verification = _verification_section(_record())

    test_row = next(
        line for line in verification.splitlines() if line.startswith("| Test |")
    )

    assert "❌ Fail" not in test_row
    assert "✅ Pass" in test_row


def test_verification_tables_carry_no_failure_claims() -> None:
    """No verification row may claim a failure the re-run does not produce.

    The trigger (issue #131): the record also carried a "five failing tests"
    table and task-specific ❌ rows, none of which reproduces on the final tree.
    The record stage derives every row from a single full-suite invocation
    (``prompts/record-implementation-results.md``), so the whole verification
    section must agree with that one green run.
    """
    verification = _verification_section(_record())

    assert "❌" not in verification
    assert "failing tests" not in verification
    assert "5 failed" not in verification


def test_deviations_no_longer_claim_the_delivered_tree_is_red() -> None:
    """The deviations section must not claim the implementation is not green.

    The trigger (issue #131): the record's first deviation bullet asserted "the
    full test gate fails; implementation is not green as delivered", contradicting
    the green suite the same document records. Deviations that remain must be real
    observations of the delivered tree, not stale claims from the first recording.
    """
    record = _record()
    deviations = record[record.index("## Deviations observed during recording") :]

    assert "not green as delivered" not in deviations


def test_x1_1_record_matches_green_evidence_and_the_ticked_task() -> None:
    """The X1.1 audit artifact must agree with its final tree and roadmap state.

    Review follow-up #154 found the opposite state: the record retained a red suite
    *and* an unverified dry-run from an intermediate tree while the roadmap already
    said the task was complete. Checking the top-level outcome rows, the task-specific
    assertions, the gate-origin tree, and the roadmap together prevents that split-brain
    record from being accepted again while allowing the deviations section to preserve
    the historical observation honestly.
    """
    record = _record_for("04-X1.1")
    verification = _verification_section(record)

    test_row = next(
        line for line in verification.splitlines() if line.startswith("| Test |")
    )
    dry_run_row = next(
        line
        for line in verification.splitlines()
        if line.startswith("| Task dry-run |")
    )
    assert "✅ Pass" in test_row
    assert "❌ Fail" not in test_row
    assert "✅ Pass" in dry_run_row
    assert "unverified" not in dry_run_row.lower()

    task_specific = verification[
        verification.index("### Task-specific verification gates") :
    ]
    assert "❌" not in task_specific
    assert (
        "`uv run aidw implement docs/task-prompts/04-X1.1-prompt.md --dry-run` "
        "prints `I8 summarize-implementation-results` between `I5` and `I7` | ✅ Pass"
    ) in task_specific

    gate_origins = verification[
        verification.index("Gate origins for the rows above") :
    ]
    assert "`suite` — passed" in gate_origins
    assert "tree `4d5538f3abb5`" in gate_origins

    roadmap = (
        toolkit_root() / "docs" / "tasks" / "04 - Enhancements.md"
    ).read_text(encoding="utf-8")
    assert "- [x] **X1.1." in roadmap
    assert "- [ ] **X1.1." not in roadmap


# --------------------------------------------------------------------------- #
# The pull-request contract (design §17 Z5)
# --------------------------------------------------------------------------- #

#: ``I5`` writes the build results *before* the PR exists (it records the gate ``I6``
#: cites), so the number is stated by two stages in one direction: the record stage
#: fills the line honestly, and the delivery stage replaces the absence with the real
#: number. The template is the contract both read, so it is asserted, not grepped from
#: a record: a template that drops the field silently drops the number from every task.
TEMPLATE = toolkit_root() / "docs" / "implementation-results" / "TEMPLATE.md"


def _flat(text: str) -> str:
    """The text with runs of whitespace collapsed, for phrase assertions across wraps."""
    return " ".join(text.split())


def _prompt(name: str) -> str:
    return _flat((toolkit_root() / "prompts" / name).read_text(encoding="utf-8"))


def test_the_template_states_the_pull_request_just_above_the_summary() -> None:
    """Z5: a mandatory ``**Pull request:**`` field, immediately above ``## Summary``."""
    lines = TEMPLATE.read_text(encoding="utf-8").splitlines()

    index = next(
        number for number, line in enumerate(lines) if line.startswith("**Pull request:**")
    )
    assert "{{PULL_REQUEST}}" in lines[index]
    assert lines[index + 1] == ""
    assert lines[index + 2].startswith("## Summary")
    assert any(line.startswith("**Spec:**") for line in lines[:index])


def test_the_record_stage_writes_an_honest_value_and_pr_backfills_the_number() -> None:
    """Z5: ``I5`` may not invent a number, and ``I6`` is the only stage that can know one."""
    record = _prompt("record-implementation-results.md")

    assert "gh pr view" in record
    assert "not yet opened" in record
    assert "invent no number" in record

    pr = _prompt("pr.md")

    assert "not yet opened" in pr
    assert "record PR #" in pr
    assert "`gh pr create` printed" in pr
