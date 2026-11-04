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

from aidw import git, lock
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
from aidw.target_config import load_target_config, resolve_config
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


def _write_config(control: Path, body: str) -> None:
    """Write the target config the preflight reads (``<target>/aidw/config.yaml``, §3.4)."""
    config = control / "aidw" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(body, encoding="utf-8")


#: The registry's implement order (I1..I6), the serial schedule.
DEFAULT_ORDER = [
    "impliment-task",
    "test",
    "update-traceability",
    "update-architecture",
    "record-implementation-results",
    "pr",
]


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
    # Since E4.3 `build_plan` is the registry's expansion, so `variables` is the registry's
    # frozen tuple (`aidw.stage_registry.PlannedStage`), not a mutable list.
    assert plan[0].variables == ("docs/task-prompts/03-E4.1-prompt.md",)
    assert plan[1].variables == () and plan[1].extra
    assert plan[2].variables == ("03-E4.1",)
    assert plan[3].variables == ("03-E4.1", "main")
    assert plan[5].variables == ("03-E4.1",)


def test_build_plan_uses_the_configured_base_branch() -> None:
    plan = implement_workflow.build_plan(
        aidt=Path("/aidt"), prompt_rel="docs/task-prompts/03-E4.1-prompt.md",
        branch="03-E4.1", task_id="03-E4.1", base_branch="develop",
    )
    assert plan[3].variables == ("03-E4.1", "develop")


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
    # The plan lines print the retained stage id, which since E4.3 rides on
    # ``StageSpec.id`` (``id`` and ``name`` are different fields): a lost carrier would
    # silently drop the ``I1 …`` prefix and change this output.
    for line in (
        "I1 impliment-task [succeeded] (planned)",
        "I2 test [succeeded] (planned)",
        "I3 update-traceability [succeeded] (planned)",
        "I4 update-architecture [succeeded] (planned)",
        "I5 record-implementation-results [succeeded] (planned)",
        "I6 pr [succeeded] (planned)",
    ):
        assert line in out


def test_dry_run_renders_a_repo_declared_prompt_override(
    tmp_path: Path, monkeypatch
) -> None:
    """E4.3: a config's D14 ``prompt:`` changes the prompt the planned stage renders."""
    control, prompt = _layout(tmp_path)
    override = control / "aidw" / "prompts" / "update-traceability.md"
    override.parent.mkdir(parents=True)
    override.write_text("# repo traceability rules\n", encoding="utf-8")
    # A declared list replaces the registry's wholesale (§3.4), so it must carry every
    # core stage (E4.5a's removal rule) — the prompt: override rides on I3's entry.
    (control / "aidw" / "config.yaml").write_text(
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    stages:\n"
        "      - id: I1\n"
        "      - id: I2\n"
        "      - id: I3\n"
        "        prompt: aidw/prompts/update-traceability.md\n"
        "      - id: I4\n"
        "      - id: I5\n"
        "      - id: I6\n",
        encoding="utf-8",
    )
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 0
    # I3 resolves to the repo's declared file; every other stage keeps the toolkit default.
    assert recorder.specs[2].prompt == override.resolve()
    assert recorder.specs[2].explicit_prompt == "aidw/prompts/update-traceability.md"
    assert recorder.specs[1].prompt == (
        ToolkitPaths.resolve().prompts_dir / "test.md"
    )
    assert recorder.specs[1].explicit_prompt is None


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
    """Recorder that tracks how many stages run at the same time.

    ``slow`` names the stages that park briefly so a group of them overlaps measurably;
    it defaults to the registry's safe pair and is widened by the E4.4 tests that
    configure a different group.
    """

    def __init__(self, slow: set[str] | None = None) -> None:
        super().__init__()
        self._guard = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.slow = {"test", "update-architecture"} if slow is None else slow

    def __call__(self, spec, **kwargs):
        with self._guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if spec.name in self.slow:
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
# --parallel: config-driven parallel_groups (E4.4, EXTRACTION.md §3.4/§3.5, R11)
# --------------------------------------------------------------------------- #


