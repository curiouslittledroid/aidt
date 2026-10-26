"""Stage runner: the primitive that executes one agent stage (design §4, §8).

A stage is one Pi invocation with one prompt and one agent. Workflows orchestrate
stages; this module performs the mechanics: resolve the prompt, render variables,
compute the session id, run Pi, and record the stage in run state.

``aidw exec`` exposes it directly for manual/dry-run use and for Phase 2 validation.
"""

from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from aidw.agents import build_argv, build_env
from aidw.config import AgentConfig, load_all
from aidw.log import RunLogger
from aidw.pi import PiResult, execute, write_meta
from aidw.paths import SCRIPTS_DIR_ENV_VAR
from aidw.progress import ProgressIndicator, resolve_enabled
from aidw.prompts import render_prompt_file
from aidw.report import cost_note
from aidw.state import (
    FAILED,
    PLANNED,
    RUNNING,
    SUCCEEDED,
    RunState,
    StageRecord,
    run_dir,
    save,
    session_id,
    utcnow_iso,
)


@dataclass
class StageSpec:
    name: str
    agent_id: str
    prompt: Path
    variables: list[str]
    workflow: str = "stage"
    extra: str = ""
    #: Optional postcondition, checked after Pi reports success. It must re-read the
    #: external state the stage was supposed to change and return a human-readable
    #: error when that state is wrong (``None`` when the stage's contract holds). A
    #: zero exit from the agent is not evidence that the work happened: an agent can
    #: stop and report a problem in its final message while still exiting 0, so the
    #: stage is marked ``failed`` whenever the check does not pass (design §10).
    verify: Callable[[], str | None] | None = None


#: Retry a clearly transient Pi invocation error once (design E6, §10). ``aidw
#: --no-retry-transient`` flips this for the whole process.
DEFAULT_RETRY_TRANSIENT = True

#: Show ``.`` progress while Pi works (design §9.3). ``None`` means auto: on only when
#: stderr is an interactive terminal. ``aidw --progress`` / ``--no-progress`` overrides it
#: for the whole process.
DEFAULT_PROGRESS: bool | None = None

#: Serializes run-state mutations so two stages may execute concurrently (design
#: §8 ``--parallel``) without corrupting ``state.json``. Pi itself runs outside the
#: lock; only the short record/save sections are held.
_STATE_LOCK = threading.Lock()


def resolve_prompt(toolkit_root: Path, value: str) -> Path:
    """Resolve a prompt name (``code-review``) or path to a prompt file."""
    candidate = Path(value)
    if candidate.is_absolute() and candidate.is_file():
        return candidate
    if (candidate.parent != Path(".")) or candidate.suffix == ".md":
        if candidate.is_file():
            return candidate.resolve()

    name = value if value.endswith(".md") else f"{value}.md"
    return (toolkit_root / "prompts" / name).resolve()


