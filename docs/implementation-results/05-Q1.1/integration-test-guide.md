# Integration-test guide — 05-Q1.1

**Branch:** `05-Q1.1`
**Guide for the change recorded in** `docs/implementation-results/05-Q1.1/build-results.md`
**Procedure type:** hand-run only. Nothing in this guide has been executed by the toolkit or by
the agent that wrote it.

## What this guide covers

This is a hand-run procedure for the Q1.1 change on branch `05-Q1.1`: `aidw implement` must not
run `I6 pr` — and therefore must not open a pull request — when the `I2 test` stage's final
message declares an in-scope `Fail`, or when the verdict cannot be parsed. It walks three
surfaces: the repository's own pytest and `aidw` verification tooling (which prove the parser,
the gate, the resume rule and the design pins without invoking a model), the `aidw implement`
CLI (including its `--resume` and `--from test` paths against a disposable scratch task), and
the read-only GitHub check that no pull request was opened. It also checks the new
machine-parseable verdict block in `prompts/test.md` after a live tester run. The change has no
browser or deployed-stack surface, so this guide contains no browser scenarios.

## Scenarios

### Repository tooling

#### Scenario 1 — Focused Q1.1 workflow and design tests

**Prerequisites**

- The worktree is on branch `05-Q1.1` with the change present (`git status` shows the modified
  `aidw/workflows/implement.py`, `prompts/test.md`, `design.md` and tests, or those changes are
  committed on the branch).
- `uv` is installed and dependencies are synchronised.
- No model credentials are needed; these are in-process fake-stage tests.

**Command(s) or steps**

```bash
uv sync --frozen
uv run --frozen pytest tests/test_implement_workflow.py tests/test_design_doc.py
```

**Expected observable result**

Both files collect and run, the process exits 0, and the summary reports no failures. The
tests include the six parser cases, the in-scope `Fail` end-to-end case (exit 3, `BLOCKED`, no
`pr` stage, criteria recorded), the parallel dispatch case, the plain-resume repeat-stop case,
the `--from test` re-test case, the `Pass` and out-of-scope-failure cases, the missing/empty
`out.txt` cases, and the `design.md` §8.2/§17 `Z10` pins.

**How to tell pass from fail**

Pass is exit 0 with no `failed` entry in the summary. A failure is any non-zero exit, a
collection error, or a `failed` test; the failing test name identifies which gate branch broke.
The focused selection's own test count is not recorded in the build results, so do not compare
against the full-suite count.

**Cost, permission or destructive warning**

None. No network, model, GitHub or cloud call is made.

#### Scenario 2 — Repository prompt, agent and doctor gates

**Prerequisites**

- Same worktree and synchronised dependencies as Scenario 1.
- No model credentials are needed.

**Command(s) or steps**

```bash
uv run --frozen aidw doctor
uv run --frozen aidw agents validate --strict
uv run --frozen aidw prompts check
```

**Expected observable result**

- `doctor` reports `21 checks: 0 failed, 2 warning(s)`. The two warnings recorded at build time
  were the dirty working tree and the missing `.mcp.json`; an additional warning is not
  necessarily a failure, but a failed check is.
- `agents validate --strict` reports `11 agent config(s): 0 error(s), 0 warning(s)`.
- `prompts check` reports `0 error(s), 0 warning(s)` for the toolkit defaults and the resolved
  repo prompts. This is the gate that proves the edited `prompts/test.md` still satisfies the
  prompt inventory and validation rules.

**How to tell pass from fail**

Pass is `0 failed` for `doctor`, and `0 error(s)` plus `0 warning(s)` for both `agents` and
`prompts`, with exit 0. Any reported error or failed check is a fail; a warning from `doctor`
alone is not, unless an error accompanies it.

**Cost, permission or destructive warning**

None. These are read-only local validations.

### Custom CLI commands

The live scenarios below exercise the actual `aidw implement` CLI with real Pi agents. They are
the only end-to-end path through the new verdict gate. They use a disposable scratch task
(`99-Q9.9`) and a disposable worktree so the real `05-Q1.1` worktree, its run history and its
pull request are untouched. Run them only if model credentials and model spend are available.

#### Scenario 3 — A live in-scope `Fail` withholds the PR

**Prerequisites**

- A control worktree on `05-Q1.1` with the change present, and Pi model credentials/configuration
  available to `aidw` (the tester and the other stages invoke a real model).
