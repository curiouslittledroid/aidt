# review-followup

Deterministic GitHub bookkeeping for the review follow-up workflow driven by
these prompts:

- `aidt/prompts/review-findings-to-github.md` (publisher)
- `aidt/prompts/approve-review-followups.md` (approver)
- `aidt/prompts/fix-next-review-followup.md` (consumer)

The scripts live beside the prompts on purpose. They are helper tooling for the
pi prompts, not part of the Mythical Forge product, and this directory can be
copied into another repository together with `aidt/prompts/`.

They exist because the bookkeeping is mechanical and error-prone when done as
ad-hoc shell: `gh issue close` has no `--body-file`, `gh api --slurp` cannot be
combined with `--jq`, and long markdown comment bodies are hazardous to pass
inline. Everything here is exact-match and shell-free.

## Portability

- **No install step.** The scripts run on any Python 3.9+ and use only the
  standard library. There is no build step and no virtualenv of their own.
- **No third-party dependencies.** Manifest validation is hand-written, so
  there is no schema library to install.
- **No project-specific paths.** The prompts invoke the scripts through the
  toolkit's absolute `prompts/scripts` directory, passed to the stage as
  `AIDW_SCRIPTS_DIR`, not through package-manager aliases and not through a
  path relative to the target repository.
- `gh` is the only external tool required, plus `git` for the branch check.

Run a script by path (set `AIDW_SCRIPTS_DIR` yourself when running outside
`aidw`, which sets it for every stage):

```bash
scripts_dir="${AIDW_SCRIPTS_DIR:-/path/to/toolkit/prompts/scripts}"
python3 "$scripts_dir/review-followup/review_followup.py" --help
python3 "$scripts_dir/review-followup/publish_review_followups.py" --help
```

`aidw fix` invokes the same entry points as a subprocess, using its own
interpreter (`sys.executable`) instead of `python3`, so the wrapper and the
agent run identical code.

## What it does not do

It never decides whether the code work is done. `fixed`/`close` are separate,
explicit calls that a caller makes only after the work has met its acceptance
checks. Nothing is chained automatically.

Since 05-P1.2 a `fix` run does not close a follow-up issue while it fixes it: the
issue stays open until the run's commit-and-push stage has pushed a tree
containing the fix, and the workflow then calls `close` for each issue it
recorded (design §8.4, §17 Z9).

## `review_followup.py`

```bash
scripts_dir="${AIDW_SCRIPTS_DIR:-/path/to/toolkit/prompts/scripts}"

# Read-only: resolve PR -> parent issue -> first available child
"$scripts_dir/review-followup/review_followup.py" select --pr 174

# Read-only: the bounded batch the fix loop asks for (`aidw fix --fix-batch`, default 3)
# `--limit` is explicit, so `selected` is an ARRAY of up to n available children in
# native sub-issue order — `--limit 1` included. Without the flag `selected` stays the
# single object `start`, `fixed` and the approval preview read.
"$scripts_dir/review-followup/review_followup.py" select --pr 174 --limit 3

# Record the exact "Status: in progress" comment (idempotent)
"$scripts_dir/review-followup/review_followup.py" start --pr 174 [--issue 176] [--dry-run]

# Record the exact "Status: fixed" comment and close the issue (in-stage form)
"$scripts_dir/review-followup/review_followup.py" fixed --pr 174 --issue 176 --body-file ./close-body.md [--dry-run]

# Deferred close: the same action for one named issue, no selection
# (`aidw fix` runs this after the fix has been pushed)
"$scripts_dir/review-followup/review_followup.py" close --pr 174 --issue 176 --body-file ./close-body.md [--dry-run]

# Read-only: assert closed, marked fixed, labels intact
"$scripts_dir/review-followup/review_followup.py" verify --pr 174 --issue 176

# Apply the human approval to every open child (idempotent)
"$scripts_dir/review-followup/review_followup.py" approve --pr 174 [--dry-run]
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | The issue's verification failed (`verify`) |
| `2` | Usage, validation, or GitHub-command error |
| `3` | No approved open review follow-up is available |
| `4` | The requested issue conflicts with the workflow's selection rules |

### `select --limit` semantics

`select` without `--limit` returns the first available child as a single `selected`
object (or `null`), the contract `start`, `fixed` and `fix`'s approval round keep. With
`--limit <n>` it returns up to `n` available children in native `subIssues` order as an
**array** — an explicit `--limit 1` is a one-element array, never an object — plus the
`skipped` children encountered up to and including the last selected one, so
`childrenInspected` is `len(skipped) + len(selected)`. Exit code `3` means the batch is
empty; no child after the batch is inspected.

### `--issue` semantics

`--issue` may only name the child that native-order selection already chose, or
the workflow's **in-flight child**: an open child that already carries an exact
`Status: in progress` comment. The in-flight exception exists because `start`
marks the selected child in progress, which removes it from native-order
selection; without it, the run that started a child could neither resume nor
close it whenever a later approved child exists. It cannot be used to bypass
the "first available child in native `subIssues` order" rule, and it does not
authorise a later untouched child. `verify` is exempt from the guard, because
its main use is re-reading the child that was just closed.

`close` is the second exception, and it **requires** `--issue`: by the time the
fix has been pushed, the just-fixed child is in flight (`Status: in progress`),
not first-available, so re-running `fixed`'s selection step would refuse every
close after the first with exit `4`. `close` therefore resolves the child by
`--issue` alone and never re-derives a selection; it closes exactly one issue per
call. Its guards and its write are `fixed`'s own (`logic.close_plan` +
`apply_close`): the `review-follow-up`/`approve-fix` label guard, refuse-to-reopen,
a closing body that must not repeat `Status: fixed`, and post-close verification
that returns `1` when the labels or the closed state did not survive.

## `publish_review_followups.py`

```bash
scripts_dir="${AIDW_SCRIPTS_DIR:-/path/to/toolkit/prompts/scripts}"

