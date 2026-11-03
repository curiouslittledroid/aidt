# Build Results — 00-E3.7: Validate configured paths (fail closed)

**Branch:** `00-E3.7`
**Date:** 2026-11-03
**Spec:** `docs/migration/EXTRACTION.md` §3.4 (target-repo config: the `paths:` schema and "Configured read-paths must exist", D17/R7), §6 E7.2 (neutralise bucket (ii): the recorder stops and reports a missing template rather than inventing one), §3.11 (workflow preflight refusal), §3.12 (no new top-level folders); `design.md` §3 (repository layout); `docs/task-prompts/00-E3.7-prompt.md`

## Summary

**Purpose:** Classify every configured `paths:` entry as a read-path or a write-target, fail closed when a read-path named by the config or by a D17 default does not exist, and create an enabled stage's write-target on demand — so a repo without Mythical Forge's layout is told what to create instead of an agent improvising around a missing directory.

| Decision | Why it matters |
|----------|---------------|
| The roadmap's four read-paths win over §3.4's three: `build_results_template`, `roadmap_dir`, `task_prompts_dir`, `implementation_results_dir` | `implementation_results_dir` is a read-path in E3.7's roadmap entry; the separate §3.4 "four configured write-targets" is the gate-scope declaration (R18), a different question, not this task's existence taxonomy. |
| Default-sourced leaves are validated too, not only config-named ones | D17's defaults *are* a naming; skipping them would let a config-less repo miss `docs/tasks` silently and defeat D17/R7. A config-less load is valid, so validation keys off the resolved leaf, never `source_path is None`. |
| `roadmap_glob` belongs in neither list | It is a glob pattern, so an existence check would stat a pattern and fail spuriously. It is never classified here. |
| Write-target enablement comes from `declared.workflows`, not the resolved stage list | The resolved stage list omits undeclared stages, so it cannot carry the "enabled unless `enabled: false` on the `architecture` stage" default that preserves E4.1's six-stage chain. |
| `validate_paths` is pure and `ensure_write_targets` catches only `OSError` | Doctor must stay read-only (§3.1) and never create a directory; a non-`OSError` is a bug that must surface rather than be folded into a plausible-looking issue. |
| Both passes resolve the config exactly once and reuse it | Doctor's FAIL/OK decision and its schema-version line cannot disagree about what the config resolved to; the prompt preflight reads `max_revisions` from the same resolution it validated. Adding a second doctor check name would also break `tests/test_doctor.py::_named`'s uniqueness assertion. |
| Read-path issues join the loader/compatibility issue list instead of a new check | One `target config` verdict, one formatter (`format_issues`), and every message names the field, the resolved path and the value's provenance. |

**Where it fits in the roadmap:** E3.7 of the extraction epic. It consumes E3.1's schema, E3.2's resolver, E3.4's seeded defaults, E3.5's `target config` doctor check and E3.6's documented contract, and turns that contract into enforcement. E4.3 owns `ensure_write_targets`'s call site in the implement chain; E5.2 owns consuming `paths.roadmap_dir`/`roadmap_glob` for parsing; E4.1/E4.5 own the stage registry and core-vs-optional enforcement this task only reads `enabled` from.

**Scope:** Touches `aidw/target_config.py` (classification plus the two passes), `aidw/doctor.py` (union read-path issues into `target config`), `aidw/workflows/prompt.py` (refuse before any run state), the three matching test modules and `tests/test_cli.py`'s fixture, updates `docs/target-repo-config.md` to describe the implemented behaviour, and marks E3.7 complete on the extraction roadmap. It deliberately stops short of wiring `ensure_write_targets` into implement/review/fix/approve, consuming the paths for parsing, editing prompts, enforcing the stage registry, and adding write-targets for repo-added stages.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E3.7-prompt.md` | Created | Task prompt recording the requirements, traps, non-goals and deliverables for E3.7. |
| `aidw/target_config.py` | Modified | Adds `READ_PATHS`, `WRITE_TARGETS`, the `_resolved_path`/`_target_path` helpers, `validate_paths` (pure read-path check) and `ensure_write_targets` (`mkdir` only, enabled stages only, `OSError` reported naming the stage). |
| `aidw/doctor.py` | Modified | Resolves once after the loader and compatibility refusals, unions `validate_paths` into the same issue list before the FAIL/OK decision, and reuses the resolution for the schema-version line; still read-only. |
| `aidw/workflows/prompt.py` | Modified | Adds the read-path refusal at the existing config preflight (exit 2, stderr via `format_issues`) before `load_tasks`/branch setup, and reads `max_revisions` from the same resolution. |
| `docs/target-repo-config.md` | Modified | Replaces the "lands in E3.7" status with the implemented classification, the two passes, doctor's read-only check and the prompt preflight, noting the implement call site is E4.3's. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E3.7 complete on the extraction roadmap. |
| `tests/test_target_config.py` | Modified | 19 new vectors: classification, declared and default-sourced missing read-paths, `roadmap_glob` never checked, absent write-target not a read-path issue, absolute overrides, purity, enabled/disabled write-target creation, `OSError` vs non-`OSError`, idempotence, and a read-path property test. |
| `tests/test_doctor.py` | Modified | Shared fixtures now carry the four read-paths; new vectors prove a configured and a default-sourced missing read-path fail `target config` with exit 1 naming field and path, and a disabled architecture write-target stays green. |
| `tests/test_prompt_workflow.py` | Modified | Fixture gains the read-paths; new vectors prove a configured and a default-sourced missing read-path refuse with exit 2 before `load_tasks`/branch setup with field and path on stderr, and a complete repo still proceeds. |
| `tests/test_cli.py` | Modified | `_init_repo_with_task` now creates the four read-paths so the implement dry-run scenario passes the prompt preflight, and its explicit `mkdir` no longer assumes the directory is absent. |

