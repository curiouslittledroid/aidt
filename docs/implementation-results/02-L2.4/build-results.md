# Build Results — 02-L2.4: Hand the agents an evidence bundle

**Branch:** `02-L2.4`
**Date:** 2026-10-27
**Spec:** `docs/tasks/02 - Prompt loop integrity.md` — task L2.4 ("Hand the agents an evidence bundle"), Epic L2 ("Reviewer authority — stop the wrong prescription"), including the phase preamble's E7.1–E7.4 gate note ("L2.4's evidence bundle is D16's mechanism") and the "Explicit non-goals for phase 02". `design.md` §8.1 (`aidw prompt <phase> <epic> <task>` — the `task-review-N` stage and the P2a fix loop). `docs/migration/EXTRACTION.md` §3.8 (D16, task-prompt format: repo conventions injected from target root `AGENTS.md`). `AGENTS.md` (Gates; Tests; "Two roots"; "Prompts and agent configs are the product contract").

## Summary

**Purpose:** Give every review round and every fix stage a written evidence bundle at `<run_dir>/stages/<stage>.evidence.md` and a pointer to it in the stage's `extra`, so reviewers and fixers stop spending ~150k input tokens and 18–20 tool calls re-deriving the prompt path, roadmap entry, cited spec sections, prerequisite tick state, gate commands and base-branch revisions that the author already gathered.

