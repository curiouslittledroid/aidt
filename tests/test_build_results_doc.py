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
    path = (
        toolkit_root()
        / "docs"
        / "implementation-results"
        / "00-E9.1"
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