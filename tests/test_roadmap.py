"""Tests for roadmap parsing (``aidw/roadmap.py``, design §11, roadmap-format.md).

The complete roadmap body these tests parse is **not** inline. Since E5.4 the canonical
example is the fenced block in ``docs/roadmap-format.md`` §9 and it is read from the doc's
current bytes on every run through ``tests/conftest.py``'s ``roadmap_example`` fixture, so
the doc and the parser cannot drift (EXTRACTION.md §3.7). The inline bodies that remain —
``OTHER_FIXTURE``, ``PROPERTY_BODY`` and the synthetic filenames — are *selection
mechanics* inputs (ordering, glob/regex pre-selection), not format examples.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

from aidw.roadmap import (
    _FILENAME_RE,
    RoadmapTask,
    derive_epic,
    filter_tasks,
    find_task,
    load_tasks,
    next_todo,
    parse_file,
)

if TYPE_CHECKING:  # pragma: no cover - type-only
    # A runtime ``from conftest import …`` binds whichever of the two collected
    # ``conftest`` modules was imported last and breaks the full-suite run; the fixture's
    # name is all these annotations need (``from __future__ import annotations``).
    from conftest import RoadmapExample


def test_derive_epic() -> None:
    assert derive_epic("E2.9") == "E2"
    assert derive_epic("E2.8a") == "E2"
    assert derive_epic("E1.1") == "E1"
    assert derive_epic("A1") == "A"
    assert derive_epic("E2") == "E"
    assert derive_epic("T1") == "T"


# --------------------------------------------------------------------------- #
# The canonical example (docs/roadmap-format.md §9), through parse_file
# --------------------------------------------------------------------------- #


def test_parse_file_extracts_tasks(tmp_path: Path, roadmap_example: RoadmapExample) -> None:
    """Hand-checkable vector from §9: three entries, in file order, none collapsed."""
    tasks = parse_file(roadmap_example.write(tmp_path), roadmap_example.phase)

    assert [task.task for task in tasks] == ["E5.1", "E5.2", "E6.1"]
    # E0.7 rule 1 / §5: a missing period collapses an id, so every id must still carry one.
    assert all("." in task.task for task in tasks)
    assert [task.done for task in tasks] == [True, False, False]
    assert [task.key for task in tasks] == ["07-E5.1", "07-E5.2", "07-E6.1"]
    assert next_todo(tasks).task == "E5.2"

    # `epic` is derived from the id, never read from the `## Epic` heading (§5).
    assert [task.epic for task in tasks] == ["E5", "E5", "E6"]
    assert [task.epic for task in tasks] == [derive_epic(task.task) for task in tasks]


def test_parse_file_done_when_forms(tmp_path: Path, roadmap_example: RoadmapExample) -> None:
    """`done_when` is the first physical line only (§6); §9's table gives the text."""
    tasks = parse_file(roadmap_example.write(tmp_path), roadmap_example.phase)

    assert [task.done_when for task in tasks] == [
        "the format doc states the five-regex contract and the worked example in it",
        "the fixture repo's roadmap parses without any code change.",
        "the bundled scripts still run standalone with no config present.",
    ]


def test_parse_file_citations_and_meta(tmp_path: Path, roadmap_example: RoadmapExample) -> None:
    """§8.1's `Design N` channel, plus the cosmetic headings and the derived branch."""
    tasks = parse_file(roadmap_example.write(tmp_path), roadmap_example.phase)

    # `EXTRACTION.md` is the doc-ref channel, which never reaches `.citations` (§8.2).
    assert [task.citations for task in tasks] == [["Design 11"], ["Design 11.1"], []]
    # `phase`/`phase_title` come from the filename prefix and the matching `# Phase 07:`.
    assert [task.phase for task in tasks] == [roadmap_example.phase] * 3
    assert [task.phase_title for task in tasks] == ["Example phase"] * 3
    assert [task.epic_title for task in tasks] == [
        "Roadmap contracts",
        "Roadmap contracts",
        "Frozen GitHub contracts",
    ]
    assert [task.file for task in tasks] == [roadmap_example.name] * 3
    assert [task.branch for task in tasks] == ["07-E5.1", "07-E5.2", "07-E6.1"]
    assert tasks[0].branch == "07-E5.1"


