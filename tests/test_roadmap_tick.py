"""Contract and property tests for the roadmap tick (H3.1, design §8.2).

The tick is one checkbox in one file, and it is a **completion claim**: a wrong flip
advances ``aidw tasks --next`` past open work. Three pieces make it honest, and this module
is their executable specification:

* :func:`aidw.roadmap.tick_entry` resolves the stage's one target through a **count** of
  ``(phase, task)`` matches, so zero and duplicates refuse instead of ticking the first
  match ``find_task`` would return.
* :func:`aidw.roadmap.verify_checkbox_flip` is the byte-exact postcondition: exactly the
  target line may flip ``- [ ]`` -> ``- [x]``, every other byte must be identical, and an
  already-``[x]`` file is a successful no-op. The comparison is the whole line list, so a
  reformat, a neighbour edit or a trailing newline change fails.
* :func:`aidw.workflows.implement._settle_roadmap_tick` records the outcome observably —
  ``StageRecord.artifacts["tick"]`` as ``flipped``/``already`` plus one ``run.log`` line —
  and marks the stage ``failed`` when the postcondition does not hold. ``already`` stays
  ``succeeded``; ``skipped`` is H3.2's word for a tick withheld behind red gates.

No Pi model is involved (design §15): the pure helpers are called directly, and the
workflow's own settlement helper is driven with a real ``RunState``/``RunLogger`` in a
temporary run directory. The workflow-level exit codes and stage plan are pinned in
``tests/test_implement_workflow.py``.

``hypothesis`` is not a dependency (AGENTS.md "Tests": pytest only), so the sweep at the
bottom enumerates its input space deterministically with a pinned seed and run count.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable
from pathlib import Path

import pytest

from aidw import roadmap
from aidw.log import RunLogger
from aidw.paths import toolkit_root
from aidw.state import FAILED, SUCCEEDED, StageRecord, create_run, run_dir
from aidw.workflows import implement as implement_workflow

CHECKBOX_ID = "H3.1"

#: The hand-calculated three-entry fixture: the target sits between two neighbours, one of
#: which is already ticked, so a wrong-line flip is observable.
BEFORE = """\
# Phase 03: Stage resilience

## Epic H3: One roadmap tick, one owner

- [x] **H3.0. A finished prerequisite** <details>
  Done when: it shipped.
- [ ] **H3.1. Give the roadmap tick its own stage** <details>
  Done when: the box is ticked by its own stage.
- [ ] **H3.2. Tick only behind evidence** <details>
  Done when: the tick waits for green gates.
"""


def _flip(text: str, checkbox_id: str = CHECKBOX_ID) -> str:
    """Flip ``checkbox_id``'s checkbox only — the one legal edit, hand-calculated."""
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        match = roadmap.TASK_RE.match(line)
        if match and match.group(2) == checkbox_id:
            lines[index] = line[: match.start(1)] + "x" + line[match.end(1) :]
            return "".join(lines)
    raise AssertionError(f"fixture has no {checkbox_id} entry")


def _roadmap_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "docs" / "tasks"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write_roadmap(tmp_path: Path, text: str) -> Path:
    path = _roadmap_dir(tmp_path) / "03 - Stage resilience.md"
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# verify_checkbox_flip — the byte-exact postcondition
# --------------------------------------------------------------------------- #


def test_the_hand_calculated_flip_is_accepted() -> None:
    """Exactly the target line changes and every other byte is identical."""
    flipped = _flip(BEFORE)

    assert roadmap.verify_checkbox_flip(BEFORE, flipped, checkbox_id=CHECKBOX_ID) == (
        roadmap.TICK_FLIPPED
    )
    # The fixture's other entries are untouched: H3.0 stays `[x]`, H3.2 stays `[ ]`.
    assert "- [x] **H3.0." in flipped
    assert "- [ ] **H3.2." in flipped


def test_an_already_ticked_entry_is_a_no_op_success() -> None:
    """``[x]`` + a byte-identical file is ``already``, never an error."""
    flipped = _flip(BEFORE)

    assert roadmap.verify_checkbox_flip(flipped, flipped, checkbox_id=CHECKBOX_ID) == (
        roadmap.TICK_ALREADY
    )


def test_an_already_ticked_entry_that_changed_anything_fails() -> None:
    """``already`` means *unchanged*: an edit on a no-op claim is a failed postcondition."""
    flipped = _flip(BEFORE)
    edited = flipped.replace("H3.2. Tick only behind evidence", "H3.2. Renamed")

    with pytest.raises(roadmap.RoadmapTickError) as raised:
        roadmap.verify_checkbox_flip(flipped, edited, checkbox_id=CHECKBOX_ID)
    assert "already `[x]`" in str(raised.value)


