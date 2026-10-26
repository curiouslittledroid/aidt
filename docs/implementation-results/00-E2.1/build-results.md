# Build Results — 00-E2.1: Git worktree primitives

**Branch:** `00-E2.1`
**Date:** 2026-10-26
**Spec:** `docs/migration/EXTRACTION.md` §3.1 (Two roots — the "Workspace root" row: `dirname(<absolute git-common-dir>)`), §3.2 (Workspace and worktree model — the verified-git-facts table, the per-task `worktree add` command, the `bare`/`detached`/`branch` porcelain markers), §4.1 (Inventory — the `aidw/git.py` row: "Clean — no product coupling. Extend with worktree primitives"), §3.12 (New repo layout — test location `tests/test_git.py`). Roadmap: `docs/tasks/00 - Extraction.md` Epic E2 ("Worktree model", D20), task E2.1.

## Summary

**Purpose:** Add seven git worktree primitives to `aidw/git.py` so AIDT can resolve the workspace root and drive the bare-plus-sibling-worktree layout of §3.2 — the foundation every later E2 task builds on.

| Decision | Why it matters |
|----------|---------------|
| `common_dir()` runs `git rev-parse --path-format=absolute --git-common-dir` and `workspace_root()` is exactly `common_dir(repo).parent` | `--path-format=absolute` is the git ≥ 2.31 floor (§3.2): without it an older git prints a *relative* common dir that `dirname` would resolve against the caller's cwd. Deriving the root from `common_dir` only is deliberate — `git_dir.parent` is wrong in a linked worktree (`<bare>/worktrees/<name>`) and a `.git`-file target is a trap |
| `worktrees()` parses `git worktree list --porcelain` line-driven on prefixes (`worktree `, `branch `, `bare`, `detached`), never by positional index, and skips the `bare` block | Porcelain blocks are variable-length (`bare` has no `HEAD`/`branch`, `detached` has `HEAD`+`detached`, `locked`/`prunable` add lines). The `bare` entry is the common dir, not a worktree — emitting it would make `worktree_for_branch`/E2.6 match a branchless phantom |
| Detached-HEAD worktrees are represented as `branch=None, detached=True`; `branch` is the short name with `refs/heads/` stripped | Lets callers distinguish "detached" from "on branch `task`" without re-parsing porcelain themselves. `Worktree` is a frozen dataclass with the prompt-fixed fields `path` (resolved), `branch`, `detached` |
| Every primitive is fail-closed: a git failure returns `None`/`False`/`[]`, never raises; the only mutating functions are `add_worktree`/`remove_worktree` (they create/remove worktrees, never commits) | Matches the module's existing `rev_parse`/`changed_paths` style; a non-repo cwd cannot take down a caller. The module docstring's "only reads git state" claim was updated to name the worktree pair as the mutation exception |
| `add_worktree()` targets `<workspace_root>/<branch>` — a *sibling* of the control worktree — and runs `git -C <repo> worktree add -b <branch> <target> <base_branch>` (default `base_branch="main"`) | Nesting the target under `<repo>/<branch>` would place it inside an existing worktree and git refuses. The target is derived from `workspace_root`, never the cwd or `<repo>` |
| `remove_worktree()` passes `--force` through only when the caller asks; `is_linked_worktree()` is `(repo / ".git").is_file()` with no git spawn | The dirty/unmerged refusal stays git's own (E2.3 wraps it with safety checks); "never `rm -rf`, never `reset --hard`". A linked worktree's `.git` is a file, a plain clone's is a directory, and a missing `.git` is `False`, not an error |

