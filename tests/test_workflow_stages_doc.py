"""Consistency checks pinning ``docs/workflow-stages.md`` to the stage registry.

The document is the operator's index into every stage of every workflow — what it runs, with
which agent, prompt, variables, condition and context. Its executable half is this module,
following ``tests/test_target_repo_config_doc.py``: the doc is read from the toolkit root and
asserted against ``aidw.stage_registry``, so a registry edit the doc does not follow fails the
suite instead of misleading a reader.

Pinned here, table by table:

- the documented workflow set is exactly ``stage_registry.DEFAULTS`` — a sixth workflow, or a
  renamed one, fails;
- each workflow's **stage inventory** rows match its definition **in order** (static, then loop
  head/body/tail, then post-loop) on every field the doc claims: id, runtime-name template,
  agent, prompt file, positional variables, ``when=`` condition and the context block kind;
- the id vocabulary is exactly ``STAGE_IDS`` plus the loop-internal labels (never the
  illustrative semantic ids of §3.4), each with its core / repo-optional / loop-internal
  classification — derived with ``validate_stage_list``'s own rule, so the two cannot disagree —
  and the workflows it appears in;
- the condition and context tables name exactly the tokens the registry can emit, so a new
  ``when=`` or a new ``extra=``/``brief=`` cannot be added silently;
- the gates table matches each workflow module's gate constants, so a renamed gate fails here
  rather than in an operator's transcript;
- every prompt file the tables name is in ``inventory.REQUIRED_PROMPTS``, so a prompt rename
  cannot leave a stale reference in the reference document;
- ``README.md``'s ``aidw implement`` stage block lists exactly the registry's ``implement``
  static chain in order — it had drifted by two stages (``I8``, ``I7``) before this test.

Deliberately *not* tested: the prose ("what each stage does"), which is semantic and belongs to
``design.md`` §8 and the prompt files; the ASCII flow blocks, which are notation rather than
data; and the behaviour of any stage — the workflows' own tests own that.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aidw.findings import MANIFEST_EXTRA
from aidw.inventory import REQUIRED_PROMPTS
from aidw.paths import toolkit_root
from aidw.stage_registry import (
    BRIEF_DELTA,
    BRIEF_RECONCILE,
    DEFAULTS,
    FIX_TEST_CONTEXT_EXTRA,
    PROMPT_FIX_BLOCKING,
    PROMPT_FIX_COULD_FIX,
    PROMPT_FIX_FALLBACK,
    PROMPT_RECONCILE,
    REPO_OPTIONAL_IDS,
    STAGE_IDS,
    TEST_CONTEXT_EXTRA,
    WHEN_BLOCKING,
    WHEN_COULD_FIX,
    WHEN_EVIDENCE_GREEN,
    WHEN_FINDINGS,
    WHEN_UNPARSEABLE,
    StageDefinition,
    get_workflow,
    stages_by_id,
)

DOC_PATH = toolkit_root() / "docs" / "workflow-stages.md"

#: The loop-internal labels: ids the expansion emits that are not ``STAGE_IDS`` members
#: (§3.5 keeps the flat vocabulary closed; ``P2``'s fix/reconcile stages are loop labels).
LOOP_LABELS = frozenset(
    {PROMPT_FIX_BLOCKING, PROMPT_FIX_COULD_FIX, PROMPT_FIX_FALLBACK, PROMPT_RECONCILE}
)

#: The documented label for each context block the registry can attach, by identity of the
#: constant the definition carries. ``P2``'s brief is listed although round 1 suppresses it:
#: the *declaration* is what the table records, and the prose states the round-1 exception.
CONTEXT_LABELS: dict[str, str] = {
    TEST_CONTEXT_EXTRA: "stage context",
    FIX_TEST_CONTEXT_EXTRA: "stage context",
    MANIFEST_EXTRA: "manifest pointer",
}
BRIEF_LABELS: dict[str, str] = {
    BRIEF_DELTA: "delta brief",
    BRIEF_RECONCILE: "reconcile brief",
}
NONE = "—"


# --------------------------------------------------------------------------- #
# Reading the document
# --------------------------------------------------------------------------- #


def _doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """The lines under ``heading`` up to the next heading of any level."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == heading:
            break
    else:  # pragma: no cover - a missing heading is the failure, named
        pytest.fail(f"docs/workflow-stages.md has no heading {heading!r}")
    body: list[str] = []
    for line in lines[index + 1 :]:
        if line.startswith("#"):
            break
        body.append(line)
    return "\n".join(body)


