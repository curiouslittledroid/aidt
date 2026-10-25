"""Human-readable reporting for stages and agent invocations (design §9, §14).

Workflows print one *stage block* per agent invocation: which stage ran, which model
answered, how much it cost, and where its output landed. The block is derived from the
stage record (and therefore from ``stages/<name>.meta.json``), so the live output and the
recorded evidence cannot drift apart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aidw.state import PLANNED, RUNNING, SUCCEEDED, StageRecord

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

    lines = [head]

    if record.error:
        lines.append(f"        error: {record.error}")
    elif record.status in (SUCCEEDED, RUNNING) and usage_line(record.usage):
        lines.append(f"        usage: {usage_line(record.usage)}")

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
