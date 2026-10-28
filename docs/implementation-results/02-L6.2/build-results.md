# Build Results — 02-L6.2: Re-baseline the extraction tasks this phase moves

**Branch:** `02-L6.2`
**Date:** 2026-10-28
**Spec:** `design.md` §8.1 (the `aidw prompt` chain) and §17 (resolved-decisions log), with §§9.1–9.3, 11, 12, 14, 15 as the sections the phase-02 L-task entries cite; `docs/tasks/00 - Extraction.md` E4.1/E4.3 (the entries re-baselined); `docs/tasks/02 - Prompt loop integrity.md` (L1.1–L6.1 entries); `docs/migration/EXTRACTION.md` §§3.4, 3.8 (D16/D17); `AGENTS.md` (Gates and Tests)

## Summary

**Purpose:** Record every phase-02 decision in `design.md` §17, amend §8.1 to name the reconcile
stage the loop omitted, and hand the post-phase-02 `prompt` chain over to the extraction tasks
(E4.1/E4.3) as their new baseline — documentation only.

| Decision | Why it matters |
|----------|---------------|
| Append one grouped `H` row per decision category, continuing the existing `A`…`G` id scheme | Keeps the §17 log the single place decisions are recorded without renumbering or duplicating earlier rows. |
| Verify G2 and annotate it in place instead of adding a new L4.1 row | The task's own trap: a second terminal-review/budget row would contradict "record, don't duplicate". |
| Name the reconcile stage by its long form (`task-review-reconcile-N`) and invent no `P` id | The stage registry's `P` ids are E4.1's deliverable; §8.1 only needs the chain shape, and `prompt.py` stage 4 is authoritative over the stale "then P2 again" prose. |
| Keep the §8.1 amendment provisional (`*(Provisional — E9.1…)*`) and leave the L1.x/L4.1 text intact | E9.1 owns the design rewrite; this task only fills the one missing piece (reconcile) without re-litigating landed text. |
| Put the post-phase-02 baseline note on E4.1/E4.3 but leave both `[ ]` unticked | Re-baselining is not implementation: E4.1/E4.3 remain future work and their id scheme is untouched. |

**Where it fits in the roadmap:** Final task of Phase 02 ("Prompt loop integrity"), Epic L6
("Evidence and close-out"). It depends on every landed L1.1–L5.3 behaviour and on L6.1's
loop-contract tests; it unblocks extraction tasks E4.1 (stage registry) and E4.3 (config-driven
plans), whose "unchanged against the baseline" checks would otherwise fail against the deliberately
changed `prompt` chain.

