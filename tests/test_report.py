"""Tests for stage reporting (design §9, §14)."""

from __future__ import annotations

from pathlib import Path

from aidw.report import rel_to, short_count, stage_lines, usage_line
from aidw.state import FAILED, PLANNED, SUCCEEDED, StageRecord

USAGE = {
    "input_tokens": 193,
    "output_tokens": 16,
    "cache_read": 50432,
    "cache_write": 0,
    "reasoning": 0,
    "total_tokens": 50641,
    "cost_usd": 0.0286,
}


def _record(**overrides: object) -> StageRecord:
    values: dict[str, object] = {
        "name": "task-review",
        "agent": "task-reviewer",
        "model": "openrouter/z-ai/glm-5.3",
        "status": SUCCEEDED,
        "duration_seconds": 69.1,
        "cost_usd": 0.0286,
        "usage": dict(USAGE),
        "artifacts": {"out": "/repo/aidt/runs/x/stages/task-review.out.txt"},
    }
    values.update(overrides)
    return StageRecord(**values)  # type: ignore[arg-type]


def test_short_count() -> None:
    assert short_count(0) == "0"
    assert short_count(999) == "999"
    assert short_count(1000) == "1.0k"
    assert short_count(50641) == "50.6k"
    assert short_count(2_000_000) == "2.0M"


def test_usage_line_reports_every_counter() -> None:
    line = usage_line(USAGE)
    assert line == (
        "total=50.6k in=193 out=16 cache_read=50.4k cache_write=0 "
        "reasoning=0 cost=$0.0286"
    )


def test_usage_line_is_empty_without_measurements() -> None:
    assert usage_line(None) == ""
    assert usage_line({}) == ""


def test_stage_lines_show_model_usage_and_output_path() -> None:
    lines = stage_lines(_record(), repo_root=Path("/repo"))
    assert lines[0] == (
        "stage:  task-review [succeeded] model=openrouter/z-ai/glm-5.3 "
        "69.1s cost=$0.0286"
    )
    assert lines[1].startswith("        usage: total=50.6k")
    assert lines[2] == "        out:   aidt/runs/x/stages/task-review.out.txt"


def test_stage_lines_carry_the_workflow_stage_id() -> None:
    lines = stage_lines(_record(), prefix="I2")
    assert lines[0].startswith("stage:  I2 task-review [succeeded]")


def test_stage_lines_omit_usage_for_a_planned_stage() -> None:
    lines = stage_lines(_record(status=PLANNED, usage=None, cost_usd=None, duration_seconds=None))
    assert lines == ["stage:  task-review [planned] model=openrouter/z-ai/glm-5.3"]


def test_stage_lines_report_a_failure_instead_of_usage() -> None:
    lines = stage_lines(_record(status=FAILED, error="cost_ceiling: $0.5 > $0.1"))
    assert lines[0] == (
        "stage:  task-review [failed] model=openrouter/z-ai/glm-5.3 "
        "69.1s cost=$0.0286"
    )
    assert lines[1] == "        error: cost_ceiling: $0.5 > $0.1"
    assert not any(line.strip().startswith("usage:") for line in lines)


def test_rel_to_falls_back_outside_the_base() -> None:
    assert rel_to(Path("/repo"), "/repo/docs/x.md") == "docs/x.md"
    assert rel_to(None, "/x/y.md") == "/x/y.md"
    assert rel_to(Path("/repo"), "/elsewhere/y.md") == "/elsewhere/y.md"
