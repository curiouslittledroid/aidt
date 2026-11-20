# Integration-test guide — G1.2: check task feasibility before the authoring stage

## 1. What this guide covers

This is a **hand-run procedure** for branch `05-G1.2`, which adds a cited-spec preflight to
`aidw prompt` (design §8.1, §17 row Z19; `aidw/workflows/prompt.py`). The change makes
`aidw prompt <phase> <epic> <task>` refuse with exit `3`, before any fetch, branch, worktree,
run directory or prompt file, when the resolved roadmap entry cites a spec file or section
that is missing, cannot be located uniquely, or is empty; `--dry-run` reports the same gaps
as notes and never refuses, and a `--resume`/`--from-prompt` takeover does not repeat the
check. The procedure walks the repository's own checks, the `aidw prompt` CLI surface (all
four gap kinds, the predecessor-precedence order, the dry-run note, the hash-prefixed-body
rule, the all-resolved path and the resume guard), the documentation drift tests, and the
roadmap entry the branch ticks.
**Nothing in this guide has been executed by the toolkit**: this is an instruction document.
The build results beside it (`build-results.md`) are the recorded evidence, and where they
mark a row `unverified` this guide repeats it with its recorded reason rather than predicting
green.

There are no browser-UI or external (cloud-provider) scenarios in this change: no changed
file, build-results row or task-prompt statement names a web screen, route, deployed stack,
cloud account, bucket, role or ARN. Those groups are therefore absent, not omitted by
accident.

## 2. Scenarios

### Group A — The repository's own tooling (the `aidt` checkout)

#### A1. Install and full test suite

**Prerequisites.** The `aidt` checkout for branch `05-G1.2`; `uv` installed; network access for
`uv sync --frozen` if the environment is not already populated. No credentials and no target
repository.

**Command(s) or steps.** From the `aidt` checkout root:

```bash
uv sync --frozen
echo "sync exit: $?"
uv run --frozen pytest
echo "pytest exit: $?"
```

**Expected observable result.** `uv sync --frozen` reports `Checked 19 packages in 1ms` (or a
superset if the lock moved) and exits 0; the build results record that install as run at the
recorded tree. The suite passes: `2468 passed in 51.01s`, exit 0, with no failure line. The
build results cite that outcome from the `suite` gate recorded at tree `117f26ae9a50`
(stage `update-traceability`, 2026-11-20T11:17:25Z) and record that it was re-asked with the
same key, command and scope and **reused** rather than re-run (the Deviations section records
that `suite` was reused against the same tree and scope). Two earlier trees are superseded in
that Deviations section: tree `4fb24c6fef22` gated 2467 tests before the shared-enumeration
regression test was added, and tree `5a4c53219231` observed the suite red on
`test_g12_hash_prefix_without_heading_space_is_section_body` — do not expect either at the
current tree.

**How to tell pass from fail.** Pass when the suite exits 0 with all 2468 tests passing and no
failure, error or collection-error line. Fail on any failure (including a reappearance of the
former `test_g12_hash_prefix_without_heading_space_is_section_body` failure), on a different
test count at the same tree, or on a non-zero install exit. If your tree differs from
`117f26ae9a50`, the result is new: record it rather than attributing it to the build
results.

**Cost, permission or destructive warning.** None: local install and local tests, no spend, no
external write. `uv sync --frozen` will not modify `uv.lock`; a lock mismatch is a failure, not
an update.

#### A2. Environment and prompt/agent validation

**Prerequisites.** A1's install has completed. Pi is not invoked by any of these commands.

**Command(s) or steps.**

```bash
uv run --frozen aidw doctor
echo "doctor exit: $?"
uv run --frozen aidw prompts check
echo "prompts exit: $?"
uv run --frozen aidw agents validate --strict
echo "agents exit: $?"
git diff --check
echo "whitespace exit: $?"
```

