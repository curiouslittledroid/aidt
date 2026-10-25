---
description: Summarise the integration tests added on the current branch into docs/implementation-results/<branch>/integration-tests.md
argument-hint: "[branch]"
---

# Show updated integration tests

You are documenting, for the branch currently checked out, which **integration tests** the new code adds or changes and **what use cases those tests cover**. This runs after an implementation session and **before the branch is merged**, so the full change set is reachable through `git diff main...HEAD` and the session context. Re-derive every claim from the repository: the session context may be stale or wrong, so verify against the actual test files and diff before writing a single line.

The output is one Markdown document at `docs/implementation-results/<branch>/integration-tests.md`. It complements — and must **not** duplicate — `docs/implementation-results/<branch>/build-results.md` (which reports build/verification results). This document describes *what the tests are and what they prove*.

## Variables

- `$1` (optional) — branch name override. Default: `git branch --show-current`.

## What counts as "integration testing"

Document these, in this order of importance:

1. **Deployed integration suites** — `tests/integration/src/**/*.integration.test.ts` (real AWS dev endpoints; no mocks).
2. **Seeded / API-level suites** — integration tests that run against a deployed route without a WebSocket (e.g. the rules-engine admin route).
3. **Fixtures that drive those suites** — `tests/integration/src/**/fixtures/*.json`, the fixture schema, and the fixture-seeding path in the Lambda.
4. **Vector-matrix coverage** — new/changed rows in `tests/integration/src/vector-matrix/vectors.ts` and any new `not_applicable` marker, plus the `docs/rules-coverage/catalog.json` `integrationTests[]` / `integration[]` refs that point at integration evidence.
5. **The suite README(s)** — `tests/integration/src/<task-id>/README.md`, which is the canonical planning document.

Unit tests co-located with source (`*.test.ts`) and handler tests are **not** integration tests. Mention them only in a short "Related unit/handler coverage" note if they are the only evidence for a behaviour, and label them clearly as not integration tests.

## Step 1 — Identify the branch and the change set

```bash
git branch --show-current
git merge-base main HEAD
git log --oneline main..HEAD
git diff --stat main...HEAD
```

- If the branch is `main`, stop: there is nothing branch-local to document.
- Read `docs/implementation-results/<branch>/build-results.md` if it exists — it names the task(s), the gates run, and the real outcomes. Use it as a map, but confirm against the diff.
- Read the task prompt(s) that produced the branch: `docs/task-prompts/<branch>-prompt.md` (and any other `docs/task-prompts/*-prompt.md` referenced by the branch commits).
- Read `docs/conventions/integration-testing.md` so the suite's placement and prerequisites are described correctly.

## Step 2 — Locate the new and changed tests

```bash
git diff --name-status main...HEAD -- tests/integration
git diff --name-status main...HEAD -- docs/rules-coverage/catalog.json
git diff --name-status main...HEAD -- docs/rules-coverage/report.md
```

Separate **added** files (`A`) from **modified** ones (`M`). For each added/modified test file, read it in full — do not infer coverage from the filename. For each fixture, read the `description` and the `expect` block; the fixture's own `description` is usually the clearest statement of the scenario.

Check whether the branch touches the vector matrix or the catalog, and whether it added or removed `not_applicable` markers. A claim left as `not_applicable` because the branch added no matrix-scoped action is itself worth recording.

## Step 3 — For each suite, establish what it covers and how to run it

For every added or changed suite, capture:

- **Path** — `tests/integration/src/<dir>/<file>.integration.test.ts`.
- **Type** — deployed wire suite / seeded API suite / fixture-driven / offline matrix. Label honestly.
- **What it exercises** — the real endpoint or route (e.g. the `PLAYER_INPUT` WebSocket turn loop, the rules-engine admin route).
- **Use cases covered** — one row per `describe`/`it` (or per fixture turn): the scenario, the assertion, and why it matters. Prefer the test's own name over a paraphrase.
- **Prerequisites** — deployed dev stack, `AWS_ENV=dev`, cached tokens (`pnpm integration:bootstrap`), a seeding env var (e.g. `T2_FIXTURE_SEEDING_ENABLED=true`), credentials/IAM, or none.
- **How to run** — the exact command, e.g. `pnpm integration -- --testPathPatterns=<dir>`.
- **Evidence it provides** — the SRD claim(s) or gate it backs (catalog `integrationTests[]` / `integration[]`, `vectors.ts` rows).
- **Status** — one of:
  - **Added and passing** — you ran it and observed it pass (give the real outcome).
  - **Added, not run** — say why (no credentials, no deployment, flaky-skip).
  - **Modified** — what changed and why.