- `gh` is installed and authenticated, for the read-only no-PR check in Scenario 5.
- Disk space and a disposable worktree name; the commands below use `99-Q9.9`.
- The scratch task has its own roadmap entry. `aidw implement` resolves exactly one roadmap
  entry for the task before it plans the stages, and refuses with exit 2 if none matches; this is
  why the scratch entry below is part of the fixture, not an optional extra.
- Optional but recommended for isolation: a separate shell session, because the commands export
  shell variables.

**Command(s) or steps**

1. From the control worktree (the `05-Q1.1` worktree), note the workspace and state roots:

   ```bash
   uv run --frozen aidw config show
   ```

   Record the `workspace root:` and `state root:` lines. The scratch worktree will be
   `<workspace root>/99-Q9.9`.

2. Capture the change if it is still uncommitted, then create the scratch branch/worktree from
   `05-Q1.1`:

   ```bash
   git diff > /tmp/q1.1-wip.patch
   uv run --frozen aidw worktree add 99-Q9.9 --base 05-Q1.1
   ```

   If the change is already committed on `05-Q1.1`, skip the `git diff` line and the `git apply`
   line below; `--base 05-Q1.1` already carries it.

3. Apply the captured change inside the scratch worktree and confirm the worktree exists:

   ```bash
   git -C <workspace root>/99-Q9.9 apply /tmp/q1.1-wip.patch
   uv run --frozen aidw worktree list
   ```

   `<workspace root>` is the value recorded in step 1. `aidw worktree list` should show the
   `99-Q9.9` entry at `<workspace root>/99-Q9.9`.

4. Create the scratch task prompt at
   `<workspace root>/99-Q9.9/docs/task-prompts/99-Q9.9-prompt.md` with a deliberately impossible
   in-scope criterion. Use the repository's task-prompt style; the essential content is:

   ```markdown
   Task: Scratch fixture for the Q1.1 verdict gate. Do not change product code.

   Requirements:
   1. Add a short comment to `README.md` naming this scratch fixture.

   Done when:
   - Running the shell command `false` exits 0. This criterion is deliberately impossible;
     report it as `Fail` in the tester report.

   Deliverables:
   - README.md
   ```

   The filename must be `99-Q9.9-prompt.md`: the branch is derived from the prompt filename
   (`<phase>-<task>`), and the branch created in step 2 is `99-Q9.9`.

5. Create the scratch roadmap entry at
   `<workspace root>/99-Q9.9/docs/tasks/99 - Scratch.md`:

   ```markdown
   # Phase 99: Scratch

   ## Epic Q9: Scratch

   - [ ] **Q9.9. Scratch verdict-gate fixture** (Design 8.2)
     - Done when: the live implement run reaches the I2 verdict gate and opens no PR.
   ```

   Then validate the roadmap parse and the task id:

   ```bash
   cd <workspace root>/99-Q9.9
   uv run --frozen aidw tasks --validate
   ```

   `aidw tasks --validate` must exit 0 with no output.

6. Run the workflow from the scratch worktree:

   ```bash
   cd <workspace root>/99-Q9.9
   uv run --frozen aidw implement docs/task-prompts/99-Q9.9-prompt.md --yes
   ```

   `--yes` approves the `approve-implementation-pr` gate if the run reaches it. On the intended
   `Fail` path the gate is never reached.

7. Inspect the run record:

   ```bash
   uv run --frozen aidw runs list
   uv run --frozen aidw runs show <run-id>
   ```

   Use the newest run id from the list.

8. Inspect the tester's recorded final message, which is also the evidence for the
   `prompts/test.md` contract:

   ```bash
   sed -n '1,200p' <state root>/runs/<run-id>/stages/test.out.txt
   ```

   `<state root>` is the value recorded in step 1.

9. Optionally inspect the recorded verdict fields in
   `<state root>/runs/<run-id>/state.json` with an editor or `grep`; look for
   `test_verdict` and `test_failing_criteria`.

**Expected observable result**

- The `implement` command exits 3.
- Its stderr contains a line of the form
  `test verdict gate: I2 test reported `Fail` for in-scope criteria: <criteria>` (the criteria
  are the ones the tester named after `Failing in-scope criteria:`), followed by
  `no PR opened: `I6 pr` is withheld, so this run opens no pull request.` and the resume hint
  naming both `--resume` and `--from test`.
- `aidw runs list` shows the scratch run with status `blocked`.
- `aidw runs show <run-id>` shows the `test` stage as `succeeded`, shows no `pr` stage, and shows
  no `approve-implementation-pr` gate. The `update-roadmap` stage may be `succeeded` or
  `skipped`; that is not the subject of this gate.
