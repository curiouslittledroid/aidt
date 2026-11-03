# Build Results — 00-E3.6: Document the config contract

**Branch:** `00-E3.6`
**Date:** 2026-11-03
**Spec:** `docs/migration/EXTRACTION.md` §3.4 (target-repo config: tracked `aidw/` layout, "required if the folder exists", "no `aidw/` folder is valid", precedence, D17 defaults), §3.12 (new repo layout: the `docs/target-repo-config.md` entry), §2 (D3 tracked `aidw/`, D10 `schema_version`/`requires_toolkit` refusal, D11 YAML, D12 override granularity, D17 defaults = Mythical Forge layout); `design.md` §12 (`max_revisions`, default `3`, CLI > config > `3`) and §3 (repository layout)

## Summary

**Purpose:** Replace the placeholder `docs/target-repo-config.md` with the authoritative contract for `<target>/aidw/config.yaml` — every loader-accepted field with its type, default and effect, both override-precedence layers, and three worked Minimal/Typical/Full examples — so a reader can author a correct config without reading the loader.

| Decision | Why it matters |
|----------|---------------|
| Document from `aidw.target_config`'s field-name constants, never re-typed | The doc must name exactly the keys the loader accepts; a new or removed key then fails `tests/test_target_repo_config_doc.py` instead of silently drifting from the schema. |
| `schema_version` is documented as **unset**, not defaulted to `1` | Only `max_revisions`/`repo.*`/`paths.*` resolve when absent; conflating the two misstates `resolve_config`'s output. |
| `github.*` and `workflows.*` are documented as **unset** until E6/E4.1 seed them | Presenting the §3.4/D5 literals as current defaults would contradict today's resolver; the Full example declares them explicitly instead. |
| Two precedence layers are kept distinct: `override > config > default > unset` for values, and explicit `prompt:` → `aidw/prompts/` → toolkit default → error for prompts | The exact conflation §3.4 forbids; the doc is pinned on both orders. |
| The three `yaml` examples are extracted from the doc itself and loaded/resolved by the test, not kept as fixtures | A reader's copy-paste target is what gets executed, so doc↔code drift cannot hide in a separate fixture. |
| `roadmap_glob` is reproduced as the literal `[0-9]* - *.md` (space-dash-space) | The `[0-9]*-*.md` typo silently matches nothing; the doc calls that out next to the value. |
| Read-path contract stated for all four paths, with `architecture_dir` as the write-target exemption | Sets up E3.7's existence validation without implementing it here. |

**Where it fits in the roadmap:** E3.6 in the extraction epic. It consumes E3.1's schema, E3.2's resolver, E3.4's seeded defaults and E3.5's doctor check, and turns them into operator-facing documentation. E3.7 owns read-path existence validation and the write-target classification this doc states as contract; E9.2 cross-links both contract docs from the README; E4.1/E4.5 own the enforced stage vocabulary and E6 owns the frozen `github.*` defaults the doc marks unset.

**Scope:** Touches `docs/target-repo-config.md` (placeholder body replaced), adds `tests/test_target_repo_config_doc.py` (field coverage, defaults, precedence wording and the three loaded/resolved examples), and marks E3.6 complete on the extraction roadmap. It deliberately stops short of any loader, schema, doctor or CLI change, any path-existence enforcement, the E6.4 freeze rationale, the E4.1/E4.5 stage-registry enforcement, and README cross-linking.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `tests/test_target_repo_config_doc.py` | Created | Doc-consistency test: asserts the doc names exactly the loader's keys and none it rejects, that stated defaults equal `TOOLKIT_DEFAULTS` + `DEFAULT_MAX_REVISIONS`, that both precedence orders are present, and that the three fenced examples load with zero `ERROR` issues and resolve to the claimed values. |
| `docs/task-prompts/00-E3.6-prompt.md` | Created | Task prompt recording the requirements, traps, non-goals and deliverables for E3.6. |
| `docs/target-repo-config.md` | Modified | Placeholder body replaced with the §3.4 contract: tracked `aidw/` layout, full field inventory (type/default/effect), the seeded defaults and the genuinely-unset values, the two precedence layers, the read-path contract, and Minimal/Typical/Full examples. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E3.6 complete on the extraction roadmap. |

