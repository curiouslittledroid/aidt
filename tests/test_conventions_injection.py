"""Contract and property tests for the repo-conventions injection (E7.3, C1.1; §3.8/D16).

The channel this module pins is deliberately narrow: **exactly five** prompts
(``task-prompt.md``, ``impliment-task.md``, ``test.md``,
``record-implementation-results.md``, ``update-traceability.md``) receive the *target*
repo's conventions, verbatim, keyed by the **resolved prompt basename** rather than by
stage id — and everything else is byte-identical. ``update-traceability.md`` is W1.1's
fifth (design §17 Z13): ``I3`` must never edit ``paths.roadmap_dir``, and a repo can only
declare its traceability artefacts — including "none" — to ``I3`` if the conventions
channel reaches that prompt.

C1.1 (design §7.3 step 4, §17) narrows **what** is appended: only
``<target>/aidw/conventions.md``, the file Pi does not provide. The root ``AGENTS.md`` is
dropped from the render because Pi already loads it as project context at ``cwd`` =
target root (§5.5). A frontmatter marker — ``append_agents_md: true`` on the *resolved*
prompt file — restores the old two-source append for a repo whose agents set
``no_context_files: true``. ``read_conventions_sources``/``CONVENTIONS_SOURCES`` are
deliberately unchanged: that is the read channel ``aidw/workflows/prompt.py:_gate_block``
takes gate commands from (C1.2/C1.3 depend on it), and the split is injection-only.

The four traps each get their own test rather than a comment:

1. **Two roots.** The fixture's ``AGENTS.md`` carries :data:`AGENTS_SENTINEL`, which the
   toolkit's own ``AGENTS.md`` cannot contain, and the assertions also require a
   toolkit-only phrase to be *absent* from the render. A ``toolkit_root()`` read therefore
   fails here, not only after extraction (AGENTS.md "Two roots").
2. **Basename, not stage id.** ``test.md`` runs as ``test`` (``_IMPLEMENT``) and
   ``iter{iteration}-test`` (``_FIX``); the keying tests cover both directions — a
   fix-loop stage name with ``test.md`` *is* injected, and a stage named ``test`` with a
   non-conventions prompt file is *not*.
3. **Resolved path.** ``spec.prompt`` is already resolved through §3.6, so a shadowed or
   explicitly declared file keeps its basename, and the ``append_agents_md`` marker is
   read from that file — never from the toolkit default or a stage id.
4. **Absence = nothing.** A missing source contributes nothing: no placeholder note, no
   raise, ``record.status == SUCCEEDED``, and the render is exactly the un-injected text.

The property sweeps at the bottom are this repo's pytest-only substitute for
``hypothesis`` (AGENTS.md "Tests": no new dependencies): each seed is an enumerated
variation matrix (shipped prompt names, source presence × include flag, the five
basenames × frontmatter marker variants) and ``numRuns`` is its pinned length.
"""

from __future__ import annotations

from itertools import product
from pathlib import Path

import pytest

from aidw import runner as runner_mod
from aidw.config import load_all
from aidw.log import RunLogger
from aidw.paths import repo_root as toolkit_repo_root
from aidw.paths import toolkit_root
from aidw.pi import PiResult, Usage
from aidw.prompts import (
    CONVENTIONS_PROMPTS,
    CONVENTIONS_SOURCES,
    GATE_BLOCK_HEADER,
    GATE_BLOCK_SOURCES,
    GATE_PROMPTS,
    appends_target_agents_md,
    inject_gate_block,
    inject_repo_conventions,
    read_conventions_sources,
    receives_gate_block,
    receives_repo_conventions,
    render_prompt_file,
    render_repo_conventions,
    resolved_gate_block,
)
from aidw.runner import StageSpec, resolve_prompt, run_stage
from aidw.state import SUCCEEDED, create_run, run_dir

#: A sentinel that exists in this fixture's ``AGENTS.md`` and nowhere in the toolkit's own
#: ``AGENTS.md``. If the injection ever read ``toolkit_root()`` this assertion would fail.
AGENTS_SENTINEL = "E7.3-FIXTURE-SENTINEL-FROM-TARGET-AGENTS-MD"

#: Same idea for the optional second source.
CONVENTIONS_SENTINEL = "E7.3-FIXTURE-SENTINEL-FROM-TARGET-CONVENTIONS-MD"

#: A phrase from the *toolkit's* root ``AGENTS.md`` (``# AGENTS.md — developing `aidt`
#: itself``). Its absence proves the target root, not the toolkit root, was read.
TOOLKIT_ONLY_PHRASE = "developing `aidt` itself"

#: The whole-file sentinels live in their own ``## Notes`` section, *outside* the gate
#: section: C1.3 injects the gate section itself into the five gate prompts, so a sentinel
#: inside it would stop distinguishing "the whole file was appended" from "its commands were
#: resolved". The section also ends ``_gates_section``'s capture, exactly as a real
#: ``## Tests`` heading would.
AGENTS_MD = f"""# Target repo conventions

Intro prose that belongs to the target repo.

## Gates

```bash
target-fixture gate --check
```

## Notes

{AGENTS_SENTINEL}
"""

CONVENTIONS_MD = f"""# Repo conventions (target)

Stack rules the toolkit must not inline.

## Gates

```bash
target-fixture lint && target-fixture test
```

## Notes

{CONVENTIONS_SENTINEL}
"""

#: The five prompts §3.8/D16 and W1.1/Z13 cover, each with the positional variables its
#: stage passes (``task-prompt`` takes phase/epic/task, ``impliment-task`` the prompt path,
#: ``test`` none, ``record-implementation-results`` and ``update-traceability`` the branch).
FIVE_PROMPTS: dict[str, list[str]] = {
    "task-prompt.md": ["03", "E7", "E7.3"],
    "impliment-task.md": ["docs/task-prompts/00-E7.3-prompt.md"],
    "test.md": [],
    "record-implementation-results.md": ["00-E7.3"],
    "update-traceability.md": ["00-E7.3"],
}


# --------------------------------------------------------------------------- #
# Fixtures and the dry-run seam
# --------------------------------------------------------------------------- #


def _target(
    tmp_path: Path,
    *,
    agents_md: str | None = AGENTS_MD,
    conventions_md: str | None = CONVENTIONS_MD,
) -> Path:
    """A plain directory standing in for a target repo, with the requested sources.

    No git: the injection reads two files from ``repo_root`` and the dry run below spawns
    no process, so a git repo would only buy process spawns (AGENTS.md "Tests").
    """
    target = tmp_path / "target"
    (target / "aidw").mkdir(parents=True, exist_ok=True)
    if agents_md is not None:
        (target / "AGENTS.md").write_text(agents_md, encoding="utf-8")
    if conventions_md is not None:
        (target / "aidw" / "conventions.md").write_text(
            conventions_md, encoding="utf-8"
        )
    return target


def _prompt_with(
    tmp_path: Path,
    basename: str,
    frontmatter: str | None = None,
    body: str = "# shadow prompt\n",
) -> Path:
    """A resolved prompt file with the requested frontmatter, outside the toolkit.

    Used for the C1.1 ``append_agents_md`` lever: the marker is read from the *resolved*
    prompt file, so a target shadow (or any declared path) with one of the five basenames
    is the fixture — not a toolkit prompt, whose frontmatter must not be edited for a test.
    """
    path = tmp_path / "prompts" / basename
    path.parent.mkdir(parents=True, exist_ok=True)
    if frontmatter is None:
        path.write_text(body, encoding="utf-8")
    else:
        path.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return path


