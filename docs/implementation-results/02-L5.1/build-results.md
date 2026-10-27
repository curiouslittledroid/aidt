# Build Results — 02-L5.1: Give the author the reviewer's rubric before it submits

**Branch:** `02-L5.1`
**Date:** 2026-10-28
**Spec:** `docs/tasks/02 - Prompt loop integrity.md` (L5.1), `design.md §8.1`, `prompts/task-review.md` (`## Review order`), `docs/migration/EXTRACTION.md §3.8` / `§4.2`, `AGENTS.md` (Gates and Tests)

## Summary

**Purpose:** Give the task-prompt author the reviewer's rubric before it submits, by adding a compact
`## Pre-submit self-check` to `prompts/task-prompt.md` that walks the same ground as
`prompts/task-review.md`'s nine-step `## Review order`.

| Decision | Why it matters |
|----------|---------------|
| Reuse the existing `prompt-fixed` label and point back to it from the ask-if-ambiguous clause | The label and its contract already exist; a second label or a separate decisions list would be a mechanism the reviewer does not parse |
| Each check is one line that names the review-order step it shadows, and the whole section stays under a pinned line bound (`L51_SECTION_LINE_BOUND = 30`) | A transcribed copy of the nine steps would drift from `task-review.md` and blow the Conciseness budget; the bound fails a copy and leaves room for the intro plus nine checks |
| Wording of the added lines is product-neutral; existing product text in the file is untouched | The added text ships to the target repo at the E7.1 bucket (iii) split, but `task-prompt.md` is already ~100% product-specific (EXTRACTION.md §3.8), so neutrality is asserted on the added lines only |
| Neutrality test strips the file to the pointer phrase and the self-check section before asserting | A whole-file absence assertion on `pnpm`/`Design 21`/etc. would fail against pre-existing text the task is explicitly forbidden to change |
| Render-arity test uses exactly three args (`["02", "L5", "L5.1"]`) and asserts two args raise `PromptError` while an extra arg is ignored | `task-prompt.md` references `$1`/`$2`/`$3`; `aidw/prompts.py` raises only when the highest referenced index exceeds the count |

