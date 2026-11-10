# Build Results — 03-H2.1: Give the delta brief a size budget

**Branch:** `03-H2.1`
**Date:** 2026-11-10
**Spec:** `design.md` §8.1, §9.2, §15, §17; `docs/tasks/03 - Stage resilience.md` H2.1

## Summary

**Purpose:** A later review round's delta brief now has a documented size contract — the previous review is re-emitted as the reviewer's structured finding blocks only when that is strictly smaller, and an over-budget diff is replaced by an explicit elision note — so a six-finding round can no longer inflate the next review prompt from 12,317 to 55,636 chars and end the stage on `stop_reason: length`.

| Decision | Why it matters |
|----------|---------------|
| Budget the two halves **separately**: no hard cap on the previous review, a hard cap on the diff. | They fail differently. A review's findings are already structured and can be shrunk losslessly per finding; a diff either fits or must be elided, because truncating it silently reads like a complete diff and a reviewer that cannot see a fix cannot verify it. |
| Previous review: smaller-of-two representations, strictly smaller wins, measured with `len(s)` on the exact strings compared, equality keeps prose. | The spec fixes no number for this half, and a strict win is what lets the raw prose stay byte-for-byte (trailing whitespace included) on a tie and on any non-win, so no finding is ever dropped or rewritten. |
| Structured rendering uses `findings._finding_text_block` under a delta-brief heading, never `render_finding_block`. | `render_finding_block` carries the fixer's "Fix exactly this finding" instruction; the reviewer must *resolve*, not fix. The per-finding `resolved` / `not resolved` / `newly contradicted` instruction (`DELTA_BRIEF_INSTRUCTION`) survives in every rendering. |
| Diff cap `DELTA_BRIEF_DIFF_BUDGET_CHARS = 4000` chars; over-budget diff becomes `DELTA_BRIEF_DIFF_ELIDED`, naming `elided`, size as the reason, and the numeric budget. | Pinned tokens make "it was dropped to fit" assertable and distinguishable from `DIFF_UNAVAILABLE`'s could-not-produce case. The cap lives in the registry, not in the shared `_brief_diff`/`_prompt_diff` producer, so the out-of-scope reconcile brief is untouched. |
| `StageRecord.rendered_chars` is recorded for review-loop heads (`task-review-<n>`) only, on the real-run path only; one `run.log` line names the size. | `run_stage` renders and records every stage and serves `--dry-run`; unscoped recording would change author/fix records and the byte-identical dry-run plan. The field is additive at the same `schema_version` and sits beside `usage.input_tokens`. |

**Where it fits in the roadmap:** H2.1 is the first task in phase 03's Epic H2 (bound the review context). It builds on L2.3's delta brief, L3.4's reconcile brief, E4.3's registry move and E4.5's failure run, and it is followed by H3.1 (roadmap tick stage) and H3.2/H3.3 in the same phase. The prompt-fixed round-2 acceptance bound is 24,000 chars; the measured budgeted rendering of the E4.5 shape is **18,814 chars**, against the failure run's **55,636**.

