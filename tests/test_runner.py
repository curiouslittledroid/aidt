"""Tests for the stage runner (dry-run; no Pi invocation)."""

from __future__ import annotations

from pathlib import Path

from aidw.config import load_all
from aidw.log import RunLogger
from aidw.paths import (
    RUN_ID_ENV_VAR,
    SCRIPTS_DIR_ENV_VAR,
    STAGE_ENV_VAR,
    toolkit_root,
    repo_root,
)
from aidw.pi import PiResult, Usage
from aidw import runner as runner_mod
from aidw.runner import StageSpec, resolve_prompt, run_stage
from aidw.state import FAILED, SUCCEEDED, create_run


def _noop_prompt() -> Path:
    return toolkit_root() / "tests" / "fixtures" / "noop.md"


def test_resolve_prompt_by_name() -> None:
    assert resolve_prompt(toolkit_root(), "code-review") == toolkit_root() / "prompts" / "code-review.md"


def test_resolve_prompt_by_path() -> None:
    resolved = resolve_prompt(toolkit_root(), str(_noop_prompt()))
    assert resolved == _noop_prompt()


def test_dry_run_writes_state_and_rendered_prompt(tmp_path: Path) -> None:
    agents, _ = load_all(toolkit_root(), repo_root())
    run = create_run(tmp_path, repo_root(), "stage", label="dry")
    logger = RunLogger(tmp_path / run.run_id)

    record = run_stage(
        StageSpec(name="noop", agent_id="code-reviewer", prompt=_noop_prompt(), variables=[]),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        dry_run=True,
        runs_root=tmp_path,
    )

    directory = tmp_path / run.run_id
    assert (directory / "state.json").is_file()
    assert (directory / "prompts" / "noop.rendered.md").is_file()
    assert record.status == SUCCEEDED
    assert record.exit_code is None
    assert run.status == SUCCEEDED


def test_run_stage_writes_under_the_threaded_runs_root(tmp_path: Path) -> None:
    """``state.json`` and ``prompts/`` are siblings under the caller's ``runs_root``.

    The toolkit-root fallback was deleted in E1.4: ``run_stage`` must not re-derive a
    write directory, or the run would split across two locations.
    """
    agents, _ = load_all(toolkit_root(), repo_root())
    run = create_run(tmp_path, repo_root(), "stage", label="threaded")
    logger = RunLogger(tmp_path / run.run_id)

    run_stage(
        StageSpec(name="noop", agent_id="code-reviewer", prompt=_noop_prompt(), variables=[]),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        dry_run=True,
        runs_root=tmp_path,
    )

    directory = tmp_path / run.run_id
    assert (directory / "state.json").is_file()
    assert (directory / "prompts" / "noop.rendered.md").is_file()
    assert not (toolkit_root() / "runs" / run.run_id).exists()


def test_dry_run_renders_variables(tmp_path: Path) -> None:
    agents, _ = load_all(toolkit_root(), repo_root())
    run = create_run(tmp_path, repo_root(), "stage", label="dry")
    logger = RunLogger(tmp_path / run.run_id)

    run_stage(
        StageSpec(
            name="task-prompt",
            agent_id="task-author",
            prompt=toolkit_root() / "prompts" / "task-prompt.md",
            variables=["03", "E2", "E2.9"],
        ),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        dry_run=True,
        runs_root=tmp_path,
    )
    rendered = (tmp_path / run.run_id / "prompts" / "task-prompt.rendered.md").read_text()
    assert "$1" not in rendered
    assert "$3" not in rendered


def test_dry_run_records_session_policy(tmp_path: Path) -> None:
    agents, _ = load_all(toolkit_root(), repo_root())
    run = create_run(tmp_path, repo_root(), "stage", label="dry")
    logger = RunLogger(tmp_path / run.run_id)

    record = run_stage(
        StageSpec(name="impliment-task", agent_id="implementer", prompt=_noop_prompt(), variables=[]),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        dry_run=True,
        runs_root=tmp_path,
    )
    # implementer's session policy is shared: no stage suffix.
    assert record.session_id == f"aidw-{run.run_id}-implementer"


def test_stage_env_exposes_the_toolkit_scripts_dir(
    tmp_path: Path, monkeypatch
) -> None:
    """Prompts resolve the bundled scripts through an absolute, cwd-independent path.

    Regression: the review-followup prompts used to invoke
    ``python3 aidt/prompts/scripts/...``, which resolved inside the *target* repo and
    failed whenever the toolkit lived in its own checkout (EXTRACTION.md §3.6).
    """
    agents, _ = load_all(toolkit_root(), repo_root())
    captured: dict = {}

    def _capture(argv, prompt, **kwargs):
        captured.update(kwargs)
        return _result(0.0)

    monkeypatch.setattr(runner_mod, "execute", _capture)
    run = create_run(tmp_path, repo_root(), "stage", label="env")
    logger = RunLogger(tmp_path / run.run_id)

    run_stage(
        StageSpec(name="noop", agent_id="code-reviewer", prompt=_noop_prompt(), variables=[]),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        runs_root=tmp_path,
    )

    scripts_dir = captured["env"][SCRIPTS_DIR_ENV_VAR]
    assert scripts_dir == str(toolkit_root() / "prompts" / "scripts")
    assert Path(scripts_dir).is_absolute()
    assert (Path(scripts_dir) / "review-followup" / "review_followup.py").is_file()


