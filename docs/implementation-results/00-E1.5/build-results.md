# Build Results — 00-E1.5: CLI plumbing

**Branch:** `00-E1.5`
**Date:** 2026-10-26
**Spec:** `docs/migration/EXTRACTION.md` §2 (Locked decisions, row D19), §3.1 (Two roots — the "two distinct types" rule), §3.3 (CLI surface changes — the `--repo`/`AIDW_REPO` row), §3.10 (State, runs, locking — the state-root layout). Roadmap: `docs/tasks/00 - Extraction.md` Epic E1, task E1.5.

> **Template note:** `prompts/record-implementation-results.md` (and `aidt/prompts/record-implementation-results.md`) instructs this stage to use `docs/implementation-results/TEMPLATE.md`, and `docs/migration/EXTRACTION.md` §config names `build_results_template: docs/implementation-results/TEMPLATE.md`. **That file does not exist anywhere in this repository or its history** (`find`/`git log` both empty), as already recorded in `docs/implementation-results/00-E1.3/build-results.md` and `00-E1.4/build-results.md`. This document therefore follows the structure established by the four existing results documents, `00-E1.1` through `00-E1.4`, which are the de-facto template in this repo. No placeholders remain.

## Summary

**Purpose:** Wire `AIDW_REPO` into target selection with the owner-confirmed precedence `--repo` > `AIDW_REPO` > cwd, resolve the three typed roots **once** in `cli._roots()`, and replace the `(repo: Path, aidt: Path)` workflow tuple with `repo: TargetRepo, aidt: ToolkitPaths, workspace: WorkspacePaths` across every workflow and the chain in `run.py`. Primitives below the workflow layer keep their `Path` parameters; only call sites unwrap `.root`/`.prompts_dir`.

| Decision | Why it matters |
|----------|---------------|
| `AIDW_REPO` is read from `os.environ`, `.strip()`ed, and treated as unset when empty/whitespace-only; a non-empty value becomes `explicit=Path(value)` | `TargetRepo.resolve(explicit=…)` is the fail-closed validation path; passing `Path("")` would silently resolve to cwd. `start=` was deliberately **not** used because it walks up and falls back to cwd |
| One `except RepoNotFoundError` wraps the `TargetRepo.resolve` call, echoing the message and raising `typer.Exit(EXIT_REFUSED)` (4) | `BareRepositoryError` subclasses `RepoNotFoundError`, so one catch site covers a bad `AIDW_REPO`, an existing-but-non-repo `--repo`, and a bare `--repo`, each with its own message; this is `EXIT_REFUSED`'s first use |
| `_roots()` returns `(TargetRepo, ToolkitPaths, WorkspacePaths)` and is the **sole** `TargetRepo`/`WorkspacePaths` resolution site | Carries E1.4's resolve-once-and-thread rule forward; `run.py` and the workflows receive typed objects and pass those same objects on, so no git calls are repeated or diverge |
| `prompt.py`'s optional `runs_root: Path | None` test-injection parameter is replaced by the required `workspace: WorkspacePaths` | A fallback would quietly reintroduce per-site resolution; tests inject an isolated state root via `WorkspacePaths.resolve(target, state_dir_override=…)` |
| `run.py`'s `task_to_pr`/`review_and_fix` take the three typed roots, pass the same objects to sub-workflows, and unwrap `repo.root` only for the dry-run `prompt_path` and `find_task_prompt(repo.root, …)` | The primitive keeps its `repo: Path` parameter, so passing the `TargetRepo` itself would `TypeError` |
| Primitives (`run_stage`, `resolve_prompt`, `load_all`, `create_run`, `run_dir`, `build_plan`, `PlanStage.spec`, `find_task_prompt`) and all `git`/`github`/`report` helpers keep `Path` parameters | Prompt-fixed threading boundary; only workflow/CLI call sites unwrap |
| `prompts` stays toolkit-only via `ToolkitPaths.resolve().root` and resolves no target | It must work with no repository present |
| A new module constant `AIDW_REPO_ENV_VAR = "AIDW_REPO"` lives in `aidw/cli.py`, not `aidw/paths.py` | Requirement 7 forbids touching `paths.py`, where the sibling `STATE_DIR_ENV_VAR` lives. This is a recorded deviation from the implementer |

