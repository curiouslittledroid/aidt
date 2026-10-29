"""Tests for git safety helpers and the prompt workflow (dry-run)."""

from __future__ import annotations

import dataclasses
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aidw import git, state
from aidw.cli import app
from aidw.config import ERROR, Issue
from aidw.paths import ToolkitPaths, TargetRepo, WorkspacePaths, repo_root, toolkit_root
from aidw.prompts import PromptError, render_prompt_file
from aidw.workflows import prompt as prompt_workflow

#: Test-only run label. It keeps test-created runs identifiable and lets the session
#: fixture in ``conftest.py`` delete any that slip past the isolated ``runs_root``.
RUN_LABEL = "pytest"

#: Isolated run-state root, a per-test sibling so it lives outside every worktree
#: (EXTRACTION.md §3.1).
_STATE_DIR_SUFFIX = "-state"


def _roots(
    repo: Path,
    *,
    base_branch: str | None = None,
    branch_pattern: str | None = None,
) -> dict:
    """Typed roots for a direct workflow call, isolated under a per-test state dir.

    ``WorkspacePaths.resolve`` appends the repo slug, so the runs root is
    ``workspace.state_root / "runs"`` — under the override, never at it. The state dir is
    a sibling of ``repo`` so it never dirties the control worktree (design §13).
    """
    target = TargetRepo.resolve(repo)
    if base_branch is not None or branch_pattern is not None:
        overrides = {}
        if base_branch is not None:
            overrides["base_branch"] = base_branch
        if branch_pattern is not None:
            overrides["branch_pattern"] = branch_pattern
        target = dataclasses.replace(target, **overrides)
    return {
        "repo": target,
        "aidt": ToolkitPaths.resolve(),
        "workspace": WorkspacePaths.resolve(
            target, state_dir_override=repo.parent / f"{repo.name}{_STATE_DIR_SUFFIX}"
        ),
    }


def _runs_root(repo: Path) -> Path:
    return _roots(repo)["workspace"].state_root / "runs"


def _task_worktree(repo: Path, branch: str = "03-E4.1") -> Path:
    """The task worktree AIDT creates at ``<workspace_root>/<branch>`` (EXTRACTION.md §3.2)."""
    workspace = git.workspace_root(repo)
    assert workspace is not None, "the fixture must build a real git repository"
    return (workspace / branch).resolve()


def test_git_helpers_types() -> None:
    repo = repo_root()
    assert isinstance(git.is_clean(repo), bool)
    assert git.current_branch(repo) in (None, "ai-dev-workflows", "main") or isinstance(
        git.current_branch(repo), str
    )
    assert isinstance(git.status_short(repo), str)


def test_prompt_workflow_dry_run(tmp_path: Path, monkeypatch, capsys) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(git, "current_branch", lambda repo: "feature-branch")
    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        dry_run=True,
    )
    assert code == 0
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.run_id.endswith("-pytest-prompt")
    assert latest.workflow == "prompt"
    assert [s.name for s in latest.stages] == ["task-prompt", "task-review-1"]
    assert all(s.status == state.SUCCEEDED for s in latest.stages)
    # L5.3 is post-author only; a dry-run never produces a prompt to measure.
    out = capsys.readouterr().out
    assert "budget:" not in out
    # EXTRACTION.md §3.2: the dry run names the planned worktree and the base-branch
    # requirement, but creates no worktree and invokes no stage.
    assert "branch-setup (planned): worktree add -b 03-E4.1" in out
    assert "a real run requires the base branch `main`" in out
    assert not _task_worktree(tmp_path).exists()


def test_prompt_workflow_unknown_task(tmp_path: Path, monkeypatch) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    code = prompt_workflow.run(
        phase="99",
        epic="Z",
        task="Z9",
        **_roots(tmp_path),
        label=RUN_LABEL,
        dry_run=True,
    )
    assert code == 2


def test_prompt_workflow_requires_base_branch_for_real_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """R4: the control guard compares against ``repo.base_branch``, not literal main."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path, base_branch="trunk"),
        label=RUN_LABEL,
        dry_run=False,
    )
    assert code == 4
    assert "must run on the base branch `trunk`" in capsys.readouterr().err
    assert not _task_worktree(tmp_path).exists()


def test_prompt_workflow_requires_clean_tree(tmp_path: Path, monkeypatch) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(git, "current_branch", lambda repo: "main")
    monkeypatch.setattr(git, "is_clean", lambda repo: False)
    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        dry_run=False,
    )
    assert code == 4


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


TASK_REVIEW_CHANGES = """\
## What I verified

The prompt's assumptions hold.

## Findings

```text
Priority: Should fix
Confidence: 4
What I found: The deliverable leaves a stale path reference.
Why it matters: A reviewer lands on a missing file.
Trigger and effect: After the rename the pointer is dead.
Where: docs/task-prompts/03-E4.1-prompt.md, Deliverables.
Suggested fix: Add the path update to the deliverables.
```

```text
Priority: Should fix
Confidence: 4
What I found: The prompt is silent on matrix coverage.
Why it matters: A convention-mandated check is skipped silently.
Trigger and effect: The implementer omits the matrix review.
Where: docs/task-prompts/03-E4.1-prompt.md, requirement 7.
Suggested fix: Add one line recording the out-of-scope decision.
```

```text
Priority: Could fix
Confidence: 3
What I found: The annotations contradict the import strategy.
Why it matters: Minor compile churn or diff noise.
Trigger and effect: The implementer picks either strategy.
Where: docs/task-prompts/03-E4.1-prompt.md, Deliverables vs requirement 4.
Suggested fix: Pick one consumer-import strategy and align them.
```

## Verdict

Request changes — two should-fix items remain.
"""

TASK_REVIEW_UNPARSEABLE = """\
Priority: Urgent
Confidence: 4
What I found: Something is wrong.
Why it matters: It matters.
Trigger and effect: Always.
Where: docs/task-prompts/03-E4.1-prompt.md.
Suggested fix: Fix it.

## Verdict

Request changes
"""

#: The bold-label shape a real reviewer produced (see PR #214's regression test).
TASK_REVIEW_BOLD = """\
## Findings

**Priority: Should fix**
**Confidence: 5**

**What I found:** The importer enumeration omits a real fourth importer.
**Why it matters:** Literal compliance produces a non-building PR.
**Trigger and effect:** Any implementation that trusts the list.
**Where:** docs/task-prompts/03-E4.1-prompt.md, Context.
**Suggested fix:** Add the missing importer.

**Priority: Could fix**
**Confidence:** 3

**What I found:** The annotations contradict the import strategy.
**Why it matters:** Minor diff noise.
**Trigger and effect:** The implementer picks either strategy.
**Where:** docs/task-prompts/03-E4.1-prompt.md, Deliverables.
**Suggested fix:** Pick one strategy.

## Verdict

Request changes — one should-fix item remains.
"""


def _make_control_repo(
    tmp_path: Path,
    *,
    files: dict[str, str],
    base_branch: str = "main",
) -> Path:
    """Build a real bare repo plus a control worktree at ``tmp_path`` (EXTRACTION.md §3.2).

    The bare repo lives in a unique workspace sibling so branch setup can create
    ``<workspace_root>/<branch>`` outside the control tree. The control worktree is
    ``tmp_path`` itself, keeping the existing tests' repo-relative paths valid. All files
    are committed on ``base_branch`` so a newly created task worktree sees them.
    """
    workspace = tmp_path.parent / f"{tmp_path.name}-ws"
    seed = workspace / "seed"
    seed.mkdir(parents=True)
    _run_git(["init", "-q", "-b", base_branch, str(seed)], workspace)
    for rel, text in files.items():
        path = seed / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _run_git(["add", "."], seed)
    _run_git(["commit", "-qm", "init"], seed)
    bare = workspace / "bare.git"
    _run_git(["clone", "--bare", "-q", str(seed), str(bare)], workspace)
    _run_git(["worktree", "add", "-q", str(tmp_path), base_branch], bare)
    return workspace


def _patch_prompt_repo(
    tmp_path: Path,
    monkeypatch,
    *,
    roadmap: str | None = None,
    extra_files: dict[str, str] | None = None,
    base_branch: str = "main",
) -> None:
    """A committed bare+control repo (no origin) carrying the roadmap fixtures.

    ``roadmap`` defaults to :data:`ROADMAP_FIXTURE`; the default cannot be a literal
    default argument because that fixture is defined later in this module. ``extra_files``
    adds further phase files for the ``file``-scope tests. The files are committed so
    branch setup really creates a task worktree from ``base_branch``; ``current_branch``
    and ``is_clean`` are left unmocked so preflight reads real git.
    """
    files = {
        "docs/tasks/03 - Test Phase.md": (
            roadmap if roadmap is not None else ROADMAP_FIXTURE
        )
    }
    for name, text in (extra_files or {}).items():
        files[f"docs/tasks/{name}"] = text
    _make_control_repo(tmp_path, files=files, base_branch=base_branch)


def _review_index(stage_name: str) -> int | None:
    """N for ``task-review-N``, None for every other stage."""
    match = re.fullmatch(r"task-review-(\d+)", stage_name)
    return int(match.group(1)) if match else None


def _fix_round(stage_name: str) -> int | None:
    """Revision round N for a ``task-review-fixes-N[-M]`` stage, else ``None``.

    The fake fixer uses it to write a round-distinct marker into the prompt, so an
    assertion on a later round's ``extra`` can tell that round's diff from an earlier
    round's (L2.3). Without a mutation a naive per-round diff would be empty.
    """
    match = re.fullmatch(r"task-review-fixes-(\d+)(?:-\d+)?", stage_name)
    return int(match.group(1)) if match else None


def _fake_stages(
    review_body: str,
    *,
    fix_status: str = "succeeded",
    reconcile_status: str = "succeeded",
    approve_review: int | None = 2,
    blocked_review: int | None = None,
    prompt_body: str = "prompt body\n",
):
    """A fake ``run_stage`` returning canned review text, approving at ``approve_review``.

    Each fix stage appends a round-distinct marker to the prompt file (once per round), so
    the L2.3 delta-brief tests can prove that a round's diff carries only the immediately
    preceding fix batch's net effect, not every round's changes cumulatively. ``fix_status``
    and ``reconcile_status`` are separate knobs so a failing reconcile stage can be injected
    without special-casing its name in the workflow (L3.4). ``prompt_body`` is the text the
    fake author writes, so the L5.3 budget tests can seed an over-budget fixture.
    """
    from aidw.state import SUCCEEDED, StageRecord, run_dir

    seen: list[tuple[str, list[str], str]] = []
    repo_roots: list[Path] = []

    def fake_run_stage(spec, **kwargs):
        repo = kwargs["repo_root"]
        repo_roots.append(repo)
        state = kwargs["state"]
        directory = run_dir(kwargs["runs_root"], state.run_id)
        stages = directory / "stages"
        stages.mkdir(parents=True, exist_ok=True)

        if spec.name == "task-prompt":
            created = repo / "docs" / "task-prompts" / "03-E4.1-prompt.md"
            created.parent.mkdir(parents=True, exist_ok=True)
            created.write_text(prompt_body, encoding="utf-8")

        seen.append((spec.name, list(spec.variables), spec.extra))
        index = _review_index(spec.name)
        if index is not None:
            if index == blocked_review:
                body = TASK_REVIEW_BLOCKED_DEPENDENCY
            else:
                body = "## Verdict\n\n**Approve**\n" if index == approve_review else review_body
            # A round-distinct tail so a later round's "previous review" section is
            # attributable to the round it came from (L2.3 delta-brief tests).
            body += f"\n<!-- review round {index} -->\n"
        elif spec.name.startswith("task-review-fixes"):
            body = "fixed\n"
            revision = _fix_round(spec.name)
            if revision is not None:
                prompt_file = repo / "docs" / "task-prompts" / "03-E4.1-prompt.md"
                marker = f"<!-- fix round {revision} -->\n"
                text = prompt_file.read_text(encoding="utf-8")
                if marker not in text:
                    prompt_file.write_text(text + marker, encoding="utf-8")
        else:
            body = "prompt body\n"

        status = SUCCEEDED
        if spec.name.startswith("task-review-fixes") and fix_status != SUCCEEDED:
            status = fix_status
        if spec.name.startswith("task-review-reconcile") and reconcile_status != SUCCEEDED:
            status = reconcile_status
        out = stages / f"{spec.name}.out.txt"
        out.write_text(body, encoding="utf-8")
        record = StageRecord(
            name=spec.name,
            agent=spec.agent_id,
            model="test-model",
            status=status,
            artifacts={"out": str(out)},
        )
        state.record_stage(record)
        return record

    fake_run_stage.repo_roots = repo_roots
    return seen, fake_run_stage


# ---------------------------------------------------------------------------
# Branch setup: EXTRACTION.md §3.2/§3.4 — the worktree is Python-created before P1
# ---------------------------------------------------------------------------


def test_full_run_creates_one_worktree_keeps_control_clean_and_commits_only_prompt(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The full run creates the task worktree, runs every stage in it, and commits once."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)
    base_sha = git.rev_parse(tmp_path, "main")
    before = {worktree.path for worktree in git.worktrees(tmp_path)}

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    worktree = _task_worktree(tmp_path)
    after = {entry.path for entry in git.worktrees(tmp_path)}
    assert after - before == {worktree}
    assert [entry.path for entry in git.worktrees(tmp_path) if entry.branch == "03-E4.1"] == [
        worktree
    ]
    # §3.2 trap: every stage must run with cwd = the new worktree, never the control tree.
    assert fake.repo_roots and all(root == worktree for root in fake.repo_roots)
    # The control worktree stays on the base branch and clean; the commit is on the task
    # branch only and touches exactly the owned prompt path (design §13).
    assert git.current_branch(tmp_path) == "main"
    assert git.status_short(tmp_path) == ""
    assert git.rev_parse(tmp_path, "main") == base_sha
    assert git.changed_files(worktree, "main") == [
        "docs/task-prompts/03-E4.1-prompt.md"
    ]
    assert git.changed_files(tmp_path, "main") == []
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.git["branch"] == "03-E4.1"
    assert "branch: 03-E4.1" in capsys.readouterr().out


def test_non_default_base_branch_flows_through_and_worktree_branches_from_it(
    tmp_path: Path, monkeypatch
) -> None:
    """R4: a non-``main`` base branch is preflighted and is the worktree's branch point."""
    _patch_prompt_repo(tmp_path, monkeypatch, base_branch="trunk")
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)
    base_sha = git.rev_parse(tmp_path, "trunk")

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path, base_branch="trunk"),
        label=RUN_LABEL,
        approve_all=True,
    )

    assert code == 0
    worktree = _task_worktree(tmp_path)
    assert git.current_branch(worktree) == "03-E4.1"
    assert base_sha is not None
    head = git.rev_parse(worktree, "HEAD")
    assert head is not None and git.is_ancestor(worktree, base_sha, head) is True
    assert git.changed_files(worktree, "trunk") == [
        "docs/task-prompts/03-E4.1-prompt.md"
    ]
    assert state.list_runs(_runs_root(tmp_path))[-1].git["branch"] == "03-E4.1"


def test_derive_branch_name_default_reproduces_task_id_and_subphase() -> None:
    assert (
        prompt_workflow.derive_branch_name("{phase}-{task}", phase="00", task="E2.5")
        == "00-E2.5"
    )
    assert (
        prompt_workflow.derive_branch_name("{phase}-{task}", phase="03.1", task="A2")
        == "03.1-A2"
    )


def test_non_default_branch_pattern_names_branch_worktree_and_state_consistently(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)
    pattern = "ai-{phase}-{task}"

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path, branch_pattern=pattern),
        label=RUN_LABEL,
        approve_all=True,
    )

    assert code == 0
    branch = "ai-03-E4.1"
    worktree = _task_worktree(tmp_path, branch)
    assert git.current_branch(worktree) == branch
    assert all(root == worktree for root in fake.repo_roots)
    assert state.list_runs(_runs_root(tmp_path))[-1].git["branch"] == branch
    assert f"branch: {branch}" in capsys.readouterr().out


@pytest.mark.parametrize(
    "pattern",
    ["{phase}", "static", "{phase}-{task}-{extra}", "{phase}-{task"],
)
def test_malformed_branch_pattern_is_a_usage_error_before_any_worktree(
    tmp_path: Path, monkeypatch, capsys, pattern: str
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path, branch_pattern=pattern),
        label=RUN_LABEL,
        approve_all=True,
    )

    assert code == 2
    assert "malformed repo.branch_pattern" in capsys.readouterr().err
    assert state.list_runs(_runs_root(tmp_path)) == []
    assert len(git.worktrees(tmp_path)) == 1  # the control worktree only


def test_invalid_agent_config_refuses_before_worktree_or_run_state(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Initial agent validation must fail before Python creates the task worktree."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(
        prompt_workflow,
        "load_all",
        lambda _aidt_root, _repo_root: (
            {},
            [Issue(ERROR, "task-author.yaml", "invalid test configuration")],
        ),
    )
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL
    )

    assert code == 2
    assert "invalid test configuration" in capsys.readouterr().err
    assert state.list_runs(_runs_root(tmp_path)) == []
    assert len(git.worktrees(tmp_path)) == 1  # the control worktree only


