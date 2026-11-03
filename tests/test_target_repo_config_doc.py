"""Consistency checks pinning ``docs/target-repo-config.md`` to the loader (E3.6).

The document is the operator contract for ``<target>/aidw/config.yaml``
(EXTRACTION.md §3.4); this module is its executable half. Following
``tests/test_design_doc.py``, the doc is read from the toolkit root and asserted
against the code, so prose drift fails here instead of at a reader's desk:

- the field inventory names **exactly** the keys the loader accepts — every key in
  ``TOP_LEVEL_KEYS``/``REPO_FIELDS``/``PATH_FIELDS``/``WORKFLOW_KEYS``/``STAGE_KEYS``/
  ``GITHUB_KEYS``/``MARKER_FIELDS``/``LABEL_KEYS`` and nothing else — and the three
  stage fields the loader rejects (``model``/``thinking``/``timeout_seconds``, E4.6's)
  are documented as rejected, never as configurable;
- each documented default equals ``TOOLKIT_DEFAULTS`` / ``DEFAULT_MAX_REVISIONS`` (the
  literals ``tests/test_target_config.py::
  test_every_seeded_default_is_the_section_3_4_mythical_forge_value`` pins), with the
  genuinely unset fields (``schema_version``, ``requires_toolkit``, ``github.*``,
  ``workflows.*``) marked ``unset`` rather than presented as defaulting;
- the three fenced ```yaml examples are extracted **from the doc** — the doc↔code drift
  guard is that a reader's copy-paste target is what gets loaded — and each loads through
  ``load_target_config`` with zero ``ERROR`` issues and resolves through ``resolve_config``
  to the values the prose claims; they are pairwise distinct and Minimal is
  ``schema_version``-only, so a Typical that merely duplicates Minimal fails;
- both precedence layers are pinned: the four-step prompt order and the
  ``override > config > default`` value order, so an edit that flattens or swaps them fails;
- resolving the examples is pure: ``TOOLKIT_DEFAULTS`` is not mutated and no resolved
  container aliases the declared config or the defaults.

Deliberately *not* tested here: path existence (E3.7), the enforced stage-id vocabulary
(E4.1/E4.5), and anything the loader does not accept — the doc states those contracts but
does not implement them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aidw.config import ERROR
from aidw.paths import toolkit_root
from aidw.target_config import (
    DEFAULT_MAX_REVISIONS,
    GITHUB_KEYS,
    LABEL_KEYS,
    MARKER_FIELDS,
    PATH_FIELDS,
    REPO_FIELDS,
    SOURCE_CONFIG,
    SOURCE_DEFAULT,
    STAGE_KEYS,
    TOP_LEVEL_KEYS,
    TOOLKIT_DEFAULTS,
    WORKFLOW_KEYS,
    ConfigDefaults,
    format_issues,
    load_target_config,
    resolve_config,
)

DOC_PATH = toolkit_root() / "docs" / "target-repo-config.md"

#: Every key the loader accepts, taken from the module's own field-name constants rather
#: than re-typed, so a new key the doc forgets (or a stale key the doc keeps) fails here.
DOCUMENTED_KEYS: frozenset[str] = frozenset(
    key
    for group in (
        TOP_LEVEL_KEYS,
        REPO_FIELDS,
        PATH_FIELDS,
        WORKFLOW_KEYS,
        STAGE_KEYS,
        GITHUB_KEYS,
        MARKER_FIELDS,
        LABEL_KEYS,
    )
    for key in group
)

#: The stage fields E4.6 owns and the loader rejects (`STAGE_KEYS` excludes them). The doc
#: must name them only to say so: listing them as configurable would contradict both.
REJECTED_STAGE_KEYS = ("model", "thinking", "timeout_seconds")

#: The expected ``Default`` cell for every documented key, given as a hand-checked vector.
#: Value-bearing keys are derived from ``TOOLKIT_DEFAULTS``/``DEFAULT_MAX_REVISIONS`` — the
#: point is that the *doc* states what the code resolves — while ``unset``/``required``
#: record the absence of a default (see the doc's "Unset, not defaulted" section).
EXPECTED_DEFAULTS: dict[str, str] = {
    # Top level. `schema_version` is required in a file but has no toolkit default, which
    # is exactly the distinction the doc must not blur.
    "schema_version": "unset",
    "requires_toolkit": "unset",
    "max_revisions": f"`{DEFAULT_MAX_REVISIONS}`",
    "repo": "unset",
    "paths": "unset",
    "workflows": "unset",
    "github": "unset",
    # repo:
    "base_branch": f"`{TOOLKIT_DEFAULTS.repo.base_branch}`",
    "branch_pattern": f"`{TOOLKIT_DEFAULTS.repo.branch_pattern}`",
    # paths:
    **{
        name: f"`{getattr(TOOLKIT_DEFAULTS.paths, name)}`"
        for name in PATH_FIELDS
    },
    # workflows: / stage entry
    "stages": "unset",
    "parallel_groups": "unset",
    "id": "required",
    "enabled": "`true`",
    "prompt": "unset",
    "agent": "unset",
    # github: markers / labels (E6's defaults, unseeded today)
    "markers": "unset",
    "labels": "unset",
    "parent": "unset",
    "child": "unset",
    "summary": "unset",
    "color": "required",
    "description": "required",
}

MINIMAL_PATHS = frozenset(
    {
        "schema_version",
        "requires_toolkit",
        "max_revisions",
        "repo.base_branch",
        "repo.branch_pattern",
        "paths.roadmap_dir",
        "paths.roadmap_glob",
        "paths.task_prompts_dir",
        "paths.implementation_results_dir",
        "paths.build_results_template",
        "paths.architecture_dir",
        "github.markers.parent",
        "github.markers.child",
        "github.markers.summary",
    }
)

FULL_PATHS = frozenset(
    {
        "schema_version",
        "requires_toolkit",
        "max_revisions",
        "repo.base_branch",
        "repo.branch_pattern",
        "paths.roadmap_dir",
        "paths.roadmap_glob",
        "paths.task_prompts_dir",
        "paths.implementation_results_dir",
        "paths.build_results_template",
        "paths.architecture_dir",
        "github.markers.parent",
        "github.markers.child",
        "github.markers.summary",
        "github.labels.review-follow-up.color",
        "github.labels.review-follow-up.description",
        "github.labels.must-fix.color",
        "github.labels.must-fix.description",
        "github.labels.should-fix.color",
        "github.labels.should-fix.description",
        "github.labels.could-fix.color",
        "github.labels.could-fix.description",
        "github.labels.decision-pending.color",
        "github.labels.decision-pending.description",
        "github.labels.approve-fix.color",
        "github.labels.approve-fix.description",
        "workflows.prompt.stages",
        "workflows.implement.stages",
        "workflows.implement.parallel_groups",
    }
)

_YAML_FENCE = re.compile(r"```yaml\n(.*?)```", re.DOTALL)
_FIELD_ROW = re.compile(r"^\|\s*`([a-z_]+)`\s*\|(.+)\|\s*$")


# ---------------------------------------------------------------------------
# Doc reading helpers
# ---------------------------------------------------------------------------


def _doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _section(doc: str, prefix: str, *, level: int) -> str:
    """The block headed by ``prefix``, up to the next heading of ``level`` or shallower.

    ``level=2`` keeps a ``##`` section's ``###``/``####`` subsections; ``level=3`` stops at
    the next ``#``/``##``/``###`` heading. Raises rather than returning ``""`` when the
    heading is missing, so a renamed section is a loud failure.
    """
    lines = doc.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if line.startswith(prefix)), None
    )
    assert start is not None, f"missing heading {prefix!r} in {DOC_PATH.name}"
    stop = re.compile(rf"^#{{1,{level}}} ")
    for index in range(start + 1, len(lines)):
        if stop.match(lines[index]):
            return "\n".join(lines[start:index])
    return "\n".join(lines[start:])


def _field_rows(section: str) -> dict[str, list[str]]:
    """Every ``| `key` | type | default | effect |`` row, keyed by the key.

    Only rows whose first cell is a bare backticked key count as *documented fields*, which
    is what lets the rejected stage fields appear in prose without counting as accepted.
    """
    rows: dict[str, list[str]] = {}
    for line in section.splitlines():
        match = _FIELD_ROW.match(line)
        if match is None:
            continue
        key = match.group(1)
        cells = [cell.strip() for cell in match.group(2).split("|")]
        assert len(cells) == 3, f"row for {key!r} must have type/default/effect columns"
        assert key not in rows, f"duplicate field row for {key!r}"
        rows[key] = cells
    return rows


def _inventory_rows() -> dict[str, list[str]]:
    return _field_rows(_section(_doc(), "## Field inventory", level=2))


def _example(name: str) -> str:
    """The single ```yaml block under ``### <name>``."""
    section = _section(_doc(), f"### {name}", level=3)
    blocks = _YAML_FENCE.findall(section)
    assert len(blocks) == 1, (
        f"expected exactly one ```yaml block under '### {name}', found {len(blocks)}"
    )
    return blocks[0]


