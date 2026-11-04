# Build Results — 00-E4.4: `parallel_groups`

**Branch:** `00-E4.4`
**Date:** 2026-11-04
**Spec:** `docs/migration/EXTRACTION.md` §3.5 (stage and workflow model — the `parallel_groups` rule, stage-name vs id vocabulary, R6), §3.4 (target-repo config — the `workflows.<name>.parallel_groups` shape), §2 (locked decisions D2, D4, D12, D13, D14), §10 (R11), §3.12 (directory layout); `design.md` §8.2 (`aidw implement`, `--parallel` I2/I4 semantics, disjoint file sets, run-state writes serialized by a lock) and §3 (layout)

## Summary

**Purpose:** Replace `aidw implement`'s hardcoded `[test, update-architecture]` pair with the target config's resolved `workflows.implement.parallel_groups`, and validate those groups in the preflight so a broken list fails closed before any run record or worktree.

**Key design decisions**

| Decision | Why it matters |
|----------|---------------|
| Declared-ness, not value equality, selects the groups: `config.get("workflows.implement.parallel_groups") is None` → registry default; `source == SOURCE_CONFIG` → the declared value verbatim, including an explicit `[]` | `resolve_config` omits an undeclared entry entirely and carries `source=config` for `[]`; testing "non-empty" would silently fall back to the default pair when a repo declares "no parallel groups". |
| All non-member stages are derived from the registry order (`pre_pr`) and each group runs at the position of its **earliest** member; the hardcoded tail is gone | Generalizing only the pair would leave `("update-traceability", "record-implementation-results")` hardcoded, re-creating the problem the task removes. Earliest-member placement preserves the documented I1 → {I2, I4} → I3 → I5 → I6 schedule, including the non-adjacent default pair. |
| `validate_parallel_groups(workflow, groups)` is a pure registry helper taking the **effective** groups, importing only `aidw.config` for `Issue`/`ERROR` | Keeps `stage_registry.py` free of I/O and workflow/target-config imports (its stated dependency direction), while letting `implement`'s preflight render group errors through the same `format_issues` as every other config refusal. |
| "Not ordered against one another" is implemented as the two rejections a single-trigger scheduler cannot honour: a duplicate within one group and a member shared across groups; an empty inner group is an error, an empty list of groups is not | The spec fixes the rule, not the mechanism (R11 forbids inferring safety); a group with no members has no schedulable position. File-ownership safety, adjacency and the semantic `test`→`update-traceability` order stay unvalidated by design. |
| Group validation runs in the preflight immediately after `resolve_workflow_config`, on the effective groups, before run state and in `--dry-run` | A broken config is broken regardless of `--parallel`; exit 2 with the same stderr contract as the existing config refusals. |
| A failed group member records `resume={"next_stage": <earliest failed member in registry order>}` | The pool completes out of order; deriving the resume hint from registry order keeps it deterministic instead of depending on which future finished first. |

**Where it fits in the roadmap:** Phase E4 (config-driven orchestrator). It consumes E4.1's registry `parallel_groups` data and E4.3's `resolve_workflow_config`/`plan_stages` run path. E4.5 (core-vs-repo-optional enforcement), E4.6 (agent/model overrides) and E4.7 (the six-behaviour fixture integration test) are separate and unaffected.

