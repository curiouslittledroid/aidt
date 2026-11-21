# Build Results — 05-B1.1: Fix multiple approved follow-ups per iteration

**Branch:** `05-B1.1`
**Date:** 2026-11-21
**Spec:** `design.md` §8.4 (`aidw fix --pr <n>`), §17 (Resolved decisions); roadmap `docs/tasks/05 - Pipeline efficiency.md`, epic B1, task B1.1
**Pull request:** [#177](https://github.com/curiouslittledroid/aidt/pull/177)

## Summary

**Purpose:** Make `aidw fix` process a bounded batch of approved review follow-ups per iteration (`--fix-batch`, default 3), so N approved children cost one fix/test/review cycle instead of N.

| Decision | Why it matters |
|----------|---------------|
| `select --limit <n>` returns an array whenever the flag is explicit (including `--limit 1`); without the flag it keeps the single-object shape. | The JSON contract keys on the flag, not the value, so the loop always gets a batch while the approval round keeps its single-object summary unchanged. |
| Per-issue closing bodies: `{closing_bodies}` is the absolute `<run_dir>/artifacts/iter{N}` directory, with one `closing-body-{issue}.md` per child. | A variable batch cannot carry N positional paths, and a shared per-iteration body could not say which fix it describes. The workflow, never the agent, creates the directory. |
| The run's resolved width is passed to `F1` as a third positional variable, `{fix_batch}`. | Nothing exports the batch width to the stage environment, so leaving it implicit let `--fix-batch 1` be honoured by Python's `select` and silently widened to 3 by the agent's own `select`. |
| `closed_issues` appends one entry per batch issue; `run_closes` still makes one `close` call per entry. | Preserves P1.2's one-issue-per-close and deferred close-after-push ordering: a half-failed close cannot strand an issue half-closed. |
| A failed `F2`/`F3` records no `closed_issues` for the batch. | Fails the whole batch closed — no subset of its children can be closed by a partially successful iteration. |
| The loop and the dry-run preview share one fail-closed batch reader. | An object-shaped `selected` must fail both paths identically; normalising it in the preview would claim a one-child batch the real loop would never fix. |
| Decision id `Z20` records the stale roadmap reference to `Z14`. | `Z14` is already the dry-run-ownership row; `aidw/conventions.md` forbids reusing or renumbering an id, so the next free id is appended and the roadmap's "Z14" is left untouched. |

**Where it fits in the roadmap:** Task B1.1 in epic B1 of `05 - Pipeline efficiency.md`. It builds on 05-P1.1 (verified commit-and-push, `F5`) and 05-P1.2 (deferred close with one close per recorded entry), which remain inputs and are not re-opened. It changes the shape of `fix`'s per-iteration loop and the `review_followup.py select` contract that later fix rounds consume.

**Scope:** Touches the fix workflow, the CLI flag, the GitHub helper, the F1 registry variables, the fixer prompt and its shipped agent guidance, the review-followup script/logic and its README, the design §8.4/§17 docs, the workflow-stage inventory, README operator docs, and the associated tests. It deliberately stops short of batching closes, changing `aidw/workflows/implement.py`'s verdict gate (Q1.1), touching `aidw/workflows/prompt.py`'s revision budget, or adding any new agent id, allowlist entry, required prompt/script, or prompt file.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/05-B1.1-prompt.md` | Created | Task prompt for B1.1 (committed as `b7ad52c`), amended in `99fa7c6` to require the `{fix_batch}` variable and the fixer agent guidance update. |
| `README.md` | Modified | Documents the bounded batch loop, `--fix-batch`, iteration-only `--max-iterations`, and per-issue closing bodies. |
| `agents/fixer/AGENTS.md` | Modified | Rewrites the shipped fixer guidance for a bounded batch, reads the width as `$3`, and requires one closing-body file per issue. |
| `aidw/cli.py` | Modified | Adds `--fix-batch` (default 3), updates `--max-iterations` help, and threads `fix_batch` into `fix_workflow.run`. |
| `aidw/github.py` | Modified | Adds `limit` to `select_followups` and passes it through `build_followup_argv` as `--limit`. |
| `aidw/runner.py` | Modified | Renames the documented fix field `closing_body` to `closing_bodies` and documents `fix_batch`. |
| `aidw/stage_registry.py` | Modified | Changes F1's variables to `("{pr}", "{closing_bodies}", "{fix_batch}")` and updates registry documentation. |
| `aidw/state.py` | Modified | Updates the planned-run placeholder comment to `{closing_bodies}`. |
| `aidw/workflows/fix.py` | Modified | Batch selection, one shared fail-closed batch reader for the loop and dry run, per-issue `closed_issues`, iteration-directory creation, `--fix-batch` validation, and rendering the resolved width into every F1 plan. |
| `design.md` | Modified | §8.4 bounded-batch and `{fix_batch}` wording, §17 `Z20` decision row (noting the stale `Z14`), and the `aidw fix` CLI synopsis. |
| `docs/workflow-stages.md` | Modified | Updates the `fix` stage inventory and F1/F2/F3/loop prose to the batch contract. |
| `prompts/fix-next-review-followup.md` | Modified | Rewrites the fixer instructions for a batch, reads the width as `$3`, posts per-child `start` comments, writes per-issue closing-body files, and verifies the batch. |
| `prompts/scripts/review-followup/README.md` | Modified | Documents `select --limit` and its array-vs-single-object contract. |
| `prompts/scripts/review-followup/logic.py` | Modified | Adds `BatchSelection`, pure `select_available`, `ParsedArgs.limit`, `--limit` parsing, and flag-aware positive-int refusals. |
| `prompts/scripts/review-followup/review_followup.py` | Modified | `cmd_select` emits an array when `--limit` is explicit, keeps the single object when absent, and updates help. |
| `prompts/scripts/review-followup/tests/test_logic.py` | Modified | Adds batch-selection, scan-metadata, flag-shape, and refusal tests. |
| `tests/test_agent_guidance_neutrality.py` | Modified | Adds a fixer-guidance guard requiring the batch wording, `$3`, and one file per issue. |
| `tests/test_design_doc.py` | Modified | Adds §8.4 bounded-batch and §17 `Z20` drift tests. |
| `tests/test_fix_workflow.py` | Modified | Adds batch loop, fail-closed, per-issue close, iteration-directory, dry-run, F1 width, and CLI threading tests. |
| `tests/test_plan_stages.py` | Modified | Re-baselines the F1 variable pins to include `{fix_batch}`. |
| `tests/test_prompt_neutrality.py` | Modified | Adds a guard that the fixer prompt describes the batch and re-baselines its three-positional-variable arity. |
| `tests/test_stage_registry.py` | Modified | Re-baselines the F1 variable and per-issue closing-body pins. |

---

## Verification Results

All commands below were requested through `aidw gate run` with the declared scope
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.
The recorded tree for every gate was `1a12b4b64fd4`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.42ms`; gate `install`, tree `1a12b4b64fd4`, 2026-11-21T00:30:43Z, stage `record-implementation-results`) |
| Build | `uv build --out-dir <mktemp-dir>` | ✅ Pass (built `aidt-1.5.0.tar.gz` and `aidt-1.5.0-py3-none-any.whl`; gate `build`, tree `1a12b4b64fd4`, 2026-11-21T00:30:44Z, stage `record-implementation-results`) |
| Test | `uv run --frozen pytest` | ✅ Pass (`2505 passed in 46.90s`) — **cited from `aidw gate` reuse**: gate `suite`, tree `1a12b4b64fd4`, recorded 2026-11-21T00:28:55Z by stage `test`; this stage's request reused it without re-running |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`23 checks: 0 failed, 2 warning(s)`) — **cited from `aidw gate` reuse**: gate `doctor`, tree `1a12b4b64fd4`, recorded 2026-11-21T00:29:00Z by stage `test`; this stage's request reused it without re-running |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`; gate `agents`, tree `1a12b4b64fd4`, 2026-11-21T00:30:49Z, stage `record-implementation-results`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (`resolved repo prompts: 0 error(s), 0 warning(s)`; gate `prompts`, tree `1a12b4b64fd4`, 2026-11-21T00:30:50Z, stage `record-implementation-results`) |
| Whitespace | `git diff --check` | ✅ Pass (no whitespace errors) |
| Lint | — | **unverified** (this repository configures no linter, formatter, or type-checker; `AGENTS.md` says `pytest` is the only verification, so there is no lint command to run) |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2505 | ✅ Pass (`2505 passed in 46.90s`; gate `suite`, tree `1a12b4b64fd4`, recorded 2026-11-21T00:28:55Z by stage `test`) |
| Changed-file subsets | — | **unverified** (the single `-q` full-suite run does not report per-file counts; the suite was not re-run because the same-tree gate was reused) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Batch select purity and JSON shape (`prompts/scripts/review-followup/tests/test_logic.py`) | ✅ Pass (all tests in this file passed within the full-suite run) |
| Batch loop, per-issue close accounting, fail-closed batch, CLI flag, F1 width, dry-run (`tests/test_fix_workflow.py`) | ✅ Pass (all tests in this file passed within the full-suite run) |
| Dry-run malformed-select rejection (`tests/test_fix_workflow.py::test_dry_run_rejects_object_shaped_select_results`) | ✅ Pass (included in the full-suite run; the preview now shares the loop's fail-closed batch reader) |
| Design §8.4/§17 drift (`tests/test_design_doc.py`) | ✅ Pass (all tests in this file passed within the full-suite run) |
| F1 variable re-baseline (`tests/test_stage_registry.py`, `tests/test_plan_stages.py`) | ✅ Pass (all tests in these files passed within the full-suite run) |
| Fixer prompt neutrality and F1 arity (`tests/test_prompt_neutrality.py`) | ✅ Pass (all tests in this file passed within the full-suite run) |
| Fixer agent guidance matches the bounded-batch contract (`tests/test_agent_guidance_neutrality.py::test_fixer_guidance_matches_the_bounded_batch_contract`) | ✅ Pass (included in the full-suite run; the guidance names `$3` and keeps the batch wording) |
| `aidw fix --pr <n> --dry-run --fix-batch 3` against a live PR | **unverified** (no PR, no GitHub credentials or live approved children were used in this recording stage; the dry-run contract is covered by the automated tests only) |

---

## Deviations observed during recording

- **The suite and doctor gates were reused, not re-run.** The change set matched the tree an earlier `test` stage had already gated, so `aidw gate run suite` and `aidw gate run doctor` printed the recorded same-tree outcomes above and exited without re-running. Both rows name their origin (gate key, tree, stage, timestamp) as required.
- **The task prompt carries a late amendment.** Commit `99fa7c6` adds the amendment requiring `{fix_batch}` as F1's third variable and `agents/fixer/AGENTS.md` in scope. Both the registry/prompt and the shipped fixer guidance reflect it, and the guidance guard passes.
- **No lint/build gate is named by `AGENTS.md`.** `AGENTS.md` names `uv sync --frozen`, `pytest`, `aidw doctor`, `aidw agents validate --strict` and `aidw prompts check`, and says pytest is the only verification. The template's build row was run as `uv build`; no lint command exists, so the lint row is recorded as unverified rather than invented.
- **No pull request exists for this branch.** `gh pr view 05-B1.1` returned "no pull requests found for branch", so the document records the not-yet-opened note instead of a number.

---

## Non-Goals (NOT implemented)

- ❌ Re-opening P1.1's F5 commit-and-push or P1.2's deferred close / close-after-push ordering, the one-close-per-entry rule, or the D3 commit table (task prompt, "Explicit non-goals").
- ❌ Touching Q1.1 / `aidw/workflows/implement.py`'s tester-`Fail` verdict gate (task prompt, "Explicit non-goals").
- ❌ Touching the prompt workflow's own "fix batch" / `aidw/workflows/prompt.py`'s revision budget (task prompt, "Explicit non-goals").
- ❌ Adding a new agent id, allowlist entry, `REQUIRED_PROMPTS`/`REQUIRED_SCRIPTS` entry, or prompt file — the fixer prompt is edited in place (task prompt, "Explicit non-goals").
- ❌ Auto-closing or auto-reopening a failed batch's children — they stay `OPEN` with `Status: in progress`, and the existing `start --issue` resume path is the recovery (task prompt, "Traps / prior review findings").
- ❌ Committing, pushing, or opening a pull request — the `/pr` stage owns delivery.
