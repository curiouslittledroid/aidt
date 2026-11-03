# Build Results — 00-E4.1: Stage registry and workflow definitions as data

**Branch:** `00-E4.1`
**Date:** 2026-11-03
**Spec:** `docs/migration/EXTRACTION.md` §3.5 (stage and workflow model, `PlanStage`, stage ids), §3.4 (workflow config shape and precedence), §2 (D2, D4, D12, D13, D14) and §10 (R6, R11); `design.md` §3 (layout), §8.1–§8.5 (workflow chains and notation); `docs/task-prompts/00-E4.1-prompt.md`

## Summary

**Purpose:** Turn AIDT's five hardcoded workflow chains into one declarative, importable registry keyed by workflow and retained stage id, so later tasks can build plans from data instead of editing `build_plan` and four run loops.

| Decision | Why it matters |
|----------|---------------|
| The registry owns its own `StageDefinition`/`PlannedStage` types instead of importing `PlanStage` from `aidw/workflows/implement.py` | E4.3 inverts the dependency (`implement.py` → registry); importing back would be a cycle, and `target_config.py` forbids importing workflow modules. The fields match §3.5 exactly. |
| Stage ids stay R6's retained vocabulary (`I1`–`I6`, `P1`, `P2`, `R1`, `R2`, `F1`–`F4`, `A1`), not §3.4's illustrative `author`/`review`/`implement` | §3.4's ids illustrate the YAML schema shape only; R6 says ids are retained, and `id` is a different field from the runtime `name` (`"I1"` vs `"impliment-task"`). |
| Loops are a minimal declarative `LoopDefinition` (`head`/`body`/`tail`, `terminal_last`, `unprimed_first`) plus `when`, not a flat stage list | A flat list cannot express the bounded review loop or the `if findings` conditionals. `terminal_last` is H6/G2/L4.1's review-only terminal review; `unprimed_first` is L2.3's unprimed first round. |
| The prompt loop's finding partition is input (`FixBatch`), not branching inside the expander | Per-blocking-finding, one combined could-fix, and the single unparseable-review fallback are concrete inputs; keeping the expander pure and deterministic follows from that. |
| `extra` templates and the delta/reconcile/whole-review renderers live in the registry, pinned against the workflow modules' copies | "Byte for byte" includes the I2/F2/R2/F4 extras and the delta/reconcile briefs; the tests compare registry output with today's `build_plan`/`prompt.py`/`review.py`/`fix.py` so duplicated text cannot drift before E4.3 deletes the originals. |
| The `implement` default records `parallel_groups=(("test", "update-architecture"),)` as data only | R11/§3.4 make groups stage *names*; `implement.py`'s `by_name` lookup keys on those names. E4.4 owns replacing and validating the hardcoded pair. |
| Defaults are frozen dataclasses in a `MappingProxyType`; `variables` are tuples | The expander must be pure: a caller cannot mutate shared defaults through an expansion result. |

**Where it fits in the roadmap:** E4.1 of the config-driven-stages epic. It consumes E3.4's seeded `ConfigDefaults` and the §3.5 stage model, and provides the data E4.3 (config-driven plans), E4.4 (`parallel_groups` replacement), E4.5 (core vs repo-optional enforcement), E4.6 (agent/model overrides) and E4.7 (fixture integration) build on. E4.2's prompt resolver and E4.3's plan wiring are explicitly separate.

**Scope:** Adds one new toolkit module and its pinning test suite, and marks E4.1 complete on the extraction roadmap. It deliberately stops short of rewiring any workflow: `implement.py`, `prompt.py`, `review.py`, `fix.py`, `approve.py`, `target_config.py`, `resolve_config`, `ConfigDefaults.workflows`, prompts and agent configs are untouched.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `aidw/stage_registry.py` | Created | Declarative defaults for `implement`/`prompt`/`review`/`fix`/`approve`: frozen `StageDefinition`, `LoopDefinition`, `WorkflowDefinition`, `FixBatch` and `PlannedStage` shapes, the retained stage-id vocabulary, `extra`/brief templates, and the pure `expand()` plus `get_workflow`/`stage`/`stages_by_id` lookups and fail-closed errors. |
| `tests/test_stage_registry.py` | Created | 43 pinning/contract tests: byte-for-byte equality with `build_plan` for the default and a non-default base branch, the post-phase-02 prompt loop order (reconcile per batch, review-only terminal), unparseable fallback, delta/reconcile brief parity, R1/R2/A1/`iterN-*` fix stages with variables and extras, no-I/O purity, immutability and independent second expansion, plus a deterministic invariant sweep. |
| `docs/task-prompts/00-E4.1-prompt.md` | Created | Task prompt recording requirements, traps, non-goals and deliverables for E4.1 (committed by an earlier stage). |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E4.1 complete on the extraction roadmap. |

