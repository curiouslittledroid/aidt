# Integration-test guide — G1.3: resolve `Design N` citations against a repo-declared spec directory

## 1. What this guide covers

This is a **hand-run procedure** for branch `05-G1.3`, which adds the optional
`paths.specs_dir` config key and makes `aidw prompt`'s cited-spec preflight resolve a
`Design N` citation against a numbered spec document in that directory instead of always
against section `N` of a root `design.md` (design.md §§8.1, 11, 12.1, §17 row Z22;
`aidw/target_config.py`, `aidw/workflows/prompt.py`, `aidw/doctor.py`). The procedure walks
the repository's own gates (the suite the build results record as green on the current tree,
after an earlier tree's recorded failure), the `aidw config show` and `aidw doctor` surfaces
(the new `paths.specs_dir` leaf and its advisory `specs dir` check), and the `aidw prompt`
preflight in specs mode: canonical-number resolution, the flat scan, zero/two-candidate gaps,
the merged citation window, per-occurrence claims and pair-level dedupe, the `§5.3A` letter
rule, the document-level bare citation, the byte-identical unset channel, the exit-3 refusal
with its remedy line, and the evidence bundle.
**Nothing in this guide has been executed by the toolkit**: this is an instruction document.
The build results beside it (`build-results.md`) are the recorded evidence. Where they record
a failure or mark a row `unverified`, this guide repeats that state with the recorded reason
rather than predicting green.

There are no browser-UI or external (cloud-provider) scenarios in this change: no changed
file, build-results row or task-prompt statement names a web screen, route, deployed stack,
cloud account, bucket, role or ARN. Those groups are declared empty below, not omitted by
accident.

## 2. Scenarios

### Group A — The repository's own tooling (the `aidt` checkout)

#### A1. Install and the full suite (the earlier recorded failure is superseded)

**Prerequisites.** The `aidt` checkout on branch `05-G1.3` (the change set may be uncommitted:
the build results record it as working-tree modifications). `uv` installed; network access for
`uv sync --frozen` unless the environment is already populated. No credentials, no target
repository, no Pi.

**Command(s) or steps.** From the `aidt` checkout root:

```bash
uv sync --frozen
echo "sync exit: $?"
uv run --frozen pytest
echo "pytest exit: $?"
```

**Expected observable result.** `uv sync --frozen` exits 0 (the build results record
`Checked 19 packages in 1ms`). The suite is **green**: the build results cite
`2558 passed in 55.88s` for tree `2efae543353d` from the recorded `suite` gate —
`reused: gate 'suite' passed for tree 2efae543353d at 2026-11-22T02:50:20Z by stage
'update-traceability' (2558 passed in 55.88s) [scope excludes: docs/architecture,
docs/implementation-results, docs/task-prompts, docs/tasks]` — with no failure line. Their
Deviations section records that the tree advanced during recording: an earlier recording of
the same stage ran the suite against tree `e241ed5eba82` and observed
`1 failed, 2556 passed`, failing on
`tests/test_prompt_workflow.py::test_g13_repeated_same_design_token_uses_each_token_window`;
the current tree's own gates record that test passing on its own (`1 passed, 292 deselected`,
stage `test`) and the full suite passing. Do not expect the earlier failure at this tree.

**How to tell pass from fail.** Pass when the install exits 0 and the suite exits 0 showing
`2558 passed` with no failure, error or collection-error line. Fail on any failing test, on a
collection error, on a non-zero `uv sync` exit, or on a test count that differs at the same
tree. A failure of
`test_g13_repeated_same_design_token_uses_each_token_window` is a **regression** against the
recorded pass at tree `2efae543353d`, not the recorded state — do not explain it away as the
superseded earlier failure.

**Cost, permission or destructive warning.** None: local install and local tests, no spend, no
external write. `uv sync --frozen` will not update `uv.lock`; a lock mismatch is a failure, not
an update.

#### A2. Environment gates: doctor, prompts, agents, whitespace

**Prerequisites.** A1's install has completed. No Pi invocation occurs in any of these
commands.

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

**Expected observable result.** Recorded outcomes: `doctor` — exit 0,
`24 checks: 0 failed, 2 warning(s)` (a dirty working tree on `05-G1.3`; a missing
`.mcp.json`), and its `specs dir` line is an **OK** reading
``[  ok  ] specs dir … `paths.specs_dir` unset; `Design N` resolves against the root design.md``
(the `aidt` checkout has a root `design.md` and no `aidw/config.yaml`, so nothing is
declared). `prompts check` — exit 0, `resolved repo prompts: 0 error(s), 0 warning(s)`.
`agents validate --strict` — exit 0, `11 agent config(s): 0 error(s), 0 warning(s)`.
`git diff --check` — exit 0 with no output.

**How to tell pass from fail.** Fail on any non-zero exit, on a `failed` count above 0 in
`doctor`, on an error count other than `0 error(s)` in `prompts check`/`agents validate`, or on
any output from `git diff --check`. A different **warning** set in `doctor` is environmental,
not a failure; a `specs dir` line at `warn` or `fail` on the `aidt` checkout is a failure of
this change, because that tree has a root `design.md`.

**Cost, permission or destructive warning.** None. All four commands are read-only.

#### A3. The G1.3 tests and the documentation drift pins

**Prerequisites.** A1's install has completed. Python only; no Pi.

**Command(s) or steps.**

```bash
uv run --frozen pytest tests/test_prompt_workflow.py -k g13
echo "g13 exit: $?"
uv run --frozen pytest \
  tests/test_doctor.py tests/test_target_config.py tests/test_target_repo_config_doc.py \
  tests/test_cli.py tests/test_roadmap_format.py tests/test_design_doc.py
echo "pins exit: $?"
```

