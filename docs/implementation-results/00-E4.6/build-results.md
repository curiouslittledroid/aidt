# Build Results — 00-E4.6: Agent and model overrides

**Branch:** `00-E4.6`
**Date:** 2026-11-04
**Spec:** `docs/migration/EXTRACTION.md` §2 (D12), §3.4, §3.12; `design.md` §3, §5.1, §5.4, §17

## Summary

**Purpose:** Allow a target repo to override a stage's `agent`/`model`/`thinking`/`timeout_seconds`
— per stage, and globally through an agent-config directory — while every repo without overrides
keeps the toolkit's `agent-configs/` defaults unchanged.

| Decision | Why it matters |
|----------|---------------|
| The three new stage keys are validated on load and a bad value is dropped with the dotted field path | `thinking` reuses `aidw/config.py:THINKING_LEVELS`, `timeout_seconds` must be a positive int and `model` a non-empty string, so a refused config can never resolve into a half-applied override. |
| `paths.agent_configs_dir` is a read-path that is **unset, not defaulted** | Its consumer falls back to `<toolkit>/agent-configs/`; seeding a repo-relative value would make every repo without that folder fail `validate_paths`. |
| `load_all` loads the override directory **before** `check_independence`/`check_read_only`, shadowing by `id` | A repo that makes `implementer` equal `code-reviewer` through an override must draw the §5.4 warning for the values actually used; brand-new ids are additive and an empty directory equals the toolkit defaults. |
| `run_stage` applies the stage metadata with one `dataclasses.replace` before any consumer reads `agent.model` | `build_argv`, `execute(timeout=…)`, `StageRecord(model=…)`, `write_meta`, logging and progress all see the same effective model, so argv, run state and cost cannot disagree. |
| A per-stage `model` replaces `model` only, never `provider`; the `provider/model` split stays `model_name`/`qualified_model` | D12's override surface and the §3.4 stage entry have no `provider` key. A bare slug or vendor-namespace slug rides the base `--provider`; the record carries the effective config's qualified model. |
| A declared `agent` on a **known** stage is existence-checked in preflight | An unknown id refuses exit 2 with the config error, instead of reaching `run_stage`'s `ValueError: unknown agent` traceback. |
| Per-stage `model`/`thinking`/`timeout_seconds` are **not** re-run through §5.4 | §5.4 is a load-time check on the shadowed agent dict; a per-stage override is an explicit operator choice recorded in argv and `state.json`, like `--force-model`. |

**Where it fits in the roadmap:** E4.6 completes the override surface opened by E4.5b (which made
repo-added stages plan and carried the declared `agent` as `agent_id`) and depends on E3.1's stage
entry schema and E3.7's read-path validation. It unblocks E4.7, the fixture integration test over
the six end-to-end behaviours, which seeds its own overrides in `fixtures/target-repo/`.

