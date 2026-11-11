# Build Results — 03-H3.3: Give `fix` the same tick, once its loop converges

**Branch:** `03-H3.3`
**Date:** 2026-11-10
**Spec:** `design.md` §8.4 (`aidw fix --pr <n>` and the post-loop tick), §8.2 (I7 `update-roadmap` shared with `fix`), §8.6 (`aidw run` and chain-level exactly-once), §9.2 (`state.json` `state.task`/`state.pr` fields), §15 (testing strategy), §17 (decision row `Z2`); roadmap entry H3.3 in `docs/tasks/03 - Stage resilience.md`; `docs/task-prompts/03-H3.3-prompt.md`

## Summary

**Purpose:** Make `aidw fix` tick the task's roadmap checkbox once its review loop converges, using the same shared `I7 update-roadmap` stage `implement` uses, so a closed task is no longer left unticked after a `prompt-to-fix` chain.

| Decision | Why it matters |
|----------|---------------|
| `I7` is one module-level `StageDefinition` shared by `implement.stages` and a new `fix.post_loop` half | One id, prompt, agent, name and variable set means the two workflows' ticks cannot drift (the `A1` precedent). |
| `post_loop` is emitted only on request (`include_post_loop`) | `expand("fix", …)` is the per-iteration expansion; emitting the tick unconditionally would plan and dry-run print it once per iteration instead of once per run. |
| `fix`'s green rule is its own three-part condition, not `implement`'s gate-outcome rule | Green iff `select` returned `EXIT_NONE_AVAILABLE`, every `iter{N}-test` record is `SUCCEEDED`, and `latest_verdict == Approve`; an empty run is not green. |
| Declared stage lists are classified three ways (static / loop / post-loop), with `fix`'s `I7` treated as core | A declared `workflows.fix.stages: [A1, I7]` must be accepted, `I7`'s removal/disable/reorder must be refused, and `I7` must not be mistaken for a loop id. |
| Task id comes from the newest `implement` run's `state.task`, falling back to an exhaustive branch-pattern reversal | Never a `gh` query or PR title; zero or several viable splits/entries skip with a reason and exit 0 so `fix` keeps working on non-AIDT PRs. |
| Green reuses `implement.settle_roadmap_tick`; non-green uses `record_skipped` | The byte-exact flip rule is not duplicated, and a withheld tick leaves the roadmap byte-identical while recording why. |

**Where it fits in the roadmap:** Phase 3 (Stage resilience), task H3.3. It depends on H3.1's `I7 update-roadmap` stage and H3.2's carried `WHEN_EVIDENCE_GREEN` condition, and on H0.1/E4.8's recorded gate-outcome infrastructure for the `implement` side. It completes the phase's `fix`-side tick work; phase 02's convergence rules and E4.8's gate scope are unchanged.

