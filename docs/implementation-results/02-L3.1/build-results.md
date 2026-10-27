# Build Results — 02-L3.1: The fixer verifies the finding before applying it

**Branch:** `02-L3.1`
**Date:** 2026-10-27
**Spec:** `docs/tasks/02 - Prompt loop integrity.md` — task L3.1 ("The fixer verifies the finding before applying it"), Epic L3 ("Fixer integrity — stop the churn"), including the phase preamble's "Gate: do not start before these are known" note that `prompts/task-review-fixes.md` is bucket (i) and the "Explicit non-goals for phase 02". `design.md` §8.1 (`aidw prompt <phase> <epic> <task>` — the P2a `task-review-fixes-N` stage: one stage per blocking finding, `could-fix` batched, whole-review fallback). `docs/migration/EXTRACTION.md` §4.2 (`task-review-fixes.md` is bucket (i), generic, and ships as-is, so its added text must stay product-neutral). `AGENTS.md` (Gates; Tests; "Prompts and agent configs are the product contract").

## Summary

**Purpose:** Stop the fixer from converting a wrong reviewer prescription into a Must-fix regression by making its first act verification of the finding against the repository and the cited sources, and by giving it an explicit, reportable push-back path plus a never-guess rule for material ambiguities.

| Decision | Why it matters |
|----------|---------------|
| The verify/push-back/never-settle text is added to `prompts/task-review-fixes.md` and `agents/task-fixer/AGENTS.md` only — no new prompt, no `prompt.py` change, no `REQUIRED_PROMPTS` edit | `task-review-fixes.md` renders with exactly `$1`; editing it is a behaviour change that must keep `prompts check` and `agents validate --strict` green. The stage prompt carries no reviewer reasoning (`session: fresh`), so the fixer must re-read the sources itself. |
| Verification is worded as the stage's **first act**, before the edit instruction | A phrase merely present somewhere in the prompt does not stop the fixer applying the `Suggested fix` verbatim; the test asserts order (`Your first act is verification` precedes `Before making any edit`). |
| Push-back reports the disagreement in the agent's `## Output` **text**, per finding — never a new field or finding label | The fixer has no findings manifest, so a new field could not travel; the Output clause ("which finding, what the reviewer prescribed, what the evidence shows, what you changed instead") is the delivery channel. |
| The never-settle rule is stated once in each file with matching wording ("state the options and stop", "`Blocked` escalation") and the existing AGENTS.md bullet is **kept** | Two divergent copies of the rule are themselves a consistency finding; `agents/task-fixer/AGENTS.md`'s Hard-rules bullet already carried it, so the prompt gets the matching statement rather than a second, contradictory one. |
| The "smallest edit" rule is qualified to the smallest **correct** edit that resolves the **verified** finding | A bare tiniest-diff mandate conflicts with the verify-first step; correctness/verification qualification removes the conflict while leaving room for L3.2's six-section sweep. |
| Neutrality is asserted on the added lines only (L2.1's pattern) | `task-review-fixes.md` is bucket (i) and ships as-is; a whole-file absence check would over-reach, but a copied product story (`pnpm`, `Design 21`, `docs/task-prompts`, `origin/00-E1.5`) must not ship. |

**Where it fits in the roadmap:** Phase 02, Epic L3 ("Fixer integrity — stop the churn"), and its first task. It builds on Epic L2 (L2.1 dependency/`Blocked` rules, L2.2 verified-revision evidence, L2.3 delta brief, L2.4 evidence bundle) and precedes L3.2 (six-section consistency sweep), L3.3 (per-stage snapshots), L3.4 (reconcile stage) and L4.x (terminal review and recording). It opens no `design.md` §17 entry — L6.2 consolidates phase 02's decisions.

**Scope:** Rewrites the opening of `prompts/task-review-fixes.md`; extends the Hard rules and `## Output` of `agents/task-fixer/AGENTS.md`; adds one rendered-prompt + agent-context test to `tests/test_prompt_workflow.py`; ticks the L3.1 roadmap checkbox. It deliberately stops short of L3.2's six-section sweep and its "which sections were re-checked" report clause, L3.3's snapshots, L3.4's reconcile stage, L4.x, any change to the P2a loop/batching/fallback, the reviewer prompt `prompts/task-review.md`, `agent-configs/task-fixer.yaml`, `aidw/inventory.py`, and any `design.md` amendment.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L3.1-prompt.md` | Created (committed) | The task prompt authored on the branch before implementation (commits `fa64531`, `b80fde4`). |
| `prompts/task-review-fixes.md` | Modified (uncommitted) | Replaced "Fix the issues as you suggest…" with verify-first (against the repository and the cited sources), the push-back path (correction the evidence supports + explicit disagreement), and the never-settle-material-ambiguity rule (`state the options and stop`, `Blocked` escalation). |
| `agents/task-fixer/AGENTS.md` | Modified (uncommitted) | Reworked the "Read the prompt in full first…" Hard rule into verify-then-fix, added the push-back bullet, qualified "Prefer the smallest edit…" to the smallest *correct* edit resolving the *verified* finding, reworded the ambiguity bullet to "state the options and stop, leaving it a `Blocked` escalation", and extended `## Output` with the per-finding disagreement report. |
| `tests/test_prompt_workflow.py` | Modified (uncommitted) | Added `test_l31_rendered_fixer_prompt_and_agent_context_state_verify_and_pushback`: asserts the verify/push-back/never-settle phrases in the rendered prompt and the agent context, the ordering of verification before the edit instruction, the neutral added lines, the qualified smallest-edit rule, and the zero-arg `PromptError` render contract. |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified (uncommitted) | Roadmap escalation: L3.1 checkbox ticked (traceability artifact owned by the update-traceability stage). |

---

## Verification Results

> **This run passed.** Every gate below was run through `aidw gate run <key> -- …` with the `pr.md` scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`, against tree `1edfd57f6a08` (the tree that includes the uncommitted working-tree change set) by stage `record-implementation-results`. Every outcome is a real observation from this run; none was copied from an earlier run or document.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Exit 0 — `Checked 15 packages in 1ms` (gate `install`, tree `1edfd57f6a08`, 2026-10-27T07:20:34Z) |
| Build | `uv build --out-dir <tmp>` | ✅ Exit 0 — built `aidt-0.1.0-py3-none-any.whl` and `aidt-0.1.0.tar.gz` (gate `build`, tree `1edfd57f6a08`, 2026-10-27T07:20:39Z) |
| Test | `env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ✅ Exit 0 — **`631 passed in 68.42s`** (gate `suite`, tree `1edfd57f6a08`, 2026-10-27T07:21:50Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)` (branch `02-L3.1` dirty; `.mcp.json` absent) (gate `doctor`, tree `1edfd57f6a08`, 2026-10-27T07:21:55Z) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `1edfd57f6a08`, 2026-10-27T07:21:54Z) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `1edfd57f6a08`, 2026-10-27T07:21:54Z) |
| Whitespace | `git diff --check` | ✅ Exit 0 — no whitespace errors (gate `whitespace`, tree `1edfd57f6a08`, 2026-10-27T07:21:58Z) |

The `suite` gate ran fresh for this stage and tree (no reusable outcome existed for this run's key), so `record-implementation-results` bought the full suite once for tree `1edfd57f6a08`; the subset row below derives from that single invocation.

### `env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` (full suite)

Single invocation: **`631 passed in 68.42s`** (exit 0, gate `suite`, tree `1edfd57f6a08`, 2026-10-27T07:21:50Z). No second run was made to obtain the subset row; the new test is part of the collected set that run reported green (the change set adds exactly one test function, and the run reported zero failures).

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 631 | ✅ Pass (`631 passed in 68.42s`) |
| New L3.1 test in `tests/test_prompt_workflow.py` | 1 | ✅ Pass (part of the 631-passed run; zero failures) |

### Task-specific verification gates

The task's proofs are the new rendered-prompt + agent-context assertions, all inside the single full-suite invocation above; there is no separate live CLI gate.

| Gate | Status |
|------|--------|
| Rendered `task-review-fixes.md` states verify-first ("verify the finding against the repository and the cited sources") and the push-back path ("make the correction the evidence supports and report the disagreement") | ✅ `test_l31_rendered_fixer_prompt_and_agent_context_state_verify_and_pushback` passes |
| Rendered prompt states the never-settle rule ("state the options and stop" / "`Blocked` escalation") just as the agent-context bullet does | ✅ passes |
| Rendered prompt no longer contains "Fix the issues as you suggest"; verification precedes the edit instruction | ✅ passes |
| Added lines are product-neutral — no `pnpm`, `Design 21`, `docs/task-prompts`, or `0x-Ex`-shaped task id | ✅ passes |
| `agents/task-fixer/AGENTS.md` states verify-then-fix and push-back; the "smallest edit" line is qualified (not the bare "Prefer the smallest edit that satisfies the finding."); the ambiguity line reads "state the options and stop" / "`Blocked` escalation"; `## Output` carries the per-finding disagreement clause | ✅ passes |
| Render contract: `render_prompt_file` with zero args raises `PromptError` (the prompt references exactly `$1`) | ✅ passes (`pytest.raises(PromptError)`) |
| `uv run aidw prompts check` and `uv run aidw agents validate --strict` stay green with the edited prompt/agent context | ✅ both clean (see top-level table) |
| Diff touches only the three deliverable files plus the task prompt and roadmap tick | ✅ Change set is exactly `prompts/task-review-fixes.md`, `agents/task-fixer/AGENTS.md`, `tests/test_prompt_workflow.py`, `docs/task-prompts/02-L3.1-prompt.md`, `docs/tasks/02 - Prompt loop integrity.md` |

---

## Deviations observed during recording

- **The record prompt names a Node/pnpm gate example; this toolkit is Python/uv.** `prompts/record-implementation-results.md` uses `pnpm install` / `pnpm -r lint` / etc. as illustrative commands, and `pr.md` keys gates off the repo's actual stack. This repo has `pyproject.toml`/`uv.lock`, so its gates are `uv sync --frozen`, `uv build`, `uv run --frozen pytest`, plus the `AGENTS.md` gate set (doctor, agents validate, prompts check). No `pnpm` command was run because this repo has no `pnpm-workspace.yaml`, and the task prompt names no `pnpm srd:*` gate.
- **The suite gate runs under `env -u AIDW_STAGE -u AIDW_RUN_ID`.** The record stage runs with `AIDW_RUN_ID=20261027T070134Z-02-L3.1-implement` and `AIDW_STAGE=record-implementation-results` exported; L2.3's recording showed the leaked identity makes `tests/test_verification.py`'s gate-run tests fail against an unknown run and record the wrong stage. The suite gate scrubs both variables for the pytest subprocess (the outer `aidw gate run` still reads them to record the outcome). No implementation or test file was modified to achieve this.
- **Every gate printed the EXTRACTION.md §3.10 single-checkout warning.** This checkout is a single working tree, so the advisory is emitted before each command. It is the intended warning, not a gate failure; for `agents-validate` the warning became the gate's recorded last non-blank summary line, while the command's own output showed `11 agent config(s): 0 error(s), 0 warning(s)`.
- **No task-specific command beyond the full suite was named in `02-L3.1-prompt.md`.** The task's proofs are rendered-prompt and agent-context assertions inside the full `pytest` invocation; there is no separate validator or smoke script to run.

---

## Non-Goals (NOT implemented)

- ❌ L3.2 (six-section consistency sweep + "which sections re-checked/changed" report clause), L3.3 (per-stage snapshots), L3.4 (reconcile stage), L4.x (terminal review, recording, config) — the rest of phase 02 (task prompt, Explicit non-goals).
- ❌ `prompts/task-review.md` (the reviewer prompt) untouched — L2.x owns its rules; L3.1 changes only the fixer side (task prompt, Explicit non-goals).
- ❌ No change to the P2a loop, per-finding/batching, or the whole-review fallback in `aidw/workflows/prompt.py` — L3.4/L4.1 own loop changes (task prompt, Explicit non-goals).
- ❌ No `design.md` §8.1 amendment and no §17 decision entry — L6.2 consolidates phase-02 decisions (task prompt, Explicit non-goals).
- ❌ No six-section sweep and no "which sections were re-checked" report clause — L3.2 owns both (task prompt, Explicit non-goals).
- ❌ No `prompt.py` change, no new prompt file, no `aidw/inventory.py:REQUIRED_PROMPTS` change, and no `agent-configs/task-fixer.yaml` change (task prompt, requirement 6 and traps).
- ❌ The push-back disagreement is not a new field or finding label — it travels in the fixer's `## Output` text (task prompt, resolved readings).
- ❌ No PR opened and nothing committed by this stage (record-implementation-results non-goals; `pr.md` owns delivery).

---

## Deliverables Checklist

- [x] `prompts/task-review-fixes.md` — verify-first opening, push-back path, and never-settle rule; "Fix the issues as you suggest" removed; product-neutral wording.
- [x] `agents/task-fixer/AGENTS.md` — verify-then-fix and push-back Hard rules, qualified smallest-edit rule, "state the options and stop / `Blocked` escalation" ambiguity line, and the `## Output` disagreement clause.
- [x] `tests/test_prompt_workflow.py` — `test_l31_rendered_fixer_prompt_and_agent_context_state_verify_and_pushback` covering the phrases, the verify-before-edit ordering, neutrality of the added lines, the agent-context wording, and the zero-arg `PromptError` render contract.
- [x] `uv run --frozen pytest` green (`631 passed`) and `uv run aidw prompts check` / `uv run aidw agents validate --strict` clean.
