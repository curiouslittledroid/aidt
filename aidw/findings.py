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

**Rounds after the first** add an optional ``Verdict on this finding:`` line (the delta
brief requires one per previous finding: ``resolved`` / ``not resolved`` / ``newly
contradicted``). Those blocks are *verdicts on earlier findings*, not new findings, so a
``resolved`` block never counts as blocking — otherwise an approving review that resolved
everything would contradict itself under M2 and block the run (observed on PR #282's
`04-A1.3`, 2026-11-16). An absent or unrecognised verdict keeps the block blocking, which
is the fail-closed direction: no finding is silently cleared.

The **prompt** review additionally classifies each finding with an optional ``Kind:`` line
(``spec-gap`` / ``prompt-gap``, G1.1, design §8.1). It is parsed here but **not** made a
required field and **not** published: §8.3's code-review findings carry no ``Kind:`` and
must keep parsing clean, so the prompt workflow is where a missing, empty or unrecognised
kind fails closed (see :func:`normalise_kind` and :data:`KIND_MAP`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: The two canonical ``Kind:`` tokens (G1.1, design §8.1). Spelled once so the parser, the
#: workflow's classification stop and the tests cannot drift on the strings.
SPEC_GAP = "spec-gap"
PROMPT_GAP = "prompt-gap"

PRIORITY_MAP = {
    "must fix": "must-fix",
    "must-fix": "must-fix",
    "should fix": "should-fix",
    "should-fix": "should-fix",
    "could fix": "could-fix",
    "could-fix": "could-fix",
}

#: The prompt-review finding classifications (G1.1, design §8.1), normalised exactly as
#: :data:`PRIORITY_MAP` is — same ``_clean_scalar`` path, so a space or a hyphen both parse.
#:
#: The pair means: a ``spec-gap`` is a defect only the cited spec or roadmap can close (the
#: prompt cannot be fixed without changing its source of truth), and a ``prompt-gap`` is
#: fixable by editing the prompt. Only the prompt review enforces the field
#: (``aidw/workflows/prompt.py``); parsing stays optional so §8.3's code-review findings,
#: which carry no ``Kind:``, keep parsing clean and the published manifest shape does not
#: change.
KIND_MAP = {
    "spec gap": SPEC_GAP,
    "spec-gap": SPEC_GAP,
    "prompt gap": PROMPT_GAP,
    "prompt-gap": PROMPT_GAP,
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
    # Optional at parse level and prompt-review only (G1.1, design §8.1): code-review
    # findings have no ``Kind:``, and the prompt review enforces the field itself. Recognised
    # as a label so it never appends itself to the confidence field's text.
    "kind": "kind",
    "what i found": "whatFound",
    "why it matters": "whyItMatters",
    "trigger and effect": "triggerAndEffect",
    "where": "where",
    "suggested fix": "suggestedFix",
    # Optional, later rounds only (the delta brief's per-finding verdict). Recognised as a
    # label so it does not append itself to the preceding field's text.
    "verdict on this finding": "resolution",
}

_LABEL_RE = re.compile(
    r"^[ \t]*(?:[-*+][ \t]+)?(?:\*\*)?([A-Za-z][A-Za-z ]*?)(?:\*\*)?[ \t]*:"
    r"[ \t]*(?:\*\*)?[ \t]*(.*?)(?:\*\*)?[ \t]*$"
)
_CONFIDENCE_RE = re.compile(r"\d+")
_TITLE_CLEAN_RE = re.compile(r"[`*_#>]+")

#: Markdown emphasis that can wrap a whole label line, e.g. ``**Priority: Must fix**``.
_EMPHASIS_STRIP = "*`_ \t"


#: The per-finding verdicts the delta brief asks for, normalised.
RESOLVED = "resolved"
NOT_RESOLVED = "not-resolved"
NEWLY_CONTRADICTED = "newly-contradicted"

#: Longer phrases first: ``not resolved`` must not be read as ``resolved``.
_RESOLUTION_PREFIXES = (
    ("not resolved", NOT_RESOLVED),
    ("newly contradicted", NEWLY_CONTRADICTED),
    ("resolved", RESOLVED),
)


def normalise_resolution(value: str) -> str:
    """The canonical per-finding verdict, or ``""`` when absent or unrecognised.

    Prefix-matched on the cleaned, lowercased text so prose after the token
    (``resolved. The current prompt conditions …``) is tolerated. An unrecognised value is
    deliberately **not** an error: the caller keeps the finding blocking, which is the
    conservative reading, and a formatting quirk must not fail an otherwise valid review.
    """
    cleaned = _clean_scalar(value).rstrip(".").strip().lower()
    for prefix, canonical in _RESOLUTION_PREFIXES:
        if cleaned.startswith(prefix):
            return canonical
    return ""


def normalise_kind(value: str) -> str:
    """The canonical ``Kind:`` token, or ``""`` when absent or unrecognised.

    Optional at parse level and deliberately **not** a ``problems`` entry: §8.3's
    code-review findings carry no ``Kind:``, so a required-at-parse field would fail every
    one of them closed and change the published manifest. The prompt review's own
    fail-closed classification check (``aidw/workflows/prompt.py``) is where a missing,
    empty or unrecognised kind stops the run — parse here, enforce there (G1.1).
    """
    return KIND_MAP.get(_clean_scalar(value).lower(), "")


def _clean_scalar(value: str) -> str:
    """Strip markdown emphasis and whitespace from a one-word field (priority, kind)."""
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
    #: Later rounds only: ``resolved`` / ``not-resolved`` / ``newly-contradicted``, else ``""``.
    resolution: str = ""
    #: Prompt review only (G1.1): ``spec-gap`` / ``prompt-gap``, else ``""``. Never published
    #: (``to_manifest_entry`` omits it), so §8.3's manifest shape is unchanged.
    kind: str = ""

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
                resolution=normalise_resolution(block.get("resolution", "")),
                kind=normalise_kind(block.get("kind", "")),
            )
        )

    return findings, problems


