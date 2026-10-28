# Build Results — 02-L6.1: Pin the new loop contract in tests

**Branch:** `02-L6.1`
**Date:** 2026-10-28
**Spec:** `design.md` §15 (testing strategy) / §8.1 (prompt workflow) / §14 (exit codes), `docs/tasks/02 - Prompt loop integrity.md` (L6.1 and the L1.1–L5.3 entries it pins), `AGENTS.md` (Gates and Tests)

## Summary

**Purpose:** Close the final loop-integrity evidence gap by adding the named E1.6-shape fixture
(an unticked predecessor plus a base branch behind `origin`) and confirming that the already-landed
L1.1–L5.3 behaviours each fail at least one test when removed.

| Decision | Why it matters |
|----------|---------------|
| Compose the E1.6 fixture from `_origin_and_clone` + `_advance_origin` + `ROADMAP_INCOMPLETE_PREDECESSOR` | Reuses the existing deterministic helpers instead of inventing another repo-building path; the fixture is local, network-free and does not touch the real `runs/` tree. |
| Assert the *ordering refusal* wins while `origin/main` is genuinely ahead | The local incomplete-predecessor refusal must short-circuit before the network fetch; otherwise the combined E1.6 shape could silently spend a fetch and report the wrong refusal first. |
| Add one fixture/test rather than rewrite the module | Requirements 2–7 were already pinned by the per-task L1.1–L5.3 tests; the audit found only the combined E1.6 shape missing, so duplicating or restructuring would be churn. |
| Keep the delayed claims as rendered-prompt assertions | The prompt-content precedent (`render_prompt_file`) proves instruction clauses without invoking a real Pi model, preserving design §15's no-live-model rule. |

