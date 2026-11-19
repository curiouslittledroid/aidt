# Integration Test Guide — 05-P1.2: Close a follow-up issue only after its fix is pushed

## 1. What this guide covers

This is a hand-run procedure for branch `05-P1.2`, which moves the closing of a review
follow-up issue behind the `F5 commit-and-push` stage so `aidw fix` can no longer report an
issue fixed before its fix has been pushed. It walks the surfaces the change touches: the
repository's own validation tooling and the recorded failing guard test, the bundled
`review_followup.py` command line (its `--help` text, `close --dry-run`, and a real
`close`), the `aidw fix --pr <n>` workflow end to end (with the post-push close and the
deferred closing-body artifact), and the GitHub issue state a human confirms in a browser.

It is an instruction document only: nothing in it has been executed by the toolkit as part
of writing it, and no outcome below is claimed except the ones the build results already
record. Where the build results record a failure, this guide carries it as a failure.

Per the repo's configuration under `paths.implementation_results_dir`, the results for this
branch live in `docs/implementation-results/05-P1.2/`; the build evidence this guide cites
is `build-results.md` beside it.

---

## 2. Scenarios

### A. Repository's existing tooling

#### A1. Validate the changed prompt and agent context files

**Prerequisites**

- A checkout of this repository at branch `05-P1.2`, with `uv` installed.
- Dependencies synced (`uv sync --frozen`).
- No credentials and no GitHub access are needed for these commands.

**Command(s) or steps**

```bash
uv sync --frozen
uv run --frozen aidw prompts check
uv run --frozen aidw agents validate --strict
uv run --frozen aidw doctor
```

**Expected observable result**

