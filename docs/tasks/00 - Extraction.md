# Phase 00: Extraction

## Epic E0: Extract the repository (verbatim, then self-hosting)

- [x] **E0.1. Create the new repository**
  Create the remote repo `aidt` at the owner's account, default branch `main`.
  - Deliverable: an empty repo with `main`.
  - Done when: `git clone` succeeds and `main` exists.
  - Open for the owner: visibility and licence. Do not guess either.

- [x] **E0.2. Verbatim copy commit**
  Copy the §5.2 include-list at a recorded source SHA, flattened to the new repo's root; commit
  exactly as in §5.2; tag `baseline-verbatim`.
  - Deliverable: one commit containing the unmodified `aidt/` contents at the repo root.
  - Done when: `diff -r <source>/aidt <new-repo> -x .venv -x runs -x __pycache__ -x .pytest_cache` is empty and the tag exists. (A `git diff` against `<source-sha>:aidt` will *not* be empty — the copy is flattened, per §5.2.)

- [x] **E0.3. Repo skeleton (file moves only)**
  Move `aidw-initial-prompt*.md` to `docs/history/`; create `docs/roadmap-format.md`,
  `docs/target-repo-config.md`, `docs/schema/`, `fixtures/` and `docs/migration/` placeholders;
  move this document to `docs/migration/EXTRACTION.md`. No code behaviour changes.
  - Deliverable: the §3.12 directory layout, with placeholders for docs written later.
  - Done when: `git status` shows additions and renames only, and no Python file is modified.

- [x] **E0.4. Make the toolkit root its own repo (first functional commit)**
  Flattening `aidt/` to the repo root breaks the toolkit's own path resolution: `paths.aidt_root()`
  is `repo_root()/aidt` (`paths.py:40`) and `cli.py:54` does `aidt = repo / "aidt"`, so `prompts/`,
  `agent-configs/`, `inventory` and doctor all point at a non-existent directory. Resolve the
  **toolkit root from the package location** (`Path(__file__)` / `importlib.resources`) instead of
  from git, and re-point the existing global `--repo` so it selects the **target** only. Rewrite
  `tests/test_paths.py` (it asserts `<repo>/aidt`) and `pyproject.toml` `testpaths`.

  Also repo-ise the tests that assert the **target repo's** content, or this task's Done-when is
  unachievable: `test_roadmap.py::test_load_tasks_real_roadmap`, and
  `test_prompt_workflow.py::{test_prompt_workflow_dry_run,
  test_prompt_workflow_requires_main_for_real_run, test_prompt_workflow_requires_clean_tree}`
  (see §4.1). **A toolkit test may never assert a target repo's content.**
  - Deliverable: toolkit-root resolution, plus rewritten path tests and de-coupled roadmap tests.
  - Done when: `uv run pytest` is green from the new repo root, and `uv run aidw doctor` and `uv run aidw prompts check` are clean in a repo whose `prompts/` sits at the repo root.
  - Note: this is the minimal version of E1.2, landed early so the repo can run its own workflow. E1.2 formalises it into a type; E1.1 and E1.3 add the target, workspace and state roots.

- [x] **E0.5. CI**
  `.github/workflows/ci.yml`: `uv sync`, `uv run pytest`, `uv run aidw doctor` on push and PR.
  - Deliverable: a CI workflow.
  - Done when: CI is green on `main` and on a test PR, and a deliberately broken test fails CI.

- [x] **E0.6. Provenance and naming note**
  README states: the repo is `aidt`; the package/CLI is `aidw`; a target repo uses a tracked
  `aidw/` folder for config; the source SHA of the baseline; and that inside this repo `aidw/` is
  code while inside a target repo `aidw/` is configuration.
  - Deliverable: README section.
  - Done when: a reader with no context can explain the two roots after reading the README alone.

