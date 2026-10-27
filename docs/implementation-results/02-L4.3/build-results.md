# Build Results — 02-L4.3: Make the revision budget configurable

**Branch:** `02-L4.3`
**Date:** 2026-10-27
**Spec:** `docs/tasks/02 - Prompt loop integrity.md`, `design.md §8.1`, `design.md §12`, `design.md §14`, `AGENTS.md`

## Summary

**Purpose:** Make the revision budget in the `aidw prompt` loop configurable via a `--max-revisions <n>` CLI flag and document the key in design.md.

**Where it fits in the roadmap:** This task parameterizes the `MAX_REVISIONS` constant as part of Phase 02's Prompt loop integrity. The actual configuration loader for target repos is deferred to E3.1. The task documents the `max_revisions` key in design.md §12 and §14 and leaves a seam comment in `aidw/workflows/prompt.py` for E3.1 to insert the target-config read.

**Scope:** Adds the `--max-revisions` flag to the CLI and parameterizes the revision budget in the workflow. Updates design docs §8.1, §12, and §14. Does not implement the target-repo config loader (E3.1/E3.2/E3.6) or change the terminal-review shape.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L4.3-prompt.md` | Created | Task prompt defining the requirements for making the revision budget configurable. |
| `aidw/cli.py` | Modified | Added `--max-revisions <n>` option to the `prompt()` command. |
| `aidw/workflows/prompt.py` | Modified | Renamed `MAX_REVISIONS` to `DEFAULT_MAX_REVISIONS`, added `max_revisions` parameter to `run()`, resolved the value, and updated docstrings/comments. |
| `design.md` | Modified | Updated §8.1, §12, and §14 to document the configurable revision budget. |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified | Updated task status/notes for L4.3. |
| `tests/test_prompt_workflow.py` | Modified | Added/updated tests for the new `--max-revisions` flag and the parameterized loop. |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (Checked 15 packages in 0.81ms) |
| Test | `uv run --frozen pytest` | ✅ Pass (662 passed in 102.42s) |
| Doctor | `uv run aidw doctor` | ✅ Pass (14 checks: 0 failed, 2 warnings) |
| Agents validate | `uv run aidw agents validate --strict` | ✅ Pass (11 config(s): 0 errors, 0 warnings) |
| Prompts check | `uv run aidw prompts check` | ✅ Pass (0 errors, 0 warnings) |
| Install (pnpm) | `pnpm install` | ❌ Fail (`ERR_PNPM_NO_PKG_MANIFEST`: No package.json found in /Users/phil) |
| Lint (pnpm) | `pnpm -r lint` | ✅ Pass (No projects found) |
| Build (pnpm) | `pnpm -r build` | ✅ Pass (No projects found) |
| Test (pnpm) | `pnpm -r test` | ✅ Pass (No projects found) |
| Whitespace | `git diff --check` | ✅ Pass |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 662 | ✅ Pass (662 passed in 102.42s) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run --frozen pytest` stays green | ✅ Pass — 662 tests passed; the gate was run with stage/run identity variables unset so CLI gate tests observe their intended standalone context. |

---

## Deviations observed during recording

- **`pnpm` commands executed against a Python repo** — The instructions provided `pnpm install`, `pnpm -r lint`, etc. as the "full verification gate". These commands do not apply to this repository (no `package.json`), so `pnpm install` failed with `ERR_PNPM_NO_PKG_MANIFEST` and the recursive commands reported "No projects found". The actual Python gates were run via `uv`.
- **`pytest` failures due to stage context** — The `uv run --frozen pytest` suite was run through `aidw gate run`, which sets a stage context. Two tests (`test_cli_gate_run_propagates_a_failing_exit_code` and `test_cli_gate_run_records_into_the_branch_run_without_an_env_identity`) failed because they expect a default "cli" stage and a specific exit code propagation that does not occur when run from within the "record-implementation-results" stage. These are test-environment artifacts, not code defects.

---

## Non-Goals (NOT implemented)

- ❌ E3.1/E3.2/E3.6 (target-repo config loader, layered resolution with provenance, `docs/target-repo-config.md` contract, `docs/schema/aidw-config.schema.json`) — they own the config-read half; L4.3 documents the key only. Do not implement the loader or write the contract doc/schema.
- ❌ L6.1 (synthesized fixture pinning the whole loop contract) and L6.2 (consolidating §17 decisions + re-baselining E4.1/E4.3) — later; this task edits only design.md §8.1/§12/§14, nothing in `docs/tasks/00 - Extraction.md` and no new §17 row.
- ❌ Do not change the terminal-review shape itself (L4.1's "last slot is a review, residual Request changes fails closed") — only parameterize the number.
- ❌ Do not add a cost/round-count/latency gate or threshold (phase preamble "Explicit non-goals for phase 02").
