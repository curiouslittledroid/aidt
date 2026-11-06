# Build Results — 00-E7.4: Neutralise the agent guidance

**Branch:** `00-E7.4`
**Date:** 2026-11-05
**Spec:** `docs/migration/EXTRACTION.md` §4.3 (agents, configs, docs: the four agent rows and their exact actions), §3.2 (workspace and worktree model: AIDT owns branch setup), §3.4 (target-repo config: `paths.*` keys, D16 conventions source, D17 defaults), §2 (locked decisions D13/D16), §6 (E7.4 task entry)

## Summary

**Purpose:** Make the four shipped agent context files state only duties that hold for every target repo, so the same guidance can be shipped to any repository without leaking Mythical Forge's product names, stack rules, document paths, or task ids.

| Decision | Why it matters |
|----------|---------------|
| Traceability and architecture leave the implementer's stage list entirely (D13) | They are repo-optional stages invoked as their own agents; keeping them as implementer steps would ship a workflow only one product performs. The file now names `/impliment-task` only. |
| The stack rules are *moved* to the repo's `AGENTS.md` / `aidw/conventions.md` (D16), not deleted | The implementer keeps the duty ("rules are code, package manager/workspace/placement conventions are the repo's") without naming pnpm, the workspace catalog, `Design 21`, `infra/`, or `AWS`. The pointer must survive the rule. |
| The recorder names the config **keys** (`paths.build_results_template`, `paths.implementation_results_dir`), never the path literals | `docs/implementation-results/TEMPLATE.md` and `docs/implementation-results/<branch>/build-results.md` are Mythical Forge defaults. Naming the keys matches the neutralised `prompts/record-implementation-results.md` vocabulary and works for any `paths.*` override. |
| `(03-E2.9)` in the pr-publisher becomes `<phase>-<task>`; the `main`-base / never-merge / `## Summary`/`## Changes`/`## Verification` conventions stay | Those conventions match `prompts/pr.md`, so they are generic; only the product task-id example was repo-specific. Repo-specific PR conventions are deferred to `AGENTS.md` / `aidw/conventions.md`. |
| The task-author states the §3.2 fact — AIDT owns branch setup — instead of telling the agent a prompt creates its branch | `aidw prompt` creates the branch and worktree before the stage runs. The instruction becomes "never write on the base branch; do not create, switch, or reset branches". |
| Every `aidt/prompts/*.md` stage reference is preserved in recorder, pr-publisher and task-author | Those are toolkit-internal stage references, not product tokens; the inventory-split task (E7.5) owns the path change. A blanket "no product path" matcher would have destroyed them. |
| The neutrality check greps the whole `agents/*/AGENTS.md` glob, with the four-category vocabulary mirrored from `tests/test_prompt_neutrality.py` | The other guidance files are already clean (§4.3 "Other 8" row) and must stay clean; two disjoint definitions of "product text" would drift apart. |

**Where it fits in the roadmap:** E7.4 is the agent-guidance task of epic **E7 — Split the prompt library**. It depends on **E7.2** (the four prompts stopped naming the stack, so the shipped guidance must stop too) and **E7.3** (the runtime conventions channel exists, so pointing at `AGENTS.md` / `aidw/conventions.md` is now actionable; D16). **E7.5** (inventory split) follows and owns the `aidt/prompts/*.md` path change plus the `.pi/prompts` sentinel; **MF.2** re-supplies the product text as target-repo `aidw/prompts/` overrides at cutover.

