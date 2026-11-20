# Implementation Summary — C1.1: Stop appending the target `AGENTS.md` to rendered prompts

**Branch:** `05-C1.1`
**Source of record:** `docs/implementation-results/05-C1.1/build-results.md`

## 1. The problem it was solving

Every rendered prompt for a workflow stage carried the target repo's root `AGENTS.md`
twice. Pi already loads that file as project context for the target root (design §5.5), and
the prompt renderer appended it again as part of its conventions block (design §7.3, step 4 of
the render pipeline, decision D2). The recorded observation in the decision log puts a number
on the cost: 16.9 KB of a 28.5 KB rendered `impliment-task` prompt was that duplicated file.

The waste is not only tokens. A second copy of the same instructions in the prompt competes
with the copy Pi supplies through its own channel, so the prompt is larger and its authority
is less clear than it needs to be. The task exists to remove the duplicate while keeping the
half of that block Pi does *not* provide, and to leave a way back for the repos that genuinely
need it.

## 2. The core idea

The split is **injection-only**. The renderer keeps exactly one appended source —
`<target>/aidw/conventions.md` — and stops appending `AGENTS.md`, because Pi already delivers
that file. The *read* channel is left completely alone: `read_conventions_sources` and
`CONVENTIONS_SOURCES` still return both sources in D16 order, because
`aidw/workflows/prompt.py:_gate_block` extracts the `## Gates` section through that channel and
later tasks (C1.2, C1.3) build on it. Narrowing the read side as well would have been the
obvious simplification, and it is exactly the change that would silently strip the gate list
out of the evidence bundle.

The escape hatch is a frontmatter marker on the prompt file: `append_agents_md: true`. It was
chosen over a target-repo config key because the deliverable list confined code to
`aidw/prompts.py` and the config-key route was explicitly out of scope; the marker is read from
the **resolved** prompt path, so a repo shadow or an explicitly declared prompt is governed by
its own file rather than by whatever the toolkit default for that stage id happens to say.
Only a value `yaml.safe_load` parses as the boolean `True` restores the old append; everything
else — absent, `false`, a quoted `"true"`, a non-boolean scalar, a nested key, malformed YAML,
a frontmatter-less prompt, a missing or non-UTF-8 file — means dropped, with no raise. A typo
in a marker must never fail a stage, and guessing an opt-in would restore the duplication the
task removes.

## 3. What was built, piece by piece

**The narrowed injection in `aidw/prompts.py`.** This is the centre of the change.
`render_repo_conventions` now produces a conventions-only block by default and gains an
additive keyword, `include_agents_md: bool = False`, which is the single way to get the
pre-C1.1 D16 block back. `inject_repo_conventions` keeps its three-argument signature
deliberately: five test modules call it directly inside their `--dry-run` render seams, so
changing the signature would have forced a re-baseline across `test_override_integration.py`,
`test_plan_stages.py`, `test_prompt_resolution.py` and `test_implement_workflow.py` for no
gain. The marker is read by a new pure peek, `aidw.prompts.appends_target_agents_md`, together
with the `AGENTS_MD_SOURCE` and `AGENTS_MD_MARKER` constants. The peek is read-only by
contract: rendering still mutates nothing and writes nothing, and a prompt with no frontmatter
or a file that is not there simply reads as "not opted in".

**The unchanged read channel.** `read_conventions_sources` and `CONVENTIONS_SOURCES` keep both
sources, in D16 order, and keep their existing `(OSError, UnicodeDecodeError)` degradation, so
an unreadable or non-UTF-8 conventions file still contributes nothing rather than raising. The
peek adds the same two exception types plus `yaml.YAMLError`. This is why the evidence bundle's
gate list still shows `## Gates` sections gathered from both files after the change.

**The rationale in `aidw/runner.py`.** A comment-only update at the injection seam: the
appended block is now `aidw/conventions.md` only, and the comment names the marker opt-in and
design §17 `Z15`. No behaviour lives here — the rendered text is produced entirely by
`aidw/prompts.py` — but the seam is where a future reader would otherwise assume the old
two-file behaviour.

