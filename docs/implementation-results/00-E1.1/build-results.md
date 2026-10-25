# Build Results — 00-E1.1: TargetRepo resolution (D19)

**Branch:** `00-E1.1`
**Date:** 2026-10-26
**Spec:** `docs/migration/EXTRACTION.md` §2 (Locked decisions, row D19), §3.1 (Two roots), §3.2 (Workspace and worktree model), §3.4 (Target-repo config schema); §5.4 (verification gate). Roadmap: `docs/tasks/00 - Extraction.md` Epic E1.

## Summary

**Purpose:** Implement target-repository resolution — cwd walk-up plus an explicit override — as a single `TargetRepo` type exposing exactly `root`, `git_dir`, `common_dir` and `base_branch`.

| Decision | Why it matters |
|----------|---------------|
| `TargetRepo` is a distinct frozen dataclass, constructed only via `TargetRepo.resolve(start=None, explicit=None)` | §3.1 requires the target repo to be a type distinct from the toolkit root, never a bare `root: Path` alias; one factory keeps the fail-closed logic in one place |
| The explicit override is validated (`.resolve()`, then `is_dir()`) **before any walk-up** | A typo'd or non-repo `--repo` must raise `RepoNotFoundError`, not silently resolve to the enclosing/cwd repo; a file or missing path must never walk up |
| The bare-repo refusal is `BareRepositoryError(RepoNotFoundError)` | `aidw/doctor.py:266` catches only `RepoNotFoundError`; a sibling type would crash `aidw doctor` rather than report FAIL |
| `git_dir` from `rev-parse --absolute-git-dir`; `common_dir` from `rev-parse --path-format=absolute --git-common-dir` | Plain `--git-dir` prints a relative `.git`; §3.2 pins `common_dir`. In a linked worktree the two differ |
| `base_branch` is a defaulted field (`"main"`), not a config read | §3.4 default; E3.1 later supplies it from YAML and may change only its source, not the field |
| `repo_root()` left byte-for-byte unchanged | Existing call sites (`aidw/cli.py:58`, `aidw/doctor.py:266`) keep working; consumer porting is E1.4/E1.5 |

**Where it fits in the roadmap:** This is task E1.1 in Epic E1 ("Two-root core") of the AIDT extraction. It depends on the E0 skeleton (the repo is runnable, toolkit root resolved in E0.4). E1.2 (`ToolkitPaths`), E1.3 (workspace/state root), E1.4 (port consumers, delete `aidt_root()`/`runs_dir()`) and E1.5 (CLI plumbing, `--repo`/`AIDW_REPO`) all build on this resolver.

