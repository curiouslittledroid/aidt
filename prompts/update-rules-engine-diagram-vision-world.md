---
description: Refresh the vision and world child diagram (two independent models) from current source evidence
argument-hint: "[change-ref]"
---

# Refresh the vision and world child diagram

Maintains one artifact: the Archify architecture map of the **vision and world** facet. It is a child of `rules-engine-architecture.json`, which shows a single `Vision & World Graph` node. This diagram opens that node up into its two — genuinely unrelated — halves: the local light/visibility model and the overland travel graph.

This is a **documentation-refresh prompt**. It must not change application, infrastructure, or rules-engine implementation code. If the diagram is wrong, the implementation is the source of truth and the diagram is what gets fixed.

Read `docs/architecture/diagrams/README.md` first. It holds the shared authoring contract — the two budgets, the universal geometry rules, the layout archetypes, the truthfulness rules, and the delivery/freeze protocol. This prompt does not restate it.

## Variables

change_ref: $1

- `change_ref` is optional. If supplied, treat it as the change that motivated this refresh and check whether it altered a formula, a light or terrain constant, or a caller.
- If omitted, compare `services/rules-engine/src/vision/` and `services/rules-engine/src/world/` against what the specification records.

## Artifacts (fixed paths — do not create others)

- Candidate specification: `docs/architecture/diagrams/rules-engine-vision-world-architecture.json`
- Generated artifact: `docs/architecture/diagrams/rules-engine-vision-world-architecture.html`
- No evidence sidecars are committed. `visual-check` writes a receipt, a contact sheet, and screenshots next to the HTML; delete all of them and quote the delivery SHA-256 values in the response instead. See `docs/architecture/diagrams/README.md`.

Never hand-edit the generated HTML.

## Update in place — do not re-author from scratch

The existing candidate is a **geometrically validated baseline**: `viewBox [1100, 440]`, 8 components, 6 connections, two region boundaries, three cards.

**A stale diagram still validates.** `validate` verifies that every `sources` path and line resolves at the pinned revision; it cannot tell you that the claim beside it is still true. A citation that resolves is not a fact that holds. **Re-derive the imports and the caller-composed edges from the source modules before preserving anything** — then keep the diff small, as above.

**Record the verification.** Update the `rules-engine-vision-world-architecture.json` row in `docs/architecture/diagrams/diagram-state.md` — the UTC date and the full commit SHA you verified against, kept equal to `meta.repository.revision`. A fabricated date there is worse than an empty one.


**This diagram is two clusters, not one flow, and that is the point.** `vision.ts` and `worldGraph.ts` share no code, no types, and no imports. The parent diagram merges them into one node for canvas width, not because they belong together. Do not join the clusters, do not add a stage between them, and do not imply a shared pipeline.

**The canvas is deliberately narrow and flat, and both dimensions matter.** These two budgets pull against each other here, and only one combination satisfied both:

| viewBox | aspect | readability (`minText` @1440) | containment @1440 |
|---|---|---|---|
| 1280 × 530 | 0.41 | 6.39 — passes, no margin | passes |
| 1100 × 510 | 0.46 | 7.61 — comfortable | **fails** (945 > 900) |
| **1100 × 440** | **0.40** | **7.98** | **passes** |

`minText` is `scale × sourceFontPx` where `scale ≈ 930 / viewBoxWidth` and `sourceFontPx` saturates around 9, so **widening the canvas is what costs readability** and **heightening it is what costs containment**. Shortening node text does *not* help once the font has saturated — confirm that before editing copy, because it looks like an obvious lever and is not.

## Evidence sources (read these, in order)

1. `services/rules-engine/src/vision/index.ts` and `services/rules-engine/src/world/index.ts` — the two public surfaces.
2. `services/rules-engine/src/vision/vision.ts` — the header records the scope boundary (no coordinates in the room schema, radial-only sources, magical darkness out of scope). `LightLevel` (line 50), `LightSource` (line 69), `assessLighting` (line 188), `getVisibleEntities` (line 278).
3. `services/rules-engine/src/world/worldGraph.ts` — `TERRAIN_MULTIPLIER` (line 50), `MacroWorldGraph` (line 84), `findShortestPath` (line 129), `computeTravelTime` (line 223).
4. **The consumer search — run it, do not recall it:**
   ```bash
   grep -rn "from '\.\./vision\|from '\.\./world" --include=*.ts services/rules-engine/src --exclude-dir=__tests__
   grep -rn "assessLighting\|getVisibleEntities\|findShortestPath\|computeTravelTime" --include=*.ts services/player-api/src
   ```
