# Summary — S1.2: Gate `update-architecture` (I4) on the path condition

**Branch:** `05-S1.2`
**Build results:** `docs/implementation-results/05-S1.2/build-results.md`

## 1. The problem it was solving

S1.1 gave the pipeline a way to skip a stage whose inputs a change set never touched: the
`WHEN_PATHS_CHANGED = "paths-changed"` token, a repo-declarable `when_paths` list, and the
`paths_changed_reason`/`withhold_stage` dispatch that evaluates them. It applied that machinery
to `I3` only. `I4 update-architecture` remained ungated, so every `implement` run paid for the
architecture agent regardless of what the change set actually contained — an architecture refresh
on a run that touched no architecture input was pure cost with nothing to show for it.

The task closes that gap for the one remaining repo-optional stage. Two subtleties made it more
than a one-line change. First, the matcher is prefix-based, so the roadmap's informal
`docs/architecture/**` would match nothing and the stage would silently never run; the trigger
had to be the bare prefix `docs/architecture`. Second, the pipeline distinguishes "the repo said
nothing about triggers" from "the repo explicitly declared an empty set", and that distinction
had to survive all the way onto the planned stage, because it is what makes an always-runs
configuration detectable at all.

## 2. The core idea

The central decision was to **reuse** S1.1's token and evaluation path rather than build a
second mechanism. `I4` gets `when=WHEN_PATHS_CHANGED` and a registry default trigger set of
`("docs/architecture",)` — the literal D17 `architecture_dir` default, kept as a prefix so the
existing matcher handles it, and deliberately product-neutral because it is the toolkit's own
default and not any one repository's diagram directory. Because `I4` already sits in the default
`parallel_groups` pair with `test`, the existing dispatch in both the serial `execute()` path and
the `--parallel` member filter withholds it with no new matcher and no new evaluation code.

The one genuinely contested decision was replace-versus-merge for a repo-declared `when_paths`,
and the build results record that replace was taken. Merge would have been self-defeating: under
merge an absent key and an explicit `[]` would both resolve to the default, so the effective
trigger set could never be empty, which would make the new `aidw doctor` warning unreachable.
Replace keeps S1.1's override semantics unchanged and leaves `when_paths: []` as the single
reachable way to say "run this unconditionally".

## 3. What was built, piece by piece

The foundation is a new optional `when_paths` field on `StageDefinition`, threaded through
`PlannedStage` exactly as `when` already rides, so the trigger set travels from the registry to
the plan to the evaluation with no second mechanism. `I4`'s definition in
`aidw/stage_registry.py` attaches the carried token and the `("docs/architecture",)` default;
`_expand_static` is untouched, so planning and `--dry-run` still place `I4` in position and
evaluate nothing.

The subtle piece is in `aidw/runner.py`. The existing `_declared_when_paths` collapsed "absent"
and "explicitly empty" into the same `()`, which would have made the default apply to an explicit
`[]` and quietly destroyed the very state the doctor check needs to see. The change adds
`_declared_when_paths_or_none`, which returns `None` for an absent key — letting the registry
default apply — and `()` for an explicit empty list, and that distinction lands on
`StageSpec.when_paths` because the workflow evaluates that single value.

Evaluation needed no new code at all: `I4` now carries the token, so the existing
`paths_changed_reason`/`withhold_stage` dispatch handles it on both paths. A withheld stage
records through `record_skipped`, so it appears as `skipped` with a reason and without an
`error`, a `state.status` or a `state.resume` write — a cost-control skip, not a gate verdict.
A `None` change set, meaning the base commit could not be resolved, runs `I4` rather than skipping
on "cannot prove".

On top of that sits the operator-facing safety net: `aidw doctor` gained
`_check_architecture_trigger`, which warns only when `I4` is enabled *and* its effective trigger
set is empty. That combination is the one case where the stage will run unconditionally and
nobody asked for it; an absent key keeps the default, a non-empty declaration is the operator's
own deliberate set, and a disabled stage has no write target to justify a warning, so none of
those warn.

