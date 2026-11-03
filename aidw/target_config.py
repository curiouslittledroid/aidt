"""Target-repo configuration loading and validation (EXTRACTION.md §3.4, D10, D11).

This module owns the *target* config file — ``<target>/aidw/config.yaml`` — and nothing
else. It is deliberately separate from :mod:`aidw.config`, which means **agent** config
(``agent-configs/*.yaml``, design §5, :func:`aidw.config.load_agent`); overloading that
module with a second, unrelated schema would put two loaders behind one name.

The dataclasses below are the normative §3.4 field names (fixed in task E3.1).

Layered resolution is task E3.2: :func:`resolve_config` merges the toolkit defaults
(:data:`TOOLKIT_DEFAULTS`) under a declared :class:`TargetConfig` and under per-invocation
:class:`ConfigOverrides`, and records the ``source`` of every resolved value
(``default`` | ``config`` | ``override``). The result is a flat, dotted-path
:class:`ResolvedConfig` — ``max_revisions``, ``repo.base_branch``, ``paths.roadmap_dir``,
``github.labels.<name>.color``, ``workflows.<name>.stages`` and so on — so ``aidw config
show`` (EXTRACTION.md §3.3) and every later consumer share one addressing contract.

The loader itself stays deliberately dumb, because resolution must never hide a broken
config:

- It does not inject defaults; a field that is absent stays ``None``/empty. Only
  :func:`resolve_config` merges, so a near-empty config is never re-serialised inflated,
  and a loader caller still sees what was actually declared (E3.1's round-trip). The
  seeded default *values* are E3.4's (the eight ``repo:``/``paths:`` leaves, D17) plus
  design §12's ``max_revisions``; ``github``/``workflows`` stay empty until E6/E4.1 seed
  them, and those tasks likewise add values without touching the merge.
- The *loader* does not compare ``schema_version``/``requires_toolkit``: the fields are
  loaded and type-checked there. Interpreting them is :func:`check_compatibility`
  (E3.3, D10/§3.11), a separate pure pass a workflow preflight runs after the loader.
- It does not touch the filesystem beyond reading the one config file. ``paths:`` values
  are opaque strings; field classification and existence validation are E3.7's
  (:data:`READ_PATH_FIELDS` / :data:`WRITE_TARGET_FIELDS` / :data:`GLOB_PATH_FIELDS`,
  :func:`check_paths`, :func:`resolve_target_path`, :func:`stage_enabled`), a separate
  pure pass over a :class:`ResolvedConfig` that a preflight or ``aidw doctor`` runs.

Validation is fail-closed: **unknown keys are errors at every object level**, wrong types
name the offending field path, and a missing ``schema_version`` (when a config file
exists) or a label entry without ``color``/``description`` is an error. Issues reuse
:class:`aidw.config.Issue` and :data:`aidw.config.ERROR` so ``aidw doctor`` (E3.5) can
format them with the agent-config issues.

A missing config file is **not** an error: §3.4 says a target repo with no ``aidw/``
folder is valid and gets the toolkit's defaults. The caller resolves the target root and
the config path (E3.2/E3.5); this loader takes the file path.

Version and compatibility (E3.3, D10/§3.11) is the third job: :func:`check_compatibility`
refuses a config whose ``schema_version`` is newer than :data:`SUPPORTED_SCHEMA_VERSION`
or whose ``requires_toolkit`` pin this toolkit's own version does not satisfy. It is pure
and takes the toolkit version as an argument, so this module never imports ``aidw``'s
version or a workflow module (``aidw.workflows.prompt`` imports *this* check, never the
reverse).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# PEP 440 version/specifier comparison (E3.3). Deliberately not ``str`` comparison:
# ``"0.1.0" >= "1.0.0"`` is ``True`` lexicographically, and a hand-rolled
# ``tuple(int(x) for x in v.split("."))`` gets pre-release and build metadata wrong.
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

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

#: E3.7's classification of ``paths:``. Every entry in :data:`PATH_FIELDS` is exactly one
#: of these three: a **read-path** an input must exist for (§3.4 "Configured read-paths
#: must exist"), a **write-target** a stage creates on demand, or a **glob** that is a
#: filename pattern rather than a filesystem path. ``roadmap_glob``'s
#: ``[0-9]* - *.md`` is not a path: existence-checking it would treat the literal pattern
#: as a filename and fail every valid config.
READ_PATH_FIELDS = (
    "roadmap_dir",
    "task_prompts_dir",
    "implementation_results_dir",
    "build_results_template",
)
WRITE_TARGET_FIELDS = ("architecture_dir",)
GLOB_PATH_FIELDS = ("roadmap_glob",)

#: The config stage id that owns :data:`WRITE_TARGET_FIELDS` (``architecture_dir``). §3.4's
#: ``workflows.implement.stages`` example fixes the id; the runtime chain's label for the
#: same stage is I4 ``update-architecture``, a different name by design (the flag is read
#: from the *config* vocabulary).
ARCHITECTURE_STAGE_ID = "architecture"

#: ``github.markers`` is a fixed three-key object (D5 / §3.9); any other marker key is a
#: typo, and a missing one is filled by E6's frozen defaults.
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

    Absent optional values stay ``None``/empty: the loader never injects defaults (they
    live in :data:`TOOLKIT_DEFAULTS`, E3.4's) and never interprets ``schema_version``
    (E3.3's). ``source_path`` is ``None`` when no config file was found, which is the
    valid "defaults only" case.
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
    # Review follow-up #77: UnicodeDecodeError is a ValueError, not an OSError, so
    # non-UTF-8 bytes in an operator-controlled config must be caught alongside
    # OSError or the same fail-closed contract is violated with an uncaught crash.
    except (OSError, UnicodeDecodeError) as exc:
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


# --------------------------------------------------------------------------- #
# Version and compatibility (E3.3, EXTRACTION.md §3.11, D10; design §14 exit codes)
# --------------------------------------------------------------------------- #

#: The newest target-config ``schema_version`` this toolkit understands. A config that
#: declares a *higher* number is refused unchanged: §3.11's "exceeds what it
#: understands" / the roadmap's "newer than understood". Deliberately ``>`` and not
#: ``state.py:load``'s ``!=``: an older number (``0``) is not what the spec names, and
#: refusing it would fail repos the spec calls valid.
SUPPORTED_SCHEMA_VERSION = 1

#: The issue ``source`` for a config object built in code (``source_path is None``). The
#: loader labels its issues with ``path.name``; this is that name for the canonical
#: ``<target>/aidw/config.yaml`` location, so both refusals read the same way.
CONFIG_FILENAME = "config.yaml"


def _compat_source(declared: TargetConfig) -> str:
    """The loader's ``path.name`` convention, with a fallback for a code-built config."""
    if declared.source_path is not None:
        return declared.source_path.name
    return CONFIG_FILENAME


