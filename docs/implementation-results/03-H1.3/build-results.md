# Build Results — 03-H1.3: Give a blocked run a forward path

**Branch:** `03-H1.3`
**Date:** 2026-11-10
**Spec:** `design.md` §8.1, §9.2, §9.3, §9.4, §14, §17; `docs/tasks/03 - Stage resilience.md` H1.3

## Summary

**Purpose:** A review-loop-blocked `aidw prompt` run can now be continued in its own run id and worktree — `--resume` grants one further review cycle and `--from-prompt <path>` re-runs the review loop over operator-supplied content — instead of being refused with no forward path.

| Decision | Why it matters |
|----------|---------------|
| Continuation is scoped to the **shape of the block**: only a latest `approve-task-prompt` gate that is `denied` with mechanism `review-loop` continues through `--resume`. | An author-`blocked:` run has no review findings and a human-gate denial's review already approved; routing either into the fix cycle would re-author or re-commit silently wrong work. Both keep H1.2's exit-3 refusal; `--from-prompt` is their forward path. |
| `--resume` re-runs the **existing loop under an extended budget**, `state.task.effective_max_revisions` = recorded review count + 1, not a new stage list or a larger default budget. | The added `task-review-{N+1}` is the terminal review under the extended budget, so L4.1 holds; the terminal review's findings finally get their fix batch and reconcile, and each further `--resume` is an explicit operator decision granting exactly one more round. |
| The confirmation-point budget guard consults the budget the loop will actually run under — effective for a continuation resume, resolved for a failed-run resume, no recorded rounds for `--from-prompt`. | A re-blocked run legitimately has more recorded fix rounds than the resolved allowance; leaving the guard on the resolved value would refuse the second `--resume` with exit 2 before the continuation could run. |
| `--from-prompt <path>` copies the supplied bytes onto the canonical task-prompt path, records `state.task.from_prompt = {"path", "hash": "sha256:<hex>"}`, and forces the loop from `task-review-1` with an internal position bound. | The canonical path keeps `rel`, the evidence bundle and `_commit_reviewed_prompt` working; the position bound reviews the new content instead of re-parsing the old succeeded reviews as stale findings, without changing the `--from` grammar. A **dirty** canonical path refuses exit 4 before copying, so a blocked run's own uncommitted edits are never overwritten (design §13). |
| Each continuation's gate `detail` reports the budget it actually ran under — effective for the `--resume` fix cycle, resolved for `--from-prompt` — and verdict-bearing exits keep `review-loop` while the shared post-loop gate records `decide`'s mechanism. | The original `denied` gate stays in `state.gates`, the continuation appends its own record, and the extension (or lack of one) is visible rather than inferred. A gate decision is never re-asked unless it was denied. |
| A blocked continuation whose worktree is missing refuses exit 4 naming the run, the missing path and the re-author command; `--dry-run` never takes over a run. | Never silently re-author, and keep the dry-run baseline as the integration seam: a dry run over any blocked shape plans fresh, copies nothing and mints one new run record. |

**Where it fits in the roadmap:** H1.3 is the third task in Epic H1 (phase 03, stage resilience). It builds directly on H1.2's failed-run resume machinery and H0.1's persisted gate outcomes, and completes the "blocked run has no forward path" gap H1.2 deliberately left open. It is followed by H2.1 (delta-brief size budget) and H3.1/H3.2/H3.3 (roadmap-tick stage) in the same phase.

