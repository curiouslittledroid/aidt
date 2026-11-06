# Build Results — 00-E9.4: README rewrite

**Branch:** `00-E9.4`
**Date:** 2026-11-06
**Spec:** `docs/tasks/00 - Extraction.md` — Epic E9, E9.4; `docs/migration/EXTRACTION.md` §3.12 (new repo layout); `design.md` §1.1 (two roots and a state root), §3/§3.2 (repository layout; `aidw/` means two things), §9.1 (run state layout), §12.4 (environment and secrets; the `gh` ≥ 2.94 probe)

## Summary

**Purpose:** Rewrite the operator guide from the pre-extraction viewpoint ("the toolkit lives at `aidt/` inside the Mythical Forge repo, run everything from there") to the post-extraction one — an installed `aidw` driving Pi against a target repo, with a toolkit root and a target repo root that are never interchangeable (`design.md` §1.1).

| Decision | Why it matters |
|----------|---------------|
| Delete the "Interim state" banner and sweep every pre-extraction *path* phrase, but keep the bare word `aidt` in the provenance note and install/release URLs | `aidt` is the repository's name; a blanket `rg "aidt"` sweep would delete the install commands and the provenance trail. The banned markers are the path phrases (`cd aidt`, `aidt/runs/`, `aidt/prompts/`, `aidt/agent-configs`, `aidt/aidw/`, `./aidt/aidw/aidw doctor`) plus the two whole-sentence `aidt/` markers and "Interim state" / "design F5". |
| The installed `aidw` is the command position throughout; `uv sync` / `uv run aidw` survive only in the Development section | The README is the *operator* guide: a reader has already installed the toolkit. A toolkit developer needs the checkout forms in exactly one place, or that section stops being reproducible. The payload after `aidw gate run <key> --` is the *target repo's* command and keeps its real form (`uv run --frozen pytest`, `pnpm -r test`). |
| Run state is documented as `<state root>/<repo-slug>/runs/<run-id>/`, resolved outside every worktree | `design.md` §9.1: pruning a worktree must never delete a run, so the old `aidt/runs/` path would have been wrong even as a relative path. |
| The "Layout" section reproduces the `EXTRACTION.md` §3.12 / `design.md` §3 tree and cross-links `design.md` §3 as the authority instead of re-pasting it unannotated | A second authoritative copy of the tree drifts; the README annotates the same tree for an operator and defers the runtime/development split. |
| Troubleshooting names the failures with their real diagnostics: stale `gh` (`Unknown JSON field: "subIssues"`, `gh` ≥ 2.94.0, `which -a gh`, doctor `gh version` FAIL) and the three worktree-layout failures (`clone-of-a-worktree` / `control worktree` FAIL, the bare directory as target / `target repo` FAIL, git's `fatal: '<branch>' is already checked out at '<path>'` with no doctor check) | The E8.4 vocabulary (`clone-of-a-worktree`, `target repo`, `workspace root`, `state root`, `control worktree`) is the only vocabulary that matches `aidw/layout.py` and `aidw/doctor.py`; inventing check names would send an operator looking for diagnostics that do not exist. The link is to the existing "Supported and rejected layouts" section, not a duplicate. |
| A new drift-proof test, `tests/test_readme_doc.py`, pins the sweep, the quickstart shape, the `aidw/` dual-role note, the troubleshooting rows and the three contract-doc links | The roadmap's Done-when is human-read; a test is the only executable half (AGENTS.md: pytest is the only verification; E9.1/E9.2/E9.3 precedent). A prose-only rewrite can silently revert. |
| The three shipped contracts (`target-repo-config.md`, `roadmap-format.md`, `releasing.md`) are cross-linked, never restated | A second copy of a field table or example drifts from the files the parser/config tests read. |
| The retired "not wired into the product's `pnpm -r test` CI (design F5)" claim is replaced by this repo's own CI (`.github/workflows/ci.yml`) | The toolkit is a separate repository with its own pipeline, so the old claim is factually dead. |

**Where it fits in the roadmap:** Epic E9 (documentation), after E9.1 (rewritten `design.md`), E9.2 (the two contract docs) and E9.3 (`EXTRACTION.md` moved to history), and before E9.5. It is the last phase of the extraction that the operator reads first: E9.1–E9.3 changed the documents the toolkit's *authors* consult, E9.4 changes the document a *user* starts from.

**Scope:** `README.md` (purpose, install, quickstart, workflows, commands, layout, documentation, development, troubleshooting), one new test, the E9.4 roadmap checkbox/notes written by the traceability stage, the task prompt, and this results document. It deliberately stops short of: editing `design.md` (E9.1), the three contract docs or `EXTRACTION.md` (E9.2/E9.3/E8.5), expanding the Phase 01 "Explicit Resources" pointer, and any code, prompt, agent-config, `pyproject.toml`, inventory, checker, status-vocabulary or CI-gate change.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `tests/test_readme_doc.py` | Created | Drift-proof README checks: no "Interim state" banner or pre-extraction path phrase; target-repo purpose and two roots; the `aidw/` dual-role note; the operator quickstart and installed-`aidw` command position; stale-`gh` and the three worktree-layout troubleshooting rows with their real symptoms; the `design.md` §3 layout; the three contract-doc links; the Development-section checkout forms and this repo's CI; plus non-vacuity and a seeded membership-property run (`README_PROPERTY_SEED = 9401`, `README_PROPERTY_RUNS = 40`). |
| `docs/task-prompts/00-E9.4-prompt.md` | Created | Task prompt for E9.4, committed on the branch. |
| `docs/implementation-results/00-E9.4/build-results.md` | Created | This results document, written by the record stage after gating. |
| `README.md` | Modified | Rewritten to the post-extraction viewpoint: target-repo purpose and two roots, install forms, operator quickstart, `<state root>/<repo-slug>/runs/` state layout, installed-`aidw` command position throughout, `EXTRACTION.md` §3.12 layout tree, the three contract-doc links, this repo's own CI, and the stale-`gh` plus worktree-layout troubleshooting rows. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E9.4 `[x]` and records the absence of vector-matrix/coverage-catalog artefacts and the executable evidence in `tests/test_readme_doc.py`. |

---

## Verification Results

All outcomes below were recorded in one run by stage `record-implementation-results` against tree `7c0fa6929d99`, with the scope every stage of this workflow declares: `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`. No command was re-run; every row comes from the single invocation recorded under its gate key.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.42ms`, exit 0). Gate `install`, tree `7c0fa6929d99`, stage `record-implementation-results`, 2026-11-06T10:27:01Z |
| Build | `uv build --out-dir <tmpdir>` | ✅ Pass (`Successfully built …/aidt-0.1.0.tar.gz` and `…/aidt-0.1.0-py3-none-any.whl`). Gate `build`, tree `7c0fa6929d99`, stage `record-implementation-results`, 2026-11-06T10:27:04Z |
| Test | `uv run --frozen pytest` | ✅ Pass (`1898 passed in 26.59s`, exit 0). Gate `suite`, tree `7c0fa6929d99`, stage `record-implementation-results`, 2026-11-06T10:27:41Z |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`: dirty working tree on `00-E9.4`, missing `.mcp.json`). Gate `doctor`, tree `7c0fa6929d99`, stage `record-implementation-results`, 2026-11-06T10:27:46Z |
| Agent configs | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`). Gate `agents-validate`, tree `7c0fa6929d99`, stage `record-implementation-results`, 2026-11-06T10:27:48Z |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (`resolved repo prompts: 0 error(s), 0 warning(s)`; all prompts resolve to toolkit defaults). Gate `prompts-check`, tree `7c0fa6929d99`, stage `record-implementation-results`, 2026-11-06T10:27:50Z |
| Whitespace | `git diff --check` | ✅ Pass (no output, exit 0) |

Lint: **not run** — this repository configures no linter, formatter or type-checker (`AGENTS.md`, `design.md` §15), so it has no lint gate and none was invented. Build was run for packaging sanity; `AGENTS.md`'s configured gate set names only install, pytest, doctor, agents validation and prompts check.

### `uv run --frozen pytest` (full suite)

Both rows come from the single `suite` invocation above. The per-file count was taken from that invocation's JUnit report (added with `PYTEST_ADDOPTS=--junitxml=…`, so the gated command itself is unchanged); no subset was re-run.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1898 | ✅ Pass (`1898 passed in 26.59s`) |
| `tests/test_readme_doc.py` | 14 | ✅ Pass (14/14 `testcase` entries passed in the same run's JUnit report) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Stale-marker sweep: `rg -n 'cd aidt\|aidt/runs/\|aidt/prompts/\|aidt/agent-configs\|aidt/aidw/\|\./aidt/aidw/aidw doctor\|from `aidt/`\|outside `aidt/`\|Interim state\|design F5' README.md` | ✅ No hits (rg exited 1; ran directly, not through `aidw gate`) |
| Legitimate `aidt` references survive: provenance note ("verbatim copy of `aidt/` from `mythical-forge@…`") and install URLs (`git+https://github.com/curiouslittledroid/aidt@…`) | ✅ Both present (`README.md` lines 34, 35, 150, 203) |
| The three shipped contract docs exist and are linked | ✅ Link plus file present for `docs/target-repo-config.md`, `docs/roadmap-format.md`, `docs/releasing.md` (`test -f` exited 0 for each) |
| Drift-proof marker/property test (`test_the_interim_banner_and_pre_extraction_markers_are_gone`, `test_marker_detection_property_is_membership`) | ✅ Passed in the full-suite run (part of the 14 `tests/test_readme_doc.py` cases) |
| Operator quickstart shape: install → bootstrap → `aidw doctor` → `aidw tasks --todo` → `aidw prompt …`, no `cd aidt` / `uv sync` | ✅ Passed (`test_quickstart_is_an_operator_path`, `test_the_installed_aidw_is_the_command_position`) |
| `aidw/` dual-role note present | ✅ Passed (`test_the_dual_role_note_survives`) |
| Troubleshooting carries the stale-`gh` (`subIssues`, `2.94`, `which -a gh`) and worktree-layout rows (`clone-of-a-worktree`, `target repo`/`control worktree` FAILs, git's `already checked out`) cross-linked to "Supported and rejected layouts" | ✅ Passed (`test_troubleshooting_carries_the_stale_gh_failure`, `test_troubleshooting_carries_the_worktree_layout_failures`) |
| Layout matches the `EXTRACTION.md` §3.12 tree and Development owns the checkout forms plus this repo's CI | ✅ Passed (`test_layout_matches_the_extraction_tree`, `test_development_owns_the_checkout_forms_and_this_repos_ci`) |
| Task prompt's standalone command: `uv run --frozen pytest tests/test_readme_doc.py -n0` | ✅ Covered by the full-suite run (14/14 passed); not re-run separately, per the one-invocation rule |

---

## Deviations observed during recording

- **Implementation and traceability changes are uncommitted on the branch** — `git status` shows modified `README.md` and `docs/tasks/00 - Extraction.md`, and untracked `tests/test_readme_doc.py`; only the task prompt is committed. Recording verified the working tree relative to `main` and did not commit.
- **No standalone targeted suite run** — the task prompt's Done-when names `uv run --frozen pytest tests/test_readme_doc.py -n0`. Rather than buy a second pytest invocation, its 14 cases were counted from the JUnit report of the same `suite` run, with the gated command left exactly as the repo writes it.
- **No lint gate exists in this repo** — `AGENTS.md` states pytest is the only verification, so the lint key from the generic gate idiom was not run and no lint row claims a result.

---

## Non-Goals (NOT implemented)

- ❌ Phase 01 "Explicit Resources" documentation — the README keeps `EXPLICIT-RESOURCES.md` as a pointer only; unimplemented behaviour is not expanded (task prompt, Explicit non-goals).
- ❌ `design.md` edits, including its §16 status table — E9.1 owns them (task prompt, Explicit non-goals).
- ❌ `docs/target-repo-config.md`, `docs/roadmap-format.md`, `docs/releasing.md` and `docs/migration/EXTRACTION.md` edits — E9.2/E9.3/E8.5 own them; only cross-linked (task prompt, Explicit non-goals).
- ❌ MF.1–MF.6 Mythical Forge cutover — product-side work in the other repository (task prompt, Explicit non-goals).
- ❌ Any code, prompt, agent-config, `pyproject.toml` or inventory change — docs plus one test only (task prompt, Explicit non-goals).
- ❌ Commit, push, or PR — the `pr` stage owns delivery (record-stage non-goal).
