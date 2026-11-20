"""Contract tests for the prompt resolver and Pi's template-root plumbing (E4.2).

EXTRACTION.md §3.4 fixes the four-level precedence (explicit ``prompt:`` path → target
``aidw/prompts/`` shadow → toolkit default → failure) and D14 adds filename shadowing.
§3.6 adds the second mechanism this task has to keep in agreement with it: Pi's
``--prompt-template`` roots, which are a separate ``/``-command expansion from AIDW's own
rendering (design §7.3).

The template-root order asserted here is the *recorded empirical finding*, not a snapshot
of the helper's output: Pi 1.2.0's probe (comment next to ``prompt_template_dirs`` in
``aidw/agents.py``) showed the **first** ``--prompt-template`` root wins, so the target
override root precedes the toolkit root and the declared explicit path comes last. The
assertions spell that order out with literal expected paths, so a dropped or misplaced
root fails instead of agreeing with a shared wrong order.

Nothing here spawns ``pi``, ``gh`` or ``git`` (AGENTS.md: no test may invoke a real Pi
model); the one empirical probe was a manual RPC call answered from the loaded template
list, recorded in ``aidw/agents.py``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aidw import runner as runner_mod
from aidw.config import load_all
from aidw.log import RunLogger
from aidw.paths import toolkit_root
from aidw.prompts import render_prompt_file
from aidw.prompts import inject_repo_conventions, render_prompt_file
from aidw.runner import StageSpec, resolve_prompt, run_stage
from aidw.state import create_run, run_dir

#: The committed fixture target repo (EXTRACTION.md §3.12) and its one committed override.
FIXTURE_TARGET = toolkit_root() / "fixtures" / "target-repo"
FIXTURE_OVERRIDE = FIXTURE_TARGET / "aidw" / "prompts" / "code-review.md"
FIXTURE_MARKER = "E4.2 FIXTURE OVERRIDE"
TOOLKIT_DEFAULT = toolkit_root() / "prompts" / "code-review.md"


def _write_prompt(path: Path, marker: str) -> Path:
    """Write a template whose frontmatter description and body are ``marker``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ndescription: {marker}\n---\n{marker}\n", encoding="utf-8"
    )
    return path


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    """A throwaway toolkit root plus a target repo root (no ``aidw/`` folder yet)."""
    toolkit = tmp_path / "toolkit"
    target = tmp_path / "target"
    (toolkit / "prompts").mkdir(parents=True)
    target.mkdir()
    return toolkit, target


def _template_roots(argv: list[str]) -> list[str]:
    """Extract the ``--prompt-template`` values in emitted order."""
    return [argv[i + 1] for i, item in enumerate(argv) if item == "--prompt-template"]


def _run_dry_stage(
    tmp_path: Path,
    target: Path,
    *,
    prompt: Path,
    monkeypatch: pytest.MonkeyPatch,
    explicit_prompt: str | None = None,
) -> tuple[list[str], str]:
    """Dry-run one ``code-reviewer`` stage and return the real argv plus rendered text.

    ``build_argv`` is wrapped only to capture the argv ``run_stage`` actually hands to
    Pi; the emitted list is the production one, so this is the dry-run argv and not a
    re-derivation of the helper's output.
    """
    agents, issues = load_all(toolkit_root(), target)
    assert not [issue for issue in issues if issue.level == "error"], issues

    runs_root = tmp_path / "runs"
    run = create_run(runs_root, target, "stage", label="prompt-resolution")
    directory = run_dir(runs_root, run.run_id)
    logger = RunLogger(directory)
    recorded: dict[str, list[str]] = {}

    real_build_argv = runner_mod.build_argv

    def recording_build_argv(agent, **kwargs):  # noqa: ANN001 - mirrors build_argv
        argv = real_build_argv(agent, **kwargs)
        recorded["argv"] = argv
        return argv

    monkeypatch.setattr(runner_mod, "build_argv", recording_build_argv)

    run_stage(
        StageSpec(
            name="code-review",
            agent_id="code-reviewer",
            prompt=prompt,
            variables=[],
            explicit_prompt=explicit_prompt,
        ),
        repo_root=target,
        toolkit_root=toolkit_root(),
        state=run,
        logger=logger,
        agents=agents,
        dry_run=True,
        runs_root=runs_root,
    )

    # W1.2: a dry run writes no ``prompts/<stage>.rendered.md``; the text is computed with
    # the same pure calls ``run_stage`` applies (pinned by
    # `tests/test_conventions_injection.py::test_written_render_and_pi_stdin_receive_...`).
    rendered = inject_repo_conventions(render_prompt_file(prompt, []), prompt, target)
    assert not (directory / "prompts" / "code-review.rendered.md").exists()
    return recorded["argv"], rendered


