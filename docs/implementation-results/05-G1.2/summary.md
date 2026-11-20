# Summary — G1.2: Check task feasibility before the authoring stage

## 1. The problem it was solving

Before this change, the only reader of a roadmap entry's cited spec sections before a prompt was
written was the task author itself, in `P1`. If an entry cited a `design.md` section that did not
exist, an `<NAME>.md` document that could not be located uniquely, or a section whose heading was
followed by nothing, nobody found out until the author had already been paid for. The author then
reported `blocked:` and the run ended exit 3 — correct, but expensive: the build results cite an
observed blocked authoring run at roughly $0.36 in a 04-A2 attempt. By the time that report
arrived a branch, a worktree and a run directory already existed, and if the author did not notice
the defect the prompt was written against a citation that documents nothing.

The gap was structural rather than accidental: the citation enumeration already existed for the
`P2` evidence bundle, but it was used only to *print* what an entry cites, never to check whether
those citations resolve. The task is part of Epic G1 ("Prompt review depth"), follows G1.1 and the
C1.x prompt-evidence work, and builds on L1.2's same-file unfinished-predecessor gate — which the
task prompt and design leave as the *only* prerequisite check.

## 2. The core idea

Make the citation list a checked thing, not just a printed thing: the prompt workflow now resolves
every section an entry cites during its local preflight and refuses (exit 3) when one is missing,
unlocatable or empty — before any fetch, branch, worktree, run directory or Pi invocation.

The decision that made the rest follow is that there is **one** enumerator of cited specs.
`_render_cited_specs` (which feeds the `P2` evidence bundle) and the new feasibility checker both
consume `_cited_specs`, so the bundle and the preflight cannot drift about what an entry cites.
The bundle's rendered text is unchanged — it still prints the cited number verbatim — because the
task made changing that output text an explicit non-goal; only the enumeration was factored out.

Exit 3, not 2 or 4, is the other load-bearing choice. A dangling or empty citation is a
spec/roadmap defect only a human can fix, which is exactly the condition the author's `blocked:`
report already signals with exit 3; keeping it distinct from a usage error (2) and a safety refusal
(4) preserves §14's exit-code table. And "exist and non-empty" was fixed as a heading/body rule
compared canonically — dotted-integer tuples with leading zeros ignored, so `Design 09` matches
`## 9` — because `CITATION_RE` accepts zero-padded citations and a present section must never be
reported as a gap.

One boundary rule turned out to be part of the same idea rather than a detail: only Markdown ATX
headings delimit a section. `_heading_level` requires whitespace after the `#` run, because
`#not a heading` is body prose in Markdown. Treating it as a heading would declare a section with
content empty — a false refusal, which is the one outcome a cheap preflight must never produce.

## 3. What was built, piece by piece

The centre of the change is `aidw/workflows/prompt.py`. A new shared enumerator `_cited_specs`
walks both citation channels described in `roadmap-format.md` §8 — `Design N` from
`entry.citations`, and `<NAME>.md` tokens recovered from the task line plus the full `Done when`
block — preserving the bundle's existing semantics exactly (the bare `design.md` token is skipped
because `Design N` already covers that file, and a repeated document token is enumerated once).
`_render_cited_specs` was rewritten to render that enumeration, which is what guarantees the
bundle and the preflight see the same citations.

Above that sit the heading and section helpers. `_heading_level` identifies a real ATX heading and
its level, and draws the boundary described above. `_canonical_number` compares section numbers as
dotted-integer tuples. `_section_state` decides a section's state from its heading and the lines
beneath it: it exists when a numbered heading matches, and it is non-empty only when at least one
non-blank, non-heading line appears before the next heading of equal-or-higher level. That rule is
deliberately not "any text after the heading", which would pass a title followed only by blank
lines or deeper subheadings.

