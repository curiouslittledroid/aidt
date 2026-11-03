"""Tests for the ``aidw review`` workflow (design §8.3, Phase 5, decision K1).

Since K1 the PR head is authoritative and its **worktree** is located. The real-run tests
therefore build the §3.2 layout from the shared ``worktree_repo`` fixture (E2.9): a control
worktree on ``main`` plus a sibling task worktree. Reviewing a worktree PR from the control
root is exactly the case that used to refuse with ``current branch `main` is not the PR
head``.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from aidw import git, github, lock
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.state import SUCCEEDED, StageRecord, run_dir
from aidw.workflows import review as review_workflow

#: ``worktree_repo`` checks the task branch out in ``<workspace>/task`` (§3.2).
BRANCH = "task"

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
        self.repo_roots: list[Path] = []
        self.review_text = review_text

    def __call__(self, spec, **kwargs):
        self.names.append(spec.name)
        self.repo_roots.append(kwargs["repo_root"])
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


def _patch(monkeypatch, *, branch=BRANCH, view: dict | None = None, gh: bool = True):
    monkeypatch.setattr(review_workflow, "load_all", lambda aidt, repo: ({}, []))
    monkeypatch.setattr(github, "gh_available", lambda: gh)
    monkeypatch.setattr(
        github,
        "pr_view",
        lambda repo, pr: view
        if view is not None
        else {"number": pr, "url": f"https://github.com/o/r/pull/{pr}",
              "baseRefName": "main", "headRefName": branch},
    )


def _no_run_state(repo: Path) -> None:
    runs_root = _runs_root(repo)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []


# --------------------------------------------------------------------------- #
# PR-head worktree resolution (K1)
# --------------------------------------------------------------------------- #


def test_review_runs_from_a_control_root_checked_out_on_main(
    worktree_repo, monkeypatch, capsys
) -> None:
    """The K1 regression: the control root is on ``main``, the PR head is not.

    ``aidw run prompt-to-fix`` reviews straight after ``implement``, which worked in the
    task worktree; the chain hands ``review`` the control-root ``TargetRepo``, so the
    ``git.current_branch(repo.root) == headRefName`` preflight could never pass and the
    chain stopped with ``chain stopped: `review` exited 4`` on every worktree run.
    """
    _patch(monkeypatch)
    stages = _FakeStages(APPROVED_REVIEW)
    monkeypatch.setattr(review_workflow, "run_stage", stages)

    assert git.current_branch(worktree_repo.control) == "main"

    code = review_workflow.run(pr=7, **_roots(worktree_repo.control))

    assert code == 0
    out = capsys.readouterr().out
    assert f"branch: {BRANCH}" in out
    # Every stage reads the PR-head worktree, never the control root.
    assert stages.repo_roots == [worktree_repo.task]
    state = json.loads(
        (next(_runs_root(worktree_repo.control).iterdir()) / "state.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["repo_root"] == str(worktree_repo.task)
    assert state["git"]["branch"] == BRANCH


def test_a_pr_head_checked_out_here_still_reviews_in_place(
    worktree_repo, monkeypatch
) -> None:
    """A PR whose head *is* the invoking worktree's branch is unchanged (no relocation)."""
    _patch(monkeypatch, branch="main")
    stages = _FakeStages(APPROVED_REVIEW)
    monkeypatch.setattr(review_workflow, "run_stage", stages)

    assert review_workflow.run(pr=7, **_roots(worktree_repo.control)) == 0
    assert stages.repo_roots == [worktree_repo.control]


def test_missing_pr_head_worktree_is_refused_with_the_command(
    worktree_repo, monkeypatch, capsys
) -> None:
    _patch(monkeypatch, branch="03-E4.1")  # the PR head is known but not checked out
    stages = _FakeStages(APPROVED_REVIEW)
    monkeypatch.setattr(review_workflow, "run_stage", stages)

    code = review_workflow.run(pr=7, **_roots(worktree_repo.control))

    assert code == 4
    assert stages.names == []
    _no_run_state(worktree_repo.control)
    err = capsys.readouterr().err
    assert "no worktree for `03-E4.1`" in err
    assert (
        f"git -C {worktree_repo.workspace / 'main'} worktree add -b 03-E4.1 "
        f"{worktree_repo.workspace / '03-E4.1'} main"
    ) in err


