# Summary — 05-Q1.1: Withhold the PR when the tester's in-scope verdict is `Fail`

## The problem it was solving

The `I2 test` stage of `aidw implement` can conclude that the change fails its own acceptance
criteria and still exit 0 with the stage recorded as `SUCCEEDED`. The verdict lives in the
tester's final message as prose, not in the stage status, so the workflow's status-based checks
saw nothing wrong. `implement` therefore went on to run `I6 pr` over an in-scope `Fail`, opened
a pull request for a change the tester had just said was broken, and the reviewer then
re-found the same defects while the `fix` loop re-fixed them. The build results record that a
single task had one defect found independently by the tester, the reviewer and the fixer. The
problem was not a missing test but a missing decision: the workflow never read the verdict it
had already asked the tester to produce.

## The core idea

The central change is that the **workflow**, not the agent, parses `I2`'s recorded final message
and decides whether the PR may proceed — the same division of labour `aidw review` already uses
for `R1`'s verdict. `prompts/test.md` now ends the tester's report with a bare, machine-parseable
declaration (`Test verdict: Pass`, or `Test verdict: Fail` followed by a
`Failing in-scope criteria:` line), and a pure helper in `aidw/workflows/implement.py` reads that
declaration from the recorded `test` `out.txt`. Because the verdict is prose, the check is
message-content based and the tester's stage still exits 0 and stays `SUCCEEDED`. Any in-scope
`Fail`, and any verdict that cannot be parsed at all, stops the run `BLOCKED` with exit 3 before
`I6`, so no PR is opened; `Pass` proceeds unchanged.

The competing option — checking `record.status == SUCCEEDED` — was rejected because it would let
an in-scope `Fail` through unchanged. The prompt and the parser were edited together because the
declaration tokens are prompt-fixed: `design.md` §8.2 names none, so `prompts/test.md` is the
contract that emits them. A bare line (no heading, code span or fence) was chosen over a looser
match so that a quoted or fenced example cannot be read as the tester's conclusion, following the
prose-only discipline recorded in §18.

## What was built, piece by piece

**The tester's declaration contract** (`prompts/test.md`). The prompt's "Return" section gains a
`Scope:` line per criterion and a new "Verdict" section, and its "Final response" section tells
the tester to finish with the declaration block. `Scope:` separates an in-scope failure from an
`Unverified` criterion, a criterion outside the change's scope, and a pre-existing or unrelated
failure, all of which stay in the per-criterion report and never make the verdict `Fail`. That
separation is what lets a human audit why the workflow did or did not stop, while the parser
reads only the declaration block. Because `fix`'s `F2 test` uses the same prompt, it emits the
block too; the build results record that `fix.py` reads only the stage status and never the
message, and that no verdict parse was added on the fix side, so `fix` is unaffected.

**The parser** (`aidw/workflows/implement.py`). `_parse_test_verdict` is pure — no I/O, no
mutation — and returns `("Pass", [])`, `("Fail", [criteria...])`, or `None`. It blanks fenced code
blocks first so the prompt's own fenced example is not mistaken for the verdict, then matches
only a bare capitalised declaration line, which rejects both a heading and a code-span
declaration such as `` `Test verdict: Fail` ``. It deliberately does not reuse `verdict.py`'s
matcher, because that matcher accepts backticked tokens for a label that carries its own
meaning; here a copy would read a quoted example as a verdict. A `Fail` without the
`Failing in-scope criteria:` line is still `Fail` — the criteria are best-effort naming, so the
list being missing does not turn a definite failure into an "ambiguous" one.

**The stop gate** (`_test_verdict_stop`, same module). The gate reads the recorded `test` stage
through the existing `_read_out`, keyed by the stage name rather than its position so a
repo-declared stage list cannot move the stage it reads. A `Fail` records
`state.pr["test_verdict"] = "Fail"` plus `state.pr["test_failing_criteria"]`, prints the criteria,
sets `state.status = BLOCKED`, and returns exit 3; an unparseable verdict sets
`state.pr["test_verdict"] = None`, names the specific ambiguity, and stops the same way. Both stop
messages name the forward path, and both are written before returning so the decision survives
the run ending there. A `Pass` records `state.pr["test_verdict"] = "Pass"` and returns `None` so
the approve gate and `I6` run unchanged.

The fail-closed branch covers more than malformed prose. Because the gate reads the recorded
stage, a resumed run over a `SUCCEEDED` `test` whose `out.txt` is gone hits the same path; a
fresh run whose `I2` exhausted the inherited retry can record a successful stage with an empty
final message, and empty text parses to `None`. Both stop `BLOCKED` with exit 3 naming the
ambiguity, and the build results confirm no PR is dispatched in either case.

