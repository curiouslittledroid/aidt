# aidt — repository conventions

AIDT reads this file from the **target repo root** (after `AGENTS.md`, per D16) and injects it
into the stage prompts that ask a model to work on this repository. It carries only what
`AGENTS.md` does not already say, and it is not a place for gate commands or stack rules that
belong there.

## Traceability artefacts (`update-traceability`, `I3`)

This repo keeps requirements traceability in exactly these files, and a task updates the ones it
actually changes:

| Artefact | What traces to it | Drift check |
|---|---|---|
| `design.md` §17 "Resolved decisions" | One row per resolved decision: the task id, the spec sections it touches, the files it changed, and the rationale for every choice the spec left open. New decisions are appended as new rows; an existing row is never folded into, renumbered or reused. | `tests/test_design_doc.py` pins the rows it needs by id (one row per id) |
| `docs/workflow-stages.md` | Every stage of every workflow — agent, prompt, arguments, condition, context — plus loops and gates. | `tests/test_workflow_stages_doc.py`, drift-checked against `aidw/stage_registry.py` |
| `docs/target-repo-config.md` | The `<target>/aidw/config.yaml` contract. | `tests/test_target_repo_config_doc.py`, drift-checked against `aidw/target_config.py` |

There is **no** generated traceability matrix, coverage table or report in this repo, and none is
expected. "No artefact to update" is a valid `I3` outcome and is reported as such.

## `docs/tasks/` belongs to `update-roadmap`, not `update-traceability`

The roadmap under `paths.roadmap_dir` (`docs/tasks/*.md`) is the **plan of record**, and
`update-roadmap` (`I7`) owns it byte-exclusively. `I7`'s postcondition is exact: exactly one
`- [ ]` → `- [x]` flip on exactly one line, with every other byte of the file unchanged, compared
against a snapshot taken at run start. An `update-traceability` edit to the same file therefore
cannot be reconciled — it makes that postcondition unsatisfiable and fails the run **after** every
gate has passed. Do not edit roadmap entries during `update-traceability`.

A task entry's `Done when`, `Deliverable`, `Tests` and `Notes` are fixed at authoring time. A
correction discovered mid-implementation belongs in the task prompt or in `design.md` §17 — never
in the roadmap entry. Concretely, do not do any of the following to `docs/tasks/*.md`:

- tick the task's own checkbox (that is `I7`'s only permitted edit);
- rewrite `Done when` / `Deliverable` / `Tests` / `Notes` to describe what was actually built;
- reflow, re-wrap or reformat the entry, or touch a neighbouring entry.

Rationale: `design.md` §17 Z13. The failure this rule prevents was observed live in run
`20261119T211427Z-05-S1.2-implement`.

## Verification

Gate commands are listed in `AGENTS.md` ("Gates — run exactly these, and only these") and this
file adds none. Record a gate through the run (`aidw gate run <key> -- <command>`) rather than
paying for it twice.
