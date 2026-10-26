# AGENTS.md — developing `aidt` itself

Conventions for changing **the toolkit**, not for using it. `README.md` is the operator
guide and `design.md` is the authoritative design; read the relevant `design.md` section
before changing behaviour it specifies.

## What this repo is

- Repository **`aidt`** ("AI Developer Tools"); importable package and console command
  **`aidw`** ("AI Developer Workflows"). Both names are deliberate — don't normalise them.
- **Two roots.** *Toolkit root* = this repo (code, `prompts/`, `agent-configs/`, bundled
  scripts), resolved from the installed package. *Target repo root* = the working tree a
  workflow operates on, resolved via git from the cwd or `--repo`. Never resolve one from
  the other's cwd assumption.
- **`aidw/` means two things.** Here it is Python code. Inside a *target* repo it is
  configuration (`aidw/config.yaml`, optional `aidw/conventions.md`, prompt overrides).
- `agents/<id>/AGENTS.md` are **agent context files** shipped to Pi for target-repo work
  (`agents_md:` in `agent-configs/<id>.yaml`). They are not this file and are not about
  developing `aidt`.

## Gates — run exactly these, and only these

```bash
uv sync --frozen
uv run --frozen pytest
uv run aidw doctor
uv run aidw agents validate --strict
uv run aidw prompts check
```

CI (`.github/workflows/ci.yml`) installs Pi, then runs `uv sync --frozen` and the pytest and
`doctor` commands above with `--frozen`. Because it is frozen, a stale `uv.lock` is a build
failure rather than a silent update: adding a dependency means editing `pyproject.toml`
**and** re-syncing the lock in the same change.

Record a gate through the run instead of paying for it twice — a gate is keyed to the
content it verified, so later stages of the same run cite it:

```bash
aidw gate run suite -- uv run --frozen pytest
```

Pass `--ignore <prefix>` only for paths the command genuinely cannot read (documents other
stages write), never for source, tests, config or lockfiles.

## Tests

- `pytest` is the only verification (no linter, formatter, or type-checker is configured —
  don't add one inside an unrelated task). See `design.md` §15.
- **No test may invoke a real Pi model.** Fake the argv/plan and assert it; `--dry-run` in
  every workflow is the primary integration seam.
- `addopts = "-q -n auto"` in `pyproject.toml`; `-n0` for a serial run. `testpaths` also
  covers `prompts/scripts/review-followup/tests`.
- Runtime is dominated by `git` process spawns (~300 temporary repos per suite). Use
  `GIT_IDENTITY` from `tests/conftest.py` instead of per-repo `git config`, and don't add
  spawns to a hot path without measuring.
- Tests must not leave state behind: `tests/conftest.py` guards the toolkit `runs/` tree
  against stray `*-pytest-*` directories.

## Style

- `from __future__ import annotations` in every module except package `__init__.py`.
- Module docstrings state the module's job and the `design.md` section it implements.
- Cite sources in comments and commits: `design.md` §N, decision IDs (`D2`, `F5`), task IDs
  (`E1.4`), `EXPLICIT-RESOURCES.md`, `docs/migration/EXTRACTION.md`. Comments explaining
  *why* a non-obvious trade-off was taken are expected, not noise.

## Where truth lives

| Document | Role |
|---|---|
| `design.md` | Authoritative design. §17 is the resolved-decisions log — **record new decisions there**, not only in code. |
| `README.md` | Operator guide. Sections still read pre-extraction in places; the naming/two-roots section is current. |
| `EXPLICIT-RESOURCES.md` | **Planned future state** (not implemented). |
| `docs/migration/EXTRACTION.md` | Plan of record for the extraction. |
| `docs/target-repo-config.md`, `docs/schema/` | Placeholders owned by later tasks. |

## Prompts and agent configs are the product contract

- `prompts/` is AIDT's own source of truth; AIDT **never** reads `.pi/prompts/`.
- Editing a prompt or an `agent-configs/*.yaml` is a behaviour change, not copy-editing:
  keep `prompts check` and `agents validate --strict` green.
- A new or renamed prompt must be reflected in `REQUIRED_PROMPTS`/`REQUIRED_SCRIPTS`
  (`aidw/inventory.py`), which exists so a rename fails loudly instead of at Pi invocation.
- Tool allowlists are deny-by-default. `task-reviewer` and `code-reviewer` are read-only
  (`READ_ONLY_AGENTS`, `aidw/config.py`) — never grant them write tools.

## Never

From `design.md` §1.2 and §13:

- Never merge a PR, force-push, `git reset --hard`, `git clean`, or discard unrelated user
  changes. AIDT never merges — that is the delivery pipeline's job.
- Never bypass a gate silently; every skipped gate is recorded in `state.json`.
- Never reimplement GitHub logic: writes go through the bundled scripts
  (`publish_review_followups.py`, `review_followup.py`) or read-only `gh` calls.
- Never commit secrets, and never write outside the repository except Pi's session store.
- Run state (`runs/`, `.aidw/`) is machine-local and never committed.

## Delivering a change

- One branch and one PR per task, named for the task id (e.g. `00-E1.6`). Never commit to
  `main` directly.
- Commit prefixes seen in history: `feat(scope):`, `fix:`, `docs:`, `perf(scope):`.
  Reference the task id.
- The record stage writes `docs/implementation-results/<task-id>/build-results.md` from
  `docs/implementation-results/TEMPLATE.md` and **fails closed** if the template is absent.
- Report exact commands run and their real outcomes. Never invent gate results.
