# Build Results — 00-E2.2: Target/layout guards

**Branch:** `00-E2.2`
**Date:** 2026-10-26
**Spec:** `docs/migration/EXTRACTION.md` §3.1 (Two roots — state root = `dirname(<absolute git-common-dir>)`; nothing generated is written into a target repo), §3.2 (Workspace and worktree model — rejected layouts, the clone-of-a-worktree detection rule, the one-time bootstrap commands), §3.10 (State, runs, locking — the single-checkout warning and the registered-worktree failure), §3.12 (New repo layout — test location `tests/`). Roadmap: `docs/tasks/00 - Extraction.md` Epic E2 ("Worktree model", D20), task E2.2.

## Summary

**Purpose:** Add target/layout guards so AIDW refuses the bare directory as a target, fails fast on the §3.2 clone-of-a-worktree trap from both positions it can be inhabited, and warns when the state root falls inside the single-checkout working tree.

| Decision | Why it matters |
|----------|---------------|
| `aidw/layout.py:check_layout(target, workspace) -> list[str]` returns warnings and raises `LayoutError` for hard failures, using the read-only `git.worktrees()` primitive | Keeps the guards pure and fail-closed without introducing a second git implementation or any mutating git call. |
| The clone-of-a-worktree failure is gated on `workspace.workspace_root` being in the worktree list **and** the list having more than one entry | The literal §3.2 rule also matches the legitimate single-checkout plain clone, whose sole entry is itself; the extra-entry gate preserves that §3.10-blessed case while firing from both the clone and the linked-child positions. It deliberately does not gate on `workspace_root == target.root`, which would silently pass the linked-child position. |
| The state-inside-tree warning compares `workspace.state_root` to `target.root` | In the supported bare-plus-worktree layout state sits inside the workspace root by design but outside every worktree; comparing to the workspace root would warn on the healthy layout. |
| An empty `git.worktrees()` result raises `LayoutError` rather than passing | A successfully resolved working tree always lists at least itself, so `[]` means the list could not be verified — the guard fails closed from every position. |
| The bare-target refusal keeps its existing raise site in `TargetRepo.resolve` and only upgrades the message | A duplicate bare check in `check_layout` would be dead code; the upgraded message carries the copy-pasteable `git -C <bare> worktree add ../main main` corrective command. |
| `aidw/paths.py` gains a public `origin_remote()` accessor instead of `layout.py` importing the private `_origin_remote` | The trap message builds its re-bootstrap from real values and preserves the module boundary; a missing remote falls back to the rejected clone as the clone source. |

**Where it fits in the roadmap:** Task E2.2 builds directly on E2.1's git worktree primitives (`worktrees()`) and E1's resolved `TargetRepo`/`WorkspacePaths` roots. It is the guard layer every later E2 task relies on: E2.3 (`aidw worktree add|list|remove`), E2.4 (branch setup), E2.5/E2.6 (workflow worktree resolution), E2.7 (run-per-worktree locking), E2.8 (doctor layout checks) and E2.9 (shared worktree fixture).

**Scope:** Adds `aidw/layout.py` and `tests/test_layout.py`, wires the guards into `cli.py:_roots`, and exposes `origin_remote()` in `aidw/paths.py`, including the upgraded bare-refusal message. It deliberately stops short of E2.3's worktree CLI and dirty/unmerged `--force` wrapper, E2.4's branch-setup stage, E2.8's doctor checks, E2.9's shared fixture, and any change to the state-root formula or `WorkspacePaths.resolve`.

---

## Files Changed

The change set is the working tree relative to `main`. The implementation, tests and prompt changes are uncommitted; the task prompt was committed earlier on the branch.

| File | Action | Description |
|------|--------|-------------|
| `aidw/layout.py` | Created | `LayoutError` and `check_layout()`: fail-closed worktree-list verification, clone-of-a-worktree detection from both positions, state-inside-working-tree warning, and copy-pasteable corrective messages for the trap. |
| `tests/test_layout.py` | Created | Real-repo tests for the trap from the clone and linked child, corrective re-bootstrap, unverifiable-list fail-closed behaviour, single-checkout warning, supported bare+worktree layout, bare-refusal message, CLI wiring, purity, read-only git use and cwd invariance. |
| `aidw/cli.py` | Modified | `_roots` calls `check_layout` after `WorkspacePaths.resolve`, echoes warnings to stderr, and maps `LayoutError` to `EXIT_REFUSED` like the existing root-resolution failures. |
| `aidw/paths.py` | Modified | Upgraded `BareRepositoryError` with the §3.2 corrective `git -C <bare> worktree add ../main main`; added public `origin_remote()` accessor over the existing private helper. |
| `docs/task-prompts/00-E2.2-prompt.md` | Created (committed) | Task prompt authored and revised on the branch before implementation. |

