"""Tests for git safety helpers and the prompt workflow (dry-run)."""

from __future__ import annotations

import dataclasses
import hashlib
import random
import re
import subprocess
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aidw import __version__, git, lock, state
from aidw import stage_registry
from aidw.cli import app
from aidw.config import ERROR, Issue
from aidw.paths import ToolkitPaths, TargetRepo, WorkspacePaths, repo_root, toolkit_root
from aidw.prompts import PromptError, render_prompt_file
from aidw.roadmap import RoadmapTask
from aidw.target_config import config_identity, resolve_workflow_config
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
    assert not _runs_root(tmp_path).exists()
    # L5.3 is post-author only; a dry-run never produces a prompt to measure.
    out = capsys.readouterr().out
    assert "budget:" not in out
    # EXTRACTION.md §3.2: the dry run names the planned worktree and the base-branch
    # requirement, but creates no worktree and invokes no stage.
    assert "branch-setup (planned): worktree add -b 03-E4.1" in out
    assert "a real run requires the base branch `main`" in out
    assert not _task_worktree(tmp_path).exists()


def test_prompt_workflow_real_run_records_run_identity(
    tmp_path: Path, monkeypatch
) -> None:
    """E8.2/EXTRACTION.md §3.11: every run's ``state.json`` explains what produced it.

    Asserted on a real fake-stage run: dry-run planning creates no state, while a
    recorded run carries ``toolkit_version == aidw.__version__`` plus the identity of the
    **resolved** target config this run used — the same two values
    :func:`aidw.target_config.config_identity` computes for the same fixture here, so a
    workflow that recorded a different config (or only the declared one) fails.
    """
    _patch_prompt_repo(
        tmp_path,
        monkeypatch,
        config_text="schema_version: 1\nmax_revisions: 2\n",
    )
    monkeypatch.setattr(git, "current_branch", lambda repo: "main")
    repo = _roots(tmp_path)["repo"]

    _seen, fake = _fake_stages("## Verdict\n\n**Approve**\n", approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)
    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
    )

    assert code == 0
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    expected_config_schema_version, expected_config_hash = config_identity(
        resolve_workflow_config(repo.root, toolkit_version=__version__)[0]
    )
    assert latest.toolkit_version == __version__
    assert latest.config_schema_version == expected_config_schema_version == 1
    assert latest.config_hash == expected_config_hash
    assert latest.config_hash.startswith("sha256:")
    # Additive at the same state schema (design §9.2's precedent).
    assert latest.schema_version == state.SCHEMA_VERSION


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
    assert state.list_runs(_runs_root(tmp_path)) == []
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
    assert state.list_runs(_runs_root(tmp_path)) == []


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


#: The §3.4 read-paths ``aidw prompt``'s preflight validates (E3.7), as ``path -> text``.
#: Every committed fixture repo in this module carries them: the defaults name them (D17),
#: so a repo without them refuses at the preflight rather than planning stages.
#:
#: ``design.md`` is not a validated read-path but the file the fixtures' ``Design N``
#: citations name (G1.2): the cited-spec preflight refuses when a cited section is missing,
#: so this seed keeps ``Design 09`` (``ROADMAP_FIXTURE`` and its siblings) and ``Design 8.1``
#: (``ROADMAP_EVIDENCE``) resolvable against non-empty headings — a section with prose, never
#: a bare heading. ``Design 09`` matches ``## 9`` canonically, not as a string
#: (roadmap-format.md §8.1 accepts the zero-padded form), which is the comparison the check
#: pins. A test that needs a gap overrides this file rather than stripping a citation.
READ_PATH_FILES = {
    "docs/task-prompts/.gitkeep": "",
    "docs/implementation-results/TEMPLATE.md": "# Build results template\n",
    "design.md": (
        "# Design\n"
        "\n"
        "## 8. Workflow specifications\n"
        "\n"
        "### 8.1 Cited spec sections\n"
        "\n"
        "A fixture section with prose, so a `Design 8.1` citation is non-empty.\n"
        "\n"
        "## 9. Test fixture\n"
        "\n"
        "A fixture section with prose, so a `Design 09` citation is non-empty.\n"
    ),
}


TASK_REVIEW_CHANGES = """\
## What I verified

The prompt's assumptions hold.

## Findings

```text
Priority: Should fix
Confidence: 4
Kind: prompt-gap
What I found: The deliverable leaves a stale path reference.
Why it matters: A reviewer lands on a missing file.
Trigger and effect: After the rename the pointer is dead.
Where: docs/task-prompts/03-E4.1-prompt.md, Deliverables.
Suggested fix: Add the path update to the deliverables.
```

```text
Priority: Should fix
Confidence: 4
Kind: prompt-gap
What I found: The prompt is silent on matrix coverage.
Why it matters: A convention-mandated check is skipped silently.
Trigger and effect: The implementer omits the matrix review.
Where: docs/task-prompts/03-E4.1-prompt.md, requirement 7.
Suggested fix: Add one line recording the out-of-scope decision.
```

```text
Priority: Could fix
Confidence: 3
Kind: prompt-gap
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
Kind: prompt-gap
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
**Kind: prompt-gap**

**What I found:** The importer enumeration omits a real fourth importer.
**Why it matters:** Literal compliance produces a non-building PR.
**Trigger and effect:** Any implementation that trusts the list.
**Where:** docs/task-prompts/03-E4.1-prompt.md, Context.
**Suggested fix:** Add the missing importer.

**Priority: Could fix**
**Confidence:** 3
**Kind:** prompt-gap

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
    # The §3.4 read-paths ``aidw prompt``'s preflight validates (E3.7), committed so the
    # control worktree stays clean and every task worktree inherits them. Without them
    # every prompted run refuses at that preflight; ``TEMPLATE.md`` covers both
    # ``implementation_results_dir`` and ``build_results_template``, and the placeholder
    # file is what makes ``docs/task-prompts/`` exist (git tracks no empty directory).
    for rel, text in READ_PATH_FILES.items():
        files.setdefault(rel, text)
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
    config_text: str | None = None,
) -> None:
    """A committed bare+control repo (no origin) carrying the roadmap fixtures.

    ``roadmap`` defaults to :data:`ROADMAP_FIXTURE`; the default cannot be a literal
    default argument because that fixture is defined later in this module. ``extra_files``
    adds further phase files for the ``file``-scope tests. ``config_text`` is written to
    ``aidw/config.yaml`` (E3.2) and committed, so the control worktree stays clean for the
    real-run preflight and :func:`run` reads it from ``repo.root``. The files are committed
    so branch setup really creates a task worktree from ``base_branch``; ``current_branch``
    and ``is_clean`` are left unmocked so preflight reads real git.
    """
    files = {
        "docs/tasks/03 - Test Phase.md": (
            roadmap if roadmap is not None else ROADMAP_FIXTURE
        )
    }
    if config_text is not None:
        files["aidw/config.yaml"] = config_text
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
        if spec.name == "task-prompt" and not kwargs.get("dry_run"):
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
        if kwargs.get("dry_run"):
            return StageRecord(
                name=spec.name,
                agent=spec.agent_id,
                model="test-model",
                status=SUCCEEDED,
            )
        directory = run_dir(kwargs["runs_root"], state.run_id)
        stages = directory / "stages"
        stages.mkdir(parents=True, exist_ok=True)
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
        lambda _aidt_root, _repo_root, **_kwargs: (
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


def test_a_located_clean_worktree_is_reused_instead_of_added(
    tmp_path: Path, monkeypatch
) -> None:
    """H1.2 req 2: a re-run locates the worktree an earlier run left and never re-adds it.

    ``git.add_worktree`` returns ``None`` for an already-checked-out branch, so calling it
    unconditionally is what refused every re-run before H1.2. A clean located worktree is
    reused: the stages run in it and the branch/worktree pair is untouched.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    existing = git.add_worktree(tmp_path, "03-E4.1")
    assert existing is not None and git.is_clean(existing)
    added: list[str] = []
    real_add = git.add_worktree

    def tracking_add(repo, branch, **kwargs):
        added.append(branch)
        return real_add(repo, branch, **kwargs)

    monkeypatch.setattr(git, "add_worktree", tracking_add)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL,
        approve_all=True,
    )

    assert code == 0
    assert added == []
    assert fake.repo_roots and all(root == existing for root in fake.repo_roots)
    assert [
        entry.path for entry in git.worktrees(tmp_path) if entry.branch == "03-E4.1"
    ] == [existing]
    assert len(state.list_runs(_runs_root(tmp_path))) == 1


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
Kind: prompt-gap
What I found: The survey function name is wrong.
Why it matters: Callers cannot compile.
Trigger and effect: Any implementation.
Where: docs/task-prompts/03-E4.1-prompt.md, requirement 2.
Suggested fix: Use the real exported name.
```

```text
Priority: Could fix
Confidence: 3
Kind: prompt-gap
What I found: The prose is repetitive.
Why it matters: Slightly harder to read.
Trigger and effect: None.
Where: docs/task-prompts/03-E4.1-prompt.md, Context.
Suggested fix: Tighten the paragraph.
```

```text
Priority: Could fix
Confidence: 3
Kind: prompt-gap
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
    assert latest.resume == {"next_stage": "task-review-fixes-1-1"}
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
Kind: prompt-gap
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
Kind: prompt-gap
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


