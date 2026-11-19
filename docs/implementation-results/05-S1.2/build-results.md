# Build Results — 05-S1.2: Gate `update-architecture` (I4) on the path condition

**Branch:** `05-S1.2`
**Date:** 2026-11-20
**Spec:** `design.md` §8.2 (`aidw implement <task-prompt-path> [--pr <n>]`), §12.2 (stage registry and value overrides), §17 row `Z12`; roadmap entry S1.2 in `docs/tasks/05 - Pipeline efficiency.md`; `docs/task-prompts/05-S1.2-prompt.md`; `docs/workflow-stages.md`; `docs/target-repo-config.md`
**Pull request:** not yet opened — the /pr stage records it here once the PR exists

## Summary

**Purpose:** Gate `I4 update-architecture` on S1.1's carried `when=paths-changed` condition with a product-neutral `docs/architecture` default, so an `implement` run whose change set touches no architecture trigger path skips the architecture agent instead of paying for it.

| Decision | Why it matters |
|----------|---------------|
| `I4` reuses `WHEN_PATHS_CHANGED = "paths-changed"` and its registry default is the **prefix** `docs/architecture` | No new token; the prefix matches S1.1's prefix-based matcher, whereas the roadmap's informal `docs/architecture/**` glob would match nothing. The default is D17's own literal `architecture_dir` default, so it is product-neutral. |
| A repo-declared `when_paths` **replaces** the registry default; it never merges | This keeps S1.1's override semantics unchanged and makes an explicit `when_paths: []` the one reachable empty/effective-unconditional set, which the doctor warning can detect. Merge would make that warning unreachable. |
| The loader's absent-vs-empty distinction survives onto `StageSpec.when_paths` | `runner._declared_when_paths_or_none` returns `None` for an absent key (registry default applies) and `()` for an explicit empty list (unconditional), because the workflow evaluates the carried value. |
| Evaluation reuses the existing `paths_changed_reason`/`withhold_stage` dispatch on both paths | `I4` sits in the default `parallel_groups` pair, so the `--parallel` member filter is the common path; gating only `execute()` would still run it. A skip uses `record_skipped` (no `error`, no `state.status`/`state.resume` write), and a `None` change set runs `I4` rather than skipping on "cannot prove". |
| `aidw doctor` warns only for an **enabled** `I4` whose effective trigger set is empty | A disabled stage has no write-target to justify a warning; an absent key keeps the default and a non-empty declaration is the operator's own trigger set, so neither warns. |

**Where it fits in the roadmap:** Phase 05 ("Pipeline efficiency"), epic S1 ("Path-scoped stage conditions"), task S1.2. It depends on S1.1's `WHEN_PATHS_CHANGED` token, `when_paths` field and `paths_changed_reason`/`withhold_stage` dispatch (decision `Z11`), and it records the next decision as §17 row `Z12`. Later path/context-economy work in the phase (C1, G1, B1) depends on this gating pattern but was not started here.

