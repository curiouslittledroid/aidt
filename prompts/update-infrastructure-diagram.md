---
destination: mythical-forge/aidw/prompts/
description: Refresh the AWS CDK infrastructure architecture diagram from the synthesized CloudFormation templates
argument-hint: "[change-ref]"
---

# Refresh the AWS infrastructure architecture diagram

Maintains one artifact: the Archify architecture map of the Mythical Forge AWS deployment — the client entry points, the regional service topology, and the private data plane, as defined by the CDK app in `infra/`.

This is a **documentation-refresh prompt**. It must not change infrastructure, application, or rules-engine code. If the diagram is wrong, `infra/` is the source of truth and the diagram is what gets fixed.

Read `docs/architecture/diagrams/README.md` first. It holds the shared authoring contract — the two budgets, the universal geometry rules, the layout archetypes, the truthfulness rules, and the delivery/freeze protocol. This prompt does not restate it.

**Record the verification.** Update this diagram's row in `docs/architecture/diagrams/diagram-state.md` — the UTC date and the full commit SHA you verified against. That row currently records a **known-stale** diagram; clear that note only once the WebSocket API and the real `/ws-ticket` flow are actually drawn. A fabricated date there is worse than an empty one.

## Scope boundary: diagram vs. inventory

`docs/architecture/Infrastructure Architecture.md` is the **canonical AWS resource inventory** and owns the per-stack resource tables, deployment order, and cross-stack props. `aidt/prompts/update-architecture.md` maintains it.

This prompt owns only the **diagram**. The two are allowed to differ in **granularity** — the document enumerates resources, the diagram shows topology — but never in **facts**. If they disagree about what exists, what connects to what, or which environment has which capability, that is a defect in one of them: **stop and flag it** rather than silently picking a side or "fixing" the diagram to match.

## Variables

change_ref: $1

- `change_ref` is optional. If supplied, treat it as the change that motivated this refresh and check whether it introduced or removed a service, an entry point, or a trust boundary.
- If omitted, diff the current `infra/` app against the committed artifact.

## Artifacts (fixed paths — do not create others)

- Candidate specification: `docs/architecture/diagrams/infrastructure-diagram.json`
- Generated artifact: `docs/architecture/diagrams/infrastructure-diagram.html`
- Browser evidence sidecars. `visual-check` regenerates the receipt `.visual-check.json`, the contact sheet `.visual-check.html`, and the screenshots `.visual-check.<WxH>.<theme>.png` next to the HTML. Never author them by hand, and **commit none of them** — see the reasoning in `docs/architecture/diagrams/README.md`. Delete them before finishing and quote the delivery SHA-256 values in the response instead.

Never hand-edit the generated HTML. It is produced only by `archify deliver`.

## Update in place — do not re-author from scratch

The existing candidate specification is a **geometrically validated baseline**: 12 components, 11 connections, 2 boundaries (one nested), 3 cards. It validates 9/9 with 0 errors / 0 warnings — and it is currently **known-stale anyway**, which is the clearest possible demonstration that a green `validate` is not evidence of freshness. See the outstanding-gap note below.

Always start by reading `docs/architecture/diagrams/infrastructure-diagram.json` and editing it. Preserve every existing component `id`, `pos`, `size`, and every connection's routing controls unless the facts require a change.

**A stale diagram still validates.** `validate` checks the specification against its own declared `sources`; it cannot tell you the topology is out of date. A 9/9 pass on this artifact is evidence that the citations resolve, and nothing more. Establish freshness from `cdk synth` and the stack source, never from a green `validate`.

## The granularity rule (the most important thing in this prompt)

The dev environment synthesizes **211 resources across 6 stacks**, and the diagram shows **12 nodes**. That ratio is deliberate and must stay roughly stable. Measured inventory at the pinned revision:

| Stack | Resources | Notable |
|---|---|---|
| `Api` | 71 | 2 REST APIs, 1 WebSocket API, 6 WS routes, 1 WS authorizer, 8 Lambdas, usage plan |
| `Network` | 66 | VPC, 9 subnets (3 tiers × 3 AZs), 3 NACLs, 20 NACL entries, IGW, **no NAT, no VPC endpoints** |
| `Identity` | 26 | User Pool, client, Hosted UI domain, 3 groups, Google IdP, 4 trigger Lambdas, account table |
| `Data` | 25 | RDS instance, game-state table, DB security group, 4 secrets, SSM param, 2 custom resources |
| `Compute` | 18 | 7 Lambdas (dispatcher + 5 workers + rules API), 1 EventBridge rule |
| `Cdn` | 5 | S3 bucket, bucket policy, CloudFront distribution, OAC |
| `SrdData` | — | **not synthesized by default** — opt-in via the `seedSrd` context flag |

Therefore the diagram changes when one of these appears or disappears:

- a **new service** (a new AWS resource *type* at the entry-point or data layer),
- a **new entry point** (a new API, a new route that carries a distinct protocol or auth model),
- a **new trust or network boundary** (a new security group, subnet tier, or account-scope change),
- a **removed** one of the above.

It does **not** change when a resource is added, renamed, or resized *inside* an existing group — a new Lambda in the compute worker set, another IAM policy, another NACL entry, a bigger instance class. Do not enumerate. A refresh that turns 12 nodes into 40 has misread this section.

## Evidence sources (read these, in this order)

1. `infra/bin/infra.ts` — **the authoritative dependency graph**: which stacks exist, their deploy order, and exactly which props cross between them. This is the file that defines the diagram's edges.
2. `infra/lib/config.ts` — the environment table (3 accounts, `ap-southeast-2`, `multiAz`, RDS instance class, log retention, Hosted UI domains, `playerWebOrigins`, free-tier turns). Feeds the environment facts in the cards.
3. The stacks, each mapping to a component or cluster: `network-stack.ts`, `data-stack.ts`, `compute-stack.ts`, `identity-stack.ts`, `api-stack.ts`, `cdn-stack.ts`, `srd-data-stack.ts`, plus `secrets.ts`, `custom-resources/{enable-pgvector,provision-core-schema}.ts`, and `websocket-lambda-integration.ts`.
4. **`cdk synth` — the ground truth.** This app synthesizes **without AWS credentials by design** (the VPC pins explicit AZs specifically so `ec2:DescribeAvailabilityZones` is never called at synth time), so this check runs anywhere:

   ```bash
   pnpm --filter infra cdk synth -c env=dev
   ```

   Confirm the resource list from `infra/cdk.out/*.template.json` — count by `Type`, and read `Description` on the Lambdas to see what each one actually does. **Do not run `pnpm exec cdk synth` from inside `infra/`**: CDK bundles the NodejsFunction assets from the workspace root, where `esbuild` is not linked, and it fails with `Command "esbuild" not found`. The `--filter` form is the one CI uses and the one that works. `infra/cdk.out/` is gitignored; leave it alone.
5. `docs/architecture/Infrastructure Architecture.md` §2 (deployment order + stack dependency diagram) and §10 (cross-stack references) — the canonical prose inventory. §2's dependency diagram and this artifact should describe the same graph.
6. Specs, for the facts the cards assert: `Design 07`/`07.1`/`07.2` (the database cost stack, reserved-concurrency budgets, throttling, no-NAT rationale), `Design 11`/`11.1` (WebSocket API and the ticket handshake), `Design 18 §7` (free-tier reset schedule), `Design 20` (secret placement), `Design 21 §7` (monorepo/infra placement).

## Component ↔ stack mapping (current baseline)

