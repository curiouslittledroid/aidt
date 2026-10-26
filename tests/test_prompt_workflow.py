"""Tests for git safety helpers and the prompt workflow (dry-run)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from aidw import git, state
from aidw.paths import toolkit_root, repo_root
from aidw.workflows import prompt as prompt_workflow

#: Test-only run label. It keeps test-created runs identifiable and lets the session
#: fixture in ``conftest.py`` delete any that slip past the isolated ``runs_root``.
RUN_LABEL = "pytest"

#: Isolated run-state root, matching where the fake stages below write their output.
RUNS_DIRNAME = Path("aidt") / "runs"


def test_git_helpers_types() -> None:
    repo = repo_root()
    assert isinstance(git.is_clean(repo), bool)
    assert git.current_branch(repo) in (None, "ai-dev-workflows", "main") or isinstance(
        git.current_branch(repo), str
    )
    assert isinstance(git.status_short(repo), str)


def test_prompt_workflow_dry_run(tmp_path: Path, monkeypatch) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        repo=tmp_path,
        aidt=toolkit_root(),
        runs_root=tmp_path / RUNS_DIRNAME,
        label=RUN_LABEL,
        dry_run=True,
    )
    assert code == 0
    latest = state.list_runs(tmp_path / RUNS_DIRNAME)[-1]
    assert latest.run_id.endswith("-pytest-prompt")
    assert latest.workflow == "prompt"
    assert [s.name for s in latest.stages] == ["task-prompt", "task-review-1"]
    assert all(s.status == state.SUCCEEDED for s in latest.stages)


def test_prompt_workflow_unknown_task(tmp_path: Path, monkeypatch) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    code = prompt_workflow.run(
        phase="99",
        epic="Z",
        task="Z9",
        repo=tmp_path,
        aidt=toolkit_root(),
        runs_root=tmp_path / RUNS_DIRNAME,
        label=RUN_LABEL,
        dry_run=True,
    )
    assert code == 2


def test_prompt_workflow_requires_main_for_real_run(tmp_path: Path, monkeypatch) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(git, "current_branch", lambda repo: "feature-branch")
    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        repo=tmp_path,
        aidt=toolkit_root(),
        runs_root=tmp_path / RUNS_DIRNAME,
        label=RUN_LABEL,
        dry_run=False,
    )
    assert code == 4


def test_prompt_workflow_requires_clean_tree(tmp_path: Path, monkeypatch) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(git, "current_branch", lambda repo: "main")
    monkeypatch.setattr(git, "is_clean", lambda repo: False)
    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        repo=tmp_path,
        aidt=toolkit_root(),
        runs_root=tmp_path / RUNS_DIRNAME,
        label=RUN_LABEL,
        dry_run=False,
    )
    assert code == 4


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


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


def _patch_prompt_repo(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path)
    tasks_dir = tmp_path / "docs" / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "03 - Test Phase.md").write_text(ROADMAP_FIXTURE, encoding="utf-8")
    monkeypatch.setattr(git, "current_branch", lambda repo: "main")
    monkeypatch.setattr(git, "is_clean", lambda repo: True)


def _review_index(stage_name: str) -> int | None:
    """N for ``task-review-N``, None for every other stage."""
    match = re.fullmatch(r"task-review-(\d+)", stage_name)
    return int(match.group(1)) if match else None


def _fake_stages(review_body: str, *, fix_status: str = "succeeded", approve_review: int | None = 2):
    """A fake ``run_stage`` returning canned review text, approving at ``approve_review``."""
    from aidw.state import SUCCEEDED, StageRecord, run_dir

    seen: list[tuple[str, list[str], str]] = []

    def fake_run_stage(spec, **kwargs):
        repo = kwargs["repo_root"]
        state = kwargs["state"]
        directory = run_dir(repo / RUNS_DIRNAME, state.run_id)
        stages = directory / "stages"
        stages.mkdir(parents=True, exist_ok=True)

        if spec.name == "task-prompt":
            created = repo / "docs" / "task-prompts" / "03-E4.1-prompt.md"
            created.parent.mkdir(parents=True, exist_ok=True)
            created.write_text("prompt body\n", encoding="utf-8")

        seen.append((spec.name, list(spec.variables), spec.extra))
        index = _review_index(spec.name)
        if index is not None:
            body = "## Verdict\n\n**Approve**\n" if index == approve_review else review_body
        elif spec.name.startswith("task-review-fixes"):
            body = "fixed\n"
        else:
            body = "prompt body\n"

        status = SUCCEEDED
        if spec.name.startswith("task-review-fixes") and fix_status != SUCCEEDED:
            status = fix_status
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

    return seen, fake_run_stage


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
        phase="03", epic="E4", task="E4.1", repo=tmp_path, aidt=toolkit_root(),
        runs_root=tmp_path / RUNS_DIRNAME, label=RUN_LABEL, approve_all=False
    )

    assert code == 0
    latest = state.list_runs(tmp_path / RUNS_DIRNAME)[-1]
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "approved"
    assert gate.mechanism == "optional (default)"
    assert "gate approve-task-prompt denied" not in capsys.readouterr().err


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
        repo=tmp_path,
        aidt=toolkit_root(),
        runs_root=tmp_path / RUNS_DIRNAME,
        label=RUN_LABEL,
        approve_all=False,
        require_approval=True,
    )

    assert code == 3
    latest = state.list_runs(tmp_path / RUNS_DIRNAME)[-1]
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "denied"


def test_review_fix_loop_fixes_blocking_individually_and_batches_could_fix(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", repo=tmp_path, aidt=toolkit_root(),
        runs_root=tmp_path / RUNS_DIRNAME, label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert [name for name, _, _ in seen] == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1-1",
        "task-review-fixes-1-2",
        "task-review-fixes-1-3",
        "task-review-2",
    ]
    fixes = [item for item in seen if item[0].startswith("task-review-fixes")]
    assert all(vars_ == ["docs/task-prompts/03-E4.1-prompt.md"] for _, vars_, _ in fixes)
    assert "Review finding 1 of 3 to address" in fixes[0][2]
    assert "Review finding 2 of 3 to address" in fixes[1][2]
    assert "Suggested fix: Add one line recording the out-of-scope decision." in fixes[1][2]
    # The non-blocking could-fix finding is batched into a single stage of its own.
    assert fixes[2][2].startswith(
        "## Non-blocking (could-fix) review finding to address together"
    )
    assert "Suggested fix: Pick one consumer-import strategy and align them." in fixes[2][2]
    assert "Add the path update to the deliverables." not in fixes[2][2]

    out = capsys.readouterr().out
    assert "verdict: Request changes — 3 findings (2 should-fix, 1 could-fix)" in out
    assert "fix 1.1/3: The deliverable leaves a stale path reference [should-fix]" in out
    assert "fix 1.2/3: The prompt is silent on matrix coverage [should-fix]" in out
    assert "fix 1.3/3: 1 could-fix finding combined" in out
    assert "out:   aidt/runs/" in out and "stages/task-review-1.out.txt" in out


def test_multiple_could_fix_findings_share_one_stage(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_MULTI_COULD)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", repo=tmp_path, aidt=toolkit_root(),
        runs_root=tmp_path / RUNS_DIRNAME, label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert [name for name, _, _ in seen] == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1-1",
        "task-review-fixes-1-2",
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
        phase="03", epic="E4", task="E4.1", repo=tmp_path, aidt=toolkit_root(),
        runs_root=tmp_path / RUNS_DIRNAME, label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert [name for name, _, _ in seen] == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1-1",
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
        phase="03", epic="E4", task="E4.1", repo=tmp_path, aidt=toolkit_root(),
        runs_root=tmp_path / RUNS_DIRNAME, label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert [name for name, _, _ in seen] == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1",
        "task-review-2",
    ]
    combined = seen[2][2]
    assert combined.startswith("## Review findings to address")
    out = capsys.readouterr().out
    assert "did not parse cleanly" in out


def test_bold_review_drives_per_finding_fixes(tmp_path: Path, monkeypatch, capsys) -> None:
    """Regression: bold label lines must not silently fall back to one combined stage."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_BOLD)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", repo=tmp_path, aidt=toolkit_root(),
        runs_root=tmp_path / RUNS_DIRNAME, label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert [name for name, _, _ in seen] == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1-1",
        "task-review-fixes-1-2",
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
        phase="03", epic="E4", task="E4.1", repo=tmp_path, aidt=toolkit_root(),
        runs_root=tmp_path / RUNS_DIRNAME, label=RUN_LABEL, approve_all=True
    )

    assert code == 1
    assert "task-review-fixes-1-1" in [name for name, _, _ in seen]
    assert "task-review-fixes-1-2" not in [name for name, _, _ in seen]


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


