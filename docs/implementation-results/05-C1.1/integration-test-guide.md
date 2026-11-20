# Integration Test Guide — C1.1: Stop appending the target `AGENTS.md` to rendered prompts

**Branch:** `05-C1.1`
**Build results:** `docs/implementation-results/05-C1.1/build-results.md` (this repo's `paths.implementation_results_dir`)
**Task prompt:** `docs/task-prompts/05-C1.1-prompt.md` (this repo's `paths.task_prompts_dir`)

## 1. What this guide covers

This procedure exercises the C1.1 change on branch `05-C1.1`: the prompt renderer no longer
appends the target repo's root `AGENTS.md` to a rendered prompt (`aidw/prompts.py`'s
`render_repo_conventions` / `inject_repo_conventions`), keeps the `aidw/conventions.md` append,
and adds the opt-in frontmatter marker `append_agents_md: true`, read by the new pure peek
`aidw.prompts.appends_target_agents_md`, which restores the `AGENTS.md` append for the resolved
prompt file only. It walks the toolkit's library seams, the `aidw` CLI surface that renders and
records prompts, and the repo's own verification commands. The read channel
(`read_conventions_sources` / `CONVENTIONS_SOURCES`) is deliberately unchanged, and this guide
checks that too, because `aidw/workflows/prompt.py:_gate_block` takes gate commands through it.

**This is a hand-run procedure. Nothing in this document has been executed by the toolkit as an
integration test.** Every outcome quoted as "recorded" comes from
`docs/implementation-results/05-C1.1/build-results.md`; every other outcome is an expectation
for the person running the steps, not an observed result. The change touches no browser UI and
no cloud infrastructure, so those scenario groups do not exist here.

## 2. Scenarios

Grouped by surface kind: the repo's existing tooling, the toolkit library seams, the custom CLI
commands. Browser UI flows and external/cloud actions have no scenario — no changed file, no
build-results row and no task-prompt statement points at one.

### 2.1 Repository tooling

#### Scenario T1 — Focused contract tests for the injection and the design-doc pin

1. **Prerequisites** — A checkout of branch `05-C1.1` at its current working tree, `uv` installed,
   and the frozen environment materialised (`uv sync --frozen`). No credentials, no network
   service, no Pi invocation.
2. **Command(s) or steps** — from the repository root:
   ```bash
   uv sync --frozen
   uv run --frozen pytest -n0 tests/test_conventions_injection.py tests/test_design_doc.py
   ```
3. **Expected observable result** — pytest exits 0 and prints a passing summary. The build
   results record `145 passed` for exactly this selection (gate `smoke`, tree
   `a603ce4daaba`, stage `test`, `2026-11-20T05:35:56Z`).
4. **How to tell pass from fail** — Compare the summary line: `145 passed` with exit status 0 is
   a pass. Any failure, error, or a different test count is a fail — a changed count means the
   tests that pin the new behaviour (conventions-only default, marker restore, the
   `docs/implementation-results` §7.3/§17 design pins) were altered or lost.
5. **Cost, permission or destructive warning** — none. Both modules build temporary repositories
   under pytest's `tmp_path`; `tests/conftest.py` guards the toolkit `runs/` tree against stray
   pytest directories.

#### Scenario T2 — The gate-block read channel still sees both convention sources

1. **Prerequisites** — Same as T1: the frozen environment, no credentials.
2. **Command(s) or steps** — from the repository root:
   ```bash
   uv run --frozen pytest -n0 tests/test_prompt_workflow.py -k 'e73_gate_list_includes_conventions_md_commands_after_agents_md or e73_conventions_md_alone_supplies_the_gate_list or e73_non_utf8_conventions_source_is_ignored_by_the_gate_block'
   ```
3. **Expected observable result** — the build results record `3 passed, 236 deselected` for this
   selection (gate `smoke`, tree `a603ce4daaba`, `2026-11-20T05:36:00Z`). These three cases pin
   that `_gate_block` still takes `## Gates` commands from the root `AGENTS.md` and from
   `aidw/conventions.md`, and that a non-UTF-8 conventions source contributes nothing rather
   than raising.
4. **How to tell pass from fail** — `3 passed` and exit 0 is a pass. A `deselected` count other
   than `236` means the `-k` expression no longer matches the same three nodes; any failure means
   the read channel or its degrade-never-error contract moved, which the task forbids.
5. **Cost, permission or destructive warning** — none.

#### Scenario T3 — Whole-repo suite (broader regression, optional)

1. **Prerequisites** — Same as T1; expect the suite to take tens of seconds (the build results
   record `48.71s`).
2. **Command(s) or steps** — from the repository root:
   ```bash
   uv run --frozen pytest
   ```
3. **Expected observable result** — the build results record `2348 passed in 48.71s` (gate
   `suite`, tree `2d1f11899317`, stage `record-implementation-results`,
   `2026-11-20T05:40:20Z`).
4. **How to tell pass from fail** — Exit 0 with no failures and no errors is a pass. A count other
   than `2348` may legitimately reflect tests added after recording; a failure or error is a fail.
5. **Cost, permission or destructive warning** — none. `pyproject.toml` sets `-n auto`, so the
   suite spawns parallel workers and many temporary git repositories; it writes only under pytest
   temporary directories and is guarded by `tests/conftest.py`.

#### Scenario T4 — Prompt inventory accepts the tree (regression around the marker)

1. **Prerequisites** — Same as T1. Run from a repository checkout; the command resolves the target
   via git (`--repo` precedes the subcommand if you point it elsewhere).
2. **Command(s) or steps** — from the repository root:
   ```bash
   uv run --frozen aidw prompts check
   ```
3. **Expected observable result** — two headings, one per group, each followed by its resolved
   prompt lines and a summary:
   - `prompts check — toolkit defaults (...)` with `toolkit defaults: 0 error(s), 0 warning(s)`;
   - `prompts check — resolved repo prompts (...)` with
     `resolved repo prompts: 0 error(s), 0 warning(s)`.
   The build results record that pass (gate `prompts`, tree `2d1f11899317`,
   `2026-11-20T05:40:26Z`).
4. **How to tell pass from fail** — Exit status 0 and `0 error(s), 0 warning(s)` in both groups is
   a pass. Any error line or non-zero exit is a fail. Note that no prompt in the tree currently
   declares `append_agents_md` (confirmed by reading `prompts/*.md` and `docs/target-repo-config.md`:
   no config key or prompt frontmatter carries it), so this is a regression check that the marker
   is additive; it does not exercise the marker itself.
5. **Cost, permission or destructive warning** — none; the command is read-only. It does not
   validate arbitrary frontmatter keys (`aidw/inventory.py` performs no frontmatter parsing), so a
   marker typo is not caught here — Scenario L2 is the check for marker semantics.

### 2.2 Toolkit library seams (`aidw/prompts.py`)

These scenarios call the changed functions directly, which is the credential-free way to observe
the rendered block. The function names, signatures and keywords below are taken from
`aidw/prompts.py` on this branch: `render_repo_conventions(repo_root, *, include_agents_md=False)`,
`inject_repo_conventions(prompt_text, prompt, repo_root)`, `appends_target_agents_md(prompt)`,
`read_conventions_sources(repo_root)` and `CONVENTIONS_SOURCES`. `CONVENTIONS_PROMPTS` contains
`test.md`, so a file with that basename is the simplest prompt to inject into.

#### Scenario L1 — Default injection is conventions-only; the flag restores both sources

1. **Prerequisites** — The frozen environment (T1's `uv sync --frozen`). No target repo fixture on
   disk persists: the script creates one in a temporary directory. No credentials.
2. **Command(s) or steps** — from the repository root:
   ```bash
   uv run --frozen python - <<'PY'
   from pathlib import Path
   from tempfile import TemporaryDirectory

   from aidw import prompts

   with TemporaryDirectory() as tmp:
       target = Path(tmp)
       (target / "aidw").mkdir()
       (target / "AGENTS.md").write_text(
           "# Target AGENTS\n\nAGENTS-SENTINEL\n", encoding="utf-8"
       )
       (target / "aidw" / "conventions.md").write_text(
           "# Conventions\n\nCONVENTIONS-SENTINEL\n", encoding="utf-8"
       )

       print("SOURCES:", [source for source, _ in prompts.read_conventions_sources(target)])
       print("--- default block ---")
       print(prompts.render_repo_conventions(target))
       print("--- opted-in block ---")
       print(prompts.render_repo_conventions(target, include_agents_md=True))
   PY
   ```
3. **Expected observable result** —
   - `SOURCES: ['AGENTS.md', 'aidw/conventions.md']` — the read channel is unchanged, D16 order.
   - The default block has one header, `## Repo conventions (aidw/conventions.md)`, followed by
     `CONVENTIONS-SENTINEL`. It contains no `## Repo conventions (AGENTS.md)` header and no
     `AGENTS-SENTINEL`.
   - The opted-in block has `## Repo conventions (AGENTS.md)` **first** (with `AGENTS-SENTINEL`),
     then `## Repo conventions (aidw/conventions.md)`.
4. **How to tell pass from fail** — Count headers. Default: exactly one header and it names
   `aidw/conventions.md`; seeing `AGENTS-SENTINEL` in the default output is the C1.1 regression
   (the duplicate the task removes). Opted-in: exactly two headers with `AGENTS.md` before
   `aidw/conventions.md`; reversed order or a missing header is a fail. `SOURCES` must list both
   paths in that order — dropping `AGENTS.md` there is the trap the task prompt names, because
   `_gate_block` reads its `## Gates` section.
5. **Cost, permission or destructive warning** — none. The script writes only inside a
   `TemporaryDirectory` and mutates nothing in the repo.

#### Scenario L2 — Marker truth table, and the marker restoring the append

1. **Prerequisites** — Same as L1 (frozen environment, no credentials). The script creates all
   prompt and target fixtures in temporary directories; `prompts/impliment-task.md` is only read,
   never written.
2. **Command(s) or steps** — from the repository root:
   ```bash
   uv run --frozen python - <<'PY'
   from pathlib import Path
   from tempfile import TemporaryDirectory

   from aidw import prompts

   cases = {
       "true.md": "---\nappend_agents_md: true\n---\n# body\n",
       "absent.md": "---\ndescription: x\n---\n# body\n",
       "false.md": "---\nappend_agents_md: false\n---\n# body\n",
       "quoted.md": '---\nappend_agents_md: "true"\n---\n# body\n',
       "nested.md": "---\nappend_agents_md:\n  enabled: true\n---\n# body\n",
       "malformed.md": "---\nappend_agents_md: [\n---\n# body\n",
       "no-frontmatter.md": "# body\n",
   }

   with TemporaryDirectory() as tmp:
       base = Path(tmp)
       for name, text in cases.items():
           path = base / name
           path.write_text(text, encoding="utf-8")
           print(f"{name}: {prompts.appends_target_agents_md(path)}")

       non_utf8 = base / "non-utf8.md"
       non_utf8.write_bytes(b"---\nappend_agents_md: true\n---\n\xff\xfe\n")
       print("non-utf8.md:", prompts.appends_target_agents_md(non_utf8))
       print("missing.md:", prompts.appends_target_agents_md(base / "missing.md"))
       print(
           "toolkit impliment-task.md:",
           prompts.appends_target_agents_md(Path("prompts/impliment-task.md").resolve()),
       )

       target = base / "target"
       (target / "aidw").mkdir(parents=True)
       (target / "AGENTS.md").write_text("AGENTS-SENTINEL\n", encoding="utf-8")
       (target / "aidw" / "conventions.md").write_text("CONVENTIONS-SENTINEL\n", encoding="utf-8")

       marked = base / "marked" / "test.md"
       marked.parent.mkdir()
       marked.write_text("---\nappend_agents_md: true\n---\nBODY\n", encoding="utf-8")
       plain = base / "plain" / "test.md"
       plain.parent.mkdir()
       plain.write_text("BODY\n", encoding="utf-8")

       print("--- plain injection ---")
       print(prompts.inject_repo_conventions("BODY", plain, target))
       print("--- marked injection ---")
       print(prompts.inject_repo_conventions("BODY", marked, target))
   ```
3. **Expected observable result** —
   - `true.md: True`; `absent.md: False`; `false.md: False`; `quoted.md: False`;
     `nested.md: False`; `malformed.md: False`; `no-frontmatter.md: False`;
     `non-utf8.md: False`; `missing.md: False`; `toolkit impliment-task.md: False`.
   - `plain injection` shows `BODY` followed by the `## Repo conventions (aidw/conventions.md)`
     block only — no `AGENTS-SENTINEL`.
   - `marked injection` shows `BODY` followed by the `## Repo conventions (AGENTS.md)` block
     (`AGENTS-SENTINEL`) and then the `aidw/conventions.md` block.
4. **How to tell pass from fail** — Exactly one `True` (the plain YAML boolean under
   `true.md`) is a pass; any other `True` means the peek is guessing an opt-in, and any `False`
   for `true.md` means the lever is dead. The marker file is named `test.md` on purpose: a file
   outside `CONVENTIONS_PROMPTS` is returned byte-identically regardless of its marker, so a
   differently named fixture would make the injection half of this scenario meaningless. In both
   injection outputs the first line must be exactly `BODY` (byte-identical prefix); no "unavailable"
   note and no raise is expected for any of the edge cases.
5. **Cost, permission or destructive warning** — none. `appends_target_agents_md` and
   `inject_repo_conventions` are documented as pure: they read files and return text, and the
   script writes only into temporary directories.

### 2.3 Custom CLI commands (`aidw`)

`aidw exec` is the only CLI path that renders one stage's prompt and writes
`prompts/<stage>.rendered.md`; `aidw prompt`/`implement` also render, but need a whole workflow and
a task-prompt authoring stage. The rendered file is the surface C1.1 changes, so C2/C3 use
`exec`. Both write the rendered file **before** Pi is invoked
(`aidw/runner.py:run_stage`), and neither is recorded in the build results — the build results
record only credential-free gates, and the repo's rule is that no test may invoke a real Pi model.

#### Scenario C1 — `exec --dry-run` plans without writing a rendered file

1. **Prerequisites** — Frozen environment; a git target repository (this checkout works); Pi need
   not be installed because a dry run never invokes it. `agent-configs/tester.yaml` exists (it
   does on this branch: `tester`, provider `openrouter`).
2. **Command(s) or steps** — from the repository root:
   ```bash
   uv run --frozen aidw exec --agent tester --prompt test --dry-run
   ```
3. **Expected observable result** — a `stage:  test [planned] model=<resolved model>` line, then
   `dry-run complete; Pi not invoked`, and exit status 0. There is **no** `run:` line and **no**
   `rendered:` line, and no new directory appears under the state root
   (`<workspace_root>/.aidw/state/<repo_slug>/`, or `~/.aidw/state/<repo_slug>/` when the
   workspace root is not writable — `aidw/paths.py`).
4. **How to tell pass from fail** — Exit 0, one `[planned]` stage line, the `dry-run complete`
   line, and zero run directories. If a `run:` or `rendered:` line appears, or a new
   `runs/<timestamp>-…` directory exists afterwards, the W1.2 dry-run contract has regressed. A
   `prompt not found` or `agent not found` error means the invocation names a prompt/agent this
   tree does not carry — re-read `agent-configs/` and `prompts/` rather than guessing a name.
5. **Cost, permission or destructive warning** — none. No Pi invocation, no model spend, no writes
   (the §19 one-run-per-worktree lock is still acquired, so a concurrent run in the same worktree
   can refuse with exit 4 naming the lock — that is expected).

#### Scenario C2 — End-to-end rendered prompt drops `AGENTS.md` (real Pi run)

1. **Prerequisites** — A **disposable clone or worktree** of this repository (the target repo must
   have a root `AGENTS.md`, which this repository does, and `aidw/conventions.md`, which it also
   has), Pi installed and authenticated for the provider configured in
   `agent-configs/tester.yaml` (`provider: openrouter`, `model: openrouter/openai/gpt-5.6-luna`).
   This guide deliberately does **not** name an API-key environment variable: none is declared in
   this tree, so use whatever credential your Pi installation documents for that provider. Set
   aside model spend and assume the agent may edit the clone.
2. **Command(s) or steps** — from the disposable clone's root:
   ```bash
   uv run --frozen aidw exec --agent tester --prompt test
   ```
   Then read the file named on the `rendered:` line (e.g.
   `uv run --frozen aidw runs show <run id>` to see the run, and resolve the printed relative path
   against the state root as described in C1).
3. **Expected observable result** — the run prints `run:      <run id>`, a `stage:  test …` block
   and `rendered: runs/<run id>/prompts/test.rendered.md`. That file is the exact stdin payload
   sent to Pi and contains the `## Repo conventions (aidw/conventions.md)` block (with this
   repo's stack rules), and contains **no** `## Repo conventions (AGENTS.md)` header. Because
   `prompts/test.md` on this branch declares no `append_agents_md` marker (read the file to
   confirm), the default applies. The stage's own pass/fail is not the subject of this scenario;
   the rendered text is. Note: the build results do **not** record any real-Pi run, so this row
   is unverified by them — your run is the first evidence for it.
4. **How to tell pass from fail** — On the rendered file:
   `grep -c '^## Repo conventions (AGENTS.md)$'` → `0`;
   `grep -c '^## Repo conventions (aidw/conventions.md)$'` → `1`; and the file ends with the
   conventions block after the prompt body (applied last, after `spec.extra`). A single
   `AGENTS.md` header, or this repo's `# AGENTS.md — developing \`aidt\` itself` body appearing in
   the rendered file, is the C1.1 regression. Do not judge pass/fail by the agent's final message.
5. **Cost, permission or destructive warning** — **Cost:** a real model invocation, billed per
   token by the configured provider; price is not declared in this tree. **Permission:** the
   `tester` agent's tool allowlist on this branch is `read`, `bash`, `write`, `edit`, so it can
   change the clone and run shell commands. **Destructive:** run only in a disposable clone, and
   delete that clone afterwards; do not run it in your working checkout. The rendered file is
   written before Pi starts, so even a failed stage leaves it behind for inspection.

#### Scenario C3 — End-to-end rendered prompt restores `AGENTS.md` with the marker (real Pi run)

1. **Prerequisites** — Same as C2: disposable clone, Pi authenticated for `openrouter`, spend and
   destructive-edit assumption. Additionally create a prompt file named `test.md` (the basename
   matters — `CONVENTIONS_PROMPTS` keys on it) outside the repository, for example
   `$TMPDIR/c11-marker/test.md`, containing the marker frontmatter:
   ```markdown
   ---
   append_agents_md: true
   ---

   # Marker restore check

   Do not change any files. Report the repository's root `AGENTS.md` heading and the
   `aidw/conventions.md` heading you were given, then stop.
   ```
2. **Command(s) or steps** — from the disposable clone's root:
   ```bash
   uv run --frozen aidw exec --agent tester --prompt "$TMPDIR/c11-marker/test.md"
   ```
   Then read the file on the `rendered:` line. `aidw exec` accepts a prompt path as well as a name
   (`--prompt` help: "Prompt name (e.g. code-review) or path"), and an absolute path is the
   resolver's precedence-1 explicit prompt (`aidw/runner.py:resolve_prompt`).
3. **Expected observable result** — `rendered: runs/<run id>/prompts/test.rendered.md`, and that
   file contains **both** `## Repo conventions (AGENTS.md)` and
   `## Repo conventions (aidw/conventions.md)`, with the `AGENTS.md` block first (D16 order).
   This row is unverified by the build results for the same reason as C2: no real-Pi run is
   recorded.
4. **How to tell pass from fail** — On the rendered file:
   `grep -c '^## Repo conventions (AGENTS.md)$'` → `1` and
   `grep -c '^## Repo conventions (aidw/conventions.md)$'` → `1`, with the `AGENTS.md` header
   occurring first. If the `AGENTS.md` block is absent, the marker was not read from the resolved
   prompt file — check that the file is literally named `test.md`, that the marker is a YAML
   boolean `true` on its own line inside the frontmatter, and that the invocation passed the path
   (not the bare name `test`, which resolves the toolkit prompt that has no marker).
5. **Cost, permission or destructive warning** — **Cost and permissions:** identical to C2 (real
   `openrouter` model invocation, `read`/`bash`/`write`/`edit` tools). **Destructive:** use only a
   disposable clone; delete the marker prompt directory and the clone afterwards. The marker file
   is never added to the repository by this scenario.

## 3. Teardown

- **Scenarios T1–T4, L1–L2, C1** create nothing to undo. Temporary fixtures are inside
  `TemporaryDirectory` / pytest `tmp_path`. C1 leaves no run directory (that is its pass
  condition); if a dry run did create one, that is the failure to report — do not let it stand.
- **Scenarios C2–C3** create state under the run-state root
  (`<workspace_root>/.aidw/state/<repo_slug>/runs/<run id>/`, or `~/.aidw/state/<repo_slug>/…`)
  and may modify the disposable clone. Delete the clone directory, and delete the marker prompt
  directory (`$TMPDIR/c11-marker`). Optionally remove the run directories with
  `aidw runs list` to identify them and delete only those run ids. **Destructive warning:** a run
  directory is run history (`state.json`, `run.log`, rendered prompts, artifacts); deleting it is
  irreversible and must target only the run ids this guide created.
- No branch, commit, pull request, cloud resource, environment variable or tracked file is created
  by any scenario. Nothing was installed or mutated in the repository, so no `git checkout`,
  `git reset` or stash operation is required — and none is permitted by this guide.

## 4. Could not be exercised in this environment

- **Real Pi invocations (C2, C3).** The build results record no real-Pi run: every row is a
  credential-free gate, and this repo's rule is that no test may invoke a real Pi model. The
  end-to-end rendered `prompts/<stage>.rendered.md` therefore carries no recorded outcome; a
  developer with Pi installed, an authenticated `openrouter` credential and a spend budget must
  produce that evidence. Neither row is a pass in this guide.
- **Provider credentials and model spend.** Nothing in this tree declares the environment variable
  or account that authenticates Pi to `openrouter` (only `provider: openrouter` and
  `model: openrouter/openai/gpt-5.6-luna` appear in `agent-configs/tester.yaml`), so the guide
  cannot confirm a working credential or a price. That must be resolved in your own environment.
- **Pi's own project-instructions delivery (§5.5).** The premise of the change — that Pi already
  loads the target `AGENTS.md` at `cwd` = target root, and that `no_context_files: true` removes
  it — is a Pi behaviour. It cannot be observed from this repository's gates; only a live Pi
  session (C2/C3, ideally with and without `no_context_files: true`) can confirm that the agent
  still receives `AGENTS.md` while the renderer no longer duplicates it. No agent config in this
  tree sets `no_context_files`, so the opt-in's motivating case has no in-repo fixture.
- **Lint row — unverified in the build results.** The build results mark the `Lint` row
  `unverified` with the reason: this repository configures no linter (`AGENTS.md`: "`pytest` is
  the only verification"; `design.md` §15). That row stays unverified here; there is no command to
  run and this guide adds none.
- **No deployed stack, browser or cloud surface exists for this change**, so nothing of that kind
  is omitted — there is simply no scenario to run. If a future change to this channel touches a
  deployed service, that environment, not a normal developer machine, would be required.
