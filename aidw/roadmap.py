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

It also *validates* that parsed list (design §11, roadmap-format.md §10): ``validate_tasks``
reports the three malformations the format defines — a missing ``Done when``, a duplicate
``(phase, task)`` id, and an entry before any ``## Epic`` heading — with the entry's file,
1-based line and rule. Validation is a separate, pure pass: the parser itself still never
reports (roadmap-format.md §10), so ``parse_file``/``load_tasks`` and their callers are
unchanged.

Since H3.1 the module also owns the **one-checkbox tick** the ``I7 update-roadmap`` stage
performs (design §8.2): :func:`tick_entry` resolves the stage's single target through the
parsed list (a count, not ``find_task``'s first match, so a duplicate refuses instead of
ticking the wrong entry), :func:`entry_path` names that entry's own file, and
:func:`verify_checkbox_flip` is the workflow-owned postcondition — the agent's exit 0 is
not evidence the edit happened (design §10, the O1 precedent). All three are pure, so the
byte-exact rule lives here rather than inline in ``workflows/implement.py``.
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


#: The three rule tokens (roadmap-format.md §10). They mirror the roadmap entry's wording.
RULE_MISSING_DONE_WHEN = "missing Done when"
RULE_DUPLICATE_ID = "duplicate id"
RULE_OUTSIDE_EPIC = "entry outside an epic"


@dataclass(frozen=True)
class RoadmapIssue:
    """One format problem, addressed by the entry's own file and 1-based line."""

    file: str
    line: int
    rule: str
    message: str


def validate_tasks(tasks: list[RoadmapTask]) -> list[RoadmapIssue]:
    """Report every format malformation in a parsed roadmap (roadmap-format.md §10).

    ``tasks`` is ``load_tasks``' output, so ``file`` is already a basename and ``line`` is
    already 1-based: both are used as-is. Pure by construction — the list is read, never
    mutated, no file is re-read, and the result is deterministic (one entry's issues in a
    fixed order, entries in input order), so repeat calls compare equal.

    The three rules are exactly the ones the format enumerates:

    - ``missing Done when`` — ``done_when == ""`` (§6/§11).
    - ``duplicate id`` — a repeated ``(phase, task)``; the later entry is the issue and its
      message names the earlier ``file:line``. Keying on ``(phase, task)`` matters: the
      branch is ``{phase}-{task}`` and ``find_task`` matches phase+task, so the same task id
      in another phase file is a different task, not a duplicate.
    - ``entry outside an epic`` — ``epic_title is None`` (§4). Deliberately not ``epic``: it
      is derived from the id by ``derive_epic`` and is never ``None``.

    Validation is *not* wired into ``parse_file``/``load_tasks``; §10 keeps the parser
    silent. The collapsed-id trap is likewise not a rule here (E0.7 owns that guard).
    """
    issues: list[RoadmapIssue] = []
    seen: dict[tuple[str, str], RoadmapTask] = {}
    for entry in tasks:
        if entry.done_when == "":
            issues.append(
                RoadmapIssue(
                    file=entry.file,
                    line=entry.line,
                    rule=RULE_MISSING_DONE_WHEN,
                    message=(
                        f"task {entry.phase}-{entry.task} has no 'Done when' line "
                        "(roadmap-format.md §6)"
                    ),
                )
            )

        key = (entry.phase, entry.task)
        earlier = seen.get(key)
        if earlier is not None:
            issues.append(
                RoadmapIssue(
                    file=entry.file,
                    line=entry.line,
                    rule=RULE_DUPLICATE_ID,
                    message=(
                        f"task {entry.phase}-{entry.task} is already defined at "
                        f"{earlier.file}:{earlier.line}"
                    ),
                )
            )
        else:
            seen[key] = entry

        if entry.epic_title is None:
            issues.append(
                RoadmapIssue(
                    file=entry.file,
                    line=entry.line,
                    rule=RULE_OUTSIDE_EPIC,
                    message=(
                        f"task {entry.phase}-{entry.task} appears before any '## Epic' "
                        "heading (roadmap-format.md §4)"
                    ),
                )
            )
    return issues


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


# --------------------------------------------------------------------------- #
# The one-checkbox tick (H3.1, design §8.2)
# --------------------------------------------------------------------------- #

#: The two successful tick outcomes, recorded as ``StageRecord.artifacts["tick"]`` so the
#: run is observable from ``state.json``/``run.log`` without reading a transcript (H3.1
#: req 7). ``flipped`` is the real edit; ``already`` is the pinned no-op for an entry that
#: was already ``[x]`` — a **success**, never ``skipped`` (H3.2 reserves that status for a
#: tick withheld behind red gates).
TICK_FLIPPED = "flipped"
TICK_ALREADY = "already"


