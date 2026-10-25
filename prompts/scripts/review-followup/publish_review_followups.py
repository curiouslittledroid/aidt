#!/usr/bin/env python3
"""Publish a structured code-review finding manifest as GitHub follow-up tasks.

Sibling of ``review_followup.py``; both share :mod:`constants`, :mod:`proc`,
:mod:`gh`, and :mod:`logic`. All GitHub operations intentionally go through the
GitHub CLI. The script is idempotent by stable PR/finding markers and stops on
ambiguous matches rather than guessing which issue to modify.

Run with any Python 3.9+, no install step (``AIDW_SCRIPTS_DIR`` is the toolkit's
absolute ``prompts/scripts`` directory, set by ``aidw`` for every stage):
  python3 "${AIDW_SCRIPTS_DIR:-<toolkit>/prompts/scripts}/review-followup/publish_review_followups.py" \\
    --pr <number-or-url> --input <manifest.json> --dry-run
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from constants import (
    DECISION_APPROVE_FIX,
    LABEL_DECISION_PENDING,
    LABEL_DEFINITIONS,
    LABEL_REVIEW_FOLLOW_UP,
    PRIORITY_LABELS,
    PUBLISHER_LABELS,
    child_marker,
    parent_marker,
    summary_marker,
)
from gh import (
    GhIssue,
    PrInfo,
    assert_gh_authenticated,
    create_issue,
    create_label,
    create_pr_comment,
    edit_issue,
    issue_view,
    label_list,
    labels_of,
    list_comments,
    list_issues,
    resolve_pr,
    resolve_repo,
    update_issue_comment,
)
from logic import Finding, Manifest, parse_manifest, parse_publish_args
from proc import UsageError


@dataclass
class ChildRecord:
    finding: Finding
    issue: GhIssue
    action: str  # "created" | "updated" | "preserved-open" | "preserved-closed"


# ── Issue bodies ──────────────────────────────────────────────────────────


def parent_body(pr: PrInfo, rows: str | None = None) -> str:
    return f"""{parent_marker(pr.url)}

## Source

