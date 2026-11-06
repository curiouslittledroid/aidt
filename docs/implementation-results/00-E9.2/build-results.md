# Build Results — E9.2: Write the two contract docs

**Branch:** `00-E9.2`
**Date:** 2026-11-06
**Spec:** `docs/migration/EXTRACTION.md` §3.4 (target-repo config), §3.7 (roadmap model, D6/D15), §3.9 (persisted GitHub contracts, freeze semantics D5); `design.md` §11 (roadmap task selection), §12 (configuration, environment, secrets); `docs/tasks/00 - Extraction.md` — Epic E3 (E3.6), Epic E5 (E5.1, E5.3, E5.4), Epic E9 (E9.2)

## Summary

**Purpose:** Reconcile the two shipped contract docs — `docs/target-repo-config.md` (E3.6) and `docs/roadmap-format.md` (E5.1) — with the already-shipped toolkit, cross-link them from the README, and extend their drift tests so the reconciliation cannot silently revert.

| Decision | Why it matters |
|----------|---------------|
| `docs/roadmap-format.md` status table now marks E5.3 and E5.4 **done**, pointing at `aidw/roadmap.py:validate_tasks` and `tests/conftest.py:roadmap_example` | Both shipped; the "not done" rows were the only remaining claim that the parser had no validation pass. |
| §6 and §10 restate the shipped validation split: `parse_file`/`load_tasks` stay silent, while the separate pure `validate_tasks` pass reports exactly the three `RULE_*` tokens, surfaced by `aidw tasks --validate` as `{file}:{line}: {rule} — {message}` | The parser is still silent, so the old "No validation" framing was wrong in both directions; the doc now matches `aidw/roadmap.py` and `aidw/cli.py:tasks`. |
| §10 keeps its heading number and states the two traps precisely — duplicate id keyed on `(phase, task)`, and "outside an epic" meaning `epic_title is None` (never `epic`) | `aidw/roadmap.py` and `tests/test_roadmap_validate.py` cite "roadmap-format.md §10"; paraphrasing either trap would misdescribe `validate_tasks`. |
| `docs/target-repo-config.md` replaces both forward-looking duality notes with the shipped reality: `repo.base_branch`/`repo.branch_pattern` have two equal-valued homes (the `TOOLKIT_DEFAULTS` resolved leaves and `aidw.paths.TargetRepo`'s frozen dataclass defaults, pinned equal by `tests/test_target_config.py`), the workflows (`implement`/`fix`/`review`/`prompt`/`run`) read the dataclass defaults, and no production code reads the resolved `repo.*` leaves | The old "E4–E6 rewire … until then" text promised wiring that did not ship; the replacement states what the code actually does without changing any example value, default or provenance cell. |
| New semantic-presence pins in `tests/test_roadmap_format.py` and `tests/test_target_repo_config_doc.py`, each proved non-vacuous by doctoring the doc **in memory** | A doc-only reconciliation otherwise regresses silently; the metamorphic checks prove each pin fails on the stale wording or a deleted dual-home statement. |
| README gains a short "Documentation" note under "Layout" linking both contracts | Prompt-fixed cross-link only; the full README rewrite remains E9.4. |

**Where it fits in the roadmap:** Epic E9 (post-extraction design and contract docs). It follows E9.1 (the `design.md` rewrite, which already cross-links both docs) and E3.6/E5.1 with their shipped follow-ups E5.2/E5.3/E5.4, and it precedes E9.3 (move the roadmap to history) and E9.4 (README rewrite).

**Scope:** The two contract documents, their existing drift tests, the README cross-links, and the E9.2 checkbox/notes in the roadmap. Deliberately stops short of moving or copying the roadmap, rewriting the README, re-editing `design.md`, cleaning up `AGENTS.md`, and any change to `aidw/`, `agent-configs/`, `prompts/`, `docs/schema/` or `pyproject.toml`.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E9.2-prompt.md` | Created | Task prompt for E9.2, committed on the branch as `ab39b9c`. |
| `docs/implementation-results/00-E9.2/build-results.md` | Created | This results document, written by the record stage after gating. |
| `README.md` | Modified | Adds the short "Documentation" note under "Layout" linking `docs/target-repo-config.md` and `docs/roadmap-format.md`. |
| `docs/roadmap-format.md` | Modified | Status table marks E5.3/E5.4 done with shipped-artefact pointers; §1 adds `--validate`; §6 points at `validate_tasks`; §10 replaces the "No validation"/"No duplicate-id detection" bullets with the silent-parser vs pure-validator split and the three rule tokens. |
| `docs/target-repo-config.md` | Modified | Field-inventory intro and Override-precedence note now state the shipped two-home reality for the `repo:` leaves instead of the "rewire"/"until then" forward-looking text; examples, field tables and provenance cells unchanged. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E9.2 `[x]` and records the reconciliation notes (no vector-matrix/coverage-catalog change; the two contracts' drift tests are the traceability evidence). |
| `tests/test_roadmap_format.py` | Modified | Adds status-table/§1/§6/§10 semantic-presence pins against the `RULE_*` tokens and the shipped CLI, plus a metamorphic non-vacuity test that doctors the doc in memory only. |
| `tests/test_target_repo_config_doc.py` | Modified | Adds the dual-home pin (both leaves, both homes, the five workflows, no production reader of the resolved leaves), a ban on "rewire"/"until then", an equality assertion against `TargetRepo`/`TOOLKIT_DEFAULTS`, and a non-vacuity test. |

---

## Verification Results

All outcomes below were recorded in one run by stage `record-implementation-results` against tree `b07b4fa00ec2`, with the scope every stage of this workflow declares: `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.42ms`, exit 0). Gate `install`, tree `b07b4fa00ec2`, stage `record-implementation-results`, 2026-11-06T09:02:44Z |
| Build | `uv build --no-build-isolation --out-dir <tmpdir>` | ✅ Pass (`Successfully built …/aidt-0.1.0.tar.gz` and `…/aidt-0.1.0-py3-none-any.whl`). Gate `build`, tree `b07b4fa00ec2`, stage `record-implementation-results`, 2026-11-06T09:02:48Z |
| Test | `uv run --frozen pytest` | ✅ Pass (`1879 passed in 29.14s`, exit 0). Gate `suite`, tree `b07b4fa00ec2`, stage `record-implementation-results`, 2026-11-06T09:03:20Z |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (`21 checks: 0 failed, 2 warning(s)`: dirty working tree on `00-E9.2`, missing `.mcp.json`). Gate `doctor`, tree `b07b4fa00ec2`, stage `record-implementation-results`, 2026-11-06T09:03:25Z |
| Agent configs | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`). Gate `agents-validate`, tree `b07b4fa00ec2`, stage `record-implementation-results`, 2026-11-06T09:03:25Z |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (`toolkit defaults: 0 error(s), 0 warning(s)`; `resolved repo prompts: 0 error(s), 0 warning(s)`). Gate `prompts-check`, tree `b07b4fa00ec2`, stage `record-implementation-results`, 2026-11-06T09:03:25Z |
| Whitespace | `git diff --check` | ✅ Pass (no output, exit 0) |

