# Phase 02: Prompt loop integrity

Make `aidw prompt` converge: an accurate task prompt in one review round, and an honest
outcome when it cannot. Today the loop **samples** findings rather than closing them, the
fixer applies a reviewer's suggestion without checking it, and when the revision budget runs
out the last round's fixes ship unreviewed under a recorded `approved`.

This phase changes the loop and the three agent prompts that drive it. It does **not**
change model routing, the implement/review/fix workflows, or the product's rules.

## Evidence: the run this phase is derived from

`aidw prompt 00 E1 E1.6` → run `20261026T030249Z-00-E1.6-prompt`:

| | |
|---|---|
| Stages | 21 — 1 author, 3 reviews, **17 fix stages** |
| Cost / wall | $1.504 / 21m40s |

| | |
|---|---|
| Findings | R1 = 6 → R2 = 8 → R3 = 4 |
| Review cost | $0.83 of $1.50 (55%); each round re-derives the whole repo context (~150k input tokens, 18–20 tool calls) |
| Fix-induced findings | **5 of 18** — three of them caused a further round |
| Gate record | `decision: approved`, `detail: verdict=Request changes; revisions=3; assumed_ok=True` |

Across the seven prompt runs so far: 16 reviews, 50 fix stages, 2h26m, $9.54 — **5 of 7 runs
hit the budget, and 3 of 7 were accepted with the last verdict still `Request changes`.**

Three root causes, each traceable to a specific stage:

1. **Bad seed — the prompt was authored against a tree without its prerequisite.** `663ccf9`
   (the E1.6 prompt) has parent `6cd888f` (E1.4), while the E1.5 merge `827c324` is timestamped
   45 seconds before the run started: the run began on a **stale local `main`** and never
   fetched. The author *knew* (`git branch --merged main` was in its tool calls, and it read
   `origin/00-E1.5`) but the stage's only output channel is "return exclusively the path to the
   prompt file", so the unmet dependency was smuggled into an invented `Prerequisite:`
   paragraph instead of stopping the run.
2. **Wrong prescription, obeyed.** Review 1 never inspected the in-flight dependency branch
   (0 mentions of `origin/00-E1.5`; rounds 2 and 3 made 129 and 148). It therefore preferred
   roadmap prose to the branch that implements it and prescribed "align the prerequisite with
   the roadmap (2-tuple)". `task-review-fixes.md` says *"Fix the issues as you suggest"*, so
   fix `1-2` did exactly that; review 2 then raised it as a **Must fix** (the real shape is a
   3-tuple, per `origin/00-E1.5`), and fix `2-1` reversed it.
3. **Isolated edits, never reconciled.** One stage per finding, each told *"Do not address the
   other findings"* and *"Prefer the smallest edit"*, with no post-edit consistency pass:
   fix `1-6` scoped `--json` refusal behaviour in Req 2 without touching `Done when`; fix
   `1-3` asserted `aidw/paths.py` "keeps only `STATE_DIR_ENV_VAR`" (it also defines
   `SCRIPTS_DIR_ENV_VAR`); fix `2-6` kept a fall-through clause it had just contradicted.
   Fixers also cannot attribute their own work — three reported that the diff "includes earlier
   uncommitted fix stages" — because only the final state is committed.

## Gate: do not start before these are known

Phase 02 edits files that later extraction tasks also own. Read this table before authoring
any prompt below.

