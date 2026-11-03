# Target-repo configuration contract

> The authoritative description of `<target>/aidw/config.yaml` (EXTRACTION.md §3.4; decisions
> D3, D10, D11, D12 and D17). It documents **every field the loader accepts**, its type, its
> default, its effect, the two override-precedence layers, and three worked examples.
>
> The machine-readable counterpart is `docs/schema/aidw-config.schema.json`. That file describes
> the config **file**; toolkit defaults are applied by the resolver and are deliberately not
> expressed there. `aidw/target_config.py` is the implementation both this document and the
> schema must agree with, and `tests/test_target_repo_config_doc.py` fails when they drift.
>
> `<target>` is the **target repo root** — the working tree a workflow operates on (§3.1) — never
> the installed toolkit root. Inside a target repo `aidw/` is configuration; inside this toolkit
> repo `aidw/` is Python code (D7).

## What a target repo carries: the tracked `aidw/` folder

```
<target>/
├── aidw/
│   ├── config.yaml          # required if the folder exists
│   ├── conventions.md       # optional: repo stack rules injected into prompts (D16)
│   └── prompts/             # optional: repo prompt overrides, by filename (D4/D14)
│       └── update-traceability.md
├── AGENTS.md                # existing project system prompt (already loaded by Pi)
└── …
```

- `aidw/` is **tracked** in the target repo (D3): the configuration travels with the code it
  describes. It is not run state — state lives under the state root, outside every worktree
  (D18/§3.10).
- `config.yaml` is **required if the folder exists**: an `aidw/` folder without one is not a
  supported layout. A target repo with **no `aidw/` folder** is valid and gets the toolkit's
  pure defaults — that is the case `aidw doctor` reports as `none (defaults)` and that
  `resolve_config` turns into the full default layout. The loader only ever sees the *file* path,
  so it cannot tell those two apart; keep the invariant by not creating `aidw/` until you have a
  `config.yaml`.
- `conventions.md` is optional repo-stack material (gates, package manager, placement rules)
  injected into the `task-prompt`, `impliment-task`, `test` and `record-implementation-results`
  prompts (§3.8/D16). It is not a config key; `paths.*` does not point at it.
- `prompts/` is optional and holds prompt overrides **by filename** — the second step of the
  prompt-resolution order below. Nothing in it is a config key either.
- `AGENTS.md` at the repo root is read by Pi itself; `aidw/` config does not replace it.

## Field inventory

Every key the loader accepts, grouped by the object it belongs to. **Unknown keys are an error at
every object level** (for example ``unknown key `repo.base-brnach` ``), a wrong type names the offending field
path, and a config carrying such an error is refused before anything is resolved — a broken or
partial config is never silently patched with defaults.

In the tables below:

- **Type** is the YAML type the loader checks.
- **Default** is the *toolkit* default. `unset` means "no toolkit default exists": the value
  resolves unset (`null`, no source) unless the config declares it. `required` means the key has
  no default and must be present for the object it belongs to.
- A container (`repo`, `paths`, `workflows`, `github`, `markers`, `labels`) is itself unset when
  absent; its leaves resolve individually.
- **Effect** names the consumer that reads the field. E4–E6 rewire each consumer to the *resolved*
  value; until then the consumer named there owns the behaviour, with the default value
  hard-coded at that site.

### Top level

| Key | Type | Default | Effect |
|---|---|---|---|
| `schema_version` | integer | unset | The version of this schema the file is written against. Required whenever the file exists. A value **greater than** the toolkit's `SUPPORTED_SCHEMA_VERSION` (`1`) is refused (D10, §3.11): upgrade `aidt`, or lower the value. |
| `requires_toolkit` | string | unset | An optional minimum toolkit version as a PEP 440 specifier (`">=1.0.0"`), compared with `packaging`; the toolkit refuses to run when its own version does not satisfy it, or when the specifier is not valid PEP 440 (D10, §3.11). |
| `max_revisions` | integer | `3` | The revision budget of the `prompt` workflow (design §12): how many author→review→fix rounds run before the run blocks. `aidw prompt --max-revisions` overrides it; see the precedence section. |
| `repo` | mapping | unset | Repository and branch conventions (two fields below). |
| `paths` | mapping | unset | Per-repo path conventions (six fields below). |
| `workflows` | mapping, open | unset | Workflow overrides keyed by workflow name. An open map, so a repo may add its own workflow as well as override `prompt`/`implement` (D12). |
| `github` | mapping | unset | The strings persisted to GitHub (D5, §3.9). |

