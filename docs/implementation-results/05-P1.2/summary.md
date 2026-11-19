# Implementation Summary — 05-P1.2: Close a follow-up issue only after its fix is pushed

**Branch:** `05-P1.2`
**Source of record:** `docs/implementation-results/05-P1.2/build-results.md`
**Task prompt:** `docs/task-prompts/05-P1.2-prompt.md`

## The problem it was solving

Before this change, the fix workflow had a truthfulness gap: the fixer's own stage (`F1`) posted
the exact `Status: fixed` comment and closed the follow-up issue in the same step in which it
recorded the fix. The commit and push happened later, in P1.1's `F5 commit-and-push` stage. That
ordering allowed the workflow to report an issue as fixed before the fix had actually reached
the remote, so an abandoned, failed or skipped commit stage could leave a closed issue with no
pushed fix behind it. The task exists to remove that state, and the build results describe the
purpose in exactly those terms: move the close behind the push so `aidw fix` "can no longer
report an issue fixed before its fix has actually been pushed".

The task also had to respect a contract that could easily have been broken along the way: §7.2's
`Status: in progress` / `Status: fixed` marker strings are frozen (D5), and the existing
`closed_issues` bookkeeping means "fixed, close-pending" rather than "already closed". Nothing
could rename those literals or loosen the exact-match rule while moving the close.

## The core idea

The central decision was to split recording from closing: `F1` records the fix and leaves the
issue open with its existing `Status: in progress` marker, and Python — not the agent — runs a
new `review_followup.py close` subcommand only after `F5`'s push has been proven. The proof is
the same evidence P1.1 already establishes: `HEAD` moved, `HEAD == origin/<branch>`, a clean
tree, and `state.pr["head_sha"]` written. "Reported fixed" therefore becomes impossible without
a push, while a run with nothing to close keeps the earlier skip behaviour.

Two supporting choices followed from that. The closing body is written to an absolute
per-iteration path (`<run_dir>/artifacts/iter{N}-closing-body.md`, threaded as `F1`'s new
`{closing_body}` variable) because `F1` runs with the target repo as its cwd — a relative path
would land the body in the worktree and pollute the pushed diff, the same hazard that already
forces an absolute `manifest_path` for `F4`. And `close` resolves its target by `--issue` alone
rather than reusing `fixed`'s first-available selection, because the just-fixed child is in
flight; reusing that guard would refuse every close after the first with `EXIT_CONFLICT`. The
`fixed` and `close` paths then share one close tail and one pure rule (`logic.close_plan`) so
the marker, label, refuse-to-reopen, body and post-close-verification guards cannot drift apart.

## What was built, piece by piece

The workflow itself changed in `aidw/workflows/fix.py`. It now computes the absolute closing-body
path for each iteration, records it on the corresponding `closed_issues` entry, and runs the
close in Python after `run_commit` proves the push. The loop closes exactly the entries this
run recorded — one per iteration, never a batch and never a re-derived count — and a non-zero
close exit fails the run, naming the PR, branch and issue. When a close is pending but the push
fails, or the commit stage is absent, skipped or failed, the run fails closed with no close
call and no `head_sha`; when no close is pending, the existing D3 skip contract is preserved
and the run exits 0.

The script side gained the `close` subcommand. `prompts/scripts/review-followup/logic.py` adds
`close` to `COMMANDS`, the `ClosePlan`/`close_plan` rule, and the close action and refusal
tokens; `review_followup.py` adds the subcommand and factors the shared `apply_close` tail used
by both `fixed` and `close`. That tail posts the exact `Status: fixed` comment only if absent
(idempotent), then closes with the supplied body, enforcing strict marker equality, the
`review-follow-up`/`approve-fix` label guard, refuse-to-reopen, the `closing_body_repeats_status`
body guard, and post-close verification returning `EXIT_VERIFY_FAILED` on a label/state mismatch.
The script `README.md` and the CLI help now list `close` alongside the existing commands.

The prompt and agent contract changed with it. `prompts/fix-next-review-followup.md` was reworked
in its intro, §0, §7, §8 and Final report to leave the issue open with `Status: in progress` and
write the closing body to the supplied absolute path; `agents/fixer/AGENTS.md` drops its
"record it as fixed, and close it" rule, because §17's Z9 D9 records that prompt text alone does
not override an agent file. This is what stops the deferral from being contradicted by the
agent's own instructions.

