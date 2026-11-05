# Build Results — 00-E6.1: Move markers and labels into resolved config

**Branch:** `00-E6.1`
**Date:** 2026-11-05
**Spec:** `docs/migration/EXTRACTION.md` §3.9 (persisted GitHub contracts, freeze semantics D5), §3.4 (target-repo config, `github.markers`/`github.labels`), §2 (locked decision D5) and §3.12 (repo layout authority); `docs/task-prompts/00-E6.1-prompt.md`; `docs/tasks/00 - Extraction.md` E6.1

## Summary

**Purpose:** Make the frozen GitHub marker templates and label definitions resolved target-repo config whose defaults are byte-identical to today's persisted literals, and carry those resolved values from every aidw invocation to the bundled review-followup scripts through one JSON env handoff.

| Decision | Why it matters |
|----------|---------------|
| The frozen D5 literals live in **two homes** — `prompts/scripts/review-followup/constants.py` and `aidw/target_config.py:TOOLKIT_DEFAULTS.github` — pinned equal by a test | The wheel ships only the `aidw` package, so `target_config.py` must not import the copied scripts; keeping the merge unchanged means only the defaults' contents move. |
| The scripts receive **fully resolved** values in `AIDW_REVIEW_FOLLOWUP_CONFIG` (`{"markers", "labels"}`, JSON) | One stdlib-only channel keeps the standalone scripts independent of `aidw` while giving agent-invoked and aidw-direct runs the same contracts. |
| `gh.py` resolves and validates the handoff **once at import**, before any marker renders, and fails closed on invalid JSON/missing fields/unrenderable templates | Publishing a wrong marker or label violates D5: parent lookup is exact-match, so a silent fallback would orphan issues and create duplicates. |
| Comment bodies and role label names stay in `constants.py`; `PUBLISHER_LABELS` stays the frozen five-name tuple | §3.4 has no field for them and D5 freezes the names; deriving publisher obligations from config keys would make a repo-added label a publisher obligation. |
| Every workflow threads its single preflight `ResolvedConfig` through optional `config=` keywords to `run_stage` and the bundled-script runners | The publisher and `select` must agree on markers; setting the handoff at only one seam produces "No review-follow-up parent issue found". |

**Where it fits in the roadmap:** First task of epic E6 (GitHub contracts as config). It depends on E3.4's seeded defaults/`ResolvedConfig` walking and E4.8's stage-environment wiring, and supplies the data E6.2's preserve-matching-semantics tests and E6.3's authoritative `baseline-verbatim` golden consume. E6.2/E6.3/E6.4 remain separate tasks.

