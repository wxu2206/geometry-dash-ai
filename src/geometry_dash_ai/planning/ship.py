"""Deterministic bounded receding-horizon planning for ship mode."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import isfinite
from time import monotonic_ns

from geometry_dash_ai.physics.geometry import LocalGeometry, require_finite
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
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (self.segments, self.segment_steps, self.maximum_candidates)
        ):
            raise ValueError("ship planner integer limits are invalid")
        for name in ("switch_penalty", "hysteresis_margin"):
            require_finite(f"ShipPlannerConfig.{name}", getattr(self, name))
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

    def __post_init__(self) -> None:
        if (
            not isinstance(self.actions, tuple)
            or not 1 <= len(self.actions) <= 8
            or any(not isinstance(action, bool) for action in self.actions)
        ):
            raise ValueError("ship candidate actions are invalid")
        if (
            not isinstance(self.trajectory, ShipTrajectory)
            or isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not isfinite(self.score)
        ):
            raise ValueError("ship candidate trajectory or score is invalid")


@dataclass(frozen=True, slots=True)
class ShipDecision:
    hold: bool
    candidates: tuple[ShipCandidate, ...]
    selected_score: float
    confidence: float
    all_candidates_unsafe: bool
    planning_latency_ms: float

    def __post_init__(self) -> None:
        if not isinstance(self.hold, bool):
            raise ValueError("ship decision hold state is invalid")
        if (
            not isinstance(self.candidates, tuple)
            or not self.candidates
            or len(self.candidates) > 32
            or any(not isinstance(candidate, ShipCandidate) for candidate in self.candidates)
        ):
            raise ValueError("ship decision candidates are invalid")
        for name in ("selected_score", "confidence", "planning_latency_ms"):
            value = getattr(self, name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(value)
            ):
                raise ValueError(f"ship decision {name} must be finite")
        if not 0.0 <= self.confidence <= 1.0 or self.planning_latency_ms < 0.0:
            raise ValueError("ship decision confidence or latency is invalid")
        if not isinstance(self.all_candidates_unsafe, bool):
            raise ValueError("ship decision unsafe metadata is invalid")
        if self.all_candidates_unsafe != all(
            not candidate.trajectory.survived for candidate in self.candidates
        ):
            raise ValueError("ship decision unsafe metadata is inconsistent")
        selected = max(
            self.candidates,
            key=lambda candidate: (candidate.trajectory.survived, candidate.score),
        )
        if self.hold not in {candidate.actions[0] for candidate in self.candidates}:
            raise ValueError("ship decision selected action is absent from candidates")
        if not any(
            candidate.actions[0] is self.hold
            and abs(candidate.score - self.selected_score) <= 1e-7
            for candidate in self.candidates
        ):
            raise ValueError("ship decision selected score is inconsistent")
        if not isfinite(selected.score):
            raise ValueError("ship decision selected score is invalid")


def plan_ship_action(
    state: ShipState,
    geometry: LocalGeometry,
    parameters: ShipPhysicsParameters | None = None,
    config: ShipPlannerConfig | None = None,
) -> ShipDecision:
    """Evaluate a bounded binary action family and execute only its first segment."""
    if not isinstance(state, ShipState):
        raise ValueError("ship state is invalid")
    if not isinstance(geometry, LocalGeometry):
        raise ValueError("ship geometry is invalid")
    if parameters is not None and not isinstance(parameters, ShipPhysicsParameters):
        raise ValueError("ship physics parameters are invalid")
    if config is not None and not isinstance(config, ShipPlannerConfig):
        raise ValueError("ship planner config is invalid")
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
