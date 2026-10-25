---
description: Refresh the Cognito authentication and API authorization sequence diagram from current handler evidence
argument-hint: "[change-ref]"
---

# Refresh the Cognito authentication and API sequence diagram

Maintains one artifact: the Archify **sequence** diagram of how a browser proves identity to Mythical Forge and how each API entry point authorizes a request — Cognito signup hooks, login/MFA, token issuance and claim enrichment, and the REST API authorization paths.

This is a **documentation-refresh prompt**. It must not change application, infrastructure, or rules-engine code. If the diagram is wrong, the handlers and stacks are the source of truth and the diagram is what gets fixed.

Read `docs/architecture/diagrams/README.md` first. It holds the shared authoring contract — the layout budgets, the universal geometry rules, the truthfulness rules, and the delivery/freeze protocol. This prompt does not restate it. **Sequence diagrams differ from architecture diagrams in the schema, the commands, and the budgets**, and this prompt calls out each difference where it matters.

**Record the verification.** Update this diagram's row in `docs/architecture/diagrams/diagram-state.md` — the UTC date and the full commit SHA you verified against. A fabricated date there is worse than an empty one.

## Scope boundary: this diagram stops at authorization

The directory contains three overlapping sequence diagrams. Keeping them from becoming three copies of the same flow is the main editorial job of this prompt.

| Artifact | Owns |
|---|---|
| `authentication-api-sequence.json` (**this one**) | Identity and authorization: Cognito hooks, token issuance, claim enrichment, and how each **entry point** authorizes a request |
| `player-ws-message-flow.sequence.json` | The post-connect gameplay path: `PLAYER_INPUT` → identity resolution → moderation → intent parse → rules → narrate |

(`player-api-lambdas.sequence.json` covered the same participants and the same 18-step flow — its only unique element, a `dispatcher → postgresql` episodic-vector query, does not exist in the code — so it was deleted as a duplicate.)

**This diagram shows authorization in, gameplay out.** Concretely: show that the WebSocket `$connect` route is authorized by a single-use ticket and show the ticket being consumed — because that is an authorization mechanism — but do **not** show `PLAYER_INPUT` frames, moderation, intent parsing, the Action Dispatcher, or narration. Those belong to `player-ws-message-flow`.

That boundary is also a hard capacity constraint, not just tidiness: the WebSocket handshake plus a gameplay segment would add roughly 10 messages, and this diagram's vertical budget is nearly exhausted (see Layout notes). Do not absorb the gameplay flow into this diagram.

## Variables

change_ref: $1

- `change_ref` is optional. If supplied, treat it as the change that motivated this refresh and check whether it altered an auth hook, a token claim, an authorizer, or an entry point.
- If omitted, compare the current handlers and stacks against the committed specification.

## Artifacts (fixed paths — do not create others)

- Candidate specification: `docs/architecture/diagrams/authentication-api-sequence.json`
- Generated artifact: `docs/architecture/diagrams/authentication-api-sequence.html`
- Browser evidence sidecars. `visual-check` regenerates the receipt `.visual-check.json`, the contact sheet `.visual-check.html`, and the screenshots `.visual-check.<WxH>.<theme>.png` next to the HTML. Never author them by hand, and **commit none of them** — see the reasoning in `docs/architecture/diagrams/README.md`. Delete them before finishing and quote the delivery SHA-256 values in the response instead.

Never hand-edit the generated HTML. It is produced only by `archify deliver`.

## Update in place — do not re-author from scratch

The committed candidate is a **geometrically validated baseline**: **14 participants, 30 messages, 5 segments, 16 activations, 4 views, `viewBox [1705, 1060]`** (aspect 0.622), `column_fit: "spread"`. It validates 9/9 with 0 composition errors / 0 warnings and passes containment at every viewport — which says nothing about whether its labels are still true. The ticket flow it now draws replaced a mock integration that had been stale for months while validating green the whole time.

Always start by reading `docs/architecture/diagrams/authentication-api-sequence.json` and editing it. Preserve existing participant `id`s, and preserve the message `y` pitch (28px) and ordering unless the facts require a change.

**A stale diagram still validates.** `validate` checks the specification's internal consistency and geometry; it cannot tell you a message label describes behaviour that has since changed. A 9/9 pass is evidence about the drawing, not about the truth of its labels. Establish freshness from the handlers and stacks.

## Evidence sources (read these, in this order)

