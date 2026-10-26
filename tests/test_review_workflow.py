"""Tests for the ``aidw review`` workflow (design §8.3, Phase 5)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from aidw import git, github
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.state import SUCCEEDED, StageRecord, run_dir
from aidw.workflows import review as review_workflow

FINDINGS_REVIEW = """\
Priority: Must fix
Confidence: 5
What I found: The handler trusts an unvalidated header.
Why it matters: A caller can spoof the tenant.
Trigger and effect: Any request may act as another sandbox.
Where: services/player-api/src/handler.ts:12
Suggested fix: Validate against the session sandbox.

## Verdict

**Request changes**
"""

BLOCKED_REVIEW = FINDINGS_REVIEW.replace("**Request changes**", "**Blocked**")
APPROVED_REVIEW = "No findings.\n\n## Verdict\n\n**Approve** — looks correct.\n"


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
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


class _FakeStages:
    def __init__(self, review_text: str) -> None:
        self.names: list[str] = []
        self.review_text = review_text

    def __call__(self, spec, **kwargs):
        self.names.append(spec.name)
        directory = run_dir(kwargs["runs_root"], kwargs["state"].run_id)
        stages = directory / "stages"
        stages.mkdir(parents=True, exist_ok=True)
        out = stages / f"{spec.name}.out.txt"
        if spec.name == "code-review":
            out.write_text(self.review_text, encoding="utf-8")
        else:
            out.write_text(
                "F1: created #101 https://github.com/o/r/issues/101\n"
                "Parent issue: https://github.com/o/r/issues/100\n"
                "Summary comment: https://github.com/o/r/pull/7#issuecomment-1\n",
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


def _patch(monkeypatch, *, branch="03-E4.1", view: dict | None = None):
    monkeypatch.setattr(review_workflow, "load_all", lambda aidt, repo: ({}, []))
    monkeypatch.setattr(git, "current_branch", lambda repo: branch)
    monkeypatch.setattr(github, "gh_available", lambda: True)
    monkeypatch.setattr(
        github,
        "pr_view",
        lambda repo, pr, _view=view: _view
        if _view is not None
        else {"number": pr, "url": f"https://github.com/o/r/pull/{pr}",
              "baseRefName": "main", "headRefName": branch},
    )


def test_dry_run_plans_both_stages(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    stages = _FakeStages(APPROVED_REVIEW)
    monkeypatch.setattr(review_workflow, "run_stage", stages)

    code = review_workflow.run(pr=7, **_roots(tmp_path), dry_run=True)

    assert code == 0
    assert stages.names == ["code-review", "review-findings-to-github"]


def test_blocked_does_not_publish(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    stages = _FakeStages(BLOCKED_REVIEW)
    monkeypatch.setattr(review_workflow, "run_stage", stages)

    code = review_workflow.run(pr=7, **_roots(tmp_path))

    assert code == 3
    assert "review-findings-to-github" not in stages.names
    directory = next(_runs_root(tmp_path).iterdir())
    recorded = json.loads(
        (directory / "artifacts" / "findings.json").read_text(encoding="utf-8")
    )
    assert recorded["verdict"] == "Blocked"
    assert not (directory / "artifacts" / "review-manifest.json").exists()


def test_approved_without_findings_stops(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    stages = _FakeStages(APPROVED_REVIEW)
    monkeypatch.setattr(review_workflow, "run_stage", stages)

    code = review_workflow.run(pr=7, **_roots(tmp_path))

    assert code == 0
    assert stages.names == ["code-review"]


def test_request_changes_publishes_and_records(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    stages = _FakeStages(FINDINGS_REVIEW)
    monkeypatch.setattr(review_workflow, "run_stage", stages)

    code = review_workflow.run(pr=7, **_roots(tmp_path))

    assert code == 0
    assert stages.names == ["code-review", "review-findings-to-github"]
    directory = next(_runs_root(tmp_path).iterdir())
    manifest = json.loads(
        (directory / "artifacts" / "review-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["findings"][0]["priority"] == "must-fix"
    assert manifest["findings"][0]["id"] == "F1"


def test_preflight_rejects_non_main_base(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(
        monkeypatch,
        view={"number": 7, "url": "u", "baseRefName": "develop", "headRefName": "03-E4.1"},
    )
    monkeypatch.setattr(review_workflow, "run_stage", _FakeStages(APPROVED_REVIEW))
    assert review_workflow.run(pr=7, **_roots(tmp_path)) == 4


def test_preflight_rejects_branch_mismatch(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(
        monkeypatch,
        branch="other",
        view={"number": 7, "url": "u", "baseRefName": "main", "headRefName": "03-E4.1"},
    )
    monkeypatch.setattr(review_workflow, "run_stage", _FakeStages(APPROVED_REVIEW))
    assert review_workflow.run(pr=7, **_roots(tmp_path)) == 4


def test_preflight_missing_pr(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch, view=None)
    monkeypatch.setattr(github, "pr_view", lambda repo, pr: None)
    monkeypatch.setattr(review_workflow, "run_stage", _FakeStages(APPROVED_REVIEW))
    assert review_workflow.run(pr=7, **_roots(tmp_path)) == 2
