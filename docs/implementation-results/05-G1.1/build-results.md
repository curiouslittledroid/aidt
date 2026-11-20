# Build Results — G1.1: Classify prompt-review findings as `spec-gap` vs `prompt-gap` and short-circuit spec-gaps

**Branch:** `05-G1.1`
**Date:** 2026-11-20
**Spec:** `design.md` §8.1, §8.3, §17 (row Z18), §18
**Pull request:** #175 — https://github.com/curiouslittledroid/aidt/pull/175

## Summary

**Purpose:** Classify every task-prompt review finding as `spec-gap` or `prompt-gap` and stop the prompt-review loop fail-closed on a spec gap (or on an unclassifiable finding) instead of paying a fix stage to paper over a defect only the cited spec or roadmap can close.

| Decision | Why it matters |
|----------|---------------|
| `Kind:` is parsed in `aidw/findings.py` but enforced only in `aidw/workflows/prompt.py` | `findings.py` is shared with the §8.3 code-review workflow and the delta-brief shrink; making `Kind:` required at parse level would fail every code-review finding closed and change the published manifest shape. |
| `kind` stays out of `STRING_FIELDS` and `to_manifest_entry` | The published findings manifest is §8.3's contract; a prompt-review-only classification must not change it. |
| Gate mechanisms are `spec-gap` and `unclassified`, never `review-loop` | W1's `--resume` rule keys the fix-cycle continuation on `mechanism == "review-loop"`; recording that mechanism would hand a spec gap straight back to the fixer, the exact behaviour this task removes. |
| The unclassified stop is checked before the spec-gap stop and both before every verdict branch | A review whose classification cannot be trusted must not be acted on even in part, and a spec gap must win over `Approve`, `Blocked` and the terminal-budget branch. |
| `_finding_text_block` re-emits `Kind:` when present | It is the single re-emitter for the fixer stages and `stage_registry.render_delta_brief`'s shrink; dropping it would lose the classification in a shrunk previous review (the trap Z8 closed for `Verdict on this finding:`). |
| The §17 decision id is Z18, not the roadmap's stale "Z13" | Z13 is 05-S1.2's roadmap-ownership row and `aidw/conventions.md` forbids reusing an id; the next free id was appended and `tests/test_design_doc.py` matches the row by task id, never by number. |

**Where it fits in the roadmap:** Epic G1 ("Prompt review depth") in `docs/tasks/05 - Pipeline efficiency.md`. It follows the C1.x prompt-evidence work (resolved gate commands, injected gate block) and depends on the existing §8.1 `blocked:` mechanism, which it mirrors at the review layer. It precedes G1.2 ("Check task feasibility before the authoring stage"), which turns the remaining expensive blocked-authoring case into a cheap Python preflight.

**Scope:** `prompts/task-review.md` (required `Kind:` line, definitions, full-re-read rule), `agents/task-reviewer/AGENTS.md` (the same `Kind:` requirement, read-only boundary unchanged), `aidw/findings.py` (`KIND_MAP`, `normalise_kind`, optional `ParsedFinding.kind`, `_finding_text_block` re-emission), `aidw/workflows/prompt.py` (`classification_stop`, the surfaced stops, non-`review-loop` mechanisms, resume refusal), `design.md` §8.1 + §17, the prompt-classification and workflow-stages traceability docs, and the focused tests. It deliberately stops short of changing `prompts/task-review-fixes.md` or `agents/task-fixer/AGENTS.md` (spec gaps never reach the fixer), the code-review manifest shape, and the `review`/`fix` workflows.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/05-G1.1-prompt.md` | Created | Task prompt for this task, committed on the branch before implementation. |
| `agents/task-reviewer/AGENTS.md` | Modified | Mirrors the required `Kind:` line and its two values; read-only boundary unchanged. |
| `aidw/findings.py` | Modified | Adds `SPEC_GAP`/`PROMPT_GAP`, `KIND_MAP`, `normalise_kind`, optional `ParsedFinding.kind`, and `Kind:` re-emission in `_finding_text_block`; manifest shape unchanged. |
| `aidw/workflows/prompt.py` | Modified | Adds `classification_stop` and the two surfaced fail-closed stops (`spec-gap`, `unclassified`), recorded as gate denials before any fix/reconcile/approve path; resume refuses both. |
| `design.md` | Modified | §8.1 gains the `Kind:` contract, the re-read rule and both stops; §17 gains row Z18. |
| `docs/migration/prompt-classification.md` | Modified | Re-classifies `task-review.md` from byte-frozen bucket (i) to class (v), with the table row and rationale. |
| `docs/workflow-stages.md` | Modified | Documents `Kind:` on `P2`, the two new gate mechanisms, and the `approve-task-prompt` denials. |
| `prompts/task-review.md` | Modified | Requires a bare `Kind:` line per finding, defines both values, extends the plain-label rule, and forbids approving on a grep/diff-only re-read. |
| `tests/test_design_doc.py` | Modified | Pins the §8.1 wording and exactly one §17 row matching `G1.1`, matched by task id. |
| `tests/test_findings.py` | Modified | Covers `Kind:` parsing (both forms, bold), absent-kind compatibility, manifest shape, and text-block round-trip. |
| `tests/test_prompt_classification.py` | Modified | Re-baselines the byte-frozen partition for `task-review.md`'s move to class (v). |
| `tests/test_prompt_workflow.py` | Modified | Covers spec-gap and unclassified stops, precedence, prompt-gap flow, gate mechanisms, resume refusal, and reviewer prompt/context wiring; re-baselines fixtures with `Kind:`. |
| `tests/test_stage_registry.py` | Modified | Proves the delta-brief structured shrink preserves `Kind:`. |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.86ms`, exit 0) |
| Lint | — | **unverified** (no linter is configured in this repo; `AGENTS.md` lists exactly the gates below and `design.md` §15 says pytest is the only verification) |
| Build | — | **unverified** (no build gate is named by `AGENTS.md`; wheel/sdist construction is exercised inside the suite by `tests/test_packaging.py`) |
| Test | `uv run --frozen pytest` | ✅ Pass (`2446 passed in 49.50s`) — cited from `aidw gate` run `suite`, tree `8615ea492bae`, stage `update-traceability`, 2026-11-20T08:53:46Z; re-asked here against the same tree with the same scope and reused |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`23 checks: 0 failed, 2 warning(s)` — dirty working tree, missing `.mcp.json`) — run here via `aidw gate run doctor`, tree `8615ea492bae`, 2026-11-20T08:54:51Z |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (`resolved repo prompts: 0 error(s), 0 warning(s)`) — run here via `aidw gate run prompts-check`, tree `8615ea492bae`, 2026-11-20T08:54:50Z |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) — run here via `aidw gate run agents-validate`, tree `8615ea492bae`, 2026-11-20T08:54:53Z |
| Whitespace | `git diff --check` | ✅ Pass (exit 0, no output) |

