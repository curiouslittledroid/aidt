"""Tests for the ``aidw approve-followups`` workflow."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest

from aidw import git, github, lock
from aidw.gates import GateOutcome
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.state import SUCCEEDED, StageRecord, run_dir
from aidw.workflows import approve as approve_workflow


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "aidt").mkdir()


def _git_run(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _make_bare_with_control(tmp_path: Path) -> Path:
    seed = tmp_path / "seed"
    seed.mkdir()
    _git_run(seed, "init", "-q", "-b", "main")
    (seed / "f.txt").write_text("x\\n", encoding="utf-8")
    _git_run(seed, "add", ".")
    _git_run(seed, "commit", "-qm", "init")
    bare = tmp_path / "bare.git"
    _git_run(tmp_path, "clone", "--bare", "-q", str(seed), str(bare))
    control = tmp_path / "main"
    _git_run(bare, "worktree", "add", "-q", str(control), "main")
    return control


def _roots(repo: Path, *, state_dir: Path | None = None) -> dict:
    target = TargetRepo.resolve(repo)
    return {
        "repo": target,
        "aidt": ToolkitPaths.resolve(),
        "workspace": WorkspacePaths.resolve(
            target,
            state_dir_override=state_dir or repo.parent / f"{repo.name}-state",
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


class _FakeStages:
    def __init__(self, status: str = SUCCEEDED) -> None:
        self.names: list[str] = []
        self.specs: list = []
        self.status = status

    def __call__(self, spec, **kwargs):
        self.names.append(spec.name)
        self.specs.append(spec)
        directory = run_dir(kwargs["runs_root"], kwargs["state"].run_id)
        stages = directory / "stages"
        stages.mkdir(parents=True, exist_ok=True)
        out = stages / f"{spec.name}.out.txt"
        out.write_text("ok\n", encoding="utf-8")
        record = StageRecord(
            name=spec.name,
            agent=spec.agent_id,
            model="test/model",
            status=self.status,
            artifacts={"out": str(out)},
        )
        kwargs["state"].record_stage(record)
        return record


def _patch(
    monkeypatch, *, view: dict | None = None, agents: dict | None = None
) -> None:
    monkeypatch.setattr(
        approve_workflow, "load_all", lambda aidt, repo, **_kwargs: (agents or {}, [])
    )
    monkeypatch.setattr(git, "current_branch", lambda repo: "03-E4.1")
    monkeypatch.setattr(github, "gh_available", lambda: True)
    monkeypatch.setattr(
        github,
        "pr_view",
        lambda repo, pr: view
        if view is not None
        else {
            "number": pr,
            "url": f"https://github.com/o/r/pull/{pr}",
            "baseRefName": "main",
            "headRefName": "03-E4.1",
        },
    )
    monkeypatch.setattr(github, "select_followups", lambda aidt, repo, pr, timeout=github.DEFAULT_TIMEOUT, **_kwargs: _select_ok())


def test_dry_run_plans_stage_and_gate(tmp_path: Path, monkeypatch, capsys) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    stages = _FakeStages()
    monkeypatch.setattr(approve_workflow, "run_stage", stages)

    code = approve_workflow.run(
        pr=7, **_roots(tmp_path), dry_run=True
    )

    assert code == 0
    assert stages.names == ["approve-review-followups"]
    out = capsys.readouterr().out
    assert "child:  #101 Fix the loop" in out
    assert "approve-review-followups [succeeded] (planned) agent=review-approver" in out
    assert "gate (planned): approve-followups" in out


def test_gate_denied_stops_without_stage(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    stages = _FakeStages()
    monkeypatch.setattr(approve_workflow, "run_stage", stages)
    monkeypatch.setattr(
        approve_workflow,
        "decide",
        lambda *a, **k: GateOutcome(approve_workflow.GATE, False, "human-denied"),
    )

    code = approve_workflow.run(pr=7, **_roots(tmp_path))

    assert code == 3
    assert stages.names == []


def test_approved_runs_review_approver(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    stages = _FakeStages()
    monkeypatch.setattr(approve_workflow, "run_stage", stages)
    monkeypatch.setattr(
        approve_workflow,
        "decide",
        lambda *a, **k: GateOutcome(approve_workflow.GATE, True, "--yes"),
    )

    code = approve_workflow.run(
        pr=7, **_roots(tmp_path), approve_all=True
    )

    assert code == 0
    assert stages.names == ["approve-review-followups"]
    spec = stages.specs[0]
    assert spec.agent_id == "review-approver"
    assert spec.prompt.name == "approve-review-followups.md"
    assert spec.variables == ["7"]
    # The stage must not succeed on the agent's exit code alone (design §10).
    assert callable(spec.verify)


def test_stage_failure_is_recorded(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    stages = _FakeStages(status="failed")
    monkeypatch.setattr(approve_workflow, "run_stage", stages)
    monkeypatch.setattr(
        approve_workflow,
        "decide",
        lambda *a, **k: GateOutcome(approve_workflow.GATE, True, "--yes"),
    )

    code = approve_workflow.run(
        pr=7, **_roots(tmp_path), approve_all=True
    )

    assert code == 1


def test_missing_pr_is_usage_error(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch, view={})
    monkeypatch.setattr(github, "pr_view", lambda repo, pr: None)
    monkeypatch.setattr(approve_workflow, "run_stage", _FakeStages())

    code = approve_workflow.run(pr=7, **_roots(tmp_path))

    assert code == 2

# --------------------------------------------------------------------------- #
# One run per worktree (E2.7, EXTRACTION.md §3.2/§3.10)
# --------------------------------------------------------------------------- #


def _approved(monkeypatch) -> None:
    monkeypatch.setattr(
        approve_workflow,
        "decide",
        lambda *args, **kwargs: GateOutcome(approve_workflow.GATE, True, "--yes"),
    )


def test_a_held_repo_root_lock_is_refused_before_any_run_state(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """``approve`` resolves no worktree, so its key is the invocation worktree by design."""
    _init_repo(tmp_path)
    _patch(monkeypatch)
    _approved(monkeypatch)
    stages = _FakeStages()
    monkeypatch.setattr(approve_workflow, "run_stage", stages)
    roots = _roots(tmp_path)

    with lock.acquire(roots["workspace"].state_root, tmp_path):
        code = approve_workflow.run(pr=7, **roots, approve_all=True)

    assert code == 4
    assert stages.names == []
    runs_root = _runs_root(tmp_path)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []
    err = capsys.readouterr().err
    assert "another aidw run is already active" in err
    assert str(tmp_path.resolve()) in err


def test_two_concurrent_approve_runs_from_one_repo_root_are_refused(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Same-cwd concurrent approvals refuse; only one run directory is created."""
    _init_repo(tmp_path)
    _patch(monkeypatch)
    _approved(monkeypatch)
    entered, release = threading.Event(), threading.Event()

    class _BlockingStages(_FakeStages):
        def __call__(self, spec, **kwargs):
            entered.set()
            assert release.wait(timeout=60), "the holder was never released"
            return super().__call__(spec, **kwargs)

    monkeypatch.setattr(approve_workflow, "run_stage", _BlockingStages())
    roots = _roots(tmp_path)
    outcome: dict = {}

    def hold() -> None:
        try:
            outcome["code"] = approve_workflow.run(pr=7, **roots, approve_all=True)
        except BaseException as exc:  # pragma: no cover - asserted via ``outcome``
            outcome["error"] = exc

    holder = threading.Thread(target=hold, name="aidw-approve-run")
    holder.start()
    assert entered.wait(timeout=60), "the holding run never reached a stage"

    refused = approve_workflow.run(pr=7, **roots, approve_all=True)

    release.set()
    holder.join(timeout=60)
    assert not holder.is_alive()
    assert "error" not in outcome, outcome.get("error")

    assert refused == 4
    assert outcome["code"] == 0
    assert len(list(_runs_root(tmp_path).iterdir())) == 1
    assert "another aidw run is already active" in capsys.readouterr().err