def test_approve_with_blocking_findings_fails_closed(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """M2: `Approve` contradicting its own must-fix findings is not an approval.

    E4.5b regression (2026-11-04): the loop broke on `Approve` before partitioning, so a
    `Must fix` finding was dropped, no fix stage ran, the gate was approved, and the
    reviewed prompt was committed.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    body = TASK_REVIEW_CHANGES + "\n**Verdict: Approve**\n"
    seen, fake = _fake_stages(body, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 3
    # The contradiction stops the loop before any rework or second review.
    assert [name for name, _, _ in seen] == ["task-prompt", "task-review-1"]
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "denied"
    assert "verdict=Approve" in gate.detail
    assert "fixes=0" in gate.detail
    # The findings are handed to the human, not silently dropped.
    captured = capsys.readouterr()
    assert "approved but reported 2 blocking finding(s)" in captured.err
    assert "2 should-fix" in captured.err
    assert "The deliverable leaves a stale path reference." in captured.err
    # An unsettled review must not leave the prompt committed.
    worktree = _task_worktree(tmp_path)
    assert git.status_short(worktree, paths=["docs/task-prompts/03-E4.1-prompt.md"]) != ""


def test_ambiguous_verdict_still_reworks_and_never_approves(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """M2 keeps L4.2's ambiguous-round behaviour: rework, then fail closed at the end.

    Only the *contradiction* (``Approve`` plus blocking findings) stops the loop early.
    A verdict-less review is still reworked and still cannot approve.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    body = TASK_REVIEW_CHANGES.replace(
        "## Verdict\n\nRequest changes — two should-fix items remain.\n", ""
    )
    seen, fake = _fake_stages(body, approve_review=None)
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
    assert "approved=no" in gate.detail
    assert "verdict: ambiguous" in capsys.readouterr().out


def test_approve_with_only_could_fix_findings_is_still_an_approval(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """M2 must not turn non-blocking nits into a stop: only blocking findings contradict."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    only_could = "\n".join(
        [line for line in TASK_REVIEW_MULTI_COULD.splitlines() if "Must fix" not in line]
    )
    seen, fake = _fake_stages(only_could + "\n**Verdict: Approve**\n", approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    assert [name for name, _, _ in seen] == ["task-prompt", "task-review-1"]
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "approved"
    assert "verdict=Approve" in gate.detail
    assert "fixes=0" in gate.detail


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
    # H2.1: the previous review is re-emitted as the reviewer's structured blocks, which
    # is the smaller representation, so its *non-finding* prose (headings, verdict, and
    # this fixture's round marker) is not carried. Every finding is, and only then does
    # the diff follow.
    assert "The deliverable leaves a stale path reference." in extra
    assert stage_registry.DELTA_BRIEF_FINDINGS_LEAD in extra
    assert "<!-- review round 1 -->" not in extra
    assert "Fix exactly this finding" not in extra
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
    # No random temp path **in the brief**. Scoped to the diff section because ``extra``
    # also begins with the L2.4 evidence pointer, whose path is absolute under the state
    # root by design (`_evidence_pointer`): on Linux that is `/tmp/pytest-of-runner/...`,
    # which is the pointer, not the diff's `mkdtemp` directory.
    assert "/tmp/" not in extra[extra.index("### Prompt diff") :]


def test_over_budget_fix_diff_is_explicitly_elided_in_the_next_review(
    tmp_path: Path, monkeypatch
) -> None:
    """H2.1: the real prompt-loop wiring names an over-budget diff instead of shortening it."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)
    over = "diff --git a/baseline/prompt.md b/current/prompt.md\n" + "+" * 8000
    monkeypatch.setattr(prompt_workflow, "_brief_diff", lambda **_kwargs: over)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 0
    extra = _extra_for(seen, "task-review-2")
    note = stage_registry.DELTA_BRIEF_DIFF_ELIDED.format(size=len(over))
    assert note in extra
    assert "elided" in extra and "for size" in extra
    assert str(stage_registry.DELTA_BRIEF_DIFF_BUDGET_CHARS) in extra
    assert over not in extra
    assert "diff --git" not in extra
    # The explicit replacement is materially smaller than carrying the same diff through.
    assert len(extra) < len(extra.replace(note, over))


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
    # Round attribution is proven by the diff, not by the review text: since H2.1 a
    # parseable review renders as its structured finding blocks, and this fixture's two
    # rounds produce identical findings, so the round-markers (non-finding prose) are not
    # carried into the brief at all. The fix-batch diff below is round 2's net effect.
    assert "<!-- review round 2 -->" not in extra
    assert "<!-- review round 1 -->" not in extra
    assert stage_registry.DELTA_BRIEF_FINDINGS_LEAD in extra
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
    """The delta brief carries the previous review — through the *smaller* rendering.

    Re-baselined by H2.1 (the name is L2.3's old promise): the previous review is carried
    byte-for-byte only when it does not parse into findings, or when its structured blocks
    are not strictly smaller. When the parse is clean and the blocks win, the brief carries
    the reviewer's own blocks instead — every finding survives, and the per-finding
    resolution instruction is still there to be answered. Since E4.3 the wording is the
    registry's (``render_delta_brief``); this workflow only produces the diff it embeds, so
    the two are exercised together here.
    """
    baseline = "prompt\n"
    current = "prompt\n<!-- fix round 1 -->\n"
    diff = prompt_workflow._prompt_diff(
        baseline, current, name="03-E4.1-prompt.md"
    )

    # The old promise, which still holds for a review that does not parse into findings:
    # the prose is carried with its meaningful trailing whitespace intact.
    previous_review = "Review text with trailing spaces  \n"
    brief = stage_registry.render_delta_brief(
        previous_review=previous_review, diff=diff
    )

    assert previous_review in brief
    assert "+<!-- fix round 1 -->" in brief
    assert "### Previous review" in brief
    assert "### Prompt diff since that review" in brief

    # H2.1's substitute: a parseable, verbose review renders as one block per finding.
    brief = stage_registry.render_delta_brief(
        previous_review=TASK_REVIEW_CHANGES, diff=diff
    )
    assert stage_registry.DELTA_BRIEF_FINDINGS_LEAD in brief
    assert TASK_REVIEW_CHANGES not in brief
    for title in (
        "The deliverable leaves a stale path reference.",
        "The prompt is silent on matrix coverage.",
        "The annotations contradict the import strategy.",
    ):
        assert title in brief
    for token in ("`resolved`", "`not resolved`", "`newly contradicted`"):
        assert token in brief
    # The reviewer's voice, not the fixer's, and the diff still follows the review.
    assert "Fix exactly this finding" not in brief
    assert brief.index("### Previous review") < brief.index("### Prompt diff")


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
    # The prompt a blocked run leaves *uncommitted for a human* lives in the task
    # worktree (where the author writes), never in the control tree. Reading the control
    # root made this assertion pass for the wrong reason: with no ``docs/task-prompts/``
    # there, git printed "warning: could not open directory ..." and the non-empty string
    # satisfied ``!= ""`` (found while E3.7 committed the read-path placeholders).
    assert (
        git.status_short(
            _task_worktree(tmp_path), paths=["docs/task-prompts/03-E4.1-prompt.md"]
        )
        != ""
    )


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


# --------------------------------------------------------------------------- #
# G1.1: the prompt review's `Kind:` classification (design §8.1, row Z18)
# --------------------------------------------------------------------------- #

#: A prompt-review finding whose defect only the cited spec or roadmap can close (G1.1):
#: editing the prompt cannot make the requirement true, so no fix batch may take it.
TASK_REVIEW_SPEC_GAP = """\
## Findings

```text
Priority: Must fix
Confidence: 5
Kind: spec-gap
What I found: The prompt requires a field the cited spec never defines.
Why it matters: The implementer would have to invent a schema decision.
Trigger and effect: Any implementation follows the invented field.
Where: docs/task-prompts/03-E4.1-prompt.md, requirement 4; the cited spec section.
Suggested fix: Add the field to the spec first; the prompt cannot settle it.
```

## Verdict

Request changes — the spec must define the field before the prompt can.
"""


def _finding_block(*, priority: str, kind: str | None, what: str) -> str:
    """One reviewer finding block, with a `Kind:` line only when ``kind`` is not None."""
    lines = ["```text", f"Priority: {priority}", "Confidence: 4"]
    if kind is not None:
        lines.append(f"Kind: {kind}")
    lines += [
        f"What I found: {what}",
        "Why it matters: It matters.",
        "Trigger and effect: Always.",
        "Where: docs/task-prompts/03-E4.1-prompt.md.",
        "Suggested fix: Fix it.",
        "```",
    ]
    return "\n".join(lines)


def _two_finding_review(*kinds: str | None) -> str:
    """A two-finding review whose findings carry the given kinds (``None`` = absent)."""
    blocks = [
        _finding_block(
            priority="Must fix" if index == 0 else "Could fix",
            kind=kind,
            what=f"Finding {index + 1} text.",
        )
        for index, kind in enumerate(kinds)
    ]
    return "## Findings\n\n" + "\n\n".join(blocks) + "\n\n## Verdict\n\nRequest changes\n"


def test_g11_spec_gap_review_stops_before_any_fix(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A `spec-gap` finding ends the run blocked, surfaced, with no fixer or reconcile."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_SPEC_GAP, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 3
    names = [name for name, _, _ in seen]
    assert names == ["task-prompt", "task-review-1"]
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    assert latest.resume == {}
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "denied"
    assert gate.mechanism == "spec-gap"
    # The finding is surfaced in the reviewer's own block form, classification included.
    err = capsys.readouterr().err
    assert "spec-gap" in err
    assert "Kind: spec-gap" in err
    assert "What I found: The prompt requires a field the cited spec never defines." in err
    # No approve path ran, so the prompt stays uncommitted for a human.
    assert (
        git.status_short(
            _task_worktree(tmp_path), paths=["docs/task-prompts/03-E4.1-prompt.md"]
        )
        != ""
    )


@pytest.mark.parametrize(
    "kind_line",
    ["", "Kind:", "Kind: nope"],
    ids=["missing", "empty", "unrecognised"],
)
def test_g11_unclassified_review_fails_closed(
    tmp_path: Path, monkeypatch, capsys, kind_line: str
) -> None:
    """A missing or unrecognised `Kind:` stops the run instead of reaching the fixer."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    body = TASK_REVIEW_SPEC_GAP.replace("Kind: spec-gap\n", f"{kind_line}\n" if kind_line else "")
    seen, fake = _fake_stages(body, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 3
    names = [name for name, _, _ in seen]
    assert names == ["task-prompt", "task-review-1"]
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "denied"
    assert gate.mechanism == "unclassified"
    err = capsys.readouterr().err
    assert "unclassified" in err
    assert "What I found: The prompt requires a field the cited spec never defines." in err
    assert (
        git.status_short(
            _task_worktree(tmp_path), paths=["docs/task-prompts/03-E4.1-prompt.md"]
        )
        != ""
    )


def test_g11_unclassified_precedes_the_unparseable_fallback(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Classification is checked before malformed priority takes the old fallback path."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    body = TASK_REVIEW_SPEC_GAP.replace("Priority: Must fix", "Priority: Urgent").replace(
        "Kind: spec-gap", "Kind: nope"
    )
    seen, fake = _fake_stages(body, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 3
    assert [name for name, _, _ in seen] == ["task-prompt", "task-review-1"]
    gate = [g for g in state.list_runs(_runs_root(tmp_path))[-1].gates if g.name == "approve-task-prompt"][-1]
    assert gate.mechanism == "unclassified"
    err = capsys.readouterr().err
    assert "unclassified" in err
    assert "What I found: The prompt requires a field the cited spec never defines." in err


def test_g11_an_unclassified_finding_wins_over_a_spec_gap(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Ordering: a review whose classification cannot be trusted stops as unclassified."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    body = _two_finding_review("spec-gap", "nope")
    seen, fake = _fake_stages(body, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 3
    assert [name for name, _, _ in seen] == ["task-prompt", "task-review-1"]
    gate = [g for g in state.list_runs(_runs_root(tmp_path))[-1].gates if g.name == "approve-task-prompt"][-1]
    assert gate.mechanism == "unclassified"
    err = capsys.readouterr().err
    assert "unclassified" in err
    assert "Finding 2 text." in err


def test_g11_a_spec_gap_wins_over_an_approve_verdict(
    tmp_path: Path, monkeypatch
) -> None:
    """Classification is checked before M2's approve branch: a spec-gap is not approved."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    body = TASK_REVIEW_CHANGES.replace("Kind: prompt-gap", "Kind: spec-gap")
    seen, fake = _fake_stages(body + "\n**Verdict: Approve**\n", approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=True
    )

    assert code == 3
    assert [name for name, _, _ in seen] == ["task-prompt", "task-review-1"]
    gate = [g for g in state.list_runs(_runs_root(tmp_path))[-1].gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "denied"
    assert gate.mechanism == "spec-gap"
    # The M2 branch would also be denied, but with `review-loop`; this proves precedence.
    assert "verdict=Approve" in gate.detail


def test_g11_a_spec_gap_wins_over_a_blocked_verdict(tmp_path: Path, monkeypatch) -> None:
    """A spec-gap is the more actionable stop even when the reviewer said `Blocked`."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    body = TASK_REVIEW_BLOCKED_DEPENDENCY.replace("Kind: prompt-gap", "Kind: spec-gap")
    seen, fake = _fake_stages(body, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, approve_all=False
    )

    assert code == 3
    assert [name for name, _, _ in seen] == ["task-prompt", "task-review-1"]
    gate = [g for g in state.list_runs(_runs_root(tmp_path))[-1].gates if g.name == "approve-task-prompt"][-1]
    assert gate.mechanism == "spec-gap"
    assert "verdict=Blocked" in gate.detail


@pytest.mark.parametrize("mechanism", ["spec-gap", "unclassified"])
def test_g11_classification_stops_are_not_resume_fix_cycles(mechanism: str) -> None:
    """W1 must refuse both classification stops rather than offering a fixer continuation."""
    run = state.RunState(
        run_id="20260101T000000Z-g11-prompt",
        workflow="prompt",
        created_at=state.utcnow_iso(),
        repo_root=".",
    )
    run.record_gate(
        state.GateRecord(
            name=prompt_workflow.GATE,
            decision="denied",
            mechanism=mechanism,
            at=state.utcnow_iso(),
        )
    )

    assert prompt_workflow.review_loop_block(run) is False
    assert f"mechanism `{mechanism}`" in prompt_workflow.blocked_resume_reason(run)


def test_g11_prompt_gap_findings_keep_the_existing_fix_loop(
    tmp_path: Path, monkeypatch
) -> None:
    """`prompt-gap` findings are fixed exactly as before: no classification stop."""
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
    latest = state.list_runs(_runs_root(tmp_path))[-1]
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    assert gate.decision == "approved"
    assert not any(
        g.decision == "denied" and g.mechanism in ("spec-gap", "unclassified")
        for g in latest.gates
    )


def test_g11_rendered_reviewer_prompt_requires_kind_and_a_full_re_read() -> None:
    """G1.1 req 1/7: the prompt is the contract the reviewer and parser share."""
    rendered = render_prompt_file(
        toolkit_root() / "prompts" / "task-review.md",
        ["docs/task-prompts/03-E4.1-prompt.md"],
    )

    format_block = rendered.split("```text", 1)[1].split("```", 1)[0]
    labels = [
        f"{line.split(':', 1)[0]}:" for line in format_block.splitlines() if ":" in line
    ]
    assert "Kind:" in labels
    assert labels[labels.index("Confidence:") + 1] == "Kind:"
    assert "Kind: spec-gap / prompt-gap" in rendered
    # Both classes are defined in one line each, in the prompt's own words.
    assert "`spec-gap`: a defect only the cited specification or roadmap can close" in rendered
    assert "`prompt-gap`: a defect the prompt itself can close" in rendered
    assert "A finding without a valid `Kind:` is not a complete review" in rendered
    # "Keep the labels plain" is extended to the new label (no bold, no backticks).
    plain = rendered.split("Keep the labels plain", 1)[1].split("\n\n", 1)[0]
    assert "`Kind:`" in plain
    # Requirement 7: a grep/diff-only re-read of a previously flagged section is not proof.
    assert "re-read the previously flagged material in full" in rendered
    assert "never sufficient to approve" in rendered


def test_g11_task_reviewer_context_mirrors_kind_and_stays_read_only() -> None:
    """G1.1 req 6: the agent context states the requirement without widening its boundary."""
    agent_md = (
        toolkit_root() / "agents" / "task-reviewer" / "AGENTS.md"
    ).read_text(encoding="utf-8")

    assert "`Kind:`" in agent_md
    assert "`spec-gap`" in agent_md and "`prompt-gap`" in agent_md
    assert "not a\n  complete review" in agent_md
    # The read-only boundary is unchanged, not relaxed by the new output requirement.
    assert "Read-only" in agent_md


def test_commit_reviewed_prompt_commits_changes(tmp_path: Path) -> None:
    """_commit_reviewed_prompt commits the prompt and leaves the tree clean.

    The helper is repo-agnostic (it takes the repo it commits in), so a plain fixture
    repo is the right unit-test seam; the cleanliness assertions must read that same
    repo, not a task-worktree path that never exists here (#55).
    """
    _init_repo(tmp_path)
    rel = "docs/task-prompts/03-E4.1-prompt.md"
    # Both status assertions read this one target: retargeting the cleanliness check to a
    # nonexistent path made `status_short` swallow the git failure and return "" (issue
    # #55), so the check passed whether the tree was clean or dirty. The guard below
    # fails first if the target cannot observe the dirty prompt, keeping the final
    # assertion non-vacuous.
    status_target = tmp_path
    prompt = tmp_path / "docs" / "task-prompts" / "03-E4.1-prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    assert prompt_workflow._commit_reviewed_prompt(tmp_path, rel, "03", "E4.1")

    prompt.write_text("revised\n", encoding="utf-8")
    assert git.status_short(status_target, paths=[rel]) != ""  # non-vacuity guard (#55)
    assert prompt_workflow._commit_reviewed_prompt(tmp_path, rel, "03", "E4.1")
    assert git.status_short(status_target, paths=[rel]) == ""


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
    # The rest of the §3.4 read-paths the path preflight validates (E3.7).
    for rel, text in READ_PATH_FILES.items():
        path = seed / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
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
    assert latest.resume == {"next_stage": "task-prompt"}
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
    # E7.4 / EXTRACTION.md §4.3: the same §3.2 fact in the agent context file — AIDT creates
    # the branch, so the author never branches and never writes on the base branch. The old
    # "the prompt creates the branch" wording is what E7.4 removes.
    assert "AIDT owns branch setup" in author_md
    assert "never write on the base branch" in author_md.lower()
    assert "the prompt creates" not in author_md


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
    # M3: the verdict is a declaration line, not a token inside a sentence or a span —
    # `parse_verdict`'s first pass (§18) reads exactly this shape.
    assert "\nVerdict: Approve\n" in rendered


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

    # Format unchanged apart from G1.1's required `Kind:` label: the eight finding labels and
    # the three verdict tokens are byte-stable, so `aidw/findings.py:_LABELS` and
    # `aidw/verdict.py` still parse.
    format_block = rendered.split("```text", 1)[1].split("```", 1)[0]
    assert [
        f"{line.split(':', 1)[0]}:"
        for line in format_block.splitlines()
        if ":" in line
    ] == [
        "Priority:",
        "Confidence:",
        "Kind:",
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
    # M3: the tokens are still byte-stable, and the prompt now fixes the line that
    # `parse_verdict`'s declaration pass reads instead of leaving the shape to the model.
    assert "\nVerdict: Approve\n" in rendered

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

#: E7.3/D16: the *second* gate channel. ``AGENTS.md`` keeps its own ``## Gates`` section
#: (the AGENTS.md-only fixture above, unchanged); this file carries the commands R14 sends
#: to ``aidw/conventions.md``, plus a trailing ``## Tests`` heading that must also bound
#: the extracted section.
CONVENTIONS_EVIDENCE_FIXTURE = """# Repo conventions

Intro prose.

## Gates

```bash
conventions-repo-only gate --strict
```

## Tests

This heading ends the conventions gate section and must not be copied.
"""

#: C1.2: the alias heading. ``## Gate commands`` is the second recognised heading, so a repo
#: that publishes its gates under that name must supply the commands instead of degrading.
GATE_COMMANDS_EVIDENCE_FIXTURE = """# Repo conventions

Intro prose.

## Gate commands

```bash
gate-commands-repo-only gate --check
```

## Tests

This heading ends the gate-commands section and must not be copied.
"""

#: C1.2: a target-declared heading. The value is the **full** ``## ``-prefixed line; a bare
#: title is a different string and must not match.
CONFIGURED_GATES_HEADING = "## Verification gates"

CONFIGURED_HEADING_FIXTURE = """# Repo conventions

Intro prose.

## Verification gates

```bash
declared-heading gate --check
```

## Tests

This heading ends the declared gate section and must not be copied.
"""

EXTRACTION_EVIDENCE_FIXTURE = """# Extraction

## 3.8 Task-prompt format and repo conventions (D16)

The conventions channel.
"""


def _evidence_repo(
    tmp_path: Path,
    monkeypatch,
    *,
    agents_md: str | None = AGENTS_EVIDENCE_FIXTURE,
    conventions_md: str | None = None,
) -> Path:
    """A committed bare+control repo (no ``origin``) with the evidence fixtures.

    Committed so the local base branch resolves to a real sha while ``origin/main``
    stays absent — the no-origin fixture the base-branch assertion needs — and so branch
    setup can create a real task worktree from it.

    ``conventions_md`` defaults to ``None`` so the AGENTS.md-only fixture every existing
    assertion uses stays byte-for-byte what it was; only the E7.3 gate-source tests add
    the second channel (D16).
    """
    files = {
        "docs/tasks/03 - Test Phase.md": ROADMAP_EVIDENCE,
        "docs/migration/EXTRACTION.md": EXTRACTION_EVIDENCE_FIXTURE,
    }
    if agents_md is not None:
        files["AGENTS.md"] = agents_md
    if conventions_md is not None:
        files["aidw/conventions.md"] = conventions_md
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


def test_l24_evidence_bundle_re_reads_the_configured_roadmap_dir(
    tmp_path: Path, monkeypatch
) -> None:
    """E5.2/D15: the bundle's re-read follows `paths.roadmap_dir` + `paths.roadmap_glob`.

    The roadmap directory has two readers (roadmap-format.md §6), and this test exists for
    the second one: rewiring only the `load_tasks` call would leave the Done-when/spec
    re-read on a fixed path, so here it would degrade to `unavailable` while the listing
    still worked. The repo has no `docs/tasks` at all, and the configured glob is not the
    default, so neither a hardcoded directory nor an ignored glob can pass.
    """
    _make_control_repo(
        tmp_path,
        files={
            "plans/03 - Test Phase.md": ROADMAP_EVIDENCE,
            "aidw/config.yaml": (
                "schema_version: 1\n"
                "paths:\n"
                "  roadmap_dir: plans\n"
                '  roadmap_glob: "0[0-9] - *.md"\n'
            ),
            "docs/migration/EXTRACTION.md": EXTRACTION_EVIDENCE_FIXTURE,
            "AGENTS.md": AGENTS_EVIDENCE_FIXTURE,
        },
    )
    _seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
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
    # The entry was parsed from the configured directory and glob...
    assert "03 - Test Phase.md:13" in bundle
    # ...and the same configured directory is what the re-read used: the full multi-line
    # Done when survives, which only the real file can supply.
    roadmap_section = bundle.split("## Roadmap entry", 1)[1].split(
        "## Cited spec sections", 1
    )[0]
    assert "unavailable" not in roadmap_section
    assert (
        "including a later continuation line that a first-line-only parser would drop."
        in roadmap_section
    )
    # A second consumer left on the default directory would read nothing at all.
    assert not (tmp_path / "docs" / "tasks").exists()


def test_l24_dry_run_writes_no_evidence_bundle(tmp_path: Path, monkeypatch) -> None:
    """W1.2: the dry-run path writes no run directory or evidence bundle."""
    _evidence_repo(tmp_path, monkeypatch)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL, dry_run=True
    )

    assert code == 0
    assert not _runs_root(tmp_path).exists()


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
    entries = prompt_workflow.load_tasks(tmp_path / "docs" / "tasks", "[0-9]* - *.md")
    entry = next(candidate for candidate in entries if candidate.task == "E4.1")
    directory = tmp_path / "state" / "run"

    path = prompt_workflow._write_evidence_bundle(
        stage="task-review-1",
        directory=directory,
        repo=repo,
        entry=entry,
        entries=entries,
        rel="docs/task-prompts/missing-prompt.md",
        roadmap_dir="docs/tasks",
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
    entries = prompt_workflow.load_tasks(tmp_path / "docs" / "tasks", "[0-9]* - *.md")
    entry = next(candidate for candidate in entries if candidate.task == "E4.1")

    path = prompt_workflow._write_evidence_bundle(
        stage="task-review-1",
        directory=directory,
        repo=repo,
        entry=entry,
        entries=entries,
        rel="docs/task-prompts/03-E4.1-prompt.md",
        roadmap_dir="docs/tasks",
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
# E7.3/D16 — the gate list's second channel: ``aidw/conventions.md``
# ---------------------------------------------------------------------------


def test_e73_gate_list_includes_conventions_md_commands_after_agents_md(
    tmp_path: Path, monkeypatch
) -> None:
    """R14: gate commands travel in ``conventions.md``, so the bundle must carry them.

    Both sources are present: the section must contain both gate lists, AGENTS.md's
    first (D16 order), each bounded by its own next ``## `` heading. The AGENTS.md-only
    six-element assertions elsewhere stay unchanged — this fixture only adds the second
    file.
    """
    _evidence_repo(
        tmp_path, monkeypatch, conventions_md=CONVENTIONS_EVIDENCE_FIXTURE
    )
    _seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
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
    # The AGENTS.md channel is still read exactly as before...
    assert "target-repo-only gate --check" in gate_section
    assert "uv run --frozen pytest" in gate_section
    # ...and the conventions.md channel now contributes too.
    assert "conventions-repo-only gate --strict" in gate_section
    # D16 order: AGENTS.md, then aidw/conventions.md.
    assert gate_section.index("target-repo-only") < gate_section.index(
        "conventions-repo-only"
    )
    # Each source's section is bounded by its own next `## ` heading.
    assert "This heading ends the gate section" not in gate_section
    assert "This heading ends the conventions gate section" not in gate_section


def test_e73_conventions_md_alone_supplies_the_gate_list(
    tmp_path: Path, monkeypatch
) -> None:
    """A repo that publishes its gates only in ``conventions.md`` still gets a usable list.

    No AGENTS.md at all, so a ``_gate_block`` that read only ``AGENTS.md`` would degrade to
    ``unavailable`` here. Asserted on the section renderer directly: the workflow-level
    proof above already covers the bundle wiring, and this needs no git fixture.
    """
    _evidence_repo(
        tmp_path,
        monkeypatch,
        agents_md=None,
        conventions_md=CONVENTIONS_EVIDENCE_FIXTURE,
    )
    repo = TargetRepo.resolve(tmp_path)

    block = prompt_workflow._gate_block(repo)

    assert block.startswith("## Gates")
    assert "conventions-repo-only gate --strict" in block
    assert "unavailable" not in block
    assert "This heading ends the conventions gate section" not in block


def test_e73_non_utf8_conventions_source_is_ignored_by_the_gate_block(
    tmp_path: Path,
) -> None:
    """A malformed optional source must not crash the evidence-bundle reader.

    The valid AGENTS.md gate list remains usable while the shared reader skips the
    undecodable ``aidw/conventions.md`` source, matching the injection channel's
    fail-closed behavior.
    """
    target = tmp_path / "target"
    (target / "aidw").mkdir(parents=True)
    (target / "AGENTS.md").write_text(AGENTS_EVIDENCE_FIXTURE, encoding="utf-8")
    (target / "aidw" / "conventions.md").write_bytes(b"\xff invalid utf8")
    repo = TargetRepo(root=target, git_dir=target / ".git", common_dir=target / ".git")

    block = prompt_workflow._gate_block(repo)

    assert "target-repo-only gate --check" in block
    assert "unavailable" not in block
    assert "conventions-repo-only" not in block


def test_e73_no_source_still_degrades_the_gate_block(tmp_path: Path) -> None:
    """Neither file: the unavailable note survives the second channel (L2.4 requirement 4).

    Built as a bare :class:`TargetRepo` over a plain directory — ``_gate_block`` reads only
    ``repo.root``, and a real git repo would buy process spawns for nothing.
    """
    plain = tmp_path / "plain"
    plain.mkdir()
    repo = TargetRepo(root=plain, git_dir=plain / ".git", common_dir=plain / ".git")

    assert prompt_workflow._gate_block(repo) == prompt_workflow._EVIDENCE_UNAVAILABLE


# ---------------------------------------------------------------------------
# C1.2 — two recognised gate headings, a declared one, and the diagnose-not-fail rule
# ---------------------------------------------------------------------------


def test_c12_gate_commands_heading_supplies_the_bundle_gate_commands(
    tmp_path: Path, monkeypatch
) -> None:
    """A ``## Gate commands`` conventions source contributes its commands, not ``unavailable``.

    The pre-C1.2 reader recognised only ``## Gates``, so this repo's list vanished from the
    evidence bundle. Asserted through a real run's rendered bundle, because that is the
    element the reviewer receives.
    """
    _evidence_repo(
        tmp_path,
        monkeypatch,
        agents_md=None,
        conventions_md=GATE_COMMANDS_EVIDENCE_FIXTURE,
    )
    _seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
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
    assert "gate-commands-repo-only gate --check" in gate_section
    assert "unavailable" not in gate_section
    assert "This heading ends the gate-commands section" not in gate_section


def test_c12_gate_commands_heading_alone_supplies_the_block(tmp_path: Path) -> None:
    """The section renderer alone, so the recognition is proved without a git fixture."""
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "aidw").mkdir()
    (plain / "aidw" / "conventions.md").write_text(
        GATE_COMMANDS_EVIDENCE_FIXTURE, encoding="utf-8"
    )
    repo = TargetRepo(root=plain, git_dir=plain / ".git", common_dir=plain / ".git")

    block = prompt_workflow._gate_block(repo)

    assert block.startswith("## Gate commands")
    assert "gate-commands-repo-only gate --check" in block
    assert "unavailable" not in block


def test_c12_configured_heading_is_a_full_prefixed_line_passed_in() -> None:
    """A configured ``## ``-prefixed line is recognised; the bare title is not.

    The value format is prompt-fixed: the loader stores the full heading line, and the
    matcher applies the same ``startswith`` rule as the built-in headings — so verifying
    that a bare title does *not* match pins the format, not just the happy path.
    """
    block = prompt_workflow._gates_section(
        CONFIGURED_HEADING_FIXTURE, CONFIGURED_GATES_HEADING
    )

    assert block == (
        "## Verification gates\n\n```bash\ndeclared-heading gate --check\n```"
    )
    assert (
        prompt_workflow._gates_section(CONFIGURED_HEADING_FIXTURE, "Verification gates")
        is None
    )


def test_c12_gate_block_loads_the_declared_heading_from_the_target_config(
    tmp_path: Path,
) -> None:
    """The config is read from ``repo.root``, never the toolkit root (AGENTS.md "Two roots").

    The toolkit's own config declares no ``gates_heading``, so a wrong-root load would find
    nothing and leave the section ``unavailable`` here — a self-hosted run would still pass.
    """
    plain = tmp_path / "target"
    (plain / "aidw").mkdir(parents=True)
    (plain / "aidw" / "config.yaml").write_text(
        'schema_version: 1\ngates_heading: "## Verification gates"\n',
        encoding="utf-8",
    )
    (plain / "aidw" / "conventions.md").write_text(
        CONFIGURED_HEADING_FIXTURE, encoding="utf-8"
    )
    repo = TargetRepo(root=plain, git_dir=plain / ".git", common_dir=plain / ".git")

    block = prompt_workflow._gate_block(repo)

    assert block.startswith("## Verification gates")
    assert "declared-heading gate --check" in block
    assert "unavailable" not in block


def test_c12_unrecognised_gates_like_heading_still_degrades(tmp_path: Path) -> None:
    """Case is deliberate: ``## Gate Commands`` (capital C) is not ``## Gate commands``.

    The spec fixes the two literal strings, and the degrade contract (L2.4 requirement 4)
    still holds for a heading nothing recognises — the doctor WARN is the diagnosis, not a
    run failure.
    """
    plain = tmp_path / "plain"
    (plain / "aidw").mkdir(parents=True)
    (plain / "aidw" / "conventions.md").write_text(
        "# Conventions\n\n## Gate Commands\n\ncapital-c gate --check\n",
        encoding="utf-8",
    )
    repo = TargetRepo(root=plain, git_dir=plain / ".git", common_dir=plain / ".git")

    assert prompt_workflow._gate_block(repo) == prompt_workflow._EVIDENCE_UNAVAILABLE


def test_c12_gates_section_is_pure(monkeypatch) -> None:
    """No I/O and no mutation: the function only reads the text it was handed."""
    text = CONFIGURED_HEADING_FIXTURE
    before = str(text)

    def _no_io(*_args, **_kwargs):
        raise AssertionError("`_gates_section` must not perform I/O")

    monkeypatch.setattr(Path, "read_text", _no_io)
    monkeypatch.setattr(Path, "write_text", _no_io)
    monkeypatch.setattr("builtins.open", _no_io)

    block = prompt_workflow._gates_section(text, CONFIGURED_GATES_HEADING)

    assert block is not None and "declared-heading gate --check" in block
    assert text == before


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
    assert stage_registry.RECONCILE_INSTRUCTION in extra
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
    """``render_reconcile`` never mutates its inputs and degrades, not raises (req 3).

    E4.3 moved the wording to the registry; ``_brief_diff`` keeps the workflow-side half
    (produce the diff, or ``None`` when a snapshot cannot be read).
    """
    baseline = "prompt\n"
    current = "prompt\n<!-- fix round 1 -->\n"
    review = "Review text with trailing spaces  \n"

    diff = prompt_workflow._brief_diff(
        index=1,
        baseline=baseline,
        current=current,
        rel="docs/task-prompts/03-E4.1-prompt.md",
        verb="reconcile",
        brief_name="reconcile brief",
    )
    brief = stage_registry.render_reconcile(review=review, diff=diff)

    assert stage_registry.RECONCILE_INSTRUCTION in brief
    assert review in brief
    assert "+<!-- fix round 1 -->" in brief
    # Purity: the caller's strings are untouched.
    assert baseline == "prompt\n"
    assert current == "prompt\n<!-- fix round 1 -->\n"
    # An unreadable prompt degrades to the explicit unavailable note, never an empty diff.
    assert (
        prompt_workflow._brief_diff(
            index=1,
            baseline=None,
            current=None,
            rel="docs/task-prompts/03-E4.1-prompt.md",
            verb="reconcile",
            brief_name="reconcile brief",
        )
        is None
    )
    degraded = stage_registry.render_reconcile(review=review, diff=None)
    assert stage_registry.DIFF_UNAVAILABLE in degraded
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
            # Model the real H1.1 result: both clean attempts were truncated and the
            # final attempt reported ``length``. The workflow must not collapse this
            # evidence back to the old bare message.
            stop_reason="length" if spec.name != "task-prompt" else None,
            attempts=2 if spec.name != "task-prompt" else 1,
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
    assert latest.resume == {"next_stage": "task-review-1"}
    assert not any(g.name == "approve-task-prompt" for g in latest.gates)
    log = _run_log(tmp_path, latest.run_id)
    assert "task-review-1: both attempts produced no final message" in log
    assert "final stop_reason: length" in log
    assert "both attempts were truncated" in log
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


def test_l43_config_max_revisions_beats_the_default(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A target config declaring `max_revisions: 2` is the effective budget (design §12).

    The config is the *target repo's* file at `<target>/aidw/config.yaml` (§3.4), read
    through the loader and merged by `resolve_config` — not the toolkit's.
    """
    _patch_prompt_repo(
        tmp_path, monkeypatch, config_text="schema_version: 1\nmax_revisions: 2\n"
    )
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
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
    assert "task-review-3" not in names

    latest = state.list_runs(_runs_root(tmp_path))[-1]
    assert latest.status == state.BLOCKED
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    for token in ("max_revisions=2", "rounds=2", "revisions=1"):
        assert token in gate.detail
    assert "max_revisions=2" in capsys.readouterr().out


def test_l43_cli_flag_beats_config_max_revisions(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """`--max-revisions 1` beats a config declaring 2: one review, no fix batch (H8)."""
    _patch_prompt_repo(
        tmp_path, monkeypatch, config_text="schema_version: 1\nmax_revisions: 2\n"
    )
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
    assert [name for name, _, _ in seen] == ["task-prompt", "task-review-1"]

    latest = state.list_runs(_runs_root(tmp_path))[-1]
    gate = [g for g in latest.gates if g.name == "approve-task-prompt"][-1]
    for token in ("max_revisions=1", "rounds=1", "revisions=0"):
        assert token in gate.detail
    assert "max_revisions=1" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("config_text", "expected"),
    [
        pytest.param("{{ not yaml: [", "cannot read/parse config", id="unparseable"),
        pytest.param(
            "schema_version: 1\nreop:\n  base_branch: main\n",
            "unknown key `reop`",
            id="unknown-key",
        ),
        pytest.param("schema_version: one\n", "must be an integer", id="wrong-type"),
    ],
)
def test_l43_broken_config_refuses_instead_of_defaulting(
    tmp_path: Path, monkeypatch, capsys, config_text: str, expected: str
) -> None:
    """A config with ERROR issues refuses with exit 2, before any run state (E3.2/Req 5).

    A silent `DEFAULT_MAX_REVISIONS` fallback would pass every earlier `max_revisions`
    test, so the assertion that matters is the refusal plus the absence of the run
    record, branch and worktree.
    """
    _patch_prompt_repo(tmp_path, monkeypatch, config_text=config_text)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
    )

    assert code == 2
    err = capsys.readouterr().err
    assert expected in err
    assert "error: config.yaml:" in err
    # Nothing was created: no stage ran, no run record, no branch and no worktree.
    assert seen == []
    assert state.list_runs(_runs_root(tmp_path)) == []
    assert not (_runs_root(tmp_path)).exists()
    assert git.worktree_for_branch(tmp_path, "03-E4.1") is None
    assert not (tmp_path.parent / f"{tmp_path.name}-ws" / "03-E4.1").exists()


def test_l43_broken_config_refuses_on_a_dry_run_too(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The refusal is independent of `--dry-run`: a plan must not hide a broken config."""
    _patch_prompt_repo(tmp_path, monkeypatch, config_text="{{ not yaml: [")
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        dry_run=True,
    )

    assert code == 2
    assert "cannot read/parse config" in capsys.readouterr().err
    assert seen == []
    assert state.list_runs(_runs_root(tmp_path)) == []


def test_l43_unreadable_directory_config_refuses_before_dry_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A directory at ``aidw/config.yaml`` is a loader error, not a missing config.

    This covers the ``Path.exists()``/``read_text()`` edge explicitly: prompt planning must
    refuse the unreadable config before it can fall back to the default budget or create
    any run state, including when the invocation is a dry run (E3.2 Requirement 5).
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    (tmp_path / "aidw" / "config.yaml").mkdir(parents=True)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        dry_run=True,
    )

    assert code == 2
    assert "cannot read/parse config" in capsys.readouterr().err
    assert seen == []
    assert state.list_runs(_runs_root(tmp_path)) == []
    assert git.worktree_for_branch(tmp_path, "03-E4.1") is None


# --------------------------------------------------------------------------- #
# E3.3 — version and compatibility refusal (D10, EXTRACTION.md §3.11)
# --------------------------------------------------------------------------- #
#
# The refusal belongs at the E3.2 config-refusal site: stderr + exit 2, before
# `load_tasks`/`derive_branch_name`, any run record, branch or worktree, and regardless of
# `--dry-run`. `EXIT_REFUSED` (4) would split the two config refusals into different
# codes; requirement 5 keeps `config show` display-only (pinned in `tests/test_cli.py`).

#: A `requires_toolkit` floor no release can satisfy: one major above the running toolkit.
#: It used to be the literal `">=1.0.0"`, which silently became **satisfiable** when the
#: project version reached 1.0.0 — the version bump turned this refusal case into a
#: no-op and reddened `main` (2026-11-08). Derived from `__version__` so the case stays
#: unsatisfiable across bumps instead of needing a second edit.
_UNSATISFIABLE_TOOLKIT = f">={int(__version__.split('.', 1)[0]) + 1}.0.0"


@pytest.mark.parametrize(
    ("config_text", "expected_tokens"),
    [
        pytest.param(
            "schema_version: 2\n",
            ("schema_version", "2", "1"),
            id="newer-schema-version",
        ),
        pytest.param(
            f'schema_version: 1\nrequires_toolkit: "{_UNSATISFIABLE_TOOLKIT}"\n',
            ("requires_toolkit", _UNSATISFIABLE_TOOLKIT, __version__),
            id="unsatisfied-requires-toolkit",
        ),
        pytest.param(
            'schema_version: 1\nrequires_toolkit: "banana"\n',
            ("requires_toolkit", "banana"),
            id="invalid-requires-toolkit",
        ),
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_e33_incompatible_config_refuses_before_any_state(
    tmp_path: Path,
    monkeypatch,
    capsys,
    config_text: str,
    expected_tokens: tuple[str, ...],
    dry_run: bool,
) -> None:
    """Both refusals exit 2 with the issues on stderr, before tasks/branch/run state.

    The toolkit version in the message is ``aidw.__version__`` (passed in, not
    hardcoded), and the refusal must hold for a real run *and* a plan: a `--dry-run` that
    silently planned an incompatible config would hide the incompatibility until the
    first real run.
    """
    _patch_prompt_repo(tmp_path, monkeypatch, config_text=config_text)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    def _must_not_run(*_args, **_kwargs):
        raise AssertionError(
            "an incompatible config must refuse before load_tasks/derive_branch_name"
        )

    monkeypatch.setattr(prompt_workflow, "load_tasks", _must_not_run)
    monkeypatch.setattr(prompt_workflow, "derive_branch_name", _must_not_run)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
        max_revisions=1,
        dry_run=dry_run,
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "error: config.yaml:" in err
    for token in expected_tokens:
        assert token in err
    # Nothing was created: no stage ran, no run record, no branch and no worktree.
    assert seen == []
    assert state.list_runs(_runs_root(tmp_path)) == []
    assert not _runs_root(tmp_path).exists()
    assert git.worktree_for_branch(tmp_path, "03-E4.1") is None
    assert not _task_worktree(tmp_path).exists()


@pytest.mark.parametrize(
    ("glob", "expected"),
    [
        pytest.param("", "must be a non-empty glob pattern", id="empty"),
        pytest.param("/etc/*.md", "must be a relative glob pattern", id="absolute"),
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_degenerate_roadmap_glob_refuses_before_load_tasks(
    tmp_path: Path,
    monkeypatch,
    capsys,
    glob: str,
    expected: str,
    dry_run: bool,
) -> None:
    """A degenerate ``paths.roadmap_glob`` refuses (stderr + exit 2) before ``load_tasks``.

    Review follow-up for PR #97, finding F1: pre-fix the value reached
    ``tasks_dir.glob`` unguarded, so the run escaped the single-refusal-site design
    (E3.3's config refusal) with a traceback instead of the documented stderr + 2.
    """
    _patch_prompt_repo(
        tmp_path,
        monkeypatch,
        config_text=(
            "schema_version: 1\npaths:\n"
            f"  roadmap_glob: \"{glob}\"\n"
        ),
    )
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    def _must_not_run(*_args, **_kwargs):
        raise AssertionError(
            "a degenerate roadmap_glob must refuse before load_tasks/derive_branch_name"
        )

    monkeypatch.setattr(prompt_workflow, "load_tasks", _must_not_run)
    monkeypatch.setattr(prompt_workflow, "derive_branch_name", _must_not_run)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
        max_revisions=1,
        dry_run=dry_run,
    )

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    err = captured.err
    assert "error: config.yaml:" in err
    assert "paths.roadmap_glob" in err
    assert expected in err
    # Nothing was created: no stage ran, no run record, no branch and no worktree.
    assert seen == []
    assert state.list_runs(_runs_root(tmp_path)) == []
    assert not _runs_root(tmp_path).exists()
    assert git.worktree_for_branch(tmp_path, "03-E4.1") is None
    assert not _task_worktree(tmp_path).exists()


def test_e33_both_refusals_are_reported(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A config that is both newer and pins an unsatisfied version reports both issues."""
    _patch_prompt_repo(
        tmp_path,
        monkeypatch,
        config_text=(
            f'schema_version: 2\nrequires_toolkit: "{_UNSATISFIABLE_TOOLKIT}"\n'
        ),
    )
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        max_revisions=1,
    )

    assert code == 2
    err = capsys.readouterr().err
    assert err.count("error: config.yaml:") == 2
    assert "schema_version" in err
    assert "requires_toolkit" in err
    assert seen == []
    assert state.list_runs(_runs_root(tmp_path)) == []


def test_e33_satisfied_pin_still_proceeds(tmp_path: Path, monkeypatch) -> None:
    """The happy path: a compatible pin must not refuse (or the refusal is unconditional)."""
    _patch_prompt_repo(
        tmp_path,
        monkeypatch,
        config_text=f'schema_version: 1\nrequires_toolkit: ">={__version__}"\n',
    )
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

    assert code == 3  # the fake review requests changes; compatibility did not refuse
    assert [name for name, _, _ in seen] == ["task-prompt", "task-review-1"]
    assert state.list_runs(_runs_root(tmp_path)) != []


# --------------------------------------------------------------------------- #
# E3.7 path preflight: EXTRACTION.md §3.4 "Configured read-paths must exist"
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("dry_run", [False, True])
def test_e37_missing_configured_read_path_refuses_before_any_state(
    tmp_path: Path, monkeypatch, capsys, dry_run: bool
) -> None:
    """A config naming a nonexistent read-path refuses (exit 2) before load_tasks.

    Same site and contract as the two config refusals above: stderr via
    :func:`format_issues`, exit 2, no run record, no branch and no worktree — and for a
    plan as well as a real run, so ``--dry-run`` cannot hide a missing directory.
    """
    _patch_prompt_repo(
        tmp_path,
        monkeypatch,
        config_text="schema_version: 1\npaths:\n  task_prompts_dir: docs/no-prompts\n",
    )
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    def _must_not_run(*_args, **_kwargs):
        raise AssertionError(
            "a missing read-path must refuse before load_tasks/derive_branch_name"
        )

    monkeypatch.setattr(prompt_workflow, "load_tasks", _must_not_run)
    monkeypatch.setattr(prompt_workflow, "derive_branch_name", _must_not_run)

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        approve_all=True,
        dry_run=dry_run,
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "error: config.yaml:" in err
    # §3.4: the message names the field *and* the path, so the operator knows what to
    # create or override.
    assert "`paths.task_prompts_dir`" in err
    assert str(tmp_path / "docs" / "no-prompts") in err
    assert "source: config" in err
    assert seen == []
    assert state.list_runs(_runs_root(tmp_path)) == []
    assert not _runs_root(tmp_path).exists()
    assert git.worktree_for_branch(tmp_path, "03-E4.1") is None
    assert not _task_worktree(tmp_path).exists()


def test_e37_missing_default_read_path_refuses_in_a_configless_repo(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """D17/R7: the defaults are validated too, and before the dirty-tree preflight.

    The fixture commits ``docs/task-prompts/.gitkeep`` (so the default read-path exists);
    removing it leaves the tree dirty *and* the path missing. The path refusal is exit 2
    and the dirty-tree refusal is exit 4, so the exit code also pins the ordering.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    (tmp_path / "docs" / "task-prompts" / ".gitkeep").unlink()
    (tmp_path / "docs" / "task-prompts").rmdir()
    assert not (tmp_path / "aidw" / "config.yaml").exists()
    assert git.is_clean(tmp_path) is False
    # No model may be reached: the refusal precedes every stage (and the branch setup).
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "`paths.task_prompts_dir`" in err
    assert str(tmp_path / "docs" / "task-prompts") in err
    assert "source: default" in err


def test_e37_complete_repo_passes_the_path_preflight(
    tmp_path: Path, monkeypatch
) -> None:
    """The positive control: the fixture's four read-paths are enough to proceed."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=RUN_LABEL,
        approve_all=True,
    )

    assert code == 0
    assert [name for name, _, _ in seen][0] == "task-prompt"


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
    assert latest.resume == {"next_stage": "task-prompt"}
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

# --------------------------------------------------------------------------- #
# One run per worktree (E2.7, EXTRACTION.md §3.2/§3.10)
# --------------------------------------------------------------------------- #


def test_the_task_worktree_key_is_held_for_the_whole_run_and_free_after(
    tmp_path: Path, monkeypatch
) -> None:
    """The key is the task worktree the run creates, held until ``run()`` returns.

    Prompt-vs-prompt contention cannot exercise the lock — git's one-branch-one-worktree
    rule refuses a second ``prompt.run`` for the same branch before the lock is reached —
    so this proves the *wiring*: while the author stage runs, a concurrent
    implement/fix/review/approve started in the just-created task worktree would be
    refused by the same key; after ``run()`` exits the key is free.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    entered, release = threading.Event(), threading.Event()

    def blocking_stage(spec, **kwargs):
        if spec.name == "task-prompt":
            entered.set()
            assert release.wait(timeout=60), "the holding run was never released"
        return fake(spec, **kwargs)

    monkeypatch.setattr(prompt_workflow, "run_stage", blocking_stage)
    roots = _roots(tmp_path)
    state_root = roots["workspace"].state_root
    outcome: dict = {}

    def hold() -> None:
        try:
            outcome["code"] = prompt_workflow.run(
                phase="03",
                epic="E4",
                task="E4.1",
                **roots,
                label=RUN_LABEL,
                approve_all=True,
            )
        except BaseException as exc:  # pragma: no cover - asserted via ``outcome``
            outcome["error"] = exc

    holder = threading.Thread(target=hold, name="aidw-prompt-run")
    holder.start()
    assert entered.wait(timeout=60), "the author stage never ran"

    task_worktree = _task_worktree(tmp_path)
    # Branch setup precedes the acquire, so the worktree exists and is the key.
    assert git.current_branch(task_worktree) == "03-E4.1"
    with pytest.raises(lock.LockHeldError) as held:
        lock.acquire(state_root, task_worktree)
    assert held.value.worktree == task_worktree
    assert str(task_worktree) in str(held.value)

    release.set()
    holder.join(timeout=60)
    assert not holder.is_alive()
    assert "error" not in outcome, outcome.get("error")
    assert outcome["code"] == 0
    assert seen and seen[0][0] == "task-prompt"

    # Released on exit: the same worktree can start its next run.
    with lock.acquire(state_root, task_worktree) as guard:
        assert guard.held


# --------------------------------------------------------------------------- #
# core vs repo-optional preflight (E4.5a, D12/D13, EXTRACTION.md §3.5)
# --------------------------------------------------------------------------- #


def test_a_disabled_core_stage_is_refused_before_any_side_effect(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """D12/D13: P1 (the author) is core for the prompt workflow."""
    _patch_prompt_repo(
        tmp_path,
        monkeypatch,
        config_text=(
            "schema_version: 1\n"
            "workflows:\n"
            "  prompt:\n"
            "    stages:\n"
            "      - id: P1\n"
            "        enabled: false\n"
        ),
    )

    code = prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        dry_run=True,
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "workflows.prompt.stages" in err
    assert "P1" in err
    assert "core stage cannot be disabled" in err
    # Before any run record or worktree, `--dry-run` included.
    assert state.list_runs(_runs_root(tmp_path)) == []
    assert not _task_worktree(tmp_path).exists()


# --------------------------------------------------------------------------- #
# repo-added stages in a name-keyed workflow (E4.5b req 2/req 5)
# --------------------------------------------------------------------------- #

#: The declared `prompt:` of a repo-added prompt stage, relative to the target root.
REPO_ADDED_PROMPT = "aidw/prompts/repo-added.md"

#: P1 (the only static stage) plus a repo-added one, which `prompt`'s name-keyed consumer
#: never runs: E4.5b's non-goal, warned about rather than silently dropped.
_CONFIG_WITH_REPO_ADDED = (
    "schema_version: 1\n"
    "workflows:\n"
    "  prompt:\n"
    "    stages:\n"
    "      - id: P1\n"
    "      - id: repo-added-review\n"
    "        agent: task-reviewer\n"
    "        prompt: aidw/prompts/repo-added.md\n"
)


def _write_repo_added_prompt(root: Path, text: str = "# repo-added stage\n") -> None:
    path = root / REPO_ADDED_PROMPT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run_prompt_dry(tmp_path: Path) -> int:
    return prompt_workflow.run(
        phase="03",
        epic="E4",
        task="E4.1",
        **_roots(tmp_path),
        label=RUN_LABEL,
        dry_run=True,
    )


def test_a_repo_added_stage_is_accepted_warned_about_and_never_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 2/req 5: accepted, warned about by id, and never executed (non-goal)."""
    _patch_prompt_repo(tmp_path, monkeypatch, config_text=_CONFIG_WITH_REPO_ADDED)
    _write_repo_added_prompt(tmp_path)

    code = _run_prompt_dry(tmp_path)

    assert code == 0
    captured = capsys.readouterr()
    assert "workflow `prompt` stage `repo-added-review`" in captured.err
    assert "repo-added" in captured.err
    # The name-keyed consumer plans the registry's stages only: the entry never executes.
    # W1.2: a dry run records no run, so the printed plan is the evidence — the author and
    # the first review are planned, and the repo-added id appears only in the warning.
    assert "stage:  task-prompt" in captured.out
    assert "stage:  task-review-1" in captured.out
    assert "repo-added-review" not in captured.out
    assert not _runs_root(tmp_path).exists()


def test_a_repo_added_stage_with_a_missing_prompt_is_refused(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 5: exit 2 via ``format_issues``, before any run record or worktree."""
    _patch_prompt_repo(tmp_path, monkeypatch, config_text=_CONFIG_WITH_REPO_ADDED)

    code = _run_prompt_dry(tmp_path)

    assert code == 2
    err = capsys.readouterr().err
    assert "error: workflows.prompt.stages: " in err
    assert "`repo-added-review`" in err
    assert "prompt does not resolve" in err
    assert state.list_runs(_runs_root(tmp_path)) == []
    assert not _task_worktree(tmp_path).exists()


def test_a_repo_added_stage_with_an_unknown_agent_is_refused(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 4/req 5: an unknown declared ``agent`` refuses here, not in ``run_stage``."""
    _patch_prompt_repo(
        tmp_path,
        monkeypatch,
        config_text=_CONFIG_WITH_REPO_ADDED.replace("agent: task-reviewer", "agent: nobody"),
    )
    _write_repo_added_prompt(tmp_path)

    code = _run_prompt_dry(tmp_path)

    assert code == 2
    err = capsys.readouterr().err
    assert "`repo-added-review`" in err
    assert "unknown agent `nobody`" in err
    assert state.list_runs(_runs_root(tmp_path)) == []


# --------------------------------------------------------------------------- #
# Resumability (H1.2, design §8.1/§9.3/§9.4/§14)
# --------------------------------------------------------------------------- #

#: Run label for a *seeded* record. ``new_run_id`` stamps whole seconds, so seeding a run
#: and then minting a fresh one with the same label in the same test would collide on the
#: run directory; a distinct label keeps the two run ids distinct.
SEED_LABEL = "pytest-seed"


def _run_prompt(tmp_path: Path, *, label: str = RUN_LABEL, **kwargs) -> int:
    """Call ``prompt_workflow.run`` for the fixture task with this test's isolated roots."""
    return prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(tmp_path), label=label, **kwargs
    )


def _only_run(tmp_path: Path) -> state.RunState:
    runs = state.list_runs(_runs_root(tmp_path))
    assert len(runs) == 1, [run.run_id for run in runs]
    return runs[0]


def _state_text(tmp_path: Path, run_id: str) -> str:
    directory = state.run_dir(_runs_root(tmp_path), run_id)
    return (directory / "state.json").read_text(encoding="utf-8")


def _fail_stages(fake, names: set[str]):
    """Wrap a fake ``run_stage`` so the named stages come back ``failed``.

    The fake already wrote the stage's ``.out.txt`` and recorded it, so a resumed run has
    exactly what a real failed stage leaves behind: a record with a status that is not
    ``succeeded`` and recorded text the rebuild can re-parse.
    """

    def wrapped(spec, **kwargs):
        record = fake(spec, **kwargs)
        if spec.name in names:
            record.status = state.FAILED
            record.error = "injected failure"
        return record

    return wrapped


def _explode_create(*args: object, **kwargs: object) -> object:
    raise AssertionError("create_run must not fire on a resume")


def _explode_locate(*args: object, **kwargs: object) -> object:
    raise AssertionError("a resumed/declined run must not reach the worktree locate")


def _explode_lock(*args: object, **kwargs: object) -> object:
    raise AssertionError("this refusal must precede the worktree lock")


#: A run that fails at a *review* stage after round 1's fixes: the shape the roadmap's
#: "a run that failed at `task-review-2`" describes.
FAIL_AT_REVIEW_2 = {"task-review-2"}


def test_resume_continues_at_the_failed_review_with_one_run_id(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.2 req 1/4: resume at `task-review-2`, never re-author, never mint a second run.

    Also the resume-over-a-dirty-tree case: a failed run leaves uncommitted prompt edits in
    its own worktree, and a resume proceeds in exactly that tree (req 2's exemption).
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(
        prompt_workflow, "run_stage", _fail_stages(fake1, FAIL_AT_REVIEW_2)
    )

    assert _run_prompt(tmp_path) == 1

    failed = _only_run(tmp_path)
    run_id = failed.run_id
    assert failed.status == state.FAILED
    assert failed.resume == {"next_stage": "task-review-2"}
    recorded = [stage.name for stage in failed.stages]
    assert recorded[:2] == ["task-prompt", "task-review-1"]
    worktree = _task_worktree(tmp_path)
    assert not git.is_clean(worktree)  # the failed run's own partial edits

    seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)

    code = _run_prompt(tmp_path, resume=True, approve_all=True)

    assert code == 0
    names = [name for name, _variables, _extra in seen2]
    assert names[0] == "task-review-2"
    assert "task-prompt" not in names
    assert "task-review-1" not in names
    assert not any(name.startswith("task-review-fixes-1") for name in names)

    resumed = _only_run(tmp_path)  # one run directory: no `create_run` fired
    assert resumed.run_id == run_id
    assert resumed.status == state.SUCCEEDED
    # H1.2 req 3: a successful run clears the resume key.
    assert resumed.resume == {"next_stage": None}
    assert [stage.name for stage in resumed.stages].count("task-review-2") == 1
    review = resumed.stage("task-review-2")
    assert review is not None and review.status == state.SUCCEEDED
    # The skipped round is reported rather than silently dropped.
    assert "task-review-1 [skipped]" in capsys.readouterr().out


def test_resume_does_not_reask_an_already_approved_gate(
    tmp_path: Path, monkeypatch
) -> None:
    """Design §9.4: a recorded approval survives a failed stage and is not re-asked."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(
        prompt_workflow, "run_stage", _fail_stages(fake1, FAIL_AT_REVIEW_2)
    )
    assert _run_prompt(tmp_path, require_approval=True) == 1

    failed = _only_run(tmp_path)
    failed.record_gate(
        state.GateRecord(
            name=prompt_workflow.GATE,
            decision="approved",
            mechanism="human",
            at=state.utcnow_iso(),
        )
    )
    state.save(state.run_dir(_runs_root(tmp_path), failed.run_id), failed)

    _seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)

    def fail_if_reasked(*args, **kwargs):
        raise AssertionError("an already-approved gate must not be re-asked")

    monkeypatch.setattr(prompt_workflow, "decide", fail_if_reasked)
    assert (
        _run_prompt(
            tmp_path,
            resume=True,
            approve_all=True,
            require_approval=True,
        )
        == 0
    )

    resumed = _only_run(tmp_path)
    assert any(
        gate.name == prompt_workflow.GATE
        and gate.decision == "approved"
        and gate.mechanism == "human"
        for gate in resumed.gates
    )


def test_resume_rebuilds_the_prior_rounds_fix_batch_from_its_review_text(
    tmp_path: Path, monkeypatch
) -> None:
    """H1.2 req 4: the batch is re-parsed from the recorded review, never inferred from names.

    ``TASK_REVIEW_CHANGES`` has two blocking findings plus one could-fix finding, so round
    1 planned ``task-review-fixes-1-1``/``-1-2``/``-1-3``. Failing at ``-1-2`` leaves ``-1-1``
    succeeded; the resume must replan the same remaining stages with the same partitions,
    which only a real ``FixBatch`` rebuilt from the review text can produce.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(
        prompt_workflow, "run_stage", _fail_stages(fake1, {"task-review-fixes-1-2"})
    )

    assert _run_prompt(tmp_path) == 1

    failed = _only_run(tmp_path)
    assert failed.resume == {"next_stage": "task-review-fixes-1-2"}
    assert [
        stage.name for stage in failed.stages if stage.name.startswith("task-review-fixes")
    ] == ["task-review-fixes-1-1", "task-review-fixes-1-2"]

    seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)

    assert _run_prompt(tmp_path, resume=True, approve_all=True) == 0

    assert [name for name, _variables, _extra in seen2] == [
        "task-review-fixes-1-2",
        "task-review-fixes-1-3",
        "task-review-reconcile-1",
        "task-review-2",
    ]
    extras = {name: extra for name, _variables, extra in seen2}
    # The rebuilt partition is the recorded review's: the second blocking finding, then the
    # combined could-fix block the stage names alone cannot distinguish.
    assert "The prompt is silent on matrix coverage" in extras["task-review-fixes-1-2"]
    assert "The annotations contradict the import strategy" not in extras[
        "task-review-fixes-1-2"
    ]
    assert "Non-blocking (could-fix) review finding" in extras["task-review-fixes-1-3"]
    assert _only_run(tmp_path).run_id == failed.run_id


def test_resume_rebuilds_the_unparseable_fallback_batch(
    tmp_path: Path, monkeypatch
) -> None:
    """H1.2 req 4: a review that never parsed is replanned as its single fallback stage."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_UNPARSEABLE, approve_review=2)
    monkeypatch.setattr(
        prompt_workflow, "run_stage", _fail_stages(fake1, {"task-review-fixes-1"})
    )

    assert _run_prompt(tmp_path) == 1
    assert _only_run(tmp_path).resume == {"next_stage": "task-review-fixes-1"}

    seen2, fake2 = _fake_stages(TASK_REVIEW_UNPARSEABLE, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)

    assert _run_prompt(tmp_path, resume=True, approve_all=True) == 0

    names = [name for name, _variables, _extra in seen2]
    assert names[0] == "task-review-fixes-1"
    assert not any(name.startswith("task-review-fixes-1-") for name in names)
    extras = {name: extra for name, _variables, extra in seen2}
    # The fallback carries the whole recorded review verbatim.
    assert "## Review findings to address" in extras["task-review-fixes-1"]
    assert "Something is wrong" in extras["task-review-fixes-1"]


def test_resume_acquires_the_same_worktree_keyed_lock(
    tmp_path: Path, monkeypatch
) -> None:
    """H1.2 req 7: the resume takes the lock keyed on the reused worktree's path."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(
        prompt_workflow, "run_stage", _fail_stages(fake1, FAIL_AT_REVIEW_2)
    )
    assert _run_prompt(tmp_path) == 1

    keys: list[Path] = []
    real_acquire = prompt_workflow.lock.acquire

    def recording_acquire(state_root, worktree):
        keys.append(worktree)
        return real_acquire(state_root, worktree)

    monkeypatch.setattr(prompt_workflow.lock, "acquire", recording_acquire)
    _seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)

    assert _run_prompt(tmp_path, resume=True, approve_all=True) == 0
    assert keys == [_task_worktree(tmp_path)]


# --------------------------------------------------------------------------- #
# Fresh re-run worktree rules (H1.2 req 2)
# --------------------------------------------------------------------------- #


def test_a_fresh_rerun_refuses_a_dirty_reused_worktree(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.2 req 2: a fresh re-run neither reuses nor discards a dirty task worktree."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(
        prompt_workflow, "run_stage", _fail_stages(fake1, FAIL_AT_REVIEW_2)
    )
    assert _run_prompt(tmp_path) == 1
    worktree = _task_worktree(tmp_path)
    dirty = git.status_short(worktree)
    assert dirty != ""

    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)

    code = _run_prompt(tmp_path)

    assert code == 4
    err = capsys.readouterr().err
    remove_command, branch_command = prompt_workflow.worktree_clear_commands(
        _roots(tmp_path)["workspace"], "03-E4.1", "main"
    )
    assert remove_command in err
    assert branch_command in err
    assert "aidw worktree remove 03-E4.1 --force" in err
    assert "branch -D 03-E4.1" in err
    # No second run, and nothing was discarded (design §13).
    assert len(state.list_runs(_runs_root(tmp_path))) == 1
    assert worktree.is_dir()
    assert git.status_short(worktree) == dirty


def test_a_fresh_rerun_refuses_a_leftover_branch(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.2 req 2: worktree removed but the branch alive — exit 4 with both clear commands."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(
        prompt_workflow, "run_stage", _fail_stages(fake1, FAIL_AT_REVIEW_2)
    )
    assert _run_prompt(tmp_path) == 1
    worktree = _task_worktree(tmp_path)
    assert git.remove_worktree(tmp_path, worktree, force=True)
    assert git.worktree_for_branch(tmp_path, "03-E4.1") is None

    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)

    code = _run_prompt(tmp_path)

    assert code == 4
    err = capsys.readouterr().err
    assert "branch-setup refused" in err
    assert "aidw worktree remove 03-E4.1 --force" in err
    assert "branch -D 03-E4.1" in err
    assert len(state.list_runs(_runs_root(tmp_path))) == 1


def test_resume_refuses_when_its_worktree_is_missing(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.2 req 2: a resume never recreates the failed run's missing worktree."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(
        prompt_workflow, "run_stage", _fail_stages(fake, FAIL_AT_REVIEW_2)
    )
    assert _run_prompt(tmp_path) == 1
    failed = _only_run(tmp_path)
    before = _state_text(tmp_path, failed.run_id)
    worktree = _task_worktree(tmp_path)
    assert git.remove_worktree(tmp_path, worktree, force=True)
    assert git.worktree_for_branch(tmp_path, "03-E4.1") is None

    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)

    code = _run_prompt(tmp_path, resume=True, approve_all=True)

    assert code == 4
    err = capsys.readouterr().err
    assert failed.run_id in err
    assert "has no worktree" in err
    assert _state_text(tmp_path, failed.run_id) == before
    assert len(state.list_runs(_runs_root(tmp_path))) == 1


