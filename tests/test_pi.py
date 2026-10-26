"""Tests for Pi JSON event parsing (no subprocess)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from aidw.pi import (
    PiResult,
    Usage,
    _invoke,
    generation_seconds,
    is_transient,
    parse_events,
    parse_json_lines,
    tool_breakdown,
    tool_breakdown_from_log,
    tool_execution_seconds,
    tool_seconds_from_log,
    write_meta,
)


def _pi_result(**overrides: object) -> PiResult:
    """A minimal successful :class:`PiResult` for tests that vary one field."""
    values: dict[str, object] = {
        "exit_code": 0,
        "session_id": None,
        "final_message": "",
        "usage": Usage(),
        "duration_seconds": 0.0,
        "event_count": 0,
        "tool_calls": 0,
        "tool_errors": 0,
        "stop_reason": "stop",
        "stderr": "",
        "timed_out": False,
        "attempts": 1,
        "jsonl_path": "",
        "out_path": None,
    }
    values.update(overrides)
    return PiResult(**values)  # type: ignore[arg-type]


def _events() -> list[dict]:
    return [
        {"type": "session", "version": 3, "id": "sess-1", "cwd": "/repo"},
        {"type": "tool_execution_end", "toolName": "read", "isError": False},
        {"type": "tool_execution_end", "toolName": "bash", "isError": True},
        {"type": "message_end", "message": {"role": "assistant", "content": []}},
        {
            "type": "agent_end",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "hmm"},
                        {"type": "text", "text": "FINAL ANSWER"},
                    ],
                    "usage": {
                        "input": 10,
                        "output": 2,
                        "cacheRead": 1,
                        "totalTokens": 13,
                        "cost": {"total": 0.25},
                    },
                    "stopReason": "stop",
                },
            ],
        },
    ]


def test_parse_events_extracts_final_message_and_usage() -> None:
    parsed = parse_events(_events())
    assert parsed.session_id == "sess-1"
    assert parsed.final_message == "FINAL ANSWER"
    assert parsed.usage.input_tokens == 10
    assert parsed.usage.cost_usd == 0.25
    assert parsed.usage.total_tokens == 13
    assert parsed.stop_reason == "stop"
    assert parsed.tool_calls == 2
    assert parsed.tool_errors == 1
    assert parsed.event_count == 5


def test_parse_events_empty() -> None:
    parsed = parse_events([])
    assert parsed.final_message == ""
    assert parsed.session_id is None


def _usage(input_tokens: int, output_tokens: int, cache_read: int, cost: float) -> dict:
    return {
        "input": input_tokens,
        "output": output_tokens,
        "cacheRead": cache_read,
        "cacheWrite": 0,
        "reasoning": 0,
        "totalTokens": input_tokens + output_tokens + cache_read,
        "cost": {"total": cost},
    }


def test_parse_events_sums_usage_across_turns() -> None:
    """Pi reports usage per assistant message; a stage's total is their sum."""
    events = [
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "first"}],
                "usage": _usage(100, 10, 20, 0.001),
            },
        },
        {
            "type": "turn_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "first"}],
                "usage": _usage(100, 10, 20, 0.001),
            },
        },
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "last"}],
                "usage": _usage(200, 20, 40, 0.002),
                "stopReason": "stop",
            },
        },
        {
            "type": "turn_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "last"}],
                "usage": _usage(200, 20, 40, 0.002),
                "stopReason": "stop",
            },
        },
        {
            "type": "agent_end",
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "last"}],
                    "usage": _usage(200, 20, 40, 0.002),
                    "stopReason": "stop",
                }
            ],
        },
    ]
    parsed = parse_events(events)
    assert parsed.final_message == "last"
    assert parsed.usage.input_tokens == 300
    assert parsed.usage.output_tokens == 30
    assert parsed.usage.cache_read == 60
    assert parsed.usage.total_tokens == 390
    assert parsed.usage.cost_usd == pytest.approx(0.003)


def test_parse_events_falls_back_to_agent_end_usage() -> None:
    """Older/odd streams may carry usage only on the final agent message."""
    parsed = parse_events(_events())
    assert parsed.usage.input_tokens == 10
    assert parsed.usage.cost_usd == 0.25


def test_parse_json_lines_ignores_malformed() -> None:
    lines = ["not json", '{"type":"session","id":"s"}', "", '{"broken":']
    parsed = parse_json_lines(lines)
    assert parsed.session_id == "s"


def test_parse_json_lines_uses_last_assistant() -> None:
    lines = [
        '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"first"}]}}',
        '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"second"}]}}',
    ]
    assert parse_json_lines(lines).final_message == "second"


def test_is_transient() -> None:
    assert is_transient("Error: socket hang up", 1)
    assert is_transient("HTTP 503 Service Unavailable", 1)
    assert not is_transient("invalid API key", 1)
    assert not is_transient("anything", 0)


