---
description: Refresh the combat child diagram (turn resolution subsystems) from current source evidence
argument-hint: "[change-ref]"
---

# Refresh the combat child diagram

Maintains one artifact: the Archify architecture map of the **combat** facet's internals. It is a child of `rules-engine-architecture.json`, which shows `Combat & Action Economy` as a single node with the entry point `resolveCombatTurn`. This diagram opens that node up: the turn gate, the attack pipeline, injury and death, and the off-turn reaction subsystems.

This is a **documentation-refresh prompt**. It must not change application, infrastructure, or rules-engine implementation code. If the diagram is wrong, the implementation is the source of truth and the diagram is what gets fixed.

Read `docs/architecture/diagrams/README.md` first. It holds the shared authoring contract — the two budgets, the universal geometry rules, the layout archetypes, the truthfulness rules, and the delivery/freeze protocol. This prompt does not restate it.

## Variables

change_ref: $1

- `change_ref` is optional. If supplied, treat it as the change that motivated this refresh and check whether it altered any entry point, stage, or cross-module edge.
- If omitted, compare `services/rules-engine/src/combat/` against what the specification records and reconcile the difference.

## Artifacts (fixed paths — do not create others)

- Candidate specification: `docs/architecture/diagrams/rules-engine-combat-architecture.json`
- Generated artifact: `docs/architecture/diagrams/rules-engine-combat-architecture.html`
- No evidence sidecars are committed. `visual-check` writes a receipt, a contact sheet, and screenshots next to the HTML; delete all of them and quote the delivery SHA-256 values in the response instead. See `docs/architecture/diagrams/README.md`.

Never hand-edit the generated HTML.

## Update in place — do not re-author from scratch

The existing candidate is a **geometrically validated baseline**: `viewBox [1280, 500]`, a three-row landscape layout, 12 components, 11 connections. Update it as a small diff and preserve existing `id`, `pos`, `size`, and every routing control unless the facts require a change.

**A stale diagram still validates.** `validate` verifies that every `sources` path and line resolves at the pinned revision; it cannot tell you that the claim beside it is still true. A citation that resolves is not a fact that holds. **Re-derive the imports and the caller-composed edges from the source modules before preserving anything** — then keep the diff small, as above.

**Record the verification.** Update the `rules-engine-combat-architecture.json` row in `docs/architecture/diagrams/diagram-state.md` — the UTC date and the full commit SHA you verified against, kept equal to `meta.repository.revision`. A fabricated date there is worse than an empty one.


If you add or remove a node, you are spending from the readability budget — shorten copy elsewhere and re-validate. Do not widen the canvas.

## Evidence sources (read these, in this order)

1. `services/rules-engine/src/combat/index.ts` — the module's public surface; the authoritative list of what combat exports.
2. `services/rules-engine/src/combat/resolveCombatTurn.ts` — the orchestrator. Its numbered comments (`── 0.` … `── 20.`) **are** the turn pipeline and the best source for stage boundaries.
3. `services/rules-engine/src/combat/encounterInit.ts` — the pre-turn phase; its header quotes the SRD "How Combat Works" steps 1–3.
4. `services/rules-engine/src/combat/endOfRound.ts` — the post-turn phase; its header documents the two passes (dying tick/stabilisation, nonlethal re-evaluation).
5. `services/rules-engine/src/combat/statusGating.ts` and `actionEconomy.ts` — the gate that runs before any dice.
6. The leaves: `attack.ts`, `armorClass.ts`, `initiative.ts`, `damage.ts`, `injury.ts`, `attackOfOpportunity.ts`, `deathTrigger.ts`, `surpriseRound.ts`, `fullAttack.ts`.
7. `docs/specs/Design 06 - Combat.md` §3A–§3C (initiative queue, action economy, AoO flow, combat calculation matrix) and `docs/specs/Design 09 - Game Rules Engines.md` §3 Engine 1.

## Current baseline structure

**Middle row — the turn pipeline, left to right**

