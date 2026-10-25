"""Workflow policy constants for the review follow-up scripts.

These strings are a contract with the sibling prompts that publish, approve,
and consume review follow-ups:

  - ``aidt/prompts/review-findings-to-github.md``  (publisher)
  - ``aidt/prompts/approve-review-followups.md``   (approver)
  - ``aidt/prompts/fix-next-review-followup.md``   (consumer)

Change them here and in those prompts together, or not at all.

The scripts deliberately have no runtime dependencies beyond the Python
standard library and no project-specific paths, so this directory can be copied
into another repository with the prompts. They run on any Python 3.9+:

    python3 aidt/prompts/scripts/review-followup/review_followup.py --help
"""

from __future__ import annotations

#: Present on the parent issue and on every child issue.
LABEL_REVIEW_FOLLOW_UP = "review-follow-up"

#: Added by the human approval step; required before implementation starts.
LABEL_APPROVE_FIX = "approve-fix"

#: Blocks implementation until a human records a decision.
LABEL_DECISION_PENDING = "decision-pending"

#: Exactly one of these is expected on every child issue.
PRIORITY_LABELS = ("must-fix", "should-fix", "could-fix")

#: Exact comment bodies that record workflow status.
#:
#: Availability and idempotency are decided with strict equality, so this text
#: must never vary (no trailing punctuation, no case changes).
STATUS_IN_PROGRESS = "Status: in progress"
STATUS_FIXED = "Status: fixed"

#: The approval decision an agent needs before it may implement a child.
DECISION_APPROVE_FIX = "Decision: approve-fix"


def parent_marker(pr_url: str) -> str:
    """Exact parent-issue body marker.

    ``pr_url`` must be the canonical browser URL returned by
    ``gh pr view <ref> --json url``, not the ``api.github.com`` URL.
    """
    return f"<!-- mythical-forge-review-followups: pr={pr_url} -->"


def child_marker(pr_url: str, finding_id: str) -> str:
    """Exact child-issue body marker, one per review finding."""
    return f"<!-- mythical-forge-review-follow-up: pr={pr_url} finding={finding_id} -->"


def summary_marker(pr_url: str) -> str:
    """Exact marker on the single PR summary comment."""
    return f"<!-- mythical-forge-review-followups-summary: pr={pr_url} -->"


#: Canonical label definitions.
#:
#: A single source for every label the workflow owns, so the publisher creates
#: exactly the same colors and descriptions that the approval prompt documents.
LABEL_DEFINITIONS = {
    LABEL_REVIEW_FOLLOW_UP: {
        "color": "5319E7",
        "description": "Review-generated task or parent issue",
    },
    "must-fix": {"color": "B60205", "description": "Blocking review finding"},
    "should-fix": {
        "color": "D93F0B",
        "description": "Non-blocking but recommended finding",
    },
    "could-fix": {
        "color": "FBCA04",
        "description": "Limited review improvement or simplification",
    },
    LABEL_DECISION_PENDING: {
        "color": "EDEDED",
        "description": "Human decision required before implementation",
    },
    LABEL_APPROVE_FIX: {
        "color": "B8D64A",
        "description": "Human-approved review follow-up fix",
    },
}

#: The subset the publisher ensures up front. ``approve-fix`` is intentionally
#: absent: it is created by the approval step only when a human approves a
#: finding, so publishing a review never pre-creates an approval label.
PUBLISHER_LABELS = (
    LABEL_REVIEW_FOLLOW_UP,
    "must-fix",
    "should-fix",
    "could-fix",
    LABEL_DECISION_PENDING,
)

#: Process exit codes. Distinct codes let a caller branch without parsing text.
EXIT_OK = 0
#: The selected issue's verification failed.
EXIT_VERIFY_FAILED = 1
#: Usage, validation, or GitHub-command failure.
EXIT_ERROR = 2
#: No approved open review follow-up is available.
EXIT_NONE_AVAILABLE = 3
#: The requested issue conflicts with the workflow's selection rules.
EXIT_CONFLICT = 4

EXIT_CODES = {
    "OK": EXIT_OK,
    "VERIFY_FAILED": EXIT_VERIFY_FAILED,
    "ERROR": EXIT_ERROR,
    "NONE_AVAILABLE": EXIT_NONE_AVAILABLE,
    "CONFLICT": EXIT_CONFLICT,
}
