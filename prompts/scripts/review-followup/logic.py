"""Pure selection, parsing, and manifest logic.

This module performs no I/O so the workflow rules can be unit tested directly.
All GitHub access lives in :mod:`gh`; all process execution lives in
:mod:`proc`. Both CLI entry points share these rules.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from constants import (
    DECISION_APPROVE_FIX,
    LABEL_APPROVE_FIX,
    LABEL_DECISION_PENDING,
    LABEL_REVIEW_FOLLOW_UP,
    PRIORITY_LABELS,
    STATUS_FIXED,
    STATUS_IN_PROGRESS,
)
from proc import UsageError

# ── Issue shape ───────────────────────────────────────────────────────────


@dataclass
class ChildIssue:
    """A child issue as needed to decide availability."""

    number: int
    title: str
    url: str
    #: Upper-case state, e.g. ``OPEN`` or ``CLOSED``.
    state: str
    labels: list[str]
    #: Raw comment bodies, compared with strict equality.
    comment_bodies: list[str]


SKIP_REASONS = (
    "CLOSED",
    "MISSING_APPROVE_FIX",
    "DECISION_PENDING",
    "STATUS_IN_PROGRESS",
    "STATUS_FIXED",
)


@dataclass
class SkippedChild:
    number: int
    title: str
    url: str
    reason: str


@dataclass
class Selection:
    selected: ChildIssue | None
    #: Skipped children that appear *before* the selected child, in native order.
    skipped: list[SkippedChild] = field(default_factory=list)


# ── Status comments ───────────────────────────────────────────────────────


def has_exact_comment(bodies: list[str], exact: str) -> bool:
    """Exact-match comment lookup.

    Availability intentionally uses equality rather than substring matching, so
    a prose comment that merely mentions the status text cannot mark an issue.
    """
    return any(body == exact for body in bodies)


@dataclass
class StatusFlags:
    in_progress: bool
    fixed: bool


def status_flags(bodies: list[str]) -> StatusFlags:
    return StatusFlags(
        in_progress=has_exact_comment(bodies, STATUS_IN_PROGRESS),
        fixed=has_exact_comment(bodies, STATUS_FIXED),
    )


# ── Availability and selection ────────────────────────────────────────────


@dataclass
class Availability:
    available: bool
    reason: str | None = None


def availability(child: ChildIssue) -> Availability:
    """Availability per the review follow-up workflow.

    A child is available only when it is open, carries ``approve-fix``, does not
    carry ``decision-pending``, and has neither an exact ``Status: in progress``
    nor an exact ``Status: fixed`` comment.
    """
    if child.state.upper() != "OPEN":
        return Availability(False, "CLOSED")
    if LABEL_APPROVE_FIX not in child.labels:
        return Availability(False, "MISSING_APPROVE_FIX")
    if LABEL_DECISION_PENDING in child.labels:
        return Availability(False, "DECISION_PENDING")
    flags = status_flags(child.comment_bodies)
    if flags.in_progress:
        return Availability(False, "STATUS_IN_PROGRESS")
    if flags.fixed:
        return Availability(False, "STATUS_FIXED")
    return Availability(True)


def select_first_available(children: list[ChildIssue]) -> Selection:
    """Select the first available child.

    ``children`` must already be in the parent's native ``subIssues`` order;
    this function deliberately does not sort. Selection stops at the first
    available child, so children after it are not inspected and are not reported
    as skipped — the workflow processes exactly one child per run.
    """
    skipped: list[SkippedChild] = []
    for child in children:
        verdict = availability(child)
        if verdict.available:
            return Selection(selected=child, skipped=skipped)
        skipped.append(
            SkippedChild(
                number=child.number,
                title=child.title,
                url=child.url,
                reason=verdict.reason or "CLOSED",
            )
        )
    return Selection(selected=None, skipped=skipped)


def is_in_flight(child: ChildIssue) -> bool:
    """True when the child is the workflow's in-flight child.

    That is: still open and already carrying the exact ``Status: in progress``
    comment that ``start`` posts.
    """
    return child.state.upper() == "OPEN" and status_flags(child.comment_bodies).in_progress


def can_override_selection(explicit: ChildIssue, selection: Selection) -> bool:
    """Whether an explicit ``--issue`` may override native-order selection.

    Allowed when the explicit child is the one selection already chose, when
    selection found no child at all, or when the explicit child is the
    workflow's in-flight child. The in-flight exception exists because ``start``
    marks the selected child in progress, which removes it from native-order
    selection: without it, resuming (``start``) or closing (``fixed``) that
    child would be impossible whenever a later approved child exists. It never
    authorises skipping ahead to a later untouched child.
    """
    if selection.selected is None:
        return True
    if selection.selected.number == explicit.number:
        return True
    return is_in_flight(explicit)


def priority_label(labels: list[str]) -> str | None:
    """The child's priority label, when exactly one known priority label is present."""
    found = [label for label in PRIORITY_LABELS if label in labels]
    return found[0] if len(found) == 1 else None