- `test.out.txt` contains a per-criterion block with `Criterion:`, `Result:`, `Scope:`,
  `Evidence:` and `Gap:` lines, and ends with the bare declaration lines
  `Test verdict: Fail` and `Failing in-scope criteria: <criteria>`.
- The state file records `test_verdict` as `Fail` and `test_failing_criteria` as the parsed
  criteria list.

**How to tell pass from fail**

Pass requires all of: exit 3, the stderr line naming the failing in-scope criteria, the absence
of a `pr` stage and an `approve-implementation-pr` gate in `aidw runs show`, and the bare
`Test verdict: Fail` declaration in `test.out.txt`. If the run exits 0, if a `pr` stage appears,
if the PR is opened, or if the verdict gate is reached but the recorded test stage is not
`succeeded`, the result is a fail. If the tester instead reports `Pass` (for example because it
did not treat the impossible criterion as in-scope), the scenario did not exercise the gate;
that is a fixture fail, not a gate pass.

**Cost, permission or destructive warning**

This scenario spends real model tokens across the whole `implement` chain (implementation,
test, record, summary, guide and roadmap stages), and the tester may run the repository's test
suites. It writes only inside the disposable `99-Q9.9` worktree and the machine-local run state.
It must not open a PR on the intended `Fail` path. Do not run it in the real `05-Q1.1`
worktree, and do not use `--yes` if a `Pass` could open a PR you do not want. The `I7` tick may
edit the scratch roadmap file; that edit is confined to the scratch worktree.

#### Scenario 4 — A plain `--resume` repeats the stop, and `--from test` re-runs I2

**Prerequisites**

- Scenario 3 completed, with a blocked scratch run whose recorded `test.out.txt` still declares
  `Test verdict: Fail`.
- The scratch worktree `<workspace root>/99-Q9.9` still exists.
- Model credentials are still available; the `--from test` step invokes the tester again.

**Command(s) or steps**

1. Repeat the same command with a plain resume:

   ```bash
   cd <workspace root>/99-Q9.9
   uv run --frozen aidw implement docs/task-prompts/99-Q9.9-prompt.md --resume --yes
   ```

2. Record the run id and stage list:

   ```bash
   uv run --frozen aidw runs list
   uv run --frozen aidw runs show <run-id>
   ```

3. Re-test with `--from test`:

   ```bash
   uv run --frozen aidw implement docs/task-prompts/99-Q9.9-prompt.md --resume --from test --yes
   ```

4. Record the same run's stage list again:

   ```bash
   uv run --frozen aidw runs show <run-id>
   ```

**Expected observable result**

- Step 1 exits 3 with the same `test verdict gate` stderr lines and the same resume hint.
- After step 1, `aidw runs show` shows the same run id and no additional `test` stage: the
  already-`SUCCEEDED` `test` stage is skipped and its recorded verdict is re-read.
- Step 3 exits 3 again, but it re-runs `I2 test`: the run's stage list now shows a second `test`
  stage record, and `I1 impliment-task` does not re-run. The `pr` stage still does not appear
  and no gate is recorded.

**How to tell pass from fail**

Pass is: step 1 exits 3 without adding a `test` stage; step 3 exits 3 and adds exactly one new
`test` stage without re-running `impliment-task`; neither step dispatches `pr` or records the
approve gate. A plain `--resume` that re-runs the whole chain, an exit 0, a missing new `test`
stage after `--from test`, or any `pr` stage is a fail. The `--from test` step is expected to
stop again because the scratch criterion is still impossible; a `Pass` there would mean the
fixture changed, not that the gate passed.

**Cost, permission or destructive warning**

Step 1 costs no model call if nothing re-runs, but step 3 invokes the tester and every later
stage again, so budget for another model-backed run and possible test-suite execution. It writes
only inside the scratch worktree and machine-local state, and it must not open a PR on this
fixture.

### Browser UI flows

No scenario. No changed file, build-results row or task-prompt statement names a browser route,
screen or client-side flow; the change is a workflow gate and a prompt contract. The
`prompts/test.md` instruction to use a real browser applies to browser-facing target changes,
not to this change.

### External actions

#### Scenario 5 — No pull request was opened after the `Fail`

**Prerequisites**

- Scenario 3 completed on the scratch branch `99-Q9.9`.
- `gh` is installed and authenticated against the repository that owns the scratch worktree's
  remote.