def _schema_version_issue(declared_version: int, source: str) -> Issue:
    return Issue(
        ERROR,
        source,
        f"`schema_version` {declared_version} is newer than this toolkit understands "
        f"({SUPPORTED_SCHEMA_VERSION}); upgrade `aidt` to a version that supports "
        f"schema version {declared_version}, or lower the config's `schema_version` "
        f"to {SUPPORTED_SCHEMA_VERSION}.",
    )


def _requires_toolkit_issue(
    specifier: str, toolkit_version: str, source: str
) -> Issue:
    return Issue(
        ERROR,
        source,
        f"`requires_toolkit` {specifier!r} is not satisfied by this toolkit's "
        f"version {toolkit_version}; upgrade `aidt` to a version matching "
        f"{specifier!r}, or relax the pin in `{source}`.",
    )


def _invalid_requires_toolkit_issue(specifier: str, source: str) -> Issue:
    return Issue(
        ERROR,
        source,
        f"`requires_toolkit` {specifier!r} is not a valid version specifier; use a "
        'PEP 440 specifier such as ">=1.0.0", or upgrade `aidt`.',
    )


def _invalid_toolkit_version_issue(
    specifier: str, toolkit_version: str, source: str
) -> Issue:
    return Issue(
        ERROR,
        source,
        f"`requires_toolkit` {specifier!r} cannot be evaluated: this toolkit's own "
        f"version {toolkit_version!r} is not a valid PEP 440 version.",
    )