# ── Approval step ─────────────────────────────────────────────────────────


@dataclass
class ApprovalPlan:
    """The label, label removal, and comment the approval step must apply."""

    add_labels: list[str] = field(default_factory=list)
    remove_labels: list[str] = field(default_factory=list)
    add_decision_comment: bool = False


def approval_plan(child: ChildIssue) -> ApprovalPlan:
    """What the approval step must change on an open child so it becomes available.

    Closed children are never planned here; the caller preserves them unchanged.
    """
    return ApprovalPlan(
        add_labels=[] if LABEL_APPROVE_FIX in child.labels else [LABEL_APPROVE_FIX],
        remove_labels=(
            [LABEL_DECISION_PENDING] if LABEL_DECISION_PENDING in child.labels else []
        ),
        add_decision_comment=not has_exact_comment(
            child.comment_bodies, DECISION_APPROVE_FIX
        ),
    )


def is_approved(child: ChildIssue) -> bool:
    """True when an open child already carries the full approval state."""
    return (
        child.state.upper() == "OPEN"
        and LABEL_APPROVE_FIX in child.labels
        and LABEL_DECISION_PENDING not in child.labels
        and has_exact_comment(child.comment_bodies, DECISION_APPROVE_FIX)
    )


def closing_body_repeats_status(body: str) -> bool:
    """True when the closing comment body opens with the exact status line.

    The status is recorded as its own exact-match comment so availability checks
    stay a strict equality test; the closing comment must not repeat it.
    """
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped:
            return stripped.startswith(STATUS_FIXED)
    return False


# ── Closing an issue (P1.2, design §8.4/§17 Z9) ───────────────────────────

#: One close action: post the exact ``Status: fixed`` comment if absent, then close.
CLOSE_ACTION_CLOSE = "close"
#: Closed **and** already carrying the exact ``Status: fixed`` comment: repeating the call
#: is a no-op, not a conflict. Without it a resumable workflow could never re-run a close it
#: already completed (native-order selection has moved on by then).
CLOSE_ACTION_NOOP = "noop"

#: Refusals, kept as tokens so ``close`` and ``fixed`` cannot drift apart in wording or
#: ordering: a missing label is reported before the state, exactly as ``fixed`` always has.
CLOSE_REFUSAL_MISSING_LABELS = "MISSING_LABELS"
CLOSE_REFUSAL_NOT_OPEN = "NOT_OPEN"


@dataclass
class ClosePlan:
    """What one close must do to a child, or why it must refuse (design §7.2/§8.4).

    ``action`` is :data:`CLOSE_ACTION_CLOSE` or :data:`CLOSE_ACTION_NOOP`.
    ``status_comment`` is true exactly when the exact ``Status: fixed`` comment is still
    absent, so the marker is posted once and never duplicated. ``refusal`` is empty when
    the call may proceed; otherwise it is one of the ``CLOSE_REFUSAL_*`` tokens and
    ``missing_labels`` names the labels the child lacks.
    """

    action: str = CLOSE_ACTION_CLOSE
    status_comment: bool = False
    missing_labels: list[str] = field(default_factory=list)
    refusal: str = ""


