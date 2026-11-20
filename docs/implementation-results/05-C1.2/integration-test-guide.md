# Integration Test Guide — C1.2: resolve gate commands from the target's actual gates heading, and diagnose misses

**Branch:** `05-C1.2`
**Source of record:** `docs/implementation-results/05-C1.2/build-results.md`
**Task prompt:** `docs/task-prompts/05-C1.2-prompt.md`

## 1. What this guide covers

This is a hand-run procedure for a human to confirm, in their own environment, the change on
branch `05-C1.2`: the prompt workflow's evidence bundle now recognises a target repo's gate
commands under `## Gates` **or** `## Gate commands` **or** a config-declared heading
(top-level `gates_heading`, value = the full `## `-prefixed heading line), and `aidw doctor`
gains an advisory `gates heading` WARN that names a gates-like heading nothing recognises. It
walks the surfaces the changed files and the task prompt point at: the `aidw doctor` check
(`aidw/doctor.py`), the target config loader (`aidw/target_config.py`, key accepted / empty
value refused), and the evidence bundle's gate-commands element read through
`aidw/prompts.py` and `aidw/workflows/prompt.py`.

**Nothing in this guide has been executed by the toolkit.** No scenario below was run while
writing it: every expected result is derived from the changed source, the changed tests, the
task prompt and the build results, not observed here. You run these; the toolkit did not.

## 2. Scenarios

Grouped by surface kind. The change touches **no browser UI flow** and **no external
(cloud-provider) surface** — no changed file, build-results row or task-prompt statement points
at one — so those two groups have no scenario, by evidence rather than by omission.

All scenarios work in a throwaway clone so the checked-out `05-C1.2` tree is never modified.
Set these shell variables first (replace the paths with real ones):

```bash
TOOLKIT=$(git rev-parse --show-toplevel)   # the aidt checkout on branch 05-C1.2
SCRATCH=$(mktemp -d)/target                # disposable target repo
git clone "$TOOLKIT" "$SCRATCH"
```

### A. Repo tooling — the target repo's own commands

#### S1 — `aidw doctor` reports an unrecognised gates-like heading as an advisory WARN

