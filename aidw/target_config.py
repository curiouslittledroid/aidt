"""Target-repo configuration loading and validation (EXTRACTION.md §3.4, D10, D11).

This module owns the *target* config file — ``<target>/aidw/config.yaml`` — and nothing
else. It is deliberately separate from :mod:`aidw.config`, which means **agent** config
(``agent-configs/*.yaml``, design §5, :func:`aidw.config.load_agent`); overloading that
module with a second, unrelated schema would put two loaders behind one name.

The dataclasses below are the normative §3.4 field names (fixed in task E3.1). What this
module does *not* do, by design:

- It does not merge toolkit defaults into a config or record per-value provenance — that
  is E3.2. A field that is absent stays ``None``/empty, so a near-empty config is not
  inflated with Mythical Forge's layout values (E3.4 owns those defaults).
- It does not compare or refuse ``schema_version``/``requires_toolkit`` — that is E3.3.
  The fields are loaded and type-checked; their values are not interpreted here.
- It does not touch the filesystem beyond reading the one config file. ``paths:`` values
  are opaque strings; existence validation is E3.7's.

Validation is fail-closed: **unknown keys are errors at every object level**, wrong types
name the offending field path, and a missing ``schema_version`` (when a config file
exists) or a label entry without ``color``/``description`` is an error. Issues reuse
:class:`aidw.config.Issue` and :data:`aidw.config.ERROR` so ``aidw doctor`` (E3.5) can
format them with the agent-config issues.

A missing config file is **not** an error: §3.4 says a target repo with no ``aidw/``
folder is valid and gets the toolkit's defaults. The caller resolves the target root and
the config path (E3.2/E3.5); this loader takes the file path.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Issues are the agent-config ones on purpose: ``aidw doctor`` (E3.5) formats target-config
# validation errors with the same helper. ``format_issues`` is re-exported for that caller.
from aidw.config import ERROR, Issue, format_issues

#: Top-level keys of the §3.4 schema. ``max_revisions`` is design.md §12's key (also
#: carried forward by L4.3); §3.4's YAML example omits it, so a loader that rejects it
#: would reject a legitimate config.
TOP_LEVEL_KEYS = (
    "schema_version",
    "requires_toolkit",
    "max_revisions",
    "repo",
    "paths",
    "workflows",
    "github",
)

REPO_FIELDS = ("base_branch", "branch_pattern")

PATH_FIELDS = (
    "roadmap_dir",
    "roadmap_glob",
    "task_prompts_dir",
    "implementation_results_dir",
    "build_results_template",
    "architecture_dir",
)

#: ``github.markers`` is a fixed three-key object (D5 / §3.9); any other marker key is a
#: typo, and a missing one is filled by E3.2/E3.4's frozen defaults.
MARKER_FIELDS = ("parent", "child", "summary")

WORKFLOW_KEYS = ("stages", "parallel_groups")

#: Stage fields E3.1 owns. ``model``/``thinking``/``timeout_seconds`` are E4.6's stage
#: overrides and are intentionally absent, so a config using them fails loudly here.
STAGE_KEYS = ("id", "enabled", "prompt", "agent")

GITHUB_KEYS = ("markers", "labels")

#: A label entry is exactly ``{color, description}``: ``publish_review_followups.py``
#: reads both unconditionally and D5 freezes names, colours and descriptions together.
LABEL_KEYS = ("color", "description")


def _join(path: str, key: str | int) -> str:
    """Join a field path for an issue message (``workflows.implement.stages[0]``)."""
    if isinstance(key, int):
        return f"{path}[{key}]"
    return f"{path}.{key}" if path else key


def _type_name(value: Any) -> str:
    return "null" if value is None else type(value).__name__


def _declared_keys(raw: Mapping[str, Any]) -> frozenset[str]:
    """The keys the config file actually declared.

    Serialization (:meth:`TargetConfig.to_dict`) uses this instead of comparing against
    defaults, so a declared ``enabled: true`` or an explicit empty container survives a
    round-trip, while an absent field is never injected. The field is excluded from
    equality and ``repr`` so it is bookkeeping, not config.
    """
    return frozenset(str(key) for key in raw)


def _flag_unknown(
    raw: Mapping[str, Any],
    allowed: Iterable[str],
    path: str,
    source: str,
    issues: list[Issue],
) -> None:
    """Reject every key outside ``allowed``, naming the value's full path."""
    allowed_set = set(allowed)
    for key in raw:
        if str(key) not in allowed_set:
            issues.append(Issue(ERROR, source, f"unknown key `{_join(path, str(key))}`"))


