# Integration Test Guide — 05-S1.2

**Branch:** `05-S1.2`
**Change under test:** `I4 update-architecture` gated on `when=paths-changed`, with the
`docs/architecture` registry default, the absent-vs-empty replacement rule, and the
`aidw doctor` warning for an enabled `I4` whose effective trigger set is empty.

## 1. What this guide covers

This is a hand-run procedure for exercising the S1.2 change on branch `05-S1.2`. It walks the
surfaces the change actually touches: the repository's own test tooling (the focused S1.2 test
selection and the fake-stage `implement` tests), the `aidw doctor` command (on this repository and
against four small scratch configurations), and the `aidw implement --dry-run` planning output.
It does not cover a live Pi-backed `implement` run, a live `--parallel` run, GitHub/PR actions, a
browser flow or any cloud provider, for the reasons in section 4. Everything here is an
instruction: nothing in this document has been executed by the toolkit, and no outcome below is
claimed as observed by this guide.

Run every command from the `aidt` checkout root (the directory containing `pyproject.toml` and
`aidw/`). The `aidw` commands in this guide assume the installed package from this checkout, which
is what `uv run --frozen aidw ...` uses in this repository.

## 2. Scenarios

### 2.1 Repository tooling — focused automated checks

**Prerequisites.** A checkout of branch `05-S1.2`; `uv` installed; network access only if the
frozen environment is not already cached; no running workflow needed.

**Command(s) or steps.**

```bash
uv sync --frozen
uv run --frozen pytest tests/test_implement_workflow.py tests/test_doctor.py tests/test_stage_registry.py tests/test_plan_stages.py tests/test_design_doc.py tests/test_workflow_stages_doc.py tests/test_target_repo_config_doc.py
```

For the full gate (optional, slower), also run:

```bash
uv run --frozen pytest
```

**Expected observable result.** `uv sync --frozen` exits 0 and reports the frozen environment is
satisfied. The focused `pytest` invocation exits 0 with no failures or errors. The build results
record this seven-file selection as passing with 428 tests; the full suite is recorded there as
`2265 passed in 58.25s`. Your run is the observation — use its own summary line.

**How to tell pass from fail.** Pass: both commands exit 0 and the pytest summary reports zero
failed/error tests. Fail: a non-zero exit, any `FAILED` line, a collection error, or a frozen-lock
error from `uv sync --frozen` (a stale `uv.lock` is a build failure in this repository). Do not
treat the exact test count as the check; the discriminator is the zero-failure summary and exit 0.

**Cost, permission or destructive warning.** None. `pytest` creates temporary repositories under
the system temporary directory and removes them; it does not spend model tokens, call GitHub, or
touch a cloud account.

### 2.2 Repository tooling — `I4` gating through the fake-stage `implement` tests (no Pi)

**Prerequisites.** The same checkout and environment as 2.1. No Pi credentials or model account
are needed: these tests replace `run_stage` with a recording fake, so no model is invoked.

**Command(s) or steps.**

```bash
uv run --frozen pytest tests/test_implement_workflow.py -k i4
uv run --frozen pytest tests/test_stage_registry.py::test_i4_carries_paths_changed_and_its_architecture_default
uv run --frozen pytest tests/test_plan_stages.py::test_i4_uses_the_registry_default_but_explicit_empty_stays_empty
uv run --frozen pytest tests/test_doctor.py::test_doctor_warns_only_for_enabled_i4_with_an_empty_effective_path_set
```

**Expected observable result.** Each invocation exits 0. The selected `test_implement_workflow.py`
tests cover: an unrelated change set records `update-architecture` as `skipped` with a reason
naming `docs/architecture`, and the run still ends `succeeded`; a change under
`docs/architecture/ARCHITECTURE.md` runs it; a declared `docs/diagrams` prefix replaces the default
and runs it; explicit `when_paths: []` runs it unconditionally; an unresolvable change set runs it;
and the `--parallel` member filter withholds it before dispatch. The registry test pins
`when == "paths-changed"` and the `("docs/architecture",)` default. The planning test pins default
/ replace / explicit-empty. The doctor test pin covers the four-case warning matrix.

**How to tell pass from fail.** Pass: all four commands exit 0 with zero failures. Fail: any
non-zero exit or a failure in one of the named node ids. A test that is silently deselected is not
a pass for that case — check the summary reports a non-zero number of tests for each command.

**Cost, permission or destructive warning.** None. Temporary repositories only; no model, GitHub
or cloud calls.

