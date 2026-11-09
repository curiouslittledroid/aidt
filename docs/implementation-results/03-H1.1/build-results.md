# Build Results — 03-H1.1: Retry a stage whose final message never arrived

**Branch:** `03-H1.1`
**Date:** 2026-11-09
**Spec:** `design.md` §9.2, §10, §14, §17; `docs/tasks/03 - Stage resilience.md` H1.1

## Summary

**Purpose:** A stage whose Pi invocation exits cleanly but produces no final text — the
`stop_reason: length` truncation seen in `20261104T020519Z-00-E4.5-prompt` — is now retried once
in a fresh session instead of killing the run, and two truncated attempts fail with a message that
names the stage, the final attempt's stop reason and that both attempts were truncated.

| Decision | Why it matters |
|----------|---------------|
| The retry is a second, additive branch in `execute`'s attempt loop, gated on `not parsed.provider_error`, not folded into `is_transient`. | A 402 is exit 0 with empty final text; without the provider-error guard the truncation retry would silently turn design §10's "provider error → failed, not retried" row into a double attempt. |
| The retry uses a distinct `--session-id`: the base id plus a `-retry` suffix (`RETRY_SESSION_SUFFIX`, rewritten by `retry_argv`). | `build_argv` bakes the base session id into argv before `execute` runs, and Pi resumes `--session-id`, so re-running the identical argv resumes the truncated context and truncates again. The caller's argv (recorded in the meta) is never mutated; a sessionless argv is already fresh and is left unchanged. |
| Both branches share today's cap, `max_attempts = 2 if retry_transient else 1`. | `--no-retry-transient` disables the new retry exactly as it disables the transient one, and neither branch can produce a third attempt. |
| Per-attempt evidence is the additive `attempts_detail` list on `PiResult` and the stage `.meta.json`, one entry per attempt (session id, exit code, stop reason, usage, timing). | The retry overwrites the stage JSONL and the meta's `argv` still describes the first attempt, so without this list the first attempt's cost would be unrecoverable. |
| `usage`, `generation_seconds`, `tool_seconds` and the tool breakdown are captured per attempt inside the loop and **summed** over the attempts that ran; `event_count`/`tool_calls`/`tool_errors` likewise. | `output_tokens_per_second` is `usage.output_tokens / generation_seconds`; leaving the timing at the last attempt's window would divide summed tokens by one attempt's seconds. Summing also lets the existing cost-ceiling check cover both attempts with no second check. |
| `StageRecord` gains additive `stop_reason` (the **final** attempt's) and `attempts`, defaulting `None` at the same `SCHEMA_VERSION`. | Same additive precedent as the throughput fields: an older `state.json` still loads, and the workflows' empty-final-message failure path can name the evidence. |
| One shared message builder, `aidw/report.py:empty_final_message_error`, used by `prompt`, `fix` and `review`. | The three workflows previously printed the same bare string; the enriched wording must not drift per workflow, and a single-attempt record (`--no-retry-transient`) keeps its own attempt-count context. |

**Where it fits in the roadmap:** H1.1 is the first task in Epic H1 (phase 03, stage resilience).
It depends on H0.1's persisted gate evidence (a gate the first attempt already ran is cited, never
re-asked) and on the existing transient-retry seam at `aidw/pi.py:execute`; H1.2 (`--resume`) and
H1.3 (blocked-run continuation) build on the run surviving a bad round, and E9.1 carries the §10
and §17 amendments forward.

