# Build Results — 00-E3.7: Validate configured paths (fail closed)

**Branch:** `00-E3.7`
**Date:** 2026-11-03
**Spec:** `docs/migration/EXTRACTION.md` §3.4 (target-repo config: `paths:` schema, "Configured read-paths must exist", D17 defaults, "no silent fallback"), §3.12 (repo layout); `docs/target-repo-config.md` §"Configured paths must exist" (E3.6 contract); `design.md` §12 (configuration and `aidw doctor`'s read-only validation duty), §3 (repository layout)

## Summary

**Purpose:** Validate every configured `paths:` entry fail-closed — classify it as a read-path, write-target or glob, refuse a missing read-path in `aidw doctor` and in the stage preflight that first needs it, and create the architecture write-target only when its owning stage is enabled.

| Decision | Why it matters |
|----------|---------------|
| One classification in `aidw/target_config.py` (`READ_PATH_FIELDS` / `WRITE_TARGET_FIELDS` / `GLOB_PATH_FIELDS`) that is exhaustive over `PATH_FIELDS` | A later path cannot be silently left out of validation, and `roadmap_glob` can never be mistaken for a filename. |
| Four read-paths, including `implementation_results_dir` | The E3.7 roadmap entry adds it to §3.4's three; omitting it leaves the record stage's parent directory unvalidated. |
| `check_paths` is pure and existence-only | It reads `exists()`, writes and mutates nothing, and does not impose a file-vs-directory contract the spec does not state. |
| Read-paths resolve against the **target** root, never the toolkit/cwd root | Resolving against the wrong root would flag a healthy target repo's `docs/` as missing (AGENTS.md "Two roots"). |
| Doctor unions path issues with loader `ERROR`s and compatibility issues, remaining read-only | A missing default read-path is now an explicit `FAIL` naming field and path; the write-target creation belongs to the owning stage, not doctor. |
| `aidw prompt` validates only its two startup paths | It must refuse before any branch/worktree/run record, while leaving the record stage's paths to `aidw implement`. |
| `aidw implement` validates I5 paths post-locate against the worktree root, and creates I4's target immediately before I4 executes | The control tree and task worktree are different trees; the worktree is what I4/I5 write into. Dry runs write nothing and a skipped stage creates nothing. |
| `architecture_dir` is owned by the config stage id `architecture`, enabled by default when undeclared | The prompt fixes the ownership/default; E4.1/E4.5 own wiring `enabled` into the stage chain, so E3.7 reads the flag only for path validation. |

**Where it fits in the roadmap:** E3.7 in Phase 00's extraction epic. It consumes E3.1's schema, E3.2's resolver, E3.3's compatibility gate, E3.4's seeded defaults, E3.5's doctor check and E3.6's published contract. It closes the read-path enforcement those tasks documented. E4.1/E4.5 will make the stage chain honour `enabled`; E5.2 will make `load_tasks` consume the configured `roadmap_dir`; E7.2 owns the prompt-level record-template refusal.

**Scope:** Adds path classification/validation to `aidw/target_config.py`, wires it into `aidw/doctor.py` and the `aidw prompt`/`aidw implement` preflights, creates `architecture_dir` on demand before I4, updates the affected fixtures and adds the E3.7 contract tests, and marks E3.7 complete on the extraction roadmap. It deliberately stops short of the stage registry, enforcing `enabled` in the stage chain, driving `load_tasks` from configuration, editing prompts, and any write-target schema for future repo-added stages.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E3.7-prompt.md` | Created | Task prompt recording requirements, traps, non-goals and deliverables for E3.7. |
| `aidw/target_config.py` | Modified | Adds the exhaustive read-path/write-target/glob classification, `resolve_target_path`, `resolved_path`, pure `check_paths`, `stage_enabled`, and the architecture stage id. |
| `aidw/doctor.py` | Modified | Unions configured read-path issues into the `target config` check so a missing path is a `FAIL` naming the field and resolved path; doctor stays read-only. |
| `aidw/workflows/prompt.py` | Modified | Adds the startup preflight for `roadmap_dir` and `task_prompts_dir`, refusing exit 2 before any branch/worktree/run record. |
| `aidw/workflows/implement.py` | Modified | Adds the post-locate I5 read-path preflight against `target.root` (including loader/compatibility refusals) and on-demand `architecture_dir` creation immediately before an executing I4. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E3.7 complete on the extraction roadmap. |
| `tests/test_target_config.py` | Modified | Adds classification, per-read-path, glob/write-target, purity, stage-enabled and seeded property tests for path validation. |
| `tests/test_doctor.py` | Modified | Seeds the default read-paths into fixtures and adds config-less, missing-default and per-field missing-read-path doctor tests. |
| `tests/test_prompt_workflow.py` | Modified | Adds read-paths to fixture repos, fixes the blocked-stage assertion to inspect the task worktree, and adds startup-refusal/non-startup-path tests. |
| `tests/test_implement_workflow.py` | Modified | Adds record-stage refusal, malformed/incompatible config, dry-run, skipped-I4, enabled/disabled architecture and write-target failure tests. |
| `tests/test_cli.py` | Modified | Provides the default read-paths in the CLI fixture repo so `aidw prompt`'s startup check passes. |

---

## Verification Results

Every gate was run through `aidw gate run <key> $SCOPE -- <command>` with `SCOPE="--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts"` — the document this stage writes plus the write-targets of the other stages. Every outcome below is a real observation against tree `1f824587a132` from this run at stage `record-implementation-results`; none was copied from an earlier run or another document. `AIDW_STAGE` / `AIDW_RUN_ID` were removed from the child environment for pytest and doctor-style commands so the recorder's ambient identity did not leak into the suite, matching CI.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `aidw gate run install $SCOPE -- uv sync --frozen` | ✅ `Checked 15 packages in 0.40ms` — frozen lock consistent (gate `install`, tree `1f824587a132`, stage `record-implementation-results`, 2026-11-03T08:39:52Z) |
| Build | `aidw gate run build $SCOPE -- uv build --out-dir <tmp>` | ✅ Built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` (gate `build`, tree `1f824587a132`, stage `record-implementation-results`, 2026-11-03T08:39:55Z) |
| Test | `aidw gate run suite $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ✅ `1043 passed in 31.52s` (gate `suite`, tree `1f824587a132`, stage `record-implementation-results`, 2026-11-03T08:40:52Z) |
| Doctor | `aidw gate run doctor $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw doctor` | ✅ exit 0 — 19 checks: 0 failed, 2 warnings (dirty working tree; missing `.mcp.json`); `target config` reports `none (defaults)` (gate `doctor`, tree `1f824587a132`, stage `record-implementation-results`, 2026-11-03T08:40:56Z) |
| Agents validate | `aidw gate run agents-validate $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw agents validate --strict` | ✅ exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `1f824587a132`, stage `record-implementation-results`, 2026-11-03T08:40:58Z) |
| Prompts check | `aidw gate run prompts-check $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw prompts check` | ✅ exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `1f824587a132`, stage `record-implementation-results`, 2026-11-03T08:40:59Z) |
| Whitespace | `git diff --check` | ✅ exit 0, no whitespace errors |
| Lint | — | **unverified** — the repository configures no linter or formatter (`AGENTS.md` "Gates": pytest is the only verification; none was added in this task) |

### `uv run --frozen pytest` (full suite)

Counts are from the single full-suite gate invocation above. The per-file counts are collection-only (`pytest --collect-only -q`, which executes no test) and show the four files covered by the single task-specific focused run whose total is also from one invocation; no test was re-run to obtain a row. The suite reported no skips, xfails or failures.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1043 | ✅ Pass (`1043 passed in 31.52s`) |
| `tests/test_target_config.py` | 127 | ✅ Pass (all part of the focused `focused-tests` run) |
| `tests/test_doctor.py` | 59 | ✅ Pass (all part of the focused `focused-tests` run) |
| `tests/test_prompt_workflow.py` | 155 | ✅ Pass (all part of the focused `focused-tests` run) |
| `tests/test_implement_workflow.py` | 56 | ✅ Pass (all part of the focused `focused-tests` run) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Focused task suite | ✅ `aidw gate run focused-tests $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest tests/test_target_config.py tests/test_doctor.py tests/test_prompt_workflow.py tests/test_implement_workflow.py` — `397 passed in 19.69s` (gate `focused-tests`, tree `1f824587a132`, stage `record-implementation-results`, 2026-11-03T08:40:18Z) |
| Every `paths:` entry is classified exhaustively; `roadmap_glob` is never existence-checked | ✅ `test_path_classification_is_exhaustive_over_path_fields` and `test_roadmap_glob_is_never_existence_checked` passed |
| Each missing read-path yields one `ERROR` naming the dotted field and resolved absolute path; all present yields none | ✅ `test_each_missing_read_path_yields_one_issue_naming_field_and_resolved_path` and `test_all_read_paths_present_yields_no_issues` passed |
| Defaults are validated in an empty target root; `architecture_dir` absence yields no issue | ✅ `test_defaults_in_an_empty_target_root_yields_one_issue_each` and `test_write_target_absence_produces_no_issue` passed |
| A disabled `architecture` stage passes an absent write-target; enabled/undeclared is enabled | ✅ `test_architecture_stage_is_enabled_when_absent_and_disabled_only_by_false` passed |
| `check_paths` writes nothing and does not mutate its frozen input | ✅ `test_check_paths_writes_nothing_and_mutates_nothing` passed |
| Seeded property run over generated path configs | ✅ `test_path_validation_property` passed (seed 713, 40 runs) |
| Doctor fails a valid config naming a missing read-path, and passes a config-less repo with the four defaults | ✅ `test_valid_config_naming_a_nonexistent_read_path_fails_naming_field_and_path` and `test_configless_repo_with_the_default_read_paths_is_ok` passed |
| `aidw prompt` refuses a missing startup read-path with exit 2 naming field and path, and ignores non-startup paths | ✅ `test_e37_missing_startup_read_path_refuses_naming_field_and_path` and `test_e37_a_missing_non_startup_read_path_does_not_block_prompt` passed |
| `aidw implement` record preflight refuses a missing worktree read-path and malformed/incompatible configs | ✅ `test_e37_missing_record_read_path_refuses_naming_field_and_path`, `test_e37_record_preflight_refuses_a_malformed_worktree_config` and `test_e37_record_preflight_refuses_an_incompatible_worktree_config` passed |
| I4's write-target is created only on a real enabled run, never on a dry run or skipped stage; failure names `architecture` | ✅ `test_e37_dry_run_with_a_located_worktree_creates_no_architecture_dir`, `test_e37_enabled_architecture_stage_creates_the_write_target`, `test_e37_skipped_architecture_stage_creates_nothing`, `test_e37_architecture_write_target_that_is_a_file_fails_naming_the_stage` and `test_e37_disabled_architecture_stage_passes_an_absent_write_target` passed |
| `aidw doctor` remains clean on this repo | ✅ In the `doctor` gate above: `target config none (defaults)`, 0 failed |

---

## Deviations observed during recording

- **The stage prompt's generic pnpm commands do not apply to this repository.** This is the `aidt` toolkit (Python/uv), so the `AGENTS.md` / `prompts/pr.md` gate set was run instead. `pnpm install`, `pnpm -r lint`, `pnpm -r build` and `pnpm -r test` were not run, and the `lint` row is recorded as unverified rather than passing.
- **The task prompt's focused pytest command was run as its own named gate.** The four named modules were invoked once as `focused-tests`, and the full suite was invoked once as `suite`; no suite or module was re-run to obtain a count. Per-file rows use collection-only counts from a separate non-executing collection pass.
- **`uv build` does not write into the tree.** It built into a `mktemp -d` directory, so the gated tree stayed identical to the delivered change set.
- **The implementation and tests are uncommitted on this branch.** `git diff main` shows the code, test and roadmap edits plus the task-prompt commit; the change set verified here is the working tree relative to `main`, not only the commits on the branch.

---

## Non-Goals (NOT implemented)

- ❌ E4.1/E4.5 stage registry and core-vs-optional `enabled: false` enforcement — E3.7 reads the `architecture` stage's `enabled` flag for path validation only; the stage chain does not honour it yet.
- ❌ E5.2 driving `roadmap.py` from the configured `roadmap_dir`/`roadmap_glob` — E3.7 validates the configured path; consuming it in `load_tasks` is E5.2's.
- ❌ E7.2 neutralising the record prompt — the prompt-level "missing template → stop and report, never invent a structure" is already in `prompts/record-implementation-results.md`; no prompt was edited here.
- ❌ "Any repo-added stage's directory" as a write-target — no schema field declares one yet; that is E4.1's stage registry.
- ❌ E3.6's contract doc — already written and consistent; it was kept true, not rewritten.
- ❌ No commit, push, or PR was made by this stage.
