# Build Results — 00-E7.1: Classify and relocate

**Branch:** `00-E7.1`
**Date:** 2026-11-05
**Spec:** `docs/migration/EXTRACTION.md` §4.2 (prompts — three buckets, 31 files), §7 (Mythical Forge adoption and cutover, MF.2), §3.12 (repo layout authority)

## Summary

**Purpose:** Apply §4.2's three buckets to the toolkit's 31 top-level prompt files, recording each file's bucket, action and destination without moving or rewording any prompt before MF.2.

| Decision | Why it matters |
|----------|---------------|
| The destination marker is a `destination:` **frontmatter** field, never a body note | `aidw/prompts.py:strip_frontmatter` removes the leading block before rendering, so every bucket (iii) prompt sent to Pi is byte-identical to its parent revision. A body note would render into the agent message and change behaviour. |
| Classification comes from §4.2's **named lists**, not a product-token grep | §4.2 deliberately keeps `git-update.md` and `review-findings-to-github.md` in (i) despite frozen marker strings, and `task-prompt.md` in (iii) even though it names `aidt/prompts`; a grep would misroute all three. |
| The three files with no frontmatter (`task-prompt.md`, `integration-tests.md`, `manual-test-plan.md`) gain a minimal `---` block carrying only the destination field | Requirement 2 allows nothing else added to those files; a note appended after the `# ` heading would render, and extra fields would not be the specified minimal block. |
| The table↔directory check is **bidirectional**, and bucket (i)/(ii) bodies are compared against the parent revision via `git archive` | A one-way "every row exists on disk" check silently passes when a future prompt is added without a row; the parent-revision oracle catches an accidental body edit even when the marker is absent. |
| `prompts/scripts/*.py` is excluded from the inventory | Those are the toolkit-owned `REQUIRED_SCRIPTS` helpers, not prompts; including `inventory.list_files` output wholesale would fail the 31-file completeness assertion immediately. |
| The marker value is `mythical-forge/aidw/prompts/`, never anything containing `.pi/prompts` | The foreign-prefix sentinel in `aidw/inventory.py` would turn `aidw prompts check` and `tests/test_inventory.py` red; the new repo's own folder is not the old mirror. |
| Bucket (i)/(ii) files carry no marker and no body edit | Their destinations live in the table only; bucket (ii) neutralisation belongs to E7.2, and `pr.md` is already partly edited ahead of E7.2 and was left exactly as found. |

**Where it fits in the roadmap:** E7.1 is the classification task of epic **E7 — Split the prompt library**. It completes the prompt half of the extraction inventory that follows E6's contract freeze and precedes **E7.2** (neutralise bucket ii), **E7.3** (conventions injection), **E7.4** (agent-guidance neutralisation, §4.3), **E7.5** (inventory split), and **MF.2** (the actual move of bucket iii into Mythical Forge's `aidw/prompts/`).

