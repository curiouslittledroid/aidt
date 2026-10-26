# Build Results — 02-L2.3: Rounds after the first get a delta brief

**Branch:** `02-L2.3`
**Date:** 2026-10-27
**Spec:** `docs/tasks/02 - Prompt loop integrity.md` — task L2.3 ("Rounds after the first get a delta brief"), Epic L2 ("Reviewer authority — stop the wrong prescription"), including the phase preamble's bucket-(i) note and the "Explicit non-goals for phase 02". `design.md` §8.1 (`aidw prompt` `task-review-N` stage and the `⟳ if Request changes` loop). `docs/migration/EXTRACTION.md` §4.2 (prompt buckets — `task-review.md` is bucket (i), generic, ships as-is). `AGENTS.md` (Gates; Tests; "Prompts and agent configs are the product contract").

## Summary

**Purpose:** Give every review round after the first a delta brief — a per-finding resolution instruction, the previous review verbatim, and a real `git diff` of the prompt since that review — so rounds 2+ confirm resolution and report genuinely new findings instead of re-sampling the whole space unprimed.

| Decision | Why it matters |
|----------|---------------|
| The delta brief is assembled in `aidw/workflows/prompt.py` and passed through the existing `StageSpec.extra`, not a new prompt file | `prompts/task-review.md` is bucket (i): generic and shipped verbatim to target repos (EXTRACTION.md §4.2). Round-specific priming is runtime assembly, so L2.1/L2.2's prompt edits and the bucket split stay intact. It also means no `aidw/inventory.py:REQUIRED_PROMPTS` change. |
| The baseline is captured in memory after the review verdict and before that round's fix stages; the diff is `baseline → current` | `_commit_reviewed_prompt` runs only once after the loop, so there are no per-round commits and a bare `git diff -- <path>` would be cumulative across rounds. Capture-then-diff makes round N's diff exactly the preceding fix batch's net effect. |
| The diff is produced with `git diff --no-index` on stable relative names in a `tempfile` directory | A real unified diff, never a hand-built summary, so the brief cannot claim changes that did not happen. Stable names keep the `diff --git a/baseline/<name> b/current/<name>` header deterministic across rounds and runs, so the brief never carries a random `/tmp/...` path. Exit code 0 (identical) and 1 (differences) are both success; `git diff` reports differences as exit 1, and the `code == 0` guards in `aidw/git.py` would silently drop the diff this brief exists for. |
| Degradation is explicit, never a silently empty diff section | A `git diff` exit other than 0/1 (or an unreadable prompt) warns on stderr and degrades the brief to the instruction plus the previous review plus an explicit "unavailable" note, then the loop continues. This follows L2.4's "missing bundle degrades to the current behaviour, never an error" and `_verify_base_branch`'s warn-and-continue precedent. |
| Round 1 stays unprimed and `--dry-run` is untouched | The independent first sample is what keeps the loop from anchoring. Keying the brief off `review_index >= 2` (not `revisions`) keeps the discriminator correct, since `revisions` increments later in the same iteration; no stage is added, removed or renamed and round-1 `StageSpec` args stay `[rel]`. |

**Where it fits in the roadmap:** Phase 02, Epic L2 ("Reviewer authority — stop the wrong prescription"). It is the third rule in the epic: L2.1 (dependency inspection / `Blocked`) and L2.2 (verified-revision evidence) precede it; L2.4 (evidence bundle) follows. It leaves the fixer stages (L3.x), the terminal-review budget and recording (L4.x) untouched, and opens no `design.md` §17 entry — L6.2 consolidates phase 02's decisions.