def _render_text(
    prompt: Path,
    variables: list[str] | None = None,
    extra: str = "",
    repo_root: Path | None = None,
) -> str:
    """The text ``run_stage`` renders on the real-run path (W1.2).

    A ``--dry-run`` writes no ``prompts/<stage>.rendered.md``, so this module computes the
    text with the same pure calls the runner applies, in the same order: the prompt and
    its positional variables, then ``spec.extra``, then the target repo's conventions, then
    the resolved gate block (C1.3).
    ``test_written_render_and_pi_stdin_receive_the_same_injection`` pins it against the file
    (and Pi stdin payload) a **real** run produces, so the two cannot drift.
    """
    rendered = render_prompt_file(prompt, list(variables or []))
    if extra:
        rendered = f"{rendered}\n\n{extra}"
    if repo_root is not None:
        rendered = inject_repo_conventions(rendered, prompt, repo_root)
        # C1.3 applies the resolved gate block after the conventions block, in the same order
        # ``run_stage`` does — ``test_written_render_and_pi_stdin_receive_the_same_injection``
        # pins this helper against a real run's written file.
        rendered = inject_gate_block(rendered, prompt, repo_root)
    return rendered


def _dry_run(
    tmp_path: Path,
    target: Path,
    *,
    name: str,
    prompt: Path,
    variables: list[str] | None = None,
    extra: str | None = None,
) -> tuple[str, str]:
    """Dry-run one stage against ``target``; return the rendered text and the record.

    The rendered text and the record's status are the two observable outcomes the task
    cares about (the stdin payload is the same string, ``run_stage`` passes ``rendered``).
    """
    runs_root = tmp_path / "runs"
    agents, issues = load_all(toolkit_root(), toolkit_repo_root())
    assert [issue for issue in issues if issue.level == "error"] == []
    state = create_run(runs_root, target, "stage", label="conventions")
    record = run_stage(
        StageSpec(
            name=name,
            agent_id="implementer",
            prompt=prompt,
            variables=list(variables or []),
            extra=extra,
        ),
        repo_root=target,
        toolkit_root=toolkit_root(),
        state=state,
        logger=RunLogger(run_dir(runs_root, state.run_id)),
        agents=agents,
        dry_run=True,
        runs_root=runs_root,
    )
    # W1.2: a dry run writes no ``prompts/<stage>.rendered.md``, so the text is computed
    # with the same pure calls ``run_stage`` applies (pinned against a real run's file
    # below, in ``test_written_render_and_pi_stdin_receive_the_same_injection``).
    rendered = _render_text(prompt, variables, extra or "", target)
    assert not (
        run_dir(runs_root, state.run_id) / "prompts" / f"{name}.rendered.md"
    ).exists()
    assert record.status == SUCCEEDED
    return rendered, record


# --------------------------------------------------------------------------- #
# The five prompts receive conventions.md only — AGENTS.md is Pi's (C1.1, §5.5)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("basename", sorted(FIVE_PROMPTS))
def test_each_of_the_five_prompts_receives_conventions_md_but_not_agents_md(
    tmp_path: Path, basename: str
) -> None:
    """Hand-calculated example: conventions.md is appended, AGENTS.md is not.

    Pi already loads the target's root ``AGENTS.md`` as project context at ``cwd`` = target
    root (§5.5, decision C1.1), so the render must not carry a second copy of the same
    file. The source Pi does *not* provide — ``aidw/conventions.md`` — is still appended,
    verbatim and whole, under its own header.
    """
    target = _target(tmp_path)
    prompt = toolkit_root() / "prompts" / basename

    rendered, record = _dry_run(
        tmp_path,
        target,
        name=basename.removesuffix(".md"),
        prompt=prompt,
        variables=FIVE_PROMPTS[basename],
    )

    # Dropped: the root AGENTS.md body, its header and its sentinel are all absent even
    # though the target repo has one.
    assert AGENTS_SENTINEL not in rendered
    assert "## Repo conventions (AGENTS.md)" not in rendered
    assert AGENTS_MD not in rendered
    assert "Intro prose that belongs to the target repo." not in rendered
    # Kept: the source Pi does not provide, identifiable by its header and whole.
    assert CONVENTIONS_SENTINEL in rendered
    assert "## Repo conventions (aidw/conventions.md)" in rendered
    assert CONVENTIONS_MD in rendered
    assert "Stack rules the toolkit must not inline." in rendered
    # Injected after the prompt body, never before it.
    assert rendered.index("## Repo conventions (aidw/conventions.md)") > 0
    assert record.status == SUCCEEDED


def test_the_five_prompts_are_exactly_the_injection_set() -> None:
    """The frozen set is §3.8's four plus W1.1/Z13's fifth — no silent superset.

    Dropping ``update-traceability.md`` from :data:`CONVENTIONS_PROMPTS` fails this
    assertion, which is the regression W1.1 exists to prevent: ``I3`` would go back to
    being unable to hear a repo's "the roadmap is not yours" declaration. The sources
    tuple is C1.1's *read* channel and must keep both entries in D16 order, because
    ``_gate_block`` reads gate commands from the root ``AGENTS.md`` (C1.2/C1.3).
    """
    assert CONVENTIONS_PROMPTS == frozenset(
        {
            "task-prompt.md",
            "impliment-task.md",
            "test.md",
            "record-implementation-results.md",
            "update-traceability.md",
        }
    )
    assert CONVENTIONS_SOURCES == ("AGENTS.md", "aidw/conventions.md")


# --------------------------------------------------------------------------- #
# The C1.1 lever: the `append_agents_md: true` marker on the resolved prompt
# --------------------------------------------------------------------------- #


def test_the_append_agents_md_marker_restores_the_agents_md_block(
    tmp_path: Path,
) -> None:
    """Hand-calculated example: the opt-in restores both sources, in D16 order.

    A repo whose agents set ``no_context_files: true`` (§5.5) gets no ``AGENTS.md`` from
    Pi, so its prompt may declare the marker and the renderer must append both files
    again — root ``AGENTS.md`` first, then ``aidw/conventions.md``.
    """
    target = _target(tmp_path)
    prompt = _prompt_with(tmp_path, "impliment-task.md", "append_agents_md: true")

    assert appends_target_agents_md(prompt) is True
    rendered, record = _dry_run(
        tmp_path, target, name="impliment-task", prompt=prompt
    )

    assert AGENTS_SENTINEL in rendered
    assert "## Repo conventions (AGENTS.md)" in rendered
    assert AGENTS_MD in rendered
    assert CONVENTIONS_SENTINEL in rendered
    assert "## Repo conventions (aidw/conventions.md)" in rendered
    # D16 order survives when both halves are present, and both come after the body.
    assert rendered.index(AGENTS_SENTINEL) < rendered.index(CONVENTIONS_SENTINEL)
    assert rendered.index("# shadow prompt") < rendered.index(
        "## Repo conventions (AGENTS.md)"
    )
    assert record.status == SUCCEEDED


