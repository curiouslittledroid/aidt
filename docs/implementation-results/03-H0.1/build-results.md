# Build Results — 03-H0.1: Keep gate outcomes across stage boundaries

**Branch:** `03-H0.1`
**Date:** 2026-11-09
**Spec:** `design.md` §9.1, §9.2, §14, §17; `docs/tasks/03 - Stage resilience.md` H0.1; `docs/tasks/00 - Extraction.md` E4.8

## Summary

**Purpose:** Make gate outcomes recorded by `aidw gate run` survive the workflow's next `save()`, concurrent gate writes, and the run process itself, so later stages can cite the same evidence instead of re-buying the same gate.

| Decision | Why it matters |
|----------|---------------|
| Use mechanism (b): merge-on-write of `gate_outcomes` inside `state.json`. | The loss is symmetric — the workflow and CLI share one file — so a second append-only artifact would leave the rest of the file with the same unchecked read-modify-write. |
| Serialize all state writers with `<run_dir>/state.json.lock` (`fcntl.flock(LOCK_EX\|LOCK_NB)`). | `runner._STATE_LOCK` is in-process only, while the worktree run lock is held by the workflow for its whole lifetime; a worktree-keyed state lock would refuse every gate subprocess. |
| Publish through a same-directory temp file, fsync, then `os.replace`. | Lock-free readers (`load`, `gate list`, `runs show`, concurrent citations) must never observe a truncated or half-written `state.json`. |
| `save()` reloads and merges disk outcomes; the CLI reloads and appends only. | Neither writer may drop the other's rows: a stale workflow handle must keep CLI-appended outcomes, and a gate write must keep stage records written while its command ran. |
| Collapse only byte-identical rows; never "newest wins per key". | Two processes that both executed a command are two pieces of evidence, and the task explicitly requires both concurrent outcomes to survive. |
| Keep `GateOutcome` fields and the `gate_outcomes` list at the existing schema version; leave the cite-or-run rule unchanged. | Persistence is the change, not the gate contract: same key, tree, command, declared scope and `passed` still decides reuse. |

**Where it fits in the roadmap:** H0.1 is the first task in Epic H0 (phase 03, stage resilience). It completes the persistence half of E4.8 and is a prerequisite for H3.2, whose roadmap tick reads gate outcomes recorded by this path. H0.1 does not change which stages gate or what a red gate stops.

**Scope:** `aidw/state.py` now owns atomic publication, the per-run state lock, symmetric outcome merging and the CLI append helper; `aidw/cli.py` uses that append path; `aidw/verification.py` documents the writer split without changing reuse. `design.md` records the mechanism in §17 T1 and updates §9.1, §9.2 and §14; the H0.1 tick and E4.8 progress line are updated. Tests cover the stale-handle round trip, cross-stage citation, concurrent writers, unlocked-reader integrity, post-exit reporting and fail-closed paths. The task deliberately stops short of H1.1/H1.2 and the H3.2 roadmap tick.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/03-H0.1-prompt.md` | Created | Task prompt committed before implementation. |
| `aidw/state.py` | Modified | Adds `state.json.lock` serialization, atomic `os.replace` publication, lossless outcome merge, append-only CLI writer and unreadable-state fail-closed handling. |
| `aidw/cli.py` | Modified | `aidw gate run` persists a non-cited outcome through `append_gate_outcomes` instead of rewriting a stale full state. |
| `aidw/verification.py` | Modified | Documents the workflow/CLI writer split; reuse rule and gate execution are unchanged. |
| `tests/test_verification.py` | Modified | Adds eleven tests for round-trip survival, cross-stage citation, overlap integrity, concurrency, post-exit reporting, atomic save, lock reuse, merge identity and fail-closed writes. |
| `design.md` | Modified | Updates §9.1 lock non-conflation, §9.2 two-writer publication contract, §14 gate CLI behaviour, and records decision T1 in §17. |
| `docs/tasks/03 - Stage resilience.md` | Modified | Ticks H0.1. |
| `docs/tasks/00 - Extraction.md` | Modified | E4.8 Progress line now names the stage-boundary persistence gap and H0.1's fix. |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 1ms`; exit 0) |
| Build | `aidw gate run build --ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv build --out-dir "$(mktemp -d)"` | ✅ Pass (`aidt-1.1.1.tar.gz` and `aidt-1.1.1-py3-none-any.whl` built; gate `build` passed for tree `77b534f00f08` at `2026-11-09T08:36:10Z` by stage `record-implementation-results`) |
| Test | `aidw gate run suite --ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv run --frozen pytest` | ✅ Pass (`1833 passed in 34.08s`; gate `suite` passed for tree `77b534f00f08` at `2026-11-09T08:36:47Z` by stage `record-implementation-results`) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`; warnings: dirty working tree, missing `.mcp.json`) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (toolkit defaults `0 error(s), 0 warning(s)`; resolved repo prompts `0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (no output; exit 0) |
| Lint | — | ⚠️ **unverified** (the repository configures no lint command; `AGENTS.md` names only pytest, `doctor`, `agents validate --strict` and `prompts check`) |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1,833 | ✅ Pass (`1833 passed in 34.08s`) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| H0.1 round trip: a CLI gate outcome survives the workflow's next stale-handle save (`test_a_cli_gate_outcome_survives_the_workflows_next_save`) | ✅ Pass (included in the 1,833-test full suite) |
| H0.1 symmetric merge: a stage record survives a CLI gate write (`test_a_stage_record_written_while_a_cli_gate_runs_survives_its_write`) | ✅ Pass (included in the 1,833-test full suite) |
| H0.1 concurrency: two overlapping CLI gate runs both record an outcome (`test_two_overlapping_cli_gate_runs_both_record_an_outcome`) | ✅ Pass (included in the 1,833-test full suite) |
| H0.1 overlap integrity: unlocked readers never see a torn or stage-losing state (`test_no_unlocked_reader_observes_a_torn_or_stage_losing_state`) | ✅ Pass (included in the 1,833-test full suite) |
| H0.1 citation chain: one `test` gate is cited by `record` and `pr` (`test_one_test_gate_is_cited_by_record_and_by_pr`) | ✅ Pass (included in the 1,833-test full suite) |
| H0.1 post-exit reporting: `gate list` and `runs show` see outcomes after the process exits (`test_gate_list_and_runs_show_report_outcomes_after_the_process_exits`) | ✅ Pass (included in the 1,833-test full suite) |
| State-lock exclusion and reuse, atomic save, fail-closed unreadable state, distinct-key retention and lossless merge | ✅ Pass (five further tests included in the 1,833-test full suite) |

---

## Deviations observed during recording

- **No lint gate was available** — this repository has no configured linter or formatter (`AGENTS.md` §Tests, `design.md` §15), so the row is marked unverified rather than substituting an invented command.
- **The suite gate summary captured the trailing `VIRTUAL_ENV` warning** — pytest itself reported `1833 passed in 34.08s`; the warning from the ambient virtual environment followed it and became the gate's last-line summary.
- **Implementation changes were still uncommitted at record time** — the recorded change set is the working tree relative to `main`, as the recording stage directs; only the task prompt was committed.

---

## Non-Goals (NOT implemented)

- ❌ H1.1 (retry a stage whose final message never arrived) and H1.2 (`aidw prompt` resumes instead of re-authoring) were not started (task prompt non-goals).
- ❌ H3.2 (the roadmap tick reads gate outcomes) was not implemented (task prompt non-goals).
- ❌ Which stages gate, what a red gate stops, and the cite-or-run rule were not changed (task prompt non-goals).