**Scope:** The four agent context files §4.3 singles out, one new contract-test module asserting over the whole `agents/*/AGENTS.md` glob, one rewritten L1.3 pin in `tests/test_prompt_workflow.py`, and the extraction-roadmap tick. It stops short of E7.5's inventory split and `aidt/prompts/*.md` path updates, the "Other 8" row's mechanical path updates, re-editing `prompts/*.md` or `aidw/prompts.py` (E7.2/E7.3 are landed), and MF.2's cutover move of `task-prompt.md`. It also makes no vector-matrix or coverage-catalog change: this repo has no `docs/rules-coverage/`, `tests/integration/`, or `srd:*` scripts, and E7.4 adds no Rules Engine action or product claim.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `tests/test_agent_guidance_neutrality.py` | Created | Greps every `agents/*/AGENTS.md` against the four-category vocabulary (package managers, product scopes, product paths, product docs), plus keys-vs-paths, stage-reference preservation, branch-recipe and numbered-`AGENTS.md`-section guards, and two seeded sweeps. |
| `docs/implementation-results/00-E7.4/build-results.md` | Created | This document (written by the record stage after gating). |
| `docs/task-prompts/00-E7.4-prompt.md` | Created | Task brief for this task (committed on the branch by the task-prompt stage). |
| `agents/implementer/AGENTS.md` | Modified | Drops `/update-traceability` and `/update-architecture` (D13) and the pinned stack rules; defers the repo's package manager, placement, dependency and property-test conventions to `AGENTS.md` / `aidw/conventions.md` (D16). Remaining duty: `/impliment-task`, code plus contract tests, leave uncommitted, no PR. |
| `agents/recorder/AGENTS.md` | Modified | Names `paths.build_results_template` and `paths.implementation_results_dir` instead of the path literals; adds the fail-closed "missing template → stop and report" instruction; "traceability artifacts" becomes "implementation artifacts". |
| `agents/pr-publisher/AGENTS.md` | Modified | `(03-E2.9)` → `<phase>-<task>`; adds the D16 pointer that repo-specific PR conventions come from `AGENTS.md` / `aidw/conventions.md`. |
| `agents/task-author/AGENTS.md` | Modified | Replaces "the branch the prompt creates" with the §3.2 fact that AIDT owns branch setup, and forbids writing on the base branch or creating/switching/resetting branches. |
| `tests/test_prompt_workflow.py` | Modified | The L1.3 author-prompt pin asserted the old "before creating or switching to the `{phase}-{task}` branch" wording; it now asserts `AIDT owns branch setup`, `never write on the base branch`, and the absence of "the prompt creates". |
| `docs/tasks/00 - Extraction.md` | Modified | Traceability stage: ticks **E7.4** complete and records the delivered artifacts, tests and flags. |

---

## Verification Results

