# Build Results — 00-E2.4: Branch setup becomes a Python stage, not a prompt

**Branch:** `00-E2.4`
**Date:** 2026-10-29
**Spec:** `docs/migration/EXTRACTION.md` §3.2 (Workspace and worktree model — per-task `worktree add -b <branch> <workspace-root>/<branch> <base-branch>`, one-branch-one-worktree, the `agent.cwd` plumbing note), §3.4 (Target-repo config — `repo.base_branch`/`repo.branch_pattern` schema), §3.5 (Stage and workflow model — D13 "plus Python-owned branch setup", the `I1..I6` id continuity), §4.2 (Prompts — the `impliment-task.md` bucket (ii) row); `design.md` §8.2 (`aidw implement`), §14 (CLI reference — exit codes 0 ok, 1 stage/gate, 2 usage, 3 blocked, 4 safety refusal). Roadmap: `docs/tasks/00 - Extraction.md` Epic E2 ("Worktree model", D20), task E2.4.

## Summary

**Purpose:** Move task-branch creation out of the implementation prompt and into `aidw implement` itself: before the first agent stage runs, Python derives the branch worktree name from `repo.branch_pattern`, creates the worktree from `repo.base_branch`, and re-resolves the target and agents so I1..I6 run inside it.

| Decision | Why it matters |
|----------|---------------|
| `parse_task_id` stays a pure one-argument filename parser returning the task id; `run()` derives the branch name via `repo.branch_pattern.format(phase=, task=)` | §3.4 sources the branch/worktree name from task ids. Keeping the derivation in one place in `run()` means the git branch, the worktree directory and the state label cannot diverge; under the default pattern the names stay byte-identical (`00-E2.4`, `02.5-B`). |
| A malformed pattern is a usage error (`EXIT_USAGE`, 2), checked before branch-setup | §3.4 "name from task ids", §3.2 one-branch-one-worktree: a constant or partial name would collide across tasks. Refusing in Python before any write is better than a `.format` `KeyError` traceback. |
| `branch-setup` is inline Python in `run()`, not a `PlanStage` | §3.5 keeps `I1..I6` as the default six stage ids for continuity in run artifacts and `state.json`; branch-setup leaves no stage record and never flows through `run_stage`. |
| `git.add_worktree(...) is None` fails closed with `EXIT_REFUSED` (4) | The primitive does not return a reason, so "already checked out" and any other git refusal are treated alike. E2.6 owns locate/reuse; this step is create-only. |
| The prompt file is copied into the new worktree when absent there | The worktree is born at the base commit, so a task prompt still uncommitted in the control worktree (the standard authoring layout) would be missing. A copy keeps I1's `$1` and I5's relative `docs/task-prompts/<branch>-prompt.md` both resolvable; an absolute path would break I5, and refusing unless committed would break the authoring layout. |
| The target and agents are re-resolved against the worktree (`replace(TargetRepo.resolve(...), ...)`) | `agent.cwd` is resolved once against the repo root in `load_agent`; without re-resolution I1..I6 would silently run in the control worktree — the exact §3.2 failure this task removes. `TargetRepo` is frozen, so a fresh resolve plus `replace` is used instead of mutation. |
| The diff/PR base follows `repo.base_branch` at every call site (`_gate_summary`, `_record_pr`, I4's `base_ref`) | §3.4 makes `base_branch` the "PR base and branch point"; R4 keeps `main` out of the code for repos whose base branch differs. |

**Where it fits in the roadmap:** E2.4 sits in Epic E2 (worktree model) between E2.3's `aidw worktree add|list|remove` command (which it consumes through `git.add_worktree`) and E2.5/E2.6, which build on the worktree it now creates: E2.5 (`aidw prompt` worktree creation for authoring) and E2.6 (`implement`/`fix` locating/reusing an existing worktree, which supersedes this task's fail-closed refusal). E2.7 (per-worktree run locking), E2.8 (doctor worktree/git checks) and E2.9 (shared bare+control fixture) follow; E3 wires `base_branch`/`branch_pattern` to `aidw/config.yaml`.

**Scope:** Touches `aidw/paths.py` (new `TargetRepo.branch_pattern` field), `aidw/workflows/implement.py` (branch-setup step, `derive_branch_name`, base-branch threading), `prompts/impliment-task.md` (removes the agent branch-setup section), the workflow/target tests, and marks E2.4 complete in the roadmap. It deliberately stops short of locating/reusing an existing worktree (E2.6), `aidw prompt` worktree creation (E2.5), config-driven values (E3), and neutralising the rest of `impliment-task.md`'s `pnpm`/`srd:*` content (E7.2).

---

## Files Changed

