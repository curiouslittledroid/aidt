---
destination: mythical-forge/aidw/prompts/
description: Refresh the WebSocket player-message sequence diagram (PLAYER_INPUT → identity → moderation → intent → rules → frames) from current handler evidence
argument-hint: "[change-ref]"
---

# Refresh the WebSocket player-message sequence diagram

Maintains one artifact: the Archify **sequence** diagram of what happens between a connected browser sending one `PLAYER_INPUT` frame and the server finishing that turn — identity resolution, ingress moderation, intent parsing, deterministic rules execution, and the frames sent back.

This is a **documentation-refresh prompt**. It must not change application, infrastructure, or rules-engine code. If the diagram is wrong, `services/player-api/src/handlers/ws-message.ts` and the modules it calls are the source of truth and the diagram is what gets fixed.

Read `docs/architecture/diagrams/README.md` first. It holds the shared authoring contract — the layout budgets, the universal geometry rules, the truthfulness rules, and the delivery/freeze protocol. This prompt does not restate it. **Sequence diagrams differ from architecture diagrams in the schema, the commands, and the budgets**, and this prompt calls out each difference where it matters.

**A stale diagram still validates.** `validate` proves the drawing is internally consistent and geometrically sound; it cannot tell you that a step is still a stub, or that a step you drew has since been implemented for real. A 9/9 pass is evidence about the *drawing*, not about the *truth* of its labels. Establish freshness from `ws-message.ts` and the modules it calls — never from a green `validate`.

**Record the verification.** Update this diagram's row in `docs/architecture/diagrams/diagram-state.md` — the UTC date and the full commit SHA you verified against. A fabricated date there is worse than an empty one.

## Truth policy: current implemented reality only

This diagram documents **what the deployed code does today**. It is not a design document, not a roadmap, and not an illustration of intent. This rule overrides every other consideration in this prompt, including tidiness and completeness of the story.

- **A stub is not a step.** Where the code sends a hard-coded value, the diagram shows the hard-coded value — not the model call, tool call, or lookup that a comment says will replace it. `ws-message.ts` step 10 is the canonical example: it is marked `F1 REPLACEMENT POINT` and sends the literal string `'Your action is resolved.'`. Drawing an OpenRouter call there is a **falsehood**, not a simplification.
- **A comment is evidence of intent, not of behaviour.** `F1 REPLACEMENT POINT`, `TODO`, `placeholder`, and `Phase 4` markers describe what will replace the code. They never license an arrow.
- **Deployed is not doing.** A Lambda, table, or service that exists in the estate but performs no step in *this* flow gets no arrow and no participant.
- **This schema has no future-state styling.** There is no `dashed` or `planned` relationship variant, so an unimplemented step cannot be drawn "with a caveat" — it must simply **not be drawn**. Design intent belongs in `docs/specs/`, which is where a reader who wants the target architecture should be sent.
- **Every message must be traceable to a line.** If you cannot point at the handler line that sends, reads, or computes it, do not draw it.
- **If a change would require drawing future state, stop and ask.** The answer is never to invent a "planned" edge; it is to leave it out and say so.

The "Explicit Unknowns" card this artifact once carried is **gone on purpose** and must not return. A card enumerating unfinished design work is future state, and it makes the diagram read as a plan.

## State of the baseline — both gates pass

The committed specification is **22 messages over 7 participants at `viewBox` `[1400, 840]`** (aspect 0.600), and it satisfies both budgets:

- **`validate --quality showcase` passes: 9/9 artifact checks, 0 composition errors, 0 warnings, 0 proper crossings.**
- **Containment passes** (`overflowY: false` at 1440×900, 1600×1000, 1920×1080 and 2048×1320).
- **Readability passes** (`minText` 8.53 at 1440×900, against a floor of 6).

Two constraints squeeze this diagram, and both were measured rather than assumed:

