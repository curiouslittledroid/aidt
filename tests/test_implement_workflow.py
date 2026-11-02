"""Tests for the ``aidw implement`` workflow (design §8.2, Phase 4; E2.6).

E2.6 turns branch setup into a **locate**: ``run()`` derives the branch/worktree name
from ``repo.branch_pattern``, finds the worktree ``aidw prompt`` (E2.5) already created
with ``git.worktree_for_branch``, and re-resolves the target/agents so I1..I6 run in it.
A missing worktree is a preflight refusal (exit 4) that prints the §3.2 ``worktree add``
command; implement no longer creates one or copies the prompt. The harness therefore
builds the real bare+control layout (EXTRACTION.md §3.2), pre-creating the task worktree
with real git, and never fakes git output; only the Pi seam (``run_stage``) is mocked.
"""

from __future__ import annotations

import dataclasses
import subprocess
import threading
import time
from pathlib import Path

import pytest

from aidw import git
from aidw.config import ERROR, Issue
from aidw.gates import GateOutcome
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.state import (
    FAILED,
    SUCCEEDED,
    StageRecord,
    create_run,
    run_dir,
    save,
)
from aidw.workflows import implement as implement_workflow


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


def _write_prompt(control: Path, name: str = "03-E4.1-prompt.md") -> Path:
    """Write the task prompt into the control worktree **uncommitted** (the real layout)."""
    prompt = control / "docs" / "task-prompts" / name
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("# Implement E4.1\n", encoding="utf-8")
    return prompt


def _layout(tmp_path: Path) -> tuple[Path, Path]:
    """Control root plus the prompt uncommitted there (no task worktree. E2.6)."""
    _bare, control = _make_bare_with_control(tmp_path)
    return control, _write_prompt(control)


def _make_task_worktree(
    control: Path,
    branch: str = "03-E4.1",
    name: str = "03-E4.1-prompt.md",
    base_branch: str = "main",
) -> tuple[Path, Path]:
    """Pre-create the task worktree and commit the prompt inside it (the E2.5 layout).

    This is what ``aidw prompt`` leaves behind: the branch's worktree is created, the
    task prompt is committed there, and the control root stays on the base branch.
    """
    worktree = git.add_worktree(control, branch, base_branch=base_branch)
    assert worktree is not None
    prompt = worktree / "docs" / "task-prompts" / name
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("# Implement E4.1\n", encoding="utf-8")
    _git_run(worktree, "add", ".")
    _git_run(worktree, "commit", "-qm", "task prompt")
    return worktree, prompt


def _located_layout(
    tmp_path: Path,
    branch: str = "03-E4.1",
    name: str = "03-E4.1-prompt.md",
    base_branch: str = "main",
) -> tuple[Path, Path, Path]:
    """Control root plus a ready task worktree/prompt (the E2.5/E2.6 happy path)."""
    _bare, control = _make_bare_with_control(tmp_path)
    worktree, prompt = _make_task_worktree(control, branch, name, base_branch)
    return control, worktree, prompt


def _roots(control: Path) -> dict:
    target = TargetRepo.resolve(control)
    return {
        "repo": target,
        "aidt": ToolkitPaths.resolve(),
        "workspace": WorkspacePaths.resolve(
            target, state_dir_override=control.parent / "aidt-state"
        ),
    }


def _runs_root(control: Path) -> Path:
    """Where E1.4 writes run state: the per-repo state root, never the toolkit."""
    return _roots(control)["workspace"].state_root / "runs"


class _Recorder:
    """Fake ``run_stage`` that records stages and returns canned statuses."""

    def __init__(self, fail: set[str] | None = None) -> None:
        self.names: list[str] = []
        self.specs = []
        self.repo_roots: list[Path] = []
        self.fail = fail or set()

    def __call__(self, spec, **kwargs):
        self.names.append(spec.name)
        self.specs.append(spec)
        self.repo_roots.append(kwargs["repo_root"])
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


def _patch(monkeypatch) -> None:
    monkeypatch.setattr(implement_workflow, "load_all", lambda aidt, repo: ({}, []))


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


def test_derive_branch_name_default_reproduces_the_task_id() -> None:
    pattern = "{phase}-{task}"
    assert implement_workflow.derive_branch_name(pattern, phase="00", task="E2.4") == "00-E2.4"
    # The dotted-phase form must survive byte-for-byte.
    assert implement_workflow.derive_branch_name(pattern, phase="02.5", task="B") == "02.5-B"


