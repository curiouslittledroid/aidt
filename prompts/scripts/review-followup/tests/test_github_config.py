"""The ``AIDW_REVIEW_FOLLOWUP_CONFIG`` handoff: ``gh.py``'s effective markers and labels.

Run with: uv run pytest prompts/scripts/review-followup/tests

Named ``test_github_config.py`` rather than ``test_config.py`` because pytest's default
``prepend`` import mode derives a module name from the bare basename, and the toolkit's own
``tests/test_config.py`` (the *agent*-config loader, an unrelated module) would collide
with it under one session.

E6.1 moved the marker templates and label definitions out of the scripts and into the target
repo's resolved config (EXTRACTION.md §3.4/§3.9, D5), with the values in
:mod:`constants` as the standalone fallback. :mod:`gh` is the seam:

- **absent → fallback**: with no handoff, its effective accessors are byte-identical to
  ``constants``' frozen functions and mapping;
- **present → configured**: a handoff's template, colour and description are what the
  accessors return, and its extra labels are carried too (the map is open);
- **present-but-broken → fail closed**: invalid JSON, a missing marker/label field, or a
  well-formed payload whose template cannot render under the accessor's keyed
  ``str.format`` stops the script with a clear ``error:`` and exit code 2, raised at
  ``gh``'s resolution step — before any marker renders, so nothing is ever published.

The last group is a safety property, not cosmetics: publishing a wrong marker orphans
every existing parent/child and makes the next publish create duplicates (D5).
"""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import constants
import gh

SCRIPT_DIR = Path(__file__).resolve().parents[1]


def _handoff(markers: dict | None = None, labels: dict | None = None) -> str:
    """A well-formed payload: the frozen values by default, overridable per field."""
    return json.dumps(
        {
            "markers": markers
            if markers is not None
            else {
                "parent": constants.PARENT_MARKER_TEMPLATE,
                "child": constants.CHILD_MARKER_TEMPLATE,
                "summary": constants.SUMMARY_MARKER_TEMPLATE,
            },
            "labels": labels
            if labels is not None
            else {
                name: dict(definition)
                for name, definition in constants.LABEL_DEFINITIONS.items()
            },
        }
    )


def _all_labels(color: str = "111111", description: str = "configured") -> dict:
    return {
        name: {"color": color, "description": description}
        for name in constants.LABEL_DEFINITIONS
    }


@contextlib.contextmanager
def effective_module(value: str | None):
    """Reload :mod:`gh` with ``AIDW_REVIEW_FOLLOWUP_CONFIG`` set (or unset), then restore.

    ``gh`` resolves once at import, so this is the closest in-process equivalent of what a
    fresh script invocation does — and the ``finally`` block puts the module back on the
    frozen fallback, so one test's configured handoff cannot leak into another.
    """
    saved = os.environ.pop(gh.CONFIG_ENV_VAR, None)
    try:
        if value is not None:
            os.environ[gh.CONFIG_ENV_VAR] = value
        yield importlib.reload(gh)
    finally:
        os.environ.pop(gh.CONFIG_ENV_VAR, None)
        if saved is not None:
            os.environ[gh.CONFIG_ENV_VAR] = saved
        importlib.reload(gh)


# ---------------------------------------------------------------------------
# Absent → the frozen fallback (the standalone case)
# ---------------------------------------------------------------------------


def test_no_handoff_falls_back_to_the_frozen_constants() -> None:
    """The overlay's *default path*, not the untouched constants: assert through ``gh``."""
    with effective_module(None) as module:
        assert module.parent_marker("https://github.com/o/r/pull/7") == (
            constants.parent_marker("https://github.com/o/r/pull/7")
        )
        assert module.child_marker("https://github.com/o/r/pull/7", "F3") == (
            constants.child_marker("https://github.com/o/r/pull/7", "F3")
        )
        assert module.summary_marker("https://github.com/o/r/pull/7") == (
            constants.summary_marker("https://github.com/o/r/pull/7")
        )
        assert module.LABEL_DEFINITIONS == constants.LABEL_DEFINITIONS


def test_the_frozen_fallback_renders_byte_identically_to_todays_literals() -> None:
    """The exact strings already persisted in live issues (§3.9), hand-written here."""
    with effective_module(None) as module:
        assert module.parent_marker("https://github.com/o/r/pull/7") == (
            "<!-- mythical-forge-review-followups: pr=https://github.com/o/r/pull/7 -->"
        )
        assert module.child_marker("U", "F1") == (
            "<!-- mythical-forge-review-follow-up: pr=U finding=F1 -->"
        )
        assert module.summary_marker("U") == (
            "<!-- mythical-forge-review-followups-summary: pr=U -->"
        )
        assert module.LABEL_DEFINITIONS["approve-fix"] == {
            "color": "B8D64A",
            "description": "Human-approved review follow-up fix",
        }