The workflow machinery and documentation were updated to carry the new field:
`aidw/stage_registry.py` adds `{closing_body}` to `F1`'s variables and documents it in the
per-iteration expansion, with `aidw/runner.py` documenting `closing_body` among the fix
workflow's per-iteration fields. `docs/workflow-stages.md` updates the fix flow, `F1`'s variables
and adds a deferred-close section; `README.md` documents the deferred close and post-push
contract; `design.md` updates §8.4's `F1`/D3 prose, appends P1.2's decisions to the existing §17
row `Z9` (not a new row), and updates the §18 risk row; the roadmap entry's deliverables and
tests were expanded to match. The new and updated tests pin all of this: `test_close.py` (created)
covers the `close`/`fixed` CLI tail and its guards, `test_logic.py` covers parsing and pure
`close_plan`, `test_fix_workflow.py` covers ordering and fail-closed paths, `test_plan_stages.py`
and `test_stage_registry.py` re-baseline `F1`'s variables, `test_prompt_neutrality.py`
re-baselines the prompt arity to `$1`/`$2`, and `test_design_doc.py` pins the §8.4 deferred close
and the single `Z9` row.

## What it deliberately did not do

- **P1.1's commit/push mechanics were left alone.** The `F5` stage, the D3 four-case table and
  the D6 proof were not changed; P1.2 only moves the close behind that push, per the task
  prompt's explicit non-goals.
- **No batch fixes or batch closes.** B1.1 is separate work; the fix loop and the close loop
  remain one issue per iteration.
- **Q1.1 was not started.** Withholding the PR when the tester's in-scope verdict is `Fail`
  belongs to a different epic.
- **No marker or label renames.** `Status: fixed` and `Status: in progress` stay D5-frozen in
  `prompts/scripts/review-followup/constants.py`.
- **No reopen path was added.** The roadmap's "or is reopened" covers only the pre-P1.2
  transitional state; nothing now closes before the push, so no reopen path is needed.
- **No commit, push or pull request from the recording stage.** Delivery belongs to `/pr`; the
  build results record that no pull request exists yet and that `/pr` will fill in the number.

## Verification

The build results record the repository's own gates, run from the root `AGENTS.md` list. The
install gate (`uv sync --frozen`) passed, the build gate (`uv build`, run through
`aidw gate run build`) passed and produced both `aidt-1.5.0.tar.gz` and the wheel, `aidw doctor`
passed with `21 checks: 0 failed, 2 warning(s)` (the dirty working tree and the missing
`.mcp.json`, both expected while the work is uncommitted), `aidw agents validate --strict`
passed with `11 agent config(s): 0 error(s), 0 warning(s)`, `aidw prompts check` passed with
`0 error(s), 0 warning(s)`, and `git diff --check` passed with no output. The lint row is
recorded as `n/a` because this repo configures no linter.

The test gate is the one recorded failure, and it is carried here as a failure. `uv run --frozen
pytest` (gate `suite`, run by the recording stage itself) reported **`1 failed, 2191 passed in
47.55s`**: `prompts/scripts/review-followup/tests/test_close.py::test_a_body_prefixed_by_the_status_marker_is_refused`
failed with `assert 0 == 2`. Per the build results, a `close --body-file` whose body begins
`Status: fixed — verification details` exited 0 and closed the issue, while the test expects a
refusal with exit 2 and no comment or close call; the build results attribute this to
`closing_body_repeats_status` matching only an exact `Status: fixed` line. The failure was not
repaired during recording, and no implementation or test file was changed to work around it.
Consequently the task-specific gate row "`close` command guards — missing labels, non-open
issue, missing/empty body, idempotent re-run and post-close verification" is also recorded as
failed for that same test, while its other cases passed.

All the other task-specific gates passed in the same full-suite run: the close-after-push
ordering test, the five fail-closed tests, the empty-run and two-iteration ordering tests, the
absolute closing-body path test, the `test_logic.py` parse and `close_plan` tests, the design-doc
pins, the stage/planning pins, the prompt arity/neutrality test, and the workflow-stages drift
check. The build results also note that the `suite` row is the recording stage's own run rather
than a reused outcome, and that no pull request existed when it was written.

One point of ambiguity worth naming: the recorded failure row is reported under both "Test"
(gate `suite`) and the task-specific "`close` command guards" row, so the summary counts it as
one real failure observed in the full suite rather than two independent ones. No other recorded
outcome required interpretation.