class RoadmapTickError(ValueError):
    """The tick cannot be resolved, or its postcondition does not hold (H3.1).

    Every path raises rather than returning a partial answer: an unresolvable entry would
    tick the wrong line, and a postcondition that cannot be checked must fail the stage
    (design §10), never be reported as success.
    """


def tick_entry(
    tasks: list[RoadmapTask], *, phase: str, task: str
) -> RoadmapTask:
    """The **one** entry matching ``(phase, task)``, or :class:`RoadmapTickError`.

    Deliberately a count, not :func:`find_task`: ``find_task`` returns the first match, so
    a duplicated ``(phase, task)`` would silently tick one of two entries (H3.1 req 5).
    Zero matches and duplicates are both refusals, because a tick is a completion claim
    and a wrong or ambiguous flip advances ``aidw tasks --next`` past open work.
    """
    matches = [
        entry for entry in tasks if entry.phase == phase and entry.task == task
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise RoadmapTickError(
            f"no roadmap entry matches {phase}-{task}; exactly one is required"
        )
    locations = ", ".join(f"{entry.file}:{entry.line}" for entry in matches)
    raise RoadmapTickError(
        f"{len(matches)} roadmap entries match {phase}-{task} ({locations}); "
        "exactly one is required"
    )


def entry_path(root: Path, entry: RoadmapTask) -> Path:
    """The absolute path of the roadmap file ``entry`` was parsed from.

    ``entry.file`` is a basename (``parse_file`` records ``path.name``) and ``load_tasks``
    only globs the caller's directory, so joining it to that directory reconstructs the one
    file the stage may edit — the file the workflow hands the prompt as ``{roadmap_file}``
    and the file whose bytes the postcondition re-reads (H3.1 req 6/req 7).
    """
    return (Path(root) / entry.file).resolve()


def verify_checkbox_flip(
    before: str, after: str, *, checkbox_id: str
) -> str:
    """The I7 postcondition: exactly one checkbox flipped, every other byte unchanged.

    ``before`` is the roadmap file's text read before the stage ran, ``after`` the text
    re-read from the **same** file afterwards; ``checkbox_id`` is the entry's own task id
    without the phase prefix (``H3.1``, not the branch's ``03-H3.1``). Returns
    :data:`TICK_FLIPPED` for the one legal edit or :data:`TICK_ALREADY` when the entry was
    already ``[x]`` and the file is byte-identical, and raises :class:`RoadmapTickError` for
    everything else.

    The comparison is the whole line list, never a "this line now starts with ``[x]``"
    check: that weaker shape would pass a reformat, an edited neighbour or a trailing
    whitespace change, and a tick is a completion claim on a committed file (H3.1 traps).
    Line endings are kept verbatim by ``splitlines(keepends=True)``, so a reflow fails.

    Pure: no I/O, and neither input is mutated.
    """
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    targets = [
        (index, match)
        for index, line in enumerate(before_lines)
        if (match := TASK_RE.match(line)) is not None
        and match.group(2) == checkbox_id
    ]
    if len(targets) != 1:
        # The entry disappeared or was duplicated between resolution and the stage; both
        # make the tick unverifiable, so the stage fails rather than claiming either.
        raise RoadmapTickError(
            f"expected exactly one `{checkbox_id}` entry before the tick, found "
            f"{len(targets)}"
        )
    index, match = targets[0]
    line = before_lines[index]
    if match.group(1) in ("x", "X"):
        if after_lines != before_lines:
            raise RoadmapTickError(
                f"`{checkbox_id}` was already `[x]`, so the file had to stay unchanged; "
                f"line {index + 1} or a neighbour was edited"
            )
        return TICK_ALREADY

    expected = list(before_lines)
    expected[index] = (
        line[: match.start(1)] + "x" + line[match.end(1) :]
    )
    if after_lines != expected:
        raise RoadmapTickError(
            f"the `{checkbox_id}` tick changed more than the `- [ ]` -> `- [x]` checkbox "
            f"on line {index + 1}; every other byte must be unchanged"
        )
    return TICK_FLIPPED


# ── The recorded verdict on the task's Done-when (design §8.2) ──────────────────────
#
# I7 flips a completion claim. H3.2 gates that flip on the run's own green evidence; this
# gates it on the *recorded* verdict too, because a run whose gates all passed can still
# have written "the task's Done-when is not met" into its build results — which is exactly
# what happened to PR #282: `04-A1.1` was ticked over a recorded contract-suite failure, and
# the only thing that caught it was a check the target repo had grown itself. The stage
# also has no way to express the repair: its postcondition allows one checkbox and nothing
# else, so an agent told to tick a contradicted entry can only fail or go around it.

#: A line naming the task's Done-when — the record stage's own vocabulary.
DONE_WHEN_MENTION_RE = re.compile(r"done[- ]when", re.IGNORECASE)
#: …asserting that it is unmet, with the negation adjacent to ``met`` — at most four words
#: between them (``not met``, ``not yet met``, ``has not been met``, ``is **not** met``).
#: Deliberately narrow in both directions: a gate row that merely *quotes* the Done-when
#: command concludes nothing, and a distant ``not`` (``… is met; the earlier attempt was not
#: reviewed …``) must not manufacture a conclusion either.
DONE_WHEN_UNMET_RE = re.compile(
    r"\bnot\b(?:\s+[^\s]+){0,4}\s+met\b", re.IGNORECASE
)

#: The build-results document the record stage writes per task (``I5``).
BUILD_RESULTS_NAME = "build-results.md"


@dataclass(frozen=True)
class UnmetConclusion:
    """A recorded build-results conclusion that the task's Done-when is unmet.

    ``results_file`` is repo-relative so a skip reason names a path an operator can open;
    ``line`` is 1-based and ``text`` the offending line, stripped.
    """

    results_file: str
    line: int
    text: str


def _without_emphasis(line: str) -> str:
    """``line`` with markdown emphasis and code-span marks removed before matching.

    The record stage bolds its verdicts (``is **not** met``), and ``**`` between the
    negation and ``met`` is markup, not a word: matching the raw line would read the one
    sentence this rule exists for as no conclusion at all.
    """
    return line.replace("*", "").replace("_", "").replace("`", "")


def find_unmet_conclusion(text: str) -> tuple[int, str] | None:
    """Pure: the first line that both names the Done-when and asserts it is unmet.

    Returns ``(1-based line, stripped text)`` or ``None``. One line is enough: the document
    is a claim about one task, so any such line contradicts a tick, and reporting the first
    keeps the skip reason short.
    """
    for index, line in enumerate(text.splitlines()):
        plain = _without_emphasis(line)
        if DONE_WHEN_MENTION_RE.search(plain) and DONE_WHEN_UNMET_RE.search(plain):
            return index + 1, line.strip()
    return None


def task_results_candidates(phase: str, task: str) -> tuple[str, ...]:
    """The ``<phase>-<task>`` directory names a build-results document may live under.

    Padded first (``04-A1.1``), then the unpadded form older result trees use
    (``4-A1.1``) — the same pair the layout accepts, so a tick is judged by the document the
    run actually wrote rather than by one naming convention.
    """
    padded = f"{phase}-{task}"
    unpadded = re.sub(r"(^|\.)0+(\d)", r"\1\2", padded)
    return (padded,) if unpadded == padded else (padded, unpadded)


def recorded_unmet_conclusion(
    root: Path, *, implementation_results_dir: str, phase: str, task: str
) -> UnmetConclusion | None:
    """The task's **recorded** verdict, when it contradicts a tick (design §8.2).

    ``implementation_results_dir`` is the resolved ``paths.implementation_results_dir``
    value — target-relative by default, absolute allowed — so this module still carries no
    product-specific directory (D15). A **missing** document is not a contradiction: a repo
    without build results, or a task whose recording stage legitimately wrote none, keeps
    the H3.2 behaviour unchanged. Only a document that exists and concludes unmet withholds.

    Read-only: one file read, no mutation, and an unreadable file is treated as absent
    rather than as a reason to fail — the tick's own postcondition is still the gate on
    the edit itself.
    """
    base = Path(implementation_results_dir)
    if not base.is_absolute():
        base = Path(root) / base
    for dirname in task_results_candidates(phase, task):
        path = base / dirname / BUILD_RESULTS_NAME
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        found = find_unmet_conclusion(text)
        if found is None:
            continue
        line, text_of_line = found
        try:
            shown = path.resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:  # results dir outside the tree: name what we read
            shown = path.as_posix()
        return UnmetConclusion(shown, line, text_of_line)
    return None


def unmet_conclusion_reason(conclusion: UnmetConclusion) -> str:
    """The one-line skip reason a withheld tick carries.

    Names the document and line first, because that is the thing to fix — the agents read
    ``run.log``, and "the recorded verdict contradicts the tick" without a pointer is not
    actionable.
    """
    return (
        f"the recorded build results conclude the task's Done-when is unmet "
        f"({conclusion.results_file}:{conclusion.line})"
    )
