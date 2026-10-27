"""AIDW command-line interface.

Typer application that dispatches to the workflow groups plus inspection
commands. Phase 0 registers every command from the design's CLI reference so the
surface is stable; workflow bodies are implemented in later phases.

Design reference: ``aidt/design.md`` §14 (CLI reference), §16 (build plan).
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Optional

import typer

from aidw import (
    __version__,
    git,
    inventory,
    pi as pi_mod,
    runner as runner_mod,
    state as state_mod,
)
from aidw import verification
from aidw.config import ERROR, WARNING, format_issues, load_all
from aidw.doctor import run_doctor
from aidw.gates import GateDefault
from aidw.layout import LayoutError, check_layout
from aidw.log import RunLogger
from aidw.paths import (
    RUN_ID_ENV_VAR,
    STAGE_ENV_VAR,
    STATE_DIR_ENV_VAR,
    RepoNotFoundError,
    TargetRepo,
    ToolkitPaths,
    WorkspacePaths,
)
from aidw.roadmap import filter_tasks, find_task, load_tasks, next_todo
from aidw.report import (
    rel_to,
    stage_lines,
    throughput,
    timing_line,
    tool_breakdown_line,
    usage_line,
)
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

#: Environment variable overriding ``--repo``'s target selection (EXTRACTION.md §3.3/D19).
AIDW_REPO_ENV_VAR = "AIDW_REPO"

# Populated by the top-level callback; read by commands.
_state: dict[str, object] = {"repo": None, "verbose": False}


def _resolve_target_selection() -> tuple[Optional[Path], str]:
    """Return ``(explicit target override, winning provenance label)``.

    Precedence is ``--repo`` > ``$AIDW_REPO`` > cwd (EXTRACTION.md §3.3/D19),
    mirroring ``aidw/gates.py`` (``--gate-default`` > ``$AIDW_GATE_DEFAULT``).
    ``--repo`` is validated by Typer; ``AIDW_REPO`` is raw environment text
    normalised here — stripped, with an empty/whitespace-only value treated as
    unset — so a blank value never becomes ``Path("")``. The label is one of
    ``--repo`` | ``AIDW_REPO`` | ``cwd`` and is shared by :func:`_roots` and
    ``config show`` so the environment is read in exactly one place.
    """
    override = _state.get("repo")
    if override:
        return Path(override), "--repo"
    raw = (os.environ.get(AIDW_REPO_ENV_VAR) or "").strip()
    if raw:
        return Path(raw), AIDW_REPO_ENV_VAR
    return None, "cwd"


def _roots() -> tuple[TargetRepo, ToolkitPaths, WorkspacePaths]:
    """Resolve ``(target repo, toolkit, workspace)`` once for a command.

    Target selection comes from :func:`_resolve_target_selection` (``--repo`` >
    ``$AIDW_REPO`` > cwd); the chosen override is passed as ``explicit=`` so an
    invalid one refuses rather than falling back to cwd. The toolkit root always
    comes from the installed package location, so no flag can point the toolkit at
    a checkout. This is the single ``TargetRepo``/``WorkspacePaths`` resolution
    site: ``run.py`` and the workflows receive the typed objects and pass those
    same objects on.
    """
    explicit, _source = _resolve_target_selection()
    try:
        target = TargetRepo.resolve(explicit=explicit)
    except RepoNotFoundError as exc:
        # One catch site for every `explicit=` failure: a bad AIDW_REPO, or a --repo
        # that passed Typer's exists=True but is not a repo or is bare
        # (BareRepositoryError subclasses RepoNotFoundError and keeps its message).
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_REFUSED)
    workspace = WorkspacePaths.resolve(target)
    try:
        # E2.2 layout guards (§3.2/§3.10). The clone-of-a-worktree trap is a hard
        # failure mirroring the RepoNotFoundError catch above; the state-inside-tree
        # case is advisory and is echoed to stderr without blocking.
        warnings = check_layout(target, workspace)
    except LayoutError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_REFUSED)
    for warning in warnings:
        typer.echo(warning, err=True)
    return target, ToolkitPaths.resolve(), workspace


def _state_root_source(workspace: WorkspacePaths) -> str:
    """Label which ``_state_base`` tier produced ``workspace.state_root``.

    ``config show`` gets its workspace from :func:`_roots` with
    ``state_dir_override`` at its ``None`` default, so only three tiers are
    reachable: ``$AIDW_STATE_DIR``, ``<workspace_root>/.aidw/state``, else
    ``~/.aidw/state``. The already-resolved ``state_root`` encodes which one won,
    so compare its parent to the candidates in ``_state_base``'s post-override
    order instead of re-running the usability walk (which could disagree).

    The env candidate mirrors ``_state_base`` exactly — a bare truthiness test and
    ``Path(env).resolve()``, no strip — so a whitespace-only value counts as "set".
    Both candidates are resolved before comparison because ``state_root.parent`` is
    already resolved (``WorkspacePaths.resolve`` resolves every tier).
    """
    parent = workspace.state_root.parent
    env = os.environ.get(STATE_DIR_ENV_VAR)
    if env and Path(env).resolve() == parent:
        return STATE_DIR_ENV_VAR
    if (workspace.workspace_root / ".aidw" / "state").resolve() == parent:
        return "workspace"
    return "home"


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
            "Override the target repository root (default: $AIDW_REPO, else "
            "auto-detect via git). Never selects the toolkit."
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
    """AIDT = AI Developer Tools — Pi-driven workflows for Mythical Forge.

    The target repository is ``--repo > $AIDW_REPO > cwd`` (EXTRACTION.md §3.3/D19).
    """
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
    no_fetch: bool = typer.Option(
        False,
        "--no-fetch",
        help="Skip fetching and the base-branch freshness check (offline runs).",
    ),
    allow_incomplete_prereqs: bool = typer.Option(
        False,
        "--allow-incomplete-prereqs",
        help="Author even when earlier tasks in the same phase file are unticked.",
    ),
    max_revisions: Optional[int] = typer.Option(
        None,
        "--max-revisions",
        help=(
            "Review-round budget (default 3); the last round is review-only. "
            "Must be >= 1."
        ),
    ),
) -> None:
    """Generate and review a task prompt (workflow group 1)."""
    # Usage error before any work: a sub-review budget (0 or negative) is meaningless, so
    # refuse it here rather than after the author has written and committed a prompt (L4.3).
    if max_revisions is not None and max_revisions < 1:
        typer.echo(
            f"--max-revisions must be >= 1 (got {max_revisions}).", err=True
        )
        raise typer.Exit(EXIT_USAGE)
    repo, aidt, workspace = _roots()
    code = prompt_workflow.run(
        phase=phase,
        epic=epic,
        task=task,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
        approve_all=yes,
        skip_gates=list(skip_gates),
        deny_gates=list(deny_gates),
        gate_default=_gate_default_value(gate_default),
        require_approval=require_approval,
        strict=strict,
        dry_run=dry_run,
        no_fetch=no_fetch,
        allow_incomplete_prereqs=allow_incomplete_prereqs,
        max_revisions=max_revisions,
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
    repo, aidt, workspace = _roots()
    code = implement_workflow.run(
        task_prompt_path=task_prompt_path,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
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
    repo, aidt, workspace = _roots()
    code = review_workflow.run(
        pr=pr,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
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
    repo, aidt, workspace = _roots()
    code = fix_workflow.run(
        pr=pr,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
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
    repo, aidt, workspace = _roots()
    code = approve_workflow.run(
        pr=pr,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
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
    repo, aidt, workspace = _roots()

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
            workspace=workspace,
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
            workspace=workspace,
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
    repo, _aidt, _workspace = _roots()
    entries = load_tasks(repo.root / "docs" / "tasks")
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
    repo, aidt, _workspace = _roots()
    configs, issues = load_all(aidt.root, repo.root)

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
    repo, aidt, workspace = _roots()
    state_root = workspace.state_root
    runs_root = state_root / "runs"
    agents, issues = load_all(aidt.root, repo.root)
    errors = [i for i in issues if i.level == ERROR]
    warnings = [i for i in issues if i.level == WARNING]
    if errors or (strict and warnings):
        typer.echo(format_issues(errors + (warnings if strict else [])))
        raise typer.Exit(EXIT_STAGE_FAILURE)

    try:
        prompt_path = resolve_prompt(aidt.root, prompt)
    except Exception as exc:  # pragma: no cover - defensive
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc

    run = state_mod.create_run(
        runs_root,
        repo.root,
        workflow,
        label=label,
        strict=strict,
        branch=git.current_branch(repo.root),
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
            repo_root=repo.root,
            toolkit_root=aidt.root,
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
    for line in stage_lines(record, repo_root=repo.root):
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
    repo, _aidt, workspace = _roots()
    runs_root = workspace.state_root / "runs"

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
        run_directory = state_mod.run_dir(runs_root, loaded.run_id)
        for stage in loaded.stages:
            # A run recorded before these fields existed still has Pi's per-call
            # ``durationMs`` in its stage log, so recover the split rather than hiding
            # it. Display-only: ``state.json`` is left untouched by a read command. The
            # log is parsed once and both the total and the per-tool split come from it.
            if (stage.tool_seconds is None or not stage.tool_breakdown) and stage.log:
                recovered = pi_mod.tool_breakdown_from_log(run_directory / stage.log)
                if recovered:
                    if stage.tool_seconds is None:
                        stage = dataclasses.replace(
                            stage, tool_seconds=round(sum(recovered.values()), 3)
                        )
                    if not stage.tool_breakdown:
                        stage = dataclasses.replace(stage, tool_breakdown=recovered)
            detail = f"{stage.status} ({stage.agent}, {stage.model})"
            if stage.duration_seconds is not None:
                detail += f", {stage.duration_seconds:g}s"
            if stage.cost_usd:
                detail += f", ${stage.cost_usd:.4f}"
            speed = throughput(stage)
            if speed:
                detail += f", {speed}"
            typer.echo(f"  stage {stage.name}: {detail}")
            measured = usage_line(stage.usage)
            if measured:
                typer.echo(f"          usage: {measured}")
            timing = timing_line(stage)
            if timing:
                typer.echo(f"          timing: {timing}")
            breakdown = tool_breakdown_line(stage.tool_breakdown)
            if breakdown:
                typer.echo(f"          tools:  {breakdown}")
            out = stage.artifacts.get("out")
            if out:
                typer.echo(f"          out:   {rel_to(Path(loaded.repo_root), out)}")
            if stage.error:
                typer.echo(f"          error: {stage.error}")
        for gate in loaded.gates:
            typer.echo(f"  gate {gate.name}: {gate.decision} ({gate.mechanism})")
        for outcome in loaded.gate_outcomes:
            for line in verification.describe(outcome):
                typer.echo(line)
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


@app.command(
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True}
)
def gate(
    ctx: typer.Context,
    action: str = typer.Argument("list", help="run | list"),
    key: Optional[str] = typer.Argument(
        None, help="Gate key for `run` — a short name such as suite, lint, build."
    ),
    run_id: Optional[str] = typer.Option(
        None,
        "--run",
        help=f"Run id to record into (default: ${RUN_ID_ENV_VAR}, which a stage sets).",
    ),
    stage: Optional[str] = typer.Option(
        None,
        "--stage",
        help=f"Stage to cite as the origin (default: ${STAGE_ENV_VAR}, else cli).",
    ),
    base: str = typer.Option(
        verification.BASE_DEFAULT,
        "--base",
        help="Base branch the tree identity is measured against.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Run even when this tree already passed this gate."
    ),
    ignore: list[str] = typer.Option(
        [],
        "--ignore",
        help=(
            "Repo-relative prefix this gate's command cannot read (repeatable). A gate "
            "never re-runs for a change confined to an ignored path, so cite it only for "
            "paths the command genuinely does not read — documents other stages write, "
            "never source, tests, config or lockfiles."
        ),
    ),
    tail: int = typer.Option(
        verification.DEFAULT_TAIL, "--tail", help="Lines of output to show."
    ),
    timeout: Optional[float] = typer.Option(
        None, "--timeout", help="Seconds before the gate command is killed."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit one JSON object instead of text."
    ),
) -> None:
    """Run a whole-repo verification gate, or list the ones this run recorded (E4.8).

    A gate is run **once per tree**: the second and later stages of a run to ask for the
    same gate against unchanged content cite the recorded outcome instead of paying for
    it again, and the citation names its origin. Content is what counts, so committing
    the verified change set does not invalidate its own verification.

    The command is the **repo's own** and is passed after ``--`` (click stops parsing
    options there, so a gate's own flags come through untouched):

    \b
        aidw gate run suite -- uv run --frozen pytest
        aidw gate run suite -- pnpm -r test

    Use ``--ignore <prefix>`` (repeatable) for paths this gate's command cannot read, and
    pass the same values from every stage that runs it. Without it the gate is tied to the
    whole tree, and in the implement chain it will re-run: ``record`` writes its results
    document after running the gate, so the tree ``pr`` delivers never matches the tree
    ``test`` gated. With the documents declared, the suite is bought once per run.

    Nothing is skipped that cannot be proven: without a resolvable base branch, without
    a run to cite from, with a differently declared scope, or with a previously *failed*
    outcome for this tree, the command runs. Use ``--force`` to run regardless.
    """
    repo, _aidt, workspace = _roots()
    runs_root = workspace.state_root / "runs"
    # The run's own artifacts must never count as part of the gated content: with
    # AIDW_STATE_DIR inside the repo (and not gitignored) every stage writes logs, so
    # nothing would ever be reusable.
    exclude = (workspace.state_root,)

    if action == "list":
        target = _gate_run(runs_root, run_id, repo.root)
        if target is None:
            typer.echo(
                f"no run to list gates for (pass --run, set {RUN_ID_ENV_VAR}, or run a "
                "workflow first)",
                err=True,
            )
            raise typer.Exit(EXIT_USAGE)
        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "run": target.run_id,
                        "gates": [dataclasses.asdict(o) for o in target.gate_outcomes],
                    }
                )
            )
            return
        if not target.gate_outcomes:
            typer.echo(f"no gate outcomes recorded for {target.run_id}")
            return
        typer.echo(f"run: {target.run_id} ({target.git.get('branch') or '-'})")
        for outcome in target.gate_outcomes:
            for line in verification.describe(outcome):
                typer.echo(line)
        return

    if action != "run":
        typer.echo(f"unknown action: {action} (expected run | list)", err=True)
        raise typer.Exit(EXIT_USAGE)

    command = list(ctx.args)
    if not key or not command:
        typer.echo(
            "usage: aidw gate run <key> -- <command> [args...] "
            '(for example: aidw gate run suite -- uv run --frozen pytest)',
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    try:
        verification.normalise_ignore(ignore)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE)

    recorded = _gate_run(runs_root, run_id, repo.root)

    result = verification.run_gate(
        key,
        command,
        repo_root=repo.root,
        run=recorded,
        stage=stage or os.environ.get(STAGE_ENV_VAR) or "cli",
        base=base,
        exclude=exclude,
        ignore=ignore,
        force=force,
        tail=tail,
        timeout=timeout,
    )
    if recorded is not None and not result.reused:
        state_mod.save(state_mod.run_dir(runs_root, recorded.run_id), recorded)

    if json_output:
        typer.echo(json.dumps(result.to_dict()))
        raise typer.Exit(result.exit_code)

    # The real output first, the one-line outcome last: the summary is the takeaway, and
    # a failed gate is legible without re-reading the tail.
    if not result.reused:
        for line in result.tail_lines(tail):
            typer.echo(line)
    typer.echo(result.citation)
    if result.note:
        typer.echo(f"note: {result.note}", err=True)
    raise typer.Exit(result.exit_code)


def _gate_run(
    runs_root: Path, run_id: Optional[str], repo_root: Path
) -> state_mod.RunState | None:
    """Resolve the run a gate records into: ``--run`` > ``$AIDW_RUN_ID`` > this branch.

    The environment variable is how a stage's agent finds its own run; the branch
    fallback is for a human at a terminal, who has no run id to hand and means the one
    they are working in. An explicitly named run that does not exist is an error rather
    than a silent fall-through to the branch, so a typo cannot quietly record an outcome
    against the wrong run.
    """
    value = run_id or (os.environ.get(RUN_ID_ENV_VAR) or "").strip()
    if value:
        found = state_mod.find_run(runs_root, value)
        if found is None:
            typer.echo(f"unknown run: {value}", err=True)
            raise typer.Exit(EXIT_USAGE)
        return found
    branch = git.current_branch(repo_root)
    return state_mod.latest_for_branch(runs_root, branch) if branch else None


@app.command()
def prompts(
    action: str = typer.Argument("list", help="list | check"),
) -> None:
    """List or check the toolkit's own prompts and helper scripts."""
    aidt = ToolkitPaths.resolve().root

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


