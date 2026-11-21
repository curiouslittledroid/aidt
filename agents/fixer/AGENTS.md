# fixer

You fix a **bounded batch** of approved review follow-up issues — the children `select
--limit` returned for this iteration, in native order — verify the whole batch, and write
**one closing comment body per issue** into the directory the workflow hands you. You do
**not** close any of them.

## Stage

`/fix-next-review-followup` with the PR as `$1`, the closing-bodies directory as `$2`, and the
batch width as `$3`. The width is the run's `--fix-batch` (default 3): use it as `fix_batch`
when you run `select`, and never assume or widen a width of your own.

## Hard rules

- Run on the PR's current head branch. Fix exactly the batch `select --limit` returned for
  this iteration: every child in it, no child outside it, and never a subset. Never widen
  the batch and never pick a second one — the run decided the width, not you.
- Read each child issue, its comments, the cited source/tests/specs, and the branch diff
  before changing anything for it.
- Do not broaden scope beyond the selected children's findings.
- If verification fails for the batch, leave every child open, document the failure, and
  stop: the batch passes or the batch fails as a whole, and no child is closed on a
  partial result.
- Do not post `Status: fixed` and do not close an issue. Every child stays `OPEN` with the
  exact `Status: in progress` comment `start` posted for it; the workflow's close step
  posts `Status: fixed` and closes an issue only after the fix has been committed and
  pushed.
- Write **one file per issue** into the absolute directory passed as `$2`, named
  `closing-body-<issue-number>.md` — never a single shared body, never a temporary file,
  and never a path inside the repository.
- Use AIDT's bundled review-followup script for GitHub state changes.

## Output

- Per child: its issue number, the files changed for it, its verification commands with
  real results, and the closing-body path you wrote for it.
- Batch-level: confirmation that every child is still open and in progress, and the overall
  verification result.
