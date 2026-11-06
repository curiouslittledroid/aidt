# Build Results — E8.3: Version reporting

**Branch:** `00-E8.3`
**Date:** 2026-11-06
**Spec:** `docs/migration/EXTRACTION.md` §3.11 (version and compatibility, D10: `aidw doctor` validates the target config; semver the toolkit; a target may pin `requires_toolkit`), §2 (D9/D10 locked decisions: toolkit version recorded in `state.json`, config `schema_version` + optional minimum toolkit version, toolkit refuses a config it cannot understand); `design.md` §12 (configuration and `aidw doctor` validation), §14 (CLI reference, global flags and exit codes)

## Summary

**Purpose:** Make the toolkit version reportable without a target repo (`aidw --version`) and make `aidw doctor` state the toolkit version, the git version, and the D10 compatibility verdict as three separately named checks.

| Decision | Why it matters |
|----------|---------------|
| One rendering helper, `_version_line()` → `aidt {__version__}`, shared by the `version` subcommand and the new eager `--version` flag | The two surfaces cannot disagree about what this checkout ships, and the version stays `aidw.__version__` (E1.6 / §17 P1) rather than a `git`/`uv` shell-out or a `pyproject.toml` parse. |
| `--version` is an eager Click option with a callback that echoes and exits before `_roots()` | Exactly the roadmap's "without a target repo": from a non-repository cwd it exits 0 instead of raising `RepoNotFoundError`. Click's default `<prog>, version <v>` shape is deliberately not used because it would disagree with the `version` subcommand. |
| `toolkit version` is an environment check placed before the `TargetRepo.resolve` try/except, beside `git version` | Doctor still names the version when it runs outside any repository; the check is informational and always OK. |
| The D10 verdict **moves out of** `target config` into a distinct `compat status` check | `check_compatibility` is evaluated exactly once, an incompatible `schema_version`/`requires_toolkit` is one FAIL on one named line, and `target config` keeps the loader's ERROR issues, `validate_paths`, and the resolved schema-version line. Copying instead of moving would double-report the same failure. |
| `compat status` does not pre-test the config file with `exists()`/`is_file()` | A missing `aidw/config.yaml` is §3.4's valid defaults case; the loader's `source_path is None` with no issues is what makes the verdict OK, and a pre-check would turn every config-less repo red. |

**Where it fits in the roadmap:** Epic E8 (packaging, distribution, versions) under D9/D10. It builds on E8.1's installable wheel and single version source and on E8.2's toolkit/config identity in `state.json`, and it completes the version/compatibility reporting the E8 epic names. E8.4 (README install paths, bare/worktree bootstrap), E8.5 (release process, first tag) and E9.1's design rewrite remain downstream.

**Scope:** Two surfaces in `aidw/cli.py` (`--version` plus the shared version-line helper) and two new doctor checks in `aidw/doctor.py` (`toolkit version`, `compat status`), with the compatibility verdict moved out of `_check_target_config`; tests in `tests/test_cli.py` and `tests/test_doctor.py`; one §17 decision-log row in `design.md`; the E8.3 roadmap checkbox. It deliberately stops short of installation/release documentation, any tag, the E9.1 design rewrite, changing the `version` subcommand's output or `_check_target_config`'s read-path/schema-version reporting, and refactoring `aidw config show`.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/implementation-results/00-E8.3/build-results.md` | Created | This results document, written by the record stage after gating. |
| `docs/task-prompts/00-E8.3-prompt.md` | Created | Task prompt for E8.3 (committed on the branch). |
| `aidw/cli.py` | Modified | Adds `_version_line()` and the eager, target-free `--version` callback; the `version` subcommand now echoes the same helper. |
| `aidw/doctor.py` | Modified | Adds `_check_toolkit_version()` (environment check) and `_check_compat()` (D10 verdict), extracts the shared `_config_source()` helper, and removes the compatibility union from `_check_target_config` without changing its read-path or schema-version reporting. |
| `tests/test_cli.py` | Modified | Adds `--version` coverage: exact `aidt {__version__}` text, equality with the `version` subcommand, success from a non-repo cwd, and no `TargetRepo.resolve` call. |
| `tests/test_doctor.py` | Modified | Adds `toolkit version` coverage, a compat-status vector table (config-less, `schema_version: 1`, `requires_toolkit: ">=99.0.0"`, `schema_version: 2`, loader+compat as two checks), a `check_compatibility`-evaluated-once spy test, a single-FAIL-owner test, and updates the two former union-asserting tests to the split. |
| `design.md` | Modified | Adds §17 decision-log row `Q1` for the eager `--version` flag, the shared version rendering, and the moved `compat status` verdict. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E8.3 complete. |

---

## Verification Results

All gate outcomes below were produced by this recording run against tree `f7b0ab52dbb7`, with the scope every stage of this workflow declares: `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.42ms`, exit 0; no dependency or lockfile change). Gate `install`, tree `f7b0ab52dbb7`, stage `record-implementation-results`, 2026-11-06T04:33:00Z |
| Build | `uv build --no-build-isolation --out-dir $(mktemp -d)` | ✅ Pass (`Successfully built …/aidt-0.1.0.tar.gz` and `…/aidt-0.1.0-py3-none-any.whl`). Gate `build`, tree `f7b0ab52dbb7`, stage `record-implementation-results`, 2026-11-06T04:33:41Z |
| Test | `uv run --frozen pytest` | ✅ Pass (`1849 passed in 28.12s`). Gate `suite`, tree `f7b0ab52dbb7`, stage `record-implementation-results`, 2026-11-06T04:33:31Z |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (exit 0, `21 checks: 0 failed, 2 warning(s)`; warnings are the expected dirty working tree and missing `.mcp.json`, and both new checks report OK: `toolkit version 0.1.0`, `compat status none (defaults) — toolkit 0.1.0 is compatible`). Gate `doctor`, tree `f7b0ab52dbb7`, stage `record-implementation-results`, 2026-11-06T04:33:36Z |
| Agent configs | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`). Gate `agents-validate`, tree `f7b0ab52dbb7`, stage `record-implementation-results`, 2026-11-06T04:33:38Z |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (`toolkit defaults: 0 error(s), 0 warning(s)`; `resolved repo prompts: 0 error(s), 0 warning(s)`). Gate `prompts-check`, tree `f7b0ab52dbb7`, stage `record-implementation-results`, 2026-11-06T04:33:38Z |
| Whitespace | `git diff --check` | ✅ Pass (no output, exit 0) |