# --------------------------------------------------------------------------- #
# The stale `running` record (H1.2 req 1)
# --------------------------------------------------------------------------- #


def test_a_stale_running_record_refuses_a_fresh_run_but_resume_takes_it_over(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A crashed run releases its lock and keeps a `running` record: one run id, ever."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    worktree = git.add_worktree(tmp_path, "03-E4.1")
    assert worktree is not None
    runs_dir = _runs_root(tmp_path)
    crashed = state.create_run(
        runs_dir, worktree, "prompt", label=SEED_LABEL, branch="03-E4.1"
    )
    directory = state.run_dir(runs_dir, crashed.run_id)
    crashed.record_stage(
        state.StageRecord(
            name="task-prompt",
            agent="task-author",
            model="test-model",
            status=state.FAILED,
            error="the process died between stages",
        )
    )
    state.save(directory, crashed)
    assert state.list_runs(runs_dir)[-1].status == state.RUNNING

    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)

    code = _run_prompt(tmp_path)

    assert code == 4
    err = capsys.readouterr().err
    assert "still marked running" in err
    assert crashed.run_id in err
    assert len(state.list_runs(runs_dir)) == 1

    code = _run_prompt(tmp_path, resume=True, approve_all=True)

    assert code == 0
    # The in-flight stage's record is not `succeeded`, so it re-runs — no `next_stage` was
    # ever stamped, which is exactly what a crash leaves behind.
    assert [name for name, _variables, _extra in seen][0] == "task-prompt"
    resumed = _only_run(tmp_path)
    assert resumed.run_id == crashed.run_id
    assert resumed.status == state.SUCCEEDED


