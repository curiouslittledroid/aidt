"""Tests for the stage runner (dry-run; no Pi invocation)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from aidw.config import load_all
from aidw.github import serialize_github_config
from aidw.log import RunLogger
from aidw.paths import (
    REVIEW_FOLLOWUP_CONFIG_ENV_VAR,
    RUN_ID_ENV_VAR,
    SCRIPTS_DIR_ENV_VAR,
    STAGE_ENV_VAR,
    toolkit_root,
    repo_root,
)
from aidw.pi import AttemptDetail, PiResult, Usage
from aidw import runner as runner_mod
from aidw.prompts import render_prompt_file
from aidw.runner import StageSpec, declared_stage_issues, resolve_prompt, run_stage
from aidw.state import FAILED, SUCCEEDED, create_run, session_id


def _noop_prompt() -> Path:
    return toolkit_root() / "tests" / "fixtures" / "noop.md"


def test_resolve_prompt_by_name() -> None:
    # E4.2: the resolver is target-aware (precedence 2–3), so the target root is an
    # explicit argument. The toolkit repo has no ``aidw/prompts/`` shadow, so the
    # toolkit default is still what ``code-review`` names here.
    assert resolve_prompt(toolkit_root(), repo_root(), "code-review") == (
        toolkit_root() / "prompts" / "code-review.md"
    )


def test_resolve_prompt_by_path() -> None:
    # E4.2: a declared ``prompt:`` path is precedence 1 and is passed as a plain string;
    # an absolute one is used as-is rather than reinterpreted as a filename.
    resolved = resolve_prompt(
        toolkit_root(), repo_root(), "noop", str(_noop_prompt())
    )
    assert resolved == _noop_prompt()


def test_dry_run_does_not_persist_stage_state_or_rendered_prompt(tmp_path: Path) -> None:
    """W1.2: planning returns metadata without adding stage artifacts or saving state."""
    agents, _ = load_all(toolkit_root(), repo_root())
    run = create_run(tmp_path, repo_root(), "stage", label="dry")
    logger = RunLogger(tmp_path / run.run_id)
    directory = tmp_path / run.run_id
    before_state = (directory / "state.json").read_bytes()

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

    assert not (directory / "prompts" / "noop.rendered.md").exists()
    assert (directory / "state.json").read_bytes() == before_state
    # `state.record_stage` is in-memory and stays (W1.2 (c1)); it is the `save` that would
    # publish evidence for a stage that never ran, so the record is planned but unwritten.
    assert [item.name for item in run.stages] == ["noop"]
    assert b'"noop"' not in before_state
    assert record.name == "noop"
    assert record.agent == "code-reviewer"
    assert record.model
    # W1.2 req 3: the returned record keeps the shape the workflows print, session id
    # included — only the writes are suppressed.
    assert record.session_id == session_id(run.run_id, "code-reviewer", "noop", shared=False)
    assert record.status == SUCCEEDED
    assert record.exit_code is None
    assert run.status != SUCCEEDED


def test_run_stage_dry_run_does_not_recreate_a_toolkit_runs_tree(tmp_path: Path) -> None:
    """The caller's runs root remains the only possible artifact location."""
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
    assert not (directory / "prompts" / "noop.rendered.md").exists()
    assert not (toolkit_root() / "runs" / run.run_id).exists()


def test_dry_run_renders_variables(tmp_path: Path) -> None:
    agents, _ = load_all(toolkit_root(), repo_root())
    run = create_run(tmp_path, repo_root(), "stage", label="dry")
    logger = RunLogger(tmp_path / run.run_id)

    rendered = render_prompt_file(
        toolkit_root() / "prompts" / "task-prompt.md", ["03", "E2", "E2.9"]
    )
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


# --------------------------------------------------------------------------- #
# E4.6: per-stage model/thinking/timeout_seconds reach the effective agent
# --------------------------------------------------------------------------- #


def _dry_run(tmp_path: Path, spec: StageSpec):
    """Run one dry-run stage against the real agent configs; return record/log/agents."""
    agents, _ = load_all(toolkit_root(), repo_root())
    run = create_run(tmp_path, repo_root(), "stage", label="overrides")
    logger = RunLogger(tmp_path / run.run_id)
    record = run_stage(
        spec,
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        dry_run=True,
        runs_root=tmp_path,
    )
    return record, (tmp_path / run.run_id / "run.log").read_text(), agents


