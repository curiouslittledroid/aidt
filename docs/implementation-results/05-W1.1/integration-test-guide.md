# Integration Test Guide — 05-W1.1: `update-traceability` (I3) must not edit the roadmap

## 1. What this guide covers

This is a hand-run procedure for branch `05-W1.1`, which makes the `I3 update-traceability`
stage treat everything under `paths.roadmap_dir` as owned byte-exclusively by the
`/update-roadmap` stage (`I7`), and extends the repo-conventions channel so
`update-traceability.md` is the fifth `CONVENTIONS_PROMPTS` member. The procedure walks the
toolkit's own checks, the rendered `I3` prompt (including the target repo's `aidw/conventions.md`
block), the `implement --dry-run` render path, and the documentation drift checks. **Nothing in
this document has been executed by the toolkit.** Every command below is for a human to run in
their own environment; this document only records what to run and what to look for. The build
results mark the live-Pi run and the mechanical `I3` postcondition as unverified, and they stay
unverified here.

## 2. Scenarios

### 2.1 Repository tooling

#### Scenario 1 — Toolkit preflight still passes on this tree

1. **Prerequisites** — A checkout of branch `05-W1.1` at the repository root, with `uv`, `python3`,
   `git`, `pi` and `gh` available on `PATH` (the `doctor` checks look for them). No cloud account
   or deployed stack is involved.
2. **Command(s) or steps**

   ```bash
   cd "$(git rev-parse --show-toplevel)"
   uv sync --frozen
   uv run --frozen aidw doctor
   ```

3. **Expected observable result** — `uv sync --frozen` completes without changing the lockfile.
   `aidw doctor` exits 0 and its final line is a check count with `0 failed`. The build results
   recorded `22 checks: 0 failed, 2 warning(s)` for this tree, with warnings for the dirty working
   tree and the missing `.mcp.json`; a clean clone may show different (or no) warnings.
4. **How to tell pass from fail** — Pass requires `aidw doctor` to exit 0 and to print
   `0 failed` with no `[FAIL]` check line. A non-zero exit or any `[FAIL]` line is a failure even
   if the warning count looks familiar.
5. **Cost, permission or destructive warning** — None. `uv sync` may write only into `.venv/`;
   `doctor` is read-only and invokes no model or cloud API.

#### Scenario 2 — `update-traceability.md` remains a resolvable required prompt

1. **Prerequisites** — Scenario 1 completed (dependencies synced), and the shell is at the
   repository root on branch `05-W1.1`. For a self-hosted run there is no `aidw/prompts/`
   override directory, so the prompt must resolve to the toolkit default.
2. **Command(s) or steps**

   ```bash
   uv run --frozen aidw prompts check
   ```

3. **Expected observable result** — The command prints two group summaries. The build results
   recorded both as `0 error(s), 0 warning(s)`:
   `toolkit defaults: 0 error(s), 0 warning(s)` and
   `resolved repo prompts: 0 error(s), 0 warning(s)`. The resolved list contains a line for
   `update-traceability.md` whose provenance label is `toolkit default`.
4. **How to tell pass from fail** — Pass requires exit status 0 and **both** summaries at
   `0 error(s)`. A missing `update-traceability.md` line, a `repo override` label in this
   self-hosted checkout, or any `ERROR` line means the required prompt inventory is broken.
5. **Cost, permission or destructive warning** — None. The command reads prompt files and
   writes nothing.

#### Scenario 3 — The three task test modules pass

1. **Prerequisites** — Scenario 1 completed. These tests use temporary directories and never
   invoke a real Pi model.
2. **Command(s) or steps**

   ```bash
   uv run --frozen pytest tests/test_conventions_injection.py tests/test_prompt_neutrality.py tests/test_implement_workflow.py
   ```

3. **Expected observable result** — The run exits 0 with no failures or errors. The build results
   record these modules' cases as covered by the full-suite gate (`2276 passed in 49.29s`), not as
   a separate run, so no standalone pass count is stated here. The tests that pin this change
   are, in particular:
   - `tests/test_conventions_injection.py::test_the_five_prompts_are_exactly_the_injection_set`
   - `tests/test_conventions_injection.py::test_the_traceability_prompt_is_injected_by_basename_not_by_stage_id`
   - `tests/test_prompt_neutrality.py::test_the_traceability_default_states_the_roadmap_ownership_rule`
   - `tests/test_implement_workflow.py::test_a_target_conventions_declaration_reaches_the_rendered_i3_prompt`
4. **How to tell pass from fail** — Pass is pytest's exit status 0 with zero failures. A failure
   in any of the four named tests is a regression of this task's contract (the five-prompt set,
   basename keying, the ownership wording, or the implement-level render), even if the rest of
   the modules pass.
5. **Cost, permission or destructive warning** — None. Tests use temp directories; no Pi
   invocation, no network spend, no repository writes beyond ignored cache directories.

#### Scenario 4 — Documentation drift checks and the recorded edits