1. The three identity-stack triggers referenced by the signup and login segments — `services/player-api/src/handlers/` (`pre-signup`, `post-confirmation`, `pre-token`/`pre-token-generation`, `pre-auth`). These define the hook order, the group check, and the exact claim names.
2. `services/player-api/src/handlers/ws-ticket.ts` — the ticket issuer. Its header comment is the authoritative step list.
3. `services/player-api/src/handlers/ws-authorizer.ts` — the `$connect` Lambda authorizer, which is where ticket validation and connection binding actually happen.
4. `infra/lib/identity-stack.ts` — the User Pool, Hosted UI domain, Google IdP, the three groups, the trigger wiring, and which claims are injected.
5. `infra/lib/api-stack.ts` — which entry points exist and **how each one authorizes**: the Cognito `CognitoUserPoolsAuthorizer` on the Admin API, the CORS preflight on the Player API, the WebSocket API's `WebSocketAuthorizer`, and which routes carry an authorizer.
6. `infra/lib/network-stack.ts` / `data-stack.ts` only if a data-layer fact in a card changed.
7. Specs: `Design 19` (authentication and token semantics — note §4A, access token vs ID token), `Design 11`/`11.1` (the WebSocket API and the ticket handshake), `Design 16 §3A–§3B` (ingress moderation — **out of scope here**), `Design 18 §7A` (free tier / account tier claims).

Per the archify authoring contract, sequence participants do **not** carry `sources`, so there is no line-number evidence to maintain. That also means the schema cannot mark a stale label for you — the freshness check is reading the handlers.

## Participants ↔ code (current baseline)

| Participant | `type` | Real thing | Segment |
|---|---|---|---|
| `browser` | external | The SPA / browser client | all |
| `cognito` | security | Cognito User Pool + Hosted UI | 1, 2, 3, 5 |
| `preSignup` | backend | Pre Sign-up trigger — account linking, disposable-email rejection | 1 |
| `postConfirmation` | backend | Post Confirmation trigger — Players group, account metadata | 1 |
| `preAuth` | backend | Pre-Authentication trigger — MFA enforcement for Authors/Admins | 2 |
| `preToken` | backend | Pre Token Generation trigger — custom claims | 2 |
| `accountState` | database | `rpg_account_state` (account-scoped) | 1, 2 |
| `playerApi` | backend | Player REST API Gateway | 3 |
| `wsTicket` | backend | `WsTicket` Lambda behind `POST /ws-ticket` | 3 |
| `wsApi` | backend | WebSocket API Gateway | 4 |
| `wsAuthorizer` | backend | `$connect` Lambda authorizer (labelled **`WS Authz`** — see Layout notes for why) | 4 |
| `gameState` | database | `rpg_game_state` (sandbox-scoped) — **a different table from `accountState`** | 3, 4 |
| `adminApi` | backend | Admin/Author REST API Gateway | 5 |
| `rulesEngine` | backend | `RulesEngineApi` Lambda behind `ANY /{proxy+}` | 5 |

The segment structure is: **1** signup and provisioning (y 150–310), **2** login, MFA and token issuance (330–510), **3** player ticket issuance (530–645), **4** WebSocket `$connect` authorization (660–850), **5** Admin API authorization and invocation (870–1000).

Note the identity stack provisions **four** trigger Lambdas; `identity-stack.c4.test.ts` and the infra allowlist both refer to them. Only the three that participate in the browser-visible flow appear here. If a trigger gains a browser-visible effect, add it.

## Schema and command differences from the architecture diagrams

These are the differences most likely to cost time:

- **`--repo-root` is architecture-only.** For sequence diagrams it is **rejected** with `--repo-root is currently supported for architecture diagrams only.` Run every command in this prompt **without** it.
- **`meta.viewBox` is required in practice** and is a real authoring control here, unlike the infrastructure diagram where it is derived. Its minimum permitted value is `480` per axis, and content beyond it is clipped.
- **Message `y` has a schema minimum of `160`**, which reserves the top band for the participant header boxes.
- **`meta.column_fit`**: omit for the stable `fixed` layout (86px boxes, 108px gaps); use `"spread"` when a wide viewBox would otherwise leave unused horizontal space, or when labels do not fit. This diagram uses `spread` legitimately: at 14 participants the `fixed` layout needs `14×86 + 13×108 = 2608px`, but the viewBox is 1705 wide. **Re-derive this arithmetic whenever the participant count changes** — it is the justification for the setting. At 14 participants `spread` is near its limit: the column pitch is already only ~122px, so **a 15th participant means removing one or widening past the label cap** (see Layout notes).

