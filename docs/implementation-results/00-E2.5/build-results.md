# Build Results — 00-E2.5: `aidw prompt` runs in the control worktree and creates the task worktree

**Branch:** `00-E2.5`
**Date:** 2026-10-29
**Spec:** `docs/migration/EXTRACTION.md` §3.2 (workspace and worktree model — the per-task `git -C <workspace-root>/main worktree add -b <branch> <workspace-root>/<branch> <base-branch>` command, one-branch-one-worktree, and `agent.cwd` plumbing), §3.4 (target-repo config — `repo.base_branch` and `repo.branch_pattern`); `design.md` §8.1 (`aidw prompt`), §13 (git and GitHub safety), §14 (CLI exit codes). Roadmap: `docs/tasks/00 - Extraction.md` Epic E2 ("Worktree model"), task E2.5.

## Summary

**Purpose:** Make `aidw prompt` derive the branch/worktree name from `repo.branch_pattern`, create the task worktree itself before the author stage, and run the author/review/fix stages inside that worktree, so the author no longer creates or commits on a branch.

| Decision | Why it matters |
|----------|---------------|
| Reuse `derive_branch_name` from `aidw/workflows/implement.py` | Both workflows share one `string.Formatter` contract for `branch_pattern`; a malformed pattern is a usage error (exit 2) before any worktree, stage or run state, rather than a duplicated parser or a traceback. |
| Create the worktree inline with `git.add_worktree(repo.root, branch_name, base_branch=repo.base_branch)` before the author stage | Matches §3.2's per-task command and E2.4's branch-setup order. The worktree is deterministic, so a blocked run can report it unconditionally and the old before/after branch probe is no longer needed. |
| Fail closed when `add_worktree` returns `None` (exit 4) | The primitive discards git's stderr, so "branch already checked out" and any other git refusal are reported with one actionable message. No `run_stage` call and no run state are created. |
| Re-resolve `TargetRepo` against the worktree and reload agents with `load_all(aidt.root, target.root)` | `agent.cwd` is resolved once against the control root; without re-resolution P1 and every review/fix stage would silently run in the control worktree — the §3.2 failure this task removes. `TargetRepo` is frozen, so `resolve` plus `replace` is used instead of assignment. |
| `_commit_reviewed_prompt(target.root, rel, phase, task)` becomes the single commit point | The author no longer commits. The reviewed (or initial) prompt is committed only after the review loop, via `git.commit_paths`, on the branch the worktree already has checked out, and only for the owned prompt path. |
| Keep the prompt filename on `{phase}-{task}` even when `branch_pattern` differs | `default_rel` and `_resolve_prompt_path` are task-id based, matching `implement.py`; `branch_name` flows separately through the worktree, `create_run`, `state.git["branch"]` and the final print. |

**Where it fits in the roadmap:** E2.5 sits in Epic E2 (worktree model) after E2.4, which moved branch setup into `aidw implement`, and completes the same branch-setup move for prompt authoring. It depends on E2.4's `derive_branch_name` and `git.add_worktree` usage. E2.6 (locate/reuse an existing worktree) supersedes this task's create-only refusal; E2.7 (per-worktree locking), E2.8 (doctor worktree/git checks) and E2.9 (shared worktree fixture) follow. E3 will wire `base_branch`/`branch_pattern` to `aidw/config.yaml`.

**Scope:** Changes the `aidw prompt` preflight and branch-setup path, the task-author prompt's branch/commit instructions, the prompt-workflow test harness, and the roadmap checkbox. It deliberately stops short of locating or reusing an existing worktree (E2.6), per-worktree locking (E2.7), doctor worktree/git checks (E2.8), a shared worktree fixture (E2.9), config-driven values (E3), and neutralising the unrelated `pnpm`/`catalog.json`/Zod content in `prompts/task-prompt.md` (E7).

---

## Files Changed

