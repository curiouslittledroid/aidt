# Summary — 05-B1.1: Fix multiple approved follow-ups per iteration

## The problem it was solving

`aidw fix` processed exactly one approved review follow-up issue per iteration, so N approved
children cost N complete fix → test → code-review cycles. Each cycle re-paid for the same branch
state, reviewer context and instructions, and the cost of clearing a review round grew linearly
with the number of small, independently approved findings even when those findings were adjacent
enough to fix together.

The task replaces "one fix per iteration" with a bounded batch per iteration, sized by a flag
(`--fix-batch`, default 3) rather than a constant, while keeping the iteration count capped. Two
things around that loop also needed settling. The shipped fixer guidance,
`agents/fixer/AGENTS.md`, still told a real fixer to fix "exactly one" issue, which would have
made it fix a subset of the children the loop selected. And nothing in the stage environment
exported the batch width: a `--fix-batch 1` honoured by the workflow's own `select` could be
silently widened to 3 by the agent's own `select`. Both are now part of the contract.

## The core idea

"Availability, not arithmetic" is the decision everything else follows. `fix` never decides how
many issues to fix by counting anything — not `closed_issues`, not `childrenInspected`, not the
batch size itself. It asks the existing `select` command for a bounded batch
(`select --limit <n>`) and fixes exactly the children that call returned, in the order returned.
One `F1` fixes the batch, and one `F2` test and one `F3` code-review judge the batch's combined
change set; F3's findings still route to F4 → new children, unchanged.

The JSON contract was shaped to make that split safe. `select` returns a `selected` **array**
whenever `--limit` is passed explicitly — including `--limit 1` — and keeps the single-object
shape when the flag is absent. The shape keys on the flag's presence, not its value: `fix.py`'s
loop and dry-run preview always pass the flag, so they see only arrays; the approval round never
passes it and keeps its unchanged single-object read. The object-to-batch normalisation lives only
in `cmd_select`'s flag branch. To keep that rule from being quietly re-implemented, the loop and
the dry-run preview now share **one** fail-closed batch reader: a non-array, an empty array on
exit 0, or an entry without a usable issue number is refused with the same message in both paths.
Normalising an object into a one-child batch in the preview would have claimed a batch the real
loop would never fix — a preview that lies about what would happen.

The amendment added a further decision in the same spirit: the batch width must reach `F1` **as
data**. F1's variable tuple became `("{pr}", "{closing_bodies}", "{fix_batch}")` and the fixer
prompt reads it as `$3`, rather than as a shell variable an environment might supply — nothing
exports one, and a fix-specific export would teach the generic stage seam about fix batches. The
prompt keeps a documented default as the empty-value fallback so a hand invocation outside `aidw`
still works.

## What was built, piece by piece

At the bottom sits `logic.py`. A new pure `select_available(children, limit)` returns the first N
available children in the parent's native `subIssues` order, always in the batch shape
(`BatchSelection.selected` is a list). It sits beside the untouched `select_first_available`,
which `start`, `fixed` and the flag-absent `select` path keep using, so the two contracts cannot
blur into each other. `ParsedArgs` gained `limit`, and the positive-integer refusal now names the
flag it is refusing instead of hardcoding `--issue`. Scan metadata follows the batch: `skipped`
covers unavailable children up to and including the last selected one, `childrenInspected` is
`len(skipped) + len(selected)`, and `totalChildren` is unchanged. `review_followup.py`'s
`cmd_select` is the only place that chooses between the two shapes, and `aidw/github.py` threads
a `limit` through `select_followups` into `build_followup_argv`, which emits it generically as a
keyword flag.

In `aidw/workflows/fix.py` the loop re-derives the batch each iteration through that
`limit`-carrying helper, reads it with the shared fail-closed reader, and runs one fixer stage
over it. The reader exists because the alternative — a fallback to the first element, or a width
derived from a count — is exactly the one-fix-per-iteration behaviour this task reverses. The
bookkeeping followed the batch: the `closed:` report and the dry-run `child:` block show the
whole batch, the dry-run `select argv:` echo shows the new `--limit`, and the run's resolved width
is rendered into every F1 plan (`_planned_iteration`, `_post_loop_specs` and so through
`_approval_round`) as the third positional variable. `aidw/cli.py` gained `--fix-batch` (default
3), refusing values below 1 the same way `--max-iterations` does, and passes it into `run(...)`.
`--max-iterations` still bounds iterations — now batches — not total fixes, and its help text,
the dry-run `loop:` line and the module docstrings were corrected where they said "one at a time"
or "one fix per iteration", because no test pins that prose and it would otherwise drift
silently.

Closing is where the batch must *not* propagate. `closed_issues` appends one entry per batch
**issue**, each carrying its own `closing_body`, and `run_closes` still makes exactly one `close`
call per entry. Batching fixes is not a licence to batch closes: a half-failed batched close
would strand an issue half-closed, and P1.2's deferred close-after-push ordering is untouched. To
give each issue its own body, `closing_body_path(directory, iteration, issue_number)` returns the
absolute `<run_dir>/artifacts/iter{N}/closing-body-{issue}.md`, and F1's second variable is that
`iter{N}` directory: a variable batch cannot carry N positional paths, and a single
per-iteration body could not say which fix it describes. The workflow — never the agent — creates
the directory at the top of each real-run iteration, before `F1`; a dry-run plan creates nothing.