def test_a_declined_resume_leaves_no_side_effect(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.2 req 1: answering no exits 4 before the locate, the lock and any write."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(
        prompt_workflow, "run_stage", _fail_stages(fake1, FAIL_AT_REVIEW_2)
    )
    assert _run_prompt(tmp_path) == 1
    failed = _only_run(tmp_path)
    before = _state_text(tmp_path, failed.run_id)

    monkeypatch.setattr(prompt_workflow, "_confirm_resume", lambda assume_yes: False)
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)
    monkeypatch.setattr(git, "worktree_for_branch", _explode_locate)
    monkeypatch.setattr(prompt_workflow.lock, "acquire", _explode_lock)

    code = _run_prompt(tmp_path, resume=True)

    assert code == 4
    out = capsys.readouterr()
    assert "resume declined." in out.err
    # The completed-stages print happens before the question, then nothing else does.
    assert "completed stages:" in out.out
    assert failed.run_id in out.out
    assert _state_text(tmp_path, failed.run_id) == before
    assert len(state.list_runs(_runs_root(tmp_path))) == 1


def test_resume_without_a_matching_run_is_a_usage_error(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _patch_prompt_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)

    code = _run_prompt(tmp_path, resume=True)

    assert code == 2
    assert "no prompt run to resume for `03-E4.1`" in capsys.readouterr().err
    assert state.list_runs(_runs_root(tmp_path)) == []
    assert len(git.worktrees(tmp_path)) == 1