Every row below was produced once, in this recording, against the working tree containing the files above. `aidw gate run` reported tree id **`56c60dab592e`** for every gate, all under stage `record-implementation-results`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.71ms` (lockfile in sync, no resolution) |
| Build | `uv run --frozen aidw gate run build $SCOPE -- uv build --out-dir $(mktemp -d)` | ✅ `Successfully built aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` — gate `build`, tree `56c60dab592e`, stage `record-implementation-results`, 2026-11-05T22:46:27Z |
| Test / suite | `uv run --frozen aidw gate run suite $SCOPE -- uv run --frozen pytest` | ✅ `1771 passed in 26.03s` — gate `suite`, tree `56c60dab592e`, stage `record-implementation-results`, 2026-11-05T22:46:55Z |
| Doctor | `uv run --frozen aidw gate run doctor $SCOPE -- uv run --frozen aidw doctor` | ✅ `19 checks: 0 failed, 2 warning(s)` — expected `dirty working tree` and `missing .mcp.json`; gate `doctor`, tree `56c60dab592e`, 2026-11-05T22:46:57Z |
| Agents validate | `uv run --frozen aidw gate run agents-validate $SCOPE -- uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` — gate `agents-validate`, tree `56c60dab592e`, 2026-11-05T22:46:58Z |
| Prompts check | `uv run --frozen aidw gate run prompts-check $SCOPE -- uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` — gate `prompts-check`, tree `56c60dab592e`, 2026-11-05T22:46:58Z |
| Lint | — | ❌ **unverified** — no linter, formatter or type-checker is configured in this repo (`AGENTS.md` §Gates / `design.md` §15), so there is no lint gate to run |
| Whitespace | `git diff --check` | ✅ clean (no output, exit 0) |

`$SCOPE` = `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` (the write-targets of the stages of this workflow; nothing a gate reads is excluded — `agents/`, `aidw/` and `tests/` are inside the gated tree). `aidw gate run` echoed `[scope excludes: docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks]` on every gate above, confirming the same scope was applied.

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1771 | ✅ Pass (`1771 passed in 26.03s`, gate `suite`, tree `56c60dab592e`, 2026-11-05T22:46:55Z) |
| `tests/test_agent_guidance_neutrality.py` | 72 | ✅ Pass (collected via `pytest --collect-only -q`; executed inside the task gate below, not a second full-suite run) |
| `tests/test_prompt_workflow.py` | 170 | ✅ Pass (collected via `pytest --collect-only -q`; executed inside the full suite above) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run --frozen aidw gate run agent-guidance-neutrality $SCOPE -- uv run --frozen pytest tests/test_agent_guidance_neutrality.py` (the task prompt's Done-when command) | ✅ `72 passed in 5.88s` — gate `agent-guidance-neutrality`, tree `56c60dab592e`, 2026-11-05T22:47:07Z |
| No file under `agents/*/AGENTS.md` names a product, a package manager, or a product doc (whole-word for bare tokens, literal for punctuated ones) | ✅ pass over the whole 11-file glob (`test_no_agents_guidance_names_a_product_package_manager_or_product_doc`, `test_property_every_guidance_file_is_clean_and_every_planted_token_is_detected`) |
| The vocabulary is complete and disjoint, so the sweep cannot go vacuously green | ✅ pass (`test_the_vocabulary_covers_every_category_without_overlap`, `test_property_every_vocabulary_token_matches_itself`, `test_the_property_seeds_are_the_whole_sample`) |
| The matcher separates the config keys from the product path literals | ✅ pass (`test_the_matcher_separates_config_keys_from_product_paths`) |
| The recorder names both `paths.*` keys and neither literal | ✅ pass (`test_the_recorder_names_the_two_config_keys_instead_of_the_literals`) |
| Toolkit stage references are preserved in recorder, pr-publisher and task-author | ✅ pass (`test_toolkit_stage_references_are_preserved` over `STAGE_REFERENCES`) |
| The implementer names `/impliment-task` and neither `/update-traceability` nor `/update-architecture` | ✅ pass (`test_the_implementer_names_no_traceability_or_architecture_stage`) |
| The pr-publisher has a generic `<phase>-<task>` example and keeps the generic body/never-merge conventions | ✅ pass (`test_the_pr_publisher_uses_a_generic_task_id_example`) |
| The task-author states AIDT owns branch setup and the agent never writes on the base branch; no file claims a prompt creates the branch | ✅ pass (`test_the_task_author_states_aidt_owns_branch_setup`, `test_no_agents_guidance_claims_a_prompt_creates_the_branch`, `test_the_branch_guard_rejects_an_instructed_recipe`) |
| Every `agents_md:` target still resolves to a shipped guidance file | ✅ pass (`test_every_agent_config_still_reaches_its_guidance_file`, cross-checked by the `agents-validate` gate above) |
| Reading the guidance is pure and repeatable | ✅ pass (`test_reading_the_guidance_is_pure_and_repeatable`) |

---

## Deviations observed during recording

- **The L1.3 pin in `tests/test_prompt_workflow.py` changed, which the task prompt did not name.** The prompt's Deliverables list only the four guidance files and the new test module, but `test_l13_rendered_author_prompt_and_agent_context_state_the_contract` asserted the old "before creating or switching to the `{phase}-{task}` branch" wording that Requirement 4 removes. The implementation rewrote that assertion to the new §3.2 contract (and to assert the old wording is absent); this is recorded in the roadmap entry as a flag rather than left as a silent test edit.
- **`agent-configs/implementer.yaml` still claims the implementer owns traceability and architecture documentation.** §4.3 declares the agent configs portable as-is, so the config description was not edited; the roadmap entry flags it for E7.5 or a follow-up. Nothing in this recording's gates depends on it.
- **No vector-matrix or coverage-catalog update was attempted.** The task prompt notes the deliverables (same as E7.2/E7.3): this repo has no `docs/rules-coverage/`, `tests/integration/`, or `srd:*` scripts and E7.4 adds no implemented product claim.

---

## Non-Goals (NOT implemented)

- ❌ E7.5 (Inventory split) — the `aidt/prompts/*.md` stage references and the `.pi/prompts` sentinel are E7.5's to change; they are preserved here (task prompt, explicit non-goals).
- ❌ The §4.3 "Other 8" row's mechanical `aidt/prompts/*.md` path updates for the remaining `agents/*/AGENTS.md` and `SYSTEM.md` files (task prompt, explicit non-goals).
- ❌ Re-editing `prompts/*.md` or `aidw/prompts.py` — E7.2 (bucket ii) and E7.3 (conventions injection) are already landed (task prompt, explicit non-goals).
- ❌ MF.2 (moving bucket-iii prompts to Mythical Forge's `aidw/prompts/` at cutover) and the `task-prompt.md` `destination:` marker (task prompt, explicit non-goals).
- ❌ No vector-matrix or coverage-catalog change — this repo has neither artifact (task prompt, requirement 7).
- ❌ No gate, checker, or status-vocabulary change (`uv run --frozen pytest` and `uv run aidw agents validate --strict` stay green) (task prompt, requirement 7).
- ❌ No commit, push, or PR opened by this stage — `aidt/prompts/pr.md` owns delivery (record-stage non-goals).
