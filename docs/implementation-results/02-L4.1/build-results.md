# Build Results — 02-L4.1: Spend the last revision slot on a review, not a fix

**Branch:** `02-L4.1`
**Date:** 2026-10-27
**Spec:** `docs/tasks/02 - Prompt loop integrity.md` (L4.1), `design.md` §8.1 / §17, `AGENTS.md` (Gates and Tests)
**Run id:** `20261027T104930Z-02-L4.1-implement`

## Summary

**Purpose:** Make the `aidw prompt` P2a fix loop spend its last revision slot on a review: fix
batches run only for the first `MAX_REVISIONS - 1` review rounds, the `MAX_REVISIONS`-th review is
review-only, and a residual `Request changes` after that terminal review fails closed instead of
having its fixes accepted unreviewed (the E1.6 symptom).

| Decision | Why it matters |
|----------|---------------|
| Terminal-review branch replaces both `revisions >= MAX_REVISIONS` exits, placed **after** the `VERDICT_BLOCKED` short-circuit | The loop now only leaves through `Approve` or the terminal `return 3`; placing the branch after `Blocked` keeps a final `Blocked` reading as "a human must settle it" rather than as generic residual changes |
| Terminal condition keyed off fix-budget spent (`revisions >= MAX_REVISIONS - 1`, i.e. two fix batches at `MAX_REVISIONS=3`) | Every non-approving round runs exactly one fix batch, so this is equivalent to `review_index >= MAX_REVISIONS`; keying off `revisions` avoids confusing fix batches (max 2) with review rounds (max 3) |
| Residual terminal `Request changes` sets `BLOCKED`, prints `review_text` to stderr, `return 3`, and records **no** gate | `return 3` happens before the `approve-task-prompt` gate, mirroring the `Blocked` verdict, so `approve_all` can never record an unreviewed acceptance |
| Delete all `assumed_ok` machinery (post-loop print, residual block, `verdict_line` suffix, gate `detail=` field) | Removes the exact unreviewed-acceptance signal E1.6 recorded (`assumed_ok=True`); the gate now reads `verdict={verdict}; revisions={revisions}` and is recorded only on the `Approve` path |
| `MAX_REVISIONS` stays `3` and its comment now says it counts review rounds, last one review-only | No new status or gate vocabulary; the budget's meaning is the only thing that changes |
| `design.md` §8.1 amended provisionally, one §17 row (`G2`) appended | E9.1 owns the §8.1 rewrite, L6.2 owns consolidating §17; this task edits only its own text |

