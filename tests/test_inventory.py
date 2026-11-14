"""Contract tests for the prompt/script inventory (design §7.2, EXTRACTION.md §3.6).

These tests are the executable specification of :mod:`aidw.inventory`'s two halves
(E7.5):

- :func:`aidw.inventory.check_defaults` — the toolkit's own tree, behaviour unchanged from
  the pre-split ``check``: missing required prompts/scripts, the ``.pi/prompts`` sentinel
  over ``.md``/``.py``/``.json``, the ``VENDOR.md`` warning, and ``AIDW_SCRIPTS_DIR`` in
  every script-invoking prompt.
- :func:`aidw.inventory.check_resolved` — what a target repo actually runs. Provenance
  comes from :func:`aidw.runner.resolve_prompt` (§3.6's precedence is never reimplemented
  here), target-side issues carry the target-relative ``aidw/prompts/…`` label, scripts are
  not part of this half, and a default-resolved file is never re-swept.

The seeded property run at the bottom is this repo's pytest-only substitute for
``hypothesis`` (AGENTS.md "Tests"): a pinned seed and run count, no shrinking.
"""

from __future__ import annotations

import random
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from aidw import inventory
from aidw.config import ERROR, WARNING
from aidw.paths import SCRIPTS_DIR_ENV_VAR, toolkit_root

FOREIGN = inventory.FOREIGN_PREFIX


# --------------------------------------------------------------------------- #
# Fixtures: minimal toolkit/default trees and target override trees
# --------------------------------------------------------------------------- #


def _toolkit(
    base: Path,
    *,
    complete: bool = True,
    files: Mapping[str, str] | None = None,
) -> Path:
    """A fake toolkit root at ``<base>/toolkit``.

    ``complete`` writes every required prompt and script; the script-invoking prompts
    carry ``AIDW_SCRIPTS_DIR`` so a complete tree is issue-free. ``files`` adds/overwrites
    entries relative to ``prompts/``.
    """
    root = base / "toolkit"
    prompts = root / "prompts"
    prompts.mkdir(parents=True)
    if complete:
        for name in inventory.REQUIRED_PROMPTS:
            text = "# prompt\n"
            if name in inventory.PROMPT_INVOKED_SCRIPTS:
                text = f'"{SCRIPTS_DIR_ENV_VAR}/review-followup/review_followup.py"\n'
            (prompts / name).write_text(text, encoding="utf-8")
        for rel in inventory.REQUIRED_SCRIPTS:
            path = prompts / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# script\n", encoding="utf-8")
    for rel, text in (files or {}).items():
        path = prompts / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _target(base: Path, overrides: Mapping[str, str] | None = None) -> Path:
    """A fake target root at ``<base>/target`` with ``overrides`` under ``aidw/prompts``."""
    root = base / "target"
    root.mkdir(parents=True)
    for rel, text in (overrides or {}).items():
        path = root / "aidw" / "prompts" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _defaults(root: Path) -> list[object]:
    return inventory.check_defaults(root)


def _resolved(toolkit: Path, target: Path) -> inventory.ResolvedInventory:
    return inventory.check_resolved(toolkit, target)


def _errors(issues) -> list:
    return [issue for issue in issues if issue.level == ERROR]


def _sentinel_sources(issues) -> list[str]:
    return sorted(issue.source for issue in issues if FOREIGN in issue.message)


def _env_sources(issues) -> list[str]:
    return sorted(
        issue.source for issue in issues if SCRIPTS_DIR_ENV_VAR in issue.message
    )


# --------------------------------------------------------------------------- #
# check_defaults: the pre-split behaviour, ported vector for vector
# --------------------------------------------------------------------------- #


def test_real_toolkit_defaults_are_complete() -> None:
    assert _errors(_defaults(toolkit_root())) == []


def test_real_toolkit_defaults_have_no_legacy_manifest() -> None:
    issues = _defaults(toolkit_root())
    assert not any(issue.source == inventory.LEGACY_MANIFEST for issue in issues)


