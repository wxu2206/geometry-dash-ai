"""Observe-only live runtime. This module intentionally has no control dependency."""

from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from typing import Protocol

from geometry_dash_ai.capture.source import FrameSource, interval_seconds
from geometry_dash_ai.telemetry.frames import DiagnosticFrameBuffer
from geometry_dash_ai.ui.overlay import render_debug_overlay
from geometry_dash_ai.vision.pipeline import PerceptionPipeline, PerceptionSnapshot

OBSERVE_ONLY = True


class OverlayViewer(Protocol):
    def show(self, image: object, status: str) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ObservationRunMetrics:
    captured: int
    processed: int
    capture_fps: float
    dropped_frames: int


class ObserveOnlyRuntime:
    """Runs capture and perception serially with bounded state and zero input authority."""

    def __init__(
        self,
        source: FrameSource,
        pipeline: PerceptionPipeline,
        target_fps: float,
        recorder: DiagnosticFrameBuffer | None = None,
        viewer: OverlayViewer | None = None,
    ) -> None:
        self._source = source
        self._pipeline = pipeline
        self._interval = interval_seconds(target_fps)
        self._recorder = recorder
        self._viewer = viewer

    def run(
        self, maximum_frames: int | None = None
    ) -> tuple[ObservationRunMetrics, PerceptionSnapshot | None]:
        if maximum_frames is not None and (
            isinstance(maximum_frames, bool)
            or not isinstance(maximum_frames, int)
            or maximum_frames <= 0
        ):
            raise ValueError("maximum frame count must be positive")
        processed = 0
        latest: PerceptionSnapshot | None = None
        try:
            while maximum_frames is None or processed < maximum_frames:
                frame = self._source.capture_once()
                snapshot = self._pipeline.process(frame)
                if self._recorder is not None:
                    self._recorder.append(frame)
                if self._viewer is not None:
                    overlay = render_debug_overlay(
                        frame.image, snapshot.tracked_player.bounds, snapshot.fused_geometry
                    )
                    self._viewer.show(overlay, _status(snapshot, self._source.capture_fps))
                latest = snapshot
                processed += 1
                if maximum_frames is None or processed < maximum_frames:
                    sleep(self._interval)
        finally:
            self._source.close()
            if self._viewer is not None:
                self._viewer.close()
        return (
            ObservationRunMetrics(
                processed, processed, self._source.capture_fps, self._source.dropped_frames
            ),
            latest,
        )


def _status(snapshot: PerceptionSnapshot, capture_fps: float) -> str:
    player = snapshot.tracked_player
    return (
        "OBSERVE ONLY | "
        f"capture={capture_fps:.1f} fps perception={snapshot.metrics.processing_fps:.1f} fps "
        f"mode={player.mode.value} vx={player.vx:.1f} vy={player.vy:.1f} "
        f"confidence={player.confidence:.2f} scroll={snapshot.scroll.speed_px_s:.1f}"
    )
