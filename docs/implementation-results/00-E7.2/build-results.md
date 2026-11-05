# Build Results — 00-E7.2: Neutralise bucket (ii)

**Branch:** `00-E7.2`
**Date:** 2026-11-05
**Spec:** `docs/migration/EXTRACTION.md` §4.2 (prompts — three buckets; the bucket-(ii) table), §3.4 (target-repo config: configured read-paths / write-targets, R10/D16, R18, `paths.*` leaves), §3.2 (workspace and worktree model), §5.4 (freeze scope), §3.12 (repo layout authority)

## Summary

**Purpose:** Remove the last repo-specific commands, paths and product tokens from the five "mixed" prompts that Pi still ships to any target repo, replacing them with references to the target repo's own conventions and to the configured `paths.*` / `github.markers.*` keys.

| Decision | Why it matters |
|----------|---------------|
| The contract asserts the **rendered** prompt, not the template text | §5.4 excludes bucket (ii) from byte-frozen coverage because E7.2 edits it, and two later changes land around the template without touching it: a repo override (§3.6 precedence 2) and E7.3's conventions injection. A template grep would prove the wrong text; rendering at each prompt's own `$1` arity is exactly what Pi receives. |
| The forbidden vocabulary distinguishes **config keys from product paths** and matches whole words | The prompts must now name `implementation_results_dir` while never naming `docs/implementation-results`; a blanket `results`/`implementation` match would fail the required reference. Likewise bare `infra` is forbidden but the legitimate word `infrastructure` in `fix-next-review-followup.md` is not. |
| The neutral-config fixture overrides **every** `paths.*` leaf the prompts name, with values differing from the §3.4/D17 defaults | A partial override leaves keys falling back to the Mythical Forge layout, making the "also resolves under a neutral config" claim vacuous. The D5-frozen `github.markers.parent` deliberately resolves through the default in both fixtures. |
| The parent-marker literal became a reference to `github.markers.parent`; the value itself is untouched | The marker is D5-frozen and lives in config (E6.1). Retyping it in the aggregate helper would orphan live GitHub issues and break `tests/test_baseline_verbatim_golden.py`; the prompt now tells the runner to substitute the PR URL into the resolved template. |
| E7.1's unmarked-prompt byte-equality oracle was **rescoped to bucket (i)** | §5.4 excludes bucket (ii) from byte-frozen coverage precisely because this task edits those five files; the old oracle could only hold until the neutralisation landed. Their contract is now `tests/test_prompt_neutrality.py`. |
| No package-manager name survives anywhere, including `pnpm -s` and `pr.md`'s stack table | §3.4/R17: gate commands are "the repo's own, taken by name from `aidw/conventions.md` / its root `AGENTS.md` / the task prompt — never inline". The stack table keyed off `pnpm-workspace.yaml`/`pyproject.toml`/`uv.lock` was itself a set of forbidden tokens. |

**Where it fits in the roadmap:** E7.2 is the neutralisation task of epic **E7 — Split the prompt library**. It depends on **E7.1** (the §4.2 bucketing and classification table) and on the **E6** contract freeze that made the markers and gate vocabulary stable. **E7.3** (conventions injection, D16) then supplies the conventions text these prompts now reference by name, **E7.4** neutralises agent guidance (§4.3), **E7.5** splits the inventory, and **MF.2** re-supplies the five prompts' product text as `aidw/prompts/` overrides at cutover.

