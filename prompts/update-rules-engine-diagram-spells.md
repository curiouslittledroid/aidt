---
description: Refresh the spells child diagram (cast resolution subsystems) from current source evidence
argument-hint: "[change-ref]"
---

# Refresh the spells child diagram

Maintains one artifact: the Archify architecture map of the **spells and magic** facet's internals. It is a child of `rules-engine-architecture.json`, which shows `Spell & Magic System` as a single node with the entry point `resolveSpellTurn`. This diagram opens that node up: composing a cast from state, the fail-closed gate, save DC and save composition, the saving throw, save effects, and conditions.

This is a **documentation-refresh prompt**. It must not change application, infrastructure, or rules-engine implementation code. If the diagram is wrong, the implementation is the source of truth and the diagram is what gets fixed.

Read `docs/architecture/diagrams/README.md` first. It holds the shared authoring contract — the two budgets, the universal geometry rules, the layout archetypes, the truthfulness rules, and the delivery/freeze protocol. This prompt does not restate it.

## Variables

change_ref: $1

- `change_ref` is optional. If supplied, treat it as the change that motivated this refresh and check whether it altered any stage, rejection, or cross-module edge.
- If omitted, compare `services/rules-engine/src/spells/` against what the specification records and reconcile the difference.

## Artifacts (fixed paths — do not create others)

- Candidate specification: `docs/architecture/diagrams/rules-engine-spells-architecture.json`
- Generated artifact: `docs/architecture/diagrams/rules-engine-spells-architecture.html`
- No evidence sidecars are committed. `visual-check` writes a receipt, a contact sheet, and screenshots next to the HTML; delete all of them and quote the delivery SHA-256 values in the response instead. See `docs/architecture/diagrams/README.md`.

Never hand-edit the generated HTML.

## Update in place — do not re-author from scratch

The existing candidate is a **geometrically validated baseline**: `viewBox [1280, 500]`, a three-row landscape layout, 11 components, 10 connections.

**A stale diagram still validates.** `validate` verifies that every `sources` path and line resolves at the pinned revision; it cannot tell you that the claim beside it is still true. A citation that resolves is not a fact that holds. **Re-derive the imports and the caller-composed edges from the source modules before preserving anything** — then keep the diff small, as above.

**Record the verification.** Update the `rules-engine-spells-architecture.json` row in `docs/architecture/diagrams/diagram-state.md` — the UTC date and the full commit SHA you verified against, kept equal to `meta.repository.revision`. A fabricated date there is worse than an empty one.


The card copy is load-bearing in a way it is not elsewhere: this layout sits within ~23px of the containment limit at 1440×900, and the earlier draft failed only because the cards were two lines taller. **Adding a card line can break containment.** If you add one, trim another and re-run the containment probe before delivering.

## Evidence sources (read these, in this order)

1. `services/rules-engine/src/spells/index.ts` — the module's public surface.
2. `services/rules-engine/src/spells/resolveSpell.ts` — the leaf. Its header enumerates the six responsibilities from Design 09 §3 Engine 2, and its numbered `// Step N` comments are the pipeline.
3. `services/rules-engine/src/spells/resolveSpellTurn.ts` — the orchestrator. `SpellTurnFailureReason` (line 195) **is** the rejection vocabulary, and `composeTargetSaves` (line 236) is the character/monster save split.
4. `services/player-api/src/dispatcher/spellExecutor.ts` — the live caller. Its header comment is the best record of what is deliberately deferred; the call site shows which inputs the adapter resolves versus hard-codes.
5. `services/rules-engine-api/src/db/srdQueries.ts` — `getSpellById` (line 160), the `srd_spells` lookup that produces `SpellReferenceType`.
6. `docs/specs/Design 09 - Game Rules Engines.md` §2A (Spell Registry as static reference data) and §3 Engine 2.
7. `docs/specs/Design 06 - Combat.md` §3C item 3 for the saving-throw composition, if you touch the save nodes.

## Current baseline structure