def test_list_files_includes_known_prompts() -> None:
    files = inventory.list_files(toolkit_root())
    assert "code-review.md" in files
    assert "scripts/review-followup/review_followup.py" in files


def test_required_prompts_include_the_summary_stage() -> None:
    """X1.1: the `I8` stage's prompt is a required default, not an optional extra.

    ``REQUIRED_PROMPTS`` is what makes a rename fail loudly instead of at Pi invocation
    (AGENTS.md "Prompts and agent configs are the product contract"), so the stage the
    registry schedules must be listed here beside ``record-implementation-results.md``.
    """
    assert "summarize-implementation-results.md" in inventory.REQUIRED_PROMPTS
    # The real toolkit ships it, and the defaults half resolves it without issues.
    assert "summarize-implementation-results.md" in inventory.list_files(toolkit_root())
    assert _errors(_defaults(toolkit_root())) == []


def test_missing_prompts_dir_is_error(tmp_path: Path) -> None:
    issues = inventory.check_defaults(tmp_path / "aidt")
    assert issues and issues[0].level == ERROR


def test_missing_required_prompt_is_error_in_defaults(tmp_path: Path) -> None:
    root = _toolkit(tmp_path, complete=False, files={"task-prompt.md": "ok\n"})
    issues = _defaults(root)
    assert any(
        issue.level == ERROR and issue.source == "code-review.md" for issue in issues
    )


def test_foreign_reference_in_a_toolkit_prompt_is_error(tmp_path: Path) -> None:
    root = _toolkit(tmp_path, files={"notes.md": "see .pi/prompts/x.md\n"})
    assert _sentinel_sources(_defaults(root)) == ["notes.md"]


def test_foreign_reference_in_a_toolkit_python_file_is_error(tmp_path: Path) -> None:
    root = _toolkit(tmp_path, files={"helper.py": "# see .pi/prompts/x.md\n"})
    assert _sentinel_sources(_defaults(root)) == ["helper.py"]


def test_legacy_manifest_is_warning(tmp_path: Path) -> None:
    root = _toolkit(tmp_path, files={inventory.LEGACY_MANIFEST: "old\n"})
    issues = _defaults(root)
    assert any(
        issue.level == WARNING and issue.source == inventory.LEGACY_MANIFEST
        for issue in issues
    )


def test_a_toolkit_prompt_invoking_a_script_must_use_the_env_var(
    tmp_path: Path,
) -> None:
    """A cwd-relative script path resolves inside the target repo, not the toolkit."""
    root = _toolkit(
        tmp_path,
        files={
            "approve-review-followups.md": (
                'runner="python3 aidt/prompts/scripts/review-followup/'
                'review_followup.py"\n'
            )
        },
    )

    issues = _defaults(root)

    assert _env_sources(issues) == ["approve-review-followups.md"]


# --------------------------------------------------------------------------- #
# check_resolved: provenance over REQUIRED_PROMPTS only (§3.6, D14)
# --------------------------------------------------------------------------- #


def test_real_self_hosted_resolution_reports_every_prompt_as_a_toolkit_default() -> None:
    """The toolkit repo has no ``aidw/prompts/``: self-hosted is the all-defaults case."""
    report = _resolved(toolkit_root(), toolkit_root())

    assert report.issues == ()
    assert [prompt.name for prompt in report.prompts] == list(
        inventory.REQUIRED_PROMPTS
    )
    assert all(prompt.origin == inventory.ORIGIN_TOOLKIT for prompt in report.prompts)
    assert [prompt.display for prompt in report.prompts] == [
        f"prompts/{name}" for name in inventory.REQUIRED_PROMPTS
    ]