# --------------------------------------------------------------------------- #
# The four precedence levels (§3.4, D14)
# --------------------------------------------------------------------------- #


def test_explicit_path_wins_over_shadow_and_toolkit_default(tmp_path: Path) -> None:
    """Precedence 1: the stage config's declared ``prompt:`` path beats both others."""
    toolkit, target = _tree(tmp_path)
    _write_prompt(toolkit / "prompts" / "code-review.md", "TOOLKIT DEFAULT")
    _write_prompt(target / "aidw" / "prompts" / "code-review.md", "TARGET SHADOW")
    declared = _write_prompt(
        target / "aidw" / "prompts" / "declared.md", "DECLARED EXPLICIT"
    )

    resolved = resolve_prompt(
        toolkit, target, "code-review", "aidw/prompts/declared.md"
    )

    assert resolved == declared.resolve()
    assert "DECLARED EXPLICIT" in resolved.read_text(encoding="utf-8")


def test_absolute_explicit_path_is_used_as_declared(tmp_path: Path) -> None:
    """§3.4's example is target-relative; an absolute declared path is not re-based."""
    toolkit, target = _tree(tmp_path)
    _write_prompt(toolkit / "prompts" / "code-review.md", "TOOLKIT DEFAULT")
    elsewhere = _write_prompt(tmp_path / "elsewhere" / "declared.md", "ABSOLUTE EX")

    assert resolve_prompt(toolkit, target, "code-review", str(elsewhere)) == elsewhere


def test_target_shadow_wins_over_the_toolkit_default(tmp_path: Path) -> None:
    """Precedence 2 (D14 filename shadowing) beats precedence 3 (D4 default)."""
    toolkit, target = _tree(tmp_path)
    _write_prompt(toolkit / "prompts" / "code-review.md", "TOOLKIT DEFAULT")
    shadow = _write_prompt(target / "aidw" / "prompts" / "code-review.md", "TARGET SHADOW")

    assert resolve_prompt(toolkit, target, "code-review") == shadow.resolve()


def test_toolkit_default_used_when_the_target_has_no_shadow(tmp_path: Path) -> None:
    """Precedence 3 (D4): a target with no override still gets a working prompt."""
    toolkit, target = _tree(tmp_path)
    default = _write_prompt(toolkit / "prompts" / "code-review.md", "TOOLKIT DEFAULT")
    (target / "aidw" / "prompts").mkdir(parents=True)  # present but unrelated

    assert resolve_prompt(toolkit, target, "code-review") == default.resolve()


# --------------------------------------------------------------------------- #
# Precedence 4: fail closed, never a silent skip (§3.4, §3.11)
# --------------------------------------------------------------------------- #


def test_unresolvable_name_fails_closed_naming_every_searched_location(
    tmp_path: Path,
) -> None:
    toolkit, target = _tree(tmp_path)

    with pytest.raises(FileNotFoundError) as excinfo:
        resolve_prompt(toolkit, target, "code-review")

    message = str(excinfo.value)
    assert "code-review" in message
    assert "explicit_path is None" in message
    assert str(target / "aidw" / "prompts" / "code-review.md") in message
    assert str(toolkit / "prompts" / "code-review.md") in message