**Expected observable result.** Both selections pass. The build results cite this run's
recorded gates: `gate g13: passed (tree 2efae543353d, stage test, 2026-11-22T02:46:20Z,
2.34s, 25 passed, 734 deselected)` and, for the formerly failing case alone,
`gate smoke: passed (tree 2efae543353d, stage test, 2026-11-22T02:46:15Z, 1 passed,
292 deselected)`. The drift-pin files — `test_target_config.py`,
`test_target_repo_config_doc.py`, `test_cli.py`, `test_roadmap_format.py`,
`test_design_doc.py`, `test_doctor.py` — passed inside the same full-suite gate, whose result
is `2558 passed`.

**How to tell pass from fail.** Pass when both selections exit 0 with no failure line. Fail —
as a new result — on any failing g13 or pin test (including
`test_g13_repeated_same_design_token_uses_each_token_window`, which the recorded tree passes),
or if a drift pin reports a missing/duplicated §17 `Z22` row, a `specs_dir` default other than
`unset`, or a `paths.*` leaf-set mismatch.

**Cost, permission or destructive warning.** None: local test runs only.

### Group B — Custom CLI: `aidw config show`, `aidw doctor` and the `aidw prompt` preflight

#### B0. Common setup for every Group B scenario

Run this once, from the `aidt` checkout. It builds a disposable target repository in the
supported layout (a bare repository plus sibling worktrees, design §3.2) under
`/tmp/aidw-g13-ws`, declares `paths.specs_dir: docs/specs`, and seeds three numbered spec
documents. `schema_version: 1` plus the declared `paths.specs_dir` is the minimal config from
`docs/target-repo-config.md`; `paths.roadmap_dir`, `paths.task_prompts_dir`,
`paths.implementation_results_dir` and `paths.build_results_template` are the default
read-paths `aidw prompt` validates, so the seed creates them.

```bash
rm -rf /tmp/aidw-g13-ws
mkdir -p /tmp/aidw-g13-ws/seed/aidw \
         /tmp/aidw-g13-ws/seed/docs/tasks \
         /tmp/aidw-g13-ws/seed/docs/task-prompts \
         /tmp/aidw-g13-ws/seed/docs/implementation-results \
         /tmp/aidw-g13-ws/seed/docs/specs
cd /tmp/aidw-g13-ws/seed
git init -q -b main
git config user.name "AIDW G1.3 Manual"
git config user.email "aidw-g13-manual@example.invalid"
cat > aidw/config.yaml <<'EOF'
schema_version: 1
paths:
  specs_dir: docs/specs
EOF
printf '# Build results template\n' > docs/implementation-results/TEMPLATE.md
: > docs/task-prompts/.gitkeep
cat > 'docs/tasks/03 - Manual Test.md' <<'EOF'
# Phase 3: Manual test

## Epic E4: Manual epic

- [ ] **E4.1. A specs-mode target** (Design 11 §5.3)
  - Done when: the cited section resolves inside the spec document.
EOF
cat > 'docs/specs/Design 4 - Story Manager.md' <<'EOF'
# Story Manager

## 5.3 Sub-part

Prose.
EOF
cat > 'docs/specs/Design 11 - Foo.md' <<'EOF'
# Foo

## 5.3 Sub-part

Prose.
EOF
cat > 'docs/specs/Design 20.1 - Condition Language.md' <<'EOF'
# Condition Language

## 2. Effect

Prose.
EOF
git add -A
git commit -qm "seed the manual target repo"
git clone --bare -q /tmp/aidw-g13-ws/seed /tmp/aidw-g13-ws/bare.git
git -C /tmp/aidw-g13-ws/bare.git worktree add -q /tmp/aidw-g13-ws/control main
cd - >/dev/null
```

Sanity-check the target before any scenario (from the `aidt` checkout):

```bash
uv run --frozen aidw --repo /tmp/aidw-g13-ws/control tasks --phase 03
uv run --frozen aidw --repo /tmp/aidw-g13-ws/control config show
```

`tasks --phase 03` lists `E4.1`; `config show` ends with a leaf line
`paths.specs_dir: docs/specs (config)` beside the defaulted leaves and
`repo.base_branch` = `main`.

**Reset snippet — re-run before each Group B scenario** so one scenario's mutation does not
leak into the next. It recreates the seed's roadmap entry and spec documents and commits the
result:

```bash
cd /tmp/aidw-g13-ws/control
git checkout -q main
cat > aidw/config.yaml <<'EOF'
schema_version: 1
paths:
  specs_dir: docs/specs
EOF
rm -f design.md
rm -rf docs/migration
rm -rf docs/specs
mkdir -p docs/specs
cat > 'docs/tasks/03 - Manual Test.md' <<'EOF'
# Phase 3: Manual test

## Epic E4: Manual epic

- [ ] **E4.1. A specs-mode target** (Design 11 §5.3)
  - Done when: the cited section resolves inside the spec document.
EOF
cat > 'docs/specs/Design 4 - Story Manager.md' <<'EOF'
# Story Manager

## 5.3 Sub-part

Prose.
EOF
cat > 'docs/specs/Design 11 - Foo.md' <<'EOF'
# Foo

## 5.3 Sub-part

Prose.
EOF
cat > 'docs/specs/Design 20.1 - Condition Language.md' <<'EOF'
# Condition Language

## 2. Effect

Prose.
EOF
git add -A
git commit -qm "reset to seed state"
cd - >/dev/null
```

Every scenario below is run from the `aidt` checkout: each fenced block starts there, `cd`s
into the scratch tree only to mutate it, and the trailing `cd - >/dev/null` returns to the
`aidt` checkout where `uv run --frozen` resolves the project. The cheap check for every
preflight case is `--dry-run`, which reports the same gaps as notes, writes nothing and
spends nothing; only B9 and B10 need a real (non-dry-run) invocation.

#### B1. `aidw config show` reports the new leaf with its provenance

**Prerequisites.** B0's common setup completed; the reset snippet has been run (so
`paths.specs_dir` is declared).

