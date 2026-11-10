"""Tests for the ``aidw fix`` workflow (design §8.4, Phase 6; H3.3's post-loop tick).

The post-loop roadmap tick (`H3.3`) is exercised with fake ``select`` payloads and the fake
``run_stage`` below — never a real Pi model (design §15). Its three skip reasons, its
task-id resolution and its once-per-run position are all asserted from run state.
"""

from __future__ import annotations

import json
import random
import subprocess
import threading
from dataclasses import replace
from pathlib import Path

from aidw import git, github, lock
from aidw.config import ERROR, WARNING, AgentConfig, Issue, SystemPrompt
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.state import (
    FAILED,
    SKIP_REASON_KEY,
    SKIPPED,
    SUCCEEDED,
    StageRecord,
    create_run,
    run_dir,
)
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

    def _next(aidt, repo, pr, timeout=github.DEFAULT_TIMEOUT, **_kwargs):
        return queue.pop(0) if queue else _select_none()

    return _next


class _FakeStages:
    """The fake ``run_stage``: writes each stage's ``.out.txt`` and a succeeded record.

    ``failing`` names the stages that must come back ``failed`` (H3.3's red ``iter{N}-test``
    case), so the workflow's own stop path runs exactly as a real red stage's would.
    """

    def __init__(
        self, review_text: str = APPROVE_REVIEW, *, failing: tuple[str, ...] = ()
    ) -> None:
        self.names: list[str] = []
        self.specs: list = []
        self.repo_roots: list[Path] = []
        self.review_text = review_text
        self.failing = failing

    @staticmethod
    def _apply_tick(spec) -> None:
        """Play the recorder agent's part: flip the checkbox ``I7``'s variables name.

        The workflow re-reads the file and requires exactly the target line to flip, so a
        fake stage that wrote nothing would (correctly) fail the postcondition.
        """
        roadmap_file = Path(spec.variables[0])
        lines = roadmap_file.read_text(encoding="utf-8").splitlines(keepends=True)
        for index, line in enumerate(lines):
            if f"**{spec.variables[1]}." in line and "- [ ]" in line:
                lines[index] = line.replace("- [ ]", "- [x]", 1)
                break
        roadmap_file.write_text("".join(lines), encoding="utf-8")

    def __call__(self, spec, **kwargs):
        self.names.append(spec.name)
        self.specs.append(spec)
        self.repo_roots.append(kwargs["repo_root"])
        if spec.name == "update-roadmap" and not kwargs.get("dry_run"):
            self._apply_tick(spec)
        directory = run_dir(kwargs["runs_root"], kwargs["state"].run_id)
        stages = directory / "stages"
        stages.mkdir(parents=True, exist_ok=True)
        out = stages / f"{spec.name}.out.txt"
        out.write_text(
            self.review_text if spec.name.endswith("code-review") else "ok\n",
            encoding="utf-8",
        )
        failed = spec.name in self.failing
        record = StageRecord(
            name=spec.name,
            agent=spec.agent_id,
            model="test/model",
            status=FAILED if failed else SUCCEEDED,
            error="the re-test failed" if failed else None,
            # The empty code-review case below models H1.1's double-truncation result.
            stop_reason="length" if spec.name.endswith("code-review") and not self.review_text else None,
            attempts=2 if spec.name.endswith("code-review") and not self.review_text else None,
            artifacts={"out": str(out)},
        )
        kwargs["state"].record_stage(record)
        return record


def _patch(monkeypatch, *, branch="03-E4.1", select_impl=None, view=None, gh=True):
    # The real agent dict's shape matters since H3.3: a skipped post-loop stage is recorded
    # through `record_skipped`, which resolves the `recorder` agent's qualified model.
    monkeypatch.setattr(
        fix_workflow, "load_all", lambda aidt, repo, **_kwargs: (_AGENTS, [])
    )
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


