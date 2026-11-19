"""Tests for the ``aidw fix`` workflow (design §8.4, Phase 6; H3.3's post-loop tick).

The post-loop roadmap tick (`H3.3`) is exercised with fake ``select`` payloads and the fake
``run_stage`` below — never a real Pi model (design §15). Its three skip reasons, its
task-id resolution and its once-per-run position are all asserted from run state.

Since 05-P1.2 the run also closes its follow-up issues, **after** the commit-and-push stage
has proved the push. That close is not an agent stage — ``fix.py`` runs the bundled
``review_followup.py close`` itself — so the fakes model it as a Python-side script call
(``_FakeStages.close_script``, installed over ``github.run_script``) and keep one ordered
timeline of what happened, which is what proves the issue was still ``OPEN`` at the push.
"""

from __future__ import annotations

import json
import random
import subprocess
import threading
from dataclasses import replace
from pathlib import Path

import pytest

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

    Since 05-P1.1 the fake also models the two writes the workflow *verifies*: an ``F1``
    stage leaves a real edit in the PR-head worktree (a real fixer edits the repo, so an
    untouched tree would be D3's fourth case, and the commit case would have nothing to
    commit), and ``F5 commit-and-push`` performs a real ``git add -A`` + ``git commit`` plus
    a real ``git update-ref`` for the remote-tracking ref a successful ``git push`` moves — no
    network, no fake git. ``push=False``, ``commit=False``, ``leave_dirty=True`` and
    ``discard=True`` model the failure modes without inventing a signal the workflow does
    not read.

    Since 05-P1.2 it also models the **deferred close**, which is *not* an agent stage: the
    workflow runs the bundled ``review_followup.py close`` itself, so :meth:`close_script` is
    installed as the fake ``github.run_script``. ``F1`` writes its closing comment body to
    the ``{closing_body}`` variable it was given, ``events`` records the push and the close in
    one timeline (so a test can prove the order), and ``issues`` is the fake GitHub state the
    close flips — ``OPEN`` when the push happened, ``CLOSED`` only afterwards.
    """

    def __init__(
        self,
        review_text: str = APPROVE_REVIEW,
        *,
        failing: tuple[str, ...] = (),
        push: bool = True,
        commit: bool = True,
        leave_dirty: bool = False,
        discard: bool = False,
        write_closing_body: bool = True,
        close_exit_code: int = 0,
        issues: dict[int, str] | None = None,
    ) -> None:
        self.names: list[str] = []
        self.specs: list = []
        self.repo_roots: list[Path] = []
        self.review_text = review_text
        self.failing = failing
        self.push = push
        self.commit = commit
        self.leave_dirty = leave_dirty
        self.discard = discard
        self.write_closing_body = write_closing_body
        self.close_exit_code = close_exit_code
        self.issues: dict[int, str] = dict(issues or {})
        #: One ordered timeline of what the run did: ``("stage", name)``, ``("push", state)``
        #: and ``("close", issue)``. The state snapshot at push time is *copied*, so the
        #: assertion "the issue was still OPEN before the push" cannot pass by accident.
        self.events: list[tuple[str, object]] = []
        #: Every ``close`` call the workflow made, in order.
        self.closes: list[dict] = []

    @staticmethod
    def _apply_fix_edit(spec, repo_root: Path) -> None:
        """Play the fixer's part: leave an uncommitted edit in the PR-head worktree."""
        path = repo_root / "fix-edits" / f"{spec.name}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixed", encoding="utf-8")

    def _write_closing_body(self, spec) -> None:
        """Play the fixer's other part: write the body to ``{closing_body}`` (P1.2 req 4)."""
        if not self.write_closing_body or len(spec.variables) < 2:
            return
        path = Path(spec.variables[1])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Implemented on the current PR branch.\n", encoding="utf-8")

    def close_script(self, argv: list[str], repo_root: Path) -> github.ScriptResult:
        """Model ``review_followup.py close`` as the workflow invokes it (P1.2 req 2/3).

        The one guard modelled here is the body check, because it is what the workflow
        depends on: a missing or empty ``--body-file`` must fail the close before any close
        action. The real script's label/state guards and its ``EXIT_VERIFY_FAILED`` are
        covered by ``prompts/scripts/review-followup/tests``.
        """
        command = argv[2]
        issue = int(argv[argv.index("--issue") + 1])
        body_file = (
            argv[argv.index("--body-file") + 1] if "--body-file" in argv else ""
        )
        self.closes.append(
            {
                "command": command,
                "issue": issue,
                "body_file": body_file,
                "argv": list(argv),
                "repo_root": repo_root,
            }
        )
        self.events.append(("close", issue))
        if self.close_exit_code:
            return github.ScriptResult(
                list(argv), self.close_exit_code, "", "error: close refused"
            )
        path = Path(body_file) if body_file else None
        if path is None or not path.is_file() or not path.read_text(encoding="utf-8").strip():
            return github.ScriptResult(
                list(argv),
                github.EXIT_ERROR,
                "",
                f"error: --body-file not usable: {body_file or '(missing)'}",
            )
        self.issues[issue] = "CLOSED"
        return github.ScriptResult(list(argv), github.EXIT_OK, "{}", "")

    def _apply_commit(self, repo_root: Path) -> None:
        """Play ``F5``'s part: commit the change set and move ``origin/<branch>`` to it."""
        if self.discard:
            # The PR #158 review finding's failure mode: the change set is stashed away
            # instead of committed, so `HEAD`, `origin/<branch>` and a clean tree all still
            # describe the *pre-existing* SHAs and only a HEAD-movement proof can tell.
            _git_run(repo_root, "stash", "push", "--include-untracked", "--quiet")
            branch = git.current_branch(repo_root)
            _git_run(repo_root, "update-ref", f"refs/remotes/origin/{branch}", "HEAD")
            return
        if self.commit:
            _git_run(repo_root, "add", "-A")
            _git_run(repo_root, "commit", "-qm", "fix: land the accumulated change set")
        if self.push:
            branch = git.current_branch(repo_root)
            _git_run(repo_root, "update-ref", f"refs/remotes/origin/{branch}", "HEAD")
            # The snapshot the deferred close is ordered against (P1.2 req 1/req 3): every
            # recorded issue is still open at the moment the push landed.
            self.events.append(("push", dict(self.issues)))
        if self.leave_dirty:
            (repo_root / "left-behind.txt").write_text("dirty", encoding="utf-8")

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
        self.events.append(("stage", spec.name))
        if not kwargs.get("dry_run"):
            if spec.name == "update-roadmap":
                self._apply_tick(spec)
            elif spec.name == "commit-and-push" and spec.name not in self.failing:
                self._apply_commit(kwargs["repo_root"])
            elif spec.name.endswith("fix-next-review-followup"):
                self._apply_fix_edit(spec, kwargs["repo_root"])
                self._write_closing_body(spec)
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

    def _run_script(argv, repo, timeout=600, *, config=None):
        """Route the bundled ``close`` call to the fake stage object (05-P1.2).

        ``_patch`` runs before a test constructs its ``_FakeStages``, so this resolves the
        fake lazily from the ``run_stage`` seam the test installs — one object then owns the
        whole timeline (stage, push, close). Without it the workflow would spawn the real
        script, which is neither network-free nor what these tests are proving.
        """
        close = getattr(fix_workflow.run_stage, "close_script", None)
        if close is None:  # pragma: no cover - every close test installs a fake
            return github.ScriptResult(list(argv), github.EXIT_OK, "{}", "")
        return close(list(argv), repo)

    monkeypatch.setattr(github, "run_script", _run_script)


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
    # The iteration, then the post-loop half: the tick (skipped — this branch maps to no
    # roadmap entry) and, since 05-P1.1, the commit stage that publishes the fix edit.
    assert stages.names == [
        "round1-approve-review-followups",
        "iter1-fix-next-review-followup",
        "iter1-test",
        "iter1-code-review",
        "commit-and-push",
    ]
    assert all(root == worktree for root in stages.repo_roots)
    assert fix_workflow.list_runs(_runs_root(control))[-1].pr[PR_HEAD_SHA]
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
        "      - id: I7\n"
        "      - id: F5\n",
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

