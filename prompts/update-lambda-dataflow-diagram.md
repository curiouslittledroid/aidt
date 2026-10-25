---
description: Refresh the Lambda data-flow diagram (every Lambda, its stage, and the datastores it touches)
argument-hint: "[change-ref]"
---

# Refresh the Lambda data-flow diagram

Maintains one artifact: the Archify **dataflow** map of the Mythical Forge Lambda estate — every function in the deployment, grouped into pipeline stages, and the datastores and external services each one touches.

This is a **documentation-refresh prompt**. It must not change application, infrastructure, or rules-engine code. If the diagram is wrong, `infra/` and the handlers are the source of truth and the diagram is what gets fixed.

Read `docs/architecture/diagrams/README.md` first. It holds the shared authoring contract — the layout budgets, the universal geometry rules, the truthfulness rules, and the delivery/freeze protocol. This prompt does not restate it.

**A stale diagram still validates.** `validate` proves the drawing is internally consistent and geometrically sound; it cannot tell you that a stage, a node count, or a flow still describes the estate. A 9/9 pass is evidence about the *drawing*, not about the *truth* of its labels. Establish freshness from `infra/lib/*.ts`, the handlers, and a `cdk synth` — never from a green `validate`.

**Record the verification.** Update this diagram's row in `docs/architecture/diagrams/diagram-state.md` — the UTC date and the full commit SHA you verified against. A fabricated date there is worse than an empty one.

## State of the baseline — both gates pass

The committed specification is a **3-row layout at `viewBox` `[1085, 495]`** (aspect 0.456), and it satisfies both budgets at once:

- **`validate --quality showcase` passes: 9/9 artifact checks, 0 composition errors, 0 warnings.**
- **Readability passes** (`minText` 6.82 at 1440×900 against a floor of 6, and 7.00 at 1600×1000 and above).
- **Containment passes** (`overflowY: false` at 1440×900, 1600×1000, 1920×1080 and 2048×1320; `scrollHeight` equals the viewport height at every one).

This took two separate breakthroughs. Both are recorded because the *reasoning* is the expensive part, not the JSON.

**Before changing any geometry, read the committed specification.** Its `via` arrays, `fromSide`/`toSide` values and `labelAt` points *are* the routing. The prose below only explains why they are what they are — the tables cannot reproduce a five-point `via` array, so **copy the committed values rather than reconstructing them from the tables**.

### Do not search for a layout

The 3-row shape, the corridor assignments and the label positions in the committed spec were found by an exhaustive search — all 1944 row permutations, then a candidate generator that produced tens of thousands of routings, then a greedy label pass. **Do not repeat it.** Stop and re-read the committed spec if you notice any of these:

- you are writing a script that permutes rows or generates candidate routings;
- you have run more than ~20 `validate` invocations without converging;
- you are re-measuring the width/aspect window (it is tabulated below and in the README);
- you are trying a different number of rows.

The search space is not the difficulty — the constraints are tight enough that only a few shapes exist and the committed spec is one of them. A change that genuinely needs a new shape is a **stop-and-ask** decision (see *If containment regresses*), not a search.

### Capacity: this grid is nearly full

5 stages × 3 rows = **15 cells, 13 occupied**. The only free cells are **(stage 0, row 2)** and **(stage 2, row 2)**. The top corridor band holds **4** long horizontals (y 106/118/130/140 within 104–148) and all four are in use. Therefore:

- A new node fits only in those two cells, and only if its flows can reach it without claiming a new top-band corridor.
- A new cross-stage flow into a stage-4 store needs a **5th** top-band corridor. There is not one. Prefer folding the fact into an existing node's `sublabel`/`tag`, or into a card.
- A **fourth row breaks containment** at this width. Do not add one.

### Breakthrough 1 — the 3-row layout only became routable after `ws-default` was dropped

In a 3-row layout every stage occupies all three rows, so the only free horizontal corridors are the two inter-row bands (y 186–242 and 300–356). The `ws-gw` fan put a vertical in **both** bands at the same x (≈422.5, the only column between stages 1 and 2), because its two targets sat in different rows — and every cross-stage flow from stage 1 to the state store has to cross that x. With no fourth row to use as a highway, there was no clean route.

