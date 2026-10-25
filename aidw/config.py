"""Agent configuration loading and validation (design §5).

One YAML file per agent under ``aidt/agent-configs/``. Configuration is validated on
load; :func:`load_all` returns both the parsed agents and a list of issues so callers
can decide whether warnings are fatal (``--strict``).

Path resolution (design §5.1):

- ``cwd`` is relative to the **repository root** (default ``.``).
- ``agents_md``, ``system_prompt.file``, ``mcp_config`` and every entry of ``skills``,
  ``extensions`` and ``prompt_templates`` are relative to the **aidt root**
  (so ``../.mcp.json`` means ``<repo>/.mcp.json`` and ``prompts`` means
  ``<repo>/aidt/prompts``).
- Absolute paths are used as-is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
SESSION_MODES = ("fresh", "shared")
OUTPUT_MODES = ("json", "text")
SYSTEM_PROMPT_MODES = ("append", "override", "none")

#: Pi built-in tools. Extension, custom, and MCP tool names are also valid in an
#: allowlist; unknown names produce a warning, not an error.
BUILTIN_TOOLS = ("read", "bash", "powershell", "edit", "write", "grep", "find", "ls")

#: Reviewer agents must not be able to mutate the tree.
READ_ONLY_MARKERS = ("write", "edit")

#: Reviewer agents that are strictly read-only. ``tester`` is a reviewer that legitimately
#: writes *tests*, so it is not in this set.
READ_ONLY_AGENTS = ("task-reviewer", "code-reviewer")

#: (reviewer, author) pairs that must use different models (design §5.4).
INDEPENDENCE_RULES = (
    ("task-reviewer", "task-author"),
    # The prompt reviewer re-reviews the prompt that `task-fixer` just revised.
    ("task-reviewer", "task-fixer"),
    ("tester", "implementer"),
    ("code-reviewer", "implementer"),
    ("tester", "code-reviewer"),
)

ERROR = "error"
WARNING = "warning"


@dataclass
class Issue:
    level: str
    source: str
    message: str

    def __str__(self) -> str:
        return f"{self.level}: {self.source}: {self.message}"


@dataclass
class SystemPrompt:
    mode: str = "append"
    file: Path | None = None
    content: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "file": str(self.file) if self.file else None,
        }


@dataclass
class AgentConfig:
    id: str
    description: str
    provider: str
    model: str
    thinking: str
    system_prompt: SystemPrompt
    agents_md: Path | None
    agents_md_content: str | None
    tools: list[str]
    skills: list[Path]
    extensions: list[Path]
    prompt_templates: list[Path]
    mcp_config: Path | None
    cwd: Path
    env: dict[str, str]
    session: str
    timeout_seconds: int
    max_cost_usd: float | None
    output: str
    no_context_files: bool
    source_path: Path
    issues: list[Issue] = field(default_factory=list)

    @property
    def qualified_model(self) -> str:
        """A ``provider/model`` string suitable for Pi's ``--model``."""
        if "/" in self.model and self.model.split("/", 1)[0] == self.provider:
            return self.model
        return f"{self.provider}/{self.model}"

    @property
    def label(self) -> str:
        return f"{self.id} ({self.qualified_model})"