def test_parse_events_captures_provider_error() -> None:
    events = [
        {"type": "session", "id": "s"},
        {
            "type": "turn_end",
            "message": {
                "role": "assistant",
                "content": [],
                "stopReason": "error",
                "errorMessage": "402: insufficient credits",
            },
        },
    ]
    parsed = parse_events(events)
    assert parsed.stop_reason == "error"
    assert parsed.error_message is not None and "402" in parsed.error_message


def test_parse_events_captures_top_level_error() -> None:
    parsed = parse_events([{"type": "error", "message": "boom"}])
    assert parsed.error_message == "boom"


def test_pi_result_failed_on_provider_error() -> None:
    result = PiResult(
        exit_code=0,
        session_id=None,
        final_message="",
        usage=Usage(),
        duration_seconds=0.0,
        event_count=0,
        tool_calls=0,
        tool_errors=0,
        stop_reason="error",
        stderr="",
        timed_out=False,
        attempts=1,
        jsonl_path="",
        out_path=None,
        error_message="402: insufficient credits",
    )
    assert result.provider_error is True
    assert result.failed is True


def test_write_meta_records_model_usage_and_prompt_provenance(tmp_path: Path) -> None:
    """The stage metadata must answer "which prompt did this stage use?"."""
    result = PiResult(
        exit_code=0,
        session_id="sess",
        final_message="ok",
        usage=Usage(input_tokens=5, total_tokens=5),
        duration_seconds=1.5,
        event_count=2,
        tool_calls=0,
        tool_errors=0,
        stop_reason="stop",
        stderr="",
        timed_out=False,
        attempts=1,
        jsonl_path="stages/task-review.jsonl",
        out_path=None,
    )
    path = tmp_path / "task-review.meta.json"
    write_meta(
        path,
        result,
        ["pi", "-p"],
        model="openrouter/z-ai/glm-5.3",
        stage="task-review",
        agent="task-reviewer",
        prompt_source="/aidt/prompts/task-review.md",
        rendered_prompt="prompts/task-review.rendered.md",
    )

    meta = json.loads(path.read_text(encoding="utf-8"))
    assert meta["stage"] == "task-review"
    assert meta["agent"] == "task-reviewer"
    assert meta["prompt_source"] == "/aidt/prompts/task-review.md"
    assert meta["rendered_prompt"] == "prompts/task-review.rendered.md"
    assert meta["model"] == "openrouter/z-ai/glm-5.3"
    assert meta["usage"]["input_tokens"] == 5


# ── generation timing: output tokens per second ─────────────────────────── #


def _timed(at: float, event: dict) -> tuple[float, str]:
    return at, json.dumps(event)


def test_generation_seconds_counts_only_streaming_time() -> None:
    """Prefill and tool execution fall outside a message's window; thinking is inside."""
    lines = [
        _timed(0.0, {"type": "message_start", "message": {"role": "assistant"}}),
        _timed(0.2, {"type": "message_update", "usage": {"output": 0}}),
        _timed(0.4, {"type": "message_update", "usage": {"output": 5}}),
        _timed(1.0, {"type": "message_end", "message": {"role": "assistant", "usage": {"output": 5}}}),
        # An 8s tool call must not inflate generation time.
        _timed(1.1, {"type": "tool_execution_start", "toolName": "bash"}),
        _timed(9.0, {"type": "tool_execution_end", "toolName": "bash", "isError": False}),
        _timed(10.0, {"type": "message_start", "message": {"role": "assistant"}}),
        _timed(10.1, {"type": "message_update", "usage": {"output": 0}}),
        _timed(10.4, {"type": "message_end", "message": {"role": "assistant", "usage": {"output": 2}}}),
    ]
    # 0.2 -> 1.0 and 10.1 -> 10.4; the 0.2s prefill and 8s tool call are excluded.
    assert generation_seconds(lines) == pytest.approx(1.1)


def test_generation_seconds_skips_messages_without_output() -> None:
    """Only messages that reported output tokens contribute, matching the numerator."""
    lines = [
        _timed(0.0, {"type": "message_update", "usage": {"output": 0}}),
        _timed(0.6, {"type": "message_end", "message": {"role": "assistant", "usage": {"output": 0}}}),
        _timed(1.0, {"type": "message_update", "usage": {"output": 0}}),
        _timed(1.5, {"type": "message_end", "message": {"role": "assistant", "usage": {"output": 7}}}),
    ]
    assert generation_seconds(lines) == pytest.approx(0.5)


