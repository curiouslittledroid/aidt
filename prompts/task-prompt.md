# Create a task prompt

The task files in the ./docs/tasks folder (`01 - Foundation.md` through `09 - Frontend.md`) are **planning indexes**, not agent prompts. Each entry is deliberately terse — one line of context, one spec citation, one done-condition — so the roadmap itself stays scannable and doesn't drift out of sync with 100+ fully-written prompts.

Generated prompts must stay lean for the same reason: the implementer (via `aidt/prompts/impliment-task.md`) reads the specs and the repo itself. The prompt's job is scope + traps + acceptance — not transcription.

## Variables

phase: $1
epic: $2
task: $3

## Instructions
AIDT owns branch setup (EXTRACTION.md §3.2): `aidw prompt` creates the task branch and its worktree before this stage runs. Do not create, switch, or reset branches yourself — write the prompt file and return its path; AIDT commits the reviewed prompt.

- Feasibility check before writing the prompt file: read the roadmap entry and every spec section it cites, and check whether what the task depends on exists. When authoring cannot proceed, output `blocked: <reason>` as the first line of your final message and change nothing — no prompt file, no other edits.
- Report `blocked: <reason>` for any of these reasons: a cited spec section is missing or contradicts the roadmap entry; a prerequisite the entry depends on cannot be found (not merged and no branch carrying it); an acceptance condition cannot be made executable without inventing a contract the cited sources do not fix. A `blocked:` line with an empty reason is still a blocked report.
- Read the roadmap document for the phase. It is `./docs/tasks/{phase} - *.md` — the file whose name begins with `{phase} - ` and whose title matches the task's phase (for example `./docs/tasks/03 - Single-Player Loop.md`, or `./docs/tasks/03.1 - Developer Play Tool & Scenario Registry.md` for sub-phase `03.1`). Expand Phase {phase} Epic {epic} task {task} into a full prompt using the `Prompt Format`. Store this prompt in the `docs/task-prompts` folder.
- Replace every <placeholder> in the `Prompt Format` with specific implementation details.
- Obey the `Conciseness budget` below. If the draft exceeds it, cut pasted content first (schemas, code, static data, test scripts) and replace with pointers — never cut traps, non-goals, or Done-when checks.
- Do not invent a material interface the cited spec omits. If a schema field, keying convention, failure contract, or signature this task must implement is not fixed by the spec, stop and report it as a spec gap and update the spec first. A prompt-fixed decision is only acceptable when it is explicitly labelled as such, with its rationale, and the ambiguity is named in the ask-if-ambiguous clause.
- IMPORTANT: When you finish writing the task prompt, return exclusively the path to the prompt file created — or, when blocked, `blocked: <reason>` — and nothing else.

## Conciseness budget (mandatory)

- Target: **80–120 lines, <15KB**. Larger tasks may reach ~150 lines; beyond that, stop and cut.
- **Cite, don't paste.** Never paste code, schemas, Zod definitions, or type unions longer than ~15 lines. Reference them as `Design XX §Y` + `path/to/file.ts:Symbol` and let the implementer read the source.
- **No repo snapshots.** Describe starting state with file+symbol pointers (e.g. "follows `combatExecutor.ts:executeCombat` pattern"), not pasted contents. The implementer has `read`/`bash`.
- **No stale-prone pins.** Never hard-code line numbers, test-file line refs, current counts that drift with ordinary work (action-list sizes, claim totals), or pasted static-data values. Write "recount and update the size/title assertion" instead. A spec- or roadmap-mandated minimum is different: state the required floor (for example "at least three archetypes") when the authoritative source sets it as an acceptance condition.
- **No wrapper duplication.** Branch setup and the implementation belong to `aidt/prompts/impliment-task.md`. The full `pnpm install / -r lint / -r build / -r test` matrix and the results doc belong to `aidt/prompts/record-implementation-results.md`. `srd:validate / check-references / report`, the catalog/vector-matrix edits, and the roadmap checkbox belong to `aidt/prompts/update-traceability.md`. Commit/push/PR belong to `aidt/prompts/pr.md`. The task prompt lists only *task-specific* verification. One narrow exception: when the task adds a new workspace dependency, package boundary, or bundling path, Done when may name the single `build`/`lint` command that proves that wiring (`pnpm --filter <pkg> build`) — never the full matrix.
- If in doubt, cut context — keep traps.

## Prompt Format

