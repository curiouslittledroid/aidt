---
description: Push the current branch and open a pull request to main following repo conventions
argument-hint: "[task-id]"
---

Open a pull request for the work on the current branch. Task id (if known, e.g. `<phase>-<task>`): $1.

## Pre-flight

Earlier focused stages (`/impliment-task`, `/test`, `/update-traceability`,
`/record-implementation-results`, `/update-architecture`) leave their work **uncommitted**. This
prompt is the single owner of the delivery step: commit the accumulated change set, push, and open
the PR.

- Confirm the current branch is not `main`:
  ```bash
  git branch --show-current
  git status --short --untracked-files=all
  git diff main...HEAD --stat
  ```
- Review the complete change set relative to `main` — the working tree, not only commits.
- Run the verification gates and capture the **real** results (never invent them). The commands are
  the **repo's own** — take them by name from its `aidw/conventions.md`, its root `AGENTS.md`, or the
  task prompt for this task, and never from this prompt. Run the gates it names, written the way it
  writes them; a command from another repo's stack is not a gate here, and running one costs a turn
  and produces no evidence.
- Run each gate through `aidw gate run <key> -- <command>` so its outcome is recorded against the
  exact tree it gated, and a later stage of this run cites it instead of paying for the same run
  twice:

  ```bash
  # what this gate's command cannot read: the documents the *other* stages write — read
  # each resolved value from `aidw config show` and pass it as one --ignore prefix
  SCOPE="--ignore <implementation_results_dir> --ignore <architecture_dir> --ignore <roadmap_dir> --ignore <task_prompts_dir>"
  aidw gate run lint  $SCOPE -- <the repo's lint command, as the repo writes it>
  aidw gate run suite $SCOPE -- <the repo's full test command>
  ```

  `--ignore` declares paths the gate's command cannot read. The four above are the other stages'
  configured write-targets — `implementation_results_dir`, `architecture_dir`, `roadmap_dir`,
  `task_prompts_dir` — resolved for this repo by `aidw config show` and never retyped from another
  repo's defaults: a document those stages wrote cannot change a lint, build or test result. If a
  stage of this workflow writes anywhere else — a traceability report directory, for example — add
  that too: the list is every path a stage *writes* and no path a gate *reads*.
  Declaring them is what makes reuse work at all — `/record` writes its results document *after* it
  gates, so without a scope every tree this stage delivers differs from the tree that was verified,
  and the suite is bought again here. **Never ignore anything else**: source, tests, config and
  lockfiles must always re-run the gate. Every stage that runs a gate must pass the same `--ignore`
  values, or the outcomes will not line up.

  Keys name gates: use `suite` for the full test gate, `lint` for lint, `build` for build, and ask
  for the same gate under the same key from every stage so the outcomes line up. `aidw gate run`
  runs the command in the repo root, prints its output and a one-line outcome, and records it in
  this run. Asking again for the same key against content that differs only inside the declared
  scope prints
  `reused: gate 'suite' passed for tree <id> at <time> by stage '<stage>' (<summary>) [scope excludes: ...]`
  and exits 0 **without re-running** — cite that line, with its origin, in `## Verification`. A
  same-run, same-tree outcome is evidence, not a stale number; `--force` re-runs when you doubt it.
- If anything fails, stop and fix it before committing.

## Commit

Stage and commit the accumulated change set on the task branch:

```bash
git add -A
git commit -m "<type>(<scope>): <summary> (<task-id>)"
```

- `<type>` ∈ `feat` / `fix` / `docs` / `refactor` / `chore`; `<scope>` is the package/area; append
  the task id when known.
- If earlier stages already committed everything (clean working tree), do not create an empty
  commit — continue to the push.

## Push

```bash
git push -u origin "$(git branch --show-current)"
```

## Create the PR

Use `gh pr create --base main --head <branch>` (base is **always** `main`).

- **Title:** conventional-commit style — `<type>(<scope>): <summary>` where:
  - `<type>` ∈ `feat` / `fix` / `docs` / `refactor` / `chore`
  - `<scope>` is the package, service, or area touched (e.g. `<the package, service, or area>`)
  - append the task id in parentheses when known, e.g. `feat(<scope>): <summary> (<task-id>)`
- **Body** with these exact sections:
  - `## Summary` — 1–2 sentences: what changed and which spec section / roadmap task it implements.
  - `## Changes` — bullet list of files added/modified with their paths.
  - `## Verification` — the exact commands run and their outcomes (pass/fail, test counts), naming
    the origin (`tree`, `stage`, timestamp) of any outcome you cite from `aidw gate` rather than ran.

## Record the PR number in the build results

The build results name the pull request for this change at the very top of the document,
immediately above their `## Summary` section — under the configured results directory
(`paths.implementation_results_dir`), at `<branch>/build-results.md`. The record stage wrote that
document *before* this one, so its line normally reads `not yet opened`. Now that the PR exists,
replace that one line with the number (and URL) `gh pr create` printed, commit it on the branch,
and push:

```bash
git add "<implementation_results_dir>/<branch>/build-results.md"
git commit -m "docs(<scope>): record PR #<n> in the build results (<task-id>)"
git push
```

- Change that one line and nothing else in the document, and use the number `gh pr create`
  printed — never an invented or inferred one.
- The document lives inside the results directory every stage declares in its `--ignore` scope, so
  this edit cannot invalidate the gate outcomes above it. Re-run no gate to make it.
- If the document does not exist, report it and continue: the record stage owns that file and this
  stage does not create it.

## Do NOT merge

Leave the PR open. Merging is driven by the CI/CD pipeline (PR → ephemeral dev → staging → prod) — never by a direct merge on the branch.
