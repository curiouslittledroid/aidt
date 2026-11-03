# Build Results — 00-E4.3: Config-driven plans

**Branch:** `00-E4.3`
**Date:** 2026-11-03
**Spec:** `docs/migration/EXTRACTION.md` §3.5 (stage and workflow model), §3.4 (target-repo config, four-level prompt precedence), §2 (locked decisions D2, D4, D12, D13, D14), §3.11 (compatibility preflight), §3.12 (directory layout); `design.md` §8.1–§8.5 (workflow specifications) and §3 (layout)

## Summary

**Purpose:** Make `aidw.runner.plan_stages` the single run-path plan builder for all five workflows, so every stage list derives from the `aidw.stage_registry` defaults and a target repo's declared `prompt:` overlay instead of a hand-built list (D2/D14).

**Key design decisions**

| Decision | Why it matters |
|----------|---------------|
| `plan_stages` expands the registry and maps each `PlannedStage` through `resolve_prompt`, carrying `id`, `variables` (tuple → list) and `extra` byte for byte | One builder serves every workflow and every dynamic round/iteration, so the registry is the only stage-list source of truth and the existing dry-run baselines stay byte-identical. |
| The repo-declared `workflows.<name>.stages` list is an **overlay matched by `id`**, never a mirror of registry order or size | §3.4's list is a whole-list override; matching by position would silently mis-resolve prompts when a repo declares a subset or an added stage. Only `source == config` entries overlay. |
| Only `prompt:` is honoured; `agent`, `enabled: false` and unknown ids each draw exactly one deferred `warning:` line per entry naming the workflow, id and all reasons | E4.5/E4.6 own enforcement; warning per entry (not per field) prevents a no-op from being silent while keeping the deferred work out of this task. |
| `build_plan` becomes a thin wrapper over `expand("implement", …)` and `PlanStage` is deleted | The wrapper preserves the tests/compat seam, but `implement`'s run path goes through `plan_stages` so config overrides actually apply. |
| Implement/review/fix/approve share `target_config.resolve_workflow_config` for the two fail-closed config refusals | Replicates `aidw prompt`'s config-ERROR and `check_compatibility` refusals (exit 2, before run state, `--dry-run` included) without copying them five times; `validate_paths` stays prompt-only because these trees need not carry its read paths. |
| Delta/reconcile/brief renderers move to the registry; workflows call the pure registry helpers and compose the evidence pointer workflow-side | Removes the duplicated prose E4.1 deliberately left in place; the registry owns stage wording, while payload (previous review, diff, snapshots) and the L2.4 pointer stay in the loops that have them. |

**Where it fits in the roadmap:** Extraction phase E4 (config-driven workflows). Depends on E1.x (runner/argv plumbing), E4.1 (`stage_registry` defaults + `expand`) and E4.2 (`resolve_prompt` precedence). It is the prerequisite for E4.4 (`parallel_groups` from config), E4.5 (core vs repo-optional enforcement), E4.6 (agent/model/thinking/timeout overrides) and E4.7 (the six-behaviour fixture integration test).

