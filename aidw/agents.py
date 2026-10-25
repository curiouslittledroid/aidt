"""Translate an :class:`AgentConfig` into a Pi command line (design §5.1, §7.3).

The rendered prompt itself is **not** part of the argv: AIDW pipes it to Pi on stdin
(``pi -p`` reads piped stdin as the prompt, verified against Pi 0.85.x). AIDW reads
``agents_md`` / ``system_prompt.file`` and passes their *contents* to
``--append-system-prompt`` / ``--system-prompt`` rather than paths, so behaviour does
not depend on Pi's path-vs-literal detection.
"""

from __future__ import annotations

from aidw.config import AgentConfig


def model_name(agent: AgentConfig) -> str:
    """Return the model id with any ``provider/`` prefix removed (passed via --provider)."""
    prefix = f"{agent.provider}/"
    if agent.model.startswith(prefix):
        return agent.model[len(prefix) :]
    return agent.model


def build_argv(
    agent: AgentConfig,
    *,
    session_id: str | None = None,
) -> list[str]:
    """Build the Pi argv (excluding the prompt, which goes on stdin)."""
    argv: list[str] = [
        "pi",
        "--provider",
        agent.provider,
        "--model",
        model_name(agent),
        "--thinking",
        agent.thinking,
        "-p",
        "--approve",
    ]

    if agent.output == "json":
        argv += ["--mode", "json"]

    if session_id:
        argv += ["--session-id", session_id]
    else:
        argv += ["--no-session"]

    # System prompt: override replaces Pi's default; append adds to it.
    if agent.system_prompt.mode == "override" and agent.system_prompt.content:
        argv += ["--system-prompt", agent.system_prompt.content]
    elif agent.system_prompt.mode == "append" and agent.system_prompt.content:
        argv += ["--append-system-prompt", agent.system_prompt.content]

    # Per-agent context file is always appended, in every mode.
    if agent.agents_md_content:
        argv += ["--append-system-prompt", agent.agents_md_content]

    # Tool allowlist (deny-by-default). Empty means no tools at all.
    if agent.tools:
        argv += ["--tools", ",".join(agent.tools)]
    else:
        argv += ["--no-tools"]

    for path in agent.skills:
        argv += ["--skill", str(path)]
    for path in agent.extensions:
        argv += ["--extension", str(path)]
    for path in agent.prompt_templates:
        argv += ["--prompt-template", str(path)]

    if agent.mcp_config:
        argv += ["--mcp-config", str(agent.mcp_config)]

    if agent.no_context_files:
        argv += ["--no-context-files"]

    return argv


def build_env(agent: AgentConfig, base_env: dict[str, str]) -> dict[str, str]:
    """Return the subprocess environment: inherited env plus the agent overrides."""
    env = dict(base_env)
    env.update(agent.env)
    return env
