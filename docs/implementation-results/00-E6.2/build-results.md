# Build Results — 00-E6.2: Preserve matching semantics exactly

**Branch:** `00-E6.2`
**Date:** 2026-11-05
**Spec:** `docs/migration/EXTRACTION.md` §3.9 (persisted GitHub contracts, freeze semantics D5), §2 (locked decision D5: marker and label literals are frozen), §3.12 (repo layout authority); `docs/task-prompts/00-E6.2-prompt.md`; `docs/tasks/00 - Extraction.md` E6.2

## Summary

**Purpose:** Pin the review-followup scripts' frozen matching semantics with tests only, so a plausible "improvement" — whitespace normalisation, case folding, regex matching, or a label-edit path — fails in the suite instead of orphaning persisted GitHub parents and creating duplicate issues.

| Decision | Why it matters |
|----------|---------------|
| All new vectors live in one new file, `prompts/scripts/review-followup/tests/test_matching_semantics.py`; no pre-existing test file is edited | The roadmap's Done-when ("`test_logic.py` and `test_publish_logic.py` pass unmodified") is provable by byte-identity only while the diff touches neither file. |
| Every wrong-value vector has an exact-case/exact-byte positive control | Without the control a test could pass vacuously — e.g. a fixture that is unavailable for an unrelated reason would "prove" case sensitivity it never exercised. |
| Tests are env-var-free and read markers/definitions through `gh`'s accessors | `test_github_config.py` owns the configured/fail-closed handoff and its reload fixture; these tests pin the frozen semantics as actually rendered. |
| The literal-marker property is seeded (`random.Random`) with a pinned run count rather than adding Hypothesis | Reproducible near-miss cases without a new dependency for one module's property test; each iteration also asserts the exact marker still matches, so a matcher that finds nothing fails too. |
| "Ensure existing never overwrites" pins both that `create_label` is not called for an existing name **and** that no script contains a label-edit call | Asserting only the absence of a create call would be vacuous if an overwrite later arrived as `gh label edit`; the structural scan closes that route. |

**Where it fits in the roadmap:** Second task of epic E6 (GitHub contracts as config). It depends on E6.1's resolved marker/label handoff and the pre-existing bundled scripts, and it guards the D5 semantics that E6.3's authoritative `baseline-verbatim` golden and E6.4's freeze documentation describe. E6.3 and E6.4 remain separate tasks.

**Scope:** Adds one tests-only file under the bundled scripts' `tests/` directory and ticks the E6.2 roadmap checkbox. It deliberately stops short of changing any matching code, producing the E6.3 golden, writing E6.4's narrative, or touching E6.1's config plumbing.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E6.2-prompt.md` | Created | Task prompt added on the branch by the prompt-authoring stage. |
| `docs/implementation-results/00-E6.2/build-results.md` | Created | This recording document. |
| `prompts/scripts/review-followup/tests/test_matching_semantics.py` | Created | Pins byte-exact comment matching, literal (non-regex) marker matching, case-sensitive label checks, and "ensure existing" never overwriting, with positive controls and purity checks. |
| `docs/tasks/00 - Extraction.md` | Modified | Ticks E6.2 complete in the E6 roadmap. |

No production matching code, pre-existing test, config, or lockfile was modified: `git diff --name-status main -- prompts/scripts/review-followup aidw tests` produced no output, and the only change under `prompts/scripts/review-followup` is the added test file.

---

## Verification Results

