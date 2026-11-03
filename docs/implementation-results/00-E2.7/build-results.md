# Build Results — 00-E2.7: One run per worktree

**Branch:** `00-E2.7`
**Date:** 2026-11-02
**Spec:** `docs/migration/EXTRACTION.md` §3.2 (workspace and worktree model), §3.10 (state, runs, locking — D18); `design.md` §13 (git and GitHub safety), §14 (CLI exit codes)

## Summary

**Purpose:** Move the per-run mutex out of the process and into the per-repo state root, keyed by the resolved worktree path, so two concurrent `aidw` runs in the same worktree are refused while runs in different worktrees proceed.

| Decision | Why it matters |
|----------|---------------|
| `fcntl.flock(LOCK_EX \| LOCK_NB)` on a fresh descriptor per acquire, in `aidw/lock.py` | The kernel releases the flock when the holder dies, so there is no stale lock to hand-clean; `LOCK_NB` fails fast instead of hanging a non-interactive run, matching `aidw/git.py`'s convention. A cached fd would let two threads of one process both "acquire" while a real second process is still excluded. |
| Lock key is the **resolved worktree path**, hashed into one filesystem-safe filename | §3.10's `<branch>.lock` is shorthand valid only under the one-branch-one-worktree fact (§3.2); a detached-HEAD worktree has no branch, so branch-keying would leave it unguarded. Two worktrees never share a lock file. |
| Lock files live at `workspace.state_root / "locks"`, never under a target repo or worktree | §3.1/design §13: nothing generated is written into a target repo, and `git worktree remove` could otherwise delete a lock mid-run. |
| Acquire immediately before `create_run`, release in a `finally` on every exit path | The key is final at that point; the refusal happens before any run state is written (exit 4), and a post-acquire gate/stage failure cannot leave the worktree locked until process exit. Dry runs reach `create_run` too, so they take and release the same lock. |
| `_latest_implement_run`/`_latest_fix_run` stay branch-keyed and unchanged | They are the `--resume` path for a crashed `RUNNING` run (flock already released); the lock closes the race where the second process reads `state.json` before the first has written it. |
| No `state.json` schema change; `_STATE_LOCK` and `--parallel` untouched | The lock is a filesystem mutex, not recorded state; `_STATE_LOCK` serialises `state.json` writes between stages *inside* one run and `--parallel` means concurrent stages in one worktree — §3.2 says "do not conflate the two". |

**Where it fits in the roadmap:** E2.7 in the extraction epic, following E2.1 (macOS/Linux support), E2.4 (worktree location) and E2.6 (missing-worktree refusal, whose fail-closed exit-4 contract this reuses). It depends on the state-root resolution (`WorkspacePaths.resolve`) and the worktree locators (`TargetRepo.resolve`, `git.worktree_for_branch`). E2.8 (doctor worktree/git health checks) and E2.9 (shared worktree test fixture) are the follow-on tasks that build on this lock and its test harness.

