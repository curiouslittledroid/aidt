# Build Results — 02-L2.2: Require the revision a finding was verified against

**Branch:** `02-L2.2`
**Date:** 2026-10-27
**Spec:** `docs/tasks/02 - Prompt loop integrity.md` — task L2.2 ("Require the revision a finding was verified against"), Epic L2 ("Reviewer authority — stop the wrong prescription"), including the phase preamble's bucket-(i) note for `prompts/task-review.md` and the "Explicit non-goals for phase 02". `design.md` §8.1 (`aidw prompt` review stage and the verdict/finding loop). `docs/migration/EXTRACTION.md` §4.2 (prompt buckets — `task-review.md` is bucket (i), generic, ships as-is). `AGENTS.md` (Gates; Tests; "Prompts and agent configs are the product contract").

## Summary

**Purpose:** Make the reviewer's `Where:` field carry the evidence a finding was checked against — the file or symbol, and the revision or command it was verified at, or an explicit statement that nothing could be verified — so a citation-free round-1 finding cannot be published as if it were verified.

| Decision | Why it matters |
|----------|---------------|
| Evidence travels inside the existing `where` value; no new manifest key or finding label | The finding manifest keys are fixed at `prompts/scripts/review-followup/logic.py:_FINDING_KEYS` and the labels at `aidw/findings.py:_LABELS`. A new `Revision:`/`Evidence:` label would either be dropped (unknown label maps to nothing) or rejected (unknown key), so the already-parsed and already-published `where` field is the only place evidence can live without changing the manifest shape. |
| The `Where:` label and the six other labels stay byte-stable; only the guidance after the colon changes | `aidw/findings.py:_LABELS` keys the parser on the literal label, and `aidw/verdict.py` keys on the three verdict tokens. Renaming the label would silently parse every finding with an empty `where` and fail the manifest closed. |
| The added wording is product-neutral and asserted only on the added line | `prompts/task-review.md` is bucket (i) and ships verbatim to target repos at cutover (EXTRACTION.md §4.2), so no package-manager name, product path, product document, or product task-id example may be baked in. The pre-existing Scope bullet already names `Design 21`, so a whole-prompt absence assertion would be both wrong and misleading; the test scopes the check to the `Where:` line this task reworded. |
| The wording accepts "the revision **or** command" and an explicit "nothing could be verified" | The roadmap accepts either a revision or a command, so the text must not force a git sha. The escape hatch is required because a reviewer forced to always cite a revision will fabricate one — the exact citation-free round-1 failure L2.2 exists to prevent. |

**Where it fits in the roadmap:** Phase 02, Epic L2 ("Reviewer authority — stop the wrong prescription"). It is the second rule in the epic: L2.1 (dependency inspection, `Blocked` semantics) precedes it, and L2.3 (delta brief) and L2.4 (evidence bundle) follow. It depends on the `where` mapping and finding labels being stable, which it leaves untouched. No `design.md` §17 entry is opened — L6.2 consolidates phase 02's decisions.