#: One hand-calculated vector per ``model`` spelling (E4.6 req 4). ``--model`` is the argv
#: slug and ``record.model`` is the *qualified* effective model: only a prefix matching the
#: agent's own ``provider`` (``openrouter`` for ``code-reviewer``) is stripped, so a bare
#: slug and a vendor-namespace slug both ride ``--provider openrouter`` whole.
MODEL_OVERRIDE_VECTORS = [
    pytest.param("muse-spark-2.0", "muse-spark-2.0", "openrouter/muse-spark-2.0", id="bare"),
    pytest.param(
        "deepseek/deepseek-v4.1-flash",
        "deepseek/deepseek-v4.1-flash",
        "openrouter/deepseek/deepseek-v4.1-flash",
        id="vendor-namespace",
    ),
    pytest.param(
        "openrouter/anthropic/claude-x",
        "anthropic/claude-x",
        "openrouter/anthropic/claude-x",
        id="own-provider-prefix",
    ),
]


@pytest.mark.parametrize(("override", "argv_model", "record_model"), MODEL_OVERRIDE_VECTORS)
def test_dry_run_argv_and_record_use_the_per_stage_model(
    tmp_path: Path, override: str, argv_model: str, record_model: str
) -> None:
    """Req 4/Done-when: the new model reaches the argv; the record keeps the qualified one."""
    record, log, agents = _dry_run(
        tmp_path,
        StageSpec(
            name="noop",
            agent_id="code-reviewer",
            prompt=_noop_prompt(),
            variables=[],
            model=override,
        ),
    )

    argv_line = next(line for line in log.splitlines() if "argv:" in line)
    assert "--provider openrouter" in argv_line
    assert f"--model {argv_model}" in argv_line
    # No doubled prefix and no provider switch; the record is the qualified effective model.
    assert f"--model openrouter/{argv_model}" not in argv_line
    assert record.model == record_model
    assert f"model={record_model}" in log
    # Purity: the loaded config another stage would use is untouched.
    assert agents["code-reviewer"].model == "openrouter/meta/muse-spark-1.3-contributor"


def test_an_un_overridden_stage_keeps_the_toolkit_model(tmp_path: Path) -> None:
    """Sibling check: the override is for that stage's invocation only."""
    agents, _ = load_all(toolkit_root(), repo_root())
    run = create_run(tmp_path, repo_root(), "stage", label="siblings")
    logger = RunLogger(tmp_path / run.run_id)

    def run_one(name: str, model: str | None) -> object:
        return run_stage(
            StageSpec(
                name=name,
                agent_id="code-reviewer",
                prompt=_noop_prompt(),
                variables=[],
                model=model,
            ),
            repo_root=repo_root(),
            toolkit_root=toolkit_root(),
            state=run,
            logger=logger,
            agents=agents,
            dry_run=True,
            runs_root=tmp_path,
        )

    overridden = run_one("overridden", "muse-spark-2.0")
    sibling = run_one("sibling", None)

    assert overridden.model == "openrouter/muse-spark-2.0"
    assert sibling.model == agents["code-reviewer"].qualified_model
    assert sibling.model == "openrouter/meta/muse-spark-1.3-contributor"
    log = (tmp_path / run.run_id / "run.log").read_text()
    assert "model=openrouter/meta/muse-spark-1.3-contributor" in log


