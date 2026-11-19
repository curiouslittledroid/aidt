# Build Results — 05-Q1.1: Withhold the PR when the tester's in-scope verdict is `Fail`

**Branch:** `05-Q1.1`
**Date:** 2026-11-19
**Spec:** `design.md` §8.2 (`aidw implement <task-prompt-path> [--pr <n>]`), §8.3 (the `R1` verdict-parse pattern), §18 (verdict parsing, M1/M3) and §17 row `Z10`; roadmap entry Q1.1 in `docs/tasks/05 - Pipeline efficiency.md`; `docs/task-prompts/05-Q1.1-prompt.md`
**Pull request:** not yet opened — the /pr stage records it here once the PR exists

## Summary

**Purpose:** Stop `aidw implement` from running `I6 pr` — and therefore from opening a pull request — when the `I2 test` stage reports `Fail` for any in-scope acceptance criterion.

| Decision | Why it matters |
|----------|---------------|
| The workflow parses I2's final message instead of checking its stage status | The tester exits 0 whether it passes or fails, so a `SUCCEEDED` status would let an in-scope `Fail` through to `I6 pr`. |
| `prompts/test.md` emits a bare `Test verdict: Pass|Fail` declaration, with a `Failing in-scope criteria:` line on `Fail` | The prompt and parser are edited together, the way §7.2 couples a prompt to the code that reads it; a bare line keeps a quoted or fenced example from being read as the verdict. |
| A pure `_parse_test_verdict` in `implement.py` blanks fenced blocks and rejects code-span or heading declarations | It reuses §8.3/§18's prose-only discipline without inheriting `verdict.py`'s deliberate acceptance of backticked tokens, which would read an example as a verdict. |
| `Fail` or an unparseable verdict (including missing/empty `out.txt`) stops with `state.status = BLOCKED` and exit 3 | Fail closed at the same boundary as `review.py`'s ambiguous verdict; `Pass` proceeds to the approve gate and `I6` unchanged. |
| The gate reads the recorded `test` stage after the pre-PR block and before the approve gate | A resumed run re-reads the same verdict and repeats the stop, while `I7` is deliberately not withheld because `I6` is the only committer. |

**Where it fits in the roadmap:** Phase 05 ("Pipeline efficiency"), epic Q1 ("Tester feedback — failures stop the run"), task Q1.1. It reuses the verdict-parsing shape established for `aidw review` in §8.3 and the fail-closed precedent in §18; later tasks in the same phase (S1, C1, G1, B1, O1) are independent and were not started here.

**Scope:** `aidw/workflows/implement.py` (the imperative pre-PR verdict gate and its pure parser), `prompts/test.md` (the machine-parseable verdict block and the per-criterion `Scope:` line), `design.md` §§8.2 and 17 (`Z10`), and the tests in `tests/test_implement_workflow.py` and `tests/test_design_doc.py`, plus the roadmap checkbox and the task prompt. It deliberately stops short of adding a verdict gate to `fix`, moving the stop earlier than "before `I6`", changing the stage registry or adding a `when=` condition, and changing the tester's exit-code behaviour or the prompt inventory.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/05-Q1.1-prompt.md` | Created | The task prompt recording the requirements, fixed decisions, tests and explicit non-goals. |
| `aidw/workflows/implement.py` | Modified | Adds the pure `_parse_test_verdict`, the recorded-verdict stop helper and the pre-PR gate that withholds `I6` on `Fail` or an unreadable verdict. |
| `design.md` | Modified | Documents the I2 verdict gate and its resume rule in §8.2 and records the prompt-fixed decisions in §17 row `Z10`. |
| `docs/tasks/05 - Pipeline efficiency.md` | Modified | Ticks Q1.1 as complete. |
| `prompts/test.md` | Modified | Adds the bare verdict-block contract and the per-criterion `Scope:` line that separates in-scope failures from `Unverified`, out-of-scope and pre-existing ones. |
| `tests/test_design_doc.py` | Modified | Pins §8.2's gate and resume-rule sentences and the single §17 `Z10` row. |
| `tests/test_implement_workflow.py` | Modified | Adds the six parser cases, the fake-stage `Pass`/`Fail`/unparseable/resume cases, and re-baselines the recorded I2 message to a passing verdict. |

---

## Verification Results