5. `docs/specs/Design 05 §2–§3` (room schema, light-level categories, vision traits, light source dynamics), `docs/specs/Design 07 §2B` (directed `graph_edges`), and `docs/specs/Design 03` (lazy world simulation).

## Current baseline structure

**Vision cluster** (left, inside a region boundary)

| Node | Owns | Entry point |
|---|---|---|
| `light` | caller-resolved light radii and the viewer's vision trait | `LightSource`, `VisionType` |
| `assess` | the light ladder: BRIGHT → SHADOWY → DARKNESS with and without darkvision | `assessLighting` |
| `visible` | a per-entity visibility verdict | `getVisibleEntities` |
| `ambient` | the room's `base_light_level`, passed straight through | `LightLevel` |

**World cluster** (right, inside a region boundary)

| Node | Owns | Entry point |
|---|---|---|
| `graph` | nodes and **directed** edges | `MacroWorldGraph` |
| `path` | Dijkstra keyed by effective distance | `findShortestPath` |
| `time` | exact fractional days and hours | `computeTravelTime` |
| `terrain` | STANDARD 1 · DIFFICULT 2 · TRACKLESS 3 | `TERRAIN_MULTIPLIER` |

## Facts the diagram must keep honest

- **Neither module has an in-engine consumer.** The only importers are `IRulesEngine.ts` (the interface) and `d20_rules.ts` (the facade). No other engine in `src/` imports either module, and `player-api` never calls them. The real callers are the Phase 2.5 router action list in `rules-engine-api/src/validation.ts` and `router.ts`. Do not invent a consumer edge — this is the whole reason the card says "neither wired in".
- **The two modules do not import each other, and neither imports anything at all** — not even `shared-types`. They are self-contained leaves. `worldGraph.ts` mentions `movement/movement.ts` in a comment; that is not a dependency.
- **Both are dice-free.** No `diceRoller` parameter anywhere. Do not add the "fail closed before any dice" framing the combat/spells/skills children use.
- **`getVisibleEntities` genuinely calls `assessLighting`** per entity, so `assess → visible` is a real internal call. `computeTravelTime` consumes `findShortestPath`'s `totalEffectiveMiles`, so `path → time` is real too.
- **Vision specifics that are easy to flatten:** BRIGHT carries no penalty; SHADOWY is 20% concealment; DARKNESS is 50% concealment, −2 AC, no Dex bonus to AC, half speed and blind — *unless* the viewer has darkvision and is within 60 ft, in which case it is black and white with no penalty. `DARKVISION_RANGE_FT = 60`. LOW_LIGHT doubles source radii.
- **Vision scope boundaries, all deliberate:** sources are radial only and co-located with the viewer; the bullseye lantern's cone is deferred because the spec carries no angle; magical light and darkness are out of scope and all DARKNESS is treated as non-magical; the MVP room schema has no coordinates, so the caller supplies viewer-relative distances.
- **World specifics:** edges are **directed**, so a two-way route must be expressed as two edges (matching Design 07 §2B). Terrain multiplies distance to give "effective" distance. `computeTravelTime` **never rounds** — rounding a partial day is the Time-Delta Tick Engine's concern, explicitly.
- **Overland is a pure graph** — no hex geometry. That is an architectural invariant, not an omission; do not add hex or geographic presentation nodes.

**The likeliest silent staleness here — check this first.** Either module gaining an **in-engine consumer**: another `src/` engine importing it, or `player-api` calling it. The `no live caller` tags and the "neither wired in" card are the whole reason this diagram exists, and a single new import would make them false without breaking any gate.

## Layout notes specific to this diagram

It matches **neither** README archetype. It is two three-stage clusters side by side, each a small vertical-then-horizontal flow, and both deviations are deliberate.

