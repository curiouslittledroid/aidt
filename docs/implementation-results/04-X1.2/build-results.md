# Build Results — 04-X1.2: Write a human-run integration test guide beside the build results

**Branch:** `04-X1.2`
**Date:** 2026-11-14
**Spec:** `design.md` §1.3 (non-goals), §2 (stage-id vocabulary), §5.4 (model routing), §8.2 (`aidw implement` chain), §12.2 (stage registry), §17 (decision row `Z6`); roadmap entry X1.2 in `docs/tasks/04 - Enhancements.md`; `docs/task-prompts/04-X1.2-prompt.md`
**Pull request:** not yet opened — the `/pr` stage records its number here once the PR exists

## Summary

**Purpose:** Add a `recorder`-owned `write-integration-test-guide` stage (`I9`) immediately after `summarize-implementation-results` (`I8`) in the `implement` chain, which records a step-by-step, human-run integration-test procedure beside the build results without executing any test, gate or cloud/browser command.

| Decision | Why it matters |
|----------|---------------|
| `I9` is a separate **core**, unconditional stage between `I8` and `I7` | The guide needs `I5`'s finished build results, must land uncommitted in the task's own PR before the tick/PR stages, and must not be silently disabled by a repo (`REPO_OPTIONAL_IDS` stays `{I3, I4}`). Its registry position is load-bearing for `validate_stage_list`'s reorder rule. |
| The stage is an **instruction document, never an execution** | Running an integration test, gate, cloud call or browser flow is the side effect §1.3's deployed-integration-tests non-goal forbids. The guide tells a human what to run; the toolkit only reads the tree. |
| The prompt file is `write-integration-test-guide.md`, deliberately not `integration-tests.md` | `integration-tests.md` is a product prompt MF owns; a target repo's same-named file would shadow this stage's prompt by filename (D14), silently swapping it. |
| The guide's section order and five per-scenario fields live in the prompt; no new config path or template | The roadmap fixes the structure, while exact heading wording stays implementer freedom. Adding `paths.*` keys would be a new config surface the task explicitly refuses. |
| The guide is a `recorder` stage, not a new agent | `recorder` already owns the mechanical record/summary/tick work; a new agent id would expand the agent contract without a behavioural gain. |

**Where it fits in the roadmap:** Phase 04, Epic X1 ("Narrative implementation summaries"), task X1.2. It depends on X1.1's core `I8 summarize-implementation-results` stage and on H3.1's core `I7 update-roadmap` stage, and it completes the epic's second deliverable: the hand-run runbook that complements the mechanical `build-results.md` and the narrative `summary.md`. The `I6 pr` stage depends on `I9`'s guide being present so it lands in the task's PR.

