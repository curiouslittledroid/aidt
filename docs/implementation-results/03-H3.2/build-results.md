# Build Results — 03-H3.2: Tick only behind evidence, never against a red gate

**Branch:** `03-H3.2`
**Date:** 2026-11-10
**Spec:** `design.md` §8.2 (I7 `update-roadmap` and `WHEN_EVIDENCE_GREEN`), §9.2 (`gate_outcomes` and content-tree identity), §9.3 (the stage status vocabulary), §10 (error handling), §14 (`aidw gate run` and cite-or-run), §15 (testing strategy), §17 (decision row `Z1`); roadmap entry H3.2 in `docs/tasks/03 - Stage resilience.md`

## Summary

**Purpose:** Withhold the roadmap tick unless the run's own recorded gate evidence is green for the exact tree the tick edits, so an agent can never claim completion while a gate is red.

| Decision | Why it matters |
|----------|---------------|
| `WHEN_EVIDENCE_GREEN` is **carried**, never expanded away | `plan_stages`, `build_plan` and `--dry-run` still plan I7 in its run position; the workflow evaluates the condition at run time because gate outcomes are not visible to the expander. |
| The workflow evaluates the condition **before any `run_stage` call**, on both serial and `--parallel` member paths | A `--parallel` group may legally name `update-roadmap`, bypassing the serial `execute()` path; checking both paths means no agent ever gets the chance to tick a box the run has no evidence for. |
| Evidence is the run's **in-memory** `gate_outcomes`, against `tree_identity`'s default base and the four resolved document write-target directories | This matches exactly what `aidw gate run` recorded (same base, same `--ignore` scope, same state-root exclusion) and avoids re-reading stale state or re-introducing the boundary loss H0.1 closed. |
| A withheld tick is a full `StageRecord` with status `skipped`, `error` unset, and the reason in `artifacts[skip_reason]` | A skip is neither a failure nor a successful no-op (H3.1's already-`[x]` case); it is observable from `state.json`/`run.log` without a transcript and renders as `skipped: <reason>`, not `error:`. |
| `None` tree identity and zero matching outcomes are **no evidence**, never green | E4.8 is cite-or-run, never assume: an unresolvable base or over-budget change set must not silently become permission to tick. |

**Where it fits in the roadmap:** Phase 3 (Stage resilience), task H3.2. It depends on H3.1's `I7 update-roadmap` stage, H0.1's gate-outcome persistence across stage boundaries, and E4.8's recorded gate outcomes. It is the prerequisite for H3.3, which reuses `WHEN_EVIDENCE_GREEN` for the `fix` workflow. The roadmap entry H3.2 is ticked in the working tree.

**Scope:** `aidw/stage_registry.py` (token + I7 condition), `aidw/runner.py` (`StageSpec.when`, shared agent resolution, `record_skipped`), `aidw/state.py` (`SKIPPED`, `SKIP_REASON_KEY`), `aidw/workflows/implement.py` (pure evidence rule, tree/scope computation, both dispatch paths), `aidw/report.py` (`skipped` rendering), the design sections and §17 `Z1` row, and the four affected test modules. It deliberately stops short of applying the condition to `fix` (H3.3), changing which stages gate, and adding any lint/formatter/type-checker.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/03-H3.2-prompt.md` | Created | The task prompt for this task (committed earlier on this branch). |
| `aidw/stage_registry.py` | Modified | Adds and exports `WHEN_EVIDENCE_GREEN`; I7 `update-roadmap` carries the condition so it is planned but not expanded away. |
| `aidw/runner.py` | Modified | Adds additive `StageSpec.when`, copies it from the planned stage, extracts shared `stage_agent`, and adds `record_skipped` (persisted under `_STATE_LOCK` like a normal stage record). |
| `aidw/state.py` | Modified | Adds the `skipped` stage status and the `skip_reason` artifact key; both additive at the existing schema version. |
| `aidw/workflows/implement.py` | Modified | Adds the pure `tick_evidence` rule, resolved ignore-scope and current-tree computation, and withholds I7 before `run_stage` on both serial and parallel dispatch paths. |
| `aidw/report.py` | Modified | `stage_lines` renders a skipped record with its reason and never as an `error:`/failure line. |
| `design.md` | Modified | §8.2 documents I7's `when=WHEN_EVIDENCE_GREEN`; §9.3 adds the `skipped` stage status; §17 records decision row `Z1`. |
| `tests/test_stage_registry.py` | Modified | Pins I7's condition, its carried-not-expanded behaviour, and the exported `WHEN_*` vocabulary. |
| `tests/test_roadmap_tick.py` | Modified | Adds hand-calculated fixtures for green/red/no-evidence/different-tree outcomes, ignore-scope resolution, default-base recomputation, in-memory state use, purity and property checks. |
| `tests/test_implement_workflow.py` | Modified | Covers the E6.1 red-`suite` replay, the green tick exactly once, no-evidence skip, already-`[x]` no-op, parallel-group withholding, and that neither `run_stage` nor `settle_tick` runs for a skipped I7. |
| `tests/test_report.py` | Modified | Covers skipped-stage rendering with its reason, the missing-reason fallback, and that a failed stage is not rendered as a skip. |
| `docs/tasks/03 - Stage resilience.md` | Modified | H3.2 roadmap checkbox ticked (already `[x]` in the working tree before this recording stage). |

---

## Verification Results

### Top-level verification

Commands are this repo's own, taken from its root `AGENTS.md` ("Gates — run exactly these, and only these"). There is no `aidw/conventions.md` in this target repo and no lint/formatter/type-checker is configured (AGENTS.md "Tests"; design §15). Gate commands ran through `aidw gate run <key>` with the workflow's declared ignore scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 1ms`) |
| Build | `uv build --out-dir <tmp>/dist` (gate `build`) | ✅ Pass — built `aidt-1.1.1.tar.gz` and `aidt-1.1.1-py3-none-any.whl` |
| Test | `uv run --frozen pytest` (gate `suite`) | ✅ Pass (`1999 passed in 42.81s`) |
| Doctor | `uv run --frozen aidw doctor` (gate `doctor`) | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`) |
| Agents validate | `uv run --frozen aidw agents validate --strict` (gate `agents`) | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` (gate `prompts`) | ✅ Pass (`resolved repo prompts: 0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (exit 0, no output) |
| Lint | — | n/a — this repo configures no linter (AGENTS.md: "pytest is the only verification") |

Gate origins for the rows above (recorded by this run, tree `ac4d08cca1f1`, scope excludes `docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks`):

- `build` — passed at `2026-11-10T21:25:06Z`, stage `record-implementation-results`.
- `suite` — **reused** pass at `2026-11-10T21:23:30Z` from stage `update-traceability` (`1999 passed in 42.81s`); this invocation returned `reused: gate 'suite' passed …` and did not re-run.
- `doctor` — passed at `2026-11-10T21:25:12Z`, stage `record-implementation-results`.
- `agents` — passed at `2026-11-10T21:25:12Z`, stage `record-implementation-results`.
- `prompts` — passed at `2026-11-10T21:25:12Z`, stage `record-implementation-results`.

### `uv run --frozen pytest` (full suite)

Rows are derived from recorded gate outcomes for the same tree and scope; no second full-suite run was bought for this document.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (gate `suite`, cited from `update-traceability`) | 1999 | ✅ Pass (`1999 passed in 42.81s`) |
| `tests/test_stage_registry.py tests/test_roadmap_tick.py tests/test_implement_workflow.py tests/test_report.py` (focused gate `suite` from stage `test`, tree `ac4d08cca1f1`) | 223 | ✅ Pass (`223 passed in 20.05s`) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| I7 carries `when=WHEN_EVIDENCE_GREEN`; the condition is carried by `expand`/`plan_stages`; the token is exported beside the other `WHEN_*` values | ✅ Pass — covered by `tests/test_stage_registry.py` in the focused and full suite runs |
| Condition helper is green iff ≥1 outcome for the current tree and all passed; red names every failing key; zero matching outcomes or `tree_identity is None` is no evidence; different-tree outcomes are ignored | ✅ Pass — covered by `tests/test_roadmap_tick.py` in the focused suite (`223 passed`) |
| E6.1 replay with red `suite` records I7 `skipped` naming `suite`, writes no roadmap change, and does not call `run_stage` or `settle_tick`; green `suite` ticks exactly once; second green run on `[x]` is `succeeded`; zero outcomes skips naming the absence; skip leaves exit status unchanged; parallel member gets the same check | ✅ Pass — covered by `tests/test_implement_workflow.py` in the focused suite |
| `stage_lines` renders a `skipped` record with its reason and no `error:`/`usage:` line | ✅ Pass — covered by `tests/test_report.py` in the focused suite |
| Hand-run `uv run aidw implement --dry-run docs/task-prompts/03-H3.2-prompt.md` plans `update-roadmap` without failing on missing evidence | ❌ **unverified** — the CLI refused with exit 4: `another implement run for '03-H3.2' is still marked running: 20261110T205832Z-03-H3.2-implement. Use --resume or finish it.` Resuming or finishing that run is outside this stage's mandate; the plan-level condition pins are covered by `tests/test_stage_registry.py` and the workflow tests in the suite above. |

---

## Deviations observed during recording

- **Suite gate was reused, not re-run** — `aidw gate run suite` reported a same-tree, same-scope pass recorded by `update-traceability` at `2026-11-10T21:23:30Z` (`1999 passed in 42.81s`). That is this run's recorded observation of the same content, so no second full-suite run was performed.
- **`--dry-run` hand check could not run** — a stale `running` marker for run `20261110T205832Z-03-H3.2-implement` blocks a second `aidw implement` for the same task. Recorded as unverified rather than worked around (`--resume` would start real workflow stages).
- **Roadmap entry already ticked** — `docs/tasks/03 - Stage resilience.md` already has H3.2 as `- [x]` in the working tree before the record/update-roadmap stages. The update-roadmap stage therefore reports `already [x]` and leaves the file byte-identical.

---

## Non-Goals (NOT implemented)

- ❌ H3.3: do not add the stage/condition to `fix` or build a shared post-loop `WorkflowDefinition` section; only make the token reusable via `StageSpec.when` (task prompt, "Explicit non-goals").
- ❌ H0.1: do not restate or re-fix gate-outcome persistence/the lock mechanism; read outcomes from the merged in-memory run state (task prompt, "Explicit non-goals").
- ❌ Do not change which stages gate, what a red gate stops, or E4.8's gate scope (it stays with I5); I3/I4 stay ungated (task prompt, "Explicit non-goals").
- ❌ Do not add a lint/formatter/type-checker — AGENTS.md and design §15: pytest only (task prompt, "Explicit non-goals").
- ❌ Do not write `player-actions.md` or `integration-tests.md` — the `show-updated-*` prompts own those documents.
- ❌ No commit, push, or pull request from this stage — `/pr` owns delivery.
