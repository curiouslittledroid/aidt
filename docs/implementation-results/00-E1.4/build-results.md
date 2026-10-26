# Build Results — 00-E1.4: Port consumers and delete the old helpers

**Branch:** `00-E1.4`
**Date:** 2026-10-26
**Spec:** `docs/migration/EXTRACTION.md` §2 (Locked decisions, row D18), §3.1 (Two roots — the "Nothing generated…" rule + two-types rule), §3.10 (State, runs, locking, D18), §4.1 (Code: small — the `aidw/paths.py` coupling row), §10 (Decisions resolved while writing this document, row R1). Roadmap: `docs/tasks/00 - Extraction.md` Epic E1, task E1.4.

> **Template note:** `prompts/record-implementation-results.md` (and `aidt/prompts/record-implementation-results.md`) instructs this stage to use `docs/implementation-results/TEMPLATE.md`, and `docs/migration/EXTRACTION.md` §config names `build_results_template: docs/implementation-results/TEMPLATE.md`. **That file does not exist anywhere in this repository or its history** (`find`/`git log` both empty), as already recorded in `docs/implementation-results/00-E1.3/build-results.md`. This document therefore follows the structure established by the three existing results documents, `docs/implementation-results/00-E1.1/build-results.md`, `00-E1.2/build-results.md` and `00-E1.3/build-results.md`, which are the de-facto template in this repo. No placeholders remain.

## Summary

**Purpose:** Port every consumer of the transitional helpers off `aidt_root()`/`runs_dir()`, delete both from `aidw/paths.py`, and move run artifacts from the toolkit root (`<toolkit>/runs`) to the per-repository state root (`<workspace root>/.aidw/state/<slug>/runs`, EXTRACTION.md §3.10). The Done-when `rg "aidt_root|runs_dir" aidw/` is literal: it must match nothing, including surviving parameter/local names.

| Decision | Why it matters |
|----------|---------------|
| `run_stage`'s toolkit-root `runs_dir` fallback is deleted; `runs_root` becomes a required keyword argument | The old code silently derived `<toolkit>/runs` while workflows separately computed `aidt / "runs"`; they agreed only because `aidt == aidt_root`. Removing the default makes a split run impossible to express |
| Each entry point (the five workflow `run()` bodies, plus CLI `exec`/`runs`) resolves `TargetRepo → WorkspacePaths` **once** per invocation and threads one `runs_root = …state_root / "runs"` to `create_run`, `run_dir`/`RunLogger`, `run_stage`, `list_runs`/`find_run` and `_latest_*_run` | §3.10 + E1.3's per-repo `state_root`; re-resolving per site costs extra git calls and can diverge, splitting a run across two directories |
| `runner.py` and `cli.py` no longer resolve any root themselves; `cli._run_dir` was dropped in favour of `state_mod.run_dir(runs_root, run_id)` | `run_stage` and the CLI receive the threaded value (Requirement 4); the old `_run_dir(run_id)` body (`toolkit_root() / "runs" / run_id`) would have split the run |
| Every surviving identifier was renamed: `aidt_root → toolkit_root` and `runs_dir → runs_root` in `config.py`, `inventory.py`, `state.py`, `runner.py`, `doctor.py`, `cli.py` and all five workflows | The literal `rg` gate trips on parameter/local names, not just the two deleted functions |
| `doctor.py` switches to `toolkit_root()` but threads **no** state root | Its `_check_prompts`/`_check_agent_configs` are runs-independent toolkit-asset checks (Requirement 5): `aidt` still locates prompts/agent-configs; only the *runs* location moves |
| `prompt.py run()`'s optional test-injection parameter renames to `runs_root: Path | None = None` | The literal gate bans `runs_dir` under `aidw/`; when omitted it resolves the state root itself, so `repo`/`aidt` are untouched |
| The literal gate is implemented as a Python file-scan in `tests/test_paths.py` rather than shelling to `rg` | CI then needs no ripgrep; it still covers parameter/local names, not just the deleted functions |

