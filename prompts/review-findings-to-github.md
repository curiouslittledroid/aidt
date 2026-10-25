---
description: Turn completed review findings into an idempotent GitHub follow-up hierarchy
argument-hint: "[PR number or URL]"
---

# Publish review findings as GitHub tasks

Use this prompt after a code review is complete. Publish one parent GitHub issue, one native sub-issue per actionable review finding, and one linked summary comment on the originating pull request.

## Source of truth

Use only the findings from the immediately preceding review in this pi session.

- Include only findings with priority `Must fix`, `Should fix`, or `Could fix`.
- Preserve each finding's priority, confidence, technical evidence, impact, trigger/effect, location, and suggested fix.
- Do not invent findings from a fresh review.
- Do not create tasks for test-environment failures, unverified risks, personal preferences, or review commentary unless they were explicitly reported as findings.
- If the preceding review findings are unavailable or their priorities are ambiguous, stop and ask the user.
- If the review reported no findings, report that no issues will be created and stop.
- Assign stable IDs in review order: `F1`, `F2`, `F3`, and so on.

The optional argument is `$1`. If supplied, pass it as the PR number or URL. Otherwise resolve the PR from the current branch through the publisher.

## Use the publisher script

Do not perform GitHub issue or PR writes directly. Use the script that ships beside this prompt:

```bash
# AIDW exports AIDW_SCRIPTS_DIR = the toolkit's absolute prompts/scripts directory, for
# every stage. It is inherited by each `bash` call, so the bundled script resolves no
# matter which repository is the working directory; fail fast if it is unset rather than
# guessing a path relative to the current directory.
: "${AIDW_SCRIPTS_DIR:?AIDW_SCRIPTS_DIR is not set; run this prompt via aidw (aidw review or aidw fix)}"

python3 "$AIDW_SCRIPTS_DIR/review-followup/publish_review_followups.py" [--pr <PR number or URL>] --input <manifest path> --dry-run
python3 "$AIDW_SCRIPTS_DIR/review-followup/publish_review_followups.py" [--pr <PR number or URL>] --input <manifest path>
```

If the prompt argument contains a PR number or URL, pass it with `--pr`. If no argument was supplied, omit `--pr`; the script will resolve the PR for the current branch with `gh pr view`.

The script is `publish_review_followups.py` in the toolkit's `prompts/scripts/review-followup/` directory (`$AIDW_SCRIPTS_DIR/review-followup/`). It invokes the GitHub CLI, validates the PR and manifest, creates missing labels, reconciles existing parent/child issues using stable markers, verifies native sub-issue relationships, and creates or updates the PR summary comment. It is intentionally idempotent and stops on ambiguous matches.

It has no install step and no third-party dependencies: run it with any Python 3.9+ (`python3`). If `AIDW_SCRIPTS_DIR` is unset or the script is missing, stop and report that the publisher is unavailable; do not hand-write the issue, label, sub-issue, and comment writes this prompt depends on.

The script requires:

- an authenticated GitHub CLI;
- an open PR targeting `main`;
- a JSON manifest containing the findings;
- `gh` as the only GitHub integration.

Exit codes are `0` success, `2` usage/validation/GitHub error. A non-zero exit means stop and report the exact error and the issues it says were already created or updated.

Run the dry run first. If it reports an ambiguity or validation failure, stop and report it. If the dry run succeeds, run the real command without `--dry-run`.

## Manifest format

Create a temporary JSON manifest from the preceding review. Use a quoted heredoc so Markdown content and backticks are not interpreted by the shell:

```bash
manifest_file="$(mktemp)"
trap 'rm -f "$manifest_file"' EXIT
cat > "$manifest_file" <<'EOF'
{
  "findings": [
    {
      "id": "F1",
      "priority": "must-fix",
      "confidence": 5,
      "title": "Short imperative task title",
      "whatFound": "The exact technical defect.",
      "whyItMatters": "The customer, caller, service, security, data, or operations impact.",
      "triggerAndEffect": "The exact condition and observable effect.",
      "where": "path/to/file.ts:10-20",
      "suggestedFix": "A practical direction for correcting it."
    }
  ]
}
EOF
```

The manifest must contain exactly these fields:

- `id`: sequential `F1`, `F2`, ... in review order;
- `priority`: one of `must-fix`, `should-fix`, or `could-fix`;
- `confidence`: integer from 0 to 5;
- `title`, `whatFound`, `whyItMatters`, `triggerAndEffect`, `where`, and `suggestedFix`: non-empty strings.

Do not include findings with any other priority. Do not weaken technical evidence while converting the review into JSON. JSON escaping is required for embedded quotes, backslashes, or newlines.

## Reconciliation behavior

The script uses these exact browser-URL markers:

```text
<!-- mythical-forge-review-followups: pr=<canonical PR URL> -->
<!-- mythical-forge-review-follow-up: pr=<canonical PR URL> finding=F1 -->
<!-- mythical-forge-review-follow-ups-summary: pr=<canonical PR URL> -->
```

It will:

- reuse exactly one existing parent for the PR, or create one;
- stop if duplicate parents or duplicate child markers exist;
- create missing children as native GitHub sub-issues;
- update open children that still have `decision-pending`;
- preserve closed children and open children with an existing decision;
- keep the parent table and PR summary synchronized;
- preserve human decisions rather than reopening or rewriting decided children;
- stop if an existing child is not a native sub-issue of the selected parent.

Do not manually retry individual issue or comment writes. If the script exits unsuccessfully, report its exact error and the issues it says were already created or updated.

## Completion report

After the real command succeeds, report:

- PR number and canonical browser URL;
- parent issue number and browser URL;
- every finding ID, child issue number, browser URL, priority, confidence, and title;
- labels created or reused;
- confirmation that native parent/child relationships and labels were verified;
- confirmation that each body was re-read and validated;
- confirmation that the PR summary comment exists exactly once;
- any preserved closed or previously decided children;
- the required human action: decide each open pending child with `Decision: approve-fix`, `Decision: accepted-risk`, or `Decision: not-a-bug`.

Do not claim that any task is approved, fixed, verified, or closed. Publication only records pending follow-up tasks.
