import math
import unittest

from geometry_dash_ai.physics import (
    AABB,
    CollisionType,
    CubePhysicsParameters,
    CubeState,
    FloorSegment,
    LocalGeometry,
    SolidRect,
    Spike,
)
from geometry_dash_ai.planning import CubeAction, CubePlannerConfig, plan_cube_action
from geometry_dash_ai.planning.candidates import (
    HARD_MAX_CANDIDATES,
    CubeActionCandidate,
    generate_cube_candidates,
)


def state(x: float = 0.0, *, alive: bool = True) -> CubeState:
    return CubeState(x, 0.0, 180.0, 0.0, 24.0, 24.0, True, alive)


def floor_geometry(*spikes: Spike) -> LocalGeometry:
    return LocalGeometry(
        floors=(FloorSegment(-100.0, 1_000.0),),
        spikes=spikes,
    )


class CubePlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.physics = CubePhysicsParameters()

    def test_flat_floor_selects_no_input(self) -> None:
        decision = plan_cube_action(state(), floor_geometry(), self.physics)

        self.assertIs(decision.selected_action, CubeAction.NO_INPUT)
        self.assertIsNone(decision.jump_delay_frames)
        self.assertFalse(decision.all_candidates_unsafe)

    def test_geometry_uncertainty_reduces_score_and_confidence(self) -> None:
        certain = plan_cube_action(state(), floor_geometry(), self.physics)
        uncertain_geometry = LocalGeometry(
            floors=(FloorSegment(-100.0, 1_000.0),),
            uncertainty=0.25,
        )
        uncertain = plan_cube_action(state(), uncertain_geometry, self.physics)

        self.assertLess(uncertain.selected_score, certain.selected_score)
        self.assertAlmostEqual(uncertain.confidence, 0.75)
        self.assertLess(uncertain.selected_candidate.score_components.uncertainty, 0.0)

    def test_single_spike_selects_safe_delayed_jump(self) -> None:
        geometry = floor_geometry(Spike(150.0, 0.0, 24.0, 24.0, "single"))
        decision = plan_cube_action(state(), geometry, self.physics)

        self.assertIs(decision.selected_action, CubeAction.JUMP)
        self.assertIsNotNone(decision.jump_delay_frames)
        self.assertTrue(decision.selected_candidate.trajectory.survived_horizon)
        self.assertGreater(decision.selected_candidate.trajectory.minimum_clearance, 0.0)

    def test_two_spikes_select_safe_timing(self) -> None:
        geometry = floor_geometry(
            Spike(150.0, 0.0, 24.0, 24.0, "one"),
            Spike(174.0, 0.0, 24.0, 24.0, "two"),
        )
        decision = plan_cube_action(state(80.0), geometry, self.physics)

        self.assertIs(decision.selected_action, CubeAction.JUMP)
        self.assertTrue(decision.selected_candidate.trajectory.survived_horizon)

    def test_three_clearable_spikes_select_safe_timing(self) -> None:
        geometry = floor_geometry(
            Spike(150.0, 0.0, 24.0, 24.0, "one"),
            Spike(174.0, 0.0, 24.0, 24.0, "two"),
            Spike(198.0, 0.0, 24.0, 24.0, "three"),
        )
        decision = plan_cube_action(state(80.0), geometry, self.physics)

        self.assertIs(decision.selected_action, CubeAction.JUMP)
        self.assertTrue(decision.selected_candidate.trajectory.survived_horizon)
        self.assertEqual(decision.selected_candidate.robustness_safe_fraction, 1.0)

    def test_spike_too_close_reports_all_candidates_unsafe(self) -> None:
        geometry = floor_geometry(Spike(20.0, 0.0, 24.0, 24.0, "unavoidable"))
        decision = plan_cube_action(state(), geometry, self.physics)

        self.assertTrue(decision.all_candidates_unsafe)
        self.assertIsNotNone(decision.predicted_collision)
        self.assertIsNotNone(decision.predicted_time_to_death)
        assert decision.predicted_collision is not None
        self.assertIs(decision.predicted_collision.collision_type, CollisionType.SPIKE)

    def test_all_unsafe_case_maximizes_survival_time(self) -> None:
        geometry = LocalGeometry(
            floors=(FloorSegment(-100.0, 1_000.0),),
            solids=(SolidRect(AABB(150.0, 0.0, 30.0, 300.0), "wall"),),
            spikes=(Spike(80.0, 0.0, 24.0, 24.0, "early"),),
        )
        decision = plan_cube_action(state(), geometry, self.physics)
        durations = [
            item.trajectory.simulated_duration for item in decision.evaluated_candidates
        ]

        self.assertTrue(decision.all_candidates_unsafe)
        self.assertEqual(decision.selected_candidate.trajectory.simulated_duration, max(durations))

    def test_gap_requires_jump(self) -> None:
        geometry = LocalGeometry(
            floors=(FloorSegment(-100.0, 100.0), FloorSegment(200.0, 1_000.0)),
            death_y=-48.0,
        )
        decision = plan_cube_action(state(), geometry, self.physics)

        self.assertIs(decision.selected_action, CubeAction.JUMP)
        self.assertTrue(decision.selected_candidate.trajectory.survived_horizon)
        self.assertIsNotNone(decision.selected_candidate.trajectory.landing_position)

    def test_platform_plan_has_positive_landing_margin(self) -> None:
        geometry = LocalGeometry(
            floors=(FloorSegment(-100.0, 90.0), FloorSegment(280.0, 1_000.0)),
            solids=(SolidRect(AABB(150.0, 40.0, 120.0, 20.0), "platform"),),
            death_y=-48.0,
        )
        decision = plan_cube_action(state(), geometry, self.physics)

        self.assertIs(decision.selected_action, CubeAction.JUMP)
        trajectory = decision.selected_candidate.trajectory
        self.assertTrue(trajectory.landings)
        self.assertGreater(trajectory.landing_margin or 0.0, 0.0)
        self.assertEqual(trajectory.landings[-1].obstacle_id, "platform")
        safe_margins = [
            item.trajectory.landing_margin or 0.0
            for item in decision.evaluated_candidates
            if item.trajectory.survived_horizon
        ]
        self.assertEqual(trajectory.landing_margin, max(safe_margins))

    def test_jump_now_rejected_when_it_lands_on_later_spike(self) -> None:
        geometry = floor_geometry(Spike(150.0, 0.0, 24.0, 24.0, "later"))
        decision = plan_cube_action(state(), geometry, self.physics)
        jump_now = next(
            item for item in decision.evaluated_candidates if item.candidate.jump_delay_frames == 0
        )

        self.assertFalse(jump_now.trajectory.survived_horizon)
        self.assertNotEqual(decision.jump_delay_frames, 0)

    def test_jump_too_late_is_rejected(self) -> None:
        geometry = floor_geometry(Spike(80.0, 0.0, 24.0, 24.0, "soon"))
        decision = plan_cube_action(state(), geometry, self.physics)
        latest = next(
            item for item in decision.evaluated_candidates if item.candidate.jump_delay_frames == 24
        )

        self.assertFalse(latest.trajectory.survived_horizon)
        self.assertTrue(decision.selected_candidate.trajectory.survived_horizon)
        assert decision.jump_delay_frames is not None
        self.assertLess(decision.jump_delay_frames, 24)

    def test_delayed_candidate_checks_collision_before_jump(self) -> None:
        geometry = floor_geometry(Spike(40.0, 0.0, 24.0, 24.0, "immediate"))
        decision = plan_cube_action(state(), geometry, self.physics)
        delayed = next(
            item for item in decision.evaluated_candidates if item.candidate.jump_delay_frames == 24
        )

        self.assertFalse(delayed.trajectory.survived_horizon)
        self.assertFalse(delayed.trajectory.jump_applied)
        assert delayed.trajectory.collision is not None
        self.assertLess(delayed.trajectory.collision.time, 24 * self.physics.time_step)

    def test_timing_robustness_prefers_interior_safe_candidate(self) -> None:
        geometry = floor_geometry(
            Spike(150.0, 0.0, 24.0, 24.0, "one"),
            Spike(174.0, 0.0, 24.0, 24.0, "two"),
            Spike(198.0, 0.0, 24.0, 24.0, "three"),
        )
        config = CubePlannerConfig(
            maximum_jump_delay_frames=18,
            delay_increment_frames=1,
            maximum_candidates=20,
        )
        decision = plan_cube_action(state(80.0), geometry, self.physics, config)
        fragile = [
            item
            for item in decision.evaluated_candidates
            if item.trajectory.survived_horizon and item.robustness_safe_fraction < 1.0
        ]

        self.assertTrue(fragile)
        self.assertEqual(decision.selected_candidate.robustness_safe_fraction, 1.0)
        self.assertGreater(decision.selected_score, max(item.total_score for item in fragile))

    def test_survival_always_beats_dying_candidate(self) -> None:
        geometry = floor_geometry(Spike(150.0, 0.0, 24.0, 24.0, "spike"))
        decision = plan_cube_action(state(), geometry, self.physics)
        safe_scores = [
            item.total_score
            for item in decision.evaluated_candidates
            if item.trajectory.survived_horizon
        ]
        dead_scores = [
            item.total_score
            for item in decision.evaluated_candidates
            if not item.trajectory.survived_horizon
        ]

        self.assertTrue(safe_scores)
        self.assertTrue(dead_scores)
        self.assertGreater(min(safe_scores), max(dead_scores))

    def test_candidate_generation_has_required_and_bounded_actions(self) -> None:
        candidates = generate_cube_candidates(12, 4, 8)
        delays = {candidate.jump_delay_frames for candidate in candidates}

        self.assertLessEqual(len(candidates), 8)
        self.assertIs(candidates[0].action, CubeAction.NO_INPUT)
        self.assertTrue({0, 1, 2, 3}.issubset(delays))

    def test_huge_candidate_request_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "maximum candidates"):
            generate_cube_candidates(10, 1, HARD_MAX_CANDIDATES + 1)
        with self.assertRaisesRegex(ValueError, "candidate count"):
            CubePlannerConfig(maximum_candidates=HARD_MAX_CANDIDATES + 1)
        with self.assertRaisesRegex(ValueError, "jump delay"):
            generate_cube_candidates(10_000_000, 1, 5)

    def test_huge_or_nan_planner_values_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "hard limit"):
            CubePlannerConfig(horizon_seconds=5.1)
        with self.assertRaisesRegex(ValueError, "finite"):
            CubePlannerConfig(clearance_weight=math.nan)
        with self.assertRaisesRegex(ValueError, "obstacle count"):
            CubePlannerConfig(maximum_obstacles=257)

    def test_geometry_processing_is_bounded(self) -> None:
        geometry = LocalGeometry(
            spikes=tuple(
                Spike(float(index * 10), 0.0, 2.0, 2.0, f"spike-{index}")
                for index in range(300)
            )
        )

        self.assertEqual(geometry.nearest(0.0, 32).item_count, 32)
        with self.assertRaisesRegex(ValueError, "hard limit"):
            LocalGeometry(
                spikes=tuple(
                    Spike(float(index), 0.0, 1.0, 1.0, f"item-{index}")
                    for index in range(1_025)
                )
            )

    def test_tiny_geometry_is_stable_and_deterministic(self) -> None:
        geometry = floor_geometry(Spike(80.0, 0.0, 0.001, 0.001, "tiny"))

        first = plan_cube_action(state(), geometry, self.physics)
        second = plan_cube_action(state(), geometry, self.physics)

        self.assertEqual(first, second)
        self.assertTrue(math.isfinite(first.selected_score))

    def test_invalid_action_enum_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid cube action"):
            CubeActionCandidate("jump", 0)  # type: ignore[arg-type]

    def test_repeated_calls_are_identical(self) -> None:
        geometry = floor_geometry(Spike(80.0, 0.0, 24.0, 24.0, "same"))
        original_state = state()

        first = plan_cube_action(original_state, geometry, self.physics)
        second = plan_cube_action(original_state, geometry, self.physics)

        self.assertEqual(first, second)
        self.assertEqual(original_state, state())

    def test_survival_priority_holds_at_score_weight_bounds(self) -> None:
        geometry = floor_geometry(Spike(150.0, 0.0, 24.0, 24.0, "weighted"))
        config = CubePlannerConfig(
            clearance_weight=10.0,
            landing_margin_weight=20.0,
            uncertainty_weight=1_000.0,
            unnecessary_jump_penalty=3_000.0,
        )

        decision = plan_cube_action(state(), geometry, self.physics, config)

        self.assertTrue(decision.selected_candidate.trajectory.survived_horizon)

    def test_dead_cube_returns_well_defined_unsafe_plan(self) -> None:
        decision = plan_cube_action(state(alive=False), floor_geometry(), self.physics)

        self.assertTrue(decision.all_candidates_unsafe)
        self.assertIsNotNone(decision.predicted_collision)
        self.assertEqual(decision.predicted_time_to_death, 0.0)


if __name__ == "__main__":
    unittest.main()