def check_compatibility(
    declared: TargetConfig, *, toolkit_version: str
) -> list[Issue]:
    """Refuse an incompatible target config (E3.3, EXTRACTION.md §3.11, D10).

    Returns a **fresh** list: empty when the config is compatible, otherwise one
    :data:`~aidw.config.ERROR` issue per violated rule, so the caller can refuse through
    the same ``format_issues`` path as the loader's errors.

    Two independent refusals, both evaluated (a config can violate both):

    1. ``schema_version`` is not ``None`` and is **greater than**
       :data:`SUPPORTED_SCHEMA_VERSION` — "exceeds what it understands". ``None`` is the
       valid defaults-only case (no config file, §3.4), never "newer"; ``0`` or a negative
       number is not newer either.
    2. ``requires_toolkit`` is not ``None`` and this toolkit's ``toolkit_version`` does
       not satisfy it, compared with :mod:`packaging` (PEP 440). An unparseable specifier,
       or an unparseable toolkit version, is a refusal with an actionable message rather
       than a traceback.

    Pure: no I/O, no mutation of ``declared`` (or of anything it references), and a list
    the caller owns. The toolkit version is **passed in** — hardcoding it here would let
    this module disagree with the package it ships in — and the issue ``source`` follows
    the loader's ``path.name`` convention (:data:`CONFIG_FILENAME` when the config was
    built in code rather than read from a file).
    """
    issues: list[Issue] = []
    source = _compat_source(declared)

    if (
        declared.schema_version is not None
        and declared.schema_version > SUPPORTED_SCHEMA_VERSION
    ):
        issues.append(_schema_version_issue(declared.schema_version, source))

    if declared.requires_toolkit is not None:
        specifier = declared.requires_toolkit
        try:
            requirement = SpecifierSet(specifier)
        except InvalidSpecifier:
            issues.append(_invalid_requires_toolkit_issue(specifier, source))
        else:
            try:
                version = Version(toolkit_version)
            except InvalidVersion:
                issues.append(
                    _invalid_toolkit_version_issue(specifier, toolkit_version, source)
                )
            else:
                if version not in requirement:
                    issues.append(
                        _requires_toolkit_issue(specifier, toolkit_version, source)
                    )

    return issues


# --------------------------------------------------------------------------- #
# Layered resolution with provenance (E3.2, EXTRACTION.md §3.3/§3.4, design §12)
# --------------------------------------------------------------------------- #

#: The revision budget's toolkit default (design §12/H8: "the toolkit default stays 3").
#: This module is its single home. §12's "lives in ``aidw/workflows/prompt.py``" wording
#: describes the pre-E3.1 interim state; keeping the definition there would force this
#: low-level loader to import a workflow module, and with ``prompt.py`` importing the
#: resolver back, that is a ``target_config -> workflows.prompt -> target_config`` cycle
#: that breaks ``aidw.cli`` at import time.
DEFAULT_MAX_REVISIONS = 3

#: Provenance labels (EXTRACTION.md §3.3: "with the provenance of each value"; the
#: roadmap's "default, the config file, or an override"). Deliberately the only three: a
#: field with neither a default nor a declared value is *unset*, encoded as
#: ``ResolvedValue(value=None, source=None)`` — there is no fourth label.
SOURCE_DEFAULT = "default"
SOURCE_CONFIG = "config"
SOURCE_OVERRIDE = "override"

#: Every label a resolved value can carry. ``source is None`` (unset) is the fourth state
#: and deliberately not in here, so ``source in SOURCES`` is the "a value resolved" test.
SOURCES = (SOURCE_DEFAULT, SOURCE_CONFIG, SOURCE_OVERRIDE)


@dataclass(frozen=True)
class ResolvedValue:
    """One resolved §3.4 leaf: its value plus where that value came from.

    ``source is None`` is the *unset* state (value ``None`` too): the config did not
    declare the field and no default exists for it. After E3.4 the ``paths:``/``repo:``
    leaves always resolve ``default``; the still-unset leaves are ``requires_toolkit`` and
    ``github.markers.*`` until E6 seeds them. ``aidw config show`` renders that state as
    ``unset`` and omits the ``source`` key in its JSON.
    """

    value: Any = None
    source: str | None = None

    @property
    def is_set(self) -> bool:
        """True when a value resolved (one of the three labels applies)."""
        return self.source is not None

    def to_dict(self) -> dict[str, Any]:
        """``{"value": ..., "source": ...}``, or ``{"value": None}`` when unset."""
        if self.source is None:
            return {"value": None}
        return {"value": self.value, "source": self.source}