**Scope:** Adds the delta-brief helpers and per-round wiring to `aidw/workflows/prompt.py` and the corresponding fake-stage and rendered-`extra` tests to `tests/test_prompt_workflow.py` (plus the L2.3 roadmap tick). It deliberately stops short of L2.4 and the rest of Epic L2, the L3.x fixer verify/sweep/snapshot/reconcile work, the L4.x terminal-review/config work, per-round run-directory snapshots (`stages/<stage>.prompt.md`, owned by L3.3), a second independent end-of-loop review, and any `design.md` §8.1/§17 amendment.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L2.3-prompt.md` | Created (committed) | The task prompt authored on the branch before implementation (commits `6d48e97`, `4a35bfd`). |
| `aidw/workflows/prompt.py` | Modified (uncommitted) | Added `_capture_prompt`, `_no_index_diff`, `_prompt_diff`, `_render_delta_brief`, the `_DELTA_BRIEF_INSTRUCTION` / `_DIFF_UNAVAILABLE` / `_DIFF_EMPTY` / `_DIFF_TMP_PREFIX` constants and imports; captured `baseline_prompt` after the verdict and before the fix stages; wired `review_index >= 2` to `StageSpec(..., extra=delta)`; documented the stage-2 delta brief in the module docstring. |
| `tests/test_prompt_workflow.py` | Modified (uncommitted) | Fake fixer writes a round-distinct prompt marker so per-round diffs are distinguishable; added seven L2.3 tests (round-1 unprimed, round-2 brief, round-3 non-cumulative baseline, temp-dir cleanup, verbatim previous review, unparseable-review priming, diff-failure degradation). |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified (uncommitted) | Roadmap escalation: L2.3 checkbox ticked (traceability artifact owned by the update-traceability stage). |

---

## Verification Results

> **Historical recording:** this document records an earlier failed run (`1 failed, 620 passed`) before the trailing-whitespace fix. The defect was fixed in `aidw/workflows/prompt.py`; the final PR pre-flight re-ran the gates successfully against tree `fffb0eb64ed5` (621 passed). The historical rows below remain real observations from that earlier recording run.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Exit 0 — `Checked 15 packages in 0.71ms` (gate `install`, tree `a4ab8338f91e`, 2026-10-26T22:57:03Z) |
| Build | `uv build --out-dir <tmp>` | ✅ Exit 0 — built `aidt-0.1.0-py3-none-any.whl` and `aidt-0.1.0.tar.gz` (gate `build`, tree `a4ab8338f91e`, 2026-10-26T22:57:10Z) |
| Test | `env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ❌ Exit 1 — **`1 failed, 620 passed in 59.69s`** (gate `suite`, tree `a4ab8338f91e`, 2026-10-26T23:00:31Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)` (branch `02-L2.3` dirty; `.mcp.json` absent) (gate `doctor`, tree `a4ab8338f91e`, 2026-10-26T22:59:08Z) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `a4ab8338f91e`, 2026-10-26T22:59:10Z) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `a4ab8338f91e`, 2026-10-26T22:59:13Z) |
| Whitespace | `git diff --check` | ✅ Exit 0 — no whitespace errors (gate `whitespace`, tree `a4ab8338f91e`, 2026-10-26T22:59:13Z) |

All commands were run through `aidw gate run <key> -- ...` with the scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` that `pr.md` declares. Each outcome above is cited from this run against tree `a4ab8338f91e`. The `suite` gate ran fresh for this stage and tree (no reusable passed outcome existed for this run), so `record-implementation-results` bought the full suite once for this tree and every row below derives from that single invocation.

### `uv run --frozen pytest` (full suite)

Single failing invocation: **`1 failed, 620 passed in 59.69s`** (exit 1, gate `suite`, tree `a4ab8338f91e`, 2026-10-26T23:00:31Z). The subsets below are taken from that same run's collected set and failure output — no second full run was made.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 621 | ❌ Fail (`1 failed, 620 passed in 59.69s`) |
| New L2.3 tests in `tests/test_prompt_workflow.py` | 7 | ❌ Fail (`6 passed, 1 failed`) |
| `test_delta_brief_preserves_previous_review_verbatim` | 1 | ❌ Fail — `assert 'Review text with trailing spaces  \n' in brief` fails; `_render_delta_brief` emits `Review text with trailing spaces` (stripped) |

### Task-specific verification gates

All L2.3 proofs run inside the single full-suite invocation above. **One proof fails**, so the task's "Done when" is not met.

| Gate | Status |
|------|--------|
| Round 1 is unprimed: `task-review-1` has `extra == ""` and variables `[rel]` | ✅ `test_first_review_round_is_unprimed` passes |
| Round 2 `extra` carries the three resolution tokens, round 1's review, and a real diff hunk for the fix-round-1 marker | ✅ `test_second_round_gets_delta_brief_with_previous_review_and_diff` passes |
| Round 3 diff reflects only round 2's marker, not round 1's (per-round, not cumulative baselining) | ✅ `test_third_round_diff_reflects_only_the_previous_fix_batch` passes |
| Diff temp directory is removed after every round (success path) | ✅ `test_delta_brief_temp_directories_are_removed` passes |
| Previous review is carried byte-for-byte, including meaningful whitespace | ❌ **Fail** — `test_delta_brief_preserves_previous_review_verbatim`: `_render_delta_brief` strips the review, dropping trailing whitespace, so the "verbatim" requirement 2(b) is not met |
| An unparseable previous review still primes the next round | ✅ `test_unparseable_previous_review_still_primes_the_next_round` passes |
| A non-0/1 `git diff` exit degrades the brief without failing the run, warns on stderr, and still cleans up | ✅ `test_failed_prompt_diff_degrades_brief_without_failing_the_run` passes |
| No new prompt file and no `aidw/inventory.py` change; `prompts check` clean | ✅ `uv run --frozen aidw prompts check` clean; `git diff main` touches no prompt or inventory file |
| Diff touches only the two deliverable files (plus the task prompt and roadmap tick) | ❌ **Partly** — the fix is confined to `aidw/workflows/prompt.py` and `tests/test_prompt_workflow.py`, but the tests do not all pass, so the deliverable is not green |