def test_the_marker_is_read_from_the_resolved_prompt_not_the_toolkit_default(
    tmp_path: Path,
) -> None:
    """A target shadow carrying the marker opts in; the toolkit default does not.

    The lever is keyed to ``spec.prompt`` — a repo shadow keeps its basename and its own
    frontmatter — so reading the toolkit default instead would silently ignore the repo's
    opt-in (and a stage id would not name a file at all).
    """
    target = _target(tmp_path)
    shadow = _prompt_with(tmp_path, "test.md", "append_agents_md: true")

    assert appends_target_agents_md(shadow) is True
    assert appends_target_agents_md(toolkit_root() / "prompts" / "test.md") is False
    assert AGENTS_SENTINEL in inject_repo_conventions("body\n", shadow, target)


def test_a_resolved_shadow_with_marker_restores_agents_in_the_runner_path(
    tmp_path: Path,
) -> None:
    """The runner's resolved shadow, not merely a direct helper call, controls the opt-in."""
    target = _target(tmp_path)
    shadow = target / "aidw" / "prompts" / "test.md"
    shadow.parent.mkdir(parents=True, exist_ok=True)
    shadow.write_text(
        "---\nappend_agents_md: true\n---\n# target shadow\n", encoding="utf-8"
    )

    resolved = resolve_prompt(toolkit_root(), target, "test")
    assert resolved == shadow.resolve()
    rendered, record = _dry_run(tmp_path, target, name="shadow-test", prompt=resolved)

    assert record.status == SUCCEEDED
    assert "# target shadow" in rendered
    assert AGENTS_SENTINEL in rendered
    assert CONVENTIONS_SENTINEL in rendered


#: Frontmatter blocks that must **not** restore the append. Each is a different way to be
#: "not the YAML boolean ``true``", so the fail-closed direction is pinned on all of them.
NON_RESTORING_FRONTMATTER: dict[str, str] = {
    "absent": "description: no marker here",
    "false": "append_agents_md: false",
    "quoted-string": 'append_agents_md: "true"',
    "non-boolean-scalar": "append_agents_md: maybe",
    "integer": "append_agents_md: 1",
    "nested-key": "stage:\n  append_agents_md: true",
    "malformed-yaml": "append_agents_md: [unclosed",
}


@pytest.mark.parametrize(
    "frontmatter",
    NON_RESTORING_FRONTMATTER.values(),
    ids=NON_RESTORING_FRONTMATTER.keys(),
)
def test_a_marker_that_is_not_the_yaml_boolean_renders_as_if_absent(
    tmp_path: Path, frontmatter: str
) -> None:
    """Only YAML boolean ``true`` restores: absent/false/string/nested/malformed do not."""
    target = _target(tmp_path)
    prompt = _prompt_with(tmp_path, "impliment-task.md", frontmatter)

    assert appends_target_agents_md(prompt) is False
    rendered = inject_repo_conventions("body\n", prompt, target)

    assert rendered.startswith("body\n")
    assert CONVENTIONS_SENTINEL in rendered
    assert AGENTS_SENTINEL not in rendered
    assert "## Repo conventions (AGENTS.md)" not in rendered


def test_uppercase_true_is_the_same_yaml_boolean(tmp_path: Path) -> None:
    """``TRUE`` is a YAML boolean ``true``, so it restores the append too."""
    target = _target(tmp_path)
    prompt = _prompt_with(tmp_path, "impliment-task.md", "append_agents_md: TRUE")

    assert appends_target_agents_md(prompt) is True
    assert AGENTS_SENTINEL in inject_repo_conventions("body\n", prompt, target)


def test_a_frontmatter_less_prompt_drops_the_append_with_no_raise(
    tmp_path: Path,
) -> None:
    """Most prompts have no frontmatter at all: that is the default, not an error."""
    target = _target(tmp_path)
    # ``prompts/impliment-task.md`` ships without frontmatter; pin that, so this test cannot
    # silently become a marker test if the prompt gains one.
    prompt = toolkit_root() / "prompts" / "impliment-task.md"
    assert not prompt.read_text(encoding="utf-8").startswith("---")

    assert appends_target_agents_md(prompt) is False
    rendered = inject_repo_conventions("body\n", prompt, target)

    assert rendered.startswith("body\n")
    assert CONVENTIONS_SENTINEL in rendered
    assert AGENTS_SENTINEL not in rendered


def test_a_missing_prompt_file_drops_the_append_with_no_raise(
    tmp_path: Path,
) -> None:
    """A missing (or unreadable) prompt file means dropped — the peek never raises."""
    target = _target(tmp_path)
    missing = tmp_path / "no-such-dir" / "impliment-task.md"

    assert not missing.exists()
    assert appends_target_agents_md(missing) is False
    # A directory where the file should be is an ``IsADirectoryError`` (an ``OSError``).
    assert appends_target_agents_md(tmp_path) is False

    rendered = inject_repo_conventions("body\n", missing, target)

    assert rendered.startswith("body\n")
    assert CONVENTIONS_SENTINEL in rendered
    assert AGENTS_SENTINEL not in rendered


def test_a_non_utf8_prompt_drops_the_append_with_no_raise(tmp_path: Path) -> None:
    """A non-UTF-8 prompt file is a ``UnicodeDecodeError``, not a crash.

    ``UnicodeDecodeError`` is a ``ValueError``, so it needs its own catch beside
    ``OSError`` (the same issue #113 precedent as ``read_conventions_sources``).
    """
    target = _target(tmp_path)
    prompt = tmp_path / "prompts" / "impliment-task.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_bytes(b"---\nappend_agents_md: true\n\xff\xfe\n---\nbody\n")

    assert appends_target_agents_md(prompt) is False
    assert AGENTS_SENTINEL not in inject_repo_conventions("body\n", prompt, target)


def test_a_malformed_frontmatter_prompt_still_renders_and_appends_conventions(
    tmp_path: Path,
) -> None:
    """Fail-closed on the marker never blocks the append of the source Pi lacks."""
    target = _target(tmp_path)
    prompt = _prompt_with(tmp_path, "test.md", "append_agents_md: [unclosed")

    rendered = inject_repo_conventions("body\n", prompt, target)

    assert rendered.startswith("body\n")
    assert CONVENTIONS_SENTINEL in rendered
    assert AGENTS_SENTINEL not in rendered


# --------------------------------------------------------------------------- #
# Absence is never an error (requirement 3)
# --------------------------------------------------------------------------- #


def test_missing_conventions_md_contributes_nothing_and_the_run_succeeds(
    tmp_path: Path,
) -> None:
    """The repository has no ``aidw/conventions.md`` yet (§3.4) — no note, no failure.

    The root ``AGENTS.md`` is present but is Pi's to deliver (C1.1), so the rendered
    prompt is byte-identical to the un-injected one: no header, no placeholder.
    """
    target = _target(tmp_path, conventions_md=None)
    prompt = toolkit_root() / "prompts" / "impliment-task.md"
    # The read channel still sees the source the injection drops.
    assert [name for name, _ in read_conventions_sources(target)] == ["AGENTS.md"]

    rendered, _state = _dry_run(
        tmp_path,
        target,
        name="impliment-task",
        prompt=prompt,
        variables=FIVE_PROMPTS["impliment-task.md"],
    )

    # The missing *conventions* source contributes nothing (no header, no sentinel)...
    assert AGENTS_SENTINEL not in rendered
    assert CONVENTIONS_SENTINEL not in rendered
    assert "## Repo conventions (" not in rendered
    # ...but the AGENTS.md gate section written before it still resolves, so C1.3 appends it
    # once under its own header. That block is not a "Repo conventions" placeholder.
    assert rendered.count(GATE_BLOCK_HEADER.format(sources=GATE_BLOCK_SOURCES)) == 1
    assert "target-fixture gate --check" in rendered
    # Not an "unavailable" placeholder either: absence is silent.
    assert "unavailable" not in rendered.lower()