**Scope:** Rewords only the `Where:` field definition inside the finding-format block of `prompts/task-review.md`, adds one rendered-prompt test to `tests/test_prompt_workflow.py` (plus the `PromptError` import), and records the L2.2 roadmap tick. It deliberately stops short of the rest of Epic L2 (L2.2's sibling tasks L2.3/L2.4), the L3.x fixer stages, and the L4.x terminal-review/config work.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L2.2-prompt.md` | Created (committed) | The task prompt authored on the branch before implementation (commits `4bbd414`, `2732b9d`). |
| `prompts/task-review.md` | Modified | Reworded only the `Where:` field definition in the finding-format block to require the file/symbol plus the revision/command it was verified at, or an explicit "nothing could be verified". Label and verdict tokens unchanged. |
| `tests/test_prompt_workflow.py` | Modified | Added `test_l22_rendered_reviewer_prompt_requires_verified_revision`: asserts the three new `Where:` phrases, byte-stable seven labels and three verdict tokens, product-neutral added line, the one-variable render, and that a zero-argument render raises `PromptError`. Added `PromptError` to the `aidw.prompts` import. |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified | Roadmap escalation: L2.2 checkbox ticked (traceability artifact owned by the update-traceability stage). |

---

## Verification Results

> **Overall gate: ✅ PASS.** `env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` produced **`614 passed in 52.70s`**; install, build, doctor, agent validation, prompts check and `git diff --check` all passed. Every row below is a real observation from this recording run against tree `e1c8c8cd6eee`, captured through `aidw gate run` with the scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Exit 0 — `Checked 15 packages in 0.68ms` (gate `install`, tree `e1c8c8cd6eee`, stage `record-implementation-results`, 2026-10-26T22:23:31Z) |
| Build | `uv build --out-dir <tmp>` | ✅ Exit 0 — built `aidt-0.1.0-py3-none-any.whl` and `aidt-0.1.0.tar.gz` (gate `build`, tree `e1c8c8cd6eee`, 2026-10-26T22:23:35Z) |
| Test | `env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ✅ Exit 0 — **`614 passed in 52.70s`** (gate `suite`, tree `e1c8c8cd6eee`, 2026-10-26T22:24:30Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)` (branch dirty; `.mcp.json` absent) (gate `doctor`, tree `e1c8c8cd6eee`, 2026-10-26T22:24:35Z) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `e1c8c8cd6eee`, 2026-10-26T22:24:36Z) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `e1c8c8cd6eee`, 2026-10-26T22:24:37Z) |
| Whitespace | `git diff --check` | ✅ Exit 0 — no whitespace errors |