Lint: **not run** — this repository configures no linter, formatter, or type-checker (`AGENTS.md`, `design.md` §15), so it has no lint gate and none was invented. Build was run for packaging sanity; `AGENTS.md`'s configured gate set names only install, pytest, doctor, agents validation and prompts check.

### `uv run --frozen pytest` (full suite)

Every row is taken from a single invocation; no subset was re-run to obtain a count.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1879 | ✅ Pass (`1879 passed in 29.14s`) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Task prompt's targeted suite: `uv run --frozen pytest tests/test_target_repo_config_doc.py tests/test_roadmap_format.py tests/test_roadmap.py tests/test_roadmap_validate.py -n0` | ✅ Pass (`93 passed in 0.47s`). Gate `task-tests`, tree `b07b4fa00ec2`, stage `record-implementation-results`, 2026-11-06T09:03:29Z |
| Stale-claim sweep: `rg "not done\|No validation\|No duplicate-id detection\|E4–E6 rewire\|E4/E5 rewire\|until then" docs/roadmap-format.md docs/target-repo-config.md` | ✅ No hits (rg exited 1; ran directly, not through `aidw gate`) |
| Shipped validation surfaced: `rg "validate_tasks\|aidw tasks --validate" docs/roadmap-format.md` | ✅ Hits the status table (line 11), §2 (62), §6 (217), and §10 (420, 433) |
| README cross-links: `rg "docs/target-repo-config.md\|docs/roadmap-format.md" README.md` | ✅ Both links present at lines 713 and 715 |
| Roadmap doc's status table and §10 carry no stale wording and name `validate_tasks`, `aidw tasks --validate` and the three `RULE_*` tokens | ✅ `test_status_table_marks_the_validation_tasks_shipped`, `test_section_10_states_the_shipped_validation_contract`, `test_the_three_surfaces_name_the_shipped_validation`, `test_section_1_lists_validate_in_the_tasks_surface`, `test_section_10_uses_the_modules_rule_tokens_verbatim` passed in the full-suite run |
| Config doc states the shipped dual home for the `repo:` leaves and bans "rewire"/"until then" | ✅ `test_the_repo_leaves_dual_home_is_stated_as_shipped`, `test_the_field_inventory_drops_the_forward_looking_effect_note`, `test_the_documented_two_homes_are_equal_in_the_code` passed in the full-suite run |
| The reconciliation pins are not vacuous (doctored stale wording / deleted dual-home statement fails) | ✅ `test_the_reconciliation_pins_are_not_vacuous` and `test_the_dual_home_pin_is_not_vacuous` passed in the full-suite run |
| Contract examples still validate against the shipped schema/parser (§9 roadmap example, three YAML examples) | ✅ The existing extraction/resolution tests (`tests/test_roadmap_format.py`, `tests/test_roadmap.py`, `tests/test_target_repo_config_doc.py`, `tests/conftest.py:roadmap_example`) passed in the full-suite run |
| Purity regressions (`test_validate_tasks_is_pure`, `test_example_parsing_is_deterministic_and_read_only`) | ✅ Passed untouched in the full-suite run |

