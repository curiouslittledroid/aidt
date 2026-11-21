# Prompt-to-fix stage gating

What is examined at the end of each stage before the next stage in the
`aidw run prompt-to-fix` chain may run.

The chain runs the five orchestrators in order — `prompt → implement → review →
approve-followups → fix` — and stops at the first non-zero exit. Each orchestrator owns its
own preflight, gates, state and resumability (`aidw/workflows/run.py`). The interesting
behaviour is not the chain glue but the two layers of checks that decide whether a stage,
loop round, or successor may proceed.

## Two layers of checks

### A. Generic per-stage checks — every stage

`aidw.runner.run_stage` (`aidw/runner.py`) applies the same three checks to every stage
before it can be marked `SUCCEEDED`:

1. **Provider failure** — Pi's exit code, timeout, empty final message, or a transient error
   (transient errors retry first). Pi exiting 0 only means the agent finished, not that it
   did the work.
2. **Cost ceiling** — `usage.cost_usd > agent.max_cost_usd` fails the stage.
3. **Stage postcondition** (`spec.verify`) — after a successful Pi run the stage may re-read
   external state and fail itself if a declared invariant does not hold.

A failure records `state.resume = {"next_stage": ...}` and the run stays resumable.

### B. Workflow-level gates and conditions

Between stages, the workflows evaluate conditions, gates and verdicts. They are the subject
of the walkthrough below.

## Stage-by-stage walkthrough

### 1. `prompt` workflow

`aidw/workflows/prompt.py`.

**P1 `task-prompt`** authors the prompt, then the **review loop** (`P2`) begins.

At the end of each **review round** (`task-review-N`) the loop parses the reviewer's prose
with `aidw.verdict.parse_verdict` (`aidw/verdict.py`):

- **`Request changes`** — the fix stages run (one per *blocking* finding, one combined
  *could-fix*, or an *unparseable* fallback), then a reconcile stage, then another review
  round. The loop is bounded by `max_revisions`; the last round is review-only (`L4.1`).
- **`Approve`** (or approve-with-blocking-findings) — the loop converges and the human
  **`approve-task-prompt`** gate is asked.
- **`Blocked`** — the run ends blocked and resumable.
- **Classification stops** (`G1.1`) — a finding classified *spec-gap* or *unclassified*
  stops the loop rather than acting on an unactionable review.

The verdict parser is deliberately strict (three passes over prose only): a truncated
review that found defects but never emitted a verdict **fails closed** — it never approves
(`M1`/`M3`, design §17).

### 2. Chain guard before `implement`

`run.py:task_to_pr` / `prompt_to_fix`:

- Derive the branch (`derive_branch_name`) — a malformed `branch_pattern` → exit 2.
- Locate the task worktree — absent → exit 4, printing the add-worktree command.
- Find the task prompt (newest `docs/task-prompts/<phase>-<task>*.md`) — none → exit 2.

### 3. `implement` workflow

`aidw/workflows/implement.py`.

- **I1 `impliment-task`** runs, then **I2 `test`**. At the end of I2,
  `_test_verdict_stop` reads the tester's **message** — not its exit code, because the
  tester exits 0 and reports `Fail` in prose:
  - **`Pass`** — `I6 pr` may run.
  - **`Fail`** (in-scope criteria) — withhold **I6**, `state.status = BLOCKED`, no PR.
  - **Unreadable** — fail closed the same way (`Q1.1`).
- **I3 `update-traceability`** and **I4 `update-architecture`** — `when=paths-changed`
  (`S1.1`/`S1.2`): the workflow computes the change set and runs the stage only if it
  touches the declared `when_paths` (I4 defaults to `docs/architecture`). Evaluated *before*
  `run_stage`, so an agent never runs a stage whose trigger does not hold.
- **I5 `record-implementation-results`** is the sync point and the stage that buys the
  **whole-repo verification gate** — the gate command's outcome is recorded against the tree
  identity (`E4.8`).