**Expected observable result.** Recorded outcomes: `doctor` — `23 checks: 0 failed, 2
warning(s)` (dirty working tree, missing `.mcp.json`), exit 0; `prompts check` — `resolved
repo prompts: 0 error(s), 0 warning(s)`, exit 0; `agents validate --strict` — `11 agent
config(s): 0 error(s), 0 warning(s)`, exit 0; `git diff --check` — exit 0, no output. The
build results record `doctor`, `prompts check` and `agents validate` as run at tree
`117f26ae9a50` (stage `record-implementation-results`); only the `suite` gate is recorded as
reused, while install and `git diff --check` are reported as run here.

**How to tell pass from fail.** Fail if any command exits non-zero, or if the error count in
`prompts check`/`agents validate` is anything but `0 error(s)`. A different *warning* set is
not a failure (the two recorded doctor warnings are environmental), but a different error
count is.

**Cost, permission or destructive warning.** None. These commands are read-only; `doctor`
may inspect local tooling and report warnings only.

#### A3. Documentation drift checks

**Prerequisites.** A1's install has completed. Python only; no Pi.

**Command(s) or steps.**

```bash
uv run --frozen pytest tests/test_design_doc.py tests/test_workflow_stages_doc.py
echo "docs-drift exit: $?"
```

**Expected observable result.** Both files pass. The recorded full-suite result is
`2468 passed in 51.01s` with no failures at tree `117f26ae9a50`, and the `g12-focused` gate
(`aidw gate run g12-focused`, tree `117f26ae9a50`, stage `record-implementation-results`,
2026-11-20T11:17:53Z) ran `tests/test_prompt_workflow.py` + `tests/test_design_doc.py -k g12`
(22 tests) with `......................` / `[100%]` and no failures. The run was made once as a
separate selection, not as a second full-suite invocation. The build results record the
`tests/test_design_doc.py` G1.2 pins (one §17 row matched by task id `G1.2`, §8.1 wording)
passing in that gate.

**How to tell pass from fail.** Fail if either file reports a failure, if a G1.2 pin is
missing, or if `tests/test_design_doc.py` reports a duplicate or missing `G1.2` §17 row. A
failure here is a new result: the recorded tree has none.

**Cost, permission or destructive warning.** None: local test run only, no spend, no external
write.

#### A4. The roadmap entry is ticked and nothing else in its file changed

**Prerequisites.** The `aidt` checkout for branch `05-G1.2` with `main` available locally; no Pi,
no network. The branch's change set includes the single checkbox flip on the `G1.2` entry of
`docs/tasks/05 - Pipeline efficiency.md`, recorded in the build results' Files Changed note.

**Command(s) or steps.** From the `aidt` checkout root:

```bash
git diff main -- 'docs/tasks/05 - Pipeline efficiency.md'
uv run --frozen aidw --repo . tasks --show "05 G1 G1.2"
echo "exit: $?"
```

**Expected observable result.** The diff contains exactly one changed line pair — the `G1.2`
entry's `- [ ]` becoming `- [x]` — and no other added, removed or reformatted line in that file.
`tasks --show` exits `0` and prints the entry with a ticked checkbox:
`05 G1.2  [x] Check task feasibility before the authoring stage`, followed by a `Branch:` line,
a `File:` line naming `docs/tasks/05 - Pipeline efficiency.md`, the entry's `Done when:` text and
`Specs:     Design 8.1`.

**How to tell pass from fail.** Pass when the checkbox is `[x]` in both the diff and the CLI
output and the file's diff contains no other change. Fail on `[ ]`, on a missing or duplicated
`G1.2` entry (the command prints `task not found` and exits non-zero), or on any additional
hunk, whitespace change or neighbour edit in the roadmap file.

**Cost, permission or destructive warning.** None: both commands are read-only (the diff
inspects the working tree; `tasks --show` only parses the roadmap).

### Group B — Custom CLI: the `aidw prompt` cited-spec preflight

#### Common setup for every Group B scenario

Run these once, from the `aidt` checkout. They build a disposable target repo in the
supported layout (a bare repository plus sibling worktrees, design §3.2) under
`/tmp/aidw-g12-ws`. `schema_version: 1` is the minimal config from
`docs/target-repo-config.md`; `paths.roadmap_dir`, `paths.task_prompts_dir`,
`paths.implementation_results_dir` and `paths.build_results_template` are the default
read-paths that `aidw prompt` validates, and `design.md` is the file a `Design N` citation
names.

