# Build Results — 02-L1.3: Give the author a blocked channel

**Branch:** `02-L1.3`
**Date:** 2026-10-26
**Spec:** `docs/tasks/02 - Prompt loop integrity.md` — task L1.3 ("Give the author a blocked channel"), Epic L1 ("Scheduling and preflight — stop the bad seed"), including the phase preamble's E1.6 evidence and the "How this phase is driven" ordering note. `design.md` §8.1 (`aidw prompt` author stage), §10 (Error handling condition table), §13 (Git and GitHub safety). `docs/migration/EXTRACTION.md` §3.8 (task-prompt format and repo conventions). `AGENTS.md` (Gates; Tests).

## Summary

**Purpose:** Give the `task-prompt` author stage an honest output channel — `blocked: <reason>` — so an author that finds a cited spec section missing, a prerequisite absent, or an acceptance condition that cannot be made executable without inventing a contract stops the run instead of smuggling the problem into the prompt body (the E1.6 failure).

| Decision | Why it matters |
|----------|---------------|
| The blocked marker is detected on the author stage output *before* `_resolve_prompt_path` | That helper takes the first output line as a path and falls back to the conventional file, so a `blocked:` line would be silently ignored whenever the author also left a file, and would produce the exit-1 "not found" failure when it did not. |
| The author stage record stays `succeeded`; the *run* becomes `BLOCKED` | The stage exited 0 with a valid report; it is the workflow's run, not the stage, that is blocked. Recording the stage as failed would misattribute a valid protocol result. |
| Blocked detection reuses the `_resolve_prompt_path` strip-then-first-line convention, case-insensitively | The marker is recognised the same way a prompt path is (surrounding backticks/fences and whitespace tolerated, `BLOCKED:` accepted), and the rest of the output is the reason — an empty reason is still a blocked run. |
| Leftovers are reported, never repaired: uncommitted changes under `docs/task-prompts/`, and a `{phase}-{task}` branch that appeared *during* the run | design §13: AIDT never deletes a branch and never discards work. The branch is probed before the author stage and again when blocked, so a legitimately pre-existing branch is never blamed on the run; an unanswerable probe reports nothing rather than guessing. |
| Exit code 3, no new status or code | Reuses the review-blocked exit code; `state.json`'s schema is unchanged and no review stage, fix loop or commit follows. |

**Where it fits in the roadmap:** Phase 02, Epic L1 ("Scheduling and preflight — stop the bad seed"). It is the third of L1's three stops: L1.1 requires a current base branch, L1.2 refuses out-of-order authoring from the roadmap, and L1.3 covers what only the author can see (a missing spec section, a contradictory roadmap entry, a prerequisite that is not merged). The author-prompt wording stays product-neutral because `prompts/task-prompt.md` is bucket (iii) and moves to the target repo at cutover (E7.1); the branch line in `agents/task-author/AGENTS.md` is left for E7.4. No `design.md` §17 entry is opened — L6.2 consolidates phase 02's decisions.

