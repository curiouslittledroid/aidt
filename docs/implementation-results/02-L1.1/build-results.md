# Build Results — 02-L1.1: Fetch, and require the base branch to be current

**Branch:** `02-L1.1`
**Date:** 2026-10-26
**Spec:** `docs/tasks/02 - Prompt loop integrity.md` — task L1.1 ("Fetch, and require the base branch to be current"), Epic L1 ("Scheduling and preflight — stop the bad seed"), including the phase preamble's E1.6 evidence. `design.md` §8.1 (`aidw prompt` preflight), §13 (Git and GitHub safety), §14 (CLI reference). `docs/migration/EXTRACTION.md` §3.2 (workspace/worktree model — the control worktree) and §3.10 (state root and locking, D18). `AGENTS.md` (Gates; Tests).

## Summary

**Purpose:** Make `aidw prompt` fetch `origin` before it authors anything and refuse the run when the local base branch is behind or diverged from `origin/<base>`, so a run can no longer be seeded against a tree that lacks a merged prerequisite — exactly the E1.6 failure, where the local base was never pulled while the E1.5 merge was already on `origin/main`.

| Decision | Why it matters |
|----------|---------------|
| The fetch outcome is only a warning; the `merge-base --is-ancestor` comparison decides the verdict | An offline run still refuses a provably stale base against the last known `origin/<base>`, instead of passing silently because the network failed. |
| Full `git fetch origin`, not a single-refspec fetch | Guarantees `refs/remotes/origin/<base>` is current; a partial refspec would leave the comparison reading a stale tracking ref. |
| The refusal sits in the preflight, after the branch/clean-tree checks and before `load_all`/`create_run` | A refused run leaves no run directory, no `{phase}-{task}` branch and no prompt file behind, matching the two existing refusals. |
| `is_ancestor` returns `bool \| None` and the caller separates behind (`local → remote`), ahead (`remote → local`) and diverged (neither), with `None` warned and never passed as current | A locally rebased base is *diverged* and must refuse, while an ahead base (unpushed commits) must only warn; the tristate keeps "git could not answer" from being mistaken for "not an ancestor". |
| Credential userinfo is stripped from fetch-failure text (`_redact_credentials`) | Warnings/refusals are operator-facing on stderr, are copied into issue reports, and happen before `create_run`, so there is no run log to redact after the fact (design §13). |
| The fetch runs with `GIT_TERMINAL_PROMPT=0` and a 30s timeout that reports as a failed fetch | `git fetch` prompts for credentials and would hang a non-interactive run; the timeout covers a stalled connection without raising. |
| `--no-fetch` is the only bypass and warns; `--dry-run` performs neither fetch nor comparison | The escape hatch is explicit and recorded; dry-run stays hermetic and CI/connectivity-independent. |

**Where it fits in the roadmap:** Phase 02, Epic L1 ("stop the bad seed"). It implements the preflight half of `aidw prompt` that E1.6's post-mortem identified, building on the existing current-branch and clean-tree checks and the resolved `TargetRepo`/`WorkspacePaths` roots from phase 00. It is the slot the rest of L1 builds on: L1.2 (refuse to author when phase predecessors are unticked) and L1.3 (the author's blocked channel) assume a preflight that already owns pre-write refusals. The `[--no-fetch]` usage line and §8.1 sentence are the design surface E3's configurable base branch will extend.

**Scope:** Adds fetch/ancestry primitives to `aidw/git.py`, the `_verify_base_branch` preflight to `aidw/workflows/prompt.py`, the `--no-fetch` CLI option, 13 tests plus helpers in `tests/test_prompt_workflow.py`, and the §8.1/§14 doc lines. It deliberately stops short of L1.2/L1.3, L2.x–L5.x, E2.4/E2.5/E2.6/E2.7, and E3's configurable base branch.

---

## Files Changed