def test_branch_already_checked_out_fails_closed_before_any_stage(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """``git.add_worktree`` returns None (one branch, one worktree) → exit 4, no run state."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    existing = git.add_worktree(tmp_path, "03-E4.1")
    assert existing is not None
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL
    )

    assert code == 4
    assert "branch-setup refused" in capsys.readouterr().err
    assert state.list_runs(_runs_root(tmp_path)) == []
    assert [entry.path for entry in git.worktrees(tmp_path) if entry.branch == "03-E4.1"] == [
        existing
    ]


def test_task_prompt_contains_no_branch_creation_or_commit_instructions() -> None:
    """The author is already on AIDT's branch; it neither branches nor commits."""
    text = (toolkit_root() / "prompts" / "task-prompt.md").read_text(encoding="utf-8")
    for token in (
        "git checkout -b",
        "git switch -c",
        "git branch --show-current",
        "Commit the new prompt",
        "before branching",
        "creating or switching",
        "must be created on",
        "current branch is not",
        "create or switch",
        "verify and retain",
    ):
        assert token not in text, token
    assert "AIDT owns branch setup" in text
    assert "creates the task branch and its worktree" in text
    assert "AIDT commits the reviewed prompt" in text


TASK_REVIEW_MULTI_COULD = """\
## Findings

```text
Priority: Must fix
Confidence: 5
What I found: The survey function name is wrong.
Why it matters: Callers cannot compile.
Trigger and effect: Any implementation.
Where: docs/task-prompts/03-E4.1-prompt.md, requirement 2.
Suggested fix: Use the real exported name.
```

```text
Priority: Could fix
Confidence: 3
What I found: The prose is repetitive.
Why it matters: Slightly harder to read.
Trigger and effect: None.
Where: docs/task-prompts/03-E4.1-prompt.md, Context.
Suggested fix: Tighten the paragraph.
```

```text
Priority: Could fix
Confidence: 3
What I found: The example path is stale.
Why it matters: Minor confusion.
Trigger and effect: None.
Where: docs/task-prompts/03-E4.1-prompt.md, Examples.
Suggested fix: Point at the current directory.
```

## Verdict

Request changes — one must-fix item.
"""


def test_approval_gate_defaults_to_not_required(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Without --require-approval the gate is auto-approved and recorded."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=False
    )

    assert code == 0
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "approved"
    assert gate.mechanism == "optional (default)"
    # L4.2: approve on review 1 records the full summary (one round, no fix batch).
    # The fake's approving round carries no findings block, so ``len(findings)`` is 0.
    for token in (
        "verdict=Approve",
        "rounds=1",
        "revisions=0",
        "findings=0",
        "fixes=0",
        "approved=yes",
        "fixes_after_last_review=no",
    ):
        assert token in gate.detail
    captured = capsys.readouterr()
    assert "gate approve-task-prompt denied" not in captured.err
    # The per-round count line reaches stdout, not only run.log.
    assert "round 1: findings=0 fixes=0" in captured.out
    assert "verdict=Approve" in _run_log(tmp_path, latest.run_id)


def test_approval_gate_can_be_required(
    tmp_path: Path, monkeypatch
) -> None:
    """--require-approval pauses; a non-interactive session fails closed."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("AIDW_NONINTERACTIVE", "1")
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=False,
        require_approval=True,
    )

    assert code == 3
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "denied"


def test_review_fix_loop_fixes_blocking_individually_and_batches_could_fix(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert [name for name, _, _ in seen] == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1-1",
        "task-review-fixes-1-2",
        "task-review-fixes-1-3",
        "task-review-reconcile-1",
        "task-review-2",
    ]
    fixes = [item for item in seen if item[0].startswith("task-review-fixes")]
    assert all(vars_ == ["docs/task-prompts/03-E4.1-prompt.md"] for _, vars_, _ in fixes)
    assert "Review finding 1 of 3 to address" in fixes[0][2]
    assert "Review finding 2 of 3 to address" in fixes[1][2]
    assert "Suggested fix: Add one line recording the out-of-scope decision." in fixes[1][2]
    # The non-blocking could-fix finding is batched into a single stage of its own.
    # L2.4 prepends the evidence pointer, so the combined block follows it.
    assert "## Non-blocking (could-fix) review finding to address together" in fixes[2][2]
    assert fixes[2][2].index("## Evidence bundle") < fixes[2][2].index(
        "## Non-blocking (could-fix) review finding to address together"
    )
    assert "Suggested fix: Pick one consumer-import strategy and align them." in fixes[2][2]
    assert "Add the path update to the deliverables." not in fixes[2][2]
    # Every author, review, fix, and reconcile stage must stay in the created worktree.
    worktree = _task_worktree(tmp_path)
    assert fake.repo_roots and all(root == worktree for root in fake.repo_roots)

    out = capsys.readouterr().out
    assert "verdict: Request changes — 3 findings (2 should-fix, 1 could-fix)" in out
    assert "fix 1.1/3: The deliverable leaves a stale path reference [should-fix]" in out
    assert "fix 1.2/3: The prompt is silent on matrix coverage [should-fix]" in out
    assert "fix 1.3/3: 1 could-fix finding combined" in out
    assert "stages/task-review-1.out.txt" in out


def test_multiple_could_fix_findings_share_one_stage(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_MULTI_COULD)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert [name for name, _, _ in seen] == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1-1",
        "task-review-fixes-1-2",
        "task-review-reconcile-1",
        "task-review-2",
    ]
    combined = seen[3][2]
    assert "The review raised 2 non-blocking findings." in combined
    assert "Tighten the paragraph." in combined
    assert "Point at the current directory." in combined
    assert "Use the real exported name." not in combined
    out = capsys.readouterr().out
    assert "fix 1.1/2: The survey function name is wrong [must-fix]" in out
    assert "fix 1.2/2: 2 could-fix findings combined" in out


def test_could_fix_only_review_still_runs_one_combined_stage(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    only_could = "\n".join(
        [line for line in TASK_REVIEW_MULTI_COULD.splitlines() if "Must fix" not in line]
    ).replace("one must-fix item.", "two could-fix items.")
    seen, fake = _fake_stages(only_could)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert [name for name, _, _ in seen] == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1-1",
        "task-review-reconcile-1",
        "task-review-2",
    ]
    out = capsys.readouterr().out
    assert "fix 1.1/1: 2 could-fix findings combined" in out


def test_review_fix_loop_falls_back_to_one_combined_stage(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_UNPARSEABLE)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert [name for name, _, _ in seen] == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1",
        "task-review-reconcile-1",
        "task-review-2",
    ]
    combined = seen[2][2]
    # L2.4 prepends the evidence pointer, so the whole-review block follows it.
    assert "## Review findings to address" in combined
    assert combined.index("## Evidence bundle") < combined.index(
        "## Review findings to address"
    )
    out = capsys.readouterr().out
    assert "did not parse cleanly" in out


def test_bold_review_drives_per_finding_fixes(tmp_path: Path, monkeypatch, capsys) -> None:
    """Regression: bold label lines must not silently fall back to one combined stage."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_BOLD)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert [name for name, _, _ in seen] == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1-1",
        "task-review-fixes-1-2",
        "task-review-reconcile-1",
        "task-review-2",
    ]
    out = capsys.readouterr().out
    assert "verdict: Request changes — 2 findings (1 should-fix, 1 could-fix)" in out
    assert "did not parse cleanly" not in out
    assert "fix 1.1/2: The importer enumeration" in out
    assert "fix 1.2/2: 1 could-fix finding combined" in out


def test_failed_fix_stage_stops_the_run(tmp_path: Path, monkeypatch) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    from aidw.state import FAILED

    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, fix_status=FAILED)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 1
    assert "task-review-fixes-1-1" in [name for name, _, _ in seen]
    assert "task-review-fixes-1-2" not in [name for name, _, _ in seen]
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.FAILED
    # A verdict-less failure exit records no gate and writes no summary line (Req 3).
    assert not any(g.name == "approve-task-prompt" for g in latest.gates)
    log = _run_log(tmp_path, latest.run_id)
    assert "approved=" not in log
    assert "fixes_after_last_review" not in log


def test_failed_fix_round_prints_no_predicted_round_line(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A fixing round's stdout line waits for its fix batch (review follow-up #31).

    ``fixes=`` is predicted before the batch runs; printed there it would overstate a
    run that dies mid-batch — ``state.json`` would hold fewer ``task-review-fixes-*``
    stages than the line claims. Recorded after the batch (and its reconcile) instead,
    a FAILED exit prints no round line at all, like every other verdict-less exit.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    from aidw.state import FAILED

    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, fix_status=FAILED)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )
    captured = capsys.readouterr()

    assert code == 1
    # TASK_REVIEW_CHANGES plans three fix stages (2 blocking + 1 combined); the first
    # fails, so the run stops before the second and never reaches the reconcile.
    names = [name for name, _, _ in seen]
    assert "task-review-fixes-1-1" in names
    assert "task-review-fixes-1-2" not in names
    # The predicted count must not reach stdout: no round line on the FAILED path.
    assert "round 1: findings=3 fixes=3" not in captured.out
    assert "round 1:" not in captured.out


TASK_REVIEW_BLOCKED = """\
## Findings

```text
Priority: Must fix
Confidence: 5
What I found: A material ambiguity the prompt cannot settle.
Why it matters: An implementer would have to guess a schema decision.
Trigger and effect: Always.
Where: docs/task-prompts/03-E4.1-prompt.md.
Suggested fix: The owner must decide it.
```

## Verdict

Blocked — a human must settle the schema decision.
"""

#: A `Blocked` verdict reporting a dependency-branch conflict (L2.1). It carries a
#: parseable finding block on purpose: the short-circuit must hold with findings too.
TASK_REVIEW_BLOCKED_DEPENDENCY = """\
## What I verified

The prompt depends on a task whose implementation is not on the base branch.

## Findings

```text
Priority: Could fix
Confidence: 4
What I found: The dependency's shape is unmerged and the roadmap summary disagrees with it.
Why it matters: Prescribing one shape would settle the conflict without authority.
Trigger and effect: The implementer follows a prescription the dependency branch does not support.
Where: the dependency branch, inspected at its current revision.
Suggested fix: Do not prescribe a shape; the owner must decide which authority governs.
```

## Verdict

Blocked — the dependency branch is the authority and a human must settle the conflict.
"""

#: A Blocked verdict without a parseable findings block must not fall through to the
#: single whole-review fallback fixer (L2.1).
TASK_REVIEW_BLOCKED_NO_FINDINGS = """\
## Verdict

Blocked — the dependency implementation is unmerged and requires an owner decision.
"""


def test_third_review_is_terminal_and_residual_request_changes_fails_closed(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The default `max_revisions` (3) runs three review rounds; the third is review-only,
    so a residual `Request changes` fails closed with review-3's findings and no round-3 fixes."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 3
    names = [name for name, _, _ in seen]
    # Two fix batches (rounds 1 and 2) + two reconciles, then the terminal review-3:
    # no `task-review-fixes-3-*`, no `task-review-reconcile-3`, no review-4.
    assert names == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1-1",
        "task-review-fixes-1-2",
        "task-review-fixes-1-3",
        "task-review-reconcile-1",
        "task-review-2",
        "task-review-fixes-2-1",
        "task-review-fixes-2-2",
        "task-review-fixes-2-3",
        "task-review-reconcile-2",
        "task-review-3",
    ]
    assert not any(name.startswith("task-review-fixes-3") for name in names)
    assert "task-review-reconcile-3" not in names
    assert "task-review-4" not in names
    # The two keeps: review-1's batch sits before review-2, review-2's before review-3.
    assert names.index("task-review-fixes-1-3") < names.index(
        "task-review-reconcile-1"
    ) < names.index("task-review-2")
    assert names.index("task-review-fixes-2-3") < names.index(
        "task-review-reconcile-2"
    ) < names.index("task-review-3")

    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    # L4.2 reverses L4.1's "no gate record": the terminal `Request changes` records
    # `approve-task-prompt` with `decision=denied` and the full per-round summary, so the
    # verdict is readable from state.json without opening any stage `.out.txt`.
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "denied"
    for token in (
        "verdict=Request changes",
        "rounds=3",
        "revisions=2",
        "max_revisions=3",
        "findings=3/3/3",
        "fixes=3/3/0",
        "approved=no",
        "fixes_after_last_review=no",
    ):
        assert token in gate.detail
    log = _run_log(tmp_path, latest.run_id)
    assert "findings=3/3/3" in log
    assert "fixes=3/3/0" in log
    assert "run BLOCKED" in log

    captured = capsys.readouterr()
    # Per-round counts reach stdout, not only run.log.
    assert "round 1: findings=3 fixes=3" in captured.out
    assert "round 3: findings=3 fixes=0" in captured.out
    # The terminal review itself, rather than an earlier round, is the residual evidence
    # shown to the human; the old unreviewed-acceptance line is gone.
    assert "The deliverable leaves a stale path reference." in captured.err
    assert "<!-- review round 3 -->" in captured.err
    assert "revision budget spent" not in captured.out
    # Fixes from rounds 1 and 2 remain as uncommitted human-review material, but no
    # round-3 fix was applied before the fail-closed return (design §8.1, G2).
    worktree = _task_worktree(tmp_path)
    prompt_path = worktree / "docs" / "task-prompts" / "03-E4.1-prompt.md"
    prompt = prompt_path.read_text(encoding="utf-8")
    assert "<!-- fix round 1 -->" in prompt
    assert "<!-- fix round 2 -->" in prompt
    assert "<!-- fix round 3 -->" not in prompt
    assert git.status_short(worktree, paths=["docs/task-prompts/03-E4.1-prompt.md"]) != ""


def test_approve_on_the_terminal_review_succeeds(
    tmp_path: Path, monkeypatch
) -> None:
    """`Approve` on review-3 (after two fix batches) still succeeds, review-3 last."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=3)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    names = [name for name, _, _ in seen]
    assert names[-1] == "task-review-3"
    assert not any(name.startswith("task-review-fixes-3") for name in names)
    assert "task-review-4" not in names

    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.SUCCEEDED
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "approved"
    assert "verdict=Approve" in gate.detail
    # ``revisions`` counts fix batches, so a 3-review success reports 2.
    assert "revisions=2" in gate.detail
    assert "assumed_ok" not in gate.detail
    # Rounds 1-2 fix the three-finding review; the approving review-3 body carries no
    # findings block, so its count is 0 (Req 1: 0 only when nothing parsed).
    for token in (
        "rounds=3",
        "findings=3/3/0",
        "fixes=3/3/0",
        "approved=yes",
        "fixes_after_last_review=no",
    ):
        assert token in gate.detail
    assert "verdict=Approve" in _run_log(tmp_path, latest.run_id)


def _extra_for(seen: list[tuple[str, list[str], str]], name: str) -> str:
    """The ``extra`` the workflow passed to stage ``name``."""
    return next(extra for stage, _, extra in seen if stage == name)


def _record_temp_dirs(monkeypatch) -> list[Path]:
    """Record every temp directory the delta brief creates, to assert cleanup (L2.3)."""
    created: list[Path] = []
    real_mkdtemp = prompt_workflow.mkdtemp

    def recording_mkdtemp(*args, **kwargs):
        path = Path(real_mkdtemp(*args, **kwargs))
        created.append(path)
        return path

    monkeypatch.setattr(prompt_workflow, "mkdtemp", recording_mkdtemp)
    return created


def test_first_review_round_is_unprimed(tmp_path: Path, monkeypatch) -> None:
    """Round 1 stays findings-unprimed; it still receives its evidence pointer (L2.4).

    L2.3's "unprimed" guarantee is about *prior findings*, not the gathered context the
    reviewer already reads through its Scope step, so the evidence pointer is allowed.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert [name for name, _, _ in seen] == ["task-prompt", "task-review-1"]
    _, variables, extra = next(item for item in seen if item[0] == "task-review-1")
    assert variables == ["docs/task-prompts/03-E4.1-prompt.md"]
    # No prior-findings priming on the first round.
    assert "## Delta brief" not in extra
    assert "### Previous review" not in extra
    assert "### Prompt diff" not in extra
    run_id = state.list_runs(_runs_root(tmp_path))[-1].run_id
    evidence = _runs_root(tmp_path) / run_id / "stages" / "task-review-1.evidence.md"
    assert extra == prompt_workflow._evidence_pointer(evidence.resolve())
    assert str(evidence) in extra


def test_second_round_gets_delta_brief_with_previous_review_and_diff(
    tmp_path: Path, monkeypatch
) -> None:
    """Round 2 receives the resolution instruction, round 1's review, and a real diff."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    extra = _extra_for(seen, "task-review-2")
    for token in ("`resolved`", "`not resolved`", "`newly contradicted`"):
        assert token in extra
    # The previous review is passed verbatim, and only then does the diff follow.
    assert "The deliverable leaves a stale path reference." in extra
    assert "<!-- review round 1 -->" in extra
    assert extra.index("## Delta brief") < extra.index("### Previous review")
    assert extra.index("### Previous review") < extra.index("### Prompt diff")
    # A genuine unified diff for the fix round-1 marker, under stable header paths and
    # with no random temp path in the brief.
    assert "diff --git a/baseline/03-E4.1-prompt.md b/current/03-E4.1-prompt.md" in extra
    assert "--- a/baseline/03-E4.1-prompt.md" in extra
    assert "+++ b/current/03-E4.1-prompt.md" in extra
    assert "@@" in extra
    assert "+<!-- fix round 1 -->" in extra
    assert "aidw-prompt-diff-" not in extra
    assert "/tmp/" not in extra


def test_third_round_diff_reflects_only_the_previous_fix_batch(
    tmp_path: Path, monkeypatch
) -> None:
    """The baseline is captured per round, so round 3's diff is not cumulative."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=3)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    extra = _extra_for(seen, "task-review-3")
    # Round 2's review, not round 1's.
    assert "<!-- review round 2 -->" in extra
    assert "<!-- review round 1 -->" not in extra
    # Only the round-2 marker is an addition; round 1's marker is at most context.
    assert "+<!-- fix round 2 -->" in extra
    assert "+<!-- fix round 1 -->" not in extra
    assert "diff --git a/baseline/03-E4.1-prompt.md b/current/03-E4.1-prompt.md" in extra
    assert "aidw-prompt-diff-" not in extra