**Scope:** `prompts/write-integration-test-guide.md` (new), `tests/test_integration_guide_prompt.py` (new), `aidw/stage_registry.py` (`I9` in `_IMPLEMENT.stages` and `STAGE_IDS`), `agents/recorder/AGENTS.md` (fourth stage section), `aidw/inventory.py` (`REQUIRED_PROMPTS`), `aidw/workflows/implement.py` (chain documentation), `design.md` (§1.3, §2, §5.4, §8.2, §12.2, §17 `Z6`), `README.md`, `docs/workflow-stages.md`, `docs/migration/prompt-classification.md`, the fixture's declared implement list, and the affected tests. It deliberately stops short of changing `I5`/`I8`/`I7`/`I6`, adding any agent id, `paths.*` key, template or `parallel_groups` member, wiring a stage that runs a deployed integration test, and touching the `prompt`/`review`/`fix`/`approve` workflows.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `prompts/write-integration-test-guide.md` | Created | The `I9` prompt: owns only `<implementation_results_dir>/<branch>/integration-test-guide.md`, reads the build results, task prompt and changed files, and runs nothing. |
| `tests/test_integration_guide_prompt.py` | Created | Contract tests for the guide prompt: single owned artifact, required inputs, four sections in order, five per-scenario fields, two closing sections, no execution instruction, and a pinned property sweep. |
| `README.md` | Modified | Updates the `aidw implement` block, stage count and dry-run wording to `I1`–`I9`. |
| `agents/recorder/AGENTS.md` | Modified | Adds a fourth `## Stage` section for `/write-integration-test-guide`, read-only and non-overlapping with record/summarize/update-roadmap. |
| `aidw/inventory.py` | Modified | Adds `write-integration-test-guide.md` to `REQUIRED_PROMPTS` so a rename fails loudly. |
| `aidw/stage_registry.py` | Modified | Adds the core `I9` to `STAGE_IDS` and `_IMPLEMENT.stages` between `I8` and `I7`, and updates the core-id documentation. |
| `aidw/workflows/implement.py` | Modified | Documents the nine-stage chain and `I9`'s read-only, no-execution role. |
| `design.md` | Modified | Preserves §1.3's non-goal while naming `I9`, extends §2/§5.4/§8.2/§12.2 to `I9`, and records decision `Z6` in §17. |
| `docs/migration/prompt-classification.md` | Modified | Adds `write-integration-test-guide.md` to post-cutover class `(iv)` and updates the toolkit prompt count to 17. |
| `docs/task-prompts/04-X1.2-prompt.md` | Modified | The task prompt, added on this branch before the implementation. |
| `docs/workflow-stages.md` | Modified | Adds `I9` to the drift-checked id-vocabulary, inventory, per-stage description and core runtime order. |
| `fixtures/target-repo/aidw/config.yaml` | Modified | Re-baselines the declared implement stage list to include the core `I9` between `I8` and `I7`. |
| `tests/test_design_doc.py` | Modified | Re-baselines the design chain assertions from `I1–I8`/`I1–I7` to `I1–I9`/`I1–I8`. |
| `tests/test_implement_workflow.py` | Modified | Re-baselines the implement order and dry-run assertions, and adds a fake-stage test that `I9` dispatches on `recorder` between `I8` and `I7`. |
| `tests/test_inventory.py` | Modified | Pins the guide prompt in `REQUIRED_PROMPTS` and in the shipped toolkit inventory, and checks `integration-tests.md` is not required. |
| `tests/test_plan_stages.py` | Modified | Re-baselines the nine-stage plan and adds coverage that a declared list omitting `I9` is refused and the `I8 → I9 → I7` position is accepted. |
| `tests/test_prompt_classification.py` | Modified | Adds the new prompt to `POST_CUTOVER` and updates the toolkit count to 17. |
| `tests/test_stage_registry.py` | Modified | Pins `I9` in `STAGE_IDS`, its position, core classification (removal/disable/reorder errors), and retargets the unknown-id probe to `I10`. |
| `tests/test_workflow_stages_doc.py` | Modified | Re-baselines the drift-checked id-vocabulary and implement tables to carry `I9` in order. |

---

## Verification Results

