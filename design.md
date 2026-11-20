# AI Developer Tools (AIDT) — Design

**Status:** Design of record. Sections describe the implemented toolkit unless they say
otherwise; §16 records where the implementation stands.
**Scope:** the `aidt` repository and the `aidw` command it installs. AIDT is a
developer-workflow toolkit: it drives the Pi agent through the SDLC stages of a **target
repo** — any git repository a developer points it at — one workflow at a time.
**Names:** AIDT = AI Developer Tools (the repository, the toolkit). AIDW = AI Developer
Workflows (the importable package and the console command `aidw`). One toolkit, one package,
one command; the two spellings are deliberate and are not normalised.
**Distribution:** installed once from a tag, independently of any checkout. The toolkit is
never vendored into a target repo, and a target repo is not a toolkit checkout (§12.5).
**Companion documents:** `docs/migration/EXTRACTION.md` is the extraction plan of record and
the source of the D/R decisions cited throughout; `README.md` is the operator guide;
`docs/target-repo-config.md`, `docs/roadmap-format.md` and `docs/releasing.md` are shipped
contracts this design cross-links rather than restates; `AGENTS.md` carries this repository's
own development conventions.

---

## 1. Purpose and scope

AIDT turns a human-driven, prompt-by-prompt development workflow into scriptable, resumable,
agent-configurable commands. A developer selects a roadmap task, and a wrapper drives one or
more specialised Pi agents through a defined sequence of stages, pausing at human decision
gates and recording every stage, gate and cost.

The workflow groups in scope:

| Group | Command | Stages |
|---|---|---|
| Task prompt generation + review | `aidw prompt` | author (P1) + bounded review/fix loop (P2, P2 fixes, reconcile) |
| Implementation + PR | `aidw implement` | I1–I9: implement, test, traceability (repo-optional), architecture (repo-optional), record, summarize, integration-test guide, roadmap tick, publish |
| Code review + issue creation | `aidw review` | R1 code review, R2 publish findings as GitHub issues |
| Review-follow-up approval | `aidw approve-followups` | A1 approve, without the fix loop |
| Issue fixing | `aidw fix` | A1 approval + bounded fix/test/re-review loop (F1–F4) |
| Chains | `aidw run` | `task-to-pr`, `review-and-fix`, `prompt-to-fix` |
| Inspection / primitives | `aidw tasks`, `agents`, `runs`, `prompts`, `config`, `worktree`, `gate`, `doctor`, `exec` | §14 |

The groups were derived from an earlier human-run workflow document that lived in the product
repo AIDT was first used on. That document is **not** part of this toolkit and is not a source
of truth here: the stages, ordering and gates below are AIDT's own design.

### 1.1 Two roots and a state root

AIDT has exactly two roots it operates on plus one it writes state to, and they are never
interchangeable (EXTRACTION.md §3.1):

| Concept | Meaning | Resolved from |
|---|---|---|
| **Toolkit root** | Where the installed toolkit's code, **default** prompts, agent configs, agent context files and `prompts/scripts/` live. Read-only for every workflow. | The installed package location (`aidw.paths.toolkit_root()`, `ToolkitPaths`) — never git, never the target. |
| **Target repo root** | The working tree the workflow operates on: git operations, generated documents, `<target>/aidw/` config, repo prompt overrides. | The working directory by default, then `--repo <path>`, then `$AIDW_REPO` (`TargetRepo.resolve`). |
| **Workspace root** | The folder holding the bare repo and all sibling worktrees. Not itself a git repository. | `dirname(<absolute git-common-dir>)` (`WorkspacePaths.workspace_root`). |
| **State root** | Per-repo run state, run locks and artifact directories. Outside every working tree in the supported layout. | `$AIDW_STATE_DIR`, else `<workspace root>/.aidw/state/<repo-slug>`, else `~/.aidw/state/<repo-slug>` (`WorkspacePaths.state_root`). |

Rules that follow, and that the rest of this document assumes:

- `ToolkitPaths`, `TargetRepo` and `WorkspacePaths` are three **distinct types**, never one
  `root: Path` flag with two meanings. A toolkit-relative path (`agents_md`, a prompt
  template, a bundled script) and a target-relative path (`cwd`, `paths.roadmap_dir`,
  `aidw/prompts/*.md`) must never be swapped (§3.1).
- A target repo with no `aidw/` folder is valid: it gets the toolkit's pure defaults.
- Nothing generated is written into a target repo (§3.3).
- `--repo`, `$AIDW_REPO` and cwd select only the **target**. No flag can point the toolkit at
  a checkout, and the toolkit root is resolvable with no repository at all (§14: `aidw
  --version`, `aidw doctor`'s environment checks).

Worktree layout, worktree creation and the per-worktree run lock are the target-side
consequences of this split; §3.2, §8.1, §8.2 and §9.1 state them where the workflows meet them.

### 1.2 What AIDT must never do

- Never let an agent bypass a gate silently: every skipped gate is recorded in `state.json`.
- Never reimplement GitHub logic: all GitHub reads/writes go through the bundled Python
  scripts (`publish_review_followups.py`, `review_followup.py`) or read-only `gh` calls,
  exactly as the prompts specify.
- Never merge a PR, force-push, `git reset --hard`, `git clean`, or discard unrelated user
  changes. AIDT never merges — that is the delivery pipeline's job.
- Never commit secrets. Never write outside the repository except the state root and Pi's own
  session store.

### 1.3 Non-goals

- **Deployed integration tests.** They need a deployed dev stack and post-CI ordering. A stage
  stub exists in the state model, but no workflow invokes it; the bundled product prompt is not
  wired in. `I9 write-integration-test-guide` (§8.2, §17 Z6) writes a human-run **guide** to
  such a test and runs nothing itself, so the non-goal holds: AIDT writes the recipe, a human
  runs it. A target repo may add a deployed-test stage (§12.2).
- **Optional summary prompts, as a class.** The bundled leftovers remain available as ordinary
  prompts and are not workflow stages. The one deliberate exception is `I8
  summarize-implementation-results` (§8.2), the narrative summary the toolkit's own `implement`
  chain produces; reversing this non-goal for it is decision `Z3` (§17) and scopes to exactly
  that summary.
- **Merging PRs.** AIDT never merges (§1.2).
- **Procedural authoring of roadmap tasks.** AIDT selects existing roadmap tasks; it does not
  invent them (§11).
- **A web UI.** CLI only.
- **Cross-*task* parallelism inside one invocation.** `--parallel` means concurrent *stages*
  inside one task (§8.2). Running several tasks at once is several `aidw` invocations in
  separate workspace locations — a property of the workspace, not of a run.

---

## 2. Concepts and terminology

| Term | Meaning |
|---|---|
| **Toolkit** | This repository's installed form: `aidw/` code plus the default `prompts/`, `agent-configs/`, `agents/` trees, resolved through `ToolkitPaths`. |
| **Target repo** | The git working tree a workflow operates on (`TargetRepo`). Owns its `<target>/aidw/config.yaml`, optional `aidw/conventions.md` and optional `aidw/prompts/` overrides. |
| **Workflow** | One of the registry entries: `prompt`, `implement`, `review`, `fix`, `approve`, plus the `run` chains (§8). |
| **Stage** | One Pi invocation with one prompt and one agent. The atomic unit of work, identified by a stable id (`I1`…`I9`, `P1`, `R1`, `R2`, `A1`, loop ids) so existing run artifacts stay readable. |
| **Stage registry** | The config-driven, data-defined default stage lists and loops (`aidw/stage_registry.py`), which a target repo may override per stage, disable (repo-optional stages only) or extend (§12.2). |
| **Agent** | A named configuration (`agent-configs/<id>.yaml`) bundling model, system-prompt mode, context file and tool allowlist. Resolved from the **toolkit**, shadowable by a target directory of the same shape (`paths.agent_configs_dir`, §5.1). Agents are stateless; a session is their memory. |
| **Run** | One execution of a workflow. Identified by `run_id` (`<utc-stamp>-<task-or-pr>-<workflow>`, so sibling runs of one task are distinguishable in a directory listing) and persisted under `<state root>/<repo-slug>/runs/<run-id>/` (§9.1). |
| **Gate** | A human decision point (§6). Every gate is skippable (`--yes`) and every decision or skip is logged. |
| **Verification gate** | A repo command run once per content tree (`aidw gate run <key> -- <command>`) and recorded in `state.json`, so a later stage cites the outcome instead of re-running it (§9.2). Not to be confused with a human gate. |
| **Artifact** | A file a stage produces or consumes for a cross-agent handoff (task-prompt path, findings manifest, PR number). |
| **Session** | A Pi session (JSONL). Authoring-adjacent stages of one agent in one run share a session; independent reviewers always get a fresh session (§5.3). |
| **Author ≠ judge** | The workflow's model-independence rule, enforced by config validation (§5.4). |
| **Provenance** | Where a resolved config value came from: `default`, `config`, or `override` (§12.1). |

---

## 3. Repository layout

The toolkit repo is self-contained (EXTRACTION.md §3.12). Everything the toolkit needs at
runtime is inside the installed package plus three repo-root sibling directories that ship in
the wheel; everything else is development-time. `ToolkitPaths` resolves the toolkit assets and
`TargetRepo` resolves the target checkout; they are never interchangeable. R8 applies here:
Nothing generated is written inside the **toolkit** repo or inside a **target** repo.

```text
aidt/                          # repo root; holds every AI developer tool
├── aidw/                      # the importable package (CLI: aidw) — see §4
│   ├── aidw                   # executable entry point (thin shim -> cli:main)
│   └── workflows/             # prompt.py, implement.py, review.py, fix.py, approve.py, run.py
├── prompts/                   # toolkit DEFAULT prompts (+ scripts/review-followup/)
├── agent-configs/             # default agent configs (a target may shadow them, §5.1)
├── agents/                    # default per-agent AGENTS.md / SYSTEM.md fragments
├── docs/
│   ├── history/               # aidw-initial-prompt*.md (D24: historical design inputs)
│   ├── schema/
│   │   └── aidw-config.schema.json   # JSON Schema for the target config (§12.1)
│   ├── roadmap-format.md      # the AIDT roadmap contract (§11)
│   ├── target-repo-config.md  # the target-config contract + worked examples (§12.1)
│   ├── releasing.md           # tag releases, install forms, `requires_toolkit` pins (§12.5)
│   ├── migration/EXTRACTION.md# the extraction plan of record (kept as history)
│   ├── tasks/                 # this repo's own roadmap: AIDT dogfoods its SDLC (D21)
│   ├── task-prompts/          # task prompts produced by `aidw prompt`
│   └── implementation-results/ # per-task build-results docs, plus TEMPLATE.md
├── tests/                     # pytest (§15)
├── fixtures/target-repo/      # a fixture target repo used by the interface tests (§15)
├── design.md                  # this document
├── README.md                  # operator guide
├── pyproject.toml             # uv-managed; hatchling build; `aidw` console script
├── uv.lock
└── .github/workflows/ci.yml   # pytest + doctor on every push and PR
```

Machine-local content is ignored, never committed: `.venv/`, `__pycache__/`,
`.pytest_cache/`, the historical `runs/`, and any `.aidw/` state directory a repo resolves
inside its own tree (the single-checkout case, §9.1).

### 3.1 Two distinct path types

The toolkit root, the target repo root and (in the bare + worktrees layout) the workspace root
are three different things, and AIDT models them as three different types on purpose:

| Type | Answers | Never used for |
|---|---|---|
| `ToolkitPaths` (`aidw/paths.py`) | "where is the installed toolkit's `prompts/`, `agent-configs/`, `agents/`, `prompts/scripts/`?" | target documents, git operations, config reads |
| `TargetRepo` | "which working tree am I operating on, and what is its git base/common dir?" | toolkit assets — there is no `aidt/` inside a target repo |
| `WorkspacePaths` | "where is the bare repo's folder, and where does per-repo state live?" | anything inside a working tree |

Two consequences the code enforces, not just documents:

- A **stage's `cwd` is target-relative**, while its `agents_md`, `system_prompt.file`,
  `mcp_config`, `skills`, `extensions` and `prompt_templates` are **toolkit-relative** (§5.1).
  A prompt-invoked helper script therefore locates itself through the runner-provided
  `AIDW_SCRIPTS_DIR` (an absolute toolkit path), never through a path relative to the
  stage's cwd — which would resolve inside the target repo and fail.
- `aidw/worktree` and the workflows translate a branch into a **target** worktree and then
  re-resolve `TargetRepo` against it, so every stage, `github.*` read, the run lock and
  `state.json`'s `repo_root` agree on one tree (EXTRACTION.md §3.2).

### 3.2 `aidw/` means two things

Inside the **toolkit** repo, `aidw/` is *code*: the Python package behind the `aidw` command.
Inside a **target** repo, `aidw/` is *configuration*: `config.yaml`, optional `conventions.md`,
optional `prompts/`. Same word, two roles, by owner decision (D7 in EXTRACTION.md §2). A
design that says "`aidw/` is X" without the dual role misleads implementers, so every rule
below names which one it means.

### 3.3 Nothing generated is written into a target repo

R8, from EXTRACTION.md §3.1/§3.10, is absolute: no `runs/`, no locks, no caches, no toolkit
scratch files are ever created inside a target repo or inside any worktree. Run state and
locks live in the state root, outside every working tree in the supported layout, so `git
worktree remove` can never delete a live run. The single-checkout case is the one exception in
*mechanism* — there the state root necessarily resolves inside the tree
(`<root>/.aidw/state/<repo-slug>`) — and AIDT **warns** about it in `aidw doctor` rather than
pretending otherwise.

---

## 4. Architecture

```
        ┌──────────────────────────── aidw CLI (Typer) ────────────────────────────┐
        │ prompt | implement | review | fix | approve-followups | run | tasks      │
        │ worktree | agents | exec | runs | gate | prompts | config | doctor       │
        └───────────────┬──────────────────────────────────────────────────────────┘
                        │
             ┌──────────▼──────────┐   resolves the three roots once:
             │ paths.py            │   ToolkitPaths · TargetRepo · WorkspacePaths
             └──────────┬──────────┘
                        │
             ┌──────────▼──────────┐   config-driven plan (target overlay applied)
             │ stage_registry.py   │   workflow definitions, stage ids, loops
             └──────────┬──────────┘
                        │
   ┌────────────────────▼─────────────────┐
   │ Workflow modules                     │  prompt/implement/review/fix/approve/run
   └──┬───────┬────────┬─────────┬────────┘
      │       │        │         │
 ┌────▼───┐ ┌─▼─────┐ ┌▼───────┐ ┌▼────────────┐
 │state.py│ │gates.py│ │lock.py │ │verification.py│  run state, HITL, one-run-per-worktree lock,
 │        │ │ HITL   │ │        │ │ E4.8 gate reuse│  content-tree gate outcomes
 └────────┘ └────────┘ └────────┘ └──────────────┘
                        │
             ┌──────────▼──────────────────────┐
             │ runner.py · stage_registry.py   │  plan → render → run → record
             │ config.py · agents.py · prompts.py │  agent configs, Pi argv, prompt rendering
             └──────────┬──────────────────────┘
                        │
             ┌──────────▼─────────┐    ┌──────────────────────────────────┐
             │       pi.py        │───▶│ pi (subprocess, --mode json)      │
             │  invoke/capture    │    └──────────────────────────────────┘
             └──────────┬─────────┘
                        │
   ┌────────────────────▼──────────────────┐   ┌────────────────────────────────────┐
   │ git.py · github.py · findings.py      │──▶│ bundled review-followup scripts     │
   │ verdict.py · cost.py · report.py      │   │ + read-only `gh` reads              │
   └───────────────────────────────────────┘   └────────────────────────────────────┘
```

Module map (`aidw/`):

| Module | Job |
|---|---|
| `paths.py` | `ToolkitPaths`, `TargetRepo`, `WorkspacePaths`; state-root and slug resolution; runner-provided environment variable names. |
| `layout.py` | The workspace-layout guards: bare target, clone-of-a-worktree, state root inside a working tree (§9.1). |
| `config.py` | Agent-config loading, validation, target override directory. |
| `target_config.py` | Target-config loading, layered resolution with provenance, compatibility, path classification, config identity. |
| `stage_registry.py` | The default workflows as data: stage ids, loop descriptors, parallel groups, plan expansion. |
| `prompts.py` | Prompt rendering, frontmatter stripping, repo-convention injection. |
| `agents.py` | Agent → Pi argv rendering. |
| `pi.py` | Pi subprocess invocation, JSONL capture, result parsing. |
| `runner.py` | The stage primitive (plan → resolve prompt → run → record) and `--dry-run` plans. |
| `state.py` | Run state read/write, resume, stage/gate/gate-outcome bookkeeping. |
| `lock.py` | One-run-per-worktree cross-process lock in the state root. |
| `git.py` | Git safety checks, branch/worktree primitives, PR helpers. |
| `github.py` | Read-only `gh` wrappers around the bundled Python scripts, plus the frozen-contract config handoff (§7.2). |
| `gates.py` | Human-in-the-loop prompts and skip recording. |
| `roadmap.py` | Roadmap parsing against the configured directory and glob (§11). |
| `verdict.py` | Deterministic `Approve` / `Request changes` / `Blocked` parsing. |
| `findings.py` | Strict findings-manifest parsing and rendering. |
| `inventory.py` | Toolkit-default and target-resolved prompt/script inventory checks. |
| `verification.py` | Content-tree identity and gate-outcome citation (`aidw gate`). |
| `cost.py`, `report.py`, `log.py`, `progress.py` | Pricing-gap check, stage reporting, run log, live progress. |
| `doctor.py` | Environment, root, layout, config, compatibility and inventory checks (§12.4). |
| `cli.py` | Typer app, target selection, exit codes (§14). |

**Data flow of one stage**

1. The workflow resolves the target config, then the stage definition, agent and prompt from
   the registry plus the target's overlay (§12.1–§12.3).
2. `runner.resolve_prompt` resolves the prompt file: explicit stage path, then the target's
   `aidw/prompts/` shadow, then the toolkit default, then an error (§12.3).
3. `prompts.py` loads it, strips YAML frontmatter, substitutes `$1..$n`, and appends the target
   repo's conventions where the prompt takes them.
4. `config.py`/`agents.py` build the Pi argv (`--provider`, `--model`, `--thinking`, `--tools`,
   system-prompt flags, `--session-id` when sharing) with `cwd` = the target worktree.
5. `pi.py` runs Pi non-interactively with the rendered message on stdin, tees stdout to
   `<run-dir>/stages/<stage>.jsonl`, and captures the final assistant message.
6. The workflow parses the result (verdict, artifact paths), runs the stage's postcondition if
   it declares one, and writes the stage and gate records to `state.json`.
7. Cross-agent handoffs are written as files under `<run-dir>/artifacts/` and passed on as
   variables or as absolute paths (§8.3, decision O1).

---

## 5. Agent configuration

### 5.1 Schema

One YAML file per agent under the **toolkit's** `agent-configs/`. Validated on load by
`config.py` (PyYAML + explicit checks; no pydantic).

```yaml
# agent-configs/implementer.yaml
id: implementer                       # required, unique, must match filename stem
description: Implements a task prompt as code plus module contract/property tests.

provider: openrouter                  # required; passed to pi --provider
model: <provider/model-slug>          # required; passed to pi --model
thinking: medium                      # off|minimal|low|medium|high|xhigh|max

system_prompt:                        # optional
  mode: append                        # append | override | none   (default: append)
  file: agents/implementer/SYSTEM.md  # required when mode != none; toolkit-relative

agents_md: agents/implementer/AGENTS.md  # optional context file; toolkit-relative

tools:                                # allowlist; deny-by-default
  - read
  - bash
  - write
  - edit

skills: []                            # -> repeated --skill <path>          (toolkit-relative)
extensions: []                        # -> repeated --extension <path>      (toolkit-relative)
prompt_templates:                     # -> repeated --prompt-template <path> (toolkit-relative)
  - prompts
mcp_config: ../.mcp.json              # optional -> --mcp-config <path> (toolkit-relative)
cwd: .                                # relative to the TARGET repo root; default the target root
env: {}                               # extra environment variables for the subprocess
session: shared                       # fresh | shared  (see §5.3)
timeout_seconds: 3600                 # required
max_cost_usd: null                    # optional ceiling; run aborts when exceeded (best-effort)
output: json                          # json | text  (default json)
```

Path resolution is the two-root rule of §3.1 in miniature: **`cwd` is target-relative**;
`agents_md`, `system_prompt.file`, `mcp_config`, `skills`, `extensions` and `prompt_templates`
are **toolkit-relative**; absolute paths are used as-is.

**A target repo may override agent configs globally** (D12, decision N1): the resolved
`paths.agent_configs_dir` (default: unset — deliberately not defaulted) names a directory of
`*.yaml` files, loaded **after** the toolkit's and shadowing **by id**. Un-overridden toolkit
ids still load, a brand-new id is additive and is a legal `agent:` target, an empty directory
equals the toolkit defaults, and a named-but-missing directory is an error (exit 2). Precedence
is **per-stage override > global override directory > toolkit default**, for that stage's
invocation only.

### 5.2 Tool allowlist semantics (deny-by-default)

- `tools` is the **only** tool field. There is no deny list.
- Passed to Pi as `--tools <comma-separated>`.
- An empty or omitted `tools` list means the agent gets **no** built-in, extension, or custom
  tools: the wrapper passes `--no-tools`.
- A reviewer that must not mutate the tree simply omits `write`/`edit`; that is the
  enforcement mechanism, not a prompt instruction.
- MCP tools count as tools. An agent needing MCP tools must list them explicitly in `tools`
  **and** set `mcp_config`; because `--tools` is a strict allowlist over built-in, extension
  and MCP tools, setting `mcp_config` alone exposes nothing. No baseline agent enables MCP.
- Adding an extension/MCP tool name produces a validation **warning** (it is not a known
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
| `pr-publisher` | read, bash, write, edit | commits/pushes/opens PR; `edit` for doc fixups |
| `code-reviewer` | read, bash | read-only |
| `review-publisher` | bash | delegates to the bundled Python script |
| `review-approver` | bash | delegates to the bundled Python script |
| `fixer` | read, bash, write, edit | implements one approved finding |

### 5.3 Session policy

- `session: fresh` (default for reviewers, recorder, PR publisher, publisher/approver): every
  stage invocation gets a new Pi session id (`--session-id aidw-<run_id>-<agent>-<stage>`),
  giving a clean context. Pi prints a benign ``No project session found with id ...; creating a
  new session`` warning when a session id is new; AIDW treats it as expected, not an error.
- `session: shared` (default for `implementer`): all stages assigned to that agent in one run
  reuse a single session id (`--session-id aidw-<run_id>-<agent>`), so `/impliment-task`,
  `/update-traceability`, and `/update-architecture` share naming and format context — the
  implementation stages need each other's decisions (the traceability stage cites the test
  names the test stage added; the architecture stage keeps the design decisions consistent).
- Reviewer independence is a **model** property, not a session property; a fresh session alone
  is never sufficient (§5.4).

### 5.4 Model routing and validation

The role table maps stages onto agent configs. A target repo may override the *agent* of a
stage (§12.2), but the independence rules below still apply to the effective set.

| Stage | Agent | Role |
|---|---|---|
| P1 task-prompt | `task-author` | authoring |
| P2 task-review | `task-reviewer` | **reviewer ≠ `task-author` and ≠ `task-fixer` model** |
| P2 fixes / reconcile | `task-fixer` | authoring |
| I1 impliment-task | `implementer` | authoring |
| I2 test | `tester` | **reviewer ≠ `implementer` model** |
| I3 update-traceability | `implementer` | authoring (shared session) |
| I4 update-architecture | `implementer` | authoring (shared session) |
| I5 record-implementation-results | `recorder` | cheap/mechanical |
| I8 summarize-implementation-results | `recorder` | cheap/mechanical |
| I9 write-integration-test-guide | `recorder` | cheap/mechanical |
| I7 update-roadmap | `recorder` | cheap/mechanical |
| I6 pr | `pr-publisher` | cheap/mechanical |
| R1 code-review | `code-reviewer` | **reviewer ≠ `implementer` model** |
| R2 review-findings-to-github | `review-publisher` | cheap/mechanical |
| A1 approve-review-followups | `review-approver` | cheap/mechanical |
| F1 fix-next-review-followup | `fixer` | authoring |
| F2/F3 re-review | `tester`, `code-reviewer` | reviewers (rotate models when a second reviewer exists) |

`config.py` validation rules:

1. `id` matches filename; all referenced files exist (respecting the two-root resolution of
   §5.1).
2. Required fields present; `thinking`, `session`, `output` in range.
3. **Independence check:** `task-reviewer.model != task-author.model`,
   `task-reviewer.model != task-fixer.model`, `tester.model != implementer.model`,
   `code-reviewer.model != implementer.model`, and `tester.model != code-reviewer.model`.
   Default: emit a **warning**. With `--strict`, fail.
4. Reviewer agents (`task-reviewer`, `code-reviewer`) must not have `write` or `edit` in
   `tools`; warn, or fail with `--strict`.
5. Every workflow's required agent ids resolve.

Independence is checked at the workflow level too: before running a code review on a fix
branch, AIDT refuses to reuse an agent whose model equals the model that authored the diff,
with an explicit `--force-model` escape hatch that is recorded in state.

### 5.5 System prompt and context files

- Pi's `--append-system-prompt` and `--system-prompt` accept literal text (verified against Pi
  0.85.x, the floor `aidw doctor` enforces). AIDW reads `agents_md` / `system_prompt.file` and
  passes their **contents**, so behaviour does not depend on Pi's path-vs-literal detection.
  Multi-line literal text is supported.
- `agents_md` is always appended (`--append-system-prompt`), in every `system_prompt.mode`.
- `system_prompt.mode: override` replaces Pi's default prompt via `--system-prompt`; `append`
  adds to it; `none` (or an omitted `system_prompt`) adds nothing.
- Repository context files remain enabled by default, so the **target** repo's `AGENTS.md`
  still loads at `cwd` = target root. Set `no_context_files: true` on an agent to disable
  discovery.

---

## 6. Human-in-the-loop gates

Every gate is skippable. `--yes` approves all gates in a run; `--skip-gates <name,...>` skips
specific gates; `--deny-gates <name,...>` refuses specific gates and is checked before both, so
an explicit refusal cannot be overridden by a blunter approval. Every decision and skip is
written to `state.json` with timestamp and mechanism (`human`, `human-default`, `human-denied`,
`--yes`, `--skip-gates`, `--deny-gates`, `noninteractive`).

**The interactive default is approve**: Enter at a prompt approves, and the marker reads
`[Y/n]`. `--gate-default deny` (or `AIDW_GATE_DEFAULT=deny`) restores the strict `[y/N]` prompt;
the CLI flag wins over the environment variable. `human` means the human typed `y`,
`human-default` means Enter accepted an approve default — the distinction is kept so an audit
can tell consent from convenience.

| Gate | Workflow | Default behaviour | Skip flag |
|---|---|---|---|
| `approve-task-prompt` | `prompt` | Optional. After the review loop returns `Approve`, show the verdict + prompt path and ask to proceed. Not required by default; enable with `--require-approval`. | `--require-approval`, `--yes`, `--skip-gates approve-task-prompt` |
| `approve-implementation-pr` | `implement` | After the record stage, show gate results and ask before the PR stage commits, pushes, and opens the PR. | `--yes`, `--skip-gates approve-implementation-pr` |
| `confirm-review-publish` | `review` | **Not used by default** (see below). | n/a |
| `approve-followups` | `fix`, `approve-followups` | At entry, list the PR's open child issues with their GitHub state and ask which to approve; runs the approval stage. | `--yes`, `--skip-gates approve-followups` |
| `approve-fix-pr` | `fix` | After each fix + re-review, before the fix is considered done (i.e. before moving to the next issue). | `--yes`, `--skip-gates approve-fix-pr` |

**Review publishing is deliberately ungated (decision E2).** `aidw review` runs the code review
and, when findings exist, immediately publishes the parent + child issues **without** a human
confirmation prompt inside the run. Human review happens **on GitHub** between `aidw review` and
`aidw fix`. To make this safe:

- `review-publisher` runs with `--tools bash` only; all writes go through
  `publish_review_followups.py`, which is idempotent and validates the manifest.
- `aidw review --dry-run` renders the manifest, prints exactly what would be created, and
  performs no writes.
- Children are created `decision-pending`; no code is written until `aidw fix` approves them.
- The publish stage carries a read-only postcondition (`github.verify_published`), so an agent
  that exits 0 without publishing fails the stage (§8.3, §10).

Gate UI: `gates.py` prints a compact summary to the TTY and reads a line from stdin. In
non-interactive/CI contexts (`--yes`, `AIDW_NONINTERACTIVE=1`, or no TTY), unapproved gates fail
closed with a clear message unless an explicit flag approves them. The approve default is
**not** an auto-approval: it only decides what Enter means for a human at a terminal, so a
scripted run still needs `--yes` or `--skip-gates`.

---

## 7. Prompts and helper scripts

### 7.1 Defaults and overrides

`prompts/` in the toolkit is AIDT's **own** source of truth for the default prompts. It holds
every prompt and every helper script the workflows invoke, including the review-followup Python
tools; it is edited freely as the workflows evolve, and the toolkit never mirrors or compares it
against any other prompt directory.

The library is **14 prompts**: six generic, five neutralised against repo-specific tooling, and the
three (S1) that the *default* chains invoke — `task-prompt.md` (`P1`), `update-traceability.md`
(`I3`) and `update-architecture.md` (`I4`) — which were rewritten product-free at cutover because a
target repo with no `aidw/` folder must still run. Product-specific prompts are not part of this
library at all: the repo that owns them ships them under its own `aidw/prompts/`, shadowing by
filename. §17 S1 records the split; `docs/migration/prompt-classification.md` is the inventory.

Resolution is per prompt, per stage (D4/D14, §12.3): a target repo may **shadow any prompt by
filename** under `<target>/aidw/prompts/`, or point a stage at an explicit path, and only what
it does not override falls back to the toolkit default. `prompts/scripts/` stays toolkit-side
in every case: the helper scripts are GitHub bookkeeping, not repo-specific, and a target repo
has no scripts tree to shadow them with.

### 7.2 Frozen GitHub contracts (D5)

Some strings in this tree are **already written into live GitHub issues** in Mythical Forge, the
product repo where AIDT was first used: the three review-followup **marker templates** (parent,
child, summary), the six **label** names with their exact colours and descriptions, and the
three exact-match **comment bodies** (`Status: in progress`, `Status: fixed`, `Decision: approve-fix`)
in `prompts/scripts/review-followup/constants.py`.

The freeze is the contract (EXTRACTION.md §3.9):

- The marker templates and label definitions are **per-repo configuration**
  (`github.markers.*`, `github.labels.*`, §12.1) whose **defaults are today's literals**. A repo
  that pins those literals in its `aidw/config.yaml` sees not one character of any existing
  issue change; a repo that has never run the workflows gets those defaults.
- They are therefore **not** toolkit brand constants. They are one repo's historical values,
  preserved as defaults so the migration is a no-op.
- Parent lookup is an **exact string match** (`find_parent_issues` in the bundled `aidw/github.py`), and
  the comment bodies are compared with **strict `==`** (the bundled `logic.py`). No whitespace
  normalisation, no case folding, anywhere in that path.
- Renaming a marker or label orphans every existing parent/child and causes duplicate issue
  creation on the next publish. Changing them for a repo that already has issues is a one-time
  marker/label migration across open issues and is explicitly out of scope (EXTRACTION.md §9).