**Scope:** Prompt text plus one contract test. Five prompt files were edited to drop package-manager names, product paths, product docs/verifiers and stack-specific scope examples; the E7.1 classification test's byte-frozen oracle was narrowed to bucket (i); the extraction roadmap ticked E7.2 with its review notes. It deliberately stops short of implementing conventions injection (E7.3), editing agent guidance (E7.4), splitting the inventory (E7.5), creating Mythical Forge's prompt overrides (MF.2), or touching any `aidw/*.py` code, the E7.1 classification table/markers, and the frozen marker values.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `tests/test_prompt_neutrality.py` | Created | Rendered-prompt neutrality contract for the five bucket-(ii) prompts: forbidden-token vocabulary, key-vs-path and whole-word matchers, neutral + Mythical-Forge-shaped config legs, and preserved-behaviour guards. |
| `docs/implementation-results/00-E7.2/build-results.md` | Created | This document (written by the record stage after gating). |
| `docs/task-prompts/00-E7.2-prompt.md` | Created | Task brief for this task (committed on the branch by the task-prompt stage). |
| `prompts/test.md` | Modified | Traceability/integration/results references and package-scoped commands neutralised; scope example derived from the four configured write-targets. |
| `prompts/pr.md` | Modified | Package-manager stack table replaced by "take the commands from the repo, never this prompt"; scope and task-id examples made neutral; `--ignore` examples derive from the configured keys. |
| `prompts/fix-next-review-followup.md` | Modified | `pnpm -s` caveat and `pnpm --filter` commands neutralised; parent-marker literal (body §2 and Appendix) replaced by `github.markers.parent`; AWS caveat generalised to "unavailable credentials or external dependencies". |
| `prompts/record-implementation-results.md` | Modified | `pnpm` gate matrix replaced by repo-supplied commands; results/template/task-prompt paths become `paths.*` keys; missing-template stop-and-report, `mktemp`/fixtures guidance and run-once rule preserved. |
| `prompts/impliment-task.md` | Modified | SRD/vector/property-test wording neutralised; `pnpm` smoke commands become repo-supplied placeholders; write-target paths become `paths.*` keys; AIDT-owns-branch-setup section untouched. |
| `tests/test_prompt_classification.py` | Modified | Byte-frozen parent-revision oracle narrowed from all unmarked prompts to bucket (i), with the §5.4 rationale; marker-free rule kept for both buckets. |
| `docs/tasks/00 - Extraction.md` | Modified | Traceability stage: ticks **E7.2** complete and records the delivered artifacts, the rescoped oracle, and the MF.2 re-supply note. |

---

## Verification Results