Removing the `$default` stub node (`ws-default`) deleted the `ws-gw → ws-default` leg and freed a band. It is a real (if inert) route handler, so this is a **content trade-off**, deliberately taken: the `$default` handler touches no datastore, and the card says so. See the history note.

### Breakthrough 2 — a taller top corridor without a taller canvas

Even then, the four cross-stage flows (`ws-ticket`, `ws-lifecycle`, `ws-message` → `ddb-game`, and `id-triggers` → `ddb-account`) all needed a horizontal corridor, and **both inter-row bands are unusable for them**: band A is crossed by same-stage verticals (`cognito→id-triggers` at x=100, `ws-gw→ws-message` at 422.5, `ws-message→openrouter` at 530, `admin-gw→rules-engine` at 745) and band B by `ws-gw→ws-lifecycle` at 315 and `seed-srd→postgres` at 852.5. A long horizontal in either band must cross one of those. **The top band (y 104–128) is the only fully free corridor — and it is only 24px tall, enough for two corridors, not four.**

The fix is a `yOffset` on row 0 **only**: `yOffset: 20` moves the row-0 nodes to y 148–206, which grows the top band to 104–148 (44px) *without changing `viewBox` height*, so containment is unaffected. Row 0 → row 1 still leaves a 36px gap, above the 34px minimum flow length; **`yOffset: 24` fails** with three "too short" errors, so 20 is close to the ceiling.

### The ladder rule that makes four corridors work

Four flows sharing a 44px band cross each other unless the corridors are ordered deliberately. The rule that worked: **sort the flows by riser x ascending and give them corridors from the top of the band downward** (leftmost riser gets the highest corridor). A riser can then only reach corridors above its own, so it never crosses a lower corridor's horizontal. The winning assignment:

| Flow | riser x | corridor y | target side |
|---|---|---|---|
| `id-triggers → ddb-account` | 190 | 106 | `top` (descends at x=1062, then west to 960, then south) |
| `ws-lifecycle → ddb-game` | 207 | 118 | `bottom` (descends at x=1050 to y=220, west to 960, then north into the bottom edge) |
| `ws-ticket → ddb-game` | 315 | 130 | `right` (descends at x=1048, west to the right edge) |
| `ws-message → ddb-game` | 530 | 140 | `top` (descends at x=960) |

The final descents must also clear each other's horizontals, which is what fixes the descent columns at 1048/1050/1062 (≥8px apart) and forces `ws-ticket`'s descent to 1048 rather than 1040 — at 1040 the target stub into the right edge is only 5px and fails `composition/micro-segment`. **Corridors 10–12px apart do not fit four labels**, so all four long-flow labels are placed with `labelAt` on the wide empty interior (`~[560,330]`, `~[700,330]`) rather than on their routes.

### If containment regresses

Probe first (`render` + `visual-check`), then take one lever: keep the 3-row shape, re-check the `yOffset` (20 is near the ceiling), and trim card copy. The options that were considered and rejected — splitting the artifact, folding the workers/DynamoDB splits back into single nodes — reverse accuracy for geometry, so treat them as genuine trade-offs, not free wins. The one that *was* taken is the `ws-default` removal above; do not undo it silently. **If none of those levers works, stop and ask** — per `AGENTS.md`, a trade-off between showing real content and passing a gate is the user's call, not yours, and it is exactly the decision that consumed the session that produced this note.

## History note: what was repaired, and the defects that are now fixed

Do not re-fix these; they are recorded so the reasoning survives.

