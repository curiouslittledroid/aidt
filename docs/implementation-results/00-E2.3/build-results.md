# Build Results — 00-E2.3: `aidw worktree add|list|remove`

**Branch:** `00-E2.3`
**Date:** 2026-10-28
**Spec:** `docs/migration/EXTRACTION.md` §3.3 (CLI surface changes — the three `worktree` command rows, stable existing subcommands/exit codes/stdout JSON keys), §3.2 (Workspace and worktree model — per-task `worktree add`, one-branch-one-worktree, the `git worktree list --porcelain` branch↔worktree fact), §3.12 (New repo layout — test location `tests/`); `design.md` §14 (CLI reference — exit codes 0 ok, 1 stage/gate, 2 usage, 3 blocked, 4 safety refusal). Roadmap: `docs/tasks/00 - Extraction.md` Epic E2 ("Worktree model", D20), task E2.3.

## Summary

**Purpose:** Add `aidw worktree add|list|remove` as thin, safe operator wrappers over the E2.1 git worktree primitives, with `remove` refusing a dirty tree or an unmerged branch unless `--force` is explicit.

| Decision | Why it matters |
|----------|---------------|
| `remove` takes a branch but resolves it to a path via `git.worktree_for_branch` before calling `git.remove_worktree` (which takes a path) | Passing the branch name as a path fails opaquely or, if a same-named directory exists, can target the wrong tree. |
| Unmerged means `git.is_ancestor(repo, branch, target.base_branch) is True`; `False` and `None` both refuse | git's own `worktree remove` accepts a clean-but-unmerged branch, and `None` means git cannot answer — failing closed prevents a missing base branch from silently passing the check. |
| The dirty refusal is checked before the unmerged refusal | "Never delete uncommitted work" is the headline invariant, so it wins when both unsafe cases hold. |
| `list --json` emits an array of `{path, branch, detached}` objects, serialising `str(path)` | A `{branch: path}` dict cannot represent a detached HEAD; `json.dumps` rejects `Path` objects. |
| `add` pre-checks `worktree_for_branch` before `add_worktree` and emits a generic refusal on `None` | §3.2 one-branch-one-worktree; `add_worktree` discards git's stderr, so the pre-check names the branch/path while an unexpected failure gets an actionable generic message. |
| Only `git.add_worktree`/`git.remove_worktree` mutate; every git call lives in the command body | No `reset --hard` or `rm -rf`, and no git spawn is added to the `_roots` path. |

**Where it fits in the roadmap:** E2.3 builds on E2.1's worktree primitives and E2.2's `_roots` layout guards. It is the manual operator command that later E2 tasks build on: E2.4 (branch-setup stage), E2.5 (`aidw prompt` worktree creation), E2.6 (`implement`/`fix` worktree resolution), E2.7 (run-per-worktree locking), E2.8 (doctor worktree/git checks) and E2.9 (shared worktree fixture).

**Scope:** Adds the `worktree` command to `aidw/cli.py` and `tests/test_worktree_cli.py`, and marks E2.3 complete in the roadmap. It deliberately stops short of E2.4's branch-setup stage, E2.5/E2.6 workflow wiring, E2.8 doctor checks, E2.9's shared fixture, config-driven `base_branch` (E3), and any control-worktree removal guard.

---

## Files Changed

The change set is the working tree relative to `main`. The task prompt is committed on the branch; the command, tests and roadmap checkbox are uncommitted.

| File | Action | Description |
|------|--------|-------------|
| `tests/test_worktree_cli.py` | Created | Real bare + control + task + detached worktree tests for `add`, `list --json` round-trip, human listing, dirty/unmerged/fail-closed `remove` refusals, `--force`, unknown branch/action, arity and purity. |
| `docs/task-prompts/00-E2.3-prompt.md` | Created (committed) | Task prompt authored on the branch before implementation. |
| `aidw/cli.py` | Modified | Adds the `worktree` command with `add`/`list`/`remove` action dispatch, `--base`, `--json`, `--force`, and the §14 exit-code mapping. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks `E2.3. aidw worktree add\|list\|remove` complete (`[x]`). |

---

## Verification Results

> **Overall gate: ❌ FAIL.** `uv run --frozen pytest` produced **3 failed, 709 passed in 101.55s**. All three failures are the same real `test_action_arity_rejects_arguments_belonging_to_another_action` parametrisation: `list extra`, `add feat --json` and `remove main --base dev` exit `0` instead of `EXIT_USAGE` (2), because the command's shared optional arguments/options are accepted for every action rather than rejected as belonging to another action. Install, build, doctor, agent validation and prompts check all passed. The failures were not repaired here.

The suite was first invoked inside this recording run's identity, which made two `tests/test_verification.py` gate tests fail (`unknown run` from the inherited `AIDW_RUN_ID`). It was re-run with `AIDW_STAGE`/`AIDW_RUN_ID` removed from the child environment, matching CI; the two environmental failures disappeared, leaving the three real failures below. Both invocations are real observations; the clean invocation is the one recorded as the final outcome.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Exit 0 — `Checked 15 packages in 0.89ms` (gate `install`, tree `75419616bfb6`, stage `record-implementation-results`, 2026-10-28T20:47:23Z) |
| Build | `uv build --out-dir <mktemp dir>` | ✅ Exit 0 — built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` (gate `build`, tree `75419616bfb6`, 2026-10-28T20:47:31Z) |
| Test | `uv run --frozen pytest` | ❌ Exit 1 — **`3 failed, 709 passed in 101.55s`** (gate `suite`, tree `75419616bfb6`, 2026-10-28T20:52:07Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)` (gate `doctor`, tree `75419616bfb6`, 2026-10-28T20:52:19Z). Warnings are the dirty working tree and missing `.mcp.json`, both expected |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents`, tree `75419616bfb6`, 2026-10-28T20:52:20Z) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts`, tree `75419616bfb6`, 2026-10-28T20:52:21Z) |
| Whitespace | `git diff --check` / `git diff --check main` | ✅ Exit 0 — no whitespace errors in tracked changes |