def test_find_filter_next(tmp_path: Path, roadmap_example: RoadmapExample) -> None:
    tasks = parse_file(roadmap_example.write(tmp_path), roadmap_example.phase)

    assert find_task(tasks, roadmap_example.phase, "E5", "E5.2") is tasks[1]
    assert find_task(tasks, "99", "E5", "E5.2") is None
    assert [task.task for task in filter_tasks(tasks, todo=True)] == ["E5.2", "E6.1"]
    assert [task.task for task in filter_tasks(tasks, epic="E5")] == ["E5.1", "E5.2"]
    assert [task.task for task in filter_tasks(tasks, phase=roadmap_example.phase)] == [
        "E5.1",
        "E5.2",
        "E6.1",
    ]
    assert next_todo(tasks).task == "E5.2"
    assert next_todo(tasks, phase="99") is None


# --------------------------------------------------------------------------- #
# The drift proof: the fields above come from the doc's bytes, not a cached copy
# --------------------------------------------------------------------------- #


#: The first task entry's id line: `- [x] **E5.1. Title**`. Mutating the *entry shape*
#: rather than a fixed sentence keeps these edits valid when §9's prose changes.
_ENTRY_ID_RE = re.compile(r"^(\s*-\s*\[[ xX]\]\s*\*\*[A-Za-z0-9.]+)\.", re.MULTILINE)


def _drop_the_first_entrys_separator(example: str) -> str:
    """`**E5.1. Title**` → `**E5.1 Title**` — the §5 collapsed-id trap."""
    return _ENTRY_ID_RE.sub(r"\1", example, count=1)


def _rename_the_last_done_when(example: str) -> str:
    """`Done when:` → `Checked when:` on the last entry, so `DONE_RE` stops matching (§6)."""
    head, separator, tail = example.rpartition("Done when")
    assert separator, "the example carries no `Done when` label to rename"
    return head + "Checked when" + tail


def _drop_the_first_design_citation(example: str) -> str:
    """Remove the first `Design N` token, leaving only the doc-ref channel (§8.1/§8.2)."""
    return re.sub(r"Design\s+\d+(?:\.\d+)?,?\s*", "", example, count=1)


def _parse_doctored_example(
    tmp_path: Path, roadmap_example: RoadmapExample, edit: Callable[[str], str]
) -> list[RoadmapTask]:
    """Parse the doc's §9 example after applying ``edit`` to the doc's *current* bytes.

    The example is located in the doc and replaced in place, so an edit cannot go stale
    when the surrounding prose changes; the real doc is never written to (it lives outside
    ``tmp_path``). The edited copy is what the shared helper extracts from, which is how
    each test below proves the parsed fields are a function of the doc's bytes rather than
    a module-level string.
    """
    doc_text = roadmap_example.doc.read_text(encoding="utf-8")
    example = roadmap_example.text()  # also exercises the "exactly one example" guard
    assert example in doc_text, "§9's example is no longer a contiguous block of the doc"

    doctored_text = doc_text.replace(example, edit(example), 1)
    assert doctored_text != doc_text, "the drift edit changed nothing"
    doctored = tmp_path / "doctored-roadmap-format.md"
    doctored.write_text(doctored_text, encoding="utf-8")
    return parse_file(roadmap_example.write(tmp_path, doc=doctored), roadmap_example.phase)


