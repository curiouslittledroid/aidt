"""Tests for run state, persistence, and resumability metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aidw import state
from aidw.state import (
    PLANNED,
    GateRecord,
    RunState,
    StageRecord,
    create_run,
    find_run,
    latest_for_branch,
    list_runs,
    load,
    new_run_id,
    sanitize_label,
    save,
    session_id,
)


def test_sanitize_label() -> None:
    assert sanitize_label("03-E2.9") == "03-E2.9"
    assert sanitize_label("docs/task prompts/x") == "docs-task-prompts-x"
    assert sanitize_label("///") == "run"


def test_new_run_id_has_label_then_workflow_suffix() -> None:
    run_id = new_run_id("03-E2.9", "implement")
    assert run_id.endswith("-03-E2.9-implement")
    assert "T" in run_id


def test_new_run_id_distinguishes_workflows_for_one_label() -> None:
    ids = {new_run_id("03-E2.9", w) for w in ("prompt", "implement", "review", "fix")}
    # The stamp may collide within the same second; the workflow segment is what differs.
    assert {run_id.rsplit("-", 1)[-1] for run_id in ids} == {
        "prompt",
        "implement",
        "review",
        "fix",
    }
    assert all(run_id.split("-", 1)[1].startswith("03-E2.9-") for run_id in ids)


def test_new_run_id_sanitizes_both_segments() -> None:
    run_id = new_run_id("03/E2.9", "approve followups")
    assert run_id.endswith("-03-E2.9-approve-followups")


def test_new_run_id_does_not_repeat_a_workflow_already_in_the_label() -> None:
    # Guards the "workflow appears exactly once, at the end" invariant.
    assert new_run_id("pr-42-fix", "fix").endswith("-pr-42-fix")
    assert new_run_id("implement", "implement").endswith("-implement")
    # A label that merely contains the name keeps its own suffix.
    assert new_run_id("pr-42-fixups", "fix").endswith("-pr-42-fixups-fix")


def test_create_run_puts_workflow_in_the_directory_name(tmp_path: Path) -> None:
    run = create_run(tmp_path, tmp_path, "implement", label="03-E2.9", branch="03-E2.9")
    assert run.run_id.endswith("-03-E2.9-implement")
    assert (tmp_path / run.run_id / "state.json").is_file()


def test_create_save_load_round_trip(tmp_path: Path) -> None:
    run = create_run(tmp_path, tmp_path, "implement", label="t", branch="03-E2.9")
    run.record_stage(StageRecord(name="impliment-task", agent="implementer", model="m"))
    run.record_gate(GateRecord(name="g", decision="approved", mechanism="--yes", at="now"))
    save(tmp_path / run.run_id, run)

    loaded = load(tmp_path / run.run_id)
    assert loaded.run_id == run.run_id
    assert loaded.workflow == "implement"
    assert loaded.stages[0].name == "impliment-task"
    assert loaded.gates[0].decision == "approved"
    assert loaded.git["branch"] == "03-E2.9"


def test_record_stage_replaces_existing(tmp_path: Path) -> None:
    run = create_run(tmp_path, tmp_path, "stage", label="t")
    run.record_stage(StageRecord(name="s", agent="a", model="m", status=PLANNED))
    run.record_stage(StageRecord(name="s", agent="a", model="m", status="succeeded"))
    assert len(run.stages) == 1
    assert run.stages[0].status == "succeeded"


def test_list_find_latest(tmp_path: Path) -> None:
    first = create_run(tmp_path, tmp_path, "stage", label="one", branch="b")
    second = create_run(tmp_path, tmp_path, "stage", label="two", branch="b")
    found = list_runs(tmp_path)
    assert {r.run_id for r in found} == {first.run_id, second.run_id}
    assert find_run(tmp_path, first.run_id) is not None
    assert find_run(tmp_path, "missing") is None
    assert latest_for_branch(tmp_path, "b") is not None


def test_schema_version_guard(tmp_path: Path) -> None:
    directory = tmp_path / "run"
    directory.mkdir()
    (directory / "state.json").write_text(
        json.dumps({"schema_version": 999, "run_id": "x"}), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load(directory)


def test_session_id_shared_vs_fresh() -> None:
    shared = session_id("run1", "implementer", "impliment-task", shared=True)
    fresh = session_id("run1", "code-reviewer", "code-review", shared=False)
    assert shared == "aidw-run1-implementer"
    assert fresh == "aidw-run1-code-reviewer-code-review"


def test_totals_sum_all_stage_usage(tmp_path: Path) -> None:
    run = create_run(tmp_path, tmp_path, "prompt", label="t")
    run.record_stage(
        StageRecord(
            name="task-prompt",
            agent="task-author",
            model="m",
            usage={"input_tokens": 100, "output_tokens": 10, "cost_usd": 0.25},
        )
    )
    run.record_stage(
        StageRecord(
            name="task-review-1",
            agent="task-reviewer",
            model="m",
            usage={"input_tokens": 50, "output_tokens": 5, "cost_usd": 0.75},
        )
    )
    run.record_stage(StageRecord(name="planned", agent="a", model="m", status=PLANNED))

    assert run.totals() == {"input_tokens": 150, "output_tokens": 15, "cost_usd": 1.0}


def test_totals_fall_back_to_stage_cost(tmp_path: Path) -> None:
    run = create_run(tmp_path, tmp_path, "stage", label="t")
    run.record_stage(StageRecord(name="old", agent="a", model="m", cost_usd=0.5))
    assert run.totals() == {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.5}


def test_saved_state_has_totals_at_the_top(tmp_path: Path) -> None:
    run = create_run(tmp_path, tmp_path, "stage", label="t")
    run.record_stage(
        StageRecord(
            name="s",
            agent="a",
            model="m",
            usage={"input_tokens": 7, "output_tokens": 3, "cost_usd": 0.01},
        )
    )
    save(tmp_path / run.run_id, run)

    data = json.loads((tmp_path / run.run_id / "state.json").read_text(encoding="utf-8"))
    keys = list(data)
    assert keys.index("totals") == keys.index("schema_version") + 1
    assert data["totals"] == {"input_tokens": 7, "output_tokens": 3, "cost_usd": 0.01}


def test_from_dict_ignores_unknown_fields() -> None:
    data = {"run_id": "x", "workflow": "w", "created_at": "t", "repo_root": "/", "future": 1}
    loaded = RunState.from_dict(data)
    assert loaded.run_id == "x"


def test_stage_throughput_round_trips_without_a_schema_bump(tmp_path: Path) -> None:
    """Output tokens per second is additive: old runs still load at the same version."""
    run = create_run(tmp_path, tmp_path, "stage", label="t")
    run.record_stage(
        StageRecord(
            name="s",
            agent="a",
            model="m",
            generation_seconds=4.0,
            tool_seconds=9.0,
            tool_breakdown={"read": 6.0, "bash": 3.0},
            output_tokens_per_second=25.0,
        )
    )
    save(tmp_path / run.run_id, run)

    loaded = load(tmp_path / run.run_id)
    assert loaded.schema_version == state.SCHEMA_VERSION
    assert loaded.stages[0].generation_seconds == 4.0
    assert loaded.stages[0].tool_seconds == 9.0
    assert loaded.stages[0].tool_breakdown == {"read": 6.0, "bash": 3.0}
    assert loaded.stages[0].output_tokens_per_second == 25.0


def test_old_state_without_throughput_still_loads(tmp_path: Path) -> None:
    """A run written before the fields existed loads with ``None``, not an error."""
    directory = tmp_path / "run"
    directory.mkdir()
    (directory / "state.json").write_text(
        json.dumps(
            {
                "schema_version": state.SCHEMA_VERSION,
                "run_id": "x",
                "workflow": "w",
                "created_at": "t",
                "repo_root": "/",
                "stages": [{"name": "s", "agent": "a", "model": "m"}],
            }
        ),
        encoding="utf-8",
    )
    loaded = load(directory)
    assert loaded.stages[0].generation_seconds is None
    assert loaded.stages[0].tool_seconds is None
    assert loaded.stages[0].tool_breakdown is None
    assert loaded.stages[0].output_tokens_per_second is None
