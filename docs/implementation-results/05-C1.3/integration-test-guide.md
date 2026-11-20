# Integration Test Guide — C1.3: Inline the resolved gate commands into the stage prompts that reference them

**Branch:** `05-C1.3`
**Source of record:** `docs/implementation-results/05-C1.3/build-results.md`
**Task prompt:** `docs/task-prompts/05-C1.3-prompt.md`

## 1. What this guide covers

This is a hand-run procedure for a human to confirm, in their own environment, the change on
branch `05-C1.3`: the target repo's gate commands are now **resolved once**
(`aidw/prompts.py:resolved_gate_block`) from the root `AGENTS.md` and the optional
`aidw/conventions.md` in D16 order, and **injected as text** into exactly five stage prompts —
`impliment-task.md`, `test.md`, `fix-next-review-followup.md`,
`record-implementation-results.md`, `code-review.md` — under the header
`## Resolved gate commands (AGENTS.md + aidw/conventions.md)`, while every other prompt stays
byte-identical (`aidw/prompts.py:GATE_PROMPTS`, `inject_gate_block`; called from
`aidw/runner.py:run_stage` after the repo-conventions append). It also covers the prompt-text
edits (the "never inlined here" clause replaced by a pointer, every `aidw gate run` wrapper
kept), the `code-review.md` re-classification out of byte-frozen bucket (i) in
`docs/migration/prompt-classification.md`, and the docs/design updates.

It walks the surfaces the changed files, the build-results rows and the task prompt point at:
the toolkit's own verification gates, the pure resolution/injection functions, the `aidw exec`
render seam, and the prompt/document contract text. It touches no browser UI flow and no cloud
surface, because no changed file, build-results row or task-prompt statement names one.

**Nothing in this guide has been executed by the toolkit.** No scenario below was run while
writing it: every expected result is derived from the changed source, the changed tests, the
task prompt and the recorded build results — not observed here. You run these; the toolkit did
not.

## 2. Scenarios

Grouped by surface kind. Section C (browser UI) and section D (external/cloud actions) carry no
scenario by evidence, not by omission.

Set these shell variables first (replace the paths with real ones). Everything below reads or
writes only inside `$WORK`, a throwaway directory, so the checked-out `05-C1.3` tree is never
modified:

```bash
TOOLKIT=$(git -C /path/to/aidt rev-parse --show-toplevel)   # the aidt checkout on branch 05-C1.3
WORK=$(mktemp -d)
TARGET="$WORK/target"          # a scratch "target repo" for the pure-function probes
EMPTY="$WORK/empty-target"     # a target with no AGENTS.md and no aidw/conventions.md
mkdir -p "$TARGET/aidw" "$EMPTY"
```

The toolkit's own verification gates (S1) resolve the commands from the *toolkit's* root
`AGENTS.md` "Gates — run exactly these, and only these" section; the guide quotes those
commands, not the recorded `--frozen` variants.

### A. Repo tooling — the toolkit's own commands and prompt contract

#### S1 — the branch's verification gates still hold

1. **Prerequisites.** The `05-C1.3` checkout, `uv` on `PATH`, and network access for the frozen
   sync if the environment is not already synced. No model, no credentials, no cloud account.
   These are exactly the repo's gates from the root `AGENTS.md`.
2. **Command(s) or steps.**
   ```bash
   cd "$TOOLKIT"
   uv sync --frozen
   uv run --frozen pytest
   uv run aidw doctor
   uv run aidw agents validate --strict
   uv run aidw prompts check
   ```
   `uv run --frozen aidw doctor`, `... agents validate --strict` and `... prompts check` are the
   `--frozen` forms the build results recorded; either form exercises the same check.
3. **Expected observable result.** Build results record, for tree `fba465750012`:
   `uv sync --frozen` → `Checked 19 packages …`, exit 0; `pytest` → `2425 passed in 48.96s`;
   `doctor` → `23 checks: 0 failed, 2 warning(s)` with the `gates heading` row `ok`, exit 0 (the
   two WARNs are the pre-existing dirty-working-tree and `mcp config missing` ones);
   `agents validate --strict` → `11 agent config(s): 0 error(s), 0 warning(s)`;
   `prompts check` → `resolved repo prompts: 0 error(s), 0 warning(s)` with 43 files. Your own
   totals may differ with your machine's state; the contract is zero failures.