def test_effective_parallel_groups_distinguishes_absent_from_declared_empty(
    tmp_path: Path,
) -> None:
    """Absent entry → the registry default; an explicit ``[]`` → no groups (serial)."""
    resolved = resolve_config(load_target_config(tmp_path / "aidw" / "config.yaml"))
    assert "workflows.implement.parallel_groups" not in resolved
    assert implement_workflow.effective_parallel_groups(resolved) == (
        ("test", "update-architecture"),
    )

    _write_config(
        tmp_path,
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    parallel_groups: []\n",
    )
    resolved = resolve_config(load_target_config(tmp_path / "aidw" / "config.yaml"))
    assert resolved["workflows.implement.parallel_groups"].source == "config"
    assert implement_workflow.effective_parallel_groups(resolved) == ()


def test_parallel_runs_a_configured_group_instead_of_the_default_pair(
    tmp_path: Path, monkeypatch
) -> None:
    control, _worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control,
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    parallel_groups:\n"
        "      - [test, record-implementation-results]\n",
    )
    _patch(monkeypatch)
    # Slow the non-member too: an implementation that accidentally retained the default
    # pair would overlap all three, making this exact bound fail.
    recorder = _TrackingStages(
        slow={"test", "record-implementation-results", "update-architecture"}
    )
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True, parallel=True
    )

    assert code == 0
    assert recorder.max_active == 2
    assert set(recorder.names[:3]) == {
        "impliment-task",
        "test",
        "record-implementation-results",
    }
    # The default pair's other member is no longer grouped: it keeps registry order and
    # runs on its own. Nothing hardcoded survived the replacement.
    assert recorder.names[3:] == ["update-traceability", "update-architecture", "pr"]


def test_parallel_group_runs_at_its_earliest_member_not_its_first_listed(
    tmp_path: Path, monkeypatch
) -> None:
    """A group's members run at the position of its *earliest* member (I2 here)."""
    control, _worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control,
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    parallel_groups:\n"
        "      - [update-architecture, test]\n",
    )
    _patch(monkeypatch)
    recorder = _TrackingStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True, parallel=True
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


def test_parallel_with_an_explicit_empty_group_list_runs_serially(
    tmp_path: Path, monkeypatch
) -> None:
    """``parallel_groups: []`` means serial — never a fallback to the default pair."""
    control, _worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control,
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    parallel_groups: []\n",
    )
    _patch(monkeypatch)
    recorder = _TrackingStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True, parallel=True
    )

    assert code == 0
    # The default pair would have overlapped here; the declared empty list does not.
    assert recorder.max_active == 1
    assert recorder.names == DEFAULT_ORDER


def test_a_group_naming_the_pr_stage_leaves_pr_in_its_post_gate_slot(
    tmp_path: Path, monkeypatch
) -> None:
    """``pr`` is a valid stage name but the post-gate sync point, so it still runs alone."""
    control, _worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control,
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    parallel_groups:\n"
        "      - [test, pr]\n",
    )
    _patch(monkeypatch)
    recorder = _TrackingStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True, parallel=True
    )

    assert code == 0
    assert recorder.names == DEFAULT_ORDER
    assert recorder.max_active == 1


def test_a_group_member_failure_stops_the_run_with_a_resume_hint(
    tmp_path: Path, monkeypatch
) -> None:
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _TrackingStages()
    recorder.fail = {"update-architecture"}
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True, parallel=True
    )

    assert code == 1
    # No later stage ran: the tail and I6 are absent.
    assert set(recorder.names) == {"impliment-task", "test", "update-architecture"}
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    # By name, not by position: the two group members record in completion order.
    assert state.stage("update-architecture").status == FAILED
    assert state.stage("test").status == SUCCEEDED
    assert state.status == FAILED
    # Deterministic: the earliest failed member in registry order, not completion order.
    assert state.resume == {"next_stage": "update-architecture"}


@pytest.mark.parametrize("dry_run", [False, True])
def test_unknown_parallel_group_member_fails_closed_before_any_run_state(
    tmp_path: Path, monkeypatch, capsys, dry_run: bool
) -> None:
    control, prompt = _layout(tmp_path)
    _write_config(
        control,
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    parallel_groups:\n"
        "      - [test, nonesuch]\n",
    )
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=dry_run
    )

    assert code == 2
    assert recorder.names == []
    # Before any worktree or run record: the refusal precedes branch setup.
    assert not (tmp_path / "03-E4.1").exists()
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []
    err = capsys.readouterr().err
    assert "workflows.implement.parallel_groups" in err
    assert "group [0]" in err
    assert "nonesuch" in err


