"""Displayable, testable application status and live-readiness components."""

from __future__ import annotations

from dataclasses import dataclass, fields

from geometry_dash_ai.vision.models import PlayerMode
from geometry_dash_ai.vision.pipeline import PerceptionSnapshot


@dataclass(frozen=True, slots=True)
class Readiness:
    capture: bool
    frame_fresh: bool
    player: bool
    mode: bool
    geometry: bool
    tracking: bool
    scroll: bool
    physics: bool
    planner: bool
    control: bool

    @property
    def ready(self) -> bool:
        return all(bool(getattr(self, field.name)) for field in fields(self))

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(field.name for field in fields(self) if not getattr(self, field.name))


def readiness_from_snapshot(
    snapshot: PerceptionSnapshot,
    now_ns: int,
    *,
    control_healthy: bool,
    physics_ready: bool,
    planner_healthy: bool,
    maximum_frame_age_ms: float = 100.0,
) -> Readiness:
    age_ns = now_ns - snapshot.frame.timestamp_ns
    player = snapshot.tracked_player
    return Readiness(
        capture=age_ns >= 0,
        frame_fresh=0 <= age_ns <= int(maximum_frame_age_ms * 1_000_000.0),
        player=player.bounds is not None and player.confidence >= 0.5,
        mode=player.mode in {PlayerMode.CUBE, PlayerMode.SHIP},
        geometry=snapshot.fused_geometry.confidence >= 0.35,
        tracking=player.lost_seconds <= 0.25 and player.lost_frames <= 2,
        scroll=abs(snapshot.scroll.speed_px_s) <= 10_000.0,
        physics=physics_ready,
        planner=planner_healthy,
        control=control_healthy,
    )


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    status: str
    capture_status: str
    control_status: str
    ai_mode: str
    game_mode: str
    attempt: int
    capture_fps: float
    perception_fps: float
    planner_hz: float
    latency_ms: float
    player_confidence: float
    geometry_confidence: float
    planner_confidence: float
    physics_ready: bool
    predicted_action: str
    risk: str
    last_error: str | None = None
