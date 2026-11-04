"""Contract tests for the target-repo config loader (EXTRACTION.md §3.4, task E3.1).

These tests are the executable specification of :mod:`aidw.target_config`:

- a full §3.4-shaped config loads with zero issues and every field populated;
- a ``schema_version: 1``-only config and a *missing* config file both load cleanly
  (E3.1 proves they load); E3.4 below proves resolution produces the Mythical Forge
  layout from them;
- unknown keys at every object level, wrong types, out-of-set ``enabled`` values and
  missing required keys each fail with the offending field path;
- YAML → dataclass → dict → YAML is lossless (the declared config is reproduced, no
  defaults injected) and pure (no file writes, no input mutation, no shared containers);
- ``docs/schema/aidw-config.schema.json`` agrees field-for-field with the dataclasses.

E3.2 adds the second half of the module — layered resolution with provenance:
:func:`aidw.target_config.resolve_config` merges the toolkit defaults under a declared
config and under per-invocation overrides, and the tests below pin the precedence
(override > config > default > *unset*), the flat dotted-path addressing, the
declared-ness-not-value-equality rule, and the resolver's purity (no input mutation, no
I/O, no shared containers), plus a seeded property run over generated configs.

E3.4 seeds the defaults: the eight §3.4 ``repo:``/``paths:`` values (D17/R7) are pinned
one by one, a ``schema_version: 1``-only config resolves all eight with
``source == "default"``, a declared ``repo.base_branch`` beats its sibling's default, and
the seeded defaults are never mutated by resolution.

E3.3 adds the compatibility pass, :func:`aidw.target_config.check_compatibility`: the two
independent refusals (§3.11's "newer than understood" ``schema_version`` and an
unsatisfied ``requires_toolkit`` pin), their boundaries (``None`` and older numbers are
*not* refusals), the no-traceback failure paths (an unparseable specifier, an unparseable
toolkit version), the loader's ``path.name`` issue-source convention, purity, and a seeded
property run over both rules together.

The *loader* deliberately does not merge defaults (E3.4 seeds the values), validate path
existence (E3.7), or own the stage-id vocabulary (E4.1/E4.5); no test here asks it to.
``aidw config show``'s rendering of these values is ``tests/test_cli.py``'s, and the
``max_revisions`` consumer is ``tests/test_prompt_workflow.py``'s.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import fnmatch
import inspect
import json
import pathlib
import random
from pathlib import Path
from typing import Any

import pytest
import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from aidw.config import ERROR
from aidw.paths import TargetRepo, toolkit_root
from aidw.target_config import (
    CONFIG_FILENAME,
    DEFAULT_MAX_REVISIONS,
    SOURCE_CONFIG,
    SOURCE_DEFAULT,
    SOURCE_OVERRIDE,
    SOURCES,
    ConfigDefaults,
    ConfigOverrides,
    GitHubConfig,
    LabelConfig,
    MarkersConfig,
    PathsConfig,
    READ_PATHS,
    RepoConfig,
    ResolvedConfig,
    ResolvedValue,
    SUPPORTED_SCHEMA_VERSION,
    StageConfig,
    TargetConfig,
    TOOLKIT_DEFAULTS,
    WRITE_TARGETS,
    WorkflowConfig,
    agent_configs_override,
    check_compatibility,
    ensure_write_targets,
    format_issues,
    load_target_config,
    resolve_config,
    validate_paths,
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
        "agent_configs_dir": "aidw/agent-configs",
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
                    "model": "meta/muse-spark-1.3",
                    "thinking": "high",
                    "timeout_seconds": 1800,
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
    "agent_configs_dir",
}
MARKERS_CONFIG_KEYS = {"parent", "child", "summary"}
STAGE_CONFIG_KEYS = {
    "id",
    "enabled",
    "prompt",
    "agent",
    "model",
    "thinking",
    "timeout_seconds",
}
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
        agent_configs_dir="aidw/agent-configs",
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
    # E4.6's per-stage metadata overrides round-trip with the rest of the entry.
    assert traceability.model == "meta/muse-spark-1.3"
    assert traceability.thinking == "high"
    assert traceability.timeout_seconds == 1800
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


def test_non_utf8_bytes_are_an_error_not_an_exception(tmp_path: Path) -> None:
    """Review follow-up #77: non-UTF-8 bytes are a decode error, not an uncaught
    UnicodeDecodeError — UnicodeDecodeError is a ValueError, so the OSError handler
    alone does not cover it.
    """
    path = tmp_path / "aidw" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"schema_version: 1\nname: caf\xe9\n")

    config = load_target_config(path)

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


STAGE_OVERRIDE_VECTORS = [
    pytest.param("model", "openrouter/deepseek/deepseek-v4.1-flash", id="model"),
    pytest.param("thinking", "xhigh", id="thinking"),
    pytest.param("timeout_seconds", 1800, id="timeout-seconds"),
]


@pytest.mark.parametrize(("key", "value"), STAGE_OVERRIDE_VECTORS)
def test_stage_override_fields_are_accepted_and_round_trip(
    tmp_path: Path, key: str, value: object
) -> None:
    """E4.6's stage metadata fields are part of the schema and survive a round-trip.

    One hand-calculated vector per field: the loader accepts the value and serialises
    exactly what was declared (an unseen field is never injected, so the entry keeps only
    ``id`` plus the one key the vector names).
    """
    config = _load(
        tmp_path,
        {
            "schema_version": 1,
            "workflows": {
                "implement": {"stages": [{"id": "implement", key: value}]}
            },
        },
    )

    assert config.issues == []
    stage = config.workflows["implement"].stages[0]
    assert getattr(stage, key) == value
    assert config.to_dict()["workflows"]["implement"]["stages"][0] == {
        "id": "implement",
        key: value,
    }


STAGE_OVERRIDE_FAILURE_VECTORS = [
    pytest.param("model", "", "non-empty", id="model-empty"),
    pytest.param("model", 7, "must be a string", id="model-int"),
    pytest.param("thinking", "super", "must be one of", id="thinking-bad-level"),
    pytest.param("thinking", 3, "must be a string", id="thinking-int"),
    pytest.param("timeout_seconds", 0, "positive integer", id="timeout-zero"),
    pytest.param("timeout_seconds", -5, "positive integer", id="timeout-negative"),
    pytest.param("timeout_seconds", True, "must be an integer", id="timeout-bool"),
    pytest.param("timeout_seconds", "600", "must be an integer", id="timeout-str"),
]


@pytest.mark.parametrize(("key", "value", "fragment"), STAGE_OVERRIDE_FAILURE_VECTORS)
def test_stage_override_bad_value_fails_naming_the_field_path(
    tmp_path: Path, key: str, value: object, fragment: str
) -> None:
    """E3.1's contract extended to E4.6's fields: field path, rule, fail closed."""
    config = _load(
        tmp_path,
        {
            "schema_version": 1,
            "workflows": {
                "implement": {"stages": [{"id": "implement", key: value}]}
            },
        },
    )

    errors = _errors(config)
    assert any(
        f"workflows.implement.stages[0].{key}" in message and fragment in message
        for message in errors
    ), format_issues(config.issues)


def test_absent_stage_overrides_are_never_serialised_as_null(tmp_path: Path) -> None:
    """Round-trip via the declared keys: a 2-field entry stays 2 fields."""
    declared = {"id": "implement", "agent": "implementer"}
    config = _load(
        tmp_path,
        {
            "schema_version": 1,
            "workflows": {"implement": {"stages": [declared]}},
        },
    )

    assert config.issues == []
    stage = config.workflows["implement"].stages[0]
    assert (stage.model, stage.thinking, stage.timeout_seconds) == (None, None, None)
    assert config.to_dict()["workflows"]["implement"]["stages"] == [declared]


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


# ---------------------------------------------------------------------------
# Layered resolution with provenance (E3.2, EXTRACTION.md §3.3/§3.4, design §12/H8)
# ---------------------------------------------------------------------------

#: Pinned seed and run count for the seeded property test below. This repo's dev
#: dependencies are pytest only (``pyproject.toml``; no hypothesis), so the provenance
#: invariants are exercised over a reproducible, seeded sample rather than a shrinking
#: generator. Same seed + same count => same cases, on every machine.
PROPERTY_SEED = 3211
PROPERTY_RUNS = 64


def _resolve_loaded(
    tmp_path: Path, config: dict[str, Any] | None = None, **kwargs: Any
) -> ResolvedConfig:
    declared = TargetConfig() if config is None else _load(tmp_path, config)
    assert declared.issues == [], format_issues(declared.issues)
    return resolve_config(declared, **kwargs)


def test_every_seeded_default_is_the_section_3_4_mythical_forge_value() -> None:
    """Requirement 4/E3.4: each of the eight §3.4 defaults is asserted by name.

    Eight separate assertions rather than a loop over a shared dict: a dropped, renamed
    or mistyped default must fail loudly under its own name instead of vanishing into a
    parametrisation. These are D17/R7's strings — Mythical Forge's current layout — not
    neutral placeholders, so ``00 - Extraction.md`` (the real roadmap filenames) must
    match ``roadmap_glob`` character-for-character: ``[0-9]* - *.md``.
    """
    # ``repo:`` — EXTRACTION.md §3.4.
    assert TOOLKIT_DEFAULTS.repo.base_branch == "main"
    assert TOOLKIT_DEFAULTS.repo.branch_pattern == "{phase}-{task}"
    # ``paths:`` — EXTRACTION.md §3.4.
    assert TOOLKIT_DEFAULTS.paths.roadmap_dir == "docs/tasks"
    assert TOOLKIT_DEFAULTS.paths.roadmap_glob == "[0-9]* - *.md"
    assert TOOLKIT_DEFAULTS.paths.task_prompts_dir == "docs/task-prompts"
    assert (
        TOOLKIT_DEFAULTS.paths.implementation_results_dir
        == "docs/implementation-results"
    )
    assert (
        TOOLKIT_DEFAULTS.paths.build_results_template
        == "docs/implementation-results/TEMPLATE.md"
    )
    assert TOOLKIT_DEFAULTS.paths.architecture_dir == "docs/architecture"


def test_seeded_defaults_are_the_budget_and_the_mythical_forge_layout_only() -> None:
    """Requirement 1/2: nothing else is seeded — no ``schema_version``, no ``github``."""
    assert DEFAULT_MAX_REVISIONS == 3
    assert TOOLKIT_DEFAULTS.max_revisions == DEFAULT_MAX_REVISIONS
    # E3.1/E3.3 own the version fields: a missing config file has no resolved version,
    # and ``requires_toolkit`` is an optional pin, never a default.
    assert TOOLKIT_DEFAULTS.schema_version is None
    assert TOOLKIT_DEFAULTS.requires_toolkit is None
    # E6 owns the frozen D5 markers/labels: present as empty slots, so they stay unset.
    assert TOOLKIT_DEFAULTS.github == GitHubConfig(markers=MarkersConfig())
    assert dict(TOOLKIT_DEFAULTS.github.labels) == {}
    # E4.1 owns the stage-list defaults.
    assert dict(TOOLKIT_DEFAULTS.workflows) == {}
    assert {f.name for f in dataclasses.fields(ConfigDefaults)} >= {
        "repo",
        "paths",
        "github",
        "workflows",
    }


def test_default_roadmap_glob_matches_the_real_roadmap_filenames() -> None:
    """The ``roadmap_glob`` trap: ``[0-9]* - *.md`` is space-dash-space, and exact.

    The real phase filenames (``00 - Extraction.md``, ``03.1 - Target-repo config.md``)
    only match the seeded glob because the separators are spaces; a ``[0-9]*-*.md``
    typo would match nothing and E5.2's parser would silently find no roadmap. The
    near-misses are pinned as *not* matching for the same reason.
    """
    pattern = TOOLKIT_DEFAULTS.paths.roadmap_glob

    assert fnmatch.fnmatch("00 - Extraction.md", pattern)
    assert fnmatch.fnmatch("03.1 - Target-repo config.md", pattern)
    assert not fnmatch.fnmatch("00-Extraction.md", pattern)
    assert not fnmatch.fnmatch("Extraction.md", pattern)
    # Prefix pinned: the roadmap's own parser only accepts two-digit (optionally dotted)
    # ids (``aidw/roadmap.py:_FILENAME_RE``), so a glob leading with ``*`` is wrong.
    assert not fnmatch.fnmatch("extraction - notes.md", pattern)


def test_toolkit_defaults_equal_a_freshly_built_defaults_structure() -> None:
    """``TOOLKIT_DEFAULTS`` is immutable in practice: resolution never mutates it."""
    assert TOOLKIT_DEFAULTS == ConfigDefaults()
    assert TOOLKIT_DEFAULTS.repo == RepoConfig(
        base_branch="main", branch_pattern="{phase}-{task}"
    )
    assert TOOLKIT_DEFAULTS.paths == PathsConfig(
        roadmap_dir="docs/tasks",
        roadmap_glob="[0-9]* - *.md",
        task_prompts_dir="docs/task-prompts",
        implementation_results_dir="docs/implementation-results",
        build_results_template="docs/implementation-results/TEMPLATE.md",
        architecture_dir="docs/architecture",
    )


def test_the_two_repo_defaults_match_the_target_repo_dataclass() -> None:
    """Trap/second source of truth: ``TargetRepo``'s literals must stay equal.

    E3.4 seeds config defaults that duplicate ``aidw.paths.TargetRepo``'s frozen
    ``base_branch``/``branch_pattern`` defaults instead of collapsing them into one shared
    constant — ``target_config`` must not import ``aidw.paths`` (layering), and rewiring
    ``TargetRepo`` to the resolved config is E4/E5's. This test is what keeps the two
    homes from drifting until then.
    """
    from aidw import target_config

    assert not any(
        module == "aidw.paths" or module.startswith("aidw.paths.")
        for module in _imported_modules(inspect.getsource(target_config))
    )
    assert TargetRepo.base_branch == TOOLKIT_DEFAULTS.repo.base_branch
    assert TargetRepo.branch_pattern == TOOLKIT_DEFAULTS.repo.branch_pattern


def test_undeclared_max_revisions_resolves_to_the_default(tmp_path: Path) -> None:
    resolved = _resolve_loaded(tmp_path, {"schema_version": 1})

    assert resolved["max_revisions"] == ResolvedValue(3, SOURCE_DEFAULT)


def test_declared_max_revisions_beats_the_default(tmp_path: Path) -> None:
    resolved = _resolve_loaded(tmp_path, {"schema_version": 1, "max_revisions": 5})

    assert resolved["max_revisions"] == ResolvedValue(5, SOURCE_CONFIG)


def test_override_beats_declared_and_default(tmp_path: Path) -> None:
    """The only override surface today is ``--max-revisions`` (design §12/H8)."""
    resolved = _resolve_loaded(
        tmp_path,
        {"schema_version": 1, "max_revisions": 5},
        overrides=ConfigOverrides(max_revisions=7),
    )

    assert resolved["max_revisions"] == ResolvedValue(7, SOURCE_OVERRIDE)

    no_config = _resolve_loaded(
        tmp_path / "again", None, overrides=ConfigOverrides(max_revisions=7)
    )
    assert no_config["max_revisions"] == ResolvedValue(7, SOURCE_OVERRIDE)


def test_explicit_value_equal_to_the_default_still_reports_config(
    tmp_path: Path,
) -> None:
    """Requirement 3: declared-ness, not value equality, decides ``config``.

    A ``value == default ? "default" : "config"`` implementation mislabels this config;
    the loader's ``_declared`` tracking is what makes the explicit ``3`` observable.
    """
    declared = _load(tmp_path, {"schema_version": 1, "max_revisions": 3})
    assert "max_revisions" in declared._declared

    resolved = resolve_config(declared)

    assert resolved["max_revisions"] == ResolvedValue(3, SOURCE_CONFIG)


def test_partial_config_resolves_defaults_and_leaves_only_unseeded_leaves_unset(
    tmp_path: Path,
) -> None:
    """Requirement 5/E3.4: a declared leaf wins; its siblings fall back to the defaults."""
    resolved = _resolve_loaded(
        tmp_path, {"schema_version": 1, "repo": {"base_branch": "trunk"}}
    )

    assert resolved["repo.base_branch"] == ResolvedValue("trunk", SOURCE_CONFIG)
    assert resolved["schema_version"] == ResolvedValue(1, SOURCE_CONFIG)
    # The undeclared sibling is a separate leaf and keeps the §3.4 default.
    assert resolved["repo.branch_pattern"] == ResolvedValue(
        "{phase}-{task}", SOURCE_DEFAULT
    )
    # After E3.4/E4.6 the only unseeded leaves are ``requires_toolkit``, E4.6's override
    # directory (no default on purpose) and the E6 markers.
    assert {
        path
        for path, entry in resolved.items()
        if entry == ResolvedValue()
    } == {
        "requires_toolkit",
        "paths.agent_configs_dir",
        "github.markers.parent",
        "github.markers.child",
        "github.markers.summary",
    }


#: The eight §3.4 ``repo:``/``paths:`` leaves and D17's Mythical Forge values, spelled
#: out literally (never imported from the module) so a changed default fails here.
MYTHICAL_FORGE_LAYOUT = (
    ("repo.base_branch", "main"),
    ("repo.branch_pattern", "{phase}-{task}"),
    ("paths.roadmap_dir", "docs/tasks"),
    ("paths.roadmap_glob", "[0-9]* - *.md"),
    ("paths.task_prompts_dir", "docs/task-prompts"),
    ("paths.implementation_results_dir", "docs/implementation-results"),
    ("paths.build_results_template", "docs/implementation-results/TEMPLATE.md"),
    ("paths.architecture_dir", "docs/architecture"),
)


def test_schema_version_only_config_resolves_the_mythical_forge_layout() -> None:
    """The roadmap's Done-when: ``schema_version: 1`` alone produces the MF layout.

    Built in code rather than loaded, so the vector proves resolution itself injects no
    ``config`` provenance and invents no ``github``/``workflows`` entries.
    """
    resolved = resolve_config(TargetConfig(schema_version=1))

    for path, value in MYTHICAL_FORGE_LAYOUT:
        assert resolved[path] == ResolvedValue(value, SOURCE_DEFAULT), path
        assert resolved[path].is_set is True

    # Every other leaf is either the E3.2 budget, E4.6's unset override dir, or still
    # unseeded; no E6/E4.1 value.
    assert set(resolved) == {
        "schema_version",
        "requires_toolkit",
        "max_revisions",
        * (path for path, _ in MYTHICAL_FORGE_LAYOUT),
        "paths.agent_configs_dir",
        "github.markers.parent",
        "github.markers.child",
        "github.markers.summary",
    }
    assert not any(path.startswith(("github.labels.", "workflows.")) for path in resolved)
    assert resolved["max_revisions"] == ResolvedValue(3, SOURCE_DEFAULT)


def test_schema_version_only_config_file_through_the_loader_resolves_the_layout(
    tmp_path: Path,
) -> None:
    """The same Done-when through the real loader: a near-empty file is all it takes."""
    resolved = _resolve_loaded(tmp_path, {"schema_version": 1})

    for path, value in MYTHICAL_FORGE_LAYOUT:
        assert resolved[path] == ResolvedValue(value, SOURCE_DEFAULT), path


def test_declared_base_branch_beats_the_default_but_not_its_sibling(
    tmp_path: Path,
) -> None:
    """Precedence vector: ``config`` > ``default``, decided per leaf."""
    resolved = _resolve_loaded(
        tmp_path, {"schema_version": 1, "repo": {"base_branch": "trunk"}}
    )

    assert resolved["repo.base_branch"] == ResolvedValue("trunk", SOURCE_CONFIG)
    assert resolved["repo.branch_pattern"] == ResolvedValue(
        "{phase}-{task}", SOURCE_DEFAULT
    )


def test_declared_value_equal_to_a_default_is_still_config(tmp_path: Path) -> None:
    """Declared-ness, not value equality: ``main`` declared is ``config``, not ``default``."""
    resolved = _resolve_loaded(
        tmp_path, {"schema_version": 1, "repo": {"base_branch": "main"}}
    )

    assert resolved["repo.base_branch"] == ResolvedValue("main", SOURCE_CONFIG)
    assert resolved["repo.branch_pattern"] == ResolvedValue(
        "{phase}-{task}", SOURCE_DEFAULT
    )


def test_defaults_resolution_is_pure_and_does_not_touch_toolkit_defaults() -> None:
    """Requirement 4: resolving twice is fresh, alias-free, and mutates nothing."""
    declared = TargetConfig(schema_version=1)
    before = copy.deepcopy(declared)
    defaults_before = TOOLKIT_DEFAULTS

    first = resolve_config(declared)
    second = resolve_config(declared)

    assert first.to_dict() == second.to_dict()
    assert first is not second
    assert first.entries is not second.entries
    # Every entry is a fresh ``ResolvedValue``, not a shared one.
    for path in first:
        assert first[path] is not second[path], path
    # The defaults structure is never mutated, so a later resolution is unaffected.
    assert TOOLKIT_DEFAULTS == defaults_before == ConfigDefaults()
    assert declared == before
    first.entries.clear()
    assert len(resolve_config(declared)) == len(second)
    assert resolve_config(declared).to_dict() == second.to_dict()
    assert TOOLKIT_DEFAULTS.paths.roadmap_dir == "docs/tasks"


def test_declared_markers_and_labels_carry_config_provenance(tmp_path: Path) -> None:
    resolved = _resolve_loaded(
        tmp_path,
        {
            "schema_version": 1,
            "github": {
                "markers": {"parent": "<!-- p -->"},
                "labels": {"must-fix": {"color": "B60205", "description": "Blocking"}},
            },
        },
    )

    assert resolved["github.markers.parent"] == ResolvedValue("<!-- p -->", SOURCE_CONFIG)
    assert resolved["github.markers.child"] == ResolvedValue()
    assert resolved["github.markers.summary"] == ResolvedValue()
    assert resolved["github.labels.must-fix.color"] == ResolvedValue(
        "B60205", SOURCE_CONFIG
    )
    assert resolved["github.labels.must-fix.description"] == ResolvedValue(
        "Blocking", SOURCE_CONFIG
    )
    # Open maps contribute only the keys the config declared (E6 seeds defaults later).
    assert not any(path.startswith("github.labels.could-fix") for path in resolved)


def test_workflow_stages_are_one_whole_list_entry(tmp_path: Path) -> None:
    """Requirement 1: the list's own path carries provenance; elements carry none."""
    resolved = _resolve_loaded(
        tmp_path,
        {
            "schema_version": 1,
            "workflows": {
                "prompt": {
                    "stages": [{"id": "author"}, {"id": "review"}],
                    "parallel_groups": [["review", "record"]],
                }
            },
        },
    )

    assert resolved["workflows.prompt.stages"] == ResolvedValue(
        [{"id": "author"}, {"id": "review"}], SOURCE_CONFIG
    )
    assert resolved["workflows.prompt.parallel_groups"] == ResolvedValue(
        [["review", "record"]], SOURCE_CONFIG
    )
    # No per-element and no per-stage-subfield entries: addressing is one path per list.
    assert not any("stages[" in path or "parallel_groups[" in path for path in resolved)
    assert "workflows.prompt.stages.id" not in resolved
    assert "workflows.prompt.stages.0.enabled" not in resolved
    # An undeclared sibling list is absent rather than an ``unset`` entry.
    undeclared = _resolve_loaded(
        tmp_path / "sibling",
        {"schema_version": 1, "workflows": {"prompt": {"stages": [{"id": "x"}]}}},
    )
    assert "workflows.prompt.stages" in undeclared
    assert "workflows.prompt.parallel_groups" not in undeclared


