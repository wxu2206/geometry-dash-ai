"""Constrained local-only storage for explicit shadow-planner telemetry."""

from __future__ import annotations

from pathlib import Path

from geometry_dash_ai.telemetry.events import JsonlTelemetryWriter, TelemetryEvent


class ShadowTelemetryWriter:
    """A telemetry context manager restricted to this project's ignored data/runs."""

    def __init__(self, requested: Path) -> None:
        root = Path.cwd().resolve()
        runs = (root / "data" / "runs").resolve()
        if requested.is_absolute():
            raise ValueError("shadow telemetry path must be relative to data/runs")
        destination = (runs / requested).resolve()
        if runs not in destination.parents or destination == runs:
            raise ValueError("shadow telemetry must remain under data/runs")
        if destination.suffix not in {".jsonl", ".gz"}:
            raise ValueError("shadow telemetry must use a .jsonl or .gz suffix")
        if (
            any(part.is_symlink() for part in (runs, *destination.parents))
            or destination.is_symlink()
        ):
            raise ValueError("refusing to write shadow telemetry through a symlink")
        self.path = destination
        self._writer = JsonlTelemetryWriter(destination)

    def __enter__(self) -> ShadowTelemetryWriter:
        self._writer.__enter__()
        return self

    def write(self, event: TelemetryEvent) -> None:
        self._writer.write(event)

    def __exit__(self, *args: object) -> None:
        self._writer.__exit__(None, None, None)
