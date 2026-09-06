"""Visual run-state and conservative death/reset observation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from geometry_dash_ai.capture.models import CapturedFrame
from geometry_dash_ai.vision.models import PlayerMode
from geometry_dash_ai.vision.pipeline import PerceptionSnapshot


class RunPhase(StrEnum):
    WAITING = "waiting"
    STARTING = "starting"
    ACTIVE = "active"
    DEAD = "dead"
    RESETTING = "resetting"
    COMPLETE = "complete"
    UNKNOWN = "unknown"


class DeathCause(StrEnum):
    SPIKE = "spike"
    GAP = "gap"
    SOLID_SIDE = "solid_side"
    CEILING = "ceiling"
    FLOOR = "floor"
    SHIP_OBSTACLE = "ship_obstacle"
    PERCEPTION_FAILURE = "perception_failure"
    MODE_ERROR = "mode_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RunObservation:
    phase: RunPhase
    confidence: float
    death_cause: DeathCause | None = None
    last_safe_frame: int | None = None


class VisualRunStateObserver:
    """Require temporal evidence; one missed player frame is never a death."""

    def __init__(self) -> None:
        self._phase = RunPhase.WAITING
        self._visible_frames = 0
        self._missing_frames = 0
        self._last_safe_frame: int | None = None

    def reset_for_retry(self) -> None:
        """Forget the prior death while waiting for visual restart evidence."""
        self._phase = RunPhase.WAITING
        self._visible_frames = 0
        self._missing_frames = 0

    def update(
        self, snapshot: PerceptionSnapshot, *, completion_visual_cue: bool = False
    ) -> RunObservation:
        visible = snapshot.raw_player is not None and snapshot.tracked_player.confidence >= 0.35
        if completion_visual_cue and self._phase is RunPhase.ACTIVE:
            self._phase = RunPhase.COMPLETE
            return RunObservation(self._phase, 0.9, last_safe_frame=self._last_safe_frame)
        if visible:
            self._visible_frames += 1
            self._missing_frames = 0
            self._last_safe_frame = snapshot.frame.sequence
            if self._phase is RunPhase.DEAD:
                self._phase = RunPhase.RESETTING
                return RunObservation(self._phase, 0.7, last_safe_frame=self._last_safe_frame)
            self._phase = RunPhase.ACTIVE if self._visible_frames >= 2 else RunPhase.STARTING
            return RunObservation(self._phase, min(1.0, snapshot.tracked_player.confidence))
        self._visible_frames = 0
        self._missing_frames += 1
        enough_loss = self._missing_frames >= 3 and snapshot.tracked_player.lost_seconds >= 0.25
        scroll_stopped = abs(snapshot.scroll.speed_px_s) < 5.0
        if enough_loss and scroll_stopped and self._last_safe_frame is not None:
            self._phase = RunPhase.DEAD
            confidence = min(0.95, 0.55 + snapshot.tracked_player.lost_seconds)
            return RunObservation(
                self._phase,
                confidence,
                _attribute_death(snapshot),
                self._last_safe_frame,
            )
        self._phase = RunPhase.UNKNOWN if self._last_safe_frame is not None else RunPhase.WAITING
        return RunObservation(self._phase, 0.25, last_safe_frame=self._last_safe_frame)


def detect_completion_visual_cue(frame: CapturedFrame) -> bool:
    """Detect a conservative bright-green completion panel cue from pixels only."""
    rgb = frame.image[:, :, :3]
    height, width, _ = rgb.shape
    if height < 20 or width < 40:
        return False
    panel = rgb[: max(10, height // 3), width // 4 : width * 3 // 4]
    green = (
        (panel[:, :, 1] >= 170)
        & (panel[:, :, 1].astype(np.int16) - panel[:, :, 0].astype(np.int16) >= 50)
        & (panel[:, :, 1].astype(np.int16) - panel[:, :, 2].astype(np.int16) >= 20)
    )
    return float(green.mean()) >= 0.15


def _attribute_death(snapshot: PerceptionSnapshot) -> DeathCause:
    player = snapshot.tracked_player
    geometry = snapshot.local_geometry
    if player.mode is PlayerMode.UNKNOWN:
        return DeathCause.MODE_ERROR
    if geometry is None or player.bounds is None or snapshot.fused_geometry.confidence < 0.35:
        return DeathCause.PERCEPTION_FAILURE
    width = player.bounds.width
    height = player.bounds.height
    spike_contact = any(
        spike.x < width
        and spike.x + spike.width > 0.0
        and spike.base_y < height
        and spike.base_y + spike.height > 0.0
        for spike in geometry.spikes
    )
    solid_contact = any(
        solid.bounds.x < width
        and solid.bounds.right > 0.0
        and solid.bounds.y < height
        and solid.bounds.top > 0.0
        for solid in geometry.solids
    )
    if player.mode is PlayerMode.SHIP and (spike_contact or solid_contact):
        return DeathCause.SHIP_OBSTACLE
    if spike_contact:
        return DeathCause.SPIKE
    if solid_contact:
        return DeathCause.SOLID_SIDE
    supported = any(
        floor.start_x < width and floor.end_x > 0.0 and abs(floor.height) <= height * 0.5
        for floor in geometry.floors
    )
    return DeathCause.UNKNOWN if supported else DeathCause.GAP
