# Summary — 05-P1.1: A commit-and-push stage for `aidw fix`

## The problem it was solving

`aidw fix` closed the work it had done without ever publishing it. `F1` closes each
review follow-up issue as `Status: fixed` during the stage, but no stage of `fix`
committed or pushed anything — the fix edits, and the `I7 update-roadmap` tick added in
H3.3, stayed in the PR-head worktree. PR #300 is the recorded example: one fix commit
unpushed, two fixes uncommitted, and all three follow-up issues closed. The run therefore
reported success while the code it claims to have fixed never reached the pull request,
which is exactly the untruthful state the epic exists to remove. Until this task the
boundary was deliberate — `design.md` §8.4 said "The edit stays uncommitted: no stage of
`fix` commits (§13)" — and the change reverses it, recording the reversal as decision
`Z9` in §17 and resolving the §18 risk row "The fix-loop prompts leave their changes
uncommitted".

## The core idea

The single decision that made the rest follow is that `F5 commit-and-push` is a **core
post-loop stage**, emitted from the same `WorkflowDefinition.post_loop` half as `I7` and
placed after it, whose trigger is **loop convergence rather than green evidence**. That
distinction is the crux: `fix`'s `WHEN_EVIDENCE_GREEN` rule stays `I7`'s completion claim
only, because a converged run whose tick was withheld, an empty run, and a run whose
roadmap target could not be resolved are all non-green — yet their fix edits are still
real and must land. Being core (not repo-optional) means the existing removal, disable and
reorder rules apply to it, so a declared `workflows.fix.stages` list simply becomes
`[A1, I7, F5]`.

The second decision is the division of labour: the `pr-publisher` agent performs the
writes — `git add -A`, `git commit`, `git push origin <branch>` — and Python only decides
whether a write should happen and then verifies that it did. A stage record alone is not
evidence, so the workflow compares `HEAD` with `origin/<branch>` before it will record a
remote SHA. The `pr-publisher` agent was reused rather than replaced, with its hard rules
carved out per prompt, because prompt text alone does not reliably override an agent
file's rules.

## What was built, piece by piece

The stage catalog came first. `aidw/stage_registry.py` gains `_COMMIT_PUSH_STAGE` — id
`F5`, runtime name `commit-and-push`, agent `pr-publisher`, prompt `fix-commit.md`,
variables `("{pr}",)`, and no `when` token — appended to `_FIX.post_loop` after
`_ROADMAP_TICK_STAGE`. `F5` joins `STAGE_IDS` while `REPO_OPTIONAL_IDS` stays `{I3, I4}`,
and the core/classification documentation was updated to match. The existing machinery
(`plan_stages`, `validate_stage_list`, `declared_stage_issues`, `_warn_deferred_settings`)
already iterated `post_loop` as a whole, so the declared-list consequences followed without
rewriting them; `aidw/runner.py` only had its canonical declared list documentation
updated to `[A1, I7, F5]`.

The behaviour lives in `aidw/workflows/fix.py`. Both post-loop stages are planned once per
run through the same `include_post_loop` expansion, never per iteration, and the
`--dry-run` block plans them identically. Once the loop converges and `I7` has succeeded or
been recorded as skipped, the workflow decides among four cases over two facts it already
owns — whether the tree is dirty, and this run's own accumulated `closed_issues` (never a
`gh` query, never a count of `Status: fixed` comments). A dirty tree with at least one
closed issue commits the accumulated change set (the fix edits plus the tick, if it
flipped), pushes to the PR-head branch, verifies, and records `head_sha`. A dirty tree with
nothing closed is a recorded skip, because unowned dirt is not this run's to publish — §13
forbids discarding unrelated user changes. A clean tree with nothing closed is the
roadmap's successful no-op: a recorded skip with no empty commit. A clean tree with closed
issues fails closed, because that is precisely the untruthful state being removed; P1.2
will make that case unrepresentable by moving the close behind the push.

The fail-closed edges are all explicit and all name the PR number and the branch: a
non-`SUCCEEDED` `F5` record, a `HEAD`/`origin/<branch>` mismatch or unresolvable ref, a
tree still dirty after the stage, and the clean-tree-with-closed-issues case. A base-branch
refusal is checked before any push, so a misresolved ref can never push `main`. A stopped
loop never reaches any of this: the single existing `stop()` helper — already the one place
that records `I7`'s skip for every stop path — was extended to record `F5`'s skip with the
same reason, so no per-`return` bookkeeping was added. A *failed* `I7` stage keeps today's
behaviour and leaves `F5` neither planned nor recorded.

`state.pr` gained exactly two shapes: `head_sha`, written only when the head comparison
holds, and `commit_skip_reason`, mirroring `roadmap_tick_skip_reason`; a skipped
`StageRecord` also carries the existing `SKIP_REASON_KEY`. No `committed`/`pushed` boolean
was added, because `head_sha`'s presence is the boolean.

