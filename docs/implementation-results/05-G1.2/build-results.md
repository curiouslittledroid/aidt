# Build Results — G1.2: Check task feasibility before the authoring stage

**Branch:** `05-G1.2`
**Date:** 2026-11-20
**Spec:** `design.md` §§8.1, 14, 17 (row Z19); `docs/roadmap-format.md` §§8, 10
**Pull request:** not yet opened — the /pr stage records it here once the PR exists

## Summary

**Purpose:** Make `aidw prompt` refuse (exit 3) before it spends an authoring run when a roadmap
entry cites a spec section that is missing, cannot be located uniquely, or is empty, instead of
discovering the same defect from the author's later `blocked:` report.

| Decision | Why it matters |
|----------|---------------|
| The refusal is `exit 3`, not `2` or `4` | A dangling or empty citation is a spec/roadmap defect only a human can fix — the same condition the author's `blocked:` reports with exit 3 — kept distinct from a usage error (2) and a safety refusal (4) in §14's table. |
| One shared enumerator (`_cited_specs`) feeds both `_render_cited_specs` and the checker | The `P2` evidence bundle and the preflight cannot disagree about what an entry cites; the bundle's printed form is unchanged (it still prints the cited number verbatim). |
| Section numbers compare as dotted-integer tuples (`_canonical_number`) | `CITATION_RE` accepts zero-padded citations (roadmap-format.md §8.1), so `Design 09` must match `## 9`; comparing strings would refuse a present section. The canonical form lives only in the checker. |
| "Non-empty" means at least one non-blank, non-heading line between the heading and the next equal-or-higher heading | "Any text after the heading" would pass a title followed only by blank lines or deeper subheadings, which documents nothing. |
| Only Markdown ATX headings delimit a section (`_heading_level` requires whitespace after the `#` run) | `#not a heading` is body prose in Markdown, so treating it as a heading would report a section with content as empty — a false refusal. |
| Placed after L1.2's predecessor refusal and immediately before `_verify_base_branch`, inside `not takeover` | A predecessor wins when both fire (roadmap ordering is the first authority), a purely local check never spends a network fetch, a refused run leaves no run dir/branch/worktree/prompt file, and a `--resume` does not repeat a run-scoped check the run already passed. |
| `--dry-run` reports the gaps as a note and falls through to normal planning | A dry run is a write-free plan (design §8.1, §17 Z14) and must not refuse; the note sits beside the incomplete-predecessor note. |
| The check stays non-semantic | Judging whether a section contradicts the roadmap or whether a prerequisite's work is merged is the author's job; `prompts/task-prompt.md` is unchanged and remains the semantic backstop. |

**Where it fits in the roadmap:** Epic G1 ("Prompt review depth") in `docs/tasks/05 - Pipeline
efficiency.md`. It follows G1.1 (finding classification) and C1.x's prompt-evidence work, and it
builds on L1.2's same-file unfinished-predecessor gate, which stays the only prerequisite check. It
turns a blocked authoring run (observed at ~$0.36 in 04-A2 attempt 1) into a seconds-cost refusal.
No later roadmap task is named as depending on it in this file.