**Scope:** Adds the `blocked:` contract to `prompts/task-prompt.md` and `agents/task-author/AGENTS.md`, the marker parsing / branch probe / leftover reporting and the pre-`_resolve_prompt_path` early-return in `aidw/workflows/prompt.py`, the §8.1 author-stage description and §10 condition-table row in `design.md`, 13 L1.3 test items in `tests/test_prompt_workflow.py`, and the L1.3 roadmap tick. It deliberately stops short of the predecessor gate (L1.2), the base-branch check (L1.1), `--no-fetch` / `--allow-incomplete-prereqs`, E2.4/E2.5 branch creation, any branch removal, any resume path for a blocked run, any new run status or exit code, and any change to the reviewer/fixer prompts or review loop.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L1.3-prompt.md` | Created (committed) | The task prompt authored on the branch before implementation (commit `3c2ee53`). |
| `agents/task-author/AGENTS.md` | Modified | Added the feasibility-before-branch rule and the `blocked: <reason>` output contract; branch line left for E7.4. |
| `aidw/workflows/prompt.py` | Modified | Added `_parse_blocked`, `_probe_branch`, `_uncommitted_prompt_paths`, `_report_blocked_leftovers`; probe the author branch before the author stage; detect the blocked report before `_resolve_prompt_path` and end the run `BLOCKED` (exit 3) with the reason logged and printed, no commit/review. |
| `prompts/task-prompt.md` | Modified | Added the feasibility check before branching, the three reason classes, the empty-reason rule, and the extended `IMPORTANT:` closing line. |
| `tests/test_prompt_workflow.py` | Modified | Added `_blocked_author_stages` / `_run_log` helpers and 10 L1.3 test functions (13 items); imports `pytest`, `toolkit_root` and `render_prompt_file`. |
| `design.md` | Modified | §8.1 gained the blocked-report/feasibility/leftover sentence; §10 gained the `task-prompt` blocked condition row. No §17 entry. |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified | Roadmap escalation: L1.3 checkbox ticked (traceability artifact owned by the implement stage). |

---

## Verification Results

> **Overall gate: ✅ PASS.** `env -u AIDW_RUN_ID -u AIDW_STAGE uv run --frozen pytest` produced **`607 passed in 64.52s`**; install, build, doctor, agent validation, prompts check and `git diff --check` all passed. Every row below is a real observation from the single invocation named in its row, recorded through `aidw gate run` against tree `2a3f9226e36d`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Exit 0 — `Checked 15 packages in 1ms` (gate `install`, tree `2a3f9226e36d`, stage `record-implementation-results`, 2026-10-26T12:09:15Z) |
| Build | `uv build --out-dir <tmp>` | ✅ Exit 0 — built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` (gate `build`, tree `2a3f9226e36d`, 2026-10-26T12:09:21Z) |
| Test | `env -u AIDW_RUN_ID -u AIDW_STAGE uv run --frozen pytest` | ✅ Exit 0 — **`607 passed in 64.52s`** (gate `suite`, tree `2a3f9226e36d`, 2026-10-26T12:10:29Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)` (gate `doctor`, tree `2a3f9226e36d`, 2026-10-26T12:10:38Z) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `2a3f9226e36d`, 2026-10-26T12:10:37Z) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `2a3f9226e36d`, 2026-10-26T12:10:41Z) |
| Whitespace | `git diff --check` | ✅ Exit 0 — no whitespace errors |

All commands were run through `aidw gate run <key> -- ...` with the scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` that `pr.md` declares (the write-targets of the other stages). Each outcome above is cited from that run against tree `2a3f9226e36d`; `/pr` can cite `reused:` lines against the same tree.

### `uv run --frozen pytest` (full suite)

Single invocation: **`607 passed in 64.52s`** (exit 0, gate `suite`, tree `2a3f9226e36d`). The subsets below are counts from the same run's collected set — no second run was made.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 607 | ✅ Pass (`607 passed in 64.52s`) |
| `tests/test_prompt_workflow.py` (within the full suite) | 53 test functions | ✅ Pass (all collected items green within the 607) |
| L1.3 tests added in this task (within the full suite) | 10 functions / 13 items | ✅ Pass (10 of the 607 functions; the marker-parsing function is parametrized over 4 cases) |

The suite count rose from L1.2's 594 to 607 (+13), matching the 13 added L1.3 items.

### Task-specific verification gates

All L1.3 proofs are satisfied inside the single full-suite run above.

| Gate | Status |
|------|--------|
| Blocked author returns 3, run `BLOCKED`, reason in `run.log` and stderr, only the author stage ran, author record stays `succeeded`, nothing committed, no branch, no prompt file | ✅ `test_l13_blocked_report_ends_the_run_without_authoring` |
| Blocked detection precedes `_resolve_prompt_path`: a leftover file does not become the prompt | ✅ `test_l13_blocked_detection_precedes_path_resolution` |
| An uncommitted prompt file left behind is named and remains present (reported, never removed) | ✅ `test_l13_leftover_prompt_is_reported_not_removed` |
| A `{phase}-{task}` branch created during the run is named and still exists (reported, never deleted) | ✅ `test_l13_branch_created_during_run_is_reported_not_deleted` |
| A branch that pre-existed the run is not blamed on it | ✅ `test_l13_preexisting_branch_is_not_reported` |
| An unanswerable branch probe reports nothing rather than guessing | ✅ `test_l13_unanswerable_branch_probe_does_not_warn` |
| Marker parsing: leading blank line, upper-case `BLOCKED:`, and a multi-line reason all reach the log | ✅ `test_l13_marker_parsing_reaches_the_log` (4 params) |
| `blocked:` with no reason is still a blocked run, reported as "no reason" | ✅ `test_l13_empty_reason_is_still_blocked` |
| Empty author output keeps today's exit-1 "generated task prompt not found" failure | ✅ `test_l13_empty_author_output_keeps_the_not_found_failure` |
| Rendered author prompt and `agents/task-author/AGENTS.md` state the contract, and feasibility precedes the branch step | ✅ `test_l13_rendered_author_prompt_and_agent_context_state_the_contract` |
| Normal authoring path unchanged | ✅ Existing prompt-workflow tests pass in the same full-suite run (exit 0, 607 passed) |

