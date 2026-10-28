# Build Results — 02-L5.3: Check the conciseness budget in the workflow

**Branch:** `02-L5.3`
**Date:** 2026-10-28
**Spec:** `design.md` §8.1 (prompt workflow) / §14 (exit codes), `prompts/task-prompt.md` §Conciseness budget, `docs/tasks/02 - Prompt loop integrity.md` (L5.3), `AGENTS.md` (Gates and Tests)

## Summary

**Purpose:** Measure the task prompt the `aidw prompt` author stage has just produced against the
conciseness budget that `prompts/task-prompt.md` states but the workflow never enforced — warn by
default, refuse under `--strict` — so an over-budget prompt is visible (and optionally fatal) before
the review loop begins.

| Decision | Why it matters |
|----------|---------------|
| Read exactly the just-generated `prompt_path`, never scan `docs/task-prompts/` | The toolkit's own prompts already exceed the budget (`00-E1.5-prompt.md` is 17.9KB, `00-E1.4-prompt.md` 181 lines), so a directory scan would warn forever; the check measures the artifact this run produced (Req 1, task-prompt trap). |
| Decimal 15KB = 15000 bytes (not binary 15360) | Matches the roadmap's own decimal KB (17855 bytes = "17.9KB"); a binary budget would shift every boundary by 360 bytes (Req 2). |
| Trip strictly greater than the budget (`>` not `>=`) | Exactly 15000 bytes / 150 lines are allowed; boundary tests prove inclusivity. |
| Attribute the size to the longest numbered `Requirements:` item(s), degrade to totals-only on absent/unparseable section | "Names the offending requirement" is attribution, not a per-clause word cap — no numeric word-per-requirement limit exists in the cited sources. A parse or read failure must never fail the run (Req 3). |
| Warn/refuse at the workflow level, not a recorded gate; `--strict` returns exit 1 with `FAILED` and no `approve-task-prompt` gate | Avoids new gate-decision vocabulary (L4.2 / design §9.2); §14 exit 1 reads as a stage/gate failure. The author has already committed the prompt, so the over-budget file/branch is left as-is (design §13). |
| Count line printed unconditionally, right after `prompt: {rel}` | Requirement 5: the "count in the stage report" for every produced prompt, independent of whether the check trips. |

