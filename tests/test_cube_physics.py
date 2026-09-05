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
    simulate_cube_trajectory,
)
from geometry_dash_ai.physics.geometry import (
    spike_intersects_aabb,
    swept_spike_collision_time,
)


def cube_state(
    *,
    x: float = 0.0,
    y: float = 0.0,
    vy: float = 0.0,
    grounded: bool = True,
    alive: bool = True,
) -> CubeState:
    return CubeState(x, y, 180.0, vy, 24.0, 24.0, grounded, alive)


class CubePhysicsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.physics = CubePhysicsParameters()
        self.floor = LocalGeometry(floors=(FloorSegment(-100.0, 1_000.0),))

    def test_fixed_step_motion_is_deterministic(self) -> None:
        first = simulate_cube_trajectory(cube_state(), self.floor, self.physics, 0.5, 0)
        second = simulate_cube_trajectory(cube_state(), self.floor, self.physics, 0.5, 0)

        self.assertEqual(first, second)
        self.assertAlmostEqual(first.samples[1].simulation_time, self.physics.time_step)
        self.assertAlmostEqual(first.samples[1].x, 3.0)

    def test_side_collision_is_fatal(self) -> None:
        geometry = LocalGeometry(
            floors=(FloorSegment(-100.0, 1_000.0),),
            solids=(SolidRect(AABB(40.0, 0.0, 30.0, 48.0), "block"),),
        )
        result = simulate_cube_trajectory(cube_state(), geometry, self.physics, 0.3, None)

        self.assertFalse(result.survived_horizon)
        self.assertIsNotNone(result.collision)
        assert result.collision is not None
        self.assertIs(result.collision.collision_type, CollisionType.SOLID_SIDE)

    def test_landing_on_block_is_safe_and_has_margin(self) -> None:
        geometry = LocalGeometry(
            floors=(FloorSegment(-100.0, 1_000.0),),
            solids=(SolidRect(AABB(0.0, 0.0, 140.0, 48.0), "platform"),),
        )
        state = cube_state(x=10.0, y=80.0, vy=-100.0, grounded=False)
        result = simulate_cube_trajectory(state, geometry, self.physics, 0.3, None)

        self.assertTrue(result.survived_horizon)
        self.assertTrue(result.landings)
        landing = result.landings[0]
        self.assertEqual(landing.obstacle_id, "platform")
        self.assertEqual(landing.y, 48.0)
        self.assertGreater(landing.margin, 0.0)

    def test_underside_collision_is_fatal(self) -> None:
        geometry = LocalGeometry(
            floors=(FloorSegment(-100.0, 1_000.0),),
            solids=(SolidRect(AABB(0.0, 42.0, 100.0, 20.0), "ceiling-block"),),
        )
        result = simulate_cube_trajectory(cube_state(), geometry, self.physics, 0.3, 0)

        self.assertFalse(result.survived_horizon)
        assert result.collision is not None
        self.assertIs(result.collision.collision_type, CollisionType.SOLID_UNDERSIDE)

    def test_swept_solid_collision_prevents_tunneling(self) -> None:
        fast_physics = CubePhysicsParameters(
            horizontal_speed=5_000.0,
            time_step=0.05,
            maximum_simulation_duration=1.0,
        )
        geometry = LocalGeometry(
            floors=(FloorSegment(-100.0, 1_000.0),),
            solids=(SolidRect(AABB(100.0, 0.0, 0.1, 50.0), "thin-block"),),
        )
        result = simulate_cube_trajectory(cube_state(), geometry, fast_physics, 0.05, None)

        assert result.collision is not None
        self.assertIs(result.collision.collision_type, CollisionType.SOLID_SIDE)
        self.assertLess(result.collision.x, 100.0)

    def test_triangle_spike_center_collision(self) -> None:
        spike = Spike(0.0, 0.0, 24.0, 24.0)
        self.assertTrue(spike_intersects_aabb(spike, AABB(8.0, 0.0, 8.0, 8.0)))

    def test_triangle_spike_grazing_bounding_box_is_safe(self) -> None:
        spike = Spike(0.0, 0.0, 24.0, 24.0)
        grazing_box = AABB(0.0, 20.0, 3.0, 3.0)

        self.assertFalse(spike_intersects_aabb(spike, grazing_box))

    def test_cube_can_clear_spike(self) -> None:
        geometry = LocalGeometry(
            floors=(FloorSegment(-100.0, 1_000.0),),
            spikes=(Spike(80.0, 0.0, 24.0, 24.0, "spike"),),
        )
        result = simulate_cube_trajectory(cube_state(), geometry, self.physics, 1.0, 6)

        self.assertTrue(result.survived_horizon)
        self.assertGreater(result.minimum_clearance, 0.0)

    def test_swept_spike_collision_prevents_tunneling(self) -> None:
        spike = Spike(0.0, 0.0, 24.0, 24.0)
        start = AABB(-50.0, 0.0, 24.0, 24.0)
        end = AABB(100.0, 0.0, 24.0, 24.0)

        collision_fraction = swept_spike_collision_time(spike, start, end)

        self.assertIsNotNone(collision_fraction)
        assert collision_fraction is not None
        self.assertGreaterEqual(collision_fraction, 0.0)
        self.assertLessEqual(collision_fraction, 1.0)

    def test_gap_is_fatal(self) -> None:
        geometry = LocalGeometry(floors=(FloorSegment(-100.0, 30.0),), death_y=-24.0)
        result = simulate_cube_trajectory(cube_state(), geometry, self.physics, 1.0, None)

        self.assertFalse(result.survived_horizon)
        assert result.collision is not None
        self.assertIs(result.collision.collision_type, CollisionType.GAP)

    def test_jump_can_land_between_spike_groups(self) -> None:
        geometry = LocalGeometry(
            floors=(FloorSegment(-100.0, 1_000.0),),
            spikes=(
                Spike(80.0, 0.0, 24.0, 24.0, "first"),
                Spike(220.0, 0.0, 24.0, 24.0, "second"),
            ),
        )
        result = simulate_cube_trajectory(cube_state(), geometry, self.physics, 0.9, 0)

        self.assertTrue(result.survived_horizon)
        self.assertTrue(result.landings)
        assert result.landing_position is not None
        self.assertGreater(result.landing_position[0], 104.0)
        self.assertLess(result.landing_position[0], 220.0)

    def test_dead_initial_state_has_explicit_collision(self) -> None:
        result = simulate_cube_trajectory(
            cube_state(alive=False), self.floor, self.physics, 0.5, None
        )

        self.assertFalse(result.survived_horizon)
        self.assertEqual(len(result.samples), 1)
        assert result.collision is not None
        self.assertIs(result.collision.collision_type, CollisionType.ALREADY_DEAD)

    def test_invalid_numeric_and_geometry_input_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite"):
            cube_state(x=math.nan)
        with self.assertRaisesRegex(ValueError, "finite"):
            CubePhysicsParameters(gravity=math.inf)
        with self.assertRaisesRegex(ValueError, "bounds"):
            cube_state(x=10**10_000)
        with self.assertRaisesRegex(ValueError, "positive"):
            AABB(0.0, 0.0, -1.0, 2.0)
        with self.assertRaisesRegex(ValueError, "positive"):
            CubeState(0.0, 0.0, 0.0, 0.0, 0.0, 2.0, True)
        with self.assertRaisesRegex(ValueError, "positive"):
            Spike(0.0, 0.0, 0.0, 2.0)
        with self.assertRaisesRegex(ValueError, "greater"):
            FloorSegment(10.0, 10.0)
        with self.assertRaisesRegex(ValueError, "tuple"):
            LocalGeometry(floors=[])  # type: ignore[arg-type]

    def test_invalid_horizons_and_excessive_steps_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            simulate_cube_trajectory(cube_state(), self.floor, self.physics, -0.1, None)
        long_physics = CubePhysicsParameters(maximum_simulation_duration=5.0)
        with self.assertRaisesRegex(ValueError, "maximum"):
            simulate_cube_trajectory(cube_state(), self.floor, long_physics, 5.1, None)
        tiny_step = CubePhysicsParameters(
            time_step=0.0001,
            maximum_simulation_duration=1.0,
        )
        with self.assertRaisesRegex(ValueError, "1200"):
            simulate_cube_trajectory(cube_state(), self.floor, tiny_step, 0.2, None)

    def test_finite_input_produces_finite_ordered_states(self) -> None:
        result = simulate_cube_trajectory(cube_state(), self.floor, self.physics, 1.0, 4)

        previous_time = -1.0
        for state in result.samples:
            kinematics = (state.x, state.y, state.vx, state.vy)
            self.assertTrue(all(math.isfinite(value) for value in kinematics))
            self.assertGreater(state.width, 0.0)
            self.assertGreater(state.height, 0.0)
            self.assertGreaterEqual(state.simulation_time, previous_time)
            previous_time = state.simulation_time


if __name__ == "__main__":
    unittest.main()
