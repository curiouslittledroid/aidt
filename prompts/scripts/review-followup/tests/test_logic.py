"""Unit tests for the pure selection logic in ``logic.py``.

Run with: uv run pytest prompts/scripts/review-followup/tests
"""

from __future__ import annotations

import pytest

from logic import (
    ApprovalPlan,
    ChildIssue,
    ParsedArgs,
    Selection,
    approval_plan,
    availability,
    can_override_selection,
    closing_body_repeats_status,
    has_exact_comment,
    is_approved,
    is_in_flight,
    parse_args,
    priority_label,
    select_first_available,
    status_flags,
)
from proc import UsageError


def child(**overrides: object) -> ChildIssue:
    values: dict[str, object] = {
        "number": 100,
        "title": "Fix a thing",
        "url": "https://github.com/o/r/issues/100",
        "state": "OPEN",
        "labels": ["review-follow-up", "must-fix", "approve-fix"],
        "comment_bodies": [],
    }
    values.update(overrides)
    return ChildIssue(**values)  # type: ignore[arg-type]


def selection_of(selected: ChildIssue | None) -> Selection:
    return Selection(selected=selected, skipped=[])


# ── hasExactComment ───────────────────────────────────────────────────────


def test_has_exact_comment_matches_only_the_exact_body() -> None:
    assert has_exact_comment(["Status: fixed"], "Status: fixed") is True
    assert has_exact_comment(["Status: fixed pending"], "Status: fixed") is False
    assert has_exact_comment(["status: fixed"], "Status: fixed") is False
    assert has_exact_comment(["Status: fixed "], "Status: fixed") is False
    assert has_exact_comment([], "Status: fixed") is False


def test_status_flags_never_treat_a_mention_as_a_status() -> None:
    bodies = ["Decision: approve-fix", "Preamble\nStatus: in progress was recorded"]
    flags = status_flags(bodies)
    assert (flags.in_progress, flags.fixed) == (False, False)


# ── availability ──────────────────────────────────────────────────────────


def test_availability_accepts_an_open_approved_child() -> None:
    verdict = availability(child())
    assert verdict.available is True
    assert verdict.reason is None


def test_availability_rejects_a_closed_child() -> None:
    verdict = availability(child(state="CLOSED"))
    assert (verdict.available, verdict.reason) == (False, "CLOSED")


def test_availability_rejects_a_child_without_approve_fix() -> None:
    verdict = availability(child(labels=["review-follow-up", "must-fix"]))
    assert (verdict.available, verdict.reason) == (False, "MISSING_APPROVE_FIX")


def test_availability_rejects_a_child_with_decision_pending() -> None:
    verdict = availability(
        child(labels=["review-follow-up", "must-fix", "approve-fix", "decision-pending"])
    )
    assert (verdict.available, verdict.reason) == (False, "DECISION_PENDING")


def test_availability_rejects_a_child_already_in_progress() -> None:
    verdict = availability(child(comment_bodies=["Status: in progress"]))
    assert (verdict.available, verdict.reason) == (False, "STATUS_IN_PROGRESS")


def test_availability_rejects_a_child_already_fixed() -> None:
    verdict = availability(child(comment_bodies=["Status: fixed"]))
    assert (verdict.available, verdict.reason) == (False, "STATUS_FIXED")


# ── selectFirstAvailable ──────────────────────────────────────────────────


def test_selects_the_first_available_child_in_native_order() -> None:
    selection = select_first_available([child(number=1, state="CLOSED"), child(number=2)])
    assert selection.selected is not None
    assert selection.selected.number == 2
    assert len(selection.skipped) == 1
    skipped = selection.skipped[0]
    assert (skipped.number, skipped.reason) == (1, "CLOSED")
    assert skipped.url == "https://github.com/o/r/issues/100"


def test_records_the_skip_reason_for_each_child_before_the_selection() -> None:
    selection = select_first_available(
        [
            child(number=1, labels=["review-follow-up"]),
            child(number=2, comment_bodies=["Status: fixed"]),
            child(number=3),
        ]
    )
    assert selection.selected is not None
    assert selection.selected.number == 3
    assert [skipped.reason for skipped in selection.skipped] == [
        "MISSING_APPROVE_FIX",
        "STATUS_FIXED",
    ]


def test_does_not_inspect_children_after_the_selected_one() -> None:
    selection = select_first_available([child(number=1), child(number=2, state="CLOSED")])
    assert selection.selected is not None
    assert selection.selected.number == 1
    assert selection.skipped == []


def test_returns_no_selection_when_every_child_is_unavailable() -> None:
    selection = select_first_available([child(number=1, state="CLOSED"), child(number=2, state="CLOSED")])
    assert selection.selected is None
    assert len(selection.skipped) == 2


def test_handles_an_empty_child_list() -> None:
    selection = select_first_available([])
    assert selection.selected is None
    assert selection.skipped == []


# ── isInFlight ────────────────────────────────────────────────────────────


def test_in_flight_accepts_an_open_child_with_the_exact_in_progress_comment() -> None:
    assert is_in_flight(child(comment_bodies=["Status: in progress"])) is True


def test_in_flight_rejects_an_open_child_with_no_status_comment() -> None:
    assert is_in_flight(child()) is False


def test_in_flight_rejects_a_closed_child_even_with_the_comment() -> None:
    assert is_in_flight(child(state="CLOSED", comment_bodies=["Status: in progress"])) is False


def test_in_flight_rejects_a_prose_mention_of_the_status() -> None:
    assert is_in_flight(child(comment_bodies=["Status: in progress was recorded"])) is False


