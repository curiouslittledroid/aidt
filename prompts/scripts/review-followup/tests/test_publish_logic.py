"""Unit tests for the pure publisher logic: manifest validation and CLI parsing.

Run with: uv run pytest prompts/scripts/review-followup/tests
"""

from __future__ import annotations

import json

import pytest

from logic import PublishArgs, parse_manifest, parse_publish_args, validate_manifest
from proc import UsageError


def finding(**overrides: object) -> dict:
    values: dict[str, object] = {
        "id": "F1",
        "priority": "must-fix",
        "confidence": 4,
        "title": "Short imperative title",
        "whatFound": "The defect.",
        "whyItMatters": "The impact.",
        "triggerAndEffect": "When X, Y happens.",
        "where": "path/to/file.ts:10-20",
        "suggestedFix": "Do the right thing.",
    }
    values.update(overrides)
    return values


# ── validateManifest ──────────────────────────────────────────────────────


def test_accepts_a_well_formed_manifest() -> None:
    manifest = validate_manifest(
        {"findings": [finding(), finding(id="F2", priority="could-fix")]}
    )
    assert len(manifest.findings) == 2
    assert manifest.findings[1].priority == "could-fix"


def test_trims_string_fields() -> None:
    manifest = validate_manifest({"findings": [finding(title="  spaced  ")]})
    assert manifest.findings[0].title == "spaced"


def test_rejects_a_non_object_manifest() -> None:
    with pytest.raises(UsageError, match="must be a JSON object"):
        validate_manifest([])


def test_rejects_unexpected_top_level_keys() -> None:
    with pytest.raises(UsageError, match="unexpected key"):
        validate_manifest({"findings": [finding()], "extra": True})


def test_rejects_an_empty_findings_array() -> None:
    with pytest.raises(UsageError, match="non-empty"):
        validate_manifest({"findings": []})


def test_rejects_an_unexpected_finding_key() -> None:
    with pytest.raises(UsageError, match="unexpected key"):
        validate_manifest({"findings": [finding(oops=1)]})


def test_rejects_a_missing_finding_key() -> None:
    without_title = finding()
    del without_title["title"]
    with pytest.raises(UsageError, match="missing required key"):
        validate_manifest({"findings": [without_title]})


def test_rejects_a_malformed_finding_id() -> None:
    with pytest.raises(UsageError, match="F1, F2"):
        validate_manifest({"findings": [finding(id="finding-1")]})


def test_rejects_an_unknown_priority() -> None:
    with pytest.raises(UsageError, match="priority must be one of"):
        validate_manifest({"findings": [finding(priority="urgent")]})


def test_rejects_a_non_integer_confidence() -> None:
    with pytest.raises(UsageError, match="integer from 0 to 5"):
        validate_manifest({"findings": [finding(confidence=2.5)]})


def test_rejects_a_boolean_confidence() -> None:
    with pytest.raises(UsageError, match="integer from 0 to 5"):
        validate_manifest({"findings": [finding(confidence=True)]})


def test_rejects_an_out_of_range_confidence() -> None:
    with pytest.raises(UsageError, match="integer from 0 to 5"):
        validate_manifest({"findings": [finding(confidence=6)]})


def test_rejects_an_empty_string_field() -> None:
    with pytest.raises(UsageError, match="non-empty string"):
        validate_manifest({"findings": [finding(whatFound="   ")]})


def test_requires_sequential_finding_ids_in_review_order() -> None:
    with pytest.raises(UsageError, match="sequential"):
        validate_manifest({"findings": [finding(id="F2"), finding(id="F3")]})


# ── parseManifest ─────────────────────────────────────────────────────────


def test_parses_valid_json() -> None:
    assert len(parse_manifest(json.dumps({"findings": [finding()]})).findings) == 1


def test_reports_invalid_json() -> None:
    with pytest.raises(UsageError, match="not valid JSON"):
        parse_manifest("{ not json")


# ── parsePublishArgs ──────────────────────────────────────────────────────


def test_parses_a_full_invocation() -> None:
    assert parse_publish_args(
        ["--pr", "174", "--input", "manifest.json", "--repo", "o/r", "--dry-run"]
    ) == PublishArgs(pr="174", input="manifest.json", repo="o/r", dry_run=True)


def test_omits_pr_to_resolve_the_current_branch() -> None:
    assert parse_publish_args(["--input", "manifest.json"]) == PublishArgs(
        input="manifest.json"
    )


def test_tolerates_a_leading_double_dash() -> None:
    assert parse_publish_args(["--", "--input", "manifest.json"]).input == "manifest.json"


def test_rejects_a_missing_input() -> None:
    with pytest.raises(UsageError, match="Usage:"):
        parse_publish_args(["--pr", "174"])


def test_rejects_a_flag_missing_its_value() -> None:
    with pytest.raises(UsageError, match="requires a value"):
        parse_publish_args(["--input"])


def test_rejects_an_unknown_argument() -> None:
    with pytest.raises(UsageError, match="Unknown argument"):
        parse_publish_args(["--input", "m.json", "--yes"])