**Where it fits in the roadmap:** Task E1.5 in Epic E1 ("Two-root core") of the AIDT extraction. It consumes E1.1 (`TargetRepo.resolve(explicit=…)`), E1.2 (`ToolkitPaths`) and E1.3/E1.4 (`WorkspacePaths`, resolve-once run location). E1.6 (`aidw config show`) is the next task; E2.2 adds layout guards, E2.7 the run lock, E2.8 doctor checks, and E3.x config-driven state roots.

**Scope:** Plumbing only — target selection (`AIDW_REPO` + fail-closed `explicit=` validation), the `_roots()` 3-tuple, typed workflow signatures, and call-site `.root`/`.prompts_dir` unwraps, plus the matching test updates and the E1.5 roadmap checkbox. It deliberately stops short of E1.6, E2.2, E2.7, E2.8, E3.x, and any new root type or bundling object.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `aidw/cli.py` | Modified | Added `AIDW_REPO_ENV_VAR`; `_roots()` resolves once and returns the 3-tuple, applying `--repo` > `AIDW_REPO` > cwd with one `except RepoNotFoundError` → `typer.Exit(EXIT_REFUSED)`; all ten call sites unpack three roots; `exec`/`runs` use `workspace.state_root / "runs"`; `tasks`/`agents`/`exec` unwrap `.root`; `prompts` uses `ToolkitPaths.resolve().root`; `--repo` help and `_main` docstring mention `AIDW_REPO` |
| `aidw/workflows/prompt.py` | Modified | `run()` signature is `repo: TargetRepo, aidt: ToolkitPaths, workspace: WorkspacePaths`; `runs_root = workspace.state_root / "runs"`; optional `runs_root` injection removed; call sites unwrap `.root`/`.prompts_dir` |
| `aidw/workflows/implement.py` | Modified | Same typed signature and `runs_root` derivation; `_gate_summary`/`_record_pr` keep `Path` params, call sites unwrap |
| `aidw/workflows/review.py` | Modified | Same typed signature and `runs_root` derivation; call sites unwrap `.root` |
| `aidw/workflows/fix.py` | Modified | Same typed signature and `runs_root` derivation; `_approval_round` receives the threaded value |
| `aidw/workflows/approve.py` | Modified | Same typed signature and `runs_root` derivation |
| `aidw/workflows/run.py` | Modified | `task_to_pr`/`review_and_fix` take `repo: TargetRepo, aidt: ToolkitPaths, workspace: WorkspacePaths`, pass the same objects to sub-workflows, unwrap `repo.root` for `prompt_path`/`find_task_prompt`; zero `resolve` matches |
| `tests/test_cli.py` | Modified | Added 15 tests: `AIDW_REPO` selection, `--repo` precedence, bad/bare `AIDW_REPO` refusal (exit 4, no cwd effect), non-repo/bare `--repo` refusal, whitespace-only `AIDW_REPO` unset, typed `_roots()` shape, resolve-exactly-once, and the two-roots proofs for prompt/implement/review/fix/approve dry-runs plus exec |
| `tests/test_prompt_workflow.py` | Modified | Every `run(...)` call site passes typed `repo`/`aidt`/`workspace`; state isolated via `state_dir_override`; runs-root assertions derive from `workspace.state_root` |
| `tests/test_implement_workflow.py` | Modified | Same typed call sites and state-root assertion updates |
| `tests/test_review_workflow.py` | Modified | Added `_roots()` helper injecting an external state root; all `run(...)` call sites use it. `test_dry_run_plans_both_stages` now exercises a state root outside the target and **fails** (see Verification) |
| `tests/test_fix_workflow.py` | Modified | Same typed call sites and state-root assertion updates |
| `tests/test_approve_workflow.py` | Modified | Same typed call sites and state-root assertion updates |
| `tests/test_run_workflow.py` | Modified | Added `_init_repo`/`_roots` helpers and object-identity assertions proving the same `repo`/`aidt`/`workspace` reach chained sub-workflows; state isolated via `state_dir_override` |
| `docs/tasks/00 - Extraction.md` | Modified | Marked roadmap task E1.5 done (`[ ]` → `[x]`, one line) |
| `docs/task-prompts/00-E1.5-prompt.md` | Created | Task prompt authored for E1.5 through the toolkit (planning-stage artifact; committed as `d9ff572`, then revised by `682b115`) |