---

## Verification Results

Every gate was run through `aidw gate run <key> $SCOPE -- <command>` with `SCOPE="--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts"` — the document this stage writes plus the write-targets of the other stages. Every outcome below is a real observation against tree `532a14c8a21c` from this run; none was reused from an earlier run or copied from another document. `AIDW_STAGE` / `AIDW_RUN_ID` were removed from the child environment for the pytest and doctor-style commands so the recorder's ambient identity did not leak into the suite, matching CI.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `aidw gate run install $SCOPE -- uv sync --frozen` | ✅ `Checked 15 packages in 0.35ms` — frozen lock consistent (gate `install`, tree `532a14c8a21c`, stage `record-implementation-results`, 2026-11-03T11:08:25Z) |
| Build | `aidw gate run build $SCOPE -- uv build --out-dir <tmp>` | ✅ Built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` into a `mktemp -d` (gate `build`, tree `532a14c8a21c`, stage `record-implementation-results`, 2026-11-03T11:08:28Z) |
| Test | `aidw gate run suite $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ✅ `1031 passed in 27.54s` (gate `suite`, tree `532a14c8a21c`, stage `record-implementation-results`, 2026-11-03T11:09:00Z) |
| Doctor | `aidw gate run doctor $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw doctor` | ✅ exit 0 — 19 checks: 0 failed, 3 warnings (`gh` unauthenticated, dirty working tree, missing `.mcp.json`); `target config` reports `none (defaults)` (gate `doctor`, tree `532a14c8a21c`, stage `record-implementation-results`, 2026-11-03T11:09:04Z) |
| Agents validate | `aidw gate run agents-validate $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw agents validate --strict` | ✅ exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `532a14c8a21c`, stage `record-implementation-results`, 2026-11-03T11:09:05Z) |
| Prompts check | `aidw gate run prompts-check $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw prompts check` | ✅ exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `532a14c8a21c`, stage `record-implementation-results`, 2026-11-03T11:09:05Z) |
| Whitespace | `git diff --check` | ✅ exit 0, no whitespace errors |
| Lint | — | **unverified** — the repository configures no linter or formatter (`AGENTS.md` "Gates": pytest is the only verification; none was added in this task) |

### `uv run --frozen pytest` (full suite)