def test_stage_thinking_and_timeout_override_the_effective_agent(
    tmp_path: Path, monkeypatch
) -> None:
    """``thinking`` reaches the argv and ``timeout_seconds`` reaches ``execute``."""
    agents, _ = load_all(toolkit_root(), repo_root())
    captured: dict = {}

    def _capture(argv, prompt, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return _result(0.0)

    monkeypatch.setattr(runner_mod, "execute", _capture)
    run = create_run(tmp_path, repo_root(), "stage", label="thinking")
    logger = RunLogger(tmp_path / run.run_id)

    record = run_stage(
        StageSpec(
            name="noop",
            agent_id="code-reviewer",
            prompt=_noop_prompt(),
            variables=[],
            thinking="low",
            timeout_seconds=42,
        ),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        runs_root=tmp_path,
    )

    argv = captured["argv"]
    assert argv[argv.index("--thinking") + 1] == "low"
    assert captured["timeout"] == 42.0
    # An un-overridden model still comes from the agent config.
    assert record.model == "openrouter/meta/muse-spark-1.3-contributor"


def test_state_meta_and_log_all_carry_the_effective_model(
    tmp_path: Path, monkeypatch
) -> None:
    """The trap: five consumers must read the same effective config, not just ``build_argv``."""
    import json

    agents, _ = load_all(toolkit_root(), repo_root())
    captured: dict = {}

    def _capture(argv, prompt, **kwargs):
        captured["argv"] = argv
        return _result(0.0)

    monkeypatch.setattr(runner_mod, "execute", _capture)
    run = create_run(tmp_path, repo_root(), "stage", label="effective")
    logger = RunLogger(tmp_path / run.run_id)

    record = run_stage(
        StageSpec(
            name="noop",
            agent_id="code-reviewer",
            prompt=_noop_prompt(),
            variables=[],
            model="openrouter/anthropic/claude-x",
        ),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        runs_root=tmp_path,
    )

    argv = captured["argv"]
    assert argv[argv.index("--model") + 1] == "anthropic/claude-x"
    assert record.model == "openrouter/anthropic/claude-x"
    directory = tmp_path / run.run_id
    meta = json.loads((directory / "stages" / "noop.meta.json").read_text())
    assert meta["model"] == "openrouter/anthropic/claude-x"
    assert (directory / "run.log").read_text().count(
        "model=openrouter/anthropic/claude-x"
    ) >= 1


# --------------------------------------------------------------------------- #
# E4.6: the preflight existence-checks a *known* stage's declared agent
# --------------------------------------------------------------------------- #


def test_declared_stage_issues_refuses_an_unknown_agent_on_a_known_stage(
    tmp_path: Path,
) -> None:
    """Req 3: no `ValueError: unknown agent` traceback may escape `run_stage`."""
    issues = declared_stage_issues(
        "implement",
        [{"id": "I1", "agent": "ghost"}],
        toolkit_root=toolkit_root(),
        target_root=tmp_path,
        agents={"implementer": object()},
    )

    assert any(
        "stage `I1`" in issue.message
        and "unknown agent `ghost`" in issue.message
        and issue.level == "error"
        for issue in issues
    ), issues


def test_declared_stage_issues_accepts_a_known_stage_agent(tmp_path: Path) -> None:
    """The same check passes for an agent the loaded configs define (E4.6 req 3)."""
    issues = declared_stage_issues(
        "implement",
        [{"id": "I1", "agent": "implementer"}],
        toolkit_root=toolkit_root(),
        target_root=tmp_path,
        agents={"implementer": object()},
    )

    assert issues == []


def test_global_override_then_per_stage_model_precedence(tmp_path: Path) -> None:
    """Req 5: per-stage > global override-dir shadow > toolkit, in the rendered argv.

    The override directory supplies an effective ``code-reviewer``; a stage that declares
    nothing uses it, and a stage that declares ``model`` wins over it. The toolkit's own
    ``agent-configs/`` remains the third layer (asserted by the un-shadowed value).
    """
    override = tmp_path / "target" / "aidw" / "agent-configs"
    override.mkdir(parents=True)
    (override / "code-reviewer.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "code-reviewer",
                "description": "override",
                "provider": "openrouter",
                "model": "vendor/global-override",
                "thinking": "minimal",
                "tools": ["read", "bash"],
                "session": "fresh",
                "timeout_seconds": 60,
            }
        ),
        encoding="utf-8",
    )
    agents, issues = load_all(toolkit_root(), repo_root(), override)
    assert [issue for issue in issues if issue.level == "error"] == []
    assert agents["code-reviewer"].qualified_model == "openrouter/vendor/global-override"

    run = create_run(tmp_path, repo_root(), "stage", label="precedence")
    logger = RunLogger(tmp_path / run.run_id)

    def run_one(name: str, model: str | None) -> object:
        return run_stage(
            StageSpec(
                name=name,
                agent_id="code-reviewer",
                prompt=_noop_prompt(),
                variables=[],
                model=model,
            ),
            repo_root=repo_root(),
            toolkit_root=toolkit_root(),
            state=run,
            logger=logger,
            agents=agents,
            dry_run=True,
            runs_root=tmp_path,
        )

    global_layer = run_one("global-layer", None)
    per_stage = run_one("per-stage", "vendor/stage-winner")
    toolkit_layer = load_all(toolkit_root(), repo_root())[0]["code-reviewer"]

    assert global_layer.model == "openrouter/vendor/global-override"
    assert per_stage.model == "openrouter/vendor/stage-winner"
    assert toolkit_layer.qualified_model == "openrouter/meta/muse-spark-1.3-contributor"
    log = (tmp_path / run.run_id / "run.log").read_text()
    assert "--model vendor/global-override" in log
    assert "--model vendor/stage-winner" in log


