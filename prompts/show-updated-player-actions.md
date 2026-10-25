---
description: Summarise the player-facing actions added on the current branch into docs/implementation-results/<branch>/player-actions.md
argument-hint: "[branch]"
---

# Show updated player actions

You are documenting, for the branch currently checked out, which **player-invocable actions** the new code makes available (or changes) and **how a player uses each one**. This runs after an implementation session and **before the branch is merged**, so the full change set is reachable through `git diff main...HEAD` and the session context. Re-derive every claim from the repository: the session context may be stale or wrong, so verify against the actual code and diff before writing a single line.

The output is one Markdown document at `docs/implementation-results/<branch>/player-actions.md`. It complements — and must **not** duplicate — `docs/implementation-results/<branch>/build-results.md` (which describes what was *built*). This document describes what a *player* can now *do*.

## Variables

- `$1` (optional) — branch name override. Default: `git branch --show-current`.

## What counts as a "player action"

A **player action** is something a player can invoke **end-to-end from the client**:

- **WebSocket turn path:** natural-language `PLAYER_INPUT` (`packages/shared-types/src/schemas/ws-frames.ts`) → Intent Parser category/variant (`services/player-api/src/intent-parser/types.ts`) → `ActionDispatcher` validation (`services/player-api/src/dispatcher/ActionDispatcher.ts`) → an executor (`services/player-api/src/dispatcher/*Executor.ts`) → a deterministic rules-engine result → `MECHANICAL_RESOLUTION` / `NARRATIVE_CHUNK` / `TURN_COMPLETE` frames.
- **Admin rules route:** a new `{ action, payload }` accepted by the Rules Engine API (`services/rules-engine-api/src/router.ts`).

**Not** a player action — do not document these as available:

- A pure rules-engine primitive (`services/rules-engine/src/**`) with no executor / turn-path caller.
- A parser variant with no dispatcher mapping, or a `CombatAction` union member no executor handles.
- An LLM-narrated-only path (the golden rule: the LLM proposes, the deterministic engine enforces and computes).
- Anything the branch's task prompt lists as an explicit non-goal or deferred follow-up.

If reachability cannot be established from the code, say so and mark it **unverified** — never assume it works because a primitive exists.

## Step 1 — Identify the branch and the change set

```bash
git branch --show-current
git merge-base main HEAD
git log --oneline main..HEAD
git diff --stat main...HEAD
git diff --name-status main...HEAD
```

- If the branch is `main`, stop: there is nothing branch-local to document.
- Read `docs/implementation-results/<branch>/build-results.md` if it exists — it names the task(s), the files changed, and the deviations. Use it as a map, but confirm against the diff.
- Read the task prompt(s) that produced the branch: `docs/task-prompts/<branch>-prompt.md` (and any other `docs/task-prompts/*-prompt.md` referenced by the branch commits). These name the intended player-facing surface and the explicit non-goals.
- Read the cited spec sections for the contracts the actions must satisfy.

## Step 2 — Locate the player-facing surface in the diff

Filter the change set to the files that define or wire player actions:

```bash
git diff --name-status main...HEAD -- \
  services/player-api/src/intent-parser \
  services/player-api/src/dispatcher \
  services/player-api/src/handlers/ws-message.ts \
  services/rules-engine-api \
  packages/shared-types/src/schemas/combat.ts \
  packages/shared-types/src/schemas/ws-frames.ts
```

Then read the current state (not just the diff) of:

- `services/player-api/src/intent-parser/types.ts` — the `ParsedAction` discriminated union and its variants.
- `services/player-api/src/intent-parser/IntentParserService.ts` — the `SYSTEM_PROMPT` examples (what phrasing the parser is taught to recognise).
- `packages/shared-types/src/schemas/combat.ts` — the `CombatAction` union members.
- `services/player-api/src/dispatcher/ActionDispatcher.ts` — the eval/map path for each variant.
- `services/player-api/src/dispatcher/*Executor.ts` — the executors and the rules-engine symbols they call.
- `services/player-api/src/handlers/ws-message.ts` — step 7 branch order and the status gate (E3.9).
- `services/rules-engine-api/src/router.ts` — any new admin action.

Use `git log -L` / `git diff main...HEAD -- <file>` to separate **new** actions from **changed behaviour of existing** actions. Both belong in the document, in different sections.

## Step 3 — For each new action, establish how the player uses it

For every action that is genuinely player-invocable, capture:

- **Name** — the action identifier (e.g. `CAST_HEALING_SPELL`) and a plain-language title.
- **Player input** — the natural-language phrasing the parser accepts (quote the `SYSTEM_PROMPT` example or the fixture `text` that exercises it).
- **Parser mapping** — parser category/variant → executable action.
- **Prerequisites / legality** — required target(s), spell known / item held / weapon equipped, visibility, `legal_target`, action category and per-turn budget, status gate (E3.9), action economy.
- **Deterministic effect** — exactly what the rules engine computes (HP/status/nonlethal deltas, bonuses, movement cost, etc.). Name the engine symbol.
- **Observable outcome** — the frames and `state_deltas` the player sees, and any events (e.g. `PLAYER_DOWNED`).
- **Rejection modes** — the error codes the player gets (e.g. `UNCONSCIOUS_CANNOT_ACT`, `DEAD_CANNOT_ACT`, `ACTION_NOT_ALLOWED`, `EXECUTOR_UNAVAILABLE`, `INVALID_ACTION`) and when each fires.
- **Evidence** — `file:symbol` for the parser, dispatcher, executor, and engine; the spec section; and a test that proves it.
- **Status** — one of:
  - **Available end-to-end** — every link above exists and is wired.
  - **Partial** — wired but with a named limitation (state it).
  - **Primitive only** — the engine function exists but no player path reaches it (list under "Not available").

## Step 4 — Write the document

Create `docs/implementation-results/<branch>/player-actions.md` (create the directory if needed; do not touch `build-results.md`). Use this structure:

```markdown
# Player Actions Added — <branch>

**Branch:** `<branch>`
**Date:** <YYYY-MM-DD>
**Base:** `main` (merge-base `<short-sha>`)
**Task(s):** <roadmap task ids from build-results / commits>
**Build results:** `docs/implementation-results/<branch>/build-results.md`

## Summary

<One short paragraph: how many new player-invocable actions, in which areas
(combat / spellcasting / movement / skill use / items / …), and the single most
important thing a reviewer should know. If there are none, say so plainly and
explain what the branch added instead.>

## New player actions

### <ACTION ID> — <plain-language title>

| Field | Detail |
|-------|--------|
| Player input | "<example utterance the parser accepts>" |
| Parser mapping | `<category>` / `<variant>` → `<executable action>` |
| Prerequisites | <targets, resources, action category, status gate> |
| Deterministic effect | <what the engine computes; name the symbol> |
| Observable outcome | <frames / `state_deltas` / events> |
| Rejection modes | `<ERROR_CODE>` when <condition> |
| Evidence | `path:file.ts:symbol`, <spec section>, `<test file>` |
| Status | Available end-to-end / Partial (<limitation>) |

<One or two sentences of prose if the table needs context.>

### <ACTION ID> — <plain-language title>
…

## Changed behaviour of existing actions

<!-- Only if the branch altered an action that already existed. Keep it to what
     the player would notice. Delete the section if empty. -->

| Action | Before | After | Why |
|--------|--------|-------|-----|
| <action> | <old behaviour> | <new behaviour> | <reason> |

## Not available (explicit non-goals / deferred)

<!-- Anything the branch deliberately did NOT wire up, and primitives with no
     player path. This stops a reviewer assuming an engine function is playable. -->

- ❌ <capability> — <why it is not available / which follow-up owns it> (<reference>)

## Verification and caveats

- **How reachability was confirmed:** <the diff/read commands and the code
  chain you actually traced, per action>.
- **Not verified:** <any claim you could not confirm from the repo, and why>.
- **Tests not run:** <any test you did not execute, and why — do not report a
  result you did not observe>.
```

## Rules

- **Do not invent.** Every action, phrasing, error code, and effect must be traceable to a real file/symbol and, where possible, a test. If you cannot cite it, mark it unverified.
- **Never report a test result you did not observe.** If you run tests, give the real command and outcome. If you do not run them, say so.
- **Do not edit implementation code, tests, specs, or the roadmap.** This prompt only writes the one document.
- **Do not duplicate `build-results.md`.** Link to it for build detail; this document stays focused on player-facing capability and usage.
- **Distinguish available from merely-implemented.** A merged engine primitive is not a player action.
- **Mark uncertainty explicitly** rather than smoothing it over. "Not available" is a valid and useful answer.

## Done when

- `docs/implementation-results/<branch>/player-actions.md` exists and follows the structure above.
- Every documented action cites a real `file:symbol` chain from player input to engine effect, or is explicitly marked unverified.
- The "Not available" section lists the branch's non-goals and any primitives with no player path.
- No implementation file was modified.

## Final response

Return the document path and a one-line summary of what it covers (or that the branch added no new player actions).