def test_a_collapsed_id_in_the_doc_example_changes_the_parsed_id(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    """Drop the period after the first id (§5's trap) and the asserted id no longer holds."""
    tasks = _parse_doctored_example(
        tmp_path, roadmap_example, _drop_the_first_entrys_separator
    )

    assert [task.task for task in tasks] != ["E5.1", "E5.2", "E6.1"]
    assert tasks[0].task == "E5"  # collapsed to the epic-level id...
    assert tasks[0].title.startswith("1 ")  # ...with a stray leading digit
    assert "." not in tasks[0].task


def test_a_broken_done_when_line_in_the_doc_example_changes_done_when(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    """Rename the last `Done when:` and `DONE_RE` stops matching (§6): the field empties."""
    tasks = _parse_doctored_example(tmp_path, roadmap_example, _rename_the_last_done_when)

    assert [task.task for task in tasks] == ["E5.1", "E5.2", "E6.1"]  # ids unaffected
    assert tasks[2].done_when == ""  # only the renamed entry lost its check
    assert all(task.done_when for task in tasks[:2])


def test_a_dropped_citation_in_the_doc_example_changes_citations(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    """Remove the first `Design N` token and §8.1's channel finds nothing for E5.1."""
    tasks = _parse_doctored_example(
        tmp_path, roadmap_example, _drop_the_first_design_citation
    )

    assert tasks[0].citations == []
    assert tasks[0].citations != ["Design 11"]


# --------------------------------------------------------------------------- #
# Directory selection mechanics (glob first, then _FILENAME_RE) — inline bodies
# --------------------------------------------------------------------------- #

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


def test_load_tasks_reads_a_directory(tmp_path: Path, roadmap_example: RoadmapExample) -> None:
    roadmap_example.write(tmp_path)
    _write(tmp_path, "99 - Other Phase.md")
    tasks = load_tasks(tmp_path, DEFAULT_GLOB)
    assert [task.task for task in tasks] == ["E5.1", "E5.2", "E6.1", "Z1"]


def test_load_tasks_glob_pre_selects_but_the_filename_regex_is_the_phase_authority(
    tmp_path: Path,
    roadmap_example: RoadmapExample,
) -> None:
    """One vector per selection rule: glob first, then ``_FILENAME_RE``, phase from prefix.

    ``0 - x.md`` and ``0123 - x.md`` are the trap: both match the default glob, both are
    rejected by ``_FILENAME_RE`` (exactly two digits), so neither may be parsed — and a
    glob alone must never be treated as the phase authority.
    """
    roadmap_example.write(tmp_path)
    _write(tmp_path, "0 - One digit.md")
    _write(tmp_path, "0123 - Four digits.md")
    _write(tmp_path, "notes.md", "# Notes\n")

    # Hand-calculated: the glob admits three of the four, the filename pattern two of those.
    assert [fnmatch(name, DEFAULT_GLOB) for name in (
        roadmap_example.name,
        "0 - One digit.md",
        "0123 - Four digits.md",
        "notes.md",
    )] == [True, True, True, False]
    assert _FILENAME_RE.match("0 - One digit.md") is None
    assert _FILENAME_RE.match("0123 - Four digits.md") is None

    tasks = load_tasks(tmp_path, DEFAULT_GLOB)

    assert [task.file for task in tasks] == [roadmap_example.name] * 3
    assert {task.phase for task in tasks} == {roadmap_example.phase}
    assert [task.task for task in tasks] == ["E5.1", "E5.2", "E6.1"]


def test_load_tasks_glob_drives_selection(tmp_path: Path) -> None:
    """A non-default glob really selects the files: it is not decorative.

    Both files are ``_FILENAME_RE``-valid, so only the glob can explain the difference.
    (A glob such as ``roadmap-*.md`` cannot be used as the vector: no name it selects
    starts with the two-digit prefix ``_FILENAME_RE`` requires, so it would select nothing
    and prove nothing about selection.)
    """
    _write(tmp_path, "04 - Roadmap.md")
    _write(tmp_path, "05 - Other.md")

    assert [task.phase for task in load_tasks(tmp_path, "*- Roadmap.md")] == ["04"]
    assert [task.phase for task in load_tasks(tmp_path, DEFAULT_GLOB)] == ["04", "05"]


def test_load_tasks_missing_directory_is_empty_not_an_error(tmp_path: Path) -> None:
    """Fail closed on the read, not by raising: the read-path check is the caller's (E3.7)."""
    assert load_tasks(tmp_path / "absent", DEFAULT_GLOB) == []


def test_load_tasks_is_pure_and_repeatable(
    tmp_path: Path, roadmap_example: RoadmapExample
) -> None:
    """No file is created, changed or removed, and two calls agree entry for entry."""
    roadmap_example.write(tmp_path)
    _write(tmp_path, "07 - Ignored.md")  # same phase, its own tasks
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    first = load_tasks(tmp_path, DEFAULT_GLOB)
    second = load_tasks(tmp_path, DEFAULT_GLOB)

    assert first == second
    assert first is not second
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
    assert sorted(before) == sorted([roadmap_example.name, "07 - Ignored.md"])


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