@pytest.mark.parametrize("scenario", ["success", "stage-failure", "gate-denied"])
def test_the_lock_is_released_on_every_exit_path(
    tmp_path: Path, monkeypatch, scenario: str
) -> None:
    _init_repo(tmp_path)
    _patch(monkeypatch)
    expected = {"success": 0, "stage-failure": 1, "gate-denied": 3}[scenario]
    status = "failed" if scenario == "stage-failure" else SUCCEEDED
    monkeypatch.setattr(approve_workflow, "run_stage", _FakeStages(status=status))
    if scenario == "gate-denied":
        monkeypatch.setattr(
            approve_workflow,
            "decide",
            lambda *args, **kwargs: GateOutcome(approve_workflow.GATE, False, "human-denied"),
        )
    else:
        _approved(monkeypatch)
    roots = _roots(tmp_path)

    assert approve_workflow.run(pr=7, **roots, approve_all=True) == expected

    with lock.acquire(roots["workspace"].state_root, tmp_path):
        pass

def test_approvals_from_different_worktrees_both_proceed(
    tmp_path: Path, monkeypatch
) -> None:
    """Different invocation worktrees are different keys — by design, not a violation.

    ``approve`` resolves no worktree, so its key is the worktree it was started in: two
    approvals in the *same* tree refuse (above), two in different trees both proceed.
    """
    for name in ("first", "second"):
        (tmp_path / name).mkdir()
        _init_repo(tmp_path / name)
    _patch(monkeypatch)
    _approved(monkeypatch)
    entered = {
        (tmp_path / "first").resolve(): threading.Event(),
        (tmp_path / "second").resolve(): threading.Event(),
    }
    release = threading.Event()

    class _PerWorktreeStages(_FakeStages):
        def __call__(self, spec, **kwargs):
            entered.setdefault(kwargs["repo_root"], threading.Event()).set()
            assert release.wait(timeout=60), "the runs were never released"
            return super().__call__(spec, **kwargs)

    monkeypatch.setattr(approve_workflow, "run_stage", _PerWorktreeStages())
    roots = {name: _roots(tmp_path / name) for name in ("first", "second")}
    outcomes: dict[str, dict] = {"first": {}, "second": {}}

    def approve(name: str) -> None:
        try:
            outcomes[name]["code"] = approve_workflow.run(
                pr=7, **roots[name], approve_all=True
            )
        except BaseException as exc:  # pragma: no cover - asserted via ``outcomes``
            outcomes[name]["error"] = exc

    threads = [
        threading.Thread(target=approve, args=(name,), name=f"aidw-approve-{name}")
        for name in ("first", "second")
    ]
    for thread in threads:
        thread.start()
    for path in entered:
        assert entered[path].wait(timeout=60), f"{path} never reached a stage"
    release.set()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive()

    assert outcomes["first"].get("code") == 0, outcomes["first"].get("error")
    assert outcomes["second"].get("code") == 0, outcomes["second"].get("error")
    for name in ("first", "second"):
        assert len(list(_runs_root(tmp_path / name).iterdir())) == 1