**Scope:** `aidw/stage_registry.py` (`post_loop`, shared `I7`, three-way classification, `expand(include_post_loop=…)`), `aidw/runner.py` (`plan_stages` post-loop expansion, `declared_stage_issues`, `_warn_deferred_settings`), `aidw/workflows/fix.py` (target resolution, green helper, skip/tick recording, dry-run plan), `aidw/workflows/implement.py` (public `settle_roadmap_tick`), `design.md` §§8.2/8.4/8.6/17 (`Z2`), and the four affected test modules. It deliberately stops short of changing `implement`'s gate-outcome rule, adding a new stage/prompt/agent, altering convergence rules or gate scope, and moving the tick to a merge.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/03-H3.3-prompt.md` | Created | The task prompt for this task (committed earlier on this branch). |
| `aidw/stage_registry.py` | Modified | Adds `WorkflowDefinition.post_loop`, the shared module-level `I7` stage, post-loop enumeration in `stage`/`stages_by_id`/`validate_stage_list`, three-way classification, and `expand(include_post_loop=…)`. |
| `aidw/runner.py` | Modified | `plan_stages` splits static/loop/post-loop three ways and emits the post-loop half only on request; `declared_stage_issues` and `_warn_deferred_settings` include the post-loop half. |
| `aidw/workflows/fix.py` | Modified | Resolves the task from the newest `implement` run or branch reversal, evaluates fix's three-part green rule, records skip/tick outcomes, and plans the tick once after the loop and in `--dry-run`. |
| `aidw/workflows/implement.py` | Modified | Makes `settle_roadmap_tick` public while retaining the old private alias, so `fix` reuses the one flip rule. |
| `design.md` | Modified | Documents the shared tick in §8.2, the post-loop tick and fix's green rule in §8.4, chain-level exactly-once in §8.6, and decision row `Z2` in §17. |
| `tests/test_stage_registry.py` | Modified | Pins `post_loop`, request-only expansion, the shared `I7` object, and core classification of `fix`'s `I7`. |
| `tests/test_fix_workflow.py` | Modified | Covers green tick once, stopped/empty runs skipping with reasons, no-roadmap-entry exit 0, newest-run task resolution and branch-pattern fallbacks. |
| `tests/test_plan_stages.py` | Modified | Re-baselines the fix plan, covers the three-way split and declared `[A1, I7]` acceptance/reorder/removal cases. |
| `tests/test_run_workflow.py` | Modified | Pins a whole `prompt-to-fix` chain ticking the roadmap exactly once whether `implement` or `fix` flipped it. |

---

## Verification Results

### Top-level verification

Commands are this repo's own, taken from its root `AGENTS.md` ("Gates — run exactly these, and only these"). There is no `aidw/conventions.md` in this target repo and no lint/formatter/type-checker is configured (AGENTS.md "Tests"; design §15). Gate commands ran through `aidw gate run <key>` with the workflow's declared ignore scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`. All gates below were re-run against the committed tree by the review-follow-up fix for issue #151 (the record stage's original `suite` outcome was a stale red — see Deviations).

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 1ms`) |
| Build | `uv build --out-dir <tmp>/dist` (gate `build`) | ✅ Pass — built `aidt-1.1.1.tar.gz` and `aidt-1.1.1-py3-none-any.whl` |
| Test | `uv run --frozen pytest` (gate `suite`) | ✅ Pass (`2036 passed in 42.18s`) |
| Doctor | `uv run --frozen aidw doctor` (gate `doctor`) | ✅ Pass (`21 checks: 0 failed, 1 warning(s)`) |
| Agents validate | `uv run --frozen aidw agents validate --strict` (gate `agents`) | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` (gate `prompts`) | ✅ Pass (`resolved repo prompts: 0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (exit 0, no output) |
| Lint | — | n/a — this repo configures no linter (AGENTS.md: "pytest is the only verification") |

