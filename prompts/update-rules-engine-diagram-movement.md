---
description: Refresh the movement and spatial child diagram (grid subsystems) from current source evidence
argument-hint: "[change-ref]"
---

# Refresh the movement and spatial child diagram

Maintains one artifact: the Archify architecture map of the **movement, range and spatial** facet's internals. It is a child of `rules-engine-architecture.json`, which shows `Movement & Spatial` as a single node with the entry point `validateMovement`. This diagram opens that node up: illegal-space recovery, the validation precedence, the grid model, pathfinding, path cost, the speed budget, and the cover/flanking geometry that combat consumes.

This is a **documentation-refresh prompt**. It must not change application, infrastructure, or rules-engine implementation code. If the diagram is wrong, the implementation is the source of truth and the diagram is what gets fixed.

Read `docs/architecture/diagrams/README.md` first. It holds the shared authoring contract — the two budgets, the universal geometry rules, the layout archetypes, the truthfulness rules, and the delivery/freeze protocol. This prompt does not restate it.

## Variables

change_ref: $1

- `change_ref` is optional. If supplied, treat it as the change that motivated this refresh and check whether it altered any stage, rejection, or cross-module edge.
- If omitted, compare `services/rules-engine/src/movement/` against what the specification records and reconcile the difference.

## Artifacts (fixed paths — do not create others)

- Candidate specification: `docs/architecture/diagrams/rules-engine-movement-architecture.json`
- Generated artifact: `docs/architecture/diagrams/rules-engine-movement-architecture.html`
- No evidence sidecars are committed. `visual-check` writes a receipt, a contact sheet, and screenshots next to the HTML; delete all of them and quote the delivery SHA-256 values in the response instead. See `docs/architecture/diagrams/README.md`.

Never hand-edit the generated HTML.

## Update in place — do not re-author from scratch

The existing candidate is a **geometrically validated baseline**: `viewBox [1280, 500]`, a three-row landscape layout, 10 components, 8 connections.

**A stale diagram still validates.** `validate` verifies that every `sources` path and line resolves at the pinned revision; it cannot tell you that the claim beside it is still true. A citation that resolves is not a fact that holds. **Re-derive the imports and the caller-composed edges from the source modules before preserving anything** — then keep the diff small, as above.

**Record the verification.** Update the `rules-engine-movement-architecture.json` row in `docs/architecture/diagrams/diagram-state.md` — the UTC date and the full commit SHA you verified against, kept equal to `meta.repository.revision`. A fabricated date there is worse than an empty one.


As with the skills child, the cards are the containment risk: the first two drafts overflowed 1440×900 by 23–33px until the card copy was shortened. **Adding a card line can break containment**, and trimming it raises the projected font size for free, because the viewer's scale depends on whether the page fits. Probe after any copy change.

## Evidence sources (read these, in order)

1. `services/rules-engine/src/movement/index.ts` — the module's public surface.
2. `services/rules-engine/src/movement/movement.ts` — the header enumerates the five responsibilities and the SRD citations. `GridMap` (line 27) is the passability/terrain model, `MovementRejectionReason` (line 65) **is** the rejection vocabulary, `computePathCostInFeet` (line 182) is the cost rule, `findPath` (line 260) is the pathfinder, `resolveIllegalSpace` (line 497) is recovery, `validateMovement` (line 565) is the entry point and its header gives the fixed precedence order.
3. `services/rules-engine/src/movement/spatial.ts` — `getCoverBonus` (line 212) and `getFlankingBonus` (line 259); the header records the scoping decisions and what is out of scope.
4. `services/player-api/src/dispatcher/movementExecutor.ts` — the live caller. **This file is the authority on call order**; read the numbered steps, not the function names.
5. `services/rules-engine/src/combat/resolveCombatTurn.ts` (line 36) — the only consumer of cover and flanking.
6. `docs/specs/Design 09 - Game Rules Engines.md` §3 Engine 4 and `docs/specs/Design 05 §4B` (SRD 3.5 tactical grid integration).

## Current baseline structure

**Middle row — the movement pipeline, left to right**

