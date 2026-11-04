# Build Results — 00-E4.5a: Enforce core vs repo-optional — the rules and their messages (D12, D13)

**Branch:** `00-E4.5a`
**Date:** 2026-11-04
**Spec:** `docs/migration/EXTRACTION.md` §2 (locked decisions D12 override granularity, D13 core vs repo-optional stages), §3.4 (target-repo config — the `workflows.<name>.stages` shape replaces wholesale), §3.5 (stage and workflow model — core-vs-repo-optional rules, `enabled: false`, repo-added stages, R6 stage-id vocabulary), §10 (R6); `design.md` §3 (directory layout)

## Summary

**Purpose:** Refuse a repo config that disables, removes or reorders a core stage — and refuse a declarable loop stage — through a pure `validate_stage_list` validator wired into all five workflow preflights, so D12/D13 are enforced before any run record or worktree exists.

| Decision | Why it matters |
|----------|---------------|
| Loop stages are detected as `stages_by_id(workflow)` keys **minus** `definition.stages`, never via `STAGE_IDS` membership | `STAGE_IDS` holds `P2` but not `P2-fix-*`/`P2-reconcile`, which `stages_by_id()` does return; membership testing would misclassify `P2-fix-blocking` as a repo-added stage and let it be silently double-planned by `expand`. |
| Classification has no third category: repo-optional = `REPO_OPTIONAL_IDS = frozenset({"I3", "I4"})`, core = static stage ids minus those, everything else repo-added | D13 names only traceability/architecture as optional; a single derived split keeps the validator and the registry from drifting apart. |
| R2 (review publisher) and A1 (approve) are fixed as **core** | D13/§3.5 are silent on those roles, but making them repo-optional would turn `review`/`approve`/`fix` into no-ops; prompt-fixed in the task. |
| Validation runs only when the resolved `workflows.<name>.stages` entry has `source == SOURCE_CONFIG` | `resolve_config` omits an undeclared entry, so value-based tests would falsely report every core stage removed on a config that never declared the list; an explicit `stages: []` does carry `source=config` and correctly reports removals. |
| A declared list replaces the registry's list wholesale, so removal, duplication and reorder are **separate** whole-list checks with one `ERROR` each (reorder: one per list, naming both orders) | An omitted core stage is a removal, a present-but-misordered one a reorder; `[I2, I1]` must report removals for I5/I6 *and* one reorder error, never one blended message. A duplicate is one error per core id. |
| `validate_stage_list` takes plain stage mappings and imports no `target_config`/workflow module; it raises `UnknownWorkflowError` for an unknown workflow | Mirrors `validate_parallel_groups`' dependency direction (registry stays a leaf) and turns a programming error into a named exception rather than a traceback. |
| Entries the target-config loader already refused (non-`Mapping`, missing/empty `id`) are skipped | Re-reporting them would duplicate the loader's refusal; the validator adds only rules the loader cannot express. |
| Repo-added and repo-optional stages are free to interleave or move; the declared core-id subsequence must equal the registry's static core order | D12 locks only core stages, so I3/I4 may be disabled, removed or moved and repo-added stages may sit anywhere. |

**Where it fits in the roadmap:** Phase E4 (config-driven orchestrator). It builds on E4.1's registry (`stages_by_id`/`WorkflowDefinition`), E4.3's `resolve_workflow_config`/`plan_stages` and E4.4's `validate_parallel_groups` preflight pattern, and it is the enforcement half of the split E4.5; E4.5b (planning the shapes this task accepts: repo-added `StageSpec` construction, a named `StageRegistryError`, honouring `enabled: false` in the plan, the three fixed-arity consumer rewrites) is separate, as are E4.6 (agent/model/thinking overrides) and E4.7 (the fixture integration test).