Lint: **not run** — this repository configures no linter, formatter, or type-checker (`AGENTS.md`, `design.md` §15), so it has no lint gate.

### `uv run --frozen pytest` (full suite)

Every row is taken from the single full-suite invocation above; no subset was re-run to obtain a count.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1849 | ✅ Pass (`1849 passed in 28.12s`) |

Per-file counts for `tests/test_cli.py` and `tests/test_doctor.py` were not taken, because that would require a second invocation of the suite (the run prints a single summary under `-q -n auto`). Their E8.3 cases are included in the full-suite total.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `cd /tmp && aidw --version` prints `aidt {__version__}` and exits 0 without a target repo | ✅ `aidt 0.1.0`, exit 0 (direct run with the repo's `.venv/bin/aidw` from `/tmp`, which contains no repository) |
| `aidw version` and `aidw --version` share one format and source | ✅ Both printed `aidt 0.1.0`, exit 0 (direct runs); equality is also pinned in the suite (`test_version_flag_agrees_with_the_version_command`) |
| `--version` performs no target resolution | ✅ Suite test `test_version_flag_resolves_no_target_repo` patches `TargetRepo.resolve` to raise and still observes exit 0 with `aidt 0.1.0` |
| Doctor reports `toolkit version` as an environment check | ✅ Gate `doctor` row: `[ ok ] toolkit version   0.1.0`, before `repo root` |
| Doctor reports `compat status` on a config-less target | ✅ Gate `doctor` row: `[ ok ] compat status     none (defaults) — toolkit 0.1.0 is compatible` |
| Compat vectors: config-less → OK; `schema_version: 1` → OK; `requires_toolkit: ">=99.0.0"` → FAIL naming the field; `schema_version: 2` → FAIL naming `schema_version`; `schema_version: 2` + `bogus: true` → separate `target config` and `compat status` FAILs | ✅ Covered by `tests/test_doctor.py::test_compat_status_reports_the_d10_verdict` and `::test_compat_verdict_lives_on_exactly_one_check` in the full-suite run |
| `check_compatibility` is evaluated exactly once per doctor run | ✅ Covered by `tests/test_doctor.py::test_collect_checks_evaluates_compatibility_once` in the full-suite run |
| Incompatible target config makes `aidw doctor` exit 1 | ✅ Covered by the FAIL vectors above in the full-suite run; not separately re-run against a scratch repository here to avoid a second suite invocation and a throwaway `git init` |

---

## Deviations observed during recording

- **No lint command exists to gate** — `AGENTS.md` lists no linter/formatter/type-checker and says not to add one, so the `lint` gate was not run; the template's lint row is omitted rather than marked passing.
- **The outside-repo `--version` gate was run directly, not through `aidw gate run`** — `aidw gate run` executes its command in the repository root, which would defeat the "no target repo" predicate. The observation is recorded above as a direct run from `/tmp`.
- **`docs/architecture` is in the declared ignore scope but does not exist yet** — it is a configured write-target of a later stage (`paths.architecture_dir`), so the scope declares it uniformly with the other stages even though the directory is absent.
- **Per-file test counts were not recorded** — taking them would need a second pytest invocation, which the single-invocation rule forbids; the full-suite total is the only count reported.

---

## Non-Goals (NOT implemented)

- ❌ E8.4 (README install paths, bare+worktree bootstrap) and E8.5 (release process, first tag) — no README sections, no tag, no release doc.
- ❌ E9.1 `design.md` rewrite — only one §17 decision-log entry; §9.2/§12/§14 are not rewritten.
- ❌ Changing the `version` subcommand's output or `_check_target_config`'s read-path/schema-version reporting — only the compatibility union moved out.
- ❌ Refactoring `aidw config show`'s `version: {__version__} (package)` output.
- ❌ Committing, pushing, or opening a PR — owned by the `/pr` stage.
- ❌ Writing `player-actions.md` or `integration-tests.md` — owned by the `show-updated-*` stages.
