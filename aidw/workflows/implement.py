"""``aidw implement`` — implement a task prompt and open the PR (design §8.2).

Stage order follows ``docs/workflow.md`` (the focused stages run serially, leaving the
working tree uncommitted; ``/pr`` is the single owner of the delivery step):

```
I1 impliment-task                 agent implementer (session shared)
I2 test                           agent tester      (fresh)
I3 update-traceability            agent implementer (session shared)
I4 update-architecture            agent implementer (session shared)
I5 record-implementation-results  agent recorder    (fresh)  SYNC POINT
◇  approve-implementation-pr
I6 pr                             agent pr-publisher (fresh)
```

``I2`` and ``I4`` touch disjoint trees and are safe to run concurrently in principle,
but v1 runs every stage serially (``--parallel`` is accepted and deferred to Phase 7).

The workflow refuses to run on ``main``, when the branch does not match the task id, or
when another implement run for the branch is still marked ``running``.
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from aidw import git
from aidw.config import ERROR, WARNING, format_issues, load_all
from aidw.gates import decide
from aidw.log import RunLogger
from aidw.report import print_stage
from aidw.runner import StageSpec, run_stage
from aidw.state import (
    BLOCKED,
    FAILED,
    RUNNING,
    SUCCEEDED,
    GateRecord,
    RunState,
    create_run,
    list_runs,
    run_dir,
    save,
    utcnow_iso,
)

GATE = "approve-implementation-pr"

#: ``03-E4.1-prompt.md`` → phase ``03``, task ``E4.1``, branch ``03-E4.1``.
_PROMPT_NAME = re.compile(
    r"^(?P<phase>[0-9]+(?:\.[0-9]+)?)-(?P<task>.+?)(?:-prompt)?\.md$"
)

_PR_URL = re.compile(r"https?://\S*/pull/(\d+)")

_TEST_CONTEXT = """\

## Stage context (provided by aidw)

- Task: {task_id}
- Branch: {branch}
- Task prompt: {prompt_rel}

