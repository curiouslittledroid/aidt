"""Contract tests for the target-repo config loader (EXTRACTION.md §3.4, task E3.1).

These tests are the executable specification of :mod:`aidw.target_config`:

- a full §3.4-shaped config loads with zero issues and every field populated;
- a ``schema_version: 1``-only config and a *missing* config file both load cleanly
  (E3.1 proves they load; producing the Mythical Forge layout is E3.4's);
- unknown keys at every object level, wrong types, out-of-set ``enabled`` values and
  missing required keys each fail with the offending field path;
- YAML → dataclass → dict → YAML is lossless (the declared config is reproduced, no
  defaults injected) and pure (no file writes, no input mutation, no shared containers);
- ``docs/schema/aidw-config.schema.json`` agrees field-for-field with the dataclasses.

The loader deliberately does not merge defaults (E3.2/E3.4), compare versions (E3.3),
validate path existence (E3.7), or own the stage-id vocabulary (E4.1/E4.5); no test here
asks it to.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from aidw.config import ERROR
from aidw.paths import toolkit_root
from aidw.target_config import (
    GitHubConfig,
    LabelConfig,
    MarkersConfig,
    PathsConfig,
    RepoConfig,
    StageConfig,
    TargetConfig,
    WorkflowConfig,
    format_issues,
    load_target_config,
)

#: The §3.4 example, with every field E3.1 owns populated. Deliberately declares an
#: explicit ``enabled: true`` as well as an ``enabled: false`` so the round-trip proves
#: both survive (the former equals the default and would be lost without presence
#: tracking).
FULL_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "requires_toolkit": ">=1.0.0",
    "max_revisions": 3,
    "repo": {
        "base_branch": "main",
        "branch_pattern": "{phase}-{task}",
    },
    "paths": {
        "roadmap_dir": "docs/tasks",
        "roadmap_glob": "[0-9]* - *.md",
        "task_prompts_dir": "docs/task-prompts",
        "implementation_results_dir": "docs/implementation-results",
        "build_results_template": "docs/implementation-results/TEMPLATE.md",
        "architecture_dir": "docs/architecture",
    },
    "workflows": {
        "prompt": {
            "stages": [{"id": "author"}, {"id": "review"}],
        },
        "implement": {
            "stages": [
                {"id": "implement"},
                {"id": "test"},
                {"id": "record"},
                {"id": "pr"},
                {
                    "id": "traceability",
                    "enabled": True,
                    "prompt": "aidw/prompts/update-traceability.md",
                    "agent": "implementer",
                },
                {"id": "architecture", "enabled": False},
            ],
            "parallel_groups": [["test", "architecture"]],
        },
    },
    "github": {
        "markers": {
            "parent": "<!-- mythical-forge-review-followups: pr={pr_url} -->",
            "child": "<!-- mythical-forge-review-follow-up: pr={pr_url} finding={finding_id} -->",
            "summary": "<!-- mythical-forge-review-followups-summary: pr={pr_url} -->",
        },
        "labels": {
            "must-fix": {
                "color": "B60205",
                "description": "Blocking review finding",
            },
        },
    },
}

GITHUB_CONFIG_KEYS = {"markers", "labels"}
REPO_CONFIG_KEYS = {"base_branch", "branch_pattern"}
PATHS_CONFIG_KEYS = {
    "roadmap_dir",
    "roadmap_glob",
    "task_prompts_dir",
    "implementation_results_dir",
    "build_results_template",
    "architecture_dir",
}
MARKERS_CONFIG_KEYS = {"parent", "child", "summary"}
STAGE_CONFIG_KEYS = {"id", "enabled", "prompt", "agent"}
LABEL_CONFIG_KEYS = {"color", "description"}
TOP_LEVEL_CONFIG_KEYS = {
    "schema_version",
    "requires_toolkit",
    "max_revisions",
    "repo",
    "paths",
    "workflows",
    "github",
}

#: Fields ``TargetConfig`` carries for provenance/validation, not as config keys.
NON_SCHEMA_TARGET_FIELDS = {"source_path", "issues"}

SCHEMA_PATH = toolkit_root() / "docs" / "schema" / "aidw-config.schema.json"


def _write_config(tmp_path: Path, config: dict[str, Any]) -> Path:
    path = tmp_path / "aidw" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _write_text(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "aidw" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _load(tmp_path: Path, config: dict[str, Any]) -> TargetConfig:
    return load_target_config(_write_config(tmp_path, config))


def _errors(config: TargetConfig) -> list[str]:
    return [issue.message for issue in config.issues if issue.level == ERROR]


def _dataclass_fields(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls) if not f.name.startswith("_")}


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_full_section_3_4_config_loads_with_every_field_populated(tmp_path: Path) -> None:
    path = _write_config(tmp_path, FULL_CONFIG)

    config = load_target_config(path)

    assert config.issues == []
    assert config.schema_version == 1
    assert config.requires_toolkit == ">=1.0.0"
    assert config.max_revisions == 3
    assert config.source_path == path

    assert config.repo == RepoConfig(
        base_branch="main", branch_pattern="{phase}-{task}"
    )
    assert config.paths == PathsConfig(
        roadmap_dir="docs/tasks",
        roadmap_glob="[0-9]* - *.md",
        task_prompts_dir="docs/task-prompts",
        implementation_results_dir="docs/implementation-results",
        build_results_template="docs/implementation-results/TEMPLATE.md",
        architecture_dir="docs/architecture",
    )

    assert set(config.workflows) == {"prompt", "implement"}
    assert [stage.id for stage in config.workflows["prompt"].stages] == [
        "author",
        "review",
    ]

    implement = config.workflows["implement"]
    assert [stage.id for stage in implement.stages] == [
        "implement",
        "test",
        "record",
        "pr",
        "traceability",
        "architecture",
    ]
    traceability = implement.stages[4]
    assert traceability.enabled is True
    assert traceability.prompt == "aidw/prompts/update-traceability.md"
    assert traceability.agent == "implementer"
    assert implement.stages[5].enabled is False
    assert implement.parallel_groups == [["test", "architecture"]]

    assert config.github is not None
    assert config.github.markers == MarkersConfig(
        parent="<!-- mythical-forge-review-followups: pr={pr_url} -->",
        child="<!-- mythical-forge-review-follow-up: pr={pr_url} finding={finding_id} -->",
        summary="<!-- mythical-forge-review-followups-summary: pr={pr_url} -->",
    )
    assert config.github.labels["must-fix"] == LabelConfig(
        color="B60205", description="Blocking review finding"
    )


def test_schema_version_only_config_loads_without_error(tmp_path: Path) -> None:
    """E3.1 only proves this *loads*; the Mythical Forge layout is E3.4's test."""
    config = _load(tmp_path, {"schema_version": 1})

    assert config.issues == []
    assert config.schema_version == 1
    assert config.repo is None
    assert config.paths is None
    assert config.github is None
    assert config.workflows == {}
    assert config.to_dict() == {"schema_version": 1}