| Constraint | Value | Why |
|---|---|---|
| Message `y` range | `[160, height − 83]`, **≥28px apart** | Renderer minimum spacing. 22 messages therefore need `height ≥ 831` — this is what sets the height |
| `validate` width cap | **~1085 when any participant has a `sublabel`** | Sublabels are "context" text at a 7px source font, and the readability model assumes 930px of available diagram width: `930 / viewBoxWidth × 7 ≥ 6` |

**Participant sublabels are therefore incompatible with this diagram's content, and it has none.** At the required height of 831, a width of ≤1085 gives aspect 0.766 — far past the ~0.64 ceiling — so sublabels cannot be used here. The information they would have carried lives in the **message `note` fields**, which do render into the artifact (`note` is visible text, not metadata). The sibling `authentication-api-sequence.json` is sublabel-free for the same reason. If you add a sublabel, expect `composition/desktop-readability` to fail and be ready to explain why the width had to drop.

**Cards are the other expensive lever** (~74px of page height each at this size). With 22 messages at the 28px minimum, **one card overflows 1440×900**; the artifact deliberately carries **zero cards**, matching the sibling sequence diagram. Put summary content in `note` fields instead of cards.

## History note: what was repaired, and the defects that are now fixed

Do not re-fix these; they are recorded so the reasoning survives — and so a future refresh does not "restore" them.

- **Narration was drawn as two real OpenRouter calls** (`narrate result (Tier 2/3 model)` and `narrative SSE stream`). It is a stub: `ws-message.ts:1193–1202` sends the literal `'Your action is resolved.'` via `sendNarrativeChunk`, marked `F1 REPLACEMENT POINT`. The artifact now draws `NARRATIVE_CHUNK — stub string` as a `dashed` message. **This is the canonical example of the truth policy: the arrow was removed, not softened.**
- **Ingress moderation was missing entirely.** The handler's step (c) runs `ModerationService.classify()` — a **separate OpenRouter call (Llama Guard 3 8B)** with three outcomes: SAFE (proceed), BLOCKED (`SAFETY_BLOCKED`, turn ends), UNAVAILABLE (`ERROR`/`MODERATION_UNAVAILABLE`, turn ends). It is now drawn as a `security` request plus a `dashed` `SAFETY_BLOCKED` branch.
- **`rulesEngine → dynamodb "read + atomic write game state"` asserted a write that never happens.** The handler imports only `GetCommand` — **no DynamoDB writes at all** — and the state provider is `FixtureSandboxStateProvider`: *"Mutations are applied in-memory only — no DynamoDB or PostgreSQL writes."* The edge is gone; the in-memory fact is in the `dice results + state deltas` note.
- **The identity-resolution read was missing.** Step (b) reads `CONNECTION#<connectionId>` from `rpg_game_state` and never trusts client-supplied identity. Now drawn as a `security` pair.
- **`rulesEngine` was drawn as a network peer.** It is an in-process import (`@mythical-forge/rules-engine/src/combat`, `ws-message.ts:82–93`). It is **still a participant lane** — the sequence renderer rejects self-messages (a `from == to` message fails with `spans 0px (minimum 60px)`), so a lane is the only way to show in-process work — but the message note now states **"IN-PROCESS module call, not a network hop"**, and the participant is named for the module rather than for a service.
- **The pgvector / episodic-memory card was removed**, along with the whole "Explicit Unknowns" card. There is no `pg`, `pgvector`, embedding, or episodic-recall code in the player-api path; it was design intent, and a card enumerating unfinished design work makes the diagram read as a plan.
- **The layout was rebuilt from `[960, 1000]` (aspect 1.04) to `[1400, 840]`.** The old shape failed containment at every viewport (`scrollHeight` 1799 against 900) while still passing `validate` 9/9 — the two gates are independent, which is why the defect survived. Fixing it meant **widening**, not cutting content.
- **The `dispatcher` participant was renamed `PLAYER_INPUT Lambda`.** "Dispatcher" read as a separate service, when the hop into it is an API Gateway invoke of the route Lambda.

## Scope boundary: one message, post-connect

