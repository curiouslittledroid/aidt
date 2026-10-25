"""Tests for the GitHub helper layer (design §13, Phase 5)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from aidw import github


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
        lambda argv, repo, timeout: _script_result(
            _approve_children("already-approved", "preserved-closed")
        ),
    )

    assert github.verify_approvals(Path("/aidt"), Path("/repo"), 7) is None


def test_verify_approvals_reports_children_still_pending(monkeypatch) -> None:
    monkeypatch.setattr(
        github,
        "run_script",
        lambda argv, repo, timeout: _script_result(
            _approve_children("already-approved", "would-approve")
        ),
    )

    error = github.verify_approvals(Path("/aidt"), Path("/repo"), 7)

    assert error is not None and "#101" in error


def test_verify_approvals_reports_a_read_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        github,
        "run_script",
        lambda argv, repo, timeout: _script_result("", exit_code=2, stderr="gh: not authenticated"),
    )

    error = github.verify_approvals(Path("/aidt"), Path("/repo"), 7)

    assert error is not None
    assert "exit 2" in error
    assert "not authenticated" in error


def test_verify_approvals_rejects_unparseable_output(monkeypatch) -> None:
    monkeypatch.setattr(
        github,
        "run_script",
        lambda argv, repo, timeout: _script_result("not json"),
    )

    error = github.verify_approvals(Path("/aidt"), Path("/repo"), 7)

    assert error == "approve --dry-run returned unparseable output"


def test_verify_approvals_runs_a_read_only_command(monkeypatch) -> None:
    seen: dict = {}

    def _capture(argv, repo, timeout):
        seen["argv"] = argv
        return _script_result(_approve_children("already-approved"))

    monkeypatch.setattr(github, "run_script", _capture)

    github.verify_approvals(Path("/aidt"), Path("/repo"), 7)

    assert "approve" in seen["argv"]
    assert "--dry-run" in seen["argv"]
    assert "--pr" in seen["argv"]
