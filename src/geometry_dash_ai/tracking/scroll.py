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

    def __init__(self, maximum_displacement_px: float = 256.0) -> None:
        if (
            isinstance(maximum_displacement_px, bool)
            or not isinstance(maximum_displacement_px, (int, float))
            or not isfinite(maximum_displacement_px)
            or not 1.0 <= maximum_displacement_px <= 4_096.0
        ):
            raise ValueError("maximum scroll displacement is invalid")
        self._maximum_displacement_px = float(maximum_displacement_px)
        self._previous: tuple[tuple[tuple[str, ScreenBox], ...], int] | None = None

    def update(self, geometry: GeometryDetection, timestamp_ns: int) -> ScrollEstimate:
        if not isinstance(geometry, GeometryDetection):
            raise ValueError("scroll geometry is invalid")
        if (
            isinstance(timestamp_ns, bool)
            or not isinstance(timestamp_ns, int)
            or not 0 <= timestamp_ns <= 2**63 - 1
        ):
            raise ValueError("scroll timestamp is invalid")
        anchors = tuple(
            [("solid", box) for box in geometry.solids]
            + [("floor", box) for box in geometry.floors]
        )
        previous = self._previous
        self._previous = (anchors, timestamp_ns)
        if previous is None or timestamp_ns <= previous[1] or not anchors or not previous[0]:
            return ScrollEstimate(0.0, 0.0, 0.0, timestamp_ns)
        old, old_time = previous
        differences = _matching_displacements(
            old,
            anchors,
            self._maximum_displacement_px,
        )
        if not differences:
            return ScrollEstimate(0.0, 0.0, 0.0, timestamp_ns)
        scene_dx = float(median(differences))
        elapsed = (timestamp_ns - old_time) / 1_000_000_000.0
        confidence = min(1.0, len(differences) / 3.0) * geometry.confidence
        return ScrollEstimate(scene_dx, scene_dx / elapsed, confidence, timestamp_ns)


def _matching_displacements(
    previous: tuple[tuple[str, ScreenBox], ...],
    current: tuple[tuple[str, ScreenBox], ...],
    maximum_displacement_px: float,
) -> tuple[float, ...]:
    """Match a bounded set of same-kind anchors without relying on list order.

    Screen-edge entry/exit regularly changes component ordering. Greedy nearest
    one-to-one matching is sufficient for the small local map and, unlike index
    matching, refuses a new distant object as evidence of a huge scroll jump.
    """
    unmatched = set(range(min(len(previous), 64)))
    displacements: list[float] = []
    for kind, candidate in current[:64]:
        choices = (
            (abs(candidate.x - prior.x), index, prior)
            for index in unmatched
            for previous_kind, prior in (previous[index],)
            if previous_kind == kind and _similar_anchor(candidate, prior)
        )
        match = min(choices, default=None, key=lambda value: (value[0], value[1]))
        if match is None or match[0] > maximum_displacement_px:
            continue
        _, index, prior = match
        unmatched.remove(index)
        displacements.append(candidate.x - prior.x)
    return tuple(displacements)


def _similar_anchor(current: ScreenBox, previous: ScreenBox) -> bool:
    """Reject matches whose vertical placement or scale changed implausibly."""
    vertical_limit = max(8.0, max(current.height, previous.height) * 0.5)
    if abs(current.y - previous.y) > vertical_limit:
        return False
    width_ratio = current.width / previous.width
    height_ratio = current.height / previous.height
    return 0.5 <= width_ratio <= 2.0 and 0.5 <= height_ratio <= 2.0