def _resolve(path_value: str, base: Path) -> Path:
    candidate = Path(path_value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (base / candidate).resolve()


def _require(config: dict[str, Any], key: str, source: str, issues: list[Issue]) -> Any:
    value = config.get(key)
    if value is None or value == "":
        issues.append(Issue(ERROR, source, f"missing required field `{key}`"))
    return value


def _load_system_prompt(
    raw: Any, aidt_root: Path, source: str, issues: list[Issue]
) -> SystemPrompt:
    if raw is None:
        return SystemPrompt(mode="none")

    if isinstance(raw, str):
        raw = {"mode": raw}

    if not isinstance(raw, dict):
        issues.append(Issue(ERROR, source, "`system_prompt` must be a mapping or string"))
        return SystemPrompt(mode="none")

    mode = str(raw.get("mode", "append"))
    if mode not in SYSTEM_PROMPT_MODES:
        issues.append(
            Issue(
                ERROR,
                source,
                f"invalid system_prompt.mode `{mode}` (expected one of {SYSTEM_PROMPT_MODES})",
            )
        )
        return SystemPrompt(mode="none")

    if mode == "none":
        return SystemPrompt(mode="none")

    file_value = raw.get("file")
    if not file_value:
        issues.append(
            Issue(ERROR, source, f"system_prompt.mode `{mode}` requires `system_prompt.file`")
        )
        return SystemPrompt(mode=mode)

    path = _resolve(str(file_value), aidt_root)
    if not path.is_file():
        issues.append(Issue(ERROR, source, f"system_prompt.file not found: {path}"))
        return SystemPrompt(mode=mode, file=path)

    return SystemPrompt(mode=mode, file=path, content=path.read_text(encoding="utf-8"))


def _load_path_list(
    raw: Any, base: Path, field_name: str, source: str, issues: list[Issue]
) -> list[Path]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        issues.append(Issue(ERROR, source, f"`{field_name}` must be a list"))
        return []
    paths: list[Path] = []
    for entry in raw:
        path = _resolve(str(entry), base)
        if not path.exists():
            issues.append(
                Issue(ERROR, source, f"{field_name} entry not found: {path}")
            )
        paths.append(path)
    return paths


def load_agent(
    path: Path, aidt_root: Path, repo_root: Path
) -> AgentConfig:
    """Load and validate a single agent config file."""
    source = path.name
    issues: list[Issue] = []

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        issues.append(Issue(ERROR, source, f"cannot read/parse config: {exc}"))
        raw = None

    if not isinstance(raw, dict):
        issues.append(Issue(ERROR, source, "config must be a YAML mapping"))
        raw = {}

    agent_id = str(raw.get("id") or path.stem)
    if agent_id != path.stem:
        issues.append(
            Issue(ERROR, source, f"`id` ({agent_id}) must match filename stem ({path.stem})")
        )

    provider = str(_require(raw, "provider", source, issues) or "")
    model = str(_require(raw, "model", source, issues) or "")

    thinking = str(raw.get("thinking", "medium"))
    if thinking not in THINKING_LEVELS:
        issues.append(
            Issue(ERROR, source, f"invalid thinking `{thinking}` (expected {THINKING_LEVELS})")
        )

    session = str(raw.get("session", "fresh"))
    if session not in SESSION_MODES:
        issues.append(
            Issue(ERROR, source, f"invalid session `{session}` (expected {SESSION_MODES})")
        )

    output = str(raw.get("output", "json"))
    if output not in OUTPUT_MODES:
        issues.append(
            Issue(ERROR, source, f"invalid output `{output}` (expected {OUTPUT_MODES})")
        )

    timeout_raw = raw.get("timeout_seconds", 3600)
    try:
        timeout_seconds = int(timeout_raw)
    except (TypeError, ValueError):
        issues.append(Issue(ERROR, source, f"`timeout_seconds` must be an integer: {timeout_raw!r}"))
        timeout_seconds = 3600
    if timeout_seconds <= 0:
        issues.append(Issue(ERROR, source, "`timeout_seconds` must be positive"))

    max_cost_usd: float | None = raw.get("max_cost_usd")
    if max_cost_usd is not None:
        try:
            max_cost_usd = float(max_cost_usd)
        except (TypeError, ValueError):
            issues.append(Issue(ERROR, source, f"`max_cost_usd` must be a number: {max_cost_usd!r}"))
            max_cost_usd = None

    tools_raw = raw.get("tools")
    tools: list[str] = []
    if tools_raw is None:
        tools = []
    elif isinstance(tools_raw, list):
        tools = [str(item) for item in tools_raw]
        for tool in tools:
            if tool not in BUILTIN_TOOLS:
                issues.append(
                    Issue(WARNING, source, f"tool `{tool}` is not a known built-in; ensure an extension/MCP provides it")
                )
    else:
        issues.append(Issue(ERROR, source, "`tools` must be a list"))

    agents_md_raw = raw.get("agents_md")
    agents_md: Path | None = None
    agents_md_content: str | None = None
    if agents_md_raw:
        agents_md = _resolve(str(agents_md_raw), aidt_root)
        if not agents_md.is_file():
            issues.append(Issue(ERROR, source, f"agents_md not found: {agents_md}"))
        else:
            agents_md_content = agents_md.read_text(encoding="utf-8")

    mcp_raw = raw.get("mcp_config")
    mcp_config: Path | None = None
    if mcp_raw:
        mcp_config = _resolve(str(mcp_raw), aidt_root)
        if not mcp_config.is_file():
            issues.append(Issue(ERROR, source, f"mcp_config not found: {mcp_config}"))

    cwd_raw = str(raw.get("cwd", "."))
    cwd = _resolve(cwd_raw, repo_root)
    if not cwd.is_dir():
        issues.append(Issue(ERROR, source, f"cwd not found: {cwd}"))

    env_raw = raw.get("env") or {}
    if not isinstance(env_raw, dict):
        issues.append(Issue(ERROR, source, "`env` must be a mapping"))
        env_raw = {}
    env = {str(k): str(v) for k, v in env_raw.items()}

    return AgentConfig(
        id=agent_id,
        description=str(raw.get("description", "")),
        provider=provider,
        model=model,
        thinking=thinking,
        system_prompt=_load_system_prompt(raw.get("system_prompt"), aidt_root, source, issues),
        agents_md=agents_md,
        agents_md_content=agents_md_content,
        tools=tools,
        skills=_load_path_list(raw.get("skills"), aidt_root, "skills", source, issues),
        extensions=_load_path_list(raw.get("extensions"), aidt_root, "extensions", source, issues),
        prompt_templates=_load_path_list(
            raw.get("prompt_templates"), aidt_root, "prompt_templates", source, issues
        ),
        mcp_config=mcp_config,
        cwd=cwd,
        env=env,
        session=session,
        timeout_seconds=timeout_seconds,
        max_cost_usd=max_cost_usd,
        output=output,
        no_context_files=bool(raw.get("no_context_files", False)),
        source_path=path,
        issues=issues,
    )


def load_all(
    aidt_root: Path, repo_root: Path
) -> tuple[dict[str, AgentConfig], list[Issue]]:
    """Load every ``*.yaml`` under ``aidt/agent-configs/``.

    Returns the agents keyed by id and the combined issue list (per-agent errors plus
    cross-agent independence checks).
    """
    config_dir = aidt_root / "agent-configs"
    agents: dict[str, AgentConfig] = {}
    issues: list[Issue] = []

    if not config_dir.is_dir():
        issues.append(Issue(ERROR, str(config_dir), "agent-configs directory not found"))
        return agents, issues

    for path in sorted(config_dir.glob("*.yaml")):
        agent = load_agent(path, aidt_root, repo_root)
        if agent.id in agents:
            issues.append(Issue(ERROR, path.name, f"duplicate agent id `{agent.id}`"))
        agents[agent.id] = agent
        issues.extend(agent.issues)

    issues.extend(check_independence(agents))
    for agent in agents.values():
        issues.extend(check_read_only(agent))
    return agents, issues


def check_independence(agents: dict[str, AgentConfig]) -> list[Issue]:
    """Model-independence checks for the author/judge reviewer rules."""
    issues: list[Issue] = []
    for reviewer_id, author_id in INDEPENDENCE_RULES:
        reviewer = agents.get(reviewer_id)
        author = agents.get(author_id)
        if not reviewer or not author:
            continue
        if reviewer.qualified_model == author.qualified_model:
            issues.append(
                Issue(
                    WARNING,
                    reviewer_id,
                    f"model matches `{author_id}` ({reviewer.qualified_model}); "
                    "the workflow requires reviewer != author",
                )
            )
    return issues


def check_read_only(agent: AgentConfig) -> list[Issue]:
    """Strictly read-only reviewer agents must not hold mutating tools."""
    issues: list[Issue] = []
    if agent.id in READ_ONLY_AGENTS:
        for tool in agent.tools:
            if tool in READ_ONLY_MARKERS:
                issues.append(
                    Issue(
                        WARNING,
                        agent.id,
                        f"reviewer agent allows mutating tool `{tool}`",
                    )
                )
    return issues


def format_issues(issues: list[Issue]) -> str:
    return "\n".join(str(issue) for issue in issues)