def test_empty_code_review_names_both_truncated_attempts(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    control, _worktree = _fix_layout(tmp_path)
    _patch(
        monkeypatch,
        select_impl=_select_seq([_select_ok(), _select_ok(), _select_none()]),
    )
    monkeypatch.setattr(fix_workflow, "run_stage", _FakeStages(""))

    assert fix_workflow.run(pr=7, **_roots(control), approve_all=True) == 1

    stderr = capsys.readouterr().err
    assert "iter1-code-review: both attempts produced no final message" in stderr
    assert "final stop_reason: length" in stderr
    assert "both attempts were truncated" in stderr


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

    def load_for_root(_aidt: Path, repo_root: Path, **_kwargs):
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
        fix_workflow, "load_all", lambda _aidt, _repo, **_kwargs: ({}, [_independence_warning()])
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

    def load_for_root(_aidt: Path, repo_root: Path, **_kwargs):
        calls.append(repo_root)
        return _AGENTS, [_independence_warning()]

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


# --------------------------------------------------------------------------- #
# core vs repo-optional preflight (E4.5a, D12/D13, EXTRACTION.md §3.5)
# --------------------------------------------------------------------------- #


def test_a_disabled_core_approver_is_refused_before_any_side_effect(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Prompt-fixed: A1 (approve) is core — only I3/I4 are repo-optional."""
    control, _worktree = _fix_layout(tmp_path)
    config = control / "aidw" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    # A1 disabled and I7 declared: the refusal must be about the disabled core approver
    # alone (since H3.3 a declared `fix` list must also carry I7, req 2).
    config.write_text(
        "schema_version: 1\n"
        "workflows:\n"
        "  fix:\n"
        "    stages:\n"
        "      - id: A1\n"
        "        enabled: false\n"
        "      - id: I7\n",
        encoding="utf-8",
    )
    _patch(monkeypatch, select_impl=_select_seq([_select_ok()]))
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), dry_run=True)

    assert code == 2
    err = capsys.readouterr().err
    assert "workflows.fix.stages" in err
    assert "A1" in err
    assert "core stage cannot be disabled" in err
    assert stages.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []


# --------------------------------------------------------------------------- #
# repo-added stages in a name-keyed workflow (E4.5b req 2/req 5)
# --------------------------------------------------------------------------- #

#: The declared `prompt:` of a repo-added fix stage, relative to the target root.
REPO_ADDED_PROMPT = "aidw/prompts/repo-added.md"

#: A1, the post-loop I7 (a declared `fix` list must carry it — H3.3 req 2) and a repo-added
#: one, which `fix`'s name-keyed consumer never runs: E4.5b's non-goal, warned about rather
#: than silently dropped.
_CONFIG_WITH_REPO_ADDED = (
    "schema_version: 1\n"
    "workflows:\n"
    "  fix:\n"
    "    stages:\n"
    "      - id: A1\n"
    "      - id: I7\n"
    "      - id: repo-added-review\n"
    "        agent: code-reviewer\n"
    "        prompt: aidw/prompts/repo-added.md\n"
)


def _agent(agent_id: str, model: str) -> AgentConfig:
    """A minimal agent config for the faked ``load_all`` — an id, a provider, a model.

    Every stage id ``fix`` can reach is present, including the shared tick's ``recorder``:
    :func:`aidw.runner.record_skipped` resolves the agent it *would* have run so the skip
    names its model, and a missing id there is a ``ValueError`` by design (H3.2 req 4).
    """
    return AgentConfig(
        id=agent_id,
        description="",
        provider="test",
        model=model,
        thinking="off",
        system_prompt=SystemPrompt(),
        agents_md=None,
        agents_md_content=None,
        tools=[],
        skills=[],
        extensions=[],
        prompt_templates=[],
        mcp_config=None,
        cwd=Path("/"),
        env={},
        session="fresh",
        timeout_seconds=60,
        max_cost_usd=None,
        output="text",
        no_context_files=False,
        source_path=Path("/agents") / f"{agent_id}.yaml",
    )


#: Stand-in agent configs: `load_all` is faked, so only the ids and models matter — a
#: repo-added stage's declared `agent` is *existence*-checked against this dict (E4.5b
#: req 4), and the reviewer-rotation check sees distinct models (so it adds no warning).
_AGENTS = {
    agent_id: _agent(agent_id, f"{agent_id}-model")
    for agent_id in ("review-approver", "fixer", "tester", "code-reviewer", "recorder")
}


def _write_repo_added_prompt(*roots: Path) -> None:
    """Write the repo-added stage's prompt into each root.

    The preflight resolves it against the **control** root (the tree under check) and the
    plan against the located PR-head **worktree**, so a real-run test needs it in both —
    exactly as a committed repo prompt file is.
    """
    for root in roots:
        path = root / REPO_ADDED_PROMPT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# repo-added stage\n", encoding="utf-8")


def _write_stages_config(control: Path, text: str) -> None:
    config = control / "aidw" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(text, encoding="utf-8")


def test_a_repo_added_stage_is_accepted_and_warned_about(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 2/req 5: accepted, warned about by id, never a silent drop."""
    control, worktree = _fix_layout(tmp_path)
    _write_stages_config(control, _CONFIG_WITH_REPO_ADDED)
    _write_repo_added_prompt(control, worktree)
    _patch(monkeypatch, select_impl=_select_seq([_select_ok()]))
    monkeypatch.setattr(
        fix_workflow, "load_all", lambda aidt, repo, **_kwargs: (_AGENTS, [])
    )
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), dry_run=True)

    assert code == 0
    assert "stage `repo-added-review`" in capsys.readouterr().err
    # The dry run shows the declared plan (a repo-added entry is planned, E4.5b req 1) ...
    assert "repo-added-review" in stages.names
    assert "round1-approve-review-followups" in stages.names


