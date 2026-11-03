"""``aidw doctor`` — environment and prerequisite validation.

Checks the local environment, repository state, AIDT's own prompts and helper scripts,
agent configs and optional external tooling. Reports ``OK`` / ``WARN`` / ``FAIL`` per
check and exits non-zero only when at least one check fails.

The target side of the report is the §3.2 layout diagnosis (E2.8): the target is
resolved through :meth:`aidw.paths.TargetRepo.resolve` (so ``--repo``/``AIDW_REPO`` are
honoured and a bare directory is reachable), and the workspace root, state root and
control worktree are classified by :func:`aidw.layout.check_layout` — the same guard
``cli._roots`` uses — rather than by a doctor-local copy of its rules.

See ``design.md`` §12/§14 and ``docs/migration/EXTRACTION.md`` §3.1/§3.2/§3.10.
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
from aidw.layout import LayoutError, check_layout
from aidw.paths import (
    BareRepositoryError,
    RepoNotFoundError,
    TargetRepo,
    ToolkitPaths,
    WorkspacePaths,
    toolkit_root,
)

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

_SYMBOL = {OK: "  ok  ", WARN: " warn ", FAIL: " fail "}

#: The ``gh`` release that added sub-issue support: the ``parent``/``subIssues`` fields on
#: ``gh issue view --json`` and ``--parent`` on ``gh issue create``. The bundled
#: review-followup scripts use all three, so an older ``gh`` breaks ``select``, ``approve``
#: and ``publish`` with ``Unknown JSON field: "subIssues"``.
GH_MIN_VERSION = (2, 94, 0)

#: The oldest Pi AIDW works with: its argv flags are verified against 0.85.x (§5.5). Below
#: this floor a stage fails *before the first model call* — an older Pi cannot load the
#: extensions the operator's package set installs (``@earendil-works/pi-ai/compat`` is a
#: 0.85 addition), so every ``pi`` invocation exits 1 at extension load and AIDW records
#: only ``exit code 1`` with zero tokens, zero events and an empty stage JSONL. That is
#: unreadable from a run record, so preflight names it instead (§12).
PI_MIN_VERSION = (0, 85, 0)

#: The oldest git AIDW works with: ``TargetRepo.resolve`` reads the repository identity
#: with ``git rev-parse --path-format=absolute``, which git added in 2.31 (§3.2 "Minimum
#: git"). Older git fails that flag inside every command's preflight, so the floor is
#: checked up front rather than discovered as an unreadable repository.
GIT_MIN_VERSION = (2, 31, 0)

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


def _parse_pi_version(output: str) -> tuple[int, int, int] | None:
    """``X.Y.Z`` from ``pi --version``, which prints the bare version (``0.74.2``)."""
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", output)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def _check_pi() -> Check:
    """``pi`` must be on ``PATH`` and at least :data:`PI_MIN_VERSION` (§5.5, §12).

    An unversioned presence check is not enough: a stale ``pi`` earlier on ``PATH`` — an
    old ``nvm`` bin dir shadowing the current one — starts up far enough to answer
    ``--version`` and then dies loading extensions inside the first stage, which reaches
    the run record as nothing more than ``exit code 1``.
    """
    path = shutil.which("pi")
    if not path:
        return Check("pi", FAIL, "not on PATH")
    code, out = _run(["pi", "--version"])
    if code != 0:
        return Check("pi", WARN, f"found at {path} but `pi --version` failed")
    first = out.splitlines()[0] if out else "unknown"
    version = _parse_pi_version(out)
    if version is not None and version < PI_MIN_VERSION:
        shown = ".".join(str(part) for part in version)
        minimum = ".".join(str(part) for part in PI_MIN_VERSION)
        return Check(
            "pi",
            FAIL,
            f"{shown} ({path}) predates the Pi AIDW supports; require pi >= {minimum}. "
            "An older Pi cannot load the installed extensions, so every stage exits 1 "
            "before its first model call. Check for a stale nvm bin dir earlier on PATH "
            "with `which -a pi`.",
        )
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


def _parse_git_version(output: str) -> tuple[int, int, int] | None:
    """``X.Y.Z`` from ``git --version`` (``git version 2.39.5 (Apple Git-154)``)."""
    match = re.search(r"git version (\d+)\.(\d+)\.(\d+)", output)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def _check_git_version() -> Check:
    """``git`` must be present and at least :data:`GIT_MIN_VERSION` (§3.2).

    Unlike ``gh`` (workflow-optional, ``WARN`` when absent) git is required by every
    command, so an absent binary is a ``FAIL`` — the same split ``pi`` uses. An
    unreadable ``--version`` is still only a ``WARN``: it is not proof of an old git.
    """
    path = shutil.which("git")
    if path is None:
        return Check("git version", FAIL, "not on PATH; git is required by every command")

    code, out = _run(["git", "--version"])
    if code != 0:
        return Check("git version", WARN, f"found at {path} but `git --version` failed")

    version = _parse_git_version(out)
    shown = ".".join(str(part) for part in version) if version else "unknown version"
    minimum = ".".join(str(part) for part in GIT_MIN_VERSION)
    if version is not None and version < GIT_MIN_VERSION:
        return Check(
            "git version",
            FAIL,
            f"{shown} ({path}) predates `rev-parse --path-format=absolute`; require "
            f"git >= {minimum} (EXTRACTION.md §3.2). Upgrade git and make sure that "
            "copy is first on PATH.",
        )
    if version is None:
        return Check("git version", WARN, f"{shown} ({path})")
    return Check("git version", OK, f"{shown} ({path})")


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


def _check_toolkit_root() -> Check:
    """Report the installed toolkit root (EXTRACTION.md §3.1/§3.3).

    Derived from :class:`ToolkitPaths`, which resolves from the package location, never
    from git or the cwd, so this check still reports when AIDW runs outside any
    repository (``/tmp``) — the early ``repo_root()`` refusal below would otherwise skip
    it. It is ``FAIL`` when resolution fails, the root is missing, or a workflow-critical
    asset (``prompts``/``scripts``) is absent; ``WARN`` when only the advisory
    ``agent-configs``/``agents`` dirs are missing.
    """
    try:
        toolkit = ToolkitPaths.resolve()
    except Exception as exc:  # noqa: BLE001 - any resolution failure is a doctor FAIL
        return Check("toolkit root", FAIL, f"unresolved: {exc}")

    missing = [
        label
        for label, path in (
            ("prompts", toolkit.prompts_dir),
            ("scripts", toolkit.scripts_dir),
            ("agent-configs", toolkit.agent_configs_dir),
            ("agents", toolkit.agents_dir),
        )
        if not path.is_dir()
    ]
    if not toolkit.root.is_dir():
        missing = ["root", *missing]

    if {"root", "prompts", "scripts"} & set(missing):
        status = FAIL
    elif missing:
        status = WARN
    else:
        status = OK

    detail = str(toolkit.root)
    if missing:
        detail = f"{detail} (missing: {', '.join(missing)})"
    return Check("toolkit root", status, detail)


def _layout_checks(target: TargetRepo) -> list[Check]:
    """Workspace root, state root and control-worktree checks (§3.2/§3.10).

    :func:`aidw.layout.check_layout` is the single classification source, deliberately
    reused instead of reimplemented: a doctor-local copy of its membership/
    more-than-one rule could report ``OK`` while ``cli._roots`` refuses the same layout.
    Its advisory warnings map to a ``WARN`` on the state root, never a ``FAIL``; its
    :class:`LayoutError` maps to a ``FAIL`` on the control worktree.

    ``check_layout`` decides the clone-of-a-worktree trap *before* it returns warnings,
    so a rejected layout never also reports the state-inside-tree ``WARN`` (and can
    never exit 0 on it). Nothing here writes: ``WorkspacePaths.resolve`` only checks
    writability and the layout guard runs read-only git (§3.1 "nothing generated is ever
    written into a target repo").
    """
    workspace = WorkspacePaths.resolve(target)
    checks: list[Check] = [Check("workspace root", OK, str(workspace.workspace_root))]

    layout_error: LayoutError | None = None
    warnings: list[str] = []
    try:
        warnings = check_layout(target, workspace)
    except LayoutError as exc:
        layout_error = exc

    # The warnings are already worded by the guard (both paths, the §3.10 explanation),
    # so echo them rather than restating the finding.
    state_detail = str(workspace.state_root)
    if warnings:
        state_detail = f"{state_detail} — {' '.join(warnings)}"
    checks.append(Check("state root", WARN if warnings else OK, state_detail))

    if layout_error is not None:
        checks.append(Check("control worktree", FAIL, str(layout_error)))
    else:
        checks.append(
            Check(
                "control worktree",
                OK,
                f"{workspace.workspace_root} is not a registered worktree",
            )
        )
    return checks


def collect_checks(explicit: Path | None = None) -> list[Check]:
    """Run every check; ``explicit`` is the ``--repo``/``AIDW_REPO`` target override.

    The override is threaded from :func:`aidw.cli.doctor` (the single place that reads
    the environment) so ``aidw --repo <path> doctor`` and ``AIDW_REPO`` select the
    target, and a bare directory is reachable — the legacy ``repo_root()`` walk-up
    neither honoured the override nor detected a bare repo.
    """
    checks: list[Check] = [
        _check_python(),
        _check_python3(),
        _check_dependencies(),
        _check_uv(),
        _check_pi(),
        _check_gh(),
        _check_gh_version(),
        # Environment checks run outside any repository, so the git floor is verified
        # before the target is resolved (§3.2).
        _check_git_version(),
        # Must precede the target try/except: that branch returns early, and the
        # toolkit root is deliberately resolvable with no repository at all.
        _check_toolkit_root(),
    ]

    try:
        target = TargetRepo.resolve(explicit=explicit)
    except BareRepositoryError as exc:
        # Must precede RepoNotFoundError — BareRepositoryError is its subclass, and the
        # §3.2 bootstrap in this message is the whole point of the check.
        checks.append(Check("target repo", FAIL, str(exc)))
        return checks
    except RepoNotFoundError as exc:
        checks.append(Check("repo root", FAIL, str(exc)))
        return checks

    checks.append(Check("repo root", OK, str(target.root)))
    checks.extend(_layout_checks(target))
    checks.append(_check_git(target.root))
    checks.append(_check_mcp(target.root))

    aidt = toolkit_root()
    checks.append(_check_prompts(aidt))
    checks.append(_check_agent_configs(aidt))
    checks.append(_check_archify())
    return checks


def run_doctor(verbose: bool = False, explicit: Path | None = None) -> int:
    """Print the environment report and return a process exit code.

    Exits non-zero when any check FAILs (``design.md`` §14); a bare target or a
    clone-of-a-worktree layout is a FAIL, the single-checkout state-inside-tree case is
    only a WARN.
    """
    checks = collect_checks(explicit=explicit)
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