def test_derive_branch_name_rejects_malformed_patterns() -> None:
    # References only one of phase/task: a constant/partial name collides across tasks.
    assert implement_workflow.derive_branch_name("{phase}", phase="00", task="E2.4") is None
    assert implement_workflow.derive_branch_name("static", phase="00", task="E2.4") is None
    # Unknown placeholder: str.format raises KeyError.
    assert (
        implement_workflow.derive_branch_name(
            "{phase}-{task}-{extra}", phase="00", task="E2.4"
        )
        is None
    )
    # Unbalanced braces raise ValueError.
    assert implement_workflow.derive_branch_name("{phase}-{task", phase="00", task="E2.4") is None


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


def test_build_plan_uses_the_configured_base_branch() -> None:
    plan = implement_workflow.build_plan(
        aidt=Path("/aidt"), prompt_rel="docs/task-prompts/03-E4.1-prompt.md",
        branch="03-E4.1", task_id="03-E4.1", base_branch="develop",
    )
    assert plan[3].variables == ["03-E4.1", "develop"]


# --------------------------------------------------------------------------- #
# Branch-name derivation at the run seam
# --------------------------------------------------------------------------- #


def test_non_default_branch_pattern_names_branch_worktree_and_state(
    tmp_path: Path, monkeypatch
) -> None:
    control, worktree, prompt = _located_layout(
        tmp_path, branch="E4.1-03", name="03-E4.1-prompt.md"
    )
    roots = _roots(control)
    roots["repo"] = dataclasses.replace(
        roots["repo"], branch_pattern="{task}-{phase}"
    )
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(task_prompt_path=prompt, **roots, approve_all=True)

    assert code == 0
    assert worktree == (tmp_path / "E4.1-03").resolve()
    assert recorder.repo_roots[0] == worktree
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert state.git.get("branch") == "E4.1-03"


@pytest.mark.parametrize("pattern", ["static", "{phase}", "{phase}-{task}-{extra}"])
def test_malformed_branch_pattern_is_usage_error_before_worktree(
    tmp_path: Path, monkeypatch, pattern: str
) -> None:
    control, prompt = _layout(tmp_path)
    roots = _roots(control)
    roots["repo"] = dataclasses.replace(roots["repo"], branch_pattern=pattern)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(task_prompt_path=prompt, **roots)

    # A pattern missing a placeholder, or naming an unknown one, is refused before
    # branch-setup: no worktree, no stage, no run state.
    assert code == 2
    assert recorder.names == []
    assert not (tmp_path / "03-E4.1").exists()
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []


# --------------------------------------------------------------------------- #
# Dry run
# --------------------------------------------------------------------------- #