The freeze is guarded by tests, not by convention: `tests/test_baseline_verbatim_golden.py`
loads `prompts/scripts/review-followup/constants.py` **as of the `baseline-verbatim` tag** and
asserts the resolved marker templates, every label colour/description and the exact-match
comment bodies are byte-identical — both through `resolve_config` and through
`TOOLKIT_DEFAULTS.github`. It fails loudly (never skips) when the tag is missing, which is why
CI checks out full history.

The values themselves, the label table and the worked config example live in
`docs/target-repo-config.md` (`github:` section) and in
`docs/schema/aidw-config.schema.json`; this design does not restate them.

Prompt/script compatibility is a contract in the same sense: the exact strings the
review-followup scripts rely on are declared in `constants.py` and must be changed together with
the prompts that document them.

### 7.3 Prompt rendering (decision D2)

`prompts.py`:

1. Reads the prompt file (UTF-8).
2. Strips a leading YAML frontmatter block (`---` … `---`) — it is Pi template metadata, not
   message content.
3. Replaces positional tokens `$1`…`$n` with the stage's variables. Only `$` followed by digits
   is substituted, so shell references such as `$runner` and `$pr` inside prompts are untouched.
4. Appends the target repo's `aidw/conventions.md` where the prompt is one that takes it
   (D16; labelled with its source). The root `AGENTS.md` is **not** appended: Pi already
   delivers it as project context at `cwd` = target root (§5.5), so the renderer's copy
   duplicated the same file in every stage that takes conventions. A prompt whose *resolved*
   file declares the frontmatter marker `append_agents_md: true` opts back in — the escape
   hatch for a repo whose agents set `no_context_files: true` and would otherwise lose
   `AGENTS.md` entirely — and then both sources are appended in D16 order (`AGENTS.md` first).
   The marker is read from the resolved prompt path, never from the toolkit default or a
   stage id, and only the YAML boolean `true` counts: absent, `false`, a quoted string, a
   malformed value, a frontmatter-less prompt and a missing file all mean dropped (C1.1, §17).
   The **read** channel is untouched by the injection split: `read_conventions_sources`/
   `CONVENTIONS_SOURCES` still return both sources in D16 order, and the prompt workflow's
   evidence bundle (`aidw/workflows/prompt.py:_gate_block`) reads its gate commands from
   either one. C1.2 extends only what that reader recognises (design §8.1): a gate list may
   open with `## Gates` **or** `## Gate commands`, plus the target's optional top-level
   `gates_heading` — the full `## `-prefixed heading line, matched verbatim by the same
   prefix rule. Recognition is a `startswith` test, never `==`, so a suffixed canonical
   heading such as `## Gates — run exactly these` still matches. The recognised set and both
   pure helpers live once in `aidw/prompts.py` (`GATES_HEADINGS`, `is_gates_like_heading`,
   `is_recognised_gates_heading`); the bundle reader imports the tuple as `_GATES_HEADING`
   and `aidw doctor` imports the same objects, so the two cannot drift.
5. Appends the target repo's **resolved gate commands** where the prompt is one that records
   gate outcomes (C1.3): the five resolved basenames `impliment-task.md`, `test.md`,
   `fix-next-review-followup.md`, `record-implementation-results.md` and `code-review.md`
   (`aidw/prompts.py:GATE_PROMPTS`) receive the block verbatim under one source-labelled header,
   `## Resolved gate commands (AGENTS.md + aidw/conventions.md)`. The block is resolved once,
   by `aidw/prompts.py:resolved_gate_block`, from `read_conventions_sources` in D16 order using
   step 4's heading recognition plus the target's declared `gates_heading` — the *same*
   resolution the evidence bundle uses, because `aidw/workflows/prompt.py:_gate_block` is now a
   thin wrapper that maps its `None` to `unavailable`. It is appended **after** step 4's
   conventions block, and the prompt keeps its own `aidw gate run <key> $SCOPE -- <command>`
   wrappers and key/scope guidance: a repo's gate section is bare commands, so the injection
   supplies the commands, never the wrapper. A prompt outside the five, and a repo that
   resolves no block, both leave the text **byte-identically** unchanged — the renderer never
   injects an `unavailable` note, which is the evidence bundle's degrade, a different consumer.
   Where a prompt is in both this set and `CONVENTIONS_PROMPTS`, the full `aidw/conventions.md`
   append may also contain its gate section; the focused resolved block is the authoritative
   presentation of the commands and its header appears exactly once (Z17).
6. Returns the rendered text, which `pi.py` passes as the final message on stdin to `pi -p`.

The wrapper does **not** rely on Pi's `/` prompt-template expansion: CLI invocation would not
expand it, and rendering in Python keeps the transform testable.

### 7.4 External dependencies

- The Archify skill referenced by `/update-architecture` is machine-local
  (`~/.pi/agent/skills/archify/`). `aidw doctor` checks for it and reports a warning if absent;
  the architecture stage only needs it when a diagram changes.
- A target repo's `.mcp.json` (if any) is passed via `--mcp-config` for agents that list MCP
  tools; the toolkit's own `.mcp.json` is absent and the doctor check warns rather than fails.
- `gh` authentication, `pi` authentication and any cloud profile come from the environment
  (§12.4).

---

## 8. Workflow specifications

Notation: `→` runs a stage, `◇` is a gate, `⟳` is a bounded loop, `∥` is a parallel pair (v1 runs
these serially by default; the design allows `--parallel`).

Every workflow's stage list is the **registry default** overlaid by the target's
`workflows.<name>` config (§12.2): a repo may override a stage's agent/model/thinking/timeout,
disable a repo-optional stage, and add stages; it may not reorder or remove a core stage.

### 8.1 `aidw prompt <phase> <epic> <task>`

```
preflight (control worktree on the base branch, clean tree; fetch and refuse when the base
           branch is behind origin; refuse on an unticked predecessor in the same phase file)
  → create the task worktree for the derived branch (Python-owned branch setup)
  → P1 task-prompt        (agent task-author)      writes <task_prompts_dir>/<id>-prompt.md
  → P2 task-review-1..N   (agent task-reviewer)    read-only verdict
  ⟳  if Request changes: P2a task-prompt-fixes (agent task-fixer; one stage per finding)
                          then task-review-reconcile-N (agent task-fixer; one per batch)
                          then P2 again — fixes run only for the first max_revisions-1
                          rounds; the max_revisions-th review is review-only
                          (default 3, `--max-revisions`; a residual Request changes exits 3)
  ◇  approve-task-prompt        (optional; off unless --require-approval)
  → commit the reviewed prompt in the task worktree
```

- Branch setup is a Python stage, never an agent's `git checkout -b`: the branch and worktree
  name come from `repo.branch_pattern`, the worktree is located at the workspace root and created
  only when none exists, and every later stage of the run is re-resolved into it (EXTRACTION.md
  §§3.2, 3.4). A malformed pattern is a usage error (exit 2); a git refusal is a preflight
  refusal (exit 4); both happen before any stage or run state.
- A located worktree is **reused**, not re-created (`git.add_worktree` returns `None` for an
  already-checked-out branch, so calling it unconditionally refused every re-run): a resume
  continues in the failed run's own tree, whose partial prompt edits are the state it continues
  from, while a fresh re-run reuses the tree only when it is clean. A dirty reused tree, or a
  leftover branch with no worktree, is a preflight refusal (exit 4) that prints the same two
  copy-pasteable commands — `aidw worktree remove <branch> --force` and
  `git -C <base-worktree> branch -D <branch>` — because design §13 makes the discard an explicit
  operator action, never something AIDT performs. Both sit at branch setup: after the L1.1/L1.2
  preflights, before the run lock, the run record and any stage.
- The preflight fetches `origin` and refuses (exit 4) when the local base branch is behind or
  diverged from `origin/<base>`; `--no-fetch` skips the fetch and the comparison.
- Before that fetch, the preflight refuses (exit 4) when an earlier task in the target's own
  roadmap phase file (the configured `paths.roadmap_dir`) is still unticked, naming every
  incomplete predecessor in roadmap order. `--allow-incomplete-prereqs` proceeds with a warning
  instead. `--dry-run` reports the incomplete predecessors and never refuses.
- `P1` receives `$1=phase`, `$2=epic`, `$3=task`. The prompt itself creates no branch and
  commits nothing — AIDT owns both (EXTRACTION.md §3.2). Before writing, the author checks
  feasibility — the roadmap entry and the spec sections it cites, and whether what the task
  depends on exists. When authoring cannot proceed it reports `blocked: <reason>` as the first
  line and changes nothing; the run is then `blocked` (exit 3) with the reason in the run log
  and on stderr. AIDT reports, never repairs, what the blocked run can see it left behind:
  an uncommitted change under the task-prompts directory, and a branch that appeared during the run
  (probed before and after the author stage, so a pre-existing branch is never blamed on the
  run). The author stage itself stays `succeeded` — it exited 0 with a valid report; it is the
  run that is blocked.
- Immediately after the author, the workflow measures the produced prompt against the
  conciseness budget (80–120 lines, <15KB; ~150 lines for larger tasks): it always prints a
  `budget:` count, warns naming the offending requirement, and refuses under `--strict` before
  the review loop (H11).
- `P2` receives `$1=<task-prompt-file>` and a pointer to its own evidence bundle
  (`<run_dir>/stages/<stage>.evidence.md`: prompt path, roadmap entry, cited headings,
  prerequisite tick state, gate commands, base revisions); a missing bundle degrades to the
  earlier behaviour, never an error (H3). The gate-commands element is each conventions
  source's section under `## Gates`/`## Gate commands` — prefix-matched, so a suffixed
  canonical heading still counts — or under the target's configured `gates_heading`, joined
  in D16 order; with no source, no recognised heading, or only an unrecognised gates-like
  heading it degrades to `unavailable`, which is a normal state and never fails the run
  (C1.2). `aidw doctor`'s advisory `gates heading` WARN is the diagnosis: for each `## `
  gates-like heading neither convention recognises it names the source file and the heading
  and offers the two fixes (rename to `## Gates`/`## Gate commands`, or declare
  `gates_heading`); a bare, suffixed or declared heading is silent, and it is a WARN, never a
  FAIL, so a repo that only degrades still exits 0. Rounds after the first also receive a delta brief —
  the previous review plus the prompt diff since it (H2).
- `P2a` uses the `task-review-fixes` prompt; it receives `$1=<task-prompt-file>` and, per
  finding, that finding re-rendered in the reviewer's own block format. AIDW runs one fix stage
  per **blocking** (`must-fix`/`should-fix`) finding so progress is reported per change, and
  batches every non-blocking `could-fix` finding into a single stage so those cost one
  invocation instead of one each. When the review does not parse into findings — or any block
  is malformed — it falls back to a single stage carrying the whole review text. Every fix
  stage's input prompt is snapshotted to `<run_dir>/stages/<stage>.prompt.md` first (H5).
- After each fix batch, one `task-review-reconcile-N` stage runs on the `task-fixer` agent,
  before the next review. It carries the whole review plus the batch's combined diff and
  repairs cross-section contradictions and any finding the batch left unaddressed; one stage
  per batch, never per finding. A round that approves runs none — unless that `Approve` carries
  `must-fix`/`should-fix` findings, which is a contradiction and fails closed (M2).
- At most `max_revisions` review rounds run (default 3, overridable per run with
  `--max-revisions <n>`; precedence CLI flag > target config `max_revisions` > 3), and fix
  batches run only for the first `max_revisions - 1` of them. The **last** round is review-only
  — the terminal review — so a review is always the last stage for a non-approving prompt and
  no fix is ever accepted without being reviewed. A residual `Request changes` after the
  terminal review fails closed: the run is `BLOCKED` (exit 3), the last review's findings are
  printed for a human to settle, and the verdict-bearing exit records the
  `approve-task-prompt` gate `denied` with mechanism `review-loop` (H7) — the earlier "no gate
  is recorded" wording was stale phase-02 text, and H1.3's blocked-run continuation keys on
  exactly that record. The old `assumed_ok` / `no further review — accepted` acceptance path
  is gone. A `Blocked` verdict short-circuits earlier with the same exit-3 outcome and its own
  "a human must settle it" message.
- A blocked run's forward path is §9.4's: `--resume` runs **one** further cycle under an
  extended budget — a fix batch for the recorded round's findings, its reconcile, then a
  review that is again terminal — and `--from-prompt <path>` re-runs the loop from
  `task-review-1` over operator-supplied content. Neither re-authors, neither changes the
  loop's shape, and neither is a larger default budget.
- Every verdict-bearing exit records the `approve-task-prompt` gate with a per-round summary —
  rounds run, findings per round, fixes per round, final verdict, and whether any fix ran after
  the last review — in the gate `detail`, `run.log` and stdout (H7).
- Output artifacts: `task_prompt_path`, `branch`, `task_review_verdict`, `task_review_findings`.

### 8.2 `aidw implement <task-prompt-path> [--pr <n>]`

```
preflight (target config + compatibility, declared stage-list validity,
           the task branch's worktree is located, no other run active in it)
  → I1 impliment-task                 (agent implementer, session shared)
  → I2 test                           (agent tester, fresh)
  → I3 update-traceability            (agent implementer, shared)  [repo-optional; after I2]
  → I4 update-architecture            (agent implementer, shared)  [repo-optional]
  → I5 record-implementation-results  (agent recorder, fresh)      SYNC POINT
  → I8 summarize-implementation-results (agent recorder, fresh)   read-only summary
  → I9 write-integration-test-guide   (agent recorder, fresh)      human-run guide, runs nothing
  → I7 update-roadmap                 (agent recorder, fresh)      roadmap tick, verified
  ◇  approve-implementation-pr
  → I6 pr                             (agent pr-publisher, fresh)
  …  any repo-added stages the repo declared, in the declared position
```

- Branch setup is Python-owned here too: `implement` **locates** the task branch's worktree
  (`git.worktree_for_branch`); it never creates a branch. When the worktree is missing it
  prints the exact `git worktree add` command and refuses (exit 4) without creating anything.
  It does not require the invoking worktree to be the task worktree; the located tree is
  re-resolved into the target and every agent cwd.
- The target config is resolved and checked before any stage: `schema_version` newer than the
  toolkit understands, an unsatisfied `requires_toolkit`, an invalid or illegal stage list, and
  a missing configured read-path are each a refusal (exit 2) with named issues — never a silent
  fallback to defaults.
- Ordering: the test stage runs before traceability (traceability cites the test names the test
  stage may add), and architecture runs after implementation and before the record sync point.
- **`--dry-run` creates no run** (W1.2, §9.4): it prints the plan it always printed — every stage
  in its run position with its resolved agent and model, the planned
  `approve-implementation-pr` gate, and the planned worktree/branch-setup command when the task
  worktree is missing — and writes nothing: no run directory, no `state.json`, no `run.log`, no
  `prompts/<stage>.rendered.md`, no stage record, and no run id (the plan prints none, because
  there is no run to name). It still takes the one-run-per-worktree lock (§9.1), so a peer run in
  the worktree is refused (exit 4) exactly as in a real run. A run that never invoked Pi is
  therefore **not resumable**, enforced structurally rather than detected: no such run exists.
- `I3` carries **`when=WHEN_PATHS_CHANGED`** (S1.1, Z11): a **path-scoped** stage condition the
  workflow evaluates itself, in the same place and on the same two dispatch paths as `I7`'s
  evidence check (`execute()` and the `--parallel` member filter), before `run_stage` is
  invoked. The token joins the `when=` vocabulary and is **carried, never expanded away**
  (`_expand_static` still omits only on `when=findings`), so `plan_stages`, `build_plan` and
  `--dry-run` plan `I3` in its run position and a dry run evaluates nothing. For `I3` the
  paths are only the repo's declaration — the optional per-stage `when_paths` list of
  repo-relative prefixes in `workflows.<name>.stages[]` — with no toolkit default, because a
  hardcoded path set would be a product literal (§7.1, Z11): an **absent or empty**
  `when_paths` makes the stage **unconditional**, which is today's behaviour. The stage runs only
  when the change set — `git.changed_paths` against `BASE_DEFAULT` plus `git.untracked_paths`,
  with the run's state root excluded, i.e. the change set `I7`'s evidence already measures —
  touches one declared prefix, where "touches" is `path == prefix or
  path.startswith(prefix + "/")` after `verification.normalise_ignore` canonicalises the
  declaration. A withheld stage is a **cost-control skip, not a gate verdict**: it is recorded
  `skipped` through `runner.record_skipped` (agent and model resolved the same way `run_stage`
  resolves them, `error` unset, the reason in `SKIP_REASON_KEY` naming the declared prefixes),
  with no `state.status`/`state.resume` write, and the run continues. "Cannot prove" **runs**
  the stage: `changed_paths` returning `None` (an unresolvable base) is not "no changes", and
  only a real empty change set skips. `when_paths` is validated fail-closed on load (§12.1): a
  non-list value is one `ERROR` and the field is dropped, and each bad entry (a non-string, an
  absolute path, `.`, `..` or empty) is one `ERROR` naming its own dotted entry path and is
  dropped while parsing continues.
- `I3` maintains the repo's traceability artefacts and **never** edits anything under
  `paths.roadmap_dir` (W1.1, Z13): that tree is `I7`'s alone, and `I7`'s exact-flip
  postcondition (`I7` below, §17 Z13) cannot be reconciled with a second editor, so a repo whose
  only candidate artefact is the roadmap gets **no** `I3` edit and reports "None for
  traceability" — a valid outcome, never a licence to adopt the roadmap. The rule is stated in
  `prompts/update-traceability.md` and declared in the repo's `aidw/conventions.md` (§12.1),
  which reaches `I3` because `update-traceability.md` is one of the five
  `aidw/prompts.py:CONVENTIONS_PROMPTS`.
- `I4` carries the **same `when=WHEN_PATHS_CHANGED`** token (S1.2, Z12), with a registry-default
  trigger set: `StageDefinition.when_paths` (and its `PlannedStage` twin) defaults to the
  **prefix** `docs/architecture`, which is D17's literal `architecture_dir` default — not the
  repo's resolved `paths.architecture_dir`, and not the roadmap's informal glob
  `docs/architecture/**` (the matcher is prefix-based, so a glob would match nothing). A
  repo-declared `when_paths` **replaces** that default rather than merging with it (the S1.1
  override rule, unchanged): a repo that names diagram inputs should re-list
  `docs/architecture` itself if it wants the output directory watched, and a repo with a custom
  `paths.architecture_dir` must declare its own path set or `I4` skips perpetually. The
  loader's absent-vs-empty distinction survives onto `StageSpec.when_paths`: absent keeps the
  default, while an explicit `when_paths: []` is the one reachable empty set, which makes the
  stage unconditional and makes `aidw doctor` emit a WARN naming `I4 update-architecture` and
  telling the operator to declare `docs/architecture` plus their diagram inputs (a disabled
  `I4`, an absent key, or a non-empty list does not warn). Evaluation adds no matcher: `I4`
  rides `paths_changed_reason`/`withhold_stage` on both dispatch paths, a skip is the same
  `runner.record_skipped` cost-control record as `I3`'s (no `error`, no
  `state.status`/`state.resume` write), and a `None` change set **runs** it.
- `I2` and `I4` touch disjoint file sets (package tests vs the architecture directory). With
  `--parallel`, AIDW runs the target config's `parallel_groups` concurrently in the same working
  tree; run-state writes are serialized by a lock. Without `--parallel` every stage runs
  serially. A group whose members are ordered against each other is a config error.
- `I5` is the mandatory sync point over the fully merged tree; `I6` must see the same tree, so
  the repo's verification gates are run once per tree and cited thereafter (§9.2).
- `I8` is the **read-only summary** of `I5`'s output (X1.1, Z3). It reads
  `<implementation_results_dir>/<branch>/build-results.md` and writes `<branch>/summary.md`
  beside it: it runs no verification gate and re-runs no command (it cites the outcomes `I5`
  recorded), it edits nothing else, and it owns no commit. It is a **core** stage (`I3`/`I4`
  remain the only repo-optional ids), placed immediately after the sync point because there is
  nothing to summarise until `I5` has finished, and before `I7`/`I6` so the summary lands
  uncommitted in the task's own PR. It runs serially between `I5` and `I7` — never in a
  `parallel_group` — and the five-section narrative structure lives in
  `prompts/summarize-implementation-results.md`, with no new config path and no template.
- `I9` is the **integration-test guide** (X1.2, Z6): an instruction document, never an
  execution. It reads `I5`'s `<branch>/build-results.md`, the task prompt under
  `paths.task_prompts_dir` and the branch's changed files through read-only `git`, and writes
  `<branch>/integration-test-guide.md` beside them — a step-by-step procedure a human follows
  to integration-test the change by hand across the surfaces it actually touches. Each
  scenario carries prerequisites, the exact commands or steps, the expected observable result,
  how to tell pass from fail, and any cost/permission/destructive warning; the guide closes
  with the teardown and the honest "could not be exercised in this environment" sections. It
  runs no integration test, no verification gate and no command touching a cloud account, a
  browser or a deployed stack, so §1.3's non-goal holds. It is **core** and unconditional like
  `I8` (`I3`/`I4` remain the only repo-optional ids, and it carries no `when=` token), sits
  immediately after `I8` and before `I7` so it lands uncommitted in the task's own PR, runs
  serially — never in a `parallel_group` — and the four-section structure lives in
  `prompts/write-integration-test-guide.md`, with no new config path and no template. The
  prompt file is deliberately **not** `integration-tests.md`: that is a product prompt a
  target repo would shadow by filename (D14), silently swapping this stage's prompt.