**Scope:** Touches `design.md` (§8.1 diagram + bullet, §17 rows) and
`docs/tasks/00 - Extraction.md` (E4.1/E4.3 baseline notes), plus the L6.2 checkbox in
`docs/tasks/02 - Prompt loop integrity.md`. It deliberately stops short of rewriting any other
`design.md` section, implementing the stage registry or config-driven plans, changing
`aidw/workflows/prompt.py` or its tests, or producing a stored `--dry-run` baseline artifact.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/02-L6.2-prompt.md` | Created | Task prompt defining the §17/§8.1/E4.x re-baseline requirements, traps and non-goals (committed on the branch). |
| `design.md` | Modified | §8.1 loop and bullets now name `task-review-reconcile-N` (one per fix batch, before the next review, `task-fixer`), with the provisional marker and L1.x/L4.1 text intact; §17 gains H1–H12 and annotates G2 as the single terminal-review/budget row (uncommitted). |
| `docs/tasks/00 - Extraction.md` | Modified | E4.1 states the converted `prompt.py` chain is the post-phase-02 shape and names the reconcile stage + terminal review as registry defaults; E4.3 states the `prompt` `--dry-run` baseline is taken after phase 02. Both stay `[ ]` (uncommitted). |
| `docs/tasks/02 - Prompt loop integrity.md` | Modified | Flipped the L6.2 checkbox to done (traceability update left uncommitted). |

---

## Verification Results

Repo gates are the ones `AGENTS.md` names under "Gates — run exactly these, and only these", plus
`uv build` because `prompts/pr.md` lists it for the `pyproject.toml` / `uv.lock` stack. The build and
full-suite gates were run through `aidw gate run <key> -- <command>` with the shared scope
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`,
against tree `1518b0c57c68` in run `20261028T121953Z-02-L6.2-implement`, stage
`record-implementation-results`. Outcomes below are from this run.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.81ms` |
| Build | `uv build --out-dir <mktemp -d>` | ✅ built sdist + wheel `aidt-0.1.0` — gate `build`, tree `1518b0c57c68`, 2026-10-28T12:42:22Z |
| Test | `env -u AIDW_RUN_ID -u AIDW_STAGE uv run --frozen pytest` | ✅ `678 passed in 94.21s (0:01:34)` — gate `suite`, tree `1518b0c57c68`, 2026-10-28T12:44:02Z |
| Doctor | `env -u AIDW_RUN_ID -u AIDW_STAGE uv run --frozen aidw doctor` | ✅ `14 checks: 0 failed, 2 warning(s)` (dirty working tree, missing `.mcp.json`) |
| Agent configs | `env -u AIDW_RUN_ID -u AIDW_STAGE uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` |
| Prompts check | `env -u AIDW_RUN_ID -u AIDW_STAGE uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` |
| Whitespace | `git diff --check` | ✅ no output (exit 0) |
| Lint | `pnpm -r lint` | **unverified — not applicable**: no `pnpm-workspace.yaml` or `package.json` exists and no linter is configured (`design.md` §15); this repo's gates are the uv commands above. |
| Build (pnpm) | `pnpm -r build` | **unverified — not applicable**: same reason; the Python build gate (`uv build`) is run above. |
| Test (pnpm) | `pnpm -r test` | **unverified — not applicable**: same reason; the Python test gate (`uv run --frozen pytest`) is run above. |

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 678 | ✅ Pass (`678 passed in 94.21s (0:01:34)`) |

The single full-suite invocation above is the one recorded by gate `suite`; no second full-suite run
was made to obtain the count. The command ran the child under `env -u AIDW_RUN_ID -u AIDW_STAGE` so
the harness's stage identity did not leak into the two pre-existing `tests/test_verification.py`
gate-recording tests (see Deviations).

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `git grep -nE 'dry-run\|prompt\.py' -- 'docs/tasks/00 - Extraction.md'` shows exactly the expected E4.x hits | ✅ hits at lines 253/255 (E4.1 preserved `prompt.py:170+` list + new baseline note) and 272 (E4.3 baseline note); lines 54/102 are the out-of-scope E0.7 `prompt.py:123` references, and no E4.x hit asserts a pre-phase-02 baseline |
| §8.1 names `task-review-reconcile-N` (one per batch, before the next review, `task-fixer`) and keeps the provisional marker + L1.x/L4.1 text | ✅ verified by read-only contract check in this run's `/test` stage (`design.md` lines 442, 467, 480) |
| §17 carries one row per phase-02 decision category with terminal-review/budget only in G2 | ✅ H1 now cites the source sections and document named by L1.1–L1.3 (`design` §§8.1, 11, 14; `EXTRACTION.md` §3.8); all §17/E4.x criteria pass. |
| Documentation-only change (no code/test file touched) | ✅ `git diff main --stat` lists only `design.md`, `docs/task-prompts/02-L6.2-prompt.md`, `docs/tasks/00 - Extraction.md`, `docs/tasks/02 - Prompt loop integrity.md` |
| `pnpm srd:validate` / `srd:check-references` / `srd:matrix-check` / `srd:report` | **unverified — not applicable**: no `pnpm-workspace.yaml`, `package.json`, `docs/rules-coverage/catalog.json` or vector matrix exists in this toolkit repo. |
| `pnpm --filter infra cdk synth -c env=dev` | **unverified — not applicable**: no `infra/` package or CDK workspace exists in this repo. |
| Deployed integration / matrix completeness test | **unverified — not applicable**: no TypeScript integration workspace or matrix fixture exists. |

---

## Deviations observed during recording

- **The task-prompt template's pnpm/SRD gates do not apply to this repo.** `prompts/record-implementation-results.md`
  ships pnpm examples, but `AGENTS.md` names the uv commands above and `prompts/pr.md` says to take
  gate commands from the target repo. Those rows are marked unverified/not applicable, not passing.
- **The pytest gate runs under `env -u AIDW_RUN_ID -u AIDW_STAGE`.** Two pre-existing
  `tests/test_verification.py` gate-recording tests read the harness's ambient stage identity and
  fail when it leaks into the child process. Clearing it for the child produced `678 passed`; the
  outer `aidw gate run` still recorded the outcome into this run. No test or workflow code was
  changed by this stage.
- **The `/test` stage returned `Overall result: Fail` on one documentation criterion.** H1's §17 row
  does not cite all the sections/documents its L1.1–L1.3 source entries name (missing `Design 14`,
  `Design 11`, `EXTRACTION.md §3.8`). This is an implementation/documentation defect, recorded here
  as observed; the recording stage did not fix it (that is a separate deliberate change).
- **The `/test` stage's own `aidw gate run` invocations were not recorded.** Its log shows five
  `no run to record into` notices, so the earlier suite/build outcomes are absent from
  `state.json`; this stage re-ran both gates against tree `1518b0c57c68` and recorded them fresh.
- **The change set spans commits and the working tree.** The branch carries the committed L6.2 task
  prompt (`docs/task-prompts/02-L6.2-prompt.md`, commits `341d796`, `246ae0d`); `design.md`,
  `docs/tasks/00 - Extraction.md` and `docs/tasks/02 - Prompt loop integrity.md` are uncommitted.
  This stage modified none of them.

---

## Non-Goals (NOT implemented)

- ❌ E9.1 "Rewrite design.md" — the §8.1 amendment is provisional precisely for that rewrite; no other `design.md` section was rewritten.
- ❌ E4.1/E4.3 implementation — building the stage registry or config-driven plans is that task's work; L6.2 only edits their entry text.
- ❌ The `aidw prompt` chain itself — `aidw/workflows/prompt.py` and its tests are already landed (L1.x–L4.x, L6.1) and were not changed.
- ❌ A stored `--dry-run` baseline artifact — none is produced or re-generated; the baseline is the current chain, described in prose.
- ❌ No commit, push, or PR opened by this stage.
