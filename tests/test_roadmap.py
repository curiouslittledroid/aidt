"""Tests for roadmap parsing."""

from __future__ import annotations

import random
from fnmatch import fnmatch
from pathlib import Path

from aidw.roadmap import (
    _FILENAME_RE,
    derive_epic,
    filter_tasks,
    find_task,
    load_tasks,
    next_todo,
    parse_file,
)

FIXTURE = """# Phase 7: Test Phase

Some intro.

## Epic A: Alpha

- [x] **A1. First task** per Design 07 §1.
  - Done when: first is done.

- [ ] **A2. Second task** per Design 08.1.
  Done when: second is done.

## Epic B: Beta

- [ ] **B1. Third task** text.
  - Done when: third is done.
"""


def _write_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "07 - Test Phase.md"
    path.write_text(FIXTURE, encoding="utf-8")
    return path


def test_derive_epic() -> None:
    assert derive_epic("E2.9") == "E2"
    assert derive_epic("E2.8a") == "E2"
    assert derive_epic("E1.1") == "E1"
    assert derive_epic("A1") == "A"
    assert derive_epic("E2") == "E"
    assert derive_epic("T1") == "T"


def test_parse_file_extracts_tasks(tmp_path: Path) -> None:
    tasks = parse_file(_write_fixture(tmp_path), "07")
    assert [t.task for t in tasks] == ["A1", "A2", "B1"]
    assert tasks[0].done is True
    assert tasks[1].done is False
    assert tasks[0].epic == "A"
    assert tasks[1].epic == "A"
    assert tasks[2].epic == "B"


def test_parse_file_done_when_forms(tmp_path: Path) -> None:
    tasks = parse_file(_write_fixture(tmp_path), "07")
    assert tasks[0].done_when == "first is done."
    assert tasks[1].done_when == "second is done."
    assert tasks[2].done_when == "third is done."


def test_parse_file_citations_and_meta(tmp_path: Path) -> None:
    tasks = parse_file(_write_fixture(tmp_path), "07")
    assert "Design 07" in tasks[0].citations
    assert "Design 08.1" in tasks[1].citations
    assert tasks[0].phase_title == "Test Phase"
    assert tasks[0].epic_title == "Alpha"
    assert tasks[0].branch == "07-A1"


def test_find_filter_next(tmp_path: Path) -> None:
    tasks = parse_file(_write_fixture(tmp_path), "07")
    assert find_task(tasks, "07", "A", "A2") is not None
    assert find_task(tasks, "99", "A", "A2") is None
    assert [t.task for t in filter_tasks(tasks, todo=True)] == ["A2", "B1"]
    assert [t.task for t in filter_tasks(tasks, epic="A")] == ["A1", "A2"]
    assert next_todo(tasks).task == "A2"
    assert next_todo(tasks, phase="99") is None


#: The toolkit's default ``paths.roadmap_glob`` (``TOOLKIT_DEFAULTS.paths``, D17). Every
#: call passes a glob explicitly: ``load_tasks`` carries no pattern of its own (E5.2), so
#: the default is named once in the config module and not duplicated in the parser.
DEFAULT_GLOB = "[0-9]* - *.md"

#: A second, valid roadmap file body. Two files (not one) are what makes the ordering and
#: the "one parse per selected file" contract observable.
OTHER_FIXTURE = """# Phase 99: Other Phase

## Epic Z: Zed

- [ ] **Z1. Zed task** text.
  - Done when: zed is done.
"""


def _write(tmp_path: Path, name: str, body: str = OTHER_FIXTURE) -> None:
    (tmp_path / name).write_text(body, encoding="utf-8")


def test_load_tasks_reads_a_directory(tmp_path: Path) -> None:
    _write(tmp_path, "07 - Test Phase.md", FIXTURE)
    _write(tmp_path, "99 - Other Phase.md")
    tasks = load_tasks(tmp_path, DEFAULT_GLOB)
    assert [t.task for t in tasks] == ["A1", "A2", "B1", "Z1"]


def test_load_tasks_glob_pre_selects_but_the_filename_regex_is_the_phase_authority(
    tmp_path: Path,
) -> None:
    """One vector per selection rule: glob first, then ``_FILENAME_RE``, phase from prefix.

    ``0 - x.md`` and ``0123 - x.md`` are the trap: both match the default glob, both are
    rejected by ``_FILENAME_RE`` (exactly two digits), so neither may be parsed — and a
    glob alone must never be treated as the phase authority.
    """
    _write(tmp_path, "07 - Test Phase.md", FIXTURE)
    _write(tmp_path, "0 - One digit.md")
    _write(tmp_path, "0123 - Four digits.md")
    _write(tmp_path, "notes.md", "# Notes\n")

    # Hand-calculated: the glob admits three of the four, the filename pattern two of those.
    assert [fnmatch(name, DEFAULT_GLOB) for name in (
        "07 - Test Phase.md",
        "0 - One digit.md",
        "0123 - Four digits.md",
        "notes.md",
    )] == [True, True, True, False]
    assert _FILENAME_RE.match("0 - One digit.md") is None
    assert _FILENAME_RE.match("0123 - Four digits.md") is None

    tasks = load_tasks(tmp_path, DEFAULT_GLOB)

    assert [t.file for t in tasks] == ["07 - Test Phase.md"] * 3
    assert {t.phase for t in tasks} == {"07"}
    assert [t.task for t in tasks] == ["A1", "A2", "B1"]


