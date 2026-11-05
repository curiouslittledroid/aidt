# Build Results — 00-E6.4: Document the freeze

**Branch:** `00-E6.4`
**Date:** 2026-11-05
**Spec:** `docs/migration/EXTRACTION.md` §3.9 (persisted GitHub contracts — freeze semantics), §3.4 (target-repo config: the `github:` block shape), §2 (locked decision D5 — marker and label literals are frozen), §3.12 (repo layout authority for `docs/target-repo-config.md`), §9 (one-time marker/label migration — out of scope)

## Summary

**Purpose:** Document, in the one place a config editor reads before declaring `github:` in `aidw/config.yaml`, why the persisted GitHub strings are config-with-frozen-defaults and exactly what renaming one breaks (orphaned parent/child pairings, duplicate issues and duplicate labels), so a plausible-looking "config tweak" is read as a migration that duplicates live issues.

| Decision | Why it matters |
|----------|---------------|
| The narrative expands E6.1's one-sentence "Freeze means…" intro **inside** the existing `### github:` section, above the defaults tables | The prompt fixes the placement where a config editor lands while deciding whether to declare the block; a standalone section or a schema footnote is read after the decision, not before it. |
| The rename consequence is stated as *warning prose around the drift-checked tables*, never as re-typed literals | Requirement 4/D5: hand-copying a marker template or label colour into new prose is precisely the drift the freeze exists to prevent; every value the prose refers to is the table literal seeded at `TOOLKIT_DEFAULTS.github`. |
| The lookup symbol is cited in the **bundled script** (`prompts/scripts/review-followup/gh.py:find_parent_issues`), not `aidw/github.py` | §3.9's exact-match lookup lives in the review-followup script that writes to GitHub; pointing at the toolkit's own GitHub helper would mislead the reader about which code path is frozen. |
| The scope boundary is stated explicitly: `github.markers`/`github.labels` are config-with-frozen-defaults; the three comment bodies and five role-name constants are **not** config | §3.4 has no field for them, so presenting them as overridable would contradict the loader; `tests/test_target_config.py` pins the two homes (`constants.py` and `TOOLKIT_DEFAULTS.github`) equal, so a "configurable" claim would be a lie the suite already disproves. |
| The label rename consequence is "creates beside the old one", not "edited in place" | E6.2: the "ensure existing" path only creates names it does not find and never overwrites, so a rename duplicates the label rather than updating it. |
| The doc test pins **semantic presence** (symbols plus the roadmap's own words "orphan"/"duplicate issue"), not a sentence | Wording edits stay free while silently removing the warning fails; a pinned sentence would make copy-editing a test failure. |

**Where it fits in the roadmap:** Final task of epic **E6** (extracting the toolkit from Mythical Forge). It depends on **E6.1** (markers and labels became config with frozen defaults, seeded at `aidw/target_config.py:TOOLKIT_DEFAULTS.github`), **E6.2** (the matching semantics the warning describes — exact-match parent lookup, non-overwriting label "ensure existing", strict-`==` comment detection), and **E6.3** (the `tests/test_baseline_verbatim_golden.py` D5 guard the narrative names as the enforcement). It completes the contracts half of the epic: E6.1 made the strings configurable, E6.2/E6.3 pinned and guarded them, and E6.4 tells a repo owner what changing one costs. **E7.1/E7.2** (prompt-library classification and neutralisation) and **E9.2** (cross-linking the contract docs from the README) follow, and both depend on the freeze being stated rather than assumed.

**Scope:** Documentation-only. A freeze narrative added to the `### github:` section of `docs/target-repo-config.md` (why config-with-frozen-defaults, the three rename failure modes with their code symbols, the not-config boundary, the E6.3 guard and §9's out-of-scope migration), one cross-reference line from the **Toolkit defaults** bullet list back to that narrative, and the doc test extended with eight semantic assertions pinning it. Plus the routine traceability tick of **E6.4** in the extraction roadmap. It deliberately stops short of: any code change (`aidw/target_config.py`, `aidw/github.py`, `prompts/scripts/review-followup/*`), any new config key or schema field, planning the §9 one-time migration, and E7.1/E7.2's prompt-library split or E9.2's README cross-linking.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/implementation-results/00-E6.4/build-results.md` | Created | This document (written by the record stage after gating). |
| `docs/task-prompts/00-E6.4-prompt.md` | Created | Task brief for this task (written by the task-prompt stage, committed as `fdbd417`). |
| `docs/target-repo-config.md` | Modified | Expands E6.1's "Freeze means…" intro in `### github:` into the full narrative: why config-with-frozen-defaults (D5 + brand neutrality + D17 byte-identical defaults), a warning block naming the three rename failure modes with their symbols (`find_parent_issues` exact match → orphaned pairings and duplicate issues; `ensure_labels` create-only → duplicate label; `has_exact_comment` strict `==` → broken availability/idempotency detection), the not-config boundary (comment bodies and role names stay in `constants.py`), and the `test_baseline_verbatim_golden.py` guard plus §9's out-of-scope migration. Adds a cross-reference line from the **Toolkit defaults** `github.*` bullets back to the narrative, and tightens the post-table "not config" note to point at that same boundary. Tables, defaults and the Full example are unchanged. |
| `tests/test_target_repo_config_doc.py` | Modified | Adds eight tests (`test_freeze_narrative_*`, `test_toolkit_defaults_cross_references_the_freeze_narrative`) plus two helpers (`_github_section`, `_prose`). They assert the narrative precedes the default tables, cites `find_parent_issues` / the exact string match / the bundled script path, states both rename failure modes and the strict-`==` comment comparison, states the D5/§3.9/D17/`TOOLKIT_DEFAULTS.github` rationale, states the not-config boundary in `constants.py`, names the E6.3 guard and §9, and that the prose does **not** re-type any frozen marker template, label colour or description. Docstring updated to describe the new coverage. |
| `docs/tasks/00 - Extraction.md` | Modified | Traceability stage: ticks **E6.4** complete in the 00-Extraction roadmap. |

---

## Verification Results

Every row below was run once, in this recording, against the working tree at commit `fdbd417` plus the three uncommitted files above. `aidw gate run` reported tree id **`a24f7e7435b1`** for every gate.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.42ms` (lockfile in sync, no resolution) |
| Build | `uv build --out-dir $(mktemp -d)` | ✅ `Successfully built aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` |
| Test / suite | `uv run --frozen aidw gate run suite $SCOPE -- uv run --frozen pytest` | ✅ `1457 passed in 27.31s` — gate `suite`, tree `a24f7e7435b1`, stage `record-implementation-results`, 2026-11-05T06:46:23Z |
| Doctor | `uv run --frozen aidw gate run doctor $SCOPE -- uv run --frozen aidw doctor` | ✅ `19 checks: 0 failed, 2 warning(s)` — the two warnings are the expected `dirty working tree` and `missing .mcp.json`; gate `doctor`, tree `a24f7e7435b1`, 2026-11-05T06:46:29Z |
| Agents validate | `uv run --frozen aidw gate run agents-validate $SCOPE -- uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` — gate `agents-validate`, tree `a24f7e7435b1`, 2026-11-05T06:46:30Z |
| Prompts check | `uv run --frozen aidw gate run prompts-check $SCOPE -- uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` — gate `prompts-check`, tree `a24f7e7435b1`, 2026-11-05T06:46:30Z |
| Lint | — | ❌ **unverified** — no linter, formatter or type-checker is configured in this repo (`AGENTS.md` §Gates / `design.md` §15), so there is no lint gate to run |
| Whitespace | `git diff --check` | ✅ clean (no output, exit 0) |

`$SCOPE` = `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` (the write-targets of the other stages of this workflow; nothing a gate reads is excluded).

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1457 | ✅ Pass (`1457 passed in 27.31s`, gate `suite`, tree `a24f7e7435b1`, 2026-11-05T06:46:23Z) |
| `tests/test_target_repo_config_doc.py` | 28 | ✅ Pass (collected via `pytest --collect-only -q`; executed inside the two-file gate below, not a second full-suite run) |
| `tests/test_baseline_verbatim_golden.py` | 8 | ✅ Pass (collected via `pytest --collect-only -q`; executed inside the two-file gate below) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run --frozen aidw gate run docs-freeze-contract $SCOPE -- uv run --frozen pytest tests/test_target_repo_config_doc.py tests/test_baseline_verbatim_golden.py` (the task prompt's Done-when command) | ✅ `36 passed in 0.78s` — gate `docs-freeze-contract`, tree `a24f7e7435b1`, 2026-11-05T06:46:34Z |
| `test_freeze_narrative_precedes_the_marker_and_label_tables` | ✅ pass |
| `test_freeze_narrative_cites_the_exact_match_lookup_by_symbol` | ✅ pass |
| `test_freeze_narrative_states_both_rename_failure_modes` | ✅ pass |
| `test_freeze_narrative_states_why_they_are_config_with_frozen_defaults` | ✅ pass |
| `test_freeze_narrative_states_the_not_config_scope_boundary` | ✅ pass |
| `test_freeze_narrative_names_the_guard_and_the_out_of_scope_migration` | ✅ pass |
| `test_freeze_narrative_does_not_retype_the_frozen_literals` | ✅ pass |
| `test_toolkit_defaults_cross_references_the_freeze_narrative` | ✅ pass |
| Pre-existing assertions in `tests/test_target_repo_config_doc.py` (field inventory matches the loader's keys, fenced `yaml` examples load, defaults/Full-example agreement) | ✅ unchanged and green — the narrative adds no key and no fence, as required by requirement 4/traps |
| D5 guard still green — `tests/test_baseline_verbatim_golden.py` against the `baseline-verbatim` tag (`d3cc1bc`) | ✅ pass (8 tests, in the same two-file gate) |
| Mutation check — perturb a frozen literal and confirm `test_freeze_narrative_does_not_retype_the_frozen_literals` fails | ❌ **unverified** — that would mutate the tree this document records, which the record stage must not do; the assertion's logic is exercised by the same run's positive case |
| Rendered reader experience (the warning reads as a warning, not a schema footnote) | ❌ **unverified** — a judgment on prose presentation in a Markdown viewer; no automated check can assert it |

---

## Deviations observed during recording

- **Gate stack.** The stage prompt's `pnpm install` / `pnpm -r lint|build|test` rows are another repo's stack; this repo is Python/uv and `AGENTS.md` names `uv sync --frozen`, `uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents validate --strict`, `uv run aidw prompts check`. Those were run, plus `uv build` to fill the template's Build row. No `pnpm` command was executed.
- **Doc test count.** The file now collects 28 tests from 24 `def test_` functions because two are parametrised (5 and 3 cases); the eight E6.4 additions are unparametrised.
- **Task gate key.** The task prompt's Done-when names the two-file pytest command; it was recorded under the key `docs-freeze-contract` because it is task-specific rather than the repo's `suite` gate.

---

## Non-Goals (NOT implemented)

- ❌ E7.1/E7.2 prompt-library classification and neutralisation — the freeze narrative explains *why* the GitHub strings are frozen; the broader prompt split is separate (task prompt, "Explicit non-goals").
- ❌ Any code change: `aidw/target_config.py`, `aidw/github.py`, `prompts/scripts/review-followup/*` — E6.1 (plumbing), E6.2 (semantics pins) and E6.3 (golden) are delivered and left untouched (task prompt, "Explicit non-goals").
- ❌ No new config key or schema field — §3.4 has no field for comment bodies/role labels, and this task adds none (task prompt; D5/§3.4).
- ❌ No design of the §9 one-time migration across open issues — the doc states it is out of scope; it does not plan it (task prompt; §9).
- ❌ E9.2 cross-linking both contract docs from the README — separate task (task prompt, "Explicit non-goals").
- ❌ No commit, push or PR opened by this stage (`prompts/pr.md` owns delivery).
