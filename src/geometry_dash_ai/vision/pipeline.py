"""Pure observe-only composition of capture, visual detection, tracking, and geometry."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic_ns

from geometry_dash_ai.capture.models import CapturedFrame
from geometry_dash_ai.physics.geometry import LocalGeometry
from geometry_dash_ai.tracking.geometry import GeometryFuser
from geometry_dash_ai.tracking.player import PlayerTracker, TrackedPlayer
from geometry_dash_ai.tracking.scroll import ScrollEstimate, ScrollEstimator
from geometry_dash_ai.vision.coordinates import local_geometry_from_screen
from geometry_dash_ai.vision.geometry import ClassicalGeometryDetector
from geometry_dash_ai.vision.models import GeometryDetection, PlayerDetection
from geometry_dash_ai.vision.player import ClassicalPlayerDetector


@dataclass(frozen=True, slots=True)
class PerceptionMetrics:
    processing_fps: float
    processing_latency_ms: float
    maximum_recent_latency_ms: float
    processed_frames: int


@dataclass(frozen=True, slots=True)
class PerceptionSnapshot:
    frame: CapturedFrame
    raw_player: PlayerDetection | None
    tracked_player: TrackedPlayer
    raw_geometry: GeometryDetection
    fused_geometry: GeometryDetection
    local_geometry: LocalGeometry | None
    scroll: ScrollEstimate
    perception_unreliable: bool
    metrics: PerceptionMetrics


class PerceptionPipeline:
    """Latest-frame friendly pipeline with no control imports or action side effects."""

    def __init__(
        self,
        player_detector: ClassicalPlayerDetector,
        geometry_detector: ClassicalGeometryDetector,
        tracker: PlayerTracker,
        geometry_fuser: GeometryFuser,
        scroll_estimator: ScrollEstimator,
        minimum_confidence: float = 0.35,
        maximum_geometry_items: int = 128,
    ) -> None:
        if not 0.0 <= minimum_confidence <= 1.0 or not 1 <= maximum_geometry_items <= 256:
            raise ValueError("perception pipeline configuration is invalid")
        self._player_detector = player_detector
        self._geometry_detector = geometry_detector
        self._tracker = tracker
        self._fuser = geometry_fuser
        self._scroll = scroll_estimator
        self._minimum_confidence = minimum_confidence
        self._maximum_geometry_items = maximum_geometry_items
        self._last_processed_ns: int | None = None
        self._maximum_latency_ms = 0.0
        self._processed = 0

    def process(self, frame: CapturedFrame) -> PerceptionSnapshot:
        start_ns = monotonic_ns()
        player = self._player_detector.detect(frame, self._tracker.predicted_bounds)
        raw_geometry = self._geometry_detector.detect(frame, player)
        tracked = self._tracker.update(frame, player)
        fused = self._fuser.update(raw_geometry)
        scroll = self._scroll.update(fused, frame.timestamp_ns)
        local = None
        if tracked.bounds is not None:
            local = local_geometry_from_screen(tracked, fused, self._maximum_geometry_items)
        latency_ms = (monotonic_ns() - start_ns) / 1_000_000.0
        self._maximum_latency_ms = max(self._maximum_latency_ms, latency_ms)
        self._processed += 1
        processing_fps = 0.0
        if self._last_processed_ns is not None and start_ns > self._last_processed_ns:
            processing_fps = 1_000_000_000.0 / (start_ns - self._last_processed_ns)
        self._last_processed_ns = start_ns
        metrics = PerceptionMetrics(
            processing_fps, latency_ms, self._maximum_latency_ms, self._processed
        )
        unreliable = (
            tracked.bounds is None
            or tracked.confidence < self._minimum_confidence
            or tracked.lost_seconds > self._tracker.maximum_missing_seconds
            or fused.confidence < self._minimum_confidence
        )
        return PerceptionSnapshot(
            frame, player, tracked, raw_geometry, fused, local, scroll, unreliable, metrics
        )
