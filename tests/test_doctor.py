"""Phase 0 tests for the doctor checks that are environment-independent."""

from __future__ import annotations

import pytest

from aidw import doctor
from aidw.doctor import (
    FAIL,
    OK,
    WARN,
    _check_dependencies,
    _check_gh_version,
    _check_python,
    _missing_gh_capabilities,
    _parse_gh_version,
    collect_checks,
)

#: ``gh --help`` excerpts for a build that has sub-issue support, and one that predates it.
_CURRENT_GH_HELP = {
    "issue view --help": (
        "JSON FIELDS\n  assignees, body, number, parent, state, subIssues,\n"
        "  subIssuesSummary, title, url\n"
    ),
    "issue create --help": (
        "FLAGS\n  -t, --title string\n      --parent number   Add the new issue as a sub-issue\n"
    ),
}
_OLD_GH_HELP = {
    "issue view --help": "JSON FIELDS\n  assignees, author, body, number, state, title\n",
    "issue create --help": "FLAGS\n  -t, --title string\n",
}


def _install_gh(
    monkeypatch: pytest.MonkeyPatch,
    *,
    version: str | None = "gh version 2.97.0 (2026-07-31)",
    help_output: dict[str, str] | None = None,
    path: str | None = "/usr/local/bin/gh",
    version_exit: int = 0,
) -> list[list[str]]:
    """Stand in for ``gh``; returns the list of argv arrays the checks invoked."""
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: path)
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: object = None) -> tuple[int, str]:
        assert cmd[0] == "gh", f"unexpected command: {cmd}"
        calls.append(cmd)
        if cmd[1] == "--version":
            return version_exit, version or ""
        if help_output is None:
            return 1, "gh: help unavailable"
        return 0, help_output.get(" ".join(cmd[1:]), "")

    monkeypatch.setattr(doctor, "_run", fake_run)
    return calls


def test_python_check_ok() -> None:
    check = _check_python()
    assert check.status == OK


def test_dependencies_importable() -> None:
    check = _check_dependencies()
    assert check.status == OK


def test_collect_checks_returns_results(fake_external_clis: None) -> None:  # noqa: ARG001
    checks = collect_checks()
    assert checks
    # Findings must be within the known status vocabulary.
    for check in checks:
        assert check.status in (OK, "WARN", FAIL)


def test_parse_gh_version() -> None:
    assert _parse_gh_version("gh version 2.97.0 (2026-07-31)\nhttps://example") == (2, 97, 0)
    assert _parse_gh_version("gh: command not found") is None


def test_gh_version_check_ok_for_current_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_gh(monkeypatch, help_output=_CURRENT_GH_HELP)
    check = _check_gh_version()
    assert check.status == OK
    assert "2.97.0" in check.detail
    assert "/usr/local/bin/gh" in check.detail


def test_gh_version_check_fails_for_stale_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    """The incident this check exists for: an old ``gh`` shadowing a current one on PATH."""
    _install_gh(
        monkeypatch,
        version="gh version 2.65.0 (2025-01-06)",
        help_output=_OLD_GH_HELP,
        path="/Users/phil/.local/bin/gh",
    )
    check = _check_gh_version()
    assert check.status == FAIL
    assert "2.65.0" in check.detail
    assert "/Users/phil/.local/bin/gh" in check.detail
    assert "2.94.0" in check.detail
    assert "subIssues" in check.detail
    assert "--parent" in check.detail


def test_gh_version_check_fails_when_capability_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A new version number alone is not enough; the capability probe is authoritative."""
    _install_gh(monkeypatch, help_output=_OLD_GH_HELP)
    check = _check_gh_version()
    assert check.status == FAIL
    assert "lacks" in check.detail


def test_gh_version_check_warns_when_gh_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_gh(monkeypatch, path=None)
    check = _check_gh_version()
    assert check.status == WARN


def test_gh_version_check_warns_when_version_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_gh(monkeypatch, version_exit=1, help_output=_CURRENT_GH_HELP)
    check = _check_gh_version()
    assert check.status == WARN


def test_unreadable_probe_is_not_a_missing_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_gh(monkeypatch, help_output=None)
    assert _missing_gh_capabilities() == []
