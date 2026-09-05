"""Small visual horizontal-scroll estimator independent of player motion."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import median

from geometry_dash_ai.vision.models import GeometryDetection, ScreenBox


@dataclass(frozen=True, slots=True)
class ScrollEstimate:
    scene_dx: float
    speed_px_s: float
    confidence: float
    timestamp_ns: int

    def __post_init__(self) -> None:
        for value in (self.scene_dx, self.speed_px_s, self.confidence):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(value)
            ):
                raise ValueError("scroll estimate must be finite")
        if not 0.0 <= self.confidence <= 1.0 or self.timestamp_ns < 0:
            raise ValueError("scroll estimate confidence/timestamp is invalid")


class ScrollEstimator:
    """Uses stable geometry anchors; it intentionally never infers scroll from the player."""

    def __init__(self) -> None:
        self._previous: tuple[tuple[ScreenBox, ...], int] | None = None

    def update(self, geometry: GeometryDetection, timestamp_ns: int) -> ScrollEstimate:
        if (
            isinstance(timestamp_ns, bool)
            or not isinstance(timestamp_ns, int)
            or not 0 <= timestamp_ns <= 2**63 - 1
        ):
            raise ValueError("scroll timestamp is invalid")
        anchors = (*geometry.solids, *geometry.floors)
        previous = self._previous
        self._previous = (anchors, timestamp_ns)
        if previous is None or timestamp_ns <= previous[1] or not anchors or not previous[0]:
            return ScrollEstimate(0.0, 0.0, 0.0, timestamp_ns)
        old, old_time = previous
        count = min(len(old), len(anchors), 8)
        differences = [anchors[index].x - old[index].x for index in range(count)]
        scene_dx = float(median(differences))
        elapsed = (timestamp_ns - old_time) / 1_000_000_000.0
        confidence = min(1.0, count / 3.0) * geometry.confidence
        return ScrollEstimate(scene_dx, scene_dx / elapsed, confidence, timestamp_ns)
