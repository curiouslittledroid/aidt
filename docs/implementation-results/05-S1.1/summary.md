# Implementation Summary — 05-S1.1: Gate `update-traceability` on a path-scoped stage condition

**Branch:** `05-S1.1`
**Source of record:** `docs/implementation-results/05-S1.1/build-results.md`
**Task prompt:** `docs/task-prompts/05-S1.1-prompt.md`

## The problem it was solving

Every `implement` run paid for `I3 update-traceability`, whether or not the change set had
anything to trace. The task's stated purpose is a cost-control one: an `implement` run whose
diff touches none of the paths that traceability cares about still invoked the `I3` agent, and
there was no way for a target repo to say "traceability only matters when these files move".
The build results put it in the same terms — the condition exists so such a run "skips
traceability instead of paying for an agent invocation".

The work also had to solve a shape problem before it could solve the cost problem. The stage
vocabulary already had conditions, including a carried `WHEN_EVIDENCE_GREEN` precedent from
H3.2 (`Z1`), but none of them was scoped by *which files changed*. Adding that meant deciding
where the path set lives — the toolkit, a global `paths.*` key, or each stage's own declaration
— without reintroducing product-specific paths into a toolkit that must stay repo-neutral.

## The core idea

The central decision was to make the condition **carried rather than resolved by the planner**.
`WHEN_PATHS_CHANGED = "paths-changed"` joins the `when=` vocabulary like
`WHEN_EVIDENCE_GREEN`, so `_expand_static` never expands it away: `plan_stages`, `build_plan`
and `--dry-run` still plan `I3` in position, and the workflow itself decides just before
`run_stage` whether to run or skip. The expander has no change set, so moving the decision
earlier was never an option; carrying it keeps the plan truthful and puts the evaluation where
the evidence exists.

The second half of the idea is that the path set is **declared, not hardcoded**. `I3`'s
registry entry carries the token but no default paths, because a toolkit default containing the
Mythical Forge rules-engine / `docs/rules-coverage` / vector-matrix paths would be a product
literal in the toolkit (design §7.1, §17 `S1`). Instead each stage may carry an optional
`when_paths` list of repo-relative prefixes in the target repo's config, and an absent or empty
list means "unconditional" — today's behaviour. The competing option, a registry-default path
set drawn from the roadmap's example, was explicitly rejected for that neutrality reason; the
task prompt records the empty default as prompt-fixed.

## What was built, piece by piece

The vocabulary and the stage wiring came first. `aidw/stage_registry.py` gains
`WHEN_PATHS_CHANGED` and attaches it to the `I3 update-traceability` entry with no path set. That
one edit is what makes the condition declarable and gives the rest of the work something to
carry.

Carrying it required the runner to know about paths without changing any existing contract.
`aidw/runner.py` adds an additive `StageSpec.when_paths` field defaulting to `()`, populated in
`_spec_from_planned` through a type-guarded `_declared_when_paths` reader. A registry stage with
no declared entry keeps the empty default, so nothing that does not opt in changes behaviour.

The declaration itself lives in the target config, not the toolkit. `aidw/target_config.py`
adds `when_paths` to `STAGE_KEYS`, `StageConfig`, the parser and `to_dict`, and validates it
fail-closed in the same spirit as `_parse_parallel_groups`: a non-list value is a single `ERROR`
naming the field and the field is dropped; each bad entry (non-string, absolute, `.`, `..`,
empty) is a single `ERROR` naming the dotted entry path, that entry is dropped, and parsing
continues with the surviving valid entries. Valid entries are normalised, sorted and deduped by
reusing `verification.normalise_ignore`, so the config layer and the matcher agree on what a
path prefix means.

The behaviour lives in `aidw/workflows/implement.py`. Three pieces were added: a pure
`paths_changed_reason` matcher, a `change_set_paths` reader, and `withhold_paths_stage`, which
dispatches from both evaluation sites alongside the existing evidence condition. The matcher
follows the prompt-fixed rule `path == prefix or path.startswith(prefix + "/")`, mirroring
`verification._excluded`, so `docs/x` matches a file or a directory subtree but never the
sibling `docs/xy`. The change set is deliberately the one `I7` already measures —
`git.changed_paths` against `BASE_DEFAULT` plus untracked paths, with the run's state root
excluded — rather than `repo.base_branch`, because a different base would silently always- or
never-skip and the two conditions would stop agreeing.

