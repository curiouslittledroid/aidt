# Build Results — {{TASK_ID}}: {{TASK_TITLE}}

**Branch:** `{{BRANCH}}`
**Date:** {{DATE}}
**Spec:** {{SPEC_LIST}}

## Summary

<!--
  Write a concise summary (3–5 paragraphs) covering:
  1. **Purpose** — what the task built and why it matters (one sentence).
  2. **Key design decisions** — use a table if there are multiple trade-offs worth calling
     out (decision | why it matters). Omit if the task was straightforward.
  3. **Where it fits in the roadmap** — which tasks this depends on and which tasks
     depend on it. Place it in the broader epic/phase context.
  4. **Scope** — what the task touches and, just as important, what it deliberately stops
     short of.
-->

**Purpose:** {{ONE_SENTENCE_PURPOSE}}

<!-- Key design decisions table (optional — delete if not applicable) -->
| Decision | Why it matters |
|----------|---------------|
| {{decision}} | {{rationale}} |

**Where it fits in the roadmap:** {{ROADMAP_CONTEXT}}

**Scope:** {{SCOPE}}

---

## Files Changed

<!--
  One table listing every file touched, with the action and a one-line description.
  New files before modified files.
-->

| File | Action | Description |
|------|--------|-------------|
| `{{file-path}}` | Created | {{description}} |
| `{{file-path}}` | Modified | {{description}} |

---

<!--
  OPTIONAL: If describing each change in detail is valuable (multi-file changes,
  non-trivial logic), add a "## Changes Made" section with numbered subsections per
  module. Delete this comment and the section if the file table above is sufficient.

## Changes Made

### 1. `{{MODULE_PATH}}`

{{DETAILED_DESCRIPTION}}

- **Key detail** — ...
-->

---

## Verification Results

<!--
  Report the commands this repo's conventions name as its verification gate, and their
  real outcomes from this run. The example rows below are this repository's stack
  (Python/uv); a different target repo's rows are whatever its own conventions list.
  Every row is a real observation. A command that could not run (missing credentials,
  no network, no deployment) is marked unverified with the reason — never as passing.
-->

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ / ❌ {{details}} |
| Build | `uv build --out-dir <tmp>` | ✅ / ❌ {{details}} |
| Test | `uv run --frozen pytest` | ✅ / ❌ {{details}} |
| Doctor | `uv run --frozen aidw doctor` | ✅ / ❌ {{details}} |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ / ❌ {{details}} |
| Whitespace | `git diff --check` | ✅ / ❌ {{details}} |
| {{repo gate}} | {{command}} | ✅ / ❌ / **unverified** ({{reason}}) |

### `uv run --frozen pytest` (full suite)

<!--
  Derive every row from the single full-gate run above. Do not re-run a suite just to
  obtain a count. If a subset needs its own row, take it from the same invocation
  (e.g. `--durations` or a per-file report), not from a second run.
-->

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | N | ✅ Pass (`N passed`) |
| `{{subset}}` | N | ✅ Pass (`N passed`) |

### Task-specific verification gates

<!--
  Add gates that are specific to this task: validators, smoke scripts, structural or
  behavioural checks named in the task prompt. Delete rows that do not apply.
-->

| Gate | Status |
|------|--------|
| {{gate}} | ✅ {{assertion}} |
| {{gate}} | ❌ **unverified** ({{reason}}) |

---

<!--
  OPTIONAL: where the run diverged from the task prompt — prompt wording that did not
  match the code, gates that did not apply, prerequisite merges. Delete if none.
-->

## Deviations observed during recording

- **{{deviation}}** — {{what was observed and what was done instead}}.

---

## Non-Goals (NOT implemented)

<!--
  Copy from the task prompt's "Explicit non-goals" section. Anything the task explicitly
  said NOT to build goes here so reviewers don't flag it. Add any implicit non-goals that
  were out of scope but might seem in-scope to a reviewer (e.g. "No PR opened").
-->

- ❌ {{non-goal}} ({{reference}})

---

<!--
  OPTIONAL: "## Deliverables Checklist" — use when the task prompt has a checklist of
  concrete deliverables (e.g. specific files, test counts). Delete if not applicable.

## Deliverables Checklist

- [x] `{{file-path}}` — {{description}}
-->

<!--
  OPTIONAL: "## Human Reviewer Checklist" — use when manual verification steps are
  valuable beyond what automated tests cover. Delete if not applicable.

## Human Reviewer Checklist

- [x] {{manual check}}
-->
