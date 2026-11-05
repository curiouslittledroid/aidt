---
destination: mythical-forge/aidw/prompts/
description: Update architecture documentation and Archify diagrams after an implementation change
---

# Update architecture documentation

Run this prompt after an implementation task, before review or PR preparation. The implementation is already complete; this prompt updates architecture documentation to match the verified repository state. Do not modify application or infrastructure implementation code.

**A stale diagram still validates.** This is the master prompt for every diagram in the directory, and it carries the failure mode that matters most here: `validate` proves a drawing is internally consistent and that its `sources` citations resolve. It **cannot** tell you that a component label, a relationship, or a participant still describes the system. A 9/9 pass is evidence about the *drawing*, not about the *truth* of its labels. Two artifacts in this directory passed `validate` 9/9 for a long time while being materially wrong — one drew a mock integration that had been real for months, another drew a model call where the handler sends a hard-coded string. Neither defect was reachable by any gate. **Re-derive each claim from the CDK stacks, the handlers, and the prose inventory before preserving it** — never accept a green `validate` as evidence of freshness, and never treat "the committed specification says X" as a reason to keep X.

## Variables

change_ref: $1
base_ref: $2

- `change_ref` is optional. If supplied, use it as the commit, branch, or PR/change reference to review.
- `base_ref` is optional. If omitted, use `main` as the comparison base when it exists.
- If neither argument is supplied, review the current branch relative to `main`, plus staged, unstaged, and untracked files.

## Source-of-truth locations

- AWS infrastructure inventory: `docs/architecture/Infrastructure Architecture.md`
- CDK application: `infra/`
- Repository rules: `AGENTS.md`
- Formal system specifications: `docs/specs/`
- Implementation task and task prompt: identify these from the change being reviewed

## Approved architecture artifacts

This prompt is intentionally allowlisted so the workflow does not create random documentation or diagrams. Update only these architecture artifacts:

1. `docs/architecture/Infrastructure Architecture.md` — the canonical AWS/CDK resource inventory.
2. `docs/architecture/diagrams/infrastructure-diagram.json` — the Archify candidate specification for the AWS infrastructure diagram, with `docs/architecture/diagrams/infrastructure-diagram.html` as its generated artifact.
3. `docs/architecture/diagrams/authentication-api-sequence.json` — the Archify sequence specification for Cognito hooks and API Gateway/Lambda authentication flow, with `docs/architecture/diagrams/authentication-api-sequence.html` as its generated artifact.
4. `docs/architecture/diagrams/rules-engine-architecture.json` — the Archify architecture specification for the deterministic rules engine's SRD 3.5 subsystems, with `docs/architecture/diagrams/rules-engine-architecture.html` as its generated artifact.
5. `docs/architecture/diagrams/rules-engine-combat-architecture.json` — the Archify architecture specification for the combat facet's internals (turn gate, attack pipeline, injury/death, reactions), with `docs/architecture/diagrams/rules-engine-combat-architecture.html` as its generated artifact.
6. `docs/architecture/diagrams/rules-engine-spells-architecture.json` — the Archify architecture specification for the spells and magic facet's internals (cast gate, save DC, saving throw, save effects, conditions), with `docs/architecture/diagrams/rules-engine-spells-architecture.html` as its generated artifact.
7. `docs/architecture/diagrams/rules-engine-skills-architecture.json` — the Archify architecture specification for the skills and stunts facet's internals (fail-closed gate, skill modifier, check modes, opposed resolution, stunt fallback), with `docs/architecture/diagrams/rules-engine-skills-architecture.html` as its generated artifact.
8. `docs/architecture/diagrams/rules-engine-movement-architecture.json` — the Archify architecture specification for the movement and spatial facet's internals (illegal-space recovery, validation precedence, grid passability, pathfinding, path cost, speed budget, cover and flanking), with `docs/architecture/diagrams/rules-engine-movement-architecture.html` as its generated artifact.
9. `docs/architecture/diagrams/rules-engine-progression-architecture.json` — the Archify architecture specification for the progression and attributes kernel (ability modifiers, BAB, size, saving throws, hit dice, skill rank caps, and the static class tables), with `docs/architecture/diagrams/rules-engine-progression-architecture.html` as its generated artifact.
10. `docs/architecture/diagrams/rules-engine-vision-world-architecture.json` — the Archify architecture specification for the vision and world facet (the light ladder and the overland travel graph, as two independent models), with `docs/architecture/diagrams/rules-engine-vision-world-architecture.html` as its generated artifact.
11. `docs/architecture/diagrams/lambda-dataflow.json` — the Archify dataflow specification for the Lambda estate (every function, its pipeline stage, and the datastores and external services it touches), with `docs/architecture/diagrams/lambda-dataflow.html` as its generated artifact. Renamed from `mythical-forge-lambdas.dataflow.json` / `mythical-forge-lambdas.html`.
12. `docs/architecture/diagrams/README.md` — the shared Archify authoring contract for this directory (commands, the two layout budgets, geometry rules, layout archetypes, truthfulness rules). Update it only when the contract itself changes, never to describe one diagram's facts.
13. `docs/architecture/diagrams/player-ws-message-flow.sequence.json` — the Archify sequence specification for one `PLAYER_INPUT` turn (identity resolution, ingress moderation, intent parse, in-process rules execution, frames out), with `docs/architecture/diagrams/player-ws-message-flow.html` as its generated artifact.
14. `docs/architecture/diagrams/diagram-state.md` — the as-of record for every diagram in the directory (one row per diagram: last-verified date and the commit verified against). **Each diagram's own prompt owns its row**; update a row here only for a diagram this run actually re-derived, and never fabricate or backdate a date. See the file itself for the convention.