def test_missing_config_file_is_valid_defaults_with_no_issues(tmp_path: Path) -> None:
    """§3.4: a target repo with no ``aidw/`` folder gets the toolkit defaults."""
    path = tmp_path / "target" / "aidw" / "config.yaml"
    assert not path.parent.exists()

    config = load_target_config(path)

    assert config.issues == []
    assert config == TargetConfig()
    assert config.to_dict() == {}
    assert config.source_path is None


def test_stage_enabled_defaults_true_and_explicit_values_are_kept(tmp_path: Path) -> None:
    config = _load(
        tmp_path,
        {
            "schema_version": 1,
            "workflows": {
                "implement": {
                    "stages": [
                        {"id": "implement"},
                        {"id": "architecture", "enabled": False},
                    ]
                }
            },
        },
    )

    assert config.issues == []
    assert config.workflows["implement"].stages[0].enabled is True
    assert config.workflows["implement"].stages[1].enabled is False
    dumped = config.to_dict()["workflows"]["implement"]["stages"]
    # The default is not injected; the explicit false is preserved.
    assert "enabled" not in dumped[0]
    assert dumped[1]["enabled"] is False


def test_github_labels_are_an_open_map_of_colour_description_entries(
    tmp_path: Path,
) -> None:
    labels = {
        "review-follow-up": {
            "color": "5319E7",
            "description": "Review-generated task or parent issue",
        },
        "approve-fix": {
            "color": "B8D64A",
            "description": "Human-approved review follow-up fix",
        },
    }

    config = _load(
        tmp_path, {"schema_version": 1, "github": {"labels": labels}}
    )

    assert config.issues == []
    assert config.github is not None
    assert set(config.github.labels) == set(labels)
    assert config.github.labels["approve-fix"] == LabelConfig(
        color="B8D64A", description="Human-approved review follow-up fix"
    )


