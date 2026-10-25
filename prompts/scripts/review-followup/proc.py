"""Low-level process helpers.

Every external command is executed with an argument array and no shell, so
comment bodies, issue titles, and file paths are never re-interpreted by a
shell. This removes the quoting hazards of inline ``gh --comment "$(cat ...)"``
shell usage: backticks, apostrophes, ``$``, and newlines are all inert here.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


class UsageError(Exception):
    """A caller error (bad flags, unmet precondition). Safe to print verbatim.

    ``exit_code`` defaults to 2; callers may pass a more specific code from
    :mod:`constants`.
    """

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class CommandError(Exception):
    """A failure of an external command (``gh``, ``git``)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class ProbeResult:
    ok: bool
    status: int | None
    stdout: str
    stderr: str


def probe(file: str, args: list[str], input: str | None = None) -> ProbeResult:
    """Run a command and capture its outcome without raising."""
    try:
        completed = subprocess.run(
            [file, *args],
            input=input,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        return ProbeResult(ok=False, status=None, stdout="", stderr=str(error))
    return ProbeResult(
        ok=completed.returncode == 0,
        status=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def run(file: str, args: list[str], input: str | None = None) -> str:
    """Run a command, raising :class:`CommandError` on a non-zero exit."""
    result = probe(file, args, input)
    if not result.ok:
        detail = (result.stderr or result.stdout).strip() or f"exit status {result.status}"
        raise CommandError(f"{file} {' '.join(args)} failed: {detail}", result.status)
    return result.stdout


def git_branch() -> str:
    """Current git branch name."""
    return run("git", ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
