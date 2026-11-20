# Summary — C1.3: Inline the resolved gate commands into the stage prompts that reference them

## The problem it was solving

Five stage prompts told their agent to run the repository's gates, but named them only as "the
repo's own, taken by name from `aidw/conventions.md`/root `AGENTS.md`". The prompt workflow had
already resolved those commands for the evidence bundle, yet each stage still re-derived them —
or guessed — independently. That produced per-stage key/command/scope drift and defeated the
gate-outcome reuse the pipeline depends on: a stage that named the command slightly differently
could not cite an earlier recorded result. The task prompt and the build results both frame this
as the last piece of the prompt-context-economy epic, following C1.1's conventions channel and
C1.2's heading recognition.

## The core idea

Resolve the gate block in exactly one place and inject that resolved text into the stage prompts
that reference it. `aidw/prompts.py:resolved_gate_block(repo_root)` became the single resolution
path; the evidence bundle's existing `_gate_block` in `aidw/workflows/prompt.py` was reduced to a
wrapper over it that maps `None` to its own `_EVIDENCE_UNAVAILABLE` sentinel. The resolver
returns `None`, never a sentinel string, because the two consumers take different
no-resolution contracts: a stage prompt must stay byte-identical, while the evidence bundle
degrades with an `unavailable` note. That split is what let the rest of the change follow —
one resolver, one injected block, and a prompt-side guarantee that a repo with no resolvable
gates renders exactly as before.

## What was built, piece by piece

The single resolution moved into `aidw/prompts.py`, carrying `gates_section` with it. It reads
both conventions sources in D16 order, recognises headings through C1.2's machinery plus the
target's configured `gates_heading`, and always reads the **target** root rather than the
toolkit root. `aidw/workflows/prompt.py` keeps `_gates_section` as a re-export so existing
callers and tests still import it, and drops the imports that are no longer its own. This is the
piece that makes the two consumers incapable of disagreeing.

Beside it, `GATE_PROMPTS` is a frozenset of the five resolved basenames —
`impliment-task.md`, `test.md`, `fix-next-review-followup.md`, `record-implementation-results.md`
and `code-review.md` — keyed by resolved basename exactly like `CONVENTIONS_PROMPTS`, so a repo
shadow or explicit prompt path still keys correctly. It is deliberately not the conventions set:
the fix and code-review prompts record gate outcomes, while `task-prompt.md` and
`update-traceability.md` do not.

`inject_gate_block(prompt_text, prompt, repo_root)` appends the resolved block verbatim under a
source-labelled header modelled on `CONVENTIONS_HEADER`, and returns the text byte-identically
when the prompt is outside the five or nothing resolves. `aidw/runner.py:run_stage` calls it at
the `inject_repo_conventions` seam, after the conventions append, so the written `.rendered.md`
and the stdin payload sent to Pi carry the same text. An `unavailable` note is never injected
into a stage prompt; that remains the evidence bundle's degrade.

The five prompt files then had their "never inlined here" clause replaced with a pointer that
names the injected resolved gate block as authoritative when the repo declares one and keeps the
`aidw/conventions.md`/root `AGENTS.md` fallback. `code-review.md`, which never carried that
clause, gained equivalent gate-command guidance in its review-order step 6. Every
`aidw gate run <key> $SCOPE -- <command>` wrapper and its key/scope guidance survives, because a
repo's gate section is bare commands: the injection supplies the commands, not the wrapper.

One deliberate corner was decided rather than left silent. Three prompts
(`impliment-task.md`, `test.md`, `record-implementation-results.md`) are in both
`GATE_PROMPTS` and `CONVENTIONS_PROMPTS`, so a repo declaring gates in `aidw/conventions.md`
would see that section twice. The focused resolved block is the authoritative "resolved gate
commands" presentation, and the whole-file conventions append is not de-duplicated, because
C1.1's contract is a verbatim whole-file append and trimming it would make the injected
conventions depend on a second reader. This relationship is recorded in `design.md` §17 row Z17.