def test_missing_declared_path_does_not_fall_through_to_shadow_or_toolkit(
    tmp_path: Path,
) -> None:
    """A declared-but-missing ``prompt:`` is an error, not a best-effort fallback."""
    toolkit, target = _tree(tmp_path)
    _write_prompt(toolkit / "prompts" / "code-review.md", "TOOLKIT DEFAULT")
    shadow = _write_prompt(
        target / "aidw" / "prompts" / "code-review.md", "TARGET SHADOW"
    )
    missing = target / "aidw" / "prompts" / "missing.md"

    with pytest.raises(FileNotFoundError) as excinfo:
        resolve_prompt(toolkit, target, "code-review", "aidw/prompts/missing.md")

    message = str(excinfo.value)
    assert str(missing) in message
    assert "explicit_path is set" in message
    # Neither default location is offered as an alternative: only the declared path is
    # searched when one is declared.
    assert str(shadow) not in message
    assert str(toolkit / "prompts" / "code-review.md") not in message


# --------------------------------------------------------------------------- #
# Name normalisation: ``code-review`` and ``code-review.md`` are the same prompt
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("shadow_present", [False, True])
def test_bare_and_md_suffixed_names_resolve_to_the_same_file(
    tmp_path: Path, shadow_present: bool
) -> None:
    """The old resolver stripped one ``.md``; ``aidw exec --prompt code-review.md`` works."""
    toolkit, target = _tree(tmp_path)
    expected = _write_prompt(
        toolkit / "prompts" / "code-review.md", "TOOLKIT DEFAULT"
    ).resolve()
    if shadow_present:
        expected = _write_prompt(
            target / "aidw" / "prompts" / "code-review.md", "TARGET SHADOW"
        ).resolve()

    assert resolve_prompt(toolkit, target, "code-review") == expected
    assert resolve_prompt(toolkit, target, "code-review.md") == expected


def test_shadow_choice_is_invariant_to_the_toolkit_default_appearing(
    tmp_path: Path,
) -> None:
    """Metamorphic: adding a lower-precedence file never changes the winning prompt.

    The project's AGENTS.md has no §6 property-harness rule and ``pyproject.toml`` has no
    property-test dependency, so this is the dependency-free form: change one input the
    precedence must ignore and assert the result is stable.
    """
    toolkit, target = _tree(tmp_path)
    shadow = _write_prompt(target / "aidw" / "prompts" / "code-review.md", "TARGET SHADOW")

    before = resolve_prompt(toolkit, target, "code-review")
    _write_prompt(toolkit / "prompts" / "code-review.md", "TOOLKIT DEFAULT")
    after = resolve_prompt(toolkit, target, "code-review")

    assert before == after == shadow.resolve()


# --------------------------------------------------------------------------- #
# Purity: a leaf of ``Path`` existence checks, no process spawns, no writes
# --------------------------------------------------------------------------- #


def test_resolution_is_a_pure_existence_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolkit, target = _tree(tmp_path)
    shadow = _write_prompt(target / "aidw" / "prompts" / "code-review.md", "TARGET SHADOW")
    declared = _write_prompt(
        target / "aidw" / "prompts" / "declared.md", "DECLARED EXPLICIT"
    )
    original = shadow.read_text(encoding="utf-8")
    target_before = sorted(str(path) for path in target.rglob("*"))
    toolkit_before = sorted(str(path) for path in toolkit.rglob("*"))

    def _forbidden_spawn(*args: object, **kwargs: object) -> None:
        raise AssertionError("resolve_prompt must not spawn a process")

    monkeypatch.setattr(subprocess, "run", _forbidden_spawn)
    monkeypatch.setattr(subprocess, "Popen", _forbidden_spawn)
    monkeypatch.setattr(subprocess, "check_output", _forbidden_spawn)

    assert resolve_prompt(toolkit, target, "code-review") == shadow.resolve()
    assert (
        resolve_prompt(toolkit, target, "code-review", "aidw/prompts/declared.md")
        == declared.resolve()
    )

    assert shadow.read_text(encoding="utf-8") == original
    assert sorted(str(path) for path in target.rglob("*")) == target_before
    assert sorted(str(path) for path in toolkit.rglob("*")) == toolkit_before


