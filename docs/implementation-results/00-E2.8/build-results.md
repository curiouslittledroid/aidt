# Build Results — 00-E2.8: Doctor worktree and git checks

**Branch:** `00-E2.8`
**Date:** 2026-11-03
**Spec:** `docs/migration/EXTRACTION.md` §3.1, §3.2, §3.3, §3.10; `design.md` §12, §14

## Summary

**Purpose:** Extend `aidw doctor` with the §3.2 layout diagnosis — a git version floor, target resolution through the app-level `--repo`/`AIDW_REPO` selection, a named bare-target failure, workspace/state root reporting, and a control-worktree check — so a rejected layout is named at preflight instead of failing later inside a command.

| Decision | Why it matters |
|----------|---------------|
| `GIT_MIN_VERSION = (2, 31, 0)` with absent git → `FAIL`, unreadable `--version` → `WARN` | `TargetRepo.resolve` depends on `git rev-parse --path-format=absolute`, added in git 2.31. Git is required by every command, so absence is a hard failure (like `pi`), while an unreadable version is not proof of an old git and stays advisory. |
| Target resolved with `TargetRepo.resolve(explicit=...)`, threaded from `cli.doctor()` via `_resolve_target_selection()` | The legacy `repo_root()` walk-up neither honoured `--repo`/`AIDW_REPO` nor detected a bare repository, so the bare and trap checks were unreachable from a terminal. |
| `BareRepositoryError` caught before `RepoNotFoundError` | It subclasses `RepoNotFoundError`; catching the parent first would collapse the §3.2 `git -C <bare> worktree add ../main main` bootstrap into a generic "not a git repository". |
| `aidw.layout.check_layout` imported as the single classification source | A doctor-local copy of its membership/more-than-one rule could report `OK` while `cli._roots` refuses the same layout. Its `LayoutError` maps to `FAIL` on "control worktree"; its warnings map to `WARN` on "state root". |
| Trap `FAIL` decided before the inside-tree `WARN` | A clone-of-a-worktree also has state inside a tree; if the warning won, doctor would exit 0 on a layout `_roots` rejects. `check_layout` already orders it this way. |
| Checks are read-only | `WorkspacePaths.resolve` only checks writability and `check_layout` runs read-only git; nothing creates the state root or writes under the target (§3.1). |

**Where it fits in the roadmap:** E2.8 in the extraction epic. It depends on E2.1 (macOS/Linux support), E2.2 (`aidw.layout` guard), E2.4 (worktree location / `TargetRepo.resolve`), E2.6 (missing-worktree refusal) and E2.7 (state-root and per-worktree locking). E2.9 (shared worktree test fixture) is the follow-on test-infrastructure task; this task uses local real-repo fixtures instead. It consumes the `WorkspacePaths.resolve`/`TargetRepo.resolve`/`check_layout` primitives rather than adding new ones.

**Scope:** `aidw/doctor.py` gains `GIT_MIN_VERSION`, `_parse_git_version()`, `_check_git_version()` and `_layout_checks()`; `collect_checks()`/`run_doctor()` accept and thread the explicit target; `aidw/cli.py` resolves the app-level selection and passes it to `run_doctor`. `tests/test_doctor.py` gains git-version, bare-target, trap, single-checkout, supported-layout, CLI and purity tests on real local bare/worktree fixtures. It deliberately stops short of `aidw/config.yaml` validation, toolkit-version reporting, lock-health checks, and a "main control worktree must exist" check.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E2.8-prompt.md` | Created | Task prompt committed on the branch. |
| `aidw/doctor.py` | Modified | Adds the git floor, explicit-target resolution, named bare failure, workspace/state root checks and the `check_layout`-backed control-worktree check; updates the module docstring. |
| `aidw/cli.py` | Modified | `doctor()` resolves the app-level `--repo`/`AIDW_REPO` selection via `_resolve_target_selection()` and passes it to `run_doctor()`. |
| `tests/test_doctor.py` | Modified | Adds git-version parsing/floor/absence/unreadable cases, real-repo bare/trap/single-checkout/supported-layout cases, CLI cases, cwd invariance and read-only purity. |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.43ms` (frozen lock consistent) |
| Build | `uv run --frozen aidw gate run build --ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv build --out-dir <tmp>` | ✅ `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` built (gate `build`, tree `da69c6f63f93`, stage `record-implementation-results`, 2026-11-03T01:16:26Z) |
| Test | `uv run aidw gate run suite --ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts -- uv run --frozen pytest` | ✅ `810 passed in 19.40s` (gate `suite`, tree `32a447124dbe`, stage `pr`, 2026-11-03T01:20:40Z) |
| Doctor | `uv run --frozen aidw doctor` | ✅ exit 0 — 18 checks: 0 failed, 2 warnings (dirty working tree; missing `.mcp.json`); `git version`, `repo root`, `workspace root`, `state root`, `control worktree` all OK |
| Agents validate | `uv run --frozen aidw agents validate --strict` | ✅ exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ exit 0 — `prompts check: 0 error(s), 0 warning(s)` |
| Whitespace | `git diff --check` | ✅ exit 0, no whitespace errors |
| Lint | — | **unverified** — the repository configures no linter/formatter (`AGENTS.md` §Gates: pytest is the only verification; none is added inside an unrelated task) |