**Scope:** Metadata-only. A classification table for all 31 prompts (`docs/migration/prompt-classification.md`), a destination field added to the 20 bucket (iii) prompts' frontmatter, an executable contract test (`tests/test_prompt_classification.py`), and the routine traceability tick of E7.1 in the extraction roadmap. It deliberately stops short of: editing any bucket (i)/(ii) prompt body, neutralising bucket (ii) (E7.2), conventions injection or agent/document classification (E7.3/E7.4), splitting the inventory (E7.5), and moving, renaming or deleting any prompt file (MF.2).

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/migration/prompt-classification.md` | Created | The §4.2 classification table: 31 rows with bucket, action and destination, plus the marker contract and the table's explicit non-ownership boundaries. |
| `tests/test_prompt_classification.py` | Created | Executable half of the classification: bidirectional table↔directory completeness, §4.2 named-list membership, action/destination rules, frontmatter-only marker, rendered-prompt and parent-revision equality, and unmarked bucket (i)/(ii) guards. |
| `docs/task-prompts/00-E7.1-prompt.md` | Created | Task brief for this task (committed on the branch by the task-prompt stage). |
| `docs/implementation-results/00-E7.1/build-results.md` | Created | This document (written by the record stage after gating). |
| `prompts/doc-lambdas.md` | Modified | Adds `destination: mythical-forge/aidw/prompts/` to existing frontmatter; no body change. |
| `prompts/implement-srd-followup.md` | Modified | Adds the destination field to existing frontmatter; no body change. |
| `prompts/integration-tests.md` | Modified | Adds a minimal frontmatter block carrying only the destination field; no body change. |
| `prompts/manual-test-plan.md` | Modified | Adds a minimal frontmatter block carrying only the destination field; no body change. |
| `prompts/show-updated-integration-tests.md` | Modified | Adds the destination field to existing frontmatter; no body change. |
| `prompts/show-updated-player-actions.md` | Modified | Adds the destination field to existing frontmatter; no body change. |
| `prompts/task-prompt.md` | Modified | Adds a minimal frontmatter block carrying only the destination field; no body change. |
| `prompts/update-architecture.md` | Modified | Adds the destination field to existing frontmatter; no body change. |
| `prompts/update-authentication-sequence-diagram.md` | Modified | Adds the destination field to existing frontmatter; no body change. |
| `prompts/update-infrastructure-diagram.md` | Modified | Adds the destination field to existing frontmatter; no body change. |
| `prompts/update-lambda-dataflow-diagram.md` | Modified | Adds the destination field to existing frontmatter; no body change. |
| `prompts/update-player-ws-message-flow-diagram.md` | Modified | Adds the destination field to existing frontmatter; no body change. |
| `prompts/update-rules-engine-diagram-combat.md` | Modified | Adds the destination field to existing frontmatter; no body change. |
| `prompts/update-rules-engine-diagram-movement.md` | Modified | Adds the destination field to existing frontmatter; no body change. |
| `prompts/update-rules-engine-diagram-progression.md` | Modified | Adds the destination field to existing frontmatter; no body change. |
| `prompts/update-rules-engine-diagram-skills.md` | Modified | Adds the destination field to existing frontmatter; no body change. |
| `prompts/update-rules-engine-diagram-spells.md` | Modified | Adds the destination field to existing frontmatter; no body change. |
| `prompts/update-rules-engine-diagram-vision-world.md` | Modified | Adds the destination field to existing frontmatter; no body change. |
| `prompts/update-rules-engine-diagram.md` | Modified | Adds the destination field to existing frontmatter; no body change. |
| `prompts/update-traceability.md` | Modified | Adds the destination field to existing frontmatter; no body change. |
| `docs/tasks/00 - Extraction.md` | Modified | Traceability stage: ticks **E7.1** complete in the 00-Extraction roadmap. |

---

## Verification Results

Every row below was run once, in this recording, against the working tree containing the 21 modified files and two uncommitted new files above. `aidw gate run` reported tree id **`da1a188ebbfc`** for every gate.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.78ms` (lockfile in sync, no resolution) |
| Build | `uv run --frozen aidw gate run build $SCOPE -- uv build --out-dir $(mktemp -d)` | ✅ `Successfully built aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` — gate `build`, tree `da1a188ebbfc`, stage `record-implementation-results`, 2026-11-05T07:15:36Z |
| Test / suite | `uv run --frozen aidw gate run suite $SCOPE -- uv run --frozen pytest` | ✅ `1565 passed in 27.59s` — gate `suite`, tree `da1a188ebbfc`, stage `record-implementation-results`, 2026-11-05T07:15:29Z |
| Doctor | `uv run --frozen aidw gate run doctor $SCOPE -- uv run --frozen aidw doctor` | ✅ `19 checks: 0 failed, 2 warning(s)` — the two warnings are the expected `dirty working tree` and `missing .mcp.json`; gate `doctor`, tree `da1a188ebbfc`, 2026-11-05T07:15:32Z |
| Agents validate | `uv run --frozen aidw gate run agents-validate $SCOPE -- uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` — gate `agents-validate`, tree `da1a188ebbfc`, 2026-11-05T07:15:32Z |
| Prompts check | `uv run --frozen aidw gate run prompts-check $SCOPE -- uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` — gate `prompts-check`, tree `da1a188ebbfc`, 2026-11-05T07:15:33Z |
| Lint | — | ❌ **unverified** — no linter, formatter or type-checker is configured in this repo (`AGENTS.md` §Gates / `design.md` §15), so there is no lint gate to run |
| Whitespace | `git diff --check` | ✅ clean (no output, exit 0) |