```bash
rm -rf /tmp/aidw-g12-ws
mkdir -p /tmp/aidw-g12-ws/seed/aidw \
         /tmp/aidw-g12-ws/seed/docs/tasks \
         /tmp/aidw-g12-ws/seed/docs/task-prompts \
         /tmp/aidw-g12-ws/seed/docs/implementation-results
cd /tmp/aidw-g12-ws/seed
git init -q -b main
git config user.name "AIDW G1.2 Manual"
git config user.email "aidw-g12-manual@example.invalid"
printf 'schema_version: 1\n' > aidw/config.yaml
printf '# Build results template\n' > docs/implementation-results/TEMPLATE.md
: > docs/task-prompts/.gitkeep
cat > design.md <<'EOF'
# Design

## 9. Cited section

Prose that makes the section non-empty.
EOF
cat > 'docs/tasks/03 - Manual Test.md' <<'EOF'
# Phase 3: Manual test

## Epic E4: Manual epic

- [ ] **E4.1. A feasibility target** per Design 9..
  - Done when: the cited section stays non-empty.
EOF
git add -A
git commit -qm "seed the manual target repo"
git clone --bare -q /tmp/aidw-g12-ws/seed /tmp/aidw-g12-ws/bare.git
git -C /tmp/aidw-g12-ws/bare.git worktree add -q /tmp/aidw-g12-ws/control main
```

Sanity-check the target before any scenario (from the `aidt` checkout):

```bash
uv run --frozen aidw --repo /tmp/aidw-g12-ws/control tasks --phase 03
uv run --frozen aidw --repo /tmp/aidw-g12-ws/control config show
```

`tasks --phase 03` lists `E4.1`; `config show` resolves `paths.roadmap_dir` =
`docs/tasks`, `paths.task_prompts_dir` = `docs/task-prompts`,
`paths.implementation_results_dir` = `docs/implementation-results`,
`paths.build_results_template` = `docs/implementation-results/TEMPLATE.md` and
`repo.base_branch` = `main`. Every group B edit is made in `/tmp/aidw-g12-ws/control` and
**committed** before the next command, because the real-run preflight refuses a dirty control
worktree (exit 4) before it reaches the cited-spec check.

#### B1. Each gap kind refuses with exit 3, names the citation, and leaves no side effect

**Prerequisites.** Common setup completed; you are in the `aidt` checkout; a configured git
identity is not needed beyond the scratch repo's local config. No Pi, no network.

**Command(s) or steps.** For each case: apply the edit in `/tmp/aidw-g12-ws/control`, commit
it, then run the command and capture the exit code.

1. **Missing cited file.** Remove `design.md`:

   ```bash
   git -C /tmp/aidw-g12-ws/control rm -q design.md
   git -C /tmp/aidw-g12-ws/control commit -qm "drop the cited spec"
   uv run --frozen aidw --repo /tmp/aidw-g12-ws/control prompt 03 E4 E4.1 --no-fetch
   echo "exit: $?"
   ```

2. **Cited section heading absent.** Restore a file whose only heading is numbered `10`:

   ```bash
   cat > /tmp/aidw-g12-ws/control/design.md <<'EOF'
# Design

## 10. A different section

Prose.
EOF
   git -C /tmp/aidw-g12-ws/control add -A
   git -C /tmp/aidw-g12-ws/control commit -qm "renumber the cited section"
   uv run --frozen aidw --repo /tmp/aidw-g12-ws/control prompt 03 E4 E4.1 --no-fetch
   echo "exit: $?"
   ```

3. **Cited section present but empty.** Restore `## 9` with only a deeper subheading under it:

   ```bash
   cat > /tmp/aidw-g12-ws/control/design.md <<'EOF'
# Design

## 9. Cited section

### 9.1 A subheading with no prose

## 10. A filled section

Real prose.
EOF
   git -C /tmp/aidw-g12-ws/control add -A
   git -C /tmp/aidw-g12-ws/control commit -qm "empty the cited section"
   uv run --frozen aidw --repo /tmp/aidw-g12-ws/control prompt 03 E4 E4.1 --no-fetch
   echo "exit: $?"
   ```

