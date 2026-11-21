# Build Results — 05-O1.1: Teach agents to handle blocked bash commands

**Branch:** `05-O1.1`
**Date:** 2026-11-21
**Spec:** `design.md` §5.5 "System prompt and context files", `design.md` §17 "Resolved decisions"; roadmap `docs/tasks/05 - Pipeline efficiency.md`, epic O1, task O1.1
**Pull request:** #180 — https://github.com/curiouslittledroid/aidt/pull/180

## Summary

**Purpose:** Teach every shipped agent context file that a `Blocked bash command with unapproved
operations` tool result is a hard deny — not to be retried, in any cosmetic variant — and to be
reported as a blocker naming the denied command, closing the blind-retry loop observed live in an
implement stage (four blocks plus retries in one run).

| Decision | Why it matters |
|----------|---------------|
| The guidance lives in all eleven `agents/*/AGENTS.md` files, not in a shared fragment or a stage prompt | No shared fragment or assembly mechanism exists — each `agent-configs/<id>.yaml` points `agents_md:` at its own file (design §5.5) — and prompt text alone does not override an agent file's hard rules (§17 Z9/Z20). Editing the eleven files is the smallest change that reaches every agent, and every agent's allowlist grants `bash`. |
| The phrase `Blocked bash command with unapproved operations` is quoted verbatim | It is Pi's real tool-result text (quoted in the roadmap entry), so the agent can match the block when it sees it; a close reword would not match. |
| Content-only edit: no file moved or renamed, no `agents_md:` path changed | `aidw agents validate --strict` only checks that each `agents_md:` file exists and reads, so reachability (and `test_every_agent_config_still_reaches_its_guidance_file`) stays green; content coverage comes from the new glob sweep instead. |
| The added text carries no product, package-manager or product-path token, no slash-command, no `AGENTS.md §N` form, and no example command | The neutrality sweep in `tests/test_agent_guidance_neutrality.py` applies to the whole glob; any example command risks a forbidden token. |
| The §17 row takes the next free id, `Z21` | `aidw/conventions.md` forbids reusing or renumbering decision ids. |

**Where it fits in the roadmap:** Epic O1 ("Operator ergonomics") in phase 05. It builds on the
decision-log and agent-context rules already recorded in §17 (Z9, Z20) and on the §5.5 contract for
`agents_md` injection. The remaining epic O1 tasks are separate entries and are not started here.

