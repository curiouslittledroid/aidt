# Build Results — E8.4: Install and worktree guide

**Branch:** `00-E8.4`
**Date:** 2026-11-06
**Spec:** `docs/migration/EXTRACTION.md` §3.2 (workspace and worktree model: supported layout, one-time bootstrap, verified git facts, rejected layouts, consequences), §2 (locked decisions D7 naming `aidt`/`aidw`, D9 distribution forms, D18 state location, D20 worktrees in scope); `design.md` §3 (repo layout authority for this checkout — `README.md` is repo-root, so the task adds README sections only)

## Summary

**Purpose:** Document how to install AIDT and how to lay out and bootstrap a workspace, so a reader copies the supported `bare.git` + sibling-worktree layout instead of producing the `clone-of-a-worktree` shape AIDT refuses to run on.

| Decision | Why it matters |
|----------|---------------|
| The two install forms are D9's literal commands, pinned to `@<tag>`, with `<tag>` explicitly marked as an E8.5-owned placeholder (and `baseline-verbatim` named as a non-release tag) | No release tag exists yet; a concrete tag would be invented, and a reader who copies one would get a resolution failure. The section points at a commit SHA as the reproducible pin until E8.5 cuts the first tag. |
| The `uvx` form is written as `uvx --from "git+…@<tag>" aidw` and the bare-`uvx` failure mode is spelled out beside it | Bare `uvx aidw` resolves a package named `aidw` from PyPI, which is not this repository; the `--from` argument is the whole reason the secondary form works. |
| Bootstrap is documented as two commands, `git clone --bare <remote> bare.git` then `git -C bare.git worktree add ../main main`, with the actual `origin` URL substituted | A normal `git clone` followed by `git worktree add` is exactly the clone-of-a-worktree trap: worktrees register in `main/.git`, so `dirname(git-common-dir)` is the clone folder and the state root lands in a prunable worktree (§3.2). Starting from `--bare` is what makes `bare.git` the common dir. |
| A separate "Task worktrees are created by AIDT" subsection draws the one-time/per-task line: the §3.2 per-task form is shown as what AIDT runs, plus the explicit "do not hand-run it, do not `git checkout -b`/`git switch -c` on `main`" | A reader who hand-runs the per-task `worktree add -b …` defeats the workflow AIDT owns (E2.4/E2.5), and a branch already checked out in `main/` cannot be checked out a second time. |
| The rejected-layout table uses the diagnostics that actually exist — `clone-of-a-worktree` (`aidw/layout.py:check_layout`) and the `workspace root` / `state root` / `control worktree` / `target repo` check names (`aidw/doctor.py`) — rather than invented vocabulary | Readers who hit a failure need the string they will see to find the fix; naming checks that do not exist would send them searching for the wrong output. |
| The git ≥ 2.31 minimum is tied to the command that needs it (`rev-parse --path-format=absolute`) and to `aidw doctor`'s `git version` check | The workspace root is derived from that exact invocation (§3.2 verified facts), so the layout genuinely does not work on older git, and doctor is where the failure surfaces. |

**Where it fits in the roadmap:** Epic E8 (packaging, distribution, versions) under D7/D9/D18/D20. It builds on E8.1's installable distribution (the install commands are the user-facing surface of it), on E8.2/E8.3's version-and-state reporting (the "smoke-check with `aidw doctor`" instruction and the "every run records the toolkit version in `state.json`" note), and on E2.4/E2.5 (AIDT-owned per-task worktree creation) and the E0.6 two-roots/naming section the new text must stay consistent with. E8.5 (release process, first tag) fills in the `@<tag>` placeholder, and E9.4 (full README rewrite, including retiring the "Interim state" note) rewrites the pre-extraction sections this task deliberately leaves untouched.