**Where it fits in the roadmap:** Phase 02 ("Prompt loop integrity"), Epic L6 ("Evidence and
close-out"). It depends on the completed L1.1–L5.3 workflow behaviours and their per-task tests, and
it precedes L6.2 (design §17 decision log, provisional §8.1 amendment, re-baselining
`00 - Extraction.md`).

**Scope:** Adds only
`_e16_stale_base_with_unticked_predecessor` and
`test_l61_e16_fixture_ordering_refusal_precedes_the_fetch` to
`tests/test_prompt_workflow.py`, plus the roadmap tick. It deliberately stops short of changing
workflow or prompt behaviour, renaming/splitting the test module, and starting L6.2.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L6.1-prompt.md` | Created | Task prompt defining the L6.1 audit/gap-fill requirements, traps and non-goals (committed on the branch). |
| `tests/test_prompt_workflow.py` | Modified | Added the E1.6-shape fixture helper and `test_l61_e16_fixture_ordering_refusal_precedes_the_fetch`, proving exit 4 names the predecessor, zero fetch calls occur, no stage runs, and no run directory/branch/prompt is created. |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified | Flipped the L6.1 checkbox to done (traceability update left uncommitted). |

---

## Verification Results

Repo gates are the ones `AGENTS.md` names under "Gates — run exactly these, and only these", plus
`uv build` because `prompts/pr.md` lists it for the `pyproject.toml` / `uv.lock` stack. Each runnable
gate was run through `aidw gate run <key> -- <command>` where a gate key applies, with the shared
scope
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`,
against tree `81b0fd880400` in run `20261028T110439Z-02-L6.1-implement`, stage
`record-implementation-results`. Outcomes below are from this run.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 2ms` |
| Build | `uv build --out-dir <mktemp -d>` | ✅ built sdist + wheel `aidt-0.1.0` — gate `build`, tree `81b0fd880400`, 2026-10-28T11:50:07Z |
| Test | `env -u AIDW_RUN_ID -u AIDW_STAGE uv run --frozen pytest` | ✅ `678 passed in 91.47s (0:01:31)` — gate `suite`, tree `81b0fd880400`, 2026-10-28T11:49:56Z |
| Doctor | `env -u AIDW_RUN_ID -u AIDW_STAGE uv run --frozen aidw doctor` | ✅ `14 checks: 0 failed, 2 warning(s)` (missing `.mcp.json`, dirty working tree) |
| Agent configs | `env -u AIDW_RUN_ID -u AIDW_STAGE uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` |
| Prompts check | `env -u AIDW_RUN_ID -u AIDW_STAGE uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` |
| Whitespace | `git diff --check` | ✅ no output (exit 0) |
| Lint (pnpm) | `pnpm -r lint` | **unverified — not applicable**: no `pnpm-workspace.yaml` or `package.json` exists in this `pyproject.toml`/`uv.lock` toolkit repo; no lint gate is configured (`design.md` §15). |
| Build (pnpm) | `pnpm -r build` | **unverified — not applicable**: same reason; the Python build gate (`uv build`) is run above. |
| Test (pnpm) | `pnpm -r test` | **unverified — not applicable**: same reason; the Python test gate (`uv run --frozen pytest`) is run above. |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 678 | ✅ Pass (`678 passed in 91.47s (0:01:31)`) |

The single full-suite invocation above includes the new L6.1 test; no second full-suite run was made
to obtain the count. The first attempt through the gate inherited the agent shell's
`AIDW_RUN_ID`/`AIDW_STAGE`, failed the two pre-existing `tests/test_verification.py` gate-recording
tests (`2 failed, 676 passed`), and is described under Deviations; the passing invocation cleared
those variables for the child command while the outer `aidw gate run` still recorded the outcome.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run --frozen pytest tests/test_prompt_workflow.py` | ✅ `126 passed in 45.85s` — gate `prompt-workflow`, tree `81b0fd880400`, 2026-10-28T11:50:57Z |
| Full suite is green | ✅ `678 passed` — gate `suite`, tree `81b0fd880400`, 2026-10-28T11:49:56Z |
| Per-behaviour delete→fail pass | ✅ 15/15 behaviours reported as `FAILED-AS-EXPECTED` by the `/impliment-task` and `/test` stages of this same run (L1.1 behind/diverged, L1.2 incomplete, the L1.1/L1.2 precedence pair, L1.3 blocked, L3.3 snapshots, L3.4 reconcile, L4.1 terminal review, L2.3 delta brief, L4.2 recording, and the L2.1/L2.2/L3.1/L3.2/L5.1 rendered-prompt clauses). Not re-executed by this recording stage because it requires temporarily mutating implementation source, which `/record` must not do. |
| Fetch path is local and no real Pi model is invoked | ✅ the module's fetch tests use local bare origins and monkeypatched `git.subprocess.run`; the suite is test-only and invokes no live model |
| `pnpm srd:validate` / `srd:check-references` / `srd:matrix-check` / `srd:report` | **unverified — not applicable**: no `pnpm-workspace.yaml`, `package.json`, `docs/rules-coverage/catalog.json` or vector matrix exists in this toolkit repo. |
| `pnpm --filter infra cdk synth -c env=dev` | **unverified — not applicable**: no `infra/` package or CDK workspace exists in this repo. |
| Deployed integration / matrix completeness test | **unverified — not applicable**: no TypeScript integration workspace or matrix fixture exists. |

---

## Deviations observed during recording

- **The task-prompt template's pnpm/SRD gates do not apply to this repo.** `prompts/record-implementation-results.md`
  ships pnpm examples, but `AGENTS.md` names the uv commands above and `prompts/pr.md` says to take
  gate commands from the target repo. Those rows are marked unverified/not applicable, not passing.
- **The pytest gate runs under `env -u AIDW_RUN_ID -u AIDW_STAGE`.** Two pre-existing
  `tests/test_verification.py` gate-recording tests read the harness's ambient stage identity and fail
  when it leaks into the child process (first attempt: `2 failed, 676 passed`). The suite was re-run
  with the ambient identity cleared for the child, producing `678 passed`; the outer `aidw gate run`
  still recorded the outcome into this run. No test or workflow code was changed by this stage.
- **The change set spans a commit and the working tree.** The branch carries the committed L6.1 task
  prompt (`docs/task-prompts/02-L6.1-prompt.md`, commit `c4bf6a6`); `tests/test_prompt_workflow.py`
  and the L6.1 roadmap checkbox are uncommitted. This stage modified none of them.

---

## Non-Goals (NOT implemented)

- ❌ L6.2 (design.md §17 decision log, provisional §8.1 amendment, re-baselining `00 - Extraction.md`) — it is the next task and was not started here.
- ❌ Any workflow or prompt behaviour change — this task is test-only; a gap would be reported rather than implemented inside a test task.
- ❌ Renaming or splitting `tests/test_prompt_workflow.py` into a new module — the roadmap names it and pytest `testpaths` already covers `tests/`.
- ❌ Any target-repo AWS/SRD/matrix/credentials or TypeScript/pnpm conventions from `prompts/task-prompt.md` — they do not apply to this toolkit-repo task.
- ❌ No commit, push, or PR opened by this stage.