def test_generation_seconds_ignores_non_assistant_and_malformed() -> None:
    lines = [
        _timed(0.0, {"type": "message_update", "usage": {"output": 0}}),
        _timed(0.2, {"type": "message_end", "message": {"role": "toolResult", "usage": {"output": 9}}}),
        (0.3, "{not json"),
        (0.4, ""),
    ]
    assert generation_seconds(lines) == 0.0


def test_tool_execution_seconds_prefers_pi_duration_ms() -> None:
    """Each call's recorded elapsed time is summed; generation gaps are excluded."""
    lines = [
        _timed(0.0, {"type": "message_update", "usage": {"output": 0}}),
        _timed(1.0, {"type": "tool_execution_start", "toolCallId": "a", "toolName": "read"}),
        _timed(
            3.5,
            {
                "type": "tool_execution_end",
                "toolCallId": "a",
                "toolName": "read",
                "durationMs": 2500,
                "isError": False,
            },
        ),
        _timed(9.0, {"type": "tool_execution_start", "toolCallId": "b", "toolName": "bash"}),
        _timed(
            9.5,
            {
                "type": "tool_execution_end",
                "toolCallId": "b",
                "toolName": "bash",
                "durationMs": 500,
                "isError": False,
            },
        ),
    ]
    assert tool_execution_seconds(lines) == pytest.approx(3.0)


def test_tool_execution_seconds_falls_back_to_arrival_windows() -> None:
    """A stream without ``durationMs`` is measured between start and end per call."""
    lines = [
        _timed(1.0, {"type": "tool_execution_start", "toolCallId": "a", "toolName": "read"}),
        _timed(3.5, {"type": "tool_execution_end", "toolCallId": "a", "toolName": "read"}),
        _timed(4.0, {"type": "tool_execution_start", "toolCallId": "b", "toolName": "bash"}),
        _timed(4.5, {"type": "tool_execution_end", "toolCallId": "b", "toolName": "bash"}),
    ]
    assert tool_execution_seconds(lines) == pytest.approx(3.0)


def test_tool_execution_seconds_ignores_unterminated_and_malformed() -> None:
    lines = [
        _timed(0.0, {"type": "tool_execution_start", "toolCallId": "a", "toolName": "read"}),
        (1.0, "{not json"),
        (2.0, ""),
    ]
    assert tool_execution_seconds(lines) == 0.0