Every recorded gate was run once through `aidw gate run`, with the same scope —
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts` —
for tree `616864f078ef`, stage `record-implementation-results`, on 2026-11-05. The rows below report
this run's own outcomes; no suite, module or subset was re-run to obtain a count.
`uv sync --frozen` and `git diff --check` were run directly because neither is a recorded gate.
No lint gate was run because this repository configures no linter (AGENTS.md, design.md §15).

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 15 packages in 0.72ms`) |
| Build | `uv build --out-dir <tmp>` | ✅ Pass (gate `build`, tree `616864f078ef`, 2026-11-05T05:47:26Z: built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` in a fresh temporary directory) |
| Test | `uv run --frozen pytest` | ✅ Pass (gate `suite`, tree `616864f078ef`, 2026-11-05T05:47:21Z: `1441 passed in 34.04s`) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (gate `doctor`, tree `616864f078ef`, 2026-11-05T05:47:27Z: `19 checks: 0 failed, 2 warning(s)` — dirty working tree and absent `.mcp.json`, both expected mid-run) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (gate `agents`, tree `616864f078ef`, 2026-11-05T05:47:30Z: `11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (gate `prompts`, tree `616864f078ef`, 2026-11-05T05:47:30Z: `prompts check: 0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (no output) |

The environment printed a `VIRTUAL_ENV` mismatch warning for every `uv` invocation because
`/Users/phil/software-projects/aidt-workspace/main/.venv` differs from the project environment
path `.venv`; `uv` ignored it, and the commands themselves produced the outputs above.

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1441 | ✅ Pass (`1441 passed in 34.04s`; no deselections) |
| `prompts/scripts/review-followup/tests/test_matching_semantics.py` | not separately counted | ✅ No failures in the full-suite summary; not re-run for a count |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Comment-body strict equality — exact frozen bodies match; trailing/leading whitespace, newline, case change, extra prose, mention and empty body do not | ✅ Pinned by passing vectors in the full-suite run above |
| Marker literal match — byte-exact parent/child/summary markers match; a body substituting one URL `.` with another character does not, including the seeded property runs | ✅ Pinned by passing vectors in the full-suite run above |
| Label case sensitivity — wrong-case `Approve-fix`, priority labels and `Decision-pending` never satisfy `availability`, `priority_label`, `approval_plan` or `is_approved`; exact-case twins confirm each fixture is non-vacuous | ✅ Pinned by passing vectors in the full-suite run above |
| "Ensure existing" never overwrites — `create_label` is not called for an existing exact name, its colour/description are untouched, a wrong-case existing name does not suppress creation, and no script issues a label edit | ✅ Pinned by passing vectors in the full-suite run above |
| Purity — no vector mutates `constants.LABEL_DEFINITIONS` or `gh.LABEL_DEFINITIONS` | ✅ Autouse purity assertion passed across the new file's vectors |
| Frozen code and pre-existing tests unchanged — `git diff --name-status main -- prompts/scripts/review-followup aidw tests` | ✅ No output; `test_logic.py` and `test_publish_logic.py` are byte-identical to `main` |

---

## Deviations observed during recording

- **The generic record prompt names a pnpm gate set, but this repo's stack is Python/uv.** Per
  `AGENTS.md`, `prompts/pr.md` ("take them from the target repo, not from this prompt") and
  `docs/implementation-results/TEMPLATE.md`, the install/build/test rows are `uv sync --frozen`,
  `uv build` and `uv run --frozen pytest`. No lint gate was run because the repo configures no linter.
- **`uv build` wrote to a fresh `$(mktemp -d)` directory**, leaving no artifacts in the gated tree.
- **The implementation was still uncommitted in the working tree.** The change set was measured
  against `main` including working-tree changes; tree `616864f078ef` covers that content, and this
  stage did not commit it.
- **The task prompt was already committed on the branch by the prompt-authoring stage.** It is part
  of the change set relative to `main` and is listed above.
- **No subsets were re-run for their own counts.** Task-specific rows cite the single full-suite
  invocation above rather than a second run of the new module.

---

## Non-Goals (NOT implemented)

- ❌ E6.3's authoritative `baseline-verbatim` golden (byte-identical markers/labels/comment bodies against the tag) — separate task; this one pins semantics, not the golden byte values (task prompt, explicit non-goals).
- ❌ E6.4's "Document the freeze" narrative in `docs/target-repo-config.md` — separate task (task prompt, explicit non-goals).
- ❌ Any change to E6.1 config plumbing (`gh.py`'s `AIDW_REVIEW_FOLLOWUP_CONFIG` handoff, `aidw/target_config.py` defaults, the serializer) — already delivered (task prompt, explicit non-goals).
- ❌ Any "improvement" to the matching code — normalisation, case folding, regex escaping, or a label-edit path (task prompt, explicit non-goals).
- ❌ No PR opened and nothing committed by the recording stage (`prompts/pr.md` owns delivery).
