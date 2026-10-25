"""Tests for Pi argv construction."""

from __future__ import annotations

from aidw.agents import build_argv, build_env, model_name
from aidw.config import AgentConfig, SystemPrompt
from aidw.paths import aidt_root, repo_root
import pytest


@pytest.fixture(scope="module")
def agents() -> dict[str, AgentConfig]:
    from aidw.config import load_all

    loaded, issues = load_all(aidt_root(), repo_root())
    assert not [i for i in issues if i.level == "error"], issues
    return loaded


def test_model_name_strips_provider_prefix(agents: dict[str, AgentConfig]) -> None:
    agent = agents["implementer"]
    stripped = agent.model[len(f"{agent.provider}/") :]
    assert model_name(agent) == stripped
    assert not model_name(agent).startswith(f"{agent.provider}/")


def test_standard_flags_present(agents: dict[str, AgentConfig]) -> None:
    argv = build_argv(agents["task-author"])
    assert argv[0] == "pi"
    assert "--provider" in argv
    assert "--model" in argv
    assert "-p" in argv
    assert "--approve" in argv
    assert ["--mode", "json"] == argv[argv.index("--mode") : argv.index("--mode") + 2]


def test_tool_allowlist_rendered(agents: dict[str, AgentConfig]) -> None:
    argv = build_argv(agents["code-reviewer"])
    assert ["--tools", "read,bash"] == argv[argv.index("--tools") : argv.index("--tools") + 2]
    assert "--no-tools" not in argv


def test_reviewer_gets_no_mutating_tools(agents: dict[str, AgentConfig]) -> None:
    argv = build_argv(agents["code-reviewer"])
    tools = argv[argv.index("--tools") + 1]
    assert "write" not in tools
    assert "edit" not in tools


def test_session_id_used_when_supplied(agents: dict[str, AgentConfig]) -> None:
    argv = build_argv(agents["implementer"], session_id="aidw-run-implementer")
    assert ["--session-id", "aidw-run-implementer"] == argv[
        argv.index("--session-id") : argv.index("--session-id") + 2
    ]
    assert "--no-session" not in argv


def test_no_session_when_id_absent(agents: dict[str, AgentConfig]) -> None:
    argv = build_argv(agents["implementer"])
    assert "--no-session" in argv
    assert "--session-id" not in argv


def test_agents_md_appended(agents: dict[str, AgentConfig]) -> None:
    argv = build_argv(agents["implementer"])
    appended = [argv[i + 1] for i, flag in enumerate(argv) if flag == "--append-system-prompt"]
    assert any("implementer" in content.lower() for content in appended)
    assert any("one task prompt as code" in content for content in appended)


def test_system_prompt_append_file_inlined(agents: dict[str, AgentConfig]) -> None:
    argv = build_argv(agents["code-reviewer"])
    appended = [argv[i + 1] for i, flag in enumerate(argv) if flag == "--append-system-prompt"]
    assert any("independent code reviewer" in content for content in appended)
    assert "--system-prompt" not in argv


def test_prompt_template_and_mcp_flags(agents: dict[str, AgentConfig]) -> None:
    argv = build_argv(agents["task-author"])
    assert "--prompt-template" in argv
    assert argv[argv.index("--prompt-template") + 1].endswith("/prompts")


def test_empty_tools_means_no_tools() -> None:
    agent = AgentConfig(
        id="bare",
        description="",
        provider="openrouter",
        model="vendor/model",
        thinking="off",
        system_prompt=SystemPrompt(),
        agents_md=None,
        agents_md_content=None,
        tools=[],
        skills=[],
        extensions=[],
        prompt_templates=[],
        mcp_config=None,
        cwd=repo_root(),
        env={},
        session="fresh",
        timeout_seconds=60,
        max_cost_usd=None,
        output="text",
        no_context_files=False,
        source_path=repo_root() / "x.yaml",
    )
    argv = build_argv(agent)
    assert "--no-tools" in argv
    assert "--mode" not in argv  # text output


def test_override_system_prompt_uses_system_prompt_flag() -> None:
    agent = AgentConfig(
        id="override",
        description="",
        provider="openrouter",
        model="vendor/model",
        thinking="off",
        system_prompt=SystemPrompt(mode="override", content="CUSTOM"),
        agents_md=None,
        agents_md_content=None,
        tools=["read"],
        skills=[],
        extensions=[],
        prompt_templates=[],
        mcp_config=None,
        cwd=repo_root(),
        env={},
        session="fresh",
        timeout_seconds=60,
        max_cost_usd=None,
        output="text",
        no_context_files=False,
        source_path=repo_root() / "x.yaml",
    )
    argv = build_argv(agent)
    assert ["--system-prompt", "CUSTOM"] == argv[
        argv.index("--system-prompt") : argv.index("--system-prompt") + 2
    ]


def test_build_env_merges_overrides(agents: dict[str, AgentConfig]) -> None:
    agent = agents["task-author"]
    agent.env["AIDW_TEST"] = "1"
    env = build_env(agent, {"BASE": "yes"})
    assert env["BASE"] == "yes"
    assert env["AIDW_TEST"] == "1"
