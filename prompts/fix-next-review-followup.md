---
description: Fix the next approved review follow-up issue for a pull request
argument-hint: "[PR number or URL]"
---

# Fix the next available review follow-up task for a PR

Use this prompt after review follow-up issues have been published and approved. Given a pull request number or URL, locate its review-follow-up parent issue, enumerate the parent’s native child issues, select the first available approved child, implement that issue against the current branch, verify the fix, record that it is fixed, and close the issue.

This prompt authorizes both repository code changes and GitHub issue updates. Every GitHub read or write goes through the `review-followup` script (which wraps `gh`), or through the GitHub CLI (`gh`) directly as a fallback. Do not edit the PR description, merge the PR, or create a new PR unless the user explicitly asks.

The PR argument is `$1`. If it is missing, stop and ask for a PR number or URL.

## 0. Use the bookkeeping script

The toolkit's `prompts/scripts/review-followup/` directory (`$AIDW_SCRIPTS_DIR/review-followup/`) owns every mechanical part of the GitHub workflow described below. Prefer it over hand-written `gh` calls: it is exact-match, idempotent, and avoids the known shell hazards (`gh issue close` has no `--body-file`; `gh api --slurp` cannot be combined with `--jq`; long markdown bodies are unsafe to pass inline).

```bash
# AIDW exports AIDW_SCRIPTS_DIR = the toolkit's absolute prompts/scripts directory, for
# every stage. It is inherited by each `bash` call, so the bundled script resolves no
# matter which repository is the working directory; fail fast if it is unset rather than
# guessing a path relative to the current directory.
: "${AIDW_SCRIPTS_DIR:?AIDW_SCRIPTS_DIR is not set; run this prompt via aidw (aidw fix)}"
pr="<PR number or URL>"

python3 "$AIDW_SCRIPTS_DIR/review-followup/review_followup.py" select --pr "$pr"          # read-only
python3 "$AIDW_SCRIPTS_DIR/review-followup/review_followup.py" start  --pr "$pr"          # records "Status: in progress"
python3 "$AIDW_SCRIPTS_DIR/review-followup/review_followup.py" fixed  --pr "$pr" --issue <child> --body-file "$body"
python3 "$AIDW_SCRIPTS_DIR/review-followup/review_followup.py" verify --pr "$pr" --issue <child>   # read-only
```

Rules for using it:

- Use the `python3 "$AIDW_SCRIPTS_DIR/review-followup/review_followup.py"` form above. It runs on any Python 3.9+ with no install step and no third-party dependencies, so it works in any repository these prompts are copied into.
- Do **not** route the output through a package-manager script alias when you need to read the JSON output — the package manager prefixes its own banner to stdout, and `pnpm -s` collapses every non-zero exit code to 1.
- Read the exit code: `0` ok, `1` verification failed, `2` usage/GitHub error, `3` no available child, `4` workflow conflict. A non-zero code means stop and report — do not work around it.
- The script never decides whether the *code* work is done. `fixed` is an explicit call you make only after section 5 passes. Never chain it to anything.
- Its `select` output is the authoritative parent/child resolution; use it for your final report rather than re-deriving values.

If the script is unavailable, the manual equivalents in the Appendix are the fallback. Do not invent other command forms.

## Definition of “available”

A child issue is available only when all of these are true:

- Its state is `OPEN`.
- It has the `approve-fix` label.
- It does not have the `decision-pending` label.
- It does not already have a comment whose body is exactly `Status: in progress` or exactly `Status: fixed`.

Select the first available child in the order returned by the parent issue’s native `subIssues` relationship. Do not choose an issue by title, priority, creation date, or issue number if the native relationship gives an order.

Closed children, pending-decision children, unapproved children, and children already marked in progress or fixed must be skipped. Do not modify skipped issues.

Children that appear *after* the selected child are not inspected. This prompt fixes exactly one issue per invocation.

## 1. Validate GitHub access, the PR, and the current branch

Run the read-only validation first:

```bash
python3 "$AIDW_SCRIPTS_DIR/review-followup/review_followup.py" select --pr "$pr"
```

This performs the access, PR, base-branch, and branch checks below and resolves the parent and selection in one call. It stops when:

- GitHub CLI is not authenticated.
- The PR cannot be resolved.
- The PR is not open, unless the user explicitly confirms that a closed PR should be processed.
- The PR base is not `main`, unless the user explicitly confirms the exception.
- The current branch does not equal the PR’s `headRefName` (use `--allow-branch-mismatch` only after the user confirms).

Record from its output: repository, PR number, title, canonical PR URL, head branch, current branch, parent issue, selected child, and the skipped children with reasons.

Inspect the current branch’s complete change set before editing:

```bash
git diff --stat main...HEAD
git diff main...HEAD --
git diff --cached --stat
git status --short --untracked-files=all
```

Do not discard, reset, or overwrite unrelated existing work. If the working tree contains changes that make it unsafe to identify which files belong to the selected issue, stop and ask the user before editing.

## 2. Locate the review-follow-up parent issue

The parent issue is identified by this exact body marker:

```text
<!-- mythical-forge-review-followups: pr=<canonical PR URL> -->
```

`select` performs this search across all repository issues, including closed ones. Rules it enforces for you:

- If no matching parent exists, it stops and reports that no review-follow-up hierarchy was found.
- If more than one matching parent exists, it stops and reports all matches; it will not guess.
- The parent may itself be open or closed. The child state and labels determine availability.

Do not substitute a title or label match for the marker.

## 3. Enumerate and select the first available child

`select` enumerates the parent’s native `subIssues` in GitHub’s order, resolves each child’s labels and comment bodies, and applies the availability definition above. It reports:

- `selected` — the first available child (or `null`), with its priority label.
- `skipped` — each earlier child with the reason it was skipped (`CLOSED`, `MISSING_APPROVE_FIX`, `DECISION_PENDING`, `STATUS_IN_PROGRESS`, `STATUS_FIXED`).

If exit code `3` is returned, no child is available: stop without changing files or GitHub issues and report that no approved open review follow-up is available.

Before editing code, report:

- Parent issue number and URL.
- Selected child issue number, title, URL, and priority label.
- Skipped children and the reason each was skipped.

### Resuming after an interrupted run

An exact `Status: in progress` comment makes a child unavailable, so a run that aborts after `start` would otherwise strand that child forever. If `select` reports `STATUS_IN_PROGRESS` for the child you were working on, and the user confirms you should resume it, run `python3 "$AIDW_SCRIPTS_DIR/review-followup/review_followup.py" start --pr "$pr" --issue <child>` again: it is idempotent and reports `ALREADY_IN_PROGRESS` without posting a second comment. Only do this when you are resuming the same child in the same working tree; otherwise report the stranded child and stop.

## 4. Read the selected issue and repository guidance

Read the complete selected issue body and all relevant comments. Treat the issue’s review finding, trigger, location, suggested fix, and acceptance criteria as the task scope.

Also read, as applicable:

- `AGENTS.md` and any nearer `AGENTS.md` files.
- The source files and tests named by the issue.
- Immediate surrounding code and callers.
- The task prompt, design/spec, convention, or documentation cited by the issue.
- Existing repository scripts and package guidance needed to run focused checks.

Do not weaken the issue’s technical requirement. Do not expand into other review findings or speculative cleanup. If the issue is ambiguous, conflicts with the repository’s current architecture, or requires a decision not stated in the issue, stop and ask the user instead of guessing.

Before implementation, record that work has started:

```bash
python3 "$AIDW_SCRIPTS_DIR/review-followup/review_followup.py" start --pr "$pr"
```

This posts the exact comment `Status: in progress` to the selected issue. Only run it after the selected issue has been confirmed as available and the repository/issue context has been read. If it fails, stop before editing files.

## 5. Implement the fix on the current branch

Implement only the selected issue in the current working tree.

Requirements:

- Preserve unrelated existing changes.
- Follow repository language, tenancy, security, testing, and package conventions.
- Add or update focused tests that fail before the fix and pass after it.
- Do not close the issue merely because code was changed; the acceptance criteria must be verified.
- Do not create infrastructure, schema, or security changes beyond the selected issue’s scope.

Use repository editing tools for code changes. Do not use GitHub API calls to alter source files.

### Proving the focused tests fail before the fix

The requirement “fail before the fix and pass after it” needs a before-state. Because your changes are uncommitted, capture them and swap in the pre-fix version of the file:

```bash
cp <path> /tmp/review-followup-fixed.bak
git show HEAD:<path> > <path>
pnpm --filter <affected-package> test -- <focused pattern>   # must FAIL
cp /tmp/review-followup-fixed.bak <path>
pnpm --filter <affected-package> test -- <focused pattern>   # must PASS
```

Always restore the file and confirm `git diff` still shows your fix before continuing. A path-scoped `git stash push -- <paths you modified in this run>` followed immediately by `git stash pop` is also acceptable. Never stash, reset, or check out paths you did not modify in this run.

## 6. Verify the fix

Run the narrowest meaningful checks first, then broader checks required by the affected package or issue. Use the repository’s package manager and report the real commands and outcomes.

At minimum, where applicable, run:

```bash
pnpm --filter <affected-package> build
pnpm --filter <affected-package> lint
pnpm --filter <affected-package> test
```

