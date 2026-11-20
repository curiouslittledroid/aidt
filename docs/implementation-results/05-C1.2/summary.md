# Implementation Summary — C1.2: Resolve gate commands from the target's actual gates heading, and diagnose misses

**Branch:** `05-C1.2`
**Source of record:** `docs/implementation-results/05-C1.2/build-results.md`

## 1. The problem it was solving

The prompt workflow's evidence bundle carries a gate-commands element so the `P2` reviewer
knows how the target repo verifies itself (design §8.1). That element was read from the
target's conventions sources, but the reader recognised exactly one literal heading, `## Gates`.

A target repo that publishes its gates under `## Gate commands` — the shape a natural reader
writes — therefore contributed nothing, and the bundle silently degraded to
`unavailable — could not be read`. Nothing failed; the reviewer was simply handed a bundle with
a hole in it, and the miss had no diagnostic anywhere. The degradation is by design and
normal (L2.4 requirement 4), which is what made the failure mode so quiet: a missing gate list
looked identical whether the repo had no gates section at all or used a heading one word
different from the one AIDT expected.

The task exists to widen what the reader recognises, to give a repo a way to declare its own
heading when it uses something else entirely, and to make a near-miss visible in `aidw doctor`
instead of only silently degrading.

## 2. The core idea

The recognised heading set became **one shared definition** instead of a literal repeated in a
reader. `aidw/prompts.py` now owns `GATES_HEADINGS = ("## Gates", "## Gate commands")` plus two
pure helpers — `is_gates_like_heading` (a `## ` heading containing "gate", case-insensitive)
and `is_recognised_gates_heading` (the prefix predicate). The bundle reader in
`aidw/workflows/prompt.py` imports the tuple as `_GATES_HEADING`; `aidw/doctor.py` imports the
same objects directly. Neither reader holds a second literal set, so the bundle reader and the
diagnosis cannot drift on what counts as a gate heading.

Two decisions inside that idea matter as much as the shared constant:

- **Recognition stays a `startswith` prefix test, never `==`.** Switching to exact matching
  would have been the obvious way to be strict about headings, and it would have broken the
  toolkit's own `## Gates — run exactly these, and only these`, which the existing
  `AGENTS_EVIDENCE_FIXTURE` shape depends on. The same rule in the doctor keeps that suffixed
  heading silent rather than newly warned.
- **A config lever rather than a third literal.** A repo whose heading matches none of the
  canonical forms can declare it with the new optional top-level `gates_heading`. Its value is
  the **full heading line including the `## ` prefix** (`gates_heading: "## Verification gates"`),
  matched verbatim. A bare title was the alternative and was rejected because it would force the
  code to prefix it, hiding the format and adding a second matching rule; a verbatim full line
  keeps the matcher a single `startswith`.

Deliberately absent from that idea is a structured `gates:` config field: R14 rejected it, and
this task adds only the single heading pointer.

## 3. What was built, piece by piece

**The shared contract (`aidw/prompts.py`).** This is the piece everything else is built on. It
gains the `GATES_HEADINGS` tuple and the two pure helpers, and its
`AGENTS_MD_SOURCE`/`CONVENTIONS_SOURCES`/`read_conventions_sources` comments were updated
because they still described the single `## Gates` heading. Putting the constant here rather
than in either reader is what makes requirement 4's "no second literal set" enforceable: there
is one place to read what AIDT considers a gate heading.

**The read channel (`aidw/workflows/prompt.py`).** `_gates_section` now takes an `extra_heading`
and routes recognition through the shared predicate — it stays a pure function over the text it
is given, with no I/O and no mutation of its input, which is what lets the tests pin purity. It
determines the section by taking lines from a recognised heading to the next `## ` heading, as
before. `_gate_block` still passes each conventions source's text through in D16 order
(`AGENTS.md`, then `aidw/conventions.md`), unchanged; what changed is that it now loads the
declared heading first, via `load_target_config(repo.root / "aidw" / "config.yaml")`, and
passes it in. The load is `repo.root`-relative on purpose: reading the toolkit's own config
would pass every self-hosted test and break only after extraction (AGENTS.md "Two roots"). The
literal `_GATES_HEADING = "## Gates"` that lived in this module is replaced by the import of the
shared tuple.

**The diagnosis (`aidw/doctor.py`).** A new `_check_gates_heading`, wired into `collect_checks`
and shaped like `_check_architecture_trigger`, reads the target's conventions sources and, for
each `## ` heading that looks gates-like but is not recognised, emits a `gates heading` WARN
naming the source file and the heading, plus both fixes: rename to `## Gates`/`## Gate commands`,
or declare `gates_heading`. It is WARN and never FAIL, and never touches `run_doctor`'s exit
code, because a non-standard heading still works — degrading is a normal state, so the check is
advice about a near-miss, not a broken prerequisite. It loads the configured `gates_heading`
before deciding something is unrecognised, so a repo that declares its heading is not warned,
and a missing or unreadable config or source degrades to "nothing to report" rather than
crashing.

Because the heuristic is deliberately broader than the recognised set — its job is to catch
what is *not* recognised — case is significant: `## Gate Commands` (capital C) is not
`## Gate commands`, and it both degrades the bundle and triggers the WARN, rather than being
silently lowercased into a match.