Fixed:
- `ws-gw` tag said **"7 routes"** — there are **6 routes** and 7 WS *Lambdas* (6 handlers + the authorizer; the authorizer is not a route).
- `rules-engine` tag said **"30+ pure D&D 3.5 functions"** — the router declares **40 actions**, five of which are reference lookups (`getSpellById`, `getFeatById`, `getMonsterById`, `getItemById`, `getSkillById`).
- The `workers`** node was removed**, and its two flows deleted. Only `ReindexHnswWorker` is invoked at all, and its body is a no-op stub that never connects to Postgres; the other five placeholder Lambdas have no event source and no invoker. **Deployed is not the same as performing a data flow** — a `dashed` variant has no "planned" semantics and does not license asserting movement that does not happen. The worker story now lives in a card.
- **`DynamoDB` was split into `rpg_game_state` and `rpg_account_state`.** They are different tables with different scoping (sandbox- vs account-scoped), so showing them separately is more accurate, not just more convenient.
- The 14 composition errors were removed by routing each converging flow through a corridor in a **free horizontal band** and giving each a **distinct entry side** on the state-store node. Two traps that cost the most time: the `ws-gw` fan already occupies the column at x≈422.5 (so `channelY` values there push routes through nodes), and `route: "straight"` between nodes in *different* rows renders as a **diagonal**, which fails the `orthogonal_arrows` artifact check while composition still reports clean.
- **`ws-default` was removed as a node, and its `ws-gw → ws-default` flow deleted.** This is the one place where a real deployed route handler is deliberately not drawn. It is a `$default` stub with no datastore access, so no data flow is lost — but the *reason* it is gone is geometry, not truth. Both the card and this note record it so a future refresh does not "restore" it and re-break the 3-row layout.

## Scope boundary: this diagram is breadth, not depth

Three artifacts in this directory describe overlapping runtime behaviour. They are not interchangeable, and this one is the odd one out:

| Artifact | Job |
|---|---|
| `lambda-dataflow.json` (**this one**) | **Breadth.** Every Lambda, grouped by stage, and which datastore each touches. The only place you can see the whole estate at once. |
| `authentication-api-sequence.json` | **Depth on identity.** Cognito hooks, token issuance, and how each entry point authorizes. |
| `player-ws-message-flow.sequence.json` | **Depth on one message.** `PLAYER_INPUT` through moderation, intent parse, rules, and narration. |

Because breadth is the point, **do not grow this diagram message-by-message.** No per-frame detail, no ordering within a stage, no per-invocation arguments. If a change adds a step inside an existing flow, it probably belongs in `player-ws-message-flow.sequence.json` instead.

## Variables

change_ref: $1

- `change_ref` is optional. If supplied, treat it as the change that motivated this refresh and check for added or removed Lambda functions, new datastore access, and new stages.
- If omitted, diff the current `infra/` app and handlers against the committed specification.

## Artifacts (fixed paths — do not create others)

- Candidate specification: `docs/architecture/diagrams/lambda-dataflow.json`
- Generated artifact: `docs/architecture/diagrams/lambda-dataflow.html`
- Browser evidence sidecars. `visual-check` writes a receipt, a contact sheet, and screenshots next to the HTML, and **prunes stale sidecars in that directory**. Never author them by hand and commit none of them — see `docs/architecture/diagrams/README.md`. Delete them before finishing and quote the delivery SHA-256 values in the response instead.

Never hand-edit the generated HTML.

**This artifact was renamed** from `mythical-forge-lambdas.dataflow.json` / `mythical-forge-lambdas.html` to `lambda-dataflow.json` / `lambda-dataflow.html`, and `meta.output` now records the new name. If you find a stale reference to the old name anywhere (a prompt, a doc, an allowlist), fix it — but do not rename further.

## Evidence sources (read these, in this order)