Review findings from [PR #{pr.number}]({pr.url}).

## Purpose

This issue groups the actionable findings from the completed review. Each finding is a child issue and must receive an explicit human decision before implementation.

## Human decision gate

- `Decision: approve-fix` — an agent may implement the child task.
- `Decision: accepted-risk` — do not implement; record the rationale and close the child issue when appropriate.
- `Decision: not-a-bug` — the finding is rejected with evidence; close the child issue.

Agents must not implement a child issue while it has the `decision-pending` label. The human decision must be recorded in an issue comment and reflected by removing `decision-pending` and adding the appropriate workflow label or closing the issue.

## Child issues

{rows or "The child issue list is added after all children are created."}
"""


def child_body(pr: PrInfo, parent: GhIssue, finding: Finding) -> str:
    priority_text = {
        "must-fix": "Must fix",
        "should-fix": "Should fix",
    }.get(finding.priority, "Could fix")
    return f"""{child_marker(pr.url, finding.id)}

## Source

Found during review of [PR #{pr.number}]({pr.url}).
Parent task: [Review follow-ups for PR #{pr.number}]({parent.url})

## Priority

{priority_text}

**Review confidence:** {finding.confidence}

## What I found

{finding.whatFound}

## Why it matters

{finding.whyItMatters}

## Trigger and effect

{finding.triggerAndEffect}

## Where

{finding.where}

## Suggested fix

{finding.suggestedFix}

## Acceptance criteria

- [ ] The defect described above is corrected without expanding scope.
- [ ] A focused regression test covers the trigger and expected result.
- [ ] Relevant repository checks pass and their real results are reported.
- [ ] Any remaining limitation is documented in the issue before closure.

## Agent workflow

Do not start implementation while this issue has `decision-pending`.
A human must comment one of:

- `{DECISION_APPROVE_FIX}`
- `Decision: accepted-risk` plus rationale
- `Decision: not-a-bug` plus evidence

For approved work, comment `Status: in progress`, implement only this issue, run the acceptance checks, and report the files changed and commands/results before requesting review.
"""


def child_row(record: ChildRecord) -> str:
    finding, issue = record.finding, record.issue
    pending = LABEL_DECISION_PENDING in labels_of(issue)
    decision = "Pending" if pending else "Existing decision preserved"
    if issue.state == "CLOSED":
        status = "Preserved closed"
    elif pending:
        status = "Awaiting human decision"
    else:
        status = "Existing decision preserved"
    return (
        f"| {finding.id} | [#{issue.number} — {issue.title}]({issue.url}) | "
        f"{finding.priority} | {finding.confidence} | {decision} | {status} |"
    )


def summary_body(pr: PrInfo, parent: GhIssue, records: list[ChildRecord]) -> str:
    rows = "\n".join(child_row(record) for record in records)
    return f"""{summary_marker(pr.url)}

## Review follow-up tasks

The completed review produced the following task issues. Each issue is a child of [#{parent.number}]({parent.url}) and starts with `decision-pending` unless it was a previously decided closed child preserved during reconciliation.

| Finding | Task | Priority | Confidence | Human decision | Status |
|---|---|---:|---:|---|---|
{rows}

### Decision protocol

A human should comment on each open pending child issue with `{DECISION_APPROVE_FIX}`, `Decision: accepted-risk`, or `Decision: not-a-bug`. Agents may implement only issues explicitly approved with `{DECISION_APPROVE_FIX}`.
"""


# ── Validation ────────────────────────────────────────────────────────────


def exact_count(text: str, value: str) -> int:
    """Count non-overlapping occurrences of an exact string."""
    if not value:
        return 0
    count = 0
    offset = 0
    while True:
        index = text.find(value, offset)
        if index < 0:
            return count
        count += 1
        offset = index + len(value)


def validate_parent(issue: GhIssue, pr: PrInfo, must_be_open: bool) -> None:
    marker = parent_marker(pr.url)
    if exact_count(issue.body, marker) != 1:
        raise UsageError(f"Parent #{issue.number} has an invalid or duplicated parent marker.")
    if pr.url not in issue.body:
        raise UsageError(f"Parent #{issue.number} does not link to {pr.url}.")
    if LABEL_REVIEW_FOLLOW_UP not in labels_of(issue):
        raise UsageError(f"Parent #{issue.number} is missing {LABEL_REVIEW_FOLLOW_UP}.")
    if LABEL_DECISION_PENDING in labels_of(issue):
        raise UsageError(f"Parent #{issue.number} must not have {LABEL_DECISION_PENDING}.")
    if must_be_open and issue.state != "OPEN":
        raise UsageError(f"New parent #{issue.number} is not open.")


CHILD_SECTIONS = (
    "## Source",
    "## Priority",
    "## What I found",
    "## Why it matters",
    "## Trigger and effect",
    "## Where",
    "## Suggested fix",
    "## Acceptance criteria",
    "## Agent workflow",
)


def validate_child(issue: GhIssue, pr: PrInfo, parent: GhIssue, finding: Finding) -> None:
    marker = child_marker(pr.url, finding.id)
    if exact_count(issue.body, marker) != 1:
        raise UsageError(
            f"Child #{issue.number} has an invalid or duplicated {finding.id} marker."
        )
    if pr.url not in issue.body or parent.url not in issue.body:
        raise UsageError(f"Child #{issue.number} is missing the PR or parent link.")
    for section in CHILD_SECTIONS:
        if section not in issue.body:
            raise UsageError(f"Child #{issue.number} is missing {section}.")
    if issue.state != "OPEN":
        raise UsageError(f"New or updated child #{issue.number} is not open.")
    labels = labels_of(issue)
    priority_labels = [label for label in PRIORITY_LABELS if label in labels]
    if (
        LABEL_REVIEW_FOLLOW_UP not in labels
        or LABEL_DECISION_PENDING not in labels
        or len(priority_labels) != 1
        or priority_labels[0] != finding.priority
    ):
        raise UsageError(
            f"Child #{issue.number} has incorrect labels: {', '.join(sorted(labels))}"
        )
    if issue.parent != parent.number:
        raise UsageError(
            f"Child #{issue.number} is not a native sub-issue of parent #{parent.number}."
        )


# ── Reconciliation helpers ────────────────────────────────────────────────


def ensure_labels(repo: str, dry_run: bool) -> None:
    existing = {str(label.get("name")) for label in label_list(repo)}
    for name in PUBLISHER_LABELS:
        if name in existing:
            continue
        if dry_run:
            print(f"[dry-run] would create missing label: {name}")
            continue
        definition = LABEL_DEFINITIONS.get(name)
        if not definition:
            raise UsageError(f"No label definition for {name}.")
        create_label(repo, name, definition["color"], definition["description"])
        verified = {str(label.get("name")) for label in label_list(repo)}
        if name not in verified:
            raise UsageError(f"Label {name} was created but could not be verified.")
        existing.add(name)


def find_marked_issues(repo: str, marker: str) -> list[dict]:
    """Find non-PR issues whose body contains an exact marker."""
    found = []
    for issue in list_issues(repo):
        if issue.get("pull_request") or not isinstance(issue.get("body"), str):
            continue
        if marker not in issue["body"]:
            continue
        found.append(
            {
                "number": int(issue["number"]),
                "title": str(issue["title"]),
                "state": str(issue["state"]),
                "url": str(issue["html_url"]),
                "body": str(issue["body"]),
            }
        )
    return found


def legacy_child_number(parent_body_text: str, finding: Finding) -> int | None:
    """Recover a child created before markers were introduced, via the parent table."""
    pattern = re.compile(rf"^\|\s*{finding.id}\s*\|\s*\[#(\d+)\s+—\s+(.+?)\]\([^)]*\)")
    matches: list[int] = []
    for line in parent_body_text.split("\n"):
        match = pattern.match(line)
        if match and match.group(2) == finding.title:
            matches.append(int(match.group(1)))
    if len(matches) > 1:
        raise UsageError(
            f"Parent table has multiple legacy matches for {finding.id}: "
            f"{', '.join(str(m) for m in matches)}"
        )
    return matches[0] if matches else None


def create_parent(repo: str, pr: PrInfo) -> GhIssue:
    issue = create_issue(
        repo,
        title=f"Review follow-ups: PR #{pr.number} — {pr.title}",
        body=parent_body(pr),
        labels=[LABEL_REVIEW_FOLLOW_UP],
    )
    validate_parent(issue, pr, True)
    return issue


def create_child(repo: str, pr: PrInfo, parent: GhIssue, finding: Finding) -> GhIssue:
    issue = create_issue(
        repo,
        title=finding.title,
        body=child_body(pr, parent, finding),
        labels=[LABEL_REVIEW_FOLLOW_UP, finding.priority, LABEL_DECISION_PENDING],
        parent_number=parent.number,
    )
    validate_child(issue, pr, parent, finding)
    return issue


def reconcile_pending_child(
    repo: str, pr: PrInfo, parent: GhIssue, finding: Finding, issue: GhIssue
) -> GhIssue:
    remove_labels = [
        label
        for label in PRIORITY_LABELS
        if label != finding.priority and label in labels_of(issue)
    ]
    edit_issue(
        repo,
        issue.number,
        title=finding.title,
        body=child_body(pr, parent, finding),
        add_labels=[LABEL_REVIEW_FOLLOW_UP, finding.priority, LABEL_DECISION_PENDING],
        remove_labels=remove_labels,
    )
    updated = issue_view(repo, issue.number)
    validate_child(updated, pr, parent, finding)
    return updated


def reconcile_parent_labels(repo: str, parent: GhIssue) -> GhIssue:
    labels = labels_of(parent)
    add_labels = None if LABEL_REVIEW_FOLLOW_UP in labels else [LABEL_REVIEW_FOLLOW_UP]
    remove_labels = (
        [LABEL_DECISION_PENDING] if LABEL_DECISION_PENDING in labels else None
    )
    if not add_labels and not remove_labels:
        return parent
    edit_issue(repo, parent.number, add_labels=add_labels, remove_labels=remove_labels)
    return issue_view(repo, parent.number)


def update_parent_table(
    repo: str, parent: GhIssue, pr: PrInfo, records: list[ChildRecord]
) -> GhIssue:
    rows = "\n".join(child_row(record) for record in records)
    updated_body = parent_body(
        pr,
        f"| Finding | Issue | Priority | Confidence | Decision | Status |\n"
        f"|---|---|---:|---:|---|---|\n{rows}",
    )
    edit_issue(repo, parent.number, body=updated_body)
    updated = issue_view(repo, parent.number)
    validate_parent(updated, pr, False)
    for record in records:
        if exact_count(updated.body, f"| {record.finding.id} |") != 1:
            raise UsageError(
                f"Parent #{parent.number} does not contain exactly one row for "
                f"{record.finding.id}."
            )
    return updated


def update_summary(
    repo: str, pr: PrInfo, parent: GhIssue, records: list[ChildRecord]
) -> None:
    body = summary_body(pr, parent, records)
    marker = summary_marker(pr.url)
    matches = [
        comment
        for comment in list_comments(repo, pr.number)
        if marker in str(comment.get("body") or "")
    ]
    if len(matches) > 1:
        raise UsageError(
            f"Found multiple summary comments for {pr.url}: "
            f"{', '.join(str(c.get('id')) for c in matches)}"
        )

    if not matches:
        create_pr_comment(repo, pr.number, body)
    else:
        update_issue_comment(repo, int(matches[0]["id"]), body)

    verified = [
        comment
        for comment in list_comments(repo, pr.number)
        if marker in str(comment.get("body") or "")
    ]
    if len(verified) != 1:
        raise UsageError(
            f"Expected exactly one summary comment after publishing, found {len(verified)}."
        )
    final_body = str(verified[0].get("body") or "")
    for record in records:
        if exact_count(final_body, f"| {record.finding.id} |") != 1:
            raise UsageError(f"Summary is missing exactly one row for {record.finding.id}.")
        if exact_count(final_body, record.issue.url) != 1:
            raise UsageError(f"Summary does not contain exactly one link for {record.issue.url}.")
    if parent.url not in final_body or pr.url not in final_body:
        raise UsageError("Summary is missing the parent or PR link.")

    print(f"Summary comment: {verified[0].get('html_url')}")


# ── Commands ──────────────────────────────────────────────────────────────


def dry_run(repo: str, pr: PrInfo, manifest: Manifest) -> None:
    ensure_labels(repo, True)

    parents = find_marked_issues(repo, parent_marker(pr.url))
    if len(parents) > 1:
        raise UsageError(
            f"Found multiple parent issues for {pr.url}: "
            f"{', '.join(str(issue['number']) for issue in parents)}"
        )
    parent_label = "create" if not parents else f"reuse #{parents[0]['number']}"
    print(f"[dry-run] parent: {parent_label}")

    issues = list_issues(repo)
    for finding in manifest.findings:
        marker = child_marker(pr.url, finding.id)
        matches = [
            issue
            for issue in issues
            if not issue.get("pull_request")
            and isinstance(issue.get("body"), str)
            and marker in issue["body"]
        ]
        if len(matches) > 1:
            raise UsageError(
                f"Found multiple child issues for {finding.id}: "
                f"{', '.join(str(issue['number']) for issue in matches)}"
            )
        if not matches:
            print(f'[dry-run] {finding.id}: create child "{finding.title}"')
        else:
            issue = matches[0]
            verb = "preserve closed" if issue["state"] == "CLOSED" else "reconcile existing"
            print(f"[dry-run] {finding.id}: {verb} #{issue['number']}")
    print(f"[dry-run] summary: {'create after children' if not parents else 'create or update'}")


def publish(repo: str, pr: PrInfo, manifest: Manifest) -> None:
    ensure_labels(repo, False)

    parents = find_marked_issues(repo, parent_marker(pr.url))
    if len(parents) > 1:
        raise UsageError(
            f"Found multiple parent issues for {pr.url}: "
            f"{', '.join(str(issue['number']) for issue in parents)}"
        )

    parent = create_parent(repo, pr) if not parents else issue_view(repo, int(parents[0]["number"]))
    parent = reconcile_parent_labels(repo, parent)
    validate_parent(parent, pr, False)

    # A single listing is enough: each finding has a unique marker, so children
    # created earlier in this loop cannot match a later finding.
    existing_issues = list_issues(repo)

    records: list[ChildRecord] = []
    for finding in manifest.findings:
        marker = child_marker(pr.url, finding.id)
        marker_matches = [
            issue
            for issue in existing_issues
            if not issue.get("pull_request")
            and isinstance(issue.get("body"), str)
            and marker in issue["body"]
        ]
        if len(marker_matches) > 1:
            raise UsageError(
                f"Found multiple child issues for {finding.id}: "
                f"{', '.join(str(issue['number']) for issue in marker_matches)}"
            )

        if len(marker_matches) == 1:
            issue = issue_view(repo, int(marker_matches[0]["number"]))
            if issue.parent != parent.number:
                raise UsageError(
                    f"Existing child #{issue.number} is not a native sub-issue of "
                    f"parent #{parent.number}."
                )
            issue, action = reconcile_child(repo, pr, parent, finding, issue)
        else:
            legacy_number = legacy_child_number(parent.body, finding)
            if legacy_number is not None:
                issue = issue_view(repo, legacy_number)
                if issue.parent != parent.number:
                    raise UsageError(
                        f"Legacy child #{issue.number} is not a native sub-issue of "
                        f"parent #{parent.number}."
                    )
                issue, action = reconcile_child(repo, pr, parent, finding, issue)
            else:
                issue = create_child(repo, pr, parent, finding)
                action = "created"

        records.append(ChildRecord(finding=finding, issue=issue, action=action))
        print(f"{finding.id}: {action} #{issue.number} {issue.url}")

    parent = update_parent_table(repo, parent, pr, records)
    final_parent = issue_view(repo, parent.number)
    for record in records:
        if record.issue.number not in final_parent.sub_issue_numbers:
            raise UsageError(
                f"Parent #{parent.number} is missing native child #{record.issue.number}."
            )

    update_summary(repo, pr, final_parent, records)
    print(f"Parent issue: {final_parent.url}")


def reconcile_child(
    repo: str, pr: PrInfo, parent: GhIssue, finding: Finding, issue: GhIssue
) -> tuple[GhIssue, str]:
    """Decide what to do with an already-existing child."""
    if issue.state == "CLOSED":
        return issue, "preserved-closed"
    if LABEL_DECISION_PENDING in labels_of(issue):
        return reconcile_pending_child(repo, pr, parent, finding, issue), "updated"
    return issue, "preserved-open"


# ── Entry point ───────────────────────────────────────────────────────────


def read_manifest(path: str) -> Manifest:
    content = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return parse_manifest(content)


def main(argv: list[str]) -> int:
    options = parse_publish_args(argv)

    assert_gh_authenticated()
    repo = resolve_repo(options.repo)
    pr = resolve_pr(options.pr)
    if pr.state.upper() != "OPEN":
        raise UsageError(f"PR #{pr.number} is {pr.state}; only open PRs are supported.")
    if pr.baseRefName != "main":
        raise UsageError(f"PR #{pr.number} targets {pr.baseRefName}, not main.")
    manifest = read_manifest(options.input)

    print(f"Repository: {repo}")
    print(f"PR: #{pr.number} {pr.url}")
    print(f"Findings: {len(manifest.findings)}")

    if options.dry_run:
        dry_run(repo, pr, manifest)
    else:
        publish(repo, pr, manifest)
    return 0


def cli(argv: list[str] | None = None) -> int:
    try:
        return main(sys.argv[1:] if argv is None else argv)
    except UsageError as error:
        if error.exit_code == 0:
            sys.stdout.write(f"{error}\n")
        else:
            sys.stderr.write(f"error: {error}\n")
        return error.exit_code
    except Exception as error:  # noqa: BLE001 - mirrors the TS top-level handler
        sys.stderr.write(f"error: {error}\n")
        return 2


if __name__ == "__main__":
    sys.exit(cli())
