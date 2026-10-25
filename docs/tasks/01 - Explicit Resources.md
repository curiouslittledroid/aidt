# Phase 01: Explicit resources

Make an agent config file the **only** place where skills, extensions, custom tools and MCP
servers are declared for what Pi may pull into a stage, while keeping two things that must
stay automatic: the **target repo's `AGENTS.md`** context files and AIDW's own per-agent
`agents_md` (appended to the system prompt).

The future state, with all evidence and the full rationale, is written up in
[`EXPLICIT-RESOURCES.md`](../../EXPLICIT-RESOURCES.md). That document is **not implemented**;
this roadmap is what implements it.

## Gate: do not start before the migration completes

Phase 01 edits the same code the migration is moving. Start only when these are done:

| Prerequisite | Why it blocks phase 01 |
|---|---|
| `E1.2`/`E1.4` `ToolkitPaths`, old helpers deleted | every task here resolves resource paths from the toolkit root |
| `E1.5` CLI plumbing (`TargetRepo` + `ToolkitPaths` threaded) | validation rule 4 needs both roots separately, not the `(repo, aidt)` tuple |
| `E3.6`/`E3.1` target-repo config contract | R2.5 constrains that contract's fields |
| `E9.4` README rewrite | R6.2 edits the README that E9.4 rewrites |

Every file/line reference below is as of 2026-10-26 and **will drift**; locate by symbol
name, not line number, when the time comes.

## How this phase is driven

Each task is authorable and implementable through the toolkit itself:

```bash
uv run aidw tasks --phase 01
uv run aidw agents validate --strict
uv run aidw prompt 01 R1 R1.1     # then implement, test, review, PR
```

Parser guard (run after any edit to this file — a missing period after the task id silently
collapses every id and breaks `aidw prompt`):

```bash
uv run python -c 'import pathlib; from aidw.roadmap import load_tasks; t=load_tasks(pathlib.Path("docs/tasks")); assert t, "no tasks parsed"; bad=[x.task for x in t if "." not in x.task]; assert not bad, f"MISPARSE: {bad}"; print(f"{len(t)} tasks, none collapsed")'
```

Verification for the phase as a whole lives in R5: the fixture-repo integration test is the
proof, the transcript audit is the audit trail, and `aidw doctor`'s capability probe is the
early warning.

---

## Epic R1: Freeze Pi's resource discovery in the argv

- [ ] **R1.1. Add the resource-denial flags to `build_argv`** (Design 5.1, Design 5.2)
  `aidw/agents.py:23` (`build_argv`) gains unconditional `--no-skills`, `--no-extensions`
  and `--no-prompt-templates`, and passes `--no-mcp` unless an agent declares MCP (R3.1 owns
  the MCP branch). Emit them in a fixed position, before the explicit declarations they
  bound, so `meta.json`'s `argv` diff is stable run to run. Explicit `--skill`/`--extension`
  /`--prompt-template` paths still load with these flags — that is the whole mechanism, and
  the reason the flags can be unconditional.
  - Deliverable: `build_argv` emits the three denial flags for every agent; module docstring
    explains the mechanism in one sentence.
  - Done when: a real smoke stage run through `uv run aidw prompt 01 R1 R1.1` produces a
    stage JSONL whose system prompt has **no** `<skills>` section at all (nothing declared),
    while its `argv` in `<stage>.meta.json` contains `--no-skills --no-extensions
    --no-prompt-templates`.

- [ ] **R1.2. Replace `--approve` with `--no-approve`** (Design 5.2, Design 5.5)
  `aidw/agents.py:38` hardcodes `--approve`, which grants the target repo trust for the run:
  its `.pi/settings.json`, `.pi/{skills,extensions,prompts,themes}`, `.pi/mcp.json`,
  `.pi/SYSTEM.md` and `.pi/APPEND_SYSTEM.md` all load. Switch to `--no-approve` (`-na`).
  `--no-approve` does **not** disable context files — AGENTS.md/CLAUDE.md load regardless of
  trust — so do not add `--no-context-files`, and leave the `no_context_files` default
  (`aidw/config.py:315`, `false`) as it is.
  - Deliverable: argv carries `--no-approve`; a comment states why (system-prompt files have
    no denial flag) and why context files are unaffected.
  - Done when: a stage rendered in a fixture repo containing `.pi/APPEND_SYSTEM.md` and
    `.pi/settings.json` shows neither in its system prompt, while the fixture's `AGENTS.md`
    is present.

