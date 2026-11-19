"""Tests for the ``aidw implement`` workflow (design §8.2, Phase 4; E2.6).

E2.6 turns branch setup into a **locate**: ``run()`` derives the branch/worktree name
from ``repo.branch_pattern``, finds the worktree ``aidw prompt`` (E2.5) already created
with ``git.worktree_for_branch``, and re-resolves the target/agents so I1..I6 run in it.
A missing worktree is a preflight refusal (exit 4) that prints the §3.2 ``worktree add``
command; implement no longer creates one or copies the prompt. The harness therefore
builds the real bare+control layout (EXTRACTION.md §3.2), pre-creating the task worktree
with real git, and never fakes git output; only the Pi seam (``run_stage``) is mocked.
"""

from __future__ import annotations

import builtins
import dataclasses
import random
import subprocess
import threading
import time
from pathlib import Path

import pytest

from aidw import git, lock, roadmap, verification
from aidw.config import ERROR, Issue
from aidw.gates import GateOutcome
from aidw.paths import TargetRepo, ToolkitPaths, WorkspacePaths
from aidw.state import (
    BLOCKED,
    FAILED,
    SKIP_REASON_KEY,
    SKIPPED,
    SUCCEEDED,
    GateOutcome as EvidenceOutcome,
    StageRecord,
    append_gate_outcomes,
    create_run,
    run_dir,
    save,
)
from aidw.target_config import load_target_config, resolve_config
from aidw.workflows import implement as implement_workflow