def test_delta_brief_temp_directories_are_removed(
    tmp_path: Path, monkeypatch
) -> None:
    """Every round's diff temp directory is removed, including on the success path."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=3)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)
    created = _record_temp_dirs(monkeypatch)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    # Two reconcile diffs (after each of the two fix batches) plus the two review delta
    # briefs (rounds 2 and 3); the terminal review-3 has no fix batch to reconcile.
    assert len(created) == 4
    assert all(not path.exists() for path in created)


def test_delta_brief_preserves_previous_review_verbatim(
    tmp_path: Path, monkeypatch
) -> None:
    """The prior review is carried byte-for-byte, including meaningful whitespace."""
    baseline = "prompt\n"
    previous_review = "Review text with trailing spaces  \n"

    brief = prompt_workflow._render_delta_brief(
        index=2,
        previous_review=previous_review,
        baseline=baseline,
        current=baseline,
        rel="docs/task-prompts/03-E4.1-prompt.md",
    )

    assert previous_review in brief


def test_unparseable_previous_review_still_primes_the_next_round(
    tmp_path: Path, monkeypatch
) -> None:
    """A fallback whole-review fix still supplies a delta brief on round 2."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_UNPARSEABLE, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    extra = _extra_for(seen, "task-review-2")
    assert "## Delta brief" in extra
    assert "Something is wrong." in extra
    assert "`resolved`" in extra
    assert "+<!-- fix round 1 -->" in extra


def test_failed_prompt_diff_degrades_brief_without_failing_the_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A non-0/1 git diff exit warns and degrades the brief; the loop still finishes."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)
    created = _record_temp_dirs(monkeypatch)

    def failing_diff(directory: Path, name: str) -> tuple[int, str, str]:
        return 2, "", "fatal: could not read object\n"

    monkeypatch.setattr(prompt_workflow, "_no_index_diff", failing_diff)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    extra = _extra_for(seen, "task-review-2")
    for token in ("`resolved`", "`not resolved`", "`newly contradicted`"):
        assert token in extra
    assert "The deliverable leaves a stale path reference." in extra
    assert "unavailable" in extra
    assert "diff --git" not in extra
    # Both degraded diffs (the round-1 reconcile and the round-2 delta brief) still
    # clean up their temp directory.
    assert len(created) == 2
    assert all(not path.exists() for path in created)
    err = capsys.readouterr().err
    assert "warning:" in err
    assert "prompt diff" in err
    assert "fatal: could not read object" in err


def test_a_blocked_final_review_still_fails_closed(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A Blocked verdict always needs a human: no fix stage, no commit, exit 3."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_BLOCKED, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=False
    )

    assert code == 3
    names = [name for name, _, _ in seen]
    assert names == ["task-prompt", "task-review-1"]
    assert not any(name.startswith("task-review-fixes") for name in names)
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    # L4.2: a Blocked verdict also records the gate, so the outcome is visible from
    # state.json (decision=denied; the verdict travels in the summary).
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "denied"
    for token in (
        "verdict=Blocked",
        "rounds=1",
        "revisions=0",
        "findings=1",
        "fixes=0",
        "approved=no",
        "fixes_after_last_review=no",
    ):
        assert token in gate.detail
    assert "run BLOCKED" in _run_log(tmp_path, latest.run_id)
    captured = capsys.readouterr()
    assert "A material ambiguity the prompt cannot settle." in captured.err
    assert "revision budget spent" not in captured.out


def test_blocked_terminal_review_keeps_human_escalation_path(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A Blocked verdict on review 3 wins over the terminal Request-changes branch."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(
        TASK_REVIEW_CHANGES, approve_review=None, blocked_review=3
    )
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 3
    names = [name for name, _, _ in seen]
    assert names[-1] == "task-review-3"
    assert not any(name.startswith("task-review-fixes-3") for name in names)
    assert "task-review-reconcile-3" not in names
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "denied"
    for token in (
        "verdict=Blocked",
        "rounds=3",
        "revisions=2",
        "findings=3/3/1",
        "fixes=3/3/0",
        "approved=no",
        "fixes_after_last_review=no",
    ):
        assert token in gate.detail
    assert "run BLOCKED" in _run_log(tmp_path, latest.run_id)
    captured = capsys.readouterr()
    assert "a human must settle it" in captured.err
    assert "the dependency branch is the authority" in captured.err
    assert "task review did not approve within the revision budget" not in captured.err
    assert git.status_short(
        tmp_path, paths=["docs/task-prompts/03-E4.1-prompt.md"]
    ) != ""


def test_blocked_dependency_verdict_short_circuits_before_any_fix(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A dependency-branch conflict reported as Blocked ends the run with no fix round."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_BLOCKED_DEPENDENCY, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=False
    )

    assert code == 3
    names = [name for name, _, _ in seen]
    assert names == ["task-prompt", "task-review-1"]
    assert not any(name.startswith("task-review-fixes") for name in names)
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    assert "the dependency branch is the authority" in capsys.readouterr().err
    # Fail closed at the git level too: the prompt is still uncommitted.
    assert (
        git.status_short(_task_worktree(tmp_path), paths=["docs/task-prompts/03-E4.1-prompt.md"]) != ""
    )


def test_blocked_verdict_overrides_approve_all(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """approve_all must not carry a Blocked verdict past the short-circuit to commit."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_BLOCKED_DEPENDENCY, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 3
    names = [name for name, _, _ in seen]
    assert not any(name.startswith("task-review-fixes") for name in names)
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    assert "the dependency branch is the authority" in capsys.readouterr().err
    assert (
        git.status_short(_task_worktree(tmp_path), paths=["docs/task-prompts/03-E4.1-prompt.md"]) != ""
    )


def test_blocked_without_findings_does_not_run_fallback_fix(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Blocked short-circuits before the no-findings fallback fixer as well."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_BLOCKED_NO_FINDINGS, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=False
    )

    assert code == 3
    assert [name for name, _, _ in seen] == ["task-prompt", "task-review-1"]
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    assert "requires an owner decision" in capsys.readouterr().err
    assert (
        git.status_short(_task_worktree(tmp_path), paths=["docs/task-prompts/03-E4.1-prompt.md"]) != ""
    )


def test_commit_reviewed_prompt_commits_changes(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    prompt = tmp_path / "docs" / "task-prompts" / "03-E4.1-prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    assert prompt_workflow._commit_reviewed_prompt(
        tmp_path, "docs/task-prompts/03-E4.1-prompt.md", "03", "E4.1"
    )

    prompt.write_text("revised\n", encoding="utf-8")
    assert prompt_workflow._commit_reviewed_prompt(
        tmp_path, "docs/task-prompts/03-E4.1-prompt.md", "03", "E4.1"
    )
    assert git.status_short(_task_worktree(tmp_path), paths=["docs/task-prompts/03-E4.1-prompt.md"]) == ""


def test_commit_reviewed_prompt_noop_when_clean(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    assert prompt_workflow._commit_reviewed_prompt(
        tmp_path, "docs/task-prompts/03-E4.1-prompt.md", "03", "E4.1"
    )


ROADMAP_FIXTURE = """# Phase 3: Test Phase

## Epic E4: Defensive Combat

- [ ] **E4.1. Implement Total Defense** per Design 09..
  - Done when: applyTotalDefense returns the fixed effect.
"""


def test_review_uses_resolved_path_and_commits(tmp_path: Path, monkeypatch) -> None:
    """The reviewer is pointed at the path the author created, resolved against the worktree."""
    _patch_prompt_repo(tmp_path, monkeypatch)

    from aidw.state import SUCCEEDED, StageRecord, run_dir

    captured: list[list[str]] = []
    repo_roots: list[Path] = []

    def fake_run_stage(spec, **kwargs):
        repo = kwargs["repo_root"]
        repo_roots.append(repo)
        state = kwargs["state"]
        directory = run_dir(kwargs["runs_root"], state.run_id)
        stages = directory / "stages"
        stages.mkdir(parents=True, exist_ok=True)

        if spec.name == "task-prompt":
            # Author creates a non-canonical filename; workflow must trust the report.
            created = repo / "docs" / "task-prompts" / "03-E4.1.md"
            created.parent.mkdir(parents=True, exist_ok=True)
            created.write_text("prompt body\n", encoding="utf-8")
            out = stages / "task-prompt.out.txt"
            out.write_text("docs/task-prompts/03-E4.1.md\n", encoding="utf-8")
        else:
            captured.append(list(spec.variables))
            out = stages / f"{spec.name}.out.txt"
            out.write_text("...\n## Verdict\n\n**Approve**\n", encoding="utf-8")

        record = StageRecord(
            name=spec.name,
            agent=spec.agent_id,
            model="test",
            status=SUCCEEDED,
            artifacts={"out": str(out)},
        )
        state.record_stage(record)
        return record

    monkeypatch.setattr(prompt_workflow, "run_stage", fake_run_stage)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
    )

    assert code == 0
    worktree = _task_worktree(tmp_path)
    assert captured == [["docs/task-prompts/03-E4.1.md"]]
    assert all(root == worktree for root in repo_roots)
    assert git.status_short(worktree, paths=["docs/task-prompts/03-E4.1.md"]) == ""
    assert git.changed_files(worktree, "main") == ["docs/task-prompts/03-E4.1.md"]


# ---------------------------------------------------------------------------
# L1.1 — fetch and require the base branch to be current (design §8.1, §13)
# ---------------------------------------------------------------------------


def _run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _explode_stage(*args: object, **kwargs: object) -> object:
    raise AssertionError("no stage may run when the preflight refuses")


def _origin_and_clone(
    tmp_path: Path, *, roadmap: str = ROADMAP_FIXTURE
) -> tuple[Path, Path]:
    """Build a bare ``origin`` and a bare+control clone carrying the roadmap fixture.

    The control worktree at ``tmp_path/clone`` is the target repo the workflow drives; its
    bare repo is ``tmp_path/clone.git`` and ``origin/main`` resolves from the first run.
    The real bare+worktree layout lets branch setup create ``tmp_path/03-E4.1`` instead of
    trying to nest a worktree inside the control tree (EXTRACTION.md §3.2).
    """
    seed = tmp_path / "seed"
    seed.mkdir()
    _run_git(["init", "-q", "-b", "main", str(seed)], tmp_path)
    tasks_dir = seed / "docs" / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "03 - Test Phase.md").write_text(roadmap, encoding="utf-8")
    _run_git(["add", "."], seed)
    _run_git(["commit", "-qm", "init"], seed)
    origin = tmp_path / "origin.git"
    _run_git(["clone", "--bare", "-q", str(seed), str(origin)], tmp_path)
    bare_clone = tmp_path / "clone.git"
    _run_git(["clone", "--bare", "-q", str(origin), str(bare_clone)], tmp_path)
    # A bare clone maps refs/heads/* to refs/heads/*, so teach it the normal
    # remote-tracking refspec and populate origin/main for the preflight comparison.
    _run_git(
        ["config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"],
        bare_clone,
    )
    _run_git(["fetch", "-q", "origin"], bare_clone)
    clone = tmp_path / "clone"
    _run_git(["worktree", "add", "-q", str(clone), "main"], bare_clone)
    return origin, clone


def _advance_origin(tmp_path: Path, origin: Path, name: str) -> str:
    """Push a new commit to ``origin/main`` from a throwaway clone; return its sha."""
    pusher = tmp_path / f"pusher-{name}"
    _run_git(["clone", "-q", str(origin), str(pusher)], tmp_path)
    (pusher / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
    _run_git(["add", f"{name}.txt"], pusher)
    _run_git(["commit", "-qm", f"advance {name}"], pusher)
    _run_git(["push", "-q", "origin", "main"], pusher)
    return git.rev_parse(pusher, "HEAD") or ""


def _local_commit(clone: Path, name: str) -> str:
    """Commit a local-only change on ``main`` in the clone; return its sha."""
    (clone / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
    _run_git(["add", f"{name}.txt"], clone)
    _run_git(["commit", "-qm", f"local {name}"], clone)
    return git.rev_parse(clone, "HEAD") or ""


def _break_origin(clone: Path, url: str = "https://user:token@127.0.0.1:1/nope.git") -> None:
    _run_git(["remote", "set-url", "origin", url], clone)


def _approve_first_review():
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    return seen, fake


def test_fetch_is_noninteractive_and_bounded(tmp_path: Path, monkeypatch) -> None:
    """The spawn reaches subprocess with ``GIT_TERMINAL_PROMPT=0`` and the timeout."""
    captured: dict = {}

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _Result()

    monkeypatch.setattr(git.subprocess, "run", fake_run)
    ok, reason = git.fetch(tmp_path, timeout=7)

    assert ok is True and reason == ""
    assert captured["cmd"] == ["git", "fetch", "origin"]
    assert captured["kwargs"]["timeout"] == 7
    assert captured["kwargs"]["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_fetch_default_timeout_is_thirty_seconds(tmp_path: Path, monkeypatch) -> None:
    captured: dict = {}

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["kwargs"] = kwargs
        return _Result()

    monkeypatch.setattr(git.subprocess, "run", fake_run)
    assert git.fetch(tmp_path) == (True, "")
    assert captured["kwargs"]["timeout"] == 30


def test_fetch_timeout_counts_as_failure(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(git.subprocess, "run", fake_run)
    ok, reason = git.fetch(tmp_path, timeout=1)

    assert ok is False
    assert "timed out" in reason


def test_is_ancestor_is_tristate(tmp_path: Path) -> None:
    _run_git(["init", "-q", "-b", "main", str(tmp_path)], tmp_path)
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    _run_git(["add", "a.txt"], tmp_path)
    _run_git(["commit", "-qm", "a"], tmp_path)
    parent = git.rev_parse(tmp_path, "HEAD")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    _run_git(["add", "b.txt"], tmp_path)
    _run_git(["commit", "-qm", "b"], tmp_path)
    child = git.rev_parse(tmp_path, "HEAD")

    assert git.is_ancestor(tmp_path, parent or "", child or "") is True
    assert git.is_ancestor(tmp_path, child or "", parent or "") is False
    assert git.is_ancestor(tmp_path, "0" * 40, child or "") is None


def test_preflight_equal_base_proceeds_silently(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _origin, clone = _origin_and_clone(tmp_path)
    _seen, fake = _approve_first_review()
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(clone), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    err = capsys.readouterr().err
    assert err == ""


def test_preflight_behind_refuses_before_writing(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    origin, clone = _origin_and_clone(tmp_path)
    remote_sha = _advance_origin(tmp_path, origin, "upstream")
    local_sha = git.rev_parse(clone, "main") or ""
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(clone), label=RUN_LABEL
    )

    assert code == 4
    err = capsys.readouterr().err
    assert local_sha in err and remote_sha in err
    assert "behind" in err
    assert "git pull --ff-only" in err
    # A refusal leaves no run directory, no ``{phase}-{task}`` branch and no prompt file.
    assert state.list_runs(_runs_root(clone)) == []
    assert git.current_branch(clone) == "main"
    assert git.rev_parse(clone, "03-E4.1") is None
    assert not (clone / "docs" / "task-prompts" / "03-E4.1-prompt.md").exists()


def test_preflight_diverged_refuses_without_a_destructive_command(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    origin, clone = _origin_and_clone(tmp_path)
    remote_sha = _advance_origin(tmp_path, origin, "upstream")
    local_sha = _local_commit(clone, "local")
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(clone), label=RUN_LABEL
    )

    assert code == 4
    err = capsys.readouterr().err
    assert local_sha in err and remote_sha in err
    assert "diverged" in err
    assert "reset" not in err.lower()
    assert "force" not in err.lower()
    assert state.list_runs(_runs_root(clone)) == []


def test_preflight_ahead_warns_and_proceeds(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _origin, clone = _origin_and_clone(tmp_path)
    _local_commit(clone, "local")
    _seen, fake = _approve_first_review()
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(clone), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert "ahead" in capsys.readouterr().err


def test_preflight_without_origin_warns_and_proceeds(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen, fake = _approve_first_review()
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    err = capsys.readouterr().err
    assert "cannot verify" in err


def test_preflight_stale_cache_still_refuses_when_fetch_fails(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A failed fetch does not decide the verdict: the cached ref still refuses."""
    origin, clone = _origin_and_clone(tmp_path)
    _advance_origin(tmp_path, origin, "upstream")
    _run_git(["fetch", "origin"], clone)  # cache origin/main ahead of the local branch
    _break_origin(clone)
    remote_sha = git.rev_parse(clone, "origin/main") or ""
    local_sha = git.rev_parse(clone, "main") or ""
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(clone), label=RUN_LABEL
    )

    assert code == 4
    err = capsys.readouterr().err
    assert "could not fetch" in err
    assert local_sha in err and remote_sha in err
    assert "git pull --ff-only" in err
    assert state.list_runs(_runs_root(clone)) == []


