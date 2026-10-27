# Build Results — 02-L4.2: Record what was accepted and what it cost

**Branch:** `02-L4.2`
**Date:** 2026-10-27
**Spec:** `docs/tasks/02 - Prompt loop integrity.md` (L4.2), `design.md` §9.2 / §9.3 / §8.1, `AGENTS.md` (Gates and Tests)
**Run id:** `20261027T120651Z-02-L4.2-implement`

## Summary

**Purpose:** Make a completed `aidw prompt` run carry the per-round evidence a human needs to
judge the loop from `state.json` and `run.log` alone — verdict, rounds, findings per round, fixes
per round, whether the final verdict approved, and whether any fix ran after the last review — and
make a run that ends `BLOCKED` say so in the gate record and the run log.

| Decision | Why it matters |
|----------|---------------|
| One `_loop_summary` helper renders the named `key=value` string for the gate `detail`, the `run.log` line and stdout | The three channels cannot drift; the gate, log and stage report are the same observation |
| Per-round telemetry is accumulated in-loop as `(review_index, findings_count, fix_stage_count)` | The in-loop partition is authoritative: the whole-review fallback runs one stage while a parsed 3-finding review runs three; counting stage names after the fact undercounts the fallback |
| Every verdict-bearing exit records `approve-task-prompt` with `decision` ∈ `approved`/`denied` and the verdict in `detail` | Reverses L4.1's "no gate record" on the terminal/Blocked paths; `denied` is existing vocabulary and the verdict travels in `detail`, so no new gate-decision word is invented |
| `fixes_after_last_review` derived from the last round's fix-stage count, never a constant | Records the L4.1 invariant as evidence: the terminal review is review-only, so a `yes` would prove an unreviewed fix shipped |
| `approved=yes` iff the final verdict is `Approve`, independent of the gate `decision` | A human denial records `approved=yes` beside `decision=denied` — the reviewer's verdict and the human's refusal each keep their own field |
| Verdict-less exits (author-blocked, failed stage, empty review, missing prompt) record no gate and no summary line | A `denied` would claim a review outcome that never happened; they keep today's `FAILED`/`BLOCKED` status and logging |

