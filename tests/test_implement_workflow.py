"""Tests for the ``aidw implement`` workflow (design §8.2, Phase 4)."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

from aidw import git
from aidw.paths import TargetRepo, WorkspacePaths
from aidw.state import (
    FAILED,
    SUCCEEDED,
    StageRecord,
    create_run,
    run_dir,
    save,
)
from aidw.workflows import implement as implement_workflow


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def _make_inputs(tmp_path: Path) -> Path:
    """A tmp repo with a task prompt; returns the prompt path."""
    _init_repo(tmp_path)
    prompt = tmp_path / "docs" / "task-prompts" / "03-E4.1-prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("# Implement E4.1\n", encoding="utf-8")
    (tmp_path / "aidt").mkdir()
    return prompt


def _runs_root(repo: Path) -> Path:
    """Where E1.4 writes run state: the per-repo state root, never the toolkit."""
    return WorkspacePaths.resolve(TargetRepo.resolve(repo)).state_root / "runs"


class _Recorder:
    """Fake ``run_stage`` that records stages and returns canned statuses."""

    def __init__(self, fail: set[str] | None = None) -> None:
        self.names: list[str] = []
        self.specs = []
        self.fail = fail or set()

    def __call__(self, spec, **kwargs):
        self.names.append(spec.name)
        self.specs.append(spec)
        directory = run_dir(kwargs["runs_root"], kwargs["state"].run_id)
        stages = directory / "stages"
        stages.mkdir(parents=True, exist_ok=True)
        out = stages / f"{spec.name}.out.txt"
        out.write_text(
            "https://github.com/o/r/pull/42\n" if spec.name == "pr" else "ok\n",
            encoding="utf-8",
        )
        status = FAILED if spec.name in self.fail else SUCCEEDED
        record = StageRecord(
            name=spec.name,
            agent=spec.agent_id,
            model="test/model",
            status=status,
            artifacts={"out": str(out)},
            error="boom" if status == FAILED else None,
        )
        kwargs["state"].record_stage(record)
        return record


def _patch(monkeypatch, *, branch: str = "03-E4.1"):
    monkeypatch.setattr(implement_workflow, "load_all", lambda aidt, repo: ({}, []))
    monkeypatch.setattr(git, "current_branch", lambda repo: branch)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


def test_parse_task_id_variants() -> None:
    assert implement_workflow.parse_task_id(Path("03-E4.1-prompt.md")) == (
        "03",
        "E4.1",
        "03-E4.1",
    )
    assert implement_workflow.parse_task_id(Path("03-E4.1.md")) == ("03", "E4.1", "03-E4.1")
    assert implement_workflow.parse_task_id(Path("02.5-B-prompt.md")) == (
        "02.5",
        "B",
        "02.5-B",
    )
    assert implement_workflow.parse_task_id(Path("nonsense.md")) is None


def test_build_plan_order_and_agents() -> None:
    plan = implement_workflow.build_plan(
        aidt=Path("/aidt"), prompt_rel="docs/task-prompts/03-E4.1-prompt.md",
        branch="03-E4.1", task_id="03-E4.1",
    )
    assert [(p.id, p.name) for p in plan] == [
        ("I1", "impliment-task"),
        ("I2", "test"),
        ("I3", "update-traceability"),
        ("I4", "update-architecture"),
        ("I5", "record-implementation-results"),
        ("I6", "pr"),
    ]
    assert [p.agent for p in plan] == [
        "implementer",
        "tester",
        "implementer",
        "implementer",
        "recorder",
        "pr-publisher",
    ]
    assert plan[0].variables == ["docs/task-prompts/03-E4.1-prompt.md"]
    assert plan[1].variables == [] and plan[1].extra
    assert plan[2].variables == ["03-E4.1"]
    assert plan[3].variables == ["03-E4.1", "main"]
    assert plan[5].variables == ["03-E4.1"]


# --------------------------------------------------------------------------- #
# Dry run
# --------------------------------------------------------------------------- #


def test_dry_run_plans_all_six_stages(tmp_path: Path, monkeypatch) -> None:
    prompt = _make_inputs(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, repo=tmp_path, aidt=tmp_path / "aidt", dry_run=True
    )

    assert code == 0
    assert recorder.names == [
        "impliment-task",
        "test",
        "update-traceability",
        "update-architecture",
        "record-implementation-results",
        "pr",
    ]


def test_dry_run_writes_runs_under_the_state_root(tmp_path: Path, monkeypatch) -> None:
    """E1.4: a run lives under the state root, never under ``repo/aidt/runs``.

    ``_make_inputs`` pre-creates ``repo/aidt``; after the run that tree must still have
    no ``runs/`` directory (the toolkit-root assumption is gone).
    """
    prompt = _make_inputs(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(implement_workflow, "run_stage", _Recorder())

    code = implement_workflow.run(
        task_prompt_path=prompt, repo=tmp_path, aidt=tmp_path / "aidt", dry_run=True
    )

    assert code == 0
    runs_root = _runs_root(tmp_path)
    run_dirs = list(runs_root.iterdir())
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "state.json").is_file()
    assert not (tmp_path / "aidt" / "runs").exists()


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #


def test_refuses_on_main(tmp_path: Path, monkeypatch) -> None:
    prompt = _make_inputs(tmp_path)
    _patch(monkeypatch, branch="main")
    monkeypatch.setattr(implement_workflow, "run_stage", _Recorder())

    code = implement_workflow.run(
        task_prompt_path=prompt, repo=tmp_path, aidt=tmp_path / "aidt"
    )

    assert code == 4


def test_refuses_on_branch_mismatch(tmp_path: Path, monkeypatch) -> None:
    prompt = _make_inputs(tmp_path)
    _patch(monkeypatch, branch="04-A1")
    monkeypatch.setattr(implement_workflow, "run_stage", _Recorder())

    code = implement_workflow.run(
        task_prompt_path=prompt, repo=tmp_path, aidt=tmp_path / "aidt"
    )

    assert code == 4


def test_missing_prompt_is_usage_error(tmp_path: Path, monkeypatch) -> None:
    _make_inputs(tmp_path)
    _patch(monkeypatch)
    code = implement_workflow.run(
        task_prompt_path=tmp_path / "docs" / "task-prompts" / "nope.md",
        repo=tmp_path,
        aidt=tmp_path / "aidt",
    )
    assert code == 2


# --------------------------------------------------------------------------- #
# Execution, gates, resume
# --------------------------------------------------------------------------- #


def test_full_run_succeeds_and_records_pr(tmp_path: Path, monkeypatch) -> None:
    prompt = _make_inputs(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(implement_workflow, "run_stage", _Recorder())

    code = implement_workflow.run(
        task_prompt_path=prompt,
        repo=tmp_path,
        aidt=tmp_path / "aidt",
        approve_all=True,
    )

    assert code == 0
    runs = list(_runs_root(tmp_path).iterdir())
    state = implement_workflow.list_runs(_runs_root(tmp_path))[-1]
    assert state.status == SUCCEEDED
    assert state.gates and state.gates[-1].name == implement_workflow.GATE
    assert state.pr.get("number") == 42
    assert len(runs) == 1
    assert not (tmp_path / "aidt" / "runs").exists()


def test_stage_failure_returns_one(tmp_path: Path, monkeypatch) -> None:
    prompt = _make_inputs(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(implement_workflow, "run_stage", _Recorder(fail={"test"}))

    code = implement_workflow.run(
        task_prompt_path=prompt,
        repo=tmp_path,
        aidt=tmp_path / "aidt",
        approve_all=True,
    )

    assert code == 1
    state = implement_workflow.list_runs(_runs_root(tmp_path))[-1]
    assert state.status == FAILED


def test_gate_denied_returns_blocked(tmp_path: Path, monkeypatch) -> None:
    prompt = _make_inputs(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    # No --yes and a non-interactive session: the gate fails closed.
    code = implement_workflow.run(
        task_prompt_path=prompt, repo=tmp_path, aidt=tmp_path / "aidt"
    )

    assert code == 3
    # The PR stage must not have run after a denied gate.
    assert "pr" not in recorder.names


def test_resume_skips_succeeded_stages(tmp_path: Path, monkeypatch) -> None:
    prompt = _make_inputs(tmp_path)
    _patch(monkeypatch)
    runs_dir = _runs_root(tmp_path)

    state = create_run(
        runs_dir,
        tmp_path,
        "implement",
        label="03-E4.1",
        task={"phase": "03", "task": "E4.1"},
        branch="03-E4.1",
    )
    directory = run_dir(runs_dir, state.run_id)
    state.record_stage(
        StageRecord(name="impliment-task", agent="implementer", model="m", status=SUCCEEDED)
    )
    state.record_stage(
        StageRecord(
            name="test", agent="tester", model="m", status=FAILED, error="boom"
        )
    )
    state.status = FAILED
    save(directory, state)

    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        repo=tmp_path,
        aidt=tmp_path / "aidt",
        resume=True,
        approve_all=True,
    )

    assert code == 0
    assert "impliment-task" not in recorder.names
    assert recorder.names == [
        "test",
        "update-traceability",
        "update-architecture",
        "record-implementation-results",
        "pr",
    ]


def test_from_forces_rerun(tmp_path: Path, monkeypatch) -> None:
    prompt = _make_inputs(tmp_path)
    _patch(monkeypatch)
    runs_dir = _runs_root(tmp_path)

    state = create_run(
        runs_dir, tmp_path, "implement", label="03-E4.1", branch="03-E4.1"
    )
    directory = run_dir(runs_dir, state.run_id)
    for name in ("impliment-task", "test", "update-traceability"):
        state.record_stage(
            StageRecord(name=name, agent="implementer", model="m", status=SUCCEEDED)
        )
    save(directory, state)

    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        repo=tmp_path,
        aidt=tmp_path / "aidt",
        resume=True,
        from_stage="test",
        approve_all=True,
    )

    assert code == 0
    assert recorder.names[0] == "test"
    assert "impliment-task" not in recorder.names


# --------------------------------------------------------------------------- #
# git.changed_files
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# --parallel
# --------------------------------------------------------------------------- #


class _TrackingStages(_Recorder):
    """Recorder that tracks how many stages run at the same time."""

    def __init__(self) -> None:
        super().__init__()
        self._guard = threading.Lock()
        self.active = 0
        self.max_active = 0

    def __call__(self, spec, **kwargs):
        with self._guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if spec.name in ("test", "update-architecture"):
                time.sleep(0.05)
            return super().__call__(spec, **kwargs)
        finally:
            with self._guard:
                self.active -= 1


def test_serial_runs_the_pair_one_at_a_time(tmp_path: Path, monkeypatch) -> None:
    prompt = _make_inputs(tmp_path)
    _patch(monkeypatch)
    recorder = _TrackingStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        repo=tmp_path,
        aidt=tmp_path / "aidt",
        approve_all=True,
    )

    assert code == 0
    assert recorder.max_active == 1


def test_parallel_runs_test_and_architecture_concurrently(
    tmp_path: Path, monkeypatch
) -> None:
    prompt = _make_inputs(tmp_path)
    _patch(monkeypatch)
    recorder = _TrackingStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        repo=tmp_path,
        aidt=tmp_path / "aidt",
        approve_all=True,
        parallel=True,
    )

    assert code == 0
    assert recorder.max_active >= 2
    assert set(recorder.names[:3]) == {
        "impliment-task",
        "test",
        "update-architecture",
    }
    assert recorder.names[3:] == [
        "update-traceability",
        "record-implementation-results",
        "pr",
    ]


def test_changed_files_lists_branch_diff(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "checkout", "-qb", "feature"], cwd=tmp_path, check=True)
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "b"], cwd=tmp_path, check=True)

    assert git.changed_files(tmp_path, "main") == ["b.txt"]
