# Build Results — 05-W1.2: `--dry-run` must not create a run or become a `--resume` target

**Branch:** `05-W1.2`
**Date:** 2026-11-20
**Spec:** `design.md` §8.2 (`aidw implement` dry-run planning), §9.1/§9.4 (run lock and resumability), §17 row `Z14`, §19 items 8–10 (dry-run "no run state" acceptance criteria); roadmap entry W1.2 in `docs/tasks/05 - Pipeline efficiency.md`; `docs/task-prompts/05-W1.2-prompt.md` (including the owner-resolved points c1–c3)
**Pull request:** not yet opened — the /pr stage records it here once the PR exists

## Summary

**Purpose:** Make every `--dry-run` a pure plan — no run directory, no `state.json`, no `run.log`, no rendered prompt, no stage record — so a dry run can never become a `--resume` target or leave a phantom "all stages succeeded" run behind.

| Decision | Why it matters |
|----------|---------------|
| The rule is decided once: a dry run creates no run at all, uniformly across all five workflows and `aidw exec` | The roadmap Notes offered two options; the live 05-S1.2 observation (`20261119T233947Z-05-S1.2-implement` recorded all nine stages succeeded without invoking Pi, and would have captured the next genuine `--resume`) forced the stronger rule. Applying it once avoids five divergent dry-run behaviours. |
| A never-invoked-Pi run is not resumable, enforced structurally | No run is recorded, so `_latest_implement_run`/`_latest_prompt_run` can never select a phantom. No legacy-phantom detector or `state.json` marker is added; `runs/` is machine-local operator state (AGENTS.md). |
| The write-free planning substitute is `NullLogger` + `planned_run`, with `run_stage`'s signature unchanged | `RunLogger`'s constructor mkdirs the run directory and `create_run` publishes state. Two additive helpers avoid either write without pushing `None` branches through the shared seam or every call site (owner decision c1). |
| A plan names no run id and uses literal planned paths | No run was created, so a printed id would identify nothing. Plans use `PLANNED_RUN_ID = "<planned>"` and `PLANNED_RUN_DIR_TEXT = "<run dir>"` so two dry runs are byte-identical and no fabricated run id is printed (owner decisions c2/c3). |
| The one-run-per-worktree lock is still acquired in dry-run | A dry run must still refuse with exit 4 when a peer holds the worktree lock (§19 item 8, §9.1); only the run-state writes are skipped. |
| `aidw exec --dry-run` follows the same rule and drops the `rendered:` line | `exec` shares the `run_stage` seam; a planned path would fabricate the run id the rule forbids, so the echo is removed outright while the real-run echo is unchanged. |

**Where it fits in the roadmap:** Phase 05 ("Pipeline efficiency"), epic W1 ("Write ownership"), task W1.2 — the last entry in epic W1. It follows W1.1 (roadmap write ownership) and closes the second silent gap the epic opens: a preview that silently becomes resumable state. No later task in epic W1 depends on it; the other epics' unchecked tasks are out of scope.

