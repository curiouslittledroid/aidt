"""Tests for review-finding extraction (design §8.3, Phase 5)."""

from __future__ import annotations

from aidw import findings

REVIEW = """\
## Code review findings

### Finding: loop misses the tail

Priority: Should fix
Confidence: 4
What I found: The loop stops one element early.
Why it matters: Callers lose the final record.
Trigger and effect: With three items, the third is never processed.
Where: packages/shared/src/list.ts:42
Suggested fix: Iterate with a `<`-bound to the array length.

Priority: Could fix
Confidence: 3
What I found: A helper is duplicated in two modules.
Why it matters: The copies can drift apart.
Trigger and effect: None observable today.
Where: packages/shared/src/util.ts:10
Suggested fix: Extract one helper.

## Verdict

**Request changes** — the first finding is real.
"""

APPROVED = """\
No findings.

## Verdict

**Approve** — the change is correct.
"""

#: The reviewer sometimes bolds the whole label line (``**Priority: Should fix**``)
#: and the label with the colon (``**What I found:** ...``). Both must parse.
BOLD_REVIEW = """\
## Findings

**Priority: Should fix**
**Confidence: 5**

**What I found:** The importer enumeration omits a real fourth importer.
**Why it matters:** Literal compliance produces a non-building PR.
**Trigger and effect:** Any implementation that trusts the list.
**Where:** `services/player-api/src/handlers/__tests__/ws-message.test.ts:19,781`
**Suggested fix:** Add the missing importer to the list and the deliverables.

**Priority: Could fix**
**Confidence: 3**

**What I found:** The annotations contradict the import strategy.
**Why it matters:** Minor diff noise.
**Trigger and effect:** The implementer picks either strategy.
**Where:** docs/task-prompts/03-E4.1-prompt.md, Deliverables.
**Suggested fix:** Pick one strategy and align the annotations.

## Verdict

Request changes — one should-fix item remains.
"""


def test_parse_two_findings() -> None:
    parsed, problems = findings.parse_review_findings(REVIEW)
    assert problems == []
    assert [f.priority for f in parsed] == ["should-fix", "could-fix"]
    assert [f.confidence for f in parsed] == [4, 3]
    assert parsed[0].where == "packages/shared/src/list.ts:42"


def test_to_manifest_shape() -> None:
    parsed, _ = findings.parse_review_findings(REVIEW)
    manifest = findings.to_manifest(parsed)
    assert [f["id"] for f in manifest["findings"]] == ["F1", "F2"]
    assert manifest["findings"][0]["title"] == "The loop stops one element early"
    assert set(manifest["findings"][0]) == {
        "id",
        "priority",
        "confidence",
        "title",
        "whatFound",
        "whyItMatters",
        "triggerAndEffect",
        "where",
        "suggestedFix",
    }


def test_approve_has_no_findings() -> None:
    parsed, problems = findings.parse_review_findings(APPROVED)
    assert parsed == []
    assert problems == []


FENCED_REVIEW = """\
## Findings

```text
Priority: Should fix
Confidence: 4
What I found: The closing fence must not be absorbed.
Why it matters: The value would carry stray markdown.
Trigger and effect: Any fenced finding block.
Where: packages/shared/src/list.ts:42
Suggested fix: Iterate with a `<`-bound to the array length.
```

## Verdict

Request changes
"""


def test_a_closing_fence_is_not_absorbed_into_the_last_field() -> None:
    parsed, problems = findings.parse_review_findings(FENCED_REVIEW)
    assert problems == []
    assert parsed[0].suggested_fix == "Iterate with a `<`-bound to the array length."
    assert "```" not in parsed[0].suggested_fix


def test_partition_findings_splits_on_blocking_priority() -> None:
    parsed, _ = findings.parse_review_findings(REVIEW)
    blocking, non_blocking = findings.partition_findings(parsed)
    assert [f.priority for f in blocking] == ["should-fix"]
    assert [f.priority for f in non_blocking] == ["could-fix"]


