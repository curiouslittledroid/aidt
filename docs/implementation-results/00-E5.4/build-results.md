# Build Results — 00-E5.4: Promote the canonical example

**Branch:** `00-E5.4`
**Date:** 2026-11-05
**Spec:** `docs/roadmap-format.md` §2, §9 and §11; `docs/migration/EXTRACTION.md` §3.7 (roadmap model, D6/D15); `tests/test_roadmap.py`; `tests/test_roadmap_format.py`; `docs/tasks/00 - Extraction.md` E5.4

## Summary

**Purpose:** Make the worked example in `docs/roadmap-format.md` §9 the single canonical roadmap example and rewire the roadmap tests to parse the document's current bytes, so the format doc and `aidw/roadmap.py` cannot drift.

| Decision | Why it matters |
|----------|---------------|
| The doc's existing §9 example (`E5.1`/`E5.2`/`E6.1`) is canonical; the inline A1/A2/B1 `FIXTURE` is retired | §9 already exercises field bullets, both citation channels and a multi-line `Done when`, and `tests/test_roadmap_format.py` asserts it exhaustively. Promoting the older, thinner fixture would have lost coverage. |
| Extraction and the "exactly one complete worked example" guard live once in `tests/conftest.py` | Two copies of the selector could let a second example satisfy one copy while the other still finds "one", re-opening the drift the guard exists to prevent. |
| The helper is handed to tests as the `roadmap_example` session fixture, with a type-only `from conftest import RoadmapExample` | Two `conftest` modules are collected under the same top-level module name; a runtime import binds whichever was imported last and breaks the full suite. Tests still share one implementation and one doc read. |
| `OTHER_FIXTURE`, `PROPERTY_BODY` and the synthetic filenames stay inline | They are selection-mechanics inputs (glob/regex pre-selection, ordering), not format examples; moving them into the doc would create competing example bodies and trip the single-example guard. |
| The rewired tests copy documented field values from §9's parse table rather than recomputing them | The assertions stay a statement of the documented contract, not a second implementation of the parser's rules. |
| Drift is proved with doctored copies inside `tmp_path` | Each proof edits the doc's current bytes, extracts through the same guard, and parses the doctored example, so no cached copy or snapshot can mask a doc/parser divergence. The real doc is never written. |

**Where it fits in the roadmap:** Final task of epic E5 (the roadmap as an AIDT-owned format, D6/D15). It builds on E5.1's format contract, E5.2's config-driven parser and E5.3's validator, and closes the fixture-promotion item that E5.3's results document named as its successor. No later task in this epic depends on it; epic E6 and E7 remain separate.

**Scope:** Adds the shared roadmap-example extraction to `tests/conftest.py`; rewires `tests/test_roadmap.py` and `tests/test_roadmap_format.py` to use it, including the single-example guard and the drift proofs; and reconciles the stale §3.7 sentence (plus its E0.4 resolution note) in `docs/migration/EXTRACTION.md`. It deliberately stops short of editing §9's example or its parse table, changing the parser, CLI or validator, adding a second example or separate fixture file, and starting E6 or E7.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E5.4-prompt.md` | Created | Task prompt added on the branch by the prompt-authoring stage. |
| `docs/implementation-results/00-E5.4/build-results.md` | Created | This recording document. |
| `tests/conftest.py` | Modified | Adds `ROADMAP_FORMAT_DOC`, the §9 filename/phase constants, `_fenced_blocks`/`_example_text` (including the exactly-one-example guard), the frozen `RoadmapExample` helper and the `roadmap_example` session fixture. |
| `tests/test_roadmap.py` | Modified | Removes the inline `FIXTURE`; the single-file parse, find/filter/next, directory-ordering and purity tests now read §9's example through the shared fixture; adds collapsed-id, broken-`Done when` and dropped-citation drift proofs from doctored copies. |
| `tests/test_roadmap_format.py` | Modified | Deletes the private `_fenced_blocks`/`_example_text`/`_write_example` extraction and takes the doc/example through the shared fixture; adds tests for the single-example guard and for reading the example without I/O outside `tmp_path`. |
| `docs/migration/EXTRACTION.md` | Modified | §3.7 and its E0.4 resolution note now state that the §9 worked example is the single canonical source and the inline fixture is retired. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks `E5.4. Promote the canonical example` as done. |

---

## Verification Results

