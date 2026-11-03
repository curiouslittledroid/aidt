# Build Results — 00-E3.2: Layered resolution with provenance

**Branch:** `00-E3.2`
**Date:** 2026-11-03
**Spec:** `docs/migration/EXTRACTION.md` §3.3 (CLI surface: `aidw config show` with per-value provenance) and §3.4 (target-repo config, precedence, "a target repo with no `aidw/` folder is valid"); `design.md` §12 (configuration and the `max_revisions` precedence) and §17 resolved decision H8 (resolution wired to the loader, toolkit default stays 3)

## Summary

**Purpose:** Merge the toolkit defaults under a target repo's declared config and under per-invocation overrides, recording for every resolved value whether it came from `default`, `config`, or `override`, and render that provenance through `aidw config show` and `aidw prompt`'s revision budget.

| Decision | Why it matters |
|----------|---------------|
| `ResolvedConfig` is one flat mapping keyed by each §3.4 leaf's dotted path, with whole-list entries at the list path | Later consumers (E3.4/E4.1/E6) share a single addressing contract; mirroring YAML nesting or splitting list elements would create competing schemes, and lists are never merged element-wise. |
| `DEFAULT_MAX_REVISIONS = 3` has its single home in `aidw/target_config.py` | `prompt.py` imports it from there. Keeping the definition in the workflow module (the pre-E3.1 interim wording in design §12) would create a `target_config -> workflows.prompt -> target_config` import cycle once resolution is wired in. |
| Defaults are seeded with only `max_revisions`; `repo`/`paths`/`github`/`workflows` slots are empty | `repo:`/`paths:` values belong to E3.4, `github:` values to E6, and workflow stage defaults to E4.1. Empty slots resolve to *unset* rather than inventing a second source of truth next to `aidw.paths.TargetRepo`. |
| Provenance follows declared-ness, not `value == default` | An explicit `max_revisions: 3` must still report `source == "config"`; the loader's `_declared` bookkeeping is the mechanism E3.1 built for exactly this. |
| `config show` and `aidw prompt` fail closed on loader ERROR issues | A malformed or unreadable config must never silently resolve to defaults. `config show` exits `EXIT_STAGE_FAILURE` with issues on stderr and no JSON stdout; `aidw prompt` prints `format_issues` to stderr and returns 2 before any run record, branch, or worktree exists, including on `--dry-run`. |
| `resolve_config` is pure: no input mutation, no I/O, fresh containers | Resolve-twice and the E3.1 round-trip tests depend on the loader's declared config staying untouched; aliased result containers would let one consumer corrupt a later resolution. |

**Where it fits in the roadmap:** E3.2 in the extraction epic. It builds directly on E3.1's schema and fail-closed loader and completes the `max_revisions` wiring that design §12/H8 deferred until the loader existed. E3.3 (version/compat refusal), E3.4 (Mythical-Forge `repo:`/`paths:` defaults), E3.5 (`aidw doctor` wiring), E3.6 (operator docs), E3.7 (read-path existence validation), E4.1/E4.5 (stage registry/vocabulary), E4.6 (stage overrides), and E6 (GitHub marker/label defaults) all consume the resolved contract this task establishes.

**Scope:** Touches `aidw/target_config.py` (resolution API and defaults structure), `aidw/cli.py` (`config show`), `aidw/workflows/prompt.py` (`max_revisions` consumer), their contract tests, and the extraction roadmap checkbox. It deliberately stops short of version/compat refusal, seeding the remaining default values, doctor validation, operator documentation, path-existence checks, stage-registry work, and a broader override surface.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `aidw/target_config.py` | Modified | Adds `DEFAULT_MAX_REVISIONS`, the three provenance labels, `ResolvedValue`, `ResolvedConfig`, `ConfigOverrides`, `ConfigDefaults`/`TOOLKIT_DEFAULTS`, and the pure `resolve_config` merge walk over every §3.4 leaf. |
| `aidw/cli.py` | Modified | `config show` now loads and resolves the target config instead of using `is_file()`; adds the flat `config` JSON section, one human-mode `dotted-path: value (source)` line per leaf with `unset` for absent values, and fail-closed handling of loader ERROR issues. |
| `aidw/workflows/prompt.py` | Modified | Replaces the deferred `max_revisions` placeholder with `resolve_config` (CLI flag > config > default), imports `DEFAULT_MAX_REVISIONS` from its single home, and refuses a config carrying ERROR issues with stderr output and exit 2 before any run state. |
| `tests/test_target_config.py` | Modified | Adds resolver contract tests: precedence, explicit-value-equal-to-default provenance, partial-config unset state, whole-list and open-map entries, purity/alias-freedom, single-home constant, and a seeded property run over generated configs. |
| `tests/test_cli.py` | Modified | Updates `CONFIG_KEYS` and the pinned source expectations for the new `config` section; adds declared/unset rendering tests and flips the unparseable-YAML and directory-in-place-of-file edge cases to the fail-closed contract. |
| `tests/test_prompt_workflow.py` | Modified | Extends the `max_revisions` cases to prove config beats default, CLI beats config, and a broken config (unparseable, unknown key, wrong type, unreadable directory) refuses with exit 2 and creates no run state, including on `--dry-run`. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E3.2 complete on the extraction roadmap. |

