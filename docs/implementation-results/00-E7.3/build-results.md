# Build Results — 00-E7.3: Conventions injection (D16)

**Branch:** `00-E7.3`
**Date:** 2026-11-05
**Spec:** `docs/migration/EXTRACTION.md` §3.8 (task-prompt format and repo conventions, D16), §3.4 (target-repo config: gate commands come from the repo, R10/R14/D16; the degrade-never-error state), §2 (locked decisions, row D16), §3.6 (prompt resolution and repo overrides), §3.12 (repo layout authority)

## Summary

**Purpose:** Deliver the runtime conventions channel that injects the **target** repo's root `AGENTS.md` and optional `aidw/conventions.md` into exactly the four prompts §3.8 names, so prompts no longer need to inline a target repo's stack rules and gate commands.

| Decision | Why it matters |
|----------|---------------|
| Key injection on the **resolved prompt basename** (`spec.prompt.name`), not the stage id | `test.md` runs under two stage names (`test` in `_IMPLEMENT`, `iter{iteration}-test` in `_FIX`); stage-id keying would silently skip the fix-loop tester. A repo-shadowed prompt (§3.6 precedence 2/3) also keeps its basename. |
| Read `AGENTS.md` then `aidw/conventions.md` from the `run_stage` **`repo_root`** parameter | In a self-hosted run the toolkit root and target root coincide, so a `toolkit_root()` read would pass every test here and break only after extraction. The fixture carries a target-only sentinel and asserts a toolkit-only phrase is absent. |
| One shared reader in `aidw/prompts.py`, consumed by both injectors | `read_conventions_sources` / `render_repo_conventions` is the single channel for the four-prompt injection **and** `_gate_block`, so the evidence bundle and the prompts cannot drift into two conventions sources. |
| Absence contributes nothing (empty string), never a placeholder or raise | §3.4's "a repo with no conventions yet" is a normal state. The render stays byte-identical to the un-injected prompt, which keeps existing dry-run render tests and prompts noise-free. |
| Inject after `render_prompt_file` and after `spec.extra` | The agent reads prompt body → stage's curated extra → repo conventions, and both the written `.rendered.md` and the stdin payload to Pi carry the same text. The prompt files and `spec.variables` are never mutated. |
| `_gate_block` extracts each source's `## Gates` section and joins them in D16 order | R14 sends new gate commands to `conventions.md` by name; an AGENTS.md-only reader would silently ignore them. The heading-bounded extraction and the unavailable-note degradation are preserved, so the existing six-element AGENTS.md-only fixture stays green. |

**Where it fits in the roadmap:** E7.3 is the injection-mechanism task of epic **E7 — Split the prompt library**. It depends on **E7.2**, which made the four prompts name the conventions source without inlining stack-specific commands, and on the **E6** contract freeze that stabilised the marker and gate vocabulary. **E7.4** then neutralises agent guidance, **E7.5** splits the inventory, and **MF.2** re-supplies the product text as `aidw/prompts/` overrides at cutover. E7.3 deliberately adds only the runtime mechanism; it does not relocate or rewrite `task-prompt.md`.

**Scope:** New conventions code in `aidw/prompts.py`, its `run_stage` call site in `aidw/runner.py`, the extended gate source in `aidw/workflows/prompt.py`, a new contract/property test module, new E7.3 cases in `tests/test_prompt_workflow.py`, and the extraction-roadmap tick. It stops short of neutralising agent guidance (E7.4), splitting the inventory (E7.5), moving bucket-(iii) `task-prompt.md` to a target repo's `aidw/prompts/` (cutover §7 / MF.2), editing the four prompts' text, or adding a config field — `aidw/conventions.md` is a fixed D16 path, not a `paths.*` entry.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `tests/test_conventions_injection.py` | Created | Contract/property tests for the four-prompt injection: D16 order, absence, basename keying, shadowed prompts, stage extra ordering, stdout/stdin parity, two-roots sentinel, purity, and unreadable/empty sources. |
| `docs/implementation-results/00-E7.3/build-results.md` | Created | This document (written by the record stage after gating). |
| `aidw/prompts.py` | Modified | Adds the conventions channel: `CONVENTIONS_PROMPTS`, `CONVENTIONS_SOURCES`, `read_conventions_sources`, `render_repo_conventions`, `receives_repo_conventions`, `inject_repo_conventions`. |
| `aidw/runner.py` | Modified | `run_stage` injects the target repo's conventions after `render_prompt_file` and `spec.extra`, keyed on the resolved prompt basename and reading `repo_root`. |
| `aidw/workflows/prompt.py` | Modified | `_gate_block` now sources `## Gates` from every D16 conventions source via the shared reader; extraction split into `_gates_section` and the evidence heading names both files. |
| `tests/test_prompt_workflow.py` | Modified | Adds a `conventions.md` evidence fixture and E7.3 cases proving the bundle's gate list includes its commands while the AGENTS.md-only assertions remain unchanged. |
| `docs/tasks/00 - Extraction.md` | Modified | Traceability stage: ticks **E7.3** complete and records the delivered artifacts, tests, and flags. |
| `docs/task-prompts/00-E7.3-prompt.md` | Created | Task brief for this task (committed on the branch by the task-prompt stage). |