**Scope:** A new `aidw/lock.py` primitive plus wiring into all five workflows (`prompt`, `implement`, `review`, `fix`, `approve`) and the delegation note in `run`. `run.py` itself acquires nothing — it calls each workflow, which takes and releases its own key in turn. Tests cover the primitive cross-process (real bare repo + worktrees, a subprocess holder), same-key refusal on every workflow key path, different-worktree proceed, dry-run locking, release on every exit path, purity, and prompt's task-worktree wiring. It deliberately stops short of re-keying the resume guard, any global/read-write lock, Windows support, and a doctor check for lock health.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `aidw/lock.py` | Created | Cross-process run lock: `flock`-based acquire/release, state-root `locks/` location, deterministic worktree-path key, `LockHeldError` refusal. |
| `tests/test_lock.py` | Created | Primitive tests: per-worktree filenames, cross-process exclusion and auto-release on holder death, same-process second-fd refusal, idempotent release, purity, no run state on refusal. |
| `docs/task-prompts/00-E2.7-prompt.md` | Created | Task prompt (committed on the branch). |
| `aidw/workflows/prompt.py` | Modified | Acquires/releases the created task-worktree key around `create_run`; refusal returns `EXIT_REFUSED` (4); module docstring documents the key and dry-run behaviour. |
| `aidw/workflows/implement.py` | Modified | Acquires/releases the located worktree key (`target.root`) around the run body; exit 4 before any run state on a held lock. |
| `aidw/workflows/fix.py` | Modified | Acquires/releases the re-resolved PR-head worktree key; exit 4 on refusal; resume guard left branch-keyed. |
| `aidw/workflows/review.py` | Modified | Acquires/releases the invocation `repo.root` key; exit 4 before `create_run`. |
| `aidw/workflows/approve.py` | Modified | Acquires/releases the invocation `repo.root` key; exit 4 before `create_run`. |
| `aidw/workflows/run.py` | Modified | Docstring only: records that `run` takes no lock itself and each delegated workflow takes its own. |
| `tests/test_implement_workflow.py` | Modified | Same-worktree refusal, different-worktree proceed, refusal before run state, dry-run lock, release on every exit path. |
| `tests/test_fix_workflow.py` | Modified | PR-head worktree refusal/proceed, refusal before run state, release after the run. |
| `tests/test_review_workflow.py` | Modified | Same-`repo.root` refusal, refusal before run state, release on every exit path. |
| `tests/test_approve_workflow.py` | Modified | Same-`repo.root` refusal, refusal before run state, different-worktree proceed and shared state, release on every exit path. |
| `tests/test_prompt_workflow.py` | Modified | Proves the task-worktree key is held for the whole `prompt.run` and free after it exits. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E2.7 complete. |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.90ms` (frozen lock consistent) |
| Build | `uv run --frozen aidw gate run build --ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv build --out-dir <tmp>` | ✅ `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` built (gate `build`, tree `c66b3c256049`, stage `record-implementation-results`, 2026-11-02T22:53:05Z) |
| Test | `uv run --frozen aidw gate run suite --ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv run --frozen pytest` | ✅ `791 passed in 23.64s` (gate `suite`, tree `c66b3c256049`, stage `record-implementation-results`, 2026-11-02T22:53:31Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ exit 0 — 14 checks: 0 failed, 2 warnings (dirty working tree; missing `.mcp.json`) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ exit 0 — `prompts check: 0 error(s), 0 warning(s)` |
| Whitespace | `git diff --check` | ✅ exit 0, no whitespace errors |
| Lint | — | **unverified** — the repository configures no linter/formatter (`AGENTS.md` §Gates: pytest is the only verification; none is added inside an unrelated task) |

### `uv run --frozen pytest` (full suite)

Every row is derived from the single full-suite gate invocation above; the per-file counts come from `uv run --frozen pytest --collect-only -q <files>` (collection only — no test was re-run).

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 791 | ✅ Pass (`791 passed in 23.64s`) |
| `tests/test_lock.py` | 9 | ✅ Pass (part of the full-suite run) |
| `tests/test_implement_workflow.py` | 42 | ✅ Pass (part of the full-suite run) |
| `tests/test_fix_workflow.py` | 20 | ✅ Pass (part of the full-suite run) |
| `tests/test_review_workflow.py` | 11 | ✅ Pass (part of the full-suite run) |
| `tests/test_approve_workflow.py` | 12 | ✅ Pass (part of the full-suite run) |
| `tests/test_prompt_workflow.py` | 135 | ✅ Pass (part of the full-suite run) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Cross-process exclusion and auto-release (real bare repo + worktrees; subprocess holder; parent refused for A, acquires B, re-acquires A after holder exit) | ✅ `tests/test_lock.py::test_holder_in_another_process_excludes_and_its_death_auto_releases` and `test_a_second_descriptor_in_one_process_is_refused` pass |
| Same-key refusal on every workflow key path (implement/fix located worktree, review/approve `repo.root`, prompt task worktree) | ✅ Covered by `test_two_concurrent_*` / `test_a_held_*` in all five workflow test files; full suite green |
| Different-worktree proceed | ✅ `test_two_concurrent_runs_in_different_worktrees_both_proceed`, `test_fix_runs_in_different_worktrees_proceed`, `test_approvals_from_different_worktrees_both_proceed`, plus the primitive's A/B paths |
| Refusal is exit 4, names the worktree path, creates no run directory | ✅ `test_a_held_*_lock_is_refused_before_any_run_state` assert code 4, the worktree path in stderr, and no run directory; `test_a_refusal_creates_no_run_state` |
| Dry run takes the same lock and releases it | ✅ `test_the_dry_run_takes_the_same_worktree_lock` |
| Release on every exit path (success, stage failure, gate refusal) | ✅ Parametrised `test_*_lock_is_released_on_every_exit_path` / `test_*_released_after_the_run` |
| Purity: the only lock file is under `<state root>/locks`, nothing written under the worktree | ✅ `test_acquiring_writes_only_the_lock_file_under_the_state_root`, `test_each_worktree_gets_its_own_lock_file_under_the_state_root` |
| Prompt wiring: task-worktree key held while `prompt.run` runs, free after | ✅ `tests/test_prompt_workflow.py::test_the_task_worktree_key_is_held_for_the_whole_run_and_free_after` |
| `rg "locks" aidw/` shows the only lock location is `workspace.state_root / "locks"` | ✅ Only `aidw/lock.py` defines `locks_dir`/`LOCKS_DIRNAME`; no target-repo or worktree lock path |
| `rg "threading.Lock" aidw/workflows aidw/lock.py` has no hits | ✅ No hits |
| Resume guard unchanged and branch-keyed | ✅ `_latest_implement_run`/`_latest_fix_run` untouched by the diff |

---

## Deviations observed during recording

- **Task-specific gate not re-run as a standalone subset** — the task prompt's "Done when" names a subset `pytest` invocation. That subset is exercised by the single full-suite gate above; per-file counts were taken with `--collect-only` rather than a second run, so no test was executed twice.
- **`uv.lock` unchanged and `uv sync --frozen` clean** — confirming the stdlib-only (`fcntl`) implementation introduced no dependency, as required.
- **No lint gate exists** — the repository configures no linter (per `AGENTS.md`), so the row is marked unverified rather than invented.

---

## Non-Goals (NOT implemented)

- ❌ E2.8 doctor worktree/git checks — no doctor check for lock health or leftovers (`docs/task-prompts/00-E2.7-prompt.md`, non-goals).
- ❌ E2.9 shared worktree fixture — tests build local bare+worktree helpers instead (`docs/task-prompts/00-E2.7-prompt.md`, non-goals).
- ❌ Re-keying the resume guard to worktree path or merging it into the lock — `_latest_implement_run`/`_latest_fix_run` stay branch-keyed (`docs/task-prompts/00-E2.7-prompt.md`, requirement 5).
- ❌ Whole-repo/global lock, read-write (shared) locking, or a lock in `run.py` — only "one run per worktree" (`docs/task-prompts/00-E2.7-prompt.md`, non-goals; EXTRACTION.md §3.2).
- ❌ Windows/non-POSIX support — macOS/Linux only, `fcntl` is fine (`docs/task-prompts/00-E2.7-prompt.md`, non-goals).
- ❌ No commit, push, or PR opened — `/record-implementation-results` owns only this document (`prompts/pr.md` owns delivery).
