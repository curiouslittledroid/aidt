# Integration-test guide — 05-S1.1: Path-scoped `when_paths` and a gated `I3 update-traceability`

**Branch:** `05-S1.1`
**Recorded evidence:** `docs/implementation-results/05-S1.1/build-results.md`

This is a hand-run procedure. Nothing in it has been executed by the toolkit or by the stage that
wrote it. The build results record what was actually run; the commands below are for a human to
run in their own environment, with their own credentials and their own disposable fixtures.

## 1. What this guide covers

This procedure exercises the `05-S1.1` change on branch `05-S1.1`: `WHEN_PATHS_CHANGED`
(`paths-changed`) joins the stage-condition vocabulary, `I3 update-traceability` carries it, and
a target repo declares the repo-relative prefixes it is gated on through the optional per-stage
`when_paths` field. The guide walks three surfaces — the repository's own focused tests and
verification gates, the target-config CLI (`aidw config show` parsing, canonicalising and
refusing a bad declaration), and the `aidw implement` workflow on a disposable scratch worktree
(a run whose change set touches none of the declared paths records `update-traceability` as
`skipped` without invoking its agent; a touched path runs it; an absent declaration keeps it
unconditional). It also checks the two dispatched paths the build results cover, but a live
`--parallel` group naming `update-traceability` is left to the test suite rather than a second
model-backed run. There is no browser UI, cloud-provider or deployed-stack surface in this
change, so the guide contains no such scenario.

The owned document is written beneath the configured `paths.implementation_results_dir`; the
build results in the same directory are the source of every recorded outcome cited here. In
particular, the build results mark **lint `unverified`** because this repository configures no
linter (`AGENTS.md`: "pytest is the only verification"). That row stays unverified in this
guide; no lint command exists to run.

Paths named as `<workspace root>`, `<state root>` and `<run-id>` are values printed by
`uv run --frozen aidw config show` and `uv run --frozen aidw runs list`. Run the `uv` commands
from the repository root unless a step says otherwise.

## 2. Scenarios

### Repository tooling

#### 2.1 Focused contract tests for the token, the config field and the docs

