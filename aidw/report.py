"""Human-readable reporting for stages and agent invocations (design §9, §14).

Workflows print one *stage block* per agent invocation: which stage ran, which model
answered, how much it cost, and where its output landed. The block is derived from the
stage record (and therefore from ``stages/<name>.meta.json``), so the live output and the
recorded evidence cannot drift apart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aidw.cost import is_unpriced, total_tokens
from aidw.state import (
    PLANNED,
    RUNNING,
    SKIP_REASON_KEY,
    SKIPPED,
    SUCCEEDED,
    StageRecord,
)

#: Field order for the one-line usage summary.
_USAGE_FIELDS = (
    ("total_tokens", "total"),
    ("input_tokens", "in"),
    ("output_tokens", "out"),
    ("cache_read", "cache_read"),
    ("cache_write", "cache_write"),
    ("reasoning", "reasoning"),
)


def short_count(value: int) -> str:
    """Compact token counts: ``50641`` -> ``50.6k``."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(value)


def usage_line(usage: dict[str, Any] | None) -> str:
    """One line of usage counters, or ``""`` when nothing was measured."""
    if not usage:
        return ""
    parts = [
        f"{label}={short_count(int(usage.get(key, 0) or 0))}"
        for key, label in _USAGE_FIELDS
    ]
    cost = float(usage.get("cost_usd", 0.0) or 0.0)
    parts.append(f"cost=${cost:.4f}")
    return " ".join(parts)


def throughput(record: StageRecord) -> str | None:
    """``"47.1 out-tok/s"`` for a stage, or ``None`` when it was not measured."""
    value = record.output_tokens_per_second
    if value is None:
        return None
    return f"{value:.1f} out-tok/s"


def timing_line(record: StageRecord) -> str:
    """``"ai=176.5s tools=183.2s"`` — stage wall time split by activity (design §9.2).

    ``tools`` is ``tool_seconds`` (time Pi spent executing tool calls). ``ai`` is the
    complement of the stage's ``duration_seconds``: model prefill, generation and
    provider wait, plus subprocess startup. The two terms therefore account for the whole
    stage, which is more useful than the narrower ``generation_seconds`` (streaming only,
    prefill excluded). When ``tool_seconds`` was not measured the tools term is omitted
    and ``ai`` falls back to ``generation_seconds``, so a record without either field
    yields an empty line rather than a fabricated split.
    """
    tools = record.tool_seconds
    parts = []
    if tools is not None and record.duration_seconds is not None:
        parts.append(f"ai={max(0.0, record.duration_seconds - tools):g}s")
    elif record.generation_seconds is not None:
        parts.append(f"ai={record.generation_seconds:g}s")
    if tools is not None:
        parts.append(f"tools={tools:g}s")
    return " ".join(parts)


def tool_breakdown_line(breakdown: dict[str, float] | None) -> str:
    """``"bash=95.2s read=60.1s edit=20s"`` — per-tool shares of stage tool time.

    Names arrive longest-first from :func:`aidw.pi.tool_breakdown`; the empty string is
    returned for a stage that made no tool calls, so a caller can skip the line.
    """
    if not breakdown:
        return ""
    return " ".join(f"{name}={seconds:g}s" for name, seconds in breakdown.items())


def cost_note(model: str, usage: dict[str, Any] | None) -> str | None:
    """Warn about token spend with no recorded cost (design §9.2).

    ``None`` when the stage was priced, measured nothing, or runs on a local provider,
    so the note appears only where a zero cost is suspicious rather than true.
    """
    if not is_unpriced(model, usage):
        return None
    return (
        f"{short_count(total_tokens(usage))} tokens with $0.0000 cost — {model} has no "
        'pricing; check models.json (a "models" entry replaces catalog pricing, a '
        '"modelOverrides" entry merges)'
    )


def empty_final_message_error(record: StageRecord) -> str:
    """Why a stage that exited cleanly with no final text fails the run (H1.1, §10).

    One rule for the three workflows that check it. A retried stage names its final
    attempt's ``stop_reason`` and states that **both** attempts were truncated, rather
    than the bare ``produced no final message`` that used to hide the retry; a single
    attempt says so, which is what ``--no-retry-transient`` produces. ``unknown`` stands
    in for a record (or a fake in a test) that predates the additive fields.
    """
    reason = record.stop_reason or "unknown"
    if record.attempts is not None and record.attempts > 1:
        return (
            f"{record.name}: both attempts produced no final message "
            f"(final stop_reason: {reason}); both attempts were truncated"
        )
    return (
        f"{record.name}: produced no final message "
        f"(stop_reason: {reason}, attempts: "
        f"{record.attempts if record.attempts is not None else 'unknown'})"
    )


def rel_to(base: Path | None, path: str | Path | None) -> str:
    """Render ``path`` relative to ``base`` when possible, else as-is."""
    if path is None:
        return ""
    if base is None:
        return str(path)
    try:
        return Path(path).resolve().relative_to(Path(base).resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def stage_lines(
    record: StageRecord,
    *,
    repo_root: Path | None = None,
    prefix: str = "",
) -> list[str]:
    """The report block for one finished stage.

    ``prefix`` carries the workflow's stage id (for example ``I2``) so the block keeps
    the existing ``stage:  <id> <name>`` shape.
    """
    name = f"{prefix} {record.name}".strip()
    head = f"stage:  {name} [{record.status}]"
    if record.model:
        head += f" model={record.model}"
    if record.duration_seconds is not None:
        head += f" {record.duration_seconds:g}s"
    if record.cost_usd:
        head += f" cost=${record.cost_usd:.4f}"
    speed = throughput(record)
    if speed:
        head += f" {speed}"

    lines = [head]

    if record.status == SKIPPED:
        # H3.2: a withheld stage carries its reason in ``artifacts``, never in ``error``
        # (which would render as a failure). The head already says ``[skipped]``, so the
        # operator sees the decision *and* what decided it without a transcript.
        reason = str(record.artifacts.get(SKIP_REASON_KEY) or "no reason recorded")
        lines.append(f"        skipped: {reason}")
    elif record.error:
        lines.append(f"        error: {record.error}")
    elif record.status in (SUCCEEDED, RUNNING) and usage_line(record.usage):
        lines.append(f"        usage: {usage_line(record.usage)}")

    note = cost_note(record.model, record.usage)
    if note and record.status != PLANNED:
        lines.append(f"        note:  {note}")

    out = record.artifacts.get("out")
    if out and record.status != PLANNED:
        lines.append(f"        out:   {rel_to(repo_root, out)}")

    return lines


def print_stage(
    record: StageRecord,
    *,
    repo_root: Path | None = None,
    prefix: str = "",
) -> None:
    for line in stage_lines(record, repo_root=repo_root, prefix=prefix):
        print(line)
