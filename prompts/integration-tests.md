# Build Integration Tests

Given a completed and deployed implementation task, write automated integration tests using the framework in `tests/integration/`. The tests verify real AWS endpoints — not mocks, not unit tests, not local stubs.

The **README** (`tests/integration/src/<task-id>/README.md`) is the canonical planning document. It describes what will be tested and why. There is no separate manual test plan — the README replaces it. Any step that genuinely cannot be automated (Hosted UI flows, MFA setup) goes into the README as a "Manual setup" or "Manual verification" section.

## Variables

`$1` — task-id (e.g. `03-A1`, `01-C6`).

## Instructions

- Read `docs/conventions/integration-testing.md` §11 ("Adding a new plan (checklist)") and §2-11 in full.
- Read `tests/integration/src/02.5-A2/README.md` and `tests/integration/src/02.5-A4/README.md` for the canonical README format. **Match this format exactly.**
- Read `tests/integration/src/shared/README.md` and `tests/integration/src/lib/README.md` so you understand the existing shared infrastructure.
- Read the task's **implementation prompt** at `docs/task-prompts/$1-prompt.md` — this tells you what was built and why.
- Read the relevant **spec sections** cited by the task — these define the contracts the tests must verify.
- Read `src/lib/config.ts`, `auth.ts`, `http.ts`, `aws.ts`, `jwt.ts`, `cognito.ts`, `resources.ts` — the shared helpers.
- Read `AGENTS.md` — language, tenancy, validation, and security conventions.

Create all files on the current branch. Do not open a PR unless asked.

---

## Prompt Format

Produce exactly the following when building integration tests for a task:

```
Read the following before starting, in full:

- `tests/integration/src/02.5-A2/README.md` — example README format (match this)
- `tests/integration/src/02.5-A4/README.md` — example README format (match this)
- `tests/integration/src/shared/README.md` — shared auth-boundary matrix
- `tests/integration/src/lib/README.md` — shared library modules
- `src/lib/config.ts`, `src/lib/auth.ts`, `src/lib/http.ts`, `src/lib/aws.ts`,
  `src/lib/jwt.ts`, `src/lib/cognito.ts`, `src/lib/resources.ts` — shared helpers
- `docs/conventions/integration-testing.md` — package conventions and checklist
- `docs/specs/<Design XX — Title>.md` — the spec section(s) the task implements
- `AGENTS.md` — project conventions

Task: Write automated integration tests for task **$1**, stored in
`tests/integration/src/$1/`. Follow exactly the patterns and conventions
already established by the 02.5-A2 and 02.5-A4 suites.
```

---

## Before writing code

1. **Plan the README first.** Before writing any test code, write the suite
   README (`tests/integration/src/$1/README.md`). This is the planning
   document — it forces you to identify every scenario, every expected
   result, and the "why" behind each test. Use the A2 and A4 READMEs as
   templates. The README must cover:

   - What the suite covers (one sentence at the top).
   - A section per test file with a table of tests:
     - What each test checks (the scenario or assertion).
     - Why it matters or what the expected result is.
   - Manual-only steps if any (e.g. Hosted UI flows, MFA setup) — clearly
     marked and sectioned off.
   - A "What this suite proves" section with checkmark bullet points.

2. **Decide what identity each suite needs.** See `src/fixtures/identities.ts`
   and `src/lib/auth.ts`:
   - Admin API / rules-engine tests → `auth.for('admin')` (or `'author'`,
     `'player'` depending on the test).
   - DynamoDB / Postgres / Cognito Admin API tests → AWS IAM credentials only
     (no JWT). The `getClient()` factory already handles profile + region.
   - If the task needs a new role not in the existing fixtures, add it to
     `identities.ts` and document it.

3. **Decide what endpoints are being tested.** Use `resolveConfig()` from
   `src/lib/config.ts` — it resolves `adminUrl`, `playerUrl`, `poolId`,
   `clientId` from CloudFormation stack outputs. Never hardcode URLs.