Gate origins for the rows above (re-recorded by the review-follow-up fix for issue #151, tree `962a6da23ca0`, scope excludes `docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks`):

- `build` — passed at `2026-11-10T23:02:31Z`, stage `iter1-fix-next-review-followup`.
- `suite` — passed at `2026-11-10T23:03:18Z`, stage `iter1-fix-next-review-followup` (`2036 passed in 42.18s`).
- `doctor` — passed at `2026-11-10T23:03:24Z`, stage `iter1-fix-next-review-followup`.
- `agents` — passed at `2026-11-10T23:03:24Z`, stage `iter1-fix-next-review-followup`.
- `prompts` — passed at `2026-11-10T23:03:25Z`, stage `iter1-fix-next-review-followup`.
- `smoke` — passed at `2026-11-10T23:03:38Z`, stage `iter1-fix-next-review-followup` (`tests/test_fix_workflow.py::test_a_newest_implement_run_without_task_falls_back_to_the_branch_pattern`: `1 passed in 8.06s`).

### `uv run --frozen pytest` (full suite)

The full-suite row is derived from the single full-gate invocation above; no second suite run was bought for this document. The focused row cites the recorded `smoke` gate (a single-test invocation).

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2036 | ✅ Pass (`2036 passed in 42.18s`) |
| `tests/test_fix_workflow.py::test_a_newest_implement_run_without_task_falls_back_to_the_branch_pattern` | 1 | ✅ Pass (`1 passed in 8.06s`, gate `smoke`) — the newest `implement` run has `task={}`, and `resolve_roadmap_target` falls back to the `03-H3.3` branch pattern and resolves the roadmap entry (`roadmap_file` set, `("03", "H3.3")`) instead of keeping the older run's `H3.1` task. |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `tests/test_stage_registry.py`: `post_loop` exists, `expand("fix", …)` emits the shared `I7` only on request, shared object identity, `stage`/`stages_by_id` find the post-loop id, `validate_stage_list("fix", …)` classifies `I7` as core | ✅ Pass — no failures from this module appear in the single run's failure list (`2036 passed` overall) |
| `tests/test_fix_workflow.py`: green tick once, `roadmap_ticked`, once-per-run records, stopped/empty runs skip with reasons, no-roadmap-entry exits 0, branch-pattern reversal on non-default and ambiguous patterns | ✅ Pass — no failures from this module appear in the single run's failure list (`2036 passed` overall) |
| `tests/test_plan_stages.py`: re-baselined fix plan, three-way split, declared `[A1, I7]` acceptance, missing/reordered `I7` refusal | ✅ Pass — no failures from this module appear in the single run's failure list |
| `tests/test_run_workflow.py`: `prompt-to-fix` chain leaves the roadmap entry `[x]` exactly once | ✅ Pass — no failures from this module appear in the single run's failure list |
| `aidw fix --pr <n> --dry-run` plans `update-roadmap` once in final position without evaluating evidence | ✅ Pass — hand-run as `uv run --frozen aidw fix --pr 149 --dry-run` (exit 0) in a clean clone of the committed tree, because the active fix run holds this worktree's one-run lock: it resolved `branch: 03-H3.3`, planned the loop stages, printed `update-roadmap [succeeded] (planned) agent=recorder (after the loop, only when this run's evidence is green)` exactly once, in the final position, and ended `dry-run complete; Pi not invoked, no GitHub state written` — no evidence evaluated, no tick. |

---

## Deviations observed during recording

- **The record stage's `suite` outcome was a stale red** — the original recording measured `uv run --frozen pytest` before the task-id fallback was corrected during development (`1 failed, 2035 passed`, tree `40412cf9e573`) and described a live product gap in `fix`'s task-id fallback. On the committed tree that gap does not exist: `_recorded_task_identity` falls through to the branch-pattern resolver when the newest `implement` run has no usable `state.task`, the named test passes, and the full suite is `2036 passed` (tree `962a6da23ca0`). Found in review (issue #151); every gate above was re-run against the committed tree and this document now records the real green outcomes.
- **Roadmap entry remains `- [ ]`** — this recording stage only writes its results document; ticking the roadmap belongs to the update-roadmap stage.

---

## Non-Goals (NOT implemented)

- ❌ H3.2's implement-side gate-outcome rule is separate and unchanged; `fix`'s green is its own three conditions, not a copy of `implement.tick_evidence` (task prompt, "Explicit non-goals").
- ❌ Do not add a new stage id, prompt, or agent — reuse `I7` / `prompts/update-roadmap.md` / `recorder` (task prompt, "Explicit non-goals").
- ❌ Phase 02's convergence rules, which stages gate, and E4.8's gate scope are unchanged (task prompt, "Explicit non-goals").
- ❌ "Move the tick to the merge" is not done — AIDT never merges (design §13; task prompt, "Explicit non-goals").
- ❌ Do not write `player-actions.md` or `integration-tests.md` — the `show-updated-*` prompts own those documents.
- ❌ No commit, push, or pull request from this stage — `/pr` owns delivery.