**Trace:** modified `tests/test_stage_registry.py`, `tests/test_plan_stages.py`,
`tests/test_implement_workflow.py`, `tests/test_target_config.py`,
`tests/test_target_repo_config_doc.py`, `tests/test_workflow_stages_doc.py` and
`tests/test_design_doc.py`; build-results task-specific gate rows ("Registry pins", "Plan pins",
"Config/schema pins", "Doc pins", "Pure matcher", "Serial end-to-end", "`--parallel`
end-to-end").

**Prerequisites**

- A checkout of this branch with the implementation and tests present (committed, or present as
  uncommitted changes in the working tree).
- `uv` is installed and the environment is synchronised.
- No model, GitHub or cloud credentials are needed; these tests use fixture repositories and
  fake stages.

**Command(s) or steps**

```bash
uv sync --frozen
uv run --frozen pytest \
  tests/test_stage_registry.py \
  tests/test_plan_stages.py \
  tests/test_implement_workflow.py \
  tests/test_target_config.py \
  tests/test_target_repo_config_doc.py \
  tests/test_workflow_stages_doc.py \
  tests/test_design_doc.py
```

**Expected observable result**

The selected files collect and run, pytest exits 0, and the summary reports no failures or
errors. The same tests are inside the full suite the build results record as
`2248 passed in 44.46s`; the build results do **not** record a separate count for this focused
selection, so do not compare against an invented subset total.

**How to tell pass from fail**

Pass means exit status 0, no `failed`/`error` entries in the summary, and no collection error.
Any non-zero exit or a named failing test is a fail; the failing test name identifies which
contract (token, matcher, loader, serial/parallel dispatch or documentation pin) broke.

**Cost, permission or destructive warning:** none. These are local, model-free tests.

#### 2.2 Repository gates recorded by the build results

**Trace:** build-results "Top-level verification" rows for `aidw doctor`,
`aidw agents validate --strict`, `aidw prompts check`, `git diff --check` and the full suite.

**Prerequisites**

- The same checkout and synchronised environment as scenario 2.1.
- No model, GitHub or cloud credentials are needed; all four commands are local reads.

**Command(s) or steps**

```bash
uv run --frozen pytest
uv run --frozen aidw doctor
uv run --frozen aidw agents validate --strict
uv run --frozen aidw prompts check
git diff --check
```

**Expected observable result**

- `pytest` exits 0. The build results record `2248 passed in 44.46s`; a different count is not
  itself a failure, but a failure or error is. The build results cite this from the run's own
  recorded gate rather than a fresh run.
- `aidw doctor` exits 0 with `21 checks: 0 failed, 2 warning(s)` when the working tree is dirty
  and `.mcp.json` is absent, exactly as recorded. A different warning count is acceptable; any
  **failed** check is not.
- `aidw agents validate --strict` exits 0 with
  `11 agent config(s): 0 error(s), 0 warning(s)`.
- `aidw prompts check` exits 0 with `0 error(s), 0 warning(s)` for both the toolkit defaults and
  the resolved repo prompts.
- `git diff --check` exits 0 with no output.

**How to tell pass from fail**

Pass requires exit 0 from every command, `0 failed` from `doctor`, and `0 error(s)` plus
`0 warning(s)` from both `agents` and `prompts`, with `git diff --check` printing nothing. A
failed doctor check, any agent/prompt error or warning, a non-zero exit, or whitespace output is
a fail. A different `doctor` warning count alone is not the discriminator.

**Cost, permission or destructive warning:** none. These commands only read the tree and the
machine-local run state.

### Custom CLI commands

The scenarios in this section use a disposable scratch worktree, `99-S9.9`, created from
`05-S1.1`. They never modify the real `05-S1.1` worktree, its roadmap entries or its run history.

#### 2.3 `aidw config show` parses, canonicalises and refuses `when_paths`

**Trace:** `aidw/target_config.py` (`STAGE_KEYS`, `StageConfig.when_paths`, `_parse_when_paths`,
`to_dict`); `docs/schema/aidw-config.schema.json`'s `when_paths` property;
`docs/target-repo-config.md`'s stage-field table; build-results "Config/schema pins" row.

**Prerequisites**

- A checkout of `05-S1.1` with the change present.
- The workspace and state roots. Record them first:

  ```bash
  uv run --frozen aidw config show
  ```

  Keep the `workspace root:` and `state root:` lines. The scratch worktree will be
  `<workspace root>/99-S9.9`.
- No model, GitHub or cloud credentials are needed for this scenario.

**Command(s) or steps**

1. Capture any uncommitted change on `05-S1.1` and create the scratch worktree from it:

   ```bash
   git diff > /tmp/s1.1-wip.patch
   uv run --frozen aidw worktree add 99-S9.9 --base 05-S1.1
   ```

   If the change is already committed on `05-S1.1`, skip the `git diff` line and the
   `git apply` line below.

2. Apply the captured change inside the scratch worktree and confirm it exists:

   ```bash
   WT="<workspace root>/99-S9.9"
   git -C "$WT" apply /tmp/s1.1-wip.patch
   uv run --frozen aidw worktree list
   ```

3. Write a valid target config in the scratch worktree. A declared `stages:` list replaces the
   toolkit's list wholesale, so every core id is present in registry order (`I1`, `I2`, `I3`,
   `I4`, `I5`, `I8`, `I9`, `I7`, `I6`). Only `I3` carries `when_paths`; the duplicate and the
   `./`-and-trailing-slash forms are deliberate, to check canonicalisation.

   ```bash
   cat > "$WT/aidw/config.yaml" <<'YAML'
   schema_version: 1

   workflows:
     implement:
       stages:
         - id: I1
         - id: I2
         - id: I3
           when_paths:
             - ./docs/rules-coverage/
             - docs/traceability
             - docs/rules-coverage
         - id: I4
         - id: I5
         - id: I8
         - id: I9
         - id: I7
         - id: I6
   YAML
   ```

4. Resolve the config and inspect the stage entry:

   ```bash
   cd "$WT"
   uv run --frozen aidw config show | grep '^workflows.implement.stages:'
   ```

5. Replace the valid entry with one bad entry, resolve again, then restore the valid config:

   ```bash
   cd "$WT"
   sed -i.bak 's|./docs/rules-coverage/|../outside|' aidw/config.yaml
   uv run --frozen aidw config show
   mv aidw/config.yaml.bak aidw/config.yaml
   ```

   `sed -i.bak` is the GNU/BSD-portable form; if your `sed` refuses it, edit the file in place
   instead. The exact command used to edit the file is not itself part of the contract.

**Expected observable result**

- Step 4 prints a single `workflows.implement.stages: [...]` JSON line whose `I3` entry carries
  `"when_paths": ["docs/rules-coverage", "docs/traceability"]` — the `./` prefix and trailing
  slash are gone and the duplicate is collapsed, in sorted order.
