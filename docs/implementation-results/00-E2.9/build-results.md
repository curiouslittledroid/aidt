# Build Results — 00-E2.9: Worktree fixtures

**Branch:** `00-E2.9`
**Date:** 2026-11-03
**Spec:** `docs/migration/EXTRACTION.md` §3.2, §3.12; `design.md` §15; `AGENTS.md` (Tests)

## Summary

**Purpose:** Add a shared, function-scoped pytest fixture that builds the §3.2 supported layout — a temporary bare repo with sibling `main` (control) and `task` worktrees — so E2 and later epics test against real git wiring instead of each module's private copy.

| Decision | Why it matters |
|----------|---------------|
| `WorktreeRepo` is an immutable dataclass exposing `bare`, `control`, `task`, `workspace`, plus `add_task(branch, *, base="main")` | Later epics need the paths, not a helper they must re-derive. The dataclass keeps the layout explicit and the fixture name/container name are prompt-fixed (the spec fixes the layout, not the naming). |
| `add_task` runs §3.2's per-task `git worktree add -b <branch> <path> <base>` from the **control** worktree and raises `subprocess.CalledProcessError` on refusal | Mirrors `aidw.git.add_worktree`'s position; a silent `None` would let a test pass while asserting nothing. `add_task("task")` therefore always raises — the pre-created worktree is `repo.task`. |
| The seed is committed (`git init -b main` + file + commit) before `git clone --bare` | An empty `git init` has no `main` ref, so `worktree add ../main main` fails with "invalid reference". |
| Identity comes from the existing session-wide `_git_identity` environment; no per-repo `git config user.*` | Two spawns × ~300 temporary repos is exactly the cost AGENTS.md measured out. |
| Function-scoped on `tmp_path`, no `git worktree remove` teardown | Everything sits under `tmp_path`; pytest removes it. A session-scoped bare repo with registered worktrees would leak checkouts, and explicit teardown spawns are pure cost. Nothing is written outside `tmp_path`, so `_clean_test_runs` stays green. |
| Migrated tests use `repo.task` for the pre-created branch and `repo.add_task` only for *additional* branches (`feat`, `other`) | Git refuses a second checkout of an already-checked-out branch; re-adding `task` is the collision the fixture surfaces. |

**Where it fits in the roadmap:** E2.9 in the extraction epic, the test-infrastructure follow-on to E2.3 (`aidw worktree`), E2.4/E2.6 (worktree resolution) and E2.8 (doctor layout checks). Later E2 work and E4/E5 integration tests consume the fixture; E2.8's `test_doctor.py` and `test_git.py` keep their own local helpers, and `fixtures/target-repo/` (§3.12) stays a separate static asset.

