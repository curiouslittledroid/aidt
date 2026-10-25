"""Tests for the ``aidw run`` chains (design §8.6, Phase 7)."""

from __future__ import annotations

import time
from pathlib import Path

from aidw.workflows import run as run_workflow


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
    monkeypatch.setattr(run_workflow.prompt_workflow, "run", lambda **kwargs: 1)
    called: list[dict] = []
    monkeypatch.setattr(
        run_workflow.implement_workflow, "run", lambda **kwargs: called.append(kwargs) or 0
    )
    code = run_workflow.task_to_pr(
        phase="03", epic="E4", task="E4.1", repo=tmp_path, aidt=tmp_path / "aidt"
    )
    assert code == 1
    assert called == []


def test_task_to_pr_hands_resolved_prompt_to_implement(tmp_path: Path, monkeypatch) -> None:
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

    code = run_workflow.task_to_pr(
        phase="03", epic="E4", task="E4.1", repo=tmp_path, aidt=tmp_path / "aidt"
    )
    assert code == 0
    assert captured["task_prompt_path"] == prompt


def test_review_and_fix_stops_when_review_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_workflow.review_workflow, "run", lambda **kwargs: 3)
    called: list[dict] = []
    monkeypatch.setattr(
        run_workflow.fix_workflow, "run", lambda **kwargs: called.append(kwargs) or 0
    )
    code = run_workflow.review_and_fix(pr=7, repo=tmp_path, aidt=tmp_path / "aidt")
    assert code == 3
    assert called == []


def test_review_and_fix_runs_fix(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_workflow.review_workflow, "run", lambda **kwargs: 0)
    captured: dict = {}
    monkeypatch.setattr(
        run_workflow.fix_workflow,
        "run",
        lambda **kwargs: captured.update(kwargs) or 0,
    )
    code = run_workflow.review_and_fix(
        pr=7, repo=tmp_path, aidt=tmp_path / "aidt", max_iterations=3
    )
    assert code == 0
    assert captured["pr"] == 7
    assert captured["max_iterations"] == 3
