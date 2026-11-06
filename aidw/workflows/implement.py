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
…  any repo-added stages the repo declared before / after I6 (E4.5b)
```

``--parallel`` runs the target config's ``workflows.implement.parallel_groups``
(EXTRACTION.md §3.4/§3.5, R11): each group's members run concurrently at the position of
the group's earliest member, every non-member keeps registry order, and the registry
default is the one pair known to be safe — ``I2 test`` and ``I4 update-architecture``,
which touch disjoint trees. Without ``--parallel``, or with a declared
``parallel_groups: []``, every stage runs serially. The effective groups are validated in
the preflight (§3.5: every member exists and is not ordered against another member); an
invalid list is a config refusal (stderr + exit 2) before any run record or worktree.

The six stages are not hardcoded here since E4.3: ``run()`` builds them with
:func:`aidw.runner.plan_stages` over the ``aidw.stage_registry`` defaults, so the target
repo's per-stage ``prompt:`` overlay applies and the prompts resolve against the located
worktree (EXTRACTION.md §3.5, D2/D14). The target config's two fail-closed preflight
refusals run first, sharing :func:`aidw.target_config.resolve_workflow_config` with the
other four workflows. The same preflight validates a **declared**
``workflows.implement.stages`` list (E4.5a, D12/D13): disabling, removing or reordering a
core stage is one ``ERROR`` per violation (stderr + exit 2, before any run record or
worktree), while a repo-optional ``enabled: false`` and a repo-added stage are accepted.

Branch setup is a Python stage: ``run()`` derives the branch/worktree name from
``repo.branch_pattern`` and **locates** the existing worktree (``git.worktree_for_branch``,
EXTRACTION.md §3.2) — ``aidw prompt`` (E2.5) is what creates it and commits the task
prompt inside it. When the worktree is missing, ``run()`` prints the exact ``worktree
add`` command and refuses (exit 4, design §14) without creating anything. The located
worktree is re-resolved into the target and agents so every stage runs in it. It no
longer refuses to run on ``main`` or on a branch that does not match the task id, but
still refuses when another implement run for the branch is marked ``running`` unless
``--resume``.

The run lock (``aidw.lock``, EXTRACTION.md §3.2/§3.10) is keyed on the **located
worktree path**, acquired immediately before ``create_run`` and released on every exit
path (success, stage/gate failure, and the post-acquire refusals). A live peer in the
same worktree is refused with exit 4 and writes no run state. ``--dry-run`` reaches
``create_run`` too, so it holds and releases the same lock.
"""

from __future__ import annotations

import json
import os
import re
import string
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

from aidw import __version__, git, lock
from aidw import stage_registry
from aidw.config import ERROR, WARNING, format_issues, load_all
from aidw.gates import decide
from aidw.log import RunLogger
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.report import print_stage
from aidw.runner import StageSpec, declared_stage_issues, plan_stages, run_stage
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
from aidw.target_config import (
    SOURCE_CONFIG,
    ResolvedConfig,
    agent_configs_override,
    config_identity,
    resolve_workflow_config,
)

GATE = "approve-implementation-pr"

#: The resolved §3.4 path of the config-driven parallel groups (R11/E4.4).
PARALLEL_GROUPS_PATH = "workflows.implement.parallel_groups"

#: The resolved §3.4 path of the declared stage list (D12/D13, E4.5a).
STAGES_PATH = "workflows.implement.stages"

#: ``03-E4.1-prompt.md`` → phase ``03``, task ``E4.1``, branch ``03-E4.1``.
_PROMPT_NAME = re.compile(
    r"^(?P<phase>[0-9]+(?:\.[0-9]+)?)-(?P<task>.+?)(?:-prompt)?\.md$"
)

_PR_URL = re.compile(r"https?://\S*/pull/(\d+)")


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
) -> list[stage_registry.PlannedStage]:
    """The six stages, in order, exactly as the registry expands them (compat wrapper).

    ``base_branch`` is I4's ``$2`` (``base_ref``): the architecture stage measures
    against the configured PR base, not a hardcoded ``main`` (EXTRACTION.md §3.4/R4).

    Since E4.3 this is a thin wrapper over :func:`aidw.stage_registry.expand`, kept for the
    one caller that needs only the stage **names** before the target config is resolved and
    the prompt located (``run``'s ``--from`` validation). It is deliberately *not* on the
    ``implement`` run path: ``run`` builds its stages with
    :func:`aidw.runner.plan_stages`, so a repo's ``prompt:`` override (D14) applies and the
    prompts resolve against the target repo rather than the toolkit unconditionally.
    ``aidt`` is accepted and unused now that the plan carries prompt *names*: keeping it
    keeps every existing call site (and its ``aidt=`` argument) working.
    """
    return list(
        stage_registry.expand(
            "implement",
            prompt_rel=prompt_rel,
            branch=branch,
            task_id=task_id,
            base_branch=base_branch,
        )
    )


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


def effective_parallel_groups(
    config: ResolvedConfig | None,
) -> tuple[tuple[str, ...], ...]:
    """The groups ``--parallel`` schedules: the repo's declared list, else the default (E4.4).

    Declared-ness decides, never value equality (matching :func:`resolve_config`'s
    whole-list semantics): a config that declares ``parallel_groups: []`` resolves with
    ``source == "config"`` and means "no parallel groups" — serial, never a fallback to
    the default. When the config did not declare the list the entry is **absent** from the
    resolved config (not an ``unset`` entry), and the registry default (E4.1's
    ``(('test', 'update-architecture'),)``) applies. Members are stage *names* (R6/R11),
    which is what the ``by_name``/``index_of`` lookups below key on.

    Pure; ``config`` is ``None`` only for a caller that has not resolved one — the
    preflight refuses before that can happen — and then the registry default is used.
    """
    entry = None if config is None else config.get(PARALLEL_GROUPS_PATH)
    if entry is None or entry.source != SOURCE_CONFIG:
        return stage_registry.get_workflow("implement").parallel_groups
    return tuple(tuple(group) for group in (entry.value or []))


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

    # --- target config (E4.3, EXTRACTION.md §3.4/§3.11, D10) --------------------- #
    # The first two of `aidw prompt`'s config refusals, at the same site and with the same
    # contract: stderr + exit 2, before the locate and before any run record or worktree,
    # `--dry-run` included. The resolved config is what `plan_stages` needs for the
    # per-stage `prompt:` overlay (D14); a repo with no `aidw/config.yaml` resolves the
    # toolkit defaults and plans exactly as before. `validate_paths` stays prompt-only:
    # its read-paths (`roadmap_dir`, the build-results template) need not exist in an
    # implement tree, and a missing one surfaces fail-closed at the stage that reads it.
    resolved_config, config_issues = resolve_workflow_config(
        repo.root, toolkit_version=__version__
    )
    if config_issues:
        print(format_issues(config_issues), file=sys.stderr)
        return 2

    # --- parallel groups (E4.4, EXTRACTION.md §3.5, R11) ------------------------ #
    # Validate the *effective* groups (the repo's declared list or the registry default)
    # immediately after the config resolution, before any run record, worktree or stage —
    # and in `--dry-run` too: a broken group list is a config error either way, with the
    # same stderr + exit 2 contract as the two refusals above. `parallel_groups: []` (the
    # empty list of groups) is valid and means serial; an empty *inner* group is not.
    parallel_groups = effective_parallel_groups(resolved_config)
    group_issues = stage_registry.validate_parallel_groups("implement", parallel_groups)
    if group_issues:
        print(format_issues(group_issues), file=sys.stderr)
        return 2

    # --- core vs repo-optional stages (E4.5a, D12/D13, EXTRACTION.md §3.5) ------ #
    # A declared list **replaces** the registry's list wholesale (§3.4), so a repo that
    # omits a core stage has removed it; validate that list right after the config
    # resolution and the E4.4 groups, before `load_all`, any run record or worktree, and
    # in `--dry-run`: a D12/D13 violation is a config error either way, with the same
    # stderr + exit 2 contract as the refusals above. Declared-ness, never value
    # equality, decides (matching `effective_parallel_groups`): an undeclared list is
    # absent from the resolved config and the registry defaults plan unchanged, while an
    # explicit `stages: []` carries `source == "config"` and reports every core stage
    # removed.
    stages_entry = resolved_config.get(STAGES_PATH)
    if stages_entry is not None and stages_entry.source == SOURCE_CONFIG:
        stage_issues = stage_registry.validate_stage_list(
            "implement", stages_entry.value or []
        )
        if stage_issues:
            print(format_issues(stage_issues), file=sys.stderr)
            return 2

    # --- agents/config ---------------------------------------------------------- #
    # Config validation stays in the preflight, before the locate: a combined
    # bad-config-plus-missing-worktree run is a usage/config error (exit 2, design §14),
    # not a preflight refusal (exit 4).
    # E4.6: a declared `paths.agent_configs_dir` is target-repo configuration, resolved
    # against the control root here and re-resolved against the worktree below — the same
    # tree the stages run in. Unset (the toolkit default) passes `None`, so the toolkit's
    # own `agent-configs/` is used and nothing about a repo without overrides changes.
    agents, issues = load_all(
        aidt.root,
        repo.root,
        override_dir=agent_configs_override(resolved_config, repo.root),
    )
    errors = [i for i in issues if i.level == ERROR]
    warnings = [i for i in issues if i.level == WARNING]
    if errors or (strict and warnings):
        print(format_issues(errors + (warnings if strict else [])), file=sys.stderr)
        return 2

    # --- declared stage settings (E4.5b, EXTRACTION.md §3.5/§3.6) --------------- #
    # After `load_all`, because the agents dict is what a repo-added stage's `agent` is
    # checked against — the validator above runs before it. `validate_stage_list` stays
    # the first stage-list refusal; this one covers the two settings the plan needs and
    # turns them into config ERRORs (stderr + exit 2) before the locate, any run record or
    # worktree, and in `--dry-run`, so a missing declared prompt or an unknown repo-added
    # agent never escapes `run()` as a traceback. Control-root only: the worktree reload
    # below keeps its own `load_all` refusal and, like `validate_stage_list`, is not re-run.
    if stages_entry is not None and stages_entry.source == SOURCE_CONFIG:
        declaration_issues = declared_stage_issues(
            "implement",
            stages_entry.value or [],
            toolkit_root=aidt.root,
            target_root=repo.root,
            agents=agents,
        )
        if declaration_issues:
            print(format_issues(declaration_issues), file=sys.stderr)
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
    # with exit 2 and leaves behind no run directory. ``build_plan`` is the registry
    # expansion (pure); the real ``prompt_rel`` is resolved after the locate and the
    # run-path plan is built with it by ``plan_stages``.
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
    # Inline Python, not a plan stage: I1..I6 stay the exact six stage ids (§3.5), and a
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
        agents, issues = load_all(
            aidt.root,
            target.root,
            override_dir=agent_configs_override(resolved_config, target.root),
        )
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

    # The run-path plan: the registry's six stages mapped to specs through `resolve_prompt`,
    # with the repo's `prompt:` overlay applied (E4.3). Prompts resolve against the tree the
    # stages run in — the located worktree. A dry run with no worktree has no such tree yet,
    # so it plans against the control root instead (the same fallback review/fix document):
    # resolving against the planned-but-absent path would make every repo-declared `prompt:`
    # fail closed in every dry run, a state the real run never sees.
    plan_root = worktree_root if (worktree is not None or not dry_run) else repo.root
    plan = plan_stages(
        "implement",
        config=resolved_config,
        toolkit_root=aidt.root,
        target_root=plan_root,
        prompt_rel=prompt_rel,
        branch=branch_name,
        task_id=task_id,
        base_branch=repo.base_branch,
    )
    # I6 is the PR stage, located **by id** (E4.5b): a declared list may carry repo-added
    # stages before or after it, so a positional ``plan[:-1]``/``plan[-1]`` split would
    # mistake a trailing stage for the PR stage (or drop it). Everything before I6 is the
    # pre-PR block the gate sits behind; everything after it runs once I6 succeeded.
    pr_index = next(
        index for index, spec in enumerate(plan) if spec.id == "I6"
    )
    pre_pr = plan[:pr_index]
    pr_plan = plan[pr_index]
    post_pr = plan[pr_index + 1 :]

    # --- one run per worktree (EXTRACTION.md §3.2/§3.10, E2.7) ---------------- #
    # The key is the *resolved* worktree path -- ``target.root``, the same value
    # ``create_run`` records as ``repo_root`` -- never the branch: a detached-HEAD
    # worktree has no branch, and §3.2 says "keyed by worktree path". Acquired
    # immediately before ``create_run`` (the point where the key is final) and released
    # on every exit path below, refusals and failures included, so the worktree cannot
    # stay locked until process exit. It lives in the state root, never in a target
    # repo or worktree (§3.1), and it is neither ``_STATE_LOCK`` (in-process, per
    # ``state.json`` write) nor ``--parallel`` (concurrent stages inside one run).
    # A dry run reaches this line too (``create_run`` writes ``state.json``
    # unconditionally), so it holds and releases the same lock.
    try:
        run_lock = lock.acquire(workspace.state_root, target.root)
    except lock.LockHeldError as exc:
        print(str(exc), file=sys.stderr)
        return 4

    try:
        # --- run state (new or resumed) ----------------------------------------- #
        # A resumed run was confirmed above, before the worktree locate and this write.
        if resume and not dry_run:
            state = existing
            directory = run_dir(runs_root, state.run_id)
            logger = RunLogger(directory, stream=stream)
        else:
            # EXTRACTION.md §3.11 (E8.2): what produced this run. One helper so the
            # five workflows cannot record different values for one config.
            config_schema_version, config_hash = config_identity(resolved_config)
            state = create_run(
                runs_root,
                target.root,
                "implement",
                label=branch_name,
                task={"phase": phase, "task": task, "prompt_path": prompt_rel},
                strict=strict,
                branch=branch_name,
                toolkit_version=__version__,
                config_schema_version=config_schema_version,
                config_hash=config_hash,
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
                    entry,
                    repo_root=target.root,
                    toolkit_root=aidt.root,
                    runs_root=runs_root,
                    state=state,
                    logger=logger,
                    agents=agents,
                    dry_run=True,
                    config=resolved_config,
                )
                print(f"{entry.id} {record.name} [{record.status}] (planned) "
                      f"agent={record.agent} model={record.model}")
            print(f"gate (planned): {GATE}")
            state.status = SUCCEEDED
            save(directory, state)
            print("dry-run complete; Pi not invoked")
            return 0

        # --- stage selection (resume / --from) ---------------------------------- #
        # ``from_stage`` was validated against the registry names before branch setup;
        # the log line waits for the run's logger to exist. Its index is re-derived from
        # the run-path plan (E4.5b): ``should_run`` compares full-plan positions, and a
        # repo-added stage declared before the named one shifts them, so the registry-name
        # index would re-run the wrong stages. ``from_stage`` is always a registry name,
        # so it is present in the plan.
        if from_stage is not None:
            plan_names = [spec.name for spec in plan]
            if from_stage in plan_names:
                from_index = plan_names.index(from_stage)
                logger.info(f"--from {from_stage}: re-running from {from_stage}")
            else:
                # The named stage is not in this run's plan — a repo-optional stage the
                # repo disabled, or one `build_plan` knows but the declared list dropped.
                # Nothing to re-run from, so every stage keeps its own succeeded-skip
                # decision instead of crashing on a missing position.
                from_index = None
                logger.info(f"--from {from_stage}: stage is not in this run's plan")

        def should_run(index: int, name: str) -> bool:
            if from_index is not None and index >= from_index:
                return True
            record = state.stage(name)
            return not (record is not None and record.status == SUCCEEDED)

        # --- I1..I5 -------------------------------------------------------------- #
        def execute(entry: StageSpec, index: int) -> bool:
            """Run one stage unless it already succeeded; return its success."""
            if not should_run(index, entry.name):
                print(f"stage:  {entry.id} {entry.name} [skipped]")
                return True
            record = run_stage(
                entry,
                repo_root=target.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
                config=resolved_config,
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
            # The config-driven groups (E4.4, R11). Every member of a group runs
            # concurrently at the position of the group's *earliest* member (registry
            # order), and every non-member stage keeps its registry order — so the default
            # pair still schedules I1 → {I2, I4} → I3 → I5 → I6. The preflight proved each
            # member exists and is not ordered against another member; file-ownership
            # safety is the repo's declaration, not something the toolkit infers (R11),
            # and the groups must still touch disjoint trees because every member runs in
            # the same working tree. ``pr`` (I6) is the post-gate sync point and always
            # runs alone below, so a group naming it only schedules its other members.
            # Run-state writes are serialized inside ``run_stage`` (``_STATE_LOCK``).
            logger.info(
                "--parallel: groups: "
                + (
                    "; ".join(", ".join(group) for group in parallel_groups)
                    or "none (every stage serially)"
                )
            )
            group_of: dict[str, int] = {}
            for group_index, group in enumerate(parallel_groups):
                for member in group:
                    group_of.setdefault(member, group_index)
            handled: set[str] = set()
            for index, entry in enumerate(pre_pr):
                if entry.name in handled:
                    continue
                group_index = group_of.get(entry.name)
                if group_index is None:
                    if not execute(entry, index):
                        return 1
                    continue
                # This stage is its group's earliest pre-PR member: run the whole group
                # here. Members that already succeeded are reported and left out of the
                # pool, exactly as the serial path skips them (resume/--from).
                members = [
                    by_name[name]
                    for name in parallel_groups[group_index]
                    if name in by_name
                ]
                handled.update(member.name for member in members)
                active = [
                    member
                    for member in members
                    if should_run(index_of[member.name], member.name)
                ]
                for member in members:
                    if member not in active:
                        print(f"stage:  {member.id} {member.name} [skipped]")
                if not active:
                    continue
                failed: list[StageSpec] = []
                with ThreadPoolExecutor(max_workers=len(active)) as pool:
                    futures = {
                        pool.submit(
                            run_stage,
                            member,
                            repo_root=target.root,
                            toolkit_root=aidt.root,
                            runs_root=runs_root,
                            state=state,
                            logger=logger,
                            agents=agents,
                        ): member
                        for member in active
                    }
                    for future in as_completed(futures):
                        member = futures[future]
                        record = future.result()
                        print_stage(record, repo_root=target.root, prefix=member.id)
                        if record.status != SUCCEEDED:
                            print(
                                f"stage {member.name} failed: {record.error}",
                                file=sys.stderr,
                            )
                            failed.append(member)
                if failed:
                    # The earliest failed member in registry order (not whichever the pool
                    # happened to finish first), so the resume hint is deterministic. No
                    # later stage runs: the same failure contract as the serial path.
                    first = min(failed, key=lambda item: index_of[item.name])
                    state.status = FAILED
                    state.resume = {"next_stage": first.name}
                    save(directory, state)
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
        # I6's own plan index (E4.5b): ``len(plan) - 1`` is only I6 when nothing is
        # declared after it, so a trailing repo-added stage would make the skip/resume test
        # ask about the wrong stage.
        if should_run(pr_index, pr_plan.name):
            record = run_stage(
                pr_plan,
                repo_root=target.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
                config=resolved_config,
            )
            print_stage(record, repo_root=target.root, prefix=pr_plan.id)
            if record.status != SUCCEEDED:
                print(f"stage {pr_plan.name} failed: {record.error}", file=sys.stderr)
                return 1
            _record_pr(state, target, record)
        else:
            print(f"stage:  {pr_plan.id} {pr_plan.name} [skipped]")

        # --- stages declared after I6 (E4.5b) ------------------------------------- #
        # After a successful (or skipped-because-resumed) I6 only: a denied gate returns 3
        # and a failed I6 returns 1 above, so nothing declared after I6 runs on either —
        # exactly as a trailing stage did not exist before E4.5b. They run in declared
        # order under the same ``should_run`` skip, at their full-plan positions.
        for offset, spec in enumerate(post_pr, start=1):
            if not should_run(pr_index + offset, spec.name):
                print(f"stage:  {spec.id} {spec.name} [skipped]")
                continue
            record = run_stage(
                spec,
                repo_root=target.root,
                toolkit_root=aidt.root,
                runs_root=runs_root,
                state=state,
                logger=logger,
                agents=agents,
                config=resolved_config,
            )
            print_stage(record, repo_root=target.root, prefix=spec.id)
            if record.status != SUCCEEDED:
                print(f"stage {spec.name} failed: {record.error}", file=sys.stderr)
                state.status = FAILED
                state.resume = {"next_stage": spec.name}
                save(directory, state)
                return 1

        _write_artifacts(directory, state, branch_name)
        state.status = SUCCEEDED
        state.resume = {"next_stage": None}
        save(directory, state)

        print("implement workflow complete")
        print(f"branch: {branch_name}")
        if state.pr.get("url"):
            print(f"pr:     {state.pr['url']}")
        return 0
    finally:
        run_lock.release()