Counts are from the single full-suite gate invocation above. The per-file counts are collection-only (`pytest --collect-only -q -n0`, which executes no test) and show the files the full suite already covered; no test was re-run for a row. The suite reported no skips, xfails or failures.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1031 | ✅ Pass (`1031 passed in 27.54s`) |
| `tests/test_target_config.py` | 133 | ✅ Pass (all part of the full-suite run) |
| `tests/test_doctor.py` | 56 | ✅ Pass (all part of the full-suite run) |
| `tests/test_prompt_workflow.py` | 154 | ✅ Pass (all part of the full-suite run) |
| `tests/test_cli.py` | 46 | ✅ Pass (all part of the full-suite run) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Classification is exactly the roadmap's four read-paths and the one `architecture_dir` write-target; `roadmap_glob` is in neither | ✅ `test_path_classification_is_the_roadmap_read_paths_and_the_architecture_write_target` passed |
| A configured nonexistent read-path yields one `ERROR` naming `paths.<field>` and the resolved path | ✅ `test_declared_read_path_that_does_not_exist_is_one_error_naming_field_and_path` passed |
| Default-sourced read-paths are validated, not skipped (D17/R7) | ✅ `test_default_sourced_read_paths_are_validated_not_skipped` passed |
| All four present yields no issues; an absent write-target is not a read-path issue; unset leaves are skipped | ✅ `test_every_read_path_resolves_with_no_issues_when_present`, `test_absent_write_target_is_not_a_read_path_issue`, `test_validate_paths_skips_unset_leaves_defensively` passed |
| `roadmap_glob` is never existence-checked; an absolute override wins over the target root | ✅ `test_roadmap_glob_is_a_pattern_and_is_never_existence_checked`, `test_absolute_read_path_override_wins_over_the_target_root` passed |
| `validate_paths` writes nothing | ✅ `test_validate_paths_is_pure_and_writes_nothing` passed |
| An enabled stage's absent write-target is created on demand (default and configured path) | ✅ `test_enabled_write_target_is_created_on_demand`, `test_write_target_uses_the_resolved_default_when_the_config_is_silent`, `test_enabled_write_target_uses_the_configured_resolved_path`, `test_write_target_is_created_when_its_stage_is_enabled_explicitly` passed |
| A disabled stage's write-target is skipped entirely — no directory, no issue | ✅ `test_disabled_stage_skips_its_write_target_entirely` passed |
| Impossible creation fails naming the stage and path; only `OSError` is caught | ✅ `test_impossible_creation_fails_naming_the_stage_and_the_path`, `test_write_target_path_that_is_a_file_is_an_error_naming_the_stage`, `test_write_target_does_not_swallow_non_oserror` passed |
| `ensure_write_targets` is idempotent and creates only the target | ✅ `test_ensure_write_targets_is_idempotent_and_only_creates_the_target` passed |
| Read-path validation property holds across generated inputs | ✅ `test_read_path_validation_property` passed |
| Doctor: configured missing read-path fails `target config` with field and path, exit 1 | ✅ `test_nonexistent_read_path_fails_naming_the_field_and_the_path` passed |
| Doctor: a config-less repo missing a default read-path fails closed, exit 1 | ✅ `test_default_read_path_missing_fails_closed_in_a_configless_repo` passed |
| Doctor: a disabled architecture write-target keeps doctor green, exit 0 | ✅ `test_disabled_architecture_write_target_keeps_doctor_green` passed |
| Prompt preflight: configured missing read-path refuses (exit 2) before `load_tasks`/branch setup, for a plan and a real run | ✅ `test_e37_missing_configured_read_path_refuses_before_any_state` passed for both `dry_run` parametrizations |
| Prompt preflight: default missing read-path refuses in a configless repo, ordered before the dirty-tree refusal (exit 2 vs exit 4) | ✅ `test_e37_missing_default_read_path_refuses_in_a_configless_repo` passed |
| Prompt preflight: a complete repo is unchanged and proceeds | ✅ `test_e37_complete_repo_passes_the_path_preflight` passed |
| This toolkit repo still passes `aidw doctor` (all four read-paths present) | ✅ Observed in the `doctor` gate above: `target config none (defaults)`, exit 0 |

---

## Deviations observed during recording

- **The stage prompt's generic pnpm commands do not apply to this repository.** This is the `aidt` toolkit (Python/uv), so the `AGENTS.md` / `prompts/pr.md` gate set was run instead. `pnpm install`, `pnpm -r lint`, `pnpm -r build` and `pnpm -r test` were not run, and the `lint` row is recorded as unverified rather than passing.
- **The targeted pytest commands in the task prompt's "Done when" were not re-run.** The four touched test modules are fully included in the single full-suite gate above, which passed; their per-file counts are collection-only to avoid buying the same tests twice, matching the E3.3–E3.6 records.
- **`uv build` does not write into the tree.** It built into a `mktemp -d` directory, so the gated tree stayed identical to the delivered change set.
- **The implementation is uncommitted on this branch.** `git diff main` shows the source, test, doc and roadmap edits plus the committed task prompt; the change set verified here is the working tree relative to `main`, not only the one commit on the branch.

---

## Non-Goals (NOT implemented)

- ❌ `ensure_write_targets`'s call site in `aidw/workflows/implement.py` — implement's target-config loading is E4.3's; the function is delivered and unit-tested but no config loading was added to implement/review/fix/approve.
- ❌ E5.2 driving `roadmap.py`/`prompt.py` from `paths.roadmap_dir`/`roadmap_glob` — this task validates paths, it does not consume them for parsing.
- ❌ E7.2's prompt edits — the recorder's "stop and report" wording already lives in `prompts/record-implementation-results.md`; this task changes no prompt file.
- ❌ E4.1/E4.5's stage registry and core-vs-optional enforcement — this task only reads `enabled` on the architecture stage.
- ❌ Write-targets for repo-added stages other than `architecture_dir` — forward-looking to E4.5/E4.6.
- ❌ No commit, push, or PR was made by this stage (`prompts/pr.md` owns delivery).
