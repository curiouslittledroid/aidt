---
description: Update the repo's traceability artefacts for a change
argument-hint: "[branch]"
---

# Update traceability

The implementation and its contract tests are complete on the current branch. This prompt owns
**only** the repo's traceability artefacts for the change — whatever this repo uses to prove that a
requirement is implemented and tested. This prompt does not write or change implementation code,
and it does not commit, push, or open a PR.

This is a focused stage so it can run as its own agent. It is mechanical but gate-touching, so
every edit must be validated against the repo's conventions and its checkers — never papered over.

## Variables

- `$1` (optional) — branch name override. Default: `git branch --show-current`.

## Owned artifacts (the only files this prompt may change)

| Artifact | What to update |
|---|---|
| The repo's traceability artefacts | The entries, statuses, references and generated views that cover the requirements this task implements — as its conventions define them |

The artefact set is the **target repo's**, named by its `aidw/conventions.md` and its root
`AGENTS.md`; it is not fixed here, and a repo with no traceability convention has nothing for this
stage to update. Do not invent an artefact, a status vocabulary or a generated file to have
something to change.

Do **not** touch implementation code, unit tests, integration suites, specs, the build-results
document (`paths.implementation_results_dir`), the architecture documents, or anything under
`paths.roadmap_dir`.

### The roadmap belongs to `/update-roadmap`

`paths.roadmap_dir` is owned **byte-exclusively** by the `/update-roadmap` stage. Never edit
anything under it: not this task's own checkbox, and not an entry's `Done when`, `Deliverable`,
`Tests` or `Notes`. That stage's postcondition allows exactly one `- [ ]` → `- [x]` substitution
on exactly one line, with every other byte of the file unchanged, so an edit made here cannot be
reconciled with it — it fails the run after every gate has already passed. A task entry is fixed
at authoring time, and a correction discovered mid-implementation belongs in the task prompt or
the repo's decision record, never in a roadmap entry.

When the roadmap is the only candidate traceability artefact this repo has, the correct outcome is
to report **None for traceability** (step 7). "None" is a valid result, never a licence to adopt
the roadmap as a traceability artefact.

## Instructions

1. Read the repo's root `AGENTS.md` and its optional `aidw/conventions.md`, and any traceability
   convention document they cite. Those sources own the artefact list, the status vocabulary, the
   checker commands and the evidence rules; this prompt does not restate them.
2. Determine the branch and the change set:
   ```bash
   git branch --show-current
   git merge-base main HEAD
   git log --oneline main..HEAD
   git diff --stat main...HEAD
   ```
3. Read the task prompt (`paths.task_prompts_dir`/`<branch>-prompt.md`) and the implementation's
   final response and diff to learn the exact symbols, actions and tests the task added. Every
   reference you record must resolve to something that exists — a real file, a real symbol, a real
   test name. Never record a reference you did not verify.
4. **Before changing any status or checked set, verify the effect against the current repo** with
   the repo's own checker, run as the conventions name it. If it already fails on pre-existing
   entries, **stop and ask** — do not silently narrow the requirement set or widen the checker.
   Name the extra coverage a widening pulls in, or leave the set alone.
5. Update the artefacts with **targeted, in-place edits**: preserve the file's existing formatting
   and ordering, and re-validate a structured file immediately after each edit. A whole-file
   re-serialise buries the real change in diff noise and is not acceptable.
6. Only change a status when the evidence justifies it, and state the reason where the repo records
   one. Recording a status the evidence does not support is the failure mode this stage exists to
   prevent — it is never a way to make a checker pass.
7. If this change is out of scope for an artefact the repo maintains, record that conclusion and
   its reason rather than silently omitting the entry. A repo with no traceability artefact at
   all — including one whose only candidate is the roadmap — reports **None for traceability**
   and stops there.
8. Run the repo's traceability checks and report their real outcomes. Run each through
   `aidw gate run <key> -- <command>`, with the gates named as `pr.md` names them and the same
   `--ignore` scope `pr.md` declares, so the outcome is recorded against the tree it gated and
   `/pr` can cite it instead of re-running it:
   ```bash
   aidw gate run <key> $SCOPE -- <the repo's traceability check command>
   ```
   A check that needs credentials, a deployed environment or another unavailable prerequisite is
   reported as not run — never as passing.

## Non-goals — do NOT do these

- Do **not** write or modify implementation code, unit tests, or integration suites.
- Do **not** commit, push, or open a PR (the `/pr` stage owns that).
- Do **not** write the build-results document (`paths.implementation_results_dir`) — the
  `/record-implementation-results` stage owns that.
- Do **not** edit specs, or any artefact entry unrelated to this task's requirements.
- Do **not** change a status to make a checker pass.
- Do **not** edit anything under `paths.roadmap_dir`, not even this task's own checkbox — the
  `/update-roadmap` stage owns that file byte-exclusively.

## Done when

- Every requirement this task implements cites real, resolvable evidence, or is explicitly
  documented as out of scope with its reason.
- The repo's traceability checks pass, or the reason they cannot run is stated.
- Superseded or duplicated entries this change replaces are removed rather than left contradicting
  the new ones.
- No implementation, test or results file was modified; no commit was made.

## Final response

Return: the artefacts changed (paths), the exact commands and their real outcomes, the scope
decision and its reason, and any requirement left unverified with the reason.
