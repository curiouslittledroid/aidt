---
destination: mythical-forge/aidw/prompts/
description: Refresh the rules-engine SRD subsystem architecture diagram from current source evidence
argument-hint: "[change-ref]"
---

# Refresh the rules-engine architecture diagram

Maintains one artifact: the Archify architecture map of the deterministic rules engine's SRD 3.5 subsystems. It shows the call path from the Intent Parser to the Narrator, and the engine facets in between (combat, spells, skills, movement, progression, vision/world).

This is a **documentation-refresh prompt**. It must not change application, infrastructure, or rules-engine implementation code. If the diagram is wrong, the implementation is the source of truth and the diagram is what gets fixed.

Read `docs/architecture/diagrams/README.md` first. It holds the shared authoring contract — the two budgets, the universal geometry rules, the layout archetypes, the truthfulness rules, and the delivery/freeze protocol. This prompt does not restate it.

## Variables

change_ref: $1

- `change_ref` is optional. If supplied, treat it as the change that motivated this refresh (commit, branch, or PR) and check whether it altered any facet's entry points, additions, or removals.
- If omitted, compare the current rules-engine source against what the existing specification records and reconcile the difference.

## Artifacts (fixed paths — do not create others)

- Candidate specification: `docs/architecture/diagrams/rules-engine-architecture.json`
- Generated artifact: `docs/architecture/diagrams/rules-engine-architecture.html`
- Browser evidence sidecars. `visual-check` regenerates the receipt `.visual-check.json`, the contact sheet `.visual-check.html`, and the screenshots `.visual-check.<WxH>.<theme>.png` next to the HTML, and may prune stale ones. Never author them by hand, and **commit none of them** — see the reasoning in `docs/architecture/diagrams/README.md`. Delete them before finishing and quote the delivery SHA-256 values in the response instead.

Never hand-edit the generated HTML. It is produced only by `archify deliver`.

## Update in place — do not re-author from scratch

The existing candidate specification is a **geometrically validated baseline** — it passes `validate` 9/9 and both browser budgets. That is a statement about the *drawing*, **not** about whether its labels are still true. Two diagrams in this directory passed `validate` 9/9 for a long time while being materially wrong, and no gate could see it: one drew a mock integration that had been real for months, another drew a model call where the handler sends a hard-coded string.

So the order is: **re-derive the facet set, the entry points, and the caller chain from the source modules first**, and only then make a small diff. Re-planning the canvas is still not warranted — but "it validates" is not a reason to skip the check. Preserve every existing component `id`, `pos`, `size`, and every connection's routing controls **after** confirming the facts, not instead of it.

**A stale diagram still validates.** `validate` verifies that every `sources` path and line resolves at the pinned revision; it cannot tell you the claim beside it is still true. A citation that resolves is not a fact that holds.

**Record the verification.** Update this diagram's row in `docs/architecture/diagrams/diagram-state.md` — the UTC date and the full commit SHA you verified against, kept equal to `meta.repository.revision`. A fabricated date there is worse than an empty one.

Always start by reading `docs/architecture/diagrams/rules-engine-architecture.json` and editing it. Preserve every existing component `id`, `pos`, `size`, and every connection's routing controls unless the facts require a change. Adding or removing one facet is a targeted layout edit; it is not a reason to re-plan the canvas.

## Evidence sources (read these, in this order)

