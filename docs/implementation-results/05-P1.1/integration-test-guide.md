# Integration Test Guide — 05-P1.1: `F5 commit-and-push` in `aidw fix`

**Branch:** `05-P1.1`

This is a hand-run procedure. Nothing in it has been executed by the toolkit or by the stage that
wrote this guide; the build results record what was actually run, and the commands below are for
a human to run in their own environment with their own credentials.

## 1. What this guide covers

This procedure exercises the `05-P1.1` change that adds `F5 commit-and-push` to `aidw fix`: after
the review/fix loop converges, the `pr-publisher` agent commits the accumulated change set and
pushes it to the PR-head branch, and AIDT verifies that the pushed head landed before recording
`state.pr["head_sha"]`. The guide walks the repository-tooling surfaces (`aidw prompts check`,
`aidw agents validate --strict`, the focused drift-checked tests), the `aidw fix` CLI (dry-run,
live publish, recorded skips, and a stopped loop), and the external git/GitHub action that the
new stage performs. There is no browser UI surface in this change.

The repository is this checkout unless a step says otherwise. Examples use PR `42` and the
worktree path printed by `aidw worktree list`; substitute the PR and worktree you are actually
testing. Run the `uv` commands from the repository root. Where a step says "state root", use the
state root printed by `uv run --frozen aidw doctor`.

## 2. Scenarios

### Repository tooling

#### 2.1 Prompt inventory and the `pr-publisher` prompt carve-out

**Trace:** `prompts/fix-commit.md` (created), `aidw/inventory.py` (`REQUIRED_PROMPTS`),
`agents/pr-publisher/AGENTS.md` (modified); build-results rows for `aidw prompts check`,
`aidw agents validate --strict`, and the prompt/agent contract.

**Prerequisites**

- A working checkout of this branch with the development environment installed
  (`uv sync --frozen` has been run).
- No GitHub account, cloud credentials or Pi model access are needed for these checks.

**Command(s) or steps**

```bash
uv run --frozen aidw prompts check
uv run --frozen aidw agents validate --strict
grep -n "gh pr create" prompts/fix-commit.md
grep -n "backfill" prompts/fix-commit.md
```

Then read `agents/pr-publisher/AGENTS.md` and confirm it has a `/fix-commit` rule that says
commit and push **only**, with no `gh pr create`, no PR body sections, no build-results edit and
no merge.

**Expected observable result**

- `aidw prompts check` exits 0 and reports `resolved repo prompts: 0 error(s), 0 warning(s)`.
  The build results record that `fix-commit.md` resolves to the toolkit default.
- `aidw agents validate --strict` exits 0 and reports
  `11 agent config(s): 0 error(s), 0 warning(s)`.
- Both `grep` commands print nothing.
- The agent file contains the `/fix-commit` carve-out.

**How to tell pass from fail**

Pass means both `aidw` commands exit 0 with zero errors, both `grep` commands have no match, and
the agent file visibly scopes its rules by prompt. A non-zero exit, any warning/error count
above zero, a `gh pr create` match, a `backfill` match, or an agent file that still tells
`/fix-commit` to open a PR is a failure.

**Cost, permission or destructive warning:** none. These are local read-only checks.

#### 2.2 Focused stage-catalog and documentation drift tests

**Trace:** the six named test files changed by the task and the build-results focused-test row.

**Prerequisites**

- The development environment is installed with `uv sync --frozen`.
- No GitHub, cloud or model credentials are needed; these tests use fixtures and fakes.

**Command(s) or steps**

```bash
uv run --frozen pytest \
  tests/test_fix_workflow.py \
  tests/test_stage_registry.py \
  tests/test_plan_stages.py \
  tests/test_inventory.py \
  tests/test_design_doc.py \
  tests/test_workflow_stages_doc.py
```

**Expected observable result**

All selected tests pass and pytest exits 0. The build results record `284 passed in 17.21s` for
this selection against the implementation tree; a re-run should report no failures.

**How to tell pass from fail**

Pass means pytest exits 0 with zero failures and zero errors. Any failure, error or collection
error is a fail; inspect which of the six files failed rather than treating the whole run as a
single result.

**Cost, permission or destructive warning:** none. The tests use temporary repositories and
fixtures and do not touch GitHub or a model provider.

### Custom CLI commands (`aidw fix`)

#### 2.3 Plan the post-loop stages with `--dry-run`

**Trace:** `aidw/stage_registry.py` (`F5` in `_FIX.post_loop`), `aidw/workflows/fix.py` (`--dry-run`
post-loop block), and the build-results "Task dry-run" row.

**Prerequisites**

- `gh` is installed and authenticated enough to read the PR, because the dry run still performs
  the read-only `review_followup.py select` and `gh pr view` reads.