1. **Prerequisites** — Scenario 1 completed. The changed documents are `design.md` (§8.2, §12.1,
   §17 Z13, §18) and `docs/target-repo-config.md`.
2. **Command(s) or steps**

   ```bash
   uv run --frozen pytest tests/test_design_doc.py tests/test_workflow_stages_doc.py tests/test_target_repo_config_doc.py
   grep -n 'Enforcement (landed, W1.1)' design.md
   grep -n 'Resolved (W1.1)' design.md
   grep -n 'update-traceability' docs/target-repo-config.md
   ```

3. **Expected observable result** — The pytest command exits 0; the build results record
   `82 passed in 0.80s` for this exact selection on this tree. Each `grep` exits 0 and prints at
   least one matching line: the §17 Z13 row carries `Enforcement (landed, W1.1)`, the §18
   conventions-channel risk row carries `Resolved (W1.1)`, and the target-config document names
   `update-traceability` among the prompts that receive the repository conventions.
4. **How to tell pass from fail** — Pass requires exit 0 from pytest **and** from all three
   `grep` commands. If a `grep` exits 1, the document still records the old state even though
   pytest may be green on the tests it covers; that is a documentation failure, not a pass.
5. **Cost, permission or destructive warning** — None. Read-only checks.

### 2.2 Custom CLI commands

#### Scenario 5 — Render the `I3` prompt and confirm the rule plus the repo conventions

1. **Prerequisites** — Scenario 1 completed. Run from the `05-W1.1` worktree, which has root
   `AGENTS.md` and `aidw/conventions.md`; these are the two D16 conventions sources. Use a
   throwaway state directory so the dry-run's run record and rendered prompt are easy to remove.
   Pi is not invoked in dry-run mode.
2. **Command(s) or steps**

   ```bash
   export AIDW_STATE_DIR="$(mktemp -d)"
   uv run --frozen aidw exec --agent implementer --prompt update-traceability --var 05-W1.1 --dry-run
   rendered="$(find "$AIDW_STATE_DIR" -name 'update-traceability.rendered.md' -print -quit)"
   grep -n 'paths.roadmap_dir' "$rendered"
   grep -n '/update-roadmap' "$rendered"
   grep -n 'None for traceability' "$rendered"
   grep -n '## Repo conventions (AGENTS.md)' "$rendered"
   grep -n '## Repo conventions (aidw/conventions.md)' "$rendered"
   grep -n 'docs/workflow-stages.md' "$rendered"
   ```

3. **Expected observable result** — `aidw exec` exits 0 and prints a `run:` line, a stage line, a
   `rendered:` path, and finally `dry-run complete; Pi not invoked`. The rendered file contains
   the ownership section naming `paths.roadmap_dir` and `/update-roadmap`, the sentence about
   reporting **None for traceability** when the roadmap is the only candidate, and both
   conventions blocks. Because this repo's `aidw/conventions.md` declares its traceability
   artefacts, the conventions block also contains the `docs/workflow-stages.md` table row.
4. **How to tell pass from fail** — Pass requires exit 0 from the `exec` command and from all six
   `grep` commands, on a rendered file that was produced by this run (the `find` must locate a
   file, so check that `$rendered` is non-empty). If the ownership wording is absent, the prompt
   edit is missing; if the `## Repo conventions (aidw/conventions.md)` block is absent while the
   `AGENTS.md` block is present, the fifth-prompt injection is broken. A rendered file that
   contains the conventions block but no ownership rule is a fail, because the build results
   record both as required.
5. **Cost, permission or destructive warning** — No model call and no spend: `--dry-run` does not
   invoke Pi. It **does** write a run record and the rendered prompt beneath
   `$AIDW_STATE_DIR`; delete that directory in teardown. Do not run this with a long-lived
   state directory if you want to keep unrelated run history clean.

#### Scenario 6 — Plan an `implement` run and inspect the rendered `I3` prompt

1. **Prerequisites** — Scenario 1 completed. The branch `05-W1.1` must have a located git
   worktree containing `docs/task-prompts/05-W1.1-prompt.md` (check with
   `git worktree list`), the roadmap resolved from `paths.roadmap_dir` must contain exactly one
   `W1.1` entry, and the roadmap path must have no uncommitted changes before starting (check
   with `git status --porcelain -- docs/tasks`; `docs/tasks` is this repository's toolkit-default
   value for `paths.roadmap_dir`). Use a fresh throwaway state directory so no pre-existing
   implement run can be found for the branch.
2. **Command(s) or steps**

   ```bash
   export AIDW_STATE_DIR="$(mktemp -d)"
   uv run --frozen aidw implement docs/task-prompts/05-W1.1-prompt.md --dry-run
   rendered="$(find "$AIDW_STATE_DIR" -path '*prompts/update-traceability.rendered.md' -print -quit)"
   grep -n 'paths.roadmap_dir' "$rendered"
   grep -n '/update-roadmap' "$rendered"
   grep -n 'None for traceability' "$rendered"
   grep -n '## Repo conventions (aidw/conventions.md)' "$rendered"
   git status --porcelain -- docs/tasks
   ```

