# AI Developer Tools (AIDT) — Design

**Status:** Draft for review
**Scope:** `./aidt` only. AIDT is a developer-workflow toolkit that drives the Pi agent via the
command line to develop the Mythical Forge application. It is **not** part of the Mythical Forge
product, is not built or tested by the product's pnpm pipeline, and creates no AWS resources.
**Name:** AIDT = AI Developer Tools. AIDW = AI Developer Workflows (the wrapper scripts).
**Source of truth:** the process in `docs/workflow.md`; the prompts and helper scripts in
`.pi/prompts/` (bundled into `aidt/prompts/`, see §7).

---

## 1. Purpose and scope

AIDT turns the human-driven workflow in `docs/workflow.md` into scriptable, resumable,
agent-configurable commands. A developer selects a roadmap task, and a wrapper drives one or more
specialised Pi agents through a defined sequence of stages, pausing at human decision gates.

The workflow groups in scope for v1:

| Group | Command | Maps to `docs/workflow.md` |
|---|---|---|
| Task prompt generation + review | `aidw prompt` | Step 1 (`/task-prompt`) + `/task-review` gate |
| Implementation + PR | `aidw implement` | Steps 2–7 (`/impliment-task`, `/test`, `/update-traceability`, `/record-implementation-results`, `/update-architecture`, `/pr`) |
| Code review + issue creation | `aidw review` | Steps 9–10 (`/code-review`, `/review-findings-to-github`) |
| Review follow-up approval | `aidw approve-followups` | Step 11 (`/approve-review-followups`) without the fix loop |
| Issue fixing | `aidw fix` | Steps 11–13 (`/approve-review-followups`, `/fix-next-review-followup`, `/test`, `/code-review` re-review loop) |

### 1.1 Non-goals (v1)

- **Deployed integration tests** (`/integration-tests`, workflow Step 8). Requires a deployed dev
  stack and post-CI ordering. A stage stub exists in the state model but no workflow invokes it.
  The bundled prompt is not wired in.
- **Optional summary prompts** (`/show-updated-player-actions`, `/show-updated-integration-tests`).
- **Merging PRs.** AIDT never merges. Merge is the CI/CD pipeline's job (per `AGENTS.md` §9).
- **Parallel task execution / `git worktree`.** v1 is strictly one workflow run at a time on the
  current working tree. The state model is designed so worktrees can be added later.
- **Procedural authoring of roadmap tasks.** AIDT selects existing roadmap tasks; it does not invent
  them.
- **A web UI.** CLI only.

### 1.2 What AIDT must never do

- Never let an agent bypass a gate silently: every skipped gate is recorded in `state.json`.
- Never reimplement GitHub logic: all GitHub reads/writes go through the bundled Python
  scripts (`publish_review_followups.py`, `review_followup.py`) or the `gh` CLI, exactly as the
  existing prompts specify.
- Never merge a PR, force-push, `git reset --hard`, `git clean`, or discard unrelated user changes.
- Never commit secrets. Never write outside the repository except Pi's own session store.

---

## 2. Concepts and terminology

| Term | Meaning |
|---|---|
| **Workflow** | One of the four groups (`prompt`, `implement`, `review`, `fix`). |
| **Stage** | One Pi invocation with one prompt and one agent. The atomic unit of work. |
| **Agent** | A named configuration (`aidt/agent-configs/<id>.yaml`) bundling model, system prompt, context file, and tool allowlist. Agents are stateless; a session is their memory. |
| **Run** | One execution of a workflow. Identified by `run_id`
(`<utc-stamp>-<task-or-pr>-<workflow>`, so sibling runs of one task are distinguishable
in a directory listing), persisted under `aidt/runs/<run_id>/`. |
| **Gate** | A human decision point. Listed in §6. Every gate is skippable (`--yes`) and every decision or skip is logged. |
| **Artifact** | A file a stage produces or consumes for a cross-agent handoff (task-prompt path, findings manifest, PR number). |
| **Session** | A Pi session (JSONL). Authoring-adjacent stages of one agent in one run share a session; independent reviewers always get a fresh session. |
| **Author ≠ judge** | The workflow's model-independence rule (`docs/workflow.md` §2 Model routing). Enforced by config validation (§5.4). |

---

## 3. Directory layout

Everything the toolkit needs lives under `aidt/`, so the folder is self-contained and portable to
another repository.

```text
aidt/
├── design.md                     # this document
├── README.md                     # operator quickstart
├── pyproject.toml                # uv-managed; deps: pyyaml, typer; optional: rich
├── uv.lock
├── .env.local                    # optional local overrides (gitignored)
├── aidw/
│   ├── aidw                      # executable entry point (thin shim -> cli:main)
│   ├── __init__.py
│   ├── cli.py                    # Typer app; subcommand dispatch
│   ├── doctor.py                 # `aidw doctor` environment checks
│   ├── paths.py                  # repo-root discovery, AIDT paths
│   ├── config.py                 # agent-config loading + validation
│   ├── agents.py                 # agent -> Pi argv rendering
│   ├── pi.py                     # Pi subprocess invocation, JSONL capture, result parsing
│   ├── runner.py                 # stage primitive (render → run → record)
│   ├── prompts.py                # prompt rendering ($1..$n, frontmatter strip)
│   ├── state.py                  # run state read/write, resume, stage bookkeeping
│   ├── git.py                    # git safety checks, branch/PR helpers
│   ├── github.py                 # thin wrappers around bundled Python scripts + gh reads
│   ├── gates.py                  # human-in-the-loop prompts, skip recording
│   ├── roadmap.py                # docs/tasks/*.md checkbox parsing
│   ├── verdict.py                # deterministic Approve/Request changes/Blocked parsing
│   ├── inventory.py              # prompt/script inventory check
│   ├── log.py                    # run logging (JSONL + human transcript)
│   └── workflows/
│       ├── prompt.py
│       ├── implement.py
│       ├── review.py
│       └── fix.py
├── agent-configs/
│   ├── task-author.yaml
│   ├── task-reviewer.yaml
│   ├── task-fixer.yaml
│   ├── implementer.yaml
│   ├── tester.yaml
│   ├── recorder.yaml
│   ├── pr-publisher.yaml
│   ├── code-reviewer.yaml
│   ├── review-publisher.yaml
│   ├── review-approver.yaml
│   └── fixer.yaml
├── agents/
│   └── <agent-id>/
│       ├── AGENTS.md             # per-agent context file (inlined via --append-system-prompt)
│       └── SYSTEM.md             # optional system-prompt override/append file
├── prompts/                      # AIDT's own prompts and helper scripts (see §7)
│   ├── task-prompt.md
│   ├── task-review.md
│   ├── task-review-fixes.md
│   ├── impliment-task.md
│   ├── test.md
│   ├── update-traceability.md
│   ├── record-implementation-results.md
│   ├── update-architecture.md
│   ├── pr.md
│   ├── code-review.md
│   ├── review-findings-to-github.md
│   ├── approve-review-followups.md
│   ├── fix-next-review-followup.md
│   └── scripts/review-followup/  # bundled Python helper scripts
├── runs/                         # gitignored; one dir per run
└── tests/                        # pytest; not part of product CI
```