The change set is the working tree relative to `main`, not only committed work: **all** implementation and test changes plus the roadmap checkbox are **uncommitted** (`git status --short` shows ` M` for the 7 `aidw/` files, 8 `tests/` files and the roadmap). Only `docs/task-prompts/00-E1.5-prompt.md` is committed (`d9ff572`, `682b115`).

---

## Changes Made

### 1. `aidw/cli.py`

- **`AIDW_REPO_ENV_VAR = "AIDW_REPO"`** module constant.
- **`_roots() -> tuple[TargetRepo, ToolkitPaths, WorkspacePaths]`** — reads `--repo` from `_state`; when absent, reads `AIDW_REPO` from `os.environ`, `.strip()`s it, treats empty/whitespace as unset, and wraps a non-empty value in `Path(...)`; calls `TargetRepo.resolve(explicit=…)`; on `RepoNotFoundError` (including the `BareRepositoryError` subclass) echoes the message to stderr and raises `typer.Exit(EXIT_REFUSED)`; returns the target plus `ToolkitPaths.resolve()` and `WorkspacePaths.resolve(target)`. No longer calls `repo_root()`/`toolkit_root()`.
- **Ten call sites** unpack `repo, aidt, workspace = _roots()`; the six workflow bodies forward `workspace=…`; `tasks` uses `repo.root / "docs" / "tasks"`; `agents` uses `load_all(aidt.root, repo.root)`; `exec`/`runs` use `workspace.state_root / "runs"`, `repo.root`, `aidt.root`, `aidt.root` for `resolve_prompt`, and `repo_root=repo.root` for `stage_lines`; `prompts` uses `ToolkitPaths.resolve().root`.
- `--repo` help and the `_main` docstring document the `--repo > $AIDW_REPO > cwd` precedence.

### 2. Workflow layer (`prompt`, `implement`, `review`, `fix`, `approve`, `run`)

- Every `run()` is now `repo: TargetRepo, aidt: ToolkitPaths, workspace: WorkspacePaths`, with `runs_root = workspace.state_root / "runs"` computed once and threaded to `create_run`/`run_dir`/`run_stage`/`list_runs`/`find_run` and the `_latest_*` helpers.
- Primitive calls pass `.root`/`.prompts_dir`; the private `Path`-typed helpers (`_resolve_prompt_path`, `_commit_reviewed_prompt`, `_gate_summary`, `_record_pr`, `_approval_round`) keep their parameters and are only unwrapped at their `run()` call sites.
- `run.py`'s `task_to_pr`/`review_and_fix` pass the identical typed objects to sub-workflows (asserted by object identity in `tests/test_run_workflow.py`) and unwrap `repo.root` only for the dry-run `prompt_path` and `find_task_prompt(repo.root, …)`.

### 3. Tests

- `tests/test_cli.py`: 15 new tests covering target selection, precedence, refusal contracts, whitespace handling, `_roots()` shape and exact-once resolution, and the two-roots proofs (prompt/implement/review/fix/approve dry-runs and exec).
- `tests/test_{prompt,implement,review,fix,approve,run}_workflow.py`: all direct `run(...)` call sites switched to typed roots with an isolated state root via `WorkspacePaths.resolve(target, state_dir_override=…)`; runs-root assertions derive from `workspace.state_root`; `test_run_workflow.py` adds object-identity forwarding assertions.

---

## Verification Results

> **Overall gate: ❌ FAIL.** The full test suite is not green: `uv run --frozen pytest` exits 1 with **1 failed, 421 passed**. The failure is a real implementation defect identified by the `/test` stage and reproduced independently by this recorder in `aidw/workflows/review.py:167` (see below). Per the recording prompt, this document records the failure and does **not** fix it; a separate implementation follow-up owns the fix.

### Top-level verification

The toolkit repository is a Python/uv project: `.github/workflows/ci.yml` runs `uv sync --frozen`, `uv run --frozen pytest` and `uv run --frozen aidw doctor`. There is **no `package.json`, `pnpm-workspace.yaml` or `pnpm-lock.yaml`**, so the template's `pnpm` matrix does not apply. Both the `pnpm` commands and the repository's real `uv` gates were executed; the exact outcomes are recorded below.

