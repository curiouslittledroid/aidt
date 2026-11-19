# Integration Test Guide — S1.2: gating `I4 update-architecture` on `paths-changed`

**Branch:** `05-S1.2`
**Build results read for this guide:** `docs/implementation-results/05-S1.2/build-results.md`
**Task prompt read for this guide:** `docs/task-prompts/05-S1.2-prompt.md`

## 1. What this guide covers

This is a hand-run procedure for the S1.2 change on branch `05-S1.2`: gating the
`I4 update-architecture` stage of `aidw implement` on the existing `paths-changed`
condition, giving it the literal registry default `docs/architecture`, preserving the
difference between an absent `when_paths` and an explicit `when_paths: []`, and warning
operators through `aidw doctor` when an enabled I4 would run unconditionally. The guide
walks three surfaces the branch's tests and build results point at: the repository's
pytest gate, the `aidw doctor` CLI check, and the `aidw implement` workflow (dry-run plan,
serial skip/run, declared paths, explicit-empty paths, and `--parallel` dispatch). It also
records the contract that cannot be confirmed from a normal environment.

Nothing in this guide has been executed by the toolkit. Every expected result below is
either quoted from the recorded build results, pinned by a changed test file on this
branch, or required by the task prompt; no result here was observed by running the
scenario. **Important recorded state:** the build results state that the implementation
deliverables are absent from this branch — `aidw/stage_registry.py`, `aidw/runner.py`,
`aidw/doctor.py`, `docs/target-repo-config.md`, `docs/workflow-stages.md` and `design.md`
are unchanged relative to `main`. The recorded suite therefore fails the new S1.2 pins
(`10 failed, 2255 passed`). Read the scenarios as the procedure to run once the change is
delivered, and use the recorded failure as the current baseline, not as a pass.

## 2. Scenarios

### 2.1 Repository tooling

#### Scenario 1 — Run the repository's pytest gate and the S1.2 pins

1. **Prerequisites.** A checkout of branch `05-S1.2`; `uv` installed; network access for
   `uv sync --frozen` if the environment cache is empty. The repository's `AGENTS.md`
   names pytest as its only verification command; no linter or formatter is configured.
2. **Command(s) or steps.** From the repository root:

   ```bash
   uv sync --frozen
   uv run --frozen pytest
   ```

   To exercise only the S1.2 pins recorded in the build results, run:

   ```bash
   uv run --frozen pytest \
     tests/test_design_doc.py::test_s1_2_design_sections_and_next_free_decision_row_are_recorded \
     "tests/test_doctor.py::test_doctor_warns_only_for_enabled_i4_with_an_empty_effective_path_set[enabled-explicit-empty]" \
     tests/test_plan_stages.py::test_i3_plans_with_paths_changed_and_the_declared_when_paths \
     tests/test_plan_stages.py::test_i4_uses_the_registry_default_but_explicit_empty_stays_empty \
     tests/test_implement_workflow.py::test_i4_default_skips_an_unrelated_change_and_records_a_cost_control_skip \
     tests/test_implement_workflow.py::test_i4_is_withheld_on_the_parallel_member_dispatch_path \
     tests/test_stage_registry.py::test_the_evidence_green_condition_is_carried_never_expanded_away \
     tests/test_stage_registry.py::test_i4_carries_paths_changed_and_its_architecture_default \
     tests/test_target_repo_config_doc.py::test_when_paths_documentation_covers_i4_default_and_repo_override_rules \
     tests/test_workflow_stages_doc.py::test_i4_documents_the_paths_changed_condition_and_default
   ```

3. **Expected observable result.** A fully delivered change exits `0` with the whole suite
   green. The build results record the current branch as failing the full suite with
   `10 failed, 2255 passed in 47.74s` (gate `suite`, tree `dc9702c4c7b8`), and every one of
   the ten node ids above is in that failing list. The representative recorded assertion is
   `AssertionError: assert '' == 'paths-changed'` from
   `test_i4_carries_paths_changed_and_its_architecture_default`.
4. **How to tell pass from fail.** Pass: `uv run --frozen pytest` exits `0` with no failures,
   and each of the ten S1.2 pins above passes individually. Fail: any of the ten pins
   fails, or the suite reports a non-zero exit. On the recorded branch the result is a fail;
   matching the recorded `10 failed, 2255 passed` is consistent with the build results, not
   a pass.