---

## Verification Results

Every gate was run through `aidw gate run <key> $SCOPE -- <command>` with `SCOPE="--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts"` — the document this stage writes plus the write-targets of the other stages. Every outcome below is a real observation against tree `ba047a69a30a` from this run; none was reused from an earlier run or copied from another document. `AIDW_STAGE` / `AIDW_RUN_ID` were removed from the child environment for the pytest and doctor-style commands so the recorder's ambient identity did not leak into the suite, matching CI.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `aidw gate run install $SCOPE -- uv sync --frozen` | ✅ `Checked 15 packages in 3ms` — frozen lock consistent (gate `install`, tree `ba047a69a30a`, stage `record-implementation-results`, 2026-11-03T07:26:59Z) |
| Build | `aidw gate run build $SCOPE -- uv build --out-dir <tmp>` | ✅ Built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` (gate `build`, tree `ba047a69a30a`, stage `record-implementation-results`, 2026-11-03T07:27:04Z) |
| Test | `aidw gate run suite $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ✅ `1005 passed in 22.32s` (gate `suite`, tree `ba047a69a30a`, stage `record-implementation-results`, 2026-11-03T07:27:26Z) |
| Doctor | `aidw gate run doctor $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw doctor` | ✅ exit 0 — 19 checks: 0 failed, 2 warnings (dirty working tree; missing `.mcp.json`); `target config` reports `none (defaults)` (gate `doctor`, tree `ba047a69a30a`, stage `record-implementation-results`, 2026-11-03T07:27:31Z) |
| Agents validate | `aidw gate run agents-validate $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw agents validate --strict` | ✅ exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `ba047a69a30a`, stage `record-implementation-results`, 2026-11-03T07:27:30Z) |
| Prompts check | `aidw gate run prompts-check $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw prompts check` | ✅ exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `ba047a69a30a`, stage `record-implementation-results`, 2026-11-03T07:27:31Z) |
| Whitespace | `git diff --check` | ✅ exit 0, no whitespace errors |
| Lint | — | **unverified** — the repository configures no linter or formatter (`AGENTS.md` "Gates": pytest is the only verification; none was added in this task) |

### `uv run --frozen pytest` (full suite)

