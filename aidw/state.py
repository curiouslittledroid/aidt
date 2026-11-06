"""Run state, artifacts, and resumability (design §9).

A run is one execution of a workflow. State lives under the per-repo state root
(``<state root>/runs/<run_id>/state.json``) and records every stage and gate so a
workflow can be inspected, logged, and resumed.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
BLOCKED = "blocked"
ABORTED = "aborted"
PLANNED = "planned"

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
    state = RunState(
        run_id=new_run_id(label, workflow),
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
    save(run_dir(runs_root, state.run_id), state)
    return state


def save(directory: Path, state: RunState) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "state.json").write_text(
        json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8"
    )


def load(directory: Path) -> RunState:
    data = json.loads((directory / "state.json").read_text(encoding="utf-8"))
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
        if not (directory / "state.json").is_file():
            continue
        try:
            states.append(load(directory))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return states


def find_run(runs_root: Path, run_id: str) -> RunState | None:
    directory = run_dir(runs_root, run_id)
    if (directory / "state.json").is_file():
        return load(directory)
    return None


def latest_for_branch(runs_root: Path, branch: str) -> RunState | None:
    matches = [s for s in list_runs(runs_root) if s.git.get("branch") == branch]
    return matches[-1] if matches else None


def session_id(run_id: str, agent_id: str, stage_name: str, *, shared: bool) -> str:
    base = f"aidw-{run_id}-{agent_id}"
    return base if shared else f"{base}-{stage_name}"