**Scope:** `aidw/stage_registry.py` (the optional `StageDefinition`/`PlannedStage` `when_paths` field and `I4`'s token + default), `aidw/runner.py` (absent-vs-empty carry onto `StageSpec.when_paths`), `aidw/doctor.py` (the enabled-empty warning), `design.md` §§8.2/12.2/17, `docs/target-repo-config.md`, `docs/workflow-stages.md`, the roadmap checkbox, and the named contract/doc tests. It deliberately stops short of changing `I3`'s handling, adding a new config key or `paths.*` key, adding glob matching, gating `I4` on `WHEN_EVIDENCE_GREEN`, or starting C1.1/C1.2/C1.3 and G1.1/G1.2.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/implementation-results/05-S1.2/integration-test-guide.md` | Created | The human-run integration guide written by the `write-integration-test-guide` stage. |
| `docs/implementation-results/05-S1.2/summary.md` | Created | The implementation summary written by the `summarize-implementation-results` stage. |
| `docs/task-prompts/05-S1.2-prompt.md` | Created | The task prompt recording requirements, the task owner's replace decision, tests, deliverables and explicit non-goals. |
| `aidw/doctor.py` | Modified | Adds `_check_architecture_trigger`, warning only when `I4` is enabled with an explicit empty `when_paths`. |
| `aidw/runner.py` | Modified | Adds `_declared_when_paths_or_none` and applies the registry default only when the repo entry omits `when_paths`; an explicit empty list stays empty. |
| `aidw/stage_registry.py` | Modified | Adds `when_paths` to `StageDefinition`/`PlannedStage`, attaches `WHEN_PATHS_CHANGED` and the `("docs/architecture",)` default to `I4`. |
| `design.md` | Modified | Documents `I4`'s path gate/default/override/doctor contract in §§8.2 and 12.2 and records decision row `Z12` in §17. |
| `docs/target-repo-config.md` | Modified | Documents the `when_paths` replace rule, the literal default, the custom-`architecture_dir` obligation, the re-list guidance and the empty-set doctor warning. |
| `docs/tasks/05 - Pipeline efficiency.md` | Modified | Updates the S1.2 roadmap entry and marks its checkbox complete. |
| `docs/workflow-stages.md` | Modified | Changes `I4`'s `when=` cell to `paths-changed`, extends the condition table, and documents the default/replace/doctor contract. |
| `tests/test_design_doc.py` | Modified | Pins §8.2/§12.2 mentions and exactly one S1.2 decision row in §17. |
| `tests/test_doctor.py` | Modified | Covers the four enabled/absent/non-empty/disabled cases and the warning message contents. |
| `tests/test_implement_workflow.py` | Modified | Adds end-to-end fake-stage runs for the default skip, architecture/declared-input runs, explicit empty, `None` change set, and the parallel dispatch path. |
| `tests/test_plan_stages.py` | Modified | Pins `I4`'s default `when_paths`, replacement by a declared list, and explicit `[]` staying empty. |
| `tests/test_stage_registry.py` | Modified | Pins `I4`'s carried `when`, its registry default, and the expanded plan carrying both. |
| `tests/test_target_repo_config_doc.py` | Modified | Pins the `when_paths` documentation for `I4`, the re-list rule and the custom-`architecture_dir` sentence. |
| `tests/test_workflow_stages_doc.py` | Modified | Pins `I4`'s documented `when=` cell and the default/doctor prose. |

---

## Verification Results

Commands are this repo's own, taken from its root `AGENTS.md` ("Gates — run exactly these, and only these"). There is no `aidw/conventions.md`, and AGENTS.md states that `pytest` is the only verification (no linter, formatter or type-checker is configured; design §15), so the lint row is unverified. The gates ran through `aidw gate run <key>` with the workflow's declared scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 1ms`) |
| Lint | — | **unverified** — the repo configures no linter (AGENTS.md: "pytest is the only verification") |
| Build | `uv build --out-dir <mktemp dir>` (gate `build`) | ✅ Pass — built `aidt-1.5.0.tar.gz` and `aidt-1.5.0-py3-none-any.whl` |
| Test | `uv run --frozen pytest` (gate `suite`) | ✅ Pass (`2265 passed in 58.25s`) — cited from the run's recorded gate, not re-run here |
| Doctor | `uv run --frozen aidw doctor` (gate `doctor`) | ✅ Pass (`22 checks: 0 failed, 2 warning(s)`) — warnings are the dirty working tree and the missing `.mcp.json` |
| Agents validate | `uv run --frozen aidw agents validate --strict` (gate `agents`) | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` (gate `prompts`) | ✅ Pass (toolkit defaults and resolved repo prompts: `0 error(s), 0 warning(s)`) |
| Traceability / roadmap parser | `uv run aidw tasks --validate` (gate `traceability`) | ✅ Pass (exit 0, no output) |
| Whitespace | `git diff --check` | ✅ Pass (exit 0, no output) |

Gate origins for the rows above (tree `91f13fbdb5ab`, scope excludes `docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks`):

- `build` — passed at `2026-11-19T21:36:30Z`, stage `record-implementation-results` (`Successfully built …/aidt-1.5.0-py3-none-any.whl`).
- `suite` — passed at `2026-11-19T21:34:01Z`, stage `test` (`2265 passed in 58.25s`), reused by this stage against the same tree and scope. No second suite was run for this document.
- `doctor` — passed at `2026-11-19T21:36:36Z`, stage `record-implementation-results` (`22 checks: 0 failed, 2 warning(s)`).
- `prompts` — passed at `2026-11-19T21:36:37Z`, stage `record-implementation-results` (resolved repo prompts: `0 error(s), 0 warning(s)`).
- `agents` — passed at `2026-11-19T21:36:38Z`, stage `record-implementation-results` (`11 agent config(s): 0 error(s), 0 warning(s)`).
- `traceability` — passed at `2026-11-19T21:35:24Z`, stage `update-traceability`, command `uv run aidw tasks --validate`, same tree and scope.

### `uv run --frozen pytest` (full suite)

The single full-gate run above is the source for the full-suite row. The focused row is the same run's earlier `test` stage smoke gate against the same tree; neither was re-run for this document.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2265 | ✅ Pass (`2265 passed in 58.25s`, gate `suite`, stage `test`) |
| `tests/test_implement_workflow.py tests/test_doctor.py tests/test_stage_registry.py tests/test_plan_stages.py tests/test_design_doc.py tests/test_workflow_stages_doc.py tests/test_target_repo_config_doc.py` | 428 | ✅ Pass (`428 passed in 54.07s`, gate `smoke`, stage `test`) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Registry pins — `I4` carries `WHEN_PATHS_CHANGED`, its `when_paths` default is `("docs/architecture",)`, and expansion carries both | ✅ Pass — covered by `tests/test_stage_registry.py` in the full and focused runs |
| Planning pins — undeclared `I4` uses the default, a declared non-empty list replaces it, and explicit `[]` stays empty | ✅ Pass — covered by `tests/test_plan_stages.py` in the full and focused runs |
| Serial end-to-end — an unrelated change set records `I4` `skipped` with a reason and the run still succeeds; a change under `docs/architecture` runs it; a declared diagram input runs it; explicit `[]` runs unconditionally; `None` change set runs it | ✅ Pass — covered by `tests/test_implement_workflow.py` in the full and focused runs |
| Parallel end-to-end — `I4` is withheld by the `--parallel` member filter before dispatch | ✅ Pass — covered by `tests/test_implement_workflow.py` in the full and focused runs |
| Doctor warning — enabled + explicit `[]` warns naming `I4` and the required declaration; enabled + absent, enabled + non-empty, and disabled + `[]` do not warn | ✅ Pass — covered by `tests/test_doctor.py` in the full and focused runs |
| Design-doc pins — §8.2 and §12.2 mention `I4`/`paths-changed`/`docs/architecture`/`doctor`, and exactly one S1.2 §17 row exists | ✅ Pass — covered by `tests/test_design_doc.py` |
| Workflow-stages doc drift — `I4`'s `when=` cell is `paths-changed` and the default/doctor prose is documented | ✅ Pass — covered by `tests/test_workflow_stages_doc.py` |
| Target-config doc drift — `when_paths` documentation covers `I4`, the re-list rule and the custom-`architecture_dir` obligation | ✅ Pass — covered by `tests/test_target_repo_config_doc.py` |
| Roadmap parser guard — validated task ids are intact | ✅ Pass — `uv run aidw tasks --validate` exited 0 (gate `traceability`) |

---

## Deviations observed during recording

- **No lint command exists to run** — the repo's AGENTS.md gate list contains install, pytest, doctor, agents validation and prompts check only, and states that `pytest` is the only verification. The lint row is recorded as unverified rather than inventing a command.
- **The suite and focused outcomes were reused from this run's recorded gates** — `suite` and `smoke` had already passed for tree `91f13fbdb5ab` under the identical declared scope during the `test` stage. `aidw gate run` printed the `reused: …` line and exited 0 without re-running, so the rows cite those origins instead of buying the suites again.
- **No pull request exists** — the read-only `gh pr view 05-S1.2` lookup returned nothing. The document records the required not-yet-opened note; `/pr` will replace it with the real number after creating the pull request.
- **`aidw doctor` reports two warnings** — the dirty working tree and missing `.mcp.json` are expected while the implementation and this results document remain uncommitted, and `0 checks failed`.
- **The roadmap checkbox was already ticked** — `docs/tasks/05 - Pipeline efficiency.md` already carries `- [x]` for S1.2 in the working tree; this record stage did not modify it.

---

## Non-Goals (NOT implemented)

- ❌ S1.1's `I3` gating and its empty-equals-unconditional semantics were not changed — `I4` is the only stage this task gates (task prompt, "Explicit non-goals").
- ❌ C1.1/C1.2/C1.3 (context and gate-command economy) and G1.1/G1.2 (prompt-review depth) were not started (task prompt, "Explicit non-goals").
- ❌ No glob matching, new config key, top-level `paths.*` key or separate "diagram-input" field was added — repo-declared diagram inputs reuse `when_paths` (task prompt, "Explicit non-goals").
- ❌ `I4` was not gated on `WHEN_EVIDENCE_GREEN` — the gate is path membership, not evidence (task prompt, "Explicit non-goals").
- ❌ No commit, push or pull request from this record stage — delivery belongs to `/pr` (record stage instruction).
