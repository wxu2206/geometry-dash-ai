"""Bounded ship dynamics independent from cube physics."""

from __future__ import annotations

from dataclasses import dataclass
from math import inf

from geometry_dash_ai.physics.geometry import (
    AABB,
    LocalGeometry,
    conservative_spike_clearance,
    require_finite,
    require_positive,
    spike_intersects_aabb,
)

MAX_SHIP_STEPS = 240


@dataclass(frozen=True, slots=True)
class ShipState:
    x: float
    y: float
    vx: float
    vy: float
    width: float
    height: float
    held: bool
    confidence: float = 1.0

    def __post_init__(self) -> None:
        for name in ("x", "y", "vx", "vy", "confidence"):
            require_finite(f"ShipState.{name}", getattr(self, name))
        require_positive("ShipState.width", self.width)
        require_positive("ShipState.height", self.height)
        if not isinstance(self.held, bool) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("ship held/confidence is invalid")

    @property
    def bounds(self) -> AABB:
        return AABB(self.x, self.y, self.width, self.height)


@dataclass(frozen=True, slots=True)
class ShipPhysicsParameters:
    held_acceleration: float = 760.0
    released_acceleration: float = -620.0
    maximum_up_velocity: float = 260.0
    maximum_down_velocity: float = -260.0
    response_latency_seconds: float = 0.035
    time_step: float = 1.0 / 60.0
    horizon_seconds: float = 0.6

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            require_finite(f"ShipPhysicsParameters.{name}", value)
        if self.held_acceleration <= 0 or self.released_acceleration >= 0:
            raise ValueError("ship accelerations must point in opposite directions")
        if self.maximum_up_velocity <= 0 or self.maximum_down_velocity >= 0:
            raise ValueError("ship velocity limits are invalid")
        if not 0.0 <= self.response_latency_seconds <= 0.25:
            raise ValueError("ship response latency is outside bounds")
        if not 1e-3 <= self.time_step <= 0.05 or not 0.05 <= self.horizon_seconds <= 2.0:
            raise ValueError("ship time step or horizon is outside bounds")


@dataclass(frozen=True, slots=True)
class ShipTrajectory:
    samples: tuple[ShipState, ...]
    survived: bool
    collision_kind: str | None
    minimum_clearance: float


def simulate_ship_trajectory(
    initial: ShipState,
    geometry: LocalGeometry,
    parameters: ShipPhysicsParameters,
    actions: tuple[bool, ...],
    segment_steps: int,
) -> ShipTrajectory:
    """Simulate a bounded held/released sequence and stop on first collision."""
    if not actions or len(actions) > 8:
        raise ValueError("ship action sequence must contain 1..8 segments")
    if isinstance(segment_steps, bool) or not 1 <= segment_steps <= 30:
        raise ValueError("ship segment length must be within 1..30 steps")
    if len(actions) * segment_steps > MAX_SHIP_STEPS:
        raise ValueError("ship trajectory exceeds bounded step count")
    if not isinstance(geometry, LocalGeometry):
        raise ValueError("ship geometry is invalid")
    state = initial
    samples = [state]
    minimum_clearance = inf
    for held in actions:
        if not isinstance(held, bool):
            raise ValueError("ship actions must be booleans")
        for _ in range(segment_steps):
            acceleration = (
                parameters.held_acceleration if held else parameters.released_acceleration
            )
            vy = max(
                parameters.maximum_down_velocity,
                min(parameters.maximum_up_velocity, state.vy + acceleration * parameters.time_step),
            )
            state = ShipState(
                state.x + state.vx * parameters.time_step,
                state.y + vy * parameters.time_step,
                state.vx,
                vy,
                state.width,
                state.height,
                held,
                state.confidence,
            )
            samples.append(state)
            collision, clearance = _collision(state.bounds, geometry)
            minimum_clearance = min(minimum_clearance, clearance)
            if collision is not None:
                return ShipTrajectory(tuple(samples), False, collision, max(0.0, minimum_clearance))
    return ShipTrajectory(
        tuple(samples), True, None, 10_000.0 if minimum_clearance == inf else minimum_clearance
    )


def _collision(bounds: AABB, geometry: LocalGeometry) -> tuple[str | None, float]:
    distances: list[float] = []
    for floor in geometry.floors:
        if bounds.right > floor.start_x and bounds.x < floor.end_x:
            distance = bounds.y - floor.height
            if distance <= 0:
                return "floor", 0.0
            distances.append(distance)
    for solid in geometry.solids:
        if bounds.overlaps(solid.bounds):
            return "solid", 0.0
        dx = max(bounds.x - solid.bounds.right, solid.bounds.x - bounds.right, 0.0)
        dy = max(bounds.y - solid.bounds.top, solid.bounds.y - bounds.top, 0.0)
        distances.append((dx * dx + dy * dy) ** 0.5)
    for spike in geometry.spikes:
        if spike_intersects_aabb(spike, bounds):
            return "spike", 0.0
        distances.append(conservative_spike_clearance(spike, bounds))
    if bounds.y <= geometry.death_y:
        return "floor", 0.0
    return None, min(distances, default=10_000.0)
