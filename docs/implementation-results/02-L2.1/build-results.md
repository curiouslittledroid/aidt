# Build Results — 02-L2.1: Reviewer rules for dependencies and unresolved choices

**Branch:** `02-L2.1`
**Date:** 2026-10-26
**Spec:** `docs/tasks/02 - Prompt loop integrity.md` — task L2.1 ("Reviewer rules for dependencies and unresolved choices"), Epic L2 ("Reviewer authority — stop the wrong prescription"), including the phase preamble's bucket-(i) note for `prompts/task-review.md` and the "Explicit non-goals for phase 02". `design.md` §8.1 (`aidw prompt` review stage, the verdict/fix loop, and `Blocked`-verdict semantics) and §8.3. `docs/migration/EXTRACTION.md` §4.2 (prompt buckets — `task-review.md` is bucket (i), generic, ships as-is). `AGENTS.md` (Gates; Tests).

## Summary

**Purpose:** Extend the reviewer prompt with the three rules that stop a factually-wrong prescription — inspect the branch that implements a dependency before trusting a roadmap summary, report a dependency conflict as a `Blocked` verdict rather than a `Must fix`/`Should fix` with a `Suggested fix`, and treat a `Suggested fix` as a direction rather than a decision — and make a `Blocked` verdict short-circuit the fix loop so it fails closed regardless of `approve_all`.

| Decision | Why it matters |
|----------|---------------|
| The `Blocked` short-circuit sits immediately after the `APPROVE` break and before `revisions += 1` and the `not findings or problems` fallback | A `Blocked` review must never spawn a fixer, with or without parsed findings; placing it earlier than the budget and fallback branches is what makes that true for every `Blocked` verdict, not only a "final" one. |
| The short-circuit precedes every `approve_all` acceptance path and `_commit_reviewed_prompt` | The pre-existing terminal guard was gated on `not approve_all`, so `approve_all=True` could carry a `Blocked` verdict through to the gate and commit. The short-circuit closes that hole and keeps the prompt uncommitted (design §8.3: "If `Blocked`, the workflow stops and reports — it does not publish"). |
| The two later `assumed_ok = verdict != VERDICT_BLOCKED` lines are left untouched | They are now unreachable for the `Blocked` case but still implement budget-exhaustion acceptance on the non-`Blocked` (`Request changes`) path owned by L4.1; removing or inverting them would regress the three-round and fix-batching tests. |
| The added prompt text is product-neutral and asserted on the added lines only | `prompts/task-review.md` is bucket (i) and ships verbatim to target repos at cutover (EXTRACTION.md §4.2), so no package manager, product path, product document, or product task-id example may be baked in. The pre-existing Scope bullet already names `Design 21`, and L2.1 does not neutralise pre-existing text, so the neutrality assertion is scoped to the rule lines this task adds. |
| `Blocked` stays a verdict, not a fourth finding priority | The finding labels, the three priorities and the three verdict tokens are byte-stable; `parse_review_findings` (`aidw/findings.py`) fails closed on an unknown `PRIORITY_MAP` key, so a `Priority: Blocked` would break parsing. |

**Where it fits in the roadmap:** Phase 02, Epic L2 ("Reviewer authority — stop the wrong prescription"). It is the first of L2's four rules and addresses the costliest finding of Review 1, which reasoned from roadmap prose about code that existed on an unmerged branch it never read. L2.2 (revision in `Where:`), L2.3 (delta brief) and L2.4 (evidence bundle) follow; the fixer's verify/sweep/snapshot/reconcile (L3.x) and terminal-review budget honesty (L4.1) depend on the verdict semantics pinned here. No `design.md` §17 entry is opened — L6.2 consolidates phase 02's decisions.