`$SCOPE` = `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` (the write-targets of the other stages of this workflow; nothing a gate reads is excluded — `docs/migration/prompt-classification.md`, `prompts/` and `tests/` are all inside the gated tree).

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1565 | ✅ Pass (`1565 passed in 27.59s`, gate `suite`, tree `da1a188ebbfc`, 2026-11-05T07:15:29Z) |
| `tests/test_prompt_classification.py` | 108 | ✅ Pass (collected via `pytest --collect-only -q`; executed inside the task gate below, not a second full-suite run) |
| `tests/test_prompts.py` | 9 | ✅ Pass (collected via `pytest --collect-only -q`; executed inside the task gate below) |
| `tests/test_inventory.py` | 9 | ✅ Pass (collected via `pytest --collect-only -q`; executed inside the task gate below) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run --frozen aidw gate run prompt-classification $SCOPE -- uv run --frozen pytest tests/test_prompt_classification.py tests/test_prompts.py tests/test_inventory.py` (the task prompt's Done-when command) | ✅ `126 passed in 0.78s` — gate `prompt-classification`, tree `da1a188ebbfc`, 2026-11-05T07:15:39Z |
| Table↔directory completeness is bidirectional (no unclassified file, no stale row) | ✅ pass (`test_table_classifies_exactly_the_prompt_files_that_exist`) |
| Bucket membership equals §4.2's named lists — 6 (i), 5 (ii), 20 (iii), 31 total | ✅ pass (`test_the_classification_covers_the_specs_31_files`, `test_table_bucket_membership_is_the_section_4_2_assignment`, `test_bucket_membership_matches_the_spec_s_named_lists`) |
| Each row states its bucket's action and destination | ✅ pass (`test_each_row_states_its_bucket_s_action_and_destination`) |
| All 20 bucket (iii) files carry exactly one `destination: mythical-forge/aidw/prompts/` in frontmatter | ✅ pass (`test_product_prompts_declare_their_destination_in_frontmatter`) |
| Marker is inert — `strip_frontmatter` removes it and `load_prompt_file` equals the parent revision | ✅ pass (`test_the_marker_never_reaches_the_rendered_prompt`, `test_product_prompt_rendering_matches_the_parent_revision`) |
| The three no-frontmatter files gained only the minimal block | ✅ pass (`test_files_without_frontmatter_gained_only_the_minimal_block`) |
| Existing frontmatter was extended, not replaced | ✅ pass (`test_existing_frontmatter_was_extended_not_replaced`) |
| Bucket (i)/(ii) files carry no marker and are byte-identical to the parent revision | ✅ pass (`test_generic_and_mixed_prompts_carry_no_marker`, `test_unmarked_prompt_content_matches_the_parent_revision`) |
| No foreign prefix `.pi/prompts` introduced | ✅ `aidw prompts check: 0 error(s), 0 warning(s)` and `tests/test_inventory.py::test_real_inventory_is_complete` green in the gates above |
| `prompts/scripts/` excluded from the 31-file table | ✅ pass (`_prompt_files` takes top-level `prompts/*.md` only) |
| Rendered reader experience of the classification table in a Markdown viewer | ❌ **unverified** — a judgment on document presentation; no automated check asserts it |

---

## Deviations observed during recording

- **Gate stack.** The stage prompt's `pnpm install` / `pnpm -r lint|build|test` rows are another repo's stack; this repo is Python/uv and `AGENTS.md` names `uv sync --frozen`, `uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents validate --strict`, `uv run aidw prompts check`. Those were run, plus `uv build` to fill the template's Build row. No `pnpm` command was executed.
- **Task gate key.** The task prompt's Done-when names the three-file pytest command; it was recorded under the key `prompt-classification` because it is task-specific rather than the repo's `suite` gate.
- **Test count.** `tests/test_prompt_classification.py` collects 108 tests from 19 `def test_` functions because most are parametrised over the 20 product prompts and the 11 unmarked prompts; the file is part of the 1565-test full suite as well as the 126-test task gate.
- **Lint row.** No lint command exists in this repo, so the template's lint analogue is recorded as **unverified** rather than as a passing run.

---

## Non-Goals (NOT implemented)

- ❌ E7.2 neutralise bucket (ii): `test.md`, `pr.md`, `fix-next-review-followup.md`, `record-implementation-results.md` and `impliment-task.md` were not edited; `pr.md` was left exactly as found (task prompt, "Explicit non-goals").
- ❌ E7.3 conventions injection, E7.4 agent-guidance neutralisation (§4.3), E7.5 inventory split — all separate tasks (task prompt, "Explicit non-goals").
- ❌ MF.2 the actual move: no prompt file was moved, deleted or renamed; bucket (iii) is marked only (task prompt, "Explicit non-goals"; §7).
- ❌ §4.1 code classification and §4.3 agent/config/document classification — this task is §4.2 prompts only (task prompt, "Explicit non-goals").
- ❌ No checker, status vocabulary, catalog reference, or CI gate change — gate impact is none (task prompt, requirement 5).
- ❌ No commit, push or PR opened by this stage (`prompts/pr.md` owns delivery).
