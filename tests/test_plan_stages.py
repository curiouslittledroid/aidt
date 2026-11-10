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
* the E4.5b plan shapes: a declared list becomes the plan's static half **in declared
  order** (repo-added stages included, with their full ``StageSpec`` field set), a
  repo-optional ``enabled: false`` is honoured by omission, and the registry's loop portion
  follows unchanged — split from the static half by stage id (E4.5a's formula);
* refusal (E4.5b req 3): a declared list the validator rejects — a disabled core stage, a
  reordered core list, ``stages: []``, a declared loop id — raises ``StageListError``
  carrying the validator's ``format_issues`` text, never a shortened/reordered plan;
* the remaining deferred-field warning (a repo-added stage in the name-keyed ``prompt``/
  ``fix``): one stderr line per entry, naming the workflow, the id and the reason;
* the E4.6 overrides are *honoured*, not deferred: a known stage's ``agent`` becomes
  ``agent_id`` and ``model``/``thinking``/``timeout_seconds`` ride on the ``StageSpec`` —
  uniformly for a repo-added stage — with no warning;
* fail-closed and purity: a declared-but-missing prompt raises, no shadow/toolkit fallback,
  and neither the config nor the registry defaults are mutated.

The invariant sweep at the end is the metamorphic half: for all five workflows, the builder's
output is exactly the registry's expansion (E4.3 req 1), a declared overlay never changes a
plan's shape — only which prompt file a stage resolves to — and inserting a repo-added stage
at any declared position changes nothing but its own insertion point (E4.5b req 1). It also
pins the purity half: the builder mutates neither the config nor the registry defaults, so
running the sweep over them again yields the same plan. ``hypothesis`` is not a dependency,
so the sweep enumerates the small input space deterministically; the "seed" is the
enumeration itself (the same convention as ``tests/test_stage_registry.py``, AGENTS.md's
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
#: I7's two expansion fields (H3.1): the entry's own roadmap file and its task id.
ROADMAP_FILE = "/repo/docs/tasks/03 - Extraction.md"
CHECKBOX_ID = "E4.1"


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
    """The run-path plan. Implement's two I7 expansion fields default here (H3.1)."""
    if workflow == "implement":
        fields.setdefault("roadmap_file", ROADMAP_FILE)
        fields.setdefault("checkbox_id", CHECKBOX_ID)
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


def _static_ids(workflow: str) -> list[str]:
    """The static stage ids ``workflow`` plans, in registry order (E4.5a's core order)."""
    return [item.id for item in stage_registry.get_workflow(workflow).stages]


def _stage_entries(
    workflow: str,
    *,
    overrides: dict[str, dict[str, object]] | None = None,
    added: list[tuple[int, dict[str, object]]] | None = None,
) -> list[dict[str, object]]:
    """A full declared stage list, plus per-id overrides and repo-added entries.

    A declared list **replaces** the toolkit's static half wholesale (§3.4), so E4.5a
    refuses one that omits or reorders a core id: every static id (repo-optional ones
    included, so the declared plan stays shape-identical) is named in registry order.
    ``overrides`` adds keys to a declared static id's entry; ``added`` inserts repo-added
    entries at declared positions (``0`` = before the first core stage).
    """
    entries: list[dict[str, object]] = [
        {"id": stage_id, **(overrides or {}).get(stage_id, {})}
        for stage_id in _static_ids(workflow)
    ]
    for position, entry in sorted(added or [], key=lambda item: item[0]):
        entries.insert(position, dict(entry))
    return entries


def _config(workflow: str, entries: list[dict[str, object]]) -> str:
    """The ``aidw/config.yaml`` text declaring ``workflows.<workflow>.stages = entries``."""
    lines = ["schema_version: 1", "workflows:", f"  {workflow}:", "    stages:"]
    for entry in entries:
        for index, (key, value) in enumerate(entry.items()):
            prefix = "      - " if index == 0 else "        "
            rendered = ("true" if value else "false") if isinstance(value, bool) else str(value)
            lines.append(f"{prefix}{key}: {rendered}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# One hand-calculated vector per workflow (design §8.1–§8.5)
# --------------------------------------------------------------------------- #


def test_implement_plan_is_the_seven_registry_stages(tmp_path: Path) -> None:
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
        ("I7", "update-roadmap", "recorder", _toolkit_prompt("update-roadmap.md"),
         [ROADMAP_FILE, CHECKBOX_ID]),
        ("I6", "pr", "pr-publisher", _toolkit_prompt("pr.md"), [TASK_ID]),
    ]
    # The `extra` is part of the plan: I2's test context, rendered for these fields.
    assert specs[1].extra == stage_registry.TEST_CONTEXT_EXTRA.format(
        task_id=TASK_ID, branch=BRANCH, prompt_rel=PROMPT_REL
    )
    assert [spec.extra for spec in specs if spec.id != "I2"] == [""] * 6
    # A pure-defaults repo declares no overlay, so no stage carries an explicit path.
    assert all(spec.explicit_prompt is None for spec in specs)
    assert all(spec.workflow == "implement" for spec in specs)
    assert all(isinstance(spec.variables, list) for spec in specs)


def test_review_plan_is_r1_plus_the_r2_manifest_pointer(tmp_path: Path) -> None:
    root = _target(tmp_path)
    specs = _plan(
        "review", root=root, pr=PR, manifest_path=MANIFEST, findings=True
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
            MANIFEST_EXTRA.format(manifest_path=MANIFEST),
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
        manifest_path="artifacts/iter1-review-manifest.json",
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
        manifest_path="artifacts/iter1-review-manifest.json"
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

#: §3.4's own example: a repo-declared stage naming an explicit prompt path. The list is
#: a whole-list *declaration* (E4.5a), so it names every static stage in registry order and
#: only I3 carries the overlay.
OVERLAY_REL = "aidw/prompts/update-traceability.md"
OVERLAY_CONFIG = _config(
    "implement", _stage_entries("implement", overrides={"I3": {"prompt": OVERLAY_REL}})
)


def test_declared_prompt_sets_explicit_prompt_and_resolves_it(tmp_path: Path) -> None:
    root = _target(tmp_path, OVERLAY_CONFIG)
    declared = _write_prompt(root, OVERLAY_REL)

    specs = _plan(
        "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
        branch=BRANCH, task_id=TASK_ID,
    )

    by_id = {spec.id: spec for spec in specs}
    assert by_id["I3"].explicit_prompt == OVERLAY_REL
    assert by_id["I3"].prompt == declared
    # Every other stage keeps the toolkit default and no explicit path.
    for stage_id in ("I1", "I2", "I4", "I5", "I7", "I6"):
        assert by_id[stage_id].explicit_prompt is None
        assert by_id[stage_id].prompt.parent == TOOLKIT.prompts_dir


def test_declared_prompt_beats_a_same_named_target_shadow(tmp_path: Path) -> None:
    """D14: the explicit path wins over filename shadowing, which still applies otherwise."""
    root = _target(tmp_path, OVERLAY_CONFIG)
    declared = _write_prompt(root, OVERLAY_REL, "explicit\n")
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
    declared = _write_prompt(root, OVERLAY_REL, "# explicit prompt\n")
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


def test_a_declared_loop_id_is_refused_rather_than_double_planned(
    tmp_path: Path,
) -> None:
    """A loop id is generated by ``expand``; declaring one is a D12/D13 refusal (E4.5a).

    Before E4.5b this overlaid every instance of the repeated id; the plan path now runs
    the validator the preflight runs, so the direct caller is refused too instead of being
    handed a plan with the loop stage twice.
    """
    root = _target(
        tmp_path,
        _config(
            "prompt",
            _stage_entries(
                "prompt",
                added=[(1, {"id": "P2", "prompt": "aidw/prompts/task-review.md"})],
            ),
        ),
    )
    _write_prompt(root, "aidw/prompts/task-review.md")

    with pytest.raises(stage_registry.StageListError) as raised:
        plan_stages(
            "prompt",
            config=_resolved(root),
            toolkit_root=TOOLKIT.root,
            target_root=root,
            phase="03",
            epic="E4",
            task="E4.1",
            rel=PROMPT_REL,
            max_revisions=3,
            rounds=(),
        )

    message = str(raised.value)
    assert "workflows.prompt.stages" in message
    assert "`P2`" in message
    assert "loop stages are generated by `expand`" in message


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


def test_a_reordered_declared_list_raises_the_named_error(tmp_path: Path) -> None:
    """D12: a core stage may not be reordered, so the builder refuses, never re-sorts.

    The preflight is expected to have refused first (exit 2); this is the "not trusting
    because the validator already ran" half — the plan is not silently built in registry
    order behind the repo's back.
    """
    entries = _stage_entries("implement")
    entries[0], entries[1] = entries[1], entries[0]  # I2 before I1
    root = _target(tmp_path, _config("implement", entries))

    with pytest.raises(stage_registry.StageListError) as raised:
        _plan(
            "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
            branch=BRANCH, task_id=TASK_ID,
        )

    message = str(raised.value)
    assert message.startswith("error: workflows.implement.stages: ")
    assert "core stage cannot be reordered" in message
    # The declared core subsequence and the registry's core order, both named.
    assert "declared [I2, I1, I5, I7, I6]" in message
    assert "registry order is [I1, I2, I5, I7, I6]" in message


def test_an_empty_declared_list_raises_the_named_error(tmp_path: Path) -> None:
    """``stages: []`` removes every core stage; the builder reports all of them."""
    root = _target(tmp_path, "schema_version: 1\nworkflows:\n  implement:\n    stages: []\n")

    with pytest.raises(stage_registry.StageListError) as raised:
        _plan(
            "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
            branch=BRANCH, task_id=TASK_ID,
        )

    message = str(raised.value)
    for stage_id in ("I1", "I2", "I5", "I6"):
        assert f"stage `{stage_id}`: core stage cannot be removed" in message


def test_a_disabled_core_stage_raises_the_named_error(tmp_path: Path) -> None:
    """D12/D13: only a repo-optional stage may be disabled, so a core disable refuses."""
    root = _target(
        tmp_path,
        _config(
            "implement", _stage_entries("implement", overrides={"I5": {"enabled": False}})
        ),
    )

    with pytest.raises(stage_registry.StageListError) as raised:
        _plan(
            "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
            branch=BRANCH, task_id=TASK_ID,
        )

    message = str(raised.value)
    assert "stage `I5`: core stage cannot be disabled" in message


# --------------------------------------------------------------------------- #
# Repo-added stages (E4.5b req 1/req 4, EXTRACTION.md §3.5/§3.6)
# --------------------------------------------------------------------------- #

REPO_ADDED_PROMPT = "aidw/prompts/repo-added.md"


def test_a_repo_added_stage_is_planned_in_declared_order_with_every_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Req 4: the declared id, its agent and its prompt become a full ``StageSpec``.

    ``id``/``name`` are the declared id, ``agent_id`` is the declared ``agent`` (the one
    per-stage setting this version honours), ``variables`` is a fresh empty list (never
    ``()``), ``extra`` is empty, and the declared ``prompt:`` is the D14 level-1 path.
    """
    root = _target(
        tmp_path,
        _config(
            "implement",
            _stage_entries(
                "implement",
                added=[
                    (1, {"id": "X9", "agent": "implementer", "prompt": REPO_ADDED_PROMPT})
                ],
            ),
        ),
    )
    declared = _write_prompt(root, REPO_ADDED_PROMPT)

    specs = _plan(
        "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
        branch=BRANCH, task_id=TASK_ID,
    )

    # Declared order: the repo-added stage sits between I1 and I2, not appended.
    assert [spec.id for spec in specs] == [
        "I1", "X9", "I2", "I3", "I4", "I5", "I7", "I6"
    ]
    added = specs[1]
    assert (added.id, added.name, added.agent_id) == ("X9", "X9", "implementer")
    # E4.6: the same three metadata fields apply to a repo-added stage, uniformly.
    assert (added.model, added.thinking, added.timeout_seconds) == (None, None, None)
    assert added.prompt == declared
    assert added.explicit_prompt == REPO_ADDED_PROMPT
    assert added.variables == []
    assert added.extra == ""
    assert added.workflow == "implement"
    # Its `agent` is honoured, so nothing about it is deferred any more.
    assert capsys.readouterr().err == ""


def test_a_repo_added_stage_honours_the_metadata_overrides(tmp_path: Path) -> None:
    """Req 5: a repo-added stage carries ``model``/``thinking``/``timeout_seconds`` too."""
    root = _target(
        tmp_path,
        _config(
            "implement",
            _stage_entries(
                "implement",
                added=[
                    (
                        1,
                        {
                            "id": "X9",
                            "agent": "implementer",
                            "prompt": REPO_ADDED_PROMPT,
                            "model": "deepseek/deepseek-v4.1-flash",
                            "thinking": "xhigh",
                            "timeout_seconds": 120,
                        },
                    )
                ],
            ),
        ),
    )
    _write_prompt(root, REPO_ADDED_PROMPT)

    specs = _plan(
        "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
        branch=BRANCH, task_id=TASK_ID,
    )

    added = specs[1]
    assert added.id == "X9"
    assert (added.model, added.thinking, added.timeout_seconds) == (
        "deepseek/deepseek-v4.1-flash",
        "xhigh",
        120,
    )


def test_a_repo_added_stage_shadows_by_its_declared_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§3.6 level 2: with no ``prompt:``, the shadow is ``<target>/aidw/prompts/<id>.md``."""
    root = _target(
        tmp_path,
        _config(
            "implement",
            _stage_entries(
                "implement", added=[(7, {"id": "review-agent", "agent": "code-reviewer"})]
            ),
        ),
    )
    shadowed = _write_prompt(root, "aidw/prompts/review-agent.md", "# repo stage\n")

    specs = _plan(
        "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
        branch=BRANCH, task_id=TASK_ID,
    )

    assert [spec.id for spec in specs][-1] == "review-agent"
    added = specs[-1]
    assert added.prompt == shadowed
    assert added.explicit_prompt is None
    assert added.agent_id == "code-reviewer"
    assert added.name == "review-agent"
    assert capsys.readouterr().err == ""


def test_a_disabled_repo_added_stage_is_omitted(tmp_path: Path) -> None:
    """E4.5a accepts any ``enabled`` on a repo-added stage; disabling means omitting it."""
    root = _target(
        tmp_path,
        _config(
            "implement",
            _stage_entries(
                "implement",
                added=[
                    (
                        1,
                        {
                            "id": "X9",
                            "agent": "implementer",
                            "prompt": REPO_ADDED_PROMPT,
                            "enabled": False,
                        },
                    )
                ],
            ),
        ),
    )
    _write_prompt(root, REPO_ADDED_PROMPT)

    specs = _plan(
        "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
        branch=BRANCH, task_id=TASK_ID,
    )

    assert [spec.id for spec in specs] == ["I1", "I2", "I3", "I4", "I5", "I7", "I6"]


def test_a_prompt_repo_added_static_stage_precedes_the_loop_portion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Req 1/req 2: the declared static half, then ``expand``'s P2 loop portion.

    ``prompt``'s consumer is name-keyed and never runs a repo-added stage, so the entry is
    planned (the declaration is honoured on the plan path) *and* warned about — never a
    silent drop.
    """
    root = _target(
        tmp_path,
        _config(
            "prompt",
            _stage_entries(
                "prompt",
                added=[(1, {"id": "X9", "agent": "task-reviewer", "prompt": REPO_ADDED_PROMPT})],
            ),
        ),
    )
    _write_prompt(root, REPO_ADDED_PROMPT)
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
        config=_resolved(root),
        toolkit_root=TOOLKIT.root,
        target_root=root,
        phase="03",
        epic="E4",
        task="E4.1",
        rel=PROMPT_REL,
        max_revisions=3,
        rounds=(FixBatch(review_text="r", blocking=(finding,)),),
    )

    # The declared static half (P1, X9) is followed by the whole loop portion, unchanged.
    assert [spec.name for spec in specs] == [
        "task-prompt",
        "X9",
        "task-review-1",
        "task-review-fixes-1-1",
        "task-review-reconcile-1",
        "task-review-2",
    ]
    lines = _warning_lines(capsys.readouterr().err)
    assert len(lines) == 1, lines
    assert "`prompt`" in lines[0]
    assert "`X9`" in lines[0]
    assert "repo-added" in lines[0]


def test_a_fix_repo_added_static_stage_precedes_the_iteration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``fix`` is name-keyed too: planned, warned about, and its loop portion follows."""
    root = _target(
        tmp_path,
        _config(
            "fix",
            _stage_entries(
                "fix",
                added=[(1, {"id": "X9", "agent": "fixer", "prompt": REPO_ADDED_PROMPT})],
            ),
        ),
    )
    _write_prompt(root, REPO_ADDED_PROMPT)

    specs = _plan(
        "fix",
        config=_resolved(root),
        root=root,
        pr=PR,
        round_index=1,
        iteration=1,
        manifest_path="artifacts/iter1-review-manifest.json",
    )

    assert [spec.name for spec in specs] == [
        "round1-approve-review-followups",
        "X9",
        "iter1-fix-next-review-followup",
        "iter1-test",
        "iter1-code-review",
        "iter1-review-findings-to-github",
    ]
    lines = _warning_lines(capsys.readouterr().err)
    assert len(lines) == 1, lines
    assert "`X9`" in lines[0]
    assert "repo-added" in lines[0]


# --------------------------------------------------------------------------- #
# Deferred settings warn — one line per entry (E4.3 req 3, E4.5b req 2)
# --------------------------------------------------------------------------- #


def _warning_lines(err: str) -> list[str]:
    return [line for line in err.splitlines() if line.startswith("warning:")]


def test_a_repo_optional_disabled_stage_is_omitted_with_no_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """E4.5b/E4.6: ``enabled: false`` is honoured and ``agent`` now applies.

    Nothing about this entry is deferred any more, so the plan simply omits I3 and stderr
    stays empty.
    """
    root = _target(
        tmp_path,
        _config(
            "implement",
            _stage_entries(
                "implement", overrides={"I3": {"agent": "implementer", "enabled": False}}
            ),
        ),
    )

    specs = _plan(
        "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
        branch=BRANCH, task_id=TASK_ID,
    )

    assert [spec.id for spec in specs] == ["I1", "I2", "I4", "I5", "I7", "I6"]
    assert capsys.readouterr().err == ""


def test_known_stage_metadata_overrides_are_honoured_silently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """E4.6: a known stage's ``agent``/``model``/``thinking``/``timeout`` all take effect.

    The pre-E4.6 deferred-setting line is gone: the two entries draw no warning, the
    declared ``agent`` becomes ``agent_id``, and the three metadata values ride on the
    spec for :func:`run_stage` to apply.
    """
    root = _target(
        tmp_path,
        _config(
            "implement",
            _stage_entries(
                "implement",
                overrides={
                    "I3": {
                        "agent": "code-reviewer",
                        "model": "meta/muse-spark-1.3",
                        "thinking": "low",
                        "timeout_seconds": 900,
                    },
                    "I4": {"agent": "implementer"},
                },
            ),
        ),
    )

    specs = _plan(
        "implement", config=_resolved(root), root=root, prompt_rel=PROMPT_REL,
        branch=BRANCH, task_id=TASK_ID,
    )

    by_id = {spec.id: spec for spec in specs}
    assert by_id["I3"].agent_id == "code-reviewer"
    assert (by_id["I3"].model, by_id["I3"].thinking, by_id["I3"].timeout_seconds) == (
        "meta/muse-spark-1.3",
        "low",
        900,
    )
    assert by_id["I4"].agent_id == "implementer"
    # A stage the config did not override keeps the registry agent and no metadata.
    assert (by_id["I2"].agent_id, by_id["I2"].model, by_id["I2"].thinking) == (
        "tester",
        None,
        None,
    )
    assert capsys.readouterr().err == ""


def test_a_prompt_only_entry_draws_no_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``prompt:`` is not deferred: it is the one field E4.3 honours."""
    root = _target(tmp_path, OVERLAY_CONFIG)
    _write_prompt(root, OVERLAY_REL)

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
        _config(
            "implement",
            _stage_entries(
                "implement", overrides={"I3": {"prompt": "aidw/prompts/does-not-exist.md"}}
            ),
        ),
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
    _write_prompt(root, OVERLAY_REL)
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

    assert len(specs) == 7


def test_each_call_returns_fresh_objects(tmp_path: Path) -> None:
    root = _target(tmp_path, OVERLAY_CONFIG)
    _write_prompt(root, OVERLAY_REL)
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
        "manifest_path": "artifacts/iter1-review-manifest.json",
    },
    "implement": {
        "prompt_rel": PROMPT_REL,
        "branch": BRANCH,
        "task_id": TASK_ID,
        "roadmap_file": ROADMAP_FILE,
        "checkbox_id": CHECKBOX_ID,
    },
    "prompt": {
        "phase": "03",
        "epic": "E4",
        "task": "E4.1",
        "rel": PROMPT_REL,
        "max_revisions": 3,
        "rounds": (),
    },
    "review": {"pr": PR, "manifest_path": MANIFEST, "findings": True},
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

    ``prompt:`` is a pure overlay for every workflow: same stages, same order, same
    ``agent_id``, same ``extra`` — the declared list is not a second source of truth for
    the shape. (E4.6's ``agent`` *does* change ``agent_id``; that is asserted separately.)
    """
    stage_id = _OVERLAY_ID[workflow]
    rel = f"aidw/prompts/{workflow}-override.md"
    # Every static stage in registry order (a whole-list declaration, E4.5a) with the
    # ``prompt:`` on one of them.
    root = _target(
        tmp_path,
        _config(
            workflow,
            _stage_entries(workflow, overrides={stage_id: {"prompt": rel}}),
        ),
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


#: Every declared position a repo-added stage can occupy: before the first static stage,
#: between any two, and after the last. This is the sweep's "seed": the enumeration is the
#: generator (``hypothesis`` is not a dependency, AGENTS.md's no-new-deps rule).
@pytest.mark.parametrize("workflow", sorted(_FIELDS))
def test_a_declared_agent_override_changes_only_that_stage(
    workflow: str, tmp_path: Path
) -> None:
    """E4.6 req 3: the declared ``agent`` replaces the registry's for one stage only.

    Metamorphic over all five workflows: every other spec is untouched, and the overridden
    one keeps its name, prompt, variables and ``extra`` — only ``agent_id`` moves.
    """
    stage_id = _OVERLAY_ID[workflow]
    fields = _FIELDS[workflow]
    plain_root = _target(tmp_path / "plain")
    plain = _plan(workflow, root=plain_root, **fields)
    override_agent = "implementer" if _stage_entry_agent(plain, stage_id) != "implementer" else "tester"

    root = _target(
        tmp_path / "override",
        _config(
            workflow,
            _stage_entries(workflow, overrides={stage_id: {"agent": override_agent}}),
        ),
    )

    overridden = _plan(workflow, config=_resolved(root), root=root, **fields)

    assert _shape(overridden) == [
        (spec.id, spec.name, override_agent if spec.id == stage_id else spec.agent_id,
         spec.variables, spec.extra)
        for spec in plain
    ]
    assert [spec.prompt for spec in overridden] == [spec.prompt for spec in plain]


def _stage_entry_agent(specs: list[StageSpec], stage_id: str) -> str:
    return next(spec.agent_id for spec in specs if spec.id == stage_id)


@pytest.mark.parametrize("workflow", sorted(_FIELDS))
def test_inserting_a_repo_added_stage_only_inserts(
    workflow: str, tmp_path: Path
) -> None:
    """Metamorphic (E4.5b req 1): the core plan and the loop portion never move.

    Inserting a repo-added entry at *any* declared position leaves every other spec — its
    id, name, agent, variables and ``extra``, and therefore the registry's loop portion too
    — byte-identical; the only change is the inserted spec at the inserted position.
    """
    rel = f"aidw/prompts/{workflow}-repo-added.md"
    fields = _FIELDS[workflow]
    plain_root = _target(tmp_path / "plain")
    plain = _plan(workflow, root=plain_root, **fields)

    for position in range(len(_static_ids(workflow)) + 1):
        root = _target(
            tmp_path / f"added-{position}",
            _config(
                workflow,
                _stage_entries(
                    workflow,
                    added=[(position, {
                        "id": "X9",
                        "agent": "implementer",
                        "prompt": rel,
                    })],
                ),
            ),
        )
        _write_prompt(root, rel)

        plan = _plan(workflow, config=_resolved(root), root=root, **fields)

        assert plan[position].id == "X9", position
        rest = [spec for spec in plan if spec.id != "X9"]
        assert _shape(rest) == _shape(plain), position
        # The loop portion is the *tail* of both plans, so the insertion cannot reorder it.
        assert [spec.id for spec in plan[position + 1 :]] == [
            spec.id for spec in plain[position:]
        ]