**Where it fits in the roadmap:** Task E2.1 opens Epic E2 ("Worktree model", D20). It consumes E1's typed resolution (`TargetRepo.common_dir`, `WorkspacePaths`) and design §13's git-safety module, and extends `aidw/git.py` per its §4.1 inventory row. Downstream tasks depend on these primitives directly: E2.2 (target/layout guards), E2.3 (`aidw worktree add|list|remove` + the dirty/unmerged safety wrapper), E2.4 (branch-setup Python stage consuming `add_worktree`), E2.5/E2.6 (workflow worktree resolution via `worktrees()`/`worktree_for_branch()`), E2.7 (run-per-worktree locking), E2.8 (doctor worktree/git checks) and E2.9 (shared worktree fixture).

**Scope:** The seven primitives, the `Worktree` dataclass and the `_parse_worktrees` helper in `aidw/git.py`; the module-docstring update; a real bare+worktree test rig and 25 focused tests in `tests/test_git.py`; and the E2.1 roadmap checkbox. It deliberately stops short of E2.2 (no layout guards), E2.3 (no CLI and no dirty/unmerged safety wrapper — `remove_worktree` only passes `--force` through), E2.4 (no branch-setup stage), E2.9 (the bare+worktree fixture stays local to `tests/test_git.py`), and any change to `aidw/paths.py`/`WorkspacePaths`.

---

## Files Changed