# ---------------------------------------------------------------------------
# Fail-closed: non-mapping input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",  # empty file: yaml.safe_load returns None
        "- a\n- b\n",  # top-level list
        "just a scalar\n",  # top-level scalar
        "null\n",  # explicit null
    ],
    ids=["empty-file", "list", "scalar", "null"],
)
def test_non_mapping_yaml_is_an_error_not_an_attribute_error(
    tmp_path: Path, text: str
) -> None:
    config = load_target_config(_write_text(tmp_path, text))

    assert [issue.level for issue in config.issues] == [ERROR]
    assert "must be a YAML mapping" in config.issues[0].message


def test_unparseable_yaml_is_an_error_not_an_exception(tmp_path: Path) -> None:
    config = load_target_config(_write_text(tmp_path, "schema_version: [unclosed\n"))

    assert [issue.level for issue in config.issues] == [ERROR]
    assert "cannot read/parse config" in config.issues[0].message


# ---------------------------------------------------------------------------
# Fail-closed: unknown keys at every object level
# ---------------------------------------------------------------------------


UNKNOWN_KEY_CASES = [
    pytest.param({"schema_version": 1, "reop": {}}, "reop", id="top-level"),
    pytest.param(
        {"schema_version": 1, "repo": {"basebranch": "main"}},
        "repo.basebranch",
        id="repo",
    ),
    pytest.param(
        {"schema_version": 1, "paths": {"roadmap_dirs": "docs/tasks"}},
        "paths.roadmap_dirs",
        id="paths",
    ),
    pytest.param(
        {"schema_version": 1, "workflows": {"implement": {"paralel_groups": []}}},
        "workflows.implement.paralel_groups",
        id="workflow",
    ),
    pytest.param(
        {
            "schema_version": 1,
            "workflows": {
                "implement": {"stages": [{"id": "implement", "enabld": False}]}
            },
        },
        "workflows.implement.stages[0].enabld",
        id="stage",
    ),
    pytest.param(
        {"schema_version": 1, "github": {"marker": {}}},
        "github.marker",
        id="github",
    ),
    pytest.param(
        {"schema_version": 1, "github": {"markers": {"body": "x"}}},
        "github.markers.body",
        id="markers",
    ),
    pytest.param(
        {
            "schema_version": 1,
            "github": {
                "labels": {"must-fix": {"colr": "B60205", "description": "d"}}
            },
        },
        "github.labels.must-fix.colr",
        id="label-entry",
    ),
]


@pytest.mark.parametrize(("config_data", "path"), UNKNOWN_KEY_CASES)
def test_unknown_key_is_an_error_naming_the_offending_path(
    tmp_path: Path, config_data: dict[str, Any], path: str
) -> None:
    config = _load(tmp_path, config_data)

    assert any(
        f"unknown key `{path}`" in message for message in _errors(config)
    ), format_issues(config.issues)


@pytest.mark.parametrize("key", ["model", "thinking", "timeout_seconds"])
def test_stage_override_fields_are_not_in_this_schema(
    tmp_path: Path, key: str
) -> None:
    """E4.6 owns stage metadata overrides; until then they are unknown keys."""
    config = _load(
        tmp_path,
        {
            "schema_version": 1,
            "workflows": {
                "implement": {"stages": [{"id": "implement", key: "value"}]}
            },
        },
    )

    assert any(
        f"workflows.implement.stages[0].{key}" in message
        for message in _errors(config)
    )


# ---------------------------------------------------------------------------
# Fail-closed: wrong types
# ---------------------------------------------------------------------------


