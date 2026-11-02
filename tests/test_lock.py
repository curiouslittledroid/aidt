"""Contract tests for the cross-process run lock (E2.7, EXTRACTION.md §3.2/§3.10).

The lock is the whole point of the task — "one run per worktree" — so the tests are
about *real* exclusion, not about a helper returning ``True``:

* a **second process** holding the lock excludes this one, and its death releases the
  lock with no stale file to clean up (``flock``, not ``O_EXCL`` + PID marker);
* a second **open file description** excludes this one too — a cached module-level fd or
  a ``threading.Lock`` would pass a naive in-process test while two real ``aidw``
  processes both proceeded;
* the key depends on the worktree **path**, so two worktrees never share a lock file and a
  detached-HEAD worktree still gets its own;
* acquiring writes nothing but the lock file, and only under ``<state root>/locks``
  (§3.1: nothing generated is ever written into a target repo).

Fixtures are local by design: E2.9 owns the shared bare+worktree fixture, so these build
a real bare repo with a ``main`` control worktree and real task worktrees, mirroring
``tests/test_worktree_cli.py::_make_bare_with_control``.
"""

from __future__ import annotations

import os
import random
import subprocess
import sys
import textwrap
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from aidw import git, lock
from aidw.paths import toolkit_root

#: Pinned property-test parameters (AGENTS.md §6 asks for an explicit seed and run count
#: so a failure is reproducible rather than "random").
PROPERTY_SEED = 20_270_409
PROPERTY_NUM_RUNS = 200

#: Characters the generated worktree names draw from: path separators, spaces, dots,
#: leading dashes, and non-ASCII — everything a real workspace path may contain.
_PROPERTY_ALPHABET = "ab Z/.-_é漢09"


# ---------------------------------------------------------------------------
# Real git fixtures (EXTRACTION.md §3.2 supported layout)
# ---------------------------------------------------------------------------


