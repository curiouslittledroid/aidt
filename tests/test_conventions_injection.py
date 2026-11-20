"""Contract and property tests for the repo-conventions injection (E7.3, EXTRACTION.md §3.8/D16).

The channel this module pins is deliberately narrow: **exactly five** prompts
(``task-prompt.md``, ``impliment-task.md``, ``test.md``,
``record-implementation-results.md``, ``update-traceability.md``) receive the *target*
repo's root ``AGENTS.md`` and its optional ``aidw/conventions.md``, in that order,
verbatim, keyed by the **resolved prompt basename** rather than by stage id — and
everything else is byte-identical. ``update-traceability.md`` is W1.1's fifth (design §17
Z13): ``I3`` must never edit ``paths.roadmap_dir``, and a repo can only declare its
traceability artefacts — including "none" — to ``I3`` if the conventions channel reaches
that prompt. The four traps the task prompt names each get their own test rather than a
comment:

1. **Two roots.** The fixture's ``AGENTS.md`` carries :data:`AGENTS_SENTINEL`, which the
   toolkit's own ``AGENTS.md`` cannot contain, and the assertions also require a
   toolkit-only phrase to be *absent* from the render. A ``toolkit_root()`` read therefore
   fails here, not only after extraction (AGENTS.md "Two roots").
2. **Basename, not stage id.** ``test.md`` runs as ``test`` (``_IMPLEMENT``) and
   ``iter{iteration}-test`` (``_FIX``); the keying tests cover both directions — a
   fix-loop stage name with ``test.md`` *is* injected, and a stage named ``test`` with a
   non-conventions prompt file is *not*.
3. **Resolved path.** ``spec.prompt`` is already resolved through §3.6, so a shadowed or
   explicitly declared file keeps its basename; :func:`receives_repo_conventions` takes the
   resolved path, never a "came from the toolkit default" flag.
4. **Absence = nothing.** A missing ``aidw/conventions.md`` contributes nothing: no
   placeholder note, no raise, ``record.status == SUCCEEDED``, and the render is exactly
   the un-injected text.

The property sweep at the bottom is the repo's pytest-only substitute for ``hypothesis``
(AGENTS.md "Tests": no new dependencies): the seed is the enumerated prompt-basename list
and the source-presence matrix, and ``numRuns`` is their pinned length.
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
    inject_repo_conventions,
    read_conventions_sources,
    receives_repo_conventions,
    render_prompt_file,
    render_repo_conventions,
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

AGENTS_MD = f"""# Target repo conventions

Intro prose that belongs to the target repo.

## Gates

```bash
target-fixture gate --check
```

{AGENTS_SENTINEL}
"""

CONVENTIONS_MD = f"""# Repo conventions (target)

Stack rules the toolkit must not inline.

## Gates

```bash
target-fixture lint && target-fixture test
```

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


def _dry_run(
    tmp_path: Path,
    target: Path,
    *,
    name: str,
    prompt: Path,
    variables: list[str] | None = None,
    extra: str | None = None,
) -> tuple[str, str]:
    """Dry-run one stage against ``target``; return the rendered text and ``state.json``.

    The rendered file and the record's status are the two observable outcomes the task
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
    rendered = (
        run_dir(runs_root, state.run_id) / "prompts" / f"{name}.rendered.md"
    ).read_text(encoding="utf-8")
    assert record.status == SUCCEEDED
    return rendered, (run_dir(runs_root, state.run_id) / "state.json").read_text(
        encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# The five prompts receive both sources, AGENTS.md first (§3.8, D16; W1.1/Z13)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("basename", sorted(FIVE_PROMPTS))
def test_each_of_the_five_prompts_receives_both_sources_in_d16_order(
    tmp_path: Path, basename: str
) -> None:
    """Hand-calculated example: the rendered prompt carries both files, in D16 order."""
    target = _target(tmp_path)
    prompt = toolkit_root() / "prompts" / basename

    rendered, state_json = _dry_run(
        tmp_path,
        target,
        name=basename.removesuffix(".md"),
        prompt=prompt,
        variables=FIVE_PROMPTS[basename],
    )

    assert AGENTS_SENTINEL in rendered
    assert CONVENTIONS_SENTINEL in rendered
    # D16 order: root AGENTS.md first, then aidw/conventions.md.
    assert rendered.index(AGENTS_SENTINEL) < rendered.index(CONVENTIONS_SENTINEL)
    # Each source is identifiable by its own header, and its content is whole.
    assert "## Repo conventions (AGENTS.md)" in rendered
    assert "## Repo conventions (aidw/conventions.md)" in rendered
    assert AGENTS_MD in rendered
    assert CONVENTIONS_MD in rendered
    assert "Intro prose that belongs to the target repo." in rendered
    assert "Stack rules the toolkit must not inline." in rendered
    # Injected after the prompt body, never before it.
    assert rendered.index("## Repo conventions (AGENTS.md)") > 0
    assert '"status": "succeeded"' in state_json


def test_the_five_prompts_are_exactly_the_injection_set() -> None:
    """The frozen set is §3.8's four plus W1.1/Z13's fifth — no silent superset.

    Dropping ``update-traceability.md`` from :data:`CONVENTIONS_PROMPTS` fails this
    assertion, which is the regression W1.1 exists to prevent: ``I3`` would go back to
    being unable to hear a repo's "the roadmap is not yours" declaration.
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
# Absence is never an error (requirement 3)
# --------------------------------------------------------------------------- #