def _table(section: str) -> list[list[str]]:
    """The first markdown table in ``section`` as rows of raw cells (header included)."""
    rows: list[list[str]] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        # The ``|---|---|`` separator carries no data; ``-``/``:``/space only.
        if all(cell and set(cell) <= set("-: ") for cell in cells):
            continue
        rows.append(cells)
    if not rows:  # pragma: no cover - a missing table is the failure, named
        pytest.fail("expected a markdown table in this section of docs/workflow-stages.md")
    return rows


def _plain(cell: str) -> str:
    """A cell's value with its markdown code ticks and padding removed."""
    return cell.replace("`", "").strip()


def _rows(section: str) -> list[list[str]]:
    """A section's first table as data rows, its header row dropped."""
    return _table(section)[1:]


# --------------------------------------------------------------------------- #
# The registry's side of each table
# --------------------------------------------------------------------------- #


def _definitions(workflow: str) -> list[StageDefinition]:
    """Every stage of ``workflow`` in plan order: static, loop head/body/tail, post-loop."""
    definition = get_workflow(workflow)
    found = list(definition.stages)
    if definition.loop is not None:
        found.extend(definition.loop.head)
        found.extend(definition.loop.body)
        found.extend(definition.loop.tail)
    found.extend(definition.post_loop)
    return found


def _context_label(stage: StageDefinition) -> str:
    """The documented context label for a stage's ``extra``/``brief``, or ``—``."""
    if stage.brief:
        assert not stage.extra, f"{stage.id} carries both extra and brief"
        label = BRIEF_LABELS.get(stage.brief)
        assert label is not None, (
            f"{stage.id} carries a brief this document does not label: {stage.brief!r}"
        )
        return label
    if stage.extra:
        label = CONTEXT_LABELS.get(stage.extra)
        assert label is not None, (
            f"{stage.id} carries an extra this document does not label: {stage.extra!r}"
        )
        return label
    return NONE


def _expected_rows(workflow: str) -> list[list[str]]:
    return [
        [
            stage.id,
            stage.name,
            stage.agent,
            stage.prompt_file,
            ", ".join(stage.variables) or NONE,
            stage.when or NONE,
            _context_label(stage),
        ]
        for stage in _definitions(workflow)
    ]


def _kind_of(workflow: str, stage_id: str) -> str:
    """A stage's kind, derived exactly as ``validate_stage_list`` classifies it."""
    definition = get_workflow(workflow)
    static_ids = {item.id for item in definition.stages}
    post_loop_ids = {item.id for item in definition.post_loop}
    loop_ids = set(stages_by_id(workflow)) - static_ids - post_loop_ids
    if stage_id in loop_ids:
        return "loop-internal"
    if stage_id in REPO_OPTIONAL_IDS:
        return "repo-optional"
    return "core"


def _workflows_by_id() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for workflow in DEFAULTS:
        for stage in _definitions(workflow):
            found.setdefault(stage.id, set()).add(workflow)
    return found


def _kinds_by_id() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for workflow in DEFAULTS:
        for stage in _definitions(workflow):
            found.setdefault(stage.id, set()).add(_kind_of(workflow, stage.id))
    return found


# --------------------------------------------------------------------------- #
# The document's side
# --------------------------------------------------------------------------- #


def _inventory_section(workflow: str) -> str:
    return _section(_doc(), f"### `{workflow}` — stage inventory")


def _documented_inventory(workflow: str) -> list[list[str]]:
    table = _table(_inventory_section(workflow))
    assert [cell.lower() for cell in table[0]] == [
        "id",
        "runtime name",
        "agent",
        "prompt",
        "variables",
        "runs when",
        "context",
    ], f"unexpected `{workflow}` inventory header: {table[0]}"
    rows = table[1:]
    for row in rows:
        assert len(row) == 7, (
            f"`{workflow}` inventory row for {row[0]} must have 7 columns, got {len(row)}: {row}"
        )
    return [[_plain(cell) for cell in row] for row in rows]


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_document_exists_and_names_its_drift_guard() -> None:
    """The reference is shipped and says what keeps it true."""
    assert DOC_PATH.is_file()
    doc = _doc()
    assert "tests/test_workflow_stages_doc.py" in doc
    assert "docs/target-repo-config.md" in doc or "target-repo-config.md" in doc


