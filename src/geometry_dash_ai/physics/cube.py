"""Deterministic fixed-step cube physics and continuous collision checks."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from itertools import pairwise
from math import ceil, hypot

from geometry_dash_ai.physics.geometry import (
    AABB,
    FloorSegment,
    LocalGeometry,
    SolidRect,
    Spike,
    aabb_distance,
    conservative_spike_clearance,
    require_finite,
    require_positive,
    swept_spike_collision_time,
)


MAX_SIMULATION_HORIZON_SECONDS = 5.0
MAX_SIMULATION_STEPS = 1_200
MAX_JUMP_DELAY_STEPS = 240
MAX_ABS_KINEMATIC_VALUE = 100_000.0
_EPSILON = 1e-9


class CollisionType(str, Enum):
    SPIKE = "spike"
    SOLID_SIDE = "solid_side"
    SOLID_UNDERSIDE = "solid_underside"
    GAP = "gap"
    ALREADY_DEAD = "already_dead"


@dataclass(frozen=True, slots=True)
class CubeState:
    x: float
    y: float
    vx: float
    vy: float
    width: float
    height: float
    grounded: bool
    alive: bool = True
    simulation_time: float = 0.0

    def __post_init__(self) -> None:
        for name in ("x", "y", "vx", "vy", "simulation_time"):
            require_finite(f"CubeState.{name}", getattr(self, name))
        require_positive("CubeState.width", self.width)
        require_positive("CubeState.height", self.height)
        if abs(self.vx) > MAX_ABS_KINEMATIC_VALUE or abs(self.vy) > MAX_ABS_KINEMATIC_VALUE:
            raise ValueError("cube velocity exceeds supported bounds")
        if self.simulation_time < 0:
            raise ValueError("CubeState.simulation_time cannot be negative")
        if not isinstance(self.grounded, bool) or not isinstance(self.alive, bool):
            raise ValueError("CubeState grounded/alive flags must be booleans")

    @property
    def bounds(self) -> AABB:
        return AABB(self.x, self.y, self.width, self.height)


@dataclass(frozen=True, slots=True)
class CubePhysicsParameters:
    gravity: float = -1_300.0
    jump_velocity: float = 480.0
    horizontal_speed: float = 180.0
    collision_width: float = 24.0
    collision_height: float = 24.0
    time_step: float = 1.0 / 60.0
    maximum_simulation_duration: float = 2.0
    clearance_relevance_distance: float = 240.0

    def __post_init__(self) -> None:
        for name in ("gravity", "jump_velocity", "horizontal_speed"):
            require_finite(f"CubePhysicsParameters.{name}", getattr(self, name))
        require_positive("CubePhysicsParameters.collision_width", self.collision_width)
        require_positive("CubePhysicsParameters.collision_height", self.collision_height)
        require_positive("CubePhysicsParameters.time_step", self.time_step)
        require_positive(
            "CubePhysicsParameters.maximum_simulation_duration",
            self.maximum_simulation_duration,
        )
        require_positive(
            "CubePhysicsParameters.clearance_relevance_distance",
            self.clearance_relevance_distance,
        )
        if self.gravity >= 0:
            raise ValueError("cube gravity must be negative")
        if self.jump_velocity <= 0 or self.horizontal_speed <= 0:
            raise ValueError("jump velocity and horizontal speed must be positive")
        if any(
            abs(value) > MAX_ABS_KINEMATIC_VALUE
            for value in (self.gravity, self.jump_velocity, self.horizontal_speed)
        ):
            raise ValueError("cube physics value exceeds supported bounds")
        if not 1e-4 <= self.time_step <= 0.05:
            raise ValueError("time_step must be between 0.0001 and 0.05 seconds")
        if self.maximum_simulation_duration > MAX_SIMULATION_HORIZON_SECONDS:
            raise ValueError(
                f"maximum simulation duration cannot exceed {MAX_SIMULATION_HORIZON_SECONDS}"
            )
        if self.clearance_relevance_distance > 10_000.0:
            raise ValueError("clearance relevance distance is too large")


@dataclass(frozen=True, slots=True)
class CollisionEvent:
    collision_type: CollisionType
    time: float
    x: float
    y: float
    obstacle_id: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.collision_type, CollisionType):
            raise ValueError("invalid collision type")
        for name in ("time", "x", "y"):
            require_finite(f"CollisionEvent.{name}", getattr(self, name))
        if self.time < 0:
            raise ValueError("collision time cannot be negative")
        if self.obstacle_id is not None and (
            not isinstance(self.obstacle_id, str)
            or not self.obstacle_id
            or len(self.obstacle_id) > 128
        ):
            raise ValueError("collision obstacle_id is invalid")


@dataclass(frozen=True, slots=True)
class LandingEvent:
    time: float
    x: float
    y: float
    surface_start_x: float
    surface_end_x: float
    margin: float
    obstacle_id: str

    def __post_init__(self) -> None:
        for name in (
            "time",
            "x",
            "y",
            "surface_start_x",
            "surface_end_x",
            "margin",
        ):
            require_finite(f"LandingEvent.{name}", getattr(self, name))
        if self.time < 0 or self.surface_end_x <= self.surface_start_x or self.margin < 0:
            raise ValueError("invalid landing metadata")
        if (
            not isinstance(self.obstacle_id, str)
            or not self.obstacle_id
            or len(self.obstacle_id) > 128
        ):
            raise ValueError("landing obstacle_id is invalid")


@dataclass(frozen=True, slots=True)
class CubeTrajectory:
    samples: tuple[CubeState, ...]
    survived_horizon: bool
    collision: CollisionEvent | None
    landings: tuple[LandingEvent, ...]
    jump_requested: bool
    jump_applied: bool
    minimum_clearance: float
    simulated_duration: float

    def __post_init__(self) -> None:
        if not isinstance(self.samples, tuple) or not self.samples:
            raise ValueError("trajectory samples must be a non-empty tuple")
        if not isinstance(self.landings, tuple):
            raise ValueError("trajectory landings must be a tuple")
        if len(self.samples) > MAX_SIMULATION_STEPS + 1:
            raise ValueError("trajectory contains too many samples")
        if len(self.landings) > MAX_SIMULATION_STEPS:
            raise ValueError("trajectory contains too many landings")
        if any(not isinstance(sample, CubeState) for sample in self.samples):
            raise ValueError("trajectory contains an invalid cube state")
        if any(not isinstance(landing, LandingEvent) for landing in self.landings):
            raise ValueError("trajectory contains invalid landing metadata")
        if not isinstance(self.jump_requested, bool) or not isinstance(self.jump_applied, bool):
            raise ValueError("trajectory jump flags must be booleans")
        if self.jump_applied and not self.jump_requested:
            raise ValueError("a jump cannot be applied unless it was requested")
        if not isinstance(self.survived_horizon, bool):
            raise ValueError("trajectory survival flag must be a boolean")
        if self.collision is not None and not isinstance(self.collision, CollisionEvent):
            raise ValueError("trajectory collision metadata is invalid")
        require_finite("CubeTrajectory.minimum_clearance", self.minimum_clearance)
        require_finite("CubeTrajectory.simulated_duration", self.simulated_duration)
        if self.minimum_clearance < 0 or self.simulated_duration < 0:
            raise ValueError("trajectory metrics cannot be negative")
        if self.survived_horizon == (self.collision is not None):
            raise ValueError("trajectory survival and collision metadata disagree")
        if any(
            later.simulation_time + _EPSILON < earlier.simulation_time
            for earlier, later in pairwise(self.samples)
        ):
            raise ValueError("trajectory sample times must be ordered")

    @property
    def landing_position(self) -> tuple[float, float] | None:
        if not self.landings:
            return None
        landing = self.landings[-1]
        return (landing.x, landing.y)

    @property
    def landing_margin(self) -> float | None:
        return self.landings[-1].margin if self.landings else None


@dataclass(frozen=True, slots=True)
class _Contact:
    fraction: float
    collision_type: CollisionType | None
    obstacle_id: str
    surface_y: float | None = None
    surface_start_x: float | None = None
    surface_end_x: float | None = None

    @property
    def fatal(self) -> bool:
        return self.collision_type is not None


def simulate_cube_trajectory(
    initial_state: CubeState,
    geometry: LocalGeometry,
    physics: CubePhysicsParameters,
    horizon_seconds: float,
    jump_delay_steps: int | None,
) -> CubeTrajectory:
    """Simulate one prospective jump decision without mutating caller-owned data."""
    _validate_simulation_request(
        initial_state,
        geometry,
        physics,
        horizon_seconds,
        jump_delay_steps,
    )
    if not initial_state.alive:
        collision = CollisionEvent(
            CollisionType.ALREADY_DEAD,
            initial_state.simulation_time,
            initial_state.x,
            initial_state.y,
            None,
        )
        return CubeTrajectory(
            samples=(initial_state,),
            survived_horizon=False,
            collision=collision,
            landings=(),
            jump_requested=jump_delay_steps is not None,
            jump_applied=False,
            minimum_clearance=0.0,
            simulated_duration=0.0,
        )

    step_count = ceil(horizon_seconds / physics.time_step)
    state = initial_state
    samples = [state]
    landings: list[LandingEvent] = []
    jump_applied = False
    minimum_clearance = _state_clearance(state, geometry, physics.clearance_relevance_distance)
    collision: CollisionEvent | None = None

    for step_index in range(step_count):
        jump_now = jump_delay_steps is not None and step_index == jump_delay_steps
        state, contact, landing, applied = _advance_one_step(state, geometry, physics, jump_now)
        jump_applied = jump_applied or applied
        samples.append(state)
        if landing is not None:
            landings.append(landing)
        clearance = _state_clearance(state, geometry, physics.clearance_relevance_distance)
        minimum_clearance = min(minimum_clearance, clearance)
        if contact is not None:
            collision = contact
            minimum_clearance = 0.0
            break

    duration = state.simulation_time - initial_state.simulation_time
    return CubeTrajectory(
        samples=tuple(samples),
        survived_horizon=collision is None,
        collision=collision,
        landings=tuple(landings),
        jump_requested=jump_delay_steps is not None,
        jump_applied=jump_applied,
        minimum_clearance=minimum_clearance,
        simulated_duration=duration,
    )


def _validate_simulation_request(
    state: CubeState,
    geometry: LocalGeometry,
    physics: CubePhysicsParameters,
    horizon_seconds: float,
    jump_delay_steps: int | None,
) -> None:
    if not isinstance(state, CubeState):
        raise ValueError("initial_state must be a CubeState")
    if not isinstance(geometry, LocalGeometry):
        raise ValueError("geometry must be LocalGeometry")
    if not isinstance(physics, CubePhysicsParameters):
        raise ValueError("physics must be CubePhysicsParameters")
    require_finite("horizon_seconds", horizon_seconds)
    if horizon_seconds <= 0:
        raise ValueError("simulation horizon must be positive")
    if horizon_seconds > physics.maximum_simulation_duration:
        raise ValueError("simulation horizon exceeds physics maximum")
    if horizon_seconds > MAX_SIMULATION_HORIZON_SECONDS:
        raise ValueError("simulation horizon exceeds hard limit")
    if (
        abs(state.width - physics.collision_width) > _EPSILON
        or abs(state.height - physics.collision_height) > _EPSILON
    ):
        raise ValueError("cube state dimensions must match calibrated collision dimensions")
    step_count = ceil(horizon_seconds / physics.time_step)
    if step_count > MAX_SIMULATION_STEPS:
        raise ValueError(f"simulation requires more than {MAX_SIMULATION_STEPS} steps")
    if jump_delay_steps is not None:
        if isinstance(jump_delay_steps, bool) or not isinstance(jump_delay_steps, int):
            raise ValueError("jump delay must be an integer number of steps")
        if not 0 <= jump_delay_steps <= MAX_JUMP_DELAY_STEPS:
            raise ValueError(f"jump delay must be in [0, {MAX_JUMP_DELAY_STEPS}]")


def _advance_one_step(
    state: CubeState,
    geometry: LocalGeometry,
    physics: CubePhysicsParameters,
    jump_now: bool,
) -> tuple[CubeState, CollisionEvent | None, LandingEvent | None, bool]:
    vy = physics.jump_velocity if jump_now and state.grounded else state.vy
    jump_applied = jump_now and state.grounded
    next_vy = vy + physics.gravity * physics.time_step
    proposed = CubeState(
        x=state.x + physics.horizontal_speed * physics.time_step,
        y=state.y + next_vy * physics.time_step,
        vx=physics.horizontal_speed,
        vy=next_vy,
        width=state.width,
        height=state.height,
        grounded=False,
        alive=True,
        simulation_time=state.simulation_time + physics.time_step,
    )
    if state.grounded and not jump_applied:
        support_y = _support_height(state, proposed, geometry)
        if support_y is not None:
            proposed = replace(proposed, y=support_y, vy=0.0, grounded=True)

    contacts = _collect_contacts(state, proposed, geometry)
    if not contacts:
        return proposed, None, None, jump_applied
    contact = min(contacts, key=lambda item: (item.fraction, not item.fatal, item.obstacle_id))
    contact_time = state.simulation_time + physics.time_step * contact.fraction
    contact_x = state.x + (proposed.x - state.x) * contact.fraction
    contact_y = state.y + (proposed.y - state.y) * contact.fraction

    if contact.fatal:
        assert contact.collision_type is not None
        dead_state = CubeState(
            x=contact_x,
            y=contact_y,
            vx=physics.horizontal_speed,
            vy=next_vy,
            width=state.width,
            height=state.height,
            grounded=False,
            alive=False,
            simulation_time=contact_time,
        )
        collision = CollisionEvent(
            contact.collision_type,
            contact_time,
            contact_x,
            contact_y,
            contact.obstacle_id,
        )
        return dead_state, collision, None, jump_applied

    assert contact.surface_y is not None
    assert contact.surface_start_x is not None
    assert contact.surface_end_x is not None
    landed_state = replace(proposed, y=contact.surface_y, vy=0.0, grounded=True)
    landing = None
    if not state.grounded or state.y > contact.surface_y + _EPSILON:
        center_x = contact_x + state.width / 2.0
        margin = _landing_margin(
            center_x,
            state.width,
            contact.surface_start_x,
            contact.surface_end_x,
        )
        landing = LandingEvent(
            time=contact_time,
            x=center_x,
            y=contact.surface_y,
            surface_start_x=contact.surface_start_x,
            surface_end_x=contact.surface_end_x,
            margin=margin,
            obstacle_id=contact.obstacle_id,
        )
    return landed_state, None, landing, jump_applied


def _collect_contacts(
    start: CubeState,
    end: CubeState,
    geometry: LocalGeometry,
) -> list[_Contact]:
    contacts: list[_Contact] = []
    for floor in geometry.floors:
        landing = _floor_landing_contact(start, end, floor)
        if landing is not None:
            contacts.append(landing)
    for solid in geometry.solids:
        contacts.extend(_solid_contacts(start, end, solid))
    for spike in geometry.spikes:
        collision_time = swept_spike_collision_time(spike, start.bounds, end.bounds)
        if collision_time is not None:
            contacts.append(_Contact(collision_time, CollisionType.SPIKE, spike.obstacle_id))

    if end.bounds.top <= geometry.death_y:
        denominator = start.bounds.top - end.bounds.top
        fraction = 1.0 if denominator <= 0 else (start.bounds.top - geometry.death_y) / denominator
        contacts.append(_Contact(max(0.0, min(1.0, fraction)), CollisionType.GAP, "gap"))
    return contacts


def _floor_landing_contact(
    start: CubeState,
    end: CubeState,
    floor: FloorSegment,
) -> _Contact | None:
    if start.grounded and end.grounded and abs(start.y - floor.height) <= _EPSILON:
        return None
    fraction = _downward_crossing_fraction(start.y, end.y, floor.height)
    if fraction is None:
        return None
    x = start.x + (end.x - start.x) * fraction
    final_supported = end.x < floor.end_x and end.x + end.width > floor.start_x
    crosses_surface = x < floor.end_x and x + start.width > floor.start_x
    if not crosses_surface or not final_supported:
        return None
    return _Contact(
        fraction,
        None,
        floor.obstacle_id,
        floor.height,
        floor.start_x,
        floor.end_x,
    )


def _solid_contacts(start: CubeState, end: CubeState, solid: SolidRect) -> list[_Contact]:
    bounds = solid.bounds
    contacts: list[_Contact] = []
    maintained_support = (
        start.grounded and end.grounded and abs(start.y - bounds.top) <= _EPSILON
    )
    landing_fraction = None if maintained_support else _downward_crossing_fraction(
        start.y, end.y, bounds.top
    )
    if landing_fraction is not None:
        x = start.x + (end.x - start.x) * landing_fraction
        crosses_top = x < bounds.right and x + start.width > bounds.x
        finishes_supported = end.x < bounds.right and end.x + end.width > bounds.x
        if crosses_top and finishes_supported:
            contacts.append(
                _Contact(
                    landing_fraction,
                    None,
                    solid.obstacle_id,
                    bounds.top,
                    bounds.x,
                    bounds.right,
                )
            )

    start_top = start.y + start.height
    end_top = end.y + end.height
    if end_top > start_top and start_top <= bounds.y + _EPSILON and end_top >= bounds.y:
        fraction = (bounds.y - start_top) / (end_top - start_top)
        x = start.x + (end.x - start.x) * fraction
        if x < bounds.right and x + start.width > bounds.x:
            contacts.append(
                _Contact(max(0.0, fraction), CollisionType.SOLID_UNDERSIDE, solid.obstacle_id)
            )

    start_right = start.x + start.width
    end_right = end.x + end.width
    if end_right > start_right and start_right <= bounds.x + _EPSILON and end_right >= bounds.x:
        fraction = (bounds.x - start_right) / (end_right - start_right)
        y = start.y + (end.y - start.y) * fraction
        if y < bounds.top and y + start.height > bounds.y:
            contacts.append(
                _Contact(max(0.0, fraction), CollisionType.SOLID_SIDE, solid.obstacle_id)
            )

    if end.bounds.overlaps(bounds) and not contacts:
        contacts.append(_Contact(1.0, CollisionType.SOLID_SIDE, solid.obstacle_id))
    return contacts


def _support_height(
    start: CubeState,
    end: CubeState,
    geometry: LocalGeometry,
) -> float | None:
    surfaces = [
        floor.height
        for floor in geometry.floors
        if abs(start.y - floor.height) <= _EPSILON
        and end.x < floor.end_x
        and end.x + end.width > floor.start_x
    ]
    surfaces.extend(
        solid.bounds.top
        for solid in geometry.solids
        if abs(start.y - solid.bounds.top) <= _EPSILON
        and end.x < solid.bounds.right
        and end.x + end.width > solid.bounds.x
    )
    return max(surfaces) if surfaces else None


def _downward_crossing_fraction(start_y: float, end_y: float, surface_y: float) -> float | None:
    if end_y > start_y or start_y < surface_y - _EPSILON or end_y > surface_y + _EPSILON:
        return None
    distance = start_y - end_y
    return 0.0 if distance <= _EPSILON else max(0.0, min(1.0, (start_y - surface_y) / distance))


def _landing_margin(center_x: float, width: float, start_x: float, end_x: float) -> float:
    usable_start = start_x + width / 2.0
    usable_end = end_x - width / 2.0
    return max(0.0, min(center_x - usable_start, usable_end - center_x))


def _state_clearance(state: CubeState, geometry: LocalGeometry, relevance: float) -> float:
    if not state.alive:
        return 0.0
    box = state.bounds
    clearance = relevance
    for spike in geometry.spikes:
        if spike.x <= box.right + relevance and spike.x + spike.width >= box.x - relevance:
            clearance = min(clearance, conservative_spike_clearance(spike, box))
    for solid in geometry.solids:
        bounds = solid.bounds
        if bounds.x <= box.right + relevance and bounds.right >= box.x - relevance:
            supported = (
                abs(box.y - bounds.top) <= 1e-7
                and box.x < bounds.right
                and box.right > bounds.x
            )
            if not supported:
                clearance = min(clearance, aabb_distance(box, bounds))
    for floor in geometry.floors:
        if floor.start_x <= box.right <= floor.end_x and floor.end_x - box.right <= relevance:
            vertical = max(0.0, box.y - floor.height)
            clearance = min(clearance, hypot(floor.end_x - box.right, vertical))
    return max(0.0, clearance)