- The scratch branch was not pushed by any earlier manual step; `I6 pr` is the only stage that
  pushes here, and it did not run.

**Command(s) or steps**

```bash
cd <workspace root>/99-Q9.9
gh pr view 99-Q9.9 --json number,url
```

**Expected observable result**

`gh` exits non-zero and reports that no pull request exists for `99-Q9.9` (for example,
`no pull requests found for branch "99-Q9.9"`). It must not print a number or URL.

**How to tell pass from fail**

Pass is a non-zero `gh` exit with a "no pull requests found" message. A printed PR number or
URL is a fail: it means `I6 pr` ran despite the in-scope `Fail`. An authentication or
remote-resolution error is neither pass nor fail; fix the `gh` setup and re-run this read-only
check.

**Cost, permission or destructive warning**

None; this is a read-only GitHub query. It requires `gh` authentication but performs no write,
no push and no PR action.

## Teardown

After completing the scenarios, remove the scratch fixture and its local run state. Run these
from the control worktree (the `05-Q1.1` worktree), not from the scratch worktree.

```bash
cd <control worktree>
uv run --frozen aidw worktree remove 99-Q9.9 --force
git branch -D 99-Q9.9
rm -f /tmp/q1.1-wip.patch
```

`<control worktree>` is the worktree whose `target root:` line you recorded from
`uv run --frozen aidw config show` in Scenario 3. `aidw worktree remove --force` removes the
scratch worktree even though it is dirty; `git branch -D` deletes the local scratch branch.
Both are destructive to the scratch branch only; confirm the branch name is `99-Q9.9` before
running them.

The scenarios created no pull request, no remote branch and no deployed resource, so there is
nothing to close, unpublish or revert. If you want the machine-local state tree back to its
pre-guide contents, delete only the scratch run directory after noting its id:

```bash
uv run --frozen aidw runs list
rm -rf <state root>/runs/<run-id>
```

`<state root>` is the value recorded in Scenario 3. This deletes only the scratch run's
`state.json` and artifacts; it does not touch the real `05-Q1.1` run history. Leaving it in
place is harmless — it is run history, not tracked repository content.

If the change was committed on `05-Q1.1` and you skipped `/tmp/q1.1-wip.patch`, the `rm -f` line
is a no-op. If you created any shell variables in the scenario, close that shell.

## Could not be exercised in this environment

- **A live `Pass` run through `I6 pr` and real PR creation.** The `Pass` path proceeds to the
  approve gate and `I6 pr`, which pushes the branch and opens a real pull request on the
  repository's GitHub remote. That needs a disposable remote, repository write permission and
  model spend, and would create an external artifact this guide cannot clean up by itself. The
  `Pass` behaviour is instead covered by Scenario 1's in-process tests
  (`test_a_pass_verdict_proceeds_to_the_gate_and_dispatches_pr` and
  `test_a_pass_verdict_survives_an_out_of_scope_failure_in_the_report`). A disposable fork or
  throwaway GitHub repository with `gh` authenticated would exercise it.
- **A live unreadable-verdict stop.** The missing-`out.txt`, empty-final-message and
  no-declaration cases fail closed, but inducing them live requires deleting a recorded
  `out.txt` or making the tester return an empty message, neither of which is a safe or
  repeatable operator step. They are covered in-process by Scenario 1's
  `test_an_unreadable_test_verdict_fails_closed_without_a_pr` and
  `test_a_resumed_run_with_a_lost_out_txt_fails_closed`.
- **A live `--parallel` run.** The gate is asserted on the parallel dispatch path in-process by
  `test_an_in_scope_fail_withholds_the_pr_on_the_parallel_dispatch_path`; a live run would
  double the model spend without adding a surface this guide can safely observe.
- **Lint.** The build results mark lint **unverified** because the repository configures no
  linter (`AGENTS.md`: “pytest is the only verification”). There is no command to run here, and
  this guide does not invent one.
- **Build.** The build results mark build **unverified** because the repository's gate list
  defines no build command. There is no build artifact to produce or inspect.
- **Browser and deployed-stack flows.** The change touches no browser route, UI screen, cloud
  account or deployed service, so there is nothing to exercise with a browser, AWS credentials
  or a live stack.
- **The live Scenario 3–5 procedure itself.** It is written from the changed files, the code's
  own messages, the tests and the recorded build results; it has not been executed by the
  toolkit. Its expected outcomes are the expected outcomes of the code, not observations from a
  run performed while writing this guide.
