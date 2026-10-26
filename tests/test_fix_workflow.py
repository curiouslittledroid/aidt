"""Tests for the ``aidw fix`` workflow (design §8.4, Phase 6)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from aidw import git, github
from aidw.paths import TargetRepo, WorkspacePaths
from aidw.state import SUCCEEDED, StageRecord, run_dir
from aidw.workflows import fix as fix_workflow

APPROVE_REVIEW = "No findings.\n\n## Verdict\n\n**Approve** — fixed.\n"
FINDINGS_REVIEW = """\
Priority: Should fix
Confidence: 4
What I found: The fix does not cover the empty case.
Why it matters: Callers still crash on an empty list.
Trigger and effect: Empty input raises.
Where: src/list.ts:1
Suggested fix: Guard the empty case.

## Verdict

**Request changes**
"""


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "aidt").mkdir()


def _runs_root(repo: Path) -> Path:
    return WorkspacePaths.resolve(TargetRepo.resolve(repo)).state_root / "runs"


def _select_ok(number: int = 101, title: str = "Fix the loop") -> github.ScriptResult:
    payload = {
        "selected": {"number": number, "title": title, "priority": "must-fix"},
        "childrenInspected": 1,
        "totalChildren": 1,
        "skipped": [],
    }
    return github.ScriptResult([], 0, json.dumps(payload), "")


def _select_none() -> github.ScriptResult:
    payload = {
        "selected": None,
        "childrenInspected": 1,
        "totalChildren": 1,
        "skipped": [{"number": 101, "reason": "STATUS_FIXED", "title": "Fix the loop"}],
    }
    return github.ScriptResult([], github.EXIT_NONE_AVAILABLE, json.dumps(payload), "")


def _select_seq(items: list[github.ScriptResult]):
    queue = list(items)

    def _next(aidt, repo, pr, timeout=github.DEFAULT_TIMEOUT):
        return queue.pop(0) if queue else _select_none()

    return _next


class _FakeStages:
    def __init__(self, review_text: str = APPROVE_REVIEW) -> None:
        self.names: list[str] = []
        self.specs: list = []
        self.review_text = review_text

    def __call__(self, spec, **kwargs):
        self.names.append(spec.name)
        self.specs.append(spec)
        directory = run_dir(kwargs["runs_root"], kwargs["state"].run_id)
        stages = directory / "stages"
        stages.mkdir(parents=True, exist_ok=True)
        out = stages / f"{spec.name}.out.txt"
        out.write_text(
            self.review_text if spec.name.endswith("code-review") else "ok\n",
            encoding="utf-8",
        )
        record = StageRecord(
            name=spec.name,
            agent=spec.agent_id,
            model="test/model",
            status=SUCCEEDED,
            artifacts={"out": str(out)},
        )
        kwargs["state"].record_stage(record)
        return record


def _patch(monkeypatch, *, branch="03-E4.1", select_impl=None, view=None):
    monkeypatch.setattr(fix_workflow, "load_all", lambda aidt, repo: ({}, []))
    monkeypatch.setattr(git, "current_branch", lambda repo: branch)
    monkeypatch.setattr(github, "gh_available", lambda: True)
    monkeypatch.setattr(
        github,
        "pr_view",
        lambda repo, pr: view
        if view is not None
        else {"number": pr, "url": f"https://github.com/o/r/pull/{pr}",
              "baseRefName": "main", "headRefName": branch},
    )
    monkeypatch.setattr(github, "select_followups", select_impl or _select_seq([]))


def test_dry_run_lists_child_and_plans(tmp_path: Path, monkeypatch, capsys) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch, select_impl=_select_seq([_select_ok()]))
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, repo=tmp_path, aidt=tmp_path / "aidt", dry_run=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "child:  #101 Fix the loop" in out
    assert "iter1-fix-next-review-followup" in out
    assert "review-findings-to-github" in out
    assert stages.names[0] == "round1-approve-review-followups"


def test_no_available_child_is_success(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch, select_impl=_select_seq([_select_none()]))
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(
        pr=7, repo=tmp_path, aidt=tmp_path / "aidt", approve_all=True
    )

    assert code == 0
    assert stages.names == ["round1-approve-review-followups"]
    # The approve step must not succeed on the agent's exit code alone (design §10).
    assert callable(stages.specs[0].verify)


def test_clean_iteration_closes_child(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(
        monkeypatch,
        select_impl=_select_seq([_select_ok(), _select_ok(), _select_none()]),
    )
    stages = _FakeStages(APPROVE_REVIEW)
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(
        pr=7, repo=tmp_path, aidt=tmp_path / "aidt", approve_all=True
    )

    assert code == 0
    assert stages.names == [
        "round1-approve-review-followups",
        "iter1-fix-next-review-followup",
        "iter1-test",
        "iter1-code-review",
    ]
    state = next(_runs_root(tmp_path).iterdir())
    payload = json.loads((state / "artifacts" / "fix.json").read_text(encoding="utf-8"))
    assert payload["iterations"] == 1
    assert payload["closed_issues"][0]["number"] == 101


def test_findings_trigger_publish_and_second_approval(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(
        monkeypatch,
        select_impl=_select_seq([_select_ok(), _select_ok(), _select_ok(), _select_none()]),
    )
    stages = _FakeStages(FINDINGS_REVIEW)
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(
        pr=7, repo=tmp_path, aidt=tmp_path / "aidt", approve_all=True
    )

    assert code == 0
    assert "iter1-review-findings-to-github" in stages.names
    assert "round2-approve-review-followups" in stages.names
    gate_names = [g.name for g in _gates(tmp_path)]
    assert gate_names == ["approve-followups", "approve-followups"]


def _gates(tmp_path: Path):
    from aidw import state as state_mod

    run = state_mod.list_runs(_runs_root(tmp_path))[-1]
    return run.gates


def test_gate_denied_stops_before_approver(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch, select_impl=_select_seq([_select_ok()]))
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    # No --yes and a non-interactive session: the gate fails closed.
    code = fix_workflow.run(pr=7, repo=tmp_path, aidt=tmp_path / "aidt")

    assert code == 3
    assert stages.names == []


def test_max_iterations_bounds_the_loop(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch, select_impl=_select_seq([_select_ok(), _select_ok()]))
    stages = _FakeStages(APPROVE_REVIEW)
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(
        pr=7, repo=tmp_path, aidt=tmp_path / "aidt", approve_all=True, max_iterations=1
    )

    assert code == 3
    assert "iter1-code-review" in stages.names
    assert "iter2-fix-next-review-followup" not in stages.names


def test_preflight_rejects_non_main_base(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(
        monkeypatch,
        view={"number": 7, "url": "u", "baseRefName": "develop", "headRefName": "03-E4.1"},
    )
    monkeypatch.setattr(fix_workflow, "run_stage", _FakeStages())
    assert fix_workflow.run(pr=7, repo=tmp_path, aidt=tmp_path / "aidt") == 4


def test_preflight_rejects_branch_mismatch(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(
        monkeypatch,
        branch="other",
        view={"number": 7, "url": "u", "baseRefName": "main", "headRefName": "03-E4.1"},
    )
    monkeypatch.setattr(fix_workflow, "run_stage", _FakeStages())
    assert fix_workflow.run(pr=7, repo=tmp_path, aidt=tmp_path / "aidt") == 4


def test_preflight_missing_pr(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(github, "pr_view", lambda repo, pr: None)
    monkeypatch.setattr(fix_workflow, "run_stage", _FakeStages())
    assert fix_workflow.run(pr=7, repo=tmp_path, aidt=tmp_path / "aidt") == 2


def test_zero_max_iterations_is_usage_error(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(fix_workflow, "run_stage", _FakeStages())
    assert (
        fix_workflow.run(
            pr=7, repo=tmp_path, aidt=tmp_path / "aidt", max_iterations=0
        )
        == 2
    )