The change set is the working tree relative to `main`. The task prompt is committed on the branch; the implementation, tests and roadmap checkbox are uncommitted.

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E2.4-prompt.md` | Created (committed) | Task prompt authored on the branch before implementation. |
| `aidw/paths.py` | Modified | Adds `TargetRepo.branch_pattern: str = "{phase}-{task}"`, mirroring `base_branch`, with the §3.4 default. |
| `aidw/workflows/implement.py` | Modified | Adds `derive_branch_name`/`_branch_pattern_fields`, the inline `branch-setup` step (create the worktree, copy the prompt, re-resolve target/agents), removes the main/branch-mismatch preflight, retains the still-running guard, and threads `repo.base_branch` through `build_plan` (I4 `base_ref`), `_gate_summary`, `_record_pr` and `create_run`. |
| `prompts/impliment-task.md` | Modified | Removes the "Branch setup" agent instructions (`branch --list`/`ls-remote`/`checkout -b`/`show-current`) and leaves a one-line pointer that AIDT owns branch setup (§3.2). |
| `tests/test_implement_workflow.py` | Modified | Converts the harness to the bare+control layout so every `run()` test exercises real branch-setup; adds branch-name derivation, malformed-pattern, worktree-before-I1, prompt-copy, base-branch, agent-reload, fail-closed and readiness-guard tests; deletes the `main`/mismatch preflight tests. |
| `tests/test_target_repo.py` | Modified | Pins the new `branch_pattern` field and the five-field `TargetRepo` shape. |
| `tests/test_toolkit_paths.py` | Modified | Updates the `TargetRepo` field-set assertion for `branch_pattern`. |
| `tests/test_workspace_paths.py` | Modified | Updates the shared `TargetRepo` field-order assertion for `branch_pattern`. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks `E2.4. Branch setup becomes a Python stage, not a prompt` complete (`[x]`). |

---

## Verification Results

> **Overall gate: ✅ PASS.** `uv run --frozen pytest` produced **728 passed in 84.60s** (exit 0). Install, build, doctor, agent validation and prompts check also passed, and `git diff --check` is clean. Every row below is a recorded outcome of this run's single invocation of each command, against tree `285f65ef0372`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Exit 0 — `Checked 15 packages in 0.80ms` (gate `install`, tree `285f65ef0372`, stage `record-implementation-results`, 2026-10-29T00:04:20Z) |
| Build | `uv build --out-dir /tmp/aidt-e24-build.nef98u` | ✅ Exit 0 — built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` (gate `build`, tree `285f65ef0372`, 2026-10-29T00:04:37Z) |
| Test | `uv run --frozen pytest` | ✅ Exit 0 — **728 passed in 84.60s** (gate `suite`, tree `285f65ef0372`, stage `record-implementation-results`, 2026-10-29T00:06:12Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)` (gate `doctor`, tree `285f65ef0372`, 2026-10-29T00:06:36Z). Warnings are the dirty working tree and the missing `.mcp.json`, both expected |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents`, tree `285f65ef0372`, 2026-10-29T00:06:37Z) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts`, tree `285f65ef0372`, 2026-10-29T00:06:37Z) |
| Whitespace | `git diff --check` / `git diff --check main` | ✅ Exit 0 — no whitespace errors in tracked changes |

### `uv run --frozen pytest` (full suite)

Single invocation: **`728 passed in 84.60s`** (exit 0, gate `suite`, tree `285f65ef0372`). The subset rows below are drawn from that same run; no second run was made.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 728 | ✅ Pass (`728 passed in 84.60s`, exit 0, gate `suite`) |
| `tests/test_implement_workflow.py` (within the full suite) | included in 728 | ✅ Pass (all tests in this module passed; focused per-file count not separately observed) |
| `tests/test_git.py` (within the full suite) | included in 728 | ✅ Pass (all tests in this module passed; focused per-file count not separately observed) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Worktree exists before I1; prompt copied for an uncommitted control-worktree prompt | ✅ Covered by `test_worktree_exists_before_first_stage_and_prompt_is_copied` — sibling `<workspace_root>/<branch>` on disk, I1's `repo_root` = the worktree, `<worktree>/<prompt_rel>` present |
| Target/agents re-resolved against the created worktree | ✅ Covered by `test_agents_are_reloaded_against_the_created_worktree` — `load_all` called with the control root then the worktree |
| `--dry-run` plans branch-setup and six stages but writes no worktree | ✅ Covered by `test_dry_run_plans_branch_setup_and_all_six_stages` — sibling worktree path does not exist |
| Default `branch_pattern` reproduces the task id byte-for-byte | ✅ Covered by `test_derive_branch_name_default_reproduces_the_task_id` (`00-E2.4`, `02.5-B`) |
| Non-default pattern names the branch, worktree and state label consistently | ✅ Covered by `test_non_default_branch_pattern_names_branch_worktree_and_state` |
| Malformed pattern (unknown placeholder / missing `phase`/`task`) refused with exit 2 before any worktree or stage | ✅ Covered by `test_derive_branch_name_rejects_malformed_patterns`, `test_malformed_branch_pattern_is_usage_error_before_worktree` |
| Non-default `base_branch` flows through worktree, `state.pr.changed_files` and I4's `base_ref` | ✅ Covered by `test_base_branch_flows_through_the_whole_run`, `test_build_plan_uses_the_configured_base_branch` |
| Branch-setup fails closed (`EXIT_REFUSED`) when the branch is already checked out | ✅ Covered by `test_branch_setup_fails_closed_when_branch_already_checked_out` — no `run_stage`, no partial run state |
| Still-running run refused without `--resume`, before branch-setup | ✅ Covered by `test_running_run_is_refused_without_resume` |
| `impliment-task.md` has no agent branch-setup commands | ✅ Covered by `test_impliment_prompt_has_no_agent_branch_setup` |
| Ported `run()` tests exercise real branch-setup (bare+control, real git) | ✅ Full run / stage failure / gate denial / resume / `--from` / serial-parallel / dry-run tests all pass within the 728 |

---

## Deviations observed during recording

- **Gates ran with the recording run identity removed from the child environment.** Each `aidw gate run` invocation was made with `env -u AIDW_STAGE -u AIDW_RUN_ID` and `--run`/`--stage` supplied explicitly, so the inherited stage/run does not leak into tests that exercise `aidw gate run` (the environmental `unknown run` failures seen in E2.1/E2.3). This matches CI; the gate still records into this run.
- **The generic `record-implementation-results.md` template is `pnpm`/`srd:*`/`cdk`-shaped; this repo is uv-based.** There is no `package.json`, `pnpm-workspace.yaml`, `srd:*` script or `infra` CDK project, so no `pnpm`/`srd:*`/`cdk` row applies. The repo's own gates from `AGENTS.md` and `.github/workflows/ci.yml` were run instead, reusing the gate keys E2.1–E2.3 established (`install`, `build`, `suite`, `doctor`, `agents`, `prompts`).
- **A first gate invocation was mistyped and produced no real evidence.** `aidw gate run --run … -- uv sync --frozen` placed the command's first token in the positional `<key>` slot, recording a stray `uv` gate whose command was `sync --frozen`. That bogus outcome was removed from this run's state; the correct `install` gate above is the real observation.
- **The task prompt's focused command was not re-run.** The task prompt's Done-when names `uv run --frozen pytest tests/test_implement_workflow.py tests/test_git.py`. Both modules are inside the full-suite invocation already run, so per the record stage's "run each command exactly once" rule they are recorded as covered by the `suite` gate rather than bought a second time; no per-file count was observed or invented.
- **Every `aidw` invocation emitted the single-checkout layout warning.** This toolkit checkout is itself a single working tree, so `_roots` prints the §3.10 advisory before each gate. This is the intended E2.2 warning, not a gate failure.
- **The `agents` gate's one-line summary captured the layout warning**, because the advisory is the last non-blank line of the captured output; the observed result printed by the command was `11 agent config(s): 0 error(s), 0 warning(s)` and its exit code was 0.

---

## Non-Goals (NOT implemented)

- ❌ E2.5 `aidw prompt` running in the control worktree and creating the task worktree for authoring — branch-setup is not wired into `prompt.py` (task prompt, Explicit non-goals)
- ❌ E2.6 `implement`/`fix` resolving their worktree via `worktrees()` from an unrelated cwd — branch-setup *creates*, E2.6 *locates* (task prompt, Explicit non-goals)
- ❌ E2.7 per-worktree run locking (task prompt, Explicit non-goals)
- ❌ E2.8 doctor worktree/git checks (task prompt, Explicit non-goals)
- ❌ E2.9 shared worktree fixture — the bare+control layout is mirrored locally inside `tests/test_implement_workflow.py` (task prompt, Explicit non-goals)
- ❌ E3 config-driven `base_branch`/`branch_pattern` (loading `aidw/config.yaml`) — this task uses the hardcoded `TargetRepo` defaults (task prompt, Explicit non-goals)
- ❌ E7.2 neutralising the rest of `impliment-task.md`'s `pnpm`/`@mythical-forge`/`srd:*` content — only the branch-setup section is removed (task prompt, Explicit non-goals)
- ❌ No commit, push or pull request — `aidt/prompts/pr.md` owns delivery (task prompt, Non-goals)