- A pull request number that exists and targets `main`. The build results used merged PR `#156`
  as a stand-in because this branch has no PR; for your own check use a PR you can read.
- No Pi model is invoked, but the dry run writes a run record to the state directory.

**Command(s) or steps**

```bash
AIDW_STATE_DIR="$(mktemp -d)" uv run --frozen aidw fix --pr 42 --dry-run
```

Keep the printed temporary directory path so it can be removed in teardown.

**Expected observable result**

The command prints the run and PR, the selected child (or `child: none available`), the planned
`F1`–`F4` stages, then one `update-roadmap` line and one `commit-and-push` line, in that order.
The `commit-and-push` line carries `(planned)` and is printed exactly once; its status is the
dry-run status. The build results observed `update-roadmap [skipped]` followed by
`commit-and-push [succeeded] (planned)` exactly once after it for the stand-in PR. The run ends
with `dry-run complete; Pi not invoked, no GitHub state written` and exits 0.

**How to tell pass from fail**

Pass means there is exactly one `commit-and-push` line, it appears after the `update-roadmap`
line, it carries `(planned)`, the final dry-run line is present, and the exit status is 0. Zero
`commit-and-push` lines, more than one, a line before `update-roadmap`, a missing final line, or
a non-zero exit is a failure. The exact status of `update-roadmap` may be `planned` or `skipped`
depending on whether the PR resolves to a roadmap target; that difference is not the
discriminator.

**Cost, permission or destructive warning:** no model spend and no GitHub writes; the command
still performs read-only GitHub reads and writes a local run record under the temporary state
directory. Do not use `--dry-run` as evidence that a live push works.

#### 2.4 Live run: a converged fix publishes its commit and tick

**Trace:** `aidw/workflows/fix.py` D3's commit case and D6's verification, `prompts/fix-commit.md`,
and the build-results D3 case 1 / D6 rows.

**Prerequisites**

- A controlled or disposable pull request that targets `main` and has at least one approved open
  review follow-up child for the loop to fix.
- The PR-head worktree exists. Find it with `aidw worktree list`; the PR head is authoritative,
  not the control checkout's current branch.
- `gh` is installed and authenticated with permission to read the PR, its issues and their
  review state.
- Pi is installed and configured with usable model credentials, and the tester/code-review
  models differ from the fixer model (or you have deliberately accepted the warning).
- The target repository configuration resolves cleanly and `aidw doctor` reports the workspace
  root, state root and control worktree as `ok`.
- The PR-head worktree must not contain unrelated uncommitted files. The new stage runs
  `git add -A`, so a successful publish commits everything in that worktree, not only the fix.

Before running, capture the state you will compare against:

```bash
aidw worktree list
WT=/absolute/path/printed/beside/the/PR-head/branch
git -C "$WT" branch --show-current
git -C "$WT" rev-parse HEAD
git -C "$WT" status --short --untracked-files=all
```

**Command(s) or steps**

Run the live workflow from the repository root, approving only the gates you intend to approve:

```bash
uv run --frozen aidw fix --pr 42
```

`--yes` exists and approves all gates, but do not use it unless you intend to approve every gate.
If the command reports that no worktree exists for the PR head, create it with the exact
`git worktree add` command the workflow prints, then rerun.

**Expected observable result**

- The loop runs its approval, fix, test and re-review stages and reaches the post-loop half.
- `update-roadmap` runs or is recorded as skipped, then `commit-and-push` runs and is recorded
  as `succeeded`.
- The run exits 0 and prints `fix workflow complete`, followed by `closed: #...` for each issue
  this run closed.
- In the PR-head worktree, `git status --short --untracked-files=all` is clean after the run.
- `git -C "$WT" rev-parse HEAD` equals `git -C "$WT" rev-parse origin/<PR-head-branch>`, and the
  new commit's subject is a conventional-commit subject with the task id when one is known.
- The run's `state.json` contains `pr.head_sha` equal to that same SHA and does not contain a
  `pr.commit_skip_reason`.
- `uv run --frozen aidw runs list` shows the new fix run; `uv run --frozen aidw runs show <run-id>`
  lists `commit-and-push` as a stage without an error.

**How to tell pass from fail**

Pass requires the exit status 0, a `commit-and-push` stage recorded as succeeded, a clean tree,
`HEAD == origin/<branch>`, and `pr.head_sha` present and equal to that remote SHA. A skipped
`commit-and-push`, a non-zero exit, a dirty tree after the run, unequal `HEAD` and
`origin/<branch>`, or a missing/incorrect `head_sha` is a failure. Do not treat the agent's
success message alone as a pass.

