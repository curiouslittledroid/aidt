# Build Results — 02-L1.2: Refuse to author a task whose predecessors are incomplete

**Branch:** `02-L1.2`
**Date:** 2026-10-26
**Spec:** `docs/tasks/02 - Prompt loop integrity.md` — task L1.2 ("Refuse to author a task whose predecessors are incomplete"), Epic L1 ("Scheduling and preflight — stop the bad seed"), including the phase preamble's E1.6 evidence and the phase's "How this phase is driven" ordering note. `design.md` §8.1 (`aidw prompt` preflight), §11 (Roadmap task selection), §14 (CLI reference). `docs/migration/EXTRACTION.md` §3.7 (Roadmap format). `AGENTS.md` (Gates; Tests).

## Summary

**Purpose:** Make `aidw prompt` refuse to author a task while earlier tasks in the same `docs/tasks/*.md` phase file are still unticked, so the roadmap — not the author's judgement — is the ordering authority, and the E1.6 failure (a prompt authored against a base that lacked a merged prerequisite, with the missing prerequisite smuggled into the prompt text) cannot recur.

| Decision | Why it matters |
|----------|---------------|
| Predecessors are the target's own `RoadmapTask.file` with `line <` the target's line and `done` false | Roadmap line order is the authority, never epic-id order (a later-sorting epic can sit on an earlier line); filtering on `file` rather than `phase` keeps phase 00's ~45 unticked entries from blocking every other phase's runs. |
| The predecessor list is computed once, after `find_task` and before the `dry_run` split | The dry-run note and the real-run refusal read the same list, so they cannot disagree. `run()` already holds the parsed entries, so no roadmap file is re-read. |
| The refusal sits inside the real-run preflight after the current-branch and clean-tree checks and immediately before `_verify_base_branch` | A purely local, in-memory ordering failure is reported before any network fetch; a run that is both on the wrong branch and out of order reports the branch refusal first, and an out-of-order run with an unreachable `origin` refuses without fetching. |
| `--allow-incomplete-prereqs` warns naming every skipped predecessor and proceeds; nothing else bypasses the check | Deliberate out-of-order authoring is an explicit, recorded choice. |
| `--dry-run` reports the incomplete predecessors (or states there are none) and returns 0 | The plan-only contract is preserved; dry-run never refuses and stays hermetic (no fetch, no target-repo writes). |

**Where it fits in the roadmap:** Phase 02, Epic L1 ("Scheduling and preflight — stop the bad seed"). It builds on L1.1's preflight (branch, clean tree, base-branch fetch) and is the second of L1's three stops: L1.2 closes the "author against a stale prerequisite" hole in-memory, and the still-open L1.3 gives the author a `blocked:` channel for the cases a roadmap gate cannot see. The check is intentionally phase-scoped and ordering-based; cross-phase gating and a per-task `requires:` field are explicitly out of scope (E5.1/E5.2 own any roadmap-format change, and D15 forbids a second dialect). L1.2's own gate applies to this phase, so the roadmap's task order is the build order.

**Scope:** Adds `_incomplete_predecessors`/rendering/warn helpers and the preflight branch to `aidw/workflows/prompt.py`, the `--allow-incomplete-prereqs` CLI option to `aidw/cli.py`, 12 tests to `tests/test_prompt_workflow.py`, and the §8.1/§14 design lines. It deliberately stops short of L1.3, L2.x–L5.x, cross-phase prerequisites, any change to the roadmap parser / `find_task` / `RoadmapTask` / `aidw tasks`, and any change to L1.1's base-branch check or the existing branch/clean-tree refusals.

---

## Files Changed