**Middle row — the cast pipeline, left to right**

| Node | Owns | Entry point |
|---|---|---|
| `turn` | composes the cast from authoritative state and delegates | `resolveSpellTurn` |
| `gate` | every fail-closed rejection, then slot consumption | `SpellTurnFailureReason`, component/range/slot checks |
| `dc` | save DC and per-target save totals | `saveDc = 10 + spellLevel + castingAbilityModifier` |
| `save` | the d20 saving throw and its automatic results | `savePassed` (natural 1 / natural 20) |
| `damage` | dice, and what the save does to them | NEGATES / HALF / PARTIAL |
| `effects` | conditions applied, updated slots returned | `appliedConditions`, `updatedSpellSlots` |

**Top row — inputs**

| Node | Owns | Source |
|---|---|---|
| `spellRef` | spell level, saving throw, damage, components — **database** | `srd_spells` via `getSpellById` |
| `slots` | the `level_0` … `level_9` ledger | `SpellSlots`, `slotKey` |
| `progression` | base saves and ability modifiers — **sibling module** | `getBaseSaves`, `getAbilityModifier`, `computeSavingThrowModifiers` |

**Bottom row — the branch and the authored input**

| Node | Owns | Source |
|---|---|---|
| `monsterSaves` | static saves copied verbatim, never recomputed | `composeTargetSaves` MONSTER path |
| `conditions` | conditions applied on a failed save | `SpellCondition` |

## Facts the diagram must keep honest

These are the spells-specific traps. Each one is a plausible-looking detail that is **not** true of this code.

- **The engine holds no spell data.** `resolveSpellTurn` takes `spellReference: SpellReferenceType` as a parameter and returns `SPELL_REFERENCE_MISMATCH` if `spellReference.spell_id !== action.spell_id`. There is no lookup inside the engine. The live dispatcher path reads a pre-resolved `state.player_spells.spell_references[spell_id]` map; `rules-engine-api` queries `srd_spells` directly. Do not draw the engine querying the database itself.
- **The engine never applies damage to HP.** `resolveSpell` returns per-target `damage`; `spellExecutor` returns `deltas: []`. Unlike combat there is **no** `applyDamage`/`evaluateHpStatus` stage and no HP edge. Do not copy the combat diagram's injury stage into this one.
- **Range, components, and conditions are engine features with permissive callers.** The component check, range check, and condition application are implemented and tested in `resolveSpell`, but `spellExecutor` hard-codes `in_range: true`, `can_meet_components: true`, and `conditions: []` — its own header calls all three "named deferred non-goals". Show the checks as real and say plainly that the current caller does not yet evaluate them.
- **`cast_defensively` is never read by the engine.** It is a field on `SpellCastAction` retained "for narration/provenance only" (`resolveSpellTurn.ts` line 80), and a test asserts the pass-through explicitly. Casting-provokes-an-attack-of-opportunity lives in `combat/attackOfOpportunity.ts` (`doesSpellcastProvokeAoO`, `resolveCastDefensively`) — the spells module neither imports combat nor is imported by it. There is deliberately **no** spells ↔ combat edge; the relationship is caller-composed, and a card is the honest place for it.
- **`resolveSpellTurn` imports exactly one sibling module: `progression`.** Confirm with the imports before adding another edge.
- **Two save paths, one function:** characters recompute base saves + ability modifiers + caller-aggregated misc; monsters use `static_saves` verbatim and deliberately ignore `save_misc` (a named D5 decision). Do not present monster saves as recomputed.
- **Caster level is the sum of class levels**, and spell level comes from `spellReference.level[casting_class]` — the caller has already decided which class is casting.
- **Rejection counts:** nine typed `SpellTurnFailureReason` values, then three more rejections inside `resolveSpell` (components, range, slots) — twelve fail-closed checks, all before the first `diceRoller` call. An INVALID result returns `updatedSpellSlots: null`, so nothing is consumed.

## Layout notes specific to this diagram

Archetype **B (landscape pipeline)** from the README, same skeleton as the combat child.

