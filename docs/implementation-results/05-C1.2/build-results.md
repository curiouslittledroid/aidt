# Build Results — C1.2: Resolve gate commands from the target's actual gates heading, and diagnose misses

**Branch:** `05-C1.2`
**Date:** 2026-11-20
**Spec:** `design.md` §7.3 (prompt rendering, decision D2 — step 4, the gate-block read channel), §8.1 (`aidw prompt`, the P2 evidence bundle's gate-commands element), §17 (resolved decisions, row Z16); roadmap entry C1.2 in `docs/tasks/05 - Pipeline efficiency.md`; `docs/task-prompts/05-C1.2-prompt.md`; `docs/target-repo-config.md` (config contract); `aidw/conventions.md` (traceability artefacts)
**Pull request:** not yet opened — the /pr stage records it here once the PR exists

## Summary

**Purpose:** Make the prompt workflow's evidence bundle read a target repo's gate commands from the headings it actually uses — `## Gates`, `## Gate commands`, or a config-declared heading — instead of recognising one literal heading and silently degrading to `unavailable — could not be read`, and have `aidw doctor` diagnose a gates-like heading nothing recognises.

| Decision | Why it matters |
|----------|---------------|
| The recognised heading set is one shared constant, `aidw.prompts.GATES_HEADINGS = ("## Gates", "## Gate commands")`, with the pure helpers `is_gates_like_heading` and `is_recognised_gates_heading` defined once there; `aidw/workflows/prompt.py` imports it as `_GATES_HEADING` and `aidw/doctor.py` imports the same objects | The bundle reader and the diagnosis cannot drift on what counts as a gate heading, and no second literal set of recognised headings exists in either reader (requirement 4). |
| Recognition is a `startswith` prefix test, never `==`, in both the bundle reader and the doctor's recognised test | A suffixed canonical heading — the toolkit's own `## Gates — run exactly these, and only these` — keeps matching, and the existing `AGENTS_EVIDENCE_FIXTURE` shape stays valid instead of starting to WARN. |
| The config lever is a new optional **top-level** `gates_heading` whose value is the **full heading line including its `## ` prefix** (`gates_heading: "## Verification gates"`), matched verbatim | A bare title would require the code to prefix it, hiding the format; a verbatim full line keeps the matcher a single `startswith`. An empty value is one loader ERROR naming the field with the value dropped, because `line.startswith("")` would match every line (`model`/`paths.roadmap_glob` precedent). |
| The "gates-like heading" heuristic (a `## ` heading containing "gate", case-insensitive) is deliberately broader than the recognised set, and case is significant | The heuristic's whole job is to catch what is *not* recognised, so `## Gate Commands` (capital C) and `## Verification gates` are both reported while the spec's two literal strings stay fixed. |
| The doctor check is `WARN`, never `FAIL`, and never touches the exit code | A non-standard heading still works — the bundle degrades to `unavailable`, a normal state (L2.4 requirement 4) — so this is advice with both fixes named (rename, or declare `gates_heading`), not a broken prerequisite. |
| Both readers load the config from the **target** root (`<repo.root>/aidw/config.yaml`), and the doctor loads it *before* deciding a heading is unrecognised | AGENTS.md's "Two roots": reading the toolkit's own config would pass every self-hosted test and break only after extraction. A repo that declares its heading is never warned. |

**Where it fits in the roadmap:** Phase 05 ("Pipeline efficiency"), epic C1 ("Prompt context economy"), task C1.2. It builds directly on C1.1 (§17 row Z15), which deliberately left the read channel (`read_conventions_sources`/`CONVENTIONS_SOURCES`) in D16 order because this task reads gate commands through it; it is recorded as §17 row `Z16`, the next free id after `Z15`, and is not a reuse or renumbering of an existing row. C1.3 ("Inline the resolved gate commands into the stage prompts") is the next task in the epic and consumes the resolved source this task produces.

**Scope:** The gates-heading contract and its one config key: `aidw/prompts.py` (shared constant + two pure helpers, comment updates), `aidw/workflows/prompt.py` (`_gates_section` extra heading, `_gate_block` target-relative config load), `aidw/doctor.py` (`_check_gates_heading`, wired into `collect_checks`), `aidw/target_config.py` (`gates_heading` key), the drift-checked doc and JSON schema, `design.md` §§7.3, 8.1 and the new §17 row, plus the five contract-test modules. It deliberately stops short of C1.3 (inlining the resolved commands into the stage prompts), of C1.1's injection split (`render_repo_conventions`/`appends_target_agents_md` and the `AGENTS.md` append/opt-in are untouched), and of any structured `gates:` config field (R14 rejected it — only the single heading pointer exists). The degrade contract is unchanged: no source, no recognised heading, an unrecognised gates-like heading, and non-UTF-8/unreadable sources all still yield `_EVIDENCE_UNAVAILABLE`, and the bundle never fails a run.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/05-C1.2-prompt.md` | Created | The task prompt (spec references, requirements, prompt-fixed decisions, non-goals). |
| `aidw/prompts.py` | Modified | Adds `GATES_HEADINGS` plus the pure `is_gates_like_heading`/`is_recognised_gates_heading` helpers; updates the `AGENTS_MD_SOURCE`/`CONVENTIONS_SOURCES`/`read_conventions_sources` comments that still said `## Gates`. |
| `aidw/workflows/prompt.py` | Modified | `_gates_section` takes an `extra_heading` and routes recognition through the shared predicate (stays pure); `_gate_block` loads `gates_heading` from `repo.root/aidw/config.yaml` and passes it in; the literal `_GATES_HEADING = "## Gates"` is replaced by an import of the shared tuple. |
| `aidw/doctor.py` | Modified | New `_check_gates_heading` (advisory `gates heading` WARN naming each unrecognised gates-like heading, its source file and both fixes), wired into `collect_checks`. |
| `aidw/target_config.py` | Modified | `gates_heading` in `TOP_LEVEL_KEYS`, a field on `TargetConfig`, parsed via `_read_str` with a non-empty ERROR guard, and round-tripped by `to_dict`. |
| `docs/target-repo-config.md` | Modified | Field-table row for `gates_heading` (type, default, effect with the `## `-prefixed example), the conventions bullet's gate-heading note, and the Full example. |
| `docs/schema/aidw-config.schema.json` | Modified | `gates_heading` property (`string`, `minLength: 1`) with a `## `-prefixed example and the ERROR-on-empty note. |
| `design.md` | Modified | §7.3 step 4 (two recognised headings, the declaration, one shared definition), §8.1 (the evidence-bundle gate element and the doctor diagnosis), and the new §17 row `Z16` with the prompt-fixed decisions (a)–(c). |
| `tests/test_prompt_workflow.py` | Modified | `## Gate commands` fixture supplying the bundle and the block, a configured full-`## `-prefixed heading recognised (bare title not), a target-relative config load that a toolkit-root read would fail, the `## Gate Commands` degrade case, and a purity test for `_gates_section`. |
| `tests/test_doctor.py` | Modified | `gates heading` WARN for `## Gate Commands`/`## Verification gates`, silence for `## Gates`/`## Gate commands`/suffixed canonical/declared heading, OK for a config-less and source-less repo and an unreadable config, and the WARN never failing `run_doctor`. |
| `tests/test_target_config.py` | Modified | `gates_heading` parse + verbatim round-trip, default unset, wrong type naming the field, empty value as one ERROR with the value dropped, re-baselined `TOP_LEVEL_CONFIG_KEYS` and the schema-agreement case. |
| `tests/test_target_repo_config_doc.py` | Modified | Re-baselines `EXPECTED_DEFAULTS` with `gates_heading: unset` (drift check, not weakened). |
| `tests/test_design_doc.py` | Modified | Pins the §7.3/§8.1 wording and exactly one C1.2 §17 row (matched by task id + wording, never by `Z` number). |

---

## Verification Results

Every row below is a real observation from this recording run. The gate commands are the repo's
own (`AGENTS.md` "Gates — run exactly these, and only these"), recorded through
`aidw gate run <key> $SCOPE -- <command>` with the canonical four-directory scope
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`
(all four resolved from `aidw config show`, i.e. the four configured write-targets of this
workflow's stages). All five recorded outcomes are against tree `ca12234bcb33`, stage
`record-implementation-results`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass — `Checked 19 packages in 0.53ms`, exit 0 |
| Build | `uv build --out-dir <tmp>` (via `aidw gate run build`) | ✅ Pass — `aidt-1.5.0.tar.gz` and `aidt-1.5.0-py3-none-any.whl` built; gate `build` passed for tree `ca12234bcb33` at `2026-11-20T06:32:24Z` |
| Test | `uv run --frozen pytest` (via `aidw gate run suite`) | ✅ Pass — `2367 passed in 52.22s`; gate `suite` passed for tree `ca12234bcb33` at `2026-11-20T06:32:20Z` |
| Doctor | `uv run --frozen aidw doctor` (via `aidw gate run doctor`) | ✅ Pass — `23 checks: 0 failed, 2 warning(s)`; WARNs are the pre-existing `git branch 05-C1.2, dirty working tree` and `mcp config missing`; `gates heading` is `ok`; exit 0; gate `doctor` passed for tree `ca12234bcb33` at `2026-11-20T06:32:29Z` |
| Agents validate | `uv run --frozen aidw agents validate --strict` (via `aidw gate run agents`) | ✅ Pass — `11 agent config(s): 0 error(s), 0 warning(s)`; gate `agents` passed for tree `ca12234bcb33` at `2026-11-20T06:32:28Z` |
| Prompts check | `uv run --frozen aidw prompts check` (via `aidw gate run prompts`) | ✅ Pass — `resolved repo prompts: 0 error(s), 0 warning(s)`; gate `prompts` passed for tree `ca12234bcb33` at `2026-11-20T06:32:28Z` |
| Whitespace | `git diff --check` | ✅ Pass — no output, exit 0 |
| Lint | — | **unverified** — this repo configures no lint command (`AGENTS.md`: "no linter, formatter, or type-checker is configured — don't add one inside an unrelated task"; `aidw/conventions.md` adds no gates) |

### `uv run --frozen pytest` (full suite)

Every row is derived from the single `suite` gate invocation above; nothing was re-run.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`uv run --frozen pytest`) | 2367 | ✅ Pass (`2367 passed in 52.22s`) |
| C1.2 contracts (`tests/test_prompt_workflow.py`, `tests/test_doctor.py`, `tests/test_target_config.py`, `tests/test_target_repo_config_doc.py`, `tests/test_design_doc.py`) | included above | ✅ Pass — these modules are part of the 2367 and no test in the run failed |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `_gate_block` over a `## Gate commands` conventions fixture returns the commands, and the rendered evidence bundle carries them (not `unavailable`) | ✅ Pass (`test_c12_gate_commands_heading_supplies_the_bundle_gate_commands`, `test_c12_gate_commands_heading_alone_supplies_the_block` — inside the recorded suite) |
| A configured `gates_heading` is a full `## `-prefixed line: recognised verbatim, bare title not, and loaded from `repo.root` | ✅ Pass (`test_c12_configured_heading_is_a_full_prefixed_line_passed_in`, `test_c12_gate_block_loads_the_declared_heading_from_the_target_config`) |
| `## Gate Commands` (capital C) still degrades the bundle and `_gates_section` stays pure | ✅ Pass (`test_c12_unrecognised_gates_like_heading_still_degrades`, `test_c12_gates_section_is_pure`) |
| `aidw doctor` reports the `gates heading` WARN naming file+heading for `## Gate Commands`/`## Verification gates`, stays silent for `## Gates`/`## Gate commands`/suffixed canonical/declared, and the WARN never fails the doctor | ✅ Pass (`test_c12_*` in `tests/test_doctor.py`, plus the live `[  ok  ] gates heading` row in the doctor output above) |
| `gates_heading` accepted, documented and drift-checked (field table, JSON schema, schema-agreement case, `to_dict` round-trip, empty value ERROR) | ✅ Pass (`tests/test_target_config.py`, `tests/test_target_repo_config_doc.py`) |
| Design §§7.3, 8.1 and the new §17 row `Z16` pinned by task id | ✅ Pass (`tests/test_design_doc.py::test_c1_2_sections_and_decision_row_record_the_gate_heading_contract`) |

---

## Deviations observed during recording

- **No `lint` gate exists to record** — the record prompt's illustrative `lint`/`build`/`suite` triple
  maps onto this repo only as `build` and `suite`; `AGENTS.md` states no lint command exists and
  forbids adding one in an unrelated task. The row is therefore `unverified` with that reason rather
  than invented or borrowed from another stack.
- **Skip-level test counts were not re-run** — the focused C1.2 test modules were not invoked a second
  time to obtain per-module counts; they are reported as part of the single full-suite run, as the
  prompt requires.

---

## Non-Goals (NOT implemented)

- ❌ C1.3 "Inline the resolved gate commands into the stage prompts" — that consumes C1.2's resolved source; not started here (task prompt "Explicit non-goals").
- ❌ C1.1's injection split is untouched: only the **read** channel (`_gate_block`) changes; `render_repo_conventions`/`appends_target_agents_md` and the `AGENTS.md` append/opt-in are unchanged (task prompt "Explicit non-goals").
- ❌ No structured `gates:` config field (R14 rejected it) — only the single heading pointer `gates_heading` (task prompt "Explicit non-goals").
- ❌ No pull request opened, no commit or push — the `/pr` stage owns delivery (record prompt non-goals).