- [x] **E0.7. Convert this document's tasks into a roadmap (mandatory)**
  **Mandatory, not optional.** `aidw prompt` is roadmap-driven: `prompt.py:123` reads
  `repo/docs/tasks`, and `find_task` returning `None` exits `2` with `roadmap task not found`. Every
  task §5.5 sends through the pipeline therefore depends on this one. It cannot dogfood itself — it
  creates the file `aidw prompt` needs — so it is implemented directly.

  Note that `aidw implement` does **not** read the roadmap: it derives `(phase, task, branch)` from
  the prompt *filename* (`implement.py` `_PROMPT_NAME`). The roadmap gates prompt *authoring*, not
  implementation.

  Create `docs/tasks/00 - Extraction.md`. **The contract is five regexes in `aidw/roadmap.py`** —
  match those, not the summary in §3.7:

      TASK_RE      ^\s*-\s*\[([ xX])\]\s*\*\*([A-Za-z0-9.]+)\.\s*(.*?)\*\*(.*)$
      EPIC_RE      ^##\s+Epic\s+([A-Za-z0-9]+):\s*(.*)$
      PHASE_RE     ^#\s+Phase\s+([0-9.]+):?\s*(.*)$
      DONE_RE      ^\s*(?:-\s*)?\**Done when:?\**\s*(.*)$      (IGNORECASE)
      _FILENAME_RE ^(\d{2}(?:\.\d+)?)\s*-\s*(.*)\.md$

  Rules that bite, each verified against the shipped parser:

  1. **The task id must be followed by a period inside the bold.** This document's own headings are
     `- [x] **E0.1 Create the new repository**` — no period — and that parses as task id `E0` with
     title `1 Create the new repository`. It fails *silently and destructively*: every entry
     collapses to the epic-level id with a stray leading digit in the title, so `find_task` finds
     nothing and `aidw prompt` fails. Add the period.
  2. **Phase comes from the filename, not the heading** — `00 - Extraction.md` yields
     `entry.phase == "00"`, so the invocation is `aidw prompt 00 E0 E0.1`. `aidw prompt 0 …` does
     not match `find_task`.
  3. **The filename must be exactly `\d{2}` + ` - ` + name + `.md`.** `0 -`, `000 -` and
     `extraction.md` all fail.
  4. **`## Epic X:` and `# Phase N:` headings are cosmetic.** `epic` is derived from the task id
     (`derive_epic("E0.1") → "E0"`), and `find_task` matches on phase + task only. For a `00 -`
     file, `# Phase 0:` does not even match `PHASE_RE`, so `phase_title` stays `None`. Harmless.
  5. **`- Done when:` must appear before any blank line** after the task line. Intervening lines are
     fine: this document's `- Deliverable:` line between the task and its `Done when` parses
     correctly, and the task's prose detail may sit on the line *after* the `**` rather than inline.
  6. **Exclude MF.1–MF.6.** They would parse as phase-`00` tasks with id/epic `MF`, but they are
     work in the *Mythical Forge* repo. They belong in Mythical Forge's roadmap, or nowhere.
  7. **Carry the checkbox state over** (`[x]` for E0.1–E0.6, `[ ]` for the rest). `find_task`
     ignores `done`, and `aidw tasks --todo` filters on it.

  Guard against rule 1 before relying on the file. Kept to a single line, and single-quoted, so it
  survives a copy-paste out of this indented block; it exits non-zero on a collapsed id:

      uv run python -c 'import pathlib; from aidw.roadmap import load_tasks; t=load_tasks(pathlib.Path("docs/tasks")); assert t, "no tasks parsed"; bad=[x.task for x in t if "." not in x.task]; assert not bad, f"MISPARSE: {bad}"; print(f"{len(t)} tasks, none collapsed")'

  - Deliverable: `docs/tasks/00 - Extraction.md`, plus one task prompt authored through the toolkit as a smoke test.
  - Done when: `uv run aidw tasks --phase 00` lists every §6 task (E0–E9, none collapsed), the guard above passes, and one `aidw prompt 00 E1 E1.1` run produces a prompt for review. (E1.1 rather than E0.1: E0.1 is already complete, so its prompt would be a throwaway, whereas E1.1 is the first task that actually needs the pipeline — the smoke test doubles as its real authoring step.)
  - Known frictions: `prompt.py:123` hardcodes `docs/tasks` until E3, and `_FILENAME_RE` requires a two-digit phase, so branches are named `00-E1.1` until `repo.branch_pattern` is configurable (E4).

- [x] **E0.8. Test-suite runtime budget**
  The suite is the largest single cost in every workflow stage: `test` (I2), `record` (I5) and the implementer each re-run most of it, and §5.4 makes `uv run pytest` the verification for every task, so its runtime multiplies across E0–E9 — one E1.6 run spent ~1000s re-running it. Measured with a `subprocess` profiler rather than assumed: 3185 process spawns accounted for 136.6s of 145s wall time, and the driver is `git`, not the CLI — `TargetRepo.resolve` ran three `git rev-parse` invocations per call, the repo fixtures ran two `git config` spawns each across ~300 repositories, and the doctor tests spawned real `pi`/`gh` (~25s). Cut all three, then parallelise the remainder with `pytest-xdist` (`-n auto` in `addopts`, so every stage and CI inherit it; `-n0` is the serial override).
  - Measured: 129.5–150.3s serial before → 65.0s serial after (spawns 3185 → 1843) → 33.9–36.4s under `-n auto`; `TargetRepo.resolve` 3 spawns/132ms → 1 spawn/37ms; 450 tests throughout, none deselected or skipped.
  - Deliverable: a runtime measurement plus the changes that reduce it.
  - Done when: full-suite wall time is measured before and after, the reduction is at least 2×, and `uv run pytest` is green with no test deselected or skipped to achieve it.

## Epic E1: Two-root core

- [x] **E1.1. `TargetRepo` resolution (D19)**
  Implement target resolution: cwd walk-up, then `--repo <path>`, then `AIDW_REPO`. Expose
  `root`, `git_dir`, `common_dir`, `base_branch` (from config, E3).
  - Deliverable: a `TargetRepo` type plus tests including: inside a worktree; inside a subdirectory; an explicit `--repo`; a non-repo path; the bare dir.
  - Done when: tests prove `repo_root` semantics are preserved and the bare dir is rejected.

