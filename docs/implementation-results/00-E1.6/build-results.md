# Build Results — 00-E1.6: `aidw config show` (skeleton)

**Branch:** `00-E1.6`
**Date:** 2026-10-26
**Spec:** `docs/migration/EXTRACTION.md` §3.1 (Two roots — resolution table and the "two distinct types" rule), §3.3 (CLI surface changes — the `aidw config show` row, line 173, and the "existing subcommands / exit codes / stdout JSON keys stay stable" note), §3.4 (Target-repo config — the `<target>/aidw/config.yaml` layout; "a target repo with no `aidw/` folder is valid"), §3.10 (State, runs, locking — the three-tier state-root formula and `AIDW_STATE_DIR`). Roadmap: `docs/tasks/00 - Extraction.md` Epic E1, task E1.6.

> **Template note:** This stage's prompt instructs it to use `docs/implementation-results/TEMPLATE.md`. **That file has never existed in this repository or its history** (`find`/`git log --all` both empty), as already recorded in `docs/implementation-results/00-E1.3/build-results.md`, `00-E1.4/build-results.md` and `00-E1.5/build-results.md`. This document therefore follows the structure established by the five existing results documents, `00-E1.1` through `00-E1.5`, which are the de-facto template in this repo. No placeholders remain.

## Summary

**Purpose:** Add the `aidw config show` skeleton to `aidw/cli.py` plus its `--json` mode. It prints six values — toolkit root, version, target root, workspace root, state root, and the target config file found or none — each with a provenance source label. It consumes E1.5's already-resolved 3-tuple `(TargetRepo, ToolkitPaths, WorkspacePaths)` without re-resolving, detects (but never parses) `<target>/aidw/config.yaml`, and resolves target/workspace/state once through `_roots()`.

| Decision | Why it matters |
|----------|---------------|
| The `config` command follows the `agents`/`runs` `action`-argument pattern (`action: str = "show"`, `--json`) and validates the action **before** any printing or `_roots()` call | A doubly-bad invocation (unknown action plus a bad target) exits `EXIT_USAGE` (2) with empty stdout; action validation wins over target refusal. This is a deliberate deviation from `agents`/`runs`, which resolve roots first |
| The E1.5 inline `_roots()` target-selection normalization was extracted verbatim into `_resolve_target_selection() -> tuple[Optional[Path], str]` in `aidw/cli.py`, returning `(explicit, source)` | The one sanctioned edit to `_roots()`: a pure refactor with no behavior change. `config show` and `_roots()` now read `AIDW_REPO` in exactly one place (`--repo` > `$AIDW_REPO` stripped/blank→unset > cwd), so provenance labels cannot diverge from the winner |
| `_state_root_source(workspace: WorkspacePaths) -> str` labels the winning state tier by comparing `workspace.state_root.parent` to the resolved candidates in `_state_base`'s post-override order (`$AIDW_STATE_DIR`, then `<workspace_root>/.aidw/state`, else `home`) | `config show` threads `WorkspacePaths` from `_roots()` with `state_dir_override=None`, so only three tiers are reachable. Comparing already-resolved paths (env candidate via `Path(env).resolve()`, workspace candidate via `(.../"state").resolve()`) avoids re-running the usability walk, which could disagree. The env check mirrors `_state_base`'s bare truthiness (no strip), so a whitespace-only `AIDW_STATE_DIR` is labelled `AIDW_STATE_DIR` |
| Human mode pre-prints `toolkit root` + `version` (both source `package`) **before** `_roots()`; `--json` buffers all six values and emits one object only on success | A wrong-target invocation still shows toolkit root + version on stdout before the refusal — the wrong-target debug aid. JSON is all-or-nothing: a refusal exits 4 with empty stdout, no partial object and no human lines |
| `config show` uses the threaded `workspace`/`target` objects and never calls `WorkspacePaths.resolve()`/`TargetRepo.resolve()` itself | Preserves E1.5's resolve-once rule (`_roots()` is the single resolution site); a second resolution would duplicate the threaded one |
| Config detection is `Path(<target>/aidw/config.yaml).is_file()` only; a regular file yields its resolved path with source `target repo`, otherwise value `none` with source `defaults` | Detection only — no YAML parse/validate (that is E3.1/E3.5). Missing path, a directory, and a broken symlink all fall to `defaults` |
| The pinned source strings are `package` (toolkit_root, version), `--repo`/`AIDW_REPO`/`cwd` (target_root), `workspace` (workspace_root and the workspace state tier), `AIDW_STATE_DIR`/`home` (state_root), `target repo`/`defaults` (config_file); human and `--json` modes use the same strings | The `--json` shape and label vocabulary are prompt-fixed (the cited spec says only "with provenance"). Display-label wording is intentionally not pinned |
| Existing commands' stdout, JSON keys and exit codes are unchanged; `aidw/paths.py` and the `TargetRepo`/`ToolkitPaths`/`WorkspacePaths` types are untouched | §3.3 surface freeze and Requirement 7; provenance is display-layer only |