def _git_run(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git; the session fixture in ``tests/conftest.py`` supplies the identity."""
    return subprocess.run(
        ["git", *args],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _make_bare_with_control(tmp_path: Path) -> tuple[Path, Path]:
    """Bare repo plus the ``main`` control worktree (the §3.2 bootstrap layout)."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _git_run(seed, "init", "-q", "-b", "main")
    (seed / "f.txt").write_text("x\n", encoding="utf-8")
    _git_run(seed, "add", ".")
    _git_run(seed, "commit", "-qm", "init")
    bare = tmp_path / "bare.git"
    _git_run(tmp_path, "clone", "--bare", "-q", str(seed), str(bare))
    control = tmp_path / "main"
    _git_run(bare, "worktree", "add", "-q", str(control), "main")
    return bare, control


def _add_worktree(control: Path, branch: str) -> Path:
    """Create a task worktree sibling of the bare repo; return its resolved path."""
    path = control.parent / branch
    _git_run(control, "worktree", "add", "-q", "-b", branch, str(path), "main")
    return path.resolve()


def _add_detached_worktree(control: Path, name: str = "detached") -> Path:
    """Create a detached-HEAD worktree — it has no branch to key a lock on."""
    path = control.parent / name
    _git_run(control, "worktree", "add", "-q", "--detach", str(path), "main")
    return path.resolve()


def _snapshot(root: Path) -> set[str]:
    """Every file path under ``root``, relative — a write detector for the purity test."""
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


# ---------------------------------------------------------------------------
# A holder in a *separate process*
# ---------------------------------------------------------------------------

#: Acquire, signal readiness, then die without any Python-level cleanup. ``os._exit``
#: skips ``finally``/``atexit`` handlers and does not close descriptors explicitly, so the
#: release below is the kernel's, exactly as it is for a crashed ``aidw`` run.
_HOLDER_SCRIPT = textwrap.dedent(
    """
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, sys.argv[1])
    from aidw import lock

    guard = lock.acquire(Path(sys.argv[2]), Path(sys.argv[3]))
    print("ready", flush=True)
    sys.stdin.readline()
    os._exit(0)
    """
)


@contextmanager
def _holder(state_root: Path, worktree: Path) -> Iterator[subprocess.Popen[str]]:
    """Run the holder subprocess and wait until it reports the lock is held."""
    env = {**os.environ, "PYTHONPATH": str(toolkit_root())}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _HOLDER_SCRIPT,
            str(toolkit_root()),
            str(state_root),
            str(worktree),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline().strip()
        assert line == "ready", proc.stderr.read() if proc.stderr else line
        yield proc
    finally:
        if proc.poll() is None:
            try:
                assert proc.stdin is not None
                proc.stdin.write("\n")
                proc.stdin.flush()
            except (BrokenPipeError, ValueError):
                pass
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:  # pragma: no cover - keeps the suite from hanging
            proc.kill()
            proc.wait()


# ---------------------------------------------------------------------------
# Key derivation: worktree path, not branch
# ---------------------------------------------------------------------------


def test_each_worktree_gets_its_own_lock_file_under_the_state_root(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    a = _add_worktree(control, "task-a")
    b = _add_worktree(control, "task-b")
    detached = _add_detached_worktree(control)
    state_root = tmp_path / "state"

    paths = {worktree: lock.lock_path(state_root, worktree) for worktree in (a, b, detached)}

    # §3.10: the locks live in the state root, never under a target repo or worktree.
    assert {path.parent for path in paths.values()} == {state_root / "locks"}
    assert len(set(paths.values())) == 3, paths
    # A worktree path contains "/", so it cannot be a flat filename: the derived name is
    # one path component.
    for path in paths.values():
        assert "/" not in path.name
        assert path.name.endswith(".lock")

    # The detached worktree has no branch at all — a branch-keyed lock would have nothing
    # to key on — yet it still gets its own lock keyed by its resolved path.
    assert git.current_branch(detached) is None
    assert paths[detached] not in {paths[a], paths[b]}


def test_lock_filename_is_deterministic_from_the_resolved_path(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    a = _add_worktree(control, "task-a")

    assert lock.lock_filename(a) == lock.lock_filename(a)
    # A syntactically different spelling of the same directory is the same key.
    assert lock.lock_filename(a) == lock.lock_filename(Path(f"{a}/sub/.."))
    # Pure: deriving the key reads and writes nothing.
    assert not (tmp_path / "state").exists()


def test_lock_filename_is_injective_and_filesystem_safe_for_generated_paths() -> None:
    """Property: the key is a function of the path, safe as a filename, and injective.

    Pinned seed/run count: a failure here is reproducible (AGENTS.md §6).
    """
    rng = random.Random(PROPERTY_SEED)
    resolved: set[Path] = set()
    for _ in range(PROPERTY_NUM_RUNS):
        parts = []
        for _ in range(rng.randint(1, 4)):
            raw = "".join(
                rng.choice(_PROPERTY_ALPHABET) for _ in range(rng.randint(1, 40))
            )
            component = raw.strip("/") or "w"
            if component in (".", ".."):
                component = "w"
            parts.append(component)
        resolved.add(Path("/tmp/aidw-lock-property", *parts).resolve())

    names = {path: lock.lock_filename(path) for path in resolved}

    assert len(set(names.values())) == len(names), "two worktree paths shared one lock"
    for name in names.values():
        assert "/" not in name
        assert "\x00" not in name
        assert len(name) <= 255
        assert name == Path(name).name  # a single path component

    # Metamorphic: the name follows the path, so moving the worktree changes the key
    # (two same-named worktrees under different parents must not collide).
    sample = sorted(resolved)[0]
    assert lock.lock_filename(sample) != lock.lock_filename(sample.parent.parent / sample.name)


# ---------------------------------------------------------------------------
# Exclusion
# ---------------------------------------------------------------------------


def test_holder_in_another_process_excludes_and_its_death_auto_releases(
    tmp_path: Path,
) -> None:
    """Cross-process exclusion plus ``flock``'s automatic release with no stale lock."""
    _bare, control = _make_bare_with_control(tmp_path)
    a = _add_worktree(control, "task-a")
    b = _add_worktree(control, "task-b")
    state_root = tmp_path / "state"

    with _holder(state_root, a) as proc:
        with pytest.raises(lock.LockHeldError) as held:
            lock.acquire(state_root, a)
        assert held.value.worktree == a
        assert str(a) in str(held.value)

        # A different worktree is a different key: two runs in different worktrees
        # proceed (the roadmap's E2.7 "done when").
        other = lock.acquire(state_root, b)
        assert other.held
        other.release()

    assert proc.returncode == 0
    # The holder died without releasing or unlinking anything, and the file is still
    # there — proof that no cleanup is needed for the key to become free again.
    assert lock.lock_path(state_root, a).is_file()
    again = lock.acquire(state_root, a)
    assert again.held
    again.release()


def test_a_second_descriptor_in_one_process_is_refused(tmp_path: Path) -> None:
    """A fresh fd per acquire: a cached fd or a ``threading.Lock`` would not exclude."""
    _bare, control = _make_bare_with_control(tmp_path)
    a = _add_worktree(control, "task-a")
    state_root = tmp_path / "state"

    first = lock.acquire(state_root, a)
    try:
        with pytest.raises(lock.LockHeldError):
            lock.acquire(state_root, a)

        # Same for a second thread in this process: ``flock`` is per open file
        # description, so a module-level fd cache would let both "acquire" here.
        refused: list[Exception] = []

        def worker() -> None:
            try:
                lock.acquire(state_root, a)
            except Exception as exc:  # noqa: BLE001 - recorded and asserted below
                refused.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=60)
        assert not thread.is_alive()
        assert [type(exc) for exc in refused] == [lock.LockHeldError]
    finally:
        first.release()


def test_release_returns_the_key_to_free_and_is_idempotent(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    a = _add_worktree(control, "task-a")
    state_root = tmp_path / "state"

    guard = lock.acquire(state_root, a)
    assert guard.held
    guard.release()
    assert not guard.held
    guard.release()  # idempotent: a ``finally`` cannot mask the exit code

    with lock.acquire(state_root, a) as again:
        assert again.held
    assert not again.held


def test_refusal_message_names_the_worktree_and_the_lock_file(tmp_path: Path) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    a = _add_worktree(control, "task-a")
    state_root = tmp_path / "state"

    guard = lock.acquire(state_root, a)
    try:
        with pytest.raises(lock.LockHeldError) as held:
            lock.acquire(state_root, a)
    finally:
        guard.release()

    message = str(held.value)
    assert "another aidw run is already active" in message
    assert str(a) in message
    assert str(lock.lock_path(state_root, a)) in message
    assert held.value.path == lock.lock_path(state_root, a)


# ---------------------------------------------------------------------------
# Purity / fail-closed
# ---------------------------------------------------------------------------


def test_acquiring_writes_only_the_lock_file_under_the_state_root(tmp_path: Path) -> None:
    """Nothing is written into the worktree or the repo (§3.1, E2.7 req 7)."""
    _bare, control = _make_bare_with_control(tmp_path)
    a = _add_worktree(control, "task-a")
    state_root = tmp_path / "state"

    worktree_before = _snapshot(a)
    before = _snapshot(tmp_path)
    guard = lock.acquire(state_root, a)
    try:
        after = _snapshot(tmp_path)
        created = {Path(path) for path in after - before}
        assert created, "the lock file should have been created"
        assert all(path.is_relative_to(Path("state") / "locks") for path in created), created
        # The worktree itself is untouched: no ``.aidw/``, no lock, no marker.
        assert _snapshot(a) == worktree_before
    finally:
        guard.release()


def test_a_refusal_creates_no_run_state(tmp_path: Path) -> None:
    """A held lock fails closed before ``create_run``: the state root gains no run."""
    _bare, control = _make_bare_with_control(tmp_path)
    a = _add_worktree(control, "task-a")
    state_root = tmp_path / "state"

    guard = lock.acquire(state_root, a)
    try:
        with pytest.raises(lock.LockHeldError):
            lock.acquire(state_root, a)
    finally:
        guard.release()

    assert not (state_root / "runs").exists()
    assert sorted(path.name for path in (state_root / "locks").iterdir()) == [
        lock.lock_filename(a)
    ]
