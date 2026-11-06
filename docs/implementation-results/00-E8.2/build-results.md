# Build Results — E8.2: state.json records identity

**Branch:** `00-E8.2`
**Date:** 2026-11-06
**Spec:** `docs/migration/EXTRACTION.md` §2 (D9 toolkit version recorded in every run's `state.json`; D10 target config declares `schema_version` and optional minimum toolkit version), §3.4 (target-repo config; `schema_version: 1` required when the `aidw/` folder exists, no `aidw/` folder is valid), §3.11 (version and compatibility); `design.md` §9.1/§9.2 (run layout and `state.json` schema, including the additive-fields precedent)

## Summary

**Purpose:** Record which toolkit version and which resolved target config produced every run, so an old `state.json` can explain the run after the fact (D9, EXTRACTION.md §3.11).

| Decision | Why it matters |
|----------|---------------|
| Add three additive `RunState` fields at the same `SCHEMA_VERSION`, each defaulting to `None` | A `state.json` written before E8.2 still loads unchanged; the throughput-fields precedent in design §9.2 is followed rather than bumping the state schema. |
| Name the config version `config_schema_version` | The bare `schema_version` key is already the **state** schema and `load()` refuses a mismatch, so reusing it for the config's version would break loading. |
| Hash the **resolved** config (`sha256:` over `json.dumps(resolved.to_dict(), sort_keys=True)`) | It is the same object `aidw config show --json` prints, so the fingerprint is reproducible, and each leaf's `source` is included — a declared `max_revisions: 3` fingerprints differently from the default `3`. |
| Compute both config values in one pure helper, `aidw.target_config.config_identity(resolved)` | The five workflows cannot drift into recording different values for one config; no I/O and no input mutation. |
| `aidw exec` records `toolkit_version` only, leaving both config fields `None` | `exec` resolves no target config today; wiring config validation into it would change its failure surface, which E8.2 does not own. |
| Leave `config_hash` unrelated to E4.8's `GateOutcome.tree` | That is a content-tree identity for gate reuse; this hash identifies the resolved config, never git state. |

**Where it fits in the roadmap:** Epic E8 (packaging, distribution, versions) under D9/D10. It builds on E8.1's installable wheel and on the run-layout/state schema in design §9.1/§9.2. E8.3 (`aidw --version`, doctor version/compatibility reporting), E8.4 (README install paths) and E8.5 (release process and first tag) remain downstream, as does E9.1's rewrite of the §9.2 schema example.

**Scope:** Three additive fields on `RunState` and the `create_run` signature; one pure config-identity helper in `aidw/target_config.py`; threading through the five workflows (`prompt`, `implement`, `review`, `fix`, `approve`) and the version-only `exec` path; one §17 decision-log row in `design.md`; the E8.2 roadmap checkbox; and tests in `tests/test_state.py`, `tests/test_target_config.py`, `tests/test_prompt_workflow.py` and `tests/test_cli.py`. It deliberately stops short of version-reporting commands, install/release documentation, any tag, the §9.2 schema-example rewrite, and any change to E4.8's gate-citation tree identity.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E8.2-prompt.md` | Created | Task prompt for E8.2 (committed on the branch). |
| `aidw/state.py` | Modified | Adds `toolkit_version`, `config_schema_version` and `config_hash` to `RunState` after `schema_version`, and keyword-only, defaulted `create_run` parameters; no `SCHEMA_VERSION` bump and no `load` special-casing. |
| `aidw/target_config.py` | Modified | Adds `CONFIG_HASH_PREFIX` and the pure `config_identity(resolved) -> (config_schema_version, config_hash)` helper next to `resolve_config`. |
| `aidw/workflows/prompt.py` | Modified | Records the toolkit version and config identity at its `create_run` site. |
| `aidw/workflows/implement.py` | Modified | Records the toolkit version and config identity on the fresh-run path (resume keeps its original record). |
| `aidw/workflows/review.py` | Modified | Records the toolkit version and config identity at its `create_run` site. |
| `aidw/workflows/fix.py` | Modified | Records the toolkit version and config identity at its `create_run` site. |
| `aidw/workflows/approve.py` | Modified | Records the toolkit version and config identity at its `create_run` site. |
| `aidw/cli.py` | Modified | `exec` records `toolkit_version=__version__` only and leaves the two config fields `None`, with the rationale recorded in a comment. |
| `design.md` | Modified | Adds §17 decision-log row `P1` for the key names, canonicalisation, additive schema choice, `exec` exception and provenance hashing. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E8.2 complete. |
| `tests/test_state.py` | Modified | Adds persistence, default-`None`, backward-load, field-order and round-trip property coverage for the identity fields. |
| `tests/test_target_config.py` | Modified | Adds hand-computed hash, determinism, changed-leaf, declared-default-vs-default, purity, resolved-not-declared, config-less `None` and property coverage for `config_identity`. |
| `tests/test_prompt_workflow.py` | Modified | Adds the dry-run integration assertion that `state.json` identity matches `aidw.__version__` and the resolved fixture config. |
| `tests/test_cli.py` | Modified | Asserts the `exec` run records `toolkit_version` and leaves the config fields `None`. |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 1ms`, exit 0; no dependency or lockfile change) |
| Build | `uv build --no-build-isolation --out-dir $(mktemp -d)` | ✅ Pass (`Successfully built …/aidt-0.1.0.tar.gz` and `…/aidt-0.1.0-py3-none-any.whl`); gate `build`, tree `7c3d21d591e2`, stage `record-implementation-results`, 2026-11-06T02:49:31Z |
| Test | `uv run --frozen pytest` | ✅ Pass (`1838 passed in 27.92s`); gate `suite`, tree `7c3d21d591e2`, stage `record-implementation-results`, 2026-11-06T02:50:01Z |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (exit 0, `19 checks: 0 failed, 2 warning(s)` — warnings are the expected dirty working tree and missing `.mcp.json`); gate `doctor`, tree `7c3d21d591e2`, 2026-11-06T02:50:03Z |
| Agent configs | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`); gate `agents-validate`, tree `7c3d21d591e2`, 2026-11-06T02:50:03Z |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (`toolkit defaults: 0 error(s), 0 warning(s)`; `resolved repo prompts: 0 error(s), 0 warning(s)`); gate `prompts-check`, tree `7c3d21d591e2`, 2026-11-06T02:50:04Z |
| Whitespace | `git diff --check` | ✅ Pass (no output, exit 0) |
| Lint | — (none configured) | **unverified** — the repo configures no linter, formatter or type-checker (`AGENTS.md` "Gates", `design.md` §15); `pytest` is the only verification, so there is no lint command to run |

