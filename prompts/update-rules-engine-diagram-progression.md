---
description: Refresh the progression child diagram (shared kernel) from current source evidence
argument-hint: "[change-ref]"
---

# Refresh the progression child diagram

Maintains one artifact: the Archify architecture map of the **character progression and attribute** facet. It is a child of `rules-engine-architecture.json`, which shows `Progression & Attributes` as a single node tagged *shared kernel*. This diagram opens that node up: the six pure calculators, the class tables they read, and the three d20 engines that compose them.

This is a **documentation-refresh prompt**. It must not change application, infrastructure, or rules-engine implementation code. If the diagram is wrong, the implementation is the source of truth and the diagram is what gets fixed.

Read `docs/architecture/diagrams/README.md` first. It holds the shared authoring contract — the two budgets, the universal geometry rules, the layout archetypes, the truthfulness rules, and the delivery/freeze protocol. This prompt does not restate it.

## Variables

change_ref: $1

- `change_ref` is optional. If supplied, treat it as the change that motivated this refresh and check whether it altered a formula, a class table, or a consumer.
- If omitted, compare `services/rules-engine/src/progression/` and its consumers against what the specification records.

## Artifacts (fixed paths — do not create others)

- Candidate specification: `docs/architecture/diagrams/rules-engine-progression-architecture.json`
- Generated artifact: `docs/architecture/diagrams/rules-engine-progression-architecture.html`
- No evidence sidecars are committed. `visual-check` writes a receipt, a contact sheet, and screenshots next to the HTML; delete all of them and quote the delivery SHA-256 values in the response instead. See `docs/architecture/diagrams/README.md`.

Never hand-edit the generated HTML.

## Update in place — do not re-author from scratch

The existing candidate is a **geometrically validated baseline**: `viewBox [1280, 560]`, 8 components, 7 connections, three cards.

**A stale diagram still validates.** `validate` verifies that every `sources` path and line resolves at the pinned revision; it cannot tell you that the claim beside it is still true. A citation that resolves is not a fact that holds. **Re-derive the imports and the caller-composed edges from the source modules before preserving anything** — then keep the diff small, as above.

**Record the verification.** Update the `rules-engine-progression-architecture.json` row in `docs/architecture/diagrams/diagram-state.md` — the UTC date and the full commit SHA you verified against, kept equal to `meta.repository.revision`. A fabricated date there is worse than an empty one.


**This diagram is deliberately not a pipeline.** Every other child in this family is a left-to-right pipeline of stages, because those facets are processes. Progression is a *library*: its functions have no ordering, no shared gate, and no orchestrator. Do not "fix" the shape into a pipeline, and do not add a stage-to-stage flow that the code does not have. If you find yourself wanting an orchestrator node, check whether one exists first — it does not today.

The containment margin is thin: the first draft had 4 cards totalling 14 items and overflowed by 293px at 1440×900. **Three cards of three items each is the envelope.** Adding card content, or widening `meta.viewBox`, will break containment.

## Evidence sources (read these, in order)

