from __future__ import annotations

import math
import unittest

from geometry_dash_ai.physics import (
    AABB,
    FloorSegment,
    LocalGeometry,
    ShipPhysicsParameters,
    ShipState,
    SolidRect,
)
from geometry_dash_ai.physics.ship import simulate_ship_trajectory
from geometry_dash_ai.planning import ShipPlannerConfig, plan_ship_action


class ShipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.physics = ShipPhysicsParameters()
        self.corridor = LocalGeometry(
            floors=(FloorSegment(-100.0, 1_000.0),),
            death_y=-50.0,
        )
        self.ship = ShipState(0.0, 80.0, 180.0, 0.0, 20.0, 16.0, False)

    def test_hold_rises_and_release_falls(self) -> None:
        held = simulate_ship_trajectory(self.ship, self.corridor, self.physics, (True,), 4)
        released = simulate_ship_trajectory(self.ship, self.corridor, self.physics, (False,), 4)
        self.assertGreater(held.samples[-1].y, self.ship.y)
        self.assertLess(released.samples[-1].y, self.ship.y)

    def test_floor_and_solid_collisions_are_detected(self) -> None:
        floor_ship = ShipState(0.0, 0.5, 100.0, -100.0, 20.0, 16.0, False)
        result = simulate_ship_trajectory(floor_ship, self.corridor, self.physics, (False,), 1)
        self.assertFalse(result.survived)
        self.assertEqual(result.collision_kind, "floor")
        ceiling = LocalGeometry(
            floors=(FloorSegment(-100.0, 1_000.0),),
            solids=(SolidRect(AABB(-100.0, 95.0, 1_000.0, 10.0), "ceiling"),),
            death_y=-50.0,
        )
        result = simulate_ship_trajectory(self.ship, ceiling, self.physics, (True,), 1)
        self.assertFalse(result.survived)
        self.assertEqual(result.collision_kind, "solid")

    def test_mpc_is_bounded_and_deterministic(self) -> None:
        config = ShipPlannerConfig(segments=5, segment_steps=2, maximum_candidates=12)
        first = plan_ship_action(self.ship, self.corridor, self.physics, config)
        second = plan_ship_action(self.ship, self.corridor, self.physics, config)
        self.assertEqual(first.hold, second.hold)
        self.assertEqual(len(first.candidates), 12)
        self.assertLessEqual(len(first.candidates), config.maximum_candidates)
        self.assertTrue(math.isfinite(first.selected_score))

    def test_hysteresis_preserves_safe_current_action(self) -> None:
        held_ship = ShipState(0.0, 80.0, 180.0, 0.0, 20.0, 16.0, True)
        decision = plan_ship_action(
            held_ship,
            self.corridor,
            self.physics,
            ShipPlannerConfig(hysteresis_margin=100.0),
        )
        self.assertTrue(decision.hold)

    def test_non_finite_state_and_unbounded_horizon_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ShipState(0.0, math.nan, 1.0, 0.0, 20.0, 16.0, False)
        with self.assertRaises(ValueError):
            ShipPlannerConfig(segments=6)
        with self.assertRaises(ValueError):
            simulate_ship_trajectory(self.ship, self.corridor, self.physics, (True,) * 9, 1)


if __name__ == "__main__":
    unittest.main()