def test_preflight_fetch_warning_redacts_credentials(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _origin, clone = _origin_and_clone(tmp_path)
    _break_origin(clone)
    _seen, fake = _approve_first_review()
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(clone), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    err = capsys.readouterr().err
    assert "could not fetch" in err
    assert "token" not in err
    assert "user:token@" not in err
    assert "127.0.0.1" in err  # the host survives; only the userinfo is removed


def test_no_fetch_warns_and_skips_the_stale_check(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    origin, clone = _origin_and_clone(tmp_path)
    _advance_origin(tmp_path, origin, "upstream")
    _seen, fake = _approve_first_review()
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)
    monkeypatch.setattr(git, "fetch", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("--no-fetch must not fetch")
    ))
    monkeypatch.setattr(git, "rev_parse", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("--no-fetch must not compare revisions")
    ))

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(clone),
        label=RUN_LABEL,
        approve_all=True,
        no_fetch=True,
    )

    assert code == 0
    assert "--no-fetch" in capsys.readouterr().err


def test_dry_run_never_fetches_with_an_unreachable_origin(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _origin, clone = _origin_and_clone(tmp_path)
    _break_origin(clone)
    calls: list[tuple] = []
    comparisons: list[tuple] = []

    def spy_fetch(*args, **kwargs):
        calls.append(args)
        return True, ""

    def spy_rev_parse(*args, **kwargs):
        comparisons.append(args)
        return None

    monkeypatch.setattr(git, "fetch", spy_fetch)
    monkeypatch.setattr(git, "rev_parse", spy_rev_parse)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(clone), label=RUN_LABEL, dry_run=True
    )

    assert code == 0
    assert calls == []
    assert comparisons == []
    assert "[dry-run] a real run will fetch and verify the base branch" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# L1.2 — refuse to author when earlier tasks in the same phase file are unticked
#        (design §8.1, §11)
# ---------------------------------------------------------------------------

#: Target ``E4.1`` has an earlier unticked ``E3.1`` in the same phase file.
ROADMAP_INCOMPLETE_PREDECESSOR = """# Phase 3: Test Phase

## Epic E3: Earlier Epic

- [ ] **E3.1. An earlier unticked task** per Design 09..
  - Done when: whatever the task requires.

## Epic E4: Defensive Combat

- [ ] **E4.1. Implement Total Defense** per Design 09..
  - Done when: applyTotalDefense returns the fixed effect.
"""

#: The same shape with the earlier task ticked: the ``[x]`` state must satisfy the gate.
ROADMAP_COMPLETE_PREDECESSORS = """# Phase 3: Test Phase

## Epic E3: Earlier Epic

- [x] **E3.1. An earlier ticked task** per Design 09..
  - Done when: whatever the task requires.

## Epic E4: Defensive Combat

- [ ] **E4.1. Implement Total Defense** per Design 09..
  - Done when: applyTotalDefense returns the fixed effect.
"""

#: An earlier line inside a later-sorting epic (E9) must still block E4.1: line order is
#: the authority, never epic-id order.
ROADMAP_EARLIER_LINE_LATER_EPIC = """# Phase 3: Test Phase

## Epic E9: Later Epic

- [ ] **E9.1. A later-sorting epic on an earlier line** per Design 09..
  - Done when: whatever the task requires.

## Epic E4: Defensive Combat

- [ ] **E4.1. Implement Total Defense** per Design 09..
  - Done when: applyTotalDefense returns the fixed effect.
"""

#: A later, unticked sibling (E4.2) must not block an earlier target (E4.1).
ROADMAP_LATER_UNTICKED_SIBLING = """# Phase 3: Test Phase

## Epic E4: Defensive Combat

- [ ] **E4.1. Implement Total Defense** per Design 09..
  - Done when: applyTotalDefense returns the fixed effect.

- [ ] **E4.2. Implement Parry** per Design 09..
  - Done when: applyParry returns the fixed effect.
"""

#: An unticked task in a different phase file must not block phase 03's runs.
OTHER_PHASE_FIXTURE = """# Phase 4: Another Phase

## Epic E4: Defensive Combat

- [ ] **E4.1. An unticked task in another phase file** per Design 09..
  - Done when: it stays out of scope.
"""

#: Multiple predecessors prove that the refusal is an ordered list, not a count or sample.
ROADMAP_MULTIPLE_INCOMPLETE_PREDECESSORS = """# Phase 3: Test Phase

## Epic E3: Earlier Epic

- [ ] **E3.1. First incomplete predecessor** per Design 09..
  - Done when: whatever the task requires.

- [ ] **E3.2. Second incomplete predecessor** per Design 09..
  - Done when: whatever the task requires.

## Epic E4: Defensive Combat

- [ ] **E4.1. Implement Total Defense** per Design 09..
  - Done when: applyTotalDefense returns the fixed effect.
"""


runner = CliRunner()


def test_l12_incomplete_predecessor_refuses_without_writing(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """An unticked earlier task refuses with 4 and names file, target and predecessor."""
    _patch_prompt_repo(tmp_path, monkeypatch, roadmap=ROADMAP_INCOMPLETE_PREDECESSOR)
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL
    )

    assert code == 4
    err = capsys.readouterr().err
    assert "03 - Test Phase.md" in err
    assert "E4.1" in err
    assert "E3.1 — An earlier unticked task" in err
    assert "Tick each predecessor once its work is merged" in err
    assert "or re-run with `--allow-incomplete-prereqs`" in err
    assert state.list_runs(_runs_root(tmp_path)) == []
    assert git.current_branch(tmp_path) == "main"
    assert not (tmp_path / "docs" / "task-prompts" / "03-E4.1-prompt.md").exists()


def test_l12_refusal_names_all_predecessors_in_roadmap_order(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _patch_prompt_repo(
        tmp_path, monkeypatch, roadmap=ROADMAP_MULTIPLE_INCOMPLETE_PREDECESSORS
    )
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL
    )

    assert code == 4
    err = capsys.readouterr().err
    first = err.index("E3.1 — First incomplete predecessor")
    second = err.index("E3.2 — Second incomplete predecessor")
    assert first < second
    assert "incomplete predecessor(s)" not in err
    assert state.list_runs(_runs_root(tmp_path)) == []


def test_l12_all_predecessors_ticked_proceeds(
    tmp_path: Path, monkeypatch
) -> None:
    """The gate reads ``[x]`` state, not the mere presence of earlier tasks."""
    _patch_prompt_repo(tmp_path, monkeypatch, roadmap=ROADMAP_COMPLETE_PREDECESSORS)
    seen, fake = _approve_first_review()
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert seen[0][0] == "task-prompt"
    assert state.list_runs(_runs_root(tmp_path))


def test_l12_later_unticked_sibling_does_not_block(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch, roadmap=ROADMAP_LATER_UNTICKED_SIBLING)
    seen, fake = _approve_first_review()
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert "E4.2" not in capsys.readouterr().err


def test_l12_line_order_beats_epic_order(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """An earlier line in a later-sorting epic still blocks."""
    _patch_prompt_repo(tmp_path, monkeypatch, roadmap=ROADMAP_EARLIER_LINE_LATER_EPIC)
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL
    )

    assert code == 4
    assert "E9.1 — A later-sorting epic on an earlier line" in capsys.readouterr().err


def test_l12_other_phase_file_does_not_block(
    tmp_path: Path, monkeypatch
) -> None:
    """Unticked entries in another phase file are out of scope (the ``file`` filter)."""
    _patch_prompt_repo(
        tmp_path,
        monkeypatch,
        extra_files={"04 - Another Phase.md": OTHER_PHASE_FIXTURE},
    )
    seen, fake = _approve_first_review()
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0


def test_l12_allow_incomplete_prereqs_warns_and_proceeds(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _patch_prompt_repo(
        tmp_path, monkeypatch, roadmap=ROADMAP_MULTIPLE_INCOMPLETE_PREDECESSORS
    )
    seen, fake = _approve_first_review()
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
        allow_incomplete_prereqs=True,
    )

    assert code == 0
    err = capsys.readouterr().err
    assert "E3.1 — First incomplete predecessor" in err
    assert "E3.2 — Second incomplete predecessor" in err
    assert "--allow-incomplete-prereqs" in err


def test_l12_dry_run_reports_incomplete_predecessors(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Dry-run reports and never refuses; it writes nothing."""
    _patch_prompt_repo(tmp_path, monkeypatch, roadmap=ROADMAP_INCOMPLETE_PREDECESSOR)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, dry_run=True
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "[dry-run] incomplete predecessors for `E4.1`" in out
    assert "E3.1 — An earlier unticked task" in out
    assert (tmp_path / "docs" / "task-prompts" / "03-E4.1-prompt.md").exists() is False


def test_l12_dry_run_states_when_there_are_none(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch, roadmap=ROADMAP_COMPLETE_PREDECESSORS)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, dry_run=True
    )

    assert code == 0
    assert (
        "[dry-run] no incomplete predecessors in `03 - Test Phase.md`."
        in capsys.readouterr().out
    )


def test_l12_refusal_precedes_the_origin_fetch(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The purely local ordering refusal must not spend a network fetch first."""
    _origin, clone = _origin_and_clone(tmp_path, roadmap=ROADMAP_INCOMPLETE_PREDECESSOR)
    _break_origin(clone)
    fetch_calls: list[tuple] = []

    def spy_fetch(*args, **kwargs):
        fetch_calls.append(args)
        return False, "boom"

    monkeypatch.setattr(git, "fetch", spy_fetch)
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(clone), label=RUN_LABEL
    )

    assert code == 4
    assert fetch_calls == []
    assert "E3.1 — An earlier unticked task" in capsys.readouterr().err