def _mapping(
    value: Any,
    path: str,
    source: str,
    issues: list[Issue],
    *,
    null_ok: bool = True,
) -> dict[str, Any] | None:
    """Coerce a YAML mapping to ``dict[str, Any]``, or report the path and return None.

    ``null_ok`` distinguishes an optional container (``repo:`` with no value, treated as
    absent) from a required one (a stage or label entry, where ``null`` is a type error).
    """
    if value is None:
        if null_ok:
            return None
        issues.append(Issue(ERROR, source, f"`{path}` must be a mapping, got null"))
        return None
    if not isinstance(value, Mapping):
        issues.append(
            Issue(ERROR, source, f"`{path}` must be a mapping, got {_type_name(value)}")
        )
        return None
    return {str(key): item for key, item in value.items()}


def _read_str(
    raw: Mapping[str, Any],
    key: str,
    parent: str,
    source: str,
    issues: list[Issue],
    *,
    required: bool = False,
) -> str | None:
    path = _join(parent, key)
    if key not in raw:
        if required:
            issues.append(Issue(ERROR, source, f"missing required key `{path}`"))
        return None
    value = raw[key]
    if not isinstance(value, str):
        issues.append(
            Issue(ERROR, source, f"`{path}` must be a string, got {_type_name(value)}")
        )
        return None
    if required and not value:
        issues.append(Issue(ERROR, source, f"missing required key `{path}`"))
        return None
    return value


def _read_bool(
    raw: Mapping[str, Any],
    key: str,
    parent: str,
    source: str,
    issues: list[Issue],
    *,
    default: bool,
) -> bool:
    path = _join(parent, key)
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, bool):
        issues.append(
            Issue(ERROR, source, f"`{path}` must be a boolean, got {_type_name(value)}")
        )
        return default
    return value


def _read_int(
    raw: Mapping[str, Any],
    key: str,
    parent: str,
    source: str,
    issues: list[Issue],
    *,
    required: bool = False,
) -> int | None:
    path = _join(parent, key)
    if key not in raw:
        if required:
            issues.append(Issue(ERROR, source, f"missing required key `{path}`"))
        return None
    value = raw[key]
    # ``bool`` is an ``int`` subclass; ``schema_version: true`` must not pass.
    if isinstance(value, bool) or not isinstance(value, int):
        issues.append(
            Issue(ERROR, source, f"`{path}` must be an integer, got {_type_name(value)}")
        )
        return None
    return value


@dataclass
class StageConfig:
    """One workflow stage (EXTRACTION.md §3.5)."""

    id: str
    enabled: bool = True
    prompt: str | None = None
    agent: str | None = None
    _declared: frozenset[str] = field(
        default_factory=frozenset, compare=False, repr=False
    )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id}
        # ``enabled`` defaults to true, so absence and an explicit ``true`` are only
        # distinguishable through the declared-key set (§3.4 "disabled with enabled: false").
        if not self.enabled or "enabled" in self._declared:
            data["enabled"] = self.enabled
        if self.prompt is not None:
            data["prompt"] = self.prompt
        if self.agent is not None:
            data["agent"] = self.agent
        return data


@dataclass
class WorkflowConfig:
    """A workflow's stage list and parallel-safe pairs (§3.4, §3.5)."""

    stages: list[StageConfig] = field(default_factory=list)
    parallel_groups: list[list[str]] = field(default_factory=list)
    _declared: frozenset[str] = field(
        default_factory=frozenset, compare=False, repr=False
    )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.stages or "stages" in self._declared:
            data["stages"] = [stage.to_dict() for stage in self.stages]
        if self.parallel_groups or "parallel_groups" in self._declared:
            data["parallel_groups"] = [list(group) for group in self.parallel_groups]
        return data