---

## Changes Made

### 1. `aidw/layout.py`

- **`LayoutError(RuntimeError)`** — hard failure for an unsupported layout.
- **`check_layout(target, workspace)`** — reads `git.worktrees(target.root)`; raises when the list is empty; raises the clone-of-a-worktree failure when `workspace.workspace_root` is a listed worktree and more than one worktree is registered; otherwise returns the state-inside-working-tree warning when `workspace.state_root.is_relative_to(target.root)`.
- **Corrective messages** — the trap message derives `<parent>` from the rejected clone's parent and uses `origin_remote()` (falling back to the clone) for a real `git clone --bare` command, followed by the `mv` and `git -C <bare> worktree add ../main main` steps; the unverifiable-list message names the failed `git worktree list` and requires no bootstrap.
- The module is read-only: it never writes and never runs mutating git.

### 2. `aidw/cli.py`

- `_roots` now resolves `WorkspacePaths`, calls `check_layout`, echoes each advisory warning to stderr, and catches `LayoutError` to exit `EXIT_REFUSED` with the message on stderr.
- The new `git worktree list` spawn on the `_roots` path is documented in the module docstring as required by AGENTS.md.

### 3. `aidw/paths.py`

- `BareRepositoryError` now names the cause and includes the copy-pasteable control-worktree bootstrap command.
- `origin_remote(repo_root)` exposes `_origin_remote` with the same `str | None` contract.

### 4. `tests/test_layout.py`

- Builds real repositories for all four layouts: bare, supported bare+control (+ task worktree), single-checkout plain clone, and plain clone with a linked worktree.
- Covers both trap positions, no-origin fallback, corrective-command execution and re-resolution, empty-list fail-closed behaviour, warnings, bare refusal, CLI exits/stderr, purity and cwd invariance.

---

## Verification Results

> **Overall gate: ❌ FAIL.** `uv run --frozen pytest` produced **2 failed, 567 passed in 82.11s**. Both failures are the space-containing-path tests for the corrective shell commands: the printed commands are not quoted, so a path such as `/tmp/.../bare workspace/bare.git` is split by the shell and `git worktree add` exits 128. Install, build, doctor, agent validation and prompts check all passed. The suite was not re-run after the failure; the results below are from this recording run.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Exit 0 — `Checked 15 packages in 8ms` (gate `install`, tree `d53a5945415e`, stage `cli`, 2026-10-26T09:17:42Z) |
| Build | `uv build --out-dir /tmp/aidt-e22-build.UlyE0p` | ✅ Exit 0 — built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` into the temp dir (gate `build`, tree `d53a5945415e`, 2026-10-26T09:17:52Z) |
| Test | `uv run --frozen pytest` | ❌ Exit 1 — **`2 failed, 567 passed in 82.11s`** (gate `suite`, tree `d53a5945415e`, 2026-10-26T09:19:25Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)` (gate `doctor`, tree `d53a5945415e`, 2026-10-26T09:19:33Z). Warnings are the dirty working tree and missing `.mcp.json`, both expected |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents`, tree `d53a5945415e`, 2026-10-26T09:19:34Z) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts`, tree `d53a5945415e`, 2026-10-26T09:19:35Z) |
| Whitespace | `git diff --check` | ✅ Exit 0 — no whitespace errors |

### `uv run --frozen pytest` (full suite)