#: A1, the post-loop I7 and F5 (a declared `fix` list must carry every core id — H3.3
#: req 2, 05-P1.1 req 1) and a repo-added one, which `fix`'s name-keyed consumer never runs:
#: E4.5b's non-goal, warned about rather than silently dropped.
_CONFIG_WITH_REPO_ADDED = (
    "schema_version: 1\n"
    "workflows:\n"
    "  fix:\n"
    "    stages:\n"
    "      - id: A1\n"
    "      - id: I7\n"
    "      - id: F5\n"
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
    for agent_id in (
        "review-approver",
        "fixer",
        "tester",
        "code-reviewer",
        "recorder",
        "pr-publisher",
    )
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
    # Once per run, and after the last iteration's stages (req 7). Since 05-P1.1 the tick is
    # followed by the commit stage, which is the run's last stage.
    assert stages.names.count("update-roadmap") == 1
    assert stages.names[-2:] == ["update-roadmap", "commit-and-push"]
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
    # 05-P1.1 req 2/D10: the commit stage is planned once, after the tick, and evaluates no
    # evidence — the dry run never inspects the tree and never withholds it.
    assert stages.names[-2:] == ["update-roadmap", "commit-and-push"]
    commit_lines = [
        line for line in out.splitlines() if line.startswith("commit-and-push ")
    ]
    assert len(commit_lines) == 1, out
    assert "(planned)" in commit_lines[0]
    assert out.index("update-roadmap [") < out.index("commit-and-push [")
    # Nothing ran and nothing was evaluated: the roadmap is untouched.
    assert roadmap_file.read_bytes() == before
    assert _state_of(control).pr.get("roadmap_ticked") is None
    assert fix_workflow.PR_HEAD_SHA not in _state_of(control).pr


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
    # D10: an unresolvable target withholds no commit stage in a dry run.
    assert "commit-and-push" in stages.names
    state = _state_of(control)
    assert _tick_records(state)[0].status == SKIPPED
    assert state.pr["roadmap_ticked"] is False


# --------------------------------------------------------------------------- #
# The post-loop commit-and-push stage (05-P1.1, design §8.4/§13/§17 Z9)
# --------------------------------------------------------------------------- #

#: ``state.pr`` key the skip writes (decision D7).
PR_HEAD_SHA = "head_sha"


def _commit_records(state) -> list[StageRecord]:
    return [record for record in state.stages if record.name == "commit-and-push"]


def _head(worktree: Path) -> str:
    return _git_run(worktree, "rev-parse", "HEAD").stdout.strip()


def _committed_paths(worktree: Path) -> set[str]:
    """The paths the branch's ``HEAD`` commit added or changed."""
    listing = _git_run(
        worktree, "show", "--name-only", "--pretty=format:", "HEAD"
    ).stdout
    return {line.strip() for line in listing.splitlines() if line.strip()}


def test_a_converged_run_with_an_unresolvable_roadmap_target_still_publishes_fixes(
    tmp_path: Path, monkeypatch
) -> None:
    """D2: convergence, not a green roadmap tick, triggers F5.

    An ambiguous branch-to-task mapping with a real closed issue leaves I7 skipped, but the
    fixer still produced owned work. F5 must commit and verify that work rather than being
    withheld with the tick.
    """
    control, worktree = _fix_layout(tmp_path, branch="03-H3-3")
    _write_roadmap(worktree)
    _patch(monkeypatch, branch="03-H3-3", select_impl=_converging_select())
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    assert fix_workflow.run(pr=7, **_roots(control), approve_all=True) == 0

    state = _state_of(control)
    tick = _tick_records(state)[0]
    commit = _commit_records(state)[0]
    assert tick.status == SKIPPED
    assert "exactly one" in tick.artifacts[SKIP_REASON_KEY]
    assert commit.status == SUCCEEDED
    assert [record.name for record in state.stages][-2:] == [
        "update-roadmap",
        "commit-and-push",
    ]
    assert stages.names[-1] == "commit-and-push"
    assert "update-roadmap" not in stages.names
    assert state.pr[PR_HEAD_SHA] == _head(worktree)
    assert "fix-edits/iter1-fix-next-review-followup.txt" in _committed_paths(worktree)
    assert _git_run(worktree, "status", "--porcelain").stdout.strip() == ""


def test_a_converged_run_with_an_unmet_recorded_done_when_still_publishes_fixes(
    tmp_path: Path, monkeypatch
) -> None:
    """D2/Z7: a withheld completion claim does not withhold the converged fix commit."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    roadmap_file = _write_roadmap(worktree)
    results = worktree / "docs/implementation-results/03-H3.3/build-results.md"
    results.parent.mkdir(parents=True, exist_ok=True)
    results.write_text(
        "## Summary\\n\\nDone when: the task is not yet met.\\n", encoding="utf-8"
    )
    _git_run(
        worktree,
        "add",
        str(roadmap_file.relative_to(worktree)),
        str(results.relative_to(worktree)),
    )
    _git_run(worktree, "commit", "-qm", "record an unmet done-when")
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    assert fix_workflow.run(pr=7, **_roots(control), approve_all=True) == 0

    state = _state_of(control)
    tick = _tick_records(state)[0]
    commit = _commit_records(state)[0]
    assert tick.status == SKIPPED
    assert "recorded build results" in tick.artifacts[SKIP_REASON_KEY]
    assert commit.status == SUCCEEDED
    assert state.pr[PR_HEAD_SHA] == _head(worktree)
    assert "fix-edits/iter1-fix-next-review-followup.txt" in _committed_paths(worktree)
    assert _git_run(worktree, "status", "--porcelain").stdout.strip() == ""


def test_a_converged_run_commits_and_pushes_the_change_set(
    tmp_path: Path, monkeypatch
) -> None:
    """D3 case 1: dirty tree + one closed issue → one commit, one push, ``head_sha``.

    The commit must carry the **accumulated** change set — the fixer's edit *and* the
    roadmap tick ``I7`` flipped — and the recorded ``head_sha`` must be the *remote* head the
    push produced (D6), not merely ``HEAD``. The run then ends clean, at exit 0.
    """
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    roadmap_file = _write_roadmap(worktree)
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)
    before_head = _head(worktree)

    assert fix_workflow.run(pr=7, **_roots(control), approve_all=True) == 0

    assert stages.names.count("commit-and-push") == 1
    assert stages.names[-2:] == ["update-roadmap", "commit-and-push"]
    # The agent's part: one real commit on the PR-head branch, carrying both edits.
    new_head = _head(worktree)
    assert new_head != before_head
    committed = _committed_paths(worktree)
    assert roadmap_file.relative_to(worktree).as_posix() in committed
    assert "fix-edits/iter1-fix-next-review-followup.txt" in committed
    # The pushed proof: HEAD equals the remote-tracking ref, and that is what is recorded.
    assert _git_run(worktree, "rev-parse", "origin/03-H3.3").stdout.strip() == new_head
    state = _state_of(control)
    assert state.pr[PR_HEAD_SHA] == new_head
    assert fix_workflow.PR_COMMIT_SKIP_REASON not in state.pr
    assert _git_run(worktree, "status", "--porcelain").stdout.strip() == ""
    records = _commit_records(state)
    assert len(records) == 1
    assert records[0].status == SUCCEEDED


def test_a_dirty_tree_with_nothing_closed_is_a_recorded_skip(
    tmp_path: Path, monkeypatch
) -> None:
    """D3 case 2: unowned dirt is not this run's to publish — skip, exit 0, no commit.

    The operator's own file stays uncommitted and ``HEAD`` does not move: the run records
    *why* it published nothing instead of sweeping somebody else's work into a commit.
    """
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    operator_file = worktree / "operator-notes.txt"
    operator_file.write_text("mine\n", encoding="utf-8")
    _patch(monkeypatch, branch="03-H3.3", select_impl=_select_seq([_select_none()]))
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)
    before_head = _head(worktree)

    assert fix_workflow.run(pr=7, **_roots(control), approve_all=True) == 0

    assert "commit-and-push" not in stages.names
    assert _head(worktree) == before_head
    assert operator_file.read_text(encoding="utf-8") == "mine\n"
    assert "?? operator-notes.txt" in _git_run(
        worktree, "status", "--porcelain"
    ).stdout
    state = _state_of(control)
    reason = state.pr[fix_workflow.PR_COMMIT_SKIP_REASON]
    assert "this run closed no issue" in reason
    assert "not this run's" in reason
    assert PR_HEAD_SHA not in state.pr
    record = _commit_records(state)[0]
    assert record.status == SKIPPED
    assert record.error is None
    assert record.artifacts[SKIP_REASON_KEY] == reason


def test_a_clean_tree_with_nothing_closed_is_a_successful_noop(
    tmp_path: Path, monkeypatch
) -> None:
    """D3 case 3: the roadmap's successful no-op — no commit object, no push, exit 0."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    _patch(monkeypatch, branch="03-H3.3", select_impl=_select_seq([_select_none()]))
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)
    before_head = _head(worktree)
    before_count = _git_run(worktree, "rev-list", "--count", "HEAD").stdout.strip()

    assert fix_workflow.run(pr=7, **_roots(control), approve_all=True) == 0

    assert "commit-and-push" not in stages.names
    assert _head(worktree) == before_head
    assert (
        _git_run(worktree, "rev-list", "--count", "HEAD").stdout.strip() == before_count
    )
    state = _state_of(control)
    assert "nothing to commit" in state.pr[fix_workflow.PR_COMMIT_SKIP_REASON]
    assert PR_HEAD_SHA not in state.pr
    assert _commit_records(state)[0].status == SKIPPED