def test_missing_conventions_md_contributes_nothing_and_the_run_succeeds(
    tmp_path: Path,
) -> None:
    """The repository has no ``aidw/conventions.md`` yet (§3.4) — no note, no failure."""
    target = _target(tmp_path, conventions_md=None)
    prompt = toolkit_root() / "prompts" / "impliment-task.md"

    rendered, _state = _dry_run(
        tmp_path,
        target,
        name="impliment-task",
        prompt=prompt,
        variables=FIVE_PROMPTS["impliment-task.md"],
    )

    assert AGENTS_SENTINEL in rendered
    assert CONVENTIONS_SENTINEL not in rendered
    assert "## Repo conventions (aidw/conventions.md)" not in rendered
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
    assert AGENTS_SENTINEL in rendered
    assert CONVENTIONS_SENTINEL in rendered


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
    assert captured["prompt"] == rendered_path.read_text(encoding="utf-8")
    assert CONVENTIONS_SENTINEL in captured["prompt"]


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
        "## Repo conventions (AGENTS.md)"
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

    assert AGENTS_SENTINEL in rendered
    assert CONVENTIONS_SENTINEL in rendered


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


@pytest.mark.parametrize("basename", ["code-review.md", "noop.md"])
def test_no_other_prompt_is_injected(tmp_path: Path, basename: str) -> None:
    """Requirement 5: every other prompt is untouched even when both sources exist."""
    target = _target(tmp_path)
    prompt = (
        toolkit_root() / "prompts" / basename
        if basename == "code-review.md"
        else toolkit_root() / "tests" / "fixtures" / "noop.md"
    )

    rendered, _state = _dry_run(
        tmp_path, target, name=basename.removesuffix(".md"), prompt=prompt
    )

    assert AGENTS_SENTINEL not in rendered
    assert CONVENTIONS_SENTINEL not in rendered
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
    assert AGENTS_SENTINEL in rendered
    assert CONVENTIONS_SENTINEL in rendered

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
# Two roots: ``repo_root`` is the target, never ``toolkit_root()``
# --------------------------------------------------------------------------- #