def test_a_target_shadow_resolves_and_is_reported_as_a_repo_override(
    tmp_path: Path,
) -> None:
    toolkit = _toolkit(tmp_path)
    target = _target(tmp_path, {"code-review.md": "# repo review\n"})
    shadow_file = target / "aidw" / "prompts" / "code-review.md"

    report = _resolved(toolkit, target)

    assert report.issues == ()
    resolved = {prompt.name: prompt for prompt in report.prompts}
    assert resolved["code-review.md"].origin == inventory.ORIGIN_TARGET
    assert resolved["code-review.md"].path == shadow_file.resolve()
    assert resolved["code-review.md"].display == "aidw/prompts/code-review.md"
    assert resolved["code-review.md"].label == "repo override"
    # Untouched names keep resolving to the toolkit default.
    assert resolved["test.md"].origin == inventory.ORIGIN_TOOLKIT


def test_a_target_without_overrides_resolves_every_prompt_to_the_toolkit_default(
    tmp_path: Path,
) -> None:
    toolkit = _toolkit(tmp_path)
    target = _target(tmp_path)

    report = _resolved(toolkit, target)

    assert report.issues == ()
    assert len(report.prompts) == len(inventory.REQUIRED_PROMPTS)
    assert {prompt.origin for prompt in report.prompts} == {inventory.ORIGIN_TOOLKIT}
    for prompt in report.prompts:
        assert prompt.path == (toolkit / "prompts" / prompt.name).resolve()
        assert prompt.display == f"prompts/{prompt.name}"


def test_the_two_displays_of_one_basename_differ(tmp_path: Path) -> None:
    """The relative-path collision: ``code-review.md`` twice must stay tellable apart."""
    toolkit = _toolkit(tmp_path)
    shadowed = _resolved(
        toolkit, _target(tmp_path, {"code-review.md": "# repo review\n"})
    )
    plain = _resolved(toolkit, _target(tmp_path / "plain"))

    shadow = {prompt.name: prompt for prompt in shadowed.prompts}["code-review.md"]
    default = {prompt.name: prompt for prompt in plain.prompts}["code-review.md"]

    assert shadow.display == "aidw/prompts/code-review.md"
    assert shadow.label == "repo override"
    assert default.display == "prompts/code-review.md"
    assert default.label == "toolkit default"
    assert shadow.display != default.display


def test_an_unresolvable_required_prompt_names_every_searched_location(
    tmp_path: Path,
) -> None:
    toolkit = _toolkit(tmp_path)
    (toolkit / "prompts" / "code-review.md").unlink()
    target = _target(tmp_path)

    issues = _errors(_resolved(toolkit, target).issues)

    assert len(issues) == 1, issues
    assert issues[0].source == "aidw/prompts/code-review.md"
    assert "prompt not found" in issues[0].message
    # Both §3.6 levels are named, so the operator knows neither location has it.
    assert str(target / "aidw" / "prompts" / "code-review.md") in issues[0].message
    assert str(toolkit / "prompts" / "code-review.md") in issues[0].message


def test_scripts_are_not_part_of_the_resolved_half(tmp_path: Path) -> None:
    """§3.6: the bundled scripts stay toolkit-side; a target never shadows them."""
    toolkit = _toolkit(tmp_path)
    for rel in inventory.REQUIRED_SCRIPTS:
        (toolkit / "prompts" / rel).unlink()
    target = _target(tmp_path)

    # Every required prompt resolves, so the resolved half is clean even though every
    # script is missing — the defaults half owns REQUIRED_SCRIPTS.
    assert _resolved(toolkit, target).issues == ()
    assert {issue.source for issue in _errors(_defaults(toolkit))} == set(
        inventory.REQUIRED_SCRIPTS
    )


# --------------------------------------------------------------------------- #
# Sentinel and AIDW_SCRIPTS_DIR parity across the two halves
# --------------------------------------------------------------------------- #


def test_a_target_override_with_a_foreign_reference_is_a_target_side_error(
    tmp_path: Path,
) -> None:
    toolkit = _toolkit(tmp_path)
    target = _target(tmp_path, {"notes.md": "see .pi/prompts/notes.md\n"})

    report = _resolved(toolkit, target)

    assert _sentinel_sources(report.issues) == ["aidw/prompts/notes.md"]
    assert all(issue.level == ERROR for issue in report.issues)
    assert "target repo" in report.issues[0].message
    # The defaults half never sees the target tree, so it stays clean.
    assert _defaults(toolkit) == []


