# Phase 03: Stage resilience

Make one bad round survivable. Today a stage that returns nothing, a review prompt that
outgrows the model's context, or a provider hiccup discards the whole run — including every
stage that already succeeded — because `aidw prompt` cannot resume and the only recovery is a
manual re-run from the author.

This phase changes the Pi attempt loop, the delta brief's size contract, the prompt workflow's
resumability, the run state's gate evidence (epic H0), and — in epic H3 — which stage owns the
roadmap tick. It does **not** change the loop's convergence rules (Phase 02), model routing, or
the shape of `prompt`/`review`/`approve`; `implement`'s chain becomes seven stages and `fix`
gains one after its loop, both for the tick alone.

## Evidence: the runs this phase is derived from

Every E4 prompt run so far, each on its own branch worktree:

| Run | Stages | Cost | Outcome |
|---|---|---|---|
| `20261103T202948Z-00-E4.3-prompt` | 15 | $2.11 | `blocked` — terminal `Request changes` (Phase 02's L4.1 working as designed) |
| `20261103T215546Z-00-E4.3-prompt` | 8 | $2.00 | `succeeded`, approved in round 2 |
| `20261103T235209Z-00-E4.4-prompt` | 6 | $0.91 | `succeeded`, approved in round 2 |
| `20261104T010511Z-00-E4.5-prompt` | 1 | $0.17 | `failed` — OpenRouter 402 on the author stage |
| `20261104T020519Z-00-E4.5-prompt` | 10 | $1.52 | `failed` — the round-2 reviewer returned no final message |

Three of those five outcomes discarded completed work, and in none of them was a stage's *work*
wrong — the run simply had nowhere to go.

### The truncation, in detail

`20261104T020519Z-00-E4.5-prompt`, `stages/task-review-2.meta.json`:

| | |
|---|---|
| `stop_reason` | **`length`** |
| `exit_code` | 0 (`error_message: None`) |
| output / reasoning tokens | 19,034 / 15,445 |
| input tokens | 187,268 |

The final assistant message holds exactly one content block — a `thinking` block — and **no
text**, so `_read_out()` returned `""` and the workflow failed the run:

```
02:44:29 [ERROR] task-review-2 produced no final message
```

`aidw/pi.py` retries once (`max_attempts = 2 if retry_transient else 1`) but only for a non-zero
exit or an in-stream provider error, so a clean-exit truncation is not retried at all, and design
§10's own row for this case is "stage `failed`; the workflow stops". That row predates being able
to tell a truncation apart from an agent that simply declined to answer.

### The context that caused it

The round-2 review prompt is the round-1 prompt plus a delta brief that carries the whole
previous review *and* the whole fix-batch diff, and both grow with the number of findings. Six
findings meant six fix stages and ~43k chars of brief:

| | round 1 | round 2 |
|---|---|---|
| rendered prompt | 12,317 chars | **55,636** chars |
| input tokens | 149,002 | 187,268 |

Nothing bounds either half of the brief, and the growth is invisible: a 55k round-2 prompt looks
exactly as complete as a 12k round-1 one.

### The discarded work

`aidw prompt` never sets `state.resume` and the CLI has no `--resume`, so each failure above
re-authors from scratch. Worse, the failed run leaves its task worktree and branch in place, so a
fresh re-run refuses at branch-setup (`git.add_worktree` returns `None` for an already
checked-out branch) — exit 4, before it reads the roadmap — until the operator deletes the
worktree and branch by hand.

A **blocked** run is worse off than a failed one. Design §9.2 sets `resume.next_stage` only when a
*stage fails*, so a block records no continuation point at all: `20261103T202948Z-00-E4.3-prompt`
ends `status: blocked` with `resume: {}` and a **successful** terminal review as its last stage.
Its fifteen stages and $2.11 are unreachable by any supported path — although L4.1 makes exactly
this outcome (`Request changes` at the budget, exit 3) an intended one that will keep recurring —
and the only recovery is a blind re-roll whose first stage re-authors the prompt file the review
was about.

## Gate: do not start before these are known

| Prerequisite | Why it constrains phase 03 |
|---|---|
| `E2.4`/`E2.5` (AIDT owns branch creation; `aidw prompt` runs in the control worktree) | H1.2 reuses the existing task worktree instead of creating one, so it edits the same branch-setup code and must preserve the one-run-per-worktree lock (design §3.2). |
| `E4.3` (config-driven plans) | H2.1 edits `stage_registry.render_delta_brief`, which E4.3 moved out of `prompt.py`, and must keep `--dry-run` for `prompt` byte-identical (E4.3's Done when). |
| Phase 02 `L2.3` (delta brief) and `L3.4` (reconcile) | H2.1 changes what a later round is told. L2.3's purpose — a per-finding `resolved`/`not resolved`/`newly contradicted` verdict before any new finding — must survive the substitution. |
| `E4.8` (whole-repo gates, recorded once and cited) | H3.2's condition is a read of the outcomes `aidw gate run` recorded (design §14); it cannot cite evidence the run does not keep. H0.1 is that half of E4.8 — the outcomes are recorded today but do not survive a stage boundary — and is a prerequisite for H3.2. |
| `E5.1`/`E5.2` (`aidw.roadmap` and the configured `paths.roadmap_dir`) | H3.1 resolves the tick's entry through `find_task` against the resolved config, so the stage names no `docs/tasks` literal (D15/D17's two readers). |
| `E6.1` (the incident this epic exists for) | `20261105T030527Z-00-E6.1-implement` is H3.2's acceptance replay: the stage flipped E6.1's box and reverted it against a red `suite`. |
| `E9.1` (rewrite `design.md`) | H1.1, H1.2 and H3.1 amend design §9.3, §10 and §8.2 and record the decisions in §17; E9.1 carries them forward. |

## How this phase is driven

Each task is authorable through the toolkit itself:

```bash
uv run aidw tasks --phase 03
uv run aidw prompt 03 H1 H1.1     # then implement, test, review, PR
```

Parser guard (run after any edit to this file — a missing period after the task id silently
collapses every id and breaks `aidw prompt`):

```bash
uv run python -c 'import pathlib; from aidw.roadmap import load_tasks; t=load_tasks(pathlib.Path("docs/tasks"), "[0-9]* - *.md"); assert t, "no tasks parsed"; bad=[x.task for x in t if "." not in x.task]; assert not bad, f"MISPARSE: {bad}"; print(f"{len(t)} tasks, none collapsed")'
```

Every behaviour change here is proven by a fake Pi argv or a fake stage (AGENTS.md §Tests, design
§15) — no task in this phase may invoke a real model, and each must be observable from
`state.json`/`run.log` without reading a transcript.

## Epic H0: Keep the gate evidence

H3.2 asks "is a pass recorded for the tree the tick edits". The answer today is always no, and the
same loss is what makes `pr` (I6) re-buy the gate suite `record` (I5) already passed. This epic
lands first because it is the cheaper half of the phase and everything else that reads gate
evidence depends on it.

- [x] **H0.1. Keep gate outcomes across stage boundaries** (Design 9, Design 14)
  E4.8 records every `aidw gate run <key> -- <command>` outcome in run state and lets a later
  stage cite it instead of paying for it again. Nothing survives. Every `state.json` in the state
  root shows `gate_outcomes: []` (94 of 94, E6.1's red `suite` among them) because a workflow's
  `save()` rewrites the file from the in-memory `RunState` it loaded at `create_run`, dropping
  whatever the agent's `aidw gate run` subprocess appended. The split is visible in one run:
  `reused: gate 'srd' passed … by stage 'update-traceability'` shows intra-stage reuse working,
  and no citation ever crosses a stage boundary — the signature of the save, not of a missing
  rule. Measured on the three `03.1-B*` implement runs, `pr` spends 53–75s — 42–55% of its wall
  clock — inside `aidw gate run`, re-buying `lint`/`build` that `record` had passed on the
  identical tree minutes earlier (tree `7955d5effa2d`: passed by `record` at 06:55:07Z and
  06:55:18Z, bought again by `pr` at 06:56:33Z and 06:56:42Z).
  A second, independent loss is concurrent: Pi issues tool calls in parallel within one turn, so
  one turn ran `lint`, `build` and `suite` as three simultaneous `aidw gate run` processes, each
  read-modify-writing the same `state.json` — at most one of the three can survive even with the
  workflow's overwrite fixed, and `aidw/runner.py`'s `_STATE_LOCK` is in-process only, so it does
  not serialize them.
  - Deliverable: one owner for the file. Either an append-only outcome log per run that
    `aidw gate run` appends to and every citation reads, or a merge-on-write of `gate_outcomes`
    performed under a cross-process file lock and published with `os.replace`, so no reader ever
    sees a half-written `state.json` and neither writer can drop the other's rows — the loss is
    symmetric: a stage record the workflow wrote must survive a later CLI write too. Amend design
    §9.2's `gate_outcomes` paragraph and §14 to state who writes the file under which lock, and
    record the decision in §17.
  - Done when: an outcome `aidw gate run` recorded is still present and unchanged after the
    workflow's next `save()` — the round trip, not the write; a gate `test` passed for tree `T` is
    cited by `record` and by `pr` in one uninterrupted chain with the command executed once,
    proven by a counter outside the repository (E4.8's own technique) rather than by output text;
    two `aidw gate run` invocations that overlap for one run both record an outcome and neither is
    lost; no `state.json` is observed truncated or missing a stage record while a CLI write and a
    workflow write overlap; and `aidw gate list` / `aidw runs show` report the outcomes after the
    run process has exited, not only while it is running.
  - Tests: `tests/test_verification.py` extended to drive `aidw/runner.py:run_stage` with a fake
    argv instead of faking a stage by setting `AIDW_STAGE` alone — that shortcut is why this loss
    is green today — plus a threaded pair of `cli.invoke(app, ["gate", "run", …])` calls against
    one run asserting both outcomes survive, and the save-after-gate round trip.
  - Notes: rejected — "read the file at the moment of the decision", which H3.2's earlier wording
    allowed. That answers the tick's question and leaves every agent-side citation broken,
    including the `pr` citations above, which the agent reads during its own stage. Rejected —
    retry the failed gate: E4.8's rule is cite-or-run, and a re-run buys the same answer for the
    same tree. E4.8's Done when ("a run whose `test` stage gated tree `T` performs no second
    full-suite run for `T` in `record`") is disproved by the same 94 runs and is what H0.1
    closes; `docs/tasks/00 - Extraction.md`'s E4.8 "Progress" line should name it instead of
    leaving the box ticked with the gap in a trailing sentence. H0.1 changes neither which stages
    gate nor what a red gate stops.

## Epic H1: A stage that returns nothing

- [x] **H1.1. Retry a stage whose final message never arrived** (Design 10, Design 14)
  A truncation is distinguishable from a refusal: the invocation exits 0, the transcript's last
  message is a `thinking` block with no text, and `stop_reason` says `length`. Today all three
  collapse into "produced no final message" and the run dies, even though the stage had already
  done its reading and needed only to write the report.
  - Deliverable: extend the attempt loop at the Pi invocation seam (`aidw/pi.py`, surfaced through
    `aidw/runner.py:run_stage`) with one second attempt when the invocation exits cleanly and the
    stage produced no final text; a retry starts a **fresh session** (resuming a truncated context
    truncates again); both attempts are recorded in the stage meta and `run.log` with the retry's
    own cost; `--no-retry-transient` suppresses it exactly as it suppresses the provider-error
    retry. Amend design §10's "returns no final message" row and record the decision in §17.
  - Done when: a stage whose first attempt ends `stop_reason: length` (or with empty final text)
    is retried once with a distinct session id, and a second attempt that answers continues the run
    with both attempts visible in the stage meta and both costs in the run total; two truncated
    attempts fail the run naming the stage, the stop reason and that **both** attempts were
    truncated — never the bare "produced no final message"; a stage that answers first time is
    never retried; a non-zero exit keeps today's behaviour; `--no-retry-transient` disables both
    retries; and a gate decision is never re-asked by a retry.
  - Tests: `tests/test_pi.py` and `tests/test_runner.py` with a fake argv asserting one retry, the
    fresh session id, the attempt count in the meta, and the fail-closed double-truncation path.
  - Notes: a fixer that truncated may have partially edited the prompt, and a truncated stage is
    not distinguishable from a silent one — the retry re-applies the same instruction to the same
    tree and the round's reconcile stage still follows. That is accepted, not solved. Rejected
    alternative: treat a truncated review as `ambiguous` and continue; design §10 forbids running
    rework on empty findings.

- [ ] **H1.2. `aidw prompt` resumes instead of re-authoring** (Design 9.3, Design 14)
  Design §9.3 gives resumability to `implement` alone; `aidw prompt` writes no `state.resume` and
  has no flag, so a blocked review (exit 3), a provider 402, or a truncated stage throws away every
  completed stage — $3.63 across the two runs in the table above, for no result.
  - Deliverable: `--resume` and `--from <stage>` on `aidw prompt`, modelled on
    `aidw/workflows/implement.py` (`_confirm_resume`, the latest-run-by-branch lookup, stage
    selection by name), plus the branch-setup change that reuses the existing task worktree for the
    same `{phase}-{task}` branch instead of calling `git.add_worktree` into a refusal; write
    `state.resume` on a stop and clear it on success.
  - Done when: a run that failed at `task-review-2` resumes at that stage in its own worktree,
    never re-runs `task-prompt` or `task-review-1`, and keeps one run id with the later stages
    appended; a `blocked` run either rebuilds the loop from its recorded rounds or refuses naming
    the reason, and never silently re-authors; a fresh (non-resumed) re-run after a failed run
    either reuses the worktree or refuses with exit 4 printing the two commands that clear it;
    `--from` validates stage names against the planned stages before any side effect; and the
    one-run-per-worktree lock still holds across a resume.
  - Tests: `tests/test_prompt_workflow.py` with fake stages — the resumed stage list, the absence
    of an author stage, the single run id, and the refusal message and its commands.
  - Notes: the preflights that produced the run are not repeated on resume (the base-branch fetch
    check L1.1 and the predecessor check L1.2 belong to the run being resumed); the lock and the
    worktree identity are. Gates already recorded are not re-asked (design §9.3).

- [ ] **H1.3. Give a blocked run a forward path** (Design 8.1, Design 9.2, Design 9.3)
  H1.2 recovers a *failed* run at the stage that failed. A *blocked* run is not a failure and has
  no such stage: design §9.2 sets `resume.next_stage` only when a stage fails, so a block records
  nothing to resume from. E4.3 stopped one round short with findings 5 → 4 → 2, and the reviewed
  prompt — plus any operator correction to it — is discarded by the next author stage.
  - Deliverable: a continuation path on the blocked run's own state — `aidw prompt --resume` on a
    `blocked` run runs one further cycle (a fix batch for the terminal review's findings, its
    reconcile, then a review), and `--from-prompt <path>` starts at `task-review-1` on an
    operator-supplied prompt; record the effective review budget and the supplied prompt's path
    and content hash in `state.json`, so the extension is visible rather than inferred.
  - Done when: resuming a `blocked` run never re-runs `task-prompt`, keeps the run id, and its
    summary shows the effective budget and the added round; the continuation is a fix batch for
    the terminal review's findings, its reconcile, then a review — never a fix without a following
    review, so L4.1's invariant holds in a continuation too; `--from-prompt <path>` starts at
    `task-review-1` with that file, records its path and hash, applies the tree preflights (clean
    tree, current base) and skips the run-scoped one (L1.2's predecessor check); a blocked run
    whose worktree no longer exists refuses with exit 4 naming the run, the missing worktree and
    the command to re-author, never silently re-authoring; and the gate record keeps the original
    `denied` decision in the run's history, distinguishable from the continuation's.
  - Tests: `tests/test_prompt_workflow.py` with fake stages — the stage list after a block, the
    single run id, the `--from-prompt` provenance, the recorded effective budget, and the
    missing-worktree refusal.
  - Notes: rejected alternative — unblock by treating the terminal review's findings as "known and
    recorded"; that is L4.2's deleted `assumed_ok` path. The continuation is an explicit operator
    decision about one run, which is why it is a `--resume` action on that run and not a larger
    default budget.

## Epic H2: Bound the review context

- [ ] **H2.1. Give the delta brief a size budget** (Design 8.1, Design 15)
  L2.3's delta brief passes the previous review verbatim and the prompt diff after it, with no
  bound on either half; a six-finding round inflated the next review from 12,317 to
  55,636 chars and the stage then ended with `stop_reason: length`.
  - Deliverable: a documented size contract in `stage_registry.render_delta_brief` — budget the
    previous review and the diff separately; render prior findings as their structured blocks
    (`aidw/findings.py:render_finding_block`, one block per finding, which is exactly what the
    reviewer must answer) whenever that is smaller than the raw review prose; and elide an
    over-budget diff behind an explicit note in the existing `DIFF_UNAVAILABLE` style, never a
    silently shortened or empty section. Record the rendered size per review stage.
  - Done when: a round whose fix-batch diff exceeds the budget still renders a review prompt under
    the budget, and the elision is named in the prompt text; every prior finding and the
    per-finding resolution instruction survive the substitution; the E4.5 shape (six findings,
    19k → 23k prompt) renders a round-2 prompt materially smaller than today's 55,636 chars, with
    the before/after recorded in the task's result; round 1 is unchanged and `--dry-run` for
    `prompt` stays byte-identical; and the rendered size plus the review stage's input tokens are
    recorded in `run.log`/`state.json`.
  - Tests: `tests/test_stage_registry.py` renderer units for the budget and the elision, and
    `tests/test_prompt_workflow.py::test_delta_brief_preserves_previous_review_verbatim`
    re-baselined — that test's name is the old promise.
  - Notes: the first lever is the previous review (structured findings are cheaper than prose and
    are what the delta brief actually asks about); the second is the diff's context lines — a
    reduced-context diff costs a fraction and loses nothing the reviewer needs, since it is
    checking whether a change landed, not reading the surrounding prose. A hard cap stays as the
    backstop and must name what it dropped: a reviewer that cannot see a fix cannot verify it.

## Epic H3: One roadmap tick, one owner

- [ ] **H3.1. Give the roadmap tick its own stage** (Design 8.2, EXTRACTION.md §3.5)
  I3 carries two jobs with different owners. Four of its owned artifacts —
  `docs/rules-coverage/catalog.json`, the generated `report.md`,
  `tests/integration/src/vector-matrix/vectors.ts` and `tests/integration/src/02.5-B/**` — exist
  only in a repo that has an SRD traceability system, which is exactly why D13 makes I3
  repo-optional. The fifth is the roadmap checkbox, which every repo has and which no repo should
  be able to switch off: today `enabled: false` on I3 drops the tick with it, and a repo with no
  catalog runs a stage whose only honest move is to stop and report that it owns nothing. The tick
  is also the one edit in that prompt needing no repo knowledge at all — one checkbox in one file
  whose location is `paths.roadmap_dir` (D15/D17).
  - Deliverable: split the stage. I3 keeps the four repo-specific artifacts and stays
    repo-optional; `prompts/update-traceability.md` loses its roadmap row and its checkbox
    instruction. A new **core** stage (`update-roadmap`, prompt `prompts/update-roadmap.md`) does
    the tick and nothing else, on the `recorder` agent — `read`/`bash`/`write`, `session: fresh`,
    `thinking: low`, the same cheap/mechanical shape as I5 — with a second section added to
    `agents/recorder/AGENTS.md` rather than a new agent id, and `inventory.REQUIRED_PROMPTS`
    gaining the prompt. Its id joins `STAGE_IDS` (`REPO_OPTIONAL_IDS` unchanged) and the
    vocabulary decision is recorded in EXTRACTION.md §3.5 and design §17. It is placed after I5
    `record-implementation-results` — where the gates have been recorded — and before the
    `approve-implementation-pr` gate and I6 `pr`, because I6 is the single owner of the commit
    (§8.2), so the tick lands in the task's own PR. `implement.py` resolves the entry itself
    through `aidw.roadmap.find_task` against the resolved `paths.roadmap_dir`/`paths.roadmap_glob`
    and renders `{roadmap_file}` and `{task_id}` into the stage, so the prompt names no directory
    (`prompt.py`'s D15 "two readers" rule); zero or two matching entries refuse with exit 2 before
    the stage runs. After the stage the workflow re-parses the file and asserts that exactly the
    target line flipped and every other byte is unchanged.
  - Done when: a repo with no `docs/rules-coverage/` gets its box ticked and no error; `enabled:
    false` on I3 no longer drops the tick, while a declared implement stage list that omits the new
    core id errors naming it (`validate_stage_list`'s removal rule) instead of silently planning
    defaults; an already-`[x]` entry is a successful no-op recorded as such; an edit touching any
    other line, and an entry that is missing or appears twice, fail the stage instead of passing;
    `--dry-run` plans the new stage in the position the run would use; and `uv run aidw prompts
    check`, `uv run aidw agents validate --strict` and `uv run aidw doctor` stay green.
  - Tests: `tests/test_implement_workflow.py`'s `DEFAULT_ORDER`/stage-list pins plus
    `tests/test_plan_stages.py` and `tests/test_stage_registry.py` re-baselined for the seventh
    stage, `tests/test_override_integration.py`'s I3 prompt-override case re-pointed, and a new
    `tests/test_roadmap_tick.py` driving the one-line verification with a fake stage (design §15:
    no task invokes a real model).
  - Notes: rejected — keep the tick in I3 and document "don't disable I3 if you want your roadmap
    ticked"; that turns one config switch into a trap and keeps a repo-independent edit hostage to
    artifacts the repo may not have. Rejected — a new agent id for a two-line mechanical edit. The
    split does not by itself make the tick honest; that is H3.2.

- [ ] **H3.2. Tick only behind evidence, never against a red gate** (Design 8.2, Design 10, Design 14)
  The run this epic exists for: `20261105T030527Z-00-E6.1-implement`. Its traceability stage
  flipped E6.1's box, then reverted it —
  > I flipped the E6.1 checkbox as instructed, then reverted it when the gate run came back red:
  > `docs/roadmap-format.md` defines `[x]` = "done" and `aidw prompt --next` takes "the first
  > unchecked entry in file order", so a checked E6.1 would advance the roadmap to E6.2 while
  > E6.1's own change set fails `uv run --frozen pytest`.
  Both halves of that decision were the agent's, and both were made early: `[x]` is a completion
  claim, and I3 runs *before* I5 records the gates, so the stage had no evidence either way. The
  suite was green by the time `pr` ran (1382 passed) and the review approved with no follow-ups,
  so E6.1's branch ships `- [ ]` and nothing ever re-runs I3 after a gate turns green.
  - Deliverable: a `when=` condition the workflow evaluates instead of the agent — a new
    `WHEN_EVIDENCE_GREEN` token answering each workflow from its own evidence. In `implement` it
    means: every gate outcome recorded for the tree the tick edits is a pass. Any recorded failure
    skips the stage; so does a tree with no recorded outcome, because "no evidence" is not
    "green" and E4.8's contract is cite-or-run, never assume. A skip records a skipped stage
    naming the failing gate(s) or the absence, leaves the checkbox byte-identical — nothing flips,
    so nothing needs reverting — and changes no exit status, since the red gate already decided
    the run. The condition is only real if the evidence survives the run, which today it does not:
    every `state.json` in the state root shows `gate_outcomes: []` (94 of 94, E6.1's red `suite`
    among them). **H0.1 lands first and fixes that** — it records the loss, its mechanism and its
    concurrency, and it is where the fix is proven. This task names it as a predecessor rather
    than restating it, so one decision has one owner and the tick does not carry a second,
    differently worded copy of it.
  - Done when: replaying the E6.1 shape (green `build`/`doctor`/`agents`/`prompts`, red `suite`)
    leaves the box unticked, records the stage `skipped` naming `suite`, and writes no roadmap
    change at all; the same run with `suite` green ticks it exactly once; a second green run on an
    already-ticked box is a successful no-op; a run whose gates recorded nothing skips with its own
    reason; and no stage in the chain can tick a box the run has no evidence for.
  - Tests: `tests/test_implement_workflow.py` with fake gate outcomes and a fake stage — the skip
    reason, the untouched file, the single tick, the missing-evidence skip — reading outcomes H0.1
    guarantees survive. The persistence test itself belongs to H0.1, not here.
  - Notes: rejected — instruct the agent to "run the tests and tick if they pass": that is the
    judgement that produced the flip and the revert, it pays for a suite run the run has already
    recorded, and it re-opens the same red-gate hole. I3 and I4 stay ungated: they are the repo's
    own documents, and E4.8's gate scope belongs to I5. Depends on H0.1 (the evidence) and H3.1
    (the stage it gates).

- [ ] **H3.3. Give `fix` the same tick, once its loop converges** (Design 8.4, Design 8.6, H3.1)
  `fix` is where a task the review found wanting actually finishes — every `prompt-to-fix` chain
  ends in it — and no stage of it has ever touched the roadmap. A `fix` run that closes a task's
  last approved follow-up leaves that task's box unticked, so `aidw tasks --next` keeps offering
  work on a roadmap that still calls the previous task open. The other half is the double claim:
  with the tick in `implement` and nothing in `fix`, the box can be asserted twice, or by a run
  whose own tests are red.
  - Deliverable: one stage definition shared by both workflows — the `A1` precedent (one id, one
    prompt, one agent, two workflows, so the two ticks cannot drift) — emitted by `expand()` from a
    new post-loop section on `WorkflowDefinition` rather than bolted on in
    `aidw/workflows/fix.py`, so `--dry-run` plans it and `validate_stage_list` classifies it as
    core. In `fix` the task id comes from the newest `implement` run's recorded `state.task` for
    the PR-head branch — `run.py`'s re-read-the-run-state trade-off, not a new `gh` query and never
    the PR title; a branch with no such run falls back to reversing `repo.branch_pattern`, and when
    neither yields a roadmap entry the stage is **skipped with a reason** and the run still
    succeeds, because `fix` must keep working on PRs that are not AIDT tasks. The condition is
    `WHEN_EVIDENCE_GREEN`, read from this run: `select` returned `EXIT_NONE_AVAILABLE` (not
    `--max-iterations`, not a denied gate, not an ambiguous verdict), every `iter{N}-test` stage
    succeeded, and the last recorded re-review verdict is `Approve`. The edit is left uncommitted
    like every other `fix` stage (no stage of `fix` commits), and the outcome is recorded as
    `state.pr.roadmap_ticked` plus the skip reason.
  - Done when: a `fix` run closing its last approved follow-up ticks the box once and records
    `roadmap_ticked: true`; a run stopped by `--max-iterations`, by a denied gate, or by a failed
    `iter{N}-test` ticks nothing and records why; a PR whose branch maps to no roadmap entry skips
    and still exits 0; the stage appears once per run — never once per iteration — in `state.json`,
    `run.log` and the `--dry-run` plan; and a whole `prompt-to-fix` chain leaves one task ticked
    exactly once, whether the tick came from `implement` or from `fix`.
  - Tests: `tests/test_fix_workflow.py` with fake `select` payloads and fake stages (once-per-run,
    the three skip reasons, the task-id resolution), `tests/test_stage_registry.py` for the
    post-loop expansion and its carried condition, and `tests/test_run_workflow.py` for the
    chain-level exactly-once assertion.
  - Notes: rejected — put the tick in the fix loop's `tail`: it would run per iteration, so
    iteration 1's green tests would claim the task done while an approved follow-up was still
    open, and nothing in the chain can untick. Rejected — run the repo's `suite` gate inside `fix`
    to reuse E4.8 evidence: F2 already ran this iteration's tests, a second suite run doubles every
    iteration's cost, and the stage records its decision either way. Depends on H3.1 (the stage)
    and H3.2 (the condition).

## Explicit non-goals

- Phase 02's convergence rules (finding sampling, fixer verification, the terminal review) are
  done and unchanged here.
- Model routing and per-stage model overrides are `E4.6`'s; H2.1 makes the prompt smaller rather
  than buying a bigger context window.
- Deciding that a task is too large to author in one prompt is an authoring concern (L5.1 and the
  E4.5 split); this phase makes a failure survivable, it does not prevent one.
- Gate failures are never retried automatically (design §10) — a `Request changes`, a `Blocked`
  verdict and the revision budget's terminal review all keep failing closed. H1.3's continuation
  is an explicit operator action on one recorded run, not a retry.
- Moving the tick to the merge. AIDT still never merges (design §13), so H3 makes the tick
  evidence-based inside the run that produced the evidence; it does not make a merge the proof.
