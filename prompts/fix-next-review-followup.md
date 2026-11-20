---
description: Fix the next approved review follow-up issue for a pull request
argument-hint: "[PR number or URL]"
---

# Fix the next available review follow-up task for a PR

Use this prompt after review follow-up issues have been published and approved. Given a pull request number or URL, locate its review-follow-up parent issue, enumerate the parent’s native child issues, select the first available approved child, implement that issue against the current branch, verify the fix, and write its closing comment body to the file this prompt hands you.

**Do not post `Status: fixed` and do not close the issue.** A `fix` run closes its follow-up issues only after the change set has been committed and pushed, so the issue stays `OPEN` with the exact `Status: in progress` comment `start` posted; the workflow’s close step runs `review_followup.py close` once the push is verified. Closing it here would report work as landed before it reached the pull request.

This prompt authorizes both repository code changes and GitHub issue updates. Every GitHub read or write goes through the `review-followup` script (which wraps `gh`), or through the GitHub CLI (`gh`) directly as a fallback. Do not edit the PR description, merge the PR, or create a new PR unless the user explicitly asks.

The PR argument is `$1`. If it is missing, stop and ask for a PR number or URL.

The closing-body path is `$2`: an **absolute** path inside this run's directory. Write section 7's body there — never to a `mktemp` file and never to a path relative to the repository.

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
python3 "$AIDW_SCRIPTS_DIR/review-followup/review_followup.py" verify --pr "$pr" --issue <child>   # read-only
```

There is deliberately no `fixed` or `close` call in this prompt. `close --pr "$pr" --issue <child> --body-file <path>` is the workflow’s own step, run in Python after the commit-and-push stage has verified the push. It posts the exact `Status: fixed` comment (skipped if already present) and closes the issue with the body you wrote.

Rules for using it:

- Use the `python3 "$AIDW_SCRIPTS_DIR/review-followup/review_followup.py"` form above. It runs on any Python 3.9+ with no install step and no third-party dependencies, so it works in any repository these prompts are copied into.
- Do **not** route the output through a wrapper or script alias when you need to read the JSON output — a wrapper can prefix its own banner to stdout and collapse every non-zero exit code to 1. Run the `python3` command above directly.
- Read the exit code: `0` ok, `1` verification failed, `2` usage/GitHub error, `3` no available child, `4` workflow conflict. A non-zero code means stop and report — do not work around it.
- The script never decides whether the *code* work is done. It also never closes an issue on your behalf in this prompt: you write the closing body (section 7) and the workflow closes the issue once the fix is pushed.
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

The parent issue is identified by the repo's configured parent marker (`github.markers.parent`), rendered with the canonical PR URL. The marker template is frozen and lives in the repo's config, so never retype it: `select` reads it from the resolved config and matches issue bodies exactly.

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
<the repo's focused test command>   # must FAIL
cp /tmp/review-followup-fixed.bak <path>
<the repo's focused test command>   # must PASS
```

Always restore the file and confirm `git diff` still shows your fix before continuing. A path-scoped `git stash push -- <paths you modified in this run>` followed immediately by `git stash pop` is also acceptable. Never stash, reset, or check out paths you did not modify in this run.

These two invocations stay **bare commands** — deliberately *not* `aidw gate run`. The first is **meant to fail**: it is the red-before half of the proof. Wrapping it would record a `failed` gate outcome that is never cited, only noise in `aidw gate list`, and section 6's outcomes are the evidence this prompt records.

## 6. Verify the fix

Run the narrowest meaningful checks first, then broader checks required by the affected package or issue. Use the repo's own gate commands. When this prompt carries a **resolved gate commands** block, that block is the authoritative source: the repo's own gate commands, taken verbatim from its `aidw/conventions.md` and/or its root `AGENTS.md` and injected by the renderer. When no such block is present, take them by name from its `aidw/conventions.md`, its root `AGENTS.md`, or the issue. Report the real commands and outcomes.