Every recorded gate was run once through `aidw gate run`, with the same scope —
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` —
for tree `d438a6a28c0c`, stage `record-implementation-results`, on 2026-11-05. The rows below
report this run's own outcomes; no suite, module or subset was re-run to obtain a count.
`uv sync --frozen` and `git diff --check` were run directly because neither is a recorded gate.
No lint gate was run because this repository configures no linter (AGENTS.md, design.md §15).

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 15 packages in 0.68ms`) |
| Build | `uv build --out-dir <tmp>` | ✅ Pass (gate `build`, tree `d438a6a28c0c`, 2026-11-05T02:16:26Z: built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` in a fresh temporary directory) |
| Test | `uv run --frozen pytest` | ✅ Pass (gate `suite`, tree `d438a6a28c0c`, 2026-11-05T02:16:55Z: `1343 passed in 26.60s`) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (gate `doctor`, tree `d438a6a28c0c`, 2026-11-05T02:16:58Z: `19 checks: 0 failed, 2 warning(s)` — dirty working tree and absent `.mcp.json`, both expected mid-run) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (gate `agents`, tree `d438a6a28c0c`, 2026-11-05T02:17:02Z: `11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (gate `prompts`, tree `d438a6a28c0c`, 2026-11-05T02:17:02Z: `prompts check: 0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (no output) |

The environment printed a `VIRTUAL_ENV` mismatch warning for every `uv` invocation because
`/Users/phil/software-projects/aidt-workspace/main/.venv` differs from the project environment
path `.venv`; `uv` ignored it, and the commands themselves produced the passing outputs above.
The gate's recorded summary field captured that warning on the suite, doctor, agents and prompts rows.

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1343 | ✅ Pass (`1343 passed in 26.60s`; no deselections) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `tests/test_roadmap.py` — §9's example parsed to the documented field set (period-bearing ids, `done` flags, derived epics, first-line `done_when`, `Design N` citations, phase/epic titles, branch); `find_task`/`filter_tasks`/`next_todo`; cross-file ordering; purity; no `FIXTURE` | ✅ Covered by the full-suite run above |
| `tests/test_roadmap.py` — drift proof: collapsing the first id, renaming the last `Done when`, or dropping the first `Design N` in the doc's current bytes changes the parsed field | ✅ Covered by the full-suite run above |
| `tests/test_roadmap_format.py` — shared selector rejects a second complete worked example; reading/writing the example performs no I/O outside `tmp_path` and leaves the doc unchanged | ✅ Covered by the full-suite run above |
| Exact `AGENTS.md` gate set (`uv sync --frozen`, `uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents validate --strict`, `uv run aidw prompts check`) | ✅ All five passed as recorded above |

---

## Deviations observed during recording

- **The generic record prompt names a pnpm gate set, but this repo's stack is Python/uv.** Per
  `AGENTS.md` and `prompts/pr.md` ("take them from the target repo, not from this prompt"), the
  install/build/test rows are `uv sync --frozen`, `uv build` and `uv run --frozen pytest`. No lint
  gate was run because the repo configures no linter.
- **`uv build` wrote to a fresh `$(mktemp -d)` directory**, leaving no artifacts in the gated tree.
- **The implementation was still uncommitted in the working tree.** The change set was measured
  against `main` including working-tree changes, and the gate tree `d438a6a28c0c` covers that
  content; this stage did not commit it.
- **The change set contains stage-owned files beyond the implementation deliverables:** the
  branch's task prompt (`docs/task-prompts/00-E5.4-prompt.md`, added by the prompt-authoring stage)
  and the roadmap `[x]` marker for E5.4 overlap the ignored `docs/tasks`/`docs/task-prompts` scope.
  They are expected stage-owned edits, not implementation changes.
- **The shared helper is exposed as a fixture rather than a runtime `from conftest import …`.**
  The task prompt suggested the import idiom, but two `conftest` modules are collected under the
  same top-level name, so a runtime import is order-dependent; the implementation keeps a single
  helper in `tests/conftest.py` and imports its type only under `TYPE_CHECKING`.
- **No subsets were re-run for their own counts.** The task-specific rows cite the single
  full-suite invocation above rather than a second run.

---

## Non-Goals (NOT implemented)

- ❌ E6.1 (move GitHub markers/labels into resolved config) and the rest of epic E6 — separate; not started (task prompt, explicit non-goals).
- ❌ E7.x (split the prompt library) — separate; not started (task prompt, explicit non-goals).
- ❌ A second canonical example or a separate fixture file outside the doc — §9's fenced block remains the single source (task prompt, explicit non-goals).
- ❌ Editing §9's example content or its parse table — both are unchanged; the parser agrees with them (task prompt, explicit non-goals).
- ❌ Changing the parser or E5.3's validator (`validate_tasks`, `aidw tasks --validate`) — `aidw/roadmap.py` and `aidw/cli.py` are untouched (task prompt, explicit non-goals).
- ❌ No PR opened and nothing committed by the recording stage (`prompts/pr.md` owns delivery).
