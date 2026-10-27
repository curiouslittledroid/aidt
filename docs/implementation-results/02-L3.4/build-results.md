# Build Results — 02-L3.4: Reconcile after each fix batch

**Branch:** `02-L3.4`
**Date:** 2026-10-27
**Spec:** `docs/tasks/02 - Prompt loop integrity.md` (L3.4), `design.md` §8.1
**Run id:** `20261027T095247Z-02-L3.4-implement`

## Summary

**Purpose:** Add one `task-review-reconcile-N` stage per fix batch to the P2a prompt fix loop, so
that fixes applied one finding at a time (or as a could-fix / whole-review batch) are reconciled
against the full review and the batch's combined diff before the next review — or, on the final
round, before terminal acceptance.

| Decision | Why it matters |
|----------|---------------|
| Reuse the `task-fixer` agent and `prompts/task-review-fixes.md`; carry the reconcile instruction in `extra=` | Keeps the shipped bucket-(i) prompt generic (EXTRACTION.md §4.2) and adds no prompt file or `REQUIRED_PROMPTS` entry, mirroring L2.3's `_DELTA_BRIEF_INSTRUCTION` |
| New `_RECONCILE_INSTRUCTION` constant rather than reusing `_DELTA_BRIEF_INSTRUCTION` | The delta brief orders the *reviewer* to emit `resolved` / `not resolved` / `newly contradicted`; the fixer must reconcile, not review |
| Stage named `task-review-reconcile-N` | Does not match `task-review-fixes-*` (L3.3 snapshot writer) or `task-review-N` (`_fix_round` / harness `fix_status`), so neither mis-handles it |
| Placed after the fix if/else and before `if revisions >= MAX_REVISIONS: break` | Covers all three fix paths (per-finding, could-fix-only, whole-review fallback) and reconciles the final round's fixes, which are otherwise never reviewed pre-L4.1 |
| Combined diff is `baseline_prompt` → `_capture_prompt(prompt_path)` captured before the reconcile stage runs | The diff is the fix batch's net effect, not one finding's edit and not polluted by the reconcile edit itself |
| Non-`SUCCEEDED` reconcile stops the run (`return 1`) | Matches the fix-stage failure contract with no new status vocabulary |

**Where it fits in the roadmap:** Phase 02 ("Prompt loop integrity"), Epic L3. It follows L3.3
(snapshots) and precedes L4.1 (terminal review), which will remove the final-round fix batch that
this task's final-round reconcile deliberately papers over. L4.2 owns per-round recording in
`state.json` / `run.log`, and L6.2 owns the `design.md` §17 decision entry and the E4.1/E4.3
re-baselining this change implies.

**Scope:** Touches `aidw/workflows/prompt.py` and `tests/test_prompt_workflow.py`, and flips the
L3.4 checkbox in the phase roadmap. It deliberately stops short of changing `MAX_REVISIONS` or the
terminal acceptance path, recording any new per-round field, extending L3.3's `.prompt.md`
snapshots to the reconcile stage, and adding any prompt or agent config.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L3.4-prompt.md` | Created | Task prompt for L3.4 (committed on the branch) |
| `aidw/workflows/prompt.py` | Modified | Add `_RECONCILE_INSTRUCTION`, `_render_reconcile()`, and the per-round `task-review-reconcile-N` stage in `run()` |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified | Mark L3.4 done |
| `tests/test_prompt_workflow.py` | Modified | Extend `_fake_stages` with a `reconcile_status` knob, update the exact-sequence assertions, add five L3.4 tests |

---

## Verification Results

Repo gates are the ones `AGENTS.md` names ("run exactly these, and only these") and `prompts/pr.md`
selects for a `pyproject.toml` / `uv.lock` tree. Each command was run through
`aidw gate run <key> -- <command>` with the shared scope
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`,
and recorded against tree `2419d22d0c42` in run `20261027T095247Z-02-L3.4-implement`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.79ms` (exit 0) |
| Test | `uv run --frozen pytest` | ✅ `644 passed in 77.09s` — gate `suite`, tree `2419d22d0c42`, stage `record-implementation-results`, 2026-10-27T10:21:31Z |
| Doctor | `uv run --frozen aidw doctor` | ✅ `14 checks: 0 failed, 2 warning(s)` — gate `doctor`, tree `2419d22d0c42`, stage `cli`, 2026-10-27T10:21:43Z |
| Agent configs | `uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` — gate `agents`, tree `2419d22d0c42`, stage `cli`, 2026-10-27T10:21:44Z |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` — gate `prompts`, tree `2419d22d0c42`, stage `cli`, 2026-10-27T10:21:45Z |
| Whitespace | `git diff --check` | ✅ no output (exit 0) |

