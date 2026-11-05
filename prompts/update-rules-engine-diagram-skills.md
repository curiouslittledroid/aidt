---
destination: mythical-forge/aidw/prompts/
description: Refresh the skills and stunts child diagram (check resolution subsystems) from current source evidence
argument-hint: "[change-ref]"
---

# Refresh the skills and stunts child diagram

Maintains one artifact: the Archify architecture map of the **skills and stunts** facet's internals. It is a child of `rules-engine-architecture.json`, which shows `Skill & Stunt Fallback` as a single node with the entry point `resolveSkillTurn`. This diagram opens that node up: the fail-closed gate, the skill modifier, the four check modes, opposed resolution, and the separate stunt engine.

This is a **documentation-refresh prompt**. It must not change application, infrastructure, or rules-engine implementation code. If the diagram is wrong, the implementation is the source of truth and the diagram is what gets fixed.

Read `docs/architecture/diagrams/README.md` first. It holds the shared authoring contract — the two budgets, the universal geometry rules, the layout archetypes, the truthfulness rules, and the delivery/freeze protocol. This prompt does not restate it.

## Variables

change_ref: $1

- `change_ref` is optional. If supplied, treat it as the change that motivated this refresh and check whether it altered any stage, rejection, mode, or cross-module edge.
- If omitted, compare `services/rules-engine/src/skills/` and `services/rules-engine/src/stunts/` against what the specification records and reconcile the difference.

## Artifacts (fixed paths — do not create others)

- Candidate specification: `docs/architecture/diagrams/rules-engine-skills-architecture.json`
- Generated artifact: `docs/architecture/diagrams/rules-engine-skills-architecture.html`
- No evidence sidecars are committed. `visual-check` writes a receipt, a contact sheet, and screenshots next to the HTML; delete all of them and quote the delivery SHA-256 values in the response instead. See `docs/architecture/diagrams/README.md`.

Never hand-edit the generated HTML.

## Update in place — do not re-author from scratch

The existing candidate is a **geometrically validated baseline**: `viewBox [1280, 500]`, a three-row landscape layout, 12 components, 10 connections.

**A stale diagram still validates.** `validate` verifies that every `sources` path and line resolves at the pinned revision; it cannot tell you that the claim beside it is still true. A citation that resolves is not a fact that holds. **Re-derive the imports and the caller-composed edges from the source modules before preserving anything** — then keep the diff small, as above.

**Record the verification.** Update the `rules-engine-skills-architecture.json` row in `docs/architecture/diagrams/diagram-state.md` — the UTC date and the full commit SHA you verified against, kept equal to `meta.repository.revision`. A fabricated date there is worse than an empty one.


This layout has **no containment headroom at 1440×900** — the first two drafts each overflowed by a single pixel until the card copy was trimmed. Any addition to the cards or to node text can push it over. Re-run the containment probe after every copy change, and note that trimming the cards raises the projected font size too, because the viewer's scale depends on whether the page fits.

## Evidence sources (read these, in order)

1. `services/rules-engine/src/skills/index.ts` — the module's public surface.
2. `services/rules-engine/src/skills/skillCheck.ts` — the leaf. `computeModifier` (line 117) is the modifier formula, `resolveSkillCheck` (line 141) is the mode switch, `resolveAidAnother` (line 361) is the helper check. It imports nothing but `shared-types`.
3. `services/rules-engine/src/skills/resolveSkillTurn.ts` — the orchestrator. `SkillTurnRejectionReason` (line 177) **is** the rejection vocabulary; the three `resolve*` inner functions are the three action paths; `MAX_OPPOSED_REROLLS` (line 241) bounds the re-roll loop.
4. `services/rules-engine/src/stunts/resolveStunt.ts` — a fully self-contained leaf with **no imports at all**. Its header quotes Design 09 §5.3 and Design 06 §4C.
5. `services/player-api/src/dispatcher/skillExecutor.ts` — the live caller; shows which state fields are read and how absent references fail closed.
6. `services/rules-engine-api/src/validation.ts` and `util/seedDice.ts` — the action list, which is the evidence for what the router can reach.
7. `docs/specs/Design 09 - Game Rules Engines.md` §3 Engine 3 (opposed checks, synergy bonuses) and §5.3 (the stunt fallback), and `docs/specs/Design 06 - Combat.md` §4C.

## Current baseline structure

**Middle row — the check pipeline, left to right**