# --------------------------------------------------------------------------- #
# Pi's template roots: the recorded empirical order, asserted on the dry-run argv
# --------------------------------------------------------------------------- #


def test_template_roots_pin_target_first_and_explicit_path_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Literal expected roots from the probe: target → toolkit → declared path.

    The leading position is the winner under Pi 1.2.0 (first ``--prompt-template`` root
    wins — see ``aidw/agents.py``), so the target override shadows the toolkit default.
    """
    target = tmp_path / "target"
    (target / "aidw" / "prompts").mkdir(parents=True)
    declared_rel = "aidw/prompts/traceability.md"
    declared = _write_prompt(target / declared_rel, "DECLARED EXPLICIT")
    prompt = resolve_prompt(toolkit_root(), target, "traceability", declared_rel)
    assert prompt == declared.resolve()

    argv, _rendered = _run_dry_stage(
        tmp_path,
        target,
        prompt=prompt,
        explicit_prompt=declared_rel,
        monkeypatch=monkeypatch,
    )

    assert _template_roots(argv) == [
        str(target / "aidw" / "prompts"),
        str(toolkit_root() / "prompts"),
        str(declared.resolve()),
    ]


def test_template_roots_omit_a_target_without_an_override_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§3.4: a repo with no ``aidw/`` folder gets the toolkit's pure defaults."""
    target = tmp_path / "no-aidw-folder"
    target.mkdir()
    prompt = resolve_prompt(toolkit_root(), target, "code-review")

    argv, _rendered = _run_dry_stage(
        tmp_path, target, prompt=prompt, monkeypatch=monkeypatch
    )

    assert _template_roots(argv) == [str(toolkit_root() / "prompts")]


def test_template_roots_include_a_present_but_empty_override_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The helper keys on the directory existing, not on it having contents (probe 3)."""
    target = tmp_path / "empty-aidw-prompts"
    (target / "aidw" / "prompts").mkdir(parents=True)
    prompt = resolve_prompt(toolkit_root(), target, "code-review")

    argv, _rendered = _run_dry_stage(
        tmp_path, target, prompt=prompt, monkeypatch=monkeypatch
    )

    assert _template_roots(argv) == [
        str(target / "aidw" / "prompts"),
        str(toolkit_root() / "prompts"),
    ]


def test_fixture_override_end_to_end_renders_the_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Done-when: the committed fixture override is what the stage renders and what Pi
    receives in the winning template root."""
    assert FIXTURE_OVERRIDE.is_file(), FIXTURE_OVERRIDE
    resolved = resolve_prompt(toolkit_root(), FIXTURE_TARGET, "code-review")

    assert resolved == FIXTURE_OVERRIDE.resolve()
    assert resolved != (toolkit_root() / "prompts" / "code-review.md")

    argv, rendered = _run_dry_stage(
        tmp_path, FIXTURE_TARGET, prompt=resolved, monkeypatch=monkeypatch
    )

    assert FIXTURE_MARKER in rendered
    # Exactly the override's rendered body — not the toolkit default's (design §7.3
    # strips the frontmatter before rendering).
    assert rendered == render_prompt_file(FIXTURE_OVERRIDE)
    assert rendered != render_prompt_file(TOOLKIT_DEFAULT)
    roots = _template_roots(argv)
    assert roots == [
        str(FIXTURE_TARGET / "aidw" / "prompts"),
        str(toolkit_root() / "prompts"),
    ]
    # The winning position — the first root — is the fixture override's directory.
    assert roots[0] == str(FIXTURE_OVERRIDE.parent)