def _load_example(tmp_path: Path, text: str):
    path = tmp_path / "aidw" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    declared = load_target_config(path)
    errors = [issue.message for issue in declared.issues if issue.level == ERROR]
    assert errors == [], format_issues(declared.issues)
    return declared


def _resolve_example(tmp_path: Path, text: str):
    return resolve_config(_load_example(tmp_path, text))


def _values(resolved) -> dict[str, object]:
    return {path: entry.value for path, entry in resolved.items()}


# ---------------------------------------------------------------------------
# The document's shape: it is the contract, not a placeholder
# ---------------------------------------------------------------------------


def test_doc_is_not_the_placeholder():
    """E3.6's Done-when: the placeholder body is gone, the schema pointer is kept."""
    doc = _doc()

    assert "**Placeholder.**" not in doc
    assert "This document is written in task E3.6" not in doc
    # The machine-readable counterpart stays referenced.
    assert "docs/schema/aidw-config.schema.json" in doc


def test_doc_states_the_tracked_layout_and_the_no_folder_case():
    """§3.4: `config.yaml` required if the folder exists; *no* folder is valid."""
    doc = _doc()

    assert "config.yaml" in doc
    assert "required if the folder exists" in doc
    assert "conventions.md" in doc
    assert "aidw/prompts/" in doc
    assert "no `aidw/` folder" in doc
    assert "pure defaults" in doc


