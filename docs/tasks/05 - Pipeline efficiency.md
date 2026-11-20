# Phase 05: Pipeline efficiency

Corrections and cost-control for the workflow chains, derived from a transcript-level audit of
Mythical Forge's last ten AIDW runs (implement / review / fix). Each task is a deliberate,
self-contained improvement, authorable through the toolkit itself. Ordering below is the
suggested implementation order; the roadmap has no dependency graph, so prerequisites are
named in each entry's `Notes`.

```bash
uv run aidw tasks --phase 05
uv run aidw prompt 05 P1 P1.1     # then implement, test, review, PR
```

Parser guard (run after any edit to this file — a missing period after the task id silently
collapses every id and breaks `aidw prompt`):

```bash
uv run python -c 'import pathlib; from aidw.roadmap import load_tasks; t=load_tasks(pathlib.Path("docs/tasks"), "[0-9]* - *.md"); assert t, "no tasks parsed"; bad=[x.task for x in t if "." not in x.task]; assert not bad, f"MISPARSE: {bad}"; print(f"{len(t)} tasks, none collapsed")'
```

The gates every task must keep green (from the repo AGENTS.md, quoted not re-defined):

```bash
uv sync --frozen
uv run --frozen pytest
uv run aidw doctor
uv run aidw agents validate --strict
uv run aidw prompts check
```

## Epic P1: Fix-loop delivery (commit, push, issue integrity)

The `fix` workflow deliberately never commits (Design 8.4, Design 13), so its fixes and the
shared `I7` roadmap tick stay uncommitted in the PR-head worktree and never reach the PR —
while its stages close the follow-up issues as `Status: fixed`. On PR #300 this left one fix
commit unpushed, two fixes uncommitted, and all three follow-up issues closed. This epic makes
`fix` land its work and keeps "issue closed" truthful.

- [x] **P1.1. Add a commit-and-push stage to `aidw fix`** (Design 8.4, Design 13, Design 17)
  - Done when: a `fix` run whose loop closed at least one issue ends with a new core stage that commits the accumulated change set (the fixes plus the `I7` roadmap tick) and pushes it to the PR head branch; the run records the pushed head SHA in `state.pr`; a stage that cannot commit or push fails the run (exit non-zero) with a message naming the PR and branch instead of succeeding silently; `--dry-run` plans the stage exactly once, after `I7`, and evaluates no evidence; the §8.4 sentence "The edit stays uncommitted: no stage of `fix` commits (§13)" and the §13 clause it cites are reversed, recorded as decision Z9; and the five gates above are green.
  - Deliverable: a new retained core stage id (e.g. `F5 commit-and-push`) in `aidw/stage_registry.py` and `aidw/workflows/fix.py` (emitted from the `post_loop` half, after `I7`); a prompt `prompts/fix-commit.md` plus its `REQUIRED_PROMPTS` entry in `aidw/inventory.py`; design.md §§8.4, 13, 17 (row Z9); `docs/workflow-stages.md`; the `aidw fix` block in `README.md`; and the tests below.
  - Tests: `tests/test_fix_workflow.py`, `tests/test_stage_registry.py`, `tests/test_plan_stages.py`, `tests/test_inventory.py`, `tests/test_design_doc.py`, `tests/test_workflow_stages_doc.py`.
  - Notes: Model the stage on `implement`'s `I6 pr`, which is the only stage that commits there. The stage must resolve the PR-head branch from the located worktree (decision K1), push that branch, and treat "nothing to commit and no issue closed" as a successful no-op rather than a failure. The Z9 row also records P1.2's close-after-push ordering — one reversal, one decision row.

