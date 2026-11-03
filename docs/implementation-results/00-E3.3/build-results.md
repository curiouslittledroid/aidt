# Build Results — 00-E3.3: Version and compatibility refusal (D10)

**Branch:** `00-E3.3`
**Date:** 2026-11-03
**Spec:** `docs/migration/EXTRACTION.md` §3.11 (version and compatibility, D10), §3.4 (the `schema_version` / `requires_toolkit` fields and "a target repo with no `aidw/` folder is valid"), and §2 locked decision D10; `design.md` §14 (CLI exit codes: `2` usage/config error, `4` preflight/safety refusal) and §3 / `docs/migration/EXTRACTION.md` §3.12 (no new top-level folders)

## Summary

**Purpose:** Refuse to run a workflow when the target repo's `aidw/config.yaml` declares a `schema_version` this toolkit does not understand, or a `requires_toolkit` pin the toolkit's own version does not satisfy, with a clear, actionable message instead of silently proceeding.

| Decision | Why it matters |
|----------|---------------|
| `check_compatibility` is a separate pure pass after the loader, taking `toolkit_version` as an argument | The E3.1 loader keeps loading/type-checking and stays free of version semantics; passing the version in (rather than importing it or hardcoding `0.1.0`) keeps the module testable against hand-calculated vectors and prevents `target_config -> workflows.prompt` import cycles. |
| `packaging.version.Version` + `packaging.specifiers.SpecifierSet` for the pin | String comparison is wrong (`"0.1.0" >= "1.0.0"` is `True` lexicographically) and a hand-rolled tuple parse mishandles PEP 440 pre-release/build metadata. An invalid specifier or toolkit version becomes an ERROR issue, never a traceback. |
| Refusal is `schema_version > SUPPORTED_SCHEMA_VERSION`, not `!=` | The spec names only "newer than understood". A `schema_version: 0` (or a missing config, whose `schema_version` is `None`) is valid and must not be refused; the `state.py:load` strict-equality shape would break every defaults-only repo. |
| Both refusals are evaluated independently | A config that is both newer and pins an unsatisfied version reports two issues; reporting only the first would make the user fix, re-run, and discover the second refusal later. |
| The refusal lives at the E3.2 config-refusal site in `prompt.py`: `format_issues` to stderr and exit `2` | §3.11's "refuses to run" means before `load_tasks`, `derive_branch_name`, any run record, branch or worktree, and on `--dry-run` too. Exit `2` keeps both config refusals on one code; `EXIT_REFUSED` (`4`) stays reserved for git/worktree/layout refusals. |
| `aidw config show` gains no refusal | It is the inspection aid that shows the resolved `schema_version`/`requires_toolkit` with provenance, so a user can see *why* a workflow refuses. A refusal there would remove the diagnostic surface. |

**Where it fits in the roadmap:** E3.3 in the extraction epic. It consumes E3.1's loader (`TargetConfig`, `Issue`/`ERROR`, the `path.name` issue-source convention) and E3.2's resolved-config contract and `prompt.py` refusal site. It is the enforcement half of `requires_toolkit`; E3.4 seeds Mythical-Forge default values, E3.5 wires config validation into `aidw doctor`, E3.6 documents the target-repo config for operators, E4.3 makes the other workflows config-driven (they will call this same check), E4.2 owns the third §3.11 refusal (unresolvable required prompt), and E8 owns tag-based releases and documenting how a repo pins `requires_toolkit`.