1. `services/rules-engine/src/IRulesEngine.ts` — the authoritative method groups (Combat, Skills, Spells, Stunts, Movement, Progression, Vision, World). This file defines the facet set and the entry-point names on the connection labels.
2. `services/rules-engine/src/d20_rules.ts` — the `DND_3_5` implementation; every method delegates to a leaf function. Confirms which module each facet owns.
3. `services/rules-engine/src/rulesRegistry.ts` — the `rules_system → IRulesEngine` plugin boundary.
4. Each facet's barrel: `services/rules-engine/src/<module>/index.ts` — the public surface actually exported.
5. `docs/specs/Design 09 - Game Rules Engines.md` §3 (Engines 1–5) and §4 (execution timeline), and `docs/specs/Design 09.1 - Alternative Rule Sets.md` §2 (`IRulesEngine` decoupling). These name the engines; they do not override the code.
6. **Caller chain — verify, do not assume.** Run:
   `grep -rn "rulesRegistry\|getEngine" --include=*.ts services/player-api/src services/rules-engine-api/src`

   Trap: two callers exist and they behave differently. The `player-api` dispatcher executors (`spellExecutor.ts`, `skillExecutor.ts`, `movementExecutor.ts`) go **through** `rulesRegistry.getEngine(...)`. The `rules-engine-api` router imports the leaf functions **directly** and bypasses the registry. The diagram models the registry path; if that changes, the diagram is stale.

## Facet ↔ code mapping (current baseline)

| Facet node | Spec engine | Entry point on the edge | Code |
|---|---|---|---|
| `combat` | Engine 1 | `resolveCombatTurn` | `src/combat/` |
| `spells` | Engine 2 | `resolveSpellTurn` | `src/spells/` |
| `skills` | Engine 3 + §5.3 fallback | `resolveSkillTurn` | `src/skills/`, `src/stunts/` |
| `movement` | Engine 4 | `validateMovement` | `src/movement/` |
| `progression` | Engine 5 (shared kernel) | `getBAB · saves · HP` | `src/progression/` |
| `awareness` | *not in Design 09 §3* | `assessLighting · travel` | `src/vision/`, `src/world/` |

Reconciliation rules:

- Design 09 §3 names exactly five engines. The code has more modules. **Do not drop a real module to match the spec's count, and do not invent a spec engine number for one.** Show it and be explicit that it is outside §3.
- Two facets currently combine two modules each (`skills`+`stunts`, `vision`+`world`). These merges exist for canvas width, not because the modules are the same thing. Each carries up to 3 `sources` entries so both modules are cited. If you split a merged facet back out, expect to re-do the layout work described below.
- The card copy carries the facts a merged node cannot: the §5.3 DC 15 stunt fallback, and that `resolveCombatTurn` calls Movement/spatial for cover (+4 AC) and flanking (+2).

**The likeliest silent staleness here — check this first.** A **new module or directory appearing under `services/rules-engine/src/`** that is not in the table above. The diagram is a facet map, so a whole new subsystem is invisible to every gate: nothing in `validate` compares the facet set against the directory listing. Diff the source tree against the table before accepting the baseline. The second likeliest is the caller chain changing — see the `rulesRegistry` trap above.

## Layout notes specific to this diagram

This diagram uses archetype **A (hub fan-out)** from the README: the `engine` hub fans out to a row of six facets. Read that archetype before touching the fan edges — `labelSegment: 2` and the directly-beneath-the-hub special case are both explained there, and getting them wrong produces a cascade of `label-route-clearance` errors.

Points specific to this diagram:

- `meta.viewBox` is `[1250, 560]`, content in x 40..1200. Do not widen it: the readability budget in the README is what forces the facet count and the short sublabels.
- Six facets at `y = 340`, pitch 196, width 180.
- Top row: `intent` → `dispatcher` → `registry` → `engine`, with `narrator` further right, all at `y = 30` (`engine` at `y = 20`, height 96). Chain gaps are 32px and their labels carry `labelDy` ≈ 58–64 to drop below the row.
- The single `region` boundary wraps the six facets with `pad: 30`, and must not enclose the `engine` hub.
- `engine-to-movement` carries an explicit `labelAt` because `movement` sits directly beneath the hub.

## Commands

Read `/Users/phil/.pi/agent/skills/archify/SKILL.md` and follow its authoring workflow. Write the candidate before inspecting renderer internals. The validate / probe / deliver / visual-check commands, the `--repo-root .` requirement, and the freeze and delivery protocol are all in `docs/architecture/diagrams/README.md`.