Run each command through `aidw gate run <key> $SCOPE -- <command>`, so its outcome is recorded against the exact tree it verified and a later stage of this run cites it instead of buying the same run twice. At minimum, where applicable:

```bash
# what these gates' commands cannot read: the documents the *other* stages write — read
# each resolved value from `aidw config show` and pass it as one --ignore prefix
SCOPE="--ignore <implementation_results_dir> --ignore <architecture_dir> --ignore <roadmap_dir> --ignore <task_prompts_dir>"
aidw gate run build $SCOPE -- <the repo's package-scoped build command>
aidw gate run lint  $SCOPE -- <the repo's package-scoped lint command>
aidw gate run smoke $SCOPE -- <the repo's package-scoped test command>
```

Keys name gates the way `pr.md` names them: `suite` for the full test gate, `lint`, `build`, and `smoke` for a package-scoped check (as `test.md` uses). The same command from every stage must carry the same key.

`--ignore` declares paths the gate’s command cannot read. The four above are the other stages' configured write-targets — `implementation_results_dir`, `architecture_dir`, `roadmap_dir`, `task_prompts_dir` — resolved for this repo by `aidw config show` and never retyped from another repo's defaults: a document those stages wrote cannot change a build, lint or test result. If a stage of this workflow writes anywhere else, add that too — the list is every path a stage *writes* and no path a gate *reads*. **Never ignore anything else**: source, tests, config and lockfiles must always re-run the gate.

Every stage of a run that asks for a gate must pass the same key, command and `--ignore` scope, or the outcomes cannot line up and the gate re-runs instead of being cited.

Reuse is **same-run only**. A gate outcome is evidence about *this* run’s tree, never about another run’s, so a `reused:` line here can only cite an outcome an earlier stage of this same fix run recorded — the fix chain’s `test` stage (F2, `test.md`) is the citing consumer of the gates recorded here, and it asks for the same keys and the same scope. An outcome from the implement chain, or from an earlier fix run, is a number to reproduce, not one to copy.

Asking again for the same key, command and scope against content that differs only inside that scope prints

`reused: gate '<key>' passed for tree <id> at <time> by stage '<stage>' (<summary>) [scope excludes: ...]`

and exits 0 **without re-running** — cite that line, with its origin (key, tree, stage, timestamp), as evidence rather than re-running the gate, and never transcribe a number you did not observe. `--force` re-runs when you doubt the outcome; a `failed:` line is never evidence — fix the failure and ask again.

Also run focused tests for the selected issue: bare when the point is the red-before/green-after proof (section 5), or through `aidw gate run smoke $SCOPE -- <focused command>` when the result is evidence to record. Do not claim tests passed unless they actually passed. If a check cannot run because it requires unavailable credentials or external dependencies, report it clearly and do not write a closing body that claims it passed unless the user explicitly accepts that limitation.

Inspect the final diff and check for accidental changes:

```bash
git diff --check
git diff --stat
git diff --
git status --short --untracked-files=all
```

### Pre-existing failures

If a broader check fails, reproduce that failure on the unmodified branch tip before attributing it to your change. Run that reproduction as a **bare command**, not through `aidw gate run`: the failure is expected there, and a recorded `failed` outcome is never cited. Report pre-existing failures and new failures separately, and never report a pre-existing failure as caused by your fix.

“Verification fails” in this prompt means **the selected issue’s acceptance checks fail** — not an unrelated, pre-existing failure elsewhere in the repository. An unrelated failure does not by itself make the fix wrong; it must be reported as a limitation in the closing body instead.

If the selected issue’s own acceptance checks fail, do not write a closing body, leave the issue `OPEN` and in progress, add a concise issue comment describing the failure, and stop. The workflow will not close it: a run that records no fixed issue closes nothing.

## 7. Write the closing comment body — leave the issue open

Only after implementation and acceptance checks pass.