| Prerequisite | Why it constrains phase 02 |
|---|---|
| `E2.4`/`E2.5` (branch setup becomes a Python stage; `aidw prompt` runs in the control worktree and creates the task worktree) | L1's preflight lives in the same function, and L1.3's "leave no branch behind" is only clean once AIDT owns branch creation. If E2.4/E2.5 land first, implement L1 against the new shape. |
| `E4.1` (stage registry) / `E4.3` (config-driven plans) | Both pin today's chains: E4.1's deliverable covers `prompt.py`'s chain, and E4.3's `Done when` requires `--dry-run` for *each* workflow to be unchanged against a baseline. L4.1 and L3.4 **change `aidw prompt --dry-run`**. Either this phase lands first and E4.1/E4.3 are re-baselined (L6.2), or they land first and L4.1/L3.4 are expressed as registry defaults. Do not do both silently. |
| `E7.1`/`E7.2`/`E7.3`/`E7.4` (prompt buckets, conventions injection D16, agent-guidance neutralisation) | `prompts/task-prompt.md` is bucket **(iii)** — wholly Mythical Forge, moving to `<target>/aidw/prompts/` at cutover. Text L5 adds to it must be product-neutral and must survive that split. `agents/task-author/AGENTS.md` is on E7.4's edit list — L1.3 must not re-do E7.4's reword. L2.4's evidence bundle is D16's mechanism: if E7.3 lands first, build on it. |
| `E3.1` (target-repo config loader) | L4.3's `max_revisions` config key has nowhere to be read from until the `<target>/aidw/config.yaml` loader exists. Until then the CLI flag and the default are the whole surface. |
| `E9.1` (rewrite `design.md`) | L6.2 amends `design.md` §8.1 provisionally and records the decisions in §17; E9.1 carries them forward. |

`prompts/task-review.md` and `prompts/task-review-fixes.md` are bucket **(i) generic — ship
as-is** (EXTRACTION.md §4.2), so L2.1–L2.3 and L3.1–L3.2 are clean toolkit work.

## How this phase is driven

- **Hand-author the prompts for L1.1–L1.3** (they fix the loop's own preflight and the author
  stage). Self-host from L2.1 onward with `aidw prompt 02 L2 L2.1` — that is also the
  observation data for the phase's close-out.
- L1.2's own prerequisite gate applies to this phase, so **the task order below is the build
  order** and each task's prompt may only be authored once every task above it is ticked.
