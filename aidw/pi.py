"""Pi subprocess invocation and JSON event parsing (design §4, §9).

Runs ``pi`` non-interactively (``-p``), pipes the rendered prompt on stdin, captures
stdout (JSONL in ``--mode json``) to a stage log, and parses the final assistant message
and usage. Retries once on a clearly transient invocation error (design E6); never
retries a gate failure.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from aidw.log import RunLogger
from aidw.progress import ProgressIndicator

TRANSIENT_PATTERNS = (
    "econnreset",
    "etimedout",
    "econnrefused",
    "socket hang up",
    "fetch failed",
    "rate limit",
    "too many requests",
    " 429",
    " 502",
    " 503",
    " 504",
    "temporarily unavailable",
)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    reasoning: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class ParsedRun:
    session_id: str | None = None
    final_message: str = ""
    stop_reason: str | None = None
    tool_calls: int = 0
    tool_errors: int = 0
    event_count: int = 0
    error_message: str | None = None
    usage: Usage = field(default_factory=Usage)


@dataclass
class PiResult:
    exit_code: int
    session_id: str | None
    final_message: str
    usage: Usage
    duration_seconds: float
    event_count: int
    tool_calls: int
    tool_errors: int
    stop_reason: str | None
    stderr: str
    timed_out: bool
    attempts: int
    jsonl_path: str
    out_path: str | None
    error_message: str | None = None
    #: Seconds Pi spent generating assistant messages (tool execution excluded).
    generation_seconds: float | None = None

    @property
    def output_tokens_per_second(self) -> float | None:
        """Generated output tokens per second of generation time (design §9.2).

        ``None`` when Pi generated no output or the stream carried no measurable
        generation window, so a caller never divides by a missing or zero denominator.
        """
        if not self.generation_seconds or not self.usage.output_tokens:
            return None
        return round(self.usage.output_tokens / self.generation_seconds, 1)

    @property
    def provider_error(self) -> bool:
        """True when the provider/agent reported an error inside the event stream.

        Pi can exit 0 while the run failed (for example an OpenRouter 402 emitted
        with ``stopReason: "error"``). Such a stage must not be reported as succeeded.
        """
        return self.stop_reason == "error" or bool(self.error_message)

    @property
    def failed(self) -> bool:
        return self.exit_code != 0 or self.timed_out or self.provider_error


def _assistant_text(message: dict[str, Any]) -> str:
    content = message.get("content") or []
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    return "".join(parts).strip()


def _usage_from(message: dict[str, Any]) -> Usage:
    raw = message.get("usage") or {}
    cost = raw.get("cost") or {}
    return Usage(
        input_tokens=int(raw.get("input", 0) or 0),
        output_tokens=int(raw.get("output", 0) or 0),
        cache_read=int(raw.get("cacheRead", 0) or 0),
        cache_write=int(raw.get("cacheWrite", 0) or 0),
        reasoning=int(raw.get("reasoning", 0) or 0),
        total_tokens=int(raw.get("totalTokens", 0) or 0),
        cost_usd=float(cost.get("total", 0) or 0),
    )


def _has_usage(message: dict[str, Any]) -> bool:
    """True when Pi attached token counters to a message."""
    usage = message.get("usage")
    return isinstance(usage, dict) and any(
        key in usage for key in ("input", "output", "cacheRead", "totalTokens")
    )


def _add_usage(total: Usage, message: dict[str, Any]) -> None:
    usage = _usage_from(message)
    total.input_tokens += usage.input_tokens
    total.output_tokens += usage.output_tokens
    total.cache_read += usage.cache_read
    total.cache_write += usage.cache_write
    total.reasoning += usage.reasoning
    total.total_tokens += usage.total_tokens
    total.cost_usd += usage.cost_usd


def parse_events(events: Iterable[dict[str, Any]]) -> ParsedRun:
    """Parse a sequence of Pi JSON events into a :class:`ParsedRun`.

    Pi reports usage per assistant message, not per session, and repeats each
    message in both ``message_end`` and ``turn_end``. Usage is therefore summed
    from the ``message_end`` events only; the later events are used solely to
    identify the final message. Streams without per-message usage fall back to
    the final assistant message's counters.
    """
    parsed = ParsedRun()
    last_assistant: dict[str, Any] | None = None
    saw_message_usage = False

    for event in events:
        parsed.event_count += 1
        event_type = event.get("type")

        if event_type == "session" and parsed.session_id is None:
            parsed.session_id = event.get("id")

        if event_type == "tool_execution_end":
            parsed.tool_calls += 1
            if event.get("isError"):
                parsed.tool_errors += 1

        if event_type == "error":
            parsed.error_message = str(
                event.get("message") or event.get("error") or "provider error"
            )

        if event_type == "message_end":
            message = event.get("message") or {}
            if message.get("role") == "assistant":
                last_assistant = message
                if _has_usage(message):
                    _add_usage(parsed.usage, message)
                    saw_message_usage = True
        elif event_type == "turn_end":
            message = event.get("message") or {}
            if message.get("role") == "assistant":
                last_assistant = message
        elif event_type == "agent_end":
            for message in event.get("messages") or []:
                if message.get("role") == "assistant":
                    last_assistant = message

    if last_assistant is not None:
        parsed.final_message = _assistant_text(last_assistant)
        if not saw_message_usage:
            parsed.usage = _usage_from(last_assistant)
        parsed.stop_reason = last_assistant.get("stopReason")
        message_error = last_assistant.get("errorMessage")
        if message_error and not parsed.error_message:
            parsed.error_message = str(message_error)

    return parsed


def parse_json_lines(lines: Iterable[str]) -> ParsedRun:
    events: list[dict[str, Any]] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return parse_events(events)


def generation_seconds(timed_lines: Iterable[tuple[float, str]]) -> float:
    """Seconds Pi spent generating assistant messages, excluding tool execution.

    Pi timestamps nothing in its JSONL, so ``timed_lines`` pairs each raw line with the
    monotonic time AIDW read it (the same read that feeds the progress indicator). A
    message's window opens at its first streamed update — the first token — and closes at
    ``message_end``; the prefill gap before it and every tool call after it fall outside.
    Only messages that reported output tokens contribute, so the total covers exactly the
    tokens the numerator counts.
    """
    total = 0.0
    opened: float | None = None
    for at, raw in timed_lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "message_update":
            if opened is None:
                opened = at
        elif kind == "message_end":
            message = event.get("message") or {}
            if message.get("role") == "assistant":
                usage = message.get("usage") or {}
                if opened is not None and int(usage.get("output", 0) or 0) > 0:
                    total += max(0.0, at - opened)
            opened = None
    return round(total, 3)


def is_transient(stderr: str, exit_code: int) -> bool:
    if exit_code == 0:
        return False
    lowered = stderr.lower()
    return any(pattern in lowered for pattern in TRANSIENT_PATTERNS)


def _kill_group(proc: subprocess.Popen[str]) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()


def _invoke(
    argv: list[str],
    prompt: str,
    *,
    env: dict[str, str],
    cwd: Path,
    timeout: float,
    progress: ProgressIndicator | None = None,
    arrivals: list[float] | None = None,
) -> tuple[int, str, str, bool]:
    """Run Pi, streaming stdout through ``progress`` and capturing everything else.

    Pi writes one JSON event per line as it works, so reading stdout incrementally is
    what makes the progress indicator live. The prompt is written and stderr drained on
    worker threads so a chatty process cannot deadlock a pipe, and a watchdog timer
    enforces the wall-clock timeout.

    When ``arrivals`` is given, each stdout line's monotonic read time is appended to it,
    in line order. Pi timestamps nothing itself, so these are the only clock the caller
    has for measuring generation speed (see :func:`generation_seconds`).
    """
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(cwd),
        env=env,
        start_new_session=True,
    )
    stdout_lines: list[str] = []
    stderr_chunks: list[str] = []
    timed_out = False

    def write_prompt() -> None:
        if proc.stdin is None:
            return
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass

    def read_stderr() -> None:
        if proc.stderr is None:
            return
        try:
            stderr_chunks.append(proc.stderr.read())
        except (OSError, ValueError):
            pass

    def on_timeout() -> None:
        nonlocal timed_out
        timed_out = True
        _kill_group(proc)

    writer = threading.Thread(target=write_prompt, daemon=True)
    err_reader = threading.Thread(target=read_stderr, daemon=True)
    watchdog = threading.Timer(timeout, on_timeout)
    writer.start()
    err_reader.start()
    watchdog.start()
    try:
        if proc.stdout is not None:
            for line in proc.stdout:
                stdout_lines.append(line)
                if arrivals is not None:
                    arrivals.append(time.monotonic())
                if progress is not None:
                    progress.feed(line)
    finally:
        watchdog.cancel()
    proc.wait()
    writer.join(timeout=5.0)
    err_reader.join(timeout=5.0)
    return (
        proc.returncode or 0,
        "".join(stdout_lines),
        "".join(stderr_chunks),
        timed_out,
    )


def execute(
    argv: list[str],
    prompt: str,
    *,
    env: dict[str, str],
    cwd: Path,
    timeout: float,
    stage_dir: Path,
    stage_name: str,
    logger: RunLogger,
    retry_transient: bool = True,
    progress: ProgressIndicator | None = None,
) -> PiResult:
    """Run Pi, capture its JSONL transcript, and parse the final message."""
    stage_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = stage_dir / f"{stage_name}.jsonl"
    out_path = stage_dir / f"{stage_name}.out.txt"

    attempts = 0
    max_attempts = 2 if retry_transient else 1
    start = time.monotonic()

    while True:
        attempts += 1
        arrivals: list[float] = []
        exit_code, stdout, stderr, timed_out = _invoke(
            argv,
            prompt,
            env=env,
            cwd=cwd,
            timeout=timeout,
            progress=progress,
            arrivals=arrivals,
        )
        jsonl_path.write_text(stdout, encoding="utf-8")

        if (
            retry_transient
            and attempts < max_attempts
            and not timed_out
            and is_transient(stderr, exit_code)
        ):
            logger.warn(
                f"transient Pi failure (exit {exit_code}); retrying once"
            )
            time.sleep(2)
            continue
        break

    duration = round(time.monotonic() - start, 3)
    lines = stdout.splitlines()
    parsed = parse_json_lines(lines)
    # Generation time comes from when AIDW read each event, not from Pi (it timestamps
    # nothing), so prefill and tool execution are excluded. ``arrivals`` belongs to the
    # last attempt: a retry overwrites the transcript, which is accepted.
    generation = generation_seconds(zip(arrivals, lines)) or None
    if parsed.final_message:
        out_path.write_text(parsed.final_message + "\n", encoding="utf-8")
        final_out: str | None = str(out_path)
    else:
        final_out = None

    if timed_out:
        logger.error(f"Pi timed out after {timeout}s")
    elif parsed.error_message:
        logger.error(f"Pi provider error: {parsed.error_message[:300]}")
    elif exit_code != 0:
        logger.error(f"Pi exited {exit_code}: {stderr.strip()[:300]}")
    else:
        logger.info(
            f"Pi finished in {duration}s "
            f"({parsed.event_count} events, {parsed.tool_calls} tool calls, "
            f"cost ${parsed.usage.cost_usd:.4f})"
        )

    return PiResult(
        exit_code=exit_code,
        session_id=parsed.session_id,
        final_message=parsed.final_message,
        usage=parsed.usage,
        duration_seconds=duration,
        event_count=parsed.event_count,
        tool_calls=parsed.tool_calls,
        tool_errors=parsed.tool_errors,
        stop_reason=parsed.stop_reason,
        stderr=stderr,
        timed_out=timed_out,
        attempts=attempts,
        jsonl_path=str(jsonl_path),
        out_path=final_out,
        error_message=parsed.error_message,
        generation_seconds=generation,
    )


def write_meta(
    path: Path,
    result: PiResult,
    argv: list[str],
    *,
    model: str,
    stage: str | None = None,
    agent: str | None = None,
    prompt_source: str | None = None,
    rendered_prompt: str | None = None,
) -> None:
    """Write stage metadata (argv, model, usage, prompt provenance) next to the JSONL.

    ``prompt_source`` is the prompt file the stage was rendered from, so the metadata
    answers "which prompt did this stage actually use?" without consulting
    ``state.json`` or the run's rendered copy.
    """
    meta = {
        "stage": stage,
        "agent": agent,
        "argv": argv,
        "model": model,
        "prompt_source": prompt_source,
        "rendered_prompt": rendered_prompt,
        "exit_code": result.exit_code,
        "session_id": result.session_id,
        "duration_seconds": result.duration_seconds,
        "attempts": result.attempts,
        "timed_out": result.timed_out,
        "stop_reason": result.stop_reason,
        "error_message": result.error_message,
        "provider_error": result.provider_error,
        "tool_calls": result.tool_calls,
        "tool_errors": result.tool_errors,
        "event_count": result.event_count,
        "generation_seconds": result.generation_seconds,
        "output_tokens_per_second": result.output_tokens_per_second,
        "usage": asdict(result.usage),
    }
    path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