- [ ] **R1.3. Pin the argv contract in tests** (Design 15)
  Rewrite/extend `tests/test_agents.py`: assert every denial flag is present for every agent,
  assert `--mcp-config` never appears, assert each `--skill`/`--extension`/`--prompt-template`
  matches its config entry exactly (no discovery-derived extras), and assert flag ordering.
  Replace `test_standard_flags_present`'s `"--approve" in argv` with its inverse.
  - Deliverable: unit tests that fail if a future edit drops a denial flag or reintroduces
    `--approve`.
  - Done when: deleting any one denial flag from `build_argv` fails at least one test, and
    `uv run pytest tests/test_agents.py` is green.

- [ ] **R1.4. Add a Pi capability probe to `aidw doctor`** (Design 12, Design 15)
  Mirror `_check_gh_version`'s help-scraping pattern (`aidw/doctor.py:155-203`,
  `_GH_CAPABILITY_PROBES`): probe `pi --help` for `--no-skills`, `--no-extensions`,
  `--no-prompt-templates`, `--no-approve`, `--no-mcp`, `--exclude-tools` and `-e`, and FAIL
  naming the missing capability. A Pi upgrade that renames a flag must fail preflight, not
  silently re-enable discovery mid-workflow. Record the minimum verified Pi version beside
  the existing `_check_pi`.
  - Deliverable: a `pi flags` check in `aidw/doctor.py` plus a test using captured help text
    (both a good and a flag-missing fixture).
  - Done when: `uv run aidw doctor` reports the probe, and a stubbed help output lacking
    `--no-skills` produces FAIL with the flag named.

- [ ] **R1.5. Pin session storage per run (decision D3)** (Design 5.3, Design 9.1)
  Pass `--session-dir <run dir>` so sessions land with the run's other artifacts. A project
  `.pi/settings.json`'s `sessionDir` is read *before* trust is resolved, so session location
  is the one project-controlled knob `--no-approve` does not close. Safe because
  `state.session_id` (`aidw/state.py:247`) derives ids from the run id, so no workflow
  resumes a session across AIDW invocations — verify that claim against every workflow before
  landing.
  - Deliverable: `--session-dir` in argv plus a test; if any workflow does resume across
    invocations, stop and record why instead.
  - Done when: two runs of one task keep separate sessions under their own run dirs, and
    `session: shared` still works within a run.

## Epic R2: The agent config becomes the only declaration site

- [ ] **R2.1. Make `skills:` live** (Design 5.1)
  `skills` exists on `AgentConfig` (`aidw/config.py:89`) and is already resolved against the
  toolkit root by `_load_path_list` (`aidw/config.py:171`), but no config sets it and nothing
  validates it. Accept a skill directory or a `SKILL.md` file; error when a directory has no
  `SKILL.md` or its frontmatter has no `description` (Pi drops those silently, so AIDW must
  not). Render as repeated `--skill`.
  - Deliverable: resolution + validation + argv rendering, documented in the §5.1 schema.
  - Done when: a config declaring `skills: [skills/archify]` yields exactly one `--skill`
    argv pair, an agent with a description-less skill fails `aidw agents validate --strict`,
    and a stage for that agent advertises only the declared skill.

- [ ] **R2.2. Make `extensions:` live, including `builtin:` entries** (Design 5.1)
  Same shape as R2.1, with one addition: entries of the form `builtin:<name>` are passed
  through verbatim and validated against the real built-in extension names (`mcp`,
  `codemode`, `tool-search`, `llama.cpp`). They must bypass path resolution and existence
  checks, which today would hard-error "entry not found". Note in the docs that
  `--no-extensions` disables built-in extensions too, so naming one is the only way to get it.
  - Deliverable: `builtin:` handling in `config.py` + argv rendering + schema/doc update.
  - Done when: `extensions: [builtin:codemode]` renders `--extension builtin:codemode` and
    passes validation, `builtin:nope` fails with a named error, and a nonexistent path still
    fails as before.

- [ ] **R2.3. Tighten tool and path validation** (Design 5.2)
  Three rules, all in `config.py` (`check_read_only` is at `:370`, tool validation at
  `:251-263`):
  1. a tool name that is neither a built-in nor plausibly provided by a declared extension
     or MCP server becomes an **error** (it is a warning today) — with discovery off, an
     unprovided name is certainly a bug;
  2. any `mcp__<server>__*` entry must match a server in the declared MCP config, and an
     agent that declares an MCP config must name its MCP tools so `--tools` filters them;
  3. a declared skill/extension path that resolves inside the target repo but outside the
     toolkit root is an **error** (explicit project-local resource paths plus `--no-approve`
     are not something to rely on).
  Also add the read-only sibling check: a strictly read-only reviewer (`READ_ONLY_AGENTS`)
  must not be reachable by `direct`-exposure MCP tools.
  - Deliverable: validation rules + tests, each with a failing and a passing case.
  - Done when: `aidw agents validate --strict` fails on a fabricated config for each rule,
    and the real configs still pass.