| Decision | Why it matters |
|----------|---------------|
| The bundle is rendered and written by a plain writer in `aidw/workflows/prompt.py`, passed through the existing `StageSpec.extra`, not by a new prompt file | `prompts/task-review.md` and `prompts/task-review-fixes.md` are shipped product prompts; priming is runtime assembly, so no shipped-prompt edit, no new prompt file and no `aidw/inventory.py:REQUIRED_PROMPTS` change (L2.3's precedent). |
| The pointer is **prepended** to every review and fix `extra` via `_with_evidence`, including the fallback whole-review fix and the per-finding / `render_could_fix_block` stages | One missed `extra` site silently breaks "each review and fix stage's prompt names its evidence path"; the fallback fix (whose `extra` is the whole review text) is the easiest to miss. |
| The bundle lands inside the run directory and the pointer is **absolute** | The reviewer/fixer `cwd` is the repo root while the run dir lives under the state root, outside the tree; a relative `stages/...` pointer resolves nowhere. The file stays out of the working tree, so no `.gitignore` change and the tree stays clean. |
| Degrade, never error: every source read is wrapped and every failure becomes an explicit "unavailable" note; a write failure returns `None`, warns on stderr and omits the pointer | The bundle is an optimisation, never a gate. A missing `AGENTS.md`, a failed `rev_parse` or an unwritable `stages/` must leave the run exactly as before. This mirrors L2.3's `_render_delta_brief` unavailable-note path and `_verify_base_branch`'s warn-and-continue. |
| Round 1 carries the pointer but no delta brief | L2.3's "unprimed" guarantee is about *prior findings*, not the gathered context the reviewer already reads via its Scope step; the delta brief stays keyed off `review_index >= 2`. |
| `--dry-run` is untouched — the writer lives only in the real loop | The dry-run path plans `task-review-1` and returns before the loop, so it writes no evidence file and adds no pointer. |
| The gate block is read from `repo.root / "AGENTS.md"` (target root), and `aidw/conventions.md` is **not** read | Per D16 the eventual source is root `AGENTS.md` + optional `aidw/conventions.md`, but E7.3 has not landed; reading the target root directly (never `ToolkitPaths` or a cwd-relative path) is what keeps the read correct after extraction. Ignoring the absent second channel avoids building E7.3's abstraction early. |

**Where it fits in the roadmap:** Phase 02, Epic L2 ("Reviewer authority — stop the wrong prescription"), and the last L2 task: L2.1 (dependency inspection / `Blocked`) and L2.2 (verified-revision evidence) and L2.3 (delta brief) precede it. The bundle is the mechanism D16 formalises for target-repo conventions injection; E7.3 will extend it into a reusable channel rather than a second one. It leaves the fixer stages (L3.x), the terminal-review budget and recording (L4.x) untouched, and opens no `design.md` §17 entry — L6.2 consolidates phase 02's decisions.

**Scope:** Adds the evidence-bundle renderers/writer, the pointer helpers and the per-stage wiring to `aidw/workflows/prompt.py`, plus the fixture, helpers and nine L2.4 test instances in `tests/test_prompt_workflow.py`, and the L2.4 roadmap tick. It deliberately stops short of generalising the mechanism into D16's reusable conventions channel (E7.3), the L3.x fixer work (verify/sweep/snapshot/reconcile), the L4.x terminal-review work, snapshotting the per-stage prompt (`stages/<stage>.prompt.md`, owned by L3.3), any shipped-prompt edit, and any `design.md` §8.1/§17 amendment.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L2.4-prompt.md` | Created (committed) | The task prompt authored on the branch before implementation (commits `b599e0d`, `76e0dae`). |
| `aidw/workflows/prompt.py` | Modified (uncommitted) | Added the evidence-bundle section (`_roadmap_lines`, `_done_when_block`, `_locate_doc`, `_decision_section`, `_render_cited_specs`, `_render_prerequisites`, `_gate_block`, `_render_base_branch`, `_render_evidence_bundle`, `_write_evidence_bundle`, `_evidence_pointer`, `_stage_evidence_pointer`, `_with_evidence`) with the `_EVIDENCE_UNAVAILABLE` note, `_GATES_HEADING` and the line/token/section regexes; prepended the pointer at every `task-review-*` and `task-review-fixes-*` `StageSpec` (round 1, rounds 2+, both fallback/per-finding fix paths); documented the bundle in the module docstring. |
| `tests/test_prompt_workflow.py` | Modified (uncommitted) | Added the `_evidence_repo` fixture (multi-line `Done when`, ticked + unticked predecessors, target-root `AGENTS.md` gate block, no `origin`) and `_evidence_path` helper, nine L2.4 test instances, and updated the existing round-1 and fix-`extra` assertions to accept the prepended pointer. |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified (uncommitted) | Roadmap escalation: L2.4 checkbox ticked (traceability artifact owned by the update-traceability stage). |

---

## Verification Results

> **This run failed.** The full suite reports `1 failed, 629 passed`; the failure is a genuine implementation defect in the L2.4 evidence writer (the unreadable-prompt degradation path is not implemented). Per the record stage's rule the failure is recorded and **not fixed here**.

### Top-level verification

All commands were run through `aidw gate run <key> -- ...` with the `pr.md` scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`, against tree `beefc9819d14` (the tree that includes the uncommitted working-tree change set) by stage `record-implementation-results`. Every outcome below is a real observation from this run; none was reused from an earlier stage or run.

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Exit 0 — `Checked 15 packages in 5ms` (gate `install`, tree `beefc9819d14`, 2026-10-27T06:24:40Z, 0.047s) |
| Build | `uv build --out-dir <tmp>` | ✅ Exit 0 — built `aidt-0.1.0-py3-none-any.whl` and `aidt-0.1.0.tar.gz` (gate `build`, tree `beefc9819d14`, 2026-10-27T06:24:48Z, 3.013s) |
| Test | `env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ❌ Exit 1 — **`1 failed, 629 passed in 67.01s`** (gate `suite`, tree `beefc9819d14`, 2026-10-27T06:26:01Z, 68.042s) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)` (branch `02-L2.4` dirty; `.mcp.json` absent) (gate `doctor`, tree `beefc9819d14`, 2026-10-27T06:26:27Z, 2.99s) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `beefc9819d14`, 2026-10-27T06:26:46Z, 0.406s) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `beefc9819d14`, 2026-10-27T06:26:47Z, 0.261s) |
| Whitespace | `git diff --check` | ✅ Exit 0 — no whitespace errors (gate `whitespace`, tree `beefc9819d14`, 2026-10-27T06:26:47Z, 0.034s) |

The `suite` gate ran fresh for this stage and tree (no reusable outcome existed for this run's gate key), so `record-implementation-results` bought the full suite once for tree `beefc9819d14`; every subset row below derives from that single invocation.

### `env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` (full suite)

Single invocation: **`1 failed, 629 passed in 67.01s`** (exit 1, gate `suite`, tree `beefc9819d14`, 2026-10-27T06:26:01Z). No second run was made to obtain the subset rows; they are taken from that run's collected set and failure output.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 630 | ❌ Fail (`1 failed, 629 passed in 67.01s`) |
| New L2.4 tests in `tests/test_prompt_workflow.py` | 9 | ❌ Fail (`8 passed, 1 failed` — the run reported exactly one failing test, `test_l24_unreadable_prompt_is_explicitly_unavailable`) |

### Task-specific verification gates

All L2.4 proofs run inside the single full-suite invocation above. **One proof fails**, so the task's "Done when" is not met.

| Gate | Status |
|------|--------|
| Each review and fix stage has its own on-disk evidence file inside the run directory, and its `extra` names that file's **absolute** path, prepended rather than replacing the stage's own content | ✅ `test_l24_every_review_and_fix_stage_has_its_own_evidence_file` passes |
| The fallback whole-review fix (the easiest `extra` site to miss) also has its own evidence file and keeps `## Review findings to address` after the pointer | ✅ `test_l24_fallback_whole_review_fix_also_has_its_own_evidence` passes |
| One bundle carries all six elements: prompt path; roadmap entry + full multi-line `Done when`; `design.md` and `EXTRACTION.md` cited sections; every predecessor's `[x]`/`[ ]` state; the target-root `AGENTS.md` gate block bounded before `## Tests`; local base sha plus the explicit `origin/main: absent/unverifiable` note | ✅ `test_l24_bundle_contains_the_six_elements` passes |
| `--dry-run` writes no evidence bundle and adds no pointer | ✅ `test_l24_dry_run_writes_no_evidence_bundle` passes |
| A writer forced to return `None` degrades the run to a normal exit with an "could not be written" note and no `.evidence.md` pointer | ✅ `test_l24_unwritable_bundle_degrades_without_a_dangling_pointer` passes |
| An unreadable prompt path is reported as `unavailable` in the bundle's Task-prompt section | ❌ **Fail** — `test_l24_unreadable_prompt_is_explicitly_unavailable`: the Prompt-section text is `\n\n- path: \`docs/task-prompts/missing-prompt.md\`\n\n`, with no `unavailable` note |
| The writer itself never raises on an unwritable `stages/` path: it warns on stderr and returns `None` | ✅ `test_l24_writer_failure_returns_none_and_warns` passes |
| A missing `AGENTS.md` or a missing `## Gates` section degrades only that section to `unavailable` while the rest of the bundle stays usable | ✅ `test_l24_missing_gate_source_notes_the_section_unavailable` passes (both parametrisations) |
| No new prompt file and no `aidw/inventory.py` change; `prompts check` clean | ✅ `uv run --frozen aidw prompts check` clean; the change set touches no prompt or inventory file |
| Diff confined to the two deliverable files (plus the task prompt and roadmap tick) | ✅ Change set is exactly `aidw/workflows/prompt.py`, `tests/test_prompt_workflow.py`, `docs/task-prompts/02-L2.4-prompt.md`, `docs/tasks/02 - Prompt loop integrity.md` |

