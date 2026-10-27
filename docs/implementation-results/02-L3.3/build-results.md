# Build Results — 02-L3.3: Snapshot the prompt at every fix stage

**Branch:** `02-L3.3`
**Date:** 2026-10-27
**Spec:** `docs/tasks/02 - Prompt loop integrity.md` — task L3.3 ("Snapshot the prompt at every fix stage"), Epic L3 ("Fixer integrity — stop the churn"), including the Epic L3 ordering (L3.3 sits after L3.2, before L3.4) and the "Explicit non-goals for phase 02". `design.md` §9.1 (run-directory layout: `stages/` holds `<name>.jsonl` / `.out.txt` / `.meta.json`; the snapshot joins it as `<stage>.prompt.md`, and nothing goes under `artifacts/` or `prompts/`). `design.md` §8.1 (`aidw prompt` P2a fix loop: stage names `task-review-fixes-N` and `task-review-fixes-N-M`, one stage per blocking finding, `could-fix` batched, whole-review fallback, single final commit of the owned prompt path). `AGENTS.md` (Gates; Tests — fake-stage pattern, no real Pi model).

## Summary

**Purpose:** Before each fix stage runs, write the prompt's on-disk content to `<run_dir>/stages/<stage>.prompt.md` so every fix stage's input is recoverable, ending the "fixers cannot tell their own diff from their predecessors'" churn.

| Decision | Why it matters |
|----------|---------------|
| The snapshot is taken **before** `run_stage`, at both fix call sites (the `if not findings or problems:` fallback and the `for index, (kind, group) in enumerate(steps)` loop) | Capture-before-run makes `snapshot(i)` exactly stage `i`'s input: it carries every earlier fix stage's mutation and none of its own. `_fake_stages` appends a round marker *inside* the fix stage, so ordering is observable and a capture-after-regression would fail the input-of-stage test. |
| `_write_prompt_snapshot` reuses `_capture_prompt(prompt_path)` and writes `stages/<stage>.prompt.md` under the run directory | The snapshot is a plain run-dir artifact like L2.4's `.evidence.md`, not a new `state.json` field and not a findings-manifest key. Paths under the run dir are machine-local and never committed (design §13). |
| The `.prompt.md` suffix is distinct from `.evidence.md`, `.jsonl`/`.out.txt`/`.meta.json`, and the `_prompt_diff` `baseline/`/`current/` names | No two writers can collide on a path; the L3.3 snapshot never lands in `_DIFF_TMP_PREFIX`, whose `finally: shutil.rmtree(...)` would delete a snapshot at run end. |
| `_snapshot_fix_stage` is a warn-and-continue guard mirroring `_write_evidence_bundle`; an unreadable prompt (`None`) or an `OSError` write warns on stderr and lets the stage run | The snapshot is recoverability, not a gate. A read-only or odd run directory must not kill the whole prompt run for a nicety; the roadmap leaves the failure mode unspecified and the L2.4 bundle's warn-and-continue is the repo precedent. |
| `_commit_reviewed_prompt` is untouched — it still commits exactly `[rel]` after the loop | No per-stage commits and no snapshot in the single final commit; adding the snapshot path would violate "not tracked by git" and "single final commit" (design §18 risk row). |

**Where it fits in the roadmap:** Phase 02, Epic L3 ("Fixer integrity — stop the churn"), and its third task. It builds directly on L3.1 (verify-then-fix) and L3.2 (post-edit document sweep) and precedes L3.4 (reconcile stage after each fix batch) and L4.x (terminal review, revision budget, recording). It reuses the L2.4 evidence-bundle pattern (path under the run dir, degrade-never-gate) and opens no `design.md` §17 entry — L6.2 consolidates phase 02's decisions.