3. **Expected observable result** — The command exits 0 and prints `run:`, `branch: 05-W1.1`,
   `prompt: docs/task-prompts/05-W1.1-prompt.md`, one planned line per implement stage including
   `I3 update-traceability [succeeded] (planned)` and `I7 update-roadmap [succeeded] (planned)`,
   a `gate (planned):` line, and `dry-run complete; Pi not invoked`. The rendered `I3` file
   contains the ownership rule and the target-repo conventions block. `git status --porcelain --
   docs/tasks` prints nothing.
4. **How to tell pass from fail** — Pass requires exit 0, the presence of the
   `I3 update-traceability ... (planned)` line, all four `grep` commands succeeding on a non-empty
   rendered path, and an **empty** `git status --porcelain -- docs/tasks` output. If the roadmap
   path shows any modification after a dry run, the invariant this task protects is broken; if
   `I3` is missing from the plan, the stage wiring is wrong. Do not confuse the planned `I7` line
   with a real tick: dry-run invokes no model and performs no write.
5. **Cost, permission or destructive warning** — No Pi invocation and no spend. **The dry run
   still creates a run record** (W1.2, which would prevent that, was explicitly out of scope for
   this task). Because a created dry-run can be adopted by a later `--resume`, keep it in the
   throwaway `$AIDW_STATE_DIR` and delete that directory in teardown; never run this scenario
   against the shared state directory if a later resume matters to you. No commit, push or pull
   request is made.

### 2.3 Browser UI flows

None. No changed file, build-results row or task-prompt statement references a browser UI, a
route, a screen or a front-end asset. There is no browser scenario to run.

### 2.4 External actions (cloud providers, deployed stacks, paid services)

None. The change touches a prompt, the conventions-injection set, this repository's conventions
document, design/config documentation and tests. No changed file or build-results row names an
AWS command, a bucket, a role, a deployed stack or any other external resource. There is no
external-action scenario to run.

## 3. Teardown

- Remove the throwaway state directory and unset the override created by Scenarios 5 and 6:

  ```bash
  rm -rf "$AIDW_STATE_DIR"
  unset AIDW_STATE_DIR
  ```

  This deletes the dry-run's run record, `state.json`, `run.log` and rendered prompts. If you ran
  either scenario without setting `AIDW_STATE_DIR`, locate and remove the run directory it
  created under the default state root (`aidw runs list` shows the run id); do not leave a
  dry-run in place, because a later `--resume` can adopt it.
- No branches, worktrees or commits are created by these scenarios. `uv sync --frozen` may have
  written only into `.venv/`, which is normal developer-environment state and needs no undo.
- Confirm the repository tree is left as found:

  ```bash
  git status --porcelain
  ```

  The output should show only the implementation changes that were already present on
  `05-W1.1`; no file under the resolved `paths.roadmap_dir` (this repo's default is `docs/tasks`)
  should appear. `pytest` may leave ignored `.pytest_cache/` and `__pycache__/` directories; they
  are ignored and contain no test state.
- No deployed resources, cloud accounts, credentials, environment variables or fixtures are
  created, so there is nothing else to delete. No pull request is opened by this guide.

## 4. Could not be exercised in this environment

- **A live end-to-end `implement` run against a real Pi model.** The build results mark this
  **unverified**: it was not run, `AGENTS.md` forbids a test invoking a real Pi model, and the
  render path is proven only by `--dry-run`. Exercising it needs `pi` installed with model
  credentials and a disposable target repo; it would spend model tokens and write commits, so it
  belongs in a developer's own environment, not in this guide.
- **The mechanical `I3` postcondition** (Python verifying that the bytes under
  `paths.roadmap_dir` are unchanged after `I3` runs). The build results mark this **unverified**
  because it was not implemented — the task prompt makes it an explicit non-goal and leaves it as
  the stronger alternative Z13 records. No environment can exercise it until it exists.
- **Lint.** The build results mark the lint row **unverified** because this repository configures
  no linter; `AGENTS.md` states that `pytest` is the only verification. There is no lint command
  to run in any environment, and this guide does not invent one.
- **The live `I7` byte-exact tick after a real `I3` edit.** The guide can confirm only that a
  dry run leaves the roadmap untouched and that the rendered prompt carries the ownership rule.
  Observing the actual `- [ ]` → `- [x]` postcondition requires a real `implement` run through
  `I3` and `I7` with Pi, with the same credential, spend and repository-write requirements as the
  first item above.
- **Browser and cloud/external surfaces.** The change touches none, so no browser or
  cloud-provider flow is omitted: there is nothing there to exercise.

Everything else in this guide is exercisable from a normal developer checkout with `uv`, `git` and
the toolkit's own dependencies; nothing beyond Pi credentials and model spend is required for the
cases above.
