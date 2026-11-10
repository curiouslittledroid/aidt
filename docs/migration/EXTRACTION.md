# AIDT Extraction Plan

**Status: historical — the extraction is complete.** This document is the plan that produced
this repository, kept at this path as the record of how it was carried out. It is not a live
source of truth and nothing in it should be actioned: every task in §6 (E0–E9) has been
superseded.
**Read instead:** `design.md` — the design of record — and `docs/tasks/00 - Extraction.md` —
this repo's own roadmap, which supersedes §6's task list (E0–E9).
**Audience:** a reader tracing *why* the toolkit is shaped as it is, and the project owner.
**Provenance:** the plan was written against the `aidt/` directory inside the Mythical Forge
repo, and the initial commit of the new repo was a verbatim copy of that directory at a
recorded SHA (§5.2). The Mythical Forge references below are that history, not a claim about
where the toolkit lives today.

---

## 0. How to use this document

1. Read §1–§5 before starting any task. Do not start a task without reading its section.
2. Execute tasks from §6 in order unless a task says it may run in parallel.
3. Each task states a **Deliverable** and a **Done when**. "Done when" is the acceptance check.
4. When a task needs a decision this document does not settle, **stop and ask**. Do not silently
   resolve it — several of these choices are persisted GitHub state or hard to reverse.
5. §10 lists decisions taken *while writing* this document that the owner has not explicitly
   seen. Veto or confirm them before starting E3.
6. §9 lists what is deliberately out of scope. Do not drift into it.

---

## 1. Context and goal

AIDT is a Pi-driven developer-workflow toolkit. It lives at `aidt/` inside the Mythical Forge
product repo, which creates two problems:

1. **Bootstrap** — the toolkit is only obtainable from a checkout, so a bare-repo + worktree
   layout has no way to start.
2. **Coupling** — `paths.aidt_root()` is `repo_root()/aidt`, so whichever branch you are on is
   the version of the toolkit you run. It also means every product branch carries `aidt/` diffs.

**Goal.** Move AIDT into its own repository so that:

- the toolkit is installed once, independently of any checkout, and is no longer
  branch-coupled;
- the toolkit repo owns the SDLC **structure** — workflows, stages, ordering, gates, the
  roadmap concept, and the **default** task prompts;
- a **target repo** supplies only what is specific to it: a small config file and the prompts
  for stages it wants to override, under a tracked `aidw/` folder;
- anything a target repo does not override falls back to the toolkit's default.

What this buys, concretely: worktree-per-branch becomes workable, one toolkit version serves
several repos, and Mythical Forge's own prompts live where they belong (in Mythical Forge).

---

## 2. Locked decisions

Settled by the owner before writing this document. Do not re-litigate them.

| # | Decision |
|---|---|
| D1 | AIDT moves to its own repo. |
| D2 | The **toolkit repo owns** SDLC structure, stages, workflow ordering, the roadmap concept, and the default task prompts. |
| D3 | A **target repo needs a tracked `aidw/` folder** containing config that points at repo-specific prompts. |
| D4 | Missing repo prompt ⇒ the toolkit's **default** is used (per prompt, per stage). |
| D5 | **Marker and label literals are frozen.** No currently-persisted string in GitHub changes (§3.9). |
| D6 | The **roadmap/task concept lives in AIDT**, not in the target repo. |
| D7 | Name: new repo is **`aidt`** ("AI Developer Tools"). The importable package and CLI are **`aidw`** ("AI Developer Workflows"). Future sibling tools get their own packages in the same repo. The target-repo config folder is **`aidw/`**. |
| D8 | Fresh repo with a single "verbatim copy" initial commit; no filtered history. |
| D9 | Distribution: `uv tool install git+…@<tag>` (primary) and `uvx --from … aidw` (secondary); the toolkit version is recorded in every run's `state.json`. |
| D10 | Target config declares `schema_version` and an optional minimum toolkit version; the toolkit refuses to run when it cannot understand the config. |
| D11 | Config format is **YAML**. |
| D12 | Override granularity: a repo may replace a prompt, override stage metadata (agent/model/timeout/thinking), add new stages, and override agent config globally. It may **not** reorder or remove a core stage; a repo-optional stage is disabled with an explicit `enabled: false`. |
| D13 | Core stages = branch setup, implement, test, code-review, record-results, pr-publish. Traceability and architecture are **repo-optional**. |
| D14 | Prompt resolution supports **both** filename shadowing and an explicit per-stage path (explicit wins). |
| D15 | AIDT documents and owns **one** roadmap format; a target repo supplies only the directory and filename pattern. |
| D16 | Repo conventions for the task-prompt format come from the target repo's root `AGENTS.md` plus an optional `<target>/aidw/conventions.md`, injected into the relevant prompts. |
| D17 | Path conventions (task-prompts dir, roadmap dir, implementation-results dir, template, branch pattern, artifacts) are all configurable; AIDT's **defaults are Mythical Forge's current layout**. |
| D18 | Run state lives outside all worktrees: `dirname(<absolute git-common-dir>)/.aidw/state/<repo-slug>/…`, falling back to `~/.aidw/state/<repo-slug>/…`. |
| D19 | Target repo selection: current working directory by default, with `--repo <path>` and `AIDW_REPO` overrides. |
| D20 | **Git worktrees are in scope for this plan**, including AIDT owning worktree creation. |
| D21 | The new repo dogfoods its own SDLC (design + roadmap + task prompts, no numbered spec set) and gets CI from the start. |
| D22 | After cutover, Mythical Forge keeps **nothing** of AIDT — no history copy, no stub. All preservation happens in the new repo. |
| D23 | This document's tasks are numbered `E<n>.<task>` with a concrete "Done when". |
| D24 | Historical design inputs (`aidw-initial-prompt*.md`) travel under `docs/history/`. |

---

## 3. Target architecture

### 3.1 Two roots

This split already exists, unstated, in `aidw/config.py`: some paths resolve against the **aidt
root** (`agents_md`, `system_prompt.file`, `mcp_config`, `skills`, `extensions`,
`prompt_templates` — `config.py:275-309`), and `cwd` resolves against the **repo root**
(`config.py:283`). Extraction makes it explicit and total.

| Concept | Meaning | Resolved from |
|---|---|---|
| **Toolkit root** | Where the installed toolkit's code, default prompts, agent configs and `prompts/scripts/` live. | Installed package location (`importlib.resources` / `Path(__file__)`). |
| **Target repo root** | The working tree the workflow operates on — git operations, generated artifacts, config, repo prompts. | cwd, then `--repo`, then `AIDW_REPO`. |
| **Workspace root** | The folder containing the bare repo and all sibling worktrees. Not itself a git repo. | `dirname(<absolute git-common-dir>)`. |
| **State root** | Per-repo run state, locks, and artifact directories. | `AIDW_STATE_DIR`, else `<workspace root>/.aidw/state`, else `~/.aidw/state`. |

Rules:

- **Nothing generated is ever written into a target repo.** No `runs/`, no locks, no caches.
- Toolkit-relative and target-relative paths must never be interchangeable. Use two distinct
  types (e.g. `ToolkitPaths` and `TargetRepo`) rather than one `root: Path`.

### 3.2 Workspace and worktree model

The supported layout. Every worktree is a **sibling of the bare repo**, and all of them are
linked off the bare repo (not off one another, and `main` must not be a separate clone):

```
~/mythical-forge/
├── bare.git/        # bare clone — the common dir for every worktree
├── main/            # control worktree: base branch permanently checked out
├── 03.1-B2/         # task worktree
└── 04.2-A1/         # task worktree
```

One-time bootstrap:

```bash
git clone --bare <remote> bare.git
git -C bare.git worktree add ../main main
```

Per task, owned by AIDT (never by an agent):

```bash
git -C <workspace-root>/main worktree add -b <branch> <workspace-root>/<branch> <base-branch>
```

Verified git facts this model depends on — the implementation must not assume otherwise:

| Fact | Verified behaviour |
|---|---|
| Repo identity / workspace root | `git rev-parse --path-format=absolute --git-common-dir` returns the **bare repo path** from every worktree; `dirname()` is the workspace root, identically from all worktrees. |
| Target root inside a worktree | `git rev-parse --show-toplevel` returns the **worktree** path. `paths.repo_root()` therefore needs no change. |
| `.git` in a worktree | A **file** pointing into `<bare>/worktrees/<name>`. `(candidate/".git").exists()` in the existing fallback still succeeds. |
| The bare dir as a target | `git rev-parse --show-toplevel` fails ("this operation must be run in a work tree"). AIDT must detect this and refuse with a clear message. |
| One branch, one worktree | Git refuses a second checkout: `fatal: '<branch>' is already checked out at '<path>'`. This is why the branch is born in its own worktree, instead of being created on `main` and moved. |
| Branch ↔ worktree lookup | `git worktree list --porcelain` (blocks of `worktree`, `HEAD`, `branch`; `bare` marks the common dir). |
| Minimum git | `--path-format=absolute` needs **git ≥ 2.31** (local is 2.39.5). Add a doctor check. |

**Rejected layouts, and why** (a fresh session will otherwise reinvent them):

- **`main` as a plain clone**, with worktrees hanging off it. Worktrees then register in
  `main/.git`, so `dirname(common-dir)` becomes the `main` folder and state lands inside a
  prunable worktree. Detect this: **if the resolved workspace root is itself a registered
  worktree of the same repository, fail with an explanation.**
- **Creating the branch on `main` then moving it into a worktree.** Impossible — see the
  one-branch-one-worktree rule above.

**Consequences:**

- AIDT owns branch setup as a **Python stage**, replacing the agent-run `git checkout -b` in
  `prompts/impliment-task.md:40`.
- `aidw prompt` runs in the **control worktree**, creates the task worktree, then runs the
  author/review stages with `cwd` set to the new worktree. That plumbing already exists:
  `runner.py:163` ← `agent.cwd` ← `config.py:283`.
- `aidw implement` / `aidw fix` locate the worktree for the branch they need via
  `git worktree list --porcelain`. When it is absent, print the exact `worktree add` command to
  run. `--repo` overrides the lookup.
- One run per worktree. The lock lives in the state root, keyed by worktree path.
- `--parallel` keeps its current meaning (concurrent *stages* inside one worktree, state writes
  serialised). Cross-*task* parallelism now comes from separate `aidw` invocations in separate
  worktrees. Document this; do not conflate the two.

### 3.3 CLI surface changes

