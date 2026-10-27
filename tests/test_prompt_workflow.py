"""Tests for git safety helpers and the prompt workflow (dry-run)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aidw import git, state
from aidw.cli import app
from aidw.paths import ToolkitPaths, TargetRepo, WorkspacePaths, repo_root, toolkit_root
from aidw.prompts import PromptError, render_prompt_file
from aidw.workflows import prompt as prompt_workflow

#: Test-only run label. It keeps test-created runs identifiable and lets the session
#: fixture in ``conftest.py`` delete any that slip past the isolated ``runs_root``.
RUN_LABEL = "pytest"

#: Isolated run-state root, matching where the fake stages below write their output.
RUNS_DIRNAME = Path("aidt") / "runs"


def _roots(repo: Path) -> dict:
    """Typed roots for a direct workflow call, isolated under ``repo/RUNS_DIRNAME``.

    ``WorkspacePaths.resolve`` appends the repo slug, so the runs root is
    ``workspace.state_root / "runs"`` — under the override, never at it.
    """
    target = TargetRepo.resolve(repo)
    return {
        "repo": target,
        "aidt": ToolkitPaths.resolve(),
        "workspace": WorkspacePaths.resolve(
            target, state_dir_override=repo / RUNS_DIRNAME
        ),
    }


def _runs_root(repo: Path) -> Path:
    return _roots(repo)["workspace"].state_root / "runs"


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


def test_prompt_workflow_requires_main_for_real_run(tmp_path: Path, monkeypatch) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(git, "current_branch", lambda repo: "feature-branch")
    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
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


def _patch_prompt_repo(
    tmp_path: Path,
    monkeypatch,
    *,
    roadmap: str | None = None,
    extra_files: dict[str, str] | None = None,
) -> None:
    """A lightweight fake repo (no origin) carrying ``docs/tasks/03 - Test Phase.md``.

    ``roadmap`` defaults to :data:`ROADMAP_FIXTURE`; the default cannot be a literal
    default argument because that fixture is defined later in this module. ``extra_files``
    adds further phase files for the ``file``-scope tests.
    """
    _init_repo(tmp_path)
    tasks_dir = tmp_path / "docs" / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "03 - Test Phase.md").write_text(
        roadmap if roadmap is not None else ROADMAP_FIXTURE, encoding="utf-8"
    )
    for name, text in (extra_files or {}).items():
        (tasks_dir / name).write_text(text, encoding="utf-8")
    monkeypatch.setattr(git, "current_branch", lambda repo: "main")
    monkeypatch.setattr(git, "is_clean", lambda repo: True)


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


def _fake_stages(review_body: str, *, fix_status: str = "succeeded", approve_review: int | None = 2):
    """A fake ``run_stage`` returning canned review text, approving at ``approve_review``.

    Each fix stage appends a round-distinct marker to the prompt file (once per round), so
    the L2.3 delta-brief tests can prove that a round's diff carries only the immediately
    preceding fix batch's net effect, not every round's changes cumulatively.
    """
    from aidw.state import SUCCEEDED, StageRecord, run_dir

    seen: list[tuple[str, list[str], str]] = []

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

        seen.append((spec.name, list(spec.variables), spec.extra))
        index = _review_index(spec.name)
        if index is not None:
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
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=False
    )

    assert code == 0
    latest = state.list_runs(_runs_root(tmp_path))[-1]
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
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
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
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
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
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert [name for name, _, _ in seen] == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1",
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


def test_three_review_rounds_then_accept_without_another_review(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The budget is 3 rounds; the third round's fixes end the loop with no review 4."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
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

    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.SUCCEEDED
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert "assumed_ok=True" in gate.detail
    assert "revisions=3" in gate.detail

    out = capsys.readouterr().out
    assert "revision budget spent (3 round(s)); accepting the prompt" in out


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
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
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
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)
    created = _record_temp_dirs(monkeypatch)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert len(created) == 2  # rounds 2 and 3
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
    # The degradation round's temp directory is cleaned up too.
    assert len(created) == 1
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
    captured = capsys.readouterr()
    assert "A material ambiguity the prompt cannot settle." in captured.err
    assert "revision budget spent" not in captured.out


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
        git.status_short(tmp_path, paths=["docs/task-prompts/03-E4.1-prompt.md"]) != ""
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
        git.status_short(tmp_path, paths=["docs/task-prompts/03-E4.1-prompt.md"]) != ""
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
        git.status_short(tmp_path, paths=["docs/task-prompts/03-E4.1-prompt.md"]) != ""
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
    assert captured == [["docs/task-prompts/03-E4.1.md"]]
    assert git.status_short(tmp_path, paths=["docs/task-prompts/03-E4.1.md"]) == ""


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
    """Build a bare ``origin`` and a clone whose ``main`` carries the roadmap fixture.

    The clone is the target repo the workflow drives; ``origin/main`` tracks it. The
    roadmap fixture is committed and pushed so both the base branch and its remote-tracking
    ref resolve from the first run.
    """
    origin = tmp_path / "origin.git"
    clone = tmp_path / "clone"
    _run_git(["init", "-q", "--bare", "-b", "main", str(origin)], tmp_path)
    _run_git(["clone", "-q", str(origin), str(clone)], tmp_path)
    tasks_dir = clone / "docs" / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "03 - Test Phase.md").write_text(roadmap, encoding="utf-8")
    _run_git(["add", "."], clone)
    _run_git(["commit", "-qm", "init"], clone)
    _run_git(["push", "-q", "-u", "origin", "main"], clone)
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
    repo = tmp_path / "plain"
    _run_git(["init", "-q", "-b", "main", str(repo)], tmp_path)
    tasks_dir = repo / "docs" / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "03 - Test Phase.md").write_text(ROADMAP_FIXTURE, encoding="utf-8")
    _run_git(["add", "."], repo)
    _run_git(["commit", "-qm", "init"], repo)
    _seen, fake = _approve_first_review()
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(repo), label=RUN_LABEL, approve_all=True
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
    assert "must run on `main`" in err
    assert "earlier tasks in the same file are incomplete" not in err


# ---------------------------------------------------------------------------
# L1.3 — the author's blocked channel (design §8.1, §10, §13; EXTRACTION.md §3.8)
# ---------------------------------------------------------------------------


def _blocked_author_stages(
    output: str,
    *,
    write_prompt: bool = False,
    create_branch: str | None = None,
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
            if create_branch:
                _run_git(["branch", create_branch], repo)

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
    # Nothing was committed or written under the author's directory.
    assert git.status_short(tmp_path, paths=["docs/task-prompts"]) == ""
    assert not (tmp_path / "docs" / "task-prompts" / "03-E4.1-prompt.md").exists()
    assert git.rev_parse(tmp_path, "03-E4.1") is None
    assert git.rev_parse(tmp_path, "HEAD") is None


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
    # The file the author left is not committed and not removed; it is uncommitted.
    leftover = tmp_path / "docs" / "task-prompts" / "03-E4.1-prompt.md"
    assert leftover.exists()
    assert git.status_short(tmp_path, paths=["docs/task-prompts"]).startswith("??")


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
    assert "docs/task-prompts/03-E4.1-prompt.md" in err
    assert "neither committed nor removed" in err
    assert (tmp_path / "docs" / "task-prompts" / "03-E4.1-prompt.md").exists()


def test_l13_branch_created_during_run_is_reported_not_deleted(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _origin, clone = _origin_and_clone(tmp_path)
    _seen, fake = _blocked_author_stages(
        "blocked: prerequisite missing\n", create_branch="03-E4.1"
    )
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(clone), label=RUN_LABEL
    )

    assert code == 3
    err = capsys.readouterr().err
    assert "created branch" in err and "03-E4.1" in err
    assert git.rev_parse(clone, "03-E4.1") is not None  # reported, never deleted


def test_l13_preexisting_branch_is_not_reported(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A branch that existed before the run must not be blamed on the run."""
    _origin, clone = _origin_and_clone(tmp_path)
    _run_git(["branch", "03-E4.1"], clone)
    _seen, fake = _blocked_author_stages("blocked: prerequisite missing\n")
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(clone), label=RUN_LABEL
    )

    assert code == 3
    assert "created branch" not in capsys.readouterr().err