**Scope:** Only the schedule-selection and validation path of `aidw implement`: effective-group resolution, the generalized `--parallel` scheduler, `validate_parallel_groups` in the registry plus its preflight call, corrected module documentation, and the tests that pin all of it. The task deliberately stops short of constraining how groups combine with the config's `stages:` list, and leaves `ConfigDefaults.workflows`/`resolve_config` untouched.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/implementation-results/00-E4.4/build-results.md` | Created | This results document. |
| `docs/task-prompts/00-E4.4-prompt.md` | Created | The task prompt (committed earlier on the branch). |
| `aidw/stage_registry.py` | Modified | Adds the pure `validate_parallel_groups` validator (`Issue`/`ERROR`, no I/O) and rewrites the module docstring's dependency-direction sentence to name both leaf imports (`aidw.findings`, `aidw.config`); updates the `parallel_groups` data comments. |
| `aidw/workflows/implement.py` | Modified | Adds `effective_parallel_groups` and `PARALLEL_GROUPS_PATH`; rewrites the `if parallel:` block to schedule the resolved groups at each group's earliest member with a registry-order tail; runs group validation in the preflight (exit 2); replaces the stale `--parallel` module docstring. |
| `tests/test_stage_registry.py` | Modified | Adds validator tests (default, `[]`, unknown member, semantic-id rejection, empty inner group, duplicate within a group, cross-group member, unknown workflow, purity/no-mutation) plus a 1600-case exhaustive property sweep; updates the import-allowlist test for `aidw.config`. |
| `tests/test_implement_workflow.py` | Modified | Adds `_write_config`/`DEFAULT_ORDER` helpers, parameterizes `_TrackingStages.slow`, and adds tests for absent-vs-declared-empty resolution, a configured group replacing the default pair, earliest-member placement, explicit `[]` → serial, a group naming `pr`, member-failure resume hint, and fail-closed unknown/empty-group preflight (including `--dry-run`). |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E4.4 complete. |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 2ms` (already locked and synced) |
| Build | `uv build --out-dir <tmp>` | ✅ gate `build` passed — built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` |
| Test | `uv run --frozen pytest` | ✅ gate `suite` passed — `1142 passed in 27.97s` |
| Doctor | `uv run --frozen aidw doctor` | ✅ `19 checks: 0 failed, 2 warning(s)` (warnings: branch `00-E4.4` dirty working tree; missing `.mcp.json`) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` |
| Whitespace | `git diff --check` | ✅ clean (exit 0) |

`build` and `suite` were executed in this stage against tree `590c2f9b7cd9` (no reused outcome from an
earlier stage), with the declared scope
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.
The recorded outcome lines were:

- `passed: gate 'build' passed for tree 590c2f9b7cd9 at 2026-11-04T00:36:15Z by stage 'record-implementation-results' (Successfully built …/aidt-0.1.0-py3-none-any.whl) [scope excludes: docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks]`
- `passed: gate 'suite' passed for tree 590c2f9b7cd9 at 2026-11-04T00:36:07Z by stage 'record-implementation-results' (1142 passed in 27.97s) [scope excludes: docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks]`

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1142 | ✅ Pass (`1142 passed in 27.97s`) |
| `tests/test_stage_registry.py` | 52 collected | ✅ Pass — part of the full-suite run above (collection count only, no second execution) |
| `tests/test_implement_workflow.py` | 52 collected | ✅ Pass — part of the full-suite run above (collection count only, no second execution) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Default pair still runs concurrently, followed by the ordered I3 → I5 → I6 tail (`test_parallel_runs_test_and_architecture_concurrently`) | ✅ passed in the full-suite run |
| Serial path still runs the pair one at a time (`test_serial_runs_the_pair_one_at_a_time`) | ✅ passed in the full-suite run |
| A target config's `parallel_groups: [["test", "record-implementation-results"]]` runs those two concurrently (`max_active == 2`) and `update-architecture` serially | ✅ passed in the full-suite run |
| A group runs at the position of its earliest member, not its first-listed member | ✅ passed in the full-suite run |
| `parallel_groups: []` with `--parallel` runs every stage serially (`max_active == 1`, registry order) | ✅ passed in the full-suite run |
| A group naming `pr` leaves `pr` alone in its post-gate slot | ✅ passed in the full-suite run |
| A group member failure → exit 1, no later stage, `resume.next_stage` set to the earliest failed member in registry order | ✅ passed in the full-suite run |
| Unknown member and empty inner group → exit 2, stderr names path/group/member, no worktree or run state (also under `--dry-run`) | ✅ passed in the full-suite run |
| `validate_parallel_groups` accepts the default and `[]`; rejects unknown/duplicate/cross-group/empty-group; is pure and non-mutating; exhaustive 1600-case equivalence sweep | ✅ passed in the full-suite run |
| Hardcoded `pair = [...]` and the hardcoded traceability/record tail removed from `implement.py` | ✅ verified by inspection of `git diff` (only registry-derived scheduling remains) |

---

## Deviations observed during recording

- **The task prompt's generic `pnpm` gate commands do not apply to this repository** — this repo is
  Python/uv (`pyproject.toml` + `uv.lock`). Per `prompts/pr.md`'s stack table and `AGENTS.md`, the
  gates run were `uv sync --frozen`, `uv build`, `uv run --frozen pytest`, `uv run --frozen aidw
  doctor`, `uv run --frozen aidw agents validate --strict` and `uv run --frozen aidw prompts check`.
- **No lint gate exists** — `AGENTS.md` §"Gates" states pytest is the only verification and no
  linter/formatter/type-checker is configured, so no `lint` gate key was recorded.
- **No `aidw gate run` reuse occurred** — both gated commands were executed in this stage; no
  `reused:` line was observed.

---

## Non-Goals (NOT implemented)

- ❌ E4.5 core-vs-repo-optional enforcement (D12/D13 reorder/disable refusals, `enabled: false`, repo-added stages) — separate; this task only validates group members against the default stage names.
- ❌ E4.6 agent/model/thinking/timeout overrides — separate.
- ❌ E4.7 the six-behaviour fixture integration test against `fixtures/target-repo/` — separate (its parallel assertion uses `update-architecture`, not `architecture`).
- ❌ Adding `parallel_groups` validation to `aidw doctor` — out of scope; only `implement`'s preflight calls the validator today.
- ❌ Changing `ConfigDefaults.workflows` / `resolve_config` output — the field already parses and resolves (E3.1).
- ❌ Validating file-ownership safety, adjacency, or the semantic `test`→`update-traceability` dependency (R11/§8.2 leave these to the repo's declaration).
- ❌ Changing `--parallel`'s CLI help in `aidw/cli.py`.
- ❌ Committing, pushing, or opening a PR (`aidt/prompts/pr.md` owns that).
