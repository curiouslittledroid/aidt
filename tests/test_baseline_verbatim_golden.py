"""The D5 freeze golden: resolved GitHub contracts vs the ``baseline-verbatim`` tag (E6.3).

``docs/migration/EXTRACTION.md`` §5.4 requires a "no-regression" check: *with a
Mythical-Forge-shaped config, the toolkit's resolved … marker strings and label
definitions must be byte-identical to the ``baseline-verbatim`` tag.* That is what
protects D5 ("marker and label literals are frozen. No currently-persisted string in
GitHub changes") across E6.1's move of those literals into config with frozen defaults.

The frozen surfaces, all of §3.9:

- the three marker **templates** and their rendered output (``github.markers.*``);
- all six label names with their exact colour and description (``github.labels.*``);
- the three exact-match comment bodies and the five role-name constants
  (``prompts/scripts/review-followup/constants.py`` — §3.4 has no config field for them).

**The oracle is the tag, never the working tree.** :func:`_baseline_constants_source`
runs ``git show baseline-verbatim:prompts/scripts/review-followup/constants.py`` from the
toolkit root and :func:`_load_baseline_constants` execs those *bytes* into a fresh module
namespace. The current ``constants.py`` (loaded by path, under a different module name) is
the thing under test. The two files' **text** is deliberately never compared: E6.1
legitimately rewrote the current file (module-level marker templates, updated docstrings),
so only the values are frozen.

Because the baseline predates E6.1's module-level templates, it exposes each marker only
as an f-string *function*. The template is recovered by self-substitution —
``baseline.parent_marker("{pr_url}")`` is exactly the literal — and compared with the
resolved template byte-for-byte. Pinning the template, not just one rendering, is what
catches a pre-rendered literal that happens to match the probe and breaks every real PR.

**A missing tag is an error, never a skip** (req 6): a silently skipped golden disables the
D5 guard exactly where it matters. ``.github/workflows/ci.yml`` therefore fetches full
history (``fetch-depth: 0``) so the root-commit tag exists when CI runs the suite.

This is a repo-root test on purpose (§3.12): it needs ``aidw.target_config`` and
``git show``, neither of which the stdlib-only, copy-into-another-repo
``prompts/scripts/review-followup/tests/`` tree may use.
"""

from __future__ import annotations

import copy
import importlib.util
import subprocess
import types
from typing import Any, Mapping

import pytest

from aidw.paths import toolkit_root
from aidw.target_config import (
    MARKER_FIELDS,
    SOURCE_DEFAULT,
    TOOLKIT_DEFAULTS,
    ResolvedConfig,
    TargetConfig,
    resolve_config,
)

#: The frozen oracle (§5.2: the verbatim copy of ``aidt/`` is tagged with this name).
BASELINE_TAG = "baseline-verbatim"

#: The one file §3.9 freezes — the same path in the tag and in the working tree.
BASELINE_CONSTANTS_PATH = "prompts/scripts/review-followup/constants.py"

#: Module names for the two by-path loads. Both must differ from each other *and* from
#: ``tests/test_target_config.py``'s ``review_followup_constants_for_two_home_test``:
#: a collision would silently alias one module over the other and compare a thing to
#: itself (the trap E6.3's prompt names).
BASELINE_MODULE_NAME = "baseline_verbatim_constants_for_freeze_golden_test"
CURRENT_MODULE_NAME = "current_review_followup_constants_for_freeze_golden_test"

#: The fixed probe for the rendered-marker half of req 2. Any fixed URL/finding id works
#: because byte-identity is probe-independent for a correct template; the real PR in
#: §7 MF.5 is irrelevant to the assertion. The *alternate* probe exists so a hardcoded
#: literal cannot pass by matching one probe.
PROBE_PR_URL = "https://github.com/mythical-forge/mythical-forge/pull/237"
PROBE_FINDING_ID = "F1"
ALTERNATE_PR_URL = "https://github.com/other-owner/other-repo/pull/9"
ALTERNATE_FINDING_ID = "F7"