- Every task here is prompt-text, workflow code, or both. A prompt-text change is proven by an
  assertion on the *rendered* prompt (EXTRACTION.md §4.2 E7.2's precedent) or on the workflow's
  stage plan; a behaviour change is proven by a fake-stage test (`tests/test_prompt_workflow.py`
  pattern — never a real Pi model, AGENTS.md §Tests).

## Epic L1: Scheduling and preflight — stop the bad seed

- [x] **L1.1. Fetch, and require the base branch to be current** (Design 8.1, Design 14)
  `aidw prompt`'s preflight checks the branch name and the clean tree and never fetches, so a
  run can start on a stale local base — exactly what E1.6 did. Add a `git fetch` preflight plus
  a comparison of the local base branch against `origin/<base_branch>` (`TargetRepo.base_branch`,
  `aidw/paths.py:160`, default `main` until E3 supplies config).
  - Deliverable: `aidw/git.py` fetch/remote-ref helpers; preflight in
    `aidw/workflows/prompt.py`; a `--no-fetch` flag for offline runs.
  - Done when: a run whose local base is behind `origin` refuses with `EXIT_REFUSED` (4) and a
    message naming both revisions and the corrective command; an up-to-date repo proceeds; a
    failed fetch with `--no-fetch` degrades to a warning and does not block (a network outage
    must not stop authoring); when the comparison cannot be made the run warns, it does not
    silently pass as current.
  - Tests: `tests/test_prompt_workflow.py`, building a bare `origin` plus a clone inline.

- [x] **L1.2. Refuse to author a task whose predecessors are incomplete** (Design 11)
  `aidw prompt` resolves the roadmap entry and then proceeds regardless of ordering. E1.6 was
  authored against E1.4's tree with E1.5 unticked, which is what forced the author to invent a
  prerequisite paragraph. Gate on the roadmap itself: every task **preceding** the target in
  the same phase file must be `done` (`aidw/roadmap.py` `RoadmapTask.done`, already parsed).
  - Deliverable: preflight check plus `--allow-incomplete-prereqs` for deliberate parallelism.
  - Done when: authoring an entry with an unticked predecessor refuses with `EXIT_REFUSED` (4)
    naming every incomplete predecessor (`00 E1 E1.6` in today's tree refuses on E1.5); a fully
    ticked phase proceeds; the flag proceeds with a warning naming what it skipped.
  - Tests: `tests/test_prompt_workflow.py`, using the file's own roadmap fixture.
  - Notes: the check is intentionally phase-scoped and ordering-based — it is the strongest
    available signal (a per-task `requires:` field would be a roadmap-format change, which
    E5.1/E5.2 own, and D15 forbids a second dialect). Phase-scoping means a genuinely
    parallelisable pair needs the flag; that is the accepted trade.

- [x] **L1.3. Give the author a blocked channel** (Design 8.1, EXTRACTION.md §3.8)
  `prompts/task-prompt.md` requires the output to be *exclusively* the prompt path and the
  branch to exist before writing, so an author that finds its prerequisite missing has no way
  to report it — it must either stop silently or invent a workaround. Define `blocked: <reason>`
  as an alternative first line, and have the workflow record the run as `BLOCKED` (3) with no
  prompt file committed and **no branch left behind**.
  - Deliverable: `prompts/task-prompt.md` (neutral wording only — this file moves to the target
    repo at cutover, E7.1), `agents/task-author/AGENTS.md` (coordinate with E7.4's branch
    reword; do not undo it), and the output handling in `prompt.py`.
  - Done when: an author stage whose first output line is `blocked: <reason>` produces a run
    with no prompt file, no `docs/task-prompts/**` diff and no new branch, and the run log
    carries the reason; a normal path is unaffected.
  - Tests: `tests/test_prompt_workflow.py` fake-stage tests for both paths.
  - Notes: L1.2 makes this rare, not redundant — a missing *spec* section, a contradictory
    roadmap entry, or a merge that has not happened yet must still stop the run.

## Epic L2: Reviewer authority — stop the wrong prescription

- [x] **L2.1. Reviewer rules for dependencies and unresolved choices** (Design 8.1)
  Review 1's costliest finding was factually wrong because it reasoned from roadmap prose about
  code that existed on an unmerged branch it never read. Extend the authority chain in
  `prompts/task-review.md` (bucket (i): generic, product-neutral):
  - when the prompt depends on a task whose code is not on the base branch, inspect that branch
    (`git log main..origin/<id>`, `git show origin/<id>:<path>`) and state the revision verified
    — do not resolve a roadmap-vs-branch conflict in favour of the roadmap summary;
  - when the resolution of a finding depends on another task's unmerged implementation, the
    finding is `Blocked`, not a prescription;
  - a `Suggested fix` is a direction, not a decision: when two readings both satisfy the cited
    sources, mark the finding `Blocked` and name the choice.
  - Done when: the rendered reviewer prompt contains all three rules and the existing
    verdict/finding format is unchanged; a fixture review that reports a dependency-branch
    conflict as `Blocked` is recorded as a blocked run, not a fix round.
  - Tests: rendered-prompt assertion plus the `tests/test_prompt_workflow.py` verdict path.

- [x] **L2.2. Require the revision a finding was verified against** (Design 8.1)
  Round 2 and 3 findings that cite `origin/00-E1.5@<sha>` were decisive; round 1's citation-free
  finding was wrong. Require the reviewer to put its evidence in the `Where:` field — that field
  is already parsed and published, so no manifest change is needed.
  - Deliverable: `prompts/task-review.md` (`Where:` must name the file/symbol **and** the
    revision or command it was verified against, or state that nothing could be verified).
  - Done when: the rendered reviewer prompt requires it, and
    `prompts/scripts/review-followup/tests` still pass with an unmodified manifest shape
    (the bundled validator rejects unknown keys — `logic.py:_FINDING_KEYS` — so the evidence
    travels inside `where`, never as a new field).
  - Tests: rendered-prompt assertion; the bundled script suite unchanged.

- [x] **L2.3. Rounds after the first get a delta brief** (Design 8.1)
  Rounds 2 and 3 are fresh sessions that re-derive everything and re-sample the whole space, so
  they re-find leftovers and the fixers' collateral but never confirm resolution. Pass them the
  previous review plus the prompt diff since it, and require a per-finding resolution verdict
  before new findings.
  - Deliverable: an `extra=` block assembled in `aidw/workflows/prompt.py` (the existing
    `render_finding_block` mechanism in `aidw/findings.py`, so no new prompt file and no
    `aidw/inventory.py:REQUIRED_PROMPTS` change).
  - Done when: the second and later review stages receive the previous review text and a
    `git diff` of the prompt since it, the rendered instruction requires
    `resolved`/`not resolved`/`newly contradicted` per prior finding, and round 1 is unchanged.
  - Tests: `tests/test_prompt_workflow.py` asserting the `extra` content per round.
  - Notes: accepts anchoring risk — the independent sample is preserved by running round 1
    unprimed and by L6.1's content assertions; if anchoring shows up in practice, add a second
    independent review at the end rather than reverting this.

- [x] **L2.4. Hand the agents an evidence bundle** (Design 8.1, EXTRACTION.md D16)
  Each review round spends ~150k input tokens and 18–20 tool calls re-deriving conventions,
  spec sections and prerequisite state that the author already gathered. Write
  `stages/<stage>.evidence.md` into the run directory and point the reviewer and fixers at it.
  - Deliverable: an evidence writer in `aidw/workflows/prompt.py` (run-dir artifact, never
    committed — the state root is gitignored, so the tree stays clean); the prompt/`extra`
    pointer.
  - Done when: each review and fix stage's prompt names its evidence path; the bundle contains
    the prompt path, the roadmap entry (with `Done when`), the cited spec headings, the
    prerequisite tasks' tick state, the target repo's gate commands and the base-branch
    revisions; a missing bundle degrades to the current behaviour, never an error.
  - Tests: `tests/test_prompt_workflow.py` asserts the file exists, is inside the run directory
    and is referenced by the stage.
  - Notes: this is the same mechanism E7.3 (D16) generalises for target-repo conventions — if
    E7.3 has landed, extend it rather than adding a second channel.

## Epic L3: Fixer integrity — stop the churn

- [x] **L3.1. The fixer verifies the finding before applying it** (Design 8.1)
  `prompts/task-review-fixes.md` opens with *"Fix the issues as you suggest"*, which converted a
  wrong reviewer prescription into a Must-fix regression that cost a full round.
  - Deliverable: rewrite that line in `prompts/task-review-fixes.md` and
    `agents/task-fixer/AGENTS.md`: verify the finding against the repository and the cited
    sources first; if the suggested fix is wrong or contradicts the sources, make the
    correction the evidence supports and report the disagreement explicitly; never settle a
    material ambiguity (that stays a `Blocked` escalation).
  - Done when: both files state verify-then-fix and the push-back path, and the "smallest edit"
    rule is qualified by the consistency sweep in L3.2.
  - Tests: rendered-prompt/agent-context assertion.

- [x] **L3.2. Sweep the document after editing** (Design 8.1)
  Three of the five fix-induced findings in the E1.6 run were edits that invalidated a
  neighbouring section. Every fix stage must end by re-reading the whole prompt and repairing
  what the edit made stale, naming the sections that must be checked:
  `Requirements`, `Traps / prior review findings`, `Explicit non-goals`, `Tests`,
  `Done when`, and the closing prompt-fixed/ambiguity list.
  - Deliverable: `prompts/task-review-fixes.md` + `agents/task-fixer/AGENTS.md`.
  - Done when: both files require the sweep and name the six sections; the report contract asks
    the fixer to state which sections it re-checked and which it changed because of the sweep.
  - Tests: rendered-prompt/agent-context assertion.

- [x] **L3.3. Snapshot the prompt at every fix stage** (Design 9.1)
  Only the final state is committed, so fixers cannot tell their own diff from their
  predecessors' — three reported exactly that. Write a copy of the prompt into the run directory
  before each fix stage (`stages/<stage>.prompt.md`) so every stage's input is recoverable and
  `git diff` between snapshots is possible.
  - Deliverable: snapshot writer in `aidw/workflows/prompt.py`; keep the single final commit of
    the owned prompt path (design §17's resolved decision — do not start committing per stage).
  - Done when: a run with two fix stages leaves two snapshots under its run directory in stage
    order, they are not tracked by git, and the final prompt is still the single commit.
  - Tests: `tests/test_prompt_workflow.py`.

- [x] **L3.4. Reconcile after each fix batch** (Design 8.1)
  One stage per finding is kept for per-change visibility, but the batch can end internally
  inconsistent. Add one cheap stage after the batch (before the next review) whose instruction
  is to compare the fixed prompt against the full review text and the combined diff, and repair
  cross-section contradictions and any finding it left unaddressed.
  - Deliverable: a `task-review-reconcile-N` stage in `aidw/workflows/prompt.py` using the
    `task-fixer` agent with `extra=` carrying the whole review and the diff; one stage per
    review round, never per finding.
  - Done when: a round with blocking findings runs exactly one reconcile stage after the batch
    and before the next review; a round that approves runs none; a reconcile stage failure
    stops the run.
  - Tests: `tests/test_prompt_workflow.py` (extend the existing per-finding/batching tests).
  - Notes: this changes the `prompt` chain — see the E4.1/E4.3 gate row.

## Epic L4: Termination honesty

- [x] **L4.1. Spend the last revision slot on a review, not a fix** (Design 8.1)
  Today the final round's fixes are applied and *never reviewed*, and the run then records
  `approved` — the E1.6 gate record reads `verdict=Request changes; revisions=3;
  assumed_ok=True`. Reserve the budget so a review is always the last stage for a non-approving
  prompt; a residual `Request changes` marks the run `BLOCKED` (3) and prints the residual
  findings for a human to decide. A `Blocked` verdict keeps failing closed exactly as now.
  - Deliverable: the loop in `aidw/workflows/prompt.py`; `MAX_REVISIONS` semantics documented
    in `design.md` §8.1 (provisionally — E9.1 owns the rewrite) and §17.
  - Done when: `Request changes` × N leaves the run `BLOCKED` with the last review's findings on
    stderr and **no** unreviewed fixes applied; `Approve` on any round still succeeds; a
    `Blocked` final verdict still fails closed.
  - Tests: rewrite `tests/test_prompt_workflow.py::test_three_review_rounds_then_accept_without_another_review`
    (it pins the current behaviour) and keep `::test_a_blocked_final_review_still_fails_closed`.

- [ ] **L4.2. Record what was accepted and what it cost** (Design 9.2, Design 9.3)
  A run that ends `BLOCKED` must say so in the gate record and the run log, and the run should
  carry the per-round evidence a human needs to judge the loop without reading 21 stage files.
  - Deliverable: `state.json` gate detail and run-log lines for rounds run, findings per round,
    fixes applied per round, whether the final verdict approved, and whether any fix stage ran
    after the last review; per-round counts printed in the stage report.
  - Done when: a completed run's `state.json` gate record distinguishes
    `verdict=Approve` from `verdict=Request changes` without reading stage outputs, and the
    per-round counts appear in `run.log`; no new gate-decision vocabulary is invented.
  - Tests: `tests/test_prompt_workflow.py` asserting the state/`run.log` content.
  - Notes: this is deliberately observability only — phase 02 states no cost, round-count or
    latency acceptance criterion; the operator judges from these numbers. Do not turn it into a
    gate.

- [ ] **L4.3. Make the revision budget configurable** (Design 12, Design 8.1)
  Three is a guess. Expose it as `max_revisions` with precedence CLI flag > target config >
  default 3, and keep the toolkit default at 3.
  - Deliverable: `--max-revisions <n>` on `aidw prompt`; the `max_revisions` key documented in
    the config contract; resolution wired to the config loader when it exists.
  - Done when: the flag changes the loop's round count with the default and the flag both
    proven by test, and the effective value is reported in the run summary.
  - Tests: `tests/test_prompt_workflow.py`.
  - Notes: **gated on E3.1** — there is no `<target>/aidw/config.yaml` loader yet, so until it
    lands the flag and the default are the whole surface. Land the flag and the documented key
    now, and complete the resolution when E3.1 lands; if you would rather not split it, hold
    this task until E3.1 is ticked.

## Epic L5: Author upstream quality — fewer findings to fix

- [ ] **L5.1. Give the author the reviewer's rubric before it submits** (Design 8.1)
  The reviewer has a nine-step review order; the author has a format and a conciseness budget.
  Round 1 therefore always carries material findings — in E1.6, half of them were contract
  decisions the author left open (provenance labels for two of six values, the fourth state
  tier, refusal/`--json` precedence).
  - Deliverable: `prompts/task-prompt.md` gains a concise pre-submit self-check that walks the
    same ground as the review order and requires an explicit decision, labelled `prompt-fixed`
    where the spec is silent, for: failure-path precedence when two failures are possible;
    per-mode output contracts on the failure path; the complete label/key vocabulary; why the
    enumerated set is complete; exact comparison semantics; where new shared code lives; and one
    proof per requirement.
  - Done when: the rendered author prompt contains the checklist, the added text is
    product-neutral (no package manager, path or product doc — it must survive E7.1's bucket
    split), and the conciseness budget still holds for the prompt itself.
  - Tests: rendered-prompt assertion; `aidw prompts check` clean.

- [ ] **L5.2. Tell the author to reconcile gates and verifiers** (EXTRACTION.md §3.4, D17)
  E2.2's first review found the done-condition missing the target repo's mandated gate commands.
  The author prompt should require reading the gate list from the target repo's conventions
  (root `AGENTS.md`, optional `aidw/conventions.md`) and naming the exact commands, and should
  require the "Gate impact:" line whenever a task touches a checker, status vocabulary or CI
  gate.
  - Deliverable: `prompts/task-prompt.md` (task-prompt format section) — neutral wording that
    names *where* the gate list comes from, never the commands themselves.
  - Done when: the rendered author prompt requires the reconciliation and names the injection
    source; no product command name appears in the file.
  - Tests: rendered-prompt assertion; coordinate with E7.3 (D16), which owns the injection.

- [ ] **L5.3. Check the conciseness budget in the workflow** (Design 8.1)
  The budget is stated (80–120 lines, <15KB; ~150 lines for larger tasks) and unenforced — E1.5
  shipped 17.9KB and E1.6 14.7KB in 57 lines, with single requirements of 120–244 words. Warn
  from the workflow after the author stage; fail under `--strict`.
  - Deliverable: a size/clause check in `aidw/workflows/prompt.py` with the thresholds and the
    one-line reason, plus the count in the stage report.
  - Done when: a fixture prompt over the byte or line budget warns and `--strict` refuses it;
    the repository's existing prompts are unaffected at the default; the message names the
    offending requirement, not just the total.
  - Tests: `tests/test_prompt_workflow.py`.

## Epic L6: Evidence and close-out

- [ ] **L6.1. Pin the new loop contract in tests** (Design 15)
  A single test module addition that makes each new guarantee fail loudly if it regresses, and
  that reproduces the E1.6 shape as a deterministic fixture (a roadmap with an unticked
  predecessor, a base branch behind its `origin`) — the model-mediated claims are asserted as
  prompt content, which is this repository's precedent for prompt behaviour.
  - Deliverable: a synthesized fixture (no checked-in run artifacts, no real Pi model) plus
    assertions for: the L1.1/L1.2 refusals; the L1.3 blocked path; the L3.4 reconcile stage and
    the L3.3 snapshots; the L4.1 terminal review; the L2.3 delta brief; the L4.2 recording; and
    the presence of the L2.1/L2.2/L3.1/L3.2/L5.1 instruction clauses in the rendered prompts.
  - Done when: deleting any one of those behaviours fails at least one test, and the suite runs
    without a network fetch (the fetch path is exercised through a fake remote) and without a
    real model.
  - Tests: `tests/test_prompt_workflow.py`.

- [ ] **L6.2. Re-baseline the extraction tasks this phase moves** (Design 8.1)
  Record the decisions and hand the baselines over, so E4.1/E4.3 do not fail against a chain
  that changed deliberately.
  - Deliverable: `design.md` §17 decision log entries (preflight refusals, reviewer authority,
    fixer verify/sweep, reconcile stage, terminal-review/budget semantics, evidence bundle);
    a provisional §8.1 amendment; and the E4.1/E4.3 entries in `docs/tasks/00 - Extraction.md`
    amended to say the `prompt` chain baseline is taken **after** phase 02, with the reconcile
    stage and the terminal review named as registry defaults to reproduce.
  - Done when: `design.md` §17 carries every decision this phase made, and no extraction task
    still asserts a `prompt` chain or `--dry-run` baseline that phase 02 changed.
  - Tests: none (documentation); `uv run aidw prompts check` and the suite stay green.

## Explicit non-goals for phase 02

- **Do not change model routing or the independence rule.** `task-reviewer.model !=
  task-author.model != task-fixer.model` (design §5.4) stays as it is; this phase fixes the
  instructions those models receive, not which model runs which stage.
- **Do not restructure the stage registry.** E4.1/E4.3 own turning the hardcoded chains into
  data; phase 02 edits the `prompt` chain in place and hands over the new baseline (L6.2).
- **Do not touch the implement, review, fix or approve-followups loops.** Their loops were not
  measured and are not in evidence here — the report's cost data is prompt-workflow only.
- **Do not add fields to the review-finding manifest.** L2.2 carries evidence inside `where`;
  the bundled validator rejects unknown keys and the manifest shape is documented and shipped
  with the prompts (E6.1/E6.2).
- **Do not add a second roadmap dialect or a per-task `requires:` field.** L1.2 is an
  ordering heuristic over the existing parser; the roadmap format is E5.1/E5.2's contract (D15).
- **Do not move branch creation into the workflow here.** E2.4/E2.5 own that; L1.3 only has to
  avoid leaving a branch behind.
- **Do not add a cost, round-count or latency gate.** No acceptance criterion on loop length —
  L4.2 records the numbers for the operator to judge.
- **Do not re-neutralise the prompts E7 owns.** L5's additions must be product-neutral on the
  way in, and must not undo E7.2/E7.4's wording or re-add product paths to
  `prompts/task-prompt.md`.

## Definition of done for phase 02

- Every L1–L6 task is ticked, and each landed with its own prompt reviewed through the (now
  fixed) loop — the phase is its own first user.
- `uv run --frozen pytest` is green; `uv run aidw doctor`, `uv run aidw prompts check` and
  `uv run aidw agents validate --strict` are clean.
- One end-to-end smoke run on a real task shows: a preflight that fetches and refuses a stale
  base, no authoring when a predecessor is unticked, per-round snapshots and an evidence file
  under the run directory, one reconcile stage after a fix batch, and a terminal review that
  leaves the run `BLOCKED` rather than `approved` when it does not approve.
- The gate records of the next three prompt runs are read and compared by hand against the
  table at the top of this document (rounds, findings per round, fix stages, whether anything
  was accepted unreviewed). This is an **observation**, not an acceptance criterion — no
  threshold is set here, deliberately.