The change set is the working tree relative to `main`. The implementation, tests, design edit and roadmap tick are uncommitted; the task prompt was committed earlier on the branch.

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L1.1-prompt.md` | Created (committed) | The task prompt authored on the branch before implementation. |
| `aidw/git.py` | Modified | Added `fetch(repo, remote="origin", *, timeout=30)` (non-interactive, bounded, returns `(ok, reason)`) and `is_ancestor(repo, ancestor, descendant) -> bool \| None`; `_git_out` gained `timeout`/`env`; credential redaction (`_redact_credentials`, `_failure_reason`); corrected the module docstring's "read helpers never change git state" claim. |
| `aidw/workflows/prompt.py` | Modified | Added `REMOTE`/`EXIT_REFUSED` and `_verify_base_branch` implementing the six outcomes; added the `no_fetch` parameter; refusal placed before config load and `create_run`; dry-run prints the would-fetch note. |
| `aidw/cli.py` | Modified | Added the `--no-fetch` option and threaded it as `no_fetch=` into `prompt_workflow.run`. |
| `tests/test_prompt_workflow.py` | Modified | 13 new tests plus `_origin_and_clone`/`_advance_origin`/`_local_commit`/`_break_origin` helpers, covering all six outcomes, both refusals' messages and pre-write cleanliness, `--no-fetch`, dry-run hermeticity, the non-interactive/bounded spawn and credential redaction. |
| `design.md` | Modified | §8.1 preflight chain updated to "fetch and refuse when the base branch is behind origin" plus one behaviour sentence; §14 `aidw prompt` usage line gained `[--no-fetch]`. |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified | Roadmap escalation: L1.1 checkbox ticked (traceability artifact owned by the implement stage). |

---

## Changes Made

### 1. `aidw/git.py`

- `_git_out` gained `*, timeout` and `*, env`; `subprocess.TimeoutExpired` is caught and reported as `(124, "", "…timed out…")` rather than raised, so a hung git is an ordinary failure.
- `fetch()` copies the environment with `GIT_TERMINAL_PROMPT=0`, runs `git fetch <remote>` bounded by `timeout`, and returns `(False, reason)` on a non-zero exit or timeout. `_failure_reason` takes the first non-empty stderr line, redacted and length-capped.
- `is_ancestor()` wraps `git merge-base --is-ancestor`: `True`/`False`/`None` for yes/no/cannot-answer.
- `_URL_USERINFO` strips `scheme://user:token@` userinfo from any URL in the text (design §13).

### 2. `aidw/workflows/prompt.py`

- `_verify_base_branch(repo, *, no_fetch)` returns `EXIT_REFUSED` or `None`. `--no-fetch` warns and skips both fetch and comparison. Otherwise it fetches `origin`, warns on failure (naming the remote and the failure kind), then compares `repo.base_branch` against `origin/<base>`: equal → silent proceed; local ancestor of remote → refuse naming both shas and `git pull --ff-only`; neither ancestor → refuse naming both shas and telling the operator to reconcile, with no destructive command; remote ancestor of local → warn ahead and proceed; unresolvable ref or `None` ancestry → warn cannot-verify and proceed.
- `run()` calls the check after the branch/clean-tree refusals and before `load_all`/`create_run`. The existing current-branch check is untouched.
- `--dry-run` adds a one-line note that a real run will fetch and verify, and makes no git/network call.

### 3. `aidw/cli.py`

- `--no-fetch` option on the `prompt` command, documented as the offline escape hatch, passed through to `prompt_workflow.run`.

### 4. `tests/test_prompt_workflow.py`

- Helpers build a bare `origin` plus a clone (the phase-entry approach), push new origin commits and make local-only commits to construct behind/ahead/diverged states; `_break_origin` points `origin` at a dead URL carrying userinfo.
- The 13 tests pin the six outcomes, refusal messages (both revisions; `git pull --ff-only` corrective; no destructive command on divergence), no run directory/branch on refusal, `--no-fetch` prompting the warning, dry-run never reaching the network, the child environment and timeout reaching `subprocess.run`, and credential redaction.

### 5. `design.md`

- §8.1 preflight chain and a new sentence; §14 usage line `[--no-fetch]`.

---

## Verification Results

> **Overall gate: ✅ PASS.** `uv run --frozen pytest` produced **`582 passed in 50.66s`**; install, build, doctor, agent validation and prompts check all passed. No gate was re-run for a count; every row below is from the single invocation named in its row.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Exit 0 — `Checked 15 packages in 0.82ms` (gate `install`, tree `9fa3af434413`, stage `record-implementation-results`, 2026-10-26T10:39:57Z) |
| Build | `uv build --out-dir /tmp/aidt-l11-build.7YtGH6` | ✅ Exit 0 — built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` (gate `build`, tree `9fa3af434413`, 2026-10-26T10:40:00Z) |
| Test | `uv run --frozen pytest` | ✅ Exit 0 — **`582 passed in 50.66s`** (gate `suite`, tree `9fa3af434413`, 2026-10-26T10:39:07Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)` (gate `doctor`, tree `9fa3af434413`, 2026-10-26T10:39:17Z). The 2 warnings are advisories; 0 checks failed |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `9fa3af434413`, 2026-10-26T10:39:18Z) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `9fa3af434413`, 2026-10-26T10:39:18Z) |
| Whitespace | `git diff --check` | ✅ Exit 0 — no whitespace errors |

### `uv run --frozen pytest` (full suite)