def test_a_repo_added_stage_never_runs_in_a_real_fix_run(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 2: the name-keyed real path runs A1 and the iteration only — never X9."""
    control, worktree = _fix_layout(tmp_path)
    _write_stages_config(control, _CONFIG_WITH_REPO_ADDED)
    _write_repo_added_prompt(control, worktree)
    _patch(monkeypatch, select_impl=_select_seq([_select_none()]))
    monkeypatch.setattr(
        fix_workflow, "load_all", lambda aidt, repo, **_kwargs: (_AGENTS, [])
    )
    stages = _FakeStages(APPROVE_REVIEW)
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 0
    assert stages.names == ["round1-approve-review-followups"]


def test_a_repo_added_stage_with_a_missing_prompt_is_refused(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 5: exit 2 via ``format_issues``, before any run record or worktree."""
    control, _worktree = _fix_layout(tmp_path)
    _write_stages_config(control, _CONFIG_WITH_REPO_ADDED)
    _patch(monkeypatch, select_impl=_select_seq([_select_ok()]))
    monkeypatch.setattr(
        fix_workflow, "load_all", lambda aidt, repo, **_kwargs: (_AGENTS, [])
    )
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), dry_run=True)

    assert code == 2
    err = capsys.readouterr().err
    assert "error: workflows.fix.stages: " in err
    assert "`repo-added-review`" in err
    assert "prompt does not resolve" in err
    assert stages.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []


def test_a_repo_added_stage_with_an_unknown_agent_is_refused(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 4/req 5: an unknown declared ``agent`` refuses here, not in ``run_stage``."""
    control, worktree = _fix_layout(tmp_path)
    _write_stages_config(
        control, _CONFIG_WITH_REPO_ADDED.replace("agent: code-reviewer", "agent: nobody")
    )
    _write_repo_added_prompt(control, worktree)
    _patch(monkeypatch, select_impl=_select_seq([_select_ok()]))
    monkeypatch.setattr(
        fix_workflow, "load_all", lambda aidt, repo, **_kwargs: (_AGENTS, [])
    )
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), dry_run=True)

    assert code == 2
    err = capsys.readouterr().err
    assert "`repo-added-review`" in err
    assert "unknown agent `nobody`" in err
    assert stages.names == []


# --------------------------------------------------------------------------- #
# The post-loop roadmap tick (H3.3, design §8.4)
# --------------------------------------------------------------------------- #

#: The roadmap file the default config's ``paths.roadmap_dir``/``paths.roadmap_glob`` read
#: (``docs/tasks`` / ``[0-9]* - *.md``), relative to the PR-head worktree.
ROADMAP_REL = "docs/tasks/03 - Stage resilience.md"


def _roadmap_text(*, task: str = "H3.3", phase: str = "03", done: bool = False) -> str:
    """One phase file holding a single roadmap entry (H3.1's format, design §11)."""
    box = "x" if done else " "
    return (
        f"# Phase {phase}: Stage resilience\n\n"
        "## Epic H3: Ticks\n\n"
        f"- [{box}] **{task}. Give `fix` the same tick** a task description.\n"
        "  - Done when: the box is ticked.\n"
    )


def _write_roadmap(root: Path, text: str | None = None) -> Path:
    """Write the roadmap into ``root`` (the PR-head worktree) and return its path."""
    path = root / ROADMAP_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_roadmap_text() if text is None else text, encoding="utf-8")
    return path


def _state_of(control: Path):
    """The newest recorded run of the layout under ``control``."""
    return fix_workflow.list_runs(_runs_root(control))[-1]


def _tick_records(state) -> list[StageRecord]:
    return [record for record in state.stages if record.name == "update-roadmap"]


def _converging_select():
    """One approved fix, then ``EXIT_NONE_AVAILABLE``: the loop's converged exit.

    Three payloads, because the entry approval round reads ``select`` too (its gate
    summary): the approval's, the iteration's, then the empty one that ends the loop.
    """
    return _select_seq([_select_ok(), _select_ok(), _select_none()])


def test_a_converged_run_ticks_the_box_once_and_records_true(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H3.3 req 5/req 6/req 7: green evidence → one flip, ``roadmap_ticked: true``.

    The run is the canonical shape: one iteration whose re-review approves, then a
    ``select`` that finds nothing available. The stage must appear **once** per run — in
    ``state.stages``, in ``run.log``, in the fake stages' call list — and after the last
    iteration, never inside the loop.
    """
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    roadmap_file = _write_roadmap(worktree)
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 0
    assert roadmap_file.read_text(encoding="utf-8") == _roadmap_text(done=True)
    state = _state_of(control)
    assert state.pr["roadmap_ticked"] is True
    assert fix_workflow.PR_ROADMAP_TICK_SKIP_REASON not in state.pr
    records = _tick_records(state)
    assert len(records) == 1
    assert records[0].status == SUCCEEDED
    assert records[0].artifacts["tick"] == "flipped"
    # Once per run, and after the last iteration's stages (req 7).
    assert stages.names.count("update-roadmap") == 1
    assert stages.names[-1] == "update-roadmap"
    assert stages.names.index("update-roadmap") > stages.names.index("iter1-code-review")
    log = (run_dir(_runs_root(control), state.run_id) / "run.log").read_text(encoding="utf-8")
    assert log.count("roadmap H3.3") == 1
    assert "flipped `[ ]` -> `[x]`" in log


def test_a_tick_stage_that_does_not_flip_fails_closed(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 5/req 6: a successful agent exit is not enough without the shared postcondition."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    roadmap_file = _write_roadmap(worktree)
    before = roadmap_file.read_bytes()
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages()
    # Model a recorder that exits successfully but leaves the roadmap untouched.
    stages._apply_tick = lambda _spec: None
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    assert fix_workflow.run(pr=7, **_roots(control), approve_all=True) == 1

    state = _state_of(control)
    assert roadmap_file.read_bytes() == before
    assert state.pr["roadmap_ticked"] is False
    assert "postcondition not met" in state.pr[
        fix_workflow.PR_ROADMAP_TICK_SKIP_REASON
    ]
    record = _tick_records(state)[0]
    assert record.status == FAILED
    assert "postcondition not met" in (record.error or "")
    assert stages.names.count("update-roadmap") == 1


def test_an_already_ticked_box_stays_a_successful_no_op(
    tmp_path: Path, monkeypatch
) -> None:
    """H3.3 req 5: ``tick: already`` is ``succeeded`` and ``roadmap_ticked: true``."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    roadmap_file = _write_roadmap(worktree, _roadmap_text(done=True))
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    monkeypatch.setattr(fix_workflow, "run_stage", _FakeStages())

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 0
    assert roadmap_file.read_text(encoding="utf-8") == _roadmap_text(done=True)
    state = _state_of(control)
    assert state.pr["roadmap_ticked"] is True
    records = _tick_records(state)
    assert len(records) == 1
    assert records[0].status == SUCCEEDED
    assert records[0].artifacts["tick"] == "already"


def test_max_iterations_ticks_nothing_and_records_why(
    tmp_path: Path, monkeypatch
) -> None:
    """H3.3 req 1/req 4(a): a ``--max-iterations`` stop never converges, so no tick."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    roadmap_file = _write_roadmap(worktree)
    before = roadmap_file.read_bytes()
    # One payload for the entry approval round, one for the iteration that then runs out
    # of budget: the loop never reaches `EXIT_NONE_AVAILABLE`.
    _patch(
        monkeypatch, branch="03-H3.3", select_impl=_select_seq([_select_ok(), _select_ok()])
    )
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True, max_iterations=1)

    assert code == 3
    assert roadmap_file.read_bytes() == before
    state = _state_of(control)
    assert state.pr["roadmap_ticked"] is False
    assert "--max-iterations" in state.pr[fix_workflow.PR_ROADMAP_TICK_SKIP_REASON]
    records = _tick_records(state)
    assert len(records) == 1
    assert records[0].status == SKIPPED
    assert "--max-iterations" in records[0].artifacts[SKIP_REASON_KEY]
    assert "update-roadmap" not in stages.names


def test_a_denied_approve_fix_pr_gate_ticks_nothing(tmp_path: Path, monkeypatch) -> None:
    """H3.3 req 1/req 4(a): a denied gate stops the loop before it converges."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    roadmap_file = _write_roadmap(worktree)
    before = roadmap_file.read_bytes()
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(
        pr=7,
        **_roots(control),
        approve_all=True,
        deny_gates=[fix_workflow.GATE_FIX_PR],
    )

    assert code == 3
    assert roadmap_file.read_bytes() == before
    state = _state_of(control)
    assert state.pr["roadmap_ticked"] is False
    assert fix_workflow.GATE_FIX_PR in state.pr[fix_workflow.PR_ROADMAP_TICK_SKIP_REASON]
    assert _tick_records(state)[0].status == SKIPPED
    assert "update-roadmap" not in stages.names


def test_a_denied_entry_approval_gate_ticks_nothing(tmp_path: Path, monkeypatch) -> None:
    """H3.3 req 1: the entry approval round is a stop too, and records its own reason."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    roadmap_file = _write_roadmap(worktree)
    before = roadmap_file.read_bytes()
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(
        pr=7, **_roots(control), deny_gates=[fix_workflow.GATE_FOLLOWUPS]
    )

    assert code == 3
    assert roadmap_file.read_bytes() == before
    state = _state_of(control)
    assert state.pr["roadmap_ticked"] is False
    assert "approve-followups" in state.pr[fix_workflow.PR_ROADMAP_TICK_SKIP_REASON]
    assert _tick_records(state)[0].status == SKIPPED
    assert stages.names == []


def test_a_failed_retest_ticks_nothing_and_records_why(
    tmp_path: Path, monkeypatch
) -> None:
    """H3.3 req 4(b): a red ``iter{N}-test`` is no green evidence for a completion claim."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    roadmap_file = _write_roadmap(worktree)
    before = roadmap_file.read_bytes()
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages(failing=("iter1-test",))
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 1
    assert roadmap_file.read_bytes() == before
    state = _state_of(control)
    assert state.pr["roadmap_ticked"] is False
    assert "iter1-test" in state.pr[fix_workflow.PR_ROADMAP_TICK_SKIP_REASON]
    records = _tick_records(state)
    assert len(records) == 1
    assert records[0].status == SKIPPED
    assert "iter1-test" in records[0].artifacts[SKIP_REASON_KEY]
    assert "update-roadmap" not in stages.names


def test_an_empty_run_ticks_nothing(tmp_path: Path, monkeypatch) -> None:
    """H3.3 trap: the first ``select`` finding nothing closed nothing — no tick."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    roadmap_file = _write_roadmap(worktree)
    before = roadmap_file.read_bytes()
    _patch(monkeypatch, branch="03-H3.3", select_impl=_select_seq([_select_none()]))
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 0
    assert roadmap_file.read_bytes() == before
    state = _state_of(control)
    assert state.pr["roadmap_ticked"] is False
    assert "no re-review verdict" in state.pr[fix_workflow.PR_ROADMAP_TICK_SKIP_REASON]
    assert _tick_records(state)[0].status == SKIPPED
    assert stages.names == ["round1-approve-review-followups"]


def test_a_branch_with_no_roadmap_entry_skips_and_exits_zero(
    tmp_path: Path, monkeypatch
) -> None:
    """H3.3 req 3: a PR that is not an AIDT task still finishes successfully."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    # A roadmap that knows a different task only: the `(phase, task)` split resolves, the
    # entry does not.
    _write_roadmap(worktree, _roadmap_text(task="H3.1"))
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 0
    state = _state_of(control)
    assert state.pr["roadmap_ticked"] is False
    assert "no single roadmap entry" in state.pr[fix_workflow.PR_ROADMAP_TICK_SKIP_REASON]
    record = _tick_records(state)[0]
    assert record.status == SKIPPED
    assert record.agent == "recorder"
    assert record.error is None
    assert "update-roadmap" not in stages.names
    # The run itself still succeeded and still closed its follow-up.
    assert state.status == SUCCEEDED
    assert state.pr["closed_issues"]


def test_duplicate_roadmap_entries_skip_without_ticking(tmp_path: Path, monkeypatch) -> None:
    """Req 3: several roadmap matches are ambiguous and must succeed without a tick."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    duplicate = _roadmap_text() + "\n" + _roadmap_text()
    roadmap_file = _write_roadmap(worktree, duplicate)
    before = roadmap_file.read_bytes()
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    assert fix_workflow.run(pr=7, **_roots(control), approve_all=True) == 0

    state = _state_of(control)
    assert roadmap_file.read_bytes() == before
    assert state.pr["roadmap_ticked"] is False
    assert "2 roadmap entries match 03-H3.3" in state.pr[
        fix_workflow.PR_ROADMAP_TICK_SKIP_REASON
    ]
    assert _tick_records(state)[0].status == SKIPPED
    assert "update-roadmap" not in stages.names


def test_the_task_id_comes_from_the_newest_implement_run(
    tmp_path: Path, monkeypatch
) -> None:
    """H3.3 req 3: a recorded ``state.task`` wins over the branch name.

    The PR head here is ``feature/x``, which no ``{phase}-{task}`` split can reverse; only
    the newest ``implement`` run's recorded ``state.task`` can name the roadmap entry.
    """
    control, worktree = _fix_layout(tmp_path, branch="feature/x")
    roadmap_file = _write_roadmap(worktree)
    runs_root = _runs_root(control)
    older = create_run(
        runs_root,
        worktree,
        "implement",
        label="03-H3.1-older",
        task={"phase": "03", "task": "H3.1", "prompt_path": "docs/x.md"},
        branch="feature/x",
    )
    assert older is not None
    newest = create_run(
        runs_root,
        worktree,
        "implement",
        label="03-H3.3-newer",
        task={"phase": "03", "task": "H3.3", "prompt_path": "docs/y.md"},
        branch="feature/x",
    )
    assert newest is not None
    _patch(monkeypatch, branch="feature/x", select_impl=_converging_select())
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 0
    assert roadmap_file.read_text(encoding="utf-8") == _roadmap_text(done=True)
    state = _state_of(control)
    assert state.pr["roadmap_ticked"] is True
    tick_spec = next(spec for spec in stages.specs if spec.name == "update-roadmap")
    assert tick_spec.variables == [str(roadmap_file.resolve()), "H3.3"]


def test_a_newest_implement_run_without_task_falls_back_to_the_branch_pattern(
    tmp_path: Path,
) -> None:
    """Req 3: only the newest implement run is authoritative before branch fallback.

    A stale older run must not supply a task when the newest run has no usable
    ``state.task``. The specified fallback is reversing the PR-head branch, which resolves
    this ``03-H3.3`` branch to the roadmap entry rather than guessing from stale state.
    """
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    roadmap_file = _write_roadmap(worktree)
    runs_root = _runs_root(control)
    create_run(
        runs_root,
        worktree,
        "implement",
        label="03-H3.1-older",
        task={"phase": "03", "task": "H3.1", "prompt_path": "docs/x.md"},
        branch="03-H3.3",
    )
    create_run(
        runs_root,
        worktree,
        "implement",
        label="03-H3.3-newest",
        task={},
        branch="03-H3.3",
    )

    # Import the resolver here rather than reaching through the workflow's implementation
    # details: this is the same resolved default config a real fix preflight supplies.
    from aidw.target_config import TargetConfig, resolve_config

    target = fix_workflow.resolve_roadmap_target(
        runs_root=runs_root,
        branch="03-H3.3",
        branch_pattern="{phase}-{task}",
        repo_root=worktree,
        config=resolve_config(TargetConfig()),
    )

    assert target.roadmap_file == roadmap_file.resolve()
    assert (target.phase, target.task) == ("03", "H3.3")


def test_the_branch_pattern_is_reversed_when_no_implement_run_records_the_task(
    tmp_path: Path, monkeypatch
) -> None:
    """H3.3 req 3: a non-default pattern (other literals, other field order) reverses."""
    branch = "H3.3-on-03"
    pattern = "{task}-on-{phase}"
    control, worktree = _fix_layout(tmp_path, branch=branch)
    roadmap_file = _write_roadmap(worktree)
    _patch(monkeypatch, branch=branch, select_impl=_converging_select())
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)
    roots = _roots(control)
    roots["repo"] = replace(roots["repo"], branch_pattern=pattern)

    code = fix_workflow.run(pr=7, **roots, approve_all=True)

    assert code == 0
    assert roadmap_file.read_text(encoding="utf-8") == _roadmap_text(done=True)
    assert _state_of(control).pr["roadmap_ticked"] is True


def test_an_ambiguous_branch_skips_with_a_reason_instead_of_guessing(
    tmp_path: Path, monkeypatch
) -> None:
    """H3.3 trap: ``03-H3-3`` splits several ways, so the tick is withheld (exit 0).

    Under ``{phase}-{task}`` the branch admits ``03``/``H3-3`` and ``03-H3``/``3``. Picking
    either would be a guess, and ``roadmap.tick_entry``'s count check cannot catch a
    wrong-but-valid pair that matches a different real entry, so the resolution requires
    exactly one viable split.
    """
    control, worktree = _fix_layout(tmp_path, branch="03-H3-3")
    roadmap_file = _write_roadmap(worktree)
    before = roadmap_file.read_bytes()
    _patch(monkeypatch, branch="03-H3-3", select_impl=_converging_select())
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 0
    assert roadmap_file.read_bytes() == before
    state = _state_of(control)
    assert state.pr["roadmap_ticked"] is False
    reason = state.pr[fix_workflow.PR_ROADMAP_TICK_SKIP_REASON]
    assert "2 viable" in reason
    assert "exactly one is required" in reason


def test_the_dry_run_plans_the_tick_once_in_the_final_position(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H3.3 req 7: planned once, last, and no evidence is evaluated.

    The loop's real evidence would be red for this dry run's shape (a single approved child
    and no convergence), but a dry run evaluates none of it: the stage is planned.
    """
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    roadmap_file = _write_roadmap(worktree)
    before = roadmap_file.read_bytes()
    _patch(monkeypatch, branch="03-H3.3", select_impl=_select_seq([_select_ok()]))
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), dry_run=True)

    assert code == 0
    out = capsys.readouterr().out
    planned = [
        line
        for line in out.splitlines()
        if line.startswith("update-roadmap ")
    ]
    assert len(planned) == 1, out
    assert "(planned)" in planned[0]
    assert stages.names[-1] == "update-roadmap"
    # Nothing ran and nothing was evaluated: the roadmap is untouched.
    assert roadmap_file.read_bytes() == before
    assert _state_of(control).pr.get("roadmap_ticked") is None


