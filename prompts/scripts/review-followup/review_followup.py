#!/usr/bin/env python3
"""review-followup — deterministic GitHub bookkeeping for the workflow in
``aidt/prompts/fix-next-review-followup.md``.

Subcommands:
  select   Read-only. PR -> parent issue -> first available child, as JSON.
  start    Post the exact ``Status: in progress`` comment (idempotent).
  fixed    Post the exact ``Status: fixed`` comment and close the issue.
  verify   Assert closed, marked fixed, and labels intact.
  approve  Apply the human approval to every open child (idempotent).

What this script does NOT do: decide whether the code work is done. ``fixed`` is
a separate, explicit call that the agent makes only after its own acceptance
checks pass. Nothing here is ever chained automatically.

Run with any Python 3.9+, no install step:
  python3 aidt/prompts/scripts/review-followup/review_followup.py --help

Exit codes: 0 ok, 1 verification failed, 2 usage/GitHub error,
            3 no available child, 4 workflow conflict.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from constants import (
    DECISION_APPROVE_FIX,
    EXIT_CONFLICT,
    EXIT_ERROR,
    EXIT_NONE_AVAILABLE,
    EXIT_OK,
    EXIT_VERIFY_FAILED,
    LABEL_APPROVE_FIX,
    LABEL_DEFINITIONS,
    LABEL_REVIEW_FOLLOW_UP,
    STATUS_FIXED,
    STATUS_IN_PROGRESS,
    parent_marker,
)
from gh import (
    ParentIssue,
    PrInfo,
    add_comment,
    assert_gh_authenticated,
    close_issue,
    create_label,
    edit_issue,
    find_parent_issues,
    get_issue,
    label_list,
    list_native_children,
    resolve_pr,
    resolve_repo,
)
from logic import (
    ApprovalPlan,
    ChildIssue,
    ParsedArgs,
    Selection,
    approval_plan,
    can_override_selection,
    closing_body_repeats_status,
    is_approved,
    parse_args,
    priority_label,
    select_first_available,
    status_flags,
)
from proc import CommandError, UsageError, git_branch

# ── Context ───────────────────────────────────────────────────────────────


@dataclass
class Context:
    repo: str
    pr: PrInfo
    branch: str
    branch_matches: bool


def resolve_context(pr_ref: str) -> Context:
    assert_gh_authenticated()
    repo = resolve_repo()
    pr = resolve_pr(pr_ref)
    branch = git_branch()
    return Context(repo=repo, pr=pr, branch=branch, branch_matches=branch == pr.headRefName)


def assert_processable(context: Context, allow_branch_mismatch: bool) -> None:
    """Guard the workflow's preconditions.

    Every stop here is deliberate: the prompt requires asking the user rather
    than guessing.
    """
    if context.pr.state.upper() != "OPEN":
        raise UsageError(
            f"PR #{context.pr.number} is {context.pr.state}, not OPEN. "
            "Stop and ask the user before processing a closed PR."
        )
    if context.pr.baseRefName != "main":
        raise UsageError(
            f'PR #{context.pr.number} targets "{context.pr.baseRefName}", not "main". '
            "Stop and ask the user."
        )
    if not context.branch_matches and not allow_branch_mismatch:
        raise UsageError(
            f'Current branch "{context.branch}" is not the PR head branch '
            f'"{context.pr.headRefName}". Check out the PR branch, or pass '
            "--allow-branch-mismatch after confirming with the user."
        )


def find_single_parent(repo: str, pr_url: str) -> ParentIssue:
    matches = find_parent_issues(repo, pr_url)
    if not matches:
        raise UsageError(
            f"No review-follow-up parent issue found for {pr_url}.\n"
            f"Expected an issue body containing: {parent_marker(pr_url)}"
        )
    if len(matches) > 1:
        lines = "\n".join(
            f"  #{match.number} {match.title} ({match.url})" for match in matches
        )
        raise UsageError(
            f"Found {len(matches)} parent issues for {pr_url}; refusing to guess:\n{lines}"
        )
    return matches[0]


def load_children(repo: str, parent: ParentIssue) -> list[ChildIssue]:
    nodes = list_native_children(repo, parent.number)
    if not nodes:
        raise UsageError(
            f"Parent #{parent.number} has no native sub-issues. "
            "Refusing to infer children from titles, labels, or comments."
        )
    # Preserve the native order returned by GitHub.
    return [get_issue(repo, node.number) for node in nodes]


# ── Reporting ─────────────────────────────────────────────────────────────


def summarize(child: ChildIssue) -> dict:
    flags = status_flags(child.comment_bodies)
    return {
        "number": child.number,
        "title": child.title,
        "url": child.url,
        "state": child.state,
        "priority": priority_label(child.labels),
        "labels": child.labels,
        "status": {"inProgress": flags.in_progress, "fixed": flags.fixed},
    }


def plan_json(plan: ApprovalPlan) -> dict:
    return {
        "addLabels": plan.add_labels,
        "removeLabels": plan.remove_labels,
        "addDecisionComment": plan.add_decision_comment,
    }


def emit(value: object) -> None:
    sys.stdout.write(json.dumps(value, indent=2) + "\n")


def no_available(selection: Selection) -> UsageError:
    reasons = "\n".join(
        f"  #{skipped.number} {skipped.reason}: {skipped.title}"
        for skipped in selection.skipped
    )
    return UsageError(
        "No approved open review follow-up is available. "
        f"Skipped children in native order:\n{reasons}",
        EXIT_NONE_AVAILABLE,
    )


def find_child(children: list[ChildIssue], issue_number: int) -> ChildIssue:
    for child in children:
        if child.number == issue_number:
            return child
    raise UsageError(f"Issue #{issue_number} is not a native child of this parent.")


def resolve_target(
    args: ParsedArgs, children: list[ChildIssue], selection: Selection
) -> ChildIssue:
    """Resolve which child to act on for ``start`` and ``fixed``.

    ``--issue`` may only name the child that native-order selection already
    chose, or the workflow's in-flight child: an open child that already carries
    an exact ``Status: in progress`` comment. ``start`` marks the selected child
    in progress, which removes it from native-order selection, so without the
    in-flight exception the same run could neither resume nor close the child it
    started whenever a later approved child exists. The exception never permits
    skipping ahead to a later untouched child.
    """
    if args.issue is None:
        if selection.selected is None:
            raise no_available(selection)
        return selection.selected
    explicit = find_child(children, args.issue)
    if not can_override_selection(explicit, selection):
        assert selection.selected is not None
        raise UsageError(
            f"Issue #{explicit.number} is not the first available child "
            f"(#{selection.selected.number}). The workflow requires the first "
            "available child in native sub-issue order; refusing to override.",
            EXIT_CONFLICT,
        )
    return explicit


def require_pr(args: ParsedArgs) -> str:
    if not args.pr:
        raise UsageError("Missing --pr <number-or-url>.")
    return args.pr


# ── select ────────────────────────────────────────────────────────────────


def cmd_select(args: ParsedArgs) -> int:
    context = resolve_context(require_pr(args))
    assert_processable(context, args.allow_branch_mismatch)
    parent = find_single_parent(context.repo, context.pr.url)
    children = load_children(context.repo, parent)
    selection = select_first_available(children)

    emit(
        {
            "repo": context.repo,
            "pr": {
                "number": context.pr.number,
                "title": context.pr.title,
                "url": context.pr.url,
                "state": context.pr.state,
                "headRefName": context.pr.headRefName,
                "baseRefName": context.pr.baseRefName,
            },
            "branch": {"current": context.branch, "matches": context.branch_matches},
            "parent": {
                "number": parent.number,
                "title": parent.title,
                "url": parent.url,
                "state": parent.state,
            },
            "selected": summarize(selection.selected) if selection.selected else None,
            "skipped": [
                {
                    "number": skipped.number,
                    "title": skipped.title,
                    "url": skipped.url,
                    "reason": skipped.reason,
                }
                for skipped in selection.skipped
            ],
            "childrenInspected": (
                len(selection.skipped) + 1 if selection.selected else len(selection.skipped)
            ),
            "totalChildren": len(children),
        }
    )

    return EXIT_OK if selection.selected else EXIT_NONE_AVAILABLE


# ── start ─────────────────────────────────────────────────────────────────


def cmd_start(args: ParsedArgs) -> int:
    context = resolve_context(require_pr(args))
    assert_processable(context, args.allow_branch_mismatch)
    parent = find_single_parent(context.repo, context.pr.url)
    children = load_children(context.repo, parent)
    selection = select_first_available(children)

    # With no --issue, selection must find one; with --issue, allow the resume
    # case where the child is already in progress.
    if args.issue is None:
        if selection.selected is None:
            raise no_available(selection)
        target = selection.selected
    else:
        target = resolve_target(args, children, selection)

    flags = status_flags(target.comment_bodies)
    if flags.fixed:
        emit({"action": "none", "reason": "STATUS_FIXED", "issue": summarize(target)})
        return EXIT_CONFLICT
    if flags.in_progress:
        # Idempotent: a rerun after an interrupted attempt must not fail here.
        emit({"action": "none", "reason": "ALREADY_IN_PROGRESS", "issue": summarize(target)})
        return EXIT_OK

    if args.dry_run:
        emit(
            {
                "action": "dry-run",
                "wouldComment": STATUS_IN_PROGRESS,
                "issue": summarize(target),
            }
        )
        return EXIT_OK

    add_comment(context.repo, target.number, STATUS_IN_PROGRESS)
    after = get_issue(context.repo, target.number)
    emit({"action": "commented", "comment": STATUS_IN_PROGRESS, "issue": summarize(after)})
    return EXIT_OK


# ── fixed ─────────────────────────────────────────────────────────────────


def read_closing_body(args: ParsedArgs) -> str:
    if not args.body_file:
        raise UsageError(
            "Missing --body-file <path>. Write the closing comment body to a file; "
            "do not pass markdown inline."
        )
    path = Path(args.body_file)
    if not path.exists():
        raise UsageError(f"--body-file not found: {args.body_file}")
    body = path.read_text(encoding="utf-8").strip()
    if not body:
        raise UsageError(f"--body-file is empty: {args.body_file}")
    if closing_body_repeats_status(body):
        raise UsageError(
            f'The closing comment begins with "{STATUS_FIXED}". The exact status comment '
            "is posted separately for availability checks; remove that line from the "
            "closing body."
        )
    return body


def cmd_fixed(args: ParsedArgs) -> int:
    body = read_closing_body(args)
    context = resolve_context(require_pr(args))
    assert_processable(context, args.allow_branch_mismatch)
    parent = find_single_parent(context.repo, context.pr.url)
    children = load_children(context.repo, parent)
    selection = select_first_available(children)

    # Idempotent re-run: an explicit issue that is already closed *and* marked
    # fixed is a no-op, even though native-order selection has moved on to the
    # next child. Without this, rerunning `fixed` after a successful close would
    # fail the selection-override guard below.
    if args.issue is not None:
        explicit = find_child(children, args.issue)
        if explicit.state.upper() != "OPEN" and status_flags(explicit.comment_bodies).fixed:
            emit(
                {
                    "action": "none",
                    "reason": "ALREADY_CLOSED_AND_FIXED",
                    "issue": summarize(explicit),
                }
            )
            return EXIT_OK

    target = resolve_target(args, children, selection)

    # Guard against closing something that is not an approved follow-up.
    missing = [
        label
        for label in (LABEL_REVIEW_FOLLOW_UP, LABEL_APPROVE_FIX)
        if label not in target.labels
    ]
    if missing:
        raise UsageError(
            f"Issue #{target.number} is missing required label(s): {', '.join(missing)}. "
            "Refusing to close.",
            EXIT_CONFLICT,
        )

    before = status_flags(target.comment_bodies)
    if target.state.upper() != "OPEN":
        raise UsageError(
            f'Issue #{target.number} is {target.state} without an exact "{STATUS_FIXED}" '
            "comment. Refusing to reopen or re-close it.",
            EXIT_CONFLICT,
        )

    if args.dry_run:
        emit(
            {
                "action": "dry-run",
                "wouldComment": None if before.fixed else STATUS_FIXED,
                "wouldClose": True,
                "bodyFile": args.body_file,
                "issue": summarize(target),
            }
        )
        return EXIT_OK

    if not before.fixed:
        add_comment(context.repo, target.number, STATUS_FIXED)
    close_issue(context.repo, target.number, body)

    after = get_issue(context.repo, target.number)
    after_labels_intact = all(
        label in after.labels for label in (LABEL_REVIEW_FOLLOW_UP, LABEL_APPROVE_FIX)
    )
    emit(
        {
            "action": "closed",
            "statusCommentAdded": not before.fixed,
            "labelsIntact": after_labels_intact,
            "issue": summarize(after),
        }
    )

    if not after_labels_intact or after.state.upper() != "CLOSED":
        sys.stderr.write("error: post-close verification failed; inspect the issue above.\n")
        return EXIT_VERIFY_FAILED
    return EXIT_OK


# ── approve ───────────────────────────────────────────────────────────────


def ensure_approve_label(repo: str) -> bool:
    """Create the ``approve-fix`` label if it is missing, so the edit cannot fail."""
    existing = any(label.get("name") == LABEL_APPROVE_FIX for label in label_list(repo))
    if existing:
        return False
    definition = LABEL_DEFINITIONS[LABEL_APPROVE_FIX]
    create_label(repo, LABEL_APPROVE_FIX, definition["color"], definition["description"])
    return True


def cmd_approve(args: ParsedArgs) -> int:
    """Record the human approval on every open child.

    Adds ``approve-fix``, removes ``decision-pending``, and posts the exact
    ``Decision: approve-fix`` comment.

    Idempotent and non-destructive: closed children are never touched, existing
    labels and comments are preserved, and a child that is already approved is
    reported, not rewritten.
    """
    context = resolve_context(require_pr(args))
    assert_processable(context, args.allow_branch_mismatch)
    parent = find_single_parent(context.repo, context.pr.url)
    children = load_children(context.repo, parent)

    open_children = [child for child in children if child.state.upper() == "OPEN"]
    needs_label = any(
        LABEL_APPROVE_FIX in approval_plan(child).add_labels for child in open_children
    )
    label_present = any(
        label.get("name") == LABEL_APPROVE_FIX for label in label_list(context.repo)
    )

    if args.dry_run:
        emit(
            {
                "action": "dry-run",
                "parent": {"number": parent.number, "url": parent.url},
                "wouldCreateLabel": needs_label and not label_present,
                "children": [
                    _approve_dry_run_child(child) for child in children
                ],
            }
        )
        return EXIT_OK

    label_created = ensure_approve_label(context.repo) if needs_label else False

    results: list[dict] = []
    ok = True
    for child in children:
        if child.state.upper() != "OPEN":
            results.append(
                {"number": child.number, "url": child.url, "action": "preserved-closed"}
            )
            continue
        before = is_approved(child)
        plan = approval_plan(child)
        if plan.add_labels or plan.remove_labels:
            edit_issue(
                context.repo,
                child.number,
                add_labels=plan.add_labels,
                remove_labels=plan.remove_labels,
            )
        if plan.add_decision_comment:
            add_comment(context.repo, child.number, DECISION_APPROVE_FIX)
        after = get_issue(context.repo, child.number)
        approved = is_approved(after)
        ok = ok and approved
        results.append(
            {
                "number": child.number,
                "title": child.title,
                "url": child.url,
                "action": "already-approved" if before else "approved",
                "decisionCommentAdded": plan.add_decision_comment,
                "approved": approved,
                "issue": summarize(after),
            }
        )

    emit(
        {
            "action": "approve",
            "parent": {"number": parent.number, "url": parent.url},
            "labelCreated": label_created,
            "children": results,
        }
    )

    if not ok:
        sys.stderr.write("error: post-approve verification failed; inspect the issues above.\n")
        return EXIT_VERIFY_FAILED
    return EXIT_OK


def _approve_dry_run_child(child: ChildIssue) -> dict:
    is_open = child.state.upper() == "OPEN"
    if not is_open:
        action = "preserved-closed"
    elif is_approved(child):
        action = "already-approved"
    else:
        action = "would-approve"
    return {
        "number": child.number,
        "title": child.title,
        "url": child.url,
        "state": child.state,
        "action": action,
        "plan": plan_json(approval_plan(child)) if is_open else None,
    }


# ── verify ────────────────────────────────────────────────────────────────


def cmd_verify(args: ParsedArgs) -> int:
    context = resolve_context(require_pr(args))
    parent = find_single_parent(context.repo, context.pr.url)
    children = load_children(context.repo, parent)
    selection = select_first_available(children)

    if args.issue is None and selection.selected is None:
        raise UsageError(
            "No available child to verify. Pass --issue <number> to verify a "
            "specific (typically closed) child.",
            EXIT_NONE_AVAILABLE,
        )
    # `verify` is read-only and deliberately exempt from the native-order
    # override guard: its main use is re-reading the child that was just closed.
    if args.issue is not None:
        target = find_child(children, args.issue)
    else:
        assert selection.selected is not None
        target = selection.selected

    flags = status_flags(target.comment_bodies)
    required_labels = (LABEL_REVIEW_FOLLOW_UP, LABEL_APPROVE_FIX)
    missing_labels = [label for label in required_labels if label not in target.labels]
    priority = priority_label(target.labels)
    detail_comment = any(
        body != STATUS_IN_PROGRESS
        and body != STATUS_FIXED
        and not body.startswith("Decision:")
        for body in target.comment_bodies
    )

    checks = {
        "closed": target.state.upper() == "CLOSED",
        "hasStatusFixed": flags.fixed,
        "requiredLabelsPresent": not missing_labels,
        "hasPriorityLabel": priority is not None,
        "hasDetailComment": detail_comment,
    }
    passed = all(checks.values())

    emit(
        {
            "issue": summarize(target),
            "checks": checks,
            "missingLabels": missing_labels,
            "passed": passed,
        }
    )
    return EXIT_OK if passed else EXIT_VERIFY_FAILED


# ── Entry point ───────────────────────────────────────────────────────────

HELP = """review-followup — GitHub bookkeeping for review follow-up issues