When the change reaches the AWS infrastructure *topology* — a new service, a new entry point, or a new trust/network boundary — prefer the dedicated prompt `/update-infrastructure-diagram`, which owns artifact 2 and encodes that diagram's granularity rule (a curated ~12-node view over 211 synthesized resources), the `cdk synth` ground-truth check, and its layout constraints. Update artifact 2 from this prompt only to keep it consistent with a change that also affected artifact 1; do not run the dedicated prompt and this prompt against the same change.

When the change touches browser identity, a Cognito trigger, a token claim, or how an API entry point authorizes a request, prefer `/update-authentication-sequence-diagram`, which owns artifact 3. It encodes that diagram's scope boundary (authorization in, gameplay out), its sequence-specific commands and budgets (no `--repo-root`; a ~0.64 aspect ceiling rather than ~0.45), and the handler files that are its evidence. Update artifact 3 from this prompt only to keep it consistent with an artifact 1/2 change; do not run the dedicated prompt and this prompt against the same change.

When the change touches the Lambda estate — a Lambda added or removed, a placeholder becoming real, a new event source, or a new datastore access — prefer `/update-lambda-dataflow-diagram`, which owns artifact 11. Its committed baseline passes `--quality showcase` (9/9 checks, 0 errors) and both browser budgets at 1440×900, but it sits in a narrow window: `validate` caps its viewBox width at ~1085 while containment needs a low aspect, so **a fourth node row would break it**. The prompt records the measured constraints and the routing that makes the 3-row layout work; read it before re-planning geometry. Update artifact 11 from this prompt only to keep it consistent with an infrastructure change; do not run both prompts against the same change.

When the change touches the post-connect gameplay path — a handler step in `ws-message.ts`, an ingress-moderation verdict, a frame type, or the intent/rules dispatch pipeline — prefer `/update-player-ws-message-flow-diagram`, which owns artifact 13. **That prompt's governing rule is that the diagram must match implemented reality, never future state** (a stub is drawn as a stub, an unimplemented step is not drawn at all), and it currently carries a repair list: the committed artifact draws a narration model call that is a hard-coded stub, omits ingress moderation, and asserts a DynamoDB state write that does not exist. Read it before touching artifact 13. Update artifact 13 from this prompt only to keep it consistent with a change that also affected the artifacts above; do not run both prompts against the same change.

When the change touches the rules engine's facet set, entry points, or caller chain, prefer the dedicated prompts — `/update-rules-engine-diagram`, `/update-rules-engine-diagram-combat`, `/update-rules-engine-diagram-spells`, `/update-rules-engine-diagram-skills`, `/update-rules-engine-diagram-movement`, `/update-rules-engine-diagram-progression`, and `/update-rules-engine-diagram-vision-world` — which own artifacts 4–10 and encode their layout constraints and evidence sources. Update artifacts 4–10 from this prompt only to keep them consistent with a change that also affected the artifacts above; do not run the dedicated prompt and this prompt against the same change.