**Scope:** All eleven `agents/*/AGENTS.md` files (one new `## Blocked bash commands` section each),
one bullet under design.md §5.5, one appended §17 row (Z21), and the two pinning tests. It
deliberately stops short of introducing a shared context fragment or assembly mechanism, and
touches no tool allowlist, `agent-configs/*.yaml`, prompt file or stage-registry entry.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/05-O1.1-prompt.md` | Created | Task prompt for O1.1 (committed on this branch). |
| `agents/code-reviewer/AGENTS.md` | Modified | Adds the `## Blocked bash commands` hard-deny section. |
| `agents/fixer/AGENTS.md` | Modified | Adds the `## Blocked bash commands` hard-deny section. |
| `agents/implementer/AGENTS.md` | Modified | Adds the `## Blocked bash commands` hard-deny section. |
| `agents/pr-publisher/AGENTS.md` | Modified | Adds the `## Blocked bash commands` hard-deny section. |
| `agents/recorder/AGENTS.md` | Modified | Adds the `## Blocked bash commands` hard-deny section. |
| `agents/review-approver/AGENTS.md` | Modified | Adds the `## Blocked bash commands` hard-deny section. |
| `agents/review-publisher/AGENTS.md` | Modified | Adds the `## Blocked bash commands` hard-deny section. |
| `agents/task-author/AGENTS.md` | Modified | Adds the `## Blocked bash commands` hard-deny section. |
| `agents/task-fixer/AGENTS.md` | Modified | Adds the `## Blocked bash commands` hard-deny section. |
| `agents/task-reviewer/AGENTS.md` | Modified | Adds the `## Blocked bash commands` hard-deny section. |
| `agents/tester/AGENTS.md` | Modified | Adds the `## Blocked bash commands` hard-deny section. |
| `design.md` | Modified | New §5.5 bullet stating the blocked-bash contract; new §17 row `Z21` recording task O1.1 and its prompt-fixed decisions. |
| `tests/test_agent_guidance_neutrality.py` | Modified | Parameterized glob sweep asserting the verbatim phrase and every behaviour clause, two live-guard tests proving the check rejects a dropped phrase or a dropped "cosmetic variants" clause, and a pinned property seed. |
| `tests/test_design_doc.py` | Modified | One test matching the §17 row by task id `O1.1` and wording (never by `Z` number), one test for the §5.5 bullet. |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 19 packages in 1ms` |
| Build | `aidw gate run build -- uv build --out-dir $(mktemp -d)` | ✅ Built `aidt-1.5.0.tar.gz` and `aidt-1.5.0-py3-none-any.whl` (gate `build`, tree `4a25c9d757fb`, 2026-11-21T01:12:49Z) |
| Test | `aidw gate run suite -- uv run --frozen pytest` | ✅ `2532 passed in 52.46s` (gate `suite`, tree `4a25c9d757fb`, 2026-11-21T01:13:45Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ `23 checks: 0 failed, 2 warning(s)` (warnings: branch `05-O1.1` dirty working tree; missing `.mcp.json`) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ `resolved repo prompts: 0 error(s), 0 warning(s)` |
| Whitespace | `git diff --check` | ✅ No output, exit 0 |

This repository configures no linter, formatter or type-checker (`AGENTS.md` "Gates — run exactly
these, and only these"; design.md §15), so there is no lint row to record.

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2532 | ✅ Pass (`2532 passed in 52.46s`) |
| `tests/test_agent_guidance_neutrality.py` + `tests/test_design_doc.py` (focused gate named by the task prompt's Done-when) | 143 | ✅ Pass (`143 passed in 0.79s`, gate `focused`, tree `4a25c9d757fb`, 2026-11-21T01:13:49Z) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Every `agents/*/AGENTS.md` carries the verbatim phrase and the three behaviour clauses (hard deny; do not retry, including cosmetic variants; report as a blocker naming the denied command) | ✅ `test_every_agents_guidance_teaches_the_blocked_bash_contract` passes over the whole glob |
| The content guard is non-vacuous | ✅ `test_the_blocked_bash_guard_is_live_on_the_two_observed_drops` and `test_property_every_missing_blocked_bash_clause_is_detected` pass; seed pinned by `test_the_blocked_bash_property_seed_is_pinned` |
| Neutrality sweep over the whole glob stays green | ✅ `tests/test_agent_guidance_neutrality.py` passes |
| Guidance reachable, configs unchanged | ✅ `uv run --frozen aidw agents validate --strict` exits 0 (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| design.md §5.5 bullet and exactly one new §17 row (Z21) | ✅ `test_o1_1_section_5_5_states_the_blocked_bash_hard_deny_contract` and `test_o1_1_decision_row_records_the_blocked_bash_guidance` pass |

---

## Deviations observed during recording

- **Roadmap names a test file that does not exist** — the entry lists `tests/test_agent_configs.py`;
  the equivalent that reads the whole `agents/*/AGENTS.md` glob and asserts `agents validate`-style
  reachability is `tests/test_agent_guidance_neutrality.py`. The task prompt fixed this up front and
  the implementation followed the prompt; the roadmap entry was left untouched (`aidw/conventions.md`).
- **No lint gate to run** — the recording prompt's generic lint/build/test skeleton names a lint
  command, but this repository configures none, so only build and suite were run as gates.

---

## Non-Goals (NOT implemented)

- ❌ No shared context fragment or assembly mechanism (task prompt "Explicit non-goals").
- ❌ No change to tool allowlists, `agent-configs/*.yaml`, prompts, or the stage registry — guidance
  text only (task prompt "Explicit non-goals").
- ❌ No work on the remaining epic O1 tasks (task prompt "Explicit non-goals").
- ❌ No PR opened, no commit or push from this stage — the `/pr` stage owns delivery.
