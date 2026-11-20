# Build Results — C1.1: Stop appending the target `AGENTS.md` to rendered prompts

**Branch:** `05-C1.1`
**Date:** 2026-11-20
**Spec:** `design.md` §7.3 (prompt rendering, decision D2), §5.5 (system prompt and context files), §17 (resolved decisions); roadmap entry C1.1 in `docs/tasks/05 - Pipeline efficiency.md`; `docs/task-prompts/05-C1.1-prompt.md`; `aidw/conventions.md` (traceability artefacts)
**Pull request:** not yet opened — the /pr stage records it here once the PR exists

## Summary

**Purpose:** Stop the prompt renderer from appending the target repo's root `AGENTS.md` to rendered prompts, because Pi already delivers that file as project context, while keeping the `aidw/conventions.md` append that Pi does not provide.

| Decision | Why it matters |
|----------|---------------|
| The injection appends only `aidw/conventions.md` by default; the read channel (`read_conventions_sources` / `CONVENTIONS_SOURCES`) keeps both sources in D16 order | The duplicate was the renderer's copy of a file the agent already has (§5.5); the read channel must stay because `aidw/workflows/prompt.py:_gate_block` takes gate commands from the root `AGENTS.md`'s `## Gates` section and C1.2/C1.3 build on it. |
| The opt-in lever is the frontmatter marker `append_agents_md: true` on the **resolved** prompt file, read by the new pure peek `aidw.prompts.appends_target_agents_md` | A repo whose agents set `no_context_files: true` (§5.5) would otherwise lose `AGENTS.md` entirely. Keying on the resolved path means a repo shadow or an explicitly declared prompt is read by its own file, never the toolkit default a stage id would name. |
| Only a value `yaml.safe_load` parses as the boolean `True` restores the append; every other case drops it with no raise | Absent, `false`, a quoted `"true"`, a non-boolean scalar, a nested key, malformed YAML, a frontmatter-less prompt and a missing/unreadable/non-UTF-8 file all mean "dropped". A marker typo must never fail a stage, and guessing an opt-in would re-introduce the duplication this task removes. |
| `render_repo_conventions` gains the additive keyword `include_agents_md: bool = False`; `inject_repo_conventions` keeps its three-argument signature | The flag is the single way to restore the pre-C1.1 block, and keeping the signature avoids re-baselining the five test modules that call it inside their `--dry-run` render seams. |
| No target-repo config key, `docs/schema/` node or `docs/target-repo-config.md` field is added | The config-key alternative was explicitly out of scope; the marker is prompt-fixed, so no config drift check moves. |

**Where it fits in the roadmap:** Phase 05 ("Pipeline efficiency"), epic C1 ("Prompt context economy"), task C1.1. It follows S1.2's path-scoped `I4` gating (decision `Z12`) in the same phase and is recorded as §17 row `Z15`, the next free id after `Z14` — not the roadmap's stale "Z12", which is S1.2's row and may not be reused or renumbered. C1.2 (resolve gate commands from the target's actual heading) and C1.3 (inline resolved gate commands into the stage prompts) are the next tasks in the epic and depend on the read channel this task deliberately left untouched.

