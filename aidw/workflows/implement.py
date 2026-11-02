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

Branch setup is a Python stage: ``run()`` derives the branch/worktree name from
``repo.branch_pattern`` and **locates** the existing worktree (``git.worktree_for_branch``,
EXTRACTION.md §3.2) — ``aidw prompt`` (E2.5) is what creates it and commits the task
prompt inside it. When the worktree is missing, ``run()`` prints the exact ``worktree
add`` command and refuses (exit 4, design §14) without creating anything. The located
worktree is re-resolved into the target and agents so every stage runs in it. It no
longer refuses to run on ``main`` or on a branch that does not match the task id, but
still refuses when another implement run for the branch is marked ``running`` unless
``--resume``.
"""

from __future__ import annotations

import json
import os
import re
import string
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from pathlib import Path

from aidw import git
from aidw.config import ERROR, WARNING, format_issues, load_all
from aidw.gates import decide
from aidw.log import RunLogger
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
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


def worktree_add_command(
    workspace: WorkspacePaths, branch: str, base_branch: str
) -> str:
    """The copy-pasteable §3.2 per-task worktree command (E2.6 req 4).

    Prompt-fixed to §3.2's per-task command with ``base_branch`` substituted for the
    literal ``main``: ``-C`` points at the base-branch worktree, so the new worktree is
    linked off the configured base. ``workspace.workspace_root`` is absolute, so every
    path in the returned string is absolute and the line can be pasted as-is.
    """
    root = workspace.workspace_root
    return (
        f"git -C {root / base_branch} worktree add -b {branch} "
        f"{root / branch} {base_branch}"
    )


def _resolve_prompt_argument(
    task_prompt_path: Path, control_root: Path, worktree_root: Path
) -> tuple[Path, str] | None:
    """Resolve the task-prompt argument inside the task worktree (E2.6 req 2).

    Returns ``(prompt_path, prompt_rel)`` where ``prompt_rel`` is the repo-relative
    subpath used by I1 and I5, or ``None`` when an absolute argument lives inside
    neither the control root nor the worktree (a usage error). Three argument shapes:

    * relative — a repo-relative subpath, resolved against ``worktree_root`` (never the
      control root or the cwd);
    * absolute under the control root — re-based by its repo-relative subpath;
    * absolute under the worktree root — resolved as-is (what the chain hands over).

    Pure apart from ``Path.resolve`` on the arguments; no file existence check here
    (the caller owns the real-run-only ``is_file`` refusal).
    """
    raw = Path(task_prompt_path)
    if not raw.is_absolute():
        rel = Path(os.path.normpath(raw))
        candidate = (worktree_root / rel).resolve()
        try:
            candidate.relative_to(worktree_root.resolve())
        except ValueError:
            return None
        return candidate, rel.as_posix()
    resolved = raw.resolve()
    control = control_root.resolve()
    worktree = worktree_root.resolve()
    try:
        rel = resolved.relative_to(control)
    except ValueError:
        pass
    else:
        return (worktree / rel).resolve(), rel.as_posix()
    try:
        rel = resolved.relative_to(worktree)
    except ValueError:
        return None
    return resolved, rel.as_posix()


def parse_task_id(prompt_path: Path) -> tuple[str, str, str] | None:
    """Derive ``(phase, task, task_id)`` from a task-prompt filename.

    Pure: one argument, no I/O. The third element is the task id ``f"{phase}-{task}"``;
    the *branch* name is ``repo.branch_pattern`` applied to it by :func:`run`. Accepts the
    canonical ``<phase>-<task>-prompt.md`` and the bare ``<phase>-<task>.md`` an author
    model may produce. Returns ``None`` when the filename carries no task id.
    """
    match = _PROMPT_NAME.match(prompt_path.name)
    if not match:
        return None
    phase = match.group("phase")
    task = match.group("task")
    return phase, task, f"{phase}-{task}"


def _branch_pattern_fields(pattern: str) -> set[str]:
    """Top-level replacement field names referenced by ``pattern``.

    ``string.Formatter().parse`` lets :func:`derive_branch_name` check "mentions both
    ``phase`` and ``task``" without formatting, and never raises on an arbitrary
    placeholder (unlike ``str.format``, which would). ````phase.foo```` / ``task[0]``
    still reference ``phase`` / ``task``.
    """
    fields: set[str] = set()
    for _literal, field_name, _spec, _conversion in string.Formatter().parse(pattern):
        if field_name:
            fields.add(re.split(r"[.\[]", field_name, maxsplit=1)[0])
    return fields


def derive_branch_name(pattern: str, *, phase: str, task: str) -> str | None:
    """Apply ``repo.branch_pattern`` to a task id (EXTRACTION.md §3.4), or ``None``.

    ``None`` means the pattern is malformed — ``str.format`` cannot apply it (unknown
    placeholder, unbalanced braces) or it does not reference both ``phase`` and
    ``task`` (a constant/partial name would collide across tasks; §3.2 one branch, one
    worktree). The caller turns ``None`` into a usage error (exit 2) before any worktree
    or stage. Under the §3.4 default this reproduces the old names byte-for-byte.
    """
    try:
        fields = _branch_pattern_fields(pattern)
    except ValueError:
        # Unbalanced braces; ``str.format`` would raise the same.
        return None
    if not {"phase", "task"} <= fields:
        return None
    try:
        return pattern.format(phase=phase, task=task)
    except (KeyError, IndexError, ValueError):
        return None


def build_plan(
    *, aidt: Path, prompt_rel: str, branch: str, task_id: str, base_branch: str = "main"
) -> list[PlanStage]:
    """The six stages, in order (I6 is the ``pr`` stage).

    ``base_branch`` is I4's ``$2`` (``base_ref``): the architecture stage measures
    against the configured PR base, not a hardcoded ``main`` (EXTRACTION.md §3.4/R4).
    """
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
            [branch, base_branch],
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


def _latest_implement_run(runs_root: Path, branch: str) -> RunState | None:
    matches = [
        state
        for state in list_runs(runs_root)
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


def _gate_summary(state: RunState, repo: TargetRepo, branch: str, prompt_rel: str) -> str:
    lines = [f"Implementation for {branch}", f"Task prompt: {prompt_rel}", ""]
    for record in state.stages:
        lines.append(f"  {record.name}: {record.status} ({record.agent}, {record.model})")
    files = git.changed_files(repo.root, repo.base_branch)
    if files:
        lines.append("")
        lines.append(f"Changed files ({len(files)}):")
        lines.extend(f"  {name}" for name in files[:50])
    return "\n".join(lines)


def _record_pr(state: RunState, repo: TargetRepo, record) -> None:
    text = _read_out(record) or ""
    match = _PR_URL.search(text)
    if match:
        state.pr = {**state.pr, "number": int(match.group(1)), "url": match.group(0)}
    state.pr["changed_files"] = git.changed_files(repo.root, repo.base_branch)


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
    repo: TargetRepo,
    aidt: ToolkitPaths,
    workspace: WorkspacePaths,
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
    runs_root = workspace.state_root / "runs"

    # --- task id + branch (before any side effect) -------------------------- #
    # The task id comes from the filename alone (E2.5 commits the prompt in the task
    # worktree, so the file is not readable from the control root at this point), and
    # the branch is derived from it with the same helper ``aidw prompt`` uses.
    raw_path = Path(task_prompt_path)
    parsed = parse_task_id(raw_path)
    if parsed is None:
        print(
            f"cannot derive a task id from prompt filename: {raw_path.name}",
            file=sys.stderr,
        )
        return 2
    phase, task, task_id = parsed
    branch_name = derive_branch_name(repo.branch_pattern, phase=phase, task=task)
    if branch_name is None:
        print(
            f"malformed repo.branch_pattern {repo.branch_pattern!r}: it must be a "
            "format string referencing both `{phase}` and `{task}` "
            '(e.g. "{phase}-{task}").',
            file=sys.stderr,
        )
        return 2

    # --- agents/config ---------------------------------------------------------- #
    # Config validation stays in the preflight, before the locate: a combined
    # bad-config-plus-missing-worktree run is a usage/config error (exit 2, design §14),
    # not a preflight refusal (exit 4).
    agents, issues = load_all(aidt.root, repo.root)
    errors = [i for i in issues if i.level == ERROR]
    warnings = [i for i in issues if i.level == WARNING]
    if errors or (strict and warnings):
        print(format_issues(errors + (warnings if strict else [])), file=sys.stderr)
        return 2

    # --- retained preflight: one live run per branch ------------------------ #
    # The old main/branch-mismatch guards are gone: the task worktree is located, so
    # `aidw implement` no longer requires being on the task branch. The still-running
    # guard stays, checked before the locate, so a refusal creates no run state.
    existing = _latest_implement_run(runs_root, branch_name)
    if existing is not None and existing.status == RUNNING and not resume:
        print(
            f"another implement run for `{branch_name}` is still marked running: "
            f"{existing.run_id}. Use --resume or finish it.",
            file=sys.stderr,
        )
        return 4
    if resume and not dry_run and existing is None:
        print(f"no implement run to resume for `{branch_name}`.", file=sys.stderr)
        return 2

    # --- --from validation (names only; before any lookup) ------------------ #
    # F1 (PR #49 review follow-up): validate `--from` against the planned stage
    # names before the locate and run-state creation, so a typo'd stage name refuses
    # with exit 2 and leaves behind no run directory. ``build_plan`` is pure
    # (constants only); the real ``prompt_rel`` is resolved after the locate and the
    # plan is rebuilt with it.
    names = [
        entry.name
        for entry in build_plan(
            aidt=aidt.root,
            prompt_rel="",
            branch=branch_name,
            task_id=task_id,
            base_branch=repo.base_branch,
        )
    ]
    from_index: int | None = None
    if from_stage is not None:
        if from_stage not in names:
            print(
                f"unknown stage `{from_stage}` (expected one of {', '.join(names)})",
                file=sys.stderr,
            )
            return 2
        from_index = names.index(from_stage)

    # --- resume confirmation (before any side effects) ---------------------- #
    # F2 (PR #49 review follow-up): ask before the locate, so a declined resume
    # leaves behind no run state — the same fail-closed contract as the
    # still-running refusal above.
    if resume and not dry_run:
        print(f"resume: {existing.run_id}")
        print("completed stages:")
        _print_completed(existing)
        if not _confirm_resume(approve_all):
            print("resume declined.", file=sys.stderr)
            return 4

    # --- locate the task worktree (EXTRACTION.md §3.2, E2.6 req 1) ---------- #
    # Inline Python, not a PlanStage: I1..I6 stay the exact six stage ids (§3.5), and a
    # refusal must leave no run state behind. ``aidw prompt`` (E2.5) created the worktree
    # and committed the task prompt inside it; implement only locates it. A missing
    # worktree is a preflight refusal (exit 4, design §14) in a real run; a dry run
    # prints the corrective command as planned output and keeps planning (req 6).
    planned_worktree = (workspace.workspace_root / branch_name).resolve()
    worktree = git.worktree_for_branch(repo.root, branch_name)
    if worktree is None:
        command = worktree_add_command(workspace, branch_name, repo.base_branch)
        if dry_run:
            print(f"worktree (planned): {planned_worktree}")
            print(f"branch-setup (planned): {command}")
            target = repo
            worktree_root = planned_worktree
        else:
            print(
                f"branch-setup refused: no worktree for `{branch_name}`. "
                f"Create it first:\n  {command}",
                file=sys.stderr,
            )
            return 4
    else:
        # Re-resolve the target and agents against the worktree: agent.cwd was resolved
        # against the control root and would silently keep I1..I6 in the wrong worktree.
        resolved = TargetRepo.resolve(worktree)
        target = replace(
            resolved,
            base_branch=repo.base_branch,
            branch_pattern=repo.branch_pattern,
        )
        agents, issues = load_all(aidt.root, target.root)
        reloaded_errors = [i for i in issues if i.level == ERROR]
        reloaded_warnings = [i for i in issues if i.level == WARNING]
        if reloaded_errors or (strict and reloaded_warnings):
            print(
                format_issues(reloaded_errors + (reloaded_warnings if strict else [])),
                file=sys.stderr,
            )
            return 2
        worktree_root = target.root
        if dry_run:
            print(f"worktree (planned): {worktree}")

    # --- resolve the prompt inside the worktree (E2.6 req 2) ---------------- #
    resolved_prompt = _resolve_prompt_argument(raw_path, repo.root, worktree_root)
    if resolved_prompt is None:
        print(
            f"task prompt must live inside the repository: {raw_path}",
            file=sys.stderr,
        )
        return 2
    prompt_path, prompt_rel = resolved_prompt
    # The existence refusal needs the located worktree: a dry run with no worktree plans
    # the re-based path unchecked, but a located worktree still refuses (even in dry-run).
    if not dry_run or worktree is not None:
        if not prompt_path.is_file():
            print(f"task prompt not found: {prompt_path}", file=sys.stderr)
            return 2

    plan = build_plan(
        aidt=aidt.root,
        prompt_rel=prompt_rel,
        branch=branch_name,
        task_id=task_id,
        base_branch=repo.base_branch,
    )
    pre_pr = plan[:-1]
    pr_plan = plan[-1]

    # --- run state (new or resumed) ----------------------------------------- #
    # A resumed run was confirmed above, before the worktree locate and this write.
    if resume and not dry_run:
        state = existing
        directory = run_dir(runs_root, state.run_id)
        logger = RunLogger(directory, stream=stream)
    else:
        state = create_run(
            runs_root,
            target.root,
            "implement",
            label=branch_name,
            task={"phase": phase, "task": task, "prompt_path": prompt_rel},
            strict=strict,
            branch=branch_name,
        )
        if pr is not None:
            state.pr = {**state.pr, "number": pr}
        directory = run_dir(runs_root, state.run_id)
        logger = RunLogger(directory, stream=stream)
        save(directory, state)

    logger.info(f"implement workflow {task_id}: {prompt_rel}")
    print(f"run:    {state.run_id}")
    print(f"branch: {branch_name}")
    print(f"prompt: {prompt_rel}")

    # --- dry run: plan every stage, no Pi, no git/GitHub writes -------------- #
    if dry_run:
        for entry in plan:
            record = run_stage(
                entry.spec(aidt.root),
                repo_root=target.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
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
    # ``from_index`` was validated before branch setup; the log line waits for
    # the run's logger to exist.
    if from_index is not None:
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
            entry.spec(aidt.root),
            repo_root=target.root,
            toolkit_root=aidt.root,
            runs_root=runs_root,
            state=state,
            logger=logger,
            agents=agents,
        )
        print_stage(record, repo_root=target.root, prefix=entry.id)
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
                        entry.spec(aidt.root),
                        repo_root=target.root,
                        toolkit_root=aidt.root,
                        runs_root=runs_root,
                        state=state,
                        logger=logger,
                        agents=agents,
                    ): entry
                    for entry in active
                }
                for future in as_completed(futures):
                    entry = futures[future]
                    record = future.result()
                    print_stage(record, repo_root=target.root, prefix=entry.id)
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
        summary = _gate_summary(state, target, branch_name, prompt_rel)
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
            pr_plan.spec(aidt.root),
            repo_root=target.root,
            toolkit_root=aidt.root,
            runs_root=runs_root,
            state=state,
            logger=logger,
            agents=agents,
        )
        print_stage(record, repo_root=target.root, prefix=pr_plan.id)
        if record.status != SUCCEEDED:
            print(f"stage {pr_plan.name} failed: {record.error}", file=sys.stderr)
            return 1
        _record_pr(state, target, record)
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
