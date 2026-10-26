"""Tests for agent config loading and validation."""

from __future__ import annotations

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
