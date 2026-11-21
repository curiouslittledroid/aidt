# Integration Test Guide — 05-B1.1: Fix multiple approved follow-ups per iteration

## 1. What this guide covers

This is a hand-run procedure for exercising the 05-B1.1 change on branch `05-B1.1`: `aidw fix`
now fixes a bounded batch of approved review follow-ups per iteration (`--fix-batch`, default 3),
passes the run's resolved width to the fixer prompt as `F1`'s third positional variable
(`{fix_batch}`), posts one `Status: in progress` comment per child, writes one closing body per
issue under `<run_dir>/artifacts/iter{N}/closing-body-{issue}.md`, and makes one deferred
`close` call per recorded issue. It walks the bundled `review-followup` script's new
`select --limit`, the `aidw fix` dry-run preview, its flag refusals and the rendered `F1`
variables, the live fix loop's GitHub bookkeeping, and the existing pytest suite whose recorded
outcome includes one failure. The person reading this runs every step in their own environment
with their own GitHub credentials; **nothing in this guide has been executed by the toolkit**.
It is an instruction document, not a record of results.

Evidence boundaries taken from `build-results.md`: the recorded tree is `1a12b4b64fd4`; install,
build, test, doctor, agents-validate, prompts-check and whitespace are all recorded as passing;
the full suite is recorded as `2505 passed`, with no failing test; lint and per-file test subsets
are recorded as **unverified**; and the live-PR dry run is recorded as **unverified**. The
build results also state that the `suite` and `doctor` rows were reused from an earlier same-tree
gate rather than re-run by the recording stage. This guide does not convert any unverified row
into a pass.

---

## 2. Scenarios

### 2a. Repository tooling

#### Scenario 1 — Full pytest suite and the dry-run malformed-select guard

**Prerequisites**

- A checkout of `05-B1.1` with its dependencies installed.
- No `gh` access or credentials are needed for this scenario.

**Commands or steps**

```bash
uv sync --frozen
uv run --frozen pytest
uv run --frozen pytest tests/test_fix_workflow.py::test_dry_run_rejects_object_shaped_select_results
```

**Expected observable result**

- `uv sync --frozen` completes without modifying `uv.lock` (the lock is recorded as in sync).
- `pytest` reports 2505 tests and, per the build results at tree `1a12b4b64fd4`, exits `0` with
  `2505 passed`.
- The second command passes as part of that run: the dry-run preview shares the loop's fail-closed
  batch reader, so an object-shaped `selected` while `--limit` is passed is rejected (exit `1`,
  no `F1` planned), not normalised into a one-child batch.
- Every task-specific file (`test_logic.py`, `test_design_doc.py`, `test_stage_registry.py`,
  `test_plan_stages.py`, `test_prompt_neutrality.py`, `test_agent_guidance_neutrality.py`) is
  recorded as passing.

**How to tell pass from fail**

- Pass: `2505 passed`, exit `0`.
- Fail: any test is red. The recorded evidence has no failing test at this tree, so any failure is
  a new signal — including the dry-run rejection test, whose green result is what distinguishes a
  preview that fails closed from one that silently normalises a malformed `select` result.
- If the suite is green but you are on a different tree than `1a12b4b64fd4`, note the tree; this
  guide only carries the recorded tree's outcome.

**Cost, permission or destructive warning**

`none` — read-only with respect to GitHub. The suite creates temporary git repositories and run
state under a temporary root, and the repo's test guards refuse to leave `*-pytest-*` directories
behind.

### 2b. Custom CLI and bundled-script commands

#### Scenario 2 — `review_followup.py select --limit` returns an array

**Prerequisites**