def test_doc_states_the_read_path_contract_and_the_write_target_exemption():
    """§3.4 + E3.7: all four read-paths, `architecture_dir` as write-target."""
    doc = _doc()

    for field in (
        "paths.build_results_template",
        "paths.roadmap_dir",
        "paths.task_prompts_dir",
        "paths.implementation_results_dir",
    ):
        assert field in doc
    assert "write-target" in doc
    assert "paths.architecture_dir" in doc
    # The contract is stated here; the enforcement is E3.7's.
    assert "E3.7" in doc


# ---------------------------------------------------------------------------
# Field inventory: exactly the loader's keys, with the defaults it resolves
# ---------------------------------------------------------------------------


def test_field_inventory_documents_exactly_the_loader_keys():
    """Every accepted key is documented, and no rejected one is documented as a field."""
    rows = _inventory_rows()

    missing = DOCUMENTED_KEYS - set(rows)
    assert not missing, f"undocumented keys: {sorted(missing)}"
    extra = set(rows) - DOCUMENTED_KEYS
    assert not extra, f"documented keys the loader rejects: {sorted(extra)}"
    # The expectation table covers every key too, so a new key needs a default decision.
    assert set(EXPECTED_DEFAULTS) == DOCUMENTED_KEYS


def test_documented_defaults_are_the_toolkit_defaults():
    """The doc's stated defaults equal `TOOLKIT_DEFAULTS` + `DEFAULT_MAX_REVISIONS`."""
    rows = _inventory_rows()

    for key, expected in EXPECTED_DEFAULTS.items():
        assert rows[key][1] == expected, (
            f"{key}: doc says default {rows[key][1]!r}, code resolves {expected!r}"
        )


def test_stage_fields_the_loader_rejects_are_documented_as_rejected():
    """`model`/`thinking`/`timeout_seconds` (E4.6's) are not configurable today."""
    doc = _doc()
    rows = _inventory_rows()

    assert not set(REJECTED_STAGE_KEYS) & set(rows)

    mentions = [
        line
        for line in doc.splitlines()
        if all(key in line for key in REJECTED_STAGE_KEYS)
    ]
    assert len(mentions) == 1, "expected one sentence naming all three rejected keys"
    sentence = mentions[0]
    assert "not" in sentence
    assert "reject" in sentence


