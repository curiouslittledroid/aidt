"""Whole-repo verification gates: run once per tree, then cite (EXTRACTION.md E4.8).

``test`` (I2), ``record`` (I5) and the implementer each run the full suite against the
same tree, and ``pr`` (I6) is the fourth payer. This module records every gate outcome
against the identity of the *tree* it gated, so a later stage in the same run can cite
that outcome instead of buying the same answer again.

**The identity is content, not commit history.** It hashes every path whose content
differs from the base branch, plus every untracked non-ignored path, read from the
working tree. ``HEAD`` is deliberately *not* part of it: ``/pr`` commits the change set
it just gated, and committing a verified tree must not invalidate its own verification.
Two consequences follow, and both are wanted:

- any content change — a new untracked file, a one-character edit, an execution-bit
  flip, a deletion — changes the identity, so the gate re-runs;
- a change invisible to content — ``git add``, a rebase onto an identical tree, a
  commit — does not, so the gate is cited.

**What it does not cover:** the gitignored environment a gate depends on (``.venv``,
``node_modules``, freshly installed dependencies). A gate that passed and then had the
environment rebuilt underneath it may legitimately disagree with the recorded outcome.
``--force`` exists for that case, and a citation always carries its origin — stage,
command and timestamp — so the reader can judge it rather than trust a bare number.

**Declared scope.** A whole-tree identity is sound but rarely reusable in the real
implement chain: ``record`` (I5) writes its results document *after* it runs the gate, so
the tree ``pr`` (I6) delivers is never byte-identical to the tree ``test`` (I2) gated,
and the suite would be bought again every stage. So a gate may *declare* that its command
cannot read certain paths (``--ignore docs/implementation-results``) — a declaration made
by the stage that ran the gate, stored in the outcome, and part of what must match before
anything is cited. Nothing is inferred: if a stage declares nothing, the identity is the
whole tree. The rule for a repo is the same one that governs its gate commands (R14) — it
owns them — and it is written down in the prompts: ignore the documents the *other stages
write*, never source, tests, config or lockfiles. Every citation prints its scope, so an
over-broad declaration is visible in the record rather than buried in it.

**Fail closed.** When the base branch cannot be resolved (a repo whose default branch is
not ``main``, or a repo with no commits), or when the change set is too large to hash
cheaply, the identity is ``None``: nothing is cited and nothing is recorded, and the gate
simply runs, exactly as it did before this module existed. Reuse additionally requires the
*same run*: an outcome from an earlier run is not evidence about this one, so it is never
cited.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from aidw import git
from aidw.state import (
    GATE_FAILED,
    PASSED,
    GateOutcome,
    RunState,
    utcnow_iso,
)

#: Branch the change set is measured against. The configured ``repo.base_branch`` (E3)
#: replaces this; until then ``main`` is the same assumption ``pr.md`` and
#: ``workflows/implement.py`` already make.
BASE_DEFAULT = "main"

#: Characters of a tree identity shown in messages. The full digest is stored.
TREE_DISPLAY = 12

#: Lines of the gate's output echoed back. The tail carries the summary line for a test
#: runner, and keeping it short keeps a gate from flooding the agent's context.
DEFAULT_TAIL = 40

#: The summary line is one line, for state.json and for a results-table row.
SUMMARY_LIMIT = 300

#: Identity budget. An enormous change set costs a directory listing and a cheap digest,
#: not minutes of hashing: a target repo that does not gitignore its ``node_modules`` has
#: hundreds of thousands of untracked files, and no gate should stall on hashing them.
#: Over budget the identity is ``None``, which fails safe — the gate simply runs.
MAX_IDENTITY_PATHS = 5000
MAX_IDENTITY_BYTES = 256 * 1024 * 1024


def short_tree(tree: str | None) -> str:
    return (tree or "")[:TREE_DISPLAY]


# --------------------------------------------------------------------------- #
# Tree identity
# --------------------------------------------------------------------------- #


def tree_identity(
    repo_root: Path,
    *,
    base: str = BASE_DEFAULT,
    exclude: Sequence[Path] = (),
    ignore: Sequence[str] = (),
) -> str | None:
    """Hash the content of the change set this tree carries, or ``None`` if unknown.

    ``exclude`` names paths that must not contribute whatever their git state; callers
    pass the run's state root, because when ``AIDW_STATE_DIR`` points inside the target
    repo and is not gitignored, the run's own logs would otherwise be part of the change
    set — and every stage writes logs, so no gate would ever be reused.

    ``ignore`` names repo-relative prefixes the *gate* declares it cannot read (see the
    module docstring). Both are removed before hashing, and both travel with the outcome
    so a citation can only match against the same scope.

    Returns ``None`` when the base branch cannot be resolved *or* when the change set
    exceeds ``MAX_IDENTITY_PATHS``/``MAX_IDENTITY_BYTES``. Both mean "cannot prove", and
    both fail safe: the caller runs the gate instead of citing one.
    """
    changed = git.changed_paths(repo_root, base)
    if changed is None:
        return None
    untracked = git.untracked_paths(repo_root)
    prefixes = _relative_prefixes(repo_root, exclude)
    declared = normalise_ignore(ignore)
    paths = sorted(
        p for p in (*changed, *untracked) if not _excluded(p, (*prefixes, *declared))
    )
    if len(paths) > MAX_IDENTITY_PATHS:
        return None

    digest = hashlib.sha256()
    consumed = 0
    for path in paths:
        piece, size = _path_digest(repo_root / path)
        consumed += size
        if consumed > MAX_IDENTITY_BYTES:
            return None
        digest.update(path.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(piece)
        digest.update(b"\0")
    return digest.hexdigest()


def normalise_ignore(values: Sequence[str]) -> tuple[str, ...]:
    """Canonicalise ``--ignore`` prefixes so two invocations can be compared.

    ``docs/x/``, ``./docs/x`` and ``docs/x`` are one declaration, and the result is
    sorted so ordering never matters. Raises :class:`ValueError` for a value that cannot
    be a repo-relative prefix, or that would ignore the whole repository — which would
    make every tree identical and turn the gate into a permanent no-op.
    """
    cleaned: list[str] = []
    for value in values:
        text = (value or "").strip().replace("\\", "/")
        while text.startswith("./"):
            text = text[2:]
        if text in (".", "..") or text.startswith("/") or text.startswith(".."):
            raise ValueError(
                f"invalid --ignore prefix {value!r}: must be a repo-relative path "
                f"such as docs/implementation-results"
            )
        text = text.rstrip("/")
        if not text:
            raise ValueError(
                f"invalid --ignore prefix {value!r}: must be a repo-relative path "
                f"such as docs/implementation-results"
            )
        cleaned.append(text)
    return tuple(sorted(set(cleaned)))


def _relative_prefixes(repo_root: Path, exclude: Sequence[Path]) -> tuple[str, ...]:
    """Repo-relative prefixes for ``exclude`` entries that live inside the repo."""
    root = repo_root.resolve()
    prefixes: list[str] = []
    for entry in exclude:
        if entry is None:
            continue
        try:
            relative = Path(entry).resolve().relative_to(root)
        except ValueError:
            continue
        value = relative.as_posix()
        if value and value != ".":
            prefixes.append(value)
    return tuple(prefixes)


def _excluded(path: str, prefixes: Sequence[str]) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes)


def _path_digest(path: Path) -> tuple[bytes, int]:
    """``(content digest, bytes read)`` for one path, with absent painted distinctly.

    Content only: the execution bit is folded in because git tracks it, a symlink is
    hashed by its target because a gate can depend on where it points, and anything that
    cannot be read is named rather than silently treated as absent. The byte count lets
    the caller stop before hashing a change set no identity should cover.
    """
    try:
        info = path.lstat()
    except OSError:
        return b"absent", 0
    if stat.S_ISLNK(info.st_mode):
        try:
            target = os.readlink(path)
        except OSError:
            return b"symlink:unreadable", 0
        return b"symlink:" + target.encode("utf-8", "surrogateescape"), 0
    if not stat.S_ISREG(info.st_mode):
        return f"other:{info.st_mode:o}".encode(), 0
    digest = hashlib.sha256()
    digest.update(f"exec:{bool(info.st_mode & 0o111)}:".encode())
    consumed = 0
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                consumed += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        return b"unreadable:" + type(exc).__name__.encode(), consumed
    return digest.hexdigest().encode(), consumed


# --------------------------------------------------------------------------- #
# Running a gate
# --------------------------------------------------------------------------- #


@dataclass
class GateResult:
    """What happened when a gate was asked for: a run, or a citation of an earlier run."""

    key: str
    command: list[str]
    status: str
    exit_code: int
    reused: bool = False
    tree: str | None = None
    outcome: GateOutcome | None = None
    output: str = ""
    summary: str = ""
    note: str = ""
    duration_seconds: float | None = None
    ignored: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.status == PASSED

    @property
    def scope(self) -> str:
        """The declared exclusion set, for a citation, or ``""`` when it is empty."""
        return f" [scope excludes: {', '.join(self.ignored)}]" if self.ignored else ""

    @property
    def citation(self) -> str:
        """One line naming the outcome, the tree and who produced it (E4.8's origin)."""
        outcome = self.outcome
        if outcome is None:
            return f"gate '{self.key}' {self.status}"
        detail = f" ({outcome.summary})" if outcome.summary else ""
        verb = "reused" if self.reused else self.status
        return (
            f"{verb}: gate '{outcome.key}' {outcome.status} for tree "
            f"{short_tree(outcome.tree)} at {outcome.at} by stage "
            f"'{outcome.stage}'{detail}{self.scope}"
        )

    def tail_lines(self, limit: int = DEFAULT_TAIL) -> list[str]:
        lines = [line for line in self.output.splitlines() if line.strip()]
        return lines[-limit:]

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "command": list(self.command),
            "status": self.status,
            "exit_code": self.exit_code,
            "reused": self.reused,
            "tree": self.tree,
            "stage": self.outcome.stage if self.outcome else None,
            "at": self.outcome.at if self.outcome else None,
            "summary": self.summary,
            "duration_seconds": self.duration_seconds,
            "note": self.note,
            "ignored": list(self.ignored),
        }


