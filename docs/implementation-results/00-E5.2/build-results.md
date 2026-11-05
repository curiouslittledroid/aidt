# Build Results — 00-E5.2: Generalise the parser

**Branch:** `00-E5.2`
**Date:** 2026-11-05
**Spec:** `docs/migration/EXTRACTION.md` §3.7 (roadmap model, D6/D15), §2 (locked decisions D6/D15/D17); `docs/roadmap-format.md` §1, §3 and §6; `design.md` §11 (roadmap task selection); `aidw/roadmap.py`; `aidw/target_config.py`; `aidw/cli.py`; `aidw/workflows/prompt.py`; `docs/tasks/00 - Extraction.md` E5.2

## Summary

**Purpose:** Drive the roadmap parser from the target repo's `paths.roadmap_dir` +
`paths.roadmap_glob` instead of a hardcoded `docs/tasks`, so the roadmap format is AIDT-owned while
the directory and filename pattern are the entire per-repo surface (D15).

| Decision | Why it matters |
|----------|---------------|
| `load_tasks(tasks_dir, glob)` — the glob is required, no default in `roadmap.py` | The single home of the default is `TOOLKIT_DEFAULTS.paths.roadmap_glob` (D17); a second copy in the parser would drift the way the `repo:` defaults are pinned against. |
| `_FILENAME_RE` stays the phase authority; the glob only pre-selects | `0 - x.md` and `0123 - x.md` match the default glob but must still be dropped, and the phase must always come from the filename prefix, never the `# Phase` heading. |
| `roadmap_dir` threaded into the evidence bundle as a **required** parameter | `_roadmap_lines` is the second consumer of the roadmap directory (roadmap-format.md §6); a default would silently re-read the wrong directory under a non-default `roadmap_dir`. |
| `aidw tasks` resolves `aidw/config.yaml` and fails closed on ERROR issues | E3.2/E3.3: a broken config is never silently resolved to defaults, so a typo cannot list the wrong or an empty roadmap. It deliberately skips `validate_paths`, so a roadmap-only repo still lists. |
| `CITATION_RE` (`Design N`) left untouched | It is the documented §8.1 citation channel, not a product assumption; removing it would empty every `RoadmapTask.citations`. |

**Where it fits in the roadmap:** Epic E5 (roadmap as an AIDT-owned format, D6/D15). It builds on
E5.1's format contract and the E3.2/E3.3 config resolver, and it unblocks E5.3 (format validation)
and E5.4 (promoting the canonical example), which can now assume the configured-location reader.

