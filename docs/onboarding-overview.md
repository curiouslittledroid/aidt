# AIDT Onboarding Guide

> Generated from the knowledge graph at commit `a786e84` — 399 files, 893 nodes, 10 layers.
> Refresh the graph with `/understand` after significant structural changes.

## Project Overview

| | |
|---|---|
| **Name** | `aidt` (AI Developer Tools) — package & CLI are **`aidw`** |
| **Languages** | Python, Markdown, YAML, TOML, JSON |
| **Frameworks/tools** | Typer (CLI), pytest (tests), GitHub Actions (CI) |
| **What it is** | A developer-workflow toolkit that drives the **Pi** coding agent from the command line through the SDLC stages of a *target repo*. The `aidw` CLI selects a roadmap task and runs specialised agents through workflow stages, pausing at human decision gates and recording every stage, gate and cost. |

**The most important mental model — two roots.** The *toolkit root* (this repo — code, `prompts/`, `agent-configs/`) and the *target repo root* (the working tree a workflow operates on) are **two distinct roots, never interchangeable**. Also, `aidw/` means two things: here it's Python code; inside a target repo it's configuration (`aidw/config.yaml`).

## Architecture Layers

| Layer | What it is | Key files |
|---|---|---|
| **CLI & Entry Points** | Typer command surface mapping user commands to workflows | `aidw/cli.py`, `aidw/aidw`, `aidw/__init__.py` |
| **Core Engine** | Toolkit runtime: paths, config, runner, state, Pi execution, git/GitHub | `aidw/paths.py`, `runner.py`, `stage_registry.py`, `state.py`, `pi.py`, `target_config.py` |
| **Workflow Orchestration** | Six end-to-end workflows driving a target repo's SDLC | `aidw/workflows/{prompt,implement,review,fix,approve,run}.py` |
| **Bundled Scripts** | Shipped automation — release tooling + review-followup GitHub scripts | `scripts/release.py`, `prompts/scripts/review-followup/*.py` |
| **Prompt Templates** | LLM prompts defining each stage's behaviour | `prompts/*.md` (18 files) |
| **Agent Configurations** | Agent YAMLs + shipped AGENTS.md/SYSTEM.md context | `agent-configs/*.yaml`, `agents/*/` |
| **Test Suite** | Pytest suites + fixtures (72 files) | `tests/`, `fixtures/` |
| **Task Records** | Per-task build results, summaries, task prompts (221 files) | `docs/implementation-results/`, `docs/task-prompts/` |
| **Documentation** | Design, contracts, plans | `design.md`, `README.md`, `docs/` |
| **Configuration & Infrastructure** | Manifest, schema, CI | `pyproject.toml`, `.github/workflows/ci.yml` |

## Key Concepts

- **Workflow → Stage → Gate.** A workflow is an ordered set of *stages* (agent + prompt + conditions). Stages pause at *human decision gates* (approve/deny/skip). `aidw/stage_registry.py` is the canonical definition source; `docs/workflow-stages.md` mirrors it and is drift-checked.
- **Prompts & agent-configs are the product contract.** Editing a prompt or `agent-configs/*.yaml` is a behaviour change, not copy-editing. `aidw/inventory.py` keeps a `REQUIRED_PROMPTS`/`REQUIRED_SCRIPTS` inventory so a rename fails loudly.
- **Tool allowlists are deny-by-default.** `task-reviewer` and `code-reviewer` are read-only (`READ_ONLY_AGENTS`) — never grant them write tools.
- **Never merge.** AIDT never merges, force-pushes, resets, or discards user changes — that's the delivery pipeline's job. GitHub writes go through the bundled scripts only.
- **Roadmap ticking with evidence.** Roadmap checkboxes are flipped only behind verified evidence (`tree_identity` change detection + test verdicts).
- **Run state is machine-local.** `runs/`, `.aidw/` are never committed; state is persisted atomically with fsync.
- **Deterministic where possible.** Imports, structure, and tree identity are resolved by bundled deterministic scripts — the LLM only adds semantic analysis.

## Guided Tour

1. **Project Overview** → `README.md` — the operator guide.
2. **The Authoritative Design** → `design.md` — §17 is the resolved-decisions log.
3. **CLI & Entry Points** → `aidw/cli.py` (every `aidw` subcommand).
4. **The Two-Roots Model** → `aidw/paths.py`, `aidw/layout.py`.
5. **Target-Repo Config Contract** → `aidw/target_config.py` + `docs/target-repo-config.md`.
6. **Workflow & Stage Registry** → `aidw/stage_registry.py` + `docs/workflow-stages.md`.
7. **Planning & Running Stages** → `aidw/runner.py` (plan → resolve prompt → dispatch).
8. **Executing Pi Agents** → `aidw/pi.py` (event parsing, usage/token accounting, retry).
9. **Run State & Decision Gates** → `aidw/state.py`, `aidw/gates.py`.
10. **End-to-End Workflows** → `aidw/workflows/*.py`.
11. **Prompts & Agent Configurations** → `agent-configs/`, `prompts/`.
12. **Git & GitHub Integration** → `aidw/git.py`, `aidw/github.py`.
13. **Verification, CI & Release** → `aidw/verification.py`, `.github/workflows/ci.yml`, `scripts/release.py`.
14. **The Test Suite** → `tests/conftest.py`, `tests/test_prompt_workflow.py`.

## File Map (key files, by layer)