**Scope:** `aidw/target_config.py` (stage keys, `StageConfig`/`PathsConfig`, read-path and override
resolution), `aidw/config.py` (`load_all` override directory and shadow-by-id), `aidw/runner.py`
(planned specs, preflight agent existence, effective agent), the five workflow preflights and their
worktree reloads, the schema/docs mirrors, `design.md` §17 and their tests. It proves the behaviour
with unit/tmp fixtures and dry-run argv assertions; it deliberately stops short of E4.7's fixture
integration test, `--force-model`, the E4.4/E4.5a stage-list rules, editing the eleven toolkit agent
defaults, and neutralising `agents/*/AGENTS.md`.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/implementation-results/00-E4.6/build-results.md` | Created | This recording document. |
| `docs/task-prompts/00-E4.6-prompt.md` | Modified | Add the task prompt (committed by the prompt-authoring stage). |
| `aidw/target_config.py` | Modified | Add `model`/`thinking`/`timeout_seconds` to `STAGE_KEYS` and `StageConfig` with per-key validation and declared-only round-trip; add `agent_configs_dir` to `PATH_FIELDS`, `PathsConfig` and `READ_PATHS`; add `agent_configs_override` and keep the default unset. |
| `aidw/config.py` | Modified | Add the optional `override_dir` to `load_all`, load each directory through `_load_agent_dir`, shadow by `id`, keep un-overridden toolkit agents, allow additive ids, and error on a named-but-missing directory before the independence/read-only checks. |
| `aidw/runner.py` | Modified | Carry the three metadata overrides on `StageSpec`, honour a known stage's declared `agent`, existence-check it in `declared_stage_issues`, remove `_REASON_AGENT` while keeping the `prompt`/`fix` repo-added warning, and apply the effective agent once in `run_stage`. |
| `aidw/workflows/implement.py` | Modified | Pass the resolved `agent_configs_override` to `load_all` at the control root and the worktree reload. |
| `aidw/workflows/review.py` | Modified | Pass the resolved override directory at the preflight and the PR-head worktree reload. |
| `aidw/workflows/fix.py` | Modified | Pass the resolved override directory at the control root and the worktree reload. |
| `aidw/workflows/approve.py` | Modified | Pass the resolved override directory to `load_all` in the preflight. |
| `aidw/workflows/prompt.py` | Modified | Pass the resolved override directory to `load_all` at the control root and the worktree reload. |
| `docs/schema/aidw-config.schema.json` | Modified | Add the three stage properties and `paths.agent_configs_dir`, still under `additionalProperties: false`. |
| `docs/target-repo-config.md` | Modified | Document the three stage fields, the `paths.agent_configs_dir` inventory row and `Full` example, precedence, and replace the "not stage fields" sentence. |
| `design.md` | Modified | Add decision row N1 to §17 recording the prompt-fixed override choices. |
| `docs/tasks/00 - Extraction.md` | Modified | Tick E4.6 in the roadmap (traceability update owned by the prior stage). |
| `tests/test_target_config.py` | Modified | Accept and round-trip the stage overrides, reject bad values by field path, prove absent overrides never serialise as `null`, and cover `agent_configs_dir` default/declaration/target-root resolution. |
| `tests/test_target_repo_config_doc.py` | Modified | Flip the rejected-stage-key expectations to acceptance and keep the doc contract aligned with `STAGE_KEYS`/`PATH_FIELDS` and the `Full` example. |
| `tests/test_config.py` | Modified | Cover override shadow-by-id, additive ids, empty directory, missing directory error, independence/read-only on shadowed values, and relative-vs-absolute resolution. |
| `tests/test_plan_stages.py` | Modified | Cover known-stage and repo-added metadata overrides, a declared `agent` changing only that stage, and the surviving `prompt`/`fix` repo-added warning without the agent warning. |
| `tests/test_runner.py` | Modified | Cover dry-run argv and recorded model for bare/qualified overrides, thinking/timeout on the effective agent, state/meta/log consistency, un-overridden siblings, known-stage agent refusal, and global-then-per-stage precedence. |
| `tests/test_implement_workflow.py` | Modified | Cover the named-but-missing override directory refusal before worktree lookup and an unknown agent on a known stage. |
| `tests/test_cli.py` | Modified | Add `paths.agent_configs_dir` to the config leaf list and the unset leaves. |
| `tests/test_approve_workflow.py` | Modified | Accept the new `load_all` keyword in the fake. |
| `tests/test_fix_workflow.py` | Modified | Accept the new `load_all` keyword in the fakes. |
| `tests/test_prompt_workflow.py` | Modified | Accept the new `load_all` keyword in the fake. |
| `tests/test_review_workflow.py` | Modified | Accept the new `load_all` keyword in the fakes. |

---

## Verification Results

The build, suite, doctor, agents and prompts gates were run through `aidw gate run` with the same scope —
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` —
and every row below reports this run's own outcome for tree `01e60de7421b`, stage
`record-implementation-results`, on 2026-11-04; `uv sync --frozen` and `git diff --check` were run
directly (neither is a recorded gate). Re-running the same key/command/scope after writing this
document is expected to reuse the recorded outcomes, because the document lies inside the declared
scope.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 15 packages in 0.56ms`) |
| Build | `uv build --out-dir <tmp>` | ✅ Pass (gate `build`: `Successfully built aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl`) |
| Test | `uv run --frozen pytest` | ✅ Pass (gate `suite`: `1246 passed in 30.42s`) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (gate `doctor`: `19 checks: 0 failed, 2 warning(s)` — the dirty working tree and absent `.mcp.json`, both expected mid-run) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (gate `agents`: `11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (gate `prompts`: `prompts check: 0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (no output) |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1246 | ✅ Pass (`1246 passed in 30.42s`) |

The task-specific proofs live in the changed test modules and ran inside this single suite
invocation (no subset was re-run to obtain a count): `tests/test_target_config.py`,
`tests/test_target_repo_config_doc.py`, `tests/test_config.py`, `tests/test_plan_stages.py`,
`tests/test_runner.py`, `tests/test_implement_workflow.py`, and the `load_all`-signature updates in
the approve/fix/prompt/review workflow tests and `tests/test_cli.py`.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| A declared per-stage/global model changes the rendered Pi argv while the un-overridden sibling keeps the toolkit model | ✅ Covered by the suite run above (`tests/test_runner.py`) |
| Stage `thinking`/`timeout_seconds` apply to the effective agent for that invocation only | ✅ Covered by the suite run above (`tests/test_runner.py`) |
| Bad `thinking`/`timeout_seconds`/empty `model` fail with the dotted field path; absent overrides do not serialise as `null` | ✅ Covered by the suite run above (`tests/test_target_config.py`) |
| Schema JSON and `docs/target-repo-config.md` agree with `STAGE_KEYS` and `PATH_FIELDS` | ✅ Covered by the suite run above (`tests/test_target_repo_config_doc.py`, `tests/test_cli.py`) |
| Global override dir shadows by id, keeps un-overridden agents, is additive, treats an empty dir as defaults, and errors when named-but-missing | ✅ Covered by the suite run above (`tests/test_config.py`, `tests/test_implement_workflow.py`) |
| Independence/read-only checks run on the shadowed dict | ✅ Covered by the suite run above (`tests/test_config.py`) |
| A known stage's declared `agent` is honoured; an unknown one refuses exit 2 in preflight with no traceback | ✅ Covered by the suite run above (`tests/test_plan_stages.py`, `tests/test_runner.py`, `tests/test_implement_workflow.py`) |
| Exact `AGENTS.md` gate set (sync/test/doctor/agents/prompts) | ✅ All five passed as recorded above |

---

## Deviations observed during recording

- **The generic record prompt names a pnpm gate set, but this repo's stack is Python/uv.** Per
  `AGENTS.md` and `prompts/pr.md` ("take them from the target repo, not from this prompt"), the
  install/build/test rows are `uv sync --frozen`, `uv build` and `uv run --frozen pytest`, and no
  lint gate was run because the repo configures no linter.
- **`uv build` writes to a fresh `$(mktemp -d)` directory** rather than the working tree, so the
  recorded build row leaves no artifacts to clean up.

---

## Non-Goals (NOT implemented)

- ❌ E4.7's fixture integration test (six behaviours end-to-end against `fixtures/target-repo/`) — separate task; `fixtures/target-repo/` is untouched (task prompt, explicit non-goals).
- ❌ `--force-model` (design §5.4 workflow-level independence refusal) — a different mechanism; untouched.
- ❌ `parallel_groups`, `validate_stage_list`, and reorder/disable rules — E4.4/E4.5a own them; this task only honours the fields it adds.
- ❌ Editing the eleven toolkit `agent-configs/*.yaml` defaults — they are the defaults; neutralising `agents/*/AGENTS.md` is E7.4.
- ❌ No PR opened and nothing committed by the recording stage (`prompts/pr.md` owns delivery).