def run_gate(
    key: str,
    command: Sequence[str],
    *,
    repo_root: Path,
    run: RunState | None = None,
    stage: str = "cli",
    base: str = BASE_DEFAULT,
    exclude: Sequence[Path] = (),
    ignore: Sequence[str] = (),
    force: bool = False,
    tail: int = DEFAULT_TAIL,
    timeout: float | None = None,
    cwd: Path | None = None,
) -> GateResult:
    """Run the gate, or cite a passing outcome this run already recorded for this tree.

    Reuse needs all five of: a run to record into, a known tree identity, an outcome with
    the same ``key``, tree and *command*, the same ``ignore`` scope, and a ``passed``
    status. Anything else — a failed previous outcome, a different command under the same
    key, a differently declared scope, no base branch, no run — runs the command. There is
    no path here that turns "unknown" into "skip".

    A run is recorded whatever its exit code, so ``aidw gate list`` shows the failure;
    only a pass is ever cited. The caller owns persisting ``run``: the workflow through
    ``state.save`` (which merges what is already on disk), the CLI through
    ``state.append_gate_outcomes`` (H0.1, design §9.2). Neither path replaces the other's
    rows, so an outcome recorded by a stage's own subprocess is still there — and still
    citable — after the workflow's next save and after the run process exits. The reuse
    rule itself is unchanged: same key, tree, command and declared scope, and ``passed``.
    """
    command = list(command)
    ignored = normalise_ignore(ignore)
    tree = tree_identity(repo_root, base=base, exclude=exclude, ignore=ignored)

    if run is not None and tree is not None and not force:
        prior = run.gate_outcome(key, tree)
        if (
            prior is not None
            and prior.passed
            and prior.command == command
            and tuple(prior.ignored) == ignored
        ):
            return GateResult(
                key=key,
                command=command,
                status=PASSED,
                exit_code=0,
                reused=True,
                tree=tree,
                outcome=prior,
                summary=prior.summary,
                note="this run already passed this gate for this tree",
                duration_seconds=prior.duration_seconds,
                ignored=ignored,
            )

    started = time.monotonic()
    exit_code, output = _execute(command, cwd=cwd or repo_root, timeout=timeout)
    elapsed = round(time.monotonic() - started, 3)
    status = PASSED if exit_code == 0 else GATE_FAILED
    summary = summarise(output)

    outcome = GateOutcome(
        key=key,
        command=command,
        tree=tree or "",
        status=status,
        stage=stage,
        at=utcnow_iso(),
        exit_code=exit_code,
        duration_seconds=elapsed,
        summary=summary,
        ignored=list(ignored),
    )
    if run is not None and tree is not None:
        run.record_gate_outcome(outcome)

    note = ""
    if tree is None:
        note = f"base branch '{base}' is not resolvable, so this outcome is not recorded"
    elif run is None:
        note = "no run to record into (pass --run or set AIDW_RUN_ID)"

    return GateResult(
        key=key,
        command=command,
        status=status,
        exit_code=exit_code,
        reused=False,
        tree=tree,
        outcome=outcome if (run is not None and tree is not None) else None,
        output=output,
        summary=summary,
        note=note,
        duration_seconds=elapsed,
        ignored=ignored,
    )


