# Build Results — 05-S1.1: Add a path-scoped stage condition and gate `update-traceability` (I3) on it

**Branch:** `05-S1.1`
**Date:** 2026-11-19
**Spec:** `design.md` §8.2 (`aidw implement <task-prompt-path> [--pr <n>]`), §12.2 (stage registry and value overrides) and §17 row `Z11`; roadmap entry S1.1 in `docs/tasks/05 - Pipeline efficiency.md`; `docs/task-prompts/05-S1.1-prompt.md`
**Pull request:** not yet opened — the /pr stage records it here once the PR exists

## Summary

**Purpose:** Add a carried, path-scoped stage condition (`WHEN_PATHS_CHANGED`) and gate `I3 update-traceability` on a repo-declared `when_paths` set, so an `implement` run whose change set touches none of those paths skips traceability instead of paying for an agent invocation.

| Decision | Why it matters |
|----------|---------------|
| `WHEN_PATHS_CHANGED = "paths-changed"` joins the `when=` vocabulary and is **carried**, never expanded away | The expander has no change set, so `plan_stages`/`build_plan`/`--dry-run` must still plan `I3` in position and the workflow decides before `run_stage`. |
| `I3`'s registry entry carries the token but **no default path set** | A hardcoded path set would be a product literal in the toolkit (design §7.1/§17 S1); the roadmap's rules-engine/vector-matrix example belongs to a target repo, not the toolkit. |
| The paths are the optional per-stage `when_paths` list on `workflows.<name>.stages[]` | The set is per stage, not a global `paths.*` key, and the loader validates it fail-closed (design §12.1) by reusing `verification.normalise_ignore`. |
| Absent or empty `when_paths` means unconditional — today's behaviour | A repo that declares nothing keeps running `I3`; the toolkit default is the neutral empty set. |
| The change set is the one `I7` already measures: `git.changed_paths` against `BASE_DEFAULT` plus untracked paths, state root excluded | Using `repo.base_branch` would silently always- or never-skip, and reusing the evidence change set keeps both conditions consistent. |
| `None` change set (unresolvable base) **runs** the stage; only a real empty set skips | Dropping a stage that may be needed is not the fail-closed direction; "cannot prove irrelevant" is not "skip". |
| A skip is a cost-control decision, recorded through `runner.record_skipped` with `error` unset and no `state.status`/`state.resume` write | A skip is a success, not a red gate; it must not render as a failure (`aidw/report.py:stage_lines`). |
| Matching is `path == prefix or path.startswith(prefix + "/")` after normalisation | Mirrors `verification._excluded`, so `docs/x` matches a file or a directory subtree but never the sibling `docs/xy`. |

**Where it fits in the roadmap:** Phase 05 ("Pipeline efficiency"), epic S1 ("Path-scoped stage conditions"), task S1.1. It builds on H3.2's `WHEN_EVIDENCE_GREEN` carried-condition precedent (`Z1`) and the carried-condition evaluation points; S1.2 (gating `I4 update-architecture` on the same token, a repo-declared architecture trigger set and a doctor warning when the set is empty) is the next task and depends on this token.