@dataclass(frozen=True)
class ResolvedConfig(Mapping[str, ResolvedValue]):
    """The merged config as a flat ``dotted path -> ResolvedValue`` mapping.

    Flat and dotted on purpose: ``schema_version``, ``max_revisions``,
    ``repo.base_branch``, the six ``paths.<field>`` leaves,
    ``github.markers.<name>``, ``github.labels.<name>.{color,description}``, and one
    whole-list entry per declared ``workflows.<name>.{stages,parallel_groups}``.
    Mirroring §3.4's YAML nesting would hand E3.4/E4.1/E6 a second addressing scheme, and
    lists carry provenance only at their own path: the elements are copy-through, never
    merged element-wise, so a repo's stage list replaces the default list rather than
    being interleaved with it.
    """

    entries: Mapping[str, ResolvedValue] = field(default_factory=dict)

    def __getitem__(self, path: str) -> ResolvedValue:
        return self.entries[path]

    def __iter__(self) -> Iterator[str]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def to_dict(self) -> dict[str, dict[str, Any]]:
        """The ``aidw config show`` / JSON dump: one flat ``path -> {value, source}``."""
        return {path: entry.to_dict() for path, entry in self.entries.items()}


@dataclass(frozen=True)
class ConfigOverrides:
    """Per-invocation overrides, which beat both the config file and the defaults.

    ``max_revisions`` is the only config value a CLI flag overrides today
    (``aidw prompt --max-revisions``, design §12/H8), and ``aidw config show``
    deliberately takes no override flag, so this surface is the one place
    ``source == "override"`` can arise. A broader surface belongs to a later task.
    """

    max_revisions: int | None = None


@dataclass(frozen=True)
class ConfigDefaults:
    """Toolkit defaults merged *below* a target repo's declared config (§3.4, D17).

    Seeded with design §12's revision budget (``max_revisions``, H8) and the eight §3.4
    ``repo:``/``paths:`` values E3.4 owns. Those eight are exactly Mythical Forge's
    current layout (D17/R7): deliberately not neutral, so a Mythical-Forge-shaped repo's
    config file is near-empty and doubles as the documented example.

    ``aidw.paths.TargetRepo`` carries the same two ``repo:`` literals as frozen dataclass
    defaults. That is a second home *by design* until E4/E5 wire the resolved config
    through: this module must not import ``aidw.paths`` (layering), so the equality is
    pinned by the tests rather than derived from one shared constant.

    ``github``/``workflows`` are present but empty: an empty slot resolves *unset* rather
    than inventing a value, because those defaults are E6's and E4.1's to own. A later
    task adds values by populating a slot; :func:`resolve_config` already walks the
    slots, so the merge does not change. ``schema_version`` and ``requires_toolkit`` are
    left empty on purpose: the former is required *in* a config file and interpreting it
    is E3.3's, so a repo with no config file has no resolved version; the latter is an
    optional pin, never a default.
    """

    schema_version: int | None = None
    requires_toolkit: str | None = None
    max_revisions: int | None = DEFAULT_MAX_REVISIONS
    # EXTRACTION.md §3.4's ``repo:`` block, character-for-character (D17).
    repo: RepoConfig = field(
        default_factory=lambda: RepoConfig(
            base_branch="main",
            branch_pattern="{phase}-{task}",
        )
    )
    # EXTRACTION.md §3.4's ``paths:`` block, character-for-character (D17).
    # ``roadmap_glob`` is literal: ``[0-9]* - *.md`` (space, dash, space) is what matches
    # the real ``00 - Extraction.md`` filenames; ``[0-9]*-*.md`` would silently match
    # nothing.
    paths: PathsConfig = field(
        default_factory=lambda: PathsConfig(
            roadmap_dir="docs/tasks",
            roadmap_glob="[0-9]* - *.md",
            task_prompts_dir="docs/task-prompts",
            implementation_results_dir="docs/implementation-results",
            build_results_template="docs/implementation-results/TEMPLATE.md",
            architecture_dir="docs/architecture",
        )
    )
    # ``markers`` is materialised (not ``None``) so the merge can read its slots; every
    # field is still ``None``, so markers stay unset until E6 seeds the frozen D5 values.
    github: GitHubConfig = field(default_factory=lambda: GitHubConfig(markers=MarkersConfig()))
    workflows: Mapping[str, WorkflowConfig] = field(default_factory=dict)


