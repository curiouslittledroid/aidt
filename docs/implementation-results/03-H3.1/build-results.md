# Build Results — 03-H3.1: Give the roadmap tick its own stage

**Branch:** `03-H3.1`
**Date:** 2026-11-10
**Spec:** `design.md` §8.2 (`aidw implement`, I1–I6 chain and the I6 commit), §15 (testing strategy), §17 (resolved decisions); `docs/migration/EXTRACTION.md` §3.5 (stage and workflow model); roadmap entry H3.1 in `docs/tasks/03 - Stage resilience.md`

## Summary

**Purpose:** Move the roadmap checkbox flip out of the repo-optional `I3 update-traceability` stage and into its own core `I7 update-roadmap` stage, so every repo ticks its roadmap entry whether or not it has the SRD-specific traceability artifacts, and so the tick is verified by Python rather than trusted from an agent's exit code.

| Decision | Why it matters |
|----------|---------------|
| `I7` is a **core** stage between `I5` and the approval gate/`I6`, not a repo-optional one | `I3`'s `enabled: false` silently dropped the tick, and repos without `docs/rules-coverage/` ran a stage that owned nothing; a tick every repo needs cannot live behind a repo-optional switch (D13: `REPO_OPTIONAL_IDS` stays `{I3, I4}`). Placement before `I6` is what puts the tick in the task's own PR, since `I6` is the single owner of the commit. |
| `{checkbox_id}` = `entry.task` (`H3.1`), a distinct field from `{task_id}` | `{task_id}` already means I6's branch form `03-H3.1`; reusing it would target a non-existent roadmap id. `I7` never binds `{task_id}`. |
| `{roadmap_file}` is the resolved **absolute path to the entry's own file** | The prompt names no directory (D15's two readers): `run()` resolves `paths.roadmap_dir`/`paths.roadmap_glob` from the resolved config **after** the locate, against the worktree the stages run in (K1), and passes the file, not the directory. |
| Entry resolution counts `(phase, task)` matches and refuses (exit 2, before the stage) unless exactly one | `find_task` returns the first match, so a duplicate would tick the wrong entry instead of refusing. |
| Post-stage verification re-parses the same file and requires exactly the target line `- [ ]` → `- [x]` with every other byte identical | An agent's exit 0 is not evidence the write happened (the O1 precedent). A weaker "line starts with `[x]`" check would pass a reformat, a neighbour edit, or trailing whitespace; the tick is a write to a committed file, so a wrong flip would advance `aidw tasks --next` past open work. |
| An already-`[x]` entry is a **successful no-op**: status `succeeded` (never `skipped`), `artifacts.tick = already` (vs `flipped`), plus one `run.log` line, `error` unset | Observable from `state.json`/`run.log` without a transcript; `skipped` is H3.2's status for a tick withheld behind red gates, and conflating the two would break H3.2's acceptance replay on this stage. |