4. **A `<NAME>.md` citation that cannot be located uniquely, then one whose `D<nn>` id no
   heading names.** First create two files with the same name and add the reference to the
   task line:

   ```bash
   cat > /tmp/aidw-g12-ws/control/design.md <<'EOF'
# Design

## 9. Cited section

Prose that makes the section non-empty.
EOF
   mkdir -p /tmp/aidw-g12-ws/control/docs/migration /tmp/aidw-g12-ws/control/docs/notes
   printf '# Extraction\n\n## 3.8 Other\n\nProse.\n' \
     > /tmp/aidw-g12-ws/control/docs/migration/EXTRACTION.md
   printf '# Extraction\n\n## 3.8 Other\n\nProse.\n' \
     > /tmp/aidw-g12-ws/control/docs/notes/EXTRACTION.md
   cat > '/tmp/aidw-g12-ws/control/docs/tasks/03 - Manual Test.md' <<'EOF'
# Phase 3: Manual test

## Epic E4: Manual epic

- [ ] **E4.1. A feasibility target** per Design 9 (EXTRACTION.md D16)..
  - Done when: the cited section stays non-empty.
EOF
   git -C /tmp/aidw-g12-ws/control add -A
   git -C /tmp/aidw-g12-ws/control commit -qm "add an ambiguous doc citation"
   uv run --frozen aidw --repo /tmp/aidw-g12-ws/control prompt 03 E4 E4.1 --no-fetch
   echo "exit: $?"
   rm /tmp/aidw-g12-ws/control/docs/notes/EXTRACTION.md
   git -C /tmp/aidw-g12-ws/control add -A
   git -C /tmp/aidw-g12-ws/control commit -qm "make the doc token unique"
   uv run --frozen aidw --repo /tmp/aidw-g12-ws/control prompt 03 E4 E4.1 --no-fetch
   echo "exit: $?"
   ```

5. **Cheap-failure order (no fetch before the refusal).** Make `origin` unreachable by
   removing the seed repository, then run **without** `--no-fetch`:

   ```bash
   rm -rf /tmp/aidw-g12-ws/seed
   uv run --frozen aidw --repo /tmp/aidw-g12-ws/control prompt 03 E4 E4.1
   echo "exit: $?"
   ```

   Finally confirm no side effect was left behind:

   ```bash
   uv run --frozen aidw --repo /tmp/aidw-g12-ws/control runs list
   git -C /tmp/aidw-g12-ws/bare.git branch --list '03-*'
   test -e /tmp/aidw-g12-ws/control/docs/task-prompts/03-E4.1-prompt.md && echo "PROMPT FILE EXISTS" || echo "no prompt file"
   test -d /tmp/aidw-g12-ws/03-E4.1 && echo "WORKTREE EXISTS" || echo "no task worktree"
   ```

**Expected observable result.** Cases 1–4 exit `3` and print on **stderr** this refusal
header, then one indented gap line, then the closing line. The sample below shows case 1's gap:

```text
refusing: cannot author `E4.1` in `03 - Manual Test.md`; a cited spec section is missing, not uniquely locatable, or empty:
  Design 9 → design.md: file not found
Repair the cited spec or the roadmap entry — this check is deterministic and never guesses — then re-run `aidw prompt`.
```

The gap line for each mutation is:

| Case | Recorded gap text |
|---|---|
| 1 | `Design 9 → design.md: file not found` |
| 2 | `Design 9 → design.md: no heading numbered §9` |
| 3 | `Design 9 → design.md: §9 is empty` |
| 4 (first run) | `EXTRACTION.md → could not locate the cited file uniquely` |
| 4 (second run) | ``EXTRACTION.md → docs/migration/EXTRACTION.md: no numbered heading names `D16` `` |