#: The toolkit's defaults, resolved once at import; immutable and never mutated.
TOOLKIT_DEFAULTS = ConfigDefaults()


def _override_values(overrides: ConfigOverrides | None) -> dict[str, Any]:
    """The dotted-path override map for this invocation (empty when nothing overrides)."""
    if overrides is None:
        return {}
    values: dict[str, Any] = {}
    if overrides.max_revisions is not None:
        values["max_revisions"] = overrides.max_revisions
    return values


class _Merge:
    """Accumulates ``path -> ResolvedValue`` for the three-source precedence walk."""

    def __init__(self, overrides: Mapping[str, Any]) -> None:
        self._overrides = overrides
        self.entries: dict[str, ResolvedValue] = {}

    def leaf(
        self,
        path: str,
        *,
        declared_value: Any,
        default_value: Any,
        declared: bool | None = None,
    ) -> None:
        """Record one leaf: ``override`` > ``config`` > ``default`` > *unset*.

        ``declared`` is passed explicitly for containers, where an explicitly empty list
        (``stages: []``) must still count as the config declaring the value; elsewhere it
        defaults to "the loader produced a non-``None`` value", which is declared-ness and
        not value equality — an explicit ``max_revisions: 3`` stays ``config``.
        """
        if path in self._overrides:
            self.entries[path] = ResolvedValue(self._overrides[path], SOURCE_OVERRIDE)
            return
        if declared is None:
            declared = declared_value is not None
        if declared:
            self.entries[path] = ResolvedValue(declared_value, SOURCE_CONFIG)
        elif default_value is not None:
            self.entries[path] = ResolvedValue(default_value, SOURCE_DEFAULT)
        else:
            self.entries[path] = ResolvedValue()


def _workflow_value(workflow: WorkflowConfig, key: str) -> list[Any]:
    """One workflow list as plain data: stage dicts, copied ``parallel_groups``.

    Fresh containers on every call, so a resolved value never aliases the declared config
    (or a global default) and mutating a result cannot corrupt a later resolution.
    """
    if key == "stages":
        return [stage.to_dict() for stage in workflow.stages]
    return [list(group) for group in workflow.parallel_groups]


