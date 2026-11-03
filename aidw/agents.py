"""Translate an :class:`AgentConfig` into a Pi command line (design §5.1, §7.3).

The rendered prompt itself is **not** part of the argv: AIDW pipes it to Pi on stdin
(``pi -p`` reads piped stdin as the prompt, verified against Pi 0.85.x). AIDW reads
``agents_md`` / ``system_prompt.file`` and passes their *contents* to
``--append-system-prompt`` / ``--system-prompt`` rather than paths, so behaviour does
not depend on Pi's path-vs-literal detection.
"""

from __future__ import annotations

from pathlib import Path

from aidw.config import AgentConfig


def model_name(agent: AgentConfig) -> str:
    """Return the model id with any ``provider/`` prefix removed (passed via --provider)."""
    prefix = f"{agent.provider}/"
    if agent.model.startswith(prefix):
        return agent.model[len(prefix) :]
    return agent.model


# Pi's ``--prompt-template`` precedence was **measured**, not assumed (EXTRACTION.md
# §3.6: "Verify Pi's precedence behaviour; do not assume it"). Pi 1.2.0 (`pi --version`),
# probed manually once in the E4.2 session — no model call, and no test spawns ``pi``:
# RPC mode answers ``get_commands`` from the already-loaded template list.
#
# Probe 1, order A then B (each root holds a ``probe.md`` whose frontmatter
# ``description`` is ``PROBE-ROOT-A`` / ``PROBE-ROOT-B`` and whose first line is that
# same marker). Exact command — run from the toolkit root, with the single line
# ``{"type":"get_commands"}`` written to its stdin, nothing else:
#   pi --mode rpc --no-session --no-prompt-templates \
#     --prompt-template .probe/a --prompt-template .probe/b
# Observable: the single surviving ``/probe`` entry in the ``get_commands`` response had
# ``sourceInfo.path = <cwd>/.probe/a/probe.md`` and ``description = PROBE-ROOT-A``.
# Probe 2, the same command and stdin with the flags reversed (B then A): the one
# ``/probe`` entry
# was ``<cwd>/.probe/b/probe.md`` / ``PROBE-ROOT-B``. The winner tracked the *first*
# ``--prompt-template`` flag in both runs, so it is precedence rather than coincidence.
#
# Finding: **the first ``--prompt-template`` root wins**; a later root's same-named
# template is shadowed and does not appear as a duplicate command. This contradicts
# §3.6's asserted "toolkit then target so repo files win", so the verified order is
# emitted instead: the target override root first, the configured toolkit roots after it
# (they are already toolkit-resolved by ``aidw.config``), and the declared explicit path
# last (E4.2 prompt-fixed placement; the resolver has already selected that file for the
# stdin prompt, so AIDW itself is unaffected by Pi's shadowing of the trailing root).
#
# Probe 3, a present-but-empty directory as a root (same stdin):
#   pi --mode rpc --no-session --no-prompt-templates --prompt-template .probe/empty
# Observable: exit 0, no ``/probe`` entry, empty stderr — **accepted silently** (not
# warned, not rejected). Passing it before a populated root still let that root's
# ``probe.md`` register. So an empty ``<target>/aidw/prompts/`` is harmless, which is why
# this helper keys on the directory *existing*, never on it having contents (§3.4 makes a
# target with no ``aidw/`` folder valid — then there is no second root to pass).
def prompt_template_dirs(
    agent: AgentConfig,
    target_root: Path,
    explicit_path: Path | None,
) -> list[Path]:
    """Return Pi's ordered ``--prompt-template`` roots for one stage (§3.6, D14, E4.2).

    The order is the empirically verified one recorded above: target override root (when
    ``<target>/aidw/prompts/`` exists) → the agent config's toolkit roots → the declared
    explicit prompt path, when the stage has one. The target root is omitted — not passed
    as a non-existent path — when the repo has no ``aidw/prompts/`` directory; a
    present-but-empty directory is still passed, because Pi accepts it silently.

    This is Pi's ``/``-command expansion, a separate mechanism from AIDW's own rendering
    (design §7.3, D2): the *resolved* prompt file still goes to Pi on stdin, and this
    list only has to agree with that resolution so a slash-command lookup finds the same
    file the stage rendered.
    """
    dirs: list[Path] = []
    override_dir = Path(target_root) / "aidw" / "prompts"
    if override_dir.is_dir():
        dirs.append(override_dir)
    dirs.extend(agent.prompt_templates)
    if explicit_path is not None:
        dirs.append(explicit_path)
    return dirs


def build_argv(
    agent: AgentConfig,
    *,
    session_id: str | None = None,
    prompt_templates: list[Path] | None = None,
) -> list[str]:
    """Build the Pi argv (excluding the prompt, which goes on stdin).

    ``prompt_templates`` is the complete, already-ordered root list the runner composes
    via :func:`prompt_template_dirs`; ``None`` keeps this function's original behaviour
    (emit ``agent.prompt_templates``) so every pre-E4.2 caller and test is unchanged.
    """
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
    roots = agent.prompt_templates if prompt_templates is None else prompt_templates
    for path in roots:
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
