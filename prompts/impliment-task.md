# Impliment a task prompt

## Variables

task-prompt-file: $1

## Scope of this prompt — code and its contract tests only

This prompt implements **code and the module's own contract/property tests**. It deliberately
stops before the activities that downstream prompts own, so each SDLC stage stays focused and
can run as its own agent:

| Activity | Owned by |
|---|---|
| Code + module contract/property tests | **this prompt** (`impliment-task.md`) |
| Local proof against acceptance criteria, extra edge tests | `/test` prompt (workflow Step 3, `aidt/prompts/test.md`) |
| Traceability: `catalog.json`, `vectors.ts`, `report.md`, roadmap checkbox | `aidt/prompts/update-traceability.md` |
| Build-results doc + the full verification gate | `aidt/prompts/record-implementation-results.md` |
| Architecture inventory + diagrams | `aidt/prompts/update-architecture.md` |
| Commit, push, open the PR | `aidt/prompts/pr.md` |

Do **none** of those here. Leave your changes **uncommitted** in the working tree and do not
open a PR. If a downstream activity seems necessary to finish the code, note it in your final
response instead of doing it.

## Instructions
Carefully follow all the instructions in `task-prompt-file` prompt.

### Branch setup (do this first, before any code)

The task will specify a branch name (e.g. `3-D3`). Before creating or resetting anything:

1. Check if the branch already exists locally: `git branch --list <branch-name>`
2. Check if it exists on the remote: `git ls-remote --heads origin <branch-name>`
3. **If the branch exists locally and has commits not on `main` (`git log <branch> --not main`):**
   - Inspect what's there (`git diff --stat main...<branch>`).
   - Those commits represent prior work (docs, specs, partial implementation). **Do not `git reset --hard`** — you would destroy that work.
   - If the branch is just docs/specs/task-prompts (no implementation code), check it out and continue from where it left off, keeping those files.
   - If the branch already has implementation code that conflicts with the task, **stop and ask** before overwriting anything.
4. **If the branch does not exist:** create it fresh from `main` (`git checkout -b <branch-name>`).
5. Verify with `git branch --show-current`.

### Before you build (verify the constraint, not just the instruction)

Task prompts are derived artifacts and can be wrong about the repo. Before changing a shared gate, set, checker, or schema:

- Run `pnpm srd:matrix-check --statuses <set>` before widening a gate/set; if it reds on pre-existing entries, **stop and ask** rather than silently narrowing the instruction.
- Confirm the acceptance command can run the evidence (`pnpm srd:check-tests` is credential-free and only owns `services/`/`packages/` refs).
- Leave a re-export shim for a relocated symbol and keep existing suites green.

If an instruction conflicts with the repo (a gate that would go red, a validator that cannot resolve the cited evidence, a field/schema that does not exist), **stop and ask** — do not silently follow or re-decide it. If you resolve it, flag the deviation in your final response so it reaches the PR body and the build-results doc. Traceability specifics live in `docs/conventions/srd-traceability.md`.

### Implementation

- Read the cited spec sections and any task-specific docs first.
- Implement **only** this task. Do not begin the next roadmap task.
- Write the module's own contract tests **as you write the code**:
  - one hand-calculated SRD/spec vector per behaviour path, plus purity (no input mutation, no undeclared I/O) and fail-closed checks;
  - the property or metamorphic test required by `AGENTS.md` §6 for every new rules-engine module, with an explicit pinned `seed` + `numRuns`.
  These tests are the executable specification of the module and the evidence the traceability
  stage cites — they belong with the code, not in a separate stage.
- Run a **package-scoped smoke check** on the package(s) you touched, e.g.:
  ```bash
  pnpm --filter @mythical-forge/<pkg> lint
  pnpm --filter @mythical-forge/<pkg> build
  pnpm --filter @mythical-forge/<pkg> test
  ```
  This is a fast sanity check, not the acceptance gate. The full `pnpm -r` matrix and the
  task-specific gates are run and recorded by `record-implementation-results.md`.
- **Do not edit** `docs/rules-coverage/catalog.json`, `docs/rules-coverage/report.md`,
  `tests/integration/src/vector-matrix/vectors.ts`, the roadmap checkbox in `docs/tasks/`, or
  `docs/implementation-results/**`. Downstream prompts own those.
- If you find a catalog/spec reference (code symbol or test name) that does not match the actual
  code, **flag it** for the traceability stage — do not fix it here.
- If the task adds or changes a Rules Engine API action or an implemented SRD claim, **flag it**
  for the traceability stage (it decides the vector-matrix impact) — do not touch the matrix here.
- If anything in the task prompt is ambiguous or underspecified — especially security, cost,
  schema, or hard-to-reverse changes — or conflicts with the current repo/gate/checker state,
  stop and ask rather than guessing.

### Handoff (what downstream stages need from you)

Leave the working tree coherent (no half-applied edits) and record in your final response:

- the files created/modified, with paths;
- the exact symbols/actions/tests the task added — the traceability stage must reference them;
- the acceptance criteria you proved and any you did not;
- anything flagged for review, and any deviation from the task prompt.

## Final response format (mandatory)

Your final chat message is what the next stage reads before continuing. End with these three
sections, in this order and under these exact headings:

1. **`## What I built`** — 2–6 bullets on the delivered code and contract tests, naming real file
   paths. Call out any deviation from the task prompt explicitly, and what you chose instead.
2. **`## Verification (real outcomes)`** — the exact package-scoped commands you ran and their
   real results (pass/fail, test counts). Never invent numbers. If a command could not run
   (missing credentials, no network), say so and why. Do not claim the full `pnpm -r` gate ran.
3. **`## Flagged for downstream stages`** — the traceability refs to add, the PR-body flags, and
   every ambiguity/deviation/pre-existing bug you found, plus what you did about it.

Rules for this message:

- Do not paste raw diffs or full test logs.
- Do not collapse it into vague prose ("tests pass", "changes made"). Every claim must be checkable.
- Do **not** commit, push, or open a PR. Do **not** write a results doc. State that the changes
  are uncommitted and which downstream prompt owns each remaining step.

## Results

None. This prompt does not write a results document. `record-implementation-results.md` owns
`docs/implementation-results/<branch>/build-results.md`.