- Step 5 exits 1 (the CLI's stage-failure status), prints no resolved configuration, and writes
  to stderr an `ERROR` of the form
  `ERROR: aidw/config.yaml: \`workflows.implement.stages[2].when_paths[0]\` must be a
  repo-relative path prefix such as docs/rules-coverage, got '../outside'`. The other stage
  entries are not reported as errors; only the bad entry is dropped.

**How to tell pass from fail**

Pass means the valid declaration resolves to exactly the normalised, sorted, deduplicated
two-value list, and the bad declaration exits non-zero with one `ERROR` naming the dotted entry
path (`workflows.implement.stages[2].when_paths[0]`), not a traceback and not a silently
accepted value. A raw `./docs/rules-coverage/` in the printed list, a missing `when_paths` key,
a zero exit for the bad config, or an error naming a different field is a fail.

**Cost, permission or destructive warning:** none. This is a local config read/write inside the
disposable worktree; no model or external service is contacted.

#### 2.4 A live run whose change set touches no declared path skips `I3`

**Trace:** `aidw/workflows/implement.py` (`change_set_paths`, `paths_changed_reason`,
`withhold_paths_stage`), `aidw/stage_registry.py`'s `I3` entry with `when=WHEN_PATHS_CHANGED`,
and the build-results "Serial end-to-end fake-stage runs — skip when no declared path is touched"
row.

**Prerequisites**

- Scenario 2.3 completed: scratch worktree `99-S9.9` exists and `aidw/config.yaml` declares
  `when_paths: [docs/rules-coverage, docs/traceability]` on `I3`.
- `uv sync --frozen` has run inside `$WT`, and Pi is installed and configured with usable model
  credentials. `I1` and `I2` invoke real agents.
- A scratch task prompt and exactly one roadmap entry exist in the scratch worktree, because
  `aidw implement` derives the branch from the prompt filename and refuses without one matching
  roadmap entry.
- The scratch implementation must not create `docs/rules-coverage` or `docs/traceability`; the
  prompt below says so explicitly.

**Command(s) or steps**

1. Create the scratch task prompt at
   `$WT/docs/task-prompts/99-S9.9-prompt.md`:

   ```markdown
   Task: Disposable fixture for the 05-S1.1 path-scoped condition. Do not change product code.

   Requirements:
   1. Add a short comment to `README.md` naming this scratch fixture.
   2. Do not create or modify `docs/rules-coverage` or `docs/traceability`.

   Done when:
   - `README.md` contains the scratch comment and no file under `docs/rules-coverage` or
     `docs/traceability` was created or modified.

   Deliverables:
   - README.md
   ```

   The filename `99-S9.9-prompt.md` is what derives branch `99-S9.9`; keep it exact.

2. Create the scratch roadmap entry at `$WT/docs/tasks/99 - Scratch.md`:

   ```markdown
   # Phase 99: Scratch

   ## Epic S9: Scratch

   - [ ] **S9.9. Scratch path-scoped condition fixture** (Design 8.2)
     - Done when: the live implement run records `update-traceability` as skipped when no
       declared path is touched.
   ```

3. Validate the scratch roadmap and confirm the branch/worktree:

   ```bash
   cd "$WT"
   uv run --frozen aidw tasks --validate
   uv run --frozen aidw worktree list
   ```

4. Run the workflow with the PR gate explicitly denied, so the run stops before `I6 pr` and
   cannot push or open a pull request:

   ```bash
   cd "$WT"
   uv run --frozen aidw implement docs/task-prompts/99-S9.9-prompt.md \
     --deny-gates approve-implementation-pr
   ```

5. Record the run id, then inspect the run and its log:

   ```bash
   uv run --frozen aidw runs list
   uv run --frozen aidw runs show <run-id>
   grep -n 'update-traceability' <state root>/runs/<run-id>/run.log
   ```

   `<run-id>` is the newest run whose branch is `99-S9.9`; `<state root>` is the value recorded
   in scenario 2.3.

**Expected observable result**

- Steps 1–3 succeed: `aidw tasks --validate` exits 0, and `aidw worktree list` shows `99-S9.9`
  at `<workspace root>/99-S9.9`.
- Step 4 runs `I1` and `I2`, then prints a stage block headed
  `stage:  I3 update-traceability [skipped]` followed by
  `skipped: no changed path matches the declared when_paths (docs/rules-coverage, docs/traceability): the change set does not touch any of them`.
  No `update-traceability` agent invocation appears.
- `I4 update-architecture` is **not** skipped by this declaration (the condition is attached to
  `I3` only), and the run continues through the remaining stages.
- Step 5 shows `update-traceability` as `skipped` with no `error:` line, and `run.log` contains
  the same skip reason. No `pr` stage is recorded, because the denied gate stops the run before
  `I6`.
- The run exits 3 at the `approve-implementation-pr` gate, the expected outcome of the explicit
  denial, not a failure of the path condition.

**How to tell pass from fail**

Pass requires all of: the `I3 update-traceability [skipped]` block with exactly the reason above,
no `update-traceability` agent invocation, `I4` not skipped by the declaration, the same
`skipped` record and reason in `runs show`/`run.log`, no `pr` stage, and no error recorded on the
`update-traceability` stage. A succeeded/running `update-traceability`, a missing skip reason, an
error on the stage, a `pr` stage, or the run stopping before `I3` (for example because `I2`
failed) is a fail. Exit 3 is expected here; do not use it alone as the discriminator.

**Cost, permission or destructive warning:** this spends real model credit for `I1`, `I2` and
the later stages. It writes only inside the disposable `99-S9.9` worktree and the machine-local
run state. The denied gate must stop before `I6 pr`, so no commit, push or pull request is
intended; if a `pr` stage appears, stop and inspect the run. Do not run this in the real
`05-S1.1` worktree.

#### 2.5 A touched declared path runs `I3`

**Trace:** the same workflow code and the build-results "Serial end-to-end fake-stage runs — run
when one is touched" row; `aidw/workflows/implement.py`'s `paths_changed_reason` matching rule.

**Prerequisites**

- Scenario 2.4 completed and left the scratch run blocked at the denied gate, with the
  `update-traceability` stage recorded `skipped`.
- The scratch worktree still exists, and `05-S1.1`'s change set (which this scratch branch
  carries) touches `aidw/` relative to `main`.
