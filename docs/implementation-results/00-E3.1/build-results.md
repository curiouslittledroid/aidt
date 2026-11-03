# Build Results — 00-E3.1: Schema, loader, validation

**Branch:** `00-E3.1`
**Date:** 2026-11-03
**Spec:** `docs/migration/EXTRACTION.md` §3.4 (target-repo config), §2 (D10, D11, D17), §3.9 (persisted GitHub contracts, D5); `design.md` §12 (configuration and the `max_revisions` key)

## Summary

**Purpose:** Define the target-repo config schema (`<target>/aidw/config.yaml`) as dataclasses, ship it as a hand-written JSON Schema, and provide a fail-closed loader that rejects unknown keys and wrong types with the offending field path.

| Decision | Why it matters |
|----------|---------------|
| New module `aidw/target_config.py` rather than extending `aidw/config.py` | `aidw/config.py` already owns *agent* config (`load_agent`/`load_all`, design §5); a second, unrelated schema behind the same module name would risk breaking agent loading. |
| `load_target_config(path)` takes the config **file** path and returns `TargetConfig` carrying `.issues` | Mirrors `load_agent`'s single-file shape; resolving the target root to `aidw/config.yaml` is E3.2/E3.5's job. Reuses `Issue`/`ERROR`/`WARNING`/`format_issues` from `aidw/config.py` so `aidw doctor` (E3.5) can format both. |
| Unknown keys are errors at every object level (top level, `repo`, `paths`, each workflow, each stage, `github`, `markers`, each label entry) | A top-level-only check would let a typo such as `workflows.implement.stages[0].enabld` load silently. |
| `github.markers` is a fixed three-field object; `github.labels` is an open map whose entries are exactly `{color, description}` | §3.9/D5 freezes the three marker keys while label names are repo-chosen; `publish_review_followups.py` reads both label fields unconditionally. |
| `max_revisions` is accepted at the top level | It is a real key (design.md §12) that §3.4's YAML listing omits; rejecting it would reject a legitimate config. Its default-3 merge is E3.2's, so no value is baked into the loader. |
| Hand-written `docs/schema/aidw-config.schema.json`, no generation dependency | Keeps `pyproject.toml`/`uv.lock` unchanged so the frozen-lock gate stays as it was; a field-agreement test guards drift between dataclasses and schema. |
| A missing config file is not an error; a non-mapping file is | §3.4 says a target repo with no `aidw/` folder is valid, while an empty/list/scalar file must produce an issue rather than an `AttributeError`. |

**Where it fits in the roadmap:** E3.1 in the extraction epic — the schema foundation for E3.2 (layered resolution with provenance), E3.3 (version/compat refusal), E3.4 (Mythical-Forge defaults), E3.5 (`aidw doctor` wiring), E3.6 (`docs/target-repo-config.md`) and E3.7 (read-path existence validation). E4.1/E4.5 own the stage registry and id vocabulary, and E4.6 owns stage `model`/`thinking`/`timeout_seconds` overrides.

**Scope:** Adds `aidw/target_config.py`, `docs/schema/aidw-config.schema.json` (replacing `docs/schema/.gitkeep`) and `tests/test_target_config.py`. It deliberately stops short of merging defaults, comparing `schema_version`/`requires_toolkit`, validating path existence, wiring `aidw doctor`/`cli.py`, documenting the config for operators, enumerating stage ids or workflow names, or adding the E4.6 stage override fields.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `aidw/target_config.py` | Created | §3.4 dataclasses (`TargetConfig`, `RepoConfig`, `PathsConfig`, `WorkflowConfig`, `StageConfig`, `GitHubConfig`, `MarkersConfig`, `LabelConfig`), `load_target_config`, recursive unknown-key rejection, type validation, and a pure serializer for round-trip. |
| `docs/schema/aidw-config.schema.json` | Created | Hand-written JSON Schema (draft 2020-12) for the same schema: `additionalProperties: false` at every object level, required/optional fields, types, and `enum`/`const` where a value set is fixed. |
| `tests/test_target_config.py` | Created | Contract tests: full and near-empty configs, missing file, non-mapping/unparseable YAML, unknown keys at every level, wrong types, missing required keys, round-trip losslessness/purity, and dataclass ↔ JSON-Schema agreement. |
| `docs/schema/.gitkeep` | Deleted | The schema directory now ships a real file. |

---

## Verification Results

Every gate was run once in this recording against tree `a218a8df3c9c` with the stage name `record` and the scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`. The repository is Python/uv, so the gates are `AGENTS.md`'s, not the front-matter prompt's pnpm commands.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.46ms` — frozen lock consistent |
| Build | `aidw gate run build $SCOPE --stage record -- uv build --out-dir <tmp>` | ✅ `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` built (gate `build`, tree `a218a8df3c9c`, stage `record`, 2026-11-03T03:09:41Z) |
| Test | `aidw gate run suite $SCOPE --stage record -- uv run --frozen pytest` | ❌ `4 failed, 894 passed in 20.26s` (gate `suite`, tree `a218a8df3c9c`, stage `record`, 2026-11-03T03:10:03Z) |
| Doctor | `aidw gate run doctor $SCOPE --stage record -- uv run --frozen aidw doctor` | ✅ exit 0 — 18 checks: 0 failed, 2 warnings (dirty working tree; missing `.mcp.json`) (gate `doctor`, tree `a218a8df3c9c`, stage `record`, 2026-11-03T03:10:08Z) |
| Agents validate | `aidw gate run agents-validate $SCOPE --stage record -- uv run --frozen aidw agents validate --strict` | ✅ exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `a218a8df3c9c`, stage `record`, 2026-11-03T03:10:08Z) |
| Prompts check | `aidw gate run prompts-check $SCOPE --stage record -- uv run --frozen aidw prompts check` | ✅ exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `a218a8df3c9c`, stage `record`, 2026-11-03T03:10:08Z) |
| Whitespace | `git diff --check` | ✅ exit 0, no whitespace errors |
| Lint | — | **unverified** — the repository configures no linter/formatter (`AGENTS.md` "Gates": pytest is the only verification; none is added inside this task) |