---

## Verification Results

Every gate was run once through `aidw gate run <key> $SCOPE -- <command>` with `SCOPE="--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts"` — the document this stage writes plus the other stages' write-targets. Every outcome below is a real observation against tree `252ba552f66a` from this run; no number was copied from another document. `AIDW_STAGE`/`AIDW_RUN_ID` were removed from the child environment for the pytest and `aidw` commands so the recorder's ambient identity did not leak into the suite, matching CI.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `aidw gate run install $SCOPE -- uv sync --frozen` | ✅ `Checked 15 packages in 2ms` — frozen lock consistent (gate `install`, tree `252ba552f66a`, stage `record-implementation-results`, 2026-11-03T12:55:40Z) |
| Build | `aidw gate run build $SCOPE -- uv build --out-dir <tmp>` | ✅ Built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` into a `mktemp -d` (gate `build`, tree `252ba552f66a`, stage `record-implementation-results`, 2026-11-03T12:55:44Z) |
| Test | `aidw gate run suite $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ✅ `1074 passed in 25.13s`, no failures, skips or deselections (gate `suite`, tree `252ba552f66a`, stage `record-implementation-results`, 2026-11-03T12:56:11Z) |
| Doctor | `aidw gate run doctor $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw doctor` | ✅ exit 0 — 19 checks: 0 failed, 2 warnings (dirty working tree, missing `.mcp.json`); `target config` reports `none (defaults)` (gate `doctor`, tree `252ba552f66a`, stage `record-implementation-results`, 2026-11-03T12:56:14Z) |
| Agents validate | `aidw gate run agents-validate $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw agents validate --strict` | ✅ exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `252ba552f66a`, stage `record-implementation-results`, 2026-11-03T12:56:17Z) |
| Prompts check | `aidw gate run prompts-check $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw prompts check` | ✅ exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `252ba552f66a`, stage `record-implementation-results`, 2026-11-03T12:56:17Z) |
| Whitespace | `git diff --check` | ✅ exit 0, no whitespace errors |
| Lint | `pnpm -r lint` | **unverified** — this repository is Python/uv and configures no linter or formatter (`AGENTS.md` "Gates": pytest is the only verification; none was added in this task). There is no `package.json`/pnpm workspace. |
| pnpm build / test | `pnpm -r build`, `pnpm -r test` | **unverified** — no pnpm workspace in this repository; the equivalent build and test gates above (`uv build`, `uv run pytest`) passed. |

### `uv run --frozen pytest` (full suite)

Counts derive from the single full-suite gate invocation above. The per-file count is collection-only (`pytest tests/test_stage_registry.py --collect-only -q -n0`, which executes no test) and confirms the file's contribution to the 1074; no test was re-run for a row.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1074 | ✅ Pass (`1074 passed in 25.13s`) |
| `tests/test_stage_registry.py` | 43 | ✅ Pass (all part of the full-suite run) |

### Task-specific verification gates

Each row names a test from `tests/test_stage_registry.py` that ran as part of the single full-suite invocation above.