1. **`infra/lib/compute-stack.ts`** — the worker set, the reserved-concurrency budgets, and the single EventBridge cron rule. This is the file that determines which "workers" exist and, more importantly, **which of them are actually reachable**.
2. **`infra/lib/api-stack.ts`** — the REST and WebSocket entry points, the ticket issuer, the authorizer, and the route list.
3. **`infra/lib/identity-stack.ts`** — the four Cognito trigger Lambdas.
4. **`infra/lib/data-stack.ts`** — the two DynamoDB tables, RDS, the proxy, and the two custom-resource handlers.
5. **`infra/lib/srd-data-stack.ts`** — the ad-hoc SRD seeder (opt-in, not in the default pipeline).
6. **`infra/lib/websocket-lambda-integration.ts`** — the custom WS integration construct.
7. **The handlers themselves** — `services/player-api/src/handlers/*.ts` and `services/rules-engine-api/src/router.ts`. Their header comments state the Design section and the step list. **A header comment can be stale; the code below it is not.**
8. **`cdk synth` — the ground truth for the Lambda inventory.** Synthesizes without AWS credentials:

   ```bash
   pnpm --filter infra cdk synth -c env=dev
   ```

   Read `infra/cdk.out/*.template.json` and count resources by type. **Do not run `pnpm exec cdk synth` from inside `infra/`** — CDK bundles from the workspace root, where `esbuild` is not linked, and it fails with `Command "esbuild" not found`. `infra/cdk.out/` is gitignored.

   Per-stack Lambda counts at the pinned revision: `Api` 8, `Compute` 7, `Identity` 4, `Data` 4 (custom-resource handlers and provider frameworks). Every Lambda in the deployment should be accounted for by a node or a node's `sublabel` count.

## Layout notes specific to this diagram

The dataflow renderer is a **grid**, not free placement. Constants (from `renderers/dataflow/README.md`):

| Thing | Value |
|---|---|
| Stage centres | `x = 100 + stage×215`; stage band 168 wide (so bands span ±84) |
| Stage gaps (free vertical corridors) | x ≈ 207, 422, 637, 852 |
| Row tops (`row` 0–4) | y = 128, 242, 356, 470, 584 (plus `yOffset`) |
| Free horizontal bands | y 104–128, 186–242, 300–356, 414–470, 528–584 — **before `yOffset`**. With this diagram's `yOffset: 20` on row 0 they are 104–148, 206–242 and 300–356. Always recompute from the actual row tops; the raw constants mislead once an offset is in play |
| Default node | 112×58; node area x ∈ [24, width−24], y ∈ [104, height−74] |
| Legend row | y = height − 36 |

Consequences that matter when routing:

- **Long horizontals must live in a free band**, never at a row's own y — at a row's y they pass straight through that row's nodes in every intervening stage (`clean-flow/edge-through-node`).
- **Risers must use a stage gap or a column with no node in the rows they cross.** A riser at a stage centre passes through that stage's nodes.
- **`ws-gw` already occupies x ≈ 422.5** (its `auto` routes elbow at the midpoint). Any `channelX`/`channelY` you add near there pushes routes through nodes.
- **`rules-engine → postgres` must be `straight` only when both sit in the same row.** Across different rows, `straight` renders a **diagonal**, which fails the `orthogonal_arrows` artifact check even though `composition` reports `pass` with 0 errors. If `validate` returns `ok: false` with an empty error string, check `checker.checks` — the failure is an artifact check, not composition.
- **The top band is the only reliable long horizontal corridor.** Both inter-row bands carry same-stage verticals in the middle columns, so a long horizontal there is guaranteed to cross one. Open a taller top band with `yOffset` on row 0 (see above) rather than by growing `viewBox[1]`.
- Automatic port spread produces small elbows on otherwise straight same-row flows; a 7px interior segment fails `composition/micro-segment`. Pin `route: "straight"` (same row only) or explicit sides to suppress it.
- **Changing any row's `yOffset` invalidates every label on every flow touching that row.** The labels are positioned with `labelDy`/`labelAt` tuned to the *current* row gaps, so a `yOffset` change silently produces `Label "…" overlaps node "…"` and `label-route-clearance` errors even though no route moved. Re-do the affected flows' labels; do not assume they survived. This is the one repair that reliably costs a second pass.

## Routing controls reference

