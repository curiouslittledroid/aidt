# Build Results — 00-E4.2: Prompt resolver (D14)

**Branch:** `00-E4.2`
**Date:** 2026-11-03
**Spec:** `docs/migration/EXTRACTION.md` §3.6 (prompt resolution), §3.4 (target-repo config, the four-level precedence), §3.12 (directory layout), §2 (locked decisions D2, D4, D14); `design.md` §7.3 (prompt rendering) and §3 (layout)

## Summary

**Purpose:** One prompt resolver implementing §3.4's four-level precedence — declared `prompt:` path → `<target>/aidw/prompts/<name>` shadow → toolkit `prompts/<name>` default → fail-closed error — and a `--prompt-template` root list that hands Pi the same file the resolver chose.

**Key design decisions**

| Decision | Why it matters |
|----------|---------------|
| `resolve_prompt(toolkit_root, target_root, name, explicit_path=None)` widens the existing resolver in `aidw/runner.py` | `cli.py` already imports it from there (E4.2 req 1, D14); no second resolver exists, so there is no divergent precedence implementation. |
| A declared-but-missing `explicit_path` raises `FileNotFoundError` and never falls through to the shadow or toolkit | §3.4 makes an unresolvable required prompt an error, not a silent skip; the failure message names the searched locations. |
| `name` accepts both `code-review` and `code-review.md` (one trailing `.md` stripped before lookup) | Preserves the old resolver's behaviour (`aidw/runner.py`), keeping `aidw exec --prompt code-review.md` working. |
| `StageSpec.explicit_prompt: str | None` carries the declared `prompt:` string; the caller sets it, the resolver never imports `target_config` or workflows | Keeps the resolver a leaf and avoids the `target_config → runner → workflows` import cycle (E4.1's trap, req 6). |
| `prompt_template_dirs(agent, target_root, explicit_path)` in `aidw/agents.py` composes the complete ordered root list; `build_argv` gains `prompt_templates=None` | `run_stage` is the only place the target root is in scope; `None` keeps every pre-E4.2 caller and test unchanged. |
| **Empirically verified order: first `--prompt-template` root wins** — verified order emitted as target root → toolkit roots → explicit path last | Pi 1.2.0 was probed in both root orders (no model call). This contradicts §3.6's asserted "toolkit then target", so the measured order is emitted and the deviation recorded next to the helper. |
| Target root omitted when `<target>/aidw/prompts/` does not exist; passed when present-but-empty | §3.4 makes a repo with no `aidw/` folder valid (pure defaults) and Pi accepted an empty root silently in the probe. |

**Where it fits in the roadmap:** Extraction phase E4 (config-driven workflows). Depends on E1.x (runner/argv plumbing, E1.2's scripts-dir fix) and E4.1 (target config, whose no-import-cycle constraint this task honours). The resolver and template-root helper are the prerequisite for E4.3 (config-driven plans built from `stage_registry` + this resolver), E4.5 (core vs repo-optional enforcement), and E4.6/E4.7 (agent/model overrides and the full fixture integration test).

**Scope:** Touches `aidw/runner.py` (resolver + `StageSpec.explicit_prompt` + `run_stage` root plumbing), `aidw/agents.py` (`prompt_template_dirs`, `build_argv` keyword, the recorded Pi precedence comment), `aidw/cli.py` (the `aidw exec` call site only), the one committed fixture override, and the four test files. It deliberately stops short of rewiring the workflows.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `tests/test_prompt_resolution.py` | Created | 13 contract tests (14 collected) for the four precedence levels, fail-closed paths, both `name` forms, template-root ordering via a `run_stage` dry-run argv, and the fixture-override end-to-end. |
| `fixtures/target-repo/aidw/prompts/code-review.md` | Created | Minimal, unmistakable fixture override proving `<target>/aidw/prompts/code-review.md` shadows the toolkit default. |
| `docs/task-prompts/00-E4.2-prompt.md` | Created | Task prompt for this task (written by an earlier stage). |
| `aidw/runner.py` | Modified | Four-level `resolve_prompt` with fail-closed messages; `StageSpec.explicit_prompt`; `run_stage` builds the ordered `--prompt-template` list via `prompt_template_dirs`. |
| `aidw/agents.py` | Modified | New `prompt_template_dirs` with the recorded Pi 1.2.0 precedence probe (both root orders, empty-root result); `build_argv(..., prompt_templates=None)`. |
| `aidw/cli.py` | Modified | `aidw exec` maps `--prompt` onto name vs `explicit_path`, sets `StageSpec.explicit_prompt`, and calls the new resolver signature. |
| `tests/test_runner.py` | Modified | `test_resolve_prompt_by_name` / `test_resolve_prompt_by_path` updated to the new contract. |
| `tests/test_agents.py` | Modified | Tests for the `prompt_templates` override, complete ordered emission, and `prompt_template_dirs` omit/empty/explicit cases. |
| `tests/test_cli.py` | Modified | `spy_resolve` updated to the four-argument resolver signature only. |
| `docs/tasks/00 - Extraction.md` | Modified | E4.2 marked complete (traceability stage). |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.38ms` (already locked/synced) |
| Build | `uv build --out-dir <tmp>` | ✅ gate `build` passed — built `aidt-0.1.0-py3-none-any.whl` and `aidt-0.1.0.tar.gz` |
| Test | `uv run --frozen pytest` | ✅ gate `suite` passed — `1093 passed in 23.83s` |
| Doctor | `uv run --frozen aidw doctor` | ✅ `19 checks: 0 failed, 2 warning(s)` (warnings: dirty working tree, missing `.mcp.json`) |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ `11 agent config(s): 0 error(s), 0 warning(s)` |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ `prompts check: 0 error(s), 0 warning(s)` |
| Whitespace | `git diff --check` | ✅ clean |

Both `suite` and `build` were run in this stage against tree `24707a6e5537` (not reused from an earlier stage), with the declared scope
`--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1093 | ✅ Pass (`1093 passed in 23.83s`) |
| `tests/test_prompt_resolution.py` | 14 collected | ✅ Pass — part of the full-suite run above (count from `--collect-only`, no separate execution) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Four precedence levels (explicit > shadow > toolkit > error) | ✅ `test_explicit_path_wins_over_shadow_and_toolkit_default`, `test_target_shadow_wins_over_the_toolkit_default`, `test_toolkit_default_used_when_the_target_has_no_shadow`, `test_unresolvable_name_fails_closed_naming_every_searched_location` |
| Missing declared path fails closed (no fall-through) | ✅ `test_missing_declared_path_does_not_fall_through_to_shadow_or_toolkit`, `test_absolute_explicit_path_is_used_as_declared` |
| Both `name` forms resolve identically | ✅ `test_bare_and_md_suffixed_names_resolve_to_the_same_file` |
| Template-root ordering pinned via `run_stage` dry-run argv | ✅ `test_template_roots_pin_target_first_and_explicit_path_last`, `test_template_roots_omit_a_target_without_an_override_dir`, `test_template_roots_include_a_present_but_empty_override_dir` |
| Fixture override end-to-end renders the override, not the toolkit default | ✅ `test_fixture_override_end_to_end_renders_the_override` |
| Resolver purity (no git/gh/pi spawn, no input mutation) | ✅ `test_resolution_is_a_pure_existence_check`, `test_shadow_choice_is_invariant_to_the_toolkit_default_appearing` |
| Empirical Pi `--prompt-template` precedence probe | ✅ Recorded in the comment next to `prompt_template_dirs` (Pi `1.2.0`, confirmed `pi --version`): first root wins in both orders; empty root accepted silently. **Not re-run in this stage** — it is a one-time manual, model-free RPC probe by the implementation agent, and no test may spawn `pi`. |

---

## Deviations observed during recording

- **Prompt's generic gate commands are pnpm-shaped** — this repository's own stack is Python/uv (`pyproject.toml`/`uv.lock`), so the `uv` gates named in `AGENTS.md` and `pr.md` were run instead of `pnpm install` / `pnpm -r lint|build|test`. There is no configured linter (design §15), so no `lint` gate row exists.
- **Verified Pi precedence contradicts §3.6's asserted order** — the probe showed the first `--prompt-template` root wins, so the helper emits target root → toolkit roots → explicit path, with the deviation documented at the helper (as the task prompt required).

---

## Non-Goals (NOT implemented)

- ❌ E4.3 config-driven plans (porting `build_plan` and the workflows to build stage lists from `stage_registry` + this resolver) — `implement`/`prompt`/`review`/`fix`/`approve` are not rewired.
- ❌ E4.5 core vs repo-optional enforcement (the "unknown stage id" half of §3.4 precedence 4).
- ❌ E4.6 agent/model/thinking/timeout overrides, and E4.7 the full six-behaviour fixture integration test against `fixtures/target-repo/` — only the single minimal override this task needs was committed.
- ❌ E7.5 inventory split (`aidw prompts check` validating resolved repo prompts independently).
- ❌ §3.6's `AIDW_SCRIPTS_DIR` note (already landed in `run_stage` in E1.2).
- ❌ No PR opened, no push, no merge — delivery is `/pr`'s job.
