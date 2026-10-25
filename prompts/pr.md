---
description: Push the current branch and open a pull request to main following repo conventions
argument-hint: "[task-id]"
---

Open a pull request for the work on the current branch. Task id (if known, e.g. `02-D2`): $1.

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
- Run the verification commands and capture the **real** results (never invent them):
  ```bash
  pnpm install
  pnpm -r lint
  pnpm -r build
  pnpm -r test        # or pnpm --filter <pkg> test for the package(s) this branch touched
  ```
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
  - `<scope>` is the package/service/area touched (e.g. `rules-engine`, `player-api`, `shared-types`, `infra`)
  - append the task id in parentheses when known, e.g. `feat(rules-engine): cover & flanking bonus calculation (D2)`
- **Body** with these exact sections:
  - `## Summary` — 1–2 sentences: what changed and which spec section / roadmap task it implements.
  - `## Changes` — bullet list of files added/modified with their paths.
  - `## Verification` — the exact commands run and their outcomes (pass/fail, test counts).

## Do NOT merge

Leave the PR open. Merging is driven by the CI/CD pipeline (PR → ephemeral dev → staging → prod) — never by a direct merge on the branch.