**Where it fits in the roadmap:** Phase 02 ("Prompt loop integrity"), Epic L4 ("Termination
honesty"). It follows L4.1, which made the final revision slot a review-only round and left the
terminal `Request changes` and `Blocked` exits with no gate record; L4.2 records those outcomes
instead. L4.3 owns the configurable `--max-revisions` / `max_revisions` surface; L6.1/L6.2 own the
synthesized loop fixture and the `design.md` §17 consolidation plus E4.1/E4.3 re-baselining.

**Scope:** Touches the loop and its observability in `aidw/workflows/prompt.py` and the loop tests
in `tests/test_prompt_workflow.py`, and flips the L4.2 checkbox in the phase roadmap. It
deliberately stops short of adding any config or CLI surface, changing the fix/reconcile stage
mechanics, or turning the recorded numbers into a gate, threshold or cost/latency acceptance
criterion.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L4.2-prompt.md` | Created | Task prompt for L4.2 (committed on the branch) |
| `aidw/workflows/prompt.py` | Modified | Add per-round telemetry (`ReviewRound`, `_record_round`), the single `_loop_summary` renderer, and `_record_review_outcome`; record the `approve-task-prompt` gate, the run.log line and the stdout summary on every verdict-bearing exit; add the missing BLOCKED `logger.error` on the terminal `Request changes` branch; update the module docstring |
| `tests/test_prompt_workflow.py` | Modified | Revise the L4.1 gate-absence assertions; add L4.2 tests for the summary renderer, partial-parse fallback count, human-denial fields, run.log summary/BLOCKED line, ambiguous terminal verdict, and the gate-less empty-review exit |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified | Flip the L4.2 checkbox to done |

---

## Verification Results

Repo gates are the ones `AGENTS.md` names under "Gates — run exactly these, and only these":
`uv sync --frozen`, `uv run --frozen pytest`, `uv run aidw doctor`,
`uv run aidw agents validate --strict`, `uv run aidw prompts check`. `prompts/pr.md` selects the
same `pyproject.toml` / `uv.lock` rows. Each runnable gate was run through
`aidw gate run <key> -- <command>` with the shared scope
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`,
recorded against tree `063f11a8750b` in run `20261027T120651Z-02-L4.2-implement`. The pytest gate
scrubs the harness's ambient `AIDW_STAGE` / `AIDW_RUN_ID` from its child process — the convention
prior stages (`docs/implementation-results/02-L4.1/`, `02-L3.3/`, `02-L3.4/`) documented, because
two pre-existing `tests/test_verification.py` gate-recording tests read those variables and fail
when the stage identity leaks into the child.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.66ms` (exit 0) — gate `install`, tree `063f11a8750b`, stage `record-implementation-results`, 2026-10-27T12:42:43Z |
| Build | `uv build --out-dir <tmp>` | ✅ built sdist + wheel `aidt-0.1.0` — gate `build`, tree `063f11a8750b`, 2026-10-27T12:42:50Z (extra: `uv build` is not one of `AGENTS.md`'s five named gates; run because `prompts/pr.md` lists it for the `pyproject.toml` stack) |
| Test | `env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ✅ `652 passed in 80.68s` — gate `suite`, tree `063f11a8750b`, stage `record-implementation-results`, 2026-10-27T12:45:46Z |
| Doctor | `uv run --frozen aidw doctor` | ✅ `14 checks: 0 failed, 2 warning(s)` — gate `doctor`, tree `063f11a8750b`, 2026-10-27T12:45:55Z |
| Agent configs | `uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` — gate `agents`, tree `063f11a8750b`, 2026-10-27T12:45:53Z |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` — gate `prompts`, tree `063f11a8750b`, 2026-10-27T12:45:53Z |
| Whitespace | `git diff --check` | ✅ no output (exit 0) |

The two `doctor` warnings are the expected dirty working tree on branch `02-L4.2` and the missing
optional `/.mcp.json`; neither is a failure.

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 652 | ✅ Pass (`652 passed in 80.68s`) |

The new and revised L4.2 cases are inside this single run; no separate subset count was produced
(per the stage rule against re-running a suite for a row). They are:
`test_l42_loop_summary_renders_ambiguous_and_derives_fixes_after`,
`test_l42_partial_parse_fallback_keeps_findings_count`,
`test_l42_human_denial_keeps_reviewer_verdict_and_denied_decision`,
`test_l42_run_log_carries_the_per_round_summary_and_blocked_line`,
`test_l42_terminal_round_without_a_verdict_records_ambiguous`, and
`test_l42_empty_review_exit_stays_gate_less`; plus the revised
`test_third_review_is_terminal_and_residual_request_changes_fails_closed`,
`test_approve_on_the_terminal_review_succeeds`,
`test_blocked_terminal_review_keeps_human_escalation_path`,
`test_a_blocked_final_review_still_fails_closed`,
`test_approval_gate_defaults_to_not_required`, and `test_failed_fix_stage_stops_the_run`.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run --frozen pytest` (the only gate the task prompt names) | ✅ `652 passed` — gate `suite`, tree `063f11a8750b`, 2026-10-27T12:45:46Z |
| Install / build / doctor / agents / prompts | ✅ see top-level table |
| `pnpm srd:validate` / `srd:check-references` / `srd:matrix-check` / `srd:report` | **unverified — not applicable**: no `pnpm-workspace.yaml`, `package.json`, `docs/rules-coverage/catalog.json` or vector matrix exists in this `pyproject.toml`/`uv.lock` toolkit repo |
| `pnpm --filter infra cdk synth -c env=dev` | **unverified — not applicable**: no `infra/` package or CDK workspace exists in this repo |
| Deployed integration / matrix completeness test | **unverified — not applicable**: no `tests/integration` TypeScript workspace or matrix fixture exists |

---

## Deviations observed during recording

- **Generic prompt template named pnpm gates; this repo is Python/uv.** `prompts/record-implementation-results.md`
  ships pnpm examples, but `AGENTS.md` names exactly the five uv commands above and `prompts/pr.md`
  says to take the gate commands from the target repo. The pnpm/SRD/CDK rows do not apply here and
  are marked unverified/not applicable rather than passing. No lint gate exists in this repo.
- **The pytest gate runs under `env -u AIDW_STAGE -u AIDW_RUN_ID`.** The first, un-scrubbed
  invocation of the same gate recorded `failed` — `2 failed, 650 passed` — solely because the
  harness's ambient `AIDW_STAGE`/`AIDW_RUN_ID` leaked into two pre-existing
  `tests/test_verification.py` gate-recording tests
  (`test_cli_gate_run_propagates_a_failing_exit_code`,
  `test_cli_gate_run_records_into_the_branch_run_without_an_env_identity`). The gate was then
  re-run with the documented scrub (the same invocation prior stages used) and passed
  `652 passed`; the failed outcome remains in the run's gate list and is recorded here rather than
  hidden. No implementation or test file was changed between the two runs.
- **Tree is `063f11a8750b`, shared by every recorded gate above.** The working tree was not
  modified by this stage, so all six gate outcomes name the same tree.

---

## Non-Goals (NOT implemented)

- ❌ L4.3 — the `--max-revisions` CLI flag / `max_revisions` config key; no config surface or flag
  was added. (Task prompt, explicit non-goals)
- ❌ L6.1 / L6.2 — the synthesized loop fixture pinning every contract, and the `design.md` §17
  consolidation plus E4.1/E4.3 re-baselining; this task records data and edits neither `design.md`
  §17 nor `docs/tasks/00 - Extraction.md`. (Task prompt, explicit non-goals)
- ❌ An `approve-task-prompt` gate record on the author-blocked (L1.3) path — it has no review
  rounds or verdict; it keeps `status=blocked` and its existing run.log line. (Task prompt, explicit
  non-goals)
- ❌ Any new `status`/`decision`/verdict vocabulary: `decision` stays ∈ `approved`,`denied` and
  `status` stays `blocked`; the verdict lives in `detail`. (Task prompt, requirement 7)
- ❌ Any cost, round-count or latency gate/threshold, or a separate cost field — `totals` already
  aggregates cost (§9.2); the numbers are recorded for the operator to judge. (Task prompt, explicit
  non-goals; phase 02 preamble)
- ❌ No commit, push, or PR — `prompts/pr.md` owns delivery. (Implicit non-goal of this stage)
