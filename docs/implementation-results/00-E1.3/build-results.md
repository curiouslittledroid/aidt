# Build Results — 00-E1.3: Workspace and state root (D18)

**Branch:** `00-E1.3`
**Date:** 2026-10-26
**Spec:** `docs/migration/EXTRACTION.md` §2 (Locked decisions, row D18), §3.1 (Two roots — "Workspace root" / "State root"), §3.2 (Workspace and worktree model — "Verified git facts"), §3.10 (State, runs, locking), §10 (Decisions resolved while writing this document, row R1). Roadmap: `docs/tasks/00 - Extraction.md` Epic E1, task E1.3.

> **Template note:** `prompts/record-implementation-results.md` (and `aidt/prompts/record-implementation-results.md`) instructs this stage to use `docs/implementation-results/TEMPLATE.md`, and `docs/migration/EXTRACTION.md` §config names `build_results_template: docs/implementation-results/TEMPLATE.md`. **That file does not exist anywhere in this repository or its history** (`find`/`git log` both empty). This document therefore follows the structure established by the two existing results documents, `docs/implementation-results/00-E1.1/build-results.md` and `docs/implementation-results/00-E1.2/build-results.md`, which are the de-facto template in this repo. No placeholders remain.

## Summary

**Purpose:** Resolve the per-repository **workspace root** and **state root** as a single frozen `WorkspacePaths` type exposing exactly `workspace_root`, `state_root` and `repo_slug`. `workspace_root = dirname(<absolute git-common-dir>)`, derived from the passed-in `TargetRepo`; `state_root = <state base>/<repo_slug>`; `repo_slug` comes from the `origin` remote, else the workspace-root basename. Resolution helpers plus a new contract-test module only.

| Decision | Why it matters |
|----------|---------------|
| `WorkspacePaths` is a distinct frozen dataclass from `TargetRepo`/`ToolkitPaths`, constructed via `WorkspacePaths.resolve(repo, state_dir_override=None, home=None)` | §3.1 requires the toolkit root and target repo never to be interchangeable; a third distinct type keeps workspace/state roots out of both |
| `workspace_root = repo.common_dir.parent.resolve()` | §3.2's verified layout: the bare repo and all sibling worktrees share one `common_dir`; deriving from the already-resolved `TargetRepo` never re-runs git and is identical from every worktree. Never `git_dir.parent` (a linked worktree's `git_dir` is `<bare>/worktrees/<name>`) and never `root.parent` (only coincidentally right in the §3.2 layout) |
| `repo_slug` parsing handles both `https://host/<o>/<n>.git` and scp-like `git@host:<o>/<n>.git`, plus `ssh://…`, strips a trailing `.git`, and joins the **last two** path segments with `-` | §3.10/R1 "always present"; the SSH form uses `:` before the path, so parsing only `/` would break it; fewer than two segments or any git failure → basename fallback |
| `state_root = <base>/<repo_slug>`, slug appended in **all three** tiers (`state_dir_override`/`AIDW_STATE_DIR` → workspace `.aidw/state` → home `.aidw/state`) | §3.10 layout `<state root>/<repo-slug>/` and R1 "always present"; the Done-when's "differs between repos sharing a parent" only holds with the slug in the result |
| Fail-closed, never raises: the workspace tier is taken only when usable, else falls to `<home>/.aidw/state` | §3.10 single-checkout case lands state **inside** the working tree; an unusable workspace root must not raise — the fallback is pinned, the probe mechanism is not |
| The "usable" probe is a non-mutating `os.access` walk-up (`_is_usable_directory`), not a guarded `mkdir` | The prompt left the mechanism open; a read-only `resolve()` must not create `<workspace_root>/.aidw/state` and dirty `git status` in the single-checkout case |
| `state_dir_override` and `home` are injectable, defaulting to the real `AIDW_STATE_DIR` / `Path.home()` | Tests exercise every tier and the fallback without touching the real environment (Requirement 6) |
| `aidt_root()`, `runs_dir()` and every consumer are left behaviourally unchanged | E1.4 owns porting consumers and deleting the transitional aliases; E1.5 owns CLI plumbing; E2.2/E2.8 own layout guards and doctor checks |

**Where it fits in the roadmap:** Task E1.3 in Epic E1 ("Two-root core") of the AIDT extraction. It builds directly on E1.1 (`TargetRepo`, whose `common_dir` it consumes) and E1.2 (`ToolkitPaths`). E1.4 (port consumers, delete `aidt_root()`/`runs_dir()`, rewrite `test_paths.py`) and E1.5 (CLI plumbing / `AIDW_REPO`) build on this resolver; E2.2 adds layout warnings/failures and E2.8 adds doctor checks.