4. **How to tell pass from fail.** Pass: every command exits 0 and pytest's summary shows no
   failure/error. Fail: any non-zero exit, a pytest failure or error, a FAIL row in `doctor`, or
   the `gates heading` row going `warn`/`fail` on the toolkit's own suffixed canonical heading
   `## Gates — run exactly these, and only these` (that row must stay `ok` — C1.2 owns it and
   C1.3 must not regress it). A `doctor` WARN unrelated to gates (your own Pi/`gh`/MCP state) is
   not this scenario's failure.
5. **Cost, permission or destructive warning.** None beyond disk and CPU time: the suite spawns
   hundreds of temporary git repositories. Do not edit `pyproject.toml` or `uv.lock` to make it
   pass — a stale lock is a build failure by design.

#### S2 — the C1.3 contract tests and the re-baselined classification guard

1. **Prerequisites.** S1 step 1 (synced environment). No credentials, no model.
2. **Command(s) or steps.**
   ```bash
   cd "$TOOLKIT"
   uv run --frozen pytest -v tests/test_conventions_injection.py tests/test_prompt_classification.py tests/test_design_doc.py
   # the C1.3 cases only, as a shorter read:
   uv run --frozen pytest -v tests/test_conventions_injection.py -k c13
   ```
   `-v` and `-k` are pytest's own options, not aidw flags.
3. **Expected observable result.** Every selected test passes. The `c13` selection should name
   `test_c13_the_gate_prompt_set_is_exactly_the_five_and_not_the_conventions_set`,
   `test_c13_resolved_gate_block_joins_the_sections_verbatim_in_d16_order`,
   `test_c13_each_gate_prompt_receives_the_block_under_its_header`,
   `test_c13_prompts_outside_the_five_stay_byte_identical`,
   `test_c13_a_repo_with_no_source_resolves_none_and_renders_identically`,
   `test_c13_the_gate_block_reads_the_target_root_not_the_toolkit_root`,
   `test_c13_the_dry_run_render_carries_the_block_exactly_once`, plus the remaining `c13` cases
   in the same module. `tests/test_prompt_classification.py` passes with `code-review.md` in
   class `(v)` and out of the byte-frozen set; `tests/test_design_doc.py` passes with §7.3
   step 5 and one `C1.3` §17 row. The build results record these modules as part of the single
   recorded 2425-test suite; **no per-module count was recorded**, so do not treat a count you
   see as a recorded expectation.
4. **How to tell pass from fail.** Pass: pytest exits 0 and no selected test is `FAILED`,
   `ERROR`, or `xfail`-ed where the guard expects a pass. Fail: any failure, or a green run
   whose `-k c13` selection collects **zero** tests (that would mean the contracts were renamed
   or skipped, not that they passed).