#: The three marker names, enumerated literally rather than read from the code under test:
#: an added or renamed marker must fail this golden instead of quietly escaping coverage.
FROZEN_MARKER_NAMES = ("parent", "child", "summary")

#: The keyword arguments each marker accessor takes, in signature order.
MARKER_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "parent": ("pr_url",),
    "child": ("pr_url", "finding_id"),
    "summary": ("pr_url",),
}

#: What the baseline's f-string functions receive to reveal their template literal.
TEMPLATE_PLACEHOLDERS: dict[str, dict[str, str]] = {
    "parent": {"pr_url": "{pr_url}"},
    "child": {"pr_url": "{pr_url}", "finding_id": "{finding_id}"},
    "summary": {"pr_url": "{pr_url}"},
}

PROBE_VALUES: dict[str, dict[str, str]] = {
    "parent": {"pr_url": PROBE_PR_URL},
    "child": {"pr_url": PROBE_PR_URL, "finding_id": PROBE_FINDING_ID},
    "summary": {"pr_url": PROBE_PR_URL},
}

ALTERNATE_PROBE_VALUES: dict[str, dict[str, str]] = {
    "parent": {"pr_url": ALTERNATE_PR_URL},
    "child": {"pr_url": ALTERNATE_PR_URL, "finding_id": ALTERNATE_FINDING_ID},
    "summary": {"pr_url": ALTERNATE_PR_URL},
}

#: All six label names §3.9 freezes, enumerated so the whole map is compared (req 3).
FROZEN_LABEL_NAMES = (
    "review-follow-up",
    "must-fix",
    "should-fix",
    "could-fix",
    "decision-pending",
    "approve-fix",
)

#: The two fields of every ``github.labels.<name>`` entry.
LABEL_FIELDS = ("color", "description")

#: §3.9's exact-match comment bodies — ``logic.py`` compares them with ``==``, so no
#: whitespace or case normalisation is allowed anywhere in this path.
FROZEN_COMMENT_BODIES = ("STATUS_IN_PROGRESS", "STATUS_FIXED", "DECISION_APPROVE_FIX")

#: The role-name/tuple constants that have no config field (§3.4) and stay script-side.
FROZEN_ROLE_NAMES = (
    "LABEL_REVIEW_FOLLOW_UP",
    "LABEL_APPROVE_FIX",
    "LABEL_DECISION_PENDING",
    "PRIORITY_LABELS",
    "PUBLISHER_LABELS",
)


class BaselineTagError(RuntimeError):
    """The frozen baseline could not be read from git — an error, never a skip (req 6)."""


# --------------------------------------------------------------------------- #
# The oracle: the tag, loaded into a fresh module namespace
# --------------------------------------------------------------------------- #