# ---------------------------------------------------------------------------
# E6.1: the resolved github.markers/github.labels reach the stage environment
# ---------------------------------------------------------------------------


def _declared_github_config():
    """A resolved config whose declared marker/label prove the wiring is not just defaults."""
    from aidw.target_config import (
        GitHubConfig,
        LabelConfig,
        MarkersConfig,
        TargetConfig,
        resolve_config,
    )

    return resolve_config(
        TargetConfig(
            schema_version=1,
            github=GitHubConfig(
                markers=MarkersConfig(parent="<!-- declared: pr={pr_url} -->"),
                labels={"must-fix": LabelConfig(color="111111", description="Declared")},
            ),
        )
    )


def _capture_stage_env(
    tmp_path: Path, monkeypatch, *, clear_handoff: bool = True, **stage_kwargs
) -> dict:
    agents, _ = load_all(toolkit_root(), repo_root())
    captured: dict = {}

    def _capture(argv, prompt, **kwargs):
        captured.update(kwargs)
        return _result(0.0)

    if clear_handoff:
        monkeypatch.delenv(REVIEW_FOLLOWUP_CONFIG_ENV_VAR, raising=False)
    monkeypatch.setattr(runner_mod, "execute", _capture)
    run = create_run(tmp_path, repo_root(), "stage", label="github-config")
    logger = RunLogger(tmp_path / run.run_id)

    run_stage(
        StageSpec(name="noop", agent_id="code-reviewer", prompt=_noop_prompt(), variables=[]),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        runs_root=tmp_path,
        **stage_kwargs,
    )
    return captured


def test_stage_env_carries_the_resolved_github_config(tmp_path: Path, monkeypatch) -> None:
    """Req 6(a): the agent-invoked scripts inherit the resolved markers/labels.

    The variable is set alongside ``AIDW_SCRIPTS_DIR`` and comes from the one serializer, so
    the publisher an agent runs and the ``select`` aidw runs cannot disagree about a marker
    (a disagreement reads as "No review-follow-up parent issue found").
    """
    import json

    config = _declared_github_config()

    captured = _capture_stage_env(tmp_path, monkeypatch, config=config)

    env = captured["env"]
    assert env[SCRIPTS_DIR_ENV_VAR].endswith("prompts/scripts")
    assert env[REVIEW_FOLLOWUP_CONFIG_ENV_VAR] == serialize_github_config(config)
    payload = json.loads(env[REVIEW_FOLLOWUP_CONFIG_ENV_VAR])
    # A declared override rides through, so the assertion cannot pass on defaults alone.
    assert payload["markers"]["parent"] == "<!-- declared: pr={pr_url} -->"
    assert payload["labels"]["must-fix"] == {"color": "111111", "description": "Declared"}
    assert set(payload["labels"]) == {
        "review-follow-up",
        "must-fix",
        "should-fix",
        "could-fix",
        "decision-pending",
        "approve-fix",
    }


def test_stage_env_leaves_the_variable_unset_without_a_config(
    tmp_path: Path, monkeypatch
) -> None:
    """``config=None`` keeps the scripts' frozen fallback: the variable is *absent*."""
    captured = _capture_stage_env(tmp_path, monkeypatch)

    assert REVIEW_FOLLOWUP_CONFIG_ENV_VAR not in captured["env"]
    assert SCRIPTS_DIR_ENV_VAR in captured["env"]


def test_stage_env_removes_a_stale_inherited_handoff_without_a_config(
    tmp_path: Path, monkeypatch
) -> None:
    """A stage without config must not inherit a handoff from its parent process."""
    monkeypatch.setenv(REVIEW_FOLLOWUP_CONFIG_ENV_VAR, '{"stale": true}')
    captured = _capture_stage_env(tmp_path, monkeypatch, clear_handoff=False)

    assert REVIEW_FOLLOWUP_CONFIG_ENV_VAR not in captured["env"]
    assert SCRIPTS_DIR_ENV_VAR in captured["env"]


# --------------------------------------------------------------------------- #
# H1.1: both attempts reach state.json + the stage meta; the final reason wins
# --------------------------------------------------------------------------- #