Failure semantics are deliberately blunt. A failed `F2` or `F3` records **no** `closed_issues`
entry for that batch, so no issue in it is closed — never a subset. Its children stay `OPEN` with
`Status: in progress`, which is correct fail-closed behaviour rather than a defect; the existing
`start --issue` resume path is the recovery, and no auto-close or auto-reopen was added.

The prompt and the shipped guidance moved together. `prompts/fix-next-review-followup.md` was
rewritten for the batch: it reads the width as `$3`, posts one `start` per child in selection
order immediately before that child's edits, writes one closing-body file per issue into `$2`,
and verifies the batch, while keeping the `select`-authoritative and "do not post `Status: fixed`,
do not close" rules. `agents/fixer/AGENTS.md` was brought into scope and rewritten to the batch
wording and the `$3` positional form, because `agent-configs/fixer.yaml` ships it verbatim as
hard rules and prompt text alone does not reliably override an agent file. The operator README,
`docs/workflow-stages.md`'s `fix` inventory and design §8.4 were updated to the same
bounded-batch wording.

The design decision is recorded in §17 as **Z20**, not the `Z14` the roadmap entry names: `Z14` is
already the dry-run-ownership row, and `aidw/conventions.md` forbids reusing or renumbering an id.
The new row is appended at the next free id and records the staleness; the roadmap's "Z14" was
left untouched, mirroring how the `Z18` row handled G1.1's stale "Z13".

## What it deliberately did not do

- **It did not batch the close.** `run_closes` remains one `close` per recorded entry; P1.2's
  close-after-push ordering, one-close-per-entry rule and the exact `Status: fixed` marker are
  unchanged. A wrong close posts an irreversible comment, so the batch stops at fixes.
- **It did not touch 05-P1.1 or 05-P1.2.** Verified commit-and-push (`F5`) and deferred close are
  inputs here, not outputs; re-opening them, or the D3 commit table, was an explicit non-goal.
- **It did not touch `aidw/workflows/implement.py`'s verdict gate.** Q1.1 (withholding the
  implement PR on a tester `Fail`) is a different workflow.
- **It did not touch `aidw/workflows/prompt.py`'s revision budget.** The prompt workflow's own
  "fix batch" is a different concept that happens to share a word.
- **It did not add any new agent id, allowlist entry, `REQUIRED_PROMPTS`/`REQUIRED_SCRIPTS`
  entry or prompt file**, and no new stage, config key or gate. The fixer prompt and its agent
  guidance were edited in place, so the inventory surface is unchanged.
- **It did not add auto-close or auto-reopen for a failed batch.** Children stranded `OPEN` with
  `Status: in progress` are the intended fail-closed state, recovered through the existing resume
  path.
- **It did not commit, push or open a pull request.** Delivery belongs to the later `/pr` stage;
  the build results record that no PR exists yet for this branch.

## Verification

The build results record nine top-level rows, all against tree `1a12b4b64fd4`, and every row that
could be run passed.

`uv sync --frozen` passed, as did `uv build --out-dir <mktemp-dir>`, which produced
`aidt-1.5.0.tar.gz` and `aidt-1.5.0-py3-none-any.whl`. `uv run --frozen pytest` passed with
`2505 passed in 46.90s`, and `uv run --frozen aidw doctor` passed with 23 checks, 0 failed and 2
warnings. Both of those came from `aidw gate` reuse rather than a fresh run: the change set
matched the tree an earlier `test` stage had already gated, so the stage requested them and the
recorded same-tree outcomes were cited without re-running — the build results name each row's
origin (gate key, tree, stage and timestamp) and record the reuse as a deviation. `uv run --frozen
aidw agents validate --strict` passed with 11 agent configs and no errors or warnings,
`uv run --frozen aidw prompts check` passed with 0 errors and 0 warnings, and `git diff --check`
reported no whitespace errors.

The task-specific table is green too: batch-select purity and JSON shape
(`prompts/scripts/review-followup/tests/test_logic.py`), the batch loop / per-issue close /
fail-closed batch / CLI flag / F1 width / dry-run tests (`tests/test_fix_workflow.py`), the design
§8.4 and §17 drift tests, the F1 variable re-baselines, the fixer prompt neutrality and F1 arity
tests, and the fixer agent-guidance guard all passed within that full-suite run. The dry-run
malformed-select rejection is called out on its own row as passing, because the preview now
shares the loop's fail-closed batch reader.

Three rows are recorded as **unverified**, each with its stated reason. The lint row is unverified
because this repository configures no linter, formatter or type-checker — `AGENTS.md` names
`pytest` as the only verification, so there is no lint command to run and none was invented. The
"changed-file subsets" row is unverified because the single `-q` full-suite run does not report
per-file counts, and the suite was not re-run since the same-tree gate was reused. The
`aidw fix --pr <n> --dry-run --fix-batch 3` row against a live PR is unverified because no PR,
GitHub credentials or live approved children were used in the recording stage; the dry-run
contract is covered by the automated tests only.