1. `services/rules-engine/src/progression/index.ts` — the module's public surface; the authoritative list of calculators.
2. The calculators themselves: `modifier.ts` (line 12), `bab.ts` (lines 20 and 43), `size.ts` (line 36), `saves.ts` (line 71), `hp.ts` (line 43), `skill.ts` (line 20). Each header states its SRD formula and its citation.
3. **The in-engine consumer imports — this is the load-bearing search.** Run it and trust the output over any recollection (including this file's):

   ```bash
   grep -rn "from '\.\./progression" --include=*.ts services/rules-engine/src --exclude-dir=__tests__
   ```

   For consumers outside the engine, add `services/player-api/src` and `services/rules-engine-api/src`.
4. `docs/specs/Design 09 - Game Rules Engines.md` §3 Engine 5 and `docs/specs/Design 06 - Combat.md` §3C.

## Current baseline structure

**Consumer band (top)** — one full-width node naming the three d20 engines that compose this kernel.

**Middle row — the calculators, left to right**

| Node | Owns | Entry point |
|---|---|---|
| `ability` | `floor((score − 10) / 2)` — the only universal calculator | `getAbilityModifier` |
| `bab` | GOOD = level, AVERAGE = floor(level × 3/4), POOR = floor(level / 2) | `getBAB`, `getBABProgression` |
| `size` | FINE +8 … COLOSSAL −8, applied to attack and AC | `getSizeModifier` |
| `saves` | GOOD = 2 + floor(level/2), POOR = floor(level/3); multiclass sums base | `getBaseSaves`, `computeSavingThrowModifiers` |
| `hp` | max hit die + CON at level 1, then roll + CON, minimum 1 | `getHitDie`, `rollHPGain` |
| `ranks` | level + 3 class, half that cross-class | `getMaxSkillRanks`, `isSkillAtCap` |

**Bottom row** — `tables`, the static class→progression maps, fanning up into `bab`, `saves` and `hp`.

## Facts the diagram must keep honest

- **The consumer set is small and asymmetric, and it is easy to overstate.** Verified in-engine consumers (`--exclude-dir=__tests__`):
  | Consumer | Composes |
  |---|---|
  | `combat/resolveCombatTurn.ts` | `getAbilityModifier`, `getBAB`, `getSizeModifier` |
  | `combat/damage.ts` | `getAbilityModifier` |
  | `spells/resolveSpellTurn.ts` | `getAbilityModifier`, `getBaseSaves`, `computeSavingThrowModifiers` |
  | `skills/resolveSkillTurn.ts` | `getAbilityModifier` — **only** this |

  Do not add a consumer edge without re-running the grep.
- **`rollHPGain` appears in `combat/attack.ts`, `combat/attackOfOpportunity.ts` and `combat/initiative.ts` — all three are comments**, not imports ("matching B2's `rollHPGain`"). A bare word-match on a function name is not a dependency. Check for a matching `import`.
- **`getBABProgression`, `getBaseSaveBonus`, `getClassSaveProgression`, `getHitDie`, `rollHPGain`, `getMaxSkillRanks` and `isSkillAtCap` have no in-engine consumer at all.** They are reachable only through `IRulesEngine` and the rules-engine-api router. **No level-up flow exists** in `player-api`, so nothing calls them in live play. They are implemented and tested — this is a missing caller, not a stub. That is the `no live caller` tag on `hp` and `ranks` and the third card, and it is the likeliest thing to go stale.
- **The class tables are static in-code records, not database tables.** `bab.ts` (line 20) holds the class→BAB map and `hp.ts` (line 19) the class→hit-die map, both keyed by lowercased class name. Do not type the `tables` node as `database`, and do not draw an SRD database node — unlike spells, there is no `srd_*` lookup in this path.
- **Progression imports nothing.** Every file imports only `@mythical-forge/shared-types` or a sibling within `progression/`. It is a leaf; the arrows must point out of it, never into it from another engine.
- **`size` is a fixed nine-entry lookup**, not derived from level or class, so it has no input in this diagram. Do not invent one.
- **Model what the code does:** `saves.ts` also carries `getBaseSaveBonus` and `getClassSaveProgression`, which the facade exposes but no engine uses. They belong in the "no consumer" note, not as separate nodes.

## Layout notes specific to this diagram

This uses **neither** README archetype exactly; it is a wide-band variant, and the deviations were forced by real diagnostics.

- Two rows: a full-width consumer band at `y = 20` (`size [1240, 72]`) and six calculators at `y = 250` (pitch 205, width 175), with `tables` at `y = 440`.
- **The consumer band is wide on purpose.** The four calculator→consumer edges rise into its bottom; a wide target spreads the ports so the labels separate by ~205px. A narrow single node made every label collide.
- **Do not add `labelDy` to the four upward edges.** Their default anchor already lands mid-gap. `labelDy: -74` (the value that is correct for the *downward* fans in the sibling diagrams) pushed the labels up into the consumer band and produced four node-overlap errors. The default is right here.
- Two of those four carry an explicit `labelAt` (`size-to-consumers` at `[537, 200]`, `saves-to-consumers` at `[742, 200]`) because other routes pass through the lane band above them.
- The three `tables` edges use `labelSegment: 2` (the README's fan-out pattern) — the same control that makes the parent diagram's fan work, here applied upward.
- **Sublabel length sets the readability ceiling.** `saves` had to drop its formula to `GOOD and POOR progressions` because a 36-character sublabel in a 175px node shrank `sourceFontPx` to 7.9, and `scale × sourceFontPx` fell below the gate. The formula lives in the card instead. If you lengthen any calculator sublabel, expect the readability gate to fail and check `sourceFontPx` in the diagnostic evidence.

## Keeping the diagram current

- A formula change in `modifier.ts`, `bab.ts`, `saves.ts`, `hp.ts`, `skill.ts` or `size.ts` changes that node and usually the formula card.
- A change to a class→progression map changes `tables`; a new class added to the SRD maps is a `tables` change, not a new node.
- A new in-engine consumer — or a removed one — changes the consumer band, the edge set, and the "who composes what" card. Re-run the grep.
- **A level-up flow appearing in `player-api` makes the `no live caller` tags and the third card false.** That is the most likely staleness: progression's HP and rank-cap calculators are complete and waiting for a caller.
- If progression ever imports another engine, the "imports no other engine" card line is false.
- Bump `meta.repository.revision` to the full 40-hex commit documented.

If `change_ref` is supplied, state which calculators it affected and which it did not. If nothing changed, update only the revision — or leave the artifact untouched and say why.

## Non-goals

- Do not touch the other rules-engine diagrams, `docs/architecture/Infrastructure Architecture.md`, or the infrastructure/authentication diagrams.
- Do not change rules-engine implementation, tests, or `IRulesEngine`.
- Do not add, remove, or rename a Rules Engine API action or an SRD claim. A diagram refresh changes no engine behaviour, so `tests/integration/src/vector-matrix/vectors.ts` and `docs/rules-coverage/catalog.json` are **out of scope here** — they follow the action or claim that motivated the change and belong to that change's own task. State this reasoning rather than silently skipping the check.
- Do not add a level-up orchestrator, an XP/experience node, an SRD-database node, or a stage-to-stage pipeline. None of them exist.
- Do not widen `meta.viewBox` or draw an edge that is not a real import.

## Done when

- Every node maps to a real calculator or static table; every consumer edge is verified by the grep above; every `sources` path and line exists at the pinned revision.
- `validate` passes with `--quality showcase`: 9/9 artifact checks, 0 composition errors, 0 warnings.
- The containment probe passes before delivery — this layout has almost no card headroom.
- `deliver` succeeds and its receipt reports matching specification and artifact SHA-256 values.
- `visual-check` against the exact delivered artifact reports no overflow and readability OK at 1440×900, 1600×1000, 1920×1080, and 2048×1320.
- `meta.repository.revision` matches the commit documented, and only the spec, the artifact, and this diagram's row in `docs/architecture/diagrams/diagram-state.md` are changed — no `visual-check` sidecars remain.
- This diagram's row in `docs/architecture/diagrams/diagram-state.md` records the date and commit actually verified against — not backdated, and equal to `meta.repository.revision` where the schema has it.
- `git diff --check` passes.

If the source and Design 09 §3 Engine 5 disagree about what the kernel owns, or a consumer edge cannot be confirmed with a real `import`, **stop and ask** rather than guessing.

## Response

Return:

1. The artifact paths changed, and whether this was a refresh-in-place or a re-layout.
2. Each calculator and each consumer edge, with the grep output or import that proves it — and explicitly, which functions have no in-engine consumer.
3. The exact commands run with their real outcomes (validation check count, error/warning count, delivery SHA-256 values, `visual-check` per-viewport results). Never report a non-zero exit as success.
4. Browser evidence and perceptual review reported **separately**. If the active model cannot view images, state that the perceptual review was not performed.
5. Anything unresolved, assumed, or deliberately left out of scope.