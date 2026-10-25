---
name: implement-srd-followup
description: Implement one approved SRD mapping follow-up task on a dedicated branch, with regression tests, catalog updates, and verification.
argument-hint: "<mapping-task-path> <claim-id> [approved]"
---

# Implement an SRD Mapping Follow-up Task

Use this prompt to implement one approved follow-up task created by the SRD mapping workflow.

This prompt is for implementation, not for discovering or redefining the rule. The nominated follow-up task must already exist in an SRD mapping task document or be explicitly provided by the user.

## Invocation inputs

When invoked as a pi prompt template, pass these positional arguments:

- Mapping task document: `$1`
- Follow-up claim ID: `$2`
- Implementation authorization: `${3:-approved}`

The resolved assignment is:

```text
Mapping task document: $1
Follow-up claim ID: $2
Implementation authorization: ${3:-approved}
```

If either `$1` or `$2` is missing, stop and ask the user to invoke the template with the required parameters. Do not guess the task document or claim ID.

Example values:

```text
Mapping task document: docs/srd-analysis/srd-mapping/tasks/combat-attack-roll.md
Follow-up claim ID: srd35.combat.attack_roll.natural_1_misses
Implementation authorization: approved
```

## Instructions

You are implementing one approved SRD rules-engine follow-up task in the Mythical Forge repository.

Before making any file edits, create a dedicated Git branch from `main`.

1. Inspect the current branch and working tree:

   ```bash
   git branch --show-current
   git status --short
   ```

2. If the current branch is not `main`, stop and ask the user to return the session to `main`. Do not create the implementation branch and do not edit any files.

3. If the working tree contains unrelated uncommitted changes, stop and ask the user to clean or explicitly account for them. Do not carry unrelated changes into the implementation branch.

4. Derive a branch name from the claim ID using lowercase kebab-case. Use this format:

   ```text
   srd-followup/<claim-id-with-dots-replaced-by-hyphens>
   ```

   For example:

   ```text
   srd-followup/srd35-combat-attack-roll-natural-1-misses
   ```

5. Create and switch to the branch from `main`:

   ```bash
   git switch -c srd-followup/<claim-id-with-dots-replaced-by-hyphens> main
   git branch --show-current
   ```

   Verify that the reported branch is exactly the branch created. If that branch already exists, do not silently choose another name. Verify that it is based on `main`, then stop and ask whether it should be reused.

6. Only after the branch has been created and verified may you edit the task document, source code, tests, catalog, or any other file.

7. Read `AGENTS.md` in full.

8. Read these mapping documents in full enough to follow their requirements:

   - `docs/srd-analysis/srd-mapping/WORKFLOW.md`
   - `docs/srd-analysis/srd-mapping/SRD-mapping.md`
   - the nominated mapping task document
   - the relevant section of `docs/srd-analysis/srd-mapping/action-plan.md`, when applicable

4. Read the complete SRD source section identified by the claim, including relevant tables, footnotes, exceptions, and cross-references. Use `docs/rules-coverage/source-index.json` to locate the section.

5. Read the rules-engine specification cited by the mapping task, normally the relevant section of:

   - `docs/specs/Design 06 - Combat.md`
   - `docs/specs/Design 09 - Game Rules Engines.md`
   - `docs/specs/Design 09.1 - Alternative Rule Sets.md`

   Also read `docs/specs/Design 21 - Monorepo Layout.md` when adding files or changing package structure.

6. Read the complete existing implementation files and tests named by the mapping task. Search for related callers, public interfaces, exports, and data types before deciding where the fix belongs.

## Approval and ambiguity gates

Do not start implementation if the nominated claim is missing, ambiguous, or not explicitly approved.

Stop and ask for human clarification if implementation would require deciding any of the following:

- an interpretation not already settled in the mapping task or project specification;
- an SRD versus project-spec conflict;
- a change to a public rules-engine interface;
- a schema or stored-data change;
- a new action primitive or resolution contract;
- a change in MVP, phase, deferred, or excluded scope;
- a new cross-domain ownership boundary;
- behavior that the mapping task records as blocked or unresolved.

Do not silently resolve ambiguity. Record the question, relevant evidence, and the decision needed.

## Implementation procedure

### 1. Confirm the exact acceptance criteria

Read the selected follow-up task and extract:

- claim ID;
- source section ID;
- required behavior;
- affected module;
- required tests;
- scope;
- explicit non-goals;
- acceptance criteria.

Do not expand the task to implement other gaps from the same SRD section unless the user explicitly authorizes that expansion.

### 2. Confirm the current catalog state

Read the claim in:

```text
docs/rules-coverage/catalog.json
```

The claim should normally be `not_started`, `partial`, `implemented_unverified`, or another status indicating that implementation is still required.

Do not mark the claim complete before the code and tests pass.

Do not manually edit these generated files:

```text
docs/rules-coverage/source-index.json
docs/rules-coverage/report.md
```

The SRD source index is maintained separately and only regenerated when the SRD source changes.

### 3. Design the smallest correct change

Prefer the smallest implementation that satisfies the approved claim and preserves the existing module boundary.

Before coding, determine:

- whether the existing function already owns the behavior;
- whether the behavior belongs in a new pure helper;
- whether the public `IRulesEngine` interface must change;
- whether callers must change;
- whether reference data is needed;
- whether the result shape already contains the evidence required by callers and the narrator.

