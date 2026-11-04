# Build Results — 00-E4.8: Run each whole-repo gate once per tree

**Branch:** `00-E4.8`
**Date:** 2026-11-04
**Spec:** `docs/migration/EXTRACTION.md` §3.4 (One gate, one tree, one run), §6 (E4.8), §10 (R16, R18); `design.md` §15

## Summary

**Purpose:** Finish the two remaining E4.8 pieces: put the `aidw gate run` idiom in
`prompts/fix-next-review-followup.md` §6 and prove end-to-end, through the CLI, that a run's later
stage cites the suite its earlier stage bought for the same tree and re-runs after a source change
outside the declared scope.

| Decision | Why it matters |
|----------|---------------|
| The fix prompt uses `pr.md`'s keys (`build`, `lint`, `smoke`) and its four-path `--ignore` scope | The fix-chain `test` stage (F2, `test.md`) can cite the fix stage's outcomes only when key, command and scope line up. `smoke` names the package-scoped test, so it can never match a full-repo `suite` command string. |
| §5's red-before/green-after invocation stays a bare command | It is meant to fail; recording a `failed` gate outcome would add noise to `aidw gate list` without ever being cited. |
| The end-to-end test's side effect is a counter **outside** the repo | A write inside the repo changes `tree_identity`, which would defeat the reuse the test exists to prove. The counter proves "no second run" rather than inferring it from output text. |
| The test asserts the recorded origin rather than a transcribed number | `run_gate` cites the first stage that passed for the tree; asserting `stage == "test"`, one stored outcome and its real summary/origin fields is what distinguishes reuse from a second run. |
| No new schema, state vocabulary or CLI surface | The landed gate machinery already expresses the contract; only the prompt and the proof were missing. |

**Where it fits in the roadmap:** E4.8 completes the gate-reuse work that closes the E3/E4 extraction
phase. It depends on the landed `aidw gate run|list` primitive, content tree identity (R16), declared
`--ignore` scope (R18), run-state gate outcomes and the `AIDW_RUN_ID`/`AIDW_STAGE` stage environment.
It leaves E7.2's de-naming of `pr.md`'s stack-keyed table and default scope (R17/R18) and E8.2's
toolkit/schema identity fields to their own tasks.

**Scope:** Edits only `prompts/fix-next-review-followup.md` and `tests/test_verification.py` beyond
the task prompt. It deliberately stops short of re-implementing or refactoring the landed gate
machinery, touching the four implement-chain prompts, editing `pr.md`'s command table, relocating the
scope list into target-repo conventions, or adding E8.2 identity fields.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E4.8-prompt.md` | Created | Task prompt added by the prompt-authoring stage (already committed on the branch). |
| `docs/implementation-results/00-E4.8/build-results.md` | Created | This recording document. |
| `prompts/fix-next-review-followup.md` | Modified | §6 runs each verification command through `aidw gate run` with `pr.md`'s keys and four-path scope, states the same-run line-up/citation rule, and keeps §5's red-before proof bare. |
| `tests/test_verification.py` | Modified | Adds one end-to-end reuse test: `test` gates, `record` cites the same tree after a scoped write, and a source edit outside scope forces a fresh run. |

---

## Verification Results

Every gate command was run once, through `aidw gate run`, with the same scope —
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` —
for tree `5c13eeb6fbc0`, stage `record-implementation-results`, on 2026-11-04. The rows below report
this run's own outcomes; no subset was re-run to obtain a count. `uv sync --frozen` and
`git diff --check` were run directly because neither is a gate.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 15 packages in 0.67ms`) |
| Build | `uv build --out-dir <tmp>` | ✅ Pass (gate `build`, tree `5c13eeb6fbc0`, 2026-11-04T22:57:47Z: `Successfully built .../aidt-0.1.0-py3-none-any.whl`) |
| Test | `uv run --frozen pytest` | ✅ Pass (gate `suite`, tree `5c13eeb6fbc0`, 2026-11-04T22:57:45Z: `1272 passed in 23.61s`) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (gate `doctor`, tree `5c13eeb6fbc0`, 2026-11-04T22:57:50Z: `19 checks: 0 failed, 2 warning(s)` — dirty working tree and absent `.mcp.json`, both expected mid-run) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (gate `agents`, tree `5c13eeb6fbc0`, 2026-11-04T22:57:52Z: `11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (gate `prompts`, tree `5c13eeb6fbc0`, 2026-11-04T22:57:54Z: `prompts check: 0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (no output) |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1272 | ✅ Pass (`1272 passed in 23.61s`) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| End-to-end reuse through the CLI: stage `test` records `suite`, stage `record` cites it after a write inside `docs/implementation-results` without a second run, the origin stays `test`, and a source change outside the scope re-runs | ✅ Covered by the full-suite run above (`tests/test_verification.py::test_a_run_cites_the_suite_across_the_record_stage_and_reruns_after_a_code_edit`) |
| Existing `tests/test_verification.py` remains green (the new test extends it) | ✅ Covered by the full-suite run above |
| `fix-next-review-followup.md` §6 uses `aidw gate run` with `pr.md`'s keys/scope and §5 stays a bare command | ✅ `prompts check` passed with `0 error(s), 0 warning(s)`; reviewed in the diff |
| Exact `AGENTS.md` gate set (`uv sync --frozen`, `uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents validate --strict`, `uv run aidw prompts check`) | ✅ All five passed as recorded above |

---

## Deviations observed during recording

- **The generic record prompt names a pnpm gate set, but this repo's stack is Python/uv.** Per
  `AGENTS.md` and `prompts/pr.md` ("take them from the target repo, not from this prompt"), the
  install/build/test rows are `uv sync --frozen`, `uv build` and `uv run --frozen pytest`. No lint
  gate was run because the repo configures no linter.
- **`uv build` writes to a fresh `$(mktemp -d)` directory** rather than the working tree, leaving no
  artifacts behind in the gated content.

---

## Non-Goals (NOT implemented)

- ❌ E7.2's de-naming of `pr.md`'s stack-keyed command table and relocation of the default `--ignore`
  path list into target-repo conventions (R17/R18) — separate task, `pr.md` untouched (task prompt,
  explicit non-goals).
- ❌ E8.2's `toolkit_version`/`schema_version`/config-hash fields in `state.json` — separate task; the
  gate identity remains content-based (R16) (task prompt, explicit non-goals).
- ❌ Re-implementing or refactoring the landed gate machinery (`verification.py`, `state.py`, the
  `cli.py` gate command, `runner.py` environment variables) — only the prompt and its proof were
  missing, and no reuse bug forced a fix (task prompt, explicit non-goals).
- ❌ Editing the four implement-chain prompts' gate idiom, `aidw/inventory.py`, or the fix prompt's
  frontmatter — already landed / out of scope (task prompt, explicit non-goals).
- ❌ No PR opened and nothing committed by the recording stage (`prompts/pr.md` owns delivery).
