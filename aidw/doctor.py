"""``aidw doctor`` — environment and prerequisite validation.

Checks the local environment, repository state, AIDT's own prompts and helper scripts,
agent configs and optional external tooling. Reports ``OK`` / ``WARN`` / ``FAIL`` per
check and exits non-zero only when at least one check fails.

See ``design.md`` §12.
"""

from __future__ import annotations

import importlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from aidw import inventory
from aidw.paths import RepoNotFoundError, aidt_root, repo_root

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

_SYMBOL = {OK: "  ok  ", WARN: " warn ", FAIL: " fail "}

#: The ``gh`` release that added sub-issue support: the ``parent``/``subIssues`` fields on
#: ``gh issue view --json`` and ``--parent`` on ``gh issue create``. The bundled
#: review-followup scripts use all three, so an older ``gh`` breaks ``select``, ``approve``
#: and ``publish`` with ``Unknown JSON field: "subIssues"``.
GH_MIN_VERSION = (2, 94, 0)

#: Sub-issue capabilities to probe for, as ``(argv, label, help pattern)``. Probed from
#: ``gh``'s own help output as well as version-checked, so a stale or shadowed binary that
#: reports a new version without the features is still caught, and the report names exactly
#: what is missing. The ``\bsubIssues\b`` word boundary stops the adjacent
#: ``subIssuesSummary`` field from satisfying the probe on its own.
_GH_CAPABILITY_PROBES: tuple[tuple[list[str], str, str], ...] = (
    (["issue", "view", "--help"], "issue view --json parent/subIssues", r"\bsubIssues\b"),
    (["issue", "create", "--help"], "issue create --parent", r"^\s*--parent\b"),
)


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not found"
    return result.returncode, (result.stdout + result.stderr).strip()


def _check_python() -> Check:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info >= (3, 11):
        return Check("python", OK, version)
    return Check("python", FAIL, f"{version} (requires >= 3.11)")


def _check_python3() -> Check:
    """The interpreter the prompts use to invoke the bundled helper scripts.

    ``aidw`` itself always runs the scripts with its own interpreter
    (``sys.executable``); this check is about the ``python3`` the review and fix
    prompts call from the agent's shell.
    """
    path = shutil.which("python3")
    if path is None:
        return Check(
            "python3",
            WARN,
            "not on PATH; the review/fix prompts invoke the helper scripts with python3",
        )
    return Check("python3", OK, path)


def _check_dependencies() -> Check:
    missing = []
    for module in ("yaml", "typer"):
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(module)
    if missing:
        return Check(
            "python deps",
            FAIL,
            "missing: "
            + ", ".join(missing)
            + " (run `uv sync` inside aidt/)",
        )
    return Check("python deps", OK, "pyyaml, typer importable")


def _check_uv() -> Check:
    path = shutil.which("uv")
    if path:
        code, out = _run(["uv", "--version"])
        if code == 0:
            return Check("uv", OK, f"{out} ({path})")
        return Check("uv", WARN, f"found at {path} but `uv --version` failed")
    # Running under `uv run` is fine even when uv is not on PATH.
    if os.environ.get("UV"):
        return Check("uv", OK, "running under uv (UV env set)")
    return Check(
        "uv",
        WARN,
        "not on PATH; install from https://docs.astral.sh/uv/ or use the full path",
    )


def _check_pi() -> Check:
    path = shutil.which("pi")
    if not path:
        return Check("pi", FAIL, "not on PATH")
    code, out = _run(["pi", "--version"])
    if code != 0:
        return Check("pi", WARN, f"found at {path} but `pi --version` failed")
    first = out.splitlines()[0] if out else "unknown"
    return Check("pi", OK, f"{first} ({path})")


def _check_gh() -> Check:
    path = shutil.which("gh")
    if not path:
        return Check("gh", WARN, "not on PATH; required by review/fix workflows")
    code, out = _run(["gh", "auth", "status"])
    if code != 0:
        return Check("gh", WARN, "not authenticated; run `gh auth login`")
    account = next(
        (line.strip() for line in out.splitlines() if "account" in line.lower()),
        "authenticated",
    )
    return Check("gh", OK, account)


def _parse_gh_version(output: str) -> tuple[int, int, int] | None:
    match = re.search(r"gh version (\d+)\.(\d+)\.(\d+)", output)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def _missing_gh_capabilities() -> list[str]:
    """Sub-issue capabilities this ``gh`` build lacks, per its own ``--help`` output.

    A probe that cannot be read reports nothing missing: a change to the help layout is not
    evidence that the capability is absent, and the version check still applies.
    """
    missing: list[str] = []
    for argv, capability, pattern in _GH_CAPABILITY_PROBES:
        code, out = _run(["gh", *argv])
        if code != 0:
            continue
        if re.search(pattern, out, re.MULTILINE) is None:
            missing.append(capability)
    return missing


