"""Tests for the live stage progress indicator (design §9.3)."""

from __future__ import annotations

import io
import json
import sys
import time

from aidw.progress import HEARTBEAT, RESPONSE, STAGE_MARKER, TOOL, ProgressIndicator
from aidw.progress import resolve_enabled


def _event(**payload: object) -> str:
    return json.dumps(payload) + "\n"


def test_disabled_indicator_writes_nothing() -> None:
    stream = io.StringIO()
    indicator = ProgressIndicator(enabled=False, stream=stream)
    indicator.start("task-review (task-reviewer) model=x")
    indicator.feed(_event(type="message_end", message={"role": "assistant"}))
    indicator.feed(_event(type="tool_execution_start", toolName="read"))
    indicator.finish()
    assert stream.getvalue() == ""
    assert indicator.responses == 0
    assert indicator.tools == 0


def test_header_then_symbols_for_responses_and_tools() -> None:
    stream = io.StringIO()
    indicator = ProgressIndicator(enabled=True, interval=60.0, stream=stream)
    indicator.start("task-review (task-reviewer) model=openrouter/z-ai/glm-5.3")
    assert stream.getvalue() == (
        f"{STAGE_MARKER}task-review (task-reviewer) model=openrouter/z-ai/glm-5.3\n  "
    )

    indicator.feed(_event(type="message_end", message={"role": "assistant", "content": []}))
    indicator.feed(_event(type="tool_execution_start", toolName="read"))
    indicator.feed(_event(type="message_end", message={"role": "assistant", "content": []}))
    indicator.finish()

    assert stream.getvalue().endswith(f"{RESPONSE}{TOOL}{RESPONSE}\n")
    assert indicator.responses == 2
    assert indicator.tools == 1


def test_ignores_user_messages_noise_and_malformed_lines() -> None:
    stream = io.StringIO()
    indicator = ProgressIndicator(enabled=True, interval=60.0, stream=stream)
    indicator.start("stage")
    indicator.feed(_event(type="message_end", message={"role": "user", "content": []}))
    indicator.feed("not json at all")
    indicator.feed("")
    indicator.feed("[1, 2, 3]\n")
    indicator.feed(_event(type="tool_execution_end", toolName="read", isError=False))
    indicator.finish()
    assert stream.getvalue().endswith("\n  \n")
    assert indicator.responses == 0
    assert indicator.tools == 0


def test_heartbeat_ticks_while_nothing_happens() -> None:
    stream = io.StringIO()
    indicator = ProgressIndicator(enabled=True, interval=0.02, stream=stream)
    indicator.start("stage")
    time.sleep(0.09)
    indicator.finish()
    assert stream.getvalue().count(HEARTBEAT) >= 2


def test_a_closed_stream_never_fails_the_stage() -> None:
    class Broken(io.StringIO):
        def write(self, _text: str) -> int:  # type: ignore[override]
            raise ValueError("I/O operation on closed file")

    indicator = ProgressIndicator(enabled=True, interval=60.0, stream=Broken())
    indicator.start("stage")  # must not raise
    indicator.feed(_event(type="message_end", message={"role": "assistant"}))
    indicator.finish()
    assert indicator.enabled is False


def test_resolve_enabled_honours_explicit_values_and_auto_detects() -> None:
    assert resolve_enabled(True) is True
    assert resolve_enabled(False) is False
    assert resolve_enabled(None) == bool(sys.stderr.isatty())