def test_the_target_root_is_the_read_source_not_the_toolkit_root(
    tmp_path: Path,
) -> None:
    """A ``toolkit_root()`` read would pass self-hosted and break after extraction."""
    target = _target(tmp_path)

    rendered, _state = _dry_run(
        tmp_path,
        target,
        name="impliment-task",
        prompt=toolkit_root() / "prompts" / "impliment-task.md",
        variables=FIVE_PROMPTS["impliment-task.md"],
    )

    assert AGENTS_SENTINEL in rendered
    # The negative assertion is non-vacuous: the toolkit's own AGENTS.md really carries the
    # phrase, so reading it instead of the target's would put it in the render.
    assert TOOLKIT_ONLY_PHRASE in (toolkit_root() / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assert TOOLKIT_ONLY_PHRASE not in rendered


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
    assert block.startswith("## Repo conventions (AGENTS.md)\n\n")
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

    assert [name for name, _ in sources] == ["AGENTS.md"]
    assert CONVENTIONS_SENTINEL not in block
    assert AGENTS_SENTINEL in block


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

    assert [name for name, _ in sources] == ["aidw/conventions.md"]
    assert AGENTS_SENTINEL not in block
    assert CONVENTIONS_SENTINEL in block


def test_a_non_utf8_conventions_file_does_not_fail_a_dry_run(
    tmp_path: Path,
) -> None:
    """The stage boundary also degrades when the optional second source is malformed.

    The shared reader is used by ``run_stage`` rather than only by its direct renderer;
    this proves the user-visible dry-run still succeeds and retains the valid AGENTS.md
    source when ``aidw/conventions.md`` cannot be decoded.
    """
    target = _target(tmp_path)
    (target / "aidw" / "conventions.md").write_bytes(b"\xff invalid utf8")

    rendered, state_json = _dry_run(
        tmp_path,
        target,
        name="test",
        prompt=toolkit_root() / "prompts" / "test.md",
    )

    assert AGENTS_SENTINEL in rendered
    assert CONVENTIONS_SENTINEL not in rendered
    assert '"status": "succeeded"' in state_json


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
# Property sweep (pytest only: no hypothesis dependency, AGENTS.md "Tests")
# --------------------------------------------------------------------------- #

#: The property seed and run count, pinned so the sample is reproducible. Series 1: every
#: prompt file the toolkit ships, sorted — ``seed = PROMPT_SEED``, ``numRuns =
#: PROMPT_NUM_RUNS``. The claim it sweeps is the whole allowlist: exactly the five §3.8/Z13
#: basenames are injected and every other shipped prompt is unchanged.
PROMPT_SEED: tuple[str, ...] = tuple(
    sorted(path.name for path in (toolkit_root() / "prompts").glob("*.md"))
)
PROMPT_NUM_RUNS = len(PROMPT_SEED)

#: Series 2's seed: the source-presence matrix ``(AGENTS.md, aidw/conventions.md)``, in the
#: four combinations; ``numRuns = SOURCE_NUM_RUNS``. The claim it sweeps is the
#: order/absence rule: the block is empty iff no source has content, and otherwise it lists
#: exactly the present sources in D16 order.
SOURCE_SEED: tuple[tuple[bool, bool], ...] = tuple(product((True, False), repeat=2))
SOURCE_NUM_RUNS = len(SOURCE_SEED)


def test_the_property_seeds_are_the_pinned_sample() -> None:
    """The sample is complete, not a convenient subset (a seed that shrinks proves nothing)."""
    assert PROMPT_NUM_RUNS == len(PROMPT_SEED) > len(CONVENTIONS_PROMPTS)
    assert set(CONVENTIONS_PROMPTS) <= set(PROMPT_SEED)
    assert {name for name in PROMPT_SEED if name in CONVENTIONS_PROMPTS} == set(
        CONVENTIONS_PROMPTS
    )
    assert SOURCE_NUM_RUNS == 4 == len(SOURCE_SEED)


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
        assert AGENTS_SENTINEL in injected
        assert CONVENTIONS_SENTINEL in injected
    else:
        assert injected == body


@pytest.mark.parametrize(("agents_present", "conventions_present"), SOURCE_SEED)
def test_property_source_presence_matches_the_d16_order_rule(
    tmp_path: Path, agents_present: bool, conventions_present: bool
) -> None:
    """Sweep 2: the block is empty iff no source has content, else D16 order of what exists."""
    target = _target(
        tmp_path,
        agents_md=AGENTS_MD if agents_present else None,
        conventions_md=CONVENTIONS_MD if conventions_present else None,
    )

    block = render_repo_conventions(target)

    if not agents_present and not conventions_present:
        assert block == ""
        return
    assert block != ""
    if agents_present:
        assert AGENTS_SENTINEL in block
        assert block.startswith("## Repo conventions (AGENTS.md)")
    else:
        assert AGENTS_SENTINEL not in block
        assert block.startswith("## Repo conventions (aidw/conventions.md)")
    if conventions_present:
        assert CONVENTIONS_SENTINEL in block
        if agents_present:
            assert block.index(AGENTS_SENTINEL) < block.index(CONVENTIONS_SENTINEL)
    else:
        assert CONVENTIONS_SENTINEL not in block
