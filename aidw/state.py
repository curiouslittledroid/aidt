"""Run state, artifacts, and resumability (design §9).

A run is one execution of a workflow. State lives under the per-repo state root
(``<state root>/runs/<run_id>/state.json``) and records every stage and gate so a
workflow can be inspected, logged, and resumed.

**One state file, two writers** (H0.1, design §9.2). The workflow process writes the
whole state through :func:`save`; the separate ``aidw gate run`` processes an agent
spawns write gate outcomes through :func:`append_gate_outcomes`. Neither may drop the
other's rows, so:

* every write happens under a per-run cross-process lock beside the file it protects
  (``<run_dir>/state.json.lock``, :func:`state_write_lock`) held around the whole
  read-modify-write, and
* every write is published with :func:`_write_atomic` — a temp file in the *same*
  directory, fsynced, then ``os.replace``d — so an unlocked reader (``load``,
  ``aidw runs show``, a concurrent citation) only ever sees a whole file.

:func:`save` merges the ``gate_outcomes`` already on disk into what it publishes, which
is what lets an outcome a stage's subprocess recorded survive the workflow's next
``save()`` of a ``RunState`` it loaded before that subprocess ran. The gate-write path
does not publish full state at all: it reloads under the lock and appends only, so a
stage record the workflow wrote in between survives it. The dedup rule is "two distinct
outcomes are two pieces of evidence": only byte-identical rows collapse (H0.1 Req 3).

This lock is **not** :data:`aidw.runner._STATE_LOCK` (in-process, concurrent stages of
one run) and **not** :func:`aidw.lock.acquire` (one run per worktree, held for the whole
workflow). Design §9.1: the three must not be conflated — a worktree-keyed lock here
would refuse every ``aidw gate run`` subprocess, because the workflow already holds it.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
import time
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

#: The state file, relative to the run directory (design §9.1).
STATE_FILENAME = "state.json"

#: Cross-process lock guarding the read-modify-write of ``state.json`` (H0.1 Req 4).
#: Colocated with the file it protects — never under ``locks/``, never worktree-keyed.
STATE_LOCK_FILENAME = "state.json.lock"

#: How long a writer waits for a peer before failing closed, and how often it retries.
#: The critical sections are a read plus an atomic rename, so contention is measured in
#: milliseconds; the ceiling only exists so a wedged peer cannot hang a workflow for ever.
STATE_LOCK_TIMEOUT_SECONDS = 60.0
STATE_LOCK_POLL_SECONDS = 0.01

RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
BLOCKED = "blocked"
ABORTED = "aborted"
PLANNED = "planned"

#: A stage the **workflow withheld before invoking Pi**, with a recorded reason (H3.2,
#: design §9.3). Distinct from :data:`FAILED` (nothing went wrong — the run's own evidence
#: decided the stage had nothing honest to do) and from a successful no-op (H3.1's
#: already-``[x]`` tick, which *did* run and recording nothing was its own success): it says
#: "this stage did not run, and here is why", which the resume skip's bare ``[skipped]``
#: print (it leaves no record at all) cannot. Additive to the vocabulary above at the same
#: ``SCHEMA_VERSION``: an older ``state.json`` never contains it and still loads.
SKIPPED = "skipped"

#: Key into ``StageRecord.artifacts`` carrying a skipped stage's human-readable reason
#: (H3.2). ``error`` stays unset on a skip — it renders as a failure (design §9.3) — so the
#: reason travels here, where the stage block and ``runs show`` can read it without a
#: transcript.
SKIP_REASON_KEY = "skip_reason"

#: Verification gate outcome statuses (``GateOutcome``, E4.8). A gate is never
#: "succeeded" — that word describes a *stage*; a gate passed or failed.
PASSED = "passed"
GATE_FAILED = "failed"

_LABEL_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sanitize_label(label: str) -> str:
    cleaned = _LABEL_SAFE.sub("-", label).strip("-")
    return cleaned or "run"


def new_run_id(label: str, workflow: str) -> str:
    """Build ``<stamp>-<label>-<workflow>``.

    The workflow trails the label so ``ls aidt/runs`` distinguishes several runs of the
    same task (for example ``...-03.1-A2-prompt`` from ``...-03.1-A2-implement``)
    without opening each ``state.json``. The timestamp stays first so directory sort
    order is still chronological.

    The workflow appears exactly once, at the end: a label that already ends with the
    workflow segment (``pr-42-fix`` for ``fix``) is not suffixed again, so a call site
    cannot produce ``...-pr-42-fix-fix``.
    """
    label_part = sanitize_label(label)
    workflow_part = sanitize_label(workflow)
    if label_part == workflow_part or label_part.endswith(f"-{workflow_part}"):
        return f"{_stamp()}-{label_part}"
    return f"{_stamp()}-{label_part}-{workflow_part}"


@dataclass
class StageRecord:
    name: str
    agent: str
    model: str
    status: str = PLANNED
    session_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    exit_code: int | None = None
    #: The **final** Pi attempt's ``stopReason`` (H1.1). Additive at the same
    #: ``SCHEMA_VERSION`` with a ``None`` default, so a record written before the field
    #: still loads. Per-attempt reasons live in ``stages/<name>.meta.json``'s
    #: ``attempts_detail``; this one exists so the workflow's failure path can name it.
    stop_reason: str | None = None
    #: Pi attempts this stage made: 1 normally, 2 when a retry ran. ``None`` for a
    #: record written before the field existed.
    attempts: int | None = None
    duration_seconds: float | None = None
    cost_usd: float | None = None
    #: Token/cost counters from the stage's ``.meta.json`` (``aidw.pi.Usage`` as a dict).
    usage: dict[str, Any] | None = None
    #: Seconds Pi spent generating assistant text (tool execution excluded).
    generation_seconds: float | None = None
    #: Seconds Pi spent executing tool calls (assistant generation excluded).
    tool_seconds: float | None = None
    #: Seconds per tool name, longest first; sums to ``tool_seconds`` (design §9.2).
    tool_breakdown: dict[str, float] | None = None
    #: Output tokens per second of generation time (design §9.2).
    output_tokens_per_second: float | None = None
    log: str | None = None
    rendered_prompt: str | None = None
    #: Size of this stage's rendered prompt in **characters**, ``len(rendered)`` — the same
    #: string written to ``prompts/<stage>.rendered.md`` (H2.1). Recorded for the ``prompt``
    #: review loop's head stages only, on the real-run path; author/fix stages and the
    #: ``--dry-run`` path leave it at its ``None`` default. Additive at the same
    #: ``SCHEMA_VERSION`` (the ``stop_reason``/``attempts`` precedent above), so a
    #: ``state.json`` written before the field still loads and a record that never set it
    #: serialises ``rendered_chars: null``. It sits beside ``usage``'s ``input_tokens`` so
    #: "how big was the prompt, and what did it cost in context?" is answerable from one
    #: record.
    rendered_chars: int | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class GateRecord:
    name: str
    decision: str
    mechanism: str
    at: str
    detail: str = ""


@dataclass
class GateOutcome:
    """One whole-repo verification gate outcome, tied to the tree it gated (E4.8).

    Distinct from :class:`GateRecord`, which records a *human* approval gate (design §6).
    This is a verification result: ``command`` was run, ``exit_code`` came back, and
    ``tree`` is the identity of the content it ran against (see ``aidw.verification``).
    Recording the origin — ``stage``, ``at`` and the command — is what lets a later
    stage of the same run cite the outcome as evidence rather than copy a bare number.
    """

    key: str
    command: list[str]
    tree: str
    status: str
    stage: str
    at: str
    exit_code: int | None = None
    duration_seconds: float | None = None
    summary: str = ""
    #: Repo-relative prefixes this gate declares its command cannot read; part of what
    #: must match before the outcome may be cited (see ``aidw.verification``).
    ignored: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == PASSED


@dataclass
class RunState:
    run_id: str
    workflow: str
    created_at: str
    repo_root: str
    schema_version: int = SCHEMA_VERSION
    #: Identity of what produced the run (E8.2, EXTRACTION.md §3.11, D9/D10): the toolkit
    #: version from :data:`aidw.__version__`, the *target config* schema version (never the
    #: state schema above — that key is taken and ``load`` refuses a mismatch), and a
    #: ``sha256:<hex>`` fingerprint of the resolved config.
    #:
    #: Additive at the same ``SCHEMA_VERSION``, following the throughput-fields precedent
    #: (design §9.2): each defaults to ``None`` so a ``state.json`` written before these
    #: fields existed still loads, and a caller that does not hold a resolved config (for
    #: example ``aidw exec``) records ``None`` rather than inventing one.
    toolkit_version: str | None = None
    config_schema_version: int | None = None
    config_hash: str | None = None
    git: dict[str, Any] = field(default_factory=dict)
    task: dict[str, Any] = field(default_factory=dict)
    pr: dict[str, Any] = field(default_factory=dict)
    strict: bool = False
    status: str = RUNNING
    stages: list[StageRecord] = field(default_factory=list)
    gates: list[GateRecord] = field(default_factory=list)
    #: Whole-repo verification gate outcomes (E4.8), newest last.
    gate_outcomes: list[GateOutcome] = field(default_factory=list)
    resume: dict[str, Any] = field(default_factory=dict)

    def totals(self) -> dict[str, Any]:
        """Combined usage across every recorded stage.

        Values come from each stage's ``usage`` counters; a stage that has a
        ``cost_usd`` but no ``usage`` (for example an older record) still contributes
        its cost. Planned stages contribute nothing.
        """
        input_tokens = 0
        output_tokens = 0
        cost_usd = 0.0
        for record in self.stages:
            usage = record.usage or {}
            input_tokens += int(usage.get("input_tokens", 0) or 0)
            output_tokens += int(usage.get("output_tokens", 0) or 0)
            if usage:
                cost_usd += float(usage.get("cost_usd", 0.0) or 0.0)
            elif record.cost_usd:
                cost_usd += float(record.cost_usd)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 6),
        }

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        ordered: dict[str, Any] = {}
        for key, value in data.items():
            ordered[key] = value
            if key == "schema_version":
                ordered["totals"] = self.totals()
        # Defensive: keep the section even if a future schema drops schema_version.
        ordered.setdefault("totals", self.totals())
        return ordered

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunState":
        known = {f.name for f in fields(cls)}
        stages = [StageRecord(**_filter(StageRecord, s)) for s in data.get("stages", [])]
        gates = [GateRecord(**_filter(GateRecord, g)) for g in data.get("gates", [])]
        outcomes = [
            GateOutcome(**_filter(GateOutcome, o))
            for o in data.get("gate_outcomes", [])
        ]
        scalar = {k: v for k, v in data.items() if k in known}
        scalar["stages"] = stages
        scalar["gates"] = gates
        scalar["gate_outcomes"] = outcomes
        return cls(**scalar)

    def stage(self, name: str) -> StageRecord | None:
        for record in self.stages:
            if record.name == name:
                return record
        return None

    def record_stage(self, record: StageRecord) -> StageRecord:
        existing = self.stage(record.name)
        if existing is not None:
            self.stages[self.stages.index(existing)] = record
        else:
            self.stages.append(record)
        return record

    def record_gate(self, record: GateRecord) -> None:
        self.gates.append(record)

    def gate_outcome(self, key: str, tree: str) -> GateOutcome | None:
        """The newest outcome for exactly this gate key and tree, if any.

        Both ``key`` and ``tree`` must match: two different gates never cite each other,
        and a different tree is a different question that must be answered by running.
        """
        for outcome in reversed(self.gate_outcomes):
            if outcome.key == key and outcome.tree == tree:
                return outcome
        return None

    def record_gate_outcome(self, outcome: GateOutcome) -> GateOutcome:
        self.gate_outcomes.append(outcome)
        return outcome


def _filter(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    known = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in known}


def run_dir(runs_root: Path, run_id: str) -> Path:
    return runs_root / run_id


# --------------------------------------------------------------------------- #
# Publication: one lock, atomic rename, merged gate outcomes (H0.1, design §9.2)
# --------------------------------------------------------------------------- #


def state_path(directory: Path) -> Path:
    """``<run_dir>/state.json`` — the single state file for a run."""
    return Path(directory) / STATE_FILENAME


def state_lock_path(directory: Path) -> Path:
    """``<run_dir>/state.json.lock`` — the state writer's cross-process mutex.

    Deliberately colocated with ``state.json`` instead of ``<state root>/locks`` (H0.1
    Req 4): the workflow holds the *worktree* run lock (``aidw.lock``) for its whole
    lifetime, so a worktree-keyed state lock would refuse every ``aidw gate run``
    subprocess the workflow itself spawned (design §9.1's non-conflation).
    """
    return Path(directory) / STATE_LOCK_FILENAME


class StateLockTimeout(RuntimeError):
    """A peer held the state write lock past :data:`STATE_LOCK_TIMEOUT_SECONDS`.

    Fail closed rather than write unguarded: publishing without the lock is exactly the
    lost-update this lock exists to prevent.
    """


@contextmanager
def state_write_lock(
    directory: Path, *, timeout: float = STATE_LOCK_TIMEOUT_SECONDS
) -> Iterator[None]:
    """Hold the run's state write lock across a full read-modify-write.

    ``fcntl.flock(LOCK_EX | LOCK_NB)`` on ``<run_dir>/state.json.lock``, following
    :mod:`aidw.lock`'s pattern: the descriptor is opened **fresh per acquire** (``flock``
    is per open file description, so a cached fd would let two threads of one process
    both "acquire") and the lock file is **never unlinked** (unlinking would race a
    second acquirer onto a new inode while this one still holds the old one).

    ``LOCK_NB`` plus a bounded retry loop, rather than a blocking ``LOCK_EX``: a peer
    holding the lock must be *waited for* (two overlapping ``aidw gate run`` processes
    both have evidence to record — H0.1 Req 3 forbids dropping either), but a wedged
    holder must not hang the run for ever. Raises :class:`StateLockTimeout` when the
    ceiling is reached.

    Never nest calls: ``flock`` on a second descriptor of the same file does not
    re-enter, so a nested acquire would wait for a lock the caller already holds.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = state_lock_path(directory)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise StateLockTimeout(
                        f"another writer held {path} for more than {timeout:g}s"
                    ) from None
                time.sleep(STATE_LOCK_POLL_SECONDS)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _write_atomic(
    directory: Path, state: "RunState", outcomes: Sequence["GateOutcome"]
) -> None:
    """Publish ``state`` with ``outcomes`` through fsync + ``os.replace`` (H0.1 Req 2).

    The temp file is created **in the run directory**, not ``/tmp``: ``os.replace`` is
    only atomic within one filesystem, and a cross-device move reopens the torn-read
    window this exists to close. Readers never take the lock, so this rename is the only
    thing standing between them and a partially written file.
    """
    data = state.to_dict()
    data["gate_outcomes"] = [asdict(outcome) for outcome in outcomes]
    payload = json.dumps(data, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(
        dir=directory, prefix=f".{STATE_FILENAME}.", suffix=".tmp"
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, state_path(directory))
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    _fsync_directory(directory)


def _fsync_directory(directory: Path) -> None:
    """Best-effort fsync of the directory entry the rename created.

    Durability, not atomicity: the rename is already atomic for readers. A platform that
    cannot fsync a directory handle (or refuses the open) must not fail the write, which
    has completed.
    """
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def outcome_identity(outcome: "GateOutcome") -> tuple[Any, ...]:
    """A hashable identity for one outcome row — every recorded field, in order.

    Used only to recognise the *same* row seen twice (the in-memory copy a ``save``
    started from and the copy already on disk); it never merges two rows that differ in
    any field, because two gate runs that both executed a command are two pieces of
    evidence (H0.1 Req 3's dedup hazard).
    """
    return (
        outcome.key,
        tuple(outcome.command),
        outcome.tree,
        outcome.status,
        outcome.stage,
        outcome.at,
        outcome.exit_code,
        outcome.duration_seconds,
        outcome.summary,
        tuple(outcome.ignored),
    )


def merge_gate_outcomes(
    base: Iterable["GateOutcome"], extra: Iterable["GateOutcome"]
) -> list["GateOutcome"]:
    """``base`` in order, then every ``extra`` row not already among them, in order.

    Pure: neither argument is mutated and no I/O happens, so the merge is citable as a
    rule rather than a side effect. ``extra`` is the *newer* side (in-memory on a
    ``save``), but nothing is reordered or replaced: an outcome is evidence with the
    origin it recorded, so "newest wins per key" would silently delete a run (H0.1
    Req 3's trap).
    """
    merged = list(base)
    seen = {outcome_identity(outcome) for outcome in merged}
    for outcome in extra:
        identity = outcome_identity(outcome)
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(outcome)
    return merged


def _load_if_present(directory: Path) -> "RunState | None":
    """The run on disk, or ``None`` when this is a run's first write."""
    if not state_path(directory).is_file():
        return None
    return load(directory)


#: The run id a ``--dry-run`` plans under (W1.2, design §9.4). A dry run creates no run, so it
#: mints no id either: the literal makes a plan's ``StageRecord.session_id`` deterministic
#: (``aidw-<planned>-<agent>-<stage>``), so two dry runs print identical output and a test can
#: pin it without stubbing the clock. Nothing is ever persisted under it — ``run_dir(runs_root,
#: PLANNED_RUN_ID)`` is a path no code creates.
PLANNED_RUN_ID = "<planned>"

#: The run-directory text a ``--dry-run`` plan renders where a real run's directory would go
#: (W1.2, design §9.4): ``review``'s manifest pointer, its publisher argv and ``fix``'s
#: per-iteration manifest / ``{closing_bodies}`` paths. A planned path is *named*, never
#: fabricated — a real-looking run id would name a run that does not exist. Real runs keep the
#: absolute ``run_dir(...)`` path (E7.3's PR 110), and because this text is relative, a stray
#: write would land in the working tree, which is why the tests assert none appears.
PLANNED_RUN_DIR_TEXT = "<run dir>"


def _new_run_state(
    run_id: str,
    repo_root: Path,
    workflow: str,
    *,
    task: dict[str, Any] | None,
    pr: dict[str, Any] | None,
    strict: bool,
    branch: str | None,
    toolkit_version: str | None,
    config_schema_version: int | None,
    config_hash: str | None,
) -> RunState:
    """The one run-record construction ``create_run`` and :func:`planned_run` share.

    Private and keyword-only so a new ``RunState`` field reaches a real run and a dry-run
    plan in the same edit; the two callers differ only in the run id they pass and whether
    they publish.
    """
    return RunState(
        run_id=run_id,
        workflow=workflow,
        created_at=utcnow_iso(),
        repo_root=str(repo_root),
        toolkit_version=toolkit_version,
        config_schema_version=config_schema_version,
        config_hash=config_hash,
        strict=strict,
        task=task or {},
        pr=pr or {},
        git={"branch": branch} if branch else {},
    )


def create_run(
    runs_root: Path,
    repo_root: Path,
    workflow: str,
    *,
    label: str,
    task: dict[str, Any] | None = None,
    pr: dict[str, Any] | None = None,
    strict: bool = False,
    branch: str | None = None,
    toolkit_version: str | None = None,
    config_schema_version: int | None = None,
    config_hash: str | None = None,
) -> RunState:
    state = _new_run_state(
        new_run_id(label, workflow),
        repo_root,
        workflow,
        task=task,
        pr=pr,
        strict=strict,
        branch=branch,
        toolkit_version=toolkit_version,
        config_schema_version=config_schema_version,
        config_hash=config_hash,
    )
    save(run_dir(runs_root, state.run_id), state)
    return state


def planned_run(
    runs_root: Path,
    repo_root: Path,
    workflow: str,
    *,
    label: str,
    task: dict[str, Any] | None = None,
    pr: dict[str, Any] | None = None,
    strict: bool = False,
    branch: str | None = None,
    toolkit_version: str | None = None,
    config_schema_version: int | None = None,
    config_hash: str | None = None,
) -> RunState:
    """A ``--dry-run``'s run record: ``create_run``'s exact arguments, with **no run** (W1.2).

    It returns the same :class:`RunState` under :data:`PLANNED_RUN_ID` and writes nothing —
    no run directory, no ``state.json`` — so a plan can never become a ``--resume`` target
    (design §9.4). The signature is deliberately identical to :func:`create_run`, argument
    for argument, so a caller picks one with ``planned_run if dry_run else create_run`` and
    the two cannot disagree about what a run records. ``runs_root`` and ``label`` are
    accepted and unused: they are the two inputs only a real run needs (its published path
    and its id), and dropping them would make the two calls differ at every call site.
    """
    return _new_run_state(
        PLANNED_RUN_ID,
        repo_root,
        workflow,
        task=task,
        pr=pr,
        strict=strict,
        branch=branch,
        toolkit_version=toolkit_version,
        config_schema_version=config_schema_version,
        config_hash=config_hash,
    )


def save(directory: Path, state: RunState) -> None:
    """Publish the whole run state, keeping every gate outcome already recorded.

    The workflow's writer. It reloads the file **inside** the lock and merges its
    ``gate_outcomes`` with the in-memory ones before publishing (H0.1 Req 3(i)): a
    ``RunState`` loaded at ``create_run`` is stale by the time a stage finishes, and a
    plain rewrite from it is what dropped every outcome an agent's ``aidw gate run``
    subprocess had appended. Everything else in ``state`` (stages, status, totals, the
    run's own fields) is the workflow's to write, so it is published as given.

    The merged list is also folded back into ``state`` so a long-lived workflow handle
    cites what its own agents recorded. A state file that cannot be read fails closed:
    overwriting it would delete evidence nobody could parse.
    """
    directory = Path(directory)
    with state_write_lock(directory):
        disk = _load_if_present(directory)
        merged = merge_gate_outcomes(
            disk.gate_outcomes if disk is not None else [], state.gate_outcomes
        )
        _write_atomic(directory, state, merged)
        state.gate_outcomes = merged


def append_gate_outcomes(
    directory: Path, outcomes: Sequence[GateOutcome]
) -> RunState:
    """Append gate outcomes to the run on disk without touching anything else.

    The CLI's writer (``aidw gate run``, H0.1 Req 3(ii)). It reloads the run *inside* the
    lock and changes only ``gate_outcomes``, so a stage record the workflow wrote between
    this process's initial load and this write survives — a full-state save of a stale
    ``RunState`` is exactly the other half of the symmetric loss. Rows are appended
    unconditionally: this process ran the command, so its outcome is new evidence even if
    an identical-looking row already exists.

    Returns the state as published, so the caller can report without a second read.
    """
    directory = Path(directory)
    with state_write_lock(directory):
        state = load(directory)
        for outcome in outcomes:
            state.record_gate_outcome(outcome)
        _write_atomic(directory, state, state.gate_outcomes)
    return state


def load(directory: Path) -> RunState:
    """Read a run's state. Lock-free by design: writers publish atomically."""
    data = json.loads(state_path(directory).read_text(encoding="utf-8"))
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported state schema_version {version!r} in {directory} "
            f"(expected {SCHEMA_VERSION})"
        )
    return RunState.from_dict(data)


def list_runs(runs_root: Path) -> list[RunState]:
    if not runs_root.is_dir():
        return []
    states: list[RunState] = []
    for directory in sorted(runs_root.iterdir()):
        if not state_path(directory).is_file():
            continue
        try:
            states.append(load(directory))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return states


def find_run(runs_root: Path, run_id: str) -> RunState | None:
    directory = run_dir(runs_root, run_id)
    if state_path(directory).is_file():
        return load(directory)
    return None


def latest_for_branch(runs_root: Path, branch: str) -> RunState | None:
    matches = [s for s in list_runs(runs_root) if s.git.get("branch") == branch]
    return matches[-1] if matches else None


def session_id(run_id: str, agent_id: str, stage_name: str, *, shared: bool) -> str:
    base = f"aidw-{run_id}-{agent_id}"
    return base if shared else f"{base}-{stage_name}"