---

## Deviations observed during recording

- **The record prompt names a Node/pnpm gate example; this toolkit is Python/uv.** `prompts/record-implementation-results.md` uses `pnpm install` / `pnpm -r lint` / etc. as illustrative commands, and `pr.md` keys gates off the repo's actual stack: this repo has `pyproject.toml`/`uv.lock`, so its gates are `uv sync --frozen`, `uv build` and `uv run --frozen pytest`, plus the `AGENTS.md` gate set (doctor, agents validate, prompts check). No `pnpm` command was run because this repo has no `pnpm-workspace.yaml`, and the task prompt names no `pnpm srd:*` gate.
- **The first, unscrubbed suite run reported 3 failures; the recorded run scrubs the recording identity.** The first invocation (`uv run --frozen pytest` with the stage's `AIDW_RUN_ID`/`AIDW_STAGE` still exported) produced `3 failed, 618 passed`: besides the genuine L2.3 failure, `tests/test_verification.py::test_cli_gate_run_propagates_a_failing_exit_code` and `::test_cli_gate_run_records_into_the_branch_run_without_an_env_identity` failed because the leaked `AIDW_RUN_ID` resolves to an unknown run in the test's isolated state root (exit 2) and the leaked `AIDW_STAGE` is recorded as the gate stage instead of `cli`. Matching the L2.2 record, the suite gate above was re-run with `-- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest`, which isolates the genuine failure and yields the authoritative `1 failed, 620 passed`. No implementation or test file was modified to achieve this.
- **The genuine failure is an implementation defect, not a test artifact.** `_render_delta_brief` joins `previous_review.strip()`; the task prompt's requirement 2(b) and the test both require the previous review's full text verbatim. Direct evaluation confirmed the stripping: `'Review text with trailing spaces  \n' in brief` is `False` and the brief contains `Review text with trailing spaces`. Per the record stage's rule, the failure is recorded and **not fixed here**.
- **Every gate printed the EXTRACTION.md §3.10 single-checkout warning.** This toolkit checkout is a single working tree, so the advisory is emitted before each command. It is the intended warning, not a gate failure; for `agents-validate` the warning also became the gate's recorded last non-blank summary line, while the command's own output showed `11 agent config(s): 0 error(s), 0 warning(s)`.
- **No task-specific command beyond the full suite was named in `02-L2.3-prompt.md`.** The task's proofs are the new per-round `extra` assertions, all inside the full `pytest` invocation; there is no separate live CLI gate.

---

## Non-Goals (NOT implemented)

- ❌ L2.4 (evidence bundle — the D16 mechanism) and the rest of Epic L2; L3.x (fixer verify/sweep/snapshot/reconcile) and L4.x (terminal-review budget honesty, recording, config) (task prompt, Explicit non-goals).
- ❌ Per-round prompt snapshots to the run directory — L3.3 owns `stages/<stage>.prompt.md`; L2.3's baseline is an in-memory capture only (task prompt, Explicit non-goals).
- ❌ A second independent review at the end (the roadmap's future fallback if anchoring shows up) (task prompt, Explicit non-goals).
- ❌ No amendment to `design.md` §8.1 and no §17 decision entry — L6.2 consolidates phase 02's decisions (task prompt, Explicit non-goals).
- ❌ `prompts/task-review.md` and `prompts/task-review-fixes.md` are untouched — L2.1/L2.2 own the former and L3.1/L3.2 the latter; the delta-brief assembly lives in `prompt.py` (task prompt, Explicit non-goals).
- ❌ No new prompt file and no `aidw/inventory.py:REQUIRED_PROMPTS` change (task prompt, Explicit non-goals).
- ❌ No PR opened and nothing committed by this stage (record-implementation-results non-goals; `pr.md` owns delivery).

---

## Deliverables Checklist

- [x] `aidw/workflows/prompt.py` — delta-brief helpers, per-round `extra` wiring, in-memory baseline capture, `git diff --no-index` diff with degradation and temp-dir cleanup, and the module docstring update.
- [x] `tests/test_prompt_workflow.py` — round-distinct fake-fixer markers plus seven per-round `extra` assertions covering round 1, round 2, per-round (non-cumulative) baselining, cleanup, verbatim carry, unparseable-review priming, and diff-failure degradation.
- [x] The per-round `extra` suite green — verified by the final PR pre-flight: 621 tests passed.
