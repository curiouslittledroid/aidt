# Build Results — 02-L3.2: Sweep the document after editing

**Branch:** `02-L3.2`
**Date:** 2026-10-27
**Spec:** `docs/tasks/02 - Prompt loop integrity.md` — task L3.2 ("Sweep the document after editing"), Epic L3 ("Fixer integrity — stop the churn"), including the phase preamble's "Gate: do not start before these are known" note that `prompts/task-review-fixes.md` is bucket (i) and the "Explicit non-goals for phase 02". `design.md` §8.1 (`aidw prompt <phase> <epic> <task>` — the P2a `task-review-fixes-N` stage: one stage per blocking finding, `could-fix` batched, whole-review fallback; the fixer receives `$1` and the re-rendered finding). `docs/migration/EXTRACTION.md` §4.2 (`task-review-fixes.md` is bucket (i), generic, and ships as-is, so its added text must stay product-neutral). `AGENTS.md` (Gates; Tests; "Prompts and agent configs are the product contract").

## Summary

**Purpose:** Make every fix stage end by re-reading the whole prompt under revision and repairing whatever its edit made stale, naming the exact six prompt-format sections that must be swept, so a one-line fix cannot silently invalidate a neighbouring section.

| Decision | Why it matters |
|----------|---------------|
| The sweep text is added to `prompts/task-review-fixes.md` and `agents/task-fixer/AGENTS.md` only — no new prompt, no `prompt.py` change, no `REQUIRED_PROMPTS` edit | `task-review-fixes.md` renders with exactly `$1`; editing it is a behaviour change that must keep `prompts check` and `agents validate --strict` green. The stage carries no reviewer manifest, so the sweep is a text instruction, not a new loop step. |
| The sweep is the stage's **last** act, appended after L3.1's verify-then-fix text | L3.1's ordering guarantee ("Your first act is verification" precedes "Before making any edit") must survive; the test asserts the edit instruction also precedes the sweep ("re-read the whole prompt"). |
| Both files name **exactly** the six roadmap sections (`Requirements`, `Traps / prior review findings`, `Explicit non-goals`, `Tests`, `Done when`, and the closing prompt-fixed/ambiguity list) | An edit to `Requirements` can also stale `Deliverables`, but the roadmap fixes six; a seventh swept section would be a roadmap deviation. A single test asserts the same complete list in both files and that `Deliverables` is absent. |
| The report contract travels in `agents/task-fixer/AGENTS.md` `## Output`, never a new finding field | The fixer has no parsed manifest, so a new key would have nowhere to live; the Output clause ("which sections it re-checked in the sweep, and which it changed because of the sweep") is the delivery channel. |
| Neutrality is asserted on the added block only (L2.1/L3.1 pattern) | `task-review-fixes.md` is bucket (i) and ships to every target repo; a copied product story (`pnpm`, `Design 21`, `docs/task-prompts`, `0x-Ex`-shaped task id) must not ship, but a whole-file absence check would over-reach. |

**Where it fits in the roadmap:** Phase 02, Epic L3 ("Fixer integrity — stop the churn"), and its second task. It builds directly on L3.1 (verify-then-fix and push-back) and is the point at which L3.1's "smallest *correct* edit" rule is qualified by the consistency sweep. It precedes L3.3 (per-stage snapshots), L3.4 (reconcile stage) and L4.x (terminal review and recording). It opens no `design.md` §17 entry — L6.2 consolidates phase 02's decisions.

