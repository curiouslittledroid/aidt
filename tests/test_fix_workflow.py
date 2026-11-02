"""Tests for the ``aidw fix`` workflow (design §8.4, Phase 6)."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

from aidw import git, github, lock
from aidw.config import ERROR, WARNING, Issue
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
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


def _git_run(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "aidt").mkdir()


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


def _control_only(tmp_path: Path) -> Path:
    """Control root with **no** PR-head worktree (the missing-worktree layout, E2.6)."""
    _bare, control = _make_bare_with_control(tmp_path)
    return control


def _fix_layout(tmp_path: Path, branch: str = "03-E4.1") -> tuple[Path, Path]:
    """Control root plus the PR-head worktree created with real git (E2.6)."""
    _bare, control = _make_bare_with_control(tmp_path)
    worktree = git.add_worktree(control, branch)
    assert worktree is not None
    return control, worktree


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
        self.repo_roots: list[Path] = []
        self.review_text = review_text

    def __call__(self, spec, **kwargs):
        self.names.append(spec.name)
        self.specs.append(spec)
        self.repo_roots.append(kwargs["repo_root"])
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


def _patch(monkeypatch, *, branch="03-E4.1", select_impl=None, view=None, gh=True):
    monkeypatch.setattr(fix_workflow, "load_all", lambda aidt, repo: ({}, []))
    monkeypatch.setattr(github, "gh_available", lambda: gh)
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
    control, worktree = _fix_layout(tmp_path)
    _patch(monkeypatch, select_impl=_select_seq([_select_ok()]))
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), dry_run=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "child:  #101 Fix the loop" in out
    assert "iter1-fix-next-review-followup" in out
    assert "review-findings-to-github" in out
    # The PR-head worktree is located and planned against (E2.6 req 3/req 6).
    assert f"worktree (planned): {worktree}" in out
    assert stages.names[0] == "round1-approve-review-followups"
    assert stages.repo_roots and all(root == worktree for root in stages.repo_roots)


def test_no_available_child_is_success(tmp_path: Path, monkeypatch) -> None:
    control, worktree = _fix_layout(tmp_path)
    _patch(monkeypatch, select_impl=_select_seq([_select_none()]))
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 0
    assert stages.names == ["round1-approve-review-followups"]
    assert stages.repo_roots == [worktree]
    # The approve step must not succeed on the agent's exit code alone (design §10).
    assert callable(stages.specs[0].verify)


def test_clean_iteration_closes_child(tmp_path: Path, monkeypatch) -> None:
    control, worktree = _fix_layout(tmp_path)
    _patch(
        monkeypatch,
        select_impl=_select_seq([_select_ok(), _select_ok(), _select_none()]),
    )
    stages = _FakeStages(APPROVE_REVIEW)
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 0
    assert stages.names == [
        "round1-approve-review-followups",
        "iter1-fix-next-review-followup",
        "iter1-test",
        "iter1-code-review",
    ]
    assert all(root == worktree for root in stages.repo_roots)
    state = next(_runs_root(control).iterdir())
    payload = json.loads((state / "artifacts" / "fix.json").read_text(encoding="utf-8"))
    assert payload["iterations"] == 1
    assert payload["closed_issues"][0]["number"] == 101


def test_run_state_records_the_pr_head_worktree(tmp_path: Path, monkeypatch) -> None:
    control, worktree = _fix_layout(tmp_path)
    _patch(monkeypatch, select_impl=_select_seq([_select_none()]))
    monkeypatch.setattr(fix_workflow, "run_stage", _FakeStages())

    assert fix_workflow.run(pr=7, **_roots(control), approve_all=True) == 0

    state = fix_workflow.list_runs(_runs_root(control))[-1]
    assert state.repo_root == str(worktree)


def test_reloaded_worktree_config_error_is_usage_error(
    tmp_path: Path, monkeypatch
) -> None:
    control, worktree = _fix_layout(tmp_path)
    _patch(monkeypatch, select_impl=_select_seq([_select_none()]))
    calls: list[Path] = []

    def load_for_root(_aidt: Path, repo_root: Path):
        calls.append(repo_root)
        if repo_root == worktree:
            return {}, [Issue(ERROR, "config", "bad config in PR worktree")]
        return {}, []

    monkeypatch.setattr(fix_workflow, "load_all", load_for_root)
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 2
    assert calls == [control.resolve(), worktree]
    assert stages.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []


def _independence_warning() -> Issue:
    # ``check_independence`` emits this from inside ``load_all`` for every root alike:
    # the models come from the toolkit agent configs, not the repo (issue #58).
    return Issue(
        WARNING,
        "code-reviewer",
        "model matches `implementer` (test/model); "
        "the workflow requires reviewer != author",
    )


def test_strict_independence_warning_refuses_without_force_model(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    control, _worktree = _fix_layout(tmp_path)
    _patch(monkeypatch, select_impl=_select_seq([_select_none()]))
    monkeypatch.setattr(
        fix_workflow, "load_all", lambda _aidt, _repo: ({}, [_independence_warning()])
    )
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True, strict=True)

    # The warning itself stays fatal under --strict without the explicit override.
    assert code == 2
    assert stages.names == []
    assert "reviewer != author" in capsys.readouterr().err


def test_force_model_overrides_reloaded_worktree_independence_warning(
    tmp_path: Path, monkeypatch
) -> None:
    control, worktree = _fix_layout(tmp_path)
    _patch(monkeypatch, select_impl=_select_seq([_select_none()]))
    calls: list[Path] = []

    def load_for_root(_aidt: Path, repo_root: Path):
        calls.append(repo_root)
        return {}, [_independence_warning()]

    monkeypatch.setattr(fix_workflow, "load_all", load_for_root)
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(
        pr=7, **_roots(control), approve_all=True, strict=True, force_model=True
    )

    # Both loads warn identically; --force-model must override the reloaded
    # worktree check exactly as it overrides the control-root preflight (issue #58).
    assert calls == [control.resolve(), worktree]
    assert code == 0
    assert stages.names == ["round1-approve-review-followups"]
    assert stages.repo_roots == [worktree]
    state = fix_workflow.list_runs(_runs_root(control))[-1]
    assert state.pr["force_model"] is True


def test_findings_trigger_publish_and_second_approval(tmp_path: Path, monkeypatch) -> None:
    control, _worktree = _fix_layout(tmp_path)
    _patch(
        monkeypatch,
        select_impl=_select_seq([_select_ok(), _select_ok(), _select_ok(), _select_none()]),
    )
    stages = _FakeStages(FINDINGS_REVIEW)
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 0
    assert "iter1-review-findings-to-github" in stages.names
    assert "round2-approve-review-followups" in stages.names
    gate_names = [g.name for g in _gates(control)]
    assert gate_names == ["approve-followups", "approve-followups"]


def _gates(repo: Path):
    from aidw import state as state_mod

    run = state_mod.list_runs(_runs_root(repo))[-1]
    return run.gates


def test_gate_denied_stops_before_approver(tmp_path: Path, monkeypatch) -> None:
    control, _worktree = _fix_layout(tmp_path)
    _patch(monkeypatch, select_impl=_select_seq([_select_ok()]))
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    # No --yes and a non-interactive session: the gate fails closed.
    code = fix_workflow.run(pr=7, **_roots(control))

    assert code == 3
    assert stages.names == []


def test_max_iterations_bounds_the_loop(tmp_path: Path, monkeypatch) -> None:
    control, _worktree = _fix_layout(tmp_path)
    _patch(monkeypatch, select_impl=_select_seq([_select_ok(), _select_ok()]))
    stages = _FakeStages(APPROVE_REVIEW)
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(
        pr=7, **_roots(control), approve_all=True, max_iterations=1
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
    assert fix_workflow.run(pr=7, **_roots(tmp_path)) == 4


def test_missing_pr_head_worktree_is_refused_with_the_command(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    control = _control_only(tmp_path)  # PR head known, no local worktree
    _patch(monkeypatch)
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control))

    assert code == 4
    assert stages.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []
    command = (
        f"git -C {tmp_path / 'main'} worktree add -b 03-E4.1 "
        f"{tmp_path / '03-E4.1'} main"
    )
    assert command in capsys.readouterr().err


def test_missing_pr_head_worktree_dry_run_plans_the_command(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    control = _control_only(tmp_path)
    _patch(monkeypatch, select_impl=_select_seq([_select_ok()]))
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), dry_run=True)

    assert code == 0
    out = capsys.readouterr().out
    command = (
        f"git -C {tmp_path / 'main'} worktree add -b 03-E4.1 "
        f"{tmp_path / '03-E4.1'} main"
    )
    assert f"branch-setup (planned): {command}" in out
    assert "branch: 03-E4.1" in out
    # No worktree to plan in: the F-rounds fall back to the control root, still exit 0.
    assert stages.repo_roots and all(root == control for root in stages.repo_roots)


def test_dry_run_unanswerable_pr_read_is_branch_unknown(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    control = _control_only(tmp_path)
    _patch(monkeypatch, gh=False, select_impl=_select_seq([_select_ok()]))
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=0, **_roots(control), dry_run=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "branch: unknown (`gh` not found)" in out
    assert stages.repo_roots and all(root == control for root in stages.repo_roots)


def test_preflight_missing_pr(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(github, "pr_view", lambda repo, pr: None)
    monkeypatch.setattr(fix_workflow, "run_stage", _FakeStages())
    assert fix_workflow.run(pr=7, **_roots(tmp_path)) == 2


def test_zero_max_iterations_is_usage_error(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(fix_workflow, "run_stage", _FakeStages())
    assert (
        fix_workflow.run(
            pr=7, **_roots(tmp_path), max_iterations=0
        )
        == 2
    )

# --------------------------------------------------------------------------- #
# One run per worktree (E2.7, EXTRACTION.md §3.2/§3.10)
# --------------------------------------------------------------------------- #


def _two_pr_head_worktrees(
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict[int, str]]:
    """Control root plus two PR-head worktrees, and a pr -> head-branch map."""
    _bare, control = _make_bare_with_control(tmp_path)
    first = git.add_worktree(control, "03-E4.1")
    second = git.add_worktree(control, "03-E4.2")
    assert first is not None and second is not None
    return control, first, second, {7: "03-E4.1", 8: "03-E4.2"}


def test_a_held_pr_head_worktree_lock_is_refused_before_any_run_state(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The key is the re-resolved PR-head worktree, not the control root.

    A lock keyed on the pre-re-resolve control root would not be held here, so this run
    would proceed and the test would fail.
    """
    control, worktree = _fix_layout(tmp_path)
    _patch(monkeypatch, select_impl=_select_seq([_select_none()]))
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)
    roots = _roots(control)

    with lock.acquire(roots["workspace"].state_root, worktree):
        code = fix_workflow.run(pr=7, **roots, approve_all=True)

    assert code == 4
    assert stages.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []
    err = capsys.readouterr().err
    assert "another aidw run is already active" in err
    assert str(worktree) in err


