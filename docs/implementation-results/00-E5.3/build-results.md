# Build Results — 00-E5.3: Format validation with actionable errors

**Branch:** `00-E5.3`
**Date:** 2026-11-05
**Spec:** `docs/roadmap-format.md` §4, §6, §10 and §11; `design.md` §11 (roadmap task selection); `docs/migration/EXTRACTION.md` §3.7 (roadmap model, D6/D15); `aidw/roadmap.py`; `aidw/cli.py`; `docs/tasks/00 - Extraction.md` E5.3

## Summary

**Purpose:** Report the file, line and rule for the three malformations the roadmap format defines — a missing `Done when`, a duplicate `(phase, task)` id, and an entry before any `## Epic` heading — through a pure validator and `aidw tasks --validate`, so a broken roadmap produces an actionable report instead of parsing silently.

| Decision | Why it matters |
|----------|---------------|
| `validate_tasks` is a separate, pure pass over `load_tasks` output | `parse_file`/`load_tasks` keep the documented "never report" contract (roadmap-format.md §10), so existing `aidw tasks`, the `aidw prompt` preflight and `find_task` callers are unchanged. |
| Duplicate ids key on `(phase, task)`, report the later entry, and name the earlier `file:line` | The branch id is `{phase}-{task}` and `find_task` matches phase+task, so the same task id in another phase is a different task. Reporting the later location preserves the first definition as the canonical one. |
| "Outside an epic" keys on `epic_title is None`, not `epic` | `epic` is always derived from the id by `derive_epic`, so it is never `None`; keying on it would flag nothing. |
| `--validate` runs over the full list before the filter/show branches | Filters must not narrow validation: an issue outside a requested `--phase` would otherwise go unreported. `--validate` therefore takes precedence and exits after printing. |
| Issues go to stdout and a malformed roadmap exits `EXIT_USAGE` | Follows the repository's report convention (`agents validate`, `prompts check`): stdout carries the issue listing, stderr remains the refusal channel for config errors and `no roadmap tasks found`. |
| The existing zero-entry guard is kept inside `aidw tasks` | An empty roadmap is empty, not clean; treating it as a passing validation would be a silent pass. |
| No wiring into `aidw doctor` or the `aidw prompt` preflight | E5.3 is the reporting surface, not a new gate or refusal; adding one would change existing command behaviour beyond the task. |

**Where it fits in the roadmap:** Epic E5 (the roadmap as an AIDT-owned format, D6/D15). It builds on E5.1's format contract, E5.2's config-driven parser and the E3.2/E3.3 fail-closed config resolver. It unblocks E5.4 (promoting the canonical fixture into `docs/roadmap-format.md`), which can rely on the validator for the three malformations.