**Scope:** Changes the parser signature and docstring, rewires both `docs/tasks` consumers in
`aidw/workflows/prompt.py`, makes `aidw tasks` config-driven, and flips the two E5.2 status markers
in `docs/roadmap-format.md`. It deliberately stops short of adding format validation, moving the test
fixture, adding a roadmap to `fixtures/target-repo/`, or introducing any per-repo dialect.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E5.2-prompt.md` | Created | Task prompt added on the branch by the prompt-authoring stage. |
| `docs/implementation-results/00-E5.2/build-results.md` | Created | This recording document. |
| `aidw/roadmap.py` | Modified | `load_tasks` takes a required `glob`; module docstring neutralised (configured directory, generic phase-id rule); `_FILENAME_RE` and `CITATION_RE` unchanged. |
| `aidw/cli.py` | Modified | `tasks` resolves `aidw/config.yaml`, fails closed on ERROR issues, and reads `paths.roadmap_dir`/`paths.roadmap_glob`; docstring neutralised; no `validate_paths`. |
| `aidw/workflows/prompt.py` | Modified | `load_tasks` call and `_roadmap_lines` read the resolved roadmap dir/glob; resolved `roadmap_dir` threaded through `_stage_evidence_pointer` → `_write_evidence_bundle` → `_render_evidence_bundle`; module docstring neutralised. |
| `design.md` | Modified | §11 documents the configured roadmap dir/glob, the glob-vs-`_FILENAME_RE` split, the `aidw tasks` fail-closed/no-preflight behaviour, and the corrected `--show`/preflight surface. |
| `docs/roadmap-format.md` | Modified | Flips the §1 E5.2 status marker, the §3 "Until it lands" sentence, and updates the E0.7 guard command to pass the glob. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks `E5.2. Generalise the parser` as done. |
| `tests/test_roadmap.py` | Modified | Glob-argument updates plus selection tests: regex remains the phase authority, a non-default glob drives selection, missing dir is empty, purity/repeatability, and a seeded property run. |
| `tests/test_roadmap_format.py` | Modified | Passes the default glob explicitly at the one `load_tasks` call. |
| `tests/test_cli.py` | Modified | `aidw tasks` tests: configured dir + glob (no `docs/tasks` present), absolute dir wins, default still lists with no config, malformed config fails closed, no read-path preflight. |
| `tests/test_prompt_workflow.py` | Modified | New evidence-bundle re-read test using a non-default dir/glob; two existing direct callers updated to the new `load_tasks`/`_write_evidence_bundle` signatures. |

---

## Verification Results

Every gate command was run once, through `aidw gate run`, with the same scope —
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` —
for tree `d8b4f88bd062`, stage `record-implementation-results`, on 2026-11-05. The rows below report
this run's own outcomes; no suite, module or subset was re-run to obtain a count. `uv sync --frozen`
and `git diff --check` were run directly because neither is a recorded gate.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 15 packages in 0.83ms`) |
| Build | `uv build --out-dir <tmp>` | ✅ Pass (gate `build`, tree `d8b4f88bd062`, 2026-11-05T00:54:07Z: `Successfully built .../aidt-0.1.0-py3-none-any.whl`) |
| Test | `uv run --frozen pytest` | ✅ Pass (gate `suite`, tree `d8b4f88bd062`, 2026-11-05T00:54:39Z: `1312 passed in 29.58s`) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (gate `doctor`, tree `d8b4f88bd062`, 2026-11-05T00:54:42Z: `19 checks: 0 failed, 2 warning(s)` — dirty working tree and absent `.mcp.json`, both expected mid-run) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (gate `agents`, tree `d8b4f88bd062`, 2026-11-05T00:54:42Z: `11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (gate `prompts`, tree `d8b4f88bd062`, 2026-11-05T00:54:43Z: `prompts check: 0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (no output) |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1312 | ✅ Pass (`1312 passed in 29.58s`) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `rg -n 'docs/tasks\|"docs" / "tasks"' aidw/roadmap.py aidw/cli.py aidw/workflows/prompt.py` | ✅ No matches (`rg` exit 1) — every consumer reads the resolved `paths.roadmap_dir` |
| `rg -n 'docs/tasks' aidw/target_config.py` | ✅ Only the D17 default remains (`roadmap_dir="docs/tasks"`, plus docstrings) |
| E0.7 no-collapsed-id guard: `load_tasks(Path("docs/tasks"), "[0-9]* - *.md")` over the real roadmap | ✅ `111 tasks, none collapsed` |
| `tests/test_roadmap.py` — glob pre-selects, `_FILENAME_RE` is the phase authority, non-default glob drives selection, missing dir empty, purity, seeded property run | ✅ Covered by the full-suite run above |
| `tests/test_cli.py` — `aidw tasks` is config-driven (no `docs/tasks`), absolute dir wins, default with no config, malformed config fails closed, no read-path preflight | ✅ Covered by the full-suite run above |
| `tests/test_prompt_workflow.py` — evidence-bundle re-read follows the configured dir/glob (second reader) | ✅ Covered by the full-suite run above |
| `tests/test_roadmap_format.py` — worked example still parses with the explicit glob | ✅ Covered by the full-suite run above |
| Exact `AGENTS.md` gate set (`uv sync --frozen`, `uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents validate --strict`, `uv run aidw prompts check`) | ✅ All five passed as recorded above |

---

## Deviations observed during recording

- **The generic record prompt names a pnpm gate set, but this repo's stack is Python/uv.** Per
  `AGENTS.md` and `prompts/pr.md` ("take them from the target repo, not from this prompt"), the
  install/build/test rows are `uv sync --frozen`, `uv build` and `uv run --frozen pytest`. No lint
  gate was run because the repo configures no linter.
- **`uv build` wrote to a fresh `$(mktemp -d)` directory**, leaving no artifacts in the gated tree.
- **The change set contains two files beyond the prompt's deliverables list:** the branch's task
  prompt (`docs/task-prompts/00-E5.2-prompt.md`, added by the prompt-authoring stage) and the
  roadmap `[x]` marker for E5.2. Both are expected stage-owned edits, not implementation changes.
- **No subsets were re-run for their own counts.** The rows describing individual test modules cite
  the single full-suite invocation above rather than a second run.

---

## Non-Goals (NOT implemented)

- ❌ E5.3 — format validation with file/line/rule errors for missing `Done when`, duplicate ids, or
  entries outside an epic; the parser still does not validate (task prompt, explicit non-goals).
- ❌ E5.4 — promoting `tests/test_roadmap.py`'s inline fixture into `docs/roadmap-format.md` and
  rewiring that test; the fixture did not move (task prompt, explicit non-goals).
- ❌ Any per-repo parser or dialect (D15) — no configurable regexes, heading syntax or parser
  variant; `paths.roadmap_dir` + `paths.roadmap_glob` remain the whole surface (task prompt).
- ❌ A roadmap in `fixtures/target-repo/` — the acceptance fixture is a test-built repo (task
  prompt, explicit non-goals).
- ❌ Running `validate_paths` or stage validation from `aidw tasks` — the E3.7 read-path check stays
  in the workflow preflights (task prompt requirement 5).
- ❌ No PR opened and nothing committed by the recording stage (`prompts/pr.md` owns delivery).