5. **Cost, permission or destructive warning.** None. The suite's temporary repos live under the
   pytest tmp tree; check the toolkit's `runs/` tree afterwards for stray `*-pytest-*`
   directories (S1's suite guards this, but a killed run can leave one).

#### S3 — the prompt-text and document contract

1. **Prerequisites.** The `05-C1.3` checkout only. No environment, no credentials.
2. **Command(s) or steps.** Read-only inspection; each line is a separate check.
   ```bash
   cd "$TOOLKIT"

   # (a) the "never inlined here" clause is gone from the five (and only remains elsewhere)
   grep -rn "inlined here" prompts/

   # (b) each of the five carries the new pointer text
   grep -c "resolved gate commands" prompts/impliment-task.md \
     prompts/test.md prompts/fix-next-review-followup.md \
     prompts/record-implementation-results.md prompts/code-review.md

   # (c) the gate-recording wrapper survived in every one of them
   grep -c "aidw gate run" prompts/impliment-task.md prompts/test.md \
     prompts/fix-next-review-followup.md prompts/record-implementation-results.md \
     prompts/code-review.md

   # (d) the re-classification and the single-resolution doc rows
   grep -n "code-review.md" docs/migration/prompt-classification.md | head
   grep -n "resolved_gate_block" docs/target-repo-config.md design.md | head
   ```
3. **Expected observable result.** (a) exactly one hit, `prompts/task-prompt.md:153` — a prompt
   **outside** the five; no hit for `impliment-task.md`, `test.md`,
   `fix-next-review-followup.md`, `record-implementation-results.md` or `code-review.md`
   (build results record exactly that result). (b) one hit per file — the five prompts each name
   the injected **resolved gate commands** block. (c) the build results record these occurrence
   counts: `impliment-task.md` 4, `test.md` 3, `fix-next-review-followup.md` 7,
   `record-implementation-results.md` 6, `code-review.md` 1; a higher count is acceptable, a
   zero is not. (d) `docs/migration/prompt-classification.md` lists `code-review.md` in class
   `(v)`, re-classified out of (i) after the cutover; both `docs/target-repo-config.md` and
   `design.md` name `aidw/prompts.py:resolved_gate_block` (and `design.md` carries one `Z17` row).
4. **How to tell pass from fail.** Pass: (a) one hit, in `task-prompt.md`; (b) five non-zero
   counts; (c) five non-zero counts with `code-review.md` at least 1; (d) the class-(v) row and
   the `resolved_gate_block` references are present. Fail: any hit for `inlined here` inside the
   five, a zero count in (b) or (c), or `code-review.md` still listed as bucket `(i)` /
   "ship as-is".
5. **Cost, permission or destructive warning.** None. Read-only `grep` and file reads.

### B. Custom CLI / TUI commands — the resolution, the injection and the render seam

#### S4 — `resolved_gate_block` joins both sources verbatim in D16 order (target root only)

1. **Prerequisites.** `$TOOLKIT` and `$TARGET` from the setup block, `uv` on `PATH`. No model,
   no credentials, no git repository required. Write `$TARGET`'s two sources:
   `AGENTS.md` carrying `## Gates — run exactly these, and only these` with two commands and a
   later `## Notes` section, and `aidw/conventions.md` carrying `## Gate commands` with one
   command.
2. **Command(s) or steps.**
   ````bash
   cd "$TOOLKIT"

   cat > "$TARGET/AGENTS.md" <<'MD'
   # Target repo

   Intro paragraph, not part of a gate section.

   ## Gates — run exactly these, and only these

   ```bash
   target-gate-one --check
   target-gate-two --check
   ```

   ## Notes

   C13-TARGET-ONLY-MARKER
   MD

   cat > "$TARGET/aidw/conventions.md" <<'MD'
   # Conventions

   ## Gate commands

   ```bash
   target-gate-three --check
   ```
   MD

   uv run --frozen python - "$TARGET" <<'PY'
   import pathlib, sys
   from aidw.prompts import GATE_BLOCK_HEADER, GATE_BLOCK_SOURCES, resolved_gate_block
   root = pathlib.Path(sys.argv[1])
   print("sources:", GATE_BLOCK_SOURCES)
   print("header: ", GATE_BLOCK_HEADER.format(sources=GATE_BLOCK_SOURCES))
   print("--- block ---")
   print(resolved_gate_block(root))
   PY
   ````
3. **Expected observable result.** `sources: AGENTS.md + aidw/conventions.md`; `header:  ##
   Resolved gate commands (AGENTS.md + aidw/conventions.md)`; the block is exactly the two
   sections joined by one blank line, in D16 order — the `## Gates — run exactly these, and only
   these` heading, its two commands, then the `## Gate commands` heading and
   `target-gate-three --check`. The intro paragraph, `## Notes` and
   `C13-TARGET-ONLY-MARKER` are **absent** (a section runs to the next `## ` heading), and the
   toolkit's own `uv sync --frozen` is **absent** (the block was read from the target root, not
   `toolkit_root()` — the two-roots trap).
4. **How to tell pass from fail.** Pass: the printed block equals the two sections byte-for-byte
   in that order, with no toolkit command in it. Fail: `None` while both headings are present;
   the `## Notes` section or marker leaking into the block; the toolkit's `uv sync --frozen`
   appearing; or the two sections in the reverse order (the D16 order is `AGENTS.md` first).
5. **Cost, permission or destructive warning.** None. The probe only reads `$TARGET`; the module
   under test is pure, and writing the fixture files is confined to the throwaway directory.

#### S5 — `inject_gate_block`: five prompts in, three byte-identical out, None is never `unavailable`

1. **Prerequisites.** S4's `$TARGET` (with both sources written), `$EMPTY` (created empty), and a
   repo-shadow fixture under `$TARGET/aidw/prompts/`. No model, no credentials.
