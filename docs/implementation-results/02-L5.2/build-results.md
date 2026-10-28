# Build Results — 02-L5.2: Tell the author to reconcile gates and verifiers

**Branch:** `02-L5.2`
**Date:** 2026-10-28
**Spec:** `docs/tasks/02 - Prompt loop integrity.md` (L5.2), `docs/migration/EXTRACTION.md` §2 (D16), §3.4, §3.8, `prompts/task-prompt.md`, `AGENTS.md` (Gates and Tests)

## Summary

**Purpose:** Make the task-prompt author treat the target repo's own conventions as the authority for
gate commands, so a generated prompt names the exact gates that repo mandates instead of inheriting
product-specific verifier commands from the toolkit prompt.

| Decision | Why it matters |
|----------|---------------|
| Name the injection source (root `AGENTS.md` + optional `aidw/conventions.md`) and require the exact commands to be named from it | EXTRACTION.md §3.4/§3.8 and D16 make the target repo the owner of its gate list; inlining commands in the toolkit prompt would go stale and violate "a toolkit prompt must not name a package manager" |
| Remove the product verifier specifics (`srd:matrix-check`, `srd:check-tests`, `docs/conventions/srd-traceability.md`, `services/`/`packages/`/`tests/integration/… --jest-json`) from the reconciliation section | Those commands and paths belong to one product; the section must survive the E7.1 bucket (iii) split |
| Keep the two neutral obligations ("state the observable effect on existing data"; "fix the instruction or make the reconciliation an explicit deliverable") | They are the reconciliation the roadmap's Done-when demands; without them the rewrite loses its fail-closed fallback |
| Keep the Prompt Format's "Gate impact:" line as-is | It is already generic (checker / status vocabulary / catalog reference / CI gate) and Requirement 3 says not to change it |
| Scope the neutrality assertion to the rendered reconciliation section, not the whole file | The rest of `prompts/task-prompt.md` still carries product text that E7.1/E7.2 own; a whole-file absence assertion would fail against pre-existing lines |

**Where it fits in the roadmap:** Phase 02 ("Prompt loop integrity"), Epic L5 ("Author upstream quality").
It follows L5.1's pre-submit self-check and completes the L5 author-prompt work; E7.3 (D16) later owns
the injection mechanism that will drop the conventions into the rendered prompt. L5.3 (workflow-side
conciseness check) and L6.x remain separate tasks.

**Scope:** Rewrites the `### Gate and verifier reconciliation (gate-touching tasks)` section of
`prompts/task-prompt.md` to name the injection source rather than the commands, and adds one
rendered-prompt test to `tests/test_prompt_workflow.py` covering the section's required content,
neutrality, the intact "Gate impact:" line, and render arity. It deliberately stops short of building
the E7.3 injection, editing `aidw/workflows/prompt.py`, `aidw/inventory.py` or any agent context file,
neutralising the rest of `prompts/task-prompt.md`, or adding a workflow stage.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L5.2-prompt.md` | Created | Task prompt defining the L5.2 reconciliation requirements (committed on the branch). |
| `prompts/task-prompt.md` | Modified | Replaced the product-specific gate/verifier commands in the reconciliation section with the target repo's `AGENTS.md` / optional `aidw/conventions.md` as the gate source and a requirement to name the exact commands; kept the two neutral obligations. |
| `tests/test_prompt_workflow.py` | Modified | Added `test_l52_rendered_author_prompt_reconciles_gates_against_the_repo` and its section/constant helpers: source names, exact-command requirement, kept obligations, section-scoped absence of product verifier tokens/paths/package managers, intact "Gate impact:" trigger set, and three-arg render arity. |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified | Flipped the L5.2 checkbox to done (traceability update left uncommitted). |

---

## Verification Results

Repo gates are the ones `AGENTS.md` names under "Gates — run exactly these, and only these", plus
`uv build` because `prompts/pr.md` lists it for the `pyproject.toml` / `uv.lock` stack. Each runnable
gate was run through `aidw gate run <key> -- <command>` with the shared scope
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`,
against tree `523b27fcd58e` in run `20261028T053419Z-02-L5.2-implement`, stage
`record-implementation-results`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.87ms` (exit 0) — gate `install`, tree `523b27fcd58e`, stage `record-implementation-results`, 2026-10-28T05:56:19Z |
| Build | `uv build --out-dir $(mktemp -d)` | ✅ built sdist + wheel `aidt-0.1.0` — gate `build`, tree `523b27fcd58e`, 2026-10-28T05:56:22Z |
| Test | `env -u AIDW_STAGE -u AIDW_RUN_ID uv run --frozen pytest` | ✅ `664 passed in 76.83s (0:01:16)` — gate `suite`, tree `523b27fcd58e`, 2026-10-28T05:57:42Z |
| Doctor | `uv run --frozen aidw doctor` | ✅ `14 checks: 0 failed, 2 warning(s)` — gate `doctor`, tree `523b27fcd58e`, 2026-10-28T05:57:48Z |
| Agent configs | `uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` — gate `agents`, tree `523b27fcd58e`, 2026-10-28T05:57:49Z |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` — gate `prompts`, tree `523b27fcd58e`, 2026-10-28T05:57:49Z |
| Whitespace | `git diff --check` | ✅ no output (exit 0) |
| Lint (pnpm) | `pnpm -r lint` | **unverified — not applicable**: no `pnpm-workspace.yaml` or `package.json` exists in this `pyproject.toml`/`uv.lock` toolkit repo; no lint gate is configured (`design.md` §15). |
| Build (pnpm) | `pnpm -r build` | **unverified — not applicable**: same reason; the Python build gate (`uv build`) is run above. |
| Test (pnpm) | `pnpm -r test` | **unverified — not applicable**: same reason; the Python test gate (`uv run --frozen pytest`) is run above. |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 664 | ✅ Pass (`664 passed in 76.83s (0:01:16)`) |

