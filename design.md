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
| Implementation + PR | `aidw implement` | I1–I6: implement, test, traceability (repo-optional), architecture (repo-optional), record, publish |
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
  stub exists in the state model, but no workflow invokes it; the bundled prompt is not wired
  in. A target repo may add such a stage (§12.2).
- **Optional summary prompts.** The bundled leftovers are available as ordinary prompts, not
  as a workflow stage.
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
| **Stage** | One Pi invocation with one prompt and one agent. The atomic unit of work, identified by a stable id (`I1`…`I6`, `P1`, `R1`, `R2`, `A1`, loop ids) so existing run artifacts stay readable. |
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
4. Appends the target repo's conventions where the prompt is one that takes them (D16: the root
   `AGENTS.md` plus optional `<target>/aidw/conventions.md`, each labelled with its source).
5. Returns the rendered text, which `pi.py` passes as the final message on stdin to `pi -p`.

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
  name come from `repo.branch_pattern`, the worktree is created at the workspace root, and every
  later stage of the run is re-resolved into it (EXTRACTION.md §§3.2, 3.4). A malformed pattern
  is a usage error (exit 2); a git refusal is a preflight refusal (exit 4); both happen before
  any stage or run state.
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
  earlier behaviour, never an error (H3). Rounds after the first also receive a delta brief —
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
  printed for a human to settle, and no gate is recorded (the old `assumed_ok` / `no further
  review — accepted` acceptance path is gone). A `Blocked` verdict short-circuits earlier with
  the same exit-3 outcome and its own "a human must settle it" message.
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
- `I2` and `I4` touch disjoint file sets (package tests vs the architecture directory). With
  `--parallel`, AIDW runs the target config's `parallel_groups` concurrently in the same working
  tree; run-state writes are serialized by a lock. Without `--parallel` every stage runs
  serially. A group whose members are ordered against each other is a config error.
- `I5` is the mandatory sync point over the fully merged tree; `I6` must see the same tree, so
  the repo's verification gates are run once per tree and cited thereafter (§9.2).