def test_dry_run_plans_locate_and_all_six_stages(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    control, prompt = _layout(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
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
    out = capsys.readouterr().out
    command = (
        f"git -C {tmp_path / 'main'} worktree add -b 03-E4.1 "
        f"{tmp_path / '03-E4.1'} main"
    )
    # The dry run plans the locate, not a ``worktree add`` it no longer performs, and
    # prints the corrective command copy-pasteable (E2.6 req 4/req 6).
    assert f"worktree (planned): {tmp_path / '03-E4.1'}" in out
    assert f"branch-setup (planned): {command}" in out
    # A dry run performs no worktree writes.
    assert not (tmp_path / "03-E4.1").exists()
    # The prompt argument is re-based onto the planned worktree (req 2/req 6).
    assert recorder.specs[0].variables == ["docs/task-prompts/03-E4.1-prompt.md"]


def test_dry_run_writes_runs_under_the_state_root(tmp_path: Path, monkeypatch) -> None:
    """E1.4: a run lives under the state root, never under ``repo/aidt/runs``."""
    control, prompt = _layout(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(implement_workflow, "run_stage", _Recorder())

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 0
    runs_root = _runs_root(control)
    run_dirs = list(runs_root.iterdir())
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "state.json").is_file()
    assert not (control / "aidt" / "runs").exists()


# --------------------------------------------------------------------------- #
# Branch setup creates the worktree before I1
# --------------------------------------------------------------------------- #


def test_locates_existing_worktree_and_runs_every_stage_in_it(
    tmp_path: Path, monkeypatch
) -> None:
    control, worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert recorder.names[0] == "impliment-task"
    # Every stage ran in the located worktree, not the control root.
    assert recorder.repo_roots == [worktree] * len(recorder.repo_roots)
    # No second worktree was created: one branch maps to exactly one worktree.
    branches = [entry.branch for entry in git.worktrees(control) if entry.branch]
    assert branches.count("03-E4.1") == 1


def test_repo_override_from_unrelated_cwd_locates_the_worktree(
    tmp_path: Path, monkeypatch
) -> None:
    """``--repo``/``explicit=`` selects the control root; the lookup follows it."""
    control, worktree, prompt = _located_layout(tmp_path)
    unrelated = tmp_path / "elsewhere"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    target = TargetRepo.resolve(explicit=control)
    workspace = WorkspacePaths.resolve(
        target, state_dir_override=control.parent / "aidt-state"
    )
    code = implement_workflow.run(
        task_prompt_path=prompt,
        repo=target,
        aidt=ToolkitPaths.resolve(),
        workspace=workspace,
        approve_all=True,
    )

    assert code == 0
    assert recorder.repo_roots[0] == worktree


def test_base_branch_flows_through_the_whole_run(tmp_path: Path, monkeypatch) -> None:
    bare, control = _make_bare_with_control(tmp_path)
    # develop exists and is one commit ahead of main.
    _git_run(bare, "branch", "develop", "main")
    develop_wt = tmp_path / "develop"
    _git_run(bare, "worktree", "add", "-q", str(develop_wt), "develop")
    (develop_wt / "g.txt").write_text("g\n", encoding="utf-8")
    _git_run(develop_wt, "add", ".")
    _git_run(develop_wt, "commit", "-qm", "develop work")
    _git_run(bare, "worktree", "remove", str(develop_wt))
    worktree, prompt = _make_task_worktree(control, base_branch="develop")

    roots = _roots(control)
    roots["repo"] = dataclasses.replace(roots["repo"], base_branch="develop")
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)
    summaries: list[str] = []

    def capture_gate(_name: str, summary: str, **_kwargs) -> GateOutcome:
        summaries.append(summary)
        return GateOutcome(implement_workflow.GATE, True, "test")

    monkeypatch.setattr(implement_workflow, "decide", capture_gate)

    code = implement_workflow.run(task_prompt_path=prompt, **roots, approve_all=True)

    assert code == 0
    assert len(summaries) == 1
    prompt_rel = "docs/task-prompts/03-E4.1-prompt.md"
    # develop contains g.txt while main does not; the gate summary must use the
    # configured base just as the PR record does, so it must not report g.txt.
    assert "g.txt" not in summaries[0]
    assert worktree == (tmp_path / "03-E4.1").resolve()
    # The worktree branches from develop: only the committed prompt differs from develop.
    assert git.changed_files(worktree, "develop") == [prompt_rel]
    # state.pr.changed_files and I4's base_ref both measure against develop.
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert state.pr.get("changed_files") == [prompt_rel]
    arch = next(s for s in recorder.specs if s.name == "update-architecture")
    assert arch.variables == ["03-E4.1", "develop"]


# --------------------------------------------------------------------------- #
# Preflight (retained still-running guard; fail-closed branch setup)
# --------------------------------------------------------------------------- #


def test_agents_are_reloaded_against_the_located_worktree(
    tmp_path: Path, monkeypatch
) -> None:
    control, worktree, prompt = _located_layout(tmp_path)
    load_roots: list[Path] = []

    def record_load(_aidt: Path, repo_root: Path):
        load_roots.append(repo_root)
        return {}, []

    monkeypatch.setattr(implement_workflow, "load_all", record_load)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    # Config validates against the control root first, then agents reload for the worktree.
    assert load_roots == [control.resolve(), worktree]
    assert recorder.repo_roots[0] == worktree


def test_missing_prompt_is_usage_error(tmp_path: Path, monkeypatch) -> None:
    control, _prompt = _layout(tmp_path)
    _patch(monkeypatch)
    code = implement_workflow.run(
        task_prompt_path=control / "docs" / "task-prompts" / "nope.md",
        **_roots(control),
    )
    assert code == 2


def test_relative_prompt_resolves_inside_the_worktree(
    tmp_path: Path, monkeypatch
) -> None:
    """A relative argument is a repo-relative subpath of the worktree, not the control root."""
    control, worktree, _prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=Path("docs/task-prompts/03-E4.1-prompt.md"),
        **_roots(control),
        approve_all=True,
    )

    assert code == 0
    assert recorder.specs[0].variables == ["docs/task-prompts/03-E4.1-prompt.md"]
    assert recorder.repo_roots[0] == worktree