The change set is the working tree relative to `main`. The implementation, tests, design edit and roadmap tick are uncommitted; the task prompt was committed earlier on the branch (`0ffbb03`).

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L1.2-prompt.md` | Created (committed) | The task prompt authored on the branch before implementation. |
| `aidw/workflows/prompt.py` | Modified | Added `_incomplete_predecessors`, `_render_predecessors`, `_refuse_incomplete_predecessors`, `_warn_incomplete_predecessors`; added the `allow_incomplete_prereqs` parameter; computed the predecessor list once before the dry-run split; refused (exit 4) for incomplete predecessors after the branch/clean checks and before `_verify_base_branch`; warned-and-proceeded under the flag; dry-run reports the list and never refuses. |
| `aidw/cli.py` | Modified | Added the `--allow-incomplete-prereqs` option on the `prompt` command and threaded it into `prompt_workflow.run`. |
| `tests/test_prompt_workflow.py` | Modified | Extended `_patch_prompt_repo`/`_origin_and_clone` with injectable roadmaps and a second phase file; added 12 L1.2 tests plus five roadmap fixtures covering the refusal, the ordered message, ticked/later/other-file cases, the flag, dry-run, cheap-failure ordering and CLI forwarding. |
| `design.md` | Modified | §8.1 preflight description gained one behaviour sentence; §14 `aidw prompt` usage line gained `[--allow-incomplete-prereqs]`. |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified | Roadmap escalation: L1.2 checkbox ticked (traceability artifact owned by the implement stage). |

---

## Changes Made

### 1. `aidw/workflows/prompt.py`

- `_incomplete_predecessors(entries, entry)` returns the entries with `candidate.file == entry.file`, `candidate.line < entry.line` and `not candidate.done`, preserving roadmap order.
- `_render_predecessors` prints one `  {id} — {title}` line per predecessor; the refusal never collapses the set to a count.
- `_refuse_incomplete_predecessors` prints the target, its phase file, the ordered predecessor list, and both ways forward (tick once merged, since a merged task can still be unticked; or re-run with the flag), then returns `EXIT_REFUSED` (4).
- `_warn_incomplete_predecessors` prints the same list under the flag and continues.
- `run()` computes `incomplete` immediately after `find_task` and before the `dry_run` split. The real-run branch checks it after the branch and clean-tree refusals and before `_verify_base_branch`; the dry-run branch prints the list (or "no incomplete predecessors") and returns the normal plan.

### 2. `aidw/cli.py`

- `--allow-incomplete-prereqs` option on `prompt`, documented as authoring out of order, passed to `prompt_workflow.run`.

### 3. `tests/test_prompt_workflow.py`

- `_patch_prompt_repo` gained optional `roadmap` and `extra_files`; `_origin_and_clone` gained an optional `roadmap`, so the ordering tests use the lightweight no-origin repo unless network ordering is under test.
- Fixtures cover: an unticked earlier task, all-ticked predecessors, an earlier line in a later-sorting epic, a later unticked sibling, a second phase file, and multiple predecessors in order.
- The 12 tests pin the exit code and message content, no run directory/branch/prompt on refusal, the ordered list, ticked-state semantics, the later-sibling and other-file non-refusals, the warn-and-proceed flag, both dry-run cases, the no-fetch-on-refusal ordering, the branch-refusal-first ordering, and CLI forwarding.

### 4. `design.md`

- §8.1 gained the ordering-refusal sentence; §14's usage line lists `[--allow-incomplete-prereqs]`. No §17 entry (phase 02's L6.2 consolidates this phase's decisions).

---

## Verification Results

> **Overall gate: ✅ PASS.** `uv run --frozen pytest` produced **`594 passed in 58.70s`**; install, build, doctor, agent validation and prompts check all passed. No gate was re-run for a count; every row below is from the single invocation named in its row.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Exit 0 — `Checked 15 packages in 0.87ms` (gate `install`, tree `0d36a9ee4d0d`, stage `record-implementation-results`, 2026-10-26T11:22:32Z) |
| Build | `uv build --out-dir <tmp>` | ✅ Exit 0 — built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` (gate `build`, tree `0d36a9ee4d0d`, 2026-10-26T11:22:44Z) |
| Test | `uv run --frozen pytest` | ✅ Exit 0 — **`594 passed in 58.70s`** (gate `suite`, tree `0d36a9ee4d0d`, 2026-10-26T11:23:52Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)` (gate `doctor`, tree `0d36a9ee4d0d`, 2026-10-26T11:22:35Z) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `0d36a9ee4d0d`, 2026-10-26T11:22:36Z) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `0d36a9ee4d0d`, 2026-10-26T11:22:37Z) |
| Whitespace | `git diff --check` | ✅ Exit 0 — no whitespace errors |

All gates were run through `aidw gate run <key> -- ...` with the scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` that `pr.md` declares (the write-targets of the other stages). Each outcome above is cited from that run (`0d36a9ee4d0d`) and was not re-run; `/pr` can cite `reused:` lines against the same tree.

### `uv run --frozen pytest` (full suite)