def _git_run(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _make_bare_with_control(tmp_path: Path) -> tuple[Path, Path]:
    """Bare repo plus the ``main`` control worktree (the §3.2 bootstrap layout)."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _git_run(seed, "init", "-q", "-b", "main")
    (seed / "f.txt").write_text("x\n", encoding="utf-8")
    _git_run(seed, "add", ".")
    _git_run(seed, "commit", "-qm", "init")
    bare = tmp_path / "bare.git"
    _git_run(tmp_path, "clone", "--bare", "-q", str(seed), str(bare))
    control = tmp_path / "main"
    _git_run(bare, "worktree", "add", "-q", str(control), "main")
    return bare, control


#: The roadmap file every fixture layout carries (H3.1: I7 resolves its entry from the
#: configured ``paths.roadmap_dir``/``paths.roadmap_glob``, so a layout without one is a
#: refusal, not a run).
ROADMAP_REL = "docs/tasks/03 - Fixture.md"


def _roadmap_text(task: str = "E4.1", *, checked: bool = False) -> str:
    """A three-entry roadmap whose middle entry is ``task`` (hand-calculated fixture)."""
    box = "x" if checked else " "
    return (
        "# Phase 03: Fixture phase\n"
        "\n"
        "## Epic E4: Fixture epic\n"
        "\n"
        f"- [{box}] **{task}. A fixture task** <details>\n"
        "  Done when: the fixture task's checks pass.\n"
        "\n"
        "## Epic E9: Another epic\n"
        "\n"
        "- [ ] **E9.9. A neighbour task** <details>\n"
        "  Done when: a neighbour changes for another task.\n"
    )


def _write_roadmap(
    root: Path, task: str = "E4.1", *, checked: bool = False
) -> Path:
    path = root / ROADMAP_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_roadmap_text(task, checked=checked), encoding="utf-8")
    return path


def _task_from_prompt_name(name: str) -> str:
    parsed = implement_workflow.parse_task_id(Path(name))
    assert parsed is not None
    return parsed[1]


def _write_prompt(control: Path, name: str = "03-E4.1-prompt.md") -> Path:
    """Write the task prompt into the control worktree **uncommitted** (the real layout)."""
    prompt = control / "docs" / "task-prompts" / name
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("# Implement E4.1\n", encoding="utf-8")
    _write_roadmap(control, _task_from_prompt_name(name))
    return prompt


def _layout(tmp_path: Path) -> tuple[Path, Path]:
    """Control root plus the prompt uncommitted there (no task worktree. E2.6)."""
    _bare, control = _make_bare_with_control(tmp_path)
    return control, _write_prompt(control)


def _make_task_worktree(
    control: Path,
    branch: str = "03-E4.1",
    name: str = "03-E4.1-prompt.md",
    base_branch: str = "main",
) -> tuple[Path, Path]:
    """Pre-create the task worktree and commit the prompt inside it (the E2.5 layout).

    This is what ``aidw prompt`` leaves behind: the branch's worktree is created, the
    task prompt is committed there, and the control root stays on the base branch.
    """
    worktree = git.add_worktree(control, branch, base_branch=base_branch)
    assert worktree is not None
    prompt = worktree / "docs" / "task-prompts" / name
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("# Implement E4.1\n", encoding="utf-8")
    # The roadmap is committed with the prompt: a real ``aidw prompt`` run commits the
    # authored prompt in the task worktree, and I7 ticks the entry in that tree.
    _write_roadmap(worktree, _task_from_prompt_name(name))
    _git_run(worktree, "add", ".")
    _git_run(worktree, "commit", "-qm", "task prompt")
    return worktree, prompt


def _located_layout(
    tmp_path: Path,
    branch: str = "03-E4.1",
    name: str = "03-E4.1-prompt.md",
    base_branch: str = "main",
) -> tuple[Path, Path, Path]:
    """Control root plus a ready task worktree/prompt (the E2.5/E2.6 happy path)."""
    _bare, control = _make_bare_with_control(tmp_path)
    worktree, prompt = _make_task_worktree(control, branch, name, base_branch)
    return control, worktree, prompt


def _roots(control: Path) -> dict:
    target = TargetRepo.resolve(control)
    return {
        "repo": target,
        "aidt": ToolkitPaths.resolve(),
        "workspace": WorkspacePaths.resolve(
            target, state_dir_override=control.parent / "aidt-state"
        ),
    }


def _runs_root(control: Path) -> Path:
    """Where E1.4 writes run state: the per-repo state root, never the toolkit."""
    return _roots(control)["workspace"].state_root / "runs"


def _stage_out_text(name: str) -> str:
    """The final message a fake stage leaves in its ``out.txt``.

    Q1.1 re-baseline: I2's message now carries the verdict block ``implement`` parses, so the
    baseline fake emits a *passing* one. ``Test verdict: Pass`` is hand-written here (not
    imported from the workflow) so a changed token fails this fake loudly; ``pr`` keeps the
    URL ``_record_pr`` parses and every other stage keeps the ``ok`` transcript.
    """
    if name == "pr":
        return "https://github.com/o/r/pull/42\n"
    if name == implement_workflow.TEST_STAGE_NAME:
        return "Test verdict: Pass\n"
    return "ok\n"


class _Recorder:
    """Fake ``run_stage`` that records stages and returns canned statuses."""

    def __init__(self, fail: set[str] | None = None) -> None:
        self.names: list[str] = []
        self.specs = []
        self.repo_roots: list[Path] = []
        self.fail = fail or set()

    @staticmethod
    def _flip_roadmap(spec) -> None:
        """Do what the I7 agent is told to: flip ``$2``'s checkbox in ``$1`` (H3.1)."""
        path = Path(spec.variables[0])
        checkbox_id = spec.variables[1]
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for index, line in enumerate(lines):
            match = roadmap.TASK_RE.match(line)
            if match and match.group(2) == checkbox_id:
                lines[index] = line[: match.start(1)] + "x" + line[match.end(1) :]
                break
        path.write_text("".join(lines), encoding="utf-8")

    def __call__(self, spec, **kwargs):
        self.names.append(spec.name)
        self.specs.append(spec)
        self.repo_roots.append(kwargs["repo_root"])
        if spec.name == "update-roadmap" and not kwargs.get("dry_run"):
            # The workflow re-reads the file after the stage; a fake stage that did not
            # edit it would (correctly) fail the postcondition.
            self._flip_roadmap(spec)
        directory = run_dir(kwargs["runs_root"], kwargs["state"].run_id)
        stages = directory / "stages"
        stages.mkdir(parents=True, exist_ok=True)
        out = stages / f"{spec.name}.out.txt"
        out.write_text(_stage_out_text(spec.name), encoding="utf-8")
        status = FAILED if spec.name in self.fail else SUCCEEDED
        record = StageRecord(
            name=spec.name,
            agent=spec.agent_id,
            model="test/model",
            status=status,
            artifacts={"out": str(out)},
            error="boom" if status == FAILED else None,
        )
        kwargs["state"].record_stage(record)
        return record


class _FakeAgent:
    """The two fields a stage's agent resolution reads.

    ``run_stage`` is faked in this module, but H3.2's withheld tick resolves the agent it
    *would* have run through the same rule (``aidw.runner.stage_agent``), and
    ``StageRecord.model`` is required — so the faked ``load_all`` has to hand back
    something with ``id`` and ``qualified_model`` rather than a bare ``object()``.
    """

    def __init__(self, agent_id: str, model: str = "test/model") -> None:
        self.id = agent_id
        self.qualified_model = model


#: Every agent id the registry's implement chain names, so a real-run stage (and the
#: skipped tick) always resolves.
_AGENTS: dict[str, _FakeAgent] = {
    agent_id: _FakeAgent(agent_id)
    for agent_id in ("implementer", "tester", "recorder", "pr-publisher")
}


def _patch(monkeypatch) -> None:
    monkeypatch.setattr(
        implement_workflow, "load_all", lambda aidt, repo, **_kwargs: (dict(_AGENTS), [])
    )


def _write_config(control: Path, body: str) -> None:
    """Write the target config the preflight reads (``<target>/aidw/config.yaml``, §3.4)."""
    config = control / "aidw" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(body, encoding="utf-8")


#: The four resolved document write-targets, hand-written from H3.2 req 3's prompt-fixed
#: scope rather than read from the workflow: the fake evidence has to carry the *canonical*
#: scope, so a workflow that resolved a different one matches nothing and the test fails
#: instead of agreeing with itself.
EVIDENCE_IGNORE = (
    "docs/implementation-results",
    "docs/architecture",
    "docs/tasks",
    "docs/task-prompts",
)

#: Every gate the E6.1 shape recorded: four green, one red `suite`.
EVIDENCE_KEYS = ("build", "doctor", "agents", "prompts", "suite")


def _evidence_tree(
    worktree: Path,
    *,
    exclude: tuple[Path, ...] = (),
    ignore: tuple[str, ...] = EVIDENCE_IGNORE,
) -> str:
    """The tree the gate CLI would have recorded for this fixture (H3.2).

    Computed with ``aidw.verification.tree_identity``'s **default** base, which is what
    every ``aidw gate run`` resolves when the prompts pass no ``--base``, and with the
    hand-written :data:`EVIDENCE_IGNORE` scope — never the workflow's own helper, so a
    workflow that resolved a different base or scope matches nothing and the test fails.
    ``ignore`` widens for a fixture that relocated one of the four document dirs (the
    prompts' scope is the *resolved* paths, so a custom ``roadmap_dir`` is declared too).
    """
    tree = verification.tree_identity(worktree, exclude=exclude, ignore=ignore)
    assert tree is not None, "the fixture's change set has no identity"
    return tree


def _record_evidence(
    state,
    directory: Path,
    *,
    tree: str,
    keys: tuple[str, ...] = EVIDENCE_KEYS,
    failing: set[str] | frozenset[str] = frozenset(),
    stage: str = "record-implementation-results",
) -> None:
    """Append a hand-calculated outcome set through the CLI's writer, then merge it.

    ``aidw gate run`` appends to ``state.json`` from a subprocess (H0.1); the workflow's own
    ``save`` is what folds those rows into the in-memory state a later stage reads. Both
    halves are exercised here through the public writers rather than by poking the list, so
    a fake cannot pass through a path a real run never takes.
    """
    append_gate_outcomes(
        directory,
        [
            EvidenceOutcome(
                key=key,
                command=["uv", "run", "--frozen", "pytest"],
                tree=tree,
                status=FAILED if key in failing else "passed",
                stage=stage,
                at="2026-11-10T00:00:00Z",
                exit_code=1 if key in failing else 0,
                summary="1 failed" if key in failing else "1 passed",
            )
            for key in keys
        ],
    )
    save(directory, state)


class _GateEvidenceStages(_Recorder):
    """A fake ``run_stage`` that leaves the run's gate evidence behind, as real agents do.

    H3.2's condition is a read of the run's recorded ``gate_outcomes``; in a live run they
    arrive through ``aidw gate run`` subprocesses appending to ``state.json`` (H0.1). This
    fake appends through the same public writer at the ``record-implementation-results``
    stage — the sync point where the run's gates have been recorded — and computes the tree
    the way the gate CLI does.
    """

    def __init__(
        self,
        *,
        failing: set[str] | None = None,
        keys: tuple[str, ...] = EVIDENCE_KEYS,
        tree: str | None = None,
    ) -> None:
        super().__init__()
        self.failing = failing or set()
        self.keys = keys
        self.tree = tree

    def __call__(self, spec, **kwargs):
        record = super().__call__(spec, **kwargs)
        if spec.name != "record-implementation-results":
            return record
        state = kwargs["state"]
        tree = self.tree or _evidence_tree(
            Path(kwargs["repo_root"]),
            exclude=(Path(kwargs["runs_root"]).parent,),
        )
        _record_evidence(
            state,
            run_dir(kwargs["runs_root"], state.run_id),
            tree=tree,
            keys=self.keys,
            failing=self.failing,
        )
        return record


class _VerdictStages(_GateEvidenceStages):
    """A fake chain whose I2 final message is whatever the scenario wrote (Q1.1).

    ``test_out`` is the exact text I2 leaves in its ``out.txt`` (the tester's final message,
    which is where the verdict lives — the stage itself exits 0 whether it passes or fails).
    ``None`` removes the file *after* the stage recorded the artifact: the resumed/lost-out
    case the gate must fail closed on. Gate evidence and the roadmap flip are unchanged.
    """

    def __init__(self, test_out: str | None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.test_out = test_out

    def __call__(self, spec, **kwargs):
        record = super().__call__(spec, **kwargs)
        if spec.name == implement_workflow.TEST_STAGE_NAME:
            out = Path(record.artifacts["out"])
            if self.test_out is None:
                out.unlink()
            else:
                out.write_text(self.test_out, encoding="utf-8")
        return record


#: The registry's implement order (I1..I9), the serial schedule. X1.1's I8
#: (``summarize-implementation-results``) runs immediately after I5's record stage, and
#: X1.2's I9 (``write-integration-test-guide``) immediately after the summary.
DEFAULT_ORDER = [
    "impliment-task",
    "test",
    "update-traceability",
    "update-architecture",
    "record-implementation-results",
    "summarize-implementation-results",
    "write-integration-test-guide",
    "update-roadmap",
    "pr",
]


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


def test_parse_task_id_variants() -> None:
    assert implement_workflow.parse_task_id(Path("03-E4.1-prompt.md")) == (
        "03",
        "E4.1",
        "03-E4.1",
    )
    assert implement_workflow.parse_task_id(Path("03-E4.1.md")) == ("03", "E4.1", "03-E4.1")
    assert implement_workflow.parse_task_id(Path("02.5-B-prompt.md")) == (
        "02.5",
        "B",
        "02.5-B",
    )
    assert implement_workflow.parse_task_id(Path("nonsense.md")) is None


def test_derive_branch_name_default_reproduces_the_task_id() -> None:
    pattern = "{phase}-{task}"
    assert implement_workflow.derive_branch_name(pattern, phase="00", task="E2.4") == "00-E2.4"
    # The dotted-phase form must survive byte-for-byte.
    assert implement_workflow.derive_branch_name(pattern, phase="02.5", task="B") == "02.5-B"


def test_derive_branch_name_rejects_malformed_patterns() -> None:
    # References only one of phase/task: a constant/partial name collides across tasks.
    assert implement_workflow.derive_branch_name("{phase}", phase="00", task="E2.4") is None
    assert implement_workflow.derive_branch_name("static", phase="00", task="E2.4") is None
    # Unknown placeholder: str.format raises KeyError.
    assert (
        implement_workflow.derive_branch_name(
            "{phase}-{task}-{extra}", phase="00", task="E2.4"
        )
        is None
    )
    # Unbalanced braces raise ValueError.
    assert implement_workflow.derive_branch_name("{phase}-{task", phase="00", task="E2.4") is None


def test_build_plan_order_and_agents() -> None:
    plan = implement_workflow.build_plan(
        aidt=Path("/aidt"), prompt_rel="docs/task-prompts/03-E4.1-prompt.md",
        branch="03-E4.1", task_id="03-E4.1",
        roadmap_file="/repo/docs/tasks/03 - Extraction.md", checkbox_id="E4.1",
    )
    assert [(p.id, p.name) for p in plan] == [
        ("I1", "impliment-task"),
        ("I2", "test"),
        ("I3", "update-traceability"),
        ("I4", "update-architecture"),
        ("I5", "record-implementation-results"),
        ("I8", "summarize-implementation-results"),
        ("I9", "write-integration-test-guide"),
        ("I7", "update-roadmap"),
        ("I6", "pr"),
    ]
    assert [p.agent for p in plan] == [
        "implementer",
        "tester",
        "implementer",
        "implementer",
        "recorder",
        "recorder",
        "recorder",
        "recorder",
        "pr-publisher",
    ]
    # Since E4.3 `build_plan` is the registry's expansion, so `variables` is the registry's
    # frozen tuple (`aidw.stage_registry.PlannedStage`), not a mutable list.
    assert plan[0].variables == ("docs/task-prompts/03-E4.1-prompt.md",)
    assert plan[1].variables == () and plan[1].extra
    assert plan[2].variables == ("03-E4.1",)
    assert plan[3].variables == ("03-E4.1", "main")
    assert plan[5].variables == ("03-E4.1",)
    assert plan[6].variables == ("03-E4.1",)
    assert plan[7].variables == ("/repo/docs/tasks/03 - Extraction.md", "E4.1")
    assert plan[8].variables == ("03-E4.1",)


def test_build_plan_uses_the_configured_base_branch() -> None:
    plan = implement_workflow.build_plan(
        aidt=Path("/aidt"), prompt_rel="docs/task-prompts/03-E4.1-prompt.md",
        branch="03-E4.1", task_id="03-E4.1", base_branch="develop",
        roadmap_file="/repo/docs/tasks/03 - Extraction.md", checkbox_id="E4.1",
    )
    assert plan[3].variables == ("03-E4.1", "develop")


# --------------------------------------------------------------------------- #
# Branch-name derivation at the run seam
# --------------------------------------------------------------------------- #


def test_non_default_branch_pattern_names_branch_worktree_and_state(
    tmp_path: Path, monkeypatch
) -> None:
    control, worktree, prompt = _located_layout(
        tmp_path, branch="E4.1-03", name="03-E4.1-prompt.md"
    )
    roots = _roots(control)
    roots["repo"] = dataclasses.replace(
        roots["repo"], branch_pattern="{task}-{phase}"
    )
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(task_prompt_path=prompt, **roots, approve_all=True)

    assert code == 0
    assert worktree == (tmp_path / "E4.1-03").resolve()
    assert recorder.repo_roots[0] == worktree
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert state.git.get("branch") == "E4.1-03"


@pytest.mark.parametrize("pattern", ["static", "{phase}", "{phase}-{task}-{extra}"])
def test_malformed_branch_pattern_is_usage_error_before_worktree(
    tmp_path: Path, monkeypatch, pattern: str
) -> None:
    control, prompt = _layout(tmp_path)
    roots = _roots(control)
    roots["repo"] = dataclasses.replace(roots["repo"], branch_pattern=pattern)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(task_prompt_path=prompt, **roots)

    # A pattern missing a placeholder, or naming an unknown one, is refused before
    # branch-setup: no worktree, no stage, no run state.
    assert code == 2
    assert recorder.names == []
    assert not (tmp_path / "03-E4.1").exists()
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []


# --------------------------------------------------------------------------- #
# Dry run
# --------------------------------------------------------------------------- #


def test_dry_run_plans_locate_and_all_eight_stages(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    control, prompt = _layout(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 0
    assert recorder.names == DEFAULT_ORDER
    # H3.1 req 8: the tick stage is planned in its run position with both variables
    # rendered from the configured roadmap — the entry's own file and its task id, not
    # the branch form (``03-E4.1``).
    tick = next(spec for spec in recorder.specs if spec.name == "update-roadmap")
    assert tick.variables == [
        str((control / ROADMAP_REL).resolve()),
        "E4.1",
    ]
    # H3.2: the condition is carried onto the planned spec — `StageSpec.when` is what a
    # workflow reads to decide at run time — and the dry run neither fails nor skips on
    # the evidence, because it returns before the condition is ever evaluated.
    assert tick.when == "evidence-green"
    # S1.1: I3's carried token rides the same field, and the dry run evaluates no change
    # set — the stage is planned, with its empty default path set, and never withheld.
    traceability = next(
        spec for spec in recorder.specs if spec.name == "update-traceability"
    )
    assert traceability.when == "paths-changed"
    assert traceability.when_paths == ()
    assert all(
        spec.when == ""
        for spec in recorder.specs
        if spec.name not in ("update-roadmap", "update-traceability")
    )
    out = capsys.readouterr().out
    command = (
        f"git -C {tmp_path / 'main'} worktree add -b 03-E4.1 "
        f"{tmp_path / '03-E4.1'} main"
    )
    # The dry run plans the locate, not a ``worktree add`` it no longer performs, and
    # prints the corrective command copy-pasteable (E2.6 req 4/req 6).
    assert f"worktree (planned): {tmp_path / '03-E4.1'}" in out
    assert f"branch-setup (planned): {command}" in out
    # A dry run performs no worktree writes.
    assert not (tmp_path / "03-E4.1").exists()
    # The prompt argument is re-based onto the planned worktree (req 2/req 6).
    assert recorder.specs[0].variables == ["docs/task-prompts/03-E4.1-prompt.md"]
    # The plan lines print the retained stage id, which since E4.3 rides on
    # ``StageSpec.id`` (``id`` and ``name`` are different fields): a lost carrier would
    # silently drop the ``I1 …`` prefix and change this output.
    for line in (
        "I1 impliment-task [succeeded] (planned)",
        "I2 test [succeeded] (planned)",
        "I3 update-traceability [succeeded] (planned)",
        "I4 update-architecture [succeeded] (planned)",
        "I5 record-implementation-results [succeeded] (planned)",
        "I8 summarize-implementation-results [succeeded] (planned)",
        "I9 write-integration-test-guide [succeeded] (planned)",
        "I7 update-roadmap [succeeded] (planned)",
        "I6 pr [succeeded] (planned)",
    ):
        assert line in out


def test_dry_run_renders_a_repo_declared_prompt_override(
    tmp_path: Path, monkeypatch
) -> None:
    """E4.3: a config's D14 ``prompt:`` changes the prompt the planned stage renders."""
    control, prompt = _layout(tmp_path)
    override = control / "aidw" / "prompts" / "update-traceability.md"
    override.parent.mkdir(parents=True)
    override.write_text("# repo traceability rules\n", encoding="utf-8")
    # A declared list replaces the registry's wholesale (§3.4), so it must carry every
    # core stage (E4.5a's removal rule) — the prompt: override rides on I3's entry.
    (control / "aidw" / "config.yaml").write_text(
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    stages:\n"
        "      - id: I1\n"
        "      - id: I2\n"
        "      - id: I3\n"
        "        prompt: aidw/prompts/update-traceability.md\n"
        "      - id: I4\n"
        "      - id: I5\n"
        "      - id: I8\n"
        "      - id: I9\n"
        "      - id: I7\n"
        "      - id: I6\n",
        encoding="utf-8",
    )
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 0
    # I3 resolves to the repo's declared file; every other stage keeps the toolkit default.
    assert recorder.specs[2].prompt == override.resolve()
    assert recorder.specs[2].explicit_prompt == "aidw/prompts/update-traceability.md"
    assert recorder.specs[1].prompt == (
        ToolkitPaths.resolve().prompts_dir / "test.md"
    )
    assert recorder.specs[1].explicit_prompt is None


def test_dry_run_writes_runs_under_the_state_root(tmp_path: Path, monkeypatch) -> None:
    """E1.4: a run lives under the state root, never under ``repo/aidt/runs``."""
    control, prompt = _layout(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(implement_workflow, "run_stage", _Recorder())

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 0
    runs_root = _runs_root(control)
    run_dirs = list(runs_root.iterdir())
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "state.json").is_file()
    assert not (control / "aidt" / "runs").exists()


# --------------------------------------------------------------------------- #
# Branch setup creates the worktree before I1
# --------------------------------------------------------------------------- #


def test_locates_existing_worktree_and_runs_every_stage_in_it(
    tmp_path: Path, monkeypatch
) -> None:
    control, worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert recorder.names[0] == "impliment-task"
    # Every stage ran in the located worktree, not the control root.
    assert recorder.repo_roots == [worktree] * len(recorder.repo_roots)
    # No second worktree was created: one branch maps to exactly one worktree.
    branches = [entry.branch for entry in git.worktrees(control) if entry.branch]
    assert branches.count("03-E4.1") == 1


def test_repo_override_from_unrelated_cwd_locates_the_worktree(
    tmp_path: Path, monkeypatch
) -> None:
    """``--repo``/``explicit=`` selects the control root; the lookup follows it."""
    control, worktree, prompt = _located_layout(tmp_path)
    unrelated = tmp_path / "elsewhere"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    target = TargetRepo.resolve(explicit=control)
    workspace = WorkspacePaths.resolve(
        target, state_dir_override=control.parent / "aidt-state"
    )
    code = implement_workflow.run(
        task_prompt_path=prompt,
        repo=target,
        aidt=ToolkitPaths.resolve(),
        workspace=workspace,
        approve_all=True,
    )

    assert code == 0
    assert recorder.repo_roots[0] == worktree


def test_base_branch_flows_through_the_whole_run(tmp_path: Path, monkeypatch) -> None:
    bare, control = _make_bare_with_control(tmp_path)
    # develop exists and is one commit ahead of main.
    _git_run(bare, "branch", "develop", "main")
    develop_wt = tmp_path / "develop"
    _git_run(bare, "worktree", "add", "-q", str(develop_wt), "develop")
    (develop_wt / "g.txt").write_text("g\n", encoding="utf-8")
    _git_run(develop_wt, "add", ".")
    _git_run(develop_wt, "commit", "-qm", "develop work")
    _git_run(bare, "worktree", "remove", str(develop_wt))
    worktree, prompt = _make_task_worktree(control, base_branch="develop")

    roots = _roots(control)
    roots["repo"] = dataclasses.replace(roots["repo"], base_branch="develop")
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)
    summaries: list[str] = []

    def capture_gate(_name: str, summary: str, **_kwargs) -> GateOutcome:
        summaries.append(summary)
        return GateOutcome(implement_workflow.GATE, True, "test")

    monkeypatch.setattr(implement_workflow, "decide", capture_gate)

    code = implement_workflow.run(task_prompt_path=prompt, **roots, approve_all=True)

    assert code == 0
    assert len(summaries) == 1
    prompt_rel = "docs/task-prompts/03-E4.1-prompt.md"
    # develop contains g.txt while main does not; the gate summary must use the
    # configured base just as the PR record does, so it must not report g.txt.
    assert "g.txt" not in summaries[0]
    assert worktree == (tmp_path / "03-E4.1").resolve()
    # The worktree branches from develop: the committed prompt and I7's uncommitted tick
    # are the only differences (the tick stays uncommitted; I6 commits it in a real run).
    assert git.changed_files(worktree, "develop") == [prompt_rel, ROADMAP_REL]
    # state.pr.changed_files and I4's base_ref both measure against develop.
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert state.pr.get("changed_files") == [prompt_rel, ROADMAP_REL]
    arch = next(s for s in recorder.specs if s.name == "update-architecture")
    assert arch.variables == ["03-E4.1", "develop"]


# --------------------------------------------------------------------------- #
# Preflight (retained still-running guard; fail-closed branch setup)
# --------------------------------------------------------------------------- #


def test_agents_are_reloaded_against_the_located_worktree(
    tmp_path: Path, monkeypatch
) -> None:
    control, worktree, prompt = _located_layout(tmp_path)
    load_roots: list[Path] = []

    def record_load(_aidt: Path, repo_root: Path, **_kwargs):
        load_roots.append(repo_root)
        return dict(_AGENTS), []

    monkeypatch.setattr(implement_workflow, "load_all", record_load)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    # Config validates against the control root first, then agents reload for the worktree.
    assert load_roots == [control.resolve(), worktree]
    assert recorder.repo_roots[0] == worktree


def test_missing_prompt_is_usage_error(tmp_path: Path, monkeypatch) -> None:
    control, _prompt = _layout(tmp_path)
    _patch(monkeypatch)
    code = implement_workflow.run(
        task_prompt_path=control / "docs" / "task-prompts" / "nope.md",
        **_roots(control),
    )
    assert code == 2


def test_relative_prompt_resolves_inside_the_worktree(
    tmp_path: Path, monkeypatch
) -> None:
    """A relative argument is a repo-relative subpath of the worktree, not the control root."""
    control, worktree, _prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=Path("docs/task-prompts/03-E4.1-prompt.md"),
        **_roots(control),
        approve_all=True,
    )

    assert code == 0
    assert recorder.specs[0].variables == ["docs/task-prompts/03-E4.1-prompt.md"]
    assert recorder.repo_roots[0] == worktree


def test_config_error_wins_over_missing_worktree(tmp_path: Path, monkeypatch) -> None:
    """Config validation stays pre-locate, so bad config is exit 2, not exit 4."""
    control, _prompt = _layout(tmp_path)  # no task worktree
    issue = Issue(ERROR, "config", "bad config")
    monkeypatch.setattr(implement_workflow, "load_all", lambda aidt, repo, **_kwargs: ({}, [issue]))
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=control / "docs" / "task-prompts" / "03-E4.1-prompt.md",
        **_roots(control),
    )

    assert code == 2
    assert recorder.names == []


def test_reloaded_worktree_config_error_is_usage_error(
    tmp_path: Path, monkeypatch
) -> None:
    control, worktree, prompt = _located_layout(tmp_path)
    calls: list[Path] = []

    def load_for_root(_aidt: Path, repo_root: Path, **_kwargs):
        calls.append(repo_root)
        if repo_root == worktree:
            return {}, [Issue(ERROR, "config", "bad config in task worktree")]
        return {}, []

    monkeypatch.setattr(implement_workflow, "load_all", load_for_root)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 2
    assert calls == [control.resolve(), worktree]
    assert recorder.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []


def test_relative_prompt_cannot_escape_the_task_worktree(
    tmp_path: Path, monkeypatch
) -> None:
    control, _worktree, _prompt = _located_layout(tmp_path)
    escaped = tmp_path / "escaped" / "docs" / "task-prompts" / "03-E4.1-prompt.md"
    escaped.parent.mkdir(parents=True)
    escaped.write_text("outside the worktree\n", encoding="utf-8")
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=Path("../escaped/docs/task-prompts/03-E4.1-prompt.md"),
        **_roots(control),
        approve_all=True,
    )

    assert code == 2
    assert recorder.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []


def test_located_worktree_missing_prompt_is_usage_error(
    tmp_path: Path, monkeypatch
) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    worktree = git.add_worktree(control, "03-E4.1")
    assert worktree is not None  # located, but the prompt was never committed there
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=Path("docs/task-prompts/03-E4.1-prompt.md"),
        **_roots(control),
    )

    assert code == 2
    assert recorder.names == []


def test_located_worktree_missing_prompt_is_usage_error_in_dry_run(
    tmp_path: Path, monkeypatch
) -> None:
    _bare, control = _make_bare_with_control(tmp_path)
    assert git.add_worktree(control, "03-E4.1") is not None
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=Path("docs/task-prompts/03-E4.1-prompt.md"),
        **_roots(control),
        dry_run=True,
    )

    # A located worktree still refuses in dry-run; only the absent-worktree case suspends
    # the existence check.
    assert code == 2
    assert recorder.names == []


def test_running_run_is_refused_without_resume(tmp_path: Path, monkeypatch) -> None:
    control, prompt = _layout(tmp_path)
    _patch(monkeypatch)
    runs_root = _runs_root(control)
    create_run(runs_root, control, "implement", label="03-E4.1", branch="03-E4.1")
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(task_prompt_path=prompt, **_roots(control))

    assert code == 4
    assert recorder.names == []
    assert not (tmp_path / "03-E4.1").exists()
    # No second run state was written.
    assert len(list(_runs_root(control).iterdir())) == 1


def test_missing_worktree_is_refused_with_the_command(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    control, prompt = _layout(tmp_path)  # no task worktree
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 4
    assert recorder.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []
    command = (
        f"git -C {tmp_path / 'main'} worktree add -b 03-E4.1 "
        f"{tmp_path / '03-E4.1'} main"
    )
    assert command in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Q1.1: the I2 verdict parser (`_parse_test_verdict`, design §8.2 / §17 Z10)
# --------------------------------------------------------------------------- #


#: A whole final message whose only declaration is a bare `Pass` line.
_PASS_REPORT = (
    "Criterion: AC-1\n"
    "Result: Pass\n"
    "Scope: in-scope\n"
    "Evidence: uv run --frozen pytest tests/test_x.py\n"
    "Gap: None\n"
    "\n"
    "Test verdict: Pass\n"
)

#: A whole final message declaring an in-scope failure for two criteria.
_FAIL_REPORT = (
    "Criterion: AC-1\n"
    "Result: Fail\n"
    "Scope: in-scope\n"
    "Evidence: uv run --frozen pytest tests/test_x.py\n"
    "Gap: None\n"
    "\n"
    "Criterion: AC-3\n"
    "Result: Fail\n"
    "Scope: in-scope\n"
    "Evidence: uv run --frozen pytest tests/test_y.py\n"
    "Gap: None\n"
    "\n"
    "Test verdict: Fail\n"
    "Failing in-scope criteria: AC-1, AC-3\n"
)


def test_parse_test_verdict_reads_a_bare_pass_declaration() -> None:
    """Hand-calculated spec example: a bare `Pass` line proceeds, with no criteria."""
    assert implement_workflow._parse_test_verdict(_PASS_REPORT) == ("Pass", [])


def test_parse_test_verdict_reads_the_failing_criteria_list() -> None:
    """Hand-calculated spec example: `Fail` plus the following criteria line."""
    assert implement_workflow._parse_test_verdict(_FAIL_REPORT) == (
        "Fail",
        ["AC-1", "AC-3"],
    )


def test_parse_test_verdict_fail_without_a_criteria_line_is_still_fail() -> None:
    """A missing criteria line is best-effort naming, never "ambiguous" (req 5)."""
    assert implement_workflow._parse_test_verdict("Test verdict: Fail\n") == ("Fail", [])


def test_parse_test_verdict_ignores_a_declaration_inside_a_fence() -> None:
    """M1: the prompt's own fenced template is never read as the tester's verdict."""
    report = (
        "The template asks for this shape:\n"
        "\n"
        "```text\n"
        "Test verdict: Fail\n"
        "Failing in-scope criteria: AC-1\n"
        "```\n"
        "\n"
        "Test verdict: Pass\n"
    )
    assert implement_workflow._parse_test_verdict(report) == ("Pass", [])
    # A fenced declaration on its own is not a declaration at all (the E4.5b lesson).
    assert (
        implement_workflow._parse_test_verdict("```\nTest verdict: Fail\n```\n") is None
    )


def test_parse_test_verdict_rejects_a_code_span_declaration() -> None:
    """Only a bare line is a declaration (`verdict.py`'s `DECLARATION_RE` differs)."""
    assert implement_workflow._parse_test_verdict("`Test verdict: Fail`\n") is None
    assert (
        implement_workflow._parse_test_verdict(
            "Write `Test verdict: Fail` when a criterion failed.\n"
        )
        is None
    )
    # Nor is a heading a declaration.
    assert implement_workflow._parse_test_verdict("## Test verdict: Fail\n") is None


def test_parse_test_verdict_with_no_declaration_is_none() -> None:
    """No declaration is `None`, which the workflow fails closed on (req 4/5)."""
    assert implement_workflow._parse_test_verdict("") is None
    assert (
        implement_workflow._parse_test_verdict("Criterion: AC-1\nResult: Fail\n")
        is None
    )


def test_the_test_prompt_carries_the_declarations_the_parser_reads() -> None:
    """`prompts/test.md` is the contract that emits the block §8.2 parses (§7.2's rule).

    The prompt's own examples are fed to the parser, so a reformat that stops asking for a
    bare declaration — or ropes it into a fence or a code span — fails here instead of making
    every real run stop `BLOCKED` on a verdict no tester can produce.
    """
    prompt = (ToolkitPaths.resolve().prompts_dir / "test.md").read_text(encoding="utf-8")
    lines = prompt.splitlines()

    # The per-criterion template carries the `Scope:` separation the verdict relies on.
    assert "Scope: in-scope / out-of-scope / pre-existing" in lines

    # Both declaration shapes are bare lines in the prompt, and each parses as itself.
    pass_at = lines.index("Test verdict: Pass")
    assert implement_workflow._parse_test_verdict(
        "\n".join(lines[pass_at - 1 : pass_at + 1])
    ) == ("Pass", [])
    fail_at = lines.index("Test verdict: Fail")
    assert implement_workflow._parse_test_verdict(
        "\n".join(lines[fail_at : fail_at + 2])
    ) == ("Fail", ["AC-1", "AC-3"])


def test_parse_test_verdict_is_pure() -> None:
    """No I/O, no mutation, repeatable: the helper is the executable spec."""
    before = _FAIL_REPORT
    first = implement_workflow._parse_test_verdict(_FAIL_REPORT)
    second = implement_workflow._parse_test_verdict(_FAIL_REPORT)
    assert _FAIL_REPORT == before
    assert first == second == ("Fail", ["AC-1", "AC-3"])
    # The criteria list is a fresh object, so a caller cannot mutate a cached result.
    assert first is not second
    assert first[1] is not second[1]


#: Pinned seed and run count for the seeded property run below (AGENTS.md "Tests": pytest
#: only, no ``hypothesis``, so a reproducible sample is the generator and there is no
#: shrinking).
TEST_VERDICT_PROPERTY_SEED = 51011
TEST_VERDICT_PROPERTY_RUNS = 64

#: Prose a sampler may wrap around the declaration. None of it is a bare declaration line,
#: and it includes the trap the gate exists to avoid: a `Result: Fail` for an out-of-scope or
#: pre-existing criterion, and a code span that names the label.
_TEST_VERDICT_PROSE = (
    "Criterion: AC-1",
    "Result: Fail",
    "Result: Unverified",
    "Scope: in-scope",
    "Scope: out-of-scope",
    "Scope: pre-existing",
    "Evidence: uv run --frozen pytest",
    "Gap: None",
    "The template asks for a `Test verdict: Fail` line on its own.",
)


def test_parse_test_verdict_is_a_seeded_property() -> None:
    """Metamorphic property (seed/runs pinned above): only the bare block decides.

    For every sampled report, the parsed verdict is exactly the one the **bare** declaration
    block planted and the criteria are that block's comma-separated names — a fenced example
    declaring the opposite verdict, an out-of-scope `Result: Fail`, an `Unverified` criterion
    and a code span naming the label never change it. Two calls agree, which is the purity
    half of the property.
    """
    rng = random.Random(TEST_VERDICT_PROPERTY_SEED)

    for _ in range(TEST_VERDICT_PROPERTY_RUNS):
        verdict = rng.choice(["Pass", "Fail"])
        criteria = [f"AC-{rng.randint(1, 12)}" for _ in range(rng.randint(0, 3))]
        prose = [rng.choice(_TEST_VERDICT_PROSE) for _ in range(rng.randint(0, 4))]
        fenced = rng.choice(["Pass", "Fail"])
        report = "\n".join(
            [
                *prose,
                "```text",
                f"Test verdict: {fenced}",
                "Failing in-scope criteria: AC-999",
                "```",
                f"Test verdict: {verdict}",
                *(
                    [f"Failing in-scope criteria: {', '.join(criteria)}"]
                    if criteria
                    else []
                ),
                "",
            ]
        )
        expected = ("Pass", []) if verdict == "Pass" else ("Fail", criteria)
        assert implement_workflow._parse_test_verdict(report) == expected
        assert implement_workflow._parse_test_verdict(report) == expected


# --------------------------------------------------------------------------- #
# Execution, gates, resume
# --------------------------------------------------------------------------- #


def test_full_run_succeeds_and_records_pr(tmp_path: Path, monkeypatch) -> None:
    control, worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(implement_workflow, "run_stage", _Recorder())

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        approve_all=True,
    )

    assert code == 0
    runs = list(_runs_root(control).iterdir())
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert state.status == SUCCEEDED
    assert state.repo_root == str(worktree)
    assert state.gates and state.gates[-1].name == implement_workflow.GATE
    assert state.pr.get("number") == 42
    assert len(runs) == 1
    assert not (control / "aidt" / "runs").exists()


def test_full_run_dispatches_the_summary_stage_on_the_recorder_agent(
    tmp_path: Path, monkeypatch
) -> None:
    """X1.1: I8 is planned and dispatched between I5 and I7 on the ``recorder`` agent.

    A fake-stage run with no Pi: the plan comes from the registry, so this is the
    workflow's own dispatch. It pins the position (immediately after I5's record stage,
    before the tick), the agent, the single ``{branch}`` variable, the resolved prompt and
    the absence of a run-time condition — I8 runs unconditionally, unlike I7.
    """
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    # Immediately after I5's record stage and before the tick / the PR stage. (The tick
    # itself is withheld here because this fake records no gate evidence — H3.2.)
    assert (
        recorder.names.index("summarize-implementation-results")
        == recorder.names.index("record-implementation-results") + 1
    )
    assert recorder.names.index("summarize-implementation-results") < recorder.names.index(
        "pr"
    )
    spec = next(
        item
        for item in recorder.specs
        if item.name == "summarize-implementation-results"
    )
    assert (spec.id, spec.agent_id, spec.variables, spec.when) == (
        "I8",
        "recorder",
        ["03-E4.1"],
        "",
    )
    assert spec.prompt.name == "summarize-implementation-results.md"
    assert spec.prompt.parent == ToolkitPaths.resolve().prompts_dir


def test_full_run_dispatches_the_integration_test_guide_on_the_recorder_agent(
    tmp_path: Path, monkeypatch
) -> None:
    """X1.2: I9 is planned and dispatched between I8 and the tick, on ``recorder``.

    A fake-stage run with no Pi, exactly the X1.1 I8 test's shape: the plan comes from the
    registry, so this pins the real dispatch — its position immediately after the summary,
    before the tick / PR stage, its agent, its single ``{branch}`` variable, its resolved
    prompt and the absence of a run-time condition (I9 is unconditional, unlike I7).
    """
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert (
        recorder.names.index("write-integration-test-guide")
        == recorder.names.index("summarize-implementation-results") + 1
    )
    assert recorder.names.index("write-integration-test-guide") < recorder.names.index(
        "pr"
    )
    spec = next(
        item
        for item in recorder.specs
        if item.name == "write-integration-test-guide"
    )
    assert (spec.id, spec.agent_id, spec.variables, spec.when) == (
        "I9",
        "recorder",
        ["03-E4.1"],
        "",
    )
    assert spec.prompt.name == "write-integration-test-guide.md"
    assert spec.prompt.parent == ToolkitPaths.resolve().prompts_dir


def test_stage_failure_returns_one(tmp_path: Path, monkeypatch) -> None:
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(implement_workflow, "run_stage", _Recorder(fail={"test"}))

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        approve_all=True,
    )

    assert code == 1
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert state.status == FAILED