- Pi credentials are still available; this scenario re-runs `I3` and the stages after it.

**Command(s) or steps**

1. Change only `I3`'s declaration in `$WT/aidw/config.yaml` to a prefix the change set definitely
   touches:

   ```yaml
         - id: I3
           when_paths:
             - aidw
   ```

2. Resume the same run from `update-traceability`, again denying the PR gate:

   ```bash
   cd "$WT"
   uv run --frozen aidw implement docs/task-prompts/99-S9.9-prompt.md \
     --resume --from update-traceability --deny-gates approve-implementation-pr
   ```

   If prompted `Resume this implement run? [y/N]`, answer `y`. Do not add `--yes`: that would
   approve the gate and let `I6 pr` run.

3. Inspect the run again:

   ```bash
   uv run --frozen aidw runs list
   uv run --frozen aidw runs show <run-id>
   ```

**Expected observable result**

- The run resumes the same `<run-id>` and re-runs `I3` onward from `update-traceability`; `I1`
  and `I2` do not re-run.
- The `I3 update-traceability` stage is `succeeded` (not `skipped`) and the stage block does not
  contain the `no changed path matches...` reason.
- `runs show <run-id>` lists `update-traceability` as `succeeded` and adds a new `update-traceability`
  stage record relative to scenario 2.4.
- The run still stops with exit 3 at the denied `approve-implementation-pr` gate and records no
  `pr` stage.

**How to tell pass from fail**

Pass means the same run id, no re-run of `impliment-task` or `test`, a `succeeded`
`update-traceability` stage, and no path-scoped skip reason for it. A `skipped`
`update-traceability` despite the touched `aidw` prefix, a re-run of `I1`/`I2`, a new run id, or
a reached `I6` is a fail.

**Cost, permission or destructive warning:** model spend for `I3` and every stage after it in
the chain. It writes inside the scratch worktree and machine-local state; the denied gate must
prevent any commit, push or PR. Do not force-push or reset any shared branch.

#### 2.6 An absent `when_paths` keeps `I3` unconditional

**Trace:** `aidw/workflows/implement.py`'s empty-declaration path in `paths_changed_reason`; the
build-results "Serial end-to-end fake-stage runs — run with no declaration" row; the task prompt's
"empty default path set … today's behaviour" statement.

**Prerequisites**

- Scenario 2.5 completed; the scratch run is blocked at the gate and the worktree still exists.
- Pi credentials are still available.

**Command(s) or steps**

1. Remove the `when_paths` lines from `I3` in `$WT/aidw/config.yaml`, leaving the entry as:

   ```yaml
         - id: I3
   ```

2. Resume from `update-traceability` once more, with the PR gate denied:

   ```bash
   cd "$WT"
   uv run --frozen aidw implement docs/task-prompts/99-S9.9-prompt.md \
     --resume --from update-traceability --deny-gates approve-implementation-pr
   ```

   Answer `y` if the resume prompt appears.