2. **Command(s) or steps.**
   ```bash
   cd "$TOOLKIT"

   # (a) each of the five gets the block under the header, exactly once
   uv run --frozen python - "$TARGET" <<'PY'
   import pathlib, sys
   from aidw.prompts import (
       GATE_BLOCK_HEADER, GATE_BLOCK_SOURCES, inject_gate_block, receives_gate_block,
   )
   root = pathlib.Path(sys.argv[1]).resolve()
   toolkit = pathlib.Path.cwd()
   header = GATE_BLOCK_HEADER.format(sources=GATE_BLOCK_SOURCES)
   body = "rendered body\n"
   for name in ("impliment-task.md", "test.md", "fix-next-review-followup.md",
                "record-implementation-results.md", "code-review.md"):
       out = inject_gate_block(body, toolkit / "prompts" / name, root)
       print(name, "received:", out.startswith(body + "\n\n" + header + "\n\n"),
             "headers:", out.count(header))
   for name in ("pr.md", "task-prompt.md", "update-traceability.md"):
       out = inject_gate_block(body, toolkit / "prompts" / name, root)
       print(name, "byte-identical:", out == body, "gate-prompt:", receives_gate_block(toolkit / "prompts" / name))
   PY

   # (b) a repo shadow is keyed by resolved basename, and no source is byte-identity
   mkdir -p "$TARGET/aidw/prompts"
   printf '# target shadow\n' > "$TARGET/aidw/prompts/test.md"
   uv run --frozen python - "$TARGET" "$EMPTY" <<'PY'
   import pathlib, sys
   from aidw.prompts import inject_gate_block, receives_gate_block, resolved_gate_block
   target, empty = (pathlib.Path(p).resolve() for p in sys.argv[1:3])
   body = "rendered body\n"
   shadow = target / "aidw" / "prompts" / "test.md"
   print("shadow keyed:", receives_gate_block(shadow))
   print("shadow injected:", inject_gate_block(body, shadow, target) != body)
   print("empty resolves:", resolved_gate_block(empty))
   for name in ("impliment-task.md", "test.md", "fix-next-review-followup.md",
                "record-implementation-results.md", "code-review.md"):
       print(name, "unchanged on empty target:",
             inject_gate_block(body, pathlib.Path.cwd() / "prompts" / name, empty) == body)
   PY
   ```
3. **Expected observable result.** (a) five lines `received: True headers: 1` — the header occurs
   **exactly once** per prompt even for the three that also receive the whole-file conventions
   append (the duplication corner is resolved by the injection being the authoritative
   "resolved gate commands" presentation); then three lines `byte-identical: True
   gate-prompt: False`. (b) `shadow keyed: True`, `shadow injected: True`, `empty resolves:
   None`, and five `unchanged on empty target: True` lines — with no `unavailable` text anywhere,
   because the renderer never injects the evidence bundle's degrade note.
4. **How to tell pass from fail.** Pass: the counts and booleans above, exactly. Fail: any of the
   five reporting `received: False` or `headers` other than 1; any of `pr.md`, `task-prompt.md`,
   `update-traceability.md` changed by the injection; the shadow not keyed (a stage-id key would
   miss it); `resolved_gate_block($EMPTY)` anything other than `None`; or an `unavailable` string
   appearing in a no-source render (that would be the evidence bundle's contract leaking into a
   stage prompt).
5. **Cost, permission or destructive warning.** None. Writes stay inside `$TARGET` (the shadow
   file) and `$EMPTY`; the functions are pure and mutate nothing.

#### S6 — `aidw exec --dry-run` still plans without writing, and cannot show the injected text

1. **Prerequisites.** A git checkout the toolkit accepts as a target — use a clone of `$TOOLKIT`
   so the resolution has the toolkit's own `## Gates — run exactly these, and only these`
   section: `SCRATCH=$(mktemp -d)/target && git clone "$TOOLKIT" "$SCRATCH"`. A synced
   environment (S1). No model, no credentials. `--dry-run` invokes no Pi process.
2. **Command(s) or steps.**
   ```bash
   cd "$TOOLKIT"
   uv run --frozen aidw config show | sed -n '/state root/p'   # note the state root for S7/teardown
   uv run --frozen aidw --repo "$SCRATCH" exec \
     --agent implementer --prompt impliment-task.md \
     --var docs/task-prompts/05-C1.3-prompt.md --dry-run; echo "exit=$?"
   ```
   `--agent implementer`, `--prompt`, `--var` and `--dry-run` are `aidw exec`'s own options
   (`aidw/cli.py`); `--var` is positional variable `$1`, which `impliment-task.md` declares as
   `task-prompt-file: $1`.
