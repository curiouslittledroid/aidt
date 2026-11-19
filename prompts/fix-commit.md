---
description: Commit the accumulated fix change set on the PR-head branch and push it, nothing else
argument-hint: "[pr]"
---

Commit the change set this `aidw fix` run accumulated and push it to the pull request's head
branch. Pull request: #$1.

This prompt is **commit and push only**. It is not the delivery step: do not open a pull
request, do not edit a build-results document, do not run a verification gate of your own, and
do not merge. Opening the PR is `/pr`'s job and the run that owns this branch already has one.

## Pre-flight

The caller (`aidw fix`) has already decided this run may publish. If the caller reports that
this run closed no issue, **do not commit and do not push** — the working-tree changes are then
not this run's, and the run's state records that decision instead.

- Work in the **PR-head worktree** the caller placed you in: the repository's own
  `AGENTS.md` / `aidw/conventions.md` is in effect there. Never run this from another checkout.
- Read the branch you must push — it is the branch that is checked out here, which is also the
  pull request's head branch:
  ```bash
  git branch --show-current
  git status --short --untracked-files=all
  ```
- **Refuse before pushing** when that branch is the repository's base branch (`main`). Pushing
  the base branch is not recoverable in a shared repository: report it and stop.

## Commit

Stage and commit the accumulated change set — the fixes this run made, plus the roadmap tick
when the run flipped one:

```bash
git add -A
git commit -m "<type>(<scope>): <summary> (<task-id>)"
```

- `<type>` ∈ `feat` / `fix` / `docs` / `refactor` / `chore`; `<scope>` is the package, service or
  area touched, and the task id in parentheses when one is known (take it from the run state
  under `<state root>/<repo-slug>/runs/`, or from the branch name, in that order — never invent
  one).
- `git add -A` is deliberate: nothing records which paths the fix stages touched, so the
  accumulated change set is the unit this stage publishes. Preserve unrelated work — never
  reset, clean, stash, or discard anything.
- If the tree is already clean, do not create an empty commit. Report that there was nothing to
  commit and stop.

## Push

```bash
git push origin "$(git branch --show-current)"
```

- `origin` is the remote the branch came from. No `-u`, no `--force`, no `--force-with-lease`.
- Never merge, never rebase, never reset.

## Output

Report, in your final message:

- the branch pushed and the commit SHA you created;
- the `git commit` subject line;
- any file you deliberately left uncommitted and why (there should be none);
- a blocker instead of a success when the commit or the push failed — the caller verifies the
  pushed head itself and fails the run when it does not match.
