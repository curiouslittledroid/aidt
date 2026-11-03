"""Contract and metamorphic tests for the run-path plan builder (E4.3).

:func:`aidw.runner.plan_stages` is the **only** run-path plan builder (EXTRACTION.md §3.5,
D2): every workflow's stage list is ``aidw.stage_registry.expand(...)`` mapped to
:class:`aidw.runner.StageSpec` through :func:`aidw.runner.resolve_prompt`, with the target
repo's declared ``prompt:`` overlay applied (D14). These tests are that mapping's executable
specification:

* one hand-calculated vector per workflow (design §8.1–§8.5), pinned literally — names,
  agents, resolved prompt files, variables, ``extra`` and the retained stage ``id`` — so the
  five workflow dry-run baselines stay byte-identical;
* the D14 overlay: ``explicit_prompt`` set, the declared path resolved, precedence over the
  target shadow, and the whole-list override treated as an overlay (never as a mirror of the
  registry's order/size);
* the deferred-field warnings of E4.3 (``agent`` → E4.6; ``enabled: false`` and repo-added
  ids → E4.5): one stderr line per entry, naming the workflow, the id and every reason;
* fail-closed and purity: a declared-but-missing prompt raises, no shadow/toolkit fallback,
  and neither the config nor the registry defaults are mutated.

The invariant sweep at the end is the metamorphic half: for all five workflows, the builder's
output is exactly the registry's expansion (E4.3 req 1) and a declared overlay never changes
a plan's shape — only which prompt file a stage resolves to. ``hypothesis`` is not a
dependency, so the sweep enumerates the small input space deterministically; the "seed" is
the enumeration itself (the same convention as ``tests/test_stage_registry.py``, AGENTS.md's
no-new-deps rule).
"""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from aidw import stage_registry
from aidw.findings import MANIFEST_EXTRA, ParsedFinding
from aidw.log import RunLogger
from aidw.paths import ToolkitPaths
from aidw.runner import StageSpec, plan_stages, run_stage
from aidw.stage_registry import DEFAULTS, FixBatch
from aidw.state import create_run, run_dir
from aidw.target_config import ResolvedConfig, TargetConfig, load_target_config, resolve_config

TOOLKIT = ToolkitPaths.resolve()
PROMPT_REL = "docs/task-prompts/03-E4.1-prompt.md"
BRANCH = "03-E4.1"
TASK_ID = "03-E4.1"
PR = 17
MANIFEST = "artifacts/review-manifest.json"


# --------------------------------------------------------------------------- #
# Fixtures: a target root, optionally carrying a declared config (§3.4)
# --------------------------------------------------------------------------- #


def _target(tmp_path: Path, config_text: str | None = None) -> Path:
    """A target repo root with ``docs/task-prompts/`` and an optional ``aidw/config.yaml``."""
    root = tmp_path / "target"
    (root / "docs" / "task-prompts").mkdir(parents=True, exist_ok=True)
    if config_text is not None:
        (root / "aidw").mkdir(parents=True, exist_ok=True)
        (root / "aidw" / "config.yaml").write_text(config_text, encoding="utf-8")
    return root


def _resolved(root: Path) -> ResolvedConfig:
    """The real load → resolve path, so the tests exercise the config shapes the loader emits."""
    declared = load_target_config(root / "aidw" / "config.yaml")
    assert declared.issues == [], declared.issues
    return resolve_config(declared)


def _defaults() -> ResolvedConfig:
    """Pure toolkit defaults: a target repo with no ``aidw/`` folder (§3.4)."""
    return resolve_config(TargetConfig())


