"""Deterministic survival-first cube trajectory planner."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from geometry_dash_ai.physics.cube import (
    MAX_JUMP_DELAY_STEPS,
    MAX_SIMULATION_HORIZON_SECONDS,
    CollisionEvent,
    CubePhysicsParameters,
    CubeState,
    CubeTrajectory,
    simulate_cube_trajectory,
)
from geometry_dash_ai.physics.geometry import LocalGeometry, require_finite
from geometry_dash_ai.planning.candidates import (
    HARD_MAX_CANDIDATES,
    CubeAction,
    CubeActionCandidate,
    generate_cube_candidates,
)


HARD_MAX_OBSTACLES_PER_PLAN = 256
HARD_MAX_ROBUSTNESS_WINDOW_FRAMES = 3


@dataclass(frozen=True, slots=True)
class CubePlannerConfig:
    horizon_seconds: float = 1.25
    maximum_jump_delay_frames: int = 24
    delay_increment_frames: int = 2
    maximum_candidates: int = 16
    maximum_obstacles: int = 128
    robustness_window_frames: int = 1
    clearance_weight: float = 2.0
    landing_margin_weight: float = 20.0
    uncertainty_weight: float = 400.0
    unnecessary_jump_penalty: float = 2_100.0

    def __post_init__(self) -> None:
        numeric = (
            "horizon_seconds",
            "clearance_weight",
            "landing_margin_weight",
            "uncertainty_weight",
            "unnecessary_jump_penalty",
        )
        for name in numeric:
            require_finite(f"CubePlannerConfig.{name}", getattr(self, name))
        if not 0 < self.horizon_seconds <= MAX_SIMULATION_HORIZON_SECONDS:
            raise ValueError("planner horizon must be positive and within the hard limit")
        integers = (
            "maximum_jump_delay_frames",
            "delay_increment_frames",
            "maximum_candidates",
            "maximum_obstacles",
            "robustness_window_frames",
        )
        for name in integers:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"CubePlannerConfig.{name} must be an integer")
        if not 3 <= self.maximum_jump_delay_frames <= MAX_JUMP_DELAY_STEPS:
            raise ValueError("maximum jump delay is outside supported bounds")
        if not 1 <= self.delay_increment_frames <= MAX_JUMP_DELAY_STEPS:
            raise ValueError("delay increment is outside supported bounds")
        if not 5 <= self.maximum_candidates <= HARD_MAX_CANDIDATES:
            raise ValueError("maximum candidate count is outside supported bounds")
        if not 1 <= self.maximum_obstacles <= HARD_MAX_OBSTACLES_PER_PLAN:
            raise ValueError("maximum obstacle count is outside supported bounds")
        if not 0 <= self.robustness_window_frames <= HARD_MAX_ROBUSTNESS_WINDOW_FRAMES:
            raise ValueError("robustness timing window is outside supported bounds")
        if any(
            value < 0
            for value in (
                self.clearance_weight,
                self.landing_margin_weight,
                self.uncertainty_weight,
                self.unnecessary_jump_penalty,
            )
        ):
            raise ValueError("planner score weights cannot be negative")
        maximum_weights = {
            "clearance_weight": (self.clearance_weight, 10.0),
            "landing_margin_weight": (self.landing_margin_weight, 20.0),
            "uncertainty_weight": (self.uncertainty_weight, 1_000.0),
            "unnecessary_jump_penalty": (self.unnecessary_jump_penalty, 3_000.0),
        }
        for name, (value, maximum) in maximum_weights.items():
            if value > maximum:
                raise ValueError(f"planner {name} exceeds supported bound of {maximum}")


@dataclass(frozen=True, slots=True)
class ScoreComponents:
    survival: float
    clearance: float
    landing_margin: float
    stable_grounded: float
    timing_robustness: float
    timing_risk: float
    uncertainty: float
    unnecessary_jump: float
    invalid_jump: float

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            require_finite(f"ScoreComponents.{name}", getattr(self, name))

    @property
    def total(self) -> float:
        return sum(
            (
                self.survival,
                self.clearance,
                self.landing_margin,
                self.stable_grounded,
                self.timing_robustness,
                self.timing_risk,
                self.uncertainty,
                self.unnecessary_jump,
                self.invalid_jump,
            )
        )


@dataclass(frozen=True, slots=True)
class EvaluatedCandidate:
    candidate: CubeActionCandidate
    trajectory: CubeTrajectory
    robustness_safe_fraction: float
    timing_variant_survival: tuple[bool, ...]
    score_components: ScoreComponents
    total_score: float

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, CubeActionCandidate):
            raise ValueError("evaluated candidate has an invalid action")
        if not isinstance(self.trajectory, CubeTrajectory):
            raise ValueError("evaluated candidate has an invalid trajectory")
        require_finite("EvaluatedCandidate.robustness_safe_fraction", self.robustness_safe_fraction)
        require_finite("EvaluatedCandidate.total_score", self.total_score)
        if not 0.0 <= self.robustness_safe_fraction <= 1.0:
            raise ValueError("robustness fraction must be in [0, 1]")
        if (
            not isinstance(self.timing_variant_survival, tuple)
            or not self.timing_variant_survival
            or len(self.timing_variant_survival) > 7
            or any(
                not isinstance(value, bool) for value in self.timing_variant_survival
            )
        ):
            raise ValueError("timing variants must be a non-empty tuple of booleans")
        if not isfinite(self.score_components.total):
            raise ValueError("score components must be finite")
        if abs(self.total_score - self.score_components.total) > 1e-7:
            raise ValueError("candidate total does not match score components")


@dataclass(frozen=True, slots=True)
class PlanDecision:
    selected_action: CubeAction
    jump_delay_frames: int | None
    evaluated_candidates: tuple[EvaluatedCandidate, ...]
    selected_score: float
    confidence: float
    all_candidates_unsafe: bool
    predicted_collision: CollisionEvent | None
    predicted_time_to_death: float | None
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.selected_action, CubeAction):
            raise ValueError("invalid selected cube action")
        if (
            not isinstance(self.evaluated_candidates, tuple)
            or not self.evaluated_candidates
            or len(self.evaluated_candidates) > HARD_MAX_CANDIDATES
        ):
            raise ValueError("plan must contain a bounded, non-empty candidate set")
        if any(not isinstance(item, EvaluatedCandidate) for item in self.evaluated_candidates):
            raise ValueError("plan contains an invalid evaluated candidate")
        require_finite("PlanDecision.selected_score", self.selected_score)
        require_finite("PlanDecision.confidence", self.confidence)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("plan confidence must be in [0, 1]")
        if self.predicted_time_to_death is not None:
            require_finite("PlanDecision.predicted_time_to_death", self.predicted_time_to_death)
            if self.predicted_time_to_death < 0:
                raise ValueError("predicted time to death cannot be negative")
        if self.all_candidates_unsafe != all(
            not item.trajectory.survived_horizon for item in self.evaluated_candidates
        ):
            raise ValueError("all-candidates-unsafe metadata is inconsistent")
        if self.all_candidates_unsafe != (self.predicted_collision is not None):
            raise ValueError("predicted collision metadata is inconsistent")
        if self.selected_action is CubeAction.NO_INPUT and self.jump_delay_frames is not None:
            raise ValueError("no-input decision cannot have a jump delay")
        if self.selected_action is CubeAction.JUMP and self.jump_delay_frames is None:
            raise ValueError("jump decision requires a delay")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("plan reason must be a non-empty string")
        selected = self.selected_candidate
        if abs(selected.total_score - self.selected_score) > 1e-7:
            raise ValueError("selected score does not match selected candidate")

    @property
    def selected_candidate(self) -> EvaluatedCandidate:
        for evaluated in self.evaluated_candidates:
            if (
                evaluated.candidate.action is self.selected_action
                and evaluated.candidate.jump_delay_frames == self.jump_delay_frames
            ):
                return evaluated
        raise RuntimeError("selected candidate is absent from evaluated candidates")


def plan_cube_action(
    player_state: CubeState,
    local_geometry: LocalGeometry,
    physics_parameters: CubePhysicsParameters,
    planner_config: CubePlannerConfig | None = None,
) -> PlanDecision:
    """Evaluate bounded candidates and return a deterministic survival-first plan."""
    config = planner_config or CubePlannerConfig()
    if not isinstance(player_state, CubeState):
        raise ValueError("player_state must be CubeState")
    if not isinstance(local_geometry, LocalGeometry):
        raise ValueError("local_geometry must be LocalGeometry")
    if not isinstance(physics_parameters, CubePhysicsParameters):
        raise ValueError("physics_parameters must be CubePhysicsParameters")
    if not isinstance(config, CubePlannerConfig):
        raise ValueError("planner_config must be CubePlannerConfig")
    if config.horizon_seconds > physics_parameters.maximum_simulation_duration:
        raise ValueError("planner horizon exceeds physics maximum simulation duration")

    geometry = local_geometry.nearest(player_state.x, config.maximum_obstacles)
    candidates = generate_cube_candidates(
        config.maximum_jump_delay_frames,
        config.delay_increment_frames,
        config.maximum_candidates,
    )
    required_delays = {
        delay
        for candidate in candidates
        for delay in _variant_delays(candidate, config)
    }
    trajectories = {
        delay: simulate_cube_trajectory(
            player_state,
            geometry,
            physics_parameters,
            config.horizon_seconds,
            delay,
        )
        for delay in required_delays
    }
    evaluated = tuple(
        _evaluate_candidate(candidate, trajectories, geometry, physics_parameters, config)
        for candidate in candidates
    )
    selected = max(
        evaluated,
        key=lambda item: (
            item.trajectory.survived_horizon,
            item.trajectory.simulated_duration,
            item.total_score,
        ),
    )
    all_unsafe = not any(item.trajectory.survived_horizon for item in evaluated)
    collision = selected.trajectory.collision if all_unsafe else None
    time_to_death = None
    if collision is not None:
        time_to_death = max(0.0, collision.time - player_state.simulation_time)
    confidence = selected.robustness_safe_fraction * (1.0 - geometry.uncertainty)
    if all_unsafe:
        confidence *= min(1.0, selected.trajectory.simulated_duration / config.horizon_seconds)
    delay_text = (
        "without jumping"
        if selected.candidate.action is CubeAction.NO_INPUT
        else f"with a jump delayed {selected.candidate.jump_delay_frames} frame(s)"
    )
    safety_text = (
        "all candidates collide; maximizing survival time" if all_unsafe else "safe horizon"
    )
    return PlanDecision(
        selected_action=selected.candidate.action,
        jump_delay_frames=selected.candidate.jump_delay_frames,
        evaluated_candidates=evaluated,
        selected_score=selected.total_score,
        confidence=max(0.0, min(1.0, confidence)),
        all_candidates_unsafe=all_unsafe,
        predicted_collision=collision,
        predicted_time_to_death=time_to_death,
        reason=f"Selected {selected.candidate.label} ({delay_text}): {safety_text}",
    )


def _evaluate_candidate(
    candidate: CubeActionCandidate,
    trajectories: dict[int | None, CubeTrajectory],
    geometry: LocalGeometry,
    physics: CubePhysicsParameters,
    config: CubePlannerConfig,
) -> EvaluatedCandidate:
    trajectory = trajectories[candidate.jump_delay_frames]
    variant_results = tuple(trajectories[delay] for delay in _variant_delays(candidate, config))
    variant_survival = tuple(result.survived_horizon for result in variant_results)
    robust_fraction = sum(variant_survival) / len(variant_survival)
    score = _score(candidate, trajectory, robust_fraction, geometry, physics, config)
    return EvaluatedCandidate(
        candidate=candidate,
        trajectory=trajectory,
        robustness_safe_fraction=robust_fraction,
        timing_variant_survival=variant_survival,
        score_components=score,
        total_score=score.total,
    )


def _variant_delays(
    candidate: CubeActionCandidate,
    config: CubePlannerConfig,
) -> tuple[int | None, ...]:
    if candidate.action is CubeAction.NO_INPUT:
        return (None,)
    assert candidate.jump_delay_frames is not None
    window = config.robustness_window_frames
    delays = {
        max(0, candidate.jump_delay_frames + offset)
        for offset in range(-window, window + 1)
        if candidate.jump_delay_frames + offset <= MAX_JUMP_DELAY_STEPS
    }
    return tuple(sorted(delays))


def _score(
    candidate: CubeActionCandidate,
    trajectory: CubeTrajectory,
    robustness: float,
    geometry: LocalGeometry,
    physics: CubePhysicsParameters,
    config: CubePlannerConfig,
) -> ScoreComponents:
    if trajectory.survived_horizon:
        survival = 10_000.0
    else:
        survival = -10_000.0 + min(1_000.0, trajectory.simulated_duration * 200.0)
    clearance = (
        min(trajectory.minimum_clearance, physics.clearance_relevance_distance, 250.0)
        * config.clearance_weight
    )
    landing_margin = min(trajectory.landing_margin or 0.0, 100.0) * config.landing_margin_weight
    stable_grounded = (
        50.0 if trajectory.samples[-1].alive and trajectory.samples[-1].grounded else 0.0
    )
    timing_robustness = robustness * 300.0
    timing_risk = -(1.0 - robustness) * 500.0
    uncertainty = -geometry.uncertainty * config.uncertainty_weight
    unnecessary_jump = (
        -config.unnecessary_jump_penalty if candidate.action is CubeAction.JUMP else 0.0
    )
    invalid_jump = -200.0 if trajectory.jump_requested and not trajectory.jump_applied else 0.0
    return ScoreComponents(
        survival=survival,
        clearance=clearance,
        landing_margin=landing_margin,
        stable_grounded=stable_grounded,
        timing_robustness=timing_robustness,
        timing_risk=timing_risk,
        uncertainty=uncertainty,
        unnecessary_jump=unnecessary_jump,
        invalid_jump=invalid_jump,
    )