**Scope:** `aidw/workflows/prompt.py` (the shared `_cited_specs` enumerator,
`_task_citation_inputs`, `_heading_level`, `_canonical_number`, `_section_state`,
`_spec_feasibility_gaps`, `_refuse_spec_gaps`, and the wiring in `run()`), `design.md` §§8.1 + 17
(row Z19), `docs/workflow-stages.md`'s prompt preflight line, and the focused tests in
`tests/test_prompt_workflow.py` and `tests/test_design_doc.py`. It deliberately stops short of the
author-side feasibility check in `prompts/task-prompt.md`, of any dependency graph or `Notes:`
parsing, of a new CLI flag, and of any change to the evidence bundle's rendered text.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/05-G1.2-prompt.md` | Created | Task prompt for this task, committed on the branch before implementation (plus one scoping edit to its artefact list, commit `b09e2a4`). |
| `aidw/workflows/prompt.py` | Modified | Adds `_task_citation_inputs`, the shared `_cited_specs` enumerator (`_render_cited_specs` now renders it), `_heading_level`, `_canonical_number`, `_section_state`, the pure `_spec_feasibility_gaps` checker and the `_refuse_spec_gaps` message, and wires the computed gap list into the real-run preflight (exit 3) and the `--dry-run` note. |
| `design.md` | Modified | §8.1's preflight line and a new bullet document the check, its position, gap rule, exit code and the author-side backstop; §17 gains row Z19. |
| `docs/workflow-stages.md` | Modified | The prompt workflow's preflight line names the cited-spec-section check in execution order. |
| `tests/test_design_doc.py` | Modified | Pins the §8.1 wording and exactly one §17 row matching `G1.2` (matched by task id, never by `Z` number), including the prompt-fixed decisions and touched paths. |
| `tests/test_prompt_workflow.py` | Modified | Adds the `design.md` seed to `READ_PATH_FILES` (so the fixtures' `Design 09`/`Design 8.1` citations resolve) and the G1.2 tests: one case per gap kind and its no-gap mirror, the zero-padding comparison, the `#not a heading` body rule, purity/determinism, seeded property coverage, the shared-enumeration rendering/dedup regression, exit-3 refusal with no fetch/run/branch/prompt, predecessor precedence, dry-run note, and the `--resume` non-repeat. |

The change set also carries edits this stage does not own: the single `- [ ]` → `- [x]` flip on the
`G1.2` entry in `docs/tasks/05 - Pipeline efficiency.md` (the `/update-roadmap` stage) and the
`build-results.md` / `summary.md` / `integration-test-guide.md` documents beneath
`docs/implementation-results/05-G1.2/` (the record, summarize and integration-guide stages). This
stage wrote only `build-results.md`.

---

## Verification Results

All gates below were run from `/Users/phil/software-projects/aidt-workspace/05-G1.2` on the working
tree relative to `main` (commits `67e4b1a..b09e2a4` plus the uncommitted change set above), through
`aidw gate run` with the scope the workflow's other stages declare:

```
--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts
```

No source, test, config or lockfile was excluded. Every outcome below is recorded against tree
`117f26ae9a50`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 1ms`, exit 0) — run here |
| Lint | — | **unverified** (no linter is configured: `AGENTS.md` lists exactly the gates below and `design.md` §15 says pytest is the only verification) |
| Build | — | **unverified** (no build command is named by `AGENTS.md` or `aidw/conventions.md`; packaging is exercised inside the suite by `tests/test_packaging.py`) |
| Test | `uv run --frozen pytest` | ✅ Pass (`2468 passed in 51.01s`) — cited from `aidw gate run suite`, tree `117f26ae9a50`, stage `update-traceability`, 2026-11-20T11:17:25Z; re-asked here with the same key, command and scope and reused (exit 0, no re-run) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`23 checks: 0 failed, 2 warning(s)` — dirty working tree, missing `.mcp.json`) — `aidw gate run doctor`, tree `117f26ae9a50`, stage `record-implementation-results`, 2026-11-20T11:17:49Z |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (`resolved repo prompts: 0 error(s), 0 warning(s)`) — `aidw gate run prompts-check`, tree `117f26ae9a50`, stage `record-implementation-results`, 2026-11-20T11:17:49Z |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) — `aidw gate run agents-validate`, tree `117f26ae9a50`, stage `record-implementation-results`, 2026-11-20T11:17:50Z |
| Whitespace | `git diff --check` | ✅ Pass (exit 0, no output) — run here |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2468 | ✅ Pass (`2468 passed in 51.01s`) — reused `suite` outcome, tree `117f26ae9a50`, stage `update-traceability`, 2026-11-20T11:17:25Z |
| `tests/test_prompt_workflow.py` + `tests/test_design_doc.py` `-k g12` | 22 | ✅ Pass (`......................` / `[100%]`, no failures) — `aidw gate run g12-focused`, tree `117f26ae9a50`, stage `record-implementation-results`, 2026-11-20T11:17:53Z |

The full suite was reused, not re-run; the focused G1.2 gate is a separate selection run once, not a
second full-suite invocation.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Pure checker: one case per gap kind and its no-gap mirror (missing `design.md`, missing `§N` heading, empty section, unlocatable `<NAME>.md`, missing doc `§N`, unresolvable `D<nn>`, unreadable file) | ✅ Pass (`g12-focused`, tree `117f26ae9a50`) |
| Canonical zero-padded citation (`Design 09` → `## 9`, both directions) | ✅ Pass (`g12-focused`, tree `117f26ae9a50`) |
| `#not a heading` (no whitespace after `#`) is section body, not a heading boundary | ✅ Pass (`test_g12_hash_prefix_without_heading_space_is_section_body`, `g12-focused`, tree `117f26ae9a50`) |
| Shared enumeration preserves `_render_cited_specs`'s rendering and de-duplication | ✅ Pass (`test_g12_shared_citation_enumeration_preserves_rendering_and_deduplication`, `g12-focused`, tree `117f26ae9a50`) |
| Purity/determinism and seeded property coverage of the checker (padding never changes a verdict) | ✅ Pass (`g12-focused`, tree `117f26ae9a50`) |
| Workflow: exit 3 names every citation gap, with no `git.fetch`, no run dir, no branch and no prompt file | ✅ Pass (`g12-focused`, tree `117f26ae9a50`) |
| Predecessor refusal wins over the spec-gap refusal (exit 4, spec gaps not printed) | ✅ Pass (`g12-focused`, tree `117f26ae9a50`) |
| `--dry-run` notes the gaps, still prints the full plan and returns 0 without writes | ✅ Pass (`g12-focused`, tree `117f26ae9a50`) |
| `--resume`/takeover does not repeat the check | ✅ Pass (`g12-focused`, tree `117f26ae9a50`) |
| `tests/test_design_doc.py`: one §17 row for `G1.2` (by task id) + the §8.1 wording pins | ✅ Pass (`g12-focused`, tree `117f26ae9a50`) |
| `prompts/task-prompt.md` unmodified (author-side backstop intact) | ✅ Pass (`git status --short` lists it as unmodified; full suite green) |

---

## Deviations observed during recording

- **A later change set than the previous recording.** The previous recording of this stage gated tree
  `4fb24c6fef22` (2467 tests); the change set now carries the shared-enumeration regression test, so
  this run's tree is `117f26ae9a50` with `2468 passed`. An earlier recording against tree
  `5a4c53219231` observed the suite red on
  `test_g12_hash_prefix_without_heading_space_is_section_body`; that failure is superseded by the
  whitespace-after-`#` fix and is not part of the outcomes above.
- **No gate was re-run except the ones reported as run here.** `suite` was reused against the same
  tree and scope and its origin is named in the row.
- **No lint or build gate exists** — the template's lint/build rows are recorded as unverified
  rather than invented, following `AGENTS.md` and `design.md` §15.
- **No pull request exists yet** for `05-G1.2` (`gh pr view 05-G1.2` reports "no pull requests found
  for branch"); the line above says so rather than inventing a number.

---

## Non-Goals (NOT implemented)

- ❌ G1.1 (findings classification — already merged) and B1.1 (batch fixes) — separate tasks, not touched.
- ❌ The author-side semantic feasibility check in `prompts/task-prompt.md` — kept unchanged as the semantic backstop; not weakened or removed.
- ❌ Cross-phase/cross-file prerequisite gating and `Notes:` parsing — L1.2's explicit non-goal; no dependency graph, no `requires:` field, no `aidw/roadmap.py`/`RoadmapTask` change.
- ❌ No new CLI flag (no `--skip-spec-check`).
- ❌ No change to `_render_cited_specs`'s rendered output text — only the enumeration was factored out; the evidence bundle's printed form stays byte-identical.
- ❌ No new prompt/agent id, checker, status vocabulary, config key, CI gate or `REQUIRED_PROMPTS`/`REQUIRED_SCRIPTS` entry.
- ❌ No pull request opened, and nothing committed or pushed — the `/pr` stage owns delivery.