| Node | `type` | Stack | What it stands for |
|---|---|---|---|
| `clients` | external | — | Browser clients: Player / Author / Admin |
| `edge` | cloud | `CdnStack` | CloudFront + private versioned S3 bucket via OAC |
| `apis` | backend | `ApiStack` | Player + Admin/Author REST APIs, usage-plan throttling, Cognito authorizer on Admin |
| `cognito` | security | `IdentityStack` | User Pool, Hosted UI, Google IdP, groups, custom JWT claims |
| `identity` | backend | `IdentityStack` | The 4 Cognito trigger Lambdas (pre-signup, post-confirmation, pre-token, pre-auth/MFA) |
| `dynamo` | database | `IdentityStack` + `DataStack` | `rpg_account_state` **and** `rpg_game_state` — two tables, two stacks, one node |
| `rules` | backend | `ComputeStack` | `RulesEngineApi` — VPC-attached, reserved concurrency 25, IAM DB auth |
| `eventbridge` | messagebus | `ComputeStack` | The monthly HNSW reindex cron rule |
| `workers` | backend | `ComputeStack` | Action Dispatcher (125) + the background worker set + reindex worker |
| `dbaccess` | cloud | `DataStack` | RDS Proxy (opt-in, non-dev only) and the SSM endpoint parameter |
| `postgres` | database | `DataStack` | RDS PostgreSQL 16, pgvector, core schema, custom resources |
| `secrets` | security | `DataStack` + `secrets.ts` | Third-party secrets (OpenRouter, Stripe), RDS master secret, DB endpoint SSM |

Reconciliation rules:

- **`workers` and `identity` are each a consolidated group.** The node stands for a *worker set*, not one function. Keep them consolidated; enumerate the members in the `sublabel` or a card, never as separate nodes.
- **`apis` currently means the two REST APIs.** If the WebSocket API is added (see below), give it its own node rather than widening `apis` — it is a distinct entry point with a distinct auth model, and folding it in would hide the thing worth showing.
- **`dynamo` spans two stacks** because `rpg_account_state` is provisioned in `IdentityStack` (it holds account/billing state, which is account-scoped, and the identity triggers write it) while `rpg_game_state` is in `DataStack` (sandbox-scoped). That split is real, not an error — keep both `sources` entries.
- **`NetworkStack` has no component** — the VPC is carried by the region boundary's label and the security-group boundary. A 66-resource VPC is exactly the kind of thing the granularity rule says not to enumerate.
- **`SrdDataStack` has no component.** It is opt-in, excluded from `cdk deploy --all`, and absent from a default synth. That is why it is not drawn. If it is ever folded into the default pipeline, it earns a node.

## Layout notes specific to this diagram

This is a **2D topology**, not a pipeline or a fan-out — it matches **neither** README archetype. The consequences are specific and worth knowing before editing:

- **`meta.viewBox` is absent**, so the renderer derives it from content bounds: currently **1349 × 734**, aspect **0.544**. That is the **tallest aspect ratio and the thinnest readability margin of any diagram in this family** (`minText` 6.41 at 1440×900, against a floor of 6, and a README guidance of ≤0.45 aspect / ≤1290 width). It passes, but with almost no room. **Any addition needs compensating compaction**, and the compensation must be found by measuring, not by guessing — see the probe loop in the README.
- **An explicit `meta.viewBox` can only pad, never crop.** It must be at least the content bounding box *including boundary padding*; a smaller value clips content. So it is not a lever for fitting a bigger topology — moving nodes closer is.
- Columns sit at `x` = 40, 250, 470, 730, 1030; rows at `y` = 100, 270, 360, 570. `clients` sits alone at `[40, 360]`, vertically mid-band, which is what lets the three client edges fan without crossing.
- **Two boundaries, nested:** a `region` boundary with `pad: 34` wrapping everything except `clients`, and a `security-group` boundary with `pad: 24` wrapping `rules`, `dbaccess`, `postgres` (the shared DB security group). The inner one sits inside the outer one and wraps a *subset* of it — that is legitimate. The outer must still not enclose `clients`, and both must fit inside the viewBox.
- **Most labels need explicit placement.** 7 of 11 connections carry `labelAt`, and two carry `via` waypoints (`client-auth` routes around the middle; `secret-db` detours along `y = 700` because the direct path is blocked). This is the cost of a topology: the README's default "label at the start of the route" lands on top of the source node whenever the route leaves sideways. Expect to place labels explicitly here rather than tuning `labelDy`.
- Connection `variant` is in use and carries meaning: `emphasis` for the two primary client entry paths, `security` for the identity/secret edges, `dashed` for the scheduled one. Preserve them.

## Outstanding gap at authoring time