This diagram owns exactly one runtime path — the `PLAYER_INPUT` turn. It is not the connection lifecycle, not authorization, and not the Lambda estate:

| Artifact | Owns |
|---|---|
| `authentication-api-sequence.json` | Identity and authorization: Cognito hooks, token issuance, and how each entry point authorizes a request |
| `player-ws-message-flow.sequence.json` (**this one**) | **One turn.** `PLAYER_INPUT` → identity resolution → moderation → intent parse → rules execution → frames out |
| `lambda-dataflow.json` | Breadth: every Lambda, its stage, and the datastores it touches |

Consequences:

- **Do not add per-frame or per-turn variants.** One representative turn, not the combat/skill/spell/movement branches. The executors differ in mechanics, not in flow shape.
- **Do not add the connection lifecycle.** `$connect`, `$disconnect`, `PING`, and `RESYNC_STATE` belong to the Lambda dataflow diagram and the authentication diagram.
- **The ticket handshake segment is context, and it is duplicated.** This diagram spends 8 of its 22 messages on ticket issuance and the WS handshake. That is real behaviour and it is the precondition for a turn, so it stays — but note that `authentication-api-sequence.json` renders `/ws-ticket` as **"200 mock; no Lambda invoked"**, which is stale (a real `WsTicket` Lambda writes the ticket). **Because that diagram is stale, this is currently the only truthful record of the real ticket flow** — so do not drop this segment until the authentication diagram is repaired. Once it is, this segment becomes a duplicate and should be **reduced to at most one context message**. Flag this rather than silently keeping or dropping it.

## Known defects in the current artifact

*(None outstanding — the artifact conforms.)* The defects that were fixed, with their evidence, are in the history note above. The rule they all illustrate is the truth policy: each one was either an arrow for something that does not run, or a missing arrow for something that does.

## The verified flow (the reference the diagram must match)

Derived from `ws-message.ts`. Eleven numbered steps plus the preamble; the numbers are the code's own section comments.

**Preamble — validation and identity**
1. Parse and validate the incoming frame against `PlayerInputFrame`. On failure: `ERROR` / `INVALID_FRAME`, return 200.
2. Resolve connection identity: `GetItem CONNECTION#<connectionId>` from `rpg_game_state` (written by the WS Authorizer). On failure: `CONNECTION_BINDING_LOOKUP_FAILED` or `CONNECTION_BINDING_NOT_FOUND`. **Never trust client-supplied identity.**
3. Ingress moderation — `ModerationService.classify()` → OpenRouter, Llama Guard 3 8B. Lazily initialised, cached for the warm container, with a cooldown before re-attempt after failure.

**Branch on the verdict**
- `BLOCKED` → send `SAFETY_BLOCKED`, log the violation, **turn ends**.
- `UNAVAILABLE` → send `ERROR` / `MODERATION_UNAVAILABLE`, **turn ends**.
- `SAFE` → the dispatch pipeline:

**Dispatch pipeline (E2.2) — all in-process**
1. Resolve **fixture-backed** authoritative state (`FixtureSandboxStateProvider`, in-memory, keyed by `sandbox_id + player_id`).
2. Build `IntentParserContext`.
3. Initialise the intent-parser router — **separate router from moderation**.
4. Call `IntentParserService.parse` → OpenRouter (Tier 1). May return a clarification request instead of actions.
5. `ActionDispatcher.dispatch()`.
6. Preflight the non-combat executors.
7. Execute the ordered READY actions in parser order, with **server-side dice** (`createDiceRoller`).
8. Apply all state deltas atomically (**in memory**).
9. Send `MECHANICAL_RESOLUTION` (dice results + state deltas).
10. Send `NARRATIVE_CHUNK` — **the stub string**.
11. Send `TURN_COMPLETE`.

Frames the handler can send: `sendError` / `sendErrorFrame`, `sendClarificationRequest`, `sendMechanicalResolution`, `sendNarrativeChunk`, `sendTurnComplete`.