5. **Cost, permission or destructive warning.** None. The command is local, creates
   temporary test repositories and removes them, and needs no credentials. `uv sync` may
   download packages.

### 2.2 Custom CLI — `aidw doctor`

#### Scenario 2 — Doctor warns only for an enabled I4 with an explicit empty trigger set

1. **Prerequisites.** A scratch target repository with a `schema_version: 1`
   `aidw/config.yaml` at its root, and an environment where `uv run --frozen aidw doctor`
   already runs (the build results record a doctor run with 21 checks and 2 warnings).
   Use a disposable directory so the config can be replaced four times. The YAML in the
   steps is the exact matrix pinned by `tests/test_doctor.py`.
2. **Command(s) or steps.** Set up the scratch target and the first config:

   ```bash
   SCRATCH="${TMPDIR:-/tmp}/aidw-s12-doctor"
   mkdir -p "$SCRATCH/aidw"
   git init "$SCRATCH"
   cat > "$SCRATCH/aidw/config.yaml" <<'YAML'
   schema_version: 1
   workflows:
     implement:
       stages:
         - id: I4
           when_paths: []
   YAML
   ```

   Run doctor with the app-level `--repo` before the subcommand:

   ```bash
   uv run --frozen aidw --repo "$SCRATCH" doctor
   ```

   Then repeat with the other three configurations pinned by the test. Non-empty:

   ```yaml
   schema_version: 1
   workflows:
     implement:
       stages:
         - id: I4
           when_paths: [docs/diagrams]
   ```

   Absent key (the registry default applies):

   ```yaml
   schema_version: 1
   workflows:
     implement:
       stages:
         - id: I4
   ```

   Disabled I4 with an explicit empty set:

   ```yaml
   schema_version: 1
   workflows:
     implement:
       stages:
         - id: I4
           enabled: false
           when_paths: []
   ```

3. **Expected observable result.** In the first case (`enabled-explicit-empty`), doctor
   reports a `WARN` check whose name or detail names `I4` / `I4 update-architecture` and
   tells the operator to declare `docs/architecture` plus their diagram-input paths, as the
   task prompt's Requirement 6 specifies. In the other three cases no I4 warning appears.
   The recorded doctor row exits `0` with 2 warnings (dirty working tree, missing
   `.mcp.json`); it does **not** record an I4 warning, and the build results state the
   doctor warning is not implemented on this branch. The exact warning text is
   **unconfirmed**: `aidw/doctor.py` is unchanged in the recorded change set, so no
   changed file or build-results row contains the implemented wording.
4. **How to tell pass from fail.** Pass: case `enabled-explicit-empty` produces exactly
   one warning naming I4 and exit status `0`, and cases `enabled-non-empty`,
   `enabled-absent-default` and `disabled-explicit-empty` produce none. Fail: no I4 warning
   in the first case; an I4 warning in any of the other three; or doctor exits non-zero
   solely because of the I4 check. Do not treat the recorded doctor run as evidence that the
   warning works — the build results record the warning as absent.
5. **Cost, permission or destructive warning.** None. `aidw doctor` is a read-only local
   check; the scratch repository and config are disposable.

### 2.3 Custom CLI — `aidw implement`

#### Scenario 3 — `--dry-run` plans I4 in position and evaluates nothing

1. **Prerequisites.** A disposable target git repository on a feature branch, and a task
   prompt file to pass as the positional argument. The `--dry-run` flag is defined by
   `aidw implement` in `aidw/cli.py`. The task prompt says the dry run plans I4 in position
   and evaluates no condition; whether the dry run performs the full environment preflight
   is not stated by the changed files or build results.
2. **Command(s) or steps.**

   ```bash
   uv run --frozen aidw --repo "$SCRATCH" implement /path/to/task-prompt.md --dry-run
   ```

   The path above is the one your environment actually uses. **Unconfirmed:** the changed
   files and build results do not state whether the prompt path must be inside the target
   repository; if an absolute path is refused, copy the prompt into the scratch repository
   and pass its repo-relative path instead.
3. **Expected observable result.** The printed plan includes `I4 update-architecture` at its
   registry position in the implement stage order, and no stage agent is dispatched. The
   task prompt records that `plan_stages` / `build_plan` / `--dry-run` plan I4 in position
   and a dry run evaluates nothing. The exact plan line format is **unconfirmed**: no
   changed file or build-results row quotes it.