- `prompts check` prints `resolved repo prompts: 0 error(s), 0 warning(s)`.
- `agents validate --strict` prints `11 agent config(s): 0 error(s), 0 warning(s)`. This also
  confirms that `agents/fixer/AGENTS.md`, referenced by the fixer agent config, still
  resolves (it does not judge the file's prose).
- `doctor` prints 21 checks with 0 failed. The build results record two warnings on the
  recorded tree — a dirty working tree and a missing `.mcp.json` — so warnings in that shape
  are consistent with the recorded run, not a failure.

**How to tell pass from fail**

Pass is every command exiting 0 and every summary line reading `0 error(s)` and `0 failed`.
Fail is any non-zero exit, any `error(s)` greater than 0, or a `doctor` line reporting a
failed check. Warnings alone are not a failure; read the counts, not the exit code alone.

**Cost, permission or destructive warning**

None. These commands are read-only against the checkout; `doctor` may read local config and
environment but writes nothing outside its own run state.

#### A2. Reproduce the recorded failing close-guard test

**Prerequisites**

- The checkout from A1, with dependencies synced.
- No GitHub credentials are used by this test (the script's GitHub access is faked in the
  test suite).

**Command(s) or steps**

```bash
uv run --frozen pytest -n0 \
  prompts/scripts/review-followup/tests/test_close.py::test_a_body_prefixed_by_the_status_marker_is_refused
```

**Expected observable result**

The build results record this test as **FAILING**: `1 failed, 2191 passed` in the full-suite
run, with `assert 0 == 2` at `prompts/scripts/review-followup/tests/test_close.py:260`. The
CLI is expected to refuse a closing body that begins `Status: fixed — verification details`
with exit 2 and make no GitHub call, but the recorded run returned exit 0 and reported
`"action": "closed"`, closing the issue. Running this selection alone should therefore
report `1 failed`, not `1 passed`.

**How to tell pass from fail**

The recorded, currently-true outcome is a test failure. If the test now passes, the recorded
failure is stale and the body guard has changed — that is a real difference from the build
results and must be investigated, not treated as an expected pass. If it fails with the same
`assert 0 == 2` shape, it reproduces the recorded defect.

**Cost, permission or destructive warning**

None. The test is local, uses a fake GitHub client, and makes no network calls.

### B. Custom CLI commands

#### B1. `review_followup.py` usage text and `close` argument handling

**Prerequisites**

- The repository checkout; Python 3.9+ available as `python3`.
- No `gh` authentication needed: the help text and argument errors are produced before any
  GitHub call.

**Command(s) or steps**

Run from the repository root, in order:

```bash
python3 prompts/scripts/review-followup/review_followup.py --help
python3 prompts/scripts/review-followup/review_followup.py close --pr 42 --body-file /tmp/close-body.md
```

**Expected observable result**

- The help text lists, among the other commands,
  `review_followup.py close   --pr <number-or-url> --issue <n> --body-file <path> [--dry-run]`
  and a note that `close` requires `--issue` and shares `fixed`'s guards.
- The second command, which omits `--issue`, prints
  `error: Missing --issue <number>. ...` on stderr and exits 2 **before** reading the body
  file or contacting GitHub. (The body path above need not exist because the `--issue` check
  runs first.)

**How to tell pass from fail**

Pass requires the `close` line in the help output and exit code 2 plus the `Missing --issue`
message for the second command. Fail is a help text without `close`, an exit code other than
2, or any attempt to read the body file or reach GitHub before the `--issue` refusal.

**Cost, permission or destructive warning**

None. The help path and the missing-`--issue` path perform no GitHub write.

#### B2. `close --dry-run` against a real pull request

**Prerequisites**

- An authenticated `gh` CLI (`gh` on `PATH` and logged in with read access to the target
  repository).
- A target repository containing a pull request whose review follow-up child issue is
  `OPEN`, carries the `review-follow-up` and `approve-fix` labels, and has an exact
  `Status: in progress` comment.
- A closing-body file that exists, is non-empty, and does **not** begin with a line equal to
  `Status: fixed` (for example `/tmp/close-body.md`). The body is read even in `--dry-run`.

**Command(s) or steps**

```bash
python3 prompts/scripts/review-followup/review_followup.py close \
  --pr <PR number> --issue <child issue number> --body-file /tmp/close-body.md --dry-run
```

**Expected observable result**

A JSON object on stdout with `"action": "dry-run"`, `"wouldClose": true`,
`"wouldComment": "Status: fixed"` when the exact marker comment is absent (or `null` when it
is already present), the `bodyFile` path, and an `issue` object for the named child. Exit
code 0. No comment is posted and the issue stays `OPEN`.

**How to tell pass from fail**

Pass is exit 0, `"action": "dry-run"`, and an unchanged issue afterwards (still `OPEN`, no
new `Status: fixed` comment). Fail is a non-zero exit, a different `action`, or any observable
change on the issue.

**Cost, permission or destructive warning**

Read-only against GitHub, but it does consume GitHub API calls and requires `gh`
authentication with access to the target repository. It writes nothing.

#### B3. `aidw fix --pr <n> --dry-run` plans the deferred-close run

**Prerequisites**

- `uv` and the synced checkout, plus an authenticated `gh` CLI for the read-only
  `review_followup.py select` the dry run performs when `gh` is available.
- A target repository and pull request reachable from the current directory, or pass the
  global `--repo` option before the subcommand (for example `aidw --repo <path> fix ...`).
- Pi does **not** need to be configured for a dry run.

**Command(s) or steps**

Run from the target repository (or with the global `--repo` option):

```bash
uv run --frozen aidw fix --pr 42 --dry-run
```

**Expected observable result**

- A `run:` line and a `pr: #42` line.
- Either `child:  #<n> <title> (<priority>)` with the inspected/total child counts, or
  `child:  none available`, or `child:  unknown (`gh` not found)`.
- A `select argv: ...` line.
- Planned stage lines for the iteration's approval plus `F1`–`F4`, then the post-loop `I7`
  and `F5` stage lines, then `gates (planned): approve-followups, approve-fix-pr`, a loop
  bound line, and finally
  `dry-run complete; Pi not invoked, no GitHub state written`. Exit code 0.

**How to tell pass from fail**

Pass is exit 0 and the final `dry-run complete; Pi not invoked, no GitHub state written`
line, with no issue comment or close performed. Fail is a non-zero exit, any Pi invocation,
or any GitHub write. Note that the close is not a stage: it has no id in the plan, so its
absence from the planned stage list is expected, not a failure.

**Cost, permission or destructive warning**

Requires `gh` authentication (read-only API use). It creates a local run directory and run
state on disk but performs no GitHub write and no push. See teardown.

### C. External actions (GitHub)

#### C1. A real `close` on one named issue

**Prerequisites**

- A disposable test repository, pull request, and open child issue with the
  `review-follow-up` and `approve-fix` labels and an exact `Status: in progress` comment.
  Do not use an issue whose closure history you care about.
- `gh` authenticated with **write** access to that repository.
- A closing-body file that exists, is non-empty, and does not start with an exact
  `Status: fixed` line, for example `/tmp/close-body.md`.

**Command(s) or steps**

1. Record the issue's current state (open, comments, labels) in the GitHub UI or with a
   read-only view.
2. Run:

```bash
python3 prompts/scripts/review-followup/review_followup.py close \
  --pr <PR number> --issue <child issue number> --body-file /tmp/close-body.md
```

3. Re-run the identical command once to check idempotency.
4. Verify the resulting state with the read-only `verify` subcommand:

```bash
python3 prompts/scripts/review-followup/review_followup.py verify \
  --pr <PR number> --issue <child issue number>
```

**Expected observable result**

- The first run exits 0 and prints JSON with `"action": "closed"`,
  `"statusCommentAdded": true` (or `false` if the exact `Status: fixed` comment already
  existed), and `"labelsIntact": true`; the issue is now `CLOSED`, carries exactly the
  `Status: fixed` marker comment, and has the closing body as its closing comment.
- The second run exits 0 with `"action": "none"` and
  `"reason": "ALREADY_CLOSED_AND_FIXED"`, posting nothing and changing nothing.
- `verify` exits 0 with `"passed": true` and a `checks` object whose `closed`,
  `hasStatusFixed`, `requiredLabelsPresent`, `hasPriorityLabel` and `hasDetailComment`
  entries are all `true`.

**How to tell pass from fail**

Pass requires all three: the first run's `"action": "closed"` with its labels intact, the
second run's `"action": "none"` (a conflict or a second comment is a fail), and `verify`
exiting 0 with `"passed": true`. A non-zero `close` exit, `"labelsIntact": false`, a missing
`Status: fixed` marker, or a duplicated marker comment is a fail.

**Cost, permission or destructive warning**

This is an **irreversible GitHub write**: it posts a comment and closes a real issue, which
is visible to everyone with access to that repository. It needs write scope on the target
repository. Use a disposable issue; reopening later leaves the posted `Status: fixed` comment
behind and can confuse later `select` runs.

#### C2. Full `aidw fix --pr <n>` run: push first, then close

**Prerequisites**

- A target repository whose pull request branch is an AIDT task branch, with at least one
  `OPEN`, approved review follow-up child issue (`review-follow-up` + `approve-fix` labels,
  a `Decision: approve-fix` comment, no `decision-pending` label).
- `gh` authenticated with **write** access to that repository; git credentials able to push
  the PR-head branch.
- Pi installed and configured, with a fixer model and a distinct re-review model (the run
  warns or fails with `--strict` when no distinct reviewer model exists).
- A clean, disposable working tree at the PR head; the run commits and pushes the change
  set it accumulates.

**Command(s) or steps**

1. From the target repository, run:

```bash
uv run --frozen aidw fix --pr 42 --max-iterations 5
```

2. Answer any interactive approval gate the run presents (approve using the default, or
   `--gate-default`/`AIDW_GATE_DEFAULT` if you deliberately want another meaning).
3. Note the `run:` line printed at the start; it names the run directory the artifacts and
   `run.log` are written to.
4. After the run, inspect the PR head and the issue in GitHub (see D1), and read the run's
   `run.log` and `state.json` in the run directory.

**Expected observable result**

- Per iteration, the approval stage, then `F1`–`F4`; then the post-loop `I7` roadmap tick
  (when this run's evidence is green) and `F5 commit-and-push`.
- A log line recording the push (the build results describe it as
  `stage <name>: pushed \`<sha>\` to \`origin/<branch>\``) **before** a close line of the
  shape `close: #<n> marked fixed and closed (<absolute body path>)`, and on stdout
  `close:  #<n> marked \`Status: fixed\` and closed after the push`, then
  `fix workflow complete`. Exit code 0.
- The recorded issue is `CLOSED` with an exact `Status: fixed` comment and the closing body;
  it was still `OPEN` with `Status: in progress` while `F1` ran.
- `state.json` records a `pr.head_sha` value and a `pr.closed_issues` entry whose
  `closing_body` is an **absolute** path inside the run directory (of the form
  `<run_dir>/artifacts/iter<N>-closing-body.md`), and that file exists and is non-empty.

**How to tell pass from fail**

Pass requires exit 0, the close line appearing **after** the push line in `run.log`, the issue
closed with exactly one `Status: fixed` comment and the recorded body, `pr.head_sha` present,
and the closing-body file existing at the absolute recorded path. Fail includes: exit 1 with a
message of the shape
`close failed for PR #<n> on branch \`<branch>\`: issue #<n> — ...`; the issue closed before the
push; an issue still open after a successful exit; or a `closing_body` path that is relative,
missing, or inside the repository worktree.

**Cost, permission or destructive warning**

This is the expensive scenario: it invokes Pi models (token cost), writes GitHub comments,
commits to and **pushes** the PR-head branch, and closes a real issue. It must not run against
a repository or branch you do not intend to modify. It never merges or force-pushes. Do not
run it on a shared PR without coordinating with the other users of that branch.

### D. Browser UI flow

#### D1. Confirm the issue stays open until the push and closes after it

**Prerequisites**

- A completed or in-progress `aidw fix` run from C2 (or a manual `close` from C1) on a
  repository whose issue pages you can open in a browser.
- A signed-in GitHub session with read access to the issue.

**Command(s) or steps**

1. During a run, after `F1` has finished and before the close, open the child issue page and
   read its state, comment timeline and labels.
2. After the run finishes, reload the same issue page.
3. Open the parent review-follow-up issue and read the child list.

**Expected observable result**

- Before the close: the issue is **Open**, its latest status comment is exactly
  `Status: in progress`, there is **no** `Status: fixed` comment, and the priority,
  `review-follow-up` and `approve-fix` labels are present.
- After the close: the issue is **Closed**, the timeline contains exactly one
  `Status: fixed` comment followed by the closing comment (the body written to the
  `iter<N>-closing-body.md` artifact), and the labels are unchanged.
- The parent issue's child list shows the child as completed/closed.

**How to tell pass from fail**

Pass is the two-state sequence: open with `Status: in progress` and no `Status: fixed` marker
before the push, then closed with exactly one `Status: fixed` marker and the closing body
after it. Fail is a `Status: fixed` comment or a closed state before the run's close step, a
duplicated `Status: fixed` marker, missing labels, or an issue left open on a successful run.

**Cost, permission or destructive warning**

None beyond browser access to the repository. Reading the page writes nothing; the writes
shown were performed by the scenarios above, not by this check.

---

## 3. Teardown

Do these after the scenarios, in order, so the environment returns to the state the guide
found it in:

1. **GitHub test data (irreversible).** The `close` scenario and the `aidw fix` run closed
   real issues and posted `Status: fixed` comments. If the test repository is disposable,
   delete the test pull request and its follow-up issues (or archive the repository). If you
   must keep them, do not silently reopen the issue: reopening leaves the `Status: fixed`
   marker behind, which later `select`/`close` calls read as "already fixed". Record what
   you left behind.
2. **Branches and PRs.** The `aidw fix` run committed and pushed to the PR-head branch. If the
   test branch was disposable, delete the branch and close the test PR through the GitHub UI.
   Do not force-push or reset a branch someone else may be using.
3. **Local run state.** Delete the run directories the dry run and the real run created
   (the `run:` line names each one), including their `artifacts/iter<N>-closing-body.md`
   files, `run.log` and `state.json`. These are machine-local run state and are never
   committed.
4. **Fixture files.** Remove any closing-body fixture you created (for example
   `/tmp/close-body.md`).
5. **Environment.** No scenario in this guide requires you to set an environment variable.
   If you set `AIDW_REPO`, `AIDW_STATE_DIR`, `AIDW_GATE_DEFAULT` or `AIDW_SCRIPTS_DIR` for a
   scenario, unset it. Confirm `git status` in the target repository is clean of anything the
   scenarios added.
6. **This repository.** Do not modify or revert the build results, summary, or this guide.
   The only file this procedure creates here is nothing.

---

## 4. Could not be exercised in this environment

- **Fail-closed with a pending close and no verified push.** The build results record this
  path as covered by automated tests (`tests/test_fix_workflow.py`'s fail-closed cases), but
  there is no user-facing flag on `aidw fix` to force `commit=False`, `push=False`, a dirty
  tree, or a discarded change set, so a human cannot reproduce it with a command. It would
  require an environment where the `pr-publisher` agent deliberately does not push, or a
  deliberately broken remote — neither is a normal developer environment. The guide therefore
  carries this path as test-covered only, exactly as the build results record it.
- **The recorded body-marker failure (A2).** The build results record
  `test_a_body_prefixed_by_the_status_marker_is_refused` as failing at
  `prompts/scripts/review-followup/tests/test_close.py:260` (`assert 0 == 2`, observed
  `"action": "closed"`). No environment makes that pass; the guide carries it as a recorded
  failure. A scenario using a body that begins `Status: fixed — verification details` against
  a real GitHub issue would close the issue, so it is deliberately not offered as a
  hand-run step.
- **A real end-to-end run without spend.** C2 requires Pi model invocations (token cost),
  write-scoped `gh` credentials, and permission to push a branch. It cannot be exercised
  offline, in a sandbox without Pi, or in a repository you only have read access to.
- **Cloud-provider or deployed-stack surfaces.** This change touches no cloud account,
  deployment, browser-only UI owned by the project, or paid third-party service beyond GitHub
  and Pi. There is no AWS (or other cloud) command surface in the changed files or build
  results to exercise.
- **`aidw doctor`'s `.mcp.json` warning.** The build results record a warning for a missing
  `.mcp.json` in the recorded tree. Whether your environment has that file is local
  configuration, not part of this change, so the guide does not assert its state.