`.gitignore` additions (repository root):

```
aidt/runs/
aidt/.env.local
aidt/**/__pycache__/
aidt/.venv/
aidt/.pytest_cache/
```

---

## 4. Architecture

```
        ┌──────────────────────────── aidw CLI (Typer) ────────────────────────────┐
        │  prompt | implement | review | fix | tasks | agents | runs | doctor      │
        └───────────────┬──────────────────────────────────────────────────────────┘
                        │
             ┌──────────▼──────────┐
             │  Workflow modules   │  prompt.py / implement.py / review.py / fix.py
             └──┬──────┬───────┬───┘
                │      │       │
     ┌──────────▼─┐ ┌──▼─────┐ ┌▼──────────┐
     │   state.py │ │gates.py│ │inventory.py│
     │ run/state  │ │ HITL   │ │ drift     │
     └────────────┘ └────────┘ └───────────┘
                │
     ┌──────────▼─────────┐
     │  config.py/agents  │  load + validate agent YAML, render Pi argv
     └──────────┬─────────┘
                │
     ┌──────────▼─────────┐    ┌──────────────┐   ┌──────────────────────────┐
     │       pi.py        │───▶│  pi (subprocess, --mode json)              │
     │  invoke/capture    │    └──────────────┘   └──────────────────────────┘
     └──────────┬─────────┘
                │  prompts.py renders prompt + variables
                │
     ┌──────────▼─────────┐   ┌──────────────────────────────────────────────┐
     │ github.py / git.py │──▶│ bundled Python review-followup scripts + `gh`   │
     └────────────────────┘   └──────────────────────────────────────────────┘
```

**Data flow of one stage**

1. Workflow module resolves stage → agent + prompt + variables from config.
2. `prompts.py` loads the prompt, strips YAML frontmatter, substitutes `$1..$n`, and
   returns the message body.
3. `config.py`/`agents.py` build the Pi argv (`--provider`, `--model`, `--thinking`, `--tools`,
   system-prompt flags, `--session-id` when sharing).
4. `pi.py` runs Pi non-interactively with that message on stdin, tees stdout to
   `runs/<id>/stages/<stage>.jsonl`, and captures the final assistant message.
5. The workflow parses the result (verdict, artifact paths) and writes stage + gate records to
   `state.json`.
6. Cross-agent handoffs are written as files under `runs/<id>/artifacts/` and passed as variables to
   the next stage.

---

## 5. Agent configuration

### 5.1 Schema

One YAML file per agent under `aidt/agent-configs/`. Validated on load by `config.py` (PyYAML +
explicit checks; no pydantic).

```yaml
# aidt/agent-configs/implementer.yaml
id: implementer                       # required, unique, must match filename stem
description: Implements a task prompt as code plus module contract/property tests.

provider: openrouter                  # required; passed to pi --provider
model: <provider/model-slug>          # required; passed to pi --model
thinking: medium                      # off|minimal|low|medium|high|xhigh|max

system_prompt:                        # optional
  mode: append                        # append | override | none   (default: append)
  file: agents/implementer/SYSTEM.md  # required when mode != none

agents_md: agents/implementer/AGENTS.md  # optional per-agent context file

tools:                                # allowlist; deny-by-default
  - read
  - bash
  - write
  - edit

skills: []                            # -> repeated --skill <path>
extensions: []                        # -> repeated --extension <path>
prompt_templates:                     # -> repeated --prompt-template <path>
  - prompts
mcp_config: ../.mcp.json              # optional -> --mcp-config <path> (relative to repo root)
cwd: .                                # relative to repo root; default repo root
env: {}                               # extra environment variables for the subprocess
session: shared                       # fresh | shared  (see §5.3)
timeout_seconds: 3600                 # required
max_cost_usd: null                    # optional ceiling; run aborts when exceeded (best-effort)
output: json                          # json | text  (default json)
```

### 5.2 Tool allowlist semantics (deny-by-default)

- `tools` is the **only** tool field. There is no deny list.
- Passed to Pi as `--tools <comma-separated>`.
- An empty or omitted `tools` list means the agent gets **no** built-in, extension, or custom tools:
  the wrapper passes `--no-tools`.
- A reviewer that must not mutate the tree simply omits `write`/`edit`; that is the enforcement
  mechanism, not a prompt instruction.
- MCP tools count as tools. An agent needing AWS MCP tools must list them explicitly in `tools`
  **and** set `mcp_config`; because `--tools` is a strict allowlist over built-in, extension and
  MCP tools, setting `mcp_config` alone exposes nothing. No baseline agent enables MCP in v1.
- Adding an MCP/extension tool name produces a validation **warning** (it is not a known
  built-in), not an error.

Baseline agent tool sets:

| Agent | tools | Rationale |
|---|---|---|
| `task-author` | read, bash, write, edit | writes the task prompt |
| `task-reviewer` | read, bash | read-only review |
| `task-fixer` | read, bash, write, edit | revises a task prompt from review findings |
| `implementer` | read, bash, write, edit | code + contract tests + traceability + architecture docs |
| `tester` | read, bash, write, edit | writes missing tests |
| `recorder` | read, bash, write | runs the gate and writes `build-results.md` |
| `pr-publisher` | read, bash, write, edit | commits/pushes/opens PR; `edit` for any doc fixups |
| `code-reviewer` | read, bash | read-only |
| `review-publisher` | bash | delegates to the bundled Python script |
| `review-approver` | bash | delegates to the bundled Python script |
| `fixer` | read, bash, write, edit | implements one approved finding |