Also run focused tests for the selected issue. Do not claim tests passed unless they actually passed. If a check cannot run because it requires unavailable AWS credentials, deployed infrastructure, or another external dependency, report it clearly and do not close the issue unless the user explicitly accepts that limitation.

Inspect the final diff and check for accidental changes:

```bash
git diff --check
git diff --stat
git diff --
git status --short --untracked-files=all
```

### Pre-existing failures

If a broader check fails, reproduce that failure on the unmodified branch tip before attributing it to your change. Report pre-existing failures and new failures separately, and never report a pre-existing failure as caused by your fix.

“Verification fails” in this prompt means **the selected issue’s acceptance checks fail** — not an unrelated, pre-existing failure elsewhere in the repository. An unrelated failure does not by itself prevent closing a correctly fixed issue; it must be reported as a limitation instead.

If the selected issue’s own acceptance checks fail, leave the issue open, add a concise issue comment describing the failure, and stop. Do not label or close the issue as fixed.

## 7. Mark the issue fixed and close it

Only after implementation and acceptance checks pass.

Write the closing comment body to a file first. Use a quoted heredoc so backticks, `$`, and apostrophes in the body stay inert:

```bash
body="$(mktemp -t review-followup-body.XXXXXX)"
cat > "$body" <<'BODY'
Implemented on the current PR branch.

**Root cause.** ...

**Files changed**
- `path` — what changed

**Verification**
- `<exact command>` — passed
- `<exact command>` — 12 passed, 0 failed

**Remaining limitations**
- ... or `None.`
BODY
```

The body must not begin with `Status: fixed`; that exact comment is posted separately so availability checks stay an exact-match test. The script enforces this.

Then:

```bash
python3 "$AIDW_SCRIPTS_DIR/review-followup/review_followup.py" fixed --pr "$pr" --issue <child> --body-file "$body"
```

This posts the exact comment `Status: fixed` (skipped if already present), closes the issue with your body, and reports whether the labels survived.

The closing comment must include the real verification results and any remaining limitation, including pre-existing failures you did not fix. Do not write results you did not observe.

Preserve the child’s priority label and `review-follow-up` label. Do not remove `approve-fix` unless the repository workflow explicitly requires it. Do not use `Fixes #...` unless the user explicitly requests automatic PR linkage.

## 8. Verify GitHub state

Re-read the selected issue:

```bash
python3 "$AIDW_SCRIPTS_DIR/review-followup/review_followup.py" verify --pr "$pr" --issue <child>
```

Confirm from its output:

- The selected issue is `CLOSED`.
- It has an exact `Status: fixed` comment.
- The fix verification results are recorded (a detail comment exists).
- The priority, `review-follow-up`, and `approve-fix` labels are intact.

If any check fails, report the exact mismatch. Do not process a second child in the same run. This prompt fixes exactly one next available issue per invocation.

## Final report

Report:

- PR number and canonical URL.
- Parent issue number and URL.
- Selected child issue number, URL, title, and priority.
- Children skipped and why.
- Files changed.
- Exact verification commands and their real results.
- Confirmation that `Status: fixed` was recorded and the selected issue was closed.
- Any remaining limitation or unverified check.

Do not claim that the PR is approved, merged, or fully complete. This prompt fixes and closes one approved review follow-up issue only.

## Appendix: manual equivalents

Use these only if the toolkit's `prompts/scripts/review-followup/` scripts are unavailable. They require `jq`.

Find the parent by exact marker (external `jq`, because `gh api --slurp` cannot be combined with `--jq`):

```bash
repo="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
pr_url="$(gh pr view <pr-number-or-url> --json url --jq .url)"
marker="<!-- mythical-forge-review-followups: pr=$pr_url -->"
gh api --paginate --slurp "repos/$repo/issues?state=all&per_page=100" |
  jq -r --arg marker "$marker" '
    add[]
    | select(.pull_request == null)
    | select((.body // "") | contains($marker))
    | {number,title,html_url,state}
  '
```

Enumerate native children in order:

```bash
gh issue view <parent-number> --repo "$repo" \
  --json subIssues \
  --jq '.subIssues.nodes[] | {number,title,state,url}'
```

Decide availability with strict equality (never substring matching):

```bash
gh api --paginate --slurp "repos/$repo/issues/<child-number>/comments?per_page=100" |
  jq -r '[add[].body] | {in_progress: any(. == "Status: in progress"),
                          fixed: any(. == "Status: fixed")}'
```

Post a status comment from stdin, and close with a file-sourced body:

```bash
printf 'Status: fixed' | gh issue comment <child-number> --repo "$repo" --body-file -
gh issue close <child-number> --repo "$repo" --comment "$(cat "$body")"
```

`gh issue close` supports only `--comment`; it has no `--body-file`. Never write a comment body inline in double quotes — backticks would execute.
