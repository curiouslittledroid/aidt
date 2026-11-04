# Build Results — 00-E4.5b: Plan the shapes E4.5a accepts

**Branch:** `00-E4.5b`
**Date:** 2026-11-04
**Spec:** `docs/migration/EXTRACTION.md` §2 (D12/D13), §3.4, §3.5, §3.6; `design.md` §3, §8.2, §8.3, §8.5

## Summary

**Purpose:** Turn a repo-declared `workflows.<name>.stages` list that E4.5a accepts into a run-path plan the five workflows execute, so a permitted repo-added stage plans and runs without tripping the fixed-arity assumptions of `review`, `approve` and `implement`.

| Decision | Why it matters |
|----------|---------------|
| `plan_stages` refuses a declared list the validator rejects by raising a named `StageListError` carrying `format_issues` text | A direct caller (`aidw exec`, tests) never gets a silently shortened or reordered plan just because the preflight was expected to have run first. |
| Static-vs-loop split is **by stage id** (`stages_by_id − definition.stages`), never a `len(definition.stages)` slice | `review`'s `R2` is `when=findings`, so `expand`'s static half is one or two stages; a count slice would misclassify a loop stage. |
| Declared static entries are built in declared order; the registry's loop portion is appended unchanged | A declared list replaces the toolkit's static half wholesale (§3.4), while the `⟳` loop stays the registry's. |
| Repo-added stage gets the full `StageSpec` contract, with its declared `agent` honoured as `agent_id` and its prompt resolved at §3.6 with `name=declared_id` | This is the only field source a repo-added stage has; resolving by declared id makes `<target>/aidw/prompts/<id>.md` shadow correctly, and `prompt:` resolves against the **target** root. |
| A shared `declared_stage_issues` helper converts missing prompts and unknown repo-added agents into config `ERROR`s, wired once per preflight immediately after `load_all` | `resolve_prompt`'s `FileNotFoundError` and `run_stage`'s `ValueError: unknown agent` must be refused at exit 2 before any run record or worktree, with no local call-site `except`. The agents dict does not exist at the `validate_stage_list` site, so it cannot live there. |
| `review`/`approve`/`implement` consumers locate their fixed stages **by id** and iterate the plan in declared order; `prompt`/`fix` keep name-keyed consumption and warn about a repo-added entry | Removes every "R1,R2 unpack", "A1 first" and "I6 is last" assumption, while the two name-keyed consumers honestly warn rather than silently dropping an accepted declaration (their consumer rewrite is a non-goal). |

**Where it fits in the roadmap:** The second half of the former E4.5, directly after E4.5a (which owns the `validate_stage_list` rules/messages this task calls and raises on). It unblocks E4.6 (per-stage agent/model/thinking/timeout overrides — the surviving deferred `agent` warning on known ids) and E4.7 (the fixture integration test over the six end-to-end behaviours). The three fixed-arity consumers (`review`, `approve`, `implement`) are rewritten here; `prompt`/`fix` consumer rewrites are deliberately not.