Usage:
  review_followup.py select  --pr <number-or-url> [--allow-branch-mismatch]
  review_followup.py start   --pr <number-or-url> [--issue <n>] [--dry-run]
  review_followup.py fixed   --pr <number-or-url> --body-file <path> [--issue <n>] [--dry-run]
  review_followup.py verify  --pr <number-or-url> [--issue <n>]
  review_followup.py approve --pr <number-or-url> [--dry-run]

Notes:
  --issue may only name the child chosen by native-order selection, or the
  workflow's in-flight child (open, with an exact "Status: in progress"
  comment). It cannot bypass the "first available in native sub-issue order"
  rule.

Exit codes: 0 ok, 1 verification failed, 2 usage/GitHub error,
            3 no available child, 4 workflow conflict.
"""


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.command == "help":
        sys.stdout.write(HELP)
        return EXIT_OK
    if args.command == "select":
        return cmd_select(args)
    if args.command == "start":
        return cmd_start(args)
    if args.command == "fixed":
        return cmd_fixed(args)
    if args.command == "verify":
        return cmd_verify(args)
    if args.command == "approve":
        return cmd_approve(args)
    raise UsageError(f'Unknown command "{args.command}".')


def cli(argv: list[str] | None = None) -> int:
    try:
        return main(sys.argv[1:] if argv is None else argv)
    except UsageError as error:
        sys.stderr.write(f"error: {error}\n")
        return error.exit_code
    except CommandError as error:
        sys.stderr.write(f"error: {error}\n")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(cli())
