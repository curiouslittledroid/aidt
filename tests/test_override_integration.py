"""The override integration test: the acceptance test for E3 + E4 (task E4.7).

``fixtures/target-repo/`` is a committed **target repo** (EXTRACTION.md §3.12), and this
module is the executable proof of the six override behaviours the config surface promises
(EXTRACTION.md §2 D4/D12/D13/D14, §3.4, §3.5, §3.6; design §17 N1) at the two seams design
§15 names: :func:`aidw.runner.plan_stages` (prompt paths + agents) and
:func:`aidw.runner.run_stage` under ``dry_run=True`` (the argv Pi would receive). Nothing
here invokes a real Pi model, ``git`` or ``gh``, and nothing runs a workflow preflight: the
fixture deliberately lacks Mythical Forge's default read-paths (``docs/tasks``,
``docs/implementation-results/TEMPLATE.md``, …), and validating those is E3.7's
``validate_paths`` — a later concern than the override mechanism this test proves.

The behaviour→stage-id mapping is **prompt-fixed** (the roadmap names the behaviours, not
their ids): ``implement`` is the only workflow with both repo-optional stages and a
seven-stage static chain, and a declared ``stages:`` list replaces the static half wholesale,
so all seven core ids are declared in registry order with I3 disabled by ``enabled: false``.

============================ =================================================
Behaviour                    Evidence in ``fixtures/target-repo``
============================ =================================================
D4 default fallback          I1/I5/I6 → ``<toolkit>/prompts/<name>.md``, no
                             ``explicit_prompt``
D14 level 2 filename shadow  I2 → ``aidw/prompts/test.md``
D14 level 1 explicit path    I4 → ``aidw/prompts/architecture-explicit.md``
D12/D13 repo-optional off    I3 omitted; every other core id kept in order
§3.5 repo-added stage        ``lint``: declared ``agent``, prompt from
                             ``aidw/prompts/lint.md``
E4.6/N1 global agent-config  ``paths.agent_configs_dir`` shadows ``implementer``
override                     by id (never a wholesale replacement)
============================ =================================================

Regression sensitivity is structural, not incidental: each behaviour has its own check, and
the ``test_perturbing_*`` / ``test_dropping_*`` tests change **exactly one** fixture input in
a temporary copy and assert the behaviour disappears — so no check can pass because a second
mechanism covers for the removed one. ``hypothesis`` is not a dependency (design §15, no new
deps), so the perturbation set is the pinned, enumerated list of those tests: its "seed" is
that list and its "numRuns" is its length, the convention ``tests/test_stage_registry.py``
and ``tests/test_plan_stages.py`` already use.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

from aidw import runner as runner_mod
from aidw import stage_registry
from aidw.agents import model_name
from aidw.config import ERROR, AgentConfig, load_all
from aidw.log import RunLogger
from aidw.paths import toolkit_root
from aidw.prompts import render_prompt_file
from aidw.runner import StageSpec, plan_stages, run_stage
from aidw.state import SUCCEEDED, RunState, StageRecord, create_run, run_dir
from aidw.target_config import (
    ResolvedConfig,
    TargetConfig,
    agent_configs_override,
    load_target_config,
    resolve_config,
)

#: The committed fixture target repo (EXTRACTION.md §3.12) — never written to by a test.
FIXTURE = toolkit_root() / "fixtures" / "target-repo"
CONFIG_REL = Path("aidw") / "config.yaml"
TEST_SHADOW = FIXTURE / "aidw" / "prompts" / "test.md"
EXPLICIT_PROMPT = FIXTURE / "aidw" / "prompts" / "architecture-explicit.md"
LINT_PROMPT = FIXTURE / "aidw" / "prompts" / "lint.md"
IMPLEMENTER_OVERRIDE = FIXTURE / "aidw" / "agent-configs" / "implementer.yaml"
IMPLEMENTER_OVERRIDE_DIR = FIXTURE / "aidw" / "agent-configs"

TEST_MARKER = "E4.7 FIXTURE FILENAME OVERRIDE"
EXPLICIT_MARKER = "E4.7 FIXTURE EXPLICIT PATH"
LINT_MARKER = "E4.7 FIXTURE REPO-ADDED LINT"

#: The fixture implementer's model as the config declares it, and as it reaches an argv:
#: ``qualified_model`` keeps the provider, ``--model`` drops the agent's own prefix only
#: (design §5.1, ``aidw/agents.py:model_name``).
OVERRIDE_MODEL = "openrouter/fixture/e4-override-implementer"
OVERRIDE_MODEL_SLUG = "fixture/e4-override-implementer"

WORKFLOW = "implement"
PROMPT_REL = "docs/task-prompts/00-E4.7-prompt.md"
BRANCH = "00-E4.7"
TASK_ID = "00-E4.7"
#: I7's two expansion fields (H3.1): the entry's own roadmap file and its task id.
ROADMAP_FILE = "/repo/docs/tasks/03 - Extraction.md"
CHECKBOX_ID = "E4.1"
BASE_BRANCH = "main"


# --------------------------------------------------------------------------- #
# Helpers: the committed fixture, its load path, and its plan
# --------------------------------------------------------------------------- #


def _declared(target: Path = FIXTURE) -> TargetConfig:
    """Load the fixture's ``aidw/config.yaml`` exactly as a workflow would."""
    return load_target_config(target / CONFIG_REL)