**Scope:** `aidw/runner.py` (plan construction, repo-added specs, the shared preflight helper, deferred-warning split), `aidw/stage_registry.py` (the `StageListError` subclass plus docstring truth), the five workflow preflights and the three fixed-arity consumers, and their tests. It deliberately stops short of running repo-added stages in `prompt`/`fix` (they warn), of the E4.6 agent/model/thinking/timeout overrides, of changing `validate_stage_list`'s rules or messages, and of the E4.7 fixture integration test.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/implementation-results/00-E4.5b/build-results.md` | Created | This recording document. |
| `aidw/runner.py` | Modified | Build the static half from a declared list in declared order, the `enabled: false` omission and the repo-added `StageSpec` contract; append the by-id loop portion; raise `StageListError`; add `declared_stage_issues` for missing prompts and unknown repo-added agents; update the deferred-warning reasons. |
| `aidw/stage_registry.py` | Modified | Add the named `StageListError(StageRegistryError)` subclass; update the module docstring to state that E4.5b plans the accepted shapes. |
| `aidw/workflows/review.py` | Modified | Replace the `r1, r2 = plan_stages(...)` unpack with id-based lookup; dry-run and real paths iterate the full plan in declared order with §8.3 gating and stops intact; wire the per-entry preflight helper after `load_all`. |
| `aidw/workflows/approve.py` | Modified | `_planned_stage` returns the ordered spec list with `verify` attached to A1 only (located by id); `run()` iterates it linearly in both dry-run and real paths; wire the helper after `load_all`. |
| `aidw/workflows/implement.py` | Modified | Locate I6 by id for the pre-PR/PR split; make `index_of`/`by_name`, serial and `--parallel` scheduling cover every pre-I6 stage at full-plan positions; I6's `should_run` uses its own plan index; post-I6 stages run after a successful-or-resumed I6; wire the helper after `load_all`. |
| `aidw/workflows/prompt.py` | Modified | Wire the per-entry preflight helper after `load_all`; a repo-added stage keeps the not-run warning and never executes. |
| `aidw/workflows/fix.py` | Modified | Wire the helper once at the control-root `load_all` site only (not the worktree reload); repo-added stages warn and never run. |
| `tests/test_plan_stages.py` | Modified | Construction of repo-added specs (explicit `prompt:` and `<id>.md` shadow), `enabled: false` omission, loop-after-static for `prompt`, byte-identical pure defaults; `StageListError` refusals for core `enabled: false`, reordered list, `stages: []` and a declared loop id; purity and missing-prompt fail-closed. |
| `tests/test_review_workflow.py` | Modified | Repo-added review stages plan and run in declared order (between R1/R2 and after R2) on the findings path, and are skipped with the existing Approve/stop exit when R1 approves with no findings. |
| `tests/test_approve_workflow.py` | Modified | The full approve plan runs in declared order with `verify` on A1 only. |
| `tests/test_implement_workflow.py` | Modified | PR split still targets I6 with a trailing repo-added stage (which runs after I6, after a successful/resumed I6, never after a denied gate), and a pre-I6 repo-added stage schedules and skips-on-resume identically to a core stage in serial and `--parallel` modes. |
| `tests/test_prompt_workflow.py` | Modified | Preflight refuses exit 2 (no traceback) on a missing prompt / unknown repo-added agent; an accepted repo-added stage draws the not-run warning naming it and never executes. |
| `tests/test_fix_workflow.py` | Modified | Same preflight refusals and accepted-but-not-run behaviour as `prompt`. |
| `docs/tasks/00 - Extraction.md` | Modified | Tick E4.5b in the roadmap (traceability update owned by the prior stage). |

---

## Verification Results

All commands were run through `aidw gate run` with the same scope —
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` —
and every row below reports this run's own outcome for tree `0e95afeab576` at
2026-11-04T10:39Z, stage `record-implementation-results`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 15 packages in 0.34ms`) |
| Build | `uv build --out-dir <tmp>` | ✅ Pass (`Successfully built aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl`) |
| Test | `uv run --frozen pytest` | ✅ Pass (`1209 passed in 28.05s`) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`19 checks: 0 failed, 2 warning(s)` — warnings are the dirty working tree and the absent `.mcp.json`, both expected mid-run) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (`prompts check: 0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (no output) |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1209 | ✅ Pass (`1209 passed in 28.05s`) |

The task-specific proofs live in the changed test modules and ran inside this single suite
invocation (no subset was re-run to obtain a count): `tests/test_plan_stages.py` (construction,
refusal via `StageListError`, purity), `tests/test_review_workflow.py`, `tests/test_approve_workflow.py`
and `tests/test_implement_workflow.py` (repo-added stages plan and run, R2 gated on findings,
`verify` on A1 only, I6 split with leading/trailing repo-added stages in serial and `--parallel`),
and `tests/test_prompt_workflow.py` / `tests/test_fix_workflow.py` (preflight exit 2 on a missing
prompt or unknown agent, accepted-but-not-run warning).

### Task-specific verification gates

| Gate | Status |
|------|--------|
| A repo-added stage in `review`/`approve`/`implement` plans and runs without an unpack `ValueError` | ✅ Covered by the suite run above (`1209 passed`) |
| Disabled core stage / reordered core list refuse exit 2; direct `plan_stages` raises `StageListError` | ✅ Covered by the suite run above |
| Missing declared prompt and unknown repo-added agent refused exit 2 in every preflight, no traceback from `run()` | ✅ Covered by the suite run above |
| Untouched E4.5a validator tests still green | ✅ Covered by the suite run above |
| Exact `AGENTS.md` gate set (sync/test/doctor/agents/prompts) | ✅ All five passed as recorded above |

---

## Non-Goals (NOT implemented)

- ❌ E4.6 agent/model/thinking/timeout overrides — `agent` stays a deferred warning on known ids; a repo-added stage's `agent` is only existence-checked (task prompt, explicit non-goals).
- ❌ E4.7 the fixture integration test (six behaviours end-to-end) — separate task.
- ❌ `prompt.py`/`fix.py` repo-added *running* — they keep name-keyed consumption and warn (req 2's surviving `_REASON_REPO_ADDED` line), never silently drop.
- ❌ No changes to `validate_stage_list`'s rules or messages — E4.5a owns them; this task only calls and raises.
- ❌ No PR opened and nothing committed/reverted by the recording stage (`prompts/pr.md` owns delivery).