**Where it fits in the roadmap:** Task E1.6 in Epic E1 ("Two-root core") of the AIDT extraction — the last task in E1. It consumes E1.1 (`TargetRepo.resolve`), E1.2 (`ToolkitPaths`), E1.3/E1.4 (workspace state root) and E1.5 (typed CLI plumbing, `AIDW_REPO`, `_roots()` 3-tuple). Downstream: E3.1/E3.2/E3.5 add YAML load/validate and defaults→config merge (the skeleton's provenance is a CLI label, not a data model), E2.8 adds doctor checks, E3.4 materialises default path values.

**Scope:** The `config show` subcommand and `--json` mode; the `_resolve_target_selection` verbatim extraction; `_state_root_source`; config-file detection; the matching `tests/test_cli.py` cases; and the E1.6 roadmap checkbox. It deliberately stops short of E3.1/E3.2/E3.5 (no YAML load/validate/merge), E2.8 (not `doctor`), E3.4 (no default path materialisation), and any E1.5 re-threading or re-resolution.

---

## Files Changed

The change set is the working tree relative to the base branch (`origin/main`, where E1.5 is merged via PR #10; local `main` is stale at E1.4). Three files are **uncommitted** in the working tree; the task prompt is committed.

| File | Action | Description |
|------|--------|-------------|
| `aidw/cli.py` | Modified (uncommitted) | Added the `config` command (`config(action="show", --json)`) with action validation first; added `_resolve_target_selection()` (verbatim extraction of `_roots()`'s `--repo`>`AIDW_REPO`>cwd normalization, returning `(explicit, source)`) and `_state_root_source(workspace)`; `_roots()` now calls the helper; human and JSON output with the six values and provenance; added the `json` and `STATE_DIR_ENV_VAR` imports |
| `tests/test_cli.py` | Modified (uncommitted) | Added 17 `config show` contract tests (human 6-line output, exact JSON key set/sources, config-file detection file/directory/broken-symlink/invalid-YAML, target precedence `--repo`/`AIDW_REPO`/`cwd`, whitespace `AIDW_REPO`, state tiers env/whitespace-env/home, human/JSON refusals, doubly-bad exit 2, resolve-once, no-state-writes); added the `json` and `EXIT_USAGE` imports plus `CONFIG_KEYS`/helpers |
| `docs/tasks/00 - Extraction.md` | Modified (uncommitted) | Marked roadmap task E1.6 done (`[ ]` → `[x]`, one line) |
| `docs/task-prompts/00-E1.6-prompt.md` | Created (committed `663ccf9`, revised `59ef416`) | Task prompt authored for E1.6 through the toolkit (planning-stage artifact) |

The E1.6 implementation changes (`aidw/cli.py`, `tests/test_cli.py`, roadmap checkbox) are **uncommitted** — `git status --short` shows exactly ` M aidw/cli.py`, ` M "docs/tasks/00 - Extraction.md"`, ` M tests/test_cli.py`. The branch also carries the docs-only task-prompt commits (`663ccf9`, `59ef416`) and merge commit `7a0c750`, which merged `origin/main` (E1.5 via PR #10) into the `00-E1.6` branch to satisfy the hard E1.5 prerequisite. `git diff --stat origin/main` (working tree) is 4 files, +569/−17.

---

## Changes Made

### 1. `aidw/cli.py`

- **`_resolve_target_selection() -> tuple[Optional[Path], str]`** — reads `_state["repo"]` first (`--repo` → `"--repo"`), then `os.environ.get(AIDW_REPO_ENV_VAR)`, stripped with empty/whitespace-only treated as unset (`AIDW_REPO` → label `"AIDW_REPO"`), else `(None, "cwd")`. Docstring pins the precedence and the single-env-read rule.
- **`_roots()`** — now calls `_resolve_target_selection()` and keeps its 3-tuple shape, `TargetRepo.resolve(explicit=…)` call, and the single `except RepoNotFoundError` → `typer.Exit(EXIT_REFUSED)` refusal path unchanged. A whitespace-only `AIDW_REPO` still becomes unset (never `Path("")`).
- **`_state_root_source(workspace)`** — compares `workspace.state_root.parent` against `Path(os.environ[STATE_DIR_ENV_VAR]).resolve()` (bare truthiness, no strip) then `(workspace.workspace_root / ".aidw" / "state").resolve()`, returning `"AIDW_STATE_DIR"`, `"workspace"` or `"home"`; does not re-run `_is_usable_directory`.
- **`config()`** — `@app.command()` with `action: str = typer.Argument("show")` and `json_output: bool = typer.Option(False, "--json")`. Unknown action → stderr message + `typer.Exit(EXIT_USAGE)` before any output or resolution. Human mode echoes `toolkit root`/`version` (source `package`) first, then calls `_roots()` bare, then echoes `target root`/`workspace root`/`state root`/`config file` lines. `--json` builds one object with exactly the keys `toolkit_root`, `version`, `target_root`, `workspace_root`, `state_root`, `config_file`, each `{"value": <str|null>, "source": <str>}`, and `json.dumps`es it. Config detection is `(target.root / "aidw" / "config.yaml").is_file()`.

### 2. `tests/test_cli.py`

- 17 new tests: `test_config_show_resolves_target_and_workspace_once`, `test_config_show_human_single_checkout`, `test_config_show_json_single_checkout`, `test_config_show_detects_the_target_config_file`, `test_config_show_config_file_directory_is_not_a_config`, `test_config_show_config_file_detection_does_not_parse_yaml`, `test_config_show_broken_config_symlink_uses_defaults`, `test_config_show_target_provenance`, `test_config_show_whitespace_aidw_repo_falls_to_cwd`, `test_config_show_state_provenance_env`, `test_config_show_state_provenance_whitespace_env`, `test_config_show_state_provenance_home`, `test_config_show_wrong_target_refuses_human`, `test_config_show_bare_target_refuses`, `test_config_show_wrong_target_json_leaves_stdout_empty`, `test_config_unknown_action_beats_a_bad_target`, `test_config_show_writes_no_state_dir`.
- Existing tests were not modified; only the `json` and `EXIT_USAGE` imports were added at the top.

---

## Verification Results

> **Overall gate: ✅ PASS.** The repository's real test gate (`uv run --frozen pytest`) is green: **439 passed in 98.20s**, exit 0. All task-specific gates (`aidw doctor`, `aidw prompts check`, structural resolve-site check, live CLI demos) also pass. `git diff --check` is clean.

### Top-level verification

This is a Python/uv project: `.github/workflows/ci.yml` runs `uv sync --frozen`, `uv run --frozen pytest` and `uv run --frozen aidw doctor`. There is **no `package.json`, `pnpm-workspace.yaml` or `pnpm-lock.yaml`**, so the template's pnpm matrix does not apply. Both the `pnpm` commands and the repository's real `uv` gates were executed; exact outcomes follow.

| Step | Command | Result |
|------|---------|--------|
| Install (template) | `pnpm install` | ❌ Exit 1 — `ERR_PNPM_NO_PKG_MANIFEST No package.json found in /Users/phil`. Not applicable: no pnpm project |
| Lint (template) | `pnpm -r lint` | ⚠️ Exit 0 — `No projects found in "/Users/phil/software-projects/aidt"`. No linter/lint script configured |
| Build (template) | `pnpm -r build` | ⚠️ Exit 0 — `No projects found …`. See `uv build` below for the real build gate |
| Test (template) | `pnpm -r test` | ⚠️ Exit 0 — `No projects found …`. See `uv run --frozen pytest` below for the real test gate |
| Install (real) | `uv sync --frozen` | ✅ Exit 0 — `Checked 13 packages in 2ms` |
| Build (real) | `uv build --out-dir /tmp/aidt-e16-build.OljEr1` | ✅ Exit 0 — built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` into the temp dir; repo tree untouched |
| Test (real) | `uv run --frozen pytest` | ✅ **Exit 0 — `439 passed in 98.20s`** |
| Doctor | `uv run --frozen aidw doctor` | ✅ Exit 0 — `14 checks: 0 failed, 2 warning(s)`; warnings are the dirty working tree and missing `.mcp.json`, both expected |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Exit 0 — `0 error(s), 0 warning(s)` |
| Whitespace | `git diff --check` | ✅ Clean (exit 0) |

### `uv run --frozen pytest` (full suite)

Full-suite total: **439 passed in 98.20s** (exit 0). No test failed, errored or was skipped.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 439 | ✅ Pass (`439 passed`) |
| `tests/test_cli.py` (all existing + 17 new `config show`) | 38 | ✅ Pass (`38 passed in 20.80s`) |
| `tests/test_cli.py -k config` | 17 selected (21 deselected) | ✅ Pass (`17 passed, 21 deselected in 5.84s`) |
| Regression modules (`test_paths`, `test_target_repo`, `test_toolkit_paths`, `test_workspace_paths` — unmodified) | 86 | ✅ Pass (`86 passed in 51.08s`) |

> The full-suite count (439) is consistent with the `/test` stage's `439 passed`; the implementer's earlier `436 passed` predates the final test additions and is superseded by this recorder's run.

### Task-specific verification gates

The task prompt names no `srd:*`/`cdk` gate; its Done-when is the pytest suite, the config-show contract tests, `aidw doctor`, `aidw prompts check`, and the structural resolve-site / changed-files checks.

| Gate | Status |
|------|--------|
| `config show` human mode prints six `label: value (source)` lines | ✅ Live demo exit 0 — 6 lines: toolkit root/version `(package)`, target root `(cwd)`, workspace root `(workspace)`, state root `(workspace)`, config file `none (defaults)`; `test_config_show_human_single_checkout` passes |
| `--json` emits one object with exactly the six keys and `{value, source}` per value | ✅ Live demo exit 0 — parsed object has exactly `toolkit_root`, `version`, `target_root`, `workspace_root`, `state_root`, `config_file`, each `{value, source}`; `test_config_show_json_single_checkout` passes |
| Toolkit root + version resolve with no repo and print first (`package`) | ✅ `test_config_show_wrong_target_refuses_human`; live refusal demo shows both on stdout |
| `config show --repo <non-repo>` refuses `EXIT_REFUSED` (4), stderr names the path, no traceback | ✅ Live demo exit 4 — stderr `Not inside a git repository (started at …/notarepo); cannot determine repo root.`; `test_config_show_wrong_target_refuses_human` passes |
| `--json` refusal exits 4 with empty stdout (all-or-nothing) | ✅ Live demo exit 4, stdout `0 bytes`, path on stderr; `test_config_show_wrong_target_json_leaves_stdout_empty` passes |
| Bare target refuses via the same catch site | ✅ `test_config_show_bare_target_refuses` passes (`bare repository`, `EXIT_REFUSED`) |
| Doubly-bad (unknown action + bad target) exits `EXIT_USAGE` (2) with empty stdout | ✅ Live demo exit 2, stdout `0 bytes`, stderr `unknown action: bogus (expected show)`; `test_config_unknown_action_beats_a_bad_target` passes |
| Target provenance follows `--repo` > `AIDW_REPO` > cwd | ✅ `test_config_show_target_provenance` (all three, both-set) and `test_config_show_whitespace_aidw_repo_falls_to_cwd` pass |
| `_roots()` is the sole `TargetRepo`/`WorkspacePaths` resolution site; `config show` does not re-resolve | ✅ `rg "TargetRepo\.resolve|WorkspacePaths\.resolve" aidw/` matches only `aidw/cli.py:94` (`TargetRepo.resolve`) and `aidw/cli.py:101` (`WorkspacePaths.resolve`, both inside `_roots()`); `test_config_show_resolves_target_and_workspace_once` asserts each resolves exactly once |
| State provenance labels `AIDW_STATE_DIR` / `workspace` / `home` | ✅ `test_config_show_state_provenance_env`, `::test_config_show_state_provenance_whitespace_env` (whitespace env stays `AIDW_STATE_DIR`), `::test_config_show_state_provenance_home` pass |
| Config detection is `is_file()` only (file/directory/broken symlink/invalid YAML) | ✅ `test_config_show_detects_the_target_config_file`, `::test_config_show_config_file_directory_is_not_a_config`, `::test_config_show_broken_config_symlink_uses_defaults`, `::test_config_show_config_file_detection_does_not_parse_yaml` pass |
| Resolution is read-only (no undeclared state-dir writes) | ✅ `test_config_show_writes_no_state_dir` passes |
| `uv run pytest` is green | ✅ Exit 0 — 439 passed |
| `uv run aidw doctor` clean | ✅ Exit 0 — 14 checks, 0 failed, 2 warnings |
| `uv run aidw prompts check` clean | ✅ Exit 0 — 0 error(s), 0 warning(s) |
| Diff touches only `aidw/cli.py`, `tests/test_cli.py`, roadmap checkbox (+ committed prompt) | ✅ `git status --short` shows only those three working-tree files; `git diff --name-only HEAD -- aidw/paths.py` is empty (`aidw/paths.py` untouched) |
| `pnpm srd:validate` | ❌ Exit 1 — `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND No package.json (or package.yaml, or package.json5) was found in "/Users/phil"`. **Unrunnable**: no pnpm manifest / `srd:*` scripts in this repo |
| `pnpm srd:check-references` | ❌ Exit 1 — same `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND`; **unrunnable** (no pnpm manifest) |
| `pnpm srd:matrix-check` | ❌ Exit 1 — same `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND`; **unrunnable** (no pnpm manifest) |
| `pnpm srd:report` | ❌ Exit 1 — same `ERR_PNPM_NO_IMPORTER_MANIFEST_FOUND`; **unrunnable** (no pnpm manifest) |
| `pnpm --filter infra cdk synth -c env=dev` | ⚠️ Exit 0 — `No projects found …`. **Structurally unrunnable**: no `infra/` project or `cdk.json` exists, so this is not a real synth |

### Deviations observed during recording

- **`--repo` ordering in the task prompt vs. the real CLI.** The prompt phrases the refusal case as `config show --repo <path>`, but here `--repo` is a **global** callback option and must precede the subcommand (`aidw --repo <path> config show`). The tests and the live demos use the repository's actual ordering. Recorded by the implementer.
- **`AIDW_REPO`-with-no-`--repo` provenance relies on the shared `_resolve_target_selection` helper.** Extracting that helper was the one sanctioned edit to `_roots()`; `_roots()`'s 3-tuple shape, precedence, strip/empty→unset semantics and `RepoNotFoundError → EXIT_REFUSED` behavior are otherwise unchanged.
- **No `pnpm` workspace.** The template's `pnpm install`/`-r lint|build|test` and `srd:*`/`cdk` gates are not part of this repository; the real uv gates were run instead.
- **Prerequisite merge commit `7a0c750`.** E1.5 is merged to `origin/main` (PR #10); the docs branch was merged with `origin/main` to satisfy the hard E1.5 prerequisite. It adds no code to this task's change set.

---

## Non-Goals (NOT implemented)

- ❌ E3.1/E3.2/E3.5: no YAML load/validate, no defaults→config merge, no per-value provenance resolution API — the skeleton's provenance is a CLI label, not a data model (task prompt, Explicit non-goals)
- ❌ E2.8: no doctor checks (workspace/state-root/git/target) — `config show` is not `doctor` (task prompt, Explicit non-goals)
- ❌ E3.4: no materialising the Mythical Forge default path values (task prompt, Explicit non-goals)
- ❌ E1.5: no re-threading, no re-resolution — `config show` consumes E1.5's 3-tuple as-is. The only `_roots()` edit is the sanctioned verbatim extraction of the target-selection normalization into `_resolve_target_selection` (task prompt, Explicit non-goals; Requirement 4)
- ❌ No change to any existing command's stdout, JSON keys or exit codes; no `aidw/paths.py` type change — the surface stays frozen (§3.3, Requirement 7)
- ❌ No commit, push or pull request — `aidt/prompts/pr.md` owns that; the implementation and its tests remain uncommitted