def run_stage(
    spec: StageSpec,
    *,
    repo_root: Path,
    toolkit_root: Path,
    state: RunState,
    logger: RunLogger,
    agents: dict[str, AgentConfig] | None = None,
    dry_run: bool = False,
    retry_transient: bool | None = None,
    show_progress: bool | None = None,
    runs_root: Path,
) -> StageRecord:
    """Execute (or plan) one stage and persist its record in ``state``."""
    if retry_transient is None:
        retry_transient = DEFAULT_RETRY_TRANSIENT
    if show_progress is None:
        show_progress = DEFAULT_PROGRESS
    if agents is None:
        agents, issues = load_all(toolkit_root, repo_root)
        errors = [i for i in issues if i.level == "error"]
        if errors:
            raise ValueError(
                "agent config errors:\n" + "\n".join(str(i) for i in errors)
            )

    agent = agents.get(spec.agent_id)
    if agent is None:
        raise ValueError(f"unknown agent: {spec.agent_id}")

    if not spec.prompt.is_file():
        raise FileNotFoundError(f"prompt not found: {spec.prompt}")

    rendered = render_prompt_file(spec.prompt, spec.variables)
    if spec.extra:
        rendered = f"{rendered}\n\n{spec.extra}"
    directory = run_dir(runs_root, state.run_id)
    prompts_dir = directory / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    rendered_path = prompts_dir / f"{spec.name}.rendered.md"
    rendered_path.write_text(rendered, encoding="utf-8")

    sid = session_id(state.run_id, agent.id, spec.name, shared=agent.session == "shared")
    argv = build_argv(agent, session_id=sid)
    env = build_env(agent, dict(os.environ))
    # Prompts invoke the bundled helper scripts with `python3`; the subprocess working
    # directory is the *target* repo, where `aidt/prompts/scripts/...` does not exist
    # once the toolkit lives in its own checkout. Expose the absolute toolkit path
    # instead (EXTRACTION.md §3.6). Set after the agent's `env:` overrides so the
    # toolkit location cannot be shadowed by config.
    env[SCRIPTS_DIR_ENV_VAR] = str((Path(toolkit_root) / "prompts" / "scripts").resolve())

    record = StageRecord(
        name=spec.name,
        agent=agent.id,
        model=agent.qualified_model,
        status=PLANNED,
        session_id=sid,
        started_at=utcnow_iso(),
        rendered_prompt=str(rendered_path.relative_to(directory)),
        artifacts={"prompt_source": str(spec.prompt)},
    )
    with _STATE_LOCK:
        state.record_stage(record)
        save(directory, state)

    logger.section(f"stage {spec.name} ({agent.id})")
    logger.info(f"model={agent.qualified_model} session={sid}")
    logger.info(f"prompt={spec.prompt} vars={spec.variables}")

    if dry_run:
        logger.info("dry-run: not invoking Pi")
        logger.info("argv: " + _redact_argv(argv))
        record.status = SUCCEEDED
        record.ended_at = utcnow_iso()
        with _STATE_LOCK:
            state.status = SUCCEEDED
            save(directory, state)
        return record

    with _STATE_LOCK:
        record.status = RUNNING
        save(directory, state)

    stages_dir = directory / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)
    progress = ProgressIndicator(enabled=resolve_enabled(show_progress))
    progress.start(f"{spec.name} ({agent.id}) model={agent.qualified_model}")
    try:
        result: PiResult = execute(
            argv,
            rendered,
            env=env,
            cwd=agent.cwd,
            timeout=float(agent.timeout_seconds),
            stage_dir=stages_dir,
            stage_name=spec.name,
            logger=logger,
            retry_transient=retry_transient,
            progress=progress,
        )
    finally:
        progress.finish()
    write_meta(
        stages_dir / f"{spec.name}.meta.json",
        result,
        argv,
        model=agent.qualified_model,
        stage=spec.name,
        agent=agent.id,
        prompt_source=str(spec.prompt),
        rendered_prompt=record.rendered_prompt,
    )

    record.ended_at = utcnow_iso()
    record.exit_code = result.exit_code
    record.duration_seconds = result.duration_seconds
    record.cost_usd = result.usage.cost_usd
    record.usage = asdict(result.usage)
    record.log = f"stages/{spec.name}.jsonl"
    record.artifacts["out"] = result.out_path
    # A zero cost for real token spend is a pricing gap, not a free run: surface it in
    # run.log so it is caught during the run rather than in a later audit (design §9.2).
    unpriced = cost_note(record.model, record.usage)
    over_budget = (
        agent.max_cost_usd is not None
        and result.usage.cost_usd > agent.max_cost_usd
    )
    # Pi exiting 0 only means the agent finished, not that it did the work: it can
    # report a problem in its final message and still exit 0. When the stage declares a
    # postcondition, re-read the external state and fail the stage if it does not hold
    # (design §10). A check that raises fails the stage rather than crashing the run.
    verification_error: str | None = None
    if not result.failed and not over_budget and spec.verify is not None:
        try:
            verification_error = spec.verify() or None
        except Exception as exc:  # noqa: BLE001 - any check failure fails the stage
            verification_error = f"check raised {type(exc).__name__}: {exc}"
        if verification_error:
            logger.warn(
                f"stage {spec.name}: postcondition not met: {verification_error}"
            )
    with _STATE_LOCK:
        if result.failed:
            record.status = FAILED
            if result.timed_out:
                record.error = "timeout"
            elif result.error_message:
                record.error = f"provider error: {result.error_message[:200]}"
            else:
                record.error = f"exit code {result.exit_code}"
            state.resume = {"next_stage": spec.name}
            state.status = FAILED
        elif over_budget:
            record.status = FAILED
            record.error = (
                f"cost_ceiling: ${result.usage.cost_usd:.4f} > "
                f"${agent.max_cost_usd:.4f}"
            )
            state.resume = {"next_stage": spec.name}
            state.status = FAILED
        elif verification_error:
            record.status = FAILED
            record.error = f"postcondition not met: {verification_error}"
            state.resume = {"next_stage": spec.name}
            state.status = FAILED
        else:
            record.status = SUCCEEDED
        save(directory, state)
    if unpriced:
        logger.warn(f"stage {spec.name}: {unpriced}")
    return record


def _redact_argv(argv: list[str]) -> str:
    """Render argv for logs without dumping inlined system-prompt contents."""
    redacted: list[str] = []
    skip_next = False
    for index, item in enumerate(argv):
        if skip_next:
            redacted.append(f"<{len(item)} chars>")
            skip_next = False
            continue
        redacted.append(item)
        if item in ("--system-prompt", "--append-system-prompt"):
            skip_next = True
    return " ".join(redacted)