**Command(s) or steps.**

```bash
uv run --frozen aidw --repo /tmp/aidw-g13-ws/control config show | grep 'paths.specs_dir'
```

Then, for the unset state, remove the `paths:` block from the scratch config and repeat:

```bash
cd /tmp/aidw-g13-ws/control
printf 'schema_version: 1\n' > aidw/config.yaml
git add -A && git commit -qm "drop the declared specs dir"
cd - >/dev/null
uv run --frozen aidw --repo /tmp/aidw-g13-ws/control config show | grep 'paths.specs_dir'
```

**Expected observable result.** Declared: the line `paths.specs_dir: docs/specs (config)`.
Unset: the line `paths.specs_dir: unset` with no source in parentheses (an unset leaf prints
`unset` and no source). The `--json` form of the same command carries `"paths.specs_dir":
{"value": null}` for the unset state.

**How to tell pass from fail.** Pass when the declared leaf shows the value **and** the
`config` provenance, and the unset leaf shows exactly `unset`. Fail if the leaf is absent
(the field is not wired into the resolved config), if an unset leaf shows a seeded default
(`specs_dir` must not be in `TOOLKIT_DEFAULTS`), or if a declared leaf reports `default`.

**Cost, permission or destructive warning.** None: reads the scratch config; the edits are
confined to `/tmp/aidw-g13-ws`.

#### B2. `aidw doctor`'s `specs dir` check is advisory `WARN`, never `FAIL`

**Prerequisites.** B0's common setup completed; `aidw doctor` on the scratch repo. The
`aidt` checkout's own doctor is not the subject here.

**Command(s) or steps.** From the `aidt` checkout, for each of the five states: apply the
mutation in `/tmp/aidw-g13-ws/control`, commit it, then run doctor and capture the exit code.

1. **Healthy: a declared directory holding a numbered document.**

   ```bash
   # reset snippet, then:
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control doctor
   echo "exit: $?"
   ```

2. **Declared but missing.**

   ```bash
   cd /tmp/aidw-g13-ws/control
   rm -rf docs/specs
   git add -A && git commit -qm "remove the specs dir"
   cd - >/dev/null
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control doctor
   echo "exit: $?"
   ```

3. **Declared but not a directory.**

   ```bash
   cd /tmp/aidw-g13-ws/control
   printf 'not a directory\n' > docs/specs
   git add -A && git commit -qm "make the specs dir a file"
   cd - >/dev/null
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control doctor
   echo "exit: $?"
   ```

4. **Declared and a directory, but no numbered spec document.** The files deliberately carry
   no `Design <number> - ` prefix, so a laxer `Design *.md` glob would wrongly report OK:

   ```bash
   cd /tmp/aidw-g13-ws/control
   rm -f docs/specs
   mkdir -p docs/specs
   printf 'Notes.\n' > docs/specs/notes.md
   printf 'Draft.\n' > 'docs/specs/Design draft.md'
   git add -A && git commit -qm "only non-conforming filenames"
   cd - >/dev/null
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control doctor
   echo "exit: $?"
   ```

5. **Nothing declared and no root `design.md`.**

   ```bash
   cd /tmp/aidw-g13-ws/control
   printf 'schema_version: 1\n' > aidw/config.yaml
   git add -A && git commit -qm "declare nothing"
   cd - >/dev/null
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control doctor
   echo "exit: $?"
   ```

**Expected observable result.** In every case the report line is shaped
`[  ok  ] specs dir …` or `[ warn ] specs dir …` (the name is padded; the status word is
`ok`/`warn`/`fail` inside brackets), and the process exits **0** in all five. Case 1: the detail ends
`N numbered spec document(s)` — with the reset seed, `3 numbered spec document(s)` (the
`Design 4`, `Design 11` and `Design 20.1` files). Case 2: the detail names
`` `paths.specs_dir` `` and an **absolute** path ending `docs/specs` and says it `does not
exist`. Case 3: the same path with `is not a directory`. Case 4: `holds no numbered spec
document`. Case 5: `` `paths.specs_dir` is unset and there is no root `design.md` ``. Every
WARN detail also carries the remedy sentence naming `paths.specs_dir` and the root
`design.md` alternative. The build results record the recorded toolkit-repo doctor run as
`24 checks: 0 failed, 2 warning(s)` with this check at OK.

**How to tell pass from fail.** Pass only when each trigger state is a **`[ warn ]`** line,
the exit code is exactly `0`, and the `0 failed` summary is unchanged. Fail if any case says
`fail` or prints `failed,` above 0 (a missing optional directory must never fail the doctor),
if a WARN case says `ok`, or if the document-less case says `ok` (that is the doctor-local
predicate diverging from the resolver). A different WARN **count** is fine: the scratch
repository legitimately warns about its own environment.

**Cost, permission or destructive warning.** None: doctor is read-only; the mutations are
confined to `/tmp/aidw-g13-ws` and each is committed there.

#### B3. Canonical-number resolution, the flat scan, and zero/two-candidate gaps

**Prerequisites.** B0's common setup completed and the reset snippet run.

**Command(s) or steps.** For each case: apply the edit in `/tmp/aidw-g13-ws/control`, commit,
then run the free dry run from the `aidt` checkout and capture the exit code. The edit is the
roadmap entry's task line in every case.

1. **Zero padding is not a different document** — cite `Design 04` (the seed has
   `Design 4 - Story Manager.md` with `## 5.3`):

   ```bash
   cd /tmp/aidw-g13-ws/control
   printf '# Phase 3: Manual test\n\n## Epic E4: Manual epic\n\n- [ ] **E4.1. A specs-mode target** (Design 04 §5.3)\n  - Done when: the cited section resolves inside the spec document.\n' > 'docs/tasks/03 - Manual Test.md'
   git add -A && git commit -qm "cite Design 04"
   cd - >/dev/null
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --dry-run
   echo "exit: $?"
   ```

