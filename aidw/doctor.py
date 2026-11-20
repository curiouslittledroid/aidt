"""``aidw doctor`` — environment and prerequisite validation.

Checks the local environment, repository state, AIDT's own prompts and helper scripts,
agent configs, the target repo's ``aidw/config.yaml`` and optional external tooling.
Reports ``OK`` / ``WARN`` / ``FAIL`` per check and exits non-zero only when at least one
check fails.

The target side of the report is the §3.2 layout diagnosis (E2.8): the target is
resolved through :meth:`aidw.paths.TargetRepo.resolve` (so ``--repo``/``AIDW_REPO`` are
honoured and a bare directory is reachable), and the workspace root, state root and
control worktree are classified by :func:`aidw.layout.check_layout` — the same guard
``cli._roots`` uses — rather than by a doctor-local copy of its rules. Once a working
tree exists, ``target config`` (E3.5) reports the ``<target>/aidw/config.yaml`` path, its
resolved ``schema_version`` and any validation error (§3.4), and ``compat status``
(E8.3) reports the D10 compatibility verdict on its own line (§3.11). ``toolkit version``
reports ``aidw.__version__`` as an environment check, so it survives the repo early
return the same way ``git version`` does.

See ``design.md`` §12/§14 and ``docs/migration/EXTRACTION.md``
§3.1/§3.2/§3.4/§3.10/§3.11.
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

from aidw import __version__, inventory
from aidw.layout import LayoutError, check_layout
from aidw.paths import (
    BareRepositoryError,
    RepoNotFoundError,
    TargetRepo,
    ToolkitPaths,
    WorkspacePaths,
    toolkit_root,
)
from aidw.prompts import (
    is_gates_like_heading,
    is_recognised_gates_heading,
    read_conventions_sources,
)
from aidw.target_config import (
    ERROR,
    TargetConfig,
    check_compatibility,
    format_issues,
    load_target_config,
    resolve_config,
    validate_paths,
)

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

#: How the target-config check renders "no ``aidw/config.yaml``": §3.4's valid default
#: case. Shared by the path and the schema-version column so the wording cannot drift.
NO_TARGET_CONFIG = "none (defaults)"


def _config_source(declared: TargetConfig) -> str:
    """The config path both target-side checks render, or the defaults sentinel.

    Shared by ``target config`` and ``compat status`` (E8.3) so the two lines can never
    disagree about which file the verdict was made against.
    """
    if declared.source_path is None:
        return NO_TARGET_CONFIG
    return str(declared.source_path.resolve())


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


def _check_toolkit_version() -> Check:
    """Report the toolkit version this checkout ships (E8.3, EXTRACTION.md §3.11).

    Informational and always ``OK``: the requirement is that doctor *states* the version
    the compatibility verdict was made against (D10), not that some version is wrong. The
    value is :data:`aidw.__version__` — the same single source the ``aidw --version``
    flag uses (E1.6, design §17 P1) — never a hardcoded literal, a ``git``/``uv``
    shell-out or a ``pyproject.toml`` parse.

    An environment check, so it sits with ``git version`` *before* the
    ``TargetRepo.resolve`` try/except: doctor must still name the version when it is run
    outside any repository (§3.3).
    """
    return Check("toolkit version", OK, __version__)


def _check_target_config(root: Path) -> Check:
    """Report the target repo's ``aidw/config.yaml``: path, schema version, errors.

    EXTRACTION.md §3.4/§3.11 and roadmap E3.5: ``aidw doctor`` validates the target
    config and reports per-value provenance. The config path is composed the way every
    other consumer composes it (``root / "aidw" / "config.yaml"``) and loaded through
    :func:`aidw.target_config.load_target_config`, so a missing file is the valid
    defaults case — ``source_path is None`` and no issues — never a ``FAIL`` (§3.4: "a
    target repo with no ``aidw/`` folder is valid").

    The failure decision is the loader's ``ERROR`` issues unioned with
    :func:`aidw.target_config.validate_paths` (E3.7: a §3.4 read-path that does not
    exist, named by the config *or* by a toolkit default). It never comes from the merged
    output: ``resolve_config``'s contract is that callers refuse a broken config *before*
    resolving, so the config is resolved exactly once, after the loader refusal, and the
    same resolution feeds the path check and the schema-version line — the two cannot
    disagree about what the config resolved to. The loader's messages already name the
    full field path (``unknown key paths.foo``), and :func:`format_issues` is the same
    formatter ``aidw config show`` and the workflow preflights use, so the report names
    the field rather than paraphrasing it.

    The D10 compatibility verdict is **not** part of this decision (E8.3): it moved to
    :func:`_check_compat` so the roadmap's three items are three named checks and
    :func:`aidw.target_config.check_compatibility` is evaluated exactly once. Unioning it
    here as well would report the same incompatible ``schema_version``/``requires_toolkit``
    on two lines.

    Read-only: one file read, one ``exists()`` per set read-path, nothing written (§3.1).
    ``ensure_write_targets`` is deliberately **not** called here — doctor must never
    create a directory a stage has not asked for.
    """
    config_path = root / "aidw" / "config.yaml"
    declared = load_target_config(config_path)

    issues = [issue for issue in declared.issues if issue.level == ERROR]

    source = _config_source(declared)
    if issues:
        return Check("target config", FAIL, f"{source}\n{format_issues(issues)}")

    # E3.7: resolved exactly once, after the loader refusal above, and reused for both the
    # read-path check and the schema-version line. The path issues join the same list so
    # the FAIL/OK decision stays a single one (§3.4 "Configured read-paths must exist").
    resolved = resolve_config(declared)
    issues.extend(validate_paths(resolved, root))
    if issues:
        return Check("target config", FAIL, f"{source}\n{format_issues(issues)}")

    # Resolved, not ``declared.schema_version`` (roadmap: "the resolved schema version"):
    # the two are equal today only because ``schema_version`` has no toolkit default.
    schema_version = resolved["schema_version"]
    # Review follow-up #78: an unset resolved ``schema_version`` only happens when there
    # is no config file at all, so ``source`` is already the NO_TARGET_CONFIG sentinel;
    # appending the suffix would render the sentinel twice ("none (defaults) — schema
    # version none (defaults)"). Render it once.
    if not schema_version.is_set:
        return Check("target config", OK, source)
    return Check(
        "target config",
        OK,
        f"{source} — schema version {schema_version.value} ({schema_version.source})",
    )


def _check_compat(root: Path) -> Check:
    """Report the D10 compatibility verdict for the target's declared config (E8.3).

    EXTRACTION.md §3.11: the toolkit refuses an unsupported ``schema_version`` or an
    unsatisfied ``requires_toolkit``. :func:`aidw.target_config.check_compatibility` is
    the single decision source and is evaluated here **once** — the verdict was moved
    out of :func:`_check_target_config`, not copied, so an incompatible config is one
    FAIL on one named line instead of two.

    A missing ``aidw/config.yaml`` is §3.4's valid defaults case: the loader returns
    ``source_path is None`` with no issues, so :func:`check_compatibility` returns
    ``[]`` and this check is ``OK``. That is why the file is **not** pre-tested with
    ``exists()``/``is_file()``: a pre-check would turn every config-less repo red. When
    the verdict is a refusal, the messages are surfaced through :func:`format_issues`
    verbatim — they already name ``schema_version``/``requires_toolkit`` and the reason.

    Read-only: one file read, nothing written (§3.1). The toolkit version is passed in
    from :data:`aidw.__version__` (E1.6), never hardcoded, so the verdict cannot be
    claimed for a version other than the one this package ships.
    """
    declared = load_target_config(root / "aidw" / "config.yaml")
    issues = check_compatibility(declared, toolkit_version=__version__)
    if issues:
        return Check("compat status", FAIL, format_issues(issues))
    return Check(
        "compat status",
        OK,
        f"{_config_source(declared)} — toolkit {__version__} is compatible",
    )


def _check_architecture_trigger(root: Path) -> Check:
    """Warn when ``I4 update-architecture`` is enabled with an **empty** path set (S1.2).

    ``I4`` carries ``when=paths-changed`` with the registry default ``docs/architecture``
    (design §17 Z12). A repo that declares ``when_paths: []`` **replaces** that default
    (the S1.1/S1.2 override rule; the two never merge), which is the one way the effective
    set is empty — and an empty set means the stage runs unconditionally, defeating the
    path gate. That is worth a WARN, not a FAIL: the run still works, it just buys an
    architecture agent invocation on every change.

    The warning fires only when the stage is **enabled**: a repo with ``enabled: false``
    has no write-target to justify one, and an absent ``when_paths`` keeps the default, so
    neither warns. A non-empty declaration is the operator's own trigger set and needs no
    advice. Read-only: one config load, nothing written (§3.1).

    Undeclared is not disabled (review follow-up #168, PR #166): a repo with **no declared
    ``workflows.implement.stages`` list** — no config file at all, or an ``implement``
    mapping without the key — runs the registry expansion, where ``I4`` is repo-optional
    (:data:`aidw.stage_registry.REPO_OPTIONAL_IDS`) with default ``enabled: true``, so the
    toolkit default ``docs/architecture`` trigger is in force and the check says so.
    "Not enabled" stays reserved for the only cases where it is true: a declared list
    that omits ``I4`` (the whole-list override, §3.4) or an entry with ``enabled: false``.
    Declared-ness is read from ``WorkflowConfig._declared`` — the same key set the config
    round-trip and the resolution merge use — never from stage-list truthiness, because a
    declared ``stages: []`` is a declaration the validator owns and an undeclared list
    leaves ``workflow.stages`` empty either way.
    """
    declared = load_target_config(root / "aidw" / "config.yaml")
    workflow = declared.workflows.get("implement")
    entry = None
    if workflow is not None:
        entry = next((stage for stage in workflow.stages if stage.id == "I4"), None)
    if workflow is None or "stages" not in workflow._declared:
        return Check(
            "architecture trigger",
            OK,
            "I4 update-architecture uses the toolkit default docs/architecture",
        )
    if entry is None or not entry.enabled:
        return Check("architecture trigger", OK, "I4 update-architecture not enabled")
    if entry.when_paths is None:
        return Check(
            "architecture trigger",
            OK,
            "I4 update-architecture uses the toolkit default docs/architecture",
        )
    if entry.when_paths:
        return Check(
            "architecture trigger",
            OK,
            "I4 update-architecture declares " + ", ".join(entry.when_paths),
        )
    return Check(
        "architecture trigger",
        WARN,
        "`I4 update-architecture` has `when_paths: []`, so it runs unconditionally; "
        "declare docs/architecture plus any diagram-input paths in its when_paths, or "
        "remove the empty list to use the toolkit default.",
    )


def _check_gates_heading(root: Path) -> Check:
    """Warn when a conventions source publishes a gates-like heading nothing recognises.

    C1.2 (design §8.1): the evidence bundle reads gate commands from a ``## Gates`` or
    ``## Gate commands`` section (:func:`aidw.prompts.GATES_HEADINGS`, matched by prefix)
    plus the target's configured top-level ``gates_heading``. A repo that writes
    ``## Gate Commands`` (capital C) or ``## Verification gates`` and declares nothing gets
    an ``unavailable`` gate section in the bundle — a normal degraded state, never a failed
    run. This check is the diagnosis: it names the source file and the heading, so the
    operator can rename it or declare it, instead of wondering why the bundle is empty.

    ``WARN``, never ``FAIL`` and never an exit-code decision: a non-standard heading still
    works (the bundle degrades), so this is advice, not a broken prerequisite. Recognition
    is the bundle reader's own predicate with the same ``startswith`` prefix rule
    (:func:`aidw.prompts.is_recognised_gates_heading`), never ``==`` — otherwise the
    toolkit's own suffixed ``## Gates — run exactly these, and only these`` would warn while
    every bare-heading test stayed green.

    The configured ``gates_heading`` is loaded from this ``root`` (the target, never the
    toolkit root) **before** deciding a heading is unrecognised, so a repo that declares its
    heading is not warned. A missing/unreadable config and a missing/unreadable source both
    degrade to "nothing to report": :func:`aidw.target_config.load_target_config` returns
    an unset field for those, and :func:`aidw.prompts.read_conventions_sources` skips the
    source. Read-only: one config load and the conventions reads, nothing written (§3.1).
    """
    declared = load_target_config(root / "aidw" / "config.yaml")
    configured = declared.gates_heading

    findings: list[str] = []
    for relative, text in read_conventions_sources(root):
        for line in text.splitlines():
            if not is_gates_like_heading(line):
                continue
            if is_recognised_gates_heading(line, configured):
                continue
            findings.append(f"`{relative}`: `{line.strip()}`")

    if not findings:
        return Check("gates heading", OK, "every gates-like heading is recognised")
    return Check(
        "gates heading",
        WARN,
        "unrecognised gate heading(s): "
        + "; ".join(findings)
        + " — rename to `## Gates` or `## Gate commands`, or declare the heading "
        "verbatim (including the `## ` prefix) as the top-level `gates_heading` key.",
    )


def _check_prompts(aidt: Path) -> Check:
    # Toolkit defaults only (E7.5 requirement 7): the resolved-per-target half lives in
    # ``aidw prompts check``, which knows the target; doctor stays toolkit-side.
    issues = inventory.check_defaults(aidt)
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
        # The guard's OK spans two layouts with opposite membership facts: the supported
        # bare + sibling-worktree model (workspace root not registered at all) and the
        # single-checkout plain clone (workspace root IS the sole, deliberately exempted
        # self-entry — check_layout's len == 1 gate). Echo the guard's outcome instead of
        # asserting non-membership, which is false for the latter (review follow-up #63).
        checks.append(
            Check(
                "control worktree",
                OK,
                f"clone-of-a-worktree guard passed: {workspace.workspace_root} "
                "is not a second registered worktree",
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
        # Environment checks run outside any repository, so the git floor and the
        # toolkit version are verified before the target is resolved (§3.2/§3.11).
        _check_git_version(),
        _check_toolkit_version(),
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
    # After the early returns above: the config lives in the target's *working tree*, so
    # a bare directory must short-circuit first (it has no ``aidw/`` to read).
    checks.append(_check_target_config(target.root))
    checks.append(_check_compat(target.root))
    checks.append(_check_architecture_trigger(target.root))
    # C1.2: advisory only — the bundle degrades, so an unrecognised heading is a WARN.
    checks.append(_check_gates_heading(target.root))

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
