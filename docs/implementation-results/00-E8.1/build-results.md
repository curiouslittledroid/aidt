# Build Results — E8.1: Installable package

**Branch:** `00-E8.1`
**Date:** 2026-11-06
**Spec:** `docs/migration/EXTRACTION.md` §2 (D7 name `aidt` / import + CLI `aidw`; D9 distribution; D21 dogfood + CI), §3.1 (two roots), §3.12 (new repo layout, wheel targets)

## Summary

**Purpose:** Make the wheel an actually installable distribution — code *and* the three runtime asset dirs — so that `uv tool install <path>` followed by `aidw doctor` succeeds from a directory unrelated to any git repository (D9's primary form, the roadmap's Done-when predicate).

| Decision | Why it matters |
|----------|---------------|
| Bundle `prompts/`, `agent-configs/`, `agents/` with `[tool.hatch.build.targets.wheel.force-include]` mapping each repo-root dir onto itself | The assets are §3.12 siblings of `aidw/`; forcing them to the wheel root (site-packages) reproduces the checkout layout, so `aidw/paths.py:toolkit_root()` = `Path(__file__).parent.parent` stays correct in both layouts with **no** `paths.py` change. |
| Keep the asset set to exactly those three dirs; exclude `tests/`, `docs/`, `design.md`, `uv.lock`, `.github/` | Only runtime assets are needed by `doctor`/`prompts`; `README.md` stays wheel *metadata* via `readme = "README.md"` rather than payload. |
| Do **not** move assets inside `aidw/` and resolve them with `importlib.resources` | §3.1 lists that as an alternative mechanism, not a mandate to relocate; §3.12 fixes the repo-root layout, and relocating would break the checkout layout and `tests/test_toolkit_paths.py`. |
| Add `hatchling>=1.33` to `[dependency-groups] dev` and re-sync `uv.lock` | `tests/test_packaging.py` builds with `uv build --no-build-isolation`, so the backend must already be in the locked env: `uv run --frozen pytest` is offline and default build isolation would need the network (there were zero hatchling entries in `uv.lock` before). |
| Prove bundling through `aidw doctor`'s `toolkit root` check plus direct wheel/sdist inspection | `_check_toolkit_root` FAILs with `missing: prompts, scripts, agent-configs, agents` when the force-include table is absent — it is the observable bug this task exists to prevent. |

**Where it fits in the roadmap:** Epic E8 (packaging, distribution, versions) under D9/D21. It builds on the extraction work that produced the repo-root layout (`aidw/` package plus `prompts/`, `agent-configs/`, `agents/` siblings) and on D7's name settlement (repo/distribution `aidt`, import package and CLI `aidw`). E8.2 (identity in `state.json`), E8.3 (`aidw --version`), E8.4 (README install paths including `uvx`), and E8.5 (release process and the first tag) all sit downstream of a wheel that actually ships its assets.

**Scope:** `pyproject.toml` (force-include table, dev-group `hatchling`, explanatory comments), the re-synced `uv.lock`, a new `tests/test_packaging.py` contract/property suite, and the E8.1 checkbox in the roadmap. Install verification is the local-path form required before any tag exists: `uv tool install <worktree>` into a clean tool venv, then `aidw doctor` from `/tmp`. It deliberately stops short of a release tag, any push, README install documentation, and any version-reporting surface.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `tests/test_packaging.py` | Created | Builds the sdist and wheel (offline, `--no-build-isolation`) into a tmp dir and asserts the bundled assets, `REQUIRED_SCRIPTS` coverage, `entry_points.txt`, and the Requirement 3 exclusion list; also asserts the `toolkit root` doctor shape for a bundled vs. unbundled unpack. |
| `pyproject.toml` | Modified | Adds `[tool.hatch.build.targets.wheel.force-include]` for `prompts/`, `agent-configs/`, `agents/` and `hatchling>=1.33` to the dev dependency group, with citations to E8.1/§3.12. |
| `uv.lock` | Modified | Re-synced for the new dev-group dependency so `uv sync --frozen` provisions `hatchling` (frozen-lock convention). |
| `docs/tasks/00 - Extraction.md` | Modified | Marks the E8.1 roadmap item complete. |
| `docs/task-prompts/00-E8.1-prompt.md` | Created | The task prompt for this task (committed on the branch). |

---

## Verification Results

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.88ms`; `hatchling` importable from the project venv) |
| Build | `uv build --no-build-isolation --out-dir $(mktemp -d)` | ✅ Pass (`Successfully built …/aidt-0.1.0.tar.gz` and `…/aidt-0.1.0-py3-none-any.whl`; "Building wheel from source distribution") |
| Test | `uv run --frozen pytest` | ✅ Pass (`1822 passed in 27.01s`) |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (exit 0, `19 checks: 0 failed, 2 warning(s)` — warnings are the dirty working tree and a missing `.mcp.json`) |
| Agent configs | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`) |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (`resolved repo prompts: 0 error(s), 0 warning(s)`, 12 prompts resolved to toolkit defaults) |
| Whitespace | `git diff --check` | ✅ Pass (no output, exit 0) |
| Lint | — (none configured) | **unverified** — the repo configures no linter, formatter or type-checker (`AGENTS.md` "Gates", `design.md` §15); `pytest` is the only verification, so there is no lint command to run |

