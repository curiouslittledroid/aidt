"""Run state, artifacts, and resumability (design §9).

A run is one execution of a workflow. State lives in
``aidt/runs/<run_id>/state.json`` and records every stage and gate so a workflow can be
inspected, logged, and resumed.
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
class RunState:
    run_id: str
    workflow: str
    created_at: str
    repo_root: str
    schema_version: int = SCHEMA_VERSION
    git: dict[str, Any] = field(default_factory=dict)
    task: dict[str, Any] = field(default_factory=dict)
    pr: dict[str, Any] = field(default_factory=dict)
    strict: bool = False
    status: str = RUNNING
    stages: list[StageRecord] = field(default_factory=list)
    gates: list[GateRecord] = field(default_factory=list)
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
        scalar = {k: v for k, v in data.items() if k in known}
        scalar["stages"] = stages
        scalar["gates"] = gates
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


def _filter(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    known = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in known}


def run_dir(runs_dir: Path, run_id: str) -> Path:
    return runs_dir / run_id


def create_run(
    runs_dir: Path,
    repo_root: Path,
    workflow: str,
    *,
    label: str,
    task: dict[str, Any] | None = None,
    pr: dict[str, Any] | None = None,
    strict: bool = False,
    branch: str | None = None,
) -> RunState:
    state = RunState(
        run_id=new_run_id(label, workflow),
        workflow=workflow,
        created_at=utcnow_iso(),
        repo_root=str(repo_root),
        strict=strict,
        task=task or {},
        pr=pr or {},
        git={"branch": branch} if branch else {},
    )
    save(run_dir(runs_dir, state.run_id), state)
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


def list_runs(runs_dir: Path) -> list[RunState]:
    if not runs_dir.is_dir():
        return []
    states: list[RunState] = []
    for directory in sorted(runs_dir.iterdir()):
        if not (directory / "state.json").is_file():
            continue
        try:
            states.append(load(directory))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return states


def find_run(runs_dir: Path, run_id: str) -> RunState | None:
    directory = run_dir(runs_dir, run_id)
    if (directory / "state.json").is_file():
        return load(directory)
    return None


def latest_for_branch(runs_dir: Path, branch: str) -> RunState | None:
    matches = [s for s in list_runs(runs_dir) if s.git.get("branch") == branch]
    return matches[-1] if matches else None


def session_id(run_id: str, agent_id: str, stage_name: str, *, shared: bool) -> str:
    base = f"aidw-{run_id}-{agent_id}"
    return base if shared else f"{base}-{stage_name}"