def test_l13_unanswerable_branch_probe_does_not_warn(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """An advisory probe failure must not guess that the author created a branch."""
    _origin, clone = _origin_and_clone(tmp_path)
    _seen, fake = _blocked_author_stages(
        "blocked: prerequisite missing\n", create_branch="03-E4.1"
    )
    probes = iter([(False, None), (True, "branch-sha")])
    monkeypatch.setattr(prompt_workflow, "_probe_branch", lambda *args: next(probes))
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(clone), label=RUN_LABEL
    )

    assert code == 3
    assert "created branch" not in capsys.readouterr().err
    assert git.rev_parse(clone, "03-E4.1") is not None


def test_l13_transient_probe_spawn_failure_does_not_blame_preexisting_branch(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A pre-author probe git cannot answer must not read as "the branch is absent".

    Review follow-up F1 (PR #16): the before-probe's git spawn fails transiently while
    the branch legitimately pre-exists, and the after-probe answers. Collapsing the
    failed spawn into ``None`` (as ``rev_parse`` alone does) would make the run warn
    "blocked run created branch" for a branch it did not create.
    """
    _origin, clone = _origin_and_clone(tmp_path)
    _run_git(["branch", "03-E4.1"], clone)  # the branch legitimately pre-exists
    real_git_out = git._git_out
    failed_once = [False]

    def flaky_git_out(repo, args, **kwargs):
        # Fail exactly one spawn of the branch probe (the ref arg carries `^{commit}`);
        # every other git call is real.
        if not failed_once[0] and f"refs/heads/03-E4.1" in " ".join(args):
            failed_once[0] = True
            return 127, "", "git: not found"
        return real_git_out(repo, args, **kwargs)

    monkeypatch.setattr(git, "_git_out", flaky_git_out)
    _seen, fake = _blocked_author_stages("blocked: prerequisite missing\n")
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(clone), label=RUN_LABEL
    )

    assert code == 3
    assert failed_once[0]  # the transient failure was actually injected
    assert "created branch" not in capsys.readouterr().err


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
    assert "before creating or switching to the `{phase}-{task}` branch" in rendered
    assert "or, when blocked, `blocked: <reason>`" in rendered
    # Feasibility is checked before the branch is created or switched to.
    feasibility = rendered.index(
        "before creating or switching to the `{phase}-{task}` branch"
    )
    branch = rendered.index("create or switch to the dedicated `{phase}-{task}` branch")
    assert feasibility < branch

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
    """A committed repo (no ``origin``) with a multi-line Done when and a ``D16`` doc.

    Committed so the local base branch resolves to a real sha while ``origin/main``
    stays absent — the no-origin fixture the base-branch assertion needs.
    """
    _run_git(["init", "-q", "-b", "main", str(tmp_path)], tmp_path)
    tasks_dir = tmp_path / "docs" / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "03 - Test Phase.md").write_text(ROADMAP_EVIDENCE, encoding="utf-8")
    (tmp_path / "docs" / "migration").mkdir(parents=True)
    (tmp_path / "docs" / "migration" / "EXTRACTION.md").write_text(
        EXTRACTION_EVIDENCE_FIXTURE, encoding="utf-8"
    )
    if agents_md is not None:
        (tmp_path / "AGENTS.md").write_text(agents_md, encoding="utf-8")
    _run_git(["add", "."], tmp_path)
    _run_git(["commit", "-qm", "init"], tmp_path)
    monkeypatch.setattr(git, "current_branch", lambda repo: "main")
    monkeypatch.setattr(git, "is_clean", lambda repo: True)
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
