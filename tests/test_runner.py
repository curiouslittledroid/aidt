"""Tests for the stage runner (dry-run; no Pi invocation)."""

from __future__ import annotations

from pathlib import Path

from aidw.config import load_all
from aidw.log import RunLogger
from aidw.paths import aidt_root, repo_root
from aidw.pi import PiResult, Usage
from aidw import runner as runner_mod
from aidw.runner import StageSpec, resolve_prompt, run_stage
from aidw.state import FAILED, SUCCEEDED, create_run


def _noop_prompt() -> Path:
    return aidt_root() / "tests" / "fixtures" / "noop.md"


def test_resolve_prompt_by_name() -> None:
    assert resolve_prompt(aidt_root(), "code-review") == aidt_root() / "prompts" / "code-review.md"


def test_resolve_prompt_by_path() -> None:
    resolved = resolve_prompt(aidt_root(), str(_noop_prompt()))
    assert resolved == _noop_prompt()


def test_dry_run_writes_state_and_rendered_prompt(tmp_path: Path) -> None:
    agents, _ = load_all(aidt_root(), repo_root())
    run = create_run(tmp_path, repo_root(), "stage", label="dry")
    logger = RunLogger(tmp_path / run.run_id)

    record = run_stage(
        StageSpec(name="noop", agent_id="code-reviewer", prompt=_noop_prompt(), variables=[]),
        repo_root=repo_root(),
        aidt_root=aidt_root(),
        state=run,
        logger=logger,
        agents=agents,
        dry_run=True,
        runs_dir=tmp_path,
    )

    directory = tmp_path / run.run_id
    assert (directory / "state.json").is_file()
    assert (directory / "prompts" / "noop.rendered.md").is_file()
    assert record.status == SUCCEEDED
    assert record.exit_code is None
    assert run.status == SUCCEEDED


def test_dry_run_renders_variables(tmp_path: Path) -> None:
    agents, _ = load_all(aidt_root(), repo_root())
    run = create_run(tmp_path, repo_root(), "stage", label="dry")
    logger = RunLogger(tmp_path / run.run_id)

    run_stage(
        StageSpec(
            name="task-prompt",
            agent_id="task-author",
            prompt=aidt_root() / "prompts" / "task-prompt.md",
            variables=["03", "E2", "E2.9"],
        ),
        repo_root=repo_root(),
        aidt_root=aidt_root(),
        state=run,
        logger=logger,
        agents=agents,
        dry_run=True,
        runs_dir=tmp_path,
    )
    rendered = (tmp_path / run.run_id / "prompts" / "task-prompt.rendered.md").read_text()
    assert "$1" not in rendered
    assert "$3" not in rendered


def test_dry_run_records_session_policy(tmp_path: Path) -> None:
    agents, _ = load_all(aidt_root(), repo_root())
    run = create_run(tmp_path, repo_root(), "stage", label="dry")
    logger = RunLogger(tmp_path / run.run_id)

    record = run_stage(
        StageSpec(name="impliment-task", agent_id="implementer", prompt=_noop_prompt(), variables=[]),
        repo_root=repo_root(),
        aidt_root=aidt_root(),
        state=run,
        logger=logger,
        agents=agents,
        dry_run=True,
        runs_dir=tmp_path,
    )
    # implementer's session policy is shared: no stage suffix.
    assert record.session_id == f"aidw-{run.run_id}-implementer"


def _result(cost_usd: float) -> PiResult:
    return PiResult(
        exit_code=0,
        session_id="s",
        final_message="ok",
        usage=Usage(cost_usd=cost_usd),
        duration_seconds=0.1,
        event_count=1,
        tool_calls=0,
        tool_errors=0,
        stop_reason="end_turn",
        stderr="",
        timed_out=False,
        attempts=1,
        jsonl_path="",
        out_path=None,
    )


def test_cost_ceiling_fails_a_stage(tmp_path: Path, monkeypatch) -> None:
    agents, _ = load_all(aidt_root(), repo_root())
    agents["code-reviewer"].max_cost_usd = 0.01
    monkeypatch.setattr(runner_mod, "execute", lambda *args, **kwargs: _result(0.50))

    run = create_run(tmp_path, repo_root(), "stage", label="cost")
    logger = RunLogger(tmp_path / run.run_id)
    record = run_stage(
        StageSpec(name="noop", agent_id="code-reviewer", prompt=_noop_prompt(), variables=[]),
        repo_root=repo_root(),
        aidt_root=aidt_root(),
        state=run,
        logger=logger,
        agents=agents,
        runs_dir=tmp_path,
    )

    assert record.status == FAILED
    assert record.error is not None and "cost_ceiling" in record.error
    assert run.status == FAILED


def test_under_cost_ceiling_succeeds(tmp_path: Path, monkeypatch) -> None:
    agents, _ = load_all(aidt_root(), repo_root())
    agents["code-reviewer"].max_cost_usd = 1.00
    monkeypatch.setattr(runner_mod, "execute", lambda *args, **kwargs: _result(0.50))

    run = create_run(tmp_path, repo_root(), "stage", label="cost")
    logger = RunLogger(tmp_path / run.run_id)
    record = run_stage(
        StageSpec(name="noop", agent_id="code-reviewer", prompt=_noop_prompt(), variables=[]),
        repo_root=repo_root(),
        aidt_root=aidt_root(),
        state=run,
        logger=logger,
        agents=agents,
        runs_dir=tmp_path,
    )

    assert record.status == SUCCEEDED