**Scope:** `aidw/prompts.py` (the narrowed injection, the new pure peek and the marker constant), `aidw/runner.py` (comment-only update to the injection seam's rationale), `design.md` (§7.3 step 4 and the new `Z15` row in §17), `docs/target-repo-config.md` (corrects the related-documents bullet for the two conventions sources), and the two contract test modules `tests/test_conventions_injection.py` and `tests/test_design_doc.py`. It deliberately stops short of touching `_GATES_HEADING`/`_gates_section` and the five prompts' gate prose (C1.2/C1.3), changing `design.md` §5.5, and touching `aidw/config.py`, `docs/target-repo-config.md`'s config contract, or `docs/schema/`.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/implementation-results/05-C1.1/build-results.md` | Created | This document: the recorded, real outcomes of the whole-repo gate for the change. |
| `docs/task-prompts/05-C1.1-prompt.md` | Created | The task prompt: requirements, prompt-fixed decisions, tests, deliverables and explicit non-goals. |
| `aidw/prompts.py` | Modified | Narrows the injection to `aidw/conventions.md`, adds `AGENTS_MD_SOURCE`, `AGENTS_MD_MARKER` and the pure `appends_target_agents_md` peek, and adds the `include_agents_md` keyword to `render_repo_conventions`; `read_conventions_sources`/`CONVENTIONS_SOURCES` keep both sources. |
| `aidw/runner.py` | Modified | Comment-only: updates the injection seam's rationale to say the appended block is `aidw/conventions.md` only and names the marker opt-in (design §17 `Z15`). |
| `design.md` | Modified | Rewrites §7.3 step 4 (drop `AGENTS.md`, keep `aidw/conventions.md`, marker restores the append, read channel unchanged) and records §17 row `Z15`. |
| `docs/target-repo-config.md` | Modified | Corrects the related-documents bullet: `AGENTS.md` is Pi's project context and the gate-block read source, not an appended block. |
| `tests/test_conventions_injection.py` | Modified | Re-baselined from "`AGENTS.md` is injected" to "`conventions.md` is injected, `AGENTS.md` absent by default"; adds the marker cases (restore/false/quoted/uppercase/nested/malformed/frontmatter-less/missing/non-UTF-8), the resolved-prompt keying cases and a third property sweep. |
| `tests/test_design_doc.py` | Modified | Pins the updated §7.3 step 4 and exactly one C1.1 decision row, matched by task id plus wording and never by `Z` number, while asserting no §17 id is reused. |

---

## Verification Results

Commands are this repo's own, taken from its root `AGENTS.md` ("Gates — run exactly these, and only these"). AGENTS.md states that `pytest` is the only verification (no linter, formatter or type-checker is configured; design §15), so the lint row is unverified. Every gate ran through `aidw gate run <key>` with the workflow's declared scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.62ms`) |
| Lint | — | **unverified** — the repo configures no linter (AGENTS.md: "`pytest` is the only verification"; design §15) |
| Build | `uv build --out-dir <mktemp dir>` (gate `build`) | ✅ Pass — built `aidt-1.5.0.tar.gz` and `aidt-1.5.0-py3-none-any.whl` (run here) |
| Test | `uv run --frozen pytest` (gate `suite`) | ✅ Pass (`2348 passed in 48.71s`, run here) |
| Doctor | `uv run --frozen aidw doctor` (gate `doctor`) | ✅ Pass (`22 checks: 0 failed, 2 warning(s)` — warnings are the dirty working tree and the missing `.mcp.json`) |
| Agents validate | `uv run --frozen aidw agents validate --strict` (gate `agents`) | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` (gate `prompts`) | ✅ Pass (toolkit defaults and resolved repo prompts: `0 error(s), 0 warning(s)`) |
| Whitespace | `git diff --check` | ✅ Pass (exit 0, no output) |

Gate origins for the rows above (tree `2d1f11899317`, scope excludes `docs/architecture, docs/implementation-results, docs/task-prompts, docs/tasks`):

- `build` — passed at `2026-11-20T05:39:28Z`, stage `record-implementation-results` (`Successfully built …/aidt-1.5.0-py3-none-any.whl`).
- `suite` — passed at `2026-11-20T05:40:20Z`, stage `record-implementation-results` (`2348 passed in 48.71s`). This is the single full-suite invocation for this document; no subset was re-run and no second suite was bought.
- `doctor` — passed at `2026-11-20T05:40:23Z`, stage `record-implementation-results` (`22 checks: 0 failed, 2 warning(s)`).
- `prompts` — passed at `2026-11-20T05:40:26Z`, stage `record-implementation-results` (resolved repo prompts: `0 error(s), 0 warning(s)`).
- `agents` — passed at `2026-11-20T05:40:26Z`, stage `record-implementation-results` (`11 agent config(s): 0 error(s), 0 warning(s)`).

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 2348 | ✅ Pass (`2348 passed in 48.71s`, gate `suite`, tree `2d1f11899317`, stage `record-implementation-results`, `2026-11-20T05:40:20Z`) |

### Task-specific verification gates

The task prompt names no separate command beyond the modules it re-baselines. The focused rows below are cited from this same run's `test` stage; neither was re-run for this document.

| Gate | Status |
|------|--------|
| `uv run --frozen pytest -n0 tests/test_conventions_injection.py tests/test_design_doc.py` (gate `smoke`) | ✅ `145 passed in 8.13s` — tree `a603ce4daaba`, stage `test`, `2026-11-20T05:35:56Z` |
| `uv run --frozen pytest -n0 tests/test_prompt_workflow.py -k 'e73_gate_list_includes_conventions_md_commands_after_agents_md or e73_conventions_md_alone_supplies_the_gate_list or e73_non_utf8_conventions_source_is_ignored_by_the_gate_block'` (gate `smoke`) | ✅ `3 passed, 236 deselected in 0.73s` — tree `a603ce4daaba`, stage `test`, `2026-11-20T05:36:00Z` |
| Evidence-bundle gate list still reads both files | ✅ Covered by the three `e73_*` cases above: `_gate_block` still takes `## Gates` from the root `AGENTS.md` and from `aidw/conventions.md` |
| `read_conventions_sources` / `CONVENTIONS_SOURCES` unchanged (both sources, D16 order) | ✅ Pinned in `tests/test_conventions_injection.py` (green in the `smoke` and `suite` gates above) |
| Marker absent/`false` → `AGENTS.md` not injected; marker `true` → both injected | ✅ Pinned in `tests/test_conventions_injection.py` (same gates) |
| §7.3 step 4 and exactly one §17 C1.1 row at the next free id, no `Z12` collision | ✅ Pinned in `tests/test_design_doc.py` (same gates) |
| Whole-repo `pytest` gate | ✅ `suite` above, `2348 passed` |

---

## Deviations observed during recording

- **Two files outside the task prompt's deliverables list are modified** — `aidw/runner.py` carries a comment-only update to the injection seam's rationale (no behaviour change; the rendered text is produced entirely by `aidw/prompts.py`), and `docs/target-repo-config.md`'s related-documents bullet is corrected to say `AGENTS.md` is Pi's project context and the `_gate_block` read source rather than an appended block. No config key, `paths.*` entry or schema surface was added by either edit. Recorded here so a reviewer sees the full diff relative to `main`.
- **The roadmap's "recorded as Z12" is stale and was not followed** — `Z12` is S1.2's `I4` row, and `aidw/conventions.md` forbids reusing or renumbering an id, so the new decision took the next free id `Z15` and `tests/test_design_doc.py` matches the row by task id plus wording, never by `Z` number. The roadmap entry itself was left untouched, as the task prompt requires.
- **The focused test rows were not re-run for this document** — they are cited from the run's own `test`-stage `smoke` gate outcomes against tree `a603ce4daaba`, per the single-invocation rule; the full `suite` gate was the one full run recorded here (tree `2d1f11899317`).

---

## Non-Goals (NOT implemented)

- ❌ C1.2 (resolve gate commands from the target's actual heading and diagnose misses) and C1.3 (inline resolved gate commands into the stage prompts) — `_GATES_HEADING`/`_gates_section` and the five prompts' gate prose are untouched (`docs/task-prompts/05-C1.1-prompt.md`, "Explicit non-goals").
- ❌ No change to `design.md` §5.5 — it is the rationale for the drop, not a deliverable (same source).
- ❌ No change to `aidw/config.py`, `docs/target-repo-config.md`'s config contract, or `docs/schema/` — the target-repo config-key alternative for the lever is out of scope (same source).
- ❌ The roadmap entry is not edited; its stale "Z12" wording stays as written and the correction lives in the task prompt and §17 (same source).
- ❌ No new checker, status vocabulary, `REQUIRED_PROMPTS` entry or CI gate (same source).
- ❌ No commit, push or pull request — the `/pr` stage owns delivery, and this document therefore names no PR number yet.
