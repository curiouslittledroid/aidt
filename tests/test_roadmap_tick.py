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

H3.2 adds the **evidence condition**: :func:`aidw.workflows.implement.tick_evidence` is the
pure rule behind ``WHEN_EVIDENCE_GREEN`` — green iff the tick's tree has an identity, at least
one recorded gate outcome is for exactly that tree, and every such outcome passed; anything
else withholds the tick with a reason naming the failing gates or the absence. Its scope
(:func:`aidw.workflows.implement.tick_evidence_ignore`) is the four resolved document
write-targets, and :func:`...roadmap_tick_evidence` recomputes the tree with
``tree_identity``'s **default** base, so the identity matches the one ``aidw gate run``
recorded.

No Pi model is involved (design §15): the pure helpers are called directly, and the
workflow's own helpers are driven with a real ``RunState``/``RunLogger`` in a temporary run
directory. The workflow-level exit codes and stage plan are pinned in
``tests/test_implement_workflow.py``.

``hypothesis`` is not a dependency (AGENTS.md "Tests": pytest only), so the sweep at the
bottom enumerates its input space deterministically with a pinned seed and run count.
"""

from __future__ import annotations

import builtins
import itertools
from collections.abc import Callable
from pathlib import Path

import pytest

from aidw import roadmap
from aidw import state as state_module
from aidw.log import RunLogger
from aidw.paths import toolkit_root
from aidw.state import (
    FAILED,
    PASSED,
    SUCCEEDED,
    GateOutcome,
    StageRecord,
    create_run,
    run_dir,
)
from aidw.target_config import load_target_config, resolve_config
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
# WHEN_EVIDENCE_GREEN: the rule, its scope, and the tree it is computed for (H3.2)
# --------------------------------------------------------------------------- #

TREE = "a" * 64
OTHER_TREE = "b" * 64


def _outcome(
    key: str = "suite", *, tree: str = TREE, status: str = PASSED
) -> GateOutcome:
    """One hand-calculated recorded gate outcome (``aidw/state.py:GateOutcome``)."""
    return GateOutcome(
        key=key,
        command=["uv", "run", "--frozen", "pytest"],
        tree=tree,
        status=status,
        stage="record-implementation-results",
        at="2026-11-10T00:00:00Z",
        exit_code=0 if status == PASSED else 1,
        summary="1 passed" if status == PASSED else "1 failed",
    )


def test_evidence_is_green_when_every_outcome_for_the_tree_passed() -> None:
    """The happy path: several recorded passes for exactly this tree."""
    outcomes = [_outcome(key) for key in ("build", "doctor", "agents", "prompts", "suite")]

    evidence = implement_workflow.tick_evidence(outcomes, TREE)

    assert evidence.green is True
    assert evidence.tree == TREE
    # A green verdict never carries a reason somebody might print as one.
    assert evidence.reason == ""


def test_one_red_outcome_withholds_the_tick_and_names_every_failing_gate() -> None:
    """The E6.1 shape: four green gates and a red ``suite`` withhold the tick."""
    outcomes = [
        _outcome("build"),
        _outcome("doctor"),
        _outcome("agents"),
        _outcome("prompts"),
        _outcome("suite", status=FAILED),
    ]

    evidence = implement_workflow.tick_evidence(outcomes, TREE)

    assert evidence.green is False
    assert evidence.tree == TREE
    assert "suite" in evidence.reason
    assert TREE in evidence.reason
    # The passing gates are not blamed.
    for key in ("build", "doctor", "agents", "prompts"):
        assert key not in evidence.reason


def test_every_failing_gate_is_named_once() -> None:
    """Two failures of one key are still one key to fix; two keys are both named."""
    outcomes = [
        _outcome("suite", status=FAILED),
        _outcome("suite", status=FAILED),
        _outcome("build", status=FAILED),
        _outcome("doctor"),
    ]

    reason = implement_workflow.tick_evidence(outcomes, TREE).reason

    assert reason.count("suite") == 1
    assert "build" in reason
    assert "doctor" not in reason
    assert reason.startswith("red gates for tree ")


def test_zero_matching_outcomes_is_no_evidence_not_green() -> None:
    """"No evidence" is not "green": a run whose gates recorded nothing never ticks."""
    outcomes = [_outcome(tree=OTHER_TREE)]

    evidence = implement_workflow.tick_evidence(outcomes, TREE)

    assert evidence.green is False
    assert evidence.tree == TREE
    assert TREE in evidence.reason
    assert "no evidence" in evidence.reason
    assert "no gate outcome is recorded" in evidence.reason


def test_an_unresolvable_tree_identity_is_no_evidence() -> None:
    """``tree_identity`` returning ``None`` (unresolvable base / over budget) never greens."""
    evidence = implement_workflow.tick_evidence([_outcome()], None)

    assert evidence.green is False
    assert evidence.tree is None
    assert "no evidence" in evidence.reason
    assert "no tree identity" in evidence.reason
    assert evidence.reason == implement_workflow.TICK_NO_TREE_REASON


def test_outcomes_for_another_tree_are_ignored_in_both_directions() -> None:
    """A foreign pass is not evidence here, and a foreign failure is not this verdict."""
    green = implement_workflow.tick_evidence(
        [_outcome(tree=OTHER_TREE, status=FAILED), _outcome(tree=TREE)], TREE
    )
    red = implement_workflow.tick_evidence(
        [_outcome(tree=OTHER_TREE), _outcome(tree=TREE, status=FAILED)], TREE
    )

    assert green.green is True
    assert red.green is False
    assert "suite" in red.reason


def test_the_condition_is_pure(monkeypatch: pytest.MonkeyPatch) -> None:
    """No I/O, and neither the outcome list nor its rows are mutated (design §15)."""
    outcomes = [_outcome("build"), _outcome("suite", status=FAILED)]
    before = [(row.key, row.tree, row.status) for row in outcomes]

    def _explode(*args: object, **kwargs: object):
        raise AssertionError("tick_evidence must not touch a file")

    monkeypatch.setattr(builtins, "open", _explode)
    monkeypatch.setattr(Path, "read_text", _explode)
    monkeypatch.setattr(Path, "write_text", _explode)

    implement_workflow.tick_evidence(outcomes, TREE)

    assert [(row.key, row.tree, row.status) for row in outcomes] == before
    assert len(outcomes) == 2


def test_the_scope_is_the_four_resolved_document_write_targets(tmp_path: Path) -> None:
    """Req 3: the four resolved dirs, canonicalised the way ``--ignore`` is."""
    resolved = resolve_config(load_target_config(tmp_path / "aidw" / "config.yaml"))

    assert implement_workflow.tick_evidence_ignore(resolved, tmp_path) == (
        "docs/architecture",
        "docs/implementation-results",
        "docs/task-prompts",
        "docs/tasks",
    )


def test_the_scope_follows_a_reconfigured_document_dir(tmp_path: Path) -> None:
    """A relocated ``roadmap_dir`` is a relocated ignore prefix, not a hardcoded ``docs/tasks``."""
    (tmp_path / "aidw").mkdir()
    (tmp_path / "aidw" / "config.yaml").write_text(
        "schema_version: 1\n"
        "paths:\n"
        "  roadmap_dir: ./planning/roadmaps/\n",
        encoding="utf-8",
    )
    resolved = resolve_config(load_target_config(tmp_path / "aidw" / "config.yaml"))

    scope = implement_workflow.tick_evidence_ignore(resolved, tmp_path)

    assert "planning/roadmaps" in scope
    assert "docs/tasks" not in scope
    # Canonical form: no trailing slash, no ``./`` prefix (``normalise_ignore``'s rule).
    assert all(not value.startswith("./") and not value.endswith("/") for value in scope)


def test_the_scope_drops_a_document_dir_outside_the_repo(tmp_path: Path) -> None:
    """An absolute write-target outside the tree cannot be a repo-relative prefix."""
    outside = tmp_path.parent / "elsewhere-results"
    (tmp_path / "aidw").mkdir()
    (tmp_path / "aidw" / "config.yaml").write_text(
        "schema_version: 1\n"
        "paths:\n"
        f"  implementation_results_dir: {outside}\n",
        encoding="utf-8",
    )
    resolved = resolve_config(load_target_config(tmp_path / "aidw" / "config.yaml"))

    scope = implement_workflow.tick_evidence_ignore(resolved, tmp_path)

    assert "docs/implementation-results" not in scope
    assert scope == ("docs/architecture", "docs/task-prompts", "docs/tasks")


def test_the_tree_is_recomputed_with_the_gates_own_default_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Req 3's trap: the default base and the given scope, never ``repo.base_branch``.

    ``aidw gate run`` records every outcome under ``verification.BASE_DEFAULT`` (the prompts
    pass no ``--base``), so recomputing with the configured base would match nothing and
    silently never tick. The in-memory ``state.gate_outcomes`` is the only source read.
    """
    seen: dict[str, object] = {}

    def fake_tree_identity(repo_root: Path, **kwargs: object) -> str:
        seen["repo_root"] = repo_root
        seen.update(kwargs)
        return TREE

    monkeypatch.setattr(
        implement_workflow.verification, "tree_identity", fake_tree_identity
    )
    directory, state = _run_directory(tmp_path)
    state.record_gate_outcome(_outcome("suite"))

    evidence = implement_workflow.roadmap_tick_evidence(
        state,
        repo_root=tmp_path,
        exclude=(tmp_path / "state",),
        ignore=("docs/tasks",),
    )

    assert evidence.green is True
    assert seen == {
        "repo_root": tmp_path,
        "exclude": (tmp_path / "state",),
        "ignore": ("docs/tasks",),
    }
    # ``base`` was never passed, so ``tree_identity`` used ``BASE_DEFAULT``.
    assert "base" not in seen