2. **A parent number never matches a sub-numbered filename** — cite `Design 20` while the
   seed holds only `Design 20.1 - Condition Language.md`:

   ```bash
   cd /tmp/aidw-g13-ws/control
   printf '# Phase 3: Manual test\n\n## Epic E4: Manual epic\n\n- [ ] **E4.1. A specs-mode target** (Design 20)\n  - Done when: the cited section resolves inside the spec document.\n' > 'docs/tasks/03 - Manual Test.md'
   git add -A && git commit -qm "cite Design 20"
   cd - >/dev/null
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --dry-run
   echo "exit: $?"
   ```

3. **Two candidates is no more resolvable than zero** — add a second `Design 7` document:

   ```bash
   cd /tmp/aidw-g13-ws/control
   printf '# Alpha\n\n## 1. One\n\nProse.\n' > 'docs/specs/Design 7 - Alpha.md'
   printf '# Beta\n\n## 1. One\n\nProse.\n' > 'docs/specs/Design 7 - Beta.md'
   printf '# Phase 3: Manual test\n\n## Epic E4: Manual epic\n\n- [ ] **E4.1. A specs-mode target** (Design 7)\n  - Done when: the cited section resolves inside the spec document.\n' > 'docs/tasks/03 - Manual Test.md'
   git add -A && git commit -qm "add an ambiguous pair"
   cd - >/dev/null
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --dry-run
   echo "exit: $?"
   ```

4. **The scan is flat, never recursive** — a nested numbered document does not count:

   ```bash
   cd /tmp/aidw-g13-ws/control
   mkdir -p docs/specs/nested
   printf '# Nested\n\nProse.\n' > 'docs/specs/nested/Design 8 - Nested.md'
   printf '# Phase 3: Manual test\n\n## Epic E4: Manual epic\n\n- [ ] **E4.1. A specs-mode target** (Design 8)\n  - Done when: the cited section resolves inside the spec document.\n' > 'docs/tasks/03 - Manual Test.md'
   git add -A && git commit -qm "nest a Design 8 document"
   cd - >/dev/null
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --dry-run
   echo "exit: $?"
   ```

**Expected observable result.** Every dry run exits **0** (a dry run never refuses) and
prints, beside the predecessor and clean-tree notes:

```text
[dry-run] cited spec sections for `E4.1` have problems:
  <gap line>
```

with these gap lines (the pinned strings from `tests/test_prompt_workflow.py`):

| Case | Gap line |
|---|---|
| 1 | none — the note is ``[dry-run] no cited-spec-section problems for `E4.1`.`` |
| 2 | `Design 20 → docs/specs: no spec document numbered 20` |
| 3 | `Design 7 → docs/specs: 2 spec documents numbered 7: Design 7 - Alpha.md, Design 7 - Beta.md` |
| 4 | `Design 8 → docs/specs: no spec document numbered 8` |

**How to tell pass from fail.** Pass when the exact gap line for the case appears (or, for
case 1, the no-problems note) and the exit code is `0`. Fail if case 1 reports a gap (zero
padding wrongly treated as a different document), if case 2 resolves to the sub-numbered file
or falls back to a root `design.md` (the gap must name `docs/specs`, never `design.md`), if the
ambiguity gap names only one candidate, or if case 4 finds the nested file.

**Cost, permission or destructive warning.** None: dry runs only, no Pi, no network, no
writes; the edits are confined to `/tmp/aidw-g13-ws` and are committed there.

#### B4. Citation windows: every `§` in the window, and pair-level dedupe

**Prerequisites.** B0's common setup completed and the reset snippet run.

**Command(s) or steps.**

1. **Two sections in one window, both checked.** Set the task line to
   `(Design 11 §5.3 and §5, EXTRACTION.md §3.1)` and create that doc-ref file:

   ```bash
   cd /tmp/aidw-g13-ws/control
   mkdir -p docs/migration
   printf '# Extraction\n\n## 3.1 Section\n\nProse.\n' > docs/migration/EXTRACTION.md
   printf '# Phase 3: Manual test\n\n## Epic E4: Manual epic\n\n- [ ] **E4.1. A specs-mode target** (Design 11 §5.3 and §5, EXTRACTION.md §3.1)\n  - Done when: the cited section resolves inside the spec document.\n' > 'docs/tasks/03 - Manual Test.md'
   git add -A && git commit -qm "two sections in one Design window"
   cd - >/dev/null
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --dry-run
   echo "exit: $?"
   ```

2. **A `§` after a `Design N` belongs to that citation, not to the next `.md` token.** Point
   the Design window's section at a number the spec document does not carry, and give the
   doc-ref file the section the Design citation names:

   ```bash
   cd /tmp/aidw-g13-ws/control
   printf '# Foo\n\n## 2. Intro\n\nProse.\n' > 'docs/specs/Design 11 - Foo.md'
   printf '# Extraction\n\n## 5.3 Leaked\n\nProse.\n\n## 3.1 Real\n\nProse.\n' \
     > docs/migration/EXTRACTION.md
   printf '# Phase 3: Manual test\n\n## Epic E4: Manual epic\n\n- [ ] **E4.1. A specs-mode target** (Design 11 §5.3, EXTRACTION.md §3.1)\n  - Done when: the cited section resolves inside the spec document.\n' > 'docs/tasks/03 - Manual Test.md'
   git add -A && git commit -qm "design window precedes the doc token"
   cd - >/dev/null
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --dry-run
   echo "exit: $?"
   ```

