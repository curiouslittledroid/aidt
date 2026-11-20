# Build Results — C1.3: Inline the resolved gate commands into the stage prompts that reference them

**Branch:** `05-C1.3`
**Date:** 2026-11-20
**Spec:** `design.md` §7.3 (prompt rendering, decision D2 — the new step 5 gate-block injection beside step 4's read channel), §8.2 (`aidw implement`, the gate/citation flow whose stage prompts re-derive the repo's commands per stage), §17 (resolved decisions, row Z17); roadmap entry C1.3 in `docs/tasks/05 - Pipeline efficiency.md`; `docs/task-prompts/05-C1.3-prompt.md`; `docs/migration/prompt-classification.md` (the bucket-(i) byte-freeze and its re-classification); `aidw/conventions.md` (traceability artefacts)
**Pull request:** [#174](https://github.com/curiouslittledroid/aidt/pull/174)

## Summary

**Purpose:** The five stage prompts that tell an agent to run the repo's gates only named them as "the repo's own, taken by name from `aidw/conventions.md`/root `AGENTS.md`", so every stage re-derived (or guessed) the commands even though the prompt workflow already resolved them; C1.3 injects that resolved block into each of those prompts as text, once, from a single resolution path.

| Decision | Why it matters |
|----------|---------------|
| One resolution path: `aidw/prompts.py:resolved_gate_block(repo_root) -> str | None`, with `gates_section` moved there and `aidw/workflows/prompt.py:_gate_block` reduced to a wrapper mapping `None` → `_EVIDENCE_UNAVAILABLE` | The evidence bundle and the stage-prompt injection cannot resolve two different gate lists, and the workflow module's existing callers/tests keep importing `_gates_section` through the re-export. The resolver returns `None`, never a sentinel string, because the two consumers take different no-resolution contracts. |
| `GATE_PROMPTS` is a frozenset of the five **resolved** basenames (`impliment-task.md`, `test.md`, `fix-next-review-followup.md`, `record-implementation-results.md`, `code-review.md`), keyed exactly like `CONVENTIONS_PROMPTS` | A repo shadow (or explicit prompt path) keys by its own basename, and the set is deliberately not `CONVENTIONS_PROMPTS`: the fix and code-review prompts record gate outcomes, while `task-prompt.md` and `update-traceability.md` do not. |
| `inject_gate_block(prompt_text, prompt, repo_root)` appends the block verbatim under `## Resolved gate commands (AGENTS.md + aidw/conventions.md)`, called from `run_stage` **after** `inject_repo_conventions` | Mirroring `CONVENTIONS_HEADER`'s source-labelled shape, and applying it after the conventions append means the written `.rendered.md` and the stdin payload to Pi carry the same text; a prompt outside the five, or a repo that resolves nothing, returns the text **byte-identically** — an `unavailable` note is the evidence bundle's degrade and is never injected into a stage prompt. |
| The duplication corner is decided explicitly: for the three prompts in both sets, the focused resolved block is the authoritative "resolved gate commands" presentation (its header appears exactly once) and the whole-file conventions append is **not** de-duplicated | C1.1's contract is a verbatim whole-file append; trimming it would make the injected conventions depend on a second reader. The relationship is recorded in Z17 rather than left silent. |
| `code-review.md` is re-classified out of byte-frozen bucket (i) into a new post-cutover class (v), and out of `BYTE_FROZEN`; every other bucket-(i) file stays byte-frozen and §4.2's own (i) list is still asserted verbatim | A file whose bytes changed cannot honestly stay "ship as-is", and weakening the guard (rather than re-classifying) would hide the edit; class (v) is asserted two-sidedly so no second file can quietly leave the freeze. |
| Every `aidw gate run <key> $SCOPE -- <command>` wrapper and its key/scope guidance is kept; only the "never inlined here" clause became a pointer | A repo's gate section is **bare commands**, so the injection supplies the commands, never the wrapper; `test_prompt_neutrality.py:test_each_prompt_keeps_the_gate_recording_idiom` and the `$SCOPE` reuse contract depend on the wrappers surviving. |

**Where it fits in the roadmap:** Phase 05 ("Pipeline efficiency"), epic C1 ("Prompt context economy"), task C1.3 — the last task in the epic. It depends on C1.2 (§17 row Z16), whose resolved source (two recognised headings plus a config-declared `gates_heading`) it consumes unchanged, and on C1.1 (Z15), whose conventions channel and `AGENTS.md` non-append it extends rather than reverses. It is recorded as §17 row `Z17`, the next free id after `Z16`, and is not a reuse or renumbering of an existing row. It exists to remove the per-stage re-derivation and the key/command/scope drift that defeats gate-outcome reuse.

**Scope:** The gate-block injection and the five prompt edits: `aidw/prompts.py` (`GATE_PROMPTS`, `gates_section` moved in, `resolved_gate_block`, `receives_gate_block`, `inject_gate_block`, the header constants and comment updates), `aidw/workflows/prompt.py` (`_gate_block` wrapper, `_gates_section` re-export, `_GATES_HEADING`/`load_target_config` imports dropped), `aidw/runner.py` (one call at the `inject_repo_conventions` seam), the five prompt files, `docs/migration/prompt-classification.md`, `docs/target-repo-config.md`, `design.md` (§7.3 step 5 + the `Z17` row), plus the three contract-test modules. It deliberately stops short of extending C1.2's heading recognition or doctor diagnosis, of Epic G1's prompt-review depth work (`task-review.md`, `aidw/findings.py`, the prompt-workflow preflight), and of adding `pr.md`, `update-traceability.md` or `update-architecture.md` to `GATE_PROMPTS` — the roadmap fixes exactly five. The evidence bundle's degrade contract is unchanged.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/05-C1.3-prompt.md` | Created | The task prompt (spec references, requirements, prompt-fixed decisions, traps, non-goals, deliverables, tests). |
| `aidw/prompts.py` | Modified | Adds `GATE_PROMPTS`, `GATE_BLOCK_SOURCES`/`GATE_BLOCK_HEADER`, `receives_gate_block`, `inject_gate_block` and `resolved_gate_block`; `gates_section` moved here from the workflow module; comment updates naming the single resolution and its two consumers. |
| `aidw/runner.py` | Modified | Calls `inject_gate_block` at the `inject_repo_conventions` seam (after it) so the written `.rendered.md` and the Pi stdin payload carry the same text. |
| `aidw/workflows/prompt.py` | Modified | `_gates_section` becomes a re-export of `aidw.prompts.gates_section`; `_gate_block` becomes a thin wrapper over `resolved_gate_block` mapping `None` → `_EVIDENCE_UNAVAILABLE`; the now-unused `_GATES_HEADING`/`is_recognised_gates_heading`/`read_conventions_sources`/`load_target_config` imports are dropped. |
| `prompts/impliment-task.md` | Modified | The "never inlined here" clause becomes a pointer naming the injected resolved gate block as authoritative when present, with the `aidw/conventions.md`/root `AGENTS.md`/task-prompt fallback kept; the `<the repo's package-scoped … command>` placeholders and the `aidw gate run` wrappers stay. |
| `prompts/test.md` | Modified | Same pointer replacement in step 6, keeping the `aidw gate run <key> -- <command>` wrapper and the `pr.md` key/scope guidance. |
| `prompts/fix-next-review-followup.md` | Modified | Same pointer replacement in "6. Verify the fix", keeping every `aidw gate run <key> $SCOPE --` template. |
| `prompts/record-implementation-results.md` | Modified | Same pointer replacement in step 4, keeping the bare-command placeholders and the `aidw gate run … $SCOPE` wrappers. |
| `prompts/code-review.md` | Modified | Review-order step 6 gains gate-command guidance: the injected block is authoritative when present, otherwise take commands by name from `aidw/conventions.md` or the root `AGENTS.md`, and record a citable outcome through `aidw gate run <key> -- <command>`. |
| `docs/migration/prompt-classification.md` | Modified | `code-review.md` re-classified from bucket (i) "ship as-is" to new class (v) (post-cutover re-classification, C1.3), with the bucket-(i) freeze statement narrowed to "minus class (v)". |
| `docs/target-repo-config.md` | Modified | The `gates_heading` row and the related-documents bullet now name `aidw/prompts.py:resolved_gate_block` as the one resolution both consumers use. |
| `design.md` | Modified | §7.3 gains step 5 (the injection, the five-prompt set, the header, the byte-identity guarantee, the duplication resolution) and the step list is renumbered; §17 gains row `Z17` with decisions (a)–(f). |
| `tests/test_conventions_injection.py` | Modified | C1.3 coverage: the five-prompt set vs `CONVENTIONS_PROMPTS`, the hand-calculated D16-ordered verbatim join, per-prompt injection under the header, byte-identity for `pr.md`/`task-prompt.md`/`update-traceability.md`, repo-shadow keying, no-source/no-heading `None` + byte-identity, the target-vs-toolkit-root sentinel, purity, the dry-run render seam (header exactly once, ordering, `pr.md` unchanged), re-baselined fixture sentinels moved outside the gate section, and the property sweep over the prompt × source matrix. |
| `tests/test_prompt_classification.py` | Modified | Re-baselines `BYTE_FROZEN` and `EXPECTED_CLASS` for the new class (v), accepts `(v)` in the table parser, and pins the exception two-sidedly (spec's (i) list still verbatim; no `code-review.md` in the freeze; every other (i) file still frozen; the file's bytes really moved). |
| `tests/test_design_doc.py` | Modified | Pins §7.3 step 5's wording (the five basenames, `GATE_PROMPTS`, the header, byte-identity, no injected `unavailable`, C1.1's split intact) and exactly one C1.3 §17 row matched by task id + wording, never by `Z` number. |