- Two clusters on a 6-column grid: vision at columns c0/c1 (`x` = 40, 245), world at c3/c4 (`x` = 655, 860). The **gutter at c2 (~235px of clear space) is intentional** and is what makes the split legible.
- Rows at `y` = 40 (inputs and graph), 190 (the middle stages), 330 (the auxiliary tables); node sizes `[175, 70]`–`[175, 74]`. The rows are tighter than in the sibling diagrams — that is what buys the flat aspect ratio.
- Two `region` boundaries carry the cluster names. Check their padded rectangles: vision spans x 12..448 and world x 627..1063, so they do not overlap and neither encloses the other's nodes. Keeping the gutter wide enough for `pad: 28` on both is what constrains the cluster positions.
- `labelDy`: `30` for the downward edges into the middle row, `-30` for the upward ones, `58` for the horizontal middle-row edges. These are tuned to the tighter row gaps; re-check them if you change row positions.

## Keeping the diagram current

- A change to `LightLevel`, the concealment or penalty values, or `DARKVISION_RANGE_FT` changes `assess` and the light-ladder card.
- A change to `VisionType` behaviour (LOW_LIGHT doubling, darkvision range) changes `assess` or `light`.
- A change to `assessLighting`'s parameters changes the `light` / `ambient` inputs.
- A change to `TerrainDifficulty` or `TERRAIN_MULTIPLIER` changes `terrain` and the travel card.
- A change to edge direction semantics, or to `computeTravelTime`'s rounding contract, changes `graph` or `time`.
- **If either module gains an in-engine consumer**, the `neither wired in` card line is now false. Re-run the consumer grep rather than assuming.
- If a hex or geographic presentation layer is ever added, the pure-graph invariant card line is false — but that is a deliberate non-goal, so treat it as a design change to confirm, not a silent edit.
- Bump `meta.repository.revision` to the full 40-hex commit documented.

If `change_ref` is supplied, state which cluster it affected and which it did not. If nothing changed, update only the revision — or leave the artifact untouched and say why.

## Non-goals

- Do not touch the other rules-engine diagrams, `docs/architecture/Infrastructure Architecture.md`, or the infrastructure/authentication diagrams.
- Do not change rules-engine implementation, tests, or `IRulesEngine`.
- Do not add, remove, or rename a Rules Engine API action or an SRD claim. A diagram refresh changes no engine behaviour, so `tests/integration/src/vector-matrix/vectors.ts` and `docs/rules-coverage/catalog.json` are **out of scope here** — they follow the action or claim that motivated the change and belong to that change's own task. State this reasoning rather than silently skipping the check.
- Do not join the two clusters, add a consumer edge, or add hex geometry, procedural maps, or a fog-of-war reveal ladder.
- Do not widen `meta.viewBox` in either dimension without re-probing; see the table above.

## Done when

- Every node maps to a real function, type, or constant; every edge is a real internal call or a documented caller-supplied input; every `sources` path and line exists at the pinned revision.
- `validate` passes with `--quality showcase`: 9/9 artifact checks, 0 composition errors, 0 warnings.
- The containment probe passes **before** delivery, and readability has margin at 1440×900 — both budgets are tight here, so never accept a pass on one without the other.
- `deliver` succeeds and its receipt reports matching specification and artifact SHA-256 values.
- `visual-check` against the exact delivered artifact reports no overflow and readability OK at 1440×900, 1600×1000, 1920×1080, and 2048×1320.
- `meta.repository.revision` matches the commit documented, and only the spec, the artifact, and this diagram's row in `docs/architecture/diagrams/diagram-state.md` are changed — no `visual-check` sidecars remain.
- This diagram's row in `docs/architecture/diagrams/diagram-state.md` records the date and commit actually verified against — not backdated, and equal to `meta.repository.revision` where the schema has it.
- `git diff --check` passes.

If the source and Design 05 §3 or Design 07 §2B disagree about a light level, a terrain multiplier, or edge direction, or a consumer edge cannot be confirmed with a real import, **stop and ask** rather than guessing.

## Response

Return:

1. The artifact paths changed, and whether this was a refresh-in-place or a re-layout.
2. Each node and edge verified, with the import or source that proves it — and explicitly, that neither module has an in-engine consumer, if that is still true.
3. The exact commands run with their real outcomes (validation check count, error/warning count, delivery SHA-256 values, `visual-check` per-viewport results, and both readability and containment numbers). Never report a non-zero exit as success.
4. Browser evidence and perceptual review reported **separately**. If the active model cannot view images, state that the perceptual review was not performed.
5. Anything unresolved, assumed, or deliberately left out of scope.