def close_plan(child: ChildIssue) -> ClosePlan:
    """**The rule**: may this child be closed, and does it still need the status marker?

    P1.2 moved the close behind the push, but the closing *guards* are unchanged and are
    now shared by two commands — ``fixed`` (in-stage, kept for compatibility) and ``close``
    (the deferred close ``aidw fix`` runs after ``F5 commit-and-push`` verifies the push).
    One rule, so the two commands cannot disagree about what is safe to close:

    1. closed **and** already marked fixed → :data:`CLOSE_ACTION_NOOP` (idempotent re-run);
    2. missing ``review-follow-up`` or ``approve-fix`` → refuse (§7.2's label guard);
    3. not ``OPEN`` without that marker → refuse to reopen or re-close;
    4. otherwise close, posting the exact ``Status: fixed`` comment only when it is absent.

    The ordering matters: the no-op is checked first (a completed close is closed *and*
    marked), then the labels, then the state. Purity: no I/O, no mutation, deterministic.
    """
    flags = status_flags(child.comment_bodies)
    if child.state.upper() != "OPEN" and flags.fixed:
        return ClosePlan(action=CLOSE_ACTION_NOOP, status_comment=False)
    missing = [
        label
        for label in (LABEL_REVIEW_FOLLOW_UP, LABEL_APPROVE_FIX)
        if label not in child.labels
    ]
    if missing:
        return ClosePlan(missing_labels=missing, refusal=CLOSE_REFUSAL_MISSING_LABELS)
    if child.state.upper() != "OPEN":
        return ClosePlan(refusal=CLOSE_REFUSAL_NOT_OPEN)
    return ClosePlan(status_comment=not flags.fixed)


# ── Argument parsing: fix-next CLI ────────────────────────────────────────

COMMANDS = ("select", "start", "fixed", "close", "verify", "approve")


@dataclass
class ParsedArgs:
    command: str = "help"
    pr: str | None = None
    issue: int | None = None
    body_file: str | None = None
    dry_run: bool = False
    allow_branch_mismatch: bool = False


def parse_args(argv: list[str]) -> ParsedArgs:
    """Parse CLI arguments. Raises :class:`UsageError` on anything unexpected."""
    parsed = ParsedArgs()
    command = argv[0] if argv else None
    rest = argv[1:]

    if command is None or command in ("--help", "-h", "help"):
        return parsed
    if command not in COMMANDS:
        raise UsageError(
            f'Unknown command "{command}". Expected one of: {", ".join(COMMANDS)}.'
        )
    parsed.command = command

    index = 0
    while index < len(rest):
        flag = rest[index]

        def read_value(flag: str = flag, index: int = index) -> str:
            nxt = rest[index + 1] if index + 1 < len(rest) else None
            if nxt is None or nxt.startswith("--"):
                raise UsageError(f"Flag {flag} requires a value.")
            return nxt

        if flag == "--pr":
            parsed.pr = read_value()
            index += 2
        elif flag == "--body-file":
            parsed.body_file = read_value()
            index += 2
        elif flag == "--issue":
            value = read_value()
            parsed.issue = _positive_int(value)
            index += 2
        elif flag == "--dry-run":
            parsed.dry_run = True
            index += 1
        elif flag == "--allow-branch-mismatch":
            parsed.allow_branch_mismatch = True
            index += 1
        elif flag in ("--help", "-h"):
            parsed.command = "help"
            index += 1
        else:
            raise UsageError(f'Unknown flag "{flag}".')

    return parsed