The change set is the working tree relative to `main`. Three files are **uncommitted**; the task prompt is committed.

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E2.1-prompt.md` | Created (committed `939956b`) | Task prompt authored for E2.1 through the planning stage |
| `aidw/git.py` | Modified (uncommitted) | Added `Worktree` (frozen dataclass: `path`/`branch`/`detached`), `_parse_worktrees()`, `common_dir()`, `workspace_root()`, `worktrees()`, `worktree_for_branch()`, `add_worktree()`, `remove_worktree()`, `is_linked_worktree()`; updated the module docstring to note the worktree pair as the sole mutation exception |
| `tests/test_git.py` | Modified (uncommitted) | Added the bare+worktree test helpers (`_git_run`, `_init_committed_repo`, `_make_bare`, `_make_bare_branch_and_detached`, `_make_bare_with_control`) and 25 worktree-primitive tests (porcelain parsing incl. `locked`/`prunable`, cwd-depth metamorphic roots, sibling `add_worktree`, dirty/force `remove_worktree`, linked/plain/non-repo detection, fail-closed and read-only purity) |
| `docs/tasks/00 - Extraction.md` | Modified (uncommitted) | Marked roadmap task E2.1 done (`[ ]` → `[x]`) |

`git status --short` shows exactly `M aidw/git.py`, `M "docs/tasks/00 - Extraction.md"`, `M tests/test_git.py`. `git diff --name-status main` additionally lists the committed task prompt. Only `aidw/git.py` and `tests/test_git.py` are product/tests; there is no `aidw/paths.py` change.

---

## Changes Made

### 1. `aidw/git.py`

- **`Worktree`** — frozen dataclass: `path: Path` (resolved), `branch: str | None` (short name, `refs/heads/` stripped), `detached: bool`.
- **`_parse_worktrees(porcelain)`** — splits blank-line-separated blocks, requires a leading `worktree ` line, drops any block containing `bare`, and reads `detached` / `branch ` lines by prefix. A detached block yields `branch=None, detached=True`.
- **`common_dir(repo)`** — `git rev-parse --path-format=absolute --git-common-dir`; strips and `resolve()`s; `None` on failure/empty.
- **`workspace_root(repo)`** — `common_dir(repo).parent`, or `None`.
- **`worktrees(repo)`** — `git worktree list --porcelain` → `_parse_worktrees`; `[]` on failure.
- **`worktree_for_branch(repo, branch)`** — first `Worktree` with an exact short-name match, else `None`.
- **`add_worktree(repo, branch, *, base_branch="main")`** — computes `workspace_root(repo) / branch`, runs `git worktree add -b <branch> <target> <base_branch>`, returns the resolved target or `None`.
- **`remove_worktree(repo, path, *, force=False)`** — `git worktree remove [--force] <path>`; returns git's success.
- **`is_linked_worktree(repo)`** — `(repo / ".git").is_file()`; filesystem only.
- Module docstring: the "only reads git state" claim now names `add_worktree`/`remove_worktree` as the mutating exception (create/remove worktrees, never commits).

### 2. `tests/test_git.py`

- Real-repo rig: a committed seed → `git clone --bare` → a branch worktree and a `--detach`ed worktree, and a bare-plus-`main`-control variant.
- 25 tests covering the porcelain parser (bare excluded, `refs/heads/` stripped, detached `None`/`True`, `locked`/`prunable` tolerance), `common_dir`/`workspace_root` invariance to nesting depth and their non-`git_dir` derivation, `add_worktree` sibling creation + round-trip + `base_branch` + already-checked-out failure, `remove_worktree` clean/dirty/`force`, `is_linked_worktree` linked/plain/non-repo, fail-closed behaviour, and read-only purity.

---

## Verification Results

> **Overall gate: ✅ PASS.** The repository's real gates all pass: `uv run --frozen pytest` → **532 passed in 54.20s**, `uv build` builds both artifacts, and `doctor`/`agents validate --strict`/`prompts check` are clean. Every row below is a `aidw gate run` outcome recorded in this run against tree `4ebec567476b`; `git diff --check` is clean.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Exit 0 — `Checked 15 packages in 1ms` (gate `install`, tree `4ebec567476b`, stage `record-implementation-results`, 2026-10-26T07:18:00Z) |
| Build | `uv build --out-dir /tmp/aidt-e21-build.V7FNIq` | ✅ Exit 0 — built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` into the temp dir (gate `build`, tree `4ebec567476b`, 2026-10-26T07:18:10Z) |
| Test | `uv run --frozen pytest` | ✅ Exit 0 — **`532 passed in 54.20s`** (gate `suite`, tree `4ebec567476b`, 2026-10-26T07:20:40Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)` (gate `doctor`, tree `4ebec567476b`, 2026-10-26T07:20:59Z). Warnings are the dirty working tree and missing `.mcp.json`, both expected |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents`, tree `4ebec567476b`, 2026-10-26T07:21:01Z) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts`, tree `4ebec567476b`, 2026-10-26T07:21:03Z) |
| Whitespace | `git diff --check` | ✅ Exit 0 — no whitespace errors |

### `uv run --frozen pytest` (full suite)

Single invocation: **`532 passed in 54.20s`** (exit 0); no failures, errors or skips. The subset rows below come from that gate and its focused sibling run, not from a second full-suite run.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 532 | ✅ Pass (`532 passed in 54.20s`, gate `suite`) |
| `tests/test_git.py` | 25 | ✅ Pass (`25 passed in 15.20s`, gate `smoke`) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run --frozen pytest tests/test_git.py` | ✅ `25 passed in 15.20s` (gate `smoke`, tree `4ebec567476b`, 2026-10-26T07:21:23Z) |
| Porcelain parsing: `bare` excluded; branch short name; detached HEAD | ✅ `test_worktrees_parses_branch_and_detached_and_excludes_bare`; `test_worktrees_ignores_optional_porcelain_lines` proves `locked`/`prunable` blocks keep their facts |
| `common_dir`/`workspace_root` invariant to cwd depth; root ≠ `git_dir.parent` | ✅ `test_common_dir_and_workspace_root_are_invariant_to_cwd_depth` (depths 0,1,2,5); `test_workspace_root_is_common_dir_parent_not_git_dir` |
| `add_worktree` creates the sibling `<tmp>/feat`, round-trips, honours `base_branch`, fails closed if already checked out | ✅ `test_add_worktree_creates_a_sibling_and_round_trips`, `::test_add_worktree_honours_base_branch`, `::test_add_worktree_fails_closed_when_branch_already_checked_out` |
| `remove_worktree` clean removal disappears; dirty refuses without `force`, succeeds with `force=True` | ✅ `test_remove_worktree_clean_removes_and_disappears`, `::test_remove_worktree_refuses_dirty_and_force_removes` |
| `is_linked_worktree` true in linked worktree, false in plain clone and non-repo | ✅ `test_is_linked_worktree_true_in_a_linked_worktree`, `::test_is_linked_worktree_false_in_a_plain_clone`, `::test_is_linked_worktree_false_in_a_non_repo_dir` |
| Fail-closed from a non-repo cwd; read-only primitives do not mutate | ✅ `test_worktree_primitives_fail_closed_outside_a_repo`, `::test_common_dir_fails_closed_for_a_missing_path`, `::test_read_only_primitives_do_not_mutate_the_repo`, `::test_read_only_primitives_do_not_mutate_their_path_input`, `::test_worktrees_metamorphic_add_then_remove` |
| Diff touches only `aidw/git.py` and `tests/test_git.py` (no `aidw/paths.py`) | ✅ `git diff --name-status main` lists only `M aidw/git.py`, `M tests/test_git.py`, the roadmap checkbox and the committed prompt; `git diff --name-only main -- aidw/paths.py` is empty |