@app.command()
def config(
    action: str = typer.Argument("show", help="show"),
    json_output: bool = typer.Option(
        False, "--json", help="Emit one JSON object with per-value provenance."
    ),
) -> None:
    """Show the resolved roots and the target config file, with provenance.

    Skeleton only (EXTRACTION.md §3.3): every value is resolved, but the target
    ``aidw/config.yaml`` is detected with ``is_file()`` and never parsed — loading
    and validating it is E3.1/E3.2 scope. The action is validated before any
    printing or resolution so a doubly-bad invocation (unknown action plus a bad
    target) exits ``EXIT_USAGE`` with empty stdout; a bad target still refuses via
    :func:`_roots`'s ``RepoNotFoundError`` -> ``EXIT_REFUSED`` path.
    """
    if action != "show":
        typer.echo(f"unknown action: {action} (expected show)", err=True)
        raise typer.Exit(EXIT_USAGE)

    if not json_output:
        # Human-mode debug aid: these two resolve with no repo, so a wrong target
        # still shows them before the refusal below. JSON buffers all six values and
        # emits nothing until resolution succeeds, so a refusal leaves stdout empty.
        typer.echo(f"toolkit root: {ToolkitPaths.resolve().root} (package)")
        typer.echo(f"version: {__version__} (package)")

    # Do not catch _roots()'s RepoNotFoundError: a bad --repo/AIDW_REPO, a non-repo
    # cwd or a bare target must still refuse with EXIT_REFUSED naming the path.
    target, _toolkit, workspace = _roots()
    _explicit, target_source = _resolve_target_selection()
    state_source = _state_root_source(workspace)

    config_path = target.root / "aidw" / "config.yaml"
    if config_path.is_file():
        config_value: Optional[str] = str(config_path.resolve())
        config_source = "target repo"
    else:
        config_value = None
        config_source = "defaults"

    if json_output:
        payload = {
            "toolkit_root": {
                "value": str(ToolkitPaths.resolve().root),
                "source": "package",
            },
            "version": {"value": __version__, "source": "package"},
            "target_root": {"value": str(target.root), "source": target_source},
            "workspace_root": {
                "value": str(workspace.workspace_root),
                "source": "workspace",
            },
            "state_root": {"value": str(workspace.state_root), "source": state_source},
            "config_file": {"value": config_value, "source": config_source},
        }
        typer.echo(json.dumps(payload))
        return

    typer.echo(f"target root: {target.root} ({target_source})")
    typer.echo(f"workspace root: {workspace.workspace_root} (workspace)")
    typer.echo(f"state root: {workspace.state_root} ({state_source})")
    typer.echo(f"config file: {config_value or 'none'} ({config_source})")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