Commands are this repo's own, taken from its root `AGENTS.md` ("Gates — run exactly these, and only these"). There is no `aidw/conventions.md` in this target repo and no lint/formatter/type-checker is configured (AGENTS.md "Tests"; design §15), so the lint row is `n/a`. Gate commands ran through `aidw gate run <key>` with the workflow's declared ignore scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.88ms`) |
| Lint | — | n/a — this repo configures no linter (AGENTS.md: "pytest is the only verification") |
| Build | `uv build --out-dir <tmp>/dist` (gate `build`) | ✅ Pass — built `aidt-1.3.0.tar.gz` and `aidt-1.3.0-py3-none-any.whl` |
| Test | `uv run --frozen pytest` (gate `suite`) | ✅ Pass (`2105 passed in 39.63s`) — cited from this run's earlier `test` stage, same tree and scope (see origin below) |
| Doctor | `uv run --frozen aidw doctor` (gate `doctor`) | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`) — warnings are the dirty working tree and the missing `.mcp.json` |
| Agents validate | `uv run --frozen aidw agents validate --strict` (gate `agents`) | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` (gate `prompts`) | ✅ Pass (`resolved repo prompts: 0 error(s), 0 warning(s)`; `write-integration-test-guide.md` resolves to the toolkit default) |
| Whitespace | `git diff --check` | ✅ Pass (exit 0, no output) |
| Task dry-run | `AIDW_STATE_DIR=<temporary-state-dir> uv run --frozen aidw implement docs/task-prompts/04-X1.2-prompt.md --dry-run` (gate `dry-run`) | ✅ Pass — prints `I9 write-integration-test-guide [succeeded] (planned) agent=recorder` between `I8` and `I7`, and ends `dry-run complete; Pi not invoked` |

Gate origins for the rows above (tree `bcbaa5a589c0`, scope excludes `docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks`):

- `build` — passed at `2026-11-14T03:21:32Z`, stage `record-implementation-results`.
- `suite` — passed at `2026-11-14T03:17:25Z`, stage `test` (`2105 passed in 39.63s`), reused by this stage against the same tree and scope.
- `doctor` — passed at `2026-11-14T03:21:37Z`, stage `record-implementation-results` (`21 checks: 0 failed, 2 warning(s)`).
- `agents` — passed at `2026-11-14T03:21:37Z`, stage `record-implementation-results` (`11 agent config(s): 0 error(s), 0 warning(s)`).
- `prompts` — passed at `2026-11-14T03:21:37Z`, stage `record-implementation-results` (`resolved repo prompts: 0 error(s), 0 warning(s)`).
- `smoke` — passed at `2026-11-14T03:16:42Z`, stage `test` (`341 passed in 24.77s`), used for the task-specific module rows below.
- `dry-run` — passed at `2026-11-14T03:21:50Z`, stage `record-implementation-results` (`dry-run complete; Pi not invoked`), run with an isolated `AIDW_STATE_DIR` after the active workflow run's one-run lock refused the first attempt.

### `uv run --frozen pytest` (full suite)

The rows below are derived from this run's single full-gate invocation and its focused `smoke` invocation; no second suite run was bought for this document.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2105 | ✅ Pass (`2105 passed in 39.63s`, gate `suite`, stage `test`) |
| `tests/test_integration_guide_prompt.py tests/test_stage_registry.py tests/test_plan_stages.py tests/test_implement_workflow.py tests/test_inventory.py tests/test_prompt_classification.py tests/test_design_doc.py tests/test_workflow_stages_doc.py` | 341 | ✅ Pass (`341 passed in 24.77s`, gate `smoke`, stage `test`) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `I9` is in `STAGE_IDS`, not in `REPO_OPTIONAL_IDS`, and sits between `I8` and `I7` in `_IMPLEMENT.stages` | ✅ Pass — covered by `tests/test_stage_registry.py` in the focused `smoke` run |
| `validate_stage_list` treats `I9` as core: removal, disable and reorder each report an `ERROR` | ✅ Pass — covered by `tests/test_stage_registry.py` |
| A declared implement list missing `I9` is refused; one placing `I9` between `I8` and `I7` passes | ✅ Pass — covered by `tests/test_plan_stages.py` |
| A fake-stage run plans and dispatches `I9` on the `recorder` agent in position (no real Pi) | ✅ Pass — covered by `tests/test_implement_workflow.py` |
| `write-integration-test-guide.md` is in `REQUIRED_PROMPTS` and resolves from the toolkit | ✅ Pass — covered by `tests/test_inventory.py` and `aidw prompts check` |
| The guide prompt owns only `<branch>/integration-test-guide.md`, names the build results/task prompt/changed files as inputs, requires the five per-scenario fields and two closing sections, and contains no execution instruction | ✅ Pass — covered by `tests/test_integration_guide_prompt.py` |
| `design.md`, `docs/workflow-stages.md` and `docs/migration/prompt-classification.md` carry `I9` in the drift-checked form | ✅ Pass — covered by `tests/test_design_doc.py`, `tests/test_workflow_stages_doc.py` and `tests/test_prompt_classification.py` |
| `aidw implement docs/task-prompts/04-X1.2-prompt.md --dry-run` prints `I9 write-integration-test-guide` between `I8` and `I7` | ✅ Pass — gate `dry-run`: `dry-run complete; Pi not invoked` |

---

## Deviations observed during recording

- **The first `dry-run` gate attempt was refused by the active run's one-run lock** — it recorded `another implement run for 04-X1.2 is still marked running: 20261114T030017Z-04-X1.2-implement` and exited 4. The same command was then run through `aidw gate run` with an isolated, temporary `AIDW_STATE_DIR`, so the lock namespace did not collide with the live workflow; the plan was produced against the same working tree and the gate passed. No implementation, test or traceability file was changed.
- **`aidw doctor` reports two warnings, not one** — the branch's dirty working tree and the missing `.mcp.json` are both expected while the implementation and this results document are still uncommitted; `0 checks failed`.

---

## Non-Goals (NOT implemented)

- ❌ No new agent id — `recorder` is reused (task prompt, "Explicit non-goals").
- ❌ No new `paths.*` key, template, or `parallel_groups` member (task prompt; design §17 `Z6`).
- ❌ No change to `I5`/`I8`/`I7`/`I6`, their prompts, or their artifacts (task prompt, "Explicit non-goals").
- ❌ No `integration-tests.md` prompt, and no stage that *runs* a deployed integration test — §1.3 holds; `I9` writes the recipe, a human runs it (task prompt, "Explicit non-goals").
- ❌ No change to the `prompt`/`review`/`fix`/`approve` workflows — `implement`-only (task prompt, "Explicit non-goals").
- ❌ No running any integration test, gate, cloud, browser or deployed-stack command from the guide stage; no commit/push/PR from it (task prompt, "Explicit non-goals").