The skip path is treated as success, not failure. A skipped `I3` is recorded through
`runner.record_skipped` with the reason under `SKIP_REASON_KEY` and `error` unset, and it writes
no `state.status`/`state.resume`; the build results note this is what keeps it from rendering as
a red gate in `aidw/report.py:stage_lines`. One fail-closed nuance is explicit in the design:
`changed_paths` returning `None` (an unresolvable base) **runs** the stage, because only a real
empty list is a proof of "nothing touched" — "cannot prove irrelevant" is not "skip".

Documentation and tests were treated as part of the product contract rather than follow-up
paperwork. `design.md` §8.2 gains the token/`I3` paragraph, §12.2 the stage field, and §17 row
`Z11` the prompt-fixed decisions in the `Z1`/`Z9` format. `docs/target-repo-config.md` and
`docs/schema/aidw-config.schema.json` gain the field and its schema, and
`docs/workflow-stages.md` gains the token in the Conditions table plus `I3`'s `when=` cell. The
contract tests pin all of it: the token and carried behaviour, the planned `when` and its
`when_paths` overlay, the pure matcher's cases and both dispatch paths end to end, the config
round-trip and fail-closed errors, and the document/schema pins that make an undocumented token
fail the suite.

## What it deliberately did not do

The task stopped short of S1.2, which would attach the same condition to `I4
update-architecture`, add a repo-declared architecture trigger set, and warn from `aidw doctor`
when that set is empty. That is a separate, dependent task, and the build results record it as
not implemented for that reason.

No repo's paths were hardcoded as a toolkit default, and no top-level `paths.*` key was added.
The path set stays a per-stage `when_paths`, because a global key would misplace a per-stage
concern and a toolkit default would embed the Mythical Forge example in product-neutral code.

`_expand_static`, `record_skipped`'s contract, `STAGE_IDS`/`REPO_OPTIONAL_IDS`, and every other
stage's `when=` were left unchanged; only `I3` gains the condition here. Similarly, `I3` is not
gated on `WHEN_EVIDENCE_GREEN` and the skip does not read `state.gate_outcomes`: this is
path-membership, not evidence, and conflating the two would have made the skip depend on an
unrelated signal.

Finally, this record stage produced no commit, push or pull request. The build results record
that no PR exists yet and that `/pr` will replace the not-yet-opened note once it creates one.

## Verification

The build results record the repo's own gate list from `AGENTS.md`, run through `aidw gate run`
with the workflow's declared scope, and nothing was re-run while writing this summary. Install
(`uv sync --frozen`) passed, the `build` gate passed (producing `aidt-1.5.0.tar.gz` and
`aidt-1.5.0-py3-none-any.whl`), and the `suite` gate passed with `2248 passed in 44.46s`. The
suite row is explicitly cited from the run's recorded gate rather than re-executed: the same
gate had already passed for tree `0664239b93b2` under an identical scope during the `test`
stage, and asking for it again printed the `reused: …` line and exited 0 without running.
`aidw doctor` passed with `0` failures and `2` warnings (the dirty working tree and the missing
`.mcp.json`, both expected while the work is uncommitted), `aidw agents validate --strict`
passed with 11 configs and no errors or warnings, `aidw prompts check` passed with no errors or
warnings, and `git diff --check` exited 0 with no output.

One row is honestly **unverified**: lint. The build results record that no lint command exists
to run — the repo configures no linter, formatter or type-checker, and `AGENTS.md` states that
`pytest` is the only verification — so the row is marked unverified rather than filled with an
invented command. All task-specific gates (the pure matcher, serial and `--parallel` skip/run
runs, the registry and plan pins, the config/schema pins, and the doc pins) are covered by the
single full-suite run; the build results record no separate subset invocation, and none was made
here.

Two deviations are part of the record rather than glossed over: the lint gap above, and the
absence of a pull request, since the read-only `gh pr view 05-S1.1` lookup returned nothing.
