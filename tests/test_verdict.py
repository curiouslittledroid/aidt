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


def test_declaration_with_backticked_token() -> None:
    """Reviewers mirror the prompt's own ``Verdict: `Approve` `` shape."""
    assert parse_verdict("Done.\n\nVerdict: `Approve`") == APPROVE
    assert parse_verdict("**Verdict:** `Request changes`") == REQUEST_CHANGES


def test_bare_backticked_verdict_line() -> None:
    assert parse_verdict("## Verdict\n\n`Approve`") == APPROVE


def test_path_mentions_are_not_verdicts() -> None:
    """E4.5b regression: the mention fallback read ``approve`` out of module paths.

    The 2026-11-04 task-prompt review never emitted a verdict; it listed the workflows it
    had read (``implement/review/approve/fix/prompt``) and was parsed as ``Approve``, so
    five findings — one of them ``Must fix`` — were dropped and no fix stage ran.
    """
    text = (
        "Affected: every run path, `workflows implement/review/approve/fix/prompt "
        "preflights`, and the shared plan builder (`review`'s `r1, r2 =`, `approve`'s "
        "`(spec,) =`).\n\n"
        "Suggested fix: scope the check to prompt/review/fix/approve, but not implement."
    )
    assert parse_verdict(text) is None
    assert parse_verdict("See aidw/workflows/approve.py for the gate.") is None
    assert parse_verdict("The preflight runs in prompt/review/fix/approve.") is None


def test_code_span_symbol_mention_is_not_a_verdict() -> None:
    assert parse_verdict("Rework `approve`'s tuple unpack.") is None
    assert parse_verdict("The `approved` flag is set by the script.") is None


def test_fenced_block_mention_is_not_a_verdict() -> None:
    """A quotation of the prompt's own wording is not the reviewer's conclusion."""
    text = "```text\nVerdict: Approve\n```\nStill checking the remaining sections."
    assert parse_verdict(text) is None


def test_is_approved() -> None:
    assert is_approved("Approve")
    assert not is_approved("Request changes")