def test_the_in_memory_outcome_list_is_what_decides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Req 3's trap: the verdict reads the in-memory state, never a fresh ``state.load``.

    A re-read would re-introduce exactly the boundary loss H0.1 closed. The fixture makes
    the two disagree: the in-memory run holds the red ``suite``, the published
    ``state.json`` holds none, and a reload is made fatal.
    """
    monkeypatch.setattr(
        implement_workflow.verification, "tree_identity", lambda *a, **k: TREE
    )
    directory, state = _run_directory(tmp_path)
    state.record_gate_outcome(_outcome("suite", status=FAILED))

    def _explode(*args: object, **kwargs: object):
        raise AssertionError("the condition must not re-read the run from disk")

    monkeypatch.setattr(state_module, "load", _explode)
    monkeypatch.setattr(state_module, "find_run", _explode)

    evidence = implement_workflow.roadmap_tick_evidence(
        state, repo_root=tmp_path, exclude=(), ignore=()
    )

    # The on-disk state (``create_run`` published an empty outcome list) would have said
    # "no evidence"; the in-memory one says which gate is red.
    assert evidence.green is False
    assert "suite" in evidence.reason
    assert directory.is_dir()  # the run directory exists; its state.json was not re-read


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


#: H3.2's property sample: every status combination over three gates (the green path, the
#: red path and each mixed case), plus the two "cannot cite" rows. Pinned, deterministic —
#: the enumeration *is* the generator (AGENTS.md "Tests": pytest only, no hypothesis).
EVIDENCE_CASES: tuple[tuple[str, tuple[str, ...], str | None], ...] = tuple(
    (f"statuses-{''.join(status[0] for status in statuses)}", statuses, TREE)
    for statuses in itertools.product((PASSED, FAILED), repeat=3)
) + (("no-outcomes", (), TREE), ("no-tree", (PASSED,), None))
EVIDENCE_NUM_RUNS = len(EVIDENCE_CASES)


def test_property_green_exactly_when_every_matching_outcome_passed() -> None:
    """Property: the rule is an ``all(passed)`` over the matching rows, nothing else."""
    assert EVIDENCE_NUM_RUNS == 10
    for name, statuses, tree in EVIDENCE_CASES:
        outcomes = [
            _outcome(f"gate{index}", status=status)
            for index, status in enumerate(statuses)
        ]

        evidence = implement_workflow.tick_evidence(outcomes, tree)

        expected = bool(statuses) and tree is not None and all(
            status == PASSED for status in statuses
        )
        assert evidence.green is expected, name
        assert (evidence.reason == "") is expected, name
        if not expected:
            # Every withheld verdict says *why*, and names the tree whenever it has one.
            assert evidence.reason, name
            if tree is not None:
                assert tree in evidence.reason, name


def test_property_evidence_seed_and_run_count_are_pinned() -> None:
    """The sample covers every 3-gate status combination plus both non-citable rows."""
    assert EVIDENCE_NUM_RUNS == len(EVIDENCE_CASES) == 10
    assert len({name for name, _, _ in EVIDENCE_CASES}) == EVIDENCE_NUM_RUNS
    assert sum(1 for _, statuses, tree in EVIDENCE_CASES if tree is None) == 1


# ── The recorded verdict rule (design §8.2) ─────────────────────────────────────────
#
# H3.2 withholds a tick behind a red gate. PR #282 showed the remaining gap: every gate was
# green and the task's own build-results document concluded its Done-when was unmet, so the
# tick was a completion claim the run's own recording contradicted. These pin the rule that
# reads that document — narrow on purpose, because a gate row that merely *quotes* the
# Done-when command must not withhold anything.

#: The line the record stage actually wrote for `04-A1.1` (PR #282) — the incident.
RECORDED_UNMET_LINE = (
    "Consequently the task's \"Done when\" is **not** met on this tree: the fixture's "
    "contract suite does not pass."
)


def test_find_unmet_conclusion_detects_the_recorded_verdict() -> None:
    """The incident's own sentence is a conclusion: it names the Done-when and denies it."""
    text = f"# Build Results\n\nSome prose.\n\n{RECORDED_UNMET_LINE}\n"

    assert roadmap.find_unmet_conclusion(text) == (5, RECORDED_UNMET_LINE)


