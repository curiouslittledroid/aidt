# Build Results — E9.1: Rewrite `design.md`

**Branch:** `00-E9.1`
**Date:** 2026-11-06
**Spec:** `docs/migration/EXTRACTION.md` §2 (locked decisions D1–D24), §3.1 (two roots), §3.2 (workspace and worktree model), §3.4 (target-repo config), §3.5 (stage and workflow model), §3.9 (persisted GitHub contracts, D5), §3.10 (state, runs, locking, D18), §3.11 (version and compatibility, D10), §3.12 (new repo layout); `docs/tasks/00 - Extraction.md` — Epic E9.1

## Summary

**Purpose:** Rewrite `design.md` as the post-extraction design of record: the two-root model, worktree model, target config and stage contracts, frozen GitHub contracts, state locations, and distribution.

| Decision | Why it matters |
|----------|---------------|
| Reframed the header, §1 and §1.1 around toolkit root, target repo root, workspace root and state root, with `TargetRepo.resolve` (`cwd` → `--repo` → `$AIDW_REPO`) | The pre-extraction text described a toolkit subtree inside one product repo and contradicted the already-post-extraction worktree sections. |
| Replaced the §3 `aidt/` subtree with the extracted layout (`aidw/`, `prompts/`, `agent-configs/`, `agents/`, `docs/`, `tests/`, `fixtures/target-repo/`, `design.md`, `README.md`, `pyproject.toml`) and kept top-level `fixtures/target-repo/` as authoritative | EXTRACTION.md §3.12's tree, the on-disk layout and the interface tests agree on that path; the stale `tests/fixtures/target-repo/` prose is gone. |
| Documented `aidw/`'s dual role — Python package in the toolkit, configuration folder in a target repo (D7) | The same word otherwise reads as one concept and misleads implementers. |
| Replaced the `aidt/runs/` layout with `<state root>/<repo-slug>/runs/<run-id>/` plus `locks/`, and reconciled §9.2's example with the P1 identity fields | State must live outside every working tree, and a run must record the toolkit/config identity that produced it. |
| Documented config-driven stages and prompt precedence (D12/D13/D14), cross-linking `docs/target-repo-config.md` and the JSON Schema | Re-pasting the schema would drift from `aidw/target_config.py` and the parser. |
| Presented markers, labels and comment bodies as per-repo config defaults frozen at today's literals (D5), with exact-match semantics | Parent lookup is a strict string comparison; a "cleanup" would orphan live GitHub issues. |
| Added 12 contract tests to `tests/test_design_doc.py` pinning the rewrite's structure and cross-references | A doc-only rewrite otherwise has no executable proof and regresses silently. |

**Where it fits in the roadmap:** Epic E9 (post-extraction design and contract docs). It follows the extraction work of E1–E8 and is followed by E9.2 (contract docs — already present and only cross-linked here), E9.3 (move `EXTRACTION.md` to history), and E9.4 (README rewrite).