Write the closing comment body to the file the workflow supplied. It is `$2`: an **absolute** path inside the run directory (`<run_dir>/artifacts/iter<N>-closing-body.md`), so write to it exactly as given — never to a `mktemp` file, and never to a path relative to the repository, which would put the body in the worktree and pollute the diff the commit stage pushes. Use a quoted heredoc so backticks, `$`, and apostrophes in the body stay inert:

```bash
body="$2"
: "${body:?the workflow supplies the closing-body path as $2}"
cat > "$body" <<'BODY'
Implemented on the current PR branch.

**Root cause.** ...

**Files changed**
- `path` — what changed

**Verification**
- `<exact command>` — passed
- `<exact command>` — 12 passed, 0 failed
- `reused: gate '<key>' passed for tree <id> at <time> by stage '<stage>' (<summary>)`
  — cited, not re-run

**Remaining limitations**
- ... or `None.`
BODY
```

The body must not begin with `Status: fixed`; that exact comment is posted separately by the close step so availability checks stay an exact-match test, and the script refuses a body that repeats it.

The closing comment must include the real verification results and any remaining limitation, including pre-existing failures you did not fix. Do not write results you did not observe. If the file is missing, empty, or starts with `Status: fixed` when the close step runs, the close fails and the run fails — the issue is never closed on a bad body, so write it and confirm it exists before you finish.

Preserve the child’s priority label and `review-follow-up` label. Do not remove `approve-fix` unless the repository workflow explicitly requires it. Do not use `Fixes #...` unless the user explicitly requests automatic PR linkage.

## 8. Verify the issue is still open and in progress

Re-read the selected issue:

```bash
python3 "$AIDW_SCRIPTS_DIR/review-followup/review_followup.py" select --pr "$pr"     # read-only
```

Confirm from its output:

- The selected issue is still `OPEN`.
- It carries an exact `Status: in progress` comment (so the next `select` skips it instead of re-fixing it) and no `Status: fixed` comment.
- The priority, `review-follow-up`, and `approve-fix` labels are intact.
- The closing body exists at `$2` and is non-empty.

The issue is **not** closed here, and `verify` reports it as not closed until the workflow’s close step has run — that is expected, not a failure.

If any check fails, report the exact mismatch. Do not process a second child in the same run. This prompt fixes exactly one next available issue per invocation.

## Final report

Report:

- PR number and canonical URL.
- Parent issue number and URL.
- Selected child issue number, URL, title, and priority.
- Children skipped and why.
- Files changed.
- Exact verification commands and their real results, naming the origin (key, tree, stage,
  timestamp) of any outcome cited from `aidw gate` rather than run.
- The absolute closing-body path you wrote, and confirmation that the issue is still `OPEN` with `Status: in progress` — the workflow posts `Status: fixed` and closes it after the push.
- Any remaining limitation or unverified check.

Do not claim that the PR is approved, merged, or fully complete, and do not claim the issue is closed. This prompt fixes one approved review follow-up issue per invocation and defers its close to the commit stage.

## Appendix: manual equivalents

Use these only if the toolkit's `prompts/scripts/review-followup/` scripts are unavailable. They require `jq`.

Find the parent by exact marker (external `jq`, because `gh api --slurp` cannot be combined with `--jq`):

```bash
repo="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
pr_url="$(gh pr view <pr-number-or-url> --json url --jq .url)"
# The repo's configured parent marker (github.markers.parent), rendered with the PR URL:
# take the template from the resolved config and substitute $pr_url — never retype it.
marker="<the configured parent marker, rendered with $pr_url>"
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

The close step (run by the workflow after the push, not by this prompt) posts a status comment from stdin and closes with a file-sourced body:

```bash
printf 'Status: fixed' | gh issue comment <child-number> --repo "$repo" --body-file -
gh issue close <child-number> --repo "$repo" --comment "$(cat "$body")"
```

`gh issue close` supports only `--comment`; it has no `--body-file`. Never write a comment body inline in double quotes — backticks would execute.