Case 5 exits `3`, prints the `EXTRACTION.md ... D16` gap, and — the ordering evidence — does
**not** print ``warning: could not fetch `origin` `` (that warning belongs to the later
base-branch check; the refusal happens before it). After all cases: `runs list` prints
`no runs`; the `git branch --list '03-*'` output is empty; the prompt file check prints
`no prompt file`; the worktree check prints `no task worktree`.

**How to tell pass from fail.** Pass only when the exit code is exactly `3`, the gap line for
the mutation you made appears on **stderr** with the same citation label and the same reason,
and *none* of the four side effects exists. Fail if the exit is `2` (usage/config), `4`
(git/layout/predecessor), or `0`; if the gap names a different citation or a different reason
(e.g. `§09` when the citation is `Design 9`); if a run appears in `runs list`; or if any
branch, prompt file or worktree exists afterwards.

**Cost, permission or destructive warning.** Cheap: no Pi invocation, no model spend, no
network (case 5's fetch fails by design). Destructive only inside the disposable
`/tmp/aidw-g12-ws` tree — case 5 deletes the scratch seed repository, and case 1 deletes the
scratch `design.md`. Never run these edits against a real target repository.

#### B2. A missing spec section still yields to an unticked predecessor (exit 4)

**Prerequisites.** Common setup completed. No Pi, no network.

**Command(s) or steps.** Restore a resolvable `design.md`, then add an unticked earlier task
in the same phase file *and* keep a dangling citation on the target task:

```bash
cat > /tmp/aidw-g12-ws/control/design.md <<'EOF'
# Design

## 9. Cited section

Prose that makes the section non-empty.
EOF
cat > '/tmp/aidw-g12-ws/control/docs/tasks/03 - Manual Test.md' <<'EOF'
# Phase 3: Manual test

## Epic E4: Manual epic

- [ ] **E4.0. An earlier target** per Design 9..
  - Done when: the earlier task is complete.
- [ ] **E4.1. A feasibility target** per Design 42.7..
  - Done when: the cited section stays non-empty.
EOF
git -C /tmp/aidw-g12-ws/control add -A
git -C /tmp/aidw-g12-ws/control commit -qm "add an unticked predecessor and a dangling citation"
uv run --frozen aidw --repo /tmp/aidw-g12-ws/control prompt 03 E4 E4.1 --no-fetch
echo "exit: $?"
```

**Expected observable result.** Exit `4`; stderr reports the incomplete predecessor condition
(`earlier tasks in the same file are incomplete`) and does **not** contain `Design 42.7` or
the `refusing: cannot author` header. `runs list` still prints `no runs`.

**How to tell pass from fail.** Pass when the exit is `4` *and* the spec-gap text is absent —
that is the documented precedence (roadmap ordering is the first authority). Fail if the exit
is `3`, if both messages appear, or if a run/branch/worktree was created.

**Cost, permission or destructive warning.** None beyond the disposable scratch tree.

#### B3. `--dry-run` reports the gaps, plans normally and writes nothing

**Prerequisites.** Common setup completed, with a dangling citation in place (B2 leaves one:
`Design 42.7`). No Pi, no network.

**Command(s) or steps.**

```bash
uv run --frozen aidw --repo /tmp/aidw-g12-ws/control prompt 03 E4 E4.1 --dry-run
echo "exit: $?"
uv run --frozen aidw --repo /tmp/aidw-g12-ws/control runs list
git -C /tmp/aidw-g12-ws/bare.git branch --list '03-*'
test -e /tmp/aidw-g12-ws/control/docs/task-prompts/03-E4.1-prompt.md && echo "PROMPT FILE EXISTS" || echo "no prompt file"
```

**Expected observable result.** Exit `0`. Stdout carries, beside the predecessor note, a line
beginning ``[dry-run] cited spec sections for `E4.1` have problems:`` followed by the gap
`  Design 42.7 → design.md: no heading numbered §42.7`, and then still prints the normal plan —
including `branch-setup (planned): worktree add -b 03-E4.1`, a `stage:  task-prompt` line and
the tail `dry-run complete; Pi not invoked`. There is no early return at the dry-run split:
the plan is complete. `runs list` prints `no runs`; no `03-*` branch exists; the prompt file
check prints `no prompt file`.

**How to tell pass from fail.** Pass only when the exit is `0`, the `[dry-run]` gap note and
the full plan both appear, and nothing was written. Fail if the exit is `3` (a dry run must
never refuse), if the command stops after the note without printing the plan, if
`dry-run complete; Pi not invoked` is missing, or if any run/branch/prompt file exists.

**Cost, permission or destructive warning.** None: no writes, no Pi, no network.

#### B4. A hash-prefixed body line is prose, not a heading boundary

**Prerequisites.** Common setup completed. No Pi, no network. This scenario exercises the
recorded rule that only Markdown ATX headings delimit a section: a `#` run not followed by
whitespace (or end of line) is body prose, so a section whose only body line is `#not a
heading` is non-empty and must not be refused.

**Command(s) or steps.** Restore `## 9` with a hash-prefixed body line and a resolvable
roadmap entry, commit, and run the free dry run:

```bash
cat > /tmp/aidw-g12-ws/control/design.md <<'EOF'
# Design

## 9. Cited section

#not a heading, and this line is body prose.
EOF
cat > '/tmp/aidw-g12-ws/control/docs/tasks/03 - Manual Test.md' <<'EOF'
# Phase 3: Manual test

## Epic E4: Manual epic

- [ ] **E4.1. A feasibility target** per Design 9..
  - Done when: the cited section stays non-empty.
EOF
git -C /tmp/aidw-g12-ws/control add -A
git -C /tmp/aidw-g12-ws/control commit -qm "hash-prefixed body line"
uv run --frozen aidw --repo /tmp/aidw-g12-ws/control prompt 03 E4 E4.1 --dry-run
echo "exit: $?"
```

**Expected observable result.** Exit `0`; stdout carries
``[dry-run] no cited-spec-section problems for `E4.1`.`` — no `§9 is empty` gap is printed —
and the normal plan and `dry-run complete; Pi not invoked` tail still print. The build results
record the focused gate row `test_g12_hash_prefix_without_heading_space_is_section_body`
passing at tree `117f26ae9a50`.

**How to tell pass from fail.** Pass when the dry run reports no cited-spec problems and exits
`0`. Fail if it reports `§9 is empty` or any cited-spec gap (the false refusal this heading
boundary prevents), or if it exits `3`.

**Cost, permission or destructive warning.** None: dry run only, no writes, no Pi, no network.

#### B5. All cited sections resolve — dry-run mirror note, then the optional real run

**Prerequisites.** Common setup completed; a target repo whose citation resolves (restore the
seed state: `Design 9` against a non-empty `## 9`). The dry-run part needs no Pi. The optional
real run needs Pi installed and whatever credentials your Pi configuration requires, a clean
control worktree on `main`, and — because branch setup creates a real task worktree — the
supported bare-plus-sibling layout that the common setup already builds.

**Command(s) or steps.** Restore the resolvable state and commit it:

```bash
cat > /tmp/aidw-g12-ws/control/design.md <<'EOF'
# Design

## 9. Cited section

Prose that makes the section non-empty.
EOF
cat > '/tmp/aidw-g12-ws/control/docs/tasks/03 - Manual Test.md' <<'EOF'
# Phase 3: Manual test

## Epic E4: Manual epic

- [ ] **E4.1. A feasibility target** per Design 09..
  - Done when: the cited section stays non-empty.
EOF
git -C /tmp/aidw-g12-ws/control add -A
git -C /tmp/aidw-g12-ws/control commit -qm "restore resolvable citations"
```

Free dry run first (also proves the zero-padded `Design 09` matches `## 9`):

```bash
uv run --frozen aidw --repo /tmp/aidw-g12-ws/control prompt 03 E4 E4.1 --dry-run
echo "exit: $?"
```

Then the paid run, only if you accept the spend:

```bash
uv run --frozen aidw --repo /tmp/aidw-g12-ws/control prompt 03 E4 E4.1 --no-fetch
echo "exit: $?"
```

**Expected observable result.** The dry run exits `0`, prints
``[dry-run] no cited-spec-section problems for `E4.1`.``, still prints the plan and the
`dry-run complete; Pi not invoked` tail. The real run prints no `refusing: cannot author`
header and no gap lines, proceeds to the `task-prompt` stage (`stage:  task-prompt` / the
author's Pi invocation), and creates the `03-E4.1` branch and worktree. The build results
record this behaviour only as a test row (`test_g12_all_cited_sections_present_and_non_empty_proceeds_to_the_author`,
passing in the recorded `g12-focused` gate and in the full suite, with the stages faked); the
build results contain no real Pi run.

**How to tell pass from fail.** For the dry run, pass when the "no cited-spec-section
problems" note appears with exit `0` and nothing is written. For the real run, pass when the
preflight is cleared — no refusal text and the author stage starts — which is the
discriminator; stop there. Fail if the refusal appears (a false positive from zero-padding),
if the run stops before any stage, or if the plan says "problems" when the section is present
and non-empty.

**Cost, permission or destructive warning.** The real run spends a Pi authoring run (the
roadmap entry records a blocked authoring run costing about `$0.36`) and may continue into
review and fix stages, which cost more; press `Ctrl-C` once the author stage starts if you
only need the preflight result. It uses your Pi credentials and writes a branch, worktree,
run state and eventually a prompt file **inside `/tmp/aidw-g12-ws` only**. `--no-fetch` keeps
it off the network.

#### B6. `--resume` does not repeat the cited-spec check

**Prerequisites.** A prompt run for branch `03-E4.1` must already exist in the scratch
workspace and have been interrupted or blocked at/after the author stage (for example by
`Ctrl-C` during B5's real run, or by an author `blocked:` line). **This guide cannot
manufacture that state without a paid Pi run**; if B5 was not run, skip this scenario and
record it as not exercised. A clean control worktree is still required to reach the preflight
at all.

**Command(s) or steps.** Remove the cited file, commit the removal, then resume:

```bash
git -C /tmp/aidw-g12-ws/control rm -q design.md
git -C /tmp/aidw-g12-ws/control commit -qm "drop the cited spec after the run started"
uv run --frozen aidw --repo /tmp/aidw-g12-ws/control prompt 03 E4 E4.1 --resume --yes --no-fetch
echo "exit: $?"
uv run --frozen aidw --repo /tmp/aidw-g12-ws/control runs list
```

**Expected observable result.** The resume continues the existing run: stderr contains **no**
`refusing: cannot author` header and no `Design 9 → design.md: file not found` gap, and
`runs list` still shows the same single run id it showed before the resume (the run is
continued, not replaced). The build results record this as a test row
(`test_g12_takeover_does_not_repeat_the_cited_spec_check`, passing in the recorded
`g12-focused` gate and in the full suite); they contain no hand-run resume.

**How to tell pass from fail.** Pass when the resume is **not** refused by the cited-spec
check even though `design.md` is now gone, and no second run id appears. Fail if the refusal
text appears (the check was repeated on a takeover) or a new run id was minted.

**Cost, permission or destructive warning.** Resuming continues a Pi-driven run and therefore
spends model calls; `--no-fetch` avoids network. The `design.md` removal is destructive only
inside `/tmp/aidw-g12-ws`. The precondition may be unavailable — see the prerequisite and
section 4.

### Group C — Browser UI flows

None. No changed file, build-results row or task-prompt statement names a browser screen,
route or web flow; the change is a Python preflight plus documentation. No scenario is
listed because there is no evidence of such a surface.

### Group D — External actions (cloud providers, deployed stacks)

None. No changed file, build-results row or task-prompt statement names a cloud account,
credential scope, bucket, role, ARN, deployed stack or paid infrastructure command. The only
spend this change can influence is the Pi authoring run avoided by the refusal (B5/B6).

## 3. Teardown

The Group B scenarios create state **only** under `/tmp/aidw-g12-ws` (the seed repo, the bare
repository, the control worktree, any `03-E4.1` worktree, run state under
`/tmp/aidw-g12-ws/.aidw/state/`, and any generated prompt file). Remove it all:

```bash
uv run --frozen aidw --repo /tmp/aidw-g12-ws/control worktree list
rm -rf /tmp/aidw-g12-ws
```

The `worktree list` is a read-only last look (it will show the control worktree and, if B5/B6
ran, the `03-E4.1` worktree); deleting the parent directory is sufficient because the bare
repository lives inside it. If you ran B5/B6 in a *real* target repository instead of the
scratch tree, undo only what that run created, using the toolkit's own commands: run
`aidw worktree remove 03-E4.1` with `--repo` pointing at that target (add `--force` only if you
accept discarding its uncommitted changes) and delete the `03-E4.1` branch you created — never
touch unrelated branches or worktrees.

The Group A commands create nothing: `uv sync --frozen` reuses the checkout's existing
`.venv`, the tests use temporary directories and clean up after themselves, and
`doctor`/`prompts check`/`agents validate`/`tasks --show`/`git diff --check` are read-only, and
`git diff main -- 'docs/tasks/05 - Pipeline efficiency.md'` only inspects the tree. The scratch git
identity (`user.name`/`user.email`) was set locally inside `/tmp/aidw-g12-ws/seed` and
disappears with it; no global git configuration or environment variable was changed. If the
scratch workspace is already gone, there is nothing left to undo.

## 4. Could not be exercised in this environment

- **A real Pi authoring run (B5, B6).** Requires Pi installed, working credentials and model
  spend, and can cascade into review/fix stages. A normal developer environment may have Pi,
  but this guide was written without executing it; only a machine with the operator's Pi
  credentials can exercise it. The build results record the equivalent behaviour as *tests
  with the stages faked* (`test_g12_all_cited_sections_present_and_non_empty_proceeds_to_the_author`,
  `test_g12_takeover_does_not_repeat_the_cited_spec_check`), not as a real Pi run.
- **The `--resume` precondition (B6).** Producing a resumable prompt run for `03-E4.1`
  requires a real (paid) authoring run or an author `blocked:` line; a hand environment
  without Pi cannot create it, so B6 stays conditional and, without B5, unexercised.
- **Byte-identical `P2` evidence bundle output.** The change factors the citation enumeration
  into `_cited_specs` and its non-goals require the bundle's rendered text to stay unchanged.
  The build results now record a unit-test row for exactly that
  (`test_g12_shared_citation_enumeration_preserves_rendering_and_deduplication`, passing in
  `g12-focused` at tree `117f26ae9a50`), but observing the rendered bundle inside a real run
  means reaching `task-review-1` and reading the run's `stages/<stage>.evidence.md`, which
  needs a paid Pi review run; this guide does not exercise it.
- **Lint — recorded `unverified`.** The build results mark the lint row **unverified** with
  the reason that no linter is configured (`AGENTS.md` lists the gates and `design.md` §15
  says pytest is the only verification). This guide cannot exercise a gate that does not
  exist, and does not treat its absence as a pass.
- **Build — recorded `unverified`.** The build results mark the build row **unverified** with
  the reason that no build command is named by `AGENTS.md` or `aidw/conventions.md`, and that
  packaging is exercised inside the suite by `tests/test_packaging.py`. Same treatment: not
  exercised here, not counted as a pass.
- **A pull request.** The build results record that no PR exists for `05-G1.2`
  (`gh pr view 05-G1.2` reports no pull requests). Any PR-level review, CI or merge check is
  therefore unavailable to this guide; the `/pr` stage owns delivery.
- **The earlier red tree.** The build results' Deviations section records that an earlier
  recording of this stage, against tree `5a4c53219231`, observed the suite red on
  `test_g12_hash_prefix_without_heading_space_is_section_body`, and that the current
  implementation's `_heading_level` requires whitespace after the `#` run. The current
  recorded outcome is green at tree `117f26ae9a50`; this guide exercises that current
  behaviour (A1, B4) and cannot re-verify the superseded trees.
- **Browser, cloud and deployed-stack checks.** Not exercisable because none is touched by this
  change (see Groups C and D); there is no environment that would add coverage here.