**Scope:** `design.md` across the header and §§1–3, 7, 9, 12, 15–19, plus the new contract tests. It deliberately stops short of editing the contract docs, moving `EXTRACTION.md`, rewriting `README.md`/`AGENTS.md`, changing code, tests outside the design contract, prompts, agent configs, schema, or `pyproject.toml`, and any Mythical Forge cutover work.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/implementation-results/00-E9.1/build-results.md` | Created | This results document, written by the record stage after gating. |
| `docs/task-prompts/00-E9.1-prompt.md` | Created | Task prompt for E9.1, committed on the branch as `278df00`. |
| `design.md` | Modified | Post-extraction rewrite: header/§1 two-root model, §2 concepts, §3 layout and path types, §7.2 frozen contracts, §9.1/§9.2 state, §12 config/stage/distribution, §§15–19 testing/build/risks/acceptance, §17 decision trail. |
| `tests/test_design_doc.py` | Modified | Adds 12 contract tests for the rewritten design's roots, layout, state/lock paths, frozen GitHub contract, cross-links, stage/prompt contracts, distribution, late sections, and §17 decision trail. |

---

## Verification Results

All gate outcomes below were produced by this recording run against tree `1d6b0fc0454d`, with the scope every stage of this workflow declares: `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.42ms`, exit 0). Gate `install`, tree `1d6b0fc0454d`, stage `record-implementation-results`, 2026-11-06T06:22:35Z |
| Build | `uv build --no-build-isolation --out-dir $(mktemp -d)` | ✅ Pass (`Successfully built …/aidt-0.1.0.tar.gz` and `…/aidt-0.1.0-py3-none-any.whl`). Gate `build`, tree `1d6b0fc0454d`, stage `record-implementation-results`, 2026-11-06T06:22:38Z |
| Test | `uv run --frozen pytest` | ❌ Fail (`5 failed, 1860 passed in 32.60s`). Gate `suite`, tree `1d6b0fc0454d`, stage `record-implementation-results`, 2026-11-06T06:23:12Z |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`: dirty working tree on `00-E9.1`, missing `.mcp.json`). Gate `doctor`, tree `1d6b0fc0454d`, stage `record-implementation-results`, 2026-11-06T06:23:16Z |
| Agent configs | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`). Gate `agents-validate`, tree `1d6b0fc0454d`, stage `record-implementation-results`, 2026-11-06T06:23:15Z |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (`toolkit defaults: 0 error(s), 0 warning(s)`; `resolved repo prompts: 0 error(s), 0 warning(s)`). Gate `prompts-check`, tree `1d6b0fc0454d`, stage `record-implementation-results`, 2026-11-06T06:23:18Z |
| Whitespace | `git diff --check` | ✅ Pass (no output, exit 0) |

Lint: **not run** — this repository configures no linter, formatter, or type-checker (`AGENTS.md`, `design.md` §15), so it has no lint gate and none was invented. Build was run for packaging sanity; `AGENTS.md`'s configured gate set names only install, pytest, doctor, agents validation and prompts check.

### `uv run --frozen pytest` (full suite)

Every row is taken from the single full-suite invocation above; no subset was re-run to obtain a count.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1865 | ❌ Fail (`5 failed, 1860 passed in 32.60s`) |

The five failing tests are all in `tests/test_design_doc.py`:

| Failing test | Observed failure |
|--------------|------------------|
| `test_design_has_no_legacy_root_or_prompt_source_markers` | The forbidden legacy-marker list is absent, but §1.3 Non-goals still mentions `worktrees` (in the cross-task parallelism bullet), violating the task's "do not list worktrees as a non-goal" check. |
| `test_section_3_uses_the_extracted_fixture_layout` | The `## 3. Repository layout` block before `### 3.1` lacks the required `R8`, `Nothing generated`, `inside the **toolkit** repo`, and `inside a **target** repo` evidence; those statements live in §§3.2–3.3, after the test's section boundary. |
| `test_section_91_matches_the_extraction_state_and_lock_layout` | §9.1 uses `locks/<worktree>-<digest>.lock` and lacks the required `locks/<branch>.lock` string. |
| `test_section_72_documents_the_frozen_contract_at_the_wrapper_boundary` | §7.2 says the parent lookup lives in the bundled `gh.py`; the test requires the path `aidw/github.py`. |
| `test_section_17_keeps_rewritten_extraction_decisions_traceable` | §17 has no trace of `D5`, `D6`, `D11`, `D13`, `D15`, `D18`, `D22`, `D23`, `R3`–`R17`. |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Stale-marker sweep over `design.md` (`Scope: ./aidt`, `./aidt`, `aidt/runs/`, `aidt/prompts/`, `aidt/tests/`, `aidt/agent-configs`, `aidt/aidt.toml`, `aidt/.env`, `.pi/prompts/`, `03 E2 E2.9`) | ✅ No forbidden marker was found (standalone `rg` exited 1) |
| Stale-marker contract test's worktree non-goal clause | ❌ §1.3 contains "worktrees" (`test_design_has_no_legacy_root_or_prompt_source_markers`) |
| §3 layout consistent with EXTRACTION.md §3.12 and the top-level `fixtures/target-repo/` path | ❌ Contract test fails on the required R8/two-role evidence before §3.1 (`test_section_3_uses_the_extracted_fixture_layout`); the fixture path itself is correct (`fixtures/target-repo/`, no `tests/fixtures/target-repo/`) |
| §9.1 state/run/lock layout consistent with EXTRACTION.md §3.10/D18 | ❌ `locks/<branch>.lock` is absent and `<worktree>-<digest>.lock` is present (`test_section_91_matches_the_extraction_state_and_lock_layout`) |
| §7.2 frozen GitHub contract names `github.markers`/`github.labels`, exact matching, strict `==`, the E6.3 guard and `aidw/github.py` | ❌ Missing `aidw/github.py` cross-reference (`test_section_72_documents_the_frozen_contract_at_the_wrapper_boundary`) |
| §17 keeps the D1–D24 / R1–R18 decision trail and rewrites D4/E4/F6 | ❌ 20 identifiers are missing from §17 (`test_section_17_keeps_rewritten_extraction_decisions_traceable`) |
| Contract docs are cross-linked and exist: `docs/target-repo-config.md`, `docs/roadmap-format.md`, `docs/releasing.md`, `docs/schema/aidw-config.schema.json`, `docs/migration/EXTRACTION.md` | ✅ `test_contract_links_are_existing_cross_references` passed in the full suite |
| §12 stage registry and prompt precedence (D12–D14) | ✅ `test_section_12_describes_stage_and_prompt_contracts` passed in the full suite |
| §12.5 distribution and compatibility boundary (D9/D10) | ✅ `test_section_125_documents_distribution_and_compatibility_boundary` passed in the full suite |
| §9.2 identity fields (`toolkit_version`, `config_schema_version`, `config_hash`) | ✅ `test_section_92_records_config_identity_fields` passed in the full suite |
| Header has no product-coupling claim; §1 names all four roots and the target-selection precedence | ✅ `test_header_does_not_couple_the_toolkit_to_a_product_repo` and `test_section_1_names_the_two_roots_workspace_and_state_root` passed in the full suite |
| Late sections (§15–§19) use `tests/` + `prompts/scripts/review-followup/tests`, current-state §16 and no legacy `aidt/` paths | ✅ `test_late_sections_are_post_extraction_and_use_current_test_paths` passed in the full suite |