### 5.3 Session policy

- `session: fresh` (default for reviewers, recorder, PR publisher, publisher/approver): every stage
  invocation gets a new Pi session id (`--session-id aidw-<run_id>-<agent>-<stage>`), giving a clean
  context. Pi prints a benign ``No project session found with id ...; creating a new session``
  warning when a session id is new; AIDW treats it as expected, not an error.
- `session: shared` (default for `implementer`): all stages assigned to that agent in one run reuse
  a single session id (`--session-id aidw-<run_id>-<agent>`), so `/impliment-task`,
  `/update-traceability`, and `/update-architecture` share naming/format context — required by
  `docs/workflow.md` ("needs `/test`'s test names", "keeps design decisions consistent").
- Reviewer independence is a **model** property, not a session property; a fresh session alone is
  never sufficient (see §5.4).

### 5.5 System prompt and context files (Phase 1 findings)

- Pi's `--append-system-prompt` and `--system-prompt` accept literal text (verified against Pi
  0.85.x). AIDW reads `agents_md` / `system_prompt.file` and passes their **contents**, so behaviour
  does not depend on Pi's path-vs-literal detection. Multi-line literal text is supported.
- `agents_md` is always appended (`--append-system-prompt`), in every `system_prompt.mode`.
- `system_prompt.mode: override` replaces Pi's default prompt via `--system-prompt`; `append` adds
  to it; `none` (or an omitted `system_prompt`) adds nothing.
- Repository context files remain enabled by default, so the project `AGENTS.md` still loads at
  `cwd` = repo root. Set `no_context_files: true` on an agent to disable discovery.

### 5.4 Model routing and validation

The workflow's role table (`docs/workflow.md` §2) maps onto agent configs:

| Stage | Agent | Role |
|---|---|---|
| `/task-prompt` | `task-author` | authoring |
| `/task-review` | `task-reviewer` | **reviewer ≠ `task-author` model** |
| `/task-review-fixes` | `task-fixer` | authoring; **re-review ≠ `task-fixer` model** |
| `/impliment-task` | `implementer` | authoring |
| `/test` | `tester` | **reviewer A ≠ `implementer` model** |
| `/update-traceability` | `implementer` | authoring (shared session) |
| `/update-architecture` | `implementer` | authoring (shared session) |
| `/record-implementation-results` | `recorder` | cheap/mechanical |
| `/pr` | `pr-publisher` | cheap/mechanical |
| `/code-review` | `code-reviewer` | **reviewer ≠ `implementer` model** |
| `/review-findings-to-github` | `review-publisher` | cheap/mechanical |
| `/approve-review-followups` | `review-approver` | cheap/mechanical |
| `/fix-next-review-followup` | `fixer` | authoring |
| re-review `/test` + `/code-review` | `tester`, `code-reviewer` | reviewers (rotate models when a second reviewer exists) |

`config.py` validation rules:

1. `id` matches filename; all referenced files exist relative to `aidt/`.
2. Required fields present; `thinking`, `session`, `output` in range.
3. **Independence check:** `task-reviewer.model != task-author.model`,
   `task-reviewer.model != task-fixer.model`, `tester.model != implementer.model`,
   `code-reviewer.model != implementer.model`, and (when possible)
   `tester.model != code-reviewer.model` to diversify reviewers.
   Default: emit a **warning**. With `aidw ... --strict`, fail.
4. Reviewer agents (`task-reviewer`, `code-reviewer`) must not have `write` or `edit` in `tools`;
   warn, or fail with `--strict`.
5. Every workflow's required agent ids resolve.

Independence is checked at the workflow level too: before running `/code-review` on a fix branch,
AIDT refuses to reuse an agent whose model equals the model that authored the diff, with an explicit
`--force-model` escape hatch that is recorded in state.

---

## 6. Human-in-the-loop gates

Every gate is skippable. `--yes` approves all gates in a run; `--skip-gates <name,...>` skips
specific gates; `--deny-gates <name,...>` refuses specific gates and is checked before both, so
an explicit refusal cannot be overridden by a blunter approval. Every decision and skip is
written to `state.json` with timestamp and mechanism (`human`, `human-default`, `human-denied`,
`--yes`, `--skip-gates`, `--deny-gates`, `noninteractive`).

**The interactive default is approve**: Enter at a prompt approves, and the marker reads `[Y/n]`.
`--gate-default deny` (or `AIDW_GATE_DEFAULT=deny`) restores the strict `[y/N]` prompt; the CLI
flag wins over the environment variable. `human` means the human typed `y`, `human-default` means
Enter accepted an approve default — the distinction is kept so an audit can tell consent from
convenience.

| Gate | Workflow | Default behaviour | Skip flag |
|---|---|---|---|
| `approve-task-prompt` | `prompt` | Optional. After `/task-review` returns `Approve`, show the verdict + prompt path and ask to proceed. Not required by default; enable with `--require-approval`. If `Request changes`, run the bounded revision loop first (§8.1). | `--require-approval`, `--yes`, `--skip-gates approve-task-prompt` |
| `approve-implementation-pr` | `implement` | After `/record-implementation-results`, show gate results and ask before `/pr` commits, pushes, and opens the PR. | `--yes`, `--skip-gates approve-implementation-pr` |
| `confirm-review-publish` | `review` | **Not used by default** (see below). | n/a |
| `approve-followups` | `fix`, `approve-followups` | At entry, list the PR's open child issues with their GitHub state and ask which to approve; runs `/approve-review-followups`. | `--yes`, `--skip-gates approve-followups` |
| `approve-fix-pr` | `fix` | After each fix + re-review, before the fix is considered done (i.e. before closing the loop and moving to the next issue). | `--yes`, `--skip-gates approve-fix-pr` |

**Review publishing is deliberately ungated (decision E2).** `aidw review` runs `/code-review`
and, when findings exist, immediately runs `/review-findings-to-github` to create the parent +
child issues **without** a human confirmation prompt inside the run. Human review happens **on
GitHub** between `aidw review` and `aidw fix`. To make this safe:

- `review-publisher` runs with `--tools bash` only; all writes go through
  `publish_review_followups.py`, which is idempotent and validates the manifest.
- `aidw review --dry-run` renders the manifest, prints exactly what would be created, and performs
  no writes.
