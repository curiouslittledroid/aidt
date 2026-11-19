# Build Results — 05-P1.2: Close a follow-up issue only after its fix is pushed

**Branch:** `05-P1.2`
**Date:** 2026-11-19
**Spec:** `design.md` §8.4 (`aidw fix --pr <n>`), §7.2 (frozen GitHub contracts, D5), §17 row `Z9`; roadmap entry P1.2 in `docs/tasks/05 - Pipeline efficiency.md`; `docs/task-prompts/05-P1.2-prompt.md`
**Pull request:** not yet opened — the /pr stage records it here once the PR exists

## Summary

**Purpose:** Move a follow-up issue's exact `Status: fixed` comment and close behind the P1.1 `F5 commit-and-push` stage, so `aidw fix` can no longer report an issue fixed before its fix has actually been pushed.

| Decision | Why it matters |
|----------|---------------|
| `F1` writes the closing body to an absolute per-iteration path and leaves the issue open | The fixer runs with the target repo as its cwd, so a relative path would write the body into the worktree and pollute the pushed diff; leaving the issue open preserves the untruthful-state removal. |
| `review_followup.py close --pr <n> --issue <n> --body-file <path>` resolves by `--issue` alone | The just-fixed child is in flight, not first-available; reusing `fixed`'s selection step would refuse every close after the first with `EXIT_CONFLICT`. |
| `fixed` and `close` share one close tail and one pure rule (`logic.close_plan`) | The §7.2 exact-marker contract, label guard, refuse-to-reopen rule, closing-body guard and post-close verification cannot drift between the in-stage and deferred forms. |
| Python runs the close only after `run_commit` proves the push | `F5` stays commit-and-push only (Z9 D9); `HEAD` moved, `HEAD == origin/<branch>`, a clean tree and `state.pr["head_sha"]` are the evidence that gates the close. |
| A pending close without a verified push fails closed; no pending close keeps D3's skip | "Reported fixed" without a push is exactly the state the task removes, while an empty or no-op run still exits 0 without closing anything. |

**Where it fits in the roadmap:** Phase 05 ("Pipeline efficiency"), epic P1 ("A fix closes its issues only after the push"), task P1.2. It depends on P1.1's `F5 commit-and-push` stage (PR #158) and completes the close-after-push ordering recorded in the existing §17 `Z9` row. B1.1 (batch fixes) remains later work that must preserve the one-issue-per-close rule.