---

## Deviations observed during recording

- **Workflow-env leakage into `tests/test_verification.py`.** The first `suite` invocation, inheriting the recording session's `AIDW_STAGE=record-implementation-results` and `AIDW_RUN_ID=20261026T065507Z-00-E2.1-implement`, **failed**: `2 failed, 530 passed in 39.99s` (gate `suite`, tree `4ebec567476b`, 2026-10-26T07:19:04Z, recorded and visible in `aidw gate list`). Both failures are environmental, not in E2.1's change: `test_cli_gate_run_propagates_a_failing_exit_code` inherited the real `AIDW_RUN_ID`, so `aidw gate run` resolved an unknown run and exited `EXIT_USAGE` (2) instead of 7; `test_cli_gate_run_records_into_the_branch_run_without_an_env_identity` deleted only `AIDW_RUN_ID`, so the inherited `AIDW_STAGE` made the recorded stage `record-implementation-results` instead of `cli`. CI (`.github/workflows/ci.yml`) sets neither variable. Re-running with `env -u AIDW_STAGE -u AIDW_RUN_ID` — matching CI and the implementer's documented command — gives the passing `532 passed in 54.20s` recorded above. This is a test-isolation gap in the E4.8 gate feature, not a defect in `aidw/git.py`.
- **Generic template is pnpm/srd-shaped; this repo is uv-based.** There is no `package.json`, `pnpm-workspace.yaml`, `srd:*` script, or `infra` CDK project, so no `pnpm`/`srd:*`/`cdk` gate applies. The repo's own gates (`AGENTS.md`, `.github/workflows/ci.yml`) were run instead.
- **Build wrote to a temp dir.** `uv build --out-dir /tmp/aidt-e21-build.V7FNIq` avoids creating an untracked, non-gitignored `dist/` in the tree under verification.

---

## Non-Goals (NOT implemented)

- ❌ E2.2 Target/layout guards (warn state-in-tree, fail workspace-root-is-a-worktree) — separate task (task prompt, Explicit non-goals)
- ❌ E2.3 `aidw worktree add|list|remove` CLI and the dirty/unmerged `--force` safety wrapper — `remove_worktree` only passes `--force` through (task prompt, Explicit non-goals)
- ❌ E2.4 branch-setup Python stage consuming `add_worktree` with `repo.base_branch`/`repo.branch_pattern` — separate task (task prompt, Explicit non-goals)
- ❌ E2.9 shared worktree fixture — the E2.1 fixture stays local to `tests/test_git.py` (task prompt, Explicit non-goals)
- ❌ No change to `aidw/paths.py`/`WorkspacePaths` — it already derives `workspace_root` from `TargetRepo.common_dir`; E2.1 adds git-level primitives only (task prompt, Explicit non-goals)
- ❌ No commit, push or pull request — `aidt/prompts/pr.md` owns that; the implementation, tests and roadmap checkbox remain uncommitted