def test_render_could_fix_block_carries_every_finding_in_one_stage() -> None:
    parsed, _ = findings.parse_review_findings(REVIEW)
    _, non_blocking = findings.partition_findings(parsed)
    block = findings.render_could_fix_block(non_blocking)
    assert block.startswith("## Non-blocking (could-fix) review finding to address together")
    assert "The review raised 1 non-blocking finding." in block
    assert "Suggested fix: Extract one helper." in block
    assert block.count("```text") == 1


def test_bold_label_lines_still_parse() -> None:
    """Regression: a reviewer that bolds the whole label line must not break parsing."""
    parsed, problems = findings.parse_review_findings(BOLD_REVIEW)
    assert problems == []
    assert [f.priority for f in parsed] == ["should-fix", "could-fix"]
    assert [f.confidence for f in parsed] == [5, 3]
    assert parsed[0].what_found == "The importer enumeration omits a real fourth importer."
    assert parsed[0].where == "`services/player-api/src/handlers/__tests__/ws-message.test.ts:19,781`"
    assert findings.findings_summary(parsed) == "2 findings (1 should-fix, 1 could-fix)"


def test_unknown_priority_fails_closed() -> None:
    text = "Priority: Critical\nConfidence: 5\nWhat I found: x\n"
    parsed, problems = findings.parse_review_findings(text)
    assert len(parsed) == 1
    assert any("unknown priority" in p for p in problems)


def test_invalid_confidence_fails_closed() -> None:
    text = (
        "Priority: Must fix\nConfidence: 9\nWhat I found: x\nWhy it matters: y\n"
        "Trigger and effect: z\nWhere: a:1\nSuggested fix: b\n"
    )
    _, problems = findings.parse_review_findings(text)
    assert any("invalid confidence" in p for p in problems)


def test_missing_field_fails_closed() -> None:
    text = "Priority: Must fix\nConfidence: 3\nWhat I found: x\n"
    _, problems = findings.parse_review_findings(text)
    assert any("missing whyItMatters" in p for p in problems)


def test_findings_summary_counts_by_priority() -> None:
    parsed, problems = findings.parse_review_findings(REVIEW)
    assert problems == []
    assert findings.findings_summary(parsed) == "2 findings (1 should-fix, 1 could-fix)"


def test_findings_summary_uses_the_singular() -> None:
    parsed, _ = findings.parse_review_findings(
        "Priority: Must fix\nConfidence: 5\nWhat I found: x\nWhy it matters: y\n"
        "Trigger and effect: z\nWhere: a:1\nSuggested fix: b\n"
    )
    assert findings.findings_summary(parsed) == "1 finding (1 must-fix)"


def test_findings_summary_without_findings() -> None:
    assert findings.findings_summary([]) == "no machine-readable findings"


def test_findings_summary_names_an_unparseable_priority() -> None:
    parsed, _ = findings.parse_review_findings(
        "Priority: Critical\nConfidence: 3\nWhat I found: x\nWhy it matters: y\n"
        "Trigger and effect: z\nWhere: a:1\nSuggested fix: b\n"
    )
    assert findings.findings_summary(parsed) == "1 finding (1 unparseable priority)"


def test_finding_title_is_derived_from_what_i_found() -> None:
    parsed, _ = findings.parse_review_findings(REVIEW)
    assert findings.finding_title(parsed[0]) == "The loop stops one element early"


def test_render_finding_block_reemits_the_reviewer_format() -> None:
    parsed, _ = findings.parse_review_findings(REVIEW)
    block = findings.render_finding_block(parsed[0], index=1, total=2)
    assert block.startswith("## Review finding 1 of 2 to address")
    assert "Fix exactly this finding" in block
    assert "Priority: should-fix" in block
    assert "Confidence: 4" in block
    assert "What I found: The loop stops one element early." in block
    assert "Where: packages/shared/src/list.ts:42" in block
    assert "Suggested fix: Iterate with a `<`-bound to the array length." in block