**Scope:** `aidw/workflows/fix.py` (deferred-close loop and fail-closed paths), `aidw/stage_registry.py` (`F1`'s `{closing_body}` variable), `prompts/fix-next-review-followup.md` and `agents/fixer/AGENTS.md` (no in-stage close), `prompts/scripts/review-followup/review_followup.py` and `logic.py` (the `close` subcommand, `close_plan`, shared close tail), the script `README.md`, `design.md` §§7.2/8.4/17/18, `docs/workflow-stages.md`, `README.md`, `aidw/runner.py`, and the named test files. It deliberately stops short of changing P1.1's commit/push mechanics or D3/D6 proof, batching fixes or closes, withholding the implement PR for a tester `Fail`, and renaming the frozen `Status: fixed`/`Status: in progress` literals.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/05-P1.2-prompt.md` | Created | The task prompt recording the requirements, fixed decisions, tests and explicit non-goals. |
| `prompts/scripts/review-followup/tests/test_close.py` | Created | Pure tests for the `close`/`fixed` CLI tail, including idempotent re-runs and guard failures. |
| `README.md` | Modified | Documents the deferred close in the `aidw fix` flow and the post-push close contract. |
| `agents/fixer/AGENTS.md` | Modified | Removes the in-stage close and requires the fixer to write its closing body to the supplied absolute path. |
| `aidw/runner.py` | Modified | Documents `closing_body` in the fix workflow's per-iteration fields. |
| `aidw/stage_registry.py` | Modified | Adds `{closing_body}` to `F1`'s variables and documents the new field in the per-iteration expansion. |
| `aidw/workflows/fix.py` | Modified | Adds the absolute closing-body path, the post-push close loop, and the fail-closed path for a pending close without a verified push. |
| `design.md` | Modified | Updates §8.4's `F1`/D3 prose, appends P1.2's decisions to §17 row `Z9`, and updates the §18 risk row. |
| `docs/tasks/05 - Pipeline efficiency.md` | Modified | Expands P1.2's deliverables and tests to match the implemented close-after-push design. |
| `docs/workflow-stages.md` | Modified | Updates the fix flow, `F1`'s variables, and adds the deferred-close section. |
| `prompts/fix-next-review-followup.md` | Modified | Reworks the intro, §0, §7, §8 and Final report to leave the issue open and write the closing body. |
| `prompts/scripts/review-followup/README.md` | Modified | Documents `close`, its `--issue` resolution, and the shared guards with `fixed`. |
| `prompts/scripts/review-followup/logic.py` | Modified | Adds `close` to `COMMANDS`, the `ClosePlan`/`close_plan` rule, and close action/refusal tokens. |
| `prompts/scripts/review-followup/review_followup.py` | Modified | Adds the `close` subcommand and factors the shared `apply_close` tail used by `fixed`. |
| `prompts/scripts/review-followup/tests/test_logic.py` | Modified | Adds parsing and pure `close_plan` tests. |
| `tests/test_design_doc.py` | Modified | Pins §8.4's deferred close and §17's single `Z9` row recording it as implemented. |
| `tests/test_fix_workflow.py` | Modified | Covers close-after-push ordering, absolute body path, fail-closed paths, one close per iteration and close-failure messaging. |
| `tests/test_plan_stages.py` | Modified | Re-baselines `F1`'s variables to include the absolute closing-body path. |
| `tests/test_prompt_neutrality.py` | Modified | Re-baselines the fix prompt's arity to `$1` and `$2` and verifies both values render. |
| `tests/test_stage_registry.py` | Modified | Requires `closing_body` on fix expansion and pins the new `F1` variables. |

---

## Verification Results

Commands are this repo's own, taken from its root `AGENTS.md` ("Gates — run exactly these, and only these"). There is no `aidw/conventions.md` and no lint/formatter/type-checker is configured (AGENTS.md "Tests"; design §15), so the lint row is `n/a`. The build and suite gates ran through `aidw gate run <key>` with the workflow's declared scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.91ms`) |
| Lint | — | n/a — this repo configures no linter (AGENTS.md: "pytest is the only verification") |
| Build | `uv build --out-dir <mktemp dir>` (gate `build`) | ✅ Pass — built `aidt-1.5.0.tar.gz` and `aidt-1.5.0-py3-none-any.whl` |
| Test | `uv run --frozen pytest` (gate `suite`) | ❌ Fail (`1 failed, 2191 passed in 47.55s`) — `prompts/scripts/review-followup/tests/test_close.py::test_a_body_prefixed_by_the_status_marker_is_refused` |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`) — warnings are the dirty working tree and the missing `.mcp.json` |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (`resolved repo prompts: 0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (exit 0, no output) |

Gate origins for the rows above (tree `fd0982d4594b`, scope excludes `docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks`):

- `build` — passed at `2026-11-19T06:42:40Z`, stage `record-implementation-results` (`Successfully built …/aidt-1.5.0-py3-none-any.whl`).
- `suite` — failed at `2026-11-19T06:43:30Z`, stage `record-implementation-results` (`1 failed, 2191 passed in 47.55s`). This is this stage's own run, not a reused outcome.

### `uv run --frozen pytest` (full suite)

The single full-gate run above is the source for every row. The failing test is a task-specific deferred-close guard; the passing tests include the rest of the new coverage.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2192 collected | ❌ Fail (`1 failed, 2191 passed in 47.55s`) |

The failure:

```text
FAILED prompts/scripts/review-followup/tests/test_close.py::test_a_body_prefixed_by_the_status_marker_is_refused
E       assert 0 == 2
prompts/scripts/review-followup/tests/test_close.py:260: AssertionError
```

