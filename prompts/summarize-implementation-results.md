---
description: Distil the recorded build results into a human-readable summary.md beside them
argument-hint: "[branch]"
---

# Summarize implementation results

The implementation, its contract tests, the traceability updates, and the build-results
document are complete on the current branch. This prompt owns **only one file**: a
human-readable narrative summary written beside the build results under the repo's configured
results directory (`paths.implementation_results_dir`).

It runs immediately after the stage that wrote the build results, and that stage is the only
one that runs the repo's verification gate. This one reads what it recorded. It runs no gate,
re-runs no command, and changes nothing else.

## Variables

- `$1` (optional) — branch name override. Default: `git branch --show-current`.

## Owned artifact (the only file this prompt may write)

`<implementation_results_dir>/<branch>/summary.md`.

Do **not** modify implementation code, tests, specs, the roadmap, architecture docs, or the
build-results document itself.

## Inputs

1. `<implementation_results_dir>/<branch>/build-results.md` — read it **in full**. It is the
   single source of truth for every fact this summary states: what was built, what was
   deliberately left out, and every verification outcome. If it does not exist, **stop and
   report it**: a summary without recorded build results would be invention, not summary.
2. The task prompt at `paths.task_prompts_dir`/`<branch>-prompt.md` — for the problem the
   task solved, its scope, and its explicit non-goals.
3. The spec headings that task prompt cites — read them for purpose, scope and non-goals only,
   so the narrative is accurate about what the change is for. The build results remain the
   authority on what was actually done.

Read-only orienting commands are fine: `git branch --show-current`, reading the files above,
and listing the changed files. Do not execute anything that verifies, builds or tests the
repository.

## Instructions

Write `<implementation_results_dir>/<branch>/summary.md` in exactly these five sections, in
this order. The heading wording is yours; the order and the content of each section are not.

1. **The problem it was solving.** Why the change exists: what was broken, missing or
   ambiguous before it, and why that mattered. Take the problem statement from the task prompt
   and the recorded build results, not from your own reconstruction.
2. **The core idea.** The central change in a few sentences — the one decision that made the
   rest of the work follow. If there were competing options, say which was taken and why, as
   far as the recorded material states it.
3. **What was built, piece by piece.** Walk the delivered pieces in an order a reader can
   follow: for each, what it does, why it exists, and how it fits the pieces around it.
   Explain *why* and what changed — do **not** re-table the Files-Changed list.
4. **What it deliberately did not do.** The task's non-goals and deferred work, each with the
   reason it was left out, so a reader cannot mistake an omission for an oversight.
5. **Verification.** What was verified and how, honestly. Cite the gate outcomes the build
   results already record, in prose: what passed, what failed, and what could not be run.

Rules for the whole document:

- **Descriptive voice.** Write for a human who wants to understand the change, not for a
  reader comparing audit rows. Prose, not bullet-only tables.
- **Never re-run a verification gate or any other command.** The build results are the
  evidence; a gate you run here would be a second, unreviewed result and would double the most
  expensive step of the run for no new evidence.
- **No invented results.** Every verification claim comes from the build-results document. A
  "now passes", "later resolved" or "retried and fixed" claim it does not contain is a
  fabrication.
- **Preserve honesty.** A recorded failure stays a failure; an `unverified` row stays
  "unverified" with the reason the build results give. Never smooth, round a failure to a pass,
  or omit a bad row. Never describe a fix the build results do not record.
- **Stay within the docs.** Reference configuration by its `paths.*` key, never by a hardcoded
  directory that belongs to one repo.

## Non-goals — do NOT do these

- Do **not** touch implementation code, tests, specs, the roadmap, or architecture docs.
- Do **not** edit the build-results document; this prompt only reads it.
- Do **not** run or re-run a verification gate, a linter, a build or a test suite.
- Do **not** commit, push, or open a pull request (the delivery stage owns that).
- Do **not** backfill summaries for other tasks.

## Done when

- `<implementation_results_dir>/<branch>/summary.md` exists and contains the five sections
  above, in order, with no placeholder text.
- Every fact in it is traceable to the build results or the task prompt, and every verification
  statement matches what the build results record — failures and `unverified` rows included.
- No code, test, spec, roadmap, architecture or build-results file was modified.

## Final response

Return: the path written, a one-line description of each of the five sections, and any recorded
outcome you could not summarise without ambiguity (naming the build-results row).