4. **Plan the suites.** Cover these categories, adapted to the task:
   - Smoke test (does the resource exist / is it reachable?)
   - Happy path (does the main functionality work?)
   - Error paths (malformed input, missing fields, authentication failures)
   - Observable (logs, monitoring — where applicable)
   - Each category becomes a `*.integration.test.ts` file.
   - If the task adds an API endpoint protected by the same Cognito
     authorizer as A2/A4, reuse `src/shared/auth-boundary.shared.ts`'s
     `runAuthBoundaryTests()` for the 401/403/200 matrix.

5. **Identify flaky tests.** Tests that are inherently time-sensitive (API
   Gateway throttling, cold-start latency, EventBridge rule propagation) must
   be marked with `describe.skip` unless `INTEGRATION_FLAKY=1`. Log
   actual measurements and use generous bounds.

---

## Requirements

1. **Create integration suites in `tests/integration/src/$1/`.**
   - Files must be named `*.integration.test.ts`.
   - Every suite starts with a header comment citing what it tests:
     `// Tests <what>: <scenario> → <expected result>.`
   - Use `resolveConfig()` for env, profile, region, endpoints.
   - Use `auth.for('admin' | 'author' | 'player')` for JWT tokens.
   - Use `httpPost(url, body, token?)` for all API Gateway calls.
   - Use `getClient()` for any direct AWS SDK calls.

2. **Assert exact results.**
   - Status code + response body, both exact.
   - For SRD lookups, assert against `@mythical-forge/shared-data` lookups
     rather than hardcoded values.
   - For engine results, assert the exact `{ result }` shape and values.
   - For infrastructure checks, use `ListFunctions`/`DescribeStacks` etc.
     but prefer verifying behaviour through the API.

3. **Wire resource cleanup.** Any suite that creates AWS resources must
   register them with `resources.track(type, id, cleanupFn)`. Cleanup runs
   automatically via Jest's `globalTeardown`.

4. **Handle missing infrastructure gracefully.** If a resource may not exist
   yet (e.g. CloudWatch log group created on first Lambda invocation), catch
   `ResourceNotFoundException` and skip with a warning rather than failing.

5. **Write the README.** `tests/integration/src/$1/README.md` must follow
   exactly the format established by the A2 and A4 READMEs:
   - One sentence saying what the suite covers.
   - The run command.
   - A section per suite file, with a table of tests (what each checks +
     why it matters or what it expects).
   - Manual-only steps if any, clearly marked.
   - A "What this suite proves" section with checkmark bullet points.

6. **Update `tests/integration/README.md`** to list the new task directory
   and its run command.

---

## Non-goals — do NOT do these in this task

- Do **not** write or update manual test plans (`manual-test-plans/`). The
  README in `tests/integration/src/$1/` is the canonical document.
- Do **not** modify `infra/` or any AWS resource — these are tests only.
- Do **not** change how `tests/integration/src/lib/` works — those are
  shared infrastructure. If a new helper is genuinely needed, add it but
  do not rearchitect existing ones.
- Do **not** change the jest config, tsconfig, or package.json unless the
  task explicitly requires a new dependency.
- Do **not** write unit tests (`*.test.ts` without `.integration.`) —
  those belong alongside the implementation, not in `tests/integration/`.
- Do **not** run against `staging` or `prod` — all integration tests use
  `AWS_ENV=dev` by default.

---

## Deliverables

- `tests/integration/src/$1/README.md` (README written **first**, matching A2/A4 format)
- `tests/integration/src/$1/<name>.integration.test.ts` (one or more suites)
- Updated `tests/integration/README.md` (new task listed)

---

## Done when

- `pnpm --filter @mythical-forge/integration-tests lint && build` passes.
- `pnpm integration:bootstrap` has been run (tokens cached).
- `pnpm integration -- --testPathPatterns=$1` passes against `dev`: every
  test green (or skipped with a documented reason — flaky tests, missing
  infrastructure, manual-only steps).
- The suite README matches the A2/A4 format and covers every test file.
- Manual-only steps are clearly identified in the README and not left as
  unexecuted test code.