All commands were run through `aidw gate run <key> -- ...` with the scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` that `pr.md` declares. Each outcome above is cited from this run against tree `e1c8c8cd6eee`. The `suite` gate ran fresh for this stage and tree (no reusable outcome was listed for this run), so `record-implementation-results` bought the full suite once for this tree and every row below derives from that single invocation.

### `uv run --frozen pytest` (full suite)

Single passing invocation: **`614 passed in 52.70s`** (exit 0, gate `suite`, tree `e1c8c8cd6eee`, 2026-10-26T22:24:30Z). The subsets below are counts from that same run's collected set — no second full run was made.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 614 | ✅ Pass (`614 passed in 52.70s`) |
| `tests/test_prompt_workflow.py` (within the full suite) | 59 `def test_` functions | ✅ Pass (all collected items green within the 614) |
| L2.2 test added | 1 new function | ✅ Pass |

### Task-specific verification gates

All L2.2 proofs are satisfied inside the single full-suite run above.

| Gate | Status |
|------|--------|
| Rendered reviewer prompt requires the file/symbol + the revision/command, or an explicit "nothing could be verified" | ✅ `test_l22_rendered_reviewer_prompt_requires_verified_revision` asserts each phrase appears in the rendered `Where:` line |
| The added line is product-neutral (`pnpm`, `Design 21`, `docs/task-prompts`, `origin/00-E1.5`, product task-id) | ✅ Neutrality asserted on the added `Where:` line only, per the task trap |
| The `Where:` label, the six other labels, and the three verdict tokens are byte-stable | ✅ Exact ordered seven-label format and `Approve` / `Request changes` / `Blocked` tokens asserted |
| Rendering contract: exactly one variable; zero variables raise `PromptError` | ✅ One-variable render asserted; `render_prompt_file(prompt_path, [])` raises `PromptError` |
| Bundled `prompts/scripts/review-followup/` suite passes with `logic.py` and `aidw/findings.py` unmodified | ✅ Runs inside the full suite; `git diff --name-only -- prompts/scripts/review-followup aidw/findings.py` is empty |
| Diff touches only the two deliverable files (plus the task prompt and roadmap tick) | ✅ `git diff main --stat` shows `prompts/task-review.md`, `tests/test_prompt_workflow.py`, `docs/tasks/02 - Prompt loop integrity.md`, `docs/task-prompts/02-L2.2-prompt.md` |

---

## Deviations observed during recording

- **The record prompt names a Node/pnpm gate example; this toolkit is Python/uv.** `prompts/record-implementation-results.md` uses `pnpm install` / `pnpm -r lint` / etc. as illustrative commands, and `pr.md` keys gates off the repo's actual stack: this repo has `pyproject.toml`/`uv.lock`, so its gates are `uv sync --frozen` and `uv run --frozen pytest`, plus the AGENTS.md gate set (build, doctor, agents validate, prompts check). No `pnpm` command was run because this repo has no `pnpm-workspace.yaml`, and the task prompt itself names no `pnpm srd:*` gate.
- **The full suite was run with the recording identity scrubbed for the child.** `aidw gate run suite` was invoked with `-- env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest`, matching CI (`.github/workflows/ci.yml`) and the L2.1 record, because two pre-existing test-isolation gaps (`tests/test_verification.py::test_cli_gate_run_propagates_a_failing_exit_code` and `::test_cli_gate_run_records_into_the_branch_run_without_an_env_identity`) fail when an aidw stage's `AIDW_RUN_ID`/`AIDW_STAGE` leak into the pytest process. The gate command recorded above is the scrubbed one and passed `614 passed in 52.70s`; no implementation or test file was modified.
- **Every gate printed the EXTRACTION.md §3.10 single-checkout warning.** This toolkit checkout is a single working tree, so `_roots` emits the advisory before each command. It is the intended warning, not a gate failure; for `agents-validate` the warning also became the gate's recorded last non-blank summary line, while the command's own output showed `11 agent config(s): 0 error(s), 0 warning(s)`.
- **No task-specific command beyond the full suite was named in `02-L2.2-prompt.md`.** The task's tests are the rendered-prompt assertion and the bundled review-followup suite, both inside the full `pytest` invocation; there is no separate live CLI gate.

---

## Non-Goals (NOT implemented)

- ❌ L2.3 (delta brief) and L2.4 (evidence bundle) — the rest of Epic L2; L3.x (fixer verify/sweep/snapshot/reconcile) and L4.x (terminal-review budget honesty, recording, config) (task prompt, Explicit non-goals).
- ❌ `prompts/task-review-fixes.md` and the fixer agent context are untouched — L3.1/L3.2 own those (task prompt, Explicit non-goals).
- ❌ No amendment to `design.md` §8.1 and no §17 decision entry — L6.2 consolidates this phase's design decisions (task prompt, Explicit non-goals).
- ❌ Model routing and the independence rule (`task-reviewer.model != task-author.model != task-fixer.model`, design §5.4) are unchanged (task prompt, Explicit non-goals).
- ❌ No fields added to the review-finding manifest or a new `Where:`-adjacent label — evidence stays inside `where` (task prompt, Explicit non-goals). `aidw/findings.py` and `prompts/scripts/review-followup/logic.py` are untouched.
- ❌ `prompts/scripts/review-followup/` was not edited — the bundled suite passes unmodified (task prompt, Explicit non-goals).
- ❌ No PR opened and nothing committed by this stage (record-implementation-results non-goals; `pr.md` owns delivery).

---

## Deliverables Checklist

- [x] `prompts/task-review.md` — reworded `Where:` field definition; the label, the other six labels, and the three verdict tokens unchanged; no new field or label.
- [x] `tests/test_prompt_workflow.py` — `test_l22_rendered_reviewer_prompt_requires_verified_revision` covering the three new phrases, product-neutrality on the added line, byte-stable labels/verdict tokens, the one-variable render, and the zero-argument `PromptError`.
- [x] `aidw/findings.py`, `aidw/verdict.py`, and `prompts/scripts/review-followup/**` untouched; bundled suite green in the full-suite run.