## Layout notes specific to this diagram

**The vertical budget binds; the horizontal one is capped by the longest participant label.** Measured by varying only the viewBox:

| viewBox | aspect | 1440×900 | `minText` @1440 | verdict |
|---|---|---|---|---|
| 1400 × 800 (pre-repair) | 0.571 | OK | 9.55 | comfortable |
| 1400 × 900 | 0.643 | OK | 8.49 | at the ceiling |
| 1400 × 920 | 0.657 | **overflow** (scrollH 1077) | — | fails |
| 1600 × 1000 | 0.625 | OK | 7.64 | good growth target |
| 1800 × 1150 | 0.639 | OK | 6.65 | near the width limit |
| 1800 × 1000 | 0.556 | OK | 7.64 | safest |
| 2000 × 1280 | 0.640 | OK | **5.97** | **fails readability** |
| **1705 × 1060 (this artifact today)** | 0.622 | OK | 7.21 | current |

Read off from that:

- **Sequence diagrams tolerate roughly aspect ≤ 0.64**, not the ≤ 0.45 the README states for architecture. The README's aspect rule is derived from architecture layouts and does not transfer.
- **Width is the readability constraint, as in architecture**: `minText` falls roughly linearly with `viewBox` width and crosses the 6.0 floor somewhere past 1800. Stay at or below ~1800.
- The conclusion is a narrow corridor: **aspect ≤ 0.64 and width ≤ the label cap below.** Growing the diagram means growing width and height together (≈0.6 aspect), not extending downward.

### The width ceiling is set by the longest label, not by taste

**The renderer shrinks a participant label's font to fit its box, and `validate`'s readability model uses that shrunk size.** The model is `930 / viewBoxWidth × sourceFontPx ≥ 6` against 930px of assumed available width, and `sourceFontPx` is whatever the label was shrunk to — so **one long label lowers the ceiling for the whole diagram.** This is the single most expensive trap in this file, and it cost a full re-layout to find:

- With `WS Authorizer` (13 characters) the label font fell to **10.3px**, which capped the viewBox at **~1550** — too narrow for 30 messages at the height they require (aspect 0.68). The two budgets became mutually unsatisfiable.
- Renaming it to **`WS Authz`** restored an **11px** font and lifted the cap to **~1705**, which fits 30 messages at aspect 0.622.

So: before widening a sequence diagram, read `diagnostics[].evidence.text` — the offending string is named, along with its `sourceFontPx` and `projectedFontPx`. **Shortening that one label is usually far cheaper than re-laying out the diagram.** If a long label is unavoidable, the diagram must be shortened instead (fewer messages, or a segment split into its own artifact).

- **Height is set by the message count, and there is no slack left.** Content ends at y 1000 (last segment) / 972 (last message) inside a height-1060 viewBox, on a uniform **28px pitch**: `height ≥ 160 + 28 × (messages − 1) + 83`. At 30 messages that is 1055, so `[1705, 1060]` is already near-minimal. **A 31st message forces the viewBox taller, which forces it wider (aspect ≤ 0.64), which pushes against the ~1705 label cap.** Adding a message now means removing one.

Other structural facts worth preserving:

- Segments are **visual bands, not strict brackets**: the first message in a segment can sit slightly outside its band (e.g. the token request at y 328 against a segment starting at 330). Keep the band boundaries on clean round numbers and do not chase exact containment.
- Activations are **tight to their messages** — each starts a few pixels above its first message and ends a few pixels past its last (e.g. `preSignup` 182–224 for messages at 188 and 216). When you move a message, move its activation with it, and keep one activation span per contiguous interaction rather than one per message.
- `cognito` appears as **two separate activation spans** (154–316 and 322–508), one per segment. That is deliberate — the pool is a new interaction in each segment. Do not merge them.
- `variant` carries the auth semantics: `security` for credential/token exchanges, `return` for every response, `emphasis` for the primary request paths, `default` for internal reads. **`dashed` is no longer used** — it marked the mock integration, and there is no mock any more. Do not decorate.

## History note: the mock is now real

The committed artifact used to show the player endpoint as a **mock integration** — `POST /ws-ticket: current mock integration` / `200 mock; no Lambda invoked` — with no WebSocket authorization model at all. That is fixed: the artifact now draws the real ticket flow and the `$connect` authorization. Do not reintroduce the mock wording, and do not "simplify" the ticket flow back to two messages.