**The committed artifact is stale, and the next refresh is therefore larger than a normal one.** The diagram and `docs/architecture/Infrastructure Architecture.md` §7 both still describe `POST /ws-ticket` as a **mock integration**, and neither shows the WebSocket API, which now exists in `ApiStack`.

What `infra/lib/api-stack.ts` actually builds today:

| Reality | Evidence |
|---|---|
| `POST /ws-ticket` is a real Lambda, not a mock — CORS-enabled, `authorizationType` via the player API | `api-stack.ts` §1, `WsTicket` function |
| A **WebSocket API** (`WebSocketApi` + `WebSocketStage`, `$request.body.action`) with a **Lambda authorizer** that validates and atomically consumes the 20-second ticket | §4a/§4b |
| **6 routes** → 6 handlers: `$connect`, `$disconnect`, `$default`, `PLAYER_INPUT`, `PING`, `RESYNC_STATE` | §4d; confirmed by synth (`AWS::ApiGatewayV2::Route` = 6) |
| A **custom integration construct**, `WebSocketLambdaIntegration`, because CDK ships no built-in one and the construct does **not** auto-create `AWS::Lambda::Permission` | `websocket-lambda-integration.ts` |
| **8** Lambdas total in `ApiStack` (ticket + authorizer + 6 routes); the ticket and authorizer write/consume `rpg_game_state`; `WsMessage` reads the OpenRouter secret | synth: `AWS::Lambda::Function` = 8 |

Expected shape of the fix — **verify it against the source, do not assume it**: a new entry-point node for the WebSocket API beside `apis`, reusing the existing `clients`, `dynamo`, and `secrets` nodes rather than duplicating them, with edges for the two-step handshake (browser → `POST /ws-ticket` → ticket in `rpg_game_state`; browser → `wss://` with the ticket → authorizer consumes and binds). **The 8 Lambdas must not become 8 nodes** — the granularity rule forbids it. Consolidate to one node (at most two, if the authorizer earns its own for the auth story).

**Delete this section once the diagram shows the WebSocket API.** It describes a specific gap, not a standing rule; the standing rule is the WebSocket row in the "Keeping the diagram current" table below.

## Commands

Read `/Users/phil/.pi/agent/skills/archify/SKILL.md` and follow its authoring workflow. Write the candidate before inspecting renderer internals. The validate / probe / deliver / visual-check commands, the `--repo-root .` requirement, and the freeze and delivery protocol are all in `docs/architecture/diagrams/README.md`.

Substitute this diagram's paths:

- spec: `docs/architecture/diagrams/infrastructure-diagram.json`
- artifact: `docs/architecture/diagrams/infrastructure-diagram.html`

Re-check `sources` line numbers whenever an `infra/lib` file is edited: they are verified against `--repo-root`, and every one of them currently resolves.

## Keeping the diagram current

| Change in `infra/` | Update in the diagram |
|---|---|
| New stack in `bin/infra.ts` | A new cluster/boundary, or a new node — with `sources` pointing at the stack and the wiring line |
| New resource *type* at an entry point (new API, new protocol) | A new node, plus its connections. This is the WebSocket case |
| New or changed cross-stack prop in §10 | The corresponding connection label |
| New / removed Lambda inside the compute worker set | `workers` `sublabel` or a card — **not** a node |
| Changed reserved concurrency | The relevant node's `tag` |
| Changed `config.ts` environment table (accounts, region, instance class, multiAz, origins) | Boundary label and card copy |
| Changed subnet / CIDR / NACL / security-group rules | The boundary labels; a new boundary only if a **new tier or group** appears |
| RDS Proxy opt-in / dev exemption changed | `dbaccess` `sublabel` and the private-data-plane card |
| New custom resource or DDL version bump | `postgres` `sublabel` or a card — not a node |
| A new third-party secret | `secrets` `sublabel` |
| A service removed | Remove the node **and** every connection touching it |

Three standing truthfulness rules for this diagram, each of which has a way of going quietly wrong:

- **Deployed-as-stub is not the same as not-built.** Several Lambdas run placeholder or no-op bodies (`PLACEHOLDER_CODE`, `REINDEX_STUB_CODE`) — they are real, deployed resources and belong in the diagram. Conversely, anything that exists only in a design document does not. Do not add a node for a proposed tier, and do not remove a node because the code behind it is a stub. Say which is which in the node `tag` or a card.
- **Do not draw deferred scope.** Web Application Firewall/Bot Control, multi-region, Aurora Serverless v2, Neptune, and OpenSearch are deliberate non-goals (`AGENTS.md` §7). Their absence is the design, not staleness.
- **`NetworkStack`'s no-NAT, no-VPC-endpoint posture is intentional and load-bearing** (a NAT-free App tier with the dev bastion in a public subnet, explicitly to avoid ~$103/month of SSM interface endpoints). Do not "complete" the topology by adding NAT gateways or endpoints.

If `change_ref` is supplied, state explicitly which nodes it affected and which it did not. If nothing reached the service / entry-point / boundary level, change nothing beyond `meta.repository.revision` — or leave the artifact untouched and say why.

## Non-goals

- Do not touch the rules-engine diagrams or their prompts. `/update-rules-engine-diagram` and its five children own those.
- Do not change `infra/`, application code, tests, or `Infrastructure Architecture.md`. If the prose inventory is also stale, say so in the response and let `/update-architecture` apply it — editing both from here is how the two views drift.
- Do not add, remove, or rename a Rules Engine API action or an SRD claim. A diagram refresh changes no engine behaviour, so `tests/integration/src/vector-matrix/vectors.ts` and `docs/rules-coverage/catalog.json` are **out of scope here** — they follow the action or claim that motivated the change and belong to that change's own task. State this reasoning rather than silently skipping the check.
- Do not enumerate resources, add per-Lambda nodes, or draw designed-but-unbuilt resources.
- Do not widen or heighten the derived viewBox without re-probing; both budgets are nearly exhausted (see Layout notes).

## Done when

- Every node maps to a real stack or resource group, and every edge is either a cross-stack prop from `bin/infra.ts` or a network path documented in the source — with no invented connection.
- `pnpm --filter infra cdk synth -c env=dev` exits 0, and each node in the diagram is corroborated by a resource in `infra/cdk.out/`.
- `archify validate` passes with `--quality showcase`: all 9 artifact checks, 0 composition errors, 0 warnings.
- The containment probe passes **before** delivery, and both budgets hold: containment clean and readability with margin at 1440×900 despite the 0.544 aspect ratio.
- `archify deliver` succeeded, and its receipt reports matching specification and artifact SHA-256 values.
- `visual-check` was run against the exact delivered artifact and reports no overflow and readability OK at 1440×900, 1600×1000, 1920×1080, and 2048×1320.
- `meta.repository.revision` matches the full 40-hex commit documented.
- The only files changed are the candidate specification, the delivered HTML, and this diagram's row in `docs/architecture/diagrams/diagram-state.md`. Every `visual-check` sidecar has been deleted, and `infra/cdk.out/` is untouched.
- This diagram's row in `docs/architecture/diagrams/diagram-state.md` records the date and commit actually verified against — not backdated, and equal to `meta.repository.revision` where the schema has it.
- `git diff --check` passes.

If `cdk synth` reports a resource the diagram would have to contradict, or the diagram and `Infrastructure Architecture.md` disagree about a fact, **stop and ask** rather than picking one.

## Response

Return:

1. The artifact paths changed, and whether this was a refresh-in-place or a re-layout.
2. What was verified against `cdk synth` (stack count, resource counts by type) and each node/edge reconciled — plus an explicit statement of whether the WebSocket gap is now closed.
3. The exact commands run with their real outcomes (`cdk synth` exit code, validation check count, error/warning count, delivery SHA-256 values, `visual-check` per-viewport results, and both readability and containment numbers). Never report a non-zero exit as success.
4. Browser evidence and perceptual review reported **separately**. If the active model cannot view images, state that the perceptual review was not performed.
5. Anything unresolved, assumed, or deliberately left out of scope — including whether `Infrastructure Architecture.md` needs a matching update and you did not make it.
