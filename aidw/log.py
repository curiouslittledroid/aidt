"""Run logging for AIDW (design §9.1).

Each run writes a single human-readable ``run.log`` under its run directory. Stage
JSONL transcripts and metadata are written by :mod:`aidw.pi`.
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime, timezone
from pathlib import Path


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RunLogger:
    """Append-only logger for one run, optionally echoing to the terminal."""

    #: Concurrent stages (design §8 ``--parallel``) append to one log file.
    _lock = threading.Lock()

    def __init__(self, run_dir: Path, *, stream: bool = False) -> None:
        self.run_dir = run_dir
        self.path = run_dir / "run.log"
        self.stream = stream
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def _write(self, level: str, message: str) -> None:
        line = f"{utcnow_iso()} [{level}] {message}"
        with RunLogger._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        if self.stream:
            print(line, file=sys.stderr, flush=True)

    def info(self, message: str) -> None:
        self._write("INFO", message)

    def warn(self, message: str) -> None:
        self._write("WARN", message)

    def error(self, message: str) -> None:
        self._write("ERROR", message)

    def section(self, title: str) -> None:
        self._write("----", title)
