# Build Results — 03-H1.2: `aidw prompt` resumes instead of re-authoring

**Branch:** `03-H1.2`
**Date:** 2026-11-09
**Spec:** `design.md` §8.1, §9.4, §14, §17; `docs/tasks/03 - Stage resilience.md` H1.2; `docs/migration/EXTRACTION.md` §3.2

## Summary

**Purpose:** A failed `aidw prompt` run can now be continued at the stage that failed — in its own worktree and under its own run id — instead of throwing away every completed stage and re-authoring from scratch.

| Decision | Why it matters |
|----------|---------------|
| Branch setup **locates** the task worktree and creates one only when none exists (`git.add_worktree` returns `None` for an already-checked-out branch). | The old unconditional add refused every re-run and every resume. A resume reuses the failed run's own tree even when dirty — those partial edits are the state it continues from. |
| A **fresh** re-run reuses a located worktree only when `git status --porcelain` is empty; otherwise it refuses exit 4 printing `aidw worktree remove <branch> --force` and `git -C <base> branch -D <branch>`. | A truncated fixer can leave partial prompt edits. Design §13 keeps the discard operator-owned: AIDT prints the commands, never `rm -rf` or `reset --hard`. The same message covers a leftover branch. |
| Loop state is **reconstructed from records, never re-derived by re-running**: `review_index`/`revisions` from stage names, each prior round's `FixBatch` re-parsed from that round's recorded review `.out.txt` with `parse_review_findings`/`partition_findings`. | Stage names carry only counts, and `_expand_prompt_loop` rejects anything but a real `FixBatch`. Reconciles each rebuilt batch against the recorded `task-review-fixes-*` names and refuses (exit 4) if a recorded stage cannot be reproduced. |
| `baseline_prompt` (the pre-fix snapshot) is not persisted, so a resumed round passes `_brief_diff(baseline=None, …)`. | The brief names the diff unavailable instead of fabricating a baseline from the post-fix prompt. |
| Every `return 1` site stamps `state.resume = {"next_stage": <stage>}` via `_mark_failed`; success clears it to `None`; a block records the empty dict (`_mark_blocked`). | The key is what resume reads back. §9.3 sets `next_stage` only on failure, so a resumed-then-blocked run must not look resumable. |
| A latest run still marked `running` refuses a fresh run exit 4 naming the run id; `--resume` takes that record over as its own (same run id, no `create_run`). | A crash releases the lock but leaves the record; without this a clean-tree re-run would mint a second run id for a run that is still in flight. |
| A `blocked` run's `--resume` refuses exit 3 naming the recorded reason: the author's `blocked:` line, else the last recorded review's verdict/findings plus the denied gate's `mechanism`. | Exit 3 keeps §14's "workflow blocked (needs human)" distinct from a usage error (2) and a preflight refusal (4), and the refusal precedes every write path so nothing is mutated. |
| `--from` validates against the loop's stage-name grammar bounded by the resolved `max_revisions` before any side effect (exit 2). Applied **on encounter**, so a grammar-valid name absent from this run's plan degrades as `implement` does. | A typo'd name can never leave a run directory. With `--resume` the override takes precedence over `next_stage` in the same run id; alone it is a fresh run. |
| A `--dry-run` is always the fresh author + `task-review-1` baseline (implement's `resume and not dry_run` guard); `--from` is still validated and the still-running/blocked refusals are not dry-run-gated. | Mirrors `implement.py` exactly and keeps the plain dry-run plan unchanged as the integration seam. |

**Where it fits in the roadmap:** H1.2 is the second task in Epic H1 (phase 03, stage resilience). It depends on E2.4/E2.5 (AIDT owns branch creation), H0.1 (gate outcomes survive the resume's `save()`) and H1.1 (a stage survives a bad round). H1.3 (blocked-run continuation, `--from-prompt`) builds directly on it, and H2.1 (delta-brief budget) and H3.1 (roadmap tick) follow in the same phase.

**Scope:** `aidw/cli.py` adds `--resume`/`--from` to `prompt` and fixes the `runs resume` hint; `aidw/workflows/prompt.py` owns the resume lookup, confirmation, blocked refusal, `--from` grammar, worktree reuse/refusals, loop reconstruction and `state.resume` lifecycle; `tests/test_prompt_workflow.py` proves each contract with fake stages. `design.md` amends §8.1's branch-setup wording, §9.4's resumability wording and §14's `aidw prompt` line, and records the decision as §17 V1; the H1.2 roadmap box is ticked. The task deliberately stops short of a blocked run's forward path (H1.3), a delta-brief size budget (H2.1) and `aidw run` chain resumability.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/implementation-results/03-H1.2/build-results.md` | Created | This results document. |
| `aidw/cli.py` | Modified | Adds `--resume` and `--from <stage>` to `prompt` and threads both into `prompt_workflow.run`; the `runs resume` hint now names `aidw prompt --resume` beside implement. |
| `aidw/workflows/prompt.py` | Modified | `_latest_prompt_run`, `_confirm_resume`, `_print_completed`, blocked-resume refusal (`blocked_resume_reason`/`_refuse_blocked_resume`), `--from` grammar (`prompt_stage_position`/`is_from_stage`), worktree locate-and-reuse with the exit-4 clear commands (`worktree_clear_commands`), loop reconstruction from recorded reviews and fix-stage names, and `state.resume` stamped/cleared at every stop (`_mark_failed`/`_mark_blocked`). |
| `tests/test_prompt_workflow.py` | Modified | Adds 28 fake-stage tests for resume, worktree reuse/refusals, the still-running guard, declined resume, `--from` grammar and layering, blocked refusals, fix-batch reconstruction, the worktree-keyed lock, dry-run composition and the `runs resume` hint; extends the fake-stage helper and updates existing failure tests to assert `state.resume`. |
| `design.md` | Modified | §8.1 branch-setup reuse and refusal commands, §9.4 prompt resumability, §14's `aidw prompt` flags, and §17 decision V1. |
| `docs/tasks/03 - Stage resilience.md` | Modified | Ticks H1.2. |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 3ms`; exit 0) |
| Build | `aidw gate run build --ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv build --out-dir "$(mktemp -d)"` | ✅ Pass (`aidt-1.1.1.tar.gz` and `aidt-1.1.1-py3-none-any.whl` built; gate `build` passed for tree `9ea1bded48e3` at `2026-11-09T10:46:20Z` by stage `record-implementation-results`) |
| Test | `aidw gate run suite --ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv run --frozen pytest` | ✅ Pass (`reused: gate 'suite' passed for tree 9ea1bded48e3 at 2026-11-09T10:43:25Z by stage 'update-traceability'` — `1901 passed in 33.79s`; cited rather than re-run because the tree and declared scope match this record run's) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`; warnings: dirty working tree, missing `.mcp.json`) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (toolkit defaults `0 error(s), 0 warning(s)`; resolved repo prompts `0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (no output; exit 0) |
| Lint | — | ⚠️ **unverified** (the repository configures no lint command; `AGENTS.md` names only pytest, `doctor`, `agents validate --strict` and `prompts check`, and `design.md` §15 says no linter is configured) |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1,901 | ✅ Pass (`1901 passed in 33.79s`, gate `suite` for tree `9ea1bded48e3` recorded by stage `update-traceability` at `2026-11-09T10:43:25Z`) |
| `tests/test_prompt_workflow.py` (new H1.2 tests) | 28 new functions | ✅ Pass (included in the 1,901-test full suite; the reused gate emits no per-file summary, so the subset was not re-run for its own count) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Resume continues at the failed review with one run id and no author stage: `test_resume_continues_at_the_failed_review_with_one_run_id` | ✅ Pass (included in the 1,901-test full suite) |
| `state.resume` lifecycle — failed stamps `next_stage`, success clears it: `test_resume_continues_at_the_failed_review_with_one_run_id`; block records none: `test_from_without_resume_starts_a_fresh_run` | ✅ Pass (included in the full suite) |
| Prior-round `FixBatch` re-parsed from recorded review text and reconciled against recorded names: `test_resume_rebuilds_the_prior_rounds_fix_batch_from_its_review_text`, `test_resume_rebuilds_the_unparseable_fallback_batch`, `test_a_recorded_review_that_now_ends_the_run_refuses_to_resume` | ✅ Pass (included in the full suite) |
| Fresh re-run worktree rules — clean tree reused, dirty tree refused, leftover branch refused: `test_a_located_clean_worktree_is_reused_instead_of_added`, `test_a_fresh_rerun_refuses_a_dirty_reused_worktree`, `test_a_fresh_rerun_refuses_a_leftover_branch` | ✅ Pass (included in the full suite) |
| Missing worktree on resume refuses exit 4: `test_resume_refuses_when_its_worktree_is_missing` | ✅ Pass (included in the full suite) |
| Still-running guard and takeover: `test_a_stale_running_record_refuses_a_fresh_run_but_resume_takes_it_over` | ✅ Pass (included in the full suite) |
| Declined resume leaves no side effect: `test_a_declined_resume_leaves_no_side_effect` | ✅ Pass (included in the full suite) |
| No matching run is a usage error; missing `--resume` run under `--dry-run` plans fresh: `test_resume_without_a_matching_run_is_a_usage_error`, `test_dry_run_with_resume_plans_the_fresh_baseline_and_mints_a_new_run` | ✅ Pass (included in the full suite) |
| `--from` grammar and validation before side effects: `test_an_unknown_or_out_of_budget_from_stage_is_a_usage_error`, `test_is_from_stage_is_the_loops_bounded_grammar`, `test_from_grammar_matches_the_prompt_loop_expansion_property`, `test_dry_run_validates_from_without_minting_a_run` | ✅ Pass (included in the full suite) |
| `--from` layering — same run id with `--resume`, fresh run id alone: `test_from_with_resume_re_runs_a_succeeded_stage_in_the_same_run`, `test_from_without_resume_starts_a_fresh_run` | ✅ Pass (included in the full suite) |
| Blocked-run refusal (exit 3) per shape, no mutation: `test_blocked_resume_refuses_with_the_last_reviews_verdict`, `test_blocked_resume_names_the_authors_recorded_block`, `test_blocked_resume_names_a_gate_denial_mechanism` | ✅ Pass (included in the full suite) |
| Same worktree-keyed lock held across a resume: `test_resume_acquires_the_same_worktree_keyed_lock` | ✅ Pass (included in the full suite) |
| Gates already recorded are not re-asked: `test_resume_does_not_reask_an_already_approved_gate` | ✅ Pass (included in the full suite) |
| Dry-run composition with the new flags: `test_a_plain_dry_run_plans_the_author_and_first_review`, `test_dry_run_with_resume_plans_the_fresh_baseline_and_mints_a_new_run`, `test_dry_run_with_resume_over_a_blocked_run_still_refuses`, `test_dry_run_over_a_running_record_still_plans_fresh`, `test_dry_run_validates_from_without_minting_a_run` | ✅ Pass (included in the full suite) |
| CLI wiring and `runs resume` guidance: `test_prompt_cli_forwards_resume_and_from`, `test_runs_resume_hint_names_the_prompt_workflow` | ✅ Pass (included in the full suite) |
| A real model-backed resume (a live Pi run resuming after a real failure) | ⚠️ **unverified** (no test in this repository may invoke a real Pi model — `AGENTS.md` §Tests, `design.md` §15; the resume is proven against fake stages) |

---

## Deviations observed during recording

- **No lint gate was available** — this repository has no configured linter or formatter (`AGENTS.md` §Tests, `design.md` §15), so the row is marked unverified rather than substituting an invented command.
- **The suite gate was cited, not re-run** — `aidw gate run suite` reported that stage `update-traceability` of this run had already passed `suite` for tree `9ea1bded48e3` with the same declared scope (`2026-11-09T10:43:25Z`, `1901 passed in 33.79s`), which is this run's own recorded observation of the same content. Per-file and per-test counts were therefore not re-run; the task-specific rows cite inclusion in that single full-suite invocation.
- **Implementation changes were still uncommitted at record time** — the recorded change set is the working tree relative to `main`, as the recording stage directs; only the task prompt is committed on this branch.

---

## Non-Goals (NOT implemented)

- ❌ H1.3 blocked-run continuation, `--from-prompt <path>` and a recorded effective budget — H1.2 only refuses a blocked resume with a named reason (task prompt explicit non-goals).
- ❌ H2.1 delta-brief size budget — a resume re-sends the same prompts; it does not shrink them (task prompt explicit non-goals).
- ❌ `aidw run` chain resumability (`prompt-to-fix`/`task-to-pr`) — `aidw/workflows/run.py` calls `prompt_workflow.run` without resume flags and is unchanged (task prompt explicit non-goals).
- ❌ No re-authoring on a blocked run, and no fabrication of a fix batch or a pre-fix baseline diff to widen the resume (design §17 V1).
- ❌ No PR was opened, no commit was made, and no implementation, test or traceability file was changed by this recording stage.
