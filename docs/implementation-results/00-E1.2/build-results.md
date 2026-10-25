# Build Results — 00-E1.2: `ToolkitPaths` (E1.2)

**Branch:** `00-E1.2`
**Date:** 2026-10-26
**Spec:** `docs/migration/EXTRACTION.md` §3.1 (Two roots), §3.3 (CLI surface — the `aidw doctor` "toolkit root" extension), §3.12 (New repo layout). Roadmap: `docs/tasks/00 - Extraction.md` Epic E1, task E1.2.

## Summary

**Purpose:** Formalise the toolkit-root resolution into a `ToolkitPaths` type exposing `root`, `prompts_dir`, `agent_configs_dir`, `agents_dir` and `scripts_dir`, and make `aidw doctor` report the toolkit root even when invoked from a non-repository cwd such as `/tmp`.

| Decision | Why it matters |
|----------|---------------|
| `ToolkitPaths` is a distinct frozen dataclass from `TargetRepo`, constructed via the classmethod `ToolkitPaths.resolve()` | §3.1 requires toolkit-relative and target-relative paths never to be interchangeable; two distinct types (not a shared `root: Path`) enforce that at the type level |
| `resolve()` delegates `root` to the existing `toolkit_root()` (`Path(__file__).resolve().parent.parent`) | `toolkit_root()` stays the single source of truth; `ToolkitPaths` never re-derives it and never consults git or the cwd |
| `scripts_dir = prompts_dir / "scripts"`, not `root / "scripts"` | Matches §3.1/§3.12 and `inventory.REQUIRED_SCRIPTS`, which are relative to `prompts_dir`; a `root/scripts` directory does not exist |
| The doctor "toolkit root" check is added to the first checks list, *before* the `repo_root()` try/except | `collect_checks()` returns early on `RepoNotFoundError`; placing the check before that branch is what makes it report from `/tmp` |
| Check status is pinned to the `OK`/`WARN`/`FAIL` contract: `FAIL` when resolution fails, `root` is missing, or `prompts`/`scripts` is missing; `WARN` when only `agent-configs`/`agents` is missing | `FAIL` is a blocker per the `doctor.py` header; the workflow-critical assets (`prompts`, `scripts`) must not be hidden, mirroring the existing `prompts` check (FAIL) and `agent configs` check (WARN) |
| `toolkit_root()`, `aidt_root()` and `runs_dir()` are left behaviourally unchanged | E1.4 owns deleting the two transitional aliases and porting their call sites; `tests/test_paths.py` pins their behaviour and stays green unmodified |
| Direct `ToolkitPaths(root=…)` construction is a call-site convention, not an enforced invariant | Requirement 1 pins the `TargetRepo`-mirroring shape (plain frozen dataclass, no init guard); the `rg` call-site guard lives in the Done-when, not the suite |

**Where it fits in the roadmap:** Task E1.2 in Epic E1 ("Two-root core") of the AIDT extraction. It builds on E0.4 (minimal toolkit-root resolution, `toolkit_root()`) and E1.1 (`TargetRepo`). E1.3 (workspace/state root), E1.4 (port consumers, delete `aidt_root()`/`runs_dir()`, rewrite `test_paths.py`) and E1.5 (CLI plumbing that threads `ToolkitPaths`/`TargetRepo` through workflows) build on this type. The task prompt explicitly reconciles the roadmap's "installed (non-repo, `uv tool install`) case" note: `pyproject.toml` ships only the `aidw` package, so the sibling asset dirs do not exist in an installed venv — only the cwd/git-independent half is covered here, and the installed-wheel asset layout stays E8.1's.