- [ ] **R2.4. Surface declared resources in the CLI** (Design 14)
  `aidw agents list` (`aidw/cli.py:459`) and `aidw agents show` (`:473`) print tools, session
  and timeout but not skills/extensions/MCP. Add them. Also add `aidw agents resources <id>`:
  print the exact argv that would be passed (without running Pi) plus the resources it
  declares, so an operator can answer "what will this stage inherit?" before spending money.
  Reuse the workflow `--dry-run` convention.
  - Deliverable: CLI output + a `resources` subcommand (or `show --argv`) with tests.
  - Done when: `uv run aidw agents resources implementer` prints an argv containing every
    denial flag and every declared resource, and its output is asserted in a test.

- [ ] **R2.5. Constrain the target-repo config contract** (Design 12)
  `docs/target-repo-config.md` (placeholder, E3.6) and the schema to arrive in E3.1 describe
  `<target>/aidw/config.yaml`. Ensure that contract can never declare resources: no `skills`,
  `extensions`, `tools`, `mcp`, or prompt-template fields — it configures paths, branch
  naming and prompt *overrides* only. Add an explicit schema/validation rejection and a doc
  sentence saying so.
  - Deliverable: schema + validation + one paragraph in `docs/target-repo-config.md`.
  - Done when: a target config containing a resource field is rejected with a message naming
    the field and pointing at `agent-configs/`.

## Epic R3: MCP

- [ ] **R3.1. Remove the broken `--mcp-config` path and default to `--no-mcp`** (Design 5.2, Design 7.4)
  `aidw/agents.py:73` passes `--mcp-config`, which is **not a Pi option**
  (`pi --mcp-config /tmp/nope.json -p hi` → `Error: Unknown option: --mcp-config`), and
  `design.md:420-428` documents it as the AWS MCP mechanism. No shipped agent sets the field,
  so nothing observable changes. Two coherent end states: delete `mcp_config` and always
  pass `--no-mcp` (option A), or keep the field and make it real in R3.3 (option B). Decide
  in R3.2, but land the deletion of the dead flag path either way. Independently, add
  `--exclude-tools 'mcp__*'` whenever MCP is not declared: `--tools` only filters MCP tools
  when an entry starts with `mcp__`, so a `direct`-exposure server would otherwise be
  declared to a read-only reviewer.
  - Deliverable: no `--mcp-config` anywhere; `--no-mcp` (or the R3.3 argv) plus
    `--exclude-tools` when MCP is absent; `design.md` claim corrected in R6.1.
  - Done when: `rg "mcp-config" aidw/ design.md docs/` returns only the corrected docs, and a
    fabricated agent config with a `direct` MCP server cannot reach the model.