---

## Verification Results

Every row below is a real observation from this recording run. The gate commands are the repo's
own (`AGENTS.md` "Gates — run exactly these, and only these"), recorded through
`aidw gate run <key> $SCOPE -- <command>` with the four-directory scope
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`
(all four resolved from `aidw config show`, i.e. the configured write-targets of this workflow's
stages). Every recorded outcome is against tree `fba465750012`, stage
`record-implementation-results`, except the `suite` row, which is this run's own reuse of the
`update-traceability` stage's recorded outcome for the same tree — cited with its origin below.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass — `Checked 19 packages in 0.86ms`, exit 0 |
| Build | `uv build --out-dir <mktemp -d>` (via `aidw gate run build`) | ✅ Pass — `aidt-1.5.0.tar.gz` and `aidt-1.5.0-py3-none-any.whl` built; gate `build` passed for tree `fba465750012` at `2026-11-20T07:34:47Z` |
| Test | `uv run --frozen pytest` (via `aidw gate run suite`) | ✅ Pass — `reused: gate 'suite' passed for tree fba465750012 at 2026-11-20T07:34:09Z by stage 'update-traceability' (2425 passed in 48.96s)`, exit 0 (no re-run: same tree, same declared scope) |
| Doctor | `uv run --frozen aidw doctor` (via `aidw gate run doctor`) | ✅ Pass — `23 checks: 0 failed, 2 warning(s)`; WARNs are the pre-existing `git branch 05-C1.3, dirty working tree` and `mcp config missing`; `gates heading` is `ok`; exit 0; gate `doctor` passed for tree `fba465750012` at `2026-11-20T07:34:54Z` |
| Agents validate | `uv run --frozen aidw agents validate --strict` (via `aidw gate run agents`) | ✅ Pass — `11 agent config(s): 0 error(s), 0 warning(s)`; gate `agents` passed for tree `fba465750012` at `2026-11-20T07:34:55Z` |
| Prompts check | `uv run --frozen aidw prompts check` (via `aidw gate run prompts`) | ✅ Pass — `resolved repo prompts: 0 error(s), 0 warning(s)`, 43 files; gate `prompts` passed for tree `fba465750012` at `2026-11-20T07:34:55Z` |
| Whitespace | `git diff --check` | ✅ Pass — no output, exit 0 |
| Lint | — | **unverified** — this repo configures no lint command (`AGENTS.md`: "no linter, formatter, or type-checker is configured — don't add one inside an unrelated task"; `aidw/conventions.md` adds no gates) |

### `uv run --frozen pytest` (full suite)

Every row is derived from the single recorded `suite` outcome above; nothing was re-run to obtain
a count.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`uv run --frozen pytest`) | 2425 | ✅ Pass (`2425 passed in 48.96s`) |
| C1.3 contracts (`tests/test_conventions_injection.py`, `tests/test_prompt_classification.py`, `tests/test_design_doc.py`) | included above | ✅ Pass — these modules are part of the 2425 and no test in the run failed |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| The gate-prompt set is exactly the five and not `CONVENTIONS_PROMPTS` (both differences asserted) | ✅ Pass (`test_c13_the_gate_prompt_set_is_exactly_the_five_and_not_the_conventions_set` — inside the recorded suite) |
| `resolved_gate_block` joins the two heading-bearing sources verbatim in D16 order (hand-calculated `EXPECTED_GATE_BLOCK`) | ✅ Pass (`test_c13_resolved_gate_block_joins_the_sections_verbatim_in_d16_order`) |
| Each of the five basenames receives the block under the one header; `pr.md`/`task-prompt.md`/`update-traceability.md` stay byte-identical | ✅ Pass (`test_c13_each_gate_prompt_receives_the_block_under_its_header`, `test_c13_prompts_outside_the_five_stay_byte_identical`) |
| A repo shadow keys by resolved basename; no-source and no-recognised-heading repos resolve `None` and render byte-identically (never an `unavailable` note) | ✅ Pass (`test_c13_a_repo_shadow_is_injected_by_basename_not_stage_id`, `test_c13_a_repo_with_no_source_resolves_none_and_renders_identically`, `test_c13_a_source_without_a_recognised_heading_resolves_none`) |
| Two roots: the block reads the **target** root (both target sentinels present in D16 order; the toolkit's own `uv sync --frozen` absent) | ✅ Pass (`test_c13_the_gate_block_reads_the_target_root_not_the_toolkit_root`) |
| Purity: resolution and injection write nothing and mutate no input; the dry-run render seam carries the block exactly once, after the conventions append, and `pr.md`'s render is unchanged | ✅ Pass (`test_c13_resolution_and_injection_write_nothing_and_mutate_no_input`, `test_c13_the_dry_run_render_carries_the_block_exactly_once`) |
| `code-review.md` is out of byte-frozen bucket (i) as class (v); every other bucket-(i) file stays byte-frozen and §4.2's (i) list is still verbatim | ✅ Pass (`test_the_reclassified_prompt_is_out_of_the_spec_bucket_and_the_freeze`, `test_bucket_i_prompts_are_unchanged_since_the_pre_marker_baseline`, `test_the_classification_partitions_the_specs_31_files`) |
| The four bucket-(ii) prompts keep the `aidw gate run` idiom and both conventions sources | ✅ Pass (`tests/test_prompt_neutrality.py::test_each_prompt_keeps_the_gate_recording_idiom` — unmodified, inside the recorded suite) |
| §7.3 step 5 wording and exactly one C1.3 §17 row (matched by task id + wording, never `Z` number) | ✅ Pass (`test_c1_3_section_7_3_and_decision_row_record_the_gate_block_injection`) |
| `grep -n "inlined here"` over each of the five prompt files finds nothing (the clause's tail sits on its own wrapped line) | ✅ Pass — read-only `grep -rn "inlined here" prompts/` returns only `prompts/task-prompt.md:153`, which is not one of the five; each of the four that carried the clause still names `aidw/conventions.md` and the root `AGENTS.md`, and `code-review.md`'s step 6 names `aidw gate run` and both sources |
| The `aidw gate run <key> $SCOPE -- <command>` wrapper survives in every edited prompt | ✅ Pass — `aidw gate run` occurrences: `impliment-task.md` 4, `test.md` 3, `fix-next-review-followup.md` 7, `record-implementation-results.md` 6, `code-review.md` 1 |

---

## Deviations observed during recording

- **No `lint` gate exists to record** — the record prompt's illustrative `lint`/`build`/`suite`
  triple maps onto this repo only as `build` and `suite`; `AGENTS.md` states no lint command exists
  and forbids adding one in an unrelated task. The row is therefore `unverified` with that reason
  rather than invented or borrowed from another stack.
- **The suite was cited, not re-run** — `aidw gate run suite` reported `reused` for tree
  `fba465750012`, recorded at `2026-11-20T07:34:09Z` by stage `update-traceability` with
  `2425 passed in 48.96s` and the identical `--ignore` scope. That is this run's own recorded
  observation of the same content, so the row cites it with its origin instead of buying a second
  run.
- **No per-module test counts were obtained** — the focused C1.3 modules were not invoked a second
  time to produce per-file counts; they are reported as part of the single recorded full-suite
  outcome, as the record prompt requires.
- **Two fixture tests were re-baselined rather than newly satisfied** — moving the
  `AGENTS.md`/`conventions.md` sentinels into their own `## Notes` section and replacing
  `code-review.md` with `pr.md` in `test_no_other_prompt_is_injected` is a consequence of C1.3's
  channel, not a weakening: the assertions are stricter (the gate header must appear exactly once,
  the repo-conventions header must not).