def test_the_same_foreign_reference_in_a_toolkit_default_is_a_defaults_side_error(
    tmp_path: Path,
) -> None:
    toolkit = _toolkit(tmp_path)
    target = _target(tmp_path)
    (toolkit / "prompts" / "code-review.md").write_text(
        "see .pi/prompts/code-review.md\n", encoding="utf-8"
    )

    assert _sentinel_sources(_defaults(toolkit)) == ["code-review.md"]
    # The resolved half re-reads a required default only to prove it exists: the same
    # file is not double-counted, because check_defaults already owns it.
    report = _resolved(toolkit, target)
    assert report.issues == ()
    assert {
        prompt.origin for prompt in report.prompts if prompt.name == "code-review.md"
    } == {inventory.ORIGIN_TOOLKIT}


def test_a_shadowed_script_invoking_prompt_must_use_the_env_var(
    tmp_path: Path,
) -> None:
    toolkit = _toolkit(tmp_path)
    target = _target(
        tmp_path,
        {
            "approve-review-followups.md": (
                'runner="python3 aidt/prompts/scripts/review-followup/'
                'review_followup.py"\n'
            )
        },
    )

    report = _resolved(toolkit, target)

    assert _env_sources(report.issues) == [
        "aidw/prompts/approve-review-followups.md"
    ]
    # The toolkit default of the same name is fine, so no defaults-side duplicate.
    assert _env_sources(_defaults(toolkit)) == []


def test_a_shadowed_script_invoking_prompt_using_the_env_var_is_clean(
    tmp_path: Path,
) -> None:
    toolkit = _toolkit(tmp_path)
    target = _target(
        tmp_path,
        {
            "approve-review-followups.md": (
                f'"${{{SCRIPTS_DIR_ENV_VAR}}}/review-followup/review_followup.py"\n'
            )
        },
    )

    assert _resolved(toolkit, target).issues == ()


def test_a_default_resolved_script_prompt_is_not_rechecked_by_the_resolved_half(
    tmp_path: Path,
) -> None:
    """The default is broken, but only the defaults half may say so — no double count."""
    toolkit = _toolkit(tmp_path)
    (toolkit / "prompts" / "approve-review-followups.md").write_text(
        'runner="python3 aidt/prompts/scripts/..."\n', encoding="utf-8"
    )
    target = _target(tmp_path)

    assert _env_sources(_defaults(toolkit)) == ["approve-review-followups.md"]
    assert _resolved(toolkit, target).issues == ()


def test_repo_added_nested_prompt_named_like_a_script_is_not_treated_as_a_shadow(
    tmp_path: Path,
) -> None:
    """The script-env contract applies to a direct filename shadow, not repo-added paths."""
    toolkit = _toolkit(tmp_path)
    target = _target(
        tmp_path,
        {
            "extra/approve-review-followups.md": (
                'runner="python3 aidt/prompts/scripts/review-followup/'
                'review_followup.py"\n'
            )
        },
    )

    report = _resolved(toolkit, target)

    # The whole override tree is still swept for the foreign sentinel, but a nested
    # repo-added prompt is not the file resolve_prompt would run for this basename.
    assert report.issues == ()


# --------------------------------------------------------------------------- #
# Independence: one group's failure never masks the other's (requirement 6)
# --------------------------------------------------------------------------- #


