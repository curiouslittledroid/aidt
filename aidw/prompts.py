"""Prompt loading and rendering for AIDW.

AIDT's prompts live under ``aidt/prompts/`` (see ``inventory.py``). A prompt may begin
with a YAML frontmatter block, which is Pi template metadata and is stripped before
the prompt is rendered and sent to the agent.

Positional variables are ``$1``..``$n``. Only ``$`` followed by digits is substituted,
so shell references inside prompts (``$runner``, ``$pr``) are preserved verbatim.
This is why AIDW renders prompts in Python rather than relying on Pi's ``/`` prompt
template expansion, which does not run for CLI invocations (design §7.3).
"""

from __future__ import annotations

import re
from pathlib import Path

_POSITIONAL = re.compile(r"\$(\d+)")
_FRONTMATTER = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.DOTALL)


class PromptError(RuntimeError):
    """Raised when a prompt cannot be loaded or rendered."""


def strip_frontmatter(text: str) -> str:
    """Remove a leading ``---`` ... ``---`` YAML frontmatter block, if present."""
    return _FRONTMATTER.sub("", text, count=1)


def render(text: str, variables: list[str] | tuple[str, ...] = ()) -> str:
    """Substitute positional ``$1``..``$n`` tokens with ``variables``.

    Raises :class:`PromptError` when the prompt references a variable index that was
    not supplied. ``$0`` is always an error (positional variables start at 1).
    """
    variables = list(variables)

    def _index(match: re.Match[str]) -> int:
        return int(match.group(1))

    highest = max((_index(m) for m in _POSITIONAL.finditer(text)), default=0)
    if highest > len(variables):
        raise PromptError(
            f"prompt references ${highest} but only {len(variables)} variable(s) "
            f"were supplied"
        )

    def _replace(match: re.Match[str]) -> str:
        index = _index(match)
        if index == 0:
            raise PromptError("prompt references $0; positional variables start at $1")
        return variables[index - 1]

    return _POSITIONAL.sub(_replace, text)


def load_prompt_file(path: Path) -> str:
    """Read a prompt file and strip its frontmatter."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptError(f"cannot read prompt {path}: {exc}") from exc
    return strip_frontmatter(text)


def render_prompt_file(
    path: Path, variables: list[str] | tuple[str, ...] = ()
) -> str:
    """Load ``path``, strip frontmatter, and substitute positional variables."""
    return render(load_prompt_file(path), variables)