- [x] **E1.2. `ToolkitPaths`**
  Resolve the installed toolkit root from `Path(__file__)`/`importlib.resources` — never from git.
  Expose `prompts_dir`, `agent_configs_dir`, `agents_dir`, `scripts_dir`.
  - Deliverable: a `ToolkitPaths` type plus a test that it resolves when cwd is an unrelated directory.
  - Done when: `aidw doctor` can report the toolkit root while invoked from `/tmp`.
  - Note: E0.4 lands the minimal version of this so the repo is runnable; this task formalises it into a type and covers the installed (non-repo, `uv tool install`) case.

- [x] **E1.3. Workspace and state root (D18)**
  `workspace_root = dirname(git rev-parse --path-format=absolute --git-common-dir)`;
  `state_root = AIDW_STATE_DIR or <workspace_root>/.aidw/state or ~/.aidw/state`; `repo_slug` from
  `git remote get-url origin`, else the workspace-root basename.
  - Deliverable: resolution helpers plus tests for: bare+worktrees; single checkout; no remote; unwritable workspace root; `AIDW_STATE_DIR` override.
  - Done when: tests prove the state root is identical from every worktree of one repo and differs between repos sharing a parent directory.

- [x] **E1.4. Port consumers and delete the old helpers**
  Replace every `aidt_root()`/`runs_dir()` call site with the new types; remove both helpers;
  rewrite `test_paths.py`.
  - Deliverable: no remaining `repo_root()/aidt` assumption anywhere.
  - Done when: `rg "aidt_root|runs_dir" aidw/` returns nothing, and `runs` are written under the state root.

- [x] **E1.5. CLI plumbing**
  The global `--repo` already exists (`cli.py:89`), but `_roots()` (`cli.py:51-54`) conflates the two
  roots; E0.4 re-points it at the target only. Add `AIDW_REPO`, and thread the resolved `TargetRepo`
  and `ToolkitPaths` through every workflow, replacing the `(repo, aidt)` tuple and
  `cli.py:58`'s `_run_dir`.
  - Deliverable: CLI + workflow changes.
  - Done when: every workflow has a test asserting it operates on the target from `--repo`/`AIDW_REPO` while prompts resolve from the toolkit root, **including when the two are different directories**.

- [x] **E1.6. `aidw config show` (skeleton)**
  Print toolkit root, version, target root, workspace root, state root, and the config file found
  (or none), each with provenance.
  - Deliverable: the subcommand plus `--json`.
  - Done when: the output is sufficient to debug a wrong-target or wrong-config invocation.

## Epic E2: Worktree model (D20)

- [x] **E2.1. Git worktree primitives**
  Add to `aidw/git.py`: `common_dir()`, `workspace_root()`, `worktrees()` (parse
  `git worktree list --porcelain`), `worktree_for_branch()`, `add_worktree()`, `remove_worktree()`,
  `is_linked_worktree()`.
  - Deliverable: primitives plus tests against a real temporary bare+worktree repo.
  - Done when: tests pass on macOS with git ≥ 2.31, and the parser handles the `bare` marker and detached HEAD.

- [x] **E2.2. Target/layout guards**
  Refuse to run when the target is the bare dir; **fail** when the workspace root is itself a
  registered worktree of the same repo (the clone-of-a-worktree trap, §3.2); **warn** when the state
  root falls inside a working tree.
  - Deliverable: guards plus tests reproducing both rejected layouts.
  - Done when: each failure prints the cause and the corrective command.

- [x] **E2.3. `aidw worktree add|list|remove`**
  Thin, safe wrappers over the primitives. `remove` refuses a dirty tree or an unmerged branch
  unless `--force` is explicit. Never `reset --hard`, never delete uncommitted work.
  - Deliverable: the subcommands plus tests.
  - Done when: `worktree list --json` round-trips the branch↔path mapping and `remove` refuses the two unsafe cases.

- [x] **E2.4. Branch setup becomes a Python stage, not a prompt**
  Remove the `git checkout -b` instructions from `prompts/impliment-task.md` (§4.2). AIDT creates
  the branch and its worktree before the first agent stage runs, using `repo.base_branch` and
  `repo.branch_pattern` from config.
  - Deliverable: a `branch-setup` core stage + prompt edits.
  - Done when: `impliment-task.md` contains no `git checkout -b`/`git switch -c`, and a test proves the worktree exists before the implement stage starts.

- [x] **E2.5. `aidw prompt` runs in the control worktree and creates the task worktree**
  `aidw prompt` requires the control worktree (base branch checked out, clean). It creates the task
  worktree, then runs the author/review/fix stages with `cwd` = the new worktree, and commits the
  reviewed prompt on that branch.
  - Deliverable: workflow changes.
  - Done when: a full run creates exactly one new worktree, leaves the base worktree clean, and commits only the prompt path on the task branch.

