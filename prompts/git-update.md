---
description: Stage all changes, commit with a concise message, and push to remote
---
Run the following steps in order:

1. Show the current git status with `git status --short`.
2. Show a summary of the unstaged and staged diffs with `git diff --stat` and `git diff --staged --stat`.
3. Stage all changes with `git add -A`.
4. Derive a concise, single-line commit message that summarises what changed. Use the `git diff --staged` output to understand the changes; capture the core intent in ~50–72 characters. Use conventional commit format (e.g. `feat:`, `fix:`, `refactor:`, `chore:`) where it fits.
5. Commit with that message: `git commit -m "<message>"`.
6. Push to the default remote: `git push`.

Do not ask for confirmation — proceed with all steps automatically. If there is nothing to commit, report that and stop.