**Scope:** Adds the snapshot section to `aidw/workflows/prompt.py` (`_SNAPSHOT_SUFFIX`, `_write_prompt_snapshot`, `_snapshot_fix_stage`), wires the guard before both fix-stage `run_stage` calls, documents the artifact in the module docstring, adds seven L3.3 test instances to `tests/test_prompt_workflow.py`, and ticks the L3.3 roadmap checkbox. It deliberately stops short of L3.4's reconcile stage, L4.1's `MAX_REVISIONS`/last-round acceptance path, any change to loop batching or the commit behaviour, any `design.md` §9.1 layout-diagram edit, and any `state.json` or findings-manifest field.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L3.3-prompt.md` | Created (committed) | The task prompt authored on the branch before implementation (commit `038ea5e`). |
| `aidw/workflows/prompt.py` | Modified (uncommitted) | Added the L3.3 snapshot section: `_SNAPSHOT_SUFFIX = ".prompt.md"`, `_write_prompt_snapshot` (reads via `_capture_prompt`, lazily creates `stages/`, writes under the run dir, returns `None` on unreadable prompt), and the warn-and-continue `_snapshot_fix_stage` guard; called before both fix-stage `run_stage` sites (whole-review fallback `task-review-fixes-<revisions>` and per-finding/combined `task-review-fixes-<revisions>-<index>`); documented the artifact in the module docstring. |
| `tests/test_prompt_workflow.py` | Modified (uncommitted) | Added seven L3.3 test instances plus `_snapshot_path` / `_committed_paths` helpers: two snapshots in stage order, per-stage-input content (capture-before-run), fallback snapshot, untracked/not-committed (single path-scoped commit, no `state.json` field), warn-only degrade on a raising writer, unreadable-prompt `None` + warning, and verbatim-copy/purity. |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified (uncommitted) | Roadmap escalation: L3.3 checkbox ticked (traceability artifact owned by the update-traceability stage). |

---

## Verification Results

> **This run passed.** Every gate below was run through `aidw gate run <key> -- …` with the `pr.md` scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`, against tree `3895efc31d2d` (the tree that includes the uncommitted working-tree change set) by stage `record-implementation-results`. Every outcome is a real observation from this run; none was copied from an earlier run or document.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Exit 0 — `Checked 15 packages in 0.69ms` (gate `install`, tree `3895efc31d2d`, 2026-10-27T09:26:16Z) |
| Build | `uv build --out-dir <tmp>` | ✅ Exit 0 — built `aidt-0.1.0-py3-none-any.whl` and `aidt-0.1.0.tar.gz` (gate `build`, tree `3895efc31d2d`, 2026-10-27T09:26:21Z) |
| Test | `env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ✅ Exit 0 — **`639 passed in 66.56s`** (gate `suite`, tree `3895efc31d2d`, 2026-10-27T09:27:31Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)` (branch `02-L3.3` dirty; `.mcp.json` absent) (gate `doctor`, tree `3895efc31d2d`, 2026-10-27T09:27:38Z) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `3895efc31d2d`, 2026-10-27T09:27:39Z) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `3895efc31d2d`, 2026-10-27T09:27:39Z) |
| Whitespace | `git diff --check` | ✅ Exit 0 — no whitespace errors (gate `whitespace`, tree `3895efc31d2d`, 2026-10-27T09:27:40Z) |

