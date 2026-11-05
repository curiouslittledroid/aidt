"""Contract tests for roadmap format validation (E5.3, roadmap-format.md §6/§10/§11).

``validate_tasks`` is the reporting pass over ``load_tasks``' output. Every rule gets one
hand-calculated vector (basename + 1-based line + rule token), the two traps get their own
negative vector (``epic`` is never ``None``; the same task id in another phase is legal),
and purity — no I/O, no mutation, repeatable — is asserted directly. A seeded property run
pins the whole report against an independent reference implementation.
"""

from __future__ import annotations

import dataclasses
import random
from pathlib import Path

import pytest

from aidw.roadmap import (
    RULE_DUPLICATE_ID,
    RULE_MISSING_DONE_WHEN,
    RULE_OUTSIDE_EPIC,
    RoadmapTask,
    load_tasks,
    parse_file,
    validate_tasks,
)

#: The toolkit's default ``paths.roadmap_glob`` (``TOOLKIT_DEFAULTS.paths``, D17). Passed
#: explicitly: ``load_tasks`` carries no pattern of its own (E5.2).
DEFAULT_GLOB = "[0-9]* - *.md"

CLEAN_FIXTURE = """# Phase 07: Test Phase

## Epic E5: Roadmap contracts

- [x] **E5.1. First task** per Design 11.
  - Done when: first is done.
- [ ] **E5.2. Second task** text.
  Done when: second is done.
"""

# Line 8 is the entry: 1 heading, 2 blank, 3 epic, 4 blank, 5 E5.1, 6 Done when,
# 7 blank, 8 E5.2, 9 Notes.
MISSING_DONE_WHEN_FIXTURE = """# Phase 07: Test Phase

## Epic E5: Contracts

- [ ] **E5.1. Has a check** text.
  - Done when: checked.

- [ ] **E5.2. Missing check** text.
  - Notes: no acceptance line here.
"""

# Line 3 is the entry before the first `## Epic`; line 8 is the clean one under it.
OUTSIDE_EPIC_FIXTURE = """# Phase 07: Test Phase

- [ ] **E5.1. Before the heading** text.
  - Done when: before is done.

## Epic E5: Contracts

- [ ] **E5.2. Under the heading** text.
  - Done when: under is done.
"""

# Both entries are inside the epic and have a Done when: only the repetition is wrong.
# Lines 5 and 8 are the two `E5.1` entries.
DUPLICATE_ID_FIXTURE = """# Phase 07: Test Phase

## Epic E5: Contracts

- [ ] **E5.1. First definition** text.
  - Done when: first is done.

- [ ] **E5.1. Second definition** text.
  - Done when: second is done.
"""

OTHER_PHASE_FIXTURE = """# Phase 08: Other Phase

## Epic E5: Contracts

- [ ] **E5.1. Same id, other phase** text.
  - Done when: other phase is done.
"""


def _parse(tmp_path: Path, name: str, body: str) -> list[RoadmapTask]:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return parse_file(path, name[:2])


def test_clean_roadmap_has_no_issues(tmp_path: Path) -> None:
    """The canonical shape — epic heading, entry, first-line Done when — is clean."""
    tasks = _parse(tmp_path, "07 - Test Phase.md", CLEAN_FIXTURE)

    assert validate_tasks(tasks) == []


def test_missing_done_when_reports_the_entry_file_and_line(tmp_path: Path) -> None:
    """Hand-calculated vector: the only malformation is ``E5.2`` at ``07 - …:8``."""
    tasks = _parse(tmp_path, "07 - Test Phase.md", MISSING_DONE_WHEN_FIXTURE)
    assert [task.task for task in tasks] == ["E5.1", "E5.2"]
    assert tasks[1].done_when == ""

    issues = validate_tasks(tasks)

    assert len(issues) == 1
    issue = issues[0]
    assert (issue.file, issue.line, issue.rule) == (
        "07 - Test Phase.md",
        8,
        RULE_MISSING_DONE_WHEN,
    )
    assert RULE_MISSING_DONE_WHEN == "missing Done when"
    # The entry's own 1-based line, not an index: the file's 8th line is the entry.
    assert tasks[1].line == 8


def test_entry_before_any_epic_heading_is_reported_at_its_line(tmp_path: Path) -> None:
    """``epic_title is None`` is the signal — never ``epic``, which ``derive_epic`` fills."""
    tasks = _parse(tmp_path, "07 - Test Phase.md", OUTSIDE_EPIC_FIXTURE)
    assert [task.task for task in tasks] == ["E5.1", "E5.2"]
    assert tasks[0].epic_title is None
    assert tasks[0].epic == "E5"  # never None — keying on `epic` would flag nothing
    assert tasks[1].epic_title == "Contracts"

    issues = validate_tasks(tasks)

    assert [(issue.file, issue.line, issue.rule) for issue in issues] == [
        ("07 - Test Phase.md", 3, RULE_OUTSIDE_EPIC),
    ]
    assert RULE_OUTSIDE_EPIC == "entry outside an epic"
    # The entry under the epic produces nothing, on its own or as a second issue.
    assert tasks[1].line == 8
    assert all(issue.line != 8 for issue in issues)


def test_duplicate_id_reports_the_later_entry_and_names_the_earlier(
    tmp_path: Path,
) -> None:
    """Same ``(phase, task)`` twice: the later line is the issue, the earlier is named."""
    tasks = _parse(tmp_path, "07 - Test Phase.md", DUPLICATE_ID_FIXTURE)
    assert [task.line for task in tasks] == [5, 8]

    issues = validate_tasks(tasks)

    assert len(issues) == 1
    issue = issues[0]
    assert (issue.file, issue.line, issue.rule) == (
        "07 - Test Phase.md",
        8,
        RULE_DUPLICATE_ID,
    )
    assert RULE_DUPLICATE_ID == "duplicate id"
    assert "07 - Test Phase.md:5" in issue.message