def test_config_error_wins_over_missing_worktree(tmp_path: Path, monkeypatch) -> None:
    """Config validation stays pre-locate, so bad config is exit 2, not exit 4."""
    control, _prompt = _layout(tmp_path)  # no task worktree
    issue = Issue(ERROR, "config", "bad config")
    monkeypatch.setattr(implement_workflow, "load_all", lambda aidt, repo: ({}, [issue]))
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=control / "docs" / "task-prompts" / "03-E4.1-prompt.md",
        **_roots(control),
    )

    assert code == 2
    assert recorder.names == []


def test_reloaded_worktree_config_error_is_usage_error(
    tmp_path: Path, monkeypatch
) -> None:
    control, worktree, prompt = _located_layout(tmp_path)
    calls: list[Path] = []

    def load_for_root(_aidt: Path, repo_root: Path):
        calls.append(repo_root)
        if repo_root == worktree:
            return {}, [Issue(ERROR, "config", "bad config in task worktree")]
        return {}, []

    monkeypatch.setattr(implement_workflow, "load_all", load_for_root)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 2
    assert calls == [control.resolve(), worktree]
    assert recorder.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []


def test_relative_prompt_cannot_escape_the_task_worktree(
    tmp_path: Path, monkeypatch
) -> None:
    control, _worktree, _prompt = _located_layout(tmp_path)
    escaped = tmp_path / "escaped" / "docs" / "task-prompts" / "03-E4.1-prompt.md"
    escaped.parent.mkdir(parents=True)
    escaped.write_text("outside the worktree\n", encoding="utf-8")
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=Path("../escaped/docs/task-prompts/03-E4.1-prompt.md"),
        **_roots(control),
        approve_all=True,
    )

    assert code == 2
    assert recorder.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []


def test_located_worktree_missing_prompt_is_usage_error(
    tmp_path: Path, monkeypatch
) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    worktree = git.add_worktree(control, "03-E4.1")
    assert worktree is not None  # located, but the prompt was never committed there
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=Path("docs/task-prompts/03-E4.1-prompt.md"),
        **_roots(control),
    )

    assert code == 2
    assert recorder.names == []


def test_located_worktree_missing_prompt_is_usage_error_in_dry_run(
    tmp_path: Path, monkeypatch
) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    assert git.add_worktree(control, "03-E4.1") is not None
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=Path("docs/task-prompts/03-E4.1-prompt.md"),
        **_roots(control),
        dry_run=True,
    )

    # A located worktree still refuses in dry-run; only the absent-worktree case suspends
    # the existence check.
    assert code == 2
    assert recorder.names == []


def test_running_run_is_refused_without_resume(tmp_path: Path, monkeypatch) -> None:
    control, prompt = _layout(tmp_path)
    _patch(monkeypatch)
    runs_root = _runs_root(control)
    create_run(runs_root, control, "implement", label="03-E4.1", branch="03-E4.1")
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(task_prompt_path=prompt, **_roots(control))

    assert code == 4
    assert recorder.names == []
    assert not (tmp_path / "03-E4.1").exists()
    # No second run state was written.
    assert len(list(_runs_root(control).iterdir())) == 1


def test_missing_worktree_is_refused_with_the_command(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    control, prompt = _layout(tmp_path)  # no task worktree
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 4
    assert recorder.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []
    command = (
        f"git -C {tmp_path / 'main'} worktree add -b 03-E4.1 "
        f"{tmp_path / '03-E4.1'} main"
    )
    assert command in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Execution, gates, resume
# --------------------------------------------------------------------------- #


def test_full_run_succeeds_and_records_pr(tmp_path: Path, monkeypatch) -> None:
    control, worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(implement_workflow, "run_stage", _Recorder())

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        approve_all=True,
    )

    assert code == 0
    runs = list(_runs_root(control).iterdir())
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert state.status == SUCCEEDED
    assert state.repo_root == str(worktree)
    assert state.gates and state.gates[-1].name == implement_workflow.GATE
    assert state.pr.get("number") == 42
    assert len(runs) == 1
    assert not (control / "aidt" / "runs").exists()


