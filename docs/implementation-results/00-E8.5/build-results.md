# Build Results — E8.5: Release process

**Branch:** `00-E8.5`
**Date:** 2026-11-06
**Spec:** `docs/migration/EXTRACTION.md` §2 (locked decisions D8 verbatim `baseline-verbatim` tag, D9 distribution forms, D10 target-config minimum version), §3.11 (version and compatibility, D10), §3.12 (repo layout: the release doc lives in `docs/`); `docs/target-repo-config.md` (`schema_version`/`requires_toolkit`, "Unset, not defaulted", the full example); `README.md` §Install (the E8.4 install section this task updates)

## Summary

**Purpose:** Document how a version bump becomes an installable `v<X.Y.Z>` release and how a target repo pins and upgrades `requires_toolkit`, so an operator can cut the first `v0.1.0` tag from merged `main` and prove it by installing from the tag.

| Decision | Why it matters |
|----------|---------------|
| The release process is its own `docs/releasing.md`, cross-linking `README.md` §Install and `docs/target-repo-config.md` rather than copying either | The install commands and the config field table already have owners; duplicating them would drift from the schema and the shipped compatibility check. |
| The version bump is documented as three lockstep edits — `pyproject.toml:[project].version`, `aidw/__init__.py:__version__`, and the hardcoded `"0.1.0"` literal in `tests/test_packaging.py::test_pyproject_identity_is_the_settled_name_version_and_script` — plus a re-synced `uv.lock` | There is no dynamic versioning; editing only one source (or forgetting the test literal) fails the packaging identity test. The lock records the project version too, and `uv sync --frozen` does not catch a stale lock. |
| Release tags are annotated `v<X.Y.Z>` tags cut on merged `main`; `baseline-verbatim` is explicitly a non-release history marker | A tag pushed from the task branch would pin the pre-merge commit and ship a release without the release doc. D8's unprefixed verbatim tag must never be retagged, renamed, or reused as a release pin. |
| The first tag is an operator step documented copy-paste, not something this task pushes | AIDT never merges, and `prompts/pr.md` pushes only the branch; no SDLC stage pushes tags. |
| D9's two install forms stay literal — `uv tool install "git+…@v0.1.0"` (primary) and `uvx --from "git+…@v0.1.0" aidw --version` (secondary) | The `uvx` form needs `--from <git-url>`; bare `uvx aidw` resolves a different package from PyPI. |
| The pin is a PEP 440 specifier (`requires_toolkit: ">=0.1.0"`) compared with `packaging`, distinct from the integer `schema_version` | The two are independent refusals in `check_compatibility`; presenting `schema_version` as the version pin or a bare equality as the pin form would misstate shipped behaviour. |

**Where it fits in the roadmap:** Epic E8 (packaging, distribution, versions). It builds on E8.1's installable distribution and E8.2–E8.4's version reporting, doctor smoke checks, and install/worktree guide; it fills in the `@<tag>` placeholder E8.4 left in `README.md` §Install. Later releases reuse this runbook, and E9.4's full README rewrite inherits the concrete `@v0.1.0` install text instead of a placeholder.

**Scope:** `docs/releasing.md` (release-tag distinction, three-site version bump, annotated-tag-on-`main` and push commands, D9 install verification from a clean tool venv, and the target-repo pin/upgrade story), `README.md` §Install (concrete `@v0.1.0`, link to the release doc, `baseline-verbatim` caveat retained), a docs contract test, and the E8.5 roadmap checkbox. It deliberately stops short of a full README rewrite, any change to `docs/target-repo-config.md` or `docs/migration/EXTRACTION.md`, a version bump, any code/CI/`pyproject.toml` change, and any tag push from this branch.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `docs/releasing.md` | Created | Release runbook: tag scheme, three-site bump plus `uv.lock`, annotated `v0.1.0` tag on merged `main`, D9 install verification, and `requires_toolkit` pin/upgrade guidance. |
| `tests/test_releasing_doc.py` | Created | Contract test pinning the release doc's bump sites, tag/install commands, pin refusal, and the README install read-back. |
| `docs/task-prompts/00-E8.5-prompt.md` | Created | Task prompt for E8.5, committed on the branch as `5ac0c95`. |
| `docs/implementation-results/00-E8.5/build-results.md` | Created | This results document, written by the record stage after gating. |
| `README.md` | Modified | §Install now shows `@v0.1.0` in both D9 forms, links `docs/releasing.md`, and keeps the `baseline-verbatim` non-release caveat. |
| `docs/tasks/00 - Extraction.md` | Modified | Marks E8.5 complete (traceability stage). |