@dataclass
class RepoConfig:
    base_branch: str | None = None
    branch_pattern: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.base_branch is not None:
            data["base_branch"] = self.base_branch
        if self.branch_pattern is not None:
            data["branch_pattern"] = self.branch_pattern
        return data


@dataclass
class PathsConfig:
    roadmap_dir: str | None = None
    roadmap_glob: str | None = None
    task_prompts_dir: str | None = None
    implementation_results_dir: str | None = None
    build_results_template: str | None = None
    architecture_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            name: value
            for name in PATH_FIELDS
            if (value := getattr(self, name)) is not None
        }


@dataclass
class MarkersConfig:
    """The fixed three marker templates (D5 / §3.9: frozen values, per-repo config)."""

    parent: str | None = None
    child: str | None = None
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            name: value
            for name in MARKER_FIELDS
            if (value := getattr(self, name)) is not None
        }


@dataclass
class LabelConfig:
    """One ``github.labels`` entry: exactly a colour and a description (D5)."""

    color: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {"color": self.color, "description": self.description}


@dataclass
class GitHubConfig:
    markers: MarkersConfig | None = None
    labels: dict[str, LabelConfig] = field(default_factory=dict)
    _declared: frozenset[str] = field(
        default_factory=frozenset, compare=False, repr=False
    )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.markers is not None:
            data["markers"] = self.markers.to_dict()
        if self.labels or "labels" in self._declared:
            data["labels"] = {
                name: label.to_dict() for name, label in self.labels.items()
            }
        return data


@dataclass
class TargetConfig:
    """The declared ``<target>/aidw/config.yaml`` (§3.4).

    Absent optional values stay ``None``/empty: the loader never injects defaults (E3.4's
    job) and never interprets ``schema_version`` (E3.3's). ``source_path`` is ``None``
    when no config file was found, which is the valid "defaults only" case.
    """

    schema_version: int | None = None
    requires_toolkit: str | None = None
    max_revisions: int | None = None
    repo: RepoConfig | None = None
    paths: PathsConfig | None = None
    workflows: dict[str, WorkflowConfig] = field(default_factory=dict)
    github: GitHubConfig | None = None
    #: Where the config was read from, or ``None`` when no file existed. Excluded from
    #: equality so a config loaded from another path still compares equal (round-trip).
    source_path: Path | None = field(default=None, compare=False)
    issues: list[Issue] = field(default_factory=list)
    _declared: frozenset[str] = field(
        default_factory=frozenset, compare=False, repr=False
    )

    def to_dict(self) -> dict[str, Any]:
        """Return the declared config as plain data (YAML-safe, no injected defaults).

        A config that declared only ``schema_version`` serializes to exactly
        ``{"schema_version": 1}``; a stage that did not declare ``enabled`` does not gain
        one. This is what makes the YAML → dataclass → dict → YAML round-trip lossless.
        """
        data: dict[str, Any] = {}
        if self.schema_version is not None:
            data["schema_version"] = self.schema_version
        if self.requires_toolkit is not None:
            data["requires_toolkit"] = self.requires_toolkit
        if self.max_revisions is not None:
            data["max_revisions"] = self.max_revisions
        if self.repo is not None:
            data["repo"] = self.repo.to_dict()
        if self.paths is not None:
            data["paths"] = self.paths.to_dict()
        if self.workflows or "workflows" in self._declared:
            data["workflows"] = {
                name: workflow.to_dict() for name, workflow in self.workflows.items()
            }
        if self.github is not None:
            data["github"] = self.github.to_dict()
        return data


def _parse_stage(
    raw: Mapping[str, Any], path: str, source: str, issues: list[Issue]
) -> StageConfig:
    _flag_unknown(raw, STAGE_KEYS, path, source, issues)
    return StageConfig(
        id=_read_str(raw, "id", path, source, issues, required=True) or "",
        enabled=_read_bool(raw, "enabled", path, source, issues, default=True),
        prompt=_read_str(raw, "prompt", path, source, issues),
        agent=_read_str(raw, "agent", path, source, issues),
        _declared=_declared_keys(raw),
    )