**Scope:** Appends the consistency sweep and the six-section list to the end of `prompts/task-review-fixes.md`; adds a matching Hard-rule bullet and the `## Output` sweep-report clause to `agents/task-fixer/AGENTS.md`; adds one rendered-prompt + agent-context test to `tests/test_prompt_workflow.py`; ticks the L3.2 roadmap checkbox. It deliberately stops short of L3.3's snapshots, L3.4's reconcile stage, L4.x, L5.1/L5.3's `prompt-fixed` vocabulary enrichment, any change to the P2a loop/batching/fallback, the reviewer prompt `prompts/task-review.md`, `agent-configs/task-fixer.yaml`, `aidw/inventory.py`, and any `design.md` amendment.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L3.2-prompt.md` | Created (committed) | The task prompt authored on the branch before implementation (commit `a08a796`). |
| `prompts/task-review-fixes.md` | Modified (uncommitted) | Appended the post-edit consistency sweep: re-read the whole prompt, repair what the edit made stale, and walk the six named sections. |
| `agents/task-fixer/AGENTS.md` | Modified (uncommitted) | Added a Hard-rule bullet carrying the sweep and the six-section list alongside L3.1's verify-first bullet, and extended `## Output` with the "which sections re-checked / changed because of the sweep" report clause. |
| `tests/test_prompt_workflow.py` | Modified (uncommitted) | Added `test_l32_fixer_sweeps_the_document_and_names_the_six_sections`: asserts the sweep phrases, the verify-before-edit-before-sweep ordering, the exact six-name set in both files (and no `Deliverables`), the `## Output` report contract, the neutral added lines, and the zero-arg `PromptError` render contract. |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified (uncommitted) | Roadmap escalation: L3.2 checkbox ticked (traceability artifact owned by the update-traceability stage). |

---

## Verification Results

> **This run passed.** Every gate below was run through `aidw gate run <key> -- …` with the `pr.md` scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`, against tree `2a3c9a6e908c` (the tree that includes the uncommitted working-tree change set) by stage `record-implementation-results`. Every outcome is a real observation from this run; none was copied from an earlier run or document.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Exit 0 — `Checked 15 packages in 1ms` (gate `install`, tree `2a3c9a6e908c`, 2026-10-27T08:31:03Z) |
| Build | `uv build --out-dir <tmp>` | ✅ Exit 0 — built `aidt-0.1.0-py3-none-any.whl` and `aidt-0.1.0.tar.gz` (gate `build`, tree `2a3c9a6e908c`, 2026-10-27T08:31:07Z) |
| Test | `env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ✅ Exit 0 — **`632 passed in 71.29s`** (gate `suite`, tree `2a3c9a6e908c`, 2026-10-27T08:32:43Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)` (branch `02-L3.2` dirty; `.mcp.json` absent) (gate `doctor`, tree `2a3c9a6e908c`, 2026-10-27T08:31:09Z) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `2a3c9a6e908c`, 2026-10-27T08:31:10Z) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `2a3c9a6e908c`, 2026-10-27T08:31:11Z) |
| Whitespace | `git diff --check` | ✅ Exit 0 — no whitespace errors (gate `whitespace`, tree `2a3c9a6e908c`, 2026-10-27T08:31:12Z) |

The `suite` gate ran fresh for this stage and tree (no reusable outcome existed for this run's key), so `record-implementation-results` bought the full suite once for tree `2a3c9a6e908c`; the subset row below derives from that single invocation.

### `env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` (full suite)

Single invocation: **`632 passed in 71.29s`** (exit 0, gate `suite`, tree `2a3c9a6e908c`, 2026-10-27T08:32:43Z). No second run was made to obtain the subset row; the new test is part of the collected set that run reported green (the change set adds exactly one test function, and the run reported zero failures).

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 632 | ✅ Pass (`632 passed in 71.29s`) |
| New L3.2 test in `tests/test_prompt_workflow.py` | 1 | ✅ Pass (part of the 632-passed run; zero failures) |

### Task-specific verification gates

The task's proofs are the new rendered-prompt + agent-context assertions, all inside the single full-suite invocation above; there is no separate live CLI gate.

| Gate | Status |
|------|--------|
| Rendered `task-review-fixes.md` states the sweep ("re-read the whole prompt" / "repair what the edit made stale") | ✅ `test_l32_fixer_sweeps_the_document_and_names_the_six_sections` passes |
| Ordering: "Your first act is verification" precedes "Before making any edit", which precedes the sweep | ✅ passes |
| L3.1's phrases ("verify the finding against the repository and the cited sources", "state the options and stop", "`Blocked` escalation") are unchanged and "Fix the issues as you suggest" is still absent | ✅ passes |
| Both files name the exact six sections and neither lists `Deliverables` as a swept section | ✅ passes (complete comma-separated list matched once in the prompt and twice in the agent context) |
| `agents/task-fixer/AGENTS.md` `## Output` asks the fixer to state which sections it re-checked and which it changed because of the sweep | ✅ passes |
| Added lines are product-neutral — no `pnpm`, `Design 21`, `docs/task-prompts`, or `0x-Ex`-shaped task id | ✅ passes |
| Render contract: `render_prompt_file` with zero args raises `PromptError` (the prompt references exactly `$1`) | ✅ passes (`pytest.raises(PromptError)`) |
| `uv run aidw prompts check` and `uv run aidw agents validate --strict` stay green with the edited prompt/agent context | ✅ both clean (see top-level table) |
| Diff touches only the three deliverable files plus the task prompt and roadmap tick | ✅ Change set is exactly `prompts/task-review-fixes.md`, `agents/task-fixer/AGENTS.md`, `tests/test_prompt_workflow.py`, `docs/task-prompts/02-L3.2-prompt.md`, `docs/tasks/02 - Prompt loop integrity.md` |