`_spec_feasibility_gaps` combines them. It enumerates the citations, locates each document through
the existing `_locate_doc` (reused rather than re-walked, so its `.git`/`.venv`/`node_modules`
pruning and its `None`-on-absence-or-ambiguity contract come for free), resolves `§N` headings and
`D<nn>` decision ids, and returns one gap string per problem in citation order — including a file
that exists but cannot be read. A bare `<NAME>.md` needs only unique location.
`_task_citation_inputs` supplies the same `_roadmap_lines` / `_done_when_block` / `entry.line - 1`
inputs the evidence bundle uses, and `_refuse_spec_gaps` produces the stderr text.

The wiring in `run()` is small but load-bearing. The gap list is computed once after `find_task`,
beside the incomplete-predecessor computation and before the `dry_run` split. In a real run, inside
the `if not takeover:` block and immediately before `_verify_base_branch`, a non-empty gap list is
printed to stderr — one line per gap, each naming the citation and its reason — and the run returns
3. That position was chosen over several alternatives precisely because of its consequences: it
sits after L1.2's predecessor refusal, so a predecessor wins when both conditions fire (roadmap
ordering is the first authority); it sits before the fetch, so a purely local check never spends a
network round trip on an unreachable `origin`; it sits before `load_all`, branch setup and
`create_run`, so a refused run leaves no run directory, branch, worktree or prompt file; and the
`not takeover` guard makes it run-scoped, so a `--resume` or `--from-prompt` continuation does not
repeat a check the run already passed.

`--dry-run` is the deliberate other half. Inside the existing dry-run note block, beside the
incomplete-predecessor note, it prints a `[dry-run]` note naming the gaps (or stating there are
none) and then falls through to normal dry-run planning, reaching the usual `return 0` with no
writes. This follows L1.2's contract and §17 Z14: a dry run is a write-free plan and must not
refuse.

The documentation and tests changed with it. `design.md` §8.1 gained the preflight in the stage
diagram's `preflight (...)` line plus a bullet stating the check's position, citation enumeration,
canonical comparison, non-empty rule, exit code and the author-side backstop; §17 gained row Z19
recording the prompt-fixed decisions and the gate impact. `docs/workflow-stages.md` names the check
in the prompt workflow's preflight line, in execution order.

On the test side, `tests/test_prompt_workflow.py` needed a fixture change before any new test could
pass: its shared `READ_PATH_FILES` seed gained a committed `design.md` with non-empty `## 8.1` and
`## 9` sections, because the existing roadmaps cite `Design 09` and `Design 8.1` and the new
refusal would otherwise refuse every fixture-driven run. Stripping the citations from the roadmap
fixture was the alternative and was rejected, since that would remove the check's fixture coverage.
The new tests cover each gap kind with a no-gap mirror, the zero-padded comparison in both
directions, the `#not a heading` body rule, a regression pin that the shared enumeration preserves
`_render_cited_specs`'s rendering and de-duplication, purity and determinism plus seeded property
coverage (padding never changes a verdict), the exit-3 refusal (naming every citation gap, with no
fetch, run directory, branch or prompt file), predecessor precedence, the dry-run note, and the
`--resume` non-repeat. `tests/test_design_doc.py` pins the §8.1 wording and exactly one §17 row for
`G1.2`, matched by task id rather than by `Z` number.

## 4. What it deliberately did not do

The author-side semantic feasibility step in `prompts/task-prompt.md` is untouched and remains the
backstop — the build results record it as unmodified. This preflight is mechanical on purpose: it
does not judge whether a cited section *contradicts* the roadmap, whether a prerequisite's work is
actually merged, or whether an acceptance condition needs an invented contract. A semantic check
here would reimplement the author slowly and wrongly, which is the reason the task records for
leaving it out.

Prerequisite handling was not extended. "Prerequisites are ticked" stays L1.2's same-file,
earlier-line gate; no dependency graph, no `Notes:` parsing and no cross-phase or cross-file gating
was added, and `aidw/roadmap.py`/`RoadmapTask` were not changed — an explicit non-goal carried over
from L1.2 and `roadmap-format.md` §10.