---

## Deviations observed during recording

- **The record prompt names a Node/pnpm gate example; this toolkit is Python/uv.** `prompts/record-implementation-results.md` uses `pnpm install` / `pnpm -r lint` / etc. as illustrative commands, and `pr.md` keys gates off the repo's actual stack. This repo has `pyproject.toml`/`uv.lock`, so its gates are `uv sync --frozen`, `uv build`, `uv run --frozen pytest`, plus the `AGENTS.md` gate set (doctor, agents validate, prompts check). No `pnpm` command was run because this repo has no `pnpm-workspace.yaml`, and the task prompt names no `pnpm srd:*` gate.
- **The suite gate runs under `env -u AIDW_STAGE -u AIDW_RUN_ID`.** The record stage itself runs with `AIDW_RUN_ID=20261027T054350Z-02-L2.4-implement` and `AIDW_STAGE=record-implementation-results` exported; L2.3's recording showed the leaked identity makes `tests/test_verification.py`'s gate-run tests fail against an unknown run and record the wrong stage. The suite gate above scrubs both variables for the pytest subprocess (the outer `aidw gate run` still reads them to record the outcome), so the reported `1 failed, 629 passed` isolates the genuine L2.4 failure. No implementation or test file was modified to achieve this.
- **The genuine failure is an implementation defect, not a test artifact.** `_render_evidence_bundle` renders the Task-prompt section as `- path: \`{rel}\`` without ever reading the prompt file, so a `rel` that does not exist is presented as usable evidence. L2.4 requirement 4 requires an unreadable prompt to yield an explicit "unavailable" note; the test asserts exactly that. Per the record stage's rule, the failure is recorded and **not fixed here**.
- **Every gate printed the EXTRACTION.md §3.10 single-checkout warning.** This toolkit checkout is a single working tree, so the advisory is emitted before each command. It is the intended warning, not a gate failure; for `agents-validate` the warning also became the gate's recorded last non-blank summary line, while the command's own output showed `11 agent config(s): 0 error(s), 0 warning(s)`.
- **No task-specific command beyond the full suite was named in `02-L2.4-prompt.md`.** The task's proofs are the new evidence-bundle fixtures and assertions, all inside the full `pytest` invocation; there is no separate live CLI gate.

