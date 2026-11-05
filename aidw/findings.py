"""Extract review findings from the code-review final message (design §8.3, §18).

The `/code-review` prompt reports each finding as a labelled block:

```
Priority: Must fix / Should fix / Could fix
Confidence: 0 to 5
What I found: ...
Why it matters: ...
Trigger and effect: ...
Where: ...
Suggested fix: ...
```

AIDT parses those blocks into the JSON manifest that the bundled publisher expects. The
parser is strict and **fails closed**: an unknown priority, an out-of-range confidence, or
an empty required field yields a problem rather than a guessed manifest. A manifest is
only built when every finding parses cleanly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

PRIORITY_MAP = {
    "must fix": "must-fix",
    "must-fix": "must-fix",
    "should fix": "should-fix",
    "should-fix": "should-fix",
    "could fix": "could-fix",
    "could-fix": "could-fix",
}

#: Manifest field order after ``id``/``priority``/``confidence``.
STRING_FIELDS = (
    "whatFound",
    "whyItMatters",
    "triggerAndEffect",
    "where",
    "suggestedFix",
)

_LABELS = {
    "priority": "priority",
    "confidence": "confidence",
    "what i found": "whatFound",
    "why it matters": "whyItMatters",
    "trigger and effect": "triggerAndEffect",
    "where": "where",
    "suggested fix": "suggestedFix",
}

_LABEL_RE = re.compile(
    r"^[ \t]*(?:[-*+][ \t]+)?(?:\*\*)?([A-Za-z][A-Za-z ]*?)(?:\*\*)?[ \t]*:"
    r"[ \t]*(?:\*\*)?[ \t]*(.*?)(?:\*\*)?[ \t]*$"
)
_CONFIDENCE_RE = re.compile(r"\d+")
_TITLE_CLEAN_RE = re.compile(r"[`*_#>]+")

#: Markdown emphasis that can wrap a whole label line, e.g. ``**Priority: Must fix**``.
_EMPHASIS_STRIP = "*`_ \t"


def _clean_scalar(value: str) -> str:
    """Strip markdown emphasis and whitespace from a one-word field (priority)."""
    return value.strip().strip(_EMPHASIS_STRIP).strip()


@dataclass
class ParsedFinding:
    priority: str
    confidence: int
    what_found: str
    why_it_matters: str
    trigger_and_effect: str
    where: str
    suggested_fix: str

    def to_manifest_entry(self, index: int) -> dict[str, Any]:
        return {
            "id": f"F{index}",
            "priority": self.priority,
            "confidence": self.confidence,
            "title": _title(self.what_found),
            "whatFound": self.what_found,
            "whyItMatters": self.why_it_matters,
            "triggerAndEffect": self.trigger_and_effect,
            "where": self.where,
            "suggestedFix": self.suggested_fix,
        }


def _title(what_found: str) -> str:
    """A short, imperative-ish title derived from the finding body."""
    first = what_found.strip().splitlines()[0] if what_found.strip() else ""
    first = _TITLE_CLEAN_RE.sub("", first).strip()
    sentence = re.split(r"(?<=[.!?])\s", first)[0].strip()
    sentence = sentence.rstrip(".!? ").strip()
    if not sentence:
        return "Review finding"
    if len(sentence) > 80:
        sentence = sentence[:77].rstrip() + "..."
    return sentence


def _collect_blocks(text: str) -> list[dict[str, str]]:
    """Group labelled lines into per-finding field dictionaries."""
    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    current_field: str | None = None

    for raw in text.splitlines():
        match = _LABEL_RE.match(raw)
        label = match.group(1).strip().lower() if match else None
        if match and label in _LABELS:
            key = _LABELS[label]
            if key == "priority":
                current = {}
                blocks.append(current)
            if current is None:
                current_field = None
                continue
            current_field = key
            current[key] = match.group(2).strip()
            continue

        if current is None or current_field is None:
            continue
        if (
            not raw.strip()
            or raw.lstrip().startswith("#")
            or raw.lstrip().startswith("```")
            or raw.lstrip().startswith("~~~")
        ):
            # A blank line, a heading, or a code fence ends the current field; do not
            # bleed into the verdict section below the findings, and never absorb the
            # fence that closes a finding block into its last field.
            current_field = None
            continue
        current[current_field] = f"{current[current_field]}\n{raw.rstrip()}".strip()

    return blocks


def parse_review_findings(text: str) -> tuple[list[ParsedFinding], list[str]]:
    """Return ``(findings, problems)``.

    ``problems`` is non-empty when any finding is malformed; callers must then fail
    closed and publish nothing.
    """
    findings: list[ParsedFinding] = []
    problems: list[str] = []

    for index, block in enumerate(_collect_blocks(text), start=1):
        priority = PRIORITY_MAP.get(_clean_scalar(block.get("priority", "")).lower())
        if priority is None:
            problems.append(f"F{index}: unknown priority {block.get('priority', '')!r}")

        confidence_raw = block.get("confidence", "")
        confidence_match = _CONFIDENCE_RE.search(confidence_raw)
        confidence = int(confidence_match.group()) if confidence_match else -1
        if not (0 <= confidence <= 5):
            problems.append(f"F{index}: invalid confidence {confidence_raw!r}")

        values = {key: block.get(key, "").strip() for key in STRING_FIELDS}
        for key, value in values.items():
            if not value:
                problems.append(f"F{index}: missing {key}")

        findings.append(
            ParsedFinding(
                priority=priority or "",
                confidence=confidence,
                what_found=values["whatFound"],
                why_it_matters=values["whyItMatters"],
                trigger_and_effect=values["triggerAndEffect"],
                where=values["where"],
                suggested_fix=values["suggestedFix"],
            )
        )

    return findings, problems


def to_manifest(findings: list[ParsedFinding]) -> dict[str, Any]:
    """The exact JSON shape the bundled publisher validates."""
    return {"findings": [f.to_manifest_entry(i) for i, f in enumerate(findings, start=1)]}


def finding_title(finding: ParsedFinding) -> str:
    """The short title AIDT derives from a finding's ``What I found`` text."""
    return _title(finding.what_found)