---

## Deviations observed during recording

- **The record prompt names a Node/pnpm gate example; this toolkit is Python/uv.** `prompts/record-implementation-results.md` uses `pnpm install` / `pnpm -r lint` / etc. as illustrative commands, and `pr.md` keys gates off the repo's actual stack. This repo has `pyproject.toml`/`uv.lock`, so its gates are `uv sync --frozen`, `uv build`, `uv run --frozen pytest`, plus the `AGENTS.md` gate set (doctor, agents validate, prompts check). No `pnpm` command was run because this repo has no `pnpm-workspace.yaml`, and the task prompt names no `pnpm srd:*` gate.
- **`git diff --stat main...HEAD` understates the change set.** It shows only the committed task prompt (`docs/task-prompts/02-L3.2-prompt.md`); the implementation lives in the uncommitted working tree, so the change set recorded here is `git diff main` (committed + working tree), not the merge-base diff alone.
- **The suite gate runs under `env -u AIDW_STAGE -u AIDW_RUN_ID`.** The record stage runs with `AIDW_RUN_ID=20261027T080842Z-02-L3.2-implement` and `AIDW_STAGE=record-implementation-results` exported; L2.3's recording showed the leaked identity makes `tests/test_verification.py`'s gate-run tests fail against an unknown run and record the wrong stage. The suite gate scrubs both variables for the pytest subprocess (the outer `aidw gate run` still reads them to record the outcome). No implementation or test file was modified to achieve this.
- **Every gate printed the EXTRACTION.md §3.10 single-checkout warning.** This checkout is a single working tree, so the advisory is emitted before each command. It is the intended warning, not a gate failure; for `agents-validate` the warning became the gate's recorded last non-blank summary line, while the command's own output showed `11 agent config(s): 0 error(s), 0 warning(s)`.
- **No task-specific command beyond the full suite was named in `02-L3.2-prompt.md`.** The task's proofs are rendered-prompt and agent-context assertions inside the full `pytest` invocation; there is no separate validator or smoke script to run.

---

## Non-Goals (NOT implemented)

- ❌ L3.3 (per-stage snapshots), L3.4 (reconcile stage), L4.x (terminal review, recording, config) — the rest of phase 02 (task prompt, Explicit non-goals).
- ❌ L5.1 (author pre-submit self-check / prompt-fixed decision checklist) and L5.3 (workflow conciseness check) — the `prompt-fixed` vocabulary the sixth section names is L5.x's to enrich (task prompt, Explicit non-goals).
- ❌ `prompts/task-review.md` (the reviewer prompt) untouched — L2.x owns it; L3.2 changes only the fixer side (task prompt, Explicit non-goals).
- ❌ No change to the P2a loop, per-finding/batching, or the whole-review fallback in `aidw/workflows/prompt.py` — L3.4/L4.1 own loop changes (task prompt, Explicit non-goals).
- ❌ No `design.md` §8.1 amendment and no §17 decision entry — L6.2 consolidates phase-02 decisions (task prompt, Explicit non-goals).
- ❌ No `prompt.py` change, no new prompt file, no `aidw/inventory.py:REQUIRED_PROMPTS` change, and no `agent-configs/task-fixer.yaml` change (task prompt, requirement 6 and traps).
- ❌ The sweep report is not a new finding field or manifest key — it travels in the fixer's `## Output` text (task prompt, resolved readings).
- ❌ No PR opened and nothing committed by this stage (record-implementation-results non-goals; `pr.md` owns delivery).