4. **How to tell pass from fail.** Pass: the plan lists I4 in the registry sequence around
   `update-traceability` and `record-implementation-results`, and no Pi stage invocation
   occurs. Fail: I4 is missing from the plan, is reordered, or the dry run starts stage
   work. Do not infer skip/run behavior from the dry run — the task prompt says the dry run
   evaluates no condition.
5. **Cost, permission or destructive warning.** No model spend and no repository writes are
   expected from `--dry-run`; the command is still a workflow preflight, so run it against a
   disposable checkout. Confirm the preflight does not create a run record before relying
   on that.

#### Scenario 4 — Serial implement run skips I4 when the change set is unrelated

1. **Prerequisites.** A disposable target repository with a remote and a feature branch
   based on a resolvable base branch; a task prompt file; Pi installed and configured with
   the models the agent configs name; credentials for that model provider; a `gh` login if
   the run reaches the `I6 pr` stage; and a change set relative to the base branch that
   touches **no** path under `docs/architecture`. The target config may omit `I4`'s
   `when_paths` (the registry default applies) or the target may have no `aidw/config.yaml`
   at all, in which case defaults apply. The branch's test for this case uses a fake stage
   runner; the hand-run version invokes real agents.
2. **Command(s) or steps.** Make the only change (or the committed change set) touch an
   unrelated path, for example a file under `notes/`. Then run:

   ```bash
   uv run --frozen aidw --repo "$SCRATCH" implement /path/to/task-prompt.md --yes
   uv run --frozen aidw --repo "$SCRATCH" runs list
   uv run --frozen aidw --repo "$SCRATCH" runs show "$RUN_ID"
   ```

   Set `RUN_ID` to the id printed by `runs list` for the implement run. The prompt-path
   caveat from Scenario 3 applies. `--yes` approves all gates; drop it if you want to
   inspect each approval gate interactively.
3. **Expected observable result.** The live stage block for I4 says `[skipped]` and prints
   the skip reason; the branch's test asserts the recorded status is `skipped`, `error` is
   `None`, the reason contains `docs/architecture`, the run status is `succeeded`, and
   `state.resume` is `{"next_stage": None}`. `runs show` lists
   `stage update-architecture: skipped ...`; `state.json` under the run directory carries
   `status: "skipped"` with the reason in the `skip_reason` artifact. The pure reason built
   by the recorded code is `no changed path matches the declared when_paths
   (docs/architecture): the change set does not touch any of them`.
4. **How to tell pass from fail.** Pass: I4 is recorded `skipped` with a reason naming
   `docs/architecture`, I4's agent is never dispatched, and the run still succeeds. Fail: I4
   runs despite the unrelated change set; the record carries an `error`; the run fails; or
   `state.resume` is written for the skipped stage. A skip is a cost-control decision, not a
   gate verdict.
5. **Cost, permission or destructive warning.** This spends model tokens for every stage
   that does run and writes to the scratch repository; the workflow may commit and the
   `I6 pr` stage may open a pull request. Use a disposable repository and a throwaway
   remote, and scope `gh` credentials accordingly. Do not run it against this toolkit
   checkout or another repository you cannot discard.

#### Scenario 5 — A change under `docs/architecture` runs I4

1. **Prerequisites.** Same as Scenario 4, except the change set must include a path under
   `docs/architecture`, for example a modified or added
   `docs/architecture/ARCHITECTURE.md`.
2. **Command(s) or steps.** Create or modify the architecture file in the scratch
   repository, then run the same command as Scenario 4:

   ```bash
   uv run --frozen aidw --repo "$SCRATCH" implement /path/to/task-prompt.md --yes
   uv run --frozen aidw --repo "$SCRATCH" runs show "$RUN_ID"
   ```

3. **Expected observable result.** I4 is not skipped: the branch's test asserts
   `update-architecture` is in the dispatched stage names and its recorded status is
   `succeeded`. The literal prefix `docs/architecture` includes files below the directory,
   so `docs/architecture/ARCHITECTURE.md` matches.
4. **How to tell pass from fail.** Pass: the run dispatches I4 and records it `succeeded`;
   no I4 skip reason appears. Fail: I4 is recorded `skipped` even though the change set
   includes `docs/architecture`, or the run fails before I4.
5. **Cost, permission or destructive warning.** Same model spend, write, commit and possible
   pull-request cost as Scenario 4; use a disposable repository and throwaway remote.

#### Scenario 6 — A repo-declared `when_paths` list replaces the default

