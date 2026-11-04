"""Tests for agent config loading and validation."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
import yaml

from aidw.config import (
    ERROR,
    WARNING,
    AgentConfig,
    SystemPrompt,
    check_independence,
    check_read_only,
    load_all,
    load_agent,
)
from aidw.paths import toolkit_root, repo_root

EXPECTED_AGENTS = {
    "task-author",
    "task-reviewer",
    "implementer",
    "tester",
    "recorder",
    "pr-publisher",
    "code-reviewer",
    "review-publisher",
    "review-approver",
    "fixer",
    "task-fixer",
}


def make_agent(agent_id: str, model: str = "vendor/model", **overrides: object) -> AgentConfig:
    defaults: dict[str, object] = dict(
        description="",
        provider="openrouter",
        model=model,
        thinking="high",
        system_prompt=SystemPrompt(),
        agents_md=None,
        agents_md_content=None,
        tools=["read"],
        skills=[],
        extensions=[],
        prompt_templates=[],
        mcp_config=None,
        cwd=Path("."),
        env={},
        session="fresh",
        timeout_seconds=60,
        max_cost_usd=None,
        output="json",
        no_context_files=False,
        source_path=Path(f"{agent_id}.yaml"),
    )
    defaults.update(overrides)
    return AgentConfig(id=agent_id, **defaults)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def real_agents() -> dict[str, AgentConfig]:
    agents, issues = load_all(toolkit_root(), repo_root())
    assert not [i for i in issues if i.level == ERROR], issues
    return agents


def test_all_expected_agents_load(real_agents: dict[str, AgentConfig]) -> None:
    assert set(real_agents) == EXPECTED_AGENTS


def test_real_configs_have_no_issues(real_agents: dict[str, AgentConfig]) -> None:
    for agent in real_agents.values():
        assert agent.issues == [], (agent.id, agent.issues)


def test_qualified_model_has_provider_prefix(real_agents: dict[str, AgentConfig]) -> None:
    for agent in real_agents.values():
        assert agent.qualified_model.startswith(agent.provider + "/")


def test_reviewers_are_read_only(real_agents: dict[str, AgentConfig]) -> None:
    for agent_id in ("task-reviewer", "code-reviewer"):
        assert "write" not in real_agents[agent_id].tools
        assert "edit" not in real_agents[agent_id].tools


def test_independence_holds_for_real_configs(real_agents: dict[str, AgentConfig]) -> None:
    assert check_independence(real_agents) == []


def _minimal_config(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "task-author",
        "provider": "openrouter",
        "model": "vendor/model",
        "tools": ["read"],
    }
    base.update(overrides)
    return base


def _write_agent(tmp_path: Path, name: str, config: dict[str, object]) -> Path:
    config_dir = tmp_path / "aidt" / "agent-configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "aidt" / "prompts").mkdir(parents=True, exist_ok=True)
    path = config_dir / f"{name}.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def test_invalid_thinking_is_error(tmp_path: Path) -> None:
    path = _write_agent(tmp_path, "task-author", _minimal_config(thinking="super"))
    agent = load_agent(path, tmp_path / "aidt", tmp_path)
    assert any(i.level == ERROR and "thinking" in i.message for i in agent.issues)


def test_missing_required_provider_is_error(tmp_path: Path) -> None:
    config = _minimal_config()
    config.pop("provider")
    path = _write_agent(tmp_path, "task-author", config)
    agent = load_agent(path, tmp_path / "aidt", tmp_path)
    assert any(i.level == ERROR and "provider" in i.message for i in agent.issues)


def test_id_mismatch_is_error(tmp_path: Path) -> None:
    path = _write_agent(tmp_path, "task-author", _minimal_config(id="other"))
    agent = load_agent(path, tmp_path / "aidt", tmp_path)
    assert any(i.level == ERROR and "match filename" in i.message for i in agent.issues)


def test_missing_prompt_template_is_error(tmp_path: Path) -> None:
    path = _write_agent(
        tmp_path, "task-author", _minimal_config(prompt_templates=["prompts"])
    )
    import shutil

    shutil.rmtree(tmp_path / "aidt" / "prompts")
    agent = load_agent(path, tmp_path / "aidt", tmp_path)
    assert any(i.level == ERROR and "prompt_templates" in i.message for i in agent.issues)


def test_independence_warning_when_models_match() -> None:
    agents = {
        "task-author": make_agent("task-author", "openrouter/vendor/same"),
        "task-reviewer": make_agent("task-reviewer", "openrouter/vendor/same"),
    }
    issues = check_independence(agents)
    assert any(i.level == WARNING and i.source == "task-reviewer" for i in issues)


def test_independence_covers_the_prompt_reviewer_and_task_fixer() -> None:
    """`task-reviewer` re-reviews the prompt `task-fixer` just revised."""
    agents = {
        "task-fixer": make_agent("task-fixer", "openrouter/vendor/same"),
        "task-reviewer": make_agent("task-reviewer", "openrouter/vendor/same"),
    }
    issues = check_independence(agents)
    assert any(i.level == WARNING and i.source == "task-reviewer" for i in issues)


def test_no_independence_warning_for_distinct_models() -> None:
    agents = {
        "task-fixer": make_agent("task-fixer", "openrouter/vendor/one"),
        "task-reviewer": make_agent("task-reviewer", "openrouter/vendor/two"),
    }
    assert check_independence(agents) == []


def test_read_only_check_flags_task_reviewer_with_write() -> None:
    reviewer = make_agent("task-reviewer", tools=["read", "write"])
    issues = check_read_only(reviewer)
    assert any(i.level == WARNING and "write" in i.message for i in issues)


def test_read_only_check_ignores_tester() -> None:
    """``tester`` is a reviewer that legitimately writes tests."""
    tester = make_agent("tester", tools=["read", "bash", "write", "edit"])
    assert check_read_only(tester) == []


# --------------------------------------------------------------------------- #
# E4.6: the global agent-config override (`paths.agent_configs_dir`)
# --------------------------------------------------------------------------- #


def _config_dir(root: Path, name: str = "agent-configs") -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write_agent_config(directory: Path, agent_id: str, **fields: object) -> Path:
    """A minimal valid agent config: no path fields, so no toolkit assets are needed."""
    config: dict[str, object] = {
        "id": agent_id,
        "description": f"{agent_id} fixture",
        "provider": "openrouter",
        "model": f"vendor/{agent_id}",
        "thinking": "low",
        "tools": ["read"],
    }
    config.update(fields)
    path = directory / f"{agent_id}.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def _toolkit_with(tmp_path: Path, *agents: str) -> Path:
    # Every fixture resolves ``cwd`` against this root, so it must exist.
    (tmp_path / "target").mkdir(exist_ok=True)
    toolkit = tmp_path / "toolkit"
    directory = _config_dir(toolkit)
    for agent_id in agents:
        _write_agent_config(directory, agent_id)
    return toolkit


def test_override_dir_shadows_by_id_and_keeps_un_overridden_agents(tmp_path: Path) -> None:
    """Shadow by id: the override wins for its id; every other toolkit agent still loads."""
    toolkit = _toolkit_with(tmp_path, "implementer", "tester")
    override = _config_dir(tmp_path / "target", "agent-configs")
    _write_agent_config(
        override,
        "implementer",
        model="vendor/override",
        thinking="max",
        tools=["read", "bash"],
    )

    agents, issues = load_all(toolkit, tmp_path / "target", override)

    assert [issue for issue in issues if issue.level == ERROR] == []
    assert set(agents) == {"implementer", "tester"}
    assert agents["implementer"].model == "vendor/override"
    assert agents["implementer"].thinking == "max"
    assert agents["implementer"].tools == ["read", "bash"]
    assert agents["implementer"].source_path.parent == override
    # The un-overridden toolkit agent is untouched.
    assert agents["tester"].model == "vendor/tester"
    assert agents["tester"].thinking == "low"


def test_override_dir_brand_new_id_loads_as_an_additional_agent(tmp_path: Path) -> None:
    """Shadow semantics are additive: an id the toolkit lacks becomes a legal agent."""
    toolkit = _toolkit_with(tmp_path, "implementer")
    override = _config_dir(tmp_path / "target", "agent-configs")
    _write_agent_config(override, "auditor", model="vendor/auditor")

    agents, issues = load_all(toolkit, tmp_path / "target", override)

    assert [issue for issue in issues if issue.level == ERROR] == []
    assert set(agents) == {"implementer", "auditor"}
    assert agents["auditor"].model == "vendor/auditor"


def test_empty_override_dir_equals_the_toolkit_defaults(tmp_path: Path) -> None:
    """An empty directory is legal and changes nothing."""
    toolkit = _toolkit_with(tmp_path, "implementer", "tester")
    override = _config_dir(tmp_path / "target", "agent-configs")

    base_agents, base_issues = load_all(toolkit, tmp_path / "target")
    agents, issues = load_all(toolkit, tmp_path / "target", override)

    assert agents == base_agents
    assert issues == base_issues


def test_named_but_missing_override_dir_is_an_error(tmp_path: Path) -> None:
    """§3.4: a configured read-path must exist; this is the preflights' exit-2 refusal."""
    toolkit = _toolkit_with(tmp_path, "implementer")
    missing = tmp_path / "target" / "aidw" / "agent-configs"

    agents, issues = load_all(toolkit, tmp_path / "target", missing)

    errors = [issue for issue in issues if issue.level == ERROR]
    assert len(errors) == 1, issues
    # Same shape as the toolkit dir-not-found issue: the path is the issue's source.
    assert errors[0].source == str(missing)
    assert errors[0].message == "agent-configs directory not found"
    # The toolkit agents were still loaded, so a caller can report and stop cleanly.
    assert set(agents) == {"implementer"}