def test_a_repo_with_neither_source_leaves_the_prompt_byte_identical(
    tmp_path: Path,
) -> None:
    """No conventions at all: the render is exactly the un-injected text."""
    target = _target(tmp_path, agents_md=None, conventions_md=None)
    prompt = toolkit_root() / "prompts" / "test.md"
    body = "a body\n"

    assert inject_repo_conventions(body, prompt, target) == body
    assert render_repo_conventions(target) == ""

    rendered, _state = _dry_run(tmp_path, target, name="test", prompt=prompt)
    # The render is byte-identical to the un-injected one: no header, no blank tail.
    assert rendered == render_prompt_file(prompt, [])
    assert "## Repo conventions (" not in rendered


def test_an_opted_in_prompt_with_no_agents_md_still_renders_nothing(
    tmp_path: Path,
) -> None:
    """The marker cannot fabricate a source: no files, no block, byte-identical text."""
    target = _target(tmp_path, agents_md=None, conventions_md=None)
    prompt = _prompt_with(tmp_path, "test.md", "append_agents_md: true")

    assert appends_target_agents_md(prompt) is True
    assert inject_repo_conventions("body\n", prompt, target) == "body\n"


# --------------------------------------------------------------------------- #
# Keying: the resolved prompt basename, never the stage id (requirement 1)
# --------------------------------------------------------------------------- #


def test_a_resolved_shadow_prompt_still_receives_the_injection(tmp_path: Path) -> None:
    """A target ``aidw/prompts/test.md`` override keeps the basename contract."""
    target = _target(tmp_path)
    shadow = target / "aidw" / "prompts" / "test.md"
    shadow.parent.mkdir(parents=True)
    shadow.write_text("# target shadow\n", encoding="utf-8")

    resolved = resolve_prompt(toolkit_root(), target, "test")
    assert resolved == shadow
    rendered, _state = _dry_run(
        tmp_path, target, name="shadow-test", prompt=resolved
    )

    assert "# target shadow" in rendered
    assert CONVENTIONS_SENTINEL in rendered
    assert AGENTS_SENTINEL not in rendered


def test_written_render_and_pi_stdin_receive_the_same_injection(
    tmp_path: Path, monkeypatch
) -> None:
    """The non-dry runner path passes the exact rendered payload to Pi."""
    target = _target(tmp_path)
    agents, issues = load_all(toolkit_root(), toolkit_repo_root())
    assert [issue for issue in issues if issue.level == "error"] == []
    captured: dict[str, str] = {}

    def fake_execute(argv, prompt, **kwargs):
        captured["prompt"] = prompt
        return PiResult(
            exit_code=0,
            session_id="s",
            final_message="ok",
            usage=Usage(cost_usd=0.0, total_tokens=0),
            duration_seconds=0.1,
            event_count=1,
            tool_calls=0,
            tool_errors=0,
            stop_reason="end_turn",
            stderr="",
            timed_out=False,
            attempts=1,
            jsonl_path="",
            out_path=None,
        )

    monkeypatch.setattr(runner_mod, "execute", fake_execute)
    runs_root = tmp_path / "runs"
    state = create_run(runs_root, target, "stage", label="stdin")
    logger = RunLogger(run_dir(runs_root, state.run_id))
    record = run_stage(
        StageSpec(
            name="test-with-stdin",
            agent_id="tester",
            prompt=toolkit_root() / "prompts" / "test.md",
            variables=[],
        ),
        repo_root=target,
        toolkit_root=toolkit_root(),
        state=state,
        logger=logger,
        agents=agents,
        runs_root=runs_root,
    )

    rendered_path = run_dir(runs_root, state.run_id) / "prompts" / "test-with-stdin.rendered.md"
    assert record.status == SUCCEEDED
    written = rendered_path.read_text(encoding="utf-8")
    assert captured["prompt"] == written
    # W1.2: the dry-run plan's text is this same string — the helper the dry-run tests use
    # is pinned to the real-run file, so the two compositions cannot drift.
    assert _render_text(toolkit_root() / "prompts" / "test.md", [], "", target) == written
    assert CONVENTIONS_SENTINEL in captured["prompt"]
    # C1.1: the written prompt and the stdin payload both drop the AGENTS.md duplicate.
    assert AGENTS_SENTINEL not in captured["prompt"]


def test_injection_is_after_the_stage_extra(tmp_path: Path) -> None:
    """The agent sees prompt body, curated stage context, then repo conventions."""
    target = _target(tmp_path)
    rendered, _state = _dry_run(
        tmp_path,
        target,
        name="test-with-extra",
        prompt=toolkit_root() / "prompts" / "test.md",
        extra="E7.3-STAGE-EXTRA-SENTINEL",
    )

    assert rendered.index("E7.3-STAGE-EXTRA-SENTINEL") < rendered.index(
        "## Repo conventions (aidw/conventions.md)"
    )


def test_a_fix_loop_stage_name_still_receives_the_injection(tmp_path: Path) -> None:
    """``iter{iteration}-test`` is a stage id, not a prompt: keying must use ``test.md``.

    Keying on the stage id would silently skip the fix loop's tester stage, which is the
    regression this test exists for.
    """
    target = _target(tmp_path)

    rendered, _state = _dry_run(
        tmp_path,
        target,
        name="iter0-test",
        prompt=toolkit_root() / "prompts" / "test.md",
    )

    assert CONVENTIONS_SENTINEL in rendered
    assert AGENTS_SENTINEL not in rendered


def test_a_conventions_stage_name_with_another_prompt_is_not_injected(
    tmp_path: Path,
) -> None:
    """The mirror: the *file* decides, so a coincidental stage name proves nothing."""
    target = _target(tmp_path)
    prompt = toolkit_root() / "tests" / "fixtures" / "noop.md"

    rendered, _state = _dry_run(tmp_path, target, name="test", prompt=prompt)

    assert AGENTS_SENTINEL not in rendered
    assert CONVENTIONS_SENTINEL not in rendered
    assert rendered.strip() == "Reply with exactly the token PONG and nothing else."


@pytest.mark.parametrize("basename", ["pr.md", "noop.md"])
def test_no_other_prompt_is_injected(tmp_path: Path, basename: str) -> None:
    """Requirement 5: every other prompt is untouched even when both sources exist.

    ``code-review.md`` was this test's shipped-prompt case until C1.3 added it to
    :data:`GATE_PROMPTS`; ``pr.md`` is outside both channels, so it carries the same claim.
    """
    target = _target(tmp_path)
    prompt = (
        toolkit_root() / "prompts" / basename
        if basename == "pr.md"
        else toolkit_root() / "tests" / "fixtures" / "noop.md"
    )

    rendered, _state = _dry_run(
        tmp_path,
        target,
        name=basename.removesuffix(".md"),
        prompt=prompt,
        variables=["01-A1.1"] if basename == "pr.md" else [],
    )

    assert AGENTS_SENTINEL not in rendered
    assert CONVENTIONS_SENTINEL not in rendered
    # C1.3's channel is closed here too: neither the repo-conventions header nor the
    # resolved gate block's header is appended.
    assert "## Repo conventions (" not in rendered
    assert GATE_HEADER not in rendered
    assert "## Repo conventions (" not in rendered