---

## Deviations observed during recording

- **The full test gate fails; implementation is not green as delivered** — five of the new `tests/test_design_doc.py` contract tests fail against the current `design.md`. The record stage did not repair them, per its non-goals; the failure is recorded here for the implementation stage.
- **Roadmap traceability is not updated** — `docs/tasks/00 - Extraction.md:554` still reads `- [ ] **E9.1. Rewrite \`design.md\`**`. The prompt described traceability as complete, but the working tree shows it is not; recording did not change it.
- **Build was run although the configured gate set does not name it** — included for packaging sanity, reported above with its real outcome and no effect on the repository.

---

## Non-Goals (NOT implemented)

- ❌ E9.2: writing `docs/target-repo-config.md` / `docs/roadmap-format.md` — both already exist; `design.md` only cross-links them.
- ❌ E9.3: moving `EXTRACTION.md` to `docs/history/` — it stays the cited extraction plan of record.
- ❌ E9.4: README rewrite — only `design.md` changes here.
- ❌ `AGENTS.md` cleanup (its "Where truth lives" table still calls some docs placeholders).
- ❌ MF.1–MF.6: Mythical Forge cutover work in the product repo.
- ❌ Any code, test, prompt, agent-config, schema, or `pyproject.toml` change beyond the design contract tests — docs and their tests only.