- `I7` is the **roadmap tick**: a core stage (`I3`/`I4` remain the only repo-optional ids, D13)
  that flips exactly one roadmap checkbox. `run()` resolves the entry itself — `load_tasks` over
  the resolved `paths.roadmap_dir`/`paths.roadmap_glob`, read from the located **worktree**, not
  the control root (§8.2's locate, decision K1) — and refuses (exit 2, before the stage) unless
  exactly one `(phase, task)` entry matches, so a duplicate can never be ticked by accident. The
  stage receives the entry's own absolute roadmap file and its task id (`H3.1`, distinct from
  I6's branch-form `task_id` `03-H3.1`), so the prompt names no directory (D15/D17). After the
  stage Python re-reads the file and requires exactly the target line to have flipped
  `- [ ]` → `- [x]` with every other byte unchanged; an already-`[x]` entry is a successful
  no-op (`succeeded`, `artifacts.tick: already` and its `run.log` line — never `skipped`, which
  H3.2 reserves for a tick withheld behind red gates), a real flip records `tick: flipped`, and
  any other edit, a vanished entry or a duplicate fails the stage (§10's O1 precedent: an
  agent's exit 0 is not evidence the write happened). The edit stays uncommitted like every
  pre-I6 stage, so I6 commits it and the tick lands in the task's own PR.
- `I7` carries **`when=WHEN_EVIDENCE_GREEN`** (H3.2): a stage condition the **workflow**
  evaluates instead of the agent, **before `run_stage` is ever invoked** and on both dispatch
  paths (the serial loop and a `--parallel` group member). The condition is carried by
  `stage_registry`/`StageSpec.when`, never expanded away, so `plan_stages`, `build_plan` and
  `--dry-run` still plan I7 in its run position and a dry run evaluates no evidence. Green
  iff `verification.tree_identity`'s identity for the tree the tick edits — computed with the
  **default** `base` (`BASE_DEFAULT`, what `aidw gate run` resolves when the prompts pass no
  `--base`) and with the four resolved document write-targets
  (`implementation_results_dir`, `architecture_dir`, `roadmap_dir`, `task_prompts_dir`) as its
  `--ignore` scope plus the state root as its `exclude` — is not `None`, at least one recorded
  `gate_outcomes` row is for exactly that tree, and **every** such row `passed`. Any other
  verdict withholds the stage: the outcome is a `skipped` stage record naming the failing
  gates (or the absence, with the tree id when one could be computed), `error` unset, one
  `run.log` line, and the roadmap file byte-identical because nothing ran. A skip is a
  success on both paths and leaves `state.status`/`state.resume` untouched — the red gate
  already decided the run — while an already-`[x]` entry under green evidence stays H3.1's
  `succeeded`/`tick: already` no-op. "No evidence" (zero matching rows, or no identity at
  all: an unresolvable base or an over-budget change set) is never green: E4.8 is cite-or-run,
  never assume. Green evidence is **necessary, not sufficient**: the tick is also withheld when
  the task's recorded `<implementation_results_dir>/<phase>-<task>/build-results.md` contains a
  line that names the Done-when and denies it (`aidw.roadmap.find_unmet_conclusion`, Z7 — a
  negation within four words of `met`, markdown emphasis stripped first, padded directory before
  the unpadded form). PR #282 is the case: every gate green *and* a document concluding the
  fixture's contract suite failed, so the tick was a completion claim the run's own recording
  contradicted — and `I7` has no legal repair for it, because its postcondition allows the
  checkbox and nothing else. The verdict withholds, never fails, with
  `roadmap.unmet_conclusion_reason`'s `file:line` as the reason, and `fix` applies the identical
  rule. A missing document is not a contradiction, so a repo that records no build results keeps
  H3.2's behaviour unchanged.
- `I7` is **shared with `fix`** (H3.3): one `StageDefinition` object at module level in
  `aidw.stage_registry` — one id, one prompt, one agent, one name — referenced from
  `implement`'s static `stages` and from `fix`'s `post_loop` half (the `A1` precedent), so the
  two ticks cannot drift. Only the *condition* differs per workflow: `implement` reads its
  recorded gate outcomes (above), `fix` reads its own loop's convergence (§8.4). In
  `implement` the stage stays a static entry, so nothing about its position or its gating
  moves; in `fix` it is emitted from `post_loop` and never from the per-iteration expansion.
- **`I2`'s verdict withholds `I6`** (Q1.1, Z10): the `test` stage exits 0 whether it passes or
  fails — an in-scope `Fail` lives in its final **message**, not in its stage status — so
  `implement` parses the tester's declaration from the recorded `test` `out.txt` after the pre-PR
  stages and **before** the `approve-implementation-pr` gate: a bare `Test verdict: Pass` or
  `Test verdict: Fail` line, and on `Fail` a following
  `Failing in-scope criteria: <comma-separated list>`. The parse follows §8.3's shape
  (`_parse_test_verdict`, fenced code blocks blanked and code-span or heading lines rejected, as
  M1/M3 require); the workflow decides, the agent does not, and the tester's stage still exits 0
  and stays `SUCCEEDED`. A `Fail` for *any* in-scope criterion stops the run with
  `state.status = BLOCKED` and exit 3, records `state.pr["test_verdict"] = "Fail"` plus
  `state.pr["test_failing_criteria"]` (the criteria are best-effort naming — a `Fail` without the
  criteria line is still `Fail`), prints the criteria, and never runs `I6`, so no PR is opened.
  `Pass` proceeds unchanged and records `state.pr["test_verdict"] = "Pass"`. An unparseable
  verdict fails closed the same way, naming the ambiguity: `None`, an out-of-scope `Result: Fail`
  and an `Unverified` criterion never reach this branch or never make the verdict `Fail` —
  `Unverified`, out-of-scope and pre-existing/unrelated criteria stay in the tester's
  per-criterion report (`Scope:`) and only the declaration block is read. `I7` is deliberately
  **not** withheld: the tick runs before this gate (a consequence of the pre-PR position), and
  `I6` is the only committer, so a withheld PR still leaves the tick uncommitted.
  **Resume rule:** the gate reads the recorded stage, not a live run, so a plain `--resume` skips
  the already-`SUCCEEDED` `I2` and re-reads the same recorded verdict — it repeats the stop
  identically while the verdict is unchanged, which is correct, not stuck; re-testing requires
  `--from test` (with `--resume` to stay in the same run), which overrides §9.4's
  completed-stages-never-rerun rule and re-runs `I2` and everything after it.
- `I6` commits the accumulated uncommitted change set, pushes, and opens the PR. AIDT does not
  commit before this stage.
- The build results name the task's pull request at the very top of the document, immediately
  above their `## Summary` section, and that number is the one fact the document cannot know when
  it is written: `I5` runs before `I6`, the only stage that opens the PR. So `I5` resolves it
  read-only (`gh pr view <branch>`) and records `#<n>` plus its URL when a PR already exists — a
  re-run, a resume, or `aidw implement --pr <n>` — and records `not yet opened` otherwise, which
  is the normal case. `I6` replaces that one line with the number `gh pr create` printed and
  commits it, so the delivered document names the PR that carries it. The line lives inside
  `implementation_results_dir`, which every gating stage declares in its `--ignore` scope, so
  recording it invalidates no gate outcome and buys no extra gate; and it is never guessed or
  derived from a branch name, task id or run id — a wrong number is worse than an honest
  "not yet opened".
- Output artifacts: `pr_number`, `pr_url`, `build_results_path`, `changed_files` summary.

### 8.3 `aidw review --pr <n>`

```
preflight (PR exists, targets the base branch, the PR head's worktree is located)
  → R1 code-review                    (agent code-reviewer, fresh, read-only)
  if findings:
    → R2 review-findings-to-github    (agent review-publisher, fresh, no gate)   creates parent + children
  else: report Approved and stop
```

- Preflight is PR-head-driven, not cwd-driven (decision K1): `gh pr view` gives the base and
  head, and the **PR head's worktree** is located (`git.worktree_for_branch`) and re-resolved
  into the target, exactly as §8.2 does. The invoking worktree's checked-out branch is never
  consulted, so a review survives being run from the control root while the PR head is checked
  out in a sibling directory — which is the normal case for the §8.6 chain, whose `implement`
  stage works in the task worktree. A known head with no local worktree is a preflight refusal
  (exit 4) that prints the §3.2 `git worktree add` command; under `--dry-run` it is printed as
  planned output and the plan falls back to the invoking worktree. A single checkout locates
  itself and is unchanged.
- `R1` renders the resolved `code-review` prompt (no variables) and parses the verdict
  (`Approve` / `Request changes` / `Blocked`) and the findings block from the final message
  (§18, M1/M3).
- If `Blocked`, the workflow stops and reports — it does not publish.
- `R1` findings are extracted into `<run-dir>/artifacts/findings.json` (stable `F1..Fn`,
  priority, confidence, evidence, impact, trigger/effect, location, suggested fix). This is the
  wrapper-side equivalent of "findings from the immediately preceding review in this session"
  (decision B2), so `R2` does not depend on session memory.
- `R2` receives `$1=<pr>`; it invokes the bundled `publish_review_followups.py` with the
  manifest. The pointer is the manifest's **absolute** path in the run directory: `R2`'s agent
  runs with the target repo as its cwd, so a run-relative value names a file that does not
  exist there (decision O1).
- `R2` carries a read-only postcondition (§10): after the agent exits 0, `review` re-runs the
  publisher with `--dry-run` and fails the stage unless it now *finds* the parent issue instead
  of planning to create one. An agent that stops, reports a blocker and exits 0 is not evidence
  that the GitHub writes happened (decision O1, the same rule as the approval stage's).
- Output artifacts: `review_verdict`, `findings` (or none), `parent_issue`, `child_issues`.
- Both successful exits write `pr.followups_published` into the run state — `true` only when
  `R2` published a parent issue, `false` for an approving review with nothing to publish — so
  the §8.6 chain can tell them apart by re-reading the state it just wrote instead of asking
  GitHub a second time (decision I2). The failed and blocked exits write nothing; a non-zero
  exit already stops the chain.

### 8.4 `aidw fix --pr <n>`

```
preflight (PR exists, branch exists, its worktree is located, no other run active in it)
  → list open children; show GitHub state
  ◇  approve-followups                 runs the approval stage (agent review-approver)
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
  → I7 update-roadmap                 (agent recorder, fresh)  once per run, shared with implement
     if this run's evidence is green
  → F5 commit-and-push                (agent pr-publisher, fresh) once per run, after the loop
     whenever the loop converged
  → review_followup.py close          (Python, not an agent)   per recorded issue, after F5
```

- Entry gate: the human has already reviewed the published issues **on GitHub**. The approval
  stage is the only place AIDT writes `approve-fix`/removes `decision-pending`.
- One fix per iteration; `F1` processes exactly one issue and the loop re-derives "available"
  via `review_followup.py select`, never by counting. `F1` **records** the fix and writes its
  closing comment body; it does not mark the issue fixed and does not close it (below).
- Re-review uses the **fresh reviewer model** rule; if only one reviewer model is configured,
  AIDT warns and (under `--strict`) refuses.
- Bounded: `--max-iterations` (default 10) prevents an unbounded review→fix→review loop. The
  bundled script's exit 3 (no available child) ends the loop successfully.
- **The post-loop roadmap tick** (H3.3): `fix` runs the **same** `I7 update-roadmap` stage
  `implement` runs (§8.2), once per run, **after** the loop converges — `fix` is where a task
  the review found wanting actually finishes, and no earlier stage of the workflow ever
  touched the roadmap, so a closed task stayed unticked and `aidw tasks --next` kept offering
  it. Three things are load-bearing:
  - the stage lives in a new `WorkflowDefinition.post_loop` half and is emitted **only on
    request** (`expand(..., include_post_loop=True)`), because `expand("fix", …)` *is* the
    per-iteration expansion (`fix.py:_planned_iteration` expands one iteration at a time from
    GitHub state). A stage riding that plan would run — and dry-run print — once per
    iteration, so iteration 1's green tests could claim a task done while an approved
    follow-up was still open, and nothing in the chain can untick;
  - the task id comes from the newest `implement` run's recorded `state.task` for the PR-head
    branch — §8.6's re-read-the-run-state trade-off, never a new `gh` query and never the PR
    title — falling back to reversing `repo.branch_pattern`. The reversal is an anchored
    whole-branch match over `string.Formatter().parse`'s literal/field structure that
    **enumerates every viable `(phase, task)` split** and requires exactly one; zero or
    several splits, or zero or several roadmap entries, skips the stage with a reason. It
    never guesses: `03-H3-3` splits several ways and `roadmap.tick_entry`'s count check
    cannot catch a wrong-but-valid pair. The roadmap is read from the located PR-head
    worktree with the resolved `paths.roadmap_dir`/`paths.roadmap_glob` (design K1, §8.2's
    call), and a run whose branch maps to no entry **skips and still succeeds**, because
    `fix` must keep working on PRs that are not AIDT tasks;
  - the condition is `WHEN_EVIDENCE_GREEN` in the **workflow's** hands, evaluated before any
    `run_stage`, and it is `fix`'s own three-part rule — not a copy of `implement`'s
    gate-outcome rule: green iff (a) the loop ended because `select` returned
    `EXIT_NONE_AVAILABLE` (not `--max-iterations`, a denied gate, an ambiguous or `Blocked`
    verdict — those already stop the run with exit 3/1), (b) every `iter{N}-test` record is
    `SUCCEEDED`, and (c) the last re-review verdict is `Approve`. An **empty** run (the first
    `select` already found nothing, so `latest_verdict` is `None`) is not green: a run that
    closed nothing must not claim the task done.

  Non-green records `aidw.runner.record_skipped` — status `skipped`, the reason in
  `artifacts[SKIP_REASON_KEY]`, no `run_stage` — and leaves the roadmap byte-identical. Green
  runs the stage and applies `implement`'s byte-exact postcondition
  (`implement.settle_roadmap_tick`, the one flip rule: `tick: flipped`/`already`, an
  already-`[x]` box is `succeeded`, never `skipped`). The outcome is recorded in
  `state.pr["roadmap_ticked"]` (`true` on a successful tick, flipped or already) and, on a
  skip or a failed postcondition, `false` plus `state.pr["roadmap_tick_skip_reason"]`. A
  stopped loop records the same skip with the stop as its reason before returning, so a
  stopped run says why it ticked nothing. The tick's own edit is then committed by `F5`
  (below): it is part of the change set the run publishes.
- **The post-loop commit** (05-P1.1, Z9): `F5 commit-and-push` (agent `pr-publisher`, prompt
  `prompts/fix-commit.md`, variables `("{pr}",)`) is the one stage of `fix` that **publishes**
  the run's work. Before it, no stage of `fix` committed, so the fixes (and the tick) stayed
  uncommitted in the PR-head worktree while `F1` closed the follow-up issues as
  `Status: fixed` — the work never reached the PR. (That in-stage close is `05-P1.2`'s defect
  to remove; the close now follows this push, below.) `F5` is core (`STAGE_IDS` gains `F5`;
  `REPO_OPTIONAL_IDS` stays `{I3, I4}`), it rides the same `post_loop` half and the same
  `include_post_loop` request as `I7` (after it), and it carries **no `when=` condition**:
  - its trigger is the loop's **convergence**, not the tick's outcome. `fix`'s green rule
    above stays `I7`'s completion claim only; a converged run whose tick was withheld (Z7's
    unmet conclusion, an empty run, an unresolvable roadmap target) still has real fix edits
    that must land, so gating `F5` on `WHEN_EVIDENCE_GREEN` would reproduce the defect the
    stage exists to fix. `F5` runs after `I7` succeeded **or** was recorded as skipped, for
    any skip reason;
  - the agent executes commit and push — `git add -A`, a conventional-commit subject with the
    task id when known, `git push origin <branch>` (no `-u`, no force) — and Python only
    decides *whether* and verifies *what landed*. `<branch>` is the PR head the preflight
    already resolved (§8.3's decision K1), never `git.current_branch` of the control root,
    which is on `main`; `<branch>` equal to `repo.base_branch` is refused **before** any push;
  - the decision is a four-case table over the tree state *before* the stage and this run's
    own accumulated `closed_issues` (never a `gh` query, never a count of
    `Status: fixed` comments): dirty with ≥ 1 closed → commit and push, then verify and
    record `state.pr["head_sha"]`; dirty with 0 closed → **skip** ("this run closed no issue;
    the working-tree changes are not this run's" — unowned dirt is not `F5`'s to publish,
    §13 preserves unrelated user changes); clean with 0 closed → **skip** (the roadmap's
    successful no-op: no empty commit, no push); clean with ≥ 1 closed → **fail closed**
    (issues were recorded as fixed and there is nothing to push, exactly the untruthful
    state this change removes; the close-after-push ordering below makes it
    unrepresentable: a recorded fix implies a dirty tree, because the fixer's edit is not
    committed until `F5` commits it);
  - a **new commit must exist** before "the push landed" means anything: the workflow
    captures `HEAD` before the stage and requires it to have moved afterwards. The tree is
    dirty by construction on this path, so a real `git commit` always moves it, while a stage
    that stashes or cleans the change set instead of committing it leaves the pre-existing
    SHAs in place — and would otherwise satisfy the comparison and the clean-tree check below
    while losing the fixes (the PR #158 review finding);
  - the pushed proof is pinned without a fetch: after the stage the workflow compares
    `git.rev_parse(worktree, "HEAD")` with `git.rev_parse(worktree, "origin/<branch>")` — a
    successful `git push` updates the remote-tracking ref — and an unequal or unresolvable
    pair, a `HEAD` that did not move, a non-`SUCCEEDED` stage record, a tree still dirty
    afterwards, or the fourth case above each fail the run (exit 1) with a message naming the
    PR and the branch, never a silent success (the O1 precedent: an agent's exit 0 is not
    evidence the write happened).
    `state.pr["head_sha"]` is the **verified remote** SHA, written only when that comparison
    holds; a skip writes `state.pr["commit_skip_reason"]` instead. There is no separate
    "committed"/"pushed" flag — `head_sha`'s presence is the boolean;
  - a **stopped** loop never commits and never pushes (decision D4): every stop path returns
    before the post-loop, and the one `stop()` helper records both `I7`'s and `F5`'s skip with
    the same stop reason. A failed `I7` stage (or a failed tick postcondition) keeps its exit
    1 and `F5` is neither planned nor recorded, because committing a half-applied tick is
    worse than leaving the tree for a human.
- **The deferred close** (05-P1.2, Z9's second half): the issue's exact `Status: fixed`
  comment and its close happen only **after** `F5` has pushed a tree containing that fix.
  `F1` no longer posts the marker and no longer closes in-stage: it leaves the issue `OPEN`
  with the exact `Status: in progress` comment `start` posted — which is also what keeps the
  just-fixed child out of the next `select`, so nothing has to be marked fixed "early" to
  make selection work. Three things are load-bearing:
  - **the body survives the deferral**: `F1`'s variables are `("{pr}", "{closing_body}")`, the
    **absolute** path `<run_dir>/artifacts/iter{N}-closing-body.md`. Absolute for the reason
    `manifest_path` is: `F1` runs with the target repo as its cwd, so a relative path would
    write the body into the worktree and pollute the very diff `F5` pushes. Each
    `closed_issues` entry records that path, so the close passes it back as `--body-file`;
    composing a generic body in Python instead would silently drop the fixer's verification
    results. `closed_issues` therefore means "fixed, **close-pending**" — the D3 table and
    `state.pr["closed_issues"]`/`fix.json` keep reading it as "≥ 1 fix to publish", never as
    "≥ 1 issue already closed";
  - **the close is Python's, not an agent's**: once `run_commit` has proved the push (`HEAD`
    moved, `HEAD == origin/<branch>`, clean tree, `state.pr["head_sha"]` written), the
    workflow runs the bundled `review_followup.py close --pr <n> --issue <n> --body-file
    <path>` — a new subcommand that posts the exact `Status: fixed` comment if it is absent
    (idempotent) and then closes the issue with that body. It resolves the issue by
    `--issue` **alone**: the just-fixed child is in flight, not first-available, so reusing
    `fixed`'s selection step would refuse every close after the first with `EXIT_CONFLICT`.
    `fixed` keeps its in-stage contract by sharing the same close tail — one rule
    (`logic.close_plan`), so the §7.2 strict-equality marker, the
    `review-follow-up`/`approve-fix` label guard, refuse-to-reopen,
    `closing_body_repeats_status` and the post-close verification (exit 1 on a lost label or
    state) cannot drift between the two commands. A missing, empty or
    `Status: fixed`-prefixed body fails the close before any close action;
  - **it fails closed only where a close is pending**: one `close` call per recorded entry,
    never a batch and never a re-derived count, and a non-zero `close` exit fails the run
    (exit 1) naming the PR, the branch and the issue. A run that recorded no entry keeps
    D3's skip contract (no close, exit 0), and an empty run (`select` returned
    `EXIT_NONE_AVAILABLE` first) has nothing to close. A run that recorded an entry with no
    verified push — a `F5` skip, failure or absence — closes nothing and exits non-zero, so
    "reported fixed" without a push is unrepresentable rather than merely unlikely.
- Declared stage lists cover both halves (H3.3): `validate_stage_list` classifies `fix`'s `I7`
  and `F5` as **core** (removal, disable and reorder rules apply; neither is a loop id), so a
  declared `workflows.fix.stages` list must carry both — `[A1, I7, F5]` is the canonical
  shape, with the post-loop ids after every static core id in registry order, and the
  declared plan renders declared static entries, then the loop unchanged, then declared
  post-loop entries.
- `--dry-run` plans the tick **and** `F5` once each, in the final positions, and evaluates
  **no** evidence: it never withholds on green-ness, never ticks, never inspects the tree,
  never commits or pushes, and never withholds `F5` even where a real run would fail the
  fourth case above. An unresolvable target still shows the tick once, as the skip a real run
  would record. Each stage appears once per run — never per iteration — in `state.json`,
  `run.log` and the dry-run plan.
- Output artifacts: `closed_issues`, `latest_verdict`, `iterations`. Since 05-P1.2 each
  `closed_issues` entry also carries the absolute `closing_body` path the deferred close reads.

### 8.5 `aidw approve-followups --pr <n>`

```
preflight (PR exists; `gh` available)
  ◇  approve-followups                 show the open children; human confirms
  →  A1 approve-review-followups       (agent review-approver, fresh)
```

- Extracts the approval step that `aidw fix` performs at its entry, so a human can apply the
  GitHub decision without starting the fix loop.
- The prompt receives `$1=<pr>` and performs every write through the bundled
  `review_followup.py` script (adds `approve-fix`, removes `decision-pending` on open children;
  closed children are untouched). It carries the read-only approval postcondition (§10).
- Preflight only checks that `gh` is available and the PR exists; it does not require a
  particular branch or PR base.
- Output artifacts: the run's `pr` record and the `approve-followups` gate decision.

### 8.6 `aidw run <workflow>` (orchestrator)

`aidw prompt`, `aidw implement`, `aidw review`, and `aidw fix` are themselves the orchestrators. A
convenience chain `aidw run task-to-pr <phase> <epic> <task>` runs `prompt` then `implement`, and
`aidw run review-and-fix --pr <n>` runs `review` then `fix`, failing forward per §10.

Exactly one of the chain's workflows ticks the roadmap, and the chain can tick it **once**
(H3.3). `implement` runs `I7` in its static chain behind its own green-evidence condition
(§8.2) and `fix` runs the same stage from its post-loop half behind its own convergence rule
(§8.4), so a cycle whose implementation was already ticked ends with `fix`'s tick as H3.1's
**`already` no-op** rather than a second claim — `already` is `succeeded` and leaves the file
byte-identical, and nothing in the chain can untick. A cycle that ended before `implement`'s
evidence was green leaves the box open for `fix` to tick, and one that `fix` stops early (a
denied gate, `--max-iterations`, a failed stage) records why it ticked nothing rather than
claiming completion. The chain itself adds no bookkeeping: each workflow owns its own tick
outcome (`state.pr["roadmap_ticked"]` in `fix`), and exactly-once follows from the
postcondition both share.

`aidw run prompt-to-fix <phase> <epic> <task> [--pr <n>]` runs the whole cycle in the same
order those four orchestrators already define — `prompt` → `implement` → `review` →
`approve-followups` → `fix` — so each stage keeps its own preflight, gates, state and
resumability, and the chain stops at the first non-zero exit. The PR number comes from the
newest `implement` run's recorded state (`pr.number`), with `--pr <n>` as an override and
`0` as the planned placeholder under `--dry-run` (a dry run opens no PR). To make the cycle
unattended, the chain adds `approve-followups` to the `fix` stage's skip set and announces
it (`chain:  auto-approving \`approve-followups\` …`, decision I1). That is the only gate it
auto-approves: `approve-implementation-pr` and `approve-fix-pr` keep normal
`--yes`/`--gate-default`/interactive semantics, and `--deny-gates approve-followups` still
refuses the auto-approval because `deny` is checked before `skip` in §6.

Because both chains run `prompt` first, they forward `--allow-incomplete-prereqs` to that
stage's own preflight (decision H13). The flag still does exactly one thing — turn L1.2's
ordering refusal into a warning that names every skipped predecessor (§8.1) — so a chain
invoked without it keeps the gate, and `review-and-fix` ignores it because it runs no
`prompt`.

A chain whose review published **nothing** ends gracefully (exit 0) after that review
instead of running the fix loop into its entry postcondition (decision I2): with no
review-follow-up parent issue there is nothing to approve and nothing for the fixer to fix,
and `fix`'s entry stage fails closed with
`could not read approval state (approve --dry-run exit 2): … No review-follow-up parent
issue found`. After `review` succeeds, the chain reads `pr.followups_published` over every
`review` run of that PR: any `true` keeps the loop (an earlier round's follow-ups outlive a
later "nothing to publish" review), only `false` ends the chain with
`chain:  review published no follow-ups …` / `chain complete.`, and an unreadable or absent
record keeps the pre-I2 behaviour of running `fix`. Ending early also means the
`approve-followups` auto-approval is never announced or recorded for a stage that does not
run. `aidw fix` invoked directly is unchanged.

---

## 9. Run state, artifacts, and resumability

### 9.1 Layout

Run state lives in the **state root**, keyed by repo slug, never in a working tree
(EXTRACTION.md §3.10, D18, R8). The run directory is
`<state root>/<repo-slug>/runs/<run-id>/`, with a branch lock at `locks/<branch>.lock`:

```text
<state root>/<repo-slug>/
├── runs/
│   └── <utc-stamp>-<task-or-pr>-<workflow>/
│       ├── state.json
│       ├── run.log
│       ├── stages/
│       │   ├── impliment-task.jsonl      # raw pi --mode json stream
│       │   ├── impliment-task.out.txt    # final assistant message (human-readable)
│       │   ├── impliment-task.meta.json  # argv, model, prompt source, session id, duration, exit, usage
│       │   ├── task-review-1.evidence.md # per-review/fix evidence bundle (H3)
│       │   └── task-review-fixes-1-1.prompt.md  # fix-stage input snapshot (H5)
│       ├── artifacts/
│       │   ├── task-prompt.path
│       │   ├── findings.json
│       │   └── review-manifest.json
│       └── prompts/
│           └── impliment-task.rendered.md
└── locks/
    └── <branch>.lock                     # one run per branch/worktree
```

- `state root` = `$AIDW_STATE_DIR` if set, else `<workspace root>/.aidw/state`, else
  `~/.aidw/state`; `<repo-slug>` is `owner-name` from `origin` when available, else the
  workspace-root basename, so a shared fallback state root cannot collide between repos.
- In the supported bare + sibling-worktree layout the state root is outside every working tree,
  so `git worktree remove` can never delete a run. AIDT **warns** when the state root falls
  inside a working tree (the single-checkout case), and **fails** when the workspace root is
  itself a registered worktree of the same repository — that layout would register the state
  root inside a prunable tree (`aidw/layout.py`).
- `locks/` holds exactly one lock per **resolved worktree path** (`aidw/lock.py`). The key is
  the worktree path, not the branch: EXTRACTION.md §3.10's `<branch>.lock` is shorthand that is
  only valid under the one-branch-one-worktree fact, and a detached-HEAD worktree has no branch
  at all. The lock is taken immediately before the run record is created and released on every
  exit path; a live peer in the same worktree is refused with exit 4 and writes no run state.
  A `--dry-run` takes the same lock — so a peer is refused with exit 4 there too (§19 item 8) —
  and then creates no run at all (§9.4).
- Three different serializations exist and must not be conflated: this lock is **one run per
  worktree**, held for the whole workflow and cross-process; `runner._STATE_LOCK` serializes
  `state.json` writes between concurrent *stages inside one run* (`--parallel`) and is
  in-process only; and `<run_dir>/state.json.lock` (§9.2) serializes the read-modify-write of
  one run's file between the workflow process and every `aidw gate run` subprocess it spawns.
  A worktree-keyed lock in that third position would refuse every gate subprocess, because the
  workflow holds the worktree lock for its whole lifetime.

### 9.2 `state.json` (schema)

```json
{
  "schema_version": 1,
  "totals": { "input_tokens": 193, "output_tokens": 16, "cost_usd": 1.23 },
  "run_id": "20251106T090000Z-00-E9.1-implement",
  "workflow": "implement",
  "created_at": "2025-11-06T09:00:00Z",
  "repo_root": "/home/me/aidt-workspace/00-E9.1",
  "toolkit_version": "0.1.0",
  "config_schema_version": 1,
  "config_hash": "sha256:9f2c…",
  "git": { "branch": "00-E9.1", "base": "main" },
  "task": {
    "phase": "00", "epic": "E9", "task": "E9.1",
    "prompt_path": "docs/task-prompts/00-E9.1-prompt.md"
  },
  "pr": { "number": 42, "url": "https://github.com/…" },
  "strict": false,
  "stages": [
    {
      "name": "impliment-task",
      "agent": "implementer",
      "model": "<provider/model>",
      "session_id": "aidw-20251106T090000Z-00-E9.1-implement-implementer",
      "status": "succeeded",
      "started_at": "...", "ended_at": "...",
      "exit_code": 0,
      "stop_reason": "stop",
      "attempts": 1,
      "duration_seconds": 812.4,
      "generation_seconds": 0.5,
      "tool_seconds": 780.1,
      "tool_breakdown": { "bash": 700.0, "read": 60.1, "edit": 20.0 },
      "output_tokens_per_second": 32.0,
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
  "gate_outcomes": [
    { "key": "suite", "command": ["uv", "run", "--frozen", "pytest"],
      "tree": "<content-tree id>", "status": "passed", "stage": "record",
      "at": "...", "exit_code": 0, "duration_seconds": 391.2,
      "summary": "412 passed", "ignored": ["docs/implementation-results"] }
  ],
  "status": "succeeded",
  "resume": { "next_stage": null }
}
```

`totals` is derived on every save: it sums the `usage` counters of all recorded stages (with a
stage's `cost_usd` as the fallback when a record has no `usage`), giving the run's combined
input tokens, output tokens, and cost.

**What produced the run** (E8.2, EXTRACTION.md §3.11, D9/D10) is recorded alongside the state
schema:

- `toolkit_version` is always `aidw.__version__` — never a `git`/`uv` shell-out or a
  `pyproject.toml` parse.
- `config_schema_version` is the **config** schema version that resolved, `None` for a repo with
  no `aidw/` folder (a config file must declare it and it has no toolkit default). The bare
  `schema_version` key above is the **state** schema, and `load` refuses a mismatch on it, so
  the two are deliberately named differently.
- `config_hash` is `sha256:<hex>` over `json.dumps(resolved.to_dict(), sort_keys=True)` — the
  same object `aidw config show --json` prints, so an operator can reproduce the fingerprint.
  Hashing the *resolved* mapping (each leaf carries its provenance) is what makes it mean "the
  config this run used": a declared `max_revisions: 3` fingerprints differently from the
  default `3`.
- All three are **additive at the same `SCHEMA_VERSION`** and default to `None`, so a
  `state.json` written before them still loads. `aidw exec` records `toolkit_version` only,
  because it resolves no target config.

`task` is a free-form mapping and grows the same additive way (H1.3, design §9.4). Besides the
run's roadmap coordinates it carries the blocked-run continuation's provenance: the stage
records give `phase`/`epic`/`task`/`title`, a `--resume` fix-cycle continuation adds
`effective_max_revisions` (the extended budget it ran the loop under: recorded review count +
1, so the extension is visible rather than inferred from two gate records), and a
`--from-prompt` continuation adds `from_prompt` = `{"path": <the supplied path>, "hash":
"sha256:<hex>"}` over the bytes it copied onto the canonical prompt path — the `config_hash`
convention, reproducible with any sha256 tool. Both are per-run values, not schema fields, and
`SCHEMA_VERSION` does not move: a `state.json` written before them still loads, and a run may
hold both a stale `effective_max_revisions` (from an earlier fix cycle) and a `from_prompt`
entry, which is why each continuation's gate `detail` reports the budget it actually ran
under.

`gate_outcomes` records every `aidw gate run <key> -- <command>` verification result with the
**content-tree identity** it ran against, its origin (`stage`, `at`, `command`), its status,
exit code, duration, a one-line summary and the repo-relative prefixes it declared it cannot
read. A later stage asking for the same key against identical content is handed
`reused: gate 'suite' passed for tree <id> at <time> by stage '<stage>' (<summary>)` instead of
re-running it. The identity deliberately excludes `HEAD` (the PR stage commits the very tree it
gated); anything unprovable — no resolvable base, no run to cite, a different command under the
same key, a differently declared scope, a previous failure — means the gate executes. Human gate
decisions live in `gates`; the two lists are different questions and are never merged.

**Two writers, one file, one lock** (H0.1). `state.json` is written by two kinds of process:
the workflow (`aidw/state.py:save` — the whole state) and each `aidw gate run` subprocess a
stage's agent spawns (`aidw/state.py:append_gate_outcomes` — outcomes only). Both hold the
per-run lock file **`<run_dir>/state.json.lock`** — `fcntl.flock(LOCK_EX|LOCK_NB)`, descriptor
opened fresh per acquire, file never unlinked, colocated with `state.json` and deliberately
*not* under `locks/` (§9.1's non-conflation) — around their whole read-modify-write, and both
publish through a temp file created in the run directory, fsynced, then `os.replace`d. Readers
therefore take no lock at all and never see a half-written file. Neither writer drops the
other's rows: `save` reloads inside the lock and merges the `gate_outcomes` already on disk
into the payload it publishes, and the gate path reloads and appends rather than rewriting the
run, so a stage record written while a gate command was executing survives it. The merge
collapses only byte-identical rows; two outcomes that differ in any field both survive, because
two processes that both ran a command are two pieces of evidence (T1). An unreadable
`state.json` is never overwritten — the write fails closed rather than deleting evidence nobody
could parse.

The per-stage throughput fields are stored, not aggregated: two stages of the same model in one
run stay separate. `generation_seconds` is the time Pi spent generating assistant messages,
measured from the monotonic instant AIDW read each event (Pi timestamps nothing itself); prompt
prefill and every tool call fall outside it, so `output_tokens_per_second` is generation speed
rather than effective wall-clock throughput. `tool_seconds` is the complementary measure: the
sum of Pi's per-call `durationMs` recorded on `tool_execution_end`, or, for a stream that
predates that field, the interval between each `tool_execution_start` and its end; prompt
prefill and assistant generation are excluded. `aidw runs show` prints a `timing:` line per stage
that attributes the whole stage wall time: `tools` is `tool_seconds` and `ai` is the remainder —
model prefill, generation, provider wait and subprocess startup — so the two figures add up to
`duration_seconds` instead of leaving the reader to wonder where the rest went. A `tools:` line
then breaks `tools` down by name (longest first, summed from the same calls, so the parts add up
to the total), showing which tool actually consumed the time. Because the persisted JSONL
carries `durationMs`, the show command recovers both figures for a run recorded before the
fields existed (display-only; the run is not rewritten). Each field is `null` when its window
was not measured; they are additive to the existing schema — `schema_version` does not move — so
runs written before the fields existed still load.

A stage that records token spend at a zero cost is a **pricing gap, not a free run**: Pi
computes cost from the resolved model's price table, so a `models.json` `models` entry that
shadows a catalog model without carrying `cost` (the fix is a `modelOverrides` entry, which
merges instead of replacing) reports `$0.0000` for real tokens and leaves the agent's
`max_cost_usd` ceiling unenforceable. AIDW warns once per such stage — `WARN stage <name>: …` in
`run.log` — and repeats it as a `note:` line in the stage block (§9.3). Local providers
(`ollama`) are exempt, because there zero is the truth.

`stages/<name>.meta.json` carries the same counters — including `generation_seconds` and
`output_tokens_per_second` — plus the prompt provenance — `stage`, `agent`, `prompt_source` (the
prompt file the stage was rendered from: a toolkit `prompts/*.md` file, a target
`aidw/prompts/*.md` override, or an absolute path when `aidw exec` was given one) and
`rendered_prompt` — so "which prompt did this stage actually use?" is answerable from the
stage's own metadata.

It also carries **`attempts_detail`** (H1.1): one entry per Pi attempt that actually ran, each
recording that attempt's own `session_id`, `exit_code`, `stop_reason`, `usage` and
`generation_seconds`/`tool_seconds`. A retry overwrites the stage JSONL and the meta's `argv`
still describes the first attempt, so without this list the first attempt's cost would be
unrecoverable; `attempts` is its length. Usage and timing are captured before a retry fires and
therefore stay the **sum** of the attempts that ran — never summed tokens over one attempt's
generation seconds — so `output_tokens_per_second` remains a true rate on a retried stage.

A stage record also carries **`rendered_chars`** (H2.1): `len(rendered)`, the character count
of the very string written to `prompts/<stage>.rendered.md`, so "how big was this prompt, and
what did it cost in context?" is answerable from one record beside `usage.input_tokens`. It is
recorded for the `prompt` review loop's head stages (`task-review-<n>`) only, and only on the
real-run path: `run_stage` renders and records every stage and also serves `--dry-run`, so an
unscoped write would put a size on author/fix stages and change the dry-run plan. Everywhere
else it keeps its `None` default and serialises as `rendered_chars: null` — **additive at the
same `schema_version`** (the `stop_reason`/`attempts` precedent), so an older `state.json`
still loads. One `run.log` line names the stage and the size.

### 9.3 Stage reporting

Every stage prints a block to stdout when it finishes, derived from the stage record so the live
output and the recorded evidence cannot drift apart:

```text
stage:  task-review-1 [succeeded] model=openrouter/meta/muse-spark-1.3 132.3s cost=$0.0287 32.0 out-tok/s
        usage: total=50.6k in=193 out=16 cache_read=50.4k cache_write=0 reasoning=0 cost=$0.0287
        out:   <state root>/<repo-slug>/runs/<run-id>/stages/task-review-1.out.txt
```

The head line's `out-tok/s` is `usage.output_tokens` divided by `generation_seconds`; it is
omitted for a stage that generated nothing. `aidw runs show` prints the same value from
`state.json`.

An unpriced stage (tokens recorded, cost `$0.0000`) adds a `note:` line so the gap is explained
next to the zero that hides it:

```text
stage:  I2 impliment-task [succeeded] model=openrouter/deepseek/deepseek-v4.1-flash 248.9s
        usage: total=936.0k in=42.7k out=19.2k cache_read=874.0k cache_write=0 reasoning=12.2k cost=$0.0000
        note:  936.0k tokens with $0.0000 cost — openrouter/deepseek/deepseek-v4.1-flash has no pricing; check models.json (a "models" entry replaces catalog pricing, a "modelOverrides" entry merges)
        out:   <state root>/<repo-slug>/runs/<run-id>/stages/impliment-task.out.txt
```

A workflow prefixes its own stage id (`stage:  I2 test [succeeded] …`), a failed stage reports
`error:` instead of usage, and `aidw runs show` prints the same fields from `state.json`. Review
stages always point at their `.out.txt`, so the verdict text is one path away. A task-prompt
review that requests changes reports the parsed finding count and a per-finding fix line, for
example `verdict: Request changes — 3 findings (2 should-fix, 1 could-fix)` followed by
`fix 1.1/3: …` for each blocking finding and one `fix 1.3/3: 2 could-fix findings combined` stage
for the rest.

**While a stage runs**, an interactive terminal shows a live progress line on stderr, fed by the
JSON events Pi streams (never by the transcript, which stays on stdout):

```text
▶ task-review-1 (task-reviewer) model=openrouter/meta/muse-spark-1.3
  ..*+.+.+.**
```

`.` is a heartbeat — nothing new for 10s, Pi is still working; `*` is a completed model response;
`+` is a tool call. A dot per response alone would still leave multi-minute silences on the long
review stages, which is why the heartbeat exists. Progress is enabled only when stderr is a
terminal, so CI logs and piped runs stay clean; `--progress` / `--no-progress` overrides that.
Under `--parallel` the two concurrent stages' lines interleave.

`status` ∈ `running | succeeded | failed | blocked | aborted`, and a **stage** record adds
`skipped` (§9.3's next paragraph; a run is never `skipped`). `resume.next_stage` is set when a
stage fails, so `--resume` continues from that stage.

A stage record also carries **`skipped`** (H3.2): the stage was **withheld before Pi was
invoked**, because the workflow's own condition said no — today I7's `WHEN_EVIDENCE_GREEN`.
It is neither `failed` (nothing went wrong) nor a successful no-op (H3.1's `already` tick did
run): the stage block reads `stage:  I7 update-roadmap [skipped]` followed by
`skipped: <reason>` — never `error:`, which would render as a failure — and the reason is
`StageRecord.artifacts["skip_reason"]` (`aidw.state.SKIP_REASON_KEY`), so it is observable
from `state.json` and `run.log` without a transcript. The record still names the stage's
agent and its resolved `model`, because a skip answers "which stage did not run, on which
agent, and why" — `aidw runs show` prints the status and the record like any other, so a
skip is never read as a failure. `skipped` is additive at the same `schema_version` (a
`state.json` written before it never contains it and still loads), and it does not affect
resumability: it is not a success, so a `--resume` re-evaluates the condition instead of
treating the stage as done.

### 9.4 Resumability

- `aidw implement --resume` and `aidw prompt --resume` read the latest run for their own workflow
  and the derived branch, print the completed stages, and ask before continuing (skippable with
  `--yes`). `aidw fix` has no resume in v1.
- Completed stages are never re-run implicitly. `--from <stage>` forces a stage (and everything
  after it) to run again, recording the override.
- Gates already approved are not re-asked; a gate can be re-decided with `--gate <name> --yes|--no`.
- `aidw prompt --resume` continues a **failed** run at `state.resume.next_stage` in the same
  worktree and the same run id, appending later stages to the same `state.json`. The loop's
  in-memory state is reconstructed from the recorded stage records — the review index and revision
  count from the stage names, each round's fix batch re-parsed from that round's recorded review
  `.out.txt` — so no author or review stage is re-run to recover them. A fix batch's `FixBatch` is
  therefore always a real re-parse (reconciled against the recorded `task-review-fixes-*` names),
  never inferred from names, and the pre-fix diff baseline, which is not persisted, degrades the
  brief rather than being fabricated.
- `--from` is validated against the prompt loop's stage-name grammar bounded by the resolved
  `max_revisions` before any side effect (exit 2), and it is the explicit override for both
  layers: with `--resume` it takes precedence over `next_stage` in the same run id, without it the
  invocation is a fresh run with a new run id.
- A **blocked** run has no `resume.next_stage` (§9.3), and its forward path is scoped by the
  shape of the block (H1.3). A **review-loop** block — the run's latest `approve-task-prompt`
  gate is `denied` with mechanism `review-loop`, i.e. the terminal `Request changes`, a
  `Blocked` verdict, or M2's approve-with-blocking-findings — continues with `--resume`: the
  same loop, in the same run id and worktree, under an extended budget of
  `state.task.effective_max_revisions` = recorded review count + 1. That value makes the added
  `task-review-{N+1}` the `max_revisions`-th review, so it is terminal and L4.1 holds in the
  continuation: the recorded round's findings get their fix batch and reconcile, the added
  review decides (an `Approve` runs the same post-loop gate block and commit a fresh run does;
  a residual `Request changes`/`Blocked` fails closed, exit 3), and each further `--resume` is
  its own explicit operator decision granting one more round — never a larger default budget.
  The budget is recorded in `state.task` (§9.2) so the extension is visible, and each
  continuation's gate `detail` reports the budget and round count it actually ran under.
  An author-``blocked:`` run (no recorded gate) and a human-gate denial keep the exit-3 refusal
  naming the blocked shape's recorded reason: neither holds a terminal review whose findings
  could drive a fix batch, so `--resume` is no forward path for them and they never silently
  re-author.
- **`--from-prompt <path>`** continues either blocked shape: it copies the supplied content onto
  the canonical `docs/task-prompts/<phase>-<task>-prompt.md` in the run's worktree (so `rel`, the
  evidence bundle and the commit keep working) and records `state.task.from_prompt =
  {"path": <supplied path>, "hash": "sha256:<hex>"}` over those bytes. It applies the
  control-tree preflights (base branch checked out, clean tree) and skips the run-scoped ones,
  exactly as a resume does. The re-run is a **fresh** loop over new content: forced past the
  skip machinery by an internal position bound at `task-review-1` (never by `--from`, which is
  refused alongside it), it runs under the resolved `max_revisions` and supersedes stages by
  name while keeping the records of rounds it never reaches. It is blocked-run-only (exit 2
  on a missing or non-blocked run), it alone is a takeover, and when given with `--resume` it
  takes precedence over the fix cycle. A dirty canonical path refuses exit 4 before the copy
  (§13): a blocked run may have left the very edits it would overwrite. A blocked continuation
  whose worktree no longer exists refuses exit 4 naming the run, the missing worktree and the
  re-author command, never re-authoring silently.
- The one-run-per-worktree lock (§9.1) is held across a resume, keyed on the reused worktree path.
  A run-scoped preflight — the base-branch fetch (§8.1) and the roadmap predecessor check — belongs
  to the run being resumed and is not repeated; the worktree identity and the lock are.
- A `--dry-run` **creates no run state**, in every workflow (`implement`/`prompt`/`approve`/
  `review`/`fix`) and in `aidw exec`: no run directory, no `state.json`, no `run.log`, no
  `prompts/<stage>.rendered.md` and no stage record, so the runs tree is byte-identical before and
  after and a later `--resume` can never attach to a run that invoked no Pi. The plan works
  against an in-memory run record (its run id feeds the session names only and is never printed)
  (`aidw.log.NullLogger`) and prints nothing that would name unwritten state: no `run:` line, no
  `rendered:` line (`aidw exec`), and `state.PLANNED_RUN_DIR_TEXT` (`<run dir>`) where a real run's
  directory would appear — `review`'s manifest line and publisher argv, `fix`'s rendered manifest
  and `{closing_body}`. The plan's own run record is `state.planned_run(...)`, which is
  `create_run`'s exact signature with the literal `state.PLANNED_RUN_ID` (`<planned>`) and no
  `save`.
- A `--dry-run` is always the fresh-plan baseline (the author plus `task-review-1`): it never takes
  an existing run over, prints no completed stages, asks nothing and locates no worktree, while
  `--from` and `--from-prompt` are still validated (a missing supplied file is exit 2), while the
  still-running guard and the scoped-out blocked refusals still apply — deliberately not
  gated, so a dry run never plans an author over a blocked run through a route that is no
  forward path for that shape. Over a review-loop block or with `--from-prompt` the dry run
  simply plans the fresh baseline: it never continues the blocked run's id and copies
  nothing.

---

## 10. Error handling

| Condition | Behaviour |
|---|---|
| Pi process exits non-zero | Stage `failed`; state records exit code + tail of stderr; workflow stops (no auto-retry unless `--retry-transient`). |
| Pi exits 0 but reports an in-stream provider error (`stopReason: "error"` or `errorMessage`, e.g. an OpenRouter 402) | Stage `failed` with the provider message; workflow stops. Credit/auth errors are not transient and are not retried. |
| Pi exits 0 but the stage's declared postcondition does not hold (the agent stopped and reported a problem in its final message instead of doing the work) | Stage `failed` with `postcondition not met: …`; the workflow stops. A zero exit only means the agent finished, so a stage whose job is an external change re-reads that state (`StageSpec.verify`, e.g. `github.verify_approvals`, `github.verify_published`) before it can succeed. |
| A stage returns no final message (a review stage included) | One retry in a **fresh session** — the base `--session-id` with a `-retry` suffix — when the attempt exited 0, was not timed out, reported no provider error, and parsed no final text; both attempts are recorded in `stages/<name>.meta.json` (`attempts_detail`) and one `run.log` line names the stage and the first attempt's `stop_reason`, and their usage/timing counters sum onto the stage record. Two such attempts `failed` with a message naming the stage, the final attempt's `stop_reason` and that **both** attempts were truncated; the workflow stops rather than treating it as "ambiguous" and running rework on empty findings. `--no-retry-transient` disables this retry exactly as it disables the transient one, and a provider error (exit 0, `stopReason: "error"`) is never retried. |
| Pi invocation error that looks transient (network/provider 5xx) | With `--retry-transient` (default on for one attempt), retry once after a short backoff; record both attempts. Gate failures are never retried. |
| Stage timeout | `failed`; process group terminated; partial log retained. |
| Cost ceiling exceeded | `failed` with reason `cost_ceiling`; run stops. |
| Gate denied | `blocked`; run stops cleanly, leaving state resumable. |
| The code review returns `Blocked` | `blocked`; findings are still written, publication is not attempted. |
| An `Approve` verdict carrying `must-fix`/`should-fix` findings | `BLOCKED` (exit 3) before any fix stage, a `denied` gate whose `detail` keeps the reviewer's verdict and the per-round counts, the contradiction and findings on stderr, and the prompt left uncommitted (M2). |
| A verdict cannot be parsed | `None` fails closed: `review`/`fix` stop immediately, `prompt` reworks and then ends `BLOCKED` with `verdict=ambiguous` (M1/M3). |
| The task-prompt author reports `blocked: <reason>` | run `blocked` (exit 3); the reason is recorded in the run log and printed to stderr; a branch created during the run and any uncommitted change under the task-prompts directory are reported, never repaired; the author stage itself stays `succeeded`. |
| `review_followup.py` exit 3 (no available child) | Fix loop ends successfully with `closed_issues`. |
| `review_followup.py` exit 1/2/4 | `failed`; wrapper surfaces the script's JSON error and does not work around it. |
| A required prompt or helper script is missing (`aidw prompts check`) | `prompts check` fails; a workflow stage raises `FileNotFoundError` when its prompt file is absent. |
| The target config is invalid, incompatible, or names a missing read-path | `ERROR` issues on stderr and exit 2 before any run record, stage or worktree. |
| The target is a bare repo, or the workspace layout is a clone-of-a-worktree | Refusal with a copy-pasteable bootstrap command; `aidw doctor` reports the same. |
| Another run is active in the same worktree | exit 4 before the run record is created; no state is written. |
| The task branch's worktree for `implement`/`fix`/`review` is missing | preflight refuses (exit 4), printing the exact `git worktree add` command; the *invoking* worktree's branch is never the test (K1, §8.3). |
| Dirty control worktree for `aidw prompt` | preflight refuses: the author must start from a clean base. |

---

## 11. Roadmap task selection

Where the roadmap lives is target-repo configuration (D15/D17): the whole per-repo surface is
`paths.roadmap_dir` plus `paths.roadmap_glob`, documented in `docs/target-repo-config.md`. The
toolkit defaults are `docs/tasks` and `[0-9]* - *.md` (`TOOLKIT_DEFAULTS.paths`) — the layout of
Mythical Forge, the first repo AIDT ran against, kept as the default so that repo's config file
stays close to empty (D17) — and there is **no** per-repo dialect: no configurable regex, heading
syntax or parser variant. The format itself is AIDT's own contract and is documented in
`docs/roadmap-format.md`; this section says only what selection means.

`roadmap.py` parses the files in `<paths.roadmap_dir>` that `<paths.roadmap_glob>` selects:

- Headings `# Phase NN:`, `## Epic X:`, and checkbox items `- [x]` / `- [ ]` with
  `**<ID>. <Title>**` and an indented `- Done when:` line.
- `_FILENAME_RE` stays the phase authority: the glob only pre-selects candidates, and the phase
  always comes from the `<NN> - <Name>.md` filename prefix, never from the `# Phase` heading — a
  name the glob admits but the pattern rejects (`0 - x.md`, `0123 - x.md`) is ignored.
- Produces `{phase, epic, task, title, done, done_when, citations, file, line, epic_title,
  phase_title}`.

Commands:

- `aidw tasks` — list all tasks with `phase/epic/id/status`. It resolves `<target>/aidw/config.yaml`
  for the two `paths.` leaves and **fails closed** on a config the loader rejects (issues on
  stderr, exit 1), so a typo cannot silently list the wrong roadmap; it deliberately does not run
  the read-path preflight, so a roadmap-only repo still lists.
- `aidw tasks --todo` — only unchecked.
- `aidw tasks --phase 03 [--epic E2]` — filter.
- `aidw tasks --show "<phase> <epic> <task>"` — detail including `Done when` and cited specs. The
  argument is one quoted string whose three space-separated parts are all required.
- `aidw tasks --next [--phase 03]` — first unchecked task.
- `aidw tasks --validate` — report malformed entries as `{file}:{line}: {rule} …`, so a roadmap
  edit fails loudly instead of silently dropping a task.

Dependency-graph awareness is deferred (§17 F4): neither `--next` nor the listing enforces
ordering, and the refusal that does exist is `aidw prompt`'s preflight on an unticked
predecessor in the same roadmap phase file (§8.1).

`aidw prompt <phase> <epic> <task>` takes those three positionals only (there is no `--task`
flag) and resolves the entry from the same configured roadmap; the stage evidence bundle
re-reads the entry's own file from that same directory (`docs/roadmap-format.md` §6, "two
readers").

---

## 12. Configuration, environment, and secrets

### 12.1 The resolved target config

A target repo's tracked configuration is a small `aidw/` folder (EXTRACTION.md §3.4):

```text
<target>/
├── aidw/
│   ├── config.yaml          # required if the folder exists
│   ├── conventions.md       # optional: repo stack rules injected into prompts
│   └── prompts/             # optional: repo prompt overrides, by filename
├── AGENTS.md                # the project's system prompt (already loaded by Pi)
└── …
```

`conventions.md` is also where a repo declares its **traceability artefacts** (W1.1, Z13): the
files `I3 update-traceability` maintains, with their drift checks, or the explicit "no artefact to
update" outcome when it has none. That channel (`AGENTS.md` then `aidw/conventions.md`, D16)
reaches `I3` because `update-traceability.md` is one of `CONVENTIONS_PROMPTS` (five since W1.1).
The roadmap is never one of the artefacts a repo may declare: `paths.roadmap_dir` belongs to `I7`
byte-exclusively (§8.2, §17 Z13), so "none" is the correct declaration for a repo with no other
artefact.

`config.yaml` is YAML (D11) declaring `schema_version` (required in the file), an optional
`requires_toolkit` PEP 440 pin, and optional `max_revisions`, `repo`, `paths`, `workflows` and
`github` sections. The **normative field names, defaults, worked examples and the marker/label
tables** live in `docs/target-repo-config.md`; the machine-readable contract is
`docs/schema/aidw-config.schema.json`. This design cross-links them rather than restating them —
a second copy drifts from `aidw/target_config.py` and from the schema.

Three rules the design does own, because every consumer depends on them:

- **Layered resolution with per-value provenance.** `resolve_config` merges the toolkit defaults
  under the declared config under per-invocation overrides, and records each value's `source`:
  `override` | `config` | `default` | unset. Declared-ness, never value equality, decides
  `config` — a config that explicitly sets `max_revisions: 3` fingerprints differently from the
  default `3`. `aidw config show` prints every resolved leaf with its provenance and the roots it
  resolved; `aidw config show --json` prints the same object `config_hash` is computed over.
- **Fail closed on anything it cannot understand.** Unknown keys are errors at every object
  level, wrong types name the offending field path, a missing `schema_version` in an existing
  file is an error, and `check_compatibility` refuses a `schema_version` newer than
  `SUPPORTED_SCHEMA_VERSION` or an unsatisfied `requires_toolkit`. All of these are exit 2 before
  any run state, never a silent fallback to defaults.
- **Configured read-paths must exist.** `build_results_template`, `roadmap_dir`,
  `task_prompts_dir`, `implementation_results_dir` and `agent_configs_dir` are read-paths: a
  resolved path that does not exist is an error naming the field, the path and its provenance
  (`source: default` included). Write-targets (`architecture_dir` today) are the opposite: they
  may legitimately be absent, no read-path check applies, and `ensure_write_targets` is the
  helper that creates an enabled stage's directory and reports a failure per field — it has no
  workflow caller yet, so today absence is a normal state and the writing stage creates what it
  needs. `roadmap_glob` is a pattern and is neither classified nor stat-checked.

### 12.2 Stage registry and value overrides (D12/D13)

The stage lists, loops and parallel groups are **data** (`aidw/stage_registry.py`), with the
defaults preserved exactly (stage ids `P1`, `P2`, `I1`–`I9`, `R1`, `R2`, `F1`–`F4`, `A1`) so
existing run artifacts stay readable. A target repo's `workflows:` section overlays them:

- **Core stages** (D13): implement, test, code-review, record, pr, plus Python-owned branch
  setup and the prompt workflow's author stage, and the review publisher and approval stages. A
  core stage may not be removed, reordered, or disabled — each violation is one named error.
- **Repo-optional stages** (D13): traceability (`I3`) and architecture (`I4`). A repo disables
  one with an explicit `enabled: false`; a disabled stage's write-target is not created.
- **Repo-added stages** are allowed, including between core stages. A repo-added stage must
  declare `id`, `agent`, and either `prompt` or a file in `aidw/prompts/`.
- **Stage metadata overrides** (D12, decision N1): a stage entry may set `agent`, `model`,
  `thinking` and `timeout_seconds`, validated on load and honoured by the runner. `model` is a
  **model-only replacement, never a provider switch**. Precedence is per-stage override > global
  agent-config override > toolkit default, for that stage's invocation only; a per-stage override
  is an explicit operator choice recorded in the argv and `state.json`.
- **`parallel_groups`** replaces the one hardcoded safe pair. Every member must exist and must
  not be ordered against another member of the same group.
- **Path-scoped stages** (S1.1/S1.2, decisions Z11/Z12): a stage entry may declare `when_paths`,
  a list of repo-relative path prefixes, and a stage whose registry definition carries
  `when=paths-changed` (`I3`, and `I4`) runs only when the run's change set touches one of
  them. The list is optional and normalised on load (sorted, deduped,
  `verification.normalise_ignore`'s rule — `./docs/x` and `docs/x/` are one prefix). `I3` has no
  registry default, so an **absent or empty** list leaves it **unconditional**. `I4`'s default is
  the literal `docs/architecture`, and a repo-declared list **replaces** it (never merges), so an
  absent key keeps the default and an explicit `[]` is the only empty/effective-unconditional set
  (which `aidw doctor` warns about for `I4`). The token is one of the two the expander cannot
  resolve, so it is carried onto the planned stage exactly as `evidence-green` is, together with
  the registry default: the plan keeps the stage in position and the workflow decides before
  `run_stage`.

### 12.3 Prompt resolution (D14)

Per prompt, per stage, highest precedence first:

1. the stage's explicit `prompt:` path in the target config (target-relative when relative);
2. a same-named file in `<target>/aidw/prompts/` (filename shadowing);
3. the toolkit default `<toolkit>/prompts/*.md`;
4. failure — an unknown stage id or an unresolvable required prompt is an error, never a silent
   skip. A declared-but-missing explicit path does **not** fall through to 2–3.

`aidw prompts list` prints the inventory with each prompt's provenance, and `aidw prompts check`
verifies it: every required prompt resolves, nothing references a foreign prompt tree, and every
script-invoking prompt locates its script through `AIDW_SCRIPTS_DIR`.

### 12.4 Environment and secrets

Environment variables AIDW reads (all optional):

| Variable | Meaning |
|---|---|
| `AIDW_REPO` | Target repo root; used when `--repo` is absent. |
| `AIDW_STATE_DIR` | State-root base, overriding the workspace/`~` tiers (§9.1). |
| `AIDW_GATE_DEFAULT` | `deny` restores the strict gate prompt; `--gate-default` wins. |
| `AIDW_NONINTERACTIVE` | Non-interactive gate handling (unapproved gates fail closed). |
| `AIDW_SCRIPTS_DIR` | Runner-provided absolute path to the toolkit's `prompts/scripts` — how a prompt finds a bundled script. |
| `AIDW_REVIEW_FOLLOWUP_CONFIG` | Runner-provided JSON handoff of `github.markers`/`github.labels` to the bundled scripts (§7.2). |
| `AIDW_RUN_ID`, `AIDW_STAGE` | Runner-provided run/stage identity for `aidw gate run` inside a stage. |

Secrets/credentials are **never** stored in the toolkit or in the target repo: Pi provider
credentials come from Pi's own auth store or environment (`pi auth`), GitHub from `gh auth`, and
any cloud profile from the environment the operator exports.

`aidw doctor` validates: python and uv, `pi` on PATH and above the enforced Pi floor, `gh`
presence and authentication, `gh`'s sub-issue support (the review-followup scripts read native
`subIssues`/`parent` fields and create children with `--parent`, so an older shadowed `gh` is a
`FAIL`, not a warning), `git` ≥ 2.31, the resolved toolkit/target/workspace/state roots, the
workspace layout guards, the target config and its compatibility, the prompt and agent-config
inventories, the toolkit version, and the optional Archify and `.mcp.json` amenities. A target
repo is optional: the environment checks run before target resolution, so `aidw doctor` outside a
repository still reports them.

### 12.5 Distribution, version, and compatibility (D9/D10)

- The toolkit is installed once: `uv tool install git+…@<tag>` primary, `uvx --from … aidw`
  secondary. Nothing is vendored into a target repo, and the toolkit version is recorded in
  every run's `state.json` (`toolkit_version`, §9.2), so a run can be explained after the fact.
- `aidw --version` (and `aidw version`) prints `aidt {aidw.__version__}` from the package, and
  works outside any repository — it resolves no target.
- Semver the toolkit. A target repo may pin `requires_toolkit: ">=1.2.0"`; the toolkit refuses to
  run when the pin is unsatisfied (`aidw.target_config.check_compatibility`), and `aidw doctor`
  reports the verdict on one named `compat status` line. The refusal names the pin, the toolkit's
  version, and how to fix either side.
- The bump-and-tag procedure — the three lockstep version edits, the annotated tag, verification
  from a clean tool venv, and a target repo's pin/upgrade steps — is `docs/releasing.md` (E8.5).
  This design deliberately does not duplicate it.

---

## 13. Git and GitHub safety

`git.py` enforces:

- `implement` and `fix` must operate on the task branch's worktree, never the base branch; a
  missing worktree is a refusal with the exact `git worktree add` command.
- Worktree creation/removal is Python-owned (`aidw worktree add|list|remove`), never an agent's;
  removal refuses a dirty tree or an unmerged branch unless `--force` is explicit.
- `aidw prompt` requires a clean control worktree on the base branch (§8.1).
  `implement`/`review`/`fix` deliberately run against a tree that may be dirty — the implement
  chain accumulates its change set uncommitted until the PR stage commits it — so their guard is
  the per-worktree run lock (§9.1), not a cleanliness test.
- AIDT never runs `git reset --hard`, `git clean`, `git checkout -- .`, force-push, or merge.
- AIDT preserves unrelated user changes and never broadens `git add` beyond the run's owned paths;
  the documented `git add -A` has exactly **two** owners, and both are executed by the
  `pr-publisher` agent, not by Python: `implement`'s `I6 pr` (the task's whole accumulated change
  set) and `fix`'s `F5 commit-and-push` (§8.4), which publishes a converged fix run's changes only
  when that run closed an issue — a dirty tree with nothing closed is skipped, never committed,
  so unowned dirt is not swept into somebody else's commit.

`github.py` only:

- reads PR/issue state via `gh` (read-only, structured JSON),
- invokes the bundled `publish_review_followups.py` and `review_followup.py` for writes,
  including the `approve` subcommand that the approval prompt uses,
- serializes the frozen `github.markers`/`github.labels` leaves into the scripts' one
  environment-variable handoff (§7.2), so an agent-invoked script and a Python-invoked script
  cannot disagree about which marker to search for.

It never calls `gh issue create`, `gh pr comment`, or `gh api` with a mutating method directly.
The marker/label freeze and its exact-match semantics are §7.2's contract; renaming a literal is
a migration, not an edit.

---

## 14. CLI reference

```text
aidw --help
aidw --version
aidw version
aidw doctor

# workflows
aidw prompt    <phase> <epic> <task> [--resume] [--from <stage>] [--from-prompt <path>]
              [--require-approval] [--yes]
              [--no-fetch] [--allow-incomplete-prereqs] [--max-revisions <n>] [--skip-gates ...]
              [--deny-gates ...] [--gate-default approve|deny] [--strict] [--dry-run]
aidw implement <task-prompt-path> [--pr <n>] [--resume] [--from <stage>] [--parallel]
              [--yes] [--skip-gates ...] [--deny-gates ...] [--gate-default approve|deny]
              [--strict] [--dry-run]
aidw review    --pr <n> [--yes] [--strict] [--dry-run] [--force-model]
aidw fix       --pr <n> [--max-iterations N] [--yes] [--skip-gates ...] [--deny-gates ...]
              [--gate-default approve|deny] [--strict] [--dry-run] [--force-model]
aidw approve-followups --pr <n> [--yes] [--skip-gates ...] [--deny-gates ...]
              [--gate-default approve|deny] [--strict] [--dry-run]
aidw run       task-to-pr <phase> <epic> <task> | prompt-to-fix <phase> <epic> <task> [--pr <n>]
               | review-and-fix --pr <n>
               [--yes] [--skip-gates ...] [--deny-gates ...] [--gate-default approve|deny]
               [--strict] [--dry-run] [--parallel] [--force-model] [--max-iterations N]
               [--allow-incomplete-prereqs]

# target repo and workspace
aidw worktree  add <branch> [--base <branch>] | list [--json] | remove <branch> [--force]
aidw config    show [--json]

# inspection and primitives
aidw tasks     [--todo] [--phase NN] [--epic X] [--show "<phase> <epic> <task>"] [--next] [--validate]
aidw agents    list | show <id> | validate [--strict]
aidw exec      --agent <id> --prompt <name|path> [--var ...] [--workflow <label>]
               [--label <label>] [--strict] [--dry-run]
aidw runs      list | show <run-id> | resume <run-id>
aidw prompts   list | check
aidw gate      run <key> -- <command> [args...] | list
               run a whole-repo verification gate once per tree; a later stage of the
               same run cites the recorded outcome instead of re-running it (E4.8)
               [--run <run-id>] [--stage <name>] [--base <branch>] [--force]
               [--ignore <prefix>...] [--tail <lines>] [--timeout <seconds>] [--json]
               `run` appends its outcome to `<run_dir>/state.json` under the per-run lock
               `<run_dir>/state.json.lock` (§9.2); `list` reads that file without a lock

# global
--repo <path>   select the TARGET repo (never the toolkit); default cwd, then $AIDW_REPO
--verbose       stream the Pi transcript to the TTY
--retry-transient / --no-retry-transient   retry once on a transient Pi invocation error, or once in a
                                           fresh session when an attempt produced no final message
                                           (default on; off disables both retries)
--progress / --no-progress                 show '.' progress while Pi works
                                           (default: on when stderr is an interactive terminal)
```

`gate run` is the second writer of `state.json` (H0.1, §9.2): it reloads the run inside the
`<run_dir>/state.json.lock` critical section and appends the outcome, so a stage record the
workflow wrote while the gate command was executing survives it, and the workflow's next
`save()` merges what the subprocess recorded instead of overwriting it. That is what makes
`gate list` and `runs show` report outcomes after the run process has exited, and what lets
`record` and `pr` cite a `test` outcome in one uninterrupted chain. The cite-or-run rule itself
is unchanged.

Exit codes: `0` success/approved, `1` stage or gate failure, `2` usage/config error,
`3` workflow blocked (needs human), `4` preflight/safety refusal.

---

## 15. Testing strategy for AIDT

- `pytest` is the only verification: `AGENTS.md` configures no linter, formatter or
  type-checker, and none is added inside an unrelated task. `pyproject.toml` sets
  `testpaths = ["tests", "prompts/scripts/review-followup/tests"]` — the second path covers the
  bundled script tests, which must stay stdlib-only so the scripts remain copy-portable. `addopts
  = "-q -n auto"`; `-n0` forces a serial run. CI (`.github/workflows/ci.yml`) runs
  `uv sync --frozen`, `uv run --frozen pytest` and `uv run --frozen aidw doctor` (D21).
- `uv sync --frozen` makes a stale `uv.lock` a failure rather than a silent update. The suite is
  dominated by `git` process spawns in temporary repos (~300 per run), so repository fixtures
  reuse an identity and avoid per-repo `git config`; a new spawn on a hot path is measured, not
  assumed.
- Unit coverage, per module:
  - `prompts.py`: frontmatter stripping, `$n` substitution, no-op on `$runner`/`$pr`,
    convention injection, missing-argument errors.
  - `config.py`: schema validation, allowlist rendering, independence warnings, strict failures,
    the target override directory's shadow-by-id semantics.
  - `target_config.py`: loader fail-closed behavior, layered resolution with provenance,
    compatibility refusals, read-path vs write-target classification, `config_identity`.
  - `agents.py`: exact argv construction for every flag combination (golden tests).
  - `stage_registry.py`: default plan expansion, loop bounds, parallel-group validation, and the
    overlay rules of §12.2.
  - `runner.py`: `resolve_prompt`'s four-level precedence.
  - `state.py`: write/read round-trip, resume selection, schema-version guard, additive fields.
  - `lock.py`, `layout.py`, `paths.py`: lock keying, workspace layout guards, root resolution.
  - `roadmap.py`: checkbox parsing against fixture markdown, and the format contract parsed out
    of `docs/roadmap-format.md` so doc and parser cannot drift.
  - `inventory.py`: required prompts/scripts present; foreign-tree sentinel; `AIDW_SCRIPTS_DIR`.
  - `github.py`: argument construction for the bundled scripts (execution mocked) and the
    `github.*` config handoff.
  - `verdict.py`, `findings.py`: the fail-closed parsers behind §8.3 and §10.
  - `verification.py`: content-tree identity and gate-outcome reuse/citation.
  - `tests/test_baseline_verbatim_golden.py`: the D5 freeze (§7.2), against the
    `baseline-verbatim` tag.
- A `--dry-run` for every workflow that performs no writes and prints the planned argv/actions is
  the primary integration seam; tests assert the dry-run plan. `fixtures/target-repo/` is the
  fixture target repo those tests point at: the override mechanism, the stage model and the
  roadmap format are only proven by running the real workflows against a repo that is not this
  one.
- **No test invokes a real Pi model.** The argv/plan is faked and asserted.

---

## 16. Build state

The phased build plan this document carried through v1 completed with the extraction tasks E0–E8
and is now historical; it is not repeated here. What replaces it is the current state, because
that is what a reader of this document needs:

| Capability | State | Evidence |
|---|---|---|
| Two roots, workspace/state root, worktree model | Implemented | `aidw/paths.py`, `aidw/layout.py`, `aidw worktree`, §1.1 |
| Target config: loader, provenance, compatibility, path rules | Implemented | `aidw/target_config.py`, `docs/schema/aidw-config.schema.json`, §12.1 |
| Config-driven stages, prompt resolution, per-stage overrides | Implemented | `aidw/stage_registry.py`, `aidw/runner.py`, §12.2–§12.3 |
| All five workflows, the chains, gates, resume | Implemented | `aidw/workflows/`, §8 |
| Run state under the state root, per-worktree lock, gate reuse | Implemented | `aidw/state.py`, `aidw/lock.py`, `aidw/verification.py`, §9 |
| Frozen GitHub contracts as per-repo config with frozen defaults | Implemented and guarded | `aidw/github.py`, `tests/test_baseline_verbatim_golden.py`, §7.2 |
| Packaging, console script, tag releases, pins | Implemented | `pyproject.toml`, `docs/releasing.md`, §12.5 |
| Documentation | In progress | this rewrite (E9.1); the contract docs and README follow (E9.2, E9.4) |

Remaining roadmap work — E9.2 (contract-doc finish), E9.3 (move `EXTRACTION.md` to
`docs/history/`), E9.4 (README rewrite) — is tracked in this repo's own roadmap (`docs/tasks/`).
The product-side cutover (MF.1–MF.6) belongs to that product repo's roadmap and is not restated
here.

---

## 17. Resolved decisions (interview log)

The complete extraction trail remains findable here: D1 D2 D3 D4 D5 D6 D7 D8 D9 D10 D11 D12
D13 D14 D15 D16 D17 D18 D19 D20 D21 D22 D23 D24; R1 R2 R3 R4 R5 R6 R7 R8 R9 R10
R11 R12 R13 R14 R15 R16 R17 R18. These identifiers retain the meanings recorded in
`docs/migration/EXTRACTION.md` even where later implementation decisions superseded them.

This is the resolved-decisions log: every row is a decision that is settled, with the reason it
was taken. Rows are kept after implementation so the trail survives — superseded rows say what
superseded them rather than being blanked. The extraction-era decisions (D1–D24) and resolutions
(R1–R18) of EXTRACTION.md §2/§6 are folded into the rows below and into the sections that
implement them.

| # | Decision |
|---|---|
| A1–A5 | Four workflow groups (prompt, implement, review, fix), defaults accepted; deployed integration tests + optional summary prompts out of scope; atomic stages + chain orchestrators; resumable. (Now five groups plus chains: `approve-followups` was split out of `fix`.) |
| B1 | Shared session within one agent's authoring stages; fresh sessions for reviewers; file-based cross-agent handoffs. |
| B2 | `update-traceability` shares the implementer session; review findings are extracted to a manifest file. |
| B3 | `pi --mode json`, tee JSONL, parse the final message. |
| B4 | `-p --approve` non-interactive; per-agent flags. |
| B5 | Wall-clock timeout always; optional cost ceiling. |
| C1 | `tools` is an **allowlist only** (deny-by-default when empty). |
| C2 | Per-agent `AGENTS.md`, inlined via `--append-system-prompt`; `cwd` is the **target** repo root (§5.1, §3.1). |
| C3 | `append` by default; `override` supported. |
| C4 | Baseline allowlists as in §5.2. |
| C5 | Warn on independence violations; `--strict` fails. |
| D1 | **AIDT lives in its own repository** (`aidt`), installed once and no longer branch-coupled to any checkout. Supersedes the pre-extraction "self-contained subtree" decision: the toolkit is an installed package, not a directory inside a target repo. (EXTRACTION.md D1/D8) |
| D2 | Wrapper renders `$1..$n`; no reliance on Pi `/` expansion. |
| D3 | The **toolkit's** `prompts/` is AIDT's own source of truth for the default prompts and is edited freely; a target repo may shadow any prompt by filename or explicit path (D4/D14), and nothing compares the toolkit tree against another prompt directory. Supersedes the pre-extraction "copy of the product's prompt tree" framing. |
| D4 | **Pi `cwd` = the target repo root**, resolved through `TargetRepo.resolve` and, for a task branch, through the located worktree. A target may override an agent's `cwd` (target-relative). Supersedes "Pi cwd = the product repo root"; the extraction-era counterpart is D19 (`cwd` → `--repo` → `AIDW_REPO`). |
| E1 | Every gate optionally skippable; skips recorded. |
| E2 | Review publishing is ungated; human review happens on GitHub before `aidw fix`. |
| E3 | GitHub writes only through the bundled Python scripts (and the prompts that invoke them). |
| E4 | Safety refusals enforced; **git worktrees are in scope** (EXTRACTION.md D20). Supersedes the v1 "no worktrees" decision: `aidw prompt` creates the task worktree as a Python stage, `implement`/`fix`/`review` locate it, and one run per worktree is enforced by a state-root lock (§9.1). |
| E5 | Env-inherited credentials; no secrets in the toolkit or the target repo. The pre-extraction gitignored local env file inside the toolkit was dropped with the extraction: credentials belong to `pi auth`, `gh auth` and the operator's environment (§12.4). |
| E6 | No auto-retry on gate failures; one retry for transient invocation errors (configurable). |
| F1 | `uv`-managed project, build with hatchling; deps `packaging` + `pyyaml` + `typer`, `rich` optional; the wheel force-includes the three runtime asset dirs (`prompts/`, `agent-configs/`, `agents/`) beside the package. |
| F2 | CLI shape as in §14; single `aidw` dispatcher, one package. |
| F3 | Run state and artifacts live under the **state root** (`<state root>/<repo-slug>/runs/<run-id>/`, §9.1), never in the toolkit or a target tree. Supersedes the pre-extraction `runs/` directory inside the toolkit checkout. |
| F4 | `aidw tasks` roadmap listing in v1 (plus `--show`/`--next`/`--validate`); dependency-graph awareness deferred. |
| F5 | `pytest` is the only verification (`tests/` + the bundled script tests), and it is wired into CI from the start (D21), superseding "not part of the product's CI". |
| F6 | **Target-repo auto-detection** from the cwd, with `--repo` and `AIDW_REPO` as overrides (EXTRACTION.md D19); every path is absolute internally, and the toolkit root is never derived from the target. Supersedes the pre-extraction "auto-detect the repo root and derive `aidt/` from it" rule, which conflated the two roots. |
| F7 | AIDT = AI Developer Tools; AIDW = AI Developer Workflows; the target-repo config folder is `aidw/` (D7's dual-role naming, §3.2). |
| G1 | Stage wall time is attributed as `generation_seconds` (streaming the model) and `tool_seconds` (sum of Pi's per-call `durationMs`, or start/end intervals when that field is absent), with `tool_breakdown` splitting tool time by name. `runs show` displays a `timing:` line whose `tools` term is `tool_seconds` and whose `ai` term is the `duration_seconds` remainder, so the two add up, then a `tools:` line listing the per-name split. It recovers both from the stage JSONL for records written before the fields existed. None is aggregated, and the fields are additive at the same `schema_version`. |
| G2 | The `aidw prompt` revision budget spends its last slot on a review, not a fix. At `MAX_REVISIONS=3` the loop runs two fix batches plus three reviews, the third review review-only, so a review is always the last stage for a non-approving prompt. A residual `Request changes` after that terminal review fails closed (`BLOCKED`, exit 3) with the last review's findings on stderr and the verdict-bearing exit recorded as a `denied` `approve-task-prompt` gate whose mechanism is `review-loop`; the old `assumed_ok` / `no further review — accepted` unreviewed-acceptance path is removed. The earlier "**no** `approve-task-prompt` gate recorded" clause in this row was stale phase-02 wording that contradicted H7 and `_record_review_outcome`; H1.3 (W1) amended it and keys the blocked-run continuation on that record. `revisions` in a recorded gate detail counts fix batches (2 on a three-review success), not review rounds. (L4.1, design §8.1 — verified; this row is the phase-02 terminal-review/budget record, not duplicated.) |
| H1 | `aidw prompt`'s preflight fetches `origin` and refuses (exit 4) when the local base is behind or diverged from `origin/<base>`; before that it refuses when an earlier task in the same phase file is still unticked (`--allow-incomplete-prereqs` proceeds with a warning). The author gets a `blocked: <reason>` output channel that ends the run `blocked` (exit 3) with nothing committed; any uncommitted prompt change or created branch is reported, never removed (design §13); the author stage itself stays `succeeded`. (L1.1–L1.3, design §§8.1, 11, 14; EXTRACTION.md §3.8) |
| H2 | The reviewer inspects the branch a dependency task lives on and states the revision it verified; an unresolved cross-task or two-readings choice is `Blocked`, not a prescription. Rounds after the first receive a delta brief — the previous review plus the prompt diff since it — and must give a per-finding `resolved`/`not resolved`/`newly contradicted` verdict before new findings. (L2.1–L2.3, design §8.1) |
| H3 | Each review and fix stage is pointed at its own evidence bundle at `<run_dir>/stages/<stage>.evidence.md` (prompt path, roadmap entry, cited spec headings, prerequisite tick state, gate commands, base revisions); a missing bundle degrades to the prior behaviour, never an error. (L2.4, design §8.1, EXTRACTION.md D16) |
| H4 | The fixer verifies a finding against the repository and its cited sources before applying it, reports a disagreement explicitly rather than obeying a wrong `Suggested fix`, and sweeps the whole prompt after editing (`Requirements`, `Traps / prior review findings`, `Explicit non-goals`, `Tests`, `Done when`, closing list) to repair stale neighbours. (L3.1–L3.2, design §8.1) |
| H5 | Every fix stage snapshots its input prompt to `<run_dir>/stages/<stage>.prompt.md` before it runs, so each stage's input and the diff between stages are recoverable; the owned prompt path is still committed once at the end. (L3.3, design §9.1) |
| H6 | One `task-review-reconcile-N` stage runs per fix batch, after the batch and before the next review, on the `task-fixer` agent with the whole review and the batch's combined diff, to repair cross-section contradictions and any unaddressed finding; a round that approves runs none. (L3.4, design §8.1) |
| H7 | Prompt runs record a per-round summary — rounds run, findings per round, fixes per round, the final verdict, and whether any fix ran after the last review — in the gate `detail` and `run.log`, for the operator to judge; no cost, round-count or latency gate is added. (L4.2, design §9.2/§9.3) |
| H8 | The revision budget is `max_revisions`, with precedence CLI `--max-revisions` > target config `max_revisions` > default `3`; the toolkit default lives in `aidw/target_config.py` (`DEFAULT_MAX_REVISIONS`) so the loader needs no workflow import. (L4.3, design §12) |
| H9 | The task author gets a concise pre-submit self-check mirroring the review order, requiring an explicit decision — labelled `prompt-fixed` where the spec is silent — for failure-path precedence, per-mode output contracts, the complete label/key vocabulary, why the enumerated set is complete, exact comparison semantics, where shared code lives, and one proof per requirement. (L5.1, design §8.1) |
| H10 | The author reconciles its done-condition with the target repo's gate list, read from the root `AGENTS.md` and optional `<target>/aidw/conventions.md`, and names a "Gate impact:" line whenever a task touches a checker, status vocabulary or CI gate. (L5.2, EXTRACTION.md §3.4, D16/D17) |
| H11 | The workflow measures a produced prompt against the conciseness budget (80–120 lines, <15KB; ~150 lines for larger tasks), warns with a `budget:` count naming the offending requirement, and refuses under `--strict`. (L5.3, design §8.1) |
| H12 | `tests/test_prompt_workflow.py` pins the new loop contract on a synthesized fixture with no real model and no network: the L1.1/L1.2 refusals, the L1.3 blocked path, the L3.4 reconcile stage, the L3.3 snapshots, the L4.1 terminal review, the L2.3 delta brief, the L4.2 recording, and the L2.1/L2.2/L3.1/L3.2/L5.1 instruction clauses. (L6.1, design §15) |
| H13 | **`aidw run`'s chains forward `--allow-incomplete-prereqs` to the prompt stage** (design §§8.1, 8.6, 14; L1.2's ordering gate, `H1`). L1.2's refusal prints "re-run with `--allow-incomplete-prereqs` to author anyway", but the flag was declared only on `aidw prompt`; both chains invoke `prompt` internally with keyword arguments, so `aidw run prompt-to-fix <phase> <epic> <task> --allow-incomplete-prereqs` exited 2 with `unexpected extra argument` and the refusal named a flag the operator's own entry point rejected — a prompt-stage preflight with no path forward from the chain that runs it. `run.py`'s `task_to_pr`/`prompt_to_fix` gain the additive keyword `allow_incomplete_prereqs: bool = False` and pass it to `prompt_workflow.run`, which is the only place it is consumed; `aidw/cli.py`'s `run` command gains the option and threads it through. Nothing about the gate itself moves: the value defaults `False` in the workflow, so a chain invoked without the flag still refuses exactly as before, the flag still only converts the refusal into `_warn_incomplete_predecessors`' warning naming every skipped predecessor, and the underlying workflow's own `--resume` rule (a resumed run does not re-run the check) is unchanged. `review-and-fix` accepts the option and ignores it, because that chain runs no `prompt` stage; the other prompt-only flags (`--no-fetch`, `--max-revisions`, `--require-approval`, `--resume`/`--from`) are deliberately **not** forwarded — each changes the prompt run rather than permitting an otherwise-refused one, and none was needed to make a chain's own refusal satisfiable. (§8.6 gains one paragraph; §14's `aidw run` usage line gains the flag; `aidw/workflows/run.py`, `aidw/cli.py`; `tests/test_run_workflow.py`, `tests/test_cli.py`) |
| J1 | `aidw doctor` enforces `PI_MIN_VERSION = 0.85.0` and `FAIL`s below it, instead of reporting whatever `pi --version` prints. AIDW's Pi argv is verified against 0.85.x (§5.5), and below that floor a stage dies inside extension load *before* its first model call — `@earendil-works/pi-ai/compat` is a 0.85 addition, so a stale `pi` shadowed by an old `nvm` bin dir answers `--version` and then exits 1, which reaches the run record only as `exit code 1` with zero tokens, zero events and an empty stage JSONL. The finding names the floor, the offending path and `which -a pi`. (§12.4; `aidw/doctor.py`) |
| K1 | `aidw review` resolves the **PR-head worktree** instead of comparing the invoking worktree's checked-out branch to the PR head (supersedes the pre-E2.6 "current branch is the PR head" preflight, which §8.3 now states as "the PR head's worktree is located"). `gh pr view` supplies base and head; `git.worktree_for_branch` locates the head's worktree, and `TargetRepo.resolve` re-resolves the target and agent cwds against it, so stages, `github.*` reads, the run lock and `state.json`'s `repo_root` all use the task worktree — mirroring `implement` (§8.2) and `fix` (§8.4). The invoking branch is never read. A known head with no local worktree refuses (exit 4) with the copy-pasteable §3.2 `git worktree add` command and writes no run state; under `--dry-run` the command is planned output and the plan falls back to the invoking worktree, so a dry run still plans without a worktree. `pr_view` now runs under `--dry-run` too, so the head resolves in both modes (§8.4's E2.6 req 6 precedent). Why: since E2.6 the task branch lives in a sibling worktree, so the control root a chain/operator invokes `review` from is on `main`; the old equality test could never pass, and `aidw run prompt-to-fix` stopped with ``chain stopped: `review` exited 4`` on the review stage of every worktree run. A single checkout is a worktree whose branch *is* the PR head, so it locates itself and behaves exactly as before. Review remains branch-blind about *which* worktree invoked it, which also makes the E2.7 run lock key the task worktree rather than the control root. (design §§8.3, 8.6, 14; `aidw/workflows/review.py`) |
| I1 | `aidw run prompt-to-fix <phase> <epic> <task> [--pr <n>]` is the whole cycle — `prompt` → `implement` → `review` → `approve-followups` → `fix` — composed from the four existing orchestrators, so each keeps its own preflight, gates, state and resumability and the chain stops at the first non-zero exit. The PR number is read from the newest `implement` run's recorded `pr.number` (`--pr <n>` overrides it; `0` is the `--dry-run` placeholder, since a dry run opens no PR) instead of a new `gh` query. The chain auto-approves exactly one gate: it adds `approve-followups` to the `fix` stage's skip set and prints the mechanism. `approve-implementation-pr` and `approve-fix-pr` keep their normal `--yes`/`--gate-default`/interactive semantics, and `--deny-gates approve-followups` still refuses the auto-approval (`deny` is checked before `skip`, §6). `aidw run` also gains `--skip-gates` and `--force-model` for every chain. (design §8.6; §14 CLI reference; `aidw/workflows/run.py`) |
| I2 | A `prompt-to-fix`/`review-and-fix` chain whose review published **no follow-ups** ends gracefully (exit 0) instead of running the fix loop into its entry postcondition. Trigger: an `Approve` review printed `review approved with no findings; nothing to publish`, the chain still auto-approved `approve-followups`, and `round1-approve-review-followups` failed with `postcondition not met: could not read approval state (approve --dry-run exit 2): error: No review-follow-up parent issue found for <pr-url>` — a red run for a review that had approved. `review` now records `pr.followups_published` (`true`/`false`) in its run state on both successful exits, and the chain re-reads that state instead of adding a second GitHub query (the same trade-off `find_pr_number` makes for the PR number). It skips `fix` only when **no** review run of that PR ever recorded `true`: an earlier round's published follow-ups outlive a later "nothing to publish" review and keep the loop, and an absent record (`--dry-run`, a state root this chain did not write) keeps the pre-I2 behaviour. Skipping `fix` also skips its gate, so nothing is auto-approved or recorded for a stage that never runs. `aidw fix --pr <n>` invoked directly is unchanged and still fails closed. (design §§8.3, 8.6; `aidw/workflows/run.py`, `aidw/workflows/review.py`) |
| M1 | Review verdict parsing reads **prose only**. All three passes blank fenced code blocks first, and a verdict token only counts when it is not part of a path or module name (`prompt/review/fix/approve`, `approve.py`, `approve_round`); the bare-mention fallback additionally skips inline code spans unless the span is the line's whole content (`` `Approve` `` qualifies, `` `approve`'s `(spec,) =` `` does not). Failure this closes: the E4.5b task-prompt review (2026-11-04) never emitted a verdict — its report was cut off mid-sentence — but listed the workflows it read as `implement/review/approve/fix/prompt`, so the mention fallback returned `Approve` and five findings, one of them `Must fix`, were dropped with `fixes=0`. A verdict that still cannot be read returns `None`; `review`/`fix` fail closed on it immediately, and `prompt` keeps L4.2's behaviour (rework, then `BLOCKED` with `verdict=ambiguous`). (design §18; `aidw/verdict.py`) |
| M2 | An `Approve` verdict that reports `must-fix`/`should-fix` findings is a **self-contradicting review** and fails closed rather than being honoured: the prompt loop stops before any fix stage with `BLOCKED` (exit 3), a `denied` `approve-task-prompt` gate whose `detail` keeps the reviewer's `verdict=Approve` and the per-round counts, both the contradiction and the findings on stderr, and the prompt left **uncommitted** for a human. This is the mirror image of `review`'s "verdict requires changes but no findings could be extracted" refusal, and AIDW neither drops the evidence nor silently overrides the verdict. Approving with only `could-fix` findings is unaffected (non-blocking nits never stop a round). Failure this closes: E4.5b (2026-11-04) committed and implemented a prompt whose first finding made its central construction requirement a `TypeError`. (design §§8.1, 17; `aidw/workflows/prompt.py`) |
| M3 | Verdict parsing accepts the shape the reviewer prompts actually produce, and the prompts stop producing the shape M1 cannot read. Pass 2 now also accepts a line-leading inline code span that **closes immediately** after the token when the token is **capitalised** and only markdown emphasis and a sentence separator (`. ! ? … – —`) or end of line follow: `` `Approve` — nothing material remains unverified `` and `` **`Approve`** — reason `` parse, while `` `approve` — the function that publishes ``, `` `approve`, the publisher ``, `` `approve`: the publisher ``, `` `approve`'s … `` and `` `Approve` is what I would say if … `` still do not — a Python symbol named in a span is lowercase, and a span that runs on into a symbol or a sentence names something other than a conclusion, which is exactly the distinction M1 exists to keep. Independently, `prompts/code-review.md` and `prompts/task-review.md` now require a bare declaration line (`Verdict: Approve`) that pass 1 reads without any of this, and forbid putting the verdict in a heading, a code span, or a sentence; the two `tests/test_prompt_workflow.py` assertions that pinned the old "End with exactly one of …" sentence pin that line instead. Failure this closes: the PR #91 code review (task E4.7, 2026-11-04) approved with `` `Approve` — nothing material remains unverified for this test-and-fixture-only change. `` — M1's pass 2 rejected the span because something other than decoration followed it, passes 1 and 3 never looked, so `aidw review` failed closed (`verdict=ambiguous`, exit 3, findings recorded, nothing published), which is what stopped the `prompt-to-fix` chain after `implement`. The live report re-parses as `Approve`. (design §18; `aidw/verdict.py`, `prompts/code-review.md`, `prompts/task-review.md`) |
| N1 | Per-stage metadata overrides and a global agent-config override are **enabled** (EXTRACTION.md §2 D12: "override stage metadata (agent/model/timeout/thinking)" and "override agent config globally"; task E4.6). The stage entry gains `model`/`thinking`/`timeout_seconds` alongside `agent`, validated on load (`thinking` ∈ `THINKING_LEVELS`, `timeout_seconds` a positive int, `model` a non-empty string) and honoured by the runner; the global override is **`paths.agent_configs_dir`**, a §3.4 read-path whose default is **unset, not defaulted** (its consumer falls back to `<toolkit>/agent-configs/`, so a repo with no such folder never fails the read-path check). The override directory **shadows by `id`** rather than replacing wholesale: un-overridden toolkit ids still load, a brand-new id is additive (and a legal `agent:` target), an empty directory equals the toolkit defaults, and a named-but-missing directory is an error (in `load_all`, the exit-2 refusal point for implement/review/fix/approve, since `validate_paths` is `prompt`-only). Precedence is **per-stage override > global override-dir shadow > toolkit default, for that stage's invocation only**, and repo-added stages honour the same three metadata fields uniformly. `model` is a **model-only replacement, never a provider switch**: the `provider/model` split stays design §5.1's (`model_name`/`qualified_model` strip only a prefix matching the agent's own `provider`, so a bare or vendor-namespace slug rides the base `--provider`), and `StageRecord(model=…)`/`write_meta` record the effective config's `qualified_model`, never a second spelling. Per-stage `model`/`thinking`/`timeout_seconds` are **not** re-run through §5.4: that check runs at load time on the shadowed dict (so `implementer ≡ code-reviewer` through the override directory does warn), while a per-stage override is an explicit operator choice recorded in the argv and `state.json`, like `--force-model`. A declared `agent` on a **known** stage is existence-checked in preflight, so an unknown id refuses exit 2 instead of reaching `run_stage`'s `ValueError: unknown agent` traceback. (design §§5.1, 5.4; EXTRACTION.md §§2 D12, 3.4, 3.12; `aidw/target_config.py`, `aidw/config.py`, `aidw/runner.py`) |
| O1 | The publisher stage is told the findings manifest's **absolute** path, and its stage declares a **read-only postcondition**. Failure this closes (E7.3, PR 110, 2026-11-05): `MANIFEST_EXTRA` rendered `artifacts/review-manifest.json` "(relative to the repository root)", but the workflow writes it to the **run directory**, so `R2`'s agent — whose cwd is the target repo, and which never receives a run-dir variable — found `<repo>/artifacts/` absent, stopped, reported the blocker in its final message and exited 0. It was right not to publish (inventing findings is worse), but `parse_publish_output` then returned `parent_issue: None` and `review` unconditionally recorded `followups_published: true`, so the failure surfaced one workflow later as `aidw fix`'s `round1-approve-review-followups` failing with `No review-follow-up parent issue found` — the same entry postcondition I2 exists to avoid. The plan field is renamed `manifest_rel` → `manifest_path` and carries an absolute path in both `review` (R2) and `fix` (F4). Independently, `R2` now carries `github.verify_published` exactly as `A1` carries `verify_approvals`: a `--dry-run` re-read that fails the stage when the parent verdict is still `create`, so `followups_published: true` now means the publication was observed rather than assumed. A relative pointer and an unchecked exit 0 are the two halves of one defect: the second is why the first was silent. (design §§8.3, 10, 17; `aidw/findings.py`, `aidw/github.py`, `aidw/workflows/review.py`, `aidw/workflows/fix.py`) |
| P1 | Every run's `state.json` records **what produced it** (E8.2, EXTRACTION.md §§3.11, 3.4; D9/D10): `toolkit_version` (always `aidw.__version__` — never a `git`/`uv` shell-out or a `pyproject.toml` parse, E1.6), `config_schema_version` (the **config** schema version that resolved, `None` for a repo with no `aidw/` folder, because §3.4 requires it *in* a config file and gives it no default), and `config_hash` (`sha256:<hex>` over `json.dumps(resolved.to_dict(), sort_keys=True)` — the same object `aidw config show --json` prints, so the fingerprint is reproducible from an operator-visible command). The three are **additive at the same `SCHEMA_VERSION`** on the throughput-fields precedent (§9.2), each defaulting `None` so a `state.json` written before them still loads. Two names are deliberate: the bare `schema_version` key is the **state** schema and `load` refuses a mismatch, so the config's is `config_schema_version`; and `config_hash` is the resolved **config**, never E4.8's `GateOutcome.tree` content-tree identity. Both config values come from one pure helper, `aidw.target_config.config_identity(resolved)` → `(config_schema_version, config_hash)`, called by the five workflows at their `create_run` site so they cannot drift; `aidw exec` records `toolkit_version` only and leaves both config fields `None`, because it resolves no target config and wiring the config preflight into it would change its failure surface. Hashing the *resolved* mapping rather than the raw file or the declared `TargetConfig` is what makes the value mean "the config this run used": each leaf carries its `source`, so a declared `max_revisions: 3` fingerprints differently from the default `3` — provenance is part of the resolved-config identity. (§9.2 carries the schema example now that E9.1 has rewritten it.) (EXTRACTION.md §§2 D9/D10, 3.4, 3.11; `aidw/state.py`, `aidw/target_config.py`, `aidw/workflows/*.py`, `aidw/cli.py`) |
| S1 | The toolkit's prompt library is **14 neutral defaults** after the MF.2 cutover; EXTRACTION.md §4.2's 20 product prompts split into **17 moved** to the target repo's `aidw/prompts/` and **3 retained and neutralised** here (`task-prompt.md` = `P1`, `update-traceability.md` = `I3`, `update-architecture.md` = `I4`). MF.2's literal "none remains in the toolkit" is deliberately not followed: those three are invoked by the **default** `prompt` and `implement` chains, and `resolve_prompt` fails closed (§12.3 step 4), so deleting them would make `aidw prompt` and the default implement chain refuse for every repo without overrides — breaking §8.3's "a target repo with no `aidw/` folder runs with pure defaults". The 17 were reachable only through `aidw exec --prompt <name>` or through prose in another prompt, so removing them changes no stage: a repo that wants one supplies a same-named file under its own `aidw/prompts/` (D14 precedence 2). Two consequences are recorded rather than hidden. First, the three retained defaults were **rewritten as new neutral text**, and the product text lives on only in the target repo's copies, which is the point — Mythical Forge now owns it, and in exchange no longer receives toolkit fixes to those three (stated in its `aidw/prompts/README.md`). Second, a toolkit default names a **stage** (`/pr`, `/test`), never a prompt file path for a file it does not ship: the pre-extraction cross-references that pointed into the product repo's own `prompts/` tree were stale as soon as the toolkit moved, and the agent context files were cleaned up in the same change. `R` is skipped in this log — `R1`–`R18` are the extraction-era resolutions of EXTRACTION.md §6. (§7.1; `docs/migration/prompt-classification.md`; `tests/test_prompt_classification.py`, `tests/test_prompt_neutrality.py`) |
| Q1 | `aidw --version` is an eager top-level flag that prints exactly what the `version` subcommand prints — `aidt {aidw.__version__}` — and exits 0 **before any target resolution**, so it works outside a repository (E8.3, the roadmap's "without a target repo"). Neither click's default `<prog>, version <v>` rendering nor a `git`/`uv`/`pyproject.toml` lookup is used: both would disagree with the one version source E1.6/P1 already chose. `aidw doctor` next reports `toolkit version` (`aidw.__version__`, informational and always OK) as an environment check beside `git version`, so it survives the target early return, and a distinct `compat status` check carries the D10 verdict. That verdict **moves out of** `target config` (E3.5) rather than being copied: `check_compatibility` is evaluated once, an incompatible `schema_version`/`requires_toolkit` is one FAIL on one named line, and `target config` keeps the loader's ERROR issues, `validate_paths` and the resolved schema-version line. (EXTRACTION.md §3.11 D10; `aidw/cli.py`, `aidw/doctor.py`) |
| U1 | **A stage that produced no final text gets one fresh-session retry** (H1.1; design §§10, 9.2, 14). The attempt loop at the Pi seam (`aidw/pi.py:execute`, surfaced through `aidw/runner.py:run_stage`) gains an additive second branch, never folded into the transient branch: retry once when the invocation exited 0, was not timed out, `not parsed.provider_error` (so `stopReason != "error"` **and** no `errorMessage`), and `parse_events` returned `final_message == ""`. The provider-error guard is load-bearing: a 402 is exit 0 with empty text, and design §10 says it fails rather than retries. Emptiness is `parse_events`' own stripped notion, shared with `execute`'s out-file gate and the workflows' `not text.strip()` checks — no second predicate. The retry passes a **distinct session id**: the base id (`aidw/state.py:session_id`) with a `-retry` suffix (`RETRY_SESSION_SUFFIX`), rewritten in a copy of the baked argv (`retry_argv`), because re-running the identical argv resumes the truncated session and truncates again; the caller's argv (recorded in the meta) is never mutated, and an invocation carrying no `--session-id` is already a fresh session by construction and keeps its argv. Both branches share today's cap, `max_attempts = 2 if retry_transient else 1`: the retry is once, unconditional on stage type, and `--no-retry-transient` disables it. Per-attempt evidence is the additive `PiResult.attempts_detail` / meta `attempts_detail` list, one entry per attempt with `attempt`, `session_id`, `exit_code`, `stop_reason`, `usage`, `generation_seconds` and `tool_seconds`; usage and timing are captured inside the loop before a retry overwrites the transcript and become the **sum** of the attempts that ran, so `out-tok/s` stays `summed output / summed generation` and the existing cost-ceiling check covers both costs without a second check. `StageRecord` gains the additive `stop_reason` (the **final** attempt's) and `attempts`, at the same `SCHEMA_VERSION`, and the workflows' empty-final-message failure now names the stage, that stop reason and that both attempts were truncated instead of the bare "produced no final message". A gate decision is never re-asked: the retry fires only on this signature, so a denied gate or a `Request changes`/`Blocked` verdict is untouched. A shared-session agent's *later* stage still resumes the base id (the retry forked the context) and receives the retried stage's handoff through its `.out.txt`, which the workflows read; propagating a forked session id is H1.2/H1.3's resumability scope, not this retry. (§9.2, §10, §14; `aidw/pi.py`, `aidw/runner.py`, `aidw/state.py`, `aidw/report.py`, `aidw/workflows/prompt.py`, `aidw/workflows/fix.py`, `aidw/workflows/review.py`) |
| V1 | **`aidw prompt` resumes instead of re-authoring** (H1.2; design §§8.1, 9.3, 9.4, 14). The workflow gains `--resume`/`--from <stage>`, modelled on `implement.py` (`_latest_prompt_run` filtered on `workflow == "prompt"` and the recorded branch, `_confirm_resume` before the worktree locate and the lock, `should_run` skip-by-record) plus the branch-setup change that **locates** the task worktree and creates it only when none exists. Prompt-fixed decisions and their reasons: (a) a resume **reuses** the failed run's own worktree even when dirty — its partial edits are the state it continues from and its reconcile/next review still verify the result — while a *fresh* re-run reuses a located tree only when `git status --porcelain` is empty and otherwise refuses exit 4 printing `aidw worktree remove <branch> --force` and `git -C <base> branch -D <branch>`; the same two commands cover a leftover branch that made `git.add_worktree` refuse. (b) Loop state is **reconstructed from records, never re-derived by re-running**: `review_index`/`revisions` come from the stage names and each prior round's `FixBatch` is a real `stage_registry.FixBatch` re-parsed from that round's recorded review `.out.txt` with the loop's own `parse_review_findings`/`partition_findings` (`unparseable=True` when the parse failed), reconciled against the recorded `task-review-fixes-*` names and refused (exit 4) if a recorded fix stage cannot be reproduced, and a skipped review whose re-parsed verdict would now **end** the run while later stages are recorded is refused the same way — stage names carry only counts, and a placeholder batch is the same forbidden fabrication as a fake baseline. (c) `baseline_prompt` (the pre-fix snapshot) is not persisted, so a resumed round passes `_brief_diff(baseline=None, …)` and the brief names the diff unavailable instead of pretending the post-fix prompt is the baseline. (d) Every `return 1` site stamps `state.resume = {"next_stage": <stage>}` (including H1.1's empty-final-text failure and the author's not-found/over-budget refusals, which name `task-prompt` so a resume re-authors the only thing that can be fixed); a success clears it to `{"next_stage": None}`; a blocked exit records the **empty** dict, because §9.3 sets `next_stage` only on a stage failure and a resumed-then-blocked run must not look resumable. (e) A latest run still marked `running` (a crash releases the lock but leaves the record) refuses a fresh run with exit 4 naming the run id, before branch setup; `--resume` takes that record over as its own (same run id, no `create_run`) and re-runs the in-flight non-succeeded stage. (f) A **blocked** run's `--resume` refuses with exit 3 and the shape's own recorded reason, re-read from the run: the author's `blocked:` line, else the last recorded review's verdict plus `findings_summary`, naming the denied `approve-task-prompt` outcome's `mechanism` (`review-loop` marks the loop's own shapes, anything else is a gate denial). Exit 3 rather than 2/4 keeps design §14's "workflow blocked (needs human)" distinct from a usage error and a preflight refusal, and the refusal precedes every write path. (g) `--from` is validated against the loop's grammar bounded by the resolved `max_revisions` (`task-prompt`; `task-review-1..max_revisions`; `task-review-fixes-1..max_revisions-1[-<n>]`; `task-review-reconcile-1..max_revisions-1`) before any side effect, exit 2 otherwise, consulting only the grammar and the budget (every recorded stage is grammar-valid, so a run record would add no names). It is applied on *encounter*, so a grammar-valid name absent from this run's plan degrades as implement does — no position override, no crash — and `--from` with `--resume` re-runs the named stage onward in the same run id while `--from` alone is a fresh run. (h) The one-run-per-worktree lock is taken on the reused worktree's resolved path before the run state is re-opened and released on every exit path; recorded gate outcomes survive `save()` through H0.1's merge, and an already-approved `approve-task-prompt` gate is not re-asked. (i) A `--dry-run` is always the fresh author + `task-review-1` plan (implement's `resume and not dry_run` guard): no completed-stages print, no confirmation, no takeover, no locate, while `--from` is still validated and the still-running and blocked refusals are not dry-run-gated. (j) The run-scoped preflights (L1.1 base-branch fetch, L1.2 predecessor check) are not repeated on a resume — they belong to the run being resumed — while the worktree identity and the lock are. (Tests: `tests/test_prompt_workflow.py`.) |
| W1 | **A blocked `aidw prompt` run gets a forward path, scoped by the shape of its block** (H1.3; design §§8.1, 9.2, 9.3, 9.4, 14). The route is keyed on the run's **latest** `approve-task-prompt` gate being `denied` with mechanism `review-loop` — the terminal `Request changes`, a `Blocked` verdict, or M2's approve-with-blocking-findings — never on `status == BLOCKED` alone: an author-``blocked:`` run recorded no gate and a human-gate denial recorded `decide`'s own mechanism, and neither holds terminal findings a fix batch could take, so both keep H1.2's exit-3 refusal naming their recorded reason (`--from-prompt` is their path). Latest-wins rather than "any": a fix cycle re-blocked by the human gate holds *both* records, and its next `--resume` must meet the human-gate refusal. The `--resume` fix cycle is the **existing loop re-run under an extended budget**, never a new stage list: `state.task.effective_max_revisions` = recorded `task-review-N` count + 1, which makes the added `task-review-{N+1}` the `max_revisions`-th review, so L4.1 holds (a review is last; the recorded round's findings finally get the fix batch and reconcile the `terminal_last` break skipped) and each further `--resume` is its own explicit operator decision granting one more round — never a larger default budget, never an auto-unblock, and the resolved `max_revisions`/`--from` grammar is untouched (the extension is per-run and must not leak into the bounded name grammar). A replayed round contributes only its batch (an `Approve`/`Blocked` verdict already decided the blocked run; replaying it would re-block with no forward path), while the added review decides exactly as a fresh terminal review does, through the shared post-loop gate block: `already_approved` is false for a `denied` record, so under `--require-approval` the human is consulted **once** (design §9.4 allows re-deciding a denied gate; only an approved one is never re-asked) and a denial is the continuation's own blocked gate with `decide`'s mechanism, never `review-loop`. The confirmation-point budget guard consults the budget the loop will actually run under — the effective value for a continuation, the resolved one for a failed-run resume — because a continuation legitimately recorded more fix rounds than the resolved budget allows. `--from-prompt <path>` continues either shape: blocked-run-only (exit 2 otherwise), a takeover with or without `--resume` (the H1.2 gate widens to `(resume or from_prompt) and not dry_run`), precedence over the fix cycle when both are given, and `--from` alongside it is exit 2 because the route fixes its own start stage. It copies the supplied bytes onto the canonical `docs/task-prompts/<phase>-<task>-prompt.md` (so `rel`, the evidence bundle and `_commit_reviewed_prompt` keep keying off that path), refuses exit 4 when that path is dirty — a blocked run may have left exactly those edits, and overwriting them is the §13 discard AIDT never performs — records `state.task.from_prompt = {path, sha256:<hex>}` over the bytes written, and forces the loop from `task-review-1` with an internal position bound (never `--from`, never by skipping the old reviews, whose `succeeded` output would re-parse as stale findings). It runs under the resolved `max_revisions` (new content, fresh budget), counts no recorded fix round at the confirmation guard, and supersedes stages by name while keeping the records of rounds it never reaches. Each continuation's gate `detail` therefore reports the budget and round count it actually ran under — effective for a `--resume` fix cycle, resolved for `--from-prompt`, never a stale `effective_max_revisions` — so the original `denied` record and the continuation's stay distinguishable in `state.gates`. A blocked continuation whose task worktree no longer exists refuses exit 4 naming the run, the missing worktree and `aidw prompt <phase> <epic> <task>`, never re-authoring silently. `--dry-run` still never takes a run over: both routes plan the fresh author + `task-review-1` baseline and copy nothing, while the scoped-out refusals and `--from-prompt`'s missing-file check stay ungated. Also amends the stale "no gate is recorded" wording in §8.1 (and row G2) to the verdict-bearing recording H7 and `_record_review_outcome` already implement. (design §§8.1, 9.2, 9.4, 14; `aidw/workflows/prompt.py`, `aidw/cli.py`; `tests/test_prompt_workflow.py`) |
| T1 | **Gate outcomes persist through a merge-on-write of `state.json` under a per-run file lock** (H0.1, the roadmap's mechanism (b); supersedes nothing, it makes E4.8's recording survive a stage boundary). Rejected mechanism (a), a separate append-only outcome log per run: it needs a second artifact every reader (`RunState.gate_outcome`, `gate list`, `runs show`) and every writer learns about, and it leaves the rest of `state.json` with the same unchecked read-modify-write — the loss H0.1 closes is symmetric, so it belongs to the file both writers already share. Both writers own their rows: `state.save` publishes the workflow's whole state but reloads under the lock and merges the `gate_outcomes` already on disk, and the CLI gate path (`state.append_gate_outcomes`) reloads and appends only, so it never rewrites a stage record it did not write. The lock is **`<run_dir>/state.json.lock`**, `fcntl.flock(LOCK_EX|LOCK_NB)` opened fresh per acquire and never unlinked (the `aidw/lock.py` pattern), held around each writer's whole read-modify-write — **not** `locks/` and **not** keyed by worktree path, because the workflow already holds the worktree run lock for its whole lifetime and a worktree-keyed state lock would refuse every `aidw gate run` subprocess (design §9.1's non-conflation). `LOCK_NB` plus a bounded 60s retry loop, not a blocking `LOCK_EX`: a peer must be waited for (two overlapping gate runs both have evidence, and H0.1's symmetric-merge rule forbids dropping either), while a wedged holder fails closed with `StateLockTimeout` instead of hanging the run. Publication is a temp file **in the run directory**, fsynced, then `os.replace`d, so lock-free readers (a concurrent citation, `runs show`) never see a torn file; a temp file in `/tmp` would be an `EXDEV` failure or a non-atomic cross-device move. Dedup is identity of the whole row, never "newest wins per key": two processes that both executed a command are two pieces of evidence, so only byte-identical rows collapse. `GateOutcome`'s field names and the `gate_outcomes` list stay in `state.json` at the same `schema_version` — no schema change — and the cite-or-run rule (same key, tree, command, declared scope and `passed`; anything else runs) is untouched. An unreadable `state.json` fails the write closed rather than being overwritten. (§9.2, §9.1, §14; `aidw/state.py`, `aidw/cli.py`; `tests/test_verification.py`) |
| X1 | **The delta brief has a size contract, budgeted per half** (H2.1; design §§8.1, 9.2, 15). A six-finding round inflated the next review from 12,317 to 55,636 chars and the stage then ended `stop_reason: length`, so `stage_registry.render_delta_brief` now budgets its two halves **separately**, because they fail differently. (a) *Previous review*: no hard cap — the **smaller of two representations** wins. When `findings.parse_review_findings` returns findings with **no** problems, the review is re-emitted as one `findings._finding_text_block` per finding under a delta-brief heading (no fixer voice: `render_finding_block`'s "Fix exactly this finding" is for a fix stage, and the reviewer must *resolve*), and that rendering is used **only when strictly smaller** — `len(structured) < len(previous_review)` on the exact strings compared, the same `len(s)` char metric as the diff cap, **never** UTF-8 bytes or lines. Equality, and any non-win, and anything that does not parse cleanly (any problem, or no findings at all), keeps the prose **verbatim, trailing whitespace included**. All-or-nothing per review, so no finding is ever dropped, and `DELTA_BRIEF_INSTRUCTION`'s per-finding `resolved`/`not resolved`/`newly contradicted` verdict instruction survives in every rendering (L2.3's purpose). What the substitution gives up is the review's non-finding prose — its verdict, headings, commentary — which the looping workflow already consumed when it routed on the verdict. (b) *Diff*: a hard cap, **`DELTA_BRIEF_DIFF_BUDGET_CHARS = 4000`** characters (`len(s)`, prompt-fixed; anchored to round 1's ~12k prompt so the diff stays a small fraction of what the reviewer already reads). The spec fixes the strategy and no number, and the roadmap's second lever — a narrower `--unified` context — is **not** taken: the context width lives in the shared producer (`workflows/prompt.py:_brief_diff` → `_prompt_diff`), which also feeds L3.4's out-of-scope reconcile brief, so a registry-side cap is the diff's only lever here. An over-budget diff is replaced by an **explicit elision note** in `DIFF_UNAVAILABLE`'s style — never a silently shortened or empty section, because a reviewer that cannot see a fix cannot verify it — and it is distinguishable from the could-not-produce case by three pinned tokens: the word `elided`, size as the reason, and the numeric budget (`4000`); an in-budget diff renders byte-identically and `None` still means `DIFF_UNAVAILABLE`. (c) *Recording*: `StageRecord.rendered_chars` (prompt-fixed name, additive, `None` default, §9.2) records the rendered prompt's char count for the review-loop heads only (`stage_registry.is_review_stage`, `task-review-<n>`), on the real-run path only, with one `run.log` line; author/fix stages and `--dry-run` record neither, so E4.3's byte-identical `--dry-run` plan and round-1's deliberately unprimed rendering (the `unprimed_first` round never calls the renderer) are unchanged, and `BRIEF_DELTA`/`BRIEF_RECONCILE` are untouched. (d) *Acceptance bound*: the prompt-fixed round-2 acceptance bound is **24,000 chars** — the spec fixes no total, and 24,000 clears the budgeted ceiling (12,317 + ~2k of blocks + the 4,000-char diff cap ≈ 18.8k) while sitting under half the failure run's 55,636. Tests: `tests/test_stage_registry.py` (budget, elision, the len-equal boundary, purity, a seeded property sweep), `tests/test_runner.py` (the scoped record and `run.log` line), and the re-baselined `test_delta_brief_preserves_previous_review_verbatim`. (design §§8.1, 9.2, 15; `aidw/stage_registry.py`, `aidw/state.py`, `aidw/runner.py`) |
| Y1 | **The roadmap tick is its own core stage, `I7 update-roadmap`** (H3.1; design §8.2, EXTRACTION.md §3.5). `I3 update-traceability` carried two jobs with different owners: four SRD-specific artifacts that only some repos have (why I3 is repo-optional, D13) and the roadmap checkbox that every repo has and no repo may switch off — so `enabled: false` on I3 silently dropped the tick, and a repo with no catalog ran a stage whose only honest move was to report it owned nothing. The split: I3 keeps the four repo-specific artifacts, and `I7` (name `update-roadmap`, agent `recorder`, prompt `prompts/update-roadmap.md`) does the tick and nothing else. It is **core** (`STAGE_IDS` gains `I7`; `REPO_OPTIONAL_IDS` stays `{I3, I4}`), placed after `I5` and before the `approve-implementation-pr` gate and `I6`, because I6 is the single owner of the commit (§8.2) and the tick must land in the task's own PR. Prompt-fixed decisions, each recorded here because the spec fixed only the shape: the id is `I7` (the closed `I1`–`I6` vocabulary plus the roadmap's own "seventh stage"); the checkbox variable is the distinct field `{checkbox_id}` = `entry.task` (`H3.1`), because `{task_id}` already means I6's branch form `03-H3.1` and I7 never uses it; `{roadmap_file}` is the **resolved absolute path to the entry's own file**, so the prompt names no directory (D15's two readers — `run()` reads `paths.roadmap_dir`/`paths.roadmap_glob` from the resolved config **after** the locate, against the worktree the stages run in, design K1); and an already-`[x]` entry is a **successful no-op** — stage `succeeded` (never `skipped`, which H3.2 reserves for an evidence-withheld tick), `artifacts.tick: already` (vs `flipped`) and one `run.log` line naming the checkbox and the outcome, `error` unset. The workflow owns both halves of the honesty: before the stage it counts `(phase, task)` matches and refuses (stderr + exit 2, no stage, no run state) unless exactly one — `find_task`'s first match would tick the wrong entry on a duplicate — and after the stage it re-parses the same file and requires exactly the target line's `- [ ]` → `- [x]` with every other byte identical (the O1 precedent: an agent's exit 0 is not evidence the write happened), failing the stage on any other edit, a vanished entry or a duplicate. Both new fields are `implement` expansion fields threaded through `build_plan` and the `plan_stages` call; the pre-locate `--from` validation passes placeholders because it reads only stage names, so the F1 unknown-name refusal is unchanged. The edit stays uncommitted like every pre-I6 stage: I6 commits it. H3.2 (tick only behind recorded green gates) and H3.3 (share the tick with `fix`) are separate tasks; no new agent id is added (`recorder` gains a second section in `agents/recorder/AGENTS.md`). (design §8.2; EXTRACTION.md §3.5; `aidw/stage_registry.py`, `aidw/roadmap.py`, `aidw/workflows/implement.py`, `aidw/inventory.py`, `prompts/update-roadmap.md`, `prompts/update-traceability.md`; `tests/test_roadmap_tick.py`, `tests/test_implement_workflow.py`, `tests/test_plan_stages.py`, `tests/test_stage_registry.py`, `tests/test_override_integration.py`) |
| Z1 | **The roadmap tick is withheld unless the run's own evidence is green** (H3.2; design §8.2, §9.3, §14). I7 carries `when=WHEN_EVIDENCE_GREEN`, a new `when=` token that joins `findings`/`blocking`/`could-fix`/`unparseable` and is the only condition the expander cannot resolve: `_expand_static` only omits on `when=findings` with `findings is False`, so the value is **carried** onto `PlannedStage.when` and the additive `aidw.runner.StageSpec.when` (H3.3 reuses the same token for `fix`), and `plan_stages`, `build_plan` and `--dry-run` still plan I7 unconditionally. The **workflow** evaluates it instead of the agent, before `run_stage` is ever invoked and on **both** dispatch paths — the serial `execute()` and the `--parallel` member loop, which submits to the pool directly and whose group list `validate_parallel_groups` would happily let name `update-roadmap` — so no agent ever gets the chance to tick a box the run has no green evidence for. The rule is a pure function, `workflows/implement.py:tick_evidence`: green iff the tree has an identity, at least one `state.gate_outcomes` row is for exactly that tree, and **every** such row is `passed`; "no evidence" (zero matching rows, or no identity at all) is never green, because E4.8 is cite-or-run and never assume. Prompt-fixed decisions, recorded here because the spec fixed only the shape: (a) the tree is recomputed with `verification.tree_identity`'s **default** `base` (`verification.BASE_DEFAULT`, never `repo.base_branch` — the prompts pass no `--base`, so the recorded outcomes were all computed against the default and any other base matches nothing); (b) its `ignore` scope is the four **resolved** document write-targets `implementation_results_dir`, `architecture_dir`, `roadmap_dir`, `task_prompts_dir` (`TICK_EVIDENCE_IGNORE_PATHS`, canonicalised by `verification.normalise_ignore` so it equals what `aidw gate run` recorded), because they are the canonical scope `prompts/pr.md`/`prompts/record-implementation-results.md` declare and because the tick's own edit lands in `roadmap_dir`, which must not be part of the evidence checked against it; its `exclude` is the run's state root, exactly what the gate CLI excludes; (c) the outcomes are read from the **in-memory** run state, where H0.1's merge-on-write has already folded in every row a stage's `aidw gate run` subprocess appended — never a fresh `state.load` or a `run.log` parse, which would re-introduce the boundary loss H0.1 closed; (d) the observable record of a withheld tick is a **new status** `aidw.state.SKIPPED` (`skipped`, additive at the same `schema_version`) on a full `StageRecord` named `update-roadmap`, agent `recorder`, `status="skipped"`, and `model` = the recorder agent's resolved `qualified_model`, with `error` **unset** (it renders as a failure) and the reason in `artifacts[SKIP_REASON_KEY]` naming every failing `GateOutcome.key` plus the tree id — or the absence, with the tree id when one could be computed — plus one `run.log` line and a stage block whose `skipped:` line the operator reads (`aidw/report.py:stage_lines`); the model is resolved by `aidw.runner.stage_agent`, the same rule `run_stage` applies, so the skip names the agent it would have run; (e) the record is persisted the way `run_stage` persists its own — `aidw.runner.record_skipped` under `_STATE_LOCK`, `state.record_stage` then `save` — and is a **success** on both dispatch paths: no `state.status` stamp, no `state.resume` entry, no exit-status change, because the red gate already decided the run; (f) the skip is routed around `_settle_roadmap_tick` as well, since that helper runs whenever `exit_code in (None, 0)` and would otherwise stamp `tick: already` onto a stage that never ran. Green evidence leaves H3.1's behaviour untouched (`_settle_roadmap_tick`, `tick: flipped`/`already`), and an already-`[x]` box under green evidence stays that task's `succeeded` no-op rather than becoming `skipped`. Nothing else moves: I3/I4 stay ungated (E4.8's gate scope belongs to I5), which stages gate and what a red gate stops are unchanged, H0.1 owns the persistence it is read from, and H3.3 is the next task. (design §§8.2, 9.3, 14; `aidw/stage_registry.py`, `aidw/runner.py`, `aidw/state.py`, `aidw/workflows/implement.py`, `aidw/report.py`; `tests/test_roadmap_tick.py`, `tests/test_implement_workflow.py`, `tests/test_stage_registry.py`, `tests/test_report.py`) |
| Z2 | **`fix` ticks the same roadmap stage once its loop converges** (H3.3; design §§8.4, 8.2, 8.6, 9.2, 15; H3.1/H3.2). `fix` is where a task the review found wanting finishes — every `prompt-to-fix` chain ends there — and no stage of it had ever touched the roadmap, so a run that closed a task's last approved follow-up left the box unticked and `aidw tasks --next` kept offering the task while the tick existed in `implement` alone (which could also assert it twice). `I7 update-roadmap` is now **one module-level `StageDefinition`** in `aidw/stage_registry.py` beside `_APPROVE_STAGE` (one id `I7`, one prompt `update-roadmap.md`, one agent `recorder`, one name, variables `("{roadmap_file}", "{checkbox_id}")`, `when=WHEN_EVIDENCE_GREEN`), referenced from `_IMPLEMENT.stages` **and** from a new `WorkflowDefinition.post_loop`, so the two ticks cannot drift. `post_loop` is emitted only on request — `expand(..., include_post_loop=...)`, threaded through `plan_stages` — because `expand("fix", …)` *is* the per-iteration expansion (`fix.py:_planned_iteration` calls it once per iteration with only `pr`/`round_index`/`iteration`/`manifest_path`, and `_render` raises `StageFieldError` on a missing field, so an unconditional post-loop emission would break every `fix` plan **and** print the tick per iteration); one named post-loop planning call in `fix.py` expands it after the loop breaks on `EXIT_NONE_AVAILABLE` and at the end of the `--dry-run` plan, and the loop's stopped exits record the same `skipped` stage with the stop as its reason before returning. **Declared-list classification is now three-way**: `stage()`, `stages_by_id()`, `validate_stage_list()`, `plan_stages`, `declared_stage_issues` and `_warn_deferred_settings` all include the post-loop half, `validate_stage_list` classifies `fix`'s `I7` as **core** (removal/disable/reorder apply; it is not a loop id), `plan_stages` splits static / loop / post-loop three ways (the old `loop_ids = stages_by_id - static_ids` formula would call `I7` a loop id), `declared_stage_issues` resolves a declared `I7` by its registry prompt-file/agent (or the canonical `[A1, I7]` would be refused as repo-added, exit 2 before any run record) and `_warn_deferred_settings` no longer warns a correctly declared `I7` as repo-added-deferred in the name-keyed `fix`. A declared list covers both halves: `I7` is declared after every static core id (`[A1, I7]` today; its absence is the removal `ERROR`), the reorder rule compares the declared core subsequence against the registry's static-then-post-loop core order, and the declared plan renders declared static entries, then the loop unchanged, then declared post-loop entries (plan order is always static → loop → post-loop). **Prompt-fixed decisions**, recorded here because the spec fixed only the shape: (a) `fix`'s task id comes from the newest `implement` run's recorded `state.task` (`{phase, task, prompt_path}`) matched by `git.branch` — decision I1's re-read-the-run-state trade-off, never a `gh` query and never the PR title — and its **fallback** is the branch-pattern reversal, an anchored whole-branch match built from `string.Formatter().parse`'s literal/field structure that **enumerates every viable `(phase, task)` split** (`reverse_branch_pattern`) and requires exactly one that resolves to exactly one roadmap entry; zero or several splits, or zero/several entries, skip with a reason (exit 0) and never guess, because `03-H3-3` splits several ways and `roadmap.tick_entry`'s count check cannot catch a wrong-but-valid pair; the roadmap is read from the located PR-head worktree (K1). (b) The skip reason's `state.pr` key is `roadmap_tick_skip_reason` (the roadmap names `roadmap_ticked` only), alongside `roadmap_ticked` = `true` on a successful tick (flipped **or** already) and `false` on a skip or failed postcondition; the skipped `StageRecord` also carries `SKIP_REASON_KEY`. (c) `fix`'s `WHEN_EVIDENCE_GREEN` is its **own three-part rule** — `select` returned `EXIT_NONE_AVAILABLE`, every `iter{N}-test` record `SUCCEEDED`, `latest_verdict == Approve` — evaluated by the workflow before any `run_stage` and deliberately **not** a copy of H3.2's gate-outcome rule; an empty run (`latest_verdict is None`) is not green, because a run that closed nothing must not claim the task done. Green reuses `implement.settle_roadmap_tick` (made public; `_settle_roadmap_tick` stays as an alias) rather than duplicating the flip rule, and the skip is routed around it exactly as H3.2 routed `implement`'s. (d) The stage appears **once per run**, never per iteration, in `state.json`/`run.log`/the dry-run plan; the edit stayed uncommitted because no stage of `fix` committed (§13) — **superseded in part by Z9** (05-P1.1), which adds `F5 commit-and-push` after this tick without changing `I7`'s rule, position or gating. Gate impact: a declared `workflows.fix.stages` list must now include `I7`; `tests/test_plan_stages.py`'s fix-plan pin and `tests/test_fix_workflow.py`'s declared-list fixtures were re-baselined. H3.2's implement-side rule, phase 02's convergence rules, which stages gate, E4.8's gate scope and "move the tick to the merge" are all untouched. (design §§8.2, 8.4, 8.6, 9.2, 15; `aidw/stage_registry.py`, `aidw/runner.py`, `aidw/workflows/fix.py`, `aidw/workflows/implement.py`; `tests/test_stage_registry.py`, `tests/test_fix_workflow.py`, `tests/test_plan_stages.py`, `tests/test_run_workflow.py`) |
| Z3 | **A narrative summary is its own core `implement` stage, `I8 summarize-implementation-results`** (X1.1; design §§1.3, 2, 5.4, 8.2). This **reverses §1.3's "optional summary prompts … not as a workflow stage" non-goal**, scoped to exactly one summary: `I5 record-implementation-results` writes the audit artifact (`build-results.md` — files-changed table, gate rows, non-goals), which nobody reads to understand *why* a change was made, so a `recorder`-owned stage immediately after `I5` distils it into `<implementation_results_dir>/<branch>/summary.md`. Prompt-fixed decisions, recorded here because the spec fixed only the shape: the id is `I8` — the next free implement id after `I7`, retained forever per R6, and ids are already non-monotonic since `I7` precedes `I6`; the stage is **core** (`STAGE_IDS` gains `I8`, `REPO_OPTIONAL_IDS` stays `{I3, I4}`) because the summary is a generic artifact like `record`/`tick`/`pr`, and making it disableable would let a repo silently drop the artifact this decision exists to produce; it sits in `_IMPLEMENT.stages` **between `I5` and `I7`**, and that registry position is load-bearing for `validate_stage_list`'s reorder rule exactly as `I7`'s is — the declared core order becomes `[I1, I2, I5, I8, I7, I6]`, so a declared `workflows.implement.stages` list must include `I8` (its absence is the removal `ERROR`) and a reorder against the `I5 → I8 → I7` subsequence is refused; it runs **serially** between the two and is never added to `parallel_groups`. The **narrative structure is owned by the prompt**, not by config: five sections in a fixed order — the problem it was solving, the core idea, what was built piece by piece, what it deliberately did not do, and verification (honest about failures and `unverified` rows) — with the exact heading wording left as **implementer freedom** (no literal heading strings are fixed by this decision), and **no new `paths.*` key and no summary template** are added. Its inputs are `build-results.md` (the single source of truth for every fact it states), the task prompt under `paths.task_prompts_dir`, and the cited spec headings for purpose/scope/non-goals only. It is **read-only about evidence**: it runs no verification gate and re-runs no command, because `I5` is the only stage that buys the whole-repo gate and a second run would double the most expensive step for no new evidence; a recorded failure stays a failure and an `unverified` row keeps the reason `build-results.md` gives, and no fix is ever invented. It edits no code, tests, specs, roadmap or architecture docs and commits nothing (`I6` owns delivery), and `I5`'s prompt, gates, scope and artifact are unchanged. Because it writes only `<branch>/summary.md` inside the already-ignored `implementation_results_dir`, no gate-scope change is needed and `I7`'s `WHEN_EVIDENCE_GREEN` evidence is unaffected. Gate impact: a repo-declared `workflows.implement.stages` list must now include `I8`; `fixtures/target-repo/aidw/config.yaml` and every test fixture enumerating the implement chain were re-baselined, and `update-roadmap.md` and `summarize-implementation-results.md` are both post-cutover classes in `docs/migration/prompt-classification.md`. (design §§1.3, 2, 5.4, 8.2; `aidw/stage_registry.py`, `aidw/inventory.py`, `prompts/summarize-implementation-results.md`, `agents/recorder/AGENTS.md`; `tests/test_stage_registry.py`, `tests/test_plan_stages.py`, `tests/test_implement_workflow.py`, `tests/test_inventory.py`, `tests/test_summary_prompt.py`) |
| Z4 | **The stage chain has a shipped reader-facing reference, `docs/workflow-stages.md`** (design §§8, 12.2; D12/D13). §8 specifies each workflow and `aidw/stage_registry.py` holds the chains as data, but no single document said of every stage: which agent, which prompt, which positional arguments, which `when=` condition, which context block, in which workflow, and whether a repo may declare it — so the answer had to be assembled from §5.4's role table, §8's prose and the prompt files, and the operator guide had silently fallen two stages behind (its `aidw implement` block still listed `I1`–`I6` after `I8` and the `I7` tick landed). The new contract is a companion to `docs/target-repo-config.md` rather than a second copy of it: the config doc owns the *keys* and this one owns the *defaults they override*, and it states that split explicitly. Following the `docs/target-repo-config.md` precedent, the document is not trusted prose: `tests/test_workflow_stages_doc.py` parses its tables and asserts them against the registry — the workflow set is exactly `DEFAULTS`; each workflow's inventory rows match its definition **in order** (static, loop head/body/tail, post-loop) on id, runtime-name template, agent, prompt file, positional variables, `when=` token and context label; the id vocabulary is exactly `STAGE_IDS` plus the loop-internal labels with each id's kind derived by `validate_stage_list`'s own rule (loop ids subtracted first, so `fix`'s `I7` stays core) and the workflows it appears in; the condition and context tables name exactly the tokens the registry can emit, so a new `when=` or `extra=`/`brief=` cannot ship undocumented; the gates table matches each workflow module's gate constants; and every prompt file the tables name is in `inventory.REQUIRED_PROMPTS`. Each check was proved non-vacuous by mutating the document (agent, runtime name, kind, workflow cell, gate, condition, context, a dropped row and a renamed heading each fail). The same module pins `README.md`'s `aidw implement` block to the registry's static chain in order, which is the drift that motivated the task, and the README block is corrected to `I1`–`I8` with `I7` in its run position. Nothing about behaviour, stage ids or config semantics moves: this is a documentation contract plus its executable half. (design §§8, 12.2; `docs/workflow-stages.md`, `docs/target-repo-config.md`, `README.md`, `AGENTS.md`; `tests/test_workflow_stages_doc.py`) |
| Z5 | **The build results name the task's pull request at the top, immediately above `## Summary`** (design §§8.2, 9.2; `prompts/record-implementation-results.md`, `prompts/pr.md`). `I5` cannot know the number it is asked to state: it runs before `I6`, the only stage that opens the PR, and it is the stage whose recorded gate `I6` cites, so it cannot move after the PR either. The line is therefore written by two stages, in one direction only: the template carries a mandatory `**Pull request:**` line between `**Spec:**` and `## Summary`; `I5` fills it from a **read-only** lookup (`gh pr view <branch> --json number,url`, silent when absent) with `#<n>` and its URL when a PR already exists — a re-run, a resume, or `aidw implement --pr <n>`, whose number is already in `state.pr` — and otherwise with the literal `not yet opened — the /pr stage records it here once the PR exists`, since a fabricated number is worse than an honest absence; `I6` then replaces that one line with the number `gh pr create` printed, commits it on the branch and pushes. Two constraints keep the backfill free: the edit lands inside `implementation_results_dir`, which every gating stage declares in its `--ignore` scope, so no recorded gate outcome is invalidated and `I6` buys no second suite to make it (it re-runs no gate); and the line is never derived from a branch name, task id or run id. `I5`'s owned artifact, gates and scope are otherwise unchanged, and no new config key, stage, variable or template file is added. (design §8.2; `docs/implementation-results/TEMPLATE.md`, `prompts/record-implementation-results.md`, `prompts/pr.md`, `agents/pr-publisher/AGENTS.md`, `docs/workflow-stages.md`; `tests/test_build_results_doc.py`) |
| Z6 | **A human-run integration-test guide is its own core `implement` stage, `I9 write-integration-test-guide`** (X1.2; design §§1.3, 2, 5.4, 8.2). §1.3's “deployed integration tests” non-goal still holds — AIDT never runs one — but the change a task makes is often only really provable by hand: a real CLI invocation, a browser flow, a cloud action. `I5 record-implementation-results` records the evidence that *was* collected, and nothing turned that record into a procedure a human could follow, so a `recorder`-owned stage immediately after `I8` writes `<implementation_results_dir>/<branch>/integration-test-guide.md` beside the build results and summary. It is an **instruction document, never an execution**. Prompt-fixed decisions, recorded here because the spec fixed only the shape: the id is `I9` — the next free implement id after `I8`, retained forever per R6, and ids are already non-monotonic since `I7` precedes `I6`; it sits in `_IMPLEMENT.stages` **between `I8` and `I7`**, and that registry position is load-bearing for `validate_stage_list`'s reorder rule exactly as `I8`'s and `I7`'s are — the declared core order becomes `[I1, I2, I5, I8, I9, I7, I6]`, so a declared `workflows.implement.stages` list must include `I9` (its absence, disable or reorder is an `ERROR`), and it runs **serially**, never in `parallel_groups`; the stage is **core** (`STAGE_IDS` gains `I9`, `REPO_OPTIONAL_IDS` stays `{I3, I4}`) and **unconditional** like `I8` — no new `when=` token — because the guide is a generic artifact every repo has, and a disableable one would let a repo silently drop the artifact this decision exists to produce. The **guide's structure is owned by the prompt**, not by config, with **no new `paths.*` key and no template**: four sections in a fixed order — what the guide covers, the scenarios, teardown, and an honest “could not be exercised in this environment” section — with the exact heading wording left as implementer freedom. The scenario section and the two closing sections are roadmap-fixed rather than prompt-fixed: every scenario carries **five** fields — prerequisites, the exact command(s)/steps, the expected observable result, how to tell pass from fail, and any cost/permission/destructive warning — and both teardown and the “could not be exercised” section are mandatory, because claiming coverage the guide cannot confirm is fabrication. Its inputs are `build-results.md` (read in full), the task prompt under `paths.task_prompts_dir`, and the branch's changed files through **read-only** `git` (`git diff --name-only`, `git status`, file reads); every scenario must be traceable to a changed file, a build-results row or the task prompt, and a flag, subcommand, route or endpoint it cannot confirm against the tree is reported **unconfirmed** with its reason rather than guessed (X1.1's no-invented-results trap, restated for commands). It executes **nothing** — no integration test, no verification gate, no command touching a cloud account, a browser or a deployed stack — so §1.3's non-goal is preserved, amending that bullet to name `I9` without reversing it; recorded failures and `unverified` rows stay as `I5` recorded them. It edits no code, tests, specs, roadmap or architecture docs and commits nothing (`I6` owns delivery). The prompt file is `prompts/write-integration-test-guide.md`, deliberately **not** `integration-tests.md`: that is a product prompt MF owns (`docs/migration/prompt-classification.md`), and a target repo's same-named file would shadow it by filename (D14), silently swapping this stage's prompt. No new agent id (`recorder` gains a fourth `AGENTS.md` section), no new config key, template or `parallel_group` member. Because it writes only `<branch>/integration-test-guide.md` inside the already-ignored `implementation_results_dir`, no gate-scope change is needed and `I7`'s `WHEN_EVIDENCE_GREEN` evidence is unaffected. Gate impact: a repo-declared `workflows.implement.stages` list must now include `I9`; `fixtures/target-repo/aidw/config.yaml` and every fixture/test enumerating the implement chain were re-baselined, and `write-integration-test-guide.md` joins `docs/migration/prompt-classification.md`'s post-cutover class (iv). (design §§1.3, 2, 5.4, 8.2, 12.2; `aidw/stage_registry.py`, `aidw/inventory.py`, `aidw/workflows/implement.py`, `prompts/write-integration-test-guide.md`, `agents/recorder/AGENTS.md`; `tests/test_integration_guide_prompt.py`, `tests/test_stage_registry.py`, `tests/test_plan_stages.py`, `tests/test_implement_workflow.py`, `tests/test_inventory.py`, `tests/test_prompt_classification.py`, `tests/test_design_doc.py`, `tests/test_workflow_stages_doc.py`) |
| Z7 | **A tick must also agree with the task's recorded Done-when verdict** (design §8.2; PR #282, 2026-11-15). H3.2 withholds the tick behind a red gate; PR #282 proved that is not the whole question. `04-A1.1` ran with every gate green (`lint`, `build`, `suite`, `smoke`, a scoped `docs:check-completions`) *and* a `build-results.md` concluding the task's Done-when was unmet (the fixture's contract suite failed at recording time), so the tick was a completion claim the run's own recording contradicted. The stage could not repair it: `verify_checkbox_flip` allows the checkbox and nothing else, so an agent told to tick a contradicted entry could only fail or edit bytes it was forbidden to touch — which is what happened (a re-opened box plus an explanatory sub-bullet, `roadmap tick postcondition not met`). The workflow now applies the recorded verdict as a second rule beside H3.2's: `aidw.roadmap.recorded_unmet_conclusion` reads `<implementation_results_dir>/<phase>-<task>/build-results.md` (padded directory first, then the unpadded form older result trees use) and `find_unmet_conclusion` reports the first line that both *names* the Done-when and *denies* it. Prompt-fixed decisions, because the spec fixes none of them: (a) the rule is **narrow on both sides** — a gate row that merely quotes the Done-when command is not a conclusion, and a distant `not` (`… is met; the earlier attempt was not reviewed …`) must not manufacture one — because a false positive withholds a legitimate tick; the negation must sit within four words of `met`, and markdown emphasis is stripped before matching because the record stage bolds it (`is **not** met`); (b) a **missing** document is not a contradiction, so a repo that records no build results keeps H3.2's behaviour exactly; (c) the verdict **withholds**, never fails, and the reason names `docs/…/build-results.md:<line>` first, because that document is the thing to fix; (d) `fix` applies the identical rule at its post-loop check (H3.3: one rule, two workflows), since a converged loop can leave the same stale-verdict state; (e) it is evaluated **after** H3.2's green verdict and reported with the same `skipped` record, `SKIP_REASON_KEY` and `run.log` line, so the two withholdings are indistinguishable in shape; (f) `recorded_unmet_conclusion` takes the resolved `paths.implementation_results_dir` **value**, so `aidw/roadmap.py` still carries no product-specific directory (D15). Nothing about H3.2's gate ladder, `verify_checkbox_flip`, which stages gate, or `fix`'s convergence rules moves; a refreshed build-results document makes the tick legal again, which is how `03-H3` was reconciled target-side. (design §8.2; `aidw/roadmap.py`, `aidw/workflows/implement.py`, `aidw/workflows/fix.py`; `tests/test_roadmap_tick.py`, `tests/test_implement_workflow.py`) |
| Z8 | **A later round's per-finding verdict is not a new finding** (design §8.1, §18; PR #282 / `04-A1.3`, 2026-11-16). Two accepted requirements contradicted each other in practice: H2's delta brief *requires* every round after the first to give a per-finding `resolved` / `not resolved` / `newly contradicted` verdict on the previous findings, and M2 fails closed when an `Approve` carries `must-fix`/`should-fix` findings. `findings.parse_review_findings` had no notion of a round: it took every block's `Priority:` as a current priority, so a second-round review that resolved both findings and approved read as "Approve with 2 blocking findings" and the run stopped `BLOCKED` (`verdict=Approve; revisions=1; max_revisions=3; rounds=2; findings=2/2; fixes=2/0`) even though its own text said *"prior findings resolved, no new defects"*. The reviewer had done nothing wrong — the state machine had no word for *already resolved*. Fixed without touching the prompt or the M2 rule: `ParsedFinding.resolution` is parsed from an optional `Verdict on this finding:` line (added to the label map so it stops being appended to the preceding `Where` field's text — before this change that prose was folded into `Where`), `normalise_resolution` prefix-matches the three canonical tokens and tolerates trailing prose (`resolved. The current prompt conditions …`), and `partition_findings` excludes `RESOLVED` findings from **both** lists: they need no fix stage and must never be handed to the could-fix batch, which would ask an agent to fix something already closed. The lengths therefore no longer sum to `len(findings)`; the record keeps everything, because `to_manifest` still publishes every parsed finding. Prompt-fixed decisions: (a) *only* `resolved` clears — `not resolved`, `newly contradicted`, an absent verdict and an unrecognised one all stay blocking, so the fail-closed direction is preserved and round 1 behaves exactly as before; (b) an unrecognised verdict is **not** a `problems` entry, because a wording quirk must not fail an otherwise valid review — it simply does not clear the finding; (c) `_finding_text_block` re-emits the verdict when present, so `render_previous_review`'s shrink-to-structured-brief path cannot silently turn a closed finding back into an open one. Tests: `tests/test_findings.py` reproduces the blocking review (both resolved → zero blocking), and pins `not resolved`/`newly contradicted`/absent/unrecognised as blocking, the could-fix interaction, the `Where`-field separation, and the re-render round trip. Nothing about M2, H2's brief, the publisher, or `prompts/task-review.md` moves. (design §§8.1, 18; `aidw/findings.py`; `tests/test_findings.py`) |
| Z9 | **`fix` publishes its own work: `F5 commit-and-push` is a core post-loop stage** (05-P1.1; design §§8.4, 13, 18). This **reverses §8.4's "The edit stays uncommitted: no stage of `fix` commits (§13)"** and the §13 clause it cites, because that boundary was wrong where it mattered: `F1` closes each follow-up issue as `Status: fixed` in-stage, so a `fix` run reported work done while its fixes — and the shared `I7` roadmap tick — stayed uncommitted in the PR-head worktree and never reached the PR (PR #300: one fix commit unpushed, two fixes uncommitted, all three follow-up issues closed). `F5 commit-and-push` (agent `pr-publisher`, prompt `prompts/fix-commit.md`, variables `("{pr}",)`) is emitted from the same `WorkflowDefinition.post_loop` half as `I7`, **after** it, once per run; it is **core** (`STAGE_IDS` gains `F5`; `REPO_OPTIONAL_IDS` stays `{I3, I4}`, so removal, disable and reorder rules apply and a declared `workflows.fix.stages` list becomes `[A1, I7, F5]`), it carries **no `when=` token** (its trigger is the loop's convergence, not green evidence), and the agent executes `git add -A` / `git commit` / `git push origin <branch>` while Python only decides whether and verifies what landed (§8.4's four-case table and the `HEAD` vs `origin/<branch>` comparison). **The row also records P1.2's ordering**: closing a follow-up issue must move to *after* this push, since a close that precedes the push is the untruthful state this change removes — one reversal, one decision, with P1.2 implementing the close-after-push side rather than opening a second row. **Prompt-fixed decisions**, recorded here because the spec fixed only the shape: (D1) id `F5`, runtime name `commit-and-push`, agent `pr-publisher`, prompt `fix-commit.md`, `variables=("{pr}",)`, placed in `_FIX.post_loop` after `_ROADMAP_TICK_STAGE`, `STAGE_IDS` gains `F5`, `REPO_OPTIONAL_IDS` unchanged, and no `when=`; (D2) `F5`'s trigger is convergence — `fix`'s `WHEN_EVIDENCE_GREEN` (`tick_evidence`) stays `I7`'s completion claim only, so a converged run whose tick was withheld by Z7's unmet-conclusion check, an empty run, and a run whose roadmap target could not be resolved are all still runs whose fix edits must land; (D3) the four-case table over the pre-stage tree and this run's own accumulated `closed_issues` (never a `gh` query, never a count of `Status: fixed` comments): dirty + ≥ 1 closed → commit, push, verify, record `head_sha`, exit 0; dirty + 0 closed → **skip** ("this run closed no issue; the working-tree changes are not this run's", §13's preservation of unrelated changes); clean + 0 closed → **skip** (the roadmap's successful no-op, no empty commit); clean + ≥ 1 closed → **fail closed** (exit non-zero), the untruthful state P1.2 makes unrepresentable by moving the close behind the push; (D4) a stopped loop never commits and never pushes — every stop path returns before the post-loop and the single `stop()` helper records `F5`'s skip with the same reason as `I7`'s (no `record_skipped` at each `return`), while a **failed** `I7` stage keeps exit 1 and leaves `F5` neither planned nor recorded; (D5) the agent commits and pushes; `<branch>` is the PR head the preflight resolved (`pr_info["headRefName"]`, decision K1), never `git.current_branch` of the control root, no `-u`/`--force`/merge, and `<branch> == repo.base_branch` is refused **before** any push; (D6) the pushed proof is `git.rev_parse(worktree, "HEAD")` vs `git.rev_parse(worktree, "origin/<branch>")` — no fetch, no `ls-remote` (a successful push updates the remote-tracking ref) — and an unequal or unresolvable pair, a non-`SUCCEEDED` record or a tree still dirty afterwards fails the run; (D7) `state.pr["head_sha"]` is the verified remote SHA, written only when D6's equality holds, a skip writes `state.pr["commit_skip_reason"]` (mirroring Z2's `roadmap_tick_skip_reason`) and the skipped `StageRecord` carries `SKIP_REASON_KEY`; no third key, because `head_sha`'s presence *is* the boolean; (D8) `variables=("{pr}",)` and nothing new is threaded — the branch and the task id are read inside the PR-head worktree as `prompts/pr.md` does, and `{task_id}` keeps its I6-only branch-form meaning; (D9) the contradiction is fixed at the source: `agents/pr-publisher/AGENTS.md` scopes its hard rules by prompt (`/pr` commits, pushes, opens the PR and backfills the build-results line; `/fix-commit` commits and pushes only — no `gh pr create`, no body sections, no build-results edit), because prompt text alone does not reliably override an agent file's hard rules; (D10) `--dry-run` plans `commit-and-push [planned]` exactly once after `update-roadmap` and evaluates no evidence — it inspects no tree and never withholds. **P1.2's prompt-fixed decisions**, appended to this row rather than opened as a second one (the close-after-push ordering is this reversal's other half, and the spec fixed only its shape): (P1.2a) the deferred close is the new subcommand `review_followup.py close --pr <n> --issue <n> --body-file <path> [--dry-run]`, resolved by `--issue` **alone** — the just-fixed child is in flight, not first-available, so reusing `fixed`'s selection would refuse every close after the first with `EXIT_CONFLICT` — while `fixed` is **kept** and shares the same close tail (`logic.close_plan` plus one `apply_close`), so the §7.2 strict-equality marker, the label guard, refuse-to-reopen, `closing_body_repeats_status` and the `EXIT_VERIFY_FAILED` post-close check cannot drift; `COMMANDS` gains `close`, and the `--help` text and `prompts/scripts/review-followup/README.md` list it; (P1.2b) the closing body lives at the **absolute** `<run_dir>/artifacts/iter{N}-closing-body.md`, threaded as F1's new `{closing_body}` variable and carried by each `closed_issues` entry as `closing_body` — absolute because F1 runs with the target repo as its cwd (a relative path would put the body in the pushed diff), and the fixer's own body rather than a Python-composed one because a generic body would drop its verification results; (P1.2c) the close is **Python's** job, not an agent's: `aidw/workflows/fix.py` runs one `close` per recorded entry after `run_commit` verifies the push (`HEAD` moved, `HEAD == origin/<branch>`, clean tree, `head_sha` written), and `F5`'s scope stays commit-and-push only (D9's prompt-scoped rule); (P1.2d) it fails closed **only where a close is pending** — a non-zero `close` exit fails the run (exit 1) naming the PR, the branch and the issue, a recorded entry with no verified push closes nothing and exits non-zero, and a run that recorded no entry keeps D3's skip (exit 0, no close); (P1.2e) one `close` per entry, never a batch and never a count of `Status: fixed` comments, so one fix stays one issue and a batch failure cannot strand an issue half-closed; no reopen path is added, because the roadmap's "or is reopened" covers only the pre-P1.2 transitional state and nothing now closes before the push; (P1.2f) the instructions were fixed at the source — `prompts/fix-next-review-followup.md` (intro, §0 command list, §7, §8 and the Final report) **and** `agents/fixer/AGENTS.md`, because D9's lesson is that prompt text alone does not override an agent file's hard rules. P1.2 gate impact: F1's variables grow to `("{pr}", "{closing_body}")`, so `tests/test_plan_stages.py`'s fix-plan variables pin and `docs/workflow-stages.md`'s F1 variables cell were re-baselined; `tests/test_fix_workflow.py`, `tests/test_design_doc.py` and `prompts/scripts/review-followup/tests/` (`test_logic.py`, `test_close.py`) carry the new proofs. Nothing else moves: `I7`'s gating, `F1`'s close (now the workflow's), the `approve-fix-pr` gate and `implement`'s `I6 pr` are untouched, no agent id is added and the `pr-publisher` allowlist is unchanged. Gate impact: `tests/test_stage_registry.py`'s post-loop pins and `tests/test_plan_stages.py`'s fix-plan pin were re-baselined to `(I7, F5)` / `[…, I7, F5]` / `[A1, I7, F5]`, `tests/test_fix_workflow.py`'s `test_a_converged_fix_leaves_the_roadmap_edit_uncommitted` was replaced by the D3 cases, and `fix-commit.md` joins `REQUIRED_PROMPTS` and `docs/migration/prompt-classification.md`'s post-cutover class (iv). (design §§7.2, 8.4, 13, 17, 18; `aidw/stage_registry.py`, `aidw/workflows/fix.py`, `aidw/inventory.py`, `prompts/fix-commit.md`, `prompts/fix-next-review-followup.md`, `prompts/scripts/review-followup/review_followup.py`, `prompts/scripts/review-followup/logic.py`, `prompts/scripts/review-followup/README.md`, `agents/pr-publisher/AGENTS.md`, `agents/fixer/AGENTS.md`, `docs/workflow-stages.md`, `README.md`; `tests/test_fix_workflow.py`, `tests/test_stage_registry.py`, `tests/test_plan_stages.py`, `tests/test_inventory.py`, `tests/test_design_doc.py`, `tests/test_workflow_stages_doc.py`, `prompts/scripts/review-followup/tests/test_logic.py`, `prompts/scripts/review-followup/tests/test_close.py`) |
| Z10 | **An in-scope tester `Fail` withholds `I6` and opens no PR** (Q1.1; design §§8.2, 18). The `test` stage exits 0 whether it passes or fails — the verdict is prose in its final message, not its stage status — so `implement` ran `I6 pr` over an in-scope `Fail`, opened the PR, and the reviewer then re-found the same defects and the `fix` loop re-fixed them (one defect was found independently by the tester, the reviewer and the fixer in a single task). The workflow now parses the verdict itself, the way §8.3 parses `R1`'s, and decides; the tester's stage stays `SUCCEEDED`. Gate impact: `prompts/test.md` gains the declaration block (so `fix`'s `F2 test` emits it too — `fix.py` reads only the stage *status*, never the message, and no verdict parse is added there); no stage id, no `when=` token, no `REQUIRED_PROMPTS` entry and no registry change. **Prompt-fixed decisions**, recorded here because the spec fixed only the shape: (a) the tokens are `Test verdict: Pass` / `Test verdict: Fail` plus, on `Fail`, `Failing in-scope criteria: <comma-separated criterion IDs/wording>` — §8.2 names none, and `prompts/test.md` is the contract that emits them, so the prompt and the parser are edited together (§7.2's drift rule); the declaration is a **bare line** (no heading, code span or fence), matching §18 M3's `Verdict: Approve` rule, and the per-criterion block gains a `Scope:` line so `Unverified`, out-of-scope and pre-existing/unrelated failures are auditable as *not* verdict-deciding; (b) the stop is `state.status = BLOCKED` + exit 3, fail-closed on an unparseable verdict **and** on a missing or empty recorded `out.txt` — §18's `Blocked`/ambiguous precedent from §8.3, not §8.2; a missing `Failing in-scope criteria:` line on a `Fail` is not ambiguity, the criteria are best-effort naming; (c) the check is an **imperative gate in the workflow**, `aidw/workflows/implement.py:_test_verdict_stop` + the pure `_parse_test_verdict`, placed **after** the pre-PR block (I1..I9, I7 on both the serial and `--parallel` paths) and **before** `approve-implementation-pr` — not after I2, no new stage id, no registry `when=` token and no `--dry-run` evaluation (the dry-run path returns before the gate); the parser lives in `implement.py`, not `verdict.py`, because its `Test verdict:` label carries no meaning of its own and `verdict.py`'s `DECLARATION_RE` deliberately accepts backticked tokens, which this gate must reject (a copy would read a quoted example as a verdict); (d) the **resume rule** — a plain `--resume` skips the already-`SUCCEEDED` I2 and re-reads the same recorded verdict, repeating the stop identically (correct, not stuck), while re-testing requires `--from test` with `--resume` to stay in the same run, overriding §9.4's completed-stages-never-rerun rule — follows §9.4's semantics and is named in both stop messages because otherwise the first real `Fail` presents as a dead end. `I7` is deliberately **not** withheld: with green gates but an inspection-only `Fail` the tick can still flip the checkbox uncommitted, which is acceptable because `I6` is the only committer and never runs; aborting before I3–I9 is the explicit non-goal. (design §§8.2, 9.4, 18, 17; `aidw/workflows/implement.py`, `prompts/test.md`; `tests/test_implement_workflow.py`, `tests/test_design_doc.py`) |
| Z11 | **A stage can be scoped to the paths it owns: `WHEN_PATHS_CHANGED` and `I3`'s `when_paths`** (S1.1; design §§8.2, 12.2, 17 Z1/Z4). Traceability is the first stage whose work is only sometimes present: `I3` updates a repo's traceability artefacts, and a change that touches none of the trees those artefacts describe has nothing for it to do, yet it ran (and cost a full agent invocation) on every `implement` run. The fix is a second **carried** condition beside H3.2's: `stage_registry.WHEN_PATHS_CHANGED = "paths-changed"` joins `findings`/`blocking`/`could-fix`/`unparseable`/`evidence-green`, `_expand_static` is unchanged (it still omits only on `when=findings` with `findings is False`), so the value rides `PlannedStage.when` onto the additive `runner.StageSpec.when` and `plan_stages`/`build_plan`/`--dry-run` still plan `I3` in its run position. The paths are a **repo declaration**, the new optional stage field `when_paths` (a list of repo-relative path prefixes in `workflows.<name>.stages[]`), and `I3`'s registry definition carries **no default path set**: the roadmap's “rules-engine sources, `docs/rules-coverage`, the vector-matrix directories” is the Mythical Forge audit example, and hardcoding it in `aidw/stage_registry.py` would be a product literal in the toolkit (§7.1, the §17 S1 neutralisation) — no gate scans `aidw/*.py` for such literals (`test_prompt_neutrality.py` reads `prompts/`, `test_agent_guidance_neutrality.py` reads `agents/*/AGENTS.md`), so the principle, not a failing test, is the guard. **Prompt-fixed decisions**, recorded here because the spec fixed only the shape: (a) the config key is `when_paths`, and the roadmap's “`aidw/config.py`” is imprecise — stage fields live in `aidw/target_config.py` (`aidw/config.py` is *agent* config, §5), so the field is `STAGE_KEYS`/`StageConfig`/`_parse_stage`/`to_dict` there, mirrored in `docs/schema/aidw-config.schema.json`'s `stage` node and the `docs/target-repo-config.md` stage-entry table; (b) the empty set is the toolkit default and means **unconditional** — today's behaviour — so a repo that declares nothing keeps running `I3`, and no top-level `paths.*` key is added (the set is per stage, not global); (c) touching is `path == prefix or path.startswith(prefix + "/")`, the rule `verification._excluded` applies to a gate's declared scope, after `verification.normalise_ignore` canonicalises the declared prefixes, and a **`None` change set runs the stage** — `git.changed_paths` returns `None` only when the base is unresolvable and an empty list is a real answer, so “cannot prove” must never skip; (d) the change set is the one `I7`'s evidence already measures — `git.changed_paths(repo_root, verification.BASE_DEFAULT)` plus `git.untracked_paths`, with the run's state root excluded as `tree_identity` excludes it, never `repo.base_branch` — and it is evaluated in the same two dispatch points as H3.2's condition (the serial `execute()` and the `--parallel` `withhold_stage` member filter; a repo-declared group may legally name `update-traceability`), before `run_stage`, so no agent runs a stage the change set proved irrelevant; (e) a skip is a **cost-control decision, not a gate verdict**: `runner.record_skipped` under `_STATE_LOCK` records a full `StageRecord` (status `skipped`, agent and `qualified_model` resolved by `runner.stage_agent`, `error` unset, the reason in `SKIP_REASON_KEY` naming the declared prefixes), one `run.log` line and the stage block, with no `state.status`/`state.resume` write, because a stage the run does not need is not a failure; the reason says “no changed path matches the declared when_paths (…)”, so the operator can see which declaration decided it. The loader is fail-closed (§12.1, mirroring `_parse_parallel_groups`): a non-list value is one `ERROR` naming `…when_paths` and the field is dropped, and each bad entry (a non-string, an absolute path, `.`, `..`, or empty) is one `ERROR` naming its own dotted entry path and is dropped while parsing continues, with the surviving entries normalised, sorted and deduped by `normalise_ignore` (the helper's `ValueError` is converted, never propagated); `StageSpec.when_paths` is read from the declared entry **type-guarded**, so a directly-passed dict degrades to the unconditional default. Nothing else moves: `_expand_static`, `record_skipped`'s contract, `STAGE_IDS`/`REPO_OPTIONAL_IDS`, every other stage's `when=`, which stages gate and what a red gate stops are all untouched, and `I3` is not gated on `WHEN_EVIDENCE_GREEN` (path membership, not evidence). **S1.2 is the next task**: gating `update-architecture` on the same token, a repo-declared architecture trigger set and an `aidw doctor` warning when the set is empty are deliberately out of scope here. Gate impact: a new `when=` cannot ship undocumented (Z4), so `docs/workflow-stages.md`'s Conditions table and `I3`'s `when=` cell gain `paths-changed` and `tests/test_workflow_stages_doc.py`'s token set and `tests/test_stage_registry.py`'s vocabulary and carried-`when` map were re-baselined (the roadmap's test list omitted those two files); `docs/target-repo-config.md`'s `EXPECTED_DEFAULTS` gains `when_paths: unset`. (design §§8.2, 12.2, 17; `aidw/stage_registry.py`, `aidw/runner.py`, `aidw/target_config.py`, `aidw/workflows/implement.py`, `docs/target-repo-config.md`, `docs/schema/aidw-config.schema.json`, `docs/workflow-stages.md`; `tests/test_stage_registry.py`, `tests/test_plan_stages.py`, `tests/test_implement_workflow.py`, `tests/test_target_config.py`, `tests/test_workflow_stages_doc.py`, `tests/test_target_repo_config_doc.py`, `tests/test_design_doc.py`) |
| Z12 | **`I4 update-architecture` is path-scoped with a product-neutral `docs/architecture` default and a doctor warning for an empty set** (S1.2; design §§8.2, 12.2, 17 Z11; `aidw/stage_registry.py`, `aidw/runner.py`, `aidw/doctor.py`, `docs/target-repo-config.md`, `docs/workflow-stages.md`; `tests/test_stage_registry.py`, `tests/test_plan_stages.py`, `tests/test_implement_workflow.py`, `tests/test_doctor.py`, `tests/test_design_doc.py`, `tests/test_workflow_stages_doc.py`, `tests/test_target_repo_config_doc.py`). S1.1 fixed the token and the repo-declared `when_paths` override for `I3`; `I4` was still unconditional and bought an architecture agent invocation on every `implement` run, even when the change set touched nothing the architecture documents describe. `I4` now carries the same `WHEN_PATHS_CHANGED = "paths-changed"` token (no new token, and `_expand_static` is unchanged: it still omits only on `when=findings`, so `plan_stages`/`build_plan`/`--dry-run` plan `I4` in position and a dry run evaluates nothing) and is evaluated by the existing `paths_changed_reason`/`withhold_stage` dispatch on **both** paths (serial `execute()` and the `--parallel` member filter, which is the common path because `[test, update-architecture]` is the default `parallel_groups` pair). `StageDefinition` and `PlannedStage` gain an optional `when_paths: tuple[str, ...] = ()` field so a definition can carry a registry-default trigger set; `I4`'s is `("docs/architecture",)`. The value travels the same way `when` does. The skip is S1.1's `runner.record_skipped` shape exactly — `skipped`, `error` unset, the reason in `SKIP_REASON_KEY` naming the prefixes, one `run.log` line, no `state.status`/`state.resume` write — because it is a **cost-control skip, not a gate verdict**, and `git.changed_paths` returning `None` (an unresolvable base) **runs** `I4` rather than skipping on "cannot prove". Repo-declared diagram-input paths reuse the existing `when_paths` field: no new config key, no new `paths.*` key and no schema change. `aidw doctor` gains `_check_architecture_trigger`: when `I4` is **enabled** and its effective trigger set is **empty**, it reports a WARN naming `I4 update-architecture` and telling the operator to declare `docs/architecture` plus their diagram-input paths; an absent `when_paths` (the default applies), a non-empty list, or a disabled `I4` does not warn. **Prompt-fixed decisions**, recorded here because the spec fixed only the shape: (a) the default is the **prefix** `docs/architecture`, not the roadmap's informal `docs/architecture/**`: S1.1's matcher is `verification._excluded`'s `path == prefix or path.startswith(prefix + "/")`, so a glob entry would never match and `I4` would never run; (b) a repo-declared list **replaces** the default and never merges with it — **confirmed by the task owner on 2026-11-20** — keeping S1.1's override semantics unchanged; merge is self-defeating here because under merge an absent key and an explicit `[]` both resolve to the default, the effective set is never empty, and the doctor warning (requirement 6 and Z11's own "warning when the set is empty") is unreachable, so `docs/target-repo-config.md` tells a repo naming diagram inputs to re-list `docs/architecture` itself; (c) "declares no trigger set" means an **explicitly empty** `when_paths: []` — the only reachable empty/effective-unconditional set — while an absent key falls back to the default and does not warn, as the roadmap Notes ("warn when the set is empty") and Z11's S1.2 sentence fix; (d) the warning fires only when `I4` is **enabled**: a disabled stage has no write-target to justify one. The default is the **literal** D17 `architecture_dir` default, never the repo's resolved `paths.architecture_dir` (repo-configurable in `aidw/target_config.py`), so a repo with a custom architecture dir must declare its own `when_paths` or `I4` watches a directory the repo does not use and skips perpetually; the value is product-neutral (the toolkit's own default, unlike S1.1's deliberately empty `I3` default) and no repo's diagram-input directories are hardcoded. Absent-vs-empty survives onto `StageSpec.when_paths` through `runner._declared_when_paths_or_none` (the loader's `None`/`[]` distinction), because the workflow evaluates that one value. Gate impact: no new `when=` token, config key or gate; `docs/workflow-stages.md`'s `I4` `when=` cell changes `—` → `paths-changed`, its I4 prose gains the default/doctor sentence, and the `tests/test_workflow_stages_doc.py` / `tests/test_stage_registry.py` pins were re-baselined (Z4's "a `when=` change cannot ship undocumented"). |
| Z13 | **The roadmap entry is `I7`'s file alone: `I3` must never edit `paths.roadmap_dir`** (05-S1.2 implement run `20261119T211427Z-05-S1.2-implement`; design §§8.2, 12.2, 17 Z11; `prompts/update-traceability.md`, `aidw/conventions.md`, `aidw/workflows/implement.py`, `aidw/roadmap.py`; `tests/test_roadmap_tick.py`, `tests/test_design_doc.py`). Run `20261119T211427Z` reached `I7` with every gate green — `suite` 2265 passed, plus `traceability`, `build`, `doctor`, `prompts` and `agents` — and still failed: `roadmap tick postcondition not met: the \`S1.2\` tick changed more than the \`- [ ]\` -> \`- [x]\` checkbox on line 77; every other byte must be unchanged`. `I7` had edited nothing (it reported `already [x], file unchanged`); the bytes came from `I3`, which had decided the roadmap entry under `paths.roadmap_dir` was the repo's only traceability artefact — this repo has no `aidw/conventions.md` and no generated matrix — so it both ticked the checkbox and rewrote the entry's `Done when` / `Deliverable` / `Tests` / `Notes`. The two contracts cannot both hold: `settle_roadmap_tick` (`aidw/workflows/implement.py`) applies `roadmap.verify_checkbox_flip` against `tick_before`, a snapshot read at **run start**, and that rule requires the whole line list to match with exactly one `- [ ]` -> `- [x]` substitution — deliberately, because a weaker "this line now starts with `[x]`" check would pass a reformat, a reflow or an edited neighbour, the H3.1 defect that PR #282 exposed. **Decision:** the roadmap is the plan of record, owned **byte-exclusively** by `I7`; `I3` maintains the repo's traceability artefacts and never a roadmap entry, so a repo whose only candidate artefact is the roadmap gets **no `I3` edit** — reporting "None for traceability" is the correct outcome, not a licence to adopt the roadmap. A task entry's `Done when`/`Deliverable`/`Tests`/`Notes` are fixed at authoring time; a mid-implementation correction belongs in the task prompt or here in §17, never in the roadmap. **Enforcement (landed, W1.1):** the rule now lives in two places authored on branch `05-W1.1`. First, `prompts/update-traceability.md` states the hard rule (never edit anything under `paths.roadmap_dir`; `/update-roadmap` owns it byte-exclusively; a repo whose only candidate artefact is the roadmap reports "None for traceability" as a valid outcome, never a licence to adopt it), names `paths.roadmap_dir` in its "Do not touch" list and its non-goals, and names the config key `roadmap_dir` and the stage `/update-roadmap` — never a product path literal. Second, this repo's own `aidw/conventions.md` declares the artefact list and the ownership section. A conventions-only fix could not work on its own, because the repo conventions channel reached only the four EXTRACTION.md §3.8 prompts (`aidw/prompts.py:CONVENTIONS_PROMPTS` = `task-prompt.md`, `impliment-task.md`, `test.md`, `record-implementation-results.md`) and did **not** include `update-traceability.md`; W1.1 therefore extends that set to **five**, adding `update-traceability.md` and keeping the resolved-basename keying (a repo-shadowed `aidw/prompts/update-traceability.md` is injected by its basename too), so a repo's declaration now reaches `I3` (§18, resolved). The extension is prompt text plus the channel, not a mechanical postcondition: whether Python should verify `paths.roadmap_dir`'s bytes after `I3` is the stronger alternative Z13 leaves out of scope. Re-baselined checkers: `tests/test_conventions_injection.py` (the exact five-prompt set, basename keying, the property sweep), `tests/test_prompt_neutrality.py` (`RETAINED_KEYS` names `roadmap_dir` again) and a new `tests/test_implement_workflow.py` case proving an implement run renders the repo's declaration into the `I3` prompt. The live contract doc's own conventions bullet (`docs/target-repo-config.md`) names `update-traceability` among the injected prompts, so no current document still states the four-prompt list (the historical EXTRACTION.md §3.8 text is deliberately left as the plan of record). `update-traceability.md` stays an existing `REQUIRED_PROMPTS` entry (`aidw/inventory.py` unchanged), and no new checker, status vocabulary or CI gate was added. Nothing else moves: `tick_before`'s capture point, the byte-exact postcondition, `verify_checkbox_flip`, and `I7`'s still-`skipped`-never-`failed` behaviour on a red gate (`WHEN_EVIDENCE_GREEN`, H3.2) are all unchanged. Weakening the postcondition — capturing `tick_before` immediately before `I7`, or attributing allow-listed sub-lines — was rejected: each re-opens the PR #282 hole the exact-match rule exists to close. |
| Z14 | **A `--dry-run` creates no run state, in every workflow and in `aidw exec`** (05-W1.2; design §§8.2, 9.1, 9.4, 19; `aidw/runner.py`, `aidw/workflows/implement.py`, `aidw/workflows/prompt.py`, `aidw/workflows/approve.py`, `aidw/workflows/review.py`, `aidw/workflows/fix.py`, `aidw/cli.py`, `aidw/state.py`, `aidw/log.py`; `tests/test_runner.py`, `tests/test_cli.py`, `tests/test_implement_workflow.py`, `tests/test_prompt_workflow.py`, `tests/test_approve_workflow.py`, `tests/test_review_workflow.py`, `tests/test_fix_workflow.py`, `tests/test_design_doc.py`, `tests/test_conventions_injection.py`, `tests/test_prompt_resolution.py`, `tests/test_override_integration.py`, `tests/test_plan_stages.py`, `tests/test_state.py`). The roadmap offered two rules — a dry run creates no run at all, or one a `--resume` refuses — and 05-S1.2's live observation chose the first: `--dry-run --resume` minted `20261119T233947Z-05-S1.2-implement` recording all nine stages `succeeded` without invoking Pi, and because `_latest_implement_run` returns the newest run for the branch, the next genuine `--resume` would have attached to that phantom, skipped every stage as already-succeeded and opened no PR while the real failed run sat untouched — a silent no-op whose only symptom is a missing PR. **The rule, decided once and applied uniformly** (never resume-pairing-only) to all five workflows `implement`/`prompt`/`approve`/`review`/`fix` and to `aidw exec`: a dry run creates **no run** — no run directory, no `state.json`, no `run.log`, no `prompts/<stage>.rendered.md`, no stage record — so the runs tree is byte-identical before and after and no later `--resume` can attach to a run that invoked no Pi. A never-invoked-Pi run is therefore **not resumable**, and that is enforced structurally rather than detected: `_latest_implement_run`/`_latest_prompt_run`'s newest-run selection, the still-running guard and `I7`'s byte-exact tick postcondition (Z13) are untouched because no such run can exist; no legacy-phantom detector and no `state.json` marker are added, since `runs/` is machine-local state the operator owns (AGENTS.md) and a pre-existing phantom is never deleted, migrated or marked. **Prompt-fixed decisions**, recorded here because the spec fixed only the shape: (a) the one-run-per-worktree lock (§9.1) is still **acquired** in a dry run, and a peer still refuses exit 4 naming the lock (§19 item 8) — the lock is kept for that refusal, not because a run record is created — and every workflow's stale "a dry run reaches `create_run` too" comment was rewritten accordingly; (b) `runner.run_stage(dry_run=True)` performs no filesystem write at all: the `prompts/<stage>.rendered.md` write and the PLANNED record's `_STATE_LOCK`+`save` moved behind a `not dry_run` guard, and the dry-run branch's own `state.status = SUCCEEDED` + `save` was removed outright (`state.record_stage` stays where it is — it is in-memory, so the planned record is readable by the caller and never published), while the returned `StageRecord` keeps its shape — `name`, `status=SUCCEEDED`, `agent`, the resolved `model`, `session_id`, `ended_at` — so the workflows' plan lines are unchanged; variable rendering and per-stage model resolution stay covered through the pure render function and the returned record, not through a written file; (c) the write-free planning substitute — the prompt's one genuinely open mechanism choice, **decided by the task owner on 2026-11-20** — is a **null logger plus a never-saved `RunState`, with `run_stage`'s signature unchanged**; a `None`-tolerant `run_stage` is rejected because it pushes `is not None` branches into the shared seam and every call site to avoid a state `planned_run` already produces for free. Two additive helpers carry it: `aidw/log.py:NullLogger(stream=...)` exposes the same `info`/`warn`/`error`/`section` methods and the same `<ts> [LEVEL] <msg>` line format as `RunLogger`, echoes to stderr exactly when `RunLogger(stream=True)` would, and performs no `mkdir` and no file write — so `RunLogger`'s construction-time `mkdir` is unreachable on a dry-run path because `RunLogger` is never constructed there; and `aidw/state.py:planned_run(...)` takes `create_run`'s **exact** keyword arguments and returns the same `RunState` under the literal `state.PLANNED_RUN_ID` with no `save()`, with the shared construction factored into one private `_new_run_state` builder so the two cannot drift and `create_run`'s signature and `save` stay unchanged. `run_stage(dry_run=True)` keeps its signature and moves the `prompts/<stage>.rendered.md` write and the PLANNED record's `save()` behind `not dry_run`, while the dry-run tail's `state.status` stamp and `save()` are deleted rather than gated; `record.rendered_prompt` keeps its existing relative string (which fabricates no run id), `rendered_chars` stays `None`, and `state.record_stage` stays because it is in-memory. `runner.record_skipped` gains the additive `dry_run: bool = False` and skips its own `save` when set, because `fix`'s `withhold_tick` reaches it on a dry-run path — a write the requirement list did not enumerate — and each workflow's dry-run tail drops its own `save(directory, state)` — the call that stood immediately before that workflow's `dry-run complete` line, in `approve`, `fix`, `implement`, `prompt` and `review` — while `fix`'s `(directory / "artifacts").mkdir` (the one write outside `run_stage` that ran before the dry-run split) is guarded, so a dry run's filesystem effect is exactly zero plus the §19 item 8 lock. (d) **no run id at plan time, so no `run:` line**: all five workflows and `aidw exec` drop the echo they printed today. With no run created the printed id identifies nothing — the same fabricated-identity argument req 6 uses to drop `exec`'s `rendered:` echo — and req 2's must-keep list names the stage plan, the resolved agents and models, the planned gate and (implement/prompt) the planned worktree and branch-setup command, never the run id. The in-memory record's id is the literal `state.PLANNED_RUN_ID = "<planned>"`, not a minted timestamp: the planned `StageRecord.session_id` is therefore deterministic (`aidw-<planned>-<agent>-<stage>`), two dry runs print byte-identical output, and a test pins it without stubbing the clock; nothing persists under it, so `run_dir(runs_root, PLANNED_RUN_ID)` is a path no code creates. A `run:    (planned; --dry-run creates no run)` replacement was rejected: it is a new line every dry-run test must pin and one an operator can copy. (e) **planned paths are named, never fabricated**: dry-run paths share one literal root, `state.PLANNED_RUN_DIR_TEXT = "<run dir>"`, and the three expansion fields keep their names, shapes and rendering sites — the dry-run branch passes `directory=Path(PLANNED_RUN_DIR_TEXT)` exactly where a real run passes `run_dir(runs_root, state.run_id)`. So `review`'s `manifest:` line (label unchanged), its `publisher argv:` and R2's rendered extra all read `<run dir>/artifacts/review-manifest.json`, and `fix`'s F4 manifest pointer and F1's `{closing_body}` read `<run dir>/artifacts/iter{N}-review-manifest.json` and `<run dir>/artifacts/iter{N}-closing-body.md`; real runs are untouched, `run_dir(...)` still supplying the **absolute** path E7.3's PR 110 requires. Because `Path("<run dir>")` is relative, a stray write would land in the working tree rather than under `runs/`, so the tests assert no `<run dir>` directory appeared there as well as an unchanged runs tree. (f) `aidw exec --dry-run` follows the same rule end to end — it skips `create_run`, constructs `NullLogger` instead of `RunLogger`, drops the `rendered:` echo outright and skips the post-stage conditional `save` — and its `--dry-run` help now reads "Plan only; no writes." instead of "Plan only; do not invoke Pi.", advertising the contract this decision keeps (no test or §14 line pinned the old string). Gate impact: no checker, status vocabulary, `when=` token, config key, `REQUIRED_PROMPTS`/`REQUIRED_SCRIPTS` entry or CI gate changes; the re-baselined tests are the modules listed above — the task prompt's eight plus the five it did not list: four that read a dry run's rendered prompt file (`test_conventions_injection`, `test_prompt_resolution`, `test_override_integration`, `test_plan_stages`), which now assert the plan's text through the same pure render the runner applies and that no file exists, and `test_state`, which pins `planned_run`'s literal id, its zero writes and the deterministic planned session id, and §19 items 8–10 are reworded to "creates no run state" (item 10 covering `review`/`fix`/`approve`), with §8.2 and §9.1/§9.4 stating the rule. |
| Z15 | **The renderer appends only `aidw/conventions.md`; a frontmatter marker restores the `AGENTS.md` append** (C1.1; design §§7.3, 5.5; `aidw/prompts.py`, `aidw/runner.py`, `design.md`, `docs/target-repo-config.md`; `tests/test_conventions_injection.py`, `tests/test_design_doc.py`). Pi already loads the target repo's `AGENTS.md` as project context at `cwd` = target root (§5.5), so `inject_repo_conventions`'s copy was the same file twice in every §3.8 stage (observed: 16.9KB of a 28.5KB rendered `impliment-task` prompt). The injection now appends **only** `<target>/aidw/conventions.md`, which Pi does not provide. **Prompt-fixed decisions**, recorded here because the spec fixed only the shape: (a) the lever is a frontmatter marker `append_agents_md: true` on the **resolved** prompt file (`spec.prompt`, so a repo shadow or an explicitly declared prompt is read and marked by its own file, never the toolkit default a stage id would name), read by the new pure peek `aidw.prompts.appends_target_agents_md`; only a value `yaml.safe_load` parses as the boolean `True` restores the append — absent, `false`, a quoted `"true"` string, a non-boolean scalar, a nested key, malformed YAML, a frontmatter-less prompt and a missing/unreadable/non-UTF-8 file all mean dropped, with no raise — because the repo that needs the old append is one whose agents set `no_context_files: true` (§5.5) and would otherwise lose `AGENTS.md` entirely, and a marker typo must not fail a stage; (b) no target-repo config key, `docs/schema/` node or `docs/target-repo-config.md` field is added (a config key was the alternative and is explicitly out of scope), so no config drift check moves — only the document's related-documents bullet is corrected to say that `AGENTS.md` is Pi's project context and the gate-block read source, not an appended block; (c) the **read** channel is untouched — `read_conventions_sources`/`CONVENTIONS_SOURCES` still return both sources in D16 order — because `aidw/workflows/prompt.py:_gate_block` takes the gate commands from the root `AGENTS.md`'s `## Gates` section and C1.2/C1.3 build on it; the split is injection-only, so the evidence bundle's gate list cannot silently lose that source; (d) E7.3's byte-identity and degrade-to-none guarantees survive: a prompt outside `CONVENTIONS_PROMPTS`, a repo with no sources, an opted-in prompt whose repo has no `AGENTS.md`, an empty source and a missing/unreadable/non-UTF-8 source all leave `prompt_text` byte-identically unchanged (the existing `(OSError, UnicodeDecodeError)` handling in `read_conventions_sources` stays, and the peek adds the same pair plus `yaml.YAMLError`); (e) `render_repo_conventions` gains the additive keyword `include_agents_md: bool = False`, so the default injectable block is conventions-only and the flag is the single way to restore the pre-C1.1 D16 block, while `inject_repo_conventions`'s three-argument signature is unchanged (five test modules call it inside their `--dry-run` render seams). Gate impact: no new checker, status vocabulary, `REQUIRED_PROMPTS` entry, `when=` token or CI gate; `tests/test_conventions_injection.py` was re-baselined from "AGENTS.md is injected" to "conventions.md is injected, AGENTS.md is absent by default", gained the marker cases (restore/absent/false/quoted/nested/malformed/frontmatter-less/missing/non-UTF-8) and a third property sweep over the five basenames × the marker variants, and `tests/test_design_doc.py` pins the row by task id + wording, never by `Z` number, plus the updated §7.3 step 4. Nothing else moves: `I7`'s tick, `_gate_block`, the stage registry, agent configs and the prompts themselves are untouched. |
| Z16 | **Gate commands are resolved from two recognised headings, a declared one, and a miss is diagnosed** (C1.2; design §§7.3, §8.1; `aidw/prompts.py`, `aidw/workflows/prompt.py`, `aidw/doctor.py`, `aidw/target_config.py`, `docs/target-repo-config.md`, `docs/schema/aidw-config.schema.json`, `design.md`; `tests/test_prompt_workflow.py`, `tests/test_doctor.py`, `tests/test_target_config.py`, `tests/test_target_repo_config_doc.py`, `tests/test_design_doc.py`). The evidence bundle's gate-commands element recognised exactly one literal heading, `## Gates`, so a repo that publishes its gates under `## Gate commands` — the shape a natural reader writes — contributed nothing and the bundle silently degraded to `unavailable — could not be read`. Both readers now share one recognised set: `aidw.prompts.GATES_HEADINGS = ("## Gates", "## Gate commands")`, with the pure `is_gates_like_heading` heuristic and the pure `is_recognised_gates_heading` predicate defined once there. `aidw.workflows.prompt._gates_section` recognises either heading plus a target-declared one, still ending the section at the next `## ` heading, and `_gate_block` passes each D16 source through it unchanged (same order), so a `## Gate commands` repo now contributes its commands. Both readers match with **`startswith`, never `==`**, so a suffixed canonical heading — the toolkit's own `## Gates — run exactly these, and only these` — keeps matching. `aidw doctor` gains `_check_gates_heading` (the advisory `gates heading` check, WARN, never FAIL, never an exit-code decision) wired into `collect_checks`: for each `## ` gates-like heading that is not recognised it names the source file and the heading and offers both fixes (rename to `## Gates`/`## Gate commands`, or declare `gates_heading`), so a miss is diagnosed instead of only degrading. **Prompt-fixed decisions**, recorded here because the spec fixed only the shape: (a) the config lever is a new optional **top-level** `gates_heading` (string, unset by default) and its value is the **full heading line including its `## ` prefix** (`gates_heading: "## Verification gates"`), matched verbatim by the same prefix rule — never a bare title the code prefixes; an empty value is one loader ERROR naming `gates_heading` with the value dropped (`_read_str` passes `""` through for optional keys, and `line.startswith("")` would match every line), while `TOP_LEVEL_KEYS`, `TargetConfig`, `to_dict`, `docs/schema/aidw-config.schema.json` and the `docs/target-repo-config.md` field table carry it; (b) the "gates-like heading" heuristic the doctor diagnoses with is a `## `-level heading containing "gate", case-insensitive — deliberately broader than the recognised set, because its job is to catch what is not recognised, and case is significant (`## Gate Commands` is not `## Gate commands` and must both degrade the bundle and WARN); (c) recognition is **prefix** (`startswith`), not exact, in the bundle reader **and** the doctor's recognised test, preserving the existing suffixed fixture and keeping the toolkit's own `## Gates — run exactly these` silent — `==` in the doctor would warn on the toolkit's own `AGENTS.md` while every bare-heading test stayed green. Two roots: `_gate_block` loads the config from `repo.root / "aidw" / "config.yaml"` (the target, never the toolkit root), and the doctor loads the same target-relative path before deciding a heading is unrecognised, so a repo that declares its heading is not warned. The degrade contract is unchanged (L2.4 requirement 4): no source, no recognised heading, an unrecognised gates-like heading, and non-UTF-8/unreadable sources all still yield `_EVIDENCE_UNAVAILABLE`; the doctor WARN is the diagnostic and the bundle never fails the run. Gate impact: `docs/target-repo-config.md`'s field inventory gains `gates_heading: unset` (re-baselined `tests/test_target_repo_config_doc.py`), the JSON schema gains the property (its top-level `properties` equals the dataclass fields, re-baselined in `tests/test_target_config.py`), and `tests/test_doctor.py` pins WARN/silent/degrades without changing any FAIL. C1.1's injection split (`render_repo_conventions`/`appends_target_agents_md`) and C1.3's prompt inlining are untouched. |

| Z17 | **The resolved gate commands are inlined into the five gate-recording prompts, from one shared resolution** (C1.3; design §§7.3, 8.2; `aidw/prompts.py`, `aidw/workflows/prompt.py`, `aidw/runner.py`, `prompts/impliment-task.md`, `prompts/test.md`, `prompts/fix-next-review-followup.md`, `prompts/record-implementation-results.md`, `prompts/code-review.md`, `docs/migration/prompt-classification.md`, `docs/target-repo-config.md`, `design.md`; `tests/test_conventions_injection.py`, `tests/test_prompt_classification.py`, `tests/test_prompt_neutrality.py`, `tests/test_design_doc.py`, `tests/test_prompt_workflow.py`). The prompts that tell an agent to run the repo's gates named the commands only as "the repo's own, taken by name from its `aidw/conventions.md`/root `AGENTS.md`", so the list the evidence bundle already resolves never reached the prompt that has to act on it and every stage re-derived it (or guessed the wrapper's placeholder). C1.3 injects that list as text. **Prompt-fixed decisions**, recorded here because the spec fixed only the shape: (a) there is exactly **one** resolution path — `aidw/prompts.py:resolved_gate_block(repo_root) -> str | None`, with `gates_section` moved there too (the workflow module re-exports it as `_gates_section`, so existing callers and tests keep working) — and `aidw/workflows/prompt.py:_gate_block` becomes a wrapper mapping `None` to `_EVIDENCE_UNAVAILABLE`; the resolver returns `None`, **never** a sentinel string, because the two consumers take different no-resolution contracts; (b) the prompt set is `GATE_PROMPTS`, a frozenset of the five **resolved** basenames (`impliment-task.md`, `test.md`, `fix-next-review-followup.md`, `record-implementation-results.md`, `code-review.md`), keyed exactly like `CONVENTIONS_PROMPTS` so a repo shadow keeps working; it is deliberately not the same set, since the fix and code-review prompts record their own gate outcomes while `task-prompt.md` and `update-traceability.md` do not; (c) `inject_gate_block(prompt_text, prompt, repo_root)` appends the block **verbatim** under `GATE_BLOCK_HEADER = "## Resolved gate commands ({sources})"` (the D16 channel joined as `AGENTS.md + aidw/conventions.md`), mirroring `CONVENTIONS_HEADER`'s source-labelled shape, and is called from `aidw.runner.run_stage` **after** `inject_repo_conventions` so the written `.rendered.md` and the stdin payload carry the same text; a prompt outside the five, and a repo whose resolution is `None`, return `prompt_text` byte-identically — an `unavailable` note is never injected, because that degrade belongs to the evidence bundle; (d) each edited prompt keeps every `aidw gate run <key> $SCOPE -- <command>` wrapper and its key/scope guidance (the repo's gate section is bare commands), replacing only its "the commands are never written down here" clause with a pointer that names the injected block as authoritative when present and keeps the `aidw/conventions.md`/root `AGENTS.md` fallback otherwise; `code-review.md` had no such pointer and gains gate-command guidance in its review-order step 6, naming `aidw gate run` and both sources; (e) the duplication corner is resolved explicitly rather than silently: three of the five are also in `CONVENTIONS_PROMPTS`, so a repo declaring its gates in `aidw/conventions.md` can see that section twice (whole-file conventions append + focused block). The focused block is the authoritative "resolved gate commands" presentation, its header appears exactly once, and the conventions append is **not** de-duplicated — C1.1's contract is a verbatim whole-file append, and trimming it would make the injected conventions depend on a second reader; (f) `code-review.md` is re-classified **out of byte-frozen bucket (i)** into a new post-cutover class (v) in `docs/migration/prompt-classification.md` and out of `BYTE_FROZEN`, because a file whose bytes changed cannot honestly be called "ship as-is"; §4.2's own (i) list is still asserted verbatim (the spec is a historical authoring claim), every other bucket-(i) prompt stays byte-frozen, and class (v) records why the file is neither bucket (ii) nor bucket (iv). Gate impact: no stage id, `when=` token, config key, JSON-schema node, `REQUIRED_PROMPTS` entry or new gate; `tests/test_prompt_neutrality.py`'s four (ii) `VARIABLES` prompts keep `aidw gate run` and both conventions sources, `tests/test_prompt_classification.py` re-baselines `BYTE_FROZEN` and pins the exception two-sidedly, and `tests/test_prompt_workflow.py`'s existing `_gate_block`/`_gates_section` cases keep passing through the re-export and wrapper. |

---

## 18. Risks and open items

| Risk / open item | Status | Notes |
|---|---|---|
| Pi's `--append-system-prompt` may accept literal text rather than a file path | **Resolved (Phase 1)** | Verified: accepts both literal multi-line text and paths. AIDW passes file contents. |
| `--tools` allowlist interaction with MCP/extension tools | **Resolved (Phase 1)** | `--tools` is a strict allowlist over all tools; `mcp_config` alone exposes nothing, so MCP tool names must be listed. No baseline agent enables MCP. |
| `pi -p` with a piped stdin prompt | **Resolved (Phase 1)** | Verified: `pi -p` uses piped stdin as the prompt; AIDW pipes the rendered prompt. |
| Review verdict parsing depends on the model following the `Approve`/`Request changes`/`Blocked` format | **Resolved (Phase 3 live validation)** | Layered parser: an explicit `Verdict: <token>` line, then a line beginning with a token, then the last bare mention; `None` fails closed. Naive last-mention-wins was wrong (`Request changes ... so `Blocked` is not warranted`). **Reopened and re-resolved as M1 (2026-11-04):** every pass now reads prose only (fenced blocks blanked, path/module segments and inline code spans rejected), because the bare-mention fallback read `approve` out of `implement/review/approve/fix/prompt` and returned `Approve` for a review that never emitted a verdict. An `Approve` that contradicts its own blocking findings is refused too (M2). **Narrowed by M3 (2026-11-04):** a capitalised, self-closing code span followed by a separator is a conclusion (`` `Approve` — nothing material remains ``), because M1 read the PR #91 approval as no verdict at all; both reviewer prompts now also require a bare `Verdict: <token>` line, which pass 1 reads. |
| Provider error reported with exit code 0 | **Resolved (Phase 3 live validation)** | `PiResult.provider_error` (from `stopReason`/`errorMessage`) marks the stage failed. |
| Review-fix loop leaves the prompt uncommitted | **Resolved (Phase 3 live validation)** | The workflow commits the owned prompt path after the gate if the rework changed it (`git.py:commit_paths`). |
| The author may name the task-prompt file differently than the assumed convention | **Resolved (Phase 3 live validation)** | The reviewer is pointed at the path the author actually reported, not a hard-coded filename. |
| Findings extraction into `findings.json` depends on the code-review output format | **Resolved (Phase 5)** | Strict labelled-block parser (`findings.py`): unknown priority, out-of-range confidence, or an empty required field records a problem and the workflow fails closed without publishing. `title` is derived from the finding body (the review format has no title). |
| Two reviewer models may not be available in the configured provider set | `--strict` independence checks would always fail | Ship placeholder configs with distinct models; document the minimum viable rule (`/code-review` ≠ `/impliment-task`) and allow `--strict` to be omitted. `aidw fix` additionally warns (strict: fails) when no reviewer model differs from the fixer model. |
| The fix-loop prompts leave their changes uncommitted | **Resolved (05-P1.1, Z9)** | The boundary was wrong where it mattered: `F1` closed each issue as `Status: fixed` while the fix (and the `I7` tick) never left the PR-head worktree. `F5 commit-and-push` (§8.4) now publishes a converged run's change set — but only what the run owns: a dirty tree with nothing closed is a recorded *skip*, and Python never commits or pushes (the `pr-publisher` agent does). A stage that cannot commit or push, a stage that discards the change set instead of committing it (proved by requiring `HEAD` to have moved), a push that did not land and a clean tree with closed issues all fail the run naming the PR and branch, so "issue closed" is never ahead of "fix pushed". 05-P1.2 moved the close behind that push: `F1` no longer posts `Status: fixed` or closes in-stage, and the workflow runs `review_followup.py close` only after `F5`'s push is verified (§8.4). |
| Prompts and helper scripts evolve, but their contract is strings the scripts compare | Prompt/script contract drift (labels, exact comments, markers) | Expected and intentional: the prompts and `constants.py` are edited together, and `aidw prompts check` verifies presence, provenance and self-containment, not semantic agreement. The D5 freeze (§7.2) is the part that must not drift, and it has its own golden test. |
| A target repo's `aidw/prompts/` override can reintroduce environment assumptions | A repo override drifts from the toolkit's neutral default | `aidw prompts check` sweeps the target's own overrides with the same sentinels (§12.3), so a shadowed prompt is checked as strictly as a default. |
| The state root can land inside a working tree in a single-checkout repo | `git worktree remove`/a clean could discard run state | `aidw doctor` and `aidw/layout.py` warn on that layout and refuse the clone-of-a-worktree layout outright (§9.1). |
| A repo with no `.aidw/` in its `.gitignore` can accidentally commit run state in the single-checkout case | Machine-local state leaks into history | Documented requirement: any repo resolving its state root inside its own tree must ignore `.aidw/`. The toolkit warns about the layout but cannot edit a target's `.gitignore`. |
| Pi session storage accumulates under `~/.pi` | Disk growth | Out of scope; note in the README. |
| A repo's repo conventions cannot reach `I3`, so a roadmap-ownership rule cannot be declared by the repo | **Resolved (W1.1)** | The target-repo conventions channel is `AGENTS.md` + `aidw/conventions.md` (`aidw/prompts.py:CONVENTIONS_SOURCES`), injected into every prompt in `CONVENTIONS_PROMPTS` — **five** since W1.1, which added `update-traceability.md` and kept the resolved-basename keying (§17 Z13). A repo's `aidw/conventions.md` can therefore declare its traceability artefacts, including "none", to `I3`. The "never edit `paths.roadmap_dir`" rule still lives in the toolkit prompt, because it is a safety rule of the `I7` postcondition that no repo may switch off; the channel carries the repo's *artefact list*, not permission to re-own the roadmap. Proven by `tests/test_conventions_injection.py` (exact five-prompt set, basename keying, property sweep), `tests/test_prompt_neutrality.py` and `tests/test_implement_workflow.py`'s implement-render case. |
| The toolkit's own suite can rot if CI is weakened | Toolkit regressions | CI has run pytest + doctor since extraction (D21); `.github/workflows/ci.yml` is the guard, and `uv sync --frozen` keeps the lock honest. |

---

## 19. Acceptance criteria

AIDT's v1 is complete, and stays complete, when the following hold **from a checkout of this
repository** (the toolkit dogfooding its own SDLC, D21):

1. `uv sync --frozen` succeeds — a stale `uv.lock` is a failure, not an update.
2. `uv run --frozen pytest` is green. `pyproject.toml`'s `testpaths` covers `tests/` and
   `prompts/scripts/review-followup/tests`, and no test invokes a real Pi model.
3. `uv run aidw doctor` exits 0 with a readable report: python/uv, `pi` (above the enforced
   floor), `gh` (authenticated, sub-issue capable), `git` ≥ 2.31, the toolkit/target/workspace/
   state roots, the layout guard, the target config and compatibility, the prompt and
   agent-config inventories, and the toolkit version.
4. `uv run aidw agents validate --strict` and `uv run aidw prompts check` exit 0.
5. `uv run aidw tasks --todo --phase 00` lists this repo's own unchecked extraction tasks, parsed
   from the configured roadmap with the default directory and glob.
6. `uv run aidw config show` prints every resolved value with its provenance and the four roots,
   and `--json` prints the object `config_hash` is computed over.
7. `uv run aidw worktree list` reports the branch ↔ worktree mapping of this workspace, and
   `uv run aidw --version` prints `aidt <version>` from outside any repository.
8. With no other run active in the worktree, `uv run aidw prompt 00 E9 E9.2 --dry-run` prints the
   planned `worktree add` and the stage plan, performs no git or GitHub writes, and creates no
   run state. With a peer run active it refuses (exit 4) naming the lock it could not take
   (§9.1) and creates no run state then either.
9. With no other run active in the task worktree, `uv run aidw implement
   docs/task-prompts/00-E9.1-prompt.md --dry-run` prints stages I1–I9 with agents, prompts and
   models, performs no git or GitHub writes, and creates no run state.
10. `uv run aidw review --pr <n> --dry-run` prints the findings manifest and creates no GitHub
    state; `uv run aidw fix --pr <n> --dry-run` lists available approved children via the bundled
    `review_followup.py select`; `uv run aidw approve-followups --pr <n> --dry-run` prints its
    plan; each of the five workflows and `uv run aidw exec --dry-run` creates no run state.
11. Every stage appends a record to `<state root>/<repo-slug>/runs/<run-id>/state.json`; a failed
    stage can be resumed with `--resume`; a repeated verification gate against an unchanged tree
    is cited as `reused:` rather than re-run.
12. Skips and gate decisions are recorded with mechanism and timestamp, and no stage or gate is
    silently bypassed (§1.2).