def test_l12_cli_flag_is_forwarded_to_prompt_workflow(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch, roadmap=ROADMAP_INCOMPLETE_PREDECESSOR)
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(prompt_workflow, "run", fake_run)
    result = runner.invoke(
        app,
        [
            "--repo",
            str(tmp_path),
            "prompt",
            "03",
            "E4",
            "E4.1",
            "--allow-incomplete-prereqs",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["allow_incomplete_prereqs"] is True


def test_l12_wrong_branch_refusal_precedes_the_prerequisite_check(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """On the wrong branch and out of order, the branch refusal is reported first."""
    _patch_prompt_repo(tmp_path, monkeypatch, roadmap=ROADMAP_INCOMPLETE_PREDECESSOR)
    monkeypatch.setattr(git, "current_branch", lambda repo: "feature-branch")

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL
    )

    assert code == 4
    err = capsys.readouterr().err
    assert "must run on the base branch `main`" in err
    assert "earlier tasks in the same file are incomplete" not in err


# ---------------------------------------------------------------------------
# L1.3 — the author's blocked channel (design §8.1, §10, §13; EXTRACTION.md §3.8)
# ---------------------------------------------------------------------------


def _blocked_author_stages(
    output: str,
    *,
    write_prompt: bool = False,
):
    """A fake ``run_stage`` whose author returns ``output`` (usually ``blocked: ...``).

    Kept separate from :func:`_fake_stages` so the shared normal-path fake keeps returning
    a real path: only the blocked cases write the marker.
    """
    from aidw.state import SUCCEEDED, StageRecord, run_dir

    seen: list[str] = []

    def fake_run_stage(spec, **kwargs):
        repo = kwargs["repo_root"]
        state = kwargs["state"]
        directory = run_dir(kwargs["runs_root"], state.run_id)
        stages = directory / "stages"
        stages.mkdir(parents=True, exist_ok=True)
        seen.append(spec.name)

        if spec.name == "task-prompt":
            if write_prompt:
                created = repo / "docs" / "task-prompts" / "03-E4.1-prompt.md"
                created.parent.mkdir(parents=True, exist_ok=True)
                created.write_text("prompt body\n", encoding="utf-8")

        out = stages / f"{spec.name}.out.txt"
        out.write_text(output, encoding="utf-8")
        record = StageRecord(
            name=spec.name,
            agent=spec.agent_id,
            model="test-model",
            status=SUCCEEDED,
            artifacts={"out": str(out)},
        )
        state.record_stage(record)
        return record

    return seen, fake_run_stage


def _run_log(repo: Path, run_id: str) -> str:
    return (_runs_root(repo) / run_id / "run.log").read_text(encoding="utf-8")


def test_l13_blocked_report_ends_the_run_without_authoring(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _blocked_author_stages("blocked: cited Design 09 §5.2 is absent\n")
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL
    )

    assert code == 3
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    assert seen == ["task-prompt"]  # no review stage, no fix loop
    # The author stage exited 0 with a valid report, so its own record stays succeeded;
    # it is the run that is blocked.
    author = latest.stage("task-prompt")
    assert author is not None and author.status == state.SUCCEEDED

    assert "Design 09 §5.2 is absent" in _run_log(tmp_path, latest.run_id)
    err = capsys.readouterr().err
    assert "Design 09 §5.2 is absent" in err
    worktree = _task_worktree(tmp_path)
    # The worktree Python created is reported unconditionally and kept; nothing was
    # committed or written under the author's directory.
    assert "blocked run left the task worktree" in err
    assert str(worktree) in err and "branch `03-E4.1`" in err
    assert git.status_short(worktree, paths=["docs/task-prompts"]) == ""
    assert not (worktree / "docs" / "task-prompts" / "03-E4.1-prompt.md").exists()
    assert worktree.is_dir()
    assert git.current_branch(tmp_path) == "main"


def test_l13_blocked_detection_precedes_path_resolution(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A leftover file must not be resolved as the prompt when the report is blocked."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _blocked_author_stages(
        "blocked: prerequisite branch is missing\n", write_prompt=True
    )
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL
    )

    assert code == 3
    assert seen == ["task-prompt"]
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    # The file the author left in the worktree is not committed and not removed.
    worktree = _task_worktree(tmp_path)
    leftover = worktree / "docs" / "task-prompts" / "03-E4.1-prompt.md"
    assert leftover.exists()
    assert git.status_short(worktree, paths=["docs/task-prompts"]).startswith("??")


def test_l13_leftover_prompt_is_reported_not_removed(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen, fake = _blocked_author_stages("blocked: no reason\n", write_prompt=True)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL
    )

    assert code == 3
    err = capsys.readouterr().err
    worktree = _task_worktree(tmp_path)
    assert "docs/task-prompts/03-E4.1-prompt.md" in err
    assert "neither committed nor removed" in err
    assert (worktree / "docs" / "task-prompts" / "03-E4.1-prompt.md").exists()


def test_l13_blocked_run_reports_created_worktree_unconditionally(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The Python-created worktree is named on every blocked run and never deleted (L1.3)."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen, fake = _blocked_author_stages("blocked: prerequisite missing\n")
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL
    )

    assert code == 3
    worktree = _task_worktree(tmp_path)
    err = capsys.readouterr().err
    assert f"task worktree `{worktree}`" in err
    assert "branch `03-E4.1`" in err
    assert "does not delete it" in err
    assert worktree.is_dir()
    assert git.rev_parse(tmp_path, "03-E4.1") is not None


@pytest.mark.parametrize(
    ("output", "reason"),
    [
        ("blocked: missing spec section\n", "missing spec section"),
        ("\n  blocked: leading blank line\n", "leading blank line"),
        ("BLOCKED: upper case marker\n", "upper case marker"),
        ("blocked: first line\nsecond line\n", "second line"),
    ],
)
def test_l13_marker_parsing_reaches_the_log(
    tmp_path: Path, monkeypatch, capsys, output: str, reason: str
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen, fake = _blocked_author_stages(output)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL
    )

    assert code == 3
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    log = _run_log(tmp_path, latest.run_id)
    assert reason in log
    assert reason in capsys.readouterr().err


def test_l13_empty_reason_is_still_blocked(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen, fake = _blocked_author_stages("blocked:\n")
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL
    )

    assert code == 3
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    assert "no reason" in capsys.readouterr().err


def test_l13_empty_author_output_keeps_the_not_found_failure(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """No output is not a blocked report: it stays today's exit-1 failure."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen, fake = _blocked_author_stages("")
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL
    )

    assert code == 1
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.FAILED
    assert "generated task prompt not found" in capsys.readouterr().err


def test_l13_rendered_author_prompt_and_agent_context_state_the_contract() -> None:
    """The blocked contract is in the rendered prompt and the author's context file."""
    rendered = render_prompt_file(
        toolkit_root() / "prompts" / "task-prompt.md", ["03", "E4", "E4.1"]
    )
    assert "blocked: <reason>" in rendered
    assert "a cited spec section is missing or contradicts the roadmap entry" in rendered
    assert "or, when blocked, `blocked: <reason>`" in rendered
    # EXTRACTION.md §3.2: AIDT owns branch setup, so the author neither branches nor
    # commits; the feasibility check runs before writing the prompt file.
    assert "AIDT owns branch setup" in rendered
    assert "creates the task branch and its worktree" in rendered
    assert "Feasibility check before writing the prompt file" in rendered
    assert "before creating or switching" not in rendered
    assert "create or switch" not in rendered
    assert rendered.index("AIDT owns branch setup") < rendered.index(
        "Feasibility check before writing the prompt file"
    )

    author_md = (toolkit_root() / "agents" / "task-author" / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assert "blocked: <reason>" in author_md
    assert "stop and report" in author_md
    assert "Before creating or switching to the `{phase}-{task}` branch" in author_md


def test_l21_rendered_reviewer_prompt_states_dependency_and_blocked_rules() -> None:
    """The rendered reviewer prompt carries L2.1's three rules, product-neutrally."""
    rendered = render_prompt_file(
        toolkit_root() / "prompts" / "task-review.md",
        ["docs/task-prompts/03-E4.1-prompt.md"],
    )

    rules = {
        "dependency branch": "state the revision you verified",
        "blocked not a prescription": "depends on another task's unmerged implementation",
        "suggested fix direction": "A `Suggested fix` is a direction, not a decision",
    }
    for label, phrase in rules.items():
        assert phrase in rendered, label

    # Neutrality is asserted on the added rule lines only: the pre-existing Scope
    # bullet already names `Design 21`, and bucket (i) ships as-is (EXTRACTION.md §4.2).
    added_lines = [
        line
        for line in rendered.splitlines()
        if any(phrase in line for phrase in rules.values())
    ]
    assert added_lines, "the rule phrases must be locatable as whole lines"
    for line in added_lines:
        assert "pnpm" not in line
        assert "Design 21" not in line
        assert "docs/task-prompts" not in line
        assert "origin/00-E1.5" not in line

    # Format unchanged: the finding labels, priorities and verdict tokens are byte-stable.
    assert "Priority: Must fix / Should fix / Could fix" in rendered
    assert "Confidence: 0 to 5" in rendered
    for label in (
        "What I found:",
        "Why it matters:",
        "Trigger and effect:",
        "Where:",
        "Suggested fix:",
    ):
        assert label in rendered
    assert set(re.findall(r"^Priority: (.+)$", rendered, re.MULTILINE)) == {
        "Must fix / Should fix / Could fix"
    }
    assert "Priority: Blocked" not in rendered
    assert "End with exactly one of `Approve`, `Request changes`, or `Blocked`" in rendered


def test_l22_rendered_reviewer_prompt_requires_verified_revision() -> None:
    """L2.2: `Where:` carries the file/symbol and the revision/command it was verified at."""
    prompt_path = toolkit_root() / "prompts" / "task-review.md"
    rendered = render_prompt_file(
        prompt_path, ["docs/task-prompts/03-E4.1-prompt.md"]
    )

    where_lines = [line for line in rendered.splitlines() if line.startswith("Where:")]
    assert len(where_lines) == 1, "the `Where:` finding label must appear once"
    added_line = where_lines[0]

    for phrase in (
        "name the file or symbol the finding was verified against",
        "the revision or command used to verify it",
        "nothing could be verified",
    ):
        assert phrase in added_line, phrase

    # Neutrality is asserted on the added line only: the pre-existing Scope bullet
    # already names `Design 21`, and bucket (i) ships as-is (EXTRACTION.md §4.2).
    for forbidden in ("pnpm", "Design 21", "docs/task-prompts", "origin/00-E1.5"):
        assert forbidden not in added_line, forbidden
    assert not re.search(r"\b0[0-9]-E[0-9]", added_line), "no product task-id example"

    # Format unchanged: the seven finding labels and the three verdict tokens are
    # byte-stable, so `aidw/findings.py:_LABELS` and `aidw/verdict.py` still parse.
    format_block = rendered.split("```text", 1)[1].split("```", 1)[0]
    assert [
        f"{line.split(':', 1)[0]}:"
        for line in format_block.splitlines()
        if ":" in line
    ] == [
        "Priority:",
        "Confidence:",
        "What I found:",
        "Why it matters:",
        "Trigger and effect:",
        "Where:",
        "Suggested fix:",
    ]
    assert "Revision:" not in format_block
    assert "Evidence:" not in format_block
    assert "Priority: Must fix / Should fix / Could fix" in rendered
    assert "Confidence: 0 to 5" in rendered
    for token in ("`Approve`", "`Request changes`", "`Blocked`"):
        assert token in rendered, token
    assert "End with exactly one of `Approve`, `Request changes`, or `Blocked`" in rendered

    # Rendering contract: the prompt references exactly `$1`.
    with pytest.raises(PromptError):
        render_prompt_file(prompt_path, [])


def test_l31_rendered_fixer_prompt_and_agent_context_state_verify_and_pushback() -> None:
    """L3.1: the fixer verifies the finding, may push back, and never guesses an ambiguity."""
    prompt_path = toolkit_root() / "prompts" / "task-review-fixes.md"
    rendered = render_prompt_file(
        prompt_path, ["docs/task-prompts/03-E4.1-prompt.md"]
    )

    assert "Fix the issues as you suggest" not in rendered
    phrases = (
        "verify the finding against the repository and the cited sources",
        "make the correction the evidence supports and report the disagreement",
        "state the options and stop",
        "`Blocked` escalation",
    )
    for phrase in phrases:
        assert phrase in rendered, phrase

    # Verification must precede the edit instruction, rather than merely appearing
    # somewhere in the prompt.
    assert rendered.index("Your first act is verification") < rendered.index(
        "Before making any edit"
    )
    normalized = " ".join(rendered.split())
    for source in (
        "the prompt under revision",
        "its roadmap entry",
        "the spec sections it cites",
        "the files the finding names",
    ):
        assert source in normalized, source

    # Neutrality is asserted on the added lines only: bucket (i) ships as-is
    # (EXTRACTION.md §4.2), so a whole-file absence check would over-reach.
    added_lines = [
        line for line in rendered.splitlines() if any(p in line for p in phrases)
    ]
    assert added_lines, "the L3.1 phrases must be locatable as whole lines"
    for line in added_lines:
        assert "pnpm" not in line
        assert "Design 21" not in line
        assert "docs/task-prompts" not in line
        assert not re.search(r"\b0[0-9]-E[0-9]", line), "no product task-id example"

    fixer_md = (toolkit_root() / "agents" / "task-fixer" / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assert "Fix the issues as you suggest" not in fixer_md
    assert "verify the finding against the repository and the cited sources" in fixer_md
    assert (
        "make the correction the evidence supports and report the disagreement"
        in fixer_md
    )
    assert "state the options and stop" in fixer_md
    assert "`Blocked` escalation" in fixer_md
    output = fixer_md.split("## Output", 1)[1]
    assert "For every finding whose suggested fix was wrong or contradicted the sources" in output
    assert "which finding, what the reviewer prescribed, what the evidence shows, and what you changed" in output
    # The smallest-edit rule is qualified by correctness and verification, not a
    # bare tiniest-diff mandate (L3.2 appends the consistency sweep later).
    assert "Prefer the smallest edit that satisfies the finding." not in fixer_md
    assert "smallest *correct* edit" in fixer_md
    assert "*verified* finding" in fixer_md

    # Rendering contract: the prompt references exactly `$1`.
    with pytest.raises(PromptError):
        render_prompt_file(prompt_path, [])


#: The exact six prompt-format sections L3.2's sweep must cover, in roadmap
#: order. ``Deliverables`` and the spec-citations preamble are deliberately
#: absent: L3.2 names six, and a seventh would be a roadmap deviation.
L32_SWEPT_SECTIONS = (
    "`Requirements`",
    "`Traps / prior review findings`",
    "`Explicit non-goals`",
    "`Tests`",
    "`Done when`",
    "the closing prompt-fixed/ambiguity list",
)
L32_SECTION_LIST = (
    "`Requirements`, `Traps / prior review findings`, `Explicit non-goals`, "
    "`Tests`, `Done when`, and the closing prompt-fixed/ambiguity list"
)


def test_l32_fixer_sweeps_the_document_and_names_the_six_sections() -> None:
    """L3.2: the fixer ends by sweeping the prompt and names exactly six sections."""
    prompt_path = toolkit_root() / "prompts" / "task-review-fixes.md"
    rendered = render_prompt_file(
        prompt_path, ["docs/task-prompts/03-E4.1-prompt.md"]
    )

    # The sweep is appended after L3.1's verify-then-fix text: verification stays
    # the first act and the edit still precedes the sweep, which is the last act.
    assert "re-read the whole prompt" in rendered
    assert "repair what the edit made stale" in rendered
    assert rendered.index("Your first act is verification") < rendered.index(
        "Before making any edit"
    )
    assert rendered.index("Before making any edit") < rendered.index(
        "re-read the whole prompt"
    )

    # L3.1's verify-then-fix and push-back text is unchanged.
    for phrase in (
        "verify the finding against the repository and the cited sources",
        "state the options and stop",
        "`Blocked` escalation",
    ):
        assert phrase in rendered, phrase
    assert "Fix the issues as you suggest" not in rendered

    # Both files list the same six sections and only those six.
    fixer_md = (toolkit_root() / "agents" / "task-fixer" / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    for section in L32_SWEPT_SECTIONS:
        assert section in rendered, section
        assert section in fixer_md, section
    # Match the complete comma-separated list, not merely six substrings: this
    # makes an added seventh swept section fail even if it is not Deliverables.
    assert " ".join(rendered.split()).count(L32_SECTION_LIST) == 1
    assert " ".join(fixer_md.split()).count(L32_SECTION_LIST) == 2
    assert "Deliverables" not in rendered
    assert "Deliverables" not in fixer_md

    # The report contract travels in `## Output`, never a new finding field.
    output = fixer_md.split("## Output", 1)[1]
    assert "re-checked in the sweep" in output
    assert "changed because of the sweep" in output

    # Neutrality is asserted on the added block only: bucket (i) ships as-is
    # (EXTRACTION.md §4.2), so a whole-file absence check would over-reach.
    sweep_start = rendered.index(
        "After the edit, end the stage with a consistency sweep"
    )
    sweep_end = rendered.index("the finding did not name.", sweep_start)
    added_lines = rendered[sweep_start:sweep_end].splitlines()
    assert added_lines, "the L3.2 sweep text must be locatable"
    for line in added_lines:
        assert "pnpm" not in line
        assert "Design 21" not in line
        assert "docs/task-prompts" not in line
        assert not re.search(r"\b0[0-9]-E[0-9]", line), "no product task-id example"

    # Rendering contract: the prompt still references exactly `$1`.
    with pytest.raises(PromptError):
        render_prompt_file(prompt_path, [])


# ---------------------------------------------------------------------------
# L2.4 — hand the agents an evidence bundle (design §8.1; EXTRACTION.md §3.8 / D16)
# ---------------------------------------------------------------------------

#: Target ``E4.1`` has two earlier tasks, a multi-line ``Done when`` (whose late
#: continuation line only a full-block reader keeps) and two cited sources.
ROADMAP_EVIDENCE = """# Phase 3: Test Phase

## Epic E3: Earlier Epic

- [x] **E3.1. An earlier ticked task** per Design 09..
  - Done when: it is ticked.

- [ ] **E3.2. An earlier unticked task** per Design 09..
  - Done when: it is unticked.

## Epic E4: Defensive Combat

- [ ] **E4.1. Implement Total Defense** (Design 8.1, EXTRACTION.md D16).
  - Done when: the writer emits the six elements of the bundle,
    including a later continuation line that a first-line-only parser would drop.
  - Tests: the evidence assertions below.
"""

AGENTS_EVIDENCE_FIXTURE = """# AGENTS.md

Intro prose.

## Gates — run exactly these, and only these

```bash
uv sync --frozen
uv run --frozen pytest
uv run aidw doctor
uv run aidw agents validate --strict
uv run aidw prompts check
target-repo-only gate --check
```

CI runs the frozen commands.

## Tests

This heading ends the gate section and must not be copied.
"""

EXTRACTION_EVIDENCE_FIXTURE = """# Extraction

## 3.8 Task-prompt format and repo conventions (D16)

The conventions channel.
"""


def _evidence_repo(
    tmp_path: Path, monkeypatch, *, agents_md: str | None = AGENTS_EVIDENCE_FIXTURE
) -> Path:
    """A committed bare+control repo (no ``origin``) with the evidence fixtures.

    Committed so the local base branch resolves to a real sha while ``origin/main``
    stays absent — the no-origin fixture the base-branch assertion needs — and so branch
    setup can create a real task worktree from it.
    """
    files = {
        "docs/tasks/03 - Test Phase.md": ROADMAP_EVIDENCE,
        "docs/migration/EXTRACTION.md": EXTRACTION_EVIDENCE_FIXTURE,
    }
    if agents_md is not None:
        files["AGENTS.md"] = agents_md
    _make_control_repo(tmp_path, files=files)
    return tmp_path


def _evidence_path(repo: Path, run_id: str, stage: str) -> Path:
    return _runs_root(repo) / run_id / "stages" / f"{stage}.evidence.md"


def test_l24_every_review_and_fix_stage_has_its_own_evidence_file(
    tmp_path: Path, monkeypatch
) -> None:
    """Each review/fix stage writes and points at its own *absolute* evidence file."""
    _evidence_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
        allow_incomplete_prereqs=True,
    )

    assert code == 0
    run_id = state.list_runs(_runs_root(tmp_path))[-1].run_id
    names = [name for name, _, _ in seen]
    assert names == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1-1",
        "task-review-fixes-1-2",
        "task-review-fixes-1-3",
        "task-review-reconcile-1",
        "task-review-2",
    ]
    for name in names[1:]:  # every review and fix stage, not the author
        evidence = _evidence_path(tmp_path, run_id, name)
        assert evidence.is_file(), name
        pointer = evidence.resolve()
        assert pointer.is_absolute()
        extra = _extra_for(seen, name)
        assert f"`{pointer}`" in extra, name
        # The pointer is prepended, never a replacement for the stage's own content.
        assert extra.startswith("## Evidence bundle"), name


def test_l24_fallback_whole_review_fix_also_has_its_own_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    """The unparseable-review fallback fix is the easiest ``extra`` site to miss."""
    _evidence_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_UNPARSEABLE, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
        allow_incomplete_prereqs=True,
    )

    assert code == 0
    run_id = state.list_runs(_runs_root(tmp_path))[-1].run_id
    evidence = _evidence_path(tmp_path, run_id, "task-review-fixes-1")
    assert evidence.is_file()
    extra = _extra_for(seen, "task-review-fixes-1")
    assert f"`{evidence.resolve()}`" in extra
    assert "## Review findings to address" in extra
    assert extra.index("## Evidence bundle") < extra.index(
        "## Review findings to address"
    )


def test_l24_bundle_contains_the_six_elements(tmp_path: Path, monkeypatch) -> None:
    """One bundle carries all six elements, including the full multi-line Done when."""
    _evidence_repo(tmp_path, monkeypatch)
    # Capture the base revision before the run: the reviewed-prompt commit at the end
    # advances `main`, but the bundle records the revision the stage started from.
    base_sha = git.rev_parse(tmp_path, "main")
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
        allow_incomplete_prereqs=True,
    )

    assert code == 0
    run_id = state.list_runs(_runs_root(tmp_path))[-1].run_id
    bundle = _evidence_path(tmp_path, run_id, "task-review-1").read_text(
        encoding="utf-8"
    )

    # 1. prompt path (repo-relative).
    assert "docs/task-prompts/03-E4.1-prompt.md" in bundle
    # 2. roadmap entry + full Done when (a late continuation line must survive; a
    #    first-line-only read of `RoadmapTask.done_when` would truncate it).
    assert "E4.1 — Implement Total Defense" in bundle
    assert "03 - Test Phase.md:13" in bundle
    assert (
        "including a later continuation line that a first-line-only parser would drop."
        in bundle
    )
    # 3. cited spec sections: `entry.citations` plus the non-`Design` doc ref.
    assert "design.md §8.1" in bundle
    assert "docs/migration/EXTRACTION.md §3.8" in bundle
    # 4. every predecessor's tick state, not just the unticked subset.
    assert "- [x] E3.1 — An earlier ticked task" in bundle
    assert "- [ ] E3.2 — An earlier unticked task" in bundle
    # 5. gate commands from the target repo root's AGENTS.md, bounded by `## Tests`.
    assert "uv run --frozen pytest" in bundle
    assert "uv run aidw prompts check" in bundle
    assert "target-repo-only gate --check" in bundle
    assert "This heading ends the gate section" not in bundle
    # 6. base-branch revisions: the local sha and the explicit absent remote note.
    assert base_sha and base_sha in bundle
    assert "origin/main: absent/unverifiable" in bundle


def test_l24_dry_run_writes_no_evidence_bundle(tmp_path: Path, monkeypatch) -> None:
    """The dry-run path returns before the loop: no evidence file, no pointer."""
    _evidence_repo(tmp_path, monkeypatch)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, dry_run=True
    )

    assert code == 0
    run_id = state.list_runs(_runs_root(tmp_path))[-1].run_id
    assert not _evidence_path(tmp_path, run_id, "task-review-1").exists()


def test_l24_unwritable_bundle_degrades_without_a_dangling_pointer(
    tmp_path: Path, monkeypatch
) -> None:
    """A writer failure is a warn-and-continue: normal exit, no path pointer."""
    _evidence_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)
    monkeypatch.setattr(
        prompt_workflow, "_write_evidence_bundle", lambda **kwargs: None
    )

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
        allow_incomplete_prereqs=True,
    )

    assert code == 0
    for name, _, extra in seen[1:]:
        assert ".evidence.md" not in extra, name
        assert extra.startswith("## Evidence bundle"), name
        assert "could not be written" in extra, name


def test_l24_unreadable_prompt_is_explicitly_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    """A prompt path the writer cannot read must not look like usable evidence."""
    _evidence_repo(tmp_path, monkeypatch)
    repo = TargetRepo.resolve(tmp_path)
    entries = prompt_workflow.load_tasks(tmp_path / "docs" / "tasks")
    entry = next(candidate for candidate in entries if candidate.task == "E4.1")
    directory = tmp_path / "state" / "run"

    path = prompt_workflow._write_evidence_bundle(
        stage="task-review-1",
        directory=directory,
        repo=repo,
        entry=entry,
        entries=entries,
        rel="docs/task-prompts/missing-prompt.md",
    )

    assert path is not None
    bundle = path.read_text(encoding="utf-8")
    prompt_section = bundle.split("## Task prompt", 1)[1].split(
        "## Roadmap entry", 1
    )[0]
    assert "unavailable" in prompt_section