Read the task prompt above, follow its acceptance criteria, and prove them. Leave your
changes uncommitted in the working tree.
"""


@dataclass
class PlanStage:
    """One planned stage: an id, its agent, prompt and prompt variables."""

    id: str
    name: str
    agent: str
    prompt_file: str
    variables: list[str] = field(default_factory=list)
    extra: str = ""

    def spec(self, aidt: Path) -> StageSpec:
        return StageSpec(
            self.name,
            self.agent,
            aidt / "prompts" / self.prompt_file,
            list(self.variables),
            extra=self.extra,
        )


def parse_task_id(prompt_path: Path) -> tuple[str, str, str] | None:
    """Derive ``(phase, task, branch)`` from a task-prompt filename.

    Accepts the canonical ``<phase>-<task>-prompt.md`` and the bare
    ``<phase>-<task>.md`` an author model may produce. Returns ``None`` when the
    filename carries no task id.
    """
    match = _PROMPT_NAME.match(prompt_path.name)
    if not match:
        return None
    phase = match.group("phase")
    task = match.group("task")
    return phase, task, f"{phase}-{task}"


def build_plan(
    *, aidt: Path, prompt_rel: str, branch: str, task_id: str
) -> list[PlanStage]:
    """The six stages, in order (I6 is the ``pr`` stage)."""
    return [
        PlanStage("I1", "impliment-task", "implementer", "impliment-task.md", [prompt_rel]),
        PlanStage(
            "I2",
            "test",
            "tester",
            "test.md",
            extra=_TEST_CONTEXT.format(
                task_id=task_id, branch=branch, prompt_rel=prompt_rel
            ),
        ),
        PlanStage(
            "I3",
            "update-traceability",
            "implementer",
            "update-traceability.md",
            [branch],
        ),
        PlanStage(
            "I4",
            "update-architecture",
            "implementer",
            "update-architecture.md",
            [branch, "main"],
        ),
        PlanStage(
            "I5",
            "record-implementation-results",
            "recorder",
            "record-implementation-results.md",
            [branch],
        ),
        PlanStage("I6", "pr", "pr-publisher", "pr.md", [task_id]),
    ]


def _read_out(record) -> str | None:
    out = record.artifacts.get("out")
    if out and Path(out).is_file():
        return Path(out).read_text(encoding="utf-8")
    return None


def _latest_implement_run(runs_dir: Path, branch: str) -> RunState | None:
    matches = [
        state
        for state in list_runs(runs_dir)
        if state.workflow == "implement" and state.git.get("branch") == branch
    ]
    return matches[-1] if matches else None


def _confirm_resume(assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return True
    try:
        answer = input("Resume this implement run? [y/N] ").strip().lower()
    except EOFError:
        return True
    return answer in ("y", "yes")


def _print_completed(state: RunState) -> None:
    for record in state.stages:
        print(f"  {record.name}: {record.status}")


def _gate_summary(state: RunState, repo: Path, branch: str, prompt_rel: str) -> str:
    lines = [f"Implementation for {branch}", f"Task prompt: {prompt_rel}", ""]
    for record in state.stages:
        lines.append(f"  {record.name}: {record.status} ({record.agent}, {record.model})")
    files = git.changed_files(repo, "main")
    if files:
        lines.append("")
        lines.append(f"Changed files ({len(files)}):")
        lines.extend(f"  {name}" for name in files[:50])
    return "\n".join(lines)


def _record_pr(state: RunState, repo: Path, record) -> None:
    text = _read_out(record) or ""
    match = _PR_URL.search(text)
    if match:
        state.pr = {**state.pr, "number": int(match.group(1)), "url": match.group(0)}
    state.pr["changed_files"] = git.changed_files(repo, "main")


def _write_artifacts(directory: Path, state: RunState, branch: str) -> Path:
    artifacts_dir = directory / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "branch": branch,
        "pr_number": state.pr.get("number"),
        "pr_url": state.pr.get("url"),
        "build_results_path": f"docs/implementation-results/{branch}/build-results.md",
        "changed_files": state.pr.get("changed_files", []),
    }
    path = artifacts_dir / "implementation.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def run(
    *,
    task_prompt_path: Path,
    repo: Path,
    aidt: Path,
    pr: int | None = None,
    resume: bool = False,
    from_stage: str | None = None,
    parallel: bool = False,
    approve_all: bool = False,
    skip_gates: list[str] | None = None,
    deny_gates: list[str] | None = None,
    gate_default: str | None = None,
    strict: bool = False,
    dry_run: bool = False,
    stream: bool = False,
) -> int:
    skip = set(skip_gates or [])
    deny = set(deny_gates or [])
    runs_dir = aidt / "runs"

    # --- resolve the task prompt and derive the task id --------------------- #
    raw_path = Path(task_prompt_path)
    if not raw_path.is_absolute():
        raw_path = repo / raw_path
    prompt_path = raw_path.resolve()
    if not prompt_path.is_file():
        print(f"task prompt not found: {prompt_path}", file=sys.stderr)
        return 2
    try:
        prompt_rel = prompt_path.relative_to(repo).as_posix()
    except ValueError:
        print(
            f"task prompt must live inside the repository: {prompt_path}",
            file=sys.stderr,
        )
        return 2

    parsed = parse_task_id(prompt_path)
    if parsed is None:
        print(
            f"cannot derive a task id from prompt filename: {prompt_path.name}",
            file=sys.stderr,
        )
        return 2
    phase, task, branch_name = parsed
    task_id = f"{phase}-{task}"

    # --- agents/config ---------------------------------------------------------- #
    agents, issues = load_all(aidt, repo)
    errors = [i for i in issues if i.level == ERROR]
    warnings = [i for i in issues if i.level == WARNING]
    if errors or (strict and warnings):
        print(format_issues(errors + (warnings if strict else [])), file=sys.stderr)
        return 2

    branch = git.current_branch(repo)
    existing = _latest_implement_run(runs_dir, branch_name)

    # --- preflight ---------------------------------------------------------- #
    if not dry_run:
        if branch is None or branch == "main":
            print("`aidw implement` must not run on `main`.", file=sys.stderr)
            return 4
        if branch != branch_name:
            print(
                f"branch mismatch: on `{branch}` but the task id says `{branch_name}`. "
                "check out the task branch first.",
                file=sys.stderr,
            )
            return 4
        if existing is not None and existing.status == RUNNING and not resume:
            print(
                f"another implement run for `{branch_name}` is still marked running: "
                f"{existing.run_id}. Use --resume or finish it.",
                file=sys.stderr,
            )
            return 4

    # --- run state (new or resumed) ----------------------------------------- #
    if resume and not dry_run:
        if existing is None:
            print(f"no implement run to resume for `{branch_name}`.", file=sys.stderr)
            return 2
        state = existing
        directory = run_dir(runs_dir, state.run_id)
        logger = RunLogger(directory, stream=stream)
        print(f"resume: {state.run_id}")
        print("completed stages:")
        _print_completed(state)
        if not _confirm_resume(approve_all):
            print("resume declined.", file=sys.stderr)
            return 4
    else:
        state = create_run(
            runs_dir,
            repo,
            "implement",
            label=branch_name,
            task={"phase": phase, "task": task, "prompt_path": prompt_rel},
            strict=strict,
            branch=branch_name,
        )
        if pr is not None:
            state.pr = {**state.pr, "number": pr}
        directory = run_dir(runs_dir, state.run_id)
        logger = RunLogger(directory, stream=stream)
        save(directory, state)

    logger.info(f"implement workflow {task_id}: {prompt_rel}")
    print(f"run:    {state.run_id}")
    print(f"branch: {branch_name}")
    print(f"prompt: {prompt_rel}")

    plan = build_plan(aidt=aidt, prompt_rel=prompt_rel, branch=branch_name, task_id=task_id)
    pre_pr = plan[:-1]
    pr_plan = plan[-1]

    # --- dry run: plan every stage, no Pi, no git/GitHub writes -------------- #
    if dry_run:
        for entry in plan:
            record = run_stage(
                entry.spec(aidt),
                repo_root=repo,
                aidt_root=aidt,
                state=state,
                logger=logger,
                agents=agents,
                dry_run=True,
            )
            print(f"{entry.id} {record.name} [{record.status}] (planned) "
                  f"agent={record.agent} model={record.model}")
        print(f"gate (planned): {GATE}")
        state.status = SUCCEEDED
        save(directory, state)
        print("dry-run complete; Pi not invoked")
        return 0

    # --- stage selection (resume / --from) ---------------------------------- #
    names = [entry.name for entry in plan]
    from_index: int | None = None
    if from_stage is not None:
        if from_stage not in names:
            print(
                f"unknown stage `{from_stage}` (expected one of {', '.join(names)})",
                file=sys.stderr,
            )
            return 2
        from_index = names.index(from_stage)
        logger.info(f"--from {from_stage}: re-running from {names[from_index]}")

    def should_run(index: int, name: str) -> bool:
        if from_index is not None and index >= from_index:
            return True
        record = state.stage(name)
        return not (record is not None and record.status == SUCCEEDED)

    # --- I1..I5 -------------------------------------------------------------- #
    def execute(entry: PlanStage, index: int) -> bool:
        """Run one stage unless it already succeeded; return its success."""
        if not should_run(index, entry.name):
            print(f"stage:  {entry.id} {entry.name} [skipped]")
            return True
        record = run_stage(
            entry.spec(aidt),
            repo_root=repo,
            aidt_root=aidt,
            state=state,
            logger=logger,
            agents=agents,
        )
        print_stage(record, repo_root=repo, prefix=entry.id)
        if record.status != SUCCEEDED:
            print(f"stage {entry.name} failed: {record.error}", file=sys.stderr)
            state.status = FAILED
            state.resume = {"next_stage": entry.name}
            save(directory, state)
            return False
        return True

    index_of = {entry.name: index for index, entry in enumerate(pre_pr)}
    by_name = {entry.name: entry for entry in pre_pr}

    if parallel:
        # The one pair docs/workflow.md calls safe to parallelize: /test writes package
        # tests, /update-architecture writes docs/architecture/**. They share no files,
        # so they may run concurrently in the same working tree. The run-state writes are
        # serialized inside run_stage.
        logger.info("--parallel: running test and update-architecture concurrently")
        if not execute(by_name["impliment-task"], index_of["impliment-task"]):
            return 1
        pair = [by_name["test"], by_name["update-architecture"]]
        active = [entry for entry in pair if should_run(index_of[entry.name], entry.name)]
        for entry in pair:
            if entry not in active:
                print(f"stage:  {entry.id} {entry.name} [skipped]")
        failed = False
        if active:
            with ThreadPoolExecutor(max_workers=len(active)) as pool:
                futures = {
                    pool.submit(
                        run_stage,
                        entry.spec(aidt),
                        repo_root=repo,
                        aidt_root=aidt,
                        state=state,
                        logger=logger,
                        agents=agents,
                    ): entry
                    for entry in active
                }
                for future in as_completed(futures):
                    entry = futures[future]
                    record = future.result()
                    print_stage(record, repo_root=repo, prefix=entry.id)
                    if record.status != SUCCEEDED:
                        print(
                            f"stage {entry.name} failed: {record.error}",
                            file=sys.stderr,
                        )
                        failed = True
        if failed:
            state.status = FAILED
            save(directory, state)
            return 1
        for name in ("update-traceability", "record-implementation-results"):
            if not execute(by_name[name], index_of[name]):
                return 1
    else:
        for index, entry in enumerate(pre_pr):
            if not execute(entry, index):
                return 1

    # --- gate ---------------------------------------------------------------- #
    approved = any(g.name == GATE and g.decision == "approved" for g in state.gates)
    if approved:
        print(f"gate:   {GATE} [already approved]")
    else:
        summary = _gate_summary(state, repo, branch_name, prompt_rel)
        outcome = decide(
            GATE,
            summary,
            approve_all=approve_all,
            skip=skip,
            deny=deny,
            gate_default=gate_default,
        )
        state.record_gate(
            GateRecord(
                name=GATE,
                decision=outcome.decision,
                mechanism=outcome.mechanism,
                at=utcnow_iso(),
            )
        )
        save(directory, state)
        if not outcome.approved:
            state.status = BLOCKED
            save(directory, state)
            print(
                f"gate {GATE} denied ({outcome.mechanism}); stopping.",
                file=sys.stderr,
            )
            return 3
        print(f"gate:   {GATE} [{outcome.mechanism}]")

    # --- I6 ------------------------------------------------------------------ #
    if should_run(len(plan) - 1, pr_plan.name):
        record = run_stage(
            pr_plan.spec(aidt),
            repo_root=repo,
            aidt_root=aidt,
            state=state,
            logger=logger,
            agents=agents,
        )
        print_stage(record, repo_root=repo, prefix=pr_plan.id)
        if record.status != SUCCEEDED:
            print(f"stage {pr_plan.name} failed: {record.error}", file=sys.stderr)
            return 1
        _record_pr(state, repo, record)
    else:
        print(f"stage:  {pr_plan.id} {pr_plan.name} [skipped]")

    _write_artifacts(directory, state, branch_name)
    state.status = SUCCEEDED
    state.resume = {"next_stage": None}
    save(directory, state)

    print("implement workflow complete")
    print(f"branch: {branch_name}")
    if state.pr.get("url"):
        print(f"pr:     {state.pr['url']}")
    return 0