# ── canOverrideSelection ──────────────────────────────────────────────────


def test_override_allows_the_child_native_order_selection_chose() -> None:
    selected = child(number=2)
    assert can_override_selection(selected, selection_of(selected)) is True


def test_override_allows_any_explicit_child_when_selection_found_none() -> None:
    explicit = child(number=2, comment_bodies=["Status: in progress"])
    assert can_override_selection(explicit, selection_of(None)) is True


def test_override_allows_the_in_flight_child_after_start_removed_it() -> None:
    in_flight = child(number=2, comment_bodies=["Status: in progress"])
    assert can_override_selection(in_flight, selection_of(child(number=3))) is True


def test_override_rejects_a_later_untouched_child_when_an_earlier_one_is_available() -> None:
    assert can_override_selection(child(number=3), selection_of(child(number=2))) is False


def test_override_rejects_a_closed_child_that_is_not_in_flight() -> None:
    closed = child(number=2, state="CLOSED", comment_bodies=["Status: fixed"])
    assert can_override_selection(closed, selection_of(child(number=3))) is False


# ── priorityLabel ─────────────────────────────────────────────────────────


def test_priority_label_returns_the_single_priority_label() -> None:
    assert priority_label(["review-follow-up", "should-fix", "approve-fix"]) == "should-fix"


def test_priority_label_returns_none_without_a_priority_label() -> None:
    assert priority_label(["review-follow-up", "approve-fix"]) is None


def test_priority_label_returns_none_when_ambiguous() -> None:
    assert priority_label(["must-fix", "should-fix"]) is None


# ── closingBodyRepeatsStatus ──────────────────────────────────────────────


def test_detects_a_leading_status_line() -> None:
    assert closing_body_repeats_status("Status: fixed\n\nImplemented.") is True


def test_detects_a_leading_status_line_after_blank_lines() -> None:
    assert closing_body_repeats_status("\n\nStatus: fixed\n\nImplemented.") is True


def test_allows_a_body_that_does_not_begin_with_the_status_line() -> None:
    assert closing_body_repeats_status("\nImplemented on the PR branch.\n\nStatus: fixed") is False


# ── parseArgs ─────────────────────────────────────────────────────────────


def test_parses_a_full_fixed_invocation() -> None:
    assert parse_args(["fixed", "--pr", "174", "--body-file", "/tmp/body.md", "--dry-run"]) == ParsedArgs(
        command="fixed", pr="174", body_file="/tmp/body.md", dry_run=True
    )


def test_parses_issue_as_a_positive_integer() -> None:
    assert parse_args(["verify", "--pr", "174", "--issue", "176"]).issue == 176


def test_rejects_a_non_numeric_issue() -> None:
    with pytest.raises(UsageError, match="positive integer"):
        parse_args(["verify", "--pr", "174", "--issue", "abc"])


def test_rejects_a_flag_missing_its_value() -> None:
    with pytest.raises(UsageError, match="requires a value"):
        parse_args(["select", "--pr"])


def test_rejects_an_unknown_command() -> None:
    with pytest.raises(UsageError, match="Unknown command"):
        parse_args(["frobnicate"])


def test_rejects_an_unknown_flag() -> None:
    with pytest.raises(UsageError, match="Unknown flag"):
        parse_args(["select", "--pr", "174", "--yes"])


def test_treats_a_bare_invocation_as_help() -> None:
    assert parse_args([]).command == "help"
    assert parse_args(["--help"]).command == "help"


def test_parses_an_approve_invocation() -> None:
    assert parse_args(["approve", "--pr", "174", "--dry-run"]) == ParsedArgs(
        command="approve", pr="174", dry_run=True
    )


# ── approvalPlan ──────────────────────────────────────────────────────────


def test_approval_plan_adds_removes_and_comments() -> None:
    plan = approval_plan(
        child(labels=["review-follow-up", "must-fix", "decision-pending"], comment_bodies=[])
    )
    assert plan == ApprovalPlan(
        add_labels=["approve-fix"], remove_labels=["decision-pending"], add_decision_comment=True
    )


def test_approval_plan_is_inert_once_fully_approved() -> None:
    plan = approval_plan(
        child(
            labels=["review-follow-up", "must-fix", "approve-fix"],
            comment_bodies=["Decision: approve-fix"],
        )
    )
    assert plan == ApprovalPlan()


def test_approval_plan_does_not_re_add_an_existing_exact_decision_comment() -> None:
    plan = approval_plan(child(labels=["approve-fix"], comment_bodies=["Decision: approve-fix"]))
    assert plan.add_decision_comment is False


def test_approval_plan_treats_a_prose_mention_as_missing() -> None:
    plan = approval_plan(
        child(labels=["approve-fix"], comment_bodies=["Decision: approve-fix pending review"])
    )
    assert plan.add_decision_comment is True


# ── isApproved ────────────────────────────────────────────────────────────


def test_is_approved_requires_open_approve_fix_no_pending_and_the_exact_comment() -> None:
    assert (
        is_approved(child(labels=["approve-fix"], comment_bodies=["Decision: approve-fix"])) is True
    )
    assert is_approved(child(labels=["approve-fix", "decision-pending"])) is False
    assert is_approved(child(labels=["approve-fix"])) is False
    assert (
        is_approved(
            child(
                state="CLOSED",
                labels=["approve-fix"],
                comment_bodies=["Decision: approve-fix"],
            )
        )
        is False
    )