Single invocation: **`2 failed, 567 passed in 82.11s`** (exit 1). The subset row below comes from that same gate; no second run was made.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 569 | ❌ Fail (`2 failed, 567 passed in 82.11s`, gate `suite`) |
| `tests/test_layout.py` (within the full suite) | 26 | ❌ Fail (2 failures, named below) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run --frozen pytest tests/test_layout.py` | ❌ Fail via the full-suite invocation above — `test_corrective_commands_are_copy_pasteable_for_paths_with_spaces` and `test_bare_corrective_command_is_copy_pasteable_for_paths_with_spaces` both raised `subprocess.CalledProcessError` because the emitted `git -C <path with spaces>` command was not shell-quoted; `git worktree add` exited 128 |
| Trap fails from the plain clone and the linked child | ✅ Covered by `test_trap_fails_from_the_plain_clone`, `test_trap_fails_from_the_linked_child` |
| Trap message targets the parent outside the rejected clone; origin and no-origin sources | ✅ Covered by `test_trap_message_targets_the_parent_outside_the_rejected_clone`, `test_trap_message_uses_the_configured_origin_remote`, `test_trap_message_without_origin_uses_the_local_clone_source` |
| Unverifiable worktree list fails closed from both positions | ✅ Covered by `test_unverifiable_worktree_list_fails_closed_from_the_plain_clone`, `test_unverifiable_worktree_list_fails_closed_from_a_linked_worktree` |
| Single-checkout warns without raising; supported layout passes | ✅ Covered by `test_single_checkout_warns_without_raising`, `test_supported_bare_and_control_worktree_passes`, `test_supported_layout_with_a_task_worktree_passes_from_each_worktree` |
| Bare refusal carries the corrective `worktree add` | ✅ Covered by `test_bare_refusal_message_carries_the_corrective_worktree_add`; the space-containing-path variant fails (above) |
| CLI wiring refuses from both trap positions, warns on single checkout, passes supported layout | ✅ Covered by `test_cli_refuses_from_the_plain_clone`, `test_cli_refuses_from_the_linked_child`, `test_cli_refuses_on_an_unverifiable_worktree_list`, `test_cli_warns_on_the_single_checkout_layout`, `test_cli_passes_the_supported_layout_without_warning` |
| Purity and read-only behaviour | ✅ Covered by `test_check_layout_leaves_the_repository_unchanged`, `test_check_layout_runs_only_read_only_git`, `test_check_layout_verdict_is_invariant_to_cwd` |

---

## Deviations observed during recording

- **Suite failure not fixed here.** The full gate failed on two corrective-command tests. Per the record stage's scope, implementation code and tests were not modified; the failure is recorded rather than repaired.
- **Every gate emitted the new single-checkout warning.** Because this toolkit checkout is itself a single working tree, `_roots` printed the §3.10 advisory warning before each gate. This is the intended new warning, not a gate failure.
- **Roadmap checkbox remains unchecked.** `docs/tasks/00 - Extraction.md` still shows `[ ] **E2.2. Target/layout guards**`; changing traceability is outside this stage's write scope.
- **Generic template is pnpm/srd-shaped; this repo is uv-based.** There is no `package.json`, `pnpm-workspace.yaml`, `srd:*` script or `infra` CDK project, so no `pnpm`/`srd:*`/`cdk` gate applies. The repo's own gates from `AGENTS.md` and `.github/workflows/ci.yml` were run instead.
- **Gates ran with the recording run identity removed.** Each command was run with `env -u AIDW_STAGE -u AIDW_RUN_ID` so the inherited stage/run did not leak into tests that exercise `aidw gate run`, matching CI and avoiding the environmental failures observed in E2.1.

---

## Non-Goals (NOT implemented)

- ❌ E2.3 `aidw worktree add|list|remove` CLI and the dirty/unmerged `--force` wrapper (task prompt, Explicit non-goals)
- ❌ E2.4 branch-setup Python stage consuming `add_worktree` with `base_branch`/`branch_pattern` (task prompt, Explicit non-goals)
- ❌ E2.8 doctor checks (git ≥ 2.31, target-is-not-bare, control-worktree, workspace/state root) — E2.2's guards live in `_roots`, not `doctor` (task prompt, Explicit non-goals)
- ❌ E2.9 shared worktree fixture — E2.2's fixtures stay local to `tests/test_layout.py` (task prompt, Explicit non-goals)
- ❌ Any change to the state-root formula or `WorkspacePaths.resolve` — the warning only observes the already-resolved `state_root` (task prompt, Explicit non-goals)
- ❌ No commit, push or pull request — `aidt/prompts/pr.md` owns delivery; the implementation, tests and prompt remain uncommitted
