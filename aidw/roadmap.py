"""Roadmap parsing (design §11).

Parses the checkbox task index in the configured roadmap directory:

- ``# Phase NN: Title`` — phase title (the phase id comes from the filename)
- ``## Epic X: Title`` — epic title
- ``- [x] **A1. Title** <details>`` — a task, with an indented ``Done when:`` line

The phase id is taken from the filename prefix (a two-digit phase id, optionally ``.``
plus digits), because the ``/task-prompt`` workflow expects the zero-padded form that
matches the task-prompt file name and the branch name.

Which directory is read and which filenames are candidates are the caller's inputs
(``paths.roadmap_dir``/``paths.roadmap_glob``, D15/D17): ``load_tasks`` takes the glob
from its caller, so this module carries neither a product-specific directory nor a
product-specific pattern. There is no per-repo dialect (D15) — the patterns below are the
one format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

TASK_RE = re.compile(r"^\s*-\s*\[([ xX])\]\s*\*\*([A-Za-z0-9.]+)\.\s*(.*?)\*\*(.*)$")
EPIC_RE = re.compile(r"^##\s+Epic\s+([A-Za-z0-9]+):\s*(.*)$")
PHASE_RE = re.compile(r"^#\s+Phase\s+([0-9.]+):?\s*(.*)$")
DONE_RE = re.compile(r"^\s*(?:-\s*)?\**Done when:?\**\s*(.*)$", re.IGNORECASE)
CITATION_RE = re.compile(r"Design\s+\d+(?:\.\d+)?")
_FILENAME_RE = re.compile(r"^(\d{2}(?:\.\d+)?)\s*-\s*(.*)\.md$")


@dataclass
class RoadmapTask:
    phase: str
    epic: str
    task: str
    title: str
    done: bool
    file: str
    line: int
    done_when: str = ""
    citations: list[str] = field(default_factory=list)
    epic_title: str | None = None
    phase_title: str | None = None

    @property
    def key(self) -> str:
        return f"{self.phase}-{self.task}"

    @property
    def branch(self) -> str:
        return f"{self.phase}-{self.task}"


def derive_epic(task_id: str) -> str:
    """Derive the epic id from a task id.

    ``E2.9`` → ``E2``, ``E1.1`` → ``E1``, ``A1`` → ``A``, ``E2`` → ``E``.
    """
    if "." in task_id:
        return task_id.split(".", 1)[0]
    match = re.match(r"[A-Za-z]+", task_id)
    return match.group(0) if match else task_id


def parse_file(path: Path, phase: str) -> list[RoadmapTask]:
    lines = path.read_text(encoding="utf-8").splitlines()
    tasks: list[RoadmapTask] = []
    phase_title: str | None = None
    epic_title: str | None = None
    epic_id: str | None = None

    for index, line in enumerate(lines):
        phase_match = PHASE_RE.match(line)
        if phase_match and phase_match.group(1) in (phase, phase.lstrip("0")):
            phase_title = phase_match.group(2).strip()

        epic_match = EPIC_RE.match(line)
        if epic_match:
            epic_id = epic_match.group(1)
            epic_title = epic_match.group(2).strip()

        task_match = TASK_RE.match(line)
        if not task_match:
            continue

        done = task_match.group(1).lower() == "x"
        task_id = task_match.group(2)
        title = task_match.group(3).strip()
        detail = task_match.group(4)
        epic = derive_epic(task_id)

        done_when = ""
        block_citations = set(CITATION_RE.findall(detail))
        for subsequent in lines[index + 1 :]:
            if TASK_RE.match(subsequent) or subsequent.startswith("##") or subsequent.startswith("#"):
                break
            done_match = DONE_RE.match(subsequent)
            if done_match and not done_when:
                done_when = done_match.group(1).strip()
                block_citations.update(CITATION_RE.findall(done_when))
            elif done_when and not subsequent.strip():
                break

        tasks.append(
            RoadmapTask(
                phase=phase,
                epic=epic,
                task=task_id,
                title=title,
                done=done,
                file=path.name,
                line=index + 1,
                done_when=done_when,
                citations=sorted(block_citations),
                epic_title=epic_title,
                phase_title=phase_title,
            )
        )

    return tasks


def load_tasks(tasks_dir: Path, glob: str) -> list[RoadmapTask]:
    """Parse every roadmap file under ``tasks_dir`` that ``glob`` selects.

    ``glob`` is the caller's configured filename pattern (``paths.roadmap_glob``); it only
    pre-selects candidates. ``_FILENAME_RE`` stays the phase authority: a name the glob
    admits but the pattern rejects (``0 - x.md``, ``0123 - x.md``) is still dropped, and
    the phase always comes from the filename prefix, never from the ``# Phase`` heading.
    A missing ``tasks_dir`` is empty, not an error (the read-path check is the caller's).
    """
    if not tasks_dir.is_dir():
        return []
    tasks: list[RoadmapTask] = []
    for path in sorted(tasks_dir.glob(glob)):
        match = _FILENAME_RE.match(path.name)
        if not match:
            continue
        tasks.extend(parse_file(path, match.group(1)))
    return tasks


def find_task(tasks: list[RoadmapTask], phase: str, epic: str, task: str) -> RoadmapTask | None:
    for entry in tasks:
        if entry.phase == phase and entry.task == task:
            return entry
    for entry in tasks:
        if entry.phase == phase and entry.epic == epic and entry.task == task:
            return entry
    return None


def filter_tasks(
    tasks: list[RoadmapTask],
    *,
    phase: str | None = None,
    epic: str | None = None,
    todo: bool = False,
) -> list[RoadmapTask]:
    result = []
    for entry in tasks:
        if phase and entry.phase != phase:
            continue
        if epic and entry.epic != epic:
            continue
        if todo and entry.done:
            continue
        result.append(entry)
    return result


def next_todo(tasks: list[RoadmapTask], phase: str | None = None) -> RoadmapTask | None:
    for entry in filter_tasks(tasks, phase=phase, todo=True):
        return entry
    return None
