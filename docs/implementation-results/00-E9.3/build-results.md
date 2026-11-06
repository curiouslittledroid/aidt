# Build Results — E9.3: Move this document to history

**Branch:** `00-E9.3`
**Date:** 2026-11-06
**Spec:** `docs/tasks/00 - Extraction.md` — Epic E9, E9.3; `docs/migration/EXTRACTION.md` §3.12 ("this document, kept as history"); `design.md` §3 (repository layout), §17 (resolved decisions)

## Summary

**Purpose:** Finalise `docs/migration/EXTRACTION.md` as history in place by replacing its stale live-status front-matter with a historical header that redirects readers to `design.md` (design of record) and `docs/tasks/00 - Extraction.md` (the repo's own roadmap).

| Decision | Why it matters |
|----------|---------------|
| The plan is marked historical **in place** at `docs/migration/EXTRACTION.md`; no `git mv` to `docs/history/` | §3.12, `design.md` §3 and `tests/test_design_doc.py::test_contract_links_are_existing_cross_references` pin the existing path, and `design.md`/`AGENTS.md`/README cite it there. A relocation would break the path pin and every citation. |
| The stale status, audience and live source-of-truth lines are **replaced**, not appended to | "HISTORICAL" above "not yet started" / "Source of truth today" would be a self-contradicting header. A Mythical Forge mention remains only as provenance. |
| §2 (D1–D24), §6 (E0.1–E9.4) and §10 (R1–R18) are preserved intact, including §6's checkbox tally | `design.md` §17 retains the decision trail by reference to these sections. The document is historical as written, so its own E9.3 checkbox is not ticked inside §6. |
| The historical status is pinned by a new drift test, `tests/test_extraction_doc.py`, in the style of `tests/test_design_doc.py` | A prose-only header edit can silently revert. The test checks the header, the absence of live-status claims, the survival of the decision trail, the pinned path, and proves its checks non-vacuous by doctoring the document in memory. |
| The roadmap entry records E9.3 as done with notes explaining the in-place scope | `update-traceability` owns the roadmap checkbox; E9.3 itself changes only the plan header plus the new test. |

**Where it fits in the roadmap:** Epic E9 (documentation), after E9.1 (`design.md` rewrite) and E9.2 (the two contract docs), and before E9.4 (README rewrite). It completes the extraction plan's transition from live plan to historical record while keeping its decision trail available to `design.md` §17.

**Scope:** A front-matter-only edit to `docs/migration/EXTRACTION.md`, one new drift test, the E9.3 roadmap checkbox/notes written by the traceability stage, the task prompt, and this results document. The 1318-line plan body is deliberately untouched, and no toolkit code, config, prompts, schema or gate changes were made.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `tests/test_extraction_doc.py` | Created | Drift-proof checks that the plan is historical, names both live artifacts, has no live-status claims, keeps §2/§6/§10 intact, and stays at its pinned path; includes in-memory reversion checks proving non-vacuity. |
| `docs/task-prompts/00-E9.3-prompt.md` | Created | Task prompt for E9.3, committed on the branch. |
| `docs/implementation-results/00-E9.3/build-results.md` | Created | This results document, written by the record stage after gating. |
| `docs/migration/EXTRACTION.md` | Modified | Front-matter only: replaces the "not yet started" / "No code has moved" / "Source of truth today" lines with a historical header naming `design.md` and `docs/tasks/00 - Extraction.md`; body unchanged. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E9.3 `[x]` and records the in-place scope, the absence of vector-matrix/coverage-catalog artefacts, and the executable evidence in `tests/test_extraction_doc.py`. |

---

## Verification Results

All outcomes below were recorded in one run by stage `record-implementation-results` against tree `a52860b3097f`, with the scope every stage of this workflow declares: `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.41ms`, exit 0). Gate `install`, tree `a52860b3097f`, stage `record-implementation-results`, 2026-11-06T09:45:46Z |
| Build | `uv build --no-build-isolation --out-dir <tmpdir>` | ✅ Pass (`Successfully built …/aidt-0.1.0.tar.gz` and `…/aidt-0.1.0-py3-none-any.whl`). Gate `build`, tree `a52860b3097f`, stage `record-implementation-results`, 2026-11-06T09:45:48Z |
| Test | `uv run --frozen pytest` | ✅ Pass (`1884 passed in 28.09s`, exit 0). Gate `suite`, tree `a52860b3097f`, stage `record-implementation-results`, 2026-11-06T09:46:19Z |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`: dirty working tree on `00-E9.3`, missing `.mcp.json`). Gate `doctor`, tree `a52860b3097f`, stage `record-implementation-results`, 2026-11-06T09:46:22Z |
| Agent configs | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`). Gate `agents-validate`, tree `a52860b3097f`, stage `record-implementation-results`, 2026-11-06T09:46:24Z |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (`toolkit defaults: 0 error(s), 0 warning(s)`; `resolved repo prompts: 0 error(s), 0 warning(s)`). Gate `prompts-check`, tree `a52860b3097f`, stage `record-implementation-results`, 2026-11-06T09:46:26Z |
| Whitespace | `git diff --check` | ✅ Pass (no output, exit 0) |

