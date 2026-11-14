# Build Results — 04-X1.1: Summarise each task's build results in a human-readable summary.md

**Branch:** `04-X1.1`
**Date:** 2026-11-13
**Spec:** `design.md` §1.3 (non-goals), §2 (stage-id vocabulary), §5.4 (model routing), §8.2 (`aidw implement` chain), §12.2 (stage registry), §15 (testing strategy), §17 (decision row `Z3`); roadmap entry X1.1 in `docs/tasks/04 - Enhancements.md`; `docs/task-prompts/04-X1.1-prompt.md`

## Summary

**Purpose:** Add a `recorder`-owned `summarize-implementation-results` stage (`I8`) immediately after `record-implementation-results` (`I5`) in the `implement` chain, which reads the just-written `build-results.md` and writes a human-readable narrative `summary.md` beside it — without running any verification gate.

| Decision | Why it matters |
|----------|---------------|
| `I8` is a separate core stage between `I5` and `I7` | The summary needs `I5`'s finished artifact, must land uncommitted in the task's own PR (before `I7`/`I6`), and must not be silently disabled by a repo (`REPO_OPTIONAL_IDS` stays `{I3, I4}`). Registry position is load-bearing for `validate_stage_list`'s reorder rule. |
| The prompt owns the five-section structure; no config path or template | Order and content are fixed by §17 `Z3` while exact heading wording stays implementer freedom; adding `paths.summary_template` would be a new config surface the task explicitly refuses. |
| The stage is strictly read-only about evidence | `I5` is the only stage that buys the whole-repo gate; re-running it here would double the run's most expensive step for no new evidence. The prompt cites `build-results.md` instead. |
| §1.3's "summary prompts are not a workflow stage" non-goal is reversed, scoped to this one summary | Leaving the stale non-goal while §8.2 documents `I8` would make the design contradict itself; `Z3` records the reversal and its bounds. |
| The summary is a `recorder` stage, not a new agent | `recorder` already owns the mechanical record/tick work; adding an agent id would expand the agent contract for no behavioural gain. |

**Where it fits in the roadmap:** Phase 04, Epic X1 ("Narrative implementation summaries"), task X1.1. It depends on H3.1's core `I7 update-roadmap` stage and on E4.3's registry expansion, and completes the epic's first deliverable: the narrative counterpart to the mechanical `build-results.md`. The `I6 pr` stage depends on `I8`'s output being present so the summary lands in the task's PR.

**Scope:** `prompts/summarize-implementation-results.md` (new), `aidw/stage_registry.py` (`I8` in `_IMPLEMENT.stages` and `STAGE_IDS`), `agents/recorder/AGENTS.md` (third stage section), `aidw/inventory.py` (`REQUIRED_PROMPTS`), `design.md` (§1.3, §2, §5.4, §8.2, §17 `Z3`), `aidw/workflows/implement.py` (chain documentation), the fixture's declared implement list, `docs/migration/prompt-classification.md`, and the affected tests. It deliberately stops short of changing `I5`/`I6`/`I7`, adding a config path or template, backfilling summaries for completed tasks, and touching the `prompt`/`review`/`fix`/`approve` workflows.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `prompts/summarize-implementation-results.md` | Created | The `I8` prompt: owns only `<implementation_results_dir>/<branch>/summary.md`, reads `build-results.md` as its single source of truth, and runs no gate. |
| `tests/test_summary_prompt.py` | Created | Contract tests for the summary prompt: front matter/arity, single owned artifact, build-results input, five sections in order, no gate instruction, honesty about failures, and a pinned property sweep. |
| `agents/recorder/AGENTS.md` | Modified | Adds a third `## Stage` section for `/summarize-implementation-results`, read-only and non-overlapping with the record/tick sections. |
| `aidw/inventory.py` | Modified | Adds `summarize-implementation-results.md` to `REQUIRED_PROMPTS` so a rename fails loudly. |
| `aidw/stage_registry.py` | Modified | Adds `I8` to `STAGE_IDS` and the `_IMPLEMENT.stages` list between `I5` and `I7`; updates the core-id documentation. |
| `aidw/workflows/implement.py` | Modified | Documents the eight-stage chain and `I8`'s read-only, no-gate, no-commit role. |
| `design.md` | Modified | Reverses §1.3's non-goal for this summary, extends §2 to `I1`–`I8`, adds `I8` to §5.4 and §8.2, and records decision `Z3` in §17. |
| `docs/migration/prompt-classification.md` | Modified | Adds `summarize-implementation-results.md` to post-cutover class `(iv)` and updates the prompt count. |
| `fixtures/target-repo/aidw/config.yaml` | Modified | Re-baselines the declared implement stage list to include the core `I8`. |
| `docs/task-prompts/04-X1.1-prompt.md` | Modified | The task prompt, rewritten and committed on this branch before the implementation. |
| `tests/test_design_doc.py` | Modified | Adds `test_implement_chain_documentation_is_rebased_to_i8`; that test currently fails (see Verification and Deviations). |
| `tests/test_implement_workflow.py` | Modified | Re-baselines the implement order and dry-run assertions, and adds a fake-stage test that `I8` dispatches on `recorder` between `I5` and `I7`. |
| `tests/test_inventory.py` | Modified | Pins the summary prompt in `REQUIRED_PROMPTS` and in the shipped toolkit inventory. |
| `tests/test_plan_stages.py` | Modified | Re-baselines the eight-stage plan and adds coverage that a declared list omitting `I8` is refused. |
| `tests/test_prompt_classification.py` | Modified | Adds the new prompt to `POST_CUTOVER` and updates counts (14 → 16 toolkit prompts). |
| `tests/test_stage_registry.py` | Modified | Pins `I8` in `STAGE_IDS`, its position, core classification (removal/disable/reorder errors), and updates the permutation sweep to eight ids. |