The command exited 0 for a `close --body-file` whose body begins with `Status: fixed — verification details`, while the test expects the CLI to refuse it with exit 2 and make no comment or close call. The recorded output shows `"action": "closed"` and the issue closed. This is a real gate failure and is not repaired in this recording stage.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Close-after-push ordering — a converged run records the issue, verifies `head_sha`, and only then closes it | ✅ Pass — `tests/test_fix_workflow.py::test_a_converged_run_closes_the_recorded_issue_after_the_push` passed in the full suite |
| Fail-closed paths — no verified push, skipped commit stage, non-zero close exit and a missing body all fail without closing | ✅ Pass — the five `tests/test_fix_workflow.py` fail-closed tests passed in the full suite |
| Empty run and two-iteration ordering — no close for an empty run; one close per recorded issue in order | ✅ Pass — `test_an_empty_run_attempts_no_close` and `test_two_iterations_close_one_issue_each_in_order` passed |
| Absolute closing-body path — per-iteration, absolute, and outside the repo tree | ✅ Pass — `test_closing_body_path_is_absolute_and_per_iteration` passed |
| `close` parsing and shared `close_plan` guards | ✅ Pass — `tests/test_logic.py`'s new parse/`close_plan` tests passed |
| `close` command guards — missing labels, non-open issue, missing/empty body, idempotent re-run and post-close verification | ❌ Fail — `tests/test_close.py::test_a_body_prefixed_by_the_status_marker_is_refused` failed (expected exit 2, observed exit 0 and a completed close); the other `test_close.py` cases passed |
| Design-doc pins — §8.4 documents the deferred close and exactly one `Z9` row records it as implemented | ✅ Pass — `tests/test_design_doc.py` passed in the full suite |
| Stage/planning pins — `F1` variables and expansion require the closing-body path | ✅ Pass — `tests/test_plan_stages.py` and `tests/test_stage_registry.py` passed in the full suite |
| Prompt arity/neutrality — the fix prompt renders `$1` and `$2` with no leftover placeholder | ✅ Pass — `tests/test_prompt_neutrality.py` passed in the full suite |
| Workflow-stages drift check | ✅ Pass — `tests/test_workflow_stages_doc.py` passed in the full suite |

---

## Deviations observed during recording

- **The full suite fails on a deferred-close guard** — `test_a_body_prefixed_by_the_status_marker_is_refused` expects a `Status: fixed`-prefixed body to be refused before any close, but this tree's `closing_body_repeats_status` only matches an exact `Status: fixed` line, so `Status: fixed — verification details` is accepted and the issue is closed. The failure is recorded here as observed; no implementation, test or traceability file was changed to work around it.
- **No pull request exists** — the read-only `gh pr view 05-P1.2` lookup returned no PR. The document records the required not-yet-opened note; `/pr` will replace it with the real number after creating the pull request.
- **`aidw doctor` reports two warnings, not one** — the dirty working tree and missing `.mcp.json` are both expected while this results document and the implementation remain uncommitted; `0 checks failed`.

---

## Non-Goals (NOT implemented)

- ❌ P1.1's `F5 commit-and-push` commit/push mechanics, D3 table and D6 proof were not changed — P1.2 only moves the close behind that push (task prompt, "Explicit non-goals").
- ❌ B1.1 batch fixes were not started — the close loop and the fix loop remain one issue per iteration (task prompt, "Explicit non-goals").
- ❌ Q1.1 (withhold the PR when the tester's in-scope verdict is `Fail`) was not started (task prompt, "Explicit non-goals").
- ❌ The frozen marker/label literals in `prompts/scripts/review-followup/constants.py` were not renamed or re-worded — `Status: fixed` and `Status: in progress` stay D5-frozen (task prompt, "Explicit non-goals").
- ❌ No reopen path was added — the roadmap's "or is reopened" covers only the pre-P1.2 transitional state; nothing now closes before the push (task prompt, "Explicit non-goals" / Notes).
- ❌ No commit, push or pull request from this record stage — delivery belongs to `/pr` (record stage instruction).