| Was stale | Reality |
|---|---|
| `player-api-request`: "POST /ws-ticket: current mock integration" | A real `LambdaIntegration` backed by the `WsTicket` Lambda, with a CORS preflight for the browser's non-simple request |
| `player-api-response`: "200 mock; no Lambda invoked" | The Lambda **is** invoked; it returns `200 { ticket, expires_in: 20 }` |
| `views[2].note`: "The player endpoint is currently a mock" | Rewritten, and a fourth view now covers the WebSocket authorization |
| No `wsTicket` participant, no game-state participant | `WsTicket` validates the access token and writes a 20-second ticket to `rpg_game_state` |
| No WebSocket authorization model at all | `$connect` carries a `WebSocketAuthorizer` — a distinct third authorization model |

The verified flows, for reference when re-checking freshness. Ticket issuance, from `ws-ticket.ts` (access token, not ID token — Design 19 §4A):

1. browser → `playerApi`: `POST /ws-ticket`, `Authorization: Bearer <access token>` plus `{ sandbox_id }`, preceded by a CORS `OPTIONS` preflight
2. `playerApi` → `wsTicket`: Lambda proxy integration
3. `wsTicket` → `cognito`: verify the access token (JWKS, via `shared-auth`)
4. `wsTicket` → `gameState`: `PutItem TICKET#<tkt_...>`, `ttl = 20s`, `used = false`
5. `wsTicket` → browser: `200 { ticket, expires_in: 20 }`

And `$connect` authorization, from `ws-authorizer.ts`:

6. browser → `wsApi`: `wss://...?ticket=<tkt_...>&sandbox_id=<id>`
7. `wsApi` → `wsAuthorizer`: invoke the Lambda authorizer
8. `wsAuthorizer` → `gameState`: `GetItem TICKET#<ticket>`
9. `wsAuthorizer` validates: `sandbox_id` matches the query string, `used === false`, and `ttl > now` **explicitly** (DynamoDB TTL deletion can lag up to 48 hours)
10. `wsAuthorizer` → `gameState`: `TransactWriteItems` — set `used = true` with `ConditionExpression: used = false`, and put `CONNECTION#<connectionId>`
11. `wsAuthorizer` → `wsApi`: `Allow` with `userId` + `sandboxId` context (or `Deny`)
12. `wsApi` → browser: `101 Switching Protocols`

**Two facts that are load-bearing and easy to lose in a re-layout:**

- The ticket is consumed **atomically in one `TransactWriteItems` alongside the connection binding**, so the `$connect` route handler does not re-read or re-write it — **do not draw a second ticket write.**
- **`rpg_account_state` and `rpg_game_state` are different tables with different scoping** (account-scoped vs sandbox-scoped), so `accountState` and `gameState` must stay distinct participants. That distinction is an architectural invariant, not a detail.

The ticket issuer's sandbox-ownership check is still a `TODO(Phase 4)` stub that accepts any non-empty `sandbox_id`, and the artifact says so in the message note. That is the truth policy working correctly — **draw the stub as it behaves, and label it.**

## Commands

Read `/Users/phil/.pi/agent/skills/archify/SKILL.md` and follow its authoring workflow. Write the candidate before inspecting renderer internals.

**No `--repo-root`** (see Schema differences):

```bash
ARCHIFY=/Users/phil/.pi/agent/skills/archify/bin/archify.mjs

node $ARCHIFY validate sequence docs/architecture/diagrams/authentication-api-sequence.json --quality showcase --json
node $ARCHIFY deliver  sequence docs/architecture/diagrams/authentication-api-sequence.json docs/architecture/diagrams/authentication-api-sequence.html --quality showcase --json
node $ARCHIFY visual-check docs/architecture/diagrams/authentication-api-sequence.html --json
```

Containment probe while designing (use it before delivering — the vertical budget is the one that fails):

```bash
node $ARCHIFY render sequence <spec>.json /tmp/probe.html --quality showcase
node $ARCHIFY visual-check /tmp/probe.html --json
```

## Keeping the diagram current