WRONG_TYPE_CASES = [
    pytest.param({"schema_version": "1"}, "schema_version", id="schema-version-str"),
    pytest.param({"schema_version": True}, "schema_version", id="schema-version-bool"),
    pytest.param(
        {"schema_version": 1, "requires_toolkit": 1},
        "requires_toolkit",
        id="requires-toolkit-int",
    ),
    pytest.param(
        {"schema_version": 1, "max_revisions": "3"},
        "max_revisions",
        id="max-revisions-str",
    ),
    pytest.param(
        {"schema_version": 1, "repo": {"base_branch": 7}},
        "repo.base_branch",
        id="repo-base-branch-int",
    ),
    pytest.param(
        {"schema_version": 1, "paths": {"roadmap_dir": ["docs/tasks"]}},
        "paths.roadmap_dir",
        id="paths-roadmap-dir-list",
    ),
    pytest.param(
        {
            "schema_version": 1,
            "workflows": {
                "implement": {"stages": [{"id": "x", "enabled": "yes"}]}
            },
        },
        "workflows.implement.stages[0].enabled",
        id="stage-enabled-str",
    ),
    pytest.param(
        {"schema_version": 1, "workflows": {"implement": {"stages": "nope"}}},
        "workflows.implement.stages",
        id="stages-not-a-list",
    ),
    pytest.param(
        {
            "schema_version": 1,
            "workflows": {"implement": {"parallel_groups": "test"}},
        },
        "workflows.implement.parallel_groups",
        id="parallel-groups-not-a-list",
    ),
    pytest.param(
        {
            "schema_version": 1,
            "workflows": {"implement": {"parallel_groups": [["test", 3]]}},
        },
        "workflows.implement.parallel_groups[0][1]",
        id="parallel-group-member-not-a-string",
    ),
    pytest.param(
        {
            "schema_version": 1,
            "github": {"labels": {"must-fix": {"color": 5, "description": "d"}}},
        },
        "github.labels.must-fix.color",
        id="label-colour-int",
    ),
    pytest.param(
        {"schema_version": 1, "repo": "main"},
        "repo",
        id="repo-not-a-mapping",
    ),
    pytest.param(
        {"schema_version": 1, "repo": None},
        "repo",
        id="repo-null",
    ),
    pytest.param(
        {"schema_version": 1, "paths": None},
        "paths",
        id="paths-null",
    ),
    pytest.param(
        {"schema_version": 1, "workflows": None},
        "workflows",
        id="workflows-null",
    ),
    pytest.param(
        {"schema_version": 1, "github": None},
        "github",
        id="github-null",
    ),
    pytest.param(
        {
            "schema_version": 1,
            "workflows": {"implement": {"stages": [None]}},
        },
        "workflows.implement.stages[0]",
        id="stage-entry-null",
    ),
]


@pytest.mark.parametrize(("config_data", "path"), WRONG_TYPE_CASES)
def test_wrong_type_is_an_error_naming_the_offending_path(
    tmp_path: Path, config_data: dict[str, Any], path: str
) -> None:
    config = _load(tmp_path, config_data)

    messages = _errors(config)
    assert any(f"`{path}`" in message and "must be" in message for message in messages), (
        format_issues(config.issues)
    )


# ---------------------------------------------------------------------------
# Fail-closed: missing required keys
# ---------------------------------------------------------------------------


MISSING_REQUIRED_CASES = [
    pytest.param({"repo": {}}, "schema_version", id="schema-version"),
    pytest.param(
        {
            "schema_version": 1,
            "workflows": {"implement": {"stages": [{"enabled": False}]}},
        },
        "workflows.implement.stages[0].id",
        id="stage-id",
    ),
    pytest.param(
        {
            "schema_version": 1,
            "github": {"labels": {"must-fix": {"description": "d"}}},
        },
        "github.labels.must-fix.color",
        id="label-colour",
    ),
    pytest.param(
        {
            "schema_version": 1,
            "github": {"labels": {"must-fix": {"color": "B60205"}}},
        },
        "github.labels.must-fix.description",
        id="label-description",
    ),
]