**Where it fits in the roadmap:** Phase 02 ("Prompt loop integrity"), Epic L5 ("Author upstream
quality"). It follows L5.1 (author pre-submit self-check) and L5.2 (gate/verifier reconciliation),
and is the third and last L5 task; L6.1 (loop-contract fixture) and L6.2 (`design.md` §17
consolidation) remain separate.

**Scope:** Adds the conciseness check and its helpers to `aidw/workflows/prompt.py`, invoked once
after the author stage resolves `prompt_path` (after the `prompt: {rel}` print, before the review
loop; the `--dry-run` path returns earlier and never checks), plus eleven tests in
`tests/test_prompt_workflow.py`. It deliberately stops short of editing `prompts/task-prompt.md`,
touching the review/fix/reconcile loop, the evidence bundle or `--max-revisions`, and recording any
gate.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L5.3-prompt.md` | Created | Task prompt defining the L5.3 conciseness requirements, traps and non-goals (committed on the branch). |
| `aidw/workflows/prompt.py` | Modified | Added `PROMPT_BYTE_BUDGET` / `PROMPT_LINE_BUDGET` and `_budget_counts` / `_requirement_items` / `_longest_requirements` / `_budget_reason` / `_check_conciseness`; called `_check_conciseness` after the `prompt: {rel}` print (warn + continue at the default, exit 1 / `FAILED` / no gate under `--strict`); updated the module docstring for the post-author check. |
| `tests/test_prompt_workflow.py` | Modified | Added eleven `test_l53_*` cases (byte/line over-budget warn-and-review, strict refuse-before-review for each, in-budget silence, totals-only degrade, generated-path-only, unreadable-file degrade, byte/line boundary inclusivity, equal-longest attribution) and a `prompt_body` knob on `_fake_stages`; the dry-run test now asserts no `budget:` line. |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified | Flipped the L5.3 checkbox to done (traceability update left uncommitted). |

---

## Verification Results

Repo gates are the ones `AGENTS.md` names under "Gates — run exactly these, and only these", plus
`uv build` because `prompts/pr.md` lists it for the `pyproject.toml` / `uv.lock` stack. Each runnable
gate was run through `aidw gate run <key> -- <command>` with the shared scope
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`,
against tree `cd41f7f43ff9` in run `20261028T062533Z-02-L5.3-implement`, stage
`record-implementation-results`. All outcomes below were produced by this run.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 11ms` — gate `install`, tree `cd41f7f43ff9`, stage `record-implementation-results`, 2026-10-28T06:58:27Z |
| Build | `uv build --out-dir <mktemp -d>` | ✅ built sdist + wheel `aidt-0.1.0` — gate `build`, tree `cd41f7f43ff9`, 2026-10-28T06:58:34Z |
| Test | `env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ✅ `675 passed in 119.53s (0:01:59)` — gate `suite`, tree `cd41f7f43ff9`, 2026-10-28T07:00:38Z |
| Doctor | `uv run --frozen aidw doctor` | ✅ `14 checks: 0 failed, 2 warning(s)` — gate `doctor`, tree `cd41f7f43ff9`, 2026-10-28T07:00:43Z |
| Agent configs | `uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` — gate `agents`, tree `cd41f7f43ff9`, 2026-10-28T07:00:46Z |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` — gate `prompts`, tree `cd41f7f43ff9`, 2026-10-28T07:00:50Z |
| Whitespace | `git diff --check` | ✅ no output (exit 0) |
| Lint (pnpm) | `pnpm -r lint` | **unverified — not applicable**: no `pnpm-workspace.yaml` or `package.json` exists in this `pyproject.toml`/`uv.lock` toolkit repo; no lint gate is configured (`design.md` §15). |
| Build (pnpm) | `pnpm -r build` | **unverified — not applicable**: same reason; the Python build gate (`uv build`) is run above. |
| Test (pnpm) | `pnpm -r test` | **unverified — not applicable**: same reason; the Python test gate (`uv run --frozen pytest`) is run above. |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 675 | ✅ Pass (`675 passed in 119.53s (0:01:59)`) |

The new L5.3 cases are inside this single full-suite run — no separate subset invocation was made.
They are the eleven `test_l53_*` functions in `tests/test_prompt_workflow.py`:
`test_l53_over_byte_budget_warns_by_requirement_and_still_approves`,
`test_l53_over_line_budget_warns_by_requirement_and_still_approves`,
`test_l53_strict_over_budget_refuses_before_review`,
`test_l53_in_budget_prompt_prints_count_without_a_warning`,
`test_l53_unparseable_requirements_degrades_to_totals_only`,
`test_l53_check_reads_only_the_generated_prompt`,
`test_l53_unreadable_prompt_warns_and_never_fails_the_check`,
`test_l53_byte_budget_boundary_is_inclusive`,
`test_l53_line_budget_boundary_is_inclusive`,
`test_l53_strict_over_line_budget_refuses_before_review`, and
`test_l53_equal_longest_requirements_are_all_named`. The total rose from the prior 664-test baseline
by exactly these eleven.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run --frozen pytest` (the gate the task prompt's Tests/Done-when name) | ✅ `675 passed` — gate `suite`, tree `cd41f7f43ff9`, 2026-10-28T07:00:38Z |
| Install / build / doctor / agents / prompts | ✅ see top-level table |
| `pnpm srd:validate` / `srd:check-references` / `srd:matrix-check` / `srd:report` | **unverified — not applicable**: no `pnpm-workspace.yaml`, `package.json`, `docs/rules-coverage/catalog.json` or vector matrix exists in this toolkit repo. |
| `pnpm --filter infra cdk synth -c env=dev` | **unverified — not applicable**: no `infra/` package or CDK workspace exists in this repo. |
| Deployed integration / matrix completeness test | **unverified — not applicable**: no TypeScript integration workspace or matrix fixture exists. |

---

## Deviations observed during recording

- **The task-prompt template's pnpm/SRD gates do not apply to this repo.** `prompts/record-implementation-results.md`
  ships pnpm examples, but `AGENTS.md` names the uv commands above and `prompts/pr.md` says to take
  gate commands from the target repo. Those rows are marked unverified/not applicable, not passing.
- **The pytest gate runs under `env -u AIDW_STAGE -u AIDW_RUN_ID`.** Two pre-existing
  `tests/test_verification.py` gate-recording tests read the harness's ambient stage identity and fail
  when it leaks into the child process. The outer `aidw gate run` still records the outcome into this run.
- **The change set spans commits and the working tree.** The branch carries the committed L5.3 task
  prompt (`docs/task-prompts/02-L5.3-prompt.md`); `aidw/workflows/prompt.py`,
  `tests/test_prompt_workflow.py` and the L5.3 roadmap checkbox are uncommitted. This stage modified
  none of them.

---

## Non-Goals (NOT implemented)

- ❌ L5.1 (author pre-submit self-check) and L5.2 (gate/verifier reconciliation) — already landed; `prompts/task-prompt.md` was not edited (the roadmap assigns enforcement to the workflow, not the author prompt).
- ❌ L6.1 (loop contract fixture) and L6.2 (`design.md` §17 consolidation) — later tasks.
- ❌ Any change to the review/fix/reconcile loop, the evidence bundle, `--max-revisions`, or any other stage — this task adds one check between the author stage and review.
- ❌ Any recorded gate or `approve-task-prompt` decision — the check is a workflow-level warn/refuse, not a gate (L4.2 / design §9.2).
- ❌ No commit, push, or PR opened by this stage.