def test_stage_env_exposes_the_run_and_stage_identity(
    tmp_path: Path, monkeypatch
) -> None:
    """A gate the agent runs records into the run and stage that produced it (E4.8).

    ``aidw gate run`` is executed by the agent's own shell, not by the runner, so the
    identity cannot travel in the prompt: it travels in the environment the stage inherits.
    """
    agents, _ = load_all(toolkit_root(), repo_root())
    captured: dict = {}

    def _capture(argv, prompt, **kwargs):
        captured.update(kwargs)
        return _result(0.0)

    monkeypatch.setattr(runner_mod, "execute", _capture)
    run = create_run(tmp_path, repo_root(), "stage", label="identity")
    logger = RunLogger(tmp_path / run.run_id)

    run_stage(
        StageSpec(name="noop", agent_id="code-reviewer", prompt=_noop_prompt(), variables=[]),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        runs_root=tmp_path,
    )

    assert captured["env"][RUN_ID_ENV_VAR] == run.run_id
    assert captured["env"][STAGE_ENV_VAR] == "noop"


def test_agent_env_cannot_shadow_the_run_identity(tmp_path: Path, monkeypatch) -> None:
    """An agent's ``env:`` must not be able to point gates at another run."""
    agents, _ = load_all(toolkit_root(), repo_root())
    agents["code-reviewer"].env[RUN_ID_ENV_VAR] = "someone-elses-run"
    agents["code-reviewer"].env[STAGE_ENV_VAR] = "someone-elses-stage"
    captured: dict = {}

    def _capture(argv, prompt, **kwargs):
        captured.update(kwargs)
        return _result(0.0)

    monkeypatch.setattr(runner_mod, "execute", _capture)
    run = create_run(tmp_path, repo_root(), "stage", label="identity-shadow")
    logger = RunLogger(tmp_path / run.run_id)

    run_stage(
        StageSpec(name="noop", agent_id="code-reviewer", prompt=_noop_prompt(), variables=[]),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        runs_root=tmp_path,
    )

    assert captured["env"][RUN_ID_ENV_VAR] == run.run_id
    assert captured["env"][STAGE_ENV_VAR] == "noop"


def test_agent_env_cannot_shadow_the_toolkit_scripts_dir(
    tmp_path: Path, monkeypatch
) -> None:
    agents, _ = load_all(toolkit_root(), repo_root())
    agents["code-reviewer"].env[SCRIPTS_DIR_ENV_VAR] = "/tmp/not-the-toolkit"
    captured: dict = {}

    def _capture(argv, prompt, **kwargs):
        captured.update(kwargs)
        return _result(0.0)

    monkeypatch.setattr(runner_mod, "execute", _capture)
    run = create_run(tmp_path, repo_root(), "stage", label="env-shadow")
    logger = RunLogger(tmp_path / run.run_id)

    run_stage(
        StageSpec(name="noop", agent_id="code-reviewer", prompt=_noop_prompt(), variables=[]),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        runs_root=tmp_path,
    )

    assert captured["env"][SCRIPTS_DIR_ENV_VAR] == str(toolkit_root() / "prompts" / "scripts")