3. **The same pair cited twice is one pair.** Restore a conforming task line and cite the
   same section through both spellings (`Design 11` and `Design 011`):

   ```bash
   cd /tmp/aidw-g13-ws/control
   printf '# Foo\n\n## 5.3 Sub-part\n\nProse.\n' > 'docs/specs/Design 11 - Foo.md'
   printf '# Phase 3: Manual test\n\n## Epic E4: Manual epic\n\n- [ ] **E4.1. A specs-mode target** (Design 11 §5.3, Design 011 §5.3)\n  - Done when: the cited section resolves inside the spec document.\n' > 'docs/tasks/03 - Manual Test.md'
   git add -A && git commit -qm "cite the same pair twice"
   cd - >/dev/null
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --dry-run
   echo "exit: $?"
   ```

**Expected observable result.** All three dry runs exit `0`. Case 1 prints one gap,
`  Design 11 → docs/specs/Design 11 - Foo.md: no heading numbered §5` — `§5.3` resolves,
`§5` does not, and the doc-ref `EXTRACTION.md §3.1` (which does exist) produces no gap.
Case 2 prints one gap,
`  Design 11 → docs/specs/Design 11 - Foo.md: no heading numbered §5.3` — the `§5.3` is
checked **inside the spec document**, so a `§5.3` heading in `EXTRACTION.md` does not satisfy
it. Case 3 prints
``[dry-run] no cited-spec-section problems for `E4.1`.`` — the same `(document, 5.3)` pair
was enumerated once.

**How to tell pass from fail.** Pass when the exact gap line (or the no-problems note) for
each case appears and the exit code is `0`. Fail if case 1 misses the `§5` gap (the window
stops at the first `§`), if case 2 reports `EXTRACTION.md` as satisfied by its own `## 5.3`
(the two scans were not merged), or if case 3 reports a gap (dedupe keyed on the token
spelling rather than the pair — note that `Design 011` and `Design 11` are one document).

**Cost, permission or destructive warning.** None: dry runs only, no writes beyond the scratch
tree.

#### B5. One claim per occurrence: a repeated or bare `Design` token