- [ ] **R3.2. Record the MCP mechanism decision** (Design 17)
  Add a resolved-decision row to `design.md` §17 choosing option A (no MCP), B (bundled
  registrar extension calling `pi.registerMcpServer()`), or C (hermetic
  `PI_CODING_AGENT_DIR`) — with the reasoning from `EXPLICIT-RESOURCES.md` §6, including why
  C was rejected (must mirror `auth.json`, custom `models.json` ids, npm packages; drifts per
  Pi release). Note the trigger for revisiting: the first agent that genuinely needs the AWS
  MCP server.
  - Deliverable: a `design.md` §17 row plus a matching note in `EXPLICIT-RESOURCES.md` §10 D1
    (drop it when the doc's status flips in R6.3).
  - Done when: the decision names the option, the trigger, and the rejected alternatives in
    one paragraph each.

- [ ] **R3.3. (Only if R3.2 chooses B) Implement the registrar extension** (Design 5.2)
  `extensions/aidw-mcp.ts` in the toolkit: read the declared config path from `AIDW_MCP_CONFIG`
  (set via `build_env`), parse Pi's own `mcpServers` shape, and call `pi.registerMcpServer()`
  per entry. argv then adds `--extension builtin:mcp --extension <toolkit>/extensions/aidw-mcp.ts`
  (the built-in MCP runtime is itself an extension, so `--no-extensions` removes it too).
  Verify it works under `-p --mode json`, that `${VAR}` interpolation still resolves from the
  agent's `env:`, and that `--exclude-tools 'mcp__*'` is dropped or narrowed accordingly.
  - Deliverable: the extension, argv wiring, and a test against a trivial stdio MCP server in
    `fixtures/`.
  - Done when: a stage with a declared MCP config lists the server's `direct` tools exactly as
    `tools:` names them, and removing the config removes them with no residue.

- [ ] **R3.4. Fix the doctor's MCP check**
  `aidw/doctor.py:217` (`_check_mcp`) looks for `<target>/.mcp.json`, which is a Claude-style
  file Pi never reads (Pi reads `~/.pi/agent/mcp.json` and the trust-gated `.pi/mcp.json`).
  Replace it with a check that reports the *effective* MCP posture for the toolkit's agents:
  none by default, or the declared config and its sources when an agent declares one.
  - Deliverable: a corrected check plus updated test in `tests/test_doctor.py`.
  - Done when: `uv run aidw doctor` reports "mcp: none declared" by default and does not
    mention `.mcp.json`.

## Epic R4: Toolkit resource layout and vendoring

- [ ] **R4.1. Create the toolkit resource directories** (Design 3, Design 12)
  Add `skills/` and `extensions/` to the toolkit layout beside `prompts/`, extend
  `ToolkitPaths` (`skills_dir`, `extensions_dir`) and the layout table in `design.md` §3, and
  extend `_check_toolkit_root` (`aidw/doctor.py:254`) so a declared-but-missing skill or
  extension directory fails preflight instead of surfacing as a missing `--skill` path at
  stage time.
  - Deliverable: directories + `ToolkitPaths` members + doctor asset check.
  - Done when: a config declaring `skills/<name>` fails `aidw doctor` when the directory is
    absent and passes when it is present.

- [ ] **R4.2. Decide and vendor the Archify skill** (Design 7.4)
  `prompts/update-architecture.md` and the `update-*-diagram.md` family hardcode
  `/Users/phil/.pi/agent/skills/archify/{SKILL.md,bin/archify.mjs}` (24 references across
  `prompts/`), and `aidw/doctor.py:243` checks that machine-local path. Vendor the skill into
  `skills/archify/` so a declared resource is genuinely declared, and keep the copy honest
  with a documented update procedure (or record it as an accepted exception with the doctor
  check retained — decide in the task, do not leave it implicit).
  - Deliverable: `skills/archify/` in the toolkit (or a recorded exception), plus a README
    line describing how it is refreshed.
  - Done when: `rg "/Users/phil/.pi/agent/skills" prompts/ aidw/` returns nothing, or a
    decision paragraph explains each remaining occurrence.

- [ ] **R4.3. Declare the skill on the agent that owns the prompt** (Design 5.2)
  `/update-architecture` belongs to `implementer` (the shared-session authoring agent), so
  `implementer.yaml` gains `skills: [skills/archify]` — and only that agent does, unless
  `tester` or `recorder` genuinely needs it. Keeping the set minimal is the point: every
  declared skill is context and capability.
  - Deliverable: one agent config change, validated by R2.1's rules.
  - Done when: `uv run aidw agents resources implementer` shows exactly one declared skill,
    every other agent shows none, and a diagram-changing `/update-architecture` stage can
    read the skill.

- [ ] **R4.4. Point prompts at the declared location** (Design 7.2, Design 7.4)
  Rewrite the prompt templates to resolve the skill from its declared location rather than a
  machine-local absolute path, and state in `prompts/update-architecture.md` that the skill
  arrives via the agent config (so a missing skill reads as a config error, not a mystery).
  Keep the prompts renderable by the existing renderer and free of machine-specific paths.
  - Deliverable: prompt-template edits across the `update-*-diagram*` family.
  - Done when: `uv run aidw prompts check` is clean and the family contains no
    `/Users/phil` paths.

## Epic R5: Proof

- [ ] **R5.1. Fixture target repo and the integration test** (Design 15)
  `fixtures/target-repo/` currently holds only `.gitkeep`. Give it a sentinel `AGENTS.md`, a
  stray `.pi/skills/<name>/SKILL.md`, a stray `.pi/APPEND_SYSTEM.md`, and a
  `.pi/settings.json` that adds a skill and lists an extension. The integration test renders a
  stage (or drives argv through a fake `pi`) and asserts: sentinel `AGENTS.md` **present**,
  the agent's own `agents_md` **present**, and every stray **absent**.
  - Deliverable: fixture files + `tests/test_explicit_resources.py`.
  - Done when: the test fails if any denial flag is removed from `build_argv`, and passes on
    the real argv.

- [ ] **R5.2. Transcript audit** (Design 9.2, Design 15)
  Parse a real stage JSONL (as the investigation that motivated this phase did) and assert
  the system prompt's `<skills>` section contains **exactly** the declared skill names, and
  that the section is absent when nothing is declared. Ship the parser as a small helper so
  an operator can run the same audit on any run directory after the fact.
  - Deliverable: audit helper + test over `runs/`-style fixtures.
  - Done when: `uv run python -m aidw.audit <run-dir>` (name TBD) prints the advertised
    skills and tools per stage, and the test asserts the exact set for a fixture run.

- [ ] **R5.3. Record the declared resource set, and the context assembly order** (Design 9.2)
  `write_meta` (`aidw/pi.py`) already records `argv`; add the resolved declared resources
  (skills, extensions, MCP, context-file posture) to stage meta and to `state.json`/the run
  report so "what did this stage inherit?" is answerable from the run directory alone. In the
  same change, record empirically where the target `AGENTS.md` lands relative to AIDW's
  appended `agents_md` in the system prompt, and document the precedence that actually
  happens (decision D6).
  - Deliverable: meta/state/report fields + a short note in `EXPLICIT-RESOURCES.md` §10 and
    `design.md` §9.2.
  - Done when: a completed run's `state.json` and report show the declared resource set, and
    the observed assembly order is written down with the transcript path as evidence.

## Epic R6: Documentation and close-out

- [ ] **R6.1. Correct `design.md`**
  §5.1 schema (skill/extension/MCP semantics and the `builtin:` form), §5.2 (`--tools` is a
  strict allowlist over built-in and declared tools; MCP needs `mcp__` patterns to be
  filtered; denial flags are what make the allowlist authoritative), §5.5 (context files are
  the one automatic input; `agents_md` is appended), §7.4 (remove the `--mcp-config` and
  machine-local-archify claims), §14 (CLI reference if it lists argv).
  - Deliverable: the corrected sections, each stating the reason rather than only the rule.
  - Done when: no `design.md` statement contradicts `EXPLICIT-RESOURCES.md`, and
    `rg "mcp-config" design.md` finds only the corrected history note if any.

- [ ] **R6.2. README operator section**
  Add a short "What a stage inherits" section to `README.md`: the target `AGENTS.md` and the
  agent's `agents_md` are automatic; everything else must be declared in
  `agent-configs/<id>.yaml`; the target's `.pi/` tree is inert for AIDW stages (which also
  makes the existing "AIDT never reads `.pi/prompts/`" claim true at the Pi layer, not just
  the AIDT layer); and `aidw agents resources <id>` shows the effective argv. Coordinate with
  E9.4's README rewrite.
  - Deliverable: README section, linked from `EXPLICIT-RESOURCES.md`.
  - Done when: a reader with no context can say what a stage will and will not inherit, and
    how to check it.

