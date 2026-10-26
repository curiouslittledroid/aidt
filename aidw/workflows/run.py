"""``aidw run`` — convenience chains (design §8.6).

- ``task-to-pr <phase> <epic> <task>`` runs ``prompt`` then ``implement`` on the branch
  the prompt workflow creates.
- ``review-and-fix --pr <n>`` runs ``review`` then ``fix``.

Each workflow is a full orchestrator. A chain stops at the first non-zero exit and
returns that code, leaving the state of the completed workflows on disk (resumable with
``aidw implement --resume``).
"""

from __future__ import annotations

import sys
from pathlib import Path

from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.workflows import fix as fix_workflow
from aidw.workflows import implement as implement_workflow
from aidw.workflows import prompt as prompt_workflow
from aidw.workflows import review as review_workflow


def find_task_prompt(repo: Path, phase: str, task: str) -> Path | None:
    """Newest ``docs/task-prompts/<phase>-<task>*.md`` (the author may not use ``-prompt``)."""
    root = repo / "docs" / "task-prompts"
    if not root.is_dir():
        return None
    candidates = sorted(
        root.glob(f"{phase}-{task}*.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def task_to_pr(
    *,
    phase: str,
    epic: str,
    task: str,
    repo: TargetRepo,
    aidt: ToolkitPaths,
    workspace: WorkspacePaths,
    approve_all: bool = False,
    deny_gates: list[str] | None = None,
    gate_default: str | None = None,
    strict: bool = False,
    dry_run: bool = False,
    parallel: bool = False,
    stream: bool = False,
) -> int:
    code = prompt_workflow.run(
        phase=phase,
        epic=epic,
        task=task,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
        approve_all=approve_all,
        deny_gates=deny_gates,
        gate_default=gate_default,
        strict=strict,
        dry_run=dry_run,
        stream=stream,
    )
    if code != 0:
        print(f"chain stopped: `prompt` exited {code}.", file=sys.stderr)
        return code

    if dry_run:
        prompt_path = repo.root / "docs" / "task-prompts" / f"{phase}-{task}-prompt.md"
    else:
        found = find_task_prompt(repo.root, phase, task)
        if found is None:
            print(
                f"chain stopped: no task prompt found for {phase}-{task} after `prompt`.",
                file=sys.stderr,
            )
            return 2
        prompt_path = found

    return implement_workflow.run(
        task_prompt_path=prompt_path,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
        approve_all=approve_all,
        deny_gates=deny_gates,
        gate_default=gate_default,
        strict=strict,
        dry_run=dry_run,
        parallel=parallel,
        stream=stream,
    )


def review_and_fix(
    *,
    pr: int,
    repo: TargetRepo,
    aidt: ToolkitPaths,
    workspace: WorkspacePaths,
    approve_all: bool = False,
    deny_gates: list[str] | None = None,
    gate_default: str | None = None,
    strict: bool = False,
    dry_run: bool = False,
    force_model: bool = False,
    max_iterations: int = 10,
    stream: bool = False,
) -> int:
    code = review_workflow.run(
        pr=pr,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
        approve_all=approve_all,
        strict=strict,
        dry_run=dry_run,
        force_model=force_model,
        stream=stream,
    )
    if code != 0:
        print(f"chain stopped: `review` exited {code}.", file=sys.stderr)
        return code

    print(
        "human action: decide the published follow-up issues on GitHub before the fix "
        "loop; `fix`'s approve-followups gate fails closed unless it is approved."
    )
    return fix_workflow.run(
        pr=pr,
        repo=repo,
        aidt=aidt,
        workspace=workspace,
        max_iterations=max_iterations,
        approve_all=approve_all,
        deny_gates=deny_gates,
        gate_default=gate_default,
        strict=strict,
        dry_run=dry_run,
        force_model=force_model,
        stream=stream,
    )