def test_independence_is_checked_on_the_shadowed_agents(tmp_path: Path) -> None:
    """Trap: shadow-then-validate — the §5.4 warning must see the value actually used."""
    toolkit = _toolkit_with(tmp_path, "implementer", "code-reviewer")
    override = _config_dir(tmp_path / "target", "agent-configs")
    _write_agent_config(
        override, "code-reviewer", model="vendor/implementer", tools=["read"]
    )

    agents, issues = load_all(toolkit, tmp_path / "target", override)

    assert agents["code-reviewer"].model == agents["implementer"].model
    warnings = [issue for issue in issues if issue.level == WARNING]
    assert any(
        issue.source == "code-reviewer" and "reviewer != author" in issue.message
        for issue in warnings
    ), issues
    # With no override the two models differ, so that warning cannot come from the toolkit.
    base_agents, base_issues = load_all(toolkit, tmp_path / "target")
    assert check_independence(base_agents) == []
    assert [i for i in base_issues if i.level == WARNING] == []


def test_read_only_check_runs_on_the_shadowed_agent(tmp_path: Path) -> None:
    """The other §5.4/§5.2 check is also on the effective dict, not the toolkit's."""
    toolkit = _toolkit_with(tmp_path, "code-reviewer")
    override = _config_dir(tmp_path / "target", "agent-configs")
    _write_agent_config(override, "code-reviewer", tools=["read", "write"])

    agents, issues = load_all(toolkit, tmp_path / "target", override)

    assert agents["code-reviewer"].tools == ["read", "write"]
    assert any(
        issue.level == WARNING and "mutating tool `write`" in issue.message
        for issue in issues
    ), issues