### `uv run --frozen pytest` (full suite)

Every row is derived from the single full-suite gate invocation above; per-file counts come from `uv run --frozen pytest --collect-only -q` (collection only — no test was re-run).

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 810 | ✅ Pass (`810 passed in 19.40s`) |
| `tests/test_doctor.py` | 35 | ✅ Pass (35 passed as part of the full-suite run) |
| `tests/test_layout.py` | 26 | ✅ Pass (part of the full-suite run) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| git ≥ 2.31 floor: above/at floor OK, below floor FAIL naming the floor and binary, absent FAIL, unreadable `--version` FAIL path (WARN) | ❌ The `version_exit=1` WARN case passed; the successful-but-unparseable-output case failed — `_parse_git_version("git release unknown")` returns `None`, and `_check_git_version` returns `OK` with "unknown version" instead of `WARN`. Other four git-version tests passed. |
| git floor checked outside any repository (environment group, before the target early-return) | ✅ `test_git_version_is_checked_outside_a_repository` passed |
| Bare target: "target repo" FAIL naming the bare layout and the §3.2 `worktree add` bootstrap, reachable via `--repo` and `AIDW_REPO` | ✅ `test_bare_target_fails_by_name_with_the_bootstrap`, `test_bare_target_is_reachable_through_the_app_level_repo_option`, `test_bare_target_is_reachable_through_aidw_repo_environment` passed |
| Clone-of-a-worktree trap and its linked child: "control worktree" FAIL, exit non-zero, no state-root WARN | ✅ `test_trap_clone_fails_the_control_worktree_check`, `test_trap_linked_child_fails_the_control_worktree_check` passed |
| CLI (`CliRunner`): `["--repo", <bare>, "doctor"]` exits 1 naming the bare layout; `["doctor"]` in a trap exits 1 naming "registered worktree" | ✅ `test_bare_target_is_reachable_through_the_app_level_repo_option` and `test_cli_doctor_from_the_trap_clone_exits_non_zero` / `test_cli_doctor_from_the_trap_linked_child_exits_non_zero` passed |
| Single-checkout clone: state-inside-tree WARN naming both paths, exit 0 | ✅ `test_single_checkout_warns_on_the_state_root_and_exits_zero` passed |
| Supported bare + worktree layout: five new checks OK, no warnings | ✅ `test_supported_layout_reports_the_new_checks_ok_from_each_worktree` passed |
| Purity: repo-dependent checks leave `git status` and the worktree list unchanged and create no `.aidw/state` under the worktree | ✅ `test_repo_checks_leave_git_state_and_the_state_root_untouched` passed |
| Verdict invariant to the working directory | ✅ `test_verdict_is_invariant_to_the_working_directory` passed |
| `uv run aidw doctor` in the supported/plain-checkout dev clone stays green | ✅ exit 0, 18 checks, 0 failed; five new checks OK (live run above) |

---

## Deviations observed during recording

- **Task-specific CLI scenarios were not re-run as standalone shell commands** — they are exercised by the single full-suite gate above (the "Done when" subset), so no test was executed twice. The live `uv run aidw doctor` run covers the current checkout only.
- **`uv run aidw --repo <bare> doctor` / trap / supported-layout shell runs were not executed separately** — their behaviour is covered by the passing `CliRunner` and real-fixture tests from the same suite run; they were not re-run here to avoid duplicating the gate.
- **No lint gate exists** — the repository configures no linter (per `AGENTS.md`), so the row is marked unverified rather than invented.

---

## Non-Goals (NOT implemented)

- ❌ E3.5 `aidw/config.yaml` validation in doctor (`docs/task-prompts/00-E2.8-prompt.md`, non-goals).
- ❌ E8.3 toolkit-version reporting (`aidw --version`, doctor version/compat status) (`docs/task-prompts/00-E2.8-prompt.md`, non-goals).
- ❌ A doctor check for lock health/leftovers — deferred by E2.7 (`docs/task-prompts/00-E2.8-prompt.md`, non-goals).
- ❌ A "main control worktree must exist" check — not a rejected layout in §3.2 (`docs/task-prompts/00-E2.8-prompt.md`, non-goals).
- ❌ E2.9 shared worktree fixture — local real-repo fixtures are used instead (`docs/task-prompts/00-E2.8-prompt.md`, non-goals).
- ❌ No commit, push, or PR opened — this document predates the delivery stage (`prompts/pr.md` owns delivery).