3. **Expected observable result.** The command prints `stage:  impliment-task [succeeded]`
   (`run_stage` sets `SUCCEEDED` on the dry-run path) and ends with
   `dry-run complete; Pi not invoked`, exit 0. **No `prompts/<stage>.rendered.md`
   is written** (W1.2: a plan creates no run directory, so `exec --dry-run` echoes no `rendered:`
   line). Consequence, stated plainly: **this scenario cannot show you the injected block** —
   the dry-run seam computes the text but persists nothing. Use S4/S5 for the text and S7 for
   the written file.
4. **How to tell pass from fail.** Pass: exit 0, the `stage:` line, the exact
   `dry-run complete; Pi not invoked` line, and no new directory under `<state root>/runs`
   afterwards. Fail: a non-zero exit, any Pi invocation, or a new run directory (the plan
   published state it must not). Do **not** judge the injected text here; a dry run has no file
   to read.
5. **Cost, permission or destructive warning.** None: no model call, no writes. The clone is
   disposable (teardown removes it).

#### S7 — a real stage render writes the block into `.rendered.md` and the same text to Pi's stdin

1. **Prerequisites.** S6's `$SCRATCH` clone (a valid target with the toolkit's gate section), a
   synced environment, and a **stub `pi`** placed first on `PATH`. The stub is possible because
   `aidw/agents.py:build_argv` starts the argv with the literal `"pi"`, resolved through `PATH`,
   and `aidw/runner.py:run_stage` passes the inherited environment through
   (`build_env(agent, dict(os.environ))`). This scenario therefore costs **no model spend**.
   What it does **not** prove is that a real model reads or obeys the injected block — see
   section 4. No credentials are needed.
2. **Command(s) or steps.**
   ```bash
   cd "$TOOLKIT"
   STUB=$(mktemp -d)
   CAPTURE="$STUB/pi-stdin.txt"
   cat > "$STUB/pi" <<'SH'
   #!/bin/sh
   cat > "$PI_STUB_CAPTURE"
   exit 0
   SH
   chmod +x "$STUB/pi"

   PATH="$STUB:$PATH" PI_STUB_CAPTURE="$CAPTURE" \
     uv run --frozen aidw --repo "$SCRATCH" exec \
       --agent implementer --prompt impliment-task.md \
       --var docs/task-prompts/05-C1.3-prompt.md --label c13-guide; echo "exit=$?"

   # read the run id printed as `run:      <id>`, then (the path mirrors the `rendered:` echo):
   RENDERS="<state root>/runs/<run-id>"    # state root from `aidw config show`, id from `run:`
   cat "$RENDERS/prompts/impliment-task.rendered.md"
   ```
   `--label` is a confirmed `aidw exec` option; it only tags the run id for teardown.
3. **Expected observable result.** A run directory exists under `<state root>/runs/<run-id>/`,
   `prompts/impliment-task.rendered.md` exists, and:
   - it contains the header `## Resolved gate commands (AGENTS.md + aidw/conventions.md)`
     **exactly once**;
   - after that header it carries the toolkit's real gate commands (`uv sync --frozen`,
     `uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents validate --strict`,
     `uv run aidw prompts check`) copied verbatim from the clone's `AGENTS.md`;
   - the header appears **after** the `## Repo conventions (aidw/conventions.md)` block, if that
     block is present (`impliment-task.md` is in both prompt sets, so both append);
   - the prompt **body** still carries its `<the repo's package-scoped lint command>` style
     placeholder — the injection supplies commands, it does not rewrite the body templates;
   - `$CAPTURE` holds the same text (the stdin payload), and the run's `rendered:` echo names
     `runs/<run-id>/prompts/impliment-task.rendered.md` relative to the state root.
   The **stage's own status and the command's exit code are not this scenario's check**: the stub
   answers with empty output, so the stage will very likely end failed ("empty final message").
   The rendered file is written **before** Pi is invoked, so it exists regardless.
4. **How to tell pass from fail.** Pass: the rendered file contains the header once, the real
   gate commands after it, and the body placeholder still present; `$CAPTURE` matches the file.
   Fail: no rendered file; a header count of 0 or 2+; the body placeholder replaced by the real
   commands (that would be re-synthesising prompt text, not injecting a block); the block
   appearing **before** the conventions append; or the file holding no gate section while the
   clone's `AGENTS.md` carries `## Gates — run exactly these, and only these`. A failed/blocked
   stage status from the stub is expected and is **not** counted as this scenario's failure.