def test_l24_writer_failure_returns_none_and_warns(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The writer itself never raises; it warns on stderr and returns ``None``."""
    _evidence_repo(tmp_path, monkeypatch)
    repo = TargetRepo.resolve(tmp_path)
    directory = tmp_path / "state" / "run"
    directory.mkdir(parents=True)
    # A file where the `stages/` directory must be makes the mkdir fail.
    (directory / "stages").write_text("blocked", encoding="utf-8")
    entries = prompt_workflow.load_tasks(tmp_path / "docs" / "tasks")
    entry = next(candidate for candidate in entries if candidate.task == "E4.1")

    path = prompt_workflow._write_evidence_bundle(
        stage="task-review-1",
        directory=directory,
        repo=repo,
        entry=entry,
        entries=entries,
        rel="docs/task-prompts/03-E4.1-prompt.md",
    )

    assert path is None
    err = capsys.readouterr().err
    assert "could not write the evidence bundle" in err
    assert "task-review-1" in err


@pytest.mark.parametrize(
    "agents_md",
    [
        None,  # missing AGENTS.md
        "# AGENTS.md\n\n## Tests\n\nNo gate section here.\n",  # missing `## Gates`
    ],
)
def test_l24_missing_gate_source_notes_the_section_unavailable(
    tmp_path: Path, monkeypatch, agents_md
) -> None:
    """A missing file or gate section degrades the section, never the run."""
    _evidence_repo(tmp_path, monkeypatch, agents_md=agents_md)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
        allow_incomplete_prereqs=True,
    )

    assert code == 0
    run_id = state.list_runs(_runs_root(tmp_path))[-1].run_id
    bundle = _evidence_path(tmp_path, run_id, "task-review-1").read_text(
        encoding="utf-8"
    )
    gate_section = bundle.split("## Gate commands", 1)[1].split("## Base-branch", 1)[0]
    assert "unavailable" in gate_section
    # The rest of the bundle is still present and usable.
    assert "docs/task-prompts/03-E4.1-prompt.md" in bundle
    assert "design.md §8.1" in bundle


# ---------------------------------------------------------------------------
# L3.3 — snapshot the prompt at every fix stage (design §9.1)
# ---------------------------------------------------------------------------


def _snapshot_path(repo: Path, run_id: str, stage: str) -> Path:
    return _runs_root(repo) / run_id / "stages" / f"{stage}.prompt.md"


def _committed_paths(repo: Path) -> list[str]:
    """The paths in ``HEAD`` — the run's single reviewed-prompt commit."""
    result = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def test_l33_every_fix_stage_gets_a_snapshot_in_stage_order(
    tmp_path: Path, monkeypatch
) -> None:
    """A two-fix-stage run leaves both snapshots under ``stages/``, in stage order."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_BOLD, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    names = [name for name, _, _ in seen]
    assert names == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1-1",
        "task-review-fixes-1-2",
        "task-review-reconcile-1",
        "task-review-2",
    ]
    run_id = state.list_runs(_runs_root(tmp_path))[-1].run_id
    snapshots = sorted((_runs_root(tmp_path) / run_id / "stages").glob("*.prompt.md"))
    assert [path.name for path in snapshots] == [
        "task-review-fixes-1-1.prompt.md",
        "task-review-fixes-1-2.prompt.md",
    ]


def test_l33_snapshot_is_the_input_to_its_fix_stage(tmp_path: Path, monkeypatch) -> None:
    """snapshot(i) carries earlier fix mutations but not its own (capture-before-run)."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_BOLD, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    run_id = state.list_runs(_runs_root(tmp_path))[-1].run_id
    first = _snapshot_path(tmp_path, run_id, "task-review-fixes-1-1").read_text(
        encoding="utf-8"
    )
    second = _snapshot_path(tmp_path, run_id, "task-review-fixes-1-2").read_text(
        encoding="utf-8"
    )
    # Stage 1-1's input is the authored prompt, before any fix marker.
    assert first == "prompt body\n"
    assert "<!-- fix round 1 -->" not in first
    # Stage 1-2's input is the prompt after stage 1-1's mutation — the fake fixer
    # appends its marker inside the stage, so capture-before-run is observable.
    assert second == "prompt body\n<!-- fix round 1 -->\n"
    # The consecutive-snapshot delta is exactly the immediately preceding stage's change.
    assert second[len(first):] == "<!-- fix round 1 -->\n"


def test_l33_fallback_whole_review_fix_also_gets_a_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    """The unparseable-review fallback fix is the second snapshot call site (L3.3)."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_UNPARSEABLE, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert [name for name, _, _ in seen] == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1",
        "task-review-reconcile-1",
        "task-review-2",
    ]
    run_id = state.list_runs(_runs_root(tmp_path))[-1].run_id
    snapshot = _snapshot_path(tmp_path, run_id, "task-review-fixes-1")
    assert snapshot.is_file()
    # Captured before the fallback fix stage's own marker.
    assert snapshot.read_text(encoding="utf-8") == "prompt body\n"


def test_l33_snapshots_are_not_tracked_and_not_committed(
    tmp_path: Path, monkeypatch
) -> None:
    """The snapshots stay run-dir artifacts: untracked, absent from the single commit."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_BOLD, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    run_id = state.list_runs(_runs_root(tmp_path))[-1].run_id
    snapshot = _snapshot_path(tmp_path, run_id, "task-review-fixes-1-1")
    worktree = _task_worktree(tmp_path)
    assert snapshot.is_file()
    assert not snapshot.is_relative_to(worktree)
    # The reviewed-prompt commit is a single, path-scoped commit on the task branch: no
    # snapshot, no per-stage commits. `.prompt.md` never appears in it (the owned prompt
    # is `03-E4.1-prompt.md`, which ends in `-prompt.md`).
    committed = _committed_paths(worktree)
    assert committed == ["docs/task-prompts/03-E4.1-prompt.md"]
    assert all(not path.endswith(".prompt.md") for path in committed)
    # Snapshots are plain run-directory artifacts, not a new state-schema field.
    state_json = (_runs_root(tmp_path) / run_id / "state.json").read_text(
        encoding="utf-8"
    )
    assert ".prompt.md" not in state_json


def test_l33_snapshot_write_failure_is_warn_only(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A raising snapshot writer must not stop the fix stages or the run (L3.3)."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_BOLD, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    def exploding_writer(**kwargs: object) -> Path:
        raise OSError("read-only run directory")

    monkeypatch.setattr(prompt_workflow, "_write_prompt_snapshot", exploding_writer)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    names = [name for name, _, _ in seen]
    assert "task-review-fixes-1-1" in names
    assert "task-review-fixes-1-2" in names
    assert "task-review-2" in names
    err = capsys.readouterr().err
    assert "could not write the prompt snapshot" in err
    assert "read-only run directory" in err


def test_l33_unreadable_prompt_skips_the_snapshot_with_a_warning(
    tmp_path: Path, capsys
) -> None:
    """A missing prompt file warns and returns ``None`` instead of raising (L3.3)."""
    directory = tmp_path / "run"

    result = prompt_workflow._write_prompt_snapshot(
        stage="task-review-fixes-1-1",
        directory=directory,
        prompt_path=tmp_path / "docs" / "missing-prompt.md",
    )

    assert result is None
    assert not (directory / "stages").exists()
    err = capsys.readouterr().err
    assert "could not read the prompt" in err
    assert "task-review-fixes-1-1" in err


def test_l33_snapshot_writer_copies_the_prompt_verbatim(tmp_path: Path) -> None:
    """The snapshot is the prompt bytes, and the source is not mutated (purity)."""
    prompt = tmp_path / "docs" / "task-prompts" / "03-E4.1-prompt.md"
    prompt.parent.mkdir(parents=True)
    body = "prompt body\n\nsecond line\n"
    prompt.write_text(body, encoding="utf-8")

    destination = prompt_workflow._write_prompt_snapshot(
        stage="task-review-fixes-1-1",
        directory=tmp_path / "run",
        prompt_path=prompt,
    )

    assert destination == (tmp_path / "run" / "stages" / "task-review-fixes-1-1.prompt.md").resolve()
    assert destination.read_text(encoding="utf-8") == body
    # Read-only: the writer never rewrites the source prompt.
    assert prompt.read_text(encoding="utf-8") == body


# ---------------------------------------------------------------------------
# L3.4 — reconcile after each fix batch (design §8.1)
# ---------------------------------------------------------------------------


def test_l34_approve_runs_no_reconcile(tmp_path: Path, monkeypatch) -> None:
    """An approving first review has no fix batch, so it must add no reconcile stage."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    names = [name for name, _, _ in seen]
    assert names == ["task-prompt", "task-review-1"]
    assert not any(name.startswith("task-review-reconcile") for name in names)


def test_l34_blocked_runs_no_reconcile(tmp_path: Path, monkeypatch) -> None:
    """A Blocked verdict short-circuits before any fix or reconcile stage (req 6)."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_BLOCKED, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=False
    )

    assert code == 3
    names = [name for name, _, _ in seen]
    assert names == ["task-prompt", "task-review-1"]
    assert not any(name.startswith("task-review-reconcile") for name in names)


def test_l34_reconcile_extra_carries_instruction_review_diff_and_pointer(
    tmp_path: Path, monkeypatch
) -> None:
    """Reconcile ``extra`` = instruction + whole review + batch diff, pointer prepended."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES)
    reconcile_specs = []

    def record_reconcile_spec(spec, **kwargs):
        if spec.name == "task-review-reconcile-1":
            reconcile_specs.append(spec)
        return fake(spec, **kwargs)

    monkeypatch.setattr(prompt_workflow, "run_stage", record_reconcile_spec)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    names = [name for name, _, _ in seen]
    assert names.index("task-review-fixes-1-3") < names.index(
        "task-review-reconcile-1"
    ) < names.index("task-review-2")
    extra = _extra_for(seen, "task-review-reconcile-1")
    # The evidence pointer is prepended, exactly as every review and fix stage (L2.4).
    assert extra.startswith("## Evidence bundle"), extra
    # A reconcile-specific instruction, never the reviewer's delta brief (L3.4 trap).
    assert prompt_workflow._RECONCILE_INSTRUCTION in extra
    assert "## Reconcile the fix batch" in extra
    assert "## Delta brief" not in extra
    # The *whole* review is passed verbatim, including its trailing round marker, not one
    # finding's block.
    assert (TASK_REVIEW_CHANGES + "\n<!-- review round 1 -->\n") in extra
    for title in (
        "The deliverable leaves a stale path reference.",
        "The prompt is silent on matrix coverage.",
        "The annotations contradict the import strategy.",
    ):
        assert title in extra
    assert "<!-- review round 1 -->" in extra
    # The combined diff is the whole batch's net effect: baseline (authored prompt)
    # against current (after every fix stage), with the round marker as an addition.
    assert "### Full review" in extra
    assert "### Combined diff for this fix batch" in extra
    assert "diff --git a/baseline/03-E4.1-prompt.md b/current/03-E4.1-prompt.md" in extra
    assert "+<!-- fix round 1 -->" in extra
    assert "aidw-prompt-diff-" not in extra
    # Ordering: instruction, then the review, then the diff.
    assert extra.index("## Reconcile the fix batch") < extra.index("### Full review")
    assert extra.index("### Full review") < extra.index(
        "### Combined diff for this fix batch"
    )
    # The stage reuses the task-fixer agent and the existing fix prompt.
    assert len(reconcile_specs) == 1
    assert reconcile_specs[0].agent_id == "task-fixer"
    assert reconcile_specs[0].prompt == (
        ToolkitPaths.resolve().prompts_dir / "task-review-fixes.md"
    )
    run_id = state.list_runs(_runs_root(tmp_path))[-1].run_id
    reconcile = next(
        s
        for s in state.list_runs(_runs_root(tmp_path))[-1].stages
        if s.name == "task-review-reconcile-1"
    )
    assert reconcile.agent == "task-fixer"
    # L3.3's snapshot writer is scoped to ``task-review-fixes-*``; reconcile gets none.
    assert not (
        _runs_root(tmp_path) / run_id / "stages" / "task-review-reconcile-1.prompt.md"
    ).exists()


def test_l34_reconcile_failure_stops_the_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A reconcile stage that does not succeed fails the run, like a fix-stage failure."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    from aidw.state import FAILED

    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, reconcile_status=FAILED)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 1
    names = [name for name, _, _ in seen]
    # The whole fix batch ran before the reconcile; nothing followed the failure.
    assert "task-review-fixes-1-3" in names
    assert "task-review-reconcile-1" in names
    assert "task-review-2" not in names
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.FAILED
    # L4.2 review follow-up #31: a round line is emitted only after reconcile succeeds;
    # the failed reconcile must not leave a predicted fixes count in stdout.
    captured = capsys.readouterr()
    assert "round 1:" not in captured.out


def test_l34_render_reconcile_is_pure_and_degrades_when_unreadable(
    tmp_path: Path,
) -> None:
    """``_render_reconcile`` never mutates its inputs and degrades, not raises (req 3)."""
    baseline = "prompt\n"
    current = "prompt\n<!-- fix round 1 -->\n"
    review = "Review text with trailing spaces  \n"

    brief = prompt_workflow._render_reconcile(
        index=1,
        review_text=review,
        baseline=baseline,
        current=current,
        rel="docs/task-prompts/03-E4.1-prompt.md",
    )

    assert prompt_workflow._RECONCILE_INSTRUCTION in brief
    assert review in brief
    assert "+<!-- fix round 1 -->" in brief
    # Purity: the caller's strings are untouched.
    assert baseline == "prompt\n"
    assert current == "prompt\n<!-- fix round 1 -->\n"
    # An unreadable prompt degrades to the explicit unavailable note, never an empty diff.
    degraded = prompt_workflow._render_reconcile(
        index=1,
        review_text=review,
        baseline=None,
        current=None,
        rel="docs/task-prompts/03-E4.1-prompt.md",
    )
    assert prompt_workflow._DIFF_UNAVAILABLE in degraded
    assert review in degraded
    assert "diff --git" not in degraded


# ---------------------------------------------------------------------------
# L4.2 — record what was accepted and what it cost (design §9.2, §9.3)
# ---------------------------------------------------------------------------


def test_l42_loop_summary_renders_ambiguous_and_derives_fixes_after() -> None:
    """`_loop_summary` is pure, renders `verdict=ambiguous`, and derives
    `fixes_after_last_review` from the last round (never a hardcoded constant)."""
    rounds = [(1, 3, 3), (2, 3, 0)]

    summary = prompt_workflow._loop_summary(
        verdict=None, revisions=1, max_revisions=3, rounds=rounds
    )

    assert summary == (
        "verdict=ambiguous; revisions=1; max_revisions=3; rounds=2; findings=3/3; "
        "fixes=3/0; approved=no; fixes_after_last_review=no"
    )
    # Purity: the caller's list is untouched.
    assert rounds == [(1, 3, 3), (2, 3, 0)]
    # A last round that ran fixes would be flagged — the field is derived, not fixed.
    assert "fixes_after_last_review=yes" in prompt_workflow._loop_summary(
        verdict="Approve", revisions=1, max_revisions=3, rounds=[(1, 3, 3)]
    )
    # Approve on round 1: one round, no fix batch, reviewer approved.
    assert "rounds=1; findings=3; fixes=0; approved=yes" in prompt_workflow._loop_summary(
        verdict="Approve", revisions=0, max_revisions=3, rounds=[(1, 3, 0)]
    )


def test_l42_partial_parse_fallback_keeps_findings_count(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A malformed block among clean ones still counts as a finding, and the round runs
    one whole-review fallback stage (Req 1: 2 clean + 1 malformed records findings=3,
    fixes=1)."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    partial = TASK_REVIEW_CHANGES.replace("Priority: Could fix", "Priority: Eventually")
    assert partial.count("Priority: Eventually") == 1
    seen, fake = _fake_stages(partial, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    names = [name for name, _, _ in seen]
    # The malformed priority forces the whole-review fallback: one stage, not three.
    assert names == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1",
        "task-review-reconcile-1",
        "task-review-2",
    ]
    captured = capsys.readouterr()
    assert "round 1: findings=3 fixes=1" in captured.out


def test_l42_human_denial_keeps_reviewer_verdict_and_denied_decision(
    tmp_path: Path, monkeypatch
) -> None:
    """`approved=yes` (the reviewer approved) sits beside `decision=denied` (the human
    refused): each keeps its own field (Req 2)."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("AIDW_NONINTERACTIVE", "1")
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=False,
        require_approval=True,
    )

    assert code == 3
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "denied"
    assert "verdict=Approve" in gate.detail
    assert "approved=yes" in gate.detail
    assert "fixes_after_last_review=no" in gate.detail