**Prerequisites.** B0's common setup completed and the reset snippet run. The seed's
`Design 11 - Foo.md` carries `## 5.3` with prose. This scenario exercises the per-occurrence
rule the build results record as a decision row ("per-**occurrence** claims, not per-unique-token
claims") and as the fixed `test_g13_repeated_same_design_token_uses_each_token_window` case.

**Command(s) or steps.**

1. **The same design number cited twice with two sections.** The roadmap parser de-duplicates
   a repeated token spelling into one citation label, so the requirement is that both
   occurrences' windows are still walked:

   ```bash
   cd /tmp/aidw-g13-ws/control
   printf '# Phase 3: Manual test\n\n## Epic E4: Manual epic\n\n- [ ] **E4.1. A specs-mode target** (Design 11 §5.3; Design 11 §5)\n  - Done when: the cited section resolves inside the spec document.\n' > 'docs/tasks/03 - Manual Test.md'
   git add -A && git commit -qm "repeat the Design 11 token with a second section"
   cd - >/dev/null
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --dry-run
   echo "exit: $?"
   ```

2. **A bare occurrence beside a sectioned one.** Make the spec document headings-only so both
   claims have something to report, then cite the same number once bare and once with `§5.3`:

   ```bash
   cd /tmp/aidw-g13-ws/control
   printf '# Foo\n\n## 5.3 Sub-part\n' > 'docs/specs/Design 11 - Foo.md'
   printf '# Phase 3: Manual test\n\n## Epic E4: Manual epic\n\n- [ ] **E4.1. A specs-mode target** (Design 11; Design 11 §5.3)\n  - Done when: the cited section resolves inside the spec document.\n' > 'docs/tasks/03 - Manual Test.md'
   git add -A && git commit -qm "bare and sectioned occurrences"
   cd - >/dev/null
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --dry-run
   echo "exit: $?"
   ```

**Expected observable result.** Both dry runs exit `0` and print the problems note
``[dry-run] cited spec sections for `E4.1` have problems:``. Case 1 prints one gap,
`  Design 11 → docs/specs/Design 11 - Foo.md: no heading numbered §5` — `§5.3` resolves and
`§5` does not, so the second occurrence's window was enumerated while the shared pair was
checked once. Case 2 prints **two** gaps, in this order:

```text
  Design 11 → docs/specs/Design 11 - Foo.md: the document is empty
  Design 11 → docs/specs/Design 11 - Foo.md: §5.3 is empty
```

The bare occurrence keeps its document-level claim (the headings-only document has no
non-blank, non-heading line) and the sectioned occurrence keeps its section claim (`## 5.3`
has no body), so neither claim swallows the other. The build results record both behaviours as
passing tests (`test_g13_repeated_same_design_token_uses_each_token_window` and
`test_g13_a_bare_occurrence_keeps_its_document_claim_beside_a_sectioned_one`) inside the
recorded `g13` gate (`25 passed, 734 deselected`) and the green full suite. They also record
that this same case **failed** on the earlier tree `e241ed5eba82`
(`1 failed, 2556 passed`) and passes on the current tree `2efae543353d`; the recorded failure
is superseded by the gate store's observation of the current tree, not by anything this guide
ran.

**How to tell pass from fail.** Pass when case 1 reports exactly the `§5` gap and case 2
reports both the "the document is empty" and the "§5.3 is empty" gaps, in that order. Fail if
case 1 reports no gap at all (only the first occurrence's window was enumerated — the failure
the build results record for tree `e241ed5eba82`), if case 2 reports only one of its two gaps
(one occurrence swallowed the other), if a gap names a different document, or if either dry run
exits `3` (a dry run must never refuse).

**Cost, permission or destructive warning.** None: two dry runs, no Pi, no network, no writes
beyond the scratch tree.

#### B6. A trailing capital letter checks only its parent section

**Prerequisites.** B0's common setup completed and the reset snippet run. The seed's
`Design 11 - Foo.md` carries `## 5.3` and no `## 5.3A` heading.

**Command(s) or steps.**

```bash
cd /tmp/aidw-g13-ws/control
python3 - <<'PY'
from pathlib import Path
path = Path('docs/tasks/03 - Manual Test.md')
path.write_text(path.read_text().replace('(Design 11 §5.3)', '(Design 11 §5.3A)'))
PY
git add -A && git commit -qm "cite a lettered sub-part"
cd - >/dev/null
uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --dry-run
echo "exit: $?"
```

**Expected observable result.** Exit `0`; the note is
``[dry-run] no cited-spec-section problems for `E4.1`.`` — `§5.3A` was checked as `5.3`, which
exists and is non-empty. The builder records the same rule as a passing test pin
(`test_g13_a_trailing_capital_letter_checks_only_its_parent_section`).

**How to tell pass from fail.** Pass when no gap is reported and the exit is `0`. Fail if a
gap names a lettered form such as `§5.3A` (the false refusal the rule prevents), or if the
`5.3` section is reported missing.

**Cost, permission or destructive warning.** None: dry run only.

#### B7. A bare `Design N` is a document-level claim (exists and holds content)

**Prerequisites.** B0's common setup completed and the reset snippet run.

**Command(s) or steps.** Three cases, each with the task line citing a bare `Design N` (no
`§` in its window) and one spec document added:

```bash
cd /tmp/aidw-g13-ws/control
printf '# Story\n\nProse, no numbered heading.\n' > 'docs/specs/Design 20 - Story.md'
printf '' > 'docs/specs/Design 21 - Empty.md'
printf '# Design 22\n\n## 1. One\n\n### 1.1 Two\n' > 'docs/specs/Design 22 - Headings.md'
python3 - <<'PY'
from pathlib import Path
path = Path('docs/tasks/03 - Manual Test.md')
path.write_text(path.read_text().replace('(Design 11 §5.3)', '(Design 20)'))
PY
git add -A && git commit -qm "bare citation: a document with prose"
cd - >/dev/null
uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --dry-run
echo "exit: $?"

cd /tmp/aidw-g13-ws/control
python3 - <<'PY'
from pathlib import Path
path = Path('docs/tasks/03 - Manual Test.md')
path.write_text(path.read_text().replace('(Design 20)', '(Design 21)'))
PY
git add -A && git commit -qm "bare citation: an empty document"
cd - >/dev/null
uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --dry-run
echo "exit: $?"

cd /tmp/aidw-g13-ws/control
python3 - <<'PY'
from pathlib import Path
path = Path('docs/tasks/03 - Manual Test.md')
path.write_text(path.read_text().replace('(Design 21)', '(Design 22)'))
PY
git add -A && git commit -qm "bare citation: a headings-only document"
cd - >/dev/null
uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --dry-run
echo "exit: $?"
```

**Expected observable result.** All three exit `0`. Case 1 (prose but no `## 20` heading) has
**no** gap — a bare citation is not a heading claim, so the note is
``[dry-run] no cited-spec-section problems for `E4.1`.``. Case 2 prints
`  Design 21 → docs/specs/Design 21 - Empty.md: the document is empty`. Case 3 prints the same
message for `Design 22 - Headings.md` — a headings-only document documents nothing.

**How to tell pass from fail.** Pass when case 1 reports no problems and cases 2 and 3 report
exactly the "the document is empty" gap naming the resolved file. Fail if case 1 reports a gap
(a bare citation treated as a `## N` heading claim, the pre-G1.3 meaning), or if case 3 is
reported as having content (only a blank-line test, not the non-blank/non-heading rule).

**Cost, permission or destructive warning.** None: dry runs only.

#### B8. With `specs_dir` unset, the `Design N` channel is unchanged

**Prerequisites.** B0's common setup completed (then reset), plus a root `design.md`. This
scenario mutates the scratch repo's config to drop `paths.specs_dir`.

**Command(s) or steps.**

```bash
cd /tmp/aidw-g13-ws/control
printf 'schema_version: 1\n' > aidw/config.yaml
printf '# Design\n\n## 9. Test fixture\n\nRoot prose.\n' > design.md
python3 - <<'PY'
from pathlib import Path
path = Path('docs/tasks/03 - Manual Test.md')
path.write_text(path.read_text().replace('(Design 11 §5.3)', '(Design 9)'))
PY
git add -A && git commit -qm "unset the specs dir and add a root design"
cd - >/dev/null
uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --dry-run
echo "exit: $?"
uv run --frozen aidw --repo /tmp/aidw-g13-ws/control config show | grep 'paths.specs_dir'
```

Then renumber the root section so the citation cannot resolve:

```bash
cd /tmp/aidw-g13-ws/control
printf '# Design\n\n## 10. A different section\n\nRoot prose.\n' > design.md
git add -A && git commit -qm "renumber the cited root section"
cd - >/dev/null
uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --dry-run
echo "exit: $?"
```

**Expected observable result.** `config show` prints `paths.specs_dir: unset`. The first dry
run exits `0` with ``[dry-run] no cited-spec-section problems for `E4.1`.`` (section `9` of
the root `design.md` exists and is non-empty). The second exits `0` and prints
`  Design 9 → design.md: no heading numbered §9` — the document is the root `design.md` and the
section is the citation's own number, exactly the pre-G1.3 channel.

**How to tell pass from fail.** Pass when the unset leaf is `unset`, the resolved document in
the gap is `design.md` (never `docs/specs`), and the section is `§9`. Fail if the channel
falls back to the declared-by-seed specs directory (the config value leaked past `unset`), or
if a specs-mode document path appears in an unset-mode gap.

**Cost, permission or destructive warning.** None beyond the scratch tree; the seed's
`docs/specs` is left in place and deliberately must not be consulted.

#### B9. The exit-3 refusal and its `paths.specs_dir` remedy line

**Prerequisites.** B0's common setup completed; a **real** (non-dry-run) invocation, which
requires a clean control worktree on the base branch `main` (the reset snippet's commit
provides that) and no running prompt run for branch `03-E4.1`. No Pi is needed for the
refusal itself — the check runs before any stage — but if the gap does **not** appear the
invocation proceeds into the author stage and spends a Pi run.

**Command(s) or steps.**

1. **No `specs_dir` and no root `design.md` → remedy line.**

   ```bash
   cd /tmp/aidw-g13-ws/control
   printf 'schema_version: 1\n' > aidw/config.yaml
   rm -f design.md
   printf '# Phase 3: Manual test\n\n## Epic E4: Manual epic\n\n- [ ] **E4.1. A specs-mode target** (Design 9)\n  - Done when: the cited section resolves inside the spec document.\n' > 'docs/tasks/03 - Manual Test.md'
   git add -A && git commit -qm "no specs dir, no root design, cite Design 9"
   cd - >/dev/null
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --no-fetch
   echo "exit: $?"
   ```

2. **A section gap inside a present `design.md` → no remedy line.**

   ```bash
   cd /tmp/aidw-g13-ws/control
   printf '# Design\n\n## 10. A different section\n\nRoot prose.\n' > design.md
   git add -A && git commit -qm "root design present, cited section absent"
   cd - >/dev/null
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --no-fetch
   echo "exit: $?"
   ```

3. **No side effect after a refusal.**

   ```bash
   uv run --frozen aidw --repo /tmp/aidw-g13-ws/control runs list
   git -C /tmp/aidw-g13-ws/bare.git branch --list '03-*'
   test -e /tmp/aidw-g13-ws/control/docs/task-prompts/03-E4.1-prompt.md \
     && echo "PROMPT FILE EXISTS" || echo "no prompt file"
   test -d /tmp/aidw-g13-ws/03-E4.1 && echo "WORKTREE EXISTS" || echo "no task worktree"
   ```

**Expected observable result.** Both runs exit **3** and print on **stderr** the refusal
header, one indented gap, the closing repair line, and — case 1 only — a final `Remedy:` line:

```text
refusing: cannot author `E4.1` in `03 - Manual Test.md`; a cited spec section is missing, not uniquely locatable, or empty:
  Design 9 → design.md: file not found
Repair the cited spec or the roadmap entry — this check is deterministic and never guesses — then re-run `aidw prompt`.
Remedy: declare `paths.specs_dir` in `aidw/config.yaml`, naming the directory that holds the numbered spec documents (`Design <number> - <title>.md`), or commit the root `design.md` the `Design N` channel resolves against.
```

Case 2 keeps the same `Design 9` citation (case 1 committed it) and its gap is
`  Design 9 → design.md: no heading numbered §9` and its stderr contains **no** `Remedy:`
line. After both refusals, `runs list` prints `no runs`, the branch listing is empty, and the
two `test` checks print `no prompt file` / `no task worktree`.

**How to tell pass from fail.** Pass only when the exit code is exactly `3`, the gap text
matches the case, `Remedy:` appears in case 1 and is absent in case 2, and all four side-effect
checks are clean. Fail if case 2 carries a remedy line (the remedy must be scoped to the
whole-channel cause), if case 1 lacks it, if the exit is `2`/`4`/`0`, or if a run, branch,
prompt file or worktree exists afterwards.

**Cost, permission or destructive warning.** Cheap only as long as the refusal happens: exit 3
is reached before any Pi invocation, but an unexpectedly clean preflight continues into a paid
authoring run (and then review/fix rounds). `--no-fetch` keeps the invocation off the network.
The `design.md` and config edits are destructive only inside `/tmp/aidw-g13-ws`.

#### B10. The evidence bundle renders the resolved path and the checked sections

**Prerequisites.** B0's common setup completed and the reset snippet run; a **clean** control
worktree on `main`; **Pi installed and authenticated** — this is the only Group B scenario
that needs a real stage to run, because the bundle is written when a review stage is planned,
and there is no CLI that renders it without a run. This costs model spend.

**Command(s) or steps.** Make the entry cite a section that exists, then start a real run and
stop it once the review stage is announced:

```bash
cd /tmp/aidw-g13-ws/control
git status --short   # must be empty
cd - >/dev/null
uv run --frozen aidw --repo /tmp/aidw-g13-ws/control prompt 03 E4 E4.1 --no-fetch
```

Press `Ctrl-C` once the output names the `task-review-1` stage (the bundle is written before
that stage runs, so the prompt run need not finish). Then locate the bundle:

```bash
uv run --frozen aidw --repo /tmp/aidw-g13-ws/control config show | grep 'state root'
uv run --frozen aidw --repo /tmp/aidw-g13-ws/control runs list
```

Read `<state root>/runs/<run id>/stages/task-review-1.evidence.md` (the run directory is under
the printed state root) and inspect its `## Cited spec sections` section.

**Expected observable result.** The evidence bundle's cited-specs section contains the line
`- Design 11 → docs/specs/Design 11 - Foo.md §5.3` — the resolved repository-relative document
path plus the section the preflight checked, from the same enumeration. The build results
record this rendering only as a **test row**
(`test_g13_evidence_bundle_renders_the_resolved_path_and_checked_sections`, passing in the
recorded full suite); they contain no hand-run bundle.

**How to tell pass from fail.** Pass when the bundle names `docs/specs/Design 11 - Foo.md` (not
`design.md`, and not an absolute path) with `§5.3`. Fail if the section reads
`- Design 11 → design.md §11` (the pre-G1.3 rendering, meaning `specs_dir` was not threaded
into the bundle), if the path is absolute, or if the stage was planned with no bundle at all
(check stderr for a `could not write the evidence bundle` warning).

**Cost, permission or destructive warning.** **Paid:** it invokes Pi with your credentials, and
a run that is not interrupted proceeds into further review and fix rounds, spending more.
It also creates a branch `03-E4.1` and a task worktree under the scratch workspace. Confine
everything to `/tmp/aidw-g13-ws`; never point `--repo` at a real repository for this scenario.

#### B11. A real target repo that declares `paths.specs_dir` (Mythical Forge) — unverified

**Prerequisites.** A local checkout of the Mythical Forge target repository with the supported
layout and a root `design.md`-free specs directory at `docs/specs` — the layout the build
results describe. **The exact checkout path and the id of an entry to author are not recorded
in this branch**, so the path below is a placeholder to replace and the specific
`phase`/`epic`/`task` arguments are **unconfirmed**. The build results mark this row
`unverified`: it needs `paths.specs_dir: docs/specs` added to that repo's `aidw/config.yaml`,
which is outside this branch, and no target repo was touched by the recording stage.

**Command(s) or steps.** Add the key to that repo's config (replace the placeholder path):

```bash
# In <path-to-mythical-forge-checkout>/aidw/config.yaml, add under `paths:`:
#   specs_dir: docs/specs
uv run --frozen aidw --repo <path-to-mythical-forge-checkout> doctor
echo "doctor exit: $?"
uv run --frozen aidw --repo <path-to-mythical-forge-checkout> config show \
  | grep 'paths.specs_dir'
# Then, for one real roadmap entry of that repo (its id is unconfirmed here):
uv run --frozen aidw --repo <path-to-mythical-forge-checkout> prompt <phase> <epic> <task> --dry-run
echo "exit: $?"
```

**Expected observable result.** `doctor` exits 0 and its `specs dir` line is `[  ok  ]` naming
`<checkout>/docs/specs` and the count of numbered spec documents. `config show` reports
`paths.specs_dir: docs/specs (config)`. The dry run exits `0`; whether it prints the
no-problems note or per-entry gaps depends on the entry chosen, and **is not recorded** —
the build results contain no run against that repository (the roadmap analysis they quote
counted 45 distinct `Design N` citations resolving to one file across 299 entries, and 235
entries still failing on the section rule before this change). Treat any preflight outcome
here as a new observation, not as evidence for this branch.

**How to tell pass from fail.** Pass on the doctor and `config show` parts when the specs dir
check is OK and the leaf carries `config` provenance. For the dry run, there is no recorded
expected verdict: record what the chosen entry produces. Fail if `doctor` reports the specs
dir check at `warn`/`fail` on a directory that does contain `Design <number> - ` documents, or
if the leaf resolves `default`/`unset` after being declared.

**Cost, permission or destructive warning.** The doctor and `config show` calls are read-only;
the dry run writes nothing and spends nothing. Editing that repository's `aidw/config.yaml` is
a real change to a target repo outside this branch: commit it there only as a deliberate,
separate change, and never hand-run the paid (non-dry-run) form against it for this scenario.

### Group C — Browser UI flows

None. No changed file, build-results row or task-prompt statement names a browser screen,
route, click sequence or web flow; the change is a Python preflight, a doctor check, a config
leaf and documentation. No scenario is listed because there is no evidence of such a surface.

### Group D — External actions (cloud providers, deployed stacks)

None. No changed file, build-results row or task-prompt statement names a cloud account,
credential scope, bucket, role, ARN, deployed stack or paid infrastructure command. The only
spend this change can influence is the Pi authoring run the preflight prevents from starting
(B9) and the paid run in B10.

## 3. Teardown

Group B creates state **only** under `/tmp/aidw-g13-ws`: the seed repository, the bare
repository, the control worktree, any `03-E4.1` task worktree created by B10, run state under
the scratch workspace's state root, and any generated prompt file. Inspect, then remove it
all:

```bash
uv run --frozen aidw --repo /tmp/aidw-g13-ws/control worktree list
rm -rf /tmp/aidw-g13-ws
```

If B11 was attempted, revert the `paths.specs_dir` line in that target repo's
`aidw/config.yaml` (or commit it there deliberately as a separate change) and leave no branch,
worktree or run state behind in the target repo. Group A creates nothing: it installs the
already-locked environment and runs read-only checks and tests.

## 4. Could not be exercised in this environment

- **A real Mythical Forge target repo with `paths.specs_dir: docs/specs` (B11) — unverified.**
  The build results mark this row `unverified` with the reason that it needs
  `paths.specs_dir: docs/specs` added to Mythical Forge's `aidw/config.yaml`, which is outside
  this branch, and that no target repo was touched by the recording stage. It needs a checkout
  of that repository with its `docs/specs` layout; the checkout path and a concrete roadmap
  entry id are not recorded in this branch, so both remain unconfirmed here.
- **The paid authoring stage and its evidence bundle without model spend (B10).** The bundle is
  written only by a real run, and no CLI renders it offline. It needs Pi installed and
  authenticated plus whatever model spend your configuration incurs; a human with those
  credentials can exercise it, this guide cannot.
- **A real end-to-end `aidw prompt` run past the preflight.** The build results record the
  preflight and the bundle only through tests with faked stages; they contain no real Pi run.
  Exercising it needs Pi, credentials and spend, plus the supported bare-plus-worktree layout.
- **The earlier recorded suite failure is not reproducible at this tree, and this guide did not
  re-observe its fix.** The build results record `1 failed, 2556 passed` on tree
  `e241ed5eba82` — `test_g13_repeated_same_design_token_uses_each_token_window` — and a green
  `2558 passed` on the current tree `2efae543353d`, with the formerly failing case passing on
  its own. Their Deviations section states the tree advanced between the two recording
  invocations and that no source, test or spec file was changed by that stage, so the pass is
  the gate store's observation of the tree as it stands. B5 therefore tells you to expect two
  gaps; if you see none, that is the superseded failure reappearing, not this guide's evidence.
- **Nothing else requires a deployed stack, a production-only account, hardware or a browser.**
  Every remaining scenario runs locally against a disposable scratch tree with no credentials
  and no spend, apart from the two Pi-dependent items above.
