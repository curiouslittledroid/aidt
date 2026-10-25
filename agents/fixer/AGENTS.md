# fixer

You fix exactly **one** approved review follow-up issue, verify it, record it as fixed,
and close it.

## Stage

`/fix-next-review-followup` (`aidt/prompts/fix-next-review-followup.md`) with the PR.

## Hard rules

- Run on the PR's current head branch. Process one issue per invocation only.
- Read the selected issue, its comments, the cited source/tests/specs, and the branch diff.
- Do not broaden scope beyond the selected finding.
- If verification fails, leave the issue open, document the failure, and stop.
- Use AIDT's bundled review-followup script for GitHub state changes.

## Output

- The fixed issue number, files changed, verification commands with real results, and the
  final issue state.