#: Pinned seed + run count for the override-merge property below (AGENTS.md: pytest only,
#: no hypothesis, so a reproducible seeded sample is the generator).
OVERRIDE_PROPERTY_SEED = 4611
OVERRIDE_PROPERTY_RUNS = 64


def test_override_merge_property(tmp_path: Path) -> None:
    """Seeded property run (seed/runs pinned above) over random shadow subsets.

    For every subset of the toolkit's ids that the override directory also defines:
    the merged ids are exactly the union, each overridden id carries the override's
    model/thinking/tools, each untouched id keeps the toolkit's, no error is reported,
    and neither input dict is mutated.
    """
    toolkit_ids = ("implementer", "tester", "recorder")
    rng = random.Random(OVERRIDE_PROPERTY_SEED)

    for index in range(OVERRIDE_PROPERTY_RUNS):
        root = tmp_path / f"case-{index}"
        root.mkdir()
        toolkit = _toolkit_with(root, *toolkit_ids)
        override = _config_dir(root / "target", "agent-configs")
        shadowed = [agent_id for agent_id in toolkit_ids if rng.random() < 0.5]
        for agent_id in shadowed:
            _write_agent_config(
                override,
                agent_id,
                model=f"override/{agent_id}",
                thinking="xhigh",
                tools=["read", "bash"],
            )

        agents, issues = load_all(toolkit, root / "target", override)

        assert [issue for issue in issues if issue.level == ERROR] == [], index
        assert set(agents) == set(toolkit_ids), index
        for agent_id in toolkit_ids:
            expected = (
                f"override/{agent_id}" if agent_id in shadowed else f"vendor/{agent_id}"
            )
            assert agents[agent_id].model == expected, (index, agent_id)
            assert agents[agent_id].thinking == (
                "xhigh" if agent_id in shadowed else "low"
            ), (index, agent_id)
            assert agents[agent_id].tools == (
                ["read", "bash"] if agent_id in shadowed else ["read"]
            ), (index, agent_id)

        # The toolkit-only load is unchanged by the shadowing (no shared mutation).
        base_agents, _ = load_all(toolkit, root / "target")
        assert {aid: agent.model for aid, agent in base_agents.items()} == {
            agent_id: f"vendor/{agent_id}" for agent_id in toolkit_ids
        }, index