def test_find_unmet_conclusion_reports_the_first_line_that_concludes() -> None:
    """One line is the claim; a later duplicate must not change which one is reported."""
    first = "At recording time the task's Done-when is not yet met."
    text = f"{first}\n\nThe Done-when is not met either.\n"

    assert roadmap.find_unmet_conclusion(text) == (1, first)


def test_find_unmet_conclusion_ignores_a_gate_row_quoting_the_done_when() -> None:
    """A verification row that runs the Done-when command concludes nothing."""
    row = (
        "| `pnpm docs:check-completions` (the task's Done-when check) | ✅ Pass — 288 "
        "roadmap task(s) checked |"
    )

    assert roadmap.find_unmet_conclusion(row) is None


def test_find_unmet_conclusion_ignores_a_met_verdict() -> None:
    """A met verdict, a green gate row and a bare reference all stay silent."""
    text = (
        "**Verdict:** the Done-when recorded in the roadmap **is met** on this tree.\n"
        "The Done-when: the contract suite passes.\n"
    )

    assert roadmap.find_unmet_conclusion(text) is None


def test_find_unmet_conclusion_is_case_insensitive_and_accepts_the_hyphen() -> None:
    """`Done-When`, `Done When` and `done-when` are the same claim."""
    for line in (
        "Done-When is not met on this tree.",
        "Done When is not met on this tree.",
        "done-when is not met on this tree.",
    ):
        assert roadmap.find_unmet_conclusion(line) == (1, line)


