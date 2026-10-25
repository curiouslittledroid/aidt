"""Tests for deterministic verdict parsing."""

from __future__ import annotations

from aidw.verdict import APPROVE, BLOCKED, REQUEST_CHANGES, is_approved, parse_verdict


def test_approve() -> None:
    assert parse_verdict("All good.\n\nApprove") == APPROVE


def test_approved_variant() -> None:
    assert parse_verdict("**Approved**") == APPROVE


def test_request_changes() -> None:
    assert parse_verdict("Two defects.\nVerdict: Request changes") == REQUEST_CHANGES


def test_blocked() -> None:
    assert parse_verdict("Cannot judge.\nBlocked") == BLOCKED


def test_last_occurrence_wins() -> None:
    text = "Initially I would Request changes, but after review: Approve"
    assert parse_verdict(text) == APPROVE


def test_verdict_declaration_beats_later_rejected_mention() -> None:
    """Regression: review 1 declared Request changes, then explained Blocked was not warranted."""
    text = (
        "Findings...\n\n"
        "**Verdict: Request changes** \u2014 both findings are proof gaps; "
        "neither requires an owner design decision, so `Blocked` is not warranted.\n"
    )
    assert parse_verdict(text) == REQUEST_CHANGES


def test_verdict_heading_then_bold_line() -> None:
    """Regression: review 2 used a `## Verdict` heading followed by a bold conclusion."""
    text = "...\n\n## Verdict\n\n**Approve** \u2014 the prompt faithfully expands the task.\n"
    assert parse_verdict(text) == APPROVE


def test_ambiguous_returns_none() -> None:
    assert parse_verdict("I looked at the prompt and have some thoughts.") is None


def test_is_approved() -> None:
    assert is_approved("Approve")
    assert not is_approved("Request changes")