| Node | Owns | Entry point |
|---|---|---|
| `recover` | illegal-space recovery (SRD "Accidentally Ending Movement in an Illegal Space") | `resolveIllegalSpace` |
| `validate` | the six rejections in fixed precedence | `validateMovement` |
| `grid` | passability, terrain, occupancy and the passable overrides | `GridMap` |
| `path` | Dijkstra over `(coordinate, diagonals % 2)` | `findPath` |
| `cost` | exact SRD cost in feet | `computePathCostInFeet` |
| `budget` | the verdict, and the Run restrictions | `MovementRejectionReason` |

**Top row** — `request` (start, target, speed, mode) into `validate`.

**Bottom row** — the spatial cluster: `cover` → `combat` ← `flank`.

## Facts the diagram must keep honest

- **Recovery runs before validation, not after.** `movementExecutor` calls `engine.resolveIllegalSpace(currentSquare, requestedTarget, grid)` and then validates **the square it resolved to**, not the requested one. The intuitive "move, then fix it up" ordering is wrong here. This is the diagram's headline fact and the easiest one to get backwards.
- **Movement and spatial roll no dice at all.** Neither module has a `diceRoller` parameter — there is no dice anywhere in this engine. Do not copy the combat/spells/skills "fail-closed before any dice" framing; here the whole engine is deterministic.
- **Cover and flanking have exactly one consumer: `combat/resolveCombatTurn.ts`.** The movement pipeline itself never calls them, which is why the bottom row is a separate cluster joined to `combat` rather than to `budget`.
- **`world/worldGraph.ts` does not import movement** — it only mentions `movement/movement.ts` in a comment. There is no movement ↔ world edge and no movement ↔ vision edge: neither `vision.ts` nor `worldGraph.ts` has a single import.
- **No `isSquareThreatened` or attack-of-opportunity edge.** Those live in `combat/attackOfOpportunity.ts`, which does not import movement. The threatened-square logic is combat's.
- **Diagonal corner-cutting is prevented**, and the pathfinder's search state is `(coordinate, diagonalCount % 2)` — that parity is what makes the returned path match `computePathCostInFeet`'s alternating 1-2-1-2 rule. Both facts are load-bearing and easy to drop.
- **Cost details that are easy to flatten:** an orthogonal step is 5 ft; difficult terrain doubles it to 10 ft; a diagonal into difficult terrain is a **flat 15 ft regardless of alternation position**; very large helpless squares cost exactly like difficult terrain while normal helpless squares cost nothing extra.
- **Passable-override semantics:** a square in `blocked` is still passable if it is also in `friendlySquares`, `helplessSquares`, or `veryLargeHelplessSquares`. Do not present `blocked` as absolute.
- **The live executor hard-codes `mode: 'MOVE'`.** `DOUBLE_MOVE` and `RUN` (and therefore `RUN_NOT_STRAIGHT_LINE` and `RUN_OVER_DIFFICULT_TERRAIN`) are reachable from the engine and the router but not from live play. Say so rather than implying all three modes are in use.
- **`spatial.ts` consumes caller-mapped squares.** Design 05 §2's `RoomObject` has no coordinates, so the caller is responsible for mapping a `cover_type: "HALF_COVER"` object onto the grid squares it occupies. The engine never sees a room object.
- **Scoped out on purpose, do not draw them:** Improved Cover (+8, three or four blocked lines), reach weapons and large creatures for flanking, and the full threatening-status check. Cover is only `NONE` or `HALF_COVER`.

## Layout notes specific to this diagram

Archetype **B (landscape pipeline)** from the README, same skeleton as the other children.

- Six columns at pitch 205 (`x` = 40, 245, 450, 655, 860, 1065), rows at `y` = 30, 210, 380; node sizes `[175, 72]`–`[175, 76]`.
- The movement pipeline is the middle row; `request` enters from the top (`labelDy: 74`); middle-row horizontals use `labelDy: 60`; the bottom-row cluster uses `labelDy: -48`.
- **The spatial sink sits in the middle of its cluster**, not at the end: `cover` (c2) → `combat` (c3) ← `flank` (c4). Placing `combat` last made `cover → combat` cross `flank` and produced both an `edge-through-node` error and a `micro-segment` error. Fan-in from both sides is the layout that works; if you add a third spatial node, keep the sink adjacent to every source.
- No boundary: the module split is carried by node labels and tags.