def test_find_unmet_conclusion_requires_the_negation_to_be_near() -> None:
    """A distant `not` cannot manufacture a conclusion out of an unrelated sentence."""
    line = (
        "The Done-when is met; note that the earlier attempt was not reviewed and the "
        "fixture was met later."
    )

    assert roadmap.find_unmet_conclusion(line) is None


def test_task_results_candidates_offers_padded_then_unpadded() -> None:
    """Both layouts are where a recorded document has lived; the padded form comes first."""
    assert roadmap.task_results_candidates("04", "A1.1") == ("04-A1.1", "4-A1.1")
    assert roadmap.task_results_candidates("3", "D3") == ("3-D3",)
    assert roadmap.task_results_candidates("03", "H3") == ("03-H3", "3-H3")


def test_recorded_unmet_conclusion_reads_the_padded_directory(tmp_path: Path) -> None:
    """The path in the reason is repo-relative, so an operator can open it."""
    results = tmp_path / "docs" / "implementation-results" / "04-A1.1"
    results.mkdir(parents=True)
    (results / "build-results.md").write_text(
        f"# Build Results\n\n{RECORDED_UNMET_LINE}\n", encoding="utf-8"
    )

    conclusion = roadmap.recorded_unmet_conclusion(
        tmp_path,
        implementation_results_dir="docs/implementation-results",
        phase="04",
        task="A1.1",
    )

    assert conclusion is not None
    assert conclusion.results_file == "docs/implementation-results/04-A1.1/build-results.md"
    assert conclusion.line == 3
    assert conclusion.text == RECORDED_UNMET_LINE


