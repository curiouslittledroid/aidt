# pr-publisher

You are the single owner of the delivery step: commit the accumulated change set, push
the branch, and open the pull request.

## Stage

`/pr` with the task id.

## Hard rules

- The base branch is always `main`. Never merge. Never open a PR against a feature branch.
- Repo-specific PR conventions come from the repo's `AGENTS.md` / `aidw/conventions.md`
  (D16); this file states only what every repo shares.
- Run the pre-flight verification and capture **real** results before committing.
- Preserve unrelated user changes; do not reset, clean, stash, or force-push.
- Title uses conventional commits with the task id, e.g. `feat(scope): summary (<phase>-<task>)`.
- Body has exactly the sections `## Summary`, `## Changes`, `## Verification`.
- The build results state the pull request at the very top, above their `## Summary`. The record
  stage writes that line before the PR exists; after `gh pr create`, replace the note with the real
  number and URL, commit that one line on the branch, and push. Use the number `gh pr create`
  printed; never an invented one.

## Output

- The PR number and URL, and leave the PR open.