| Node | Owns | Entry point |
|---|---|---|
| `turn` | dispatches `USE_SKILL` / `ABILITY_CHECK` / `AID_ANOTHER` | `resolveSkillTurn` |
| `gate` | every fail-closed rejection, before any dice | `SkillTurnRejectionReason` |
| `modifier` | ranks + ability modifier + synergy + misc | `computeModifier` |
| `mode` | the four request modes | `SkillCheckMode` |
| `resolve` | d20 vs DC, or opposed d20 vs d20 | `resolveSkillCheck` |
| `result` | success, tie, re-roll signal, deltas | `SkillTurnResult` |

**Top row — inputs and the other participant**

| Node | Owns | Source |
|---|---|---|
| `actor` | ability scores, skill ranks, skill references — **sibling-free** | `SkillTurnActorState` |
| `progression` | the ability modifier — **sibling module** | `getAbilityModifier` |
| `opponent` | the other side of `OPPOSED`, and the primary of `AID_ANOTHER` | `SkillActionRequest` |

**Bottom row — the parallel paths**

| Node | Owns | Source |
|---|---|---|
| `aid` | the helper's check, bonus folded into the primary | `resolveAidAnother` |
| `stuntCheck`, `stuntAgg` | the separate stunt engine, tagged `router-only` | `resolveStunt` |

## Facts the diagram must keep honest

- **There is no SRD-database node in this diagram, deliberately.** In the spells child, `spellReference` is a direct engine parameter, so a `srd_spells` node is real. Here the skill reference arrives *inside* `SkillTurnActorState.skill_references`, read from `player_skills.skill_references` in authoritative state. `getSkillById`/`srd_skills` exists but is exposed only through the rules-engine-api router, and **no code in this repo hydrates player state from it**. Drawing an `srd_skills → actor` edge would invent that pipeline. Keep it out unless you can point at the hydration code.
- **The engine has no `TAKE_10` mode.** `skillModeToRequestMode` maps `TAKE_10` onto the engine's `PASSIVE`, which is `10 + modifier`. Three of the four modes roll no die at all: `PASSIVE`, `TAKE_10`, and `TAKE_20`. Only `ACTIVE` and `OPPOSED` roll.
- **Opposed checks have a three-way outcome**, and it is the subtlest rule here: on equal totals the higher *modifier* wins; if the modifiers are also equal the SRD says "roll again", and the caller must re-roll both sides. `resolveSkillTurn` consumes the leaf's `needsReroll` in a loop bounded by `MAX_OPPOSED_REROLLS = 1000`, and **throws** when it is exhausted — that is a caller/stub bug, not a game-state rejection.
- **`TRAINED_ONLY_BLOCKED` also applies to the Aid Another helper**, not just the acting character. The source marks this as an interpretation decision that goes beyond the roadmap.
- **`equipped_gear` is accepted but never consumed.** `SkillTurnActorState` documents this: the armor-check-penalty utility does not exist, so this orchestrator must not read the field or compute a penalty. Caller-aggregated penalties arrive via `misc_modifier`. Do not draw an armor/speed input.
- **`state_deltas` is always `[]`.** No skill action mutates a persisted scalar, and the Aid Another bonus is consumed inside the same call.
- **Circumstance modifiers are per-side:** `misc_modifier` is the actor/helper side, while `opponent_misc_modifier` and `primary_misc_modifier` carry the other side. A single shared field would misattribute the helper's tools to the primary's check.
- **The stunt fallback is not wired into live play.** `resolveStunt` is reachable only through the rules-engine-api router action list (`validation.ts`, `seedDice.ts`). Nothing in `player-api` emits `CUSTOM_STUNT` or calls `resolveStunt` — a repo-wide search for both returns nothing. The intended trigger is Design 09 §5.3's Intent Parser flag, which does not exist yet, so **do not add a "CUSTOM_STUNT" or intent-parser node**: that would model a design proposal rather than the code.
- **`resolveStunt` imports nothing**, and `stunt*` and `skill*` do not import each other. They are parallel engines that happen to share a facet in the parent diagram.
- **`AID_ANOTHER_BONUS = 2` lives in `combat/attack.ts`** and is the *combat* Aid Another constant. The skill-side `resolveAidAnother` computes its own bonus inside `skillCheck.ts` and does not import combat. There is no skills → combat edge.

## Layout notes specific to this diagram

Archetype **B (landscape pipeline)** from the README, same skeleton as the combat and spells children.

