"""Bounded temporal fusion for stable screen-space geometry observations."""

from __future__ import annotations

from collections import deque

from geometry_dash_ai.vision.models import GeometryDetection, ScreenBox


class GeometryFuser:
    """Retains only a few matching prior observations and never grows over time."""

    def __init__(self, maximum_history_frames: int = 12) -> None:
        if (
            isinstance(maximum_history_frames, bool)
            or not isinstance(maximum_history_frames, int)
            or not 1 <= maximum_history_frames <= 120
        ):
            raise ValueError("geometry history must be in [1, 120]")
        self._history: deque[GeometryDetection] = deque(maxlen=maximum_history_frames)

    def update(self, observation: GeometryDetection) -> GeometryDetection:
        if not isinstance(observation, GeometryDetection):
            raise ValueError("geometry observation is invalid")
        prior = self._history[-1] if self._history else None
        self._history.append(observation)
        if prior is None:
            return observation
        floors = self._fuse_group(observation.floors, prior.floors)
        solids = self._fuse_group(observation.solids, prior.solids)
        spikes = self._fuse_group(observation.spikes, prior.spikes)
        confidence = min(1.0, observation.confidence + 0.1 if floors or solids or spikes else 0.0)
        return GeometryDetection(floors, solids, spikes, observation.ceiling, confidence)

    @property
    def cached_observations(self) -> int:
        return len(self._history)

    @staticmethod
    def _fuse_group(
        current: tuple[ScreenBox, ...], prior: tuple[ScreenBox, ...]
    ) -> tuple[ScreenBox, ...]:
        result: list[ScreenBox] = []
        for candidate in current[:256]:
            match = next((item for item in prior if _iou(candidate, item) >= 0.5), None)
            if match is None:
                result.append(candidate)
                continue
            result.append(
                ScreenBox(
                    0.75 * candidate.x + 0.25 * match.x,
                    0.75 * candidate.y + 0.25 * match.y,
                    0.75 * candidate.width + 0.25 * match.width,
                    0.75 * candidate.height + 0.25 * match.height,
                )
            )
        return tuple(result)


def _iou(first: ScreenBox, second: ScreenBox) -> float:
    left = max(first.x, second.x)
    top = max(first.y, second.y)
    right = min(first.right, second.right)
    bottom = min(first.bottom, second.bottom)
    overlap = max(0.0, right - left) * max(0.0, bottom - top)
    union = first.width * first.height + second.width * second.height - overlap
    return 0.0 if union <= 0.0 else overlap / union