The prompt is new: `prompts/fix-commit.md`, modelled on `prompts/pr.md`'s commit and push
sections but self-contained — it instructs commit and push only, names the PR-head worktree
as the branch source and `origin` as the remote, states the no-force/no-merge rule, refuses
a base-branch head, and must not commit when the caller reports that this run closed no
issue. `aidw/inventory.py` adds it to `REQUIRED_PROMPTS` so a rename fails loudly at
`prompts check` rather than at Pi invocation. To remove the contradiction at its source,
`agents/pr-publisher/AGENTS.md` now scopes its hard rules by prompt: `/pr` commits, pushes,
opens the PR and backfills the build-results line, while `/fix-commit` commits and pushes
only — no `gh pr create`, no body sections, no build-results edit.

The documents moved in the same change because they are drift-checked, not free prose:
`design.md` §8.4's diagram and its uncommitted sentence, §13's commit-ownership bullet
(naming both `I6 pr` and `F5` as owners of the documented `git add -A`), the single `Z9`
row in §17 carrying the reversal, P1.2's ordering and the prompt-fixed decisions D1–D10,
and the resolved §18 row; plus `docs/workflow-stages.md` (the `F5` row and the extended fix
diagram) and the `aidw fix` block in `README.md`. The roadmap entry was ticked, and eight
test files were re-baselined or extended to encode the new behaviour instead of the old.

## What it deliberately did not do

P1.2 — closing a follow-up issue only after its fix is pushed — is a separate task. The
`Status: fixed` close therefore stays in `F1`, and `prompts/fix-next-review-followup.md`
and `review_followup.py` are untouched. This task only adds the commit stage and records
the ordering in `Z9`; until P1.2 lands, the clean-tree-with-closed-issues case must fail
loudly rather than become representable.

No new agent id was introduced, `agent-configs/pr-publisher.yaml` was not changed, and no
allowlist entry moved — the existing `pr-publisher` is reused, and the only agent-file
change is the `AGENTS.md` content carve-out. `fix` still creates no pull request and
backfills no build-results line; those remain `I6`/`pr.md`'s job. Q1.1 (withhold the
implement PR on tester `Fail`) and B1.1 (batch fixes) touch different or later work and
were not started. Finally, this record stage itself commits nothing, pushes nothing and
opens no pull request — delivery belongs to `/pr`.

## Verification

The gates were run through this repository's own `aidw gate run <key>` with the workflow's
declared scope. All recorded gates passed: `uv sync --frozen`; a `uv build` that produced
`aidt-1.5.0.tar.gz` and `aidt-1.5.0-py3-none-any.whl`; the full `uv run --frozen pytest`
suite at 2151 passed in 44.88s; `uv run --frozen aidw doctor` with 21 checks and 0 failed
(the two warnings being the dirty working tree and the missing `.mcp.json`); `uv run
--frozen aidw agents validate --strict` with 11 configs and 0 errors or warnings; `uv run
--frozen aidw prompts check` with 0 errors and 0 warnings, with `fix-commit.md` resolving to
the toolkit default; and `git diff --check` clean. The lint row is recorded as `n/a`
because this repository configures no linter or formatter — `pytest` is the only
verification (design §15). A focused run of the six named test files plus the
prompt-classification test also passed, at 284 passed in 17.21s.

The full suite was **reused, not re-run**: the earlier `update-traceability` stage of the
same run had already passed it against the same tree (`f69cd588e533`) and the same scope,
and the `build` gate in the recording stage confirmed the tree was unchanged. The
build-results document cites that recorded outcome rather than buying the same evidence
twice.

Every task-specific gate is recorded as passing on the strength of those runs: D3's four
cases, D6's fail-closed edges, D5's base-branch refusal, D4's stopped-loop skips, registry
purity (`post_loop == (I7, F5)`, expansion ending `[..., I7, F5]`, `[A1, I7, F5]`
validating, missing/disabled/reordered `F5` erroring, `REPO_OPTIONAL_IDS` unchanged),
dry-run planning `commit-and-push [planned]` exactly once after `update-roadmap`, and the
documentation, inventory and prompt-contract drift checks.

Two caveats are recorded honestly rather than smoothed. First, the task dry-run used merged
PR #156 as a stand-in because `05-P1.1` has no pull request yet; it proves the `F5` plan
position generically but does not exercise this branch's own PR. Because the run used an
isolated temporary state directory, `aidw gate` reported the dry-run gate as passed but
noted "no run to record into", so that row cites the command observation rather than a
recorded gate origin. Second, no pull request exists yet — a read-only `gh pr view` lookup
returned none — so the build-results header records the required not-yet-opened note, which
`/pr` will replace with the real number.