| Step | Command | Result |
|------|---------|--------|
| Install | `pnpm install` | ❌ Exit 1 — `ERR_PNPM_NO_PKG_MANIFEST No package.json found in /Users/phil`. Not applicable: no pnpm project |
| Lint | `pnpm -r lint` | ⚠️ Exit 0 — `No projects found in "/Users/phil/software-projects/aidt"`. No linter/lint script configured |
| Build | `pnpm -r build` | ⚠️ Exit 0 — `No projects found …`. See `uv build` below for the real build gate |
| Test | `pnpm -r test` | ⚠️ Exit 0 — `No projects found …`. See `uv run --frozen pytest` below for the real test gate |
| Install (real) | `uv sync --frozen` | ✅ Exit 0 — `Checked 13 packages in 11ms` |
| Build (real) | `uv build --out-dir /tmp/aidt-build-e15` | ✅ Exit 0 — built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` into `/tmp/aidt-build-e15`; repo tree untouched |
| Test (real) | `uv run --frozen pytest` | ❌ **Exit 1 — `1 failed, 421 passed in 88.94s`** |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)`; warnings are the dirty working tree and missing `.mcp.json`, both expected |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `0 error(s), 0 warning(s)` |
| Whitespace | `git diff --check` | ✅ Clean (exit 0) |

### `uv run --frozen pytest` (full suite)

Full-suite total: **1 failed, 421 passed in 88.94s** (exit 1). No test errored or was skipped.

Failure:

```
FAILED tests/test_review_workflow.py::test_dry_run_plans_both_stages
ValueError: '<state root>/test_dry_run_plans_both_stages0/runs/20261026T015050Z-pr-7-review/artifacts/review-manifest.json'
is not in the subpath of '<tmp_path target repo>'
```

Raised at `aidw/workflows/review.py:167`:

```python
print(f"manifest: {manifest_path.relative_to(repo.root)}")
```

`manifest_path` is under `workspace.state_root / "runs"`, which the E1.5 threading deliberately allows to live **outside** `repo.root`. `Path.relative_to` therefore raises `ValueError` in the review dry-run path. The `/test` stage independently recorded this as a **Fail** (Requirement 6 and the "`uv run pytest` is green" criterion) and reported that no implementation code was changed during testing. The implementer's own final response claimed `421 passed`; that run predates the strengthened review fixture, so the recorder's independent run supersedes it.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 422 | ❌ 1 failed, 421 passed |
| Focused CLI + chain (`tests/test_cli.py tests/test_run_workflow.py`) | 27 | ✅ Pass (`27 passed`) |
| Regression modules (`test_runner`, `test_paths`, `test_target_repo`, `test_toolkit_paths`, `test_workspace_paths` — unmodified) | 102 | ✅ Pass (`102 passed`) |
| Review workflow (`tests/test_review_workflow.py`) | 7 | ❌ 1 failed, 6 passed (`F......`) |

### Task-specific verification gates

The task prompt names no `srd:*`/`cdk`/integration gate; its Done-when is the pytest suite, the two-roots workflow proofs, the structural `resolve`-site check, `aidw doctor` and `aidw prompts check`.

