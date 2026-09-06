"""Explicit conversion from image coordinates to Phase 2 player-relative geometry."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from geometry_dash_ai.physics.geometry import AABB, FloorSegment, LocalGeometry, SolidRect, Spike
from geometry_dash_ai.tracking.player import TrackedPlayer
from geometry_dash_ai.vision.models import GeometryDetection, ScreenBox


@dataclass(frozen=True, slots=True)
class CoordinateTransform:
    """Maps image pixels to planner pixels relative to the player's lower-left corner.

    Image origin is top-left with y down. Planner origin is the tracked player's
    lower-left corner with y up. One internal unit is one captured pixel until
    Phase 4 calibration establishes another scale.
    """

    player_bounds: ScreenBox

    def __post_init__(self) -> None:
        if not isinstance(self.player_bounds, ScreenBox):
            raise ValueError("coordinate transform requires player screen bounds")

    def point(self, screen_x: float, screen_y: float) -> tuple[float, float]:
        if not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and isfinite(value)
            for value in (screen_x, screen_y)
        ):
            raise ValueError("screen point must be finite")
        return (float(screen_x) - self.player_bounds.x, self.player_bounds.bottom - float(screen_y))

    def solid(self, box: ScreenBox, obstacle_id: str) -> SolidRect:
        x, top_y = self.point(box.x, box.y)
        _, bottom_y = self.point(box.x, box.bottom)
        return SolidRect(AABB(x, bottom_y, box.width, top_y - bottom_y), obstacle_id)

    def spike(self, box: ScreenBox, obstacle_id: str) -> Spike:
        x, base_y = self.point(box.x, box.bottom)
        return Spike(x, base_y, box.width, box.height, obstacle_id)

    def floor(self, box: ScreenBox, obstacle_id: str) -> FloorSegment:
        start_x, height = self.point(box.x, box.y)
        end_x, _ = self.point(box.right, box.y)
        return FloorSegment(start_x, end_x, height, obstacle_id)


def local_geometry_from_screen(
    tracked: TrackedPlayer, geometry: GeometryDetection, maximum_items: int = 128
) -> LocalGeometry:
    """Convert present visual detections to bounded planner-compatible local geometry."""
    if tracked.bounds is None:
        raise ValueError("cannot construct local geometry without a tracked player")
    if (
        isinstance(maximum_items, bool)
        or not isinstance(maximum_items, int)
        or not 1 <= maximum_items <= 256
    ):
        raise ValueError("maximum geometry items must be in [1, 256]")
    transform = CoordinateTransform(tracked.bounds)
    floors = tuple(
        transform.floor(box, f"vision-floor-{index}") for index, box in enumerate(geometry.floors)
    )
    solids = tuple(
        transform.solid(box, f"vision-solid-{index}") for index, box in enumerate(geometry.solids)
    )
    if geometry.ceiling is not None:
        solids += (transform.solid(geometry.ceiling, "vision-ceiling"),)
    spikes = tuple(
        transform.spike(box, f"vision-spike-{index}") for index, box in enumerate(geometry.spikes)
    )
    base_death_y = -max(48.0, tracked.bounds.height * 2.0)
    death_y = min((base_death_y, *(floor.height - 48.0 for floor in floors)))
    combined = LocalGeometry(
        floors=floors,
        solids=solids,
        spikes=spikes,
        death_y=death_y,
        uncertainty=min(1.0, 1.0 - min(tracked.confidence, geometry.confidence)),
    )
    return combined.nearest(0.0, maximum_items)