1. **Prerequisites.** The `SCRATCH` clone from above (a git checkout that doctor already
   accepts). `uv` on `PATH` (the toolkit's own gate list starts with `uv sync --frozen`). A
   baseline: `cd "$TOOLKIT" && uv sync --frozen` has been run at least once. No credentials.
   The clone's `AGENTS.md` carries the toolkit's suffixed canonical heading
   `## Gates — run exactly these, and only these`, and `aidw/conventions.md` carries no
   gates-like heading; the clone has no `aidw/config.yaml`.
2. **Command(s) or steps.**
   ```bash
   cd "$TOOLKIT"

   # Baseline: the suffixed canonical heading must already be silent.
   uv run --frozen aidw --repo "$SCRATCH" doctor

   # Now write a heading nothing recognises (capital C is deliberate).
   uv run --frozen python - "$SCRATCH" <<'PY'
   import sys, pathlib
   p = pathlib.Path(sys.argv[1]) / "AGENTS.md"
   text = p.read_text(encoding="utf-8")
   p.write_text(text.replace("## Gates — run exactly these, and only these",
                             "## Gate Commands"), encoding="utf-8")
   PY

   uv run --frozen aidw --repo "$SCRATCH" doctor
   ```
   `--repo` is the app-level option and precedes the subcommand; `doctor` itself takes no
   per-command flag (`aidw/cli.py`).
3. **Expected observable result.** The baseline run prints a `gates heading` row as
   `[  ok  ] gates heading ... every gates-like heading is recognised`. After the edit the row
   is a `[ warn ] gates heading` row whose detail begins
   ``unrecognised gate heading(s): `AGENTS.md`: `## Gate Commands` `` and continues with the two
   fixes — rename to `## Gates` or `## Gate commands`, or declare the heading verbatim
   (including the `## ` prefix) as the top-level `gates_heading` key. The run still exits **0**
   — WARN never fails `run_doctor` — provided no *other* check FAILs on your machine.
4. **How to tell pass from fail.** Pass: exactly one `gates heading` WARN naming both the source
   file (`AGENTS.md`) and the heading (`## Gate Commands`), and the process exit status is 0.
   Fail: the row stays `ok` while `## Gate Commands` is present (the diagnosis is missing), the
   WARN omits the file or the heading, the two fixes/`gates_heading` are not named, or the WARN
   turns into a `fail` row / non-zero exit. If some *unrelated* row FAILs (for example a
   machine-specific `gh` or `mcp config` state), that is not this scenario's failure — judge
   only the `gates heading` row and whether *it* introduced a failure. On the build machine the
   recorded doctor run was `23 checks: 0 failed, 2 warning(s)` with `gates heading` `ok`.
5. **Cost, permission or destructive warning.** None. Read-only doctor checks plus writes to
   files inside the disposable `SCRATCH` clone only. Do not run it against a repo you care
   about: step 2 edits that repo's `AGENTS.md` (teardown deletes the clone).

#### S2 — a recognised heading, a declared heading, and config-loader acceptance

1. **Prerequisites.** S1's `SCRATCH` clone, freshly restored so its `AGENTS.md` again carries
   `## Gates — run exactly these, and only these` (`git -C "$SCRATCH" checkout -- AGENTS.md`).
   Write access to `$SCRATCH/aidw/config.yaml` (which does not exist yet; `schema_version` is
   required whenever it does — `docs/target-repo-config.md`). No credentials.
2. **Command(s) or steps.**
   ```bash
   cd "$TOOLKIT"

   # (a) alias heading: recognised with no config at all
   printf '\n## Gate commands\n\n```bash\nuv run --frozen pytest\n```\n' \
     >> "$SCRATCH/aidw/conventions.md"
   uv run --frozen aidw --repo "$SCRATCH" doctor

   # (b) a non-standard heading plus the declaration that makes it recognised
   git -C "$SCRATCH" checkout -- aidw/conventions.md AGENTS.md
   uv run --frozen python - "$SCRATCH" <<'PY'
   import sys, pathlib
   root = pathlib.Path(sys.argv[1])
   p = root / "AGENTS.md"
   p.write_text(p.read_text(encoding="utf-8").replace(
       "## Gates — run exactly these, and only these", "## Verification gates"),
       encoding="utf-8")
   (root / "aidw" / "config.yaml").write_text(
       'schema_version: 1\ngates_heading: "## Verification gates"\n', encoding="utf-8")
   PY

   # Loader acceptance: exit 0, no unknown-key / gates_heading ERROR on stderr.
   uv run --frozen aidw --repo "$SCRATCH" config show
   uv run --frozen aidw --repo "$SCRATCH" doctor
   ```
3. **Expected observable result.** (a) `gates heading` stays `ok`
   (`every gates-like heading is recognised`). (b) `aidw config show` exits 0 and prints the
   six root/config-file lines; no error naming `gates_heading` and no
   ``unknown key `gates_heading` `` on stderr. `aidw doctor` again reports `gates heading` as
   `ok` — the declared heading silences the WARN. Note honestly: `aidw config show` does **not**
   print a `gates_heading` leaf, because `resolve_config` in `aidw/target_config.py` does not
   merge that key into the resolved leaves; it is read directly by `_gate_block` and by the
   doctor check. So the loader acceptance is observable as "exit 0 and no error", not as a
   printed value.
4. **How to tell pass from fail.** Pass: in (a) no WARN for `## Gate commands`; in (b) `config
   show` exits 0 with no `gates_heading` error *and* the doctor's `gates heading` row is `ok`
   *while* `AGENTS.md` still carries the non-standard `## Verification gates`. Fail: a
   ``unknown key `gates_heading` `` refusal (the key never reached `TOP_LEVEL_KEYS`), any ERROR
   naming `gates_heading` for a `## `-prefixed value, or a `gates heading` WARN surviving the
   declaration (the doctor decided "unrecognised" before loading the target config).
5. **Cost, permission or destructive warning.** None. Writes stay inside `$SCRATCH`; `config
   show` and `doctor` are read-only.

#### S3 — an empty `gates_heading` is refused, naming the field

1. **Prerequisites.** The `SCRATCH` clone with `aidw/config.yaml` present (created in S2(b)) and
   `schema_version: 1` in it. No credentials.
2. **Command(s) or steps.**
   ```bash
   cd "$TOOLKIT"
   uv run --frozen python - "$SCRATCH" <<'PY'
   import sys, pathlib
   p = pathlib.Path(sys.argv[1]) / "aidw" / "config.yaml"
   p.write_text('schema_version: 1\ngates_heading: ""\n', encoding="utf-8")
   PY
   uv run --frozen aidw --repo "$SCRATCH" config show; echo "exit=$?"
   uv run --frozen aidw --repo "$SCRATCH" doctor;       echo "exit=$?"
   ```
3. **Expected observable result.** `config show` prints to stderr a line carrying
   `` `gates_heading` must be a non-empty string, got '' `` and exits **1** (`EXIT_STAGE_FAILURE`
   in `aidw/cli.py`), with no resolved `config:` values printed. `doctor` reports the target
   config problem (ERROR/FAIL from its target-config check) and exits **1**, rather than
   treating the empty heading as "match every line".
4. **How to tell pass from fail.** Pass: one ERROR naming `gates_heading`, exit status 1 from
   `config show`, and the value dropped (doctor then behaves as if no heading were declared).
   Fail: exit 0 for the empty value, an error that does not name `gates_heading`, a crash /
   traceback instead of the refusal, or a following `gates heading` `ok` that implies
   `startswith("")` matched everything.
5. **Cost, permission or destructive warning.** None. One file write inside `$SCRATCH`.

#### S4 — the branch's own verification gates still hold

1. **Prerequisites.** The `05-C1.2` checkout, `uv` on `PATH`, network access for the frozen sync
   if the environment is not already synced (no model, no credentials). These are exactly the
   repo's gates from `AGENTS.md`; the build results already record them green for tree
   `ca12234bcb33`.
2. **Command(s) or steps.**
   ```bash
   cd "$TOOLKIT"
   uv sync --frozen
   uv run --frozen pytest
   uv run --frozen aidw doctor
   uv run --frozen aidw agents validate --strict
   uv run --frozen aidw prompts check
   ```
3. **Expected observable result.** `uv sync --frozen` reports a resolved environment; `pytest`
   ends `2367 passed` (the recorded count — a different total is fine only if it reflects the
   tests you have); `doctor` reports `0 failed` with the `gates heading` row `ok`; agents
   validation reports `0 error(s)`; `prompts check` reports `0 error(s), 0 warning(s)`.
4. **How to tell pass from fail.** Pass: every command exits 0 and the pytest summary shows no
   failures. Fail: any non-zero exit, a pytest failure/error, a FAIL row in `doctor`, or the
   `gates heading` row going to `warn`/`fail` on the toolkit's own
   `## Gates — run exactly these, and only these` heading. Recorded doctor output was
   `23 checks: 0 failed, 2 warning(s)`, where the two warnings are the pre-existing dirty-tree
   and missing-MCP ones — a `gates heading` warning here would be a regression.
5. **Cost, permission or destructive warning.** None beyond disk/time: the suite spawns many
   temporary git repositories. `uv run --frozen pytest` behaves as configured (parallel,
   `addopts = "-q -n auto"`); do not add or edit lockfiles to make it pass.

### B. Custom CLI / TUI commands — the gate-commands read channel

#### S5 — the read channel: `## Gate commands`, `## Gate Commands`, and the declared heading

1. **Prerequisites.** The `SCRATCH` clone removed or reset to a tree without `aidw/config.yaml`
   (`rm -f "$SCRATCH/aidw/config.yaml"`), the toolkit environment synced (S4 step 1), and the
   `aidw/config.yaml`-free clone's `AGENTS.md` restored
   (`git -C "$SCRATCH" checkout -- AGENTS.md`). No credentials, no model, no network.
   The probe calls the private helper `aidw.workflows.prompt._gate_block` with a
   `TargetRepo(root=..., git_dir=..., common_dir=...)`, the construction the changed test
   `tests/test_prompt_workflow.py::test_c12_gate_commands_heading_alone_supplies_the_block`
   uses — it is not a supported public interface, so treat it as an inspection probe, not an API
   promise. (Working-directory caveat: `uv run` must be executed from `$TOOLKIT` so the package
   resolves; `TargetRepo` is given the scratch root explicitly.)
2. **Command(s) or steps.**
   ```bash
   cd "$TOOLKIT"

   # (a) `## Gate commands` supplies commands instead of degrading
   uv run --frozen python - "$SCRATCH" <<'PY'
   import pathlib, sys
   root = pathlib.Path(sys.argv[1])
   (root / "aidw" / "conventions.md").write_text(
       "# Conventions\n\n## Gate commands\n\n```bash\nprobe gate --check\n```\n",
       encoding="utf-8")
   PY
   uv run --frozen python - "$SCRATCH" <<'PY'
   import pathlib, sys
   from aidw.paths import TargetRepo
   from aidw.workflows.prompt import _gate_block
   root = pathlib.Path(sys.argv[1])
   print(_gate_block(TargetRepo(root=root, git_dir=root / ".git", common_dir=root / ".git")))
   PY

   # (b) capital C degrades: case is significant
   uv run --frozen python - "$SCRATCH" <<'PY'
   import pathlib, sys
   root = pathlib.Path(sys.argv[1])
   (root / "aidw" / "conventions.md").write_text(
       "# Conventions\n\n## Gate Commands\n\n```bash\nprobe gate --check\n```\n",
       encoding="utf-8")
   PY
   uv run --frozen python - "$SCRATCH" <<'PY'
   import pathlib, sys
   from aidw.paths import TargetRepo
   from aidw.workflows.prompt import _gate_block
   root = pathlib.Path(sys.argv[1])
   print(_gate_block(TargetRepo(root=root, git_dir=root / ".git", common_dir=root / ".git")))
   PY

   # (c) a declared heading must be the full `## `-prefixed line; a bare title is not recognised
   uv run --frozen python - "$SCRATCH" <<'PY'
   import pathlib, sys
   root = pathlib.Path(sys.argv[1])
   (root / "aidw" / "conventions.md").write_text(
       "# Conventions\n\n## Verification gates\n\n```bash\nprobe gate --check\n```\n",
       encoding="utf-8")
   (root / "aidw" / "config.yaml").write_text(
       'schema_version: 1\ngates_heading: "## Verification gates"\n', encoding="utf-8")
   PY
   uv run --frozen python - "$SCRATCH" <<'PY'
   import pathlib, sys
   from aidw.paths import TargetRepo
   from aidw.workflows.prompt import _gate_block
   root = pathlib.Path(sys.argv[1])
   print(_gate_block(TargetRepo(root=root, git_dir=root / ".git", common_dir=root / ".git")))
   PY
   uv run --frozen python - "$SCRATCH" <<'PY'
   import pathlib
   from aidw.workflows.prompt import _gates_section
   text = "# Conventions\n\n## Verification gates\n\n```bash\nprobe gate --check\n```\n"
   print("prefixed:", _gates_section(text, "## Verification gates"))
   print("bare:    ", _gates_section(text, "Verification gates"))
   PY
   ```
3. **Expected observable result.** (a) the printed block starts with `## Gate commands` and
   contains `probe gate --check`, with no `unavailable` text. (b) the output is exactly
   `unavailable — could not be read` (`_EVIDENCE_UNAVAILABLE`), because `## Gate Commands` is
   not a recognised heading. (c) the `_gate_block` output starts with `## Verification gates`
   and contains `probe gate --check`, loaded from `<scratch>/aidw/config.yaml` (the target root);
   the `_gates_section` probe prints the section for the `## `-prefixed value and `None` for the
   bare title.
4. **How to tell pass from fail.** Pass: (a) real commands, not `unavailable`; (b) exactly the
   `unavailable — could not be read` string (a bundle that silently shows nothing, or an
   exception, fails); (c) declared heading recognised and the bare title *not* recognised. Fail:
   (a) `unavailable` despite `## Gate commands`; (b) commands appearing for `## Gate Commands`
   (case accidentally lowered somewhere); (c) either a bare title matching (the `startswith`
   rule broken in the unsafe direction) or the declared heading not matching (the value format
   or the target-relative load broken).
5. **Cost, permission or destructive warning.** None. No model, no network, no credentials; the
   probe only reads the scratch files. It does call a private function — if that function is
   renamed later, this probe breaks where the public CLI would not.

#### S6 — a real `aidw prompt` run writes the gate commands into the evidence bundle

1. **Prerequisites.** This is the only scenario that invokes a real model. Required: `pi` on
   `PATH` and authenticated with a model provider (`aidw doctor` reports `pi` `ok`); a provider
   account with available credit; `gh` authenticated only if your workflow path needs it; a
   target repo where the roadmap file under `paths.roadmap_dir` has a `C1.2`-style entry and a
   task prompt file under `paths.task_prompts_dir` (the toolkit's own
   `docs/tasks/05 - Pipeline efficiency.md` carries the `C1.2` entry and
   `docs/task-prompts/05-C1.2-prompt.md` exists, so `$SCRATCH` — a clone of the toolkit — is a
   usable target); a clean `$SCRATCH` working tree with the gate section you want to see
   (`## Gate commands` in `$SCRATCH/aidw/conventions.md`, or `## Gates` in its `AGENTS.md`); the
   target root's config free of a bad `gates_heading`. Optionally `--no-fetch` if offline, and
   a `git` identity that can create a worktree and branch.
2. **Command(s) or steps.** (Read the recorded note first: `--dry-run` plans only and returns
   before any evidence bundle is written, so it cannot show this element; only a real author
   stage does. That is derived from `aidw/workflows/prompt.py`'s dry-run branch, not observed
   here.)
   ```bash
   cd "$TOOLKIT"
   uv run --frozen aidw --repo "$SCRATCH" prompt 05 C1 C1.2 --no-fetch
   # when it finishes (or blocks), find the run and read the bundle:
   uv run --frozen aidw --repo "$SCRATCH" config show | grep -i 'state root'
   grep -n -A 20 '## Gate commands' \
     "<state root>/<run-id>/stages/task-prompt.evidence.md"
   ```
   The bundle path is `<run_dir>/stages/<stage>.evidence.md` (`_write_evidence_bundle` in the
   changed file); `<run-id>` and the state root are what `aidw config show` reports — do not
   hardcode either. Stage names in that directory are the workflow's own (for example
   `task-prompt`); list the directory rather than assuming one.