The remaining work keeps the documentation honest about all of it. `design.md` §8.2 and §12.2
describe the gate, the default, the override rule and the warning, and §17 records the decisions
as row `Z12`. `docs/target-repo-config.md` documents the replace rule, warns a repo with a custom
`architecture_dir` that the default is the literal toolkit default rather than its resolved
`paths.architecture_dir` — so such a repo must declare its own trigger or `I4` will skip forever
without a warning — and tells a repo naming diagram inputs to re-list `docs/architecture` if it
still wants the output directory watched. `docs/workflow-stages.md` changes `I4`'s `when=` cell
from `—` to `paths-changed` and gains the default and doctor prose.

The tests close the loop by pinning each of those surfaces: the registry token and default, the
planning default/replace/empty triple, the serial end-to-end skip and run cases, the parallel
withhold path, the doctor's four-case warning matrix, the new §17 row, and the three documentation
drift checks. The roadmap entry for S1.2 is updated alongside them.

## 4. What it deliberately did not do

`I3` is untouched. S1.1 already gated it, and its empty-means-unconditional semantics were a
settled decision, not something to revisit while gating a neighbouring stage.

No generalisation of the matching was added: no glob support, no new configuration key, no new
top-level `paths.*` entry, and no separate "diagram-input" field. Repo-declared diagram inputs
reuse the existing `when_paths` list, which is precisely why the replace semantics and the re-list
guidance in the operator docs matter — the field carries both kinds of trigger, and declaring one
set means declaring all of it.

The gate is path membership, not evidence, so `I4` was not tied to `WHEN_EVIDENCE_GREEN`. Doing
so would have changed what the stage depends on, which is a different decision with a different
cost profile.

The rest of Phase 05 was not started: the context and gate-command economy work (C1.1–C1.3) and
the prompt-review-depth work (G1.1/G1.2) are separate epics that depend on this gating pattern
but were explicitly out of scope here. Finally, this stage opened no pull request — delivery
belongs to `/pr`, and the build results record the pull-request line as not-yet-opened.

## 5. Verification

The build results record a clean pass across every gate this repository configures, all run
through `aidw gate run` against the recorded tree with the workflow's declared scope excluding
`docs/implementation-results`, `docs/architecture`, `docs/tasks` and `docs/task-prompts`.

Install (`uv sync --frozen`) passed. The build gate produced `aidt-1.5.0.tar.gz` and
`aidt-1.5.0-py3-none-any.whl`. The full suite passed with `2265 passed in 58.25s`, and the
focused selection of the seven S1.2 test files passed with `428 passed in 54.07s`; both were
reused from this run's recorded gates between the `test` and record stages rather than re-run,
and the build results name each gate's origin and timestamp. `aidw doctor` reported 22 checks with
0 failed and 2 warnings — a dirty working tree and a missing `.mcp.json`, both expected while the
work is uncommitted. `aidw agents validate --strict` passed over 11 agent configs with no errors
or warnings, `aidw prompts check` passed with no errors or warnings, `uv run aidw tasks --validate`
exited 0, and `git diff --check` reported no whitespace problems.

Every task-specific gate row is recorded as passing, each covered by the full or focused run:
the registry pins, the planning pins for the default/replace/empty triple, the serial end-to-end
cases for an unrelated change set (skipped with a reason, run still succeeds), an architecture
change, a declared diagram input, explicit `[]` and a `None` change set, the parallel member
filter that withholds `I4` before dispatch, the doctor warning matrix, and the design-document,
workflow-stages and target-repo-config documentation pins.

One row could not be verified: **Lint is recorded as `unverified`** because this repository
configures no linter, formatter or type-checker, and `AGENTS.md` states that `pytest` is the only
verification. No command was invented to fill that row. Every outcome above is cited from the
build results as recorded; nothing was re-run to produce this summary.