Gate records from this run (`aidw gate run --stage record`, scope `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`):

| Gate key | Outcome |
|----------|---------|
| `build` | ✅ `passed: gate 'build' passed for tree a535fd8c6401 at 2026-11-06T02:16:15Z by stage 'record'` (ran here) |
| `suite` | ✅ `passed: gate 'suite' passed for tree a535fd8c6401 at 2026-11-06T02:16:44Z by stage 'record' (1822 passed in 27.01s)` (ran here) |

Both gates were executed by this stage against the current tree (`a535fd8c6401`), not reused from an earlier stage.

### `uv run --frozen pytest` (full suite)

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1822 | ✅ Pass (`1822 passed in 27.01s`) |
| `tests/test_packaging.py` | 23 | ✅ Pass (count from `--collect-only` against the same tree; all 23 executed inside the full-suite run above — not re-run here) |
| `tests/test_toolkit_paths.py` | 20 | ✅ Pass (unchanged regression guard for the `toolkit_root()` layout; count from `--collect-only`, executed inside the full-suite run) |

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Wheel payload inspection (`zipfile`, wheel from this run) | ✅ 104 entries; contains `prompts/task-prompt.md`, all 11 `prompts/scripts/review-followup/*.py` entries (including `publish_review_followups.py` and `review_followup.py`), 11 `agent-configs/` entries, 12 `agents/` entries; `aidt-0.1.0.dist-info/entry_points.txt` declares `aidw = aidw.cli:main`; no top-level `tests/`, `docs/`, `design.md`, `uv.lock` or `.github/` payload entries, and no `README.md` payload file |
| Sdist payload inspection (`tarfile`, sdist from this run) | ✅ Carries `prompts/`, `agent-configs/` and `agents/*/AGENTS.md` (hatchling's git-tracked default), which is what lets the wheel built *from* the sdist find the force-included dirs |
| Clean tool venv install: `UV_TOOL_DIR=$(mktemp -d) UV_TOOL_BIN_DIR=$(mktemp -d) uv tool install /Users/phil/software-projects/aidt-workspace/00-E8.1` | ✅ Pass (`Installed 10 packages`, `+ aidt==0.1.0 (from file://…/00-E8.1)`, `Installed 1 executable: aidw`; `packaging`/`pyyaml`/`typer` resolved from PyPI into the fresh venv, not the dev `.venv`) |
| `cd /tmp && aidw doctor` from the installed tool (Done-when predicate) | ✅ Pass in the exact required shape: exit code `1`; `repo root` = FAIL (`Not inside a git repository (started at /private/tmp)`); `toolkit root` = OK with detail `/private/var/folders/…/tmp.KpzQruJGBe/aidt/lib/python3.14/site-packages` and no `missing:` suffix; `10 checks: 1 failed, 0 warning(s)` |
| Conditional extra: `uv tool install "git+$(git remote get-url origin)@<ref>"` | **unverified** — the branch is not on `origin` (`git ls-remote --heads origin 00-E8.1` returns nothing, HEAD `24c5281` is local-only); Requirement 6 forbids pushing the branch or any ref to make it runnable, and `/pr` owns the delivery step. The `@<tag>` form is first exercised by E8.5. |

---

## Deviations observed during recording

- **No lint command exists to gate** — the repo's gate list (`AGENTS.md`) has no lint stage and `design.md` §15 states `pytest` is the only verification, so no `lint` gate was run or recorded; the row is marked unverified rather than passed.

---

## Non-Goals (NOT implemented)

- ❌ E8.2 — `state.json` records `toolkit_version`, `schema_version`, config hash: no version/identity recording was added.
- ❌ E8.3 — `aidw --version`, doctor version/git/compat reporting: no version CLI output was added.
- ❌ E8.4 — README install paths incl. `uvx`, bare + worktree bootstrap: no README install section was written.
- ❌ E8.5 — release process + first tag: no tag was created, no release document was written, and no branch or ref was pushed.
- ❌ E9.x documentation rewrites: no doc edits beyond the packaging change and the E8.1 roadmap checkbox.
- ❌ No rename of the project (`aidt`) or import package/CLI (`aidw`), and no second version source or dynamic versioning.
- ❌ No `aidw/paths.py` change and no relocation of assets into `aidw/` (`importlib.resources`).
- ❌ No commit, push, or PR was made by this stage.
