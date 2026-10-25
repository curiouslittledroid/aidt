"""Deterministic parsing of review verdicts (design §18).

Review prompts end with exactly one of ``Approve``, ``Request changes`` or ``Blocked``.
AIDW parses that verdict deterministically. Naive "last mention wins" is not enough:
review commentary frequently names a verdict it is *rejecting* after the verdict line
(e.g. ``**Verdict: Request changes** ... so `Blocked` is not warranted``). The parser
therefore looks, in order, for:

1. an explicit ``Verdict: <token>`` declaration on one line;
2. a line that begins with a verdict token (the conclusion is often its own bold line);
3. the last bare mention, as a final fallback.

When none is found it returns ``None`` and the workflow fails closed.
"""

from __future__ import annotations

import re

APPROVE = "Approve"
REQUEST_CHANGES = "Request changes"
BLOCKED = "Blocked"

_TOKEN = r"(request changes|blocked|approved|approve)"

#: ``Verdict: Request changes`` / ``**Verdict: Request changes**`` on a single line.
DECLARATION_RE = re.compile(
    rf"\bverdict\b[ \t]*[:\-\u2013\u2014]?[ \t]*\**[ \t]*{_TOKEN}\b", re.IGNORECASE
)

#: A line that begins with a verdict token (after markdown decoration).
LEADING_RE = re.compile(
    rf"^[ \t>*_#`\-\u2013\u2014]*\**[ \t]*{_TOKEN}\b", re.IGNORECASE | re.MULTILINE
)

#: Any bare mention.
MENTION_RE = re.compile(rf"\b{_TOKEN}\b", re.IGNORECASE)

_MAP = {
    "approve": APPROVE,
    "approved": APPROVE,
    "request changes": REQUEST_CHANGES,
    "blocked": BLOCKED,
}


def _last(matches: list[re.Match[str]]) -> str | None:
    if not matches:
        return None
    return _MAP[matches[-1].group(1).lower()]


def parse_verdict(text: str) -> str | None:
    """Return the final verdict in ``text``, or ``None`` when it is ambiguous."""
    for pattern in (DECLARATION_RE, LEADING_RE, MENTION_RE):
        verdict = _last(list(pattern.finditer(text)))
        if verdict is not None:
            return verdict
    return None


def is_approved(text: str) -> bool:
    return parse_verdict(text) == APPROVE