def _parse_parallel_groups(
    raw: Mapping[str, Any], path: str, source: str, issues: list[Issue]
) -> list[list[str]]:
    key = "parallel_groups"
    if key not in raw:
        return []
    groups_path = _join(path, key)
    value = raw[key]
    if not isinstance(value, list):
        issues.append(
            Issue(
                ERROR,
                source,
                f"`{groups_path}` must be a list of lists, got {_type_name(value)}",
            )
        )
        return []

    groups: list[list[str]] = []
    for index, group in enumerate(value):
        group_path = _join(groups_path, index)
        if not isinstance(group, list):
            issues.append(
                Issue(
                    ERROR,
                    source,
                    f"`{group_path}` must be a list, got {_type_name(group)}",
                )
            )
            continue
        members: list[str] = []
        for member_index, member in enumerate(group):
            member_path = _join(group_path, member_index)
            if not isinstance(member, str):
                issues.append(
                    Issue(
                        ERROR,
                        source,
                        f"`{member_path}` must be a string, got {_type_name(member)}",
                    )
                )
                continue
            members.append(member)
        groups.append(members)
    return groups


def _parse_workflow(
    raw: Mapping[str, Any], path: str, source: str, issues: list[Issue]
) -> WorkflowConfig:
    _flag_unknown(raw, WORKFLOW_KEYS, path, source, issues)

    stages: list[StageConfig] = []
    if "stages" in raw:
        stages_path = _join(path, "stages")
        value = raw["stages"]
        if not isinstance(value, list):
            issues.append(
                Issue(
                    ERROR,
                    source,
                    f"`{stages_path}` must be a list, got {_type_name(value)}",
                )
            )
        else:
            for index, entry in enumerate(value):
                stage_path = _join(stages_path, index)
                stage_raw = _mapping(entry, stage_path, source, issues, null_ok=False)
                if stage_raw is not None:
                    stages.append(_parse_stage(stage_raw, stage_path, source, issues))

    return WorkflowConfig(
        stages=stages,
        parallel_groups=_parse_parallel_groups(raw, path, source, issues),
        _declared=_declared_keys(raw),
    )


def _parse_workflows(
    raw: Mapping[str, Any], path: str, source: str, issues: list[Issue]
) -> dict[str, WorkflowConfig]:
    """Workflow names are an open map (D12 lets a repo add stages; §3.5 names five,
    §3.4 shows two). Only the workflow's *shape* is validated here; the stage-id
    vocabulary and core-vs-optional rules are E4.1/E4.5's."""
    workflows: dict[str, WorkflowConfig] = {}
    for key, value in raw.items():
        name = str(key)
        workflow_path = _join(path, name)
        workflow_raw = _mapping(value, workflow_path, source, issues, null_ok=False)
        if workflow_raw is not None:
            workflows[name] = _parse_workflow(workflow_raw, workflow_path, source, issues)
    return workflows


def _parse_markers(
    raw: Mapping[str, Any], path: str, source: str, issues: list[Issue]
) -> MarkersConfig:
    _flag_unknown(raw, MARKER_FIELDS, path, source, issues)
    return MarkersConfig(
        **{
            name: _read_str(raw, name, path, source, issues)
            for name in MARKER_FIELDS
        }
    )


def _parse_labels(
    raw: Mapping[str, Any], path: str, source: str, issues: list[Issue]
) -> dict[str, LabelConfig]:
    """``github.labels`` is an open map keyed by label *name* (D5/§3.9); every entry is
    exactly ``{color, description}``, both required."""
    labels: dict[str, LabelConfig] = {}
    for key, value in raw.items():
        name = str(key)
        entry_path = _join(path, name)
        entry = _mapping(value, entry_path, source, issues, null_ok=False)
        if entry is None:
            continue
        _flag_unknown(entry, LABEL_KEYS, entry_path, source, issues)
        labels[name] = LabelConfig(
            color=_read_str(entry, "color", entry_path, source, issues, required=True)
            or "",
            description=_read_str(
                entry, "description", entry_path, source, issues, required=True
            )
            or "",
        )
    return labels