def test_same_task_id_in_another_phase_is_not_a_duplicate(tmp_path: Path) -> None:
    """``00-E5.3`` and ``01-E5.3`` are different branches; keying on task alone is wrong."""
    (tmp_path / "07 - Test Phase.md").write_text(CLEAN_FIXTURE, encoding="utf-8")
    (tmp_path / "08 - Other Phase.md").write_text(OTHER_PHASE_FIXTURE, encoding="utf-8")

    tasks = load_tasks(tmp_path, DEFAULT_GLOB)

    assert [(task.phase, task.task) for task in tasks] == [
        ("07", "E5.1"),
        ("07", "E5.2"),
        ("08", "E5.1"),
    ]
    assert validate_tasks(tasks) == []


def test_every_issue_is_reported_not_just_the_first(tmp_path: Path) -> None:
    """One fixture per rule in one list: no early return, all three surface."""
    tasks = _parse(tmp_path, "07 - Test Phase.md", OUTSIDE_EPIC_FIXTURE)
    tasks.extend(_parse(tmp_path, "08 - Other Phase.md", MISSING_DONE_WHEN_FIXTURE))
    tasks.extend(_parse(tmp_path, "09 - Dup Phase.md", DUPLICATE_ID_FIXTURE))

    issues = validate_tasks(tasks)

    assert [issue.rule for issue in issues] == [
        RULE_OUTSIDE_EPIC,
        RULE_MISSING_DONE_WHEN,
        RULE_DUPLICATE_ID,
    ]


def test_validate_tasks_is_pure(tmp_path: Path) -> None:
    """No I/O, no mutation of the input, equal results on repeat calls."""
    tasks = _parse(tmp_path, "07 - Test Phase.md", DUPLICATE_ID_FIXTURE)
    tasks.extend(_parse(tmp_path, "09 - Dup Phase.md", MISSING_DONE_WHEN_FIXTURE))
    before = [dataclasses.asdict(task) for task in tasks]

    assert validate_tasks(tasks) == validate_tasks(tasks)
    assert [dataclasses.asdict(task) for task in tasks] == before
    assert len(tasks) == 4

    # A validator over an in-memory list must not touch the filesystem at all.
    def _no_io(*_args, **_kwargs):
        raise AssertionError("validate_tasks performed I/O")

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr("builtins.open", _no_io)
        patcher.setattr("pathlib.Path.read_text", _no_io)
        patcher.setattr("pathlib.Path.glob", _no_io)
        first = validate_tasks(tasks)

    assert first == validate_tasks(tasks)


def test_roadmap_issue_is_frozen(tmp_path: Path) -> None:
    """Issue records are immutable contract values, not mutable validation state."""
    tasks = _parse(tmp_path, "07 - Test Phase.md", MISSING_DONE_WHEN_FIXTURE)
    issue = validate_tasks(tasks)[0]

    with pytest.raises(dataclasses.FrozenInstanceError):
        issue.rule = "changed"  # type: ignore[misc]


def test_empty_list_is_clean_not_an_error() -> None:
    """An empty parse is empty, not malformed — the CLI's zero-entry guard stays the caller's."""
    assert validate_tasks([]) == []


#: Pinned seed and run count (AGENTS.md: pytest only, no hypothesis). The sample is the
#: generator and there is no shrinking, so the seed is part of the contract.
VALIDATE_PROPERTY_SEED = 5303
VALIDATE_PROPERTY_RUNS = 64

_PHASES = ("00", "07", "08")
_TASKS = ("E5.1", "E5.2", "E6.1")
_FILES = ("07 - Test Phase.md", "08 - Other Phase.md")


def _entry(rng: random.Random, line: int) -> RoadmapTask:
    return RoadmapTask(
        phase=rng.choice(_PHASES),
        epic="E5",
        task=rng.choice(_TASKS),
        title=f"Property task {line}",
        done=rng.random() < 0.5,
        file=rng.choice(_FILES),
        line=line,
        done_when=rng.choice(["", "the property holds."]),
        epic_title=rng.choice([None, "Contracts"]),
    )


def test_validate_tasks_seeded_property() -> None:
    """Seeded property run (seed/runs pinned above): the report is exactly the three rules.

    For every sampled list, ``validate_tasks`` reports one issue per violated rule per
    entry, in input order, with the entry's own file/line — computed here from an
    independent restatement of §6/§4 plus the ``(phase, task)`` duplicate key. The input is
    never mutated and the run is repeatable.
    """
    rng = random.Random(VALIDATE_PROPERTY_SEED)

    for case in range(VALIDATE_PROPERTY_RUNS):
        entries = [_entry(rng, line) for line in range(1, rng.randint(0, 7) + 1)]
        before = [dataclasses.asdict(entry) for entry in entries]

        expected: list[tuple[str, int, str]] = []
        seen: dict[tuple[str, str], RoadmapTask] = {}
        for entry in entries:
            if entry.done_when == "":
                expected.append((entry.file, entry.line, RULE_MISSING_DONE_WHEN))
            key = (entry.phase, entry.task)
            if key in seen:
                expected.append((entry.file, entry.line, RULE_DUPLICATE_ID))
            else:
                seen[key] = entry
            if entry.epic_title is None:
                expected.append((entry.file, entry.line, RULE_OUTSIDE_EPIC))

        issues = validate_tasks(entries)

        assert [(issue.file, issue.line, issue.rule) for issue in issues] == expected, case
        assert validate_tasks(entries) == issues, case
        assert [dataclasses.asdict(entry) for entry in entries] == before, case