def _positive_int(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError:
        parsed = 0
    if parsed <= 0:
        raise UsageError(f'--issue must be a positive integer, got "{value}".')
    return parsed


# ── Argument parsing: publisher CLI ───────────────────────────────────────


@dataclass
class PublishArgs:
    #: Explicit PR number/URL, or ``None`` to resolve from the current branch.
    pr: str | None = None
    #: Manifest path, or ``-`` for stdin.
    input: str = "-"
    #: Explicit ``owner/name``, or ``None`` to resolve from the current repo.
    repo: str | None = None
    dry_run: bool = False


def parse_publish_args(argv: list[str]) -> PublishArgs:
    """Parse the publisher CLI arguments. Raises :class:`UsageError` on error."""
    # package managers may insert a bare ``--`` when forwarding arguments.
    if argv and argv[0] == "--":
        argv = argv[1:]

    parsed = PublishArgs(input="")
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--pr":
            parsed.pr = _require_value(argv, index + 1, arg)
            index += 2
        elif arg == "--input":
            parsed.input = _require_value(argv, index + 1, arg)
            index += 2
        elif arg == "--repo":
            parsed.repo = _require_value(argv, index + 1, arg)
            index += 2
        elif arg == "--dry-run":
            parsed.dry_run = True
            index += 1
        elif arg in ("--help", "-h"):
            raise UsageError(publish_usage(), 0)
        else:
            raise UsageError(f"Unknown argument: {arg}")

    if not parsed.input:
        raise UsageError(publish_usage())

    return parsed


def _require_value(argv: list[str], index: int, flag: str) -> str:
    value = argv[index] if index < len(argv) else None
    if value is None or value.startswith("--"):
        raise UsageError(f"Flag {flag} requires a value.")
    return value


def publish_usage() -> str:
    return (
        "Usage: publish_review_followups.py [--pr <number-or-url>] --input <manifest.json> "
        "[--repo <owner/name>] [--dry-run]"
    )


# ── Review finding manifest ───────────────────────────────────────────────


@dataclass
class Finding:
    id: str
    priority: str
    confidence: int
    title: str
    whatFound: str  # noqa: N815 - matches the documented manifest JSON keys
    whyItMatters: str  # noqa: N815
    triggerAndEffect: str  # noqa: N815
    where: str
    suggestedFix: str  # noqa: N815


@dataclass
class Manifest:
    findings: list[Finding]


_STRING_FIELDS = (
    "title",
    "whatFound",
    "whyItMatters",
    "triggerAndEffect",
    "where",
    "suggestedFix",
)

_FINDING_KEYS = ("id", "priority", "confidence", *_STRING_FIELDS)

_ID_RE = re.compile(r"^F\d+$")


def validate_manifest(parsed: object) -> Manifest:
    """Validate a parsed JSON value as a review finding manifest.

    This intentionally replaces a schema library: the script directory is copied
    between repositories with the prompts, so it must run without installing
    dependencies. The accepted shape is exactly documented in
    ``aidt/prompts/review-findings-to-github.md``.
    """
    if not isinstance(parsed, dict):
        raise UsageError("Manifest must be a JSON object.")
    extra_keys = [key for key in parsed if key != "findings"]
    if extra_keys:
        raise UsageError(f"Manifest has unexpected key(s): {', '.join(extra_keys)}.")
    findings_value = parsed.get("findings")
    if not isinstance(findings_value, list) or not findings_value:
        raise UsageError('Manifest must contain a non-empty "findings" array.')

    findings = [
        _validate_finding(entry, index) for index, entry in enumerate(findings_value)
    ]

    expected_ids = [f"F{index + 1}" for index in range(len(findings))]
    actual_ids = [finding.id for finding in findings]
    if expected_ids != actual_ids:
        raise UsageError(
            "Finding IDs must be sequential in review order: "
            f"expected {', '.join(expected_ids)}, got {', '.join(actual_ids)}."
        )

    return Manifest(findings=findings)


def _validate_finding(entry: object, index: int) -> Finding:
    at = f"findings[{index}]"
    if not isinstance(entry, dict):
        raise UsageError(f"{at} must be an object.")
    extra_keys = [key for key in entry if key not in _FINDING_KEYS]
    if extra_keys:
        raise UsageError(f"{at} has unexpected key(s): {', '.join(extra_keys)}.")
    missing_keys = [key for key in _FINDING_KEYS if key not in entry]
    if missing_keys:
        raise UsageError(f"{at} is missing required key(s): {', '.join(missing_keys)}.")

    finding_id = entry["id"]
    if not isinstance(finding_id, str) or not _ID_RE.match(finding_id):
        raise UsageError(f"{at}.id must use the form F1, F2, ...")
    priority = entry["priority"]
    if not isinstance(priority, str) or priority not in PRIORITY_LABELS:
        raise UsageError(f"{at}.priority must be one of: {', '.join(PRIORITY_LABELS)}.")
    confidence = entry["confidence"]
    if (
        not isinstance(confidence, int)
        or isinstance(confidence, bool)
        or confidence < 0
        or confidence > 5
    ):
        raise UsageError(f"{at}.confidence must be an integer from 0 to 5.")

    strings: dict[str, str] = {}
    for name in _STRING_FIELDS:
        value = entry[name]
        if not isinstance(value, str) or not value.strip():
            raise UsageError(f"{at}.{name} must be a non-empty string.")
        strings[name] = value.strip()

    return Finding(
        id=finding_id,
        priority=priority,
        confidence=confidence,
        title=strings["title"],
        whatFound=strings["whatFound"],
        whyItMatters=strings["whyItMatters"],
        triggerAndEffect=strings["triggerAndEffect"],
        where=strings["where"],
        suggestedFix=strings["suggestedFix"],
    )


def parse_manifest(text: str) -> Manifest:
    """Parse and validate manifest JSON text."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise UsageError(f"The manifest is not valid JSON: {error}") from error
    return validate_manifest(parsed)
