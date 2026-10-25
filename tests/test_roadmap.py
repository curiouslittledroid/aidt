"""Tests for roadmap parsing."""

from __future__ import annotations

from pathlib import Path

from aidw.roadmap import (
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


def test_load_tasks_reads_a_directory(tmp_path: Path) -> None:
    (tmp_path / "07 - Test Phase.md").write_text(FIXTURE, encoding="utf-8")
    (tmp_path / "99 - Other Phase.md").write_text(
        "# Phase 99: Other Phase\n\n## Epic Z: Zed\n\n- [ ] **Z1. Zed task** text.\n",
        encoding="utf-8",
    )
    tasks = load_tasks(tmp_path)
    assert [t.task for t in tasks] == ["A1", "A2", "B1", "Z1"]
