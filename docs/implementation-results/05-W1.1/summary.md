# Implementation Summary — 05-W1.1: `update-traceability` must not edit the roadmap

## 1. The problem it was solving

Before this change, the `I3 update-traceability` stage could edit the roadmap, even though the
roadmap belongs to `I7 update-roadmap`. That matters because `I7`'s postcondition,
`roadmap.verify_checkbox_flip`, compares the whole line list against a snapshot taken at run
start and permits exactly one `- [ ]` → `- [x]` substitution and nothing else. If `I3` had
already rewritten the roadmap, `I7` could no longer satisfy that byte-exact tick condition in
the same run. The build results identify this as the first of the epic's silent write-ownership
gaps and tie it to the PR #282 hole captured by decision Z13. The failure mode had also been
observed live in an `implement` run, where a repo whose only candidate traceability artefact
was the roadmap had no clear instruction to leave it alone. A second gap compounded the first:
the repo-conventions channel reached only four prompts, so even a repo that declared its
traceability artefacts in `aidw/conventions.md` could not deliver that declaration to `I3`.

## 2. The core idea

The central decision was to fix this by **ownership in the `I3` prompt**, not by weakening or
loosening `I7`'s check. `I3` is told never to edit anything under `paths.roadmap_dir`, and when
the roadmap is its only candidate artefact it reports "None for traceability" as a valid
outcome rather than adopting the roadmap. The build results record why the alternatives were
rejected: capturing `tick_before` later or allow-listing sub-lines would re-open the PR #282
hole, and a mechanical Python postcondition over `paths.roadmap_dir` was left as the stronger,
separate alternative Z13 records. Alongside the ownership rule, the same decision extends
`CONVENTIONS_PROMPTS` from four to five prompts so a target repo's conventions can actually
reach `I3`.

## 3. What was built, piece by piece

The rule itself lives in `prompts/update-traceability.md`. It gains the hard rule that `I3`
never edits anything under `paths.roadmap_dir`, because `/update-roadmap` owns that tree
byte-exclusively; it adds that path to the stage's "Do not touch" list and non-goals, and it
extends the existing step that decides which traceability artefacts to update. The wording
deliberately names the config key `roadmap_dir` and the stage `/update-roadmap`, never the
product literal `docs/tasks`, so the prompt stays neutral under different target configs. The
prompt keeps taking the branch as `$1` and its default wording is undisturbed.

For the declaration to arrive at `I3` at all, `aidw/prompts.py` adds `update-traceability.md`
as the fifth member of `CONVENTIONS_PROMPTS`, and the prose that described the set as "four"
prompts in that module, in `aidw/runner.py`'s injection call site, and in
`aidw/workflows/prompt.py`'s gate-block docstring is updated to five. Keying remains the
resolved prompt **basename**, not the stage id, so a repo-shadowed
`aidw/prompts/update-traceability.md` is injected under its own basename without a special case
for stage `I3` or for the toolkit default. This is the channel decision Z13 names: it extends
the original four-prompt conventions channel so the target repo's declared artefacts, including
"none", reach `I3`.

This repository's own `aidw/conventions.md` now states that the roadmap is never a
traceability artefact and that "None for traceability" covers a repo whose only candidate is
the roadmap. The documentation was brought into line with the behaviour: `design.md` §8.2 gains
the `I3` roadmap-ownership sentence, §12.1 describes a repo declaring its traceability
artefacts (including "none") in `aidw/conventions.md`, §17's Z13 row records W1.1 as having
landed the rule instead of "pending", and §18's channel risk is marked resolved. The live config
contract in `docs/target-repo-config.md` now names `update-traceability` among the injected
prompts and explains where a repo declares its artefacts.