3. **Expected observable result.** The command runs the plan and, on success or a `blocked:`
   report, leaves a run directory containing `stages/*.evidence.md`. Each bundle contains a
   section headed `## Gate commands (target repo `AGENTS.md` + `aidw/conventions.md`)` whose body
   reproduces the gate list from the source that carries it — the actual commands, not
   `unavailable — could not be read`. The run's own exit code reflects the workflow (0 success,
   3 blocked, 1 failure), never the bundle write.
4. **How to tell pass from fail.** Pass: a bundle exists and its gate-commands section contains
   the repo's real commands from the heading you wrote. Fail: the section shows
   `unavailable — could not be read` while a recognised heading is present in `$SCRATCH` (the
   read channel or the target-root config load is broken); a traceback about the bundle; or the
   run dying because the bundle could not be written — the bundle must never fail a run.
5. **Cost, permission or destructive warning.** **Spends money**: one or more real Pi model
   invocations on your provider account. It also creates a branch and a git worktree for
   `05-C1.2`-style branch naming under the workspace root, and writes run state under the state
   root. Commit nothing from it. If you cannot spend, skip this scenario and rely on S5 — say so
   rather than marking it passed.

### C. Browser UI flows

No scenario. No changed file, build-results row or task-prompt statement names a route, page or
rendered screen.

