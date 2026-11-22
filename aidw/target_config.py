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
  seeded default *values* are E3.4's (the eight ``repo:``/``paths:`` leaves, D17), design
  §12's ``max_revisions`` and — since E6.1 — the frozen D5 ``github.markers``/
  ``github.labels`` values (a second home for ``prompts/scripts/review-followup/
  constants.py``, which this package cannot import). ``workflows`` stays empty until E4.1
  seeds it; each of those tasks adds a value without touching the merge.
- The *loader* does not compare ``schema_version``/``requires_toolkit``: the fields are
  loaded and type-checked there. Interpreting them is :func:`check_compatibility`
  (E3.3, D10/§3.11), a separate pure pass a workflow preflight runs after the loader.
- It does not touch the filesystem beyond reading the one config file. Translating a
  ``paths:`` string into a filesystem check is :func:`validate_paths`/
  :func:`ensure_write_targets` (E3.7), which take a resolved config and a target root;
  the loader never stats a path.

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

Path classification (E3.7, §3.4 "Configured read-paths must exist") is the fourth and
last job: every ``paths:`` entry is either a **read-path** (:data:`READ_PATHS`), which must
exist when a config or a toolkit default names it, or a **write-target**
(:data:`WRITE_TARGETS`), which a stage creates on demand. :func:`validate_paths` is the
read-path check (pure, no writes, no fallback); :func:`ensure_write_targets` is the
write-target side (``mkdir`` only, and only for a stage that is enabled). ``roadmap_glob``
is a pattern, not a path, and is neither classified nor existence-checked. G1.3's
``specs_dir`` is a path but also neither: optional and legitimately absent, so ``aidw
doctor`` WARNs rather than :func:`validate_paths` failing a repo whose ``Design N``
citations resolve against a root ``design.md``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any

import yaml

# PEP 440 version/specifier comparison (E3.3). Deliberately not ``str`` comparison:
# ``"0.1.0" >= "1.0.0"`` is ``True`` lexicographically, and a hand-rolled
# ``tuple(int(x) for x in v.split("."))`` gets pre-release and build metadata wrong.
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

# Issues are the agent-config ones on purpose: ``aidw doctor`` (E3.5) formats target-config
# validation errors with the same helper. ``format_issues`` is re-exported for that caller.
# ``THINKING_LEVELS`` is design §5.1's value space, reused rather than restated: a per-stage
# ``thinking`` override (E4.6) must accept exactly the levels an agent config accepts, and a
# second literal tuple would let the two drift.
from aidw.config import ERROR, THINKING_LEVELS, Issue, format_issues

# S1.1: ``normalise_ignore`` is the one rule for "a repo-relative path prefix" — the gate
# CLI's ``--ignore`` scope, ``tree_identity``'s declared scope and a stage's ``when_paths``
# (design §12.2). Reusing it keeps the loader from restating the rule (a second copy would
# let them disagree about `./x`, a trailing slash, `..` or an absolute path). The import is
# a leaf direction: ``verification`` imports only ``aidw.git``/``aidw.state``.
from aidw.verification import normalise_ignore

#: Top-level keys of the §3.4 schema. ``max_revisions`` is design.md §12's key (also
#: carried forward by L4.3); §3.4's YAML example omits it, so a loader that rejects it
#: would reject a legitimate config.
TOP_LEVEL_KEYS = (
    "schema_version",
    "requires_toolkit",
    "max_revisions",
    # C1.2 (design §7.3 step 4): the full ``## ``-prefixed heading line that introduces
    # the target's gate commands, recognised in addition to ``## Gates``/
    # ``## Gate commands``. Optional and unset by default; no toolkit default exists.
    "gates_heading",
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
    # E4.6's global agent-config override (D12 "override agent config globally"): a
    # target-repo directory whose ``*.yaml`` files shadow the toolkit's by id.
    "agent_configs_dir",
    # G1.3 (design §8.1/§12.1, §17 Z22): the directory a ``Design N`` citation resolves
    # against — one flat scan for ``Design <number> - <title>.md``. Unset, not defaulted:
    # a repo whose specs are one root ``design.md`` keeps today's channel unchanged.
    "specs_dir",
)