Single invocation: **`582 passed in 50.66s`** (exit 0, gate `suite`). The subsets below are part of that same run; no second run was made.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 582 | ✅ Pass (`582 passed in 50.66s`) |
| `tests/test_prompt_workflow.py` (within the full suite) | 31 | ✅ Pass (31 of the 582) |
| L1.1 tests added in this task (within the full suite) | 13 | ✅ Pass (13 of the 582) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Behind base refuses with `EXIT_REFUSED` before anything is written | ✅ Covered by `test_preflight_behind_refuses_before_writing` (both revisions named, `git pull --ff-only` corrective, no run directory, no branch) |
| Diverged base refuses with `EXIT_REFUSED` and no destructive suggestion | ✅ Covered by `test_preflight_diverged_refuses_without_a_destructive_command` |
| Equal revisions proceed silently | ✅ Covered by `test_preflight_equal_base_proceeds_silently` |
| Ahead base (unpushed commits) warns and proceeds | ✅ Covered by `test_preflight_ahead_warns_and_proceeds` |
| Missing `origin` warns cannot-verify and proceeds | ✅ Covered by `test_preflight_without_origin_warns_and_proceeds`; the existing remote-less workflow tests also pass unchanged |
| Failed fetch warns, then the stale comparison still refuses | ✅ Covered by `test_preflight_stale_cache_still_refuses_when_fetch_fails` |
| `--no-fetch` warns and skips the check (separate from the gate) | ✅ Covered by `test_no_fetch_warns_and_skips_the_stale_check` |
| `--dry-run` never reaches the network | ✅ Covered by `test_dry_run_never_fetches_with_an_unreachable_origin` (spies on `fetch`/`rev_parse`; returns 0, prints the would-fetch note) |
| Non-interactive environment and timeout reach the fetch | ✅ Covered by `test_fetch_is_noninteractive_and_bounded`, `test_fetch_default_timeout_is_thirty_seconds`, `test_fetch_timeout_counts_as_failure` |
| `is_ancestor` tristate | ✅ Covered by `test_is_ancestor_is_tristate` |
| Credential-bearing remote URL redacted in the warning | ✅ Covered by `test_preflight_fetch_warning_redacts_credentials` |

---

## Deviations observed during recording

- **First suite invocation leaked the recording identity.** The first `aidw gate run suite -- uv run --frozen pytest` (no env scrubbing) recorded `2 failed, 580 passed in 48.58s` (tree `9fa3af434413`, 2026-10-26T10:38:02Z): the recorder's inherited `AIDW_STAGE`/`AIDW_RUN_ID` reached the child test process, so `test_cli_gate_run_records_into_the_branch_run_without_an_env_identity` expected stage `cli` but saw `record-implementation-results`, and `test_cli_gate_run_propagates_a_failing_exit_code` exited 2 on the unknown run. The change set was not implicated; re-running the same gate command with `env -u AIDW_RUN_ID -u AIDW_STAGE` for the child — matching CI and the E2.2 recording — passed `582 passed`. No implementation or test file was modified. The failed outcome remains in the run's state.
- **Every gate emitted the new single-checkout warning.** This toolkit checkout is itself a single working tree, so `_roots` printed the §3.10 advisory before each gate. That is the intended new warning, not a gate failure.
- **Roadmap checkbox is ticked.** Unlike the E2.2 recording, `docs/tasks/02 - Prompt loop integrity.md` already carries `[x] **L1.1…**` from the implement stage; this stage wrote neither the tick nor any other traceability file.
- **Generic template is pnpm/srd-shaped; this repo is uv-based.** There is no `package.json`, `pnpm-workspace.yaml`, `srd:*` script or `infra` CDK project, so no `pnpm`/`srd:*`/`cdk` gate applies. The repo's own gates from `AGENTS.md` were run instead, each through `aidw gate run` under the `pr.md` scope (`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`).

---

## Non-Goals (NOT implemented)

- ❌ L1.2 (refuse to author when the phase's predecessors are unticked) and L1.3 (the author's blocked channel) — separate tasks in this phase (task prompt, Explicit non-goals)
- ❌ L2.x reviewer authority, L3.x fixer integrity, L4.x loop termination, L5.x author quality — separate tasks (task prompt, Explicit non-goals)
- ❌ E2.5's control-worktree preflight, E2.4's branch-setup stage, E2.6/E2.7 worktree resolution and locking — the current-branch check is left alone (task prompt, Explicit non-goals)
- ❌ E3's config resolution — `TargetRepo.base_branch` is read as it stands (default `main`); no config key and no `--base-branch` flag (task prompt, Explicit non-goals)
- ❌ No change to the stage chain, `MAX_REVISIONS`, the review/fix loop, the gates, or `TargetRepo`/`WorkspacePaths` resolution (task prompt, Explicit non-goals)
- ❌ No commit, push or pull request — `aidt/prompts/pr.md` owns delivery; the implementation, tests, design edit and roadmap tick remain uncommitted
