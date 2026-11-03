# Build Results — 00-E3.5: `aidw/config.yaml` validation in doctor

**Branch:** `00-E3.5`
**Date:** 2026-11-03
**Spec:** `docs/migration/EXTRACTION.md` §3.4 (target-repo config: missing config is valid, fail-closed validation names field paths), §3.11 / D10 (version and compatibility: `aidw doctor` validates the target config), §3.3 (CLI surface: extend doctor with `aidw/config.yaml` validity), and §3.12 (no new top-level folders); `design.md` §14 (doctor exit code non-zero iff at least one check FAILs) and §3 (repository layout)

## Summary

**Purpose:** Add a `target config` doctor check that reports the `<target>/aidw/config.yaml` path, its resolved `schema_version`, and any structural or compatibility error, while treating a missing config as the valid defaults case.

| Decision | Why it matters |
|----------|---------------|
| One check named `target config` reports path, schema version and errors together | The roadmap names a singular doctor check; splitting it would make `_named` uniqueness and operator output harder to follow without adding information. |
| Failure comes from the loader's `ERROR` issues unioned with `check_compatibility`, never from the merged output | `resolve_config`'s contract is that callers refuse a broken config before resolving; deriving FAIL from the merge would either mask structural errors or resolve an invalid config. |
| A missing `aidw/config.yaml` is `OK` with `none (defaults)` | §3.4 makes the folder optional; failing on `source_path is None` would turn every defaults-only repo — including this toolkit repo — red. |
| `check_compatibility` is included in the FAIL decision, using `aidw.__version__` | §3.11/D10 assigns compatibility to doctor and forbids hardcoding a toolkit version, so a stale literal cannot produce a false compatibility verdict. |
| The resolved schema version comes from `resolve_config(...)["schema_version"]` | The roadmap asks for the *resolved* value; it equals `declared.schema_version` today only because `schema_version` has no toolkit default. |
| The check runs only after the bare/non-repo early returns | The config lives in the working tree; a bare target has no `aidw/` directory to read, so it must short-circuit first. |
| Read-only: one file read, no writes and no `Path.exists()` probing of `paths:` fields | §3.1 forbids generating files in a target repo; path-existence and write-target classification are E3.7's scope. |

**Where it fits in the roadmap:** E3.5 in the extraction epic. It consumes E3.1's loader, E3.2's resolver, E3.3's compatibility refusals and E3.4's seeded defaults, and it turns them into a user-visible doctor verdict. E3.6 can now document the config fields doctor validates, E3.7 owns path-existence and write-target checks, and E4.3/E5.2 can rely on doctor having already reported an invalid target config.