**Scope:** `tests/conftest.py` gains `_git_run`, `WorktreeRepo` and the `worktree_repo` fixture. `tests/test_layout.py` and `tests/test_worktree_cli.py` migrate every user of their local supported-layout helpers and delete those helpers (`_make_supported`; `_make_bare_with_control`, `_make_bare`, `_init_committed_repo`, `_add_task`). A new `tests/test_worktree_fixture.py` specifies the fixture contract. `tests/test_doctor.py` and `tests/test_lock.py` only update their module docstrings. It deliberately stops short of converting the rejected/single-checkout layouts (`_make_trap`, `_make_plain_clone`, `test_layout.py::_make_bare`), converting `test_git.py` (including its same-shaped `_make_bare_with_control`), building `fixtures/target-repo/`, or writing any E4/E5 integration test.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E2.9-prompt.md` | Created | Task prompt committed on the branch. |
| `tests/test_worktree_fixture.py` | Created | Contract tests for the fixture: bare/control/task wiring, `common_dir`/workspace root from every position, `add_task` creation/base/collision paths, guard acceptance, purity and a metamorphic listing check. |
| `tests/conftest.py` | Modified | Adds `_git_run`, the `WorktreeRepo` dataclass with `add_task`, and the function-scoped `worktree_repo` fixture built from a committed seed → bare clone → `main` → `task`; docstring updated. |
| `tests/test_layout.py` | Modified | Supported-layout tests take `worktree_repo` and use `repo.control` / `repo.task`; deletes `_make_supported`; keeps `_make_bare`, `_make_trap`, `_make_plain_clone` local; docstring updated. |
| `tests/test_worktree_cli.py` | Modified | All supported-layout tests take `worktree_repo`; deletes `_make_bare_with_control`, `_make_bare`, `_init_committed_repo`, `_add_task`; docstring updated. |
| `tests/test_doctor.py` | Modified | Module docstring only: explains why its repo fixtures stay local. |
| `tests/test_lock.py` | Modified | Module docstring only: points at the shared fixture's layout. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E2.9 complete. |

---

## Verification Results

### Top-level verification

Every gate below was recorded once against tree `946a89d0b8d8` by stage `record` with the scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`. No gate was reused from another stage or run.

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ `Checked 15 packages in 0.46ms` (frozen lock consistent) |
| Build | `aidw gate run build $SCOPE --stage record -- uv build --out-dir <tmp>` | ✅ `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` built (gate `build`, tree `946a89d0b8d8`, stage `record`, 2026-11-03T02:33:44Z) |
| Test | `aidw gate run suite $SCOPE --stage record -- uv run --frozen pytest` | ✅ `827 passed in 23.72s` (gate `suite`, tree `946a89d0b8d8`, stage `record`, 2026-11-03T02:33:17Z) |
| Doctor | `aidw gate run doctor $SCOPE --stage record -- uv run --frozen aidw doctor` | ✅ exit 0 — 18 checks: 0 failed, 2 warnings (dirty working tree; missing `.mcp.json`) (gate `doctor`, tree `946a89d0b8d8`, stage `record`, 2026-11-03T02:33:21Z) |
| Agents validate | `aidw gate run agents-validate $SCOPE --stage record -- uv run --frozen aidw agents validate --strict` | ✅ exit 0 — `11 agent config(s): 0 error(s), 0 warning(s)` (gate `agents-validate`, tree `946a89d0b8d8`, stage `record`, 2026-11-03T02:33:23Z) |
| Prompts check | `aidw gate run prompts-check $SCOPE --stage record -- uv run --frozen aidw prompts check` | ✅ exit 0 — `prompts check: 0 error(s), 0 warning(s)` (gate `prompts-check`, tree `946a89d0b8d8`, stage `record`, 2026-11-03T02:33:25Z) |
| Whitespace | `git diff --check` | ✅ exit 0, no whitespace errors |
| Lint | — | **unverified** — the repository configures no linter/formatter (`AGENTS.md` "Gates": pytest is the only verification; none is added inside this task) |

### `uv run --frozen pytest` (full suite)

