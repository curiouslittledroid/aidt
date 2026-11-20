# Summary — G1.1: Classify prompt-review findings as `spec-gap` vs `prompt-gap`

## 1. The problem it was solving

The prompt reviewer (`P2` in the `aidw prompt` workflow) produced findings that were
frequently not prompt defects at all. Many of them were defects in the *source of truth* the
prompt is derived from — the cited `design.md` section or the roadmap entry — which no edit to
the prompt could actually close. The workflow could not tell the difference, so it did what it
does with every finding: it partitioned by priority and handed the blocking ones to the
task-fixer. The fixer then rewrote the prompt to accommodate a gap that lived upstream,
producing prose that read as if the problem were solved, and the re-review approved it because
the prompt now matched the (wrong) finding rather than the spec.

Two related holes made that worse. A review whose findings could not be classified had no
distinct failure mode of its own: it fell into the existing whole-review `unparseable`
fallback, which is a *fixer* path — the loop paid for a fix stage on material it could not
trust. And on later rounds the reviewer could "re-read" a previously flagged section by grepping
or diffing it, which is enough to confirm a line changed and not enough to confirm the defect is
gone, so approvals could be issued on a check that never actually re-read the cited material.

The task is the first half of Epic G1 ("Prompt review depth"). It depends on the existing §8.1
`blocked:` mechanism used at the authoring layer and mirrors it at the review layer; it precedes
G1.2, which turns the remaining expensive blocked-authoring case into a cheap Python preflight.

## 2. The core idea

Findings gain a classification, and the *classification*, not the priority, decides whether the
review loop is even allowed to continue. A `spec-gap` — a defect only the cited spec or roadmap
can close — ends the run `blocked` before any fix stage, reconcile or approve path, because a
fixer cannot repair a defect that lives outside the prompt. A `prompt-gap` — something editing
the prompt can fix — goes through the existing priority-keyed fix loop completely unchanged.

The decision that made the rest follow is *where* the classification is enforced. `Kind:` is
parsed in `aidw/findings.py`, which is shared with the §8.3 code-review workflow and with the
delta-brief shrink, but it is enforced only in `aidw/workflows/prompt.py`. Making it required at
parse level was the obvious alternative and was rejected: it would fail every code-review
finding closed (code-review findings have no `Kind:`), and adding the field to `STRING_FIELDS`
and `to_manifest_entry` would change the published findings manifest that §8.3 defines. So the
parser learns the token and stays permissive; the prompt review is the only place that requires
it.

Two smaller choices follow from the same instinct that a stop must not be quietly resumed into
the behaviour it was meant to prevent: the gate `mechanism` values are `spec-gap` and
`unclassified`, never `review-loop`, so the existing `--resume` rule (which keys the fix-cycle
continuation on `mechanism == "review-loop"`) refuses them with a recorded reason instead of
offering a fix cycle. And the unclassified stop is evaluated before the spec-gap stop, and both
before every verdict branch, so a review whose classification cannot be trusted is never acted
on even in part.

## 3. What was built, piece by piece

**The contract in the prompt.** `prompts/task-review.md` now requires a bare `Kind:` line on
every finding, alongside `Priority:` and `Confidence:`, with exactly two values and a one-line
definition of each. The existing "keep the labels plain" instruction was extended to cover it,
so the label survives the same parsing rules as its neighbours. The same file also closes the
approval loophole: on any round after the first, the reviewer must re-read the cited material in
full — the task prompt, the cited spec section, the flagged repository file — before resolving a
previous finding, and a grep- or diff-only re-read of the previously flagged section is never
sufficient to approve. `agents/task-reviewer/AGENTS.md` mirrors the `Kind:` requirement so the
agent's own context file states that a finding without a valid `Kind:` is not a complete review;
its read-only boundary is unchanged.

**The parser.** `aidw/findings.py` gains `SPEC_GAP`/`PROMPT_GAP`, a `KIND_MAP` beside the
existing `PRIORITY_MAP`, a `normalise_kind` helper on the same `_clean_scalar` path (so a space
or a hyphen, and a bolded label, all parse as they do for priority), and an optional
`ParsedFinding.kind`. Optionality is the point: a code-review finding with no `Kind:` parses
clean with `kind == ""` and no `problems`. `kind` deliberately stays out of `STRING_FIELDS` and
out of `to_manifest_entry`, and `_finding_text_block` re-emits `Kind:` when present. That last
piece matters because `_finding_text_block` is the single re-emitter used both by the fixer
stages and by `stage_registry.render_delta_brief`'s structured shrink; without it a shrunk
previous review would silently lose the classification, exactly the trap the Z8 decision closed
for `Verdict on this finding:`.