def test_empty_inner_parallel_group_fails_closed_even_in_dry_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    control, prompt = _layout(tmp_path)
    _write_config(
        control,
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    parallel_groups:\n"
        "      - []\n",
    )
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 2
    assert recorder.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []
    err = capsys.readouterr().err
    assert "group [0]" in err
    assert "names no stage" in err


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


# --------------------------------------------------------------------------- #
# One run per worktree (E2.7, EXTRACTION.md §3.2/§3.10)
# --------------------------------------------------------------------------- #


class _BlockingStages(_Recorder):
    """A fake ``run_stage`` that parks the first run inside its first stage.

    Parking there (not before ``create_run``) is what makes two runs genuinely
    concurrent: the holder owns its worktree lock *and* has already written its run
    directory, which is exactly the double-run the lock must refuse.
    """

    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        super().__init__()
        self.entered = entered
        self.release_event = release

    def __call__(self, spec, **kwargs):
        self.entered.set()
        assert self.release_event.wait(timeout=60), "the holder was never released"
        return super().__call__(spec, **kwargs)


def _start_run(**kwargs) -> tuple[threading.Thread, dict]:
    """Call ``implement.run`` on a thread; ``outcome['code']`` holds its exit code."""
    outcome: dict = {}

    def target() -> None:
        try:
            outcome["code"] = implement_workflow.run(**kwargs)
        except BaseException as exc:  # pragma: no cover - asserted via ``outcome``
            outcome["error"] = exc

    thread = threading.Thread(target=target, name="aidw-implement-run")
    thread.start()
    return thread, outcome


