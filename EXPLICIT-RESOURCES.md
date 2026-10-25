# Explicit resources for AIDW agents

> ## Status: **NOT IMPLEMENTED**
>
> This document describes a **future state**, not the current behaviour of the toolkit.
> Nothing in it is enforced today: no flag, config field, validation rule, doctor check or
> test listed here exists yet. It is written now so the intent, the evidence and the
> consequences are on record before the work starts.
>
> - Implementation plan: [`docs/tasks/01 - Explicit Resources.md`](./docs/tasks/01%20-%20Explicit%20Resources.md)
> - Sequencing: **after the AIDT migration completes** (`docs/tasks/00 - Extraction.md`,
>   epics E1 and E9 in particular).
> - Until then, `design.md` remains authoritative wherever the two disagree, and the
>   leaks listed in [§1](#1-what-is-true-today-the-problem) are live.

## 0. The contract in one paragraph

**An agent config file is the only place where skills, extensions, custom tools and MCP
servers are declared for what Pi may pull into a stage.** AIDW passes Pi the flags that
switch resource discovery off, then re-declares exactly what the config names. Two
exceptions stay on, deliberately: the **target repo's `AGENTS.md`** context files, and
AIDW's own per-agent `agents_md`, which is appended to the system prompt. Everything else
— user-level skills, the four npm Pi packages, the target repo's `.pi/` tree, its
`systemGuard`-style system-prompt files, its MCP servers — is out of a stage's context
unless an agent config says otherwise.

## 1. What is true today (the problem)

`aidw/agents.py:23` (`build_argv`) renders a Pi command line that only ever *adds*
resources. It passes `--tools`, `--approve`, `--prompt-template <aidt>/prompts`, and — if
an agent config set them — `--skill`, `--extension`, `--mcp-config`. It never passes
`--no-skills`, `--no-extensions`, `--no-prompt-templates`, `--no-mcp` or `--no-approve`, so
Pi's own discovery and trust machinery stay fully armed.

Observed, not theorised. The self-hosted stage transcript in
`runs/20261025T205847Z-00-E1.2-prompt/stages/` (agent `task-reviewer`, `cwd` = the toolkit
repo) contains a system-prompt `skills` section of **6171 characters** advertising 14
skills — `archify`, `architecture`, `architecture-review`, `design`,
`designing-beautiful-websites`, `html-doc`, `improve`, `pdf-markdown`, `plan`, `task-to-pr`,
`domain-modeling`, `grilling`, `spec-concatenation`, `test` — resolved from
`~/.pi/agent/skills` (symlinks into `~/.agents/skills`). The agent config declares none of
them. Its `tools=` allowlist renders `read,bash`, so extension-provided tools such as
`web_search` are not declared, but the user's global extensions still load and execute.

Three further leaks, all consequences of `--approve` (which `build_argv` hardcodes) plus
discovery being on:

| Leak | Source | Reaches the stage as |
|---|---|---|
| Project skills | `<target>/.pi/skills` (trust-gated) | advertised skills, e.g. `design-log`, `srd-mapping` in `~/mythical-forge` |
| Project prompt templates | `<target>/.pi/prompts` (trust-gated) | a duplicate registry of `/code-review`, `/task-review`, … shadowing nothing but confusing audits |
| Project system prompt | `<target>/.pi/SYSTEM.md`, `.pi/APPEND_SYSTEM.md` (trust-gated) | arbitrary text in every agent's system prompt |
| Project settings/MCP | `<target>/.pi/settings.json`, `.pi/mcp.json` (trust-gated) | resource arrays and MCP servers |

Also broken today, and never exercised because no shipped agent sets the field:
**`mcp_config` maps to `--mcp-config`, which is not a Pi option** (`pi --mcp-config …` →
`Error: Unknown option: --mcp-config`). `design.md:420-428` (§7.4) documents this as the
mechanism for the AWS MCP server. It cannot work.

## 2. Why the current flags are not enough

Each denial flag has an exact, documented escape hatch, which is what makes the "config is
the only source" contract possible:

| Flag | Disables | Explicit declaration still loads |
|---|---|---|
| `--no-skills` (`-ns`) | discovered **and configured** skills | `--skill <path>` |
| `--no-extensions` (`-ne`) | discovered, configured **and built-in** extensions | `-e <path>`, `-e builtin:<name>` |
| `--no-prompt-templates` (`-np`) | discovered and configured templates | `--prompt-template <path>` |
| `--no-mcp` | built-in MCP support: no servers connect, no MCP tools, no `/mcp` | `-e builtin:mcp` plus explicit registration |
| `--no-approve` (`-na`) | every trust-gated project-local file | explicitly passed CLI resources (see [§7](#7-where-declared-resources-must-live)) |

`--no-approve` is the one that is easy to miss and is load-bearing: with `-ns -ne -np` the
resource arrays in a project `.pi/settings.json` are already neutralised, but
`.pi/SYSTEM.md` and `.pi/APPEND_SYSTEM.md` are trust-gated and have **no** disabling flag,
so a target repo could otherwise still inject system-prompt text into all 11 agents.

`--no-approve` does **not** touch context files. Pi states plainly that "context files such
as `AGENTS.override.md`, `AGENTS.md`, and `CLAUDE.md` load regardless of project trust
unless you disable context loading" (`docs/security.md`, *Resources protected by project
trust*). AIDW therefore **keeps** `--no-context-files` off by default, which is what
preserves the target repo's `AGENTS.md`.

## 3. The argv AIDW will pass

Discovery-denial flags first, then everything the config declares:

```
pi --provider P --model M --thinking T -p --no-approve --mode json
   (--session-id aidw-<run>-<agent>[-<stage>] | --no-session)
   [--system-prompt | --append-system-prompt] <agents/<id>/SYSTEM.md>
   --append-system-prompt <agents/<id>/AGENTS.md>
   (--tools a,b,c | --no-tools) [--exclude-tools 'mcp__*']
   --no-skills       [--skill <toolkit-relative> …]
   --no-extensions   [--extension <toolkit-relative|builtin:name> …]
   --no-prompt-templates --prompt-template <toolkit>/prompts
   --no-mcp          [-e builtin:mcp -e <toolkit>/extensions/aidw-mcp.ts]
```

| Concern | Today | Future |
|---|---|---|
| Project trust | `--approve` (trust everything the target declares) | `--no-approve` |
| User/global skills | discovered | `--no-skills` + declared only |
| Extensions (incl. npm packages, `builtin:*`) | discovered | `--no-extensions` + declared only |
| Prompt templates | toolkit registered **and** target `.pi/prompts` | `--no-prompt-templates` + toolkit only |
| MCP | `--mcp-config` (not a real flag) | `--no-mcp` unless declared ([§6](#6-mcp-options)) |
| Target `AGENTS.md` | loaded | loaded (unchanged) |
| AIDW `agents_md` | appended | appended (unchanged) |
| Tools | `--tools` allowlist | unchanged, plus `--exclude-tools 'mcp__*'` when MCP is not declared |

Order is fixed and tested, because `meta.json` records `argv` and the roadmap treats that
as the audit trail for what a stage inherited.

## 4. Agent config: the only declaration site

All fields already exist in `aidw/config.py` (`AgentConfig`, ~line 88) and in the
`design.md` §5.1 schema; only `tools` and `prompt_templates` are ever set today. The future
state makes the empty ones meaningful.

| Field | Renders as | Rules |
|---|---|---|
| `tools:` | `--tools a,b` (plain-name allowlist) or `--no-tools` | unchanged baselines (`design.md:255-267`); validation tightens ([§5](#5-validation-rules)) |
| `skills:` | repeated `--skill <path>` | resolved relative to the **toolkit root**; directory must contain `SKILL.md` with a `description` |
| `extensions:` | repeated `--extension <path|builtin:name>` | paths resolved from the toolkit root; `builtin:` names limited to `mcp`, `codemode`, `tool-search`, `llama.cpp` |
| `prompt_templates:` | repeated `--prompt-template <path>` | stays `[prompts]`; now the **only** registered set |
| `mcp_config:` | see [§6](#6-mcp-options) | currently a broken flag; either removed or made real |
| `agents_md:` | `--append-system-prompt <contents>` | unchanged, appended in every `system_prompt.mode` |
| `no_context_files:` | `--no-context-files` | default `false`; the **only** lever over context files |
| `cwd:`, `env:`, `session:`, `timeout_seconds:`, `max_cost_usd:`, `output:` | unchanged | unchanged |

A declared skill is still *advertised* to the model — Pi writes each available skill's
name, description and path into the system prompt and the model reads `SKILL.md` on demand
via the `read` tool. The difference is that the advertised set stops being a function of
what happens to be installed on the machine.

Declaring a skill explicitly also keeps read-only reviewers safe: they can still read a
skill's instructions, but they hold only the tools the allowlist names.

### Example (`implementer` after R4)

```yaml
id: implementer
tools: [read, bash, write, edit]
skills:
  - skills/archify             # toolkit-vendored, was ~/.pi/agent/skills/archify (machine-local)
extensions: []                 # empty by default: no npm packages, no builtin:*
prompt_templates: [prompts]
session: shared
```

## 5. Validation rules

Config loading (`aidw/config.py`) gains errors, because discovery being off turns "maybe
provided elsewhere" into "certainly not provided":

1. Unknown `builtin:<name>` entry → **error** (the four real names are the whole set).
2. Declared skill directory without `SKILL.md`, or whose frontmatter omits `description` →
   **error**. Pi silently drops such skills, so AIDW must fail loudly instead.
3. A tool name that is neither a built-in nor plausibly provided by a declared extension or
   MCP server → today a warning (`config.py:258-260`), future an **error**.
4. A declared skill/extension path that resolves **inside the target repo but outside the
   toolkit root** → **error** (see [§7](#7-where-declared-resources-must-live)).
5. Any `mcp__<server>__*` entry in `tools:` must match a server in the declared MCP config,
   and an agent with an MCP config must name its MCP tools explicitly so `--tools` filters
   them.
6. The target repo's own `aidw/config.yaml` may never carry resource fields
   (`skills`, `extensions`, `tools`, `mcp`, prompt templates). It configures *paths,
   branch naming and prompt overrides*, not what Pi can reach.

`check_read_only` (`config.py:370`) keeps its current job and gains a sibling: a strictly
read-only reviewer must not be reachable by `direct`-exposure MCP tools.

## 6. MCP options

Pi has exactly three ways to get MCP servers: the user file `~/.pi/agent/mcp.json`, the
trust-gated project file `.pi/mcp.json`, or an extension calling
`pi.registerMcpServer(name, config)`. There is no `--mcp-config`. Options:

- **A — No MCP (recommended now).** Delete the field, pass `--no-mcp` unconditionally.
  `design.md:252` already records "No baseline agent enables MCP in v1", and no shipped
  agent needs it. `--tools` then becomes a genuinely strict allowlist by construction.
- **B — A bundled registrar extension.** `aidt/extensions/aidw-mcp.ts` reads the declared
  config path from an env var (e.g. `AIDW_MCP_CONFIG`, set by `build_env`) and calls
  `pi.registerMcpServer()` per entry. argv adds `-ne -e builtin:mcp -e <toolkit>/extensions/aidw-mcp.ts`.
  The config stays the single source, the file keeps Pi's own `mcpServers` shape (so
  `${VAR}` and `!command` interpolation still work), and no user-level file is touched.
  Cost: one maintained TypeScript file plus a test against a trivial stdio MCP server, and
  verification that it works under `-p --mode json`.
- **C — Hermetic `PI_CODING_AGENT_DIR` per stage.** Generate `settings.json` + `mcp.json`
  for the run and symlink the rest. Rejected: it must mirror `auth.json`, `models.json`
  (the custom `muse-spark`/`glm`/`deepseek-v4` ids live there) and `npm/`, and it drifts
  every time Pi adds a config key.

### Tool reach truth table (why `--exclude-tools` is also needed)

`--tools` selects **declared** tools. It does **not** remove MCP tools unless one of its
entries starts with `mcp__`; `--exclude-tools` applies last, over everything including MCP.
MCP exposure decides whether a server's tools are declared (`direct`), searched
(`deferred`), reachable only from codemode scripts (`codemode`, the default), or
unreachable (`hidden`).

| Situation | Model can call | Note |
|---|---|---|
| `--tools read,bash` + `--no-mcp` + `--exclude-tools 'mcp__*'` | exactly `read`, `bash` | the future default for reviewers |
| `--tools read,bash` alone | `read`, `bash`, **plus any `direct`-exposure MCP tool** | the hole `design.md:250` currently claims does not exist |
| `--tools read,codemode` | `read`, `codemode` (which can call every MCP tool indirectly) | codemode is a built-in *extension*; `-ne` disables it |
| `--no-tools` | nothing (built-in, extension, custom and MCP) | used when `tools:` is empty |

## 7. Where declared resources must live

The toolkit root is resolved from the installed package (`aidw/paths.py`), never from git,
so in the Mythical Forge install it is `<target>/aidt/` — confirmed by a real stage's
argv: `--prompt-template /Users/phil/mythical-forge/aidt/prompts`
(`mythical-forge/aidt/runs/20261001T092419Z-03.1-A1/stages/task-prompt.meta.json`).

Therefore: declared skills and extensions are **vendored into the toolkit tree**
(`<toolkit>/skills/…`, `<toolkit>/extensions/…`) beside `prompts/`, so they travel with the
toolkit copy and a target repo can never inject one. Explicit `-e`/`--skill` paths pointing
into the target repo are rejected by validation (§5 rule 4) precisely because
`--no-approve` semantics for explicitly named project files are not something to rely on.

This has a concrete consequence for the prompt templates that reach outside the tree today:
`prompts/update-architecture.md` and the `update-*-diagram.md` family hardcode
`/Users/phil/.pi/agent/skills/archify/SKILL.md` and
`/Users/phil/.pi/agent/skills/archify/bin/archify.mjs` (24 references across `prompts/`),
and `aidw/doctor.py:243` checks that machine-local path. Either archify is vendored and
declared on `implementer` (the agent that owns `/update-architecture`, per
`design.md:312`), or it is recorded as a documented, doctor-checked exception. Silently
depending on a user-level skill while claiming config is the only source is the one outcome
to avoid.

## 8. What operators will notice

Running against `~/mythical-forge` (a trusted repo with a `.pi/` tree and an `AGENTS.md`):

- **Still in context:** the target `AGENTS.md`, and AIDW's own `agents_md` per agent.
- **No longer in context:** `~/.pi/agent/skills` and `~/.agents/skills` (unless declared),
  the four npm Pi packages (`pi-web-access`, `@ctogg/pi-cost-counter`,
  `@firstpick/pi-extension-safety-guard`, `pi-context-view`), the target's
  `.pi/skills/{design-log,srd-mapping}`, `.pi/prompts`, `.pi/SYSTEM.md`,
  `.pi/APPEND_SYSTEM.md`, `.pi/settings.json`, and any `.pi/mcp.json`.
- **Smaller, stable prompts:** the skills section disappears unless declared (≈1.5–2k tokens
  per stage in the observed run), and stage prompts stop varying with the machine.
- **Auditable:** `meta.json` already records `argv`; state/report will additionally record
  the declared resource set, so "what did this stage inherit?" is answerable from the run
  directory alone.

## 9. How this will be proven

1. **A fixture target repo** (`fixtures/target-repo/`, currently just `.gitkeep`) with a
   sentinel `AGENTS.md`, a stray `.pi/skills/*`, a stray `.pi/APPEND_SYSTEM.md`, and a
   `.pi/settings.json` that adds a skill. The integration test asserts the sentinel
   `AGENTS.md` **is** present in the stage system prompt, the strays are **not**, and the
   agent's own `agents_md` **is**.
2. **A transcript audit**: parse a real stage's JSONL and assert the `<skills>` section
   contains exactly the declared set (and that it is absent when nothing is declared).
3. **argv pinning**: unit tests assert the presence of every denial flag, the absence of
   `--mcp-config`, and that each `--skill`/`--extension` matches its config exactly.
4. **A doctor capability probe** (mirroring the existing `gh` probe at
   `aidw/doctor.py:155-203`): fail preflight if the installed Pi does not advertise
   `--no-skills`, `--no-extensions`, `--no-prompt-templates`, `--no-approve`, `--no-mcp`,
   `--exclude-tools` or `-e builtin:mcp`, so a Pi upgrade that renames a flag cannot
   silently re-enable discovery.

## 10. Open decisions

| # | Decision | Leaning |
|---|---|---|
| D1 | MCP: A (remove), B (registrar extension), or C (hermetic agent dir) | **A now**, B when a real agent needs the AWS server |
| D2 | Vendor archify into the toolkit, or keep it a documented machine-local dependency? | vendor, and declare it on `implementer` |
| D3 | Pin sessions with `--session-dir <run dir>` as well? | yes; it also stops a target's `sessionDir` from mattering |
| D4 | Do declared resources ever live outside the toolkit root? | no — validation rule 4 |
| D5 | Should the target repo's `AGENTS.md` remain unconditional, or per-agent? | unconditional (matches `design.md` §5.5) |
| D6 | Record the assembly order of target `AGENTS.md` vs AIDW `agents_md` and document precedence | record empirically; treat `agents_md` as the operating contract |

## 11. Evidence appendix (as of 2026-10-26)

| Claim | Evidence |
|---|---|
| argv only adds resources | `aidw/agents.py:23-80`; real argv in `runs/20261025T205847Z-00-E1.2-prompt/stages/task-review-2.meta.json` |
| 14 skills advertised to an agent that declares none | `runs/20261025T205847Z-00-E1.2-prompt/stages/task-review-2.jsonl`, system `sections.skills` (6171 chars) |
| `--mcp-config` is not a Pi option | `pi --mcp-config /tmp/nope.json -p hi` → `Error: Unknown option: --mcp-config` |
| Denial flags leave explicit declarations working | `docs/cli.md:196-207` |
| `--no-approve` blocks trust-gated project files | `docs/cli.md:290`, `docs/security.md` (*Understand project trust*) |
| Context files survive `--no-approve` | `docs/security.md` (*Resources protected by project trust*) |
| MCP sources and `--tools` interaction | `docs/mcp.md` (*Configure servers*, *Control tool exposure*) |
| Toolkit root is the package location, per-install | `aidw/paths.py`; `mythical-forge/aidt/runs/20261001T092419Z-03.1-A1/stages/task-prompt.meta.json` argv |
| Skill-dependent prompts use machine-local paths | 24 `archify` references across `prompts/`, e.g. `prompts/update-architecture.md:103,122`; `aidw/doctor.py:243` |

All Pi line/section citations are against the installed
`@earendil-works/pi-coding-agent` docs; all AIDW citations are against this repo at the
time of writing and are expected to drift during the E1 migration.