def test_stage_failure_returns_one(tmp_path: Path, monkeypatch) -> None:
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(implement_workflow, "run_stage", _Recorder(fail={"test"}))

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        approve_all=True,
    )

    assert code == 1
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert state.status == FAILED


def test_gate_denied_returns_blocked(tmp_path: Path, monkeypatch) -> None:
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    # No --yes and a non-interactive session: the gate fails closed.
    code = implement_workflow.run(task_prompt_path=prompt, **_roots(control))

    assert code == 3
    # The PR stage must not have run after a denied gate.
    assert "pr" not in recorder.names


def test_resume_skips_succeeded_stages(tmp_path: Path, monkeypatch) -> None:
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    runs_dir = _runs_root(control)

    state = create_run(
        runs_dir,
        control,
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
        **_roots(control),
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
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    runs_dir = _runs_root(control)

    state = create_run(
        runs_dir, control, "implement", label="03-E4.1", branch="03-E4.1"
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
        **_roots(control),
        resume=True,
        from_stage="test",
        approve_all=True,
    )

    assert code == 0
    assert recorder.names[0] == "test"
    assert "impliment-task" not in recorder.names


def test_unknown_from_stage_is_usage_error_before_worktree(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """F1 (PR #49 review follow-up): a typo'd ``--from`` refuses with exit 2 and
    leaves behind neither a worktree nor a run directory — the same fail-closed
    contract as the malformed-pattern refusal."""
    control, prompt = _layout(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), from_stage="bogus"
    )

    assert code == 2
    assert recorder.names == []
    assert not (tmp_path / "03-E4.1").exists()
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []
    err = capsys.readouterr().err
    assert "unknown stage `bogus`" in err
    assert "impliment-task" in err  # the message lists the expected stage names


def test_resume_declined_leaves_no_worktree(tmp_path: Path, monkeypatch, capsys) -> None:
    """F2 (PR #49 review follow-up): declining the ``--resume`` confirmation
    must leave no worktree behind — the confirm happens before branch setup,
    so a refusal creates neither worktree nor run state (same fail-closed
    contract as the still-running guard)."""
    control, prompt = _layout(tmp_path)
    _patch(monkeypatch)
    runs_dir = _runs_root(control)
    state = create_run(
        runs_dir, control, "implement", label="03-E4.1", branch="03-E4.1"
    )
    directory = run_dir(runs_dir, state.run_id)
    state.record_stage(
        StageRecord(name="impliment-task", agent="implementer", model="m", status=SUCCEEDED)
    )
    state.status = FAILED
    save(directory, state)

    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)
    # Non-interactive stdin would auto-confirm, so fake the explicit "no".
    monkeypatch.setattr(implement_workflow, "_confirm_resume", lambda assume_yes: False)

    code = implement_workflow.run(task_prompt_path=prompt, **_roots(control), resume=True)

    assert code == 4
    assert recorder.names == []
    # Decline creates nothing: no sibling worktree in the workspace root.
    assert not (tmp_path / "03-E4.1").exists()
    # Exactly the pre-existing run state; no new run was written.
    assert len(list(_runs_root(control).iterdir())) == 1
    err = capsys.readouterr().err
    assert "resume declined." in err


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
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _TrackingStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        approve_all=True,
    )

    assert code == 0
    assert recorder.max_active == 1


def test_parallel_runs_test_and_architecture_concurrently(
    tmp_path: Path, monkeypatch
) -> None:
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _TrackingStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
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


# --------------------------------------------------------------------------- #
# git.changed_files
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Prompt cleanliness
# --------------------------------------------------------------------------- #


def test_impliment_prompt_has_no_agent_branch_setup() -> None:
    text = (ToolkitPaths.resolve().prompts_dir / "impliment-task.md").read_text(
        encoding="utf-8"
    )
    assert "git checkout -b" not in text
    assert "git switch -c" not in text
    assert "git branch --list" not in text
    assert "git ls-remote" not in text
    assert "### Branch setup (do this first" not in text
    # The one-line pointer that AIDT owns it stays.
    assert "AIDT owns branch setup" in text