The `suite` gate ran fresh for this stage and tree (no reusable outcome existed for this run's key), so `record-implementation-results` bought the full suite once for tree `3895efc31d2d`; the subset row below derives from that single invocation.

### `env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` (full suite)

Single invocation: **`639 passed in 66.56s`** (exit 0, gate `suite`, tree `3895efc31d2d`, 2026-10-27T09:27:31Z). No second run was made to obtain the subset row; the seven new tests are part of the collected set that run reported green (the change set adds exactly seven test functions and the run reported zero failures — 639 is the L3.2 recording's 632 plus those seven).

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 639 | ✅ Pass (`639 passed in 66.56s`) |
| New L3.3 tests in `tests/test_prompt_workflow.py` | 7 | ✅ Pass (part of the 639-passed run; zero failures) |

### Task-specific verification gates

The task's proofs are the seven new `test_prompt_workflow.py` assertions, all inside the single full-suite invocation above; there is no separate live CLI gate.

| Gate | Status |
|------|--------|
| Two-fix-stage run leaves `stages/task-review-fixes-1-1.prompt.md` and `stages/task-review-fixes-1-2.prompt.md`, in stage order | ✅ `test_l33_every_fix_stage_gets_a_snapshot_in_stage_order` passes |
| Input-of-stage property: snapshot `1-1` is the prompt before any fix marker, snapshot `1-2` is the prompt after `1-1`'s mutation; the consecutive delta is exactly the preceding stage's change (capture-before-run) | ✅ `test_l33_snapshot_is_the_input_to_its_fix_stage` passes |
| Unparseable review (`TASK_REVIEW_UNPARSEABLE`) still writes the fallback `stages/task-review-fixes-1.prompt.md` | ✅ `test_l33_fallback_whole_review_fix_also_gets_a_snapshot` passes |
| Snapshots are untracked run-dir artifacts: `git.untracked_paths` lists the snapshot, the single reviewed-prompt commit is exactly `["docs/task-prompts/03-E4.1-prompt.md"]`, no `.prompt.md` path is committed, and `state.json` contains no `.prompt.md` field | ✅ `test_l33_snapshots_are_not_tracked_and_not_committed` passes |
| Degrade-never-gate: a raising snapshot writer still lets both fix stages and the run succeed (warn-only, exit 0) | ✅ `test_l33_snapshot_write_failure_is_warn_only` passes |
| Unreadable prompt warns and returns `None` without creating `stages/` or raising | ✅ `test_l33_unreadable_prompt_skips_the_snapshot_with_a_warning` passes |
| The snapshot is a verbatim copy and the source prompt is not mutated | ✅ `test_l33_snapshot_writer_copies_the_prompt_verbatim` passes |
| `uv run aidw prompts check` and `uv run aidw agents validate --strict` stay green | ✅ both clean (see top-level table) |
| Diff touches only the two deliverable files plus the task prompt and roadmap tick | ✅ Change set is exactly `aidw/workflows/prompt.py`, `tests/test_prompt_workflow.py`, `docs/task-prompts/02-L3.3-prompt.md`, `docs/tasks/02 - Prompt loop integrity.md` |

---

## Deviations observed during recording

- **The record prompt names a Node/pnpm gate example; this toolkit is Python/uv.** `prompts/record-implementation-results.md` uses `pnpm install` / `pnpm -r lint` / `pnpm -r build` / `pnpm -r test` as illustrative commands, and `pr.md` keys gates off the repo's actual stack. This repo has `pyproject.toml`/`uv.lock`, so its gates are `uv sync --frozen`, `uv build`, `uv run --frozen pytest`, plus the `AGENTS.md` gate set (doctor, agents validate, prompts check). No `pnpm` command was run because this repo has no `pnpm-workspace.yaml`, and the task prompt names no `pnpm srd:*` gate.
- **`git diff --stat main...HEAD` understates the change set.** It shows only the committed task prompt (`docs/task-prompts/02-L3.3-prompt.md`); the implementation lives in the uncommitted working tree, so the change set recorded here is `git diff main` (committed + working tree), not the merge-base diff alone.
- **The suite gate runs under `env -u AIDW_STAGE -u AIDW_RUN_ID`.** The record stage runs with `AIDW_RUN_ID=20261027T090559Z-02-L3.3-implement` and `AIDW_STAGE=record-implementation-results` exported; prior recordings showed the leaked identity makes `tests/test_verification.py`'s gate-run tests fail against an unknown run and record the wrong stage. The suite gate scrubs both variables for the pytest subprocess (the outer `aidw gate run` still reads them to record the outcome). No implementation or test file was modified to achieve this.
- **Every gate printed the EXTRACTION.md §3.10 single-checkout warning.** This checkout is a single working tree, so the advisory is emitted before each command. It is the intended warning, not a gate failure; for `agents-validate` the warning became the gate's recorded last non-blank summary line, while the command's own output showed `11 agent config(s): 0 error(s), 0 warning(s)`.
- **No task-specific command beyond the full suite was named in `02-L3.3-prompt.md`.** The task's proofs are the seven new `test_prompt_workflow.py` assertions inside the full `pytest` invocation; there is no separate validator or smoke script to run.

---

## Non-Goals (NOT implemented)

- ❌ L3.4 (reconcile stage after each fix batch) — the next task in the same epic; no new stage was added to the loop (task prompt, Explicit non-goals).
- ❌ L4.1 (terminal review / revision-budget semantics) — `MAX_REVISIONS` and the last-round acceptance path are untouched (task prompt, Explicit non-goals).
- ❌ No change to commit behaviour: no per-stage commits and no committing the run directory (`AGENTS.md` "Run state is machine-local and never committed"; design §13; task prompt, Explicit non-goals).
- ❌ `design.md` §9.1's layout diagram is not edited — it is illustrative (L2.4's `.evidence.md` artifacts are not listed there either); L6.2 consolidates phase-02 decisions (task prompt, Explicit non-goals).
- ❌ No `state.json` field and no findings-manifest field — the snapshot is a run-dir artifact only (task prompt, Explicit non-goals).
- ❌ No PR opened and nothing committed by this stage (record-implementation-results non-goals; `pr.md` owns delivery).

---

## Deliverables Checklist

- [x] `aidw/workflows/prompt.py` — `_SNAPSHOT_SUFFIX`, `_write_prompt_snapshot`, `_snapshot_fix_stage`, both fix-stage call sites wired, module-docstring update.
- [x] `tests/test_prompt_workflow.py` — `_snapshot_path`/`_committed_paths` helpers plus seven L3.3 test instances (stage order, per-stage input, fallback, untracked/not-committed, warn-only degrade, unreadable prompt, verbatim copy).
- [x] The L3.3 suite is green — `639 passed in 66.56s` (`7` new L3.3 tests included).
- [x] A two-fix-stage run leaves exactly two `stages/*.prompt.md` files, and the final prompt remains a single commit of the prompt path with no snapshot and no per-stage commits.