**Scope:** `aidw/stage_registry.py` owns the size contract (`render_delta_brief`, `render_previous_review`, `render_diff_section`, the budget/elision/findings constants, `is_review_stage`); `aidw/state.py` adds the additive `rendered_chars` field; `aidw/runner.py` records it for review heads and prints the `run.log` line. `design.md` §9.2 documents the field and §17 records the decision (X1). `tests/test_stage_registry.py`, `tests/test_runner.py`, `tests/test_state.py` and the re-baselined `tests/test_prompt_workflow.py` prove each contract. The task deliberately stops short of a roadmap tick stage, budgeting the reconcile brief, model routing / a larger context window, and the unrelated author-prompt conciseness budget.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/implementation-results/03-H2.1/build-results.md` | Created | This results document. |
| `docs/task-prompts/03-H2.1-prompt.md` | Created | Task prompt for H2.1 (spec citations, requirements, prompt-fixed values, traps, tests, non-goals). |
| `aidw/stage_registry.py` | Modified | Adds the delta-brief size contract: `DELTA_BRIEF_DIFF_BUDGET_CHARS` (4000), `DELTA_BRIEF_FINDINGS_LEAD`, `DELTA_BRIEF_DIFF_ELIDED`, `render_previous_review` (strictly-smaller structured finding blocks else verbatim prose), `render_diff_section` (unchanged / unavailable / explicitly elided), `is_review_stage`, and the documented `render_delta_brief` docstring. |
| `aidw/state.py` | Modified | Adds the additive `StageRecord.rendered_chars: int \| None = None`, beside `rendered_prompt` and the usage fields, at the same `SCHEMA_VERSION`. |
| `aidw/runner.py` | Modified | Records `len(rendered)` as `rendered_chars` for review-loop head stages only, on the real-run path, and logs one line naming the stage and the rendered size. |
| `design.md` | Modified | §9.2 documents `rendered_chars` and its scoping; §17 records decision X1 (the constant, its value and rationale, the elision tokens, the recording scope, the 24,000-char acceptance bound). |
| `docs/tasks/03 - Stage resilience.md` | Modified | Ticks H2.1. |
| `tests/test_stage_registry.py` | Modified | Adds 11 renderer/contract tests: structured substitution, non-smaller and `len`-equal prose fallbacks, unparseable verbatim fallback, over-budget elision, in-budget passthrough, chars-not-bytes, purity, review-stage naming, the E4.5 six-finding size check, and a seeded property sweep. |
| `tests/test_runner.py` | Modified | Adds 3 tests for the scoped `rendered_chars` record and `run.log` line: review head records, author/fix stages do not, `--dry-run` records neither. |
| `tests/test_prompt_workflow.py` | Modified | Adds the over-budget real-loop elision test and re-baselines `test_delta_brief_preserves_previous_review_verbatim` (and the round-attribution assertions) to the new promise. |
| `tests/test_state.py` | Modified | Adds the `rendered_chars` round-trip-without-schema-bump test and asserts old state loads the new field as `None`. |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.81ms`; exit 0) |
| Build | `aidw gate run build --ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv build --out-dir "$(mktemp -d)"` | ✅ Pass (`aidt-1.1.1.tar.gz` and `aidt-1.1.1-py3-none-any.whl` built; gate `build` passed for tree `6231aa0e2e8d` at `2026-11-10T12:03:02Z` by stage `record-implementation-results`) |
| Test | `aidw gate run suite --ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv run --frozen pytest` | ✅ Pass (`reused: gate 'suite' passed for tree 6231aa0e2e8d at 2026-11-10T12:01:13Z by stage 'update-traceability'` — `1937 passed in 35.59s`; cited rather than re-run because the tree and declared scope match this record run's) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`; warnings: dirty working tree, missing `.mcp.json`) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (toolkit defaults `0 error(s), 0 warning(s)`; resolved repo prompts `0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (no output; exit 0) |
| Lint | — | ⚠️ **unverified** (the repository configures no lint command; `AGENTS.md` names only pytest, `doctor`, `agents validate --strict` and `prompts check`, and `design.md` §15 says no linter is configured) |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1,937 | ✅ Pass (`1937 passed in 35.59s`, gate `suite` for tree `6231aa0e2e8d` recorded by stage `update-traceability` at `2026-11-10T12:01:13Z`) |
| `tests/test_stage_registry.py` (11 new H2.1 functions) | 11 new functions | ✅ Pass (included in the 1,937-test full suite; the reused gate emits no per-file summary, so the subset was not re-run for its own count) |
| `tests/test_runner.py` (3 new H2.1 functions) | 3 new functions | ✅ Pass (included in the full suite, no second run) |
| `tests/test_prompt_workflow.py` (1 new, 2 re-baselined) | 1 new + 2 re-baselined | ✅ Pass (included in the full suite, no second run) |
| `tests/test_state.py` (1 new function) | 1 new function | ✅ Pass (included in the full suite, no second run) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Structured substitution: a multi-finding review whose blocks are strictly smaller renders one block per finding, no fixer voice anywhere, every finding and the resolution instruction intact: `test_delta_brief_renders_structured_findings_when_strictly_smaller` | ✅ Pass (included in the 1,937-test full suite) |
| Non-win and `len`-equal boundary keep the raw prose verbatim: `test_delta_brief_keeps_prose_verbatim_when_blocks_are_not_smaller`, `test_delta_brief_keeps_prose_on_a_len_equal_tie` | ✅ Pass (included in the full suite) |
| Unparseable review stays verbatim with trailing whitespace intact: `test_delta_brief_keeps_an_unparseable_review_verbatim_with_whitespace` | ✅ Pass (included in the full suite) |
| Over-budget diff renders the elision note with the pinned tokens (`elided`, `for size`/size reason, `4000`) and no `diff --git`: `test_an_over_budget_diff_is_replaced_by_the_elision_note` | ✅ Pass (included in the full suite) |
| In-budget diff renders unchanged (the cap is a ceiling): `test_an_in_budget_diff_renders_unchanged` | ✅ Pass (included in the full suite) |
| The cap counts characters, not UTF-8 bytes: `test_diff_budget_counts_characters_not_utf8_bytes` | ✅ Pass (included in the full suite) |
| Purity: no I/O and no mutation of the caller's strings: `test_the_delta_brief_helpers_are_pure_and_do_no_io` | ✅ Pass (included in the full suite) |
| `is_review_stage` matches only `task-review-<n>` heads: `test_is_review_stage_names_only_the_prompt_loops_review_heads` | ✅ Pass (included in the full suite) |
| Seeded property sweep (120 cases, seed 41,210) exercises both previous-review promises, never drops a finding, and never emits an over-budget diff: `test_delta_brief_size_property_holds_for_generated_reviews` | ✅ Pass (included in the full suite) |
| Real prompt-loop wiring names an over-budget fix diff and is measurably smaller than carrying the diff: `test_over_budget_fix_diff_is_explicitly_elided_in_the_next_review` | ✅ Pass (included in the full suite) |
| A review stage records `len(rendered)` in `state.json` beside `usage.input_tokens` and prints exactly one `run.log` line: `test_a_review_stage_records_the_rendered_prompt_size` | ✅ Pass (included in the full suite) |
| Author, fix and reconcile stages record neither the field value nor the line (serialised as `rendered_chars: null`): `test_author_and_fix_stages_do_not_record_the_rendered_size` | ✅ Pass (included in the full suite) |
| The `--dry-run` path records neither, preserving the byte-identical dry-run plan: `test_the_dry_run_path_records_neither_the_size_nor_the_line` | ✅ Pass (included in the full suite) |
| `rendered_chars` round-trips without a `schema_version` bump and an older state loads it as `None`: `test_rendered_chars_round_trips_without_a_schema_bump` | ✅ Pass (included in the full suite) |
| Hand-calculated size check (measured from the test fixture, not a second suite run): six-finding structured blocks = 1,972 chars; capped brief = 6,497 chars; round-2 = 12,317 + 6,497 = **18,814 chars**, under the 24,000 bound and well under the failure run's 55,636. Over-budget fixture: uncapped 42,441 chars vs elided 2,799 chars | ✅ Pass (measured with `len(s)` on the same fixtures the tests use; `test_six_findings_plus_a_capped_diff_stay_under_the_round_two_bound` asserts the bound and the smaller elided rendering) |
| A live model-backed round-2 review (a real Pi run against the budgeted brief) | ⚠️ **unverified** (no test in this repository may invoke a real Pi model — `AGENTS.md` §Tests, `design.md` §15; the contract is proven against the renderer and faked stages) |

---

## Deviations observed during recording

- **The roadmap deliverable names `findings.render_finding_block`, but the implementation uses `_finding_text_block`.** The task prompt's trap directs this: `render_finding_block` carries the fixer's "Fix exactly this finding" instruction, which is the wrong voice for a reviewer, so the block text is emitted under a delta-brief heading without it.
- **The roadmap's E4.5 note says "19k → 23k prompt"; the prompt-fixed acceptance bound is 24,000 chars.** The measured budgeted round-2 size is 18,814 chars, which satisfies the bound; the bound and its rationale are recorded in design §17 (X1) rather than inventing a different number.

---

## Non-Goals (NOT implemented)

- ❌ H3.1 (the roadmap tick stage) — not started (task prompt, non-goals).
- ❌ L3.4's reconcile brief (`stage_registry.render_reconcile`) is not budgeted and stays verbatim (task prompt, non-goals; H2.1 req 3).
- ❌ Model routing / buying a larger context window — E4.6's; this task shrinks the prompt instead (roadmap H2.1 Notes).
- ❌ The author-prompt conciseness budget (`_check_conciseness` / `PROMPT_BYTE_BUDGET`, L5.3) is untouched and is not conflated with this size contract (task prompt, non-goals).
- ❌ No commit, push, or PR opened by this stage; delivery belongs to `/pr`.