Every row is derived from the single full-suite gate invocation above. Per-file counts are collection-only (`pytest --collect-only -q`, which executes no test); the full run reported no failures, deselections or skips.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 827 | ✅ Pass (`827 passed in 23.72s`) |
| `tests/test_worktree_fixture.py` | 14 | ✅ Pass (part of the full-suite run) |
| `tests/test_layout.py` | 26 | ✅ Pass (part of the full-suite run) |
| `tests/test_worktree_cli.py` | 25 | ✅ Pass (part of the full-suite run) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `uv run --frozen pytest tests/test_worktree_fixture.py tests/test_layout.py tests/test_worktree_cli.py` | ✅ `65 passed in 3.66s` (gate `worktree-fixture`, tree `946a89d0b8d8`, stage `record`, 2026-11-03T02:33:34Z) — equals 14 + 26 + 25 collected in those files |
| Fixture contract: `bare` is bare, `control`/`task` are linked worktrees (`.git` is a file into `<bare>/worktrees/<name>`), all three are siblings | ✅ `test_bare_is_a_bare_repository_and_never_a_target`, `test_control_and_task_are_linked_worktrees_pointing_into_the_bare_repo` passed |
| `aidw.git.common_dir` from `control` and `task` resolves to `bare`; workspace root is the sibling folder | ✅ `test_common_dir_and_workspace_root_are_the_bare_repo_from_every_position` passed |
| `task`'s branch is `task` off `main` | ✅ `test_task_worktree_holds_the_task_branch_off_main` passed |
| `add_task("task")` raises (branch already checked out) and leaves the listing and worktree untouched | ✅ `test_add_task_raises_when_the_pre_created_branch_is_requested` passed |
| `add_task` collision for an existing branch and for an occupied target path raises, writing nothing | ✅ `test_add_task_raises_for_an_existing_branch_that_is_not_checked_out`, `test_add_task_raises_when_the_target_path_is_occupied` passed |
| `add_task("feat")` creates a sibling worktree, registers it in the bare repo, and grows the listing by exactly one | ✅ `test_add_task_creates_a_sibling_worktree_on_the_new_branch`, `test_add_task_changes_the_listing_by_exactly_one_entry` passed |
| `base` is discriminated: `add_task("child", base="dev")` after advancing `main` is an ancestor of `dev` and not of `main` | ✅ `test_add_task_base_is_discriminated_not_merely_accepted` passed |
| Listing is exactly the control and task worktrees; the bare dir is never an entry | ✅ `test_fixture_listing_is_exactly_the_control_and_task_worktrees` passed |
| Fixture layout passes `check_layout` from each worktree | ✅ `test_fixture_layout_passes_the_guard_from_each_worktree` passed |
| Purity/cleanup: clean `git status`, unchanged worktree list, no `.aidw/state` under `tmp_path` after use | ✅ `test_fixture_workspace_is_clean_and_carries_no_run_state`, `test_using_the_fixture_leaves_it_clean_and_unchanged` passed |
| ≥3 test functions across ≥2 modules take `worktree_repo` | ✅ 38 `def test_` signatures take the fixture across `tests/test_worktree_cli.py` (19), `tests/test_worktree_fixture.py` (14) and `tests/test_layout.py` (5) |
| Replaced helpers deleted; retained helpers kept | ✅ `rg` finds no `_make_supported` in `tests/test_layout.py` and none of `_make_bare_with_control` / `_make_bare` / `_init_committed_repo` / `_add_task` in `tests/test_worktree_cli.py`; `tests/test_layout.py::_make_bare`, `_make_trap`, `_make_plain_clone` and every `tests/test_git.py` helper remain |
| No added `git config user.*` or `git worktree remove` spawns | ✅ `rg -n "git config user\|worktree remove" tests/` finds only the pre-existing `tests/conftest.py` comment and docstrings in `tests/test_worktree_cli.py` / `tests/test_workspace_paths.py`; the change adds none |
| Tests-only change: `aidw/`, `prompts/`, `agent-configs/` untouched | ✅ `git status --short` and `git diff --stat main` list only docs and `tests/` paths |

---

## Deviations observed during recording

- **The prompt's `pnpm install` / `pnpm -r lint|build|test` commands do not apply** — this repository is Python/uv (`pyproject.toml`, `uv.lock`), so the gates recorded are the ones `AGENTS.md` and `prompts/pr.md` name for this stack: `uv sync --frozen`, `uv build`, `uv run --frozen pytest`, `aidw doctor`, `aidw agents validate --strict`, `aidw prompts check`.
- **The task prompt's focused pytest command was run once through its own gate** (`worktree-fixture`) rather than derived from the full-suite run; per-file counts in the suite table come from collection only, so no test was executed twice.
- **No lint row exists** — no linter is configured, so the row is marked unverified rather than invented.
- **The working tree is uncommitted** — earlier stages left the change set on `00-E2.9` uncommitted; gating measured the working tree relative to `main`, and this document records that tree.

---

## Non-Goals (NOT implemented)

- ❌ E2.8's doctor checks or any other E2 task — this task owns only the fixture and its adoption (`docs/task-prompts/00-E2.9-prompt.md`, non-goals).
- ❌ `fixtures/target-repo/`, the static fixture target repo for E4/E5 integration tests (§3.12) (`docs/task-prompts/00-E2.9-prompt.md`, non-goals).
- ❌ Converting any helper beyond the two consumer modules into the shared fixture — `_make_trap`, `_make_plain_clone`, `test_layout.py::_make_bare`, `test_git.py` in full (including its same-shaped `_make_bare_with_control`), and every other module's local copy (`docs/task-prompts/00-E2.9-prompt.md`, non-goals).
- ❌ E4/E5 integration tests that consume the fixture (`docs/task-prompts/00-E2.9-prompt.md`, non-goals).
- ❌ No commit, push, or PR opened — `prompts/pr.md` owns delivery (`prompts/record-implementation-results.md`, non-goals).