def _baseline_constants_source(
    *,
    tag: str = BASELINE_TAG,
    path: str = BASELINE_CONSTANTS_PATH,
) -> bytes:
    """Return the frozen ``constants.py`` **bytes** from ``tag`` (§5.4's oracle).

    ``git show`` runs from :func:`aidw.paths.toolkit_root` — the repo root of a source
    checkout, and the same base ``tests/test_target_config.py`` locates the working-tree
    file from. Output is captured as bytes (no text mode, so no newline translation): the
    exec below therefore sees exactly the object git stored, which is what "byte-identical"
    means here.

    A non-zero exit — missing tag (the CI shallow-clone failure this task's
    ``fetch-depth: 0`` change fixes), a path absent at that tag — raises
    :class:`BaselineTagError` with git's own stderr. No ``pytest.skip``/``xfail`` anywhere
    in this module: the guard must stay armed.
    """
    completed = subprocess.run(
        ["git", "show", f"{tag}:{path}"],
        cwd=toolkit_root(),
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise BaselineTagError(
            f"cannot read {tag}:{path} from {toolkit_root()} "
            f"(git exited {completed.returncode}): "
            f"{completed.stderr.decode('utf-8', 'replace').strip()} — the D5 freeze "
            "oracle is missing; a shallow/tagless clone needs `fetch-depth: 0` "
            "(.github/workflows/ci.yml) rather than a skipped golden."
        )
    return completed.stdout


def _load_baseline_constants(
    *,
    tag: str = BASELINE_TAG,
    path: str = BASELINE_CONSTANTS_PATH,
) -> types.ModuleType:
    """Exec the tag's ``constants.py`` bytes into a **fresh** module namespace.

    A plain :class:`types.ModuleType` rather than
    ``importlib.util.spec_from_file_location`` (the shape
    ``tests/test_target_config.py:_frozen_script_constants`` uses for the *working-tree*
    file): the baseline is a git object, not a file on disk, so there is no path to hand a
    file loader. The distinct module name is what keeps it from colliding with the current
    ``constants`` module — otherwise the golden would compare the working tree to itself.

    Uncached deliberately: two calls yield independent namespaces, so one test cannot leak
    a mutation into another (``test_the_baseline_module_never_aliases_the_current_constants``
    pins that, and the tag read costs ~5 ms per call).
    """
    source = _baseline_constants_source(tag=tag, path=path)
    module = types.ModuleType(BASELINE_MODULE_NAME)
    module.__file__ = f"{tag}:{path}"
    # ``compile`` accepts bytes and honours the source encoding, so the exec consumes the
    # frozen bytes without a decode/re-encode round trip.
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def _load_current_constants() -> types.ModuleType:
    """Load the **working tree's** ``constants.py`` — the thing under test.

    By path, under :data:`CURRENT_MODULE_NAME`: the repo-root suite does not put
    ``prompts/scripts/review-followup`` on ``sys.path`` (only that tree's own
    ``conftest.py`` does), so a bare ``import constants`` is not available here. The name
    differs from both the baseline's and the two-home test's so neither import can alias
    the other.
    """
    spec = importlib.util.spec_from_file_location(
        CURRENT_MODULE_NAME, toolkit_root() / BASELINE_CONSTANTS_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _mythical_forge_shaped_config_for(declared: TargetConfig) -> ResolvedConfig:
    """Resolve a caller-supplied declared config through the real resolver."""
    return resolve_config(declared)


def _mythical_forge_shaped_config() -> ResolvedConfig:
    """The "Mythical-Forge-shaped config" of §5.4: ``schema_version: 1`` and nothing else.

    D17 makes the toolkit defaults Mythical Forge's values, so this config-less-declaration
    path is the one a Mythical-Forge-shaped repo resolves through. Req 5 also pins
    :data:`TOOLKIT_DEFAULTS.github` directly in
    :func:`test_toolkit_defaults_github_equals_the_baseline_directly`, so the fallback is
    covered without depending on resolution.
    """
    return _mythical_forge_shaped_config_for(TargetConfig(schema_version=1))


def _marker_arguments(name: str, values: Mapping[str, str]) -> tuple[str, ...]:
    """The accessor's positional arguments for one marker, in signature order."""
    return tuple(values[argument] for argument in MARKER_ARGUMENTS[name])


def _baseline_marker_template(baseline: types.ModuleType, name: str) -> str:
    """Recover one baseline marker template by self-substitution (req 2).

    ``baseline.parent_marker("{pr_url}")`` returns exactly the f-string literal, because
    the f-string's only substitution is ``pr_url`` itself. That is the only way to reach
    the template: the baseline predates E6.1's module-level ``*_MARKER_TEMPLATE``
    constants, so there is no attribute to read.
    """
    accessor = getattr(baseline, f"{name}_marker")
    return accessor(*_marker_arguments(name, TEMPLATE_PLACEHOLDERS[name]))


def _read_only_snapshot(module: types.ModuleType) -> dict[str, Any]:
    """A deep copy of a loaded constants module's *frozen* namespace entries.

    Only the all-caps constants (``LABEL_DEFINITIONS``, ``STATUS_*``, ``PRIORITY_LABELS``,
    ``*_MARKER_TEMPLATE`` …) are frozen values; the rest are helpers and ``__future__``
    machinery (``annotations``), which deep-copy does not round-trip. Comparing two
    snapshots proves the golden *read* both oracles without mutating them.
    """
    return copy.deepcopy(
        {
            name: value
            for name, value in vars(module).items()
            if name.isupper()
        }
    )


# --------------------------------------------------------------------------- #
# Requirement 2 — markers, rendered *and* as templates
# --------------------------------------------------------------------------- #


def test_the_three_frozen_markers_are_byte_identical_rendered_and_as_templates() -> None:
    """Resolved ``github.markers.*`` templates and their renderings equal the tag (req 2).

    Four assertions per marker, so no single-character change survives:

    1. the resolved template equals the recovered baseline literal;
    2. rendering it with a fixed probe equals the baseline function's output;
    3. rendering it with a *different* probe also equals the baseline (the template holds
       ``{pr_url}``/``{finding_id}``; a pre-rendered literal would pass (2) and fail (3));
    4. the working-tree script fallback (``*_MARKER_TEMPLATE`` and its accessor) is the
       same value — the fallback is what a config-less script run emits.
    """
    baseline = _load_baseline_constants()
    current = _load_current_constants()
    resolved = _mythical_forge_shaped_config()

    assert set(FROZEN_MARKER_NAMES) == set(MARKER_FIELDS)
    resolved_marker_paths = {
        path for path in resolved if path.startswith("github.markers.")
    }
    assert resolved_marker_paths == {
        f"github.markers.{name}" for name in FROZEN_MARKER_NAMES
    }

    for name in FROZEN_MARKER_NAMES:
        expected_template = _baseline_marker_template(baseline, name)
        baseline_accessor = getattr(baseline, f"{name}_marker")
        current_accessor = getattr(current, f"{name}_marker")

        leaf = resolved[f"github.markers.{name}"]
        assert leaf.source == SOURCE_DEFAULT, name
        template = leaf.value
        assert isinstance(template, str), name

        # 1. Template, byte-for-byte.
        assert template == expected_template, name

        # 2. Fixed probe, rendered the way the scripts do (keyed ``str.format``).
        assert template.format(**PROBE_VALUES[name]) == baseline_accessor(
            *_marker_arguments(name, PROBE_VALUES[name])
        ), name

        # 3. Alternate probe: the placeholders are still placeholders.
        assert template.format(**ALTERNATE_PROBE_VALUES[name]) == baseline_accessor(
            *_marker_arguments(name, ALTERNATE_PROBE_VALUES[name])
        ), name
        for argument in MARKER_ARGUMENTS[name]:
            assert f"{{{argument}}}" in template, (name, argument)

        # 4. The working-tree fallback is the same literal and renders the same string.
        assert getattr(current, f"{name.upper()}_MARKER_TEMPLATE") == expected_template
        assert current_accessor(
            *_marker_arguments(name, PROBE_VALUES[name])
        ) == baseline_accessor(*_marker_arguments(name, PROBE_VALUES[name])), name


# --------------------------------------------------------------------------- #
# Requirement 3 — all six labels, whole map
# --------------------------------------------------------------------------- #


def test_all_six_frozen_labels_are_byte_identical_in_name_colour_and_description() -> None:
    """Resolved ``github.labels`` == the tag's ``LABEL_DEFINITIONS``, whole map (req 3).

    No spot-check: the name sets are asserted equal on the baseline, the defaults, the
    resolved leaves and the working-tree module, so a label added on one side or dropped
    from the other fails before any value is compared. Then every colour and description
    is compared byte-for-byte, and the whole entry dict is compared too (an extra field on
    either side is a change).
    """
    baseline = _load_baseline_constants()
    current = _load_current_constants()
    resolved = _mythical_forge_shaped_config()

    expected_names = set(FROZEN_LABEL_NAMES)
    assert set(baseline.LABEL_DEFINITIONS) == expected_names
    assert set(TOOLKIT_DEFAULTS.github.labels) == expected_names
    assert set(current.LABEL_DEFINITIONS) == expected_names
    resolved_label_names = {
        path.split(".")[2]
        for path in resolved
        if path.startswith("github.labels.")
    }
    assert resolved_label_names == expected_names

    for name in FROZEN_LABEL_NAMES:
        expected = baseline.LABEL_DEFINITIONS[name]
        assert current.LABEL_DEFINITIONS[name] == expected, name
        assert TOOLKIT_DEFAULTS.github.labels[name].to_dict() == expected, name
        for field in LABEL_FIELDS:
            leaf = resolved[f"github.labels.{name}.{field}"]
            assert leaf.source == SOURCE_DEFAULT, (name, field)
            assert leaf.value == expected[field], (name, field)


# --------------------------------------------------------------------------- #
# Requirement 4 — script-side comment bodies and role names
# --------------------------------------------------------------------------- #


def test_frozen_comment_bodies_and_role_names_are_byte_identical() -> None:
    """The config-less script surfaces are unchanged from the tag (req 4).

    ``STATUS_*``/``DECISION_APPROVE_FIX`` have no config field (§3.4) and are compared with
    ``==`` in ``logic.py``, so they are frozen as *values*: no trailing punctuation, no
    case or whitespace change. ``PRIORITY_LABELS``/``PUBLISHER_LABELS`` are tuples, and
    tuple equality also pins element order (``approve-fix`` stays out of the publisher set).
    """
    baseline = _load_baseline_constants()
    current = _load_current_constants()

    for name in FROZEN_COMMENT_BODIES:
        expected = getattr(baseline, name)
        assert isinstance(expected, str), name
        assert getattr(current, name) == expected, name

    for name in FROZEN_ROLE_NAMES:
        expected = getattr(baseline, name)
        assert getattr(current, name) == expected, name

    # The tuples are tuples, in the frozen order — not mere iterables that compare equal.
    assert isinstance(current.PRIORITY_LABELS, tuple)
    assert isinstance(current.PUBLISHER_LABELS, tuple)


# --------------------------------------------------------------------------- #
# Requirement 5 — pin the config-less fallback without depending on resolution
# --------------------------------------------------------------------------- #


def test_toolkit_defaults_github_equals_the_baseline_directly() -> None:
    """``TOOLKIT_DEFAULTS.github`` equals the tag, unmediated by ``resolve_config`` (req 5).

    The resolved path above could in principle be repaired by a later copy; this pins the
    seed itself, which is what a config-less repo (`aidw`'s own handoff default) uses.
    """
    baseline = _load_baseline_constants()

    for name in FROZEN_MARKER_NAMES:
        assert getattr(TOOLKIT_DEFAULTS.github.markers, name) == (
            _baseline_marker_template(baseline, name)
        ), name

    for name in FROZEN_LABEL_NAMES:
        default_label = TOOLKIT_DEFAULTS.github.labels[name]
        expected = baseline.LABEL_DEFINITIONS[name]
        assert default_label.color == expected["color"], name
        assert default_label.description == expected["description"], name


# --------------------------------------------------------------------------- #
# Requirement 6 — fail loudly, never skip
# --------------------------------------------------------------------------- #


def test_an_absent_baseline_tag_raises_instead_of_skipping() -> None:
    """A missing tag is a ``BaselineTagError`` — not a skip, not an xfail (req 6).

    The error path *is* the assertion: this is the exact failure a shallow tagless clone
    produced before ``.github/workflows/ci.yml`` gained ``fetch-depth: 0``, and a skip here
    would have hidden it. Real ``git``, a tag that cannot exist, no monkeypatching.
    """
    missing_tag = "baseline-verbatim-definitely-absent"

    with pytest.raises(BaselineTagError, match=missing_tag):
        _baseline_constants_source(tag=missing_tag)
    with pytest.raises(BaselineTagError, match=missing_tag):
        _load_baseline_constants(tag=missing_tag)


# --------------------------------------------------------------------------- #
# Trap guard — the oracle must not alias the thing under test
# --------------------------------------------------------------------------- #


def test_the_baseline_module_never_aliases_the_current_constants() -> None:
    """Two loads of the tag are independent namespaces, and never the working tree.

    The module-name trap is silent when it happens: ``importlib``/``sys.modules`` would
    hand back the current ``constants`` module and every assertion would pass against
    itself. Distinct names plus this identity check make that impossible to ship.
    """
    first = _load_baseline_constants()
    second = _load_baseline_constants()
    current = _load_current_constants()

    assert first is not second
    assert first is not current
    assert first.__name__ == BASELINE_MODULE_NAME
    assert current.__name__ == CURRENT_MODULE_NAME
    assert BASELINE_MODULE_NAME != CURRENT_MODULE_NAME
    # Provenance: the namespace came from the git object, not the working-tree path.
    assert first.__file__ == f"{BASELINE_TAG}:{BASELINE_CONSTANTS_PATH}"


# --------------------------------------------------------------------------- #
# Purity
# --------------------------------------------------------------------------- #


def test_the_mythical_forge_shaped_config_resolves_purely() -> None:
    """Resolving the same config twice is equal and mutates neither input nor defaults.

    ``resolve_config`` promises no input mutation and fresh containers; the freeze golden
    depends on that because it resolves on every run. No I/O is possible here beyond the
    tag read the helpers deliberately keep out of this path.
    """
    declared = TargetConfig(schema_version=1)
    declared_before = copy.deepcopy(declared)
    defaults_before = copy.deepcopy(TOOLKIT_DEFAULTS)

    first = _mythical_forge_shaped_config_for(declared)
    second = _mythical_forge_shaped_config_for(declared)

    assert declared == declared_before
    assert declared.to_dict() == declared_before.to_dict()
    # Resolution must not inject the github block into the declared config.
    assert declared.github is None
    assert declared.workflows == {}
    assert TOOLKIT_DEFAULTS == defaults_before

    assert first.to_dict() == second.to_dict()
    assert first.entries is not second.entries
    for name in FROZEN_MARKER_NAMES:
        assert (
            first[f"github.markers.{name}"].value
            == second[f"github.markers.{name}"].value
        )
    for name in FROZEN_LABEL_NAMES:
        for field in LABEL_FIELDS:
            path = f"github.labels.{name}.{field}"
            assert first[path].value == second[path].value
            assert first[path].source == SOURCE_DEFAULT


def test_the_golden_reads_both_oracles_without_mutating_them() -> None:
    """Every frozen surface can be read without changing either module's namespace.

    The golden compares live module attributes; this proves those reads are side-effect
    free (a helper that sorted/mutated ``LABEL_DEFINITIONS`` would corrupt later
    assertions and the traceability evidence).
    """
    baseline = _load_baseline_constants()
    current = _load_current_constants()
    baseline_before = _read_only_snapshot(baseline)
    current_before = _read_only_snapshot(current)

    resolved = _mythical_forge_shaped_config()
    for name in FROZEN_MARKER_NAMES:
        _baseline_marker_template(baseline, name)
        getattr(baseline, f"{name}_marker")(*_marker_arguments(name, PROBE_VALUES[name]))
        getattr(current, f"{name}_marker")(*_marker_arguments(name, PROBE_VALUES[name]))
        assert resolved[f"github.markers.{name}"].value.format(
            **PROBE_VALUES[name]
        ) == getattr(current, f"{name}_marker")(
            *_marker_arguments(name, PROBE_VALUES[name])
        )
    for name in FROZEN_LABEL_NAMES:
        for field in LABEL_FIELDS:
            assert (
                resolved[f"github.labels.{name}.{field}"].value
                == baseline.LABEL_DEFINITIONS[name][field]
            )
    for name in FROZEN_COMMENT_BODIES + FROZEN_ROLE_NAMES:
        assert getattr(current, name) == getattr(baseline, name)

    assert _read_only_snapshot(baseline) == baseline_before
    assert _read_only_snapshot(current) == current_before