def test_a_missing_default_and_a_target_sentinel_surface_one_per_group(
    tmp_path: Path,
) -> None:
    """``pr.md`` is missing from the toolkit but shadowed; a separate override is dirty.

    The defaults group reports the missing default (it never consults the target), the
    resolved group reports the target sentinel and *not* the missing file (the shadow
    resolves it), and neither group's finding is suppressed by the other's.
    """
    toolkit = _toolkit(tmp_path)
    (toolkit / "prompts" / "pr.md").unlink()
    target = _target(
        tmp_path,
        {
            "pr.md": "# repo pr\n",
            "notes.md": "see .pi/prompts/notes.md\n",
        },
    )

    default_issues = _defaults(toolkit)
    report = _resolved(toolkit, target)

    assert [issue.source for issue in _errors(default_issues)] == ["pr.md"]
    assert _sentinel_sources(default_issues) == []
    assert _sentinel_sources(report.issues) == ["aidw/prompts/notes.md"]
    assert "pr.md" not in {issue.source for issue in report.issues}
    resolved = {prompt.name: prompt for prompt in report.prompts}
    assert resolved["pr.md"].origin == inventory.ORIGIN_TARGET


# --------------------------------------------------------------------------- #
# Purity: reads and `Path` existence checks only — no writes, no spawns
# --------------------------------------------------------------------------- #


def test_check_resolved_is_pure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toolkit = _toolkit(tmp_path)
    target = _target(
        tmp_path,
        {
            "code-review.md": "# repo review\n",
            "notes.md": "see .pi/prompts/notes.md\n",
            "approve-review-followups.md": 'runner="python3 aidw/..."\n',
        },
    )
    toolkit_before = sorted(str(path) for path in toolkit.rglob("*"))
    target_before = sorted(str(path) for path in target.rglob("*"))
    texts_before = {
        path: path.read_text(encoding="utf-8")
        for path in target.rglob("*.md")
    }

    def _forbidden_spawn(*args: object, **kwargs: object) -> None:
        raise AssertionError("check_resolved must not spawn a process")

    monkeypatch.setattr(subprocess, "run", _forbidden_spawn)
    monkeypatch.setattr(subprocess, "Popen", _forbidden_spawn)
    monkeypatch.setattr(subprocess, "check_output", _forbidden_spawn)

    report = _resolved(toolkit, target)

    assert [prompt.name for prompt in report.prompts]
    assert report.issues
    assert sorted(str(path) for path in toolkit.rglob("*")) == toolkit_before
    assert sorted(str(path) for path in target.rglob("*")) == target_before
    assert {
        path: path.read_text(encoding="utf-8") for path in target.rglob("*.md")
    } == texts_before


def test_check_resolved_does_not_mutate_its_arguments(tmp_path: Path) -> None:
    toolkit = _toolkit(tmp_path)
    target = _target(tmp_path, {"code-review.md": "# repo review\n"})
    before = (toolkit, target)

    _resolved(toolkit, target)

    assert (toolkit, target) == before
    assert toolkit == before[0] and target == before[1]


# --------------------------------------------------------------------------- #
# Property run: resolution is a function of file presence (AGENTS.md "Tests":
# pytest only, so a pinned seed + run count instead of hypothesis)
# --------------------------------------------------------------------------- #

#: Pinned seed and run count. Same seed + count => same cases on every machine.
PROPERTY_SEED = 7511
PROPERTY_RUNS = 48


def _random_case(rng: random.Random) -> dict[str, object]:
    """One generated (shadows, missing defaults, extra overrides) combination."""
    names = list(inventory.REQUIRED_PROMPTS)
    shadowed = [name for name in names if rng.random() < 0.35]
    # Only names without a shadow can be missing everywhere — otherwise "missing default"
    # and "unresolvable" collapse into the same case.
    missing_defaults = [
        name for name in names if name not in shadowed and rng.random() < 0.15
    ]
    script_flags = {
        name: rng.random() < 0.5 for name in shadowed if name in inventory.PROMPT_INVOKED_SCRIPTS
    }
    sentinel_shadows = {name for name in shadowed if rng.random() < 0.2}
    extras = [
        (f"notes-{index}.md", rng.random() < 0.5)
        for index in range(rng.randrange(0, 3))
    ]
    return {
        "shadowed": shadowed,
        "missing_defaults": missing_defaults,
        "script_flags": script_flags,
        "sentinel_shadows": sentinel_shadows,
        "extras": extras,
    }