def test_a_vanished_entry_fails() -> None:
    """The target line removed (no replacement) cannot be verified as a tick."""
    without = "".join(
        line
        for line in BEFORE.splitlines(keepends=True)
        if "**H3.1." not in line
    )

    with pytest.raises(roadmap.RoadmapTickError) as raised:
        roadmap.verify_checkbox_flip(BEFORE, without, checkbox_id=CHECKBOX_ID)
    # The target line is gone, so nothing can be verified as the flip it claims to be.
    assert "H3.1" in str(raised.value)


def test_a_duplicated_entry_fails() -> None:
    """Two ``H3.1`` entries before the tick make it ambiguous, so it fails closed."""
    duplicated = BEFORE + "- [ ] **H3.1. Duplicated** <details>\n"

    with pytest.raises(roadmap.RoadmapTickError) as raised:
        roadmap.verify_checkbox_flip(duplicated, _flip(duplicated), checkbox_id=CHECKBOX_ID)
    assert "found 2" in str(raised.value)


@pytest.mark.parametrize(
    "mutate",
    [
        # A neighbour edit: the classic "line now starts with [x]" check would pass this.
        lambda text: text.replace("Done when: it shipped.", "Done when: shipped."),
        # A reformat of the flipped target line outside the checkbox (whitespace).
        lambda text: text.replace("- [x] **H3.1.", "-  [x] **H3.1."),
        # An appended line.
        lambda text: text + "\n",
        # A swallowed trailing newline.
        lambda text: text.rstrip("\n"),
    ],
    ids=["neighbour-edit", "reformat", "appended-line", "missing-final-newline"],
)
def test_any_edit_other_than_the_one_checkbox_fails(
    mutate: Callable[[str], str]
) -> None:
    """The postcondition compares the whole file: one extra byte is a failed tick."""
    after = mutate(_flip(BEFORE))

    with pytest.raises(roadmap.RoadmapTickError) as raised:
        roadmap.verify_checkbox_flip(BEFORE, after, checkbox_id=CHECKBOX_ID)
    assert "changed more than the `- [ ]` -> `- [x]` checkbox" in str(raised.value)


def test_verification_fails_when_nothing_flipped() -> None:
    """A stage that exited 0 without editing must not pass: the claim is the edit."""
    with pytest.raises(roadmap.RoadmapTickError):
        roadmap.verify_checkbox_flip(BEFORE, BEFORE, checkbox_id=CHECKBOX_ID)


def test_verification_is_pure(monkeypatch: pytest.MonkeyPatch) -> None:
    """No I/O, and neither input is mutated (design §15)."""
    before = BEFORE
    after = _flip(BEFORE)
    before_repr, after_repr = repr(before), repr(after)

    def _explode(*args: object, **kwargs: object):
        raise AssertionError("verify_checkbox_flip must not touch a file")

    monkeypatch.setattr(builtins, "open", _explode)
    monkeypatch.setattr(Path, "read_text", _explode)
    monkeypatch.setattr(Path, "write_text", _explode)

    assert roadmap.verify_checkbox_flip(before, after, checkbox_id=CHECKBOX_ID) == (
        roadmap.TICK_FLIPPED
    )
    assert repr(before) == before_repr
    assert repr(after) == after_repr


# --------------------------------------------------------------------------- #
# tick_entry / entry_path — the one target (H3.1 req 5/req 6)
# --------------------------------------------------------------------------- #


def test_one_match_resolves_the_entry_and_its_own_file(tmp_path: Path) -> None:
    """One ``(phase, task)`` match → the entry, and its file's absolute path."""
    path = _write_roadmap(tmp_path, BEFORE)
    tasks = roadmap.load_tasks(_roadmap_dir(tmp_path), "[0-9]* - *.md")

    entry = roadmap.tick_entry(tasks, phase="03", task=CHECKBOX_ID)

    assert entry.task == CHECKBOX_ID  # `entry.task`, not the branch's `03-H3.1`
    assert roadmap.entry_path(_roadmap_dir(tmp_path), entry) == path.resolve()


def test_zero_matches_refuses(tmp_path: Path) -> None:
    _write_roadmap(tmp_path, BEFORE)
    tasks = roadmap.load_tasks(_roadmap_dir(tmp_path), "[0-9]* - *.md")

    with pytest.raises(roadmap.RoadmapTickError) as raised:
        roadmap.tick_entry(tasks, phase="03", task="H9.9")
    assert "no roadmap entry matches 03-H9.9" in str(raised.value)