1. **Prerequisites.** Same as Scenario 4, with `aidw/config.yaml` declaring I4's
   `when_paths: [docs/diagrams]` and a change set that includes
   `docs/diagrams/system.mmd`. **Contract caveat:** the task prompt records replace
   semantics as *proposed, not settled*; the branch's tests pin replace, but the prompt asks
   the task owner to confirm replace or merge before implementation. Treat the
   discriminating expectation below as unconfirmed until that confirmation is recorded.
2. **Command(s) or steps.** Write the config, add the diagram file, and run:

   ```bash
   uv run --frozen aidw --repo "$SCRATCH" implement /path/to/task-prompt.md --yes
   uv run --frozen aidw --repo "$SCRATCH" runs show "$RUN_ID"
   ```

   To discriminate replace from merge, repeat with a change set that touches only
   `docs/architecture/ARCHITECTURE.md` and no declared diagram input. Under replace, I4
   skips; under merge, the default keeps `docs/architecture` and I4 runs.
3. **Expected observable result.** The branch's changed test
   `test_i4_declared_diagram_input_replaces_default_and_runs_on_that_input` asserts that
   with `when_paths: [docs/diagrams]` and a `docs/diagrams/system.mmd` change, I4 is
   dispatched and its spec's `when_paths` is exactly `("docs/diagrams",)`. That test only
   proves the declared input is sufficient; it does not by itself distinguish replace from
   merge. `test_plan_stages.py::test_i4_uses_the_registry_default_but_explicit_empty_stays_empty`
   pins the replace reading at the planning seam.
4. **How to tell pass from fail.** Pass under the branch's pinned replace reading: a
   `docs/diagrams/system.mmd` change runs I4, and an architecture-only change with
   `when_paths: [docs/diagrams]` skips I4. If the architecture-only change runs I4, the tree
   behaves as merge rather than replace; that is a contract mismatch to escalate to the task
   owner, not a runtime failure. Fail under either reading: a `docs/diagrams/system.mmd`
   change causes I4 to skip.
5. **Cost, permission or destructive warning.** Same model spend, write, commit and possible
   pull-request cost as Scenario 4; use a disposable repository and throwaway remote.

#### Scenario 7 — Explicit `when_paths: []` runs I4 unconditionally

1. **Prerequisites.** Same as Scenario 4, with `aidw/config.yaml` declaring I4's
   `when_paths: []`, and a change set that touches no path under `docs/architecture` (the
   case where the default would skip).
2. **Command(s) or steps.** Write the config, make an unrelated change, and run:

   ```bash
   uv run --frozen aidw --repo "$SCRATCH" implement /path/to/task-prompt.md --yes
   uv run --frozen aidw --repo "$SCRATCH" runs show "$RUN_ID"
   ```

3. **Expected observable result.** I4 runs rather than skipping: the branch's
   `test_i4_explicit_empty_paths_runs_unconditionally` asserts `update-architecture` is in
   the dispatched stage names and its spec's `when_paths` is `()`. The same configuration is
   the one Scenario 2 expects doctor to warn about.
4. **How to tell pass from fail.** Pass: the explicit empty set runs I4 despite the
   unrelated change set, and the run records I4 as `succeeded`. Fail: I4 is skipped because
   the registry default was applied to an explicit empty declaration.
5. **Cost, permission or destructive warning.** Same model spend, write, commit and possible
   pull-request cost as Scenario 4; use a disposable repository and throwaway remote.

#### Scenario 8 — `--parallel` withholds I4 on the parallel-member dispatch path

1. **Prerequisites.** Same as Scenario 4, with `aidw/config.yaml` declaring
   `when_paths: [docs/diagrams]` and `parallel_groups` containing the pair
   `[test, update-architecture]`; the change set touches neither `docs/diagrams` nor
   `docs/architecture`. I4 sits in the default safe pair, so the parallel member filter is
   the common path.
2. **Command(s) or steps.**

   ```bash
   uv run --frozen aidw --repo "$SCRATCH" implement /path/to/task-prompt.md --yes --parallel
   uv run --frozen aidw --repo "$SCRATCH" runs show "$RUN_ID"
   ```

3. **Expected observable result.** I4 is withheld before Pi is invoked and recorded
   `skipped`; the branch's test
   `test_i4_is_withheld_on_the_parallel_member_dispatch_path` asserts
   `update-architecture` is not in the dispatched names and its recorded status is
   `skipped`. The run still succeeds.