**Cost, permission or destructive warning:** this scenario spends model-credit money, writes to
GitHub by closing follow-up issues and approving review state, commits every change in the
PR-head worktree (including unrelated uncommitted files), and pushes a new commit to the remote
PR branch. A pushed commit is hard to reverse in a shared repository; use a disposable PR and do
not force-push or reset a shared branch. Use teardown below.

#### 2.5 Dirty worktree with nothing closed is a recorded skip

**Trace:** `aidw/workflows/fix.py` D3 case 2 (`COMMIT_SKIP_DIRTY_UNOWNED`) and D7's
`commit_skip_reason`.

**Prerequisites**

- A pull request that targets `main` but has **no** approved open review follow-up child, so the
  loop closes nothing.
- The PR-head worktree is otherwise clean and is safe to make temporarily dirty.
- Same `gh`, Pi and configuration prerequisites as scenario 2.4.

**Command(s) or steps**

```bash
aidw worktree list
WT=/absolute/path/printed/beside/the/PR-head/branch
git -C "$WT" status --short --untracked-files=all
printf 'local integration-test scratch file\n' > "$WT/aidw-integration-test-scratch.txt"
git -C "$WT" rev-parse HEAD
uv run --frozen aidw fix --pr 42
```

**Expected observable result**

The loop finds no approved child and closes no issue. `update-roadmap` is skipped, and
`commit-and-push` is recorded as skipped with the reason
`this run closed no issue; the working-tree changes are not this run's`. The run exits 0.
`HEAD` before and after is unchanged, the scratch file is still an uncommitted/untracked file,
and `state.json` contains `pr.commit_skip_reason` with that reason and no `pr.head_sha`.

**How to tell pass from fail**

Pass means exit 0, `commit-and-push` recorded as skipped with that exact unowned-dirt reason,
`HEAD` unchanged, the scratch file still uncommitted, and no `pr.head_sha`. Any new commit, a
pushed change, a committed scratch file, or a failed run is a fail. This is the boundary that
protects unrelated user changes, so a committed scratch file is a serious failure.

**Cost, permission or destructive warning:** the approval stages may invoke models and spend
model credit even though there is no approved child; check the run output and your provider
usage. No intended GitHub write occurs, but do not allow unrelated work into the worktree. The
scratch file is a local file only.

#### 2.6 Clean worktree with nothing closed is a successful no-op

**Trace:** `aidw/workflows/fix.py` D3 case 3 (`COMMIT_SKIP_CLEAN_NOOP`).

**Prerequisites**

- A pull request that targets `main` with no approved open review follow-up child.
- The PR-head worktree is clean before the run.
- Same `gh`, Pi and configuration prerequisites as scenario 2.4.

**Command(s) or steps**

```bash
aidw worktree list
WT=/absolute/path/printed/beside/the/PR-head/branch
git -C "$WT" status --short --untracked-files=all
git -C "$WT" rev-parse HEAD
uv run --frozen aidw fix --pr 42
```

**Expected observable result**

The loop closes nothing. `commit-and-push` is recorded as skipped with the reason
`this run closed no issue and the working tree is clean, so there is nothing to commit`. No empty
commit is created, no push occurs, `HEAD` is unchanged, `state.json` contains
`pr.commit_skip_reason` and no `pr.head_sha`, and the run exits 0.

**How to tell pass from fail**

Pass means exit 0, the clean no-op skip reason, an unchanged `HEAD`, and no `pr.head_sha`. Any
new commit, any push, or a non-zero exit is a fail.

**Cost, permission or destructive warning:** the approval stages may invoke models and spend
model credit even though there is no approved child. No intended commit or push occurs.

#### 2.7 Denied `approve-fix-pr` gate stops before publishing

**Trace:** `aidw/workflows/fix.py` D4's `stop()` path and the build-results D4 row.

**Prerequisites**

- A controlled or disposable PR with an approved child that will produce a fix and reach the
  `approve-fix-pr` gate.
- Same `gh`, Pi and configuration prerequisites as scenario 2.4.
- Understand that this scenario deliberately stops after the fixer may already have closed the
  follow-up issue, while the fix remains unpushed. Use a disposable PR and issue only.

**Command(s) or steps**

```bash
uv run --frozen aidw fix --pr 42 --deny-gates approve-fix-pr
```

**Expected observable result**

The run reaches the `approve-fix-pr` gate and prints a denial, then stops with exit 3. Both
`update-roadmap` and `commit-and-push` are recorded as skipped with the same stopped-loop reason
(the reason names the `approve-fix-pr` gate). No commit is created, no push is attempted,
`HEAD` and `origin/<PR-head-branch>` are unchanged, and `state.json` has no `pr.head_sha`.

**How to tell pass from fail**

Pass means exit 3, both post-loop stages recorded as skipped with the same stop reason, and no
new commit or remote head change. A commit, a push, a missing `commit-and-push` skip record, or a
different exit status is a fail.