**The gate's placement and its resume semantics.** The check sits after the whole pre-PR block
(`I1`–`I9` and `I7`, on both the serial and `--parallel` paths) and before the
`approve-implementation-pr` gate. The roadmap scopes the stop to withholding `I6`, so the run is
not aborted earlier, and `I7` is deliberately not withheld: with green gates and an
inspection-only `Fail` the tick can still flip its checkbox uncommitted, which is acceptable
because `I6` is the only committer and never runs. Reading the recorded stage rather than a live
run gives the resume rule its shape: a plain `--resume` skips the already-`SUCCEEDED` `I2` and
re-reads the same recorded verdict, repeating the stop identically while the verdict is
unchanged — correct, not stuck — while re-testing requires `--from test` (with `--resume` to stay
in the same run), which re-runs `I2` and everything after it. Both stop messages state this so
the first real `Fail` does not present as a dead end.

**Documentation and pins.** `design.md` §8.2 gains the bullet describing the `I2` verdict gate,
including its resume rule, and §17 gains the single `Z10` row recording the prompt-fixed
decisions (the tokens, the bare-line shape, the `BLOCKED`/exit-3 fail-closed boundary, the
imperative gate's placement, the parser's home in `implement.py`, and the resume rule) with their
rationale. `tests/test_design_doc.py` pins those sentences so the design cannot drift from the
code. The roadmap entry Q1.1 is ticked.

**Tests** (`tests/test_implement_workflow.py`). The six hand-calculated parser cases cover
`Pass`, `Fail` with criteria, `Fail` without criteria, a fenced declaration being ignored, a
code-span declaration being ignored, and no declaration returning `None`. The end-to-end
fake-stage runs cover an in-scope `Fail` (exit 3, `BLOCKED`, `pr` never dispatched, no approve
gate recorded, criteria in `state.pr`, stderr naming both the criteria and the `--from test`
path), the same stop on a resumed run without re-running the tester, `Pass` dispatching `pr`,
`Pass` with an out-of-scope or pre-existing `Result: Fail` in the prose still proceeding, and a
missing or empty recorded `out.txt` stopping `BLOCKED`. The existing recorder's `test` message
was re-baselined to emit a passing verdict so the older fake-stage cases keep working.

## What it deliberately did not do

- **No test-verdict gate on `fix` (`F2`), and no change to `fix.py`'s convergence rules.** Q1.1
  is `implement` withholding the PR only; `fix` shares the prompt and reads only the stage
  status, which the build results record as unchanged.
- **No earlier stop.** `I3`–`I9` and the serial/parallel dispatch were not reworked to fail fast
  after `I2`, because the roadmap scopes the stop to withholding `I6`.
- **No stage-registry change.** `stage_registry.py` and `docs/workflow-stages.md` were not
  touched and no `when=` condition was added — that is S1.1's separate `WHEN_PATHS_CHANGED` task.
- **No change to the tester's exit-code behaviour, and no new prompt or agent.**
  `REQUIRED_PROMPTS` is unchanged.
- **No commit, push or pull request from this record stage.** Delivery belongs to `/pr`; the
  build results record that no PR existed at the time they were written.

## Verification

The build results record this repo's own gate list, with install, the test suite, doctor, agent
validation, prompt checks, the roadmap parser and a whitespace check all passing. `uv sync
--frozen` passed. The test row is the `suite` gate — `uv run --frozen pytest` — recorded as
`2213 passed in 49.11s`; the task's cases in `tests/test_implement_workflow.py` and
`tests/test_design_doc.py` are included in that single run, which was not re-invoked for them.
That suite outcome was cited from the run's own recorded gate for tree `73f3fb893262` at
`2026-11-19T07:51:10Z` by the `test` stage under the same declared scope, not re-run at record
time. `uv run --frozen aidw doctor` passed with `21 checks: 0 failed, 2 warning(s)`, the warnings
being the dirty working tree and the missing `.mcp.json`; both are described as expected while
the implementation and the results document remain uncommitted. `aidw agents validate --strict`
passed with `11 agent config(s): 0 error(s), 0 warning(s)`, `aidw prompts check` passed with
`0 error(s), 0 warning(s)` across toolkit defaults and resolved repo prompts, `aidw tasks
--validate` exited 0 with no output, and `git diff --check` exited 0 with no output.

Two rows are **unverified**, with the reasons the build results give. **Lint** is unverified
because the repo configures no linter — `AGENTS.md` states that `pytest` is the only
verification, and `design.md` §15 agrees. **Build** is unverified because the repo's gate list
names no build command, so no build gate was defined to run. The task-specific verification rows
the build results list — the parser cases, the in-scope `Fail` stop, the resumed stop, `Pass` and
the out-of-scope/pre-existing `Fail` proceeding, the missing/empty `out.txt` stop, the design-doc
pins, and the roadmap parser guard — are each recorded as passing, all of them covered by that
same `2213 passed` suite run. No pull request exists yet, and the build results record that
`/pr` will replace the not-yet-opened note with the real number.
