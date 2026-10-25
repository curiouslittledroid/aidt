"""Live progress for a running Pi stage (design §9.3, §14).

A stage can run for minutes, and until it finishes AIDW otherwise prints nothing.
Pi streams its ``--mode json`` events as it works, so AIDW re-uses the transcript it
already captures as a liveness signal:

``.``  heartbeat — nothing new for ``interval`` seconds, Pi is still working
``*``  Pi finished an assistant message (one model response)
``+``  Pi started a tool call

Output goes to **stderr** — never stdout, which carries the transcript and the
workflow's own report — and is skipped unless the terminal is interactive, so CI logs
and piped runs stay clean. ``aidw --progress`` / ``--no-progress`` overrides the
default.
"""

from __future__ import annotations

import json
import sys
import threading
from typing import TextIO

HEARTBEAT = "."
RESPONSE = "*"
TOOL = "+"

#: Seconds of no output before a heartbeat dot.
DEFAULT_INTERVAL = 10.0

#: Marker written before a stage's dots.
STAGE_MARKER = "▶ "


class ProgressIndicator:
    """Writes a single line of progress symbols for one stage, then terminates it."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        interval: float = DEFAULT_INTERVAL,
        stream: TextIO | None = None,
    ) -> None:
        self.enabled = enabled
        self.interval = interval
        self.responses = 0
        self.tools = 0
        self._stream = stream if stream is not None else sys.stderr
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False

    # -- lifecycle -------------------------------------------------------- #

    def start(self, label: str) -> None:
        """Print the stage header (without a newline) and begin heartbeats."""
        if not self.enabled:
            return
        self._started = True
        self._write(f"{STAGE_MARKER}{label}\n  ")
        self._thread = threading.Thread(target=self._heartbeat, daemon=True)
        self._thread.start()

    def finish(self) -> None:
        """Stop the heartbeat and terminate the progress line."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._started:
            self._write("\n")

    # -- events ----------------------------------------------------------- #

    def feed(self, line: str) -> None:
        """Consume one raw JSONL line from Pi and tick if it is interesting."""
        if not self.enabled:
            return
        raw = line.strip()
        if not raw:
            return
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict):
            return

        kind = event.get("type")
        if kind == "message_end":
            message = event.get("message")
            if isinstance(message, dict) and message.get("role") == "assistant":
                self.responses += 1
                self._tick(RESPONSE)
        elif kind == "tool_execution_start":
            self.tools += 1
            self._tick(TOOL)

    # -- internals -------------------------------------------------------- #

    def _heartbeat(self) -> None:
        while not self._stop.wait(self.interval):
            self._tick(HEARTBEAT)

    def _tick(self, symbol: str) -> None:
        if not self.enabled:
            return
        self._write(symbol)

    def _write(self, text: str) -> None:
        with self._lock:
            if not self.enabled:
                return
            try:
                self._stream.write(text)
                self._stream.flush()
            except (ValueError, OSError):
                # A closed stream must never fail a stage.
                self.enabled = False


def resolve_enabled(explicit: bool | None) -> bool:
    """``None`` means auto: progress is shown only on an interactive terminal."""
    if explicit is not None:
        return explicit
    try:
        return sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False