- [x] **E2.6. `implement`/`fix` resolve their worktree**
  Resolve branch → worktree via `worktrees()`; when absent, print the exact
  `git worktree add …` command and stop. `--repo` overrides.
  - Deliverable: preflight changes plus tests.
  - Done when: `aidw implement` from an unrelated cwd locates the right tree, and the missing-worktree message is copy-pasteable.

- [x] **E2.7. One run per worktree**
  Move the run lock into the state root, keyed by worktree path.
  - Deliverable: locking change plus a concurrency test.
  - Done when: two concurrent runs in the same worktree are refused; two runs in different worktrees proceed.

- [x] **E2.8. Doctor: worktree and git checks**
  Add git ≥ 2.31, workspace root, state root, target-is-not-bare, and control-worktree checks.
  - Deliverable: doctor checks plus tests (follow the existing `gh version` check style, `FAIL` for hard blockers, `WARN` for advisory).
  - Done when: `uv run aidw doctor` diagnoses each rejected layout by name.

- [x] **E2.9. Worktree fixtures**
  A test helper that builds a temporary bare repo with a `main` worktree and a task worktree, wired
  off the bare repo exactly as §3.2 specifies.
  - Deliverable: a shared fixture used by E2 and later epics.
  - Done when: at least three tests across two modules use it, and it cleans up after itself.

- [x] **E2.10. `review` resolves the PR-head worktree**
  E2.6 made `implement`/`fix` locate the PR-head worktree; `review` kept the pre-worktree preflight
  (`git.current_branch` must equal the PR head), so it refuses with `current branch `main` is not
  the PR head` whenever the task branch lives in a sibling worktree — `aidw run prompt-to-fix`
  therefore stopped at its review stage with `chain stopped: `review` exited 4` on every worktree
  run. Resolve the head's worktree and review there (design §8.3, decision K1).
  - Deliverable: `review` locates the PR-head worktree, re-resolves the target and agents against
    it, keys the run lock and `state.json`'s `repo_root` on it, and refuses (exit 4) with the
    `git worktree add` command when it is missing; a single checkout still reviews in place.
  - Done when: a review of a worktree PR succeeds from the control root on `main`, the missing
    worktree is refused with the copy-pasteable command and no run state, and the plan still
    prints under `--dry-run` with no worktree.

- [x] **E2.11. A chain whose review published nothing ends gracefully**
  An `Approve` review publishes no follow-ups, so the PR has no review-follow-up parent issue —
  but `aidw run prompt-to-fix` still auto-approved `approve-followups` and ran `fix`, whose entry
  stage failed closed with `could not read approval state (approve --dry-run exit 2): No
  review-follow-up parent issue found`, turning an approving review into a red run (design §8.6,
  decision I2).
  - Deliverable: `review` records `pr.followups_published` in its run state on both successful
    exits, and `prompt-to-fix`/`review-and-fix` read it after the review stage: only when no
    review of that PR ever published follow-ups does the chain print `chain complete.` and exit 0
    without invoking `fix` (or auto-approving its gate).
  - Done when: an approving review with no findings ends the chain with exit 0 and no `fix` stage
    or gate record, published follow-ups (this round or an earlier one) still run the loop, an
    unreadable record keeps the pre-I2 behaviour, and `aidw fix --pr <n>` on its own is unchanged.

## Epic E3: Target-repo config (D3, D10, D11, D12, D17)

- [x] **E3.1. Schema, loader, validation**
  `aidw/config.py` (or a new `aidw/target_config.py`) defines the §3.4 schema as dataclasses, plus
  `docs/schema/aidw-config.schema.json`. YAML (D11). Unknown keys are an error, not ignored.
  - Deliverable: loader + schema + round-trip tests.
  - Done when: valid configs load; unknown keys, wrong types and bad enum values fail with the offending path in the message.

- [x] **E3.2. Layered resolution with provenance**
  Merge toolkit defaults → target config, recording the source of every resolved value.
  - Deliverable: a resolution API returning values plus provenance.
  - Done when: `aidw config show` reports, per value, whether it came from a default, the config file, or an override.

- [x] **E3.3. Version and compatibility refusal (D10)**
  Refuse to run when `schema_version` is newer than understood, or `requires_toolkit` is unsatisfied.
  - Deliverable: a preflight check with a clear, actionable message.
  - Done when: tests cover both refusals and the happy path.

- [x] **E3.4. Defaults equal the Mythical Forge layout (D17)**
  Every default under `paths:` and `repo:` matches Mythical Forge's current values, so a
  Mythical-Forge-shaped config is valid and near-empty.
  - Deliverable: defaults plus a test asserting each default value explicitly.
  - Done when: a config file containing only `schema_version: 1` produces the Mythical Forge layout.

- [x] **E3.5. `aidw/config.yaml` validation in doctor**
  Report the config path found (or none), the resolved schema version, and any validation error.
  - Deliverable: doctor check plus tests.
  - Done when: a malformed config fails doctor with the field path, and a missing config passes with "defaults".