def test_duplicates_refuse_and_name_both_locations(tmp_path: Path) -> None:
    """``find_task`` would return the first match; a tick must refuse instead."""
    _write_roadmap(
        tmp_path,
        BEFORE + "- [ ] **H3.1. Duplicated** <details>\n  Done when: never.\n",
    )
    tasks = roadmap.load_tasks(_roadmap_dir(tmp_path), "[0-9]* - *.md")

    with pytest.raises(roadmap.RoadmapTickError) as raised:
        roadmap.tick_entry(tasks, phase="03", task=CHECKBOX_ID)
    message = str(raised.value)
    assert "2 roadmap entries match 03-H3.1" in message
    assert "03 - Stage resilience.md:7" in message
    assert "03 - Stage resilience.md:11" in message


def test_a_same_task_id_in_another_phase_is_not_a_duplicate(tmp_path: Path) -> None:
    """``(phase, task)`` is the key — the branch, and a task id, are phase-scoped."""
    _write_roadmap(tmp_path, BEFORE)
    (tmp_path / "docs" / "tasks" / "04 - Other.md").write_text(
        "# Phase 04: Other\n\n## Epic H3: Other\n\n"
        "- [ ] **H3.1. Same task id, other phase** <details>\n  Done when: x.\n",
        encoding="utf-8",
    )
    tasks = roadmap.load_tasks(_roadmap_dir(tmp_path), "[0-9]* - *.md")

    entry = roadmap.tick_entry(tasks, phase="03", task=CHECKBOX_ID)

    assert entry.phase == "03"
    assert roadmap.entry_path(_roadmap_dir(tmp_path), entry).name == (
        "03 - Stage resilience.md"
    )


# --------------------------------------------------------------------------- #
# The settlement helper: the pinned observable record (H3.1 req 7)
# --------------------------------------------------------------------------- #


def _run_directory(tmp_path: Path) -> tuple[Path, object]:
    """A real run state + directory, so ``_settle_roadmap_tick`` writes as it does live."""
    runs_root = tmp_path / "runs"
    state = create_run(
        runs_root, tmp_path, "implement", label="pytest", branch="03-H3.1"
    )
    return run_dir(runs_root, state.run_id), state


def _settle(
    tmp_path: Path,
    *,
    before: str,
    after: str,
    checkbox_id: str = CHECKBOX_ID,
    exit_code: int | None = None,
) -> tuple[StageRecord, str, object]:
    """:func:`..._settle_roadmap_tick` over a real file, returning record + run.log text."""
    path = _write_roadmap(tmp_path, after)
    directory, state = _run_directory(tmp_path)
    logger = RunLogger(directory)
    record = StageRecord(
        name="update-roadmap",
        agent="recorder",
        model="test/model",
        status=SUCCEEDED,
        exit_code=exit_code,
    )
    state.record_stage(record)

    implement_workflow._settle_roadmap_tick(
        record,
        checkbox_id=checkbox_id,
        roadmap_file=path,
        before=before,
        logger=logger,
        state=state,
        directory=directory,
    )
    return record, (directory / "run.log").read_text(encoding="utf-8"), state


def _assert_noop_contract(record: StageRecord) -> None:
    """The pinned ``already [x]`` record: succeeded (not skipped), marked, no error."""
    assert record.status == SUCCEEDED
    assert record.status != "skipped"  # H3.2's word for an evidence-withheld tick
    assert record.artifacts.get("tick") == roadmap.TICK_ALREADY
    assert record.error is None


def test_the_flipped_outcome_is_recorded_and_logged(tmp_path: Path) -> None:
    record, log, _state = _settle(tmp_path, before=BEFORE, after=_flip(BEFORE))

    assert record.status == SUCCEEDED
    assert record.artifacts.get("tick") == roadmap.TICK_FLIPPED
    assert record.error is None
    assert "roadmap H3.1: flipped `[ ]` -> `[x]`" in log


def test_the_already_outcome_records_the_pinned_no_op(tmp_path: Path) -> None:
    """``already`` is a success with its own marker and its own ``run.log`` line."""
    flipped = _flip(BEFORE)
    record, log, _state = _settle(tmp_path, before=flipped, after=flipped)

    _assert_noop_contract(record)
    assert "roadmap H3.1: already `[x]`, file unchanged" in log


def test_a_nonzero_stage_exit_cannot_claim_the_no_op_success(tmp_path: Path) -> None:
    """H3.1: a non-zero fake stage result must not become a successful tick record."""
    flipped = _flip(BEFORE)
    record, _log, _state = _settle(
        tmp_path, before=flipped, after=flipped, exit_code=1
    )

    assert record.status == FAILED
    assert record.artifacts.get("tick") is None
    assert record.error is not None