**Where it fits in the roadmap:** Phase 02 ("Prompt loop integrity"), Epic L5 ("Author upstream
quality — fewer findings to fix"). It follows the L1–L4 work that tightened the author/reviewer loop
and precedes L5.2 (reconcile gate/verifier commands, which owns the target-conventions mechanism) and
L5.3 (workflow-side conciseness budget check, which owns the size enforcement in
`aidw/workflows/prompt.py`). E7.1/§4.2 owns the bucket split and the neutralisation of the
pre-existing product text at cutover.

**Scope:** Edits `prompts/task-prompt.md` (a new `## Pre-submit self-check` section after the
Section-by-Section Guidance plus a pointer sentence in the ask-if-ambiguous clause), adds the L5.1
tests to `tests/test_prompt_workflow.py`, and flips the roadmap checkbox. It deliberately stops
short of adding a workflow stage, editing `aidw/workflows/prompt.py` or `aidw/inventory.py`, touching
any agent context file, neutralising existing product text, changing model routing, or changing the
reviewer's review order itself.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L5.1-prompt.md` | Created | Task prompt defining the L5.1 self-check requirements (committed on the branch). |
| `prompts/task-prompt.md` | Modified | Added the `## Pre-submit self-check` section (nine one-line checks shadowing the review order, the seven `prompt-fixed` decisions, reference to `task-review.md`) and a pointer sentence in the ask-if-ambiguous clause. |
| `tests/test_prompt_workflow.py` | Modified | Added L5.1 rendered-prompt test asserting the heading, the seven decision phrases, the `prompt-fixed`/review-order references, the compact one-line-per-step shape, line-level non-intersection with the reviewer's review order, added-lines-only neutrality, and three-arg render arity. |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified | Flipped the L5.1 checkbox to done. |

---

## Verification Results

Repo gates are the ones `AGENTS.md` names under "Gates — run exactly these, and only these" and the
`pyproject.toml` / `uv.lock` row `prompts/pr.md` selects: `uv sync --frozen`,
`uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents validate --strict`,
`uv run aidw prompts check`, plus `uv build`. Each runnable gate was run through
`aidw gate run <key> -- <command>` with the shared scope
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`,
against tree `c021ba60cd4f` in run `20261027T214226Z-02-L5.1-implement`, stage
`record-implementation-results`. The pytest gate scrubs the harness's ambient `AIDW_STAGE` /
`AIDW_RUN_ID` from its child process — the convention prior stages (`docs/implementation-results/02-L4.1/`,
`02-L4.2/`, `02-L3.3/`, `02-L3.4/`) documented, because two pre-existing `tests/test_verification.py`
gate-recording tests read those variables and fail when the stage identity leaks into the child.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.68ms` (exit 0) — gate `install`, tree `c021ba60cd4f`, stage `record-implementation-results`, 2026-10-27T22:22:30Z |
| Build | `uv build --out-dir $(mktemp -d)` | ✅ built sdist + wheel `aidt-0.1.0` — gate `build`, tree `c021ba60cd4f`, 2026-10-27T22:22:34Z |
| Test | `env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ✅ `663 passed in 70.44s (0:01:10)` — gate `suite`, tree `c021ba60cd4f`, 2026-10-27T22:23:48Z |
| Doctor | `uv run --frozen aidw doctor` | ✅ `14 checks: 0 failed, 2 warning(s)` — gate `doctor`, tree `c021ba60cd4f`, 2026-10-27T22:23:53Z |
| Agent configs | `uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` — gate `agents`, tree `c021ba60cd4f`, 2026-10-27T22:23:54Z |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` — gate `prompts`, tree `c021ba60cd4f`, 2026-10-27T22:23:54Z |
| Whitespace | `git diff --check` | ✅ no output (exit 0) |
| Lint (pnpm) | `pnpm -r lint` | **unverified — not applicable**: no `pnpm-workspace.yaml` or `package.json` exists in this `pyproject.toml`/`uv.lock` toolkit repo; no lint gate is configured (`design.md` §15). |
| Build (pnpm) | `pnpm -r build` | **unverified — not applicable**: same reason; the Python build gate (`uv build`) is run above. |
| Test (pnpm) | `pnpm -r test` | **unverified — not applicable**: same reason; the Python test gate (`uv run --frozen pytest`) is run above. |

The `uv sync --frozen` install gate is the one `AGENTS.md` names. `uv build` is not one of the five
named gates; it was run because `prompts/pr.md` lists it for the `pyproject.toml` stack.

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 663 | ✅ Pass (`663 passed in 70.44s (0:01:10)`) |

The new L5.1 case is inside this single run — no separate subset invocation was made. It is
`test_l51_rendered_author_prompt_carries_the_review_order_self_check` in
`tests/test_prompt_workflow.py`, which asserts the `## Pre-submit self-check` heading appears after
the ask-if-ambiguous clause, all seven decision key phrases render, the section references the
reviewer's `## Review order` and reuses `prompt-fixed`, each of the nine checks names a review-order
step on exactly one line, the section stays within the pinned line bound, no self-check line appears
verbatim in the review order, the added lines are product-neutral, and the render contract holds
(two args raise `PromptError`, a fourth arg is ignored). The pre-existing L1.3/L2.x rendered-prompt
tests (`test_l13_rendered_author_prompt_and_agent_context_state_the_contract`,
`test_render_real_task_prompt`) are unchanged and green inside the same run.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run --frozen pytest` (the gate the task prompt's Tests/Done-when name) | ✅ `663 passed` — gate `suite`, tree `c021ba60cd4f`, 2026-10-27T22:23:48Z |
| `uv run aidw prompts check` (the gate the task prompt's Tests/Done-when name) | ✅ `prompts check: 0 error(s), 0 warning(s)` — gate `prompts`, tree `c021ba60cd4f`, 2026-10-27T22:23:54Z |
| Install / build / doctor / agents | ✅ see top-level table |
| `pnpm srd:validate` / `srd:check-references` / `srd:matrix-check` / `srd:report` | **unverified — not applicable**: no `pnpm-workspace.yaml`, `package.json`, `docs/rules-coverage/catalog.json` or vector matrix exists in this toolkit repo |
| `pnpm --filter infra cdk synth -c env=dev` | **unverified — not applicable**: no `infra/` package or CDK workspace exists in this repo |
| Deployed integration / matrix completeness test | **unverified — not applicable**: no TypeScript integration workspace or matrix fixture exists |

---

## Deviations observed during recording

- **The generic prompt template names pnpm gates; this repo is Python/uv.** `prompts/record-implementation-results.md`
  ships pnpm examples, but `AGENTS.md` names exactly the five uv commands above and `prompts/pr.md`
  says to take the gate commands from the target repo. The pnpm/SRD/CDK rows do not apply here and are
  marked unverified/not applicable rather than passing. No lint gate exists in this repo.
- **The pytest gate runs under `env -u AIDW_STAGE -u AIDW_RUN_ID`.** Two pre-existing
  `tests/test_verification.py` gate-recording tests read the harness's ambient stage identity and fail
  when it leaks into the child process. This is the convention prior stages documented; the outer
  `aidw gate run` still records the outcome into this run.
- **The change set includes the roadmap checkbox.** `docs/tasks/02 - Prompt loop integrity.md` is
  modified (L5.1 checkbox flipped) by an earlier traceability stage, so it appears in the change set
  relative to `main` even though L5.1's deliverables are `prompts/task-prompt.md` and
  `tests/test_prompt_workflow.py`. This stage did not modify it.

---

## Non-Goals (NOT implemented)

- ❌ L5.2 (gate/verifier reconciliation and naming target conventions), L5.3 (workflow-side conciseness check), L6.1 (loop contract fixture), L6.2 (consolidating design decisions) — the rest of epics L5/L6.
- ❌ Do NOT neutralise the pre-existing product text in `prompts/task-prompt.md` — E7.1/E7.2/E7.4 own the bucket split and neutralisation; L5.1 only adds neutral text and does not touch the existing `Design 21`/`pnpm` content.
- ❌ Do NOT add a workflow stage or edit `aidw/workflows/prompt.py`, `aidw/inventory.py`, or any agent context file (`agents/task-author/AGENTS.md` is untouched).
- ❌ Do NOT change model routing or the reviewer's review order itself — the rubric is read, not modified.