def _two_task_worktrees(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    """Control root plus two worktrees, each with its own committed task prompt."""
    _bare, control = _make_bare_with_control(tmp_path)
    first, first_prompt = _make_task_worktree(control, "03-E4.1", "03-E4.1-prompt.md")
    second, second_prompt = _make_task_worktree(control, "03-E4.2", "03-E4.2-prompt.md")
    return control, first, first_prompt, second, second_prompt


def test_two_concurrent_runs_in_one_worktree_are_refused(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The lock, not the branch-keyed still-running guard, refuses a live peer.

    The second run passes ``--resume`` — the documented "finish it" path — so it clears
    the still-running guard, which is exactly the race the lock closes: the second
    process's check can read ``state.json`` before the first one writes it.
    """
    control, worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    holder_stages = _BlockingStages(entered, release)
    monkeypatch.setattr(implement_workflow, "run_stage", holder_stages)
    roots = _roots(control)

    holder, outcome = _start_run(task_prompt_path=prompt, **roots, approve_all=True)
    assert entered.wait(timeout=60), "the holding run never reached a stage"

    refused = implement_workflow.run(
        task_prompt_path=prompt, resume=True, approve_all=True, **roots
    )

    release.set()
    holder.join(timeout=60)
    assert not holder.is_alive()
    assert "error" not in outcome, outcome.get("error")

    assert refused == 4
    assert outcome["code"] == 0
    # Exactly one run directory: the refused run wrote nothing, including no run state.
    assert len(list(_runs_root(control).iterdir())) == 1
    err = capsys.readouterr().err
    assert "another aidw run is already active" in err
    assert str(worktree) in err


def test_two_concurrent_runs_in_different_worktrees_both_proceed(
    tmp_path: Path, monkeypatch
) -> None:
    """Two runs in different worktrees proceed (the roadmap's E2.7 "done when")."""
    control, first, first_prompt, second, second_prompt = _two_task_worktrees(tmp_path)
    _patch(monkeypatch)
    entered = {first: threading.Event(), second: threading.Event()}
    release = threading.Event()

    class _PerWorktreeStages(_Recorder):
        def __call__(self, spec, **kwargs):
            path = kwargs["repo_root"]
            entered.setdefault(path, threading.Event()).set()
            assert release.wait(timeout=60), "the runs were never released"
            return super().__call__(spec, **kwargs)

    monkeypatch.setattr(implement_workflow, "run_stage", _PerWorktreeStages())
    roots = _roots(control)

    first_thread, first_outcome = _start_run(
        task_prompt_path=first_prompt, **roots, approve_all=True
    )
    second_thread, second_outcome = _start_run(
        task_prompt_path=second_prompt, **roots, approve_all=True
    )
    # Both reached a stage while the other is still running: neither was refused.
    assert entered[first].wait(timeout=60) and entered[second].wait(timeout=60)
    release.set()
    first_thread.join(timeout=60)
    second_thread.join(timeout=60)
    assert not first_thread.is_alive() and not second_thread.is_alive()

    assert first_outcome.get("code") == 0, first_outcome.get("error")
    assert second_outcome.get("code") == 0, second_outcome.get("error")
    runs = list(_runs_root(control).iterdir())
    assert len(runs) == 2
    assert {state.repo_root for state in implement_workflow.list_runs(_runs_root(control))} == {
        str(first),
        str(second),
    }


def test_a_held_worktree_lock_is_refused_before_any_run_state(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The key is the *located* worktree, and the refusal precedes ``create_run``."""
    control, worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)
    roots = _roots(control)

    with lock.acquire(roots["workspace"].state_root, worktree):
        code = implement_workflow.run(task_prompt_path=prompt, **roots, approve_all=True)

    assert code == 4
    assert recorder.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []
    err = capsys.readouterr().err
    assert "another aidw run is already active" in err
    assert str(worktree) in err


def test_the_dry_run_takes_the_same_worktree_lock(tmp_path: Path, monkeypatch) -> None:
    """A dry run reaches ``create_run``, so it holds and releases the same key."""
    control, worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(implement_workflow, "run_stage", _Recorder())
    roots = _roots(control)

    with lock.acquire(roots["workspace"].state_root, worktree):
        code = implement_workflow.run(
            task_prompt_path=prompt, **roots, dry_run=True
        )

    assert code == 4

    # And a dry run that does acquire releases it: the key is free afterwards.
    assert implement_workflow.run(task_prompt_path=prompt, **roots, dry_run=True) == 0
    with lock.acquire(roots["workspace"].state_root, worktree):
        pass


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [("success", 0), ("stage-failure", 1), ("gate-denied", 3)],
)
def test_the_worktree_lock_is_released_on_every_exit_path(
    tmp_path: Path, monkeypatch, scenario: str, expected: int
) -> None:
    control, worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    failures = {"test"} if scenario == "stage-failure" else set()
    monkeypatch.setattr(implement_workflow, "run_stage", _Recorder(fail=failures))
    roots = _roots(control)
    # ``gate-denied`` is the no-``--yes``, non-interactive default: the gate fails closed
    # *after* the run exists, which is the mid-run refusal that must still release.
    approve_all = scenario != "gate-denied"

    code = implement_workflow.run(
        task_prompt_path=prompt, **roots, approve_all=approve_all
    )

    assert code == expected
    with lock.acquire(roots["workspace"].state_root, worktree):
        pass


# --------------------------------------------------------------------------- #
# core vs repo-optional preflight (E4.5a, D12/D13, EXTRACTION.md §3.5)
# --------------------------------------------------------------------------- #

#: The registry's implement order (R6 ids, §3.5's inventory table).
IMPLEMENT_STAGE_IDS = ("I1", "I2", "I3", "I4", "I5", "I6")


def _declared_implement_stages(disabled: set[str] | None = None) -> str:
    """A declared implement list carrying every id, optionally disabling some of them.

    The full list is not optional: §3.4's declared list **replaces** the toolkit's
    wholesale, so a minimal list would trip E4.5a's removal rule instead of the rule a
    test is about.
    """
    disabled = disabled or set()
    lines = ["schema_version: 1", "workflows:", "  implement:", "    stages:"]
    for stage_id in IMPLEMENT_STAGE_IDS:
        lines.append(f"      - id: {stage_id}")
        if stage_id in disabled:
            lines.append("        enabled: false")
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("dry_run", [False, True])
def test_a_disabled_core_stage_is_refused_before_any_side_effect(
    tmp_path: Path, monkeypatch, capsys, dry_run: bool
) -> None:
    """D12/D13: I5 (record-results) is core, so ``enabled: false`` is a config refusal."""
    control, prompt = _layout(tmp_path)
    _write_config(control, _declared_implement_stages({"I5"}))
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)
    roots = _roots(control)

    code = implement_workflow.run(
        task_prompt_path=prompt, **roots, dry_run=dry_run
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "workflows.implement.stages" in err
    assert "I5" in err
    assert "core stage cannot be disabled" in err
    # Before any stage, run record or worktree — `--dry-run` included.
    assert recorder.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []
    assert not (roots["workspace"].workspace_root / "03-E4.1").exists()


def test_a_disabled_repo_optional_stage_passes_the_preflight(
    tmp_path: Path, monkeypatch
) -> None:
    """D13/E4.5b: I3 (traceability) is repo-optional, and disabling it means omitting it."""
    control, prompt = _layout(tmp_path)
    _write_config(control, _declared_implement_stages({"I3"}))
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 0
    # E4.5b req 2: `enabled: false` is honoured by omission, never warned about.
    assert recorder.names == [
        name for name in DEFAULT_ORDER if name != "update-traceability"
    ]


# --------------------------------------------------------------------------- #
# repo-added stages in the plan and the schedule (E4.5b req 1/req 8)
# --------------------------------------------------------------------------- #

#: The declared `prompt:` of a repo-added implement stage, relative to the target root.
REPO_ADDED_PROMPT = "aidw/prompts/repo-added.md"


def _declared_stages(entries: list[dict[str, object]]) -> str:
    """``aidw/config.yaml`` declaring ``workflows.implement.stages = entries``."""
    lines = ["schema_version: 1", "workflows:", "  implement:", "    stages:"]
    for entry in entries:
        for index, (key, value) in enumerate(entry.items()):
            prefix = "      - " if index == 0 else "        "
            rendered = (
                ("true" if value else "false") if isinstance(value, bool) else str(value)
            )
            lines.append(f"{prefix}{key}: {rendered}")
    return "\n".join(lines) + "\n"


def _stages_with_repo_added(position: int) -> list[dict[str, object]]:
    """Every core/optional implement id in registry order, plus ``X9`` after ``position``."""
    entries: list[dict[str, object]] = [
        {"id": stage_id} for stage_id in IMPLEMENT_STAGE_IDS
    ]
    entries.insert(
        position, {"id": "X9", "agent": "implementer", "prompt": REPO_ADDED_PROMPT}
    )
    return entries


def _write_repo_added_prompt(*roots: Path) -> None:
    """Write the repo-added stage's prompt into each root.

    The preflight resolves it against the **control** root (that is the tree under check)
    while the plan resolves it against the located **worktree**, so a real-run test needs
    it in both — exactly as a committed repo prompt file is.
    """
    for root in roots:
        path = root / REPO_ADDED_PROMPT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# repo-added stage\n", encoding="utf-8")


#: Stand-in agent configs: `load_all` is faked, so only the ids matter — a repo-added
#: stage's declared `agent` is *existence*-checked against this dict (E4.5b req 4).
_AGENTS = {"implementer": object(), "tester": object(), "recorder": object()}


def _patch_with_agents(monkeypatch) -> None:
    """``_patch`` plus the agent configs a repo-added stage's declared ``agent`` needs."""
    _patch(monkeypatch)
    monkeypatch.setattr(
        implement_workflow, "load_all", lambda aidt, repo: (_AGENTS, [])
    )


def test_a_trailing_repo_added_stage_is_planned_after_i6(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 8: the pr split still targets I6; a trailing stage is not mistaken for it."""
    control, prompt = _layout(tmp_path)
    _write_config(control, _declared_stages(_stages_with_repo_added(len(IMPLEMENT_STAGE_IDS))))
    _write_repo_added_prompt(control)
    _patch_with_agents(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 0
    assert recorder.names == [*DEFAULT_ORDER, "X9"]
    out = capsys.readouterr().out
    # Both id and name are the declared id (§3.5: a repo-added stage declares no name).
    assert "X9 X9 [succeeded] (planned)" in out


def test_a_trailing_repo_added_stage_runs_after_i6(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 8: declared order — I6, then the trailing stage; the PR record stays on I6."""
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control, _declared_stages(_stages_with_repo_added(len(IMPLEMENT_STAGE_IDS)))
    )
    _write_repo_added_prompt(control, worktree)
    _patch_with_agents(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert recorder.names == [*DEFAULT_ORDER, "X9"]
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert state.status == SUCCEEDED
    # `_record_pr` read I6's output, not the trailing stage's.
    assert state.pr.get("number") == 42


def test_a_denied_gate_stops_before_a_trailing_repo_added_stage(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 8: a denied gate (exit 3) stops before anything declared after I6 runs."""
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control, _declared_stages(_stages_with_repo_added(len(IMPLEMENT_STAGE_IDS)))
    )
    _write_repo_added_prompt(control, worktree)
    _patch_with_agents(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    # No --yes and a non-interactive session: the gate fails closed.
    code = implement_workflow.run(task_prompt_path=prompt, **_roots(control))

    assert code == 3
    assert "pr" not in recorder.names
    assert "X9" not in recorder.names


def test_a_failed_i6_stops_before_a_trailing_repo_added_stage(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 8: a failed I6 (exit 1) stops too, exactly as without a trailing stage."""
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control, _declared_stages(_stages_with_repo_added(len(IMPLEMENT_STAGE_IDS)))
    )
    _write_repo_added_prompt(control, worktree)
    _patch_with_agents(monkeypatch)
    monkeypatch.setattr(
        implement_workflow, "run_stage", _Recorder(fail={"pr"})
    )

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 1


def test_a_repo_added_stage_before_i6_is_scheduled_in_declared_order(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 8: a pre-I6 repo-added stage runs at its full-plan position, serially."""
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(control, _declared_stages(_stages_with_repo_added(2)))
    _write_repo_added_prompt(control, worktree)
    _patch_with_agents(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert recorder.names == [
        "impliment-task",
        "test",
        "X9",
        "update-traceability",
        "update-architecture",
        "record-implementation-results",
        "pr",
    ]


def test_a_repo_added_stage_before_i6_is_scheduled_in_parallel_mode(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 8: ``--parallel`` covers the repo-added stage at its full-plan position."""
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(control, _declared_stages(_stages_with_repo_added(2)))
    _write_repo_added_prompt(control, worktree)
    _patch_with_agents(monkeypatch)
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
    # The default pair overlaps at I2's position; X9 keeps its declared slot after them.
    assert set(recorder.names[:3]) == {"impliment-task", "test", "update-architecture"}
    assert recorder.names[3:] == [
        "X9",
        "update-traceability",
        "record-implementation-results",
        "pr",
    ]


def test_a_repo_added_stage_before_i6_skips_on_resume(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 8: resume skips it exactly as a core stage that already succeeded."""
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(control, _declared_stages(_stages_with_repo_added(2)))
    _write_repo_added_prompt(control, worktree)
    _patch_with_agents(monkeypatch)
    runs_dir = _runs_root(control)
    state = create_run(
        runs_dir, control, "implement", label="03-E4.1", branch="03-E4.1"
    )
    directory = run_dir(runs_dir, state.run_id)
    for name in ("impliment-task", "X9"):
        state.record_stage(
            StageRecord(name=name, agent="implementer", model="m", status=SUCCEEDED)
        )
    save(directory, state)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), resume=True, approve_all=True
    )

    assert code == 0
    assert recorder.names[0] == "test"
    assert "X9" not in recorder.names
    assert "impliment-task" not in recorder.names


def test_from_a_disabled_repo_optional_stage_keeps_the_run_coherent(
    tmp_path: Path, monkeypatch
) -> None:
    """A ``--from`` naming a stage the declared list dropped must not crash the run.

    ``--from`` is validated against the registry names before the locate (it is a *name*
    check), so a repo-optional stage the repo disabled passes validation but is absent from
    the run-path plan. There is no position to re-run from, so every stage keeps its own
    succeeded-skip decision — never a ``StopIteration`` traceback out of ``run()``.
    """
    control, _worktree, prompt = _located_layout(tmp_path)
    _write_config(control, _declared_implement_stages({"I3"}))
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        from_stage="update-traceability",
        approve_all=True,
    )

    assert code == 0
    assert recorder.names == [
        name for name in DEFAULT_ORDER if name != "update-traceability"
    ]


def test_a_repo_added_stage_with_a_missing_prompt_is_refused(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 5: an unresolvable declared prompt is a config refusal, never a traceback."""
    control, prompt = _layout(tmp_path)
    _write_config(control, _declared_stages(_stages_with_repo_added(2)))
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "workflows.implement.stages" in err
    assert "`X9`" in err
    assert "prompt does not resolve" in err
    assert recorder.names == []


def test_a_repo_added_stage_with_an_unknown_agent_is_refused(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 4/req 5: an unknown declared ``agent`` refuses here, not in ``run_stage``."""
    control, prompt = _layout(tmp_path)
    entries = _stages_with_repo_added(2)
    entries[2] = {"id": "X9", "agent": "no-such-agent", "prompt": REPO_ADDED_PROMPT}
    _write_config(control, _declared_stages(entries))
    _write_repo_added_prompt(control)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "workflows.implement.stages" in err
    assert "`X9`" in err
    assert "unknown agent `no-such-agent`" in err
    assert recorder.names == []