@pytest.mark.parametrize(("config_data", "path"), MISSING_REQUIRED_CASES)
def test_missing_required_key_is_an_error_naming_the_path(
    tmp_path: Path, config_data: dict[str, Any], path: str
) -> None:
    config = _load(tmp_path, config_data)

    assert any(
        f"missing required key `{path}`" in message for message in _errors(config)
    ), format_issues(config.issues)


# ---------------------------------------------------------------------------
# Round-trip: lossless and pure
# ---------------------------------------------------------------------------


def test_full_config_round_trip_is_exact_and_lossless(tmp_path: Path) -> None:
    path = _write_config(tmp_path, FULL_CONFIG)
    config = load_target_config(path)

    dumped = config.to_dict()

    # The declared config is reproduced exactly: no defaults injected, no values lost
    # (including the explicit ``enabled: true`` that equals the default).
    assert dumped == FULL_CONFIG

    # Reloading the same file is identical, and a different path compares equal because
    # ``source_path`` is provenance rather than config.
    assert load_target_config(path) == config
    assert load_target_config(_write_config(tmp_path / "again", dumped)) == config


ROUND_TRIP_CASES = [
    pytest.param({"schema_version": 1}, id="minimal"),
    pytest.param(
        {"schema_version": 1, "repo": {}},
        id="empty-repo-container",
    ),
    pytest.param(
        {
            "schema_version": 1,
            "repo": {"base_branch": "main"},
            "paths": {"roadmap_dir": "docs/tasks"},
        },
        id="partial-repo-and-paths",
    ),
    pytest.param(
        {"schema_version": 1, "workflows": {"implement": {"stages": []}}},
        id="explicit-empty-stages",
    ),
    pytest.param(
        {
            "schema_version": 1,
            "workflows": {
                "implement": {"stages": [], "parallel_groups": []}
            },
        },
        id="explicit-empty-stages-and-groups",
    ),
    pytest.param(
        {"schema_version": 1, "github": {"labels": {}, "markers": {}}},
        id="explicit-empty-github-containers",
    ),
    pytest.param(
        {
            "schema_version": 1,
            "workflows": {"implement": {"stages": [{"id": "x", "enabled": True}]}},
        },
        id="explicit-enabled-true",
    ),
    pytest.param(
        {
            "schema_version": 1,
            "workflows": {
                "custom": {
                    "stages": [
                        {
                            "id": "repo-stage",
                            "prompt": "aidw/prompts/repo-stage.md",
                            "agent": "implementer",
                        }
                    ]
                }
            },
        },
        id="repo-added-workflow-and-stage",
    ),
]


@pytest.mark.parametrize("config_data", ROUND_TRIP_CASES)
def test_round_trip_preserves_the_declared_config(
    tmp_path: Path, config_data: dict[str, Any]
) -> None:
    config = _load(tmp_path, config_data)
    assert config.issues == []

    dumped = config.to_dict()

    assert dumped == config_data
    assert load_target_config(_write_config(tmp_path / "again", dumped)) == config


def test_loader_and_serializer_are_pure(tmp_path: Path) -> None:
    """No file writes, no mutation of the declared data, no shared containers."""
    path = _write_config(tmp_path, FULL_CONFIG)
    before_bytes = path.read_bytes()
    before_tree = {item for item in tmp_path.rglob("*")}
    expected = copy.deepcopy(FULL_CONFIG)

    config = load_target_config(path)

    assert path.read_bytes() == before_bytes
    assert {item for item in tmp_path.rglob("*")} == before_tree
    assert FULL_CONFIG == expected

    first = config.to_dict()
    second = config.to_dict()
    assert first == second == expected
    assert first is not second

    # ``to_dict`` returns fresh nested containers; mutating them cannot corrupt the
    # loaded config or the next dump.
    first["workflows"]["implement"]["stages"].clear()
    first["github"]["labels"].clear()
    assert config.to_dict() == expected


def test_issues_reuse_the_agent_config_issue_type_and_formatter(tmp_path: Path) -> None:
    config = _load(tmp_path, {"schema_version": 1, "reop": {}})

    rendered = format_issues(config.issues)

    assert config.issues[0].level == ERROR
    assert config.issues[0].source == "config.yaml"
    assert "error: config.yaml: unknown key `reop`" in rendered


