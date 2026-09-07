"""Constrained local-only storage for explicit shadow-planner telemetry."""

from __future__ import annotations

from pathlib import Path

from geometry_dash_ai.telemetry.events import JsonlTelemetryWriter, TelemetryEvent

MAX_SHADOW_TELEMETRY_BYTES = 5 * 1024 * 1024


class ShadowTelemetryWriter:
    """A telemetry context manager restricted to this project's ignored data/runs."""

    def __init__(
        self,
        requested: Path,
        *,
        maximum_bytes: int = MAX_SHADOW_TELEMETRY_BYTES,
    ) -> None:
        if not 1_024 <= maximum_bytes <= MAX_SHADOW_TELEMETRY_BYTES:
            raise ValueError("shadow telemetry storage bound is invalid")
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
        self._maximum_bytes = maximum_bytes
        self._truncated = False
        self._writer = JsonlTelemetryWriter(destination)

    @property
    def truncated(self) -> bool:
        """Whether this explicit diagnostic log reached its physical size cap."""
        return self._truncated

    def __enter__(self) -> ShadowTelemetryWriter:
        self._writer.__enter__()
        return self

    def write(self, event: TelemetryEvent) -> None:
        if self._truncated:
            return
        if self.path.exists() and self.path.stat().st_size >= self._maximum_bytes:
            self._truncated = True
            return
        self._writer.write(event)

    def __exit__(self, *args: object) -> None:
        self._writer.__exit__(None, None, None)
