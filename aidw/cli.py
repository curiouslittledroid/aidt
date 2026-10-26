"""AIDW command-line interface.

Typer application that dispatches to the workflow groups plus inspection
commands. Phase 0 registers every command from the design's CLI reference so the
surface is stable; workflow bodies are implemented in later phases.

Design reference: ``aidt/design.md`` §14 (CLI reference), §16 (build plan).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from aidw import __version__, git, inventory, runner as runner_mod, state as state_mod
from aidw.config import ERROR, WARNING, format_issues, load_all
from aidw.doctor import run_doctor
from aidw.gates import GateDefault
from aidw.log import RunLogger
from aidw.paths import TargetRepo, WorkspacePaths, repo_root, toolkit_root
from aidw.roadmap import filter_tasks, find_task, load_tasks, next_todo
from aidw.report import rel_to, stage_lines, usage_line
from aidw.runner import StageSpec, resolve_prompt, run_stage
from aidw.workflows import approve as approve_workflow
from aidw.workflows import fix as fix_workflow
from aidw.workflows import implement as implement_workflow
from aidw.workflows import prompt as prompt_workflow
from aidw.workflows import review as review_workflow
from aidw.workflows import run as run_workflow

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="AIDT = AI Developer Tools. Pi-driven development workflows for Mythical Forge.",
)

# Exit codes (design §14).
EXIT_OK = 0
EXIT_STAGE_FAILURE = 1
EXIT_USAGE = 2
EXIT_BLOCKED = 3
EXIT_REFUSED = 4

# Populated by the top-level callback; read by commands.
_state: dict[str, object] = {"repo": None, "verbose": False}


def _roots() -> tuple[Path, Path]:
    """Resolve ``(target repo root, toolkit root)``.

    ``--repo`` selects the **target** repository only (E0.4). The toolkit root always
    comes from the installed package location, so no flag can point the toolkit at a
    checkout.
    """
    override = _state.get("repo")
    repo = Path(override) if override else repo_root()
    return repo, toolkit_root()


def _gate_default_value(value: Optional[GateDefault]) -> Optional[str]:
    """Narrow the CLI enum to the plain string the workflows thread to `decide`."""
    return value.value if value is not None else None


def _gate_default_option() -> Optional[GateDefault]:
    """Build a fresh OptionInfo per command; Click mutates these during decoration."""
    return typer.Option(
        None,
        "--gate-default",
        help=(
            "What Enter at an approval gate means: approve (the default) or deny. "
            "Env fallback: AIDW_GATE_DEFAULT."
        ),
    )


def _deny_gates_option() -> list[str]:
    return typer.Option(
        [],
        "--deny-gates",
        help="Gate name(s) to refuse, overriding --yes/--skip-gates (repeatable).",
    )


@app.callback()
def _main(
    ctx: typer.Context,
    repo: Optional[Path] = typer.Option(
        None,
        "--repo",
        help=(
            "Override the target repository root (default: auto-detect via git). "
            "Never selects the toolkit."
        ),
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    verbose: bool = typer.Option(
        False, "--verbose", help="Echo the run log lines (stages, models, prompts) to stderr."
    ),
    retry_transient: bool = typer.Option(
        True,
        "--retry-transient/--no-retry-transient",
        help="Retry once when Pi reports a transient invocation error.",
    ),
    progress: Optional[bool] = typer.Option(
        None,
        "--progress/--no-progress",
        help=(
            "Show '.' progress while Pi works (default: on when stderr is an "
            "interactive terminal)."
        ),
    ),
) -> None:
    """AIDT = AI Developer Tools — Pi-driven workflows for Mythical Forge."""
    _state["repo"] = repo
    _state["verbose"] = verbose
    _state["retry_transient"] = retry_transient
    _state["progress"] = progress
    runner_mod.DEFAULT_RETRY_TRANSIENT = retry_transient
    runner_mod.DEFAULT_PROGRESS = progress
    ctx.obj = _state


@app.command()
def version() -> None:
    """Print the AIDT version."""
    typer.echo(f"aidt {__version__}")


@app.command()
def doctor() -> None:
    """Validate the local environment and prerequisites."""
    raise typer.Exit(run_doctor(verbose=bool(_state["verbose"])))


# --------------------------------------------------------------------------- #
# Workflow groups
# --------------------------------------------------------------------------- #


@app.command()
def prompt(
    phase: str = typer.Argument(..., help="Zero-padded phase, e.g. 03."),
    epic: str = typer.Argument(..., help="Epic id, e.g. E2."),
    task: str = typer.Argument(..., help="Task id, e.g. E2.9."),
    yes: bool = typer.Option(False, "--yes", help="Approve all gates."),
    skip_gates: list[str] = typer.Option(
        [], "--skip-gates", help="Gate name(s) to skip (repeatable)."
    ),
    deny_gates: list[str] = _deny_gates_option(),
    gate_default: Optional[GateDefault] = _gate_default_option(),
    require_approval: bool = typer.Option(
        False,
        "--require-approval",
        help="Pause at the approve-task-prompt gate (default: no approval required).",
    ),
    strict: bool = typer.Option(False, "--strict", help="Fail on config warnings."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan only; no writes."),
) -> None:
    """Generate and review a task prompt (workflow group 1)."""
    repo, aidt = _roots()
    code = prompt_workflow.run(
        phase=phase,
        epic=epic,
        task=task,
        repo=repo,
        aidt=aidt,
        approve_all=yes,
        skip_gates=list(skip_gates),
        deny_gates=list(deny_gates),
        gate_default=_gate_default_value(gate_default),
        require_approval=require_approval,
        strict=strict,
        dry_run=dry_run,
        stream=bool(_state["verbose"]),
    )
    raise typer.Exit(code)


@app.command()
def implement(
    task_prompt_path: Path = typer.Argument(
        ..., help="Path to the generated task prompt."
    ),
    pr: Optional[int] = typer.Option(None, "--pr", help="Existing PR number, if any."),
    resume: bool = typer.Option(False, "--resume", help="Resume the latest run."),
    from_stage: Optional[str] = typer.Option(
        None, "--from", help="Re-run from this stage onward."
    ),
    parallel: bool = typer.Option(
        False, "--parallel", help="Run safe stage pairs concurrently."
    ),
    yes: bool = typer.Option(False, "--yes", help="Approve all gates."),
    skip_gates: list[str] = typer.Option([], "--skip-gates"),
    deny_gates: list[str] = _deny_gates_option(),
    gate_default: Optional[GateDefault] = _gate_default_option(),
    strict: bool = typer.Option(False, "--strict"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Implement a task prompt and open the PR (workflow group 2)."""
    repo, aidt = _roots()
    code = implement_workflow.run(
        task_prompt_path=task_prompt_path,
        repo=repo,
        aidt=aidt,
        pr=pr,
        resume=resume,
        from_stage=from_stage,
        parallel=parallel,
        approve_all=yes,
        skip_gates=list(skip_gates),
        deny_gates=list(deny_gates),
        gate_default=_gate_default_value(gate_default),
        strict=strict,
        dry_run=dry_run,
        stream=bool(_state["verbose"]),
    )
    raise typer.Exit(code)


