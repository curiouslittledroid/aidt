# Summary — S1.2: Gate `update-architecture` (I4) on the path condition

**Branch:** `05-S1.2`
**Build results:** `docs/implementation-results/05-S1.2/build-results.md`

## 1. The problem it was solving

S1.1 introduced `WHEN_PATHS_CHANGED` and used it to gate `I3` on repo-declared `when_paths`, so
an `implement` run could skip work whose inputs the change set never touched. That left the
other repo-optional stage, `I4 update-architecture`, ungated: it carried `when=""` and would run
architecture work on every implement run regardless of what changed. The task exists to extend
the S1.1 contract to I4 — attach the same token, give the stage a sensible registry default of
`docs/architecture`, keep the distinction between "the repo said nothing" and "the repo
explicitly declared an empty set", and surface the resulting always-runs configuration through
`aidw doctor`.

The problem this summary must record, however, is what the build results observed: in the
recorded tree the implementation is **absent**. Relative to `main` the branch contains the task
prompt and seven modified test files only; `aidw/stage_registry.py`, `aidw/runner.py`,
`aidw/doctor.py`, `docs/target-repo-config.md`, `docs/workflow-stages.md` and `design.md` are
unchanged. I4 still carries `when=""`, `_declared_when_paths` still collapses absent and
explicit-empty to `()`, the doctor warning does not exist, and the documentation does not
mention I4's path gate or default. The new S1.2 pins are therefore red.

## 2. The core idea

The intended central decision, as the task prompt fixes it, is to **reuse** S1.1's
`WHEN_PATHS_CHANGED = "paths-changed"` rather than invent a second token. The matcher, the
carry path through `PlannedStage` into `StageSpec.when_paths`, and the skip/withhold machinery
already exist; I4 only needs the token, a registry default, and the absent-versus-explicit-empty
distinction preserved onto the spec. The default is the literal prefix `("docs/architecture",)`
— the toolkit's own D17 `architecture_dir` default — not the roadmap's informal
`docs/architecture/**`, because the matcher is prefix-based and a glob would never match. The
prompt records replace semantics (a repo-declared list replaces the default) as the proposed
reading, pending the task owner's confirmation, with merge as the competing option.

None of that decision is realised in the recorded tree: the build results state plainly that the
key decisions are "required by the task prompt, not present in the recorded tree", and that the
document records the observed state without fixing it.

## 3. What was built, piece by piece

What the branch actually carries is the test contract for the change, not the change.

The task prompt itself was committed, pinning the requirements, the traps and the non-goals.
Alongside it, seven test files were modified to encode the expected behaviour. At the registry
level they pin that I4 carries `paths-changed`, that the carried-`when` map reflects it, and
that the registry default is `("docs/architecture",)`. At the planning level they pin that an
undeclared `when_paths` picks up the default, a declared non-empty list replaces it, and an
explicit `[]` stays empty — the distinction that makes the doctor warning possible at all. The
implement-workflow tests add fake-stage cases for skipping an unrelated change, running on an
architecture change, and withholding I4 on the `--parallel` member dispatch path, which matters
because I4 sits in the default `parallel_groups` pair. The doctor test adds the enabled/empty
warning matrix. Three documentation pins require the design, workflow-stages and target-repo
config documents to describe the gate.

The corresponding production pieces — the `when` and `when_paths` fields on I4's
`StageDefinition`, the `None`-versus-`[]` carry in `aidw/runner.py`, the conditional warning in
`aidw/doctor.py`, and the three documentation edits — were not delivered. The tests and the
implementation therefore do not meet, which is exactly what the verification section records.

## 4. What it deliberately did not do

The task's explicit non-goals, each recorded in the build results as not implemented:

It does not change S1.1's I3 gating or I3's empty-means-unconditional semantics; I4 is the only
stage in scope. It does not add glob matching, a new config key, a top-level `paths.*` key, or a
separate "diagram-input" field — diagram inputs reuse the existing `when_paths` field. It does
not gate I4 on `WHEN_EVIDENCE_GREEN`, because the condition is path membership, not evidence. It
does not start the context/gate-command-economy work (C1.1–C1.3) or the prompt-review-depth work
(G1.1/G1.2). It does not open a pull request, which the delivery stage owns; the build results
record that no PR existed at recording time.

Separately from these declared non-goals, the build results record a deviation rather than a
deliberate omission: the implementation deliverables are simply absent from the change set, and
the failing suite is recorded rather than repaired at the record stage.

## 5. Verification

The build results record one full verification pass over the recorded tree. The install gate
(`uv sync --frozen`) exited 0. The build gate, run through `aidw gate run build` into a
temporary output directory, passed and produced `aidt-1.5.0-py3-none-any.whl` and
`aidt-1.5.0.tar.gz`. `aidw doctor` exited 0 with 21 checks, 0 failed and 2 warnings (dirty
working tree, missing `.mcp.json`). `aidw agents validate --strict` exited 0 over 11 agent
configs with no errors or warnings, and `aidw prompts check` exited 0 over 17 resolved repo
prompts with no errors or warnings. `git diff --check` found no whitespace errors.

The test gate failed. `uv run --frozen pytest`, run through `aidw gate run suite`, reported
`10 failed, 2255 passed in 47.74s`; all ten failures are the new S1.2 pins, spanning the design
document pin, the doctor enabled/explicit-empty case, the planning pins for I3 and I4, the two
implement-workflow skip/withhold cases, the registry token and default pins, and the
target-repo-config and workflow-stages documentation pins. The representative recorded assertion
is `assert i4.when == registry.WHEN_PATHS_CHANGED`, failing with `assert '' == 'paths-changed'`.
Every task-specific gate row in the build results is consequently marked failed.

Lint is recorded as **unverified**, for the reason the build results give: this repository
configures no linter or formatter, and `AGENTS.md` states that pytest is the only verification.
No verification command was re-run to produce this summary; all outcomes above are cited from
the build results as recorded.