```
Read the following spec sections before starting, in full:
- <Design XX §Y — Section Title>
  Located at: docs/specs/Design XX - <Full Filename>.md
- <repeat for every spec section the task cites — usually 1-2, occasionally more>
- Design 21 — Monorepo Layout
  Located at: docs/specs/Design 21 - Monorepo Layout.md

Task: <the task's one-line description, copied from the roadmap file>

Requirements:
1. <One behaviour per item, derived from what the cited spec actually says,
   not invented. Name exact field/threshold/signature by reference
   (e.g. "per Design 09 §5.2: pure, diceRoller injected"), don't paste the
   definition. If the spec gives a snippet, say "match Design XX §Y <symbol>"
   and stop.>
2. <... — keep to the behaviours this task owns; 5–9 items max>
   <If this task changes a checker, status vocabulary, catalog reference, or CI gate,
   add a one-line "Gate impact:" naming the checker and the pre-existing entries it
   affects, and confirm against the current repo that the gate stays green.>

Traps / prior review findings (max 5–7 bullets, 1–2 lines each):
- <What the implementer will get wrong if unwarned + why, with a
  file/symbol pointer. E.g. "skill vs combat resolveAidAnother name
  collision — import from ../skills/skillCheck, not ../combat/attack.">

Explicit non-goals — do NOT do these in this task:
- <Name the next task(s) in the same epic, or an obviously-adjacent task in
  another epic, and say explicitly "that's a separate task, don't start it
  here.">
- <Name any deferred/out-of-scope spec item this task's area touches (e.g.
  Tier 2 multi-region, alternative rule sets, Phase 2 AFK auto-play) if
  there's a real risk of scope creep into it.>

Deliverables:
- <File paths only, one per line. No contents.>
- <e.g. services/rules-engine/src/combat/encounterInit.ts>

Tests (what to prove, not the literal expects):
- <One hand-calculated vector per behaviour path, plus purity/fail-closed
  checks. Say what to assert and which file to put it in; don't dictate
  stub sequences or exact error strings.>

Done when:
- <Roadmap's "Done when" line made executable: 3–6 task-specific checks
  (a test file passing, a router call working end-to-end, a frame
  asserting). No per-package build/lint/test matrix — `record-implementation-results.md` owns the full gate. The one allowed exception is a single `build`/`lint` line proving new dependency or package-boundary wiring when this task introduces one.>

If anything in the cited spec section is ambiguous or underspecified for
this task, stop and ask rather than guessing — especially <2–4 task-specific
risks named here, e.g. DC source, budget transition, queue ownership>.
Always include the generic guard: security-sensitive, cost-committing, or
hard-to-reverse changes (cross-account trust, schema changes, billing logic,
data deletion).
```

## Section-by-Section Guidance

### Spec citation(s)
Pull directly from the task's own "per Design XX §Y" reference in the roadmap file. If the task cites a whole document with no `§`, read enough of it to find the specific subsection that actually matters and cite that instead — narrower is better than "read the whole document."

If the task involves creating files, packages, services, apps, or tests, **always** also cite **Design 21 — Monorepo Layout** and use it to determine the correct paths and naming conventions. Do not invent new top-level folders unless the task explicitly requires something outside the documented layout.

### Requirements
State behaviours, not transcriptions. The roadmap bullet is a summary; each requirement should name what the spec *actually specifies* by reference — field/threshold/signature name + `Design XX §Y` + `path:Symbol` — without pasting the definition. Many Design docs include literal snippets: require matching the cited symbol, never paraphrasing it, and never pasting it into the prompt unless it is ≤15 lines *and* the implementer cannot proceed without it inline.
Unless otherwise specified, for AWS CDK deployments use the ap-southeast-2 region.

If the roadmap + spec already settle something, don't re-decide it. If you must fix an underspecification for determinism (e.g. DC precedence, default mode, per-side modifier carriers), put the decision in one line *and* flag it in the ask-if-ambiguous clause so the implementer knows it is prompt-fixed, not spec-fixed.

For any task that touches an AWS CloudFormation resource (CDK L1 construct), **pin the exact canonical property key names** from the CloudFormation docs rather than paraphrasing from memory or the spec. Example: `CfnUserPoolIdentityProvider.providerDetails` keys differ by provider type (`client_id`/`client_secret` for Google; `client_id`/`private_key`/`key_id`/`team_id` for Apple). A 30-second fetch of the CFN resource docs eliminates guesswork at execution time.