---

## Verification Results

### Top-level verification

Commands are this repo's own, taken from its root `AGENTS.md` ("Gates — run exactly these, and only these"). There is no `aidw/conventions.md` in this target repo and no lint/formatter/type-checker is configured (AGENTS.md "Tests"; design §15), so the lint row is `n/a`. Gate commands ran through `aidw gate run <key>` with the workflow's declared ignore scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`, recorded against tree `7f52a573a6b5` by stage `record-implementation-results`.

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.87ms`) |
| Lint | — | n/a — this repo configures no linter (AGENTS.md: "pytest is the only verification") |
| Build | `uv build --out-dir <tmp>/dist` (gate `build`) | ✅ Pass — built `aidt-1.3.0.tar.gz` and `aidt-1.3.0-py3-none-any.whl` at `2026-11-13T23:56:47Z` |
| Test | `uv run --frozen pytest` (gate `suite`) | ❌ Fail (`1 failed, 2060 passed in 42.79s`) at `2026-11-13T23:57:33Z` — `tests/test_design_doc.py::test_implement_chain_documentation_is_rebased_to_i8`: `assert 'I1–I8' in purpose` fails because `design.md` §1 still advertises the pre-summary vocabulary |
| Doctor | `uv run --frozen aidw doctor` (gate `doctor`) | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`) at `2026-11-13T23:57:37Z` — warnings are the dirty working tree and a missing `.mcp.json` |
| Agents validate | `uv run --frozen aidw agents validate --strict` (gate `agents`) | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) at `2026-11-13T23:57:36Z` |
| Prompts check | `uv run --frozen aidw prompts check` (gate `prompts`) | ✅ Pass (`resolved repo prompts: 0 error(s), 0 warning(s)`; `summarize-implementation-results.md` resolves to the toolkit default) at `2026-11-13T23:57:39Z` |
| Whitespace | `git diff --check` | ✅ Pass (exit 0, no output) |
| Task dry-run | `uv run aidw implement docs/task-prompts/04-X1.1-prompt.md --dry-run` (gate `dry-run`) | ❌ **unverified** — the command could not run: `another implement run for '04-X1.1' is still marked running: 20261113T233539Z-04-X1.1-implement. Use --resume or finish it.` (gate `dry-run` failed at `2026-11-13T23:57:42Z` with no plan output) |

### `uv run --frozen pytest` (full suite)

The file-level rows are derived from the single full-gate invocation above; no second suite run was bought for this document.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2061 | ❌ Fail (`1 failed, 2060 passed in 42.79s`) |
| `tests/test_design_doc.py` | — | ❌ `test_implement_chain_documentation_is_rebased_to_i8` failed; it is the only failure named in the run |
| `tests/test_stage_registry.py`, `tests/test_plan_stages.py`, `tests/test_implement_workflow.py`, `tests/test_inventory.py`, `tests/test_summary_prompt.py` | — | ✅ No failures from these modules appear in the run's failure list |
| `tests/test_prompt_classification.py` | — | ✅ No failures from this module appear in the run's failure list |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `I8` is in `STAGE_IDS`, not in `REPO_OPTIONAL_IDS`, and sits between `I5` and `I7` in `_IMPLEMENT.stages` | ✅ Pass — covered by `tests/test_stage_registry.py`; no failure from that module appears in the single run |
| `validate_stage_list` treats `I8` as core: removal, disable and reorder each report an `ERROR` | ✅ Pass — covered by `tests/test_stage_registry.py` |
| A declared implement list missing `I8` is refused; one containing `I8` between `I5` and `I7` passes | ✅ Pass — covered by `tests/test_plan_stages.py` |
| A fake-stage run plans and dispatches `I8` on the `recorder` agent in position (no real Pi) | ✅ Pass — covered by `tests/test_implement_workflow.py` |
| `summarize-implementation-results.md` is in `REQUIRED_PROMPTS` and resolves from the toolkit | ✅ Pass — covered by `tests/test_inventory.py` and `aidw prompts check` |
| The summary prompt owns only `<branch>/summary.md`, reads `build-results.md`, contains no gate instruction, and preserves failures/`unverified` rows | ✅ Pass — covered by `tests/test_summary_prompt.py` |
| `uv run aidw implement docs/task-prompts/04-X1.1-prompt.md --dry-run` prints `I8 summarize-implementation-results` between `I5` and `I7` | ❌ **unverified** — blocked by the active run's lock, so no plan was produced |
| `design.md` §1, §12.2 and §19 describe the eight-stage chain | ❌ Fail — `tests/test_design_doc.py::test_implement_chain_documentation_is_rebased_to_i8` fails on the `I1–I8` assertion for §1 |

---

## Deviations observed during recording

- **`design.md` was not fully rebased to `I1`–`I8`** — `tests/test_design_doc.py` expects §1, §12.2 and §19 to advertise the eight-stage vocabulary, but §1 still says `I1`–`I7` (and the test stops at its first assertion). `design.md` did receive the §1.3 reversal, §2, §5.4, §8.2 and §17 `Z3` edits, so the implementation is partially complete. This stage does not fix it; recorded as a real gate failure above.
- **The task dry-run gate was blocked by this branch's own active run** — `aidw implement --dry-run` refuses to start while `20261113T233539Z-04-X1.1-implement` is still marked running. No plan output was produced, so the "prints `I8` between `I5` and `I7`" criterion is recorded as unverified rather than inferred from the registry tests.
- **The `record` stage's gate run was itself blocked from reusing an earlier suite outcome** — tree `7f52a573a6b5` already carried a failed `suite` outcome from the run's `update-traceability` stage, so this stage re-ran the full suite rather than citing it. The two runs agree on the same single failure.

---

## Non-Goals (NOT implemented)

- ❌ No new agent id — `recorder` is reused (task prompt, "Explicit non-goals").
- ❌ No new config path, template, or `paths.*` key — the narrative structure lives in the prompt (task prompt; design §17 `Z3`).
- ❌ No change to `I5` (gates/scope/artifact), `I7` (tick), or `I6` (commit/PR) (task prompt, "Explicit non-goals").
- ❌ No backfill of summaries for already-completed tasks (task prompt, "Explicit non-goals").
- ❌ No change to the `prompt`/`review`/`fix`/`approve` workflows — `implement`-only (task prompt, "Explicit non-goals").
- ❌ No gate re-run and no commit/push/PR from this stage — `I6` owns delivery (task prompt, "Explicit non-goals").
- ❌ Do not write `player-actions.md` or `integration-tests.md` — the `show-updated-*` prompts own those documents.