## Keeping the diagram current

- A new `MovementRejectionReason` member, or a change to the precedence order in `validateMovement`, changes `budget` and the rejection card.
- A change to the cost rules, the 1-2-1-2 alternation, or the difficult-terrain diagonal rule changes `cost`.
- A change to the pathfinder's neighbour set, its parity state, or the corner-cutting rule changes `path`.
- A change to `GridMap` — a new field, or different override semantics — changes `grid`.
- A change to `resolveIllegalSpace`'s tie-break (last legal square, then lowest y then lowest x) changes `recover` and the recovery card.
- A change to `CoverLevel`, the cover bonus, the flanking adjacency requirement, or the bonus value changes the bottom cluster.
- **If recovery stops running before validation**, or if `movementExecutor` stops hard-coding `MOVE`, then the corresponding card line is now false — both are stated as current-caller behaviour, so they are the likeliest silent staleness here.
- If a second consumer of cover/flanking appears, the `combat` node's `only consumer` tag becomes false.
- Bump `meta.repository.revision` to the full 40-hex commit documented.

If `change_ref` is supplied, state which stages it affected and which it did not. If nothing changed, update only the revision — or leave the artifact untouched and say why.

## Non-goals

- Do not touch the other rules-engine diagrams, `docs/architecture/Infrastructure Architecture.md`, or the infrastructure/authentication diagrams.
- Do not change rules-engine implementation, tests, or `IRulesEngine`.
- Do not add, remove, or rename a Rules Engine API action or an SRD claim. A diagram refresh changes no engine behaviour, so `tests/integration/src/vector-matrix/vectors.ts` and `docs/rules-coverage/catalog.json` are **out of scope here** — they follow the action or claim that motivated the change and belong to that change's own task. State this reasoning rather than silently skipping the check.
- Do not add vision, world-graph, overland-travel, or attack-of-opportunity nodes. Those belong to other facets and, in the AoO case, to combat.
- Do not widen `meta.viewBox` or draw an edge that is not a real import or a documented caller-composed step.

## Done when

- Every node maps to a real function, type, or module; every edge is verified against the imports or against `movementExecutor`'s numbered steps; every `sources` path and line exists at the pinned revision.
- `validate` passes with `--quality showcase`: 9/9 artifact checks, 0 composition errors, 0 warnings.
- The containment probe passes before delivery — this layout has no headroom at 1440×900.
- `deliver` succeeds and its receipt reports matching specification and artifact SHA-256 values.
- `visual-check` against the exact delivered artifact reports no overflow and readability OK at 1440×900, 1600×1000, 1920×1080, and 2048×1320.
- `meta.repository.revision` matches the commit documented, and only the spec, the artifact, and this diagram's row in `docs/architecture/diagrams/diagram-state.md` are changed — no `visual-check` sidecars remain.
- This diagram's row in `docs/architecture/diagrams/diagram-state.md` records the date and commit actually verified against — not backdated, and equal to `meta.repository.revision` where the schema has it.
- `git diff --check` passes.

If the source and Design 05/09 disagree about a movement rule, or an ordering claim cannot be confirmed against `movementExecutor`, **stop and ask** rather than guessing.

## Response

Return:

1. The artifact paths changed, and whether this was a refresh-in-place or a re-layout.
2. Each node and edge verified, with the import or source that proves it — and explicitly, which edges are caller-composed rather than imported, and which behaviours are engine-only rather than live.
3. The exact commands run with their real outcomes (validation check count, error/warning count, delivery SHA-256 values, `visual-check` per-viewport results). Never report a non-zero exit as success.
4. Browser evidence and perceptual review reported **separately**. If the active model cannot view images, state that the perceptual review was not performed.
5. Anything unresolved, assumed, or deliberately left out of scope.