### 2.3 Custom CLI — `aidw doctor` on this repository

**Prerequisites.** A checkout of branch `05-S1.2` with the frozen environment installed (2.1).
`aidw doctor` is read-only.

**Command(s) or steps.**

```bash
uv run --frozen aidw doctor
```

**Expected observable result.** The report prints an `architecture trigger` row. On this
repository there is no `aidw/config.yaml`, so the row is `OK` with detail
`I4 update-architecture not enabled`. The report ends with a summary line of the form
`N checks: 0 failed, M warning(s)`; the build results record 22 checks with 0 failed and 2
warnings (dirty working tree, missing `.mcp.json`), which are expected while the branch is
uncommitted.

**How to tell pass from fail.** Pass: the `architecture trigger` row is present and not `warn` or
`fail`; no line names `I4 update-architecture` with a WARN. Fail: an `architecture trigger` row
with status `warn`/`fail`, or a missing row. Exit code 0 is expected when there are no `fail`
checks, but a warn-only report still exits 0; do not confuse an unrelated warning line with this
check.

**Cost, permission or destructive warning.** None. Read-only inspection.

### 2.4 Custom CLI — `aidw doctor` warning matrix in a scratch repository

**Prerequisites.** A scratch directory that is a Git work tree (a fresh `git init` is enough) and a
writable shell. Run from the `aidt` checkout root. No Pi or GitHub credentials are needed.

**Command(s) or steps.** Create the scratch repository once:

```bash
scratch=$(mktemp -d)
git init -q "$scratch"
mkdir -p "$scratch/aidw"
```

Then write one of the four configurations below to `"$scratch/aidw/config.yaml"`, run the doctor
command, and inspect only the `architecture trigger` line:

```bash
uv run --frozen aidw --repo "$scratch" doctor 2>&1 | grep "architecture trigger"
```

| Case | `aidw/config.yaml` content | Expected `architecture trigger` row |
|------|----------------------------|--------------------------------------|
| Enabled, explicit empty | `schema_version: 1`<br>`workflows:`<br>`  implement:`<br>`    stages:`<br>`      - id: I4`<br>`        when_paths: []` | `warn` — "`I4 update-architecture` has `when_paths: []`, so it runs unconditionally; declare docs/architecture plus any diagram-input paths in its when_paths, or remove the empty list to use the toolkit default." |
| Enabled, non-empty | Same, with `when_paths: [docs/diagrams]` | `ok` — "I4 update-architecture declares docs/diagrams" |
| Enabled, key absent | Same, with the `when_paths` line removed | `ok` — "I4 update-architecture uses the toolkit default docs/architecture" |
| Disabled, explicit empty | Same as case 1 plus `enabled: false` on the `I4` entry | `ok` — "I4 update-architecture not enabled" |

**Expected observable result.** Case 1 prints exactly one WARN row for `architecture trigger`, and
its detail contains both `docs/architecture` and `diagram-input`. Cases 2–4 print an `ok` row with
the details shown in the table and no WARN naming `I4`.

**How to tell pass from fail.** Pass: the `architecture trigger` row's status and detail match the
row for that case. Fail: case 1 is `ok` or missing the warning, case 2/3/4 shows a WARN naming `I4`,
or the row is absent. Do **not** use the process exit code as the discriminator: the scratch
repository has no remote, no agent configs and no `.mcp.json`, so unrelated checks may warn or fail
and make `doctor` exit non-zero. The `grep` line is the check.

**Cost, permission or destructive warning.** None. Writes only inside the scratch directory; the
doctor command is otherwise read-only.

### 2.5 Custom CLI — `aidw implement --dry-run` plans `I4` in position

**Prerequisites.** A checkout of branch `05-S1.2` with the frozen environment installed. The task
prompt `docs/task-prompts/05-S1.2-prompt.md` must exist (it does on this branch). No other
`implement` run for branch `05-S1.2` may be marked running. Pi is not needed: `--dry-run` plans
and returns before any stage agent is invoked.

**Command(s) or steps.**

```bash
uv run --frozen aidw implement docs/task-prompts/05-S1.2-prompt.md --dry-run
```

**Expected observable result.** The command exits 0, prints one line per planned stage, and ends
with `dry-run complete; Pi not invoked`. The plan contains the line
`I4 update-architecture [succeeded] (planned) agent=implementer model=` followed by the resolved
model name. This is the planning check: the carried `paths-changed` token must not remove `I4` from
the plan, and a dry run evaluates no change set, so `I4` appears regardless of whether the tree
touches `docs/architecture`.

