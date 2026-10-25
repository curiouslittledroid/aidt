"""GitHub access for AIDW (design §8.3, §13).

Safety rule: AIDT **reads** GitHub only through ``gh`` (read-only, structured JSON) and
**writes** only through AIDT's bundled Python scripts under
``aidt/prompts/scripts/review-followup/``. Python never calls ``gh issue create``,
``gh pr comment``, or a mutating ``gh api`` method directly.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

GH = "gh"

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


def _run(argv: list[str], repo: Path, timeout: int = DEFAULT_TIMEOUT) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            argv,
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
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


def run_script(argv: list[str], repo: Path, timeout: int = 600) -> ScriptResult:
    code, out, err = _run(argv, repo, timeout)
    return ScriptResult(argv=argv, exit_code=code, stdout=out, stderr=err)


def select_followups(
    aidt: Path, repo: Path, pr: int, timeout: int = DEFAULT_TIMEOUT
) -> ScriptResult:
    """Read-only ``review_followup.py select`` for the PR's next approved child.

    Exit code ``3`` means there is no available child; the stdout still carries JSON
    (``selected: null`` plus the skipped reasons).
    """
    script = script_path(aidt, FOLLOWUP_SCRIPT)
    argv = build_followup_argv(script, "select", pr)
    return run_script(argv, repo, timeout)


def verify_approvals(
    aidt: Path, repo: Path, pr: int, timeout: int = DEFAULT_TIMEOUT
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
    result = run_script(argv, repo, timeout)
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