**Scope:** Adds `RoadmapIssue`, the three rule tokens and `validate_tasks` to `aidw/roadmap.py`; adds the `--validate` option and report path to `aidw tasks`; adds contract and CLI tests; and marks E5.3 done in the extraction roadmap. It deliberately stops short of a fourth validation rule, parser-side reporting, epic/heading pairing enforcement, moving the E5.4 fixture, and wiring validation into `doctor` or the prompt preflight.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E5.3-prompt.md` | Created | Task prompt added on the branch by the prompt-authoring stage. |
| `docs/implementation-results/00-E5.3/build-results.md` | Created | This recording document. |
| `tests/test_roadmap_validate.py` | Created | Contract tests for the three rules, the two trap negatives, every-issue reporting, purity/immutability, frozen issues, empty input and a seeded property run. |
| `aidw/roadmap.py` | Modified | Module docstring now describes validation; adds `RULE_MISSING_DONE_WHEN`, `RULE_DUPLICATE_ID`, `RULE_OUTSIDE_EPIC`, the frozen `RoadmapIssue` dataclass and `validate_tasks`; parser functions untouched. |
| `aidw/cli.py` | Modified | Adds `--validate` to `aidw tasks`, runs full-list validation before the filter/show branches, prints every issue on stdout and exits `EXIT_USAGE` when any issue exists; the existing zero-entry guard remains. |
| `tests/test_cli.py` | Modified | Adds CLI tests for malformed (all three issues on stdout), clean, zero-entry and glob-selects-nothing repos, filter independence, additivity without `--validate`, and fail-closed broken config. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks `E5.3. Format validation with actionable errors` as done. |

---

## Verification Results

Every gate command was run once, through `aidw gate run`, with the same scope —
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` —
for tree `d447c75a1723`, stage `record-implementation-results`, on 2026-11-05. The rows below report
this run's own outcomes; no suite, module or subset was re-run to obtain a count. `uv sync --frozen`
and `git diff --check` were run directly because neither is a recorded gate. No lint gate was run
because this repository configures no linter (AGENTS.md, design.md §15).

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 15 packages in 0.66ms`) |
| Build | `uv build --out-dir <tmp>` | ✅ Pass (gate `build`, tree `d447c75a1723`, 2026-11-05T01:33:09Z: built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` in a fresh temporary directory) |
| Test | `uv run --frozen pytest` | ✅ Pass (gate `suite`, tree `d447c75a1723`, 2026-11-05T01:33:37Z: `1338 passed in 25.47s`) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (gate `doctor`, tree `d447c75a1723`, 2026-11-05T01:33:40Z: `19 checks: 0 failed, 2 warning(s)` — dirty working tree and absent `.mcp.json`, both expected mid-run) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (gate `agents`, tree `d447c75a1723`, 2026-11-05T01:33:42Z: `11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (gate `prompts`, tree `d447c75a1723`, 2026-11-05T01:33:42Z: `prompts check: 0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (no output) |

The gate's recorded summary field captured the environment's `VIRTUAL_ENV` mismatch warning on the
suite, doctor, agents and prompts rows; the commands themselves produced the passing outputs above.

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1338 | ✅ Pass (`1338 passed in 25.47s`) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `tests/test_roadmap_validate.py` — one hand-calculated vector per rule, the `epic`-vs-`epic_title` and cross-phase negatives, every-issue reporting, purity, frozen issue, empty input and seeded property run | ✅ Covered by the full-suite run above |
| `tests/test_cli.py` — malformed repo prints all three issues on stdout with `EXIT_USAGE`; clean repo is silent and exits `0`; zero-entry and glob-selects-nothing keep `no roadmap tasks found`; filters do not narrow validation; no `--validate` still lists; broken config fails closed | ✅ Covered by the full-suite run above |
| `tests/test_roadmap.py` and `tests/test_roadmap_format.py` — parser behaviour unchanged | ✅ Covered by the full-suite run above; both files are untouched |
| Exact `AGENTS.md` gate set (`uv sync --frozen`, `uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents validate --strict`, `uv run aidw prompts check`) | ✅ All five passed as recorded above |

---

## Deviations observed during recording

- **The generic record prompt names a pnpm gate set, but this repo's stack is Python/uv.** Per
  `AGENTS.md` and `prompts/pr.md` ("take them from the target repo, not from this prompt"), the
  install/build/test rows are `uv sync --frozen`, `uv build` and `uv run --frozen pytest`. No lint
  gate was run because the repo configures no linter.
- **`uv build` wrote to a fresh `$(mktemp -d)` directory**, leaving no artifacts in the gated tree.
- **The implementation was still uncommitted in the working tree.** The change set was measured
  against `main` including working-tree changes, and the gate tree `d447c75a1723` covers that
  content; this stage did not commit it.
- **The change set contains stage-owned files beyond the implementation deliverables:** the
  branch's task prompt (`docs/task-prompts/00-E5.3-prompt.md`, added by the prompt-authoring stage)
  and the roadmap `[x]` marker for E5.3 overlap the ignored `docs/tasks`/`docs/task-prompts` scope.
  They are expected stage-owned edits, not implementation changes.
- **No subsets were re-run for their own counts.** The task-specific rows cite the single
  full-suite invocation above rather than a second run.

---

## Non-Goals (NOT implemented)

- ❌ E5.4 — promoting `tests/test_roadmap.py`'s fixture into `docs/roadmap-format.md` as the single source; the fixture did not move (task prompt, explicit non-goals).
- ❌ Heading/epic pairing mismatch (`derive_epic` ≠ the `## Epic` heading) as a validation rule; roadmap-format.md §4 says nothing enforces the pairing, and only the three named malformations are validated (task prompt, explicit non-goals).
- ❌ Wiring validation into `aidw doctor` or the `aidw prompt` preflight; E5.3 is the reporting surface, not a new gate or refusal (task prompt, explicit non-goals).
- ❌ The collapsed-id trap (`**E0.1 Create …**` → id `E0`) as a fourth validation rule; E0.7's guard and `tests/test_roadmap_format.py::test_example_has_no_collapsed_id` already own it (task prompt, explicit non-goals).
- ❌ Making `parse_file`/`load_tasks` raise or warn; the parser keeps "never reporting" (roadmap-format.md §10).
- ❌ No PR opened and nothing committed by the recording stage (`prompts/pr.md` owns delivery).