**Scope:** `aidw/stage_registry.py` (the token and `I3`'s `when=`), `aidw/runner.py` (`StageSpec.when_paths` and its type-guarded carrier), `aidw/target_config.py` (`when_paths` field, parse, validate, normalise, serialise), `aidw/workflows/implement.py` (the pure matcher, the change-set reader, and both dispatch points), the config/schema/workflow-stage/design documentation, and the contract tests. It deliberately stops short of attaching the condition to `I4`, adding a doctor warning, hardcoding any repo's paths, adding a top-level `paths.*` key, changing `_expand_static`/`record_skipped`/`STAGE_IDS`/`REPO_OPTIONAL_IDS`, and gating `I3` on evidence.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/05-S1.1-prompt.md` | Created | The task prompt recording requirements, prompt-fixed decisions, tests and explicit non-goals. |
| `aidw/stage_registry.py` | Modified | Adds `WHEN_PATHS_CHANGED = "paths-changed"` and attaches it to `I3 update-traceability` with no default path set. |
| `aidw/runner.py` | Modified | Adds additive `StageSpec.when_paths` (default `()`) and the type-guarded `_declared_when_paths` carrier used by `_spec_from_planned`. |
| `aidw/target_config.py` | Modified | Adds `when_paths` to `STAGE_KEYS`/`StageConfig`/`to_dict` and the fail-closed `_parse_when_paths`, normalising via `verification.normalise_ignore`. |
| `aidw/workflows/implement.py` | Modified | Adds the pure `paths_changed_reason`, the `change_set_paths` reader and `withhold_paths_stage`, dispatching both carried tokens from `withhold_stage` in the serial and `--parallel` paths. |
| `design.md` | Modified | Documents the token and `I3` in §8.2, the stage field in §12.2, and records the prompt-fixed decisions in §17 row `Z11`. |
| `docs/target-repo-config.md` | Modified | Documents `when_paths` in the stage-entry table and shows it in the workflow example. |
| `docs/schema/aidw-config.schema.json` | Modified | Adds the `when_paths` array-of-strings property to the `stage` node. |
| `docs/workflow-stages.md` | Modified | Adds `paths-changed` to the Conditions table and `I3`'s `when=` cell, and documents `when_paths` in the stage-entry guidance. |
| `docs/tasks/05 - Pipeline efficiency.md` | Modified | Ticks S1.1 as complete. |
| `tests/test_stage_registry.py` | Modified | Pins the new token in the vocabulary, `I3`'s carried `when`, and `_expand_static`'s carrying behaviour. |
| `tests/test_plan_stages.py` | Modified | Pins `I3`'s planned `when`, the declared `when_paths` overlay, the empty default, and the type-guarded seam. |
| `tests/test_implement_workflow.py` | Modified | Adds the pure matcher cases and end-to-end skip/run/unconditional/`None`/`--dry-run` fake-stage runs for both serial and parallel dispatch. |
| `tests/test_target_config.py` | Modified | Pins the new stage key, schema agreement, round-trip/purity vectors and the fail-closed wrong-typed/bad-entry errors. |
| `tests/test_target_repo_config_doc.py` | Modified | Pins the documented `when_paths` field and its `EXPECTED_DEFAULTS` default cell. |
| `tests/test_workflow_stages_doc.py` | Modified | Adds `paths-changed` to the exact declarable-token set and pins the Conditions table / `I3` cell. |
| `tests/test_design_doc.py` | Modified | Pins §8.2's paragraph, §12.2's field description and the single §17 `Z11` row. |

---

## Verification Results

Commands are this repo's own, taken from its root `AGENTS.md` ("Gates — run exactly these, and only these"). There is no `aidw/conventions.md` and AGENTS.md states that `pytest` is the only verification (no linter, formatter or type-checker is configured; design §15). The gates ran through `aidw gate run` with the workflow's declared scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.91ms`) |
| Lint | — | **unverified** — the repo configures no linter (AGENTS.md: "pytest is the only verification") |
| Build | `uv build --out-dir <tmp>` (gate `build`) | ✅ Pass (`Successfully built aidt-1.5.0.tar.gz` and `aidt-1.5.0-py3-none-any.whl`) |
| Test | `uv run --frozen pytest` (gate `suite`) | ✅ Pass (`2248 passed in 44.46s`) — cited from the run's recorded gate, not re-run here |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`) — warnings are the dirty working tree and the missing `.mcp.json` |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (toolkit defaults and resolved repo prompts: `0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (exit 0, no output) |

Gate origins:

- `build` passed for tree `0664239b93b2` at `2026-11-19T09:14:48Z` by stage `record-implementation-results`, scope excludes `docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks`.
- `suite` passed for tree `0664239b93b2` at `2026-11-19T09:11:05Z` by stage `test` (`2248 passed in 44.46s`), same scope. Asking for the same gate with the same scope against this stage's tree printed the `reused: …` line and exited 0 without re-running, so this is the run's own recorded observation of the same gated content.