def _write_prompt(root: Path, rel: str, text: str = "# override\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path.resolve()


def _plan(
    workflow: str,
    *,
    config: ResolvedConfig | None = None,
    root: Path | None = None,
    **fields: object,
) -> list[StageSpec]:
    return plan_stages(
        workflow,
        config=config if config is not None else _defaults(),
        toolkit_root=TOOLKIT.root,
        target_root=root if root is not None else Path("/nonexistent-target"),
        **fields,
    )


def _shape(specs: list[StageSpec]) -> list[tuple[str, str, str, list[str], str]]:
    """The plan's shape: everything an overlay must never change."""
    return [
        (spec.id, spec.name, spec.agent_id, spec.variables, spec.extra) for spec in specs
    ]


def _toolkit_prompt(name: str) -> Path:
    return (TOOLKIT.prompts_dir / name).resolve()


# --------------------------------------------------------------------------- #
# One hand-calculated vector per workflow (design §8.1–§8.5)
# --------------------------------------------------------------------------- #


def test_implement_plan_is_the_six_registry_stages(tmp_path: Path) -> None:
    root = _target(tmp_path)
    specs = _plan(
        "implement",
        root=root,
        prompt_rel=PROMPT_REL,
        branch=BRANCH,
        task_id=TASK_ID,
        base_branch="develop",
    )

    assert [
        (spec.id, spec.name, spec.agent_id, spec.prompt, spec.variables)
        for spec in specs
    ] == [
        ("I1", "impliment-task", "implementer", _toolkit_prompt("impliment-task.md"),
         [PROMPT_REL]),
        ("I2", "test", "tester", _toolkit_prompt("test.md"), []),
        ("I3", "update-traceability", "implementer",
         _toolkit_prompt("update-traceability.md"), [BRANCH]),
        ("I4", "update-architecture", "implementer",
         _toolkit_prompt("update-architecture.md"), [BRANCH, "develop"]),
        ("I5", "record-implementation-results", "recorder",
         _toolkit_prompt("record-implementation-results.md"), [BRANCH]),
        ("I6", "pr", "pr-publisher", _toolkit_prompt("pr.md"), [TASK_ID]),
    ]
    # The `extra` is part of the plan: I2's test context, rendered for these fields.
    assert specs[1].extra == stage_registry.TEST_CONTEXT_EXTRA.format(
        task_id=TASK_ID, branch=BRANCH, prompt_rel=PROMPT_REL
    )
    assert [spec.extra for spec in specs if spec.id != "I2"] == [""] * 5
    # A pure-defaults repo declares no overlay, so no stage carries an explicit path.
    assert all(spec.explicit_prompt is None for spec in specs)
    assert all(spec.workflow == "implement" for spec in specs)
    assert all(isinstance(spec.variables, list) for spec in specs)


def test_review_plan_is_r1_plus_the_r2_manifest_pointer(tmp_path: Path) -> None:
    root = _target(tmp_path)
    specs = _plan(
        "review", root=root, pr=PR, manifest_rel=MANIFEST, findings=True
    )

    assert [
        (spec.id, spec.name, spec.agent_id, spec.prompt, spec.variables, spec.extra)
        for spec in specs
    ] == [
        ("R1", "code-review", "code-reviewer", _toolkit_prompt("code-review.md"), [], ""),
        (
            "R2",
            "review-findings-to-github",
            "review-publisher",
            _toolkit_prompt("review-findings-to-github.md"),
            [str(PR)],
            MANIFEST_EXTRA.format(manifest_rel=MANIFEST),
        ),
    ]


def test_fix_plan_is_the_approval_plus_one_iteration(tmp_path: Path) -> None:
    root = _target(tmp_path)
    specs = _plan(
        "fix",
        root=root,
        pr=PR,
        round_index=1,
        iteration=1,
        manifest_rel="artifacts/iter1-review-manifest.json",
    )

    assert [spec.id for spec in specs] == ["A1", "F1", "F2", "F3", "F4"]
    assert [spec.name for spec in specs] == [
        "round1-approve-review-followups",
        "iter1-fix-next-review-followup",
        "iter1-test",
        "iter1-code-review",
        "iter1-review-findings-to-github",
    ]
    assert specs[2].extra == stage_registry.FIX_TEST_CONTEXT_EXTRA.format(
        pr=PR, iteration=1
    )
    # F4's pointer names *this* iteration's manifest, the value a real run writes.
    assert specs[4].extra == MANIFEST_EXTRA.format(
        manifest_rel="artifacts/iter1-review-manifest.json"
    )
    assert [spec.variables for spec in specs] == [[str(PR)], [str(PR)], [], [], [str(PR)]]
    # The approval postcondition is workflow-side: the plan never carries one.
    assert all(spec.verify is None for spec in specs)


def test_approve_plan_is_the_single_a1_stage(tmp_path: Path) -> None:
    root = _target(tmp_path)
    specs = _plan("approve", root=root, pr=PR)

    assert [
        (spec.id, spec.name, spec.agent_id, spec.prompt, spec.variables, spec.extra)
        for spec in specs
    ] == [
        (
            "A1",
            "approve-review-followups",
            "review-approver",
            _toolkit_prompt("approve-review-followups.md"),
            [str(PR)],
            "",
        )
    ]


def test_prompt_plan_without_rounds_is_author_and_one_review(tmp_path: Path) -> None:
    """The prompt loop's dry-run baseline: ``rounds=()`` (unchanged, req 6)."""
    root = _target(tmp_path)
    specs = plan_stages(
        "prompt",
        config=_defaults(),
        toolkit_root=TOOLKIT.root,
        target_root=root,
        phase="03",
        epic="E4",
        task="E4.1",
        rel=PROMPT_REL,
        max_revisions=3,
        rounds=(),
    )

    assert [(spec.id, spec.name, spec.agent_id, spec.prompt, spec.variables) for spec in specs] == [
        ("P1", "task-prompt", "task-author", _toolkit_prompt("task-prompt.md"),
         ["03", "E4", "E4.1"]),
        ("P2", "task-review-1", "task-reviewer", _toolkit_prompt("task-review.md"),
         [PROMPT_REL]),
    ]
    # Round 1 is unprimed by the registry: no delta brief, no static extra.
    assert [spec.extra for spec in specs] == ["", ""]


def test_prompt_plan_with_a_batch_carries_the_fix_stage_and_reconcile(
    tmp_path: Path,
) -> None:
    """One accumulated batch expands to that round's fix stage plus its reconcile (L3.4)."""
    root = _target(tmp_path)
    finding = ParsedFinding(
        priority="must-fix",
        confidence=4,
        what_found="what",
        why_it_matters="why",
        trigger_and_effect="trigger",
        where="f.py",
        suggested_fix="fix",
    )
    specs = plan_stages(
        "prompt",
        config=_defaults(),
        toolkit_root=TOOLKIT.root,
        target_root=root,
        phase="03",
        epic="E4",
        task="E4.1",
        rel=PROMPT_REL,
        max_revisions=3,
        rounds=(FixBatch(review_text="r", blocking=(finding,)),),
    )

    assert [spec.name for spec in specs] == [
        "task-prompt",
        "task-review-1",
        "task-review-fixes-1-1",
        "task-review-reconcile-1",
        "task-review-2",
    ]
    fix, reconcile = specs[2], specs[3]
    assert fix.id == stage_registry.PROMPT_FIX_BLOCKING
    assert fix.agent_id == "task-fixer"
    assert fix.prompt == _toolkit_prompt("task-review-fixes.md")
    assert fix.extra.startswith("## Review finding 1 of 1 to address")
    # The reconcile body is runtime text (whole review + real diff), so the plan carries the
    # marker only — `StageSpec` has no `brief` field by design (req 5).
    assert reconcile.id == stage_registry.PROMPT_RECONCILE
    assert reconcile.extra == ""


# --------------------------------------------------------------------------- #
# The D14 explicit-path overlay (§3.4 precedence level 1)
# --------------------------------------------------------------------------- #

#: §3.4's own example: a repo-declared stage naming an explicit prompt path.
OVERLAY_CONFIG = """\
schema_version: 1
workflows:
  implement:
    stages:
      - id: I3
        prompt: aidw/prompts/update-traceability.md
"""


def test_declared_prompt_sets_explicit_prompt_and_resolves_it(tmp_path: Path) -> None:
    root = _target(tmp_path, OVERLAY_CONFIG)
    declared = _write_prompt(root, "aidw/prompts/update-traceability.md")

    specs = _plan(
        "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
        branch=BRANCH, task_id=TASK_ID,
    )

    by_id = {spec.id: spec for spec in specs}
    assert by_id["I3"].explicit_prompt == "aidw/prompts/update-traceability.md"
    assert by_id["I3"].prompt == declared
    # Every other stage keeps the toolkit default and no explicit path.
    for stage_id in ("I1", "I2", "I4", "I5", "I6"):
        assert by_id[stage_id].explicit_prompt is None
        assert by_id[stage_id].prompt.parent == TOOLKIT.prompts_dir


def test_declared_prompt_beats_a_same_named_target_shadow(tmp_path: Path) -> None:
    """D14: the explicit path wins over filename shadowing, which still applies otherwise."""
    root = _target(tmp_path, OVERLAY_CONFIG)
    declared = _write_prompt(root, "aidw/prompts/update-traceability.md", "explicit\n")
    shadowed = _write_prompt(root, "aidw/prompts/test.md", "shadow\n")

    specs = _plan(
        "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
        branch=BRANCH, task_id=TASK_ID,
    )
    by_id = {spec.id: spec for spec in specs}

    assert by_id["I3"].prompt == declared
    # No overlay for I2, so level 2 applies: the target shadow resolves.
    assert by_id["I2"].prompt == shadowed
    assert by_id["I2"].explicit_prompt is None


def test_declared_prompt_override_is_rendered_by_a_dry_run_stage(
    tmp_path: Path,
) -> None:
    """D14: the resolved override reaches the user-visible rendered dry-run prompt."""
    root = _target(tmp_path, OVERLAY_CONFIG)
    declared = _write_prompt(root, "aidw/prompts/update-traceability.md", "# explicit prompt\n")
    (root / "docs" / "task-prompts" / "03-E4.1-prompt.md").write_text(
        "# task\n", encoding="utf-8"
    )
    (spec,) = [
        spec
        for spec in _plan(
            "implement",
            config=_resolved(root),
            root=root,
            prompt_rel=PROMPT_REL,
            branch=BRANCH,
            task_id=TASK_ID,
        )
        if spec.id == "I3"
    ]
    assert spec.prompt == declared

    runs_root = tmp_path / "runs"
    state = create_run(runs_root, root, "implement", label="override")
    record = run_stage(
        spec,
        repo_root=root,
        toolkit_root=TOOLKIT.root,
        state=state,
        logger=RunLogger(run_dir(runs_root, state.run_id)),
        dry_run=True,
        runs_root=runs_root,
    )

    assert record.status == "succeeded"
    rendered = (run_dir(runs_root, state.run_id) / "prompts" / "update-traceability.rendered.md").read_text(
        encoding="utf-8"
    )
    assert rendered == "# explicit prompt\n"


def test_overlay_applies_to_every_instance_of_a_repeated_stage_id(
    tmp_path: Path,
) -> None:
    """A loop stage's id repeats per round; the declared prompt describes the stage kind."""
    root = _target(
        tmp_path,
        """\
schema_version: 1
workflows:
  prompt:
    stages:
      - id: P2
        prompt: aidw/prompts/task-review.md
""",
    )
    declared = _write_prompt(root, "aidw/prompts/task-review.md")
    finding = ParsedFinding(
        priority="could-fix",
        confidence=3,
        what_found="w",
        why_it_matters="y",
        trigger_and_effect="t",
        where="f.py",
        suggested_fix="s",
    )

    specs = plan_stages(
        "prompt",
        config=_resolved(root),
        toolkit_root=TOOLKIT.root,
        target_root=root,
        phase="03",
        epic="E4",
        task="E4.1",
        rel=PROMPT_REL,
        max_revisions=3,
        rounds=(FixBatch(review_text="r", could_fix=(finding,)),),
    )

    reviews = [spec for spec in specs if spec.id == "P2"]
    assert [spec.name for spec in reviews] == ["task-review-1", "task-review-2"]
    assert all(spec.explicit_prompt == "aidw/prompts/task-review.md" for spec in reviews)
    assert all(spec.prompt == declared for spec in reviews)


def test_a_repo_without_a_workflows_section_plans_pure_defaults(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _target(tmp_path, "schema_version: 1\n")

    specs = _plan(
        "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
        branch=BRANCH, task_id=TASK_ID,
    )

    assert _shape(specs) == _shape(
        _plan(
            "implement", prompt_rel=PROMPT_REL, branch=BRANCH, task_id=TASK_ID
        )
    )
    assert all(spec.explicit_prompt is None for spec in specs)
    assert capsys.readouterr().err == ""


def test_the_repo_declared_list_is_an_overlay_not_a_mirror(tmp_path: Path) -> None:
    """A whole-list override may be shorter/reordered; the registry still plans the chain."""
    root = _target(
        tmp_path,
        """\
schema_version: 1
workflows:
  implement:
    stages:
      - id: I5
      - id: I1
        prompt: aidw/prompts/impliment-task.md
""",
    )
    _write_prompt(root, "aidw/prompts/impliment-task.md")

    specs = _plan(
        "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
        branch=BRANCH, task_id=TASK_ID,
    )

    # All six stages, in the registry's order — the declared list reorders/omits nothing.
    assert [spec.id for spec in specs] == ["I1", "I2", "I3", "I4", "I5", "I6"]
    assert specs[0].explicit_prompt == "aidw/prompts/impliment-task.md"
    assert specs[4].explicit_prompt is None


# --------------------------------------------------------------------------- #
# Deferred settings warn — one line per entry (E4.3 req 3)
# --------------------------------------------------------------------------- #


def _warning_lines(err: str) -> list[str]:
    return [line for line in err.splitlines() if line.startswith("warning:")]


def test_one_entry_with_agent_and_disabled_draws_one_line_naming_both(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _target(
        tmp_path,
        """\
schema_version: 1
workflows:
  implement:
    stages:
      - id: I3
        agent: implementer
        enabled: false
""",
    )

    _plan(
        "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
        branch=BRANCH, task_id=TASK_ID,
    )

    lines = _warning_lines(capsys.readouterr().err)
    assert len(lines) == 1, lines
    (line,) = lines
    # The workflow, the stage id, and *every* deferred reason, on the one line.
    assert "`implement`" in line
    assert "`I3`" in line
    assert "`agent` override (E4.6)" in line
    assert "`enabled: false` (E4.5)" in line


def test_an_unknown_stage_id_draws_one_line_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _target(
        tmp_path,
        """\
schema_version: 1
workflows:
  implement:
    stages:
      - id: X9
        prompt: aidw/prompts/repo-added.md
""",
    )
    _write_prompt(root, "aidw/prompts/repo-added.md")

    specs = _plan(
        "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
        branch=BRANCH, task_id=TASK_ID,
    )

    lines = _warning_lines(capsys.readouterr().err)
    assert len(lines) == 1, lines
    assert "`X9`" in lines[0]
    assert "repo-added" in lines[0]
    # A repo-added stage is deferred (E4.5): it is not planned, and its prompt is not used.
    assert [spec.id for spec in specs] == ["I1", "I2", "I3", "I4", "I5", "I6"]
    assert all("repo-added" not in str(spec.prompt) for spec in specs)


def test_a_two_entries_are_counted_per_entry_not_per_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _target(
        tmp_path,
        """\
schema_version: 1
workflows:
  implement:
    stages:
      - id: I3
        agent: implementer
      - id: X9
""",
    )

    _plan(
        "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
        branch=BRANCH, task_id=TASK_ID,
    )

    lines = _warning_lines(capsys.readouterr().err)
    assert len(lines) == 2, lines
    assert any("`I3`" in line for line in lines)
    assert any("`X9`" in line for line in lines)


def test_a_prompt_only_entry_draws_no_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``prompt:`` is not deferred: it is the one field E4.3 honours."""
    root = _target(tmp_path, OVERLAY_CONFIG)
    _write_prompt(root, "aidw/prompts/update-traceability.md")

    _plan(
        "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
        branch=BRANCH, task_id=TASK_ID,
    )

    assert capsys.readouterr().err == ""


# --------------------------------------------------------------------------- #
# Fail-closed and purity
# --------------------------------------------------------------------------- #


def test_a_declared_but_missing_prompt_raises_and_falls_back_nowhere(tmp_path: Path) -> None:
    """§3.4 level 1: a declared path is the only location searched, so it fails closed."""
    root = _target(
        tmp_path,
        """\
schema_version: 1
workflows:
  implement:
    stages:
      - id: I3
        prompt: aidw/prompts/does-not-exist.md
""",
    )

    with pytest.raises(FileNotFoundError) as raised:
        _plan(
            "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
            branch=BRANCH, task_id=TASK_ID,
        )

    message = str(raised.value)
    assert "does-not-exist.md" in message
    assert "explicit_path is set" in message


def test_plan_stages_mutates_neither_the_config_nor_the_registry(
    tmp_path: Path,
) -> None:
    root = _target(tmp_path, OVERLAY_CONFIG)
    _write_prompt(root, "aidw/prompts/update-traceability.md")
    config = _resolved(root)
    before_config = config.to_dict()
    before_defaults = repr(DEFAULTS)
    fields = {"prompt_rel": PROMPT_REL, "branch": BRANCH, "task_id": TASK_ID}

    _plan("implement", config=config, root=root, **fields)

    assert config.to_dict() == before_config
    assert repr(DEFAULTS) == before_defaults
    assert fields == {"prompt_rel": PROMPT_REL, "branch": BRANCH, "task_id": TASK_ID}


def test_plan_stages_does_no_io_beyond_prompt_existence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The builder reads no file and writes none; only ``Path.is_file`` may run."""

    def _explode(*args: object, **kwargs: object):
        raise AssertionError("plan_stages must not read or write a file")

    monkeypatch.setattr(builtins, "open", _explode)
    monkeypatch.setattr(Path, "read_text", _explode)
    monkeypatch.setattr(Path, "write_text", _explode)

    specs = _plan(
        "implement", prompt_rel=PROMPT_REL, branch=BRANCH, task_id=TASK_ID
    )

    assert len(specs) == 6


def test_each_call_returns_fresh_objects(tmp_path: Path) -> None:
    root = _target(tmp_path, OVERLAY_CONFIG)
    _write_prompt(root, "aidw/prompts/update-traceability.md")
    config = _resolved(root)
    fields = {"prompt_rel": PROMPT_REL, "branch": BRANCH, "task_id": TASK_ID}

    first = _plan("implement", config=config, root=root, **fields)
    second = _plan("implement", config=config, root=root, **fields)

    assert first == second
    assert first is not second
    for left, right in zip(first, second, strict=True):
        assert left is not right
        assert left.variables is not right.variables


# --------------------------------------------------------------------------- #
# Metamorphic sweep: the builder *is* the registry expansion (E4.3 req 1)
# --------------------------------------------------------------------------- #

#: The documented expansion-field set of every workflow (``stage_registry.expand``).
_FIELDS: dict[str, dict[str, object]] = {
    "approve": {"pr": PR},
    "fix": {
        "pr": PR,
        "round_index": 1,
        "iteration": 1,
        "manifest_rel": "artifacts/iter1-review-manifest.json",
    },
    "implement": {
        "prompt_rel": PROMPT_REL,
        "branch": BRANCH,
        "task_id": TASK_ID,
    },
    "prompt": {
        "phase": "03",
        "epic": "E4",
        "task": "E4.1",
        "rel": PROMPT_REL,
        "max_revisions": 3,
        "rounds": (),
    },
    "review": {"pr": PR, "manifest_rel": MANIFEST, "findings": True},
}

#: A stage id that exists in each workflow, so the overlay can name a real stage.
_OVERLAY_ID = {"approve": "A1", "fix": "A1", "implement": "I1", "prompt": "P1", "review": "R1"}


@pytest.mark.parametrize("workflow", sorted(_FIELDS))
def test_every_workflow_plans_exactly_the_registry_expansion(
    workflow: str, tmp_path: Path
) -> None:
    root = _target(tmp_path)
    fields = _FIELDS[workflow]

    specs = _plan(workflow, root=root, **fields)
    planned = stage_registry.expand(workflow, **fields)

    assert len(specs) == len(planned)
    assert [
        (spec.id, spec.name, spec.agent_id, spec.variables, spec.extra) for spec in specs
    ] == [
        (stage.id, stage.name, stage.agent, list(stage.variables), stage.extra)
        for stage in planned
    ]
    assert all(spec.workflow == workflow for spec in specs)
    assert all(spec.prompt.is_file() for spec in specs)


@pytest.mark.parametrize("workflow", sorted(_FIELDS))
def test_a_declared_overlay_never_changes_a_plans_shape(
    workflow: str, tmp_path: Path
) -> None:
    """Metamorphic: the overlay moves one stage's prompt, nothing else.

    The declared entry also carries the deferred fields, so this covers the "warn but plan
    the defaults" path for every workflow: same stages, same order, same ``extra``.
    """
    stage_id = _OVERLAY_ID[workflow]
    rel = f"aidw/prompts/{workflow}-override.md"
    root = _target(
        tmp_path,
        f"""\
schema_version: 1
workflows:
  {workflow}:
    stages:
      - id: {stage_id}
        prompt: {rel}
        agent: implementer
        enabled: false
""",
    )
    declared = _write_prompt(root, rel)
    fields = _FIELDS[workflow]

    plain = _plan(workflow, root=root, **fields)
    overlaid = _plan(workflow, config=_resolved(root), root=root, **fields)

    assert _shape(overlaid) == _shape(plain)
    overridden = [spec for spec in overlaid if spec.id == stage_id]
    assert overridden, stage_id
    assert all(spec.prompt == declared for spec in overridden)
    assert all(spec.explicit_prompt == rel for spec in overridden)
    # The other stages keep the toolkit defaults.
    assert [
        spec.prompt for spec in overlaid if spec.id != stage_id
    ] == [spec.prompt for spec in plain if spec.id != stage_id]