Do not create, rename, or update any other architecture document or diagram. If a completed implementation requires another architecture artifact, stop and ask for the target to be explicitly added to this list. Future approved architecture documents and diagrams must be added to this allowlist before this prompt updates them.

The architecture documentation describes verified implementation. Do not add a resource, relationship, runtime behavior, security property, or deployment dependency solely because a design spec proposes it.

## Instructions

1. **Set the review frame.**
   - Read `AGENTS.md`.
   - Determine the current branch and repository status.
   - Identify the implementation task, commit, or change being documented.
   - Inspect the complete relevant diff, including staged, unstaged, and untracked files. If `change_ref` is supplied, include that change explicitly.
   - Preserve unrelated user changes. Do not reset, checkout, clean, commit, push, or modify implementation files.

2. **Classify the change.**
   Identify whether it affects:
   - AWS/CDK infrastructure: anything under `infra/`, `infra/lib/config.ts`, stacks, constructs, custom resources, secrets, IAM policies/grants, CloudFormation outputs, deployment dependencies, or runtime network placement.
   - Application architecture: services, packages, apps, APIs, persistence, queues, event flows, or externally visible runtime boundaries.
   - Existing or future architecture diagrams/documents.
   - No architecture-relevant behavior.

3. **Read the implementation evidence.**
   - For infrastructure changes, inspect `infra/bin/infra.ts` and every changed or affected stack/construct in context.
   - Inspect relevant Lambda/service source, package configuration, tests, and deployment configuration.
   - Read the cited specification sections when needed to resolve names or intended contracts, but prefer actual implementation and synthesized templates for deployed-resource facts.
   - Record exact resource names, stack ownership, environment differences, regions, subnet/security-group placement, cross-stack props, IAM boundaries, endpoint paths, protocols, and whether a component is live, a placeholder, a stub, optional, or deferred.

4. **Verify CDK infrastructure from synthesized templates.**
   When infrastructure changed:
   - Run the relevant `pnpm` CDK synth command, at minimum:
     `pnpm --filter infra cdk synth -c env=dev`
   - If environment-specific configuration, proxy deployment, or stack dependencies changed, also synthesize the affected staging/prod variants and any relevant context such as `-c deployProxy=true`.
   - Inspect the synthesized templates for resource types, properties, logical resources, outputs, imports/exports, and dependencies. Do not document a resource as deployed unless the CDK source and synth evidence support it.
   - Use the resulting templates to update the resource inventory, environment table, deployment-order diagram, and cross-stack references as applicable.

5. **Update the canonical AWS inventory.**
   Update `docs/architecture/Infrastructure Architecture.md` when infrastructure changed:
   - Keep the environment/account/region/configuration table accurate.
   - Keep §2 deployment order, stack dependencies, and the dependency diagram accurate.
   - Update the affected stack's purpose and resource table with exact CDK resource IDs, AWS types, physical names, important properties, and current implementation status.
   - Update database/schema, network, security, custom-resource, deferred-work, and non-goal notes when affected.
   - Update §10 cross-stack references whenever stack props or CloudFormation references change.
   - Remove stale resource rows, paths, claims, and diagrams rather than leaving contradictory documentation.
   - Use repository-relative paths under `docs/architecture/`; do not restore the old `docs/Infrastructure Architecture.md` or `docs/diagrams/` locations.