def test_gate_denied_returns_blocked(tmp_path: Path, monkeypatch) -> None:
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    # No --yes and a non-interactive session: the gate fails closed.
    code = implement_workflow.run(task_prompt_path=prompt, **_roots(control))

    assert code == 3
    # The PR stage must not have run after a denied gate.
    assert "pr" not in recorder.names


# --------------------------------------------------------------------------- #
# Q1.1: an in-scope tester `Fail` withholds I6 and opens no PR (design §8.2 / §17 Z10)
# --------------------------------------------------------------------------- #


def test_an_in_scope_fail_withholds_the_pr_and_records_the_criteria(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Done-when: I2 reports `Fail` in its message, so `pr` never runs and the run is BLOCKED.

    The stage itself stays `SUCCEEDED` (that is the whole point), the approve gate is never
    recorded, the criteria are recorded on `state.pr`, and the stop names both the criteria
    and the `--from test` re-test path — the forward path the resume rule requires.
    """
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _VerdictStages(_FAIL_REPORT)
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 3
    # I6 never runs, so no PR is opened — and the approve gate was never even offered.
    assert "pr" not in recorder.names
    # The roadmap scopes the stop to I6: the tick still ran (and stays uncommitted).
    assert "update-roadmap" in recorder.names
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert state.status == BLOCKED
    assert state.stage("test").status == SUCCEEDED
    assert state.pr["test_verdict"] == "Fail"
    assert state.pr["test_failing_criteria"] == ["AC-1", "AC-3"]
    assert [gate.name for gate in state.gates] == []

    err = capsys.readouterr().err
    assert "AC-1, AC-3" in err
    assert "--from test" in err
    assert "--resume" in err


def test_an_in_scope_fail_withholds_the_pr_on_the_parallel_dispatch_path(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 3: the post-pre-PR verdict gate also runs after ``--parallel`` dispatch."""
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _VerdictStages(_FAIL_REPORT)
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        approve_all=True,
        parallel=True,
    )

    assert code == 3
    assert recorder.names.count("test") == 1
    assert "pr" not in recorder.names
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert state.status == BLOCKED
    assert state.stage("test").status == SUCCEEDED
    assert state.pr["test_verdict"] == "Fail"
    assert state.pr["test_failing_criteria"] == ["AC-1", "AC-3"]
    assert state.gates == []
    assert "--from test" in capsys.readouterr().err


def test_from_test_reruns_i2_and_can_clear_a_recorded_fail(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 5: ``--from test`` is the explicit re-test route, unlike plain resume."""
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _VerdictStages(_FAIL_REPORT)
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    first = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )
    assert first == 3
    recorder.test_out = _PASS_REPORT

    second = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        resume=True,
        from_stage="test",
        approve_all=True,
    )

    assert second == 0
    assert recorder.names.count("test") == 2
    # The second invocation starts at I2: I1 was already succeeded, while every later
    # stage (including I6) is eligible to run after the new verdict is read.
    second_test = recorder.names.index("test", recorder.names.index("test") + 1)
    assert "impliment-task" not in recorder.names[second_test:]
    assert recorder.names[-1] == "pr"
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert state.status == SUCCEEDED
    assert state.pr["test_verdict"] == "Pass"


def test_a_resumed_run_re_reads_the_recorded_fail_and_stops_again(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 5: the recorded verdict decides, so a plain `--resume` repeats the stop.

    Every pre-PR stage is already `SUCCEEDED`, I2 included, so nothing re-runs: the gate
    re-reads the recorded `out.txt` and stops identically. That repeat-stop is the intended
    resume semantics — the message must say so and name the re-test path.
    """
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    runs_dir = _runs_root(control)
    state = create_run(
        runs_dir, control, "implement", label="03-E4.1", branch="03-E4.1"
    )
    directory = run_dir(runs_dir, state.run_id)
    stages = directory / "stages"
    stages.mkdir(parents=True, exist_ok=True)
    out = stages / "test.out.txt"
    out.write_text(_FAIL_REPORT, encoding="utf-8")
    for name in DEFAULT_ORDER[:-1]:
        state.record_stage(
            StageRecord(
                name=name,
                agent="tester",
                model="m",
                status=SUCCEEDED,
                artifacts={"out": str(out)} if name == "test" else {},
            )
        )
    state.status = BLOCKED
    save(directory, state)

    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        resume=True,
        approve_all=True,
    )

    assert code == 3
    assert recorder.names == []  # nothing re-ran: I2 is skipped and its verdict re-read
    state = implement_workflow.list_runs(runs_dir)[-1]
    assert state.status == BLOCKED
    assert state.pr["test_failing_criteria"] == ["AC-1", "AC-3"]
    err = capsys.readouterr().err
    assert "AC-1, AC-3" in err
    assert "--from test" in err


def test_a_pass_verdict_proceeds_to_the_gate_and_dispatches_pr(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 6: `Pass` leaves the gate and I6 exactly as they were, and is recorded."""
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _VerdictStages(_PASS_REPORT)
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert recorder.names[-1] == "pr"
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert state.status == SUCCEEDED
    assert state.pr["test_verdict"] == "Pass"
    assert implement_workflow.TEST_FAILING_CRITERIA_KEY not in state.pr
    assert state.gates[-1].name == implement_workflow.GATE
    assert state.pr.get("number") == 42


def test_a_pass_verdict_survives_an_out_of_scope_failure_in_the_report(
    tmp_path: Path, monkeypatch
) -> None:
    """Done-when: a pre-existing/out-of-scope `Result: Fail` never withholds a legitimate PR."""
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    report = (
        "Criterion: AC-1\n"
        "Result: Pass\n"
        "Scope: in-scope\n"
        "Evidence: uv run --frozen pytest tests/test_x.py\n"
        "Gap: None\n"
        "\n"
        "Criterion: pre-existing suite failure in an untouched package\n"
        "Result: Fail\n"
        "Scope: pre-existing\n"
        "Evidence: uv run --frozen pytest tests/test_untouched.py\n"
        "Gap: None\n"
        "\n"
        "Criterion: AC-2\n"
        "Result: Unverified\n"
        "Scope: out-of-scope\n"
        "Evidence: none\n"
        "Gap: no browser tooling\n"
        "\n"
        "Test verdict: Pass\n"
    )
    recorder = _VerdictStages(report)
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert "pr" in recorder.names
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert state.status == SUCCEEDED
    assert state.pr["test_verdict"] == "Pass"


@pytest.mark.parametrize(
    ("test_out", "reason"),
    [
        (None, "no readable out.txt"),
        ("", "final message is empty"),
        ("Criterion: AC-1\nResult: Pass\n", "no bare `Test verdict: Pass|Fail`"),
    ],
    ids=["missing-out", "empty-message", "no-declaration"],
)
def test_an_unreadable_test_verdict_fails_closed_without_a_pr(
    tmp_path: Path, monkeypatch, capsys, test_out: str | None, reason: str
) -> None:
    """Req 5: an unparseable verdict — including a missing/empty out.txt — is BLOCKED/3.

    A fresh run whose I2 exhausted the U1 retry records a `SUCCEEDED` stage with an empty
    final message (`runner.py` leaves that case to the workflow, H1.1), and ``None`` here is
    the same record with its ``out.txt`` lost; both fail closed naming the ambiguity rather
    than proceeding to a PR nobody can justify.
    """
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _VerdictStages(test_out)
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 3
    assert "pr" not in recorder.names
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert state.status == BLOCKED
    assert state.pr["test_verdict"] is None
    assert [gate.name for gate in state.gates] == []
    err = capsys.readouterr().err
    assert "cannot read I2's verdict" in err
    assert reason in err
    assert "--from test" in err


def test_a_resumed_run_with_a_lost_out_txt_fails_closed(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 5: a resumed run can carry a `SUCCEEDED` test record whose out.txt is absent."""
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    runs_dir = _runs_root(control)
    state = create_run(
        runs_dir, control, "implement", label="03-E4.1", branch="03-E4.1"
    )
    directory = run_dir(runs_dir, state.run_id)
    # The artifact path is recorded but the file was never written / has been removed.
    lost = directory / "stages" / "test.out.txt"
    for name in DEFAULT_ORDER[:-1]:
        state.record_stage(
            StageRecord(
                name=name,
                agent="tester",
                model="m",
                status=SUCCEEDED,
                artifacts={"out": str(lost)} if name == "test" else {},
            )
        )
    state.status = BLOCKED
    save(directory, state)

    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        resume=True,
        approve_all=True,
    )

    assert code == 3
    assert recorder.names == []
    assert "pr" not in recorder.names
    state = implement_workflow.list_runs(runs_dir)[-1]
    assert state.status == BLOCKED
    assert state.pr["test_verdict"] is None
    err = capsys.readouterr().err
    assert "no readable out.txt" in err
    assert "--from test" in err


def test_resume_skips_succeeded_stages(tmp_path: Path, monkeypatch) -> None:
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    runs_dir = _runs_root(control)

    state = create_run(
        runs_dir,
        control,
        "implement",
        label="03-E4.1",
        task={"phase": "03", "task": "E4.1"},
        branch="03-E4.1",
    )
    directory = run_dir(runs_dir, state.run_id)
    state.record_stage(
        StageRecord(name="impliment-task", agent="implementer", model="m", status=SUCCEEDED)
    )
    state.record_stage(
        StageRecord(
            name="test", agent="tester", model="m", status=FAILED, error="boom"
        )
    )
    state.status = FAILED
    save(directory, state)

    recorder = _GateEvidenceStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        resume=True,
        approve_all=True,
    )

    assert code == 0
    assert "impliment-task" not in recorder.names
    assert recorder.names == [
        "test",
        "update-traceability",
        "update-architecture",
        "record-implementation-results",
        "summarize-implementation-results",
        "write-integration-test-guide",
        "update-roadmap",
        "pr",
    ]


def test_from_forces_rerun(tmp_path: Path, monkeypatch) -> None:
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    runs_dir = _runs_root(control)

    state = create_run(
        runs_dir, control, "implement", label="03-E4.1", branch="03-E4.1"
    )
    directory = run_dir(runs_dir, state.run_id)
    for name in ("impliment-task", "test", "update-traceability"):
        state.record_stage(
            StageRecord(name=name, agent="implementer", model="m", status=SUCCEEDED)
        )
    save(directory, state)

    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        resume=True,
        from_stage="test",
        approve_all=True,
    )

    assert code == 0
    assert recorder.names[0] == "test"
    assert "impliment-task" not in recorder.names


def test_unknown_from_stage_is_usage_error_before_worktree(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """F1 (PR #49 review follow-up): a typo'd ``--from`` refuses with exit 2 and
    leaves behind neither a worktree nor a run directory — the same fail-closed
    contract as the malformed-pattern refusal."""
    control, prompt = _layout(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), from_stage="bogus"
    )

    assert code == 2
    assert recorder.names == []
    assert not (tmp_path / "03-E4.1").exists()
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []
    err = capsys.readouterr().err
    assert "unknown stage `bogus`" in err
    assert "impliment-task" in err  # the message lists the expected stage names


def test_resume_declined_leaves_no_worktree(tmp_path: Path, monkeypatch, capsys) -> None:
    """F2 (PR #49 review follow-up): declining the ``--resume`` confirmation
    must leave no worktree behind — the confirm happens before branch setup,
    so a refusal creates neither worktree nor run state (same fail-closed
    contract as the still-running guard)."""
    control, prompt = _layout(tmp_path)
    _patch(monkeypatch)
    runs_dir = _runs_root(control)
    state = create_run(
        runs_dir, control, "implement", label="03-E4.1", branch="03-E4.1"
    )
    directory = run_dir(runs_dir, state.run_id)
    state.record_stage(
        StageRecord(name="impliment-task", agent="implementer", model="m", status=SUCCEEDED)
    )
    state.status = FAILED
    save(directory, state)

    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)
    # Non-interactive stdin would auto-confirm, so fake the explicit "no".
    monkeypatch.setattr(implement_workflow, "_confirm_resume", lambda assume_yes: False)

    code = implement_workflow.run(task_prompt_path=prompt, **_roots(control), resume=True)

    assert code == 4
    assert recorder.names == []
    # Decline creates nothing: no sibling worktree in the workspace root.
    assert not (tmp_path / "03-E4.1").exists()
    # Exactly the pre-existing run state; no new run was written.
    assert len(list(_runs_root(control).iterdir())) == 1
    err = capsys.readouterr().err
    assert "resume declined." in err


# --------------------------------------------------------------------------- #
# --parallel
# --------------------------------------------------------------------------- #


class _TrackingStages(_GateEvidenceStages):
    """Recorder that tracks how many stages run at the same time.

    ``slow`` names the stages that park briefly so a group of them overlaps measurably;
    it defaults to the registry's safe pair and is widened by the E4.4 tests that
    configure a different group.
    """

    def __init__(self, slow: set[str] | None = None) -> None:
        super().__init__()
        self._guard = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.slow = {"test", "update-architecture"} if slow is None else slow

    def __call__(self, spec, **kwargs):
        with self._guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if spec.name in self.slow:
                time.sleep(0.05)
            return super().__call__(spec, **kwargs)
        finally:
            with self._guard:
                self.active -= 1


def test_serial_runs_the_pair_one_at_a_time(tmp_path: Path, monkeypatch) -> None:
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _TrackingStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        approve_all=True,
    )

    assert code == 0
    assert recorder.max_active == 1


def test_parallel_runs_test_and_architecture_concurrently(
    tmp_path: Path, monkeypatch
) -> None:
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _TrackingStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        approve_all=True,
        parallel=True,
    )

    assert code == 0
    assert recorder.max_active >= 2
    assert set(recorder.names[:3]) == {
        "impliment-task",
        "test",
        "update-architecture",
    }
    assert recorder.names[3:] == [
        "update-traceability",
        "record-implementation-results",
        "summarize-implementation-results",
        "write-integration-test-guide",
        "update-roadmap",
        "pr",
    ]


# --------------------------------------------------------------------------- #
# --parallel: config-driven parallel_groups (E4.4, EXTRACTION.md §3.4/§3.5, R11)
# --------------------------------------------------------------------------- #


def test_effective_parallel_groups_distinguishes_absent_from_declared_empty(
    tmp_path: Path,
) -> None:
    """Absent entry → the registry default; an explicit ``[]`` → no groups (serial)."""
    resolved = resolve_config(load_target_config(tmp_path / "aidw" / "config.yaml"))
    assert "workflows.implement.parallel_groups" not in resolved
    assert implement_workflow.effective_parallel_groups(resolved) == (
        ("test", "update-architecture"),
    )

    _write_config(
        tmp_path,
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    parallel_groups: []\n",
    )
    resolved = resolve_config(load_target_config(tmp_path / "aidw" / "config.yaml"))
    assert resolved["workflows.implement.parallel_groups"].source == "config"
    assert implement_workflow.effective_parallel_groups(resolved) == ()


