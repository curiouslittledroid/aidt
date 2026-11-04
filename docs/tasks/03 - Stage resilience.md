# Phase 03: Stage resilience

Make one bad round survivable. Today a stage that returns nothing, a review prompt that
outgrows the model's context, or a provider hiccup discards the whole run — including every
stage that already succeeded — because `aidw prompt` cannot resume and the only recovery is a
manual re-run from the author.

This phase changes the Pi attempt loop, the delta brief's size contract, and the prompt
workflow's resumability. It does **not** change the loop's convergence rules (Phase 02), model
routing, or the stage shapes of `implement`/`review`/`fix`/`approve`.

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
| `E9.1` (rewrite `design.md`) | H1.1 and H1.2 amend design §9.3 and §10 and record the decisions in §17; E9.1 carries them forward. |

## How this phase is driven

Each task is authorable through the toolkit itself:

```bash
uv run aidw tasks --phase 03
uv run aidw prompt 03 H1 H1.1     # then implement, test, review, PR
```

Parser guard (run after any edit to this file — a missing period after the task id silently
collapses every id and breaks `aidw prompt`):

```bash
uv run python -c 'import pathlib; from aidw.roadmap import load_tasks; t=load_tasks(pathlib.Path("docs/tasks")); assert t, "no tasks parsed"; bad=[x.task for x in t if "." not in x.task]; assert not bad, f"MISPARSE: {bad}"; print(f"{len(t)} tasks, none collapsed")'
```

Every behaviour change here is proven by a fake Pi argv or a fake stage (AGENTS.md §Tests, design
§15) — no task in this phase may invoke a real model, and each must be observable from
`state.json`/`run.log` without reading a transcript.

## Epic H1: A stage that returns nothing

- [ ] **H1.1. Retry a stage whose final message never arrived** (Design 10, Design 14)
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
