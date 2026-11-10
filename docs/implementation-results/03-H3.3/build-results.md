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

Commands are this repo's own, taken from its root `AGENTS.md` ("Gates — run exactly these, and only these"). There is no `aidw/conventions.md` in this target repo and no lint/formatter/type-checker is configured (AGENTS.md "Tests"; design §15). Gate commands ran through `aidw gate run <key>` with the workflow's declared ignore scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.62ms`) |
| Build | `uv build --out-dir <tmp>/dist` (gate `build`) | ✅ Pass — built `aidt-1.1.1.tar.gz` and `aidt-1.1.1-py3-none-any.whl` |
| Test | `uv run --frozen pytest` (gate `suite`) | ❌ Fail (`1 failed, 2035 passed in 46.91s`; failing test `tests/test_fix_workflow.py::test_a_newest_implement_run_without_task_falls_back_to_the_branch_pattern`) |
| Doctor | `uv run --frozen aidw doctor` (gate `doctor`) | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`) |
| Agents validate | `uv run --frozen aidw agents validate --strict` (gate `agents`) | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` (gate `prompts`) | ✅ Pass (`resolved repo prompts: 0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (exit 0, no output) |
| Lint | — | n/a — this repo configures no linter (AGENTS.md: "pytest is the only verification") |

Gate origins for the rows above (recorded by this run, tree `40412cf9e573`, scope excludes `docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks`):

- `build` — passed at `2026-11-10T22:44:08Z`, stage `record-implementation-results`.
- `suite` — **failed** at `2026-11-10T22:44:58Z`, stage `record-implementation-results` (`1 failed, 2035 passed in 46.91s`).
- `doctor` — passed at `2026-11-10T22:45:02Z`, stage `record-implementation-results`.
- `agents` — passed at `2026-11-10T22:45:02Z`, stage `record-implementation-results`.
- `prompts` — passed at `2026-11-10T22:45:03Z`, stage `record-implementation-results`.

### `uv run --frozen pytest` (full suite)

Rows are derived from the single full-gate invocation above; no second run was bought for this document.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2036 | ❌ Fail (`1 failed, 2035 passed in 46.91s`) |
| `tests/test_fix_workflow.py::test_a_newest_implement_run_without_task_falls_back_to_the_branch_pattern` | 1 | ❌ Fail — the newest `implement` run has `task={}`, but `resolve_roadmap_target` returned the older run's `H3.1` target (`roadmap_file=None`, reason "no roadmap entry matches 03-H3.1") instead of falling back to the `03-H3.3` branch and resolving the roadmap entry. |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `tests/test_stage_registry.py`: `post_loop` exists, `expand("fix", …)` emits the shared `I7` only on request, shared object identity, `stage`/`stages_by_id` find the post-loop id, `validate_stage_list("fix", …)` classifies `I7` as core | ✅ Pass — no failures from this module appear in the single run's failure list (`2035 passed` overall) |
| `tests/test_fix_workflow.py`: green tick once, `roadmap_ticked`, once-per-run records, stopped/empty runs skip with reasons, no-roadmap-entry exits 0, branch-pattern reversal on non-default and ambiguous patterns | ❌ Fail — one test (`test_a_newest_implement_run_without_task_falls_back_to_the_branch_pattern`) failed; the remaining tests in the module passed. |
| `tests/test_plan_stages.py`: re-baselined fix plan, three-way split, declared `[A1, I7]` acceptance, missing/reordered `I7` refusal | ✅ Pass — no failures from this module appear in the single run's failure list |
| `tests/test_run_workflow.py`: `prompt-to-fix` chain leaves the roadmap entry `[x]` exactly once | ✅ Pass — no failures from this module appear in the single run's failure list |
| `aidw fix --pr <n> --dry-run` plans `update-roadmap` once in final position without evaluating evidence | ❌ **unverified** — no real PR/branch context and live `gh` workflow state were available in this recording session; the plan-level assertion is covered by the stage-registry/fix workflow tests, but the hand-run CLI check itself was not executed. |

---

## Deviations observed during recording

- **The `suite` gate is red** — `uv run --frozen pytest` produced `1 failed, 2035 passed in 46.91s`. The failure is recorded here rather than fixed, because this stage does not change implementation code or tests. It is a real product gap in `fix`'s task-id fallback: when the newest `implement` run exists but has no usable `state.task`, the resolver kept the older run's task instead of reversing the branch pattern.
- **`--dry-run` was not hand-run** — the check needs a real PR number and `gh` state, so it is marked unverified rather than simulated.
- **Roadmap entry remains `- [ ]`** — this recording stage only writes its results document; ticking the roadmap belongs to the update-roadmap stage.

---

## Non-Goals (NOT implemented)

- ❌ H3.2's implement-side gate-outcome rule is separate and unchanged; `fix`'s green is its own three conditions, not a copy of `implement.tick_evidence` (task prompt, "Explicit non-goals").
- ❌ Do not add a new stage id, prompt, or agent — reuse `I7` / `prompts/update-roadmap.md` / `recorder` (task prompt, "Explicit non-goals").
- ❌ Phase 02's convergence rules, which stages gate, and E4.8's gate scope are unchanged (task prompt, "Explicit non-goals").
- ❌ "Move the tick to the merge" is not done — AIDT never merges (design §13; task prompt, "Explicit non-goals").
- ❌ Do not write `player-actions.md` or `integration-tests.md` — the `show-updated-*` prompts own those documents.
- ❌ No commit, push, or pull request from this stage — `/pr` owns delivery.