### `uv run --frozen pytest` (full suite)

Single clean invocation: **`3 failed, 709 passed in 101.55s`** (exit 1, 712 collected). The subset row below is derived from that same invocation (the file collected 21 tests; the three failures are all in this file, so it ran 18 passed / 3 failed); no second execution of the suite or module was made.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 712 | ❌ Fail (`3 failed, 709 passed in 101.55s`, gate `suite`) |
| `tests/test_worktree_cli.py` (within the full suite) | 21 | ❌ Fail (`18 passed, 3 failed` — the arity parametrisations below) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `add` creates `<workspace>/<branch>` and `list --json` reports it | ✅ Covered by `test_add_creates_sibling_worktree_and_list_json_reports_it`, `test_add_defaults_to_target_base_branch_and_honours_base` |
| Re-adding an already-checked-out branch refuses with `EXIT_REFUSED` | ✅ Covered by `test_add_refuses_an_already_checked_out_branch`, `test_add_refuses_when_git_declines` |
| `list --json` round-trips bare + control + task + detached; parsed JSON equals `git.worktrees()` | ✅ Covered by `test_list_json_round_trips_a_detached_worktree`; human mode and purity also pass |
| `remove` dirty refusal survives and `--force` overrides | ✅ Covered by `test_remove_refuses_a_dirty_tree_and_force_removes_it`, `test_remove_reports_the_dirty_cause_first_when_both_hold` |
| `remove` clean-but-unmerged refusal survives and `--force` overrides | ✅ Covered by `test_remove_refuses_a_clean_but_unmerged_branch`, `test_remove_fails_closed_when_the_merge_state_is_unverifiable` |
| `remove` success, unknown branch (`EXIT_USAGE`), generic git failure | ✅ Covered by `test_remove_succeeds_for_a_clean_merged_worktree`, `test_remove_unknown_branch_is_a_usage_error`, `test_remove_refuses_the_generic_git_failure` |
| Purity: `list` writes nothing; `add`/`remove` only touch their own worktree | ✅ Covered by `test_list_writes_nothing`, `test_add_and_remove_only_touch_their_own_worktree` |
| Unknown action and missing branch are usage errors | ✅ Covered by `test_unknown_action_is_a_usage_error`, `test_missing_branch_is_a_usage_error` |
| Per-action arity rejects arguments/flags belonging to another action | ❌ `test_action_arity_rejects_arguments_belonging_to_another_action[args0..2]` — exit `0` instead of `EXIT_USAGE` |

---

## Deviations observed during recording

- **Suite gate failed and was not repaired.** Three real arity failures remain in `tests/test_worktree_cli.py` (see above). Per the record stage's scope, implementation code and tests were not modified; the failure is recorded rather than fixed.
- **First suite invocation was contaminated by the recording run identity.** With `AIDW_STAGE`/`AIDW_RUN_ID` inherited, two `tests/test_verification.py` gate tests failed with `unknown run`. The suite was re-run with those variables removed from the child environment (the gate was still recorded into this run via `--run`/`--stage`), matching CI; the two failures disappeared. The final recorded `suite` outcome is the clean run.
- **Diff touches more than the two deliverable files.** The implementation also marks E2.3 `[x]` in `docs/tasks/00 - Extraction.md`, so the change set includes that traceability edit even though the task prompt's done-when says the diff touches only `aidw/cli.py` and `tests/test_worktree_cli.py`.
- **Generic template is pnpm/srd-shaped; this repo is uv-based.** There is no `package.json`, `pnpm-workspace.yaml`, `srd:*` script or `infra` CDK project, so no `pnpm`/`srd:*`/`cdk` gate applies. The repo's own gates from `AGENTS.md` and `.github/workflows/ci.yml` were run instead.
- **Every `aidw` invocation emitted the single-checkout layout warning.** This toolkit checkout is itself a single working tree, so `_roots` prints the §3.10 advisory before each gate. This is the intended E2.2 warning, not a gate failure.

---

## Non-Goals (NOT implemented)

- ❌ E2.4 branch-setup Python stage consuming `add_worktree` with `base_branch`/`branch_pattern` (task prompt, Explicit non-goals)
- ❌ E2.5 `aidw prompt` creating the task worktree automatically; `add` is not wired into any workflow (task prompt, Explicit non-goals)
- ❌ E2.6 `implement`/`fix` resolving their worktree via `worktrees()` (task prompt, Explicit non-goals)
- ❌ E2.8 doctor worktree/git checks (task prompt, Explicit non-goals)
- ❌ E2.9 shared worktree fixture — E2.3's fixtures stay local to `tests/test_worktree_cli.py` (task prompt, Explicit non-goals)
- ❌ `base_branch` from config (E3 owns config resolution) — `add` uses `target.base_branch` (`"main"` today) (task prompt, Explicit non-goals)
- ❌ Control-worktree removal guard — `remove`'s refusals are exactly the dirty and unmerged cases; E2.5/E2.8 own the control-worktree concern (task prompt, Explicit non-goals)
- ❌ No commit, push or pull request — `aidt/prompts/pr.md` owns delivery (task prompt, Non-goals)