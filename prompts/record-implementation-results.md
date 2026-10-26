---
description: Run the full verification gate and write docs/implementation-results/<branch>/build-results.md
argument-hint: "[branch]"
---

# Record implementation results

The implementation, its contract tests, and the traceability updates are complete on the current
branch. This prompt owns **only two things**: running the full verification gate and recording its
**real** outcomes in `docs/implementation-results/<branch>/build-results.md`. It does not change
implementation code, tests, or traceability artifacts, and it does not commit, push, or open a PR.

Keeping this separate means the implementation agent never has to own the whole-repo gate or the
results document, and the recorded numbers come from a dedicated, reproducible run.

## Variables

- `$1` (optional) — branch name override. Default: `git branch --show-current`.

## Owned artifact (the only file this prompt may write)

`docs/implementation-results/<branch>/build-results.md`, using `docs/implementation-results/TEMPLATE.md`.

Do **not** modify implementation code, unit/handler tests, integration suites, `catalog.json`,
`vectors.ts`, specs, the roadmap, or architecture docs.

## Instructions

1. Read `docs/implementation-results/TEMPLATE.md` in full — it is the required structure. If that
   file does not exist, **stop and report it** — do not invent a structure and do not substitute
   another document as the template. (The path is the target repo's configured build-results
   template; resolving to a missing file is a configuration error to report, not to work around.)
2. Determine the branch and the change set:
   ```bash
   git branch --show-current
   git merge-base main HEAD
   git log --oneline main..HEAD
   git diff --stat main...HEAD
   git status --short --untracked-files=all
   ```
   Note that earlier stages may have left work **uncommitted**; the change set is the working tree
   relative to `main`, not only the commits.
3. Read the task prompt (`docs/task-prompts/<branch>-prompt.md`) and the implementation's final
   response for the task id, purpose, scope, deviations, and non-goals.
4. Run the **full verification gate** and capture the real output of each command:
   ```bash
   pnpm install
   pnpm -r lint
   pnpm -r build
   pnpm -r test
   ```
   Then run every **task-specific** gate named in the task prompt (e.g. `pnpm srd:validate`,
   `pnpm srd:check-references`, `pnpm srd:matrix-check`, `pnpm srd:report`,
   `pnpm --filter infra cdk synth -c env=dev`). Do not invent, round, or copy numbers from an
   earlier run or another document — record what this run actually produced.

   **Run each command exactly once, and derive every results row from that single invocation.**
   Do not re-run a suite, module or subset just to obtain a count for its own row — take subsets
   from the same run (for example a per-file summary or a duration report). Re-running the gate is
   the most expensive thing this stage does; a second run of the same suite buys nothing.

   Avoid commands a non-interactive session refuses: do not `rm -rf` (build into `$(mktemp -d)`
   instead) and prefer the repo's existing fixtures over `git init` scratch demos. A blocked
   command costs a turn and produces no evidence.
5. Populate `build-results.md` from the template:
   - Fill `{{TASK_ID}}`, `{{TASK_TITLE}}`, `{{BRANCH}}`, `{{DATE}}`, `{{SPEC_LIST}}`.
   - **Summary:** purpose, key design decisions, roadmap placement, and scope (including what the
     task deliberately stops short of).
   - **Files Changed:** every file touched, with action (Created/Modified) and a one-line description.
   - **Verification Results:** the exact commands and their real outcomes (pass/fail, counts). Mark
     any command that could not run (missing credentials, no network, no deployment) as
     **unverified** with the reason — never as passing.
   - **Non-Goals (NOT implemented):** copied from the task prompt's explicit non-goals.
   - Delete optional template sections that do not apply; do not leave `{{placeholders}}` behind.
6. Run `git diff --check` and review the final diff for stale or invented content.

## Non-goals — do NOT do these

- Do **not** modify implementation code, tests, traceability artifacts, specs, or the roadmap.
- Do **not** commit, push, or open a PR (`aidt/prompts/pr.md` owns that).
- Do **not** write `player-actions.md` or `integration-tests.md` — the `show-updated-*` prompts own those.
- Do **not** record a result you did not observe. If a gate fails, record the failure and stop;
  do not fix it here.

## Done when

- `docs/implementation-results/<branch>/build-results.md` exists, follows `TEMPLATE.md`, and has no
  remaining placeholders.
- Every verification row reports a real outcome from this run, or is explicitly marked unverified
  with the reason.
- `git diff --check` passes and no code/test/traceability file was modified.

## Final response

Return: the document path, the exact gate commands with their real outcomes (pass/fail, counts),
and anything that could not be run and why.
