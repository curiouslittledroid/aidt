---
description: Approve all open review follow-up sub-issues for a pull request
argument-hint: "[PR number or URL]"
---

# Approve open review follow-up tasks for a PR

Use this prompt after review follow-up issues have been published and a human has decided
them on GitHub. Given a pull request number or URL, find the review-follow-up parent issue
for that PR and apply the approval to every child issue that is still open.

This is a GitHub-writing operation. Do not edit repository files, code, or pull-request
descriptions.

## Tool restriction

Use only the bundled bookkeeping script for GitHub reads and writes:

```bash
runner="python3 aidt/prompts/scripts/review-followup/review_followup.py"
pr="<PR number or URL>"

$runner approve --pr "$pr" --dry-run   # read-only: show exactly what would change
$runner approve --pr "$pr"             # apply the approval
```

Do not call `gh issue edit`, `gh issue comment`, `gh label create`, or a mutating `gh api`
method directly for this operation; the script owns the exact labels, comment text, marker
matching, and idempotency. Do not use MCP GitHub tools, SDKs, or other integrations.

The script:

1. Locates the parent issue by its exact body marker (never by title or label).
2. Ensures the `approve-fix` label exists — it creates it with the canonical colour and
   description only when it is missing, and never overwrites an existing label.
3. For every **open** child: adds `approve-fix`, removes `decision-pending` if present, and
   posts the exact comment `Decision: approve-fix` unless that exact comment already exists.
4. Leaves **closed** children completely unchanged.
5. Re-reads every child and fails with exit code `1` if an open child is not fully approved.

Exit codes: `0` ok, `1` verification failed, `2` usage/GitHub error, `4` workflow conflict.
A non-zero exit means stop and report the exact error.

The PR argument is `$1`. If it is missing, stop and ask for a PR number or URL.

## 1. Run the dry run first

```bash
$runner approve --pr "$pr" --dry-run
```

Stop and report if it fails. Read the JSON: it lists, per child, the action
(`would-approve`, `already-approved`, `preserved-closed`) and the exact label/comment plan.
Confirm the parent is the expected one. Do not continue on an ambiguity.

## 2. Apply the approval

```bash
$runner approve --pr "$pr"
```

Read the exit code. On `0`, the JSON reports `labelCreated` and, per child, `action`,
`decisionCommentAdded`, and `approved`.

If it exits non-zero, report the exact error and what the output says was already processed.
Do not retry individual writes by hand: the command is idempotent and may be re-run safely.

## Final report

Report:

- PR number and canonical URL.
- Parent issue number and URL.
- Whether the `approve-fix` label was created or reused.
- Every open child updated: number, URL, title, and whether the decision comment was newly
  added or already present.
- Every closed child skipped: number and URL.
- The required next action: run the fix workflow (`aidw fix` or
  `/fix-next-review-followup`), which implements one approved child at a time.

Do not claim that implementation is complete, verified, or merged. This operation only
records approval decisions and labels.