def test_parallel_runs_a_configured_group_instead_of_the_default_pair(
    tmp_path: Path, monkeypatch
) -> None:
    control, _worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control,
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    parallel_groups:\n"
        "      - [test, record-implementation-results]\n",
    )
    _patch(monkeypatch)
    # Slow the non-member too: an implementation that accidentally retained the default
    # pair would overlap all three, making this exact bound fail.
    recorder = _TrackingStages(
        slow={"test", "record-implementation-results", "update-architecture"}
    )
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True, parallel=True
    )

    assert code == 0
    assert recorder.max_active == 2
    assert set(recorder.names[:3]) == {
        "impliment-task",
        "test",
        "record-implementation-results",
    }
    # The default pair's other member is no longer grouped: it keeps registry order and
    # runs on its own. Nothing hardcoded survived the replacement.
    assert recorder.names[3:] == [
        "update-traceability",
        "update-architecture",
        "summarize-implementation-results",
        "write-integration-test-guide",
        "update-roadmap",
        "pr",
    ]


def test_parallel_group_runs_at_its_earliest_member_not_its_first_listed(
    tmp_path: Path, monkeypatch
) -> None:
    """A group's members run at the position of its *earliest* member (I2 here)."""
    control, _worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control,
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    parallel_groups:\n"
        "      - [update-architecture, test]\n",
    )
    _patch(monkeypatch)
    recorder = _TrackingStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True, parallel=True
    )

    assert code == 0
    assert recorder.max_active >= 2
    assert set(recorder.names[:3]) == {
        "impliment-task",
        "test",
        "update-architecture",
    }
    assert recorder.names[3:] == [
        "update-traceability",
        "record-implementation-results",
        "summarize-implementation-results",
        "write-integration-test-guide",
        "update-roadmap",
        "pr",
    ]


def test_parallel_with_an_explicit_empty_group_list_runs_serially(
    tmp_path: Path, monkeypatch
) -> None:
    """``parallel_groups: []`` means serial — never a fallback to the default pair."""
    control, _worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control,
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    parallel_groups: []\n",
    )
    _patch(monkeypatch)
    recorder = _TrackingStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True, parallel=True
    )

    assert code == 0
    # The default pair would have overlapped here; the declared empty list does not.
    assert recorder.max_active == 1
    assert recorder.names == DEFAULT_ORDER


def test_a_group_naming_the_pr_stage_leaves_pr_in_its_post_gate_slot(
    tmp_path: Path, monkeypatch
) -> None:
    """``pr`` is a valid stage name but the post-gate sync point, so it still runs alone."""
    control, _worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control,
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    parallel_groups:\n"
        "      - [test, pr]\n",
    )
    _patch(monkeypatch)
    recorder = _TrackingStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True, parallel=True
    )

    assert code == 0
    assert recorder.names == DEFAULT_ORDER
    assert recorder.max_active == 1


def test_a_group_member_failure_stops_the_run_with_a_resume_hint(
    tmp_path: Path, monkeypatch
) -> None:
    control, _worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _TrackingStages()
    recorder.fail = {"update-architecture"}
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True, parallel=True
    )

    assert code == 1
    # No later stage ran: the tail and I6 are absent.
    assert set(recorder.names) == {"impliment-task", "test", "update-architecture"}
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    # By name, not by position: the two group members record in completion order.
    assert state.stage("update-architecture").status == FAILED
    assert state.stage("test").status == SUCCEEDED
    assert state.status == FAILED
    # Deterministic: the earliest failed member in registry order, not completion order.
    assert state.resume == {"next_stage": "update-architecture"}


@pytest.mark.parametrize("dry_run", [False, True])
def test_unknown_parallel_group_member_fails_closed_before_any_run_state(
    tmp_path: Path, monkeypatch, capsys, dry_run: bool
) -> None:
    control, prompt = _layout(tmp_path)
    _write_config(
        control,
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    parallel_groups:\n"
        "      - [test, nonesuch]\n",
    )
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=dry_run
    )

    assert code == 2
    assert recorder.names == []
    # Before any worktree or run record: the refusal precedes branch setup.
    assert not (tmp_path / "03-E4.1").exists()
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []
    err = capsys.readouterr().err
    assert "workflows.implement.parallel_groups" in err
    assert "group [0]" in err
    assert "nonesuch" in err


def test_empty_inner_parallel_group_fails_closed_even_in_dry_run(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    control, prompt = _layout(tmp_path)
    _write_config(
        control,
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    parallel_groups:\n"
        "      - []\n",
    )
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 2
    assert recorder.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []
    err = capsys.readouterr().err
    assert "group [0]" in err
    assert "names no stage" in err


# --------------------------------------------------------------------------- #
# git.changed_files
# --------------------------------------------------------------------------- #


def test_changed_files_lists_branch_diff(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "checkout", "-qb", "feature"], cwd=tmp_path, check=True)
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "b"], cwd=tmp_path, check=True)

    assert git.changed_files(tmp_path, "main") == ["b.txt"]


# --------------------------------------------------------------------------- #
# Prompt cleanliness
# --------------------------------------------------------------------------- #


def test_impliment_prompt_has_no_agent_branch_setup() -> None:
    text = (ToolkitPaths.resolve().prompts_dir / "impliment-task.md").read_text(
        encoding="utf-8"
    )
    assert "git checkout -b" not in text
    assert "git switch -c" not in text
    assert "git branch --list" not in text
    assert "git ls-remote" not in text
    assert "### Branch setup (do this first" not in text
    # The one-line pointer that AIDT owns it stays.
    assert "AIDT owns branch setup" in text


# --------------------------------------------------------------------------- #
# One run per worktree (E2.7, EXTRACTION.md §3.2/§3.10)
# --------------------------------------------------------------------------- #


class _BlockingStages(_Recorder):
    """A fake ``run_stage`` that parks the first run inside its first stage.

    Parking there (not before ``create_run``) is what makes two runs genuinely
    concurrent: the holder owns its worktree lock *and* has already written its run
    directory, which is exactly the double-run the lock must refuse.
    """

    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        super().__init__()
        self.entered = entered
        self.release_event = release

    def __call__(self, spec, **kwargs):
        self.entered.set()
        assert self.release_event.wait(timeout=60), "the holder was never released"
        return super().__call__(spec, **kwargs)


def _start_run(**kwargs) -> tuple[threading.Thread, dict]:
    """Call ``implement.run`` on a thread; ``outcome['code']`` holds its exit code."""
    outcome: dict = {}

    def target() -> None:
        try:
            outcome["code"] = implement_workflow.run(**kwargs)
        except BaseException as exc:  # pragma: no cover - asserted via ``outcome``
            outcome["error"] = exc

    thread = threading.Thread(target=target, name="aidw-implement-run")
    thread.start()
    return thread, outcome