**Scope:** Additive changes to `aidw/paths.py` (new helpers plus the `TargetRepo` type) and a new contract-test module `tests/test_target_repo.py`, plus the roadmap checkbox. It deliberately stops short of reading `AIDW_REPO`, touching the CLI, config loading, and any worktree creation.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `tests/test_target_repo.py` | Created | 21 contract tests: bare+linked-worktree distinction, subdirectory walk-up, cwd default, override precedence and fail-closed override errors, bare refusal, plain-clone equivalence, four-field shape |
| `aidw/paths.py` | Modified | Added `BareRepositoryError`, `_git_output`, `_is_bare_repository`, `_resolve_worktree_root`, and the frozen `TargetRepo` dataclass with `resolve()`; `repo_root()` unchanged |
| `docs/tasks/00 - Extraction.md` | Modified | Marked roadmap task E1.1 done (`[ ]` → `[x]`) |
| `docs/task-prompts/00-E1.1-prompt.md` | Created | Task prompt authored for E1.1 through the toolkit (planning-stage artifact, committed in the branch's first three commits) |

---

## Changes Made

### 1. `aidw/paths.py`

- **`BareRepositoryError(RepoNotFoundError)`** — the distinct bare-dir refusal required by Requirement 5; subclassing keeps existing `except RepoNotFoundError` handlers working.
- **`_git_output(directory, *args)`** — one helper that runs `git` in a directory and returns stripped stdout, raising `CalledProcessError`/`FileNotFoundError`.
- **`_is_bare_repository(directory)`** — runs `git rev-parse --is-bare-repository`; used only when `--show-toplevel` fails.
- **`_resolve_worktree_root(origin)`** — mirrors `repo_root()`'s `--show-toplevel` call and `.git` walk-up fallback, but checks bareness first so a bare target raises `BareRepositoryError` instead of the generic message. Returns an absolute resolved path.
- **`TargetRepo`** — frozen dataclass with exactly `root: Path`, `git_dir: Path`, `common_dir: Path`, `base_branch: str = "main"`, and the classmethod `resolve(start=None, explicit=None)`. Override mode validates the path before walking up; default mode walks up from `start` (or cwd). `git_dir`/`common_dir` come from the two `rev-parse` flags, `.resolve()`d.
- **`repo_root()`** — public behaviour, signature, `.resolve()`d result and `RepoNotFoundError` message all unchanged.

### 2. `tests/test_target_repo.py`

- Builds real repositories with git: a seed repo, a `--bare` clone, and a `git worktree add` linked worktree, so `git_dir != common_dir` is genuinely exercised (not simulated with `git init`).
- Covers default resolution (worktree, subdirectory, cwd, depth-invariance), explicit override (wins over cwd, subdirectory resolves to tree root, worktree git dirs), and every fail-closed path (non-repo dir, file, nonexistent path each raise `RepoNotFoundError` naming the override and never fall back to cwd; bare override raises the bare refusal).
- Covers `repo_root()` equivalence in a plain clone, the four-field shape, absolute/resolved purity, input non-mutation, and frozen-ness.

---

## Verification Results

### Top-level verification

The toolkit repository is a Python/uv project: `.github/workflows/ci.yml` runs `uv sync --frozen`, `uv run --frozen pytest` and `uv run --frozen aidw doctor`. The template's `pnpm` commands do not apply — there is no `package.json`, `pnpm-workspace.yaml` or `pnpm-lock.yaml` in this repository. Both sets of rows are recorded below.

| Step | Result |
|------|--------|
| `uv sync --frozen` (install gate) | ✅ `Checked 13 packages in 15ms` (exit 0) |
| `uv build --out-dir <tmpdir>` (build gate) | ✅ Built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` (exit 0); output written to a temp dir, repo tree untouched |
| `uv run --frozen pytest` (test gate) | ✅ `318 passed in 34.58s` (exit 0) |
| `uv run --frozen aidw doctor` | ✅ `13 checks: 0 failed, 2 warning(s)` (exit 0) — warnings are the dirty working tree and a missing `.mcp.json`, both expected/pre-existing |
| `pnpm install` | N/A — no pnpm project in this repository |
| `pnpm -r lint` | N/A — no linter or lint script is configured in this repository |
| `pnpm -r build` | N/A — see `uv build` above |
| `pnpm -r test` | N/A — see `uv run --frozen pytest` above |

### `uv run --frozen pytest` (full suite)

Full-suite total: **318 passed in 34.58s**. Files named in the task prompt's done-when:

| Test file | Tests | Result |
|-----------|-------|--------|
| `tests/test_target_repo.py` | 21 | ✅ Pass |
| `tests/test_paths.py` | 6 | ✅ Pass |
| `tests/test_doctor.py` | 10 | ✅ Pass |
| `tests/test_cli.py` | 4 | ✅ Pass |
| `tests/test_config.py` | 14 | ✅ Pass |
| whole suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 318 | ✅ Pass |

No test file failed, errored or was skipped.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `rg -n "repo_root\(\)" aidw/` | ✅ Exactly the two pre-task call sites, text unchanged: `aidw/cli.py:58:    repo = Path(override) if override else repo_root()` and `aidw/doctor.py:266:        root = repo_root()` |
| `rg -n "def repo_root" aidw/paths.py` | ✅ Single definition `aidw/paths.py:37:def repo_root(start: Path \| None = None) -> Path:` — text unchanged (line shifted 27 → 37 by insertions above it) |
| `uv run --frozen pytest tests/test_target_repo.py` | ✅ 21 passed |
| Bare-dir distinct subclass (`test_bare_dir_raises_a_distinct_subclass`) | ✅ Asserts `BareRepositoryError` is a `RepoNotFoundError` subclass, not the same class, and that the message names "bare repository" and "worktree" without the generic text |
| Plain-clone equivalence (`test_plain_clone_matches_repo_root_and_uses_dot_git`) | ✅ `root == repo_root()` and `git_dir == common_dir == <root>/.git` |
| `git diff --check` | ✅ Clean |

---

## Non-Goals (NOT implemented)

- ❌ E1.2 `ToolkitPaths`; E1.3 workspace/state root; E1.4 port consumers & delete `aidt_root()`/`runs_dir()`; E1.5 CLI plumbing (reading `AIDW_REPO`, threading `TargetRepo` through workflows) — separate tasks (task prompt, Explicit non-goals)
- ❌ Config loading/validation (E3.1): `base_branch` is a defaulted field, not a YAML read (task prompt, Explicit non-goals)
- ❌ Worktree primitives/creation (E2.x): this task only resolves an existing target; it never creates worktrees or branches (task prompt, Explicit non-goals)
- ❌ Any environment-variable read (`AIDW_REPO`) or `--repo` CLI wiring — E1.5 owns the `--repo` > `AIDW_REPO` > cwd precedence (task prompt, Resolved decisions)
- ❌ No commit, push or pull request — this recording stage owns only this document (`prompts/record-implementation-results.md`)