- Six columns at pitch 205 (`x` = 40, 245, 450, 655, 860, 1065), rows at `y` = 30, 210, 390; node sizes `[175, 72]`–`[175, 76]`.
- Inputs enter from the **top row** straight down into their targets (`spellRef`→`turn`, `slots`→`gate`, `progression`→`dc`), each with `labelDy: 74`.
- The bottom row carries the monster-save branch and the authored conditions, entering upward with `labelDy: -32`.
- The horizontal middle-row edges carry `labelDy: 60` to put their labels in the row gap below.
- No boundary: the sibling module is flagged by `tag: "sibling module"`.

## Keeping the diagram current

- A new member of `SpellTurnFailureReason`, or a new rejection inside `resolveSpell`, changes the `gate` node and the card's check count.
- A change to the DC formula, the automatic-failure/success rule, or the save-effect handling changes `dc`, `save`, or `damage`.
- A change in `composeTargetSaves` changes `dc` or `monsterSaves`.
- A change in the `SpellSlots` shape or in `slotKey` changes `slots`; a change in how slot consumption is returned changes `effects`.
- If range, components, or conditions stop being deferred in `spellExecutor`, the card's deferral claim is now **false** and must be corrected — that is the most likely way this diagram goes stale quietly.
- If the engine ever applies damage or emits state deltas, add the stage and remove the corresponding card line.
- Bump `meta.repository.revision` to the full 40-hex commit documented.

If `change_ref` is supplied, state which stages it affected and which it did not. If nothing changed, update only the revision — or leave the artifact untouched and say why.

## Non-goals

- Do not touch the other rules-engine diagrams, `docs/architecture/Infrastructure Architecture.md`, or the infrastructure/authentication diagrams.
- Do not change rules-engine implementation, tests, or `IRulesEngine`.
- Do not add, remove, or rename a Rules Engine API action or an SRD claim. A diagram refresh changes no engine behaviour, so `tests/integration/src/vector-matrix/vectors.ts` and `docs/rules-coverage/catalog.json` are **out of scope here** — they follow the action or claim that motivated the change and belong to that change's own task. State this reasoning rather than silently skipping the check.
- Do not widen `meta.viewBox`, add speculative tiers, or draw an edge that is not a real import or a documented caller-composed step.

## Done when

- Every node maps to a real module, function, or data structure; every edge is verified against the imports; every `sources` path and line exists at the pinned revision.
- `validate` passes with `--quality showcase`: 9/9 artifact checks, 0 composition errors, 0 warnings.
- The containment probe passes before delivery — this layout has little headroom, so probe after any copy change.
- `deliver` succeeds and its receipt reports matching specification and artifact SHA-256 values.
- `visual-check` against the exact delivered artifact reports no overflow and readability OK at 1440×900, 1600×1000, 1920×1080, and 2048×1320.
- `meta.repository.revision` matches the commit documented, and only the spec, the artifact, and this diagram's row in `docs/architecture/diagrams/diagram-state.md` are changed — no `visual-check` sidecars remain.
- This diagram's row in `docs/architecture/diagrams/diagram-state.md` records the date and commit actually verified against — not backdated, and equal to `meta.repository.revision` where the schema has it.
- `git diff --check` passes.

If the source and Design 09 disagree about what Engine 2 owns, or a deferral claim cannot be confirmed against the current caller, **stop and ask** rather than guessing.

## Response

Return:

1. The artifact paths changed, and whether this was a refresh-in-place or a re-layout.
2. Each node and edge verified, with the import or source that proves it — and explicitly, which edges are caller-composed rather than imported, and which deferrals remain.
3. The exact commands run with their real outcomes (validation check count, error/warning count, delivery SHA-256 values, `visual-check` per-viewport results). Never report a non-zero exit as success.
4. Browser evidence and perceptual review reported **separately**. If the active model cannot view images, state that the perceptual review was not performed.
5. Anything unresolved, assumed, or deliberately left out of scope.