def test_recorded_unmet_conclusion_falls_back_to_the_unpadded_directory(
    tmp_path: Path,
) -> None:
    """Older result trees drop the padding; the rule must still find the document."""
    results = tmp_path / "docs" / "implementation-results" / "4-A1.1"
    results.mkdir(parents=True)
    (results / "build-results.md").write_text(
        f"{RECORDED_UNMET_LINE}\n", encoding="utf-8"
    )

    conclusion = roadmap.recorded_unmet_conclusion(
        tmp_path,
        implementation_results_dir="docs/implementation-results",
        phase="04",
        task="A1.1",
    )

    assert conclusion is not None
    assert conclusion.results_file == "docs/implementation-results/4-A1.1/build-results.md"


def test_recorded_unmet_conclusion_withholds_nothing_without_a_document(
    tmp_path: Path,
) -> None:
    """A repo with no build results keeps the H3.2 behaviour: absence is not a contradiction."""
    assert (
        roadmap.recorded_unmet_conclusion(
            tmp_path,
            implementation_results_dir="docs/implementation-results",
            phase="04",
            task="A1.1",
        )
        is None
    )


def test_recorded_unmet_conclusion_ignores_a_met_document(tmp_path: Path) -> None:
    """A refreshed verdict that now concludes met no longer withholds the tick."""
    results = tmp_path / "docs" / "implementation-results" / "03-H3"
    results.mkdir(parents=True)
    (results / "build-results.md").write_text(
        "**Verdict:** the Done-when recorded in the roadmap **is met**.\n",
        encoding="utf-8",
    )

    assert (
        roadmap.recorded_unmet_conclusion(
            tmp_path,
            implementation_results_dir="docs/implementation-results",
            phase="03",
            task="H3",
        )
        is None
    )


def test_unmet_conclusion_reason_names_the_document_and_line() -> None:
    """The skip reason is the operator's pointer: file:line first, claim second."""
    reason = roadmap.unmet_conclusion_reason(
        roadmap.UnmetConclusion(
            results_file="docs/implementation-results/04-A1.1/build-results.md",
            line=103,
            text="…",
        )
    )

    assert "docs/implementation-results/04-A1.1/build-results.md:103" in reason
    assert "Done-when is unmet" in reason