6. **Use the Archify skill for architecture diagrams.**
   If infrastructure changed, or if an existing architecture diagram's facts/relationships are affected:
   - Use the Archify skill. Read `/Users/phil/.pi/agent/skills/archify/SKILL.md` and follow its architecture authoring, validation, delivery, and visual-check workflow.
   - Inspect and update the approved AWS candidate specification at `docs/architecture/diagrams/infrastructure-diagram.json`; its generated artifact is `docs/architecture/diagrams/infrastructure-diagram.html`.
   - When Cognito hooks, API Gateway authorization, Lambda proxy events, or token/request contracts change, also update the approved sequence specification at `docs/architecture/diagrams/authentication-api-sequence.json`; its generated artifact is `docs/architecture/diagrams/authentication-api-sequence.html`.
   - Update the approved rules-engine architecture specification at `docs/architecture/diagrams/rules-engine-architecture.json` (artifact: `docs/architecture/diagrams/rules-engine-architecture.html`) only when the change affects the rules-engine facet set, an engine entry point (`resolveCombatTurn`, `resolveSpellTurn`, `resolveSkillTurn`, …), or the `rulesRegistry` caller chain. Its layout has a narrow readability budget: do not widen `meta.viewBox` beyond ~1250, and read `/update-rules-engine-diagram` before re-planning any geometry.
   - Update the approved combat child specification at `docs/architecture/diagrams/rules-engine-combat-architecture.json` (artifact: `docs/architecture/diagrams/rules-engine-combat-architecture.html`) only when the change affects combat internals: a stage of `resolveCombatTurn`, `src/combat/` module ownership, the status/action gate, the injury and death rules, or the attacks-of-opportunity rules. Read `/update-rules-engine-diagram-combat` before re-planning any geometry.
   - Update the approved spells child specification at `docs/architecture/diagrams/rules-engine-spells-architecture.json` (artifact: `docs/architecture/diagrams/rules-engine-spells-architecture.html`) only when the change affects spell internals: a stage of `resolveSpell`/`resolveSpellTurn`, a `SpellTurnFailureReason`, the save DC formula, save-effect handling, the character/monster save split, or spell-slot consumption. Also update it when a deferral it records is lifted — its cards assert that range, components, conditions, damage application, and `cast_defensively` are not yet wired; if any of those becomes live, that claim is now false. Read `/update-rules-engine-diagram-spells` before re-planning any geometry.
   - Update the approved skills child specification at `docs/architecture/diagrams/rules-engine-skills-architecture.json` (artifact: `docs/architecture/diagrams/rules-engine-skills-architecture.html`) only when the change affects skill internals: a `SkillTurnRejectionReason`, `computeModifier`, a `SkillCheckMode`, the opposed tie-break or `MAX_OPPOSED_REROLLS`, the Aid Another flow, or the stunt engine. Also update it when a claim it records is lifted — its cards assert that `equipped_gear` is never consumed, that `state_deltas` is always empty, and that the stunt fallback is router-only; if the stunt fallback becomes reachable from live play, that tag and card line are false. Read `/update-rules-engine-diagram-skills` before re-planning any geometry.

   - Update the approved movement child specification at `docs/architecture/diagrams/rules-engine-movement-architecture.json` (artifact: `docs/architecture/diagrams/rules-engine-movement-architecture.html`) only when the change affects movement internals: a `MovementRejectionReason`, the validation precedence, `GridMap` fields or override semantics, the pathfinder's parity state or corner-cutting rule, the cost rules, `resolveIllegalSpace`, or the cover/flanking geometry. Also update it when a claim it records is lifted — its cards assert that recovery runs before validation, that the live executor hard-codes `MOVE`, and that combat is cover/flanking's only consumer. Read `/update-rules-engine-diagram-movement` before re-planning any geometry.

   - Update the approved progression child specification at `docs/architecture/diagrams/rules-engine-progression-architecture.json` (artifact: `docs/architecture/diagrams/rules-engine-progression-architecture.html`) only when the change affects a progression formula (`modifier`, `bab`, `saves`, `hp`, `skill`, `size`), a class→progression map, or the set of engines that compose it. This facet is a library, not a pipeline — do not reshape it into stages. Also update it when a claim it records is lifted: its cards and tags assert that no level-up flow exists, so a new caller for `rollHPGain`, `getHitDie`, `getMaxSkillRanks` or `isSkillAtCap` makes them false. Read `/update-rules-engine-diagram-progression` before re-planning any geometry.

   - Update the approved vision-and-world child specification at `docs/architecture/diagrams/rules-engine-vision-world-architecture.json` (artifact: `docs/architecture/diagrams/rules-engine-vision-world-architecture.html`) only when the change affects the light ladder (`LightLevel`, concealment or AC penalties, `DARKVISION_RANGE_FT`, `VisionType`), the overland graph (`TerrainDifficulty`, `TERRAIN_MULTIPLIER`, directed-edge semantics, travel-time rounding), or a caller. It is deliberately two independent clusters, not one flow — do not join them. Also update it when the claim it records is lifted: its cards assert that neither module has an in-engine consumer. Read `/update-rules-engine-diagram-vision-world` before re-planning any geometry — both the readability and containment budgets are tight and pull against each other.
   - The shared authoring contract for this directory is `docs/architecture/diagrams/README.md`; follow it for all of the above.
   - Update diagrams from verified CDK/source evidence: components, participants, boundaries, stack/resource ownership, relationships, messages, labels, source references, and environment-specific behavior. Do not imply that placeholder Lambdas, mock API integrations, optional RDS Proxy deployment, deferred WAF, or other future work is live.
   - Keep the Archify repository revision metadata pinned to the commit being documented when repository evidence is used.
   - **Record every diagram you actually re-derived** in `docs/architecture/diagrams/diagram-state.md`: its row's `Last verified (UTC)` date and the commit verified against. Update only the rows for diagrams whose claims you re-checked from source this run — not every row for a change that touched one diagram, and never with a date you did not earn. A fabricated date there is worse than an empty one, because the table exists to be trustworthy at a glance.
   - Do not create a new diagram type or future architecture view in this run. Future diagrams must be explicitly added to the approved artifact list above before this prompt is used to maintain them.
   - Validate after every candidate edit and immediately before delivery:
     `node /Users/phil/.pi/agent/skills/archify/bin/archify.mjs validate <type> <candidate.json> --quality showcase --repo-root . --json`
   - Deliver the final HTML only after validation passes:
     `node /Users/phil/.pi/agent/skills/archify/bin/archify.mjs deliver <type> <candidate.json> <output.html> --quality showcase --repo-root . --json`
   - Run bounded browser evidence on the exact delivered HTML:
     `node /Users/phil/.pi/agent/skills/archify/bin/archify.mjs visual-check <output.html> --json`
   - Never hand-edit generated HTML. If Archify validation or browser evidence fails, repair the candidate specification and rerun the required checks. Report environmental browser failures truthfully rather than claiming visual verification.