| Gate | Status |
|------|--------|
| `pnpm srd:validate` | ❌ Exit 1 — `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND No package.json … found in "/Users/phil"`. Unrunnable: no pnpm manifest / `srd:*` scripts in this repo |
| `pnpm srd:check-references` | ❌ Exit 1 — same `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND` |
| `pnpm srd:matrix-check` | ❌ Exit 1 — same `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND` |
| `pnpm srd:report` | ❌ Exit 1 — same `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND` |
| `pnpm --filter infra cdk synth -c env=dev` | ⚠️ Exit 0 — `No projects found in "/Users/phil/software-projects/aidt"`. Not a real synth: no `infra/` project or `cdk.json` exists; structurally unrunnable |
| `rg "WorkspacePaths\.resolve\|TargetRepo\.resolve" aidw/workflows aidw/cli.py` matches only `_roots()` | ✅ Matches only `aidw/cli.py:79` (`TargetRepo.resolve`) and `aidw/cli.py:86` (`WorkspacePaths.resolve`); zero matches under `aidw/workflows/` (incl. `run.py`) |
| `rg "repo_root\(\)\|toolkit_root\(\)" aidw/cli.py` returns nothing | ✅ No matches (exit 1) |
| E1.4 literal gate `rg "aidt_root\|runs_dir" aidw/` returns nothing | ✅ No matches (exit 1) |
| `AIDW_REPO` selects the target; `--repo` beats `AIDW_REPO` | ✅ `tests/test_cli.py::test_aidw_repo_selects_the_target`, `::test_repo_flag_beats_aidw_repo` pass |
| Bad/bare `AIDW_REPO` refuses with `EXIT_REFUSED` (4), stderr names the path, no cwd effect | ✅ `tests/test_cli.py::test_bad_aidw_repo_refuses_without_touching_cwd`, `::test_bare_aidw_repo_refuses_with_bare_message` pass |
| Non-repo/bare `--repo` refuses via the same catch site | ✅ `tests/test_cli.py::test_non_repo_flag_refuses`, `::test_bare_repo_flag_refuses` pass |
| Whitespace-only `AIDW_REPO` treated as unset | ✅ `tests/test_cli.py::test_whitespace_only_aidw_repo_is_unset` passes |
| `_roots()` resolves exactly once and returns the typed 3-tuple | ✅ `tests/test_cli.py::test_roots_resolves_to_typed_roots`, `::test_roots_resolves_target_and_workspace_once` pass |
| Every workflow operates on the target while prompts resolve from the toolkit root, roots differing | ✅ `tests/test_cli.py::{test_prompt,test_implement,test_review,test_fix,test_approve}_dry_run_reads_target_and_uses_toolkit_prompts` and `::test_exec_resolves_prompts_from_toolkit_and_state_from_target` pass |
| Same typed objects reach chained sub-workflows | ✅ `tests/test_run_workflow.py::{test_task_to_pr_hands_resolved_prompt_to_implement,test_review_and_fix_stops_when_review_fails,test_review_and_fix_runs_fix}` pass (object identity) |
| Review workflow supports a state root outside the target repository | ❌ `tests/test_review_workflow.py::test_dry_run_plans_both_stages` fails with the `ValueError` above |
| `uv run pytest` is green | ❌ Exit 1 — 1 failed, 421 passed |
| `uv run aidw doctor` clean | ✅ Exit 0 — 14 checks, 0 failed, 2 warnings |
| `uv run aidw prompts check` clean | ✅ Exit 0 — 0 error(s), 0 warning(s) |
| Diff is plumbing-only (no run-location move, no `state.json`/CLI-surface change) | ✅ `git status --short` shows only the 7 `aidw/` files, 8 `tests/` files and the roadmap checkbox; no `aidw/paths.py`/`aidw/runner.py` change, no run-location move |

### Deviations observed during recording

- **`AIDW_REPO_ENV_VAR` lives in `aidw/cli.py`** (not `aidw/paths.py`, where `STATE_DIR_ENV_VAR` lives) because Requirement 7 forbids touching `paths.py`. Recorded by the implementer.
- **A bare repo with no override now yields a clean exit-4 bare-specific refusal** instead of an uncaught `RepoNotFoundError`, and **an existing-but-non-repo or bare `--repo` now refuses with exit 4** where it was previously accepted. Both are direct consequences of Requirement 1's single `except RepoNotFoundError` catch site.

---

## Non-Goals (NOT implemented)

- ❌ E1.6 `aidw config show` — the next task in Epic E1; kept out (task prompt, Explicit non-goals)
- ❌ E2.2 layout guards (warn when the state root falls inside a working tree / fail when the workspace root is a worktree), E2.7 run lock into the state root, E2.8 doctor workspace/state-root/git checks — separate tasks; `doctor.py` keeps using `repo_root()`/`toolkit_root()` (task prompt, Explicit non-goals)
- ❌ E3.x config-driven `paths.state_root` / `repo.base_branch` from YAML (D17/D3) — `TargetRepo.base_branch` stays `"main"` and the hardcoded three-tier state formula stays (task prompt, Explicit non-goals)
- ❌ No new root type (no `Roots` dataclass, no bundling object) — a plain 3-tuple is the threading shape (task prompt, Explicit non-goals)
- ❌ No fix for the `aidw/workflows/review.py:167` defect — this recording stage owns only this document and does not change implementation code, tests, or traceability artifacts
- ❌ No commit, push or pull request — `aidt/prompts/pr.md` owns that