"$scripts_dir/review-followup/publish_review_followups.py" [--pr <number-or-url>] --input <manifest.json> [--repo <owner/name>] --dry-run
"$scripts_dir/review-followup/publish_review_followups.py" [--pr <number-or-url>] --input <manifest.json> [--repo <owner/name>]
```

It validates the PR and manifest, creates missing labels, reconciles existing
parent/child issues using stable markers, verifies native sub-issue
relationships, and creates or updates the single PR summary comment. It is
idempotent and stops on ambiguous matches. Exit code `0` means success; `2`
means usage, validation, or GitHub error.

## Safety model

- Selection uses the parent's native `subIssues` relationship only — never
  titles, labels, or creation dates. Children after the selected one are not
  inspected.
- Availability uses strict equality on comment bodies, so a prose comment that
  merely mentions a status cannot mark an issue.
- Every write is idempotent: repeating `start`, `fixed`, or `approve` does not
  duplicate status or decision comments.
- `--issue` cannot skip ahead: an explicit child must either be the one
  native-order selection chose or be the workflow's in-flight child (open, with
  an exact `Status: in progress` comment).
- `fixed` and `close` share one rule (`logic.close_plan`): they refuse an issue
  lacking `review-follow-up` or `approve-fix`, refuse to reopen a closed issue, and
  refuse a closing body that begins with `Status: fixed` (that exact comment is
  posted separately). Repeating a completed close is a no-op, not a conflict.
- All external commands run through `subprocess` with argument arrays and no
  shell, so comment bodies, titles, and paths cannot be re-interpreted.

## Layout

| File | Purpose |
|---|---|
| `constants.py` | Workflow policy shared by both CLIs: labels, exact status bodies, markers, exit codes |
| `logic.py` | Pure selection logic, argument parsing, and manifest validation (unit tested) |
| `proc.py` | Shell-free process helper |
| `gh.py` | All `gh` access and JSON shapes |
| `review_followup.py` | `select`/`start`/`fixed`/`close`/`verify`/`approve` CLI entry point |
| `publish_review_followups.py` | Publisher CLI entry point |
| `tests/test_logic.py` | Unit tests for selection and close-plan logic |
| `tests/test_close.py` | Unit tests for the `close`/`fixed` CLI tail (no real `gh`) |
| `tests/test_publish_logic.py` | Unit tests for manifest validation and publisher arguments |

`constants.py` holds the label names, exact status and decision comment text,
and parent/child/summary markers shared with the sibling prompts. Change them
in one place and the prompts together, or not at all.

## Tests

The unit tests import the script modules directly and run with AIDT's suite:

```bash
cd aidt
uv run pytest prompts/scripts/review-followup/tests
```