Substitute this diagram's paths:

- spec: `docs/architecture/diagrams/rules-engine-architecture.json`
- artifact: `docs/architecture/diagrams/rules-engine-architecture.html`

Re-check `sources` line numbers whenever a rules-engine file is moved or its header comment shifts: they are verified against `--repo-root`.

## Keeping the diagram current

On a refresh, derive the facet set and edge labels from `IRulesEngine.ts` method groups plus the module barrels, then reconcile against the spec:

- A new method group with its own module → add a facet (and expect layout work).
- A method group that disappeared → remove the facet and its connections.
- A renamed orchestrator (`resolveCombatTurn`, `resolveSpellTurn`, `resolveSkillTurn`) → update the edge label; these are the diagram's most load-bearing strings.
- A module merged or split → update `sources` and node copy, and re-check the readability gate.
- A change in the caller chain (does `player-api` still route through `rulesRegistry`? does `rules-engine-api` still bypass it?) → update or add the `registry`/`dispatcher` nodes together. The bypass is deliberate; do not "fix" it into a registry call in the diagram.

If `change_ref` is supplied, state explicitly which facets it affected and which it did not. If nothing in the facet set, entry points, or caller chain changed, change nothing beyond `meta.repository.revision` — or leave the artifact untouched and say why.

## Non-goals

- Do not touch `docs/architecture/Infrastructure Architecture.md` or the infrastructure/authentication diagrams. `/update-architecture` owns those.
- Do not change rules-engine implementation, tests, or `IRulesEngine`.
- Do not add, remove, or rename a Rules Engine API action or an SRD claim. A diagram refresh changes no engine behaviour, so `tests/integration/src/vector-matrix/vectors.ts` and `docs/rules-coverage/catalog.json` are **out of scope for this prompt** — those follow the action/claim that motivated the change, and are the responsibility of that change's own task. Record this reasoning in the response rather than silently skipping the check.
- Do not add speculative or not-yet-built tiers to the diagram. Model what the code does, not what a design proposes.

## Done when

- `docs/architecture/diagrams/rules-engine-architecture.json` reflects the current rules-engine source: every facet maps to a real module, every connection label names a real entry point, and every `sources` path and line exists at the pinned revision.
- `archify validate` passes with `--quality showcase`, all 9 artifact checks, and 0 composition errors / 0 warnings.
- `archify deliver` succeeded, and its receipt reports matching specification and artifact SHA-256 values.
- `visual-check` was run against the exact delivered artifact and reports no overflow and readability OK at 1440×900, 1600×1000, 1920×1080, and 2048×1320.
- `meta.repository.revision` matches the commit the diagram documents.
- The only files changed are the candidate specification, the delivered HTML, and this diagram's row in `docs/architecture/diagrams/diagram-state.md`. Every `visual-check` sidecar (receipt, contact sheet, screenshots) has been deleted.
- This diagram's row in `docs/architecture/diagrams/diagram-state.md` records the date and commit actually verified against — not backdated, and equal to `meta.repository.revision` where the schema has it.
- `git diff --check` passes.

If the source and Design 09 disagree about what an engine is, or a merged facet can no longer be described truthfully, **stop and ask** — do not silently pick one. The merges in the facet table are a presentation decision that should be re-confirmed, not inherited by default.

## Response

Return:

1. The artifact paths changed, and whether this was a refresh-in-place or a re-layout.
2. Each facet verified, with the source file that proves it, and any facet added, removed, renamed, or merged.
3. The exact commands run with their real outcomes (validation check count, error/warning count, delivery SHA-256 values, `visual-check` viewport results). Never report a non-zero exit as success.
4. Browser evidence and perceptual review reported **separately**. If the active model cannot view images, say the perceptual review was not performed rather than implying it was.
5. Anything unresolved or assumed.