- Children are created `decision-pending`; no code is written until `aidw fix` approves them.

Gate UI: `gates.py` prints a compact summary to the TTY and reads a line from stdin. In
non-interactive/CI contexts (`--yes`, `AIDW_NONINTERACTIVE=1`, or no TTY), unapproved gates fail
closed with a clear message unless an explicit flag approves them. The approve default is
**not** an auto-approval: it only decides what Enter means for a human at a terminal, so a
scripted run still needs `--yes` or `--skip-gates`.

---

## 7. Prompts and helper scripts

### 7.1 Rationale

`./aidt` must be self-contained (decision D1): an operator can copy `aidt/` into another checkout
and it works without `./.pi`.

`aidt/prompts/` is **AIDT's own** prompt and helper-script tree. It began as a copy of
`.pi/prompts/`, but it is now independent (decision D3): it is the source of truth for the
workflows and is edited freely as they evolve. AIDT never compares against, or syncs from,
`.pi/prompts/`; that tree is an upstream reference only and may be retired.

### 7.2 Prompt policy

- `aidt/prompts/` holds every prompt and every helper script the workflows invoke, including the
  review-followup Python tools. Nothing under `aidt/` references `.pi/`.
- The helper scripts are standard-library-only Python (3.9+), so the agent can run them by path
  (`python3 …/review_followup.py`) with no install step, and AIDW can invoke the same entry points
  with its own interpreter (`sys.executable`). AIDT requires no Node toolchain.
- Prompts and scripts are edited in place. Improvements are expected — new instructions, and new
  subcommands in the helper scripts (for example `review-followup approve`) — and do not need to
  be reflected upstream.
- `aidw prompts check` (and `aidw doctor`) verifies the inventory: every required prompt/script is
  present and no file references `.pi/prompts`. `aidw prompts list` prints the inventory.
- Prompt/script compatibility is a contract. The exact strings the review-followup scripts rely on
  — the labels (`review-follow-up`, `approve-fix`, `decision-pending`, the priority labels), the
  exact comments (`Status: in progress`, `Status: fixed`, `Decision: approve-fix`), and the
  `<!-- mythical-forge-review-followups: pr=... -->` markers — are declared in `constants.py` and
  must be changed together with the prompts that document them.

### 7.3 Prompt rendering (decision D2)

`prompts.py`:

1. Reads the prompt file (UTF-8).
2. Strips a leading YAML frontmatter block (`---` … `---`) — it is Pi template metadata, not message
   content.
3. Replaces positional tokens `$1`…`$n` with the stage's variables. Only `$` followed by digits is
   substituted, so shell references such as `$runner` and `$pr` inside prompts are untouched.
4. Returns the rendered text, which `pi.py` passes as the final message on stdin to `pi -p`.

The wrapper does **not** rely on Pi's `/` prompt-template expansion: CLI invocation would not expand
it, and rendering in Python keeps the transform testable.

### 7.4 External dependencies

- The Archify skill referenced by `/update-architecture` lives at
  `/Users/phil/.pi/agent/skills/archify/` (machine-local). `aidw doctor` checks for it and reports a
  warning if absent; `implement` only needs it when a diagram changes.
- `.mcp.json` (AWS MCP server) is passed via `--mcp-config` for agents that list MCP tools.
- `gh` authentication and the AWS profile come from the environment (see §12).

---

## 8. Workflow specifications

Notation: `→` runs a stage, `◇` is a gate, `⟳` is a bounded loop, `∥` is a parallel pair (v1 runs
these serially by default; the design allows `--parallel`).

### 8.1 `aidw prompt <phase> <epic> <task>`

```
preflight (clean tree, on main)
  → P1 task-prompt        (agent task-author)      writes docs/task-prompts/<id>-prompt.md, commits it
  → P2 task-review-1..N   (agent task-reviewer)    read-only verdict
  ⟳  if Request changes: P2a task-prompt-fixes (agent task-fixer; one stage per finding)
                          then P2 again (skip the last P2)         (max 3 rounds)
  ◇  approve-task-prompt        (optional; off unless --require-approval)
```

- `P1` receives `$1=phase`, `$2=epic`, `$3=task`. The prompt itself creates the `{phase}-{task}`
  branch and commits the prompt.
- `P2` receives `$1=<task-prompt-file>`.
- `P2a` uses the short `aidt/prompts/task-review-fixes.md`; it receives `$1=<task-prompt-file>`
  and, per finding, that finding re-rendered in the reviewer's own block format. AIDW runs one fix
  stage per **blocking** (`must-fix`/`should-fix`) finding so progress is reported per change, and
  batches every non-blocking `could-fix` finding into a single stage so those cost one invocation
  instead of one each. When the review does not parse into findings — or any block is malformed — it
  falls back to a single stage carrying the whole review text.
- At most `MAX_REVISIONS` (3) rounds run. The **last** round's fixes are not followed by another
  review: the reviewer has had its chances, so the prompt is accepted as ready and the gate summary
  says so (`no further review — accepted`). A final `Blocked` verdict is the exception — it means a
  human must settle a material ambiguity, so the run still fails closed with the residual findings.
- Output artifacts: `task_prompt_path`, `branch`, `task_review_verdict`, `task_review_findings`.

### 8.2 `aidw implement <task-prompt-path> [--pr <n>]`

```
preflight (branch matches task id, task prompt exists, no other run active)
  → I1 impliment-task                 (agent implementer, session shared)
  → I2 test                           (agent tester, fresh)
  → I3 update-traceability            (agent implementer, shared)  [after I2: cites its tests]
  → I4 update-architecture            (agent implementer, shared)
  → I5 record-implementation-results  (agent recorder, fresh)      SYNC POINT
  ◇  approve-implementation-pr
  → I6 pr                             (agent pr-publisher, fresh)
```

- Ordering follows `docs/workflow.md`: `/test` before `/update-traceability` (traceability cites the
  test names `/test` may add); `/update-architecture` after implementation and before the
  `record-implementation-results` sync point.
- `I2` and `I4` touch disjoint file sets (package tests vs `docs/architecture/**`). With
  `--parallel`, AIDT runs them concurrently in the same working tree (v1 has no worktrees);
  run-state writes are serialized by a lock. Without `--parallel`, every stage runs serially.