**Deliberate omissions — say why in the response, do not draw them:**
- **The SSM dice-seeding read.** `loadSeedingFlag` issues `GetParameter`, but it is memoised at module scope — **once per container, never per turn** — and is dev-only. It is not part of a turn.
- **The narration model call and SSE stream.** Stub (defect 1).
- **Any DynamoDB state write.** Does not exist (defect 3).
- **pgvector / episodic retrieval.** Does not exist.

## Variables

change_ref: $1

- `change_ref` is optional. If supplied, treat it as the change that motivated this refresh and check it against the flow above.
- If omitted, re-derive the flow from `ws-message.ts` and confirm the diagram still matches.

## Artifacts (fixed paths — do not create others)

- Candidate specification: `docs/architecture/diagrams/player-ws-message-flow.sequence.json`
- Generated artifact: `docs/architecture/diagrams/player-ws-message-flow.html`

`visual-check` writes a receipt, a contact sheet, and screenshots next to the HTML, and **prunes stale sidecars in that directory**. Never author them by hand and commit none of them — see `docs/architecture/diagrams/README.md`. Delete them before finishing and quote the delivery SHA-256 values in the response instead.

Never hand-edit the generated HTML.

`player-api-lambdas.sequence.json` was a near-duplicate of this artifact and has been **deleted**; do not recreate it. Its only unique element was a `dispatcher → postgresql` episodic-vector query that does not exist in the code.

## Evidence sources (read these, in this order)

1. **`services/player-api/src/handlers/ws-message.ts`** — the authority for this diagram. The header comment lists the flow and the frame codes; the numbered `// ── n.` section comments mark the pipeline; **the code below each comment is what you draw, not the comment's aspirations.**
2. **`services/player-api/src/dispatcher/`** — `ActionDispatcher.ts`, the per-domain executors (`combatExecutor`, `spellExecutor`, `skillExecutor`, `movementExecutor`, `healingExecutor`), and `state.ts` for `FixtureSandboxStateProvider` (in-memory, no writes).
3. **`services/player-api/src/intent-parser/IntentParserService.ts`** — takes a `ModelRouter` in its constructor, which is what makes the Tier 1 call real.
4. **`services/player-api/src/moderation/`** — `ModerationService`, the Llama Guard call, and the verdict type.
5. **`services/player-api/src/util/ws-send.ts`** — `postToConnection`; the frames are sent over `@aws-sdk/client-apigatewaymanagementapi`.
6. **`services/player-api/src/dice/createDiceRoller.ts`** and **`config/seedingFlag.ts`** — server-side dice and the dev-only seeding gate.
7. **`packages/shared-types/`** — the frame and verdict schemas; prefer these names over prose in labels.

## Participants ↔ code

| Participant | Code | Notes |
|---|---|---|
| Browser | React / Zustand | Sends `PLAYER_INPUT`, receives frames |
| WS Gateway | API Gateway WebSocket | The hop into the Lambda is an **API Gateway invoke**, not a service call |
| `PLAYER_INPUT` Lambda | `handlers/ws-message.ts` | Named for what it is. It was previously called "Dispatcher", which read as a separate service — do not rename it back |
| `rpg_game_state` | DynamoDB | **Reads only** in this flow — the connection binding |
| OpenRouter | External | **Two distinct calls**: moderation (Llama Guard 3 8B) and intent parse (Tier 1) |

**The rules engine is a lane, not a peer — and the renderer forces that.** The sequence renderer **rejects self-messages**: a `from == to` message fails with `Message "…" spans 0px (minimum 60px)`. So an in-process step cannot be drawn as a self-arrow, and a lane is the only way to show it. That is why `rulesEngine` is still a participant. It must be labelled and noted as **in-process in the same Lambda** — never rendered like `openrouter`, which is a real network peer. Do not "fix" this by removing the lane; the pipeline is a headline behaviour.

## Schema and command differences from the architecture diagrams