For the Secrets Manager dynamic-reference CDK pattern used with L1 constructs, see `docs/tech-tips/CDK-SecretsManager-L1-Dynamic-Reference.md`.

If the task adds or changes a rules-engine module, include the property/metamorphic-test requirement (see *TypeScript / Node.js package conventions* below) as one of the numbered items.

If the task adds or changes a Rules Engine API action or an implemented SRD claim, include a matrix-impact requirement: update `tests/integration/src/vector-matrix/vectors.ts` with an independently hand-calculated row, update `docs/rules-coverage/catalog.json` when the claim is in scope, and remove any superseded duplicate vector assertion from `02.5-B`. If the change is not eligible for matrix coverage, require the prompt to document the reason explicitly.

### Gate and verifier reconciliation (gate-touching tasks)

If the task changes a checker, status vocabulary, or CI gate, the prompt must state the observable effect on existing data, and the author must verify it against the repo before writing the requirement. The gate list is the target repo's to declare: read it from that repo's root `AGENTS.md` plus its optional `aidw/conventions.md` (EXTRACTION.md §3.4/§3.8, D16; R10/R14), and require the generated prompt to name the exact gate commands from that source rather than any command inlined here. A repo that has no conventions yet falls back to the gates its own task prompt names plus the stack's obvious build/test commands. If a gate-touching instruction cannot be reconciled with the repo, fix the instruction or make the reconciliation an explicit deliverable — don't paper over it.

### Traps / prior review findings
This is where hard-won correctness lives — keep it, but keep it tight. Max 5–7 bullets, each: *mistake → consequence → pointer*. Prefer traps that caused real review findings (name collisions, Zod `discriminatedUnion` vs `union` under `superRefine`, engine mode mappings like `TAKE_10→PASSIVE`, frozen parser contracts, required-int wire fields, registry-delegation pattern, fail-closed DC handling). Anything the agent can discover with one `read`/`grep` is not a trap — cut it.

### Credential & L1 property checklist
For any task that touches third-party credentials or L1 CloudFormation properties with sensitive values, answer these three questions before finalizing the prompt — they prevent a deploy→rollback→fix cycle:

1. **Placeholder acceptability.** Does the target AWS service accept a plain placeholder value at resource **creation** time (not just at sign-in/usage time)? Cognito `UserPoolIdentityProvider.client_secret` for Google accepts any string; `private_key` for Apple requires a real ES256 PKCS#8 PEM and fails on deploy with a placeholder. If the service validates at creation, flag it in the prompt as a known blocker with the unblock path.
2. **Value format.** Is the credential's format validated (plain string, JSON, PEM, base64)? If validated, the placeholder must match the format or the task needs an explicit deferral note (as was done for C2's Apple IdP).
3. **Dynamic reference support.** Does CloudFormation support the `secretsmanager` dynamic reference (`{{resolve:secretsmanager:...}}`) in the specific resource property? The only documented exclusions are custom resources, `AWS::CloudFormation::Init` metadata, and EC2 `UserData` — verify per property. See `docs/tech-tips/CDK-SecretsManager-L1-Dynamic-Reference.md` for the CDK-side pattern.

If any of these answers is "no" or "don't know," resolve it and reflect it in the prompt rather than leaving it as a deploy-time discovery.