def test_workflow_set_is_the_registry() -> None:
    """One ``### `<workflow>` — stage inventory`` section per registered workflow, no more."""
    doc = _doc()
    documented = set(
        re.findall(r"^### `([A-Za-z0-9_-]+)` — stage inventory$", doc, re.MULTILINE)
    )
    assert documented == set(DEFAULTS), (
        "documented workflow inventories differ from stage_registry.DEFAULTS: "
        f"missing={set(DEFAULTS) - documented}, extra={documented - set(DEFAULTS)}"
    )


@pytest.mark.parametrize("workflow", sorted(DEFAULTS))
def test_stage_inventory_matches_the_registry(workflow: str) -> None:
    """Every field the tables claim, for every stage, in plan order."""
    documented = _documented_inventory(workflow)
    expected = _expected_rows(workflow)
    assert documented == expected, (
        f"`{workflow}` stage inventory drifted from aidw/stage_registry.py\n"
        f"documented: {documented}\nexpected:   {expected}"
    )


def test_id_vocabulary_is_closed_and_classified() -> None:
    """The id table is exactly the flat vocabulary plus the loop labels, correctly classified."""
    rows = _rows(_section(_doc(), "### The stage ids"))
    documented = {_plain(row[0]) for row in rows}
    assert documented == set(STAGE_IDS) | LOOP_LABELS, (
        "documented stage ids differ from STAGE_IDS plus the loop-internal labels: "
        f"missing={set(STAGE_IDS) | LOOP_LABELS - documented}, "
        f"extra={documented - (set(STAGE_IDS) | LOOP_LABELS)}"
    )

    for row in rows:
        stage_id = _plain(row[0])
        kind = _plain(row[1])
        workflows = {part.strip() for part in _plain(row[2]).split(",") if part.strip()}
        assert workflows == _workflows_by_id()[stage_id], (
            f"stage `{stage_id}` is documented for {sorted(workflows)} but the registry runs "
            f"it in {sorted(_workflows_by_id()[stage_id])}"
        )
        assert {kind} == _kinds_by_id()[stage_id], (
            f"stage `{stage_id}` is documented as {kind} but classified "
            f"{sorted(_kinds_by_id()[stage_id])} by validate_stage_list's rule"
        )


def test_every_stage_id_is_one_kind_in_every_workflow() -> None:
    """A shared id (``I7``, ``A1``) must not change kind between workflows."""
    for stage_id, kinds in _kinds_by_id().items():
        assert len(kinds) == 1, (
            f"stage `{stage_id}` is {sorted(kinds)} in different workflows; the id table can "
            "only document one kind, so the registry must not disagree with itself"
        )


def test_condition_table_names_exactly_the_declarable_tokens() -> None:
    """A new ``when=`` token must be documented before it can ship."""
    rows = _rows(_section(_doc(), "### Conditions"))
    documented = {_plain(row[0]) for row in rows}
    expected = {
        WHEN_FINDINGS,
        WHEN_BLOCKING,
        WHEN_COULD_FIX,
        WHEN_UNPARSEABLE,
        WHEN_EVIDENCE_GREEN,
    }
    assert documented == expected, (
        f"condition tokens drifted: missing={expected - documented}, "
        f"extra={documented - expected}"
    )


def test_context_table_names_exactly_the_context_blocks() -> None:
    """The labels the prose uses and the kinds the registry attaches are the same set."""
    rows = _rows(_section(_doc(), "### Context blocks"))
    documented = {_plain(row[0]) for row in rows}
    used = set(CONTEXT_LABELS.values()) | set(BRIEF_LABELS.values())
    assert documented == used, (
        f"context blocks drifted: missing={used - documented}, extra={documented - used}"
    )