- **`--repo-root` is architecture-only** and is rejected for sequence (`--repo-root is currently supported for architecture diagrams only.`). Drop it from every command here. Sequence participants carry no `sources`, so there is no line-number evidence for the schema to verify — which is also why it cannot flag a stale label for you.
- Participants are `{ id, type, label, sublabel }`; messages are `{ from, to, y, label, variant, note }` with a numeric `y`; segments are `{ from, to, label }` with numeric `y` bounds; activations are `{ participant, from, to, type }`.
- `variant` carries the semantic weight: `emphasis` for the primary request, `return` for responses, `security` for the identity/consumption steps, `default` otherwise. It is **styling only** — it cannot express "planned", so it must not be used to hedge a step that does not exist.
- `views` are optional focus presets; the current artifact has two and they are useful. Keep them aligned with the segments after any re-layout.

## Layout notes specific to this diagram

Measured on this repo's sequence diagrams:

| viewBox | aspect | 1440×900 | `minText` @1440 |
|---|---|---|---|
| 1400 × 800 | 0.571 | OK | 9.55 |
| 1400 × 900 | 0.643 | OK | 8.49 |
| 1400 × 920 | 0.657 | **overflow** | — |
| 1600 × 1000 | 0.625 | OK | 7.64 |
| 2000 × 1280 | 0.640 | OK | **5.97 — fails readability** |
| 960 × 1000 (**the pre-repair shape**) | 1.042 | **overflow, `scrollHeight` 1799** | 6.80 |
| 1400 × 840 (**this artifact today**, 0 cards) | 0.600 | OK, `scrollHeight` 900 | 8.53 |

Consequences:

- **The ceiling is aspect ≈ 0.64** and the width ceiling is readability at **~1800**. Grow by widening and heightening together at ~0.6 aspect, never by extending downward.
- **A narrow canvas is what broke this diagram.** 22 messages do not need 1000px of height — they need width. `authentication-api-sequence.json` fits 20 messages in 1400×800.
- **Height is set by the message count, not by taste:** `height ≥ 160 + 28 × (messages − 1) + 83`. For 22 messages that is 831, so `[1400, 840]` is already near-minimal. Trimming a message is the only way to buy height back.
- Sequence diagrams carry their own lifeline geometry and no region boundaries, which is why their ceiling is higher than the architecture/dataflow ~0.45–0.46. **Do not apply the architecture rule here** and compact the diagram for no reason.
- Participant columns: the artifact uses `column_fit: "spread"`. Prefer fewer participants — **do not split `rulesEngine` back out into a service, and do not add a participant for the executors.**
- Re-measure rather than assuming; the numbers above were taken on one revision.

## Commands

Read `/Users/phil/.pi/agent/skills/archify/SKILL.md` and follow its authoring workflow. Apply **one** geometry control per repair, then re-validate.

**No `--repo-root`:**

```bash
ARCHIFY=/Users/phil/.pi/agent/skills/archify/bin/archify.mjs

node $ARCHIFY validate sequence docs/architecture/diagrams/player-ws-message-flow.sequence.json --quality showcase --json
node $ARCHIFY deliver  sequence docs/architecture/diagrams/player-ws-message-flow.sequence.json docs/architecture/diagrams/player-ws-message-flow.html --quality showcase --json
node $ARCHIFY visual-check docs/architecture/diagrams/player-ws-message-flow.html --json
```

`validate` and containment are **separate gates** — `validate` does not model containment. Probe it before delivering:

```bash
node $ARCHIFY render sequence <spec>.json /tmp/probe.html --quality showcase
node $ARCHIFY visual-check /tmp/probe.html --json
```

`--quality standard` also renders and is a valid probe — geometry is profile-independent — but it is never acceptance evidence. Never deliver a candidate whose `visual-check` reports `overflowY`, and never report a non-zero exit as success.

**Do not run `deliver` until `validate` reports `ok: true` with all 9 checks and 0 errors.** If `deliver` exits non-zero it preserves the previous output, and running `visual-check` on that path would inspect the stale last-good artifact rather than the failed candidate.

