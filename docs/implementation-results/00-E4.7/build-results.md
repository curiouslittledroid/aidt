# Build Results — 00-E4.7: Override integration test (the acceptance test for E3+E4)

**Branch:** `00-E4.7`
**Date:** 2026-11-04
**Spec:** `docs/migration/EXTRACTION.md` §2 (D4/D12/D13/D14), §3.4, §3.5, §3.6, §3.12; `design.md` §7.3, §15, §17 (N1)

## Summary

**Purpose:** Turn `fixtures/target-repo/` into a committed target repo that exercises every
override behaviour the E3/E4 config surface promises, and prove those behaviours end-to-end in one
integration test at the two seams design §15 names — `plan_stages` and `run_stage(dry_run=True)`.

| Decision | Why it matters |
|----------|---------------|
| The fixture is **configuration**, not code | E4.7 adds no production module: `aidw/config.yaml` declares all six core `implement` ids in registry order plus a repo-added `lint`, and each prompt/agent file is a marker. The test is the acceptance test for the already-implemented E3/E4 mechanisms, not a new mechanism. |
| I3 is declared with `enabled: false` rather than omitted | A declared `stages:` list replaces the static half wholesale (§3.4), so an omitted core id is a `StageListError`. Disabling I3 is the repo-optional proof (D12/D13) without triggering the removal/reorder refusal. |
| The explicit-path prompt is deliberately not named after its stage | `architecture-explicit.md` is reachable only through I4's `prompt:` declaration. A same-named shadow therefore cannot accidentally satisfy the check, which is what makes D14 level 1 the only explanation for the resolved path. |
| The implementer override lives in `aidw/agent-configs/implementer.yaml`, shadowing by `id` | E4.6/N1's global override is an agent-config directory, not a `StageSpec.model`; `tester`/`recorder` keep toolkit defaults. A unique model slug is the argv evidence that the override reached the Pi invocation and no toolkit default can be mistaken for it. |
| Regression sensitivity is one perturbation per behaviour | The `test_perturbing_*`/`test_dropping_*` tests copy the fixture, change exactly one input, and assert that one behaviour disappears. No assertion can stay green because a second mechanism covers for the removed override. |
| No workflow preflight and no real `pi`/`git`/`gh` | The fixture intentionally lacks Mythical Forge's default read-paths; `validate_paths` is E3.7's concern. Driving `plan_stages` plus the dry-run argv keeps the test at design §15's seam and costs no model call. |

**Where it fits in the roadmap:** E4.7 is the acceptance test that closes the E3+E4 extraction work.
It depends on E3's target config, precedence and read-path vocabulary, E4.2's committed fixture
target repo, E4.5a/E4.5b's stage-list and repo-added-stage rules, and E4.6/N1's global agent-config
override. It leaves E4.8 (same-tree gate reuse) and E5/E7 (prompt-library split and neutralisation)
as the next epics.

