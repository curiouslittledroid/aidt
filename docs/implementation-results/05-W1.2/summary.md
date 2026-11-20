# Summary — 05-W1.2: `--dry-run` must not create a run or become a `--resume` target

Branch `05-W1.2`, as recorded in the build results at
`<paths.implementation_results_dir>/05-W1.2/build-results.md` (date 2026-11-20). This
summary is drawn from that document and from the task prompt under
`paths.task_prompts_dir`; the build results remain the authority on what was actually
done and on every verification outcome stated here.

## 1. The problem it was solving

A `--dry-run` was meant to be a preview — a printed plan that changes nothing. It was
not. Each of the five workflows (`implement`, `prompt`, `approve`, `review`, `fix`) and
`aidw exec` reached `create_run` before its own dry-run split, and
`run_stage(dry_run=True)` created `prompts/`, wrote the rendered prompt and saved the
PLANNED and SUCCEEDED records before it ever looked at the `dry_run` flag. A preview
therefore left a real run directory, a `state.json`, a `run.log` and a rendered prompt
behind.

That mattered for two reasons recorded in the build results. First, it produced a run
that never invoked Pi yet looked like a fully succeeded run — the record cites the live
observation `20261119T233947Z-05-S1.2-implement`, which recorded all nine stages as
succeeded without invoking Pi and would have captured the next genuine `--resume`.
Second, because `--resume` resolves through `_latest_implement_run` /
`_latest_prompt_run` newest-run selection, such a phantom could become exactly the run
a later `--resume` attaches to. `aidw exec --dry-run` shared the defect through the
`run_stage` seam, and its help text ("Plan only; do not invoke Pi.") advertised less
than a no-writes contract. The task closes that gap so a preview can never silently
become resumable state.

## 2. The core idea

The rule is decided once: **a dry run creates no run at all** — no run directory, no
`state.json`, no `run.log`, no staged rendered prompt, no stage record — applied
uniformly across all five workflows and `aidw exec`. The roadmap Notes had offered two
options; the live phantom observation above forced the stronger one, and applying it
once avoids five divergent dry-run behaviours.

The structural consequence is what makes the rest follow: with no run recorded,
`_latest_implement_run` and `_latest_prompt_run` can never select a phantom, so resume
selection needs no change, and no legacy-phantom detector or `state.json` "never invoked
Pi" marker is added (`runs/` is machine-local operator state per AGENTS.md; pre-existing
phantoms are never deleted, migrated or marked).

Two supporting decisions turn that rule into something implementable without disturbing
the shared seam. The write-free planning substitute is a `NullLogger` plus a never-saved
`planned_run` with `run_stage`'s signature unchanged, chosen over a `None`-tolerant
`run_stage` because the latter would push `is not None` branches into the shared seam
and every call site to avoid a state that `planned_run` already produces. And a plan
names no run: the in-memory id is the literal `PLANNED_RUN_ID`, planned directory text is
the literal `PLANNED_RUN_DIR_TEXT`, so two dry runs print byte-identical output and no
fabricated run id is ever shown — a rejected alternative was a
`run: (planned; --dry-run creates no run)` line, which every dry-run test would have to
pin and an operator could copy. The one-run-per-worktree lock is still acquired in
dry-run, so a peer holding it is still refused with exit 4; only the run-state writes are
skipped. `aidw exec --dry-run` keeps the same rule and drops its `rendered:` echo
outright, since a planned path would fabricate the run id the rule forbids.

## 3. What was built, piece by piece

The work divides into the plumbing that makes a write-free plan possible, the rules
applied at each entry point, and the documentation and tests that pin them.

**Plumbing first, because every later piece depends on it.** `aidw/log.py` gains
`NullLogger`, a `RunLogger`-compatible logger with the same methods and the same
`<ts> [LEVEL] <msg>` line format that performs no `mkdir` and no file write; this is what
makes the constructor-mkdirs trap unreachable on a dry-run path, because `RunLogger` is
simply never constructed there. `aidw/state.py` gains `PLANNED_RUN_ID`,
`PLANNED_RUN_DIR_TEXT` and `planned_run()`, which takes `create_run`'s exact keyword
arguments and returns the same `RunState` without saving anything; the shared
construction is factored into `_new_run_state` so the two cannot drift, and `create_run`
keeps its signature and its `save`.

**The shared seam.** `aidw/runner.py` moves the rendered-prompt write and both
PLANNED/SUCCEEDED `save()` calls behind `not dry_run`, and `record_skipped` gains an
additive `dry_run` flag so it skips its save too — that last part exists because `fix`'s
`withhold_tick` reaches `record_skipped` on a dry-run path, a write the original
requirements did not enumerate. `record.rendered_prompt` keeps its existing relative
string, which fabricates no run id, and `state.record_stage` stays in memory.