# --------------------------------------------------------------------------- #
# `--from` (H1.2 req 5)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name",
    [
        "bogus",
        "task-prompt-fixes-1",
        "task-review-5",  # out of budget under the default 3
        "task-review-0",
        "task-review-fixes-3-1",  # round 3 has no fix batch at budget 3
        "task-review-reconcile-3",
        "task-review-fixes-1-0",  # a finding index starts at 1
        "task-review-fixes-1-2-extra",
    ],
)
def test_an_unknown_or_out_of_budget_from_stage_is_a_usage_error(
    tmp_path: Path, monkeypatch, capsys, name: str
) -> None:
    """H1.2 req 5: the grammar is the loop's, bounded by the resolved ``max_revisions``."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)

    code = _run_prompt(tmp_path, from_stage=name, dry_run=True)

    assert code == 2
    err = capsys.readouterr().err
    assert f"unknown stage `{name}`" in err
    assert "max_revisions=3" in err
    assert state.list_runs(_runs_root(tmp_path)) == []
    assert len(git.worktrees(tmp_path)) == 1


@pytest.mark.parametrize(
    ("name", "max_revisions", "valid"),
    [
        ("task-prompt", 1, True),
        ("task-review-1", 1, True),
        ("task-review-3", 3, True),
        ("task-review-4", 3, False),
        ("task-review-fixes-1", 3, True),
        ("task-review-fixes-1-42", 3, True),  # a finding index is not budgeted
        ("task-review-fixes-2-1", 3, True),
        ("task-review-fixes-3-1", 3, False),  # the terminal round has no fix batch
        ("task-review-reconcile-2", 3, True),
        ("task-review-reconcile-3", 3, False),
        ("task-review-1", 0, False),  # a zero budget accepts nothing
        ("task-review-fixes-1", 1, False),
        ("task-prompt", 0, True),
        ("impliment-task", 3, False),
    ],
)
def test_is_from_stage_is_the_loops_bounded_grammar(
    name: str, max_revisions: int, valid: bool
) -> None:
    """H1.2 req 5's predicate, pinned directly (pure, no run state, no I/O)."""
    assert prompt_workflow.is_from_stage(name, max_revisions) is valid


def test_from_with_resume_re_runs_a_succeeded_stage_in_the_same_run(
    tmp_path: Path, monkeypatch
) -> None:
    """H1.2 req 5: `--from` overrides `next_stage` and re-runs even succeeded records."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(
        prompt_workflow, "run_stage", _fail_stages(fake1, {"task-review-fixes-1-2"})
    )
    assert _run_prompt(tmp_path) == 1
    failed = _only_run(tmp_path)
    assert failed.resume == {"next_stage": "task-review-fixes-1-2"}

    seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)

    code = _run_prompt(
        tmp_path, resume=True, from_stage="task-review-1", approve_all=True
    )

    assert code == 0
    names = [name for name, _variables, _extra in seen2]
    assert names[0] == "task-review-1"
    assert "task-prompt" not in names
    # Recorded `succeeded` and still forced by the explicit override.
    assert "task-review-fixes-1-1" in names
    assert _only_run(tmp_path).run_id == failed.run_id


def test_from_without_resume_starts_a_fresh_run(tmp_path: Path, monkeypatch) -> None:
    """H1.2 req 5: `--from` alone is a fresh run — new run id, fresh-re-run worktree rules."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    worktree = git.add_worktree(tmp_path, "03-E4.1")
    assert worktree is not None
    runs_dir = _runs_root(tmp_path)
    seeded = state.create_run(
        runs_dir, worktree, "prompt", label=SEED_LABEL, branch="03-E4.1"
    )
    seeded.status = state.FAILED
    state.save(state.run_dir(runs_dir, seeded.run_id), seeded)

    seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    code = _run_prompt(tmp_path, from_stage="task-review-1", approve_all=True)

    assert code == 0
    run_ids = {run.run_id for run in state.list_runs(runs_dir)}
    assert len(run_ids) == 2
    assert seeded.run_id in run_ids
    # The named review stage is absent from a fresh plan, so the author is planned afresh.
    assert [name for name, _variables, _extra in seen][0] == "task-prompt"


# --------------------------------------------------------------------------- #
# Blocked runs: the scoped exit-3 refusal (H1.2 req 6, H1.3 req 1)
# --------------------------------------------------------------------------- #


def _blocked_run(tmp_path: Path, monkeypatch, fake) -> state.RunState:
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)
    assert _run_prompt(tmp_path) == 3
    blocked = _only_run(tmp_path)
    assert blocked.status == state.BLOCKED
    assert blocked.resume == {}  # design §9.3: no `next_stage` on a block
    return blocked


def _refuse_every_side_effect(monkeypatch) -> None:
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)
    monkeypatch.setattr(git, "worktree_for_branch", _explode_locate)
    monkeypatch.setattr(prompt_workflow.lock, "acquire", _explode_lock)


def test_blocked_resume_names_the_authors_recorded_block(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The author's `blocked:` line is the block's own recorded reason."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen, fake = _blocked_author_stages("blocked: cited Design 09 §5.2 is absent\n")
    blocked = _blocked_run(tmp_path, monkeypatch, fake)
    before = _state_text(tmp_path, blocked.run_id)

    _refuse_every_side_effect(monkeypatch)

    code = _run_prompt(tmp_path, resume=True)

    assert code == 3
    err = capsys.readouterr().err
    assert blocked.run_id in err
    assert "cited Design 09 §5.2 is absent" in err
    assert _state_text(tmp_path, blocked.run_id) == before


def test_blocked_resume_names_a_gate_denial_mechanism(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """`review-loop` marks the loop's own shapes; any other mechanism is a gate decision."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)
    assert (
        _run_prompt(
            tmp_path,
            require_approval=True,
            deny_gates=[prompt_workflow.GATE],
        )
        == 3
    )
    blocked = _only_run(tmp_path)
    assert blocked.status == state.BLOCKED and blocked.resume == {}
    before = _state_text(tmp_path, blocked.run_id)

    _refuse_every_side_effect(monkeypatch)

    code = _run_prompt(tmp_path, resume=True)

    assert code == 3
    err = capsys.readouterr().err
    assert blocked.run_id in err
    assert "denied by a human decision" in err
    assert "--deny-gates" in err
    assert _state_text(tmp_path, blocked.run_id) == before


# --------------------------------------------------------------------------- #
# `--dry-run` composition (H1.2 req 8)
# --------------------------------------------------------------------------- #

#: The planned stage lines every dry run prints (the author via ``print_stage``, the first
#: review via the explicit planned line).
_PLANNED_AUTHOR = "stage:  task-prompt [succeeded]"
_PLANNED_REVIEW = "stage:  task-review-1 [succeeded] (planned)"


def test_a_plain_dry_run_plans_the_author_and_first_review(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The unchanged baseline the composed dry run below is compared against."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    assert _run_prompt(tmp_path, dry_run=True) == 0

    out = capsys.readouterr().out
    assert _PLANNED_AUTHOR in out and _PLANNED_REVIEW in out
    assert "branch-setup (planned)" in out


def test_dry_run_with_resume_plans_the_fresh_baseline_without_minting_a_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.2 req 8: a dry run is always the fresh plan — no takeover, no locate, no confirm."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(
        prompt_workflow, "run_stage", _fail_stages(fake1, FAIL_AT_REVIEW_2)
    )
    assert _run_prompt(tmp_path) == 1
    failed = _only_run(tmp_path)

    monkeypatch.setattr(git, "worktree_for_branch", _explode_locate)
    monkeypatch.setattr(prompt_workflow, "_confirm_resume", _explode_lock)
    _seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)

    code = _run_prompt(tmp_path, dry_run=True, resume=True, label="pytest-fresh")

    assert code == 0
    out = capsys.readouterr().out
    assert _PLANNED_AUTHOR in out and _PLANNED_REVIEW in out
    assert "branch-setup (planned)" in out
    assert "completed stages:" not in out
    assert f"resume: {failed.run_id}" not in out
    run_ids = {run.run_id for run in state.list_runs(_runs_root(tmp_path))}
    assert run_ids == {failed.run_id}


def test_dry_run_with_resume_over_a_review_loop_block_plans_fresh(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.2 req 8 + H1.3 req 7: a forward-path block is no dry-run refusal, no takeover.

    A terminal-`Request changes` run is a continuation candidate now, so the dry run plans
    the fresh baseline exactly as over a failed run — it never takes the blocked run over,
    never prints its completed stages, copies nothing and leaves its record untouched. The
    takeover-gated half of the route (the locate) is unreachable, so it is an assertion here
    rather than a refused call.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    blocked = _blocked_run(tmp_path, monkeypatch, fake)
    before = _state_text(tmp_path, blocked.run_id)

    monkeypatch.setattr(git, "worktree_for_branch", _explode_locate)
    monkeypatch.setattr(prompt_workflow, "_confirm_resume", _explode_lock)
    _seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)

    code = _run_prompt(tmp_path, dry_run=True, resume=True, label="pytest-fresh")

    assert code == 0
    out = capsys.readouterr().out
    assert _PLANNED_AUTHOR in out and _PLANNED_REVIEW in out
    assert "completed stages:" not in out
    assert f"resume: {blocked.run_id}" not in out
    run_ids = {run.run_id for run in state.list_runs(_runs_root(tmp_path))}
    assert run_ids == {blocked.run_id}
    blocked_after = next(
        run
        for run in state.list_runs(_runs_root(tmp_path))
        if run.run_id == blocked.run_id
    )
    assert blocked_after.status == state.BLOCKED
    assert _state_text(tmp_path, blocked.run_id) == before


def test_dry_run_with_resume_over_an_author_blocked_run_still_refuses(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.3 req 7: the scoped-out refusal is not dry-run-gated and mints nothing."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen, fake = _blocked_author_stages("blocked: cited Design 09 §5.2 is absent\n")
    blocked = _blocked_run(tmp_path, monkeypatch, fake)
    before = _state_text(tmp_path, blocked.run_id)

    _refuse_every_side_effect(monkeypatch)

    code = _run_prompt(tmp_path, dry_run=True, resume=True)

    assert code == 3
    err = capsys.readouterr().err
    assert blocked.run_id in err
    assert "blocked, not failed" in err
    assert "cited Design 09 §5.2 is absent" in err
    assert len(state.list_runs(_runs_root(tmp_path))) == 1
    assert _state_text(tmp_path, blocked.run_id) == before


def test_dry_run_with_resume_over_a_human_gate_denial_still_refuses(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.3 req 1/7: the review already approved, so a fix cycle is no forward path."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)
    assert (
        _run_prompt(
            tmp_path,
            require_approval=True,
            deny_gates=[prompt_workflow.GATE],
        )
        == 3
    )
    blocked = _only_run(tmp_path)
    before = _state_text(tmp_path, blocked.run_id)

    _refuse_every_side_effect(monkeypatch)

    code = _run_prompt(tmp_path, dry_run=True, resume=True)

    assert code == 3
    err = capsys.readouterr().err
    assert blocked.run_id in err and "denied by a human decision" in err
    assert _state_text(tmp_path, blocked.run_id) == before


def test_dry_run_over_a_running_record_still_plans_fresh(
    tmp_path: Path, monkeypatch
) -> None:
    """H1.2 req 8: the still-running guard is not dry-run-gated for a *fresh* run."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    runs_dir = _runs_root(tmp_path)
    running = state.create_run(
        runs_dir, tmp_path, "prompt", label=SEED_LABEL, branch="03-E4.1"
    )
    assert running.status == state.RUNNING
    _seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake)

    assert _run_prompt(tmp_path, dry_run=True) == 4
    code = _run_prompt(tmp_path, dry_run=True, resume=True)

    assert code == 0
    run_ids = {run.run_id for run in state.list_runs(runs_dir)}
    assert run_ids == {running.run_id}


def test_dry_run_validates_from_without_minting_a_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.2 req 8: `--from` is still validated under `--dry-run`, before any run record."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)

    code = _run_prompt(tmp_path, dry_run=True, from_stage="bogus")

    assert code == 2
    assert "unknown stage `bogus`" in capsys.readouterr().err
    assert state.list_runs(_runs_root(tmp_path)) == []


def test_dry_run_from_prompt_plans_fresh_and_copies_nothing(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.3 req 7: `--dry-run --from-prompt` plans the fresh baseline, copying nothing.

    The copy and the locate are takeover-gated, so a dry run neither writes the supplied
    content onto the canonical path nor records its provenance on the blocked run.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    blocked = _blocked_run(tmp_path, monkeypatch, fake)
    prompt = _blocked_prompt_path(tmp_path)
    before_bytes = prompt.read_bytes()
    supplied = _supplied_prompt(tmp_path)

    monkeypatch.setattr(git, "worktree_for_branch", _explode_locate)
    monkeypatch.setattr(prompt_workflow, "_confirm_resume", _explode_lock)
    _seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)

    code = _run_prompt(
        tmp_path, dry_run=True, from_prompt=supplied, label="pytest-fresh"
    )

    assert code == 0
    out = capsys.readouterr().out
    assert _PLANNED_AUTHOR in out and _PLANNED_REVIEW in out
    assert "completed stages:" not in out
    assert prompt.read_bytes() == before_bytes
    run_ids = {run.run_id for run in state.list_runs(_runs_root(tmp_path))}
    assert run_ids == {blocked.run_id}
    blocked_after = next(
        run
        for run in state.list_runs(_runs_root(tmp_path))
        if run.run_id == blocked.run_id
    )
    assert "from_prompt" not in blocked_after.task


def test_dry_run_from_prompt_with_a_missing_file_is_a_usage_error(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.3 req 7: the missing-file check is not suppressed, and precedes any run record."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _refuse_every_side_effect(monkeypatch)

    code = _run_prompt(
        tmp_path, dry_run=True, from_prompt=tmp_path / "no-such-prompt.md"
    )

    assert code == 2
    assert "no such file" in capsys.readouterr().err
    assert state.list_runs(_runs_root(tmp_path)) == []


# --------------------------------------------------------------------------- #
# Blocked-run continuation (H1.3, design §8.1/§9.2/§9.3/§9.4)
# --------------------------------------------------------------------------- #

#: The canonical prompt path inside the task worktree (what the author writes, the route
#: copies `--from-prompt` content onto, and `_commit_reviewed_prompt` commits).
PROMPT_REL = "docs/task-prompts/03-E4.1-prompt.md"


def _blocked_prompt_path(tmp_path: Path) -> Path:
    return _task_worktree(tmp_path) / PROMPT_REL


def _supplied_prompt(tmp_path: Path, text: str = "supplied prompt body\n") -> Path:
    """An operator-supplied prompt file outside the repo, as `--from-prompt` takes it."""
    path = tmp_path.parent / f"{tmp_path.name}-supplied-prompt.md"
    path.write_text(text, encoding="utf-8")
    return path


def _clear_prompt_path(tmp_path: Path) -> Path:
    """Clear a blocked run's own uncommitted prompt file, as an operator would.

    The blocked run never commits (a block records no commit), so the file the author wrote
    is untracked and dirty; `--from-prompt` refuses to copy over it (design §13), which is
    why the "clean path" leg starts here.
    """
    prompt = _blocked_prompt_path(tmp_path)
    if prompt.exists():
        prompt.unlink()
    return prompt


def test_resume_continues_a_terminal_request_changes_block_with_one_extra_review(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.3 req 1/2/3/6: the same loop, the same run id, one added terminal review.

    The blocked run recorded three reviews and two fix batches (the third review was
    review-only). The continuation runs under `effective_max_revisions = 3 + 1 = 4`, so the
    walk replays the recorded rounds, appends round 3's `FixBatch` — which the original run
    never planned, because the terminal break skipped it — and its reconcile, then runs
    `task-review-4`, which is terminal (L4.1).
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    blocked = _blocked_run(tmp_path, monkeypatch, fake1)
    run_id = blocked.run_id
    recorded = [stage.name for stage in blocked.stages]
    assert recorded[-1] == "task-review-3"

    seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=4)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)

    code = _run_prompt(tmp_path, resume=True, approve_all=True)

    assert code == 0
    ran = [name for name, _variables, _extra in seen2]
    assert ran == [
        "task-review-fixes-3-1",
        "task-review-fixes-3-2",
        "task-review-fixes-3-3",
        "task-review-reconcile-3",
        "task-review-4",
    ]
    assert "task-prompt" not in ran
    out = capsys.readouterr().out
    assert "stage:  task-prompt [skipped]" in out
    for skipped in ("task-review-1", "task-review-2", "task-review-3"):
        assert f"stage:  {skipped} [skipped]" in out

    continued = _only_run(tmp_path)  # one run id: no `create_run` fired
    assert continued.run_id == run_id
    assert continued.status == state.SUCCEEDED
    assert continued.resume == {"next_stage": None}
    assert continued.task["effective_max_revisions"] == 4
    stage_names = [stage.name for stage in continued.stages]
    # The prior records are kept in order and the continuation's stages are appended after
    # them; the last stage is the added review, never a fix or a reconcile (L4.1).
    assert stage_names[: len(recorded)] == recorded
    assert stage_names[len(recorded) :] == ran
    assert stage_names[-1] == "task-review-4"
    # The reviewed prompt is committed on the task branch, once, at the same commit point a
    # fresh run uses.
    worktree = _task_worktree(tmp_path)
    assert git.changed_files(worktree, "main") == [PROMPT_REL]
    # H1.3 req 6: two gate records, distinguishable by their detail.
    gates = continued.gates
    assert len(gates) == 2
    assert gates[0].decision == "denied" and gates[0].mechanism == "review-loop"
    assert "max_revisions=3" in gates[0].detail
    assert gates[1].decision == "approved"
    assert gates[1].mechanism == "optional (default)"
    assert "max_revisions=4" in gates[1].detail
    assert "rounds=4" in gates[1].detail


def test_a_second_resume_on_a_reblocked_run_gets_one_more_round(
    tmp_path: Path, monkeypatch
) -> None:
    """H1.3 req 2: the budget guard checks the effective budget, not the resolved one.

    The first continuation re-blocks at `task-review-4`, leaving three recorded fix rounds
    while the resolved `max_revisions` is 3 — the shape H1.2's guard refuses as exit 2 when
    it is left on the resolved value. Scoped to the continuation's effective budget
    (4 + 1 = 5) it proceeds: round 4's fix batch and reconcile, then `task-review-5`.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    blocked = _blocked_run(tmp_path, monkeypatch, fake1)

    _seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)
    assert _run_prompt(tmp_path, resume=True, approve_all=True) == 3

    reblocked = _only_run(tmp_path)
    assert reblocked.run_id == blocked.run_id
    assert reblocked.status == state.BLOCKED
    assert reblocked.task["effective_max_revisions"] == 4
    assert prompt_workflow._recorded_fix_rounds(reblocked) == 3
    assert prompt_workflow.effective_max_revisions(reblocked) == 5

    seen3, fake3 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=5)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake3)

    code = _run_prompt(tmp_path, resume=True, approve_all=True)

    assert code == 0
    assert [name for name, _variables, _extra in seen3] == [
        "task-review-fixes-4-1",
        "task-review-fixes-4-2",
        "task-review-fixes-4-3",
        "task-review-reconcile-4",
        "task-review-5",
    ]
    again = _only_run(tmp_path)
    assert again.run_id == blocked.run_id
    assert again.task["effective_max_revisions"] == 5
    assert [stage.name for stage in again.stages][-1] == "task-review-5"


def test_a_continuation_that_still_requests_changes_blocks_with_a_review_last(
    tmp_path: Path, monkeypatch
) -> None:
    """H1.3 req 3: a residual `Request changes` on the added review fails closed."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    blocked = _blocked_run(tmp_path, monkeypatch, fake1)

    _seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)

    code = _run_prompt(tmp_path, resume=True, approve_all=True)

    assert code == 3
    continued = _only_run(tmp_path)
    assert continued.run_id == blocked.run_id
    assert continued.status == state.BLOCKED
    assert continued.resume == {}
    assert continued.task["effective_max_revisions"] == 4
    # L4.1 in the continuation: the last stage is a review; no fix ran after it.
    assert [stage.name for stage in continued.stages][-1] == "task-review-4"
    # Nothing was committed: the reviewed prompt is still uncommitted in the worktree.
    assert git.status_short(_task_worktree(tmp_path), paths=[PROMPT_REL]) != ""
    # Both gates are `review-loop` denials; the continuation's reports the extended budget.
    assert [gate.mechanism for gate in continued.gates] == ["review-loop", "review-loop"]
    assert "max_revisions=3" in continued.gates[0].detail
    assert "max_revisions=4" in continued.gates[1].detail