## Keeping the diagram current

| Change | Update |
|---|---|
| A handler step added, removed, or reordered | The corresponding message(s), against the `// ── n.` section comments |
| **A stub replaced by a real implementation** | **Add the real step.** This is the live case: when the `F1 REPLACEMENT POINT` at `ws-message.ts:1193` becomes a real Tier 2/3 call, add the OpenRouter narration message and the streaming response, and update the card |
| Moderation verdicts or their handling changing | The moderation messages, the `SAFETY_BLOCKED` branch, and the `MODERATION_UNAVAILABLE` branch |
| A new frame type | A message per frame, named from `packages/shared-types`, not from prose |
| A new executor domain | Nothing — this diagram is flow, not mechanics. It belongs in the rules-engine child diagrams |
| State becoming durable (DynamoDB or Postgres) | **Add the read/write only when it is real**, and only for the access that exists. Do not add it in advance |
| A new participant | Check the width budget first; prefer folding into an existing lane |
| `viewBox` changing | Re-probe **both** budgets |

If `change_ref` is supplied, state which steps it affected and which it did not. Sequence specifications carry no `meta.repository.revision`; do not add one.

## Non-goals

- Do not draw future state. See the truth policy — this is the governing rule of this prompt.
- Do not restore the "Explicit Unknowns" card or any card enumerating unfinished design work.
- Do not add per-domain mechanics (combat rounds, spell slots, skill DCs). That is the rules-engine diagrams' job.
- Do not add the connection lifecycle (`$connect`, `$disconnect`, `PING`, `RESYNC_STATE`).
- Do not recreate `player-api-lambdas.sequence.json`.
- Do not touch the other diagrams or their prompts. In particular do not repair `authentication-api-sequence.json` from here — **flag its stale `/ws-ticket` mock** instead.
- Do not change application, infrastructure, or rules-engine code. A diagram refresh changes no engine behaviour, so `tests/integration/src/vector-matrix/vectors.ts` and `docs/rules-coverage/catalog.json` are **out of scope here** — state this reasoning rather than silently skipping the check.

## Done when

- **`validate --quality showcase` reports `ok: true`, all 9 artifact checks, 0 composition errors, 0 warnings.**
- **No message asserts a step that is not implemented**, and specifically: the narration is drawn as the stub string, moderation is drawn, and no DynamoDB state write is drawn.
- The identity-resolution read is drawn, and the rules engine is not drawn as a network peer.
- `visual-check` on the delivered HTML reports **readability OK** and **no `overflowY`** at 1440×900, 1600×1000, 1920×1080, and 2048×1320.
- `archify deliver` succeeded, and its receipt reports matching specification and artifact SHA-256 values.
- The only files changed are the candidate specification, the delivered HTML, and this diagram's row in `docs/architecture/diagrams/diagram-state.md`. Every `visual-check` sidecar has been deleted.
- This diagram's row in `docs/architecture/diagrams/diagram-state.md` records the date and commit actually verified against — not backdated, and equal to `meta.repository.revision` where the schema has it.
- `git diff --check` passes.

## Response

Return:

1. The artifact paths changed, and whether this was a geometry repair, a content repair, or both.
2. **Every message, with the handler line that proves it** — and an explicit statement that no unimplemented step is drawn, naming the narration stub as the case you checked.
3. Anything you deliberately did not draw, and why (the SSM seeding read, the narration model call, DynamoDB writes, pgvector).
4. The exact commands run with their real outcomes (validation check count and error/warning counts, delivery SHA-256 values, `visual-check` per-viewport results including 1440×900, and `minText`). Never report a non-zero exit as success.
5. Containment reported **separately** from readability.
6. Browser evidence and perceptual review reported **separately**. If the active model cannot view images, state that the perceptual review was not performed.
7. Anything unresolved — including whether the ticket-handshake segment is still duplicated with the authentication diagram, and whether that diagram's stale `/ws-ticket` mock has been repaired.