**Scope:** Touches `aidw/target_config.py` (the compatibility check and its constant), `aidw/workflows/prompt.py` (the refusal wiring), `pyproject.toml` / `uv.lock` (the `packaging` dependency), their contract and end-to-end tests, and the extraction roadmap checkbox. It deliberately stops short of seeding remaining default values, doctor validation, path-existence checks, operator documentation, wiring the check into workflows that do not yet read config, the prompt-resolver refusal, and release/pinning documentation.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `aidw/target_config.py` | Modified | Adds `SUPPORTED_SCHEMA_VERSION = 1`, `CONFIG_FILENAME`, the message helpers, and the pure `check_compatibility(declared, *, toolkit_version)` returning fresh ERROR issues for a newer schema and an unsatisfied/unparseable `requires_toolkit`; docstring now separates loading from version interpretation. |
| `aidw/workflows/prompt.py` | Modified | Imports `__version__` and `check_compatibility`; immediately after the E3.2 config-ERROR refusal, prints compatibility issues with `format_issues` to stderr and returns `2` before task loading, branch derivation, run records, branches, worktrees, and regardless of `--dry-run`. |
| `tests/test_target_config.py` | Modified | Adds compatibility contract tests: current/older/missing schema, satisfied/unsatisfied/upper-bound pins, newer schema, both refusals independently, invalid specifier and invalid toolkit version (issues, not exceptions), issue-source convention, purity/no-I/O, one-way import direction, and a seeded property run over both rules. |
| `tests/test_prompt_workflow.py` | Modified | Adds end-to-end refusals (newer schema, unsatisfied pin, invalid pin; real run and `--dry-run`) asserting exit `2`, stderr tokens, no stages, no run record, no branch/worktree; both-refusals case asserts two issues; a satisfied pin still proceeds. |
| `tests/test_cli.py` | Modified | Pins Requirement 5: on a `schema_version: 2` / impossible-pin config, `config show` still exits `0` and reports the resolved values with `source: config` — no refusal. |
| `pyproject.toml` | Modified | Adds the `packaging>=24.0` runtime dependency for PEP 440 version/specifier comparison. |
| `uv.lock` | Modified | Re-synced for `packaging` in the same change (AGENTS.md frozen-lock rule). |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E3.3 complete on the extraction roadmap. |

---

## Verification Results

