import unittest

from geometry_dash_ai.simulation import (
    Action,
    FloorSegment,
    GameMode,
    Level,
    ModePortal,
    PlayerState,
    SimulationConfig,
    SimulationStatus,
    Simulator,
    Spike,
)


class SimulationTests(unittest.TestCase):
    def test_cube_moves_and_remains_on_floor(self) -> None:
        level = Level(length=100.0, floor=(FloorSegment(0.0, 100.0),))
        simulator = Simulator(level)
        result = simulator.step()

        self.assertIs(result.status, SimulationStatus.RUNNING)
        self.assertAlmostEqual(result.state.x, 3.0)
        self.assertEqual(result.state.y, 0.0)
        self.assertTrue(result.state.grounded)

    def test_cube_jump_follows_gravity_and_lands(self) -> None:
        level = Level(length=2_000.0, floor=(FloorSegment(0.0, 2_000.0),))
        simulator = Simulator(level)
        first = simulator.step(Action.PRESS)

        self.assertGreater(first.state.y, 0)
        self.assertLess(first.state.vy, simulator.config.cube_jump_velocity)
        result = simulator.step(Action.RELEASE)
        for _ in range(120):
            result = simulator.step(Action.NONE)
            if result.state.grounded:
                break

        self.assertIs(result.status, SimulationStatus.RUNNING)
        self.assertTrue(result.state.grounded)
        self.assertEqual(result.state.y, 0.0)

    def test_spike_causes_terminal_collision(self) -> None:
        level = Level(
            length=500.0,
            floor=(FloorSegment(0.0, 500.0),),
            spikes=(Spike(40.0, 0.0),),
        )
        simulator = Simulator(level)
        result = simulator.step()
        while result.status is SimulationStatus.RUNNING:
            result = simulator.step()

        self.assertIs(result.status, SimulationStatus.DEAD)
        self.assertIsNotNone(result.collision)
        assert result.collision is not None
        self.assertEqual(result.collision.kind, "spike")

    def test_gap_causes_death(self) -> None:
        level = Level(length=400.0, floor=(FloorSegment(0.0, 45.0),))
        simulator = Simulator(level)
        result = simulator.step()
        while result.status is SimulationStatus.RUNNING:
            result = simulator.step()

        self.assertIs(result.status, SimulationStatus.DEAD)
        self.assertIsNotNone(result.collision)
        assert result.collision is not None
        self.assertEqual(result.collision.kind, "gap")

    def test_portal_switches_to_ship_and_ship_hold_accelerates_upward(self) -> None:
        level = Level(
            length=500.0,
            floor=(FloorSegment(0.0, 500.0),),
            portals=(ModePortal(3.0, GameMode.SHIP),),
        )
        initial = PlayerState(y=100.0, grounded=False)
        simulator = Simulator(level, initial_state=initial)
        transition = simulator.step(Action.HOLD)
        next_step = simulator.step(Action.HOLD)

        self.assertEqual(transition.transitions, (GameMode.SHIP,))
        self.assertIs(next_step.state.mode, GameMode.SHIP)
        self.assertGreater(next_step.state.vy, transition.state.vy)

    def test_level_completion_is_terminal(self) -> None:
        config = SimulationConfig(horizontal_speed=60.0, step_seconds=1 / 60)
        level = Level(length=2.0, floor=(FloorSegment(0.0, 10.0),))
        simulator = Simulator(level, config=config)

        self.assertIs(simulator.step().status, SimulationStatus.RUNNING)
        self.assertIs(simulator.step().status, SimulationStatus.COMPLETE)
        with self.assertRaisesRegex(RuntimeError, "reset"):
            simulator.step()

    def test_camera_keeps_player_at_configured_screen_position(self) -> None:
        config = SimulationConfig(player_screen_x=10.0)
        level = Level(length=500.0, floor=(FloorSegment(0.0, 500.0),))
        simulator = Simulator(level, config=config)
        for _ in range(10):
            result = simulator.step()

        self.assertGreater(result.camera_x, 0)
        self.assertAlmostEqual(result.screen_x, 10.0)


if __name__ == "__main__":
    unittest.main()
