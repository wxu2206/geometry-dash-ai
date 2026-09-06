"""Bounded, local-only run summary history without captured pixels."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path

MAX_HISTORY_BYTES = 5 * 1024 * 1024
MAX_LOADED_RUNS = 500


@dataclass(frozen=True, slots=True)
class RunSummary:
    attempt: int
    started_ns: int
    ended_ns: int
    outcome: str
    mode: str
    estimated_death_cause: str | None
    prediction_confidence: float
    calibration_revision: int

    def __post_init__(self) -> None:
        if not 1 <= self.attempt <= 1_000_000:
            raise ValueError("run attempt is outside bounds")
        if self.started_ns < 0 or self.ended_ns < self.started_ns:
            raise ValueError("run timestamps are invalid")
        if self.outcome not in {"dead", "complete", "stopped"}:
            raise ValueError("run outcome is invalid")
        if self.mode not in {"cube", "ship", "unknown"}:
            raise ValueError("run mode is invalid")
        if not isfinite(self.prediction_confidence) or not 0.0 <= self.prediction_confidence <= 1.0:
            raise ValueError("prediction confidence is invalid")
        if not 0 <= self.calibration_revision <= 1_000_000:
            raise ValueError("calibration revision is invalid")


class RunHistoryStore:
    """Append compact summaries below ``data/runs`` and cap storage/read size."""

    def __init__(self, project_root: Path, maximum_bytes: int = MAX_HISTORY_BYTES) -> None:
        if not 4_096 <= maximum_bytes <= 100 * 1024 * 1024:
            raise ValueError("run-history storage bound is invalid")
        root = project_root.resolve()
        data = root / "data"
        lexical_runs = data / "runs"
        if data.is_symlink() or lexical_runs.is_symlink():
            raise ValueError("run history directory is unsafe")
        runs = lexical_runs.resolve()
        self.path = runs / "history.jsonl"
        if root not in runs.parents or runs.is_symlink() or self.path.is_symlink():
            raise ValueError("run history path is unsafe")
        self._maximum_bytes = maximum_bytes

    def append(self, summary: RunSummary) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise ValueError("refusing run history through a symlink")
        line = json.dumps(asdict(summary), separators=(",", ":"), sort_keys=True).encode() + b"\n"
        if len(line) > 8_192:
            raise ValueError("run summary is unexpectedly large")
        if self.path.exists() and self.path.stat().st_size + len(line) > self._maximum_bytes:
            self._compact()
        descriptor = os.open(
            self.path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
            0o600,
        )
        try:
            remaining = memoryview(line)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("run history write did not complete")
                remaining = remaining[written:]
        finally:
            os.close(descriptor)

    def recent(self, limit: int = 100) -> tuple[RunSummary, ...]:
        if not 1 <= limit <= MAX_LOADED_RUNS:
            raise ValueError("run history read limit is invalid")
        if not self.path.exists():
            return ()
        data = self.path.read_bytes()
        if len(data) > self._maximum_bytes:
            raise ValueError("run history exceeds its storage bound")
        summaries: list[RunSummary] = []
        for raw in data.splitlines()[-limit:]:
            try:
                decoded = json.loads(raw)
                if not isinstance(decoded, dict):
                    continue
                summaries.append(RunSummary(**decoded))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return tuple(summaries)

    def _compact(self) -> None:
        keep = self.path.read_bytes()[-(self._maximum_bytes // 2) :]
        first_newline = keep.find(b"\n")
        keep = b"" if first_newline < 0 else keep[first_newline + 1 :]
        descriptor = os.open(
            self.path,
            os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW,
            0o600,
        )
        try:
            remaining = memoryview(keep)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("run history compaction did not complete")
                remaining = remaining[written:]
        finally:
            os.close(descriptor)