3. Inspect the run:

   ```bash
   uv run --frozen aidw runs show <run-id>
   ```

**Expected observable result**

- The run resumes the same run and re-runs `I3` onward.
- `update-traceability` is `succeeded`, not `skipped`; there is no path-scoped skip reason,
  exactly as before this token existed.
- The run again stops with exit 3 at the denied gate, with no `pr` stage.

**How to tell pass from fail**

Pass means a `succeeded` `update-traceability` stage with no skip reason after the declaration is
removed, on the same run. A skipped `I3` when no `when_paths` is declared, a run that refuses to
start because the stage entry is incomplete, or a reached `I6` is a fail.

**Cost, permission or destructive warning:** model spend for `I3` and later stages. It writes
inside the scratch worktree and machine-local state only; the denied gate must prevent any
commit, push or PR.

### Browser UI flows

No scenario. No changed file, build-results row or task-prompt statement names a browser route,
screen or client-side flow; this change is a workflow condition, a config field and
documentation.

### External actions

No scenario. The change makes no cloud-provider call and performs no GitHub write of its own;
the live scenarios deliberately deny `approve-implementation-pr` so `I6 pr` cannot push or open
a pull request. There is therefore no AWS/cloud, GitHub or deployed-stack action to exercise
here.

## 3. Teardown

After the scenarios, remove the disposable scratch worktree and branch from the control
worktree:

```bash
uv run --frozen aidw worktree remove 99-S9.9 --force
git branch -D 99-S9.9
rm -f /tmp/s1.1-wip.patch
```

`aidw worktree remove --force` removes the scratch worktree even though it is dirty; `git branch
-D` deletes the local scratch branch. Both are destructive to the scratch branch only — confirm
the branch name is `99-S9.9` before running them. They do not touch `05-S1.1`.

Optionally remove the scratch run history after noting its id:

```bash
uv run --frozen aidw runs list
rm -rf <state root>/runs/<run-id>
```

`<state root>` is the value recorded in scenario 2.3. This deletes only the scratch run's
`state.json`, log and artifacts; it does not touch the real `05-S1.1` run history, and leaving it
in place is harmless.

The scenarios created no pull request, no remote branch, no deployed resource and no cloud
account state, so there is nothing external to close, unpublish or revert. They created no local
files outside the scratch worktree, the machine-local run directory and `/tmp/s1.1-wip.patch`.
If you created shell variables (`WT`, run id), close that shell. If the `05-S1.1` change was
already committed and you skipped the patch step, the `rm -f` line is a no-op.

## 4. Could not be exercised in this environment

- **Lint.** The build results mark lint **unverified** because this repository configures no
  linter (`AGENTS.md`: "pytest is the only verification"). There is no command to run, and this
  guide does not invent one.
- **A live `--parallel` group naming `update-traceability`.** The build results record the
  `--parallel` path as passing through an in-process test (a group member carrying
  `paths-changed` is withheld before pool submission), but no live `--parallel` run was
  performed. A live check needs a disposable repo whose `aidw/config.yaml` declares a group such
  as `["test", "update-traceability"]` and a full model-backed run; scenario 2.5's serial run and
  the focused tests are what this environment can observe.
- **An unresolvable change set (`changed_paths` returning `None`).** The fail-closed rule that a
  `None` change set **runs** `I3` rather than skipping it cannot be produced safely by hand
  without fabricating a repository whose `main` ref does not resolve. The build results record it
  as covered by the in-process fake-stage tests; a disposable repository with no resolvable
  `main` would exercise it.
- **A real `I6 pr` / GitHub push and pull request.** Every live scenario denies
  `approve-implementation-pr`, so `I6 pr` never runs. That is intentional: this change's contract
  is observable before the PR stage, and the build results record that `05-S1.1` has no pull
  request yet. A disposable remote and repository write permission would be needed to exercise
  the PR stage; it is not part of this change's path-scoped behaviour.
- **A rushed or fault-injected run.** A failed `I1`/`I2` before `I3`, a mid-run config change
  other than the declaration edited in the scenarios, and a concurrent run on the same worktree
  are not exercised here. The build results record the skip/run/unconditional/`None` cases through
  fake stages; reproducing them live would require deliberately breaking the scratch fixture.
- **Cloud, deployed stack, browser or hardware.** This change touches no cloud provider, no
  deployed service, no browser UI and no hardware, so no such environment applies.
- **The guide procedure itself.** It is written from the changed files, the build results and the
  repository's own command surface; the toolkit has not executed it. Its expected outcomes are
  the contract's expected outcomes, not observations from a run performed while writing this
  guide.