def _parse_github(
    raw: Mapping[str, Any], path: str, source: str, issues: list[Issue]
) -> GitHubConfig:
    _flag_unknown(raw, GITHUB_KEYS, path, source, issues)

    markers_path = _join(path, "markers")
    markers_raw = (
        _mapping(raw["markers"], markers_path, source, issues, null_ok=False)
        if "markers" in raw
        else None
    )
    markers = (
        _parse_markers(markers_raw, markers_path, source, issues)
        if markers_raw is not None
        else None
    )

    labels_path = _join(path, "labels")
    labels_raw = (
        _mapping(raw["labels"], labels_path, source, issues, null_ok=False)
        if "labels" in raw
        else None
    )
    labels = (
        _parse_labels(labels_raw, labels_path, source, issues)
        if labels_raw is not None
        else {}
    )

    return GitHubConfig(
        markers=markers, labels=labels, _declared=_declared_keys(raw)
    )


def _parse_target_config(
    raw: Mapping[str, Any], source: str, source_path: Path, issues: list[Issue]
) -> TargetConfig:
    _flag_unknown(raw, TOP_LEVEL_KEYS, "", source, issues)

    repo_raw = (
        _mapping(raw["repo"], "repo", source, issues, null_ok=False)
        if "repo" in raw
        else None
    )
    if repo_raw is not None:
        _flag_unknown(repo_raw, REPO_FIELDS, "repo", source, issues)
    repo = (
        RepoConfig(
            **{
                name: _read_str(repo_raw, name, "repo", source, issues)
                for name in REPO_FIELDS
            }
        )
        if repo_raw is not None
        else None
    )

    paths_raw = (
        _mapping(raw["paths"], "paths", source, issues, null_ok=False)
        if "paths" in raw
        else None
    )
    if paths_raw is not None:
        _flag_unknown(paths_raw, PATH_FIELDS, "paths", source, issues)
    paths = (
        PathsConfig(
            **{
                name: _read_str(paths_raw, name, "paths", source, issues)
                for name in PATH_FIELDS
            }
        )
        if paths_raw is not None
        else None
    )

    workflows_raw = (
        _mapping(raw["workflows"], "workflows", source, issues, null_ok=False)
        if "workflows" in raw
        else None
    )
    workflows = (
        _parse_workflows(workflows_raw, "workflows", source, issues)
        if workflows_raw is not None
        else {}
    )

    github_raw = (
        _mapping(raw["github"], "github", source, issues, null_ok=False)
        if "github" in raw
        else None
    )
    github = (
        _parse_github(github_raw, "github", source, issues)
        if github_raw is not None
        else None
    )

    return TargetConfig(
        schema_version=_read_int(
            raw, "schema_version", "", source, issues, required=True
        ),
        requires_toolkit=_read_str(raw, "requires_toolkit", "", source, issues),
        max_revisions=_read_int(raw, "max_revisions", "", source, issues),
        repo=repo,
        paths=paths,
        workflows=workflows,
        github=github,
        source_path=source_path,
        issues=issues,
        _declared=_declared_keys(raw),
    )


def load_target_config(path: Path) -> TargetConfig:
    """Load and validate ``<target>/aidw/config.yaml`` (§3.4, D11).

    ``path`` is the config **file**, not the target repo root: resolving the root and the
    config path is the caller's job (E3.2/E3.5). A missing file is valid — it returns an
    empty :class:`TargetConfig` with no issues, because a target repo with no ``aidw/``
    folder gets the toolkit defaults (§3.4). Anything else that cannot be read or parsed,
    or that is not a YAML mapping, is an error (never an ``AttributeError``).
    """
    issues: list[Issue] = []
    source = path.name

    if not path.exists():
        return TargetConfig()

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        issues.append(Issue(ERROR, source, f"cannot read/parse config: {exc}"))
        return TargetConfig(source_path=path, issues=issues)

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        issues.append(Issue(ERROR, source, f"cannot read/parse config: {exc}"))
        return TargetConfig(source_path=path, issues=issues)

    if not isinstance(raw, Mapping):
        # Covers ``None`` (empty file) and a top-level list/scalar.
        issues.append(Issue(ERROR, source, "config must be a YAML mapping"))
        return TargetConfig(source_path=path, issues=issues)

    return _parse_target_config(dict(raw), source, path, issues)