def test_receives_repo_conventions_keys_on_the_resolved_basename(
    tmp_path: Path,
) -> None:
    """A repo-shadowed ``test.md`` (§3.6 precedence 2) keeps its basename, so it is injected."""
    shadow = tmp_path / "target" / "aidw" / "prompts" / "test.md"
    shadow.parent.mkdir(parents=True)
    shadow.write_text("# shadow\n", encoding="utf-8")

    assert receives_repo_conventions(shadow) is True
    assert receives_repo_conventions(toolkit_root() / "prompts" / "test.md") is True
    assert receives_repo_conventions(toolkit_root() / "prompts" / "code-review.md") is False


def test_the_traceability_prompt_is_injected_by_basename_not_by_stage_id(
    tmp_path: Path,
) -> None:
    """W1.1/Z13: ``I3``'s prompt is keyed by its file, so a repo shadow is injected too.

    The stage id and the toolkit default's basename coincide (``update-traceability``), so
    a name-based key would pass by luck. The two halves separate them: the repo's shadowed
    ``aidw/prompts/update-traceability.md`` (D14 precedence 2) is injected under a stage
    name that is *not* the basename, and a stage actually named ``update-traceability``
    rendering another file receives nothing.
    """
    target = _target(tmp_path)
    shadow = target / "aidw" / "prompts" / "update-traceability.md"
    shadow.parent.mkdir(parents=True)
    shadow.write_text("# repo traceability rules\n", encoding="utf-8")

    resolved = resolve_prompt(toolkit_root(), target, "update-traceability")
    assert resolved == shadow
    rendered, _state = _dry_run(
        tmp_path,
        target,
        name="traceability-shadow",
        prompt=resolved,
        variables=FIVE_PROMPTS["update-traceability.md"],
    )

    assert "# repo traceability rules" in rendered
    assert CONVENTIONS_SENTINEL in rendered
    assert AGENTS_SENTINEL not in rendered

    # The mirror: the stage name alone proves nothing — the file decides.
    rendered, _state = _dry_run(
        tmp_path,
        target,
        name="update-traceability",
        prompt=toolkit_root() / "tests" / "fixtures" / "noop.md",
    )

    assert AGENTS_SENTINEL not in rendered
    assert CONVENTIONS_SENTINEL not in rendered


# --------------------------------------------------------------------------- #
# C1.3: the resolved gate commands are inlined into the five gate prompts
# --------------------------------------------------------------------------- #

#: A target whose ``AGENTS.md`` publishes its gates under a **suffixed** canonical heading
#: (the toolkit's own shape) with two commands, and whose ``aidw/conventions.md`` uses the
#: ``## Gate commands`` alias with one. Two sources, two recognised headings, different
#: section lengths — everything the D16-ordered verbatim join must handle.
GATE_AGENTS_MD = """# Gate fixture

Intro prose outside the gate section.

## Gates — run exactly these, and only these

```bash
target gate one --check
target gate two --check
```

C1.3-AGENTS-GATE-SENTINEL
"""

GATE_CONVENTIONS_MD = """# Conventions

## Gate commands

```bash
target gate three --check
```

C1.3-CONVENTIONS-GATE-SENTINEL
"""

#: The hand-calculated join: each section verbatim, bounded at the next ``## `` heading,
#: ``AGENTS.md`` first (D16 order), joined by one blank line.
EXPECTED_GATE_BLOCK = (
    "## Gates — run exactly these, and only these\n"
    "\n"
    "```bash\n"
    "target gate one --check\n"
    "target gate two --check\n"
    "```\n"
    "\n"
    "C1.3-AGENTS-GATE-SENTINEL\n"
    "\n"
    "## Gate commands\n"
    "\n"
    "```bash\n"
    "target gate three --check\n"
    "```\n"
    "\n"
    "C1.3-CONVENTIONS-GATE-SENTINEL"
)

#: The one header the injected block sits under (C1.3 mirrors ``CONVENTIONS_HEADER``'s
#: source-labelled shape).
GATE_HEADER = GATE_BLOCK_HEADER.format(sources=GATE_BLOCK_SOURCES)

#: The five C1.3 gate prompts — **not** ``CONVENTIONS_PROMPTS``: the fix and code-review
#: prompts record their own gate outcomes, while ``task-prompt.md`` and
#: ``update-traceability.md`` do not.
GATE_FIVE = (
    "impliment-task.md",
    "test.md",
    "fix-next-review-followup.md",
    "record-implementation-results.md",
    "code-review.md",
)


def _gate_target(tmp_path: Path) -> Path:
    return _target(
        tmp_path, agents_md=GATE_AGENTS_MD, conventions_md=GATE_CONVENTIONS_MD
    )


def test_c13_the_gate_prompt_set_is_exactly_the_five_and_not_the_conventions_set() -> None:
    """The two sets are deliberately different; the roadmap fixes both memberships."""
    assert GATE_PROMPTS == frozenset(GATE_FIVE)
    assert len(GATE_PROMPTS) == 5
    # The two members the sets do not share, in both directions.
    assert {"fix-next-review-followup.md", "code-review.md"} <= GATE_PROMPTS
    assert GATE_PROMPTS - CONVENTIONS_PROMPTS == {
        "fix-next-review-followup.md",
        "code-review.md",
    }
    assert CONVENTIONS_PROMPTS - GATE_PROMPTS == {
        "task-prompt.md",
        "update-traceability.md",
    }


def test_c13_resolved_gate_block_joins_the_sections_verbatim_in_d16_order(
    tmp_path: Path,
) -> None:
    """Hand-calculated example: two sources, two headings, one D16-ordered block."""
    target = _gate_target(tmp_path)

    assert resolved_gate_block(target) == EXPECTED_GATE_BLOCK


@pytest.mark.parametrize("basename", GATE_FIVE)
def test_c13_each_gate_prompt_receives_the_block_under_its_header(
    tmp_path: Path, basename: str
) -> None:
    """Each of the five appends the block verbatim under one source-labelled header."""
    target = _gate_target(tmp_path)
    body = "rendered body\n"

    injected = inject_gate_block(body, toolkit_root() / "prompts" / basename, target)

    assert injected == f"{body}\n\n{GATE_HEADER}\n\n{EXPECTED_GATE_BLOCK}"


@pytest.mark.parametrize(
    "basename", ["pr.md", "task-prompt.md", "update-traceability.md"]
)
def test_c13_prompts_outside_the_five_stay_byte_identical(
    tmp_path: Path, basename: str
) -> None:
    """The pointer behaviour survives for every prompt C1.3 does not cover."""
    target = _gate_target(tmp_path)
    body = "rendered body\n"
    prompt = toolkit_root() / "prompts" / basename

    assert inject_gate_block(body, prompt, target) == body
    assert receives_gate_block(prompt) is False


def test_c13_a_repo_shadow_is_injected_by_basename_not_stage_id(tmp_path: Path) -> None:
    """``spec.prompt`` is the key, so a repo-shadowed ``test.md`` is injected too."""
    target = _gate_target(tmp_path)
    shadow = target / "aidw" / "prompts" / "test.md"
    shadow.parent.mkdir(parents=True)
    shadow.write_text("# target shadow\n", encoding="utf-8")

    assert receives_gate_block(shadow) is True
    assert inject_gate_block("body\n", shadow, target).startswith("body\n\n")
    # The mirror: a non-gate file at a gate-looking stage name receives nothing.
    assert receives_gate_block(toolkit_root() / "tests" / "fixtures" / "noop.md") is False