def test_load_tasks_glob_drives_selection(tmp_path: Path) -> None:
    """A non-default glob really selects the files: it is not decorative.

    Both files are ``_FILENAME_RE``-valid, so only the glob can explain the difference.
    (A glob such as ``roadmap-*.md`` cannot be used as the vector: no name it selects
    starts with the two-digit prefix ``_FILENAME_RE`` requires, so it would select nothing
    and prove nothing about selection.)
    """
    _write(tmp_path, "04 - Roadmap.md")
    _write(tmp_path, "05 - Other.md")

    assert [t.phase for t in load_tasks(tmp_path, "*- Roadmap.md")] == ["04"]
    assert [t.phase for t in load_tasks(tmp_path, DEFAULT_GLOB)] == ["04", "05"]


def test_load_tasks_missing_directory_is_empty_not_an_error(tmp_path: Path) -> None:
    """Fail closed on the read, not by raising: the read-path check is the caller's (E3.7)."""
    assert load_tasks(tmp_path / "absent", DEFAULT_GLOB) == []


def test_load_tasks_is_pure_and_repeatable(tmp_path: Path) -> None:
    """No file is created, changed or removed, and two calls agree entry for entry."""
    _write(tmp_path, "07 - Test Phase.md", FIXTURE)
    _write(tmp_path, "07 - Ignored.md")  # same phase, its own tasks
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    first = load_tasks(tmp_path, DEFAULT_GLOB)
    second = load_tasks(tmp_path, DEFAULT_GLOB)

    assert first == second
    assert first is not second
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
    assert sorted(before) == ["07 - Ignored.md", "07 - Test Phase.md"]


#: Pinned seed and run count for the seeded property test below (AGENTS.md: pytest only, no
#: hypothesis, so a reproducible sample is the generator and there is no shrinking).
ROADMAP_PROPERTY_SEED = 5207
ROADMAP_PROPERTY_RUNS = 48

#: Filename shapes the seeded sample draws from, including the two the default glob admits
#: but ``_FILENAME_RE`` rejects, and two it admits neither way.
FILENAME_SHAPES = (
    "{n:02d} - Phase {n}.md",  # glob: yes · regex: yes (two digits)
    "{n:02d}.5 - Sub phase {n}.md",  # glob: yes · regex: yes (sub-phase)
    "{n} - Bare digit.md",  # glob: yes · regex: no (one digit)
    "0{n:03d} - Overflow.md",  # glob: yes · regex: no (four digits)
    "notes-{n}.md",  # glob: no · regex: no
)

#: Globs the sample draws from: the D17 default, a narrower prefix, a wider one.
GLOBS = ("[0-9]* - *.md", "*.md", "0[0-9]* - *.md", "*- Phase *.md")

PROPERTY_BODY = "- [ ] **P1. Property task** text.\n  - Done when: the property holds.\n"


def test_load_tasks_selection_property(tmp_path: Path) -> None:
    """Seeded property run (seed/runs pinned above): selection is glob ∘ filename pattern.

    For every sampled directory and glob, the entries ``load_tasks`` returns are exactly
    the files ``tasks_dir.glob(glob)`` admits *and* ``_FILENAME_RE`` matches, in sorted
    order, with the phase taken from the filename prefix — nothing else is parsed, nothing
    that matches is dropped, and ``parse_file`` result-for-result agrees per file.
    """
    rng = random.Random(ROADMAP_PROPERTY_SEED)

    for case in range(ROADMAP_PROPERTY_RUNS):
        root = tmp_path / f"case-{case}"
        root.mkdir()
        names = sorted(
            {
                rng.choice(FILENAME_SHAPES).format(n=rng.randint(0, 12))
                for _ in range(rng.randint(2, 5))
            }
        )
        for name in names:
            _write(root, name, PROPERTY_BODY)
        glob = rng.choice(GLOBS)

        # The expectation, computed from the two rules independently of `load_tasks`:
        # the glob pre-selects (`fnmatch` is what `Path.glob` uses for a single pattern),
        # `_FILENAME_RE` filters and supplies the phase.
        selected: list[str] = []
        expected: list[str] = []
        for name in names:
            match = _FILENAME_RE.match(name)
            if fnmatch(name, glob) and match is not None:
                selected.append(name)
                expected.append(match.group(1))

        tasks = load_tasks(root, glob)

        assert [task.phase for task in tasks] == expected, (case, glob, names)
        assert [task.file for task in tasks] == selected, (case, glob, names)
        assert all(task.task == "P1" for task in tasks), (case, glob, names)
        # Per file, `load_tasks` is exactly `parse_file(path, phase-from-filename)`.
        for name in selected:
            phase = _FILENAME_RE.match(name)
            assert phase is not None
            assert load_tasks(root, name) == parse_file(root / name, phase.group(1))