---

## Non-Goals (NOT implemented)

- ❌ L3.x (fixer verify/sweep/snapshot/reconcile) and L4.x (terminal-review budget honesty, recording, config) — the rest of phase 02 (task prompt, Explicit non-goals).
- ❌ `stages/<stage>.prompt.md` per-stage prompt snapshots — L3.3 owns those; the evidence file is a distinct artifact and the prompt is not snapshotted here (task prompt, Explicit non-goals).
- ❌ The E7.3 (D16) generalisation of this mechanism into a reusable conventions channel — a plain writer in `prompt.py` is enough, and E7.3 will extend it (task prompt, Explicit non-goals).
- ❌ Any `design.md` §8.1 amendment or §17 decision entry — L6.2 consolidates phase 02's decisions (task prompt, Explicit non-goals).
- ❌ `prompts/task-review.md`, `prompts/task-review-fixes.md` and `prompts/task-prompt.md` are untouched — no re-neutralisation of E7-owned prompts (task prompt, Explicit non-goals).
- ❌ No new prompt file and no `aidw/inventory.py:REQUIRED_PROMPTS` change (task prompt, Explicit non-goals).
- ❌ `aidw/conventions.md` is deliberately not read (E7.3 owns that second channel), and the toolkit root is never the gate source — `AGENTS.md` is read from the target repo root (task prompt, requirements 2 and 5).
- ❌ No PR opened and nothing committed by this stage (record-implementation-results non-goals; `pr.md` owns delivery).

---

## Deliverables Checklist

- [x] `aidw/workflows/prompt.py` — evidence-bundle renderers, `stages/<stage>.evidence.md` writer, absolute pointer helper, per-review/per-fix `extra` wiring (round 1, rounds 2+, fallback and per-finding fixes), degradation path, and the module docstring update.
- [x] `tests/test_prompt_workflow.py` — `_evidence_repo`/`_evidence_path` fixture helpers plus nine L2.4 test instances covering existence/location/absolute reference, the fallback fix, the six bundle elements, dry-run, writer failure, unreadable prompt, and the missing gate source.
- [ ] The L2.4 suite green — **not met**: `test_l24_unreadable_prompt_is_explicitly_unavailable` fails (`1 failed, 629 passed`). Recorded, not fixed here.