7. **Keep the allowlist closed.**
   - Keep the approved artifacts internally consistent. Use exact code identifiers, paths, protocols, resource names, and environment names.
   - Do not create duplicate diagrams, new architecture documents, or files in legacy locations.
   - If a change needs an artifact outside the allowlist, stop and ask instead of creating it.
   - If no architecture-relevant behavior changed, leave both approved artifacts untouched and state why.

8. **Verify the result.**
   - Confirm all links and repository-relative paths point to the approved artifacts under `docs/architecture/`.
   - For infrastructure changes, confirm the inventory matches synthesized templates and that `infrastructure-diagram.json`/`infrastructure-diagram.html` match the same evidence.
   - Run focused documentation/JSON validation and relevant project checks. At minimum, run `git diff --check`; run CDK synth and Archify validation/delivery/visual-check whenever applicable.
   - Review the final diff for stale old paths, contradictions, invented facts, accidental implementation changes, and unrelated file modifications.

## Done when

- `docs/architecture/Infrastructure Architecture.md` accurately describes every affected deployed AWS resource and stack relationship, based on verified CDK source and synthesized templates.
- The approved artifacts are the only architecture files changed: `docs/architecture/Infrastructure Architecture.md`, plus the affected approved diagram candidate and generated HTML under `docs/architecture/diagrams/`, plus the affected rows in `docs/architecture/diagrams/diagram-state.md`.
- Every diagram whose claims this run actually re-derived has its row in `docs/architecture/diagrams/diagram-state.md` updated with the date and commit verified against — not backdated, and equal to `meta.repository.revision` where the schema has it. Diagrams that were only re-validated, or not touched, keep their existing row: a stale row is honest, a backdated one is not.
- If infrastructure changed, the AWS Archify candidate and generated HTML are updated at the approved paths, Archify validation passes with the showcase profile and zero errors/warnings, and `visual-check` is run against the exact delivered artifact.
- If no architecture-relevant behavior changed, the prompt records that conclusion and does not make speculative documentation or diagram changes.
- `git diff --check` passes, and the final diff contains only the intended documentation and diagram updates.

If the implementation, synthesized template, or cited specification is ambiguous or contradictory—especially for security boundaries, IAM permissions, network placement, data ownership, billing resources, or irreversible infrastructure changes—stop and ask rather than guessing.

## Response

Return:

1. The architecture documents and diagrams updated, with paths.
2. The implementation evidence and commands used to verify them.
3. Any remaining unverified areas or environment limitations.
