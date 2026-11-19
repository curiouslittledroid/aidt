# Build Results — 05-P1.1: Add a commit-and-push stage to `aidw fix`

**Branch:** `05-P1.1`
**Date:** 2026-11-19
**Spec:** `design.md` §8.4 (`aidw fix --pr <n>`), §13 (Git and GitHub safety), §17 (`Z9`), §18 (risk table); roadmap entry P1.1 in `docs/tasks/05 - Pipeline efficiency.md`; `docs/task-prompts/05-P1.1-prompt.md`; `docs/workflow-stages.md`
**Pull request:** #158 — https://github.com/curiouslittledroid/aidt/pull/158

## Summary

**Purpose:** Add the core post-loop stage `F5 commit-and-push` to `aidw fix`, so a converged run commits the fixes and roadmap tick it accumulated and pushes them to the PR-head branch instead of closing issues while leaving its work in the worktree.

| Decision | Why it matters |
|----------|---------------|
| `F5` rides `_FIX.post_loop` after `I7` and is core, with no `when=` token | Its trigger is loop convergence, not green evidence: a converged run whose tick was withheld, or whose roadmap target is unresolvable, still has real fix edits that must land. Being core keeps removal, disable and reorder rules applying, so a declared `workflows.fix.stages` list becomes `[A1, I7, F5]`. |
| The workflow decides among four cases before the stage runs | Dirty tree with at least one issue closed this run commits and pushes; dirty with none, and clean with none, are recorded skips with reasons and exit 0; clean with closed issues fails closed. Unowned dirt is never committed, and an empty run creates no empty commit. |
| The `pr-publisher` agent writes; Python verifies | The agent runs `git add -A`, `git commit` and `git push origin <branch>`; the workflow refuses a base-branch head before any push, then compares `HEAD` with `origin/<branch>` and records `state.pr["head_sha"]` only when they match. A stage record alone is not evidence the write happened. |
| `state.pr` uses exactly two new outcomes | `head_sha` (the verified remote SHA) or `commit_skip_reason`, mirroring `roadmap_tick_skip_reason`; a skip's `StageRecord` carries `SKIP_REASON_KEY`. No `committed`/`pushed` boolean is added. |
| The `pr-publisher` hard rules are scoped by prompt | `/pr` still owns PR creation and the build-results backfill; `/fix-commit` commits and pushes only. Fixing the agent file, not just the prompt, removes the contradiction at its source without changing the agent id, config or allowlist. |

**Where it fits in the roadmap:** Phase 05 ("Pipeline efficiency"), epic P1 ("A fix closes its issues only after the push"), task P1.1. It builds directly on H3.3's shared `I7 update-roadmap` post-loop stage (`Z2`) and on `Z7`'s rule that a tick must agree with the recorded Done-when verdict. It resolves the §18 risk row "The fix-loop prompts leave their changes uncommitted" and records the reversal as decision `Z9`. P1.2 (close a follow-up issue only after its fix is pushed) depends on this stage existing, and B1.1 (batch fixes) is later work that will reuse the same boundary.

