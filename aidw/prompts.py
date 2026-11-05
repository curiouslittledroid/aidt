"""Prompt loading and rendering for AIDW.

AIDT's prompts live under ``aidt/prompts/`` (see ``inventory.py``). A prompt may begin
with a YAML frontmatter block, which is Pi template metadata and is stripped before
the prompt is rendered and sent to the agent.

Positional variables are ``$1``..``$n``. Only ``$`` followed by digits is substituted,
so shell references inside prompts (``$runner``, ``$pr``) are preserved verbatim.
This is why AIDW renders prompts in Python rather than relying on Pi's ``/`` prompt
template expansion, which does not run for CLI invocations (design §7.3).

The module also owns the **repo-conventions channel** (EXTRACTION.md §3.8, D16; task
E7.3): :func:`read_conventions_sources` reads the *target* repo's root ``AGENTS.md`` and
its optional ``aidw/conventions.md`` in D16 order, and both consumers — the four-prompt
injection the runner applies and the prompt workflow's evidence bundle
(``aidw.workflows.prompt._gate_block``) — read through it, so there is one channel, not
two.
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


# --------------------------------------------------------------------------- #
# Repo conventions injection (EXTRACTION.md §3.8 / D16; task E7.3)
# --------------------------------------------------------------------------- #

#: The four prompts that receive the target repo's conventions, keyed by the **resolved
#: prompt file's basename** (§3.8, D16) — never by stage id. ``test.md`` runs under two
#: stage names (``test`` in ``_IMPLEMENT``, ``iter{iteration}-test`` in ``_FIX``,
#: ``aidw/stage_registry.py``), and a repo-shadowed prompt (§3.6 precedence 2/3) keeps its
#: basename, so keying on the file is what makes both cases work.
CONVENTIONS_PROMPTS: frozenset[str] = frozenset(
    {
        "task-prompt.md",
        "impliment-task.md",
        "test.md",
        "record-implementation-results.md",
    }
)

#: The D16 sources, relative to the **target** repo root and in D16 order: the root
#: ``AGENTS.md`` first, then the optional ``aidw/conventions.md`` (EXTRACTION.md §3.4/§3.8).
#: It is a fixed pair of paths, deliberately not a ``paths.*`` config entry (D16).
CONVENTIONS_SOURCES: tuple[str, ...] = ("AGENTS.md", "aidw/conventions.md")

#: One-line header per injected source, naming the file the content came from (§3.8: repo
#: stack rules are injected with their origin identifiable; the wording itself is not
#: frozen).
CONVENTIONS_HEADER = "## Repo conventions ({source})"


def read_conventions_sources(repo_root: Path) -> tuple[tuple[str, str], ...]:
    """The target repo's convention files that carry content, in D16 order.

    Reads ``<repo_root>/AGENTS.md`` then ``<repo_root>/aidw/conventions.md``
    (EXTRACTION.md §3.8, D16) and returns ``(relative source, text)`` pairs with each
    file's content **verbatim and whole**. Absence is never an error: a missing,
    unreadable or empty file is simply not returned, so "a repo with no conventions yet"
    (§3.4) contributes nothing rather than a placeholder or a raise.

    This is the single conventions channel: the four-prompt injection
    (:func:`inject_repo_conventions`) and the prompt workflow's evidence bundle
    (``aidw.workflows.prompt._gate_block``) both read through it.

    ``repo_root`` is the **target** repo root, never :func:`aidw.paths.toolkit_root`: in
    a self-hosted run the two coincide, so a wrong-root read passes every test here and
    breaks only after extraction (AGENTS.md "Two roots"). Pure — the source files are
    only read, never written or created.
    """
    sources: list[tuple[str, str]] = []
    for relative in CONVENTIONS_SOURCES:
        try:
            text = (Path(repo_root) / relative).read_text(encoding="utf-8")
        # UnicodeDecodeError is a ValueError, not an OSError (issue #113): a
        # conventions file with non-UTF-8 bytes must degrade to "no conventions" like
        # an unreadable one, not crash every §3.8 stage and the evidence bundle. The
        # same ``(OSError, UnicodeDecodeError)`` precedent is used by the must-not-fail
        # read in ``aidw/workflows/prompt.py`` (``_check_conciseness``).
        except (OSError, UnicodeDecodeError):
            continue
        if text.strip():
            sources.append((relative, text))
    return tuple(sources)


def render_repo_conventions(repo_root: Path) -> str:
    """The target repo's conventions as one injectable block, ``""`` when it has none.

    Each source's content is copied verbatim and whole under a one-line header naming the
    file it came from, joined in D16 order (``AGENTS.md`` before ``aidw/conventions.md``).
    A repo with neither file — or with an empty one — gets the empty string, so the
    rendered prompt is exactly what it would have been: no "unavailable" note, no raise
    (§3.4's "a repo with no conventions yet", task E7.3 requirement 3). Pure: no input is
    mutated and nothing is written.
    """
    return "\n\n".join(
        f"{CONVENTIONS_HEADER.format(source=source)}\n\n{text}"
        for source, text in read_conventions_sources(repo_root)
    )


def receives_repo_conventions(prompt: Path) -> bool:
    """Whether ``prompt`` is one of the four §3.8 prompts, by resolved basename.

    ``prompt`` is the *resolved* path (``spec.prompt``), so a repo shadow (§3.6
    precedence 2) and a declared explicit path (precedence 1) are keyed exactly like the
    toolkit default — the basename is what D16 names, not where the file was found.
    """
    return Path(prompt).name in CONVENTIONS_PROMPTS


def inject_repo_conventions(prompt_text: str, prompt: Path, repo_root: Path) -> str:
    """``prompt_text`` with the target repo's conventions appended, or unchanged.

    Called by :func:`aidw.runner.run_stage` **after** the prompt body is rendered and
    after the stage's ``extra`` is appended, so the agent reads prompt body → stage extra
    → repo conventions, and both the written ``.rendered.md`` and the stdin payload to Pi
    carry the same text. A prompt outside :data:`CONVENTIONS_PROMPTS` and a repo with no
    conventions both return ``prompt_text`` **byte-identically** (task E7.3 requirements
    3 and 5). Pure: the prompt files and ``spec.variables`` are never touched
    (``tests/test_prompt_neutrality.py`` asserts rendering stays pure).
    """
    if not receives_repo_conventions(prompt):
        return prompt_text
    block = render_repo_conventions(repo_root)
    if not block:
        return prompt_text
    return f"{prompt_text}\n\n{block}"