**Cost, permission or destructive warning:** model spend occurs during the loop; the fixer may
close a GitHub follow-up issue even though its changes are not pushed, leaving an issue closed
without a corresponding published fix. Use a disposable PR/issue and do not run this against
work you cannot repair. Do not force-push or discard the unpushed worktree changes.

### External actions (git and GitHub)

#### 2.8 Inspect the pushed commit on the pull request

**Trace:** `prompts/fix-commit.md`'s commit/push instructions and the successful live run in
scenario 2.4.

**Prerequisites**

- Scenario 2.4 completed successfully and produced a known PR-head branch and commit SHA.
- `gh` is authenticated read-only is sufficient for this scenario.

**Command(s) or steps**

```bash
aidw worktree list
WT=/absolute/path/printed/beside/the/PR-head/branch
git -C "$WT" branch --show-current
git -C "$WT" log -1 --format='%H%n%s'
git -C "$WT" rev-parse origin/<PR-head-branch>
gh pr view 42 --json number,url,state,baseRefName,headRefName
```

**Expected observable result**

The branch printed by git is the PR head branch; `git log -1` shows the commit subject created by
the run and its full SHA; `git rev-parse origin/<PR-head-branch>` prints the same SHA; and
`gh pr view` reports the same PR, still open, with `baseRefName` equal to `main` and
`headRefName` equal to that branch. The PR should not have gained a second, newly created PR.

**How to tell pass from fail**

Pass means the local `HEAD` SHA, the `origin/<branch>` SHA and the commit just inspected agree,
and the PR metadata names the expected head branch and `main` base. A mismatch, a closed PR, a
different head branch, or a new PR created by `fix` is a failure.

**Cost, permission or destructive warning:** none for the inspection itself; `gh pr view` is a
read. The underlying push in scenario 2.4 is the hard-to-reverse action and is covered by that
scenario's warning.

## 3. Teardown

- Delete the scratch file from scenario 2.5:
  `rm "$WT/aidw-integration-test-scratch.txt"` (adjust the worktree path).
- Remove the temporary state directory created for scenario 2.3 and any state directories created
  for a disposable live run. They are local files and can be removed with `rm -rf` on the
  temporary path you created; do not remove a state root you did not create.
- If you used a disposable PR, close it through the GitHub UI. The tree contains no PR-close
  command, so no `gh pr close` invocation is given here. Do not force-push, reset or rewrite a
  shared branch. If the live run already pushed commits you want to undo, add an explicit revert
  commit and push it rather than deleting history.
- Reopen or otherwise correct any GitHub issue that scenarios 2.4 or 2.7 closed if that issue was
  not genuinely fixed. Scenario 2.7 can leave an issue closed with an unpushed fix.
- Remove any disposable PR-head worktree with
  `uv run --frozen aidw worktree remove <PR-head-branch>` after it is clean. This command refuses a
  dirty worktree rather than discarding changes.
- Unset any shell variables you created for the worktree path and PR number.
- The repository-tooling scenarios create no GitHub, cloud or deployed resources. The dry-run
  scenario creates only a local run record under its temporary state directory.

## 4. Could not be exercised in this environment

- **A live `aidw fix` run against this branch's own pull request.** The build results record that
  `05-P1.1` had no pull request yet; the task dry run used merged PR `#156` as a stand-in and did
  not exercise this branch's own PR. Exercise scenarios 2.4–2.8 only after `/pr` has opened a real
  PR for this branch. Environment needed: a GitHub pull request targeting `main` with an AIDT
  PR-head worktree and approved review follow-ups.
- **Real Pi model invocation and model-credit spend.** The build results record a dry run that did
  not invoke Pi and fixture-based tests that fake the model calls. A human with Pi installed and
  provider credentials must run the live scenarios; this environment did not.
- **The fail-closed edges that require fault injection.** A push that reports success but leaves
  `origin/<branch>` behind, a non-`SUCCEEDED` `F5` stage, a tree that is still dirty after the
  stage, a PR head that resolves to the base branch, and unresolvable `HEAD`/`origin` refs cannot
  be produced safely by hand without fabricating a broken remote or agent. The build results record
  these as passing through test fixtures, not through a live integration run. Environment needed: a
  disposable repository with a controllable remote and a test harness that can inject the failure.
- **A deployed stack, production-only account, paid cloud service or hardware.** This change
  touches no AWS/cloud resource, deployed service, browser UI or hardware, so no such environment
  applies.
- **Recorded `unverified` rows.** The build results contain no row marked `unverified`; the only
  recorded caveat is that the dry-run used a stand-in PR because this branch had no pull request,
  and that limitation is carried above rather than rounded into a pass.
