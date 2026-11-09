---
description: Prove a change meets its acceptance criteria with focused automated checks (and a real browser for browser-facing work)
argument-hint: "<task, acceptance criteria, diff, branch, or flow>"
---

# Test — prove the implementation

Prove the behaviour that matters. A passing build or a source-code reading can support the proof, but neither proves a user-visible flow. This is the independent proof stage: it runs after `/impliment-task` and before `/update-traceability`.

## Scope

**Owned by this prompt:**

- Writing or updating the **unit/contract tests** that are missing to prove the acceptance criteria.
- Running the narrowest meaningful checks first, then wider checks for shared interfaces.
- Reporting every acceptance criterion, invariant, and affected failure path as `Pass`, `Fail`, or `Unverified` with evidence.

**Not owned — do not do these here:**

- **Implementation code.** A real defect is reported as `Fail`, never silently fixed here — fixing the code would make the proof test its own fix and lose its independence. Hand it back to `/impliment-task` (or a review follow-up).
- **Deployed integration tests.** The repo's own integration-test prompt owns those, when it supplies one (`aidw/prompts/` names it by filename); they require a deployed environment and live in whichever directory the repo's conventions reserve for them.
- **Traceability** — the traceability stage's artifacts and the roadmap checkbox: the `/update-traceability` stage.
- **The repo's full verification gate and the build-results document** (`paths.implementation_results_dir`) — the `/record-implementation-results` stage.

## Process

1. Read the task prompt (`paths.task_prompts_dir`/`<branch>-prompt.md`), its cited spec sections, the changed code, existing tests, the repo's root `AGENTS.md` and its `aidw/conventions.md`, and any cited conventions. Acceptance criteria come from the task prompt's `Done when` and `Tests` sections and from the cited `AC-n`/`INV-n` IDs. Preserve their wording — never rewrite criteria to match the code.
2. Map every acceptance criterion, cited invariant, and affected failure path to proof by ID. Test changed behaviour and behaviour a refactor must preserve.
3. If automated tests cannot exercise the affected behaviour, explain why and give other evidence.
4. **Add or update focused tests where proof is missing.** Put them where the repo's conventions say they belong (its `aidw/conventions.md`, its root `AGENTS.md`, or the layout its existing tests already use). Assertions must fail when the changed behaviour breaks. For a module the repo's property-test policy covers, keep the hand-calculated spec example and the pinned-`seed` property/metamorphic test the implementation stage wrote; add edge and fail-closed cases here rather than duplicating the example.
5. Assert behaviour a user or caller can observe unless the test targets a documented internal contract. Keep setup and assertions no more complex than the scenario.
6. Run the narrowest checks that exercise the changed behaviour and affected interfaces; run wider checks when shared behaviour or interfaces changed. The commands are the **repo's own**, taken by name from `aidw/conventions.md`, its root `AGENTS.md`, or the task prompt — never inlined here. Prefer the affected package(s); the repo's full verification gate is the next stage's job.
   Run each command through `aidw gate run <key> -- <command>`, with the gates named as
   `pr.md` names them and the same `--ignore` scope `pr.md` declares, so this run records the
   outcome against the tree it gated:
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
   and exits 0 without re-running — cite that line, with its origin, as evidence. A same-run,
   same-tree outcome is evidence, not a number copied from an earlier run. `--force` re-runs.
7. When browser-rendered behaviour changes, start the documented app and check the required flows and affected failures in a real browser.
   - Check desktop and mobile when layout or responsive styles changed.
   - Check keyboard use when interactions changed.
   - Check console errors and failed requests during every flow.
   - Capture evidence. Reading source is not browser proof.
8. Report each `AC-n`, `INV-n`, or task criterion as pass, fail, or unverified. Include the command, browser flow, or other evidence.

## Return

Report each criterion in this shape:

```text
Criterion: <ID or exact wording>
Result: Pass / Fail / Unverified
Evidence: <command, browser flow, or artifact>
Gap: <what remains unknown, or None>
```

Lead with failures and unverified criteria. Do not hide them below passing checks.

## Boundaries

- Do not weaken assertions to make a change pass.
- Do not modify implementation code or fix unrelated failures.
- Do not touch the traceability stage's artifacts, the roadmap checkbox, the results document, or the architecture docs.
- If required browser tooling is unavailable, report the check as blocked unless the user explicitly accepts a manual exception.
- Do not claim a command ran or a criterion passed unless you observed it. An `aidw gate run`
  `reused:` line is observed evidence — quote it with its origin rather than re-running the gate.

## Final response

State the criteria you proved, the tests you added or updated (with paths), the exact commands run and their real outcomes, and every criterion left `Fail` or `Unverified` with the reason. If a `Fail` is an implementation defect, say so explicitly so it is fixed in a separate, deliberate change.