Every row below was produced once, in this recording, against the working tree containing the seven modified files and two new files above. `aidw gate run` reported tree id **`63cc1e124e3d`** for every gate, all under stage `record-implementation-results`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.69ms` (lockfile in sync, no resolution) |
| Build | `uv run --frozen aidw gate run build $SCOPE -- uv build --out-dir $(mktemp -d)` | ✅ `Successfully built aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` — gate `build`, tree `63cc1e124e3d`, stage `record-implementation-results`, 2026-11-05T08:14:03Z |
| Test / suite | `uv run --frozen aidw gate run suite $SCOPE -- uv run --frozen pytest` | ✅ `1630 passed in 29.25s` — gate `suite`, tree `63cc1e124e3d`, stage `record-implementation-results`, 2026-11-05T08:13:59Z |
| Doctor | `uv run --frozen aidw gate run doctor $SCOPE -- uv run --frozen aidw doctor` | ✅ `19 checks: 0 failed, 2 warning(s)` — the two warnings are the expected `dirty working tree` and `missing .mcp.json`; gate `doctor`, tree `63cc1e124e3d`, 2026-11-05T08:14:05Z |
| Agents validate | `uv run --frozen aidw gate run agents-validate $SCOPE -- uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` — gate `agents-validate`, tree `63cc1e124e3d`, 2026-11-05T08:14:05Z |
| Prompts check | `uv run --frozen aidw gate run prompts-check $SCOPE -- uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` — gate `prompts-check`, tree `63cc1e124e3d`, 2026-11-05T08:14:05Z |
| Lint | — | ❌ **unverified** — no linter, formatter or type-checker is configured in this repo (`AGENTS.md` §Gates / `design.md` §15), so there is no lint gate to run |
| Whitespace | `git diff --check` | ✅ clean (no output, exit 0) |

`$SCOPE` = `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` (the write-targets of the other stages of this workflow; nothing a gate reads is excluded — `prompts/` and `tests/` are inside the gated tree).

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1630 | ✅ Pass (`1630 passed in 29.25s`, gate `suite`, tree `63cc1e124e3d`, 2026-11-05T08:13:59Z) |
| `tests/test_prompt_neutrality.py` | 50 | ✅ Pass (collected via `pytest --collect-only -q`; executed inside the task gate below, not a second full-suite run) |
| `tests/test_prompts.py` | 9 | ✅ Pass (collected via `pytest --collect-only -q`; executed inside the task gate below) |
| `tests/test_prompt_classification.py` | 123 | ✅ Pass (collected via `pytest --collect-only -q`; executed inside the task gate below) |
| `tests/test_baseline_verbatim_golden.py` | 8 | ✅ Pass (collected via `pytest --collect-only -q`; executed inside the task gate below) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run --frozen aidw gate run prompt-neutrality $SCOPE -- uv run --frozen pytest tests/test_prompt_neutrality.py tests/test_prompts.py tests/test_prompt_classification.py tests/test_baseline_verbatim_golden.py` (the task prompt's Done-when command) | ✅ `190 passed in 5.77s` — gate `prompt-neutrality`, tree `63cc1e124e3d`, 2026-11-05T08:14:13Z |
| Each rendered prompt contains no package-manager token and no product path/doc token, under both a Mythical-Forge-shaped and a neutral config | ✅ pass (`test_no_rendered_prompt_names_a_package_manager_product_path_or_product_doc`) |
| Each prompt still declares exactly the `$1` arity its stage passes | ✅ pass (`test_each_prompt_declares_exactly_the_arity_its_stage_passes`) |
| The matcher separates config keys from product path literals and matches bare scope tokens as whole words only | ✅ pass (`test_the_matcher_separates_config_keys_from_product_paths`, `test_the_matcher_matches_bare_scope_tokens_as_whole_words_only`) |
| Every named `paths.*` key resolves under both configs, and the neutral fixture overrides each with a distinct, literal-free value | ✅ pass (`test_each_prompt_names_the_config_keys_instead_of_a_literal`, `test_no_named_path_resolves_to_text_the_rendered_prompt_contains`, `test_the_neutral_config_overrides_every_named_path_key_with_a_distinct_value`) |
| `github.markers.parent` resolves through the frozen default in both configs | ✅ pass (`test_the_frozen_parent_marker_resolves_through_the_default_in_both_configs`) |
| Prompts point at the repo's conventions source and carry the neutral replacements requirements 4–5 fix | ✅ pass (`test_each_prompt_points_at_the_repos_conventions_source`, `test_the_record_prompt_states_the_neutral_replacements_requirements_4_and_5_fix`) |
| Record prompt keeps missing-template stop-and-report, `mktemp`/fixtures guidance and the run-once rule; implement prompt keeps AIDT-owns-branch-setup; the `aidw gate run` idiom and toolkit stage cross-references remain | ✅ pass (`test_the_record_prompt_keeps_its_preserved_behaviours`, `test_the_implement_prompt_keeps_aidt_owned_branch_setup`, `test_each_prompt_keeps_the_gate_recording_idiom`, `test_toolkit_stage_cross_references_are_preserved`) |
| No prompt instructs a recipe the non-interactive runner blocks | ✅ pass (`test_no_prompt_instructs_a_command_the_noninteractive_runner_blocks`, `test_the_recipe_guard_rejects_an_instructed_recipe`) |
| Bucket (i) prompts remain byte-identical to the parent revision; bucket (ii) carries no destination marker | ✅ pass (`tests/test_prompt_classification.py`, executed in the gate above) |
| `prompts check` clean after the five edits | ✅ `prompts check: 0 error(s), 0 warning(s)` (gate above) |

---

## Deviations observed during recording

- **Gate stack.** The stage prompt's `pnpm install` / `pnpm -r lint|build|test` rows are another repo's stack; this repo is Python/uv and `AGENTS.md` names `uv sync --frozen`, `uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents validate --strict`, `uv run aidw prompts check`. Those were run, plus `uv build` to fill the template's Build row. No `pnpm` command was executed.
- **Lint row.** No lint command exists in this repo, so the template's lint analogue is recorded as **unverified** rather than as a passing run.
- **Task gate key.** The task prompt's Done-when names the four-file pytest command; it was recorded under the key `prompt-neutrality` because it is task-specific rather than the repo's `suite` gate.
- **Test counts.** Per-file counts come from `pytest --collect-only -q` against the same tree; they were not obtained by re-running the suites. `tests/test_prompt_classification.py` collects 123 tests from parametrisation over the prompt inventory, and is part of both the 1630-test full suite and the 190-test task gate.

---

## Non-Goals (NOT implemented)

- ❌ E7.3 conventions injection (D16): the render-time mechanism was not implemented; the five prompts only reference the conventions source by name (task prompt, "Explicit non-goals").
- ❌ E7.4 agent-guidance neutralisation and E7.5 inventory split — separate tasks (task prompt, "Explicit non-goals").
- ❌ MF.2 (§7): no Mythical Forge `aidw/prompts/` overrides were created; that happens at cutover (task prompt, "Explicit non-goals").
- ❌ No bucket-(i) or bucket-(iii) file, E7.1 classification table/marker, `aidw/*.py` code, or D5-frozen marker/label/comment body was changed (task prompt, "Explicit non-goals").
- ❌ No product traceability artifacts (`catalog.json`, `vectors.ts`, `report.md`, roadmap matrix) were added or changed — this repo has none of them and E7.2 adds no implemented product claim (roadmap E7.2 notes).
- ❌ No commit, push or PR opened by this stage (`prompts/pr.md` owns delivery).
