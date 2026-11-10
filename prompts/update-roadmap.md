---
description: Flip the one roadmap checkbox for this task and change nothing else
argument-hint: "[roadmap-file] [task-id]"
---

# Update the roadmap entry

The implementation, its tests and the recorded results are complete on the current branch. This
prompt owns **exactly one edit**: the checkbox for this task in this task's roadmap file. It does
not write or change implementation code, tests, specs or any other document, and it does not
commit, push, or open a PR.

## Variables

- `$1` — the absolute path of the roadmap file that carries this task's entry.
- `$2` — the task id as the roadmap writes it, without the phase prefix (e.g. `H3.1`).

The file is given to you; never guess it and never look for a directory of your own. The task id is
the roadmap's own id, not the branch name: the branch is `<phase>-<task>`, the checkbox is `<task>`.

## Instructions

1. Read `$1` in full.
2. Find **the one** checkbox line whose bold task id is exactly `$2` — the shape is
   `- [ ] **$2. <title>** <details>`. If no line matches, or more than one does, stop and report
   it: an ambiguous tick is a refusal, never a guess.
3. If that line already reads `- [x]`, change **nothing**. Report `already [x], file unchanged` and
   stop.
4. Otherwise change only the checkbox on that one line, from `- [ ]` to `- [x]`. Preserve every
   other character of the line — the title, the details, the spacing, the trailing newline — and
   do not touch any other line, including its neighbours and any heading.
5. Change no other file. Do not reflow, reformat, sort or re-serialise the document.

## Rules

- One file, one line, one checkbox character. Any other edit fails the run's postcondition: the
  workflow re-reads the file and requires every other byte to be identical.
- The tick is a completion claim, so the one legal edit is what this stage exists for; do not
  weaken it into "the tick looks present" and do not edit around a missing or duplicated entry.
- Leave the change **uncommitted**; the `/pr` stage owns the commit.
- Do **not** modify implementation code, tests, integration suites, specs, the build-results
  document, the architecture documents, or any other roadmap entry.
- Do **not** commit, push, or open a PR.

## Done when

- The `$2` entry in `$1` reads `- [x]`, or it already did and the file is byte-identical.
- No other line or file was modified; no commit was made.

## Final response

Return: the file path, whether you flipped the checkbox or found it already ticked, and any
refusal with its reason.
