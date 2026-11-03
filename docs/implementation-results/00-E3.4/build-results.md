# Build Results — 00-E3.4: Defaults equal the Mythical Forge layout (D17)

**Branch:** `00-E3.4`
**Date:** 2026-11-03
**Spec:** `docs/migration/EXTRACTION.md` §3.4 (the normative `repo:` / `paths:` YAML block), §2 locked decisions D17 and R7 (defaults equal Mythical Forge's current layout), and §3.12 (no new top-level folders); `design.md` §3 (repository layout) and §12 (revision budget)

## Summary

**Purpose:** Seed the toolkit's config defaults with Mythical Forge's current `repo:` and `paths:` values so a Mythical-Forge-shaped target repo can use an almost empty `aidw/config.yaml` — in practice just `schema_version: 1` — and still resolve the complete layout.

| Decision | Why it matters |
|----------|---------------|
| The eight default strings are copied verbatim from `EXTRACTION.md` §3.4 (D17/R7) | These are deliberately not neutral placeholders: they are Mythical Forge's real layout, so the defaults themselves are the documented example and the near-empty config is the normal case. |
| `ConfigDefaults` owns the config defaults while `aidw.paths.TargetRepo` keeps its existing frozen literals | `target_config` must not import `aidw.paths` (layering), and rewiring `TargetRepo` to the resolved config is E4/E5's job. The duplicate `base_branch` / `branch_pattern` values are pinned equal by a test so they cannot drift. |
| Only `max_revisions` and the eight §3.4 leaves are seeded | `schema_version`, `requires_toolkit`, `github.markers` / `github.labels`, and `workflows` remain unset; E3.1/E3.3, E6, and E4.1 own those values. |
| `roadmap_glob` is exactly `[0-9]* - *.md` (space-dash-space) | The real roadmap filenames are `00 - Extraction.md`, `03.1 - Target-repo config.md`, etc. A glob such as `[0-9]*-*.md` would silently match nothing when E5.2 starts consuming it. |
| Resolution remains per leaf: `override` > `config` > `default` > *unset* | Declaring `repo.base_branch: trunk` must not suppress the default for its sibling `repo.branch_pattern`; the resolved-config contract is unchanged apart from the newly seeded values. |

**Where it fits in the roadmap:** E3.4 in the extraction epic. It consumes E3.1's loader and E3.2's resolved-config structure and merge walk, and it is the value-seeding counterpart to E3.3's version refusal. E3.5 can now validate the resolved config in `aidw doctor`, E3.6 can document the near-empty target-repo config, and E5.2 can later make `roadmap.py` and `prompt.py` consume these resolvable `paths:` values. Rewiring `aidw.paths.TargetRepo` to the resolved config remains out of scope for E3.

**Scope:** Touches `aidw/target_config.py` (the seeded defaults and their documentation) plus the contract tests in `tests/test_target_config.py` and the `config show` assertions in `tests/test_cli.py`, and marks the task complete in the extraction roadmap. It deliberately stops short of doctor validation, operator documentation, path-existence checks, `github` / `workflows` defaults, and making the roadmap/parser/prompt consume the path values.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E3.4-prompt.md` | Created | Task prompt recording the requirements, traps, non-goals, and deliverables for E3.4. |
| `aidw/target_config.py` | Modified | Seeds `TOOLKIT_DEFAULTS.repo` / `.paths` with the eight §3.4 Mythical Forge values, leaves `max_revisions` as the other seeded default, and rewrites the `ConfigDefaults`, `TargetConfig`, and `ResolvedValue` docstrings to name E3.4 as the owner and require `TargetRepo` equality. |
| `tests/test_target_config.py` | Modified | Replaces the E3.2 "unseeded" pins with per-default assertions for all eight values, a `schema_version: 1`-only resolution vector, declared-over-default precedence, roadmap-glob exactness, `TargetRepo` equality, and purity/non-mutation tests. |
| `tests/test_cli.py` | Modified | Updates `config show` (human and JSON) so the eight `repo.*` / `paths.*` leaves report `default` with their Mythical Forge values, while `requires_toolkit` and `github.markers.*` remain `unset`. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E3.4 complete on the extraction roadmap. |

---

## Verification Results

All gates were run through `aidw gate run <key> $SCOPE --stage record-implementation-results --run 20261103T060416Z-00-E3.4-implement -- <command>`, with `SCOPE="--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts"` — the document this stage writes plus the write-targets of the other stages. Every outcome below is a real observation against tree `54466d57c44e`; none was reused from an earlier run or copied from another document. `AIDW_STAGE` / `AIDW_RUN_ID` were removed from the child environment for the pytest and doctor-style commands so the recorder's ambient identity did not leak into the suite, matching CI.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `aidw gate run install $SCOPE -- uv sync --frozen` | ✅ `Checked 15 packages in 0.38ms` — frozen lock consistent (gate `install`, tree `54466d57c44e`, stage `record-implementation-results`, 2026-11-03T06:12:31Z) |
| Build | `aidw gate run build $SCOPE -- uv build --out-dir <tmp>` | ✅ Built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` (gate `build`, tree `54466d57c44e`, stage `record-implementation-results`, 2026-11-03T06:12:32Z) |
| Test | `aidw gate run suite $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ✅ `971 passed in 21.96s` (gate `suite`, tree `54466d57c44e`, stage `record-implementation-results`, 2026-11-03T06:12:57Z) |
| Doctor | `aidw gate run doctor $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw doctor` | ✅ exit 0 — 18 checks: 0 failed, 2 warnings (dirty working tree; missing `.mcp.json`) (gate `doctor`, tree `54466d57c44e`, stage `record-implementation-results`, 2026-11-03T06:13:01Z) |
| Agents validate | `aidw gate run agents-validate $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw agents validate --strict` | ✅ exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `54466d57c44e`, stage `record-implementation-results`, 2026-11-03T06:13:02Z) |
| Prompts check | `aidw gate run prompts-check $SCOPE -- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen aidw prompts check` | ✅ exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `54466d57c44e`, stage `record-implementation-results`, 2026-11-03T06:13:02Z) |
| Whitespace | `git diff --check` | ✅ exit 0, no whitespace errors |
| Lint | — | **unverified** — the repository configures no linter or formatter (`AGENTS.md` "Gates": pytest is the only verification; none was added in this task) |

### `uv run --frozen pytest` (full suite)

Counts are from the single full-suite gate invocation above. Per-file counts are collection-only (`pytest --collect-only -q`, which executes no test) and show the task-specific slice the full suite already covered; no test was re-run for a row. The suite reported no skips or xfails.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 971 | ✅ Pass (`971 passed in 21.96s`) |
| `tests/test_target_config.py` | 113 | ✅ Pass (all part of the full-suite run) |
| `tests/test_cli.py` | 46 | ✅ Pass (all part of the full-suite run) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| All eight §3.4 defaults asserted by name with the Mythical Forge values | ✅ `test_every_seeded_default_is_the_section_3_4_mythical_forge_value` passed |
| Only `max_revisions` and the eight values are seeded; version, markers, labels, and workflows stay unset | ✅ `test_seeded_defaults_are_the_budget_and_the_mythical_forge_layout_only` passed |
| `roadmap_glob` is exactly `[0-9]* - *.md` and matches the real roadmap filenames | ✅ `test_default_roadmap_glob_matches_the_real_roadmap_filenames` passed |
| `TOOLKIT_DEFAULTS` equals a freshly built defaults structure and is not mutated | ✅ `test_toolkit_defaults_equal_a_freshly_built_defaults_structure`, `test_defaults_resolution_is_pure_and_does_not_touch_toolkit_defaults` passed |
| The two `repo:` defaults stay equal to `aidw.paths.TargetRepo` without importing `aidw.paths` | ✅ `test_the_two_repo_defaults_match_the_target_repo_dataclass` passed |
| `schema_version: 1` alone resolves every `repo.*` / `paths.*` leaf as `source == "default"` with the §3.4 value | ✅ `test_schema_version_only_config_resolves_the_mythical_forge_layout`, `test_schema_version_only_config_file_through_the_loader_resolves_the_layout` passed |
| `repo.base_branch: trunk` wins as `config` while `repo.branch_pattern` still resolves the default | ✅ `test_declared_base_branch_beats_the_default_but_not_its_sibling` passed |
| A declared value equal to a default is still `config`, not `default` | ✅ `test_declared_value_equal_to_a_default_is_still_config` passed |
| A partial config leaves only `requires_toolkit` and the `github.markers.*` leaves unset | ✅ `test_partial_config_resolves_defaults_and_leaves_only_unseeded_leaves_unset` passed |
| `config show` human and JSON report the eight leaves as `default` in a no-config repo | ✅ `test_config_show_human_single_checkout`, `test_config_show_json_single_checkout` passed |
| `config show` reports a declared override and sibling default, with the still-unset leaves unchanged | ✅ `test_config_show_dumps_a_declared_config_by_dotted_path`, `test_config_show_human_renders_declared_and_unset_leaves` passed |

---

## Deviations observed during recording

- **The task prompt's generic pnpm commands do not apply to this repository.** This is the `aidt` toolkit (Python/uv), so the `AGENTS.md` / `prompts/pr.md` gate set was run instead. `pnpm install`, `pnpm -r lint`, `pnpm -r build`, and `pnpm -r test` were not run.
- **The targeted module gates were not re-run.** The task prompt's "Done when" names `pytest tests/test_target_config.py` and `pytest tests/test_cli.py`; both are fully included in the single full-suite gate above, which passed. Per-file counts are collection-only to avoid buying the same tests twice, matching the E3.3 record.
- **`uv build` does not write into the tree.** It built into a `mktemp -d` directory, so the gated tree stayed identical to the delivered change set.

---

## Non-Goals (NOT implemented)

- ❌ E3.5 `aidw doctor` config validation and exit-code wiring — `aidw/doctor.py` was not modified.
- ❌ E3.6 `docs/target-repo-config.md` operator documentation — not written here.
- ❌ E3.7 read-path existence validation / write-target creation — no `Path.exists()` on `paths:` fields was added.
- ❌ E6 `github.markers` / `github.labels` default values — left unset.
- ❌ E4.1 `workflows` stage-list defaults — the defaults map remains empty.
- ❌ E5.2 generalising `roadmap.py` to consume `paths.roadmap_dir` / `roadmap_glob`, or the equivalent `prompt.py` `task_prompts_dir` wiring — the values are resolvable but not yet consumed.
- ❌ Rewiring `aidw.paths.TargetRepo` to read base branch / branch pattern from the resolved config — out of E3's scope; its literals are only kept equal by a test.
- ❌ No commit, push, or PR was made by this stage.