def test_loader_fails_closed_on_the_stage_fields_the_doc_calls_rejected(
    tmp_path: Path,
):
    """Proves the doc's claim instead of restating it: each key is an ERROR issue."""
    path = tmp_path / "aidw" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)

    for key in REJECTED_STAGE_KEYS:
        path.write_text(
            "schema_version: 1\n"
            "workflows:\n"
            "  implement:\n"
            "    stages:\n"
            f"      - id: implement\n"
            f"        {key}: x\n",
            encoding="utf-8",
        )
        declared = load_target_config(path)
        errors = [
            issue.message
            for issue in declared.issues
            if issue.level == ERROR
        ]
        assert any(
            f"workflows.implement.stages[0].{key}" in message for message in errors
        ), f"{key}: expected an unknown-key error naming the field path, got {errors}"


# ---------------------------------------------------------------------------
# Precedence: two layers, both pinned
# ---------------------------------------------------------------------------


def test_value_precedence_order_is_documented():
    """`override > config > default` (then unset), with design §12's flag named."""
    section = _section(_doc(), "### Value resolution", level=3)

    assert "override > config > default > unset" in section
    assert "--max-revisions" in section


def test_prompt_precedence_order_is_documented():
    """The four prompt steps, in order: explicit path → shadow → toolkit → error."""
    section = _section(_doc(), "### Prompt resolution", level=3)

    anchors = [
        "an explicit `prompt:` path",
        "`<target>/aidw/prompts/`",
        "the **toolkit default** prompt",
        "never a silent skip",
    ]
    positions = [section.index(anchor) for anchor in anchors]
    assert positions == sorted(positions), f"prompt precedence out of order: {positions}"
    assert len(set(positions)) == len(anchors)


# ---------------------------------------------------------------------------
# Worked examples: extracted from the doc, loaded, resolved
# ---------------------------------------------------------------------------


def test_doc_has_exactly_three_yaml_examples():
    """Every ```yaml fence is a worked example the tests below load (no stray snippets)."""
    doc = _doc()

    assert len(_YAML_FENCE.findall(doc)) == 3
    for name in ("Minimal", "Typical", "Full"):
        assert _example(name).strip()


def test_examples_are_pairwise_distinct_and_minimal_is_schema_version_only(
    tmp_path: Path,
):
    minimal = _example("Minimal")
    typical = _example("Typical")
    full = _example("Full")

    assert len({minimal, typical, full}) == 3, "examples must be pairwise distinct"
    # Minimal declares nothing but the schema version — a Typical that duplicates it fails.
    assert _load_example(tmp_path, minimal).to_dict() == {"schema_version": 1}
    assert _load_example(tmp_path, typical).to_dict() != {"schema_version": 1}


def test_minimal_resolves_to_the_mythical_forge_layout(tmp_path: Path):
    """D17/E3.4: `schema_version: 1` alone must produce the full default layout."""
    resolved = _resolve_example(tmp_path, _example("Minimal"))

    assert set(resolved) == MINIMAL_PATHS
    assert _values(resolved) == {
        "schema_version": 1,
        "requires_toolkit": None,
        "max_revisions": 3,
        "repo.base_branch": "main",
        "repo.branch_pattern": "{phase}-{task}",
        "paths.roadmap_dir": "docs/tasks",
        "paths.roadmap_glob": "[0-9]* - *.md",
        "paths.task_prompts_dir": "docs/task-prompts",
        "paths.implementation_results_dir": "docs/implementation-results",
        "paths.build_results_template": "docs/implementation-results/TEMPLATE.md",
        "paths.architecture_dir": "docs/architecture",
        "github.markers.parent": None,
        "github.markers.child": None,
        "github.markers.summary": None,
    }
    # Provenance: the eight repo/paths leaves and the budget come from the defaults, the
    # declared schema version from the file, and the unseeded fields are unset.
    for path, entry in resolved.items():
        if path == "schema_version":
            assert entry.source == SOURCE_CONFIG
        elif path in {"requires_toolkit"} or path.startswith("github.markers."):
            assert entry.source is None, f"{path} must resolve unset"
        else:
            assert entry.source == SOURCE_DEFAULT, f"{path} must resolve from the defaults"