def test_gates_table_matches_the_workflow_constants() -> None:
    """Renaming a gate in a workflow module without the reference fails here."""
    from aidw.workflows import approve as approve_workflow
    from aidw.workflows import fix as fix_workflow
    from aidw.workflows import implement as implement_workflow
    from aidw.workflows import prompt as prompt_workflow

    expected = {
        "prompt": {prompt_workflow.GATE},
        "implement": {implement_workflow.GATE},
        "review": set(),
        "fix": {fix_workflow.GATE_FOLLOWUPS, fix_workflow.GATE_FIX_PR},
        "approve": {approve_workflow.GATE},
    }

    rows = _rows(_section(_doc(), "## Gates"))
    documented: dict[str, set[str]] = {}
    for row in rows:
        workflow = _plain(row[0])
        assert workflow in DEFAULTS, f"gates table names unknown workflow `{workflow}`"
        cell = row[1]
        documented[workflow] = (
            set() if _plain(cell).lower() == "none" else set(re.findall(r"`([^`]+)`", cell))
        )

    assert documented == expected, (
        "gates table drifted from the workflow modules' gate constants\n"
        f"documented: {documented}\nexpected:   {expected}"
    )


def test_documented_prompt_files_are_shipped_and_required() -> None:
    """Every prompt file the tables name is in the toolkit's required inventory."""
    named: set[str] = set()
    for workflow in DEFAULTS:
        rows = _table(_inventory_section(workflow))
        for row in rows:
            for cell in row:
                named.update(re.findall(r"[\w-]+\.md", cell))
    assert named, "no prompt files found in the inventory tables"
    unknown = named - set(REQUIRED_PROMPTS)
    assert not unknown, (
        f"docs/workflow-stages.md names prompts missing from REQUIRED_PROMPTS: {sorted(unknown)}"
    )


def test_name_keyed_workflows_are_the_documented_ones() -> None:
    """`prompt`/`fix` plan a repo-added stage but never run it; the doc must say which."""
    from aidw.runner import _NAME_KEYED_WORKFLOWS

    section = _section(_doc(), "## Declaring stages in a target repo")
    lines = section.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith("- **Repo-added stages run in")),
        None,
    )
    assert start is not None, "the repo-added-stage caveat is missing"

    bullet: list[str] = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("- ") or not line.strip():
            break
        bullet.append(line)
    text = " ".join(bullet)
    runs, _, stops = text.partition("not in")

    walkers = set(DEFAULTS) - _NAME_KEYED_WORKFLOWS
    for workflow in sorted(walkers):
        assert f"`{workflow}`" in runs, (
            f"`{workflow}` walks the plan and runs a repo-added stage, but the doc does not "
            "list it on the running side of the caveat"
        )
    for workflow in sorted(_NAME_KEYED_WORKFLOWS):
        assert f"`{workflow}`" in stops, (
            f"`{workflow}` is name-keyed and never runs a repo-added stage, but the doc does "
            "not list it on the not-running side of the caveat"
        )


def test_default_parallel_pair_is_documented() -> None:
    """``implement``'s default ``parallel_groups`` is the safe pair the doc claims."""
    pair = get_workflow("implement").parallel_groups
    assert pair, "implement must still declare its default parallel pair"
    doc = _doc()
    for group in pair:
        for member in group:
            assert member in doc, f"default parallel member `{member}` is undocumented"


def test_readme_implement_block_lists_the_registry_chain() -> None:
    """the operator guide's ``aidw implement`` block matches the static chain, in order."""
    readme = (toolkit_root() / "README.md").read_text(encoding="utf-8")
    block = re.search(
        r"```text\n(.*?)```",
        readme[readme.index("### `aidw implement`") :],
        re.DOTALL,
    )
    assert block is not None, "README has no rendered `aidw implement` stage block"

    listed = [
        (match.group(1), match.group(2))
        for match in re.finditer(r"^([A-Z]\d+)\s+(\S+)", block.group(1), re.MULTILINE)
    ]
    expected = [(stage.id, stage.name) for stage in get_workflow("implement").stages]
    assert listed == expected, (
        "README's `aidw implement` block drifted from the registry's static chain\n"
        f"listed:   {listed}\nexpected: {expected}"
    )