def _resolved(target: Path = FIXTURE) -> ResolvedConfig:
    """The real load → resolve path, refusing a config carrying ERROR issues."""
    declared = _declared(target)
    errors = [issue for issue in declared.issues if issue.level == ERROR]
    assert errors == [], errors
    return resolve_config(declared)


def _plan(
    config: ResolvedConfig | None = None, *, target: Path = FIXTURE
) -> list[StageSpec]:
    """``plan_stages`` for the fixture's ``implement`` chain (design §15's first seam)."""
    return plan_stages(
        WORKFLOW,
        config=config if config is not None else _resolved(target),
        toolkit_root=toolkit_root(),
        target_root=target,
        prompt_rel=PROMPT_REL,
        branch=BRANCH,
        task_id=TASK_ID,
        base_branch=BASE_BRANCH,
        roadmap_file=ROADMAP_FILE,
        checkbox_id=CHECKBOX_ID,
    )


def _by_id(specs: list[StageSpec]) -> dict[str, StageSpec]:
    return {spec.id: spec for spec in specs}


def _toolkit_prompt(name: str) -> Path:
    return (toolkit_root() / "prompts" / name).resolve()


def _agents(target: Path = FIXTURE) -> tuple[dict[str, AgentConfig], Path | None]:
    """The resolved agents, with E4.6's global override directory applied."""
    override = agent_configs_override(_resolved(target), target)
    agents, issues = load_all(toolkit_root(), target, override)
    errors = [issue for issue in issues if issue.level == ERROR]
    assert errors == [], errors
    return agents, override


def _fixture_copy(tmp_path: Path) -> Path:
    """A throwaway copy of the committed fixture, for one-input perturbations."""
    target = tmp_path / "target-repo"
    shutil.copytree(FIXTURE, target)
    return target