- `route`: `auto` (default), `straight`, `vertical-channel`, `bottom-channel`, `top-channel`.
- `via`: an explicit list of waypoints. The most reliable tool here — every long flow uses it.
- `fromSide` / `toSide`: `top`, `bottom`, `left`, `right`. A **direction contract**: `bottom` means the final segment runs vertically *upward into* the bottom edge; `top` means *downward into* the top edge. Backwards is `clean-flow/endpoint-side-direction`.
- `labelAt`, `labelDx`, `labelDy`, `labelSegment`, `width`.
- **Any** of `via`, `channelX`, `channelY`, `labelAt`, or a non-`auto` route **disables automatic port spread** — the mechanism that normally lets several flows share one node side. That is why the three flows into `ddb-game` each take a different side.

## Schema and command differences from the architecture diagrams

- **`--repo-root` is architecture-only** and is rejected for dataflow (`--repo-root is currently supported for architecture diagrams only.`). Drop it from every command here. Dataflow nodes carry no `sources`, so there is no line-number evidence to maintain — which is also why the schema cannot flag a stale label for you.
- **Nodes use a `stage`/`row` grid**, not `pos`/`size`: `stage` (integer, the pipeline column), `row` (integer, the lane), plus optional `width`, `height`, and `yOffset`. Stages are declared separately as an ordered list of `{ label }`.
- There is also a `classification` field (data contract / classification) that this diagram does not currently use.
- `viewBox` is `[1085, 495]` — aspect 0.456. **`validate` caps the width at ~1085** (its readability model assumes ~930px of diagram width against this renderer's 7px preferred node font); it passed at 1085 and failed at 1100/1150/1180/1190. Containment is an **aspect** budget, so a *narrower* viewBox renders *taller* — width and height are coupled through the viewer, and this diagram sits in the narrow window where both hold.

## Commands

Read `/Users/phil/.pi/agent/skills/archify/SKILL.md` and follow its authoring workflow. Write the candidate before inspecting renderer internals. Apply **one** geometry control per repair, then re-validate.

**No `--repo-root`:**

```bash
ARCHIFY=/Users/phil/.pi/agent/skills/archify/bin/archify.mjs

node $ARCHIFY validate dataflow docs/architecture/diagrams/lambda-dataflow.json --quality showcase --json
node $ARCHIFY deliver  dataflow docs/architecture/diagrams/lambda-dataflow.json docs/architecture/diagrams/lambda-dataflow.html --quality showcase --json
node $ARCHIFY visual-check docs/architecture/diagrams/lambda-dataflow.html --json
```

**Where each command stands today:**

| Command | Today |
|---|---|
| `validate --quality showcase` | **exit 0** — 9/9 checks, 0 errors |
| `render --quality showcase` | exit 0 |
| `deliver --quality showcase` | exit 0 |
| `visual-check` on the delivered HTML | **exit 0** — no overflow, readable at all four viewports |

`validate` and containment are **separate gates and can conflict**, so probe both before delivering:

```bash
node $ARCHIFY render dataflow <spec>.json /tmp/probe.html --quality showcase
node $ARCHIFY visual-check /tmp/probe.html --json
```

`--quality standard` also renders and is a valid probe — geometry is profile-independent — but it is never acceptance evidence. Never deliver a candidate whose `visual-check` reports `overflowY`, and never report a non-zero exit as success.

**Do not run `deliver` until `validate` reports `ok: true` with all 9 checks and 0 errors.** If `deliver` exits non-zero it preserves the previous output, and running `visual-check` on that path would inspect the stale last-good artifact rather than the failed candidate.

## Keeping the diagram current

| Change | Update |
|---|---|
| A Lambda added or removed | The owning node's `sublabel` count (`"5 Lambdas"`) and the stage it belongs to — a new node only if it is a new *kind* of participant, and then only into one of the **two free grid cells** (see *Capacity*) |
| A new pipeline stage | `stages` plus the affected nodes' `stage` values — **and this widens the viewBox**, so re-check both budgets against the ~1085 width cap |
| A new datastore or external service | A new node plus its flows — a stage-4 store needs a top-band corridor and there are none spare; see *Capacity* |
| A placeholder Lambda becoming real | **Add its flows.** This is the reverse of the current defect — the edge appears when the implementation does |
| A worker gaining an event source (queue, schedule, invoke grant) | Add the triggering flow and update the node's tag |
| A route added or removed on the WebSocket API | The `ws-gw` tag count **and** the `ws-lifecycle`/`ws-message` split — remember routes ≠ Lambdas (the authorizer is not a route). `$default` is deliberately undrawn; see the history note before adding it back |
| A route gaining or losing an authorizer | The corresponding flow label |
| A Rules Engine API action added or removed | The `rules-engine` tag count, derived from the router action table, not remembered |
| A secret or IAM grant added | Usually a card, not a node |
| `viewBox` or any row/stage assignment changing | Re-probe **both** budgets; a width change moves containment the *opposite* way (aspect) from readability |

If `change_ref` is supplied, state which stages it affected and which it did not. Dataflow specifications carry no `meta.repository.revision`; do not add one.

## Non-goals

- Do not touch the other diagrams or their prompts. In particular do not fix `player-ws-message-flow.sequence.json` from here — it is **not in the allowlist**, so flag any issue rather than editing it.
- Do not change application, infrastructure, or rules-engine code.
- Do not add, remove, or rename a Rules Engine API action or an SRD claim. A diagram refresh changes no engine behaviour, so `tests/integration/src/vector-matrix/vectors.ts` and `docs/rules-coverage/catalog.json` are **out of scope here** — they follow the action or claim that motivated the change. State this reasoning rather than silently skipping the check.
- Do not add per-message or per-frame detail; that is the sequence diagrams' job.
- Do not draw flows that placeholder Lambdas do not perform, and do not add a node for anything that exists only in a design document.
- Do not delete a semantic flow label to clear a geometry diagnostic.

## Done when

- **`validate --quality showcase` reports `ok: true`, all 9 artifact checks, 0 composition errors, 0 warnings.** Holds today; keep it holding.
- Every Lambda in a dev synth is accounted for by a node or a `sublabel` count, and every flow is either a real datastore access or an explicitly labelled not-yet-implemented step.
- No placeholder Lambda has a data flow attributed to it.
- `visual-check` on the delivered HTML reports **readability OK** at 1440×900, 1600×1000, 1920×1080, and 2048×1320.
- **Containment passes at 1440×900** (`overflowY: false`, `scrollHeight` = viewport height). Holds today; keep it holding. Do **not** silently deliver an overflowing artifact, and do not claim a fully verified result you did not measure.
- `archify deliver` succeeded, and its receipt reports matching specification and artifact SHA-256 values.
- The only files changed are the candidate specification, the delivered HTML, and this diagram's row in `docs/architecture/diagrams/diagram-state.md`. Every `visual-check` sidecar has been deleted and `infra/cdk.out/` is untouched.
- This diagram's row in `docs/architecture/diagrams/diagram-state.md` records the date and commit actually verified against — not backdated, and equal to `meta.repository.revision` where the schema has it.
- `git diff --check` passes.

If a converging flow cannot be expressed without a crossing, **stop and report the residual diagnostics and the variants you measured** rather than deleting a flow or a label to reach zero. Deleting a real flow to satisfy a geometry gate is a truthfulness regression, not a fix.

## Response

Return:

1. The artifact paths changed, and whether this was a geometry repair, a content refresh, or both.
2. Each node and flow verified, with the stack file, handler, or synth resource that proves it — and an explicit statement that no placeholder Lambda has a data flow attributed to it.
3. The exact commands run with their real outcomes (validation check count and error/warning counts, delivery SHA-256 values, `visual-check` per-viewport results including 1440×900, and `minText`). Never report a non-zero exit as success.
4. **Containment reported separately from readability**, since they are separate gates with different mechanisms. Give the measured `overflowY`/`scrollHeight` and `minText` per viewport.
5. Browser evidence and perceptual review reported **separately**. If the active model cannot view images, state that the perceptual review was not performed.
6. Anything unresolved, assumed, or deliberately out of scope — including whether the deliberately-undrawn `$default` route is still the right trade-off.