**Scope:** `aidw/stage_registry.py` (the `F5` definition, `_FIX.post_loop`, `STAGE_IDS` and classification documentation), `aidw/workflows/fix.py` (post-loop planning, the four-case decision, branch refusal, push verification and `state.pr` recording), the new `prompts/fix-commit.md`, `agents/pr-publisher/AGENTS.md` (the per-prompt carve-out), `aidw/inventory.py`, `aidw/runner.py` documentation, `design.md` §§8.4/13/17/18, `README.md`, `docs/workflow-stages.md`, `docs/migration/prompt-classification.md`, the roadmap checkbox, and the six named test files plus the prompt-classification drift test. It deliberately stops short of moving the `Status: fixed` close out of `F1`, editing `prompts/fix-next-review-followup.md` or `review_followup.py`, adding an agent id or allowlist entry, creating a PR or backfilling build results from `fix`, and starting Q1.1 or B1.1.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `prompts/fix-commit.md` | Created | The `F5` prompt: commit and push only, on the PR-head branch, with a base-branch refusal and no PR creation or build-results edit. |
| `docs/task-prompts/05-P1.1-prompt.md` | Created | The task prompt recording decisions D1–D11, requirements, tests, deliverables and explicit non-goals. |
| `README.md` | Modified | Documents `I7` and `F5` in the `aidw fix` block and replaces the "fix stages leave their changes uncommitted" paragraph with the publish/skip/fail contract. |
| `agents/pr-publisher/AGENTS.md` | Modified | Scopes the hard rules by prompt: `/pr` opens and backfills; `/fix-commit` commits and pushes only, with the base-branch refusal and no-issue skip rule. |
| `aidw/inventory.py` | Modified | Adds `fix-commit.md` to `REQUIRED_PROMPTS`, so a rename fails loudly at `prompts check`. |
| `aidw/runner.py` | Modified | Updates the canonical declared stage list in the `declared_stage_issues` documentation to `[A1, I7, F5]`. |
| `aidw/stage_registry.py` | Modified | Adds `_COMMIT_PUSH_STAGE` (`F5`, `commit-and-push`, `pr-publisher`, `fix-commit.md`, `{pr}`) after `I7` in `_FIX.post_loop`, adds `F5` to `STAGE_IDS`, and updates the core/classification documentation. |
| `aidw/workflows/fix.py` | Modified | Plans both post-loop stages once per run, implements the four-case commit decision, refuses a base-branch head, verifies `HEAD` against `origin/<branch>`, records `head_sha`/`commit_skip_reason`, and records F5's skip on every stopped-loop path. |
| `design.md` | Modified | Reverses the uncommitted-fix boundary in §8.4 and §13, adds decision row `Z9` in §17, and marks the §18 risk resolved with the F5 boundary. |
| `docs/migration/prompt-classification.md` | Modified | Adds `fix-commit.md` to post-cutover class (iv) and raises the toolkit prompt count to 18. |
| `docs/tasks/05 - Pipeline efficiency.md` | Modified | Ticks the P1.1 roadmap checkbox on its single entry. |
| `docs/workflow-stages.md` | Modified | Adds `F5` to the id vocabulary and fix inventory, extends the fix diagram, and reverses the "No stage of `fix` commits" line. |
| `tests/test_design_doc.py` | Modified | Pins the §8.4 reversal, §13's two documented `git add -A` owners, one `Z9` row, and the resolved §18 row. |
| `tests/test_fix_workflow.py` | Modified | Replaces the "leaves the roadmap edit uncommitted" test with D3's four cases and covers push mismatch, unresolvable refs, stage failure, dirty tree, base-branch refusal, stopped-loop skips, a failed tick, and the pure decision function. |
| `tests/test_inventory.py` | Modified | Pins `fix-commit.md` in `REQUIRED_PROMPTS`, proves the prompt has no `gh pr create` or build-results backfill, and checks the agent file's per-prompt carve-out. |
| `tests/test_plan_stages.py` | Modified | Re-baselines fix plans and declared lists to `[A1, I7, F5]`, including missing/disabled/reordered `F5` and dry-run planning exactly once. |
| `tests/test_prompt_classification.py` | Modified | Re-baselines the post-cutover prompt set and toolkit prompt count for `fix-commit.md`. |
| `tests/test_stage_registry.py` | Modified | Pins `post_loop == (I7, F5)`, `expand(..., include_post_loop=True)` ending `[..., I7, F5]`, `validate_stage_list("fix", [A1, I7, F5]) == []`, the classification errors, and unchanged `REPO_OPTIONAL_IDS`. |
| `tests/test_workflow_stages_doc.py` | Modified | Pins the drift-checked fix inventory row carrying `F5` after `I7`. |

---

## Verification Results

Commands are this repo's own, taken from its root `AGENTS.md` ("Gates — run exactly these, and only these"). There is no `aidw/conventions.md` in this target repo and no lint/formatter/type-checker is configured (AGENTS.md "Tests"; design §15), so the lint row is `n/a`. The build and suite gates ran through `aidw gate run <key>` with the workflow's declared scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.45ms`) |
| Lint | — | n/a — this repo configures no linter (AGENTS.md: "pytest is the only verification") |
| Build | `uv build --out-dir <mktemp dir>` (gate `build`) | ✅ Pass — built `aidt-1.5.0.tar.gz` and `aidt-1.5.0-py3-none-any.whl` |
| Test | `uv run --frozen pytest` (gate `suite`) | ✅ Pass (`2151 passed in 44.88s`) — reused from this run's earlier `update-traceability` stage against the same tree and scope |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`) — warnings are the dirty working tree and the missing `.mcp.json` |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (`resolved repo prompts: 0 error(s), 0 warning(s)`; `fix-commit.md` resolves to the toolkit default) |
| Whitespace | `git diff --check` | ✅ Pass (exit 0, no output) |
| Task dry-run | `AIDW_STATE_DIR=<temporary-state-dir> uv run --frozen aidw fix --pr 156 --dry-run` | ✅ Pass — prints `update-roadmap [skipped]` followed by `commit-and-push [succeeded] (planned)` exactly once after it, then `dry-run complete; Pi not invoked, no GitHub state written` |

Gate origins for the rows above (tree `f69cd588e533`, scope excludes `docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks`):

- `build` — passed at `2026-11-19T05:15:01Z`, stage `record-implementation-results` (`Successfully built …/aidt-1.5.0-py3-none-any.whl`).
- `suite` — passed at `2026-11-19T05:12:09Z`, stage `update-traceability` (`2151 passed in 44.88s`), reused by this stage against the same tree and scope. No second suite was run for this document.
- `dry-run` — this stage observed the command directly with an isolated temporary state directory; because that isolated directory has no run record, `aidw gate` reported `gate 'dry-run' passed` but `note: no run to record into`, so the row cites the command observation, not a recorded gate origin.

### `uv run --frozen pytest` (full suite)