def test_typical_resolves_to_the_same_values_with_configured_provenance(
    tmp_path: Path,
):
    """The D17 example echoes two defaults: same values, `config` provenance for those two."""
    minimal = _resolve_example(tmp_path, _example("Minimal"))
    typical = _resolve_example(tmp_path, _example("Typical"))

    assert _values(typical) == _values(minimal)
    assert set(typical) == set(minimal)
    assert {
        path for path, entry in typical.items() if entry.source == SOURCE_CONFIG
    } == {"schema_version", "repo.base_branch", "paths.roadmap_glob"}


def test_full_example_declares_every_field_and_resolves_from_config(tmp_path: Path):
    """§3.4's own YAML, with `max_revisions` added: every leaf resolves `config`."""
    resolved = _resolve_example(tmp_path, _example("Full"))

    assert set(resolved) == FULL_PATHS
    assert all(entry.source == SOURCE_CONFIG for entry in resolved.values())

    values = _values(resolved)
    assert values["schema_version"] == 1
    assert values["requires_toolkit"] == ">=1.0.0"
    assert values["max_revisions"] == 3
    assert values["repo.base_branch"] == "main"
    assert values["repo.branch_pattern"] == "{phase}-{task}"
    assert values["paths.roadmap_glob"] == "[0-9]* - *.md"
    assert values["paths.build_results_template"] == (
        "docs/implementation-results/TEMPLATE.md"
    )
    # D5 literals: the marker templates and every label survive verbatim.
    assert values["github.markers.parent"] == (
        "<!-- mythical-forge-review-followups: pr={pr_url} -->"
    )
    assert values["github.markers.child"] == (
        "<!-- mythical-forge-review-follow-up: pr={pr_url} finding={finding_id} -->"
    )
    assert values["github.markers.summary"] == (
        "<!-- mythical-forge-review-followups-summary: pr={pr_url} -->"
    )
    assert values["github.labels.must-fix.color"] == "B60205"
    assert values["github.labels.must-fix.description"] == "Blocking review finding"
    assert values["github.labels.approve-fix.color"] == "B8D64A"
    # The stage model (D12/D13 shape only — the vocabulary is E4.1/E4.5's).
    assert [stage["id"] for stage in values["workflows.prompt.stages"]] == [
        "author",
        "review",
    ]
    implement = values["workflows.implement.stages"]
    assert [stage["id"] for stage in implement] == [
        "implement",
        "test",
        "record",
        "pr",
        "traceability",
        "architecture",
    ]
    traceability = implement[4]
    assert traceability["enabled"] is True
    assert traceability["prompt"] == "aidw/prompts/update-traceability.md"
    assert traceability["agent"] == "implementer"
    assert implement[5]["enabled"] is True
    assert values["workflows.implement.parallel_groups"] == [["test", "architecture"]]


def test_resolving_the_examples_is_pure(tmp_path: Path):
    """No I/O, no aliasing, no mutation of `TOOLKIT_DEFAULTS`; re-resolution is stable."""
    full = _example("Full")

    first = _resolve_example(tmp_path, full)
    second = _resolve_example(tmp_path, full)
    assert first == second
    assert TOOLKIT_DEFAULTS == ConfigDefaults()

    # Mutating a resolved container must not corrupt a later resolution (fresh containers,
    # never an alias of the declared config or the global defaults).
    first["workflows.implement.stages"].value.clear()
    assert _resolve_example(tmp_path, full) == second
    assert TOOLKIT_DEFAULTS == ConfigDefaults()


@pytest.mark.parametrize("name", ["Minimal", "Typical", "Full"])
def test_each_example_loads_with_no_error_issues(tmp_path: Path, name: str):
    """Fail-closed: a fenced example the loader rejects is a broken doc, not a nit."""
    declared = _load_example(tmp_path, _example(name))

    assert [issue for issue in declared.issues if issue.level == ERROR] == []
    assert declared.source_path is not None