---

## Non-Goals (NOT implemented)

- ❌ C1.2's heading recognition and doctor diagnosis are untouched — `GATES_HEADINGS`,
  `is_gates_like_heading`/`is_recognised_gates_heading` and `aidw/doctor.py`'s `gates heading` check
  are not extended here (task prompt "Explicit non-goals", Z16).
- ❌ Epic G1 (prompt review depth: G1.1 findings classification, G1.2 feasibility preflight) is not
  started — `prompts/task-review.md`, `aidw/findings.py` and the prompt-workflow preflight are
  untouched (task prompt "Explicit non-goals").
- ❌ `pr.md`, `update-traceability.md` and `update-architecture.md` are **not** added to
  `GATE_PROMPTS` even though they reference gate commands or the conventions sources — the roadmap
  fixes exactly five (task prompt "Explicit non-goals").
- ❌ The repo's commands are not re-synthesised or re-keyed — the verbatim gate section is injected
  and the `aidw gate run` key/scope wrapping stays the prompt files' own text (task prompt
  "Explicit non-goals").
- ❌ No new stage id, `when=` token, config key, JSON-schema node, `REQUIRED_PROMPTS` entry or new
  CI gate (Z17 "Gate impact").
- ❌ No pull request opened, no commit or push — the `/pr` stage owns delivery (record prompt
  non-goals).