All gates were run through `aidw gate run <key> $SCOPE --run 20261103T051650Z-00-E3.3-implement --stage record-implementation-results -- <command>`, with `SCOPE="--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts"` — the document this stage writes plus the write-targets of the other stages. Every outcome below is a real observation against tree `5e22ad5883fa`; none was reused from an earlier run or copied from another document. The `AIDW_STAGE`/`AIDW_RUN_ID` environment was removed for the child processes that run pytest, so the recorder's ambient identity did not leak into the gate's own tests (matching CI).

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `aidw gate run install $SCOPE -- uv sync --frozen` | ✅ `Checked 15 packages in 0.52ms` — frozen lock consistent (gate `install`, tree `5e22ad5883fa`, stage `record-implementation-results`, 2026-11-03T05:28:51Z) |
| Build | `aidw gate run build $SCOPE -- uv build --out-dir <tmp>` | ✅ Built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` (gate `build`, tree `5e22ad5883fa`, stage `record-implementation-results`, 2026-11-03T05:28:55Z) |
| Test | `aidw gate run suite $SCOPE -- uv run --frozen pytest` | ✅ `957 passed in 24.54s` (gate `suite`, tree `5e22ad5883fa`, stage `record-implementation-results`, 2026-11-03T05:29:23Z) |
| Doctor | `aidw gate run doctor $SCOPE -- uv run --frozen aidw doctor` | ✅ exit 0 — 18 checks: 0 failed, 2 warnings (dirty working tree; missing `.mcp.json`) (gate `doctor`, tree `5e22ad5883fa`, stage `record-implementation-results`, 2026-11-03T05:29:26Z) |
| Agents validate | `aidw gate run agents-validate $SCOPE -- uv run --frozen aidw agents validate --strict` | ✅ exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `5e22ad5883fa`, stage `record-implementation-results`, 2026-11-03T05:29:29Z) |
| Prompts check | `aidw gate run prompts-check $SCOPE -- uv run --frozen aidw prompts check` | ✅ exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `5e22ad5883fa`, stage `record-implementation-results`, 2026-11-03T05:29:29Z) |
| Whitespace | `git diff --check` | ✅ exit 0, no whitespace errors |
| Lint | — | **unverified** — the repository configures no linter or formatter (`AGENTS.md` "Gates": pytest is the only verification; none was added in this task) |

### `uv run --frozen pytest` (full suite)

Counts are from the single full-suite gate invocation above. Per-file counts are collection-only (`pytest --collect-only -q`, which executes no test) and show the task-specific slice the full suite already covered; no test was re-run for a row. The suite reported no skips or xfails.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 957 | ✅ Pass (`957 passed in 24.54s`) |
| `tests/test_target_config.py` | 104 | ✅ Pass (all part of the full-suite run) |
| `tests/test_prompt_workflow.py` | 150 | ✅ Pass (all part of the full-suite run) |
| `tests/test_cli.py` | 46 | ✅ Pass (all part of the full-suite run) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `SUPPORTED_SCHEMA_VERSION == 1`; current schema with no pin is compatible | ✅ `test_supported_schema_version_is_one`, `test_current_schema_version_with_no_pin_is_compatible` passed |
| Satisfied pin is compatible; PEP 440, not string, ordering | ✅ `test_satisfied_requires_toolkit_is_compatible` passed (`>=0.10.0` with `0.9.0` refuses; `>=0.9.0` with `0.10.0` accepts) |
| Newer `schema_version` is one ERROR naming the field, value, ceiling and both remedies | ✅ `test_newer_schema_version_refuses_naming_field_value_and_supported` passed |
| Unsatisfied `requires_toolkit` names the field, specifier and toolkit version | ✅ `test_unsatisfied_requires_toolkit_refuses_naming_field_specifier_and_version` passed |
| Upper-bound pin (`<=0.0.5`) also refuses | ✅ `test_upper_bound_pin_also_refuses` passed |
| Newer schema **and** unsatisfied pin produce two independent issues | ✅ `test_both_refusals_are_independent_issues` passed |
| Invalid specifier (`banana`) and invalid toolkit version are ERROR issues, not tracebacks | ✅ `test_invalid_requires_toolkit_specifier_is_an_issue_not_an_exception`, `test_invalid_toolkit_version_is_an_issue_not_an_exception` passed |
| Missing config (`None`) and older/current `schema_version` are not refusals | ✅ `test_missing_config_is_compatible`, `test_missing_config_file_loads_and_is_compatible`, `test_older_or_current_schema_version_is_not_a_refusal` passed |
| Issue source follows the loader's `path.name` convention | ✅ `test_compatibility_issue_source_follows_the_loader_name_convention`, `test_compatibility_issue_source_uses_the_declared_source_path` passed |
| Purity: input `TargetConfig` unchanged, no I/O; one-way workflow import | ✅ `test_check_compatibility_is_pure`, `test_compatibility_check_is_imported_by_the_workflow_not_reverse` passed |
| Seeded property run over both rules | ✅ `test_compatibility_refusal_property` passed |
| `prompt.run()` refuses before any state: exit `2`, stderr names the cause, no stage/run record/branch/worktree, real run and `--dry-run` | ✅ `test_e33_incompatible_config_refuses_before_any_state` passed (parametrized over newer schema, unsatisfied pin, invalid pin × real/dry-run) |
| Both refusals surface end-to-end as two stderr issues | ✅ `test_e33_both_refusals_are_reported` passed |
| Compatible config still proceeds | ✅ `test_e33_satisfied_pin_still_proceeds` passed |
| `config show` remains display-only on an incompatible config (exit 0, resolved values with `config` provenance) | ✅ `test_config_show_does_not_refuse_an_incompatible_config` passed |

---

## Deviations observed during recording

- **The task prompt's generic pnpm commands do not apply to this repository.** This is the `aidt` toolkit (Python/uv), so the `AGENTS.md` / `prompts/pr.md` gate set was run instead. `pnpm install`, `pnpm -r lint`, `pnpm -r build`, and `pnpm -r test` were not run.
- **The targeted module gates were not re-run.** The task prompt's "Done when" names `pytest tests/test_target_config.py` and `pytest tests/test_prompt_workflow.py`; both are fully included in the single full-suite gate above, which passed. Per-file counts are collection-only to avoid buying the same tests twice, matching the E3.2 record.
- **`uv build` does not write into the tree.** It built into a `mktemp -d` directory, so the gated tree stayed identical to the delivered change set.
- **`doctor`'s dependency line lists `pyyaml, typer` only.** It does not enumerate `packaging`, but the install/suite gates and the build both import and exercise it; no change was made to `aidw/doctor.py` (E3.5 is a separate task).

---

## Non-Goals (NOT implemented)

- ❌ E3.4 Mythical-Forge default *values* under `paths:` / `repo:` — the defaults structure was not touched (D10/§3.11).
- ❌ E3.5 `aidw doctor` config validation and exit-code wiring — `aidw/doctor.py` was not modified and doctor reports no incompatibility.
- ❌ E3.7 read-path existence validation — no `Path.exists()` on `paths:` fields.
- ❌ E4.2's third §3.11 refusal ("a required prompt cannot be resolved") — that belongs to the prompt resolver.
- ❌ E4.3 wiring the check into every workflow — only `prompt.py` reads config today and is the only caller.
- ❌ E8 tag-based releases and documenting how a repo pins `requires_toolkit` — this task only enforces the pin.
- ❌ `docs/schema/aidw-config.schema.json` — not touched; `schema_version` stays `type: integer`, value semantics are this task's.
- ❌ No commit, push, or PR was made by this stage.