- [x] **P1.2. Close a follow-up issue only after its fix is pushed** (Design 8.4, Design 7.2)
  - Done when: in a `fix` run, an issue's `Status: fixed` comment and close happen only after the P1.1 commit stage has pushed a tree containing that fix; when the push fails or the commit stage is absent, the issue stays open (or is reopened) and the run fails instead of reporting it fixed; `prompts/fix-next-review-followup.md` no longer instructs the fixer to close the issue in-stage, deferring the close to the commit stage; `review_followup.py` supports that deferred close; design §8.4 is updated; and the five gates above are green.
  - Deliverable: `prompts/fix-next-review-followup.md` (rework its section 7 "Mark the issue fixed and close it"), `prompts/scripts/review-followup/review_followup.py` (deferred-close support: the `close` subcommand and one close tail shared with `fixed`) with its pure guards in `prompts/scripts/review-followup/logic.py` (`COMMANDS`, `close_plan`) and the command list in the script `README.md`, `aidw/workflows/fix.py` (the post-push close loop), `aidw/stage_registry.py` (F1's `{closing_body}` variable), `agents/fixer/AGENTS.md` (the in-stage close removed at its source), design.md §8.4 and §17 (row Z9, created by P1.1), `docs/workflow-stages.md`, and the tests below.
  - Tests: `tests/test_fix_workflow.py` (the close-after-push ordering and its fail-closed paths), the `prompts/scripts/review-followup/tests` suite (`test_logic.py` for `close_plan`, the new `test_close.py` for the `close` command), the re-baselined pins `tests/test_design_doc.py`, `tests/test_plan_stages.py`, `tests/test_stage_registry.py` and `tests/test_prompt_neutrality.py`, and the `docs/workflow-stages.md` drift check `tests/test_workflow_stages_doc.py`.
  - Notes: Depends on P1.1. Recorded under Z9 (P1.1), not a new decision: close-after-push is the commit stage's postcondition, not a separate reversal. Preserve the exact-marker semantics: `Status: in progress` / `Status: fixed` are availability checks that match the literal string, so the close must still post the same marker, just later. Keep one issue closed per fix so a batch failure cannot strand an issue half-closed.

## Epic Q1: Tester feedback (failures stop the run)

The `test` stage (I2) reports an in-scope `Fail` against acceptance criteria, but `implement`
still runs `I6 pr` and opens the PR; the reviewer then re-finds the same defects and the fix
loop re-fixes them (one defect was found independently by the tester, the reviewer and the
fixer in one task). This epic makes an in-scope tester `Fail` stop the run before the PR.

- [x] **Q1.1. Withhold the PR when the tester's in-scope verdict is `Fail`** (Design 8.2)
  - Done when: `implement` does not run `I6 pr` (and opens no PR) when the `I2 test` stage's final message reports `Fail` for any in-scope acceptance criterion, and the run records a stop naming the failing criteria; `Unverified` criteria, out-of-scope criteria and pre-existing failures the tester already separated do not stop the run; the workflow (not the agent) parses the verdict and decides, the way §8.3 parses `R1`'s verdict; design §8.2 is updated and the decision recorded as Z10; and the five gates above are green.
  - Deliverable: `aidw/workflows/implement.py` (a verdict gate before `I6`), a machine-parseable verdict block in `prompts/test.md`, design.md §§8.2, 17 (row Z10), and the tests below.
  - Tests: `tests/test_implement_workflow.py`, `tests/test_design_doc.py`.
  - Notes: The tester prompt already separates "real defect" from "pre-existing / unrelated" (Design 8.2's I2 description); the gate must key on the in-scope criteria only, so an unrelated flaky failure (observed: a Jest `SIGSEGV` in an untouched package) does not withhold a legitimate PR. Reuse the §8.3 verdict-parse pattern rather than inventing a new one.

## Epic S1: Stage cost control (skip documentation stages when nothing changed)

`I3 update-traceability` and `I4 update-architecture` are repo-optional but, when present, run
unconditionally. In the audited runs they consumed 22.6% and 26.4% of an implement run's cost
for a single roadmap checkbox and prose edits respectively. This epic adds a path-scoped stage
condition beside the existing `WHEN_EVIDENCE_GREEN`, so a repo can skip them cheaply.

- [x] **S1.1. Add a path-scoped stage condition and gate `update-traceability` (I3) on it** (Design 8.2, Design 12.2)
  - Done when: `aidw/stage_registry.py` gains a `WHEN_PATHS_CHANGED` condition carrying a config-declared path set (default empty, which means the stage always runs as today); the workflow evaluates it before `run_stage` (the same place `WHEN_EVIDENCE_GREEN` is evaluated) and records a `skipped` stage with the reason when the gated tree's change set touches none of the paths; `I3 update-traceability` carries it by default with a repo-overridable path set covering the rules-engine sources, `docs/rules-coverage` and the vector-matrix directories; a repo that declares no set keeps today's unconditional behaviour; design §§8.2, 12.2 are updated and the decision recorded as Z11; and the five gates above are green.
  - Deliverable: `aidw/stage_registry.py` (the condition token and the `I3` default), `aidw/runner.py` and `aidw/workflows/implement.py` (evaluation), an optional key in `aidw/config.py` surfaced through `docs/target-repo-config.md`, design.md §§8.2, 12.2, 17 (row Z11), and the tests below.
  - Tests: `tests/test_stage_registry.py`, `tests/test_plan_stages.py`, `tests/test_implement_workflow.py`, `tests/test_design_doc.py`.
  - Notes: The change set is the gated tree identity the `I7` condition already computes. A skip is a success, never a failure, and must leave the roadmap byte-identical — mirror `WHEN_EVIDENCE_GREEN`'s `record_skipped` shape.

- [x] **S1.2. Gate `update-architecture` (I4) on the path condition** (Design 8.2, Design 12.2)
  - Done when: `I4 update-architecture` skips (records `skipped` with a reason) when the gated tree's change set touches no path in the repo-declared architecture trigger set, and runs otherwise; the trigger set is repo-declared (a config key, defaulting to `docs/architecture/**` plus any diagram-input paths the repo names); when `I4` is enabled but the repo declares no trigger set, `aidw doctor` warns instead of silently running the stage unconditionally; design §§8.2, 12.2 are updated; and the five gates above are green.
  - Deliverable: `aidw/stage_registry.py` (attach the condition to `I4`), the config key and `docs/target-repo-config.md`, `aidw/doctor.py` (the warning), design.md §§8.2, 12.2, and the tests below.
  - Tests: `tests/test_stage_registry.py`, `tests/test_plan_stages.py`, `tests/test_implement_workflow.py`, `tests/test_doctor.py` (or its equivalent).
  - Notes: Depends on S1.1's condition token. "Did the architecture change?" is repo-defined; do not invent a universal heuristic — require the repo to declare its trigger paths and warn when the set is empty.

## Epic C1: Context and gate-command economy

The rendered prompts duplicate the target `AGENTS.md` that Pi already injects as project
context, and gate commands — deliberately "never inlined" — are re-derived by every stage and
misreported as `unavailable` by the evidence bundle when the target repo uses a non-canonical
heading. This epic removes the duplication and makes gate commands resolve once, correctly.

- [ ] **C1.1. Stop appending the target `AGENTS.md` to rendered prompts** (Design 7.3, Design 5.5)
  - Done when: `aidw/prompts.py` no longer appends the root `AGENTS.md` body to the rendered prompt for the prompts that already receive it via Pi's project-instructions channel, while the `aidw/conventions.md` append (which Pi does not provide) is preserved; a config flag or per-prompt marker keeps the old append for a repo that needs it; design §7.3 is updated and the decision recorded as Z12; and the five gates above are green.
  - Deliverable: `aidw/prompts.py` (`inject_repo_conventions` split), design.md §§7.3, 17 (row Z12), and the tests below.
  - Tests: `tests/test_prompts.py` (or the rendering test that covers `inject_repo_conventions`), `tests/test_inventory.py`, `tests/test_design_doc.py`.
  - Notes: Observed duplication: the `impliment-task` rendered prompt was 28.5KB of which 16.9KB was `AGENTS.md`, while the system prompt already carried the same file as `project_context` (17KB). Drop the renderer's copy, not Pi's; keep the conventions channel, which the gate block (C1.2/C1.3) still reads from.

- [ ] **C1.2. Resolve gate commands from the target's actual gates heading, and diagnose misses** (Design 8.1, Design 7.3)
  - Done when: `_gate_block` recognises the gate section under the heading the target repo actually uses — the canonical `## Gates` plus the common `## Gate commands` alias (or a config-declared heading) — instead of degrading to `unavailable — could not be read`; when a conventions source carries a gates-like heading the parser did not recognise, `aidw doctor` (or the evidence bundle) reports it rather than silently degrading; the evidence bundle for a repo whose conventions use `## Gate commands` renders the gate commands; and the five gates above are green.
  - Deliverable: `aidw/workflows/prompt.py` (`_GATES_HEADING` / `_gates_section`), `aidw/prompts.py`, `aidw/doctor.py`, `docs/target-repo-config.md`, design.md §8.1, and the tests below.
  - Tests: `tests/test_prompt_workflow.py`, `tests/test_doctor.py`.
  - Notes: Root cause observed in Mythical Forge: `aidw/conventions.md` uses `## Gate commands`, `_GATES_HEADING` is exactly `## Gates`, so every prompt-workflow evidence bundle reported the gate commands unavailable and the prompt reviewer could not verify the prompt's acceptance commands against the repo's real gates.

- [ ] **C1.3. Inline the resolved gate commands into the stage prompts that reference them** (Design 7.3, Design 8.2)
  - Done when: the stage prompts that today say "never inlined here — take them from conventions.md" (`prompts/impliment-task.md`, `prompts/test.md`, `prompts/fix-next-review-followup.md`, `prompts/record-implementation-results.md`, `prompts/code-review.md`) instead carry the target repo's resolved gate block — the exact `aidw gate run <key> <scope> -- <command>` lines from the single conventions channel — while a repo with no conventions keeps the pointer behaviour; rendering is covered by tests with no Pi model invoked; and the five gates above are green.
  - Deliverable: `aidw/prompts.py` (inject the gate block into the named prompts), the five prompt files, design.md §7.3, and the tests below.
  - Tests: `tests/test_prompts.py`, `tests/test_inventory.py`, `tests/test_design_doc.py`.
  - Notes: Depends on C1.2's resolved source. This removes the per-stage re-derivation and the key/command/scope drift that defeats gate-outcome reuse (observed: ~74 gate invocations across ten runs with only ~15 reused, and the same key bound to different commands across stages).

## Epic G1: Prompt review depth

The prompt reviewer's findings are often spec gaps, which the task-fixer then papers over in
the prompt, and re-reviews approve on grep-level checks — so a spec-level defect reaches code
review and costs a fix cycle. This epic classifies findings and checks feasibility before the
expensive authoring stage.

- [ ] **G1.1. Classify prompt-review findings as `spec-gap` vs `prompt-gap` and short-circuit spec-gaps** (Design 8.1)
  - Done when: `prompts/task-review.md` requires every finding to carry a `Kind: spec-gap | prompt-gap` classification; a `spec-gap` finding stops the run `blocked` (exit 3) with the finding surfaced, instead of handing it to the `task-fixer`; `prompt-gap` findings flow through the existing fix/reconcile loop unchanged; the reviewer prompt forbids approving on grep-only re-reads of previously flagged sections (the cited file/section must be re-read in full); design §8.1 is updated and the decision recorded as Z13; and the five gates above are green.
  - Deliverable: `prompts/task-review.md`, `aidw/findings.py` (parse the classification), `aidw/workflows/prompt.py` (the short-circuit), `agents/task-reviewer/AGENTS.md`, design.md §§8.1, 17 (row Z13), and the tests below.
  - Tests: `tests/test_findings.py`, `tests/test_prompt_workflow.py`, `tests/test_design_doc.py`.
  - Notes: The block mechanism already exists in §8.1 (the author reports `blocked:`); this adds it at the review layer so the run fails fast on a spec gap instead of burning the fix/reconcile loop "fixing" prose for a gap only the spec can close. An unclassified finding must fail closed, like §18's other malformed-verdict rules.

- [ ] **G1.2. Check task feasibility before the authoring stage** (Design 8.1)
  - Done when: the `prompt` workflow runs a cheap Python preflight (no Pi model) before `P1 task-prompt` that verifies the roadmap entry's cited spec sections exist and are non-empty and the task's prerequisites are ticked, and refuses (exit 2 or 3) naming the gaps instead of spending a full authoring run that later reports `blocked:`; the author-side feasibility check inside the `task-prompt` prompt remains as the semantic backstop; design §8.1 is updated; and the five gates above are green.
  - Deliverable: `aidw/workflows/prompt.py` (the preflight), design.md §8.1, and the tests below.
  - Tests: `tests/test_prompt_workflow.py`, `tests/test_design_doc.py`.
  - Notes: Turns a ~$0.36 blocked authoring run (observed: 04-A2 attempt 1) into a seconds-cost refusal. Scope the check to what is cheap and deterministic — file existence, section headings, tick state — never semantic completeness, which stays the author's job.

## Epic B1: Batch fixes

`fix` processes exactly one issue per iteration, so N follow-ups cost N full fix+test+review
cycles. This epic batches independent issues per iteration while keeping per-issue
accountability.

- [ ] **B1.1. Fix multiple approved follow-ups per iteration** (Design 8.4)
  - Done when: `fix` processes a bounded batch of approved child issues per iteration (default 3, overridable via a `--fix-batch <n>` flag), each with its own files-changed accountability, followed by a single `test` and a single `code-review` over the batch; the loop still re-derives availability via `review_followup.py select` and never by counting; the "one fix per iteration" prose in §8.4 and the fixer prompt is updated and the decision recorded as Z14; a finding in the batch re-review still creates new children; and the five gates above are green.
  - Deliverable: `aidw/workflows/fix.py`, `prompts/fix-next-review-followup.md`, `prompts/scripts/review-followup/review_followup.py` (batch select), design.md §§8.4, 17 (row Z14), and the tests below.
  - Tests: `tests/test_fix_workflow.py`, `tests/test_prompt_workflow.py`, `tests/test_design_doc.py`.
  - Notes: Sequence after P1.1/P1.2 (same files). Keep the one-`Status: fixed`-comment-per-issue marker semantics — batching must not blur which fix closed which issue, and a batch whose test fails must fail the whole batch loudly, not silently close a subset.

## Epic O1: Operator ergonomics

- [ ] **O1.1. Teach agents to handle blocked bash commands** (Design 5.5)
  - Done when: the bundled agent context files (`agents/*/AGENTS.md`, or the shared context they assemble from) tell agents that a `Blocked bash command with unapproved operations` result is a hard deny — do not retry the command with cosmetic variants, and report it as a blocker naming the denied command — instead of the observed blind-retry loop; the guidance is covered by `aidw agents validate --strict`; and the five gates above are green.
  - Deliverable: the agent context files under `agents/*/AGENTS.md` (or the shared section), design.md §5.5 if a contract is added, and the tests below.
  - Tests: `tests/test_agent_configs.py` (or the equivalent that exercises `agents validate`), `tests/test_design_doc.py`.
  - Notes: Observed four blocks plus blind retries in a single implement stage. Smallest possible change; pair it with any agent-context edit so the flag ship in the same run.

## Epic W1: Stage and run-store write ownership

A run's writes are only as safe as the stage boundaries around them. Two live failures show the
gaps: a stage rewrote a file another stage owns byte-exclusively, and a preview created a run that
a later `--resume` then adopted. Both are silent — every gate stayed green, and the only symptom
was a missing PR.

- [ ] **W1.1. `update-traceability` (I3) must not edit the roadmap** (Design 8.2, Design 12.1, Design 17)
  - Done when: an `implement` run whose change set leaves `I3` no plausible artefact reports "none" and leaves `paths.roadmap_dir` **byte-identical**, so `I7`'s byte-exact tick postcondition stays satisfiable in the same run; a repo can declare its traceability artefacts (including "none") in `aidw/conventions.md` and `I3` reads that declaration; and a test fails if the exclusion or the conventions channel stops reaching `I3`.
  - Deliverable: `prompts/update-traceability.md` (the hard rule), `aidw/prompts.py` (`CONVENTIONS_PROMPTS`, so the target-repo conventions reach `I3`), `aidw/conventions.md` (this repo's declaration, drafted on this branch), design.md §12.1 and a §17 row, and the tests below.
  - Tests: `tests/test_prompt_workflow.py` (the conventions set and its injection), `tests/test_prompt_neutrality.py`, `tests/test_implement_workflow.py`.
  - Notes: Observed live in `20261119T211427Z-05-S1.2-implement` on 2026-11-19: every gate green (`suite` 2265 passed, `traceability`, `build`, `doctor`, `prompts`, `agents`), then the run failed with "roadmap tick postcondition not met: the `S1.2` tick changed more than the `- [ ]` -> `- [x]` checkbox on line 77". `I7` had edited nothing; `I3` had decided the roadmap entry was the repo's only traceability artefact and rewritten its `Done when`/`Deliverable`/`Tests`/`Notes` as well as ticking it. The two contracts cannot both hold: `aidw/roadmap.py:verify_checkbox_flip` compares the whole line list against a run-start snapshot and allows exactly one substitution, deliberately, because a weaker check passes a reflow or an edited neighbour (the PR #282 defect, H3.1). Do not weaken that postcondition and do not simply capture the snapshot later — the fix is ownership. `CONVENTIONS_PROMPTS` is EXTRACTION.md §3.8's four prompts, so extending it to `update-traceability.md` is a channel decision that must be recorded; and a mechanical `I3` postcondition (the roadmap bytes unchanged) is the stronger alternative to a prompt rule if the stage can already name the file.

- [ ] **W1.2. `--dry-run` must not create a run or become a `--resume` target** (Design 8.2, Design 9)
  - Done when: `aidw implement <task-prompt> --dry-run` and `--dry-run --resume` both leave the runs tree unchanged — no new run directory, no `state.json` — while still printing the plan and the planned gate; no `--resume` can attach to a run that never invoked Pi; and the same holds for every workflow that pairs `--dry-run` with a resume lookup.
  - Deliverable: `aidw/workflows/implement.py` (the dry-run path) and whichever of `prompt.py`/`approve.py`/`review.py`/`fix.py` carry the same `create_run`-before-the-dry-run-split shape, plus the tests below.
  - Tests: `tests/test_implement_workflow.py` (`--dry-run`, with and without `--resume`, asserting the runs tree before and after), `tests/test_prompt_workflow.py` if the prompt workflow shares the fix.
  - Notes: Observed live on 2026-11-19 while verifying task 05-S1.2: a `--dry-run --resume` preview created `20261119T233947Z-05-S1.2-implement` recording all nine stages `succeeded` without invoking Pi. `implement._latest_implement_run` returns the newest implement run for the branch, so the next genuine `--resume` would have attached to that phantom run, skipped every stage as already-succeeded and opened no PR, while the real failed run sat untouched — a silent no-op whose only symptom is a missing PR. Every workflow reaches `create_run` before its dry-run split (each carries the comment that a dry run holds the same worktree lock), so decide the rule once: either a dry run creates no run at all, or it creates one that `--resume` refuses. Also decide whether a run that never invoked Pi may be resumable.