**Where it fits in the roadmap:** Task E1.4 in Epic E1 ("Two-root core") of the AIDT extraction. It consumes E1.1 (`TargetRepo`), E1.2 (`ToolkitPaths`) and E1.3 (`WorkspacePaths.state_root`) and completes the consumer port that those tasks deliberately deferred. E1.5 (typed CLI plumbing / `AIDW_REPO`, replacing the `(repo, aidt)` tuple) builds on the resolve-once boundary this task establishes; E2.2 adds layout guards/warnings; E2.7 adds the run lock; E3.x wires the config-driven `paths.state_root`.

**Scope:** Porting-only — helper deletion, run-location move, identifier renames, and the matching test updates across `aidw/` and `tests/`, plus the E1.4 roadmap checkbox. It deliberately stops short of E1.5 typed CLI plumbing, E2.2 layout guards, E2.7 run locking, E3.x config-driven state roots, and historical `aidt/runs/` migration.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `aidw/paths.py` | Modified | Deleted `aidt_root()` and `runs_dir()`; updated the module docstring to drop the "transitional aliases until E1.4" note and state that runs live under the per-repo state root |
| `aidw/runner.py` | Modified | `run_stage` signature now `run_stage(spec, *, repo_root, toolkit_root, state, logger, agents=None, dry_run=False, retry_transient=None, show_progress=None, runs_root)`; deleted the `runs_root = runs_dir if runs_dir is not None else aidt_root / "runs"` fallback. `resolve_prompt(toolkit_root, value)` renamed in lockstep |
| `aidw/state.py` | Modified | Renamed the `runs_dir` parameter to `runs_root` in `run_dir`, `create_run`, `list_runs`, `find_run`, `latest_for_branch`; docstring updated to the state-root location |
| `aidw/config.py` | Modified | Renamed `aidt_root` → `toolkit_root` across `_load_system_prompt`, `load_agent`, `load_all` and their call sites |
| `aidw/inventory.py` | Modified | Renamed `aidt_root` → `toolkit_root` in `prompts_dir`, `list_files`, `check` |
| `aidw/doctor.py` | Modified | Import and call switched `aidt_root()` → `toolkit_root()`; no state-root threading (runs-independent asset checks) |
| `aidw/cli.py` | Modified | `exec`/`runs` resolve `TargetRepo → WorkspacePaths` once and thread `runs_root`; dropped `_run_dir` for `state_mod.run_dir(runs_root, run_id)`; `run_stage(..., toolkit_root=…, runs_root=…)`; the `rendered:` echo prints the state-root-relative path |
| `aidw/workflows/implement.py` | Modified | `runs_root` resolved once in `run()` and threaded to `create_run`/`run_dir`/`run_stage`/`_latest_implement_run`; `_latest_implement_run(runs_root, …)` |
| `aidw/workflows/review.py` | Modified | `runs_root` resolved once and threaded to `create_run`/`run_dir`/`run_stage` |
| `aidw/workflows/fix.py` | Modified | `runs_root` resolved once and threaded to `create_run`/`run_dir`/`run_stage`/`_latest_fix_run`; `_approval_round` gained a `runs_root` parameter so its internal `run_stage` call stays in the same directory |
| `aidw/workflows/approve.py` | Modified | `runs_root` resolved once and threaded to `create_run`/`run_dir`/`run_stage` |
| `aidw/workflows/prompt.py` | Modified | `runs_dir: Path | None` → `runs_root: Path | None`; resolves the state root when not injected, then threads it to `create_run`/`run_dir`/`run_stage` |
| `tests/test_paths.py` | Modified | Dropped the `runs_dir` import and `test_runs_dir_is_under_the_toolkit_root`; added `test_no_old_helper_names_survive_under_aidw` (Python literal-gate scan); docstring updated |
| `tests/test_runner.py` | Modified | Imports `toolkit_root`; every `run_stage(...)` call uses `toolkit_root=`/`runs_root=`; added `test_run_stage_writes_under_the_threaded_runs_root` (state.json + `prompts/` siblings under one `runs_root`) |
| `tests/test_cli.py` | Modified | Added `_init_repo`/`_runs_root` helpers and two tests: `runs list`/`show` resolve the state root; `exec --dry-run` keeps `state.json`, `run.log` and the rendered prompt in one state-root run dir with the toolkit `runs/` unused |
| `tests/test_implement_workflow.py` | Modified | `_Recorder` reads `kwargs["runs_root"]`; added `test_dry_run_writes_runs_under_the_state_root` (run lands under the state root, `repo/aidt/runs` stays absent); assertions derive the runs dir via `WorkspacePaths` |
| `tests/test_review_workflow.py` | Modified | `_FakeStages`/assertions repointed to the state-root runs dir via `WorkspacePaths` |
| `tests/test_fix_workflow.py` | Modified | `_FakeStages`/assertions repointed to the state-root runs dir via `WorkspacePaths` |
| `tests/test_approve_workflow.py` | Modified | `_FakeStages`/assertions repointed to the state-root runs dir via `WorkspacePaths` |
| `tests/test_prompt_workflow.py` | Modified | Every `prompt_workflow.run(..., runs_dir=…)` kwarg switched to `runs_root=` (≈15 call sites) |
| `tests/test_inventory.py` | Modified | `aidt_root` import/calls switched to `toolkit_root` |
| `tests/test_prompts.py` | Modified | `aidt_root` import/calls switched to `toolkit_root` |
| `tests/test_agents.py` | Modified | `aidt_root` import/calls switched to `toolkit_root` |
| `tests/test_config.py` | Modified | `aidt_root` import/calls switched to `toolkit_root` |
| `tests/conftest.py` | Modified | Docstring wording updated (the `toolkit_root()/runs` sweep is now a stale-artifact sweep only); sweep itself kept |
| `docs/tasks/00 - Extraction.md` | Modified | Marked roadmap task E1.4 done (`[ ]` → `[x]`, one line) |
| `docs/task-prompts/00-E1.4-prompt.md` | Created | Task prompt authored for E1.4 through the toolkit (planning-stage artifact; committed as `6c963b0`, then revised by `bf2958a`) |

