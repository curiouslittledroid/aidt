# Phase 04: Enhancements

Forward-looking, self-contained improvements to `aidt` that are neither extraction (phase 00)
nor recovery work (phases 01–03). Nothing here is a v1 acceptance requirement; each task is a
deliberate improvement, authorable through the toolkit itself. Append new epics to this file
rather than renumbering a released task.

```bash
uv run aidw tasks --phase 04
uv run aidw prompt 04 X1 X1.1     # then implement, test, review, PR
```

Parser guard (run after any edit to this file — a missing period after the task id silently
collapses every id and breaks `aidw prompt`):

```bash
uv run python -c 'import pathlib; from aidw.roadmap import load_tasks; t=load_tasks(pathlib.Path("docs/tasks"), "[0-9]* - *.md"); assert t, "no tasks parsed"; bad=[x.task for x in t if "." not in x.task]; assert not bad, f"MISPARSE: {bad}"; print(f"{len(t)} tasks, none collapsed")'
```

## Epic X1: Narrative implementation summaries

The `record` stage (`I5`) writes a mechanical `build-results.md`: a files-changed table, gate
rows and non-goals. That is the audit artifact, but it is not something a human reads to
understand *why* a change was made or what it actually did. Epic X1 adds `recorder`-owned
stages immediately after `I5` that turn the recorded evidence into fixed, human-facing shapes:
a narrative summary (`X1.1`) and a runbook for exercising the change by hand (`X1.2`). Neither
re-runs anything `I5` recorded.

- [x] **X1.1. Summarise each task's build results in a human-readable summary.md**
  Add a `summarize-implementation-results` stage (new retained id `I8`) to the `implement`
  chain, immediately after `record-implementation-results` (`I5`) and before the roadmap tick
  (`I7`) / `pr` (`I6`). It is owned by the `recorder` agent, reads the just-written
  `<implementation_results_dir>/<branch>/build-results.md` plus the task prompt, and writes
  `<implementation_results_dir>/<branch>/summary.md` in a fixed narrative structure — the
  problem it was solving, the core idea, what was built piece by piece, what it deliberately
  did not do, and verification (honest about failures and unverified gates). It re-runs no
  gates and records nothing it did not read from the build results. This reverses design §1.3's
  "optional summary prompts … not as a workflow stage" non-goal, scoped to exactly this one
  summary; the reversal is recorded as decision `Z3`.
  - Deliverable: `prompts/summarize-implementation-results.md`; the `I8` stage in
    `aidw/stage_registry.py` (core — `STAGE_IDS` gains `I8`, `REPO_OPTIONAL_IDS` stays
    `{I3, I4}`); a new `agents/recorder/AGENTS.md` section; `REQUIRED_PROMPTS` in
    `aidw/inventory.py`; the design.md updates (§1.3, §2, §5.4, §8.2, §17 row `Z3`); and the
    tests below.
  - Done when: `uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents validate
    --strict` and `uv run aidw prompts check` are green; `aidw implement <prompt> --dry-run`
    plans `I8 summarize-implementation-results` between `I5` and `I7` on the `recorder` agent;
    the summary prompt names `<implementation_results_dir>/<branch>/summary.md` as its only
    owned artifact and never instructs re-running a gate.
- [ ] **X1.2. Write a human-run integration test guide beside the build results**
  Add a `write-integration-test-guide` stage (new retained id `I9`) to the `implement` chain,
  immediately after `summarize-implementation-results` (`I8`) and before the roadmap tick
  (`I7`) / `pr` (`I6`). It is owned by the `recorder` agent (no new agent id), reads the
  just-written `<implementation_results_dir>/<branch>/build-results.md`, the task prompt and
  the branch's changed files, and writes
  `<implementation_results_dir>/<branch>/integration-test-guide.md`: a step-by-step procedure a
  human follows to integration-test the change by hand, covering the surfaces the change
  actually touches — existing repo tooling, custom CLI/TUI commands, browser UI flows, and
  external actions such as AWS commands. Each scenario carries its prerequisites, the exact
  command(s) or steps, the expected observable result, how to tell pass from fail, and any
  cost/permission/destructive warning; the guide also carries a teardown section and an honest
  "could not be exercised in this environment" section. Every scenario must be traceable to the
  changed files, the build results or the task prompt — no invented flags, subcommands, routes
  or endpoints, and a command it cannot confirm against the tree is reported as unconfirmed
  rather than guessed. It is an **instruction** document, never an execution: the stage runs no
  integration test, no gate, and no command that touches a cloud account, browser or deployed
  stack, so design §1.3's "deployed integration tests" non-goal still holds — AIDT writes the
  recipe, a human runs it. The stage is core and unconditional (like `I8`): no new `when=`
  token. The prompt file is `prompts/write-integration-test-guide.md` — deliberately *not*
  `integration-tests.md`, which is a product prompt MF owns
  (`docs/migration/prompt-classification.md`) and would be shadowed by a target repo's own file
  of that name (D14), silently swapping this stage's prompt. The guide's section order and
  per-scenario fields live in the prompt, with no new `paths.*` key and no template. The
  decision is recorded as `Z6`.
  - Deliverable: `prompts/write-integration-test-guide.md`; the `I9` stage in
    `aidw/stage_registry.py` (core — `STAGE_IDS` gains `I9`, `REPO_OPTIONAL_IDS` stays
    `{I3, I4}`, `_IMPLEMENT.stages` gains `I9` between `I8` and `I7`, never in a
    `parallel_group`); a fourth `## Stage` section in `agents/recorder/AGENTS.md`;
    `REQUIRED_PROMPTS` in `aidw/inventory.py`; the `aidw/workflows/implement.py` chain
    documentation; design.md (§1.3, §2, §5.4, §8.2, §12.2, §17 row `Z6`); the drift-checked
    tables in `docs/workflow-stages.md`; the `aidw implement` block in `README.md`;
    `docs/migration/prompt-classification.md` (class (iv), 16 → 17); the fixture's declared
    implement list; and the tests below.
  - Done when: `uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents validate
    --strict` and `uv run aidw prompts check` are green; `aidw implement
    docs/task-prompts/04-X1.2-prompt.md --dry-run` plans `I9 write-integration-test-guide` on
    the `recorder` agent between `I8` and `I7` and ends `dry-run complete; Pi not invoked`;
    the prompt names `<implementation_results_dir>/<branch>/integration-test-guide.md` as its
    only owned artifact, requires the per-scenario fields and the two closing sections above,
    and forbids executing any test, gate, cloud call or browser flow (allowing only read-only
    `git` and file inspection); and no new agent id, `paths.*` key, template or
    `parallel_groups` member exists, while design §1.3 still forbids *running* deployed
    integration tests and now names `I9` as writing the guide and running nothing.
  - Tests: `tests/test_integration_guide_prompt.py` (new); re-baselined
    `tests/test_stage_registry.py` (including its unknown-id probe, which currently uses `I9`),
    `tests/test_plan_stages.py`, `tests/test_implement_workflow.py`, `tests/test_inventory.py`,
    `tests/test_prompt_classification.py`, `tests/test_design_doc.py` and
    `tests/test_workflow_stages_doc.py`.