---

## Verification Results

Every row below was produced once, in this recording, against the working tree containing the files above. `aidw gate run` reported tree id **`85cef1a84ca1`** for every gate, all under stage `record-implementation-results`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.51ms` (lockfile in sync, no resolution) |
| Build | `uv run --frozen aidw gate run build $SCOPE -- uv build --out-dir $(mktemp -d)` | ✅ `Successfully built aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` — gate `build`, tree `85cef1a84ca1`, stage `record-implementation-results`, 2026-11-05T09:03:14Z |
| Test / suite | `uv run --frozen aidw gate run suite $SCOPE -- uv run --frozen pytest` | ✅ `1689 passed in 36.18s` — gate `suite`, tree `85cef1a84ca1`, stage `record-implementation-results`, 2026-11-05T09:03:52Z |
| Doctor | `uv run --frozen aidw gate run doctor $SCOPE -- uv run --frozen aidw doctor` | ✅ `19 checks: 0 failed, 2 warning(s)` — expected `dirty working tree` and `missing .mcp.json`; gate `doctor`, tree `85cef1a84ca1`, 2026-11-05T09:03:57Z |
| Agents validate | `uv run --frozen aidw gate run agents-validate $SCOPE -- uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` — gate `agents-validate`, tree `85cef1a84ca1`, 2026-11-05T09:03:57Z |
| Prompts check | `uv run --frozen aidw gate run prompts-check $SCOPE -- uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` — gate `prompts-check`, tree `85cef1a84ca1`, 2026-11-05T09:03:57Z |
| Lint | — | ❌ **unverified** — no linter, formatter or type-checker is configured in this repo (`AGENTS.md` §Gates / `design.md` §15), so there is no lint gate to run |
| Whitespace | `git diff --check` | ✅ clean (no output, exit 0) |

`$SCOPE` = `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` (the write-targets of the stages of this workflow; nothing a gate reads is excluded — `aidw/` and `tests/` are inside the gated tree).

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1689 | ✅ Pass (`1689 passed in 36.18s`, gate `suite`, tree `85cef1a84ca1`, 2026-11-05T09:03:52Z) |
| `tests/test_conventions_injection.py` | 56 | ✅ Pass (collected via `pytest --collect-only -q`; executed inside the task gate below, not a second full-suite run) |
| `tests/test_prompt_neutrality.py` | 50 | ✅ Pass (collected via `pytest --collect-only -q`; executed inside the task gate below) |
| `tests/test_prompt_workflow.py` | 169 | ✅ Pass (collected via `pytest --collect-only -q`; executed inside the task gate below) |
| `tests/test_runner.py` | 31 | ✅ Pass (collected via `pytest --collect-only -q`; executed inside the task gate below) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run --frozen aidw gate run conventions-injection $SCOPE -- uv run --frozen pytest tests/test_conventions_injection.py tests/test_runner.py tests/test_prompt_workflow.py tests/test_prompt_neutrality.py` (the task prompt's Done-when command) | ✅ `306 passed in 16.09s` — gate `conventions-injection`, tree `85cef1a84ca1`, 2026-11-05T09:04:16Z |
| Each of the four prompts receives both sources, `AGENTS.md` before `aidw/conventions.md`, each content whole and under a header naming its source | ✅ pass (`test_each_of_the_four_prompts_receives_both_sources_in_d16_order`, `test_the_four_prompts_are_exactly_the_section_3_8_set`) |
| Missing `aidw/conventions.md` contributes nothing and the stage still succeeds; a repo with neither source renders byte-identically | ✅ pass (`test_missing_conventions_md_contributes_nothing_and_the_run_succeeds`, `test_a_repo_with_neither_source_leaves_the_prompt_byte_identical`) |
| Keying is on the resolved prompt basename: a shadowed `test.md` and the fix-loop `iter0-test` stage are injected; a non-conventions prompt under a `test` stage is not | ✅ pass (`test_a_resolved_shadow_prompt_still_receives_the_injection`, `test_a_fix_loop_stage_name_still_receives_the_injection`, `test_a_conventions_stage_name_with_another_prompt_is_not_injected`, `test_receives_repo_conventions_keys_on_the_resolved_basename`) |
| The written `.rendered.md` and the stdin payload to Pi receive the same injection, applied after the stage extra | ✅ pass (`test_written_render_and_pi_stdin_receive_the_same_injection`, `test_injection_is_after_the_stage_extra`) |
| The target root, not `toolkit_root()`, is the read source (fixture sentinel present, toolkit-only phrase absent) | ✅ pass (`test_the_target_root_is_the_read_source_not_the_toolkit_root`) |
| Reading is pure and fail-closed: sources unchanged, absent files not created, unreadable/empty sources degrade to nothing | ✅ pass (`test_reading_conventions_writes_nothing_and_leaves_the_sources_identical`, `test_injection_does_not_mutate_the_prompt_file_or_the_variables`, `test_an_unreadable_source_degrades_to_nothing_instead_of_raising`, `test_an_empty_source_contributes_no_dangling_header`) |
| Property sweeps: exactly the four shipped prompt basenames are injected, and the block follows the D16 order/absence rule across the source-presence matrix | ✅ pass (`test_the_property_seeds_are_the_pinned_sample`, `test_property_exactly_the_four_shipped_prompts_are_injected`, `test_property_source_presence_matches_the_d16_order_rule`) |
| The evidence bundle's gate list includes `conventions.md` commands after `AGENTS.md`'s, and `conventions.md` alone supplies the list; no source still degrades to the unavailable note | ✅ pass (`test_e73_gate_list_includes_conventions_md_commands_after_agents_md`, `test_e73_conventions_md_alone_supplies_the_gate_list`, `test_e73_no_source_still_degrades_the_gate_block`) |
| `prompts check` clean after the change (no prompt file edited) | ✅ `prompts check: 0 error(s), 0 warning(s)` (gate above) |

---

## Deviations observed during recording

- **Gate stack.** This repo is Python/uv; the full gate is `uv sync --frozen`, `uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents validate --strict`, `uv run aidw prompts check`, plus `uv build` to fill the template's Build row. No other stack's commands were run.
- **Lint row.** No lint command exists in this repo, so it is recorded as **unverified** rather than as a passing run.
- **Task gate key.** The task prompt's Done-when names the four-file pytest command; it was recorded under the key `conventions-injection` because it is task-specific rather than the repo's `suite` gate.
- **Test counts.** Per-file counts come from `pytest --collect-only -q` against the same tree; they were not obtained by re-running the suites.

---

## Non-Goals (NOT implemented)

- ❌ E7.4 agent-guidance neutralisation: `agents/*/AGENTS.md` were not touched (task prompt, "Explicit non-goals").
- ❌ E7.5 inventory split: `aidw/inventory.py` and its stage references were not touched (task prompt, "Explicit non-goals").
- ❌ Cutover §7 / MF.2: bucket (iii) `task-prompt.md` was not moved to a target repo's `aidw/prompts/`, and its product text was not rewritten — E7.3 adds the mechanism only (task prompt, "Explicit non-goals").
- ❌ The four prompts' text was not edited, and no config field was added: `aidw/conventions.md` remains a fixed D16 path, not a `paths.*` entry (task prompt, "Explicit non-goals").
- ❌ No redaction layer was added: injecting a repo's whole `AGENTS.md` and `conventions.md` verbatim is the repo's contract, not E7.3's (task prompt, security note).
- ❌ No commit, push or PR opened by this stage (`prompts/pr.md` owns delivery).