**Scope:** Adds the three reviewer rules to `prompts/task-review.md`, the `Blocked` short-circuit to `aidw/workflows/prompt.py`, four new tests plus one updated test in `tests/test_prompt_workflow.py`, and the L2.1 roadmap tick. It deliberately stops short of the rest of Epic L2 (L2.2–L2.4), the L3.x fixer stages, and the L4.x terminal-review/config work.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L2.1-prompt.md` | Created (committed) | The task prompt authored on the branch before implementation (commits `5b95937`, `0e117bc`). |
| `prompts/task-review.md` | Modified | Step 2 gained the dependency-branch inspection rule; the findings section gained the `Blocked`-not-a-prescription rule; the `Suggested fix` definition gained the direction-not-decision rule. |
| `aidw/workflows/prompt.py` | Modified | Added the `Blocked`-verdict short-circuit after the `APPROVE` break and before `revisions += 1` / the fallback fix stage: logs, sets `state.status = BLOCKED`, saves, prints the review text to stderr, and returns 3 — before any `approve_all` path or `_commit_reviewed_prompt`. |
| `tests/test_prompt_workflow.py` | Modified | Added `TASK_REVIEW_BLOCKED_DEPENDENCY` / `TASK_REVIEW_BLOCKED_NO_FINDINGS` fixtures and four tests (dependency short-circuit, `approve_all` override, no-findings fallback, rendered-prompt contract); updated `test_a_blocked_final_review_still_fails_closed` to assert no fix stage and a `BLOCKED` run. |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified | Roadmap escalation: L2.1 checkbox ticked (traceability artifact owned by the implement stage). |

---

## Verification Results

> **Overall gate: ✅ PASS.** `env -u AIDW_RUN_ID -u AIDW_STAGE uv run --frozen pytest` produced **`613 passed in 77.25s`**; install, build, doctor, agent validation, prompts check and `git diff --check` all passed. Every row below is a real observation from the single invocation named in its row, recorded through `aidw gate run` against tree `78ba47b6bae4`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Exit 0 — `Checked 15 packages in 0.84ms` (gate `install`, tree `78ba47b6bae4`, stage `record-implementation-results`, 2026-10-26T21:37:33Z) |
| Build | `uv build --out-dir <tmp>` | ✅ Exit 0 — built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` (gate `build`, tree `78ba47b6bae4`, 2026-10-26T21:37:38Z) |
| Test | `env -u AIDW_RUN_ID -u AIDW_STAGE uv run --frozen pytest` | ✅ Exit 0 — **`613 passed in 77.25s`** (gate `suite`, tree `78ba47b6bae4`, 2026-10-26T21:40:39Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)` (gate `doctor`, tree `78ba47b6bae4`, 2026-10-26T21:40:48Z) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `78ba47b6bae4`, 2026-10-26T21:41:17Z) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `78ba47b6bae4`, 2026-10-26T21:40:54Z) |
| Whitespace | `git diff --check` | ✅ Exit 0 — no whitespace errors |

All commands were run through `aidw gate run <key> -- ...` with the scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` that `pr.md` declares (the write-targets of the other stages). Each outcome above is cited from that run against tree `78ba47b6bae4`; `/pr` can cite `reused:` lines against the same tree only for the env-scrubbed `suite` command, since the failed bare `suite` invocation (below) is also recorded under the same key.

### `uv run --frozen pytest` (full suite)

Single passing invocation: **`613 passed in 77.25s`** (exit 0, gate `suite`, tree `78ba47b6bae4`, 2026-10-26T21:40:39Z). The subsets below are counts from that same run's collected set — no second full run was made.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 613 | ✅ Pass (`613 passed in 77.25s`) |
| `tests/test_prompt_workflow.py` (within the full suite) | 58 `def test_` functions | ✅ Pass (all collected items green within the 613) |
| L2.1 tests added or updated (within the full suite) | 4 new functions + 1 updated function | ✅ Pass |

### Task-specific verification gates

All L2.1 proofs are satisfied inside the single full-suite run above.

| Gate | Status |
|------|--------|
| Rendered reviewer prompt carries the three rules and the finding/verdict format is byte-stable | ✅ `test_l21_rendered_reviewer_prompt_states_dependency_and_blocked_rules` |
| A dependency-branch conflict reported as `Blocked` returns 3, run `BLOCKED`, no `task-review-fixes-*` stage, review text on stderr, prompt still uncommitted at the git level | ✅ `test_blocked_dependency_verdict_short_circuits_before_any_fix` |
| The same `Blocked` verdict with `approve_all=True` also returns 3, `BLOCKED`, no fix stage, no commit | ✅ `test_blocked_verdict_overrides_approve_all` |
| `Blocked` with no parseable findings does not run the fallback fixer | ✅ `test_blocked_without_findings_does_not_run_fallback_fix` |
| The existing final `Blocked` test now asserts no fix stage ran and the run is `BLOCKED` | ✅ `test_a_blocked_final_review_still_fails_closed` (updated) |
| `Approve` and `Request changes` loops unchanged | ✅ Existing three-round and fix-batching tests pass in the same full-suite run (exit 0, 613 passed) |

