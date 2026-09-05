"""Timestamp-driven player tracking with bounded velocity and mode smoothing."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import isfinite

from geometry_dash_ai.capture.models import CapturedFrame
from geometry_dash_ai.vision.models import PlayerDetection, PlayerMode, ScreenBox


@dataclass(frozen=True, slots=True)
class TrackedPlayer:
    bounds: ScreenBox | None
    vx: float
    vy: float
    mode: PlayerMode
    confidence: float
    lost_seconds: float
    frame_index: int
    timestamp_ns: int

    def __post_init__(self) -> None:
        if self.bounds is not None and not isinstance(self.bounds, ScreenBox):
            raise ValueError("tracked bounds are invalid")
        if not isinstance(self.mode, PlayerMode):
            raise ValueError("tracked player mode is invalid")
        for name in ("vx", "vy", "confidence", "lost_seconds"):
            value = getattr(self, name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(value)
            ):
                raise ValueError(f"tracked {name} must be finite")
        if not 0.0 <= self.confidence <= 1.0 or self.lost_seconds < 0.0:
            raise ValueError("tracked confidence/lost duration is invalid")


class PlayerTracker:
    """Filters detections without letting one missed or bad frame create huge velocity."""

    def __init__(
        self,
        maximum_velocity_px_s: float = 5_000.0,
        mode_history_frames: int = 5,
        maximum_missing_seconds: float = 0.5,
    ) -> None:
        if (
            isinstance(maximum_velocity_px_s, bool)
            or
            not isinstance(maximum_velocity_px_s, (int, float))
            or not 1.0 <= maximum_velocity_px_s <= 100_000
        ):
            raise ValueError("maximum velocity is invalid")
        if (
            isinstance(mode_history_frames, bool)
            or not isinstance(mode_history_frames, int)
            or not 1 <= mode_history_frames <= 30
        ):
            raise ValueError("mode history must be in [1, 30]")
        if (
            not isinstance(maximum_missing_seconds, (int, float))
            or isinstance(maximum_missing_seconds, bool)
            or not 0.01 <= maximum_missing_seconds <= 10.0
        ):
            raise ValueError("maximum missing duration is invalid")
        self._maximum_velocity = float(maximum_velocity_px_s)
        self._maximum_missing_seconds = float(maximum_missing_seconds)
        self._mode_history: deque[tuple[PlayerMode, float]] = deque(maxlen=mode_history_frames)
        self._previous: TrackedPlayer | None = None
        self._last_mode = PlayerMode.UNKNOWN

    @property
    def maximum_missing_seconds(self) -> float:
        return self._maximum_missing_seconds

    def update(self, frame: CapturedFrame, detection: PlayerDetection | None) -> TrackedPlayer:
        if detection is not None and not isinstance(detection, PlayerDetection):
            raise ValueError("tracker detection is invalid")
        if detection is not None and (
            detection.timestamp_ns != frame.timestamp_ns or detection.frame_index != frame.sequence
        ):
            raise ValueError("detection metadata does not match frame")
        previous = self._previous
        if previous is not None and frame.timestamp_ns <= previous.timestamp_ns:
            raise ValueError("frame timestamps must increase for tracking")
        delta_seconds = (
            0.0
            if previous is None
            else (frame.timestamp_ns - previous.timestamp_ns) / 1_000_000_000.0
        )
        if detection is None:
            tracked = self._missing(frame, previous, delta_seconds)
        else:
            tracked = self._detected(detection, previous, delta_seconds)
        self._previous = tracked
        return tracked

    def _detected(
        self, detection: PlayerDetection, previous: TrackedPlayer | None, delta_seconds: float
    ) -> TrackedPlayer:
        self._mode_history.append((detection.mode, detection.confidence))
        mode, mode_confidence = self._smoothed_mode()
        vx = vy = 0.0
        if previous is not None and previous.bounds is not None and delta_seconds > 0.0:
            prior_x, prior_y = previous.bounds.center
            current_x, current_y = detection.bounds.center
            raw_vx = (current_x - prior_x) / delta_seconds
            raw_vy = (current_y - prior_y) / delta_seconds
            vx = self._bounded_velocity(raw_vx, previous.vx)
            vy = self._bounded_velocity(raw_vy, previous.vy)
        confidence = min(1.0, 0.75 * detection.confidence + 0.25 * mode_confidence)
        return TrackedPlayer(
            detection.bounds,
            vx,
            vy,
            mode,
            confidence,
            0.0,
            detection.frame_index,
            detection.timestamp_ns,
        )

    def _missing(
        self, frame: CapturedFrame, previous: TrackedPlayer | None, delta_seconds: float
    ) -> TrackedPlayer:
        if previous is None:
            return TrackedPlayer(
                None, 0.0, 0.0, PlayerMode.UNKNOWN, 0.0, 0.0, frame.sequence, frame.timestamp_ns
            )
        lost = previous.lost_seconds + delta_seconds
        confidence = max(
            0.0,
            previous.confidence * (0.35 if lost > self._maximum_missing_seconds else 0.85),
        )
        mode = previous.mode if confidence >= 0.15 else PlayerMode.UNKNOWN
        return TrackedPlayer(
            previous.bounds,
            previous.vx * 0.8,
            previous.vy * 0.8,
            mode,
            confidence,
            lost,
            frame.sequence,
            frame.timestamp_ns,
        )

    def _bounded_velocity(self, raw: float, prior: float) -> float:
        if not isfinite(raw):
            return 0.0
        bounded = max(-self._maximum_velocity, min(self._maximum_velocity, raw))
        return 0.6 * bounded + 0.4 * prior

    def _smoothed_mode(self) -> tuple[PlayerMode, float]:
        scores = {mode: 0.0 for mode in PlayerMode}
        for mode, confidence in self._mode_history:
            scores[mode] += confidence
        mode = max(PlayerMode, key=lambda item: (scores[item], item.value))
        if (
            self._last_mode is not PlayerMode.UNKNOWN
            and scores[mode] <= scores[self._last_mode] * 1.1
        ):
            mode = self._last_mode
        total = sum(scores.values())
        self._last_mode = mode
        return mode, 0.0 if total == 0.0 else scores[mode] / total