**Scope:** `aidw/cli.py` adds `--from-prompt <path>` to `prompt` and threads it into `run`; `aidw/workflows/prompt.py` owns block-shape routing, the effective budget, the continuation loop, `--from-prompt` copy/provenance/preflights, the dirty-path guard, the missing-worktree refusal and the continuation gate records; `tests/test_prompt_workflow.py` proves each contract with fake stages. `design.md` amends §8.1's stale "no gate is recorded" wording, §9.2's free-form `task` note, §9.4's blocked-run resumability, §14's `aidw prompt` flags and §17's G2/W1 decisions; the H1.3 roadmap box is ticked. The task deliberately stops short of a delta-brief size budget, roadmap ticking, `aidw implement`/`aidw fix` resumability, a larger default review budget, auto-unblocking, and `--from-prompt` for failed runs.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/implementation-results/03-H1.3/build-results.md` | Created | This results document. |
| `docs/task-prompts/03-H1.3-prompt.md` | Created | Task prompt for H1.3 (spec citations, requirements, tests, explicit non-goals). |
| `aidw/cli.py` | Modified | Adds `--from-prompt <path>` to `aidw prompt` and passes it to `prompt_workflow.run`. |
| `aidw/workflows/prompt.py` | Modified | Block-shape routing (`review_loop_block`), effective budget (`_recorded_review_count`/`effective_max_revisions`), continuation loop, `--from-prompt` copy/provenance/preflights and dirty-path guard, missing-worktree refusal, per-route gate budget/mechanism, and resumed dry-run composition. |
| `tests/test_prompt_workflow.py` | Modified | Adds 22 fake-stage tests (and re-baselines the blocked dry-run test) for the continuation, second extension, verdict/approval gates, `--from-prompt`, copy guard, missing worktree, gate history, scoped-out shapes, dry-run matrix and CLI wiring. |
| `design.md` | Modified | §8.1 terminal-review gate recording and blocked forward path, §9.2 `state.task` continuation keys, §9.4 blocked-run resumability, §14 `--from-prompt`, §17 G2 amendment and W1 decision row. |
| `docs/tasks/03 - Stage resilience.md` | Modified | Ticks H1.3. |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.84ms`; exit 0) |
| Build | `aidw gate run build --ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv build --out-dir "$(mktemp -d)"` | ✅ Pass (`aidt-1.1.1.tar.gz` and `aidt-1.1.1-py3-none-any.whl` built; gate `build` passed for tree `0bb06921c8a5` at `2026-11-10T10:14:20Z` by stage `record-implementation-results`) |
| Test | `aidw gate run suite --ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv run --frozen pytest` | ✅ Pass (`reused: gate 'suite' passed for tree 0bb06921c8a5 at 2026-11-10T10:11:27Z by stage 'update-traceability'` — `1921 passed in 128.78s (0:02:08)`; cited rather than re-run because the tree and declared scope match this record run's) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`; warnings: dirty working tree, missing `.mcp.json`) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (toolkit defaults `0 error(s), 0 warning(s)`; resolved repo prompts `0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (no output; exit 0) |
| Lint | — | ⚠️ **unverified** (the repository configures no lint command; `AGENTS.md` names only pytest, `doctor`, `agents validate --strict` and `prompts check`, and `design.md` §15 says no linter is configured) |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1,921 | ✅ Pass (`1921 passed in 128.78s (0:02:08)`, gate `suite` for tree `0bb06921c8a5` recorded by stage `update-traceability` at `2026-11-10T10:11:27Z`) |
| `tests/test_prompt_workflow.py` (new H1.3 tests) | 22 new functions | ✅ Pass (included in the 1,921-test full suite; the reused gate emits no per-file summary, so the subset was not re-run for its own count) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Review-loop continuation: same run id, no `task-prompt`, three skipped reviews then `task-review-fixes-3-*` + `task-review-reconcile-3` + `task-review-4`, `effective_max_revisions == 4`: `test_resume_continues_a_terminal_request_changes_block_with_one_extra_review` | ✅ Pass (included in the 1,921-test full suite) |
| Second `--resume` on a re-blocked run is not refused by the H1.2 budget guard and gets one more round under `effective_max_revisions == 5`: `test_a_second_resume_on_a_reblocked_run_gets_one_more_round` | ✅ Pass (included in the full suite) |
| Continuation verdicts: approval commits and clears `resume`; residual `Request changes`/`Blocked` exits 3 with a review last and no commit: `test_a_continuation_that_still_requests_changes_blocks_with_a_review_last`, `test_a_blocked_verdict_continuation_fixes_reconciles_and_reviews` | ✅ Pass (included in the full suite) |
| `--require-approval` continuation asks the denied gate exactly once; denial records the continuation's own gate (mechanism from `decide`, not `review-loop`) and blocks, `--yes` commits: `test_a_continuation_approval_gate_is_asked_once_and_can_block`, `test_a_continuation_approval_gate_passes_once_with_yes` | ✅ Pass (included in the full suite) |
| Gate history keeps the original `denied` `review-loop` gate and the continuation's distinguishable `approved` gate with the extended budget: `test_resume_continues_a_terminal_request_changes_block_with_one_extra_review` | ✅ Pass (included in the full suite) |
| `--from-prompt` alone: locate/lock/reuse, supplied bytes and `sha256:<hex>` recorded, loop from `task-review-1`, no author, resolved budget past a stale effective one, prior records kept: `test_from_prompt_alone_continues_a_blocked_run_from_review_1`, `test_from_prompt_runs_at_the_resolved_budget_past_a_stale_effective_one` | ✅ Pass (included in the full suite) |
| `--from-prompt` semantics: forward path for an author-blocked run, precedence over `--resume`, control preflights applied and run-scoped preflights skipped, blocked-run-only with `--from` rejected before side effects: `test_from_prompt_is_an_author_blocked_runs_forward_path`, `test_from_prompt_takes_precedence_over_the_resume_fix_cycle`, `test_from_prompt_applies_control_preflights_but_skips_run_scoped_preflights`, `test_from_prompt_requires_a_blocked_run_and_rejects_from` | ✅ Pass (included in the full suite) |
| Dirty canonical prompt path refuses exit 4 before copying and leaves the bytes untouched: `test_from_prompt_refuses_a_dirty_canonical_path` | ✅ Pass (included in the full suite) |
| Missing worktree on a blocked continuation refuses exit 4 naming run, path and re-author command, with `state.json` unchanged: `test_a_blocked_continuation_without_its_worktree_refuses_and_never_re_authors` | ✅ Pass (included in the full suite) |
| Scoped-out shapes still refuse exit 3 and mutate nothing: `test_blocked_resume_refuses_with_the_last_reviews_verdict`, `test_blocked_resume_names_the_authors_recorded_block`, `test_blocked_resume_names_a_gate_denial_mechanism` | ✅ Pass (included in the full suite) |
| Worktree lock is held across and released after the continuation: `test_a_blocked_continuation_releases_its_worktree_lock` | ✅ Pass (included in the full suite) |
| Dry-run matrix — review-loop and `--from-prompt` plan fresh and copy nothing, scoped-out author-block/human-gate refusals still apply, missing supplied file exits 2: `test_dry_run_with_resume_over_a_review_loop_block_plans_fresh`, `test_dry_run_from_prompt_plans_fresh_and_copies_nothing`, `test_dry_run_with_resume_over_an_author_blocked_run_still_refuses`, `test_dry_run_with_resume_over_a_human_gate_denial_still_refuses`, `test_dry_run_from_prompt_with_a_missing_file_is_a_usage_error` | ✅ Pass (included in the full suite) |
| CLI wiring and the one-review extension property: `test_prompt_cli_forwards_from_prompt`, `test_continuation_extension_is_exactly_one_review_property` | ✅ Pass (included in the full suite) |
| A real model-backed continuation (a live Pi run resuming after a real block) | ⚠️ **unverified** (no test in this repository may invoke a real Pi model — `AGENTS.md` §Tests, `design.md` §15; the routes are proven against fake stages) |

---

## Deviations observed during recording

- **No lint gate was available** — this repository has no configured linter or formatter (`AGENTS.md` §Tests, `design.md` §15), so the row is marked unverified rather than substituting an invented command.
- **The suite gate was cited, not re-run** — `aidw gate run suite` reported that stage `update-traceability` of this run had already passed `suite` for tree `0bb06921c8a5` with the same declared scope (`2026-11-10T10:11:27Z`, `1921 passed in 128.78s (0:02:08)`), which is this run's own recorded observation of the same content. Per-file and per-test counts were therefore not re-run; the task-specific rows cite inclusion in that single full-suite invocation.
- **Implementation changes were still uncommitted at record time** — the recorded change set is the working tree relative to `main`, as the recording stage directs; the task prompt was committed earlier on this branch.

---

## Non-Goals (NOT implemented)

- ❌ H2.1 delta-brief size budget — the continuation re-sends the same prompts; it does not shrink them (task prompt explicit non-goals).
- ❌ H3.1/H3.2/H3.3 roadmap-tick stage and its evidence condition — no roadmap checkbox work here (task prompt explicit non-goals).
- ❌ `aidw implement --resume` and `aidw fix` resumability — unchanged; this task touches only the `prompt` workflow (task prompt explicit non-goals).
- ❌ A larger default review budget, an auto-unblock, or treating the terminal review's findings as "known and recorded" (L4.2's deleted `assumed_ok` path) — the continuation is an explicit operator `--resume`/`--from-prompt` action on one recorded run (task prompt explicit non-goals).
- ❌ `--from-prompt` for **failed** runs — out of scope; failed runs already have `--resume`/`--from` (task prompt explicit non-goals).
- ❌ No PR was opened, no commit was made, and no implementation, test or traceability file was changed by this recording stage.
