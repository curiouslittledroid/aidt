"""Tests for the ``aidw approve-followups`` workflow."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from aidw import git, github
from aidw.gates import GateOutcome
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.state import SUCCEEDED, StageRecord, run_dir
from aidw.workflows import approve as approve_workflow


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "aidt").mkdir()


def _roots(repo: Path) -> dict:
    target = TargetRepo.resolve(repo)
    return {
        "repo": target,
        "aidt": ToolkitPaths.resolve(),
        "workspace": WorkspacePaths.resolve(
            target, state_dir_override=repo.parent / f"{repo.name}-state"
        ),
    }


def _runs_root(repo: Path) -> Path:
    return _roots(repo)["workspace"].state_root / "runs"


def _select_ok(number: int = 101, title: str = "Fix the loop") -> github.ScriptResult:
    payload = {
        "selected": {"number": number, "title": title, "priority": "must-fix"},
        "childrenInspected": 1,
        "totalChildren": 1,
        "skipped": [],
    }
    return github.ScriptResult([], 0, json.dumps(payload), "")


class _FakeStages:
    def __init__(self, status: str = SUCCEEDED) -> None:
        self.names: list[str] = []
        self.specs: list = []
        self.status = status

    def __call__(self, spec, **kwargs):
        self.names.append(spec.name)
        self.specs.append(spec)
        directory = run_dir(kwargs["runs_root"], kwargs["state"].run_id)
        stages = directory / "stages"
        stages.mkdir(parents=True, exist_ok=True)
        out = stages / f"{spec.name}.out.txt"
        out.write_text("ok\n", encoding="utf-8")
        record = StageRecord(
            name=spec.name,
            agent=spec.agent_id,
            model="test/model",
            status=self.status,
            artifacts={"out": str(out)},
        )
        kwargs["state"].record_stage(record)
        return record


def _patch(monkeypatch, *, view: dict | None = None) -> None:
    monkeypatch.setattr(approve_workflow, "load_all", lambda aidt, repo: ({}, []))
    monkeypatch.setattr(git, "current_branch", lambda repo: "03-E4.1")
    monkeypatch.setattr(github, "gh_available", lambda: True)
    monkeypatch.setattr(
        github,
        "pr_view",
        lambda repo, pr: view
        if view is not None
        else {
            "number": pr,
            "url": f"https://github.com/o/r/pull/{pr}",
            "baseRefName": "main",
            "headRefName": "03-E4.1",
        },
    )
    monkeypatch.setattr(github, "select_followups", lambda aidt, repo, pr, timeout=github.DEFAULT_TIMEOUT: _select_ok())


def test_dry_run_plans_stage_and_gate(tmp_path: Path, monkeypatch, capsys) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    stages = _FakeStages()
    monkeypatch.setattr(approve_workflow, "run_stage", stages)

    code = approve_workflow.run(
        pr=7, **_roots(tmp_path), dry_run=True
    )

    assert code == 0
    assert stages.names == ["approve-review-followups"]
    out = capsys.readouterr().out
    assert "child:  #101 Fix the loop" in out
    assert "approve-review-followups [succeeded] (planned) agent=review-approver" in out
    assert "gate (planned): approve-followups" in out


def test_gate_denied_stops_without_stage(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    stages = _FakeStages()
    monkeypatch.setattr(approve_workflow, "run_stage", stages)
    monkeypatch.setattr(
        approve_workflow,
        "decide",
        lambda *a, **k: GateOutcome(approve_workflow.GATE, False, "human-denied"),
    )

    code = approve_workflow.run(pr=7, **_roots(tmp_path))

    assert code == 3
    assert stages.names == []


def test_approved_runs_review_approver(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    stages = _FakeStages()
    monkeypatch.setattr(approve_workflow, "run_stage", stages)
    monkeypatch.setattr(
        approve_workflow,
        "decide",
        lambda *a, **k: GateOutcome(approve_workflow.GATE, True, "--yes"),
    )

    code = approve_workflow.run(
        pr=7, **_roots(tmp_path), approve_all=True
    )

    assert code == 0
    assert stages.names == ["approve-review-followups"]
    spec = stages.specs[0]
    assert spec.agent_id == "review-approver"
    assert spec.prompt.name == "approve-review-followups.md"
    assert spec.variables == ["7"]
    # The stage must not succeed on the agent's exit code alone (design §10).
    assert callable(spec.verify)


def test_stage_failure_is_recorded(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    stages = _FakeStages(status="failed")
    monkeypatch.setattr(approve_workflow, "run_stage", stages)
    monkeypatch.setattr(
        approve_workflow,
        "decide",
        lambda *a, **k: GateOutcome(approve_workflow.GATE, True, "--yes"),
    )

    code = approve_workflow.run(
        pr=7, **_roots(tmp_path), approve_all=True
    )

    assert code == 1


def test_missing_pr_is_usage_error(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch, view={})
    monkeypatch.setattr(github, "pr_view", lambda repo, pr: None)
    monkeypatch.setattr(approve_workflow, "run_stage", _FakeStages())

    code = approve_workflow.run(pr=7, **_roots(tmp_path))

    assert code == 2