def _edit_config(target: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    """Rewrite a copy's ``aidw/config.yaml`` through a mutation (comments are not kept)."""
    path = target / CONFIG_REL
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _stage_entry(data: dict[str, Any], stage_id: str) -> dict[str, Any]:
    """The declared ``workflows.implement.stages`` entry for ``stage_id``."""
    for entry in data["workflows"]["implement"]["stages"]:
        if entry["id"] == stage_id:
            return entry
    raise AssertionError(f"fixture config declares no stage `{stage_id}`")


def _flag(argv: list[str], flag: str) -> str:
    """The value following ``flag`` in an emitted argv (fails when absent)."""
    assert flag in argv, argv
    return argv[argv.index(flag) + 1]


def _dry_run(
    tmp_path: Path,
    spec: StageSpec,
    *,
    agents: Mapping[str, AgentConfig],
    monkeypatch: pytest.MonkeyPatch,
    target: Path = FIXTURE,
) -> tuple[list[str], str, StageRecord]:
    """Dry-run one planned stage; return the production argv, rendered text and record.

    ``build_argv`` is wrapped only to *capture* the argv ``run_stage`` actually hands Pi
    (the ``tests/test_prompt_resolution.py`` seam), and ``run_stage(dry_run=True)`` spawns
    no ``pi``, ``git`` or ``gh`` (design §15). The ``agents`` mapping must be the
    override-applied one: a two-argument ``load_all`` silently drops the global override.
    """
    runs_root = tmp_path / "runs"
    run: RunState = create_run(runs_root, target, WORKFLOW, label=f"e4-7-{spec.id}")
    directory = run_dir(runs_root, run.run_id)
    logger = RunLogger(directory)
    captured: dict[str, list[str]] = {}
    real_build_argv = runner_mod.build_argv

    def recording_build_argv(agent: AgentConfig, **kwargs: Any) -> list[str]:
        argv = real_build_argv(agent, **kwargs)
        captured["argv"] = argv
        return argv

    monkeypatch.setattr(runner_mod, "build_argv", recording_build_argv)
    record = run_stage(
        spec,
        repo_root=target,
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=dict(agents),
        dry_run=True,
        runs_root=runs_root,
    )
    rendered = (directory / "prompts" / f"{spec.name}.rendered.md").read_text(
        encoding="utf-8"
    )
    return captured["argv"], rendered, record


# --------------------------------------------------------------------------- #
# The committed config: it loads, and it plans the chain it declares
# --------------------------------------------------------------------------- #


def test_committed_config_loads_without_errors_and_plans_the_core_chain() -> None:
    """Done-when: zero ERROR issues, and ``plan_stages`` returns I1–I7 minus I3, in order.

    A declared ``stages:`` list replaces the toolkit's static half wholesale (§3.4), so this
    pins the *order* of the core half: the declaration lists all seven core ids in registry
    order and the plan keeps exactly that order minus the disabled I3. The repo-added
    stage's own presence and position are behaviour 6's check, not this one — a single
    assertion must not cover two behaviours.
    """
    declared = _declared()
    assert [issue for issue in declared.issues if issue.level == ERROR] == []

    specs = _plan(_resolved())

    registry_static = [item.id for item in stage_registry.get_workflow(WORKFLOW).stages]
    # D12/D13: I3 is the one core id absent, omitted because it is repo-optional and the
    # config disabled it (the perturbation test below re-enables it), never reordered.
    assert "I3" not in _by_id(specs)
    assert [spec.id for spec in specs if spec.id in registry_static] == [
        stage_id for stage_id in registry_static if stage_id != "I3"
    ]


def test_planning_does_not_mutate_the_resolved_config() -> None:
    """Purity: ``plan_stages`` reads the config and the registry, and changes neither."""
    config = _resolved()
    before = dict(config)

    _plan(config=config)

    assert dict(config) == before


# --------------------------------------------------------------------------- #
# Behaviour 1 — D14 level 3 / D4: the toolkit default, per stage
# --------------------------------------------------------------------------- #


def test_default_fallback_stages_resolve_to_the_toolkit_prompts() -> None:
    """I1/I5/I6/I7 declare no ``prompt:`` and have no shadow: they get ``<toolkit>/prompts``.

    Three ids, three literal filenames: fallback is a per-prompt rule, not one stage's
    accident (D4), and each one is asserted against its own toolkit file.
    """
    specs = _by_id(_plan(_resolved()))
    expected = {
        "I1": ("impliment-task", "impliment-task.md"),
        "I5": ("record-implementation-results", "record-implementation-results.md"),
        "I7": ("update-roadmap", "update-roadmap.md"),
        "I6": ("pr", "pr.md"),
    }

    for stage_id, (name, filename) in expected.items():
        spec = specs[stage_id]
        assert spec.name == name, stage_id
        assert spec.explicit_prompt is None, stage_id
        assert spec.prompt == _toolkit_prompt(filename), stage_id
        assert spec.prompt != (FIXTURE / "aidw" / "prompts" / filename).resolve(), stage_id

    # A shadow added for any of these filenames would silently stop that stage's fallback,
    # so the check is on the fixture's committed prompt names — and only on these names, so
    # this assertion cannot cover another behaviour's shadow (the set is not pinned).
    for _name, filename in expected.values():
        assert not (FIXTURE / "aidw" / "prompts" / filename).exists(), filename


# --------------------------------------------------------------------------- #
# Behaviour 2 — D14 level 2: filename shadowing
# --------------------------------------------------------------------------- #


def test_filename_override_stage_resolves_the_fixture_shadow() -> None:
    """I2's prompt file is ``test.md``, so ``<target>/aidw/prompts/test.md`` wins."""
    spec = _by_id(_plan(_resolved()))["I2"]

    assert spec.name == "test"
    assert spec.explicit_prompt is None
    assert spec.prompt == TEST_SHADOW.resolve()
    assert spec.prompt != _toolkit_prompt("test.md")
    assert TEST_MARKER in TEST_SHADOW.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Behaviour 3 — D14 level 1: the declared explicit path
# --------------------------------------------------------------------------- #


def test_explicit_path_stage_resolves_the_declared_file_not_any_shadow(
    tmp_path: Path,
) -> None:
    """I4 declares ``prompt:``, so precedence 1 wins and level 2 is never consulted.

    The same-named-shadow half runs on a temporary copy: the fixture commits **no**
    ``update-architecture.md``, so the committed fixture proves the declared path works
    while the copy proves it beats a shadow of its own registry filename.
    """
    spec = _by_id(_plan(_resolved()))["I4"]

    assert spec.name == "update-architecture"
    assert spec.explicit_prompt == "aidw/prompts/architecture-explicit.md"
    assert spec.prompt == EXPLICIT_PROMPT.resolve()
    assert spec.prompt != _toolkit_prompt("update-architecture.md")
    assert EXPLICIT_MARKER in EXPLICIT_PROMPT.read_text(encoding="utf-8")

    copy = _fixture_copy(tmp_path)
    shadow = copy / "aidw" / "prompts" / "update-architecture.md"
    shadow.write_text("E4.7 SHADOW THAT MUST LOSE\n", encoding="utf-8")

    shadowed = _by_id(_plan(target=copy))["I4"]
    assert shadowed.explicit_prompt == "aidw/prompts/architecture-explicit.md"
    assert shadowed.prompt == (copy / "aidw" / "prompts" / "architecture-explicit.md").resolve()
    assert shadowed.prompt != shadow.resolve()


# --------------------------------------------------------------------------- #
# Behaviour 4 — §3.5: the repo-added stage
# --------------------------------------------------------------------------- #


def test_repo_added_stage_plans_with_its_id_agent_and_shadow_prompt() -> None:
    """``lint``: fresh id, declared agent, no variables/extra, prompt from the shadow."""
    specs = _plan(_resolved())
    lint = _by_id(specs)["lint"]

    assert lint.id == lint.name == "lint"
    assert lint.agent_id == "tester"  # the declared agent, not a registry default
    assert lint.variables == []
    assert lint.extra == ""
    assert lint.explicit_prompt is None
    assert lint.prompt == LINT_PROMPT.resolve()
    assert LINT_MARKER in LINT_PROMPT.read_text(encoding="utf-8")
    # Declared after I6, so the plan appends it last rather than interleaving it.
    assert [spec.id for spec in specs][-1] == "lint"

    # The id collides with no registry or loop id (E4.5a's formula: loop ids are the ids
    # ``stages_by_id`` knows minus the static ones), so it cannot shadow a real stage.
    static_ids = {item.id for item in stage_registry.get_workflow(WORKFLOW).stages}
    loop_ids = set(stage_registry.stages_by_id(WORKFLOW)) - static_ids
    assert "lint" not in static_ids | loop_ids


# --------------------------------------------------------------------------- #
# Behaviour 5 — E4.6/N1: the global agent-config override
# --------------------------------------------------------------------------- #


def test_global_agent_config_override_shadows_the_implementer_by_id() -> None:
    """``paths.agent_configs_dir`` shadows by id; un-shadowed agents keep their models.

    The override lives in ``load_all``'s agents dict, **not** on ``StageSpec``: every
    planned spec still carries ``model is None`` (the trap this test pins — a per-stage
    model is a different mechanism, E4.6's D12 metadata override).
    """
    resolved = _resolved()
    override = agent_configs_override(resolved, FIXTURE)
    assert override == IMPLEMENTER_OVERRIDE_DIR

    agents, issues = load_all(toolkit_root(), FIXTURE, override)
    assert [issue for issue in issues if issue.level == ERROR] == []

    implementer = agents["implementer"]
    assert implementer.qualified_model == OVERRIDE_MODEL
    assert implementer.provider == "openrouter"
    assert implementer.source_path == IMPLEMENTER_OVERRIDE

    toolkit_agents, _toolkit_issues = load_all(toolkit_root(), FIXTURE)
    assert toolkit_agents["implementer"].qualified_model != OVERRIDE_MODEL
    for agent_id in ("tester", "recorder", "pr-publisher", "code-reviewer"):
        assert (
            agents[agent_id].qualified_model
            == toolkit_agents[agent_id].qualified_model
        ), agent_id

    # No planned spec carries a per-stage model: the override is the agents-dict layer.
    assert {spec.model for spec in _plan(resolved)} == {None}


def test_dry_run_argv_shows_the_override_on_implementer_stages_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dry-run argv carries the shadowed model for I1 and the toolkit model elsewhere."""
    agents, _override = _agents()
    specs = _by_id(_plan(_resolved()))
    toolkit_agents, _toolkit_issues = load_all(toolkit_root(), FIXTURE)

    implementer_argv, _rendered, implementer_record = _dry_run(
        tmp_path, specs["I1"], agents=agents, monkeypatch=monkeypatch
    )
    tester_argv, _tester_rendered, _tester_record = _dry_run(
        tmp_path, specs["I2"], agents=agents, monkeypatch=monkeypatch
    )
    recorder_argv, _recorder_rendered, _recorder_record = _dry_run(
        tmp_path, specs["I5"], agents=agents, monkeypatch=monkeypatch
    )

    assert _flag(implementer_argv, "--provider") == "openrouter"
    # ``--model`` strips only the agent's own provider prefix (design §5.1), while the
    # recorded model is the qualified one — assert both, never the raw override string.
    assert _flag(implementer_argv, "--model") == OVERRIDE_MODEL_SLUG
    assert implementer_record.model == OVERRIDE_MODEL

    assert _flag(tester_argv, "--model") == model_name(toolkit_agents["tester"])
    assert _flag(recorder_argv, "--model") == model_name(toolkit_agents["recorder"])
    assert _flag(tester_argv, "--model") != OVERRIDE_MODEL_SLUG
    assert _flag(recorder_argv, "--model") != OVERRIDE_MODEL_SLUG
    assert _tester_record.model == toolkit_agents["tester"].qualified_model
    assert _recorder_record.model == toolkit_agents["recorder"].qualified_model


# --------------------------------------------------------------------------- #
# The rendered body at the dry-run seam (design §7.3: frontmatter stripped)
# --------------------------------------------------------------------------- #


def _rendered_body(
    tmp_path: Path,
    stage_id: str,
    *,
    agents: Mapping[str, AgentConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, str]:
    """Dry-run one stage: the text Pi receives, and the resolved file's own body.

    The two differ only by the stage's ``extra`` (I2 carries the test context), so
    comparing them is what proves the *prompt file* — not a second renderer — supplied
    the message, with the frontmatter stripped (design §7.3).
    """
    spec = _by_id(_plan(_resolved()))[stage_id]
    _argv, rendered, _record = _dry_run(
        tmp_path, spec, agents=agents, monkeypatch=monkeypatch
    )
    body = render_prompt_file(spec.prompt, spec.variables)
    assert rendered == (f"{body}\n\n{spec.extra}" if spec.extra else body), stage_id
    assert not rendered.startswith("---"), stage_id
    assert "description:" not in rendered, stage_id
    return rendered, body


def test_dry_run_renders_the_default_fallback_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behaviour 1 at the argv seam: I1's body *is* the toolkit prompt's."""
    agents, _override = _agents()
    spec = _by_id(_plan(_resolved()))["I1"]

    _rendered, body = _rendered_body(
        tmp_path, "I1", agents=agents, monkeypatch=monkeypatch
    )

    assert body == render_prompt_file(_toolkit_prompt("impliment-task.md"), spec.variables)


def test_dry_run_renders_the_filename_shadow_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behaviour 2 at the argv seam: I2 renders the fixture shadow, not the toolkit file."""
    agents, _override = _agents()
    spec = _by_id(_plan(_resolved()))["I2"]

    rendered, body = _rendered_body(
        tmp_path, "I2", agents=agents, monkeypatch=monkeypatch
    )

    assert TEST_MARKER in rendered
    assert body != render_prompt_file(_toolkit_prompt("test.md"), spec.variables)


def test_dry_run_renders_the_explicit_path_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behaviour 3 at the argv seam: I4 renders the declared file, not the toolkit's."""
    agents, _override = _agents()
    spec = _by_id(_plan(_resolved()))["I4"]

    rendered, body = _rendered_body(
        tmp_path, "I4", agents=agents, monkeypatch=monkeypatch
    )

    assert EXPLICIT_MARKER in rendered
    assert body != render_prompt_file(
        _toolkit_prompt("update-architecture.md"), spec.variables
    )


def test_dry_run_renders_the_repo_added_stage_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behaviour 6 at the argv seam: ``lint`` renders its shadow prompt."""
    agents, _override = _agents()

    rendered, _body = _rendered_body(
        tmp_path, "lint", agents=agents, monkeypatch=monkeypatch
    )

    assert LINT_MARKER in rendered


def test_dry_run_invokes_no_real_pi_git_or_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Design §15: ``--dry-run`` is the integration seam — no process is spawned."""
    agents, _override = _agents()
    spec = _by_id(_plan(_resolved()))["I1"]

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a dry run must not spawn a process (design §15)")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.setattr(subprocess, "check_output", _forbidden)

    argv, rendered, record = _dry_run(
        tmp_path, spec, agents=agents, monkeypatch=monkeypatch
    )

    assert argv[0] == "pi"
    assert rendered
    assert record.status == SUCCEEDED


# --------------------------------------------------------------------------- #
# Regression sensitivity: one perturbed input per behaviour, enumerated
# --------------------------------------------------------------------------- #

#: The pinned perturbation set — one entry per behaviour, each changing exactly one fixture
#: input. ``len(PERTURBATIONS)`` is this section's ``numRuns``; the list itself is the seed.
PERTURBATIONS = (
    "filename-shadow",  # behaviour 2
    "explicit-path",  # behaviour 3
    "repo-optional-enabled",  # behaviour 5 (repo-optional disable)
    "repo-added-entry",  # behaviour 6
    "agent-config-override",  # behaviour 7
    "default-stage-shadow",  # behaviour 1
)


def test_the_perturbation_set_covers_every_behaviour() -> None:
    assert len(PERTURBATIONS) == len(set(PERTURBATIONS)) == 6


def test_perturbing_the_filename_shadow_falls_back_to_the_toolkit_prompt(
    tmp_path: Path,
) -> None:
    """Behaviour 2 is load-bearing: rename the shadow and I2 gets the toolkit default."""
    copy = _fixture_copy(tmp_path)
    renamed = copy / "aidw" / "prompts" / "test-renamed.md"
    (copy / "aidw" / "prompts" / "test.md").rename(renamed)

    spec = _by_id(_plan(target=copy))["I2"]

    assert spec.prompt == _toolkit_prompt("test.md")
    assert spec.prompt != renamed.resolve()


def test_perturbing_the_explicit_path_changes_the_i4_prompt(tmp_path: Path) -> None:
    """Behaviour 3 is load-bearing: I4 follows whatever path the config declares."""
    copy = _fixture_copy(tmp_path)
    _edit_config(
        copy,
        lambda data: _stage_entry(data, "I4").update({"prompt": "aidw/prompts/lint.md"}),
    )

    spec = _by_id(_plan(target=copy))["I4"]

    assert spec.explicit_prompt == "aidw/prompts/lint.md"
    assert spec.prompt == (copy / "aidw" / "prompts" / "lint.md").resolve()
    assert spec.prompt != (copy / "aidw" / "prompts" / "architecture-explicit.md").resolve()


def test_perturbing_i3_back_to_enabled_plans_it_in_registry_order(tmp_path: Path) -> None:
    """Behaviour 5 is load-bearing: ``enabled: false`` (not omission) is what drops I3."""
    copy = _fixture_copy(tmp_path)
    _edit_config(copy, lambda data: _stage_entry(data, "I3").pop("enabled"))

    specs = _plan(target=copy)
    ids = [spec.id for spec in specs]

    # Registry position, asserted against I2/I4 rather than a full plan literal, so this
    # check stays about I3 and cannot double as the repo-added stage's presence check.
    assert ids.index("I2") < ids.index("I3") < ids.index("I4")
    i3 = _by_id(specs)["I3"]
    assert i3.name == "update-traceability"
    assert i3.prompt == _toolkit_prompt("update-traceability.md")


def test_perturbing_away_the_repo_added_entry_removes_it(tmp_path: Path) -> None:
    """Behaviour 6 is load-bearing: ``lint`` exists only because the config declares it."""
    copy = _fixture_copy(tmp_path)
    baseline = [spec.id for spec in _plan(target=copy)]
    _edit_config(copy, lambda data: data["workflows"]["implement"]["stages"].pop())

    after = [spec.id for spec in _plan(target=copy)]

    assert baseline[-1] == "lint"
    assert after == [stage_id for stage_id in baseline if stage_id != "lint"]


def test_perturbing_away_the_agent_config_override_restores_the_toolkit_model(
    tmp_path: Path,
) -> None:
    """Behaviour 7 is load-bearing: an empty override dir is the toolkit defaults."""
    copy = _fixture_copy(tmp_path)
    (copy / "aidw" / "agent-configs" / "implementer.yaml").unlink()

    agents, override = _agents(copy)
    toolkit_agents, _toolkit_issues = load_all(toolkit_root(), FIXTURE)

    assert override == copy / "aidw" / "agent-configs"  # still declared, now empty
    assert (
        agents["implementer"].qualified_model
        == toolkit_agents["implementer"].qualified_model
    )
    assert agents["implementer"].qualified_model != OVERRIDE_MODEL


def test_perturbing_in_a_shadow_for_a_default_stage_stops_the_fallback(
    tmp_path: Path,
) -> None:
    """Behaviour 1 is load-bearing: any same-named shadow beats the toolkit default."""
    copy = _fixture_copy(tmp_path)
    shadow = copy / "aidw" / "prompts" / "pr.md"
    shadow.write_text(
        "---\ndescription: perturbed shadow\n---\nE4.7 PERTURBED I6 SHADOW\n",
        encoding="utf-8",
    )

    spec = _by_id(_plan(target=copy))["I6"]

    assert spec.prompt == shadow.resolve()
    assert spec.prompt != _toolkit_prompt("pr.md")


# --------------------------------------------------------------------------- #
# Fail-closed: a resolved prompt is never a silent skip (§3.4 level 4)
# --------------------------------------------------------------------------- #


def test_dropping_the_repo_added_stages_shadow_fails_closed(tmp_path: Path) -> None:
    """A repo-added stage with no resolvable prompt raises, naming the stage."""
    copy = _fixture_copy(tmp_path)
    (copy / "aidw" / "prompts" / "lint.md").unlink()

    with pytest.raises(FileNotFoundError) as excinfo:
        _plan(target=copy)

    assert "lint" in str(excinfo.value)


def test_missing_explicit_path_does_not_fall_through_to_a_shadow(tmp_path: Path) -> None:
    """Level 1 never falls back to level 2: a declared-but-missing path is an error."""
    copy = _fixture_copy(tmp_path)
    (copy / "aidw" / "prompts" / "update-architecture.md").write_text(
        "E4.7 SHADOW THAT MUST NOT BE REACHED\n", encoding="utf-8"
    )
    _edit_config(
        copy,
        lambda data: _stage_entry(data, "I4").update(
            {"prompt": "aidw/prompts/missing.md"}
        ),
    )

    with pytest.raises(FileNotFoundError) as excinfo:
        _plan(target=copy)

    message = str(excinfo.value)
    assert "explicit_path is set" in message
    assert str(copy / "aidw" / "prompts" / "missing.md") in message


def test_dropping_a_core_id_from_the_declared_list_is_refused(tmp_path: Path) -> None:
    """Trap guard: a declared list *replaces* the static half, so a missing I5 refuses.

    Listing only the overridden ids would be a "removal" (D12) — the plan path raises the
    validator's own ``StageListError`` instead of planning a shorter chain.
    """
    copy = _fixture_copy(tmp_path)
    _edit_config(copy, lambda data: data["workflows"]["implement"]["stages"].pop(4))

    with pytest.raises(stage_registry.StageListError) as excinfo:
        _plan(target=copy)

    assert "I5" in str(excinfo.value)
    assert "cannot be removed" in str(excinfo.value)