- `I6` commits the accumulated uncommitted change set, pushes, and opens the PR. AIDT does not
  commit before this stage.
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
```

- Entry gate: the human has already reviewed the published issues **on GitHub**. The approval
  stage is the only place AIDT writes `approve-fix`/removes `decision-pending`.
- One fix per iteration; `F1` processes exactly one issue and the loop re-derives "available"
  via `review_followup.py select`, never by counting.
- Re-review uses the **fresh reviewer model** rule; if only one reviewer model is configured,
  AIDT warns and (under `--strict`) refuses.
- Bounded: `--max-iterations` (default 10) prevents an unbounded review→fix→review loop. The
  bundled script's exit 3 (no available child) ends the loop successfully.
- Output artifacts: `closed_issues`, `latest_verdict`, `iterations`.

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
    └── locks/<branch>.lock               # one run per branch/worktree
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
- Two different serializations exist and must not be conflated: this lock is **one run per
  worktree**, held for the whole workflow and cross-process, while `runner._STATE_LOCK`
  serializes `state.json` writes between concurrent *stages inside one run* (`--parallel`).

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

`gate_outcomes` records every `aidw gate run <key> -- <command>` verification result with the
**content-tree identity** it ran against, its origin (`stage`, `at`, `command`), its status,
exit code, duration, a one-line summary and the repo-relative prefixes it declared it cannot
read. A later stage asking for the same key against identical content is handed
`reused: gate 'suite' passed for tree <id> at <time> by stage '<stage>' (<summary>)` instead of
re-running it. The identity deliberately excludes `HEAD` (the PR stage commits the very tree it
gated); anything unprovable — no resolvable base, no run to cite, a different command under the
same key, a differently declared scope, a previous failure — means the gate executes. Human gate
decisions live in `gates`; the two lists are different questions and are never merged.

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

`status` ∈ `running | succeeded | failed | blocked | aborted`. `resume.next_stage` is set when a
stage fails, so `--resume` continues from that stage.

### 9.4 Resumability

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
| Pi exits 0 but reports an in-stream provider error (`stopReason: "error"` or `errorMessage`, e.g. an OpenRouter 402) | Stage `failed` with the provider message; workflow stops. Credit/auth errors are not transient and are not retried. |
| Pi exits 0 but the stage's declared postcondition does not hold (the agent stopped and reported a problem in its final message instead of doing the work) | Stage `failed` with `postcondition not met: …`; the workflow stops. A zero exit only means the agent finished, so a stage whose job is an external change re-reads that state (`StageSpec.verify`, e.g. `github.verify_approvals`, `github.verify_published`) before it can succeed. |
| A review stage returns no final message | Stage `failed`; the workflow stops rather than treating it as "ambiguous" and running rework on empty findings. |
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
defaults preserved exactly (stage ids `P1`, `P2`, `I1`–`I6`, `R1`, `R2`, `F1`–`F4`, `A1`) so
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
  the PR stage's documented `git add -A` is executed by the `pr-publisher` agent, not by Python.

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
aidw prompt    <phase> <epic> <task> [--require-approval] [--yes] [--no-fetch]
              [--allow-incomplete-prereqs] [--max-revisions <n>] [--skip-gates ...]
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

# global
--repo <path>   select the TARGET repo (never the toolkit); default cwd, then $AIDW_REPO
--verbose       stream the Pi transcript to the TTY
--retry-transient / --no-retry-transient   retry once on a transient Pi invocation error (default on)
--progress / --no-progress                 show '.' progress while Pi works
                                           (default: on when stderr is an interactive terminal)
```

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
| G2 | The `aidw prompt` revision budget spends its last slot on a review, not a fix. At `MAX_REVISIONS=3` the loop runs two fix batches plus three reviews, the third review review-only, so a review is always the last stage for a non-approving prompt. A residual `Request changes` after that terminal review fails closed (`BLOCKED`, exit 3) with the last review's findings on stderr and **no** `approve-task-prompt` gate recorded; the old `assumed_ok` / `no further review — accepted` unreviewed-acceptance path is removed. `revisions` in a recorded gate detail counts fix batches (2 on a three-review success), not review rounds. (L4.1, design §8.1 — verified; this row is the phase-02 terminal-review/budget record, not duplicated.) |
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
| Q1 | `aidw --version` is an eager top-level flag that prints exactly what the `version` subcommand prints — `aidt {aidw.__version__}` — and exits 0 **before any target resolution**, so it works outside a repository (E8.3, the roadmap's "without a target repo"). Neither click's default `<prog>, version <v>` rendering nor a `git`/`uv`/`pyproject.toml` lookup is used: both would disagree with the one version source E1.6/P1 already chose. `aidw doctor` next reports `toolkit version` (`aidw.__version__`, informational and always OK) as an environment check beside `git version`, so it survives the target early return, and a distinct `compat status` check carries the D10 verdict. That verdict **moves out of** `target config` (E3.5) rather than being copied: `check_compatibility` is evaluated once, an incompatible `schema_version`/`requires_toolkit` is one FAIL on one named line, and `target config` keeps the loader's ERROR issues, `validate_paths` and the resolved schema-version line. (EXTRACTION.md §3.11 D10; `aidw/cli.py`, `aidw/doctor.py`) |

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
| The fix-loop prompts leave their changes uncommitted | Not AIDT's to fix | The canonical fix prompt (like the implement stages) never commits; AIDT never commits or force-pushes (design §13). The operator or CI commits/pushes the fix branch. Documented as a deliberate boundary. |
| Prompts and helper scripts evolve, but their contract is strings the scripts compare | Prompt/script contract drift (labels, exact comments, markers) | Expected and intentional: the prompts and `constants.py` are edited together, and `aidw prompts check` verifies presence, provenance and self-containment, not semantic agreement. The D5 freeze (§7.2) is the part that must not drift, and it has its own golden test. |
| A target repo's `aidw/prompts/` override can reintroduce environment assumptions | A repo override drifts from the toolkit's neutral default | `aidw prompts check` sweeps the target's own overrides with the same sentinels (§12.3), so a shadowed prompt is checked as strictly as a default. |
| The state root can land inside a working tree in a single-checkout repo | `git worktree remove`/a clean could discard run state | `aidw doctor` and `aidw/layout.py` warn on that layout and refuse the clone-of-a-worktree layout outright (§9.1). |
| A repo with no `.aidw/` in its `.gitignore` can accidentally commit run state in the single-checkout case | Machine-local state leaks into history | Documented requirement: any repo resolving its state root inside its own tree must ignore `.aidw/`. The toolkit warns about the layout but cannot edit a target's `.gitignore`. |
| Pi session storage accumulates under `~/.pi` | Disk growth | Out of scope; note in the README. |
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
   planned `worktree add` and the stage plan, and performs no git or GitHub writes. With a peer
   run active it refuses (exit 4) naming the lock it could not take (§9.1).
9. With no other run active in the task worktree, `uv run aidw implement
   docs/task-prompts/00-E9.1-prompt.md --dry-run` prints stages I1–I6 with agents, prompts and
   models, and performs no git or GitHub writes.
10. `uv run aidw review --pr <n> --dry-run` prints the findings manifest and creates no GitHub
    state; `uv run aidw fix --pr <n> --dry-run` lists available approved children via the bundled
    `review_followup.py select`.
11. Every stage appends a record to `<state root>/<repo-slug>/runs/<run-id>/state.json`; a failed
    stage can be resumed with `--resume`; a repeated verification gate against an unchanged tree
    is cited as `reused:` rather than re-run.
12. Skips and gate decisions are recorded with mechanism and timestamp, and no stage or gate is
    silently bypassed (§1.2).