def test_a_blocked_continuation_releases_its_worktree_lock(
    tmp_path: Path, monkeypatch
) -> None:
    """H1.3 req 7: a re-blocked continuation cannot leave the worktree locked."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    blocked = _blocked_run(tmp_path, monkeypatch, fake1)

    _seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)

    assert _run_prompt(tmp_path, resume=True, approve_all=True) == 3

    # The continuation exits through the blocked path inside the lock's try/finally. A
    # second owner can acquire the same path only if that invocation released it.
    worktree = _task_worktree(tmp_path)
    acquired = prompt_workflow.lock.acquire(
        _roots(tmp_path)["workspace"].state_root, worktree
    )
    try:
        assert acquired is not None
    finally:
        acquired.release()
    assert _only_run(tmp_path).run_id == blocked.run_id


def test_a_continuation_approval_gate_is_asked_once_and_can_block(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.3 req 3/6: the post-loop gate is re-decided once, and records `decide`'s mechanism.

    A review-loop block's recorded gate is `denied`, so `already_approved` is false and
    `--require-approval` consults the human exactly once after the added review. Design §9.4
    allows re-deciding a *denied* gate (only an approved one is never re-asked). A denial
    here is the continuation's own blocked gate, with the mechanism `decide` returned — never
    `review-loop`, because the review loop did not produce that decision.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    blocked = _blocked_run(tmp_path, monkeypatch, fake1)

    decisions: list[object] = []
    real_decide = prompt_workflow.decide

    def counting_decide(*args, **kwargs):
        outcome = real_decide(*args, **kwargs)
        decisions.append(outcome)
        return outcome

    monkeypatch.setattr(prompt_workflow, "decide", counting_decide)
    _seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=4)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)

    code = _run_prompt(
        tmp_path,
        resume=True,
        approve_all=True,
        require_approval=True,
        deny_gates=[prompt_workflow.GATE],
    )

    assert code == 3
    assert len(decisions) == 1  # asked once, never skipped by the continuation
    blocked_again = _only_run(tmp_path)
    assert blocked_again.run_id == blocked.run_id
    assert blocked_again.status == state.BLOCKED
    assert blocked_again.resume == {}
    assert git.status_short(_task_worktree(tmp_path), paths=[PROMPT_REL]) != ""
    original, continuation = blocked_again.gates
    assert original.decision == "denied" and original.mechanism == "review-loop"
    assert continuation.decision == "denied"
    assert continuation.mechanism == f"--deny-gates {prompt_workflow.GATE}"
    assert continuation.mechanism != "review-loop"
    assert "max_revisions=4" in continuation.detail
    assert "rounds=4" in continuation.detail

    # H1.3 req 1/3: the run now holds a human-gate denial, so a later `--resume` meets the
    # scoped-out refusal instead of re-opening a loop whose review already approved.
    before = _state_text(tmp_path, blocked.run_id)
    _refuse_every_side_effect(monkeypatch)
    assert _run_prompt(tmp_path, resume=True) == 3
    err = capsys.readouterr().err
    assert "denied by a human decision" in err
    assert _state_text(tmp_path, blocked.run_id) == before


def test_a_continuation_approval_gate_passes_once_with_yes(
    tmp_path: Path, monkeypatch
) -> None:
    """H1.3 req 3: `--yes` approves the continuation's gate, then commits and exits 0."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    blocked = _blocked_run(tmp_path, monkeypatch, fake1)

    _seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=4)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)

    code = _run_prompt(
        tmp_path, resume=True, approve_all=True, require_approval=True
    )

    assert code == 0
    continued = _only_run(tmp_path)
    assert continued.run_id == blocked.run_id
    assert continued.status == state.SUCCEEDED
    assert continued.gates[-1].decision == "approved"
    assert continued.gates[-1].mechanism == "--yes"
    assert "max_revisions=4" in continued.gates[-1].detail
    assert git.changed_files(_task_worktree(tmp_path), "main") == [PROMPT_REL]


def test_a_blocked_verdict_continuation_fixes_reconciles_and_reviews(
    tmp_path: Path, monkeypatch
) -> None:
    """H1.3 req 1/2: a `Blocked`-verdict block is a fix-cycle shape too.

    The recorded `Blocked` verdict already decided the original run; replaying it would
    re-block with no forward path. The continuation therefore replays the round for its
    fix batch only — reconcile, then the added review — and that review's own `Blocked`
    verdict fails closed.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(
        TASK_REVIEW_CHANGES, approve_review=None, blocked_review=1
    )
    blocked = _blocked_run(tmp_path, monkeypatch, fake1)
    assert [stage.name for stage in blocked.stages][-1] == "task-review-1"
    assert prompt_workflow.effective_max_revisions(blocked) == 2

    seen2, fake2 = _fake_stages(
        TASK_REVIEW_CHANGES, approve_review=None, blocked_review=2
    )
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)

    code = _run_prompt(tmp_path, resume=True, approve_all=True)

    assert code == 3
    assert [name for name, _variables, _extra in seen2] == [
        "task-review-fixes-1-1",
        "task-review-reconcile-1",
        "task-review-2",
    ]
    continued = _only_run(tmp_path)
    assert continued.run_id == blocked.run_id
    assert continued.status == state.BLOCKED
    assert continued.task["effective_max_revisions"] == 2
    assert [stage.name for stage in continued.stages][-1] == "task-review-2"


def test_from_prompt_applies_control_preflights_but_skips_run_scoped_preflights(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.3 req 4: takeover keeps tree checks but does not repeat fetch or prerequisites."""
    roadmap = """# Phase 3: Test Phase

## Epic E3: Earlier work

- [ ] **E3.1. Incomplete predecessor** per Design 09..
  - Done when: the predecessor remains unticked.

## Epic E4: Defensive Combat

- [ ] **E4.1. Implement Total Defense** per Design 09..
  - Done when: applyTotalDefense returns the fixed effect.
"""
    _patch_prompt_repo(tmp_path, monkeypatch, roadmap=roadmap)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    # The blocking baseline must be faked too: without this the first run reaches real Pi
    # (design §15 — no test may invoke a model), and CI has no model credential, so it
    # would exit 1 at the author. G1.2's `READ_PATH_FILES` now commits a `design.md` whose
    # `## 9` section satisfies this fixture's `Design 09` citation, so the cited-spec
    # preflight passes and the run really would reach the author.
    monkeypatch.setattr(prompt_workflow, "run_stage", fake1)
    assert _run_prompt(tmp_path, allow_incomplete_prereqs=True) == 3
    capsys.readouterr()  # discard the initial run's expected predecessor warning
    blocked = _only_run(tmp_path)
    _clear_prompt_path(tmp_path)
    supplied = _supplied_prompt(tmp_path)

    def fail_if_run_scoped_preflight(*args, **kwargs):
        raise AssertionError("a blocked takeover must not repeat the base-branch fetch check")

    monkeypatch.setattr(prompt_workflow, "_verify_base_branch", fail_if_run_scoped_preflight)
    _seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)

    assert _run_prompt(tmp_path, from_prompt=supplied, approve_all=True) == 0
    assert _only_run(tmp_path).run_id == blocked.run_id
    assert "incomplete predecessor" not in capsys.readouterr().err


def test_from_prompt_alone_continues_a_blocked_run_from_review_1(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.3 req 4: `--from-prompt` alone is a takeover that re-reviews new content.

    No `--resume` is needed: the route locates, locks and reuses the same run id. The
    supplied content is copied onto the canonical path (so `rel`, the evidence bundle and
    the commit keep working), its provenance is recorded, the loop starts at
    `task-review-1` under the resolved budget, and the author record is still reused.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    blocked = _blocked_run(tmp_path, monkeypatch, fake1)
    prompt = _clear_prompt_path(tmp_path)
    supplied = _supplied_prompt(tmp_path, "supplied prompt body\n")
    supplied_bytes = supplied.read_bytes()

    seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)

    code = _run_prompt(tmp_path, from_prompt=supplied, approve_all=True)

    assert code == 0
    assert [name for name, _variables, _extra in seen2] == ["task-review-1"]
    out = capsys.readouterr().out
    assert "stage:  task-prompt [skipped]" in out
    continued = _only_run(tmp_path)
    assert continued.run_id == blocked.run_id
    assert continued.status == state.SUCCEEDED
    # Provenance: the supplied path and a sha256 over the bytes actually written.
    assert continued.task["from_prompt"] == {
        "path": str(supplied),
        "hash": f"sha256:{hashlib.sha256(supplied_bytes).hexdigest()}",
    }
    # A `--from-prompt` continuation never claims the fix cycle's extension.
    assert "effective_max_revisions" not in continued.task
    # The re-run's review-1 record supersedes the blocked run's (one record, new verdict)
    # and the rounds the new loop never reached keep their records as history.
    assert len([stage for stage in continued.stages if stage.name == "task-review-1"]) == 1
    replayed = continued.stage("task-review-1")
    assert replayed is not None
    assert "Approve" in (prompt_workflow._read_out(replayed) or "")
    assert continued.stage("task-review-2") is not None
    assert continued.stage("task-review-3") is not None
    # The reviewed-and-committed prompt is the supplied content.
    assert prompt.read_bytes() == supplied_bytes
    assert git.changed_files(_task_worktree(tmp_path), "main") == [PROMPT_REL]
    # H1.3 req 6: the gate reports the resolved budget it ran under and its own round count.
    gate = continued.gates[-1]
    assert gate.decision == "approved"
    assert "max_revisions=3" in gate.detail
    assert "rounds=1" in gate.detail


def test_from_prompt_is_an_author_blocked_runs_forward_path(
    tmp_path: Path, monkeypatch
) -> None:
    """H1.3 req 1/4: the supplied file is the forward path when no gate was recorded.

    An author-`blocked:` run keeps H1.2's exit-3 `--resume` refusal (it holds no terminal
    review whose findings a fix batch could take), so `--from-prompt` is its path. The
    re-run must not re-read the author's old marker and re-block before reviewing the
    supplied content.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen, fake = _blocked_author_stages("blocked: cited Design 09 §5.2 is absent\n")
    blocked = _blocked_run(tmp_path, monkeypatch, fake)
    assert not _blocked_prompt_path(tmp_path).exists()  # nothing on the canonical path
    supplied = _supplied_prompt(tmp_path, "supplied prompt body\n")

    seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)

    code = _run_prompt(tmp_path, from_prompt=supplied, approve_all=True)

    assert code == 0
    assert [name for name, _variables, _extra in seen2] == ["task-review-1"]
    continued = _only_run(tmp_path)
    assert continued.run_id == blocked.run_id
    assert continued.status == state.SUCCEEDED
    assert continued.task["from_prompt"]["path"] == str(supplied)
    assert _blocked_prompt_path(tmp_path).read_bytes() == supplied.read_bytes()


def test_from_prompt_takes_precedence_over_the_resume_fix_cycle(
    tmp_path: Path, monkeypatch
) -> None:
    """H1.3 req 4: with both flags the supplied content wins; no fix cycle, no extension."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    blocked = _blocked_run(tmp_path, monkeypatch, fake1)
    _clear_prompt_path(tmp_path)
    supplied = _supplied_prompt(tmp_path)

    seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)

    code = _run_prompt(tmp_path, resume=True, from_prompt=supplied, approve_all=True)

    assert code == 0
    assert [name for name, _variables, _extra in seen2] == ["task-review-1"]
    continued = _only_run(tmp_path)
    assert continued.run_id == blocked.run_id
    assert "from_prompt" in continued.task
    assert "effective_max_revisions" not in continued.task


