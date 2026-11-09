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
| Local proof against acceptance criteria, extra edge tests | the `/test` stage |
| Traceability: the traceability stage's artifacts and the roadmap checkbox | the `/update-traceability` stage |
| Build-results doc + the full verification gate | the `/record-implementation-results` stage |
| Architecture inventory + diagrams | the `/update-architecture` stage |
| Commit, push, open the PR | the `/pr` stage |

Do **none** of those here. Leave your changes **uncommitted** in the working tree and do not
open a PR. If a downstream activity seems necessary to finish the code, note it in your final
response instead of doing it.

## Instructions
Carefully follow all the instructions in `task-prompt-file` prompt.

### Branch setup

AIDT owns branch setup (EXTRACTION.md §3.2): `aidw implement` creates the task branch and its
worktree before any agent stage runs. Do not create, switch, or reset branches yourself — it
already ran the equivalent in Python.

### Before you build (verify the constraint, not just the instruction)

Task prompts are derived artifacts and can be wrong about the repo. Before changing a shared gate, set, checker, or schema:

- Run the repo's own pre-change checker for the gate, set, or schema you are about to widen (its `aidw/conventions.md`, root `AGENTS.md`, or the task prompt name it); if it reds on pre-existing entries, **stop and ask** rather than silently narrowing the instruction.
- Confirm the acceptance command can actually run the evidence — that every check it relies on is credential-free and resolves the references it cites.
- Leave a re-export shim for a relocated symbol and keep existing suites green.

If an instruction conflicts with the repo (a gate that would go red, a validator that cannot resolve the cited evidence, a field/schema that does not exist), **stop and ask** — do not silently follow or re-decide it. If you resolve it, flag the deviation in your final response so it reaches the PR body and the build-results doc. Traceability specifics live in the repo's traceability conventions (from its `AGENTS.md` / `aidw/conventions.md`).

### Implementation

- Read the cited spec sections and any task-specific docs first.
- Implement **only** this task. Do not begin the next roadmap task.
- Write the module's own contract tests **as you write the code**:
  - one hand-calculated spec example per behaviour path, plus purity (no input mutation, no undeclared I/O) and fail-closed checks;
  - the property or metamorphic test the repo's property-test policy requires for every new module it covers, with an explicit pinned `seed` + `numRuns`.
  These tests are the executable specification of the module and the evidence the traceability
  stage cites — they belong with the code, not in a separate stage.
- Run a **package-scoped smoke check** on the package(s) you touched, using the repo's own commands
  — taken by name from its `aidw/conventions.md`, its root `AGENTS.md`, or the task prompt, never
  inlined here:
  ```bash
  <the repo's package-scoped lint command>
  <the repo's package-scoped build command>
  <the repo's package-scoped test command>
  ```
  This is a fast sanity check, not the acceptance gate. The repo's full verification gate and the
  task-specific gates are run and recorded by `record-implementation-results.md`.
  Run each of these through `aidw gate run <key> -- <command>`, with the gates named as `pr.md`
  names them (`lint`, `build`, `suite`) and the same `--ignore` scope `pr.md` declares, so this run
  records the outcome against the tree it gated and a later stage cites it instead of re-running
  it:
  ```bash
  # The four configured write-targets of the other stages: read each resolved value from
  # `aidw config show` and pass it as one --ignore prefix.
  SCOPE="--ignore <implementation_results_dir> --ignore <architecture_dir> --ignore <roadmap_dir> --ignore <task_prompts_dir>"
  aidw gate run smoke $SCOPE -- <the repo's package-scoped test command>
  ```
  The scope declares what the command cannot read (the documents the other stages write); never
  ignore source, tests, config or lockfiles. Asking again for the same key, command and scope
  against content that differs only inside that scope prints
  `reused: gate '<key>' passed for tree <id> at <time> by stage '<stage>' (<summary>) [scope excludes: ...]`
  and exits 0 without re-running. A same-run, same-tree outcome is evidence, not a number copied
  from an earlier run; `--force` re-runs when you doubt it. If the task prompt names a wider
  acceptance command (the repo's full suite), run that one through `aidw gate run suite $SCOPE --
  <command>` too — that is the outcome the later stages reuse. Use `smoke` for a package-scoped
  check.
- **Do not edit** the traceability stage's artifacts, the roadmap checkbox in `paths.roadmap_dir`,
  or anything under `paths.implementation_results_dir`. Downstream prompts own those.
- If you find a traceability reference (code symbol or test name) that does not match the actual
  code, **flag it** for the traceability stage — do not fix it here.
- If the task adds or changes a public API action or an implemented spec claim, **flag it**
  for the traceability stage (it decides the traceability artifacts' impact) — do not touch them
  here.
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
2. **`## Verification (real outcomes)`** — the exact commands you ran and their
   real results (pass/fail, test counts). Never invent numbers. If a command could not run
   (missing credentials, no network), say so and why. Do not claim the repo's full verification
   gate ran.
   A command you ran through `aidw gate run` has a recorded outcome: quote its one-line outcome,
   and for a `reused:` citation give the origin (tree, stage, timestamp) instead of implying you
   ran it in this stage.
3. **`## Flagged for downstream stages`** — the traceability refs to add, the PR-body flags, and
   every ambiguity/deviation/pre-existing bug you found, plus what you did about it.

Rules for this message:

- Do not paste raw diffs or full test logs.
- Do not collapse it into vague prose ("tests pass", "changes made"). Every claim must be checkable.
- Do **not** commit, push, or open a PR. Do **not** write a results doc. State that the changes
  are uncommitted and which downstream prompt owns each remaining step.

## Results

None. This prompt does not write a results document. `record-implementation-results.md` owns
`<implementation_results_dir>/<branch>/build-results.md`.