**Where it fits in the roadmap:** Phase 3 (Stage resilience), task H3.1. It depends on H1's stage registry/plan work and H0's config resolution (D15/D17, K1) and on the existing `I3`/`I5`/`I6` chain. It is the prerequisite for H3.2 (tick only behind recorded green gates — which reuses this stage's `skipped` vocabulary) and H3.3 (share the tick with `fix` via a post-loop `WorkflowDefinition` section). The roadmap entry H3.1 is ticked.

**Scope:** `aidw/stage_registry.py` (new `I7` definition + `STAGE_IDS`), `aidw/roadmap.py` (pure tick helpers: entry resolution, file path, byte-exact postcondition), `aidw/workflows/implement.py` (post-locate entry resolution, variable threading through `build_plan`/`plan_stages`, pre/post-stage verification), `aidw/inventory.py`, the new `prompts/update-roadmap.md`, the trimmed `prompts/update-traceability.md`, `agents/recorder/AGENTS.md`, the design/EXTRACTION/classification documentation, the fixture config, and the affected unit tests. It deliberately stops short of gating the tick on gate evidence (H3.2), sharing it with `fix` (H3.3), adding a new agent id, and touching I3's four repo-specific artifacts.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `prompts/update-roadmap.md` | Created | New one-checkbox prompt: flips exactly one roadmap checkbox given `{roadmap_file}`/`{checkbox_id}`, names no directory, reports `already [x]` as a no-op. |
| `tests/test_roadmap_tick.py` | Created | Fake-stage tests for entry resolution (zero/duplicate/one match), the byte-exact postcondition, and the pinned `tick: flipped`/`tick: already` records and `run.log` lines. |
| `agents/recorder/AGENTS.md` | Modified | Gains a second stage section for `/update-roadmap` with its hard rules and output contract; `recorder` config unchanged. |
| `aidw/inventory.py` | Modified | `REQUIRED_PROMPTS` gains `update-roadmap.md`, so a rename fails loudly. |
| `aidw/roadmap.py` | Modified | Adds the pure tick helpers: `RoadmapTickError`, `TICK_FLIPPED`/`TICK_ALREADY`, entry resolution by match count, entry file path, and the byte-exact `verify_checkbox_flip`. |
| `aidw/stage_registry.py` | Modified | Adds `I7` to `STAGE_IDS` and `_IMPLEMENT.stages` between `I5` and `I6`; documents the two new expansion fields; `REPO_OPTIONAL_IDS` unchanged at `{I3, I4}`. |
| `aidw/workflows/implement.py` | Modified | Resolves the roadmap entry after the worktree locate and before `plan_stages` (exit 2 unless exactly one match), threads `roadmap_file`/`checkbox_id` through `build_plan` and `plan_stages`, and verifies the flip post-stage with the `tick` artifact marker and `run.log` line. |
| `design.md` | Modified | §8.2 chain/prose shows I7 and its verification; §3.4 stage table gains I7; §17 records decision row Y1. |
| `docs/migration/EXTRACTION.md` | Modified | §3.5 stage inventory table gains the `I7` row and the H3.1 amendment note. |
| `docs/migration/prompt-classification.md` | Modified | Adds class `(iv)` for `update-roadmap.md` as a post-cutover addition rather than back-dating it into an existing bucket. |
| `docs/tasks/03 - Stage resilience.md` | Modified | H3.1 roadmap checkbox ticked. |
| `docs/task-prompts/03-H3.1-prompt.md` | Created | The task prompt for this task (committed earlier on this branch). |
| `fixtures/target-repo/aidw/config.yaml` | Modified | Fixture's declared implement stage list re-baselined to the seven core ids in registry order, keeping the I3-disabled case meaningful. |
| `prompts/update-traceability.md` | Modified | Loses the tick: the `paths.roadmap_dir` owned-artifact row and the checkbox-flip instruction; it no longer mentions the roadmap, and its four repo-specific artifacts stay. |
| `tests/test_implement_workflow.py` | Modified | `DEFAULT_ORDER` now `I1, I2, I3, I4, I5, I7, I6`; adds the I3-disabled-still-ticks, no-`rules-coverage`-still-ticks, dry-run variable rendering, and F1 `--from` threading cases. |
| `tests/test_override_integration.py` | Modified | Fixture's declared-stages list includes `I7` in registry order (the "all core ids" premise), I3-disabled case kept. |
| `tests/test_plan_stages.py` | Modified | Seven-stage plan pinned with `update-roadmap` between I5 and I6, both variables rendered; registry-order pin updated. |
| `tests/test_prompt_classification.py` | Modified | Covers the new `(iv)` classification of `update-roadmap.md`. |
| `tests/test_prompt_neutrality.py` | Modified | New prompt included in the neutrality sweep. |
| `tests/test_stage_registry.py` | Modified | Asserts `I7` in `STAGE_IDS`, `REPO_OPTIONAL_IDS == {I3, I4}`, the removal/reorder rules treating `I7` as core, and re-points the unknown-stage example off `I7`. |

---

## Verification Results

### Top-level verification

Commands are this repo's own, taken from its root `AGENTS.md` ("Gates — run exactly these, and only these"); there is no `aidw/conventions.md` in this target repo and no lint/formatter/type-checker is configured (AGENTS.md §"Tests", design §15). Gate commands ran through `aidw gate run <key>` with the workflow's declared ignore scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 1ms`, lockfile current) |
| Build | `uv build --out-dir $(mktemp -d)/dist` (gate `build`) | ✅ Pass — built `aidt-1.1.1.tar.gz` and `aidt-1.1.1-py3-none-any.whl` |
| Test | `uv run --frozen pytest` (gate `suite`) | ❌ **Fail** — `1 failed, 1972 passed in 39.47s` |
| Doctor | `uv run --frozen aidw doctor` (gate `doctor`) | ✅ Pass — `21 checks: 0 failed, 2 warning(s)` (warnings: dirty working tree, missing `.mcp.json`) |
| Agents validate | `uv run --frozen aidw agents validate --strict` (gate `agents`) | ✅ Pass — `11 agent config(s): 0 error(s), 0 warning(s)` |
| Prompts check | `uv run --frozen aidw prompts check` (gate `prompts`) | ✅ Pass — `resolved repo prompts: 0 error(s), 0 warning(s)`; `update-roadmap.md` resolves to `prompts/update-roadmap.md` |
| Whitespace | `git diff --check` | ✅ Pass (exit 0, no output) |
| Lint | — | n/a — this repo configures no linter (AGENTS.md: "pytest is the only verification") |

Gate origins for the rows above (recorded by this run, tree `c25e5bd242be`):

- `build` — passed at `2026-11-10T20:09:54Z`, stage `record-implementation-results`, scope excludes `docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks`.
- `suite` — **failed** at `2026-11-10T20:10:36Z`, stage `record-implementation-results` (`1 failed, 1972 passed in 39.47s`), same scope.
- `doctor` — passed at `2026-11-10T20:10:39Z`, stage `record-implementation-results`, same scope.
- `agents` — passed at `2026-11-10T20:10:39Z`, stage `record-implementation-results`, same scope.
- `prompts` — passed at `2026-11-10T20:10:39Z`, stage `record-implementation-results`, same scope.

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1973 | ❌ Fail (`1 failed, 1972 passed` in 39.47s) |

The single failure, from the same invocation:

```
FAILED tests/test_roadmap_tick.py::test_a_nonzero_stage_exit_cannot_claim_the_no_op_success
AssertionError: assert 'succeeded' == 'failed'
tests/test_roadmap_tick.py:332
```

A fake stage exiting non-zero on an already-`[x]` entry is recorded as `succeeded` instead of `failed`. This contradicts task requirement 7 (any other outcome must fail the stage; `succeeded` is reserved for a verified flip or the pinned "already `[x]`, file unchanged" no-op) and the task prompt's test expectation that a variant "exits non-zero while claiming success" fails. Per this stage's rules the failure is recorded, not fixed here.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run aidw prompts check` green with `update-roadmap.md` present and in `REQUIRED_PROMPTS` | ✅ Pass (`0 error(s), 0 warning(s)`; prompt listed in the resolution output) |
| `uv run aidw agents validate --strict` green with the recorder AGENTS.md section | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| `tests/test_stage_registry.py`, `tests/test_plan_stages.py`, `tests/test_implement_workflow.py`, `tests/test_override_integration.py`, `tests/test_prompt_classification.py`, `tests/test_prompt_neutrality.py` re-baselined and green | ✅ Pass — derived from the single full-suite run above: none of these files appears in the failure list |
| `tests/test_roadmap_tick.py` passes with a fake stage (no real Pi model) | ❌ **Fail** — one test in this file failed (`test_a_nonzero_stage_exit_cannot_claim_the_no_op_success`); the other tests in the file passed in the same run |
| Hand-run `uv run aidw implement --dry-run docs/task-prompts/03-H3.1-prompt.md` plans `update-roadmap` after I5 and before I6 with both variables rendered | ❌ **unverified** — the CLI refused: `another implement run for '03-H3.1' is still marked running: 20261110T194333Z-03-H3.1-implement. Use --resume or finish it.` Finishing that run or resuming it is outside this stage's mandate, and the equivalent plan/render assertions are covered by `tests/test_implement_workflow.py`, which passed in the suite above. |
| Hand-run `--from update-roadmap` validates against that plan; a typo'd name still exits 2 | ❌ **unverified** — same blocked CLI invocation as the row above. The F1 refusal path is asserted by `tests/test_implement_workflow.py`, which passed in the same suite run. |

---

## Deviations observed during recording

- **Suite gate is red** — `test_a_nonzero_stage_exit_cannot_claim_the_no_op_success` fails. The implementation's no-op success path does not consult the stage exit code. Recorded as a failure; not fixed in this stage.
- **`--dry-run` hand check could not run** — a stale `running` marker for run `20261110T194333Z-03-H3.1-implement` blocks a second `aidw implement` for the same task. Marked unverified rather than worked around (`--resume` would start real workflow stages).
- **Task prompt names deliverable `aidw/roadmap.py`** — it appears under Deliverables as part of the workflow-verification change and was modified accordingly.

---

## Non-Goals (NOT implemented)

- ❌ Do not gate the tick on gate evidence — H3.2 (`WHEN_EVIDENCE_GREEN`) is the next task (task prompt, "Explicit non-goals").
- ❌ Do not share the tick with `fix` or build a shared post-loop `WorkflowDefinition` section — H3.3 is separate (task prompt, "Explicit non-goals").
- ❌ Do not make `update-roadmap` repo-optional or configurable — D13: it is core (`aidw/stage_registry.py`, `REPO_OPTIONAL_IDS == {I3, I4}`).
- ❌ Do not add a new agent id — `recorder` is reused (roadmap H3.1 Notes: rejected).
- ❌ Do not touch I3's four repo-specific artifacts (`docs/rules-coverage/catalog.json`, the generated `report.md`, `tests/integration/src/vector-matrix/vectors.ts`, `tests/integration/src/02.5-B/**`) — they stay in `update-traceability`.
- ❌ No lint/formatter/type-checker — AGENTS.md design §15: pytest only.
- ❌ No commit, push, or PR from this stage — `/pr` owns that.