def test_declared_empty_lists_stay_config_rather_than_unset(tmp_path: Path) -> None:
    """An explicit ``stages: []`` is the config declaring an empty list (§3.5 disable-all)."""
    resolved = _resolve_loaded(
        tmp_path,
        {"schema_version": 1, "workflows": {"implement": {"stages": []}}},
    )

    assert resolved["workflows.implement.stages"] == ResolvedValue([], SOURCE_CONFIG)
    assert "workflows.implement.parallel_groups" not in resolved


def test_two_declared_workflows_all_resolve(tmp_path: Path) -> None:
    """A config with two or more workflows resolves without crashing.

    Regression test for the PR #68 review follow-up (finding F1): the resolver
    loop shadowed the ``declared`` TargetConfig parameter with a per-key
    boolean, so the second workflow's iteration raised ``AttributeError`` —
    the normative EXTRACTION.md §3.4 example declares both ``prompt`` and
    ``implement`` and could not resolve at all.
    """
    resolved = _resolve_loaded(
        tmp_path,
        {
            "schema_version": 1,
            "workflows": {
                "prompt": {"stages": [{"id": "author"}, {"id": "review"}]},
                "implement": {
                    "stages": [{"id": "implement"}, {"id": "test"}],
                    "parallel_groups": [["test", "architecture"]],
                },
            },
        },
    )

    assert resolved["workflows.prompt.stages"] == ResolvedValue(
        [{"id": "author"}, {"id": "review"}], SOURCE_CONFIG
    )
    assert resolved["workflows.implement.stages"] == ResolvedValue(
        [{"id": "implement"}, {"id": "test"}], SOURCE_CONFIG
    )
    assert resolved["workflows.implement.parallel_groups"] == ResolvedValue(
        [["test", "architecture"]], SOURCE_CONFIG
    )
    # The open-map rule holds for every workflow: an undeclared sibling list
    # stays absent rather than contributing an ``unset`` entry.
    assert "workflows.prompt.parallel_groups" not in resolved


