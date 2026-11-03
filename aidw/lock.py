"""One run per worktree: the cross-process run lock (EXTRACTION.md §3.2/§3.10, E2.7).

``§3.2`` specifies *one run per worktree*, and ``§3.10`` places the locks in the per-repo
**state root** (``<state root>/locks``) — never in a target repo or a worktree, so
``git worktree remove`` can never delete one mid-run and nothing generated is ever written
into a target repo (``§3.1``, design §13).

The key is the **resolved worktree path**, not a branch name. ``§3.10``'s
``<branch>.lock`` is shorthand that is only valid under the one-branch-one-worktree fact
(``§3.2``); a detached-HEAD worktree has no branch at all, so keying by branch would let it
bypass the lock. Two different worktrees therefore never share a lock file, and a worktree
path (which contains ``/``) is encoded into one filesystem-safe filename by
:func:`lock_filename`.

Mechanism (prompt-fixed by E2.7). ``fcntl.flock`` with ``LOCK_EX | LOCK_NB`` on a lock file
opened **fresh per acquire**:

* ``flock`` is per open file description, so a cached module-level fd would let two threads
  in one process both "acquire" while a real second process is still excluded — open fresh
  every time.
* the kernel releases an ``flock`` when the holding process dies, so there is no stale-lock
  cleanup and no ``O_CREAT|O_EXCL`` + PID-marker scheme that a crashed run would leave
  behind to block every later run.
* ``LOCK_NB`` makes a held lock fail fast instead of hanging a non-interactive ``aidw``
  run (the same fail-fast convention as :mod:`aidw.git`).

The lock is a filesystem mutex, not recorded state: ``state.json`` is unchanged, and the
lock file itself is never unlinked (unlinking would race a second acquirer onto a new inode
while the first still holds the old one). The lock file keeps the holder's pid as a
diagnostic only — the presence of the file never means "held".

Deliberately **not** this module's concern: :data:`aidw.runner._STATE_LOCK` serialises
``state.json`` writes between concurrent *stages inside one run*, and ``--parallel`` means
concurrent stages within one worktree. ``§3.2``: "do not conflate the two" — this lock is
one-per-run, held for the whole workflow, and cross-process.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
from pathlib import Path

#: Subdirectory of the per-repo state root that holds the run locks (EXTRACTION.md §3.10).
#: This is the *only* lock location: no lock may live under a target repo or worktree.
LOCKS_DIRNAME = "locks"

#: Characters a lock filename may contain. Everything else is folded to ``-`` so a
#: worktree path (``/``-separated, possibly with spaces or non-ASCII) stays one component.
_SLUG_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

#: Cap on the human-readable part of the filename; the digest carries the uniqueness, and
#: the whole name must stay well under the usual 255-byte component limit.
_SLUG_MAX = 40


class LockHeldError(RuntimeError):
    """Another live run already holds this worktree's lock (E2.7 req 4).

    Carries both the worktree path and the lock file so the refusal names what the operator
    needs to act on; ``run()`` prints the message and returns exit 4 (a preflight/safety
    refusal, design §14) *before* ``create_run``, so a refusal leaves no run state behind.
    """

    def __init__(self, worktree: Path, path: Path) -> None:
        self.worktree = worktree
        self.path = path
        super().__init__(
            f"another aidw run is already active in worktree {worktree} "
            f"(it holds {path}). One run per worktree (EXTRACTION.md §3.2): wait for "
            "that run to finish, or re-run with --resume once it has stopped."
        )


def locks_dir(state_root: Path) -> Path:
    """``<state root>/locks`` — the single run-lock directory (EXTRACTION.md §3.10)."""
    return Path(state_root) / LOCKS_DIRNAME


def lock_filename(worktree: Path) -> str:
    """Deterministic, filesystem-safe lock filename for a worktree path.

    Pure: the argument is resolved but nothing is read or written. The same resolved
    worktree path always yields the same name (so two processes agree), and two different
    worktree paths never share one — uniqueness comes from the full SHA-256 of the resolved
    path, while the leading slug keeps ``ls <state root>/locks`` readable. The result is a
    single path component: no ``/``, whatever characters the worktree's name contains.
    """
    resolved = Path(worktree).resolve()
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
    slug = _SLUG_UNSAFE.sub("-", resolved.name).strip("-.")[:_SLUG_MAX] or "worktree"
    return f"{slug}-{digest}.lock"


def lock_path(state_root: Path, worktree: Path) -> Path:
    """The lock file for ``worktree`` under ``state_root`` (deterministic)."""
    return locks_dir(state_root) / lock_filename(worktree)


class RunLock:
    """A held run lock.

    Created only by :func:`acquire`; released by :meth:`release`, or by the ``with`` form.
    ``release`` is idempotent so a ``finally`` cannot mask the exit code it is preserving.
    """

    __slots__ = ("worktree", "path", "_fd")

    def __init__(self, worktree: Path, path: Path, fd: int) -> None:
        self.worktree = worktree
        self.path = path
        self._fd: int | None = fd

    @property
    def held(self) -> bool:
        """Whether this object still holds the flock."""
        return self._fd is not None

    def release(self) -> None:
        """Release the flock and close the descriptor; a no-op when already released.

        The lock file is deliberately left on disk: ``flock`` is released by the kernel
        here (and on process death), so an empty leftover file holds nothing. Unlinking it
        would let a second acquirer create a new inode while this one was still held.
        """
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def __enter__(self) -> "RunLock":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        state = "held" if self.held else "released"
        return f"RunLock({str(self.worktree)!r}, {state})"


def acquire(state_root: Path, worktree: Path) -> RunLock:
    """Take the exclusive, non-blocking run lock for ``worktree``.

    Raises :class:`LockHeldError` immediately when another live run holds it (no waiting:
    a held lock means a real concurrent run, and ``aidw`` is non-interactive). Any other
    ``OSError`` from ``flock`` propagates: a lock that cannot be taken must never be
    silently treated as taken, and the caller then fails closed rather than running
    unguarded alongside a peer.

    The descriptor is opened fresh here on every call (never cached) so that exclusion
    holds between two threads of one process as well as between two processes.
    """
    resolved = Path(worktree).resolve()
    path = lock_path(state_root, resolved)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise LockHeldError(resolved, path) from None
    except OSError:
        os.close(fd)
        raise
    _write_holder_pid(fd)
    return RunLock(resolved, path, fd)


def _write_holder_pid(fd: int) -> None:
    """Record the holder's pid in the lock file, for diagnosis only.

    Best effort: this is never read to decide whether the lock is held (``flock`` is the
    only truth), so a failure here must not fail an acquisition that has already succeeded.
    """
    try:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
    except OSError:
        pass