def resolve_config(
    declared: TargetConfig, *, overrides: ConfigOverrides | None = None
) -> ResolvedConfig:
    """Merge toolkit defaults under ``declared``, recording each value's source (§3.4).

    Precedence, highest first: an :class:`ConfigOverrides` value > a value the config file
    declared > :data:`TOOLKIT_DEFAULTS` > *unset* (``value is None`` and ``source is
    None``). ``source`` is exactly ``override``/``config``/``default``; there is no
    fourth label.

    Declared-ness, never value equality, decides ``config``: a config that explicitly sets
    ``max_revisions: 3`` resolves with ``source == "config"`` even though the default is
    also 3, which is what the loader's ``_declared`` bookkeeping exists for.

    Pure: the input (including its nested dataclasses) is never mutated, no I/O happens,
    and every container in the result is freshly built. Callers refuse a config carrying
    ``ERROR`` issues *before* resolving — the merge does not re-validate, and resolving a
    broken config would be exactly the silent-partial-state fallback §3.4 forbids.
    """
    merge = _Merge(_override_values(overrides))
    defaults = TOOLKIT_DEFAULTS

    merge.leaf(
        "schema_version",
        declared_value=declared.schema_version,
        default_value=defaults.schema_version,
    )
    merge.leaf(
        "requires_toolkit",
        declared_value=declared.requires_toolkit,
        default_value=defaults.requires_toolkit,
    )
    merge.leaf(
        "max_revisions",
        declared_value=declared.max_revisions,
        default_value=defaults.max_revisions,
    )

    for name in REPO_FIELDS:
        merge.leaf(
            f"repo.{name}",
            declared_value=(
                getattr(declared.repo, name) if declared.repo is not None else None
            ),
            default_value=getattr(defaults.repo, name),
        )

    for name in PATH_FIELDS:
        merge.leaf(
            f"paths.{name}",
            declared_value=(
                getattr(declared.paths, name) if declared.paths is not None else None
            ),
            default_value=getattr(defaults.paths, name),
        )

    declared_markers = (
        declared.github.markers if declared.github is not None else None
    )
    for name in MARKER_FIELDS:
        merge.leaf(
            f"github.markers.{name}",
            declared_value=(
                getattr(declared_markers, name)
                if declared_markers is not None
                else None
            ),
            default_value=getattr(defaults.github.markers, name),
        )

    # Open maps contribute an entry only for a key that exists on either side: the config
    # file's declared labels, plus (once E6 seeds them) the toolkit's default labels.
    declared_labels = declared.github.labels if declared.github is not None else {}
    for name in sorted(set(declared_labels) | set(defaults.github.labels)):
        declared_label = declared_labels.get(name)
        default_label = defaults.github.labels.get(name)
        for key in LABEL_KEYS:
            merge.leaf(
                f"github.labels.{name}.{key}",
                declared_value=(
                    getattr(declared_label, key)
                    if declared_label is not None
                    else None
                ),
                default_value=(
                    getattr(default_label, key) if default_label is not None else None
                ),
            )

    # Same rule for workflows: a repo-added workflow (D12) contributes its own entries and
    # a workload name seeded by E4.1 would resolve ``default`` until the repo declares it.
    for name in sorted(set(declared.workflows) | set(defaults.workflows)):
        declared_workflow = declared.workflows.get(name)
        default_workflow = defaults.workflows.get(name)
        for key in WORKFLOW_KEYS:
            declared_value = (
                _workflow_value(declared_workflow, key)
                if declared_workflow is not None
                else None
            )
            default_value = (
                _workflow_value(default_workflow, key)
                if default_workflow is not None
                else None
            )
            # A workflow built in code (not via the loader) carries no ``_declared``
            # keys, so a non-empty list is the declared-ness signal there too. The
            # ``_declared`` check is what keeps an explicit ``stages: []`` from looking
            # absent on the round-trip path.
            # Loop-local name must not shadow the ``declared`` TargetConfig
            # parameter: shadowing it crashes the second workflow's iteration
            # (review follow-up for PR #68, finding F1).
            is_declared = declared_workflow is not None and (
                key in declared_workflow._declared or bool(declared_value)
            )
            if not is_declared and default_value is None:
                # Open maps contribute entries only for keys that exist: a workflow's
                # undeclared sibling list is *absent*, not an ``unset`` entry. Otherwise
                # every declared workflow would drag in a phantom
                # ``<name>.parallel_groups`` line.
                continue
            merge.leaf(
                f"workflows.{name}.{key}",
                declared_value=declared_value,
                default_value=default_value,
                declared=is_declared,
            )

    return ResolvedConfig(merge.entries)


# --------------------------------------------------------------------------- #
# Configured path validation (E3.7, EXTRACTION.md §3.4 "Configured read-paths must
# exist"; design §12's doctor duty)
# --------------------------------------------------------------------------- #


def resolve_target_path(value: str, target_root: Path) -> Path:
    """Resolve one ``paths:`` value against the **target** root (EXTRACTION.md §3.1/§3.4).

    ``paths.*`` values are target-relative unless already absolute, so the base is always
    the working tree the workflow operates on — ``TargetRepo.root`` — never
    :func:`aidw.paths.toolkit_root` and never the cwd (AGENTS.md "Two roots"); resolving
    against the toolkit root would flag a healthy target repo's ``docs/`` as missing.
    Pure: no existence requirement, no creation, no mutation. ``resolve()`` is used so the
    path a refusal names is absolute and comparable to an operator's own ``pwd``-based
    diagnosis.
    """
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = target_root / candidate
    return candidate.resolve()