def _check_gh_version() -> Check:
    """``gh`` must carry the sub-issue API the bundled review/fix scripts call.

    A stale or shadowed ``gh`` earlier on ``PATH`` otherwise fails deep inside a review/fix
    agent stage (``Unknown JSON field: "subIssues"``) instead of during preflight.
    """
    path = shutil.which("gh")
    if path is None:
        return Check("gh version", WARN, "not on PATH; required by review/fix workflows")

    code, out = _run(["gh", "--version"])
    if code != 0:
        return Check("gh version", WARN, f"found at {path} but `gh --version` failed")

    version = _parse_gh_version(out)
    shown = ".".join(str(part) for part in version) if version else "unknown version"
    minimum = ".".join(str(part) for part in GH_MIN_VERSION)

    missing = _missing_gh_capabilities()
    if missing or (version is not None and version < GH_MIN_VERSION):
        reason = f"lacks {', '.join(missing)}" if missing else "predates sub-issue support"
        return Check(
            "gh version",
            FAIL,
            f"{shown} ({path}) {reason}; the review/fix scripts require gh >= {minimum}. "
            "Upgrade (e.g. `brew upgrade gh`) and make sure that copy is first on PATH.",
        )
    return Check("gh version", OK, f"{shown} ({path})")


def _check_git(root: Path) -> Check:
    code, out = _run(["git", "branch", "--show-current"], cwd=root)
    if code != 0:
        return Check("git", FAIL, "not a git repository")
    branch = out or "(detached)"
    code, status = _run(["git", "status", "--porcelain"], cwd=root)
    dirty = "dirty working tree" if status else "clean working tree"
    level = WARN if status else OK
    return Check("git", level, f"branch {branch}, {dirty}")


def _check_mcp(root: Path) -> Check:
    path = root / ".mcp.json"
    if path.exists():
        return Check("mcp config", OK, str(path))
    return Check("mcp config", WARN, f"missing {path}")


def _check_prompts(aidt: Path) -> Check:
    issues = inventory.check(aidt)
    errors = [issue for issue in issues if issue.level == "error"]
    if errors:
        return Check("prompts", FAIL, errors[0].message)
    return Check("prompts", OK, f"{len(inventory.list_files(aidt))} file(s)")


def _check_agent_configs(aidt: Path) -> Check:
    configs = sorted((aidt / "agent-configs").glob("*.yaml"))
    if configs:
        return Check("agent configs", OK, f"{len(configs)} config(s)")
    return Check(
        "agent configs",
        WARN,
        "none found (Phase 1: add configs under aidt/agent-configs/)",
    )


def _check_archify() -> Check:
    skill = Path.home() / ".pi" / "agent" / "skills" / "archify" / "SKILL.md"
    if skill.exists():
        return Check("archify skill", OK, str(skill))
    return Check(
        "archify skill",
        WARN,
        "not found; required only when /update-architecture changes a diagram",
    )


def collect_checks() -> list[Check]:
    checks: list[Check] = [
        _check_python(),
        _check_python3(),
        _check_dependencies(),
        _check_uv(),
        _check_pi(),
        _check_gh(),
        _check_gh_version(),
    ]

    try:
        root = repo_root()
    except RepoNotFoundError as exc:
        checks.append(Check("repo root", FAIL, str(exc)))
        return checks

    checks.append(Check("repo root", OK, str(root)))
    checks.append(_check_git(root))
    checks.append(_check_mcp(root))

    aidt = aidt_root()
    checks.append(_check_prompts(aidt))
    checks.append(_check_agent_configs(aidt))
    checks.append(_check_archify())
    return checks


def run_doctor(verbose: bool = False) -> int:
    """Print the environment report and return a process exit code."""
    checks = collect_checks()
    width = max(len(check.name) for check in checks)

    print("AIDT doctor")
    print("=" * (width + 40))
    for check in checks:
        print(f"[{_SYMBOL[check.status]}] {check.name.ljust(width)}  {check.detail}")

    failures = [check for check in checks if check.status == FAIL]
    warnings = [check for check in checks if check.status == WARN]
    print("-" * (width + 40))
    print(f"{len(checks)} checks: {len(failures)} failed, {len(warnings)} warning(s)")

    if failures:
        return 1
    return 0
