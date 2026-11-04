"""Deterministic parsing of review verdicts (design §18).

Review prompts end with exactly one of ``Approve``, ``Request changes`` or ``Blocked``.
AIDW parses that verdict deterministically. Naive "last mention wins" is not enough:
review commentary frequently names a verdict it is *rejecting* after the verdict line
(e.g. ``**Verdict: Request changes** ... so `Blocked` is not warranted``). The parser
therefore looks, in order, for:

1. an explicit ``Verdict: <token>`` declaration on one line;
2. a line that begins with a verdict token (the conclusion is often its own bold line);
3. the last bare mention, as a final fallback.

Every pass reads **prose only** (M1, design §17). A review that lists the workflow
modules it read writes paths such as ``implement/review/approve/fix/prompt``, and a
review that discusses a consumer site writes a code span such as `` `approve`'s `(spec,)
= `` ``. Before M1 the third pass accepted those as a bare mention and returned
``Approve`` for a review that never emitted a verdict at all — E4.5b, 2026-11-04, where a
truncated reviewer report found five defects, one of them `Must fix`, and the loop
approved it without a single fix stage. So fenced code blocks are blanked, a token counts
only when it is not part of a path or module name, and passes 2-3 ignore inline code
spans unless the span is the line's whole content (`` `Approve` ``, but not
`` `approve`'s ``).

When none is found it returns ``None`` and the workflow fails closed.
"""

from __future__ import annotations

import re

APPROVE = "Approve"
REQUEST_CHANGES = "Request changes"
BLOCKED = "Blocked"

#: A verdict token in prose: not a path segment (``prompt/review/fix/approve``), not a
#: module or attribute name (``approve.py``, ``approve_round``) and not part of a longer
#: word (``approval``, ``unblocked``). ``approved`` is tried first so it is never read as
#: ``approve`` followed by a stray ``d``.
_PROSE_TOKEN = r"(?<![\w/.\-])(request changes|blocked|approved|approve)(?![\w/\-]|\.\w)"

#: Fenced code blocks quote the prompt, an evidence bundle or an example; they are never
#: the reviewer's own conclusion.
_FENCE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)

#: Markdown decoration and punctuation around a token: allowed around a verdict, never
#: what makes one.
_DECORATION = " \t`*_#>-–—()[].,;:!?\"'"

#: ``Verdict: Request changes`` / ``**Verdict:** `Approve` `` on a single line. The label
#: carries the meaning, so a backticked or bolded token is accepted here.
DECLARATION_RE = re.compile(
    rf"\bverdict\b[ \t]*[:\-\u2013\u2014]?[ \t]*(?:[`*_][ \t]*)*{_PROSE_TOKEN}",
    re.IGNORECASE,
)

#: A line that begins with a verdict token (after markdown decoration).
LEADING_RE = re.compile(
    rf"^[ \t>*_#`\-\u2013\u2014]*\**[ \t]*{_PROSE_TOKEN}",
    re.IGNORECASE | re.MULTILINE,
)

#: Any bare mention.
MENTION_RE = re.compile(_PROSE_TOKEN, re.IGNORECASE)

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


def _blank_fences(text: str) -> str:
    """``text`` with fenced code blocks blanked, offsets and line starts preserved."""
    return _FENCE_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _backticked(text: str, match: re.Match[str]) -> bool:
    """True when the match sits inside an inline code span (`` `approve` ``)."""
    before = text[match.start() - 1] if match.start() else ""
    after = text[match.end()] if match.end() < len(text) else ""
    return "`" in (before, after)


def _whole_line(text: str, match: re.Match[str]) -> bool:
    """True when only decoration surrounds the token on its own line (`` `Approve` ``)."""
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    line = text[start:] if end == -1 else text[start:end]
    return line.strip(_DECORATION) == match.group(1)


def parse_verdict(text: str) -> str | None:
    """Return the final verdict in ``text``, or ``None`` when it is ambiguous."""
    prose = _blank_fences(text)
    # 1. An explicit declaration wins: the label names a verdict, so backticks and bold
    #    around the token are decoration, not evidence of a symbol reference.
    verdict = _last(list(DECLARATION_RE.finditer(prose)))
    if verdict is not None:
        return verdict
    # 2. A verdict on its own line. A code span qualifies only when it *is* the line
    #    (`` `Approve` ``); a span with more content names a symbol (`approve`'s `x`).
    line_matches = [
        match
        for match in LEADING_RE.finditer(prose)
        if not _backticked(prose, match) or _whole_line(prose, match)
    ]
    verdict = _last(line_matches)
    if verdict is not None:
        return verdict
    # 3. The last bare mention, still prose: a backticked mention is a symbol reference.
    return _last(
        [match for match in MENTION_RE.finditer(prose) if not _backticked(prose, match)]
    )


def is_approved(text: str) -> bool:
    return parse_verdict(text) == APPROVE
