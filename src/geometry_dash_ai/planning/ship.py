"""Deterministic bounded receding-horizon planning for ship mode."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from time import monotonic_ns

from geometry_dash_ai.physics.geometry import LocalGeometry
from geometry_dash_ai.physics.ship import (
    ShipPhysicsParameters,
    ShipState,
    ShipTrajectory,
    simulate_ship_trajectory,
)


@dataclass(frozen=True, slots=True)
class ShipPlannerConfig:
    segments: int = 3
    segment_steps: int = 4
    maximum_candidates: int = 8
    switch_penalty: float = 12.0
    hysteresis_margin: float = 4.0

    def __post_init__(self) -> None:
        if not 1 <= self.segments <= 5 or not 1 <= self.segment_steps <= 30:
            raise ValueError("ship planner horizon is outside bounds")
        if not 2 <= self.maximum_candidates <= 32:
            raise ValueError("ship candidate count is outside bounds")
        if not 0.0 <= self.switch_penalty <= 1_000.0:
            raise ValueError("ship switch penalty is outside bounds")
        if not 0.0 <= self.hysteresis_margin <= 100.0:
            raise ValueError("ship hysteresis is outside bounds")


@dataclass(frozen=True, slots=True)
class ShipCandidate:
    actions: tuple[bool, ...]
    trajectory: ShipTrajectory
    score: float


@dataclass(frozen=True, slots=True)
class ShipDecision:
    hold: bool
    candidates: tuple[ShipCandidate, ...]
    selected_score: float
    confidence: float
    all_candidates_unsafe: bool
    planning_latency_ms: float


def plan_ship_action(
    state: ShipState,
    geometry: LocalGeometry,
    parameters: ShipPhysicsParameters | None = None,
    config: ShipPlannerConfig | None = None,
) -> ShipDecision:
    """Evaluate a bounded binary action family and execute only its first segment."""
    started = monotonic_ns()
    physics = parameters or ShipPhysicsParameters()
    planner = config or ShipPlannerConfig()
    sequences = tuple(product((False, True), repeat=planner.segments))[: planner.maximum_candidates]
    target_y = _corridor_target(state, geometry)
    evaluated = tuple(
        _candidate(state, geometry, physics, planner, tuple(sequence), target_y)
        for sequence in sequences
    )
    selected = max(evaluated, key=lambda item: (item.trajectory.survived, item.score))
    # Preserve current action unless switching earns a meaningful advantage.
    current = max(
        (item for item in evaluated if item.actions[0] is state.held),
        key=lambda item: (item.trajectory.survived, item.score),
        default=selected,
    )
    if current.trajectory.survived and current.score + planner.hysteresis_margin >= selected.score:
        selected = current
    unsafe = not any(item.trajectory.survived for item in evaluated)
    confidence = (1.0 - geometry.uncertainty) * (1.0 if selected.trajectory.survived else 0.25)
    return ShipDecision(
        selected.actions[0],
        evaluated,
        selected.score,
        max(0.0, min(1.0, confidence * state.confidence)),
        unsafe,
        (monotonic_ns() - started) / 1_000_000.0,
    )


def _candidate(
    state: ShipState,
    geometry: LocalGeometry,
    physics: ShipPhysicsParameters,
    config: ShipPlannerConfig,
    actions: tuple[bool, ...],
    target_y: float,
) -> ShipCandidate:
    trajectory = simulate_ship_trajectory(state, geometry, physics, actions, config.segment_steps)
    switches = sum(
        first != second for first, second in zip((state.held, *actions), actions, strict=False)
    )
    terminal = trajectory.samples[-1]
    center_cost = abs(terminal.y - target_y) * 0.5
    score = (
        (10_000.0 if trajectory.survived else -10_000.0)
        + min(trajectory.minimum_clearance, 250.0) * 4.0
        - switches * config.switch_penalty
        - center_cost
        - geometry.uncertainty * 500.0
    )
    return ShipCandidate(actions, trajectory, score)


def _corridor_target(state: ShipState, geometry: LocalGeometry) -> float:
    floor_heights = (
        floor.height
        for floor in geometry.floors
        if floor.start_x <= state.x <= floor.end_x
    )
    floor = max(floor_heights, default=None)
    ceiling_bottoms = (
        solid.bounds.y
        for solid in geometry.solids
        if solid.bounds.y > state.y
        and solid.bounds.x <= state.x + state.vx * 0.25
        and solid.bounds.right >= state.x
    )
    ceiling = min(ceiling_bottoms, default=None)
    if floor is None or ceiling is None or ceiling - floor <= state.height:
        return state.y
    return (floor + ceiling - state.height) / 2.0