Finally, editing `code-review.md` meant it could no longer honestly be byte-frozen. It was
re-classified in `docs/migration/prompt-classification.md` from bucket (i) "ship as-is" into a
new post-cutover class (v), and removed from `BYTE_FROZEN` in the classification test. Every
other bucket-(i) file stays byte-frozen, and the spec's own (i) list is still asserted verbatim;
class (v) is pinned two-sidedly so no second file can quietly leave the freeze. `design.md` §7.3
gained the new step 5 describing the injection, and §17 gained row Z17 with decisions (a)–(f).
`docs/target-repo-config.md` now names `resolved_gate_block` as the one resolution both
consumers use. The contract tests were extended in `tests/test_conventions_injection.py`,
`tests/test_prompt_classification.py` and `tests/test_design_doc.py` to cover the five-prompt
set, the verbatim D16-ordered join, byte-identity for excluded prompts, repo-shadow keying,
two-roots behaviour, purity, the dry-run render seam, and the re-classified freeze.

## What it deliberately did not do

- C1.2's heading recognition and doctor diagnosis are untouched: `GATES_HEADINGS`,
  `is_gates_like_heading`/`is_recognised_gates_heading` and `aidw/doctor.py`'s `gates heading`
  check were not extended. They were already delivered under Z16 and are out of this task's
  scope.
- Epic G1 (prompt review depth) is not started: `prompts/task-review.md`, `aidw/findings.py` and
  the prompt-workflow preflight are untouched.
- `pr.md`, `update-traceability.md` and `update-architecture.md` were not added to
  `GATE_PROMPTS`, even though they reference gate commands or the conventions sources. The
  roadmap fixes exactly five prompts.
- The repo's commands were not re-synthesised or re-keyed: the verbatim gate section is injected
  and the `aidw gate run` key/scope wrapping stays the prompt files' own text.
- No new stage id, `when=` token, config key, JSON-schema node, `REQUIRED_PROMPTS` entry or new
  CI gate was added, per Z17's gate impact.
- No pull request, commit or push was made; delivery belongs to the `/pr` stage.

## Verification

The build results record this run against tree `fba465750012`. The top-level gate rows all
passed: the frozen install, the build (producing `aidt-1.5.0.tar.gz` and
`aidt-1.5.0-py3-none-any.whl`), the full test suite (2425 passed in 48.96s), `aidw doctor`
(23 checks, 0 failed, 2 warnings), `aidw agents validate --strict` (11 configs, 0 errors and 0
warnings), `aidw prompts check` (0 errors, 0 warnings across 43 files), and
`git diff --check` (no output). The doctor warnings are the pre-existing dirty working tree and
missing mcp config, and its `gates heading` check was `ok`.

Two honesty notes attach to those passes. The suite row was **not re-run** for this stage: the
build results record `aidw gate run suite` as `reused` for tree `fba465750012`, originally
recorded by the `update-traceability` stage at `2026-11-20T07:34:09Z` with the identical scope,
so it is cited with its origin rather than bought twice. And the **lint** row is `unverified`,
with the recorded reason that this repo configures no lint command — `AGENTS.md` states none
exists and forbids adding one in an unrelated task, and `aidw/conventions.md` adds no gates.

All task-specific checks recorded as passing are inside that single suite outcome: the
five-prompt set versus the conventions set, the hand-calculated D16-ordered join, per-prompt
injection under the one header, byte-identity for `pr.md`/`task-prompt.md`/`update-traceability.md`,
repo-shadow keying, the `None` + byte-identity behaviour for no-source and no-heading repos, the
target-versus-toolkit-root sentinel, purity and the dry-run render seam, the re-classified freeze
assertions, the four bucket-(ii) prompts still keeping the `aidw gate run` idiom, and the §7.3
step 5 / one-Z17-row wording pin. No per-module test counts were obtained, because the focused
modules were not invoked a second time; they are reported as part of the recorded full-suite
result. A read-only `grep` across the five prompts found no remaining "inlined here" clause —
only `prompts/task-prompt.md:153`, which is not one of the five — and the `aidw gate run`
wrappers survive in every edited prompt.