def test_the_frozen_fallback_is_a_copy_not_an_alias_of_constants() -> None:
    """A configured run must never mutate the module-level frozen literals."""
    with effective_module(None) as module:
        module.LABEL_DEFINITIONS["must-fix"]["color"] = "000000"
        assert constants.LABEL_DEFINITIONS["must-fix"]["color"] == "B60205"
    # The restore reload rebuilt the mapping from the frozen literals again.
    assert gh.LABEL_DEFINITIONS == constants.LABEL_DEFINITIONS


# ---------------------------------------------------------------------------
# Present → the resolved values (the configured case)
# ---------------------------------------------------------------------------


def test_a_non_default_handoff_supplies_the_templates_and_label_definitions() -> None:
    payload = _handoff(
        markers={
            "parent": "<!-- acme-parent: {pr_url} -->",
            "child": "<!-- acme-child: {pr_url}/{finding_id} -->",
            "summary": "<!-- acme-summary: {pr_url} -->",
        },
        labels={
            **_all_labels(),
            "must-fix": {"color": "AA0000", "description": "Acme blocking"},
            "acme-extra": {"color": "00AA00", "description": "Repo-added label"},
        },
    )

    with effective_module(payload) as module:
        assert module.parent_marker("U") == "<!-- acme-parent: U -->"
        assert module.child_marker("U", "F2") == "<!-- acme-child: U/F2 -->"
        assert module.summary_marker("U") == "<!-- acme-summary: U -->"
        assert module.LABEL_DEFINITIONS["must-fix"] == {
            "color": "AA0000",
            "description": "Acme blocking",
        }
        # An open map: a repo-added definition rides along rather than being dropped.
        assert module.LABEL_DEFINITIONS["acme-extra"]["color"] == "00AA00"
        # The frozen role names are still what the scripts import from ``constants``; the
        # handoff only supplies definitions for them.
        assert set(constants.LABEL_DEFINITIONS) <= set(module.LABEL_DEFINITIONS)


def test_find_parent_issues_matches_with_the_configured_parent_marker(monkeypatch) -> None:
    """The search the publisher's marker must agree with uses the *effective* template."""
    body = "<!-- acme-parent: https://github.com/o/r/pull/7 -->\n\nthe rest"

    with effective_module(
        _handoff(markers={
            "parent": "<!-- acme-parent: {pr_url} -->",
            "child": constants.CHILD_MARKER_TEMPLATE,
            "summary": constants.SUMMARY_MARKER_TEMPLATE,
        })
    ) as module:
        monkeypatch.setattr(
            module,
            "list_issues",
            lambda _repo: [
                {"number": 7, "title": "parent", "html_url": "u", "state": "open", "body": body}
            ],
        )
        parents = module.find_parent_issues("o/r", "https://github.com/o/r/pull/7")

    assert [parent.number for parent in parents] == [7]