---

## Deviations observed during recording

- **The task prompt's targeted pytest command was run as its own task-specific gate** — the task prompt's Done-when names it, so it was recorded under gate `task-tests` (`93 passed`) in addition to the full-suite gate. It is reported as a named gate row, not as a second full-suite run.
- **Traceability checkbox and notes are uncommitted on the branch** — `docs/tasks/00 - Extraction.md` shows E9.2 marked `[x]` plus notes in the working tree; recording verified the tree but did not commit.
- **Build was run although the configured gate set does not name it** — included for packaging sanity, reported with its real outcome, and it has no effect on the repository.

---

## Non-Goals (NOT implemented)

- ❌ E9.3: moving or copying the roadmap file to `docs/migration/` history (task prompt, "Explicit non-goals").
- ❌ E9.4: README rewrite or content restructure — only the two cross-links were added (task prompt, "Explicit non-goals").
- ❌ Re-editing `design.md` — E9.1 is done and already cross-links these docs (task prompt, "Explicit non-goals").
- ❌ `AGENTS.md` "Where truth lives" cleanup (it still calls these docs placeholders) — a separate cleanup (task prompt, "Explicit non-goals").
- ❌ Any change to `aidw/`, `agent-configs/`, `prompts/`, `docs/schema/`, or `pyproject.toml` (task prompt, "Explicit non-goals").
- ❌ Changing the contract docs' fenced examples, field-inventory tables, values, defaults or provenance cells — prose-only edits (task prompt, requirement 5).
- ❌ Fixing the stale `aidw/target_config.py:ConfigDefaults` docstring — the code comment is off-limits; the doc states the shipped reality (task prompt, "Traps").
- ❌ Committing, pushing, or opening a PR — the `/pr` stage owns delivery.