def test_l42_run_log_carries_the_per_round_summary_and_blocked_line(
    tmp_path: Path, monkeypatch
) -> None:
    """The terminal `Request changes` run logs the summary and says BLOCKED (Req 4)."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 3
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    log = _run_log(tmp_path, latest.run_id)
    assert "approve-task-prompt denied; run BLOCKED" in log
    for token in ("rounds=3", "findings=3/3/3", "fixes=3/3/0", "approved=no"):
        assert token in log


def test_l42_terminal_round_without_a_verdict_records_ambiguous(
    tmp_path: Path, monkeypatch
) -> None:
    """A terminal round that parsed no verdict renders `verdict=ambiguous` (Req 2)."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    no_verdict = TASK_REVIEW_CHANGES.split("## Verdict")[0]
    seen, fake = _fake_stages(no_verdict, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 3
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "denied"
    assert "verdict=ambiguous" in gate.detail
    assert "rounds=3" in gate.detail
    assert "findings=3/3/3" in gate.detail
    assert "fixes=3/3/0" in gate.detail
    assert "approved=no" in gate.detail
    assert "fixes_after_last_review=no" in gate.detail


def test_l42_empty_review_exit_stays_gate_less(
    tmp_path: Path, monkeypatch
) -> None:
    """An empty review message is a verdict-less failure: no gate, no summary (Req 3)."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    from aidw.state import SUCCEEDED, StageRecord, run_dir

    def fake_run_stage(spec, **kwargs):
        repo = kwargs["repo_root"]
        state = kwargs["state"]
        directory = run_dir(kwargs["runs_root"], state.run_id)
        stages = directory / "stages"
        stages.mkdir(parents=True, exist_ok=True)
        if spec.name == "task-prompt":
            created = repo / "docs" / "task-prompts" / "03-E4.1-prompt.md"
            created.parent.mkdir(parents=True, exist_ok=True)
            created.write_text("prompt body\n", encoding="utf-8")
        out = stages / f"{spec.name}.out.txt"
        # The author's report resolves the prompt path; only the review is empty.
        body = "prompt body\n" if spec.name == "task-prompt" else "   \n"
        out.write_text(body, encoding="utf-8")
        record = StageRecord(
            name=spec.name,
            agent=spec.agent_id,
            model="test-model",
            status=SUCCEEDED,
            artifacts={"out": str(out)},
        )
        state.record_stage(record)
        return record

    monkeypatch.setattr(prompt_workflow, "run_stage", fake_run_stage)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 1
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.FAILED
    assert not any(g.name == "approve-task-prompt" for g in latest.gates)
    log = _run_log(tmp_path, latest.run_id)
    assert "produced no final message" in log
    assert "approved=" not in log
    assert "fixes_after_last_review" not in log


# ---------------------------------------------------------------------------
# L4.3 — configurable revision budget (design §8.1, §12)
# ---------------------------------------------------------------------------


def test_l43_budget_two_ends_at_review_two(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """`run(max_revisions=2)` runs one fix batch + reconcile, then the review-2 terminal:
    `code == 3`, no round-2 fixes/reconcile/round-3, and `max_revisions=2` in the summary."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
        max_revisions=2,
    )

    assert code == 3
    names = [name for name, _, _ in seen]
    assert names == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1-1",
        "task-review-fixes-1-2",
        "task-review-fixes-1-3",
        "task-review-reconcile-1",
        "task-review-2",
    ]
    assert not any(name.startswith("task-review-fixes-2") for name in names)
    assert "task-review-reconcile-2" not in names
    assert "task-review-3" not in names

    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "denied"
    for token in ("max_revisions=2", "rounds=2", "revisions=1", "approved=no"):
        assert token in gate.detail
    assert "max_revisions=2" in _run_log(tmp_path, latest.run_id)
    # The effective value is visible on stdout as well as in the gate detail/run.log.
    assert "max_revisions=2" in capsys.readouterr().out


def test_l43_budget_four_runs_four_reviews(
    tmp_path: Path, monkeypatch
) -> None:
    """`run(max_revisions=4)` approving at review-4 runs three fix batches + four reviews,
    succeeds, and reports `max_revisions=4`, `revisions=3`, `rounds=4` (Req 1)."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=4)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
        max_revisions=4,
    )

    assert code == 0
    names = [name for name, _, _ in seen]
    assert names[-1] == "task-review-4"
    # Three fix batches (rounds 1-3), each with its reconcile, then the approving review-4.
    for round_n in (1, 2, 3):
        assert f"task-review-fixes-{round_n}-1" in names
        assert f"task-review-reconcile-{round_n}" in names
    assert not any(name.startswith("task-review-fixes-4") for name in names)
    assert "task-review-5" not in names

    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.SUCCEEDED
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "approved"
    for token in (
        "verdict=Approve",
        "max_revisions=4",
        "revisions=3",
        "rounds=4",
        "approved=yes",
    ):
        assert token in gate.detail
    assert "max_revisions=4" in _run_log(tmp_path, latest.run_id)


def test_l43_budget_one_is_review_only_from_the_start(
    tmp_path: Path, monkeypatch
) -> None:
    """`run(max_revisions=1)` makes review-1 terminal: `code == 3`, no fix/reconcile stage
    at all (the `- 1` bound holds at the floor)."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
        max_revisions=1,
    )

    assert code == 3
    names = [name for name, _, _ in seen]
    assert names == ["task-prompt", "task-review-1"]
    assert not any(name.startswith("task-review-fixes") for name in names)
    assert not any(name.startswith("task-review-reconcile") for name in names)
    assert "task-review-2" not in names

    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "denied"
    for token in ("max_revisions=1", "rounds=1", "revisions=0"):
        assert token in gate.detail
    assert "max_revisions=1" in _run_log(tmp_path, latest.run_id)