**Scope:** Additive changes to `aidw/paths.py` (the `ToolkitPaths` type) and `aidw/doctor.py` (the `_check_toolkit_root` check wired into `collect_checks()`), a new contract-test module `tests/test_toolkit_paths.py`, plus the roadmap checkbox. It deliberately stops short of porting consumers, deleting the transitional aliases, CLI plumbing, packaging changes and workspace/state-root work.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `aidw/paths.py` | Modified | Added the frozen `ToolkitPaths` dataclass (`root`, four asset dirs) with `resolve()` delegating `root` to `toolkit_root()`; module docstring updated to reflect E1.2 landing. `toolkit_root()`, `aidt_root()` and `runs_dir()` behaviour unchanged |
| `aidw/doctor.py` | Modified | Added `_check_toolkit_root()` and inserted it into the first `collect_checks()` list before the `repo_root()` try/except; import updated to include `ToolkitPaths` |
| `tests/test_toolkit_paths.py` | Created | 20 contract tests: cwd-independence, depth-invariance, no-git/no-subprocess resolution, dir derivation against the real shipped assets, exact five-field shape, purity/frozen-ness, type distinctness from `TargetRepo`, and doctor reporting (`OK` from a non-repo cwd, `FAIL`/`WARN` for missing assets, fail-closed on resolution errors) |
| `docs/tasks/00 - Extraction.md` | Modified | Marked roadmap task E1.2 done (`[ ]` → `[x]`) |
| `docs/task-prompts/00-E1.2-prompt.md` | Created | Task prompt authored for E1.2 through the toolkit (planning-stage artifact, committed in the branch's first two commits) |

---

## Changes Made

### 1. `aidw/paths.py`

- **`ToolkitPaths`** — a frozen dataclass with exactly `root: Path`, `prompts_dir: Path`, `agent_configs_dir: Path`, `agents_dir: Path`, `scripts_dir: Path`. Deliberately a distinct type from `TargetRepo`; like `TargetRepo` it carries no init guard, so `resolve()` is a call-site convention rather than an enforced invariant.
- **`ToolkitPaths.resolve()`** — delegates `root` to `toolkit_root().resolve()`, then derives `prompts_dir = root/"prompts"`, `agent_configs_dir = root/"agent-configs"`, `agents_dir = root/"agents"` and `scripts_dir = prompts_dir/"scripts"`, all `.resolve()`d. It never consults `repo_root()`, git or the cwd.
- **`toolkit_root()`** — body unchanged (`Path(__file__).resolve().parent.parent`); docstring notes it is the single source of truth that `resolve()` delegates to. `aidt_root()` and `runs_dir()` are unchanged.

### 2. `aidw/doctor.py`

- **`_check_toolkit_root()`** — resolves via `ToolkitPaths.resolve()`. Returns `Check("toolkit root", …)`: `FAIL` with `"unresolved: <exc>"` if resolution raises; otherwise collects missing dirs in the order prompts, scripts, agent-configs, agents (plus `root` if the root itself is absent); `FAIL` when any of `root`/`prompts`/`scripts` is missing, `WARN` when only `agent-configs`/`agents` is, `OK` when all exist. Detail is the resolved root, suffixed with `(missing: …)` when applicable.
- **`collect_checks()`** — `_check_toolkit_root()` appended to the first checks list, with a comment recording that it must precede the `repo_root()` try/except whose early return would otherwise skip it.

### 3. `tests/test_toolkit_paths.py`

- Builds no external repositories: it resolves the real in-checkout layout. Uses `monkeypatch.chdir` into unrelated `tmp_path`s to prove cwd-independence and depth-invariance, and monkeypatches `aidw.paths.repo_root`/`aidw.paths.subprocess` to prove resolution never reaches for git or a subprocess.
- Asserts the four dirs point at real shipped assets (`prompts/task-prompt.md`, `agent-configs/*.yaml`, `agents/` subdirectories, `prompts/scripts/review-followup`), and pins the exact five-field shape and frozen-ness.
- Doctor tests patch `aidw.paths.toolkit_root` (the delegation target) into synthetic roots to exercise `OK`/`WARN`/`FAIL` and the fail-closed resolution path, and assert the `"toolkit root"` check is ordered before `"repo root"` when the latter is `FAIL`.

---

## Verification Results

### Top-level verification

The toolkit repository is a Python/uv project: `.github/workflows/ci.yml` runs `uv sync --frozen`, `uv run --frozen pytest` and `uv run --frozen aidw doctor`. The template's `pnpm` commands do not apply — there is no `package.json`, `pnpm-workspace.yaml` or `pnpm-lock.yaml` in this repository. Both sets of rows are recorded below.

| Step | Result |
|------|--------|
| `uv sync --frozen` (install gate) | ✅ `Checked 13 packages in 9ms` (exit 0) |
| `uv build --out-dir <tmpdir>` (build gate) | ✅ Built `aidt-0.1.0.tar.gz` and `aidt-0.1.0-py3-none-any.whl` (exit 0); output written to a temp dir, repo tree untouched |
| `uv run --frozen pytest` (test gate) | ✅ `338 passed in 48.79s` (exit 0) |
| `uv run --frozen aidw doctor` (from toolkit root) | ✅ `14 checks: 0 failed, 2 warning(s)` (exit 0) — warnings are the dirty working tree and a missing `.mcp.json`, both expected/pre-existing |
| `pnpm install` | N/A — no pnpm project in this repository |
| `pnpm -r lint` | N/A — no linter or lint script is configured in this repository |
| `pnpm -r build` | N/A — see `uv build` above |
| `pnpm -r test` | N/A — see `uv run --frozen pytest` above |

### `uv run --frozen pytest` (full suite)

Full-suite total: **338 passed in 48.79s**. Files named in the task prompt's done-when:

| Test file | Tests | Result |
|-----------|-------|--------|
| `tests/test_toolkit_paths.py` | 20 | ✅ Pass |
| `tests/test_paths.py` (unmodified) | 6 | ✅ Pass |
| `tests/test_doctor.py` (unmodified) | 10 | ✅ Pass |
| whole suite (`tests/` + `prompts/scripts/review-followup/tests/`) | 338 | ✅ Pass |

No test file failed, errored or was skipped.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| `cd /tmp && uv run --project <toolkit-root> --frozen aidw doctor` | ✅ Prints `[  ok  ] toolkit root  /Users/phil/software-projects/aidt` naming the resolved root; `[ fail ] repo root  Not inside a git repository …` as expected in a non-repo cwd. Command exits 1 because of the `repo root` FAIL, which the done-when explicitly permits; `9 checks: 1 failed, 0 warning(s)` |
| `rg 'ToolkitPaths\(' aidw/ tests/` | ✅ No matches (exit 1) — zero direct field constructions; every construction goes through `ToolkitPaths.resolve()` (`resolve()` itself builds via `cls(…)`, which does not match the pattern) |
| `rg -n "repo_root\(\)" aidw/` | ✅ Matches are only the two pre-task call sites (`aidw/cli.py:58`, `aidw/doctor.py:310`) plus two docstrings/comments mentioning it (`aidw/doctor.py:259`, `aidw/doctor.py:304`); no new `repo_root()` call added |
| `rg -n 'def (toolkit_root\|aidt_root\|runs_dir)' aidw/paths.py` | ✅ All three definitions present and unchanged: `toolkit_root` (line 162), `aidt_root` (215), `runs_dir` (220) |
| `tests/test_paths.py`, `tests/test_doctor.py` green unmodified | ✅ 6 and 10 passed respectively; `git status` confirms neither file was touched |
| In-process doctor proof: `test_doctor_reports_toolkit_root_from_a_non_repo_cwd` | ✅ `"toolkit root"` is `OK` with the resolved root in its detail, `"repo root"` is `FAIL`, and `"toolkit root"` is ordered before `"repo root"` |
| Fail-closed doctor proof: missing-asset and resolution-error tests | ✅ `FAIL` with `(missing: prompts, scripts, agent-configs, agents)` / `(missing: root, …)`, `WARN` when only advisory dirs are missing, `FAIL` `"unresolved: …"` when `toolkit_root()` raises |
| `git diff --check` | ✅ Clean (exit 0) |

---

## Non-Goals (NOT implemented)

- ❌ E1.4 (port consumers, delete `aidt_root()`/`runs_dir()`, rewrite `test_paths.py`) and E1.5 (CLI plumbing: threading `ToolkitPaths`/`TargetRepo` through workflows) — separate tasks (task prompt, Explicit non-goals)
- ❌ E1.3 workspace/state root — separate task (task prompt, Explicit non-goals)
- ❌ E8.1 packaging: shipping `prompts/`/`agent-configs/`/`agents/` in the wheel and the `uv tool install` asset layout; `pyproject.toml` and the hatch build config were not touched (task prompt, Explicit non-goals)
- ❌ No commit, push or pull request — this recording stage owns only this document (`prompts/record-implementation-results.md`)