def _result(cost_usd: float, *, tokens: int = 0) -> PiResult:
    return PiResult(
        exit_code=0,
        session_id="s",
        final_message="ok",
        usage=Usage(cost_usd=cost_usd, total_tokens=tokens),
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


def _run_with_result(tmp_path: Path, monkeypatch, result: PiResult):
    agents, _ = load_all(toolkit_root(), repo_root())
    monkeypatch.setattr(runner_mod, "execute", lambda *args, **kwargs: result)
    run = create_run(tmp_path, repo_root(), "stage", label="cost")
    logger = RunLogger(tmp_path / run.run_id)
    record = run_stage(
        StageSpec(name="noop", agent_id="code-reviewer", prompt=_noop_prompt(), variables=[]),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        runs_root=tmp_path,
    )
    return record, (tmp_path / run.run_id / "run.log").read_text()


def test_unpriced_stage_warns_in_the_run_log(tmp_path: Path, monkeypatch) -> None:
    record, log = _run_with_result(tmp_path, monkeypatch, _result(0.0, tokens=935952))

    assert record.status == SUCCEEDED
    assert "[WARN] stage noop: 936.0k tokens with $0.0000 cost" in log
    assert "has no pricing" in log


def test_priced_stage_logs_no_warning(tmp_path: Path, monkeypatch) -> None:
    record, log = _run_with_result(tmp_path, monkeypatch, _result(0.28, tokens=935952))

    assert record.status == SUCCEEDED
    assert "WARN" not in log


def _run_with_verify(tmp_path: Path, monkeypatch, verify, *, dry_run: bool = False):
    agents, _ = load_all(toolkit_root(), repo_root())
    monkeypatch.setattr(runner_mod, "execute", lambda *args, **kwargs: _result(0.10))
    run = create_run(tmp_path, repo_root(), "stage", label="verify")
    logger = RunLogger(tmp_path / run.run_id)
    record = run_stage(
        StageSpec(
            name="noop",
            agent_id="code-reviewer",
            prompt=_noop_prompt(),
            variables=[],
            verify=verify,
        ),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        dry_run=dry_run,
        runs_root=tmp_path,
    )
    return record, run, (tmp_path / run.run_id / "run.log").read_text()


def test_postcondition_that_holds_keeps_the_stage_succeeded(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[int] = []

    record, run, _ = _run_with_verify(tmp_path, monkeypatch, lambda: calls.append(1) or None)

    assert calls == [1]
    assert record.status == SUCCEEDED
    assert record.error is None


def test_unmet_postcondition_fails_the_stage(tmp_path: Path, monkeypatch) -> None:
    """A zero exit from Pi is not evidence that the stage did its work (design §10)."""

    record, run, log = _run_with_verify(
        tmp_path, monkeypatch, lambda: "open children still awaiting approval: #5"
    )

    assert record.status == FAILED
    assert record.error == (
        "postcondition not met: open children still awaiting approval: #5"
    )
    assert run.status == FAILED
    assert run.resume == {"next_stage": "noop"}
    assert "postcondition not met" in log


def test_postcondition_that_raises_fails_the_stage(tmp_path: Path, monkeypatch) -> None:
    def boom() -> str | None:
        raise RuntimeError("gh exploded")

    record, run, _ = _run_with_verify(tmp_path, monkeypatch, boom)

    assert record.status == FAILED
    assert record.error is not None
    assert "check raised RuntimeError: gh exploded" in record.error
    assert run.status == FAILED


def test_postcondition_is_not_checked_on_a_dry_run(tmp_path: Path, monkeypatch) -> None:
    calls: list[int] = []

    record, run, _ = _run_with_verify(
        tmp_path, monkeypatch, lambda: calls.append(1) or None, dry_run=True
    )

    assert calls == []
    assert record.status == SUCCEEDED


def test_cost_ceiling_fails_a_stage(tmp_path: Path, monkeypatch) -> None:
    agents, _ = load_all(toolkit_root(), repo_root())
    agents["code-reviewer"].max_cost_usd = 0.01
    monkeypatch.setattr(runner_mod, "execute", lambda *args, **kwargs: _result(0.50))

    run = create_run(tmp_path, repo_root(), "stage", label="cost")
    logger = RunLogger(tmp_path / run.run_id)
    record = run_stage(
        StageSpec(name="noop", agent_id="code-reviewer", prompt=_noop_prompt(), variables=[]),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        runs_root=tmp_path,
    )

    assert record.status == FAILED
    assert record.error is not None and "cost_ceiling" in record.error
    assert run.status == FAILED


def test_under_cost_ceiling_succeeds(tmp_path: Path, monkeypatch) -> None:
    agents, _ = load_all(toolkit_root(), repo_root())
    agents["code-reviewer"].max_cost_usd = 1.00
    monkeypatch.setattr(runner_mod, "execute", lambda *args, **kwargs: _result(0.50))

    run = create_run(tmp_path, repo_root(), "stage", label="cost")
    logger = RunLogger(tmp_path / run.run_id)
    record = run_stage(
        StageSpec(name="noop", agent_id="code-reviewer", prompt=_noop_prompt(), variables=[]),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        runs_root=tmp_path,
    )

    assert record.status == SUCCEEDED


def test_stage_record_carries_generation_speed(tmp_path: Path, monkeypatch) -> None:
    """The runner copies the stream-derived rate onto the record that state.json keeps."""
    result = _result(0.01, tokens=100)
    result.usage.output_tokens = 100
    result.generation_seconds = 2.0
    result.tool_seconds = 7.5
    result.tool_breakdown = {"read": 7.5}

    record, _log = _run_with_result(tmp_path, monkeypatch, result)

    assert record.generation_seconds == 2.0
    assert record.tool_seconds == 7.5
    assert record.tool_breakdown == {"read": 7.5}
    assert record.output_tokens_per_second == 50.0