**The design record.** `design.md` §7.3 step 4 now states that the renderer appends only
`aidw/conventions.md`, that the `AGENTS.md` append is dropped because §5.5 already delivers
it, and that the marker restores it. The decision is recorded in §17 as row `Z15`. It is
**not** `Z12` as the roadmap entry says: `Z12` is S1.2's `I4` row, and `aidw/conventions.md`
forbids folding into, reusing or renumbering an existing id, so the new decision took the next
free id. The roadmap entry itself was left exactly as written, per the task prompt.

**The corrective doc line.** `docs/target-repo-config.md`'s related-documents bullet now says
`AGENTS.md` is Pi's project context and the `_gate_block` read source rather than an appended
block. This is a comment on an existing bullet, not a config-contract change.

**The two contract test modules.** `tests/test_conventions_injection.py` was re-baselined from
"`AGENTS.md` is injected" to "`conventions.md` is injected, `AGENTS.md` absent by default": its
sentinel and header assertions flipped, the marker cases were added (restore, `false`, quoted,
uppercase, nested, malformed, frontmatter-less, missing, non-UTF-8), the resolved-prompt keying
gained cases, and a third property sweep now covers the five `CONVENTIONS_PROMPTS` basenames
against the marker variants — including the E7.3 guarantees that a non-`CONVENTIONS_PROMPTS`
prompt and a repo with no sources each return `prompt_text` byte-identically.
`tests/test_design_doc.py` pins the updated §7.3 step 4 and exactly one C1.1 decision row,
matched by task id plus wording and never by a `Z` number, while asserting no §17 id is reused.

The build results also record two files touched outside the prompt's deliverables list:
`aidw/runner.py` (the comment above) and `docs/target-repo-config.md` (the corrected bullet).
Neither adds a config key, a `paths.*` entry or a schema surface, and both are recorded so a
reviewer sees the full diff relative to `main`.

## 4. What it deliberately did not do

- **No C1.2 or C1.3 work.** Resolving gate commands from the target's actual heading, diagnosing
  misses, and inlining resolved gate commands into the stage prompts are the next tasks in the
  epic. `_GATES_HEADING`/`_gates_section` and the five prompts' gate prose are untouched.
- **No change to `design.md` §5.5.** It is the rationale for dropping the append, not a
  deliverable.
- **No target-repo config key, `docs/schema/` node or `docs/target-repo-config.md` config
  field.** The config-key alternative for the lever was explicitly out of scope, and because
  the marker is prompt-fixed, no config drift check moves.
- **No roadmap edit.** The roadmap's stale "Z12" wording stays as written; the correction lives
  in the task prompt and in §17.
- **No new checker, status vocabulary, `REQUIRED_PROMPTS` entry, `when=` token or CI gate.**
- **No commit, push or pull request.** Delivery belongs to a later stage, so the build results
  name no PR number.

## 5. Verification

Every row below is what the build results already record; nothing was re-run to write this
summary.

All gates ran through `aidw gate run <key>` with the workflow's declared scope
(`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks
--ignore docs/task-prompts`). `uv sync --frozen` passed. The build gate passed, producing
`aidt-1.5.0.tar.gz` and `aidt-1.5.0-py3-none-any.whl`. The full suite passed with
`2348 passed in 48.71s` — recorded as the single full-suite invocation for this document, with
no subset re-run and no second suite bought. `uv run --frozen aidw doctor` passed with
`22 checks: 0 failed, 2 warning(s)`, the two warnings being the dirty working tree and the
missing `.mcp.json`. `uv run --frozen aidw agents validate --strict` passed with 11 agent
configs and no errors or warnings. `uv run --frozen aidw prompts check` passed for both toolkit
defaults and resolved repo prompts. `git diff --check` exited 0 with no output.

Two focused `smoke` rows are cited from the same run's `test` stage rather than re-run:
`145 passed in 8.13s` for `tests/test_conventions_injection.py tests/test_design_doc.py`, and
`3 passed, 236 deselected in 0.73s` for the three `e73_*` cases that pin `_gate_block` still
taking `## Gates` from both the root `AGENTS.md` and `aidw/conventions.md`. On that evidence,
the read channel is unchanged, the marker's absent/`false`/`true` behaviour is pinned, and the
§7.3 step 4 and single-`Z15`-row pins hold.

One row is **unverified**: lint. The repository configures no linter — its root `AGENTS.md`
states that `pytest` is the only verification (design §15) — so there is no lint command to
run, and the build results record the reason rather than a pass.