Counts are from the single full-suite gate invocation above. The per-file counts are collection-only (`pytest --collect-only -q`, which executes no test) and show the files the full suite already covered; no test was re-run for a row. The suite reported no skips, xfails or failures.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1005 | ✅ Pass (`1005 passed in 22.32s`) |
| `tests/test_target_repo_config_doc.py` | 18 | ✅ Pass (all part of the full-suite run) |
| `tests/test_target_config.py` | 114 | ✅ Pass (all part of the full-suite run) |
| `tests/test_design_doc.py` | 4 | ✅ Pass (all part of the full-suite run) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| The placeholder is gone and the `docs/schema/aidw-config.schema.json` pointer is kept | ✅ `test_doc_is_not_the_placeholder` passed |
| The tracked `aidw/` layout, `config.yaml` "required if the folder exists", and a config-less repo resolving to pure defaults are documented | ✅ `test_doc_states_the_tracked_layout_and_the_no_folder_case` passed |
| All four read-paths plus `architecture_dir` as the write-target exemption are stated, with E3.7 named as the enforcing task | ✅ `test_doc_states_the_read_path_contract_and_the_write_target_exemption` passed |
| The doc names every key from the loader's field-name constants and no rejected key | ✅ `test_field_inventory_documents_exactly_the_loader_keys` passed |
| Every documented default equals `TOOLKIT_DEFAULTS` / `DEFAULT_MAX_REVISIONS`, with unset/required recorded | ✅ `test_documented_defaults_are_the_toolkit_defaults` passed |
| `model`/`thinking`/`timeout_seconds` appear only as rejected stage fields, and the loader actually fails closed on each | ✅ `test_stage_fields_the_loader_rejects_are_documented_as_rejected` and `test_loader_fails_closed_on_the_stage_fields_the_doc_calls_rejected` passed |
| The `override > config > default > unset` value order and the `--max-revisions` flag are documented | ✅ `test_value_precedence_order_is_documented` passed |
| The four-step prompt-resolution order is documented in order | ✅ `test_prompt_precedence_order_is_documented` passed |
| Exactly three `yaml` examples exist, are pairwise distinct, and Minimal is `schema_version`-only | ✅ `test_doc_has_exactly_three_yaml_examples` and `test_examples_are_pairwise_distinct_and_minimal_is_schema_version_only` passed |
| Minimal resolves to the full Mythical Forge layout with `default` provenance; Typical resolves to the same values with two `config` leaves | ✅ `test_minimal_resolves_to_the_mythical_forge_layout` and `test_typical_resolves_to_the_same_values_with_configured_provenance` passed |
| Full declares every leaf and resolves entirely from `config`, including the D5 marker/label literals and the stage chain | ✅ `test_full_example_declares_every_field_and_resolves_from_config` passed |
| Resolving the examples is pure: no mutation of `TOOLKIT_DEFAULTS` and no aliasing of resolved containers | ✅ `test_resolving_the_examples_is_pure` passed |
| Each of the three examples loads with zero `ERROR` issues | ✅ `test_each_example_loads_with_no_error_issues` passed for the `Minimal`, `Typical` and `Full` parametrizations |
| The gate set is unchanged by this task (`pytest`, `doctor`, `prompts check` stay green) | ✅ Observed in the `suite`, `doctor` and `prompts-check` gates above |

---

## Deviations observed during recording

- **The stage prompt's generic pnpm commands do not apply to this repository.** This is the `aidt` toolkit (Python/uv), so the `AGENTS.md` / `prompts/pr.md` gate set was run instead. `pnpm install`, `pnpm -r lint`, `pnpm -r build` and `pnpm -r test` were not run, and the `lint` row is recorded as unverified rather than passing.
- **The targeted pytest commands in the task prompt's "Done when" were not re-run.** `tests/test_target_repo_config_doc.py`, `tests/test_target_config.py` and `tests/test_design_doc.py` are fully included in the single full-suite gate above, which passed; their per-file counts are collection-only to avoid buying the same tests twice, matching the E3.3/E3.4/E3.5 record.
- **`uv build` does not write into the tree.** It built into a `mktemp -d` directory, so the gated tree stayed identical to the delivered change set.
- **The implementation is uncommitted on this branch.** `git diff main` shows the doc and roadmap edits plus the untracked test file; the change set verified here is the working tree relative to `main`, not only the one commit on the branch.

---

## Non-Goals (NOT implemented)

- ❌ E3.7 read/write path classification and existence validation — the doc states the read-path contract for the four paths E3.7 validates, but implementing/checking path existence (and any `aidw doctor` change) is E3.7's.
- ❌ E6.4 "Document the freeze" — explaining *why* markers/labels are config-with-frozen-defaults and what a rename breaks; E3.6 only states the field shape and marks the defaults unset.
- ❌ E4.1/E4.5 stage registry and core-vs-optional enforcement — the doc states the stage-entry shape, not the enforced stage-id vocabulary or reorder/disable rules.
- ❌ E9.2 cross-linking both contract docs from the README.
- ❌ Any change to `aidw/target_config.py`, `docs/schema/aidw-config.schema.json`, `aidw/doctor.py`, or the CLI — documentation plus a doc-consistency test only.
- ❌ No commit, push, or PR was made by this stage.