def test_resolver_is_pure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No mutation of the input, no I/O, no aliased containers, stable across calls."""
    config_data = {
        "schema_version": 1,
        "max_revisions": 2,
        "repo": {"base_branch": "trunk", "branch_pattern": "{task}"},
        "workflows": {"prompt": {"stages": [{"id": "author"}]}},
        "github": {"labels": {"must-fix": {"color": "B60205", "description": "d"}}},
    }
    declared = _load(tmp_path, config_data)
    before_dict = copy.deepcopy(declared.to_dict())
    before_stages = copy.deepcopy(declared.workflows["prompt"].stages)

    def _no_io(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("resolve_config must not touch the filesystem")

    monkeypatch.setattr(pathlib.Path, "read_text", _no_io)
    monkeypatch.setattr(pathlib.Path, "write_text", _no_io)
    monkeypatch.setattr(pathlib.Path, "open", _no_io)
    first = resolve_config(declared, overrides=ConfigOverrides(max_revisions=9))
    second = resolve_config(declared, overrides=ConfigOverrides(max_revisions=9))

    assert first.to_dict() == second.to_dict()
    assert first is not second
    assert declared.to_dict() == before_dict
    assert declared.workflows["prompt"].stages == before_stages

    # Mutating a resolved container cannot corrupt the config or a later resolution.
    expected = copy.deepcopy(first.to_dict())
    first["workflows.prompt.stages"].value.clear()
    assert (
        resolve_config(declared, overrides=ConfigOverrides(max_revisions=9)).to_dict()
        == expected
    )
    assert declared.to_dict() == before_dict


def test_resolved_lists_are_fresh_containers(tmp_path: Path) -> None:
    declared = _load(
        tmp_path,
        {
            "schema_version": 1,
            "workflows": {"prompt": {"stages": [{"id": "author"}]}},
        },
    )

    first = resolve_config(declared)
    second = resolve_config(declared)

    first_value = first["workflows.prompt.stages"].value
    second_value = second["workflows.prompt.stages"].value
    assert first_value == second_value
    assert first_value is not second_value
    assert first_value is not declared.workflows["prompt"].stages
    assert first_value[0] is not declared.workflows["prompt"].stages[0]


def _imported_modules(source: str) -> set[str]:
    """Every module named by an ``import``/``from ... import`` statement in ``source``."""
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    return imported


def test_default_max_revisions_has_a_single_home() -> None:
    """Requirement 2: ``aidw/target_config.py`` defines it; ``prompt.py`` imports it.

    A second definition would let design §12's "default stays 3" drift, and the reverse
    import (``target_config -> workflows.prompt``) would be a cycle back into this module.
    """
    from aidw import target_config
    from aidw.workflows import prompt as prompt_workflow

    assert prompt_workflow.DEFAULT_MAX_REVISIONS is DEFAULT_MAX_REVISIONS
    assert "DEFAULT_MAX_REVISIONS =" not in inspect.getsource(prompt_workflow)
    assert not any(
        module.startswith("aidw.workflows")
        for module in _imported_modules(inspect.getsource(target_config))
    )


def _random_config(rng: random.Random) -> dict[str, Any]:
    """A random but loader-valid §3.4 config, for the seeded property run."""
    config: dict[str, Any] = {"schema_version": 1}
    if rng.random() < 0.6:
        config["max_revisions"] = rng.choice([1, 2, 3, 5, 9])
    if rng.random() < 0.5:
        config["repo"] = {
            "base_branch": rng.choice(["main", "trunk"]),
            "branch_pattern": rng.choice(["{phase}-{task}", "{task}"]),
        }
    if rng.random() < 0.5:
        config["paths"] = {
            "roadmap_dir": rng.choice(["docs/tasks", "tasks"]),
            "architecture_dir": "docs/architecture",
        }
    if rng.random() < 0.4:
        config["workflows"] = {
            rng.choice(["prompt", "implement"]): {
                "stages": [{"id": rng.choice(["author", "review", "implement"])}]
            }
        }
    if rng.random() < 0.4:
        config["github"] = {
            "labels": {
                rng.choice(["must-fix", "should-fix"]): {
                    "color": "B60205",
                    "description": "d",
                }
            }
        }
    return config


def test_provenance_precedence_property(tmp_path: Path) -> None:
    """Seeded property run over the three-source precedence (seed/numRuns pinned above).

    Invariants, for every generated config: an override always wins; a declared value is
    always ``config`` (even when it equals the default) and an absent one always
    ``default``; unset means ``value is None``; no resolved label is outside
    :data:`SOURCES`; resolution is idempotent and alias-free.
    """
    rng = random.Random(PROPERTY_SEED)

    for index in range(PROPERTY_RUNS):
        config_data = _random_config(rng)
        declared = _load(tmp_path / f"run-{index}", config_data)
        assert declared.issues == [], format_issues(declared.issues)
        declared_before = copy.deepcopy(declared.to_dict())

        plain = resolve_config(declared)
        overridden = resolve_config(
            declared, overrides=ConfigOverrides(max_revisions=11)
        )

        # Override dominance, independent of what the config declared.
        assert overridden["max_revisions"] == ResolvedValue(11, SOURCE_OVERRIDE)
        if "max_revisions" in config_data:
            assert plain["max_revisions"] == ResolvedValue(
                config_data["max_revisions"], SOURCE_CONFIG
            )
        else:
            assert plain["max_revisions"] == ResolvedValue(
                DEFAULT_MAX_REVISIONS, SOURCE_DEFAULT
            )

        # E3.4: the §3.4 ``repo:``/``paths:`` leaves always resolve — ``config`` when the
        # file declared them, ``default`` otherwise — and never fall back to *unset*.
        assert plain["repo.base_branch"].source == (
            SOURCE_CONFIG if "repo" in config_data else SOURCE_DEFAULT
        )
        assert plain["paths.roadmap_dir"].source == (
            SOURCE_CONFIG if "paths" in config_data else SOURCE_DEFAULT
        )

        for path, entry in plain.items():
            if entry.source is None:
                assert entry.value is None, path
                assert not entry.is_set
            else:
                assert entry.source in SOURCES, path
                assert entry.is_set
                # ``to_dict`` keeps the same two-key shape for every resolved leaf.
                assert set(entry.to_dict()) == {"value", "source"}

        # Idempotent and alias-free: mutating a result's containers changes nothing.
        expected = copy.deepcopy(plain.to_dict())
        for entry in plain.values():
            if isinstance(entry.value, list):
                entry.value.clear()
        assert resolve_config(declared).to_dict() == expected
        assert declared.to_dict() == declared_before


# --------------------------------------------------------------------------- #
# Version and compatibility refusal (E3.3, EXTRACTION.md §3.11, D10)
# --------------------------------------------------------------------------- #
#
# Hand-calculated vectors, one per behaviour path, plus a seeded property run. The check
# has exactly two independent refusals, so the interesting cases are the *combination*
# (both violated: two issues, never just the first), the boundaries (``None`` and ``0`` are
# not "newer"), and the failure paths that must not become tracebacks (an unparseable
# specifier, an unparseable toolkit version).

#: Pinned seed and run count for the seeded property test below (same convention as the
#: E3.2 property run: pytest only, no hypothesis, so a fixed sample and no shrinking).
COMPAT_PROPERTY_SEED = 3311
COMPAT_PROPERTY_RUNS = 64

#: The toolkit version the hand-calculated vectors use. Deliberately *not*
#: ``aidw.__version__``: the check must use the version it is handed, and pinning a
#: literal here is what makes a hardcoded ``"0.1.0"`` inside the module fail.
TOOLKIT_VERSION = "0.1.0"


def _compat(
    declaration: dict[str, Any] | None = None,
    *,
    toolkit_version: str = TOOLKIT_VERSION,
    tmp_path: Path | None = None,
) -> list[Any]:
    """Load ``declaration`` (through the real loader when a path is given) and check it."""
    if tmp_path is not None:
        declared = TargetConfig() if declaration is None else _load(tmp_path, declaration)
    else:
        declared = TargetConfig(**(declaration or {}))
    return check_compatibility(declared, toolkit_version=toolkit_version)


def _messages(issues: list[Any]) -> list[str]:
    return [issue.message for issue in issues]


def test_supported_schema_version_is_one() -> None:
    """The toolkit understands exactly the §3.4 schema in this module (E3.1's)."""
    assert SUPPORTED_SCHEMA_VERSION == 1


def test_current_schema_version_with_no_pin_is_compatible(tmp_path: Path) -> None:
    """Requirement 2's happy path: ``schema_version: 1`` and no ``requires_toolkit``."""
    issues = _compat({"schema_version": 1}, tmp_path=tmp_path)

    assert issues == []


def test_satisfied_requires_toolkit_is_compatible(tmp_path: Path) -> None:
    """A pin the toolkit's own version satisfies is not a refusal (§3.4's ``>=1.0.0``)."""
    assert _compat(
        {"schema_version": 1, "requires_toolkit": ">=0.1.0"},
        toolkit_version="0.1.0",
        tmp_path=tmp_path,
    ) == []
    # PEP 440 semantics, not string semantics: "0.10.0" < "0.9.0" lexicographically.
    assert _compat(
        {"schema_version": 1, "requires_toolkit": ">=0.10.0"},
        toolkit_version="0.9.0",
    ) != []
    assert _compat(
        {"schema_version": 1, "requires_toolkit": ">=0.9.0"},
        toolkit_version="0.10.0",
    ) == []


def test_newer_schema_version_refuses_naming_field_value_and_supported(
    tmp_path: Path,
) -> None:
    """Refusal 1: a newer ``schema_version`` names the field, the value and the ceiling."""
    issues = _compat({"schema_version": 2}, tmp_path=tmp_path)

    assert len(issues) == 1
    issue = issues[0]
    assert issue.level == ERROR
    assert issue.source == "config.yaml"
    for token in ("schema_version", "2", str(SUPPORTED_SCHEMA_VERSION)):
        assert token in issue.message
    # Actionable remedy, both directions (§3.11 "refuses to run ... clear, actionable").
    assert "upgrade `aidt`" in issue.message
    assert "lower the config's `schema_version`" in issue.message
    assert "error: config.yaml:" in format_issues(issues)


def test_unsatisfied_requires_toolkit_refuses_naming_field_specifier_and_version(
    tmp_path: Path,
) -> None:
    """Refusal 2: an unsatisfied pin names the field, the pin and the toolkit version."""
    issues = _compat(
        {"schema_version": 1, "requires_toolkit": ">=1.0.0"}, tmp_path=tmp_path
    )

    assert len(issues) == 1
    issue = issues[0]
    assert issue.level == ERROR
    assert issue.source == "config.yaml"
    for token in ("requires_toolkit", ">=1.0.0", TOOLKIT_VERSION):
        assert token in issue.message
    assert "upgrade `aidt`" in issue.message
    assert "relax the pin" in issue.message


def test_upper_bound_pin_also_refuses() -> None:
    """The comparator is a PEP 440 specifier, not a "minimum version" special case."""
    issues = _compat(
        {"schema_version": 1, "requires_toolkit": "<=0.0.5"},
        toolkit_version="0.1.0",
    )

    assert len(issues) == 1
    assert "requires_toolkit" in issues[0].message
    assert "<=0.0.5" in issues[0].message


def test_both_refusals_are_independent_issues(tmp_path: Path) -> None:
    """Requirement 1: a config violating both reports two issues, not just the first."""
    issues = _compat(
        {"schema_version": 2, "requires_toolkit": ">=1.0.0"}, tmp_path=tmp_path
    )

    assert len(issues) == 2
    assert all(issue.level == ERROR for issue in issues)
    assert {issue.source for issue in issues} == {"config.yaml"}
    messages = _messages(issues)
    assert "schema_version" in messages[0]
    assert "requires_toolkit" in messages[1]


def test_invalid_requires_toolkit_specifier_is_an_issue_not_an_exception() -> None:
    """Requirement 3: ``SpecifierSet``'s ``InvalidSpecifier`` becomes an ERROR issue."""
    issues = _compat(
        {"schema_version": 1, "requires_toolkit": "banana"}, toolkit_version="0.1.0"
    )

    assert len(issues) == 1
    assert issues[0].level == ERROR
    for token in ("requires_toolkit", "banana", "not a valid version specifier"):
        assert token in issues[0].message


def test_invalid_toolkit_version_is_an_issue_not_an_exception() -> None:
    """A malformed toolkit version is the toolkit's bug, so it also fails closed."""
    issues = _compat(
        {"schema_version": 1, "requires_toolkit": ">=1.0.0"},
        toolkit_version="not-a-version",
    )

    assert len(issues) == 1
    assert issues[0].level == ERROR
    for token in ("requires_toolkit", "not-a-version"):
        assert token in issues[0].message


def test_missing_config_is_compatible() -> None:
    """§3.4: no ``aidw/`` folder is the valid defaults-only case, never a refusal."""
    assert check_compatibility(TargetConfig(), toolkit_version=TOOLKIT_VERSION) == []


def test_missing_config_file_loads_and_is_compatible(tmp_path: Path) -> None:
    """The same case through the real loader: no file => no issues, no refusal."""
    path = tmp_path / "target" / "aidw" / "config.yaml"
    declared = load_target_config(path)

    assert declared.source_path is None
    assert check_compatibility(declared, toolkit_version=TOOLKIT_VERSION) == []


@pytest.mark.parametrize("schema_version", [0, -1, SUPPORTED_SCHEMA_VERSION])
def test_older_or_current_schema_version_is_not_a_refusal(schema_version: int) -> None:
    """The boundary is ``>``, not ``state.py:load``'s ``!=``: older is not "newer"."""
    assert (
        check_compatibility(
            TargetConfig(schema_version=schema_version),
            toolkit_version=TOOLKIT_VERSION,
        )
        == []
    )


def test_compatibility_issue_source_follows_the_loader_name_convention() -> None:
    """The source is the config file's name, and the fallback when none was loaded."""
    # A code-built config (no ``source_path``) still names ``config.yaml``, the loader's
    # ``path.name`` for the canonical location.
    issues = check_compatibility(
        TargetConfig(schema_version=2), toolkit_version=TOOLKIT_VERSION
    )

    assert issues[0].source == CONFIG_FILENAME == "config.yaml"


def test_compatibility_issue_source_uses_the_declared_source_path(tmp_path: Path) -> None:
    declared = _load(tmp_path, {"schema_version": 2})

    issues = check_compatibility(declared, toolkit_version=TOOLKIT_VERSION)

    assert declared.source_path is not None
    assert issues[0].source == declared.source_path.name


def test_check_compatibility_is_pure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No I/O, no input mutation, a fresh list, and stable across calls."""
    declared = _load(
        tmp_path,
        {
            "schema_version": 2,
            "requires_toolkit": ">=1.0.0",
            "repo": {"base_branch": "trunk"},
        },
    )
    before = copy.deepcopy(declared)
    before_dict = copy.deepcopy(declared.to_dict())

    def _no_io(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("check_compatibility must not touch the filesystem")

    monkeypatch.setattr(pathlib.Path, "read_text", _no_io)
    monkeypatch.setattr(pathlib.Path, "write_text", _no_io)
    monkeypatch.setattr(pathlib.Path, "open", _no_io)

    first = check_compatibility(declared, toolkit_version=TOOLKIT_VERSION)
    second = check_compatibility(declared, toolkit_version=TOOLKIT_VERSION)

    assert first == second
    assert first is not second
    assert declared == before
    assert declared.to_dict() == before_dict
    # The caller owns the list: mutating it cannot change a later result.
    first.clear()
    assert len(check_compatibility(declared, toolkit_version=TOOLKIT_VERSION)) == 2


def test_compatibility_check_is_imported_by_the_workflow_not_reverse() -> None:
    """Requirement 4 / trap: the workflow preflight imports the check, never the reverse.

    Since E4.3 the compatibility check runs inside
    :func:`aidw.target_config.resolve_workflow_config` — the one seam all five workflows use
    so their two config refusals cannot drift — so that shared helper is what ``prompt.py``
    imports from this module. The direction is unchanged: a workflow imports
    ``target_config``, never the other way round.
    """
    from aidw import target_config
    from aidw.workflows import prompt as prompt_workflow

    assert (
        prompt_workflow.resolve_workflow_config
        is target_config.resolve_workflow_config
    )
    assert not any(
        module.startswith("aidw.workflows")
        for module in _imported_modules(inspect.getsource(target_config))
    )


def _random_compat_case(rng: random.Random) -> tuple[dict[str, Any], str]:
    """A random (declaration, toolkit_version) pair, valid or intentionally broken."""
    declaration: dict[str, Any] = {}
    schema_version = rng.choice([None, -1, 0, 1, 2, 3, 99])
    if schema_version is not None:
        declaration["schema_version"] = schema_version
    requires_toolkit = rng.choice(
        [None, "", ">=1.0.0", "<=0.0.5", ">=0.1.0", "==0.1.0", "~=0.1", "!=0.1.0", "banana"]
    )
    if requires_toolkit is not None:
        declaration["requires_toolkit"] = requires_toolkit
    toolkit_version = rng.choice(
        ["0.1.0", "0.2.0", "1.0.0", "1.0.0rc1", "2.5.0", "not-a-version"]
    )
    return declaration, toolkit_version


def test_compatibility_refusal_property() -> None:
    """Seeded property run (seed/numRuns pinned above) over both independent refusals.

    Invariants for every generated case: no exception; the result is a fresh list holding
    only ERROR issues; there is exactly one issue per violated rule, in
    ``schema_version``-then-``requires_toolkit`` order, and none otherwise; each message
    names its own field; and the input config is not mutated.
    """
    rng = random.Random(COMPAT_PROPERTY_SEED)

    for _ in range(COMPAT_PROPERTY_RUNS):
        declaration, toolkit_version = _random_compat_case(rng)
        declared = TargetConfig(**declaration)
        before = copy.deepcopy(declared)

        issues = check_compatibility(declared, toolkit_version=toolkit_version)

        schema_refused = (
            declared.schema_version is not None
            and declared.schema_version > SUPPORTED_SCHEMA_VERSION
        )
        requires_refused = False
        if declared.requires_toolkit is not None:
            try:
                requirement = SpecifierSet(declared.requires_toolkit)
                version = Version(toolkit_version)
            except (InvalidSpecifier, InvalidVersion):
                requires_refused = True
            else:
                requires_refused = version not in requirement

        assert len(issues) == int(schema_refused) + int(requires_refused)
        assert all(issue.level == ERROR for issue in issues)
        assert all(issue.source == CONFIG_FILENAME for issue in issues)
        if schema_refused:
            assert "schema_version" in issues[0].message
        if requires_refused:
            assert "requires_toolkit" in issues[-1].message
        assert declared == before
        assert issues is not check_compatibility(
            declared, toolkit_version=toolkit_version
        )


# --------------------------------------------------------------------------- #
# Path classification, read-path validation and write-target creation (E3.7,
# EXTRACTION.md §3.4 "Configured read-paths must exist", D17/R7)
# --------------------------------------------------------------------------- #
#
# The classification is the whole point: a read-path must exist when a *config or a
# default* names it (so a config-less repo is validated against the Mythical Forge
# defaults too), a write-target may be absent and is created only for an enabled stage,
# and ``roadmap_glob`` is a pattern that is never stat'd. Hand-calculated vectors below,
# one per behaviour path, plus a seeded property run over arbitrary
# present/absent combinations.

PATH_PROPERTY_SEED = 3711
PATH_PROPERTY_RUNS = 64

#: ``paths:`` fields that are neither read-paths nor write-targets (a pattern).
PATTERN_FIELDS = ("roadmap_glob",)

#: A field-specific nonexistent value per read-path, so an error message that named the
#: wrong field would be caught by the parametrised vector rather than only by its count.
MISSING_READ_PATH_VALUES = {
    "build_results_template": "docs/implementation-results/MISSING.md",
    "roadmap_dir": "docs/missing-roadmap",
    "task_prompts_dir": "docs/missing-task-prompts",
    "implementation_results_dir": "docs/missing-results",
    "agent_configs_dir": "aidw/missing-agent-configs",
}

#: The read-paths whose *toolkit default* is a real value. ``agent_configs_dir`` has no
#: default (unset = use the toolkit's own ``agent-configs/``), so the present/absent
#: property generator only covers the defaulted ones; the declared case is the vector above.
DEFAULTED_READ_PATHS = tuple(
    field for field in READ_PATHS if getattr(TOOLKIT_DEFAULTS.paths, field) is not None
)


def _make_read_paths_exist(root: Path) -> None:
    """Create every §3.4 read-path under ``root`` (the D17 layout)."""
    for rel in (
        "docs/tasks",
        "docs/task-prompts",
        "docs/implementation-results",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)
    (root / "docs" / "implementation-results" / "TEMPLATE.md").write_text(
        "# t\n", encoding="utf-8"
    )


def _resolved_for(tmp_path: Path, config: dict[str, Any] | None = None) -> ResolvedConfig:
    """Resolve a declared config (or a config-less one) without touching a real tree."""
    declared = (
        _load(tmp_path, config) if config is not None else TargetConfig()
    )
    assert declared.issues == [], format_issues(declared.issues)
    return resolve_config(declared)


def test_path_classification_is_the_roadmap_read_paths_and_the_architecture_write_target() -> (
    None
):
    """E3.7's classification plus E4.6's override dir: five read-paths, one write-target.

    ``agent_configs_dir`` is a read-path but has **no default**, so it is only validated
    when a repo names it (an unset leaf is skipped, never stat'd).
    """
    assert READ_PATHS == (
        "build_results_template",
        "roadmap_dir",
        "task_prompts_dir",
        "implementation_results_dir",
        "agent_configs_dir",
    )
    assert DEFAULTED_READ_PATHS == (
        "build_results_template",
        "roadmap_dir",
        "task_prompts_dir",
        "implementation_results_dir",
    )
    assert getattr(TOOLKIT_DEFAULTS.paths, "agent_configs_dir") is None
    assert WRITE_TARGETS == {"architecture_dir": "architecture"}
    # Every classified field is a real §3.4 path field, and the two sets are disjoint.
    assert set(READ_PATHS) | set(WRITE_TARGETS) <= PATHS_CONFIG_KEYS
    assert not set(READ_PATHS) & set(WRITE_TARGETS)
    # ``roadmap_glob`` is a glob pattern, not a path: validating it would stat a pattern.
    for field in PATTERN_FIELDS:
        assert field not in READ_PATHS
        assert field not in WRITE_TARGETS


def test_declared_read_path_that_does_not_exist_is_one_error_naming_field_and_path(
    tmp_path: Path,
) -> None:
    """§3.4: a nonexistent read-path is an ERROR naming the field *and* the path."""
    root = tmp_path / "target"
    _make_read_paths_exist(root)
    present = {"schema_version": 1, "paths": {"roadmap_dir": "docs/tasks"}}

    for field, value in MISSING_READ_PATH_VALUES.items():
        corrupted = {"schema_version": 1, "paths": {field: value}}
        issues = validate_paths(_resolved_for(tmp_path, corrupted), root)
        assert len(issues) == 1, (field, format_issues(issues))
        issue = issues[0]
        assert issue.level == ERROR
        assert f"`paths.{field}`" in issue.message
        assert str(root / value) in issue.message
        assert issue.source == CONFIG_FILENAME
        # The provenance is named too, so the operator knows the *config* named it.
        assert "source: config" in issue.message

    # A valid ``paths:`` override (= the default here) produces nothing.
    assert validate_paths(_resolved_for(tmp_path, present), root) == []


def test_default_sourced_read_paths_are_validated_not_skipped(tmp_path: Path) -> None:
    """D17/R7: a config-less repo is validated against the defaults, fail closed.

    ``docs/implementation-results/TEMPLATE.md`` and the two directories are created and
    only ``docs/tasks`` is missing, so exactly one issue arises — for the default-sourced
    ``paths.roadmap_dir``.
    """
    root = tmp_path / "target"
    _make_read_paths_exist(root)
    (root / "docs" / "tasks").rmdir()

    # No config file at all: ``source_path is None`` and no loader issues.
    declared = load_target_config(root / "aidw" / "config.yaml")
    assert declared.source_path is None
    assert declared.issues == []
    resolved = resolve_config(declared)
    assert resolved["paths.roadmap_dir"].source == SOURCE_DEFAULT

    issues = validate_paths(resolved, root)

    assert len(issues) == 1, format_issues(issues)
    assert "`paths.roadmap_dir`" in issues[0].message
    assert str(root / "docs" / "tasks") in issues[0].message
    assert "source: default" in issues[0].message


def test_every_read_path_resolves_with_no_issues_when_present(tmp_path: Path) -> None:
    """All four present (the toolkit's own layout) → no issues, no error."""
    root = tmp_path / "target"
    _make_read_paths_exist(root)

    assert validate_paths(resolve_config(TargetConfig()), root) == []


def test_roadmap_glob_is_a_pattern_and_is_never_existence_checked(tmp_path: Path) -> None:
    """A glob that matches nothing is not a missing path (``[0-9]* - *.md``)."""
    root = tmp_path / "target"
    _make_read_paths_exist(root)
    config = {
        "schema_version": 1,
        "paths": {"roadmap_glob": "nowhere/[0-9]* - *.md", "roadmap_dir": "docs/tasks"},
    }

    assert validate_paths(_resolved_for(tmp_path, config), root) == []


def test_absent_write_target_is_not_a_read_path_issue(tmp_path: Path) -> None:
    """``architecture_dir`` is an output: absent means nothing to validate."""
    root = tmp_path / "target"
    _make_read_paths_exist(root)
    assert not (root / "docs" / "architecture").exists()
    resolved = resolve_config(TargetConfig())
    assert resolved["paths.architecture_dir"].is_set

    assert validate_paths(resolved, root) == []


def test_validate_paths_skips_unset_leaves_defensively(tmp_path: Path) -> None:
    """An unset leaf is never stat'd: there is no path to check, so no issue."""
    resolved = ResolvedConfig(
        {
            "paths.roadmap_dir": ResolvedValue(),
            "paths.task_prompts_dir": ResolvedValue(None, None),
        }
    )

    assert validate_paths(resolved, tmp_path) == []


def test_agent_configs_dir_is_unset_by_default_and_resolves_when_declared(
    tmp_path: Path,
) -> None:
    """E4.6: the override dir has no default; when named it is a config read-path."""
    default_entry = resolve_config(TargetConfig())["paths.agent_configs_dir"]
    assert default_entry.value is None
    assert default_entry.source is None  # unset, not defaulted

    resolved = _resolve_loaded(
        tmp_path,
        {"schema_version": 1, "paths": {"agent_configs_dir": "aidw/agent-configs"}},
    )
    entry = resolved["paths.agent_configs_dir"]
    assert entry.value == "aidw/agent-configs"
    assert entry.source == SOURCE_CONFIG


def test_agent_configs_override_resolves_against_the_target_root(tmp_path: Path) -> None:
    """Req 2: `_target_path` semantics — relative joins the root, absolute wins."""
    root = tmp_path / "target"
    resolved = _resolve_loaded(
        tmp_path,
        {"schema_version": 1, "paths": {"agent_configs_dir": "aidw/agent-configs"}},
    )
    assert agent_configs_override(resolved, root) == root / "aidw" / "agent-configs"

    outside = tmp_path / "shared-agent-configs"
    absolute = _resolve_loaded(
        tmp_path / "absolute",
        {"schema_version": 1, "paths": {"agent_configs_dir": str(outside)}},
    )
    assert agent_configs_override(absolute, root) == outside
    # Unset resolves to None, which is what makes `load_all` use the toolkit defaults.
    assert agent_configs_override(resolve_config(TargetConfig()), root) is None


def test_absolute_read_path_override_wins_over_the_target_root(tmp_path: Path) -> None:
    """§3.4 allows an absolute override; ``target_root / value`` gives it to us free."""
    root = tmp_path / "target"
    _make_read_paths_exist(root)
    outside = tmp_path / "shared-results"
    outside.mkdir()
    present = {
        "schema_version": 1,
        "paths": {"implementation_results_dir": str(outside)},
    }
    absent = {
        "schema_version": 1,
        "paths": {"implementation_results_dir": str(tmp_path / "gone")},
    }

    assert validate_paths(_resolved_for(tmp_path, present), root) == []
    issues = validate_paths(_resolved_for(tmp_path, absent), root)
    assert len(issues) == 1
    assert str(tmp_path / "gone") in issues[0].message


def test_validate_paths_is_pure_and_writes_nothing(tmp_path: Path) -> None:
    """Read-only: the check stats, it never creates, repairs or mutates its input."""
    root = tmp_path / "target"
    _make_read_paths_exist(root)
    (root / "docs" / "tasks").rmdir()
    resolved = resolve_config(TargetConfig())
    resolved_before = copy.deepcopy(resolved.to_dict())
    before = sorted(p.relative_to(root) for p in root.rglob("*"))

    first = validate_paths(resolved, root)
    second = validate_paths(resolved, root)

    assert len(first) == 1
    assert first is not second
    assert sorted(p.relative_to(root) for p in root.rglob("*")) == before
    assert not (root / "docs" / "tasks").exists()
    assert not (root / "docs" / "architecture").exists()
    assert resolved.to_dict() == resolved_before


def test_enabled_write_target_is_created_on_demand(tmp_path: Path) -> None:
    """§3.4: an enabled stage's write-target is created, not required to pre-exist."""
    root = tmp_path / "target"
    root.mkdir()
    declared = TargetConfig()
    resolved = resolve_config(declared)
    target = root / "docs" / "architecture"
    assert not target.exists()

    issues = ensure_write_targets(declared, resolved, root)

    assert issues == []
    assert target.is_dir()


def test_write_target_uses_the_resolved_default_when_the_config_is_silent(
    tmp_path: Path,
) -> None:
    """Every ``PathsConfig`` field is ``str | None``: enablement comes from ``declared``,
    the path from ``resolved`` (the trap the task prompt names)."""
    root = tmp_path / "target"
    root.mkdir()
    declared = load_target_config(root / "aidw" / "config.yaml")
    assert declared.paths is None
    assert declared.workflows == {}

    assert ensure_write_targets(declared, resolve_config(declared), root) == []

    assert (root / "docs" / "architecture").is_dir()


def test_disabled_stage_skips_its_write_target_entirely(tmp_path: Path) -> None:
    """A disabled stage's output directory is neither created nor reported."""
    root = tmp_path / "target"
    root.mkdir()
    declared = TargetConfig(
        workflows={
            "implement": WorkflowConfig(
                stages=[StageConfig(id="architecture", enabled=False)]
            )
        }
    )

    issues = ensure_write_targets(declared, resolve_config(declared), root)

    assert issues == []
    assert not (root / "docs" / "architecture").exists()


def test_enabled_write_target_uses_the_configured_resolved_path(
    tmp_path: Path,
) -> None:
    """The output location comes from ``resolved``, not from the default path."""
    root = tmp_path / "target"
    root.mkdir()
    declared = _load(
        root,
        {"schema_version": 1, "paths": {"architecture_dir": "out/architecture"}},
    )
    assert declared.issues == []

    issues = ensure_write_targets(declared, resolve_config(declared), root)

    assert issues == []
    assert (root / "out" / "architecture").is_dir()
    assert not (root / "docs" / "architecture").exists()


def test_write_target_does_not_swallow_non_oserror(tmp_path: Path, monkeypatch) -> None:
    """Only filesystem ``OSError`` failures become issues; programming errors escape."""
    root = tmp_path / "target"
    root.mkdir()
    declared = TargetConfig()

    def explode(*_args, **_kwargs):
        raise RuntimeError("unexpected mkdir failure")

    monkeypatch.setattr(Path, "mkdir", explode)

    with pytest.raises(RuntimeError, match="unexpected mkdir failure"):
        ensure_write_targets(declared, resolve_config(declared), root)


def test_write_target_is_created_when_its_stage_is_enabled_explicitly(
    tmp_path: Path,
) -> None:
    """``enabled: true`` and no ``enabled`` at all are both enabled (E4.1's chain)."""
    root = tmp_path / "target"
    root.mkdir()
    for stages in ([StageConfig(id="architecture", enabled=True)], [StageConfig(id="architecture")]):
        declared = TargetConfig(workflows={"implement": WorkflowConfig(stages=stages)})
        issues = ensure_write_targets(declared, resolve_config(declared), root)
        assert issues == []
        assert (root / "docs" / "architecture").is_dir()
        (root / "docs" / "architecture").rmdir()


def test_impossible_creation_fails_naming_the_stage_and_the_path(tmp_path: Path) -> None:
    """A parent that is a file is an ``OSError``: report it, never crash or skip."""
    root = tmp_path / "target"
    root.mkdir()
    blocker = root / "docs"
    blocker.write_text("not a directory", encoding="utf-8")
    resolved = resolve_config(TargetConfig())

    issues = ensure_write_targets(TargetConfig(), resolved, root)

    assert len(issues) == 1, format_issues(issues)
    issue = issues[0]
    assert issue.level == ERROR
    assert "architecture" in issue.message
    assert "`paths.architecture_dir`" in issue.message
    assert str(blocker / "architecture") in issue.message
    # The blocker is untouched: nothing is invented around it.
    assert blocker.read_text(encoding="utf-8") == "not a directory"


def test_write_target_path_that_is_a_file_is_an_error_naming_the_stage(
    tmp_path: Path,
) -> None:
    """"absent *or not a directory*": an existing file is not a usable write-target."""
    root = tmp_path / "target"
    (root / "docs").mkdir(parents=True)
    target = root / "docs" / "architecture"
    target.write_text("a file, not a directory", encoding="utf-8")
    resolved = resolve_config(TargetConfig())

    issues = ensure_write_targets(TargetConfig(), resolved, root)

    assert len(issues) == 1, format_issues(issues)
    assert "architecture" in issues[0].message
    assert str(target) in issues[0].message
    assert target.read_text(encoding="utf-8") == "a file, not a directory"


def test_ensure_write_targets_is_idempotent_and_only_creates_the_target(
    tmp_path: Path,
) -> None:
    """A second call is a no-op, and no other ``paths:`` entry is created."""
    root = tmp_path / "target"
    root.mkdir()
    declared = TargetConfig()
    resolved = resolve_config(declared)
    target = root / "docs" / "architecture"

    assert ensure_write_targets(declared, resolved, root) == []
    first = sorted(p.relative_to(root) for p in root.rglob("*"))
    assert ensure_write_targets(declared, resolved, root) == []

    assert sorted(p.relative_to(root) for p in root.rglob("*")) == first
    assert target.is_dir()
    for name in ("tasks", "task-prompts", "implementation-results"):
        assert not (root / "docs" / name).exists()


def _random_path_case(rng: random.Random) -> dict[str, bool]:
    """Which of the four read-paths exist, plus whether architecture is disabled.

    ``build_results_template``'s default lives *inside* ``implementation_results_dir``, so
    a present template implies a present directory; without that constraint the generated
    "absent directory" case would be contradicted by the file just written into it.
    """
    case = {field: rng.random() < 0.5 for field in DEFAULTED_READ_PATHS}
    case["architecture_disabled"] = rng.random() < 0.5
    if case["build_results_template"]:
        case["implementation_results_dir"] = True
    return case


def test_read_path_validation_property(tmp_path: Path) -> None:
    """Seeded property run (seed/numRuns pinned above) over present/absent combinations.

    Invariants: exactly one issue per absent read-path and none for a present one; each
    message names its own field and its own resolved path; ``roadmap_glob`` never
    contributes; ``validate_paths`` writes nothing; a disabled architecture stage never
    creates its directory while an enabled one always does.
    """
    rng = random.Random(PATH_PROPERTY_SEED)

    for index in range(PATH_PROPERTY_RUNS):
        case = _random_path_case(rng)
        root = tmp_path / f"run-{index}"
        root.mkdir()
        present = [field for field in DEFAULTED_READ_PATHS if case[field]]
        absent = [field for field in DEFAULTED_READ_PATHS if not case[field]]
        # ``build_results_template`` lives under ``implementation_results_dir``: create the
        # directories only for the fields generated as present, then the template itself.
        for field in present:
            if field != "build_results_template":
                (root / str(getattr(TOOLKIT_DEFAULTS.paths, field))).mkdir(parents=True)
        if case["build_results_template"]:
            template = root / str(TOOLKIT_DEFAULTS.paths.build_results_template)
            template.parent.mkdir(parents=True, exist_ok=True)
            template.write_text("# t\n", encoding="utf-8")
        declared = TargetConfig(
            workflows={
                "implement": WorkflowConfig(
                    stages=[
                        StageConfig(id="architecture", enabled=not case["architecture_disabled"])
                    ]
                )
            }
        )
        resolved = resolve_config(declared)
        before = sorted(p.relative_to(root) for p in root.rglob("*"))

        issues = validate_paths(resolved, root)

        assert len(issues) == len(absent), (index, absent, format_issues(issues))
        for field, issue in zip(absent, issues, strict=True):
            assert f"`paths.{field}`" in issue.message, (field, issue.message)
            assert str(root / str(getattr(TOOLKIT_DEFAULTS.paths, field))) in issue.message
            assert issue.level == ERROR
        assert sorted(p.relative_to(root) for p in root.rglob("*")) == before

        write_issues = ensure_write_targets(declared, resolved, root)

        assert write_issues == []
        assert (root / "docs" / "architecture").is_dir() is not case["architecture_disabled"]
