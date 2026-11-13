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
understand *why* a change was made or what it actually did. Epic X1 adds a `recorder`-owned
stage immediately after `I5` that distils the build results into a fixed narrative shape.

- [ ] **X1.1. Summarise each task's build results in a human-readable summary.md**
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