# ---------------------------------------------------------------------------
# JSON Schema agreement
# ---------------------------------------------------------------------------


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _resolve_ref(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        target: Any = schema
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target[part]
        node = target
    return node


def _schema_node(schema: dict[str, Any], path: str) -> dict[str, Any]:
    """Navigate ``prop/nested/*`` (open map) and ``prop/items[]`` (array) steps."""
    node = schema
    for part in [step for step in path.split("/") if step]:
        if part == "*":
            node = _resolve_ref(schema, node["additionalProperties"])
        elif part.endswith("[]"):
            node = _resolve_ref(schema, node["properties"][part[:-2]]["items"])
        else:
            node = _resolve_ref(schema, node["properties"][part])
    return node


SCHEMA_AGREEMENT_CASES = [
    pytest.param("", TargetConfig, ["schema_version"], NON_SCHEMA_TARGET_FIELDS, id="top"),
    pytest.param("repo", RepoConfig, [], set(), id="repo"),
    pytest.param("paths", PathsConfig, [], set(), id="paths"),
    pytest.param("workflows/*", WorkflowConfig, [], set(), id="workflow"),
    pytest.param(
        "workflows/*/stages[]", StageConfig, ["id"], set(), id="stage"
    ),
    pytest.param("github", GitHubConfig, [], set(), id="github"),
    pytest.param("github/markers", MarkersConfig, [], set(), id="markers"),
    pytest.param(
        "github/labels/*",
        LabelConfig,
        ["color", "description"],
        set(),
        id="label",
    ),
]


@pytest.mark.parametrize(
    ("path", "cls", "required", "excluded"), SCHEMA_AGREEMENT_CASES
)
def test_json_schema_properties_agree_with_dataclass_fields(
    path: str, cls: type, required: list[str], excluded: set[str]
) -> None:
    schema = _load_schema()
    node = _schema_node(schema, path)

    assert node["type"] == "object"
    assert node["additionalProperties"] is False
    assert set(node["properties"]) == _dataclass_fields(cls) - excluded
    assert node.get("required", []) == required


def test_json_schema_rejects_unknown_keys_at_every_fixed_object_level() -> None:
    schema = _load_schema()

    fixed_objects = [
        "",
        "repo",
        "paths",
        "github",
        "github/markers",
        "workflows/*",
        "workflows/*/stages[]",
        "github/labels/*",
    ]
    for path in fixed_objects:
        node = _schema_node(schema, path)
        assert node["additionalProperties"] is False, path

    # Open maps: workflow names and label names are repo-defined (D12, D5).
    assert "$ref" in _schema_node(schema, "workflows")["additionalProperties"]
    assert "$ref" in _schema_node(schema, "github/labels")["additionalProperties"]


def test_json_schema_carries_the_boolean_enum_mechanism() -> None:
    """§3.4 fixes no enum beyond ``enabled``; the schema still proves the mechanism."""
    schema = _load_schema()
    stage = _schema_node(schema, "workflows/*/stages[]")
    enabled = stage["properties"]["enabled"]

    assert enabled["type"] == "boolean"
    assert enabled["enum"] == [True, False]


@pytest.mark.parametrize(
    ("cls", "expected"),
    [
        (TargetConfig, TOP_LEVEL_CONFIG_KEYS),
        (GitHubConfig, GITHUB_CONFIG_KEYS),
        (RepoConfig, REPO_CONFIG_KEYS),
        (PathsConfig, PATHS_CONFIG_KEYS),
        (MarkersConfig, MARKERS_CONFIG_KEYS),
        (StageConfig, STAGE_CONFIG_KEYS),
        (LabelConfig, LABEL_CONFIG_KEYS),
        (WorkflowConfig, {"stages", "parallel_groups"}),
    ],
)
def test_dataclass_field_names_are_the_fixed_section_3_4_names(
    cls: type, expected: set[str]
) -> None:
    assert _dataclass_fields(cls) - NON_SCHEMA_TARGET_FIELDS == expected
