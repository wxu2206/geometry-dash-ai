from __future__ import annotations

import unittest

from geometry_dash_ai.simulation import (
    Action,
    GameMode,
    SimulationStatus,
    Simulator,
    scenario_catalog,
)
from geometry_dash_ai.simulation.render import render_step
from geometry_dash_ai.vision import ClassicalGeometryDetector, ClassicalPlayerDetector


class SyntheticScenarioTests(unittest.TestCase):
    def test_catalog_is_unique_and_perception_uses_only_rendered_pixels(self) -> None:
        scenarios = scenario_catalog()
        self.assertEqual(len({scenario.name for scenario in scenarios}), len(scenarios))
        player_detector = ClassicalPlayerDetector()
        geometry_detector = ClassicalGeometryDetector()
        for scenario in scenarios:
            with self.subTest(scenario=scenario.name):
                simulator = Simulator(scenario.level, initial_state=scenario.initial_state)
                result = simulator.reset()
                rendered = render_step(result, scenario.level, 0, 1_000_000_000)
                player = player_detector.detect(rendered)
                geometry = geometry_detector.detect(rendered, player)
                self.assertIsNotNone(player)
                self.assertGreaterEqual(len(geometry.floors), 1)
                self.assertEqual(bool(geometry.spikes), scenario.expect_spike)

    def test_transition_scenario_exposes_declared_modes_through_simulation(self) -> None:
        scenario = next(item for item in scenario_catalog() if item.name == "cube_ship_cube")
        simulator = Simulator(scenario.level, initial_state=scenario.initial_state)
        transitions = []
        result = simulator.reset()
        for _ in range(200):
            action = Action.HOLD if result.state.mode is GameMode.SHIP else Action.RELEASE
            result = simulator.step(action)
            transitions.extend(result.transitions)
            if result.status is not SimulationStatus.RUNNING:
                break
        self.assertEqual(tuple(transitions), scenario.transitions)


if __name__ == "__main__":
    unittest.main()
