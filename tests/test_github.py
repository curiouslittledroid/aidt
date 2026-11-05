"""Tests for the GitHub helper layer (design §13, Phase 5)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from aidw import github
from aidw.paths import REVIEW_FOLLOWUP_CONFIG_ENV_VAR


def test_build_publish_argv_with_pr() -> None:
    argv = github.build_publish_argv(
        Path("/aidt/prompts/scripts/review-followup/publish_review_followups.py"),
        42,
        Path("/runs/x/artifacts/review-manifest.json"),
    )
    assert argv[:2] == [
        sys.executable,
        "/aidt/prompts/scripts/review-followup/publish_review_followups.py",
    ]
    assert argv[argv.index("--pr") + 1] == "42"
    assert argv[argv.index("--input") + 1].endswith("review-manifest.json")
    assert "--dry-run" not in argv


def test_build_publish_argv_dry_run_without_pr() -> None:
    argv = github.build_publish_argv(
        Path("/s.py"), None, Path("/m.json"), dry_run=True
    )
    assert "--pr" not in argv
    assert argv[-1] == "--dry-run"


def test_build_followup_argv() -> None:
    argv = github.build_followup_argv(
        Path("/s.py"), "select", 42, allow_branch_mismatch=True
    )
    assert argv == [
        sys.executable,
        "/s.py",
        "select",
        "--pr",
        "42",
        "--allow-branch-mismatch",
    ]


def test_parse_publish_output() -> None:
    stdout = (
        "Repository: o/r\n"
        "PR: #42 https://github.com/o/r/pull/42\n"
        "Findings: 2\n"
        "F1: created #101 https://github.com/o/r/issues/101\n"
        "F2: updated #102 https://github.com/o/r/issues/102\n"
        "Parent issue: https://github.com/o/r/issues/100\n"
        "Summary comment: https://github.com/o/r/pull/42#issuecomment-999\n"
    )
    parsed = github.parse_publish_output(stdout)
    assert parsed["parent_issue"]["number"] == 100
    assert set(parsed["child_issues"]) == {"F1", "F2"}
    assert parsed["child_issues"]["F2"]["action"] == "updated"
    assert parsed["summary_comment"]["url"].endswith("issuecomment-999")


def test_pr_view_parses_gh_json(monkeypatch) -> None:
    payload = {
        "number": 7,
        "url": "https://github.com/o/r/pull/7",
        "baseRefName": "main",
        "headRefName": "03-E4.1",
    }

    monkeypatch.setattr(
        github, "_run", lambda argv, repo, timeout=github.DEFAULT_TIMEOUT: (0, json.dumps(payload), "")
    )
    assert github.pr_view(Path("/repo"), 7) == payload


def test_pr_view_returns_none_on_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "_run", lambda argv, repo, timeout=github.DEFAULT_TIMEOUT: (1, "", "nope")
    )
    assert github.pr_view(Path("/repo"), 7) is None


def _script_result(stdout: str, exit_code: int = 0, stderr: str = "") -> github.ScriptResult:
    return github.ScriptResult([], exit_code, stdout, stderr)


def _approve_children(*actions: str) -> str:
    return json.dumps(
        {
            "action": "dry-run",
            "children": [
                {"number": 100 + index, "action": action}
                for index, action in enumerate(actions)
            ],
        }
    )


def test_verify_approvals_holds_when_no_open_child_needs_changes(monkeypatch) -> None:
    monkeypatch.setattr(
        github,
        "run_script",
        lambda argv, repo, timeout, **_kwargs: _script_result(
            _approve_children("already-approved", "preserved-closed")
        ),
    )

    assert github.verify_approvals(Path("/aidt"), Path("/repo"), 7) is None


def test_verify_approvals_reports_children_still_pending(monkeypatch) -> None:
    monkeypatch.setattr(
        github,
        "run_script",
        lambda argv, repo, timeout, **_kwargs: _script_result(
            _approve_children("already-approved", "would-approve")
        ),
    )

    error = github.verify_approvals(Path("/aidt"), Path("/repo"), 7)

    assert error is not None and "#101" in error


def test_verify_approvals_reports_a_read_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        github,
        "run_script",
        lambda argv, repo, timeout, **_kwargs: _script_result("", exit_code=2, stderr="gh: not authenticated"),
    )

    error = github.verify_approvals(Path("/aidt"), Path("/repo"), 7)

    assert error is not None
    assert "exit 2" in error
    assert "not authenticated" in error


def test_verify_approvals_rejects_unparseable_output(monkeypatch) -> None:
    monkeypatch.setattr(
        github,
        "run_script",
        lambda argv, repo, timeout, **_kwargs: _script_result("not json"),
    )

    error = github.verify_approvals(Path("/aidt"), Path("/repo"), 7)

    assert error == "approve --dry-run returned unparseable output"


def test_verify_approvals_runs_a_read_only_command(monkeypatch) -> None:
    seen: dict = {}

    def _capture(argv, repo, timeout, **_kwargs):
        seen["argv"] = argv
        return _script_result(_approve_children("already-approved"))

    monkeypatch.setattr(github, "run_script", _capture)

    github.verify_approvals(Path("/aidt"), Path("/repo"), 7)

    assert "approve" in seen["argv"]
    assert "--dry-run" in seen["argv"]
    assert "--pr" in seen["argv"]


# ---------------------------------------------------------------------------
# E6.1: the resolved github.markers/github.labels handoff
# ---------------------------------------------------------------------------
#
# One vector per behaviour: the payload shape and its values, the env reaching the
# subprocess through both callers that run a bundled script, the same callers leaving the
# variable *absent* when no config is threaded, and the read-only helpers never carrying it
# (they are ``gh`` calls, not bundled scripts).


def _resolved_defaults():
    from aidw.target_config import TargetConfig, resolve_config

    return resolve_config(TargetConfig(schema_version=1))


def _resolved_with_override():
    """Defaults merged under a declared marker + label, as a real repo config resolves."""
    from aidw.target_config import (
        GitHubConfig,
        LabelConfig,
        MarkersConfig,
        TargetConfig,
        resolve_config,
    )

    return resolve_config(
        TargetConfig(
            schema_version=1,
            github=GitHubConfig(
                markers=MarkersConfig(parent="<!-- declared: pr={pr_url} -->"),
                labels={
                    "must-fix": LabelConfig(
                        color="111111", description="Declared blocking"
                    )
                },
            ),
        )
    )


def test_serialize_github_config_emits_the_handoff_shape() -> None:
    payload = json.loads(github.serialize_github_config(_resolved_defaults()))

    assert set(payload) == {"markers", "labels"}
    assert payload["markers"] == {
        "parent": "<!-- mythical-forge-review-followups: pr={pr_url} -->",
        "child": (
            "<!-- mythical-forge-review-follow-up: pr={pr_url} "
            "finding={finding_id} -->"
        ),
        "summary": "<!-- mythical-forge-review-followups-summary: pr={pr_url} -->",
    }
    # Labels are enumerated from the resolved entries: the six seeded definitions, each
    # exactly a colour and a description.
    assert set(payload["labels"]) == {
        "review-follow-up",
        "must-fix",
        "should-fix",
        "could-fix",
        "decision-pending",
        "approve-fix",
    }
    assert payload["labels"]["must-fix"] == {
        "color": "B60205",
        "description": "Blocking review finding",
    }
    assert all(set(entry) == {"color", "description"} for entry in payload["labels"].values())


def test_serialize_github_config_carries_declared_overrides_with_the_defaults() -> None:
    payload = json.loads(github.serialize_github_config(_resolved_with_override()))

    assert payload["markers"]["parent"] == "<!-- declared: pr={pr_url} -->"
    # Undeclared siblings still come from the toolkit defaults.
    assert payload["markers"]["child"].startswith("<!-- mythical-forge-review-follow-up:")
    assert payload["labels"]["must-fix"] == {
        "color": "111111",
        "description": "Declared blocking",
    }
    assert payload["labels"]["approve-fix"]["color"] == "B8D64A"


def _capture_subprocess(monkeypatch) -> dict:
    seen: dict = {}
    stdout = _approve_children("already-approved")

    def _fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(github.subprocess, "run", _fake_run)
    return seen


def test_select_followups_carries_the_handoff_to_the_script(monkeypatch) -> None:
    seen = _capture_subprocess(monkeypatch)
    config = _resolved_with_override()

    github.select_followups(Path("/aidt"), Path("/repo"), 7, config=config)

    assert seen["env"] is not None
    assert seen["env"][REVIEW_FOLLOWUP_CONFIG_ENV_VAR] == github.serialize_github_config(
        config
    )


def test_verify_approvals_carries_the_handoff_to_the_script(monkeypatch) -> None:
    seen = _capture_subprocess(monkeypatch)
    config = _resolved_defaults()

    assert github.verify_approvals(Path("/aidt"), Path("/repo"), 7, config=config) is None
    assert seen["env"][REVIEW_FOLLOWUP_CONFIG_ENV_VAR] == github.serialize_github_config(
        config
    )


def test_script_callers_leave_the_variable_absent_without_a_config(monkeypatch) -> None:
    """``config=None`` is "unset", never an empty payload: the script must fall back."""
    seen = _capture_subprocess(monkeypatch)

    github.select_followups(Path("/aidt"), Path("/repo"), 7)

    # The child gets a copied environment with any inherited handoff removed, so the
    # scripts take their frozen constants fallback rather than a stale or partial handoff.
    assert seen["env"] is not None
    assert REVIEW_FOLLOWUP_CONFIG_ENV_VAR not in seen["env"]


def test_script_callers_remove_a_stale_inherited_handoff_without_a_config(monkeypatch) -> None:
    """``config=None`` must not accidentally reuse a caller's stale repo configuration."""
    monkeypatch.setenv(REVIEW_FOLLOWUP_CONFIG_ENV_VAR, '{"stale": true}')
    seen = _capture_subprocess(monkeypatch)

    github.select_followups(Path("/aidt"), Path("/repo"), 7)

    # ``None`` means the default/frozen path, not "inherit whatever handoff the parent
    # process happened to have". The subprocess environment must explicitly omit it.
    assert seen["env"] is not None
    assert REVIEW_FOLLOWUP_CONFIG_ENV_VAR not in seen["env"]


def test_read_only_gh_helpers_never_carry_the_handoff(monkeypatch) -> None:
    """``repo_slug``/``pr_view`` are ``gh`` reads, not bundled scripts: no env channel."""
    calls: list[tuple] = []

    def _capture(argv, repo, timeout=github.DEFAULT_TIMEOUT, **kwargs):
        calls.append((argv, kwargs))
        return 1, "", ""

    monkeypatch.setattr(github, "_run", _capture)

    github.repo_slug(Path("/repo"))
    github.pr_view(Path("/repo"), 7)

    assert len(calls) == 2
    assert all(kwargs == {} for _argv, kwargs in calls)


def test_argv_builders_carry_no_env_channel() -> None:
    """Req 6(b): the argv builders are argv-only; the env travels through the runner."""
    publish = github.build_publish_argv(Path("/s.py"), 7, Path("/m.json"))
    followup = github.build_followup_argv(Path("/s.py"), "select", 7)

    assert all(isinstance(part, str) for part in publish + followup)
    assert "--input" in publish
    assert followup[2] == "select"