**Scope:** Adds the GitHub defaults, the env-var constant, the serializer, both env-handoff seams and the workflow call sites; extends the scripts' `gh.py` with config parsing and effective accessors and switches the two CLIs to them; flips the mechanical default-status cells in `docs/target-repo-config.md`; and updates the existing config/CLI/doc pins plus new toolkit and script config tests. It deliberately stops short of E6.2's matching-semantics suite, E6.3's baseline golden, E6.4's freeze narrative, a schema field for comment bodies/role names, and any change to the read-only `gh` helpers beyond the handoff.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E6.1-prompt.md` | Created | Task prompt added on the branch by the prompt-authoring stage. |
| `docs/implementation-results/00-E6.1/build-results.md` | Created | This recording document. |
| `prompts/scripts/review-followup/tests/test_github_config.py` | Created | Script-side tests for the absent/configured/broken handoff and fail-closed CLI behaviour; named `test_github_config.py` to avoid a pytest module-name collision with the toolkit's `tests/test_config.py`. |
| `aidw/paths.py` | Modified | Adds `REVIEW_FOLLOWUP_CONFIG_ENV_VAR` beside `SCRIPTS_DIR_ENV_VAR`. |
| `aidw/target_config.py` | Modified | Seeds `TOOLKIT_DEFAULTS.github.markers`/`.labels` with the frozen D5 values and updates the default/provenance documentation; the merge is unchanged. |
| `aidw/github.py` | Modified | Adds `serialize_github_config`, threads optional `config=` through `_run`/`run_script`/`select_followups`/`verify_approvals`, and composes the handoff env for bundled-script runs. |
| `aidw/runner.py` | Modified | Adds optional `config=` to `run_stage` and sets the handoff in the agent-invocation environment. |
| `aidw/workflows/review.py` | Modified | Passes the workflow's resolved config to its `run_stage` call(s). |
| `aidw/workflows/approve.py` | Modified | Threads `config=` through `_planned_stage`/`run` and the `verify_approvals` calls. |
| `aidw/workflows/fix.py` | Modified | Threads `config=` through `_approval_round`/`run` and the `select_followups`/`verify_approvals` calls. |
| `aidw/workflows/implement.py` | Modified | Passes the workflow's resolved config to `run_stage`. |
| `aidw/workflows/prompt.py` | Modified | Passes the workflow's resolved config to `run_stage`. |
| `prompts/scripts/review-followup/constants.py` | Modified | Exposes the three marker templates as frozen module literals and renders the existing accessors through keyed `.format`; no env/config parsing. |
| `prompts/scripts/review-followup/gh.py` | Modified | Owns the `AIDW_REVIEW_FOLLOWUP_CONFIG` parsing/validation and the effective `parent_marker`/`child_marker`/`summary_marker`/`LABEL_DEFINITIONS` accessors. |
| `prompts/scripts/review-followup/review_followup.py` | Modified | Takes effective markers/label definitions from `gh`; role names and `PUBLISHER_LABELS` still come from `constants`. |
| `prompts/scripts/review-followup/publish_review_followups.py` | Modified | Takes effective markers/label definitions from `gh`; role names and `PUBLISHER_LABELS` still come from `constants`. |
| `docs/target-repo-config.md` | Modified | Updates the GitHub default cells, the six label definitions and the toolkit-default/unset prose to the frozen defaults. |
| `tests/test_target_config.py` | Modified | Adds per-field default, override-precedence, purity and two-home equality assertions; updates the E3.4-era pins. |
| `tests/test_cli.py` | Modified | Updates `CONFIG_*` leaf sets and `github.markers.*`/`github.labels.*` provenance to `default`, including declared-override precedence. |
| `tests/test_target_repo_config_doc.py` | Modified | Derives `EXPECTED_DEFAULTS` markers/labels from `TOOLKIT_DEFAULTS`, adds the label leaves to `MINIMAL_PATHS`, and drops the old unset pins. |
| `tests/test_github.py` | Modified | Tests the serializer shape and the `select_followups`/`verify_approvals` env handoff; also asserts `config=None` does not inherit a stale handoff. |
| `tests/test_runner.py` | Modified | Tests the `run_stage` handoff env (declared override and `config=None`) and stale-inheritance removal. |
| `tests/test_approve_workflow.py` | Modified | Adjusts the expected call signature for the new `config=` keyword. |
| `tests/test_fix_workflow.py` | Modified | Adjusts the expected call signature for the new `config=` keyword. |

---

## Verification Results

Every recorded gate was run once through `aidw gate run`, with the same scope —
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` —
for tree `b1f5a5319820`, stage `record-implementation-results`, on 2026-11-05. The rows below report
this run's own outcomes; no suite, module or subset was re-run to obtain a count.
`uv sync --frozen` and `git diff --check` were run directly because neither is a recorded gate.
No lint gate was run because this repository configures no linter (AGENTS.md, design.md §15).

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 15 packages in 0.62ms`) |
| Build | `uv build --out-dir <tmp>` | ✅ Pass (gate `build`, tree `b1f5a5319820`, 2026-11-05T03:26:40Z: built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` in a fresh temporary directory) |
| Test | `uv run --frozen pytest` | ❌ Fail (gate `suite`, tree `b1f5a5319820`, 2026-11-05T03:27:10Z: `3 failed, 1379 passed in 26.57s`) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (gate `doctor`, tree `b1f5a5319820`, 2026-11-05T03:27:15Z: `19 checks: 0 failed, 2 warning(s)` — dirty working tree and absent `.mcp.json`, both expected mid-run) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (gate `agents`, tree `b1f5a5319820`, 2026-11-05T03:27:18Z: `11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (gate `prompts`, tree `b1f5a5319820`, 2026-11-05T03:27:19Z: `prompts check: 0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (no output) |

The environment printed a `VIRTUAL_ENV` mismatch warning for every `uv` invocation because
`/Users/phil/software-projects/aidt-workspace/main/.venv` differs from the project environment
path `.venv`; `uv` ignored it, and the commands themselves produced the outputs above.

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1382 | ❌ Fail (`3 failed, 1379 passed in 26.57s`; no deselections) |
| `tests/test_target_config.py` | not separately counted | ✅ No failures in the full-suite summary |
| `tests/test_cli.py` | not separately counted | ✅ No failures in the full-suite summary |
| `tests/test_target_repo_config_doc.py` | not separately counted | ✅ No failures in the full-suite summary |
| `tests/test_github.py` | not separately counted | ❌ 1 failure in the full-suite summary |
| `tests/test_runner.py` | not separately counted | ❌ 1 failure in the full-suite summary |
| `prompts/scripts/review-followup/tests` | not separately counted | ❌ 1 failure in the full-suite summary |

Failing tests (verbatim from the full-suite summary):

- `tests/test_github.py::test_script_callers_remove_a_stale_inherited_handoff_without_a_config`
- `tests/test_runner.py::test_stage_env_removes_a_stale_inherited_handoff_without_a_config`
- `prompts/scripts/review-followup/tests/test_github_config.py::test_a_template_that_cannot_render_fails_closed_before_any_marker[missing-attribute]`

The two stale-inheritance tests expect a `config=None` invocation to **remove** a handoff
variable inherited from the parent process, but the implementation leaves the child environment
untouched when `config is None`. The script test feeds the template `{pr_url.missing}`, whose
keyed `.format` raises `AttributeError`; `gh.py`'s validation catches `ValueError`/`KeyError`/
`IndexError`, so the `AttributeError` escapes instead of becoming the expected fail-closed
`error:`/exit-2.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `tests/test_target_config.py` — per-field defaults, declared-overrides-default precedence, purity and two-home byte equality | ✅ No failure listed in the full-suite run above |
| `tests/test_cli.py` — `config show` reports the three markers and six labels as `default`, with declared overrides as `config` | ✅ No failure listed in the full-suite run above |
| `tests/test_target_repo_config_doc.py` — documented defaults match `TOOLKIT_DEFAULTS` and a minimal config resolves them | ✅ No failure listed in the full-suite run above |
| `tests/test_github.py` — serializer shape and subprocess handoff at the script callers; `config=None` omits the stale variable | ❌ `test_script_callers_remove_a_stale_inherited_handoff_without_a_config` failed |
| `tests/test_runner.py` — `run_stage` sets the handoff alongside `SCRIPTS_DIR_ENV_VAR`; `config=None` leaves it unset | ❌ `test_stage_env_removes_a_stale_inherited_handoff_without_a_config` failed |
| `prompts/scripts/review-followup/tests` — fallback/config/fail-closed handoff, with the existing `test_logic.py`/`test_publish_logic.py` unmodified | ❌ `test_a_template_that_cannot_render_fails_closed_before_any_marker[missing-attribute]` failed |
| Standalone scripts with `AIDW_REVIEW_FOLLOWUP_CONFIG` unset: `python3 prompts/scripts/review-followup/review_followup.py --help` | ✅ Pass (exit 0, usage printed) |
| Standalone scripts with `AIDW_REVIEW_FOLLOWUP_CONFIG` unset: `python3 prompts/scripts/review-followup/publish_review_followups.py --help` | ✅ Pass (exit 0, usage printed) |
| A config containing only `schema_version: 1` resolves every `github.markers.*`/`github.labels.*` leaf as `default` with frozen values; only `schema_version`, `requires_toolkit` and `paths.agent_configs_dir` remain `unset` | ✅ Exercised by the passing config/CLI/doc tests in the full-suite run above; not separately re-run |
| Full-suite green from the toolkit root | ❌ 3 failures as recorded above |

---

## Deviations observed during recording

- **The generic record prompt names a pnpm gate set, but this repo's stack is Python/uv.** Per
  `AGENTS.md` and `prompts/pr.md` ("take them from the target repo, not from this prompt"), the
  install/build/test rows are `uv sync --frozen`, `uv build` and `uv run --frozen pytest`. No lint
  gate was run because the repo configures no linter.
- **`uv build` wrote to a fresh `$(mktemp -d)` directory**, leaving no artifacts in the gated tree.
- **The implementation was still uncommitted in the working tree.** The change set was measured
  against `main` including working-tree changes, and tree `b1f5a5319820` covers that content; this
  stage did not commit it.
- **The script-side test is named `test_github_config.py`, not the prompt's `test_config.py`.**
  The test file documents why: pytest's default `prepend` import mode would collide with the
  toolkit's unrelated `tests/test_config.py` under one session.
- **The `config=None` seam left inherited stale handoffs in place.** Two tests expect the variable
  to be actively removed rather than merely not set; this recording records the failure and does
  not change the implementation.
- **`{pr_url.missing}` is not handled by the fail-closed validation.** `AttributeError` escapes
  from keyed `.format` because `gh.py` catches only `ValueError`, `KeyError` and `IndexError`; this
  recording records the failure and does not change the implementation.
- **No subsets were re-run for their own counts.** The task-specific rows cite the single
  full-suite invocation above rather than a second run.

---

## Non-Goals (NOT implemented)

- ❌ E6.2 preserve-matching-semantics tests (strict equality, no normalisation, "ensure existing" never overwrites) — separate; this task only supplies the data matching consumes (task prompt, explicit non-goals).
- ❌ E6.3 golden freeze test vs `baseline-verbatim` — separate; this task's two-home test is a drift guard, not the authoritative golden (task prompt, explicit non-goals).
- ❌ E6.4 "Document the freeze" narrative in `docs/target-repo-config.md` — separate; E6.1 only flips the mechanical default-status cells the suite pins (task prompt, explicit non-goals).
- ❌ A comment-body or label-role field in the §3.4 schema — `aidw/target_config.py`'s dataclasses have no such field; comment bodies and role names stay in `constants.py` (task prompt, explicit non-goals).
- ❌ Writing markers/labels into prompt text or rewiring the read-only `gh` helpers in `aidw/github.py` beyond the env handoff (task prompt, explicit non-goals).
- ❌ No PR opened and nothing committed by the recording stage (`prompts/pr.md` owns delivery).