**How to tell pass from fail.** Pass: exit 0, the `dry-run complete; Pi not invoked` line, and the
`I4 update-architecture [succeeded] (planned)` line present. Fail: a non-zero exit, a missing `I4`
plan line, or any attempt to invoke Pi. The absence of a `skipped` `I4` line in a dry run is
expected and is not a failure — dry runs evaluate nothing.

**Cost, permission or destructive warning.** No model spend and no Git/GitHub writes, but a dry
run still creates a run record under the workspace state root (`create_run` writes `state.json`).
It also holds the per-worktree run lock while it runs. Do not run it concurrently with a real
`implement` run for the same worktree. The teardown section removes the run directory.

### 2.6 Browser UI flows and external/cloud actions — no scenarios

No changed file, build-results row or task-prompt statement points at a browser screen, a web
route, an AWS/cloud command or any other external provider action. The change is confined to the
Python registry/runner/doctor code, the configuration/documentation contract and the tests above,
so there is no browser or cloud scenario to run. This is a statement about the change's surface,
not a claim that such flows were exercised.

## 3. Teardown

- Remove the scratch repository created in 2.4, along with the variable pointing at it:

  ```bash
  rm -rf "$scratch"
  unset scratch
  ```

- Remove the run directory created by the dry run in 2.5. The dry-run output prints a `run:` line;
  use that run id (not the id of any real run) in the prompt below:

  ```bash
  state_root=$(uv run --frozen aidw config show | sed -n 's/^state root: \(.*\) (.*/\1/p')
  read -r -p "run id from the dry run's 'run:' line: " run_id
  rm -rf "$state_root/runs/$run_id"
  ```

  If you did not run 2.5, skip this step; it removes nothing.

- The focused tests in 2.1 and 2.2 clean up their own temporary repositories; no manual cleanup is
  required beyond confirming no `*-pytest-*` directories were left under the toolkit `runs/` tree.
- `aidw doctor` in 2.3 creates nothing.
- No branches, commits, worktrees, deployed resources, environment variables or cloud resources
  are created by any scenario in this guide. If you separately chose to run a live `implement` run
  (not part of this guide), its worktree, branch, run state and PR are yours to remove; see
  section 4.

## 4. Could not be exercised in this environment

- **A live Pi-backed `implement` run observing the actual runtime skip/run decision.** The
  skip/run rows in the build results are verified by the fake-stage tests in 2.2, not by a live
  model run. A live confirmation needs Pi model credentials, a prepared task worktree and task
  prompt, approved gates, and real model spend; the same run then continues through `I5`, `I8`,
  `I9`, `I7` and `I6`, where `I6` opens a pull request and performs GitHub writes. This guide does
  not include that run. A disposable target repository with a throwaway GitHub remote, a prepared
  `aidw prompt` worktree and Pi credentials would exercise it. Expected evidence there would be
  `state.json`/`run.log` showing `update-architecture` as `skipped` with the reason
  `no changed path matches the declared when_paths (docs/architecture): ...`, `error` unset, and
  the run still succeeding; that expected shape is recorded from the tests, not observed here.
- **A live `--parallel` run.** The parallel member-filter path is covered by the fake-stage test in
  2.2. Confirming it against a live run has the same Pi, worktree and GitHub prerequisites as the
  previous item, plus `--parallel`, and is not exercised here.
- **A repository with a custom `paths.architecture_dir` and no declared `when_paths`.**
  `docs/target-repo-config.md` says such a repository must declare its own `when_paths` or `I4`
  watches the literal `docs/architecture` and skips perpetually. That behaviour needs a live run
  (or a fake-stage harness, as in 2.2) and is not exercised by the hand-run scenarios here.
- **A live `aidw doctor` in a fully configured target repository.** The scratch matrix in 2.4
  exercises the warning decision without a real remote, agent configs or `.mcp.json`, so
  unrelated doctor rows are not meaningful there. A fully configured target repository would be
  needed to see the whole report green apart from its own expected warnings.
- **The pull request.** The build results record that no PR exists yet (`/pr` owns creating it).
  This guide does not open, review or merge a PR.
- **Lint.** The build results record the lint row as **unverified** because this repository
  configures no linter, formatter or type-checker; `AGENTS.md` states that `pytest` is the only
  verification. This guide carries that row as unverified for the same reason and does not invent
  a lint command.