def _two_attempt_result() -> PiResult:
    """A truncation retry that answered: summed usage/timing, per-attempt detail."""
    first = AttemptDetail(
        attempt=1,
        session_id="aidw-run-base",
        exit_code=0,
        stop_reason="length",
        usage=Usage(
            input_tokens=10, output_tokens=7, cache_read=2, total_tokens=19, cost_usd=0.001
        ),
        generation_seconds=0.5,
        tool_seconds=0.25,
    )
    second = AttemptDetail(
        attempt=2,
        session_id="aidw-run-base-retry",
        exit_code=0,
        stop_reason="stop",
        usage=Usage(
            input_tokens=20, output_tokens=3, cache_read=4, total_tokens=27, cost_usd=0.002
        ),
        generation_seconds=1.5,
        tool_seconds=0.75,
    )
    return PiResult(
        exit_code=0,
        session_id="aidw-run-base-retry",
        final_message="the answer",
        usage=Usage(
            input_tokens=30,
            output_tokens=10,
            cache_read=6,
            total_tokens=46,
            cost_usd=0.003,
        ),
        duration_seconds=4.0,
        event_count=8,
        tool_calls=2,
        tool_errors=0,
        stop_reason="stop",
        stderr="",
        timed_out=False,
        attempts=2,
        jsonl_path="stages/noop.jsonl",
        out_path=None,
        generation_seconds=2.0,
        tool_seconds=1.0,
        tool_breakdown={"read": 1.0},
        attempts_detail=[first, second],
    )


def test_run_stage_records_the_final_stop_reason_and_attempt_count(
    tmp_path: Path, monkeypatch
) -> None:
    """`StageRecord.stop_reason` is the *final* attempt's and usage is the summed total."""
    record, _log = _run_with_result(tmp_path, monkeypatch, _two_attempt_result())

    assert record.status == SUCCEEDED
    assert record.attempts == 2
    assert record.stop_reason == "stop"  # the last attempts_detail entry, not "length"
    assert record.usage is not None
    assert record.usage["input_tokens"] == 30
    assert record.usage["output_tokens"] == 10
    assert record.usage["cost_usd"] == pytest.approx(0.003)
    assert record.cost_usd == pytest.approx(0.003)
    assert record.generation_seconds == 2.0
    assert record.tool_seconds == 1.0
    assert record.output_tokens_per_second == 5.0


def test_run_stage_meta_shows_one_entry_per_attempt(tmp_path: Path, monkeypatch) -> None:
    """The stage `.meta.json` keeps both attempts alongside the `attempts` count."""
    result = _two_attempt_result()
    run = create_run(tmp_path, repo_root(), "stage", label="retry-meta")
    agents, _ = load_all(toolkit_root(), repo_root())
    monkeypatch.setattr(runner_mod, "execute", lambda *args, **kwargs: result)
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

    meta = json.loads(
        (tmp_path / run.run_id / "stages" / "noop.meta.json").read_text(encoding="utf-8")
    )
    assert meta["attempts"] == 2
    detail = meta["attempts_detail"]
    assert len(detail) == 2
    assert [entry["session_id"] for entry in detail] == [
        "aidw-run-base",
        "aidw-run-base-retry",
    ]
    assert [entry["exit_code"] for entry in detail] == [0, 0]
    assert [entry["stop_reason"] for entry in detail] == ["length", "stop"]
    assert [entry["usage"]["cost_usd"] for entry in detail] == [0.001, 0.002]


def test_run_stage_cost_ceiling_sees_the_summed_two_attempt_cost(
    tmp_path: Path, monkeypatch
) -> None:
    """Both attempts' spend lands in `usage`, so the one existing ceiling check covers it."""
    agents, _ = load_all(toolkit_root(), repo_root())
    # Each attempt alone is under the ceiling; only the summed 0.003 exceeds it.
    agents["code-reviewer"].max_cost_usd = 0.0025
    monkeypatch.setattr(runner_mod, "execute", lambda *args, **kwargs: _two_attempt_result())

    run = create_run(tmp_path, repo_root(), "stage", label="retry-ceiling")
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
    assert record.error is not None and record.error.startswith("cost_ceiling:")


def test_run_stage_forwards_retry_transient_false(tmp_path: Path, monkeypatch) -> None:
    """`--no-retry-transient` reaches `execute`, so neither retry branch can fire."""
    captured: dict = {}

    def _capture(argv, prompt, **kwargs):
        captured.update(kwargs)
        return _result(0.0)

    monkeypatch.setattr(runner_mod, "execute", _capture)
    agents, _ = load_all(toolkit_root(), repo_root())
    run = create_run(tmp_path, repo_root(), "stage", label="no-retry")
    logger = RunLogger(tmp_path / run.run_id)

    run_stage(
        StageSpec(name="noop", agent_id="code-reviewer", prompt=_noop_prompt(), variables=[]),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        retry_transient=False,
        runs_root=tmp_path,
    )

    assert captured["retry_transient"] is False