**Scope:** `aidw/pi.py` owns the retry predicate, the fresh-session argv rewrite, the per-attempt
records and the summed totals; `aidw/runner.py` copies `stop_reason`/`attempts` onto the stage
record; `aidw/state.py` adds the two additive fields; `aidw/report.py` adds the shared failure
message; `prompt`/`fix`/`review` use it. `design.md` amends §10's row, §9.2's schema/meta prose and
§14's `--retry-transient` description, and records the decision as §17 U1; the H1.1 roadmap tick
is set. The task deliberately stops short of resumability, prompt-size budgeting and distinguishing
a truncation from a silent agent.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/implementation-results/03-H1.1/build-results.md` | Created | This results document. |
| `aidw/pi.py` | Modified | Adds `AttemptDetail`, `retry_on_empty_final_message`, `retry_session_id`, `RETRY_SESSION_SUFFIX`/`SESSION_ID_FLAG`, `retry_argv`, `ParsedRun.provider_error`; `execute` gains the fresh-session truncation retry, per-attempt capture and summed usage/timing/counters; `write_meta` emits `attempts_detail`. |
| `aidw/runner.py` | Modified | `run_stage` populates `StageRecord.stop_reason` and `.attempts` from the `PiResult`; no extra cost-ceiling check. |
| `aidw/state.py` | Modified | `StageRecord` gains additive `stop_reason: str \| None` and `attempts: int \| None`, both defaulting `None` at the same `SCHEMA_VERSION`. |
| `aidw/report.py` | Modified | Adds `empty_final_message_error`, the shared bare/fail-closed message for a stage with no final text, distinguishing one attempt from two truncated ones. |
| `aidw/workflows/prompt.py` | Modified | Logs and prints `empty_final_message_error(rec)` instead of the bare "produced no final message". |
| `aidw/workflows/fix.py` | Modified | Uses `empty_final_message_error(record)` for the empty code-review failure. |
| `aidw/workflows/review.py` | Modified | Uses `empty_final_message_error(rec1)` for the empty review failure. |
| `tests/test_pi.py` | Modified | Adds twelve tests: the fresh-session retry, `write_meta`'s per-attempt entries, double truncation, first-answer-wins, non-zero exit, the unchanged transient branch, provider-error no-retry, whitespace-only emptiness, `retry_transient=False`, the retry predicate, the `-retry` id and the sessionless argv case. |
| `tests/test_runner.py` | Modified | Adds four tests: final `stop_reason`/`attempts` on the record, one meta entry per attempt, summed two-attempt cost against the ceiling, and `retry_transient=False` forwarding. |
| `tests/test_report.py` | Modified | Adds two tests for the shared double-truncation and single-attempt messages. |
| `tests/test_state.py` | Modified | Asserts the new fields default `None` for an older record and round-trip without a schema bump. |
| `tests/test_fix_workflow.py` | Modified | The fake stage carries the H1.1 fields; a new test asserts the empty code-review failure names both truncated attempts. |
| `tests/test_review_workflow.py` | Modified | The fake stage carries the H1.1 fields; a new test asserts the empty review failure names both truncated attempts. |
| `tests/test_prompt_workflow.py` | Modified | L4.2's empty-review test now models a retried `length` result and asserts the enriched message in `run.log`. |
| `design.md` | Modified | §9.2 stage schema/meta (`stop_reason`, `attempts`, `attempts_detail`, summed usage/timing), §10's "no final message" row, §14's `--retry-transient` flag description, and §17 decision U1. |
| `docs/tasks/03 - Stage resilience.md` | Modified | Ticks H1.1. |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.84ms`; exit 0) |
| Build | `aidw gate run build --ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv build --out-dir "$(mktemp -d)"` | ✅ Pass (`aidt-1.1.1.tar.gz` and `aidt-1.1.1-py3-none-any.whl` built; gate `build` passed for tree `4d09ae4ea99f` at `2026-11-09T09:29:06Z` by stage `record-implementation-results`) |
| Test | `aidw gate run suite --ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv run --frozen pytest` | ✅ Pass (`reused: gate 'suite' passed for tree 4d09ae4ea99f at 2026-11-09T09:25:46Z by stage 'test'` — `1854 passed in 29.37s`; cited, not re-run, because the tree and declared scope match this record run's) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`; warnings: dirty working tree, missing `.mcp.json`) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (toolkit defaults `0 error(s), 0 warning(s)`; resolved repo prompts `0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (no output; exit 0) |
| Lint | — | ⚠️ **unverified** (the repository configures no lint command; `AGENTS.md` names only pytest, `doctor`, `agents validate --strict` and `prompts check`, and `design.md` §15 says no linter is configured) |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1,854 | ✅ Pass (`1854 passed in 29.37s`, gate `suite` for tree `4d09ae4ea99f` recorded by stage `test` at `2026-11-09T09:25:46Z`) |
| `tests/test_pi.py` (new `execute` retry tests) | 12 new functions | ✅ Pass (included in the 1,854-test full suite; the gate run emits no per-file summary, so the subset was not re-run for its own count) |
| `tests/test_runner.py` (new `run_stage` record/meta tests) | 4 new functions | ✅ Pass (included in the 1,854-test full suite) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Fresh-session truncation retry: `test_execute_retries_a_truncated_attempt_in_a_fresh_session` | ✅ Pass (included in the 1,854-test full suite) |
| `write_meta` carries one `attempts_detail` entry per attempt: `test_write_meta_records_one_entry_per_attempt` | ✅ Pass (included in the full suite) |
| Double truncation fails closed (`final_message == ""`, `attempts == 2`, `out_path is None`): `test_execute_fails_closed_on_two_truncated_attempts` | ✅ Pass (included in the full suite) |
| A first-attempt answer is never retried: `test_execute_never_retries_an_attempt_that_answered` | ✅ Pass (included in the full suite) |
| Non-zero exit keeps a single attempt: `test_execute_keeps_nonzero_exit_as_a_single_attempt` | ✅ Pass (included in the full suite) |
| Transient-retry branch unchanged: `test_execute_keeps_the_existing_transient_retry_branch` | ✅ Pass (included in the full suite) |
| Provider error (exit 0, `stopReason: "error"`) is never retried: `test_execute_never_retries_a_provider_error` | ✅ Pass (included in the full suite) |
| Whitespace-only answer parses empty and retries: `test_execute_treats_a_whitespace_only_answer_as_empty` | ✅ Pass (included in the full suite) |
| `retry_transient=False` disables the new retry: `test_execute_does_not_retry_when_retry_transient_is_disabled` | ✅ Pass (included in the full suite) |
| Retry predicate requires a clean, empty attempt: `test_retry_on_empty_final_message_requires_a_clean_empty_attempt` | ✅ Pass (included in the full suite) |
| Retry session id is the distinct `-retry` id: `test_retry_session_property` | ✅ Pass (included in the full suite) |
| Sessionless argv is left unchanged: `test_retry_argv_leaves_a_sessionless_invocation_unchanged` | ✅ Pass (included in the full suite) |
| `run_stage` records the final attempt's `stop_reason` and the attempt count: `test_run_stage_records_the_final_stop_reason_and_attempt_count` | ✅ Pass (included in the full suite) |
| Stage meta shows one entry per attempt: `test_run_stage_meta_shows_one_entry_per_attempt` | ✅ Pass (included in the full suite) |
| Cost ceiling sees the summed two-attempt cost: `test_run_stage_cost_ceiling_sees_the_summed_two_attempt_cost` | ✅ Pass (included in the full suite) |
| `run_stage` forwards `retry_transient=False`: `test_run_stage_forwards_retry_transient_false` | ✅ Pass (included in the full suite) |
| Workflow failure names both truncated attempts (`prompt`, `fix`, `review`): `test_l42_empty_review_exit_stays_gate_less`, `test_empty_code_review_names_both_truncated_attempts` (fix), `test_empty_review_names_both_truncated_attempts` (review) | ✅ Pass (included in the full suite) |
| Failure-message builder: `test_empty_final_message_error_names_double_truncation`, `test_empty_final_message_error_preserves_single_attempt_context` | ✅ Pass (included in the full suite) |
| Additive record fields load as `None` and round-trip without a schema bump: `test_old_state_without_throughput_still_loads`, `test_stage_retry_fields_round_trip_without_a_schema_bump` | ✅ Pass (included in the full suite) |
| Real-model retry behaviour (a live `pi` truncation) | ⚠️ **unverified** (no test in this repository may invoke a real Pi model — `AGENTS.md` §Tests, `design.md` §15; the retry is proven against a fake argv) |

---

## Deviations observed during recording

- **No lint gate was available** — this repository has no configured linter or formatter
  (`AGENTS.md` §Tests, `design.md` §15), so the row is marked unverified rather than substituting
  an invented command.
- **The suite gate was cited, not re-run** — `aidw gate run suite` reported that stage `test` of
  this run had already passed `suite` for tree `4d09ae4ea99f` with the same declared scope
  (`2026-11-09T09:25:46Z`, `1854 passed in 29.37s`), which is this run's own recorded observation
  of the same content. Per-attempt subset counts were therefore not re-run; the task-specific rows
  cite inclusion in that single full-suite invocation.
- **Implementation changes were still uncommitted at record time** — the recorded change set is
  the working tree relative to `main`, as the recording stage directs; only the task prompt is
  committed on this branch.

---

## Non-Goals (NOT implemented)

- ❌ H1.2 (`aidw prompt --resume`/`--from`, worktree reuse) and H1.3 (blocked-run continuation) — no
  resumability or branch-setup change (task prompt non-goals).
- ❌ H2.1 (delta-brief size budget) — the retry re-sends the prompt; it does not shrink it (task
  prompt non-goals).
- ❌ Distinguishing a truncated stage from a silent one — the ambiguity is accepted, not solved;
  no new mechanism separates them (task prompt non-goals; phase-03 non-goals).
- ❌ Gate failures are never retried — a denied/blocked gate or a `Request changes`/`Blocked`
  verdict never triggers the retry, and no gate machinery was added (design §10; phase-03
  non-goals).
- ❌ No PR was opened, no commit was made, and no implementation, test or traceability file was
  changed by this recording stage.
