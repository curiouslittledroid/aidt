"""Tests for the ``aidw run`` chains (design §8.6, Phase 7)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.workflows import run as run_workflow


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _roots(repo: Path) -> tuple[TargetRepo, ToolkitPaths, WorkspacePaths]:
    target = TargetRepo.resolve(repo)
    return (
        target,
        ToolkitPaths.resolve(),
        WorkspacePaths.resolve(
            target, state_dir_override=repo.parent / f"{repo.name}-state"
        ),
    )


def test_find_task_prompt_picks_newest(tmp_path: Path) -> None:
    root = tmp_path / "docs" / "task-prompts"
    root.mkdir(parents=True)
    older = root / "03-E4.1.md"
    newer = root / "03-E4.1-prompt.md"
    older.write_text("old\n", encoding="utf-8")
    time.sleep(0.01)
    newer.write_text("new\n", encoding="utf-8")
    assert run_workflow.find_task_prompt(tmp_path, "03", "E4.1") == newer


def test_find_task_prompt_none(tmp_path: Path) -> None:
    assert run_workflow.find_task_prompt(tmp_path, "03", "E4.1") is None


def test_task_to_pr_stops_when_prompt_fails(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    monkeypatch.setattr(run_workflow.prompt_workflow, "run", lambda **kwargs: 1)
    called: list[dict] = []
    monkeypatch.setattr(
        run_workflow.implement_workflow, "run", lambda **kwargs: called.append(kwargs) or 0
    )
    repo, aidt, workspace = _roots(tmp_path)
    code = run_workflow.task_to_pr(
        phase="03", epic="E4", task="E4.1", repo=repo, aidt=aidt, workspace=workspace
    )
    assert code == 1
    assert called == []


def test_task_to_pr_hands_resolved_prompt_to_implement(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    root = tmp_path / "docs" / "task-prompts"
    root.mkdir(parents=True)
    prompt = root / "03-E4.1-prompt.md"
    prompt.write_text("body\n", encoding="utf-8")

    monkeypatch.setattr(run_workflow.prompt_workflow, "run", lambda **kwargs: 0)
    captured: dict = {}
    monkeypatch.setattr(
        run_workflow.implement_workflow,
        "run",
        lambda **kwargs: captured.update(kwargs) or 0,
    )

    repo, aidt, workspace = _roots(tmp_path)
    code = run_workflow.task_to_pr(
        phase="03", epic="E4", task="E4.1", repo=repo, aidt=aidt, workspace=workspace
    )
    assert code == 0
    assert captured["task_prompt_path"] == prompt
    assert captured["repo"] is repo
    assert captured["aidt"] is aidt
    assert captured["workspace"] is workspace


def test_review_and_fix_stops_when_review_fails(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    reviewed: list[dict] = []
    monkeypatch.setattr(
        run_workflow.review_workflow, "run", lambda **kwargs: reviewed.append(kwargs) or 3
    )
    called: list[dict] = []
    monkeypatch.setattr(
        run_workflow.fix_workflow, "run", lambda **kwargs: called.append(kwargs) or 0
    )
    repo, aidt, workspace = _roots(tmp_path)
    code = run_workflow.review_and_fix(
        pr=7, repo=repo, aidt=aidt, workspace=workspace
    )
    assert code == 3
    assert called == []
    assert reviewed[0]["repo"] is repo
    assert reviewed[0]["aidt"] is aidt
    assert reviewed[0]["workspace"] is workspace


def test_review_and_fix_runs_fix(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    monkeypatch.setattr(run_workflow.review_workflow, "run", lambda **kwargs: 0)
    captured: dict = {}
    monkeypatch.setattr(
        run_workflow.fix_workflow,
        "run",
        lambda **kwargs: captured.update(kwargs) or 0,
    )
    repo, aidt, workspace = _roots(tmp_path)
    code = run_workflow.review_and_fix(
        pr=7, repo=repo, aidt=aidt, workspace=workspace, max_iterations=3
    )
    assert code == 0
    assert captured["pr"] == 7
    assert captured["max_iterations"] == 3
    assert captured["repo"] is repo
    assert captured["aidt"] is aidt
    assert captured["workspace"] is workspace