**The enforcement.** `aidw/workflows/prompt.py` gains `classification_stop`, applied after
`partition_findings` and before the M2 / `Blocked` / terminal branches and the whole-review
`unparseable` fallback. A missing, empty or unrecognised `Kind:` stops with mechanism
`unclassified`; a `spec-gap` stops with mechanism `spec-gap`. Both record the
`approve-task-prompt` gate as `denied`, surface the offending findings on stderr, end the run
`blocked` (exit 3) with the prompt left uncommitted, and plan no fix or reconcile stage. The
classification checks are guarded by the same `not replay_only` condition the verdict branches
use, so resuming a pre-change run whose recorded review has no `Kind:` does not block on it. The
existing `problems`-driven `unparseable` fallback is untouched and stays reserved for field-level
problems such as an unknown priority or an out-of-range confidence.

**Traceability and re-baselining.** `design.md` §8.1 gains the `Kind:` contract, the
spec-gap short-circuit and the unclassified fail-closed rule, and §17 gains a row recording the
prompt-fixed decisions. That row is numbered `Z18`, not the roadmap's stale "Z13": Z13 is
05-S1.2's roadmap-ownership row and `aidw/conventions.md` forbids reusing an id, so the next free
id was appended and `tests/test_design_doc.py` matches the row by task id, never by number.
`docs/workflow-stages.md` documents `Kind:` on `P2`, the two new gate mechanisms and the
`approve-task-prompt` denials. Editing `prompts/task-review.md` turned out to be a
byte-frozen bucket (i) file, so it was re-classified to class (v) in
`docs/migration/prompt-classification.md` — the same treatment C1.3 gave `code-review.md` — with
`tests/test_prompt_classification.py` re-baselined to match. The existing prompt-workflow review
fixtures were re-baselined with `Kind:` lines, with the blocked-dependency fixture kept as a
`prompt-gap` so the existing `Blocked`-verdict tests still exercise that branch.

## 4. What it deliberately did not do

**G1.2 was not started.** "Check task feasibility before the authoring stage" is a separate
Python preflight belonging to its own task.

**`prompts/task-review-fixes.md` and `agents/task-fixer/AGENTS.md` were not touched.** Spec gaps
never reach the fixer, and prompt gaps flow through the existing fix loop unchanged, so the fixer
stage needed no new instructions.

**The code-review manifest shape and the `review`/`fix` workflows were not changed.** `Kind:` is
prompt-review-only; the published §8.3 manifest is a contract, and the parser was kept
deliberately permissive rather than having the field threaded through it.

**No new prompt or agent id, checker, status vocabulary, schema or CI change.** The new
`mechanism` values are gate-detail strings, not new `state.py` statuses, so nothing about the
schema moved. Correspondingly, `task-reviewer` remains in `READ_ONLY_AGENTS`.

**The roadmap entry itself was left untouched**, including its stale "recorded as Z13" note; the
implementation resolved the conflict by appending the next free id instead of editing the
roadmap.

**No pull request, commit or push.** Delivery belongs to the `/pr` stage.

## 5. Verification

The recorded gates all pass. `uv sync --frozen` installed cleanly (`Checked 19 packages in
0.86ms`, exit 0). The full `uv run --frozen pytest` suite passed with `2446 passed in 49.50s`;
that result is cited from the `aidw gate` run `suite` on tree `8615ea492bae` at stage
`update-traceability`, and was re-asked and reused rather than re-run. `uv run --frozen aidw
doctor` passed with `23 checks: 0 failed, 2 warning(s)`, the warnings being a dirty working tree
and a missing `.mcp.json`. `uv run --frozen aidw prompts check` reported `resolved repo prompts:
0 error(s), 0 warning(s)` and `uv run --frozen aidw agents validate --strict` reported `11 agent
config(s): 0 error(s), 0 warning(s)`. `git diff --check` exited 0 with no output.

Two rows in the build results are recorded as **unverified**, with their reasons, and remain so
here: **Lint** has no command, because no linter is configured in this repo and `design.md` §15
says pytest is the only verification; **Build** likewise has no named gate, since `AGENTS.md`
lists none, though wheel/sdist construction is exercised inside the suite by
`tests/test_packaging.py`. Neither is a failure, and neither was substituted with a guess.

Beyond the top-level gates, the task-specific checks are recorded as covered by the single full
suite run and were not re-run as a subset to obtain a separate count: the `spec-gap` stop (exit
3, gate denied with mechanism `spec-gap`, finding on stderr, no fix/reconcile stage, prompt
uncommitted), the unclassified stop and its precedence over the spec-gap stop, the `prompt-gap`
flow through the existing priority-keyed fix/reconcile loop, the `Kind:` round-trip in
`_finding_text_block` together with the absence of a `kind` key in `to_manifest_entry`, and the
delta-brief shrink preserving `Kind:`. The doc drift check across `tests/test_design_doc.py`,
`tests/test_workflow_stages_doc.py` and `tests/test_target_repo_config_doc.py` passed with 17
tests, cited from the `aidw gate` run `traceability` on the same tree. The reviewer's read-only
boundary and its mirrored `Kind:` context were confirmed by `aidw agents validate --strict`
(0 errors) plus `tests/test_prompt_workflow.py`. All gates were run with the workflow's declared
scope (`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks
--ignore docs/task-prompts`); no source, test, config or lockfile was excluded.