Commands are this repo's own, taken from its root `AGENTS.md` ("Gates — run exactly these, and only these"). There is no `aidw/conventions.md` and AGENTS.md states that `pytest` is the only verification (no linter, formatter or type-checker is configured; design §15), so the lint and build rows are not applicable here. The suite gate ran through `aidw gate run` with the workflow's declared scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 1ms`) |
| Lint | — | **unverified** — the repo configures no linter (AGENTS.md: "pytest is the only verification") |
| Build | — | **unverified** — the repo's gate list names no build command; no build gate was defined to run |
| Test | `uv run --frozen pytest` (gate `suite`) | ✅ Pass (`2213 passed in 49.11s`) — cited from the run's recorded gate, not re-run here |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`) — warnings are the dirty working tree and the missing `.mcp.json` |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (toolkit defaults and resolved repo prompts: `0 error(s), 0 warning(s)`) |
| Traceability / roadmap parser | `uv run --frozen aidw tasks --validate` | ✅ Pass (exit 0, no output) |
| Whitespace | `git diff --check` | ✅ Pass (exit 0, no output) |

Gate origin for the suite row: `suite` passed for tree `73f3fb893262` at `2026-11-19T07:51:10Z` by stage `test` (`2213 passed in 49.11s`), scope excludes `docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks`. Asking for the same gate with the same scope against this stage's tree printed the `reused: …` line and exited 0 without re-running, so this is the run's own recorded observation of the same gated content.

### `uv run --frozen pytest` (full suite)

The single full-gate run above is the source for the suite result. The task-specific test files are included in that run; no separate suite was invoked.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2213 | ✅ Pass (`2213 passed in 49.11s`) |
| Task cases in `tests/test_implement_workflow.py` and `tests/test_design_doc.py` | included in the full suite | ✅ Pass (covered by the same `2213 passed` run; no second invocation) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Parser cases — `Pass`, `Fail` with criteria, `Fail` without criteria, fenced declaration ignored, code-span declaration ignored, no declaration → `None` | ✅ Pass — covered by the full suite |
| End-to-end in-scope `Fail` — returns 3, records `BLOCKED`, `pr` never dispatched, no approve gate, criteria in `state.pr`, stderr names the criteria and the `--from test` path | ✅ Pass — covered by the full suite |
| Resumed run over the recorded `SUCCEEDED` `test` — returns 3 again without re-running I2 or dispatching `pr` | ✅ Pass — covered by the full suite |
| `Pass` and out-of-scope/pre-existing `Result: Fail` — return 0 and dispatch `pr` | ✅ Pass — covered by the full suite |
| Missing or empty recorded `out.txt` — returns 3, records `BLOCKED` naming the ambiguity, never dispatches `pr` | ✅ Pass — covered by the full suite |
| Design-doc pins — §8.2's gate and resume rule, and exactly one §17 `Z10` row | ✅ Pass — covered by the full suite |
| Roadmap parser guard — validated task ids are intact | ✅ Pass — `aidw tasks --validate` exited 0 |

---

## Deviations observed during recording

- **No lint or build command exists to run** — the repo's AGENTS.md gate list contains install, pytest, doctor, agents validation and prompts check only, and states that `pytest` is the only verification. Those rows are recorded as unverified rather than inventing a command.
- **The suite outcome was reused from this run's recorded gate** — the same `suite` gate had already passed for tree `73f3fb893262` under the identical declared scope during the `test` stage (`2026-11-19T07:51:10Z`). `aidw gate run` printed the `reused: …` line and exited 0 without re-running, so the row cites that origin instead of buying the suite again.
- **No pull request exists** — the read-only `gh pr view 05-Q1.1` lookup returned nothing. The document records the required not-yet-opened note; `/pr` will replace it with the real number after creating the pull request.
- **`aidw doctor` reports two warnings** — the dirty working tree and missing `.mcp.json` are expected while the implementation and this results document remain uncommitted, and `0 checks failed`.

---

## Non-Goals (NOT implemented)

- ❌ No test-verdict gate was added to `fix` (`F2`) and `fix.py`'s convergence rules were not changed — Q1.1 withholds the `implement` PR only (task prompt, "Explicit non-goals").
- ❌ The run was not stopped earlier than "before `I6`" — `I3`–`I9` and the serial/parallel dispatch were not reworked to fail fast after `I2` (task prompt, "Explicit non-goals").
- ❌ `stage_registry.py` and `docs/workflow-stages.md` were not touched and no registry `when=` condition was added — that belongs to S1.1's separate `WHEN_PATHS_CHANGED` task (task prompt, "Explicit non-goals").
- ❌ The tester's exit-code behaviour was not changed and no prompt or agent was added — `REQUIRED_PROMPTS` is unchanged (task prompt, "Explicit non-goals").
- ❌ No commit, push or pull request from this record stage — delivery belongs to `/pr` (record stage instruction).