All gates were run with the same scope declared by the workflow's other stages:
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`. No source, test, config or lockfile was excluded.

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2446 | ✅ Pass (`2446 passed in 49.50s`) |

The task's focused files (`tests/test_findings.py`, `tests/test_prompt_workflow.py`, `tests/test_design_doc.py`, `tests/test_stage_registry.py`, `tests/test_prompt_classification.py`) are part of this single run; no subset was re-run to obtain a separate count.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `tests/test_design_doc.py` + `tests/test_workflow_stages_doc.py` + `tests/test_target_repo_config_doc.py` drift check | ✅ Pass (`.................` — 17 tests passed) — cited from `aidw gate` run `traceability`, tree `8615ea492bae`, stage `update-traceability`, 2026-11-20T08:52:53Z |
| `spec-gap` finding ends the run `blocked` (exit 3), gate denied with mechanism `spec-gap`, finding on stderr, no fix/reconcile stage, prompt uncommitted | ✅ Covered in `tests/test_prompt_workflow.py` within the full-suite run |
| Unclassified / unrecognised `Kind:` ends the run `blocked` with mechanism `unclassified` and is checked before the spec-gap stop | ✅ Covered in `tests/test_prompt_workflow.py` within the full-suite run |
| `prompt-gap` findings keep the existing priority-keyed fix/reconcile loop | ✅ Covered in `tests/test_prompt_workflow.py` within the full-suite run |
| `_finding_text_block` round-trips `Kind:` and `to_manifest_entry` has no `kind` key | ✅ Covered in `tests/test_findings.py` and `tests/test_stage_registry.py` within the full-suite run |
| `task-reviewer` stays in `READ_ONLY_AGENTS` and its context mirrors `Kind:` | ✅ `uv run --frozen aidw agents validate --strict` (0 errors) plus `tests/test_prompt_workflow.py` |

---

## Deviations observed during recording

- **No lint or build gate exists** — `AGENTS.md` names exactly `uv sync --frozen`, `uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents validate --strict` and `uv run aidw prompts check`, and `design.md` §15 says pytest is the only verification, so the template's lint/build rows are recorded as unverified rather than invented.
- **The roadmap says "recorded as Z13"** — Z13 is 05-S1.2's roadmap-ownership row and `aidw/conventions.md` forbids reusing an id, so the implementation appended Z18; the roadmap entry itself was left untouched.
- **`prompts/task-review.md` was a byte-frozen bucket (i) file** — editing it required the same class-(v) re-classification C1.3 gave `code-review.md`, recorded in `docs/migration/prompt-classification.md` and pinned by `tests/test_prompt_classification.py`. This was not named by the task prompt's "Gate impact" note.

---

## Non-Goals (NOT implemented)

- ❌ G1.2 "Check task feasibility before the authoring stage" — a separate Python preflight, not started here.
- ❌ No changes to `prompts/task-review-fixes.md` or `agents/task-fixer/AGENTS.md` — spec gaps never reach the fixer, and prompt gaps flow through the existing fix loop unchanged.
- ❌ No change to the code-review manifest shape (`to_manifest_entry`) or to the `review`/`fix` workflows — `Kind:` is prompt-review-only.
- ❌ No new prompt/agent id, no new checker, no status-vocabulary, schema or CI change — the new gate `mechanism` values are gate-detail strings, not a `state.py` status.
- ❌ No pull request opened, and no commit/push of this change set — the `/pr` stage owns delivery.
