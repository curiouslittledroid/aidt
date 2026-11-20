# Integration Test Guide — 05-W1.2

**Branch:** `05-W1.2`
**Build results:** `docs/implementation-results/05-W1.2/build-results.md`
**Task prompt:** `docs/task-prompts/05-W1.2-prompt.md`
**Design decision:** `design.md` §17 row `Z14`, §19 items 8–10

## 1. What this guide covers

This is a hand-run procedure for exercising the W1.2 rule on branch `05-W1.2`: a
`--dry-run` creates no run state at all — no run directory, no `state.json`, no `run.log`,
no `prompts/<stage>.rendered.md`, no stage record — so the runs tree is byte-identical
before and after and no later `--resume` can attach to a run that never invoked Pi. The
procedure walks the five workflows (`implement`, `prompt`, `approve-followups`, `review`,
`fix`), the shared `aidw exec` seam, the one-run-per-worktree lock that must still refuse
during a dry run, the re-baselined test contract, and the design-document wording the task
requires.

**This is a hand-run procedure, and nothing in it has been executed by the toolkit.** The
guide was written by reading the build results, the task prompt and the changed files; it
runs no command itself. Where a step needs credentials, a PR, or money, the scenario says
so. The build results record the full suite as passing (`2281 passed in 50.08s`, tree
`8200590de259`, cited from the `update-traceability` stage's recorded `suite` gate), and
record the build, lint and mutation checks as **unverified**; those recorded outcomes are
carried unchanged into the sections below.

## 2. Scenarios

### 2.1 Existing repository tooling

#### Scenario T1 — The re-baselined test contract

1. **Prerequisites**
   - Dependencies installed with `uv sync --frozen` (the build results record
     ✅ `Checked 19 packages in 1ms`).
   - Run from the target repository root, on a worktree that contains the thirteen changed
     test modules: `tests/test_runner.py`, `tests/test_cli.py`, `tests/test_state.py`,
     `tests/test_implement_workflow.py`, `tests/test_prompt_workflow.py`,
     `tests/test_approve_workflow.py`, `tests/test_review_workflow.py`,
     `tests/test_fix_workflow.py`, `tests/test_design_doc.py`,
     `tests/test_conventions_injection.py`, `tests/test_prompt_resolution.py`,
     `tests/test_override_integration.py` and `tests/test_plan_stages.py`.
   - No credentials, network, browser or cloud account is needed. `pytest` is the only
     configured verification (`AGENTS.md` §Tests); there is no build or lint gate.

2. **Command(s) or steps**
   ```bash
   uv run aidw gate run suite --ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv run --frozen pytest
   ```
   This is the exact recorded command. The `--ignore` flags cover document paths other
   stages write; `AGENTS.md` permits them only for such paths.

3. **Expected observable result**
   - Exit 0 and a green pytest summary.
   - The recorded outcome for this content is `2281 passed in 50.08s` (gate `suite`, tree
     `8200590de259`, stage `update-traceability`, 2026-11-20T04:44:02Z). The build results
     cite the gate as `reused:` for that tree rather than a second run.
   - A gate reuse notice (`reused: gate 'suite' passed ...`) is a valid result for an
     unchanged tree, not a skipped check.

4. **How to tell pass from fail**
   - **Pass:** exit status 0 and no `failed` line in the summary.
   - **Fail:** any non-zero exit or any failing test. The W1.2 tests below are the
     discriminating ones: `tests/test_runner.py`
     (`test_dry_run_does_not_persist_stage_state_or_rendered_prompt`,
     `test_run_stage_dry_run_does_not_recreate_a_toolkit_runs_tree`), `tests/test_cli.py`
     (`test_exec_dry_run_creates_no_run_and_prints_no_rendered_path`,
     `test_exec_dry_run_help_advertises_no_writes`, the real-run echo test),
     `tests/test_implement_workflow.py`
     (`test_dry_run_leaves_the_runs_tree_unchanged`,
     `test_dry_run_with_or_without_resume_preserves_existing_runs`),
     `tests/test_prompt_workflow.py`, `tests/test_approve_workflow.py`,
     `tests/test_review_workflow.py`, `tests/test_fix_workflow.py`,
     `tests/test_state.py` (`planned_run` pins), `tests/test_plan_stages.py`, and
     `tests/test_design_doc.py::test_w12_dry_run_decision_and_acceptance_wording_are_recorded`.
   - A test that fails only on a read of a written rendered-prompt file means the dry-run
     path still writes; a test that fails on `planned_run`'s literal id means the planned
     state helper drifted.

5. **Cost, permission or destructive warning**
   - No spend, credentials or remote writes. The suite spawns many temporary `git`
     repositories and takes about a minute. `aidw gate run` records an outcome in the run
     state under the configured state root; it does not modify the repository.

#### Scenario T2 — The design-document contract for the rule

1. **Prerequisites**
   - The repository tree on branch `05-W1.2`, with `design.md` present.
   - No credentials or services.

2. **Command(s) or steps**
   ```bash
   uv run --frozen pytest tests/test_design_doc.py -k w12
   ```
   Or read the two sections directly: the §17 row that names `05-W1.2` and `dry-run`, and
   §19 items 8, 9 and 10.

3. **Expected observable result**
   - The focused test passes.
   - Exactly one §17 row contains both `05-W1.2` and `dry-run`; that row is `Z14`, and it
     states the rule, `not resumable`, the null-logger/`planned_run` mechanism, the absence
     of a `run:` line, and the `<run dir>` planned paths.
   - §19 items 8–10 each contain the phrase `no run state`; item 8 also covers the peer-lock
     refusal, item 9 the `implement` stage plan, and item 10 `review`/`fix`/
     `approve-followups` plus `exec`.
   - §8.2 and §9.1/§9.4 state the no-run rule.

4. **How to tell pass from fail**
   - **Pass:** the focused test passes and both greps find exactly the expected text (one
     §17 row; `no run state` in each of items 8–10).
   - **Fail:** zero matching §17 rows, more than one, a re-used existing row, or any of
     items 8–10 missing `no run state`.

5. **Cost, permission or destructive warning**
   - `none`. This scenario only reads `design.md` and runs one focused test.

### 2.2 Custom CLI commands

Before the scenarios in this group, isolate the run store so the checks and teardown cannot
touch real operator state. `AIDW_STATE_DIR` is the state-base override read by
`aidw/paths.py`:

```bash
export AIDW_STATE_DIR="$(mktemp -d)"
uv run --frozen aidw config show
```

`aidw config show` prints `state root: <path> (<source>)`; record that path as
`STATE_ROOT` for the steps below. With the override set, `STATE_ROOT` is
`$AIDW_STATE_DIR/<repo-slug>`.

Two literals matter in every dry-run check. `aidw/state.py` defines
`PLANNED_RUN_ID = "<planned>"` and `PLANNED_RUN_DIR_TEXT = "<run dir>"`. No run is created
under either, and because `<run dir>` is a relative path, a stray write would land in the
working tree rather than under `runs/`.

#### Scenario C1 — `aidw implement <prompt> --dry-run` leaves the runs tree unchanged

1. **Prerequisites**
   - `AIDW_STATE_DIR` set as above and `STATE_ROOT` recorded.
   - The task prompt at `docs/task-prompts/05-W1.2-prompt.md` in the tree the command
     reads. Phase and task are derived from the prompt filename (`parse_task_id`).
   - The roadmap entry `W1.2` exists exactly once in `docs/tasks/05 - Pipeline efficiency.md`
     (the tick target is resolved from it; a missing or duplicated entry refuses with
     exit 2). No prior worktree or branch setup is required: a dry run prints the planned
     worktree and branch-setup command instead of creating them.
   - Record the run ids: `uv run --frozen aidw runs list`.

2. **Command(s) or steps**
   ```bash
   uv run --frozen aidw implement docs/task-prompts/05-W1.2-prompt.md --dry-run
   uv run --frozen aidw runs list
   ```
   Then check `STATE_ROOT/runs` for a new directory, `state.json`, `run.log` or
   `prompts/*.rendered.md`, and check that the repository working tree gained no literal
   `<run dir>` directory.

3. **Expected observable result**
   - Exit 0.
   - `worktree (planned): ...` and, when no worktree exists yet,
     `branch-setup (planned): ...`.
   - `branch: <branch>` and `prompt: <relative prompt path>`.
   - One plan line per stage in the retained-id form, for example
     `I1 impliment-task [succeeded] (planned) agent=<agent> model=<model>` and
     `I2 test [succeeded] (planned) ...`; the recorded test pins the full I1–I9 set
     (`I1`, `I2`, `I3`, `I4`, `I5`, `I8`, `I9`, `I7`, `I6` in plan order).
   - `gate (planned): approve-implementation-pr`.
   - `dry-run complete; Pi not invoked`.
   - **No `run:` line** — the dry run prints no run id (`Z14` decision d).
   - The `aidw runs list` output is unchanged; no new run directory, `state.json`,
     `run.log`, rendered prompt, or literal `<run dir>` directory exists.

4. **How to tell pass from fail**
   - **Pass:** exit 0, the plan and `gate (planned):` lines are printed, no `run:` line
     appears, and the run ids and bytes under `STATE_ROOT/runs` are identical before and
     after.
   - **Fail:** any new run id, a `run:` line, a new `state.json`/`run.log`/
     `prompts/*.rendered.md`, or a `<run dir>` directory in the tree. A plan that prints
     but also creates a run is a failure: the plan output alone does not satisfy W1.2.

5. **Cost, permission or destructive warning**
   - No model spend: the dry run invokes no Pi process. It does acquire the
     one-run-per-worktree lock and reads the tree and roadmap. Nothing is written to
     GitHub. Do not unset `AIDW_STATE_DIR` mid-scenario, or the check will read the real
     state root instead.

#### Scenario C2 — `--dry-run --resume` neither adopts nor becomes a resume target

1. **Prerequisites**
   - Everything from C1, plus at least one pre-existing real run in the isolated run store
     if you want to prove a resume-capable run is untouched. If the store is empty, the
     scenario still checks the weaker property that a dry run with `--resume` creates no
     run.
   - The guide provides no CLI command that creates a fake pre-existing run. The recorded
     test constructs one programmatically
     (`tests/test_implement_workflow.py::test_dry_run_with_or_without_resume_preserves_existing_runs`);
     alternatively use a real run you already have and do not want to touch.
   - Record the run ids first: `uv run --frozen aidw runs list`.

2. **Command(s) or steps**
   ```bash
   uv run --frozen aidw implement docs/task-prompts/05-W1.2-prompt.md --dry-run --resume
   uv run --frozen aidw runs list
   ```
   Compare the run ids and the `state.json` contents under `STATE_ROOT/runs` before and
   after.

3. **Expected observable result**
   - Exit 0, the same plan and `gate (planned):` output as C1.
   - No `resume:` confirmation block, no `completed stages:` block, and no `run:` line.
   - The run-id set is identical; every pre-existing `state.json` is byte-identical; no
     run records only planned/succeeded stages without having invoked Pi.
   - The in-memory planned id is the literal `<planned>`, which no code persists.

4. **How to tell pass from fail**
   - **Pass:** exit 0 and a byte-identical runs tree, with no new run id. The decisive
     check is that a later `--resume` cannot attach to anything new: if `runs list` gains
     an id, fail even when the plan output looks correct.
   - **Fail:** any new run id, any changed `state.json`, a printed `resume: <id>`/takeover,
     or a `run:` line.

5. **Cost, permission or destructive warning**
   - No spend in the dry run itself. Do **not** follow this scenario with a real
     `--resume` to "see it attach": that invokes Pi, spends model tokens and runs the real
     workflow. The guide does not ask you to do that.

#### Scenario C3 — `aidw prompt ... --dry-run` creates no run, worktree, branch or prompt file

1. **Prerequisites**
   - `AIDW_STATE_DIR` isolated and `STATE_ROOT` recorded.
   - Roadmap entry `05 / W1 / W1.2` present, with W1.1 already ticked (it is), so no
     incomplete-predecessor refusal occurs.
   - No network is needed: the dry run prints that a real run will fetch and verify the
     base branch, and performs no fetch.
   - Record the run ids and worktree list:
     ```bash
     uv run --frozen aidw runs list
     git worktree list
     ```

2. **Command(s) or steps**
   ```bash
   uv run --frozen aidw prompt 05 W1 W1.2 --dry-run
   uv run --frozen aidw runs list
   git worktree list
   ```
   Confirm `docs/task-prompts/05-W1.2-prompt.md` still exists with the same content (the dry
   run must not author or overwrite it).

3. **Expected observable result**
   - Exit 0.
   - `[dry-run]` notice lines, including the base-branch requirement and the statement that
     a real run will fetch and verify the base branch.
   - `branch-setup (planned): ...` and `worktree (planned): ...`.
   - `task: <title>` and no `run:` line.
   - The author stage as `stage:  task-prompt [succeeded] model=<model>` and the first
     review as `stage:  task-review-1 [succeeded] (planned) model=<model>`.
   - `dry-run complete; Pi not invoked`.
   - No new run directory, no new worktree, no new branch, no rewritten task prompt, and no
     literal `<run dir>` directory.

4. **How to tell pass from fail**
   - **Pass:** run ids and worktree list unchanged, task-prompt bytes unchanged, exit 0,
     no `run:` line, and the plan lines present.
   - **Fail:** any new run id, a new `05-W1.2` worktree or branch, a changed prompt file, a
     `run:` line, or a dry run that writes run state. A dry run that creates only the
     worktree is still a failure for this task.

5. **Cost, permission or destructive warning**
   - No model spend, no fetch, no GitHub write. The dry run takes the one-run-per-worktree
     lock and reads the roadmap. Because the command may be run from a non-base branch in
     dry-run mode, expect a warning, not a refusal; do not switch branches as a "fix"
     unless you record it in teardown.

#### Scenario C4 — `aidw exec --dry-run` creates no run and prints neither `run:` nor `rendered:`

1. **Prerequisites**
   - `AIDW_STATE_DIR` isolated and `STATE_ROOT` recorded.
   - Agent configs are valid: `uv run --frozen aidw agents validate --strict` reports
     `11 agent config(s): 0 error(s), 0 warning(s)` (the build results record this).
   - The agent id `code-reviewer` and the prompt name `code-review` exist; both are used by
     the recorded CLI test.
   - Record the run ids: `uv run --frozen aidw runs list`.

2. **Command(s) or steps**
   ```bash
   uv run --frozen aidw exec --agent code-reviewer --prompt code-review --dry-run
   uv run --frozen aidw exec --help
   uv run --frozen aidw runs list
   ```

3. **Expected observable result**
   - Exit 0 and a stage line in the form
     `stage:  code-review [succeeded] model=<model>`.
   - `dry-run complete; Pi not invoked`.
   - **No `run:` line** and **no line beginning `rendered:`**. Both echoes are dropped in
     dry-run; the real-run echo is unchanged.
   - `aidw exec --help` shows the help string `Plan only; no writes.`
   - No new run directory under `STATE_ROOT/runs` and no literal `<run dir>` directory in
     the tree.

4. **How to tell pass from fail**
   - **Pass:** exit 0, both `run:` and `rendered:` absent, no new run id, and the help
     string is exactly `Plan only; no writes.`
   - **Fail:** either echo present, a new run directory, or the old
     `Plan only; do not invoke Pi.` help text. A real (non-dry) run is not part of this
     check and must not be used as a substitute: it should still print `run:` and
     `rendered:`, but it invokes Pi.

5. **Cost, permission or destructive warning**
   - No model spend in `--dry-run`. The real-run echoes are deliberately out of scope
     because a real run invokes Pi and spends tokens. No GitHub or cloud writes.

#### Scenario C5 — The one-run-per-worktree lock still refuses a dry run (exit 4)

1. **Prerequisites**
   - `AIDW_STATE_DIR` isolated and `STATE_ROOT` recorded.
   - A process holding the run lock for the same worktree. **Unconfirmed:** this tree
     exposes no toolkit command that holds the lock without invoking Pi, and the lock
     filename is a SHA-256 of the resolved worktree path (`aidw/lock.py`), so it must be
     found under `STATE_ROOT/locks` rather than computed by hand. The implementation uses
     `fcntl.flock`; `flock(1)` is not installed by default on macOS, so an equivalent
     holder would need `python3`/`fcntl`. No such holder command is provided by this tree.
   - The only confirmable holder from the tree is a second real workflow run in the same
     worktree, which invokes Pi and costs model tokens. If you are unwilling to pay that,
     record this scenario as not exercised.

2. **Command(s) or steps**
   - **Unconfirmed holder step**, if you choose to construct one:
     ```bash
     uv run --frozen aidw config show
     ls "$STATE_ROOT/locks"
     ```
     Then hold the lock file you found with a process of your own, using an OS advisory
     lock compatible with `fcntl.flock` (no command for this exists in the tree; the
     `flock` utility is not portable to macOS).
   - In another shell, with the lock held:
     ```bash
     uv run --frozen aidw implement docs/task-prompts/05-W1.2-prompt.md --dry-run
     ```
   - With a real concurrent run as the holder, the exact command is the workflow you
     chose, run without `--dry-run`, in the same worktree.

3. **Expected observable result**
   - Exit 4.
   - Stderr names the worktree and the lock path, in the `lock.LockHeldError` wording: it
     reports that another `aidw` run is already active in that worktree and names the lock
     file.
   - No new run state, no `run:` line, no stage-plan lines and no
     `dry-run complete` line. Stdout may already contain the pre-lock worktree/branch-setup
     preflight lines; those are not a plan.

4. **How to tell pass from fail**
   - **Pass:** exit 4 **and** the refusal message **and** no new run directory. The exit
     code alone is not enough: a usage error also exits non-zero.
   - **Fail:** exit 0 (the dry run ignored the lock), or a refusal that creates run state.

5. **Cost, permission or destructive warning**
   - A pure OS lock costs nothing; a real concurrent run spends model tokens and may write
     run state. Never delete or truncate a live lock file to "release" it; stop the holder
     process instead.

### 2.3 Browser UI flows

**None.** No changed file, build-results row or task-prompt statement names a browser UI,
route, page or screen. This change is CLI-and-run-store behaviour plus a documentation and
test contract, so there is no browser scenario to run.

### 2.4 External actions (GitHub, read-only)

The `review`, `fix` and `approve-followups` dry runs read GitHub through `gh` and the
bundled scripts even in dry-run mode. They are grouped here because their prerequisites and
warnings are credential- and network-bound.

#### Scenario G1 — `aidw review --pr <N> --dry-run`

1. **Prerequisites**
   - `AIDW_STATE_DIR` isolated and `STATE_ROOT` recorded.
   - `gh` on `PATH` and authenticated with read access to the target repository and its
     issues. The guide does not prescribe an auth command as confirmed: the tree only
     calls `github.gh_available()`, `github.pr_view` and the read helpers, so use your
     normal GitHub CLI sign-in. (`gh auth status` is the standard check but is not
     referenced by this tree — **unconfirmed** as a repo command.)
   - A pull-request number in the target repository that `gh` can read. This task's own PR
     is **not yet opened** (the build results record that), so the guide cannot name one;
     set `PR=<number>` to a PR you are entitled to read.
   - Record the run ids and, for the "no GitHub state written" check, the current open
     issue/comment counts for `$PR` via your normal `gh` read commands.

2. **Command(s) or steps**
   ```bash
   PR=<number>
   uv run --frozen aidw runs list
   uv run --frozen aidw review --pr "$PR" --dry-run
   uv run --frozen aidw runs list
   ```
   Then re-read the PR's issues/comments to confirm nothing was published.

3. **Expected observable result**
   - Exit 0.
   - `branch: <head-branch>` (or `branch: unknown (...)` when `gh` cannot answer) and
     `pr:     #<N>`; **no `run:` line**.
   - A planned line per review stage, including `code-review` and
     `review-findings-to-github`, in the form
     `<name> [succeeded] (planned) agent=<agent> model=<model>`, with the
     `(runs only when R1 reports findings)` note on R2.
   - `manifest: <run dir>/artifacts/review-manifest.json`.
   - `publisher argv: ... --dry-run` containing the same `<run dir>` manifest path.
   - `dry-run complete; Pi not invoked, no GitHub state written`.
   - No new run directory, no literal `<run dir>` directory, and no new issue, comment,
     label or state change.
   - The recorded review test pins both the planned manifest string and the unchanged runs
     tree.

4. **How to tell pass from fail**
   - **Pass:** exit 0, the plan, manifest and publisher-argv lines print with the literal
     `<run dir>` path, the run-id set is unchanged, and the PR's issue/comment set is
     unchanged.
   - **Fail:** a real run id or absolute run path in `manifest:`, a `run:` line, a new run
     tree entry, or any new GitHub issue/comment. An absolute path under a real run
     directory means the planned-directory substitution did not take effect.

5. **Cost, permission or destructive warning**
   - Read-only GitHub API calls; they consume rate-limit quota and need network access and
     a token with read scope. The scenario must not publish: `publisher argv` is printed
     with `--dry-run`. Do not copy that argv and run it with `--dry-run` removed — that
     would write issues.

#### Scenario G2 — `aidw fix --pr <N> --dry-run`

1. **Prerequisites**
   - `AIDW_STATE_DIR` isolated and `STATE_ROOT` recorded.
   - `gh` authenticated with read access, as in G1 (**unconfirmed** auth command, same
     reason), and a PR number `$PR` you can read. This task's PR is not yet opened, so the
     guide cannot supply the number.
   - A follow-up child may or may not exist; both paths are valid. The dry run invokes the
     bundled `review_followup.py select` script read-only.
   - Record the run ids: `uv run --frozen aidw runs list`.

2. **Command(s) or steps**
   ```bash
   PR=<number>
   uv run --frozen aidw fix --pr "$PR" --dry-run
   uv run --frozen aidw runs list
   ```

3. **Expected observable result**
   - Exit 0 and `pr:     #<N>`; **no `run:` line**.
   - `branch: <head-branch>` or `branch: unknown (...)`, plus `worktree (planned): ...`
     where a worktree exists or is planned, and `branch-setup (planned): ...` when one is
     missing.
   - A `child:` line (`child:  none available` when no follow-up is approved, or the
     selected child and inspected/total counts) and `select argv: ...`.
   - Planned stage lines in the form
     `<name> [succeeded] (planned) agent=<agent>`, starting with the
     `round1-approve-review-followups` stage, plus the post-loop lines with their
     "only when ..." notes.
   - Iteration-1 planned paths are literal:
     `<run dir>/artifacts/iter1-review-manifest.json` in the F4 manifest pointer and
     `<run dir>/artifacts/iter1-closing-body.md` for F1's `{closing_body}` variable.
   - `gates (planned): approve-followups, approve-fix-pr` and
     `loop: bounded by --max-iterations=<n>` (default 10 unless you pass
     `--max-iterations`).
   - `dry-run complete; Pi not invoked, no GitHub state written`.
   - No new run directory, no literal `<run dir>` directory, and no GitHub write.

4. **How to tell pass from fail**
   - **Pass:** exit 0, the child/plan/gates lines print, the planned paths contain the
     literal `<run dir>` root (no minted run id), the run-id set is unchanged, and no
     GitHub issue, comment, label or PR state changed.
   - **Fail:** a new run id or changed run bytes, a new GitHub write, a crash on the
     manifest/closing-body path, or a rendered path that names a real run directory instead
     of `<run dir>`.

5. **Cost, permission or destructive warning**
   - Read-only GitHub reads and the bundled selection script; network access and a
     read-scoped token are required. No model spend in dry-run. Do not run the printed
     `select argv` or any real fix cycle from this guide; those can modify the PR and spend
     tokens.

#### Scenario G3 — `aidw approve-followups --pr <N> --dry-run`

1. **Prerequisites**
   - `AIDW_STATE_DIR` isolated and `STATE_ROOT` recorded.
   - `gh` authenticated with read access, as in G1 (**unconfirmed** auth command), and a PR
     number `$PR` you can read. This task's PR is not yet opened.
   - Follow-up sub-issues may exist or not; `child:  none available` is a valid outcome.
   - Record the run ids: `uv run --frozen aidw runs list`.

2. **Command(s) or steps**
   ```bash
   PR=<number>
   uv run --frozen aidw approve-followups --pr "$PR" --dry-run
   uv run --frozen aidw runs list
   ```

3. **Expected observable result**
   - Exit 0 and `pr:     #<N>`; **no `run:` line**.
   - A `child:` line or `child:  none available`.
   - `approve-review-followups [succeeded] (planned) agent=review-approver model=<model>`
     (the stage name and agent are pinned by the recorded test).
   - `gate (planned): approve-followups`.
   - `dry-run complete; Pi not invoked, no GitHub state written`.
   - No new run directory, no literal `<run dir>` directory, and no GitHub write (no issue
     closed, no approval recorded).

4. **How to tell pass from fail**
   - **Pass:** exit 0, the stage and gate lines print, the run-id set is unchanged, and the
     PR's issues are unchanged (count and state).
   - **Fail:** a new run id or changed run state, any issue closed or approved, or a
     `child:` selection that reports a write. A selection helper failure printed as
     `select failed (...)` is also a failure even if the gate line still appears.

5. **Cost, permission or destructive warning**
   - Read-only GitHub reads; network and a read-scoped token. No model spend. Do not run the
     real `approve-followups`: it approves and closes follow-up issues, which is a write.

## 3. Teardown

Run this after the scenarios, from the same shell that set `AIDW_STATE_DIR`.

1. **Remove the isolated run store.** Every scenario above writes only under
   `$AIDW_STATE_DIR`; deleting that directory removes anything a dry run might have left.
   ```bash
   rm -rf "$AIDW_STATE_DIR"
   unset AIDW_STATE_DIR STATE_ROOT PR
   ```
   **Destructive warning:** only delete the `mktemp -d` path you exported. Never delete the
   real state root or `runs/` wholesale — `runs/` is machine-local operator state, and a
   pre-existing phantom run is never this guide's to remove.

2. **Remove any run created outside the isolated store.** If you ran a scenario before
   exporting `AIDW_STATE_DIR`, list run ids with `uv run --frozen aidw runs list` and remove
   only ids that were absent from your "before" list:
   ```bash
   rm -rf "<state root>/runs/<run-id you recorded as new>"
   ```
   Confirm the id against your notes before deleting; deleting a real run is irreversible.

3. **Check for a literal `<run dir>` directory.** Because the placeholder is a relative
   path, a stray write would appear in the working tree rather than under `runs/`. From the
   repository root, confirm no such directory exists; if one does, that is a finding to
   report (capture `git status`) before removing it.

4. **Worktrees and branches.** The W1.2 dry-run contract creates none, so no worktree or
   branch cleanup should be needed. If a scenario created one, remove it with the repo's
   normal git worktree/branch commands, and only after checking `git worktree list` and
   `git status` to be sure the branch is not someone else's work.

5. **Locks.** The scenarios release the one-run-per-worktree lock when the command exits.
   If C5 left a lock file, stop the holder process; do not delete a lock file while a run
   is active. An idle lock file may remain under `$STATE_ROOT/locks` until the isolated
   state directory is removed in step 1.

6. **GitHub.** No scenario is supposed to create GitHub state. If a dry run did write
   despite the expected result, the teardown is manual and destructive: close or delete
   only the issue/comment/label you can prove was created by this run, and do not alter
   unrelated follow-ups. The guide does not provide a write command for this.

7. **Local files.** No repository file is modified by these scenarios. If `design.md` or a
   task prompt appears changed after a scenario, that is a finding to report, not a step
   to clean up silently: capture `git status` and `git diff` first.

## 4. Could not be exercised in this environment

- **Build and lint gates.** The build results mark both **unverified**: no build command
  and no linter/formatter/type-checker are configured in `AGENTS.md` or
  `aidw/conventions.md`. They cannot be exercised in any environment for this repository
  as configured.
- **The mutation check "removing the no-write guard in `run_stage` fails a test".** The
  build results mark this **unverified**: the mutation was not separately exercised in the
  recording run. The re-baselined `tests/test_runner.py` assertions are the intended guard;
  proving the mutation would require temporarily deleting the `not dry_run` guard and
  running the focused tests, which this guide does not ask you to do against the branch.
- **A real Pi-invoking run.** The real-run `exec` echoes, the real `--resume` path, and the
  end-to-end "a dry run is not a resume target for a real run" check all require a model
  provider, credentials and spend. Not exercised here, and deliberately not instructed,
  because no test may invoke a real Pi model.
- **A PR-backed `review`/`fix`/`approve-followups` run against this task.** The build
  results record that the 05-W1.2 pull request is not yet opened, so no PR number exists
  for this change. These scenarios need a PR in the target repository and a GitHub token
  with read access; only a maintainer account in that repository can supply them.
- **The one-run-per-worktree lock holder.** No toolkit command holds the lock without
  invoking Pi, and the lock file is keyed by a SHA-256 of the resolved worktree path.
  `flock(1)` is not available by default on macOS, and no `python3`/`fcntl` holder is
  provided by the tree. A second real run would exercise it, at model cost.
- **A deployed stack, browser or hardware.** There is no browser, deployed-stack or
  hardware surface in this change, so none can be exercised.
- **Cloud-provider actions.** No changed file, build-results row or task-prompt statement
  names AWS or any other cloud provider. No cloud account, quota or spend is involved, so
  there is no cloud scenario to run.

Everything else above is exercisable from a normal developer checkout with `uv` and the
repository's test dependencies; the GitHub scenarios additionally need `gh` authentication,
network access and a PR you are entitled to read.