**Scope:** Touches the plan builder and its config preflight seam, all five workflow modules, the registry's stage-text ownership, the roadmap checkbox, and the unit/contract tests. Deliberately stops short of enforcing deferred stage settings, replacing the hardcoded parallel pair, agent/model overrides, the fixture integration test, and any change to `resolve_config`/`ConfigDefaults.workflows` or `aidw config show`.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E4.3-prompt.md` | Created | Task prompt for this task (written by an earlier stage). |
| `tests/test_plan_stages.py` | Created | 30 contract/metamorphic tests for `plan_stages`: per-workflow vectors, the D14 overlay, deferred warnings, fail-closed and purity, and the invariant sweep. |
| `aidw/runner.py` | Modified | Adds `plan_stages` and `_stage_prompt_overlays` (registry expansion + prompt overlay + deferred warnings) and `StageSpec.id`. |
| `aidw/stage_registry.py` | Modified | Updates the ownership docstrings: E4.3 is the deletion point for the workflows' duplicate renderers; registry text is now the single home. |
| `aidw/target_config.py` | Modified | Adds `resolve_workflow_config`, the shared config-ERROR + compatibility preflight that returns a resolved config or the issues to print. |
| `aidw/workflows/implement.py` | Modified | Rewires `run()`/dry-run to `plan_stages`; `build_plan` is a wrapper over `expand`; `PlanStage` and `_TEST_CONTEXT` removed; shares the config preflight. |
| `aidw/workflows/prompt.py` | Modified | Re-expands each round through `plan_stages`, reads the brief marker off planned stages, uses registry `render_delta_brief`/`render_reconcile`, deletes the duplicated renderers/constants, and shares the config preflight. |
| `aidw/workflows/review.py` | Modified | Plans R1/R2 through `plan_stages` with `findings=True` and the pinned `MANIFEST_REL`; removes the rebuilt R2 `extra`; shares the config preflight. |
| `aidw/workflows/fix.py` | Modified | Plans each iteration through `plan_stages` (`round_index`/`iteration`/manifest path), uses registry `FIX_TEST_CONTEXT_EXTRA`, and shares the config preflight. |
| `aidw/workflows/approve.py` | Modified | Plans A1 through `plan_stages`, attaching the approval postcondition workflow-side; shares the config preflight. |
| `tests/test_implement_workflow.py` | Modified | `build_plan` assertions updated to the `PlannedStage` tuple variables and the reworked implement plan path. |
| `tests/test_prompt_workflow.py` | Modified | Deleted-renderer references moved to the registry twins; real-run delta/reconcile extra content assertions kept. |
| `tests/test_stage_registry.py` | Modified | Mechanical `build_plan` tuple comparisons and the brief pins rewritten around the registry's single renderers. |
| `tests/test_target_config.py` | Modified | The import-direction test now pins `prompt.py → target_config.resolve_workflow_config`, still never the reverse. |
| `docs/tasks/00 - Extraction.md` | Modified | E4.3 marked complete (traceability stage). |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 2ms` (already locked/synced) |
| Build | `uv build --out-dir <tmp>` | ✅ gate `build` passed — built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` |
| Test | `uv run --frozen pytest` | ✅ gate `suite` passed — `1124 passed in 26.97s` |
| Doctor | `uv run --frozen aidw doctor` | ✅ `19 checks: 0 failed, 2 warning(s)` (warnings: dirty working tree, missing `.mcp.json`) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` |
| Whitespace | `git diff --check` | ✅ clean |

`build` and `suite` were run in this stage against tree `d5148c04f55c` (not reused from an earlier stage), with the declared scope
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.
The recorded outcomes were:

- `passed: gate 'build' passed for tree d5148c04f55c at 2026-11-03T23:20:33Z by stage 'record-implementation-results' (Successfully built …/aidt-0.1.0-py3-none-any.whl)`
- `passed: gate 'suite' passed for tree d5148c04f55c at 2026-11-03T23:21:02Z by stage 'record-implementation-results' (1124 passed in 26.97s)`

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1124 | ✅ Pass (`1124 passed in 26.97s`) |
| `tests/test_plan_stages.py` (new) | 30 collected | ✅ Pass — part of the full-suite run above (collection count, no second execution) |
| `tests/test_stage_registry.py` | 43 collected | ✅ Pass — part of the full-suite run above (collection count, no second execution) |
| `tests/test_implement_workflow.py` | 43 collected | ✅ Pass — part of the full-suite run above (collection count, no second execution) |
| `tests/test_prompt_workflow.py` | 154 collected | ✅ Pass — part of the full-suite run above (collection count, no second execution) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Per-workflow plans reproduce the pinned registry stage lists (implement six, review R1+R2, fix approval+iteration, approve A1, prompt author+review, prompt with a fix batch) | ✅ `test_implement_plan_is_the_six_registry_stages`, `test_review_plan_is_r1_plus_the_r2_manifest_pointer`, `test_fix_plan_is_the_approval_plus_one_iteration`, `test_approve_plan_is_the_single_a1_stage`, `test_prompt_plan_without_rounds_is_author_and_one_review`, `test_prompt_plan_with_a_batch_carries_the_fix_stage_and_reconcile` |
| Explicit `prompt:` overlay (D14) sets `explicit_prompt`, resolves the declared file, beats a same-named shadow, and renders through a dry-run stage | ✅ `test_declared_prompt_sets_explicit_prompt_and_resolves_it`, `test_declared_prompt_beats_a_same_named_target_shadow`, `test_declared_prompt_override_is_rendered_by_a_dry_run_stage`, `test_overlay_applies_to_every_instance_of_a_repeated_stage_id` |
| Whole-list config treated as an overlay, not a registry mirror; no `workflows` section plans pure defaults | ✅ `test_a_repo_without_a_workflows_section_plans_pure_defaults`, `test_the_repo_declared_list_is_an_overlay_not_a_mirror` |
| Deferred-field warnings: one stderr line per entry naming workflow, id and every reason; prompt-only entry silent | ✅ `test_one_entry_with_agent_and_disabled_draws_one_line_naming_both`, `test_an_unknown_stage_id_draws_one_line_naming_it`, `test_a_two_entries_are_counted_per_entry_not_per_field`, `test_a_prompt_only_entry_draws_no_warning` |
| Fail-closed and purity: declared-but-missing prompt raises with no fallback; no I/O beyond prompt existence; config/registry unmutated | ✅ `test_a_declared_but_missing_prompt_raises_and_falls_back_nowhere`, `test_plan_stages_does_no_io_beyond_prompt_existence`, `test_plan_stages_mutates_neither_the_config_nor_the_registry`, `test_each_call_returns_fresh_objects` |
| Builder output equals registry expansion for every workflow; overlay never changes plan shape | ✅ `test_every_workflow_plans_exactly_the_registry_expansion`, `test_a_declared_overlay_never_changes_a_plans_shape` |
| Five workflow dry-run outputs unchanged (the existing tests are the baseline) | ✅ Full suite green including the five dry-run tests (`test_dry_run_plans_locate_and_all_six_stages` (implement), `test_prompt_workflow_dry_run`, `test_dry_run_plans_both_stages` (review), `test_dry_run_lists_child_and_plans` (fix), `test_dry_run_plans_stage_and_gate` (approve)) |
| Prompt loop's real-run extras survive the rewire (delta brief round ≥ 2, reconcile per fix batch, pointer composed in front) | ✅ `test_second_round_gets_delta_brief_with_previous_review_and_diff`, `test_l34_reconcile_extra_carries_instruction_review_diff_and_pointer` in `tests/test_prompt_workflow.py` |
| `build_plan` is a wrapper returning `list[PlannedStage]`; `PlanStage` and the workflow renderer copies are gone | ✅ Full suite green; `git diff` shows `PlanStage` removed from `implement.py` and `_render_delta_brief`/`_render_reconcile` removed from `prompt.py` |

---

## Deviations observed during recording

- **Prompt's generic gate commands are pnpm-shaped** — this repository's stack is Python/uv (`pyproject.toml`/`uv.lock`), so the uv gates named in `AGENTS.md` and `pr.md` were run instead of `pnpm install` / `pnpm -r lint|build|test`. No linter/formatter/type-checker is configured (design §15), so there is no `lint` gate row.
- **The change set was uncommitted when recording started** — only the task prompt was committed on the branch; the implementation, tests and roadmap update were in the working tree. The gates therefore ran against the working tree relative to `main`, which is the change set this document records.

---

## Non-Goals (NOT implemented)

- ❌ E4.4 `parallel_groups` replacement and validation — the implement pair remains hardcoded; the registry records it as data only.
- ❌ E4.5 core vs repo-optional enforcement (reorder/disable refusals, honouring `enabled: false`, accepting repo-added stages) — E4.3 only warns on those deferred fields.
- ❌ E4.6 agent/model/thinking/timeout overrides — E4.3 warns on `agent` and keeps the registry default agent.
- ❌ E4.7 the six-behaviour fixture integration test against `fixtures/target-repo/`.
- ❌ E6 GitHub-config defaults and E7 prompt-library split.
- ❌ Seeding `ConfigDefaults.workflows` or changing `resolve_config` output / `aidw config show`.
- ❌ No PR opened, no push, no merge — delivery is `/pr`'s job.