def test_the_dry_run_reports_an_unresolvable_target_as_the_skip_it_would_record(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H3.3 req 7 + req 3: the dry run still shows the stage once, as the skip."""
    control, _worktree = _fix_layout(tmp_path, branch="03-H3.3")
    # No roadmap under the worktree at all.
    _patch(monkeypatch, branch="03-H3.3", select_impl=_select_seq([_select_ok()]))
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), dry_run=True)

    assert code == 0
    assert capsys.readouterr().out.count("update-roadmap") == 1
    assert "update-roadmap" not in stages.names
    state = _state_of(control)
    assert _tick_records(state)[0].status == SKIPPED
    assert state.pr["roadmap_ticked"] is False


# --------------------------------------------------------------------------- #
# The pure helpers: fix's green rule, the branch reversal, the test-stage shape
# --------------------------------------------------------------------------- #


def _record(name: str, status: str = SUCCEEDED) -> StageRecord:
    return StageRecord(name=name, agent="tester", model="test/model", status=status)


def test_is_test_stage_names_only_the_loops_retest() -> None:
    """Req 4(b)'s vocabulary: exactly ``iter{N}-test``, anchored on both ends."""
    for name in ("iter1-test", "iter12-test"):
        assert fix_workflow.is_test_stage(name)
    for name in (
        "test",
        "iter-test",
        "iter1-test-extra",
        "xiter1-test",
        "iter1-code-review",
        "round1-approve-review-followups",
        "iter1-test ",
        # Non-ASCII digits are not the registry's `{iteration}` rendering.
        "iter\u0661-test",
    ):
        assert not fix_workflow.is_test_stage(name), name


def test_the_green_rule_holds_for_a_converged_approved_run() -> None:
    """Req 4: green iff converged, every re-test succeeded, and the verdict is ``Approve``."""
    evidence = fix_workflow.tick_evidence(
        loop_closed=True,
        test_records=[_record("iter1-test"), _record("iter2-test")],
        latest_verdict="Approve",
    )
    assert evidence.green is True
    assert evidence.reason == ""


def test_the_green_rule_withholds_every_other_outcome() -> None:
    """One hand-calculated example per failing path, each with its own reason."""
    not_closed = fix_workflow.tick_evidence(
        loop_closed=False,
        test_records=[_record("iter1-test")],
        latest_verdict="Approve",
    )
    assert not_closed.green is False
    assert "converged" in not_closed.reason

    red_test = fix_workflow.tick_evidence(
        loop_closed=True,
        test_records=[_record("iter1-test"), _record("iter2-test", FAILED)],
        latest_verdict="Approve",
    )
    assert red_test.green is False
    assert "iter2-test" in red_test.reason
    assert "iter1-test" not in red_test.reason

    empty_run = fix_workflow.tick_evidence(
        loop_closed=True, test_records=[], latest_verdict=None
    )
    assert empty_run.green is False
    assert "no re-review verdict" in empty_run.reason

    requested = fix_workflow.tick_evidence(
        loop_closed=True,
        test_records=[_record("iter1-test")],
        latest_verdict="Request changes",
    )
    assert requested.green is False
    assert "`Request changes`" in requested.reason

    # A green verdict never carries a reason, and a withheld one always does.
    for evidence in (not_closed, red_test, empty_run, requested):
        assert evidence.reason != ""


def test_the_green_rule_is_pure() -> None:
    """Purity: no input mutation, no I/O, deterministic."""
    records = [_record("iter1-test"), _record("iter2-test", FAILED)]
    before = [(record.name, record.status) for record in records]

    first = fix_workflow.tick_evidence(
        loop_closed=True, test_records=records, latest_verdict="Approve"
    )
    second = fix_workflow.tick_evidence(
        loop_closed=True, test_records=records, latest_verdict="Approve"
    )

    assert first == second
    assert [(record.name, record.status) for record in records] == before
    assert fix_workflow.STOP_REASON.format(stop="a failed stage").startswith(
        "fix stopped before the loop converged"
    )


def test_reverse_branch_pattern_enumerates_every_viable_split() -> None:
    """Req 3's prompt-fixed rule, hand-calculated on the default pattern.

    ``03-H3.3`` has exactly one viable split; ``03-H3-3`` has two, and the caller requires
    exactly one — never a single greedy/lazy regex match.
    """
    assert fix_workflow.reverse_branch_pattern("03-H3.3", "{phase}-{task}") == [
        ("03", "H3.3")
    ]
    assert fix_workflow.reverse_branch_pattern("03-H3-3", "{phase}-{task}") == [
        ("03", "H3-3"),
        ("03-H3", "3"),
    ]


def test_reverse_branch_pattern_handles_other_literals_and_field_order() -> None:
    assert fix_workflow.reverse_branch_pattern("H3.3-on-03", "{task}-on-{phase}") == [
        ("03", "H3.3")
    ]
    assert fix_workflow.reverse_branch_pattern(
        "task-H3.3-phase-03", "task-{task}-phase-{phase}"
    ) == [("03", "H3.3")]
    assert fix_workflow.reverse_branch_pattern("03/H3.3", "{phase}/{task}") == [
        ("03", "H3.3")
    ]


def test_reverse_branch_pattern_fails_closed() -> None:
    """Anchored matching and malformed patterns both return no split, never a guess."""
    # Anchored on both ends: the pattern's own literals must match, so a branch with an
    # extra prefix or suffix that the literals cannot absorb is no split at all. (A leading
    # or trailing *field* absorbs anything, which is why these use a literal.)
    assert fix_workflow.reverse_branch_pattern("03-H3.3", "b/{phase}-{task}") == []
    assert fix_workflow.reverse_branch_pattern("03-H3.3", "{phase}-{task}-done") == []
    # An empty capture is not a split (each field is non-empty).
    assert fix_workflow.reverse_branch_pattern("-H3.3", "{phase}-{task}") == []
    assert fix_workflow.reverse_branch_pattern("03-", "{phase}-{task}") == []
    # Malformed patterns: missing a field, a repeated field, a spec, a conversion,
    # unbalanced braces — the same shapes `derive_branch_name` refuses.
    for pattern in (
        "{phase}",
        "{phase}-{epic}",
        "{phase}-{task}-{phase}",
        "{phase:>2}-{task}",
        "{phase!r}-{task}",
        "{phase}-{task",
        "{phase[idx]}-{task}",
    ):
        assert fix_workflow.reverse_branch_pattern("03-H3.3", pattern) == [], pattern


#: Pinned seed and run count for the property run below (AGENTS.md "Tests": pytest only, no
#: ``hypothesis``, so a reproducible sample is the generator and there is no shrinking).
REVERSAL_PROPERTY_SEED = 4331
REVERSAL_PROPERTY_RUNS = 60

#: Patterns the sample draws from: the §3.4 default, a different literal, a different
#: field order, a different separator, and a trailing literal.
REVERSAL_PATTERNS = (
    "{phase}-{task}",
    "{task}-on-{phase}",
    "{phase}/{task}",
    "task-{task}-phase-{phase}",
    "{phase}-{task}-done",
)
#: Ids the sample draws from, including ones containing the default separator.
REVERSAL_PHASES = ("03", "3.1", "00")
REVERSAL_TASKS = ("H3.3", "E4.1", "H3-3", "X", "H3.3.1")


def test_reverse_branch_pattern_is_a_faithful_inverse_property() -> None:
    """Seeded property run (seed/runs pinned above): every split is a real preimage.

    For every sampled ``(pattern, phase, task)``, the branch the pattern *produces* is
    reversed into a list that (1) always contains the generating pair, (2) contains only
    pairs that re-render to exactly that branch — the reversal invents nothing — (3) has no
    duplicates, and (4) has exactly one element whenever neither id can contain the
    separator, which is the case the caller requires before it resolves an entry. Also
    deterministic: a second call returns the same list.
    """
    rng = random.Random(REVERSAL_PROPERTY_SEED)

    for case in range(REVERSAL_PROPERTY_RUNS):
        pattern = rng.choice(REVERSAL_PATTERNS)
        phase = rng.choice(REVERSAL_PHASES)
        task = rng.choice(REVERSAL_TASKS)
        branch = pattern.format(phase=phase, task=task)

        splits = fix_workflow.reverse_branch_pattern(branch, pattern)

        assert (phase, task) in splits, (case, pattern, branch)
        for found_phase, found_task in splits:
            assert found_phase and found_task, (case, pattern, splits)
            assert pattern.format(phase=found_phase, task=found_task) == branch, (
                case,
                pattern,
                branch,
                splits,
            )
        assert len(set(splits)) == len(splits), (case, pattern, splits)
        if not any(char in phase or char in task for char in "-/"):
            assert len(splits) == 1, (case, pattern, branch, splits)
        assert fix_workflow.reverse_branch_pattern(branch, pattern) == splits