- [ ] **R6.3. Flip the status banner**
  When every task in phase 01 is done, change `EXPLICIT-RESOURCES.md`'s banner from "NOT
  IMPLEMENTED" to implemented (naming the phase-10 PRs and the Pi version verified in R1.4),
  drop the resolved rows from its §10 decisions table, and add the pointer from `design.md`
  §5. Also delete the roadmap's "Gate: do not start before the migration completes" section
  if it is stale by then.
  - Deliverable: doc status changes + links.
  - Done when: no document in the repo still calls this work un-implemented.

- [ ] **R6.4. Regression watch** (Design 18)
  Record the minimum verified Pi version and the required flags in one place (doctor output,
  `design.md` §18 risks, README prerequisites). Add the transcript audit (R5.2) to the
  post-upgrade checklist so a Pi release that changes discovery semantics is caught by
  inspection and not by a leaked skill section in a later run.
  - Deliverable: risk/checklist entries.
  - Done when: `design.md` §18 names the failure mode ("a Pi upgrade silently re-enables
    discovery") and the check that detects it.

---

## Definition of done for phase 01

1. `uv run aidw doctor` fails preflight if the installed Pi lacks any denial flag, and
   reports the declared resource posture per agent.
2. `uv run aidw agents resources <id>` prints an argv in which every resource is declared and
   every denial flag is present; `--approve` and `--mcp-config` appear nowhere.
3. The fixture-repo integration test proves: target `AGENTS.md` in, agent `agents_md` in,
   user-level and target-level skills/extensions/system-prompt files out.
4. A real stage transcript advertises exactly the declared skills — and none at all when the
   config declares none.
5. `design.md`, `README.md` and `EXPLICIT-RESOURCES.md` agree with the implementation, and
   `EXPLICIT-RESOURCES.md`'s banner is no longer "NOT IMPLEMENTED".