Single invocation: **`594 passed in 58.70s`** (exit 0, gate `suite`). The subsets below are counts from the same run's set — the file defines 43 top-level test functions, all collected and green in the 594; no second run was made.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 594 | ✅ Pass (`594 passed in 58.70s`) |
| `tests/test_prompt_workflow.py` (within the full suite) | 43 | ✅ Pass (all 43 green; 31 pre-existing + 12 added) |
| L1.2 tests added in this task (within the full suite) | 12 | ✅ Pass (12 of the 594) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Incomplete predecessor refuses with `EXIT_REFUSED` (4), naming file, target and predecessor, leaving no run directory, no branch and no prompt file | ✅ `test_l12_incomplete_predecessor_refuses_without_writing` |
| The refusal lists every predecessor in roadmap order, one `id — title` per line (never a bare count) | ✅ `test_l12_refusal_names_all_predecessors_in_roadmap_order` |
| All predecessors ticked proceeds — the gate reads `[x]` state, not task count | ✅ `test_l12_all_predecessors_ticked_proceeds` |
| A later unticked sibling does not block the target | ✅ `test_l12_later_unticked_sibling_does_not_block` |
| An earlier line in a later-sorting epic still blocks — line order beats epic order | ✅ `test_l12_line_order_beats_epic_order` |
| An unticked entry in another phase file does not block — the `file` filter | ✅ `test_l12_other_phase_file_does_not_block` |
| `--allow-incomplete-prereqs` proceeds (exit 0) with a warning naming each skipped predecessor | ✅ `test_l12_allow_incomplete_prereqs_warns_and_proceeds` |
| `--dry-run` reports the incomplete predecessors and writes no prompt file | ✅ `test_l12_dry_run_reports_incomplete_predecessors` |
| `--dry-run` states when there are none | ✅ `test_l12_dry_run_states_when_there_are_none` |
| The ordering refusal precedes the `origin` fetch (no `git.fetch` call) | ✅ `test_l12_refusal_precedes_the_origin_fetch` |
| On the wrong branch and out of order, the branch refusal is reported first | ✅ `test_l12_wrong_branch_refusal_precedes_the_prerequisite_check` |
| The CLI flag is forwarded to `prompt_workflow.run` | ✅ `test_l12_cli_flag_is_forwarded_to_prompt_workflow` |
| Live CLI refusal end to end | ✅ `aidw --repo <clean main clone> prompt 00 E2 E2.3` → exit 4; `refusing: cannot author `E2.3` in phase file `00 - Extraction.md` … E2.2 — Target/layout guards`; the clone stayed clean with no `00-E2.3` branch. The target id was derived at run time (`E2.2` is the first unticked phase-00 entry and `E2.3` the first with an unticked predecessor). |
| Live dry-run on the current tree | ✅ `aidw prompt 00 E2 E2.3 --dry-run` → exit 0; `[dry-run] incomplete predecessors for `E2.3` in `00 - Extraction.md`: E2.2 — Target/layout guards`. |

---

## Deviations observed during recording

- **The live CLI refusal was proven on a clean `main` clone, not the current tree.** The task prompt's "Done when" asks for a live refusal "on the current tree". The current tree is on branch `02-L1.2` and dirty, so the current-branch and clean-tree checks — which precede the prerequisite refusal by design (requirement 2) — fire first: `aidw prompt 00 E2 E2.3` prints `` `aidw prompt` must run on `main`; currently on `02-L1.2`. `` and exits 4 without naming the predecessor. That ordering is itself pinned by `test_l12_wrong_branch_refusal_precedes_the_prerequisite_check`. The end-to-end refusal was therefore run against a temporary clean `main` clone carrying the L1.2 code (exit 4, predecessor named, clone untouched), and the current tree's wiring was shown with `--dry-run`, which reports the same predecessor list and returns 0. No code or roadmap file was changed to enable this.
- **The full-suite gate needed the child's recorder identity scrubbed.** `aidw gate run suite -- env -u AIDW_RUN_ID -u AIDW_STAGE uv run --frozen pytest` was used because the recorder's own `AIDW_RUN_ID`/`AIDW_STAGE` leak into the pytest process and break two pre-existing, unrelated tests (`test_cli_gate_run_propagates_a_failing_exit_code`, `test_cli_gate_run_records_into_the_branch_run_without_an_env_identity`) that assume no ambient run identity. CI runs the same command in a clean environment, and the L1.1 record used the same scrub. The gate's command string is therefore env-wrapped, so a `/pr` run of the bare `uv run --frozen pytest` will not `reused:`-match it; the recorded `594 passed` is nonetheless this run's own observation of this tree.
- **Every gate printed the EXTRACTION.md §3.10 single-checkout warning.** This toolkit checkout is a single working tree, so `_roots` emits the advisory before each command. It is the intended warning, not a gate failure.
- **`--dry-run` creates the run directory and `state.json`.** This is pre-existing (`create_run` runs before the dry-run return on `main` too) and is not introduced by L1.2; "no writes" in the task means no target-repo writes (no branch, no prompt file). No run state is committed.

---

## Non-Goals (NOT implemented)

- ❌ L1.3 (give the author a blocked channel) and the other epics L2.x/L3.x/L4.x/L5.x (task prompt).
- ❌ Cross-phase prerequisites — phase 01's prose gate table stays prose; no dependency graph and no `requires:` field (task prompt; design §17 / E5.1 / E5.2 own any format change).
- ❌ Any change to the roadmap parser, `find_task`, `RoadmapTask`, `aidw tasks`, or `docs/tasks/00 - Extraction.md` including its unticked entries (task prompt).
- ❌ Any change to L1.1's base-branch check, `--no-fetch`, or the existing current-branch and clean-tree refusals (task prompt).
- ❌ A new flag on `aidw run task-to-pr` (it inherits the default); E2.5/E4.1 own restructuring the preflight (task prompt).
- ❌ No commit, push, or PR opened — the delivery stage owns that (this recording stage).