The change set is the working tree relative to `main`, not only committed work: **all** implementation and test changes plus the roadmap checkbox are **uncommitted** (`git status` shows ` M` for the 12 `aidw/` files, 14 `tests/` files and the roadmap). Only `docs/task-prompts/00-E1.4-prompt.md` is committed (`6c963b0`, `bf2958a`).

---

## Changes Made

### 1. `aidw/paths.py`

- Deleted `aidt_root()` and `runs_dir()` (and the transitional-alias docstring note).
- Docstring now records that E1.1–E1.3 established `TargetRepo`/`ToolkitPaths`/`WorkspacePaths` and that run artifacts are written under the per-repo state root, never into the toolkit root or the target working tree.

### 2. `aidw/runner.py`

- `run_stage`'s `aidt_root` parameter renamed to `toolkit_root`; `runs_dir: Path | None = None` replaced by the required `runs_root: Path`; the `runs_root = runs_dir if runs_dir is not None else aidt_root / "runs"` fallback line removed.
- `resolve_prompt`'s first parameter renamed to `toolkit_root` (call sites are positional).
- `load_all(toolkit_root, repo_root)` and the `SCRIPTS_DIR_ENV_VAR` derivation now use `toolkit_root`.

### 3. Run-location move (five workflows + `cli.py`)