def test_from_prompt_runs_at_the_resolved_budget_past_a_stale_effective_one(
    tmp_path: Path, monkeypatch
) -> None:
    """H1.3 req 4/6: the guard counts no recorded round, and the gate claims no extension.

    The re-blocked shape records three fix rounds while the resolved `max_revisions` is 3, so
    H1.2's guard would refuse exit 2 — but a `--from-prompt` loop rebuilds none of those
    rounds. It also runs under the resolved budget, so its gate reports `max_revisions=3`,
    never the `effective_max_revisions=4` the earlier fix cycle left on the same run.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    blocked = _blocked_run(tmp_path, monkeypatch, fake1)

    _seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)
    assert _run_prompt(tmp_path, resume=True, approve_all=True) == 3
    reblocked = _only_run(tmp_path)
    assert reblocked.task["effective_max_revisions"] == 4
    assert prompt_workflow._recorded_fix_rounds(reblocked) == 3

    _clear_prompt_path(tmp_path)
    supplied = _supplied_prompt(tmp_path)
    _seen3, fake3 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=1)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake3)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)

    code = _run_prompt(tmp_path, from_prompt=supplied, approve_all=True)

    assert code == 0
    continued = _only_run(tmp_path)
    assert continued.run_id == blocked.run_id
    gate = continued.gates[-1]
    assert gate.decision == "approved"
    assert "max_revisions=3" in gate.detail
    assert "max_revisions=4" not in gate.detail
    assert "rounds=1" in gate.detail


def test_from_prompt_refuses_a_dirty_canonical_path(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.3 req 4: the copy is a §13 discard, so a dirty path refuses exit 4 first.

    A blocked run leaves its own uncommitted prompt edits exactly where the copy would go.
    Overwriting them is the operator-work discard AIDT never performs, so the route refuses
    with the run id, the untouched path and the clear commands, and records no stage.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    blocked = _blocked_run(tmp_path, monkeypatch, fake1)
    prompt = _blocked_prompt_path(tmp_path)
    dirty_bytes = prompt.read_bytes()
    assert git.status_short(_task_worktree(tmp_path), paths=[PROMPT_REL]) != ""
    stages_before = [stage.name for stage in blocked.stages]
    before = _state_text(tmp_path, blocked.run_id)
    supplied = _supplied_prompt(tmp_path)

    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)

    code = _run_prompt(tmp_path, from_prompt=supplied, approve_all=True)

    assert code == 4
    err = capsys.readouterr().err
    assert "--from-prompt refused" in err
    assert blocked.run_id in err
    assert PROMPT_REL in err
    assert "left untouched" in err
    assert "aidw worktree remove 03-E4.1 --force" in err
    assert "branch -D 03-E4.1" in err
    assert prompt.read_bytes() == dirty_bytes  # nothing was overwritten
    assert [stage.name for stage in _only_run(tmp_path).stages] == stages_before
    assert _state_text(tmp_path, blocked.run_id) == before


def test_a_blocked_continuation_without_its_worktree_refuses_and_never_re_authors(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.3 req 5: no worktree is exit 4 naming the run, the path and the re-author command.

    Also the purity check for the route: reading the run's records (the block shape, the
    recorded rounds) writes nothing — no `save`, no `create_run` — before the locate.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    blocked = _blocked_run(tmp_path, monkeypatch, fake1)
    before = _state_text(tmp_path, blocked.run_id)
    worktree = _task_worktree(tmp_path)
    assert git.remove_worktree(tmp_path, worktree, force=True)
    assert git.worktree_for_branch(tmp_path, "03-E4.1") is None
    supplied = _supplied_prompt(tmp_path)

    saves: list[Path] = []
    real_save = prompt_workflow.save

    def recording_save(directory, run_state):
        saves.append(Path(directory))
        return real_save(directory, run_state)

    monkeypatch.setattr(prompt_workflow, "save", recording_save)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)

    for kwargs in ({"resume": True}, {"from_prompt": supplied}):
        code = _run_prompt(tmp_path, approve_all=True, **kwargs)
        assert code == 4
        err = capsys.readouterr().err
        assert "continuation refused" in err
        assert blocked.run_id in err
        assert str(worktree) in err
        assert "aidw prompt 03 E4 E4.1" in err
        assert "worktree add" not in err  # never offered for a blocked continuation

    assert saves == []  # routing read records only, before the locate
    assert _state_text(tmp_path, blocked.run_id) == before
    assert len(state.list_runs(_runs_root(tmp_path))) == 1


def test_from_prompt_requires_a_blocked_run_and_rejects_from(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.3 req 4: a missing file, a `--from` combination and a non-blocked run are usage."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    real_locate = git.worktree_for_branch
    real_acquire = prompt_workflow.lock.acquire
    real_create = prompt_workflow.create_run
    _refuse_every_side_effect(monkeypatch)

    code = _run_prompt(tmp_path, from_prompt=tmp_path / "no-such-prompt.md")

    assert code == 2
    assert "no such file" in capsys.readouterr().err
    assert state.list_runs(_runs_root(tmp_path)) == []

    supplied = _supplied_prompt(tmp_path)
    code = _run_prompt(
        tmp_path, from_prompt=supplied, from_stage="task-review-1"
    )

    assert code == 2
    assert "cannot be combined" in capsys.readouterr().err
    assert state.list_runs(_runs_root(tmp_path)) == []

    # A failed run is `--resume`/`--from`'s shape, never `--from-prompt`'s.
    monkeypatch.setattr(git, "worktree_for_branch", real_locate)
    monkeypatch.setattr(prompt_workflow.lock, "acquire", real_acquire)
    monkeypatch.setattr(prompt_workflow, "create_run", real_create)
    _seen, fake = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(
        prompt_workflow, "run_stage", _fail_stages(fake, FAIL_AT_REVIEW_2)
    )
    assert _run_prompt(tmp_path) == 1
    failed = _only_run(tmp_path)
    before = _state_text(tmp_path, failed.run_id)

    _refuse_every_side_effect(monkeypatch)
    code = _run_prompt(tmp_path, from_prompt=supplied, approve_all=True)

    assert code == 2
    err = capsys.readouterr().err
    assert failed.run_id in err
    assert "not `blocked`" in err
    assert _state_text(tmp_path, failed.run_id) == before


# --------------------------------------------------------------------------- #
# CLI wiring (H1.2 req 1)
# --------------------------------------------------------------------------- #


def test_prompt_cli_forwards_resume_and_from(tmp_path: Path, monkeypatch) -> None:
    """`aidw prompt --resume --from <stage>` reaches the workflow with both flags."""
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
            "--resume",
            "--from",
            "task-review-2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["resume"] is True
    assert captured["from_stage"] == "task-review-2"


def test_prompt_cli_forwards_from_prompt(tmp_path: Path, monkeypatch) -> None:
    """H1.3 req 4: `aidw prompt --from-prompt <path>` reaches the workflow as a Path."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    supplied = _supplied_prompt(tmp_path)
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
            "--from-prompt",
            str(supplied),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["from_prompt"] == supplied


def test_runs_resume_hint_names_the_prompt_workflow(tmp_path: Path, monkeypatch) -> None:
    """The `runs resume` hint names every workflow that has a resume path (H1.2 req 1)."""
    _patch_prompt_repo(tmp_path, monkeypatch)

    result = runner.invoke(app, ["--repo", str(tmp_path), "runs", "resume"])

    assert result.exit_code == 2
    output = result.output
    assert "aidw prompt --resume" in output
    assert "aidw implement --resume" in output
    assert "`aidw fix` has no resume" in output


# --------------------------------------------------------------------------- #
# Property sweep: the `--from` grammar is the loop's own expansion (H1.2 req 5)
# --------------------------------------------------------------------------- #

#: Pinned seed and run count (AGENTS.md "Tests": pytest only, no ``hypothesis``, so a
#: reproducible sample is the generator and there is no shrinking).
PROMPT_STAGE_PROPERTY_SEED = 3120
PROMPT_STAGE_PROPERTY_RUNS = 32


def _synthesized_review(blocking: int, could_fix: int, *, unparseable: bool) -> str:
    """A review body with the requested finding counts, in the reviewer's block format."""
    if unparseable:
        return (
            "Priority: terrible\nConfidence: 9\nKind: prompt-gap\nWhat I found: broken\n"
            "\n## Verdict\n\nRequest changes\n"
        )

    def block(priority: str) -> str:
        return (
            "```text\n"
            f"Priority: {priority}\n"
            "Confidence: 4\n"
            "Kind: prompt-gap\n"
            "What I found: something\n"
            "Why it matters: because\n"
            "Trigger and effect: always\n"
            "Where: the prompt\n"
            "Suggested fix: fix it\n"
            "```\n"
        )

    return (
        "\n".join(
            [block("Should fix") for _ in range(blocking)]
            + [block("Could fix") for _ in range(could_fix)]
        )
        + "\n## Verdict\n\nRequest changes\n"
    )


def _synthesized_batch(rng: random.Random) -> stage_registry.FixBatch:
    """A real ``FixBatch`` built the way the loop builds one (parse, then partition)."""
    unparseable = rng.random() < 0.2
    text = _synthesized_review(
        rng.randint(0, 3), rng.randint(0, 2), unparseable=unparseable
    )
    findings, problems = prompt_workflow.parse_review_findings(text)
    blocking, could_fix = prompt_workflow.partition_findings(findings)
    return stage_registry.FixBatch(
        review_text=text,
        blocking=tuple(blocking),
        could_fix=tuple(could_fix),
        unparseable=unparseable or not findings or bool(problems),
    )


def test_from_grammar_matches_the_prompt_loop_expansion_property() -> None:
    """Seeded property run (seed/runs pinned above): the grammar is the loop's own bounds.

    For every sampled budget and round of fix batches, the stages
    :func:`aidw.stage_registry.expand` plans are **all** accepted by
    :func:`aidw.workflows.prompt.is_from_stage` under that budget, in strictly increasing
    :func:`~aidw.workflows.prompt.prompt_stage_position` order, with the round's fix count
    reproducing the parsed partition — so ``--from`` can never accept a name the loop does
    not plan, nor reject one it does. The predicates are also pinned as pure: repeating a
    call returns an equal result and touches nothing.
    """
    rng = random.Random(PROMPT_STAGE_PROPERTY_SEED)

    for case in range(PROMPT_STAGE_PROPERTY_RUNS):
        max_revisions = rng.randint(1, 5)
        batches = tuple(
            _synthesized_batch(rng) for _ in range(rng.randint(0, max_revisions - 1))
        )
        planned = stage_registry.expand(
            "prompt",
            phase="03",
            epic="E4",
            task="E4.1",
            rel=f"docs/task-prompts/{case}-prompt.md",
            max_revisions=max_revisions,
            rounds=batches,
        )
        names = [stage.name for stage in planned]

        # Every planned name is accepted, and the plan is in canonical position order.
        for name in names:
            assert prompt_workflow.is_from_stage(name, max_revisions) is True
            assert prompt_workflow.prompt_stage_position(name) is not None
        positions = [prompt_workflow.prompt_stage_position(name) for name in names]
        assert positions == sorted(positions)
        assert len(set(names)) == len(names)
        # Repeating the call is the pure, deterministic answer (no state, no I/O).
        assert [prompt_workflow.prompt_stage_position(n) for n in names] == positions
        assert all(
            prompt_workflow.is_from_stage(n, max_revisions) for n in names
        )

        # The plan stops after the round that follows the batches it was given (or at the
        # budget, whichever comes first), and the grammar's budget edge is the loop's: one
        # review past `max_revisions` is never a valid `--from`.
        last_review = min(len(batches) + 1, max_revisions)
        assert f"task-review-{last_review}" in names
        assert all(
            prompt_workflow.prompt_stage_position(name)[0] <= last_review + 1
            for name in names
        )
        assert prompt_workflow.is_from_stage(
            f"task-review-{max_revisions + 1}", max_revisions
        ) is False
        # Fix rounds are bounded by `max_revisions - 1`, and each round's fix stage count
        # is the parsed partition's (one per blocking finding plus one combined stage, or
        # the single unparseable fallback).
        for index, batch in enumerate(batches, start=1):
            expected = (
                1
                if batch.unparseable
                else len(batch.blocking) + (1 if batch.could_fix else 0)
            )
            planned_round = [
                name
                for name in names
                if prompt_workflow.prompt_stage_position(name)[:2] == (index + 1, 1)
            ]
            assert len(planned_round) == expected
        if max_revisions >= 2:
            assert prompt_workflow.is_from_stage(
                f"task-review-fixes-{max_revisions}", max_revisions
            ) is False
            assert prompt_workflow.is_from_stage(
                f"task-review-reconcile-{max_revisions}", max_revisions
            ) is False
        else:
            assert not any(
                prompt_workflow.prompt_stage_position(name)[1] in (1, 2)
                for name in names
            )

        # The rebuilt-batch reconciler is total and agrees with the recorded inventory it
        # is given: a recorded subset of the plan passes, a name outside it does not.
        fixes = [
            name
            for name in names
            if (prompt_workflow.prompt_stage_position(name) or (0, 0, 0))[1] == 1
        ]
        half = rng.randint(0, len(fixes))
        assert prompt_workflow._reconcile_recorded_fixes(fixes[:half], fixes) is None
        if fixes:
            assert (
                prompt_workflow._reconcile_recorded_fixes(
                    [*fixes, "task-review-fixes-9-9"], fixes
                )
                is not None
            )


#: Pinned seed and run count for the H1.3 continuation property (AGENTS.md "Tests": pytest
#: only, no ``hypothesis``, so a reproducible sample is the generator and there is no
#: shrinking).
CONTINUATION_PROPERTY_SEED = 7712
CONTINUATION_PROPERTY_RUNS = 32


def _recorded_run(reviews: int, *, gate: str) -> state.RunState:
    """A recorded run with ``reviews`` review rounds and one ``approve-task-prompt`` gate.

    The stage names are the loop's own: one review per round, and a fix batch plus its
    reconcile for every round but the last (the terminal review runs none). ``gate`` is
    ``"review-loop"``, a human mechanism, or ``"none"`` for no gate at all.
    """
    run = state.RunState(
        run_id="20260101T000000Z-prop-prompt",
        workflow="prompt",
        created_at=state.utcnow_iso(),
        repo_root=".",
    )
    run.record_stage(
        state.StageRecord(
            name="task-prompt",
            agent="task-author",
            model="test-model",
            status=state.SUCCEEDED,
        )
    )
    for index in range(1, reviews + 1):
        run.record_stage(
            state.StageRecord(
                name=f"task-review-{index}",
                agent="task-reviewer",
                model="test-model",
                status=state.SUCCEEDED,
            )
        )
        if index == reviews:
            continue
        run.record_stage(
            state.StageRecord(
                name=f"task-review-fixes-{index}-1",
                agent="task-fixer",
                model="test-model",
                status=state.SUCCEEDED,
            )
        )
        run.record_stage(
            state.StageRecord(
                name=f"task-review-reconcile-{index}",
                agent="task-fixer",
                model="test-model",
                status=state.SUCCEEDED,
            )
        )
    if gate != "none":
        run.record_gate(
            state.GateRecord(
                name=prompt_workflow.GATE,
                decision="denied",
                mechanism=gate,
                at=state.utcnow_iso(),
            )
        )
    return run


def test_continuation_extension_is_exactly_one_review_property() -> None:
    """Seeded property run (seed/runs pinned above): the continuation is one added review.

    For every sampled recorded inventory (1–5 review rounds, a resolved budget of 1–5, and
    a review-loop, human or absent gate), :func:`~aidw.workflows.prompt.effective_max_revisions`
    is the recorded review count + 1 — never the resolved value, never a larger default — and
    the loop's own expansion under that budget replays the recorded rounds' batches and ends
    on `task-review-{N+1}`: a **review**, never a fix or a reconcile (L4.1), with the last
    recorded round's fix batch and reconcile now planned. The extension is per-run, so the
    `--from` grammar under the *resolved* budget still refuses that added review. The two
    predicates are pinned pure (same answer twice, no state touched).
    """
    rng = random.Random(CONTINUATION_PROPERTY_SEED)

    for _ in range(CONTINUATION_PROPERTY_RUNS):
        reviews = rng.randint(1, 5)
        resolved = rng.randint(1, 5)
        gate = rng.choice(["review-loop", "human", "none"])
        run = _recorded_run(reviews, gate=gate)

        effective = prompt_workflow.effective_max_revisions(run)
        assert effective == reviews + 1
        assert prompt_workflow.effective_max_revisions(run) == effective
        assert prompt_workflow.review_loop_block(run) is (gate == "review-loop")

        batches = tuple(_synthesized_batch(rng) for _ in range(reviews))
        names = [
            stage.name
            for stage in stage_registry.expand(
                "prompt",
                phase="03",
                epic="E4",
                task="E4.1",
                rel=f"docs/task-prompts/{reviews}-prompt.md",
                max_revisions=effective,
                rounds=batches,
            )
        ]
        # The added review is last and is a review, never a fix or a reconcile (L4.1).
        assert names[-1] == f"task-review-{reviews + 1}"
        assert prompt_workflow.prompt_stage_position(names[-1])[:2] == (reviews + 2, 0)
        # The last recorded round's batch and reconcile are now reachable.
        assert f"task-review-reconcile-{reviews}" in names
        # The continuation's own plan is grammar-valid under the budget it runs under.
        assert all(prompt_workflow.is_from_stage(name, effective) for name in names)
        if reviews + 1 > resolved:
            assert (
                prompt_workflow.is_from_stage(
                    f"task-review-{reviews + 1}", resolved
                )
                is False
            )