#: Priorities that must be fixed one finding at a time. ``could-fix`` is excluded: it is
#: non-blocking, so all of its findings are reworked in a single stage.
BLOCKING_PRIORITIES = ("must-fix", "should-fix")


def partition_findings(
    findings: list[ParsedFinding],
) -> tuple[list[ParsedFinding], list[ParsedFinding]]:
    """Split into ``(blocking, non_blocking)``, preserving review order in each."""
    blocking = [f for f in findings if f.priority in BLOCKING_PRIORITIES]
    non_blocking = [f for f in findings if f.priority not in BLOCKING_PRIORITIES]
    return blocking, non_blocking


def findings_summary(findings: list[ParsedFinding]) -> str:
    """``3 findings (2 should-fix, 1 could-fix)``, or a marker when none parsed.

    Findings whose priority did not parse are grouped under ``unparseable
    priority`` rather than silently dropped from the breakdown.
    """
    if not findings:
        return "no machine-readable findings"
    counts: dict[str, int] = {}
    for finding in findings:
        key = finding.priority or "unparseable priority"
        counts[key] = counts.get(key, 0) + 1
    known = [priority for priority in ("must-fix", "should-fix", "could-fix") if priority in counts]
    other = [key for key in counts if key not in known]
    breakdown = ", ".join(f"{counts[key]} {key}" for key in (*known, *other))
    noun = "finding" if len(findings) == 1 else "findings"
    return f"{len(findings)} {noun} ({breakdown})"


def _finding_text_block(finding: ParsedFinding) -> str:
    """One finding rendered in the reviewer's own ``Priority:``/``Confidence:`` format."""
    return (
        "```text\n"
        f"Priority: {finding.priority}\n"
        f"Confidence: {finding.confidence}\n"
        f"What I found: {finding.what_found}\n"
        f"Why it matters: {finding.why_it_matters}\n"
        f"Trigger and effect: {finding.trigger_and_effect}\n"
        f"Where: {finding.where}\n"
        f"Suggested fix: {finding.suggested_fix}\n"
        "```"
    )


def render_finding_block(finding: ParsedFinding, *, index: int, total: int) -> str:
    """Re-emit one finding in the reviewer's own format, for a single-finding fix stage."""
    return (
        f"## Review finding {index} of {total} to address\n\n"
        "Fix exactly this finding. Do not address the other findings in this run.\n\n"
        f"{_finding_text_block(finding)}\n"
    )


def render_could_fix_block(findings: list[ParsedFinding]) -> str:
    """Every non-blocking finding in one stage, so ``could-fix`` costs one invocation."""
    noun = "finding" if len(findings) == 1 else "findings"
    blocks = "\n\n".join(_finding_text_block(finding) for finding in findings)
    return (
        f"## Non-blocking (could-fix) review {noun} to address together\n\n"
        f"The review raised {len(findings)} non-blocking {noun}. Fix all of them in this "
        "single pass. Do not address the blocking findings, which were fixed in separate "
        "stages.\n\n"
        f"{blocks}\n"
    )


#: Appended to the publisher stage so a fresh session uses the manifest AIDW extracted.
#:
#: The pointer is an **absolute** path. The stage runs with the target repo as its cwd and
#: the run directory is outside it, so a repo-relative value made the publisher look for
#: `<repo>/artifacts/review-manifest.json`, find nothing, and stop without publishing —
#: correctly (inventing findings is worse), but the review still recorded
#: ``followups_published`` (see :func:`aidw.github.verify_published`). Absolute is the one
#: value that cannot be resolved against the wrong root.
MANIFEST_EXTRA = """\

## AIDW-supplied manifest

The preceding review's findings have already been extracted to this manifest. Use it as
`--input` and do **not** re-derive or invent findings:

- manifest: `{manifest_path}`

That path is absolute and lies in AIDW's run directory, outside your working directory.
Copy it verbatim: do not resolve it against the repository, and do not expect to find it
under `artifacts/` here.

Run the publisher `--dry-run` first, then the real command, exactly as the prompt above
instructs.
"""