# ---------------------------------------------------------------------------
# Present-but-broken → fail closed, before any marker renders
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param("definitely not json", "not valid JSON", id="not-json"),
        pytest.param("", "not valid JSON", id="empty-value"),
        pytest.param("[]", "must be a JSON object", id="top-level-list"),
        pytest.param(
            json.dumps(
                {"markers": {"parent": "p", "child": "c"}, "labels": _all_labels()}
            ),
            "`markers.summary` is missing",
            id="missing-marker",
        ),
        pytest.param(
            json.dumps(
                {
                    "markers": {"parent": 1, "child": "c", "summary": "s"},
                    "labels": _all_labels(),
                }
            ),
            "`markers.parent` must be a string",
            id="marker-type",
        ),
        pytest.param(
            _handoff(labels={"must-fix": {"color": "B60205", "description": "d"}}),
            "`labels` is missing",
            id="missing-label",
        ),
        pytest.param(
            _handoff(labels={**_all_labels(), "must-fix": {"color": "B60205"}}),
            "`labels.must-fix.description` must be a string",
            id="missing-label-field",
        ),
    ],
)
def test_a_broken_handoff_fails_closed_at_the_resolution_step(
    payload: str, expected: str, capsys
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        with effective_module(payload):
            pass  # pragma: no cover - the reload itself raises

    assert exit_info.value.code == constants.EXIT_ERROR
    stderr = capsys.readouterr().err
    assert stderr.startswith("error: ")
    assert gh.CONFIG_ENV_VAR in stderr
    assert expected in stderr


@pytest.mark.parametrize(
    ("template", "detail"),
    [
        pytest.param("<!-- {pr_url", "does not render", id="stray-brace"),
        pytest.param("<!-- {nope} -->", "does not render", id="unknown-placeholder"),
        pytest.param("{0}", "does not render", id="positional-placeholder"),
        pytest.param("{pr_url.missing}", "does not render", id="missing-attribute"),
    ],
)
def test_a_template_that_cannot_render_fails_closed_before_any_marker(
    template: str, detail: str, capsys
) -> None:
    """Req 5: validation uses the accessor's own keyed ``.format``, at resolution time.

    A stray ``{`` raises ``ValueError``, an unknown placeholder ``KeyError``, a positional
    one ``IndexError``; all three become one clear fail-closed error, so a publish can never
    start and then die half-way through with some markers already written.
    """
    payload = _handoff(
        markers={
            "parent": template,
            "child": constants.CHILD_MARKER_TEMPLATE,
            "summary": constants.SUMMARY_MARKER_TEMPLATE,
        }
    )

    with pytest.raises(SystemExit) as exit_info:
        with effective_module(payload):
            pass  # pragma: no cover - the reload itself raises

    assert exit_info.value.code == constants.EXIT_ERROR
    stderr = capsys.readouterr().err
    assert "`markers.parent`" in stderr
    assert detail in stderr


def test_an_unused_top_level_key_is_tolerated() -> None:
    """Forward compatibility: a copied copy of these scripts must not refuse a newer payload.

    Only ``markers``/``labels`` are read; anything else is ignored, while a *typo'd* key
    still fails closed as a missing required field (the parametrized cases above).
    """
    payload = json.loads(_handoff())
    payload["something_added_later"] = {"unused": True}

    with effective_module(json.dumps(payload)) as module:
        assert module.parent_marker("U") == constants.parent_marker("U")


def test_a_missing_markers_key_is_a_missing_field_not_a_typo_error(capsys) -> None:
    payload = json.loads(_handoff())
    payload["marker"] = payload.pop("markers")

    with pytest.raises(SystemExit) as exit_info:
        with effective_module(json.dumps(payload)):
            pass  # pragma: no cover - the reload itself raises

    assert exit_info.value.code == constants.EXIT_ERROR
    assert "`markers` must be a JSON object" in capsys.readouterr().err


def test_the_child_template_is_validated_with_its_own_arguments(capsys) -> None:
    """``child`` also gets ``finding_id``: a template using only ``{pr_url}`` still works."""
    payload = _handoff(
        markers={
            "parent": constants.PARENT_MARKER_TEMPLATE,
            "child": "<!-- child: {pr_url} -->",
            "summary": constants.SUMMARY_MARKER_TEMPLATE,
        }
    )

    with effective_module(payload) as module:
        assert module.child_marker("U", "F9") == "<!-- child: U -->"
    assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# The script actually exits: the CLI, not just the module import
# ---------------------------------------------------------------------------


def _run_script(script: str, payload: str | None, *args: str) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if key != gh.CONFIG_ENV_VAR}
    if payload is not None:
        env[gh.CONFIG_ENV_VAR] = payload
    return subprocess.run(
        [sys.executable, str(SCRIPT_DIR / script), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.mark.parametrize(
    "script", ["review_followup.py", "publish_review_followups.py"]
)
def test_the_scripts_run_standalone_with_no_config_present(script: str) -> None:
    """The roadmap's Done-when: no handoff, no ``aidw``, no install step."""
    result = _run_script(script, None, "--help")

    assert result.returncode == constants.EXIT_OK, result.stderr
    assert result.stdout


def test_a_broken_handoff_makes_the_cli_exit_2_with_a_clear_error() -> None:
    result = _run_script("review_followup.py", "{not json")

    assert result.returncode == constants.EXIT_ERROR
    assert result.stderr.startswith("error: ")
    assert gh.CONFIG_ENV_VAR in result.stderr
    # Nothing was published and no marker was rendered before the refusal.
    assert result.stdout == ""


def test_a_template_that_cannot_render_makes_the_cli_exit_2() -> None:
    payload = _handoff(
        markers={
            "parent": "<!-- {pr_url",
            "child": constants.CHILD_MARKER_TEMPLATE,
            "summary": constants.SUMMARY_MARKER_TEMPLATE,
        }
    )

    result = _run_script("publish_review_followups.py", payload, "--help")

    assert result.returncode == constants.EXIT_ERROR
    assert "`markers.parent`" in result.stderr
    assert result.stdout == ""