5. **Cost, permission or destructive warning.** No model spend and no credentials, but the run
   **writes** a run directory under the state root, a `run.log`, `state.json`, a `prompts/`
   subdirectory and `stages/` metadata — all machine-local, never committed, and all removed in
   teardown. Do not point `--repo` at a working tree you care about: the stage
   writes only under the state root, but keeping it on the disposable clone avoids surprises. If
   you would rather not fake Pi, skip this scenario and rely on S4/S5 (say so rather than
   marking it passed).

### C. Browser UI flows

No scenario. No changed file, build-results row or task-prompt statement names a route, page or
rendered screen; the change is prompt rendering plus file and config reads.

### D. External actions (cloud-provider commands)

No scenario. No changed file, build-results row or task-prompt statement names a cloud command,
bucket, role, ARN or environment variable. The only added I/O is reading `AGENTS.md`,
`aidw/conventions.md` and `aidw/config.yaml` from the target root.

## 3. Teardown

- Delete the throwaway tree and everything in it — the fixture target, the empty target, the
  clone and its worktree state:
  ```bash
  rm -rf "$WORK"                       # the setup block's throwaway directory
  [ -n "$SCRATCH" ] && rm -rf "$(dirname "$SCRATCH")"   # only if you ran S6/S7
  ```
- Delete the Pi stub and its capture (S7): `rm -rf "$STUB"`.
- Delete the run S7 created, if you ran it: remove
  `<state root>/runs/<run-id>` (the id printed as `run:      <run-id>`; the state root is what
  `aidw config show` reported). Run state is machine-local and never committed.
- If you ran S1/S2 and the toolkit has a `runs/` tree, check it for stray `*-pytest-*`
  directories left by a killed suite and remove only those
  (`find "$TOOLKIT/runs" -maxdepth 1 -name '*-pytest-*' 2>/dev/null`); the test fixtures normally
  clean up after themselves.
- Unset anything you exported for these steps (`PI_STUB_CAPTURE`, any `AIDW_REPO` you set
  instead of `--repo`) and drop the prefixed PATH by closing the shell or re-exporting the
  original `PATH`.
- Confirm the real checkout is untouched: `git -C "$TOOLKIT" status --short` shows nothing you
  did not already have, and `git -C "$TOOLKIT" diff --name-only` lists none of the files these
  scenarios wrote — every write above was inside `$WORK`, `$SCRATCH`, `$STUB` or a run directory
  under the state root.

## 4. Could not be exercised in this environment

- **`lint` gate — `unverified`.** This repo configures no lint command, so there is nothing to
  run. The build results record this row as `unverified` with that reason (`AGENTS.md`: "no
  linter, formatter, or type-checker is configured — don't add one inside an unrelated task").
  This guide cannot turn it into a pass; the closest honest check is `git diff --check`, which
  the build results record as passing.
- **A real, model-authenticated stage run obeying the injected block — not covered.** S7 proves
  the *text* reaches the rendered prompt and Pi's stdin, but it uses a stub `pi`, so no model
  reads the block, and whether an agent actually runs the injected commands instead of
  re-deriving them cannot be observed here. That needs a developer machine with `pi` on `PATH`,
  an authenticated model provider and available credit; it also spends money. Treat the
  prompt-following behaviour as covered only by the recorded suite's pure assertions and by S7's
  text comparison, and say so rather than marking it passed.
- **A real model-backed evidence bundle** (the C1.2 read channel `_gate_block` after C1.3's
  wrapper) is likewise not exercised by this guide: producing one needs a real `aidw prompt` run
  with a provider account and credit. The build results record the suite covering it; this guide
  does not re-run it.
- **A deployed stack or production account** is irrelevant to this change: it is local file
  reading, prompt string assembly and prompt text edits, with no deployable artefact and no
  service to reach. No browser is involved either.
- **Machine-dependent `doctor` rows** (`pi`, `gh`, `mcp config`, target-config state) make the
  overall `0 failed` count environment-specific; only the `gates heading` row is C1.2's concern
  and must stay `ok`. The recorded run (`23 checks: 0 failed, 2 warning(s)`) is from the build
  machine, not from yours.
- **The recorded suite count (2425 passed) and the recorded per-prompt `aidw gate run`
  occurrence counts** are observations of tree `fba465750012`; your tree's counts can only be
  compared for zero-versus-non-zero, not for equality, once you have changed anything locally.