4. **How to tell pass from fail.** Pass: the parallel run records I4 `skipped` and does not
   dispatch its agent; I2 and the rest of the group still run. Fail: I4 runs in the parallel
   member loop because the skip was applied only on the serial path.
5. **Cost, permission or destructive warning.** Same model spend, write, commit and possible
   pull-request cost as Scenario 4, plus the concurrency risk of a parallel group; use a
   disposable repository and throwaway remote.

## 3. Teardown

The pytest scenario creates only temporary test repositories and removes them; no manual
cleanup is normally needed. The doctor and implement scenarios deliberately create state
that must be removed:

- **Scratch repositories.** Delete the directories created for the scenarios, for example
  `rm -rf "${TMPDIR:-/tmp}/aidw-s12-doctor"` and the disposable implement repository.
  Verify first that they are the scratch paths and not a real checkout.
- **Branches, commits and pull requests.** Each implement run may create or update a
  branch, commits and a pull request on the scratch remote. Close the pull request, delete
  the scratch branch, and delete the remote if it was created for this exercise. Never merge
  the pull request.
- **Run state.** Runs are stored under the per-repo state root:
  `<state root>/runs/<run_id>/state.json`, where the state root is
  `AIDW_STATE_DIR` when set, else `<workspace>/.aidw/state/<repo_slug>`, else
  `~/.aidw/state/<repo_slug>`. Remove the scratch repository's run directories if you do
  not want them retained. `aidw runs list` shows the ids before deletion.
- **Local files.** Remove any `notes/`, `docs/architecture/` or `docs/diagrams/` files
  created only for the scenarios, and remove or restore the scratch
  `aidw/config.yaml` used by Scenarios 2, 6, 7 and 8.
- **Environment variables.** Unset `SCRATCH` and `RUN_ID` if you exported them. If you set
  `AIDW_STATE_DIR` or `AIDW_REPO` for the exercise, unset them.
- **Nothing else.** No cloud resource, deployed stack, browser session or paid service is
  created by this guide, so there is no cloud teardown to perform.

## 4. Could not be exercised in this environment

- **The recorded implementation itself.** The build results state that
  `aidw/stage_registry.py`, `aidw/runner.py`, `aidw/doctor.py` and the three documentation
  files are unchanged on this branch, and that the S1.2 pins fail. The intended I4 behavior
  therefore cannot be observed as a pass until those deliverables land. This is a recorded
  gap, not a scenario outcome.
- **The fail-closed `changed_paths() is None` case.** The branch's test reaches it by
  monkeypatching `implement_workflow.git.changed_paths` to return `None`. A hand-run
  integration test cannot force that condition without patching the code, and a real
  repository with an unresolvable base is expected to be refused by earlier preflight
  checks. The test asserts I4 runs rather than skips; exercising it by hand would need a
  test harness that injects the unresolvable change set.
- **Real Pi model invocations and agent behaviour.** Scenarios 4–8 replace the branch's
  fake stage runner with real agents. They need Pi installed, provider credentials, model
  access and the corresponding spend. The build results record no real Pi invocation for
  this task.
- **Pull-request creation through `I6 pr`.** A full implement run may reach the PR stage;
  that needs a `gh` login, a writable remote and the credentials to open a pull request.
  The build results record that no pull request existed at recording time (`gh pr view
  05-S1.2` returned no number). The guide therefore cannot confirm the PR path.
- **Doctor warning wording.** `aidw/doctor.py` is unchanged in the recorded change set, so
  the exact WARN text cannot be confirmed from the tree or the build results. The trigger
  and the operator instruction are fixed by the task prompt; only the wording is
  unconfirmed.
- **Dry-run plan output format.** No changed file or build-results row quotes the printed
  plan, so the exact line shape is unconfirmed; only I4's presence and position are fixed.
- **The replace-vs-merge contract.** The task prompt records replace semantics as proposed
  and not settled, while the changed tests pin replace. Scenario 6 is conditional on that
  confirmation; a merge reading would change the architecture-only expectation.
- **Lint.** The build results mark lint **unverified**, with the recorded reason: this
  repository configures no linter or formatter, and `AGENTS.md` states pytest is the only
  verification. No lint scenario exists to run.
- **Browser UI and cloud-provider surfaces.** The change touches no browser UI, route,
  endpoint, deployed stack, cloud account, bucket, role or ARN. There is nothing to exercise
  there, and no credentials or spend are needed for them.
