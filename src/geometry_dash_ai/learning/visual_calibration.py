"""Bounded cube calibration collection from ordinary visual tracking."""

from __future__ import annotations

from collections import deque
from dataclasses import replace

from geometry_dash_ai.learning.calibration import (
    AirborneSample,
    CalibrationInvalid,
    CalibrationStore,
    CubePhysicsCalibrator,
    PhysicsCalibration,
)
from geometry_dash_ai.vision.models import PlayerMode
from geometry_dash_ai.vision.pipeline import PerceptionSnapshot


class VisualCubeCalibrationCollector:
    """Recognize manual jump arcs and fit them without observing input events."""

    def __init__(
        self,
        store: CalibrationStore,
        *,
        minimum_samples: int = 30,
        learning_rate: float = 0.05,
    ) -> None:
        self._store = store
        self._calibrator = CubePhysicsCalibrator(minimum_samples, learning_rate)
        self._samples: deque[AirborneSample] = deque(maxlen=240)
        self._scroll_speeds: deque[float] = deque(maxlen=240)
        self._started_ns: int | None = None
        self._ready = False
        if store.path.exists():
            try:
                current, known_good = store.load()
                self._calibrator.current = current
                self._calibrator.last_known_good = known_good
                self._ready = current.sample_count >= minimum_samples
            except CalibrationInvalid:
                self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def current(self) -> PhysicsCalibration:
        return self._calibrator.current

    def update(self, snapshot: PerceptionSnapshot) -> PhysicsCalibration | None:
        player = snapshot.tracked_player
        bounds = player.bounds
        usable = (
            bounds is not None
            and player.mode is PlayerMode.CUBE
            and player.confidence >= 0.6
            and player.lost_frames == 0
        )
        if not usable:
            self._reset_arc()
            return None
        assert bounds is not None
        timestamp = snapshot.frame.timestamp_ns
        if self._started_ns is None:
            if player.vy >= -40.0:
                return None
            self._started_ns = timestamp
            self._samples.clear()
            self._scroll_speeds.clear()
        elapsed = (timestamp - self._started_ns) / 1_000_000_000.0
        if elapsed < 0.0 or elapsed > 2.0:
            self._reset_arc()
            return None
        self._samples.append(AirborneSample(elapsed, -bounds.y, player.confidence))
        if abs(snapshot.scroll.speed_px_s) >= 20.0:
            self._scroll_speeds.append(abs(snapshot.scroll.speed_px_s))
        landed = elapsed >= 0.35 and abs(player.vy) <= 25.0
        if not landed:
            return None
        samples = tuple(self._samples)
        try:
            fitted = self._calibrator.fit_airborne(samples)
            horizontal_speed = fitted.horizontal_speed
            if self._scroll_speeds:
                ordered = sorted(self._scroll_speeds)
                horizontal_speed = ordered[len(ordered) // 2]
            fitted = replace(
                fitted,
                horizontal_speed=max(20.0, min(2_000.0, horizontal_speed)),
                collision_width=max(4.0, min(256.0, bounds.width)),
                collision_height=max(4.0, min(256.0, bounds.height)),
            )
            self._calibrator.current = fitted
            if fitted.uncertainty <= 0.25:
                self._calibrator.last_known_good = fitted
            self._store.save(fitted, self._calibrator.last_known_good)
            self._ready = True
            return fitted
        except CalibrationInvalid:
            return None
        finally:
            self._reset_arc()

    def _reset_arc(self) -> None:
        self._started_ns = None
        self._samples.clear()
        self._scroll_speeds.clear()