The full-suite row is the reused gate above; the focused row is this run's earlier `test` stage, also against tree `f69cd588e533`, and was not re-run for this document.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2151 | ✅ Pass (`2151 passed in 44.88s`, gate `suite`, stage `update-traceability`) |
| `tests/test_fix_workflow.py tests/test_stage_registry.py tests/test_plan_stages.py tests/test_inventory.py tests/test_design_doc.py tests/test_workflow_stages_doc.py` | 284 | ✅ Pass (`284 passed in 17.21s`, gate `suite`, stage `test`) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| D3 case 1 — a converged run that closed an issue commits the fix and the flipped tick, records the verified remote `head_sha`, ends clean and exits 0 | ✅ Pass — covered by `tests/test_fix_workflow.py` in the focused run |
| D3 cases 2 and 3 — dirty-with-nothing-closed and clean-with-nothing-closed are recorded skips with `commit_skip_reason`, no commit object and exit 0 | ✅ Pass — covered by `tests/test_fix_workflow.py` |
| D3 case 4 — closed issues with a clean tree exits non-zero, names the PR and branch, and leaves `head_sha` absent | ✅ Pass — covered by `tests/test_fix_workflow.py` |
| D6 — a push that did not land, an unresolvable pushed ref, a non-`SUCCEEDED` stage and a tree left dirty all fail closed naming the PR and branch | ✅ Pass — covered by `tests/test_fix_workflow.py` |
| D5 — a PR head that resolves to the base branch is refused before any push | ✅ Pass — covered by `tests/test_fix_workflow.py` |
| D4 — a stopped loop records F5's skip with the same reason as I7's; a failed I7 leaves no F5 record and keeps exit 1 | ✅ Pass — covered by `tests/test_fix_workflow.py` |
| Registry purity — `post_loop == (I7, F5)`, expansion ends `[..., I7, F5]`, `[A1, I7, F5]` validates, missing/disabled/reordered F5 errors, `REPO_OPTIONAL_IDS` unchanged | ✅ Pass — covered by `tests/test_stage_registry.py` |
| Dry-run — `commit-and-push [planned]` appears exactly once after `update-roadmap`, with no evidence evaluated | ✅ Pass — the direct dry-run command above, including an unresolvable roadmap target |
| Doc/inventory drift — fix inventory carries F5 after I7, design §8.4/§13 are reversed, one Z9 row exists, §18 is no longer contradictory, `fix-commit.md` is required | ✅ Pass — covered by `tests/test_workflow_stages_doc.py`, `tests/test_design_doc.py`, `tests/test_inventory.py` and `tests/test_prompt_classification.py` |
| Prompt/agent contract — `fix-commit.md` contains no `gh pr create` or build-results backfill, and `agents/pr-publisher/AGENTS.md` carries the `/fix-commit` carve-out | ✅ Pass — covered by `tests/test_inventory.py` |
| `uv run --frozen aidw prompts check` exits 0 with `fix-commit.md` present and self-contained | ✅ Pass — `resolved repo prompts: 0 error(s), 0 warning(s)` |
| `uv run --frozen aidw agents validate --strict` exits 0 after the AGENTS.md carve-out | ✅ Pass — `11 agent config(s): 0 error(s), 0 warning(s)` |

---

## Deviations observed during recording

- **The task dry-run used PR #156 as a stand-in** — `05-P1.1` has no pull request yet, so `--pr <this branch>` could not be used. The command was run with an isolated temporary `AIDW_STATE_DIR` and merged PR #156; it resolved that PR's head branch and, because no worktree existed for it, planned against this control root. This proves the F5 plan position generically (F5 prints once, after the update-roadmap skip) but does not exercise this branch's own PR, which does not exist. No implementation, test or traceability file was changed; the temporary state directory was outside the repository.
- **The suite was reused rather than re-bought** — the `update-traceability` stage of this same run had already passed `uv run --frozen pytest` on tree `f69cd588e533` with the same scope, and the `build` gate in this stage confirmed the tree was unchanged. This document cites that recorded outcome as required rather than running the suite a second time.
- **No pull request exists** — the read-only `gh pr view 05-P1.1` lookup returned no PR. The document records the required not-yet-opened note; `/pr` will replace it with the real number after creating the pull request.
- **`aidw doctor` reports two warnings, not one** — the dirty working tree and missing `.mcp.json` are both expected while this results document and the implementation remain uncommitted; `0 checks failed`.

---

## Non-Goals (NOT implemented)

- ❌ P1.2 (close a follow-up issue only after its fix is pushed) — the `Status: fixed` close stays in `F1`; `prompts/fix-next-review-followup.md` and `review_followup.py` are untouched (task prompt, "Explicit non-goals").
- ❌ No new agent id, no `agent-configs/pr-publisher.yaml` change and no allowlist change — the existing `pr-publisher` is reused, with only its `AGENTS.md` content carved out (task prompt, "Explicit non-goals").
- ❌ No PR creation and no build-results backfill in `fix` — those remain `I6`/`pr.md`'s job (task prompt, "Explicit non-goals").
- ❌ Q1.1 (withhold the implement PR on tester `Fail`) and B1.1 (batch fixes) are not started (task prompt, "Explicit non-goals").
- ❌ No commit, push or pull request from this record stage — delivery belongs to `/pr` (record stage instruction).