No new CLI flag was added (no `--skip-spec-check`), because the roadmap names none: the refusal has
one behaviour and `--dry-run` is the escape hatch for inspection. No new prompt or agent id,
checker, status vocabulary, config key, CI gate or `REQUIRED_PROMPTS`/`REQUIRED_SCRIPTS` entry was
introduced, and no prompt file was edited, so `prompts check` and `agents validate` are unaffected
by construction. The evidence bundle's rendered text is byte-identical — only its enumeration was
shared. G1.1 and B1.1 are separate tasks and were not touched. Finally, nothing was committed or
pushed and no pull request was opened; delivery belongs to the `/pr` stage.

Two things the change set now carries are deliberately outside this task's implementation: the
single `- [ ]` → `- [x]` roadmap flip owned by `/update-roadmap`, and the results documents
(summary, integration guide) owned by their own stages. They are recorded in the build results as
such so a reader does not mistake them for implementation edits.

## 5. Verification

The gates were run from the working tree relative to `main` — commits `67e4b1a..b09e2a4` plus the
uncommitted change set — through `aidw gate run`, with the scope the workflow's other stages
declare (`--ignore` for the implementation-results, architecture, tasks and task-prompts
directories; no source, test, config or lockfile excluded). Every outcome is recorded against tree
`117f26ae9a50`, which is a later change set than the previous recording because it carries the
shared-enumeration regression test.

The install step `uv sync --frozen` passed here (`Checked 19 packages in 1ms`, exit 0), and
`git diff --check` passed here with no output. `aidw doctor` reported `23 checks: 0 failed, 2
warning(s)` — a dirty working tree and a missing `.mcp.json`. `aidw prompts check` reported 0
errors and 0 warnings, and `aidw agents validate --strict` reported 0 errors and 0 warnings across
11 agent configs. All three of those gates and the whitespace check are this stage's own recorded
outcomes at tree `117f26ae9a50`.

The full suite is green: `uv run --frozen pytest` recorded `2468 passed in 51.01s`, cited from the
`suite` gate recorded at the same tree by the traceability stage and **reused** here rather than
re-run. The focused gate `g12-focused` over `tests/test_prompt_workflow.py` and
`tests/test_design_doc.py` (`-k g12`) is a separate selection, run once for this document, and
recorded 22 tests passing with no failures. Every task-specific row passes at that tree: the
checker's one case per gap kind with its no-gap mirror (missing `design.md`, missing `§N` heading,
empty section, unlocatable `<NAME>.md`, missing doc `§N`, unresolvable `D<nn>`, unreadable file),
the canonical zero-padded comparison in both directions, the `#not a heading` body rule, the
shared-enumeration rendering/de-duplication regression, purity/determinism and seeded property
coverage, the exit-3 refusal with no fetch/run/branch/prompt, predecessor precedence (exit 4, spec
gaps not printed), the dry-run note, the `--resume` non-repeat, the `test_design_doc.py` pins, and
`prompts/task-prompt.md` being unmodified.

The build results also record deviations that matter for reading them honestly. The previous
recording of this stage gated tree `4fb24c6fef22` with 2467 tests; the current tree `117f26ae9a50`
carries the added regression test and records 2468. And an **earlier** recording against tree
`5a4c53219231` saw the suite red on
`test_g12_hash_prefix_without_heading_space_is_section_body`, because `#not a heading` was then
treated as a level-1 heading; the whitespace-after-`#` rule supersedes that failure, and none of
the outcomes quoted above come from that tree.

Two rows remain recorded as **unverified** rather than invented: lint, because no linter is
configured (`AGENTS.md` lists exactly the gates run and `design.md` §15 makes pytest the only
verification), and build, because no build command is named by `AGENTS.md` or
`aidw/conventions.md`, with packaging exercised inside the suite by `tests/test_packaging.py`. No
pull request exists yet for the branch, and the build results say so rather than inventing a
number.