- `implement.py`, `review.py`, `fix.py`, `approve.py` and `prompt.py` each resolve `runs_root = WorkspacePaths.resolve(TargetRepo.resolve(repo)).state_root / "runs"` once in `run()` and thread that same value to `create_run`, `run_dir`/`RunLogger`, `run_stage`, `list_runs`/`find_run` and their `_latest_*_run` helpers. `fix._approval_round` gained a threaded `runs_root`.
- `cli.py` `exec` and `runs` resolve `TargetRepo → WorkspacePaths` once; `_run_dir` was removed in favour of `state_mod.run_dir(runs_root, run_id)`; `exec`'s echo now prints `rendered: runs/<run-id>/…` relative to the state root.

### 4. Identifier renames

- `aidt_root → toolkit_root` in `config.py`, `inventory.py`, `doctor.py`, `runner.py`, `cli.py` and all five workflows.
- `runs_dir → runs_root` in `state.py`, `runner.py`, `cli.py` and all five workflows.

### 5. Tests

- `tests/test_paths.py`: dropped the `runs_dir` import and its test; added the literal-gate scan.
- `tests/test_runner.py`: added the threaded-`runs_root` sibling proof; call-site keywords updated.
- `tests/test_cli.py`: added state-root `runs list`/`show` and `exec --dry-run` one-run proofs.
- `tests/test_implement_workflow.py`: added the end-to-end state-root dry-run proof; `_Recorder` and assertions repointed.
- `tests/test_{review,fix,approve}_workflow.py`: `_FakeStages`/assertions repointed to the state-root runs dir.
- `tests/test_prompt_workflow.py`: `runs_dir=` → `runs_root=` at every call site.
- `tests/test_{inventory,prompts,agents,config}.py`: `aidt_root` → `toolkit_root`.

---

## Verification Results

### Top-level verification

The toolkit repository is a Python/uv project: `.github/workflows/ci.yml` runs `uv sync --frozen`, `uv run --frozen pytest` and `uv run --frozen aidw doctor`. There is **no `package.json`, `pnpm-workspace.yaml` or `pnpm-lock.yaml`**, so the template's `pnpm` matrix does not apply. Both the `pnpm` commands and the repository's real `uv` gates were executed; the exact outcomes are recorded below.

| Step | Command | Result |
|------|---------|--------|
| Install | `pnpm install` | ❌ Exit 1 — `ERR_PNPM_NO_PKG_MANIFEST No package.json found in /Users/phil`. Not applicable: no pnpm project |
| Lint | `pnpm -r lint` | ⚠️ Exit 0 — `No projects found in "/Users/phil/software-projects/aidt"`. No linter/lint script configured |
| Build | `pnpm -r build` | ⚠️ Exit 0 — `No projects found …`. See `uv build` below for the real build gate |
| Test | `pnpm -r test` | ⚠️ Exit 0 — `No projects found …`. See `uv run --frozen pytest` below for the real test gate |
| Install (real) | `uv sync --frozen` | ✅ Exit 0 — `Checked 13 packages in 6ms` |
| Build (real) | `uv build --out-dir <tmpdir>` | ✅ Exit 0 — built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` into a temp dir; repo tree untouched |
| Test (real) | `uv run --frozen pytest` | ✅ Exit 0 — **407 passed in 83.50s** |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 3 warning(s)`; warnings are unauthenticated `gh`, the dirty working tree and missing `.mcp.json`, all expected |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `0 error(s), 0 warning(s)` |
| Literal gate | `rg "aidt_root|runs_dir" aidw/` | ✅ No output, **exit 1** (no matches, as required) |
| Whitespace | `git diff --check` | ✅ Clean (exit 0) |

### `uv run --frozen pytest` (full suite)

Full-suite total: **407 passed in 83.50s** (exit 0). No test failed, errored or was skipped.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 407 | ✅ Pass (`407 passed in 83.50s`) |
| Focused E1.4 gate (`test_paths`, `test_runner`, `test_cli`, `test_{implement,review,fix,approve}_workflow`, `test_prompt_workflow`) | 83 | ✅ Pass (`83 passed in 21.09s`) |

