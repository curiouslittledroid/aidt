# Build Results — 05-W1.1: `update-traceability` (I3) must not edit the roadmap

**Branch:** `05-W1.1`
**Date:** 2026-11-20
**Spec:** `design.md` §8.2 (`I3 update-traceability` and `I7 update-roadmap`, including `I7`'s byte-exact tick postcondition), §12.1 (the resolved target config and `aidw/conventions.md`), §17 row `Z13`, §18 (the open-risk row it points at); roadmap entry W1.1 in `docs/tasks/05 - Pipeline efficiency.md`; `docs/task-prompts/05-W1.1-prompt.md`
**Pull request:** #170 — https://github.com/curiouslittledroid/aidt/pull/170

## Summary

**Purpose:** Make it impossible for `I3 update-traceability` to edit anything under `paths.roadmap_dir`, so `I7`'s byte-exact `- [ ]` → `- [x]` tick postcondition stays satisfiable in the same run, and extend the repo-conventions channel so a repo can declare its traceability artefacts (including "none") to `I3`.

| Decision | Why it matters |
|----------|---------------|
| The rule is **ownership**, stated in `prompts/update-traceability.md`, not a weaker `I7` check | `I7`'s `roadmap.verify_checkbox_flip` deliberately compares the whole line list against a run-start snapshot; capturing `tick_before` later or allow-listing sub-lines re-opens the PR #282 hole (Z13). |
| A repo whose only candidate artefact is the roadmap reports **"None for traceability"** | "None" is a valid `I3` outcome, not a licence to adopt the roadmap as an artefact — the failure mode observed live in `20261119T211427Z-05-S1.2-implement`. |
| `CONVENTIONS_PROMPTS` grows from four to five, adding `update-traceability.md` | A conventions-only fix cannot instruct `I3`: the channel reached only the four EXTRACTION.md §3.8 prompts. This is the channel decision Z13 names, recorded as the §18 risk resolution. |
| Keying stays the **resolved prompt basename**, not the stage id | A repo-shadowed `aidw/prompts/update-traceability.md` is injected by its basename too; no special case for stage `I3` or the toolkit default. |
| The prompt names the key `roadmap_dir` and the stage `/update-roadmap`, never the literal `docs/tasks` | `docs/tasks` is a `PRODUCT_PATHS` forbidden token in `tests/test_prompt_neutrality.py`; naming the config key keeps the prohibition product-neutral. |

**Where it fits in the roadmap:** Phase 05 ("Pipeline efficiency"), epic W1 ("Write ownership"), task W1.1. It closes the first of the two silent gaps the epic opens with — a stage rewriting a file another stage owns byte-exclusively — and depends on the H3.1 work that moved the roadmap tick to the core `/update-roadmap` stage and on the D16/E7.3 repo-conventions channel. W1.2 (`--dry-run` must not create a run or become a `--resume` target) is the next task in the same epic and is not started here.

**Scope:** the `I3` prompt's hard rule and non-goals, the fifth member of `aidw/prompts.py:CONVENTIONS_PROMPTS` plus the "four prompts" prose it invalidates, this repo's own `aidw/conventions.md` declaration, `design.md` §§8.2/12.1/17 Z13/18, the live config contract doc, and the three named test modules. It deliberately stops short of a mechanical `I3` postcondition (Python verifying `paths.roadmap_dir`'s bytes after `I3` runs) and of any change to `I7`'s postcondition, `tick_before`'s capture point, `verify_checkbox_flip`, or run-store/resume behaviour.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/05-W1.1-prompt.md` | Created | The task prompt recording requirements, traps, deliverables, tests and explicit non-goals. |
| `docs/implementation-results/05-W1.1/build-results.md` | Created | This document, written by the `record-implementation-results` stage. |
| `aidw/conventions.md` | Modified | States that the roadmap is never a traceability artefact and that the "None for traceability" outcome covers a repo whose only candidate is the roadmap. |
| `aidw/prompts.py` | Modified | Adds `update-traceability.md` as the fifth `CONVENTIONS_PROMPTS` member and updates the module docstring, `read_conventions_sources` and `receives_repo_conventions` prose from "four" to "five". |
| `aidw/runner.py` | Modified | Updates the `inject_repo_conventions` call-site comment to say five prompts and name `update-traceability.md` as Z13's fifth. |
| `aidw/workflows/prompt.py` | Modified | Updates `_gate_block`'s docstring from the four-prompt to the five-prompt injection. |
| `design.md` | Modified | §8.2 gains the `I3` roadmap-ownership sentence, §12.1 the conventions-declaration paragraph, §17 Z13's enforcement note reads "landed, W1.1", and §18's channel risk is marked **Resolved (W1.1)**. |
| `docs/target-repo-config.md` | Modified | The `conventions.md` bullet now names `update-traceability` among the injected prompts and names the file as where a repo declares its traceability artefacts, including "none". |
| `prompts/update-traceability.md` | Modified | Adds the hard rule (never edit `paths.roadmap_dir`; `/update-roadmap` owns it byte-exclusively; "None for traceability" is a valid outcome), extends "Do not touch" and the non-goals, and extends step 7. |
| `tests/test_conventions_injection.py` | Modified | `FOUR_PROMPTS` → `FIVE_PROMPTS` gaining `update-traceability.md`, "four" → "five" prose and test names, the exact-set assertion extended, and a new basename-vs-stage-id test using a repo-shadowed `update-traceability.md`. |
| `tests/test_implement_workflow.py` | Modified | Adds an implement-level proof that a target's `aidw/conventions.md` reaches the rendered `I3` prompt (real `run_stage`, no fake, no Pi) and that the prompt carries the ownership rule and still expands `$1`. |
| `tests/test_prompt_neutrality.py` | Modified | Re-baselines `RETAINED_KEYS["update-traceability.md"]` with `roadmap_dir` (reversing the stale H3.1 comment) and adds a test pinning the ownership sentence and the absence of the `docs/tasks` literal. |

---

## Verification Results

Commands are this repo's own, taken from its root `AGENTS.md` ("Gates — run exactly these, and only these"). AGENTS.md states that `pytest` is the only verification (no linter, formatter or type-checker is configured; design §15), so there is no lint command and the lint row is unverified. The gates ran through `aidw gate run <key>` with the workflow's declared scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.92ms`) |
| Lint | — | **unverified** — the repo configures no linter (AGENTS.md: "pytest is the only verification") |
| Build | `uv build --out-dir <mktemp dir>` (gate `build`) | ✅ Pass — built `aidt-1.5.0.tar.gz` and `aidt-1.5.0-py3-none-any.whl` |
| Test | `uv run --frozen pytest` (gate `suite`) | ✅ Pass (`2276 passed in 49.29s`) — cited from this run's recorded gate, not re-run here |
| Doctor | `uv run --frozen aidw doctor` (gate `doctor`) | ✅ Pass (`22 checks: 0 failed, 2 warning(s)`) — warnings are the dirty working tree and the missing `.mcp.json` |
| Agents validate | `uv run --frozen aidw agents validate --strict` (gate `agents`) | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` (gate `prompts`) | ✅ Pass (`resolved repo prompts: 0 error(s), 0 warning(s)`) |
| Traceability checks | `uv run --frozen pytest tests/test_design_doc.py tests/test_workflow_stages_doc.py tests/test_target_repo_config_doc.py` (gate `traceability`) | ✅ Pass (`82 passed in 0.80s`) — cited from this run's recorded gate |
| Whitespace | `git diff --check` | ✅ Pass (exit 0, no output) |

Gate origins for the rows above (tree `40a68cafaf83`, scope excludes `docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks`):

- `build` — passed at `2026-11-20T02:22:56Z`, stage `record-implementation-results` (`Successfully built …/aidt-1.5.0-py3-none-any.whl`).
- `suite` — passed at `2026-11-20T02:21:46Z`, stage `update-traceability` (`2276 passed in 49.29s`); `aidw gate run` printed the `reused: …` line and exited 0 against the same tree and scope, so no second suite was bought for this document.
- `doctor` — passed at `2026-11-20T02:23:15Z`, stage `record-implementation-results` (`22 checks: 0 failed, 2 warning(s)`).
- `prompts` — passed at `2026-11-20T02:23:15Z`, stage `record-implementation-results` (`resolved repo prompts: 0 error(s), 0 warning(s)`).
- `agents` — passed at `2026-11-20T02:23:16Z`, stage `record-implementation-results` (`11 agent config(s): 0 error(s), 0 warning(s)`).
- `traceability` — passed at `2026-11-20T02:20:53Z`, stage `update-traceability` (`82 passed in 0.80s`), same tree and scope.

### `uv run --frozen pytest` (full suite)

Every row below comes from the single full-suite gate run for this tree; no suite, module or subset was re-run for this document.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2276 | ✅ Pass (`2276 passed in 49.29s`, gate `suite`, stage `update-traceability`, tree `40a68cafaf83`) |
| Traceability doc drift (`tests/test_design_doc.py tests/test_workflow_stages_doc.py tests/test_target_repo_config_doc.py`) | 82 | ✅ Pass (`82 passed in 0.80s`, gate `traceability`, stage `update-traceability`, tree `40a68cafaf83`) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Exact-set contract — the conventions set is exactly the five prompts, and the assertion fails if `update-traceability.md` is dropped | ✅ Pass — `tests/test_conventions_injection.py::test_the_five_prompts_are_exactly_the_injection_set`, covered by the full suite (2276 passed) |
| Basename keying — a repo-shadowed `aidw/prompts/update-traceability.md` is injected under a stage name that is not its basename, and a stage named `update-traceability` rendering another file receives nothing | ✅ Pass — `tests/test_conventions_injection.py::test_the_traceability_prompt_is_injected_by_basename_not_by_stage_id`, covered by the full suite |
| Neutrality — the rendered `update-traceability.md` names `roadmap_dir`, resolves under both the Mythical-Forge-shaped and neutral configs, carries the ownership rule, and names no `docs/tasks` literal | ✅ Pass — `tests/test_prompt_neutrality.py::test_retained_defaults_name_config_keys_that_resolve_under_both_configs` and `::test_the_traceability_default_states_the_roadmap_ownership_rule`, covered by the full suite |
| Implement-level render — an implement run whose target carries `aidw/conventions.md` renders that declaration into the `I3` prompt, which also carries the ownership rule and still expands `$1` | ✅ Pass — `tests/test_implement_workflow.py::test_a_target_conventions_declaration_reaches_the_rendered_i3_prompt`, covered by the full suite |
| `update-traceability.md` stays resolvable and the prompt inventory is intact | ✅ Pass — `uv run --frozen aidw prompts check` (gate `prompts`, `0 error(s), 0 warning(s)`) |
| Design-doc pins — §8.2/§12.1 mention the ownership rule and §17 Z13 is exactly one row that no longer reads "pending"; §18's risk reads resolved | ✅ Pass — `tests/test_design_doc.py` in the `traceability` gate (`82 passed`) |
| Workflow-stages and target-config doc drift — the conventions bullet names `update-traceability` and the artefact declaration | ✅ Pass — `tests/test_workflow_stages_doc.py` and `tests/test_target_repo_config_doc.py` in the `traceability` gate |
| Mechanical `I3` postcondition (Python verifying `paths.roadmap_dir` bytes after `I3` runs) | ❌ **unverified** — not implemented; the task prompt's explicit non-goal leaves it as the "stronger alternative" Z13 records, out of scope for W1.1 |
| Live end-to-end `implement` run against a real Pi model | ❌ **unverified** — not run by this stage; AGENTS.md forbids a test invoking a real Pi model, and the render path is proven by `--dry-run` (see `integration-test-guide.md` for the human-run procedure) |

---

## Deviations observed during recording

- **No lint command exists to run** — the repo's AGENTS.md gate list contains install, pytest, doctor, agents validation and prompts check only, and states that `pytest` is the only verification. The lint row is recorded as unverified rather than inventing a command.
- **The suite and traceability outcomes were reused from this run's recorded gates** — `suite` and `traceability` had already passed for tree `40a68cafaf83` under the identical declared scope during the `update-traceability` stage. `aidw gate run` printed the `reused: …` line and exited 0 without re-running.
- **No pull request to name** — the read-only `gh pr view 05-W1.1` lookup returned `#169`, but that PR is **MERGED** and predates this change set (its content is already on `main`; only the task-prompt commit is on this branch). It is not the PR that carries these changes, so the document records the not-yet-opened note; `/pr` will replace it with the real number.
- **The three task test modules were not given their own gate** — the implementation stage's `smoke` gate (`229 passed`) ran against an earlier tree (`a7e1ec172a16`) that predates the traceability doc edits. Rather than re-running a subset for a count, the task-specific rows cite the full-suite and `traceability` gates on the current tree (`40a68cafaf83`).
- **`aidw doctor` reports two warnings** — the dirty working tree and missing `.mcp.json` are expected while the implementation and this results document remain uncommitted; `0 checks failed`.
- **Doc drift in the roadmap entry's `Tests` line** — the W1.1 roadmap entry names `tests/test_prompt_workflow.py`; the task prompt and the implemented tests use `tests/test_conventions_injection.py`. The roadmap entry was not edited (it belongs to `update-roadmap`), and §17 Z13 records the actual re-baselined checkers.

---

## Non-Goals (NOT implemented)

- ❌ W1.2 (`--dry-run` must not create a run or become a `--resume` target) — run-store creation and resume lookup were not touched (task prompt, "Explicit non-goals").
- ❌ A mechanical `I3` postcondition (Python verifying `paths.roadmap_dir` bytes unchanged after `I3` runs) — out of scope; Z13 leaves it as the stronger alternative, and adding it would be a separate §17 decision plus `aidw/workflows/implement.py`/`aidw/roadmap.py` and test scope (task prompt, "Explicit non-goals").
- ❌ No weakening of `I7`'s postcondition — `tick_before`'s capture point, `verify_checkbox_flip` and `I7`'s still-`skipped`-never-`failed` behaviour on a red gate are unchanged (Z13).
- ❌ No new checker, status vocabulary or CI gate, and no change to `aidw/inventory.py` — `update-traceability.md` stays an existing `REQUIRED_PROMPTS` entry (task prompt, "Gate impact").
- ❌ No commit, push or pull request from this record stage — delivery belongs to `/pr` (record stage instruction).