| Node | Owns | Entry point |
|---|---|---|
| `turn` | the orchestrator wrapping steps 1–20 | `resolveCombatTurn` |
| `compose` | attacker modifiers and the target's selected AC (steps 1–13) | `armorClass.ts`, `attack.ts` inputs |
| `roll` | d20 vs AC, threat range, critical confirmation | `resolveAttackRoll` |
| `damage` | weapon dice, Strength, minimum 1 (steps 15–17) | `rollWeaponDamage`, `applyMinimumDamage` |
| `injury` | HP application, status derivation, both death paths | `applyDamage`, `evaluateHpStatus`, `checkDeathTrigger`, `checkMassiveDamage` |

**Top row — before, around, and after**

| Node | Owns | Entry point |
|---|---|---|
| `encounter` | surprise round, initiative queue, everyone starts flat-footed | `beginEncounter` |
| `gate` | status and budget, fail-closed before any dice | `resolveStatusGate`, `validateActionEconomy` |
| `movement` | cover (+4 AC) and flanking (+2) — **sibling module** | `getCoverBonus`, `getFlankingBonus` |
| `progression` | BAB, ability modifiers, size — **sibling module** | `getBAB`, `getAbilityModifier`, `getSizeModifier` |
| `round` | dying tick, d% stabilisation, nonlethal re-evaluation | `processEndOfRound` |

**Bottom row — off-path**

| Node | Owns | Entry point |
|---|---|---|
| `multi` | iterative and two-weapon attack slots | `getIterativeAttacks`, `getTwoWeaponFightingSlots` |
| `aoo` | provocation, casting defensively, the off-turn attack | `doesMovementProvokeAoO`, `doesSpellcastProvokeAoO`, `resolveCastDefensively`, `resolveAttackOfOpportunity` |

## Facts the diagram must keep honest

- **Two edges are caller-composed, not imports.** `injury → round` (`processEndOfRound` is invoked once per round by the initiative/turn loop) and `encounter → gate → turn` (the dispatcher gates before reaching the engine). `resolveCombatTurn` does **not** call `resolveStatusGate`; its header says so explicitly and throws `CombatStatusError` only as a caller-bug guard. Keep this distinction visible — it is currently carried by the card copy.
- **Real cross-module imports during a turn are exactly two modules:** `movement/spatial` (cover, flanking) and `progression` (BAB, ability modifier, size). Do not add others without checking the imports.
- **`injury.ts` does not import `progression`.** The Fortitude save modifier, Constitution score, and death-threshold rule arrive on the caller's `CombatCreatureState` snapshot. There is deliberately no `progression → injury` edge. Do not add one.
- **`attackOfOpportunity.ts` does not import `movement`.** It owns `isSquareThreatened` and `doesMovementProvokeAoO` itself; the squares and reach are caller-supplied. The only real import is `resolveAttackRoll` from `combat/attack.ts`, which is why `aoo → roll` is drawn and `movement → aoo` is not.
- **An AoO is one melee attack at full BAB — no iterative attacks.** If the pipeline changes, this is the kind of rule worth surfacing.
- **Two death paths.** HP threshold (`checkDeathTrigger`) and massive damage (≥50 in one hit, then a Fortitude save). `resolveCombatTurn` triggers the massive-damage check only when the hit did not already kill by HP threshold.
- **`PLAYER_DOWNED` is emitted only for the player.** An NPC death is `status: DEAD` state alone; the event carries no entity id, so emitting it for an NPC would mis-attribute it.
- **Range penalties are a deliberate stub** (`+ 0` in `resolveCombatTurn` step 7). Do not present them as implemented.
- **Out of scope by design:** Immediate/Swift interleaving beyond the spec's table, and the Dispatcher's turn loop that iterates the queue. Do not draw them.

**The likeliest silent staleness here — check these two first.** Range penalties stop being a stub (`resolveCombatTurn` step 7 currently hard-codes `+ 0`), or `resolveCombatTurn` starts calling `resolveStatusGate`, which would turn the caller-composed `gate`/`turn` edge into a real import. Both are asserted as current behaviour in the card copy, so either one makes the diagram false without breaking any gate.

## Layout notes specific to this diagram

The baseline uses archetype **B (landscape pipeline)** from the README. Points worth knowing before editing:

- Six columns at pitch 205 (`x` = 40, 245, 450, 655, 860, 1065), node sizes `[175, 72]`–`[175, 76]`, rows at `y` = 30, 210, 390.
- The sibling inputs (`movement`, `progression`) enter from the **top row** into their targets below; the off-path combat subsystems (`multi`, `aoo`) sit in the **bottom row**.
- Horizontal middle-row edges carry `labelDy: 60`; the vertical top-row edges carry `labelDy: 74`. Without these the labels sit on the source node.
- There is deliberately **no boundary**. An earlier draft wrapped `src/combat/` in a region, but the padded rectangle then enclosed the sibling inputs, and a boundary tall enough to exclude them pushed the aspect ratio past the containment limit. The sibling modules are distinguished by `tag: "sibling module"` instead. If you reintroduce a boundary, re-check both budgets.

## Keeping the diagram current

- A new numbered step in `resolveCombatTurn`, or a new module in `combat/index.ts`, means a stage or node is missing.
- A change to `ACTING_STATUSES`, `NO_ACTION_STATUSES`, or `RESTRICTED_STATUSES` in the gate, or to `ActionCategory`, changes what "fail closed" means.
- A change to the massive-damage threshold, the stabilization roll, or the death-threshold rules changes the injury/round nodes.
- A change to the AoO provocation rules, or to casting defensively, changes the `aoo` node.
- A change in the caller chain (who calls `resolveCombatTurn`, and whether the gate still runs before it) changes the `gate`/`turn` relationship.
- Bump `meta.repository.revision` to the full 40-hex commit being documented.

If `change_ref` is supplied, state which stages it affected and which it did not. If nothing changed, update only the revision — or leave the artifact untouched and say why.

## Non-goals

- Do not touch the other rules-engine diagrams, `docs/architecture/Infrastructure Architecture.md`, or the infrastructure/authentication diagrams.
- Do not change rules-engine implementation, tests, or `IRulesEngine`.
- Do not add, remove, or rename a Rules Engine API action or an SRD claim. A diagram refresh changes no engine behaviour, so `tests/integration/src/vector-matrix/vectors.ts` and `docs/rules-coverage/catalog.json` are **out of scope here** — they follow the action or claim that motivated the change and belong to that change's own task. State this reasoning rather than silently skipping the check.
- Do not widen `meta.viewBox`, add speculative tiers, or draw an edge that is not a real import or a documented caller-composed step.

## Done when

- Every node maps to a real module or orchestrator step, every edge is verified against the imports, and every `sources` path and line exists at the pinned revision.
- `validate` passes with `--quality showcase`: 9/9 artifact checks, 0 composition errors, 0 warnings.
- The containment probe passes (aspect ratio ≤ ~0.45 and no `overflowY`), then `deliver` succeeds and its receipt reports matching specification and artifact SHA-256 values.
- `visual-check` against the exact delivered artifact reports no overflow and readability OK at 1440×900, 1600×1000, 1920×1080, and 2048×1320.
- `meta.repository.revision` matches the commit documented, and only the spec, the artifact, and this diagram's row in `docs/architecture/diagrams/diagram-state.md` are changed — no `visual-check` sidecars remain.
- This diagram's row in `docs/architecture/diagrams/diagram-state.md` records the date and commit actually verified against — not backdated, and equal to `meta.repository.revision` where the schema has it.
- `git diff --check` passes.

If the source and Design 06 disagree about a combat rule, or an edge's truthfulness cannot be established from the imports, **stop and ask** rather than guessing.

## Response

Return:

1. The artifact paths changed, and whether this was a refresh-in-place or a re-layout.
2. Each node and edge verified, with the import or source that proves it — and explicitly, which edges are caller-composed rather than imported.
3. The exact commands run with their real outcomes (validation check count, error/warning count, delivery SHA-256 values, `visual-check` per-viewport results). Never report a non-zero exit as success.
4. Browser evidence and perceptual review reported **separately**. If the active model cannot view images, state that the perceptual review was not performed.
5. Anything unresolved, assumed, or deliberately left out of scope.