| Gate | Status |
|------|--------|
| `implement` default reproduces `build_plan` byte-for-byte (ids, names, agents, prompt files, variables, I2 extra) for `main` and a non-default base branch | ✅ `test_implement_default_reproduces_build_plan` (both parameters) passed |
| `implement` defaults `base_branch` to `main` and records the `parallel_groups` pair as stage names | ✅ `test_implement_defaults_base_branch_to_main`, `test_implement_records_the_parallel_group_as_stage_names` passed |
| Stage-id vocabulary is the retained R6 set | ✅ `test_retained_stage_ids_are_the_vocabulary` passed |
| Prompt loop reproduces the post-phase-02 order (reconcile per batch, review-only terminal), with per-stage agent/prompt/variables | ✅ `test_prompt_loop_reproduces_todays_run_loop_order`, `test_prompt_loop_agents_prompts_and_variables_per_stage` passed |
| Prompt loop: finding blocks, unprimed round 1, approving first round, unparseable fallback, blocking-only batch, revision-budget refusal | ✅ `test_prompt_fix_batch_carries_the_rendered_finding_blocks`, `test_prompt_round_one_is_unprimed_and_later_rounds_carry_the_delta_brief`, `test_prompt_approving_first_round_plans_author_and_one_review`, `test_prompt_unparseable_review_expands_to_one_fallback_stage`, `test_prompt_parsed_batch_with_only_blocking_findings_has_no_combined_stage`, `test_prompt_loop_fails_closed_beyond_the_revision_budget` passed |
| Delta/reconcile briefs match the workflow renderings, including the diff-unavailable note | ✅ `test_delta_brief_matches_the_workflow_rendering`, `test_delta_brief_unavailable_note_matches_the_workflow`, `test_reconcile_brief_matches_the_workflow_rendering` passed |
| Review R1/R2 (R2 conditional on findings), approve A1, and the fix loop's `iterN-*` stages match today's code, including extras | ✅ `test_review_chain_reproduces_r1_and_r2`, `test_review_without_findings_omits_r2`, `test_approve_chain_reproduces_the_single_stage`, `test_fix_expansion_reproduces_the_dry_run_plan`, `test_fix_iteration_is_part_of_the_stage_names` passed |
| Expander is pure: no I/O, no workflow import, no mutation of defaults or inputs, independent second result, fail-closed lookups/fields, loop invariants across the input space | ✅ `test_expansion_does_no_io`, `test_the_registry_module_imports_no_io_or_workflow_module`, `test_expansion_does_not_mutate_the_defaults_or_the_input_fields`, `test_a_second_expansion_is_equal_but_independently_owned`, `test_unknown_workflow_and_stage_fail_closed`, `test_missing_or_wrong_expansion_fields_fail_closed`, `test_loop_invariants_hold_for_every_budget_and_batch_count` passed |

---

## Deviations observed during recording

- **The change set is larger than the task prompt's "only the two new files".** The recorded tree also contains the E4.1 task prompt (committed earlier) and the roadmap checkbox promotion in `docs/tasks/00 - Extraction.md` (traceability update made before this stage). No implementation code, workflow module, prompt or agent config was modified; `aidw/workflows/*` and `aidw/target_config.py` are untouched, as required.
- **The task prompt's pnpm gate list does not apply.** Its generic template names `pnpm install`/`pnpm -r lint|build|test`, but this repository's `AGENTS.md` gate is `uv sync --frozen` plus pytest/doctor/agents/prompts. The rows above record the real repository gate and mark the pnpm commands unverified rather than inventing equivalents.

---

## Non-Goals (NOT implemented)

- ❌ E4.2 prompt resolver (D14 precedence, verifying Pi's `--prompt-template` precedence) — separate task.
- ❌ E4.3 porting `build_plan` and the workflows to build stage lists from the registry, and deleting the hardcoded chains — this task only adds the registry plus the pinning test; `implement`/`prompt`/`review`/`fix`/`approve` are not rewired.
- ❌ E4.4 `parallel_groups` replacement and member validation — the default pair is recorded as data only; `implement.py` keeps its hardcoded pair.
- ❌ E4.5 core vs repo-optional enforcement (D12/D13 refusals) — separate.
- ❌ E4.6 agent/model/thinking/timeout overrides and E4.7 fixture integration test — separate.
- ❌ E6 GitHub-config defaults and E7 prompt-library split — unrelated epics.
- ❌ No commit, push or PR opened (owned by `pr.md`).