- [x] **E3.6. Document the config contract**
  `docs/target-repo-config.md`: every field, its default, its effect, the override precedence, and a
  worked Minimal / Typical / Full example.
  - Deliverable: the doc.
  - Done when: a reader can write a correct config for a new repo without reading the code.

- [x] **E3.7. Validate configured paths (fail closed)**
  Classify every `paths:` entry as a **read-path** or a **write-target**. Read-paths must exist when a config or default names them — `build_results_template`, `roadmap_dir`, `task_prompts_dir`, `implementation_results_dir` — and a missing one is an error naming the field and the path, surfaced by `aidw doctor` and by the preflight of the stage that first needs it. Write-targets are outputs of a stage and may legitimately be absent (`architecture_dir` today, and any repo-added stage's dir): create them on demand and require them only when a stage that writes there is enabled. Either way there is no silent fallback and no agent-side improvisation: the record stage stops and reports a missing build-results template rather than inventing a structure (§3.4, E7.2).
  - Deliverable: path classification (read vs write) plus existence validation and tests, wired into doctor and the stage preflight.
  - Done when: a config naming a nonexistent read-path fails with the field and the path in the message; a config whose only absent path is a write-target for a disabled stage passes; and a config whose write-target is needed by an enabled stage is either created or fails with a message naming the stage.

## Epic E4: Config-driven stages and prompt resolution (D2, D4, D12, D13, D14)

- [x] **E4.1. Stage registry and workflow definitions as data**
  Turn the current hardcoded chains (`implement.py:104-148`, `prompt.py:170+`, `review.py:135`,
  `fix.py`, `approve.py:150`) into declarative defaults keyed by workflow and stage id, keeping the
  existing ids (`I1`…`I6`, `P1`, `R1`, `R2`). The `prompt.py` chain it converts is the
  **post-phase-02** shape: the loop runs one `task-review-reconcile-N` stage per fix batch (after
  the batch, before the next review, on the `task-fixer` agent), and the final round is the
  review-only **terminal review**. The registry defaults must reproduce both.
  - Deliverable: a registry module plus a test asserting the default chains match today's order exactly.
  - Done when: the default resolution reproduces the current six-stage implement chain, byte for byte, including prompt filenames and agents.

- [x] **E4.2. Prompt resolver (D14)**
  Resolve in precedence order: explicit `prompt:` path → `<target>/aidw/prompts/<name>` → toolkit
  `prompts/<name>` → error. **Verify Pi's `--prompt-template` precedence empirically** and encode the
  finding; do not assume.
  - Deliverable: a resolver plus tests for every precedence level and the failure case.
  - Done when: an override in the fixture repo is demonstrably the file Pi receives.

- [x] **E4.3. Config-driven plans**
  Port `build_plan` and the other workflows to build their stage lists from the registry.
  - Contract, `plan_stages`: `aidw/runner.py:plan_stages(workflow, *, config, toolkit_root, target_root, **expand_fields) -> list[StageSpec]` is the **only** run-path plan builder and serves all five workflows — it expands the registry default for the workflow, then overlays `explicit_prompt` from the same-`id` config entry (which is why it needs the resolved config for `source` provenance, and both roots for `resolve_prompt`). `**expand_fields` is exactly the per-workflow `expand` field set (`prompt_rel`/`branch`/`task_id`/`base_branch`; `rounds`/`max_revisions`; `pr`/`findings`; `pr`/`iteration`; `pr`). `build_plan(...)` survives only as a thin tests/compat wrapper over `expand("implement", …)` returning `PlannedStage` — it is **not** on the `implement` run path, or config overrides would silently not apply.
  - Contract, deferred-field warnings: exactly one `warning:` line per declared-but-ignored entry, naming the workflow, the stage id, and every ignored reason on that one line — so an entry carrying both `enabled: false` and an `agent` draws one line, not two. (The Tests bullet's "one `warning:` line on stderr per ignored entry" is the counting rule; "each draws one `warning:` line" in the requirement applies per entry, not per ignored field.)
  - Deliverable: `implement`, `prompt`, `review`, `fix`, `approve` all config-driven.
  - Done when: `--dry-run` output for each workflow is unchanged against the baseline with the Mythical-Forge-shaped config. The `--dry-run` baseline for `prompt` is taken **after phase 02**: it includes the `task-review-reconcile-N` stage (one per fix batch) and the review-only **terminal review**, so "unchanged against the baseline" compares the post-phase-02 chain, not a pre-phase-02 one.

- [x] **E4.4. `parallel_groups`**
  Replace the hardcoded `[test, update-architecture]` pair. Validate members exist and are not
  ordered against one another.
  - Deliverable: config field + validation + tests.
  - Done when: a configured group runs concurrently and an invalid group fails validation.

- [x] **E4.5a. Enforce core vs repo-optional — the rules and their messages (D12, D13)**
  Split of the former E4.5; the planning consequences are E4.5b. Reject attempts to reorder a core
  stage or to disable one with `enabled: false`; allow `enabled: false` only for repo-optional
  stages; allow repo-added stages — each as an `ERROR` issue naming the stage and the rule, refused
  with exit 2 before any side effect.
  - Contract, loop ids: the reorderable sequence is the registry's *static*
    `WorkflowDefinition.stages` (`prompt` is `(P1,)`, `fix` is `(A1,)`), never the generated loop
    stages. A declared id that is a loop stage (`P2`, `P2-fix-blocking`/`P2-fix-could-fix`/
    `P2-fix-fallback`, `P2-reconcile`, `F1`–`F4`) is refused, never silently ignored or
    double-planned: with `enabled: false` as "core stage cannot be disabled", with `enabled: true`
    or no `enabled` as "loop stages are generated by `expand`, not declarable". Name ids exactly:
    `STAGE_IDS` holds `P2` but not the `P2-fix-*`/`P2-reconcile` labels, which `stages_by_id()`
    does return.
  - Contract, degenerate input: one `ERROR` per duplicated core id naming the stage and the rule;
    entries the loader already errored on (non-`Mapping`, missing or empty `id`) are skipped so the
    operator sees that error once instead of restated; an explicit `stages: []` yields one removal
    error per core stage (the list replaces wholesale, so every core stage is being removed); an
    unknown workflow name raises `UnknownWorkflowError`, never a traceback.
  - Deliverable: a pure (no I/O) `validate_stage_list` returning issues, wired into all five
    workflow preflights, plus tests for every accept and reject case.
  - Done when: each rejection names the stage and the rule; a repo-optional `enabled: false` is
    accepted while a core one is refused; the validator reads no filesystem.

- [x] **E4.5b. Plan the shapes E4.5a accepts**
  The second half of the former E4.5: an accepted config must become a plan the workflows can
  consume without crashing on their own arity assumptions.
  - Contract, `plan_stages` construction: build the static specs from the declared list (it replaces
    the static half wholesale, in declared order), then append the loop portion from
    `expand(workflow, …)`; a declared loop id is never planned as a static stage (E4.5a refuses it).
  - Contract, `plan_stages` refusal: it validates and raises the same named `StageRegistryError`
    subclass on any `ERROR` issue, so a direct caller (`tests/test_plan_stages.py`, `aidw exec`)
    cannot receive a silently shortened or reordered plan. It is *not* "trusting because the
    validator already ran": the preflight exists so the operator gets the exit-2 `format_issues`
    message instead of a traceback.
  - Contract, repo-added `StageSpec`: state every field — `id` = the declared id, `name` = the id,
    `agent` = the declared agent, `prompt_file` from the declared `prompt:` via `resolve_prompt`,
    `variables=()`, `extra=""`, `explicit_prompt` set from the declared path (it drives the
    `--prompt-template` roots in `run_stage`), `workflow` = the planning workflow. An unknown
    `agent` is refused in preflight against `load_all`/`agent-configs`, not left to fail mid-run as
    `ValueError: unknown agent`.
  - Contract, missing prompt: after the pure validator, the preflight resolves each declared
    entry's prompt and emits one `ERROR` per unresolvable prompt naming the stage and the rule;
    `resolve_prompt`'s `FileNotFoundError` must not escape `run()` as a traceback, and no call site
    adds its own `except FileNotFoundError`.
  - Contract, fixed-arity consumers: `review.py`'s `r1, r2 = plan_stages(...)`, `approve.py`'s
    `(spec,) = plan_stages(...)` and `implement.py`'s `pre_pr = plan[:-1]; pr_plan = plan[-1]` all
    assume today's arity, so a permitted repo-added stage crashes them with `ValueError: too many
    values to unpack`. Iterate the planned specs in `review` (preserving R2's "only when R1 reports
    findings" gating) and in `approve` (attaching `verify` to the A1 spec, running repo-added specs
    without it); in `implement` locate I6 by `id` for the `pr` split so a trailing repo-added stage
    is not mistaken for the PR stage.
  - Deliverable: `plan_stages` construction plus the three consumer rewrites and the rewritten
    `tests/test_plan_stages.py` overlay tests.
  - Done when: a repo-added stage in `review`/`approve`/`implement` plans and runs without an unpack
    `ValueError`; a disabled core stage and a reordered core list both refuse with exit 2 naming the
    stage and the rule; the rewritten overlay tests assert rejection through the named error rather
    than a full plan.
  - Predecessor: E4.5a (its rule set is what this plans for). Both halves came out of one E4.5
    prompt that never converged: six round-1 findings, then a truncated second review.

- [x] **E4.6. Agent and model overrides**
  Allow per-stage `agent`/`model`/`thinking`/`timeout_seconds` and a global agent-config override,
  defaulting to the toolkit's `agent-configs/`.
  - Deliverable: merge logic plus tests.
  - Done when: a fixture override changes the model used in the rendered Pi argv.

- [x] **E4.7. Override integration test (the acceptance test for E3+E4)**
  Against `fixtures/target-repo/`: one stage overridden by filename, one by explicit path, one
  falling back to the default, one repo-optional stage disabled, one repo-added stage, and a global
  model override.
  - Deliverable: an integration test asserting resolved prompt paths, agents and argv per stage.
  - Done when: the test fails if any of the six behaviours regresses.

- [ ] **E4.8. Run each whole-repo gate once per tree**
  Today `test` (I2), `record` (I5) and the implementer each run the full suite against the same tree, and `record` re-runs subsets to fill its own rows — roughly 1000s of duplicated work in one E1.6 run. Record the gated tree identity alongside each gate outcome, and let a later stage in the same run cite that outcome for the same tree instead of re-running it. This deliberately narrows the record prompt's "never copy numbers from an earlier run": a same-run, same-tree outcome is evidence, not a stale number, and it must be cited with its origin (stage, command, timestamp). Differing trees always re-run. Depends on the identity recording in E8.2; if E8.2 has not landed, hash `HEAD` plus the working-tree state as the interim identity.
  - Deliverable: gate-outcome recording in state plus the reuse rule and tests.
  - Done when: a run whose `test` stage gated tree `T` performs no second full-suite run for `T` in `record`, the recorded row still carries real numbers with their origin, and a changed tree forces a fresh run.
  - Progress: `aidw gate run|list`, content tree identity (R16 — content, not the `HEAD`-plus-worktree interim, because `/pr` commits the tree it gated), the declared gate scope (R18 — without it the document-writing stages defeat reuse), `gate_outcomes` in run state under the existing schema version, `AIDW_RUN_ID`/`AIDW_STAGE` in the stage environment, and the gate idiom in the four implement-chain prompts are in. Still open: the same idiom in `fix-next-review-followup.md`, an end-to-end reuse check against a real run, and E7.2's de-naming of `pr.md`'s stack table and default `--ignore` list (R17/R18).

## Epic E5: Roadmap as an AIDT-owned format (D6, D15)

- [ ] **E5.1. Write the format contract**
  `docs/roadmap-format.md`: the required heading/entry structure, the ids, `Done when`, optional
  `Tests:`/citations, and a complete worked example. Mythical Forge's `docs/tasks/*.md` is the
  reference implementation.
  - Deliverable: the doc, with the worked example taken from the prefixed baseline.
  - Done when: the example in the doc parses with the shipped parser.

- [ ] **E5.2. Generalise the parser**
  Drive `roadmap.py` from `paths.roadmap_dir` + `paths.roadmap_glob`. Remove product assumptions from
  its docstrings. No configurable dialect (D15).
  - Deliverable: parser change plus tests.
  - Done when: the fixture repo's roadmap parses without any code change.

- [ ] **E5.3. Format validation with actionable errors**
  Report the file, line and rule when an entry is malformed (a task with no `Done when`, a duplicate
  id, an entry outside an epic).
  - Deliverable: validation plus tests.
  - Done when: each malformed case names the file, line and rule.

- [ ] **E5.4. Promote the canonical example**
  Move the `tests/test_roadmap.py` inline fixture into `docs/roadmap-format.md` and keep the test
  reading it, so doc and parser cannot drift.
  - Deliverable: single-source example.
  - Done when: editing the doc to be invalid fails the test suite.

## Epic E6: Persisted GitHub contracts, per repo (D5)

- [ ] **E6.1. Move markers and labels into resolved config**
  Populate `github.markers` and `github.labels` from config, with defaults **exactly** equal to
  today's literals in `prompts/scripts/review-followup/constants.py`.
  - Deliverable: config plumbing into the bundled scripts (via CLI args or a generated env/JSON handoff — choose whichever keeps the scripts standalone and stdlib-only).
  - Done when: the bundled scripts still run standalone with no config present.

- [ ] **E6.2. Preserve matching semantics exactly**
  No change to strict equality, no whitespace normalisation, no case folding, no regex
  reinterpretation of markers. The label "ensure existing" path still never overwrites an existing
  label.
  - Deliverable: unchanged matching code paths, with tests pinning the semantics.
  - Done when: the review-followup test suite passes unmodified except for the new config plumbing.

- [ ] **E6.3. Freeze test (the D5 guard)**
  A golden test asserting that the Mythical-Forge-shaped config yields byte-identical marker strings,
  label names, colours, descriptions and comment bodies to the `baseline-verbatim` tag.
  - Deliverable: the test.
  - Done when: changing any frozen value in Mythical Forge's config fails this test.

- [ ] **E6.4. Document the freeze**
  Explain in `docs/target-repo-config.md` why these values are config-with-frozen-defaults, and what a
  rename would break (orphaned parents, duplicate issue creation).
  - Deliverable: documentation.
  - Done when: the migration risk is stated where a config editor will read it.

## Epic E7: Split the prompt library

- [ ] **E7.1. Classify and relocate**
  Apply §4.2: keep bucket (i), neutralise (ii), and move bucket (iii) to Mythical Forge's
  `aidw/prompts/` at cutover (§7). Until cutover, leave (iii) in the toolkit but mark each file's
  intended destination in a short header note.
  - Deliverable: a classification table checked into the repo plus the bucket (iii) marker notes.
  - Done when: every prompt file carries an explicit destination, and no file is unclassified.

- [ ] **E7.2. Neutralise bucket (ii)**
  Replace repo-specific commands and paths with references to the target repo's conventions and the
  config paths, per the §4.2 table. Keep the workflow semantics identical. Gate commands move to
  `aidw/conventions.md` by name (§3.4); the build-results template becomes the configured path; and
  the recorder's missing-template behaviour is stated explicitly (stop and report — never invent a
  structure, never substitute another document). While neutralising, also drop the recipes a
  non-interactive session refuses (`rm -rf`, `git init` scratch repos) in favour of `mktemp -d` and
  the repo's fixtures, and require each gate command to run exactly once with every results row
  derived from that single invocation.
  - Deliverable: five edited prompts.
  - Done when: the *rendered* prompt for each of the five names no package manager, no product path and no product doc — asserted against both a Mythical-Forge-shaped config and a neutral one, not by grepping the templates — and no prompt instructs a command the non-interactive runner blocks.

- [ ] **E7.3. Conventions injection (D16)**
  Define how `AGENTS.md` and optional `<target>/aidw/conventions.md` reach the four prompts that need
  them, and implement it.
  - Deliverable: injection mechanism plus tests.
  - Done when: a fixture repo's `conventions.md` appears in the rendered prompt for the relevant stages, and its absence is not an error.

- [ ] **E7.4. Neutralise the agent guidance**
  Per §4.3: `agents/implementer/AGENTS.md`, `agents/recorder/AGENTS.md`,
  `agents/pr-publisher/AGENTS.md`, `agents/task-author/AGENTS.md`.
  - Deliverable: four edited files.
  - Done when: no `agents/*/AGENTS.md` names a product, a package manager, or a product doc.

- [ ] **E7.5. Inventory split**
  `inventory.py`: separate the toolkit's **default** prompts/scripts from the prompts **resolved** for
  a target repo. Keep the `.pi/prompts` sentinel.
  - Deliverable: inventory change plus tests.
  - Done when: `aidw prompts check` validates the toolkit defaults and the resolved repo prompts independently, and reports which is which.

## Epic E8: Packaging, distribution, versions (D9)

- [ ] **E8.1. Installable package**
  `pyproject.toml`: name `aidt` (or `aidw` — pick one and be consistent with the import name),
  version, console script `aidw`, and `uv tool install git+…@<tag>` verified from a clean machine or
  clean tool venv.
  - Deliverable: working install.
  - Done when: `uv tool install` then `aidw doctor` works from a directory unrelated to any repo.

- [ ] **E8.2. `state.json` records identity**
  Record `toolkit_version`, resolved `schema_version`, and a hash of the resolved config.
  - Deliverable: state changes plus tests.
  - Done when: an old run's `state.json` explains which toolkit and config produced it.

- [ ] **E8.3. Version reporting**
  `aidw --version`, and doctor reporting toolkit version, git version, and compat status.
  - Deliverable: CLI + doctor.
  - Done when: version output is available without a target repo.

- [ ] **E8.4. Install and worktree guide**
  README: install paths (primary `uv tool install`, secondary `uvx`), the bare+worktree bootstrap
  from §3.2, and the supported/rejected layouts.
  - Deliverable: README sections.
  - Done when: a reader can bootstrap a bare+worktree workspace from the README alone.

- [ ] **E8.5. Release process**
  Tag-based releases; document how a target repo pins `requires_toolkit`.
  - Deliverable: a short release doc plus the first tag.
  - Done when: a target repo can pin and upgrade deliberately.

## Epic E9: Documentation

- [ ] **E9.1. Rewrite `design.md`**
  Two-root model, worktree model, config and stage contracts, frozen GitHub contracts, state
  locations, distribution. Replace D4/F1–F6/E4 and the `aidt/` layout tree; keep the design-of-record
  tone.
  - Deliverable: rewritten design.
  - Done when: no section describes the toolkit as living inside a product repo.

- [ ] **E9.2. Write the two contract docs**
  `docs/target-repo-config.md` (E3.6) and `docs/roadmap-format.md` (E5.1).
  - Deliverable: both docs complete and cross-linked from the README.
  - Done when: both examples validate against the shipped schema/parser.

- [ ] **E9.3. Move this document to history**
  `docs/migration/EXTRACTION.md`, with a header noting it is historical.
  - Deliverable: moved file.
  - Done when: the tasks it contains are superseded by the repo's own roadmap.

- [ ] **E9.4. README rewrite**
  Purpose, install, quickstart against a target repo, the `aidw/` naming note, troubleshooting
  (including the stale-gh and worktree-layout failures).
  - Deliverable: README.
  - Done when: the §0 audience can operate the toolkit without reading `aidw/`.