def test_a_recorded_review_that_now_ends_the_run_refuses_to_resume(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H1.2 req 4: the rebuilt loop may not contradict the recorded stage inventory.

    The failure this closes is a toolkit upgrade between invocations: the recorded round-1
    review re-parses as an *exit* while the run recorded round-1's fix stages and a failed
    `task-review-fixes-1-2`, so a walk that trusts the new verdict would "finish" a run that
    still holds a failed stage. The resume refuses with exit 4 and writes nothing.
    """
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(
        prompt_workflow, "run_stage", _fail_stages(fake1, {"task-review-fixes-1-2"})
    )
    assert _run_prompt(tmp_path) == 1
    failed = _only_run(tmp_path)
    before = _state_text(tmp_path, failed.run_id)

    real_verdict = prompt_workflow.parse_verdict

    def drifted_verdict(text: str):
        # Only round 1's recorded review drifts: its fake body carries this marker.
        if "review round 1" in text:
            return prompt_workflow.APPROVE
        return real_verdict(text)

    monkeypatch.setattr(prompt_workflow, "parse_verdict", drifted_verdict)
    seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=2)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)

    code = _run_prompt(tmp_path, resume=True, approve_all=True)

    assert code == 4
    err = capsys.readouterr().err
    assert "cannot be rebuilt faithfully" in err
    assert "task-review-fixes-1-1" in err
    assert seen2 == []  # no stage ran, nothing was re-authored
    assert _state_text(tmp_path, failed.run_id) == before


# ---------------------------------------------------------------------------
# G1.2 — refuse before authoring when a cited spec section is unusable
#        (design §8.1, §17 Z19; roadmap-format.md §§8, 10)
# ---------------------------------------------------------------------------

#: A roadmap whose only citation no fixture heading can satisfy: the committed
#: ``design.md`` carries `## 8.1` and `## 9`, never `## 42.7`.
ROADMAP_MISSING_SPEC = """# Phase 3: Test Phase

## Epic E4: Defensive Combat

- [ ] **E4.1. Implement Total Defense** per Design 42.7..
  - Done when: applyTotalDefense returns the fixed effect.
"""

#: A citation that is present but says nothing: `## 9` is followed only by a deeper
#: subheading title before the next equal-level heading, so its own body holds no prose.
DESIGN_EMPTY_SECTION = """# Design

## 9. Test fixture

### 9.1 A subheading with no prose

## 10. Filled section

Real prose.
"""


def _spec_repo(tmp_path: Path, files: dict[str, str]) -> TargetRepo:
    """A ``TargetRepo`` over plain files (no git), for the pure cited-spec checker."""
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return TargetRepo(
        root=tmp_path, git_dir=tmp_path / ".git", common_dir=tmp_path / ".git"
    )


def _spec_entry(citations: list[str] | None = None) -> RoadmapTask:
    """The fixture task entry the pure checker is called with."""
    return RoadmapTask(
        phase="03",
        epic="E4",
        task="E4.1",
        title="Implement Total Defense",
        done=False,
        file="03 - Test Phase.md",
        line=4,
        citations=list(citations or []),
    )


def _spec_gaps(
    repo: TargetRepo,
    *,
    citations: list[str] | None = None,
    task_line: str = "",
    done_block: str = "",
) -> list[str]:
    return prompt_workflow._spec_feasibility_gaps(
        repo, _spec_entry(citations), task_line, done_block
    )


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` and its bytes: the purity check's before/after image."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_g12_missing_design_md_is_a_gap_and_a_present_section_is_not(
    tmp_path: Path,
) -> None:
    """One gap per problem: the cited file, then the mirror where the section exists."""
    repo = _spec_repo(tmp_path, {})

    assert _spec_gaps(repo, citations=["Design 8.1"]) == [
        "Design 8.1 → design.md: file not found"
    ]

    # The same citation against a present, non-empty section is no gap at all.
    (tmp_path / "design.md").write_text(
        "# Design\n\n## 8.1 Cited sections\n\nThe evidence channel.\n", encoding="utf-8"
    )
    assert _spec_gaps(repo, citations=["Design 8.1"]) == []


def test_g12_a_citation_no_heading_carries_is_a_gap(tmp_path: Path) -> None:
    """A `Design N` whose section is absent names the citation and the missing heading."""
    repo = _spec_repo(
        tmp_path, {"design.md": "# Design\n\n## 9. Test fixture\n\nProse.\n"}
    )

    assert _spec_gaps(repo, citations=["Design 8.1"]) == [
        "Design 8.1 → design.md: no heading numbered §8.1"
    ]


def test_g12_a_heading_with_no_prose_is_an_empty_section(tmp_path: Path) -> None:
    """A heading whose body is only blanks and deeper subheading titles is empty."""
    repo = _spec_repo(tmp_path, {"design.md": DESIGN_EMPTY_SECTION})

    assert _spec_gaps(repo, citations=["Design 9"]) == [
        "Design 9 → design.md: §9 is empty"
    ]
    # The rule is level-independent: the prose-free `### 9.1` is an empty section too,
    # while the next equal-level heading with prose is not.
    assert _spec_gaps(repo, citations=["Design 9.1"]) == [
        "Design 9.1 → design.md: §9.1 is empty"
    ]
    assert _spec_gaps(repo, citations=["Design 10"]) == []

    # A deeper subheading carrying prose is content inside its parent (the body is what
    # lies before the next equal-or-higher heading), so the parent is not empty.
    (tmp_path / "design.md").write_text(
        "# Design\n\n## 9. Test fixture\n\n### 9.1 Subsection\n\nProse.\n",
        encoding="utf-8",
    )
    assert _spec_gaps(repo, citations=["Design 9"]) == []


def test_g12_zero_padded_citations_match_canonically(tmp_path: Path) -> None:
    """`Design 09` matches `## 9` (and `Design 9` matches `## 09`), never exact strings."""
    repo = _spec_repo(
        tmp_path, {"design.md": "# Design\n\n## 9. Test fixture\n\nProse.\n"}
    )
    assert _spec_gaps(repo, citations=["Design 09"]) == []
    assert _spec_gaps(repo, citations=["Design 9"]) == []

    repo = _spec_repo(
        tmp_path, {"design.md": "# Design\n\n## 09. Test fixture\n\nProse.\n"}
    )
    assert _spec_gaps(repo, citations=["Design 9"]) == []
    assert _spec_gaps(repo, citations=["Design 09"]) == []


def test_g12_hash_prefix_without_heading_space_is_section_body(
    tmp_path: Path,
) -> None:
    """Only Markdown ATX headings delimit a section; ``#text`` remains body prose."""
    repo = _spec_repo(
        tmp_path,
        {"design.md": "# Design\n\n## 9. Test fixture\n\n#not a heading\n"},
    )

    assert _spec_gaps(repo, citations=["Design 9"]) == []


def test_g12_a_doc_token_that_cannot_be_located_uniquely_is_a_gap(
    tmp_path: Path,
) -> None:
    """`_locate_doc`'s ambiguity is a named gap, never a crash or a guess."""
    repo = _spec_repo(
        tmp_path,
        {
            "a/EXTRACTION.md": "# A\n\n## 3.1 Section\n\nProse.\n",
            "b/EXTRACTION.md": "# B\n\n## 3.1 Section\n\nProse.\n",
        },
    )
    assert _spec_gaps(repo, task_line="(EXTRACTION.md §3.1)") == [
        "EXTRACTION.md → could not locate the cited file uniquely"
    ]

    # A uniquely locatable bare ref asks only that the file locate: no section needed.
    (tmp_path / "b" / "EXTRACTION.md").unlink()
    assert _spec_gaps(repo, task_line="(EXTRACTION.md §3.1)") == []
    assert _spec_gaps(repo, task_line="(EXTRACTION.md)") == []


def test_g12_a_doc_section_no_heading_carries_is_a_gap(tmp_path: Path) -> None:
    """A `§N` after a located `<NAME>.md` must name a heading that exists."""
    repo = _spec_repo(
        tmp_path,
        {"docs/migration/EXTRACTION.md": "# Extraction\n\n## 4.9 Other\n\nProse.\n"},
    )

    assert _spec_gaps(repo, task_line="(EXTRACTION.md §3.9)") == [
        "EXTRACTION.md → docs/migration/EXTRACTION.md: no heading numbered §3.9"
    ]


def test_g12_a_decision_id_resolves_to_the_heading_that_names_it(
    tmp_path: Path,
) -> None:
    """`D16` → the section its heading names; unresolvable or empty targets are gaps."""
    repo = _spec_repo(
        tmp_path,
        {
            "docs/migration/EXTRACTION.md": (
                "# Extraction\n\n## 3.8 Task-prompt format (D16)\n\nProse.\n"
            )
        },
    )
    assert _spec_gaps(repo, task_line="**E4.1. Title** (EXTRACTION.md D16)") == []

    repo = _spec_repo(
        tmp_path,
        {"docs/migration/EXTRACTION.md": "# Extraction\n\n## 3.8 Other\n\nProse.\n"},
    )
    assert _spec_gaps(repo, task_line="(EXTRACTION.md D16)") == [
        "EXTRACTION.md → docs/migration/EXTRACTION.md: no numbered heading names `D16`"
    ]

    # Resolved, but its section documents nothing: the same empty-section rule applies.
    repo = _spec_repo(
        tmp_path,
        {
            "docs/migration/EXTRACTION.md": (
                "# Extraction\n\n## 3.8 Roadmap (D16)\n\n### 3.8.1 deeper\n"
            )
        },
    )
    assert _spec_gaps(repo, task_line="(EXTRACTION.md D16)") == [
        "EXTRACTION.md → docs/migration/EXTRACTION.md: §3.8 is empty"
    ]


def test_g12_a_located_but_unreadable_cited_file_fails_closed(
    tmp_path: Path, monkeypatch
) -> None:
    """An unreadable file cannot prove a section exists, so it is a gap, never a pass."""
    repo = _spec_repo(
        tmp_path, {"design.md": "# Design\n\n## 9. Test fixture\n\nProse.\n"}
    )
    real_read_text = Path.read_text

    def failing_read_text(self: Path, *args, **kwargs):
        if self.name == "design.md":
            raise OSError("injected unreadable file")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", failing_read_text)

    assert _spec_gaps(repo, citations=["Design 9"]) == [
        "Design 9 → design.md: could not read the file"
    ]


def test_g12_gaps_follow_citation_order_and_deduplicate_doc_tokens(
    tmp_path: Path,
) -> None:
    """Both channels are enumerated in citation order; a repeated token is reported once."""
    repo = _spec_repo(
        tmp_path,
        {
            "design.md": "# Design\n\n## 9. Test fixture\n\nProse.\n",
            "docs/migration/EXTRACTION.md": "# Extraction\n\n## 4.9 Other\n\nProse.\n",
        },
    )

    assert _spec_gaps(
        repo,
        citations=["Design 8.1", "Design 9"],
        task_line="(Design 8.1, Design 9, EXTRACTION.md §3.9, EXTRACTION.md §3.9)",
    ) == [
        "Design 8.1 → design.md: no heading numbered §8.1",
        "EXTRACTION.md → docs/migration/EXTRACTION.md: no heading numbered §3.9",
    ]


def test_g12_spec_gap_checker_is_pure(tmp_path: Path) -> None:
    """No input mutation, no write, and the same answer twice (the check is deterministic)."""
    repo = _spec_repo(
        tmp_path,
        {
            "design.md": "# Design\n\n## 9. Test fixture\n\nProse.\n",
            "docs/migration/EXTRACTION.md": "# Extraction\n\n## 4.9 Other\n\nProse.\n",
        },
    )
    entry = _spec_entry(["Design 8.1", "Design 9"])
    task_line = "(Design 8.1, EXTRACTION.md §3.9)"
    before_entry = dataclasses.replace(entry, citations=list(entry.citations))
    before_tree = _tree_snapshot(tmp_path)

    first = prompt_workflow._spec_feasibility_gaps(repo, entry, task_line, "")
    second = prompt_workflow._spec_feasibility_gaps(repo, entry, task_line, "")

    assert first == second
    assert first == [
        "Design 8.1 → design.md: no heading numbered §8.1",
        "EXTRACTION.md → docs/migration/EXTRACTION.md: no heading numbered §3.9",
    ]
    assert entry == before_entry
    assert _tree_snapshot(tmp_path) == before_tree


def test_g12_shared_citation_enumeration_preserves_rendering_and_deduplication(
    tmp_path: Path,
) -> None:
    """The checker and evidence bundle see the same refs without normalising their display."""
    repo = _spec_repo(
        tmp_path,
        {
            "design.md": "# Design\n\n## 9. Test fixture\n\nDesign prose.\n",
            "docs/migration/EXTRACTION.md": (
                "# Extraction\n\n### 3.8 Contract (D16)\n\nDoc prose.\n"
            ),
        },
    )
    entry = _spec_entry(["Design 09"])
    task_line = "(design.md, EXTRACTION.md §03.8, EXTRACTION.md §03.8)"

    rendered = prompt_workflow._render_cited_specs(repo, entry, task_line, "")

    # The bare design.md token is skipped and the repeated document token is rendered once;
    # cited numbers remain verbatim in the evidence bundle even though the checker compares
    # them canonically against the unpadded headings.
    assert rendered.splitlines() == [
        "- Design 09 → design.md §09",
        "- EXTRACTION.md → docs/migration/EXTRACTION.md §03.8",
    ]
    assert prompt_workflow._spec_feasibility_gaps(repo, entry, task_line, "") == []


def test_g12_missing_cited_section_refuses_exit_3_before_any_side_effect(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Exit 3 names the citation and its gap, and no fetch/run/branch/prompt ever happens."""
    _origin, clone = _origin_and_clone(tmp_path, roadmap=ROADMAP_MISSING_SPEC)
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

    assert code == 3
    err = capsys.readouterr().err
    assert "Design 42.7" in err
    assert "no heading numbered §42.7" in err
    # Cheap-failure order: the local check precedes the network fetch, branch and run state.
    assert fetch_calls == []
    assert state.list_runs(_runs_root(clone)) == []
    assert git.worktree_for_branch(clone, "03-E4.1") is None
    assert git.rev_parse(clone, "refs/heads/03-E4.1") is None
    assert not (clone / "docs" / "task-prompts" / "03-E4.1-prompt.md").exists()
    assert not _task_worktree(clone).exists()


def test_g12_empty_cited_section_refuses_exit_3(tmp_path: Path, monkeypatch, capsys) -> None:
    """A present-but-empty section is a gap, not a pass by citation count."""
    _make_control_repo(
        tmp_path,
        files={
            "docs/tasks/03 - Test Phase.md": ROADMAP_FIXTURE,
            "design.md": DESIGN_EMPTY_SECTION,
        },
    )
    monkeypatch.setattr(prompt_workflow, "run_stage", _explode_stage)

    code = _run_prompt(tmp_path)

    assert code == 3
    err = capsys.readouterr().err
    assert "Design 09" in err and "§09 is empty" in err
    assert state.list_runs(_runs_root(tmp_path)) == []


def test_g12_incomplete_predecessor_wins_over_spec_gap(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """L1.2 remains the first authority when both local preflights would refuse."""
    roadmap = """# Phase 3: Test Phase

## Epic E4: Defensive Combat

- [ ] **E4.0. Earlier task** per Design 41.1..
  - Done when: the earlier task is complete.
- [ ] **E4.1. Target task** per Design 42.7..
  - Done when: the target task is complete.
"""
    _origin, clone = _origin_and_clone(tmp_path, roadmap=roadmap)
    _break_origin(clone)
    fetch_calls: list[tuple] = []
    monkeypatch.setattr(git, "fetch", lambda *args, **kwargs: fetch_calls.append(args))

    code = prompt_workflow.run(
        phase="03", epic="E4", task="E4.1", **_roots(clone), label=RUN_LABEL
    )

    assert code == 4
    err = capsys.readouterr().err
    assert "earlier tasks in the same file are incomplete" in err
    assert "Design 42.7" not in err
    assert fetch_calls == []
    assert state.list_runs(_runs_root(clone)) == []


def test_g12_all_cited_sections_present_and_non_empty_proceeds_to_the_author(
    tmp_path: Path, monkeypatch
) -> None:
    """Both channels resolve against content, so the run reaches P1 — no Pi is invoked."""
    _evidence_repo(tmp_path, monkeypatch)  # cites Design 8.1 and EXTRACTION.md D16
    seen, fake = _fake_stages("## Verdict\n\n**Approve**\n", approve_review=1)
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
    assert seen[0][0] == "task-prompt"


def test_g12_dry_run_reports_the_gaps_and_still_plans(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """`--dry-run` notes every gap, plans normally and writes nothing (no early return)."""
    _patch_prompt_repo(tmp_path, monkeypatch, roadmap=ROADMAP_MISSING_SPEC)

    code = _run_prompt(tmp_path, dry_run=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "[dry-run] cited spec sections for `E4.1` have problems" in out
    assert "Design 42.7 → design.md: no heading numbered §42.7" in out
    # The normal plan still prints: the note is beside the plan, not a return at the split.
    assert "branch-setup (planned): worktree add -b 03-E4.1" in out
    assert "stage:  task-prompt" in out
    assert "dry-run complete; Pi not invoked" in out
    assert not _runs_root(tmp_path).exists()
    assert not _task_worktree(tmp_path).exists()
    assert not (tmp_path / "docs" / "task-prompts" / "03-E4.1-prompt.md").exists()


def test_g12_dry_run_reports_no_problems_when_citations_resolve(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The mirror note: a resolvable citation says so instead of naming a gap."""
    _patch_prompt_repo(tmp_path, monkeypatch)

    code = _run_prompt(tmp_path, dry_run=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "[dry-run] no cited-spec-section problems for `E4.1`." in out
    assert "Design 09" not in out


def test_g12_takeover_does_not_repeat_the_cited_spec_check(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The refusal is run-scoped: a `--resume` continues even though the spec is now gone."""
    _patch_prompt_repo(tmp_path, monkeypatch)
    _seen1, fake1 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=None)
    blocked = _blocked_run(tmp_path, monkeypatch, fake1)

    # Make the citation genuinely dangling *and keep the control tree clean*, so a
    # re-run check would refuse and only the takeover guard can let this resume through.
    _run_git(["rm", "-q", "design.md"], tmp_path)
    _run_git(["commit", "-qm", "drop the cited spec"], tmp_path)
    assert git.is_clean(tmp_path) is True
    target = _roots(tmp_path)["repo"]
    assert prompt_workflow._spec_feasibility_gaps(
        target, _spec_entry(["Design 09"]), "", ""
    ) == ["Design 09 → design.md: file not found"]

    _seen2, fake2 = _fake_stages(TASK_REVIEW_CHANGES, approve_review=4)
    monkeypatch.setattr(prompt_workflow, "run_stage", fake2)
    monkeypatch.setattr(prompt_workflow, "create_run", _explode_create)

    code = _run_prompt(tmp_path, resume=True, approve_all=True)

    assert code == 0
    err = capsys.readouterr().err
    assert "refusing: cannot author" not in err
    assert _only_run(tmp_path).run_id == blocked.run_id


#: Pinned seed and run count (AGENTS.md "Tests": pytest only, no ``hypothesis``, so a
#: reproducible sample is the generator and there is no shrinking).
SPEC_GAP_PROPERTY_SEED = 5187
SPEC_GAP_PROPERTY_RUNS = 24


def _gap_reason(gap: str) -> str:
    """A gap's reason with its cited section number normalised, for padding comparisons."""
    return re.sub(r"§[\d.]+", "§N", gap.split(" → ", 1)[1])


def _padded_number(rng: random.Random, number: str) -> str:
    """The same dotted number with random leading zeros on one of its parts."""
    parts = number.split(".")
    index = rng.randrange(len(parts))
    return ".".join(
        "0" * rng.randint(1, 2) + part if position == index else part
        for position, part in enumerate(parts)
    )


def test_g12_cited_spec_gap_property(tmp_path: Path) -> None:
    """Seeded property run (seed/runs pinned above): padding never changes a verdict.

    For each sampled fixture the check reports a gap exactly when a cited reference is
    absent, unlocatable or empty — never because a citation is zero-padded (`Design 01` and
    `Design 1` name one section), and never for a bare `<NAME>.md` whose file locates. The
    check is also pinned as pure and deterministic: repeating it returns an equal list and
    leaves the sampled tree byte-identical.
    """
    rng = random.Random(SPEC_GAP_PROPERTY_SEED)

    for case in range(SPEC_GAP_PROPERTY_RUNS):
        case_root = tmp_path / f"case-{case}"
        case_root.mkdir(parents=True)

        empty_design = rng.random() < 0.5
        design_body = (
            "### 1.99 A deeper heading with no prose\n"
            if empty_design
            else "Prose that makes the section non-empty.\n"
        )
        doc_present = rng.random() < 0.8
        empty_doc = rng.random() < 0.5
        doc_body = (
            "#### 3.4.1 A deeper heading with no prose\n"
            if empty_doc
            else "The roadmap contract.\n"
        )
        files = {"design.md": f"# Design\n\n## 1. Cited section\n\n{design_body}"}
        if doc_present:
            files["notes/SPEC.md"] = (
                f"# Spec\n\n### 3.4 Roadmap contract (D16)\n\n{doc_body}"
            )
        if doc_present and rng.random() < 0.5:
            # A second copy makes the token ambiguous even though it is present.
            files["other/SPEC.md"] = "# Spec\n\n### 3.4 Roadmap contract (D16)\n\nProse.\n"
        repo = _spec_repo(case_root, files)

        design_citation = f"Design {_padded_number(rng, '1')}"
        doc_mode = rng.choice(("section", "decision", "bare"))
        doc_section = _padded_number(rng, "3.4")
        doc_ref = {
            "section": f"SPEC.md §{doc_section}",
            "decision": "SPEC.md D16",
            "bare": "SPEC.md",
        }[doc_mode]
        ambiguous = "other/SPEC.md" in files

        expected: list[str] = []
        if empty_design:
            # The gap names the citation verbatim, so a zero-padded `Design 01` reads `§01`.
            expected.append(
                f"{design_citation} → design.md: §{design_citation.split()[-1]} is empty"
            )
        if not doc_present:
            expected.append("SPEC.md → could not locate the cited file uniquely")
        elif ambiguous:
            expected.append("SPEC.md → could not locate the cited file uniquely")
        elif doc_mode != "bare" and empty_doc:
            expected.append(f"SPEC.md → notes/SPEC.md: §{doc_section} is empty")

        entry = _spec_entry([design_citation])
        task_line = f"(Design {design_citation.split()[-1]}, {doc_ref})"
        before = _tree_snapshot(case_root)
        gaps = prompt_workflow._spec_feasibility_gaps(repo, entry, task_line, "")
        assert gaps == expected
        # The unpadded spelling of the same citations reaches the same verdicts; only the
        # citation label differs, which is what the gaps name (padding is never a cause).
        unpadded_doc_ref = {
            "section": "SPEC.md §3.4",
            "decision": "SPEC.md D16",
            "bare": "SPEC.md",
        }[doc_mode]
        unpadded = prompt_workflow._spec_feasibility_gaps(
            repo, _spec_entry(["Design 1"]), f"(Design 1, {unpadded_doc_ref})", ""
        )
        assert [_gap_reason(gap) for gap in unpadded] == [
            _gap_reason(gap) for gap in gaps
        ]
        # Pure and deterministic: same answer, no write, no input mutation.
        assert prompt_workflow._spec_feasibility_gaps(repo, entry, task_line, "") == gaps
        assert _tree_snapshot(case_root) == before
        assert entry.citations == [design_citation]