- `I5` is the mandatory sync point over the fully merged tree; `I6` must see the same tree.
- `I6` commits the accumulated uncommitted change set, pushes, and opens the PR. AIDT does not
  commit before this stage.
- Output artifacts: `pr_number`, `pr_url`, `build_results_path`, `changed_files` summary.

### 8.3 `aidw review --pr <n>`

```
preflight (PR exists, targets main, current branch is the PR head)
  → R1 code-review                    (agent code-reviewer, fresh, read-only)
  if findings:
    → R2 review-findings-to-github    (agent review-publisher, fresh, no gate)   creates parent + children
  else: report Approved and stop
```

- `R1` renders `.pi/prompts/code-review.md` (no variables) and parses the verdict
  (`Approve` / `Request changes` / `Blocked`) and the findings block from the final message.
- If `Blocked`, the workflow stops and reports — it does not publish.
- `R1` findings are extracted into `runs/<id>/artifacts/findings.json` (stable `F1..Fn`, priority,
  confidence, evidence, impact, trigger/effect, location, suggested fix). This is the wrapper-side
  equivalent of "findings from the immediately preceding review in this pi session" (decision B2),
  so `R2` does not depend on session memory.
- `R2` receives `$1=<pr>`; it invokes the bundled `publish_review_followups.py` with the manifest.
- Output artifacts: `review_verdict`, `findings` (or none), `parent_issue`, `child_issues`.

### 8.4 `aidw fix --pr <n>`

```
preflight (PR exists, branch exists, no other run active)
  → list open children; show GitHub state
  ◇  approve-followups                 runs /approve-review-followups (agent review-approver)
  ⟳  per available approved child issue (serial, one at a time):
       → F1 fix-next-review-followup  (agent fixer, fresh)
       → F2 test                      (agent tester, fresh — rotate reviewer model)
       → F3 code-review               (agent code-reviewer, fresh — rotate reviewer model)
       if F3 has findings:
         → F4 review-findings-to-github (creates new children; ungated)
         ◇  approve-followups (show new children; human approves on GitHub)
       else:
         ◇  approve-fix-pr
     repeat until no open approved children remain
```

- Entry gate: the human has already reviewed the published issues **on GitHub**. `approve-followups`
  is the only place AIDT writes `approve-fix`/removes `decision-pending`.
- One fix per iteration; `F1` processes exactly one issue and the loop re-derives "available" via
  `review_followup.py select`, never by counting.
- Re-review uses the **fresh reviewer model** rule; if only one reviewer model is configured, AIDT
  warns and (under `--strict`) refuses.
- Bounded: `--max-iterations` (default 10) prevents an unbounded review→fix→review loop.
- Output artifacts: `closed_issues`, `latest_verdict`, `iterations`.

### 8.5 `aidw approve-followups --pr <n>`

```
preflight (PR exists)
  ◇  approve-followups                 show the open children; human confirms
  →  approve-review-followups          (agent review-approver, fresh)
```

- Extracts the approval step that `aidw fix` performs at its entry, so a human can apply the
  GitHub decision without starting the fix loop.
- The prompt (`aidt/prompts/approve-review-followups.md`) receives `$1=<pr>` and performs every
  write through the bundled `review_followup.py` script (adds `approve-fix`, removes
  `decision-pending` on open children; closed children are untouched).
- Preflight only checks that `gh` is available and the PR exists; it does not require a
  particular branch or PR base.
- Output artifacts: the run's `pr` record and the `approve-followups` gate decision.

### 8.6 `aidw run <workflow>` (orchestrator)

`aidw prompt`, `aidw implement`, `aidw review`, and `aidw fix` are themselves the orchestrators. A
convenience chain `aidw run task-to-pr <phase> <epic> <task>` runs `prompt` then `implement`, and
`aidw run review-and-fix --pr <n>` runs `review` then `fix`, failing forward per §10.

---

## 9. Run state, artifacts, and resumability

### 9.1 Layout

```text
aidt/runs/<utc-stamp>-<task-or-pr>-<workflow>/
├── state.json
├── run.log
├── stages/
│   ├── impliment-task.jsonl      # raw pi --mode json stream
│   ├── impliment-task.out.txt    # final assistant message (human-readable)
│   └── impliment-task.meta.json  # argv, model, prompt source, session id, duration, exit, usage
├── artifacts/
│   ├── task-prompt.path
│   ├── findings.json
│   └── review-manifest.json
└── prompts/
    └── impliment-task.rendered.md
```

### 9.2 `state.json` (schema)

```json
{
  "schema_version": 1,
  "totals": { "input_tokens": 193, "output_tokens": 16, "cost_usd": 1.23 },
  "run_id": "20250930T191500Z-03-E2.9-implement",
  "workflow": "implement",
  "created_at": "2025-09-30T19:15:00Z",
  "repo_root": "/Users/phil/mythical-forge",
  "git": { "branch": "03-E2.9", "base": "main" },
  "task": {
    "phase": "03", "epic": "E2", "task": "E2.9",
    "prompt_path": "docs/task-prompts/03-E2.9-prompt.md"
  },
  "pr": { "number": 42, "url": "https://github.com/..." },
  "strict": false,
  "stages": [
    {
      "name": "impliment-task",
      "agent": "implementer",
      "model": "<provider/model>",
      "session_id": "aidw-20250930T191500Z-03-E2.9-implement-implementer",
      "status": "succeeded",
      "started_at": "...", "ended_at": "...",
      "exit_code": 0,
      "duration_seconds": 812.4,
      "cost_usd": 1.23,
      "usage": { "input_tokens": 193, "output_tokens": 16, "cache_read": 50432,
                 "cache_write": 0, "reasoning": 0, "total_tokens": 50641, "cost_usd": 1.23 },
      "log": "stages/impliment-task.jsonl",
      "rendered_prompt": "prompts/impliment-task.rendered.md",
      "artifacts": {}
    }
  ],
  "gates": [
    { "name": "approve-implementation-pr", "decision": "approved",
      "mechanism": "human", "at": "..." }
  ],
  "status": "succeeded",
  "resume": { "next_stage": null }
}
```

