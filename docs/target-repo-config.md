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
  injected into the `task-prompt`, `impliment-task`, `test`, `record-implementation-results` and
  `update-traceability` prompts (§3.8/D16; `update-traceability` added by W1.1, design §17 Z13).
  It is also where a repo declares its **traceability artefacts**, including "none" (design
  §12.1). It is not a config key; `paths.*` does not point at it. Its gate commands (like
  `AGENTS.md`'s) are read only under a `## Gates` or `## Gate commands` heading, or under the
  heading named verbatim by the top-level `gates_heading` key (C1.2, design §7.3 step 4); any
  other gates-like heading leaves the evidence bundle's list `unavailable` and is reported by
  `aidw doctor` as a `gates heading` WARN.
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
- **Effect** names the consumer that reads the field. The consumer named there reads the
  **resolved** value — with one documented exception: the two `repo:` leaves, whose consumers
  hold the same literals on `aidw.paths.TargetRepo` (see "Override precedence" below).

### Top level

| Key | Type | Default | Effect |
|---|---|---|---|
| `schema_version` | integer | unset | The version of this schema the file is written against. Required whenever the file exists. A value **greater than** the toolkit's `SUPPORTED_SCHEMA_VERSION` (`1`) is refused (D10, §3.11): upgrade `aidt`, or lower the value. |
| `requires_toolkit` | string | unset | An optional minimum toolkit version as a PEP 440 specifier (`">=1.0.0"`), compared with `packaging`; the toolkit refuses to run when its own version does not satisfy it, or when the specifier is not valid PEP 440 (D10, §3.11). |
| `max_revisions` | integer | `3` | The revision budget of the `prompt` workflow (design §12): how many author→review→fix rounds run before the run blocks. `aidw prompt --max-revisions` overrides it; see the precedence section. |
| `gates_heading` | string | unset | An additional heading that introduces the target's gate commands, recognised beside the two built-in headings `## Gates` and `## Gate commands` (C1.2, design §7.3 step 4). The value is the **full heading line including its `## ` prefix** — for example `gates_heading: "## Verification gates"` — matched verbatim by the same prefix rule, never a bare title the code prefixes. It is read from `<target>/AGENTS.md` and `<target>/aidw/conventions.md` by `aidw/prompts.py:resolved_gate_block`, the one resolution both consumers use: the prompt workflow's evidence-bundle gate list (`aidw/workflows/prompt.py:_gate_block`, which maps a miss to `unavailable`) and the resolved gate block injected into the five gate-recording prompts (C1.3, design §7.3 step 5); an empty string is an error naming the field. A non-standard heading that is neither built-in nor declared leaves the bundle's gate list `unavailable` (a normal degraded state) and `aidw doctor` reports it as a `gates heading` WARN. |
| `repo` | mapping | unset | Repository and branch conventions (two fields below). |
| `paths` | mapping | unset | Per-repo path conventions (seven fields below). |
| `workflows` | mapping, open | unset | Workflow overrides keyed by workflow name. An open map, so a repo may add its own workflow as well as override `prompt`/`implement` (D12). |
| `github` | mapping | unset | The strings persisted to GitHub (D5, §3.9). |

### `repo:` — repository and branch conventions

| Key | Type | Default | Effect |
|---|---|---|---|
| `base_branch` | string | `main` | The PR base branch and the branch point of the task worktree (`git worktree add -b <branch> <path> <base_branch>`). It is also the ref the recorded gate change set is measured against, and `implement`/`fix` refuse to run on it. |
| `branch_pattern` | string | `{phase}-{task}` | The branch and worktree name, formatted from the task ids (`derive_branch_name`). It must reference both `{phase}` and `{task}`; a pattern that does not is a usage error before any worktree or stage exists. |

### `paths:` — per-repo path conventions

Values are repo-relative path strings. The loader stores them verbatim and touches no other file;
existence validation is a separate pass (`aidw.target_config.validate_paths` /
`ensure_write_targets`, E3.7), described under "Configured paths must exist".

| Key | Type | Default | Effect |
|---|---|---|---|
| `roadmap_dir` | string | `docs/tasks` | Directory the roadmap parser reads phase files from (`aidw.roadmap.load_tasks`, used by `aidw roadmap` and by `aidw prompt`'s prerequisite check). A read-path. |
| `roadmap_glob` | string | `[0-9]* - *.md` | Filename pattern selecting phase files inside `roadmap_dir` (D15). Literal space-dash-space: the real names are `00 - Extraction.md` and `03.1 - Target-repo config.md`; a `[0-9]*-*.md` typo matches nothing. Today `load_tasks` applies the equivalent built-in rule (`^(\d{2}(?:\.\d+)?)\s*-\s*(.*)\.md$`), so a value that does not select `NN - Title.md` files finds no roadmap at all. |
| `task_prompts_dir` | string | `docs/task-prompts` | Where the `task-author` stage writes `<phase>-<task>-prompt.md`, and where `aidw prompt`/`aidw run` look for the newest one. A read-path. |
| `implementation_results_dir` | string | `docs/implementation-results` | Where the record stage writes `<branch>/build-results.md`. A read-path. |
| `build_results_template` | string | `docs/implementation-results/TEMPLATE.md` | The template the record stage fills in to produce the results document. When it is missing the record stage stops and reports it instead of inventing a structure. A read-path. |
| `architecture_dir` | string | `docs/architecture` | Where the `update-architecture` stage reads and writes the architecture documents. A **write-target**: it may legitimately be absent and is created on demand. |
| `agent_configs_dir` | string | unset | A target-repo directory of agent configs (`*.yaml`) that **shadow the toolkit's `agent-configs/` by `id`** for every workflow of that repo (D12 "override agent config globally", E4.6). A **read-path** when named, so the directory must exist. Un-overridden toolkit ids still load, a brand-new id loads as an additional agent (a legal `agent:` target), and an empty directory equals the toolkit defaults. When unset the toolkit's own `agent-configs/` is used. |

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
| `agent` | string | unset | The agent the stage runs as, naming an agent config (`agent-configs/<id>.yaml` or a `paths.agent_configs_dir` override, `aidw.config.load_agent`). When unset, the toolkit's default agent for that stage applies. A declared id must resolve: an unknown one is refused in preflight. |
| `model` | string, non-empty | unset | Per-stage model override for this stage's invocation only (E4.6). It replaces the agent's `model` and never its `provider`: a value carrying the agent's own `provider/` prefix is qualified as-is, while a bare slug or another vendor-namespace slug (for example `meta/muse-spark-1.3` under `openrouter`) rides the agent's `--provider`. A provider change goes through `agent:` or `paths.agent_configs_dir`, not here. |
| `thinking` | string | unset | Per-stage `thinking` level for this stage's invocation only, one of `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` (design §5.1, E4.6). |
| `timeout_seconds` | integer | unset | Per-stage wall-clock timeout for this stage's invocation only, a positive integer (design §5.1, E4.6). |
| `when_paths` | list of strings | unset | The repo-relative path prefixes a stage whose registry definition carries `when=paths-changed` is gated on (S1.1/S1.2, design §12.2). The stage runs only when the run's change set touches one of them (`path == prefix` or the path is inside the directory); a withheld stage is recorded `skipped` with the prefixes named, and the run succeeds. Canonicalised on load (`./docs/x`/`docs/x/` are one value, sorted and deduped); a non-list value and each bad entry (a non-string, an absolute path, `.`, `..` or empty) are an error naming the field or entry path and the bad value is dropped. `I3 update-traceability` has **no** default path set, so an absent or empty list leaves it unconditional — a toolkit-hardcoded path set would be a product literal (§7.1). `I4 update-architecture` carries the toolkit default `docs/architecture`: it is D17's **literal** `architecture_dir` default, not the repo's resolved `paths.architecture_dir`. A repo-declared list **replaces** that default and never merges with it, so a repo that names diagram-input directories should **re-list** `docs/architecture` itself if it also wants the output directory watched. A repo with a **custom** `paths.architecture_dir` must declare its own `when_paths` naming it; otherwise `I4` watches a directory the repo does not use and skips on every run. An explicitly empty `when_paths: []` replaces the default and makes `I4` unconditional, which `aidw doctor` reports as a WARN. |

**Precedence (E4.6).** For one stage's invocation: the per-stage override wins over an agent loaded from `paths.agent_configs_dir`, which wins over the toolkit's `agent-configs/` default. A per-stage `model`/`thinking`/`timeout_seconds` is applied to the resolved agent for that stage only and is **not** re-run through the design §5.4 independence check — that check runs on the loaded (shadowed) agent dict, while a per-stage override is an explicit operator choice recorded in the argv and the stage's `state.json` record. Repo-added stages honour the same three fields uniformly.

### `github:` — persisted GitHub strings

These are the strings **already written into live GitHub issues** (D5, §3.9): the three markers
that identify the parent issue, the child issues and the single PR summary comment AIDT created,
and the labels the review-followup publisher ensures. **Freeze means** the values become per-repo
config whose defaults are today's literals, so the toolkit stops hardcoding the `mythical-forge`
brand while a config that does not mention this block resolves those literals byte-identically
(D17) and changes nothing in GitHub.

**Why config-with-frozen-defaults.** D5 freezes the literals ("no currently-persisted string in
GitHub changes"), and §3.9's mechanism is the one shape that satisfies both halves at once:
`github.markers` and `github.labels` are ordinary config (§3.4) seeded from
`aidw/target_config.py:TOOLKIT_DEFAULTS.github` (E6.1). That gives two different readers two
different, both-correct answers:

- **An existing repo changes nothing.** A config that declares neither block — or declares only
  part of one — resolves the rest from the defaults, which *are* the literals in the tables below
  (D17). `aidw config show`
  reports those leaves `default` instead of `config`; the values, and therefore every existing
  issue body and label, are unchanged.
- **Any repo may declare its own literals.** That is what removes the brand from the toolkit: a
  repo whose issues are marked differently supplies its own templates and definitions, and the
  publisher uses them.

Declaring this block is therefore a provenance/documentation choice, not a behaviour change: the
Full example below pins exactly the values it would otherwise inherit. Treat a *rename* as a
migration for the repo that owns the live issues, never as a config tweak.

> **Warning — renaming a frozen value breaks matching against live issues.**
>
> - **A renamed marker orphans every existing parent/child pairing.** Parent lookup is an
>   **exact string match**: `prompts/scripts/review-followup/gh.py:find_parent_issues` skips every
>   issue whose body does not contain the rendered marker
>   (`marker not in str(issue.get("body") or "")`). Issues created under the old marker stop
>   matching the new template, so the next publish finds no parent for the PR and creates a
>   **duplicate issue** — a second parent, plus a duplicate child per finding.
> - **A renamed label is created beside the old one, not renamed.**
>   `publish_review_followups.py:ensure_labels` only creates names it does not find (via
>   `gh label create`); the "ensure existing" path never updates an existing label, so a new name
>   yields a duplicate label for the same role while the old name stays on every issue that
>   already carried it.
> - **The comment bodies are compared with strict `==`**
>   (`prompts/scripts/review-followup/logic.py:has_exact_comment`,
>   `any(body == exact for body in bodies)`), so any edit — case, whitespace, punctuation — stops
>   availability and idempotency detection from seeing the comment: the script re-adds a status
>   comment, or fails to recognise an already-fixed or already-approved issue.

**Scope: what is config and what is not.** Only `github.markers` (parent/child/summary) and
`github.labels` (the six names with their colour and description) are
config-with-frozen-defaults, seeded at `aidw/target_config.py:TOOLKIT_DEFAULTS.github` (E6.1).
The three comment bodies (`Status: in progress`, `Status: fixed`, `Decision: approve-fix`) and the
role-name constants (`LABEL_REVIEW_FOLLOW_UP`, `LABEL_APPROVE_FIX`, `LABEL_DECISION_PENDING`,
`PRIORITY_LABELS`, `PUBLISHER_LABELS`) are **not** config: §3.4 has no field for them, so D5
freezes them where they live, in `prompts/scripts/review-followup/constants.py`. There is no
`github.comment_bodies:` or `github.role_labels:` key to declare — an invented one is refused as
an unknown key like any other.

**The guard, and the migration that is out of scope.** `tests/test_baseline_verbatim_golden.py`
(E6.3) pins the Mythical-Forge-shaped defaults — markers, labels, comment bodies and role names —
byte-identical to the `baseline-verbatim` tag, and `tests/test_target_config.py` pins the two
homes (`constants.py` and `TOOLKIT_DEFAULTS.github`) equal. Changing any frozen value for an
existing repo is therefore never a config edit alone: it requires a **one-time marker/label
migration across that repo's open issues**, which §9 leaves out of scope. AIDT neither plans nor
automates that migration.

#### `github.markers`

| Key | Type | Default | Effect |
|---|---|---|---|
| `markers` | mapping | unset | The fixed three-marker object; any other marker key is a typo and an error. |
| `parent` | string | `<!-- mythical-forge-review-followups: pr={pr_url} -->` | The parent-issue marker template, with `{pr_url}` substituted; it is also what parent lookup matches (the review-followup scripts' `find_parent_issues`). |
| `child` | string | `<!-- mythical-forge-review-follow-up: pr={pr_url} finding={finding_id} -->` | The child-issue marker template, with `{pr_url}` and `{finding_id}` substituted. |
| `summary` | string | `<!-- mythical-forge-review-followups-summary: pr={pr_url} -->` | The summary-comment marker template, with `{pr_url}` substituted. |

The values are **templates**, rendered with keyed `str.format` (`pr_url`, and `finding_id` for
`child`). A template with a stray `{` or an unknown placeholder cannot render, so it is refused
with a clear error before any marker is written — never a half-rendered marker or a silent
fallback to the default.

#### `github.labels`

`labels` is an open map keyed by label **name** (D5/§3.9). Every entry is exactly a colour and a
description, and both are required.

| Key | Type | Default | Effect |
|---|---|---|---|
| `labels` | mapping, open | unset | Label definitions persisted by the review-followup publisher. |
| `color` | string | required | The label colour, six hex digits as GitHub stores it (`B60205`, no leading `#`). |
| `description` | string | required | The label description. |

The six definitions that ship as defaults — the same names, colours and descriptions already on
live issues — are:

| Label name | `color` | `description` |
|---|---|---|
| `review-follow-up` | `5319E7` | Review-generated task or parent issue |
| `must-fix` | `B60205` | Blocking review finding |
| `should-fix` | `D93F0B` | Non-blocking but recommended finding |
| `could-fix` | `FBCA04` | Limited review improvement or simplification |
| `decision-pending` | `EDEDED` | Human decision required before implementation |
| `approve-fix` | `B8D64A` | Human-approved review follow-up fix |

A repo may declare more labels; they are definitions, and the publisher's own obligation stays
the fixed five (the six above minus `approve-fix`, which the approval step creates on demand).

The comment bodies (`Status: in progress`, `Status: fixed`, `Decision: approve-fix`) and the role
label names are **not** config either — §3.4 has no field for them — so D5 freezes them where they
live, in the scripts' `constants.py`; the scope boundary stated at the top of this section is the
complete list.

## Toolkit defaults

A value the config file does not declare resolves from `TOOLKIT_DEFAULTS` (§3.4, D17). The seeded
set is design §12's revision budget, the eight `repo:`/`paths:` leaves and the frozen D5 GitHub
strings — nothing else:

- `max_revisions` = `3` (`aidw.target_config.DEFAULT_MAX_REVISIONS`).
- `repo.base_branch` = `main`.
- `repo.branch_pattern` = `{phase}-{task}`.
- `paths.roadmap_dir` = `docs/tasks`.
- `paths.roadmap_glob` = `[0-9]* - *.md`.
- `paths.task_prompts_dir` = `docs/task-prompts`.
- `paths.implementation_results_dir` = `docs/implementation-results`.
- `paths.build_results_template` = `docs/implementation-results/TEMPLATE.md`.
- `paths.architecture_dir` = `docs/architecture`.
- `github.markers.parent`, `.child`, `.summary` = the three marker templates above.
- `github.labels.<name>.color`/`.description` = the six label definitions above.

The two `github.*` entries are the frozen D5 values: read the `github:` section above before you
pin or change one — it explains why they are config-with-frozen-defaults and what a rename breaks
(orphaned parent/child pairings, duplicate issue and label creation).

`paths.agent_configs_dir` is deliberately **not** seeded: its consumer falls back to
`<toolkit>/agent-configs/`, and seeding a repo-relative directory would make every repo
without that folder fail the read-path check.

These are Mythical Forge's current layout, not neutral placeholders (D17/R7) — which is why a
Mythical-Forge-shaped config file is near-empty and doubles as the Typical example below. A repo
that differs must override the fields it differs on; the defaults are not guesses about what a
generic repo might want.

**Unset, not defaulted.** Three things have **no toolkit default**, and a document that presented
them as already-defaulting would be wrong about `resolve_config`'s output today:

- `schema_version` — required *in* a config file, and unset when there is no file at all. It is
  therefore **not** defaulted to `1`: `max_revisions` and `schema_version` are different kinds of
  value, and only the former resolves when absent.
- `requires_toolkit` — an optional pin, never a default.
- `paths.agent_configs_dir` — optional, and unset means "use the toolkit's own
  `agent-configs/`" rather than a repo-relative default (E4.6).

A workflow name the config does not declare has no `workflows.*` entries at all: the default
stage registry is **E4.1's** and contributes no resolved values.

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

`repo.base_branch` and `repo.branch_pattern` have **two equal-valued homes**: the resolved
`TOOLKIT_DEFAULTS` leaves (`aidw/target_config.py`, seeded from EXTRACTION.md §3.4) and
`aidw.paths.TargetRepo`'s frozen dataclass defaults, which `tests/test_target_config.py` pins
equal. The consumers read the `TargetRepo` dataclass defaults: `implement`, `fix`, `review`,
`prompt` and `run` all take their base branch and branch/worktree pattern from the resolved
`TargetRepo` they were handed, and **no production code reads the resolved `repo.*` leaves**. A
`repo:` block therefore declares and displays a value in `aidw config show` (provenance
`config`) that those workflows do not consult: the dataclass literal is what governs the branch
point, the branch and worktree name, and the ref the recorded gate change set is measured
against. Read the resolved leaves for provenance; read `aidw.paths.TargetRepo` for behaviour.

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
  `paths.build_results_template`, `paths.roadmap_dir`, `paths.task_prompts_dir`,
  `paths.implementation_results_dir` and, when named, `paths.agent_configs_dir`. A missing one
  is an error naming the field **and** the path, reported by `aidw doctor` and by the preflight
  of the stage that first needs it. (§3.4's own paragraph lists three of these; E3.7's roadmap
  entry makes `implementation_results_dir` the fourth and E4.6 adds `agent_configs_dir`, which
  is unset by default so it is only checked when a repo names it.)
- **Write-targets** are outputs of a stage and may legitimately be absent: `paths.architecture_dir`
  today, and any repo-added stage's directory. They are created on demand and required only when
  a stage that writes there is enabled.
- Either way there is **no silent fallback and no agent-side improvisation**: the record stage
  stops and reports a missing build-results template rather than inventing a structure.

**Status.** Implemented in **E3.7**. `aidw.target_config.READ_PATHS` / `WRITE_TARGETS` hold the
classification, `validate_paths` performs the read-path check (pure: it stats and writes nothing),
and `ensure_write_targets` creates an enabled stage's write-target (`mkdir` only, disabled stages
skipped). `aidw doctor`'s `target config` check reports a missing read-path as a failure naming the
field and the path — for a default-sourced value too (D17/R7) — and is read-only, so it never
creates a directory. `aidw prompt`'s preflight refuses (exit 2, issues on stderr) before any run
state, branch or worktree. The loader itself still only records the strings, so a missing directory
is not a *load-time* error: validation is the separate pass above. `ensure_write_targets`'s call
site in the implement chain is E4.3's.

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

Resolves to the full Mythical Forge layout — `repo.*`, the six defaulted `paths.*` leaves,
`max_revisions` `3` and the three markers plus twelve label leaves from `TOOLKIT_DEFAULTS`, all
with source `default`, and `schema_version` `1` (`config`). Only `requires_toolkit` and
`paths.agent_configs_dir` resolve `unset`, and there is no `workflows.*` entry at all.

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

§3.4's own example, with `max_revisions` and C1.2's `gates_heading` added — loader-accepted
top-level keys that §3.4's snippet omits. `github.markers` and `github.labels` carry Mythical
Forge's frozen D5 literals:
declaring them pins them in the file, so `aidw config show` reports them `config` instead of
`default`. The values are identical either way — that is the point of the freeze.

```yaml
schema_version: 1
requires_toolkit: ">=1.0.0"        # optional

max_revisions: 3
gates_heading: "## Verification gates"  # extra gate-commands heading, full `## ` line (C1.2)

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
  agent_configs_dir: aidw/agent-configs   # global agent-config override (E4.6)

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
        when_paths:                   # S1.1: run only when the change set touches these
          - docs/traceability
          - docs/rules-coverage
      - id: architecture
        enabled: true
        when_paths:                   # S1.2: replaces the docs/architecture default
          - docs/architecture         # re-list the output dir to keep watching it
          - docs/diagrams
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

- [`workflow-stages.md`](./workflow-stages.md) — the companion reference: every stage of every
  workflow (agent, prompt, arguments, conditions, context), the loops, the gates and how the
  stage ids above bind to a declared `workflows.<name>.stages` list. Its tables are pinned to
  `aidw/stage_registry.py`, as this document's field tables are pinned to the loader.
- `docs/schema/aidw-config.schema.json` — the machine-readable shape of the config file (E3.1).
- `docs/roadmap-format.md` — the roadmap format that `paths.roadmap_dir`/`paths.roadmap_glob`
  point at (E5.1).
- `docs/migration/EXTRACTION.md` §3.4 (this contract), §3.5 (stage model), §3.9 (the D5 freeze),
  §3.11 (the D10 refusal), §3.12 (repo layout).
- `design.md` §12 (`max_revisions`), §5 (agent configs), §11 (roadmap).
- `<target>/AGENTS.md` — the project's system prompt, loaded by Pi as project context, and the
  first of the two D16 sources the gate list is resolved from
  (`aidw/prompts.py:resolved_gate_block`; the evidence bundle's
  `aidw/workflows/prompt.py:_gate_block` wraps it). It is **not** appended to rendered prompts
  (C1.1, design §7.3/§17 Z15).
- The optional `<target>/aidw/conventions.md` — repo conventions injected into rendered prompts
  (D16/§3.8).