---

## Verification Results

All gate outcomes below were produced by this recording run against tree `6f0193aa3e92`, with the scope every stage of this workflow declares: `--ignore docs/implementation-results --ignore docs/architecture --ignore docs/tasks --ignore docs/task-prompts`.

### Top-level verification

| Step | Command | Result |
|------|---------|--------|
| Install | `uv sync --frozen` | ✅ Pass (`Checked 19 packages in 0.44ms`, exit 0; no dependency or lockfile change). Gate `install`, tree `6f0193aa3e92`, stage `record-implementation-results`, 2026-11-06T05:45:10Z |
| Build | `uv build --no-build-isolation --out-dir $(mktemp -d)` | ✅ Pass (`Successfully built …/aidt-0.1.0.tar.gz` and `…/aidt-0.1.0-py3-none-any.whl`). Gate `build`, tree `6f0193aa3e92`, stage `record-implementation-results`, 2026-11-06T05:45:11Z |
| Test | `uv run --frozen pytest` | ✅ Pass (`1853 passed in 34.97s`). Gate `suite`, tree `6f0193aa3e92`, stage `record-implementation-results`, 2026-11-06T05:45:48Z |
| Doctor | `uv run --frozen aidw doctor` | ✅ Pass (exit 0, `21 checks: 0 failed, 2 warning(s)`; warnings are the expected dirty working tree on branch `00-E8.5` and the missing `.mcp.json`; `toolkit version 0.1.0`, `compat status none (defaults) — toolkit 0.1.0 is compatible`). Gate `doctor`, tree `6f0193aa3e92`, stage `record-implementation-results`, 2026-11-06T05:45:51Z |
| Agent configs | `uv run --frozen aidw agents validate --strict` | ✅ Pass (`11 agent config(s): 0 error(s), 0 warning(s)`). Gate `agents-validate`, tree `6f0193aa3e92`, stage `record-implementation-results`, 2026-11-06T05:45:52Z |
| Prompts check | `uv run --frozen aidw prompts check` | ✅ Pass (`toolkit defaults: 0 error(s), 0 warning(s)`; `resolved repo prompts: 0 error(s), 0 warning(s)`). Gate `prompts-check`, tree `6f0193aa3e92`, stage `record-implementation-results`, 2026-11-06T05:45:52Z |
| Whitespace | `git diff --check` | ✅ Pass (no output, exit 0) |

Lint: **not run** — this repository configures no linter, formatter, or type-checker (`AGENTS.md`, `design.md` §15), so it has no lint gate and none was invented.

### `uv run --frozen pytest` (full suite)

Every row is taken from the single full-suite invocation above; no subset was re-run to obtain a count.

| Test selection | Tests | Result |
|----------------|-------|--------|
| Full suite | 1853 | ✅ Pass (`1853 passed in 34.97s`) |

No per-file rows are reported: `-q -n auto` prints a single summary, and the docs contract test `tests/test_releasing_doc.py` is included in that total. Producing a separate count for it would require a second invocation of the suite, which this stage does not pay for.

### Task-specific verification gates