def test_resolution_is_a_function_of_file_presence_only(tmp_path: Path) -> None:
    """Property: provenance, unresolved names and target-side issues follow the files.

    For every generated case: a required name resolves to the target shadow exactly when
    one exists, else to the default exactly when the toolkit has it, else to exactly one
    ERROR naming both searched locations. Target-side sentinel/``AIDW_SCRIPTS_DIR``
    issues are exactly one per offending override file, the defaults group reports
    exactly the missing defaults, and the two never mask or double-count each other.
    """
    rng = random.Random(PROPERTY_SEED)
    cases = [_random_case(rng) for _ in range(PROPERTY_RUNS)]
    assert len(cases) == PROPERTY_RUNS

    for index, case in enumerate(cases):
        base = tmp_path / f"run{index}"
        toolkit = _toolkit(base)
        target = _target(base)

        for name in case["missing_defaults"]:
            (toolkit / "prompts" / name).unlink()

        expected_target_files: dict[str, str] = {}
        for name in case["shadowed"]:
            text = "# shadow\n"
            if name in inventory.PROMPT_INVOKED_SCRIPTS and case["script_flags"][name]:
                text += f"${{{SCRIPTS_DIR_ENV_VAR}}}/review-followup/review_followup.py\n"
            if name in case["sentinel_shadows"]:
                text += "see .pi/prompts/old.md\n"
            expected_target_files[name] = text
        for name, sentinel in case["extras"]:
            expected_target_files[name] = "see .pi/prompts/old.md\n" if sentinel else "# extra\n"
        for rel, text in expected_target_files.items():
            path = target / "aidw" / "prompts" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        report = _resolved(toolkit, target)
        resolved = {prompt.name: prompt for prompt in report.prompts}

        # (1) provenance follows presence, never order or name.
        for name in inventory.REQUIRED_PROMPTS:
            shadowed = name in case["shadowed"]
            available = name not in case["missing_defaults"]
            if shadowed:
                assert resolved[name].origin == inventory.ORIGIN_TARGET, (index, name)
                assert resolved[name].path == (
                    target / "aidw" / "prompts" / name
                ).resolve()
            elif available:
                assert resolved[name].origin == inventory.ORIGIN_TOOLKIT, (index, name)
                assert resolved[name].path == (toolkit / "prompts" / name).resolve()
            else:
                assert name not in resolved, (index, name)

        # (2) exactly one unresolvable ERROR per missing-and-unshadowed name.
        unresolvable = {
            issue.source
            for issue in report.issues
            if "prompt not found" in issue.message
        }
        expected_unresolvable = {
            f"aidw/prompts/{name}"
            for name in case["missing_defaults"]
            if name not in case["shadowed"]
        }
        assert unresolvable == expected_unresolvable, index
        assert len(report.prompts) + len(unresolvable) == len(
            inventory.REQUIRED_PROMPTS
        ), index

        # (3) target-side issues are exactly one per offending override file.
        dirty_targets = {
            f"aidw/prompts/{rel}"
            for rel, text in expected_target_files.items()
            if FOREIGN in text
        }
        assert set(_sentinel_sources(report.issues)) == dirty_targets, index
        missing_env = {
            f"aidw/prompts/{name}"
            for name, text in expected_target_files.items()
            if name in inventory.PROMPT_INVOKED_SCRIPTS
            and SCRIPTS_DIR_ENV_VAR not in text
        }
        assert set(_env_sources(report.issues)) == missing_env, index
        assert len(report.issues) == len(dirty_targets) + len(
            missing_env
        ) + len(expected_unresolvable), index
        assert all(issue.level == ERROR for issue in report.issues), index

        # (4) the defaults group depends on the toolkit tree only.
        assert {
            issue.source
            for issue in _defaults(toolkit)
            if issue.level == ERROR
        } == set(case["missing_defaults"]), index
