"""Tests for the ``aidw run`` chains (design §8.6, Phase 7)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from aidw import git as git_mod
from aidw import state as state_mod
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


# --------------------------------------------------------------------------- #
# prompt-to-fix (decision I1)
# --------------------------------------------------------------------------- #


def _record_pr(
    workspace: WorkspacePaths,
    repo: Path,
    *,
    branch: str,
    number: int,
    workflow: str = "implement",
    label: str | None = None,
) -> None:
    """Write an ``implement`` run whose state carries the PR number ``/pr`` recorded."""
    runs_root = workspace.state_root / "runs"
    created = state_mod.create_run(
        runs_root,
        repo,
        workflow,
        label=label or f"03-E4.1-{workflow}",
        pr={"number": number, "url": f"https://example.test/pull/{number}"},
        branch=branch,
    )
    state_mod.save(runs_root / created.run_id, created)


def test_find_pr_number_reads_newest_implement_run(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    repo, _aidt, workspace = _roots(tmp_path)
    # Same-second run ids sort by label, so the newer run needs the later label.
    _record_pr(workspace, tmp_path, branch="03-E4.1", number=41, label="03-E4.1-a")
    _record_pr(workspace, tmp_path, branch="03-E4.1", number=42, label="03-E4.1-b")
    assert run_workflow.find_pr_number(workspace.state_root / "runs", "03-E4.1") == 42


def test_find_pr_number_ignores_other_branches_workflows_and_missing_pr(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    repo, _aidt, workspace = _roots(tmp_path)
    _record_pr(workspace, tmp_path, branch="other", number=7)
    _record_pr(workspace, tmp_path, branch="03-E4.1", number=8, workflow="review")
    runs_root = workspace.state_root / "runs"
    bare = state_mod.create_run(
        runs_root, tmp_path, "implement", label="03-E4.1", branch="03-E4.1"
    )
    state_mod.save(runs_root / bare.run_id, bare)
    assert run_workflow.find_pr_number(runs_root, "03-E4.1") is None
    assert run_workflow.find_pr_number(runs_root, None) is None


def _write_task_prompt(tmp_path: Path) -> Path:
    """The prompt ``prompt`` would have committed, so the chain can move to ``implement``."""
    root = tmp_path / "docs" / "task-prompts"
    root.mkdir(parents=True, exist_ok=True)
    prompt = root / "03-E4.1-prompt.md"
    prompt.write_text("body\n", encoding="utf-8")
    return prompt


def test_prompt_to_fix_stops_when_prompt_fails(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    monkeypatch.setattr(run_workflow.prompt_workflow, "run", lambda **kwargs: 4)
    called: list[str] = []
    monkeypatch.setattr(
        run_workflow.implement_workflow, "run", lambda **kwargs: called.append("implement") or 0
    )
    monkeypatch.setattr(
        run_workflow.review_workflow, "run", lambda **kwargs: called.append("review") or 0
    )
    monkeypatch.setattr(
        run_workflow.fix_workflow, "run", lambda **kwargs: called.append("fix") or 0
    )
    repo, aidt, workspace = _roots(tmp_path)
    code = run_workflow.prompt_to_fix(
        phase="03", epic="E4", task="E4.1", repo=repo, aidt=aidt, workspace=workspace
    )
    assert code == 4
    assert called == []


def test_prompt_to_fix_stops_when_implement_fails(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _write_task_prompt(tmp_path)
    monkeypatch.setattr(run_workflow.prompt_workflow, "run", lambda **kwargs: 0)
    monkeypatch.setattr(run_workflow.implement_workflow, "run", lambda **kwargs: 1)
    called: list[str] = []
    monkeypatch.setattr(
        run_workflow.review_workflow, "run", lambda **kwargs: called.append("review") or 0
    )
    monkeypatch.setattr(
        run_workflow.fix_workflow, "run", lambda **kwargs: called.append("fix") or 0
    )
    repo, aidt, workspace = _roots(tmp_path)
    code = run_workflow.prompt_to_fix(
        phase="03", epic="E4", task="E4.1", repo=repo, aidt=aidt, workspace=workspace
    )
    assert code == 1
    assert called == []


def test_prompt_to_fix_refuses_when_no_pr_is_recorded(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _write_task_prompt(tmp_path)
    monkeypatch.setattr(run_workflow.prompt_workflow, "run", lambda **kwargs: 0)
    monkeypatch.setattr(run_workflow.implement_workflow, "run", lambda **kwargs: 0)
    called: list[str] = []
    monkeypatch.setattr(
        run_workflow.review_workflow, "run", lambda **kwargs: called.append("review") or 0
    )
    repo, aidt, workspace = _roots(tmp_path)
    # An implement run that recorded no PR URL (for example the `/pr` stage output was
    # unparseable) must not silently run review against PR #0.
    _record_pr(
        workspace,
        tmp_path,
        branch=git_mod.current_branch(tmp_path),
        number=0,
    )
    code = run_workflow.prompt_to_fix(
        phase="03", epic="E4", task="E4.1", repo=repo, aidt=aidt, workspace=workspace
    )
    assert code == 2
    assert called == []


def test_prompt_to_fix_runs_the_whole_cycle(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    prompt = _write_task_prompt(tmp_path)

    order: list[str] = []
    monkeypatch.setattr(
        run_workflow.prompt_workflow, "run", lambda **kwargs: order.append("prompt") or 0
    )
    implement_kwargs: dict = {}
    monkeypatch.setattr(
        run_workflow.implement_workflow,
        "run",
        lambda **kwargs: order.append("implement") or implement_kwargs.update(kwargs) or 0,
    )
    reviewed: list[int] = []
    monkeypatch.setattr(
        run_workflow.review_workflow,
        "run",
        lambda **kwargs: order.append("review") or reviewed.append(kwargs["pr"]) or 0,
    )
    fixed: dict = {}
    monkeypatch.setattr(
        run_workflow.fix_workflow,
        "run",
        lambda **kwargs: order.append("fix") or fixed.update(kwargs) or 0,
    )

    repo, aidt, workspace = _roots(tmp_path)
    branch = git_mod.current_branch(tmp_path)
    assert branch
    _record_pr(workspace, tmp_path, branch=branch, number=42)

    code = run_workflow.prompt_to_fix(
        phase="03", epic="E4", task="E4.1", repo=repo, aidt=aidt, workspace=workspace
    )

    assert code == 0
    assert order == ["prompt", "implement", "review", "fix"]
    the_pr = 42
    assert implement_kwargs["task_prompt_path"] == prompt
    assert reviewed == [the_pr]
    assert fixed["pr"] == the_pr
    assert run_workflow.GATE_FOLLOWUPS in fixed["skip_gates"]
    # Only the follow-ups gate is auto-approved: the PR gates keep normal semantics.
    assert fixed["skip_gates"] == [run_workflow.GATE_FOLLOWUPS]
    assert fixed["approve_all"] is False


def test_prompt_to_fix_explicit_pr_overrides_discovery(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _write_task_prompt(tmp_path)
    monkeypatch.setattr(run_workflow.prompt_workflow, "run", lambda **kwargs: 0)
    monkeypatch.setattr(run_workflow.implement_workflow, "run", lambda **kwargs: 0)
    reviewed: list[int] = []
    monkeypatch.setattr(
        run_workflow.review_workflow,
        "run",
        lambda **kwargs: reviewed.append(kwargs["pr"]) or 0,
    )
    fixed: dict = {}
    monkeypatch.setattr(
        run_workflow.fix_workflow, "run", lambda **kwargs: fixed.update(kwargs) or 0
    )
    repo, aidt, workspace = _roots(tmp_path)
    code = run_workflow.prompt_to_fix(
        phase="03",
        epic="E4",
        task="E4.1",
        repo=repo,
        aidt=aidt,
        workspace=workspace,
        pr=99,
    )
    assert code == 0
    assert reviewed == [99]
    assert fixed["pr"] == 99


def test_prompt_to_fix_deny_still_refuses_the_auto_approval(
    tmp_path: Path, monkeypatch
) -> None:
    """``--deny-gates approve-followups`` wins over the chain's own skip (design §6)."""
    _init_repo(tmp_path)
    _write_task_prompt(tmp_path)
    monkeypatch.setattr(run_workflow.prompt_workflow, "run", lambda **kwargs: 0)
    monkeypatch.setattr(run_workflow.implement_workflow, "run", lambda **kwargs: 0)
    monkeypatch.setattr(run_workflow.review_workflow, "run", lambda **kwargs: 0)
    fixed: dict = {}
    monkeypatch.setattr(
        run_workflow.fix_workflow, "run", lambda **kwargs: fixed.update(kwargs) or 3
    )
    repo, aidt, workspace = _roots(tmp_path)
    code = run_workflow.prompt_to_fix(
        phase="03",
        epic="E4",
        task="E4.1",
        repo=repo,
        aidt=aidt,
        workspace=workspace,
        pr=99,
        deny_gates=[run_workflow.GATE_FOLLOWUPS],
    )
    assert code == 3
    assert run_workflow.GATE_FOLLOWUPS not in fixed["skip_gates"]
    assert fixed["deny_gates"] == [run_workflow.GATE_FOLLOWUPS]


def test_prompt_to_fix_dry_run_uses_a_placeholder_pr(tmp_path: Path, monkeypatch) -> None:
    """A dry run opens no PR, so it must not read or fabricate an implement run."""
    _init_repo(tmp_path)
    monkeypatch.setattr(run_workflow.prompt_workflow, "run", lambda **kwargs: 0)
    monkeypatch.setattr(run_workflow.implement_workflow, "run", lambda **kwargs: 0)
    reviewed: list[int] = []
    monkeypatch.setattr(
        run_workflow.review_workflow,
        "run",
        lambda **kwargs: reviewed.append(kwargs["pr"]) or 0,
    )
    monkeypatch.setattr(run_workflow.fix_workflow, "run", lambda **kwargs: 0)
    repo, aidt, workspace = _roots(tmp_path)
    code = run_workflow.prompt_to_fix(
        phase="03",
        epic="E4",
        task="E4.1",
        repo=repo,
        aidt=aidt,
        workspace=workspace,
        dry_run=True,
    )
    assert code == 0
    assert reviewed == [0]