def test_two_concurrent_fix_runs_on_the_pr_head_are_refused(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A live peer is refused *by the lock* and leaves no second run directory.

    ``_latest_fix_run`` stays branch-keyed (E2.7 req 5) and would refuse the second run
    first, before it could reach the lock — the second run's check reads ``state.json``
    before the first has written it, which is exactly the race the lock closes. The test
    therefore neutralises that guard (and only that guard) to exercise the lock itself.
    """
    control, worktree = _fix_layout(tmp_path)
    _patch(monkeypatch, select_impl=_select_seq([_select_none()]))
    monkeypatch.setattr(fix_workflow, "_latest_fix_run", lambda runs_root, branch: None)
    entered, release = threading.Event(), threading.Event()

    class _BlockingStages(_FakeStages):
        def __call__(self, spec, **kwargs):
            entered.set()
            assert release.wait(timeout=60), "the holder was never released"
            return super().__call__(spec, **kwargs)

    holder_stages = _BlockingStages()
    monkeypatch.setattr(fix_workflow, "run_stage", holder_stages)
    roots = _roots(control)
    outcome: dict = {}

    def hold() -> None:
        try:
            outcome["code"] = fix_workflow.run(pr=7, **roots, approve_all=True)
        except BaseException as exc:  # pragma: no cover - asserted via ``outcome``
            outcome["error"] = exc

    holder = threading.Thread(target=hold, name="aidw-fix-run")
    holder.start()
    assert entered.wait(timeout=60), "the holding run never reached a stage"

    refused = fix_workflow.run(pr=7, **roots, approve_all=True)

    release.set()
    holder.join(timeout=60)
    assert not holder.is_alive()
    assert "error" not in outcome, outcome.get("error")

    assert refused == 4
    assert outcome["code"] == 0
    assert len(list(_runs_root(control).iterdir())) == 1
    err = capsys.readouterr().err
    assert "another aidw run is already active" in err
    assert str(worktree) in err


def test_fix_runs_in_different_worktrees_proceed(tmp_path: Path, monkeypatch) -> None:
    """Two PR heads are two keys, so both runs proceed (a repo-root key would refuse)."""
    control, first, second, heads = _two_pr_head_worktrees(tmp_path)
    _patch(monkeypatch, select_impl=_select_seq([]))
    monkeypatch.setattr(
        github,
        "pr_view",
        lambda repo, pr: {
            "number": pr,
            "url": f"https://github.com/o/r/pull/{pr}",
            "baseRefName": "main",
            "headRefName": heads[pr],
        },
    )
    entered = {first: threading.Event(), second: threading.Event()}
    release = threading.Event()

    class _PerWorktreeStages(_FakeStages):
        def __call__(self, spec, **kwargs):
            entered.setdefault(kwargs["repo_root"], threading.Event()).set()
            assert release.wait(timeout=60), "the runs were never released"
            return super().__call__(spec, **kwargs)

    monkeypatch.setattr(fix_workflow, "run_stage", _PerWorktreeStages())
    roots = _roots(control)
    outcomes: dict[int, dict] = {7: {}, 8: {}}

    def run_pr(pr: int) -> None:
        try:
            outcomes[pr]["code"] = fix_workflow.run(pr=pr, **roots, approve_all=True)
        except BaseException as exc:  # pragma: no cover - asserted via ``outcomes``
            outcomes[pr]["error"] = exc

    threads = [
        threading.Thread(target=run_pr, args=(pr,), name=f"aidw-fix-{pr}")
        for pr in (7, 8)
    ]
    for thread in threads:
        thread.start()
    assert entered[first].wait(timeout=60) and entered[second].wait(timeout=60)
    release.set()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive()

    assert outcomes[7].get("code") == 0, outcomes[7].get("error")
    assert outcomes[8].get("code") == 0, outcomes[8].get("error")
    states = fix_workflow.list_runs(_runs_root(control))
    assert {state.repo_root for state in states} == {str(first), str(second)}


def test_the_worktree_lock_is_released_after_the_run(
    tmp_path: Path, monkeypatch
) -> None:
    """Even a run that walks the whole fix loop frees its key before returning."""
    control, worktree = _fix_layout(tmp_path)
    _patch(
        monkeypatch,
        select_impl=_select_seq([_select_ok(), _select_ok(), _select_none()]),
    )
    monkeypatch.setattr(fix_workflow, "run_stage", _FakeStages(APPROVE_REVIEW))
    roots = _roots(control)

    assert fix_workflow.run(pr=7, **roots, approve_all=True) == 0

    with lock.acquire(roots["workspace"].state_root, worktree):
        pass
