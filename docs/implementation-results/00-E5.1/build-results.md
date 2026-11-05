# Build Results — 00-E5.1: Write the roadmap format contract

**Branch:** `00-E5.1`
**Date:** 2026-11-04
**Spec:** `docs/migration/EXTRACTION.md` §3.7 (Roadmap model, D6/D15), §2 (locked decisions D6/D15), §3.12 (new repo layout); `design.md` §11 (roadmap task selection); `aidw/roadmap.py`; `aidw/workflows/prompt.py`; `docs/tasks/00 - Extraction.md` E0.7

## Summary

**Purpose:** Replace the `docs/roadmap-format.md` placeholder with the AIDT-owned roadmap format
contract, backed by a worked example that the shipped parser actually parses and by contract tests
that compare every documented claim against `aidw/roadmap.py` and `aidw/workflows/prompt.py`.

| Decision | Why it matters |
|----------|---------------|
| The five shipped regexes and `derive_epic` are quoted and treated as normative | `roadmap.py` is the product contract; documenting invented structure would let the doc and parser drift silently. |
| The worked example lives inside the doc as a fenced block named `07 - Example Roadmap.md` | E5.4 can later promote the same block into the fixture source without moving it twice; the tests select it by content, not position. |
| The example uses both citation channels: `Design 11` and `EXTRACTION.md §3.7` | `.citations` captures only `Design N`; doc refs are recovered by `_render_cited_specs`, so the doc must show both. |
| `Done when` is documented as required but enforcement is left to E5.3 | The shipped parser does not validate, and E5.1 is a format contract, not a validator. |
| The E0.7 blank-line rule is documented as stale, matching both shipped readers | `parse_file` and `_done_when_block` skip blank lines before the label; the contract follows the code. |

**Where it fits in the roadmap:** E5.1 opens Epic E5 (roadmap as an AIDT-owned format). It depends
on the shipped `aidw/roadmap.py` parser and the E0.7 parser rules, and it is the written contract
that E5.2 (drive the parser from `paths.roadmap_dir`/`paths.roadmap_glob`), E5.3 (format validation)
and E5.4 (promote the example to the test fixture) build on.

**Scope:** Rewrites `docs/roadmap-format.md`, adds `tests/test_roadmap_format.py`, and marks E5.1
done in the roadmap. It deliberately stops short of changing the parser or target config, adding
validation, moving the test fixture, or introducing a per-repo dialect.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/implementation-results/00-E5.1/build-results.md` | Created | This recording document. |
| `tests/test_roadmap_format.py` | Created | Contract tests: extract the doc's worked example, parse it, and assert ids, done flags, epic derivation, `done_when`, citations, both Done-when readers, field-bullet indentation, and the documented traps. |
| `docs/task-prompts/00-E5.1-prompt.md` | Created | Task prompt added on the branch by the prompt-authoring stage. |
| `docs/roadmap-format.md` | Modified | Placeholder replaced with the format contract: D6/D15, the five regexes, filename/phase rules, ids and `derive_epic`, the Done-when block, field bullets, citations, a complete worked example, parser non-goals and produced fields. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks `E5.1. Write the format contract` as done. |

---

## Verification Results

Every gate command was run once, through `aidw gate run`, with the same scope —
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` —
for tree `f2070b738ee9`, stage `record-implementation-results`, on 2026-11-04. The rows below report
this run's own outcomes; no subset was re-run to obtain a count. `uv sync --frozen` and
`git diff --check` were run directly because neither is a gate.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 15 packages in 0.65ms`) |
| Build | `uv build --out-dir <tmp>` | ✅ Pass (gate `build`, tree `f2070b738ee9`, 2026-11-04T23:49:49Z: `Successfully built .../aidt-0.1.0-py3-none-any.whl`) |
| Test | `uv run --frozen pytest` | ✅ Pass (gate `suite`, tree `f2070b738ee9`, 2026-11-04T23:49:43Z: `1299 passed in 28.77s`) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (gate `doctor`, tree `f2070b738ee9`, 2026-11-04T23:49:47Z: `19 checks: 0 failed, 2 warning(s)` — dirty working tree and absent `.mcp.json`, both expected mid-run) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (gate `agents`, tree `f2070b738ee9`, 2026-11-04T23:49:48Z: `11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (gate `prompts`, tree `f2070b738ee9`, 2026-11-04T23:49:48Z: `prompts check: 0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (no output) |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1299 | ✅ Pass (`1299 passed in 28.77s`) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `tests/test_roadmap_format.py` — worked example parses with no collapsed id, expected ids/done/epic/`done_when`/citations | ✅ Covered by the full-suite run above |
| Both Done-when readers agree: multi-line block survives `_done_when_block`, stops at `Tests:`, blank lines before the label tolerated, blank line inside truncates | ✅ Covered by the full-suite run above |
| Citation channels stay separate: `.citations` holds `Design N` only; `_render_cited_specs` recovers `EXTRACTION.md` refs | ✅ Covered by the full-suite run above |
| `find_task` / `next_todo` / `filter_tasks` behave on the parsed example, and `load_tasks` ignores non-matching filenames | ✅ Covered by the full-suite run above |
| Doc quotes the shipped patterns verbatim, including `_FIELD_BULLET_RE`, and states D6/D15 + directory/glob only | ✅ Covered by the full-suite run above |
| Exact `AGENTS.md` gate set (`uv sync --frozen`, `uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents validate --strict`, `uv run aidw prompts check`) | ✅ All five passed as recorded above |

---

## Deviations observed during recording

- **The generic record prompt names a pnpm gate set, but this repo's stack is Python/uv.** Per
  `AGENTS.md` and `prompts/pr.md` ("take them from the target repo, not from this prompt"), the
  install/build/test rows are `uv sync --frozen`, `uv build` and `uv run --frozen pytest`. No lint
  gate was run because the repo configures no linter.
- **`uv build` wrote to a fresh `$(mktemp -d)` directory**, leaving no artifacts in the gated tree.
- **The task prompt's final `git diff` condition named only the doc and its test**, but the complete
  change set relative to `main` also contains the task prompt and the roadmap's `[x]` marker for
  E5.1; both are expected stage-owned edits, not implementation changes.

---

## Non-Goals (NOT implemented)

- ❌ E5.2 — driving `roadmap.py` from `paths.roadmap_dir`/`paths.roadmap_glob`; no edit to
  `aidw/roadmap.py`, `aidw/target_config.py`, or any parser code. The doc only states the
  directory/glob contract (task prompt, explicit non-goals).
- ❌ E5.3 — format validation with file/line/rule errors; the doc says `Done when` is required but
  enforcement is E5.3's (task prompt, explicit non-goals).
- ❌ E5.4 — moving `tests/test_roadmap.py`'s inline FIXTURE into the doc and rewiring that test; no
  edit to `tests/test_roadmap.py` (task prompt, explicit non-goals).
- ❌ Any per-repo regex/parser dialect — D15 forbids it; no configurable parser is described (task
  prompt, explicit non-goals).
- ❌ No PR opened and nothing committed by the recording stage (`prompts/pr.md` owns delivery).
