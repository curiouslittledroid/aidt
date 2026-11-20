"""Prompt loading and rendering for AIDW.

AIDT's prompts live under ``prompts/`` (see ``inventory.py``). A prompt may begin
with a YAML frontmatter block, which is Pi template metadata and is stripped before
the prompt is rendered and sent to the agent.

Positional variables are ``$1``..``$n``. Only ``$`` followed by digits is substituted,
so shell references inside prompts (``$runner``, ``$pr``) are preserved verbatim.
This is why AIDW renders prompts in Python rather than relying on Pi's ``/`` prompt
template expansion, which does not run for CLI invocations (design §7.3).

The module also owns the **repo-conventions channel** (EXTRACTION.md §3.8, D16; task
E7.3): :func:`read_conventions_sources` reads the *target* repo's root ``AGENTS.md`` and
its optional ``aidw/conventions.md`` in D16 order, and the consumers — the five-prompt
injection the runner applies, the **resolved gate commands** both the runner injects into
the gate-recording prompts and the prompt workflow's evidence bundle renders
(``aidw.workflows.prompt._gate_block``) — read through it, so there is one channel, not
two. Since C1.3 the gate-block *resolution* lives here too (:func:`resolved_gate_block`,
:func:`gates_section`) and is injected by :func:`inject_gate_block`, so the bundle and the
stage prompts cannot resolve two different gate lists.

**The injection appends only ``aidw/conventions.md`` by default** (task C1.1, design §7.3
step 4 / §17): Pi already loads the target repo's ``AGENTS.md`` as project context at
``cwd`` = target root (§5.5), so appending it again duplicated the same file in every §3.8
stage. A prompt whose *resolved* file declares the frontmatter marker
``append_agents_md: true`` opts that prompt back in — the escape hatch for a repo whose
agents set ``no_context_files: true`` and would otherwise lose ``AGENTS.md`` entirely. The
read channel keeps both sources (``CONVENTIONS_SOURCES``) because ``_gate_block`` takes the
gate commands from the root ``AGENTS.md``; only the injection was narrowed.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

# ``load_target_config`` is the one target-config loader (``gates_heading`` is read from the
# **target's** ``<repo_root>/aidw/config.yaml``, never the toolkit root — AGENTS.md "Two roots").
# ``aidw.target_config`` imports ``aidw.config``/``aidw.verification`` only, so there is no
# cycle back into this module.
from aidw.target_config import load_target_config

_POSITIONAL = re.compile(r"\$(\d+)")
# The capture group is the *inner* frontmatter text: :func:`strip_frontmatter` ignores it,
# while :func:`appends_target_agents_md` parses exactly that slice as YAML (C1.1).
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


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

#: The five prompts that receive the target repo's conventions, keyed by the **resolved
#: prompt file's basename** (§3.8, D16; ``update-traceability.md`` added by W1.1, design §17
#: Z13) — never by stage id. ``test.md`` runs under two stage names (``test`` in
#: ``_IMPLEMENT``, ``iter{iteration}-test`` in ``_FIX``, ``aidw/stage_registry.py``), and a
#: repo-shadowed prompt (§3.6 precedence 2/3) keeps its basename, so keying on the file is
#: what makes both cases work. ``update-traceability.md`` is the fifth because the roadmap
#: tick's owner (``I7``) can only be protected if the repo can declare its artefact list —
#: including "none" — to ``I3``; Z13 records why the rule cannot live in conventions alone.
CONVENTIONS_PROMPTS: frozenset[str] = frozenset(
    {
        "task-prompt.md",
        "impliment-task.md",
        "test.md",
        "record-implementation-results.md",
        "update-traceability.md",
    }
)

#: The root source's repo-relative path. Named once because the injection treats it
#: differently from the second source (C1.1: dropped unless the prompt opts in), while the
#: read channel keeps both (``_gate_block`` reads the gate-commands section through it).
AGENTS_MD_SOURCE = "AGENTS.md"

#: The five prompts that receive the target repo's **resolved gate commands** (C1.3, design
#: §7.3 step 5), keyed by the resolved prompt file's basename exactly like
#: :data:`CONVENTIONS_PROMPTS` so a repo shadow keeps working. It is deliberately **not** the
#: same set: ``fix-next-review-followup.md`` and ``code-review.md`` are in (they record gate
#: outcomes on their own), while ``task-prompt.md`` and ``update-traceability.md`` are out —
#: the roadmap fixes exactly these five.
GATE_PROMPTS: frozenset[str] = frozenset(
    {
        "impliment-task.md",
        "test.md",
        "fix-next-review-followup.md",
        "record-implementation-results.md",
        "code-review.md",
    }
)

#: The D16 sources, relative to the **target** repo root and in D16 order: the root
#: ``AGENTS.md`` first, then the optional ``aidw/conventions.md`` (EXTRACTION.md §3.4/§3.8).
#: It is a fixed pair of paths, deliberately not a ``paths.*`` config entry (D16). Both
#: stay here even though C1.1's default injection only appends the second: the sources list
#: is the *channel*, and :func:`resolved_gate_block` needs the root ``AGENTS.md``'s
#: gate-commands section (C1.2/C1.3 depend on it — the evidence bundle and the stage-prompt
#: injection both read it).
CONVENTIONS_SOURCES: tuple[str, ...] = (AGENTS_MD_SOURCE, "aidw/conventions.md")

#: The recognised heading set for a gate-commands list (C1.2, design §7.3 step 4): the
#: canonical ``## Gates`` plus its ``## Gate commands`` alias. One tuple, defined here and
#: consumed by :func:`gates_section` (used by both the resolved gate block and the re-exported
#: ``aidw/workflows/prompt.py:_gates_section``) and ``aidw/doctor.py``'s ``gates heading``
#: check, so the resolution, the bundle reader and the diagnosis cannot drift on what a
#: recognised heading is. Matched with
#: :func:`is_recognised_gates_heading`, never ``==``: a suffixed canonical heading such as
#: the toolkit's own ``## Gates — run exactly these, and only these`` stays recognised.
#: Case is deliberate: ``## Gate Commands`` is not ``## Gate commands`` and is not
#: recognised (design §7.3/§8.1 fix the two literal strings).
GATES_HEADINGS: tuple[str, ...] = ("## Gates", "## Gate commands")


def is_gates_like_heading(line: str) -> bool:
    """Whether a ``## ``-level heading *looks* like it introduces gate commands (C1.2).

    The heuristic ``aidw doctor`` uses to decide what to diagnose: a ``## `` heading whose
    text contains "gate", case-insensitive. It is deliberately broader than
    :func:`is_recognised_gates_heading` — its whole job is to catch the headings the
    bundle reader does not recognise, so ``## Gate Commands`` (capital C) and
    ``## Verification gates`` are both reported. Pure.
    """
    return line.startswith("## ") and "gate" in line.lower()


def is_recognised_gates_heading(line: str, extra: str | None = None) -> bool:
    """Whether ``line`` is a heading the gate-commands reader recognises (C1.2).

    One ``startswith`` test against :data:`GATES_HEADINGS` plus an optional configured
    heading, never ``==``, so a suffixed canonical heading still matches. ``extra`` is the
    target's ``gates_heading`` value **verbatim — the full heading line including its
    ``## `` prefix** (``## Verification gates``); the loader rejects an empty value, so
    ``line.startswith("")`` can never match every line. This is the single definition of
    the rule: :func:`gates_section` (and its re-export
    :func:`aidw.workflows.prompt._gates_section`) and ``aidw.doctor``'s ``gates heading``
    check both route their recognition through it. Pure.
    """
    headings = GATES_HEADINGS if not extra else (*GATES_HEADINGS, extra)
    return line.startswith(headings)


def gates_section(text: str, extra_heading: str | None = None) -> str | None:
    """One conventions source's gate-commands section verbatim, or ``None`` (C1.2/C1.3).

    Recognises either heading in :data:`GATES_HEADINGS` (``## Gates`` or ``## Gate
    commands``) plus ``extra_heading``, the target's configured ``gates_heading`` passed in
    verbatim as a full ``## ``-prefixed line (design §7.3 step 4). Recognition is
    :func:`is_recognised_gates_heading`'s ``startswith`` rule — the same one ``aidw doctor``
    uses — so a suffixed canonical heading still matches and the heading set has exactly one
    definition. The extra heading is passed in, never loaded here: this function stays pure.

    The section runs from the heading to the next ``## `` heading, so a later section
    (``## Tests``) is never copied into the gate list. Pure — no I/O, and the input text is
    only read.

    Moved here from ``aidw/workflows/prompt.py`` by C1.3 so the resolved-gate-commands
    *resolution* (:func:`resolved_gate_block`) and the prompt *injection*
    (:func:`inject_gate_block`) share one definition with the evidence bundle; the workflow
    module re-exports it as ``_gates_section``.
    """
    lines = text.splitlines()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if is_recognised_gates_heading(line, extra_heading)
        ),
        None,
    )
    if start is None:
        return None
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        block.append(line)
    return "\n".join(block).rstrip()

#: The opt-in frontmatter marker on the **resolved** prompt file that restores the root
#: ``AGENTS.md`` append (C1.1; design §7.3 step 4). Only the YAML boolean ``True`` counts.
AGENTS_MD_MARKER = "append_agents_md"

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

    This is the single conventions channel: the five-prompt injection
    (:func:`inject_repo_conventions`) and the prompt workflow's evidence bundle
    (``aidw.workflows.prompt._gate_block``) both read through it. The bundle finds each
    source's gate list under a heading from :data:`GATES_HEADINGS` (or the target's
    configured ``gates_heading``) via :func:`is_recognised_gates_heading` (C1.2).

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


def resolved_gate_block(repo_root: Path) -> str | None:
    """The target repo's resolved gate commands, or ``None`` when nothing resolves (C1.3).

    The single resolution path (design §7.3 steps 4–5). Sources are read through
    :func:`read_conventions_sources` — the one conventions channel — in D16 order (the root
    ``AGENTS.md``, then the optional ``aidw/conventions.md``). Each source contributes the
    section :func:`gates_section` extracts under a heading from :data:`GATES_HEADINGS` or the
    target's configured ``gates_heading``; the sections are joined verbatim in that order.

    The ``gates_heading`` value is loaded from **this target's** ``<repo_root>/aidw/config.yaml``
    (never the toolkit root — in a self-hosted run the two coincide, so a wrong-root read would
    pass every test here and break only after extraction, AGENTS.md "Two roots"). A missing or
    malformed config simply contributes no declared heading, so the bundle never fails on it
    (L2.4 requirement 4).

    Returns ``None`` — deliberately **not** a sentinel string — when no source exists or none
    carries a recognised heading. The two consumers differ on purpose: the evidence bundle maps
    ``None`` to its ``unavailable`` note (L2.4's degrade contract), while the prompt injection
    leaves the text byte-identically unchanged (there is no stage prompt degrade note — that is
    a different consumer). Pure: the sources and the config are only read.
    """
    declared = load_target_config(Path(repo_root) / "aidw" / "config.yaml")
    extra_heading = declared.gates_heading
    blocks = [
        block
        for block in (
            gates_section(text, extra_heading)
            for _, text in read_conventions_sources(repo_root)
        )
        if block is not None
    ]
    if not blocks:
        return None
    return "\n\n".join(blocks)


def appends_target_agents_md(prompt: Path) -> bool:
    """Whether ``prompt`` opts in to the root ``AGENTS.md`` append, by frontmatter marker.

    C1.1's lever: the *resolved* prompt file (``spec.prompt``, so a repo shadow or an
    explicitly declared prompt is read, never the toolkit default a stage id would name)
    may carry ``append_agents_md: true`` in its frontmatter. That restores
    :func:`render_repo_conventions`'s ``AGENTS.md`` half for a repo whose agents set
    ``no_context_files: true`` (§5.5) and would otherwise lose ``AGENTS.md`` entirely.

    Fail-closed to ``False`` — the default — on every edge, with **no raise**: an absent
    marker, a value that is not the YAML boolean ``True`` (``false``, a quoted ``"true"``
    string, ``maybe``, a nested key), malformed YAML in the frontmatter block, a
    frontmatter-less prompt, and a missing/unreadable/non-UTF-8 file. That is the same
    degrade-never-error contract as :func:`read_conventions_sources`: a marker typo must
    not fail a stage, and guessing an opt-in would re-introduce the duplication C1.1
    removes. Pure: the prompt file is only read.
    """
    try:
        text = Path(prompt).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    match = _FRONTMATTER.match(text)
    if match is None:
        return False
    try:
        # ``yaml.safe_load`` on the inner slice, not the whole block: the block's closing
        # ``---`` would start a second document and raise a ComposerError.
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return False
    if not isinstance(metadata, dict):
        return False
    # ``is True`` (not truthiness): YAML parses ``true``/``TRUE`` to the boolean, and a
    # quoted ``"true"`` or a non-zero integer must not switch the append on.
    return metadata.get(AGENTS_MD_MARKER) is True


def render_repo_conventions(
    repo_root: Path, *, include_agents_md: bool = False
) -> str:
    """The target repo's conventions as one injectable block, ``""`` when it has none.

    By default only ``aidw/conventions.md`` is included — the file Pi does not provide
    (C1.1): the root ``AGENTS.md`` already reaches the agent as project context (§5.5), so
    appending it here duplicated the same file. ``include_agents_md=True`` restores the
    pre-C1.1 block: both sources, each copied verbatim and whole under a one-line header
    naming the file it came from, joined in D16 order (``AGENTS.md`` before
    ``aidw/conventions.md``).

    A repo with no included source — or with an empty one — gets the empty string, so the
    rendered prompt is exactly what it would have been: no "unavailable" note, no raise
    (§3.4's "a repo with no conventions yet", task E7.3 requirement 3). Pure: no input is
    mutated and nothing is written.
    """
    sources = read_conventions_sources(repo_root)
    if not include_agents_md:
        sources = tuple(pair for pair in sources if pair[0] != AGENTS_MD_SOURCE)
    return "\n\n".join(
        f"{CONVENTIONS_HEADER.format(source=source)}\n\n{text}"
        for source, text in sources
    )


def receives_repo_conventions(prompt: Path) -> bool:
    """Whether ``prompt`` is one of the five §3.8/Z13 prompts, by resolved basename.

    ``prompt`` is the *resolved* path (``spec.prompt``), so a repo shadow (§3.6
    precedence 2) and a declared explicit path (precedence 1) are keyed exactly like the
    toolkit default — the basename is what D16 names, not where the file was found.
    """
    return Path(prompt).name in CONVENTIONS_PROMPTS


#: One-line header for the injected resolved gate block (C1.3), mirroring
#: :data:`CONVENTIONS_HEADER`'s source-labelled shape. ``{sources}`` is the D16 channel rather
#: than the file a section happened to come from: the block is joined from both sources and the
#: header names where the commands are read from.
GATE_BLOCK_SOURCES = " + ".join(CONVENTIONS_SOURCES)
GATE_BLOCK_HEADER = "## Resolved gate commands ({sources})"


def receives_gate_block(prompt: Path) -> bool:
    """Whether ``prompt`` is one of the five C1.3 gate prompts, by resolved basename.

    ``prompt`` is the *resolved* path (``spec.prompt``), so a repo shadow (§3.6 precedence 2)
    and a declared explicit path (precedence 1) are keyed exactly like the toolkit default.
    """
    return Path(prompt).name in GATE_PROMPTS


def inject_gate_block(prompt_text: str, prompt: Path, repo_root: Path) -> str:
    """``prompt_text`` with the target's resolved gate commands appended, or unchanged.

    Called by :func:`aidw.runner.run_stage` **after** :func:`inject_repo_conventions` and
    ``spec.extra``, so the agent reads prompt body → stage extra → repo conventions → resolved
    gate commands, and both the written ``.rendered.md`` and the stdin payload to Pi carry the
    same text (C1.3, design §7.3 step 5).

    For a prompt in :data:`GATE_PROMPTS` whose repo resolves a block, the block is appended
    **verbatim** under :data:`GATE_BLOCK_HEADER`, which names the conventions channel the
    commands were read from. Every other case — a prompt outside the five, a repo with no
    source or no recognised heading — returns ``prompt_text`` **byte-identically**, so the
    prompt's own pointer wording stays exactly what the repo would have rendered before this
    injection existed. ``None`` from :func:`resolved_gate_block` never becomes an
    ``unavailable`` note here: that degrade belongs to the evidence bundle, a different
    consumer. Pure: nothing is written and no input is mutated.
    """
    if not receives_gate_block(prompt):
        return prompt_text
    block = resolved_gate_block(repo_root)
    if block is None:
        return prompt_text
    header = GATE_BLOCK_HEADER.format(sources=GATE_BLOCK_SOURCES)
    return f"{prompt_text}\n\n{header}\n\n{block}"


def inject_repo_conventions(prompt_text: str, prompt: Path, repo_root: Path) -> str:
    """``prompt_text`` with the target repo's conventions appended, or unchanged.

    Called by :func:`aidw.runner.run_stage` **after** the prompt body is rendered and
    after the stage's ``extra`` is appended, so the agent reads prompt body → stage extra
    → repo conventions, and both the written ``.rendered.md`` and the stdin payload to Pi
    carry the same text.

    The appended block is ``aidw/conventions.md`` only unless the resolved prompt file
    carries the ``append_agents_md: true`` marker (:func:`appends_target_agents_md`; C1.1,
    design §7.3 step 4): Pi already delivers the root ``AGENTS.md`` (§5.5). A prompt
    outside :data:`CONVENTIONS_PROMPTS`, a repo with no conventions, and an opting-in
    prompt whose repo has no ``AGENTS.md`` all return ``prompt_text`` **byte-identically**
    (task E7.3 requirements 3 and 5). Pure: the prompt files and ``spec.variables`` are
    never touched (``tests/test_prompt_neutrality.py`` asserts rendering stays pure).
    """
    if not receives_repo_conventions(prompt):
        return prompt_text
    block = render_repo_conventions(
        repo_root, include_agents_md=appends_target_agents_md(prompt)
    )
    if not block:
        return prompt_text
    return f"{prompt_text}\n\n{block}"