## Step 4 — Write the document

Create `docs/implementation-results/<branch>/integration-tests.md` (create the directory if needed; do not touch `build-results.md`). Use this structure:

```markdown
# Integration Tests Added — <branch>

**Branch:** `<branch>`
**Date:** <YYYY-MM-DD>
**Base:** `main` (merge-base `<short-sha>`)
**Task(s):** <roadmap task ids from build-results / commits>
**Build results:** `docs/implementation-results/<branch>/build-results.md`

## Summary

<One short paragraph: how many suites/fixtures/vector rows were added or
changed, what area they cover, and whether they are runnable offline or need a
deployed dev stack. If the branch added no integration tests, say so plainly
and explain what evidence it added instead (unit/handler tests, matrix
markers).>

## New and changed suites

### `tests/integration/src/<dir>/<file>.integration.test.ts` — <one-line>

- **Type:** deployed wire suite / seeded API suite / fixture-driven / offline matrix
- **Exercises:** <endpoint or route>
- **Prerequisites:** <deployed dev stack / env vars / credentials / none>
- **Run:** `pnpm integration -- --testPathPatterns=<dir>`

| Test / fixture turn | Scenario | Assertion | Why it matters |
|---------------------|----------|-----------|----------------|
| `<test name>` | <scenario> | <exact assertion> | <claim/gate it backs> |

<One or two sentences of prose if the table needs context.>

### `tests/integration/src/<dir>/<file>.integration.test.ts` — <one-line>
…

## Fixtures added or changed

| Fixture | Action | Scenario it drives | Key expectations |
|---------|--------|--------------------|------------------|
| `tests/integration/src/<dir>/fixtures/<file>.json` | Added / Modified | <scenario> | <expected roll / HP / status / deltas> |

## Vector-matrix and catalog impact

- **`tests/integration/src/vector-matrix/vectors.ts`:** <new rows / new `not_applicable` markers / unchanged and why>.
- **`docs/rules-coverage/catalog.json`:** <claims whose `integration[]` / `integrationTests[]` refs changed>.
- If the branch added a matrix-scoped action or implemented claim, state whether a row was required and whether it was added; if the branch was out of matrix scope, state the reason.

## Coverage gaps

<!-- What these tests do NOT cover, and which follow-up owns it. This is the
     most useful part for a reviewer. -->

- ⚠️ <gap> — <why / which follow-up owns it> (<reference>)

## Verification and caveats

- **Tests run:** <the exact command(s) and the real outcome — pass/fail, counts.
  Never invent numbers.>
- **Not run:** <suites that require a deployed dev stack / credentials you did
  not have, and why>.
- **Flaky / skipped:** <any `describe.skip` gated on `INTEGRATION_FLAKY=1` or a
  missing resource, and the reason>.
- **Manual-only steps:** <steps that cannot be automated, if any>.
```

## Rules

- **Do not invent.** Every suite, test name, fixture, and command must be traceable to a real file. If you cannot cite it, mark it unverified.
- **Never report a test result you did not observe.** Give the real command and outcome; if you did not run a suite, say so and why. Do not copy counts from `build-results.md` without confirming they refer to these suites.
- **Do not edit tests, fixtures, specs, the vector matrix, the catalog, or the roadmap.** This prompt only writes the one document.
- **Do not duplicate `build-results.md`.** Link to it for gate/verification detail; this document describes test content and coverage.
- **Do not present unit/handler tests as integration tests.** Label the distinction explicitly.
- **Coverage gaps are required.** A suite document without a "what is not covered" section is incomplete.

## Done when

- `docs/implementation-results/<branch>/integration-tests.md` exists and follows the structure above.
- Every suite, fixture, and command cited exists in the repo, or is explicitly marked unverified.
- The document states which suites were actually run and with what real outcome, and which were not.
- The "Coverage gaps" section names what the new tests do not cover.
- No test, fixture, spec, matrix, catalog, or roadmap file was modified.

## Final response

Return the document path and a one-line summary of what it covers (or that the branch added no new integration tests and what evidence it added instead).
