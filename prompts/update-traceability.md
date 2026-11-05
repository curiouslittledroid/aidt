---
destination: mythical-forge/aidw/prompts/
description: Update SRD traceability (catalog, vector matrix, report, roadmap checkbox) for the current branch
argument-hint: "[branch]"
---

# Update SRD traceability

The implementation and its contract tests are complete on the current branch. This prompt owns
**only the traceability artifacts** for the change: the SRD claim catalog, the vector matrix, the
generated report, and the roadmap checkbox. It does not write or change implementation code, and
it does not commit, push, or open a PR.

This is a focused SDLC stage so it can run as its own agent. It is mechanical but gate-touching,
so every edit must be validated against the conventions and the checkers — never papered over.

## Variables

- `$1` (optional) — branch name override. Default: `git branch --show-current`.

## Owned artifacts (the only files this prompt may change)

| Artifact | What to update |
|---|---|
| `docs/rules-coverage/catalog.json` | Claim `status`, `implementation.integration[]`, `implementation.integrationTests[]`, `implementation.tests[]`, and `notes` for the claims this task implements |
| `docs/rules-coverage/report.md` | Regenerate via `pnpm srd:report` — never hand-edit |
| `tests/integration/src/vector-matrix/vectors.ts` | Add an independently hand-calculated row per new/changed Rules Engine API action or implemented claim in matrix scope; add/adjust `not_applicable` markers where a claim is out of scope |
| `tests/integration/src/02.5-B/**` | Remove vector assertions superseded by a new matrix row |
| `docs/tasks/<phase> - <name>.md` | Flip the one roadmap checkbox for the task id from `- [ ]` to `- [x]` |

Do **not** touch implementation code, unit/handler tests, integration suites under
`tests/integration/src/<task-id>/`, specs, or `docs/implementation-results/**`.

## Instructions

1. Read `docs/conventions/srd-traceability.md` in full, then `AGENTS.md` §6.
2. Determine the branch and the change set:
   ```bash
   git branch --show-current
   git merge-base main HEAD
   git log --oneline main..HEAD
   git diff --stat main...HEAD
   ```
3. Read the task prompt (`docs/task-prompts/<branch>-prompt.md`) and the implementation's
   final response / diff to learn the exact symbols, actions, and tests the task added. The
   catalog must cite real code and test names, resolved by `pnpm srd:check-tests` (which owns
   `services/`/`packages/` refs; `tests/integration/…` refs need `--jest-json`).
4. **Before changing any status or gate set**, verify the effect against the current repo:
   ```bash
   pnpm srd:matrix-check --statuses <set>
   ```
   If it reds on pre-existing entries, **stop and ask** — do not silently narrow the set or
   widen the gate. Name the extra coverage the widening pulls in, or leave the set alone.
5. Update `catalog.json`:
   - Add/refresh `implementation.integration[]` (`{ file, symbol }`) and
     `implementation.integrationTests[]` (`{ file, name }`) — these are **separate** fields; never
     conflate code refs with test refs.
   - Only change a claim's `status` when the evidence justifies it (`implemented` / `wired` /
     `integrated` per the vocabulary in the convention). State the reason in `notes`.
   - Edit the committed file **in place** (targeted edits, never a whole-file re-serialise) and
     validate the JSON immediately after each edit.
6. Update the vector matrix:
   - For each new/changed API action or implemented claim in matrix scope, add an independently
     hand-calculated row (seed only for seedable actions).
   - Remove any superseded duplicate vector assertion from `02.5-B`.
   - If the change is not eligible for matrix coverage, record the reason explicitly (in the
     catalog `notes` and your final response) rather than silently omitting it.
7. Regenerate the report: `pnpm srd:report`. Do not hand-edit `report.md`.
8. Flip the roadmap checkbox for this task id (`- [ ]` → `- [x]`), and only that one. If the item
   is already checked or no unchecked entry matches the task id, leave the file alone and say so.
9. Run the offline gates and report the real outcomes:
   ```bash
   pnpm srd:validate
   pnpm srd:check-references
   pnpm srd:matrix-check
   pnpm srd:report
   ```
   Run the matrix completeness test too. The deployed vector-matrix suite
   (`pnpm integration -- --testPathPatterns=vector-matrix`) runs only when the deployed dev
   prerequisites are available — if it cannot run, say so and do not treat the matrix as verified.

## Non-goals — do NOT do these

- Do **not** write or modify implementation code, unit tests, or integration suites.
- Do **not** commit, push, or open a PR (`aidt/prompts/pr.md` owns that).
- Do **not** write `docs/implementation-results/**` (`record-implementation-results.md` owns that).
- Do **not** edit specs, or any catalog field unrelated to this task's claims.
- Do **not** change a claim's `status` to make a gate pass — that is the failure mode this
  convention exists to prevent.

## Done when

- Every claim this task implements cites real, resolvable `integration[]` / `integrationTests[]`
  refs, or is explicitly documented as out of scope.
- `pnpm srd:validate`, `pnpm srd:check-references`, `pnpm srd:matrix-check`, and the matrix
  completeness test pass (or the reason they cannot run is stated).
- The vector matrix has a row for every in-scope action/claim, and superseded duplicates are gone.
- The roadmap checkbox for this task id is flipped (or the reason it was not is stated).
- No implementation, test, or results file was modified; no commit was made.

## Final response

Return: the artifacts changed (paths), the exact gate commands and their real outcomes, the
matrix-impact decision and its reason, and any claim left unverified with the reason.