def test_tool_seconds_from_log_recovers_a_persisted_run(tmp_path: Path) -> None:
    """A stage log recorded before ``tool_seconds`` existed still yields tool time."""
    log = tmp_path / "s.jsonl"
    log.write_text(
        "\n".join(
            [
                json.dumps({"type": "tool_execution_end", "toolCallId": "a", "durationMs": 1500}),
                json.dumps({"type": "tool_execution_end", "toolCallId": "b", "durationMs": 2500}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert tool_seconds_from_log(log) == pytest.approx(4.0)
    assert tool_seconds_from_log(tmp_path / "missing.jsonl") is None


def test_tool_breakdown_groups_by_name_longest_first() -> None:
    """Per-tool seconds are summed by name and ordered longest-first."""
    lines = [
        _timed(0.0, {"type": "tool_execution_start", "toolCallId": "a", "toolName": "read"}),
        _timed(
            2.5,
            {
                "type": "tool_execution_end",
                "toolCallId": "a",
                "toolName": "read",
                "durationMs": 2500,
            },
        ),
        _timed(3.0, {"type": "tool_execution_start", "toolCallId": "b", "toolName": "bash"}),
        _timed(
            10.0,
            {
                "type": "tool_execution_end",
                "toolCallId": "b",
                "toolName": "bash",
                "durationMs": 7000,
            },
        ),
        _timed(11.0, {"type": "tool_execution_start", "toolCallId": "c", "toolName": "read"}),
        _timed(
            12.0,
            {
                "type": "tool_execution_end",
                "toolCallId": "c",
                "toolName": "read",
                "durationMs": 1000,
            },
        ),
    ]
    assert tool_breakdown(lines) == {"bash": 7.0, "read": 3.5}
    # The total is exactly the sum of the parts, so a display can never disagree.
    assert tool_execution_seconds(lines) == pytest.approx(10.5)


def test_tool_breakdown_from_log_ignores_missing_read_times(tmp_path: Path) -> None:
    """A persisted log has no arrival times, so only ``durationMs`` is trusted."""
    log = tmp_path / "s.jsonl"
    log.write_text(
        "\n".join(
            [
                json.dumps({"type": "tool_execution_start", "toolCallId": "a", "toolName": "read"}),
                json.dumps({"type": "tool_execution_end", "toolCallId": "a", "toolName": "read"}),
                json.dumps(
                    {
                        "type": "tool_execution_end",
                        "toolCallId": "b",
                        "toolName": "bash",
                        "durationMs": 1500,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert tool_breakdown_from_log(log) == {"bash": 1.5}
    assert tool_breakdown_from_log(tmp_path / "missing.jsonl") == {}


def test_tool_seconds_from_log_is_none_when_unmeasurable(tmp_path: Path) -> None:
    """No ``durationMs`` and no read times must not masquerade as zero tool time."""
    log = tmp_path / "s.jsonl"
    log.write_text(
        json.dumps({"type": "tool_execution_end", "toolCallId": "a"}) + "\n",
        encoding="utf-8",
    )
    assert tool_seconds_from_log(log) is None


def test_output_tokens_per_second_rounds_and_guards_zero() -> None:
    assert _pi_result(
        usage=Usage(output_tokens=100), generation_seconds=4.0
    ).output_tokens_per_second == 25.0
    assert _pi_result(usage=Usage(output_tokens=100)).output_tokens_per_second is None
    assert _pi_result(
        usage=Usage(output_tokens=0), generation_seconds=4.0
    ).output_tokens_per_second is None


def test_write_meta_records_generation_and_throughput(tmp_path: Path) -> None:
    result = _pi_result(usage=Usage(output_tokens=100), generation_seconds=4.0)
    path = tmp_path / "s.meta.json"
    write_meta(path, result, ["pi", "-p"], model="m", stage="s")
    meta = json.loads(path.read_text(encoding="utf-8"))
    assert meta["generation_seconds"] == 4.0
    assert meta["tool_seconds"] is None
    assert meta["tool_breakdown"] == {}
    assert meta["output_tokens_per_second"] == 25.0


# ── _invoke: streaming, prompt delivery, timeout ────────────────────────── #


def test_invoke_streams_stdout_before_the_process_exits(tmp_path: Path) -> None:
    """Progress must be fed as events arrive, not after Pi exits.

    The child blocks until the first line has been fed, and exits non-zero if that
    never happens — so a buffered implementation fails the test rather than passing
    slowly.
    """
    sentinel = tmp_path / "go"
    script = (
        "import json, pathlib, sys, time\n"
        "prompt = sys.stdin.read()\n"
        "print(json.dumps({'type': 'session', 'prompt_len': len(prompt)}), flush=True)\n"
        f"sentinel = pathlib.Path({str(sentinel)!r})\n"
        "for _ in range(1000):\n"
        "    if sentinel.exists():\n"
        "        break\n"
        "    time.sleep(0.01)\n"
        "else:\n"
        "    print(json.dumps({'type': 'error', 'message': 'line 1 was never fed'}), flush=True)\n"
        "    sys.exit(3)\n"
        "print(json.dumps({'type': 'message_end', 'message': {'role': 'assistant'}}), flush=True)\n"
        "print('a warning', file=sys.stderr, flush=True)\n"
    )

    class Collector:
        def __init__(self) -> None:
            self.lines: list[str] = []

        def feed(self, line: str) -> None:
            self.lines.append(line)
            if len(self.lines) == 1:
                sentinel.write_text("go", encoding="utf-8")

    collector = Collector()
    code, stdout, stderr, timed_out = _invoke(
        [sys.executable, "-c", script],
        "the prompt",
        env=dict(os.environ),
        cwd=tmp_path,
        timeout=30.0,
        progress=collector,
    )

    assert timed_out is False
    assert code == 0
    assert len(collector.lines) == 2
    assert json.loads(collector.lines[0])["prompt_len"] == len("the prompt")
    assert json.loads(collector.lines[1])["type"] == "message_end"
    assert len(stdout.splitlines()) == 2
    assert "a warning" in stderr


def test_invoke_enforces_the_timeout(tmp_path: Path) -> None:
    start = time.monotonic()
    code, _stdout, _stderr, timed_out = _invoke(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        "",
        env=dict(os.environ),
        cwd=tmp_path,
        timeout=0.5,
    )
    assert timed_out is True
    assert time.monotonic() - start < 20
    assert code != 0


def test_invoke_records_line_arrivals(tmp_path: Path) -> None:
    """Pi timestamps nothing, so AIDW must time each line as it reads it."""
    script = (
        "import json, sys, time\n"
        "sys.stdin.read()\n"
        "print(json.dumps({'type': 'session', 'id': 's'}), flush=True)\n"
        "time.sleep(0.15)\n"
        "print(json.dumps({'type': 'message_end', 'message': {'role': 'assistant'}}), flush=True)\n"
    )
    arrivals: list[float] = []
    code, stdout, _stderr, timed_out = _invoke(
        [sys.executable, "-c", script],
        "",
        env=dict(os.environ),
        cwd=tmp_path,
        timeout=30.0,
        arrivals=arrivals,
    )
    assert code == 0
    assert timed_out is False
    assert len(arrivals) == len(stdout.splitlines()) == 2
    assert arrivals[1] - arrivals[0] >= 0.1