---

## Deviations observed during recording

- **The record prompt names a Node/pnpm gate example; this toolkit is Python/uv.** `prompts/record-implementation-results.md` uses `pnpm install` / `pnpm -r lint` / etc. as illustrative commands, and `pr.md` keys gates off the repo's actual stack: this repo has `pyproject.toml`/`uv.lock`, so its gates are `uv sync --frozen` and `uv run --frozen pytest`. The run installed and tested with the `uv` gates and additionally ran the AGENTS.md gate set (build, doctor, agents validate, prompts check) that previous phase-02 records ran. No `pnpm` command was run because this repo has no `pnpm-workspace.yaml`.
- **The full-suite gate scrubs the recorder's own run identity.** `uv run --frozen pytest` was wrapped as `env -u AIDW_RUN_ID -u AIDW_STAGE` because the recorder's ambient `AIDW_RUN_ID`/`AIDW_STAGE` leak into the pytest process and break two pre-existing, unrelated tests (`test_cli_gate_run_propagates_a_failing_exit_code`, `test_cli_gate_run_records_into_the_branch_run_without_an_env_identity`) that assume no ambient run identity. CI runs the bare command in a clean environment; the L1.2 record used the same scrub. The gate's command string is therefore env-wrapped, so a `/pr` run of the bare `uv run --frozen pytest` will not `reused:`-match it; the recorded `607 passed` is nonetheless this run's own observation of tree `2a3f9226e36d`.
- **Every gate printed the EXTRACTION.md §3.10 single-checkout warning.** This toolkit checkout is a single working tree, so `_roots` emits the advisory before each command. It is the intended warning, not a gate failure.
- **No task-specific command beyond the full suite was named.** The task prompt's tests are all `tests/test_prompt_workflow.py` fake-stage tests and a rendered-prompt assertion; there is no separate live CLI gate, so all task-specific rows are derived from the single full-suite invocation.

---

## Non-Goals (NOT implemented)

- ❌ L1.2's predecessor gate, L1.1's base-branch check, `--no-fetch`, `--allow-incomplete-prereqs` — not modified or reordered (task prompt, Explicit non-goals).
- ❌ E2.4's branch-setup stage and E2.5's control-worktree/branch creation; the branch instructions stay in `prompts/task-prompt.md` and the `agents/task-author/AGENTS.md` branch line is not reworded (E7.4 owns that) (task prompt, Explicit non-goals).
- ❌ No resume path for a blocked run, no new run status or exit code, no change to `state.json`'s schema, and no auto-retry of a blocked author (task prompt, Explicit non-goals).
- ❌ No E7.1 bucket split: the rest of `prompts/task-prompt.md` is unchanged and no product-specific wording was added (task prompt, Explicit non-goals).
- ❌ No change to the reviewer/fixer prompts or the review loop (L2/L3 own those) (task prompt, Explicit non-goals).
- ❌ No `design.md` §17 entry — L6.2 consolidates phase 02's decisions (task prompt, requirement 7).
- ❌ No PR opened and nothing committed by this stage (record-implementation-results non-goals; `pr.md` owns delivery).

---

## Deliverables Checklist

- [x] `prompts/task-prompt.md` — feasibility-before-branch step, three reason classes, empty-reason rule, extended `IMPORTANT:` line.
- [x] `agents/task-author/AGENTS.md` — same rule and `blocked: <reason>` output contract.
- [x] `aidw/workflows/prompt.py` — blocked detection before path resolution, `BLOCKED`/exit 3, leftover reporting.
- [x] `tests/test_prompt_workflow.py` — blocked path, ordering, leftover/branch warnings, parsing, empty-reason and empty-output cases, rendered contract.
- [x] `design.md` — §8.1 author-stage description and §10 condition row.