All gate commands used the resolved write-target scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1838 | ✅ Pass (`1838 passed in 27.92s`) |
| `tests/test_state.py` | 22 | ✅ Pass (count from `--collect-only`; all collected tests executed inside the full-suite run above) |
| `tests/test_target_config.py` | 162 | ✅ Pass (count from `--collect-only`; all collected tests executed inside the full-suite run above) |
| `tests/test_prompt_workflow.py` | 171 | ✅ Pass (count from `--collect-only`; all collected tests executed inside the full-suite run above) |
| `tests/test_cli.py` | 69 | ✅ Pass (count from `--collect-only`; all collected tests executed inside the full-suite run above) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `create_run(..., toolkit_version=..., config_schema_version=..., config_hash=...)` persists all three in `state.json` (`tests/test_state.py::test_create_run_records_toolkit_version_and_config_identity`) | ✅ Passed inside the full-suite run |
| A `state.json` without the three fields loads with all three `None` (`tests/test_state.py::test_old_state_without_identity_still_loads`, `::test_create_run_defaults_the_identity_fields_to_none`) | ✅ Passed inside the full-suite run |
| Additive fields do not disturb the `totals` ordering and round-trip property (`tests/test_state.py::test_identity_fields_do_not_disturb_the_recorded_totals_block`, `::test_identity_fields_round_trip_property`) | ✅ Passed inside the full-suite run |
| `config_hash` equals the hand-computed `sha256` of `json.dumps(resolved.to_dict(), sort_keys=True)` (`tests/test_target_config.py::test_config_identity_hashes_the_resolved_config_as_documented`) | ✅ Passed inside the full-suite run |
| `config_schema_version` is the config schema (`1` when declared, `None` for a config-less repo), not the state schema (`tests/test_target_config.py::test_config_identity_schema_version_is_the_config_schema_not_the_state_schema`, `::test_config_identity_schema_version_is_none_for_a_config_less_repo`) | ✅ Passed inside the full-suite run |
| Hash is deterministic across resolutions, changes when a resolved leaf changes, and separates a declared default from the default (`tests/test_target_config.py::test_config_identity_is_deterministic_across_two_resolutions`, `::test_config_identity_changes_when_one_resolved_leaf_changes`, `::test_config_identity_separates_a_declared_default_from_the_default`) | ✅ Passed inside the full-suite run |
| Helper is pure and hashes the resolved config rather than the declaration (`tests/test_target_config.py::test_config_identity_is_pure_and_never_mutates_the_resolved_config`, `::test_config_identity_is_computed_from_the_resolved_config_not_the_declaration`) | ✅ Passed inside the full-suite run |
| Dry-run `aidw prompt` writes `state.json` with `toolkit_version == aidw.__version__` and the two config fields matching the resolved fixture config (`tests/test_prompt_workflow.py::test_prompt_workflow_dry_run_records_run_identity`) | ✅ Passed inside the full-suite run |
| `exec` records `toolkit_version` and leaves both config fields `None` (`tests/test_cli.py`) | ✅ Passed inside the full-suite run |

---

## Deviations observed during recording

- **No lint command exists to gate** — `AGENTS.md` names no lint stage and `design.md` §15 states `pytest` is the only verification, so the lint row is marked unverified rather than passed.
- **No build command is listed in `AGENTS.md`** — the build row uses the packaging command established by E8.1 (`uv build --no-build-isolation --out-dir <tmp>`) to verify the wheel still builds from this tree; it is a real observation from this run, not a copied result.
- **Traceability/architecture stages found their prompt-specific toolchains inapplicable to `aidt`** (no pnpm/SRD catalog, no `docs/architecture/`) and wrote no artifact; that concerns their stages, not this verification gate.

---

## Non-Goals (NOT implemented)

- ❌ E8.3 — `aidw --version`, doctor version/git/compatibility reporting; `toolkit_version` is written to state, never printed (task prompt "Explicit non-goals").
- ❌ E8.4 — README install paths; no documentation was written (task prompt "Explicit non-goals").
- ❌ E8.5 — release process and first tag; no tag was created (task prompt "Explicit non-goals").
- ❌ E4.8's gate-citation tree identity; `GateOutcome.tree` and `aidw/verification.py` were not touched (task prompt "Explicit non-goals").
- ❌ The design.md §9.2 schema-example rewrite; this task adds only a §17 decision-log entry, and E9.1 owns that rewrite (task prompt "Explicit non-goals").
- ❌ No commit, push, or PR was made by this stage; `/pr` owns delivery.