def to_manifest(findings: list[ParsedFinding]) -> dict[str, Any]:
    """The exact JSON shape the bundled publisher validates.

    ``kind`` is deliberately absent from every entry (G1.1): the manifest is §8.3's contract
    and its shape does not change for a prompt-review-only classification.
    """
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
    """Split into ``(to_fix_one_at_a_time, could_fix_batch)``, preserving review order.

    A blocking priority is necessary but not sufficient: a later round's per-finding verdict
    can close the finding, and a closed finding needs no fix stage, so it appears in
    **neither** list. ``resolved`` is the only verdict that clears one; ``not-resolved``,
    ``newly-contradicted``, an absent verdict and an unrecognised one all stay blocking, so
    the only thing that clears a finding is the reviewer saying so. The lengths therefore do
    not have to add up to ``len(findings)`` — the review record keeps every finding either
    way (``to_manifest`` still publishes them all).
    """
    blocking = [
        f
        for f in findings
        if f.priority in BLOCKING_PRIORITIES and f.resolution != RESOLVED
    ]
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
    """One finding rendered in the reviewer's own ``Priority:``/``Confidence:`` format.

    ``Kind:`` is re-emitted **when present** (G1.1). This is the single re-emitter for both
    the fix stages and ``stage_registry.render_delta_brief``'s shrink, so dropping it here
    would hand a spec-gap finding's classification to a fixer or lose it in a shrunk brief —
    the same trap Z8 closed for ``Verdict on this finding:``. A code-review finding has no
    kind and renders byte-identically to before.
    """
    kind = f"Kind: {finding.kind}\n" if finding.kind else ""
    return (
        "```text\n"
        f"Priority: {finding.priority}\n"
        f"Confidence: {finding.confidence}\n"
        f"{kind}"
        f"What I found: {finding.what_found}\n"
        f"Why it matters: {finding.why_it_matters}\n"
        f"Trigger and effect: {finding.trigger_and_effect}\n"
        f"Where: {finding.where}\n"
        f"Suggested fix: {finding.suggested_fix}\n"
        + (
            f"Verdict on this finding: {finding.resolution}\n"
            if finding.resolution
            else ""
        )
        + "```"
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