### `uv run --frozen pytest` (full suite)

The single full-gate run above is the source for the suite result. The task-specific test files are included in that run; no separate suite or subset was invoked.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2248 | ✅ Pass (`2248 passed in 44.46s`) |
| Task cases in `tests/test_stage_registry.py`, `tests/test_plan_stages.py`, `tests/test_implement_workflow.py`, `tests/test_target_config.py`, `tests/test_target_repo_config_doc.py`, `tests/test_workflow_stages_doc.py`, `tests/test_design_doc.py` | included in the full suite | ✅ Pass (covered by the same `2248 passed` run; no second invocation) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Pure matcher — exact path, inside-directory, not-touching, empty declared set, file-prefix, `./x`/trailing-slash normalisation, `None` → run, purity | ✅ Pass — covered by the full suite |
| Serial end-to-end fake-stage runs — skip when no declared path is touched, run when one is, run with no declaration, `--dry-run` plans and evaluates nothing | ✅ Pass — covered by the full suite |
| `--parallel` end-to-end — a group member carrying `paths-changed` is withheld before pool submission | ✅ Pass — covered by the full suite |
| Registry pins — token vocabulary, `I3`'s `when=`, `_expand_static` still carries it | ✅ Pass — covered by the full suite |
| Plan pins — `I3`'s planned `when`, declared `when_paths` overlay, empty default, type-guarded seam | ✅ Pass — covered by the full suite |
| Config/schema pins — stage key, schema agreement, round-trip with explicit empty list, wrong-typed and bad-entry `ERROR`s naming the dotted path | ✅ Pass — covered by the full suite |
| Doc pins — Conditions table, `I3` cell, `when_paths` documentation/defaults, §8.2/§12.2 and a single §17 `Z11` row | ✅ Pass — covered by the full suite |

---

## Deviations observed during recording

- **No lint command exists to run** — the repo's AGENTS.md gate list contains install, pytest, doctor, agents validation and prompts check only, and states that `pytest` is the only verification. The lint row is recorded as unverified rather than inventing a command.
- **The suite outcome was reused from this run's recorded gate** — the same `suite` gate had already passed for tree `0664239b93b2` under the identical declared scope during the `test` stage (`2026-11-19T09:11:05Z`). `aidw gate run` printed the `reused: …` line and exited 0 without re-running, so the row cites that origin instead of buying the suite again.
- **No pull request exists** — the read-only `gh pr view 05-S1.1` lookup returned nothing. The document records the required not-yet-opened note; `/pr` will replace it with the real number after creating the pull request.
- **`aidw doctor` reports two warnings** — the dirty working tree and missing `.mcp.json` are expected while the implementation and this results document remain uncommitted, and `0 checks failed`.

---

## Non-Goals (NOT implemented)

- ❌ S1.2 (gating `I4 update-architecture` on the condition, a repo-declared architecture trigger set, and an `aidw doctor` warning when the set is empty) is not implemented — it is a separate task that depends on this token (task prompt, "Explicit non-goals").
- ❌ No repo's paths (the Mythical Forge rules-engine / `docs/rules-coverage` / vector-matrix paths) are hardcoded as a toolkit default, and no top-level `paths.*` key was added — the path set is a per-stage `when_paths` (task prompt, "Explicit non-goals").
- ❌ `_expand_static`, `record_skipped`'s contract, `STAGE_IDS`/`REPO_OPTIONAL_IDS`, and every other stage's `when=` were left unchanged — only `I3` gains the condition (task prompt, "Explicit non-goals").
- ❌ `I3` is not gated on `WHEN_EVIDENCE_GREEN` and the skip does not read `state.gate_outcomes` — path membership, not evidence (task prompt, "Explicit non-goals").
- ❌ No commit, push or pull request from this record stage — delivery belongs to `/pr` (record stage instruction).
