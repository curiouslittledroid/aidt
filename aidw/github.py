"""GitHub access for AIDW (design §8.3, §13).

Safety rule: AIDT **reads** GitHub only through ``gh`` (read-only, structured JSON) and
**writes** only through AIDT's bundled Python scripts under
``aidt/prompts/scripts/review-followup/``. Python never calls ``gh issue create``,
``gh pr comment``, or a mutating ``gh api`` method directly.

This module is also the toolkit side of the **config handoff** to those scripts (E6.1,
EXTRACTION.md §3.4/§3.9, D5): :func:`serialize_github_config` turns a resolved
:class:`~aidw.target_config.ResolvedConfig`'s ``github.markers.*``/``github.labels.*``
leaves into the JSON one environment variable carries
(:data:`aidw.paths.REVIEW_FOLLOWUP_CONFIG_ENV_VAR`). Both invocation seams use this one
serializer — the stage environment (:func:`aidw.runner.run_stage`, so agent-invoked
scripts inherit it) and aidw's own script runs (:func:`_run`) — because a repository whose
publisher writes one marker while ``select`` searches for another silently finds no parent
issue.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from aidw.paths import REVIEW_FOLLOWUP_CONFIG_ENV_VAR

if TYPE_CHECKING:  # stdlib-only at runtime: the annotation below is never evaluated.
    from aidw.target_config import ResolvedConfig

GH = "gh"

#: The three marker names, in ``constants.py``/``§3.4`` order. A typo here would ask the
#: scripts for a template they do not validate, so the serializer refuses a missing leaf
#: instead of emitting a partial payload.
MARKER_NAMES = ("parent", "child", "summary")

#: The two fields every ``github.labels.<name>`` entry carries (§3.4, D5).
LABEL_FIELDS = ("color", "description")

_MARKERS_PREFIX = "github.markers."
_LABELS_PREFIX = "github.labels."

SCRIPT_DIR = ("prompts", "scripts", "review-followup")
PUBLISH_SCRIPT = "publish_review_followups.py"
FOLLOWUP_SCRIPT = "review_followup.py"

DEFAULT_TIMEOUT = 120

#: ``review_followup.py`` exit codes.
EXIT_OK = 0
EXIT_VERIFY_FAILED = 1
EXIT_ERROR = 2
EXIT_NONE_AVAILABLE = 3
EXIT_CONFLICT = 4

_PR_FIELDS = "number,url,state,isDraft,baseRefName,headRefName,title"

_PARENT_LINE = re.compile(r"^Parent issue:\s*(\S+)", re.MULTILINE)
_CHILD_LINE = re.compile(
    r"^(F\d+):\s*(created|updated|preserved-open|preserved-closed)\s+#(\d+)\s+(\S+)",
    re.MULTILINE,
)
_SUMMARY_LINE = re.compile(r"^Summary comment:\s*(\S+)", re.MULTILINE)
_URL_NUMBER = re.compile(r"/(\d+)/?$")


@dataclass
class ScriptResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def gh_available() -> bool:
    return shutil.which(GH) is not None


# --------------------------------------------------------------------------- #
# Config handoff (E6.1)
# --------------------------------------------------------------------------- #


def serialize_github_config(config: ResolvedConfig) -> str:
    """Serialize a resolved config's GitHub leaves as the scripts' handoff JSON (E6.1).

    The payload is exactly what ``prompts/scripts/review-followup/gh.py`` parses:

    .. code-block:: json

        {"markers": {"parent": "…", "child": "…", "summary": "…"},
         "labels": {"<name>": {"color": "…", "description": "…"}}}

    Label names are **enumerated from the resolved entries**, never a hardcoded list: a
    repo-added label resolves a leaf like any other, and ``resolve_config`` merges the
    seeded definitions underneath the declared ones, so the payload always carries the
    fully-resolved set (a repo that overrides one colour still sends the other five).

    The parameter is a ``ResolvedConfig``, read through its ``Mapping`` interface (a
    dotted path -> ``ResolvedValue``); the import is ``TYPE_CHECKING``-only so this module
    stays a stdlib-only leaf at runtime.

    A missing/unset marker leaf is a ``ValueError``, not an omission: aidw always resolves
    the three from :data:`~aidw.target_config.TOOLKIT_DEFAULTS`, so a hole means the caller
    passed a hand-built config, and emitting it would make the script fail closed later
    with a much less specific message. Pure: no I/O, no mutation.
    """
    entries = config
    markers: dict[str, str] = {}
    for name in MARKER_NAMES:
        entry = entries.get(_MARKERS_PREFIX + name)
        value = getattr(entry, "value", None)
        if entry is None or value is None:
            raise ValueError(
                f"cannot serialize the review-followup config: `github.markers.{name}` "
                "did not resolve"
            )
        markers[name] = str(value)

    labels: dict[str, dict[str, str]] = {}
    for path in entries:
        if not path.startswith(_LABELS_PREFIX):
            continue
        name, _, key = path[len(_LABELS_PREFIX) :].rpartition(".")
        if not name or key not in LABEL_FIELDS:
            continue
        entry = entries[path]
        value = getattr(entry, "value", None)
        if value is None:
            continue
        labels.setdefault(name, {})[key] = str(value)

    # A label with only one of its two fields would be rejected by the script anyway; do
    # it here, where the message can name the unresolved leaf.
    for name, definition in labels.items():
        missing = [key for key in LABEL_FIELDS if key not in definition]
        if missing:
            raise ValueError(
                f"cannot serialize the review-followup config: "
                f"`github.labels.{name}.{missing[0]}` did not resolve"
            )

    return json.dumps({"markers": markers, "labels": labels})


# --------------------------------------------------------------------------- #
# Process execution
# --------------------------------------------------------------------------- #


def _run(
    argv: list[str],
    repo: Path,
    timeout: int = DEFAULT_TIMEOUT,
    *,
    config: ResolvedConfig | None = None,
) -> tuple[int, str, str]:
    """Run ``argv`` in ``repo``; with ``config``, carry the resolved GitHub handoff.

    ``config=None`` leaves :data:`REVIEW_FOLLOWUP_CONFIG_ENV_VAR` out of the child
    environment entirely — the scripts then use their frozen fallbacks, which is
    byte-identical to the toolkit defaults (E6.1). The read-only ``gh`` helpers
    (:func:`repo_slug`/:func:`pr_view`) never pass it; only the bundled-script callers do.
    """
    env = {
        **os.environ,
    }
    if config is None:
        env.pop(REVIEW_FOLLOWUP_CONFIG_ENV_VAR, None)
    else:
        env[REVIEW_FOLLOWUP_CONFIG_ENV_VAR] = serialize_github_config(config)
    try:
        result = subprocess.run(
            argv,
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"timed out after {timeout}s: {exc}"
    return result.returncode, result.stdout, result.stderr


# --------------------------------------------------------------------------- #
# Read-only helpers
# --------------------------------------------------------------------------- #


def repo_slug(repo: Path) -> str | None:
    """``owner/name`` for the repository, or ``None`` when ``gh`` fails."""
    code, out, _ = _run(
        [GH, "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], repo
    )
    return out.strip() if code == 0 and out.strip() else None


def pr_view(repo: Path, pr: int) -> dict | None:
    """Structured PR metadata via ``gh pr view`` (read-only)."""
    code, out, _ = _run([GH, "pr", "view", str(pr), "--json", _PR_FIELDS], repo)
    if code != 0:
        return None
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


# --------------------------------------------------------------------------- #
# Bundled scripts
# --------------------------------------------------------------------------- #


def script_path(aidt: Path, name: str) -> Path:
    return aidt.joinpath(*SCRIPT_DIR, name)


def build_publish_argv(
    script: Path, pr: int | None, manifest: Path, *, dry_run: bool = False
) -> list[str]:
    argv = [sys.executable, str(script)]
    if pr is not None:
        argv += ["--pr", str(pr)]
    argv += ["--input", str(manifest)]
    if dry_run:
        argv.append("--dry-run")
    return argv


def build_followup_argv(
    script: Path, command: str, pr: int | None, **flags: str | bool | None
) -> list[str]:
    """Build argv for ``review_followup.py <command>`` (used by ``aidw fix``)."""
    argv = [sys.executable, str(script), command]
    if pr is not None:
        argv += ["--pr", str(pr)]
    for name, value in flags.items():
        flag = "--" + name.replace("_", "-")
        if isinstance(value, bool):
            if value:
                argv.append(flag)
        elif value is not None:
            argv += [flag, str(value)]
    return argv


def run_script(
    argv: list[str],
    repo: Path,
    timeout: int = 600,
    *,
    config: ResolvedConfig | None = None,
) -> ScriptResult:
    code, out, err = _run(argv, repo, timeout, config=config)
    return ScriptResult(argv=argv, exit_code=code, stdout=out, stderr=err)


def select_followups(
    aidt: Path,
    repo: Path,
    pr: int,
    timeout: int = DEFAULT_TIMEOUT,
    *,
    config: ResolvedConfig | None = None,
) -> ScriptResult:
    """Read-only ``review_followup.py select`` for the PR's next approved child.

    Exit code ``3`` means there is no available child; the stdout still carries JSON
    (``selected: null`` plus the skipped reasons). ``config`` carries the resolved
    ``github.markers``/``github.labels`` so the search uses the same parent marker the
    publisher writes (E6.1); ``None`` means "do not set the handoff" (toolkit defaults).
    """
    script = script_path(aidt, FOLLOWUP_SCRIPT)
    argv = build_followup_argv(script, "select", pr)
    return run_script(argv, repo, timeout, config=config)


def verify_approvals(
    aidt: Path,
    repo: Path,
    pr: int,
    timeout: int = DEFAULT_TIMEOUT,
    *,
    config: ResolvedConfig | None = None,
) -> str | None:
    """Read-only postcondition for the approve stage: every open child is approved.

    A zero exit from the approver agent is not evidence that the GitHub writes
    happened — it can stop and report a problem in its final message and still exit 0
    (design §10). This re-reads the state through ``approve --dry-run``, which performs
    no writes, and reports an error when any open child would still be changed.

    Returns ``None`` when the postcondition holds, otherwise a human-readable error.
    """
    script = script_path(aidt, FOLLOWUP_SCRIPT)
    argv = build_followup_argv(script, "approve", pr, dry_run=True)
    result = run_script(argv, repo, timeout, config=config)
    if result.exit_code != 0:
        detail = (result.stderr or result.stdout).strip()[:300]
        return (
            f"could not read approval state (approve --dry-run exit "
            f"{result.exit_code}): {detail}"
        )
    payload = parse_json_output(result.stdout)
    if payload is None:
        return "approve --dry-run returned unparseable output"
    pending = [
        child
        for child in payload.get("children") or []
        if child.get("action") == "would-approve"
    ]
    if pending:
        numbers = ", ".join(f"#{child.get('number')}" for child in pending)
        return f"open children still awaiting approval: {numbers}"
    return None


def parse_json_output(stdout: str) -> dict | None:
    """Parse the JSON that ``review_followup.py`` emits on stdout."""
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _issue_ref(url: str) -> dict[str, object]:
    number = _URL_NUMBER.search(url)
    return {"url": url, "number": int(number.group(1)) if number else None}


def parse_publish_output(stdout: str) -> dict[str, object]:
    """Extract the parent/child issue references from the publisher's output.

    The publisher prints human-readable lines (``Parent issue: <url>``,
    ``F1: created #12 <url>``); this turns them back into structured references so the
    run state can record what was created.
    """
    result: dict[str, object] = {"parent_issue": None, "child_issues": {}, "summary_comment": None}
    parent = _PARENT_LINE.search(stdout)
    if parent:
        result["parent_issue"] = _issue_ref(parent.group(1))
    summary = _SUMMARY_LINE.search(stdout)
    if summary:
        result["summary_comment"] = _issue_ref(summary.group(1))
    children: dict[str, dict[str, object]] = {}
    for match in _CHILD_LINE.finditer(stdout):
        finding_id, action, number, url = match.groups()
        children[finding_id] = {**_issue_ref(url), "action": action, "number": int(number)}
    result["child_issues"] = children
    return result