**Scope:** The pure validator in `aidw/stage_registry.py`, a `REPO_OPTIONAL_IDS` constant, the preflight wiring in `implement`/`prompt`/`review`/`fix`/`approve`, the stale E4.3 deferred-warning comment header in `aidw/runner.py`, the updated stale `test_dry_run_renders_a_repo_declared_prompt_override` fixture, and the validator plus per-workflow preflight tests. It stops short of changing `plan_stages`/`_stage_prompt_overlays`, of validating repo-added stage fields, and of adding the validator to `aidw doctor`/`aidw config show`.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/implementation-results/00-E4.5a/build-results.md` | Created | This results document. |
| `aidw/stage_registry.py` | Modified | Adds `REPO_OPTIONAL_IDS`, the pure `validate_stage_list` validator with its per-entry and whole-list checks, and rewrites the module docstring to describe E4.5a enforcement vs E4.5b planning. |
| `aidw/workflows/implement.py` | Modified | Adds `STAGES_PATH` and validates the declared stage list right after the E4.4 `parallel_groups` preflight; module docstring updated. |
| `aidw/workflows/prompt.py` | Modified | Validates a declared `workflows.prompt.stages` list immediately after the config refusal, before `validate_paths`/`load_tasks`. |
| `aidw/workflows/review.py` | Modified | Imports `stage_registry`/`SOURCE_CONFIG` and validates a declared `workflows.review.stages` list in the preflight. |
| `aidw/workflows/fix.py` | Modified | Imports `stage_registry`/`SOURCE_CONFIG` and validates a declared `workflows.fix.stages` list in the preflight. |
| `aidw/workflows/approve.py` | Modified | Imports `stage_registry`/`SOURCE_CONFIG` and validates a declared `workflows.approve.stages` list in the preflight. |
| `aidw/runner.py` | Modified | Comment-only: the E4.3 `_REASON_REPO_ADDED`/`_REASON_DISABLED` header now says `enabled: false`/repo-added stages are preflight-validated by E4.5a while their planning stays deferred to E4.5b. Warnings themselves unchanged. |
| `tests/test_stage_registry.py` | Modified | Adds validator tests: static-list acceptance, disabled/removed/moved repo-optional, repo-added stages, core-disable rejection, loop-stage rejection (disabled vs declarable), one-error reorder, no removal/reorder blending, one removal per core id, one duplicate per core id, unknown workflow, loader-error skipping, purity, and an exhaustive core-order sweep. |
| `tests/test_implement_workflow.py` | Modified | Updates `test_dry_run_renders_a_repo_declared_prompt_override` to declare the full six-id list (the override rides on I3), and adds the `_declared_implement_stages` helper plus tests for a disabled core stage (exit 2, `--dry-run` included, no side effects) and a disabled repo-optional stage passing. |
| `tests/test_prompt_workflow.py` | Modified | Adds the disabled-core-`P1` preflight test (exit 2 before any run record/worktree). |
| `tests/test_review_workflow.py` | Modified | Adds the disabled-core-`R2` publisher preflight test. |
| `tests/test_fix_workflow.py` | Modified | Adds the disabled-core-`A1` approver preflight test. |
| `tests/test_approve_workflow.py` | Modified | Adds the disabled-core-`A1` approver preflight test. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E4.5a complete. |
| `docs/task-prompts/00-E4.5a-prompt.md` | Created | The task prompt (committed earlier on the branch). |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.66ms` (already locked and synced) |
| Build | `uv build --out-dir <tmp>` | ✅ gate `build` passed — built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` |
| Test | `uv run --frozen pytest` | ✅ gate `suite` passed — `1163 passed in 22.39s` |
| Doctor | `uv run --frozen aidw doctor` | ✅ `19 checks: 0 failed, 2 warning(s)` (warnings: branch `00-E4.5a` dirty working tree; missing `.mcp.json`) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` |
| Whitespace | `git diff --check` | ✅ clean (exit 0) |
| Lint | — | **unverified** (no lint gate exists in this repo: `AGENTS.md` §"Gates" and `design.md` §15 state pytest is the only verification — no linter, formatter or type-checker is configured) |

`build` and `suite` were executed in this stage against tree `cf9746549fa1` (no reused outcome from an
earlier stage), with the declared scope
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.
The recorded outcome lines were:

- `passed: gate 'build' passed for tree cf9746549fa1 at 2026-11-04T08:21:03Z by stage 'record-implementation-results' (Successfully built /var/folders/…/aidt-0.1.0-py3-none-any.whl) [scope excludes: docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks]`
- `passed: gate 'suite' passed for tree cf9746549fa1 at 2026-11-04T08:21:28Z by stage 'record-implementation-results' (1163 passed in 22.39s) [scope excludes: docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks]`

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1163 | ✅ Pass (`1163 passed in 22.39s`) |
| `tests/test_stage_registry.py` | 66 collected | ✅ Pass — part of the full-suite run above (collection count only, no second execution) |
| `tests/test_implement_workflow.py` | 55 collected | ✅ Pass — part of the full-suite run above (collection count only, no second execution) |
| `tests/test_prompt_workflow.py` | 155 collected | ✅ Pass — part of the full-suite run above (collection count only, no second execution) |
| `tests/test_review_workflow.py` | 17 collected | ✅ Pass — part of the full-suite run above (collection count only, no second execution) |
| `tests/test_fix_workflow.py` | 21 collected | ✅ Pass — part of the full-suite run above (collection count only, no second execution) |
| `tests/test_approve_workflow.py` | 13 collected | ✅ Pass — part of the full-suite run above (collection count only, no second execution) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `validate_stage_list` accepts every workflow's own static list and exactly the core stages in registry order | ✅ passed in the full-suite run |
| `validate_stage_list` accepts a disabled, removed or moved repo-optional stage, and a repo-added stage at any position | ✅ passed in the full-suite run |
| `validate_stage_list` rejects disabling a core stage — one `ERROR` naming the id and `core stage cannot be disabled` | ✅ passed in the full-suite run |
| `validate_stage_list` rejects a declared loop stage: `core stage cannot be disabled` when `enabled: false`, else `loop stages are generated by \`expand\`, not declarable` | ✅ passed in the full-suite run |
| `validate_stage_list` reports one reorder `ERROR` for a reordered core list, naming both orders, and does not blend removal into reorder | ✅ passed in the full-suite run |
| `validate_stage_list` reports one removal per core stage for `stages: []` and one duplicate per duplicated core id | ✅ passed in the full-suite run |
| `validate_stage_list` raises `UnknownWorkflowError`, skips loader-refused entries, is pure (no filesystem access) and does not mutate its input | ✅ passed in the full-suite run |
| `REPO_OPTIONAL_IDS` is exactly traceability (`I3`) and architecture (`I4`) | ✅ passed in the full-suite run |
| `implement`: disabling core `I5` returns 2 with `workflows.implement.stages`, the stage id and the rule on stderr, before any stage/run record/worktree, in `--dry-run` and normally | ✅ passed in the full-suite run |
| `implement`: disabling repo-optional `I3` passes the preflight and runs the default order | ✅ passed in the full-suite run |
| `prompt`: disabling core `P1` returns 2 before any run record/worktree | ✅ passed in the full-suite run |
| `review`: disabling core `R2` (publisher) returns 2 before any side effect | ✅ passed in the full-suite run |
| `fix` and `approve`: disabling core `A1` returns 2 before any side effect | ✅ passed in the full-suite run |
| Updated `test_dry_run_renders_a_repo_declared_prompt_override` declares the full six-id list with I3's `prompt:` override | ✅ passed in the full-suite run |
| `stage_registry` still imports no I/O or workflow module (`test_the_registry_module_imports_no_io_or_workflow_module`) | ✅ passed in the full-suite run |
| `runner.py` change is comment-only (`_REASON_*` warnings unchanged) | ✅ verified by inspection of `git diff` |

---

## Deviations observed during recording

- **The task prompt's generic `pnpm` gate commands do not apply to this repository** — this repo is
  Python/uv (`pyproject.toml` + `uv.lock`). Per `prompts/pr.md`'s stack table and `AGENTS.md`, the
  gates run were `uv sync --frozen`, `uv build`, `uv run --frozen pytest`, `uv run --frozen aidw
  doctor`, `uv run --frozen aidw agents validate --strict` and `uv run --frozen aidw prompts check`.
- **No lint gate exists** — `AGENTS.md` §"Gates" states pytest is the only verification and no
  linter/formatter/type-checker is configured, so no `lint` gate key was recorded.
- **No `aidw gate run` reuse occurred** — both gated commands were executed in this stage against tree
  `cf9746549fa1`; no `reused:` line was observed.

---

## Non-Goals (NOT implemented)

- ❌ E4.5b — planning the shapes E4.5a accepts: repo-added `StageSpec` construction, `plan_stages` raising a named `StageRegistryError`, honouring `enabled: false` in the plan, and the three fixed-arity consumer rewrites (`review`'s `r1, r2 =`, `approve`'s `(spec,) =`, `implement`'s `plan[:-1]/plan[-1]`) (task prompt, "Explicit non-goals")
- ❌ Changing `plan_stages`/`_stage_prompt_overlays` in `runner.py`, or validating repo-added stage fields (agent exists, prompt resolves) (task prompt, "Explicit non-goals")
- ❌ E4.6 agent/model/thinking/timeout overrides and E4.7 the fixture integration test (task prompt, "Explicit non-goals")
- ❌ Adding `validate_stage_list` to `aidw doctor` or `aidw config show` — preflights only (task prompt, "Explicit non-goals")
- ❌ Committing, pushing, or opening a PR — `aidt/prompts/pr.md` owns that (record stage scope)
