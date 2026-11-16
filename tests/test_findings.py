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


# ── Later-round per-finding verdicts (M4) ───────────────────────────────────────────
#
# The delta brief requires a `Verdict on this finding:` line per previous finding from
# round 2 on. Those blocks are verdicts on *earlier* findings, so a `resolved` one must not
# count as blocking — otherwise an approving review that resolved everything reads as
# "Approve with N blocking findings" and M2 blocks the run. Observed on PR #282 / 04-A1.3
# (2026-11-16): the review said "Approve — prior findings resolved, no new defects" and the
# run was still blocked with `findings=2/2`.

#: The shape that blocked the run: two previous findings, both resolved, both still
#: carrying their original blocking priority.
RESOLVED_ROUND = """\
## Previous-review findings — per-finding verdicts

Priority: Must fix
Confidence: 5
What I found: The Done when required a live 201 without A1.4's endpoints.
Why it matters: The implementer would chase an impossible green.
Trigger and effect: Every run of this task.
Where: Previous prompt Done when.
Suggested fix: Condition it on A1.4.
Verdict on this finding: resolved. The current prompt conditions the `201` on A1.4.

Priority: Should fix
Confidence: 5
What I found: Design 11 §3 was cited as a REST placement rule.
Why it matters: The authority chain did not match the source text.
Trigger and effect: A reader trusting the citation.
Where: Previous prompt header citation block.
Suggested fix: Correct the citation.
Verdict on this finding: resolved. The header now attributes placement to A1.2.

## New findings

No new findings.

Verdict: Approve — prior findings resolved, no new defects.
"""


def test_a_resolved_finding_keeps_its_priority_but_stops_blocking() -> None:
    """The block still parses (the record keeps it); only its blocking status changes."""
    parsed, problems = findings.parse_review_findings(RESOLVED_ROUND)

    assert problems == []
    assert [f.priority for f in parsed] == ["must-fix", "should-fix"]
    assert [f.resolution for f in parsed] == [
        findings.RESOLVED,
        findings.RESOLVED,
    ]
    blocking, non_blocking = findings.partition_findings(parsed)
    # Both are resolved, so neither needs a fix stage, and neither is fed to the
    # could-fix batch (which would ask an agent to fix something already closed).
    assert blocking == []
    assert non_blocking == []
    # The record keeps them: the manifest still publishes all findings.
    assert len(findings.to_manifest(parsed)["findings"]) == 2


def test_the_verdict_does_not_bleed_into_the_preceding_field() -> None:
    """`Verdict on this finding` is its own field, not appended to `Where`."""
    parsed, _ = findings.parse_review_findings(RESOLVED_ROUND)

    assert parsed[0].where == "Previous prompt Done when."
    assert "resolved" not in parsed[0].where


def test_an_unresolved_verdict_still_blocks() -> None:
    """`not resolved` and `newly contradicted` are live findings."""
    for verdict, expected in (
        ("not resolved. The prompt still owes A1.4.", findings.NOT_RESOLVED),
        ("newly contradicted. The fix broke the trap.", findings.NEWLY_CONTRADICTED),
    ):
        text = RESOLVED_ROUND.replace(
            "Verdict on this finding: resolved. The current prompt conditions the `201` on A1.4.",
            f"Verdict on this finding: {verdict}",
        )
        parsed, problems = findings.parse_review_findings(text)

        assert problems == [], verdict
        assert parsed[0].resolution == expected, verdict
        blocking, _ = findings.partition_findings(parsed)
        assert [f.what_found for f in blocking] == [
            "The Done when required a live 201 without A1.4's endpoints."
        ], verdict


def test_an_absent_verdict_still_blocks() -> None:
    """Round 1 has no verdict line; nothing about that changes."""
    parsed, problems = findings.parse_review_findings(REVIEW)

    assert problems == []
    assert [f.resolution for f in parsed] == ["", ""]
    blocking, _ = findings.partition_findings(parsed)
    assert len(blocking) == 1  # the should-fix one


def test_an_unrecognised_verdict_fails_closed_as_blocking() -> None:
    """A wording the parser does not know keeps the finding blocking, without a problem."""
    text = RESOLVED_ROUND.replace(
        "Verdict on this finding: resolved. The current prompt conditions the `201` on A1.4.",
        "Verdict on this finding: partially addressed, see above.",
    )
    parsed, problems = findings.parse_review_findings(text)

    assert problems == []
    assert parsed[0].resolution == ""
    blocking, non_blocking = findings.partition_findings(parsed)
    # The unrecognised one blocks; the other is resolved, so it needs no stage.
    assert [f.what_found for f in blocking] == [
        "The Done when required a live 201 without A1.4's endpoints."
    ]
    assert non_blocking == []


def test_a_resolved_could_fix_is_still_non_blocking() -> None:
    """Priority decides non-blocking; the verdict only ever clears a blocking one."""
    text = REVIEW.replace(
        "Suggested fix: Extract one helper.",
        "Suggested fix: Extract one helper.\nVerdict on this finding: not resolved.",
    )
    parsed, problems = findings.parse_review_findings(text)

    assert problems == []
    blocking, non_blocking = findings.partition_findings(parsed)
    assert len(blocking) == 1
    assert [f.priority for f in non_blocking] == ["could-fix"]


def test_re_render_keeps_the_verdict_so_a_shrink_cannot_clear_it() -> None:
    """`render_previous_review` shrinks the previous review; the verdict must survive it."""
    parsed, _ = findings.parse_review_findings(RESOLVED_ROUND)

    rendered = findings._finding_text_block(parsed[0])

    assert "Verdict on this finding: resolved" in rendered
    reparsed, _ = findings.parse_review_findings(rendered)
    assert reparsed[0].resolution == findings.RESOLVED