def test_the_no_op_contract_guard_is_live(tmp_path: Path) -> None:
    """A record that recorded ``skipped``, no marker, or a failure never matches it."""
    with pytest.raises(AssertionError):
        _assert_noop_contract(
            StageRecord(
                name="update-roadmap",
                agent="recorder",
                model="m",
                status="skipped",
                artifacts={"tick": roadmap.TICK_ALREADY},
            )
        )
    with pytest.raises(AssertionError):
        _assert_noop_contract(
            StageRecord(
                name="update-roadmap",
                agent="recorder",
                model="m",
                status=SUCCEEDED,
                artifacts={},
            )
        )
    with pytest.raises(AssertionError):
        _assert_noop_contract(
            StageRecord(
                name="update-roadmap",
                agent="recorder",
                model="m",
                status=FAILED,
                artifacts={"tick": roadmap.TICK_ALREADY},
                error="boom",
            )
        )


def test_a_bad_edit_fails_the_stage_and_records_no_marker(tmp_path: Path) -> None:
    """Exit 0 is not evidence: the postcondition fails the record, with the reason."""
    after = _flip(BEFORE) + "\n"
    record, log, state = _settle(tmp_path, before=BEFORE, after=after)

    assert record.status == FAILED
    assert "postcondition not met" in (record.error or "")
    assert "tick" not in record.artifacts
    assert "postcondition not met" in log
    # The persisted run state carries the failure, not a success marker.
    assert state.stage("update-roadmap").status == FAILED


def test_an_unreadable_file_fails_the_stage(tmp_path: Path) -> None:
    """A vanished file is a failed check, never a crash and never a success."""
    directory, state = _run_directory(tmp_path)
    logger = RunLogger(directory)
    record = StageRecord(
        name="update-roadmap", agent="recorder", model="m", status=SUCCEEDED
    )
    state.record_stage(record)

    implement_workflow._settle_roadmap_tick(
        record,
        checkbox_id=CHECKBOX_ID,
        roadmap_file=tmp_path / "does-not-exist.md",
        before=BEFORE,
        logger=logger,
        state=state,
        directory=directory,
    )

    assert record.status == FAILED
    assert "postcondition not met" in (record.error or "")


# --------------------------------------------------------------------------- #
# The prompt names no directory (H3.1 req 3, D15's two readers)
# --------------------------------------------------------------------------- #


def test_the_prompt_takes_the_roadmap_path_as_a_variable_and_names_no_directory() -> None:
    """D15: the workflow resolves ``paths.roadmap_dir``; the prompt receives the file."""
    text = (toolkit_root() / "prompts" / "update-roadmap.md").read_text(encoding="utf-8")

    assert "$1" in text and "$2" in text
    assert "docs/tasks" not in text
    assert "paths.roadmap_dir" not in text


# --------------------------------------------------------------------------- #
# Property sweep (pytest only: no hypothesis, AGENTS.md "Tests")
# --------------------------------------------------------------------------- #

#: The pinned seed: one mutation per non-target line, each applied to an otherwise legal
#: flip. ``numRuns`` is the seed's length, asserted below — the enumeration *is* the
#: generator (the convention ``tests/test_stage_registry.py`` uses).
MUTATIONS: tuple[tuple[str, Callable[[str], str]], ...] = (
    ("neighbour-char", lambda text: text.replace("it shipped", "it shipped!")),
    ("neighbour-indent", lambda text: text.replace("  Done when: it", "    Done when: it")),
    ("heading-edit", lambda text: text.replace("Epic H3:", "Epic H3 :")),
    ("extra-blank-line", lambda text: text.replace("## Epic", "\n## Epic")),
    ("trailing-space", lambda text: text.replace("gates.\n", "gates. \n")),
    ("crlf-tail", lambda text: text + "\r\n"),
)
NUM_RUNS = len(MUTATIONS)


def test_property_every_non_checkbox_mutation_is_rejected() -> None:
    """Property: one legal flip plus any further byte change is always rejected.

    ``numRuns = NUM_RUNS`` (pinned above): every mutation is applied to the same
    hand-calculated flip, so the sweep proves the check is byte-exact rather than
    line-shape-exact. The legal flip itself is the hand-calculated control.
    """
    assert NUM_RUNS == 6
    flipped = _flip(BEFORE)
    assert roadmap.verify_checkbox_flip(BEFORE, flipped, checkbox_id=CHECKBOX_ID) == (
        roadmap.TICK_FLIPPED
    )

    for name, mutate in MUTATIONS:
        after = mutate(flipped)
        assert after != flipped, name
        with pytest.raises(roadmap.RoadmapTickError):
            roadmap.verify_checkbox_flip(BEFORE, after, checkbox_id=CHECKBOX_ID)


def test_property_seed_and_run_count_are_pinned() -> None:
    """The seed is the whole sample, so the sweep cannot silently shrink."""
    assert NUM_RUNS == len(MUTATIONS) == 6
    assert len({name for name, _ in MUTATIONS}) == NUM_RUNS