**Scope:** Adds the fixture config, three fixture prompts and one fixture agent config under
`fixtures/target-repo/aidw/`, plus `tests/test_override_integration.py`; ticks E4.7 in the roadmap.
It deliberately stops short of running the full `aidw implement` workflow against the fixture,
validating the fixture's read-paths, editing any toolkit `prompts/*.md` or `agent-configs/*.yaml`,
and adding new dependencies.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/implementation-results/00-E4.7/build-results.md` | Created | This recording document. |
| `fixtures/target-repo/aidw/config.yaml` | Created | Fixture target config: `schema_version: 1`, `paths.agent_configs_dir`, all six core `implement` ids in order (I3 `enabled: false`), I4 explicit `prompt`, repo-added `lint` with a toolkit-known agent. |
| `fixtures/target-repo/aidw/prompts/test.md` | Created | I2 filename-shadow marker with frontmatter, proving D14 level 2. |
| `fixtures/target-repo/aidw/prompts/architecture-explicit.md` | Created | I4 explicit-path marker, reachable only through the stage's `prompt:` declaration (D14 level 1). |
| `fixtures/target-repo/aidw/prompts/lint.md` | Created | Filename shadow for the repo-added `lint` stage (§3.5/D14 level 2). |
| `fixtures/target-repo/aidw/agent-configs/implementer.yaml` | Created | Valid agent config with stem `implementer`, `provider: openrouter`, and a model slug no toolkit agent uses; shadows the toolkit implementer by id (E4.6/N1). |
| `tests/test_override_integration.py` | Created | 23 tests covering the six behaviours at `plan_stages` and dry-run argv, plus one-input perturbation checks and the no-real-`pi`/`git`/`gh` guard. |
| `docs/task-prompts/00-E4.7-prompt.md` | Modified | Add the task prompt (committed by the prompt-authoring stage). |
| `docs/tasks/00 - Extraction.md` | Modified | Tick E4.7 in the roadmap (traceability update owned by the prior stage). |

---

## Verification Results

The build, suite, doctor, agents and prompts gates were run through `aidw gate run` with the same
scope —
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` —
and every row below reports this run's own outcome for tree `8c895a76cbdd`, stage
`record-implementation-results`, on 2026-11-04; `uv sync --frozen` and `git diff --check` were run
directly (neither is a recorded gate). No gate was re-run for a subset count.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 15 packages in 0.84ms`) |
| Build | `uv build --out-dir <tmp>` | ✅ Pass (gate `build`, tree `8c895a76cbdd`, 2026-11-04T22:04:26Z: `Successfully built aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl`) |
| Test | `uv run --frozen pytest` | ✅ Pass (gate `suite`, tree `8c895a76cbdd`, 2026-11-04T22:04:52Z: `1269 passed in 23.97s`) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (gate `doctor`, tree `8c895a76cbdd`, 2026-11-04T22:04:55Z: `19 checks: 0 failed, 2 warning(s)` — the dirty working tree and absent `.mcp.json`, both expected mid-run) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (gate `agents`, tree `8c895a76cbdd`, 2026-11-04T22:04:55Z: `11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (gate `prompts`, tree `8c895a76cbdd`, 2026-11-04T22:04:56Z: `prompts check: 0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (no output) |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1269 | ✅ Pass (`1269 passed in 23.97s`) |

The task-specific proofs live in the new test module and ran inside this single suite invocation (no
subset was re-run to obtain a count). `tests/test_override_integration.py` contributes 23 tests;
`tests/test_prompt_resolution.py::test_fixture_override_end_to_end_renders_the_override` — the
existing `code-review.md` shadow contract — also stayed green.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| The committed fixture config loads with zero ERROR issues and plans I1, I2, I4, I5, I6, `lint` in order (I3 absent) | ✅ Covered by the suite run above (`tests/test_override_integration.py::test_committed_config_loads_without_errors_and_plans_the_core_chain`) |
| D14 level 2 filename shadow: I2 resolves to `fixtures/target-repo/aidw/prompts/test.md`, not the toolkit prompt, and renders that body with frontmatter stripped | ✅ Covered by the suite run above (`test_filename_override_stage_resolves_the_fixture_shadow`, `test_dry_run_renders_the_filename_shadow_body`) |
| D14 level 1 explicit path: I4 resolves to `architecture-explicit.md` with `explicit_prompt` set, never falling through to a shadow | ✅ Covered by the suite run above (`test_explicit_path_stage_resolves_the_declared_file_not_any_shadow`, `test_dry_run_renders_the_explicit_path_body`, `test_missing_explicit_path_does_not_fall_through_to_a_shadow`) |
| D4 default fallback: I1/I5/I6 resolve to `<toolkit>/prompts/<name>.md` with `explicit_prompt is None`, and render the toolkit body | ✅ Covered by the suite run above (`test_default_fallback_stages_resolve_to_the_toolkit_prompts`, `test_dry_run_renders_the_default_fallback_body`) |
| D12/D13 repo-optional disable: I3 is omitted from the plan, every other core id stays present and in order | ✅ Covered by the suite run above (`test_committed_config_loads_without_errors_and_plans_the_core_chain`, `test_perturbing_i3_back_to_enabled_plans_it_in_registry_order`) |
| §3.5 repo-added stage: `lint` plans with `id == name == "lint"`, the declared `agent_id`, `variables == []`, `extra == ""`, and its shadow prompt | ✅ Covered by the suite run above (`test_repo_added_stage_plans_with_its_id_agent_and_shadow_prompt`, `test_dry_run_renders_the_repo_added_stage_body`, `test_dropping_the_repo_added_stages_shadow_fails_closed`, `test_perturbing_away_the_repo_added_entry_removes_it`) |
| E4.6/N1 global agent-config override: `implementer` is shadowed by id, other agents keep toolkit defaults, and dry-run argv shows the override model on implementer stages only | ✅ Covered by the suite run above (`test_global_agent_config_override_shadows_the_implementer_by_id`, `test_dry_run_argv_shows_the_override_on_implementer_stages_only`, `test_perturbing_away_the_agent_config_override_restores_the_toolkit_model`) |
| Regression sensitivity: removing/renaming/re-enabling each fixture input fails exactly the behaviour it owns | ✅ Covered by the suite run above (`test_the_perturbation_set_covers_every_behaviour` and the six `test_perturbing_*` checks) |
| No real Pi/git/gh: the dry-run path spawns none of them | ✅ Covered by the suite run above (`test_dry_run_invokes_no_real_pi_git_or_gh`) |
| Exact `AGENTS.md` gate set (sync/test/doctor/agents/prompts) | ✅ All five passed as recorded above |

---

## Deviations observed during recording

- **The generic record prompt names a pnpm gate set, but this repo's stack is Python/uv.** Per
  `AGENTS.md` and `prompts/pr.md` ("take them from the target repo, not from this prompt"), the
  install/build/test rows are `uv sync --frozen`, `uv build` and `uv run --frozen pytest`, and no
  lint gate was run because the repo configures no linter.
- **`uv build` writes to a fresh `$(mktemp -d)` directory** rather than the working tree, so the
  recorded build row leaves no artifacts to clean up.

---

## Non-Goals (NOT implemented)

- ❌ E4.8 (same-tree gate reuse) and E5.x/E7.x (roadmap format, prompt-library split) — separate epics/tasks (task prompt, explicit non-goals).
- ❌ No toolkit `prompts/*.md` or `agent-configs/*.yaml` was edited — the fixture shadows them; neutralisation is E7.x (task prompt, explicit non-goals).
- ❌ No full `aidw implement` workflow run against a bare+worktree fixture — E4.7 proves the six behaviours at `plan_stages` + dry-run argv level, with no real Pi and no git (task prompt, explicit non-goals; `EXTRACTION.md` §3.12).
- ❌ No `validate_paths` or workflow preflight — the fixture lacks Mythical Forge's default read-paths, and read-path validation is E3.7's concern.
- ❌ `--force-model` and the E4.4/E4.5a stage-list rules were not re-implemented here.
- ❌ No PR opened and nothing committed by the recording stage (`prompts/pr.md` owns delivery).