# --------------------------------------------------------------------------- #
# The rendered prompt size on a review stage (H2.1 req 5)
# --------------------------------------------------------------------------- #
# ``run_stage`` renders and records *every* stage and also serves ``--dry-run``, so the
# record is scoped explicitly: only the ``prompt`` review loop's head stages
# (``task-review-<n>``, ``aidw.stage_registry.is_review_stage``) record ``rendered_chars``
# and print the ``run.log`` line, and only on the real-run path.


def _run_named_stage(tmp_path: Path, monkeypatch, name: str, *, dry_run: bool = False):
    """Run one stage named ``name`` with a faked Pi invocation; return (record, state, log)."""
    agents, _ = load_all(toolkit_root(), repo_root())
    monkeypatch.setattr(
        runner_mod,
        "execute",
        lambda *args, **kwargs: PiResult(
            exit_code=0,
            session_id="s",
            final_message="ok",
            usage=Usage(cost_usd=0.01, input_tokens=193, output_tokens=16),
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
        ),
    )
    run = create_run(tmp_path, repo_root(), "prompt", label="rendered-chars")
    logger = RunLogger(tmp_path / run.run_id)
    record = run_stage(
        StageSpec(
            name=name,
            agent_id="task-reviewer",
            prompt=_noop_prompt(),
            variables=[],
            extra="## Delta brief\n\nsome brief text\n",
        ),
        repo_root=repo_root(),
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        dry_run=dry_run,
        runs_root=tmp_path,
    )
    directory = tmp_path / run.run_id
    # W1.2: a dry run writes no rendered prompt, so the real-run cases read it back and
    # the dry-run case gets ``None`` (the file must not exist).
    rendered_path = directory / "prompts" / f"{name}.rendered.md"
    rendered = (
        rendered_path.read_text(encoding="utf-8") if rendered_path.is_file() else None
    )
    log = (directory / "run.log").read_text(encoding="utf-8")
    saved = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    return record, rendered, saved, log


def test_a_review_stage_records_the_rendered_prompt_size(
    tmp_path: Path, monkeypatch
) -> None:
    """H2.1 req 5: ``len(rendered)`` lands in the record beside ``usage.input_tokens``."""
    record, rendered, saved, log = _run_named_stage(tmp_path, monkeypatch, "task-review-2")

    assert record.rendered_chars == len(rendered)
    assert record.rendered_chars is not None and record.rendered_chars > 0
    # The state.json record carries the size and the tokens it should be read beside.
    stage = next(item for item in saved["stages"] if item["name"] == "task-review-2")
    assert stage["rendered_chars"] == len(rendered)
    assert stage["usage"]["input_tokens"] == 193
    # One run.log line, naming the stage and the size.
    line = f"stage task-review-2: rendered prompt {len(rendered)} chars"
    assert line in log
    assert log.count("rendered prompt") == 1


def test_author_and_fix_stages_do_not_record_the_rendered_size(
    tmp_path: Path, monkeypatch
) -> None:
    """H2.1 req 5: only review-loop heads record; author and fix stages record neither."""
    for name in ("task-prompt", "task-review-fixes-1-1", "task-review-reconcile-1"):
        record, rendered, saved, log = _run_named_stage(tmp_path, monkeypatch, name)
        assert rendered  # the stage really was rendered
        assert record.rendered_chars is None, name
        stage = next(item for item in saved["stages"] if item["name"] == name)
        # The additive field serialises as null — not omitted, not a number.
        assert stage["rendered_chars"] is None, name
        assert "rendered prompt" not in log, name


def test_the_dry_run_path_records_neither_the_size_nor_the_line(
    tmp_path: Path, monkeypatch
) -> None:
    """H2.1 req 4/5: a dry run of a review stage leaves the field null and logs no line.

    This is what keeps ``--dry-run`` output byte-identical to the pre-H2.1 plan: the
    record still gains the additive key (null), and nothing is printed.
    """
    record, rendered, saved, log = _run_named_stage(
        tmp_path, monkeypatch, "task-review-1", dry_run=True
    )

    assert record.status == SUCCEEDED
    assert record.rendered_chars is None
    # W1.2: the plan writes no rendered prompt and publishes no stage record at all, so
    # the additive key cannot appear in `state.json` either.
    assert rendered is None
    assert saved["stages"] == []
    assert "rendered prompt" not in log