def resolved_path(
    resolved: ResolvedConfig, name: str, target_root: Path
) -> Path | None:
    """The resolved value of ``paths.<name>`` as an absolute path, or ``None`` when unset.

    ``None`` means the leaf resolved *unset* (no declared value and no toolkit default),
    which is the only state where there is nothing to validate or create. Every
    :data:`PATH_FIELDS` leaf has a default today, so it is reached only by a code-built
    config that removed one.
    """
    entry = resolved.get(f"paths.{name}")
    if entry is None or entry.value is None:
        return None
    return resolve_target_path(str(entry.value), target_root)


def check_paths(
    resolved: ResolvedConfig,
    target_root: Path,
    *,
    fields: Sequence[str] | None = None,
) -> list[Issue]:
    """One ``ERROR`` per **read-path** that does not exist under ``target_root`` (§3.4).

    ``fields`` narrows the check to the read-paths a specific preflight first needs
    (``aidw prompt`` validates ``roadmap_dir``/``task_prompts_dir``; the record stage
    validates ``implementation_results_dir``/``build_results_template``). Omitting it
    checks every :data:`READ_PATH_FIELDS` entry — the exhaustive set E3.7's roadmap entry
    fixes (four, not §3.4's three: ``implementation_results_dir`` is the fourth).

    Write-targets produce **no** issue here: they are outputs of a stage and may
    legitimately be absent, and they are created on demand by the stage that owns them
    (:func:`stage_enabled` decides whether that stage is enabled). ``roadmap_glob`` is a
    filename pattern, never a filesystem path, so it is never checked. Asking for a field
    outside :data:`READ_PATH_FIELDS` raises: silently ignoring it would let a later task
    existence-check a write-target or the glob by mistake.

    Existence only — §3.4 says "exist", not "is a directory"/"is a file": the template is
    a file and the three dirs are directories in Mythical Forge's layout, but that typing
    is not part of the contract this check enforces.

    Pure: reads the filesystem (``exists``) and writes nothing, mutates neither the
    :class:`ResolvedConfig` (frozen) nor anything it references, and returns a fresh list
    the caller owns. Each message names both the dotted field (``paths.roadmap_dir``) and
    the resolved absolute path — §3.4's "an error naming the field and the path".
    """
    names = READ_PATH_FIELDS if fields is None else tuple(fields)
    issues: list[Issue] = []
    for name in names:
        if name not in READ_PATH_FIELDS:
            raise ValueError(
                f"`paths.{name}` is not a read-path; only {READ_PATH_FIELDS} are "
                "existence-checked (write-targets are created on demand, "
                "`roadmap_glob` is a filename pattern)"
            )
        path = resolved_path(resolved, name, target_root)
        if path is None:
            # Unset: no declared value and no default, so no path was named to validate.
            continue
        if path.exists():
            continue
        issues.append(
            Issue(
                ERROR,
                CONFIG_FILENAME,
                f"`paths.{name}` does not exist: {path} — create it, or override "
                f"`paths.{name}` in `<target>/aidw/config.yaml` (the toolkit defaults "
                "are Mythical Forge's layout, §3.4/D17)",
            )
        )
    return issues


def stage_enabled(
    resolved: ResolvedConfig, workflow: str, stage_id: str
) -> bool:
    """Whether a config stage is enabled, read from the resolved stage list (§3.4/D12).

    E3.7 reads this **for path validation only** — ``architecture_dir`` may be absent when
    its owning ``architecture`` stage is disabled. Wiring ``enabled`` into the stage chain
    itself is E4.5, so this never decides what runs.

    An absent ``workflows.<workflow>.stages`` entry, or a list that does not mention
    ``stage_id``, is **enabled**: the hardcoded chain still runs the stage, so treating an
    undeclared stage as disabled would silently exempt a path the run will need. An entry
    with ``id: <stage_id>`` and ``enabled: false`` is the only disabled form.
    """
    entry = resolved.get(f"workflows.{workflow}.stages")
    if entry is None or entry.value is None:
        return True
    for stage in entry.value:
        if isinstance(stage, Mapping) and stage.get("id") == stage_id:
            return bool(stage.get("enabled", True))
    return True