**Core Engine (`aidw/`)**
- `paths.py` — two-roots resolution (toolkit/target/workspace roots). Foundation of everything.
- `stage_registry.py` — canonical stage/workflow definitions, loop expansion, validation.
- `runner.py` — plans stages and runs each through Pi.
- `target_config.py` — `<target>/aidw/config.yaml` schema, loading, layered resolution, compatibility.
- `state.py` — `RunState`, atomic JSON persistence, run listing.
- `pi.py` — invokes Pi, parses events, token/tool accounting, retry.
- `config.py` — agent config loading, read-only allowlist enforcement.
- `gates.py` — human approve/deny/skip decisions.
- `git.py` / `github.py` — git subprocesses; gh CLI + bundled scripts.
- `verification.py` — gate commands + tree-identity change detection.
- `roadmap.py`, `findings.py`, `verdict.py`, `prompts.py`, `report.py`, `doctor.py`, `inventory.py`, `layout.py`, `lock.py`, `log.py`, `cost.py`, `progress.py`, `agents.py` — supporting runtime.

**Workflows (`aidw/workflows/`)** — `prompt.py`, `implement.py`, `review.py`, `fix.py`, `approve.py`, `run.py` (chains).

**Bundled Scripts** — `scripts/release.py`; `prompts/scripts/review-followup/` (`review_followup.py` CLI, `gh.py` GitHub helpers, `logic.py` selection/close logic, `publish_review_followups.py`).

## Complexity Hotspots

Approach these carefully — largest and most intricate files:

| File | Lines | Why it's hard |
|---|---|---|
| `aidw/workflows/prompt.py` | 3,358 | Prompt-review loop, revision budgeting, evidence bundles |
| `aidw/workflows/fix.py` | 2,034 | Iteration, commit decisions, roadmap-tick reconciliation |
| `aidw/target_config.py` | 1,718 | Schema, layered resolution, compatibility |
| `aidw/workflows/implement.py` | 1,689 | Worktree/branch derivation, roadmap ticking |
| `aidw/cli.py` | 1,588 | Entire command surface |
| `aidw/stage_registry.py` | 1,451 | Definition validation + loop expansion |
| `aidw/runner.py` | 1,080 | Stage planning/execution |
| `aidw/pi.py` | 754 | Event parsing + accounting + retry |
| `aidw/state.py` | 708 | Atomic persistence, gate outcomes |
| `prompts/scripts/review-followup/` | up to 735 | GitHub issue reconciliation semantics |

**Test-side hotspots** (also "complex", but these are specs, not logic to fear): `tests/test_prompt_workflow.py` (8,756 lines — the largest), `test_implement_workflow.py`, `test_target_config.py`, `test_fix_workflow.py`.

**Where to start reading code:** `aidw/paths.py` → `stage_registry.py` → `runner.py` → one workflow (`implement.py`) → `pi.py`. Then `target_config.py` when you touch config.

## Development Gates

Run exactly these — and only these — before delivering a change:

```bash
uv sync --frozen
uv run --frozen pytest
uv run aidw doctor
uv run aidw agents validate --strict
uv run aidw prompts check
```

CI (`.github/workflows/ci.yml`) installs Pi, then runs `uv sync --frozen` and the pytest + `doctor` commands above with `--frozen`. Because it is frozen, a stale `uv.lock` is a **build failure** rather than a silent update: adding a dependency means editing `pyproject.toml` **and** re-syncing the lock in the same change.

Record a gate through the run instead of paying for it twice — a gate is keyed to the content it verified:

```bash
aidw gate run suite -- uv run --frozen pytest
```

Pass `--ignore <prefix>` only for paths the command genuinely cannot read, never for source, tests, config or lockfiles.

### Testing conventions

- **`pytest` is the only verification** — no linter, formatter, or type-checker is configured (don't add one inside an unrelated task).
- `addopts = "-q -n auto"` in `pyproject.toml`; `-n0` for a serial run.
- **No test may invoke a real Pi model** — fake the argv/plan and assert it; `--dry-run` in every workflow is the primary integration seam.
- Test runtime is dominated by `git` process spawns (~300 temporary repos). Use `GIT_IDENTITY` from `tests/conftest.py` instead of per-repo `git config`, and don't add spawns to a hot path without measuring.
- Tests must not leave state behind: `tests/conftest.py` guards the toolkit `runs/` tree against stray `*-pytest-*` directories.

### Style & provenance

- `from __future__ import annotations` in every module except package `__init__.py`.
- Module docstrings state the module's job and the `design.md` section it implements.
- Cite sources in comments and commits: `design.md` §N, decision IDs (`D2`, `F5`), task IDs (`E1.4`).

### Delivering a change

- One branch and one PR per task, named for the task id (e.g. `00-E1.6`). Never commit to `main` directly.
- Commit prefixes: `feat(scope):`, `fix:`, `docs:`, `perf(scope):`. Reference the task id.
- The record stage writes `docs/implementation-results/<task-id>/build-results.md` from `docs/implementation-results/TEMPLATE.md` and **fails closed** if the template is absent.
- Report exact commands run and their real outcomes. Never invent gate results.

### Where truth lives

| Document | Role |
|---|---|
| `design.md` | Authoritative design. §17 is the resolved-decisions log — record new decisions there, not only in code. |
| `README.md` | Operator guide. |
| `EXPLICIT-RESOURCES.md` | Planned future state (not implemented). |
| `docs/migration/EXTRACTION.md` | Plan of record for the extraction. |
| `docs/target-repo-config.md` | The `<target>/aidw/config.yaml` contract (drift-checked). |
| `docs/workflow-stages.md` | Every stage of every workflow (drift-checked). |
| `docs/schema/` | Placeholder owned by later tasks. |
