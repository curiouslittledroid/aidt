# Build Results — G1.3: Resolve `Design N` citations against a repo-declared spec directory

**Branch:** `05-G1.3`
**Date:** 2026-11-22
**Spec:** `design.md` §§8.1, 11, 12.1, 17 (row Z22); `docs/roadmap-format.md` §8; `docs/target-repo-config.md` (`paths:` table, "Configured paths must exist", worked examples)
**Pull request:** not yet opened — the /pr stage records it here once the PR exists

## Summary

**Purpose:** Let the `Design N` citation channel resolve against an optional `paths.specs_dir` of
numbered spec documents (`Design <number> - <title>.md`, scanned flat), so a target whose specs are
one document per design number — Mythical Forge's layout — can pass `aidw prompt`'s G1.2 preflight
instead of being refused for a root `design.md` it never had.

| Decision | Why it matters |
|----------|---------------|
| `paths.specs_dir` is optional, **unset, not defaulted** (no `TOOLKIT_DEFAULTS` entry), mirroring `agent_configs_dir` | A repo whose specs are one root `design.md` is the valid case and must keep G1.2's channel byte-identically; seeding a repo-relative default would change every repo's citation contract (design §1/D15's "no second per-repo dialect"). |
| Deliberately **not** in `READ_PATHS` and not in `WRITE_TARGETS` | `validate_paths` must never fail a directory that is read only when a citation needs it; the diagnosis is an advisory `aidw doctor` `WARN`, never a `FAIL` and never an exit-code decision. |
| One filename predicate, `spec_document_number` (`^Design (\d+(?:\.\d+)?) - `), imported by the doctor | A doctor-local glob or second regex can disagree with the resolver in both directions; the diagnosis must see exactly what the preflight sees. |
| Numbers compare canonically through the existing `_canonical_number` | `Design 04` resolves `Design 4 - …`, while `Design 20` never matches `Design 20.1 - …` (parent vs sub-number), and one dotted-integer comparator serves both the filename and the heading rule. |
| One merged token scan (`_citation_tokens`) measures each citation's window up to the next token of **either** channel; each `(document, section)` pair is deduped | A `§` after a `Design N` that precedes an `<NAME>.md` token belongs to the `Design` citation, so two separate scans would misassign it; deduping on the pair (not the token) keeps a citation cited twice checked once while `§5.3` and `§5` stay distinct. |
| Per-**occurrence** claims, not per-unique-token claims | An entry may cite the same design number twice with different sections (`Design 11 §5.3; Design 11 §5`) or once bare and once with a section; the `(document, section)` pair is what is deduped, so every occurrence's window is enumerated while no pair is checked twice. |
| A `§5.3A` token is checked as `5.3`; `_SECTION_RE` is not extended to capture letters | A lettered sub-part is a deeper numbered heading in one spec and a plain list label in another, so no deterministic rule spans both; reporting a lettered-form gap would be a false refusal. |
| A bare specs-mode `Design N` is a document-level claim: exists and holds ≥1 non-blank, non-heading line (`_document_has_content`) | The document-level analogue of `_section_state`; "any text at all" would pass a headings-only spec that documents nothing. The `<NAME>.md` channel keeps its existence-only contract. |
| `specs_dir` is threaded into `_render_cited_specs`, `_render_evidence_bundle` and the preflight exactly as `roadmap_dir` is | The `P2` bundle and the preflight share one enumeration and therefore cannot disagree about the resolved path or the checked sections. |
| The exit-3 refusal appends a `paths.specs_dir` remedy line **only** when the cause is no `specs_dir` and no root `design.md` | A section gap inside a present document already names its own repair; a remedy line on every refusal would be noise. |

**Where it fits in the roadmap:** The final task of Epic G1 ("Prompt review depth") in
`docs/tasks/05 - Pipeline efficiency.md`. It follows G1.2 (the preflight it extends) and G1.1
(finding classification), and it is the last piece of Epic G1 — Epic B1 ("Batch fixes") is the next
roadmap work and is deliberately not started here. It supersedes Z19's document assumption only
when `paths.specs_dir` is declared; the unset path is unchanged.

**Scope:** The optional config key and its resolver, the rewritten citation-window enumeration in
`_cited_specs`, the document-mode branch in `_spec_feasibility_gaps`, the refusal remedy line, the
evidence-bundle rendering, the advisory doctor check, the JSON schema, three documents and six test
files. It deliberately stops short of a configurable filename template (rejected as a second
per-repo dialect), of any change to the `<NAME>.md` channel's bare-ref contract beyond the shared
window boundary, and of the one target-side change outside this branch (adding
`paths.specs_dir: docs/specs` to Mythical Forge's `aidw/config.yaml`).

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `aidw/target_config.py` | Modified | `PathsConfig.specs_dir` + `PATH_FIELDS` entry, unset by default and in neither `READ_PATHS` nor `WRITE_TARGETS`, with the third-class rationale in the module docstring. |
| `aidw/workflows/prompt.py` | Modified | The spec-document resolver (`_SPEC_DOCUMENT_RE`, `spec_document_number`, `_spec_document_matches`, `_display_path`), the merged citation-window enumeration (`_citation_tokens`, `_citation_window`, `_design_window`, `_specs_mode_citations`), per-occurrence claims, `_document_has_content`, the document-mode branch in `_spec_feasibility_gaps`, the remedy line in `_refuse_spec_gaps`, and `specs_dir` threaded into `_render_cited_specs`/`_render_evidence_bundle`/the preflight. |
| `aidw/doctor.py` | Modified | Advisory `specs dir` check: `WARN` (never `FAIL`) for a declared but missing / non-directory / document-less `specs_dir` and for none declared with no root `design.md`; imports `spec_document_number` rather than growing a second glob. |
| `docs/schema/aidw-config.schema.json` | Modified | `paths.specs_dir` string property with its "neither a read-path nor a write-target" description. |
| `docs/target-repo-config.md` | Modified | The `paths.specs_dir` row (default `unset`), the explicit third "neither" class in the read-path/write-target section, the not-seeded rationale, and the worked-example layout line. |
| `docs/roadmap-format.md` | Modified | §8.1 states where `N` resolves: document resolution, canonical numbers, the citation window, the letter suffix and the bare-citation rule. |
| `design.md` | Modified | §8.1 (specs-mode resolution, sections, letter suffix, remedy line), §12.1 (the third path class) and §17 row **Z22**. |
| `tests/test_prompt_workflow.py` | Modified | Specs-mode coverage added beside the untouched `READ_PATH_FILES`/gap pins: resolution, ambiguity, flat scan, unset byte-identity, window enumeration and dedupe, repeated-token windows, the bare-occurrence-beside-a-sectioned-one case, letter suffix, document-level bare citation, evidence-bundle rendering, both refusal-remedy cases. |
| `tests/test_doctor.py` | Modified | The four `WARN` cases and the `OK` cases, with the document-less case holding only non-conforming filenames (`notes.md`, `Design draft.md`). |
| `tests/test_target_config.py` | Modified | `specs_dir` round-trip, unset state, field/schema agreement. |
| `tests/test_target_repo_config_doc.py` | Modified | Re-baselined `EXPECTED_DEFAULTS["specs_dir"]="unset"`, the `paths.*` leaf lists and the Full example. |
| `tests/test_cli.py` | Modified | `config show`'s leaf and unset lists pick up `paths.specs_dir`. |
| `tests/test_roadmap_format.py` | Modified | §8.1 channel-description pin. |
| `tests/test_design_doc.py` | Modified | Z22 row pin (by task id, never by `Z` number) plus the §8.1 and §12.1 statement pins. |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 19 packages in 1ms` |
| Build | — (no build command) | ➖ not a repo gate: `AGENTS.md` declares no build command and CI runs only `uv sync --frozen`, `pytest` and `doctor` |
| Test | `uv run --frozen pytest` (via `aidw gate run suite` with the scope below) | ✅ **2558 passed in 55.88s** — cited from this run's recorded gate for tree `2efae543353d` |
| Doctor | `uv run --frozen aidw doctor` | ✅ exit 0 — `24 checks: 0 failed, 2 warning(s)` (warnings: dirty working tree on `05-G1.3`; missing `.mcp.json`); the new `specs dir` check reports ✅ ``paths.specs_dir` unset; `Design N` resolves against the root design.md` |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ exit 0 — `resolved repo prompts: 0 error(s), 0 warning(s)` |
| Whitespace | `git diff --check` | ✅ exit 0 — no output |

The suite row is cited, not re-run:
`reused: gate 'suite' passed for tree 2efae543353d at 2026-11-22T02:50:20Z by stage
'update-traceability' (2558 passed in 55.88s) [scope excludes: docs/architecture,
docs/implementation-results, docs/task-prompts, docs/tasks]` — the same key, command and scope this
stage asks for, against content that differs only inside that scope, so the recorded outcome is this
run's own observation of this tree. The doctor, agents-validate, prompts-check and whitespace rows
were run directly in this stage, and their exit codes were observed.

### `uv run --frozen pytest` (full suite)

Every row is taken from the single full-suite gate identified above; no subset was re-run.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2558 | ✅ Pass (`2558 passed` in 55.88s) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `aidw doctor`'s `specs dir` check is advisory only | ✅ `OK`/`WARN` only, exit code 0, 0 failed checks (observed in this run) |
| Config/docs drift pins (`test_target_config.py`, `test_target_repo_config_doc.py`, `test_cli.py`, `test_roadmap_format.py`, `test_design_doc.py`, `test_doctor.py`) | ✅ passed inside the same full-suite gate (tree `2efae543353d`) |
| G1.3 specs-mode prompt-workflow tests | ✅ passed inside the same full-suite gate — cited from this run's recorded `gate g13: passed (tree 2efae543353d, stage test, 2026-11-22T02:46:20Z, 2.34s, 25 passed, 734 deselected)` and, for the previously failing case alone, `gate smoke: passed (tree 2efae543353d, stage test, 2026-11-22T02:46:15Z, 1 passed, 292 deselected)` |
| Target-repo `paths.specs_dir` exercised against Mythical Forge | ❌ **unverified** — needs `paths.specs_dir: docs/specs` added to Mythical Forge's `aidw/config.yaml`, which is outside this branch; no target repo was touched by this stage |

---

## Deviations observed during recording

- **The tree advanced between the two record invocations, and the suite result changed with it.** The
  first recording of this stage ran the full suite against tree `e241ed5eba82` and observed
  `1 failed, 2556 passed`, the failure being
  `tests/test_prompt_workflow.py::test_g13_repeated_same_design_token_uses_each_token_window`. The
  current tree is `2efae543353d`, whose own recorded gates show that test passing on its own
  (`1 passed, 292 deselected`, stage `test`) and the full suite passing (`2558 passed`,
  stage `update-traceability`, 2026-11-22T02:50:20Z). This stage neither caused nor fixed that
  change: it modified no source, test or spec file, and the pass recorded above is the gate store's
  observation of the tree as it stands, not a re-run performed to overwrite the earlier failure.
- **No lint or build gate exists in this repo.** `AGENTS.md`'s "Gates — run exactly these, and only
  these" lists `uv sync --frozen`, `uv run --frozen pytest`, `uv run aidw doctor`, `uv run aidw agents
  validate --strict` and `uv run aidw prompts check`; `aidw/conventions.md` adds none, and the
  workflow's generic `lint`/`build` gate keys have no command to run, so those rows are marked
  not-applicable rather than invented.
- **The change set is uncommitted.** `main..HEAD` carries only the task-prompt commit; all
  implementation, test and document changes are working-tree modifications, so the tree identity
  `2efae543353d` was computed from the working tree relative to `main`.

---

## Non-Goals (NOT implemented)

- ❌ A configurable filename template for spec documents — rejected as a second per-repo dialect (Design 1 / D15)
- ❌ A stub root `design.md` in a target repo to paper over the mismatch (roadmap Notes forbid it)
- ❌ Any change to the `<NAME>.md` doc-ref channel's bare-ref contract, or to channel behaviour beyond the shared window enumerator
- ❌ Epic B1 ("Batch fixes") — Epic G1 ends at G1.3; the next roadmap work is not started here
- ❌ Any edit to `docs/tasks/*.md` (the roadmap checkbox is `update-roadmap`'s single edit)
- ❌ No commit, push or pull request opened by this stage (`/pr` owns delivery)