| Gate | Status |
|------|--------|
| Install-from-tag reproduction: cut the documented `git tag -a v0.1.0 -m "AIDT v0.1.0"` in a scratch clone, then run D9's primary form from a clean tool environment | ✅ Scratch clone at `/tmp/aidt-e85-scratch.ieJlbw/clone` (merged `main`, HEAD `27a1c9c`), annotated tag `v0.1.0` created locally, then `UV_TOOL_DIR=… UV_TOOL_BIN_DIR=… UV_CACHE_DIR=… uv tool install "git+file:///tmp/aidt-e85-scratch.ieJlbw/clone@v0.1.0"` installed `aidt==0.1.0` from the git URL and installed the `aidw` executable |
| `aidw --version` from the tagged install | ✅ `/tmp/aidt-e85-scratch.ieJlbw/bin/aidw --version` printed `aidt 0.1.0` |
| `aidw doctor` from the tagged install | ✅ `21 checks: 0 failed, 2 warning(s)`; `toolkit version 0.1.0`, `toolkit root /private/tmp/aidt-e85-scratch.ieJlbw/tools/aidt/lib/python3.14/site-packages`, `git version 2.50.1 (/usr/bin/git)`, and `compat status none (defaults) — toolkit 0.1.0 is compatible` all report OK; the two warnings are the recording checkout's dirty tree and missing `.mcp.json` |
| Read-back: release doc names all three bump sites, the annotated `v<X.Y.Z>` tag and push commands, and the `requires_toolkit: ">=0.1.0"` pin example with upgrade steps | ✅ Exact-string checks passed for `pyproject.toml` → `[project].version`, `aidw/__init__.py` → `__version__`, the `test_pyproject_identity_is_the_settled_name_version_and_script` literal, `git tag -a v0.1.0 -m "AIDT v0.1.0"`, `git push origin v0.1.0`, `requires_toolkit: ">=0.1.0"`, and the `docs/target-repo-config.md` cross-link |
| Read-back: README no longer contains "no release tag exists yet", links `docs/releasing.md`, shows `@v0.1.0` in both D9 forms, and keeps the `baseline-verbatim` caveat | ✅ All exact-string checks passed: the old sentence and `@<tag>` are absent; `[docs/releasing.md](./docs/releasing.md)`, `aidt@v0.1.0"`, `uvx --from`, and the `baseline-verbatim` non-release sentence are present |
| Pin/upgrade refusal: a throwaway target repo with `requires_toolkit: ">=99.0.0"` is refused with the §3.11 message | ✅ `aidw doctor` in `/tmp/aidt-e85-pin.5x3aGD` exited 1 with ``[ fail ] compat status     error: config.yaml: `requires_toolkit` '>=99.0.0' is not satisfied by this toolkit's version 0.1.0; upgrade `aidt` to a version matching '>=99.0.0', or relax the pin in `config.yaml`.`` — matching the wording documented in `docs/releasing.md` |
| Tag discipline: no release tag pushed or created in the task worktree | ✅ `git tag -l` in the task worktree lists only `baseline-verbatim`; the `v0.1.0` tag exists only in the local scratch clone used for the install proof |

---

## Deviations observed during recording

- **No lint command exists to gate** — `AGENTS.md` names no linter/formatter/type-checker and says not to add one, so no `lint` gate was run; the template's lint row is omitted rather than marked passing.
- **Build is a packaging smoke check, not one of the five gates `AGENTS.md` names** — `uv build --no-build-isolation` was run through `aidw gate run` because the template has a Build row and prior records use the same command; it is not presented as an `AGENTS.md` gate.
- **The E8.5 implementation was not committed at record time** — `git log main..HEAD` carries only `5ac0c95` (the task prompt); `README.md`, `docs/releasing.md`, `tests/test_releasing_doc.py`, and the roadmap checkbox are working-tree changes. The change set reported here is the working tree relative to `main`, as the stage instructs, and gate tree `6f0193aa3e92` covers those uncommitted files.
- **A docs contract test is in the change set although the task prompt's scope says "no tests"** — `tests/test_releasing_doc.py` is the implementation's contract test for the release doc and README, not a record-stage change; it is included in the suite total above and was not modified here.
- **The install-from-tag scratch clone was `main` at `27a1c9c`, not a merged post-E8.5 `main`** — E8.5 is not merged, so a clone of the branch's future merge commit does not exist; the local `git+file://` proof exercises the documented tag command, the build backend, the console script, and D9's primary install form end-to-end without pretending `v0.1.0` exists on `origin`.
- **`docs/architecture` is in the declared ignore scope but does not exist yet** — it is a configured write-target of a later stage (`paths.architecture_dir`), so the scope declares it uniformly with the other stages.

---

## Non-Goals (NOT implemented)

- ❌ E9.4 (full README rewrite) — only the Install section's placeholder note changed; the pre-extraction sections and the "Interim state" note are untouched.
- ❌ E9.2 (write `docs/target-repo-config.md`) — it already exists and owns the field contract; the release doc only cross-links it and does not rewrite or extend it.
- ❌ E9.1 (rewrite `design.md`) — no design-document change was made.
- ❌ E9.3 (move `EXTRACTION.md` to `docs/history/`) — the cited docs stay where they are.
- ❌ No version bump — `0.1.0` is already the first release; `pyproject.toml`, `aidw/__init__.py`, and `uv.lock` are unchanged.
- ❌ No tag pushed from this branch — `v0.1.0` must be cut on merged `main`; the tag was created only in a throwaway local scratch clone for the install proof.
- ❌ No code, CI, or `pyproject.toml` changes.
- ❌ Committing, pushing, or opening a PR — owned by the `/pr` stage.
- ❌ Writing `player-actions.md` or `integration-tests.md` — owned by the `show-updated-*` stages.