def test_three_review_rounds_then_accept_without_another_review(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The budget is 3 rounds; the third round's fixes end the loop with no review 4."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", repo=tmp_path, aidt=toolkit_root(),
        runs_root=tmp_path / RUNS_DIRNAME, label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    names = [name for name, _, _ in seen]
    assert "task-review-4" not in names
    assert names.count("task-review-2") == 1
    assert names.count("task-review-3") == 1
    assert names[0] == "task-prompt"
    # Three rounds of (2 individual blocking + 1 combined could-fix) fixes.
    fixes = [name for name in names if name.startswith("task-review-fixes")]
    assert fixes == [
        "task-review-fixes-1-1",
        "task-review-fixes-1-2",
        "task-review-fixes-1-3",
        "task-review-fixes-2-1",
        "task-review-fixes-2-2",
        "task-review-fixes-2-3",
        "task-review-fixes-3-1",
        "task-review-fixes-3-2",
        "task-review-fixes-3-3",
    ]

    latest = state.list_runs(tmp_path / RUNS_DIRNAME)[-1]
    assert latest.status == state.SUCCEEDED
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert "assumed_ok=True" in gate.detail
    assert "revisions=3" in gate.detail

    out = capsys.readouterr().out
    assert "revision budget spent (3 round(s)); accepting the prompt" in out


def test_a_blocked_final_review_still_fails_closed(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A Blocked verdict is the one exception: it always needs a human."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_BLOCKED, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", repo=tmp_path, aidt=toolkit_root(),
        runs_root=tmp_path / RUNS_DIRNAME, label=RUN_LABEL, approve_all=False
    )

    assert code == 3
    names = [name for name, _, _ in seen]
    assert "task-review-4" not in names
    assert "task-review-fixes-3-1" in names
    captured = capsys.readouterr()
    assert "did not approve within the revision budget" in captured.err
    assert "revision budget spent" not in captured.out


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
    assert git.status_short(tmp_path, paths=["docs/task-prompts/03-E4.1-prompt.md"]) == ""


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
    """The reviewer must be pointed at the path the author actually created."""
    _init_repo(tmp_path)
    tasks_dir = tmp_path / "docs" / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "03 - Test Phase.md").write_text(ROADMAP_FIXTURE, encoding="utf-8")

    monkeypatch.setattr(git, "current_branch", lambda repo: "main")
    monkeypatch.setattr(git, "is_clean", lambda repo: True)

    from aidw.state import SUCCEEDED, StageRecord, run_dir

    captured: list[list[str]] = []

    def fake_run_stage(spec, **kwargs):
        repo = kwargs["repo_root"]
        state = kwargs["state"]
        directory = run_dir(repo / RUNS_DIRNAME, state.run_id)
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
        repo=tmp_path,
        aidt=toolkit_root(),
        runs_root=tmp_path / RUNS_DIRNAME,
        label=RUN_LABEL,
        approve_all=True,
    )

    assert code == 0
    assert captured == [["docs/task-prompts/03-E4.1.md"]]
    assert git.status_short(tmp_path, paths=["docs/task-prompts/03-E4.1.md"]) == ""