def test_missing_pr_head_worktree_dry_run_plans_the_command(
    worktree_repo, monkeypatch, capsys
) -> None:
    _patch(monkeypatch, branch="03-E4.1")
    stages = _FakeStages(APPROVED_REVIEW)
    monkeypatch.setattr(review_workflow, "run_stage", stages)

    code = review_workflow.run(pr=7, **_roots(worktree_repo.control), dry_run=True)

    assert code == 0
    out = capsys.readouterr().out
    planned = worktree_repo.workspace / "03-E4.1"
    assert f"worktree (planned): {planned}" in out
    assert (
        f"branch-setup (planned): git -C {worktree_repo.workspace / 'main'} worktree "
        f"add -b 03-E4.1 {planned} main"
    ) in out
    assert "branch: 03-E4.1" in out
    # No worktree to plan in: the plan falls back to the invoking worktree, still exit 0.
    assert stages.repo_roots and all(
        root == worktree_repo.control for root in stages.repo_roots
    )


def test_dry_run_unanswerable_pr_read_is_branch_unknown(
    worktree_repo, monkeypatch, capsys
) -> None:
    _patch(monkeypatch, gh=False)
    stages = _FakeStages(APPROVED_REVIEW)
    monkeypatch.setattr(review_workflow, "run_stage", stages)

    code = review_workflow.run(pr=7, **_roots(worktree_repo.control), dry_run=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "branch: unknown (`gh` not found)" in out
    assert stages.repo_roots and all(
        root == worktree_repo.control for root in stages.repo_roots
    )


def test_a_config_error_in_the_worktree_is_a_usage_error(
    worktree_repo, monkeypatch
) -> None:
    """The reloaded worktree config can fail where the control root did not."""
    from aidw.config import ERROR, Issue

    _patch(monkeypatch)
    calls: list[Path] = []

    def _load_all(aidt, repo):
        calls.append(repo)
        if repo == worktree_repo.task:
            return {}, [Issue(ERROR, "config", "bad config in the PR worktree")]
        return {}, []

    monkeypatch.setattr(review_workflow, "load_all", _load_all)
    stages = _FakeStages(APPROVED_REVIEW)
    monkeypatch.setattr(review_workflow, "run_stage", stages)

    assert review_workflow.run(pr=7, **_roots(worktree_repo.control)) == 2
    assert calls == [worktree_repo.control, worktree_repo.task]
    assert stages.names == []
    _no_run_state(worktree_repo.control)


# --------------------------------------------------------------------------- #
# Stages, verdicts and publication (design §8.3)
# --------------------------------------------------------------------------- #


def test_dry_run_plans_both_stages(worktree_repo, monkeypatch, capsys) -> None:
    _patch(monkeypatch)
    stages = _FakeStages(APPROVED_REVIEW)
    monkeypatch.setattr(review_workflow, "run_stage", stages)

    code = review_workflow.run(pr=7, **_roots(worktree_repo.control), dry_run=True)

    assert code == 0
    assert stages.names == ["code-review", "review-findings-to-github"]
    assert stages.repo_roots == [worktree_repo.task, worktree_repo.task]
    assert f"worktree (planned): {worktree_repo.task}" in capsys.readouterr().out


def test_blocked_does_not_publish(worktree_repo, monkeypatch) -> None:
    _patch(monkeypatch)
    stages = _FakeStages(BLOCKED_REVIEW)
    monkeypatch.setattr(review_workflow, "run_stage", stages)

    code = review_workflow.run(pr=7, **_roots(worktree_repo.control))

    assert code == 3
    assert "review-findings-to-github" not in stages.names
    directory = next(_runs_root(worktree_repo.control).iterdir())
    recorded = json.loads(
        (directory / "artifacts" / "findings.json").read_text(encoding="utf-8")
    )
    assert recorded["verdict"] == "Blocked"
    assert not (directory / "artifacts" / "review-manifest.json").exists()


def test_approved_without_findings_stops(worktree_repo, monkeypatch) -> None:
    _patch(monkeypatch)
    stages = _FakeStages(APPROVED_REVIEW)
    monkeypatch.setattr(review_workflow, "run_stage", stages)

    code = review_workflow.run(pr=7, **_roots(worktree_repo.control))

    assert code == 0
    assert stages.names == ["code-review"]
    # The chain's graceful-end guard reads this marker (decision I2): an approving review
    # that published nothing is recorded explicitly, never left to be inferred.
    directory = next(_runs_root(worktree_repo.control).iterdir())
    recorded = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    assert recorded["pr"][review_workflow.PR_FOLLOWUPS] is False


def test_request_changes_publishes_and_records(worktree_repo, monkeypatch) -> None:
    _patch(monkeypatch)
    stages = _FakeStages(FINDINGS_REVIEW)
    monkeypatch.setattr(review_workflow, "run_stage", stages)

    code = review_workflow.run(pr=7, **_roots(worktree_repo.control))

    assert code == 0
    assert stages.names == ["code-review", "review-findings-to-github"]
    directory = next(_runs_root(worktree_repo.control).iterdir())
    manifest = json.loads(
        (directory / "artifacts" / "review-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["findings"][0]["priority"] == "must-fix"
    assert manifest["findings"][0]["id"] == "F1"
    recorded = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    assert recorded["pr"][review_workflow.PR_FOLLOWUPS] is True


def test_preflight_rejects_non_main_base(worktree_repo, monkeypatch) -> None:
    _patch(
        monkeypatch,
        view={"number": 7, "url": "u", "baseRefName": "develop", "headRefName": BRANCH},
    )
    monkeypatch.setattr(review_workflow, "run_stage", _FakeStages(APPROVED_REVIEW))
    assert review_workflow.run(pr=7, **_roots(worktree_repo.control)) == 4


def test_preflight_missing_pr(worktree_repo, monkeypatch) -> None:
    _patch(monkeypatch, view=None)
    monkeypatch.setattr(github, "pr_view", lambda repo, pr: None)
    monkeypatch.setattr(review_workflow, "run_stage", _FakeStages(APPROVED_REVIEW))
    assert review_workflow.run(pr=7, **_roots(worktree_repo.control)) == 2


# --------------------------------------------------------------------------- #
# One run per worktree (E2.7, EXTRACTION.md §3.2/§3.10)
# --------------------------------------------------------------------------- #


def test_a_held_worktree_lock_is_refused_before_any_run_state(
    worktree_repo, monkeypatch, capsys
) -> None:
    """``review`` keys on the re-resolved PR-head worktree, not the control root."""
    _patch(monkeypatch)
    stages = _FakeStages(APPROVED_REVIEW)
    monkeypatch.setattr(review_workflow, "run_stage", stages)
    roots = _roots(worktree_repo.control)

    with lock.acquire(roots["workspace"].state_root, worktree_repo.task):
        code = review_workflow.run(pr=7, **roots)

    assert code == 4
    assert stages.names == []
    _no_run_state(worktree_repo.control)
    err = capsys.readouterr().err
    assert "another aidw run is already active" in err
    assert str(worktree_repo.task) in err


def test_two_concurrent_review_runs_from_one_worktree_are_refused(
    worktree_repo, monkeypatch, capsys
) -> None:
    """A live review refuses a second one for the same PR-head worktree."""
    _patch(monkeypatch)
    entered, release = threading.Event(), threading.Event()

    class _BlockingStages(_FakeStages):
        def __call__(self, spec, **kwargs):
            entered.set()
            assert release.wait(timeout=60), "the holder was never released"
            return super().__call__(spec, **kwargs)

    monkeypatch.setattr(review_workflow, "run_stage", _BlockingStages(APPROVED_REVIEW))
    roots = _roots(worktree_repo.control)
    outcome: dict = {}

    def hold() -> None:
        try:
            outcome["code"] = review_workflow.run(pr=7, **roots)
        except BaseException as exc:  # pragma: no cover - asserted via ``outcome``
            outcome["error"] = exc

    holder = threading.Thread(target=hold, name="aidw-review-run")
    holder.start()
    assert entered.wait(timeout=60), "the holding run never reached a stage"

    refused = review_workflow.run(pr=7, **roots)

    release.set()
    holder.join(timeout=60)
    assert not holder.is_alive()
    assert "error" not in outcome, outcome.get("error")

    assert refused == 4
    assert outcome["code"] == 0
    assert len(list(_runs_root(worktree_repo.control).iterdir())) == 1
    assert "another aidw run is already active" in capsys.readouterr().err


@pytest.mark.parametrize(("review_text", "expected"), [(APPROVED_REVIEW, 0), (BLOCKED_REVIEW, 3)])
def test_the_lock_is_released_on_every_exit_path(
    worktree_repo, monkeypatch, review_text: str, expected: int
) -> None:
    _patch(monkeypatch)
    monkeypatch.setattr(review_workflow, "run_stage", _FakeStages(review_text))
    roots = _roots(worktree_repo.control)

    assert review_workflow.run(pr=7, **roots) == expected

    with lock.acquire(roots["workspace"].state_root, worktree_repo.task):
        pass