- **I7 `update-roadmap`** (the tick) — `when=evidence-green` (`H3.2`). `tick_evidence`
  examines:
  1. does the current tree have an identity?
  2. is there at least one recorded gate outcome **for exactly that tree**?
  3. did **every** such outcome **pass**?

  Anything else → the stage is recorded `skipped` with the reason, and the agent is never
  offered the checkbox. No evidence is not green; another tree's pass is not this run's
  evidence.
- The human gate **`approve-implementation-pr`** runs before **I6 `pr`**, which opens the PR
  and records `pr.number`.

### 4. Chain guard before `review`

`run.py:prompt_to_fix` re-reads the PR number from `implement`'s `state.json`
(`find_pr_number`) — no `--pr` and none recorded → exit 2.

### 5. `review` workflow

`aidw/workflows/review.py`.

- **R1 `code-review`** produces a verdict and findings.
- **R2 `review-findings-to-github`** — `when=findings`: runs only if R1 produced findings,
  publishing parent/child GitHub issues.
- Records **`pr.followups_published`** on both successful exits.

### 6. Chain guard before `fix`

`run.py:review_and_fix` calls `review_published_followups()`:

- **"Nothing published"** — the chain ends **gracefully (exit 0)** instead of running the
  fix loop into a postcondition it cannot satisfy (decision `I2`).
- **Unreadable/absent record** — keeps the old path and runs `fix`.

### 7. `fix` workflow

`aidw/workflows/fix.py`.

- **A1 `approve-review-followups`** — the one gate the chain **auto-approves** (recorded as
  a skip, decision `I1`) so the cycle is unattended; `--deny-gates approve-followups` still
  refuses it.
- **Loop F1→F2→F3→F4** per iteration (fix → test → code-review → publish findings). The
  loop is re-derived from GitHub state each round and **converges when `select` reports
  nothing available** — no more followups.
- **Post-loop I7 `update-roadmap`** (the shared evidence-green rule, with fix's own
  three-part variant, `H3.3`) then **F5 `commit-and-push`**. F5 deliberately has **no**
  `when=` token: a converged run must still publish its accumulated edits even when the tick
  was withheld (`D2`).

## The check mechanisms

| Mechanism | Where | Decides |
|---|---|---|
| `when=findings` | `stage_registry.py` | R2 / F4 run only if the review reported findings |
| `when=blocking` / `could-fix` / `unparseable` | `stage_registry.py` | which fix stages a review round spawns |
| `when=evidence-green` | `stage_registry.py`, `implement.tick_evidence` | whether I7 may tick the roadmap |
| `when=paths-changed` | `stage_registry.py`, `implement` | whether I3/I4 run for this change set |
| Human gates | `aidw/gates.py:decide` | approve-task-prompt / approve-implementation-pr / approve-fix-pr / approve-followups |
| Verification gates | `aidw/verification.py:run_gate` | whole-repo command exit code against a tree identity |
| Verdicts | `aidw/verdict.py:parse_verdict` | Approve / Request changes / Blocked from agent prose |
| Test verdict | `implement._test_verdict_stop` | Pass/Fail in the tester's message (not exit code) |
| Stage postcondition | `runner.run_stage` (`spec.verify`) | a declared invariant re-read after Pi exits 0 |
| Cost ceiling | `runner.run_stage` | `usage.cost_usd > max_cost_usd` |
| Loop convergence | `stage_registry.py` loop descriptors | review rounds (max_revisions) and fix iterations (GitHub state) |

## Underlying principle

Every "may the next stage run?" decision is **fail-closed and evidence-based, never
assumed**:

- a verdict must be *found* — else `None` fails closed;
- a test must *report* `Pass` — else the PR is withheld;
- a tick must have *green gate evidence for this exact tree* — else it is skipped;
- a path-scoped stage must *actually* touch its paths — else it is skipped;
- a chain must *find* the worktree, the prompt and the PR number — else it stops.

There is no path that turns "unknown" into "skip" or "approve": ambiguity always withholds
the next stage and leaves the run resumable with its reason recorded.