The change set is the working tree relative to `main`; this branch has no commits ahead of `main`, so every file below is uncommitted.

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E2.5-prompt.md` | Created | Task prompt authored on the branch before implementation (untracked in the working tree). |
| `aidw/workflows/prompt.py` | Modified | Derives the branch/worktree name from `repo.branch_pattern`; guards on `repo.base_branch`; creates the task worktree before the author stage; re-resolves the target and reloads agents against it; threads `target.root` through every stage, path resolution, commit and the blocked report; removes the obsolete branch probe. |
| `prompts/task-prompt.md` | Modified | Removes author-side branch creation, switching, verification and commit instructions; adds a one-line pointer that AIDT owns branch setup and commits the reviewed prompt; rewords the feasibility bullet to run before writing the prompt file. |
| `tests/test_prompt_workflow.py` | Modified | Converts the prompt-workflow harness to the real bare+control layout with a committed base; adds full-run worktree/clean-control/only-prompt-committed, base-branch, branch-pattern, fail-closed, dry-run and prompt-cleanliness coverage. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks `E2.5. aidw prompt runs in the control worktree and creates the task worktree` complete (`[x]`). |

---

## Verification Results

> **Overall gate: ✅ PASS.** `uv run --frozen pytest` produced **738 passed in 111.51s** (exit 0). Install, build, doctor, agent validation and prompts check also passed, and `git diff --check` is clean. Each row below is the real outcome of this run's single invocation of that command; outcomes cited from `aidw gate` name their key, tree, stage and timestamp.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Exit 0 — `Checked 15 packages in 0.63ms` (gate `install`, tree `954e9dc6d96a`, stage `record-implementation-results`, 2026-10-29T22:10:22Z) |
| Build | `uv build --out-dir /tmp/aidt-e25-build.ddmB8c` | ✅ Exit 0 — built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` (gate `build`, tree `954e9dc6d96a`, stage `record-implementation-results`, 2026-10-29T22:10:28Z) |
| Test | `uv run --frozen pytest` | ✅ Exit 0 — **738 passed in 111.51s (0:01:51)** (gate `suite`, tree `6186e3a1e404`, stage `record-implementation-results`, 2026-10-29T22:12:25Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)` (gate `doctor`, tree `6186e3a1e404`, stage `record-implementation-results`, 2026-10-29T22:12:32Z). Warnings are the dirty working tree and the missing `.mcp.json`, both expected. |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents`, tree `6186e3a1e404`, stage `record-implementation-results`, 2026-10-29T22:12:33Z) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts`, tree `6186e3a1e404`, stage `record-implementation-results`, 2026-10-29T22:12:34Z) |
| Whitespace | `git diff --check` / `git diff --check main` | ✅ Exit 0 — no whitespace errors in tracked changes |

### `uv run --frozen pytest` (full suite)

Single invocation: **`738 passed in 111.51s`** (exit 0, gate `suite`, tree `6186e3a1e404`). The subset rows below are drawn from that same run; no second run was made.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 738 | ✅ Pass (`738 passed in 111.51s`, exit 0, gate `suite`) |
| `tests/test_prompt_workflow.py` (within the full suite) | included in 738 | ✅ Pass (all tests in this module passed; focused per-file count not separately observed) |
| `tests/test_implement_workflow.py` (within the full suite) | included in 738 | ✅ Pass (all tests in this module passed; focused per-file count not separately observed) |
| `tests/test_git.py` (within the full suite) | included in 738 | ✅ Pass (all tests in this module passed; focused per-file count not separately observed) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Full run creates exactly one sibling worktree, leaves the control worktree clean, and commits only the prompt path on the task branch | ✅ Covered by `test_full_run_creates_one_worktree_keeps_control_clean_and_commits_only_prompt` |
| Non-default `base_branch` proceeds and the worktree branches from it | ✅ Covered by `test_non_default_base_branch_flows_through_and_worktree_branches_from_it` and `test_prompt_workflow_requires_base_branch_for_real_run` |
| Default `branch_pattern` reproduces `00-E2.5` and the sub-phase form (`03.1-A2`) | ✅ Covered by `test_derive_branch_name_default_reproduces_task_id_and_subphase` |
| Non-default `branch_pattern` names the branch, worktree and `state.git["branch"]` consistently | ✅ Covered by `test_non_default_branch_pattern_names_branch_worktree_and_state_consistently` |
| Malformed pattern (unknown placeholder, or missing `phase`/`task`) exits 2 before any worktree | ✅ Covered by `test_malformed_branch_pattern_is_a_usage_error_before_any_worktree` |
| Branch already checked out fails closed (exit 4) with no `run_stage` call and no run state | ✅ Covered by `test_branch_already_checked_out_fails_closed_before_any_stage` |
| Invalid agent config refuses before worktree creation or run state | ✅ Covered by `test_invalid_agent_config_refuses_before_worktree_or_run_state` |
| `--dry-run` prints the planned `worktree add -b …`, names the base-branch requirement, and creates no worktree | ✅ Covered by `test_prompt_workflow_dry_run` |
| Blocked run reports the created worktree unconditionally instead of a before/after branch probe | ✅ Covered by `test_l13_blocked_run_reports_created_worktree_unconditionally` |
| `prompts/task-prompt.md` contains no branch-creation or commit instructions and points at AIDT-owned branch setup | ✅ Covered by `test_task_prompt_contains_no_branch_creation_or_commit_instructions` |
| Prompt-workflow tests exercise real bare+control branch setup (real git, Pi seam mocked) | ✅ Ported harness plus full-run, preflight, review/fix, blocked and dry-run tests all pass within the 738 |

---

## Deviations observed during recording

- **The generic `record-implementation-results.md` template is `pnpm`/`srd:*`/`cdk`-shaped; this repo is uv-based.** There is no `package.json`, `pnpm-workspace.yaml`, `srd:*` script or `infra` CDK project, so no `pnpm`/`srd:*`/`cdk` row applies. The repo's own gates from `AGENTS.md` and `.github/workflows/ci.yml` were run instead, reusing the gate keys E2.4 established (`install`, `build`, `suite`, `doctor`, `agents`, `prompts`).
- **The task prompt's focused command was not re-run as a second pytest invocation.** The Done-when names `uv run --frozen pytest tests/test_prompt_workflow.py tests/test_implement_workflow.py tests/test_git.py`. All three modules are inside the full-suite invocation already run, so they are recorded as covered by the `suite` gate rather than bought a second time; no per-file count was observed or invented.
- **Install and build gates were recorded against tree `954e9dc6d96a`, while the suite/doctor/agents/prompts gates used tree `6186e3a1e404`.** The latter commands were gated with the `pr.md` scope (`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`), so their tree identity excludes those write-target documents. Both identities are this run's own observations; none of the source, tests, config or lockfiles are inside the ignored scope.
- **Every `aidw` invocation emitted the single-checkout layout warning and a `VIRTUAL_ENV` mismatch warning.** The checkout is a single working tree, so the §3.10 advisory is expected; the active environment warning is from the shell's inherited `VIRTUAL_ENV` and the project `.venv` selection, not a gate failure.

---

## Non-Goals (NOT implemented)

- ❌ E2.6 `implement`/`fix` resolving their worktree via `worktrees()` from an unrelated cwd — this task only creates the prompt worktree (task prompt, Explicit non-goals)
- ❌ E2.7 per-worktree run locking (task prompt, Explicit non-goals)
- ❌ E2.8 doctor worktree/git checks (task prompt, Explicit non-goals)
- ❌ E2.9 shared worktree fixture — the bare+control layout is mirrored locally inside `tests/test_prompt_workflow.py` (task prompt, Explicit non-goals)
- ❌ E3 config-driven `base_branch`/`branch_pattern` (loading `aidw/config.yaml`) — this task uses the hardcoded `TargetRepo` defaults (task prompt, Explicit non-goals)
- ❌ E7.1/E7.4 bucket-(iii) marker header on `task-prompt.md` and the `agents/task-author/AGENTS.md` reword — only branch/commit language is edited here (task prompt, Explicit non-goals)
- ❌ No commit, push or pull request — `aidt/prompts/pr.md` owns delivery (task prompt, Non-goals)