- Six columns at pitch 205 (`x` = 40, 245, 450, 655, 860, 1065), rows at `y` = 30, 210, 380; node sizes `[175, 72]`–`[175, 76]`.
- Inputs enter from the **top row** (`actor`→`turn`, `progression`→`modifier`, `opponent`→`resolve`) and the bottom row (`aid`→`modifier`) straight into their targets; top-row edges use `labelDy: 74`, the upward one `labelDy: -32`.
- Horizontal middle-row edges use `labelDy: 60`. The bottom-row `stuntCheck`→`stuntAgg` edge uses `labelDy: -48` to lift its label into the row gap above.
- **There is deliberately no boundary.** A region wrapping the two stunt nodes was tried and dropped: its title rail collided with the internal `conditions` edge label, and shrinking the pad to avoid it left no viewBox margin. The router-only fact is carried by both stunt nodes' `tag` and by a card instead.

## Keeping the diagram current

- A new `SkillTurnRejectionReason` member changes `gate` and the card's count of seven.
- A change to `computeModifier`'s terms changes `modifier`; a new `SkillCheckMode` member changes `mode` and the "four ways" card.
- A change to the tie-break or to `MAX_OPPOSED_REROLLS` changes `resolve` and the opposed card line.
- A change in the Aid Another flow (who is pre-validated, how the bonus folds in) changes `aid`.
- A change to `StuntComponent`, the default DC, or the condition dedupe changes the stunt pair.
- **If the stunt fallback becomes reachable from live play** — an intent parser emitting `CUSTOM_STUNT`, or `player-api` calling `resolveStunt` — then the `router-only` tags and the corresponding card line are now **false**. That is the most likely way this diagram goes stale, and it requires an actual re-layout decision, not just a tag edit.
- **If `equipped_gear` starts being consumed**, remove that card line.
- Bump `meta.repository.revision` to the full 40-hex commit documented.

If `change_ref` is supplied, state which stages it affected and which it did not. If nothing changed, update only the revision — or leave the artifact untouched and say why.

## Non-goals

- Do not touch the other rules-engine diagrams, `docs/architecture/Infrastructure Architecture.md`, or the infrastructure/authentication diagrams.
- Do not change rules-engine implementation, tests, or `IRulesEngine`.
- Do not add, remove, or rename a Rules Engine API action or an SRD claim. A diagram refresh changes no engine behaviour, so `tests/integration/src/vector-matrix/vectors.ts` and `docs/rules-coverage/catalog.json` are **out of scope here** — they follow the action or claim that motivated the change and belong to that change's own task. State this reasoning rather than silently skipping the check.
- Do not add a `CUSTOM_STUNT` or intent-parser node, an SRD-database edge, or an armor-check input. All three would describe something the code does not do.
- Do not widen `meta.viewBox` or draw an edge that is not a real import or a documented caller-composed step.

## Done when

- Every node maps to a real module, function, or data structure; every edge is verified against the imports; every `sources` path and line exists at the pinned revision.
- `validate` passes with `--quality showcase`: 9/9 artifact checks, 0 composition errors, 0 warnings.
- The containment probe passes before delivery — this layout has essentially no headroom, so probe after any copy change.
- `deliver` succeeds and its receipt reports matching specification and artifact SHA-256 values.
- `visual-check` against the exact delivered artifact reports no overflow and readability OK at 1440×900, 1600×1000, 1920×1080, and 2048×1320.
- `meta.repository.revision` matches the commit documented, and only the spec, the artifact, and this diagram's row in `docs/architecture/diagrams/diagram-state.md` are changed — no `visual-check` sidecars remain.
- This diagram's row in `docs/architecture/diagrams/diagram-state.md` records the date and commit actually verified against — not backdated, and equal to `meta.repository.revision` where the schema has it.
- `git diff --check` passes.

If the source and Design 09 disagree about what Engine 3 owns, or the ask would require modelling a rule the code does not implement, **stop and ask** rather than guessing.

## Response

Return:

1. The artifact paths changed, and whether this was a refresh-in-place or a re-layout.
2. Each node and edge verified, with the import or source that proves it — and explicitly, which edges are caller-composed rather than imported, and which claims are deferrals.
3. The exact commands run with their real outcomes (validation check count, error/warning count, delivery SHA-256 values, `visual-check` per-viewport results). Never report a non-zero exit as success.
4. Browser evidence and perceptual review reported **separately**. If the active model cannot view images, state that the perceptual review was not performed.
5. Anything unresolved, assumed, or deliberately left out of scope.