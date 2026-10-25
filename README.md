# AIDT — AI Developer Tools

AIDT is a developer-workflow toolkit that drives the [Pi](https://github.com/badlogic/pi)
coding agent from the command line to develop the Mythical Forge application. It is
**separate from the Mythical Forge product**, is not built or tested by the product's
pnpm pipeline, and creates no AWS resources.

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

> **Interim state.** Sections below still read from the pre-extraction viewpoint, where the
> toolkit lived at `aidt/` inside the Mythical Forge repository (for example `cd aidt`, or
> `aidt/runs/`). They are rewritten in E9.4; the naming and roots above are the current truth.

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
| Python ≥ 3.11 and [`uv`](https://docs.astral.sh/uv/) (managed environment) | `uv run aidw doctor` |
| `python3` ≥ 3.9 on `PATH` for the review/fix prompts, which invoke the bundled helper scripts directly (`aidw` itself uses its own interpreter) | `python3 --version` |
| `pi` on `PATH`, authenticated for the configured providers | `pi --list-models` |
| `gh` ≥ 2.94.0 and authenticated (review/fix workflows) | `gh --version`, `gh auth status` |
| AIDT-owned prompts/scripts present | `uv run aidw prompts check` |
| Valid agent configs | `uv run aidw agents validate --strict` |

Run everything from `aidt/` (paths are auto-detected inside the Mythical Forge git
repository):

`aidw doctor` exits `0` when nothing **fails** (warnings — e.g. a dirty tree — are fine).
Fix any `FAIL` before starting a workflow.

AIDT is self-contained: it never reads `.pi/prompts/`. `aidt/prompts/` is AIDT's own source
of truth and is edited freely.

## Quickstart

```bash
cd aidt
uv sync                 # create the managed environment and lockfile

uv run aidw doctor               # validate the environment
uv run aidw agents validate      # validate the agent configs
uv run aidw prompts check        # required prompts/scripts present
uv run aidw --help               # list commands
uv run aidw tasks --todo
```

## Workflows

Every workflow is atomic, resumable where noted, and records state under
`aidt/runs/<run-id>/`, where `<run-id>` is `<utc-stamp>-<task-or-pr>-<workflow>` — for example
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
uv run aidw tasks --todo --phase 03        # find a task
uv run aidw tasks --show "03 E4 E4.1"      # task detail, branch, Done when, specs
uv run aidw prompt 03 E4 E4.1 --dry-run    # plan only; no Pi, no writes
uv run aidw prompt 03 E4 E4.1              # real run; no approval gate
uv run aidw prompt 03 E4 E4.1 --require-approval   # pause for human verification
```

A **real run requires `main` and a clean working tree** — the `task-prompt` prompt creates
the `<phase>-<task>` branch from `main` and commits the generated prompt. `--dry-run` plans
the stages from any branch without those preconditions.

The generated prompt lands at `docs/task-prompts/<phase>-<task>-prompt.md`.

### `aidw implement` — implement a task prompt and open the PR

Takes a generated task prompt, derives the task id and branch from its filename, and runs
the six focused stages serially, leaving the tree uncommitted until `/pr` owns delivery:

```text
I1 impliment-task                 implementer (shared session)
I2 test                           tester     (fresh)
I3 update-traceability            implementer (shared)
I4 update-architecture            implementer (shared)
I5 record-implementation-results  recorder   (fresh)   SYNC POINT
◇  approve-implementation-pr
I6 pr                             pr-publisher (fresh)
```

```bash
# plan only: prints I1–I6 with agents/models; no Pi, no git or GitHub writes
uv run aidw implement docs/task-prompts/03-E4.1-prompt.md --dry-run

# real run on branch 03-E4.1
uv run aidw implement docs/task-prompts/03-E4.1-prompt.md
```

Preflight refuses to run on `main`, when the current branch does not match the task id
(`<phase>-<task>`), or when another implement run for the branch is still marked running.

Resume a run after a failure — completed stages are never re-run; the gate is not re-asked
once approved:

```bash
uv run aidw implement docs/task-prompts/03-E4.1-prompt.md --resume
uv run aidw implement docs/task-prompts/03-E4.1-prompt.md --resume --from test
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
uv run aidw review --pr 42 --dry-run   # plan R1/R2 + print the publisher argv
uv run aidw review --pr 42             # live review + publish
```

Preflight reads the PR via `gh` (read-only) and refuses unless the PR targets `main` and
the current branch is the PR head. A `Blocked` verdict, an ambiguous verdict, or a finding
that will not parse into a manifest fails closed: findings are recorded under
`runs/<id>/artifacts/findings.json`, but nothing is published.

AIDT never calls a mutating `gh` command. GitHub writes only ever go through the bundled
Python scripts under `aidt/prompts/scripts/review-followup/` (design §13).

### `aidw approve-followups` — approve review follow-up issues

Applies the human approval decision to a PR's open review follow-up issues by running
`/approve-review-followups` with the `review-approver` agent. Use this when you want to
record the decision without starting the `aidw fix` loop:

```bash
uv run aidw approve-followups --pr 42 --dry-run   # list the child issues; no writes
uv run aidw approve-followups --pr 42             # confirm at the gate, then approve
uv run aidw approve-followups --pr 42 --yes       # approve without prompting
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
```

```bash
uv run aidw fix --pr 42 --dry-run              # lists the next approved child via select
uv run aidw fix --pr 42 --max-iterations 5     # live loop
```

The re-review models must differ from the fixer model; `agents validate`/`aidw fix` warn
when no distinct reviewer model exists (and `--strict` fails). `--max-iterations` (default
10) bounds the loop; reaching it stops the run as blocked. All GitHub writes are performed
by the bundled prompts/scripts (the fixer and approver agents); AIDT only reads
(`gh pr view` and `review_followup.py select`).

The fix stages leave their changes **uncommitted** (the canonical prompts own delivery);
AIDT never commits or force-pushes. Commit/push the fix branch yourself or via CI.

Approval flow: after `review` publishes children, review them on GitHub and record
`Decision: approve-fix` / `accepted-risk` / `not-a-bug`, then run `aidw fix`. The
`approve-followups` gate runs `/approve-review-followups`, which applies the decisions via
`review_followup.py approve` (adds `approve-fix`, removes `decision-pending`).

### `aidw run` — chains

```bash
uv run aidw run task-to-pr 03 E4 E4.1       # prompt, then implement
uv run aidw run review-and-fix --pr 42      # review, then fix
```

A chain stops at the first non-zero exit and returns that code. For `review-and-fix`, the
`fix` approval gate still enforces the human GitHub decision; do **not** pass `--yes`
unless the decisions are already on GitHub.

### Roadmap inspection

```bash
uv run aidw tasks                  # all tasks
uv run aidw tasks --todo           # unchecked only
uv run aidw tasks --phase 03 --epic E4
uv run aidw tasks --next --phase 03
```

### `aidw exec` — a single stage

`aidw exec` runs one agent stage — the primitive the workflows build on. It is also the
supported way to smoke-test an agent.

```bash
# plan only: writes state.json + the rendered prompt, does not invoke Pi
uv run aidw exec --agent code-reviewer --prompt code-review --dry-run

# live run
uv run aidw exec --agent code-reviewer --prompt tests/fixtures/noop.md --label smoke
```

Run artifacts land under `aidt/runs/<utc-stamp>-<task-or-pr>-<workflow>/` (gitignored):
`state.json`, `run.log`,
`prompts/<stage>.rendered.md`, `stages/<stage>.jsonl` (the raw Pi event stream) with its
`.out.txt` and `.meta.json` siblings, and `artifacts/`. `state.json` starts with a `totals`
section — the combined input tokens, output tokens, and cost across every stage in the run.

Each finished stage also prints a report block — model, duration, cost, usage counters, and the
`stages/<stage>.out.txt` path:

```text
stage:  task-review-1 [succeeded] model=openrouter/meta/muse-spark-1.3 132.3s cost=$0.0287
        usage: total=50.6k in=193 out=16 cache_read=50.4k cache_write=0 reasoning=0 cost=$0.0287
        out:   aidt/runs/<run-id>/stages/task-review-1.out.txt
```

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
uv run aidw runs list
uv run aidw runs show <run-id>
```

### Agents

Agents are defined by YAML under `agent-configs/`, each with its own model, system
prompt, context file (`agents/<id>/AGENTS.md`) and **tool allowlist**. Tool access is
deny-by-default: an agent gets exactly the tools listed, and an empty list means no tools.

```bash
uv run aidw agents list
uv run aidw agents show code-reviewer
uv run aidw agents validate --strict
```

To change an agent's model, edit its YAML. Reviewer agents must use a different model
from the agent whose work they judge; `agents validate` warns when they do not (and
fails under `--strict`).

### Prompts and helper scripts

`aidt/prompts/` is **AIDT's own** prompt and helper-script tree — the source of truth for
every workflow. It is edited freely as the workflows evolve; it is not copied from, or
compared with, any other directory. New instructions and new subcommands in the bundled
scripts (for example `review-followup approve`) are expected.

```bash
uv run aidw prompts list     # every prompt/script AIDT owns
uv run aidw prompts check    # required files present, no .pi/prompts references
```

`aidw prompts check` (and `aidw doctor`) fail when a required prompt/script is missing or a
file reaches outside `aidt/`, so a workflow cannot die at Pi-invocation time.

If `uv` is not on your `PATH`, invoke it by full path (e.g. `~/.local/bin/uv`).

To invoke without `uv` (dependencies must already be importable):

```bash
./aidt/aidw/aidw doctor
```

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
aidw run       task-to-pr <phase> <epic> <task> | review-and-fix --pr <n>
              [--dry-run] [--yes] [--strict] [--parallel] [--max-iterations N]
              [--gate-default approve|deny] [--deny-gates ...]
aidw tasks     [--todo] [--phase NN] [--epic X] [--next]
aidw agents    list | show <id> | validate
aidw runs      list | show <id> | resume <id>
aidw prompts   list | check
```

Global options: `--repo <path>`, `--verbose`, `--retry-transient/--no-retry-transient`,
`--progress/--no-progress`.

## Gates

| Gate | Workflow | What approval does |
|---|---|---|
| `approve-task-prompt` | prompt | Optional (off by default; enable with `--require-approval`). On approval, commits the reviewed task prompt on the task branch |
| `approve-implementation-pr` | implement | Allows `/pr` to commit, push, and open the PR |
| `approve-followups` | fix, approve-followups | Runs `/approve-review-followups` (applies GitHub decisions) |
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
- Per-agent `max_cost_usd` in `aidt/agent-configs/<agent>.yaml` fails a stage with
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
  Python scripts under `aidt/prompts/scripts/review-followup/`.
- `implement`/`fix` refuse to run on `main` or on a branch that is not the task/PR head.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `working tree is dirty; commit or stash first` | `prompt` needs a clean tree. Commit/stash, or use `--dry-run`. |
| `branch mismatch` | Check out the task/PR head branch. |
| `provider error: 402` / stage `failed` | Provider credits/limits. Top up or switch the agent's model; not transient, so it is not retried. |
| `verdict: ambiguous` / run `blocked` | The model did not end with a clear verdict. Inspect `stages/<stage>.out.txt`, re-run, or set a stronger reviewer model. |
| `prompts check` fails | A required prompt/script is missing, or a file references `.pi/prompts`. Fix the file or `aidt/aidw/inventory.py`. |
| `gh` errors in review/fix | `gh auth status`; the PR must be **OPEN** and target `main`. |
| `Unknown JSON field: "subIssues"` in a review/fix stage | A stale or shadowed `gh` is first on `PATH` (sub-issues need `gh` ≥ 2.94.0). `aidw doctor` fails this as `gh version`; upgrade `gh` and check `which -a gh`. |
| A stage is stuck/slow | Wall-clock timeout per agent (`timeout_seconds`); the process group is terminated and the partial log kept. |
| Need to continue after a failure | `aidw implement ... --resume` (or `--from <stage>`). `fix` has no resume in v1. |

## Layout

```text
aidt/
├── design.md          # the design document
├── pyproject.toml     # uv-managed project
├── aidw/              # the Python package + CLI
├── agent-configs/     # per-agent YAML (Phase 1)
├── agents/            # per-agent AGENTS.md / SYSTEM.md (Phase 1)
├── prompts/           # AIDT's own prompts and helper scripts
├── runs/              # per-run artifacts (gitignored; Phase 2)
└── tests/             # pytest unit tests
```

## Development

```bash
cd aidt
uv run pytest
uv run aidw doctor
```

AIDT tests are intentionally **not** wired into the product's `pnpm -r test` CI (design F5);
a non-blocking CI job for AIDT is a candidate follow-up (design §18). See `design.md` §15.
