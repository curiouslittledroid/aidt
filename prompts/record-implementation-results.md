---
description: Run the repo's full verification gate and write the build-results document in its configured results directory
argument-hint: "[branch]"
---

# Record implementation results

The implementation, its contract tests, and the traceability updates are complete on the current
branch. This prompt owns **only two things**: running the full verification gate and recording its
**real** outcomes in the build-results document under the repo's configured results directory
(`paths.implementation_results_dir`). It does not change
implementation code, tests, or traceability artifacts, and it does not commit, push, or open a PR.

Keeping this separate means the implementation agent never has to own the whole-repo gate or the
results document, and the recorded numbers come from a dedicated, reproducible run.

## Variables

- `$1` (optional) — branch name override. Default: `git branch --show-current`.

## Owned artifact (the only file this prompt may write)

`<implementation_results_dir>/<branch>/build-results.md`, using the configured template
(`paths.build_results_template`).

Do **not** modify implementation code, unit/handler tests, integration suites, the traceability
stage's artifacts, specs, the roadmap, or architecture docs.

## Instructions

1. Read the target repo's build-results template (`paths.build_results_template`) in full — it is
   the required structure. If that file does not exist, **stop and report it** — do not invent a
   structure and do not substitute another document as the template. (The path is the target repo's
   configured build-results template; resolving to a missing file is a configuration error to
   report, not to work around.)
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
3. Read the task prompt (`paths.task_prompts_dir`/`<branch>-prompt.md`) and the implementation's final
   response for the task id, purpose, scope, deviations, and non-goals.
4. Run the **full verification gate** and capture the real output of each command. The commands are
   the **repo's own**, taken by name from its `aidw/conventions.md`, its root `AGENTS.md`, or the
   task prompt for this task — never inlined here:
   ```bash
   <the repo's full lint command>
   <the repo's full build command>
   <the repo's full test command>
   ```
   Then run every **task-specific** gate the task prompt names. Do not invent, round, or copy
   numbers from an earlier run or another document — record what this run actually produced.

   Run each command through `aidw gate run <key> -- <command>`, with the gates named as `pr.md`
   names them and the same `--ignore` scope `pr.md` declares:
   ```bash
   # The four configured write-targets of the stages of this workflow: read each resolved
   # value from `aidw config show` and pass it as one --ignore prefix.
   SCOPE="--ignore <implementation_results_dir> --ignore <architecture_dir> --ignore <roadmap_dir> --ignore <task_prompts_dir>"
   aidw gate run lint  $SCOPE -- <the repo's full lint command>
   aidw gate run build $SCOPE -- <the repo's full build command>
   aidw gate run suite $SCOPE -- <the repo's full test command>
   ```
   The scope declares what the command cannot read: the document this stage writes
   (`implementation_results_dir`) and the ones the other stages write — including any traceability or
   report directory a stage of this workflow writes, which belongs in the same list in every stage so
   the outcomes line up. It is what lets `/pr` cite these outcomes instead of buying the whole gate
   again: this stage writes its results document *after* gating, so without a scope the tree `/pr`
   delivers never matches the tree gated here. Never ignore source, tests, config or lockfiles:
   those must always re-run the gate.

   `aidw gate run` records the outcome against the tree it gated and prints one line naming it.
   Asking again for the same key, command and scope against content that differs only inside that
   scope prints
   `reused: gate 'suite' passed for tree <id> at <time> by stage '<stage>' (<summary>) [scope excludes: ...]`
   and exits 0 **without re-running**. That is evidence, not a copied number: cite it in the row with
   its origin (key, tree, stage, timestamp), because it is this run's own recorded observation of
   this same content. Anything outside this run, or against content that has changed outside the
   scope, is still a number you must not use — re-run it (`aidw gate run --force`) or mark the row
   unverified.

   **Run each command exactly once, and derive every results row from that single invocation.**
   Do not re-run a suite, module or subset just to obtain a count for its own row — take subsets
   from the same run (for example a per-file summary or a duration report). Re-running the gate is
   the most expensive thing this stage does; a second run of the same suite buys nothing.

   Avoid commands a non-interactive session refuses: do not `rm -rf` (build into `$(mktemp -d)`
   instead) and prefer the repo's existing fixtures over `git init` scratch demos. A blocked
   command costs a turn and produces no evidence.
5. Resolve the pull request reference for this branch **before** writing the document. The build
   results name it at the very top, immediately above their `## Summary` section. Ask GitHub
   read-only, and treat "no pull request yet" as an answer rather than an error:
   ```bash
   # <branch> is `$1` when the workflow passed one, else the current branch (step 2)
   gh pr view <branch> --json number,url \
     --jq 'if .number then "#" + (.number|tostring) + " " + .url else empty end' 2>/dev/null || true
   ```
   - **A pull request already exists** — a re-run, a resume, or an implementation started with an
     existing PR number: record it as `#<number>` with its URL beside it.
   - **None exists yet — the normal case.** This stage records the gate the `/pr` stage cites, so
     `/pr` opens the pull request *after* this document is written. Record exactly
     `not yet opened — the /pr stage records it here once the PR exists`, and invent no number.
     `/pr` replaces that note with the real number as part of delivering, so the finished document
     always ends up naming the pull request that carries it.
   - Never guess, derive or back-fill a number from a branch name, a task id, a run id or another
     document. A wrong number is worse than an honest "not yet opened".

6. Populate `build-results.md` from the template:
   - Fill `{{TASK_ID}}`, `{{TASK_TITLE}}`, `{{BRANCH}}`, `{{DATE}}`, `{{SPEC_LIST}}`.
   - Fill the pull request line above `## Summary` with the reference resolved in step 5 — a real
     `#<number>` with its URL, or the not-yet-opened note. Never a placeholder.
   - **Summary:** purpose, key design decisions, roadmap placement, and scope (including what the
     task deliberately stops short of).
   - **Files Changed:** every file touched, with action (Created/Modified) and a one-line description.
   - **Verification Results:** the exact commands and their real outcomes (pass/fail, counts). Mark
     any command that could not run (missing credentials, no network, no deployment) as
     **unverified** with the reason — never as passing.
   - **Non-Goals (NOT implemented):** copied from the task prompt's explicit non-goals.
   - Delete optional template sections that do not apply; do not leave `{{placeholders}}` behind.
7. Run `git diff --check` and review the final diff for stale or invented content.

## Non-goals — do NOT do these

- Do **not** modify implementation code, tests, traceability artifacts, specs, or the roadmap.
- Do **not** commit, push, or open a PR (the `/pr` stage owns that).
- Do **not** write `player-actions.md` or `integration-tests.md` — the `show-updated-*` prompts own those.
- Do **not** record a result you did not observe. If a gate fails, record the failure and stop;
  do not fix it here.

## Done when

- `<implementation_results_dir>/<branch>/build-results.md` exists, follows the configured template
  (`paths.build_results_template`), and has no remaining placeholders.
- Every verification row reports a real outcome from this run, or is explicitly marked unverified
  with the reason.
- `git diff --check` passes and no code/test/traceability file was modified.

## Final response

Return: the document path, the exact gate commands with their real outcomes (pass/fail, counts),
and anything that could not be run and why. Mark an outcome you cited from `aidw gate` rather than
ran here with its origin (key, tree, stage, timestamp).