---

## Verification Results

All gates were run through `aidw gate run <key> $SCOPE --run 20261103T040002Z-00-E3.2-implement --stage record-implementation-results -- <command>`, with `SCOPE="--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts"`: the document this stage writes plus the write-targets of the other stages. The outer `aidw` process ran with the stage/run supplied explicitly, while `AIDW_STAGE`/`AIDW_RUN_ID` were removed from the child environment so pytest's own gate tests did not inherit this recording identity (matching CI). Every outcome below is a real observation against tree `dffb12d5cdc2`; none was reused from an earlier run or copied from another document.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `aidw gate run install $SCOPE -- uv sync --frozen` | ✅ `Checked 15 packages in 2ms` — frozen lock consistent (gate `install`, tree `dffb12d5cdc2`, stage `record-implementation-results`, 2026-11-03T04:15:40Z) |
| Build | `aidw gate run build $SCOPE -- uv build --out-dir <tmp>` | ✅ Built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` (gate `build`, tree `dffb12d5cdc2`, stage `record-implementation-results`, 2026-11-03T04:15:43Z) |
| Test | `aidw gate run suite $SCOPE -- uv run --frozen pytest` | ✅ `928 passed in 21.71s` (gate `suite`, tree `dffb12d5cdc2`, stage `record-implementation-results`, 2026-11-03T04:16:08Z) |
| Doctor | `aidw gate run doctor $SCOPE -- uv run --frozen aidw doctor` | ✅ exit 0 — 18 checks: 0 failed, 2 warnings (dirty working tree; missing `.mcp.json`) (gate `doctor`, tree `dffb12d5cdc2`, stage `record-implementation-results`, 2026-11-03T04:16:11Z) |
| Agents validate | `aidw gate run agents-validate $SCOPE -- uv run --frozen aidw agents validate --strict` | ✅ exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `dffb12d5cdc2`, stage `record-implementation-results`, 2026-11-03T04:16:14Z) |
| Prompts check | `aidw gate run prompts-check $SCOPE -- uv run --frozen aidw prompts check` | ✅ exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `dffb12d5cdc2`, stage `record-implementation-results`, 2026-11-03T04:16:14Z) |
| Whitespace | `git diff --check` | ✅ exit 0, no whitespace errors |
| Lint | — | **unverified** — the repository configures no linter or formatter (`AGENTS.md` "Gates": pytest is the only verification; none was added in this task) |

### `uv run --frozen pytest` (full suite)

Counts are from the single full-suite gate invocation above. Per-file counts are collection-only (`pytest --collect-only -q`, which executes no test) and are reported only to show the task-specific slice that the full suite already covered; no test was re-run for a row. The suite reported no skips or xfails.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 928 | ✅ Pass (`928 passed in 21.71s`) |
| `tests/test_target_config.py` | 84 | ✅ Pass (all part of the full-suite run) |
| `tests/test_cli.py` | 45 | ✅ Pass (all part of the full-suite run) |
| `tests/test_prompt_workflow.py` | 142 | ✅ Pass (all part of the full-suite run) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `resolve_config` precedence: no config → `3`/`default`; config `5` → `5`/`config`; override `7` → `7`/`override` | ✅ Covered by the full-suite run (`test_undeclared_max_revisions_resolves_to_the_default`, `test_declared_max_revisions_beats_the_default`, `test_override_beats_declared_and_default`) |
| Declared-ness, not value equality: explicit `max_revisions: 3` → `3`/`config` | ✅ `test_explicit_value_equal_to_the_default_still_reports_config` passed |
| Partial config leaves other leaves `unset` (`value is None`, `source is None`) | ✅ `test_partial_config_leaves_every_other_leaf_unset` passed |
| Flat dotted-path addressing; whole-list workflow entries; open maps declare only present keys | ✅ `test_workflow_stages_are_one_whole_list_entry`, `test_declared_empty_lists_stay_config_rather_than_unset`, `test_declared_markers_and_labels_carry_config_provenance` passed |
| Resolver purity: input unchanged, resolve-twice identical, no I/O, fresh containers | ✅ `test_resolver_is_pure`, `test_resolved_lists_are_fresh_containers` passed |
| `DEFAULT_MAX_REVISIONS` single home and no reverse import cycle | ✅ `test_default_max_revisions_has_a_single_home` passed |
| Seeded property run over generated configs | ✅ `test_provenance_precedence_property` passed |
| `config show` JSON preserves six root entries and adds the flat `config` mapping | ✅ `test_config_show_json_single_checkout`, `test_config_show_dumps_a_declared_config_by_dotted_path` passed |
| `config show` human mode appends one dotted-path line per leaf, `unset` for absent values | ✅ `test_config_show_human_single_checkout`, `test_config_show_human_renders_declared_and_unset_leaves` passed |
| Broken config fails closed: unparseable YAML, unknown key, directory in place of the file → stderr issues, `EXIT_STAGE_FAILURE`, no JSON stdout | ✅ `test_config_show_unparseable_yaml_fails_closed`, `test_config_show_unknown_key_fails_closed_human_keeps_root_lines`, `test_config_show_config_file_directory_fails_closed` passed |
| Broken config symlink remains absent-like: `config_file` `null`/`defaults`, exit 0 | ✅ `test_config_show_broken_config_symlink_uses_defaults` passed |
| `aidw prompt` precedence end-to-end: CLI > config > default | ✅ `test_l43_config_max_revisions_beats_the_default`, `test_l43_cli_flag_beats_config_max_revisions` passed |
| `aidw prompt` refuses a broken config before any run state, including `--dry-run` | ✅ `test_l43_broken_config_refuses_instead_of_defaulting`, `test_l43_broken_config_refuses_on_a_dry_run_too`, `test_l43_unreadable_directory_config_refuses_before_dry_run` passed |
| Live `aidw config show` smoke check on this repo (no `aidw/config.yaml`) | ✅ exit 0 — `max_revisions: 3 (default)`, `config_file` `null`/`defaults`, every other leaf `unset` in both JSON and human mode |

---

## Deviations observed during recording

- **The task prompt's generic pnpm commands do not apply to this repository.** This is the `aidt` toolkit (Python/uv), so the `AGENTS.md` gate set was run instead, matching `prompts/pr.md`'s stack table and the earlier extraction records. `pnpm install`, `pnpm -r lint`, `pnpm -r build`, and `pnpm -r test` were not run.
- **The suite gate ran with the recording identity scrubbed from the child.** `AIDW_STAGE`/`AIDW_RUN_ID` were removed for the pytest subprocess (while `aidw gate run` still recorded into run `20261103T040002Z-00-E3.2-implement` via explicit options), because the recorder's ambient identity leaks into `tests/test_verification.py`'s gate-run tests. The recorded child command is the plain `uv run --frozen pytest`, so a later stage can still ask for the same gate and tree.
- **The task-specific test counts are collection-only.** Per-file counts were extracted from `pytest --collect-only -q` rather than by re-running each module; every one of those tests is part of the single full-suite invocation above, which passed.
- **`config show`'s override provenance is not reachable from the command.** The task prompt pins this: `config show` takes no per-value override flag, so `override` is proven through `resolve_config`'s `overrides` argument and the `aidw prompt --max-revisions` consumer, while `config show` displays `default`/`config`/`unset`.

---

## Non-Goals (NOT implemented)

- ❌ E3.3 version/compat refusal (`schema_version` newer than understood, `requires_toolkit` unsatisfied) — the resolver does not compare or refuse these fields.
- ❌ E3.4 Mythical-Forge default *values* under `paths:` and `repo:` — this task provides empty default slots and `unset` provenance only.
- ❌ E3.5 `aidw doctor` config validation and exit-code wiring — `aidw/doctor.py` was not touched; `config show`'s own failure contract is Requirement 6's, not E3.5's.
- ❌ E3.6 `docs/target-repo-config.md` — operator documentation was not written.
- ❌ E3.7 read-path existence validation — no `Path.exists()` check on `paths:` fields.
- ❌ E4.1/E4.5 stage registry and id vocabulary; E4.6 stage `model`/`thinking`/`timeout_seconds` overrides — the resolver only merges what E3.1's schema already declares.
- ❌ E6 `github.markers`/`labels` default values — only declared values resolve to `config`; no defaults were seeded.
- ❌ No commit, push, or PR was made by this stage.