- GitHub CLI authenticated: `gh auth login` (otherwise the script fails with "GitHub CLI is not
  authenticated. Run `gh auth login`.").
- A pull request whose head branch is the branch you have checked out, targeting `main` unless
  you pass `--allow-branch-mismatch` after confirming the exception.
- At least one open child issue under the PR's review follow-up parent issue, and at least one
  available child: labelled `review-follow-up` and `approve-fix`, no `decision-pending`, and no
  comment whose body is exactly `Status: in progress` or exactly `Status: fixed`.
- Run from the repository root. `aidw` sets `AIDW_SCRIPTS_DIR` for its own stages; a plain shell
  does not.

**Commands or steps**

```bash
python3 prompts/scripts/review-followup/review_followup.py select --pr <n> --limit 3
```

(Optional, to format the JSON: pipe the output through `python3 -m json.tool`.)

**Expected observable result**

- Exit status `0` when at least one child is available, `3` when the batch is empty.
- JSON with `selected` as an **array** of up to 3 children in native `subIssues` order, each entry
  carrying `number`, `title`, `url` and the priority/status fields the script emits.
- `skipped` lists the unavailable children encountered up to and including the last selected
  child.
- `childrenInspected` equals `len(skipped) + len(selected)`; `totalChildren` is unchanged by the
  flag.

**How to tell pass from fail**

- Fail if `selected` is a JSON object rather than an array while `--limit` is explicit, if
  `childrenInspected` differs from `len(skipped) + len(selected)`, or if a child after the batch
  appears in `skipped`/`childrenInspected`.
- Repeating with `--limit 1` must still yield a **one-element array**, never an object — the
  contract the fix loop depends on.

**Cost, permission or destructive warning**

`none` for writes — `select` is read-only. It spends GitHub API calls against your token and
counts against your rate limit.

#### Scenario 3 — `select` without `--limit` keeps the single-object shape

**Prerequisites**

- As Scenario 2. This is the contract `start`, `fixed` and `aidw fix`'s approval round keep.

**Commands or steps**

```bash
python3 prompts/scripts/review-followup/review_followup.py select --pr <n>
```

**Expected observable result**

- `selected` is a **single JSON object** (or `null` when nothing is available), not an array.
- Exit `0` with a selection, `3` when nothing is available.

**How to tell pass from fail**

- Fail if the flag-absent form returns an array. That would break the approval round's
  single-object read, which the build results record as deliberately unchanged.

**Cost, permission or destructive warning**

`none` for writes; GitHub API calls against your rate limit only.

#### Scenario 4 — `--limit 0` is refused and names `--limit`

**Prerequisites**

- As Scenario 2 (authentication and a resolvable PR); no available child is required for the
  refusal path.

**Commands or steps**

```bash
python3 prompts/scripts/review-followup/review_followup.py select --pr <n> --limit 0
```

**Expected observable result**

- Exit status `2` (usage error) with a message naming `--limit`, not `--issue`
  (`--limit must be a positive integer, got "0".`).

**How to tell pass from fail**

- Fail if the exit status is `0`, if any JSON selection is emitted, or if the message names
  `--issue` — the recorded change is specifically that the refusal names its own flag.

**Cost, permission or destructive warning**

`none` — refused before any GitHub write and before selection.

#### Scenario 5 — `aidw fix --dry-run --fix-batch 3` previews the whole batch

**Prerequisites**

- `gh` on `PATH` and authenticated (`gh auth login`); without it the preview prints
  `child:  unknown (`gh` not found)` instead of the children.
- A PR (`--pr <n>`) that exists, as the task prompt's Done-when requires.
- For a meaningful batch, approved and available children as in Scenario 2. A worktree for the
  PR head is **not** required: the dry run prints the planned `branch-setup` command instead.

**Commands or steps**

```bash
uv run --frozen aidw fix --pr <n> --dry-run --fix-batch 3
```

(`aidw fix ...` is also valid when the console script is on `PATH`, as the README shows.)

**Expected observable result**

- One `child:  #<number> <title> (<priority>)` line per child in the batch (three lines with
  three available children), then
  `children: <n> inspected of <total> (up to 3 per iteration)`.
- A line echoing the selection argv with the new flag, of the form
  `select argv: <python> <…>/review_followup.py select --pr <n> --limit 3`.
- `loop: bounded by --max-iterations=10 (iterations; up to --fix-batch=3 fixes each)`.
- The planned stages printed once each (`iter1-fix-next-review-followup`, `iter1-test`,
  `iter1-code-review`, the findings stage, the post-loop tick/commit), then
  `dry-run complete; Pi not invoked, no GitHub state written`, exit status `0`.
- No `artifacts/iter{N}/` directory is created and no GitHub state is written.

**How to tell pass from fail**

- Fail if only one `child:` line prints while several children are available, if `select argv:`
  omits `--limit 3`, if the loop line omits the batch wording, or if a real run directory /
  GitHub write appears.
- Compare the `child:` lines with Scenario 2's `selected` array: same children, same order.
- The malformed-result branch is **not** reachable from this preview while a live
  `select --limit` returns an array: the preview is recorded as sharing the loop's fail-closed
  reader, and the recorded
  `tests/test_fix_workflow.py::test_dry_run_rejects_object_shaped_select_results` passes at tree
  `1a12b4b64fd4`. The discriminating check for that branch is the unit-test seam in Scenario 1,
  not this hand-run.

**Cost, permission or destructive warning**

`none` for writes — no run state, no GitHub write, Pi not invoked, so no model spend. It still
reads from GitHub with your token (rate limit only).

#### Scenario 6 — `--fix-batch 0` is refused before any run state

**Prerequisites**

- A checkout of `05-B1.1`. For the strongest check, run from the control worktree where `main`
  is checked out and the tree is clean; the refusal is recorded as happening before any run
  record, worktree or stage, dry run included.

**Commands or steps**

```bash
uv run --frozen aidw fix --pr <n> --fix-batch 0
```

**Expected observable result**

- Exit status `2` and the message `--fix-batch must be positive.` on stderr.
- No run directory, no worktree, no stage, no Pi invocation, no GitHub write.

**How to tell pass from fail**

- Fail if the command exits `0`, starts a run, or prints a traceback. Repeat with `--fix-batch 1`
  to confirm the boundary is `<= 0` and that `1` is accepted as a one-child batch.

**Cost, permission or destructive warning**

`none` — refused before anything is created or written.

#### Scenario 7 — The run's resolved width reaches `F1` as the third variable

**Prerequisites**

- As Scenario 5: `gh` authenticated and a resolvable PR. A dry run is enough — this checks the
  rendered `F1` variables, not the agent's behaviour.

**Commands or steps**

```bash
uv run --frozen aidw --verbose fix --pr <n> --dry-run --fix-batch 1
```

`--verbose` is declared on the `aidw` application callback (`aidw/cli.py`), which is why it comes
before `fix`; it echoes the same run-log lines a real run writes to `<run_dir>/run.log`. If your
shell invocation differs, the equivalent real-run check is
`grep "prompt=fix-next-review-followup" <run_dir>/run.log` after a live run.

**Expected observable result**

- On stderr, the planned `iter1-fix-next-review-followup` stage emits a line of the form
  `... [INFO] prompt=<…>/fix-next-review-followup.md vars=['<pr>', '<run dir>/artifacts/iter1', '1']`.
- The third element is the resolved `--fix-batch` value, here `1`; with the default it is `3`.
- The dry run still ends with `dry-run complete; Pi not invoked, no GitHub state written`, exit
  status `0`.

**How to tell pass from fail**

- Fail if the `F1` line carries fewer than three variables, or if the third element is not the
  `--fix-batch` you passed (for example `3` when you passed `1`). The recorded change exists
  because nothing exports the width to the stage environment, so an implicit width would let
  `--fix-batch 1` be widened by the agent's own `select`.
- Fail if the same check shows the width inside the closing-bodies string rather than as its own
  third element.

**Cost, permission or destructive warning**

`none` for writes — the dry run creates no run directory and writes no GitHub state. It reads the
PR and children through `gh` (rate limit only), and Pi is not invoked.

### 2c. Browser UI flows

No changed file, build-results row or task-prompt statement points at a browser surface. This
change is CLI-, GitHub-issue- and prompt-level only, so there is no browser scenario to run.

### 2d. External actions — GitHub writes from a live fix run

#### Scenario 8 — A live `aidw fix` run batches fixes and closes one issue per entry

**Prerequisites**

- `gh` authenticated with permission to comment on and close issues and to read the PR in the
  target repository.
- A PR targeting `main` whose head branch has a worktree. If the worktree is missing, the run
  refuses with `branch-setup refused: no worktree for '<branch>'`; the dry run prints the exact
  `branch-setup (planned): git -C … worktree add -b … …` command, and that printed command is
  the one to use — do not construct one by hand.
- At least three approved, available child issues (labels `review-follow-up` and `approve-fix`,
  no `decision-pending`, no `Status: in progress`/`Status: fixed` comment), in native `subIssues`
  order so the ordering check is meaningful.
- Pi configured with a fixer model and a reviewer model that differ; otherwise the run warns and,
  with `--strict`, refuses.
- No other fix run for the same branch still marked `running` (the workflow refuses with exit
  `4`).

**Commands or steps**

```bash
uv run --frozen aidw fix --pr <n> --fix-batch 3
```

Then inspect the PR-head worktree and the run state:

```bash
git status --short
git diff
```

and read the run's `state.json`, its `run.log`, and the closing-body files under
`<state root>/runs/<run_id>/artifacts/iter1/`, plus the issue threads on GitHub.

**Expected observable result**

- One `fix:    #<number> <title> (<priority>)` line per child in the batch, in the order
  Scenario 2 returned them.
- `<run_dir>/run.log` shows the `iter1-fix-next-review-followup` line with three variables: the
  PR, the absolute `artifacts/iter1` directory, and the batch width.
- The workflow creates `<run_dir>/artifacts/iter1/` **before** `F1`; the fixer writes one
  `closing-body-<issue>.md` per child there (never into the worktree).
- Exactly one `F1`, one `F2` (`iter1-test`) and one `F3` (`iter1-code-review`) for the batch —
  never one set per child.
- Each batch child receives the exact comment `Status: in progress` (one `start` per child, in
  selection order) and is left `OPEN` by the fixer.
- `state.json`'s `closed_issues` holds one entry per batch issue, each with its own
  `closing_body` path under `artifacts/iter1/`.
- After `F5` verifies the push, one `review_followup.py close --issue <n> --body-file <path>`
  call per entry runs; each issue receives the exact `Status: fixed` comment and is closed.
- The recorded fixer-guidance guard passes: `agents/fixer/AGENTS.md` names `$3` and keeps the
  batch wording. That is a static check, not evidence that a real model honours the width — if
  the fixer ignores `$3` or fixes only the first child, record it as an observation; the build
  results record no live run that would confirm or refute it.

**How to tell pass from fail**

- Fail if only one `fix:` line prints while Scenario 5's preview showed several children.
- Fail if three `F1`/`F2`/`F3` sets run instead of one set over the batch.
- Fail if `closed_issues` holds one entry (or a count) instead of one per batch issue, or if one
  `close` call closes a whole batch.
- Fail if any issue is closed while `F5`'s push was not verified.
- Pass requires all of: the batch printed, `F1` carrying three variables, per-issue
  `closed_issues`, and one `close` call per entry after a verified push.

**Cost, permission or destructive warning**

**Destructive and irreversible in GitHub.** The run posts `Status: in progress` comments,
commits and pushes the PR-head branch, posts `Status: fixed` and closes issues. A close is not
reversible through the workflow — a wrong one must be reopened by hand. It spends model tokens
for the fixer, tester and code-reviewer stages and uses your GitHub token's write scope. Run it
on a disposable PR, not one you need pristine.

#### Scenario 9 — A failing `F2` fails a whole batch closed (live)

**Prerequisites**

- Everything from Scenario 8, on a throwaway PR/branch you are willing to break, with at least
  three approved children whose combined fix can be made to fail verification deliberately.
  The guide cannot give a confirmed command to make a real model's fix fail: that depends on the
  code and the tester, so this scenario stays **unconfirmed as a live procedure**. The behaviour
  is pinned by `tests/test_fix_workflow.py`, recorded as passing within the full-suite run.

**Commands or steps**

```bash
uv run --frozen aidw fix --pr <n> --fix-batch 3
```

then, after a red `iter1-test`, inspect `state.json`, the issue threads and `git status` in the
PR-head worktree.

**Expected observable result**

- The run exits non-zero.
- `state.json` has no `closed_issues` entry for the failed batch.
- No child is closed; every child in the batch is `OPEN` with exactly `Status: in progress`.
- `F5` does not commit or push the batch's change set, and no `close` call runs for it.

**How to tell pass from fail**

- Fail if any subset of the batch is closed, if `closed_issues` carries a partial batch, or if
  the run reports success after a red `F2`.
- Fail if children are auto-reopened or auto-closed by the workflow — the recorded design keeps
  the resume path (`start --issue`) as the recovery.

**Cost, permission or destructive warning**

**Destructive**: the same GitHub writes and model spend as Scenario 8, plus a deliberately red
test run and a dirty PR-head worktree you must clean up yourself. Do it only on a disposable PR.

---

## 3. Teardown

- Scenarios 1–7 create no persistent state: no branches, no worktrees, no fixtures, no
  environment variables, no GitHub writes, no run directories. Delete nothing beyond any
  `python3 -m json.tool` output you may have redirected to a file.
- Scenario 8/9, if you ran it live:
  - Reopen any issue the run closed that should not be closed, and delete the
    `Status: in progress` / `Status: fixed` comments you do not want to keep. These are manual
    GitHub actions; the workflow records no undo.
  - Revert the pushed commit on the disposable PR's head branch with your normal git process
    (AIDT never force-pushes or merges for you). If you want the worktree gone, remove it with
    your normal `git worktree` cleanup, using the path the dry run printed — this guide does not
    invent a removal command.
  - Delete the run's machine-local state under `<state root>/runs/<run_id>/` only if you are
    finished inspecting it; deleting it destroys the `state.json`, `run.log` and closing-body
    evidence the checks above rely on. Run state is never committed.
  - Unset nothing: this change introduces no environment variable of its own. `AIDW_SCRIPTS_DIR`
    is set per stage by `aidw` and was never exported by this guide.
- No deployed resource, cloud account or paid service is created by any scenario here.

## 4. Could not be exercised in this environment

- **Live `aidw fix --pr <n> --dry-run --fix-batch 3` against a real PR** — recorded as
  **unverified** in `build-results.md` for the recorded reason: "no PR, no GitHub credentials or
  live approved children were used in this recording stage; the dry-run contract is covered by
  the automated tests only". This guide carries that row as unverified. It needs a developer
  machine with `gh auth login` and a PR carrying approved children.
- **Live batch loop, per-issue closes and per-issue closing bodies (Scenarios 8–9)** — only
  `tests/test_fix_workflow.py` records them; the build results record no live run. Exercising
  them needs a disposable PR in a repository you can write to, plus model spend for the
  fixer/tester/code-reviewer stages.
- **A real model's behaviour under the batch prompt** — cannot be exercised without invoking Pi
  against a paid model. The build results record the fixer-guidance guard passing (it names
  `$3`), but that is a static text check: no live run records whether a fixer model actually
  honours `$3`, fixes every child in the batch, and writes one body per issue.
- **A malformed (object-shaped) `select` result from a live run** — cannot be produced by hand
  while `review_followup.py select --limit` returns an array. The preview's fail-closed branch is
  exercised only by the unit-test seam in `tests/test_fix_workflow.py`, which injects a faked
  single-object result; that test is recorded as passing at tree `1a12b4b64fd4`, and this guide
  does not claim a live reproduction.
- **Lint / formatter / type-check** — recorded as **unverified** because this repository
  configures none (`AGENTS.md` states pytest is the only verification), so there is no command to
  run. Carried here as unverified.
- **Per-changed-file test subsets** — recorded as **unverified** because the single `-q`
  full-suite run does not report per-file counts and the suite was not re-run (the same-tree gate
  was reused). Carried here as unverified.
- **Cloud-provider (for example AWS) commands** — none. No changed file, build-results row or
  task-prompt statement points at a cloud surface; the only external writes here are GitHub.
- **Browser UI** — none, as stated in section 2c.
- **Deliberately failing a live batch (Scenario 9)** — the procedure is described but remains
  **unconfirmed as a live recipe**: forcing a real tester failure depends on code and model
  behaviour this guide cannot confirm against the tree. It is covered only by the automated tests
  the build results record.