def test_approvals_in_different_worktrees_share_state_but_not_a_lock(
    tmp_path: Path, monkeypatch
) -> None:
    """The approve key is the invocation path, even in one bare-repo workspace."""
    control = _make_bare_with_control(tmp_path)
    first = git.add_worktree(control, "task-a")
    second = git.add_worktree(control, "task-b")
    assert first is not None and second is not None

    _patch(monkeypatch)
    _approved(monkeypatch)
    shared_state = tmp_path / "shared-state"
    roots = {
        name: _roots(path, state_dir=shared_state)
        for name, path in (("first", first), ("second", second))
    }
    assert roots["first"]["workspace"].state_root == roots["second"]["workspace"].state_root

    entered = {first: threading.Event(), second: threading.Event()}
    release = threading.Event()

    class _PerWorktreeStages(_FakeStages):
        def __call__(self, spec, **kwargs):
            entered[kwargs["repo_root"]].set()
            assert release.wait(timeout=60), "the runs were never released"
            return super().__call__(spec, **kwargs)

    monkeypatch.setattr(approve_workflow, "run_stage", _PerWorktreeStages())
    outcomes: dict[str, dict] = {"first": {}, "second": {}}

    def approve(name: str) -> None:
        try:
            pr = 7 if name == "first" else 8
            outcomes[name]["code"] = approve_workflow.run(
                pr=pr, **roots[name], approve_all=True
            )
        except BaseException as exc:  # pragma: no cover - asserted via outcomes
            outcomes[name]["error"] = exc

    threads = [
        threading.Thread(target=approve, args=(name,), name=f"aidw-approve-{name}")
        for name in ("first", "second")
    ]
    for thread in threads:
        thread.start()
    for path in entered:
        assert entered[path].wait(timeout=60), f"{path} never reached a stage"
    release.set()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive()

    assert outcomes["first"].get("code") == 0, outcomes["first"].get("error")
    assert outcomes["second"].get("code") == 0, outcomes["second"].get("error")
    # Both calls entered their stage while the other was still live, proving that
    # separate invocation paths acquire separate mutexes in the same state root.
    lock_files = {
        path.name for path in (roots["first"]["workspace"].state_root / "locks").iterdir()
    }
    assert lock_files == {lock.lock_filename(first), lock.lock_filename(second)}
    runs = list(roots["first"]["workspace"].state_root.joinpath("runs").iterdir())
    assert len(runs) == 2


