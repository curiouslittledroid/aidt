# AIDT — AI Developer Tools

AIDT is a developer-workflow toolkit that drives the [Pi](https://github.com/badlogic/pi)
coding agent from the command line through the SDLC stages of a **target repo** — any git
repository you point it at. A developer selects a roadmap task, and `aidw` drives one or more
specialised agents through the workflow's stages, pausing at human decision gates and
recording every stage, gate and cost.

The toolkit is installed once from a tag and never vendored into the repository it works on:
the **toolkit root** and the **target repo root** are two distinct roots, never
interchangeable (design.md §1.1).

The repository is `aidt`; the package and CLI are `aidw` — see
[Repository, naming, and provenance](#repository-naming-and-provenance).

The authoritative design is [`design.md`](./design.md). This README is both the quickstart
and the operator guide.

> **Not yet implemented.** [`EXPLICIT-RESOURCES.md`](./EXPLICIT-RESOURCES.md) describes the
> planned future state in which an agent config file is the **only** place skills,
> extensions, custom tools and MCP servers are declared for what Pi may pull into a stage —
> the target repo's `AGENTS.md` and the agent's own `AGENTS.md` stay automatic. Today Pi's
> own discovery still adds user-level and target-level resources to every stage. The
> implementation plan is [`docs/tasks/01 - Explicit Resources.md`](./docs/tasks/01%20-%20Explicit%20Resources.md),
> scheduled after the migration ([`docs/migration/EXTRACTION.md`](./docs/migration/EXTRACTION.md))
> finishes.

## Install

AIDT is distributed from git, not PyPI. D9 fixes two install forms, both pinned to a tag:

| Form | Command | Use it for |
|---|---|---|
| **Primary — `uv tool install`** | `uv tool install "git+https://github.com/curiouslittledroid/aidt@v0.1.0"` | An `aidw` on `PATH` for everyday use, in its own uv-managed tool environment. |
| **Secondary — `uvx`** | `uvx --from "git+https://github.com/curiouslittledroid/aidt@v0.1.0" aidw --version` | A one-off run without installing anything (swap `--version` for any other subcommand). |

`v0.1.0` is the first release tag; replace it with the `v<X.Y.Z>` release you have verified.
Tags are cut on merged `main` — the version bump, the tag command and the install verification
are the release process in [`docs/releasing.md`](./docs/releasing.md). (The repository's
`baseline-verbatim` tag marks the verbatim import, not a release.) If no release fits, pin a
commit SHA instead; `@main` also works but is unpinned and therefore not reproducible.

The `uvx` form needs `--from <git-url>`: a bare `uvx aidw` resolves a package named `aidw` from
PyPI, which is not this repository.

Smoke-check the install from the control worktree of a bootstrapped workspace (see
[Workspace layout and bootstrap](#workspace-layout-and-bootstrap)):

```bash
aidw --version     # works anywhere, no target repo needed
aidw doctor        # toolkit + git/gh/pi versions, workspace/state roots, prompts, agent configs
```

Every run records the toolkit version and the resolved target config in its `state.json`
(D9, E8.2), so an old run says which toolkit and config produced it. AIDT needs **git ≥ 2.31**;
`aidw doctor` checks that too (see below).

## Workspace layout and bootstrap

AIDT runs against a **workspace**: one bare repository plus sibling worktrees. Every worktree is a
**sibling of the bare repo**, all of them are linked off the bare repo, none is a separate clone,
and `main` is not one either (EXTRACTION.md §3.2). Supported layout:

```text
~/mythical-forge/
├── bare.git/        # bare clone — the common dir for every worktree
├── main/            # control worktree: base branch permanently checked out
├── 03.1-B2/         # task worktree
└── 04.2-A1/         # task worktree
```

Bootstrap it **once**, with the target repository's remote:

```bash
git clone --bare https://github.com/curiouslittledroid/aidt.git bare.git
git -C bare.git worktree add ../main main
```

The remote shown is this repository's own `origin`, because `aidt` dogfoods its own workflows
(D21); for a different target repo, substitute that repo's remote URL and the layout is the same.
Then run every `aidw` command from the control worktree `main/` — it is the one with the base
branch checked out.

Both commands matter. Bootstrap must start from `git clone --bare`: a normal `git clone` followed
by `git worktree add` produces the **clone-of-a-worktree** layout that
[AIDT refuses to run on](#supported-and-rejected-layouts).

Verify the result — the bare repo is the common dir from every worktree:

```bash
git -C main rev-parse --path-format=absolute --git-common-dir   # → <workspace-root>/bare.git
```

`--path-format=absolute` needs **git ≥ 2.31**, and AIDT derives the workspace root from exactly
that command, so the layout does not work on older git. `aidw doctor`'s `git version` check fails
below 2.31 and says to upgrade.

### Task worktrees are created by AIDT

The bootstrap above is **one-time** setup only. AIDT owns per-task worktree creation (D20, §3.2
"Consequences"; E2.4/E2.5): `aidw prompt` creates the task branch's worktree and then runs its
stages inside it. The command it runs — and the one `aidw implement` prints when the worktree for
its branch is missing — is the §3.2 per-task form:

```bash
git -C <workspace-root>/main worktree add -b <branch> <workspace-root>/<branch> <base-branch>
```

Do not hand-run that for each task, and do not create the branch on `main` with `git checkout -b`
or `git switch -c`: a branch already checked out in `main/` cannot be checked out a second time
(see the rejected layouts below), and the worktree is still AIDT's to create. `aidw worktree list`
shows the branch ↔ worktree mapping it uses.

### Supported and rejected layouts

Only one layout is supported: `bare.git` (the common dir) with `main/` and every task worktree as
its **siblings**, all registered in the bare repo. `aidw doctor` confirms it with `workspace root`,
`state root` and `control worktree` all `ok`, and run state lives at
`<workspace-root>/.aidw/state/<repo-slug>/` (D18) — outside every worktree, so pruning a worktree
can never delete it.

Two other layouts look reasonable and are rejected, and the bare directory itself cannot be a
target:

| Layout | Why it fails |
|---|---|
| **`main` as a plain clone**, with worktrees hanging off it (the **clone-of-a-worktree** trap) | The worktrees register in `main/.git`, so `dirname(<absolute git-common-dir>)` is the clone folder and the state root lands **inside a prunable worktree**. `aidw/layout.py:check_layout` refuses to run on it, and `aidw doctor` fails `control worktree` with the re-bootstrap commands. |
| **Creating the branch on `main`, then moving it** into a worktree | Impossible: git allows one checkout per branch and refuses the second, `fatal: '<branch>' is already checked out at '<path>'`. That is why the task branch is born in its own worktree. |
| **The bare directory as the target** (`cd bare.git`) | A bare repo has no working tree, so git's `rev-parse --show-toplevel` fails. AIDT refuses and prints the `worktree add ../main main` command to run instead, and `aidw doctor` fails `target repo`. |

## Repository, naming, and provenance

This repository is **`aidt`** ("AI Developer Tools") — the toolkit's own home, not a
directory inside a product repository. The importable Python package and the console
command are both **`aidw`** ("AI Developer Workflows").

Two roots, resolved independently:

| Root | What it is | Resolved from |
|---|---|---|
| **Toolkit root** | Where this repo's code, default prompts (`prompts/`), agent configs (`agent-configs/`) and bundled scripts live. | The installed package location, so it never depends on the working directory or on which repository `aidw` runs against. |
| **Target repo root** | The working tree whose roadmap, task prompts and artifacts a workflow operates on. | Git, starting at the working directory; `--repo <path>` overrides it. |

> **`aidw/` means two different things, by design.** Inside *this* repo, `aidw/` is the
> Python **code**. Inside a *target* repo, a tracked `aidw/` folder is **configuration**:
> `aidw/config.yaml`, optional `aidw/conventions.md`, and optional prompt overrides under
> `aidw/prompts/`. A target repo with no `aidw/` folder is valid and gets the toolkit's
> defaults.

**Provenance.** This repository starts from a single verbatim copy of `aidt/` from
`mythical-forge@31c720afb845e6bc23948f6f0aadae872ce3ff1c`, committed unmodified and tagged
`baseline-verbatim` (inspect it with `git show baseline-verbatim`), so any later behavioural
difference can be diffed against a known-good reference. The extraction plan of record is
[`docs/migration/EXTRACTION.md`](./docs/migration/EXTRACTION.md).

## Status

All seven design phases are complete: `prompt`, `implement`, `review`, `fix`, the `run`
chains, and hardening (cost ceilings, transient retry, `--parallel`, tests). The
`approve-followups` command extracts the approval step from `aidw fix` so GitHub
approval decisions can be applied on their own.

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Scaffold, `doctor`, CLI skeleton | ✅ |
| 1 | Agent configs, AIDT-owned prompts, argv rendering | ✅ |
| 2 | Pi invocation, run state, gates | ✅ |
| 3 | `aidw prompt` + `aidw tasks` | ✅ |
| 4 | `aidw implement` + resume | ✅ |
| 5 | `aidw review` + findings publication | ✅ |
| 6 | `aidw fix` + review/fix loop | ✅ |
| 7 | Hardening, tests, README | ✅ |
| — | `aidw approve-followups` (standalone approval step) | ✅ |

## Prerequisites

| Requirement | Check |
|---|---|
| `aidw` installed from a release tag (→ [Install](#install)) | `aidw --version` |
| `python3` ≥ 3.9 on `PATH` for the review/fix prompts, which invoke the bundled helper scripts directly (`aidw` itself uses its own interpreter) | `python3 --version` |
| `pi` on `PATH`, authenticated for the configured providers | `pi --list-models` |
| `gh` ≥ 2.94.0 and authenticated (review/fix workflows) | `gh --version`, `gh auth status` |
| AIDT-owned prompts/scripts present in the toolkit | `aidw prompts check` |
| Valid agent configs in the toolkit | `aidw agents validate --strict` |

Run every `aidw` command from the control worktree `main/`: the target repo is auto-detected
via git from the working directory, and `--repo <path>` overrides it (design.md §1.1, F6).

`aidw doctor` exits `0` when nothing **fails** (warnings — e.g. a dirty tree — are fine).
Fix any `FAIL` before starting a workflow.

AIDT is self-contained: it never reads `.pi/prompts/`. `prompts/` in the toolkit root is
AIDT's own source of truth and is edited freely.

## Quickstart

An operator needs three things: `aidw` on `PATH`, a bootstrapped workspace, and a target repo
with a roadmap.

1. **Install** the toolkit, once, from a release tag (details in [Install](#install)):

   ```bash
   uv tool install "git+https://github.com/curiouslittledroid/aidt@v0.1.0"
   ```

2. **Bootstrap** the target repo's workspace once — one bare repo plus sibling worktrees
   (details in [Workspace layout and bootstrap](#workspace-layout-and-bootstrap)):

   ```bash
   git clone --bare <target-repo-remote> bare.git
   git -C bare.git worktree add ../main main
   ```

3. **Run from the control worktree**, where the base branch is checked out:

   ```bash
   aidw doctor                          # environment: toolkit, git/gh/pi, roots, prompts, agents
   aidw tasks --todo                    # the target repo's unchecked roadmap tasks
   aidw prompt <phase> <epic> <task>    # author + review that task's prompt (--dry-run: plan only)
   ```

`aidw prompt` creates the task's branch and worktree itself and runs its stages inside it; a
real run needs `main` checked out and a clean tree in the control worktree, while `--dry-run`
plans the stages from any branch without those preconditions. From there the workflow chains in
[Workflows](#workflows) take over.

## Workflows

Every workflow is atomic, resumable where noted, and records state under
`<state root>/<repo-slug>/runs/<run-id>/` — the state root is outside every worktree, so
pruning a worktree can never delete a run (design.md §9.1). `<run-id>` is
`<utc-stamp>-<task-or-pr>-<workflow>` — for example
`20261022T073150Z-03.1-A2-implement`, so several runs of one task are distinguishable by name
(`-prompt`, `-implement`, `-review`, `-fix`, `-approve`). All support `--dry-run` (no Pi, no writes; `fix --dry-run` still
performs a read-only `gh` select), `--yes` (approve all gates), `--strict` (treat config
warnings as errors), `--skip-gates <name>`, `--deny-gates <name>`, and
`--gate-default approve|deny`. Enter at a gate prompt approves (`[Y/n]`) unless
`--gate-default deny` or `AIDW_GATE_DEFAULT=deny` is set, which restores `[y/N]`.

### `aidw prompt` — task prompt generation and review

Resolves a roadmap task, then runs `/task-prompt` (authoring agent) followed by
`/task-review` (a different, read-only reviewer model) with a bounded rework loop. The
final `approve-task-prompt` gate is **optional and off by default** — the reviewer already
verifies the prompt. Add `--require-approval` to pause for a human decision.

```bash
aidw tasks --todo --phase 03        # find a task
aidw tasks --show "03 E4 E4.1"      # task detail, branch, Done when, specs
aidw prompt 03 E4 E4.1 --dry-run    # plan only; no Pi, no writes
aidw prompt 03 E4 E4.1              # real run; no approval gate
aidw prompt 03 E4 E4.1 --require-approval   # pause for human verification
```

A **real run requires `main` and a clean working tree** in the control worktree: AIDT creates
the `<phase>-<task>` branch and its worktree itself, runs the stages inside it, and commits the
reviewed prompt there — no stage runs `git checkout -b`. `--dry-run` plans the stages from any
branch without those preconditions.

The generated prompt lands in the target repo's task-prompts directory,
`docs/task-prompts/<phase>-<task>-prompt.md` by default (`paths.task_prompts_dir`).

### `aidw implement` — implement a task prompt and open the PR

Takes a generated task prompt, derives the task id and branch from its filename, and runs
the nine focused stages serially, leaving the tree uncommitted until `/pr` owns delivery:

```text
I1 impliment-task                    implementer  (shared session)
I2 test                              tester       (fresh)
I3 update-traceability               implementer  (shared)   repo-optional
I4 update-architecture               implementer  (shared)   repo-optional
I5 record-implementation-results     recorder     (fresh)    SYNC POINT
I8 summarize-implementation-results  recorder     (fresh)
I9 write-integration-test-guide      recorder     (fresh)    human-run guide, runs nothing
I7 update-roadmap                    recorder     (fresh)    only if the gates are green
◇  approve-implementation-pr
I6 pr                                pr-publisher (fresh)
```

```bash
# plan only: prints I1–I9 with agents/models; no Pi, no git or GitHub writes
aidw implement docs/task-prompts/03-E4.1-prompt.md --dry-run

# real run on branch 03-E4.1
aidw implement docs/task-prompts/03-E4.1-prompt.md
```

Preflight refuses to run on `main`, when the current branch does not match the task id
(`<phase>-<task>`), or when another implement run for the branch is still marked running.

The stages run the repo's verification commands through `aidw gate run`, with the gates named
`lint`, `build` and `suite` and one shared `--ignore` scope across every stage. That is what lets
`pr` (I6) cite the suite `test` (I2) or `record` (I5) already ran for the same content instead of
running it a fourth time. Because the stages leave the tree uncommitted, a gate's identity is
the content of the change set relative to `main`, not `HEAD` — so `/pr` committing the gated
tree does not invalidate its own verification. See [`aidw gate`](#aidw-gate--whole-repo-verification-gates)
for the identity rules, the declared scope and when the gate re-runs.

Resume a run after a failure — completed stages are never re-run; the gate is not re-asked
once approved:

```bash
aidw implement docs/task-prompts/03-E4.1-prompt.md --resume
aidw implement docs/task-prompts/03-E4.1-prompt.md --resume --from test
```

`--parallel` runs `test` and `update-architecture` concurrently (disjoint files: package
tests vs `docs/architecture/**`). Use it when you are confident the two agents touch no
shared file; otherwise leave it off. Output metadata lands in
`runs/<id>/artifacts/implementation.json` (`pr_number`, `pr_url`, `build_results_path`,
`changed_files`).

### `aidw review` — independent review and findings publication

Runs the read-only `/code-review` prompt (a reviewer model, fresh session), extracts its
findings into a manifest, and — when there are findings — runs
`/review-findings-to-github` to create the parent + child issues through the bundled
publisher script. Publishing is **ungated**: the human decision happens on GitHub before
`aidw fix` (design §6, E2).

```bash
aidw review --pr 42 --dry-run   # plan R1/R2 + print the publisher argv
aidw review --pr 42             # live review + publish
```

Preflight reads the PR via `gh` (read-only) and refuses unless the PR targets `main` and the
PR head's worktree exists locally; it reviews **that** worktree, so it can be run from the
control worktree while the task branch is checked out in a sibling directory. When the
worktree is missing it prints the `git worktree add` line to create it and stops. A `Blocked`
verdict, an ambiguous verdict, or a finding that will not parse into a manifest fails closed:
findings are recorded under `<run-id>/artifacts/findings.json`, but nothing is published.

AIDT never calls a mutating `gh` command. GitHub writes only ever go through the bundled
Python scripts under `prompts/scripts/review-followup/` in the toolkit root (design §13).

### `aidw approve-followups` — approve review follow-up issues

Applies the human approval decision to a PR's open review follow-up issues by running
`/approve-review-followups` with the `review-approver` agent. Use this when you want to
record the decision without starting the `aidw fix` loop:

```bash
aidw approve-followups --pr 42 --dry-run   # list the child issues; no writes
aidw approve-followups --pr 42             # confirm at the gate, then approve
aidw approve-followups --pr 42 --yes       # approve without prompting
```

Preflight requires `gh` and a PR that exists. The prompt adds `approve-fix` and removes
`decision-pending` on every **open** child; closed children are left untouched. All GitHub
writes are performed by the bundled `review_followup.py` script the prompt invokes, so
AIDT itself still never calls a mutating `gh` command. The gate `approve-followups` can be
skipped with `--skip-gates approve-followups`.

### `aidw fix` — fix approved review follow-ups

Takes a PR whose review follow-up issues have been decided **on GitHub**, then runs the
review → fix → re-review loop one approved child at a time:

```text
◇  approve-followups      run /approve-review-followups (review-approver)
⟳  per approved child (selection re-derived from review_followup.py select):
     F1 fix-next-review-followup  fixer
     F2 test                      tester
     F3 code-review               code-reviewer
     if F3 findings: F4 review-findings-to-github (ungated) -> ◇ approve-followups
     else:           ◇ approve-fix-pr
   until no approved child remains, or --max-iterations is reached
I7 update-roadmap          recorder      once, if this run's evidence is green
F5 commit-and-push         pr-publisher  commits the change set and pushes the PR-head branch
review_followup.py close   (Python)      one call per recorded issue, after the push
```

```bash
aidw fix --pr 42 --dry-run              # lists the next approved child via select
aidw fix --pr 42 --max-iterations 5     # live loop
```

The re-review models must differ from the fixer model; `agents validate`/`aidw fix` warn
when no distinct reviewer model exists (and `--strict` fails). `--max-iterations` (default
10) bounds the loop; reaching it stops the run as blocked. All GitHub writes are performed
by the bundled prompts/scripts (the fixer and approver agents, and the deferred close); AIDT
only reads `gh pr view` and `review_followup.py select` itself.

A converged run **publishes its own work**: `F5 commit-and-push` commits the change set the run
accumulated — the fixes plus the `I7` roadmap tick when it flipped — and pushes the PR-head
branch, then AIDT records the verified remote head as `state.pr["head_sha"]`. Nothing about that
is silent: a stage that cannot commit or push, a stage that discards the change set instead of
committing it (`HEAD` never moved), a push whose remote head does not match `HEAD`, a tree left
dirty, or a run that closed an issue with nothing to push fails the run (exit non-zero) with a
message naming the PR and the branch. A run that closed no issue publishes nothing — it
records `state.pr["commit_skip_reason"]` and exits 0 rather than committing a stranger's dirt or
an empty commit. `F5` never force-pushes, never merges, and refuses outright when the resolved PR
head is the base branch; `commit`/`push` remain the `pr-publisher` agent's, never Python's.

The fixer no longer closes the issue it fixed. Each `F1` writes its closing comment body to
`<run_dir>/artifacts/iter{N}-closing-body.md` and leaves the issue `OPEN` with its exact
`Status: in progress` comment; once `F5`'s push is verified, AIDT runs `review_followup.py
close --issue <n> --body-file <path>` for each issue this run recorded, which posts the exact
`Status: fixed` comment (idempotent) and closes the issue with that body. A close that fails —
`close` exits non-zero, or a recorded fix has no verified push — fails the run instead of
reporting the issue fixed, and a run that recorded no fix closes nothing.

Approval flow: after `review` publishes children, review them on GitHub and record
`Decision: approve-fix` / `accepted-risk` / `not-a-bug`, then run `aidw fix`. The
`approve-followups` gate runs `/approve-review-followups`, which applies the decisions via
`review_followup.py approve` (adds `approve-fix`, removes `decision-pending`).

### `aidw run` — chains

```bash
aidw run task-to-pr 03 E4 E4.1       # prompt, then implement
aidw run prompt-to-fix 03 E4 E4.1    # prompt, implement, review, follow-ups, fix
aidw run review-and-fix --pr 42      # review, then fix
```

A chain stops at the first non-zero exit and returns that code. For `review-and-fix`, the
`fix` approval gate still enforces the human GitHub decision; do **not** pass `--yes`
unless the decisions are already on GitHub.

`prompt-to-fix` is the whole cycle, in the four orchestrators' own order:

```text
prompt → implement → review → approve-followups (auto-approved) → fix
```

It discovers the PR number from the `implement` run's state (`--pr <n>` overrides, and a
`--dry-run` uses a placeholder). Because `approve-followups` would otherwise stop an
unattended chain, this chain adds it to the `fix` stage's skip set and prints
`chain:  auto-approving \`approve-followups\` …` when it does. That is the **only**
gate the chain approves for you: `approve-implementation-pr` and `approve-fix-pr` keep
their normal `--yes`/interactive behaviour, and `--deny-gates approve-followups` refuses
the auto-approval (deny wins over skip), so the fix loop stops at the gate instead.

An `Approve` review that publishes no findings ends the chain there, with exit code 0:

```text
verdict: Approve
review approved with no findings; nothing to publish
chain:  review published no follow-ups for PR #72; nothing for the fix loop to approve or fix.
chain complete.
```

There is no review-follow-up parent issue in that case, so the fix loop would have nothing
to approve or fix — and running it would fail its entry postcondition. `review` records the
outcome in its run state (`pr.followups_published`), and the chain reads it: follow-ups
published by an earlier round of the same PR keep the loop, and if no record is readable
(a `--dry-run`, or a state root the chain did not write) the chain runs `fix` as before.
`aidw fix --pr <n>` on its own is unchanged and still fails closed.

### Roadmap inspection

```bash
aidw tasks                  # all tasks
aidw tasks --todo           # unchecked only
aidw tasks --phase 03 --epic E4
aidw tasks --next --phase 03
```

### `aidw gate` — whole-repo verification gates

`aidw gate run` runs one of the repo's own verification commands — the suite, lint, a build —
and records its outcome against the identity of the tree it gated. The second and later stages
of a run to ask for the same gate against the same content **cite the recorded outcome instead
of running it again**, so a full suite is bought once per run rather than once per stage. In the
implement chain the same suite is asked for at several stages and answered once.

```bash
# the command is the target repo's own and goes after -- (click stops parsing options there),
# so the payload keeps its real form even though the aidw command position never does
aidw gate run suite -- uv run --frozen pytest
aidw gate run suite -- pnpm -r test

# list the outcomes this run recorded
aidw gate list            # or: aidw runs show <run-id>
```

A gate is identified by its key (`suite`, `lint`, `build` — whatever the stages agree on),
so stages asking for the same gate must use the same key. The first ask runs the command and
prints its output tail followed by one outcome line; a later ask prints:

```text
note: this run already passed this gate for this tree
reused: gate 'suite' passed for tree 14acd7750fe3 at 2026-10-26T05:46:36Z by stage 'test' (439 passed in 97.98s)
```

and exits `0` without running anything. The citation names its origin — key, tree, stage and
timestamp — so a reader judges it rather than trusting a bare number. It exits with the
gate's own exit code, so a failing gate still fails the stage that asked for it.

**Identity is content, not commit history.** The identity hashes every path whose content
differs from the base branch (`--base`, default `main`) plus every untracked, non-ignored path.
`HEAD` is deliberately excluded: `/pr` commits the change set it just gated, and committing a
verified tree must not invalidate its own verification. Any content change — an edit, a new
file, a deletion, an execution-bit flip — changes the identity and the gate re-runs. A commit,
an identical rebase or a `git add` does not.

**Declared scope (`--ignore`).** A whole-tree identity is sound but rarely reusable in the real
chain, because `record` (I5) writes its results document *after* running the gate: the tree
`pr` delivers is never byte-identical to the tree `test` gated. So a gate may declare paths its
command cannot read:

```bash
aidw gate run suite \
  --ignore docs/implementation-results --ignore docs/architecture \
  --ignore docs/tasks --ignore docs/task-prompts \
  -- uv run --frozen pytest
```

The declaration is made by the stage that ran the gate, stored in the outcome, printed in every
citation, and is part of what must match before anything is cited — two stages must pass the same
`--ignore` values or the outcomes cannot line up. It is a *declaration*, not an inference:
nothing is guessed from file type or location. Declare only the documents other stages write —
never source, tests, config or lockfiles — and add any directory a stage of the workflow writes
(for example a traceability report). Nothing outside the declared scope can be skipped.

**Fail closed.** The command runs, exactly as it always did, when the outcome cannot be proven:
no resolvable base branch; no run to record into (then a `note:` says so); a different command
under the same key; a differently declared scope; a previous **failed** outcome for this tree;
or a change set too large to hash cheaply (over 5000 paths or 256 MB — a repo that does not
gitignore `node_modules` costs a listing, not minutes of hashing). There is no path from
"unknown" to "skip". Reuse is also confined to the **same run**: an outcome from an earlier run
is not evidence about this one. `--force` runs regardless — use it when the environment changed
under a passing gate (dependencies reinstalled, a gitignored cache rebuilt). A failed outcome is
still recorded, so `aidw gate list` shows it.

Gates are recorded in `state.json` under `gate_outcomes`, and both `aidw runs show <run-id>` and
`aidw gate list` print them with their command, summary, duration and declared scope. `--json`
emits one object instead of text.

A stage's agent finds its own run without being told: the stage runner exports `AIDW_RUN_ID` and
`AIDW_STAGE`, which `aidw gate run` uses when `--run`/`--stage` are absent. At a terminal with
neither set, the gate records into the latest run for the current branch; naming a run that does
not exist is a usage error rather than a silent fall-through to the branch.

### `aidw exec` — a single stage

`aidw exec` runs one agent stage — the primitive the workflows build on. It is also the
supported way to smoke-test an agent.

```bash
# plan only: writes state.json + the rendered prompt, does not invoke Pi
aidw exec --agent code-reviewer --prompt code-review --dry-run

# live run
aidw exec --agent code-reviewer --prompt tests/fixtures/noop.md --label smoke
```

Run artifacts land under `<state root>/<repo-slug>/runs/<utc-stamp>-<task-or-pr>-<workflow>/`,
never inside a working tree (design.md §9.1; [Workflows](#workflows) has the run-id shape):
`state.json`, `run.log`,
`prompts/<stage>.rendered.md`, `stages/<stage>.jsonl` (the raw Pi event stream) with its
`.out.txt` and `.meta.json` siblings, and `artifacts/`. `state.json` starts with a `totals`
section — the combined input tokens, output tokens, and cost across every stage in the run — and
carries `gate_outcomes`: every verification gate recorded for the run, with its tree identity,
command, exit code, summary, duration, origin stage and declared scope (`aidw runs show <run-id>`
prints them; see [`aidw gate`](#aidw-gate--whole-repo-verification-gates)).

Each finished stage also prints a report block — model, duration, cost, generation speed, usage
counters, and the `stages/<stage>.out.txt` path:

```text
stage:  task-review-1 [succeeded] model=openrouter/meta/muse-spark-1.3 132.3s cost=$0.0287 32.0 out-tok/s
        usage: total=50.6k in=193 out=16 cache_read=50.4k cache_write=0 reasoning=0 cost=$0.0287
        out:   <state root>/<repo-slug>/runs/<run-id>/stages/task-review-1.out.txt
```

Every stage also records `generation_seconds` and `output_tokens_per_second`: the time Pi spent
generating assistant messages (prompt prefill and tool execution excluded) and the output tokens
divided by it. The rate is stored per stage, not aggregated by model, and is `null` when the stage
produced no output or carried no measurable generation window.

`stages/<stage>.meta.json` records the same counters plus the prompt the stage used
(`prompt_source`, `rendered_prompt`), the argv, model, session id, attempts, and exit code.
`aidw runs show <run-id>` prints the same fields. A task-prompt review that requests changes
also reports the parsed finding count and one `fix <round>.<i>/<n>: <title>` line per
**blocking** (must-fix/should-fix) finding; the non-blocking could-fix findings are batched
into a single stage (`fix 1.3/3: 2 could-fix findings combined`).

While a stage is running, an interactive terminal shows a live progress line on stderr, fed by the
events Pi streams:

```text
▶ task-review-1 (task-reviewer) model=openrouter/meta/muse-spark-1.3
  ..*+.+.+.**
```

`.` = heartbeat (nothing new for 10s, Pi is still working), `*` = a completed model response,
`+` = a tool call. It appears only when stderr is a terminal, so CI logs and piped output stay
clean; `--progress` forces it on and `--no-progress` turns it off.

```bash
aidw runs list
aidw runs show <run-id>
```

### Agents

Agents are defined by YAML under `agent-configs/` in the toolkit root, each with its own model, system
prompt, context file (`agents/<id>/AGENTS.md`) and **tool allowlist**. Tool access is
deny-by-default: an agent gets exactly the tools listed, and an empty list means no tools.

```bash
aidw agents list
aidw agents show code-reviewer
aidw agents validate --strict
```

To change an agent's model, edit its YAML. Reviewer agents must use a different model
from the agent whose work they judge; `agents validate` warns when they do not (and
fails under `--strict`).

### Prompts and helper scripts

`prompts/` in the toolkit root is **AIDT's own** prompt and helper-script tree — the source of
truth for every workflow. It is edited freely as the workflows evolve; it is not copied from,
or compared with, any other directory.

It ships **neutral defaults only**. A product-specific prompt is not part of this library: the
repo that owns it keeps it under its own `aidw/prompts/`, where it shadows the default of the same
name, and a prompt the toolkit does not ship cannot be reached by name — `aidw exec --prompt
<name>` reports it as missing rather than falling back to something close. New instructions and new subcommands in the bundled
scripts (for example `review-followup approve`) are expected. A target repo overrides a
prompt per stage under its own `aidw/prompts/` — see the `aidw/` note in
[Repository, naming, and provenance](#repository-naming-and-provenance).

```bash
aidw prompts list     # every prompt/script AIDT owns
aidw prompts check    # required files present, no .pi/prompts references
```

`aidw prompts check` (and `aidw doctor`) fail when a required prompt/script is missing or a
file reaches outside the toolkit root, so a workflow cannot die at Pi-invocation time
(`aidw/inventory.py` holds the required inventory).

## Commands

```text
aidw doctor
aidw prompt    <phase> <epic> <task> [--dry-run] [--require-approval] [--yes] [--strict]
              [--gate-default approve|deny] [--skip-gates ...] [--deny-gates ...]
aidw implement <task-prompt-path> [--resume] [--from <stage>] [--pr <n>] [--parallel]
              [--dry-run] [--yes] [--strict] [--gate-default approve|deny]
              [--skip-gates ...] [--deny-gates ...]
aidw review    --pr <n> [--dry-run]
aidw fix       --pr <n> [--max-iterations N] [--dry-run]
              [--gate-default approve|deny] [--skip-gates ...] [--deny-gates ...]
aidw approve-followups --pr <n> [--dry-run] [--yes] [--strict]
              [--gate-default approve|deny] [--skip-gates ...] [--deny-gates ...]
aidw run       task-to-pr <phase> <epic> <task> | prompt-to-fix <phase> <epic> <task> [--pr <n>]
               | review-and-fix --pr <n>
              [--dry-run] [--yes] [--strict] [--parallel] [--force-model]
              [--max-iterations N] [--skip-gates ...]
              [--gate-default approve|deny] [--deny-gates ...]
              [--allow-incomplete-prereqs]
aidw tasks     [--todo] [--phase NN] [--epic X] [--next]
aidw agents    list | show <id> | validate
aidw runs      list | show <id> | resume <id>
aidw prompts   list | check
aidw exec      --agent <id> --prompt <name|path> [--label <name>] [--dry-run]
aidw gate      run <key> -- <command> [args...] [--run <id>] [--stage <name>]
               [--base <branch>] [--ignore <prefix> ...] [--force]
               [--tail N] [--timeout S] [--json]
               list [--run <id>] [--json]
```

Global options: `--repo <path>`, `--verbose`, `--retry-transient/--no-retry-transient`,
`--progress/--no-progress`.

## Gates

These are the **human approval** gates a workflow asks you to confirm, and are distinct from
`aidw gate run`'s **verification** gates — a repo's own commands (`pytest`, `pnpm -r test`) whose
outcomes are recorded and reused within a run (see
[`aidw gate`](#aidw-gate--whole-repo-verification-gates)). An approval gate asks a person; a
verification gate runs a command. Both record their decisions in `state.json`.

| Gate | Workflow | What approval does |
|---|---|---|
| `approve-task-prompt` | prompt | Optional (off by default; enable with `--require-approval`). On approval, commits the reviewed task prompt on the task branch |
| `approve-implementation-pr` | implement | Allows `/pr` to commit, push, and open the PR |
| `approve-followups` | fix, approve-followups, prompt-to-fix (auto-approved) | Runs `/approve-review-followups` (applies GitHub decisions) |
| `approve-fix-pr` | fix | Records a clean re-review for one fixed child |

Every gate is skippable (`--yes`, or `--skip-gates <name>`), refusable (`--deny-gates <name>`,
which wins over both), and each decision/skip is recorded with its mechanism and timestamp.

**Enter approves by default** — the prompt reads `[Y/n]`, and an accepted default is recorded as
`human-default` rather than `human` so the state file still distinguishes consent from
convenience. Override the default per run with `--gate-default deny`, or per shell with
`AIDW_GATE_DEFAULT=deny`; both restore the strict `[y/N]` prompt. In a non-interactive session
an unapproved gate **still fails closed** — the default is a convenience for a human at a
terminal, not an auto-approval for a script, so `--yes` remains the way through CI.

## Exit codes

`0` success/approved · `1` stage failure · `2` usage/config · `3` blocked (needs a human) ·
`4` preflight/safety refusal.

## Cost control and retries

- `--no-retry-transient` (global) disables the single automatic retry on a clearly
  transient Pi invocation error (network/provider 5xx). Gate failures are never retried.
- Per-agent `max_cost_usd` in `agent-configs/<agent>.yaml` (toolkit root) fails a stage with
  `cost_ceiling` when its cost exceeds the ceiling. Real cost is recorded per stage in
  `state.json` and `.meta.json`; the run's combined `totals` is at the top of `state.json`.
- A stage that spends tokens at a `$0.0000` cost is reported as a pricing gap, not a free
  run: `WARN stage <name>: …` in `run.log`, plus a `note:` line in the stage block. Pi prices
  a model from its catalog entry, so a `models.json` `models` entry that shadows one without
  `cost` silently zeroes it — use `modelOverrides`, which merges. Local providers (`ollama`)
  are exempt. A zero-cost stage also disables that agent's `max_cost_usd` ceiling.

## Boundaries — what AIDT will not do

- Never merge; never force-push; never `reset --hard`, `clean`, or `checkout -- .`.
- Never commits in `implement`/`fix` (the `/pr` agent and the fixer own/leave changes; the
  fix loop leaves fixes **uncommitted** for you or CI to commit).
- Python never calls a mutating `gh` command; GitHub writes go through the bundled
  Python scripts under `prompts/scripts/review-followup/` in the toolkit root.
- `implement`/`fix` refuse to run on `main` or on a branch that is not the task/PR head.
- Never skips a verification gate it cannot prove redundant. `aidw gate run` reuses an outcome
  only for the same run, the same key and command, the same declared scope, and content that
  differs only inside that scope; every other case runs the command. A failed gate is never cited.
- Runs a gate's command as an argv list, never through a shell, so the gate cannot be altered by
  quoting in whatever wrote it down. A repo needing a pipeline runs each side as its own gate.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `working tree is dirty; commit or stash first` | `prompt` needs a clean tree. Commit/stash, or use `--dry-run`. |
| `branch mismatch` | Check out the task/PR head branch. |
| `provider error: 402` / stage `failed` | Provider credits/limits. Top up or switch the agent's model; not transient, so it is not retried. |
| `verdict: ambiguous` / run `blocked` | The model did not end with a clear verdict. Inspect `stages/<stage>.out.txt`, re-run, or set a stronger reviewer model. |
| `prompts check` fails | A required prompt/script is missing, or a file references `.pi/prompts`. Fix the file or the inventory in `aidw/inventory.py`. |
| `gh` errors in review/fix | `gh auth status`; the PR must be **OPEN** and target `main`. |
| `Unknown JSON field: "subIssues"` in a review/fix stage | A stale or shadowed `gh` is first on `PATH`: the review-followup scripts read native `subIssues`/`parent` fields, and sub-issues need `gh` ≥ 2.94.0. `aidw doctor` **FAILs** this as `gh version` before any stage starts; upgrade `gh`, and run `which -a gh` to find the shadowing binary (design.md §12.4). |
| `Refusing to run: … is itself a registered worktree` (**`clone-of-a-worktree`**) | `main/` is a plain clone with worktrees hanging off it, so run state would land inside a prunable tree. `aidw/layout.py:check_layout` refuses to run, and `aidw doctor` **FAILs** the `control worktree` check with the re-bootstrap commands. See [Supported and rejected layouts](#supported-and-rejected-layouts). |
| `'<path>' is a bare repository: it has no working tree` (**the bare directory as the target**) | You are running inside `bare.git`. Run every command from the control worktree `main/`; `aidw doctor` **FAILs** the `target repo` check, and the refusal prints the `git worktree add ../main main` line to run. See [Supported and rejected layouts](#supported-and-rejected-layouts). |
| `fatal: '<branch>' is already checked out at '<path>'` (**creating the branch on `main`, then moving it**) | git allows one checkout per branch, so a branch checked out in `main/` cannot be checked out in a worktree. Let `aidw prompt` create the task branch and its worktree — no `aidw doctor` check covers this one. See [Supported and rejected layouts](#supported-and-rejected-layouts). |
| A stage is stuck/slow | Wall-clock timeout per agent (`timeout_seconds`); the process group is terminated and the partial log kept. |
| Need to continue after a failure | `aidw implement ... --resume` (or `--from <stage>`). `fix` has no resume in v1. |
| A gate re-ran when you expected a citation | Its key, command or `--ignore` scope differs from the earlier ask, the base branch does not resolve, or the content changed outside the declared scope. `aidw gate list` shows what was recorded and with which scope. |
| A gate was cited but you do not trust it | The citation names its origin (tree, stage, timestamp); `aidw gate run ... --force` runs it again. An environment rebuilt under a passing gate — dependencies reinstalled, a gitignored cache regenerated — is the case `--force` exists for. |

## Layout

The toolkit repo is self-contained: everything the toolkit needs at runtime is inside the
installed package plus the three repo-root sibling directories that ship in the wheel, and
everything else is development-time. [`design.md` §3](./design.md) is the authority for the
full tree and for the runtime/development split — this is the same tree, annotated for an
operator:

```text
aidt/                          # toolkit root
├── aidw/                      # the importable Python package + CLI
├── prompts/                   # toolkit DEFAULT prompts (+ scripts/review-followup/)
├── agent-configs/             # default agent configs (a target repo may shadow them)
├── agents/                    # default per-agent AGENTS.md / SYSTEM.md fragments
├── docs/                      # contract docs, this repo's roadmap, task prompts, results
├── tests/                     # pytest
├── fixtures/target-repo/      # a fixture target repo used by the interface tests
├── design.md                  # design of record
├── README.md                  # this operator guide
├── pyproject.toml             # uv-managed; hatchling build; `aidw` console script
├── uv.lock
└── .github/workflows/ci.yml   # pytest + doctor on every push and PR
```

Nothing generated is written into the toolkit repo or into a target repo: runs, locks and
caches live in the state root (design.md §3.3, §9.1). Machine-local content is gitignored and
never committed — `.venv/`, `.pytest_cache/`, and the `.aidw/` state directory a single
checkout resolves inside its own tree (design.md §9.1's warned case).

### Documentation

Four shipped contracts are the reference for what AIDT reads around a target repo:

- [`docs/target-repo-config.md`](./docs/target-repo-config.md) — the `<target>/aidw/config.yaml`
  contract: every field, its type, its default, its provenance and the worked examples.
- [`docs/workflow-stages.md`](./docs/workflow-stages.md) — every stage of every workflow: its
  agent, prompt, arguments, conditions and context, the loops, the gates, and how to declare
  stages. Its tables are pinned to `aidw/stage_registry.py` by a test.
- [`docs/roadmap-format.md`](./docs/roadmap-format.md) — the roadmap format AIDT owns, with the
  canonical worked example the parser tests read.
- [`docs/releasing.md`](./docs/releasing.md) — the tag-based release process, the two install
  forms, and how a target repo pins and upgrades `requires_toolkit`.

Each is cross-linked rather than restated here: a second copy of a field table or an example
drifts from the one the parser and config tests read.

## Development

This is the one place the **checkout** forms belong. Everywhere else in this guide the command
position is the installed `aidw`, because an operator reading it has already installed the
toolkit. Here you are working on the toolkit itself:

```bash
uv sync --frozen                # create the managed environment from uv.lock
uv run --frozen pytest          # the whole suite
uv run aidw doctor
uv run aidw agents validate --strict
uv run aidw prompts check
```

If `uv` is not on your `PATH`, invoke it by full path (e.g. `~/.local/bin/uv`), or run the
console script from the managed environment: `.venv/bin/aidw doctor`.

`pytest` is the only verification (design.md §15), and this repository has its own CI:
[`.github/workflows/ci.yml`](./.github/workflows/ci.yml) runs `uv sync --frozen`, then
`uv run --frozen pytest` and `uv run aidw doctor` on every push and PR. CI installs Pi first.
`uv.lock` is committed and CI is frozen, so adding a dependency means editing
`pyproject.toml` **and** re-syncing the lock in the same change. No test may invoke a real Pi
model: the argv/plan are faked and `--dry-run` is the integration seam.

A target repo's pipeline is unrelated to any of this: the toolkit is never vendored into a
target repo, and a target repo is never a toolkit checkout.