#: ``github.markers`` is a fixed three-key object (D5 / §3.9); any other marker key is a
#: typo, and a missing one is filled by E6's frozen defaults.
MARKER_FIELDS = ("parent", "child", "summary")

WORKFLOW_KEYS = ("stages", "parallel_groups")

#: Stage fields. E3.1 owns ``id``/``enabled``/``prompt``/``agent``; E4.6 adds the three
#: stage-metadata overrides D12 names (``agent/model/timeout/thinking``) minus ``agent``,
#: which E4.5b already carried. They are validated here and honoured by the runner.
STAGE_KEYS = (
    "id",
    "enabled",
    "prompt",
    "agent",
    "model",
    "thinking",
    "timeout_seconds",
    # S1.1 (design §12.2): the repo-declared path set a ``when=paths-changed`` stage is
    # gated on. Optional, and the only stage field whose value is a list of path prefixes.
    "when_paths",
)

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


def _check_roadmap_glob(
    paths_raw: Mapping[str, Any], source: str, issues: list[Issue]
) -> None:
    """Reject a degenerate declared ``paths.roadmap_glob`` (review follow-up PR #97, F1).

    ``roadmap_glob`` is the one ``paths`` value that is a pattern, not a path, so it is
    deliberately outside :data:`READ_PATHS`/:data:`WRITE_TARGETS` — nothing stat's it,
    and pre-fix a degenerate value reached ``Path.glob`` unguarded (E5.2): an empty
    pattern or an absolute one (``/etc/*.md``) raises there (``ValueError`` /
    ``NotImplementedError`` on Python 3.13+) and traceback'd both consumers (``aidw
    tasks``, the prompt workflow) instead of their documented stderr refusals. The
    loader is where every other bad ``paths`` value fails closed — §3.4's wrong-type
    contract — so the two shapes ``Path.glob`` refuses become an ``ERROR`` naming
    ``paths.roadmap_glob`` here, and both callers refuse through their existing config
    refusal sites (``aidw tasks``'s error check, ``resolve_workflow_config``), before
    resolution and before ``load_tasks``.

    Only a *declared* value is checked: the toolkit default (D17, ``[0-9]* - *.md``)
    stays the only in-code pattern, and a non-string value is already a wrong-type
    ``ERROR`` from ``_read_str`` — reporting it here too would duplicate the issue for
    one bad value. Host-flavour ``PurePath`` mirrors what ``Path.glob`` will see, so
    the rule is the loader's own and not a Python version's exception behaviour.
    """
    if "roadmap_glob" not in paths_raw:
        return
    value = paths_raw["roadmap_glob"]
    if not isinstance(value, str):
        return
    if not value:
        issues.append(
            Issue(
                ERROR,
                source,
                "`paths.roadmap_glob` must be a non-empty glob pattern, got ''",
            )
        )
    elif PurePath(value).is_absolute():
        issues.append(
            Issue(
                ERROR,
                source,
                f"`paths.roadmap_glob` must be a relative glob pattern, got {value!r}",
            )
        )


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
    #: E4.6's per-stage metadata overrides (D12): a ``provider/model``-shaped model id, a
    #: design §5.1 ``thinking`` level, and a positive wall-clock timeout. All ``None`` when
    #: the stage declared none, so an absent override is never serialised as ``null``.
    model: str | None = None
    thinking: str | None = None
    timeout_seconds: int | None = None
    #: S1.1's path-scoped stage condition (design §12.2): repo-relative prefixes the
    #: change set must touch for a ``when=paths-changed`` stage to run. ``None`` when the
    #: entry declared none (an absent declaration is never serialised), otherwise the
    #: **normalised** list — sorted, deduped, ``verification.normalise_ignore``'s rule — so
    #: an explicit empty list survives a round-trip and ``./docs/x``/``docs/x/`` are one value.
    when_paths: list[str] | None = None
    _declared: frozenset[str] = field(
        default_factory=frozenset, compare=False, repr=False
    )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id}
        # ``enabled`` defaults to true, so absence and an explicit ``true`` are only
        # distinguishable through the declared-key set (§3.4 "disabled with enabled: false").
        if not self.enabled or "enabled" in self._declared:
            data["enabled"] = self.enabled
        # Every optional field is ``None`` when absent, so the declared config round-trips
        # exactly: no ``null`` is injected for a setting the file did not name.
        for name in ("prompt", "agent", "model", "thinking", "timeout_seconds"):
            value = getattr(self, name)
            if value is not None:
                data[name] = value
        # A list-valued field: ``None`` means "not declared" (never serialised), while a
        # declared ``[]`` is a real declaration and must survive the round-trip.
        if self.when_paths is not None:
            data["when_paths"] = list(self.when_paths)
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
    #: E4.6's global agent-config override: a target-repo directory whose ``*.yaml`` files
    #: shadow the toolkit's ``agent-configs/`` by id. Deliberately **unset, not defaulted**
    #: (no value in :data:`TOOLKIT_DEFAULTS`): the consumer falls back to the toolkit
    #: directory, so a repo with no such folder never validates a path it does not have.
    agent_configs_dir: str | None = None
    #: G1.3's spec-directory override: a target-repo directory of one document per design
    #: number (``Design <number> - <title>.md``), scanned flat. Deliberately **unset, not
    #: defaulted** (no value in :data:`TOOLKIT_DEFAULTS`), and deliberately neither a
    #: read-path nor a write-target: absent is the valid case for a repo whose specs are a
    #: root ``design.md``, so ``aidw doctor`` WARNs rather than :func:`validate_paths`
    #: failing a directory the workflow reads only when the channel resolves a citation.
    specs_dir: str | None = None

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
    #: C1.2: the extra gate-commands heading, as the **full heading line including its
    #: ``## `` prefix** (``## Verification gates``). ``None`` when unset; the loader
    #: rejects an empty string, because ``line.startswith("")`` would match every line.
    gates_heading: str | None = None
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
        if self.gates_heading is not None:
            data["gates_heading"] = self.gates_heading
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
    """One stage entry, with E4.6's three metadata overrides validated on load.

    Each value space is the one the consumer already has: ``thinking`` is design §5.1's
    :data:`~aidw.config.THINKING_LEVELS`, ``timeout_seconds`` is a positive integer and
    ``model`` a non-empty string. The failure names the dotted field path
    (``workflows.implement.stages[0].thinking``), matching the loader's unknown-key and
    wrong-type contract, and the value is dropped (``None``) so a refused config can never
    be resolved into a half-applied override.
    """
    _flag_unknown(raw, STAGE_KEYS, path, source, issues)

    model = _read_str(raw, "model", path, source, issues)
    if model is not None and not model:
        issues.append(
            Issue(
                ERROR,
                source,
                f"`{_join(path, 'model')}` must be a non-empty string",
            )
        )
        model = None

    thinking = _read_str(raw, "thinking", path, source, issues)
    if thinking is not None and thinking not in THINKING_LEVELS:
        issues.append(
            Issue(
                ERROR,
                source,
                f"`{_join(path, 'thinking')}` must be one of {THINKING_LEVELS}, "
                f"got {thinking!r}",
            )
        )
        thinking = None

    timeout_seconds = _read_int(raw, "timeout_seconds", path, source, issues)
    if timeout_seconds is not None and timeout_seconds <= 0:
        issues.append(
            Issue(
                ERROR,
                source,
                f"`{_join(path, 'timeout_seconds')}` must be a positive integer, "
                f"got {timeout_seconds}",
            )
        )
        timeout_seconds = None

    return StageConfig(
        id=_read_str(raw, "id", path, source, issues, required=True) or "",
        enabled=_read_bool(raw, "enabled", path, source, issues, default=True),
        prompt=_read_str(raw, "prompt", path, source, issues),
        agent=_read_str(raw, "agent", path, source, issues),
        model=model,
        thinking=thinking,
        timeout_seconds=timeout_seconds,
        when_paths=_parse_when_paths(raw, path, source, issues),
        _declared=_declared_keys(raw),
    )