# --------------------------------------------------------------------------- #
# core vs repo-optional preflight (E4.5a, D12/D13, EXTRACTION.md §3.5)
# --------------------------------------------------------------------------- #


def test_a_disabled_core_approver_is_refused_before_any_side_effect(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Prompt-fixed: A1 (approve) is core — only I3/I4 are repo-optional."""
    _init_repo(tmp_path)
    config = tmp_path / "aidw" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "schema_version: 1\n"
        "workflows:\n"
        "  approve:\n"
        "    stages:\n"
        "      - id: A1\n"
        "        enabled: false\n",
        encoding="utf-8",
    )
    _patch(monkeypatch)
    stages = _FakeStages()
    monkeypatch.setattr(approve_workflow, "run_stage", stages)

    code = approve_workflow.run(pr=7, **_roots(tmp_path), dry_run=True)

    assert code == 2
    err = capsys.readouterr().err
    assert "workflows.approve.stages" in err
    assert "A1" in err
    assert "core stage cannot be disabled" in err
    assert stages.names == []
    runs_root = _runs_root(tmp_path)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []


# --------------------------------------------------------------------------- #
# repo-added stages (E4.5b req 1/req 7, EXTRACTION.md §3.5)
# --------------------------------------------------------------------------- #

#: The declared `prompt:` of a repo-added approve stage, relative to the target root.
REPO_ADDED_PROMPT = "aidw/prompts/repo-added.md"

#: Stand-in agent configs: `load_all` is faked, so only the ids matter — a repo-added
#: stage's declared `agent` is *existence*-checked against this dict (E4.5b req 4).
_AGENTS = {"review-approver": object(), "implementer": object()}


def _write_stages_config(root: Path, entries: list[dict[str, object]]) -> None:
    """``aidw/config.yaml`` declaring ``workflows.approve.stages = entries``."""
    lines = ["schema_version: 1", "workflows:", "  approve:", "    stages:"]
    for entry in entries:
        for index, (key, value) in enumerate(entry.items()):
            prefix = "      - " if index == 0 else "        "
            rendered = (
                ("true" if value else "false") if isinstance(value, bool) else str(value)
            )
            lines.append(f"{prefix}{key}: {rendered}")
    config = root / "aidw" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_repo_added_prompt(root: Path) -> None:
    path = root / REPO_ADDED_PROMPT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# repo-added stage\n", encoding="utf-8")


def _repo_added(stage_id: str) -> dict[str, object]:
    return {"id": stage_id, "agent": "implementer", "prompt": REPO_ADDED_PROMPT}


def _approved(monkeypatch) -> None:
    monkeypatch.setattr(
        approve_workflow,
        "decide",
        lambda *a, **k: GateOutcome(approve_workflow.GATE, True, "--yes"),
    )


def test_a_repo_added_stage_plans_and_runs_in_declared_order(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 7: the dry run iterates the full plan — no single-spec unpack."""
    _init_repo(tmp_path)
    _write_stages_config(tmp_path, [_repo_added("approve-preflight-notes"), {"id": "A1"}])
    _write_repo_added_prompt(tmp_path)
    _patch(monkeypatch, agents=_AGENTS)
    stages = _FakeStages()
    monkeypatch.setattr(approve_workflow, "run_stage", stages)

    code = approve_workflow.run(pr=7, **_roots(tmp_path), dry_run=True)

    assert code == 0
    assert stages.names == ["approve-preflight-notes", "approve-review-followups"]
    out = capsys.readouterr().out
    assert "approve-preflight-notes [succeeded] (planned)" in out
    assert "approve-review-followups [succeeded] (planned) agent=review-approver" in out
    assert "gate (planned): approve-followups" in out


def test_a1_runs_in_its_declared_position_with_the_only_verify(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 7: A1 keeps the approval postcondition; repo-added stages run without it."""
    _init_repo(tmp_path)
    _write_stages_config(
        tmp_path,
        [
            _repo_added("approve-notes"),
            _repo_added("approve-recheck"),
            {"id": "A1"},
            _repo_added("approve-digest"),
        ],
    )
    _write_repo_added_prompt(tmp_path)
    _patch(monkeypatch, agents=_AGENTS)
    _approved(monkeypatch)
    stages = _FakeStages()
    monkeypatch.setattr(approve_workflow, "run_stage", stages)

    code = approve_workflow.run(pr=7, **_roots(tmp_path), approve_all=True)

    assert code == 0
    assert stages.names == [
        "approve-notes",
        "approve-recheck",
        "approve-review-followups",
        "approve-digest",
    ]
    assert [spec.id for spec in stages.specs] == [
        "approve-notes",
        "approve-recheck",
        "A1",
        "approve-digest",
    ]
    # Located by id, never by position: only A1 carries the postcondition.
    assert [callable(spec.verify) for spec in stages.specs] == [False, False, True, False]
    assert stages.specs[2].variables == ["7"]
    assert stages.specs[0].variables == []


def test_a_repo_added_stage_with_a_missing_prompt_is_refused(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 5: the preflight refuses exit 2 with ``format_issues`` text, no traceback."""
    _init_repo(tmp_path)
    _write_stages_config(tmp_path, [_repo_added("approve-notes"), {"id": "A1"}])
    _patch(monkeypatch, agents=_AGENTS)
    stages = _FakeStages()
    monkeypatch.setattr(approve_workflow, "run_stage", stages)

    code = approve_workflow.run(pr=7, **_roots(tmp_path), dry_run=True)

    assert code == 2
    err = capsys.readouterr().err
    assert "workflows.approve.stages" in err
    assert "`approve-notes`" in err
    assert "prompt does not resolve" in err
    assert stages.names == []


def test_a_repo_added_stage_with_an_unknown_agent_is_refused(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 4/req 5: an unknown declared ``agent`` refuses here, not in ``run_stage``."""
    _init_repo(tmp_path)
    entry = _repo_added("approve-notes")
    entry["agent"] = "no-such-agent"
    _write_stages_config(tmp_path, [entry, {"id": "A1"}])
    _write_repo_added_prompt(tmp_path)
    _patch(monkeypatch, agents=_AGENTS)
    stages = _FakeStages()
    monkeypatch.setattr(approve_workflow, "run_stage", stages)

    code = approve_workflow.run(pr=7, **_roots(tmp_path), dry_run=True)

    assert code == 2
    err = capsys.readouterr().err
    assert "unknown agent `no-such-agent`" in err
    assert stages.names == []