| Change | Update |
|---|---|
| New or removed Cognito trigger, or a changed hook order | The participant set and the signup/login segments together |
| A changed claim injected or read (`account_tier`, `opted_in_betas`, groups) | The relevant message labels and their card |
| A changed MFA rule or group check | The `mfa-check` message label |
| A new or removed **entry point** (API, protocol) | A new participant plus its authorization model — the WebSocket `$connect` authorizer entered the diagram this way |
| A changed authorization mechanism on an existing entry point | The authorizer message label (`jwt-authorize`, the ticket consumption) |
| A route gaining or losing an authorizer | The corresponding message; note that on the WebSocket API **only `$connect` carries the authorizer** |
| Another endpoint gaining or losing a Lambda | Add the participant and its invocation message — this is exactly what the `/ws-ticket` repair did |
| Access token vs ID token semantics changing | The ticket-issuance message label — this is load-bearing and easy to get wrong |
| A brand mark for Cognito becoming available | Optional; never let a badge replace the semantic `type` or the label facts |

Three standing truthfulness rules:

- **Model deployed behaviour, not the target design.** Several handlers are explicitly stubs (the `$default` route is "a stub for Epic B"; the sandbox-ownership check in the ticket issuer is a `TODO(Phase 4)` that currently accepts any non-empty `sandbox_id`). Draw the stub as it behaves, and say so in the label or a card — do not draw the intended behaviour, and do not omit the step because it is incomplete.
- **Do not let this diagram absorb the gameplay flow.** See the scope boundary. If a change makes you want to add `PLAYER_INPUT`, moderation, or narration here, that change belongs in `player-ws-message-flow`.
- **This diagram is the only place the three authorization models are shown side by side** — JWT authorizer (Admin API), in-Lambda access-token verification (Player API), and single-use ticket via Lambda authorizer (WebSocket `$connect`). That contrast is the artifact's reason to exist; preserve it through any refresh.

If `change_ref` is supplied, state which segments it affected and which it did not. If nothing changed, update nothing and say why — this specification has no `meta.repository.revision` field, so there is not even a revision to bump. Sequence diagrams carry no revision field; do not add one.

## Non-goals

- Do not touch `player-ws-message-flow.sequence.json` from this prompt; it owns the gameplay path, which is out of scope here.
- Do not touch the rules-engine diagrams, the infrastructure diagram, or the dataflow diagram.
- Do not change application, infrastructure, or rules-engine code.
- Do not add, remove, or rename a Rules Engine API action or an SRD claim. A diagram refresh changes no engine behaviour, so `tests/integration/src/vector-matrix/vectors.ts` and `docs/rules-coverage/catalog.json` are **out of scope here** — they follow the action or claim that motivated the change. State this reasoning rather than silently skipping the check.
- Do not add a revision field, `sources` to participants, or a segment for gameplay.
- Do not grow the viewBox past aspect ~0.64 without re-probing, and do not widen it past the **label-font cap** (~1705 as it stands — see Layout notes). This diagram has no height slack: adding a message means removing one.

## Done when

- Every participant maps to a real component, and every message is a real handler step, authorizer decision, or documented endpoint behaviour — with no invented step and no leftover "mock" wording.
- `archify validate sequence … --quality showcase` passes: all 9 artifact checks, 0 composition errors, 0 warnings. (A receipt with only 4 checks is basic validation, not a showcase pass.)
- The containment probe passes **before** delivery at 1440×900, and readability `minText` stays above 6.
- `archify deliver` succeeded, and its receipt reports matching specification and artifact SHA-256 values.
- `visual-check` was run against the exact delivered artifact — without `--repo-root` — and reports no overflow and readability OK at 1440×900, 1600×1000, 1920×1080, and 2048×1320.
- The only files changed are the candidate specification, the delivered HTML, and this diagram's row in `docs/architecture/diagrams/diagram-state.md`. Every `visual-check` sidecar has been deleted.
- This diagram's row in `docs/architecture/diagrams/diagram-state.md` records the date and commit actually verified against — not backdated, and equal to `meta.repository.revision` where the schema has it.
- `git diff --check` passes.

If a handler's real behaviour contradicts the design document cited in its own header comment, or the ticket flow cannot be reconciled with `infra/lib/api-stack.ts` route wiring, **stop and ask** rather than picking one.

## Response

Return:

1. The artifact paths changed, and whether this was a refresh-in-place or a re-layout.
2. Each participant and message verified, with the handler or stack file that proves it — and explicitly, whether the mock-to-real gap is now closed and whether the three authorization models are all present.
3. The exact commands run with their real outcomes (validation check count, error/warning count, delivery SHA-256 values, `visual-check` per-viewport results, and both readability and containment numbers). Never report a non-zero exit as success.
4. Browser evidence and perceptual review reported **separately**. If the active model cannot view images, state that the perceptual review was not performed.
5. Anything unresolved, assumed, or deliberately out of scope — including any remaining overlap with `player-ws-message-flow.sequence.json`.