The new L5.2 case is inside this single run — no separate subset invocation was made. It is
`test_l52_rendered_author_prompt_reconciles_gates_against_the_repo` in
`tests/test_prompt_workflow.py`, which asserts the rendered reconciliation section names root
`AGENTS.md` and optional `aidw/conventions.md`, requires the exact gate commands from that source,
keeps both neutral obligations, contains no removed product verifier token/path/package manager, the
"Gate impact:" line retains its checker / status vocabulary / catalog reference / CI gate trigger set
with no product command name, and the three-arg render contract holds.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run --frozen pytest` (the gate the task prompt's Tests/Done-when name) | ✅ `664 passed` — gate `suite`, tree `523b27fcd58e`, 2026-10-28T05:57:42Z |
| `uv run aidw prompts check` (the gate the task prompt's Tests/Done-when name) | ✅ `prompts check: 0 error(s), 0 warning(s)` — gate `prompts`, tree `523b27fcd58e`, 2026-10-28T05:57:49Z |
| Install / build / doctor / agents | ✅ see top-level table |
| `pnpm srd:validate` / `srd:check-references` / `srd:matrix-check` / `srd:report` | **unverified — not applicable**: no `pnpm-workspace.yaml`, `package.json`, `docs/rules-coverage/catalog.json` or vector matrix exists in this toolkit repo |
| `pnpm --filter infra cdk synth -c env=dev` | **unverified — not applicable**: no `infra/` package or CDK workspace exists in this repo |
| Deployed integration / matrix completeness test | **unverified — not applicable**: no TypeScript integration workspace or matrix fixture exists |

---

## Deviations observed during recording

- **The task-prompt template's pnpm/SRD gates do not apply to this repo.** `prompts/record-implementation-results.md`
  ships pnpm examples, but `AGENTS.md` names the uv commands above and `prompts/pr.md` says to take
  gate commands from the target repo. Those rows are marked unverified/not applicable, not passing.
- **The pytest gate runs under `env -u AIDW_STAGE -u AIDW_RUN_ID`.** Two pre-existing
  `tests/test_verification.py` gate-recording tests read the harness's ambient stage identity and fail
  when it leaks into the child process. The outer `aidw gate run` still records the outcome into this run.
- **The change set includes the roadmap checkbox and the committed task prompt.** The working tree
  also differs from `main` by `docs/task-prompts/02-L5.2-prompt.md` (committed earlier on the branch)
  and the L5.2 checkbox in `docs/tasks/02 - Prompt loop integrity.md` (left uncommitted by the
  traceability stage). This stage modified neither.
- **Roadmap parenthetical cites D17; the implementation follows D16.** The task prompt resolves this
  explicitly: D17 governs path conventions, while D16 plus EXTRACTION.md §3.4/§3.8 is the
  gate-command authority. The prompt text cites D16 accordingly.

---

## Non-Goals (NOT implemented)

- ❌ L5.3 (workflow-side conciseness check in `aidw/workflows/prompt.py`) and L6.1/L6.2 (loop contract fixture, `design.md` consolidation) — the rest of epics L5/L6.
- ❌ E7.3 (D16) injection mechanism — only prompt text naming the source was written.
- ❌ E7.2/E7.1 neutralisation of the rest of `prompts/task-prompt.md` (No-wrapper-duplication bullet, matrix-impact paragraph, TypeScript conventions section).
- ❌ Edits to `aidw/workflows/prompt.py`, `aidw/inventory.py`, or any agent context file; no new workflow stage.
- ❌ No commit, push, or PR opened by this stage.