**Where it fits in the roadmap:** Phase 02 ("Prompt loop integrity"), Epic L4 ("Termination
honesty"). It follows L3.4, which reconciles each fix batch and left the final-round fix batch in
place with a prompt-fixed note ("L4.1 later removes the final-round fix batch, after which every
reconcile sits before the next review"). L4.2 (per-round recording in `state.json` / `run.log`) is
the next task and must account for a terminal `Request changes` recording `BLOCKED` with no gate
row; L4.3 owns `--max-revisions` / `max_revisions`; L6.1/L6.2 own the loop fixture and the
`design.md` §17 consolidation plus E4.1/E4.3 re-baselining.

**Scope:** Touches `aidw/workflows/prompt.py` and `tests/test_prompt_workflow.py`, amends
`design.md` §8.1 and §17, and flips the L4.1 checkbox in the phase roadmap. It deliberately stops
short of changing the fix/reconcile stage mechanics, the L2.3 delta brief, the L3.3 snapshot writer,
`MAX_REVISIONS` itself, any per-round recorded field, and any CLI or config surface.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L4.1-prompt.md` | Created | Task prompt for L4.1 (committed on the branch) |
| `aidw/workflows/prompt.py` | Modified | Replace the two `revisions >= MAX_REVISIONS` exits with one terminal-review branch after the `Blocked` short-circuit; delete `assumed_ok` machinery; update the module docstring, `MAX_REVISIONS` comment and reconcile-placement comment |
| `tests/test_prompt_workflow.py` | Modified | Add a `blocked_review` knob to `_fake_stages`; rewrite the former acceptance test for terminal-review failure; add terminal-approval and terminal-`Blocked` cases; update the round-3 diff and temp-dir tests to two fix batches |
| `design.md` | Modified | Amend §8.1's P2a diagram line and `MAX_REVISIONS` paragraph for the review-only terminal round and exit-3 fail-closed outcome (provisional); append §17 row `G2` |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified | Flip the L4.1 checkbox to done |

---

## Verification Results

Repo gates are the ones `AGENTS.md` names under "Gates — run exactly these, and only these":
`uv sync --frozen`, `uv run --frozen pytest`, `uv run aidw doctor`,
`uv run aidw agents validate --strict`, `uv run aidw prompts check`. `prompts/pr.md` selects the
same `pyproject.toml` / `uv.lock` rows. Each runnable gate was run through
`aidw gate run <key> -- <command>` with the shared scope
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`,
and recorded against tree `44e529df8d89` in run `20261027T104930Z-02-L4.1-implement`. The pytest
gate scrubs the harness's ambient `AIDW_STAGE` / `AIDW_RUN_ID` from its child process, the
convention this repo's prior stages documented: two pre-existing `tests/test_verification.py`
gate-recording tests read those variables and fail when the stage identity leaks into the child.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 2ms` (exit 0) |
| Test | `env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ✅ `646 passed in 73.74s` — gate `suite`, tree `44e529df8d89`, stage `record-implementation-results`, 2026-10-27T11:18:36Z |
| Doctor | `uv run --frozen aidw doctor` | ✅ `14 checks: 0 failed, 2 warning(s)` — gate `doctor`, tree `44e529df8d89`, stage `record-implementation-results`, 2026-10-27T11:18:50Z |
| Agent configs | `uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` — gate `agents`, tree `44e529df8d89`, stage `record-implementation-results`, 2026-10-27T11:18:51Z |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` — gate `prompts`, tree `44e529df8d89`, stage `record-implementation-results`, 2026-10-27T11:18:51Z |
| Whitespace | `git diff --check` | ✅ no output (exit 0) |

The two `doctor` warnings are the expected dirty working tree on branch `02-L4.1` and the missing
optional `/.mcp.json`; neither is a failure. `uv build` is not one of this repo's named gates and
was not run.

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 646 | ✅ Pass (`646 passed in 73.74s`) |

The new and rewritten cases are inside this single run; no separate subset count was produced.
They are: `test_third_review_is_terminal_and_residual_request_changes_fails_closed` (exact
12-stage sequence, `code == 3`, `BLOCKED`, review-3 body on stderr, no `approve-task-prompt` gate,
no round-3 fixes), `test_approve_on_the_terminal_review_succeeds` (`approve_review=3`: `code == 0`,
`SUCCEEDED`, last stage `task-review-3`, `verdict=Approve`, `revisions=2`, no `assumed_ok`), and
`test_blocked_terminal_review_keeps_human_escalation_path` (a review-3 `Blocked` keeps its own
human-escalation message over the terminal `Request changes` branch). `test_third_round_diff_reflects_only_the_previous_fix_batch`
and `test_delta_brief_temp_directories_are_removed` were updated to `approve_review=3` and a
temp-dir count of 4 (two reconcile diffs, two review delta briefs).
`test_a_blocked_final_review_still_fails_closed` and `test_blocked_verdict_overrides_approve_all`
are unchanged and green.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run --frozen pytest` (the only gate the task prompt names) | ✅ `646 passed` (gate `suite`, tree `44e529df8d89`, 2026-10-27T11:18:36Z) |
| Install / doctor / agents / prompts | ✅ see top-level table |
| `pnpm srd:validate` / `srd:check-references` / `srd:matrix-check` / `srd:report` | **unverified — not applicable**: no `pnpm-workspace.yaml`, `package.json`, `docs/rules-coverage/catalog.json` or vector matrix exists in this `pyproject.toml`/`uv.lock` toolkit repo |
| `pnpm --filter infra cdk synth -c env=dev` | **unverified — not applicable**: no `infra/` package or CDK workspace exists in this repo |
| Deployed integration / matrix completeness test | **unverified — not applicable**: no `tests/integration` TypeScript workspace or matrix fixture exists |

---

## Deviations observed during recording

- **Generic prompt template named pnpm gates; this repo is Python/uv.** `prompts/record-implementation-results.md`
  ships pnpm examples, but `AGENTS.md` names exactly the five uv commands above and `prompts/pr.md`
  says to take the gate commands from the target repo. The pnpm/SRD/CDK rows do not apply here and
  are marked unverified/not applicable rather than passing. No lint or build gate exists in this
  repo.
- **The pytest gate runs under `env -u AIDW_STAGE -u AIDW_RUN_ID`.** Two pre-existing
  `tests/test_verification.py` gate-recording tests read the harness's ambient stage identity and
  fail when it leaks into the child process. This is the convention prior stages
  (`docs/implementation-results/02-L3.3/`, `02-L3.4/`) documented; the outer `aidw gate run` still
  records the outcome into this run. The un-scrubbed invocation was not run again here.
- **Tree is `44e529df8d89`, not the implementation stage's `56355b2c2459`.** The `/test` stage added
  `test_blocked_terminal_review_keeps_human_escalation_path`, which changed the test file and hence
  the gated tree; this stage gated the current tree once, and all four recorded gates share tree
  `44e529df8d89`.

---

## Non-Goals (NOT implemented)

- ❌ L4.2 — per-round recording in `state.json` / `run.log` distinguishing `Approve` from
  `Request changes` without reading stage outputs; no new recorded field was added. (Task prompt,
  explicit non-goals)
- ❌ L4.3 — the `--max-revisions` CLI flag / `max_revisions` config key; no flag or config surface
  was added. (Task prompt, explicit non-goals)
- ❌ L6.1 / L6.2 — the synthesized fixture pinning every loop contract and the §17 consolidation /
  E4.1–E4.3 re-baselining; only §8.1 and the single `G2` row were edited, nothing in
  `docs/tasks/00 - Extraction.md`. (Task prompt, explicit non-goals)
- ❌ No change to the fix/reconcile stage mechanics, the L2.3 delta brief, or the L3.3 snapshot
  writer — only the loop's termination shape and the reconcile-placement comment changed. (Task
  prompt, explicit non-goals)
- ❌ No commit, push, or PR — `prompts/pr.md` owns delivery. (Implicit non-goal of this stage)