### `uv run --frozen pytest` (full suite)

Counts are from the single failing full-suite gate invocation above; the per-file count is collection-only (`pytest --collect-only -q`, which executes no test). The run reported no skips or xfails.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 898 | ❌ Fail (`4 failed, 894 passed in 20.26s`) |
| `tests/test_target_config.py` | 71 | ❌ Fail (`67 passed, 4 failed` — part of the full-suite run) |

**Failing tests (all in `tests/test_target_config.py`):**

- `test_wrong_type_is_an_error_naming_the_offending_path[repo-null]`
- `test_wrong_type_is_an_error_naming_the_offending_path[paths-null]`
- `test_wrong_type_is_an_error_naming_the_offending_path[workflows-null]`
- `test_wrong_type_is_an_error_naming_the_offending_path[github-null]`

Each case feeds `{"schema_version": 1, "repo"|"paths"|"workflows"|"github": None}` and expects an issue whose message names the path and contains `must be`. The assertion `any(f"`{path}`" in message and "must be" in message …)` receives no such message. The loader's `_mapping(..., null_ok=True)` treats an explicit `null` for these optional containers as absent, while the test contract requires `null` to be a type error naming the path.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run --frozen pytest tests/test_target_config.py` (task prompt "Done when") | ❌ Fail — derived from the same full-suite run: 71 collected, 67 passed, 4 failed (see failing tests above). Not re-run separately. |
| Full §3.4-shaped config loads with zero errors and every field populated | ✅ `test_full_section_3_4_config_loads_with_every_field_populated` passed |
| `schema_version: 1`-only config and missing config file load without error | ✅ `test_schema_version_only_config_loads_without_error`, `test_missing_config_file_is_valid_defaults_with_no_issues` passed |
| Non-mapping and unparseable YAML → ERROR, no exception | ✅ `test_non_mapping_yaml_is_an_error_not_an_attribute_error`, `test_unparseable_yaml_is_an_error_not_an_exception` passed |
| Unknown keys at top level, `repo`, stage, label entry → ERROR naming the path | ✅ `test_unknown_key_is_an_error_naming_the_offending_path` passed |
| Missing `schema_version` and label `color`/`description` → ERROR naming the path | ✅ `test_missing_required_key_is_an_error_naming_the_path` passed |
| Round-trip lossless and pure (no input mutation, no default inflation) | ✅ `test_full_config_round_trip_is_exact_and_lossless`, `test_round_trip_preserves_the_declared_config`, `test_loader_and_serializer_are_pure` passed |
| JSON Schema agrees with dataclass fields; `additionalProperties: false`; boolean enum mechanism | ✅ `test_json_schema_properties_agree_with_dataclass_fields`, `test_json_schema_rejects_unknown_keys_at_every_fixed_object_level`, `test_json_schema_carries_the_boolean_enum_mechanism`, `test_dataclass_field_names_are_the_fixed_section_3_4_names` passed |
| Wrong types other than an explicit `null` container (e.g. `schema_version: "1"`, `repo.base_branch: 7`, `enabled: "yes"`, label colour `5`) → ERROR naming the path | ✅ All other `test_wrong_type_is_an_error_naming_the_offending_path` parameters passed |

---

## Deviations observed during recording

- **Front-matter gate list does not apply to this repository** — the task prompt's generic instructions name pnpm gates; this is the `aidt` toolkit (Python/uv), so the `AGENTS.md` gate set was run instead, matching `prompts/pr.md`'s stack table.
- **The full suite fails, so this stage records the failure and stops** — four `null`-container wrong-type cases disagree with the loader's `null_ok=True` treatment. Nothing was fixed here (this stage does not modify implementation or tests).
- **The task-specific `tests/test_target_config.py` gate was not re-run** — its outcome is derived from the single full-suite invocation, per the record stage's no-duplicate-runs rule.

---

## Non-Goals (NOT implemented)

- ❌ E3.2 layered resolution with per-value provenance (merging toolkit defaults → config); `repo.base_branch`/`branch_pattern` are not wired into `paths.py:TargetRepo`.
- ❌ E3.3 version/compat refusal (`schema_version` newer than understood, `requires_toolkit` unsatisfied); the fields are loaded and type-checked only.
- ❌ E3.4 Mythical-Forge default values; a `schema_version: 1`-only config does not produce the MF layout.
- ❌ E3.5 `aidw doctor` config validation and exit-code wiring; `aidw/doctor.py` and `cli.py` untouched.
- ❌ E3.6 `docs/target-repo-config.md`; operator documentation is not written here.
- ❌ E3.7 read-path existence validation; `paths:` values are opaque strings and no `Path.exists()` check is performed.
- ❌ E4.1/E4.5 stage registry, id vocabulary, and core-vs-optional enforcement; stage ids and workflow names are free strings.
- ❌ E4.6 stage `agent`/`model`/`thinking`/`timeout_seconds` overrides; only `id`, `enabled`, `prompt`, `agent` are accepted.
- ❌ No commit, push, or PR was made by this stage.