@app.command()
def review(
    pr: int = typer.Option(..., "--pr", help="Pull request number."),
    yes: bool = typer.Option(False, "--yes"),
    strict: bool = typer.Option(False, "--strict"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    force_model: bool = typer.Option(
        False, "--force-model", help="Bypass the author/judge model check (recorded)."
    ),
) -> None:
    """Review a PR and publish findings as GitHub issues (workflow group 3)."""
    repo, aidt = _roots()
    code = review_workflow.run(
        pr=pr,
        repo=repo,
        aidt=aidt,
        approve_all=yes,
        strict=strict,
        dry_run=dry_run,
        force_model=force_model,
        stream=bool(_state["verbose"]),
    )
    raise typer.Exit(code)


@app.command()
def fix(
    pr: int = typer.Option(..., "--pr", help="Pull request number."),
    max_iterations: int = typer.Option(
        10, "--max-iterations", help="Bound the review/fix loop."
    ),
    yes: bool = typer.Option(False, "--yes"),
    skip_gates: list[str] = typer.Option([], "--skip-gates"),
    deny_gates: list[str] = _deny_gates_option(),
    gate_default: Optional[GateDefault] = _gate_default_option(),
    strict: bool = typer.Option(False, "--strict"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    force_model: bool = typer.Option(False, "--force-model"),
) -> None:
    """Fix approved review follow-ups, one at a time (workflow group 4)."""
    repo, aidt = _roots()
    code = fix_workflow.run(
        pr=pr,
        repo=repo,
        aidt=aidt,
        max_iterations=max_iterations,
        approve_all=yes,
        skip_gates=list(skip_gates),
        deny_gates=list(deny_gates),
        gate_default=_gate_default_value(gate_default),
        strict=strict,
        dry_run=dry_run,
        force_model=force_model,
        stream=bool(_state["verbose"]),
    )
    raise typer.Exit(code)


@app.command(name="approve-followups")
def approve_followups(
    pr: int = typer.Option(..., "--pr", help="Pull request number."),
    yes: bool = typer.Option(False, "--yes", help="Approve the gate without prompting."),
    skip_gates: list[str] = typer.Option([], "--skip-gates", help="Gate name(s) to skip."),
    deny_gates: list[str] = _deny_gates_option(),
    gate_default: Optional[GateDefault] = _gate_default_option(),
    strict: bool = typer.Option(False, "--strict"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Approve a PR's open review follow-up issues (workflow group 5)."""
    repo, aidt = _roots()
    code = approve_workflow.run(
        pr=pr,
        repo=repo,
        aidt=aidt,
        approve_all=yes,
        skip_gates=list(skip_gates),
        deny_gates=list(deny_gates),
        gate_default=_gate_default_value(gate_default),
        strict=strict,
        dry_run=dry_run,
        stream=bool(_state["verbose"]),
    )
    raise typer.Exit(code)


@app.command(name="run")
def run_chain(
    workflow: str = typer.Argument(..., help="task-to-pr | review-and-fix"),
    phase: Optional[str] = typer.Argument(None, help="task-to-pr: phase, e.g. 03."),
    epic: Optional[str] = typer.Argument(None, help="task-to-pr: epic, e.g. E4."),
    task: Optional[str] = typer.Argument(None, help="task-to-pr: task, e.g. E4.1."),
    pr: Optional[int] = typer.Option(None, "--pr", help="review-and-fix: PR number."),
    yes: bool = typer.Option(False, "--yes", help="Approve all gates."),
    deny_gates: list[str] = _deny_gates_option(),
    gate_default: Optional[GateDefault] = _gate_default_option(),
    strict: bool = typer.Option(False, "--strict"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    parallel: bool = typer.Option(False, "--parallel"),
    max_iterations: int = typer.Option(10, "--max-iterations"),
) -> None:
    """Run a convenience chain of workflows."""
    repo, aidt = _roots()

    if workflow == "task-to-pr":
        if not (phase and epic and task):
            typer.echo("task-to-pr requires <phase> <epic> <task>", err=True)
            raise typer.Exit(EXIT_USAGE)
        code = run_workflow.task_to_pr(
            phase=phase,
            epic=epic,
            task=task,
            repo=repo,
            aidt=aidt,
            approve_all=yes,
            deny_gates=list(deny_gates),
            gate_default=_gate_default_value(gate_default),
            strict=strict,
            dry_run=dry_run,
            parallel=parallel,
            stream=bool(_state["verbose"]),
        )
    elif workflow == "review-and-fix":
        if pr is None:
            typer.echo("review-and-fix requires --pr <n>", err=True)
            raise typer.Exit(EXIT_USAGE)
        code = run_workflow.review_and_fix(
            pr=pr,
            repo=repo,
            aidt=aidt,
            approve_all=yes,
            deny_gates=list(deny_gates),
            gate_default=_gate_default_value(gate_default),
            strict=strict,
            dry_run=dry_run,
            max_iterations=max_iterations,
            stream=bool(_state["verbose"]),
        )
    else:
        typer.echo(
            f"unknown chain: {workflow} (expected task-to-pr | review-and-fix)",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    raise typer.Exit(code)


# --------------------------------------------------------------------------- #
# Inspection
# --------------------------------------------------------------------------- #


@app.command()
def tasks(
    todo: bool = typer.Option(False, "--todo", help="Only unchecked tasks."),
    phase: Optional[str] = typer.Option(None, "--phase", help="Filter by phase."),
    epic: Optional[str] = typer.Option(None, "--epic", help="Filter by epic."),
    show: Optional[str] = typer.Option(
        None, "--show", help='Show one task: "<phase> <epic> <task>".'
    ),
    next_: bool = typer.Option(False, "--next", help="Show the next unchecked task."),
) -> None:
    """List or inspect roadmap tasks parsed from docs/tasks/."""
    repo, _aidt = _roots()
    entries = load_tasks(repo / "docs" / "tasks")
    if not entries:
        typer.echo("no roadmap tasks found", err=True)
        raise typer.Exit(EXIT_USAGE)

    if show:
        parts = show.split()
        if len(parts) != 3:
            typer.echo('--show requires "<phase> <epic> <task>"', err=True)
            raise typer.Exit(EXIT_USAGE)
        entry = find_task(entries, parts[0], parts[1], parts[2])
        if entry is None:
            typer.echo(f"task not found: {show}", err=True)
            raise typer.Exit(EXIT_USAGE)
        typer.echo(
            f"{entry.phase} {entry.epic} {entry.task}  "
            f"[{'x' if entry.done else ' '}] {entry.title}"
        )
        if entry.epic_title:
            typer.echo(f"Epic:      {entry.epic_title}")
        typer.echo(f"Branch:    {entry.branch}")
        typer.echo(f"File:      {entry.file}:{entry.line}")
        if entry.done_when:
            typer.echo(f"Done when: {entry.done_when}")
        if entry.citations:
            typer.echo(f"Specs:     {', '.join(entry.citations)}")
        return

    if next_:
        entry = next_todo(entries, phase=phase)
        if entry is None:
            typer.echo("no unchecked tasks match")
            return
        typer.echo(f"{entry.phase} {entry.epic} {entry.task}  {entry.title}")
        return

    result = filter_tasks(entries, phase=phase, epic=epic, todo=todo)
    if not result:
        typer.echo("no matching tasks")
        return
    for entry in result:
        mark = "x" if entry.done else " "
        typer.echo(
            f"[{mark}] {entry.phase:<5} {entry.epic:<3} {entry.task:<8} {entry.title}"
        )


@app.command()
def agents(
    action: str = typer.Argument("list", help="list | show | validate"),
    agent_id: Optional[str] = typer.Argument(None, help="Agent id for `show`."),
    strict: bool = typer.Option(
        False, "--strict", help="Treat warnings as failures when validating."
    ),
) -> None:
    """List, inspect, or validate agent configs."""
    repo, aidt = _roots()
    configs, issues = load_all(aidt, repo)

    if action == "list":
        width = max((len(a.id) for a in configs.values()), default=4)
        for agent in sorted(configs.values(), key=lambda a: a.id):
            marker = "" if not agent.issues else "  (invalid)"
            typer.echo(
                f"{agent.id.ljust(width)}  {agent.qualified_model}  "
                f"tools=[{','.join(agent.tools) or 'none'}]  "
                f"session={agent.session}{marker}"
            )
        return

    if action == "show":
        if not agent_id or agent_id not in configs:
            typer.echo(f"unknown agent: {agent_id}", err=True)
            raise typer.Exit(EXIT_USAGE)
        agent = configs[agent_id]
        typer.echo(f"id:          {agent.id}")
        typer.echo(f"description: {agent.description}")
        typer.echo(f"model:       {agent.qualified_model}")
        typer.echo(f"thinking:    {agent.thinking}")
        typer.echo(f"tools:       {', '.join(agent.tools) or '(none)'}")
        typer.echo(f"session:     {agent.session}")
        typer.echo(f"cwd:         {agent.cwd}")
        typer.echo(f"agents_md:   {agent.agents_md}")
        if agent.system_prompt.file:
            typer.echo(f"system:      {agent.system_prompt.mode} {agent.system_prompt.file}")
        typer.echo(f"timeout:     {agent.timeout_seconds}s")
        for issue in agent.issues:
            typer.echo(f"  [{issue.level}] {issue.message}")
        return

    if action == "validate":
        errors = [i for i in issues if i.level == ERROR]
        warnings = [i for i in issues if i.level == WARNING]
        if issues:
            typer.echo(format_issues(issues))
        typer.echo(
            f"{len(configs)} agent config(s): {len(errors)} error(s), {len(warnings)} warning(s)"
        )
        if errors or (strict and warnings):
            raise typer.Exit(EXIT_STAGE_FAILURE)
        return

    typer.echo(f"unknown action: {action} (expected list | show | validate)", err=True)
    raise typer.Exit(EXIT_USAGE)


@app.command(name="exec")
def exec_stage(
    agent: str = typer.Option(..., "--agent", help="Agent id from agent-configs."),
    prompt: str = typer.Option(..., "--prompt", help="Prompt name (e.g. code-review) or path."),
    var: list[str] = typer.Option(
        [], "--var", help="Positional prompt variable (repeatable)."
    ),
    workflow: str = typer.Option("stage", "--workflow", help="Workflow label for the run."),
    label: str = typer.Option("manual", "--label", help="Run label (run id suffix)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan only; do not invoke Pi."),
    strict: bool = typer.Option(False, "--strict", help="Fail on config warnings."),
    retry_transient: bool = typer.Option(
        True, "--retry-transient/--no-retry-transient",
        help="Retry once on a transient Pi invocation error.",
    ),
) -> None:
    """Run a single agent stage (the primitive workflows build on)."""
    repo, aidt = _roots()
    state_root = WorkspacePaths.resolve(TargetRepo.resolve(repo)).state_root
    runs_root = state_root / "runs"
    agents, issues = load_all(aidt, repo)
    errors = [i for i in issues if i.level == ERROR]
    warnings = [i for i in issues if i.level == WARNING]
    if errors or (strict and warnings):
        typer.echo(format_issues(errors + (warnings if strict else [])))
        raise typer.Exit(EXIT_STAGE_FAILURE)

    try:
        prompt_path = resolve_prompt(aidt, prompt)
    except Exception as exc:  # pragma: no cover - defensive
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc

    run = state_mod.create_run(
        runs_root,
        repo,
        workflow,
        label=label,
        strict=strict,
        branch=git.current_branch(repo),
    )
    directory = state_mod.run_dir(runs_root, run.run_id)
    logger = RunLogger(directory, stream=bool(_state["verbose"]))
    spec = StageSpec(
        name=prompt_path.stem,
        agent_id=agent,
        prompt=prompt_path,
        variables=list(var),
        workflow=workflow,
    )

    try:
        record = run_stage(
            spec,
            repo_root=repo,
            toolkit_root=aidt,
            state=run,
            logger=logger,
            agents=agents,
            dry_run=dry_run,
            retry_transient=retry_transient,
            runs_root=runs_root,
        )
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc

    typer.echo(f"run:      {run.run_id}")
    for line in stage_lines(record, repo_root=repo):
        typer.echo(line)
    if record.rendered_prompt:
        rendered_rel = (
            runs_root / run.run_id / record.rendered_prompt
        ).relative_to(state_root)
        typer.echo(f"rendered: {rendered_rel}")

    if record.status == state_mod.SUCCEEDED and run.status != state_mod.SUCCEEDED:
        run.status = state_mod.SUCCEEDED
        state_mod.save(directory, run)

    if dry_run:
        typer.echo("dry-run complete; Pi not invoked")
        return

    out = record.artifacts.get("out")
    if out and Path(out).is_file():
        typer.echo("--- final message ---")
        typer.echo(Path(out).read_text(encoding="utf-8").rstrip())

    if record.status != state_mod.SUCCEEDED:
        raise typer.Exit(EXIT_STAGE_FAILURE)


@app.command()
def runs(
    action: str = typer.Argument("list", help="list | show | resume"),
    run_id: Optional[str] = typer.Argument(None, help="Run id for `show`/`resume`."),
) -> None:
    """List, inspect, or resume workflow runs."""
    repo, _aidt = _roots()
    runs_root = WorkspacePaths.resolve(TargetRepo.resolve(repo)).state_root / "runs"

    if action == "list":
        states = state_mod.list_runs(runs_root)
        if not states:
            typer.echo("no runs")
            return
        for item in states:
            branch = item.git.get("branch") or "-"
            typer.echo(
                f"{item.run_id}  {item.workflow}  {item.status}  {branch}"
            )
        return

    if action == "show":
        if not run_id:
            typer.echo("`runs show` requires a run id", err=True)
            raise typer.Exit(EXIT_USAGE)
        loaded = state_mod.find_run(runs_root, run_id)
        if loaded is None:
            typer.echo(f"unknown run: {run_id}", err=True)
            raise typer.Exit(EXIT_USAGE)
        typer.echo(f"run:      {loaded.run_id}")
        typer.echo(f"workflow: {loaded.workflow}")
        typer.echo(f"status:   {loaded.status}")
        typer.echo(f"branch:   {loaded.git.get('branch') or '-'}")
        for stage in loaded.stages:
            detail = f"{stage.status} ({stage.agent}, {stage.model})"
            if stage.duration_seconds is not None:
                detail += f", {stage.duration_seconds:g}s"
            if stage.cost_usd:
                detail += f", ${stage.cost_usd:.4f}"
            typer.echo(f"  stage {stage.name}: {detail}")
            measured = usage_line(stage.usage)
            if measured:
                typer.echo(f"          usage: {measured}")
            out = stage.artifacts.get("out")
            if out:
                typer.echo(f"          out:   {rel_to(Path(loaded.repo_root), out)}")
            if stage.error:
                typer.echo(f"          error: {stage.error}")
        for gate in loaded.gates:
            typer.echo(f"  gate {gate.name}: {gate.decision} ({gate.mechanism})")
        return

    if action == "resume":
        typer.echo(
            "`runs resume` is wired per-workflow; use the workflow's own --resume flag "
            "(`aidw implement --resume`; `aidw fix` has no resume in v1).",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    typer.echo(f"unknown action: {action} (expected list | show | resume)", err=True)
    raise typer.Exit(EXIT_USAGE)


@app.command()
def prompts(
    action: str = typer.Argument("list", help="list | check"),
) -> None:
    """List or check the toolkit's own prompts and helper scripts."""
    aidt = toolkit_root()

    if action == "list":
        files = inventory.list_files(aidt)
        if not files:
            typer.echo("no prompts found", err=True)
            raise typer.Exit(EXIT_USAGE)
        for rel in files:
            typer.echo(rel)
        return

    if action == "check":
        issues = inventory.check(aidt)
        if issues:
            typer.echo(format_issues(issues))
        errors = [i for i in issues if i.level == ERROR]
        warnings = [i for i in issues if i.level == WARNING]
        typer.echo(f"prompts check: {len(errors)} error(s), {len(warnings)} warning(s)")
        if errors:
            raise typer.Exit(EXIT_STAGE_FAILURE)
        return

    typer.echo(f"unknown action: {action} (expected list | check)", err=True)
    raise typer.Exit(EXIT_USAGE)


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