def test_c13_a_repo_with_no_source_resolves_none_and_renders_identically(
    tmp_path: Path,
) -> None:
    """No-resolution is byte-identity, never an injected ``unavailable`` note."""
    target = _target(tmp_path, agents_md=None, conventions_md=None)
    body = "rendered body\n"

    assert resolved_gate_block(target) is None
    for basename in GATE_FIVE:
        prompt = toolkit_root() / "prompts" / basename
        assert inject_gate_block(body, prompt, target) == body
        assert "unavailable" not in inject_gate_block(body, prompt, target).lower()


def test_c13_a_source_without_a_recognised_heading_resolves_none(tmp_path: Path) -> None:
    """A conventions file with no gate section is the same as no source."""
    target = _target(
        tmp_path,
        agents_md="# Conventions\n\nStack rules only, no gate list.\n",
        conventions_md=None,
    )

    assert resolved_gate_block(target) is None
    assert (
        inject_gate_block("body\n", toolkit_root() / "prompts" / "test.md", target)
        == "body\n"
    )


def test_c13_the_gate_block_reads_the_target_root_not_the_toolkit_root(
    tmp_path: Path,
) -> None:
    """A ``toolkit_root()`` read would pass self-hosted and break after extraction."""
    target = _gate_target(tmp_path)

    block = resolved_gate_block(target)

    assert block is not None
    # Both target sources contribute, in D16 order.
    assert block.index("C1.3-AGENTS-GATE-SENTINEL") < block.index(
        "C1.3-CONVENTIONS-GATE-SENTINEL"
    )
    # The negative is non-vacuous: the toolkit's own AGENTS.md really carries this command,
    # so a toolkit-root read would put it in the block.
    toolkit_agents = (toolkit_root() / "AGENTS.md").read_text(encoding="utf-8")
    assert "uv sync --frozen" in toolkit_agents
    assert "uv sync --frozen" not in block


def test_c13_resolution_and_injection_write_nothing_and_mutate_no_input(
    tmp_path: Path,
) -> None:
    """Pure: the sources and the prompt are read only, and no file is created."""
    target = _gate_target(tmp_path)
    agents_path = target / "AGENTS.md"
    conventions_path = target / "aidw" / "conventions.md"
    prompt = toolkit_root() / "prompts" / "impliment-task.md"
    watched = (agents_path, conventions_path, prompt)
    before = {path: path.read_bytes() for path in watched}
    mtimes = {path: path.stat().st_mtime_ns for path in watched}
    listing_before = sorted(str(path) for path in target.rglob("*"))
    text = "rendered body\n"

    block = resolved_gate_block(target)
    injected = inject_gate_block(text, prompt, target)

    assert block == EXPECTED_GATE_BLOCK
    assert injected.startswith(text)
    # No input was mutated and no output was written anywhere the fixture can see.
    assert text == "rendered body\n"
    assert {path: path.read_bytes() for path in watched} == before
    assert {path: path.stat().st_mtime_ns for path in watched} == mtimes
    assert sorted(str(path) for path in target.rglob("*")) == listing_before


def test_c13_the_dry_run_render_carries_the_block_exactly_once(tmp_path: Path) -> None:
    """The runner's seam: the block lands after the body and the conventions append.

    ``impliment-task.md`` is in both sets, so this is also the duplication corner's pinned
    shape: the focused gate block is the authoritative *resolved gate commands*
    presentation, and its header appears exactly once even though ``aidw/conventions.md`` is
    appended whole as repo conventions as well.
    """
    target = _gate_target(tmp_path)
    prompt = toolkit_root() / "prompts" / "impliment-task.md"

    rendered, record = _dry_run(
        tmp_path,
        target,
        name="impliment-task",
        prompt=prompt,
        variables=FIVE_PROMPTS["impliment-task.md"],
    )

    assert record.status == SUCCEEDED
    assert rendered.count(GATE_HEADER) == 1
    # The AGENTS.md gate section appears only in the injected block (the conventions append
    # is conventions.md only, C1.1), so it is the block's own copy.
    assert rendered.count("## Gates — run exactly these, and only these") == 1
    assert "target gate one --check" in rendered
    # Ordering: body → repo conventions → resolved gate commands.
    assert rendered.index("## Repo conventions (aidw/conventions.md)") < rendered.index(
        GATE_HEADER
    )
    # ``pr.md`` is outside the five: its render is unchanged by C1.3.
    pr_rendered = inject_gate_block(
        render_prompt_file(toolkit_root() / "prompts" / "pr.md", ["01-A1.1"]),
        toolkit_root() / "prompts" / "pr.md",
        target,
    )
    assert GATE_HEADER not in pr_rendered

# --------------------------------------------------------------------------- #
# Two roots: ``repo_root`` is the target, never ``toolkit_root()``
# --------------------------------------------------------------------------- #