**Scope:** `README.md` only, as four new sections inserted before the existing "Repository, naming, and provenance" section: **Install** (D9's two forms, the tag placeholder, the `--from` requirement, the post-install `aidw doctor` smoke check, the git ≥ 2.31 requirement), **Workspace layout and bootstrap** (the §3.2 supported layout diagram, the two one-time bootstrap commands, the `--git-common-dir` verification, the git ≥ 2.31 rationale), **Task worktrees are created by AIDT** (the §3.2 per-task form and the "do not hand-run it" rule), and **Supported and rejected layouts** (the supported layout plus the two rejected layouts and the bare-directory refusal, each with its failure mode and the diagnostic that names it). The only other change is the E8.4 roadmap checkbox. It deliberately stops short of any tag or release documentation, any rewrite of the pre-extraction sections ("Prerequisites", "Quickstart", `aidt/runs/` references) or removal of the "Interim state" note, a `design.md` rewrite, and any code, test, or `pyproject.toml` change.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/task-prompts/00-E8.4-prompt.md` | Created | Task prompt for E8.4 (committed on the branch as `b7db2b9`). |
| `docs/implementation-results/00-E8.4/build-results.md` | Created | This results document, written by the record stage after gating. |
| `README.md` | Modified | Adds the four new sections described under Scope, inserted after the "Interim state" blockquote and before "Repository, naming, and provenance". Nothing existing is rewritten. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E8.4 complete (traceability stage). |

---

## Verification Results

All gate outcomes below were produced by this recording run against tree `156fe3c7bca8`, with the scope every stage of this workflow declares: `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.62ms`, exit 0; no dependency or lockfile change). Gate `install`, tree `156fe3c7bca8`, stage `record-implementation-results`, 2026-11-06T05:21:26Z |
| Build | `uv build --no-build-isolation --out-dir $(mktemp -d)` | ✅ Pass (`Successfully built …/aidt-0.1.0.tar.gz` and `…/aidt-0.1.0-py3-none-any.whl`). Gate `build`, tree `156fe3c7bca8`, stage `record-implementation-results`, 2026-11-06T05:21:28Z |
| Test | `uv run --frozen pytest` | ✅ Pass (`1850 passed in 35.65s`). Gate `suite`, tree `156fe3c7bca8`, stage `record-implementation-results`, 2026-11-06T05:22:07Z |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (exit 0, `21 checks: 0 failed, 2 warning(s)`; the two warnings are the expected dirty working tree on branch `00-E8.4` and the absent `.mcp.json`). Gate `doctor`, tree `156fe3c7bca8`, stage `record-implementation-results`, 2026-11-06T05:22:10Z |
| Agent configs | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`). Gate `agents-validate`, tree `156fe3c7bca8`, stage `record-implementation-results`, 2026-11-06T05:22:13Z |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (`toolkit defaults: 0 error(s), 0 warning(s)`; `resolved repo prompts: 0 error(s), 0 warning(s)`). Gate `prompts-check`, tree `156fe3c7bca8`, stage `record-implementation-results`, 2026-11-06T05:22:16Z |
| Whitespace | `git diff --check` | ✅ Pass (no output, exit 0) |

Lint: **not run** — this repository configures no linter, formatter, or type-checker (`AGENTS.md`, `design.md` §15), so it has no lint gate and none was invented.

### `uv run --frozen pytest` (full suite)

Every row is taken from the single full-suite invocation above; no subset was re-run to obtain a count.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1850 | ✅ Pass (`1850 passed in 35.65s`) |

No per-file rows are reported: `-q -n auto` prints a single summary, and producing per-file counts would require a second invocation of the suite, which this stage does not pay for. This is a documentation-only change, so it adds no tests; the total is the pre-existing suite (E8.3 recorded 1849, and the difference is not attributable to this task's diff).

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Bootstrap reproduction: the README's two bootstrap commands run verbatim in a fresh temp dir against the real origin (`https://github.com/curiouslittledroid/aidt.git`) | ✅ `git clone --bare … bare.git` then `git -C bare.git worktree add ../main main` succeeded (`HEAD is now at 809fa86`); `ls` of the workspace shows exactly `bare.git` and `main`, i.e. siblings |
| Bootstrap identity assertion: `git -C main rev-parse --path-format=absolute --git-common-dir` resolves to the bare repo (§3.2 repo-identity fact) | ✅ Printed `<workspace-root>/bare.git` — identical to the expected bare path (the `mktemp` directory appears under both `/var/...` and `/private/var/...`, which are the same directory) |
| Read-back: README contains both D9 install forms with `--from` present in the `uvx` form | ✅ Exact-string checks hit once each: `uv tool install "git+https://github.com/curiouslittledroid/aidt@<tag>"` and `uvx --from "git+https://github.com/curiouslittledroid/aidt@<tag>"` |
| Read-back: the actual origin URL `https://github.com/curiouslittledroid/aidt.git` appears (not `mythical-forge`, not a bare `<url>`) | ✅ Present once, in the bootstrap block; `mythical-forge` appears only as the illustrative workspace folder name in the layout diagram |
| Read-back: both rejected layouts named, plus the bare-directory refusal | ✅ `clone-of-a-worktree` (2 occurrences — trap name and the link from the bootstrap text), `Creating the branch on … then moving it`, and `bare directory as the target` each present |
| Read-back: git ≥ 2.31 minimum, tied to `aidw doctor` | ✅ `2.31` appears 3 times (the requirement, the `--path-format=absolute` rationale, and doctor's `git version` check) |
| Read-back: AIDT owns per-task worktree creation, with the §3.2 per-task form and the "do not hand-run it" rule | ✅ Section "Task worktrees are created by AIDT" present; `worktree add -b <branch>` appears once as the per-task form; the section states the bootstrap is one-time and forbids `git checkout -b`/`git switch -c` |
| Read-back: pre-extraction sections untouched and the "Interim state" note retained | ✅ `git diff main...HEAD -- README.md` + working-tree diff is a pure insertion of 102 lines after the blockquote; no existing line is removed or reworded |
| Layout diagnosis: `aidw doctor` from the bootstrapped `main` worktree reports `workspace root`, `state root`, `control worktree` OK with no clone-of-a-worktree FAIL | ✅ `[ ok ] workspace root <tmp>/mythical-forge`, `[ ok ] state root <tmp>/mythical-forge/.aidw/state/curiouslittledroid-aidt`, `[ ok ] control worktree clone-of-a-worktree guard passed`, `[ ok ] repo root <tmp>/mythical-forge/main`; `21 checks: 0 failed, 1 warning(s)` (the warning is the missing `.mcp.json`) |
| Tag discipline: no release tag invented, created, or pushed | ✅ `<tag>` appears only as the marked placeholder, with E8.5 named as its owner; `git tag` was not run against the remote and no tag was created |

---

## Deviations observed during recording

- **No lint command exists to gate** — `AGENTS.md` names no linter/formatter/type-checker and says not to add one, so no `lint` gate was run; the template's lint row is omitted rather than marked passing.
- **`docs/architecture` is in the declared ignore scope but does not exist yet** — it is a configured write-target of a later stage (`paths.architecture_dir`), so the scope declares it uniformly with the other stages even though the directory is absent.
- **The E8.4 implementation was not committed at record time** — `git log main..HEAD` carries only `b7db2b9` (the task prompt); `README.md` and the roadmap checkbox are working-tree changes. The change set reported here is the working tree relative to `main`, as the stage instructs, and the gate tree identity `156fe3c7bca8` covers those uncommitted files.
- **The suite total differs from E8.3's record (1850 vs 1849)** — this task adds no tests, so the difference comes from the toolkit/working tree as it stands now rather than from the E8.4 diff; the number reported is what this run observed, not a reuse of the earlier figure.
- **The bootstrap reproduction used the real origin over the network** — the task prompt allows a local fixture remote; the real origin was used because it also proves the URL the README prints resolves.
- **The per-task `worktree add -b …` form was read back, not executed** — executing it would create a task branch in a throwaway workspace and prove nothing beyond the read-back, which the prompt's test list asks for.

---

## Non-Goals (NOT implemented)

- ❌ E8.5 (release process, first tag, `requires_toolkit` pinning doc) — no tag, no release doc; the `@<tag>` placeholder stays and is documented as E8.5-owned.
- ❌ E9.4 (full README rewrite: purpose, quickstart against a target repo, stale-gh + worktree troubleshooting) — the pre-extraction sections are not rewritten and the "Interim state" note is retained.
- ❌ E9.1 (`design.md` rewrite) — `design.md` §3 still describes the pre-extraction `aidt/` layout; no design-document change was made.
- ❌ Any code, test, or `pyproject.toml` change — this is a documentation task; the diff touches `README.md` only, plus the roadmap checkbox.
- ❌ Committing, pushing, or opening a PR — owned by the `/pr` stage.
- ❌ Writing `player-actions.md` or `integration-tests.md` — owned by the `show-updated-*` stages.