### `repo:` — repository and branch conventions

| Key | Type | Default | Effect |
|---|---|---|---|
| `base_branch` | string | `main` | The PR base branch and the branch point of the task worktree (`git worktree add -b <branch> <path> <base_branch>`). It is also the ref the recorded gate change set is measured against, and `implement`/`fix` refuse to run on it. |
| `branch_pattern` | string | `{phase}-{task}` | The branch and worktree name, formatted from the task ids (`derive_branch_name`). It must reference both `{phase}` and `{task}`; a pattern that does not is a usage error before any worktree or stage exists. |

### `paths:` — per-repo path conventions

Values are repo-relative path strings. The loader stores them verbatim and touches no other file;
existence validation is E3.7's (see "Configured paths must exist").

| Key | Type | Default | Effect |
|---|---|---|---|
| `roadmap_dir` | string | `docs/tasks` | Directory the roadmap parser reads phase files from (`aidw.roadmap.load_tasks`, used by `aidw roadmap` and by `aidw prompt`'s prerequisite check). A read-path. |
| `roadmap_glob` | string | `[0-9]* - *.md` | Filename pattern selecting phase files inside `roadmap_dir` (D15). Literal space-dash-space: the real names are `00 - Extraction.md` and `03.1 - Target-repo config.md`; a `[0-9]*-*.md` typo matches nothing. Today `load_tasks` applies the equivalent built-in rule (`^(\d{2}(?:\.\d+)?)\s*-\s*(.*)\.md$`), so a value that does not select `NN - Title.md` files finds no roadmap at all. |
| `task_prompts_dir` | string | `docs/task-prompts` | Where the `task-author` stage writes `<phase>-<task>-prompt.md`, and where `aidw prompt`/`aidw run` look for the newest one. A read-path. |
| `implementation_results_dir` | string | `docs/implementation-results` | Where the record stage writes `<branch>/build-results.md`. A read-path. |
| `build_results_template` | string | `docs/implementation-results/TEMPLATE.md` | The template the record stage fills in to produce the results document. When it is missing the record stage stops and reports it instead of inventing a structure. A read-path. |
| `architecture_dir` | string | `docs/architecture` | Where the `update-architecture` stage reads and writes the architecture documents. A **write-target**: it may legitimately be absent and is created on demand. |

### `workflows:` — stage and workflow overrides

An open map keyed by workflow name (`prompt`, `implement`, …). Only the *shape* is validated here;
the stage-id vocabulary, the core-vs-optional rules and the reorder/disable rules are D12/D13 and
are enforced by E4.1/E4.5, not by this schema.

A declared list **replaces** the toolkit's list wholesale: list values are copy-through, never
merged element-wise, so a stage you omit is not inherited from the default.

| Key | Type | Default | Effect |
|---|---|---|---|
| `stages` | list of stage entries | unset | The workflow's stage chain, in order. Each entry is a stage object (below). |
| `parallel_groups` | list of lists of stage ids | unset | Groups of stage ids that may run concurrently inside the workflow (it replaces the hard-coded safe pair). Every member must be a stage id of the same workflow. |

#### Stage entry

| Key | Type | Default | Effect |
|---|---|---|---|
| `id` | string | required | The stage id (`author`, `implement`, `test`, `record`, `pr`, …). Required and non-empty. |
| `enabled` | boolean | `true` | Whether the stage runs. A repo-optional stage (D13) is disabled with an explicit `false`; a core stage cannot be disabled or reordered (D12). |
| `prompt` | string | unset | The prompt for this stage, as a path — step 1 of the prompt-resolution order. When unset, resolution falls through to `aidw/prompts/` shadowing and then the toolkit default. |
| `agent` | string | unset | The agent the stage runs as, naming an agent config (`agent-configs/<id>.yaml`, `aidw.config.load_agent`). When unset, the toolkit's default agent for that stage applies. |

`model`, `thinking` and `timeout_seconds` are **not** stage fields: `STAGE_KEYS` is exactly `id`/`enabled`/`prompt`/`agent`, so the loader rejects them as unknown keys (E4.6 owns stage `model`/`thinking`/`timeout` overrides).

### `github:` — persisted GitHub strings

These are the strings **already written into live GitHub issues** (D5, §3.9). Freeze means the
values become per-repo config whose defaults are today's literals; parent lookup is an exact
string match, so renaming one orphans every existing parent/child and causes duplicate issue
creation on the next publish. The frozen D5 defaults are **E6's** to seed: until then every field
in this block resolves `unset`, and the §3.4 literals in the Full example below are declarations,
not toolkit defaults.

#### `github.markers`

| Key | Type | Default | Effect |
|---|---|---|---|
| `markers` | mapping | unset | The fixed three-marker object; any other marker key is a typo and an error. |
| `parent` | string | unset | The parent-issue marker template, with `{pr_url}` substituted; it is also what parent lookup matches (the review-followup scripts' `find_parent_issues`). |
| `child` | string | unset | The child-issue marker template, with `{pr_url}` and `{finding_id}` substituted. |
| `summary` | string | unset | The summary-comment marker template, with `{pr_url}` substituted. |

#### `github.labels`

`labels` is an open map keyed by label **name** (D5/§3.9). Every entry is exactly a colour and a
description, and both are required.

| Key | Type | Default | Effect |
|---|---|---|---|
| `labels` | mapping, open | unset | Label definitions persisted by the review-followup publisher. |
| `color` | string | required | The label colour, six hex digits as GitHub stores it (`B60205`, no leading `#`). |
| `description` | string | required | The label description. |

## Toolkit defaults

A value the config file does not declare resolves from `TOOLKIT_DEFAULTS` (§3.4, D17). The seeded
set is exactly design §12's revision budget plus the eight `repo:`/`paths:` leaves — nothing else:

- `max_revisions` = `3` (`aidw.target_config.DEFAULT_MAX_REVISIONS`).
- `repo.base_branch` = `main`.
- `repo.branch_pattern` = `{phase}-{task}`.
- `paths.roadmap_dir` = `docs/tasks`.
- `paths.roadmap_glob` = `[0-9]* - *.md`.
- `paths.task_prompts_dir` = `docs/task-prompts`.
- `paths.implementation_results_dir` = `docs/implementation-results`.
- `paths.build_results_template` = `docs/implementation-results/TEMPLATE.md`.
- `paths.architecture_dir` = `docs/architecture`.

These are Mythical Forge's current layout, not neutral placeholders (D17/R7) — which is why a
Mythical-Forge-shaped config file is near-empty and doubles as the Typical example below. A repo
that differs must override the fields it differs on; the defaults are not guesses about what a
generic repo might want.

**Unset, not defaulted.** Four things have **no toolkit default**, and a document that presented
them as already-defaulting would be wrong about `resolve_config`'s output today:

- `schema_version` — required *in* a config file, and unset when there is no file at all. It is
  therefore **not** defaulted to `1`: `max_revisions` and `schema_version` are different kinds of
  value, and only the former resolves when absent.
- `requires_toolkit` — an optional pin, never a default.
- `github.markers.*` and `github.labels.*` — the frozen D5 values become defaults in **E6**.
  Until then a config that does not declare them resolves them unset.
- `workflows.*` — the default stage registry is **E4.1's**. Until then a workflow the config does
  not declare has no resolved entries at all.

## Override precedence

There are **two independent layers**. They answer different questions and must not be conflated:
the first decides a *value*, the second decides which *prompt file* a stage runs.

### Value resolution: `override > config > default > unset`

`resolve_config` merges, highest first, and records the source of every resolved leaf:

1. **`override`** — a per-invocation override. Today that is exactly one thing: the `prompt`
   workflow's CLI flag `aidw prompt --max-revisions <n>` (design §12/H8). `aidw config show` takes
   no override flag.
2. **`config`** — the value the `<target>/aidw/config.yaml` declared. Declared-ness decides, not
   value equality: an explicit `max_revisions: 3` resolves `config`, not `default`.
3. **`default`** — `TOOLKIT_DEFAULTS`, the seeded set above.
4. **`unset`** — no override, no declared value and no default: the value is `null` and has no
   source.

`max_revisions` is the concrete case: `--max-revisions` > config `max_revisions` > `3`.
`aidw config show` prints one line per resolved leaf with its source, and `--json` emits the same
flat dotted-path map with `{"value": …, "source": …}` per leaf (`{"value": null}` when unset).

Note that `repo.base_branch`/`repo.branch_pattern` also have a second, frozen home today
(`aidw.paths.TargetRepo`'s dataclass defaults, equal to `TOOLKIT_DEFAULTS`); E4/E5 rewire the
consumers to the resolved value.

### Prompt resolution: explicit path, then filename shadowing, then the toolkit, then an error

A stage's prompt resolves in this order (§3.4, D4, D14) — highest first:

1. an explicit `prompt:` path in the stage's config entry;
2. a **same-named file** in `<target>/aidw/prompts/` — filename shadowing;
3. the **toolkit default** prompt (`<toolkit>/prompts/<name>.md`);
4. failure — an unknown stage id, or a required prompt that cannot be resolved at any step, is
   an **error**, never a silent skip.

The layer boundary matters: `prompt:` is a *stage field* consumed by this order only. It takes no
part in the value merge above, and no `paths.*` value selects a prompt.

## Configured paths must exist

§3.4 makes path existence part of the contract, not a nicety, precisely because the defaults are
Mythical Forge's layout (D17): a target repo — including this toolkit's own repo — that does not
have Mythical Forge's files must supply them or override the field, and the failure has to be
legible when it does not.

- **Read-paths** must exist when a config or a default names them:
  `paths.build_results_template`, `paths.roadmap_dir`, `paths.task_prompts_dir` and
  `paths.implementation_results_dir`. A missing one is an error naming the field **and** the
  path, reported by `aidw doctor` and by the preflight of the stage that first needs it. (§3.4's
  own paragraph lists three of these; E3.7's roadmap entry makes `implementation_results_dir` the
  fourth and is the exhaustive set.)
- **Write-targets** are outputs of a stage and may legitimately be absent: `paths.architecture_dir`
  today, and any repo-added stage's directory. They are created on demand and required only when
  a stage that writes there is enabled.
- Either way there is **no silent fallback and no agent-side improvisation**: the record stage
  stops and reports a missing build-results template rather than inventing a structure.

**Status.** This document states the contract. The classification, the existence checks and their
wiring into `aidw doctor` and the stage preflight land in **E3.7**; the loader here only records
the strings (it touches no file but the config itself), so a missing directory is not yet an
error at load time.

## Worked examples

Three complete configs, pairwise distinct. The Minimal and Typical examples resolve to the same
values with different provenance; the Full one declares everything. All three load with no
`ERROR` issue.

### Minimal — `schema_version` only

A repo shaped like Mythical Forge (D17) needs nothing else: the whole layout comes from the
defaults.

```yaml
schema_version: 1
```

Resolves to the full Mythical Forge layout — `repo.*` and all six `paths.*` leaves from
`TOOLKIT_DEFAULTS` with source `default`, `max_revisions` `3` (`default`) and `schema_version` `1`
(`config`). `requires_toolkit`, `github.markers.*` and every `workflows.*` entry resolve `unset`.

### Typical — the defaults echoed explicitly

The same layout, but with two values written into the file so `aidw config show` reports `config`
instead of `default` for them. This is the shape Mythical Forge's own config takes: near-empty,
because the defaults *are* its layout, with the handful of values it wants visible pinned.

```yaml
schema_version: 1

repo:
  base_branch: main            # echoes the default

paths:
  roadmap_glob: "[0-9]* - *.md"  # echoes the default
```

Resolves to exactly the same **values** as Minimal. Only the provenance differs:
`repo.base_branch` and `paths.roadmap_glob` now report `config`, everything else still `default`.

### Full — every field declared

§3.4's own example, with `max_revisions` added — a loader-accepted top-level key that §3.4's
snippet omits. `github.markers` and `github.labels` carry Mythical Forge's frozen D5 literals:
declaring them is what pins them, since the toolkit seeds no defaults for them until E6.

```yaml
schema_version: 1
requires_toolkit: ">=1.0.0"        # optional

max_revisions: 3

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
    parallel_groups:              # replaces the hard-coded safe pair
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

With every field declared, every resolved leaf reports `config` — there is nothing left to fall
back to. `workflows.implement.stages` carries the chain verbatim, including the explicit
`enabled: true` (equal to the stage default, which is why it survives only because the config
declared it).

## Related documents

- `docs/schema/aidw-config.schema.json` — the machine-readable shape of the config file (E3.1).
- `docs/roadmap-format.md` — the roadmap format that `paths.roadmap_dir`/`paths.roadmap_glob`
  point at (E5.1).
- `docs/migration/EXTRACTION.md` §3.4 (this contract), §3.5 (stage model), §3.9 (the D5 freeze),
  §3.11 (the D10 refusal), §3.12 (repo layout).
- `design.md` §12 (`max_revisions`), §5 (agent configs), §11 (roadmap).
- `<target>/AGENTS.md` and the optional `<target>/aidw/conventions.md` — repo conventions
  injected into prompts (D16/§3.8).