Do not move deterministic mechanics into an LLM prompt or narrator.

Do not add speculative abstractions for future SRD rules. If the approved task exposes a missing architecture boundary, stop and ask rather than inventing one.

### 4. Add regression tests first or alongside the fix

Add tests that directly prove the SRD claim. Include the relevant boundary and exception cases from the mapping task.

For example, a natural-1 attack-roll fix should include a case where the attack would otherwise exceed AC:

```typescript
it('natural 1 always misses regardless of attack modifier', () => {
  const result = resolveAttackRoll(
    {
      baseAttackBonus: 20,
      abilityModifier: 10,
      sizeModifier: 0,
      miscModifiers: 0,
    },
    10,
    20,
    () => 1,
  );

  expect(result.isHit).toBe(false);
  expect(result.isThreat).toBe(false);
  expect(result.outcome).toBe('MISS');
});
```

Do not weaken an existing test to make the implementation pass. Do not mark a claim implemented when the test only covers an adjacent behavior.

### 5. Implement deterministic behavior

Implement the approved rule in TypeScript, following the repository conventions:

- pure functions where the module is pure;
- injected dice rollers for nondeterministic rolls;
- no I/O in the rules engine;
- no mutation of input state;
- explicit typed results;
- Zod validation only at the appropriate boundary;
- no LLM calculations;
- no hidden fallback behavior.

Preserve existing behavior unless the approved SRD claim specifically requires correcting it.

### 6. Update exports and interfaces only when required

If the task requires a new module or public symbol:

- place it according to Design 21;
- update the relevant package exports;
- update `IRulesEngine` and `D20RulesEngine` only when the approved task requires public access;
- add focused interface/delegation tests;
- do not add alternative rulesets or unrelated engine methods.

Use pnpm, `workspace:*` for internal dependencies, and `catalog:` for shared external dependencies.

### 7. Run focused verification

Run the narrowest relevant test first. For example:

```bash
pnpm --filter @mythical-forge/rules-engine test -- \
  --runInBand services/rules-engine/src/combat/__tests__/attack.test.ts
```

Then run the complete relevant package checks:

```bash
pnpm --filter @mythical-forge/rules-engine lint
pnpm --filter @mythical-forge/rules-engine build
pnpm --filter @mythical-forge/rules-engine test
```

Use the actual package and test path for the nominated task.

### 8. Update the mapping record

After implementation and tests pass:

1. Update the follow-up checklist in the mapping task document.
2. Add or correct code and test references for the claim in `docs/rules-coverage/catalog.json`.
3. Change the claim status to `implemented` only if:
   - the scoped behavior is complete;
   - the code reference exists;
   - the tests genuinely prove it;
   - no unresolved interpretation or implementation gap remains.
4. Leave the claim `partial`, `implemented_unverified`, or `blocked` if any of those conditions is not met.
5. Record the implementation decision and any remaining limitations in the task document.

If the implementation reveals that the claim was incorrectly scoped or that another design decision is needed, stop at the boundary, preserve the honest status, and record a follow-up question instead of rewriting the task silently.

### 9. Validate the mapping system and regenerate the report

Run:

```bash
pnpm srd:validate
pnpm srd:check-references
pnpm srd:report
```

Review:

```text
docs/rules-coverage/report.md
```

Confirm that the claim appears with the correct status, source section, implementation reference, and test reference.

### 10. Record actual verification evidence

Update the mapping task's verification section with the actual commands and outcomes. Do not invent test counts or claim success for commands that were not run.

Run `git diff --check` and inspect the final diff:

```bash
git diff --check
git diff --stat
git status --short
```

## Explicit non-goals

Do not do any of the following unless the user explicitly expands the task:

- audit or implement unrelated SRD claims;
- implement the whole nominated SRD section;
- change the SRD source files;
- regenerate the source index when the SRD source has not changed;
- edit generated `source-index.json` or `report.md` by hand;
- introduce alternative rulesets;
- add LLM-based rule evaluation;
- add persistence or AWS resources to the rules engine;
- change public schemas or stored data without an approved design;
- implement deferred roadmap work merely because it is adjacent;
- weaken or delete tests to preserve existing behavior;
- hide an intentional SRD deviation.

## Branch and final-state checks

Before finishing:

```bash
git branch --show-current
git status --short
git diff --check
git diff --stat
```

Confirm that all implementation changes are on the dedicated `srd-followup/<claim-id>` branch and that no files were edited on `main`. Do not merge the branch. Do not push or open a pull request unless the user separately requests it.

## Completion criteria

The implementation task is complete only when:

- the approved claim and acceptance criteria are satisfied;
- the correct deterministic module owns the behavior;
- regression and boundary tests pass;
- existing relevant tests still pass;
- package lint and build pass when applicable;
- catalog and code-reference validation pass;
- the catalog has accurate code and test references;
- the mapping task records the resulting status and verification evidence;
- the generated report has been regenerated and reviewed;
- remaining gaps or decisions are recorded as follow-up work;
- `git diff --check` passes.

## Final response

Finish with a concise implementation report containing:

- claim implemented;
- files changed;
- behavior added or corrected;
- tests added or updated;
- catalog and task-document updates;
- commands run and their actual results;
- remaining gaps or human decisions required.