def test_closed_issues_with_a_clean_tree_fail_closed(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """D3 case 4: issues closed and nothing to push is the untruthful state — exit 1.

    An already-ticked (and committed) roadmap plus a fake whose ``F1`` writes nothing models
    it exactly: the run closed a follow-up issue, so recording "fixed" with no commit to push
    must be loud, and the message names the PR and the branch (req 5(d)).
    """
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    roadmap_file = _write_roadmap(worktree, _roadmap_text(done=True))
    _git_run(worktree, "add", str(roadmap_file.relative_to(worktree)))
    _git_run(worktree, "commit", "-qm", "roadmap baseline")
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages()
    stages._apply_fix_edit = lambda _spec, _root: None
    monkeypatch.setattr(fix_workflow, "run_stage", stages)
    before_head = _head(worktree)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 1
    assert "commit-and-push" not in stages.names
    assert _head(worktree) == before_head
    err = capsys.readouterr().err
    assert "#7" in err and "03-H3.3" in err
    assert "nothing to push" in err
    state = _state_of(control)
    assert PR_HEAD_SHA not in state.pr
    assert state.status == FAILED


def test_a_push_that_did_not_land_fails_the_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """D6: the agent reports success but ``origin/<branch>`` never moved — exit 1.

    Trusting the stage's exit code is the exact O1 failure this comparison exists to close.
    The remote-tracking ref starts at the pre-run commit, so the pair is unequal.
    """
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    _write_roadmap(worktree)
    _git_run(worktree, "update-ref", "refs/remotes/origin/03-H3.3", "HEAD")
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages(push=False)
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 1
    assert "commit-and-push" in stages.names
    err = capsys.readouterr().err
    assert "#7" in err and "03-H3.3" in err
    assert "the push did not land" in err
    state = _state_of(control)
    assert PR_HEAD_SHA not in state.pr
    assert state.status == FAILED


def test_a_stage_that_discards_the_change_set_fails_the_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """PR #158 review finding: a clean tree at the *old* HEAD is not proof of a push.

    A stage that discards the change set instead of committing it (a stash/clean failure
    mode) satisfies the recorded success, ``HEAD == origin/<branch>`` **and** the clean-tree
    check — all on the pre-existing SHAs. Only the HEAD-movement proof separates "the change
    set landed" from "the change set was thrown away", so the run must fail naming the PR
    and branch with ``head_sha`` absent, instead of reporting a push that carried nothing.
    """
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    _write_roadmap(worktree)
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages(discard=True)
    monkeypatch.setattr(fix_workflow, "run_stage", stages)
    before_head = _head(worktree)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 1
    assert stages.names.count("commit-and-push") == 1
    # The three weaker proofs hold, which is exactly why this one is needed.
    assert _head(worktree) == before_head
    assert _git_run(worktree, "rev-parse", "origin/03-H3.3").stdout.strip() == before_head
    assert _git_run(worktree, "status", "--porcelain").stdout.strip() == ""
    err = capsys.readouterr().err
    assert "#7" in err and "03-H3.3" in err
    assert "HEAD did not move" in err
    state = _state_of(control)
    assert PR_HEAD_SHA not in state.pr
    assert state.status == FAILED
    assert _commit_records(state)[0].status == SUCCEEDED


def test_an_unresolvable_pushed_ref_fails_closed(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """D6: an unresolvable remote ref is not evidence of a push."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    _write_roadmap(worktree)
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)
    real_rev_parse = fix_workflow.git.rev_parse

    def hide_remote_ref(repo: Path, revision: str) -> str | None:
        if revision == "origin/03-H3.3":
            return None
        return real_rev_parse(repo, revision)

    monkeypatch.setattr(fix_workflow.git, "rev_parse", hide_remote_ref)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 1
    err = capsys.readouterr().err
    assert "#7" in err and "03-H3.3" in err
    assert "the push did not land" in err
    assert "unresolvable" in err
    assert PR_HEAD_SHA not in _state_of(control).pr


def test_a_failed_commit_stage_fails_the_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 5(a): a non-``SUCCEEDED`` record on the commit case fails, naming PR + branch."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    _write_roadmap(worktree)
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages(failing=("commit-and-push",))
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 1
    err = capsys.readouterr().err
    assert "#7" in err and "03-H3.3" in err
    assert "`failed`" in err
    state = _state_of(control)
    assert PR_HEAD_SHA not in state.pr
    assert _commit_records(state)[0].status == FAILED


def test_a_tree_left_dirty_after_the_stage_fails_the_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 5(c): a push that landed but left part of the change set behind is a failure."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    _write_roadmap(worktree)
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages(leave_dirty=True)
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 1
    err = capsys.readouterr().err
    assert "#7" in err and "03-H3.3" in err
    assert "still dirty" in err
    assert PR_HEAD_SHA not in _state_of(control).pr


def test_a_pr_head_that_is_the_base_branch_is_refused_before_any_push(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """D5: a misresolved ref must never commit or push the base branch.

    The preflight resolves the head through ``gh`` (decision K1); when that value *is* the
    base branch the run refuses before the stage, so no commit is created and no push is
    attempted — pushing ``main`` is not recoverable in a shared repository.
    """
    control, _worktree = _fix_layout(tmp_path)
    _patch(monkeypatch, branch="main", select_impl=_converging_select())
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)
    before_head = _head(control)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 1
    assert "commit-and-push" not in stages.names
    assert _head(control) == before_head
    assert _git_run(control, "status", "--porcelain").stdout.strip() != ""
    err = capsys.readouterr().err
    assert "#7" in err and "`main`" in err
    assert "refusing to commit or push" in err
    assert PR_HEAD_SHA not in _state_of(control).pr


def test_a_stopped_loop_records_the_commit_skip_with_the_same_reason(
    tmp_path: Path, monkeypatch
) -> None:
    """D4: one ``stop()`` call site records both post-loop skips, with the same reason."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    _write_roadmap(worktree)
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages()
    monkeypatch.setattr(fix_workflow, "run_stage", stages)
    before_head = _head(worktree)

    code = fix_workflow.run(
        pr=7,
        **_roots(control),
        approve_all=True,
        deny_gates=[fix_workflow.GATE_FIX_PR],
    )

    assert code == 3
    assert "commit-and-push" not in stages.names
    assert _head(worktree) == before_head
    state = _state_of(control)
    tick_reason = state.pr[fix_workflow.PR_ROADMAP_TICK_SKIP_REASON]
    commit_reason = state.pr[fix_workflow.PR_COMMIT_SKIP_REASON]
    assert commit_reason == tick_reason
    assert fix_workflow.GATE_FIX_PR in commit_reason
    record = _commit_records(state)[0]
    assert record.status == SKIPPED
    assert record.artifacts[SKIP_REASON_KEY] == tick_reason
    # Nothing was published, so the boolean that is `head_sha`'s presence stays absent.
    assert PR_HEAD_SHA not in state.pr


def test_a_failed_tick_leaves_no_commit_record(tmp_path: Path, monkeypatch) -> None:
    """D4's other half: a failed ``I7`` keeps exit 1 and records no ``F5`` at all.

    Committing a half-applied tick is worse than leaving the tree for a human, so the failed
    postcondition short-circuits before the commit stage — neither run nor recorded — rather
    than pretending the run may publish.
    """
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    _write_roadmap(worktree)
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages()
    # A recorder that exits 0 but leaves the roadmap untouched fails the tick postcondition.
    stages._apply_tick = lambda _spec: None
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 1
    assert "commit-and-push" not in stages.names
    state = _state_of(control)
    assert _commit_records(state) == []
    assert PR_HEAD_SHA not in state.pr
    assert fix_workflow.PR_COMMIT_SKIP_REASON not in state.pr
    assert _tick_records(state)[0].status == FAILED


# --------------------------------------------------------------------------- #
# The deferred close (05-P1.2, design §8.4/§17 Z9's close-after-push half)
# --------------------------------------------------------------------------- #

#: Pinned seed and run count for the property run below (AGENTS.md "Tests": pytest only, no
#: ``hypothesis``, so a reproducible sample is the generator and there is no shrinking).


def _closing_bodies(control: Path) -> list[Path]:
    """Every closing-body file this run's iterations wrote, in iteration order."""
    directory = _runs_root(control) / _state_of(control).run_id
    return sorted((directory / "artifacts").glob("iter*-closing-body.md"))


def test_a_converged_run_closes_the_recorded_issue_after_the_push(
    tmp_path: Path, monkeypatch
) -> None:
    """The happy path: fix, push, **then** the exact marker and the close (P1.2 req 1-4).

    Three facts are asserted together, because any one alone would pass a broken ordering:
    the issue was still ``OPEN`` at the moment ``F5`` pushed; the close call came after that
    push; and the path it passed back is the absolute body path ``F1`` was given. The run
    ends at exit 0 with ``head_sha`` recorded and the issue closed.
    """
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    _write_roadmap(worktree)
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages(issues={101: "OPEN"})
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    assert fix_workflow.run(pr=7, **_roots(control), approve_all=True) == 0

    # The issue was open when the push landed, and closed only after it.
    assert ("push", {101: "OPEN"}) in stages.events
    push_at = stages.events.index(("push", {101: "OPEN"}))
    close_at = stages.events.index(("close", 101))
    assert close_at > push_at
    assert stages.issues == {101: "CLOSED"}

    # One close, one issue, one script call — never a batch, never an agent stage.
    assert [call["command"] for call in stages.closes] == ["close"]
    assert [call["issue"] for call in stages.closes] == [101]
    assert "close" not in stages.names
    assert [call["repo_root"] for call in stages.closes] == [worktree]

    # The body path is absolute, lives in the run directory, and is exactly the value F1
    # rendered and the run recorded.
    recorded = stages.closes[0]["body_file"]
    body = Path(recorded)
    assert body.is_absolute()
    assert body == _closing_bodies(control)[0]
    f1 = next(spec for spec in stages.specs if spec.name.startswith("iter1-fix"))
    assert f1.variables == ["7", recorded]
    state = _state_of(control)
    assert state.pr["closed_issues"][0]["number"] == 101
    assert state.pr["closed_issues"][0]["closing_body"] == recorded
    payload = json.loads(
        (
            _runs_root(control) / state.run_id / "artifacts" / "fix.json"
        ).read_text(encoding="utf-8")
    )
    assert payload["closed_issues"][0]["closing_body"] == recorded
    assert state.pr[PR_HEAD_SHA] == _head(worktree)
    assert state.status == SUCCEEDED


@pytest.mark.parametrize(
    "failure",
    [
        {"commit": False},
        {"push": False},
        {"leave_dirty": True},
        {"discard": True},
    ],
    ids=["no-commit", "no-push", "dirty-after", "discarded-change-set"],
)
def test_a_pending_close_with_no_verified_push_fails_closed(
    tmp_path: Path, monkeypatch, capsys, failure: dict
) -> None:
    """Req 5: a recorded fix with a failed push closes nothing, exits 1, stays open.

    Each mode is one of ``F5``'s own failure proofs; the deferred close must not run for
    any of them, because closing here is exactly the "reported fixed" state P1.2 removes.
    """
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    _write_roadmap(worktree)
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages(issues={101: "OPEN"}, **failure)
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 1
    assert stages.closes == []
    assert stages.issues == {101: "OPEN"}
    assert PR_HEAD_SHA not in _state_of(control).pr
    assert _state_of(control).status == FAILED
    err = capsys.readouterr().err
    assert "#7" in err and "03-H3.3" in err


def test_a_close_stage_that_is_skipped_never_closes_a_pending_issue(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 5: "the commit stage is absent/skipped" — a skipped commit also closes nothing.

    D3's table cannot produce this combination today (clean + ≥ 1 closed fails instead), so
    the guard is forced here: the point is that the close is gated on a *verified* push, not
    on the table being well formed.
    """
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    _write_roadmap(worktree)
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages(issues={101: "OPEN"})
    monkeypatch.setattr(fix_workflow, "run_stage", stages)
    monkeypatch.setattr(
        fix_workflow,
        "commit_decision",
        lambda **_kwargs: fix_workflow.CommitDecision(
            fix_workflow.COMMIT_ACTION_SKIP, "forced skip for this test"
        ),
    )

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 1
    assert stages.closes == []
    assert stages.issues == {101: "OPEN"}
    err = capsys.readouterr().err
    assert "#7" in err and "03-H3.3" in err and "#101" in err
    assert "no commit-and-push verified a push" in err
    state = _state_of(control)
    assert PR_HEAD_SHA not in state.pr
    assert state.status == FAILED


def test_a_non_zero_close_exit_fails_the_run_naming_the_issue(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 3: the close's own failure fails the run, after the push has already landed."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    _write_roadmap(worktree)
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages(issues={101: "OPEN"}, close_exit_code=1)
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 1
    assert len(stages.closes) == 1
    # The push did land, so its proof stays recorded — only the close failed.
    assert _state_of(control).pr[PR_HEAD_SHA] == _head(worktree)
    assert stages.issues == {101: "OPEN"}
    err = capsys.readouterr().err
    assert "#7" in err and "03-H3.3" in err and "#101" in err
    assert "close" in err and "exited 1" in err
    assert _state_of(control).status == FAILED


def test_a_missing_closing_body_fails_the_close_and_so_the_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 4: the body is the fixer's, so an unwritten one fails before any close action."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    _write_roadmap(worktree)
    _patch(monkeypatch, branch="03-H3.3", select_impl=_converging_select())
    stages = _FakeStages(issues={101: "OPEN"}, write_closing_body=False)
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    code = fix_workflow.run(pr=7, **_roots(control), approve_all=True)

    assert code == 1
    assert _closing_bodies(control) == []
    assert stages.issues == {101: "OPEN"}
    err = capsys.readouterr().err
    assert "#101" in err and "--body-file not usable" in err


def test_an_empty_run_attempts_no_close(tmp_path: Path, monkeypatch) -> None:
    """Req 5: `select` found nothing, so there is no close to run — exit 0, no call."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    _patch(monkeypatch, branch="03-H3.3", select_impl=_select_seq([_select_none()]))
    stages = _FakeStages(issues={101: "OPEN"})
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    assert fix_workflow.run(pr=7, **_roots(control), approve_all=True) == 0

    assert stages.closes == []
    assert stages.issues == {101: "OPEN"}
    assert PR_HEAD_SHA not in _state_of(control).pr
    assert _state_of(control).status == SUCCEEDED


def test_two_iterations_close_one_issue_each_in_order(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 6: one close per recorded entry, each with its own iteration's body file."""
    control, worktree = _fix_layout(tmp_path, branch="03-H3.3")
    _write_roadmap(worktree)
    _patch(
        monkeypatch,
        branch="03-H3.3",
        select_impl=_select_seq(
            [
                _select_ok(),
                _select_ok(number=101),
                _select_ok(number=102, title="Fix the second loop"),
                _select_none(),
            ]
        ),
    )
    stages = _FakeStages(issues={101: "OPEN", 102: "OPEN"})
    monkeypatch.setattr(fix_workflow, "run_stage", stages)

    assert fix_workflow.run(pr=7, **_roots(control), approve_all=True) == 0

    assert [call["issue"] for call in stages.closes] == [101, 102]
    bodies = [Path(call["body_file"]).name for call in stages.closes]
    assert bodies == ["iter1-closing-body.md", "iter2-closing-body.md"]
    # Both closes still come after the single post-loop push.
    push_at = stages.events.index(("push", {101: "OPEN", 102: "OPEN"}))
    assert stages.events.index(("close", 101)) > push_at
    assert stages.events.index(("close", 102)) > push_at
    assert stages.issues == {101: "CLOSED", 102: "CLOSED"}
    assert [entry["number"] for entry in _state_of(control).pr["closed_issues"]] == [
        101,
        102,
    ]


def test_closing_body_path_is_absolute_and_per_iteration(tmp_path: Path) -> None:
    """Purity: the path is derived, absolute, and never shares a file across iterations."""
    first = fix_workflow.closing_body_path(tmp_path / "run", 1)
    second = fix_workflow.closing_body_path(tmp_path / "run", 2)

    assert first.is_absolute(), first
    assert first == tmp_path / "run" / "artifacts" / "iter1-closing-body.md"
    assert first.name != second.name
    assert fix_workflow.closing_body_path(tmp_path / "run", 1) == first


def test_close_failure_message_names_the_pr_the_branch_and_the_issue() -> None:
    """Req 3: one message shape, and it names the issue as well as the PR and branch."""
    message = fix_workflow.close_failure_message(42, "03-H3.3", 101, "`close` exited 1")

    assert message.startswith("close failed for PR #42 on branch `03-H3.3`")
    assert "issue #101" in message
    assert "`close` exited 1" in message
    assert "(unresolved)" in fix_workflow.close_failure_message(42, None, 7, "why")


# --------------------------------------------------------------------------- #
# D3's rule as a pure unit: the table, its reasons, and its determinism
# --------------------------------------------------------------------------- #

#: Pinned seed and run count for the property run below (AGENTS.md "Tests": pytest only, no
#: ``hypothesis``, so a reproducible sample is the generator and there is no shrinking).
COMMIT_PROPERTY_SEED = 4407
COMMIT_PROPERTY_RUNS = 60


def test_commit_decision_is_the_four_case_table() -> None:
    """One hand-calculated example per row of D3's table."""
    closed = [{"number": 101}]

    commit = fix_workflow.commit_decision(tree_dirty=True, closed_issues=closed)
    assert commit.action == fix_workflow.COMMIT_ACTION_COMMIT
    # A decision that runs the stage never carries a reason to print as one.
    assert commit.reason == ""

    dirty_skip = fix_workflow.commit_decision(tree_dirty=True, closed_issues=[])
    assert dirty_skip.action == fix_workflow.COMMIT_ACTION_SKIP
    assert dirty_skip.reason == fix_workflow.COMMIT_SKIP_DIRTY_UNOWNED
    assert "not this run's" in dirty_skip.reason

    clean_skip = fix_workflow.commit_decision(tree_dirty=False, closed_issues=[])
    assert clean_skip.action == fix_workflow.COMMIT_ACTION_SKIP
    assert clean_skip.reason == fix_workflow.COMMIT_SKIP_CLEAN_NOOP
    assert "nothing to commit" in clean_skip.reason

    clean_fail = fix_workflow.commit_decision(
        tree_dirty=False, closed_issues=[{"number": 1}, {"number": 2}]
    )
    assert clean_fail.action == fix_workflow.COMMIT_ACTION_FAIL
    assert "2 issue(s)" in clean_fail.reason
    assert "nothing to push" in clean_fail.reason


def test_commit_decision_is_deterministic_and_pure_property() -> None:
    """Seeded property run (seed/runs pinned above): the table, purity and determinism.

    For every sampled ``(tree_dirty, closed count)`` the decision is the table's action, a
    second call returns an equal immutable value, a ``commit`` decision carries no reason and
    every other one always does, and the caller's ``closed_issues`` list — the run's own
    accumulated list — is never mutated.
    """
    rng = random.Random(COMMIT_PROPERTY_SEED)
    expected = {
        (True, True): fix_workflow.COMMIT_ACTION_COMMIT,
        (True, False): fix_workflow.COMMIT_ACTION_SKIP,
        (False, False): fix_workflow.COMMIT_ACTION_SKIP,
        (False, True): fix_workflow.COMMIT_ACTION_FAIL,
    }

    for case in range(COMMIT_PROPERTY_RUNS):
        dirty = rng.choice([True, False])
        count = rng.choice([0, 1, 2, 7])
        closed = [{"number": number, "title": f"child {number}"} for number in range(count)]
        before = [dict(item) for item in closed]

        first = fix_workflow.commit_decision(tree_dirty=dirty, closed_issues=closed)
        second = fix_workflow.commit_decision(tree_dirty=dirty, closed_issues=closed)

        assert first == second, case
        assert closed == before, case
        assert first.action == expected[(dirty, bool(count))], (case, dirty, count)
        assert (first.reason == "") == (
            first.action == fix_workflow.COMMIT_ACTION_COMMIT
        ), (case, first)


def test_commit_failure_message_names_the_pr_and_the_branch() -> None:
    """Req 5/req 6: every failure is one shape, and it names the PR and the branch."""
    message = fix_workflow.commit_failure_message(42, "03-H3.3", "the push did not land")
    assert "#42" in message
    assert "03-H3.3" in message
    assert "the push did not land" in message
    assert message.startswith("commit-and-push failed for PR #42")
    # An unresolved branch is named as such rather than omitted.
    assert "(unresolved)" in fix_workflow.commit_failure_message(42, None, "why")


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