`totals` is derived on every save: it sums the `usage` counters of all recorded stages (with a
stage's `cost_usd` as the fallback when a record has no `usage`), giving the run's combined
input tokens, output tokens, and cost.

`stages/<name>.meta.json` carries the same counters plus the prompt provenance — `stage`, `agent`,
`prompt_source` (the prompt file the stage was rendered from: an `aidt/prompts/*.md` file, or an
absolute path when `aidw exec` was given one) and `rendered_prompt` — so "which prompt did this
stage actually use?" is answerable from the stage's own metadata.

### 9.3 Stage reporting

Every stage prints a block to stdout when it finishes, derived from the stage record so the live
output and the recorded evidence cannot drift apart:

```text
stage:  task-review-1 [succeeded] model=openrouter/meta/muse-spark-1.3 132.3s cost=$0.0287
        usage: total=50.6k in=193 out=16 cache_read=50.4k cache_write=0 reasoning=0 cost=$0.0287
        out:   aidt/runs/<run-id>/stages/task-review-1.out.txt
```

A workflow prefixes its own stage id (`stage:  I2 test [succeeded] …`), a failed stage reports
`error:` instead of usage, and `aidw runs show` prints the same fields from `state.json`. Review
stages always point at their `.out.txt`, so the verdict text is one path away. A task-prompt review
that requests changes reports the parsed finding count and a per-finding fix line, for example
`verdict: Request changes — 3 findings (2 should-fix, 1 could-fix)` followed by `fix 1.1/3: …` for
each blocking finding and one `fix 1.3/3: 2 could-fix findings combined` stage for the rest.

**While a stage runs**, an interactive terminal shows a live progress line on stderr, fed by the JSON
events Pi streams (never by the transcript, which stays on stdout):

```text
▶ task-review-1 (task-reviewer) model=openrouter/meta/muse-spark-1.3
  ..*+.+.+.**
```

`.` is a heartbeat — nothing new for 10s, Pi is still working; `*` is a completed model response;
`+` is a tool call. A dot per response alone would still leave multi-minute silences on the long
review stages, which is why the heartbeat exists. Progress is enabled only when stderr is a
terminal, so CI logs and piped runs stay clean; `--progress` / `--no-progress` overrides that. Under
`--parallel` the two concurrent stages' lines interleave.

`status` ∈ `running | succeeded | failed | blocked | aborted`. `resume.next_stage` is set when a
stage fails, so `--resume` continues from that stage.

### 9.3 Resumability

- `aidw implement --resume` reads the latest run for the branch, prints completed stages, and asks
  before continuing (skippable with `--yes`).
- Completed stages are never re-run implicitly. `--from <stage>` forces a stage (and everything
  after it) to run again, recording the override.
- Gates already approved are not re-asked; a gate can be re-decided with `--gate <name> --yes|--no`.

---

## 10. Error handling

| Condition | Behaviour |
|---|---|
| Pi process exits non-zero | Stage `failed`; state records exit code + tail of stderr; workflow stops (no auto-retry unless `--retry-transient`). |
| Pi exits 0 but reports an in-stream provider error (`stopReason: "error"` or `errorMessage`, e.g. an OpenRouter 402) | Stage `failed` with the provider message; workflow stops. Credit/auth errors are not transient and are not retried. (Found by Phase 3 live validation.) |
| A review stage returns no final message | Stage `failed`; the workflow stops rather than treating it as "ambiguous" and running rework on empty findings. |
| Pi invocation error that looks transient (network/provider 5xx) | With `--retry-transient` (default on for one attempt), retry once after a short backoff; record both attempts. Gate failures are never retried. |
| Stage timeout | `failed`; process group terminated; partial log retained. |
| Cost ceiling exceeded | `failed` with reason `cost_ceiling`; run stops. |
| Gate denied | `blocked`; run stops cleanly, leaving state resumable. |
| `/code-review` returns `Blocked` | `blocked`; findings are still written, publication is not attempted. |
| `review_followup.py` exit 3 (no available child) | Fix loop ends successfully with `closed_issues`. |
| `review_followup.py` exit 1/2/4 | `failed`; wrapper surfaces the script's JSON error and does not work around it. |
| A required prompt or helper script is missing (`aidw prompts check`) | `prompts check` fails; a workflow stage raises `FileNotFoundError` when its prompt file is absent. |
| Dirty working tree outside an active run | preflight refuses. |
| On `main` for `implement`/`fix` | preflight refuses. |

---

## 11. Roadmap task selection

`roadmap.py` parses `docs/tasks/<NN> - <Name>.md`:

- Headings `# Phase NN:`, `## Epic X:`, and checkbox items `- [x]` / `- [ ]` with
  `**<ID>. <Title>**` and an indented `- Done when:` line.
- Produces `{phase, epic, task, title, done, done_when, spec_citations}`.

Commands:

- `aidw tasks` — list all tasks with `phase/epic/id/status`.
- `aidw tasks --todo` — only unchecked.
- `aidw tasks --phase 03 [--epic E2]` — filter.
- `aidw tasks --show 03 E2 E2.9` — detail including `Done when` and cited specs.
- `aidw tasks --next [--phase 03]` — first unchecked task (dependency-graph awareness is deferred;
  v1 documents that prerequisite ordering is the operator's responsibility, per `docs/workflow.md`
  Step 0 item 3).

`aidw prompt` accepts either explicit `<phase> <epic> <task>` or `--task <id>` resolved from the
roadmap.

---

## 12. Configuration, environment, and secrets

- Non-secret toolkit config lives in `aidt/agent-configs/` and optionally `aidt/aidt.toml`
  (defaults: repo root discovery, run retention, default models per role).
- Secrets/credentials are **never** stored in `aidt/`: Pi provider credentials come from Pi's own
  auth store or environment (`pi auth`), GitHub from `gh auth`, AWS from `AWS_PROFILE` in
  `.mcp.json`'s env.
- Optional `aidt/.env.local` (gitignored) is sourced before invoking Pi, for local overrides such as
  `AIDW_DEFAULT_MODEL`. It is never read into `state.json` and never committed.
- `aidw doctor` validates: python deps, `pi` on PATH + version, `gh` auth status, git repo + clean
  tree, the prompt/script inventory, agent-config validity, Archify presence, and `.mcp.json`.
- `aidw doctor` also **fails** when `gh` predates sub-issue support (`>= 2.94.0`). The bundled
  review-followup scripts read the native `subIssues`/`parent` fields and create children with
  `--parent`, so an older or shadowed `gh` first on `PATH` otherwise fails inside an agent stage
  with `Unknown JSON field: "subIssues"`. The check probes `gh`'s own `--help` output for the
  capability as well as comparing versions, and names the resolved binary so a shadowing copy is
  obvious. This is a `FAIL` (not a `WARN` as with `gh` absent/unauthenticated) because the
  review and fix workflows cannot run at all.
- Model identifiers use Pi's `provider/model` form (`--provider` + `--model`). Exact slugs are
  operator configuration, not hard-coded in workflow logic.

---

## 13. Git and GitHub safety

`git.py` enforces:

- `implement` and `fix` must run on the task branch, never `main`.
- Preflight refuses when the working tree is dirty **unless** a run for the current branch is being
  resumed.
- AIDT never runs `git reset --hard`, `git clean`, `git checkout -- .`, force-push, or merge.
- AIDT preserves unrelated user changes and never broadens `git add` beyond the run's owned paths;
  `/pr`'s documented `git add -A` is executed by the `pr-publisher` agent, not by Python.
- `github.py` only:
  - reads PR/issue state via `gh` (read-only, structured JSON),
  - invokes the bundled `publish_review_followups.py` and `review_followup.py` for writes,
    including the `approve` subcommand that the approval prompt uses.
  It never calls `gh issue create`, `gh pr comment`, or `gh api` with a mutating method directly.

---

## 14. CLI reference

```text
aidw --help
aidw doctor

# workflows
aidw prompt    <phase> <epic> <task> [--require-approval] [--yes] [--skip-gates ...]
              [--deny-gates ...] [--gate-default approve|deny] [--strict] [--dry-run]
aidw implement <task-prompt-path> [--pr <n>] [--resume] [--from <stage>] [--parallel]
              [--yes] [--skip-gates ...] [--deny-gates ...] [--gate-default approve|deny]
              [--strict] [--dry-run]
aidw review    --pr <n> [--yes] [--strict] [--dry-run] [--force-model]
aidw fix       --pr <n> [--max-iterations N] [--yes] [--skip-gates ...] [--deny-gates ...]
              [--gate-default approve|deny] [--strict]
              [--dry-run] [--force-model]
aidw approve-followups --pr <n> [--yes] [--skip-gates ...] [--deny-gates ...]
              [--gate-default approve|deny] [--strict] [--dry-run]
aidw run       task-to-pr <phase> <epic> <task> | review-and-fix --pr <n>

# inspection
aidw tasks     [--todo] [--phase NN] [--epic X] [--show "03 E2 E2.9"] [--next]
aidw agents    list | show <id> | validate
aidw runs      list | show <run-id> | resume <run-id>
aidw prompts list | check

# global
--repo <path>   override repo root
--verbose       stream the Pi transcript to the TTY
--retry-transient / --no-retry-transient   retry once on a transient Pi invocation error (default on)
--progress / --no-progress                 show '.' progress while Pi works
                                           (default: on when stderr is an interactive terminal)
```

Exit codes: `0` success/approved, `1` stage or gate failure, `2` usage/config error,
`3` workflow blocked (needs human), `4` preflight/safety refusal.

---

## 15. Testing strategy for AIDT

- `pytest` under `aidt/tests/`, run via `uv run pytest`. **Not** wired into the product's
  `pnpm -r test` CI (decision F5); optionally a separate non-blocking CI job later.
- Unit coverage:
  - `prompts.py`: frontmatter stripping, `$n` substitution, no-op on `$runner`/`$pr`, missing-arg
    errors.
  - `config.py`: schema validation, allowlist rendering, independence warnings, strict failures.
  - `agents.py`: exact argv construction for every flag combination (golden tests).
  - `state.py`: write/read round-trip, resume selection, schema-version guard.
  - `roadmap.py`: checkbox parsing against fixture markdown.
  - `inventory.py`: required prompts/scripts present; no `.pi/prompts` references.
  - `github.py`: argument construction for the TS scripts (script execution mocked).
- A `--dry-run` for every workflow that performs no writes and prints the planned argv/actions is
  the primary integration seam; tests assert the dry-run plan.
- No test invokes a real Pi model.

---

## 16. Build plan (phased)

| Phase | Deliverable | Done when |
|---|---|---|
| **0. Scaffold** | `pyproject.toml`, `uv.lock`, `aidw` shim, `cli.py` skeleton, `.gitignore`, `README.md`, `doctor`. | `uv run aidw doctor` reports environment status. |
| **1. Config + prompts** | `config.py`, `agents.py`, `prompts.py`, `inventory.py`, all eleven agent configs + per-agent `AGENTS.md`, AIDT's own `aidt/prompts/`. | `aidw agents validate` passes; `aidw prompts check` passes; argv golden tests pass. |
| **2. Pi invocation + state** | `pi.py`, `state.py`, `log.py`, `gates.py`, run dir layout. | A `--dry-run` stage writes `state.json` + rendered prompt; a live no-op agent run captures JSONL and parses the final message. |
| **3. `aidw prompt`** | `workflows/prompt.py`, `roadmap.py`, `tasks`. | Running `aidw prompt 03 E2 E2.9 --dry-run` shows P1/P2 and resolves the roadmap entry; a real run produces a task prompt on the branch and a verdict. |
| **4. `aidw implement`** | `workflows/implement.py`, `git.py`. | Dry-run shows I1–I6 with agents/prompts; live run resumes after a simulated stage failure. |
| **5. `aidw review`** | `workflows/review.py`, `github.py`, findings extraction. | Dry-run prints the issue manifest; `--dry-run` creates no GitHub state; a live run creates parent + children via the bundled script. |
| **6. `aidw fix`** | `workflows/fix.py`, fix loop, model rotation. | Dry-run lists available children via `review_followup.py select`; loop honours `--max-iterations` and stops at exit 3. |
| **7. Hardening** | `--parallel`, `--retry-transient`, cost ceilings, `run` chains, tests, README. | Full `uv run pytest` green; `aidw doctor` green; documented operator guide (`aidt/README.md`). |

---

## 17. Resolved decisions (interview log)

| # | Decision |
|---|---|
| A1–A5 | Four groups, defaults accepted; integration tests + optional summary prompts out of scope; atomic stages + chain orchestrators; resumable. |
| B1 | Shared session within one agent's authoring stages; fresh sessions for reviewers; file-based cross-agent handoffs. |
| B2 | `update-traceability` shares the implementer session; review findings are extracted to a manifest file. |
| B3 | `pi --mode json`, tee JSONL, parse the final message. |
| B4 | `-p --approve` non-interactive; per-agent flags. |
| B5 | Wall-clock timeout always; optional cost ceiling. |
| C1 | `tools` is an **allowlist only** (deny-by-default when empty). |
| C2 | Per-agent `AGENTS.md`, inlined via `--append-system-prompt`, cwd = repo root. |
| C3 | `append` by default; `override` supported. |
| C4 | Baseline allowlists as in §5.2. |
| C5 | Warn on independence violations; `--strict` fails. |
| D1 | `./aidt` self-contained: its own prompt/script tree, no `.pi` dependency. |
| D2 | Wrapper renders `$1..$n`; no reliance on Pi `/` expansion. |
| D3 | `aidt/prompts/` is AIDT's own source of truth and is edited freely; `.pi/prompts/` is an upstream reference only and may be retired. |
| D4 | Pi cwd = Mythical Forge root. |
| E1 | Every gate optionally skippable; skips recorded. |
| E2 | Review publishing is ungated; human review happens on GitHub before `aidw fix`. |
| E3 | GitHub writes only through the bundled Python scripts (and the prompts that invoke them). |
| E4 | Safety refusals enforced; no worktrees in v1. |
| E5 | Env-inherited credentials; optional gitignored `aidt/.env.local`. |
| E6 | No auto-retry on gate failures; one retry for transient invocation errors (configurable). |
| F1 | `uv`-managed project; deps `pyyaml` + `typer`; `rich` optional. |
| F2 | CLI shape as in §14; single `aidw` dispatcher. |
| F3 | `aidt/runs/<run-id>/` artifacts, gitignored. |
| F4 | `aidw tasks` roadmap listing in v1; dependency-graph awareness deferred. |
| F5 | `pytest` locally; not part of the product's pnpm CI. |
| F6 | Auto-detect repo root from any cwd; absolute paths internally. |
| F7 | AIDT = AI Developer Tools; AIDW = AI Developer Workflows. |

---

## 18. Risks and open items

| Risk / open item | Status | Notes |
|---|---|---|
| Pi's `--append-system-prompt` may accept literal text rather than a file path | **Resolved (Phase 1)** | Verified: accepts both literal multi-line text and paths. AIDW passes file contents. |
| `--tools` allowlist interaction with MCP/extension tools | **Resolved (Phase 1)** | `--tools` is a strict allowlist over all tools; `mcp_config` alone exposes nothing, so MCP tool names must be listed. No baseline agent enables MCP in v1. |
| `pi -p` with a piped stdin prompt | **Resolved (Phase 1)** | Verified: `pi -p` uses piped stdin as the prompt; AIDW pipes the rendered prompt. |
| Review verdict parsing depends on the model following the `Approve`/`Request changes`/`Blocked` format | **Resolved (Phase 3 live validation)** | Layered parser: an explicit `Verdict: <token>` line, then a line beginning with a token, then the last bare mention; `None` fails closed. Naive last-mention-wins was wrong (`Request changes ... so `Blocked` is not warranted`). |
| Provider error reported with exit code 0 | **Resolved (Phase 3 live validation)** | `PiResult.provider_error` (from `stopReason`/`errorMessage`) marks the stage failed. |
| Review-fix loop leaves the prompt uncommitted | **Resolved (Phase 3 live validation)** | The workflow commits the owned prompt path after the gate if the rework changed it (`git.py:commit_paths`). |
| The author may name the task-prompt file differently than the assumed convention | **Resolved (Phase 3 live validation)** | The reviewer is pointed at the path the author actually reported, not a hard-coded filename. |
| Findings extraction into `findings.json` depends on the code-review output format | **Resolved (Phase 5)** | Strict labelled-block parser (`findings.py`): unknown priority, out-of-range confidence, or an empty required field records a problem and the workflow fails closed without publishing. `title` is derived from the finding body (the review format has no title). |
| Two reviewer models may not be available in the configured provider set | `--strict` independence checks would always fail | Ship placeholder configs with distinct models; document the minimum viable rule (`/code-review` ≠ `/impliment-task`) and allow `--strict` to be omitted in v1. `aidw fix` additionally warns (strict: fails) when no reviewer model differs from the fixer model. |
| The fix-loop prompts leave their changes uncommitted | Not AIDT's to fix | The canonical `/fix-next-review-followup` (like the implement stages) never commits; AIDT never commits or force-pushes (design §13). The operator or CI commits/pushes the fix branch. Documented as a deliberate boundary. |
| Prompts and helper scripts are independent of `.pi/prompts` | Prompt/script contract drift (labels, exact comments, markers) | Expected and intentional (decision D3). `constants.py` documents the contract with the prompts; change them together. `aidw prompts check` verifies presence and self-containment, not semantic agreement. |
| Pi session storage accumulates under `~/.pi` | Disk growth | Out of scope for v1; note in the README. |
| `aidt/` has no CI, so its own tests can rot | Toolkit regressions | Phase 7 adds a non-blocking CI job candidate; documented as a deliberate follow-up. |

---

## 19. Acceptance criteria for v1

AIDT v1 is complete when, from a clean checkout on `main`:

1. `uv run aidw doctor` exits 0 with a readable status report.
2. `uv run aidw agents validate` and `uv run aidw prompts check` exit 0.
3. `uv run aidw tasks --todo --phase 03` lists unchecked Phase 3 tasks parsed from the roadmap.
4. `uv run aidw prompt 03 E2 E2.9 --dry-run` prints the P1/P2 plan without writing; a real run
   produces `docs/task-prompts/03-E2.9-prompt.md` on branch `03-E2.9` and a logged verdict.
5. `uv run aidw implement docs/task-prompts/03-E2.9-prompt.md --dry-run` prints stages I1–I6 with
   agents, prompts, and models, and performs no git or GitHub writes.
6. `uv run aidw review --pr <n> --dry-run` prints the findings manifest and creates no GitHub state.
7. `uv run aidw fix --pr <n> --dry-run` lists available approved children via the bundled
   `review_followup.py select`.
8. Every stage appends a record to `runs/<id>/state.json`; a failed stage can be resumed with
   `--resume`.
9. Skips and gate decisions are recorded with mechanism and timestamp.
10. `uv run pytest` is green.
