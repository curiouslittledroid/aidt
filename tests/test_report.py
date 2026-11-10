"""Tests for stage reporting (design §9, §14)."""

from __future__ import annotations

from pathlib import Path

from aidw.report import (
    cost_note,
    empty_final_message_error,
    rel_to,
    short_count,
    stage_lines,
    throughput,
    timing_line,
    tool_breakdown_line,
    usage_line,
)
from aidw.state import (
    FAILED,
    PLANNED,
    SKIP_REASON_KEY,
    SKIPPED,
    SUCCEEDED,
    StageRecord,
)

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


def test_empty_final_message_error_names_double_truncation() -> None:
    """H1.1's workflow failure identifies the final reason and both attempts."""
    message = empty_final_message_error(
        _record(name="code-review", stop_reason="length", attempts=2)
    )

    assert message == (
        "code-review: both attempts produced no final message "
        "(final stop_reason: length); both attempts were truncated"
    )
    assert "produced no final message" in message
    assert "length" in message
    assert "both attempts were truncated" in message


def test_empty_final_message_error_preserves_single_attempt_context() -> None:
    """The no-retry path still reports its reason and attempt count."""
    message = empty_final_message_error(
        _record(name="task-review-1", stop_reason="stop", attempts=1)
    )

    assert message == (
        "task-review-1: produced no final message "
        "(stop_reason: stop, attempts: 1)"
    )


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


def test_stage_lines_render_a_skipped_stage_with_its_reason() -> None:
    """H3.2 req 4: ``[skipped]`` plus the reason, and never as a failure or a usage line."""
    reason = "red gate for tree " + "a" * 64 + ": suite"
    lines = stage_lines(
        _record(
            name="update-roadmap",
            status=SKIPPED,
            usage=None,
            cost_usd=None,
            duration_seconds=None,
            artifacts={SKIP_REASON_KEY: reason},
        ),
        repo_root=Path("/repo"),
        prefix="I7",
    )

    assert lines[0] == (
        "stage:  I7 update-roadmap [skipped] model=openrouter/z-ai/glm-5.3"
    )
    assert lines[1] == f"        skipped: {reason}"
    assert not any(line.strip().startswith("error:") for line in lines)
    assert not any(line.strip().startswith("usage:") for line in lines)


def test_stage_lines_report_a_missing_skip_reason_rather_than_nothing() -> None:
    """A skip with no recorded reason is still observable — never a silent blank."""
    lines = stage_lines(
        _record(status=SKIPPED, usage=None, cost_usd=None, duration_seconds=None),
        prefix="I7",
    )

    assert lines[1] == "        skipped: no reason recorded"


def test_stage_lines_do_not_use_the_skip_line_for_a_failed_stage() -> None:
    """The skip rendering is keyed on the status, so ``error:`` still carries a failure."""
    lines = stage_lines(_record(status=FAILED, error="boom"))

    assert not any("skipped:" in line for line in lines)
    assert lines[1] == "        error: boom"


UNPRICED_USAGE = {
    "input_tokens": 42726,
    "output_tokens": 19242,
    "cache_read": 873984,
    "cache_write": 0,
    "reasoning": 0,
    "total_tokens": 935952,
    "cost_usd": 0.0,
}


def test_cost_note_flags_tokens_with_no_cost() -> None:
    note = cost_note("openrouter/deepseek/deepseek-v4.1-flash", UNPRICED_USAGE)
    assert note is not None
    assert note.startswith("936.0k tokens with $0.0000 cost")
    assert "deepseek/deepseek-v4.1-flash has no pricing" in note
    assert "modelOverrides" in note


def test_cost_note_is_silent_for_priced_and_local_stages() -> None:
    assert cost_note("openrouter/z-ai/glm-5.3", dict(UNPRICED_USAGE, cost_usd=0.0286)) is None
    assert cost_note("ollama/qwen3.8:27b-mlx", UNPRICED_USAGE) is None
    assert cost_note("openrouter/z-ai/glm-5.3", None) is None


def test_stage_lines_add_a_note_for_an_unpriced_stage() -> None:
    lines = stage_lines(
        _record(usage=dict(UNPRICED_USAGE), cost_usd=0.0), repo_root=Path("/repo")
    )
    assert lines[2].startswith("        note:  936.0k tokens with $0.0000 cost")
    assert lines[3] == "        out:   aidt/runs/x/stages/task-review.out.txt"


def test_stage_lines_omit_the_note_for_a_planned_stage() -> None:
    lines = stage_lines(_record(status=PLANNED, usage=dict(UNPRICED_USAGE), cost_usd=None))
    assert not any("note:" in line for line in lines)


def test_stage_lines_show_output_tokens_per_second() -> None:
    lines = stage_lines(
        _record(output_tokens_per_second=47.06), repo_root=Path("/repo")
    )
    assert lines[0].endswith("47.1 out-tok/s")


def test_stage_lines_omit_throughput_when_unmeasured() -> None:
    lines = stage_lines(_record(), repo_root=Path("/repo"))
    assert "out-tok/s" not in lines[0]
    assert throughput(_record()) is None


def test_timing_line_partitions_duration_into_ai_and_tools() -> None:
    """``ai`` is the duration complement of tool time, so both terms add up."""
    assert timing_line(_record(generation_seconds=2.5, tool_seconds=9.0)) == (
        "ai=60.1s tools=9s"
    )
    assert timing_line(_record(tool_seconds=9.0)) == "ai=60.1s tools=9s"


def test_timing_line_falls_back_to_generation_without_tool_time() -> None:
    assert timing_line(_record(generation_seconds=2.5)) == "ai=2.5s"
    assert timing_line(_record(generation_seconds=2.5, duration_seconds=None)) == "ai=2.5s"
    assert timing_line(_record()) == ""


def test_tool_breakdown_line_lists_tools_in_order() -> None:
    assert tool_breakdown_line({"bash": 95.2, "read": 60.1, "edit": 20.0}) == (
        "bash=95.2s read=60.1s edit=20s"
    )
    assert tool_breakdown_line({}) == ""
    assert tool_breakdown_line(None) == ""


def test_rel_to_falls_back_outside_the_base() -> None:
    assert rel_to(Path("/repo"), "/repo/docs/x.md") == "docs/x.md"
    assert rel_to(None, "/x/y.md") == "/x/y.md"
    assert rel_to(Path("/repo"), "/elsewhere/y.md") == "/elsewhere/y.md"