def _parse_when_paths(
    raw: Mapping[str, Any], path: str, source: str, issues: list[Issue]
) -> list[str] | None:
    """S1.1's declared path set, canonicalised and fail-closed (design §12.1).

    :func:`aidw.verification.normalise_ignore` owns what a valid repo-relative prefix is,
    so this loader does not restate the rule: a **wrong-typed** value is one ``ERROR``
    naming the dotted field and the field is dropped, and each **bad entry** (a non-string,
    an absolute path, ``.``, ``..`` or empty) is one ``ERROR`` naming its own dotted entry
    path and is dropped while parsing continues — the same per-entry discipline
    :func:`_parse_parallel_groups` applies, so one typo never hides the rest. The surviving
    entries are normalised, sorted and deduped by the same rule, so ``./docs/x`` and
    ``docs/x/`` are one declaration and ordering never matters.

    ``None`` means the entry declared no ``when_paths`` at all; an explicit ``[]`` is a
    declaration and is preserved as one (both mean "unconditional" to the workflow).
    """
    key = "when_paths"
    if key not in raw:
        return None
    field_path = _join(path, key)
    value = raw[key]
    if not isinstance(value, list):
        issues.append(
            Issue(
                ERROR,
                source,
                f"`{field_path}` must be a list of repo-relative path prefixes, "
                f"got {_type_name(value)}",
            )
        )
        return None

    entries: list[str] = []
    for index, entry in enumerate(value):
        entry_path = _join(field_path, index)
        if not isinstance(entry, str):
            issues.append(
                Issue(
                    ERROR,
                    source,
                    f"`{entry_path}` must be a string, got {_type_name(entry)}",
                )
            )
            continue
        try:
            entries.extend(normalise_ignore([entry]))
        except ValueError:
            # The helper's own refusal names the bad value; this converts it to a config
            # issue and never propagates it (a loader must not raise on a bad file).
            issues.append(
                Issue(
                    ERROR,
                    source,
                    f"`{entry_path}` must be a repo-relative path prefix such as "
                    f"docs/rules-coverage, got {entry!r}",
                )
            )
    # Every surviving entry was already accepted above, so this pass only sorts and
    # dedupes; it cannot raise.
    return list(normalise_ignore(entries))


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
        _check_roadmap_glob(paths_raw, source, issues)
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

    # C1.2: ``_read_str`` passes an optional key's ``""`` through (the `model`/
    # `paths.roadmap_glob` precedent), but an empty heading would make the shared
    # ``startswith`` recognition match every line, so it is one ERROR naming the field and
    # the value is dropped.
    gates_heading = _read_str(raw, "gates_heading", "", source, issues)
    if gates_heading is not None and not gates_heading:
        issues.append(
            Issue(ERROR, source, "`gates_heading` must be a non-empty string, got ''")
        )
        gates_heading = None

    return TargetConfig(
        schema_version=_read_int(
            raw, "schema_version", "", source, issues, required=True
        ),
        requires_toolkit=_read_str(raw, "requires_toolkit", "", source, issues),
        max_revisions=_read_int(raw, "max_revisions", "", source, issues),
        gates_heading=gates_heading,
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
    declare the field and no default exists for it. After E6.1 the ``paths:``/``repo:``
    leaves and every ``github.markers.*``/``github.labels.*`` leaf always resolve
    ``default``; the still-unset leaves are ``schema_version``, ``requires_toolkit``,
    ``paths.agent_configs_dir`` and G1.3's ``paths.specs_dir``. ``aidw config show``
    renders that state as ``unset`` and omits the ``source`` key in its JSON.
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
    ``repo.base_branch``, the eight ``paths.<field>`` leaves (six seeded defaults plus
    E4.6's unset ``agent_configs_dir`` and G1.3's unset ``specs_dir``),
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

    ``paths.agent_configs_dir`` and G1.3's ``paths.specs_dir`` are deliberately absent from
    the seeded block even though the fields exist (§3.4's ``paths:`` example does not name
    either): both are "unset, not defaulted". The former's consumer falls back to
    ``<toolkit>/agent-configs`` and a seeded repo-relative path would make every repo
    without that folder fail :func:`validate_paths`; the latter resolves ``Design N``
    citations, and an unset value is the valid case that keeps today's root-``design.md``
    channel byte-identical. Seeding nothing is what keeps a config-less repo valid.

    ``github`` carries the frozen D5 markers and label definitions (E6.1, §3.4/§3.9).
    ``workflows`` is present but empty: an empty slot resolves *unset* rather than
    inventing a value, because that default is E4.1's to own. A later task adds values by
    populating a slot; :func:`resolve_config` already walks the slots, so the merge does
    not change. ``schema_version`` and ``requires_toolkit`` are left empty on purpose: the
    former is required *in* a config file and interpreting it is E3.3's, so a repo with no
    config file has no resolved version; the latter is an optional pin, never a default.

    The ``github`` values are a **second home** for
    ``prompts/scripts/review-followup/constants.py``'s literals, by design: the wheel ships
    only the ``aidw`` package, so this module must not import the bundled scripts (and the
    scripts are copied into other repositories without ``aidw``).
    ``tests/test_target_config.py`` pins the two homes byte-identical; the authoritative
    ``baseline-verbatim`` golden is E6.3's. Only ``markers`` and ``labels`` are seeded — the
    comment bodies and the role label names stay in ``constants.py``, because §3.4 has no
    field for them and D5 freezes the names.
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
    # EXTRACTION.md §3.4/§3.9's ``github:`` block, character-for-character (D5: no
    # currently-persisted GitHub string changes). The three markers are **templates**
    # rendered with keyed ``str.format`` by the review-followup scripts' accessors; the six
    # labels are exactly ``constants.py:LABEL_DEFINITIONS``. A repo declaring either wins
    # per leaf — :func:`resolve_config` already merges them.
    github: GitHubConfig = field(
        default_factory=lambda: GitHubConfig(
            markers=MarkersConfig(
                parent="<!-- mythical-forge-review-followups: pr={pr_url} -->",
                child=(
                    "<!-- mythical-forge-review-follow-up: pr={pr_url} "
                    "finding={finding_id} -->"
                ),
                summary="<!-- mythical-forge-review-followups-summary: pr={pr_url} -->",
            ),
            labels={
                "review-follow-up": LabelConfig(
                    color="5319E7",
                    description="Review-generated task or parent issue",
                ),
                "must-fix": LabelConfig(
                    color="B60205", description="Blocking review finding"
                ),
                "should-fix": LabelConfig(
                    color="D93F0B",
                    description="Non-blocking but recommended finding",
                ),
                "could-fix": LabelConfig(
                    color="FBCA04",
                    description="Limited review improvement or simplification",
                ),
                "decision-pending": LabelConfig(
                    color="EDEDED",
                    description="Human decision required before implementation",
                ),
                "approve-fix": LabelConfig(
                    color="B8D64A",
                    description="Human-approved review follow-up fix",
                ),
            },
        )
    )
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
    # file's declared labels, plus the toolkit's seeded default labels (E6.1).
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


#: Prefix on :func:`config_identity`'s hash, so the algorithm is self-describing in
#: ``state.json`` (EXTRACTION.md §3.11 leaves the algorithm open; E8.2 fixes it).
CONFIG_HASH_PREFIX = "sha256:"


def config_identity(resolved: ResolvedConfig) -> tuple[int | None, str]:
    """The resolved config's identity for ``state.json`` (E8.2, EXTRACTION.md §3.11).

    Returns ``(config_schema_version, config_hash)`` together so the five workflows that
    write a run record cannot record one without the other, or compute either differently:

    - ``config_schema_version`` is the **config** schema version and nothing else. The
      bare ``schema_version`` key in ``state.json`` is the *state* schema
      (:data:`aidw.state.SCHEMA_VERSION`), which ``aidw.state.load`` refuses when it
      differs, so reusing that key for §3.11's "resolved ``schema_version``" would break
      every load. It is ``None`` for a config-less repo: ``schema_version`` is required
      *in* a config file and deliberately has no toolkit default (§3.4), so a repo with
      no ``aidw/`` folder has no resolved version to record.
    - ``config_hash`` is ``sha256:<hex>`` over
      ``json.dumps(resolved.to_dict(), sort_keys=True)`` — the same object
      ``aidw config show --json`` prints, so an operator can reproduce the fingerprint
      from a visible command. Hashing the **resolved** mapping (not the raw
      ``config.yaml`` text, whose hash would move on a comment edit, and not the declared
      :class:`TargetConfig`) is what makes it mean "the config this run actually used":
      each leaf carries its ``source``, so a declared ``max_revisions: 3`` fingerprints
      differently from the default ``3`` — provenance is part of the identity.

    Pure: no I/O, and ``resolved`` (its entries and their containers) is never mutated.
    """
    entry = resolved.get("schema_version")
    schema_version: int | None = (
        entry.value if entry is not None and entry.is_set else None
    )
    payload = json.dumps(resolved.to_dict(), sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return schema_version, f"{CONFIG_HASH_PREFIX}{digest}"


def resolve_workflow_config(
    target_root: Path,
    *,
    toolkit_version: str,
    overrides: ConfigOverrides | None = None,
) -> tuple[ResolvedConfig | None, list[Issue]]:
    """Load, fail-closed and resolve a workflow's target config (E4.3, D10/§3.11).

    Exactly the two refusals ``aidw prompt``'s ``run()`` preflight performs, shared so the
    other workflows cannot drift from it: a config carrying validation ``ERROR`` issues,
    and a :func:`check_compatibility` refusal (a ``schema_version`` newer than this toolkit
    understands, or an unsatisfied ``requires_toolkit``). Both are usage/config errors
    (exit 2, design §14) and both must happen before any run record or worktree, in every
    mode including ``--dry-run``.

    Returns ``(resolved, [])`` when the config is usable, or ``(None, issues)`` when the
    caller must print :func:`aidw.config.format_issues` on stderr and stop with exit 2.
    The third preflight of ``aidw prompt`` — :func:`validate_paths` — is deliberately
    **not** part of this helper: its read-paths need not exist in a review/fix/approve
    tree, and a missing path surfaces fail-closed at the stage that first reads it.

    Pure apart from reading the config file; ``load_target_config`` treats a missing
    ``aidw/config.yaml`` as an empty config, so a repo with no ``aidw/`` folder resolves
    the toolkit defaults.
    """
    declared = load_target_config(target_root / "aidw" / "config.yaml")
    config_errors = [issue for issue in declared.issues if issue.level == ERROR]
    if config_errors:
        return None, config_errors
    compatibility_issues = check_compatibility(declared, toolkit_version=toolkit_version)
    if compatibility_issues:
        return None, list(compatibility_issues)
    return resolve_config(declared, overrides=overrides), []


# --------------------------------------------------------------------------- #
# Path classification and existence validation (E3.7, EXTRACTION.md §3.4)
# --------------------------------------------------------------------------- #

#: §3.4 read-paths: values the toolkit *reads*, so a missing one is always an error.
#: §3.4 lists three of these; E3.7's roadmap entry adds ``implementation_results_dir``,
#: and E4.6 adds ``agent_configs_dir`` — a directory of agent configs the workflow reads
#: whenever a repo names it (it has no default, so an unset leaf is skipped, not stat'd).
#: Deliberately not merged with §3.4's *other* use of "write-target" (the gate-scope
#: declaration: R18's ``implementation_results_dir``/``architecture_dir``/``roadmap_dir``/
#: ``task_prompts_dir``), which asks a different question — what a gate cannot read —
#: about a partly overlapping set. G1.3's ``specs_dir`` is deliberately **not** here: it
#: is optional and legitimately absent, so its absence is an advisory ``aidw doctor`` WARN
#: (``_check_specs_dir``), never a read-path FAIL.
READ_PATHS = (
    "build_results_template",
    "roadmap_dir",
    "task_prompts_dir",
    "implementation_results_dir",
    "agent_configs_dir",
)

#: §3.4 write-targets, as ``field -> id of the stage that writes there``. A write-target
#: may legitimately be absent: the stage creates it on demand, and only an *enabled*
#: stage is obliged to. ``architecture_dir`` is the only one today; a repo-added stage's
#: directory is E4.5/E4.6's to add here. ``roadmap_glob`` is a pattern, not a path, and is
#: deliberately in neither this mapping nor :data:`READ_PATHS`.
WRITE_TARGETS = {"architecture_dir": "architecture"}

#: The issue ``source`` for a path-existence problem. A resolved leaf can come from a
#: default (D17) rather than the file, so the source is the config's canonical name — the
#: per-value provenance is named in the message instead (``source: default``), which is
#: exactly what a repo without Mythical Forge's layout needs to read.
PATH_ISSUE_SOURCE = CONFIG_FILENAME


def _resolved_path(
    resolved: ResolvedConfig, field: str
) -> ResolvedValue | None:
    """The resolved ``paths.<field>`` leaf, or ``None`` when it did not resolve.

    Defensive on purpose: an unset leaf (or one a hand-built :class:`ResolvedConfig` does
    not carry at all) is skipped rather than stat'd, so a caller can never validate a
    path the config did not name. ``ResolvedConfig`` is a ``Mapping``, so ``get`` is the
    tolerant lookup.
    """
    entry = resolved.get(f"paths.{field}")
    if entry is None or not entry.is_set or entry.value is None:
        return None
    return entry


def _target_path(target_root: Path, value: str) -> Path:
    """``target_root / value``, where an absolute ``value`` wins (``pathlib`` semantics).

    Both a repo-relative ``docs/tasks`` and an absolute override resolve without a
    special case, which is why the §3.4 defaults and an operator's absolute path take the
    same code path.
    """
    return Path(target_root) / value


def agent_configs_override(
    resolved: ResolvedConfig, target_root: Path
) -> Path | None:
    """The resolved ``paths.agent_configs_dir`` as a filesystem path, or ``None`` (E4.6).

    One place for the "relative to the target root, absolute wins" rule
    (:func:`_target_path`), shared by every workflow's ``load_all`` call site: a global
    override is *target-repo configuration*, so it resolves against the tree the stages run
    in — the located worktree once one exists — exactly like the other §3.4 read-paths.
    Unset (the toolkit default, which is deliberately absent) returns ``None``: the caller
    then loads only ``<toolkit>/agent-configs/``. Pure: no ``exists()`` and no I/O; whether
    the named directory is present is :func:`validate_paths`' and ``load_all``'s question.
    """
    entry = _resolved_path(resolved, "agent_configs_dir")
    if entry is None:
        return None
    return _target_path(target_root, str(entry.value))


def validate_paths(resolved: ResolvedConfig, target_root: Path) -> list[Issue]:
    """Report every resolved read-path that does not exist under ``target_root`` (§3.4).

    The rule is fail-closed and has no fallback (§3.4 "Configured read-paths must exist",
    D17/R7): a value named by the config **or by the toolkit default** must exist, so a
    repo without Mythical Forge's layout fails legibly here instead of having an agent
    improvise around a missing template (E7.2's "stop and report"). Every issue names
    both the field (``paths.<field>``) and the resolved path, plus the value's provenance,
    so the report says *what* to create and whether the config or the default named it.

    Pure: one ``exists()`` per set read-path, no writes and no mutation of ``resolved``.
    """
    issues: list[Issue] = []
    for field in READ_PATHS:
        entry = _resolved_path(resolved, field)
        if entry is None:
            continue
        path = _target_path(target_root, str(entry.value))
        if path.exists():
            continue
        issues.append(
            Issue(
                ERROR,
                PATH_ISSUE_SOURCE,
                f"`paths.{field}` {path} does not exist "
                f"(read-path, source: {entry.source})",
            )
        )
    return issues


def _write_target_enabled(declared: TargetConfig, stage_id: str) -> bool:
    """Whether the stage that writes a write-target is enabled (E3.7, prompt-fixed).

    Disabled **iff** the declared config's ``workflows.*.stages`` carries a stage with
    this ``id`` and ``enabled is False``; otherwise enabled. The default is read from the
    declared side and not from the resolved one because §3.4's stage lists are
    whole-list overrides: a config that declares no stage at all has no entry to consult,
    and the resolution would report the absent list as unset rather than as "enabled".
    Enabled-by-default is what keeps the six-stage implement chain E4.1 preserves working
    for a config that never mentions architecture.
    """
    for workflow in declared.workflows.values():
        for stage in workflow.stages:
            if stage.id == stage_id and stage.enabled is False:
                return False
    return True


def ensure_write_targets(
    declared: TargetConfig, resolved: ResolvedConfig, target_root: Path
) -> list[Issue]:
    """Create each enabled stage's write-target, reporting a failure per field (E3.7).

    A write-target is an *output*: §3.4 lets it be absent, so this creates it
    (``mkdir(parents=True, exist_ok=True)``) instead of failing. Two rules bound that:

    - a **disabled** stage's write-target is skipped entirely — no directory, no issue,
      because nothing will write there (§3.4: "required only when a stage that writes
      there is enabled"). Enablement comes from ``declared`` (see
      :func:`_write_target_enabled`); the *path* comes from ``resolved``, since a
      config that never declares ``architecture_dir`` still gets the D17 default.
    - a creation failure is an ``ERROR`` naming the stage, never a silent skip: the stage
      cannot run without its output directory, and inventing a fallback location is the
      agent-side improvisation §3.4 forbids.

    Only ``OSError`` is caught (a parent that is a file, a permission denial, a read-only
    volume): those are the environmental failures a caller can report. Anything else is a
    bug here and must surface as a traceback rather than as a plausible-looking issue.

    Deliberately *not* called by ``aidw doctor``: doctor is read-only (§3.1). Its call
    site belongs to the workflow whose stage writes there (E4.3 for implement).
    """
    issues: list[Issue] = []
    for field, stage_id in WRITE_TARGETS.items():
        if not _write_target_enabled(declared, stage_id):
            continue
        entry = _resolved_path(resolved, field)
        if entry is None:
            continue
        path = _target_path(target_root, str(entry.value))
        if path.is_dir():
            continue
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            issues.append(
                Issue(
                    ERROR,
                    PATH_ISSUE_SOURCE,
                    f"`paths.{field}` {path} cannot be created for stage "
                    f"`{stage_id}`: {exc}",
                )
            )
    return issues