**Each entry point.** All five workflow modules take the same shape: the dry-run branch
uses `planned_run` and `NullLogger`, passes the literal
`Path(PLANNED_RUN_DIR_TEXT)` where a real run passes `run_dir(runs_root, state.run_id)`,
drops its own tail `save(directory, state)` and its `run:` line, and has its stale
"a dry run reaches `create_run` too" lock comment rewritten so it no longer contradicts
the no-write path. Beyond the shared shape, `review.py` plans
`<run dir>/artifacts/review-manifest.json` so its `manifest:` line, publisher argv and
R2's rendered extra agree; `fix.py` guards its artifacts `mkdir` and plans the F4
manifest pointer and F1's `{closing_body}` under the literal planned directory. Real runs
are untouched and still receive the absolute path E7.3's PR 110 requires. `aidw/cli.py`
brings `exec` onto `planned_run`/`NullLogger`, drops both its `run:` and `rendered:`
lines on the dry-run path, and corrects its help text to "Plan only; no writes."

**Documentation.** `design.md` §8.2, §9.1 and §9.4 now state the no-run rule, §17 gains
the single `Z14` row recording the rule and the resolved decisions with their rationale,
and §19 items 8–10 say "creates no run state".

**Tests.** Thirteen modules were re-baselined, five more than the task prompt listed,
because those five also read a dry run's rendered prompt or pin the new planned-state
helpers (`tests/test_conventions_injection.py`, `tests/test_prompt_resolution.py`,
`tests/test_override_integration.py`, `tests/test_plan_stages.py`,
`tests/test_state.py`); the build results record this as a deviation that follows from
the owner decisions. The eight prompt-listed modules carry the contract itself:
`test_runner.py` for the seam returning a valid record with nothing written,
`test_implement_workflow.py` for `--dry-run` and `--dry-run --resume` leaving the runs
tree byte-identical while still printing the plan and planned gate, `test_cli.py` for
`exec`'s no-run and no-echo behaviour plus the unchanged real-run echo,
`test_prompt_workflow.py` for the no-run rule with the E8.2 identity assertion moved onto
a real run rather than dropped, the approve/review/fix modules for plan-printed and
no-run-directory, and `test_design_doc.py` for exactly one W1.2 §17 row and the §19
wording. The planned-path tests assert no `<run dir>` directory appears in the working
tree as well as an unchanged runs tree, since the placeholder is a relative path and a
stray write would land in the repo rather than under `runs/`.

## 4. What it deliberately did not do

- **It did not start other epics' unchecked tasks** (`C1.*` gate commands, `G1.*` review
  depth, `B1.1` batch fixes, `O1.1` blocked bash); W1.2 is the last entry in epic W1 and
  no later task in the epic depends on it.
- **It did not add a legacy-phantom detector or a `state.json` "never invoked Pi"
  marker.** The fix is structural — after it, no such run exists to detect — and `runs/`
  is machine-local state the operator owns, never deleted, migrated or marked by the
  toolkit.
- **It did not change resume semantics beyond the dry-run rule**:
  `_latest_implement_run`/`_latest_prompt_run` newest-run selection, the still-running
  guard, and `I7`'s byte-exact tick postcondition (Z13) are all left as they were.
- **It did not change `aidw run` chain-level dry-run behaviour** — the `--pr 0`
  placeholder and the `(planned; --dry-run opens no PR)` line are out of scope.
- **It did not commit, push or open a pull request**; the build results record the PR as
  not yet opened, owned by the delivery stage.

## 5. Verification

The record is green on every step that could be run, and honest about the two that could
not.

`uv sync --frozen` succeeded (`Checked 19 packages in 1ms`). The suite gate passed:
`uv run aidw gate run suite --ignore docs/implementation-results --ignore
docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv run --frozen
pytest` returned a **reused** gate `suite` that had passed for tree `8200590de259` at
`2026-11-20T04:44:02Z` by stage `update-traceability`, recording **`2281 passed in
50.08s`** for the full 2281-test suite. The build results are explicit that this outcome
was cited from the run's own recorded gate rather than re-run, so it is the same run's
observation of the same scoped content. `uv run --frozen aidw doctor` reported `22
checks: 0 failed, 2 warning(s)` — the warnings being a dirty working tree and a missing
`.mcp.json`; `uv run --frozen aidw prompts check` reported `0 error(s), 0 warning(s)` for
both toolkit defaults and resolved repo prompts; `uv run --frozen aidw agents validate
--strict` reported `11 agent config(s): 0 error(s), 0 warning(s)`; and `git diff --check`
exited 0 with no output.

Two top-level rows are **unverified**, each with the reason the build results give: the
**Build** row, because no build command is configured in `AGENTS.md` or
`aidw/conventions.md` and the gate list contains no build step; and the **Lint** row,
because no linter, formatter or type-checker is configured, pytest being the only
verification per `AGENTS.md`.

Of the task-specific gates, five are recorded as met and covered by passing tests in that
same suite: `implement --dry-run` and `--dry-run --resume` leaving `runs/` byte-identical
while printing the plan and planned gate; `run_stage(dry_run=True)` writing nothing while
returning the resolved name, status, agent, model and session; `exec --dry-run` creating
no run and printing no `rendered:` line with real runs still printing it;
`prompt`/`review`/`fix`/`approve --dry-run` creating no run directory while printing
their plans; and the single §17 row plus §19 items 8–10 "no run state" wording.

The sixth task-specific gate — "removing the no-write guard in `run_stage` fails a test"
— is **unverified**: the mutation was not separately exercised in this recording run,
and the re-baselined `tests/test_runner.py` assertions are the intended guard. The build
results also note that the prompt named no external validator beyond pytest, so none was
available to run.