def test_the_target_root_is_the_read_source_not_the_toolkit_root(
    tmp_path: Path,
) -> None:
    """A ``toolkit_root()`` read would pass self-hosted and break after extraction."""
    target = _target(tmp_path)
    # The marker makes the AGENTS.md half visible again, which is what this test observes.
    prompt = _prompt_with(tmp_path, "impliment-task.md", "append_agents_md: true")

    rendered = inject_repo_conventions("body\n", prompt, target)

    assert AGENTS_SENTINEL in rendered
    # The negative assertion is non-vacuous: the toolkit's own AGENTS.md really carries the
    # phrase, so reading it instead of the target's would put it in the render.
    assert TOOLKIT_ONLY_PHRASE in (toolkit_root() / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assert TOOLKIT_ONLY_PHRASE not in rendered

    # The read channel ``_gate_block`` uses is two-rooted in the same way.
    sources = dict(read_conventions_sources(target))
    assert [name for name, _ in read_conventions_sources(target)] == [
        "AGENTS.md",
        "aidw/conventions.md",
    ]
    assert AGENTS_SENTINEL in sources["AGENTS.md"]
    assert TOOLKIT_ONLY_PHRASE not in sources["AGENTS.md"]
    assert CONVENTIONS_SENTINEL in sources["aidw/conventions.md"]


# --------------------------------------------------------------------------- #
# Purity and fail-closed reads
# --------------------------------------------------------------------------- #


def test_reading_conventions_writes_nothing_and_leaves_the_sources_identical(
    tmp_path: Path,
) -> None:
    """Rendering is pure: no source is created, rewritten or touched."""
    target = _target(tmp_path, conventions_md=None)
    agents_path = target / "AGENTS.md"
    before = agents_path.read_bytes()
    before_stat = agents_path.stat()

    sources = read_conventions_sources(target)
    block = render_repo_conventions(target)

    assert [name for name, _ in sources] == ["AGENTS.md"]
    # The default injectable block excludes the root AGENTS.md (C1.1); the opt-in restores
    # today's D16 block, and neither touches the file.
    assert block == ""
    assert render_repo_conventions(target, include_agents_md=True).startswith(
        "## Repo conventions (AGENTS.md)\n\n"
    )
    assert agents_path.read_bytes() == before
    assert agents_path.stat().st_mtime_ns == before_stat.st_mtime_ns
    # The absent source is not created by reading it.
    assert not (target / "aidw" / "conventions.md").exists()


def test_injection_does_not_mutate_the_prompt_file_or_the_variables(
    tmp_path: Path,
) -> None:
    """``spec.variables`` and the prompt file are inputs only (rendering stays pure)."""
    target = _target(tmp_path)
    prompt = toolkit_root() / "prompts" / "task-prompt.md"
    before = prompt.read_bytes()
    variables = list(FIVE_PROMPTS["task-prompt.md"])
    snapshot = list(variables)

    injected = inject_repo_conventions("rendered body\n", prompt, target)

    assert injected.startswith("rendered body\n")
    assert CONVENTIONS_SENTINEL in injected
    assert AGENTS_SENTINEL not in injected
    assert prompt.read_bytes() == before
    assert variables == snapshot


def test_an_unreadable_source_degrades_to_nothing_instead_of_raising(
    tmp_path: Path,
) -> None:
    """Fail-closed: a directory where the file should be is skipped, never raised.

    A conventions file the process cannot read must not fail a stage — the same
    degrade-never-error contract as a missing file.
    """
    target = _target(tmp_path)
    # Replace the file with a directory: ``read_text`` raises ``IsADirectoryError``.
    (target / "aidw" / "conventions.md").unlink()
    (target / "aidw" / "conventions.md").mkdir()

    sources = read_conventions_sources(target)
    block = render_repo_conventions(target)
    opted_in = render_repo_conventions(target, include_agents_md=True)

    assert [name for name, _ in sources] == ["AGENTS.md"]
    # The only included source for the default block is the unreadable one, so it is empty.
    assert block == ""
    assert CONVENTIONS_SENTINEL not in opted_in
    assert AGENTS_SENTINEL in opted_in


def test_a_non_utf8_source_degrades_to_nothing_instead_of_raising(
    tmp_path: Path,
) -> None:
    """Issue #113: a non-UTF-8 source is skipped, never raised.

    ``UnicodeDecodeError`` is a ``ValueError``, not an ``OSError``, so the
    ``except OSError`` in ``read_conventions_sources`` did not cover it and a
    Latin-1-encoded ``AGENTS.md`` crashed every §3.8 stage and the evidence bundle
    instead of degrading to "no conventions".
    """
    target = _target(tmp_path)
    # The issue's repro: invalid UTF-8 at position 0, so ``read_text`` raises
    # ``UnicodeDecodeError`` before any ``OSError`` subclass could appear.
    (target / "AGENTS.md").write_bytes(b"\xff\xfe invalid utf8 \x80\x81")

    sources = read_conventions_sources(target)
    block = render_repo_conventions(target)
    opted_in = render_repo_conventions(target, include_agents_md=True)

    assert [name for name, _ in sources] == ["aidw/conventions.md"]
    assert AGENTS_SENTINEL not in opted_in
    assert CONVENTIONS_SENTINEL in opted_in
    # The default block is the conventions.md source alone and still starts with its header.
    assert block.startswith("## Repo conventions (aidw/conventions.md)\n\n")
    assert AGENTS_SENTINEL not in block


def test_a_non_utf8_conventions_file_does_not_fail_a_dry_run(
    tmp_path: Path,
) -> None:
    """The stage boundary also degrades when the optional second source is malformed.

    The shared reader is used by ``run_stage`` rather than only by its direct renderer;
    this proves the user-visible dry-run still succeeds and renders the un-injected text
    when the only source Pi lacks cannot be decoded.
    """
    target = _target(tmp_path)
    (target / "aidw" / "conventions.md").write_bytes(b"\xff invalid utf8")
    prompt = toolkit_root() / "prompts" / "test.md"

    rendered, record = _dry_run(tmp_path, target, name="test", prompt=prompt)

    # The conventions source Pi lacks degrades to nothing; the AGENTS.md gate section still
    # resolves and is injected once (C1.3), so only the *conventions* half is byte-identical.
    assert "## Repo conventions (" not in rendered
    assert AGENTS_SENTINEL not in rendered
    assert CONVENTIONS_SENTINEL not in rendered
    assert rendered.startswith(render_prompt_file(prompt, []))
    assert rendered.count(GATE_BLOCK_HEADER.format(sources=GATE_BLOCK_SOURCES)) == 1
    assert "target-fixture gate --check" in rendered
    # An unreadable conventions file degrades; the stage still plans successfully.
    assert record.status == SUCCEEDED


def test_an_empty_source_contributes_no_dangling_header(tmp_path: Path) -> None:
    """An empty ``conventions.md`` adds nothing, so the prompt stays byte-identical."""
    target = _target(tmp_path, agents_md=None, conventions_md="   \n")

    assert read_conventions_sources(target) == ()
    assert render_repo_conventions(target) == ""
    assert (
        inject_repo_conventions(
            "body\n", toolkit_root() / "prompts" / "test.md", target
        )
        == "body\n"
    )


# --------------------------------------------------------------------------- #
# Property sweeps (pytest only: no hypothesis dependency, AGENTS.md "Tests")
# --------------------------------------------------------------------------- #

#: The property seed and run count, pinned so the sample is reproducible. Series 1: every
#: prompt file the toolkit ships, sorted — ``seed = PROMPT_SEED``, ``numRuns =
#: PROMPT_NUM_RUNS``. The claim it sweeps is the whole allowlist: exactly the five §3.8/Z13
#: basenames are injected, and every other shipped prompt is unchanged.
PROMPT_SEED: tuple[str, ...] = tuple(
    sorted(path.name for path in (toolkit_root() / "prompts").glob("*.md"))
)
PROMPT_NUM_RUNS = len(PROMPT_SEED)

#: Series 2's seed: the source-presence matrix ``(AGENTS.md, aidw/conventions.md)`` crossed
#: with the ``include_agents_md`` opt-in, in the eight combinations; ``numRuns =
#: BLOCK_NUM_RUNS``. The claim it sweeps is the order/absence rule: the block is empty iff
#: no *included* source has content, and otherwise it lists exactly the included sources in
#: D16 order.
SOURCE_SEED: tuple[tuple[bool, bool], ...] = tuple(product((True, False), repeat=2))
INCLUDE_SEED: tuple[bool, ...] = (False, True)
BLOCK_SEED: tuple[tuple[bool, bool, bool], ...] = tuple(
    (agents_present, conventions_present, include_agents_md)
    for (agents_present, conventions_present), include_agents_md in product(
        SOURCE_SEED, INCLUDE_SEED
    )
)
BLOCK_NUM_RUNS = len(BLOCK_SEED)

#: Series 3's seed: the five injected basenames crossed with the frontmatter marker
#: variants; ``numRuns = MARKER_NUM_RUNS``. The claim it sweeps is C1.1's fail-closed lever:
#: the append is restored **iff** the frontmatter parses to the YAML boolean ``True``.
MARKER_VARIANTS: tuple[tuple[str, str], ...] = (
    ("absent", "description: no marker here"),
    ("true", "append_agents_md: true"),
    ("true-upper", "append_agents_md: TRUE"),
    ("false", "append_agents_md: false"),
    ("quoted-string", 'append_agents_md: "true"'),
    ("non-boolean", "append_agents_md: maybe"),
    ("integer", "append_agents_md: 1"),
    ("nested", "stage:\n  append_agents_md: true"),
    ("malformed-yaml", "append_agents_md: [unclosed"),
)
RESTORING_VARIANTS = frozenset({"true", "true-upper"})
MARKER_SEED: tuple[tuple[str, str, str], ...] = tuple(
    (basename, variant, frontmatter)
    for basename in sorted(CONVENTIONS_PROMPTS)
    for variant, frontmatter in MARKER_VARIANTS
)
MARKER_NUM_RUNS = len(MARKER_SEED)


def test_the_property_seeds_are_the_pinned_sample() -> None:
    """The sample is complete, not a convenient subset (a seed that shrinks proves nothing)."""
    assert PROMPT_NUM_RUNS == len(PROMPT_SEED) > len(CONVENTIONS_PROMPTS)
    assert set(CONVENTIONS_PROMPTS) <= set(PROMPT_SEED)
    assert {name for name in PROMPT_SEED if name in CONVENTIONS_PROMPTS} == set(
        CONVENTIONS_PROMPTS
    )
    # Sweep 1's claim (conventions.md only, never the AGENTS.md body) depends on no shipped
    # prompt opting in: a toolkit marker would make a parametrisation disagree with it.
    assert [
        name
        for name in PROMPT_SEED
        if appends_target_agents_md(toolkit_root() / "prompts" / name)
    ] == []
    assert BLOCK_NUM_RUNS == 8 == len(BLOCK_SEED)
    assert MARKER_NUM_RUNS == len(MARKER_SEED) == (
        len(CONVENTIONS_PROMPTS) * len(MARKER_VARIANTS)
    )


@pytest.mark.parametrize("basename", PROMPT_SEED)
def test_property_exactly_the_five_shipped_prompts_are_injected(
    tmp_path: Path, basename: str
) -> None:
    """Sweep 1 over every shipped prompt: injected iff its basename is one of the five."""
    target = _target(tmp_path)
    prompt = toolkit_root() / "prompts" / basename
    body = "rendered body\n"

    injected = inject_repo_conventions(body, prompt, target)

    if basename in CONVENTIONS_PROMPTS:
        assert injected.startswith(body)
        assert CONVENTIONS_SENTINEL in injected
        # C1.1: no shipped prompt carries the marker, so AGENTS.md is never appended.
        assert AGENTS_SENTINEL not in injected
    else:
        assert injected == body


@pytest.mark.parametrize(
    ("agents_present", "conventions_present", "include_agents_md"), BLOCK_SEED
)
def test_property_source_presence_matches_the_d16_order_rule(
    tmp_path: Path,
    agents_present: bool,
    conventions_present: bool,
    include_agents_md: bool,
) -> None:
    """Sweep 2: the block is empty iff no included source has content, else D16 order."""
    target = _target(
        tmp_path,
        agents_md=AGENTS_MD if agents_present else None,
        conventions_md=CONVENTIONS_MD if conventions_present else None,
    )

    block = render_repo_conventions(target, include_agents_md=include_agents_md)

    agents_included = agents_present and include_agents_md
    if not agents_included and not conventions_present:
        assert block == ""
        return
    assert block != ""
    if agents_included:
        assert AGENTS_SENTINEL in block
        assert block.startswith("## Repo conventions (AGENTS.md)")
    else:
        assert AGENTS_SENTINEL not in block
    if conventions_present:
        assert CONVENTIONS_SENTINEL in block
        assert "## Repo conventions (aidw/conventions.md)" in block
        if agents_included:
            assert block.index(AGENTS_SENTINEL) < block.index(CONVENTIONS_SENTINEL)
        else:
            assert block.startswith("## Repo conventions (aidw/conventions.md)")
    else:
        assert CONVENTIONS_SENTINEL not in block
        assert block.startswith("## Repo conventions (AGENTS.md)")


@pytest.mark.parametrize(("basename", "variant", "frontmatter"), MARKER_SEED)
def test_property_only_the_yaml_boolean_marker_restores_the_append(
    tmp_path: Path, basename: str, variant: str, frontmatter: str
) -> None:
    """Sweep 3: the five basenames × every marker variant, restore iff YAML ``true``."""
    target = _target(tmp_path)
    prompt = _prompt_with(tmp_path, basename, frontmatter)
    restored = variant in RESTORING_VARIANTS

    assert appends_target_agents_md(prompt) is restored
    rendered = inject_repo_conventions("body\n", prompt, target)

    # The basename gate and the conventions.md append hold in every combination...
    assert rendered.startswith("body\n")
    assert CONVENTIONS_SENTINEL in rendered
    # ... and only the YAML boolean switches the root AGENTS.md half on.
    assert (AGENTS_SENTINEL in rendered) is restored
    assert ("## Repo conventions (AGENTS.md)" in rendered) is restored

#: Series 4's seed: the gate-prompt allowlist crossed with the source-presence/heading matrix;
#: ``numRuns = GATE_NUM_RUNS``. The claim it sweeps is C1.3's two-sided rule: a prompt receives
#: the resolved block **iff** its basename is in :data:`GATE_PROMPTS` *and* the target resolves
#: one, and the text is byte-identical in every other combination (the pointer behaviour).
GATE_SOURCE_SEED: tuple[tuple[str | None, str | None], ...] = (
    (GATE_AGENTS_MD, GATE_CONVENTIONS_MD),
    (GATE_AGENTS_MD, None),
    (None, GATE_CONVENTIONS_MD),
    (None, None),
    ("# Conventions\n\nStack rules only, no gate list.\n", None),
)
GATE_BASENAMES: tuple[str, ...] = (
    *sorted(GATE_PROMPTS),
    "pr.md",
    "task-prompt.md",
    "update-traceability.md",
)
GATE_SEED: tuple[tuple[str, tuple[str | None, str | None]], ...] = tuple(
    (basename, sources)
    for basename in GATE_BASENAMES
    for sources in GATE_SOURCE_SEED
)
GATE_NUM_RUNS = len(GATE_SEED)


def test_the_gate_property_seed_is_the_pinned_sample() -> None:
    """The sample covers both sides of the allowlist and shrinks only deliberately."""
    assert GATE_NUM_RUNS == len(GATE_SEED) == len(GATE_BASENAMES) * len(GATE_SOURCE_SEED)
    assert GATE_NUM_RUNS == 8 * 5 == 40
    assert set(GATE_PROMPTS) < set(GATE_BASENAMES)
    assert len(GATE_PROMPTS & CONVENTIONS_PROMPTS) == 3


@pytest.mark.parametrize(("basename", "sources"), GATE_SEED)
def test_property_the_gate_block_is_injected_iff_the_prompt_and_repo_resolve(
    tmp_path: Path,
    basename: str,
    sources: tuple[str | None, str | None],
) -> None:
    """Sweep 4: injection iff (prompt in the five) and (the target resolves a block)."""
    target = _target(tmp_path, agents_md=sources[0], conventions_md=sources[1])
    prompt = toolkit_root() / "prompts" / basename
    body = "rendered body\n"

    block = resolved_gate_block(target)
    injected = inject_gate_block(body, prompt, target)
    expected = block is not None and basename in GATE_PROMPTS

    if expected:
        assert injected == f"{body}\n\n{GATE_HEADER}\n\n{block}"
    else:
        # Byte-identity is the contract: no header, no block, no "unavailable" note.
        assert injected == body