**The config key (`aidw/target_config.py`).** `gates_heading` joins `TOP_LEVEL_KEYS` and
`TargetConfig`, is parsed through the existing `_read_str` helper, and round-trips through
`to_dict`. It is fail-closed in the way the loader requires: without the `TOP_LEVEL_KEYS` entry
a config that uses it would be refused as unknown, and the JSON schema carries
`additionalProperties: false`, so it needs the property too. An empty value is one loader ERROR
naming `gates_heading` with the value dropped, following the `model`/`paths.roadmap_glob`
non-empty-string precedent — `_read_str` passes `""` through for optional keys, and
`line.startswith("")` would match every line of every source.

**The documentation surface.** `docs/target-repo-config.md` gains the field-table row (type,
default, effect with a `## `-prefixed example), the conventions bullet's gate-heading note and
the Full example; `docs/schema/aidw-config.schema.json` gains the `gates_heading` property
(`string`, `minLength: 1`, `## `-prefixed example, ERROR-on-empty note). Both are drift-checked
by `tests/test_target_repo_config_doc.py` and the schema-agreement case, which were re-baselined
rather than weakened.

**The design record (`design.md`).** §7.3 step 4 now states the two recognised headings, the
declared heading and the one-shared-definition rule in the read channel; §8.1 describes the
evidence bundle's gate-commands element and the doctor diagnosis; and a new §17 row `Z16` — the
next free id after C1.1's `Z15`, not a reuse or renumber — records the task id, spec sections,
changed files and the prompt-fixed decisions (a)–(c).

**The contract tests.** `tests/test_prompt_workflow.py` covers a `## Gate commands` fixture
supplying both the block and the rendered bundle, a configured full-`## `-prefixed heading being
recognised while a bare title is not, a target-relative config load that a toolkit-root read
would fail, the `## Gate Commands` degrade case, and `_gates_section` purity.
`tests/test_doctor.py` pins the WARN, the silence cases (canonical, suffixed canonical, declared
heading), the config-less and source-less OK cases, and that the WARN never fails `run_doctor`.
`tests/test_target_config.py` pins parse, verbatim round-trip, default unset, wrong type naming
the field and the empty-value ERROR, with the re-baselined key inventory and schema-agreement
case. `tests/test_design_doc.py` pins the §7.3/§8.1 wording and exactly one C1.2 §17 row,
matched by task id and wording rather than by `Z` number.

## 4. What it deliberately did not do

- **C1.3, "Inline the resolved gate commands into the stage prompts", is not started.** That
  task consumes the resolved source this one produces; beginning it here would have conflated
  resolving the commands with injecting them into prompts.
- **C1.1's injection split is untouched.** Only the *read* channel (`_gate_block`) changed.
  `render_repo_conventions`/`appends_target_agents_md`, the `AGENTS.md` append and the
  `append_agents_md` opt-in are unchanged — the task prompt lists this explicitly as a non-goal.
- **No structured `gates:` config field.** R14 rejected it; the single heading pointer
  `gates_heading` is the whole lever.
- **The degrade contract is unchanged.** No source, no recognised heading, an unrecognised
  gates-like heading, and non-UTF-8/unreadable sources all still yield `_EVIDENCE_UNAVAILABLE`.
  The doctor WARN is the diagnostic; the bundle never fails a run.
- **No `lint` gate was added.** The repo configures none and `AGENTS.md` forbids adding one
  inside an unrelated task (see §5).
- **No pull request, commit or push** — delivery is the `/pr` stage's job.

## 5. Verification

Verification was recorded through the repo's own gate runner, `aidw gate run <key> $SCOPE --
<command>`, against tree `ca12234bcb33` at stage `record-implementation-results`. The build
results are the only evidence used here; no gate was re-run for this summary.

Install (`uv sync --frozen`) passed — "Checked 19 packages in 0.53ms", exit 0. Build
(`uv build`, via `aidw gate run build`) passed, producing `aidt-1.5.0.tar.gz` and
`aidt-1.5.0-py3-none-any.whl`. The full suite (`uv run --frozen pytest`, via the `suite` gate)
passed: **2367 passed in 52.22s**, with the five C1.2 contract modules included in that run —
the build results explicitly note they were not invoked a second time to obtain per-module
counts, so they are reported as part of the single suite. Doctor (`uv run --frozen aidw doctor`)
passed: 23 checks, 0 failed, 2 warnings, exit 0; the warnings are the pre-existing
`git branch 05-C1.2, dirty working tree` and `mcp config missing`, and the new `gates heading`
check is `ok` on the toolkit's own repo. `aidw agents validate --strict` passed (11 agent
configs, 0 errors, 0 warnings) and `aidw prompts check` passed (0 errors, 0 warnings);
`git diff --check` passed with no output. Each of those five gates is recorded as passed for
tree `ca12234bcb33`.

The task-specific gates are recorded as passing inside that same suite: the `## Gate commands`
fixture supplies both the block and the rendered evidence bundle; a configured full-
`## `-prefixed heading is recognised verbatim while a bare title is not, and it is loaded from
`repo.root`; `## Gate Commands` still degrades and `_gates_section` is proven pure; the doctor
WARNs for `## Gate Commands`/`## Verification gates`, stays silent for the canonical, suffixed
canonical and declared cases, and never fails `run_doctor`; `gates_heading` is accepted,
documented and drift-checked including the `to_dict` round-trip and the empty-value ERROR; and
the design sections plus the single C1.2 §17 row are pinned by task id.

One row is **unverified**, and stays unverified: the `lint` row has no command to run because
this repo configures no linter, formatter or type-checker and `AGENTS.md` forbids adding one in
an unrelated task. The build results record it as `unverified` with that reason rather than
inventing a command or borrowing one from another stack. Nothing in the recorded run failed.