**Scope:** Touches `aidw/doctor.py` (the new check, its wiring and imports) and `tests/test_doctor.py` (valid, missing, malformed and incompatible config vectors plus read-only/metamorphic checks), and marks the task complete in the extraction roadmap. It deliberately stops short of operator documentation, path-existence validation, `aidw config show` changes, workflow wiring, and making the roadmap/prompt consumers read the resolved paths.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E3.5-prompt.md` | Created | Task prompt recording the requirements, traps, non-goals and deliverables for E3.5. |
| `aidw/doctor.py` | Modified | Adds `_check_target_config` and `NO_TARGET_CONFIG`, imports the target-config loader/resolver/compatibility formatter and `__version__`, and appends the check to `collect_checks` after the bare/non-repo early returns; updates the module docstring for §3.4/§3.11. |
| `tests/test_doctor.py` | Modified | Adds the `target config` contract tests: valid config path and schema version, missing config defaults, three malformed vectors, two incompatible vectors, unioned malformed+incompatible errors, bare-target skip, CLI exit code, read-only, no-`aidw/`-created and cwd invariance. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E3.5 complete on the extraction roadmap. |

---

## Verification Results

All gates were run through `aidw gate run <key> $SCOPE -- <command>` with `SCOPE="--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts"` — the document this stage writes plus the write-targets of the other stages. Every outcome below is a real observation against tree `2e7755483b11`; none was reused from an earlier run or copied from another document. `AIDW_STAGE` / `AIDW_RUN_ID` were removed from the child environment for the pytest and doctor-style commands so the recorder's ambient identity did not leak into the suite, matching CI.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `aidw gate run install $SCOPE -- uv sync --frozen` | ✅ `Checked 15 packages in 2ms` — frozen lock consistent (gate `install`, tree `2e7755483b11`, stage `record-implementation-results`, 2026-11-03T06:39:09Z) |
| Build | `aidw gate run build $SCOPE -- uv build --out-dir <tmp>` | ✅ Built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` (gate `build`, tree `2e7755483b11`, stage `record-implementation-results`, 2026-11-03T06:39:12Z) |
| Test | `aidw gate run suite $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ✅ `984 passed in 27.28s` (gate `suite`, tree `2e7755483b11`, stage `record-implementation-results`, 2026-11-03T06:39:43Z) |
| Doctor | `aidw gate run doctor $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw doctor` | ✅ exit 0 — 19 checks: 0 failed, 2 warnings (dirty working tree; missing `.mcp.json`); `target config` reports `none (defaults) — schema version none (defaults)` (gate `doctor`, tree `2e7755483b11`, stage `record-implementation-results`, 2026-11-03T06:39:46Z) |
| Agents validate | `aidw gate run agents-validate $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw agents validate --strict` | ✅ exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `2e7755483b11`, stage `record-implementation-results`, 2026-11-03T06:39:49Z) |
| Prompts check | `aidw gate run prompts-check $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw prompts check` | ✅ exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `2e7755483b11`, stage `record-implementation-results`, 2026-11-03T06:39:49Z) |
| Whitespace | `git diff --check` | ✅ exit 0, no whitespace errors |
| Lint | — | **unverified** — the repository configures no linter or formatter (`AGENTS.md` "Gates": pytest is the only verification; none was added in this task) |

### `uv run --frozen pytest` (full suite)

Counts are from the single full-suite gate invocation above. The `tests/test_doctor.py` count is collection-only (`pytest --collect-only -q`, which executes no test) and shows the file the full suite already covered; no test was re-run for a row. The suite reported no skips or xfails.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 984 | ✅ Pass (`984 passed in 27.28s`) |
| `tests/test_doctor.py` | 51 | ✅ Pass (all part of the full-suite run) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Valid config (`schema_version: 1` plus `repo.base_branch: trunk`) is `OK`, names the absolute path and `schema version 1 (config)`, and exits 0 | ✅ `test_valid_target_config_reports_the_path_and_resolved_schema_version` passed |
| Missing `aidw/config.yaml` is `OK` with `none (defaults)`, an unset resolved schema version, no issues, and exits 0 | ✅ `test_missing_target_config_reports_defaults` passed |
| Unknown key (`paths.foo`), wrong type (`schema_version: "1"`) and missing `schema_version` each `FAIL` and name the field path, with `run_doctor` returning 1 | ✅ `test_malformed_target_config_fails_naming_the_field_path` passed for all three parameter vectors |
| CLI `aidw --repo <target> doctor` on a malformed config exits 1, prints the resolved path and `` `paths.foo` ``, with no traceback | ✅ `test_cli_doctor_reports_malformed_target_config_and_exits_non_zero` passed |
| Newer `schema_version: 2` and unsatisfied `requires_toolkit: ">=99.0.0"` each `FAIL`, name the field, and exit 1 | ✅ `test_incompatible_target_config_fails_naming_the_field` passed for both parameter vectors |
| A config that is both malformed and incompatible reports both errors | ✅ `test_malformed_and_incompatible_errors_are_both_reported` passed |
| A bare target short-circuits before the config check | ✅ `test_bare_target_does_not_run_the_target_config_check` passed |
| The check reads only: config text and `aidw/` listing unchanged, no temp file written | ✅ `test_target_config_check_is_read_only_and_leaves_the_config_untouched` passed |
| A config-less repo never gains an `aidw/` directory or `config.yaml` | ✅ `test_configless_repo_never_gains_an_aidw_directory` passed |
| The verdict follows the resolved target, not the current working directory | ✅ `test_target_config_verdict_is_invariant_to_the_working_directory` passed |
| This toolkit repo (no `<target>/aidw/config.yaml`) keeps the doctor gate green with `none (defaults)` | ✅ Observed in the `doctor` gate above: `target config  none (defaults) — schema version none (defaults)`, exit 0 |

---

## Deviations observed during recording

- **The task prompt's generic pnpm commands do not apply to this repository.** This is the `aidt` toolkit (Python/uv), so the `AGENTS.md` / `prompts/pr.md` gate set was run instead. `pnpm install`, `pnpm -r lint`, `pnpm -r build`, and `pnpm -r test` were not run.
- **The targeted module gate was not re-run.** The task prompt's "Done when" names `pytest tests/test_doctor.py`; it is fully included in the single full-suite gate above, which passed. Its per-file count is collection-only to avoid buying the same tests twice, matching the E3.3/E3.4 record.
- **`uv build` does not write into the tree.** It built into a `mktemp -d` directory, so the gated tree stayed identical to the delivered change set.

---

## Non-Goals (NOT implemented)

- ❌ E3.6 `docs/target-repo-config.md` (documenting every field, default and effect) — separate task.
- ❌ E3.7 read-path existence validation / write-target classification — this check validates the config file, not the paths it names; no `Path.exists()` on any `paths:` field and no `docs/architecture` creation.
- ❌ `aidw config show` refactoring or duplication of its resolution/provenance logic — E3.2 already owns it; doctor shares only the path/load shape.
- ❌ E4.3 wiring the config into the other workflows; E4.2's third §3.11 refusal ("a required prompt cannot be resolved") — only `aidw/doctor.py` changed.
- ❌ E5.2 making `roadmap.py` / `prompt.py` consume `paths.*` — separate task.
- ❌ No commit, push, or PR was made by this stage.