def _execute(
    command: Sequence[str], *, cwd: Path, timeout: float | None
) -> tuple[int, str]:
    """Run one gate command, returning ``(exit code, combined output)``.

    The command is an argv list run without a shell, so a gate cannot be altered by
    quoting in whatever wrote it down. A repo needing a pipeline or ``&&`` runs each
    side as its own gate — which is also what gives each one its own key.
    """
    if not command:
        return 2, "no command given"
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        return 127, f"command not found: {command[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s: {' '.join(command)}"
    except OSError as exc:
        return 126, f"cannot run {command[0]}: {exc}"
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def summarise(output: str) -> str:
    """The last non-blank line — a test runner's ``439 passed in 97.98s``."""
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped[:SUMMARY_LIMIT]
    return ""


def describe(outcome: GateOutcome, *, indent: str = "  ") -> list[str]:
    """One recorded outcome as printable lines, with its origin and command."""
    seconds = f", {outcome.duration_seconds:g}s" if outcome.duration_seconds else ""
    scope = (
        f", scope excludes {', '.join(outcome.ignored)}" if outcome.ignored else ""
    )
    lines = [
        f"{indent}gate {outcome.key}: {outcome.status} "
        f"(tree {short_tree(outcome.tree)}, stage {outcome.stage}, {outcome.at}{seconds}{scope})"
    ]
    if outcome.summary:
        lines.append(f"{indent}          summary: {outcome.summary}")
    lines.append(f"{indent}          command: {shlex.join(outcome.command)}")
    return lines