def test_l43_effective_budget_is_reported_on_approve_exit(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """An approved review reports the effective budget in every summary sink."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
        max_revisions=4,
    )

    assert code == 0
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "approved"
    assert "max_revisions=4" in gate.detail
    assert "max_revisions=4" in _run_log(tmp_path, latest.run_id)
    assert "max_revisions=4" in capsys.readouterr().out


def test_l43_effective_budget_is_reported_for_blocked_exit(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A Blocked verdict reports the effective budget in every summary sink."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_BLOCKED_DEPENDENCY, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
        max_revisions=4,
    )

    assert code == 3
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "denied"
    assert "max_revisions=4" in gate.detail
    assert "max_revisions=4" in _run_log(tmp_path, latest.run_id)
    assert "max_revisions=4" in capsys.readouterr().out


def test_l43_effective_budget_is_reported_on_human_gate_denial(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A reviewer-approved result that the human gate denies still reports the budget."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("AIDW_NONINTERACTIVE", "1")
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        require_approval=True,
        max_revisions=2,
    )

    assert code == 3
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "denied"
    assert "verdict=Approve" in gate.detail
    assert "max_revisions=2" in gate.detail
    assert "max_revisions=2" in _run_log(tmp_path, latest.run_id)
    assert "max_revisions=2" in capsys.readouterr().out


def test_l43_cli_flag_is_forwarded_to_prompt_workflow(
    tmp_path: Path, monkeypatch
) -> None:
    """`--max-revisions 5` reaches `prompt_workflow.run(max_revisions=5)`."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(prompt_workflow, "run", fake_run)
    result = runner.invoke(
        app,
        [
            "--repo",
            str(tmp_path),
            "prompt",
            "03",
            "E4",
            "E4.1",
            "--max-revisions",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["max_revisions"] == 5


@pytest.mark.parametrize("value", ["0", "-1"])
def test_l43_nonpositive_budget_is_a_usage_error_before_any_run(
    tmp_path: Path, monkeypatch, value: str
) -> None:
    """`--max-revisions 0`/negative exits 2 in the CLI and never starts the workflow."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    called: list[dict] = []

    def fake_run(**kwargs):
        called.append(kwargs)
        return 0

    monkeypatch.setattr(prompt_workflow, "run", fake_run)
    result = runner.invoke(
        app,
        [
            "--repo",
            str(tmp_path),
            "prompt",
            "03",
            "E4",
            "E4.1",
            "--max-revisions",
            value,
        ],
    )

    assert result.exit_code == 2, result.output
    assert "must be >= 1" in result.output
    assert called == []
    # No run directory was created and nothing was authored.
    assert not _runs_root(tmp_path).exists()
    assert not (tmp_path / "docs" / "task-prompts" / "03-E4.1-prompt.md").exists()


# ---------------------------------------------------------------------------
# L5.1 — give the author the reviewer's rubric before it submits (design §8.1)
# ---------------------------------------------------------------------------

#: The seven decisions L5.1 requires the author to settle before submitting, each
#: with a stable key phrase the rendered self-check must carry.
L51_DECISIONS = (
    "failure-path precedence when two failures are possible",
    "per-mode output contracts on the failure path",
    "the complete label/key vocabulary",
    "why the enumerated set is complete",
    "exact comparison semantics",
    "where new shared code lives",
    "one proof per requirement",
)

#: The self-check is a compact shadow of the reviewer's nine-step review order, not a
#: transcription of it. The review order plus its sub-bullets is far longer, so this
#: bound fails a copy while leaving room for the intro and the nine checks.
L51_SECTION_LINE_BOUND = 30

#: Package managers, product tokens, product paths and brand/task-id shapes that must
#: never appear in the *added* lines (EXTRACTION.md §3.8 / §4.2 bucket (iii)).
L51_FORBIDDEN_PACKAGE_MANAGERS = re.compile(r"\b(pnpm|npm|yarn|uv)\b")
L51_FORBIDDEN_TOKENS = (
    "Design 21",
    "Zod",
    "fast-check",
    "catalog",
    "vectors",
    "@mythical-forge",
)
L51_FORBIDDEN_PATHS = (
    "docs/task-prompts",
    "docs/specs/",
    "infra/",
    "apps/",
    "packages/",
)


def _l51_review_order_steps() -> list[str]:
    """The bolded lead of each ordered item in ``task-review.md``'s review order."""
    reviewer = (toolkit_root() / "prompts" / "task-review.md").read_text(
        encoding="utf-8"
    )
    section = reviewer.split("## Review order", 1)[1].split("\n## ", 1)[0]
    # The bolded lead carries a trailing period; drop it so the bare step name is
    # what the self-check lines must name.
    return [
        match.group(1).rstrip(".")
        for match in re.finditer(r"^\d+\.\s+\*\*(.+?)\*\*", section, re.MULTILINE)
    ]


def _l51_self_check_lines(rendered: str) -> list[str]:
    """The ``## Pre-submit self-check`` section, from its heading to the next heading."""
    rest = rendered[rendered.index("## Pre-submit self-check") :]
    end = rest.find("\n## ", 1)
    return (rest if end == -1 else rest[:end]).splitlines()


#: The pointer L5.1 adds to the ask-if-ambiguous clause, located by this phrase.
L51_POINTER_PHRASE = "Before returning the prompt, run the pre-submit"


def test_l51_rendered_author_prompt_carries_the_review_order_self_check() -> None:
    """L5.1: the rendered author prompt carries the compact pre-submit self-check."""
    prompt_path = toolkit_root() / "prompts" / "task-prompt.md"
    rendered = render_prompt_file(prompt_path, ["02", "L5", "L5.1"])
    normalized = " ".join(rendered.split())

    assert "## Pre-submit self-check" in rendered
    # The checklist follows the final subsection of the section-by-section guidance.
    assert rendered.index("## Pre-submit self-check") > rendered.index(
        "### Ask-if-ambiguous clause"
    )
    for phrase in L51_DECISIONS:
        assert phrase in rendered, phrase

    # It walks the reviewer's review order and reuses that clause's `prompt-fixed`
    # contract instead of defining a second label.
    assert "walk the same ground as the reviewer's `## Review order`" in normalized
    assert "`task-review.md`" in rendered
    assert "`prompt-fixed`" in rendered
    assert (
        "the one label that clause already defines; do not invent a second"
        in normalized
    )
    # The pointer from the ask-if-ambiguous clause back to the self-check.
    assert "run the pre-submit self-check below" in rendered

    # L1.3's blocked/feasibility contract still renders (its own test stays green).
    assert "blocked: <reason>" in rendered
    assert "Feasibility check before writing the prompt file" in rendered

    lines = _l51_self_check_lines(rendered)
    # Heading, setup and the nine checks — never a transcription of the review order
    # (nine steps plus their sub-bullets).
    assert len(lines) <= L51_SECTION_LINE_BOUND, len(lines)

    # Each check is exactly one line and names the review-order step it shadows.
    checks = [line for line in lines if re.match(r"^\d+\.\s+\*\*", line)]
    assert len(checks) == 9, checks
    first_check = lines.index(checks[0])
    check_block = lines[first_check:]
    # A wrapped continuation would otherwise be invisible to the numbered-line
    # filter above; every nonblank line in the check block must itself be a check.
    assert all(
        not line.strip() or re.match(r"^\d+\.\s+\*\*", line)
        for line in check_block
    ), check_block
    order_steps = _l51_review_order_steps()
    assert len(order_steps) == 9, order_steps
    for step in order_steps:
        assert any(step in line for line in checks), step

    # No self-check line appears verbatim in the reviewer's review order.
    reviewer = (toolkit_root() / "prompts" / "task-review.md").read_text(
        encoding="utf-8"
    )
    review_order = reviewer.split("## Review order", 1)[1].split("\n## ", 1)[0]
    self_check = {line.strip() for line in lines if line.strip()}
    review_lines = {line.strip() for line in review_order.splitlines() if line.strip()}
    assert not (self_check & review_lines)

    # Neutrality is asserted on the added lines only: the prompt is ~100%
    # product-specific today and stays that way until E7.1 (EXTRACTION.md §3.8).
    pointer_start = rendered.index(L51_POINTER_PHRASE)
    pointer_end = rendered.index("\n", pointer_start)
    added_lines = [rendered[pointer_start:pointer_end], *lines]
    assert added_lines
    for line in added_lines:
        assert not L51_FORBIDDEN_PACKAGE_MANAGERS.search(line), line
        for token in L51_FORBIDDEN_TOKENS:
            assert token not in line, (token, line)
        for path in L51_FORBIDDEN_PATHS:
            assert path not in line, (path, line)
        assert not re.search(r"\b0[0-9]-E[0-9]", line), "no product task-id example"

    # Rendering contract: `$1`/`$2`/`$3`; fewer than three args raises, extras are
    # ignored (aidw/prompts.py raises only when the highest index exceeds the count).
    with pytest.raises(PromptError):
        render_prompt_file(prompt_path, ["02", "L5"])
    assert render_prompt_file(prompt_path, ["02", "L5", "L5.1", "extra"])


# ---------------------------------------------------------------------------
# L5.2 — tell the author to reconcile gates and verifiers (EXTRACTION.md
# §3.4/§3.8, D16; R10/R14)
# ---------------------------------------------------------------------------

#: The injection source L5.2 names — never the commands themselves.
L52_INJECTION_SOURCES = (
    "root `AGENTS.md`",
    "aidw/conventions.md",
)

#: The two neutral obligations the rewrite must keep; they are the reconciliation the
#: roadmap's Done-when demands, so dropping them under-neutralises.
L52_KEPT_OBLIGATIONS = (
    "state the observable effect on existing data",
    "fix the instruction or make the reconciliation an explicit deliverable",
)

#: Product verifier tokens and paths L5.2 removes from the reconciliation section.
#: They remain valid elsewhere in the prompt until E7.1/E7.2 neutralise those lines.
L52_REMOVED_VERIFIER_TOKENS = (
    "srd:matrix-check",
    "srd:check-tests",
    "srd-traceability",
    "--jest-json",
)
L52_REMOVED_GENERIC_VERIFIER_TOKENS = ("srd:", "catalog", "vectors", "matrix")
L52_REMOVED_PRODUCT_PATHS = (
    "services/",
    "packages/",
    "tests/integration/",
    "docs/conventions/",
)
L52_PACKAGE_MANAGERS = re.compile(r"\b(pnpm|npm|yarn|uv)\b")


def _l52_reconciliation_section(rendered: str) -> str:
    """The ``### Gate and verifier reconciliation`` section, heading to heading."""
    start = rendered.index("### Gate and verifier reconciliation")
    end = rendered.index("\n### ", start + 1)
    return rendered[start:end]


def _l52_gate_impact_lines(rendered: str) -> str:
    """The Prompt Format's ``Gate impact:`` clause, from its first line to its last."""
    start = rendered.index("<If this task changes a checker")
    end = rendered.index("stays green.>", start) + len("stays green.>")
    return rendered[start:end]


def test_l52_rendered_author_prompt_reconciles_gates_against_the_repo() -> None:
    """L5.2: the rendered author prompt names the gate source and requires the commands."""
    prompt_path = toolkit_root() / "prompts" / "task-prompt.md"
    rendered = render_prompt_file(prompt_path, ["02", "L5", "L5.2"])
    section = _l52_reconciliation_section(rendered)
    normalized = " ".join(section.split())

    # It requires the reconciliation and names the injection source.
    for source in L52_INJECTION_SOURCES:
        assert source in section, source
    assert "the exact gate commands" in normalized
    assert "from that source" in normalized
    assert "gate list" in normalized
    for obligation in L52_KEPT_OBLIGATIONS:
        assert obligation in normalized, obligation

    # No product command, verifier token, package manager or product path survives
    # in the changed section (the same trap L5.1's added-lines pattern guards: the
    # rest of the prompt still names them until E7.1/E7.2).
    for token in (*L52_REMOVED_VERIFIER_TOKENS, *L52_REMOVED_GENERIC_VERIFIER_TOKENS):
        assert token not in section, token
    for path in L52_REMOVED_PRODUCT_PATHS:
        assert path not in section, path
    assert not L52_PACKAGE_MANAGERS.search(section), section

    # The kept "Gate impact:" line keeps its full trigger set and no command name.
    gate_impact = _l52_gate_impact_lines(rendered)
    assert '"Gate impact:"' in gate_impact
    for trigger in ("checker", "status vocabulary", "catalog reference", "CI gate"):
        assert trigger in gate_impact, trigger
    gate_impact_normalized = " ".join(gate_impact.split())
    assert (
        "naming the checker and the pre-existing entries it affects"
        in gate_impact_normalized
    )
    assert (
        "confirm against the current repo that the gate stays green"
        in gate_impact_normalized
    )
    assert not L52_PACKAGE_MANAGERS.search(gate_impact), gate_impact
    for token in (*L52_REMOVED_VERIFIER_TOKENS, "srd:", "vectors", "matrix"):
        assert token not in gate_impact, token

    # Rendering arity unchanged: three args, fewer raise, extras ignored.
    with pytest.raises(PromptError):
        render_prompt_file(prompt_path, ["02", "L5"])
    assert render_prompt_file(prompt_path, ["02", "L5", "L5.2", "extra"])


# ---------------------------------------------------------------------------
# L5.3 — check the conciseness budget in the workflow (design §8.1,
# prompts/task-prompt.md §Conciseness budget)
# ---------------------------------------------------------------------------

#: One numbered `Requirements:` item padded past the 15000-byte budget, plus a short
#: second item. Requirement 1 is the longest by word count, so the warning must name it.
L53_OVER_BYTES_PAD_WORDS = 4000
L53_OVER_BYTES_PROMPT = (
    "Requirements:\n"
    f"1. alpha {'pad ' * L53_OVER_BYTES_PAD_WORDS}\n"
    "2. short one\n"
)

#: Within the byte budget but over the 150-line budget. The `## Filler` heading ends the
#: `Requirements:` section, so the filler does not inflate a requirement's word count.
L53_OVER_LINES_PROMPT = (
    "Requirements:\n"
    "1. alpha beta gamma\n"
    "2. short one\n"
    "## Filler\n"
    + "\n".join(f"filler line {index}" for index in range(160))
    + "\n"
)

#: Within both budgets.
L53_IN_BUDGET_PROMPT = "Requirements:\n1. alpha beta gamma\n2. short one\n"

#: Over the byte budget with no `Requirements:` section, so attribution degrades to totals.
L53_NO_REQUIREMENTS_PROMPT = "## Context\n" + "x" * 16000 + "\n"

#: The standard task-prompt shape (`prompts/task-prompt.md`): numbered `Requirements:`
#: items with indented continuations, then the trailing sections (Traps / Non-goals /
#: Deliverables / Tests / Done-when) as plain column-0 labels and bullets — no `#`
#: heading ends the list (review follow-up #38, PR #36 finding F1).
L53_TRAILING_SECTIONS_PROMPT = (
    "Task: Check the conciseness budget in the workflow (Design 8.1)\n"
    "\n"
    "Requirements:\n"
    "1. First requirement, short.\n"
    "2. Second requirement with an indented\n"
    "   continuation line.\n"
    "3. Third requirement that is the truly longest one by word count.\n"
    "\n"
    "Traps / prior review findings:\n"
    "- A trap bullet with several words that must not fold into requirement 3.\n"
    "\n"
    "Explicit non-goals — do NOT do these in this task:\n"
    "- Another plain-label trailing section with more words.\n"
    "\n"
    "Deliverables:\n"
    "- aidw/workflows/prompt.py\n"
    "\n"
    "Tests (what to prove, not the literal expects):\n"
    "- tests/test_prompt_workflow.py\n"
    "\n"
    "Done when:\n"
    "- uv run --frozen pytest is green.\n"
)

#: Over the byte budget in the standard task-prompt shape (review follow-up #38, PR #36
#: finding F1): requirement 2 is padded truly longest, and the Traps bullet is padded
#: longer still, so folding the trailing sections into requirement 3 would name the
#: wrong requirement with an inflated word count.
L53_STANDARD_OVER_BYTES_PROMPT = (
    "Task: Pad a prompt over the budget\n"
    "\n"
    "Requirements:\n"
    "1. alpha beta\n"
    f"2. gamma {'pad ' * L53_OVER_BYTES_PAD_WORDS}delta\n"
    "3. short tail item\n"
    "\n"
    "Traps / prior review findings:\n"
    f"- {'trap ' * (L53_OVER_BYTES_PAD_WORDS + 100)}bullet\n"
    "\n"
    "Explicit non-goals — do NOT do these in this task:\n"
    "- non-goal bullet\n"
    "\n"
    "Deliverables:\n"
    "- aidw/workflows/prompt.py\n"
    "\n"
    "Tests (what to prove, not the literal expects):\n"
    "- tests/test_prompt_workflow.py\n"
    "\n"
    "Done when:\n"
    "- uv run --frozen pytest is green.\n"
)

#: Matches the count line the workflow prints on stdout for every produced prompt.
L53_BUDGET_LINE_RE = re.compile(r"budget: \d+ lines / [\d.]+KB")


def _run_l53_case(
    tmp_path: Path,
    monkeypatch,
    *,
    body: str,
    strict: bool = False,
    sibling_prompts: dict[str, str] | None = None,
):
    """Run the prompt workflow with a fake author that writes ``body`` and review 1 approving.

    ``sibling_prompts`` seeds extra files under ``docs/task-prompts/`` before the run, so a
    test can prove the check reads only the generated path and never scans the directory.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    if sibling_prompts:
        prompts_dir = tmp_path / "docs" / "task-prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        for name, text in sibling_prompts.items():
            (prompts_dir / name).write_text(text, encoding="utf-8")
        # Commit the siblings so the real clean-tree preflight still passes.
        _run_git(["add", "."], tmp_path)
        _run_git(["commit", "-qm", "siblings"], tmp_path)
    seen, fake = _fake_stages(
        "## Verdict\n\n**Approve**\n",
        approve_review=1,
        prompt_body=body,
    )
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)
    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
        strict=strict,
    )
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    return code, seen, latest


def test_l53_over_byte_budget_warns_by_requirement_and_still_approves(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """L5.3: an over-byte prompt warns naming its longest requirement, then reviews on."""
    code, seen, latest = _run_l53_case(
        tmp_path, monkeypatch, body=L53_OVER_BYTES_PROMPT
    )
    captured = capsys.readouterr()

    assert code == 0
    assert latest.status == state.SUCCEEDED
    # The default check is advisory: the review still ran and approved.
    assert "task-review-1" in [name for name, _, _ in seen]
    # The count line prints for every produced prompt regardless of the outcome.
    assert L53_BUDGET_LINE_RE.search(captured.out), captured.out
    assert captured.out.index("prompt: docs/task-prompts/03-E4.1-prompt.md") < captured.out.index(
        "budget:"
    )
    # The warning names the offending requirement and its word count, not only the total.
    assert "over the conciseness budget" in captured.err
    assert (
        f"requirement 1 ({1 + L53_OVER_BYTES_PAD_WORDS} words)" in captured.err
    ), captured.err


def test_l53_over_line_budget_warns_by_requirement_and_still_approves(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """L5.3: an over-line prompt trips identically to the byte case."""
    code, seen, latest = _run_l53_case(
        tmp_path, monkeypatch, body=L53_OVER_LINES_PROMPT
    )
    captured = capsys.readouterr()

    assert code == 0
    assert latest.status == state.SUCCEEDED
    assert "task-review-1" in [name for name, _, _ in seen]
    assert L53_BUDGET_LINE_RE.search(captured.out), captured.out
    assert "over the conciseness budget" in captured.err
    assert "requirement 1 (3 words)" in captured.err, captured.err


def test_l53_strict_over_budget_refuses_before_review(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """L5.3 + Req 4: `--strict` refuses (exit 1, FAILED, no gate) before any review."""
    code, seen, latest = _run_l53_case(
        tmp_path, monkeypatch, body=L53_OVER_BYTES_PROMPT, strict=True
    )
    captured = capsys.readouterr()

    assert code == 1
    assert latest.status == state.FAILED
    # The one-line refusal goes to stderr and names the over-budget prompt and requirement.
    assert "refusing (--strict)" in captured.err
    assert "docs/task-prompts/03-E4.1-prompt.md" in captured.err
    assert (
        f"requirement 1 ({1 + L53_OVER_BYTES_PAD_WORDS} words)" in captured.err
    ), captured.err
    # No review stage ran: the author is the only stage the fake saw.
    assert [name for name, _, _ in seen] == ["task-prompt"]
    # The author output remains in place after refusal; strict mode does not undo its
    # committed/agent-owned prompt (design §13, L5.3 trap).
    generated = _task_worktree(tmp_path) / "docs" / "task-prompts" / "03-E4.1-prompt.md"
    assert generated.read_text(encoding="utf-8") == L53_OVER_BYTES_PROMPT
    # A verdict-less exit records no gate and no new gate-decision vocabulary (L4.2).
    assert latest.gates == []


def test_l53_in_budget_prompt_prints_count_without_a_warning(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """L5.3: an in-budget prompt prints the count line but no size warning."""
    code, seen, latest = _run_l53_case(
        tmp_path, monkeypatch, body=L53_IN_BUDGET_PROMPT
    )
    captured = capsys.readouterr()

    assert code == 0
    assert latest.status == state.SUCCEEDED
    assert L53_BUDGET_LINE_RE.search(captured.out), captured.out
    assert "budget:" not in captured.err
    assert "over the conciseness budget" not in captured.err


def test_l53_unparseable_requirements_degrades_to_totals_only(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """L5.3 Req 3: a prompt with no parseable `Requirements:` warns on totals, never crashes."""
    code, _seen, latest = _run_l53_case(
        tmp_path, monkeypatch, body=L53_NO_REQUIREMENTS_PROMPT
    )
    captured = capsys.readouterr()

    assert code == 0
    assert latest.status == state.SUCCEEDED
    assert L53_BUDGET_LINE_RE.search(captured.out), captured.out
    assert "over the conciseness budget" in captured.err
    # Totals only: the attribution sentence is absent, not an error.
    assert "longest:" not in captured.err, captured.err
    assert "requirement" not in captured.err, captured.err


def test_l53_check_reads_only_the_generated_prompt(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """L5.3 Req 1 trap: an over-budget sibling under docs/task-prompts/ must not trip it."""
    code, _seen, latest = _run_l53_case(
        tmp_path,
        monkeypatch,
        body=L53_IN_BUDGET_PROMPT,
        sibling_prompts={"00-OLD-prompt.md": L53_OVER_BYTES_PROMPT},
    )
    captured = capsys.readouterr()

    assert code == 0
    assert latest.status == state.SUCCEEDED
    # The generated prompt is in budget, so the sibling must be ignored entirely.
    assert L53_BUDGET_LINE_RE.search(captured.out), captured.out
    assert "over the conciseness budget" not in captured.err, captured.err


def test_l53_unreadable_prompt_warns_and_never_fails_the_check(
    tmp_path: Path, capsys
) -> None:
    """L5.3 Req 3: a read/measure failure degrades to a warning, not a failed check."""
    path = tmp_path / "prompt.md"
    path.write_bytes(b"\xff\xfe not utf-8")

    reason = prompt_workflow._check_conciseness(
        path, "docs/task-prompts/00-bad-prompt.md"
    )
    captured = capsys.readouterr()

    assert reason is None
    assert "skipping the check" in captured.err
    assert "budget:" not in captured.out


def test_l53_byte_budget_boundary_is_inclusive(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """L5.3: exactly 15000 UTF-8 bytes is allowed (the trip is strictly greater)."""
    prefix = "Requirements:\n1. "
    body = prefix + ("x" * (15000 - len(prefix.encode("utf-8")) - 1)) + "\n"
    assert len(body.encode("utf-8")) == 15000
    assert len(body.splitlines()) == 2

    code, seen, latest = _run_l53_case(tmp_path, monkeypatch, body=body)
    captured = capsys.readouterr()

    assert code == 0
    assert latest.status == state.SUCCEEDED
    assert "task-review-1" in [name for name, _, _ in seen]
    assert "over the conciseness budget" not in captured.err


def test_l53_line_budget_boundary_is_inclusive(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """L5.3: exactly 150 physical lines is allowed (the trip is strictly greater)."""
    body = "Requirements:\n1. x\n" + ("filler\n" * 148)
    assert len(body.splitlines()) == 150

    code, seen, latest = _run_l53_case(tmp_path, monkeypatch, body=body)
    captured = capsys.readouterr()

    assert code == 0
    assert latest.status == state.SUCCEEDED
    assert "task-review-1" in [name for name, _, _ in seen]
    assert "over the conciseness budget" not in captured.err


def test_l53_strict_over_line_budget_refuses_before_review(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """L5.3: strict mode refuses a line-only over-budget prompt before review."""
    code, seen, latest = _run_l53_case(
        tmp_path, monkeypatch, body=L53_OVER_LINES_PROMPT, strict=True
    )
    captured = capsys.readouterr()

    assert code == 1
    assert latest.status == state.FAILED
    assert "refusing (--strict)" in captured.err
    assert "requirement 1 (3 words)" in captured.err
    assert [name for name, _, _ in seen] == ["task-prompt"]
    assert latest.gates == []


def test_l53_equal_longest_requirements_are_all_named(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """L5.3: attribution names every requirement tied for the longest item."""
    body = "Requirements:\n" + "\n".join(
        [f"{number}. " + (f"word{number} " * 2000) for number in (1, 2)]
    )
    code, _seen, latest = _run_l53_case(tmp_path, monkeypatch, body=body)
    captured = capsys.readouterr()

    assert code == 0
    assert latest.status == state.SUCCEEDED
    assert "requirement 1 (2000 words)" in captured.err
    assert "requirement 2 (2000 words)" in captured.err


def test_l53_trailing_sections_end_the_requirements_list() -> None:
    """L5.3 (review follow-up #38): plain-label trailing sections are not item text.

    The task-prompt format separates Traps / Non-goals / Deliverables / Tests /
    Done-when with column-0 labels and bullets, not `#` headings; folding them into
    the last numbered item inflates its word count and misattributes the warning.
    """
    items = prompt_workflow._requirement_items(L53_TRAILING_SECTIONS_PROMPT)

    assert [number for number, _ in items] == [1, 2, 3]
    # The last item's word count excludes the trailing sections.
    assert items[-1] == (
        3,
        "Third requirement that is the truly longest one by word count.",
    )
    # An indented continuation line still joins its own item.
    assert items[1] == (2, "Second requirement with an indented continuation line.")
    # The longest is the truly longest item, not the last one inflated by the fold.
    assert prompt_workflow._longest_requirements(items) == [(3, 11)]


def test_l53_standard_format_over_budget_names_the_true_longest_requirement(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """L5.3 (review follow-up #38): a standard-format over-budget prompt warns truthfully.

    A prompt in the repo's standard shape (trailing sections after the list) that
    trips the byte budget must name requirement 2, the truly longest item, with its
    own word count — not the last item inflated by the folded Traps/Non-goals text.
    """
    code, _seen, latest = _run_l53_case(
        tmp_path, monkeypatch, body=L53_STANDARD_OVER_BYTES_PROMPT
    )
    captured = capsys.readouterr()

    assert code == 0
    assert latest.status == state.SUCCEEDED
    assert "over the conciseness budget" in captured.err
    assert (
        f"requirement 2 ({2 + L53_OVER_BYTES_PAD_WORDS} words)" in captured.err
    ), captured.err
    # The last item keeps its own word count, so it is never named here.
    assert "requirement 3 (" not in captured.err, captured.err


# ---------------------------------------------------------------------------
# L6.1 — pin the E1.6 shape: an unticked predecessor plus a stale base (design §15)
# ---------------------------------------------------------------------------


def _e16_stale_base_with_unticked_predecessor(
    tmp_path: Path,
) -> tuple[Path, Path, str]:
    """The E1.6 shape: a base provably behind ``origin`` *and* an unticked predecessor.

    E1.6 was authored on a stale local ``main`` while its predecessor was still unticked
    (phase 02 evidence, design §8.1). Each condition alone already refuses (L1.1, L1.2);
    this named fixture puts both live at once so the refusal *precedence* is pinned: the
    purely local ordering refusal must win before the network fetch is spent. Returns the
    bare ``origin``, the clone, and the sha ``origin/main`` was advanced to.
    """
    origin, clone = _origin_and_clone(
        tmp_path, roadmap=ROADMAP_INCOMPLETE_PREDECESSOR
    )
    remote_sha = _advance_origin(tmp_path, origin, "upstream")
    return origin, clone, remote_sha


def test_l61_e16_fixture_ordering_refusal_precedes_the_fetch(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The combined E1.6 fixture refuses on ordering, before any fetch, and runs nothing.

    ``ROADMAP_INCOMPLETE_PREDECESSOR`` has a single predecessor, so the multi-entry
    roadmap order stays pinned by ``test_l12_refusal_names_all_predecessors_in_roadmap_order``;
    here the point is that the *local* refusal fires while ``origin/main`` is ahead.
    """
    _origin, clone, remote_sha = _e16_stale_base_with_unticked_predecessor(tmp_path)
    local_sha = git.rev_parse(clone, "main") or ""
    # Both refusal conditions are genuinely live: the remote moved past the local base,
    # and the clone's ``origin/main`` is still stale — no fetch has happened yet.
    assert remote_sha and remote_sha != local_sha
    assert git.rev_parse(clone, "origin/main") == local_sha

    fetch_calls: list[tuple] = []

    def spy_fetch(*args, **kwargs):
        fetch_calls.append(args)
        return False, "boom"

    monkeypatch.setattr(git, "fetch", spy_fetch)
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(clone), label=RUN_LABEL
    )

    assert code == 4
    # The ordering refusal short-circuits the network: no fetch, no comparison, no stage.
    assert fetch_calls == []
    err = capsys.readouterr().err
    assert "earlier tasks in the same file are incomplete" in err
    assert "E3.1 — An earlier unticked task" in err
    assert "Tick each predecessor once its work is merged" in err
    assert "re-run with `--allow-incomplete-prereqs`" in err
    # It is the ordering refusal, not the behind-origin one that a fetch would find.
    assert "is behind" not in err
    assert "git pull --ff-only" not in err
    # A refusal before ``create_run`` leaves no run directory, branch or prompt behind.
    assert state.list_runs(_runs_root(clone)) == []
    assert git.current_branch(clone) == "main"
    assert git.rev_parse(clone, "03-E4.1") is None
    assert not (clone / "docs" / "task-prompts" / "03-E4.1-prompt.md").exists()