| Command | Change |
|---|---|
| any | The global `--repo <path>` **already exists** (`cli.py:89`) but conflates the two roots — `cli.py:54` does `aidt = repo / "aidt"`. E0.4 re-points it at the target only, and `AIDW_REPO` is added. cwd is the default target. |
| `aidw worktree add <branch> [--base <branch>]` | New. Create the task worktree at the workspace root. |
| `aidw worktree list [--json]` | New. Branch ↔ worktree mapping. |
| `aidw worktree remove <branch>` | New. Refuse when the tree is dirty or the branch is unmerged unless `--force` is explicit. |
| `aidw config show` | New. Print the resolved config merged from defaults + target repo, **with the provenance of each value**. This is the main debugging aid for D4/D14. |
| `aidw doctor` | Extend: toolkit root and version, target repo detection, workspace root, state root, `aidw/config.yaml` validity, git ≥ 2.31, plus the existing gh checks. |

Existing subcommands, exit codes and stdout JSON keys stay stable — the review-followup scripts
are an external contract (§3.9).

### 3.4 Target-repo config

Tracked layout in a target repo:

```
<target>/
├── aidw/
│   ├── config.yaml          # required if the folder exists
│   ├── conventions.md       # optional: repo stack rules injected into prompts
│   └── prompts/             # optional: repo prompt overrides, by filename
│       └── update-traceability.md
├── AGENTS.md                # existing project system prompt (already loaded by Pi)
└── …
```

A target repo with **no `aidw/` folder** is valid: it gets the toolkit's pure defaults.

Normative starting schema (final field names fixed in E3.1, with a JSON Schema plus round-trip
validation tests):

```yaml
schema_version: 1
requires_toolkit: ">=1.0.0"        # optional

repo:
  base_branch: main                # PR base and branch point
  branch_pattern: "{phase}-{task}" # branch and worktree name from task ids

paths:
  roadmap_dir: docs/tasks
  roadmap_glob: "[0-9]* - *.md"
  task_prompts_dir: docs/task-prompts
  implementation_results_dir: docs/implementation-results
  build_results_template: docs/implementation-results/TEMPLATE.md
  architecture_dir: docs/architecture

workflows:
  prompt:
    stages:
      - id: author
      - id: review
  implement:
    stages:
      - id: implement
      - id: test
      - id: record
      - id: pr
      - id: traceability          # repo-optional: enabled explicitly here
        enabled: true
        prompt: aidw/prompts/update-traceability.md   # explicit path (D14)
        agent: implementer
      - id: architecture
        enabled: true
    parallel_groups:              # replaces the hardcoded pair in workflows/implement.py:402
      - [test, architecture]

github:
  markers:                        # D5: these values are FROZEN for Mythical Forge
    parent: "<!-- mythical-forge-review-followups: pr={pr_url} -->"
    child: "<!-- mythical-forge-review-follow-up: pr={pr_url} finding={finding_id} -->"
    summary: "<!-- mythical-forge-review-followups-summary: pr={pr_url} -->"
  labels:                         # D5: names, colours and descriptions are FROZEN
    review-follow-up: {color: "5319E7", description: "Review-generated task or parent issue"}
    must-fix:         {color: "B60205", description: "Blocking review finding"}
    should-fix:       {color: "D93F0B", description: "Non-blocking but recommended finding"}
    could-fix:        {color: "FBCA04", description: "Limited review improvement or simplification"}
    decision-pending: {color: "EDEDED", description: "Human decision required before implementation"}
    approve-fix:      {color: "B8D64A", description: "Human-approved review follow-up fix"}
```

Precedence, highest first:

1. explicit `prompt:` path in the target config;
2. a same-named file in `<target>/aidw/prompts/`;
3. the toolkit default prompt;
4. failure — an unknown stage id or an unresolvable required prompt is an error, never a
   silent skip.

AIDT's built-in defaults under `paths:` are Mythical Forge's current values (D17), so Mythical
Forge's config file is close to empty and doubles as the documentation example.

**Configured read-paths must exist.** Every read-path under `paths:` — `build_results_template`,
`roadmap_dir`, `task_prompts_dir` — is validated when it is named by a config or a default. A
resolved path that does not exist is an error naming the field and the path, reported by `aidw
doctor` and by the stage preflight that first needs it; it is never a silent fallback and never
something the agent improvises around. This matters precisely because the *defaults* are Mythical
Forge's layout (D17, R7): a target repo — including AIDT's own repo — that does not have Mythical
Forge's files must supply them or override the field, and the failure must be legible when it does
not. Where the configured template is genuinely absent and the repo has results documents of its
own, the repo's config points at the template it does have; the toolkit does not guess.

**Gate commands come from the repo, not the toolkit.** The record stage's whole job is running the
repo's verification gate, so the concrete commands (Mythical Forge's `pnpm -r lint|build|test` plus
`pnpm srd:*` and `cdk synth`) travel in the target repo's `aidw/conventions.md` (D16, R10) — never
inline in a toolkit prompt. A repo with no conventions yet gets the gates its task prompt names
plus its stack's obvious build/test commands. A toolkit prompt must not name a package manager.