### Explicit non-goals
This is the single highest-leverage section for keeping tasks bite-sized. Coding agents will often "helpfully" continue into the next logical piece of work unless told not to. Always name at least the next task in the same epic. If the task sits inside a phase/epic that borders a *deferred* design decision (see `00 - Roadmap Overview.md`'s cross-cutting notes — Tier 2 multi-region, sharding, alternative rule sets, Phase 2 AFK engine-play, WAF Bot Control), call that out explicitly too, since those are exactly the kind of "seems like the natural next step" traps.

### Deliverables
File paths only, one per line. "A Lambda that does X" is weaker than `infra/lib/metering-stack.ts:metering-worker (+ test)`. Use **Design 21 — Monorepo Layout** to choose locations, e.g.:
- `services/player-api/src/handlers/action.ts`
- `infra/lib/compute-stack.ts`
- `apps/player-web/src/components/CombatGrid.tsx`
- `packages/shared-types/src/schemas/action.ts`

### Tests
Say *what to prove*, not the literal `expect()`. Require one hand-calculated SRD/spec vector per behaviour path plus purity (no input mutation, no undeclared I/O) and fail-closed checks (rejections roll no dice / throw no raw player text). Name the test file. Do not dictate stub-roller sequences, exact assertion text, dice-entry ordering beyond what the spec normatively requires, or per-claim catalog surgery — for SRD traceability just say "update claims per `docs/srd-analysis/srd-mapping/WORKFLOW.md` and run the validators".

### TypeScript / Node.js package conventions
State the convention in one line per prompt ("pnpm, `workspace:*` internal, `catalog:` external, Zod at boundary only — no Zod inside pure engine fns; every new rules-engine module ships at least one property or metamorphic test with a pinned `seed` + `numRuns`"), not a full matrix. Full detail lives here for reference:

- **pnpm** — the monorepo package manager (`pnpm install`, `pnpm --filter <pkg> <script>`). Never `npm`/`yarn` unless the task migrates away from pnpm.
- **Workspace protocol for internal deps** — `"@mythical-forge/shared-types": "workspace:*"`.
- **Catalogs for shared external deps** — `"aws-cdk-lib": "catalog:"`; add multi-package deps to the catalog rather than pinning per-package.
- **Do not duplicate dependency versions** across packages.
- **Property/metamorphic tests for rules-engine modules** — every new rules-engine module ships with at least one property-based (`fast-check`, added to the `catalog:` block) or metamorphic test alongside its hand-calculated SRD vectors. Every `fc.assert(fc.property(...))` call pins an explicit integer `seed` and `numRuns` so a CI failure reproduces exactly on re-run; a higher `numRuns` may be read from an env var for local exploration only, never required in CI, and failures must be minimised counterexamples. A property or metamorphic test is valid catalog evidence on its own, provided the claim's `notes` state the invariant in SRD terms. Mirrors `AGENTS.md` §6.

### Done when
The roadmap's own "Done when" line is usually already close to right — make it executable with 3–6 task-specific checks (a test file passing, a router call working end-to-end, a frame asserting). If the roadmap's condition is already concrete, copy it as-is. Never include the per-package `build/lint/test` matrix or the `srd:*` validator list here — `record-implementation-results.md` and `update-traceability.md` own generic verification.

### Ask-if-ambiguous clause
Always include it, but scope it: 2–4 task-specific risks named inline (e.g. DC source, budget transition, queue ownership, opposed cross-skill support) plus the generic guard (security-sensitive, cost-committing, hard-to-reverse: cross-account trust, schema changes, billing logic, data deletion). A bare verbatim clause with no task-specific risks is a sign the prompt author didn't read the spec. Before returning the prompt, run the pre-submit self-check below; it is where the `prompt-fixed` label defined here is applied.

## Pre-submit self-check

Before you return the prompt, walk the same ground as the reviewer's `## Review order` in
`task-review.md` — read it, do not transcribe it. Each numbered check below shadows one
review-order step. Where the cited spec is silent, make the decision explicit and label it
`prompt-fixed` with its rationale, and name the ambiguity in the ask-if-ambiguous clause — the one
label that clause already defines; do not invent a second. If a check would force bloat, cut
context and keep traps (Conciseness budget).

1. **Set the frame** — task id, cited specs, deliverable, acceptance checks and non-goals, and who or what the change affects.
2. **Trace the authority chain** — every requirement cites the roadmap entry or spec section that fixes it; where new shared code lives is decided from the repository conventions, and labelled `prompt-fixed` if the spec is silent.
3. **Check repository fit** — paths, names and dependencies exist in the current tree; the claimed prerequisite state is true.
4. **Review the requested behavior** — failure-path precedence when two failures are possible, and per-mode output contracts on the failure path, are each decided and labelled `prompt-fixed` if the spec is silent.
5. **Check internal consistency** — the complete label/key vocabulary, why the enumerated set is complete, and exact comparison semantics are all decided; requirements, non-goals, deliverables and Done-when do not contradict.
6. **Check task boundaries and dependencies** — one coherent task, adjacent work named as a non-goal, no missing prerequisite.
7. **Check the proof** — one proof per requirement: every numbered requirement maps to at least one Tests or Done-when assertion that would fail under a broken implementation.
8. **Check ambiguity severity** — every material ambiguity the spec leaves open is visibly labelled `prompt-fixed` with its rationale and named in the ask-if-ambiguous clause, not left implicit.
9. **Report findings** — the ask-if-ambiguous clause names its task-specific risks and the generic guard.