### Task-specific verification gates

The task prompt names no `srd:*`/`cdk`/integration gate; its Done-when is the literal `rg` gate, the pytest suite, `aidw doctor` and `aidw prompts check`.

| Gate | Status |
|------|--------|
| `pnpm srd:validate` | ❌ Exit 1 — `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND No package.json (or package.yaml, or package.json5) was found in "/Users/phil"`. Unrunnable: no pnpm manifest / `srd:*` scripts in this repo |
| `pnpm srd:check-references` | ❌ Exit 1 — same `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND` |
| `pnpm srd:matrix-check` | ❌ Exit 1 — same `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND` |
| `pnpm srd:report` | ❌ Exit 1 — same `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND` |
| `pnpm --filter infra cdk synth -c env=dev` | ⚠️ Exit 0 — `No projects found in "/Users/phil/software-projects/aidt"`. Not a real synth: no `infra/` project or `cdk.json` exists; structurally unrunnable |
| `rg "aidt_root\|runs_dir" aidw/` returns nothing (exit non-zero) | ✅ No output, exit 1 |
| Runs written under the state root, never `repo/aidt/runs` | ✅ `tests/test_implement_workflow.py::test_dry_run_writes_runs_under_the_state_root` and `tests/test_cli.py::test_exec_dry_run_writes_one_run_under_the_state_root` pass |
| `run_stage` writes `state.json` and rendered prompts under the same threaded `runs_root` | ✅ `tests/test_runner.py::test_run_stage_writes_under_the_threaded_runs_root` passes |
| CLI `runs list`/`show` resolve against the state root | ✅ `tests/test_cli.py::test_runs_list_and_show_resolve_the_state_root` passes (finds the state-root run; no toolkit-root run exists) |
| `exec --dry-run` keeps `state.json`, `run.log` and the rendered prompt in ONE state-root run dir; toolkit `runs/` empty | ✅ `tests/test_cli.py::test_exec_dry_run_writes_one_run_under_the_state_root` passes |
| `test_paths.py` no longer imports/tests `runs_dir`; regression/purity guards intact | ✅ `tests/test_paths.py` passes; `tests/test_workspace_paths.py` and `tests/test_target_repo.py` pass unmodified |
| `uv run aidw doctor` clean from the toolkit root (no dangling `aidt_root` import) | ✅ Exit 0 — 14 checks, 0 failed, 3 warnings |
| `uv run aidw prompts check` clean | ✅ Exit 0 — 0 error(s), 0 warning(s) |
| Diff is porting-only (no `AIDW_REPO`, no typed `(TargetRepo, ToolkitPaths)` threading, no layout guards) | ✅ `git status --short` shows only the 12 `aidw/` files, 14 `tests/` files and the roadmap checkbox; no new root type, no guard logic |

---

## Non-Goals (NOT implemented)

- ❌ E1.5 CLI plumbing — thread `TargetRepo`/`ToolkitPaths` through every workflow, replace the `(repo, aidt)` tuple, add `AIDW_REPO`, re-point `_run_dir` to typed resolution; E1.4 keeps `(repo, aidt)` and the untyped `runs_root` stopgap (task prompt, Explicit non-goals)
- ❌ E2.2 layout guards — warn when the state root falls inside a working tree, fail when the workspace root is a worktree; E1.4 writes state there without warning (task prompt, Explicit non-goals)
- ❌ E2.7 run lock into the state root (`locks/<branch>.lock` in §3.10) — later task (task prompt, Explicit non-goals)
- ❌ E3.x config-driven `paths.state_root` (D17) — E1.4 keeps the hardcoded three-tier formula (task prompt, Explicit non-goals)
- ❌ Migrating historical `aidt/runs/` — not migrated; gitignored and historical (EXTRACTION.md §3.10, task prompt)
- ❌ No commit, push or pull request — this recording stage owns only this document (`aidt/prompts/record-implementation-results.md`)