**Scope:** Additive changes to `aidw/paths.py` (module constant, four private helpers, the `WorkspacePaths` type), a new contract-test module `tests/test_workspace_paths.py`, and the E1.3 roadmap checkbox. It deliberately stops short of porting consumers, CLI plumbing, layout guards/warnings, doctor checks, config-driven state roots, worktree primitives and historical state migration.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `aidw/paths.py` | Modified | Added `STATE_DIR_ENV_VAR`, the private helpers `_origin_remote`, `_slug_from_remote`, `_repo_slug`, `_is_usable_directory`, `_state_base`, and the frozen `WorkspacePaths` dataclass with `resolve()`. Purely additive (`+178` lines, no deletions); `toolkit_root()`, `aidt_root()` and `runs_dir()` unchanged |
| `tests/test_workspace_paths.py` | Created | 38 contract tests: two worktrees of one bare repo, two repos sharing a parent, plain clone, slug vectors (HTTPS/scp-SSH/`ssh://`/subgroup/short/missing), state-root tiers (explicit override, env, workspace, injected home), unwritable/unusable workspace fallback, purity/shape/frozen-ness/type distinctness, and cwd-depth/unrelated-env invariance |
| `docs/tasks/00 - Extraction.md` | Modified | Marked roadmap task E1.3 done (`[ ]` → `[x]`, one line) |
| `docs/task-prompts/00-E1.3-prompt.md` | Created | Task prompt authored for E1.3 through the toolkit (planning-stage artifact; committed as `89b1bf9`, the branch's only commit) |

The change set is the working tree relative to `main`, not only committed work: `aidw/paths.py`, `tests/test_workspace_paths.py` and the roadmap checkbox are **uncommitted** (`git status` shows ` M aidw/paths.py`, `?? tests/test_workspace_paths.py`, ` M "docs/tasks/00 - Extraction.md"`); only the task prompt is committed.

---

## Changes Made

### 1. `aidw/paths.py`

- **`STATE_DIR_ENV_VAR = "AIDW_STATE_DIR"`** — the env override name from §3.10.
- **`_origin_remote(repo_root)`** — runs `git remote get-url origin` in `repo.root`; returns `None` on any `CalledProcessError`/`FileNotFoundError` or empty output (missing remote is a normal configuration, never raises).
- **`_slug_from_remote(remote)`** — strips a trailing `.git`; handles scp-like `git@host:owner/name` (the `:` becomes the path separator), URL forms via `urlparse().path`, and plain/local paths; joins the last two non-empty path segments with `-`; returns `None` for fewer than two segments.
- **`_repo_slug(repo_root, workspace_root)`** — `_slug_from_remote(_origin_remote(...))` if available, else `workspace_root.name` (literal `"repo"` only if the basename is empty at a filesystem root); always a non-empty `str`.
- **`_is_usable_directory(path)`** — walks up to the nearest existing ancestor and checks it is a directory the user can write to; never creates anything (deliberately an access check, not a guarded `mkdir`, so a read-only `resolve()` does not write inside a working tree).
- **`_state_base(workspace_root, *, state_dir_override, home)`** — returns `Path(state_dir_override).resolve()` when injected, else `AIDW_STATE_DIR`, else `<workspace_root>/.aidw/state` when usable, else `<home>/.aidw/state`. Every tier is absolute and resolved.
- **`WorkspacePaths`** — frozen dataclass with exactly `workspace_root: Path`, `state_root: Path`, `repo_slug: str`; `resolve()` derives `workspace_root = repo.common_dir.parent.resolve()`, computes the slug, resolves the base, and returns `cls(workspace_root=…, state_root=(base / repo_slug).resolve(), repo_slug=…)`.

### 2. `tests/test_workspace_paths.py`

- Builds real repositories with git: a bare clone plus two linked worktrees, two bare repos under one parent with distinct `origin` remotes, and a plain clone — so `git_dir != common_dir` and the worktree/single-checkout layouts are genuinely exercised.
- Proves the Done-when: one bare + two worktrees resolve to the same workspace/state root; two repos sharing a parent resolve to different state roots; plain clone has `workspace_root == repo.root` with state **inside** the tree; missing origin falls back to the basename.
- Covers every state tier (explicit override > env > workspace > home), the slug still being appended under the override, the unwritable (`chmod 0o500`, restored in `finally`) and non-directory-`.aidw` fallbacks to the injected home, purity (no `TargetRepo` mutation), exact three-field shape, frozen-ness, absolute/resolved paths, and type distinctness.

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
| Install (real) | `uv sync --frozen` | ✅ Exit 0 — `Checked 13 packages in 2ms` |
| Build (real) | `uv build --out-dir <tmpdir>` | ✅ Exit 0 — built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` into a temp dir; repo tree untouched |
| Test (real) | `uv run --frozen pytest` | ✅ Exit 0 — **390 passed in 69.28s** |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)`; warnings are the dirty working tree and missing `.mcp.json`, both expected |

### `uv run --frozen pytest` (full suite)

Full-suite total: **390 passed in 69.28s** (exit 0). No test failed, errored or was skipped.

| Test file | Tests | Result |
|-----------|-------|--------|
| `tests/test_workspace_paths.py` (new) | 38 | ✅ Pass (`38 passed in 21.64s`) |
| `tests/test_paths.py` + `tests/test_target_repo.py` (unmodified) | 27 | ✅ Pass (`27 passed in 10.09s`) |
| whole suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 390 | ✅ Pass |

### Task-specific verification gates

The task prompt names no `srd:*`/`cdk`/integration gate; its Done-when is the pytest suite plus the behavioural proofs below.

| Gate | Status |
|------|--------|
| `pnpm srd:validate` | ❌ Exit 1 — `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND No package.json … found in "/Users/phil"`. Unrunnable: no pnpm manifest / `srd:*` scripts in this repo |
| `pnpm srd:check-references` | ❌ Exit 1 — same `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND` |
| `pnpm srd:matrix-check` | ❌ Exit 1 — same `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND` |
| `pnpm srd:report` | ❌ Exit 1 — same `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND` |
| `pnpm --filter infra cdk synth -c env=dev` | ⚪ Unverified — no `infra/` directory or `cdk.json`, and `cdk` is not installed. Structurally unrunnable |
| Two worktrees of one bare repo share `workspace_root`/`state_root` | ✅ `test_two_worktrees_of_one_bare_share_workspace_and_state_root` passes |
| Two repos sharing a parent get different `state_root`s | ✅ `test_two_repos_sharing_a_parent_get_different_state_roots` passes (`org-a-alpha` vs `org-b-beta`) |
| `workspace_root = common_dir.parent`, not `git_dir.parent`/`root.parent` | ✅ `test_workspace_root_is_common_dir_parent_not_git_dir_or_root_parent` passes |
| State root stays out of the working tree in the bare/worktree layout | ✅ All worktree/plain-clone tests pass; the plain-clone case deliberately keeps state inside the tree (`test_single_checkout_places_state_inside_the_working_tree`) |
| `AIDW_STATE_DIR` override wins while still appending the slug | ✅ `test_environment_state_dir_wins_over_the_workspace_tier` and `test_explicit_state_dir_override_wins_over_environment` pass |
| Unwritable workspace root falls closed to injected home, without raising | ✅ `test_unwritable_workspace_root_falls_closed_to_injected_home` and `test_unusable_state_parent_falls_closed_to_injected_home` pass |
| Slug parsing vectors incl. scp-SSH and subgroup | ✅ `test_slug_parsing_vectors` (7 cases) and the non-empty/separator-free property table pass |
| Additive-only scope | ✅ `git status --short` shows only ` M aidw/paths.py`, `?? tests/test_workspace_paths.py`, ` M "docs/tasks/00 - Extraction.md"`; no `aidw/cli.py`, `aidw/doctor.py`, workflow or config change |
| `git diff --check` | ✅ Clean (exit 0) |

---

## Non-Goals (NOT implemented)

- ❌ E2.2 layout guards — §3.10's "warn when the state root falls inside a working tree" and "fail when the workspace root is itself a registered worktree"; E1.3 only resolves, never warns/fails (task prompt, Explicit non-goals)
- ❌ E1.4 (port consumers, delete `aidt_root()`/`runs_dir()`, rewrite `test_paths.py`); E1.5 (CLI plumbing / `AIDW_REPO`); E1.6 (`aidw config show`); E2.8 (doctor workspace/state-root checks) — separate tasks (task prompt, Explicit non-goals)
- ❌ E2.x worktree primitives (`git worktree list`/add/remove) — E1.3 creates or parses no worktrees (task prompt, Explicit non-goals)
- ❌ E3.x config-driven `paths.state_root` (D17) — E1.3 hardcodes the three-tier formula; config wiring comes later (task prompt, Explicit non-goals)
- ❌ Migrating historical `aidt/runs/` into the new layout (EXTRACTION.md §9 non-goal)
- ❌ No commit, push or pull request — this recording stage owns only this document (`aidt/prompts/record-implementation-results.md`)