### D. External actions (cloud provider commands)

No scenario. No changed file, build-results row or task-prompt statement names a cloud command,
bucket, role, ARN or environment variable. The only subprocesses the change adds are config and
file reads.

## 3. Teardown

- Delete the disposable target clone: `rm -rf "$(dirname "$SCRATCH")"` (the `mktemp -d`
  parent), which removes every file S1–S5 wrote (`AGENTS.md` heading edits,
  `aidw/conventions.md` appends, `aidw/config.yaml`).
- If you ran S6: remove the worktree and branch it created
  (`git -C "$SCRATCH" worktree list`, then `git -C "$SCRATCH" worktree remove` on the path it
  lists, and delete the branch with `git -C "$SCRATCH" branch -d`), and delete the run
  directory it wrote under the state root that `aidw config show` reports. Run state is
  machine-local and never committed; do not leave `*-pytest-*` directories in the toolkit's
  `runs/` tree if you ran S4 with `pytest` (the suite guards this, but check).
- Delete the created run directory and any `stages/*.evidence.md` you inspected, and any
  temporary directory you made for the bundle output.
- Unset the shell variables this guide set (`TOOLKIT`, `SCRATCH`) if you exported them, and any
  `AIDW_REPO` you set instead of `--repo`.
- Confirm the real checkout is untouched: `git -C "$TOOLKIT" status --short` shows no changes
  beyond what you already had, and `git -C "$TOOLKIT" diff --name-only` lists none of the files
  S1–S5 edited (they were all inside `$SCRATCH`).

## 4. Could not be exercised in this environment

- **`lint` gate — `unverified`.** This repo configures no lint command, so there is nothing to
  run. The build results record this row as `unverified` with that reason (AGENTS.md: "no
  linter, formatter, or type-checker is configured"). This guide cannot turn it into a pass;
  the closest honest check is `git diff --check`, which the build results record as passing.
- **S6 (a real `aidw prompt` run and its written evidence bundle)** cannot be exercised without
  a real Pi installation, an authenticated model provider and available credit, plus a target
  repo with the roadmap entry and task prompt in place. It needs a developer machine with model
  access; a CI job with no provider credentials cannot run it. If your environment has no
  credits, treat the bundle's rendered content as covered only by the recorded suite
  (`test_c12_gate_commands_heading_supplies_the_bundle_gate_commands`) and say so.
- **A live, deployed stack** is irrelevant to this change: it is local config/file reading plus
  one advisory doctor check, with no deployable artefact. Nothing here needs a production
  account.
- **Machine-dependent doctor rows** (`pi`, `gh`, `mcp config`, target-config state) make the
  overall `0 failed` count environment-specific; only the `gates heading` row is this change's
  concern. The recorded run (`23 checks: 0 failed, 2 warning(s)`) is from the build machine, not
  from yours.