**One gate, one tree, one run (E4.8).** A stage that runs a gate records it through `aidw gate run
<key> -- <command>`, which hashes the change set it gated and stores the outcome in run state. A
later stage asking for the same key against identical content is handed
`reused: gate 'suite' passed for tree <id> at <time> by stage '<stage>' (<summary>)` instead of
re-running it, and cites that line with its origin. The identity deliberately excludes `HEAD`,
because `/pr` commits the very tree it gated — a `HEAD`-based identity would make the delivering
stage the one stage that can never reuse its predecessors' work. It is the content of the change
set relative to the base branch plus untracked non-ignored paths, minus the run's own state root
(otherwise every stage's log write would invalidate the tree) and minus any paths the gate
*declares* it cannot read (R18). Everything that cannot be proven runs: no resolvable base branch,
no run to cite from, a different command under the same key, a differently declared scope, or a
previous failure all mean the gate executes.

The declared scope is what makes the reuse real rather than theoretical. `record` (I5) writes its
results document *after* it gates, and `update-traceability`/`update-architecture` write their own
documents earlier in the chain, so without a declaration no two stages ever agree on a tree and the
suite is bought again in `record` and again in `pr` — the exact ~390s of one E1.6 run. The default
declaration in the implement-chain prompts is the four configured write-targets
(`implementation_results_dir`, `architecture_dir`, `roadmap_dir`, `task_prompts_dir`), with the
rule stated alongside it: never ignore source, tests, config or lockfiles, and pass the same values
from every stage or the outcomes cannot line up. As with gate commands themselves (R14), the repo
owns the declaration; the toolkit only records it and prints it in every citation.

### 3.5 Stage and workflow model

`build_plan()` in `workflows/implement.py:104` already returns a list of
`PlanStage(id, name, agent, prompt_file, variables)`. Extraction keeps that shape and makes it
**data**, loaded from config, with the current chains as defaults.

Current reality — the full inventory of stages, to be preserved exactly:

| Workflow | Stage id | Stage name | Agent | Prompt | Portable? |
|---|---|---|---|---|---|
| prompt | P1 | task-prompt | task-author | task-prompt.md | repo-specific content |
| prompt | P2… | task-review-N | task-reviewer | task-review.md | yes |
| prompt | fix loop | task-review-fixes-N | task-fixer | task-review-fixes.md | yes |
| implement | I1 | impliment-task | implementer | impliment-task.md | mixed |
| implement | I2 | test | tester | test.md | mixed |
| implement | I3 | update-traceability | implementer | update-traceability.md | **repo-specific** |
| implement | I4 | update-architecture | implementer | update-architecture.md | **repo-specific** |
| implement | I5 | record-implementation-results | recorder | record-implementation-results.md | mixed |
| implement | I7 | update-roadmap | recorder | update-roadmap.md | yes (H3.1) |
| implement | I6 | pr | pr-publisher | pr.md | mixed |
| review | R1 | code-review | code-reviewer | code-review.md | yes |
| review | R2 | review-findings-to-github | review-publisher | review-findings-to-github.md | yes (markers) |
| fix | F1… | fix-next-review-followup | fixer | fix-next-review-followup.md | mixed |
| fix | — | code-review (re-review) + test | code-reviewer / tester | code-review.md, test.md | as above |
| approve | A1 | approve-review-followups | review-approver | approve-review-followups.md | yes |

Rules:

- Keep the existing stage ids (`I1`…`I6`, `P1`, `R1`, `R2`) as defaults, for continuity in
  existing run artifacts and `state.json`.
- **H3.1 amended this inventory:** `I7 update-roadmap` is a **core** stage added after `I5` and
  before the approval gate and `I6`, on the `recorder` agent with `prompts/update-roadmap.md`. It
  owns the one roadmap checkbox (`I3` keeps only its repo-specific artifacts and stays
  repo-optional), so `STAGE_IDS` gains `I7` while `REPO_OPTIONAL_IDS` stays `{I3, I4}`. The
  vocabulary decision and its prompt-fixed field names (`{roadmap_file}`/`{checkbox_id}`) are
  recorded in `design.md` §17 (Y1).
- Core mandatory stages (D13): implement, test, code-review, record, pr, plus Python-owned
  branch setup. The prompt workflow's author stage is core for that workflow.
- Repo-optional stages (D13): traceability, architecture. Disabled with `enabled: false`;
  core stages cannot be disabled or reordered (D12).
- Repos may add stages, including between core stages. A repo-added stage must declare `id`,
  `agent`, and either `prompt` or a file in `aidw/prompts/`.
- `parallel_groups` replaces the hardcoded safe pair. Validate that every member exists and is
  not ordered against another member.

### 3.6 Prompt resolution

- Toolkit defaults: `<toolkit>/prompts/*.md`.
- Repo overrides: `<target>/aidw/prompts/*.md`, shadowing by filename.
- Pi must receive **both** template roots (`--prompt-template <toolkit>/prompts` then
  `--prompt-template <target>/aidw/prompts`) so repo files win, plus the explicit path when the
  stage declares one. **Verify Pi's precedence behaviour; do not assume it.**
- The `prompts/scripts/review-followup/` bundled scripts stay with the **toolkit** (GitHub
  bookkeeping, not repo-specific). Python-owned calls use `sys.executable`; prompt-invoked calls
  use `python3`, as today, but must locate the script through the runner-provided
  `AIDW_SCRIPTS_DIR` (the toolkit's absolute `prompts/scripts` directory). A path relative to
  the stage's working directory resolves inside the **target** repo, which has no `aidt/`
  checkout once the toolkit is extracted; `AIDW_SCRIPTS_DIR` is how E1.2's `ToolkitPaths`
  reaches a prompt.

### 3.7 Roadmap model (AIDT-owned, D6/D15)

AIDT defines and documents the format; the parser is generalised from `aidw/roadmap.py:62`.
Mythical Forge's `docs/tasks/*.md` files are the **reference implementation**.

- Required structure: `# Phase <n>:` heading, `## Epic <X>:` headings, checkbox entries
  `- [ ] **<id>. <title>** <context>.`, a one-line `Done when:` continuation, optional `Tests:`
  and spec citations.
- Per-repo config supplies only the directory and a filename pattern (D15). **No custom
  regex/parser dialect in v1** — a second dialect defeats the point of the toolkit owning the
  concept.
- The worked example in `docs/roadmap-format.md` §9 is the **single canonical format example**:
  `tests/test_roadmap.py` and `tests/test_roadmap_format.py` parse it out of the doc's bytes
  (E5.4), so the doc and the parser cannot drift.

### 3.8 Task-prompt format and repo conventions (D16)

- The toolkit owns the **format** prompt (`task-prompt.md`): conciseness budget, section
  structure, citation discipline, "Done when", "Files", "Tests" — all neutral.
- Repo stack rules (package manager, validation library, placement doc, property-test policy,
  gates) come from the target repo's root `AGENTS.md` plus optional
  `<target>/aidw/conventions.md`, which AIDT injects into `task-prompt`, `impliment-task`,
  `test` and `record-implementation-results`.
- Mythical Forge's current `task-prompt.md` is ~100% product-specific content (Design 21, pnpm,
  Zod, fast-check, `catalog.json`) and therefore **moves to Mythical Forge's
  `aidw/prompts/task-prompt.md`** at cutover (§7).

### 3.9 Persisted GitHub contracts — freeze semantics (D5)

`prompts/scripts/review-followup/constants.py` holds strings **already written into live GitHub
issues** (for example Mythical Forge parent issue #237 and children #238–#242):

- markers `<!-- mythical-forge-review-followups: … -->`, `…-review-follow-up: …`,
  `…-review-followups-summary: …`;
- labels `review-follow-up`, `approve-fix`, `decision-pending`, `must-fix`, `should-fix`,
  `could-fix`, and their exact colours/descriptions;
- exact-match comment bodies `Status: in progress`, `Status: fixed`, `Decision: approve-fix`.

Parent lookup is an **exact string match** (`gh.py` `find_parent_issues`). Renaming any of these
orphans every existing parent/child and causes duplicate issue creation on the next publish.

**Freeze means:** the values become per-repo config (§3.4) whose defaults are today's literals.
Mythical Forge's config pins the literals, so **not one character of any existing issue
changes**, while the toolkit stops hardcoding a brand. Changing these values for Mythical Forge
requires a one-time marker/label migration across open issues, and is explicitly out of scope
(§9).

Also frozen: the comment bodies must keep strict equality semantics (`logic.py` compares with
`==`). Do not normalise whitespace or case anywhere in that path.

### 3.10 State, runs, locking (D18)

```
<state root>/<repo-slug>/
├── runs/<run-id>/            # state.json, stages/, prompts/ — as today
└── locks/<branch>.lock       # one active run per worktree/branch
```

- `state root` = `AIDW_STATE_DIR` if set, else `dirname(<absolute git-common-dir>)/.aidw/state`,
  else `~/.aidw/state`.
- `repo-slug` = `owner-name` from `git remote get-url origin` when available, else the basename
  of the workspace root. Always present, so a fallback state root shared by several repos cannot
  collide.
- In the supported bare+worktrees layout the state root is outside every working tree, so
  `git worktree remove` can never delete a run.
- AIDT **warns** when the state root falls inside a working tree (single-checkout case), and
  **fails** when the workspace root is itself a registered worktree (§3.2 rejected layouts).
- Content under the current `aidt/runs/` is not migrated; it is gitignored and historical.

### 3.11 Version and compatibility (D10)

- `state.json` records `toolkit_version`, the resolved target config `schema_version`, and a hash
  of the resolved config, so a run can be explained after the fact.
- The toolkit refuses to run when `schema_version` exceeds what it understands, when
  `requires_toolkit` is unsatisfied, or when a required prompt cannot be resolved.
- `aidw doctor` validates the target config and reports per-value provenance.
- Semver the toolkit; a target repo may pin `requires_toolkit`.

### 3.12 New repo layout

```
aidt/                          # repo root; holds all AI developer tools
├── aidw/                      # the importable package (CLI: aidw)
├── prompts/                   # toolkit DEFAULT prompts (incl. scripts/review-followup/)
├── agent-configs/             # default agent configs (overridable per target repo)
├── agents/                    # default AGENTS.md / SYSTEM.md fragments
├── docs/
│   ├── history/               # aidw-initial-prompt*.md (D24)
│   ├── schema/
│   │   └── aidw-config.schema.json  # JSON Schema for the target config (§3.4, E3.1)
│   ├── roadmap-format.md      # the AIDT roadmap contract (§3.7)
│   ├── target-repo-config.md  # the config contract + worked example (§3.4)
│   └── migration/EXTRACTION.md  # this document, kept as history
├── tests/                     # pytest
├── fixtures/target-repo/      # a fixture target repo used by integration tests
├── design.md
├── README.md
├── pyproject.toml
└── .github/workflows/ci.yml
```

Naming note, worth one README line: inside the **toolkit** repo `aidw/` is code; inside a
**target** repo `aidw/` is configuration. Same word, two roles, by owner decision (D7).

`tests/fixtures/target-repo/` is **not optional**. The override mechanism (D4/D14), the stage
model (D12/D13) and the roadmap format (D15) are only proven by running the real workflows
against a fixture repo with a bare-plus-worktree layout.

---

## 4. Inventory: what is actually product-specific

Measured by grepping every file for product tokens, not by inspection.

### 4.1 Code — small

| Location | Product-specific | Action |
|---|---|---|
| `aidw/paths.py:16,28,29` | `aidt_root()` = `repo_root()/aidt`; `runs_dir()` | Replace with `ToolkitPaths` / `TargetRepo` / state root (§3.1) |
| `aidw/roadmap.py:62,120` | Parses `docs/tasks/<NN> - <Name>.md`; `RoadmapTask` | Keep the algorithm; AIDT owns the format; dir + glob from config (§3.7) |
| `aidw/workflows/prompt.py:125,154` | roadmap lookup; `docs/task-prompts/{phase}-{task}-prompt.md` | Config-driven paths |
| `aidw/workflows/run.py:24` | `docs/task-prompts/<phase>-<task>*.md` glob | Config-driven paths |
| `aidw/workflows/implement.py:210` | `docs/implementation-results/{branch}/build-results.md` | Config-driven paths |
| `aidw/workflows/implement.py:104-148` | `build_plan()` hardcodes I1–I6, including traceability and architecture | Config-driven stage model (§3.5) |
| `aidw/workflows/implement.py:402-404` | Hardcoded parallel pair `[test, update-architecture]` | `parallel_groups` (§3.4) |
| `aidw/workflows/implement.py:3` | Docstring cites the product's `docs/workflow.md` | Neutral wording |
| `aidw/workflows/{review,fix,approve}.py` | `StageSpec(… aidt/"prompts"/… )` hardcoded prompt paths | Prompt resolver (§3.6) |
| `aidw/config.py:275-309` | The implicit two-root split | Formalise into `ToolkitPaths` / `TargetRepo` |
| `aidw/doctor.py:206,214` | `_check_archify` (`~/.pi/agent/skills/archify`); `_check_mcp(root/.mcp.json)`, an AWS MCP config | Keep as optional warnings; add git ≥ 2.31 and target-config validation |
| `aidw/inventory.py:23-50` | `REQUIRED_PROMPTS`, `REQUIRED_SCRIPTS`, `FOREIGN_PREFIX` | Split "toolkit defaults" from "resolved prompts"; keep the sentinel |
| `aidw/git.py` | Clean — no product coupling | Extend with worktree primitives |
| `aidw/cli.py:36,115`, `aidw/__init__.py:4-5` | Branding strings in help and docstring | Trivial |
| `tests/test_paths.py` | Asserts the `<repo>/aidt` layout | **Resolved in E0.4** — now `toolkit_root() == repo_root()`, and asserts no `aidt/` subdirectory exists |
| `tests/test_roadmap.py` | `test_load_tasks_real_roadmap` reads the **target repo's** `docs/tasks` and asserts Mythical Forge's content: `len(tasks) > 200`, and `03/E2/E2.9` present with `done is True`. The inline fixture itself is fine (its "Design 07 §1" text is cosmetic) | **Resolved in E0.4** — repo-ised to `test_load_tasks_reads_a_directory(tmp_path)`. E5.4 retires the inline fixture: the canonical format example is the worked example in `docs/roadmap-format.md` §9, which the roadmap tests now parse from the doc's bytes |
| `tests/test_prompt_workflow.py` | Three tests passed `repo=repo_root()` and expected a **real** Mythical Forge roadmap entry `03/E4/E4.1`: `test_prompt_workflow_dry_run` (asserts `code == 0`), `test_prompt_workflow_requires_main_for_real_run` and `..._requires_clean_tree` (assert `code == 4`). `load_tasks`/`find_task` run *before* the branch and clean-tree checks, so all three returned `2` instead | **Resolved in E0.4** — all three now use the file's own `_patch_prompt_repo(tmp_path)` fixture |
| Remaining 21 test modules | **Product-free** (zero token hits) | Portable as-is |

### 4.2 Prompts — three buckets (31 files)

**(i) Generic — ship as-is (6):** `code-review.md`, `task-review.md`, `task-review-fixes.md`,
`approve-review-followups.md`, `git-update.md`, `review-findings-to-github.md` (marker strings
only, and those are frozen).

**(ii) Mixed — path and tooling names, small edits (5):**

| Prompt | What to change |
|---|---|
| `test.md` | `pnpm --filter @mythical-forge/<pkg> test`; `docs/task-prompts/…`; `<file>.test.ts` co-location; `catalog.json` / `vectors.ts` |
| `pr.md` | The `pnpm install / -r lint / -r build / -r test` block; scope examples (`rules-engine`, `player-api`); the `(03-E2.9)` task-id example. **Partly edited ahead of E7.2:** the unconditional block is now a table keyed off files the repo has (`pnpm-workspace.yaml` → pnpm; `pyproject.toml`/`uv.lock` → uv) plus the `aidw gate run` idiom, so a non-pnpm repo no longer wastes turns on pnpm. The package-manager names, the scope examples and the task-id example remain E7.2's to remove (R17). |
| `fix-next-review-followup.md` | `pnpm --filter <affected-package>`; the marker literal; the AWS-credentials caveat |
| `record-implementation-results.md` | `docs/implementation-results/<branch>/build-results.md`, `TEMPLATE.md`, the `pnpm -r` matrix, `pnpm srd:*` validators, `cdk synth` |
| `impliment-task.md` | `pnpm srd:matrix-check`, `@mythical-forge/<pkg>`, `tests/integration/src/vector-matrix/vectors.ts`, `AGENTS.md` §6, `docs/conventions/srd-traceability.md`, **and the `git checkout -b` branch setup** (§3.2) |

**(iii) Wholly Mythical Forge — product prompts (20).** These move to Mythical Forge's
`aidw/prompts/` at cutover (§7), not into the toolkit:

`task-prompt.md` (Design 21, pnpm, Zod, fast-check, `catalog.json`), `update-traceability.md`,
`update-architecture.md`, `update-rules-engine-diagram.md`,
`update-rules-engine-diagram-{combat,movement,progression,skills,spells,vision-world}.md`,
`update-infrastructure-diagram.md`, `update-lambda-dataflow-diagram.md`,
`update-authentication-sequence-diagram.md`, `update-player-ws-message-flow-diagram.md`,
`doc-lambdas.md`, `integration-tests.md`, `show-updated-integration-tests.md`,
`show-updated-player-actions.md`, `implement-srd-followup.md`, `manual-test-plan.md`
(Cognito Hosted UI, CDK logical IDs, Lambda IAM).

**Architectural note.** `update-traceability.md` and `update-architecture.md` are **wired into
the implement chain** today (`implement.py:104-148`) yet are wholly product-specific. That is
exactly what D13 resolves: they become repo-optional stages supplied by the target repo.

### 4.3 Agents, configs, docs

| Item | Product-specific | Action |
|---|---|---|
| All 11 `agent-configs/*.yaml` | **No** — models, thinking, tools, timeouts; paths resolve against the aidt root | Portable as-is; keep `prompt_templates: - prompts` pointing at the toolkit's own `prompts/` |
| `agents/implementer/AGENTS.md` | Heaviest: "SRD traceability", "catalog, vector matrix", "pnpm/workspace/catalog conventions and Design 21 placement", "AWS resources live in `infra/` only", `AGENTS.md` §3 | Reduce to neutral duties; move stack rules to the repo `AGENTS.md` / `aidw/conventions.md` (D16) |
| `agents/recorder/AGENTS.md` | `docs/implementation-results/TEMPLATE.md` and output path | Config-driven paths |
| `agents/pr-publisher/AGENTS.md` | Repo PR conventions; the `(03-E2.9)` example | Neutral wording; conventions from the repo |
| `agents/task-author/AGENTS.md` | "Work only on the dedicated `{phase}-{task}` branch the prompt creates" | AIDT now creates it (§3.2); reword to "never write on the base branch" |
| Other 8 `agents/*/AGENTS.md`, `SYSTEM.md` | No — only `aidt/prompts/*.md` path references | Mechanical path updates |
| `design.md` | The design of record: D4, F1–F6, E4, the `aidt/` layout tree (`:97`), roadmap parsing (`:697`), the marker contract (`:403`), `mythical-forge` example paths | Rewrite for the two-root model (§6 E9) |
| `README.md` | Prerequisites, `cd aidt` quickstart, troubleshooting | Rewrite; drop the "inside the product repo" framing |
| `pyproject.toml` | Package dir `aidw/`; `testpaths` includes the bundled script tests | Fine; adjust paths |
| `aidw-initial-prompt*.md` | Historical design inputs | Move to `docs/history/` (D24) |

### 4.4 What is *not* coupled (verified good news)

- **`aidt/` is not in `pnpm-workspace.yaml`.** Removing it cannot affect the product's build,
  lint or test.
- Exactly three references to `aidt/` exist outside `aidt/`: `.gitignore:44` (`aidt/runs/`) and
  two lines in `.pi/prompts/simplify-spec.md` (`:26`, `:113`).
- No hardcoded repo owner, slug, or remote URL anywhere in the toolkit. All GitHub identity is
  discovered via `gh` at runtime.
- No domain leakage: zero references to sandbox, tenancy, DynamoDB, the rules engine, SRD
  mechanics or AWS resources in `aidw/`. The toolkit only ever spoke to them through prompts.

---

## 5. Migration approach

### 5.1 Strategy: copy verbatim, freeze the original, refactor once

1. Create the new repo and make its **first commit a verbatim copy** of `aidt/` at a recorded
   SHA. No edits in that commit.
2. Tag that commit `baseline-verbatim`, so any later behavioural difference can be diffed
   against a known-good reference.
3. Do **all** refactoring in the new repo.
4. Delete `aidt/` from Mythical Forge **last** (§7), after the new repo is proven.

Never half-move. During the refactor, Mythical Forge's `aidt/` is **read-only reference** — no
edits, no fixes, even for bugs found along the way. Log those as tasks in the new repo instead.

### 5.2 What the verbatim copy includes and excludes

**Include:** `aidw/`, `prompts/` (including `prompts/scripts/review-followup/`), `agents/`,
`agent-configs/`, `tests/`, `design.md`, `README.md`, `pyproject.toml`, `uv.lock`,
`aidw-initial-prompt*.md`, and this document.

**Flattened to the repo root.** The copy places these at the new repo's root, *not* under an
`aidt/` subdirectory, because `pyproject.toml` declares
`[tool.hatch.build.targets.wheel] packages = ["aidw"]` and `uv tool install` needs the `aidw/`
package at the project root (§3.12).

Flattening **breaks the toolkit's own path resolution**, which assumes `<repo>/aidt`
(`paths.py:40`, `cli.py:54`). That is deliberate and is repaired by E0.4, the first functional
commit. Do **not** "solve" it by keeping an `aidt/` wrapper directory in the new repo — that
reintroduces the confusion the extraction exists to remove.

**Exclude** (generated, machine-local, gitignored): `.venv/`, `runs/`, `__pycache__/`,
`.pytest_cache/`.

**Record in the first commit message** the source repo, SHA and date:

```
chore: verbatim copy of aidt/ from mythical-forge@<sha>

Source: https://github.com/<owner>/mythical-forge @ <sha> (aidt/ subdirectory)
No changes from the source tree.
```

### 5.3 Working agreement in the new repo

- The new repo dogfoods its own SDLC (D21): `design.md`, a `docs/tasks/` roadmap, and task
  prompts. Until the toolkit is self-hosting (E4), tasks are plain markdown from this document.
- **Delivery depends on the task class (§5.5).** Only the tasks §5.5 sends through the pipeline —
  the ones that dogfood AIDW by authoring a task prompt — land on their own branch and go through
  a PR into the new repo's `main`. Base branch is always `main`, and **never merge from an agent**
  — the owner merges. Every other §6 task is implemented directly from this document and committed
  **straight to `main`**: no branch, no PR, because there is no pipeline output to review.
- Conventional-commit titles, matching what Mythical Forge already does.
- Ordering matters: E0 before everything; E1 and E2 before E3–E7, because later work assumes the
  two-root split and the worktree model.

### 5.4 Verification at every step

Every task's "Done when" must be demonstrable, not asserted:

- `uv run pytest` green, and `uv run aidw doctor` clean, from the toolkit root.
- The E4/E5 mechanisms are proven **against `fixtures/target-repo/`**, in a bare + worktree
  layout, not from a single checkout.
- A "no-regression" check throughout: with a Mythical-Forge-shaped config, the toolkit's resolved
  prompts, marker strings and label definitions must be byte-identical to the `baseline-verbatim`
  tag. This is what protects D5.

  **Scope:** the freeze covers the marker strings, labels and comment bodies (D5) and the bucket (i)
  prompts. The five bucket (ii) prompts are *edited* by E7.2, so they cannot be byte-identical in
  the toolkit; Mythical Forge keeps its exact text through same-named overrides in `aidw/prompts/`
  (D14 precedence 2). MF.2 must deliver those overrides, or the freeze silently stops covering the
  record stage's gate commands and template path.

### 5.5 Working method per task class

Do **not** run the full `aidw prompt` → review → implement pipeline over every task in §6. The
extraction document *is* the spec, and each task's own Deliverable/Done-when sits in the same
document as the §3 contract it depends on, so a task prompt would largely restate it. Use the
pipeline where the doc settles *what* but not *how*, and a mistake is expensive or hard to
reverse; implement directly everywhere else.

**Implement directly from this document:**
E0.1–E0.8, E1.4–E1.6, E2.3, E2.7–E2.9, E3.4–E3.7, E4.4, E4.7, E5.1, E5.3, E5.4, E6.2–E6.4,
E7.1, E7.4, E7.5, E8.1–E8.5, E9.1–E9.4, MF.1–MF.6.

**Author a task prompt for:**

| Task | Why it earns the extra stage |
|---|---|
| E1.1, E1.2, E1.3 | The two-root abstraction everything else depends on |
| E2.1, E2.2 | Worktree primitives and the layout guards — subtle, and the failure modes were found by experiment |
| E2.4, E2.5, E2.6 | Branch setup moves into Python; changes three workflows and the agent contract |
| E3.1, E3.2, E3.3 | The public config contract, layered resolution, and compat refusal |
| E4.1, E4.2, E4.3 | Stage registry, prompt resolver, porting five workflows |
| E4.5, E4.6 | Core-vs-optional enforcement, agent overrides |
| E4.8 | Touches state, the workflow gate contract and the record prompt's "no earlier-run numbers" rule; a wrong dedupe key would silently accept a stale gate |
| E5.2 | Parser generalisation |
| E6.1 | Plumbing config into the bundled scripts without breaking their standalone, stdlib-only contract — the riskiest single change in the plan |
| E7.2, E7.3 | Neutralising five prompts, and conventions injection |

**Sequencing constraint.** The pipeline is unavailable until E0.4 lands: the toolkit cannot
resolve its own prompts in the new repo before then (§5.2), so E0 and E1 are direct-implementation
work regardless of task class. Dogfooding is also not required for correctness — `fixtures/target-repo/`
(E4.7, E2.9) proves the override and stage mechanisms deterministically, and in CI.

**E0.7 is the gate for every task in the table above.** The roadmap is what makes roadmap-driven
authoring possible: `aidw prompt` reads `repo/docs/tasks` and exits `2` when the task is not
there. So E0.7 is **mandatory**, not optional, and it is the first thing to do once the toolkit
self-hosts. It appears in the direct-implementation list only because it cannot dogfood itself.
Conversely, a hand-written prompt file plus `aidw implement` skips the roadmap entirely —
`implement` derives the task id from the prompt filename — but that forfeits the task-author and
task-reviewer stages, which is most of the value for the tasks in the table.

---

## 6. Tasks

Numbering: `E<n>.<task>`. Each task is independently committable and PR-able. "Done when" is the
acceptance check.

### E0 — Extract the repository (verbatim, then self-hosting)

- [x] **E0.1 Create the new repository**
Create the remote repo `aidt` at the owner's account, default branch `main`.
- Deliverable: an empty repo with `main`.
- Done when: `git clone` succeeds and `main` exists.
- Open for the owner: visibility and licence. Do not guess either.

- [x] **E0.2 Verbatim copy commit**
Copy the §5.2 include-list at a recorded source SHA, flattened to the new repo's root; commit
exactly as in §5.2; tag `baseline-verbatim`.
- Deliverable: one commit containing the unmodified `aidt/` contents at the repo root.
- Done when: `diff -r <source>/aidt <new-repo> -x .venv -x runs -x __pycache__ -x .pytest_cache`
  is empty and the tag exists. (A `git diff` against `<source-sha>:aidt` will *not* be empty — the
  copy is flattened, per §5.2.)

- [x] **E0.3 Repo skeleton (file moves only)**
Move `aidw-initial-prompt*.md` to `docs/history/`; create `docs/roadmap-format.md`,
`docs/target-repo-config.md`, `docs/schema/`, `fixtures/` and `docs/migration/` placeholders;
move this document to `docs/migration/EXTRACTION.md`. No code behaviour changes.
- Deliverable: the §3.12 directory layout, with placeholders for docs written later.
- Done when: `git status` shows additions and renames only, and no Python file is modified.

- [x] **E0.4 Make the toolkit root its own repo (first functional commit)**
Flattening `aidt/` to the repo root breaks the toolkit's own path resolution: `paths.aidt_root()`
is `repo_root()/aidt` (`paths.py:40`) and `cli.py:54` does `aidt = repo / "aidt"`, so `prompts/`,
`agent-configs/`, `inventory` and doctor all point at a non-existent directory. Resolve the
**toolkit root from the package location** (`Path(__file__)` / `importlib.resources`) instead of
from git, and re-point the existing global `--repo` so it selects the **target** only. Rewrite
`tests/test_paths.py` (it asserts `<repo>/aidt`) and `pyproject.toml` `testpaths`.

Also repo-ise the tests that assert the **target repo's** content, or this task's Done-when is
unachievable: `test_roadmap.py::test_load_tasks_real_roadmap`, and
`test_prompt_workflow.py::{test_prompt_workflow_dry_run,
test_prompt_workflow_requires_main_for_real_run, test_prompt_workflow_requires_clean_tree}`
(see §4.1). **A toolkit test may never assert a target repo's content.**
- Deliverable: toolkit-root resolution, plus rewritten path tests and de-coupled roadmap tests.
- Done when: `uv run pytest` is green from the new repo root, and `uv run aidw doctor` and
  `uv run aidw prompts check` are clean in a repo whose `prompts/` sits at the repo root.
- Note: this is the minimal version of E1.2, landed early so the repo can run its own workflow.
  E1.2 formalises it into a type; E1.1 and E1.3 add the target, workspace and state roots.

- [x] **E0.5 CI**
`.github/workflows/ci.yml`: `uv sync`, `uv run pytest`, `uv run aidw doctor` on push and PR.
- Deliverable: a CI workflow.
- Done when: CI is green on `main` and on a test PR, and a deliberately broken test fails CI.

- [x] **E0.6 Provenance and naming note**
README states: the repo is `aidt`; the package/CLI is `aidw`; a target repo uses a tracked
`aidw/` folder for config; the source SHA of the baseline; and that inside this repo `aidw/` is
code while inside a target repo `aidw/` is configuration.
- Deliverable: README section.
- Done when: a reader with no context can explain the two roots after reading the README alone.

- [x] **E0.7 Convert this document's tasks into a roadmap (mandatory)**
**Mandatory, not optional.** `aidw prompt` is roadmap-driven: `prompt.py:123` reads
`repo/docs/tasks`, and `find_task` returning `None` exits `2` with `roadmap task not found`. Every
task §5.5 sends through the pipeline therefore depends on this one. It cannot dogfood itself — it
creates the file `aidw prompt` needs — so it is implemented directly.

Note that `aidw implement` does **not** read the roadmap: it derives `(phase, task, branch)` from
the prompt *filename* (`implement.py` `_PROMPT_NAME`). The roadmap gates prompt *authoring*, not
implementation.

Create `docs/tasks/00 - Extraction.md`. **The contract is five regexes in `aidw/roadmap.py`** —
match those, not the summary in §3.7:

    TASK_RE      ^\s*-\s*\[([ xX])\]\s*\*\*([A-Za-z0-9.]+)\.\s*(.*?)\*\*(.*)$
    EPIC_RE      ^##\s+Epic\s+([A-Za-z0-9]+):\s*(.*)$
    PHASE_RE     ^#\s+Phase\s+([0-9.]+):?\s*(.*)$
    DONE_RE      ^\s*(?:-\s*)?\**Done when:?\**\s*(.*)$      (IGNORECASE)
    _FILENAME_RE ^(\d{2}(?:\.\d+)?)\s*-\s*(.*)\.md$

Rules that bite, each verified against the shipped parser:

1. **The task id must be followed by a period inside the bold.** This document's own headings are
   `- [x] **E0.1 Create the new repository**` — no period — and that parses as task id `E0` with
   title `1 Create the new repository`. It fails *silently and destructively*: every entry
   collapses to the epic-level id with a stray leading digit in the title, so `find_task` finds
   nothing and `aidw prompt` fails. Add the period.
2. **Phase comes from the filename, not the heading** — `00 - Extraction.md` yields
   `entry.phase == "00"`, so the invocation is `aidw prompt 00 E0 E0.1`. `aidw prompt 0 …` does
   not match `find_task`.
3. **The filename must be exactly `\d{2}` + ` - ` + name + `.md`.** `0 -`, `000 -` and
   `extraction.md` all fail.
4. **`## Epic X:` and `# Phase N:` headings are cosmetic.** `epic` is derived from the task id
   (`derive_epic("E0.1") → "E0"`), and `find_task` matches on phase + task only. For a `00 -`
   file, `# Phase 0:` does not even match `PHASE_RE`, so `phase_title` stays `None`. Harmless.
5. **`- Done when:` must appear before any blank line** after the task line. Intervening lines are
   fine: this document's `- Deliverable:` line between the task and its `Done when` parses
   correctly, and the task's prose detail may sit on the line *after* the `**` rather than inline.
6. **Exclude MF.1–MF.6.** They would parse as phase-`00` tasks with id/epic `MF`, but they are
   work in the *Mythical Forge* repo. They belong in Mythical Forge's roadmap, or nowhere.
7. **Carry the checkbox state over** (`[x]` for E0.1–E0.6, `[ ]` for the rest). `find_task`
   ignores `done`, and `aidw tasks --todo` filters on it.

Guard against rule 1 before relying on the file. Kept to a single line, and single-quoted, so it
survives a copy-paste out of this indented block; it exits non-zero on a collapsed id:

    uv run python -c 'import pathlib; from aidw.roadmap import load_tasks; t=load_tasks(pathlib.Path("docs/tasks")); assert t, "no tasks parsed"; bad=[x.task for x in t if "." not in x.task]; assert not bad, f"MISPARSE: {bad}"; print(f"{len(t)} tasks, none collapsed")'

- Deliverable: `docs/tasks/00 - Extraction.md`, plus one task prompt authored through the toolkit
  as a smoke test.
- Done when: `uv run aidw tasks --phase 00` lists every §6 task (E0–E9, none collapsed), the guard
  above passes, and one `aidw prompt 00 E1 E1.1` run produces a prompt for review. (E1.1 rather than
  E0.1: E0.1 is already complete, so its prompt would be a throwaway, whereas E1.1 is the first task
  that actually needs the pipeline — the smoke test doubles as its real authoring step.)
- Known frictions: `prompt.py:123` hardcodes `docs/tasks` until E3, and `_FILENAME_RE` requires a
  two-digit phase, so branches are named `00-E1.1` until `repo.branch_pattern` is configurable
  (E4).

- [ ] **E0.8 Test-suite runtime budget**
The suite is the largest single cost in every workflow stage: `test` (I2), `record` (I5) and the
implementer each re-run most of it, and §5.4 makes `uv run pytest` the verification for every task,
so its runtime multiplies across E0–E9. One E1.6 run spent ~1000s re-running it.

Measure with a `subprocess` profiler before optimising — `--durations` alone misattributes this
suite. Measured cause: 3185 process spawns accounted for 136.6s of the 145s, and the driver is
`git`, not the CLI. `TargetRepo.resolve` ran three `git rev-parse` invocations per call (the single
hottest path in the toolkit, not just in tests); the repo fixtures ran two `git config` spawns each
across ~300 repositories; and the doctor tests spawned real `pi`/`gh` binaries (~25s). Fix those
then parallelise the remainder with `pytest-xdist` (`-n auto` in `addopts`, so every stage and CI
inherit it; `-n0` gives a serial run).
- Deliverable: a runtime measurement plus the changes that reduce it.
- Done when: full-suite wall time is measured before and after, the reduction is at least 2×, and
  `uv run pytest` is green with no test deselected or skipped to achieve it.
- Measured: 129.5–150.3s serial before → 65.0s serial after (spawns 3185 → 1843) → 33.9–36.4s under
  `-n auto`; `TargetRepo.resolve` 3 spawns/132ms → 1 spawn/37ms; 450 tests throughout, none
  deselected or skipped.

### E1 — Two-root core

- [x] **E1.1 `TargetRepo` resolution (D19)**
Implement target resolution: cwd walk-up, then `--repo <path>`, then `AIDW_REPO`. Expose
`root`, `git_dir`, `common_dir`, `base_branch` (from config, E3).
- Deliverable: a `TargetRepo` type plus tests including: inside a worktree; inside a subdirectory;
  an explicit `--repo`; a non-repo path; the bare dir.
- Done when: tests prove `repo_root` semantics are preserved and the bare dir is rejected.

- [ ] **E1.2 `ToolkitPaths`**
Resolve the installed toolkit root from `Path(__file__)`/`importlib.resources` — never from git.
Expose `prompts_dir`, `agent_configs_dir`, `agents_dir`, `scripts_dir`.
- Deliverable: a `ToolkitPaths` type plus a test that it resolves when cwd is an unrelated
  directory.
- Done when: `aidw doctor` can report the toolkit root while invoked from `/tmp`.
- Note: E0.4 lands the minimal version of this so the repo is runnable; this task formalises it
  into a type and covers the installed (non-repo, `uv tool install`) case.

- [ ] **E1.3 Workspace and state root (D18)**
`workspace_root = dirname(git rev-parse --path-format=absolute --git-common-dir)`;
`state_root = AIDW_STATE_DIR or <workspace_root>/.aidw/state or ~/.aidw/state`; `repo_slug` from
`git remote get-url origin`, else the workspace-root basename.
- Deliverable: resolution helpers plus tests for: bare+worktrees; single checkout; no remote;
  unwritable workspace root; `AIDW_STATE_DIR` override.
- Done when: tests prove the state root is identical from every worktree of one repo and differs
  between repos sharing a parent directory.

- [ ] **E1.4 Port consumers and delete the old helpers**
Replace every `aidt_root()`/`runs_dir()` call site with the new types; remove both helpers;
rewrite `test_paths.py`.
- Deliverable: no remaining `repo_root()/aidt` assumption anywhere.
- Done when: `rg "aidt_root|runs_dir" aidw/` returns nothing, and `runs` are written under the
  state root.

- [ ] **E1.5 CLI plumbing**
The global `--repo` already exists (`cli.py:89`), but `_roots()` (`cli.py:51-54`) conflates the two
roots; E0.4 re-points it at the target only. Add `AIDW_REPO`, and thread the resolved `TargetRepo`
and `ToolkitPaths` through every workflow, replacing the `(repo, aidt)` tuple and
`cli.py:58`'s `_run_dir`.
- Deliverable: CLI + workflow changes.
- Done when: every workflow has a test asserting it operates on the target from
  `--repo`/`AIDW_REPO` while prompts resolve from the toolkit root, **including when the two are
  different directories**.

- [ ] **E1.6 `aidw config show` (skeleton)**
Print toolkit root, version, target root, workspace root, state root, and the config file found
(or none), each with provenance.
- Deliverable: the subcommand plus `--json`.
- Done when: the output is sufficient to debug a wrong-target or wrong-config invocation.

### E2 — Worktree model (D20)

- [ ] **E2.1 Git worktree primitives**
Add to `aidw/git.py`: `common_dir()`, `workspace_root()`, `worktrees()` (parse
`git worktree list --porcelain`), `worktree_for_branch()`, `add_worktree()`, `remove_worktree()`,
`is_linked_worktree()`.
- Deliverable: primitives plus tests against a real temporary bare+worktree repo.
- Done when: tests pass on macOS with git ≥ 2.31, and the parser handles the `bare` marker and
  detached HEAD.

- [ ] **E2.2 Target/layout guards**
Refuse to run when the target is the bare dir; **fail** when the workspace root is itself a
registered worktree of the same repo (the clone-of-a-worktree trap, §3.2); **warn** when the state
root falls inside a working tree.
- Deliverable: guards plus tests reproducing both rejected layouts.
- Done when: each failure prints the cause and the corrective command.

- [ ] **E2.3 `aidw worktree add|list|remove`**
Thin, safe wrappers over the primitives. `remove` refuses a dirty tree or an unmerged branch
unless `--force` is explicit. Never `reset --hard`, never delete uncommitted work.
- Deliverable: the subcommands plus tests.
- Done when: `worktree list --json` round-trips the branch↔path mapping and `remove` refuses the
  two unsafe cases.

- [ ] **E2.4 Branch setup becomes a Python stage, not a prompt**
Remove the `git checkout -b` instructions from `prompts/impliment-task.md` (§4.2). AIDT creates
the branch and its worktree before the first agent stage runs, using `repo.base_branch` and
`repo.branch_pattern` from config.
- Deliverable: a `branch-setup` core stage + prompt edits.
- Done when: `impliment-task.md` contains no `git checkout -b`/`git switch -c`, and a test proves
  the worktree exists before the implement stage starts.

- [ ] **E2.5 `aidw prompt` runs in the control worktree and creates the task worktree**
`aidw prompt` requires the control worktree (base branch checked out, clean). It creates the task
worktree, then runs the author/review/fix stages with `cwd` = the new worktree, and commits the
reviewed prompt on that branch.
- Deliverable: workflow changes.
- Done when: a full run creates exactly one new worktree, leaves the base worktree clean, and
  commits only the prompt path on the task branch.

- [ ] **E2.6 `implement`/`fix` resolve their worktree**
Resolve branch → worktree via `worktrees()`; when absent, print the exact
`git worktree add …` command and stop. `--repo` overrides.
- Deliverable: preflight changes plus tests.
- Done when: `aidw implement` from an unrelated cwd locates the right tree, and the missing-worktree
  message is copy-pasteable.

- [ ] **E2.7 One run per worktree**
Move the run lock into the state root, keyed by worktree path.
- Deliverable: locking change plus a concurrency test.
- Done when: two concurrent runs in the same worktree are refused; two runs in different worktrees
  proceed.

- [ ] **E2.8 Doctor: worktree and git checks**
Add git ≥ 2.31, workspace root, state root, target-is-not-bare, and control-worktree checks.
- Deliverable: doctor checks plus tests (follow the existing `gh version` check style, `FAIL` for
  hard blockers, `WARN` for advisory).
- Done when: `uv run aidw doctor` diagnoses each rejected layout by name.

- [ ] **E2.9 Worktree fixtures**
A test helper that builds a temporary bare repo with a `main` worktree and a task worktree, wired
off the bare repo exactly as §3.2 specifies.
- Deliverable: a shared fixture used by E2 and later epics.
- Done when: at least three tests across two modules use it, and it cleans up after itself.

### E3 — Target-repo config (D3, D10, D11, D12, D17)

- [ ] **E3.1 Schema, loader, validation**
`aidw/config.py` (or a new `aidw/target_config.py`) defines the §3.4 schema as dataclasses, plus
`docs/schema/aidw-config.schema.json`. YAML (D11). Unknown keys are an error, not ignored.
- Deliverable: loader + schema + round-trip tests.
- Done when: valid configs load; unknown keys, wrong types and bad enum values fail with the
  offending path in the message.

- [ ] **E3.2 Layered resolution with provenance**
Merge toolkit defaults → target config, recording the source of every resolved value.
- Deliverable: a resolution API returning values plus provenance.
- Done when: `aidw config show` reports, per value, whether it came from a default, the config
  file, or an override.

- [ ] **E3.3 Version and compatibility refusal (D10)**
Refuse to run when `schema_version` is newer than understood, or `requires_toolkit` is unsatisfied.
- Deliverable: a preflight check with a clear, actionable message.
- Done when: tests cover both refusals and the happy path.

- [ ] **E3.4 Defaults equal the Mythical Forge layout (D17)**
Every default under `paths:` and `repo:` matches Mythical Forge's current values, so a
Mythical-Forge-shaped config is valid and near-empty.
- Deliverable: defaults plus a test asserting each default value explicitly.
- Done when: a config file containing only `schema_version: 1` produces the Mythical Forge layout.

- [ ] **E3.5 `aidw/config.yaml` validation in doctor**
Report the config path found (or none), the resolved schema version, and any validation error.
- Deliverable: doctor check plus tests.
- Done when: a malformed config fails doctor with the field path, and a missing config passes with
  "defaults".

- [ ] **E3.6 Document the config contract**
`docs/target-repo-config.md`: every field, its default, its effect, the override precedence, and a
worked Minimal / Typical / Full example.
- Deliverable: the doc.
- Done when: a reader can write a correct config for a new repo without reading the code.

- [ ] **E3.7 Validate configured paths (fail closed)**
Classify every `paths:` entry as a **read-path** or a **write-target**. Read-paths must exist when a
config or default names them — `build_results_template`, `roadmap_dir`, `task_prompts_dir`,
`implementation_results_dir` — and a missing one is an error naming the field and the path, surfaced
by `aidw doctor` and by the preflight of the stage that first needs it. Write-targets are outputs of
a stage and may legitimately be absent (`architecture_dir` today, and any repo-added stage's dir):
they are created on demand and required only when a stage that writes there is enabled. Either way
there is no silent fallback and no agent-side improvisation: the record stage stops and reports a
missing build-results template rather than inventing a structure (§3.4, E7.2).
- Deliverable: path classification (read vs write) plus existence validation and tests, wired into
  doctor and the stage preflight.
- Done when: a config naming a nonexistent read-path fails with the field and the path in the
  message; a config whose only absent path is a write-target for a disabled stage passes; and a
  config whose write-target is needed by an enabled stage is either created or fails with a message
  naming the stage.

### E4 — Config-driven stages and prompt resolution (D2, D4, D12, D13, D14)

- [ ] **E4.1 Stage registry and workflow definitions as data**
Turn the current hardcoded chains (`implement.py:104-148`, `prompt.py:170+`, `review.py:135`,
`fix.py`, `approve.py:150`) into declarative defaults keyed by workflow and stage id, keeping the
existing ids (`I1`…`I6`, `P1`, `R1`, `R2`).
- Deliverable: a registry module plus a test asserting the default chains match today's order
  exactly.
- Done when: the default resolution reproduces the current six-stage implement chain, byte for
  byte, including prompt filenames and agents.

- [ ] **E4.2 Prompt resolver (D14)**
Resolve in precedence order: explicit `prompt:` path → `<target>/aidw/prompts/<name>` → toolkit
`prompts/<name>` → error. **Verify Pi's `--prompt-template` precedence empirically** and encode the
finding; do not assume.
- Deliverable: a resolver plus tests for every precedence level and the failure case.
- Done when: an override in the fixture repo is demonstrably the file Pi receives.

- [ ] **E4.3 Config-driven plans**
Port `build_plan` and the other workflows to build their stage lists from the registry.
- Deliverable: `implement`, `prompt`, `review`, `fix`, `approve` all config-driven.
- Done when: `--dry-run` output for each workflow is unchanged against the baseline with the
  Mythical-Forge-shaped config.

- [ ] **E4.4 `parallel_groups`**
Replace the hardcoded `[test, update-architecture]` pair. Validate members exist and are not
ordered against one another.
- Deliverable: config field + validation + tests.
- Done when: a configured group runs concurrently and an invalid group fails validation.

- [ ] **E4.5 Enforce core vs repo-optional (D12, D13)**
Reject attempts to reorder or disable a core stage; allow `enabled: false` only for repo-optional
stages; allow repo-added stages.
- Deliverable: validation plus tests for each rule.
- Done when: each rejection names the stage and the rule.

- [ ] **E4.6 Agent and model overrides**
Allow per-stage `agent`/`model`/`thinking`/`timeout_seconds` and a global agent-config override,
defaulting to the toolkit's `agent-configs/`.
- Deliverable: merge logic plus tests.
- Done when: a fixture override changes the model used in the rendered Pi argv.

- [ ] **E4.7 Override integration test (the acceptance test for E3+E4)**
Against `fixtures/target-repo/`: one stage overridden by filename, one by explicit path, one
falling back to the default, one repo-optional stage disabled, one repo-added stage, and a global
model override.
- Deliverable: an integration test asserting resolved prompt paths, agents and argv per stage.
- Done when: the test fails if any of the six behaviours regresses.

- [ ] **E4.8 Run each whole-repo gate once per tree**
Today `test` (I2), `record` (I5) and the implementer each run the full suite against the same tree,
and `record` re-runs subsets to fill its own rows — roughly 1000s of duplicated work in one E1.6
run. Record the gated tree identity alongside each gate outcome, and let a later stage in the same
run cite that outcome for the same tree instead of re-running it. This deliberately narrows the
record prompt's "never copy numbers from an earlier run": a same-run, same-tree outcome is evidence,
not a stale number, and it must be cited with its origin (stage, command, timestamp). Differing
trees always re-run. Depends on the identity recording in E8.2; if E8.2 has not landed, hash `HEAD`
plus the working-tree state as the interim identity.
- Deliverable: gate-outcome recording in state plus the reuse rule and tests.
- Done when: a run whose `test` stage gated tree `T` performs no second full-suite run for `T` in
  `record`, the recorded row still carries real numbers with their origin, and a changed tree forces
  a fresh run.
- **Landed so far:** the `aidw gate run|list` primitive, content tree identity (E4.8 chose content
  over the `HEAD`-plus-worktree interim: R16 records why), the declared gate scope that makes reuse
  fire across the document-writing stages (R18), `gate_outcomes` in run state under the existing
  `schema_version` (an older `state.json` still loads), `AIDW_RUN_ID`/`AIDW_STAGE` in the stage
  environment, and the gate idiom in the four implement-chain prompts (`impliment-task`, `test`,
  `record-implementation-results`, `pr`). **Remaining:** the same idiom in
  `fix-next-review-followup.md` (not in this chain), confirming reuse end-to-end against a real
  run, and E7.2's de-naming of `pr.md`'s stack-keyed command table and of the default `--ignore`
  path list (R17/R18 — both belong in the target repo's conventions, not the toolkit).

### E5 — Roadmap as an AIDT-owned format (D6, D15)

- [ ] **E5.1 Write the format contract**
`docs/roadmap-format.md`: the required heading/entry structure, the ids, `Done when`, optional
`Tests:`/citations, and a complete worked example. Mythical Forge's `docs/tasks/*.md` is the
reference implementation.
- Deliverable: the doc, with the worked example taken from the prefixed baseline.
- Done when: the example in the doc parses with the shipped parser.

- [ ] **E5.2 Generalise the parser**
Drive `roadmap.py` from `paths.roadmap_dir` + `paths.roadmap_glob`. Remove product assumptions from
its docstrings. No configurable dialect (D15).
- Deliverable: parser change plus tests.
- Done when: the fixture repo's roadmap parses without any code change.

- [ ] **E5.3 Format validation with actionable errors**
Report the file, line and rule when an entry is malformed (a task with no `Done when`, a duplicate
id, an entry outside an epic).
- Deliverable: validation plus tests.
- Done when: each malformed case names the file, line and rule.

- [ ] **E5.4 Promote the canonical example**
Move the `tests/test_roadmap.py` inline fixture into `docs/roadmap-format.md` and keep the test
reading it, so doc and parser cannot drift.
- Deliverable: single-source example.
- Done when: editing the doc to be invalid fails the test suite.

### E6 — Persisted GitHub contracts, per repo (D5)

- [ ] **E6.1 Move markers and labels into resolved config**
Populate `github.markers` and `github.labels` from config, with defaults **exactly** equal to
today's literals in `prompts/scripts/review-followup/constants.py`.
- Deliverable: config plumbing into the bundled scripts (via CLI args or a generated env/JSON
  handoff — choose whichever keeps the scripts standalone and stdlib-only).
- Done when: the bundled scripts still run standalone with no config present.

- [ ] **E6.2 Preserve matching semantics exactly**
No change to strict equality, no whitespace normalisation, no case folding, no regex
reinterpretation of markers. The label "ensure existing" path still never overwrites an existing
label.
- Deliverable: unchanged matching code paths, with tests pinning the semantics.
- Done when: the review-followup test suite passes unmodified except for the new config plumbing.

- [ ] **E6.3 Freeze test (the D5 guard)**
A golden test asserting that the Mythical-Forge-shaped config yields byte-identical marker strings,
label names, colours, descriptions and comment bodies to the `baseline-verbatim` tag.
- Deliverable: the test.
- Done when: changing any frozen value in Mythical Forge's config fails this test.

- [ ] **E6.4 Document the freeze**
Explain in `docs/target-repo-config.md` why these values are config-with-frozen-defaults, and what a
rename would break (orphaned parents, duplicate issue creation).
- Deliverable: documentation.
- Done when: the migration risk is stated where a config editor will read it.

### E7 — Split the prompt library

- [ ] **E7.1 Classify and relocate**
Apply §4.2: keep bucket (i), neutralise (ii), and move bucket (iii) to Mythical Forge's
`aidw/prompts/` at cutover (§7). Until cutover, leave (iii) in the toolkit but mark each file's
intended destination in a short header note.
- Deliverable: a classification table checked into the repo plus the bucket (iii) marker notes.
- Done when: every prompt file carries an explicit destination, and no file is unclassified.

- [ ] **E7.2 Neutralise bucket (ii)**
Replace repo-specific commands and paths with references to the target repo's conventions and the
config paths, per the §4.2 table. Keep the workflow semantics identical. Gate commands move to
`aidw/conventions.md` by name (§3.4); the build-results template becomes the configured path; and
the recorder's missing-template behaviour is stated explicitly (stop and report — never invent a
structure, never substitute another document). While neutralising, also drop the recipes a
non-interactive session refuses (`rm -rf`, `git init` scratch repos) in favour of `mktemp -d` and
the repo's fixtures, and require each gate command to run exactly once with every results row
derived from that single invocation.
- Deliverable: five edited prompts.
- Done when: the *rendered* prompt for each of the five names no package manager, no product path
  and no product doc — asserted against both a Mythical-Forge-shaped config and a neutral one, not
  by grepping the templates — and no prompt instructs a command the non-interactive runner blocks.

- [ ] **E7.3 Conventions injection (D16)**
Define how `AGENTS.md` and optional `<target>/aidw/conventions.md` reach the four prompts that need
them, and implement it.
- Deliverable: injection mechanism plus tests.
- Done when: a fixture repo's `conventions.md` appears in the rendered prompt for the relevant
  stages, and its absence is not an error.

- [ ] **E7.4 Neutralise the agent guidance**
Per §4.3: `agents/implementer/AGENTS.md`, `agents/recorder/AGENTS.md`,
`agents/pr-publisher/AGENTS.md`, `agents/task-author/AGENTS.md`.
- Deliverable: four edited files.
- Done when: no `agents/*/AGENTS.md` names a product, a package manager, or a product doc.

- [ ] **E7.5 Inventory split**
`inventory.py`: separate the toolkit's **default** prompts/scripts from the prompts **resolved** for
a target repo. Keep the `.pi/prompts` sentinel.
- Deliverable: inventory change plus tests.
- Done when: `aidw prompts check` validates the toolkit defaults and the resolved repo prompts
  independently, and reports which is which.

### E8 — Packaging, distribution, versions (D9)

- [ ] **E8.1 Installable package**
`pyproject.toml`: name `aidt` (or `aidw` — pick one and be consistent with the import name),
version, console script `aidw`, and `uv tool install git+…@<tag>` verified from a clean machine or
clean tool venv.
- Deliverable: working install.
- Done when: `uv tool install` then `aidw doctor` works from a directory unrelated to any repo.

- [ ] **E8.2 `state.json` records identity**
Record `toolkit_version`, resolved `schema_version`, and a hash of the resolved config.
- Deliverable: state changes plus tests.
- Done when: an old run's `state.json` explains which toolkit and config produced it.

- [ ] **E8.3 Version reporting**
`aidw --version`, and doctor reporting toolkit version, git version, and compat status.
- Deliverable: CLI + doctor.
- Done when: version output is available without a target repo.

- [ ] **E8.4 Install and worktree guide**
README: install paths (primary `uv tool install`, secondary `uvx`), the bare+worktree bootstrap
from §3.2, and the supported/rejected layouts.
- Deliverable: README sections.
- Done when: a reader can bootstrap a bare+worktree workspace from the README alone.

- [ ] **E8.5 Release process**
Tag-based releases; document how a target repo pins `requires_toolkit`.
- Deliverable: a short release doc plus the first tag.
- Done when: a target repo can pin and upgrade deliberately.

### E9 — Documentation

- [ ] **E9.1 Rewrite `design.md`**
Two-root model, worktree model, config and stage contracts, frozen GitHub contracts, state
locations, distribution. Replace D4/F1–F6/E4 and the `aidt/` layout tree; keep the design-of-record
tone.
- Deliverable: rewritten design.
- Done when: no section describes the toolkit as living inside a product repo.

- [ ] **E9.2 Write the two contract docs**
`docs/target-repo-config.md` (E3.6) and `docs/roadmap-format.md` (E5.1).
- Deliverable: both docs complete and cross-linked from the README.
- Done when: both examples validate against the shipped schema/parser.

- [ ] **E9.3 Move this document to history**
`docs/migration/EXTRACTION.md`, with a header noting it is historical.
- Deliverable: moved file.
- Done when: the tasks it contains are superseded by the repo's own roadmap.

- [ ] **E9.4 README rewrite**
Purpose, install, quickstart against a target repo, the `aidw/` naming note, troubleshooting
(including the stale-gh and worktree-layout failures).
- Deliverable: README.
- Done when: the §0 audience can operate the toolkit without reading `aidw/`.

---

## 7. Mythical Forge adoption and cutover

These tasks run **in the Mythical Forge repo**, after the toolkit is proven (i.e. after E0–E9 and
at least one real workflow run against a throwaway target repo). They are listed here so the
extraction is not considered done with Mythical Forge left broken.

**MF.1 Create Mythical Forge's `aidw/` folder**
`aidw/config.yaml` pinning the frozen GitHub contracts (§3.9) and enabling traceability and
architecture; `aidw/prompts/`; optional `aidw/conventions.md` capturing the stack rules currently
baked into `task-prompt.md` (pnpm, `workspace:*`/`catalog:`, Zod, Design 21 placement, property
tests, `srd:*` gates, `docs/conventions/srd-traceability.md`).
- Done when: `aidw config show --repo <mf>` resolves every path to where the files actually live,
  and `aidw doctor` is clean.

**MF.2 Move the product prompts**
Move the §4.2 bucket (iii) prompts (20 files) from the toolkit into `aidw/prompts/`. Keep the
filenames identical so stage resolution is by name. Mythical Forge also needs same-named overrides
for the five bucket (ii) prompts E7.2 neutralises: the toolkit default can no longer carry Mythical
Forge's gate commands (`pnpm -r lint|build|test`, `pnpm srd:*`, `cdk synth`) or its
`docs/implementation-results/TEMPLATE.md` reference, so Mythical Forge supplies its own text through
`aidw/prompts/` (D14 precedence 2) — or through `aidw/conventions.md` plus the configured
`build_results_template` — whichever keeps §5.4's freeze green.
- Done when: every product-specific prompt resolves from Mythical Forge, the five bucket (ii)
  prompts resolve to Mythical Forge's own text with its gate commands and template path intact,
  none remains in the toolkit, and the §5.4 freeze test passes.

**MF.3 Apply the cutover edits**
Remove `.gitignore:44` (`aidt/runs/`); update `.pi/prompts/simplify-spec.md:26,113`, which
currently refers to `aidt/`; add one line to `AGENTS.md` noting AIDT is now an external tool.
- Done when: `rg "aidt/" --glob '!docs/specs/**'` outside `docs/` finds nothing stale.

**MF.4 Delete `aidt/`**
One commit deleting the whole directory (D22). No stub, no history copy.
- Done when: `aidt/` is gone, `pnpm -r build`/`-r test` are unaffected, and
  `uv tool install` + `aidw doctor` still work against Mythical Forge.

**MF.5 First real run**
Run one end-to-end workflow against Mythical Forge in the bare + worktree layout: `aidw prompt`,
`aidw implement`, `aidw review`. Explicitly verify that the frozen markers still match the live
issues: `aidw approve-followups --pr <n> --dry-run` must find the existing parent (issue #237 for
PR #236) and report it as `already-approved` or `would-approve`, **never as "no parent found"**.
- Done when: that dry run resolves the existing parent and takes no write action.

**MF.6 Migration of open work**
Any in-flight branch or worktree still referencing `aidt/` is re-run with the installed toolkit.
Nothing else is preserved.
- Done when: no open branch depends on `aidt/` existing.

---

## 8. Acceptance criteria

The extraction is done when **all** of these hold:

1. A fresh machine can install the toolkit (`uv tool install git+…@<tag>`) and run `aidw doctor`
   with no checkout of any product repo.
2. A bare + sibling-worktree workspace bootstraps from the README alone, and every worktree of one
   repo resolves to the **same** workspace root and the **same** state root.
3. A target repo with **no** `aidw/` folder runs with pure defaults; a target repo with nothing but
   `schema_version: 1` gets the Mythical Forge layout.
4. Against the fixture repo, E4.7's six override behaviours all hold, including fallback to the
   default and disabling a repo-optional stage.
5. With a Mythical-Forge-shaped config, the E6.3 freeze test proves markers, labels and comment
   bodies are byte-identical to `baseline-verbatim`. No live issue changes.
6. `aidw prompt` creates the task worktree and leaves the control worktree clean; `aidw implement`
   and `aidw fix` locate that worktree from anywhere.
7. The rejected worktree layouts (bare-as-target, clone-hosting-worktrees) fail with the cause and
   the corrective command.
8. The repo's own CI is green: `uv run pytest` and `uv run aidw doctor`.
9. Mythical Forge has no `aidt/` directory and runs workflows through the installed toolkit (MF.1–MF.5).
10. No generated file is ever written inside a target repo.
11. A config naming a read-path that does not exist (`build_results_template`, `roadmap_dir`,
    `task_prompts_dir`) fails fast with the field and the missing path, and never silently falls
    back — including for AIDT's own repo, which must satisfy its own defaults.

---

## 9. Non-goals

Deliberately out of scope. Do not drift into these:

- **Migrating or renaming the frozen GitHub markers/labels** in Mythical Forge's live issues. They
  stay exactly as they are (D5). A rename would need its own migration plan.
- **Preserving git history** from the product repo (D8), or keeping a copy/stub of `aidt/` in
  Mythical Forge (D22).
- **A plugin/spec system for arbitrary SDLCs.** D12/D13 define a small, bounded override surface:
  replace a prompt, adjust stage metadata, add a stage, disable a repo-optional stage. No
  conditional logic, no scripting hooks, no per-repo Python.
- **A custom roadmap dialect per repo** (D15). One format, owned by AIDT.
- **Moving Mythical Forge's numbered spec set (`docs/specs/`) or its SDLC docs** into AIDT. Only the
  *structure* and *default prompts* move; content stays per repo.
- **Cross-repo parallelism, queues, or a server/daemon.** Separate `aidw` invocations in separate
  worktrees are the concurrency story.
- **Frontend/UI for AIDT.** CLI only.
- **Deployed integration tests** in AIDT's own CI (they need a deployed product stack). The
  `integration-tests.md` prompt stays a product prompt.
- **Migrating historical `aidt/runs/` artifacts** into the new state layout.

---

## 10. Decisions resolved while writing this document

Taken by the author to make the plan concrete, not explicitly reviewed by the owner. **Veto any of
these before starting E3**; several are cheap now and expensive later.

| # | Resolution | Why it matters |
|---|---|---|
| R1 | Workspace root = `dirname(<absolute git-common-dir>)`; `repo-slug` always present; state root = `<workspace root>/.aidw/state/<slug>` with `AIDW_STATE_DIR` and `~/.aidw/state/<slug>` fallbacks. | Implements D18. The `repo-slug` component is the part the owner did not specify; without it a shared parent directory collides. |
| R2 | Worktrees **must** be linked off the common dir; AIDT actively **fails** when the workspace root is itself a registered worktree. | The clone-hosting-worktrees trap silently puts state inside a prunable tree. Verified failure mode, not hypothetical. |
| R3 | Minimum git **2.31** for `--path-format=absolute`, enforced by doctor. | Avoids hand-rolling relative-path resolution and a second code path. |
| R4 | The control worktree is whichever worktree has `repo.base_branch` checked out; not a fixed name (`main/` in the examples is illustrative). | Keeps `main` out of the code for repos whose base branch differs. |
| R5 | The branch is created **with** its worktree (`worktree add -b`), so the branch is never checked out twice; the agent no longer runs `git checkout -b`. | Forced by git's one-branch-one-worktree rule. Changes `impliment-task.md` and `task-author/AGENTS.md`. |
| R6 | Stage ids `I1`…`I6`/`P1`/`R1`/`R2` are retained as defaults rather than renamed to semantic ids. | Keeps existing `state.json` artifacts and tests meaningful. |
| R7 | AIDT's built-in default path layout equals Mythical Forge's current layout. | Makes Mythical Forge's config near-empty and doubles as the documented example (D17), but means the *default* is not neutral. If you'd rather the defaults be generic, this is the moment to say so. |
| R8 | Generated state is **never** written into a target repo, including `.aidw/`. | Prevents tooling from dirtying a repo and keeps state safe from `worktree remove`. |
| R9 | The bundled review-followup scripts receive marker/label values via config passed in from the caller, and remain stdlib-only and standalone-runnable with no config present. | Preserves the scripts' stated portability contract while removing the hardcoded brand. |
| R10 | Repo conventions reach prompts by injection of `AGENTS.md` + `aidw/conventions.md` rather than by rewriting prompts per repo. | D16's intent; keeps bucket (i)/(ii) prompts single-sourced. |
| R11 | `parallel_groups` is the replacement for the hardcoded safe pair; members are validated but not automatically proven safe. | The current pair is safe because of *file ownership*, which the toolkit cannot infer. |
| R12 | Repo visibility/licence are left to the owner in E0.1 rather than assumed. | Not a technical decision, and hard to reverse for a public release. |
| R13 | The AIDT repo carries its own `docs/implementation-results/TEMPLATE.md` (the *format*, with this repo's stack in the example rows), so dogfooding resolves the same path a target repo does instead of depending on a Mythical-Forge-shaped default it does not satisfy. AIDT needs no `aidw/config.yaml` for this: the file now sits at the default path. | Without it every AIDT run from E1.3 onward hits the missing-template path: five runs already paid for the workaround, each recording a hand-written caveat and a longer list of prior offenders. R7's defaults are deliberately not neutral, so a repo using them must supply what they name — the fix is to supply it, not to neutralise the default and break Mythical Forge. |
| R14 | Gate commands travel in the target repo's `aidw/conventions.md` by name; no toolkit prompt names a package manager or a repo-specific validator. | Keeps D16/R10's single-sourcing and removes the last "the toolkit knows a product" coupling. A structured `gates:` config field was considered and rejected: it would be a third mechanism duplicating D16, and gate *commands* are prose the repo already owns. |
| R15 | A configured read-path that does not exist fails closed (E3.7), and the record stage stops and reports rather than inventing a structure. Write-targets are exempt: they are created on demand and required only by the stage that writes them. | Matches E4.2's rule for prompts ("never a silent skip"). The observed alternative — each run reverse-engineering the previous documents — is unbounded work that grows with the number of runs, and it hides a real configuration error. The read/write split matters immediately: AIDT's own `docs/architecture/` does not exist, and treating it as a must-exist read-path would fail the toolkit's own repo. |
| R16 | A gate outcome is identified by **content**, never by `HEAD`, and may only be cited within the same run. The identity is the change set relative to the base branch plus untracked non-ignored paths, minus the run's own state root; the recording primitive runs the command itself instead of accepting a reported result. | `/pr` commits the tree it just gated, so a `HEAD`-based identity (the interim E4.8 suggested) would make the delivering stage the one stage that can never reuse its predecessors' work — the exact cost E4.8 exists to remove. Content-only identity gives up a little precision (a rebuilt `.venv` is invisible to it), which `--force` and the always-present origin citation cover. Same run only: an earlier run's outcome is not evidence about this one. Running the command inside the primitive is what makes the recorded number real rather than transcribed. |
| R17 | `pr.md` names its stack's commands in a table keyed off files the target repo has, rather than being fully de-named now. E7.2 still owns removing the package-manager names. | The E1.6 evidence is that the old *unconditional* `pnpm` block cost the PR stage two wasted turns in a uv repo while staying correct for Mythical Forge. A file-keyed table removes the waste without stripping Mythical Forge's gates before MF.2 can supply same-named overrides — the regression E7.2/MF.2 exist to avoid. |
| R18 | A gate may **declare** the paths its command cannot read (`aidw gate run --ignore <prefix>`), and the declaration is part of what must match before its outcome can be cited. The scope is stored in the outcome and printed in every citation; nothing is inferred from file type or location. | A whole-tree identity is sound but useless in practice: I5 writes its results document after gating, so the tree I6 delivers never matches the tree I2 gated, and the suite is bought at every stage — the cost E4.8 exists to remove. No *automatic* narrowing is sound, because nothing can prove a gate did not read a given file (AIDT's own suite reads prompts and roadmaps; Mythical Forge's `srd:*` gates read `docs/rules-coverage/`). Declaring the scope at the stage that ran the gate keeps the claim explicit and auditable, in the same spirit as R14. |