**Scope:** `aidw/runner.py`, `aidw/log.py`, `aidw/state.py`, the five workflows (`implement`, `prompt`, `approve`, `review`, `fix`), `aidw/cli.py`, `design.md` §8.2/§9.1/§9.4/§17/§19, and thirteen re-baselined test modules (the prompt's eight plus five it did not list). It deliberately stops short of resume-selection changes, legacy-phantom cleanup, `aidw run` chain-level dry-run behaviour, and the other epics' work.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `aidw/log.py` | Modified | Added `NullLogger`, a `RunLogger`-compatible logger that performs no mkdir and no file write. |
| `aidw/state.py` | Modified | Added `PLANNED_RUN_ID`, `PLANNED_RUN_DIR_TEXT` and `planned_run()` (identical signature to `create_run`, publishes nothing), factoring the shared construction into `_new_run_state`. |
| `aidw/runner.py` | Modified | Moved the rendered-prompt write and both PLANNED/SUCCEEDED `save()` calls behind `not dry_run`; added `dry_run` to `record_skipped` so it skips its save. |
| `aidw/cli.py` | Modified | `exec --dry-run` now uses `planned_run`/`NullLogger`, creates no run, prints no `run:` or `rendered:` line, and its help reads "Plan only; no writes." |
| `aidw/workflows/implement.py` | Modified | Dry-run uses `planned_run`/`NullLogger`, the literal planned directory, drops its tail `save` and the `run:` line, and rewrites the stale lock comment. |
| `aidw/workflows/prompt.py` | Modified | Same dry-run no-write path and no `run:` line; `_latest_prompt_run` semantics untouched. |
| `aidw/workflows/approve.py` | Modified | Same dry-run no-write path, no run directory and no tail save. |
| `aidw/workflows/review.py` | Modified | Dry-run plans `<run dir>/artifacts/review-manifest.json` through the literal planned directory and writes nothing. |
| `aidw/workflows/fix.py` | Modified | Dry-run guards the artifacts mkdir, plans `<run dir>` manifest/closing-body paths, drops the tail save and records no run. |
| `design.md` | Modified | §8.2/§9.1/§9.4 state the no-run rule, §17 gains the single `Z14` row, and §19 items 8–10 now say "creates no run state". |
| `tests/test_runner.py` | Modified | Re-baselined to assert `run_stage(dry_run=True)` writes no state/rendered prompt while returning a valid record; rendering is checked through the pure render function. |
| `tests/test_cli.py` | Modified | Asserts `exec --dry-run` creates no run and prints no `rendered:` line, the no-writes help, and that a real run still prints the echo. |
| `tests/test_state.py` | Modified | Pins `planned_run`'s literal id, its zero writes and the deterministic planned session id. |
| `tests/test_implement_workflow.py` | Modified | `--dry-run` and `--dry-run --resume` leave the runs tree byte-identical while printing the plan and planned gate. |
| `tests/test_prompt_workflow.py` | Modified | Dry-run creates no run; the E8.2 config-identity assertion moved to a real-run test. |
| `tests/test_approve_workflow.py` | Modified | Dry run prints the plan and creates no run directory. |
| `tests/test_review_workflow.py` | Modified | Dry run prints both stages and creates no run directory. |
| `tests/test_fix_workflow.py` | Modified | Dry run lists the child, plans the loop and creates no run directory. |
| `tests/test_design_doc.py` | Modified | Asserts exactly one W1.2 dry-run §17 row and the §19 "no run state" wording. |
| `tests/test_conventions_injection.py` | Modified | Dry-run render assertions now use the pure render path and assert no rendered file exists. |
| `tests/test_prompt_resolution.py` | Modified | Re-baselined for the dry-run path that writes no rendered prompt file. |
| `tests/test_override_integration.py` | Modified | Re-baselined for the dry-run path that writes no rendered prompt file. |
| `tests/test_plan_stages.py` | Modified | Pins the dry-run plan's `<run dir>` placeholder paths and unchanged runs tree. |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 19 packages in 1ms` |
| Build | — | **unverified** (no build command is configured in `AGENTS.md` or `aidw/conventions.md`; the repo's gate list contains no build step) |
| Test | `uv run aidw gate run suite --ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv run --frozen pytest` | ✅ `reused: gate 'suite' passed for tree 8200590de259 at 2026-11-20T04:44:02Z by stage 'update-traceability' (2281 passed in 50.08s) [scope excludes: docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks]` |
| Doctor | `uv run --frozen aidw doctor` | ✅ `22 checks: 0 failed, 2 warning(s)` (dirty working tree, missing `.mcp.json`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ `0 error(s), 0 warning(s)` for toolkit defaults and resolved repo prompts |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` |
| Lint | — | **unverified** (no linter/formatter/type-checker is configured; `AGENTS.md` §Tests states pytest is the only verification) |
| Whitespace | `git diff --check` | ✅ exit 0, no output |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2281 | ✅ Pass (`2281 passed in 50.08s`) — cited from gate `suite`, tree `8200590de259`, stage `update-traceability`, 2026-11-20T04:44:02Z |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `aidw implement <prompt> --dry-run` and `--dry-run --resume` leave `runs/` byte-identical and still print the plan + planned gate | ✅ Covered by the passing `tests/test_implement_workflow.py` cases in the full suite. |
| `run_stage(dry_run=True)` writes nothing and returns the resolved name/status/agent/model/session | ✅ Covered by the passing `tests/test_runner.py` cases. |
| `aidw exec --dry-run` creates no run and prints no `rendered:` line; real runs still print it | ✅ Covered by the passing `tests/test_cli.py` cases. |
| `prompt`/`review`/`fix`/`approve --dry-run` create no run directory while printing their plans | ✅ Covered by the passing `tests/test_prompt_workflow.py`, `test_review_workflow.py`, `test_fix_workflow.py` and `test_approve_workflow.py` cases. |
| `design.md` §17 has exactly one new W1.2 row and §19 items 8–10 state "no run state" | ✅ Covered by `tests/test_design_doc.py` in the passing suite. |
| Removing the no-write guard in `run_stage` fails a test | **unverified** — the mutation was not separately exercised in this recording run; the re-baselined `tests/test_runner.py` assertions are the intended guard. |

---

## Deviations observed during recording

- **Five test modules beyond the task prompt's eight were re-baselined** — `tests/test_conventions_injection.py`, `tests/test_prompt_resolution.py`, `tests/test_override_integration.py`, `tests/test_plan_stages.py` and `tests/test_state.py` also read a dry run's rendered prompt or pin the new planned-state helpers. This follows from owner decisions c1–c3 and is recorded in design.md §17 `Z14`.
- **`aidw/log.py` and `aidw/state.py` were added to the deliverable set** — the owner-resolved write-free substitute required `NullLogger` and `planned_run`, which the original task prompt did not list as deliverables.
- **The suite was cited from the run's recorded gate, not re-run** — the `aidw gate run suite` invocation reused the `update-traceability` gate for the same scoped tree (`8200590de259`), so the 2281-passed outcome is this run's own recorded observation of this content.
- **No task-specific external gate beyond pytest was named by the prompt** — the prompt lists test modules only, so no additional validator was available to run.

---

## Non-Goals (NOT implemented)

- ❌ Starting the other epics' unchecked tasks (`C1.*` gate commands, `G1.*` review depth, `B1.1` batch fixes, `O1.1` blocked bash) — W1.2 is the last entry in epic W1.
- ❌ Adding a legacy-phantom detector or a `state.json` "never invoked Pi" marker — the fix is structural, and `runs/` is machine-local state the operator owns.
- ❌ Changing resume semantics beyond the dry-run rule: `_latest_implement_run`/`_latest_prompt_run` newest-run selection, the still-running guard, and `I7`'s byte-exact tick postcondition (Z13).
- ❌ Changing `aidw run` chain-level dry-run behaviour (the `--pr 0` placeholder and the `(planned; --dry-run opens no PR)` line).
- ❌ Committing, pushing or opening a pull request — the `/pr` stage owns delivery.
