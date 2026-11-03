"""Tests for the ``aidw run`` chains (design §8.6, Phase 7)."""

from __future__ import annotations

import dataclasses
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


def _git_run(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
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


def _chain_layout(
    tmp_path: Path, phase: str = "03", task: str = "E4.1"
) -> tuple[Path, Path, Path]:
    """Control root plus the task worktree with the prompt committed inside it (E2.5)."""
    _bare, control = _make_bare_with_control(tmp_path)
    branch = f"{phase}-{task}"
    worktree = git_mod.add_worktree(control, branch)
    assert worktree is not None
    prompt = worktree / "docs" / "task-prompts" / f"{branch}-prompt.md"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("body\n", encoding="utf-8")
    _git_run(worktree, "add", ".")
    _git_run(worktree, "commit", "-qm", "task prompt")
    return control, worktree, prompt


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


def test_task_to_pr_resolves_prompt_inside_the_located_worktree(
    tmp_path: Path, monkeypatch
) -> None:
    control, _worktree, prompt = _chain_layout(tmp_path)
    monkeypatch.setattr(run_workflow.prompt_workflow, "run", lambda **kwargs: 0)
    captured: dict = {}
    monkeypatch.setattr(
        run_workflow.implement_workflow,
        "run",
        lambda **kwargs: captured.update(kwargs) or 0,
    )

    repo, aidt, workspace = _roots(control)
    code = run_workflow.task_to_pr(
        phase="03", epic="E4", task="E4.1", repo=repo, aidt=aidt, workspace=workspace
    )
    assert code == 0
    assert captured["task_prompt_path"] == prompt
    assert captured["repo"] is repo
    assert captured["aidt"] is aidt
    assert captured["workspace"] is workspace


def test_task_to_pr_missing_worktree_stops_chain_with_command(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _bare, control = _make_bare_with_control(tmp_path)  # no task worktree
    monkeypatch.setattr(run_workflow.prompt_workflow, "run", lambda **kwargs: 0)
    called: list[dict] = []
    monkeypatch.setattr(
        run_workflow.implement_workflow,
        "run",
        lambda **kwargs: called.append(kwargs) or 0,
    )

    repo, aidt, workspace = _roots(control)
    code = run_workflow.task_to_pr(
        phase="03", epic="E4", task="E4.1", repo=repo, aidt=aidt, workspace=workspace
    )

    assert code == 4
    assert called == []
    command = (
        f"git -C {tmp_path / 'main'} worktree add -b 03-E4.1 "
        f"{tmp_path / '03-E4.1'} main"
    )
    assert command in capsys.readouterr().err


def test_task_to_pr_malformed_pattern_is_usage_error(
    tmp_path: Path, monkeypatch
) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    monkeypatch.setattr(run_workflow.prompt_workflow, "run", lambda **kwargs: 0)
    called: list[dict] = []
    monkeypatch.setattr(
        run_workflow.implement_workflow,
        "run",
        lambda **kwargs: called.append(kwargs) or 0,
    )

    repo, aidt, workspace = _roots(control)
    repo = dataclasses.replace(repo, branch_pattern="static")
    code = run_workflow.task_to_pr(
        phase="03", epic="E4", task="E4.1", repo=repo, aidt=aidt, workspace=workspace
    )

    assert code == 2
    assert called == []


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
    control, _worktree, _prompt = _chain_layout(tmp_path)
    monkeypatch.setattr(run_workflow.prompt_workflow, "run", lambda **kwargs: 0)
    monkeypatch.setattr(run_workflow.implement_workflow, "run", lambda **kwargs: 1)
    called: list[str] = []
    monkeypatch.setattr(
        run_workflow.review_workflow, "run", lambda **kwargs: called.append("review") or 0
    )
    monkeypatch.setattr(
        run_workflow.fix_workflow, "run", lambda **kwargs: called.append("fix") or 0
    )
    repo, aidt, workspace = _roots(control)
    code = run_workflow.prompt_to_fix(
        phase="03", epic="E4", task="E4.1", repo=repo, aidt=aidt, workspace=workspace
    )
    assert code == 1
    assert called == []


def test_prompt_to_fix_refuses_when_no_pr_is_recorded(tmp_path: Path, monkeypatch) -> None:
    control, _worktree, _prompt = _chain_layout(tmp_path)
    monkeypatch.setattr(run_workflow.prompt_workflow, "run", lambda **kwargs: 0)
    monkeypatch.setattr(run_workflow.implement_workflow, "run", lambda **kwargs: 0)
    called: list[str] = []
    monkeypatch.setattr(
        run_workflow.review_workflow, "run", lambda **kwargs: called.append("review") or 0
    )
    repo, aidt, workspace = _roots(control)
    # An implement run that recorded no PR URL (for example the `/pr` stage output was
    # unparseable) must not silently run review against PR #0. Discovery must key on the
    # *derived task branch*, not the control root's current (base) branch.
    _record_pr(workspace, control, branch="03-E4.1", number=0)
    code = run_workflow.prompt_to_fix(
        phase="03", epic="E4", task="E4.1", repo=repo, aidt=aidt, workspace=workspace
    )
    assert code == 2
    assert called == []


def test_prompt_to_fix_runs_the_whole_cycle(tmp_path: Path, monkeypatch) -> None:
    control, _worktree, prompt = _chain_layout(tmp_path)

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

    repo, aidt, workspace = _roots(control)
    # The post-E2.5 layout: the control root is on `main`, the implement run is recorded
    # for the derived task branch. Discovery must find it without --pr.
    _record_pr(workspace, control, branch="03-E4.1", number=42)

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
    control, _worktree, _prompt = _chain_layout(tmp_path)
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
    repo, aidt, workspace = _roots(control)
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
    control, _worktree, _prompt = _chain_layout(tmp_path)
    monkeypatch.setattr(run_workflow.prompt_workflow, "run", lambda **kwargs: 0)
    monkeypatch.setattr(run_workflow.implement_workflow, "run", lambda **kwargs: 0)
    monkeypatch.setattr(run_workflow.review_workflow, "run", lambda **kwargs: 0)
    fixed: dict = {}
    monkeypatch.setattr(
        run_workflow.fix_workflow, "run", lambda **kwargs: fixed.update(kwargs) or 3
    )
    repo, aidt, workspace = _roots(control)
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


# --------------------------------------------------------------------------- #
# Graceful end when an approving review published nothing (decision I2)
# --------------------------------------------------------------------------- #


def _record_review(
    workspace: WorkspacePaths,
    repo: Path,
    *,
    pr: int,
    published: bool | None,
    label: str | None = None,
) -> None:
    """Write a ``review`` run state, optionally carrying the I2 marker.

    ``published=None`` writes a state without ``pr.followups_published``, which is what
    ``review --dry-run`` and pre-I2 records look like.
    """
    runs_root = workspace.state_root / "runs"
    pr_record: dict = {"number": pr}
    if published is not None:
        pr_record[run_workflow.PR_FOLLOWUPS] = published
    created = state_mod.create_run(
        runs_root,
        repo,
        "review",
        label=label or f"pr-{pr}-review",
        pr=pr_record,
    )
    state_mod.save(runs_root / created.run_id, created)


def _fake_review(published: bool | None, *, order: list[str] | None = None):
    """A ``review_workflow.run`` stand-in that records its outcome like the real one."""

    def run(**kwargs) -> int:
        if order is not None:
            order.append("review")
        _record_review(
            kwargs["workspace"],
            kwargs["repo"].root,
            pr=kwargs["pr"],
            published=published,
        )
        return 0

    return run


def test_review_published_followups_reads_every_review_run_for_the_pr(
    tmp_path: Path,
) -> None:
    """``False`` only when no review of this PR ever published follow-ups (I2)."""
    _init_repo(tmp_path)
    _repo, _aidt, workspace = _roots(tmp_path)
    runs_root = workspace.state_root / "runs"

    assert run_workflow.review_published_followups(runs_root, 7) is None

    # A record without the marker (a dry run, or a pre-I2 state) is not evidence.
    _record_review(workspace, tmp_path, pr=7, published=None, label="pr-7-dry-run")
    assert run_workflow.review_published_followups(runs_root, 7) is None

    _record_review(workspace, tmp_path, pr=7, published=False, label="pr-7-a")
    assert run_workflow.review_published_followups(runs_root, 7) is False

    # Another PR's review says nothing about this one.
    _record_review(workspace, tmp_path, pr=8, published=True, label="pr-8")
    assert run_workflow.review_published_followups(runs_root, 7) is False

    # An earlier round's follow-ups outlive a later "nothing to publish" review.
    _record_review(workspace, tmp_path, pr=7, published=True, label="pr-7-b")
    assert run_workflow.review_published_followups(runs_root, 7) is True


def test_review_and_fix_ends_when_the_review_published_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    """The fix loop has nothing to approve, so it must not be started at all."""
    _init_repo(tmp_path)
    monkeypatch.setattr(run_workflow.review_workflow, "run", _fake_review(False))
    called: list[dict] = []
    monkeypatch.setattr(
        run_workflow.fix_workflow, "run", lambda **kwargs: called.append(kwargs) or 0
    )
    repo, aidt, workspace = _roots(tmp_path)

    code = run_workflow.review_and_fix(pr=7, repo=repo, aidt=aidt, workspace=workspace)

    assert code == 0
    assert called == []


def test_prompt_to_fix_ends_after_review_when_nothing_was_published(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Decision I2: an approving review that published nothing completes the chain.

    The trigger: an ``Approve`` review publishes no follow-ups, so the PR has no
    review-follow-up parent issue and `fix`'s entry stage failed closed with
    ``could not read approval state (approve --dry-run exit 2): No review-follow-up
    parent issue found``. The chain must end there, gracefully, and not auto-approve a
    gate for a stage it never runs.
    """
    control, _worktree, _prompt = _chain_layout(tmp_path)
    order: list[str] = []
    monkeypatch.setattr(
        run_workflow.prompt_workflow, "run", lambda **kwargs: order.append("prompt") or 0
    )
    monkeypatch.setattr(
        run_workflow.implement_workflow,
        "run",
        lambda **kwargs: order.append("implement") or 0,
    )
    monkeypatch.setattr(
        run_workflow.review_workflow, "run", _fake_review(False, order=order)
    )
    called: list[dict] = []
    monkeypatch.setattr(
        run_workflow.fix_workflow, "run", lambda **kwargs: called.append(kwargs) or 0
    )
    repo, aidt, workspace = _roots(control)
    _record_pr(workspace, control, branch="03-E4.1", number=42)

    code = run_workflow.prompt_to_fix(
        phase="03", epic="E4", task="E4.1", repo=repo, aidt=aidt, workspace=workspace
    )

    assert code == 0
    assert order == ["prompt", "implement", "review"]
    assert called == []
    out = capsys.readouterr().out
    assert "review published no follow-ups for PR #42" in out
    assert "chain complete." in out
    assert f"auto-approving `{run_workflow.GATE_FOLLOWUPS}`" not in out


def test_prompt_to_fix_still_runs_fix_when_followups_were_published(
    tmp_path: Path, monkeypatch
) -> None:
    """A review that published follow-ups keeps the whole cycle (decision I2)."""
    control, _worktree, _prompt = _chain_layout(tmp_path)
    monkeypatch.setattr(run_workflow.prompt_workflow, "run", lambda **kwargs: 0)
    monkeypatch.setattr(run_workflow.implement_workflow, "run", lambda **kwargs: 0)
    monkeypatch.setattr(run_workflow.review_workflow, "run", _fake_review(True))
    fixed: dict = {}
    monkeypatch.setattr(
        run_workflow.fix_workflow, "run", lambda **kwargs: fixed.update(kwargs) or 0
    )
    repo, aidt, workspace = _roots(control)
    _record_pr(workspace, control, branch="03-E4.1", number=42)

    code = run_workflow.prompt_to_fix(
        phase="03", epic="E4", task="E4.1", repo=repo, aidt=aidt, workspace=workspace
    )

    assert code == 0
    assert fixed["pr"] == 42
    assert fixed["skip_gates"] == [run_workflow.GATE_FOLLOWUPS]