def _two_task_worktrees(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    """Control root plus two worktrees, each with its own committed task prompt."""
    _bare, control = _make_bare_with_control(tmp_path)
    first, first_prompt = _make_task_worktree(control, "03-E4.1", "03-E4.1-prompt.md")
    second, second_prompt = _make_task_worktree(control, "03-E4.2", "03-E4.2-prompt.md")
    return control, first, first_prompt, second, second_prompt


def test_two_concurrent_runs_in_one_worktree_are_refused(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The lock, not the branch-keyed still-running guard, refuses a live peer.

    The second run passes ``--resume`` — the documented "finish it" path — so it clears
    the still-running guard, which is exactly the race the lock closes: the second
    process's check can read ``state.json`` before the first one writes it.
    """
    control, worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    holder_stages = _BlockingStages(entered, release)
    monkeypatch.setattr(implement_workflow, "run_stage", holder_stages)
    roots = _roots(control)

    holder, outcome = _start_run(task_prompt_path=prompt, **roots, approve_all=True)
    assert entered.wait(timeout=60), "the holding run never reached a stage"

    refused = implement_workflow.run(
        task_prompt_path=prompt, resume=True, approve_all=True, **roots
    )

    release.set()
    holder.join(timeout=60)
    assert not holder.is_alive()
    assert "error" not in outcome, outcome.get("error")

    assert refused == 4
    assert outcome["code"] == 0
    # Exactly one run directory: the refused run wrote nothing, including no run state.
    assert len(list(_runs_root(control).iterdir())) == 1
    err = capsys.readouterr().err
    assert "another aidw run is already active" in err
    assert str(worktree) in err


def test_two_concurrent_runs_in_different_worktrees_both_proceed(
    tmp_path: Path, monkeypatch
) -> None:
    """Two runs in different worktrees proceed (the roadmap's E2.7 "done when")."""
    control, first, first_prompt, second, second_prompt = _two_task_worktrees(tmp_path)
    _patch(monkeypatch)
    entered = {first: threading.Event(), second: threading.Event()}
    release = threading.Event()

    class _PerWorktreeStages(_Recorder):
        def __call__(self, spec, **kwargs):
            path = kwargs["repo_root"]
            entered.setdefault(path, threading.Event()).set()
            assert release.wait(timeout=60), "the runs were never released"
            return super().__call__(spec, **kwargs)

    monkeypatch.setattr(implement_workflow, "run_stage", _PerWorktreeStages())
    roots = _roots(control)

    first_thread, first_outcome = _start_run(
        task_prompt_path=first_prompt, **roots, approve_all=True
    )
    second_thread, second_outcome = _start_run(
        task_prompt_path=second_prompt, **roots, approve_all=True
    )
    # Both reached a stage while the other is still running: neither was refused.
    assert entered[first].wait(timeout=60) and entered[second].wait(timeout=60)
    release.set()
    first_thread.join(timeout=60)
    second_thread.join(timeout=60)
    assert not first_thread.is_alive() and not second_thread.is_alive()

    assert first_outcome.get("code") == 0, first_outcome.get("error")
    assert second_outcome.get("code") == 0, second_outcome.get("error")
    runs = list(_runs_root(control).iterdir())
    assert len(runs) == 2
    assert {state.repo_root for state in implement_workflow.list_runs(_runs_root(control))} == {
        str(first),
        str(second),
    }


def test_a_held_worktree_lock_is_refused_before_any_run_state(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The key is the *located* worktree, and the refusal precedes ``create_run``."""
    control, worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)
    roots = _roots(control)

    with lock.acquire(roots["workspace"].state_root, worktree):
        code = implement_workflow.run(task_prompt_path=prompt, **roots, approve_all=True)

    assert code == 4
    assert recorder.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []
    err = capsys.readouterr().err
    assert "another aidw run is already active" in err
    assert str(worktree) in err


def test_the_dry_run_takes_the_same_worktree_lock(tmp_path: Path, monkeypatch) -> None:
    """A dry run reaches ``create_run``, so it holds and releases the same key."""
    control, worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(implement_workflow, "run_stage", _Recorder())
    roots = _roots(control)

    with lock.acquire(roots["workspace"].state_root, worktree):
        code = implement_workflow.run(
            task_prompt_path=prompt, **roots, dry_run=True
        )

    assert code == 4

    # And a dry run that does acquire releases it: the key is free afterwards.
    assert implement_workflow.run(task_prompt_path=prompt, **roots, dry_run=True) == 0
    with lock.acquire(roots["workspace"].state_root, worktree):
        pass


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [("success", 0), ("stage-failure", 1), ("gate-denied", 3)],
)
def test_the_worktree_lock_is_released_on_every_exit_path(
    tmp_path: Path, monkeypatch, scenario: str, expected: int
) -> None:
    control, worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    failures = {"test"} if scenario == "stage-failure" else set()
    monkeypatch.setattr(implement_workflow, "run_stage", _Recorder(fail=failures))
    roots = _roots(control)
    # ``gate-denied`` is the no-``--yes``, non-interactive default: the gate fails closed
    # *after* the run exists, which is the mid-run refusal that must still release.
    approve_all = scenario != "gate-denied"

    code = implement_workflow.run(
        task_prompt_path=prompt, **roots, approve_all=approve_all
    )

    assert code == expected
    with lock.acquire(roots["workspace"].state_root, worktree):
        pass


# --------------------------------------------------------------------------- #
# core vs repo-optional preflight (E4.5a, D12/D13, EXTRACTION.md §3.5)
# --------------------------------------------------------------------------- #

#: The registry's implement order (R6 ids, §3.5's inventory table), including X1.1's I8 and
#: X1.2's I9.
IMPLEMENT_STAGE_IDS = ("I1", "I2", "I3", "I4", "I5", "I8", "I9", "I7", "I6")


def _declared_implement_stages(disabled: set[str] | None = None) -> str:
    """A declared implement list carrying every id, optionally disabling some of them.

    The full list is not optional: §3.4's declared list **replaces** the toolkit's
    wholesale, so a minimal list would trip E4.5a's removal rule instead of the rule a
    test is about.
    """
    disabled = disabled or set()
    lines = ["schema_version: 1", "workflows:", "  implement:", "    stages:"]
    for stage_id in IMPLEMENT_STAGE_IDS:
        lines.append(f"      - id: {stage_id}")
        if stage_id in disabled:
            lines.append("        enabled: false")
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("dry_run", [False, True])
def test_a_disabled_core_stage_is_refused_before_any_side_effect(
    tmp_path: Path, monkeypatch, capsys, dry_run: bool
) -> None:
    """D12/D13: I5 (record-results) is core, so ``enabled: false`` is a config refusal."""
    control, prompt = _layout(tmp_path)
    _write_config(control, _declared_implement_stages({"I5"}))
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)
    roots = _roots(control)

    code = implement_workflow.run(
        task_prompt_path=prompt, **roots, dry_run=dry_run
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "workflows.implement.stages" in err
    assert "I5" in err
    assert "core stage cannot be disabled" in err
    # Before any stage, run record or worktree — `--dry-run` included.
    assert recorder.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []
    assert not (roots["workspace"].workspace_root / "03-E4.1").exists()


def test_a_disabled_repo_optional_stage_passes_the_preflight(
    tmp_path: Path, monkeypatch
) -> None:
    """D13/E4.5b: I3 (traceability) is repo-optional, and disabling it means omitting it."""
    control, prompt = _layout(tmp_path)
    _write_config(control, _declared_implement_stages({"I3"}))
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 0
    # E4.5b req 2: `enabled: false` is honoured by omission, never warned about.
    assert recorder.names == [
        name for name in DEFAULT_ORDER if name != "update-traceability"
    ]


# --------------------------------------------------------------------------- #
# repo-added stages in the plan and the schedule (E4.5b req 1/req 8)
# --------------------------------------------------------------------------- #

#: The declared `prompt:` of a repo-added implement stage, relative to the target root.
REPO_ADDED_PROMPT = "aidw/prompts/repo-added.md"


def _declared_stages(entries: list[dict[str, object]]) -> str:
    """``aidw/config.yaml`` declaring ``workflows.implement.stages = entries``."""
    lines = ["schema_version: 1", "workflows:", "  implement:", "    stages:"]
    for entry in entries:
        for index, (key, value) in enumerate(entry.items()):
            prefix = "      - " if index == 0 else "        "
            rendered = (
                ("true" if value else "false") if isinstance(value, bool) else str(value)
            )
            lines.append(f"{prefix}{key}: {rendered}")
    return "\n".join(lines) + "\n"


def _stages_with_repo_added(position: int) -> list[dict[str, object]]:
    """Every core/optional implement id in registry order, plus ``X9`` after ``position``."""
    entries: list[dict[str, object]] = [
        {"id": stage_id} for stage_id in IMPLEMENT_STAGE_IDS
    ]
    entries.insert(
        position, {"id": "X9", "agent": "implementer", "prompt": REPO_ADDED_PROMPT}
    )
    return entries


def _write_repo_added_prompt(*roots: Path) -> None:
    """Write the repo-added stage's prompt into each root.

    The preflight resolves it against the **control** root (that is the tree under check)
    while the plan resolves it against the located **worktree**, so a real-run test needs
    it in both — exactly as a committed repo prompt file is.
    """
    for root in roots:
        path = root / REPO_ADDED_PROMPT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# repo-added stage\n", encoding="utf-8")


def _patch_with_agents(monkeypatch) -> None:
    """``_patch`` plus the agent configs a repo-added stage's declared ``agent`` needs."""
    _patch(monkeypatch)
    monkeypatch.setattr(
        implement_workflow, "load_all", lambda aidt, repo, **_kwargs: (_AGENTS, [])
    )


def test_a_trailing_repo_added_stage_is_planned_after_i6(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 8: the pr split still targets I6; a trailing stage is not mistaken for it."""
    control, prompt = _layout(tmp_path)
    _write_config(control, _declared_stages(_stages_with_repo_added(len(IMPLEMENT_STAGE_IDS))))
    _write_repo_added_prompt(control)
    _patch_with_agents(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 0
    assert recorder.names == [*DEFAULT_ORDER, "X9"]
    out = capsys.readouterr().out
    # Both id and name are the declared id (§3.5: a repo-added stage declares no name).
    assert "X9 X9 [succeeded] (planned)" in out


def test_a_trailing_repo_added_stage_runs_after_i6(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 8: declared order — I6, then the trailing stage; the PR record stays on I6."""
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control, _declared_stages(_stages_with_repo_added(len(IMPLEMENT_STAGE_IDS)))
    )
    _write_repo_added_prompt(control, worktree)
    _patch_with_agents(monkeypatch)
    recorder = _GateEvidenceStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert recorder.names == [*DEFAULT_ORDER, "X9"]
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert state.status == SUCCEEDED
    # `_record_pr` read I6's output, not the trailing stage's.
    assert state.pr.get("number") == 42


def test_a_denied_gate_stops_before_a_trailing_repo_added_stage(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 8: a denied gate (exit 3) stops before anything declared after I6 runs."""
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control, _declared_stages(_stages_with_repo_added(len(IMPLEMENT_STAGE_IDS)))
    )
    _write_repo_added_prompt(control, worktree)
    _patch_with_agents(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    # No --yes and a non-interactive session: the gate fails closed.
    code = implement_workflow.run(task_prompt_path=prompt, **_roots(control))

    assert code == 3
    assert "pr" not in recorder.names
    assert "X9" not in recorder.names


def test_a_failed_i6_stops_before_a_trailing_repo_added_stage(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 8: a failed I6 (exit 1) stops too, exactly as without a trailing stage."""
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control, _declared_stages(_stages_with_repo_added(len(IMPLEMENT_STAGE_IDS)))
    )
    _write_repo_added_prompt(control, worktree)
    _patch_with_agents(monkeypatch)
    monkeypatch.setattr(
        implement_workflow, "run_stage", _Recorder(fail={"pr"})
    )

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 1


def test_a_repo_added_stage_before_i6_is_scheduled_in_declared_order(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 8: a pre-I6 repo-added stage runs at its full-plan position, serially."""
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(control, _declared_stages(_stages_with_repo_added(2)))
    _write_repo_added_prompt(control, worktree)
    _patch_with_agents(monkeypatch)
    recorder = _GateEvidenceStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert recorder.names == [
        "impliment-task",
        "test",
        "X9",
        "update-traceability",
        "update-architecture",
        "record-implementation-results",
        "summarize-implementation-results",
        "write-integration-test-guide",
        "update-roadmap",
        "pr",
    ]


def test_a_repo_added_stage_before_i6_is_scheduled_in_parallel_mode(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 8: ``--parallel`` covers the repo-added stage at its full-plan position."""
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(control, _declared_stages(_stages_with_repo_added(2)))
    _write_repo_added_prompt(control, worktree)
    _patch_with_agents(monkeypatch)
    recorder = _TrackingStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        approve_all=True,
        parallel=True,
    )

    assert code == 0
    assert recorder.max_active >= 2
    # The default pair overlaps at I2's position; X9 keeps its declared slot after them.
    assert set(recorder.names[:3]) == {"impliment-task", "test", "update-architecture"}
    assert recorder.names[3:] == [
        "X9",
        "update-traceability",
        "record-implementation-results",
        "summarize-implementation-results",
        "write-integration-test-guide",
        "update-roadmap",
        "pr",
    ]


def test_a_repo_added_stage_before_i6_skips_on_resume(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 8: resume skips it exactly as a core stage that already succeeded."""
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(control, _declared_stages(_stages_with_repo_added(2)))
    _write_repo_added_prompt(control, worktree)
    _patch_with_agents(monkeypatch)
    runs_dir = _runs_root(control)
    state = create_run(
        runs_dir, control, "implement", label="03-E4.1", branch="03-E4.1"
    )
    directory = run_dir(runs_dir, state.run_id)
    for name in ("impliment-task", "X9"):
        state.record_stage(
            StageRecord(name=name, agent="implementer", model="m", status=SUCCEEDED)
        )
    save(directory, state)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), resume=True, approve_all=True
    )

    assert code == 0
    assert recorder.names[0] == "test"
    assert "X9" not in recorder.names
    assert "impliment-task" not in recorder.names


def test_from_a_disabled_repo_optional_stage_keeps_the_run_coherent(
    tmp_path: Path, monkeypatch
) -> None:
    """A ``--from`` naming a stage the declared list dropped must not crash the run.

    ``--from`` is validated against the registry names before the locate (it is a *name*
    check), so a repo-optional stage the repo disabled passes validation but is absent from
    the run-path plan. There is no position to re-run from, so every stage keeps its own
    succeeded-skip decision — never a ``StopIteration`` traceback out of ``run()``.
    """
    control, _worktree, prompt = _located_layout(tmp_path)
    _write_config(control, _declared_implement_stages({"I3"}))
    _patch(monkeypatch)
    recorder = _GateEvidenceStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        from_stage="update-traceability",
        approve_all=True,
    )

    assert code == 0
    assert recorder.names == [
        name for name in DEFAULT_ORDER if name != "update-traceability"
    ]


def test_a_repo_added_stage_with_a_missing_prompt_is_refused(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 5: an unresolvable declared prompt is a config refusal, never a traceback."""
    control, prompt = _layout(tmp_path)
    _write_config(control, _declared_stages(_stages_with_repo_added(2)))
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "workflows.implement.stages" in err
    assert "`X9`" in err
    assert "prompt does not resolve" in err
    assert recorder.names == []


def test_named_missing_agent_config_dir_refuses_before_worktree_lookup(
    tmp_path: Path, capsys
) -> None:
    """E4.6: a named global override is an exit-2 preflight error, not a fallback."""
    control, prompt = _layout(tmp_path)
    _write_config(
        control,
        "schema_version: 1\n"
        "paths:\n"
        "  agent_configs_dir: aidw/missing-agent-configs\n",
    )

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "agent-configs directory not found" in err
    assert str(control / "aidw" / "missing-agent-configs") in err
    # The refusal happens before the locate/run-state side effects.
    assert not (control.parent / "aidt-state" / "runs").exists()


def test_a_known_stage_with_an_unknown_agent_is_refused(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """E4.6 req 3: a known id's declared `agent` is existence-checked too.

    It becomes the plan's `agent_id`, so an unknown id must refuse exit 2 here rather than
    surface as `run_stage`'s `ValueError: unknown agent` traceback.
    """
    control, prompt = _layout(tmp_path)
    entries: list[dict[str, object]] = [
        {"id": stage_id} for stage_id in IMPLEMENT_STAGE_IDS
    ]
    entries[0]["agent"] = "no-such-agent"
    _write_config(control, _declared_stages(entries))
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "workflows.implement.stages" in err
    assert "`I1`" in err
    assert "unknown agent `no-such-agent`" in err
    assert recorder.names == []


def test_a_repo_added_stage_with_an_unknown_agent_is_refused(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Req 4/req 5: an unknown declared ``agent`` refuses here, not in ``run_stage``."""
    control, prompt = _layout(tmp_path)
    entries = _stages_with_repo_added(2)
    entries[2] = {"id": "X9", "agent": "no-such-agent", "prompt": REPO_ADDED_PROMPT}
    _write_config(control, _declared_stages(entries))
    _write_repo_added_prompt(control)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "workflows.implement.stages" in err
    assert "`X9`" in err
    assert "unknown agent `no-such-agent`" in err
    assert recorder.names == []


# --------------------------------------------------------------------------- #
# I7 update-roadmap: the tick stage (H3.1, design §8.2)
# --------------------------------------------------------------------------- #


class _NoTickStages(_GateEvidenceStages):
    """A fake stage that leaves the roadmap untouched — the "already `[x]`" agent."""

    def __call__(self, spec, **kwargs):
        if spec.name == "update-roadmap":
            # Bypass the recorder's tick so the file stays byte-identical.
            self.names.append(spec.name)
            self.specs.append(spec)
            self.repo_roots.append(kwargs["repo_root"])
            directory = run_dir(kwargs["runs_root"], kwargs["state"].run_id)
            stages = directory / "stages"
            stages.mkdir(parents=True, exist_ok=True)
            out = stages / f"{spec.name}.out.txt"
            out.write_text("ok\n", encoding="utf-8")
            record = StageRecord(
                name=spec.name,
                agent=spec.agent_id,
                model="test/model",
                status=SUCCEEDED,
                artifacts={"out": str(out)},
            )
            kwargs["state"].record_stage(record)
            return record
        return super().__call__(spec, **kwargs)


class _NeighbourEditStages(_GateEvidenceStages):
    """A fake stage that flips the checkbox and edits another line too — a failed tick."""

    def __call__(self, spec, **kwargs):
        record = super().__call__(spec, **kwargs)
        if spec.name == "update-roadmap":
            path = Path(spec.variables[0])
            path.write_text(
                path.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            )
        return record


def _stage_record(state, name: str) -> StageRecord:
    record = state.stage(name)
    assert record is not None, name
    return record


def test_a_repo_with_no_traceability_catalog_still_ticks(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Done-when: ``enabled: false`` on I3 no longer drops the tick (H3.1).

    The fixture has no ``docs/rules-coverage/`` at all — the repo-optional traceability
    stage is disabled — and the tick still plans, runs and lands in the roadmap.
    """
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(control, _declared_implement_stages({"I3"}))
    assert not (worktree / "docs" / "rules-coverage").exists()
    _patch(monkeypatch)
    # H3.2: the tick only runs behind green evidence, so the run has to have recorded some.
    recorder = _GateEvidenceStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert "update-traceability" not in recorder.names
    assert "update-roadmap" in recorder.names
    text = (worktree / ROADMAP_REL).read_text(encoding="utf-8")
    assert "- [x] **E4.1. A fixture task**" in text
    # The tick's own record: succeeded (never skipped), the flipped marker, no error.
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    record = _stage_record(state, "update-roadmap")
    assert record.status == SUCCEEDED
    assert record.artifacts.get("tick") == "flipped"
    assert record.error is None
    assert capsys.readouterr().err == ""


def test_an_already_ticked_entry_is_a_successful_pinned_no_op(
    tmp_path: Path, monkeypatch
) -> None:
    """H3.1 req 7: an already-``[x]`` entry is ``succeeded`` + ``tick: already``, not skipped.

    Observable without a transcript: the stage record's status and its ``artifacts``
    marker, plus one ``run.log`` line naming the checkbox and the outcome. ``skipped`` is
    H3.2's word for a tick withheld behind red gates, so it must not appear here.
    """
    control, worktree, prompt = _located_layout(tmp_path)
    _write_roadmap(worktree, "E4.1", checked=True)
    original = (worktree / ROADMAP_REL).read_text(encoding="utf-8")
    _patch(monkeypatch)
    monkeypatch.setattr(implement_workflow, "run_stage", _NoTickStages())

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert (worktree / ROADMAP_REL).read_text(encoding="utf-8") == original
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    record = _stage_record(state, "update-roadmap")
    assert record.status == SUCCEEDED
    assert record.status != "skipped"
    assert record.artifacts.get("tick") == "already"
    assert record.error is None
    log = (run_dir(_runs_root(control), state.run_id) / "run.log").read_text(
        encoding="utf-8"
    )
    assert "roadmap E4.1: already `[x]`, file unchanged" in log


def test_a_tick_that_edits_any_other_line_fails_the_stage(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The byte-exact postcondition is fail-closed: exit 0 from the agent is not evidence."""
    control, worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(implement_workflow, "run_stage", _NeighbourEditStages())

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 1
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    record = _stage_record(state, "update-roadmap")
    assert record.status == FAILED
    assert "postcondition not met" in (record.error or "")
    assert "tick" not in record.artifacts
    assert "pr" not in [
        stage.name for stage in state.stages
    ], "I6 must not run after a failed tick"
    assert "stage update-roadmap failed" in capsys.readouterr().err


def test_zero_matching_roadmap_entries_refuses_before_the_stage(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """H3.1 req 5: an unresolvable entry is stderr + exit 2 before any stage runs."""
    control, worktree, prompt = _located_layout(tmp_path)
    _write_roadmap(worktree, "E4.9")  # no E4.1 entry in the located tree
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(task_prompt_path=prompt, **_roots(control), approve_all=True)

    assert code == 2
    assert recorder.names == []
    runs_root = _runs_root(control)
    assert not runs_root.exists() or list(runs_root.iterdir()) == []
    err = capsys.readouterr().err
    assert "roadmap tick refused" in err
    assert "no roadmap entry matches 03-E4.1" in err


def test_a_duplicate_roadmap_entry_refuses_before_the_stage(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A duplicate must refuse, not tick the first match ``find_task`` would return."""
    control, worktree, prompt = _located_layout(tmp_path)
    path = worktree / ROADMAP_REL
    duplicate = _roadmap_text() + "- [ ] **E4.1. A duplicate** <details>\n"
    path.write_text(duplicate, encoding="utf-8")
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(task_prompt_path=prompt, **_roots(control), approve_all=True)

    assert code == 2
    assert recorder.names == []
    err = capsys.readouterr().err
    assert "roadmap tick refused" in err
    assert "2 roadmap entries match 03-E4.1" in err
    # Nothing was ticked.
    assert path.read_text(encoding="utf-8") == duplicate


def test_the_tick_resolves_the_located_worktree_not_the_control_root(
    tmp_path: Path, monkeypatch
) -> None:
    """Design K1/H3.1: the entry comes from the tree the stages run in.

    The control root carries a *different* roadmap (its E4.1 already checked), so a stage
    that read the control root would record ``already`` and leave the worktree untouched.
    """
    control, worktree, prompt = _located_layout(tmp_path)
    _write_roadmap(control, "E4.1", checked=True)
    _patch(monkeypatch)
    monkeypatch.setattr(implement_workflow, "run_stage", _GateEvidenceStages())

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    record = _stage_record(state, "update-roadmap")
    assert record.artifacts.get("tick") == "flipped"
    # The located worktree's file (the one the stage edited) was ticked.
    assert "- [x] **E4.1. A fixture task**" in (
        worktree / ROADMAP_REL
    ).read_text(encoding="utf-8")


def test_the_tick_uses_the_configured_roadmap_directory_and_glob(
    tmp_path: Path, monkeypatch
) -> None:
    """D15: custom roadmap paths are resolved in the located worktree, not hardcoded."""
    control, worktree, prompt = _located_layout(tmp_path)
    custom = worktree / "planning" / "roadmaps" / "03 - Custom.md"
    custom.parent.mkdir(parents=True)
    custom.write_text(_roadmap_text(), encoding="utf-8")
    _write_config(
        control,
        "schema_version: 1\n"
        "paths:\n"
        "  roadmap_dir: planning/roadmaps\n"
        '  roadmap_glob: "[0-9]* - *.md"\n',
    )
    _patch(monkeypatch)
    # A relocated roadmap dir is a relocated *ignore* prefix: the evidence the prompts'
    # gate runs recorded names the resolved directory, not ``docs/tasks``.
    recorder = _GateEvidenceStages(
        tree=_evidence_tree(
            worktree,
            exclude=(_runs_root(control).parent,),
            ignore=(
                "docs/implementation-results",
                "docs/architecture",
                "planning/roadmaps",
                "docs/task-prompts",
            ),
        )
    )
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    tick = next(spec for spec in recorder.specs if spec.name == "update-roadmap")
    assert tick.variables == [str(custom.resolve()), "E4.1"]
    assert "- [x] **E4.1. A fixture task**" in custom.read_text(encoding="utf-8")
    # The default path remains untouched, proving the configured directory selected the file.
    assert "- [ ] **E4.1. A fixture task**" in (
        worktree / ROADMAP_REL
    ).read_text(encoding="utf-8")


def test_from_update_roadmap_validates_against_the_plan(
    tmp_path: Path, monkeypatch
) -> None:
    """H3.1 req 8/F1: ``--from update-roadmap`` is a known name, so it re-runs from it.

    H3.2: the resumed run's evidence is what lets the forced tick run — the recorded
    outcomes are read from the run state, which is the only place they come from.
    """
    control, worktree, prompt = _located_layout(tmp_path)
    exclude = (_runs_root(control).parent,)
    _patch(monkeypatch)
    runs_dir = _runs_root(control)
    state = create_run(
        runs_dir, control, "implement", label="03-E4.1", branch="03-E4.1"
    )
    directory = run_dir(runs_dir, state.run_id)
    stages_dir = directory / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)
    test_out = stages_dir / "test.out.txt"
    test_out.write_text("Test verdict: Pass\n", encoding="utf-8")
    for name in DEFAULT_ORDER[: DEFAULT_ORDER.index("update-roadmap")]:
        state.record_stage(
            StageRecord(
                name=name,
                agent="implementer",
                model="m",
                status=SUCCEEDED,
                # Q1.1: the verdict gate re-reads I2's recorded final message, so a resumed
                # run carries the passing declaration a real tester leaves behind.
                artifacts={"out": str(test_out)} if name == "test" else {},
            )
        )
    save(directory, state)
    _record_evidence(
        state, directory, tree=_evidence_tree(worktree, exclude=exclude), stage="record"
    )

    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        resume=True,
        from_stage="update-roadmap",
        approve_all=True,
    )

    assert code == 0
    assert recorder.names[0] == "update-roadmap"
    assert "impliment-task" not in recorder.names
    assert "test" not in recorder.names  # I2 is skipped; its recorded verdict still decides


def test_a_typoed_from_name_still_refuses_with_the_known_names(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The placeholder rendering keeps the F1 refusal intact (`build_plan` threading)."""
    control, prompt = _layout(tmp_path)
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), from_stage="update-roadmpa"
    )

    assert code == 2
    assert recorder.names == []
    err = capsys.readouterr().err
    assert "unknown stage `update-roadmpa`" in err
    assert "update-roadmap" in err  # the known-names list


# --------------------------------------------------------------------------- #
# H3.2: the tick only behind the run's own green evidence
# --------------------------------------------------------------------------- #


def _tick_log(control: Path, state) -> str:
    return (run_dir(_runs_root(control), state.run_id) / "run.log").read_text(
        encoding="utf-8"
    )


def test_the_e6_1_replay_withholds_the_tick_behind_a_red_suite(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Done-when: green build/doctor/agents/prompts + a red ``suite`` leaves the box alone.

    The run that this epic exists for flipped E6.1's box and then reverted it, because the
    decision was the agent's. Here the workflow decides before the agent is ever invoked:
    the stage is recorded ``skipped`` naming ``suite``, the roadmap file is byte-identical,
    and the run still exits 0 — the red gate already decided the run, not the tick.
    """
    control, worktree, prompt = _located_layout(tmp_path)
    tree = _evidence_tree(worktree, exclude=(_runs_root(control).parent,))
    before = (worktree / ROADMAP_REL).read_text(encoding="utf-8")
    _patch(monkeypatch)
    recorder = _GateEvidenceStages(failing={"suite"}, tree=tree)
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    # No agent was given the chance to claim the tick, and the file never moved.
    assert "update-roadmap" not in recorder.names
    assert (worktree / ROADMAP_REL).read_text(encoding="utf-8") == before
    assert "- [x] **E4.1. A fixture task**" not in before

    state = implement_workflow.list_runs(_runs_root(control))[-1]
    record = _stage_record(state, "update-roadmap")
    assert record.status == SKIPPED
    assert record.agent == "recorder"
    # The same agent resolution `run_stage` applies, recorded on the skip (req 4).
    assert record.model == _AGENTS["recorder"].qualified_model
    assert record.error is None
    # Settle never ran either: no tick marker was stamped onto a stage that never ran.
    assert "tick" not in record.artifacts
    reason = record.artifacts[SKIP_REASON_KEY]
    assert "suite" in reason
    assert tree in reason
    # The rest of the run is untouched: it succeeded, committed nothing, needs no resume.
    assert state.status == SUCCEEDED
    assert state.resume == {"next_stage": None}
    assert "pr" in recorder.names
    assert state.pr.get("number") == 42
    assert "roadmap E4.1: already" not in _tick_log(control, state)
    out = capsys.readouterr()
    assert "I7 update-roadmap [skipped]" in out.out
    assert "skipped: " in out.out
    assert "stage update-roadmap failed" not in out.err


def test_green_evidence_still_withholds_the_tick_against_a_recorded_unmet_verdict(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """PR #282: every gate green, and the task's own build results conclude unmet.

    H3.2 asks whether the run's gates passed, which is not the same question as "does the
    recorded proof agree the task is done". PR #282 had green gates *and* a build-results
    document concluding the fixture's contract suite failed, so the tick was a completion
    claim the run's own recording contradicted — and the stage has no legal repair (its
    postcondition allows one checkbox and nothing else). The tick is withheld before any
    agent is invoked, the document and line are named, and the run still exits 0.
    """
    control, worktree, prompt = _located_layout(tmp_path)
    tree = _evidence_tree(worktree, exclude=(_runs_root(control).parent,))
    results = worktree / "docs" / "implementation-results" / "03-E4.1"
    results.mkdir(parents=True)
    (results / "build-results.md").write_text(
        '# Build Results\n\nConsequently the task\'s "Done when" is **not** met on this '
        "tree: the fixture's contract suite does not pass.\n",
        encoding="utf-8",
    )
    before = (worktree / ROADMAP_REL).read_text(encoding="utf-8")
    _patch(monkeypatch)
    # Green evidence: no gate key fails, so H3.2 alone would let the tick run.
    recorder = _GateEvidenceStages(tree=tree)
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert "update-roadmap" not in recorder.names
    assert (worktree / ROADMAP_REL).read_text(encoding="utf-8") == before
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    record = _stage_record(state, "update-roadmap")
    assert record.status == SKIPPED
    assert record.error is None
    assert "tick" not in record.artifacts
    reason = record.artifacts[SKIP_REASON_KEY]
    assert "docs/implementation-results/03-E4.1/build-results.md:3" in reason
    assert "Done-when is unmet" in reason
    assert state.status == SUCCEEDED
    assert "I7 update-roadmap [skipped]" in capsys.readouterr().out


def test_green_evidence_ticks_the_box_exactly_once(
    tmp_path: Path, monkeypatch
) -> None:
    """The same replay with ``suite`` green flips the one checkbox, once."""
    control, worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    recorder = _GateEvidenceStages(failing=set())
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert recorder.names.count("update-roadmap") == 1
    text = (worktree / ROADMAP_REL).read_text(encoding="utf-8")
    assert text.count("- [x] **E4.1. A fixture task**") == 1
    # Nothing else moved: the neighbour stays unticked.
    assert "- [ ] **E9.9. A neighbour task**" in text
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    record = _stage_record(state, "update-roadmap")
    assert record.status == SUCCEEDED
    assert record.artifacts.get("tick") == "flipped"
    assert state.status == SUCCEEDED


def test_a_run_with_no_recorded_gate_outcomes_skips_with_the_absence(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A run whose gates recorded nothing has nothing to cite — never "assume green"."""
    control, worktree, prompt = _located_layout(tmp_path)
    before = (worktree / ROADMAP_REL).read_text(encoding="utf-8")
    tree = _evidence_tree(worktree, exclude=(_runs_root(control).parent,))
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert (worktree / ROADMAP_REL).read_text(encoding="utf-8") == before
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    record = _stage_record(state, "update-roadmap")
    assert record.status == SKIPPED
    reason = record.artifacts[SKIP_REASON_KEY]
    assert "no evidence" in reason
    assert "no gate outcome is recorded" in reason
    assert tree in reason
    assert state.gate_outcomes == []
    assert "I7 update-roadmap [skipped]" in capsys.readouterr().out


def test_a_parallel_group_member_naming_the_tick_is_withheld_without_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    """Req 4's trap: a repo-declared group may contain ``update-roadmap``.

    Group members bypass ``execute()`` (they are submitted to the pool directly), so the
    evidence check has to sit on the member path too — otherwise a group would tick with no
    evidence at all.
    """
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control,
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    parallel_groups:\n"
        "      - [test, update-roadmap]\n",
    )
    before = (worktree / ROADMAP_REL).read_text(encoding="utf-8")
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True, parallel=True
    )

    assert code == 0
    assert "update-roadmap" not in recorder.names
    assert "test" in recorder.names
    assert (worktree / ROADMAP_REL).read_text(encoding="utf-8") == before
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert _stage_record(state, "update-roadmap").status == SKIPPED


def test_a_parallel_group_member_naming_the_tick_ticks_behind_green_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    """The member path's green branch: recorded evidence lets the grouped tick run."""
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control,
        "schema_version: 1\n"
        "workflows:\n"
        "  implement:\n"
        "    parallel_groups:\n"
        "      - [update-roadmap, update-traceability]\n",
    )
    exclude = (_runs_root(control).parent,)
    _patch(monkeypatch)
    runs_dir = _runs_root(control)
    state = create_run(
        runs_dir, control, "implement", label="03-E4.1", branch="03-E4.1"
    )
    directory = run_dir(runs_dir, state.run_id)
    save(directory, state)
    _record_evidence(
        state, directory, tree=_evidence_tree(worktree, exclude=exclude), stage="record"
    )
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt,
        **_roots(control),
        resume=True,
        approve_all=True,
        parallel=True,
    )

    assert code == 0
    assert "update-roadmap" in recorder.names
    state = implement_workflow.list_runs(runs_dir)[-1]
    assert _stage_record(state, "update-roadmap").artifacts.get("tick") == "flipped"
    assert "- [x] **E4.1. A fixture task**" in (
        worktree / ROADMAP_REL
    ).read_text(encoding="utf-8")


def test_a_second_green_run_on_an_already_ticked_box_is_a_no_op(
    tmp_path: Path, monkeypatch
) -> None:
    """Green evidence twice: the first run flips, the second records ``tick: already``.

    It also proves req 3's ``roadmap_dir`` scope: the first run's flip is *uncommitted*, so
    the second run's tree contains it — and the evidence still matches, because the tick's
    own edit is inside the ignored document write-target.
    """
    control, worktree, prompt = _located_layout(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(implement_workflow, "run_stage", _GateEvidenceStages())

    assert (
        implement_workflow.run(
            task_prompt_path=prompt, **_roots(control), approve_all=True
        )
        == 0
    )
    after_first = (worktree / ROADMAP_REL).read_text(encoding="utf-8")
    first = implement_workflow.list_runs(_runs_root(control))[-1]
    assert _stage_record(first, "update-roadmap").artifacts.get("tick") == "flipped"

    monkeypatch.setattr(implement_workflow, "run_stage", _GateEvidenceStages())
    assert (
        implement_workflow.run(
            task_prompt_path=prompt, **_roots(control), approve_all=True
        )
        == 0
    )

    # The run id is second-granular, so two runs this close share a run directory; the
    # observable is the second run's record, which supersedes the first by stage name.
    second = implement_workflow.list_runs(_runs_root(control))[-1]
    assert second.stage("update-roadmap") is not None
    record = _stage_record(second, "update-roadmap")
    assert record.status == SUCCEEDED
    assert record.status != SKIPPED
    assert record.artifacts.get("tick") == "already"
    assert record.error is None
    # Byte-identical: a no-op is a no-op, and the box was never ticked twice.
    assert (worktree / ROADMAP_REL).read_text(encoding="utf-8") == after_first
    assert after_first.count("- [x] **E4.1. A fixture task**") == 1


# --------------------------------------------------------------------------- #
# S1.1: I3 is path-scoped (`when=WHEN_PATHS_CHANGED` + the declared `when_paths`)
# --------------------------------------------------------------------------- #

#: Pinned property-test parameters (``hypothesis`` is not a dependency — AGENTS.md §15 —
#: so the sweep is a fixed seed and an explicit run count).
PATH_GATE_PROPERTY_SEED = 8_311
PATH_GATE_PROPERTY_NUM_RUNS = 150


def test_the_path_gate_rule_matches_exact_paths_and_directory_members() -> None:
    """S1.1 req 7: ``path == prefix`` or ``path.startswith(prefix + "/")`` — nothing else.

    One hand-calculated vector per behaviour path. ``None`` means *run*; a string is the
    skip reason.
    """
    reason = implement_workflow.paths_changed_reason

    # A declared file: only the exact path counts (a sibling name sharing its stem does not).
    assert reason(["docs/rules.md"], ["docs/rules.md"]) is None
    assert reason(["docs/rules.md.bak"], ["docs/rules.md"]) is not None
    # A declared directory: any path inside it counts, the directory itself included.
    assert reason(["docs/rules/a.py"], ["docs/rules"]) is None
    assert reason(["docs/rules/deep/b.py"], ["docs/rules"]) is None
    assert reason(["docs/rules"], ["docs/rules"]) is None
    # A prefix is not a substring: the sibling `docs/rules-deep` is NOT inside `docs/rules`.
    assert reason(["docs/rules-deep/a.py"], ["docs/rules"]) is not None
    # No touch at all.
    skipped = reason(["src/app.py"], ["docs/traceability", "docs/rules"])
    assert skipped is not None
    assert "docs/rules, docs/traceability" in skipped
    # Empty declared set: the toolkit default, i.e. unconditional.
    assert reason(["src/app.py"], []) is None
    # An empty, successfully computed change set is different from an unknown one: it
    # proves that no declared prefix was touched, so the stage is withheld.
    assert reason([], ["docs/rules"]) is not None
    # "Cannot prove" (unresolvable base) is never a skip.
    assert reason(None, ["docs/rules"]) is None
    # Normalisation of the declaration: `./x` and a trailing slash are the same prefix.
    assert reason(["docs/rules/a.py"], ["./docs/rules/"]) is None
    assert reason(["docs/rules/a.py"], ["docs/rules/"]) is None


def test_the_path_gate_rule_is_pure() -> None:
    """S1.1 req 7: same inputs, same answer, no mutation of either list."""
    changed = ["docs/rules/a.py"]
    declared = ["./docs/rules/"]
    changed_before, declared_before = list(changed), list(declared)

    first = implement_workflow.paths_changed_reason(changed, declared)
    second = implement_workflow.paths_changed_reason(changed, declared)

    assert first == second is None
    assert changed == changed_before
    assert declared == declared_before


def test_the_path_gate_rule_performs_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """S1.1 req 5/req 7: the decision is a pure rule; the change set is the caller's I/O."""

    def _explode(*args, **kwargs):
        raise AssertionError("paths_changed_reason must perform no I/O")

    monkeypatch.setattr(builtins, "open", _explode)
    monkeypatch.setattr(Path, "read_text", _explode)
    monkeypatch.setattr(Path, "write_text", _explode)
    monkeypatch.setattr(implement_workflow.git, "changed_paths", _explode)
    monkeypatch.setattr(implement_workflow.git, "untracked_paths", _explode)

    assert implement_workflow.paths_changed_reason(["docs/a"], ["docs/a"]) is None


def _random_path(rng: random.Random) -> str:
    """A plausible repo-relative path from the sweep's alphabet (the seed's generator)."""
    return "/".join(
        rng.choice(["docs", "src", "rules", "a.py", "b.md", "tests"])
        for _ in range(rng.randint(1, 3))
    )


def test_the_path_gate_property_holds_for_generated_change_sets() -> None:
    """Property (seeded, ``numRuns`` pinned above): the rule and its monotonicity hold.

    Invariants for every generated (change set, declaration): an empty declaration and an
    unknown change set always run; otherwise "runs" is exactly "some changed path touches a
    declared prefix"; a skip's reason names every canonical prefix; adding a changed path
    never turns a run into a skip; and neither input is mutated. Both outcomes occur in the
    sample, so the sweep is not vacuous. Same seed + same count => same cases everywhere.
    """
    rng = random.Random(PATH_GATE_PROPERTY_SEED)
    skipped = ran = 0

    for _ in range(PATH_GATE_PROPERTY_NUM_RUNS):
        declared = rng.sample(
            ["docs/a", "docs/b/c", "src/rules", "./tests/"], rng.randint(0, 3)
        )
        changed: list[str] | None = (
            None
            if rng.random() < 0.15
            else [_random_path(rng) for _ in range(rng.randint(0, 6))]
        )
        declared_before = list(declared)
        changed_before = None if changed is None else list(changed)

        reason = implement_workflow.paths_changed_reason(changed, declared)

        assert declared == declared_before
        assert changed == changed_before

        if changed is None or not declared:
            assert reason is None
            ran += 1
            continue

        prefixes = verification.normalise_ignore(declared)
        touches = any(
            path == prefix or path.startswith(f"{prefix}/")
            for path in changed
            for prefix in prefixes
        )
        assert (reason is None) is touches, (changed, declared)

        if reason is None:
            ran += 1
            # Metamorphic: more changed paths can only ever add a touch, so a run stays one.
            assert (
                implement_workflow.paths_changed_reason(
                    [*changed, _random_path(rng)], declared
                )
                is None
            )
        else:
            skipped += 1
            for prefix in prefixes:
                assert prefix in reason, prefix

    assert ran and skipped, (ran, skipped)


def _declared_implement_stages_with_when_paths(
    when_paths: list[str], parallel_group: list[str] | None = None
) -> str:
    """The full declared implement list, with I3 declaring ``when_paths`` (S1.1).

    A declared list replaces the toolkit's wholesale (§3.4), so every id is named; only I3
    carries the path set. ``parallel_group`` optionally declares one concurrency group.
    """
    lines = ["schema_version: 1", "workflows:", "  implement:", "    stages:"]
    for stage_id in IMPLEMENT_STAGE_IDS:
        lines.append(f"      - id: {stage_id}")
        if stage_id == "I3":
            lines.append("        when_paths:")
            for path in when_paths:
                lines.append(f'          - "{path}"')
    if parallel_group is not None:
        lines.append("    parallel_groups:")
        lines.append("      - [" + ", ".join(parallel_group) + "]")
    return "\n".join(lines) + "\n"


def test_a_change_set_touching_no_declared_when_path_skips_i3(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Done-when: the stage is recorded ``skipped``, never dispatched, and the run succeeds.

    The fixture's change set is the committed task prompt and roadmap file; a declaration
    naming a directory it does not touch proves the skip. The reason names the declared
    prefixes, ``error`` stays unset (a skip is not a failure) and ``state.status`` is
    ``SUCCEEDED`` with no resume hint — while the rest of the chain, ``I7`` included, runs.
    """
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control, _declared_implement_stages_with_when_paths(["docs/traceability"])
    )
    _patch(monkeypatch)
    recorder = _GateEvidenceStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert "update-traceability" not in recorder.names
    # No agent was given the chance to run it: every other stage still did.
    assert [name for name in recorder.names if name != "update-traceability"] == [
        name for name in DEFAULT_ORDER if name != "update-traceability"
    ]

    state = implement_workflow.list_runs(_runs_root(control))[-1]
    record = _stage_record(state, "update-traceability")
    assert record.status == SKIPPED
    assert record.agent == "implementer"
    assert record.model == _AGENTS["implementer"].qualified_model
    assert record.error is None
    reason = record.artifacts[SKIP_REASON_KEY]
    assert "docs/traceability" in reason
    assert "no changed path matches the declared when_paths" in reason
    # A cost-control skip, not a failure: the run succeeded and needs no resume.
    assert state.status == SUCCEEDED
    assert state.resume == {"next_stage": None}
    # The tick still ran: the skip is I3's alone.
    assert "update-roadmap" in recorder.names
    assert state.pr.get("number") == 42
    out = capsys.readouterr()
    assert "I3 update-traceability [skipped]" in out.out
    assert "stage update-traceability failed" not in out.err


def test_the_run_state_root_is_excluded_from_the_path_change_set(
    tmp_path: Path, monkeypatch
) -> None:
    """S1.1 req 6: the workflow's own state files cannot make I3 appear relevant.

    Put the unignored state root inside the located worktree and declare that root as the
    trigger. The run creates state files before I3 is evaluated; correct exclusion makes
    this a genuine no-touch skip rather than a self-triggered dispatch.
    """
    control, worktree, prompt = _located_layout(tmp_path)
    state_root = worktree / ".aidw-local-state"
    _write_config(control, _declared_implement_stages_with_when_paths([state_root.name]))
    _patch(monkeypatch)
    recorder = _GateEvidenceStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)
    roots = _roots(control)
    roots["workspace"] = WorkspacePaths.resolve(
        TargetRepo.resolve(control), state_dir_override=state_root
    )

    code = implement_workflow.run(
        task_prompt_path=prompt, **roots, approve_all=True
    )

    assert code == 0
    assert "update-traceability" not in recorder.names
    state = implement_workflow.list_runs(roots["workspace"].state_root / "runs")[-1]
    record = _stage_record(state, "update-traceability")
    assert record.status == SKIPPED
    assert state_root.name in record.artifacts[SKIP_REASON_KEY]


def test_a_change_set_touching_a_declared_prefix_runs_i3(
    tmp_path: Path, monkeypatch
) -> None:
    """Done-when: one touched prefix — here a directory prefix of a committed change — runs it."""
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control, _declared_implement_stages_with_when_paths(["docs/task-prompts"])
    )
    _patch(monkeypatch)
    recorder = _GateEvidenceStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert "update-traceability" in recorder.names
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    record = _stage_record(state, "update-traceability")
    assert record.status == SUCCEEDED
    assert SKIP_REASON_KEY not in record.artifacts


def test_an_untracked_change_under_a_declared_prefix_runs_i3(
    tmp_path: Path, monkeypatch
) -> None:
    """S1.1 req 6: the change set is ``changed_paths`` **plus** ``untracked_paths``.

    The touched file is never committed, so a change set built from ``git diff`` alone would
    skip a stage the run does have work for.
    """
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control, _declared_implement_stages_with_when_paths(["docs/traceability"])
    )
    (worktree / "docs" / "traceability").mkdir(parents=True)
    (worktree / "docs" / "traceability" / "notes.md").write_text(
        "traceability notes\n", encoding="utf-8"
    )
    _patch(monkeypatch)
    recorder = _GateEvidenceStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert "update-traceability" in recorder.names
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert _stage_record(state, "update-traceability").status == SUCCEEDED


def test_an_undeclared_when_paths_runs_i3_unconditionally(
    tmp_path: Path, monkeypatch
) -> None:
    """Done-when: a repo that declares no ``when_paths`` keeps today's behaviour.

    The declared list carries every id but no path set, so the spec's empty default must
    leave the stage unconditional — the toolkit ships no default path set (§7.1).
    """
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(control, _declared_implement_stages())
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert "update-traceability" in recorder.names
    spec = next(spec for spec in recorder.specs if spec.name == "update-traceability")
    assert spec.when == "paths-changed"
    assert spec.when_paths == ()
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert _stage_record(state, "update-traceability").status == SUCCEEDED


def test_an_unresolvable_base_runs_i3_instead_of_skipping(
    tmp_path: Path, monkeypatch
) -> None:
    """Done-when: ``changed_paths`` returning ``None`` is "cannot prove" — run, not skip.

    The declared path set does not touch anything, so a workflow that treated ``None`` as an
    empty change set would withhold a stage that should run. Only the base resolution is
    faked; everything else is the real run path.
    """
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control, _declared_implement_stages_with_when_paths(["docs/traceability"])
    )
    _patch(monkeypatch)
    monkeypatch.setattr(
        implement_workflow.git, "changed_paths", lambda repo, base: None
    )
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True
    )

    assert code == 0
    assert "update-traceability" in recorder.names
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    assert _stage_record(state, "update-traceability").status == SUCCEEDED


def test_a_parallel_group_member_naming_i3_is_withheld_on_the_member_path(
    tmp_path: Path, monkeypatch
) -> None:
    """S1.1 req 5's trap: group members bypass ``execute()``, so both paths must check.

    A repo-declared group may legally name ``update-traceability``; a check only in
    ``execute()`` would run I3 whenever the group was used.
    """
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control,
        _declared_implement_stages_with_when_paths(
            ["docs/traceability"], parallel_group=["test", "update-traceability"]
        ),
    )
    _patch(monkeypatch)
    recorder = _GateEvidenceStages()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), approve_all=True, parallel=True
    )

    assert code == 0
    assert "update-traceability" not in recorder.names
    assert "test" in recorder.names
    state = implement_workflow.list_runs(_runs_root(control))[-1]
    record = _stage_record(state, "update-traceability")
    assert record.status == SKIPPED
    assert "docs/traceability" in record.artifacts[SKIP_REASON_KEY]


def test_dry_run_plans_i3_with_its_declared_paths_and_evaluates_nothing(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """S1.1 req 5: ``--dry-run`` plans the stage (with its path set) and skips nothing.

    The dry-run path returns before the dispatch loop, so no change set is computed and no
    stage is withheld even though the declared prefix matches nothing.
    """
    control, worktree, prompt = _located_layout(tmp_path)
    _write_config(
        control, _declared_implement_stages_with_when_paths(["docs/traceability"])
    )
    _patch(monkeypatch)
    recorder = _Recorder()
    monkeypatch.setattr(implement_workflow, "run_stage", recorder)

    code = implement_workflow.run(
        task_prompt_path=prompt, **_roots(control), dry_run=True
    )

    assert code == 0
    assert recorder.names == DEFAULT_ORDER
    spec = next(spec for spec in recorder.specs if spec.name == "update-traceability")
    assert spec.when == "paths-changed"
    assert spec.when_paths == ("docs/traceability",)
    out = capsys.readouterr().out
    assert "I3 update-traceability [succeeded] (planned)" in out
    assert "I3 update-traceability [skipped]" not in out