Lint: **not run** — this repository configures no linter, formatter or type-checker (`AGENTS.md`, `design.md` §15), so it has no lint gate and none was invented. Build was run for packaging sanity; `AGENTS.md`'s configured gate set names only install, pytest, doctor, agents validation and prompts check.

### `uv run --frozen pytest` (full suite)

Every row is taken from a single invocation; no subset was re-run to obtain a count.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1884 | ✅ Pass (`1884 passed in 28.09s`) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Task prompt's targeted suite: `uv run --frozen pytest tests/test_extraction_doc.py tests/test_design_doc.py -n0` | ✅ Pass (`22 passed in 0.02s`). Gate `task-tests`, tree `a52860b3097f`, stage `record-implementation-results`, 2026-11-06T09:46:29Z |
| Stale live-status sweep: `rg "not yet started\|No code has moved\|Source of truth today" docs/migration/EXTRACTION.md` | ✅ No hits (rg exited 1; ran directly, not through `aidw gate`) |
| Pinned path: `docs/migration/EXTRACTION.md` still exists and `docs/history/EXTRACTION.md` does not | ✅ Pass (`test -f` / `test ! -e` both exit 0) |
| Header states "historical" and "complete" and names `design.md` plus `docs/tasks/00 - Extraction.md` | ✅ Pass (`test_header_marks_the_plan_historical_and_names_the_live_artifacts` passed in the targeted and full-suite runs) |
| No live-status claim survives anywhere in the document | ✅ Pass (`test_no_live_status_claim_survives_the_header` passed in the targeted and full-suite runs) |
| Decision trail §2/§6/§10 survives with identifiers and content | ✅ Pass (`test_decision_trail_survives_the_historical_header` passed in the targeted and full-suite runs) |
| The checks are non-vacuous (reverted status, dropped pointer, blanked row, deleted §10 and ticked §6 box each fail; compliant header passes) | ✅ Pass (`test_the_checks_are_not_vacuous` passed in the targeted and full-suite runs) |
| Existing path pin remains green: `tests/test_design_doc.py::test_contract_links_are_existing_cross_references` | ✅ Pass (included in the `22 passed` targeted run; no path change was made) |

---

## Deviations observed during recording

- **Implementation and traceability changes are uncommitted on the branch** — `git status` shows modified `docs/migration/EXTRACTION.md` and `docs/tasks/00 - Extraction.md`, and untracked `tests/test_extraction_doc.py`. Recording verified the working tree relative to `main` and did not commit.
- **The task prompt's targeted pytest command was run as its own task-specific gate** — the prompt's Done-when names it, so it is recorded under gate `task-tests` (`22 passed`) in addition to the full-suite gate, not as a second full-suite run.
- **Build was run although the configured gate set does not name it** — included for packaging sanity, reported with its real outcome, and it has no effect on the repository.

---

## Non-Goals (NOT implemented)

- ❌ E9.4: README rewrite — next task (task prompt, "Explicit non-goals").
- ❌ `design.md` edits — E9.1 owns `design.md`, including the stale §16 "move `EXTRACTION.md` to `docs/history/`" phrasing and its "Remaining roadmap work" line (task prompt, "Explicit non-goals").
- ❌ Body cleanup of the plan — §0 instructions, §6 checkboxes, §8 acceptance criteria and §9 non-goals stay as the historical record; only the header changed (task prompt, "Explicit non-goals").
- ❌ Physically relocating the document to `docs/history/` or deleting/renaming it — "move to history" is the historical-status step, not a `git mv` (task prompt, requirements 1 and "Traps").
- ❌ Rewriting, deleting, blanking or renumbering §2 (D1–D24), §6 (task list) or §10 (R1–R18) (task prompt, requirements 4–5).
- ❌ Changing toolkit code, tests outside the new drift test, prompts, agent configs, schema or gates — docs plus one test only (task prompt, "Gate impact").
- ❌ Committing, pushing or opening a PR — the `/pr` stage owns delivery.