The two `doctor` warnings are the expected dirty working tree on branch `02-L3.4` and a missing
optional `/.mcp.json`; neither is a failure. `uv build` is not one of this repo's named gates and
was not run.

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 644 | ✅ Pass (`644 passed in 77.09s`) |

The five new cases — `test_l34_approve_runs_no_reconcile`,
`test_l34_blocked_runs_no_reconcile`,
`test_l34_reconcile_extra_carries_instruction_review_diff_and_pointer`,
`test_l34_reconcile_failure_stops_the_run`,
`test_l34_render_reconcile_is_pure_and_degrades_when_unreadable` — plus the updated
exact-sequence assertions are all inside this single run; no separate subset count was produced.

---

## Deviations observed during recording

- **Generic prompt template named pnpm gates; this repo is Python/uv.** The task prompt shipped in
  `prompts/record-implementation-results.md` uses pnpm examples, and `prompts/pr.md` says to take
  the commands "from the target repo". This repo's `AGENTS.md` names exactly `uv sync --frozen`,
  `uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents validate --strict` and
  `uv run aidw prompts check`; those are the rows above. No lint/build/type gate exists here.
- **A first `suite` run failed on ambient stage identity.** The literal
  `aidw gate run suite -- uv run --frozen pytest` inherited this stage's `AIDW_RUN_ID` and
  `AIDW_STAGE` and failed 2 pre-existing tests —
  `tests/test_verification.py::test_cli_gate_run_propagates_a_failing_exit_code` and
  `::test_cli_gate_run_records_into_the_branch_run_without_an_env_identity` — with
  `2 failed, 642 passed` (gate `suite`, tree `2419d22d0c42`, 2026-10-27T10:19:20Z). Both reproduce
  with the variables set and pass with them cleared, so they are an environment interaction with
  the gate-CLI tests, not a regression from this change. The suite was re-recorded with
  `AIDW_RUN_ID` and `AIDW_STAGE` cleared for the child process (the environment the repo's own
  tests assume) and passed `644 passed` (gate `suite`, tree `2419d22d0c42`, stage
  `record-implementation-results`, 2026-10-27T10:21:31Z). The earlier failed outcome remains in the
  run's gate history.
- **`doctor` / `agents` / `prompts` are recorded under stage `cli`.** Their child process was run
  with `AIDW_STAGE` cleared, so `aidw gate run` cited its `cli` default as the origin rather than
  `record-implementation-results`. They were not re-recorded.

---

## Non-Goals (NOT implemented)

- ❌ L4.1 (terminal review / reserve the last slot for review / change `MAX_REVISIONS` semantics)
  — the next task. L3.4's final-round reconcile is prompt-fixed here and L4.1 reshapes the terminal
  path. (Task prompt, explicit non-goals)
- ❌ L4.2 (per-round recording in `state.json` / `run.log`) — no reconcile count or new recorded
  field was added. (Task prompt, explicit non-goals)
- ❌ Extending L3.3 `.prompt.md` snapshots to the reconcile stage — L3.3's scope stays
  `task-review-fixes-*`. (Task prompt, explicit non-goals)
- ❌ E4.1/E4.3 re-baselining and the `design.md` §17 decision entry — L6.2 owns them. (Task prompt,
  explicit non-goals)
- ❌ No new prompt file or agent config, and no edit to `prompts/task-review-fixes.md` or
  `agents/task-fixer/AGENTS.md` — L3.1/L3.2 own their text. (Task prompt, explicit non-goals)
- ❌ No commit, push, or PR — `prompts/pr.md` owns delivery. (Implicit non-goal of this stage)