---

## Deviations observed during recording

- **The record prompt names a Node/pnpm gate example; this toolkit is Python/uv.** `prompts/record-implementation-results.md` uses `pnpm install` / `pnpm -r lint` / etc. as illustrative commands, and `pr.md` keys gates off the repo's actual stack: this repo has `pyproject.toml`/`uv.lock`, so its gates are `uv sync --frozen` and `uv run --frozen pytest`. The run installed and tested with the `uv` gates and additionally ran the AGENTS.md gate set (build, doctor, agents validate, prompts check) that previous phase-02 records ran. No `pnpm` command was run because this repo has no `pnpm-workspace.yaml`.
- **The first full-suite invocation leaked the recording identity and was re-run scrubbed.** `aidw gate run suite -- uv run --frozen pytest` recorded `2 failed, 611 passed in 72.62s` (tree `78ba47b6bae4`, 2026-10-26T21:38:54Z): the recorder's inherited `AIDW_RUN_ID`/`AIDW_STAGE` reached the pytest process, so `test_cli_gate_run_propagates_a_failing_exit_code` resolved an unknown run and exited 2 instead of 7, and `test_cli_gate_run_records_into_the_branch_run_without_an_env_identity` saw stage `record-implementation-results` instead of `cli`. Both failures are pre-existing test-isolation gaps, unrelated to L2.1's change, and CI (`.github/workflows/ci.yml`) sets neither variable. Re-running the same gate command with `env -u AIDW_RUN_ID -u AIDW_STAGE` for the child — matching CI and the L1.1/L1.2/L1.3 records — passed `613 passed in 77.25s`. The failed outcome remains in the run's state. No implementation or test file was modified.
- **The `agents-validate` and `doctor` gates were first invoked in parallel and raced on the run-state file.** `agents-validate`'s record was clobbered by `doctor`'s save, so it was re-run serially; its recorded passing outcome is above. No gate was skipped and no command was re-run to obtain a number.
- **Every gate printed the EXTRACTION.md §3.10 single-checkout warning.** This toolkit checkout is a single working tree, so `_roots` emits the advisory before each command. It is the intended warning, not a gate failure; for `agents-validate` the warning also became the gate's last non-blank summary line.
- **No task-specific command beyond the full suite was named.** The task prompt's tests are all `tests/test_prompt_workflow.py` fake-stage and rendered-prompt assertions; there is no separate live CLI gate, so all task-specific rows are derived from the single full-suite invocation.

---

## Non-Goals (NOT implemented)

- ❌ L2.2 (revision in `Where:`), L2.3 (delta brief), L2.4 (evidence bundle) — the rest of Epic L2; L3.x (fixer verify/sweep/snapshot/reconcile), L4.x (terminal-review budget honesty, recording, config) (task prompt, Explicit non-goals).
- ❌ No amendment to `design.md` §8.1 and no §17 decision entry — L6.2 consolidates this phase's design decisions and amends §8.1 provisionally; L4.1 owns the `MAX_REVISIONS`/terminal-review semantics (task prompt, Explicit non-goals).
- ❌ `prompts/task-review-fixes.md` and the fixer agent context are untouched — L3.1/L3.2 own those (task prompt, Explicit non-goals).
- ❌ Model routing and the independence rule (`task-reviewer.model != task-author.model != task-fixer.model`, design §5.4) are unchanged (task prompt, Explicit non-goals).
- ❌ No fields added to the review-finding manifest or the `Where:` evidence contract — L2.2 owns that; the bundled validator rejects unknown keys (task prompt, Explicit non-goals).
- ❌ No PR opened and nothing committed by this stage (record-implementation-results non-goals; `pr.md` owns delivery).

---

## Deliverables Checklist

- [x] `prompts/task-review.md` — dependency-branch inspection rule, `Blocked`-not-a-prescription rule, direction-not-decision `Suggested fix` rule; verdict tokens and finding labels unchanged.
- [x] `aidw/workflows/prompt.py` — `Blocked` short-circuit before `revisions += 1`, the fallback fix stage, any `approve_all` path, and `_commit_reviewed_prompt`; sets `BLOCKED`, prints to stderr, returns 3.
- [x] `tests/test_prompt_workflow.py` — four new tests plus the updated final-`Blocked` test, including the git-level no-commit assertion and the `approve_all` override.