Three test modules pin the contract. `tests/test_conventions_injection.py` moves its
`FOUR_PROMPTS` set to five including `update-traceability.md`, updates the "four" prose and
test names, extends the exact-set assertion so dropping `update-traceability.md` fails, and
adds a basename-versus-stage-id test using a repo-shadowed copy.
`tests/test_implement_workflow.py` adds an implement-level proof that a target's
`aidw/conventions.md` reaches the rendered `I3` prompt through the real `run_stage` path (no
fake, no Pi) and that the rendered prompt carries the ownership rule and still expands `$1`.
`tests/test_prompt_neutrality.py` re-baselines `RETAINED_KEYS["update-traceability.md"]` with
`roadmap_dir`, reversing the now-stale H3.1 comment, and adds a test pinning the ownership
sentence while asserting the `docs/tasks` literal is absent. These tests fit the pieces above
together: the prompt states the rule, the channel delivers the repo's declaration, the design
and config docs record it, and the tests make each link fail loudly if broken.

## 4. What it deliberately did not do

The task stopped short of a **mechanical `I3` postcondition** — Python verifying that the bytes
under `paths.roadmap_dir` are unchanged after `I3` runs. The build results record this as an
explicit non-goal: Z13 leaves it as the stronger alternative, and adopting it would require a
separate §17 decision plus changes in `aidw/workflows/implement.py` and `aidw/roadmap.py` and
their tests. It also made **no change to `I7`'s postcondition**: `tick_before`'s capture point,
`verify_checkbox_flip`, and `I7`'s still-`skipped`-never-`failed` behaviour on a red gate are
unchanged, because weakening them is the PR #282 hole. **W1.2**, the next task in the epic
(`--dry-run` must not create a run or become a `--resume` target), was not started; run-store
creation and resume lookup were untouched. No new checker, status vocabulary, or CI gate was
added, `aidw/inventory.py` is unchanged and `update-traceability.md` remains an existing
`REQUIRED_PROMPTS` entry. Finally, no commit, push, or pull request was made by the record
stage; delivery belongs to `/pr`.

## 5. Verification

Verification is recorded from this run's gate results, not re-run for the summary. Installation
with `uv sync --frozen` passed. `uv build --out-dir <mktemp dir>` passed, producing
`aidt-1.5.0.tar.gz` and `aidt-1.5.0-py3-none-any.whl`. The full suite,
`uv run --frozen pytest`, passed with `2276 passed in 49.29s` (gate `suite`, tree
`40a68cafaf83`, stage `update-traceability`). `uv run --frozen aidw doctor` passed with
`22 checks: 0 failed, 2 warning(s)`, where the warnings are the expected dirty working tree and
missing `.mcp.json`. `uv run --frozen aidw agents validate --strict` passed with
`11 agent config(s): 0 error(s), 0 warning(s)`, and `uv run --frozen aidw prompts check` passed
with `resolved repo prompts: 0 error(s), 0 warning(s)`. The traceability drift checks,
`uv run --frozen pytest tests/test_design_doc.py tests/test_workflow_stages_doc.py
tests/test_target_repo_config_doc.py`, passed with `82 passed in 0.80s` (gate `traceability`,
same tree), and `git diff --check` passed with exit 0 and no output.

The task-specific gates also passed as recorded: the exact five-prompt conventions set, the
basename-not-stage-id injection test, the neutrality test naming `roadmap_dir` without the
`docs/tasks` literal, the implement-level render of a target conventions declaration into the
`I3` prompt, prompt resolvability through `aidw prompts check`, the design-doc pins for §8.2,
§12.1, Z13 and §18, and the workflow-stages/target-config doc drift checks. Two rows remain
**unverified**. The mechanical `I3` postcondition (Python verifying `paths.roadmap_dir` bytes
after `I3` runs) is unverified because it was not implemented and is the task prompt's explicit
non-goal. A live end-to-end `implement` run against a real Pi model is unverified because it was
not run: the repository forbids a test invoking a real Pi model, and the render path is proven
by `--dry-run`, whose human-run procedure appears in `integration-test-guide.md`. There is no
lint row because the repository configures no linter and states that `pytest` is the only
verification. The build results also note that the suite and traceability outcomes were reused
from this run's recorded gates rather than bought twice, that the earlier `smoke` gate
(`229 passed`) predates the traceability doc edits and so is not cited for the current tree,
and that no pull request number is recorded yet because `/pr` will supply it.
